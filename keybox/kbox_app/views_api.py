"""
views_api.py - NEW FILE
Add this file to your Django app folder (same folder as views.py)

API endpoints for ESP32 to download schedules
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from .models import RoomSchedule, SystemSettings, Room
import json


@csrf_exempt
@require_http_methods(["GET", "POST"])
def esp32_get_schedules(request):
    """
    📥 ESP32 Schedule Download API
    
    ESP32 calls this to download ALL schedules for a specific room
    Returns schedules in a format easy for ESP32 to cache
    
    Usage: /api/esp32/schedules/?room=205
    """
    
    room_code = request.GET.get("room") or request.POST.get("room")
    
    if not room_code:
        return JsonResponse({
            "status": "error",
            "message": "Missing 'room' parameter"
        }, status=400)
    
    try:
        # Get the room
        room = Room.objects.get(code=room_code, is_active=True)
    except Room.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": f"Room {room_code} not found or inactive"
        }, status=404)
    
    # Get current system settings
    system_settings = SystemSettings.get_current_term()
    current_semester = system_settings.current_semester
    current_ay = system_settings.current_academic_year
    
    # Get ALL active schedules for this room in current semester
    schedules = RoomSchedule.objects.filter(
        room=room,
        semester=current_semester,
        is_active=True
    ).select_related('faculty').order_by('day_of_week', 'start_time')
    
    # Convert to ESP32-friendly format
    schedule_list = []
    
    for schedule in schedules:
        # Parse days (stored as "monday,tuesday,wednesday")
        days = [d.strip().lower() for d in schedule.day_of_week.split(',')]
        
        # Get faculty RFID codes for this schedule
        faculty_rfids = []
        if schedule.faculty:
            # Get all RFID cards for this faculty in this room
            from .models import RFIDRegistration
            rfid_cards = RFIDRegistration.objects.filter(
                faculty=schedule.faculty,
                room=room,
                is_active=True
            ).values_list('rfid_code', flat=True)
            faculty_rfids = list(rfid_cards)
        
        for day in days:
            schedule_list.append({
                "id": schedule.id,
                "day": day,  # "monday", "tuesday", etc.
                "start_time": schedule.start_time.strftime("%H:%M"),  # "08:00"
                "end_time": schedule.end_time.strftime("%H:%M"),      # "10:00"
                "subject": schedule.subject or "",
                "faculty_name": schedule.faculty.full_name if schedule.faculty else "",
                "faculty_rfids": faculty_rfids,  # List of valid RFID codes
                "instructor_display": schedule.instructor_name or ""
            })
    
    # Return response
    response_data = {
        "status": "success",
        "room_code": room_code,
        "semester": current_semester,
        "academic_year": current_ay,
        "schedule_count": len(schedule_list),
        "schedules": schedule_list,
        "last_updated": timezone.now().isoformat(),
        "server_time": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
        "day_of_week": timezone.now().strftime("%A").lower()  # Helper for ESP32
    }
    
    print(f"\n📤 ESP32 Schedule Download:")
    print(f"   Room: {room_code}")
    print(f"   Semester: {current_semester}")
    print(f"   Schedules sent: {len(schedule_list)}")
    print(f"   Timestamp: {timezone.now()}\n")
    
    return JsonResponse(response_data)


@csrf_exempt
@require_http_methods(["GET"])
def esp32_check_updates(request):
    """
    🔄 Check if schedules have been updated
    
    ESP32 calls this periodically to see if it needs to re-download schedules
    
    Usage: /api/esp32/check-updates/?room=205&last_sync=2025-01-15T10:30:00
    """
    
    room_code = request.GET.get("room")
    last_sync = request.GET.get("last_sync")  # ISO timestamp from ESP32
    
    if not room_code:
        return JsonResponse({
            "status": "error",
            "message": "Missing 'room' parameter"
        }, status=400)
    
    try:
        room = Room.objects.get(code=room_code, is_active=True)
    except Room.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": f"Room {room_code} not found"
        }, status=404)
    
    # Get system settings
    system_settings = SystemSettings.get_current_term()
    
    # Check if any schedules were updated after last_sync
    needs_update = False
    
    if last_sync:
        try:
            from django.utils.dateparse import parse_datetime
            last_sync_dt = parse_datetime(last_sync)
            
            # Check if any schedules were modified after last sync
            updated_schedules = RoomSchedule.objects.filter(
                room=room,
                semester=system_settings.current_semester,
                updated_at__gt=last_sync_dt
            ).count()
            
            needs_update = updated_schedules > 0
        except:
            needs_update = True  # If can't parse, force update
    else:
        needs_update = True  # No last sync time, force update
    
    return JsonResponse({
        "status": "success",
        "needs_update": needs_update,
        "current_semester": system_settings.current_semester,
        "current_ay": system_settings.current_academic_year,
        "server_time": timezone.now().isoformat(),
        "message": "Update required" if needs_update else "Schedules are up to date"
    })


@csrf_exempt  
@require_http_methods(["POST"])
def esp32_log_offline_access(request):
    """
    📝 Log offline access attempts
    
    When ESP32 grants access offline, it logs it here when WiFi comes back
    """
    
    try:
        data = json.loads(request.body)
        
        room_code = data.get("room_code")
        rfid_code = data.get("rfid_code")
        access_granted = data.get("access_granted")
        timestamp = data.get("timestamp")  # When it happened offline
        
        from .models import RFIDRegistration, TransactionLog
        
        # Find the RFID registration
        try:
            rfid = RFIDRegistration.objects.get(rfid_code=rfid_code)
            room = Room.objects.get(code=room_code)
            
            # Get system settings
            system_settings = SystemSettings.get_current_term()
            
            # Create transaction log
            TransactionLog.objects.create(
                rfid=rfid,
                room=room,
                faculty_name=rfid.faculty.full_name,
                room_code=room_code,
                rfid_code=rfid_code,
                academic_year=system_settings.current_academic_year,
                semester=system_settings.current_semester,
                open_time=timestamp,
                access_granted=access_granted
            )
            
            print(f"📝 Logged offline access: {rfid.faculty.full_name} - {room_code}")
            
            return JsonResponse({
                "status": "success",
                "message": "Offline access logged"
            })
            
        except Exception as e:
            print(f"❌ Error logging offline access: {str(e)}")
            return JsonResponse({
                "status": "error",
                "message": str(e)
            }, status=500)
            
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Invalid request: {str(e)}"
        }, status=400)