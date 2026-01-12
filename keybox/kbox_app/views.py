from django.shortcuts import render, redirect
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Q
from django.contrib import messages
from functools import wraps
from datetime import datetime

from .models import (
    TransactionLog, Room, RoomSchedule, RFIDRegistration, 
    UserProfile, Faculty, SystemSettings
)
from .forms import (
    SemesterChoiceForm,
    RFIDRegistrationForm,
    CustomUserRegistrationForm,
    EmailAuthenticationForm,
)
from .models import (
    TransactionLog, Room, RoomSchedule, RFIDRegistration, 
    UserProfile, Faculty, SystemSettings, ESP32Device  # Add ESP32Device here
)


# ---------- Custom Decorators ----------
def staff_or_superuser_required(view_func):
    """
    Decorator to allow access to staff users or superusers
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        
        try:
            if request.user.profile.user_type == 'staff':
                return view_func(request, *args, **kwargs)
        except UserProfile.DoesNotExist:
            pass
        
        return HttpResponseForbidden("Access denied. Staff or admin privileges required.")
    
    return wrapper


def client_required(view_func):
    """
    Decorator for client-only views (NOT USED - Faculty don't login)
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        try:
            if request.user.profile.user_type == 'client':
                return view_func(request, *args, **kwargs)
        except UserProfile.DoesNotExist:
            pass
        
        return HttpResponseForbidden("Access denied. Client access required.")
    
    return wrapper


# ---------- helper for dynamic Academic Year + Semester choices ----------
def get_term_choices():
    """
    Always show 5 academic years and all semesters.
    """
    current_year = datetime.now().year
    ay_values = [
        f"{current_year + i}-{current_year + i + 1}"
        for i in range(5)
    ]

    sem_values = ["1st", "2nd", "summer", "summer2"]
    ay_choices = [(ay, ay) for ay in ay_values]

    def sem_label(s):
        labels = {
            "1st": "1st Semester",
            "2nd": "2nd Semester",
            "summer": "Summer",
            "summer2": "Summer 2"
        }
        return labels.get(s, s)

    sem_choices = [(s, sem_label(s)) for s in sem_values]
    return ay_choices, sem_choices


def register_view(request):
    """
    Public registration page - Creates STAFF accounts only
    """
    if request.method == 'POST':
        form = CustomUserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, 'Staff account created successfully! You can now login.')
            return redirect('login')
    else:
        form = CustomUserRegistrationForm()
    return render(request, 'kbox_app/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # Only allow staff and superusers to login
            if user.is_superuser:
                return redirect('dashboard')
            
            try:
                if user.profile.user_type == 'staff':
                    return redirect('dashboard')
                else:
                    # Clients/Faculty cannot login
                    logout(request)
                    messages.error(request, 'Only staff members can access this system.')
                    return redirect('login')
            except UserProfile.DoesNotExist:
                return redirect('dashboard')
    else:
        form = EmailAuthenticationForm(request)
    
    return render(request, 'kbox_app/login.html', {'form': form})


def logout_view(request):
    """
    Logout view
    """
    logout(request)
    return redirect('login')


@staff_or_superuser_required
def dashboard(request):
    """
    Dashboard - STAFF AND ADMIN ONLY
    Now updates SystemSettings when semester is changed
    """
    ay_choices, sem_choices = get_term_choices()
    
    # Get current system settings
    system_settings = SystemSettings.get_current_term()

    if request.method == "POST":
        semester_form = SemesterChoiceForm(
            request.POST,
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )
        if semester_form.is_valid():
            selected_ay = semester_form.cleaned_data["academic_year"]
            selected_semester = semester_form.cleaned_data["semester"]
            
            # Save to session
            request.session["selected_ay"] = selected_ay
            request.session["selected_semester"] = selected_semester
            
            # ========== UPDATE SYSTEM-WIDE SETTINGS FOR RFID ==========
            system_settings.current_academic_year = selected_ay
            system_settings.current_semester = selected_semester
            system_settings.save()
            messages.success(request, f'System semester updated to {selected_semester} {selected_ay}')
            # ===========================================================
        
        # Handle room filter submission
        if "room" in request.POST:
            request.session["selected_room_code"] = request.POST.get("room", "all")

    else:
        selected_ay = request.session.get("selected_ay") or system_settings.current_academic_year
        selected_semester = request.session.get("selected_semester") or system_settings.current_semester
        selected_room_code = request.session.get("selected_room_code", "all")
        semester_form = SemesterChoiceForm(
            initial={"academic_year": selected_ay, "semester": selected_semester},
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )

    selected_ay = request.session.get("selected_ay") or system_settings.current_academic_year
    selected_semester = request.session.get("selected_semester") or system_settings.current_semester
    selected_room_code = request.session.get("selected_room_code", "all")

    # Transaction logs
    transaction_logs = (
        TransactionLog.objects
        .filter(academic_year=selected_ay, semester=selected_semester)
        .select_related("rfid", "rfid__faculty", "room")
        .order_by("-open_time")
    )

    if selected_room_code != "all":
        transaction_logs = transaction_logs.filter(room__code=selected_room_code)

    # Stats
    total_logs = transaction_logs.count()
    logs_today = transaction_logs.filter(open_time__date=timezone.now().date()).count()
    active_rooms = transaction_logs.values("room").distinct().count()
    faculty_count = transaction_logs.values("rfid__faculty__full_name").distinct().count()

    # Rooms
    rooms = Room.objects.all().order_by("code")

    # Show schedules for selected semester
    if selected_room_code != "all":
        current_schedules = RoomSchedule.objects.filter(
            room__code=selected_room_code,
            semester=selected_semester
        ).select_related("room", "faculty").order_by("day_of_week", "start_time")
    else:
        current_schedules = RoomSchedule.objects.filter(
            semester=selected_semester
        ).select_related(
            "room", "faculty"
        ).order_by("room__code", "day_of_week", "start_time")

    ctx = {
        "semester_form": semester_form,
        "transaction_logs": transaction_logs,
        "total_logs": total_logs,
        "faculty_count": faculty_count,
        "logs_today": logs_today,
        "active_rooms": active_rooms,
        "rooms": rooms,
        "selected_room_code": selected_room_code,
        "current_schedules": current_schedules,
        "user_type": 'superuser' if request.user.is_superuser else 'staff',
        "can_see_names": True,
    }
    return render(request, "kbox_app/dashboard.html", ctx)


@staff_or_superuser_required
def rfid_register(request):
    """
    Admin page to register new RFID cards.
    """
    success = False

    if request.method == "POST":
        form = RFIDRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            success = True
            form = RFIDRegistrationForm()
    else:
        form = RFIDRegistrationForm()

    ctx = {"form": form, "success": success}
    return render(request, "kbox_app/rfid_register.html", ctx)


@staff_or_superuser_required
def reports(request):
    """
    Semestral report page - STAFF ONLY
    """
    ay_choices, sem_choices = get_term_choices()

    if request.method == "POST":
        form = SemesterChoiceForm(
            request.POST,
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )
        if form.is_valid():
            ay = form.cleaned_data["academic_year"]
            sem = form.cleaned_data["semester"]
        else:
            ay = ay_choices[0][0]
            sem = sem_choices[0][0]
    else:
        ay = ay_choices[0][0]
        sem = sem_choices[0][0]
        form = SemesterChoiceForm(
            initial={"academic_year": ay, "semester": sem},
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )

    logs = (
        TransactionLog.objects
        .filter(academic_year=ay, semester=sem)
        .select_related("rfid", "rfid__faculty", "room")
    )

    faculty_summary = (
        logs.values("rfid__faculty__full_name")
        .annotate(total_sessions=Count("id"))
        .order_by("rfid__faculty__full_name")
    )

    room_summary = (
        logs.values("room__code")
        .annotate(total_sessions=Count("id"))
        .order_by("room__code")
    )

    ctx = {
        "form": form,
        "academic_year": ay,
        "semester": sem,
        "faculty_summary": faculty_summary,
        "room_summary": room_summary,
        "total_logs": logs.count(),
    }
    return render(request, "kbox_app/reports.html", ctx)


# ---------- RFID SWIPE API with Schedule Checking ----------
# Replace your rfid_swipe function in views.py with this FIXED version

@csrf_exempt
def rfid_swipe(request):
    """
    API for Arduino/keybox with schedule validation.
    UPDATED: Matches Arduino's expected JSON response format
    """
    code = request.GET.get("code") or request.POST.get("code")
    room_code = request.GET.get("room") or request.POST.get("room")

    # Validate parameters
    if not code or not room_code:
        return JsonResponse(
            {
                "status": "error",
                "access_granted": False,
                "action": "",
                "faculty": "",
                "message": "Missing 'code' or 'room' parameter",
                "denial_reason": "Invalid request - missing required parameters"
            },
            status=400,
        )

    # Get RFID registration
    try:
        rfid = RFIDRegistration.objects.select_related("faculty").get(rfid_code=code)
    except RFIDRegistration.DoesNotExist:
        print(f"DEBUG: RFID code '{code}' not found in database")
        return JsonResponse(
            {
                "status": "error",
                "access_granted": False,
                "action": "",
                "faculty": "",
                "message": "RFID card not registered",
                "denial_reason": "Card UID not found in database"
            },
            status=404
        )

    # Check if RFID is active
    if not rfid.is_active:
        print(f"DEBUG: RFID card {code} is disabled")
        return JsonResponse(
            {
                "status": "error",
                "access_granted": False,
                "action": "",
                "faculty": rfid.faculty.full_name,
                "message": "RFID card is disabled",
                "denial_reason": "This card has been deactivated"
            },
            status=403
        )

    # Get room
    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        print(f"DEBUG: Room code '{room_code}' not found")
        return JsonResponse(
            {
                "status": "error",
                "access_granted": False,
                "action": "",
                "faculty": rfid.faculty.full_name,
                "message": "Unknown room code",
                "denial_reason": f"Room {room_code} not found in system"
            },
            status=404
        )

    # Check if room is active
    if not room.is_active:
        print(f"DEBUG: Room {room_code} is disabled")
        return JsonResponse(
            {
                "status": "error",
                "access_granted": False,
                "action": "",
                "faculty": rfid.faculty.full_name,
                "message": "Room is disabled",
                "denial_reason": f"Room {room_code} is currently inactive"
            },
            status=403
        )

    # Get current time and system settings
    now = timezone.localtime(timezone.now())
    current_day_full = now.strftime("%A").lower()  # monday, tuesday, etc.
    current_time = now.time()

    # GET SEMESTER FROM SYSTEM SETTINGS
    system_settings = SystemSettings.get_current_term()
    semester = system_settings.current_semester
    academic_year = system_settings.current_academic_year

    print(f"\n{'='*60}")
    print(f"DEBUG: RFID SWIPE ATTEMPT")
    print(f"{'='*60}")
    print(f"RFID Code: {code}")
    print(f"Faculty: {rfid.faculty.full_name}")
    print(f"Room: {room.code}")
    print(f"Current Time: {now.strftime('%A, %I:%M %p')}")
    print(f"Current Day (lowercase): {current_day_full}")
    print(f"Current Time (HH:MM): {current_time}")
    print(f"System Semester: {semester}")
    print(f"System Academic Year: {academic_year}")
    print(f"{'='*60}\n")

    # Check if faculty has a schedule for this room at this time
    # Better day matching - check both full name and abbreviation
    day_matches = [
        current_day_full,  # "monday"
        current_day_full[:3],  # "mon"
        current_day_full.capitalize(),  # "Monday"
    ]
    
    print(f"Looking for schedules with day in: {day_matches}")
    
    # Get ALL schedules for this faculty/room/semester first
    all_schedules_for_faculty = RoomSchedule.objects.filter(
        room=room,
        faculty=rfid.faculty,
        semester=semester,
        is_active=True
    )
    
    print(f"Total schedules found for {rfid.faculty.full_name} in {room.code}: {all_schedules_for_faculty.count()}")
    for s in all_schedules_for_faculty:
        print(f"  - Days: '{s.day_of_week}' | Time: {s.start_time}-{s.end_time} | Semester: {s.semester}")

    # Now filter by day and time
    matching_schedules = RoomSchedule.objects.filter(
        room=room,
        faculty=rfid.faculty,
        semester=semester,
        is_active=True
    )

    # Better day checking
    matching_schedules_filtered = []
    for schedule in matching_schedules:
        days_list = [d.strip().lower() for d in schedule.day_of_week.split(',')]
        day_match = any(day in days_list for day in day_matches)
        time_match = schedule.start_time <= current_time <= schedule.end_time
        
        print(f"Checking schedule {schedule.id}:")
        print(f"  - Days stored: {days_list}")
        print(f"  - Day match: {day_match}")
        print(f"  - Time match: {time_match} ({schedule.start_time} <= {current_time} <= {schedule.end_time})")
        
        if day_match and time_match:
            matching_schedules_filtered.append(schedule)

    access_granted = len(matching_schedules_filtered) > 0
    denial_reason = None
    active_schedule = matching_schedules_filtered[0] if access_granted else None

    if not access_granted:
        # Check for day match but time mismatch
        day_only_match = False
        for schedule in matching_schedules:
            days_list = [d.strip().lower() for d in schedule.day_of_week.split(',')]
            if any(day in days_list for day in day_matches):
                day_only_match = True
                break
        
        if day_only_match:
            denial_reason = f"Outside of scheduled time (Current: {current_time.strftime('%I:%M %p')})"
        else:
            denial_reason = f"No schedule for {current_day_full.capitalize()} in {semester} semester"

    print(f"Access Granted: {access_granted}")
    print(f"Denial Reason: {denial_reason}")
    print(f"{'='*60}\n")

    # Check for existing open log (determine if borrowing or returning)
    open_log = (
        TransactionLog.objects
        .filter(
            rfid=rfid,
            room=room,
            academic_year=academic_year,
            semester=semester,
            close_time__isnull=True,
            access_granted=True
        )
        .order_by("-open_time")
        .first()
    )

    # Determine action and create/update log
    if access_granted:
        if open_log:
            # Returning key
            open_log.close_time = now
            open_log.save()
            action = "return_key"
            message = "Key returned successfully"
            access_granted = True
            print(f"✓ Closed log ID={open_log.id}")
        else:
            # Borrowing key
            new_log = TransactionLog.objects.create(
                rfid=rfid,
                room=room,
                academic_year=academic_year,
                semester=semester,
                open_time=now,
                access_granted=True,
                schedule=active_schedule
            )
            action = "borrow_key"
            message = "Access granted - Key released"
            print(f"✓ Created new log ID={new_log.id}")
    else:
        # Access denied - still log the attempt
        denied_log = TransactionLog.objects.create(
            rfid=rfid,
            room=room,
            academic_year=academic_year,
            semester=semester,
            open_time=now,
            access_granted=False,
            denial_reason=denial_reason
        )
        action = ""
        message = f"Access denied: {denial_reason}"
        print(f"✗ Access DENIED - Reason: {denial_reason}")

    # Return response in Arduino's expected format
    return JsonResponse(
        {
            "status": "ok" if access_granted else "error",
            "access_granted": access_granted,
            "action": action,
            "faculty": rfid.faculty.full_name,
            "message": message,
            "denial_reason": denial_reason if not access_granted else ""
        },
        status=200  # Always return 200 for valid requests, Arduino checks access_granted flag
    )

@staff_or_superuser_required
def transaction_logs(request):
    """
    Transaction Logs page - ONLY SUCCESSFUL ACCESS
    This is the main transaction logs page - clean and simple
    """
    ay_choices, sem_choices = get_term_choices()
    system_settings = SystemSettings.get_current_term()

    if request.method == "POST":
        semester_form = SemesterChoiceForm(
            request.POST,
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )
        if semester_form.is_valid():
            selected_ay = semester_form.cleaned_data["academic_year"]
            selected_semester = semester_form.cleaned_data["semester"]
            request.session["selected_ay"] = selected_ay
            request.session["selected_semester"] = selected_semester
        
        if "room" in request.POST:
            request.session["selected_room_code"] = request.POST.get("room", "all")
    else:
        selected_ay = request.session.get("selected_ay") or system_settings.current_academic_year
        selected_semester = request.session.get("selected_semester") or system_settings.current_semester
        selected_room_code = request.session.get("selected_room_code", "all")
        semester_form = SemesterChoiceForm(
            initial={"academic_year": selected_ay, "semester": selected_semester},
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )

    selected_ay = request.session.get("selected_ay") or system_settings.current_academic_year
    selected_semester = request.session.get("selected_semester") or system_settings.current_semester
    selected_room_code = request.session.get("selected_room_code", "all")

    # Get transaction logs - ONLY SUCCESSFUL ACCESS
    logs = (
        TransactionLog.objects
        .filter(
            academic_year=selected_ay, 
            semester=selected_semester,
            access_granted=True  # ✅ Only successful
        )
        .select_related("rfid", "rfid__faculty", "room")
        .order_by("-open_time")
    )

    if selected_room_code != "all":
        logs = logs.filter(room__code=selected_room_code)

    # Get rooms for filter
    rooms = Room.objects.all().order_by("code")
    
    # Get counts
    total_granted = TransactionLog.objects.filter(
        academic_year=selected_ay, 
        semester=selected_semester,
        access_granted=True
    ).count()
    
    total_denied = TransactionLog.objects.filter(
        academic_year=selected_ay, 
        semester=selected_semester,
        access_granted=False
    ).count()

    ctx = {
        "semester_form": semester_form,
        "transaction_logs": logs,
        "rooms": rooms,
        "selected_room_code": selected_room_code,
        "total_granted": total_granted,
        "total_denied": total_denied,
        "can_see_names": True,
    }
    return render(request, "kbox_app/transaction_logs.html", ctx)


@staff_or_superuser_required
def denied_access_logs(request):
    """
    NEW PAGE: Denied Access Logs - ONLY FAILED ATTEMPTS
    Separate security monitoring page
    """
    ay_choices, sem_choices = get_term_choices()
    system_settings = SystemSettings.get_current_term()

    if request.method == "POST":
        semester_form = SemesterChoiceForm(
            request.POST,
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )
        if semester_form.is_valid():
            selected_ay = semester_form.cleaned_data["academic_year"]
            selected_semester = semester_form.cleaned_data["semester"]
            request.session["denied_logs_ay"] = selected_ay
            request.session["denied_logs_semester"] = selected_semester
        
        if "room" in request.POST:
            request.session["denied_logs_room"] = request.POST.get("room", "all")
    else:
        selected_ay = request.session.get("denied_logs_ay") or system_settings.current_academic_year
        selected_semester = request.session.get("denied_logs_semester") or system_settings.current_semester
        selected_room_code = request.session.get("denied_logs_room", "all")
        semester_form = SemesterChoiceForm(
            initial={"academic_year": selected_ay, "semester": selected_semester},
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )

    selected_ay = request.session.get("denied_logs_ay") or system_settings.current_academic_year
    selected_semester = request.session.get("denied_logs_semester") or system_settings.current_semester
    selected_room_code = request.session.get("denied_logs_room", "all")

    # Get denied access logs ONLY
    denied_logs = (
        TransactionLog.objects
        .filter(
            academic_year=selected_ay, 
            semester=selected_semester,
            access_granted=False  # ❌ Only denied
        )
        .select_related("rfid", "rfid__faculty", "room")
        .order_by("-open_time")
    )

    if selected_room_code != "all":
        denied_logs = denied_logs.filter(room__code=selected_room_code)

    # Get rooms for filter
    rooms = Room.objects.all().order_by("code")
    
    # Get total counts
    total_denied = denied_logs.count()
    denied_today = denied_logs.filter(open_time__date=timezone.now().date()).count()
    
    # Group by denial reason
    denial_reasons = (
        denied_logs.values('denial_reason')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    
    # Most denied faculty
    most_denied_faculty = (
        denied_logs.values('rfid__faculty__full_name')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    ctx = {
        "semester_form": semester_form,
        "denied_logs": denied_logs,
        "rooms": rooms,
        "selected_room_code": selected_room_code,
        "total_denied": total_denied,
        "denied_today": denied_today,
        "denial_reasons": denial_reasons,
        "most_denied_faculty": most_denied_faculty,
        "can_see_names": True,
    }
    return render(request, "kbox_app/denied_access_logs.html", ctx)


@staff_or_superuser_required
def dashboard(request):
    """
    Dashboard - UPDATED to only show successful access by default
    """
    ay_choices, sem_choices = get_term_choices()
    system_settings = SystemSettings.get_current_term()

    if request.method == "POST":
        semester_form = SemesterChoiceForm(
            request.POST,
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )
        if semester_form.is_valid():
            selected_ay = semester_form.cleaned_data["academic_year"]
            selected_semester = semester_form.cleaned_data["semester"]
            request.session["selected_ay"] = selected_ay
            request.session["selected_semester"] = selected_semester
            system_settings.current_academic_year = selected_ay
            system_settings.current_semester = selected_semester
            system_settings.save()
            messages.success(request, f'System semester updated to {selected_semester} {selected_ay}')
        
        if "room" in request.POST:
            request.session["selected_room_code"] = request.POST.get("room", "all")
    else:
        selected_ay = request.session.get("selected_ay") or system_settings.current_academic_year
        selected_semester = request.session.get("selected_semester") or system_settings.current_semester
        selected_room_code = request.session.get("selected_room_code", "all")
        semester_form = SemesterChoiceForm(
            initial={"academic_year": selected_ay, "semester": selected_semester},
            ay_choices=ay_choices,
            sem_choices=sem_choices,
        )

    selected_ay = request.session.get("selected_ay") or system_settings.current_academic_year
    selected_semester = request.session.get("selected_semester") or system_settings.current_semester
    selected_room_code = request.session.get("selected_room_code", "all")

    # Transaction logs - ONLY SUCCESSFUL ACCESS
    transaction_logs = (
        TransactionLog.objects
        .filter(
            academic_year=selected_ay, 
            semester=selected_semester,
            access_granted=True  # ✅ Only successful
        )
        .select_related("rfid", "rfid__faculty", "room")
        .order_by("-open_time")
    )

    if selected_room_code != "all":
        transaction_logs = transaction_logs.filter(room__code=selected_room_code)

    # Stats - only successful access
    total_logs = transaction_logs.count()
    logs_today = transaction_logs.filter(open_time__date=timezone.now().date()).count()
    active_rooms = transaction_logs.values("room").distinct().count()
    faculty_count = transaction_logs.values("rfid__faculty__full_name").distinct().count()
    
    # NEW: Get denied attempts count for alert
    denied_count = TransactionLog.objects.filter(
        academic_year=selected_ay,
        semester=selected_semester,
        access_granted=False
    ).count()
    
    denied_today = TransactionLog.objects.filter(
        academic_year=selected_ay,
        semester=selected_semester,
        access_granted=False,
        open_time__date=timezone.now().date()
    ).count()

    rooms = Room.objects.all().order_by("code")

    if selected_room_code != "all":
        current_schedules = RoomSchedule.objects.filter(
            room__code=selected_room_code,
            semester=selected_semester
        ).select_related("room", "faculty").order_by("day_of_week", "start_time")
    else:
        current_schedules = RoomSchedule.objects.filter(
            semester=selected_semester
        ).select_related("room", "faculty").order_by("room__code", "day_of_week", "start_time")

    ctx = {
        "semester_form": semester_form,
        "transaction_logs": transaction_logs,
        "total_logs": total_logs,
        "faculty_count": faculty_count,
        "logs_today": logs_today,
        "active_rooms": active_rooms,
        "denied_count": denied_count,
        "denied_today": denied_today,
        "rooms": rooms,
        "selected_room_code": selected_room_code,
        "current_schedules": current_schedules,
        "user_type": 'superuser' if request.user.is_superuser else 'staff',
        "can_see_names": True,
    }
    return render(request, "kbox_app/dashboard.html", ctx)

# ---------- MANUAL TRIGGER API FOR ARDUINO ----------

@csrf_exempt
def manual_trigger_api(request):
    """
    ⭐ API FOR ARDUINO TO CHECK FOR MANUAL COMMANDS ⭐
    
    Arduino polls this endpoint every 2 seconds asking:
    "Any manual commands for my room?"
    
    Django checks database and responds with pending commands
    """
    from .models import ManualDoorLog
    from datetime import timedelta
    
    room_code = request.GET.get("room") or request.POST.get("room")
    
    if not room_code:
        return JsonResponse({
            "has_trigger": False,
            "action": "",
            "message": "Missing room parameter"
        }, status=400)
    
    try:
        # Check for commands from the last 2 seconds
        recent_time = timezone.now() - timedelta(seconds=5)
        
        latest_operation = ManualDoorLog.objects.filter(
            room__code=room_code,
            timestamp__gte=recent_time
        ).order_by('-timestamp').first()
        
        if latest_operation:
            # Found a command! Send it to Arduino
            print(f"🖱️  Arduino polling: Sending '{latest_operation.action}' command for room {room_code}")
            
            return JsonResponse({
                "has_trigger": True,
                "action": latest_operation.action,  # "open" or "close"
                "room": room_code,
                "message": f"Manual {latest_operation.action} command",
                "timestamp": latest_operation.timestamp.isoformat(),
                "staff": latest_operation.staff_user.get_full_name() if latest_operation.staff_user else "Unknown"
            }, status=200)
        else:
            # No commands found - this is normal
            return JsonResponse({
                "has_trigger": False,
                "action": "",
                "message": "No pending commands"
            }, status=200)
            
    except Exception as e:
        print(f"❌ Manual trigger API error: {str(e)}")
        return JsonResponse({
            "has_trigger": False,
            "action": "",
            "message": f"Error: {str(e)}"
        }, status=500)
    
@csrf_exempt
def esp32_heartbeat(request):
    """
    API endpoint for ESP32 devices to send heartbeat signals
    ✅ FIXED: Now accepts GET params, POST form data, AND JSON body
    """
    import json
    
    device_id = None
    firmware_version = None
    
    # Method 1: Try GET parameters
    device_id = request.GET.get("device_id")
    firmware_version = request.GET.get("firmware_version")
    
    # Method 2: Try POST form data
    if not device_id:
        device_id = request.POST.get("device_id")
        firmware_version = request.POST.get("firmware_version")
    
    # Method 3: ✅ Try JSON body (for your ESP32 Arduino code)
    if not device_id:
        try:
            if request.body:
                data = json.loads(request.body.decode('utf-8'))
                device_id = data.get("device_id")
                firmware_version = data.get("firmware_version")
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON decode error: {e}")
        except Exception as e:
            print(f"⚠️ Error reading request body: {e}")
    
    # Validation
    if not device_id:
        print("❌ Heartbeat rejected - Missing device_id")
        print(f"   Request method: {request.method}")
        print(f"   Content-Type: {request.META.get('CONTENT_TYPE', 'Not set')}")
        print(f"   Body preview: {request.body[:200] if request.body else 'Empty'}")
        
        return JsonResponse({
            "status": "error",
            "message": "Missing device_id parameter",
            "hint": "Send device_id as GET param, POST form data, or in JSON body"
        }, status=400)
    
    try:
        # Find the ESP32 device by device_id (MAC address)
        device = ESP32Device.objects.get(device_id=device_id, is_active=True)
        
        # Update last heartbeat timestamp
        device.last_heartbeat = timezone.now()
        
        # Get and update IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        
        device.ip_address = ip_address
        
        # Update firmware version if provided and different
        if firmware_version and firmware_version != device.firmware_version:
            device.firmware_version = firmware_version
            device.save()
            print(f"📝 Firmware version updated: {firmware_version}")
        else:
            device.save(update_fields=['last_heartbeat', 'ip_address'])
        
        # Success log
        print(f"💚 Heartbeat received from {device.device_name} ({device_id}) - IP: {ip_address}")
        
        return JsonResponse({
            "status": "success",
            "message": "Heartbeat received",
            "device_name": device.device_name,
            "room": device.room.code if device.room else None,
            "timestamp": device.last_heartbeat.isoformat()
        }, status=200)
        
    except ESP32Device.DoesNotExist:
        print(f"⚠️ Heartbeat from UNKNOWN device: {device_id}")
        print(f"   → This device is not registered in Django!")
        print(f"   → Go to Django Admin and add device with ID: {device_id}")
        
        return JsonResponse({
            "status": "error",
            "message": "Device not registered or inactive",
            "device_id_received": device_id,
            "hint": "Please register this device in Django Admin > ESP32 Devices"
        }, status=404)
        
    except Exception as e:
        print(f"❌ Heartbeat processing error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return JsonResponse({
            "status": "error",
            "message": f"Server error: {str(e)}"
        }, status=500)