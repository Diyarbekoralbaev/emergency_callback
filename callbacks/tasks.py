import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from django.utils import timezone
from .models import CallbackRequest, Rating, CallStatus
from callbacks.ambulance_system import complete_make_ambulance_call, ambulance_system

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def fixed_process_callback_call(self, callback_request_id):
    """
    Improved callback processing using static ambulance system with persistent connection
    """
    logger.info(f"Processing callback call for ID: {callback_request_id}")

    try:
        callback = CallbackRequest.objects.get(id=callback_request_id)
        logger.info(f"Found callback request: {callback}")

        # Update status to dialing
        callback.status = CallStatus.DIALING
        callback.call_started_at = timezone.now()
        callback.save()
        logger.info(f"Updated callback status to DIALING")

        # Execute the ambulance call using static system
        logger.info("Initiating ambulance call using static system...")
        result = async_to_sync(complete_make_ambulance_call)(callback)
        logger.info(f"Ambulance call completed with result: {result}")

        # Update callback with end time
        callback.call_ended_at = timezone.now()

        if result['success']:
            # Set status based on the detailed final_status from ambulance system
            final_status = result.get('final_status', 'completed')

            # Map ambulance system statuses to Django model statuses
            status_mapping = {
                'transferred': CallStatus.TRANSFERRED,
                'completed': CallStatus.COMPLETED,
                'no_rating': CallStatus.NO_RATING,
                'failed': CallStatus.FAILED,
            }

            callback.status = status_mapping.get(final_status, CallStatus.COMPLETED)
            callback.call_id = result.get('call_id')
            callback.transferred = result.get('transferred', False)

            # Set call duration if available
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

        # Try to update the callback status to failed if we can
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

        logger.info(f"Cleaned up stale call {call.id}: {call.phone_number} -> {call.status}")

    logger.info(f"Cleanup completed. Updated {updated_count} stale calls.")
    return updated_count


@shared_task
def check_ambulance_system_health():
    """
    Health check task for the static ambulance system
    """
    logger.info("Checking ambulance system health...")

    try:
        # Get system status
        status = async_to_sync(ambulance_system.get_system_status)()

        logger.info(f"Ambulance system status: {status}")

        # Check if system needs initialization
        if not status['initialized'] or status['connection_state'] != 'connected':
            logger.warning("Ambulance system not properly initialized, attempting to initialize...")
            success = async_to_sync(ambulance_system.initialize)()

            if success:
                logger.info("Ambulance system successfully initialized")
            else:
                logger.error("Failed to initialize ambulance system")

        return status

    except Exception as e:
        logger.error(f"Error checking ambulance system health: {e}", exc_info=True)
        return {
            'error': str(e),
            'connection_state': 'unknown',
            'initialized': False
        }


@shared_task
def initialize_ambulance_system():
    """
    Task to explicitly initialize the ambulance system (useful for startup)
    """
    logger.info("Initializing ambulance system...")

    try:
        success = async_to_sync(ambulance_system.initialize)()

        if success:
            status = async_to_sync(ambulance_system.get_system_status)()
            logger.info(f"Ambulance system initialized successfully: {status}")
            return {'success': True, 'status': status}
        else:
            logger.error("Failed to initialize ambulance system")
            return {'success': False, 'error': 'Initialization failed'}

    except Exception as e:
        logger.error(f"Error initializing ambulance system: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


@shared_task
def graceful_shutdown_ambulance_system():
    """
    Task to gracefully shutdown the ambulance system (useful for maintenance)
    """
    logger.info("Shutting down ambulance system...")

    try:
        async_to_sync(ambulance_system.shutdown)()
        logger.info("Ambulance system shut down successfully")
        return {'success': True}

    except Exception as e:
        logger.error(f"Error shutting down ambulance system: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}