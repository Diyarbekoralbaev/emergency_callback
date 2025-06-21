# callbacks/forms.py
from django import forms
from django.core.validators import RegexValidator
from .models import CallbackRequest
from teams.models import Team
import re


class CallbackRequestForm(forms.ModelForm):
    phone_validator = RegexValidator(
        regex=r'^\+?[0-9]{9,15}$',
        message="Enter a valid phone number (9-15 digits, with optional + prefix)"
    )

    phone_number = forms.CharField(
        validators=[phone_validator],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter phone number (e.g., 998901234567)',
            'pattern': r'^\+?[0-9]{9,15}$',
            'title': 'Phone number should be 9-15 digits, optionally starting with +'
        }),
        help_text="Enter phone number with country code (e.g., 998901234567 for Uzbekistan)"
    )

    team = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-select',
            'required': True
        }),
        empty_label="Select Emergency Team",
        help_text="Choose the emergency team that attended to this patient"
    )

    class Meta:
        model = CallbackRequest
        fields = ['phone_number', 'team']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes and improved styling
        for field_name, field in self.fields.items():
            if hasattr(field.widget, 'attrs'):
                field.widget.attrs.update({
                    'class': field.widget.attrs.get('class', '') + ' form-control',
                })

        # Special handling for select field
        self.fields['team'].widget.attrs.update({
            'class': 'form-select'
        })

        # Add icons and better descriptions
        self.fields['phone_number'].widget.attrs.update({
            'data-bs-toggle': 'tooltip',
            'data-bs-placement': 'top',
            'title': 'Enter the patient\'s phone number for callback'
        })

        self.fields['team'].widget.attrs.update({
            'data-bs-toggle': 'tooltip',
            'data-bs-placement': 'top',
            'title': 'Select the team that provided emergency service'
        })

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number', '').strip()

        if not phone:
            raise forms.ValidationError("Phone number is required")

        # Remove any non-digit characters except + at the beginning
        cleaned_phone = re.sub(r'[^+\d]', '', phone)

        # Remove + if it's not at the beginning
        if '+' in cleaned_phone[1:]:
            cleaned_phone = cleaned_phone.replace('+', '')
            if phone.startswith('+'):
                cleaned_phone = '+' + cleaned_phone

        # Validate length
        phone_digits = re.sub(r'[^\d]', '', cleaned_phone)
        if len(phone_digits) < 9:
            raise forms.ValidationError("Phone number is too short (minimum 9 digits)")

        if len(phone_digits) > 15:
            raise forms.ValidationError("Phone number is too long (maximum 15 digits)")

        # Uzbekistan specific validation
        if phone_digits.startswith('998'):
            if len(phone_digits) != 12:
                raise forms.ValidationError("Uzbekistan phone numbers should have 12 digits total (998 + 9 digits)")
        elif phone_digits.startswith('9') and len(phone_digits) == 9:
            # Auto-add Uzbekistan country code if it looks like a local number
            cleaned_phone = '998' + phone_digits

        # Check for obviously invalid patterns
        if phone_digits == '0' * len(phone_digits):
            raise forms.ValidationError("Invalid phone number (all zeros)")

        if len(set(phone_digits)) == 1:
            raise forms.ValidationError("Invalid phone number (all same digits)")

        return cleaned_phone

    def clean_team(self):
        team = self.cleaned_data.get('team')

        if not team:
            raise forms.ValidationError("Please select an emergency team")

        if not team.is_active:
            raise forms.ValidationError("Selected team is not currently active")

        return team

    def clean(self):
        cleaned_data = super().clean()
        phone_number = cleaned_data.get('phone_number')
        team = cleaned_data.get('team')

        # Check for recent duplicate requests (same phone + team within last hour)
        if phone_number and team:
            from django.utils import timezone
            from datetime import timedelta

            recent_threshold = timezone.now() - timedelta(hours=1)
            recent_request = CallbackRequest.objects.filter(
                phone_number=phone_number,
                team=team,
                created_at__gte=recent_threshold
            ).first()

            if recent_request:
                raise forms.ValidationError(
                    f"A callback request for this phone number and team was already created "
                    f"at {recent_request.created_at.strftime('%H:%M')}. "
                    f"Please wait before creating another request."
                )

        return cleaned_data


class RatingFilterForm(forms.Form):
    """Form for filtering ratings on the ratings page"""

    team = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True),
        required=False,
        empty_label="All Teams",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    rating = forms.ChoiceField(
        choices=[
            ('', 'All Ratings'),
            ('5', '⭐⭐⭐⭐⭐ (5 Stars)'),
            ('4', '⭐⭐⭐⭐ (4 Stars)'),
            ('3', '⭐⭐⭐ (3 Stars)'),
            ('2', '⭐⭐ (2 Stars)'),
            ('1', '⭐ (1 Star)'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError("Start date cannot be after end date")

        return cleaned_data


class CallbackFilterForm(forms.Form):
    """Form for filtering callbacks on the list page"""

    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(CallbackRequest._meta.get_field('status').choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    team = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True),
        required=False,
        empty_label="All Teams",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search phone number or team name...'
        })
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )