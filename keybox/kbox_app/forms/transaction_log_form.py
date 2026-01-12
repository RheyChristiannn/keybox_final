# kbox_app/forms.py (continued)
from django import forms
from kbox_app.models import TransactionLog

class TransactionLogForm(forms.ModelForm):
    class Meta:
        model = TransactionLog
        fields = ['course_name', 'rfid_open_time', 'rfid_close_time', 'semester']
        widgets = {
            'rfid_open_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'rfid_close_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
