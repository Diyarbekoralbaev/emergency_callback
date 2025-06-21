# teams/forms.py
from django import forms
from django.core.validators import MinLengthValidator
from .models import Team


class TeamForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        validators=[MinLengthValidator(3, "Team name must be at least 3 characters long")],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter team name (e.g., Emergency Team Alpha)',
            'maxlength': 100,
        }),
        help_text="Choose a clear, descriptive name for the emergency team"
    )

    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Describe the team\'s specialization, coverage area, and responsibilities...',
            'maxlength': 500,
        }),
        help_text="Provide details about the team's specialization and operational scope"
    )

    class Meta:
        model = Team
        fields = ['name', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes and styling
        for field_name, field in self.fields.items():
            if hasattr(field.widget, 'attrs'):
                field.widget.attrs.update({
                    'data-bs-toggle': 'tooltip',
                    'data-bs-placement': 'top',
                })

        # Add specific tooltips
        self.fields['name'].widget.attrs.update({
            'title': 'Enter a unique name for this emergency team'
        })

        self.fields['description'].widget.attrs.update({
            'title': 'Describe the team\'s role and specialization'
        })

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()

        if not name:
            raise forms.ValidationError("Team name is required")

        # Remove extra whitespace
        name = ' '.join(name.split())

        # Check for minimum length
        if len(name) < 3:
            raise forms.ValidationError("Team name must be at least 3 characters long")

        # Check for valid characters (letters, numbers, spaces, hyphens, underscores)
        import re
        if not re.match(r'^[a-zA-Z0-9\s\-_]+$', name):
            raise forms.ValidationError("Team name can only contain letters, numbers, spaces, hyphens, and underscores")

        # Check for duplicate names (case-insensitive)
        existing_team = Team.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            existing_team = existing_team.exclude(pk=self.instance.pk)

        if existing_team.exists():
            raise forms.ValidationError("A team with this name already exists")

        return name

    def clean_description(self):
        description = self.cleaned_data.get('description', '').strip()

        # Remove extra whitespace
        description = ' '.join(description.split())

        # Check maximum length
        if len(description) > 500:
            raise forms.ValidationError("Description must be under 500 characters")

        return description


class TeamSearchForm(forms.Form):
    """Form for searching and filtering teams"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search teams by name or description...',
            'data-bs-toggle': 'tooltip',
            'title': 'Search in team names and descriptions'
        })
    )

    show_inactive = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'data-bs-toggle': 'tooltip',
            'title': 'Include deactivated teams in results'
        }),
        label="Show inactive teams"
    )

    sort_by = forms.ChoiceField(
        required=False,
        choices=[
            ('name', 'Name (A-Z)'),
            ('-name', 'Name (Z-A)'),
            ('created_at', 'Oldest First'),
            ('-created_at', 'Newest First'),
            ('-callback_count', 'Most Callbacks'),
            ('-avg_rating', 'Highest Rated'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-bs-toggle': 'tooltip',
            'title': 'Sort teams by different criteria'
        }),
        initial='name'
    )