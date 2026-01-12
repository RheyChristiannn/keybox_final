from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User

from .models import TransactionLog, RFIDRegistration, Faculty, UserProfile, Room, RoomSchedule


class SemesterChoiceForm(forms.Form):
    """
    Filter form for Academic Year + Semester.
    View passes ay_choices and sem_choices dynamically.
    """
    academic_year = forms.ChoiceField(label="Academic Year", choices=[])
    semester = forms.ChoiceField(label="Semester", choices=[])

    def __init__(self, *args, **kwargs):
        ay_choices = kwargs.pop("ay_choices", [])
        sem_choices = kwargs.pop("sem_choices", [])
        super().__init__(*args, **kwargs)

        # SAFER: Assign choices ONLY if provided
        if ay_choices:
            self.fields["academic_year"].choices = ay_choices
        
        if sem_choices:
            self.fields["semester"].choices = sem_choices


class CustomUserRegistrationForm(UserCreationForm):
    """
    Registration form for /accounts/register/.
    We hide username, and internally set it from the email.
    """

    # Hidden username field so UserCreationForm stays happy
    username = forms.CharField(widget=forms.HiddenInput(), required=False)

    first_name = forms.CharField(max_length=30, required=True, label="First name")
    surname = forms.CharField(
        max_length=100, required=False, label="Surname / Middle name"
    )
    last_name = forms.CharField(max_length=150, required=True, label="Last name")
    birthday = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Birthday",
    )
    gender = forms.ChoiceField(
        choices=[("", "Select Gender"), ("M", "Male"), ("F", "Female"), ("O", "Other")],
        required=False,
        label="Gender",
    )
    email = forms.EmailField(required=True, label="Email address")
    contact_no = forms.CharField(
        max_length=20, required=False, label="Contact no."
    )
    user_type = forms.ChoiceField(
        choices=[("staff", "Staff"), ("client", "Client")],
        required=True,
        label="User Type",
        initial="client",
        help_text="Select Staff for full access or Client for basic access"
    )
    rfid_code = forms.CharField(
        max_length=50,
        required=False,
        label="RFID Code",
        help_text="Optional: Scan or enter RFID card number"
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "first_name",
            "surname",
            "last_name",
            "birthday",
            "gender",
            "email",
            "contact_no",
            "user_type",
            "rfid_code",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We don't want the user to see username, it's hidden
        self.fields["username"].widget = forms.HiddenInput()
        self.fields["username"].required = False

        self.fields["first_name"].widget.attrs.update({"placeholder": "First name"})
        self.fields["surname"].widget.attrs.update({"placeholder": "Surname / Middle name"})
        self.fields["last_name"].widget.attrs.update({"placeholder": "Last name"})
        self.fields["birthday"].widget.attrs.update({})
        self.fields["gender"].widget.attrs.update({"class": "form-select"})
        self.fields["email"].widget.attrs.update({"placeholder": "Email address"})
        self.fields["contact_no"].widget.attrs.update({"placeholder": "Contact no."})
        self.fields["user_type"].widget.attrs.update({"class": "form-select"})
        self.fields["rfid_code"].widget.attrs.update({"placeholder": "Scan or enter RFID code"})
        self.fields["password1"].widget.attrs.update({"placeholder": "Password"})
        self.fields["password2"].widget.attrs.update({"placeholder": "Confirm password"})

    def clean_email(self):
        email = self.cleaned_data.get("email", "").lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean_rfid_code(self):
        rfid_code = self.cleaned_data.get("rfid_code", "").strip()
        if rfid_code:
            # Check if RFID code already exists in UserProfile
            if UserProfile.objects.filter(rfid_code=rfid_code).exists():
                raise forms.ValidationError("This RFID code is already registered to another user.")
        return rfid_code if rfid_code else None

    def clean(self):
        """
        Set the hidden username field from email so UserCreationForm
        can use it without errors.
        """
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        if email:
            cleaned_data["username"] = email.lower()
            self.cleaned_data["username"] = email.lower()
        return cleaned_data

    def save(self, commit=True):
        email = self.cleaned_data["email"].lower()

        # This calls UserCreationForm.save(), which will now see username set
        user = super().save(commit=False)

        # store basic fields on User
        user.username = email            # internal username = email
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = email

        if commit:
            user.save()
            UserProfile.objects.create(
                user=user,
                surname=self.cleaned_data.get("surname", ""),
                birthday=self.cleaned_data.get("birthday"),
                gender=self.cleaned_data.get("gender", ""),
                contact_no=self.cleaned_data.get("contact_no", ""),
                user_type=self.cleaned_data.get("user_type", "client"),
                rfid_code=self.cleaned_data.get("rfid_code"),
            )
        return user


class EmailAuthenticationForm(AuthenticationForm):
    """
    Login form that uses email + password instead of username.
    Internally still passes username to Django auth.
    """
    username = forms.EmailField(
        label="Email add",
        widget=forms.EmailInput(attrs={"placeholder": "Email add"}),
    )

    def clean(self):
        # 'username' field actually contains email here
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if email and password:
            try:
                user_obj = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                raise forms.ValidationError("Invalid email or password.")

            # Replace email with real username for parent .clean()
            self.cleaned_data["username"] = user_obj.username

        return super().clean()


class RFIDRegistrationForm(forms.ModelForm):
    """
    Form for admin to register new RFID cards for faculty + room.
    """

    # Option 1: Select existing faculty
    faculty = forms.ModelChoiceField(
        queryset=Faculty.objects.filter(is_active=True).order_by('full_name'),
        required=False,
        label="Select Existing Faculty",
        help_text="Choose from existing faculty members",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    # Option 2: Create new faculty
    faculty_name = forms.CharField(
        max_length=150,
        required=False,
        label="OR Create New Faculty - Full Name",
        widget=forms.TextInput(attrs={
            'placeholder': 'Leave blank if selecting existing faculty above',
            'class': 'form-control'
        })
    )
    
    school_id = forms.CharField(
        max_length=50,
        required=False,
        label="School ID (for new faculty)",
        widget=forms.TextInput(attrs={
            'placeholder': 'Required if creating new faculty',
            'class': 'form-control'
        })
    )
    
    department = forms.ChoiceField(
        choices=[("", "Select Department")] + Faculty.DEPARTMENT_CHOICES,
        required=False,
        label="Department (for new faculty)",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = RFIDRegistration
        fields = ["rfid_code", "room"]
        widgets = {
            "rfid_code": forms.TextInput(attrs={
                'placeholder': 'Scan or enter RFID code',
                'class': 'form-control'
            }),
            "room": forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            "rfid_code": "RFID Code",
            "room": "Assigned Room",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active rooms
        self.fields["room"].queryset = Room.objects.filter(is_active=True).order_by('code')

    def clean_rfid_code(self):
        """Check if RFID code already exists"""
        rfid_code = (self.cleaned_data.get("rfid_code") or "").strip()
        
        if not rfid_code:
            raise forms.ValidationError("RFID code is required.")
        
        # Check if RFID already registered
        if RFIDRegistration.objects.filter(rfid_code=rfid_code).exists():
            raise forms.ValidationError("This RFID code is already registered.")
        
        return rfid_code

    def clean_school_id(self):
        """Check if school ID already exists when creating new faculty"""
        school_id = (self.cleaned_data.get("school_id") or "").strip()
        # use cleaned_data instead of self.data
        faculty_name = (self.cleaned_data.get("faculty_name") or "").strip()
        
        # Only validate if we're creating a new faculty
        if faculty_name and school_id:
            if Faculty.objects.filter(school_id=school_id).exists():
                raise forms.ValidationError(
                    "This School ID is already registered to another faculty member."
                )
        
        # allow empty -> None
        return school_id or None

    def clean(self):
        """Validate that either existing faculty is selected OR new faculty info is provided"""
        cleaned_data = super().clean()
        faculty = cleaned_data.get("faculty")
        faculty_name = (cleaned_data.get("faculty_name") or "").strip()
        school_id = (cleaned_data.get("school_id") or "").strip()
        department = (cleaned_data.get("department") or "").strip()

        # Must choose ONE option: existing faculty OR create new
        if not faculty and not faculty_name:
            raise forms.ValidationError(
                "Please either select an existing faculty member OR provide details to create a new one."
            )
        
        # If creating new faculty, all fields are required
        if faculty_name:
            if not school_id:
                self.add_error('school_id', "School ID is required when creating new faculty.")
            if not department:
                self.add_error('department', "Department is required when creating new faculty.")
        
        # Cannot select both options
        if faculty and faculty_name:
            raise forms.ValidationError(
                "Please choose only ONE option: either select existing faculty OR create new faculty (not both)."
            )
        
        return cleaned_data

    def save(self, commit=True):
        """Save the RFID registration and create faculty if needed"""
        instance = super().save(commit=False)
        
        # If no faculty selected, create a new one
        if not instance.faculty:
            faculty = Faculty.objects.create(
                school_id=self.cleaned_data["school_id"],
                full_name=self.cleaned_data["faculty_name"],
                department=self.cleaned_data["department"]
            )
            instance.faculty = faculty
        
        if commit:
            instance.save()
        
        return instance


class TransactionLogForm(forms.ModelForm):
    """
    Optional manual log form (if ever used).
    """

    class Meta:
        model = TransactionLog
        fields = ["rfid", "room", "academic_year", "semester", "open_time", "close_time"]
        widgets = {
            "open_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "close_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rfid"].label_from_instance = (
            lambda obj: f"{obj.faculty.full_name} ({obj.rfid_code})"
        )


# ========== MANAGEMENT FORMS ==========

class RoomForm(forms.ModelForm):
    """Form for adding/editing rooms"""
    class Meta:
        model = Room
        fields = ['code', 'description', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'placeholder': 'e.g., 203', 'class': 'form-control'}),
            'description': forms.TextInput(attrs={'placeholder': 'Room description', 'class': 'form-control'}),
        }
        labels = {
            'code': 'Room Code',
            'description': 'Description',
            'is_active': 'Active Status'
        }


# FIXED RoomScheduleForm in forms.py
# Replace your existing RoomScheduleForm with this version

class RoomScheduleForm(forms.ModelForm):
    """
    FIXED Form for creating/editing room schedules
    Faculty dropdown now refreshes dynamically to show all faculty
    """
    
    # Semester field
    semester = forms.ChoiceField(
        required=True,
        choices=RoomSchedule.SEMESTER_CHOICES,
        widget=forms.RadioSelect(),
        label='Semester',
        help_text='Select the academic semester',
        error_messages={'required': 'Please select a semester'}
    )
    
    # Custom field for multiple days
    day_of_week = forms.MultipleChoiceField(
        required=True,
        choices=[
            ('monday', 'Monday'),
            ('tuesday', 'Tuesday'),
            ('wednesday', 'Wednesday'),
            ('thursday', 'Thursday'),
            ('friday', 'Friday'),
            ('saturday', 'Saturday'),
            ('sunday', 'Sunday'),
        ],
        widget=forms.CheckboxSelectMultiple(),
        label='Days of Week',
        help_text='Select one or more days',
        error_messages={'required': 'Please select at least one day'}
    )
    
    class Meta:
        model = RoomSchedule
        fields = ['semester', 'room', 'start_time', 'end_time', 'subject', 'instructor_name', 'faculty', 'is_active']
        widgets = {
            'room': forms.Select(attrs={'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'subject': forms.TextInput(attrs={'placeholder': 'Subject name', 'class': 'form-control'}),
            'instructor_name': forms.TextInput(attrs={'placeholder': 'Instructor name (for display)', 'class': 'form-control'}),
            'faculty': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'faculty': 'Assign Faculty (Required for access control)',
            'instructor_name': 'Instructor Name (Display Only)',
        }
        help_texts = {
            'faculty': 'Select the faculty member who will have access to this room during this schedule',
            'instructor_name': 'This is just for display - actual access is controlled by the Faculty selection above',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # ========== CRITICAL FIX: REFRESH FACULTY QUERYSET ==========
        self.fields['faculty'].queryset = Faculty.objects.filter(is_active=True).order_by('full_name')
        self.fields['faculty'].label_from_instance = lambda obj: obj.full_name
        self.fields['faculty'].required = True
        self.fields['room'].queryset = Room.objects.filter(is_active=True).order_by('code')
        # ============================================================
        
        # ========== FIX: PROPERLY PRE-POPULATE WHEN EDITING ==========
        if self.instance and self.instance.pk:
            # Pre-populate semester
            if self.instance.semester:
                self.initial['semester'] = self.instance.semester
            
            # Pre-populate days
            if self.instance.day_of_week:
                stored_days = self.instance.day_of_week.lower()
                # Handle both formats: "mon,tue" and "monday,tuesday"
                day_mapping = {
                    'mon': 'monday', 'tue': 'tuesday', 'wed': 'wednesday',
                    'thu': 'thursday', 'fri': 'friday', 'sat': 'saturday', 'sun': 'sunday'
                }
                
                days_list = [d.strip() for d in stored_days.split(',')]
                converted_days = []
                
                for day in days_list:
                    # If it's already in full format (monday, tuesday, etc.), keep it
                    if day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                        converted_days.append(day)
                    # If it's abbreviated (mon, tue, etc.), convert it
                    elif day in day_mapping:
                        converted_days.append(day_mapping[day])
                    else:
                        # Try to match partial day names
                        for full_day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                            if day in full_day or full_day.startswith(day):
                                converted_days.append(full_day)
                                break
                
                self.initial['day_of_week'] = converted_days
        # ============================================================
    
    def clean_day_of_week(self):
        """Convert list of days to comma-separated string"""
        days = self.cleaned_data.get('day_of_week')
        if not days:
            raise forms.ValidationError('Please select at least one day')
        # Return as comma-separated string in lowercase
        return ','.join([day.lower() for day in days])
    
    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        
        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError('End time must be after start time')
        
        return cleaned_data
    
    def save(self, commit=True):
        """Save the schedule with proper day_of_week handling"""
        instance = super().save(commit=False)
        
        # ========== FIX: PROPERLY SET day_of_week ==========
        # The clean_day_of_week() already returns comma-separated string
        # So we just need to set it from cleaned_data
        if 'day_of_week' in self.cleaned_data:
            instance.day_of_week = self.cleaned_data['day_of_week']
        
        # Set semester from cleaned_data
        if 'semester' in self.cleaned_data:
            instance.semester = self.cleaned_data['semester']
        # ===================================================
        
        if commit:
            instance.save()
        
        return instance


class ClientManagementForm(forms.ModelForm):
    """Form for managing clients and their RFID"""
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    
    class Meta:
        model = UserProfile
        fields = ['surname', 'birthday', 'gender', 'contact_no', 'rfid_code', 'is_active']
        widgets = {
            'surname': forms.TextInput(attrs={'placeholder': 'Middle name', 'class': 'form-control'}),
            'birthday': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'contact_no': forms.TextInput(attrs={'placeholder': 'Contact number', 'class': 'form-control'}),
            'rfid_code': forms.TextInput(attrs={'placeholder': 'Scan RFID card', 'class': 'form-control'}),
        }
        labels = {
            'surname': 'Middle Name',
            'rfid_code': 'RFID Card Number',
            'is_active': 'Active Status'
        }
    
    def __init__(self, *args, **kwargs):
        self.user_instance = kwargs.pop('user_instance', None)
        super().__init__(*args, **kwargs)
        
        if self.user_instance:
            self.fields['first_name'].initial = self.user_instance.first_name
            self.fields['last_name'].initial = self.user_instance.last_name
            self.fields['email'].initial = self.user_instance.email
    
    def clean_rfid_code(self):
        rfid_code = self.cleaned_data.get('rfid_code', '').strip()
        if rfid_code:
            # Check if RFID already exists (excluding current instance)
            existing = UserProfile.objects.filter(rfid_code=rfid_code)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError("This RFID code is already assigned to another user.")
        return rfid_code or None


class FacultyForm(forms.ModelForm):
    first_name = forms.CharField(max_length=50, required=True)
    middle_name = forms.CharField(max_length=50, required=False)
    last_name = forms.CharField(max_length=50, required=True)
    extension = forms.CharField(max_length=10, required=False)

    class Meta:
        model = Faculty
        fields = ['school_id', 'department', 'is_active']