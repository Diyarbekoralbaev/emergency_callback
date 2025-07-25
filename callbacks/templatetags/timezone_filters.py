# callbacks/templatetags/timezone_filters.py
from django import template
from django.utils import timezone
import pytz

register = template.Library()

TASHKENT_TZ = pytz.timezone('Asia/Tashkent')


@register.filter
def tashkent_time(value):
    """Convert UTC datetime to Tashkent time"""
    if not value:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, pytz.UTC)
    return value.astimezone(TASHKENT_TZ)


@register.filter
def tashkent_date(value, format_string="d M Y"):
    """Format date in Tashkent timezone"""
    tashkent_dt = tashkent_time(value)
    if not tashkent_dt:
        return ""
    return tashkent_dt.strftime(format_string)


@register.filter
def tashkent_datetime(value, format_string="d M Y, H:i"):
    """Format datetime in Tashkent timezone"""
    tashkent_dt = tashkent_time(value)
    if not tashkent_dt:
        return ""

    # Convert strftime format
    format_mapping = {
        'H:i': '%H:%M',
        'd M Y': '%d %b %Y',
        'd M Y, H:i': '%d %b %Y, %H:%M',
        'd.m.Y': '%d.%m.%Y',
        'd.m.Y H:i': '%d.%m.%Y %H:%M'
    }

    python_format = format_mapping.get(format_string, format_string)

    # Russian month names
    month_names = {
        'Jan': 'янв', 'Feb': 'фев', 'Mar': 'мар', 'Apr': 'апр',
        'May': 'май', 'Jun': 'июн', 'Jul': 'июл', 'Aug': 'авг',
        'Sep': 'сен', 'Oct': 'окт', 'Nov': 'ноя', 'Dec': 'дек'
    }

    result = tashkent_dt.strftime(python_format)
    for eng, rus in month_names.items():
        result = result.replace(eng, rus)

    return result


@register.simple_tag
def current_tashkent_time():
    """Get current time in Tashkent timezone"""
    return timezone.now().astimezone(TASHKENT_TZ)


@register.filter
def duration_format(seconds):
    """Format duration in seconds to human readable format"""
    if not seconds:
        return ""

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}ч {minutes}м {secs}с"
    elif minutes > 0:
        return f"{minutes}м {secs}с"
    else:
        return f"{secs}с"