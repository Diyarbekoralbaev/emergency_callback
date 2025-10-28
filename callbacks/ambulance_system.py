"""
Simplified ambulance callback system - fresh connection per call
No singletons, no persistent connections, no event loop issues
"""
import asyncio
import logging
import uuid
import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum
import panoramisk
from django.conf import settings
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


class CallState(Enum):
    DIALING = "dialing"
    ANSWERED = "answered"
    WAITING_RATING = "waiting_rating"
    RATING_RECEIVED = "rating_received"
    WAITING_TRANSFER_DECISION = "waiting_transfer_decision"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CallInfo:
    call_id: str
    phone: str
    callback_request_id: Optional[int] = None
    brigade: Optional[str] = None
    state: CallState = CallState.DIALING
    uniqueid: Optional[str] = None
    channel: Optional[str] = None
    rating: Optional[int] = None
    transferred: bool = False
    error: Optional[str] = None
    answered_at: Optional[float] = None
    created_at: float = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()


@dataclass
class CallResult:
    success: bool
    call_id: Optional[str] = None
    error: Optional[str] = None
    rating: Optional[int] = None
    transferred: bool = False
    final_status: Optional[str] = None
    call_duration: Optional[int] = None


class RatingManager:
    """Saves ratings to Django database"""

    @staticmethod
    async def save_rating(call_info: CallInfo):
        """Save rating to database"""
        try:
            from callbacks.models import Rating, CallbackRequest

            if call_info.rating is None:
                return

            callback_request = await sync_to_async(
                CallbackRequest.objects.get
            )(id=call_info.callback_request_id)

            rating_obj = await sync_to_async(Rating.objects.create)(
                callback_request=callback_request,
                rating=call_info.rating,
                phone_number=callback_request.phone_number,
                team=callback_request.team            )

            logger.info(f"Rating {call_info.rating} saved for call {call_info.call_id}")

        except Exception as e:
            logger.error(f"Failed to save rating: {e}")


class SimpleAMIConnection:
    """Simple AMI connection wrapper"""

    def __init__(self, config):
        self.config = config
        self.manager = None
        self.call_info = None
        self.rating_manager = RatingManager()
        self.call_complete_event = asyncio.Event()
        self.rating_retries = {}

    async def connect(self):
        """Connect to AMI"""
        try:
            # Get the current running event loop (from async_to_sync)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # If no loop is running, create one
                loop = asyncio.get_event_loop()

            self.manager = panoramisk.Manager(
                loop=loop,
                host=self.config['AMI_HOST'],
                port=int(self.config['AMI_PORT']),
                username=self.config['AMI_USERNAME'],
                secret=self.config['AMI_SECRET']
            )

            await self.manager.connect()
            logger.info("Connected to Asterisk AMI")

            # Register event handlers
            self.manager.register_event('UserEvent', self._handle_user_event)
            self.manager.register_event('Hangup', self._handle_hangup)
            self.manager.register_event('DTMFEnd', self._handle_dtmf_event)  # DTMFEnd not DTMF!
            self.manager.register_event('Newchannel', self._handle_newchannel)  # Capture channel name
            self.manager.register_event('OriginateResponse', self._handle_originate_response)  # Track originate
            self.manager.register_event('Newexten', self._handle_newexten)  # Track call progress

            return True

        except Exception as e:
            logger.error(f"Failed to connect to AMI: {e}")
            return False

    async def disconnect(self):
        """Disconnect from AMI"""
        if self.manager:
            try:
                await self.manager.close()
            except:
                pass
            self.manager = None
        logger.info("Disconnected from AMI")

    async def originate_call(self, phone_number: str, brigade_id: Optional[int],
                             callback_request_id: Optional[int]) -> CallResult:
        """Originate a call and wait for completion"""

        call_id = str(uuid.uuid4())
        clean_phone = self._format_phone_number(phone_number)

        self.call_info = CallInfo(
            call_id=call_id,
            phone=phone_number,
            callback_request_id=callback_request_id,
            brigade=str(brigade_id) if brigade_id else None
        )

        try:
            # Originate the call
            action = {
                'Action': 'Originate',
                'Channel': f'Local/{clean_phone}@from-internal',
                'Context': 'ambulance-callback',
                'Exten': 's',
                'Priority': '1',
                'CallerID': f'Ambulance <{self.config.get("CALLER_ID", "103")}>',
                'Timeout': str(self.config.get('ORIGINATE_TIMEOUT', 30000)),
                'Async': 'true',
                'Variable': [
                    f'CALL_ID={call_id}',
                    f'PHONE_NUMBER={phone_number}',
                    f'BRIGADE_ID={brigade_id or ""}',
                    f'CALLBACK_REQUEST_ID={callback_request_id or ""}'
                ]
            }

            result = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=15.0
            )

            logger.info(f"Call {call_id} originated to {clean_phone}")

            # Wait for call to complete (with timeout)
            try:
                await asyncio.wait_for(
                    self.call_complete_event.wait(),
                    timeout=self.config.get('CALL_TIMEOUT', 300)
                )
            except asyncio.TimeoutError:
                logger.warning(f"Call {call_id} timed out")
                self.call_info.error = "Call timeout"
                self.call_info.state = CallState.FAILED

            # Return result
            return self._build_result()

        except Exception as e:
            logger.error(f"Failed to originate call: {e}")
            self.call_info.error = str(e)
            self.call_info.state = CallState.FAILED
            return self._build_result()

    def _build_result(self) -> CallResult:
        """Build call result from call info"""
        if self.call_info.state == CallState.FAILED:
            success = False
            final_status = 'failed'
        elif self.call_info.transferred:
            success = True
            final_status = 'transferred'
        elif self.call_info.rating is not None:
            success = True
            final_status = 'completed'
        else:
            success = True
            final_status = 'no_rating'

        call_duration = None
        if self.call_info.answered_at:
            call_duration = int(time.time() - self.call_info.answered_at)

        return CallResult(
            success=success,
            call_id=self.call_info.call_id,
            error=self.call_info.error,
            rating=self.call_info.rating,
            transferred=self.call_info.transferred,
            final_status=final_status,
            call_duration=call_duration
        )

    async def _handle_user_event(self, manager, event):
        """Handle Asterisk UserEvents"""
        if not self.call_info:
            return

        userevent = event.get('UserEvent', '')
        call_id = event.get('CallID', '')

        if call_id != self.call_info.call_id:
            return

        if userevent == 'CallAnswered':
            self.call_info.state = CallState.ANSWERED
            self.call_info.answered_at = time.time()
            self.call_info.uniqueid = event.get('Uniqueid')
            logger.info(f"Call {call_id} answered")

            # Play rating request
            await self._play_audio('rating_request')

        elif userevent == 'DTMFReceived':
            digit = event.get('Digit', '')
            await self._handle_dtmf(digit)

        elif userevent == 'CallEnded':
            logger.info(f"Call {call_id} ended")
            self.call_complete_event.set()

        elif userevent == 'AudioPlayed':
            audio = event.get('Audio', '')
            logger.info(f"Audio played: {audio}")

    async def _handle_hangup(self, manager, event):
        """Handle Hangup event"""
        if not self.call_info:
            return

        uniqueid = event.get('Uniqueid', '')
        if uniqueid == self.call_info.uniqueid:
            logger.info(f"Call {self.call_info.call_id} hung up")
            self.call_complete_event.set()

    async def _handle_dtmf_event(self, manager, event):
        """Handle DTMFEnd events"""
        if not self.call_info:
            return

        # DTMFEnd event has Channel, Digit, and Direction
        channel = event.get('Channel', '')
        digit = event.get('Digit', '')
        uniqueid = event.get('Uniqueid', '')
        direction = event.get('Direction', 'Received')

        # Only process received DTMF (from user), not sent (from Asterisk)
        if direction == 'Sent':
            return

        # Match by uniqueid or channel
        if uniqueid == self.call_info.uniqueid or (self.call_info.channel and channel == self.call_info.channel):
            logger.info(f"DTMF {digit} received for call {self.call_info.call_id}")
            await self._handle_dtmf(digit)

    async def _handle_newchannel(self, manager, event):
        """Handle Newchannel event to capture channel name"""
        if not self.call_info:
            return

        # Check if this is our call by looking at CallerIDNum or Exten
        channel = event.get('Channel', '')
        exten = event.get('Exten', '')
        calleridnum = event.get('CallerIDNum', '')

        # Match by extension (phone number we're calling)
        clean_phone = self._format_phone_number(self.call_info.phone)
        if exten == clean_phone or clean_phone in channel:
            if not self.call_info.channel:
                self.call_info.channel = channel
                self.call_info.uniqueid = event.get('Uniqueid')
                logger.info(f"Captured channel {channel} for call {self.call_info.call_id}")

    async def _handle_originate_response(self, manager, event):
        """Handle OriginateResponse event"""
        if not self.call_info:
            return

        response = event.get('Response', '')
        uniqueid = event.get('Uniqueid', '')

        logger.info(f"OriginateResponse for {self.call_info.call_id}: {response}")

    async def _handle_newexten(self, manager, event):
        """Handle Newexten event to track call progress"""
        if not self.call_info:
            return

        # This tracks extensions being executed
        uniqueid = event.get('Uniqueid', '')
        if uniqueid == self.call_info.uniqueid:
            context = event.get('Context', '')
            exten = event.get('Extension', '')
            app = event.get('Application', '')

            # Log context changes for debugging
            if context in ['ambulance-callback', 'play-audio', 'transfer-to-337']:
                logger.debug(f"Call {self.call_info.call_id} executing {app} in {context}:{exten}")

    async def _handle_dtmf(self, digit: str):
        """Handle DTMF input"""
        if self.call_info.state == CallState.WAITING_RATING:
            # Rating input (1-5)
            if digit in '12345':
                self.call_info.rating = int(digit)
                self.call_info.state = CallState.RATING_RECEIVED

                if self.call_info.uniqueid in self.rating_retries:
                    del self.rating_retries[self.call_info.uniqueid]

                logger.info(f"Rating {digit} received for call {self.call_info.call_id}")

                # Save rating
                await self.rating_manager.save_rating(self.call_info)

                # Play thank you
                await self._play_audio('rating_thankyou')
                await asyncio.sleep(3)

                # Ask about transfer
                self.call_info.state = CallState.WAITING_TRANSFER_DECISION

            else:
                # Invalid rating
                await self._handle_invalid_rating()

        elif self.call_info.state == CallState.WAITING_TRANSFER_DECISION:
            # Transfer decision (0 or 9 for transfer)
            if digit in ['0', '9']:
                self.call_info.transferred = True
                self.call_info.state = CallState.TRANSFERRING
                logger.info(f"Transfer requested for call {self.call_info.call_id}")
                await self._transfer_to_operator()
            else:
                # No transfer wanted
                self.call_info.state = CallState.COMPLETED
                logger.info(f"Call {self.call_info.call_id} completed - no transfer")
                await self._hangup()

    async def _handle_invalid_rating(self):
        """Handle invalid rating input"""
        retry_limit = self.config.get('RATING_RETRY_LIMIT', 3)

        if self.call_info.uniqueid not in self.rating_retries:
            self.rating_retries[self.call_info.uniqueid] = 0

        self.rating_retries[self.call_info.uniqueid] += 1

        if self.rating_retries[self.call_info.uniqueid] >= retry_limit:
            logger.warning(f"Too many invalid attempts for call {self.call_info.call_id}")
            await self._play_audio('rating_invalid')
            await asyncio.sleep(3)
            await self._hangup()
        else:
            await self._play_audio('rating_invalid')
            await asyncio.sleep(2)
            await self._play_audio('rating_request')

    async def _play_audio(self, audio_name: str):
        """Play audio by redirecting to play-audio context"""
        if not self.call_info.channel:
            # Get channel from uniqueid
            if self.call_info.uniqueid:
                self.call_info.channel = await self._get_channel_from_uniqueid(
                    self.call_info.uniqueid
                )

        if not self.call_info.channel:
            logger.error("No channel available for audio playback")
            return

        try:
            audio_map = {
                'rating_request': 'ambulance-rating-request',
                'rating_thankyou': 'ambulance-rating-thankyou',
                'rating_invalid': 'ambulance-rating-invalid',
                'transfer_message': 'ambulance-transfer-message',
                'transfer_error': 'ambulance-transfer-error'
            }

            exten = audio_map.get(audio_name, audio_name)

            # Update state for rating request
            if audio_name == 'rating_request':
                self.call_info.state = CallState.WAITING_RATING

            await self.manager.send_action({
                'Action': 'Redirect',
                'Channel': self.call_info.channel,
                'Context': 'play-audio',
                'Exten': exten,
                'Priority': '1'
            })

            logger.info(f"Playing {audio_name} on {self.call_info.channel}")

        except Exception as e:
            logger.error(f"Failed to play audio: {e}")

    async def _transfer_to_operator(self):
        """Transfer call to extension 337"""
        try:
            await self.manager.send_action({
                'Action': 'Redirect',
                'Channel': self.call_info.channel,
                'Context': 'transfer-to-337',
                'Exten': 's',
                'Priority': '1'
            })
            logger.info(f"Transfer initiated to extension 337")
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            await self._hangup()

    async def _hangup(self):
        """Hangup call"""
        try:
            await self.manager.send_action({
                'Action': 'Hangup',
                'Channel': self.call_info.channel
            })
        except Exception as e:
            logger.error(f"Failed to hangup: {e}")

    async def _get_channel_from_uniqueid(self, uniqueid: str) -> Optional[str]:
        """Get channel name from uniqueid"""
        try:
            result = await self.manager.send_action({
                'Action': 'CoreShowChannels'
            })

            if isinstance(result, list):
                for item in result:
                    if item.get('Uniqueid') == uniqueid:
                        return item.get('Channel')

        except Exception as e:
            logger.error(f"Failed to get channel: {e}")

        return None

    def _format_phone_number(self, phone_number: str) -> str:
        """Format phone number for dialing"""
        clean_number = ''.join(filter(str.isdigit, phone_number))
        # Remove 998 prefix if exists
        if clean_number.startswith('998') and len(clean_number) == 12:
            return clean_number[3:]
        return clean_number


# Main function to make ambulance call
async def make_ambulance_call(phone_number: str, brigade_id: Optional[int] = None,
                              callback_request_id: Optional[int] = None) -> CallResult:
    """
    Make an ambulance callback call
    Simple: connect -> call -> disconnect
    """
    config = settings.AMBULANCE_CONFIG
    connection = SimpleAMIConnection(config)

    try:
        # Connect
        if not await connection.connect():
            return CallResult(
                success=False,
                error="Failed to connect to AMI",
                final_status='failed'
            )

        # Make call
        result = await connection.originate_call(
            phone_number,
            brigade_id,
            callback_request_id
        )

        return result

    except Exception as e:
        logger.error(f"Error in make_ambulance_call: {e}", exc_info=True)
        return CallResult(
            success=False,
            error=str(e),
            final_status='failed'
        )

    finally:
        # Always disconnect
        await connection.disconnect()


# Django integration function
async def complete_make_ambulance_call(callback_request) -> dict:
    """
    Complete ambulance call - Django integration
    """
    try:
        phone_number = callback_request.phone_number
        brigade_id = callback_request.team.id if callback_request.team else None
        callback_request_id = callback_request.id

        result = await make_ambulance_call(phone_number, brigade_id, callback_request_id)

        if result.success:
            # Update callback request
            callback_request.call_id = result.call_id
            await sync_to_async(callback_request.save)()

            return {
                'success': True,
                'call_id': result.call_id,
                'rating': result.rating,
                'transferred': result.transferred,
                'final_status': result.final_status,
                'call_duration': result.call_duration
            }
        else:
            return {
                'success': False,
                'error': result.error,
                'call_id': result.call_id,
                'final_status': result.final_status or 'failed'
            }

    except Exception as e:
        logger.error(f"Error in complete_make_ambulance_call: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'call_id': None,
            'final_status': 'failed'
        }
