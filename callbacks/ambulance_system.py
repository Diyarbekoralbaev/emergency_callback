"""
Fixed static ambulance system with improved cleanup and state management
"""
import asyncio
import logging
import uuid
import time
import weakref
from typing import Dict, Optional, List
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
    WAITING_TRANSFER_DECISION = "waiting_transfer_decision"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

@dataclass
class CallInfo:
    call_id: str
    phone: str
    callback_request_id: Optional[int] = None
    brigade: Optional[str] = None
    status: str = "DIALING"
    state: CallState = CallState.DIALING
    uniqueid: Optional[str] = None
    channel: Optional[str] = None
    rating: Optional[int] = None
    transferred: bool = False
    error: Optional[str] = None
    call_duration: Optional[int] = None
    answered_at: Optional[float] = None
    rating_attempts: int = 0
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

class ConnectionManager:
    """Manages AMI connection with health monitoring and auto-reconnection"""

    def __init__(self, config):
        self.config = config
        self.manager = None
        self.connection_state = ConnectionState.DISCONNECTED
        self.last_ping_time = 0
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = config.get('MAX_RECONNECT_ATTEMPTS', 5)
        self.reconnect_delay = config.get('RECONNECT_DELAY', 5)
        self.ping_interval = config.get('PING_INTERVAL', 30)
        self.connection_lock = asyncio.Lock()
        self.health_check_task = None
        self.event_handlers = {}
        self.last_successful_action = time.time()

    async def connect(self) -> bool:
        """Connect to Asterisk AMI with retry logic"""
        async with self.connection_lock:
            if self.connection_state == ConnectionState.CONNECTED:
                # Verify connection is actually working
                try:
                    await self._ping()
                    return True
                except:
                    logger.warning("Connection verification failed, reconnecting...")
                    self.connection_state = ConnectionState.DISCONNECTED

            self.connection_state = ConnectionState.CONNECTING

            try:
                logger.info(f"Connecting to AMI at {self.config['AMI_HOST']}:{self.config['AMI_PORT']}")

                # Close any existing connection first
                if self.manager:
                    try:
                        close_result = self.manager.close()
                        if close_result is not None:
                            await close_result
                    except:
                        pass
                    self.manager = None

                self.manager = panoramisk.Manager(
                    loop=asyncio.get_event_loop(),
                    host=self.config['AMI_HOST'],
                    port=int(self.config['AMI_PORT']),
                    username=self.config['AMI_USERNAME'],
                    secret=self.config['AMI_SECRET']
                )

                await self.manager.connect()

                # Test connection with ping
                await self._ping()

                self.connection_state = ConnectionState.CONNECTED
                self.reconnect_attempts = 0
                self.last_ping_time = time.time()
                self.last_successful_action = time.time()

                # Re-register event handlers
                self._register_event_handlers()

                # Start health monitoring
                if not self.health_check_task or self.health_check_task.done():
                    self.health_check_task = asyncio.create_task(self._health_monitor())

                logger.info("Successfully connected to Asterisk AMI")
                return True

            except Exception as e:
                logger.error(f"Failed to connect to AMI: {e}")
                self.connection_state = ConnectionState.FAILED
                self.manager = None
                return False

    async def disconnect(self):
        """Disconnect from AMI"""
        async with self.connection_lock:
            if self.health_check_task and not self.health_check_task.done():
                self.health_check_task.cancel()
                try:
                    await self.health_check_task
                except asyncio.CancelledError:
                    pass

            if self.manager:
                try:
                    close_result = self.manager.close()
                    if close_result is not None:
                        await close_result
                except Exception as e:
                    logger.error(f"Error disconnecting: {e}")
                finally:
                    self.manager = None

            self.connection_state = ConnectionState.DISCONNECTED
            logger.info("Disconnected from AMI")

    async def ensure_connected(self) -> bool:
        """Ensure we have a healthy connection"""
        if self.connection_state != ConnectionState.CONNECTED:
            return await self.connect()

        # Check if connection is still healthy
        try:
            await self._ping()
            self.last_successful_action = time.time()
            return True
        except Exception as e:
            logger.warning(f"Connection health check failed: {e}")
            return await self._reconnect()

    async def _ping(self):
        """Send ping to test connection"""
        if not self.manager:
            raise Exception("No AMI connection")

        result = await asyncio.wait_for(
            self.manager.send_action({'Action': 'Ping'}),
            timeout=5.0
        )
        self.last_ping_time = time.time()
        return result

    async def _reconnect(self) -> bool:
        """Attempt to reconnect"""
        if self.connection_state == ConnectionState.RECONNECTING:
            return False

        self.connection_state = ConnectionState.RECONNECTING

        while self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            logger.info(f"Reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}")

            try:
                await self.disconnect()
                await asyncio.sleep(self.reconnect_delay)

                if await self.connect():
                    logger.info("Successfully reconnected to AMI")
                    return True

            except Exception as e:
                logger.error(f"Reconnection attempt {self.reconnect_attempts} failed: {e}")

        logger.error("All reconnection attempts failed")
        self.connection_state = ConnectionState.FAILED
        return False

    async def _health_monitor(self):
        """Background task to monitor connection health"""
        while True:
            try:
                await asyncio.sleep(self.ping_interval)

                if self.connection_state == ConnectionState.CONNECTED:
                    # Check if we haven't had successful action recently
                    time_since_action = time.time() - self.last_successful_action
                    if time_since_action > self.ping_interval * 2:
                        logger.warning(f"No successful actions for {time_since_action}s, checking connection...")
                        try:
                            await self._ping()
                            self.last_successful_action = time.time()
                        except Exception as e:
                            logger.warning(f"Health check ping failed: {e}")
                            asyncio.create_task(self._reconnect())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")

    def register_event_handler(self, event_name, handler):
        """Register an event handler"""
        self.event_handlers[event_name] = handler
        if self.manager:
            self.manager.register_event(event_name, handler)

    def _register_event_handlers(self):
        """Re-register all event handlers after reconnection"""
        if self.manager:
            for event_name, handler in self.event_handlers.items():
                self.manager.register_event(event_name, handler)

    async def send_action(self, action):
        """Send action with connection retry"""
        if not await self.ensure_connected():
            raise Exception("Could not establish AMI connection")

        try:
            result = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=10.0
            )
            self.last_successful_action = time.time()
            return result
        except Exception as e:
            logger.error(f"Action failed: {e}")
            # Try to reconnect and retry once
            if await self._reconnect():
                result = await asyncio.wait_for(
                    self.manager.send_action(action),
                    timeout=10.0
                )
                self.last_successful_action = time.time()
                return result
            else:
                raise

class StaticAmbulanceSystem:
    """Static ambulance system with persistent connection and improved cleanup"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config = settings.AMBULANCE_CONFIG
        self.connection_manager = ConnectionManager(self.config)
        self.rating_manager = DjangoRatingManager()
        self.audio_manager = None
        self.channel_manager = None
        self.call_manager = None
        self.call_results = {}
        self._initialized = True
        self._setup_complete = False
        self._cleanup_task = None

    async def initialize(self) -> bool:
        """Initialize the system with persistent connection"""
        if self._setup_complete:
            # Just ensure connection is healthy
            healthy = await self.connection_manager.ensure_connected()
            if healthy:
                # Clean up any stale state
                await self._cleanup_stale_state()
            return healthy

        # First time setup
        if not await self.connection_manager.connect():
            return False

        # Initialize managers
        max_channels = self.config.get('MAX_CHANNELS', 2)
        self.channel_manager = ChannelManager(max_channels)
        self.audio_manager = AudioManager(self.connection_manager)
        self.call_manager = CallManager(
            self.connection_manager,
            self.audio_manager,
            self.rating_manager,
            self.channel_manager
        )

        # Register event handlers
        self._register_event_handlers()

        # Start cleanup task
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        self._setup_complete = True
        logger.info(f"Static ambulance system initialized with {max_channels} channels")
        return True

    async def _cleanup_stale_state(self):
        """Clean up any stale state from previous calls"""
        if not self.call_manager:
            return

        current_time = time.time()
        stale_timeout = 300  # 5 minutes

        # Clean up stale active calls
        stale_calls = []
        for uniqueid, call_info in self.call_manager.active_calls.items():
            if current_time - call_info.created_at > stale_timeout:
                stale_calls.append(uniqueid)

        for uniqueid in stale_calls:
            logger.warning(f"Cleaning up stale active call: {uniqueid}")
            call_info = self.call_manager.active_calls.pop(uniqueid, None)
            if call_info:
                self.channel_manager.release_channel(call_info.call_id)

        # Clean up stale pending calls
        stale_pending = []
        for call_id, call_info in self.call_manager.pending_calls.items():
            if current_time - call_info.created_at > stale_timeout:
                stale_pending.append(call_id)

        for call_id in stale_pending:
            logger.warning(f"Cleaning up stale pending call: {call_id}")
            call_info = self.call_manager.pending_calls.pop(call_id, None)
            if call_info:
                self.channel_manager.release_channel(call_info.call_id)

        # Clean up old call results
        old_results = []
        for call_id, result in self.call_results.items():
            # Results older than 1 hour
            if call_id in old_results or len(self.call_results) > 100:
                old_results.append(call_id)

        for call_id in old_results[:50]:  # Clean up max 50 at a time
            self.call_results.pop(call_id, None)

    async def _periodic_cleanup(self):
        """Periodic cleanup task"""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await self._cleanup_stale_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")

    def _register_event_handlers(self):
        """Register AMI event handlers"""
        self.connection_manager.register_event_handler('OriginateResponse', self._handle_originate_response)
        self.connection_manager.register_event_handler('Newexten', self._handle_newexten)
        self.connection_manager.register_event_handler('DTMFEnd', self._handle_dtmf)
        self.connection_manager.register_event_handler('Hangup', self._handle_hangup)
        self.connection_manager.register_event_handler('UserEvent', self._handle_user_event)

    def _handle_originate_response(self, manager, message):
        """Handle OriginateResponse events"""
        asyncio.create_task(self._process_originate_response(message))

    async def _process_originate_response(self, message):
        """Process OriginateResponse events"""
        if not self.call_manager:
            return

        actionid = message.get('ActionID', '')
        response = message.get('Response', '')
        reason = message.get('Reason', '')
        uniqueid = message.get('Uniqueid', '')

        if actionid in self.call_manager.pending_actions:
            call_info = self.call_manager.pending_actions.pop(actionid)  # Remove immediately

            if response == 'Failure':
                call_info.status = 'FAILED'
                call_info.error = f"Call failed: {reason}"
                call_info.state = CallState.FAILED

                # Clean up immediately
                self.call_manager.pending_calls.pop(call_info.call_id, None)
                self.channel_manager.release_channel(call_info.call_id)

                self.call_results[call_info.call_id] = CallResult(
                    success=False,
                    call_id=call_info.call_id,
                    error=call_info.error,
                    final_status='failed'
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
        if not self.call_manager:
            return

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
                call_info.answered_at = time.time()

                self.call_manager.active_calls[uniqueid] = call_info

                logger.info(f"Call {call_id} answered")

                # Start rating request after a delay
                asyncio.create_task(self._start_rating_flow(call_info))

    async def _start_rating_flow(self, call_info):
        """Start the rating flow for a call"""
        try:
            await asyncio.sleep(2)
            if call_info.uniqueid in self.call_manager.active_calls:
                call_info.state = CallState.WAITING_RATING
                await self.audio_manager.play_audio(call_info.channel, 'rating_request')
        except Exception as e:
            logger.error(f"Error starting rating flow for {call_info.call_id}: {e}")

    def _handle_user_event(self, manager, message):
        """Handle UserEvent for better call tracking"""
        asyncio.create_task(self._process_user_event(message))

    async def _process_user_event(self, message):
        """Process user events from dialplan"""
        event_name = message.get('UserEvent', '')
        call_id = message.get('CallID', '')

        if event_name == 'CallEnded' and call_id:
            # Force cleanup for this call
            logger.info(f"Received CallEnded event for {call_id}")
            await self._force_cleanup_call(call_id)

    async def _force_cleanup_call(self, call_id):
        """Force cleanup of a specific call"""
        if not self.call_manager:
            return

        # Find the call in active calls
        uniqueid_to_remove = None
        for uniqueid, call_info in self.call_manager.active_calls.items():
            if call_info.call_id == call_id:
                uniqueid_to_remove = uniqueid
                break

        if uniqueid_to_remove:
            call_info = self.call_manager.active_calls.pop(uniqueid_to_remove)
            self.channel_manager.release_channel(call_id)

            # Set final result if not already set
            if call_id not in self.call_results:
                final_status = self.call_manager._determine_final_status(call_info)
                self.call_results[call_id] = CallResult(
                    success=True,
                    call_id=call_id,
                    rating=call_info.rating,
                    transferred=call_info.transferred,
                    final_status=final_status,
                    call_duration=call_info.call_duration
                )

            logger.info(f"Force cleaned up call {call_id}")

    def _handle_dtmf(self, manager, message):
        """Handle DTMF events"""
        asyncio.create_task(self._process_dtmf(message))

    async def _process_dtmf(self, message):
        """Process DTMF input"""
        if not self.call_manager:
            return

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
        """Process hangup events with improved cleanup"""
        if not self.call_manager:
            return

        uniqueid = message.get('Uniqueid', '')

        if uniqueid in self.call_manager.active_calls:
            call_info = self.call_manager.active_calls.pop(uniqueid)

            # Calculate call duration
            if call_info.answered_at:
                call_info.call_duration = int(time.time() - call_info.answered_at)

            # Determine final status
            final_status = self.call_manager._determine_final_status(call_info)

            # Release channel
            self.channel_manager.release_channel(call_info.call_id)

            # Store final result
            self.call_results[call_info.call_id] = CallResult(
                success=True,
                call_id=call_info.call_id,
                rating=call_info.rating,
                transferred=call_info.transferred,
                final_status=final_status,
                call_duration=call_info.call_duration
            )

            logger.info(f"Call {call_info.call_id} completed with status: {final_status}")

            # Cleanup
            self.call_manager.uniqueid_to_callid.pop(uniqueid, None)
            self.call_manager.rating_retries.pop(uniqueid, None)

            # Remove from pending calls if still there
            self.call_manager.pending_calls.pop(call_info.call_id, None)

    async def make_callback_call(self, phone_number: str, brigade_id: str = None, callback_request_id: int = None) -> CallResult:
        """Make a callback call using persistent connection"""
        logger.info(f"Requesting callback call to {phone_number} (callback_request_id: {callback_request_id})")

        # Ensure system is initialized and connected
        if not await self.initialize():
            error_msg = "Failed to initialize ambulance system"
            logger.error(error_msg)
            return CallResult(success=False, error=error_msg, final_status='failed')

        # Make the call
        result = await self.call_manager.make_callback_call(phone_number, brigade_id, callback_request_id)

        if not result.success:
            logger.error(f"Failed to initiate call: {result.error}")
            return result

        logger.info(f"Call {result.call_id} initiated, waiting for completion...")

        # Wait for call to complete or timeout
        timeout = self.config.get('CALL_TIMEOUT', 30) + 60  # Extra time for rating
        start_time = time.time()

        while time.time() - start_time < timeout:
            await asyncio.sleep(1)
            if result.call_id in self.call_results:
                final_result = self.call_results.pop(result.call_id)  # Remove immediately
                logger.info(f"Call {result.call_id} completed with status: {final_result.final_status}")
                return final_result

        # Timeout - force cleanup
        logger.warning(f"Call {result.call_id} timed out after {timeout} seconds")
        await self._force_cleanup_call(result.call_id)
        return CallResult(success=False, call_id=result.call_id, error="Call timeout", final_status='failed')

    async def get_system_status(self) -> dict:
        """Get current system status"""
        return {
            'connection_state': self.connection_manager.connection_state.value,
            'initialized': self._setup_complete,
            'active_channels': self.channel_manager.get_active_count() if self.channel_manager else 0,
            'max_channels': self.config.get('MAX_CHANNELS', 2),
            'reconnect_attempts': self.connection_manager.reconnect_attempts,
            'last_ping_time': self.connection_manager.last_ping_time,
            'last_successful_action': self.connection_manager.last_successful_action,
            'active_calls': len(self.call_manager.active_calls) if self.call_manager else 0,
            'pending_calls': len(self.call_manager.pending_calls) if self.call_manager else 0,
            'call_results_count': len(self.call_results)
        }

    async def shutdown(self):
        """Gracefully shutdown the system"""
        logger.info("Shutting down static ambulance system...")

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        await self.connection_manager.disconnect()
        self._setup_complete = False

# Keep existing classes with minor improvements...
class ChannelManager:
    """Manages available channels for outbound calls"""

    def __init__(self, max_channels: int):
        self.max_channels = max_channels
        self.semaphore = asyncio.Semaphore(max_channels)
        self.active_channels = set()
        self.channel_lock = asyncio.Lock()

    async def acquire_channel(self, call_id: str) -> bool:
        """Acquire a channel for making a call (non-blocking)"""
        async with self.channel_lock:
            try:
                if len(self.active_channels) >= self.max_channels:
                    logger.info(f"All channels busy for call {call_id}. Active: {len(self.active_channels)}/{self.max_channels}")
                    return False

                try:
                    await asyncio.wait_for(self.semaphore.acquire(), timeout=0.001)
                    self.active_channels.add(call_id)
                    logger.info(f"Channel acquired immediately for call {call_id}. Active: {len(self.active_channels)}/{self.max_channels}")
                    return True
                except asyncio.TimeoutError:
                    logger.info(f"All channels busy for call {call_id}. Active: {len(self.active_channels)}/{self.max_channels}")
                    return False

            except Exception as e:
                logger.error(f"Error acquiring channel: {e}")
                return False

    async def wait_for_channel(self, call_id: str):
        """Wait for a channel to become available (blocking)"""
        logger.info(f"Call {call_id} waiting for available channel...")
        await self.semaphore.acquire()
        async with self.channel_lock:
            self.active_channels.add(call_id)
        logger.info(f"Channel acquired after waiting for call {call_id}. Active: {len(self.active_channels)}/{self.max_channels}")

    def release_channel(self, call_id: str):
        """Release a channel after call completion"""
        async def _release():
            async with self.channel_lock:
                if call_id in self.active_channels:
                    self.active_channels.remove(call_id)
                    self.semaphore.release()
                    logger.info(f"Channel released for call {call_id}. Active: {len(self.active_channels)}/{self.max_channels}")
                else:
                    logger.warning(f"Attempted to release channel for call {call_id} but it was not in active channels")

        # Run release in background to avoid blocking
        asyncio.create_task(_release())

    def get_active_count(self) -> int:
        """Get number of currently active channels"""
        return len(self.active_channels)

    def is_channel_available(self) -> bool:
        """Check if a channel is available"""
        return len(self.active_channels) < self.max_channels

class DjangoRatingManager:
    """Rating manager that saves to Django models"""

    @sync_to_async
    def save_rating(self, call_info: CallInfo) -> bool:
        """Save rating to Django models using callback_request_id"""
        try:
            from .models import CallbackRequest, Rating

            if call_info.callback_request_id:
                callback = CallbackRequest.objects.get(id=call_info.callback_request_id)
            else:
                callback = CallbackRequest.objects.get(call_id=call_info.call_id)

            # Create rating
            Rating.objects.create(
                callback_request=callback,
                rating=call_info.rating,
                phone_number=call_info.phone,
                team=callback.team if hasattr(callback, 'team') else None
            )

            # Update callback status
            callback.status = 'completed'
            if not callback.call_id:
                callback.call_id = call_info.call_id
            callback.save()

            logger.info(f"Rating {call_info.rating} saved for call {call_info.call_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save rating: {e}")
            return False

class AudioManager:
    """Handles audio playback"""

    def __init__(self, connection_manager):
        self.connection_manager = connection_manager

    async def play_audio(self, channel: str, audio_key: str):
        """Play audio file using dialplan redirect"""
        try:
            config = settings.AMBULANCE_CONFIG
            audio_file = config['AUDIO_FILES'].get(audio_key)
            if not audio_file:
                logger.error(f"Unknown audio key: {audio_key}")
                return False

            logger.info(f"Playing {audio_file} on {channel}")

            await self.connection_manager.send_action({
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
    """Manages call state and operations with improved cleanup"""

    def __init__(self, connection_manager, audio_manager: AudioManager, rating_manager: DjangoRatingManager, channel_manager: ChannelManager):
        self.connection_manager = connection_manager
        self.audio_manager = audio_manager
        self.rating_manager = rating_manager
        self.channel_manager = channel_manager

        self.active_calls: Dict[str, CallInfo] = {}
        self.pending_calls: Dict[str, CallInfo] = {}
        self.pending_actions: Dict[str, CallInfo] = {}
        self.uniqueid_to_callid: Dict[str, str] = {}
        self.rating_retries: Dict[str, int] = {}

    async def make_callback_call(self, phone_number: str, brigade_id: str = None, callback_request_id: int = None) -> CallResult:
        """Initiate a callback call with channel management"""
        call_id = str(uuid.uuid4())
        formatted_number = self._format_phone_number(phone_number)

        call_info = CallInfo(
            call_id=call_id,
            phone=phone_number,
            brigade=brigade_id,
            callback_request_id=callback_request_id
        )

        # Try to acquire channel immediately
        if await self.channel_manager.acquire_channel(call_id):
            # Channel available - start call immediately
            return await self._initiate_call(call_info, formatted_number)
        else:
            # No channel available - wait for one to become free
            await self.channel_manager.wait_for_channel(call_id)
            # Now we have a channel - start the call
            return await self._initiate_call(call_info, formatted_number)

    async def _initiate_call(self, call_info: CallInfo, formatted_number: str) -> CallResult:
        """Actually initiate the call"""
        self.pending_calls[call_info.call_id] = call_info

        try:
            config = settings.AMBULANCE_CONFIG

            result = await self.connection_manager.send_action({
                'Action': 'Originate',
                'Channel': f'Local/{formatted_number}@from-internal',
                'Context': 'ambulance-callback',
                'Exten': 's',
                'Priority': '1',
                'CallerID': config['CALLER_ID'],
                'Variable': f'CALL_ID={call_info.call_id},PHONE_NUMBER={call_info.phone},BRIGADE_ID={call_info.brigade or ""},CALLBACK_REQUEST_ID={call_info.callback_request_id or ""}',
                'Timeout': f'{config.get("CALL_TIMEOUT", 30) * 1000}',
                'Async': 'true'
            })

            actionid = self._extract_action_id(result)
            if actionid:
                self.pending_actions[actionid] = call_info

            # Set timeout
            asyncio.create_task(self._handle_call_timeout(call_info.call_id))

            logger.info(f"Call {call_info.call_id} initiated to {formatted_number}")
            return CallResult(success=True, call_id=call_info.call_id)

        except Exception as e:
            logger.error(f"Failed to originate call: {e}")
            self.pending_calls.pop(call_info.call_id, None)
            self.channel_manager.release_channel(call_info.call_id)
            return CallResult(success=False, error=str(e))

    def _extract_action_id(self, result) -> Optional[str]:
        """Extract ActionID from result"""
        if isinstance(result, list) and result:
            return result[0].get('ActionID')
        elif hasattr(result, 'get'):
            return result.get('ActionID')
        return None

    def _format_phone_number(self, phone_number: str) -> str:
        clean_number = ''.join(filter(str.isdigit, phone_number))
        # Remove any 998 prefix if it exists and return the raw number
        if clean_number.startswith('998') and len(clean_number) == 12:
            return clean_number[3:]  # Remove first 3 digits (998)
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
            self.channel_manager.release_channel(call_id)
            logger.warning(f"Call {call_id} failed due to timeout")

    def _determine_final_status(self, call_info: CallInfo) -> str:
        """Determine final status based on call state and actions"""
        if call_info.transferred:
            return 'transferred'
        elif call_info.rating is not None or call_info.state == CallState.COMPLETED:
            return 'completed'
        elif call_info.state in [CallState.WAITING_RATING, CallState.WAITING_TRANSFER_DECISION, CallState.ANSWERED]:
            return 'no_rating'
        else:
            return 'failed'

    async def handle_dtmf_input(self, uniqueid: str, digit: str) -> bool:
        """Handle DTMF input for active calls - two-step process"""
        if uniqueid not in self.active_calls:
            return False

        call_info = self.active_calls[uniqueid]

        if call_info.state == CallState.WAITING_RATING:
            # First step: Get rating (1-5)
            if digit in '12345':
                return await self._handle_rating_input(call_info, digit)
            else:
                # Invalid input - retry or play invalid message
                return await self._handle_invalid_input(call_info)

        elif call_info.state == CallState.WAITING_TRANSFER_DECISION:
            # Second step: Check if they want transfer (0) or hangup (any other)
            if digit == '0':
                return await self._handle_transfer_request(call_info)
            else:
                # Any other digit - just hangup
                return await self._handle_complete_call(call_info)
        else:
            await self.audio_manager.play_audio(call_info.channel, 'rating_invalid')
            return False

    async def _handle_rating_input(self, call_info: CallInfo, digit: str) -> bool:
        """Handle valid rating DTMF input (1-5)"""
        call_info.rating = int(digit)
        call_info.state = CallState.RATING_RECEIVED

        if call_info.uniqueid in self.rating_retries:
            del self.rating_retries[call_info.uniqueid]

        logger.info(f"Rating {digit} received for call {call_info.call_id}")

        # Save rating to Django
        await self.rating_manager.save_rating(call_info)

        # Play thank you and wait for transfer decision
        await self.audio_manager.play_audio(call_info.channel, 'rating_thankyou')
        await asyncio.sleep(3)

        # Now wait for transfer decision
        call_info.state = CallState.WAITING_TRANSFER_DECISION
        return True

    async def _handle_transfer_request(self, call_info: CallInfo) -> bool:
        """Handle transfer request (digit 0 after rating)"""
        call_info.transferred = True
        call_info.state = CallState.TRANSFERRING

        logger.info(f"Transfer requested for call {call_info.call_id}")
        await self._transfer_to_operator(call_info.channel)
        return True

    async def _handle_complete_call(self, call_info: CallInfo) -> bool:
        """Handle call completion (any digit other than 0 after rating - no transfer wanted)"""
        call_info.state = CallState.COMPLETED
        logger.info(f"Call {call_info.call_id} completed - no transfer requested")
        await self._hangup_call(call_info.channel)
        return True

    async def _handle_invalid_input(self, call_info: CallInfo) -> bool:
        """Handle invalid DTMF input during rating phase"""
        config = settings.AMBULANCE_CONFIG
        retry_limit = config.get('RATING_RETRY_LIMIT', 3)

        # Track retry attempts
        if call_info.uniqueid not in self.rating_retries:
            self.rating_retries[call_info.uniqueid] = 0

        self.rating_retries[call_info.uniqueid] += 1

        if self.rating_retries[call_info.uniqueid] >= retry_limit:
            # Too many invalid attempts - hang up
            logger.warning(f"Too many invalid attempts for call {call_info.call_id}")
            await self.audio_manager.play_audio(call_info.channel, 'rating_invalid')
            await asyncio.sleep(3)
            await self._hangup_call(call_info.channel)
            return False
        else:
            # Play invalid message and ask again
            await self.audio_manager.play_audio(call_info.channel, 'rating_invalid')
            await asyncio.sleep(2)
            await self.audio_manager.play_audio(call_info.channel, 'rating_request')
            return False

    async def _transfer_to_operator(self, channel: str):
        """Transfer call to internal extension 337"""
        try:
            # Try ext-local context first (where extension actually lives)
            await self.connection_manager.send_action({
                'Action': 'Redirect',
                'Channel': channel,
                'Context': 'ext-local',
                'Exten': '337',
                'Priority': '1'
            })

            # Alternative methods if above doesn't work:
            # Method 2: Use from-internal which includes ext-local
            # await self.connection_manager.send_action({
            #     'Action': 'Redirect',
            #     'Channel': channel,
            #     'Context': 'from-internal',
            #     'Exten': '337',
            #     'Priority': '1'
            # })

            # Method 3: Use BlindTransfer
            # await self.connection_manager.send_action({
            #     'Action': 'BlindTransfer',
            #     'Channel': channel,
            #     'Exten': '337',
            #     'Context': 'ext-local'
            # })

        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            await self._hangup_call(channel)

    async def _hangup_call(self, channel: str):
        """Hangup call"""
        try:
            await self.connection_manager.send_action({
                'Action': 'Hangup',
                'Channel': channel
            })
        except Exception as e:
            logger.error(f"Failed to hangup: {e}")

# Singleton instance
ambulance_system = StaticAmbulanceSystem()

# Django integration function - now much simpler
async def complete_make_ambulance_call(callback_request) -> dict:
    """
    Complete ambulance call using static system with persistent connection
    """
    try:
        phone_number = callback_request.phone_number
        brigade_id = callback_request.team.id if callback_request.team else None
        callback_request_id = callback_request.id

        result = await ambulance_system.make_callback_call(phone_number, brigade_id, callback_request_id)

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