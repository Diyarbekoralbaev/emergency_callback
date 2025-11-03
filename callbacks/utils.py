# callbacks/utils.py
from django.utils import timezone
import pytz
from django.contrib import messages
from eskiz_sms import EskizSMS
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Tashkent timezone
TASHKENT_TZ = pytz.timezone('Asia/Tashkent')

def to_tashkent_time(utc_datetime):
    """Convert UTC datetime to Tashkent timezone"""
    if not utc_datetime:
        return None
    if timezone.is_naive(utc_datetime):
        utc_datetime = timezone.make_aware(utc_datetime, pytz.UTC)
    return utc_datetime.astimezone(TASHKENT_TZ)

def get_tashkent_now():
    """Get current time in Tashkent timezone"""
    return timezone.now().astimezone(TASHKENT_TZ)

# Russian error messages
RUSSIAN_MESSAGES = {
    'callback_created': 'Экстренный вызов создан! Звоним на номер {phone_number}...',
    'callback_not_found': 'Запрос обратного вызова не найден',
    'invalid_phone': 'Некорректный номер телефона',
    'team_required': 'Необходимо выбрать бригаду',
    'region_required': 'Необходимо выбрать регион',
    'permission_denied': 'У вас нет прав для выполнения этого действия',
    'invalid_data': 'Переданы некорректные данные',
    'system_error': 'Произошла системная ошибка. Попробуйте позже.',
    'no_active_teams': 'Нет активных бригад для выполнения вызова',
    'call_in_progress': 'Вызов уже выполняется',
    'rating_saved': 'Оценка успешно сохранена',
    'invalid_rating': 'Некорректная оценка (должна быть от 1 до 5)',
}

def get_message(key, **kwargs):
    """Get Russian message with formatting"""
    message = RUSSIAN_MESSAGES.get(key, key)
    return message.format(**kwargs) if kwargs else message


def send_sms(phone_number, message):
    """Send SMS using EskizSMS service"""
    try:
        eskiz = EskizSMS(
            email=settings.ESKIZ_EMAIL,
            password=settings.ESKIZ_PASSWORD,
        )
        eskiz.send_sms(
            mobile_phone=phone_number,
            message=message,
        )
        logger.info(f"SMS sent successfully to {phone_number}")
        return True
    except Exception as e:
        logger.error(f"Failed to send SMS to {phone_number}: {e}")
        return False