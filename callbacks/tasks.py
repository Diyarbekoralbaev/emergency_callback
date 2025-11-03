import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from django.utils import timezone
from .models import CallbackRequest, CallStatus

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_callback_call(self, callback_request_id):
    """
    Process callback call - simple version with fresh connection each time
    """
    logger.info(f"Processing callback call for ID: {callback_request_id}")

    try:
        # Get callback request
        callback = CallbackRequest.objects.get(id=callback_request_id)
        logger.info(f"Found callback request: {callback}")

        # Update status to dialing
        callback.status = CallStatus.DIALING
        callback.call_started_at = timezone.now()
        callback.save()
        logger.info("Updated callback status to DIALING")

        # Import here to avoid circular imports
        from callbacks.ambulance_system import complete_make_ambulance_call

        # Make the call (fresh connection each time)
        logger.info("Initiating ambulance call...")
        result = async_to_sync(complete_make_ambulance_call)(callback)
        logger.info(f"Ambulance call completed with result: {result}")

        # Update callback with end time
        callback.call_ended_at = timezone.now()

        if result['success']:
            # Map final_status to Django status
            final_status = result.get('final_status', 'completed')

            status_mapping = {
                'transferred': CallStatus.TRANSFERRED,
                'completed': CallStatus.COMPLETED,
                'no_rating': CallStatus.NO_RATING,
                'failed': CallStatus.FAILED,
            }

            callback.status = status_mapping.get(final_status, CallStatus.COMPLETED)
            callback.call_id = result.get('call_id')
            callback.transferred = result.get('transferred', False)

            if result.get('call_duration'):
                callback.call_duration = result['call_duration']

            logger.info(f"Call successful with status: {callback.status}")

        else:
            # Call failed
            callback.status = CallStatus.FAILED
            callback.error_message = result.get('error', 'Unknown error')
            logger.error(f"Call failed: {callback.error_message}")

        # Save the updated callback
        callback.save()
        logger.info("Callback request updated and saved successfully")

        return {
            'success': result['success'],
            'call_id': result.get('call_id'),
            'status': callback.status,
            'rating': result.get('rating'),
            'transferred': result.get('transferred', False),
            'call_duration': result.get('call_duration'),
            'error': result.get('error') if not result['success'] else None
        }

    except CallbackRequest.DoesNotExist:
        error_msg = f"CallbackRequest {callback_request_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'call_id': None,
            'status': 'failed'
        }

    except Exception as exc:
        logger.error(f"Exception in callback processing: {exc}", exc_info=True)

        # Try to update the callback status to failed
        try:
            callback = CallbackRequest.objects.get(id=callback_request_id)
            callback.status = CallStatus.FAILED
            callback.error_message = f"Processing error: {str(exc)}"
            callback.call_ended_at = timezone.now()
            callback.save()
        except:
            logger.error("Failed to update callback status after exception")

        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying task, attempt {self.request.retries + 1}")
            raise self.retry(countdown=60, exc=exc)

        return {
            'success': False,
            'error': str(exc),
            'call_id': None,
            'status': 'failed'
        }


@shared_task(bind=True, max_retries=2)
def send_rating_sms(self, callback_request_id):
    """
    Send SMS with rating link if call didn't get rating
    """
    logger.info(f"Sending rating SMS for callback ID: {callback_request_id}")

    try:
        callback = CallbackRequest.objects.get(id=callback_request_id)

        # Check if already sent
        if callback.sms_sent:
            logger.info(f"SMS already sent for callback {callback.id}")
            return {'success': True, 'message': 'SMS already sent'}

        # Check if already has rating
        if callback.has_rating:
            logger.info(f"Callback {callback.id} already has rating, no SMS needed")
            return {'success': True, 'message': 'Already has rating'}

        # Import SMS utility
        from .utils import send_sms

        # Prepare SMS message
        vote_url = callback.vote_url
        message = (
            f"Assalawma aleykum. Sizge ko'rsetilgen tez medecinaliq xizmetin bahalaw ushin "
            f"to'mende ko'rsetilgen siltemege o'tip bahalawinizdi soranamiz. {vote_url}"
        )

        # Send SMS
        success = send_sms(callback.phone_number, message)

        if success:
            # Update callback
            callback.sms_sent = True
            callback.sms_sent_at = timezone.now()
            callback.status = CallStatus.WAITING_RATING
            callback.save()

            logger.info(f"SMS sent successfully to {callback.phone_number}")
            return {
                'success': True,
                'message': 'SMS sent successfully',
                'phone_number': callback.phone_number,
                'vote_url': vote_url
            }
        else:
            logger.error(f"Failed to send SMS to {callback.phone_number}")
            # Retry
            if self.request.retries < self.max_retries:
                logger.info(f"Retrying SMS send, attempt {self.request.retries + 1}")
                raise self.retry(countdown=30)

            return {
                'success': False,
                'error': 'Failed to send SMS'
            }

    except CallbackRequest.DoesNotExist:
        error_msg = f"CallbackRequest {callback_request_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }

    except Exception as exc:
        logger.error(f"Exception in SMS sending: {exc}", exc_info=True)

        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying SMS send, attempt {self.request.retries + 1}")
            raise self.retry(countdown=30, exc=exc)

        return {
            'success': False,
            'error': str(exc)
        }


@shared_task
def cleanup_stale_calls():
    """
    Cleanup task to handle calls that may have gotten stuck in intermediate states
    """
    from datetime import timedelta

    logger.info("Running cleanup for stale calls...")

    # Find calls that have been in intermediate states for too long
    stale_timeout = timezone.now() - timedelta(minutes=30)

    stale_statuses = [
        CallStatus.DIALING,
        CallStatus.CONNECTING,
        CallStatus.ANSWERED,
        CallStatus.WAITING_RATING,
        CallStatus.WAITING_ADDITIONAL,
        CallStatus.TRANSFERRING
    ]

    stale_calls = CallbackRequest.objects.filter(
        status__in=stale_statuses,
        call_started_at__lt=stale_timeout
    )

    updated_count = 0
    for call in stale_calls:
        # Determine appropriate final status based on current status
        if call.status in [CallStatus.DIALING, CallStatus.CONNECTING]:
            call.status = CallStatus.FAILED
            call.error_message = "Call cleanup: Failed to connect"
        elif call.status in [CallStatus.ANSWERED, CallStatus.WAITING_RATING, CallStatus.WAITING_ADDITIONAL]:
            call.status = CallStatus.NO_RATING
            call.error_message = "Call cleanup: Hung up without completing"
        elif call.status == CallStatus.TRANSFERRING:
            call.status = CallStatus.TRANSFERRED
            call.transferred = True

        call.call_ended_at = timezone.now()
        call.save()
        updated_count += 1

        # Send SMS if no rating and SMS not sent
        if not call.has_rating and not call.sms_sent:
            send_rating_sms.delay(call.id)

        logger.info(f"Cleaned up stale call {call.id}: {call.phone_number} -> {call.status}")

    logger.info(f"Cleanup completed. Updated {updated_count} stale calls.")
    return updated_count