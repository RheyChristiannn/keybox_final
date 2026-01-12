from django import forms

class SemesterChoiceForm(forms.Form):
    SEMESTER_CHOICES = [
        ('1st', '1st Semester'),
        ('2nd', '2nd Semester'),
        ('summer', 'Summer Class'),
    ]
    semester = forms.ChoiceField(choices=SEMESTER_CHOICES)
