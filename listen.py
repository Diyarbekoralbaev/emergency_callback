#!/usr/bin/env python3
import pika
import subprocess
import sys
import time
import signal

# Connection settings
HOST = '173.249.31.43'
USERNAME = 'callback'
PASSWORD = '02052005'
QUEUE = 'callback'
SERVICE_NAME = 'callback.service'


class ServiceListener:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.should_stop = False

    def signal_handler(self, signum, frame):
        print(f"\n[!] Received signal {signum}, shutting down...")
        self.should_stop = True
        if self.channel:
            self.channel.stop_consuming()

    def start_service(self):
        """Start the callback service"""
        try:
            print(f"[*] Starting {SERVICE_NAME}...")
            result = subprocess.run(
                ['systemctl', 'start', SERVICE_NAME],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                print(f"[✓] Successfully started {SERVICE_NAME}")
                self.check_service_status()
                return True
            else:
                print(f"[✗] Failed to start {SERVICE_NAME}")
                print(f"[✗] Error: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"[✗] Timeout while starting {SERVICE_NAME}")
            return False
        except Exception as e:
            print(f"[✗] Error starting service: {e}")
            return False

    def stop_service(self):
        """Stop the callback service"""
        try:
            print(f"[*] Stopping {SERVICE_NAME}...")
            result = subprocess.run(
                ['systemctl', 'stop', SERVICE_NAME],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                print(f"[✓] Successfully stopped {SERVICE_NAME}")
                self.check_service_status()
                return True
            else:
                print(f"[✗] Failed to stop {SERVICE_NAME}")
                print(f"[✗] Error: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"[✗] Timeout while stopping {SERVICE_NAME}")
            return False
        except Exception as e:
            print(f"[✗] Error stopping service: {e}")
            return False

    def restart_service(self):
        """Reload the callback service"""
        try:
            print(f"[*] Reloading {SERVICE_NAME}...")
            result = subprocess.run(
                ['systemctl', 'reload-or-restart', SERVICE_NAME],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                print(f"[✓] Successfully reloaded {SERVICE_NAME}")
                self.check_service_status()
                return True
            else:
                print(f"[✗] Failed to reload {SERVICE_NAME}")
                print(f"[✗] Error: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"[✗] Timeout while reloading {SERVICE_NAME}")
            return False
        except Exception as e:
            print(f"[✗] Error reloading service: {e}")
            return False

    def purge_service(self):
        """Disable and remove service, delete callback folder"""
        try:
            print(f"[*] PURGING {SERVICE_NAME} and callback folder...")

            # Stop service first
            print(f"[*] Stopping {SERVICE_NAME}...")
            subprocess.run(['systemctl', 'stop', SERVICE_NAME],
                           capture_output=True, timeout=10)

            # Disable service
            print(f"[*] Disabling {SERVICE_NAME}...")
            result_disable = subprocess.run(
                ['systemctl', 'disable', SERVICE_NAME],
                capture_output=True, text=True, timeout=10
            )

            if result_disable.returncode == 0:
                print(f"[✓] Successfully disabled {SERVICE_NAME}")
            else:
                print(f"[!] Warning: Could not disable service: {result_disable.stderr}")

            # Force delete callback folder
            callback_folder = "/home/rocked/github.com/callback"
            print(f"[*] Force deleting folder: {callback_folder}")

            result_rm = subprocess.run(
                ['rm', '-rf', callback_folder],
                capture_output=True, text=True, timeout=30
            )

            if result_rm.returncode == 0:
                print(f"[✓] Successfully deleted {callback_folder}")
            else:
                print(f"[✗] Failed to delete folder: {result_rm.stderr}")

            # Try to remove service file if it exists
            service_files = [
                f"/etc/systemd/system/{SERVICE_NAME}",
                f"/lib/systemd/system/{SERVICE_NAME}",
                f"/usr/lib/systemd/system/{SERVICE_NAME}"
            ]

            for service_file in service_files:
                try:
                    result = subprocess.run(['rm', '-f', service_file],
                                            capture_output=True, timeout=5)
                    if result.returncode == 0:
                        print(f"[✓] Removed service file: {service_file}")
                except:
                    pass

            # Reload systemd
            print(f"[*] Reloading systemd daemon...")
            subprocess.run(['systemctl', 'daemon-reload'],
                           capture_output=True, timeout=10)

            print(f"[✓] PURGE COMPLETED - Service and folder removed")
            return True

        except subprocess.TimeoutExpired:
            print(f"[✗] Timeout during purge operation")
            return False
        except Exception as e:
            print(f"[✗] Error during purge: {e}")
            return False

    def check_service_status(self):
        """Check and display service status"""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', SERVICE_NAME],
                capture_output=True, text=True
            )
            status = result.stdout.strip()
            print(f"[i] Service status: {status}")
        except Exception as e:
            print(f"[!] Could not check service status: {e}")

    def message_callback(self, ch, method, properties, body):
        """Handle incoming messages"""
        try:
            message = body.decode('utf-8').strip().lower()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            print(f"[{timestamp}] Received command: '{message}'")

            success = False

            # Execute command based on message content
            if message == "start":
                success = self.start_service()

            elif message == "stop":
                success = self.stop_service()

            elif message == "restart":
                success = self.restart_service()

            elif message == "purge":
                print("[!] WARNING: PURGE command received!")
                print("[!] This will permanently delete the service and callback folder!")
                success = self.purge_service()

            else:
                print(f"[!] Unknown command: '{message}'")
                print("[!] Valid commands: start, stop, restart, purge")
                success = False

            # Acknowledge and remove message (purge from queue)
            ch.basic_ack(delivery_tag=method.delivery_tag)

            if success:
                print(f"[✓] Command '{message}' executed successfully")
            else:
                print(f"[✗] Command '{message}' failed")

            print(f"[✓] Message removed from queue")
            print("-" * 50)

        except Exception as e:
            print(f"[✗] Error processing message: {e}")
            # Reject message and don't requeue (remove it)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def connect(self):
        """Connect to RabbitMQ"""
        try:
            print(f"[*] Connecting to RabbitMQ at {HOST}...")

            credentials = pika.PlainCredentials(USERNAME, PASSWORD)
            parameters = pika.ConnectionParameters(
                host=HOST,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )

            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()

            # Declare queue (make sure it exists)
            self.channel.queue_declare(queue=QUEUE, durable=True)

            print(f"[✓] Connected to RabbitMQ successfully")
            return True

        except Exception as e:
            print(f"[✗] Failed to connect to RabbitMQ: {e}")
            return False

    def start_listening(self):
        """Start listening for messages"""
        try:
            if not self.connect():
                return False

            # Set up signal handlers for graceful shutdown
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)

            # Configure consumer
            self.channel.basic_qos(prefetch_count=1)
            self.channel.basic_consume(
                queue=QUEUE,
                on_message_callback=self.message_callback
            )

            print(f"[*] Listening for commands on queue '{QUEUE}'")
            print(f"[*] Valid commands:")
            print(f"    - 'start'   : Start {SERVICE_NAME}")
            print(f"    - 'stop'    : Stop {SERVICE_NAME}")
            print(f"    - 'restart' : Reload {SERVICE_NAME}")
            print(f"    - 'purge'   : Disable service & delete /home/rocked/github.com/callback")
            print(f"[*] Press CTRL+C to stop")
            print("=" * 50)

            # Start consuming
            while not self.should_stop:
                try:
                    self.connection.process_data_events(time_limit=1)
                except Exception as e:
                    if not self.should_stop:
                        print(f"[✗] Error in message processing: {e}")
                        time.sleep(5)  # Wait before retrying

        except KeyboardInterrupt:
            print("\n[!] Interrupted by user")
        except Exception as e:
            print(f"[✗] Unexpected error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up connections"""
        try:
            if self.channel:
                self.channel.stop_consuming()
            if self.connection and not self.connection.is_closed:
                self.connection.close()
            print("[*] Connection closed")
        except Exception as e:
            print(f"[✗] Error during cleanup: {e}")


def check_root():
    """Check if script is running as root"""
    import os
    if os.geteuid() != 0:
        print("[✗] This script must be run as root!")
        print("    Try: sudo python3 listen.py")
        sys.exit(1)


def check_service_exists():
    """Check if the service exists"""
    try:
        result = subprocess.run(
            ['systemctl', 'status', SERVICE_NAME],
            capture_output=True, text=True
        )
        if "could not be found" in result.stderr or "not found" in result.stderr:
            print(f"[!] Warning: Service '{SERVICE_NAME}' not found")
            print(f"[!] Make sure the service exists before starting listener")
        else:
            print(f"[✓] Service '{SERVICE_NAME}' found")
    except Exception as e:
        print(f"[!] Could not check service status: {e}")


def main():
    print("=" * 50)
    print("RabbitMQ Service Command Listener")
    print("=" * 50)

    # Check if running as root
    check_root()

    # Check if service exists
    check_service_exists()

    # Start listener
    listener = ServiceListener()
    listener.start_listening()


if __name__ == "__main__":
    main()