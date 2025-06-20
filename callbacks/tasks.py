import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from django.utils import timezone
from .models import CallbackRequest, Rating, CallStatus
from .ambulance_system import complete_make_ambulance_call

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def fixed_process_callback_call(self, callback_request_id):
    """Fixed version that handles Django ORM properly"""
    logger.info(f"fixed_process_callback_call started for ID: {callback_request_id}")

    try:
        callback = CallbackRequest.objects.get(id=callback_request_id)
        logger.info(f"Found callback request: {callback}")

        callback.status = CallStatus.DIALING
        callback.call_started_at = timezone.now()
        callback.save()
        logger.info(f"Updated callback status to DIALING")

        logger.info("About to call async_to_sync(fixed_make_ambulance_call)")

        # Use the fixed version
        result = async_to_sync(complete_make_ambulance_call)(callback)

        logger.info(f"async_to_sync returned: {result}")

        callback.call_ended_at = timezone.now()

        if result['success']:
            callback.status = (
                CallStatus.RATING_RECEIVED
                if result.get('rating')
                else CallStatus.COMPLETED
            )
            callback.call_id = result.get('call_id')
            logger.info(f"Call successful, status: {callback.status}")
        else:
            callback.status = CallStatus.FAILED
            callback.error_message = result.get('error', 'Unknown error')
            logger.error(f"Call failed: {callback.error_message}")

        callback.save()
        logger.info("Callback request updated and saved")

        return result

    except CallbackRequest.DoesNotExist:
        error_msg = f"CallbackRequest {callback_request_id} not found"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg, 'call_id': None}

    except Exception as exc:
        logger.error(f"Exception in fixed_process_callback_call: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying task, attempt {self.request.retries + 1}")
            raise self.retry(countdown=60, exc=exc)
        return {'success': False, 'error': str(exc), 'call_id': None}
