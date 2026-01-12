"""
views_management.py - Staff-Only Management
NO CLIENT MANAGEMENT - Faculty don't login
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.db.models import Q, Count
from django import forms
from django.views.decorators.http import require_http_methods
import json

from .models import (
    Room, RoomSchedule, UserProfile, Faculty, RFIDRegistration, 
    SystemSettings, ManualDoorLog, ESP32Device
)
from .forms import RoomForm, RoomScheduleForm
from .views import staff_or_superuser_required
from django.utils import timezone


# ==================== ROOM MANAGEMENT ====================

@staff_or_superuser_required
def room_list(request):
    """List all rooms with add/edit/disable options"""
    rooms = Room.objects.all().order_by('-is_active', 'code')
    
    context = {
        'rooms': rooms,
        'active_count': rooms.filter(is_active=True).count(),
        'inactive_count': rooms.filter(is_active=False).count(),
    }
    return render(request, 'kbox_app/room_list.html', context)


@staff_or_superuser_required
def room_add(request):
    """Add new room"""
    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            room = form.save()
            messages.success(request, f'Room {room.code} added successfully!')
            return redirect('room_list')
    else:
        form = RoomForm()
    
    return render(request, 'kbox_app/room_form.html', {
        'form': form,
        'title': 'Add New Room',
        'button_text': 'Add Room'
    })


@staff_or_superuser_required
def room_edit(request, room_id):
    """Edit existing room"""
    room = get_object_or_404(Room, id=room_id)
    
    if request.method == 'POST':
        form = RoomForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, f'Room {room.code} updated successfully!')
            return redirect('room_list')
    else:
        form = RoomForm(instance=room)
    
    return render(request, 'kbox_app/room_form.html', {
        'form': form,
        'title': f'Edit Room {room.code}',
        'button_text': 'Update Room',
        'room': room
    })


@staff_or_superuser_required
def room_toggle_status(request, room_id):
    """Toggle room active/inactive status"""
    room = get_object_or_404(Room, id=room_id)
    room.is_active = not room.is_active
    room.save()
    
    status = "activated" if room.is_active else "deactivated"
    messages.success(request, f'Room {room.code} has been {status}!')
    return redirect('room_list')


# ==================== SCHEDULE MANAGEMENT ====================

@staff_or_superuser_required
def schedule_list(request):
    """List all schedules with filter by room and semester"""
    room_filter = request.GET.get('room', 'all')
    semester_filter = request.GET.get('semester', 'all')
    
    schedules = RoomSchedule.objects.select_related('room', 'faculty').order_by('-is_active', 'semester', 'room__code', 'day_of_week', 'start_time')
    
    if room_filter != 'all':
        schedules = schedules.filter(room__code=room_filter)
    
    if semester_filter != 'all':
        schedules = schedules.filter(semester=semester_filter)
    
    rooms = Room.objects.filter(is_active=True).order_by('code')
    
    # Get current system semester for highlighting
    try:
        system_settings = SystemSettings.objects.get(pk=1)
        current_semester = system_settings.current_semester
    except SystemSettings.DoesNotExist:
        current_semester = '1st'
    
    context = {
        'schedules': schedules,
        'rooms': rooms,
        'selected_room': room_filter,
        'selected_semester': semester_filter,
        'active_count': schedules.filter(is_active=True).count(),
        'inactive_count': schedules.filter(is_active=False).count(),
        'semester_choices': RoomSchedule.SEMESTER_CHOICES,
        'current_semester': current_semester,
    }
    return render(request, 'kbox_app/schedule_list.html', context)


@staff_or_superuser_required
def schedule_add(request):
    """Add new schedule - handles multiple days"""
    if request.method == 'POST':
        form = RoomScheduleForm(request.POST)
        
        # Get selected days (can be multiple)
        selected_days = request.POST.getlist('day_of_week')
        
        if form.is_valid() and selected_days:
            # Create a schedule for each selected day
            created_count = 0
            
            for day in selected_days:
                try:
                    RoomSchedule.objects.create(
                        room=form.cleaned_data['room'],
                        day_of_week=day,  # Already lowercase from form
                        start_time=form.cleaned_data['start_time'],
                        end_time=form.cleaned_data['end_time'],
                        subject=form.cleaned_data.get('subject', ''),
                        faculty=form.cleaned_data.get('faculty'),
                        semester=form.cleaned_data['semester'],
                        is_active=form.cleaned_data.get('is_active', True)
                    )
                    created_count += 1
                except Exception as e:
                    messages.error(request, f"Error creating schedule for {day}: {str(e)}")
            
            if created_count > 0:
                messages.success(request, f'Successfully created {created_count} schedule(s)!')
                return redirect('schedule_list')
            else:
                messages.error(request, 'Failed to create schedules.')
        else:
            if not selected_days:
                messages.error(request, 'Please select at least one day of the week.')
    else:
        form = RoomScheduleForm()
    
    return render(request, 'kbox_app/schedule_form.html', {
        'form': form,
        'title': 'Add New Schedule',
        'button_text': 'Create Schedule'
    })


@staff_or_superuser_required
def schedule_edit(request, schedule_id):
    """Edit existing schedule"""
    schedule = get_object_or_404(RoomSchedule, id=schedule_id)
    
    if request.method == 'POST':
        form = RoomScheduleForm(request.POST, instance=schedule)
        
        # Get selected days
        selected_days = request.POST.getlist('day_of_week')
        
        if form.is_valid() and selected_days:
            # If multiple days selected, we need to handle this differently
            if len(selected_days) == 1:
                # Single day - just update
                schedule.day_of_week = selected_days[0]
                form.save()
                messages.success(request, 'Schedule updated successfully!')
            else:
                # Multiple days - delete current and create new ones
                room = form.cleaned_data['room']
                start_time = form.cleaned_data['start_time']
                end_time = form.cleaned_data['end_time']
                subject = form.cleaned_data.get('subject', '')
                faculty = form.cleaned_data.get('faculty')
                semester = form.cleaned_data['semester']
                is_active = form.cleaned_data.get('is_active', True)
                
                # Delete the original
                schedule.delete()
                
                # Create new ones for each day
                for day in selected_days:
                    RoomSchedule.objects.create(
                        room=room,
                        day_of_week=day,
                        start_time=start_time,
                        end_time=end_time,
                        subject=subject,
                        faculty=faculty,
                        semester=semester,
                        is_active=is_active
                    )
                
                messages.success(request, f'Schedule updated! Created {len(selected_days)} schedule(s).')
            
            return redirect('schedule_list')
        else:
            if not selected_days:
                messages.error(request, 'Please select at least one day.')
    else:
        form = RoomScheduleForm(instance=schedule)
    
    return render(request, 'kbox_app/schedule_form.html', {
        'form': form,
        'title': 'Edit Schedule',
        'button_text': 'Update Schedule',
        'schedule': schedule  # Pass to pre-select the day checkbox
    })


@staff_or_superuser_required
def schedule_toggle_status(request, schedule_id):
    """Toggle schedule active/inactive status"""
    schedule = get_object_or_404(RoomSchedule, id=schedule_id)
    schedule.is_active = not schedule.is_active
    schedule.save()
    
    status = "activated" if schedule.is_active else "deactivated"
    messages.success(request, f'Schedule has been {status}!')
    return redirect('schedule_list')


@staff_or_superuser_required
def schedule_delete(request, schedule_id):
    """Delete schedule (only if no transactions exist)"""
    schedule = get_object_or_404(RoomSchedule, id=schedule_id)
    
    if request.method == 'POST':
        schedule.delete()
        messages.success(request, 'Schedule deleted successfully!')
        return redirect('schedule_list')
    
    return render(request, 'kbox_app/schedule_confirm_delete.html', {
        'schedule': schedule
    })


# ==================== FACULTY MANAGEMENT ====================

class FacultyForm(forms.ModelForm):
    """Form for adding/editing faculty"""
    class Meta:
        model = Faculty
        fields = ['school_id', 'full_name', 'department', 'is_active']
        widgets = {
            'school_id': forms.TextInput(attrs={'placeholder': 'Employee/School ID', 'class': 'form-control'}),
            'full_name': forms.TextInput(attrs={'placeholder': 'Full name', 'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'school_id': 'School/Employee ID',
            'full_name': 'Full Name',
            'department': 'Department',
            'is_active': 'Active Status'
        }

@staff_or_superuser_required
def faculty_list(request):
    """
    List all faculty with their room assignments and RFID cards
    Staff use this to manage faculty records (NOT user accounts)
    """
    search_query = request.GET.get('search', '')
    
    faculty = Faculty.objects.annotate(
        rfid_count=Count('rfid_cards', distinct=True),      # ✅ Added distinct=True
        schedule_count=Count('schedules', distinct=True)    # ✅ Added distinct=True
    ).order_by('-is_active', 'full_name')
    
    if search_query:
        faculty = faculty.filter(
            Q(full_name__icontains=search_query) |
            Q(school_id__icontains=search_query)
        )
    
    context = {
        'faculty_list': faculty,
        'search_query': search_query,
        'active_count': Faculty.objects.filter(is_active=True).count(),
        'inactive_count': Faculty.objects.filter(is_active=False).count(),
    }
    return render(request, 'kbox_app/faculty_list.html', context)


@staff_or_superuser_required
def faculty_add(request):
    if request.method == "POST":
        form = FacultyForm(request.POST)

        first = request.POST.get("first_name", "").strip()
        middle = request.POST.get("middle_name", "").strip()
        last = request.POST.get("last_name", "").strip()
        ext = request.POST.get("extension", "").strip()

        if not first or not last:
            messages.error(request, "First name and last name are required.")
            return render(request, "kbox_app/faculty_form.html", {
                "form": form,
                "title": "Add New Faculty",
                "button_text": "Add Faculty",
                "first_name": first,
                "middle_name": middle,
                "last_name": last,
                "extension": ext,
            })

        if form.is_valid():
            faculty = form.save(commit=False)

            # BUILD FULL NAME
            full_name = f"{last}, {first}"
            if middle:
                full_name += f" {middle}"
            if ext:
                full_name += f" {ext}"

            faculty.full_name = full_name.strip()
            faculty.save()

            messages.success(request, "Faculty added successfully!")
            return redirect("faculty_list")

        messages.error(request, "Please correct the errors below.")
    else:
        form = FacultyForm()

    return render(request, "kbox_app/faculty_form.html", {
        "form": form,
        "title": "Add New Faculty",
        "button_text": "Add Faculty",
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "extension": "",
    })


@staff_or_superuser_required
def faculty_edit(request, faculty_id):
    faculty = get_object_or_404(Faculty, id=faculty_id)

    # Parse full_name
    name_parts = faculty.full_name.split(",")
    last_name = name_parts[0].strip() if len(name_parts) > 0 else ""
    rest = name_parts[1].strip().split(" ") if len(name_parts) > 1 else []

    first_name = rest[0] if len(rest) > 0 else ""
    middle_name = rest[1] if len(rest) > 1 else ""
    extension = rest[2] if len(rest) > 2 else ""

    if request.method == "POST":
        form = FacultyForm(request.POST, instance=faculty)

        first = request.POST.get("first_name", "").strip()
        middle = request.POST.get("middle_name", "").strip()
        last = request.POST.get("last_name", "").strip()
        ext = request.POST.get("extension", "").strip()

        if form.is_valid():
            fac = form.save(commit=False)

            full_name = f"{last}, {first}"
            if middle:
                full_name += f" {middle}"
            if ext:
                full_name += f" {ext}"

            fac.full_name = full_name.strip()
            fac.save()

            messages.success(request, "Faculty updated successfully!")
            return redirect("faculty_list")

        messages.error(request, "Please correct the errors below.")
    else:
        form = FacultyForm(instance=faculty)

    return render(request, "kbox_app/faculty_form.html", {
        "form": form,
        "title": "Edit Faculty",
        "button_text": "Save Changes",
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "extension": extension,
    })


@staff_or_superuser_required
def faculty_toggle_status(request, faculty_id):
    """Toggle faculty active/inactive status"""
    faculty = get_object_or_404(Faculty, id=faculty_id)
    faculty.is_active = not faculty.is_active
    faculty.save()
    
    status = "activated" if faculty.is_active else "deactivated"
    messages.success(request, f'Faculty {faculty.full_name} has been {status}!')
    return redirect('faculty_list')


@staff_or_superuser_required
def faculty_manage_access(request, faculty_id):
    """
    Manage which rooms a faculty can access
    Assign/remove RFID cards and view room schedules
    """
    faculty = get_object_or_404(Faculty, id=faculty_id)
    
    if request.method == 'POST':
        # Handle RFID assignment
        if 'add_rfid' in request.POST:
            rfid_code = request.POST.get('rfid_code')
            room_id = request.POST.get('room_id')
            
            if rfid_code and room_id:
                try:
                    room = Room.objects.get(id=room_id)
                    RFIDRegistration.objects.create(
                        rfid_code=rfid_code,
                        faculty=faculty,
                        room=room
                    )
                    messages.success(request, f'RFID card {rfid_code} added for {room.code}!')
                except Exception as e:
                    messages.error(request, f'Error adding RFID: {str(e)}')
            return redirect('faculty_manage_access', faculty_id=faculty_id)
        
        # Handle RFID removal
        if 'remove_rfid' in request.POST:
            rfid_id = request.POST.get('rfid_id')
            try:
                rfid = RFIDRegistration.objects.get(id=rfid_id)
                rfid.delete()
                messages.success(request, f'RFID card removed!')
            except Exception as e:
                messages.error(request, f'Error removing RFID: {str(e)}')
            return redirect('faculty_manage_access', faculty_id=faculty_id)
    
    # Get faculty's RFID cards and schedules
    rfid_cards = RFIDRegistration.objects.filter(faculty=faculty).select_related('room')
    schedules = RoomSchedule.objects.filter(faculty=faculty).select_related('room')
    
    # Get available rooms (rooms where faculty doesn't have RFID yet)
    assigned_room_ids = rfid_cards.values_list('room_id', flat=True)
    available_rooms = Room.objects.filter(is_active=True).exclude(id__in=assigned_room_ids)
    
    context = {
        'faculty': faculty,
        'rfid_cards': rfid_cards,
        'schedules': schedules,
        'available_rooms': available_rooms,
    }
    return render(request, 'kbox_app/faculty_manage_access.html', context)


# ==================== MANUAL DOOR CONTROL ====================

@staff_or_superuser_required
def manual_door_control(request):
    """
    Manual door control page - staff can open/close any room
    """
    rooms = Room.objects.filter(is_active=True).order_by('code')
    
    # Get recent manual operations
    recent_logs = ManualDoorLog.objects.select_related(
        'room', 'staff_user'
    ).order_by('-timestamp')[:20]
    
    context = {
        'rooms': rooms,
        'recent_logs': recent_logs,
    }
    return render(request, 'kbox_app/manual_door_control.html', context)


@staff_or_superuser_required
def manual_door_trigger(request):
    """
    ⭐ HANDLES STAFF BUTTON CLICKS FROM WEB INTERFACE ⭐
    
    When staff clicks "Open Door" or "Close Door" button:
    1. This function receives the request
    2. Saves the command to ManualDoorLog database
    3. Arduino will read it within 2 seconds via manual_trigger_api
    """
    if request.method == 'POST':
        room_id = request.POST.get('room_id')
        action = request.POST.get('action')  # 'open' or 'close'
        notes = request.POST.get('notes', '')
        
        if not room_id or action not in ['open', 'close']:
            messages.error(request, 'Invalid request.')
            return redirect('manual_door_control')
        
        try:
            room = Room.objects.get(id=room_id, is_active=True)
            
            # ⭐ CREATE LOG ENTRY - Arduino will read this! ⭐
            manual_log = ManualDoorLog.objects.create(
                room=room,
                staff_user=request.user,
                action=action,
                notes=notes
            )
            
            action_text = "opened" if action == "open" else "closed"
            messages.success(request, f'✅ Command sent! Room {room.code} will be {action_text} within 2 seconds.')
            
            # Debug print to console
            print(f"╔═══════════════════════════════════════════╗")
            print(f"║  MANUAL TRIGGER SAVED TO DATABASE        ║")
            print(f"╚═══════════════════════════════════════════╝")
            print(f"  Room: {room.code}")
            print(f"  Action: {action.upper()}")
            print(f"  Staff: {request.user.username}")
            print(f"  Time: {manual_log.timestamp}")
            print(f"  Log ID: {manual_log.id}")
            print(f"  Notes: {notes or '(none)'}")
            print(f"═══════════════════════════════════════════\n")
            
        except Room.DoesNotExist:
            messages.error(request, 'Room not found.')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            print(f"❌ Error saving manual trigger: {str(e)}")
    
    return redirect('manual_door_control')

"""
Add this new view function to views_management.py
Place it after the manual_door_trigger function
"""

@staff_or_superuser_required
def manual_door_log_delete(request):
    """
    Delete selected manual door logs
    """
    if request.method == 'POST':
        log_ids = request.POST.getlist('log_ids[]')
        
        if not log_ids:
            messages.error(request, 'No logs selected for deletion.')
            return redirect('manual_door_control')
        
        try:
            # Delete selected logs
            deleted_count = ManualDoorLog.objects.filter(id__in=log_ids).delete()[0]
            
            if deleted_count > 0:
                messages.success(request, f'Successfully deleted {deleted_count} log(s).')
            else:
                messages.warning(request, 'No logs were deleted.')
                
        except Exception as e:
            messages.error(request, f'Error deleting logs: {str(e)}')
    
    return redirect('manual_door_control')


# ==================== ESP32 DEVICE MANAGEMENT ====================

class ESP32DeviceForm(forms.ModelForm):
    """Form for adding/editing ESP32 devices"""
    class Meta:
        model = ESP32Device
        fields = ['device_name', 'device_id', 'room', 'firmware_version', 'is_active']
        widgets = {
            'device_name': forms.TextInput(attrs={
                'placeholder': 'e.g., ESP32-1', 
                'class': 'form-control'
            }),
            'device_id': forms.TextInput(attrs={
                'placeholder': 'MAC Address or Unique ID', 
                'class': 'form-control'
            }),
            'room': forms.Select(attrs={'class': 'form-control'}),
            'firmware_version': forms.TextInput(attrs={
                'placeholder': 'e.g., v1.0.0', 
                'class': 'form-control'
            }),
        }
        labels = {
            'device_name': 'Device Name',
            'device_id': 'Device ID (MAC Address or Unique ID)',
            'room': 'Assigned Room',
            'firmware_version': 'Firmware Version',
            'is_active': 'Active Status'
        }
        help_texts = {
            'device_name': 'Human-readable name (e.g., ESP32-1, ESP32-Room203)',
            'device_id': 'Unique identifier from ESP32 (usually MAC address)',
            'room': 'Which room does this device control?',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['room'].queryset = Room.objects.filter(is_active=True).order_by('code')
        self.fields['room'].required = False


@staff_or_superuser_required
def esp32_list(request):
    """List all ESP32 devices with their status"""
    devices = ESP32Device.objects.select_related('room').all()
    
    context = {
        'devices': devices,
        'online_count': sum(1 for d in devices if d.is_online()),
        'offline_count': sum(1 for d in devices if not d.is_online()),
        'total_count': devices.count(),
    }
    return render(request, 'kbox_app/esp32_list.html', context)


@staff_or_superuser_required
def esp32_add(request):
    """Add new ESP32 device"""
    if request.method == 'POST':
        form = ESP32DeviceForm(request.POST)
        if form.is_valid():
            device = form.save()
            messages.success(request, f'Device {device.device_name} added successfully!')
            return redirect('esp32_list')
    else:
        form = ESP32DeviceForm()
    
    return render(request, 'kbox_app/esp32_form.html', {
        'form': form,
        'title': 'Add New ESP32 Device',
        'button_text': 'Add Device'
    })


@staff_or_superuser_required
def esp32_edit(request, device_id):
    """Edit existing ESP32 device"""
    device = get_object_or_404(ESP32Device, id=device_id)
    
    if request.method == 'POST':
        form = ESP32DeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            messages.success(request, f'Device {device.device_name} updated successfully!')
            return redirect('esp32_list')
    else:
        form = ESP32DeviceForm(instance=device)
    
    return render(request, 'kbox_app/esp32_form.html', {
        'form': form,
        'title': f'Edit {device.device_name}',
        'button_text': 'Update Device',
        'device': device
    })


@staff_or_superuser_required
def esp32_toggle_status(request, device_id):
    """Toggle ESP32 device active/inactive status"""
    device = get_object_or_404(ESP32Device, id=device_id)
    device.is_active = not device.is_active
    device.save()
    
    status = "activated" if device.is_active else "deactivated"
    messages.success(request, f'Device {device.device_name} has been {status}!')
    return redirect('esp32_list')


@staff_or_superuser_required
def esp32_delete(request, device_id):
    """Delete ESP32 device"""
    device = get_object_or_404(ESP32Device, id=device_id)
    
    if request.method == 'POST':
        device_name = device.device_name
        device.delete()
        messages.success(request, f'Device {device_name} deleted successfully!')
        return redirect('esp32_list')
    
    return render(request, 'kbox_app/esp32_confirm_delete.html', {
        'device': device
    })


# ==================== ESP32 STATUS API (for sidebar) ====================

@require_http_methods(["GET"])
def esp32_status_api(request):
    """
    API endpoint for getting real-time status of all ESP32 devices
    Used by the sidebar to update device status indicators
    ENHANCED: Now includes schedule count for each device
    """
    devices = ESP32Device.objects.filter(is_active=True).select_related('room')
    
    # Get current semester
    try:
        system_settings = SystemSettings.objects.get(pk=1)
        current_semester = system_settings.current_semester
    except SystemSettings.DoesNotExist:
        current_semester = '1st'
    
    device_status = []
    for device in devices:
        # Count schedules for this device's room
        schedule_count = 0
        if device.room:
            schedule_count = RoomSchedule.objects.filter(
                room=device.room,
                semester=current_semester,
                is_active=True
            ).count()
        
        device_status.append({
            'id': device.id,
            'name': device.device_name,
            'room': device.room.code if device.room else 'Unassigned',
            'is_online': device.is_online(),
            'status': device.get_status_text(),
            'color': device.get_status_color(),
            'last_seen': device.last_heartbeat.isoformat() if device.last_heartbeat else None,
            'schedule_count': schedule_count,  # NEW - shows how many schedules loaded
        })
    
    return JsonResponse({
        'devices': device_status,
        'online_count': sum(1 for d in device_status if d['is_online']),
        'total_count': len(device_status)
    })


@staff_or_superuser_required
def esp32_device_schedules(request, device_id):
    """
    Show what schedules are loaded in a specific ESP32 device
    Staff can see: schedules, online status, last sync, WiFi status
    """
    device = get_object_or_404(ESP32Device, id=device_id)
    
    if not device.room:
        messages.warning(request, f'{device.device_name} has no assigned room.')
        return redirect('esp32_list')
    
    # Get current semester
    system_settings = SystemSettings.get_current_term()
    current_semester = system_settings.current_semester
    current_ay = system_settings.current_academic_year
    
    # Get ALL schedules for this device's room in current semester
    schedules = RoomSchedule.objects.filter(
        room=device.room,
        semester=current_semester,
        is_active=True
    ).select_related('faculty').order_by('day_of_week', 'start_time')
    
    # Build schedule data with RFID codes
    schedule_data = []
    total_rfid_count = 0
    
    for schedule in schedules:
        # Parse days (stored as comma-separated)
        days_raw = [d.strip().lower() for d in schedule.day_of_week.split(',')]
        
        # Convert to readable format
        day_names = []
        for day in days_raw:
            if 'mon' in day:
                day_names.append('Monday')
            elif 'tue' in day:
                day_names.append('Tuesday')
            elif 'wed' in day:
                day_names.append('Wednesday')
            elif 'thu' in day:
                day_names.append('Thursday')
            elif 'fri' in day:
                day_names.append('Friday')
            elif 'sat' in day:
                day_names.append('Saturday')
            elif 'sun' in day:
                day_names.append('Sunday')
        
        # Get RFID codes for this faculty in this room
        rfid_codes = []
        if schedule.faculty:
            rfid_registrations = RFIDRegistration.objects.filter(
                faculty=schedule.faculty,
                room=device.room,
                is_active=True
            )
            rfid_codes = [reg.rfid_code for reg in rfid_registrations]
            total_rfid_count += len(rfid_codes)
        
        schedule_data.append({
            'id': schedule.id,
            'days': ', '.join(day_names) if day_names else 'No days',
            'start_time': schedule.start_time,
            'end_time': schedule.end_time,
            'subject': schedule.subject,
            'faculty': schedule.faculty,
            'rfid_codes': rfid_codes,
            'rfid_count': len(rfid_codes),
        })
    
    # Calculate time since last heartbeat
    time_since_heartbeat = None
    if device.last_heartbeat:
        from django.utils import timezone
        delta = timezone.now() - device.last_heartbeat
        hours = delta.total_seconds() / 3600
        
        if hours < 1:
            minutes = int(delta.total_seconds() / 60)
            time_since_heartbeat = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif hours < 24:
            time_since_heartbeat = f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
        else:
            days = int(hours / 24)
            time_since_heartbeat = f"{days} day{'s' if days != 1 else ''} ago"
    
    context = {
        'device': device,
        'is_online': device.is_online(),
        'schedules': schedule_data,
        'schedule_count': len(schedule_data),
        'total_rfid_count': total_rfid_count,
        'current_semester': current_semester,
        'current_ay': current_ay,
        'time_since_heartbeat': time_since_heartbeat,
    }
    
    return render(request, 'kbox_app/esp32_device_schedules.html', context)


