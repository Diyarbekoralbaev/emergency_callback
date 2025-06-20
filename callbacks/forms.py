from django import forms
from .models import CallbackRequest
from teams.models import Team


class CallbackRequestForm(forms.ModelForm):
    team = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Select Team"
    )

    class Meta:
        model = CallbackRequest
        fields = ['phone_number', 'team']
        widgets = {
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter phone number (e.g., 998901234567)'
            }),
        }

    def clean_phone_number(self):
        phone = self.cleaned_data['phone_number']
        # Basic phone number validation
        cleaned_phone = ''.join(filter(str.isdigit, phone))

        if not cleaned_phone:
            raise forms.ValidationError("Please enter a valid phone number")

        if len(cleaned_phone) < 9:
            raise forms.ValidationError("Phone number is too short")

        return phone
