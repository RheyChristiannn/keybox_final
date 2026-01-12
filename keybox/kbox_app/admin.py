from django.contrib import admin
from django.utils.html import format_html
from .models import Room, Course, Faculty, RFIDRegistration, RoomSchedule, TransactionLog, SystemSettings


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("code", "description", "is_active", "created_at")
    search_fields = ("code", "description")
    list_filter = ("is_active",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("course_name", "room", "start_date", "end_date")
    list_filter = ("room",)
    search_fields = ("course_name",)


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ("full_name", "school_id", "department", "is_active")
    search_fields = ("full_name", "school_id")
    list_filter = ("department", "is_active")


@admin.register(RFIDRegistration)
class RFIDRegistrationAdmin(admin.ModelAdmin):
    list_display = ("rfid_code", "faculty", "room", "is_active", "created_at")
    search_fields = ("rfid_code", "faculty__full_name", "faculty__school_id")
    list_filter = ("room", "is_active")


@admin.register(RoomSchedule)
class RoomScheduleAdmin(admin.ModelAdmin):
    list_display = ("room", "semester", "get_days_display", "start_time", "end_time", "subject", "faculty", "is_active")
    list_filter = ("room", "semester", "is_active", "faculty")
    search_fields = ("subject", "instructor_name", "faculty__full_name")


@admin.register(TransactionLog)
class TransactionLogAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'faculty_name',
        'room_code',
        'access_status',
        'open_time',
        'close_time',
        'academic_year',
        'semester',
        'denial_reason_short'
    ]
    
    list_filter = [
        'access_granted',
        'academic_year',
        'semester',
        'open_time',
    ]
    
    search_fields = [
        'rfid__faculty__full_name',
        'rfid__faculty__school_id',
        'room__code',
        'denial_reason'
    ]
    
    date_hierarchy = 'open_time'
    
    ordering = ['-open_time']
    
    # ✅ Fixed to handle None values - this prevents crashes when viewing deleted records
    def faculty_name(self, obj):
        """Safely get faculty name even if RFID or faculty is deleted"""
        if obj.rfid and obj.rfid.faculty:
            return obj.rfid.faculty.full_name
        return "-"
    faculty_name.short_description = 'Faculty Name'
    
    def room_code(self, obj):
        """Safely get room code even if room is deleted"""
        if obj.room:
            return obj.room.code
        return "-"
    room_code.short_description = 'Room Code'
    
    def access_status(self, obj):
        if obj.access_granted:
            return format_html('<span style="color: green; font-weight: bold;">✓ GRANTED</span>')
        else:
            return format_html('<span style="color: red; font-weight: bold;">✗ DENIED</span>')
    access_status.short_description = 'Status'
    access_status.admin_order_field = 'access_granted'
    
    def denial_reason_short(self, obj):
        if obj.denial_reason:
            return obj.denial_reason[:50] + '...' if len(obj.denial_reason) > 50 else obj.denial_reason
        return '-'
    denial_reason_short.short_description = 'Denial Reason'
    
    # ✅ Override delete_queryset to ensure bulk deletion works
    def delete_queryset(self, request, queryset):
        """Override to allow bulk deletion of transaction logs"""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Successfully deleted {count} transaction log(s).')
    
    # Custom admin actions for bulk operations
    actions = ['delete_denied_logs', 'delete_old_logs']
    
    @admin.action(description='Delete all DENIED access logs')
    def delete_denied_logs(self, request, queryset):
        denied_logs = TransactionLog.objects.filter(access_granted=False)
        count = denied_logs.count()
        denied_logs.delete()
        self.message_user(request, f'Successfully deleted {count} denied access log(s).')
    
    @admin.action(description='Delete logs older than 6 months')
    def delete_old_logs(self, request, queryset):
        from django.utils import timezone
        from datetime import timedelta
        
        six_months_ago = timezone.now() - timedelta(days=180)
        old_logs = TransactionLog.objects.filter(open_time__lt=six_months_ago)
        count = old_logs.count()
        old_logs.delete()
        self.message_user(request, f'Successfully deleted {count} log(s) older than 6 months.')


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ['current_academic_year', 'current_semester', 'updated_at']
    
    def has_add_permission(self, request):
        # Only allow one SystemSettings instance
        return not SystemSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of SystemSettings
        return False