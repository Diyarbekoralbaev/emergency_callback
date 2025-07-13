# teams/forms.py
from django import forms
from django.core.validators import MinLengthValidator
from .models import Team, Region


class RegionForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        validators=[MinLengthValidator(2, "Название региона должно содержать не менее 2 символов")],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите название региона (например, Нукус)',
            'maxlength': 100,
        }),
        help_text="Введите полное название региона или района"
    )

    code = forms.CharField(
        max_length=20,
        validators=[MinLengthValidator(2, "Код региона должен содержать не менее 2 символов")],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите код региона (например, NUK)',
            'maxlength': 20,
        }),
        help_text="Уникальный код региона для идентификации"
    )

    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Опишите регион, его особенности и зону покрытия...',
            'maxlength': 500,
        }),
        help_text="Дополнительная информация о регионе"
    )

    class Meta:
        model = Region
        fields = ['name', 'code', 'description']

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
            'title': 'Введите полное название региона'
        })

        self.fields['code'].widget.attrs.update({
            'title': 'Введите уникальный код региона (например, NUK для Нукуса)'
        })

        self.fields['description'].widget.attrs.update({
            'title': 'Опишите особенности и зону покрытия региона'
        })

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()

        if not name:
            raise forms.ValidationError("Название региона обязательно")

        # Remove extra whitespace
        name = ' '.join(name.split())

        # Check for minimum length
        if len(name) < 2:
            raise forms.ValidationError("Название региона должно содержать не менее 2 символов")

        # Check for valid characters (letters, numbers, spaces, hyphens)
        import re
        if not re.match(r'^[a-zA-Zа-яА-Я0-9\s\-]+$', name):
            raise forms.ValidationError("Название региона может содержать только буквы, цифры, пробелы и дефисы")

        # Check for duplicate names (case-insensitive)
        existing_region = Region.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            existing_region = existing_region.exclude(pk=self.instance.pk)

        if existing_region.exists():
            raise forms.ValidationError("Регион с таким названием уже существует")

        return name

    def clean_code(self):
        code = self.cleaned_data.get('code', '').strip().upper()

        if not code:
            raise forms.ValidationError("Код региона обязателен")

        # Check for minimum length
        if len(code) < 2:
            raise forms.ValidationError("Код региона должен содержать не менее 2 символов")

        # Check for valid characters (letters and numbers only)
        import re
        if not re.match(r'^[A-Z0-9]+$', code):
            raise forms.ValidationError("Код региона может содержать только заглавные буквы и цифры")

        # Check for duplicate codes
        existing_region = Region.objects.filter(code__iexact=code)
        if self.instance and self.instance.pk:
            existing_region = existing_region.exclude(pk=self.instance.pk)

        if existing_region.exists():
            raise forms.ValidationError("Регион с таким кодом уже существует")

        return code

    def clean_description(self):
        description = self.cleaned_data.get('description', '').strip()

        # Remove extra whitespace
        description = ' '.join(description.split())

        # Check maximum length
        if len(description) > 500:
            raise forms.ValidationError("Описание должно быть не более 500 символов")

        return description


class TeamForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        validators=[MinLengthValidator(3, "Название бригады должно содержать не менее 3 символов")],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите название бригады (например, Экстренная бригада Альфа)',
            'maxlength': 100,
        }),
        help_text="Выберите четкое, описательное название для экстренной бригады"
    )

    region = forms.ModelChoiceField(
        queryset=Region.objects.filter(is_active=True),
        empty_label="Выберите регион...",
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        help_text="Выберите регион, в котором работает эта бригада"
    )

    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Опишите специализацию бригады, зону покрытия и обязанности...',
            'maxlength': 500,
        }),
        help_text="Предоставьте подробности о специализации и операционном охвате бригады"
    )

    class Meta:
        model = Team
        fields = ['name', 'region', 'description']

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
            'title': 'Введите уникальное название для этой экстренной бригады'
        })

        self.fields['region'].widget.attrs.update({
            'title': 'Выберите регион для этой бригады'
        })

        self.fields['description'].widget.attrs.update({
            'title': 'Опишите роль и специализацию бригады'
        })

        # Check if there are no active regions
        if not self.fields['region'].queryset.exists():
            self.fields['region'].widget.attrs['disabled'] = True
            self.fields['region'].help_text = "Нет доступных регионов. Пожалуйста, сначала создайте регион."

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        region = self.cleaned_data.get('region')

        if not name:
            raise forms.ValidationError("Название бригады обязательно")

        # Remove extra whitespace
        name = ' '.join(name.split())

        # Check for minimum length
        if len(name) < 3:
            raise forms.ValidationError("Название бригады должно содержать не менее 3 символов")

        # Check for valid characters (letters, numbers, spaces, hyphens, underscores)
        import re
        if not re.match(r'^[a-zA-Zа-яА-Я0-9\s\-_]+$', name):
            raise forms.ValidationError("Название бригады может содержать только буквы, цифры, пробелы, дефисы и подчеркивания")

        # Check for duplicate names within the same region
        if region:
            existing_team = Team.objects.filter(name__iexact=name, region=region)
            if self.instance and self.instance.pk:
                existing_team = existing_team.exclude(pk=self.instance.pk)

            if existing_team.exists():
                raise forms.ValidationError(f"Бригада с таким названием уже существует в регионе {region.name}")

        return name

    def clean_description(self):
        description = self.cleaned_data.get('description', '').strip()

        # Remove extra whitespace
        description = ' '.join(description.split())

        # Check maximum length
        if len(description) > 500:
            raise forms.ValidationError("Описание должно быть не более 500 символов")

        return description


class TeamSearchForm(forms.Form):
    """Form for searching and filtering teams"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Поиск по названию бригады или описанию...',
            'data-bs-toggle': 'tooltip',
            'title': 'Поиск в названиях бригад и описаниях'
        })
    )

    region = forms.ModelChoiceField(
        queryset=Region.objects.filter(is_active=True),
        required=False,
        empty_label="Все регионы",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-bs-toggle': 'tooltip',
            'title': 'Фильтр по региону'
        })
    )

    show_inactive = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'data-bs-toggle': 'tooltip',
            'title': 'Включить деактивированные бригады в результаты'
        }),
        label="Показать неактивные бригады"
    )

    sort_by = forms.ChoiceField(
        required=False,
        choices=[
            ('name', 'Название (А-Я)'),
            ('-name', 'Название (Я-А)'),
            ('region__name', 'Регион (А-Я)'),
            ('-region__name', 'Регион (Я-А)'),
            ('created_at', 'Старые сначала'),
            ('-created_at', 'Новые сначала'),
            ('-callback_count', 'Больше вызовов'),
            ('-avg_rating', 'Высший рейтинг'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-bs-toggle': 'tooltip',
            'title': 'Сортировка бригад по различным критериям'
        }),
        initial='region__name'
    )


class RegionSearchForm(forms.Form):
    """Form for searching and filtering regions"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Поиск по названию или коду региона...',
            'data-bs-toggle': 'tooltip',
            'title': 'Поиск в названиях и кодах регионов'
        })
    )

    show_inactive = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'data-bs-toggle': 'tooltip',
            'title': 'Включить деактивированные регионы в результаты'
        }),
        label="Показать неактивные регионы"
    )

    sort_by = forms.ChoiceField(
        required=False,
        choices=[
            ('name', 'Название (А-Я)'),
            ('-name', 'Название (Я-А)'),
            ('code', 'Код (А-Я)'),
            ('-code', 'Код (Я-А)'),
            ('created_at', 'Старые сначала'),
            ('-created_at', 'Новые сначала'),
            ('-team_count', 'Больше бригад'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-bs-toggle': 'tooltip',
            'title': 'Сортировка регионов по различным критериям'
        }),
        initial='name'
    )