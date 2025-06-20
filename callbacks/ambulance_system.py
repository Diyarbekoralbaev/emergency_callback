"""
Fixed ambulance system - passes callback_request_id for proper rating saves
"""
import asyncio
import logging
import uuid
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum
import panoramisk
from django.conf import settings
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

class CallState(Enum):
    DIALING = "dialing"
    CONNECTING = "connecting"
    ANSWERED = "answered"
    WAITING_RATING = "waiting_rating"
    RATING_RECEIVED = "rating_received"
    WAITING_ADDITIONAL = "waiting_additional"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class CallInfo:
    call_id: str
    phone: str
    callback_request_id: Optional[int] = None  # Added this field
    brigade: Optional[str] = None
    status: str = "DIALING"
    state: CallState = CallState.DIALING
    uniqueid: Optional[str] = None
    channel: Optional[str] = None
    rating: Optional[int] = None
    additional_questions: Optional[bool] = None
    transferred: bool = False
    error: Optional[str] = None

@dataclass
class CallResult:
    success: bool
    call_id: Optional[str] = None
    error: Optional[str] = None
    rating: Optional[int] = None
    transferred: bool = False

class DjangoRatingManager:
    """Rating manager that saves to Django models"""

    @sync_to_async
    def save_rating(self, call_info: CallInfo) -> bool:
        """Save rating to Django models using callback_request_id"""
        try:
            from .models import CallbackRequest, Rating

            # Find the callback request by ID instead of call_id
            if call_info.callback_request_id:
                callback = CallbackRequest.objects.get(id=call_info.callback_request_id)
            else:
                # Fallback to call_id lookup if callback_request_id not available
                callback = CallbackRequest.objects.get(call_id=call_info.call_id)

            # Create rating
            Rating.objects.create(
                callback_request=callback,
                rating=call_info.rating,
                phone_number=call_info.phone,
                team=callback.team if hasattr(callback, 'team') else None
            )

            # Update callback status and call_id if not set
            callback.status = 'rating_received'
            if not callback.call_id:
                callback.call_id = call_info.call_id
            callback.save()

            logger.info(f"Rating saved for call {call_info.call_id}, callback_request_id: {call_info.callback_request_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save rating: {e}")
            return False

class AudioManager:
    """Handles audio playback"""

    def __init__(self, manager):
        self.manager = manager

    async def play_audio(self, channel: str, audio_key: str):
        """Play audio file using dialplan redirect"""
        try:
            config = settings.AMBULANCE_CONFIG
            audio_file = config['AUDIO_FILES'].get(audio_key)
            if not audio_file:
                logger.error(f"Unknown audio key: {audio_key}")
                return False

            logger.info(f"Playing {audio_file} on {channel}")

            await self.manager.send_action({
                'Action': 'Redirect',
                'Channel': channel,
                'Context': 'play-audio',
                'Exten': audio_file,
                'Priority': '1'
            })
            return True

        except Exception as e:
            logger.error(f"Failed to play {audio_key}: {e}")
            return False

class CallManager:
    """Manages call state and operations"""

    def __init__(self, manager, audio_manager: AudioManager, rating_manager: DjangoRatingManager):
        self.manager = manager
        self.audio_manager = audio_manager
        self.rating_manager = rating_manager

        self.active_calls: Dict[str, CallInfo] = {}
        self.pending_calls: Dict[str, CallInfo] = {}
        self.pending_actions: Dict[str, CallInfo] = {}
        self.uniqueid_to_callid: Dict[str, str] = {}
        self.rating_retries: Dict[str, int] = {}

    async def make_callback_call(self, phone_number: str, brigade_id: str = None, callback_request_id: int = None) -> CallResult:
        """Initiate a callback call"""
        call_id = str(uuid.uuid4())
        formatted_number = self._format_phone_number(phone_number)

        call_info = CallInfo(
            call_id=call_id,
            phone=phone_number,
            brigade=brigade_id,
            callback_request_id=callback_request_id  # Store the callback_request_id
        )

        self.pending_calls[call_id] = call_info

        try:
            config = settings.AMBULANCE_CONFIG
            result = await self.manager.send_action({
                'Action': 'Originate',
                'Channel': f'PJSIP/{formatted_number}@skyline-trunk',
                'Context': 'ambulance-callback',
                'Exten': 's',
                'Priority': '1',
                'CallerID': config['CALLER_ID'],
                'Variable': f'CALL_ID={call_id},PHONE_NUMBER={phone_number},BRIGADE_ID={brigade_id or ""},CALLBACK_REQUEST_ID={callback_request_id or ""}',
                'Timeout': f'{config.get("CALL_TIMEOUT", 30) * 1000}',
                'Async': 'true'
            })

            # Store ActionID for failure detection
            actionid = self._extract_action_id(result)
            if actionid:
                self.pending_actions[actionid] = call_info

            # Set timeout
            asyncio.create_task(self._handle_call_timeout(call_id))

            logger.info(f"Call {call_id} initiated to {formatted_number} for callback_request_id: {callback_request_id}")
            return CallResult(success=True, call_id=call_id)

        except Exception as e:
            logger.error(f"Failed to originate call: {e}")
            self.pending_calls.pop(call_id, None)
            return CallResult(success=False, error=str(e))

    def _extract_action_id(self, result) -> Optional[str]:
        """Extract ActionID from result"""
        if isinstance(result, list) and result:
            return result[0].get('ActionID')
        elif hasattr(result, 'get'):
            return result.get('ActionID')
        return None

    def _format_phone_number(self, phone_number: str) -> str:
        """Format phone number for dialing"""
        clean_number = ''.join(filter(str.isdigit, phone_number)) # noqa

        if clean_number.startswith('998'):
            return clean_number
        elif clean_number.startswith('9') and len(clean_number) == 9:
            return f'998{clean_number}'
        elif len(clean_number) == 9:
            return f'998{clean_number}'
        return clean_number

    async def _handle_call_timeout(self, call_id: str):
        """Handle timeout for pending calls"""
        config = settings.AMBULANCE_CONFIG
        await asyncio.sleep(config.get('CALL_TIMEOUT', 30))

        if call_id in self.pending_calls:
            call_info = self.pending_calls.pop(call_id)
            call_info.status = 'FAILED'
            call_info.error = 'Call timeout'
            call_info.state = CallState.FAILED

            logger.warning(f"Call {call_id} failed due to timeout")

    async def handle_dtmf_input(self, uniqueid: str, digit: str) -> bool:
        """Handle DTMF input for active calls"""
        if uniqueid not in self.active_calls:
            return False

        call_info = self.active_calls[uniqueid]

        if call_info.state == CallState.WAITING_RATING and digit in '12345':
            return await self._handle_rating_input(call_info, digit)

        elif call_info.state == CallState.WAITING_ADDITIONAL:
            return await self._handle_additional_input(call_info, digit)

        else:
            await self.audio_manager.play_audio(call_info.channel, 'rating_invalid')
            return False

    async def _handle_rating_input(self, call_info: CallInfo, digit: str) -> bool:
        """Handle rating DTMF input"""
        call_info.rating = int(digit)
        call_info.state = CallState.RATING_RECEIVED

        # Clear retries
        if call_info.uniqueid in self.rating_retries:
            del self.rating_retries[call_info.uniqueid]

        logger.info(f"Rating {digit} received for call {call_info.call_id}")

        # Save rating to Django
        await self.rating_manager.save_rating(call_info)

        # Continue with flow
        await self.audio_manager.play_audio(call_info.channel, 'rating_thankyou')
        await asyncio.sleep(3)
        call_info.state = CallState.WAITING_ADDITIONAL
        await self.audio_manager.play_audio(call_info.channel, 'additional_questions')

        return True

    async def _handle_additional_input(self, call_info: CallInfo, digit: str) -> bool:
        """Handle additional questions DTMF input"""
        if digit == '0':
            # Transfer to operator
            call_info.additional_questions = True
            call_info.transferred = True
            call_info.state = CallState.TRANSFERRING

            await self.audio_manager.play_audio(call_info.channel, 'transfer_message')
            await asyncio.sleep(3)
            await self._transfer_to_operator(call_info.channel)
            return True

        elif digit in '123456789':
            # No additional questions
            call_info.additional_questions = False
            call_info.state = CallState.COMPLETED

            await self.audio_manager.play_audio(call_info.channel, 'goodbye')
            await asyncio.sleep(3)
            await self._hangup_call(call_info.channel)
            return True

        return False

    async def _transfer_to_operator(self, channel: str):
        """Transfer call to operator"""
        try:
            config = settings.AMBULANCE_CONFIG
            await self.manager.send_action({
                'Action': 'Redirect',
                'Channel': channel,
                'Context': 'internal',
                'Exten': config.get('OPERATOR_EXTENSION', '101'),
                'Priority': '1'
            })
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            await self.audio_manager.play_audio(channel, 'transfer_error')
            await asyncio.sleep(3)
            await self._hangup_call(channel)

    async def _hangup_call(self, channel: str):
        """Hangup call"""
        try:
            await self.manager.send_action({
                'Action': 'Hangup',
                'Channel': channel
            })
        except Exception as e:
            logger.error(f"Failed to hangup: {e}")

class CompleteAmbulanceSystem:
    """Complete ambulance callback system with event handling"""

    def __init__(self):
        self.manager = None
        self.rating_manager = DjangoRatingManager()
        self.audio_manager = None
        self.call_manager = None
        self.call_results = {}  # Store final results

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()

    async def connect(self) -> bool:
        """Connect to Asterisk AMI"""
        try:
            config = settings.AMBULANCE_CONFIG

            self.manager = panoramisk.Manager(
                loop=asyncio.get_event_loop(),
                host=config['AMI_HOST'],
                port=config['AMI_PORT'],
                username=config['AMI_USERNAME'],
                secret=config['AMI_SECRET']
            )

            await self.manager.connect()

            # Initialize managers
            self.audio_manager = AudioManager(self.manager)
            self.call_manager = CallManager(self.manager, self.audio_manager, self.rating_manager)

            # Register event handlers
            self._register_event_handlers()

            logger.info("Connected to Asterisk AMI")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to AMI: {e}")
            return False

    def _register_event_handlers(self):
        """Register AMI event handlers"""
        self.manager.register_event('OriginateResponse', self._handle_originate_response)
        self.manager.register_event('Newexten', self._handle_newexten)
        self.manager.register_event('DTMFEnd', self._handle_dtmf)
        self.manager.register_event('Hangup', self._handle_hangup)

    def _handle_originate_response(self, manager, message):
        """Handle OriginateResponse events"""
        asyncio.create_task(self._process_originate_response(message))

    async def _process_originate_response(self, message):
        """Process OriginateResponse events"""
        actionid = message.get('ActionID', '')
        response = message.get('Response', '')
        reason = message.get('Reason', '')
        uniqueid = message.get('Uniqueid', '')

        if actionid in self.call_manager.pending_actions:
            call_info = self.call_manager.pending_actions[actionid]

            if response == 'Failure':
                call_info.status = 'FAILED'
                call_info.error = f"Call failed: {reason}"
                call_info.state = CallState.FAILED

                # Store result
                self.call_results[call_info.call_id] = CallResult(
                    success=False,
                    call_id=call_info.call_id,
                    error=call_info.error
                )

            elif response == 'Success':
                call_info.status = 'CONNECTING'
                call_info.state = CallState.CONNECTING
                call_info.uniqueid = uniqueid
                if uniqueid:
                    self.call_manager.uniqueid_to_callid[uniqueid] = call_info.call_id

    def _handle_newexten(self, manager, message):
        """Handle Newexten events"""
        asyncio.create_task(self._process_newexten(message))

    async def _process_newexten(self, message):
        """Process call answer events"""
        context = message.get('Context', '')
        application = message.get('Application', '')
        app_data = message.get('AppData', '')
        uniqueid = message.get('Uniqueid', '')
        channel = message.get('Channel', '')

        if (context == 'ambulance-callback' and
                application == 'NoOp' and
                'Ambulance callback - Call ID:' in app_data):

            call_id = app_data.split('Call ID: ')[-1].strip()

            if call_id in self.call_manager.pending_calls:
                call_info = self.call_manager.pending_calls.pop(call_id)
                call_info.status = 'ANSWERED'
                call_info.uniqueid = uniqueid
                call_info.channel = channel
                call_info.state = CallState.ANSWERED

                self.call_manager.active_calls[uniqueid] = call_info

                logger.info(f"Call {call_id} answered")

                # Start rating request
                await asyncio.sleep(3)
                call_info.state = CallState.WAITING_RATING
                await self.audio_manager.play_audio(channel, 'rating_request')

    def _handle_dtmf(self, manager, message):
        """Handle DTMF events"""
        asyncio.create_task(self._process_dtmf(message))

    async def _process_dtmf(self, message):
        """Process DTMF input"""
        uniqueid = message.get('Uniqueid', '')
        digit = message.get('Digit', '')
        direction = message.get('Direction', 'Received')

        if direction == 'Sent':
            return

        await self.call_manager.handle_dtmf_input(uniqueid, digit)

    def _handle_hangup(self, manager, message):
        """Handle hangup events"""
        asyncio.create_task(self._process_hangup(message))

    async def _process_hangup(self, message):
        """Process hangup events"""
        uniqueid = message.get('Uniqueid', '')

        if uniqueid in self.call_manager.active_calls:
            call_info = self.call_manager.active_calls.pop(uniqueid)

            # Store final result
            self.call_results[call_info.call_id] = CallResult(
                success=True,
                call_id=call_info.call_id,
                rating=call_info.rating,
                transferred=call_info.transferred
            )

            logger.info(f"Call {call_info.call_id} completed")

            # Cleanup
            self.call_manager.uniqueid_to_callid.pop(uniqueid, None)
            self.call_manager.rating_retries.pop(uniqueid, None)

    async def disconnect(self):
        """Disconnect from AMI"""
        if self.manager:
            try:
                close_result = self.manager.close()
                if close_result is not None:
                    await close_result
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")

    async def make_callback_call(self, phone_number: str, brigade_id: str = None, callback_request_id: int = None) -> CallResult:
        """Make a callback call and wait for completion"""
        result = await self.call_manager.make_callback_call(phone_number, brigade_id, callback_request_id)

        if not result.success:
            return result

        # Wait for call to complete or timeout
        timeout = settings.AMBULANCE_CONFIG.get('CALL_TIMEOUT', 30) + 60  # Extra time for rating

        for _ in range(timeout):
            await asyncio.sleep(1)
            if result.call_id in self.call_results:
                return self.call_results[result.call_id]

        # Timeout
        return CallResult(success=False, call_id=result.call_id, error="Call timeout")

# Django integration function
async def complete_make_ambulance_call(callback_request) -> dict:
    """
    Complete ambulance call with full flow
    """
    try:
        async with CompleteAmbulanceSystem() as system:
            phone_number = callback_request.phone_number
            brigade_id = callback_request.team.id if callback_request.team else None
            callback_request_id = callback_request.id  # Pass the callback_request_id

            result = await system.make_callback_call(phone_number, brigade_id, callback_request_id)

            if result.success:
                # Update callback request
                callback_request.call_id = result.call_id
                await sync_to_async(callback_request.save)()

                return {
                    'success': True,
                    'call_id': result.call_id,
                    'rating': result.rating,
                    'transferred': result.transferred
                }
            else:
                return {
                    'success': False,
                    'error': result.error,
                    'call_id': result.call_id
                }

    except Exception as e:
        logger.error(f"Error in complete_make_ambulance_call: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'call_id': None
        }