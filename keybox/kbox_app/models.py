from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class UserProfile(models.Model):
    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
    ]
    
    USER_TYPE_CHOICES = [
        ("staff", "Staff"),
        ("client", "Client"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile"
    )
    # surname here = middle name / maiden name, etc.
    surname = models.CharField(max_length=100, blank=True)
    birthday = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    contact_no = models.CharField(max_length=20, blank=True)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default="client")
    rfid_code = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['rfid_code'],
                condition=models.Q(rfid_code__isnull=False) & ~models.Q(rfid_code=''),
                name='unique_rfid_code'
            )
        ]

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Room(models.Model):
    """
    Laboratory rooms like 203, 204, 205, ...
    """
    code = models.CharField(max_length=10, unique=True)
    description = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lab {self.code}" if self.code else "Lab room"


class Course(models.Model):
    """
    Optional: course using a specific lab.
    """
    course_name = models.CharField(max_length=100)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(default=timezone.now)

    def __str__(self):
        return self.course_name


class Faculty(models.Model):
    """
    Employee / faculty record.
    school_id = school RFID or employee ID.
    """
    DEPARTMENT_CHOICES = [
        ("COE", "College of Engineering"),
        ("CCIS", "College of Computing and Information Sciences"),
        ("CBT", "College of Business and Technology"),
        ("CAS", "College of Arts and Sciences"),
        ("CTE", "College of Teacher Education"),
    ]
    
    school_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=150, blank=True, null=True)
    department = models.CharField(max_length=10, choices=DEPARTMENT_CHOICES, default="COE")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.full_name} ({self.school_id})"


class RFIDRegistration(models.Model):
    """
    Maps a keybox RFID tag to a faculty member and a room.
    """
    rfid_code = models.CharField(max_length=50, unique=True)
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, related_name="rfid_cards")
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.rfid_code} -> {self.faculty.full_name} / {self.room.code}"


class RoomSchedule(models.Model):
    """
    Schedule for each laboratory room (admin-only CRUD).
    Supports multiple days per schedule (stored as comma-separated)
    """
    DAY_CHOICES = [
        ("Mon", "Monday"),
        ("Tue", "Tuesday"),
        ("Wed", "Wednesday"),
        ("Thu", "Thursday"),
        ("Fri", "Friday"),
        ("Sat", "Saturday"),
        ("Sun", "Sunday"),
    ]
    
    SEMESTER_CHOICES = [
        ("1st", "1st Semester"),
        ("2nd", "2nd Semester"),
        ("summer", "Summer"),
        ("summer2", "Summer 2"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    semester = models.CharField(max_length=10, choices=SEMESTER_CHOICES, default="1st")
    day_of_week = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    subject = models.CharField(max_length=100, blank=True)
    instructor_name = models.CharField(max_length=100, blank=True)
    
    faculty = models.ForeignKey(
        Faculty, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        related_name="schedules",
        help_text="Faculty member assigned to this schedule"
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.room} {self.get_semester_display()} {self.get_days_display()} {self.start_time}-{self.end_time}"
    
    def get_days_list(self):
        """Return days as a list"""
        if self.day_of_week:
            return self.day_of_week.split(',')
        return []
    
    def get_days_display(self):
        """Get formatted display of days for showing in the UI"""
        days_map = {
            'monday': 'M',
            'tuesday': 'T',
            'wednesday': 'W',
            'thursday': 'Thu',
            'friday': 'F',
            'saturday': 'Sat',
            'sunday': 'Sun',
            # Also support old format
            'mon': 'M',
            'tue': 'T',
            'wed': 'W',
            'thu': 'Thu',
            'fri': 'Fri',
            'sat': 'Sat',
            'sun': 'Sun',
        }
        days = self.get_days_list()
        return ', '.join([days_map.get(day.strip().lower(), day.capitalize()) for day in days])
    
    def get_day_of_week_display(self):
        """Backward compatibility method"""
        return self.get_days_display()
    
    def is_schedule_active_now(self):
        """
        Check if this schedule is currently active (right day and time)
        Updated to support multiple days
        """
        now = timezone.localtime(timezone.now())
        current_day_full = now.strftime("%A").lower()  # monday, tuesday, etc.
        current_day_short = now.strftime("%a").lower()  # mon, tue, etc.
        current_time = now.time()
        
        if not self.is_active:
            return False
        
        # Check if current day is in the schedule
        days = [d.strip().lower() for d in self.get_days_list()]
        day_match = current_day_full in days or current_day_short in days
        
        return (
            day_match and
            self.start_time <= current_time <= self.end_time
        )
    
    def can_access_now(self, faculty):
        """
        Check if a faculty member can access this room now based on schedule
        """
        if not self.is_active:
            return False
        
        # Check if it's the scheduled time
        if not self.is_schedule_active_now():
            return False
        
        # Check if this faculty is assigned to this schedule
        return self.faculty == faculty


class TransactionLog(models.Model):
    """
    One open/close session in the keybox.
    Tracks access granted/denied with reasons
    """
    SEMESTER_CHOICES = [
        ("1st", "1st Semester"),
        ("2nd", "2nd Semester"),
        ("summer", "Summer"),
        ("summer2", "Summer 2"),
    ]

    AY_CHOICES = [
        ("2024-2025", "2024-2025"),
        ("2025-2026", "2025-2026"),
        ("2026-2027", "2026-2027"),
        ("2027-2028", "2027-2028"),
        ("2028-2029", "2028-2029"),
    ]

    # ✅ Changed to SET_NULL to preserve logs
    rfid = models.ForeignKey(
        RFIDRegistration, 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transaction_logs'
    )
    
    room = models.ForeignKey(
        Room, 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transaction_logs'
    )

    # ✅ Add backup fields to preserve critical info even if FK is deleted
    faculty_name = models.CharField(max_length=150, blank=True)
    room_code = models.CharField(max_length=10, blank=True)
    rfid_code = models.CharField(max_length=50, blank=True)

    academic_year = models.CharField(
        max_length=20,
        choices=AY_CHOICES,
        default="2025-2026",
    )
    semester = models.CharField(
        max_length=10,
        choices=SEMESTER_CHOICES,
        default="1st",
    )

    open_time = models.DateTimeField(null=True, blank=True)
    close_time = models.DateTimeField(null=True, blank=True)
    
    access_granted = models.BooleanField(default=True)
    denial_reason = models.CharField(max_length=200, blank=True, null=True)
    
    schedule = models.ForeignKey(
        RoomSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transaction_logs"
    )

    def __str__(self):
        status = "GRANTED" if self.access_granted else "DENIED"
        faculty = self.faculty_name or (self.rfid.faculty.full_name if self.rfid else "Unknown")
        room = self.room_code or (self.room.code if self.room else "Unknown")
        return f"{faculty} - {room} - {status}"
    
    class Meta:
        ordering = ['-open_time']


class SystemSettings(models.Model):
    """
    Stores system-wide settings like current academic year and semester
    Should only have ONE record
    """
    current_academic_year = models.CharField(max_length=20, default="2025-2026")
    current_semester = models.CharField(
        max_length=10,
        choices=[
            ("1st", "1st Semester"),
            ("2nd", "2nd Semester"),
            ("summer", "Summer"),
            ("summer2", "Summer 2"),
        ],
        default="1st"
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"
    
    def __str__(self):
        return f"Current Term: {self.current_semester} {self.current_academic_year}"
    
    @classmethod
    def get_current_term(cls):
        """Get or create the system settings"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

class ManualDoorLog(models.Model):
    """
    Tracks manual door open/close operations by staff
    """
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='manual_operations'
    )
    staff_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='manual_operations'
    )
    action = models.CharField(
        max_length=10,
        choices=[
            ('open', 'Open'),
            ('close', 'Close'),
        ]
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Optional notes")
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.room.code} - {self.action.upper()} by {self.staff_user.username} at {self.timestamp}"

class ESP32Device(models.Model):
    """
    Tracks ESP32 devices in the system
    """
    device_name = models.CharField(max_length=50, unique=True, help_text="e.g., ESP32-1, ESP32-2")
    device_id = models.CharField(max_length=100, unique=True, help_text="Unique device identifier")
    room = models.ForeignKey(
        Room, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='esp32_devices',
        help_text="Room this device controls"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="Last known IP address")
    last_heartbeat = models.DateTimeField(null=True, blank=True, help_text="Last time device checked in")
    is_active = models.BooleanField(default=True, help_text="Is device enabled in system")
    firmware_version = models.CharField(max_length=20, blank=True, help_text="Current firmware version")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['device_name']
    
    def __str__(self):
        return f"{self.device_name} ({self.room.code if self.room else 'Unassigned'})"
    
    def is_online(self):
        """
        Check if device is online (heartbeat within last 30 seconds)
        """
        if not self.last_heartbeat:
            return False
        
        from django.utils import timezone
        from datetime import timedelta
        
        time_threshold = timezone.now() - timedelta(seconds=30)
        return self.last_heartbeat >= time_threshold
    
    def get_status_color(self):
        """
        Returns color code for UI
        """
        return 'green' if self.is_online() else 'red'
    
    def get_status_text(self):
        """
        Returns status text for UI
        """
        return 'Online' if self.is_online() else 'Offline'