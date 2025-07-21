"""
Django management command to check ambulance system status
Save this as: callbacks/management/commands/ambulance_status.py
"""

import asyncio
import json
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from callbacks.ambulance_system import ambulance_system


class Command(BaseCommand):
    help = 'Check Emergency Ambulance System status'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            choices=['table', 'json', 'simple'],
            default='table',
            help='Output format (default: table)'
        )
        parser.add_argument(
            '--watch',
            action='store_true',
            help='Watch status continuously (refresh every 5 seconds)'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Refresh interval for watch mode (default: 5 seconds)'
        )

    def handle(self, *args, **options):
        if options['watch']:
            self.watch_status(options)
        else:
            self.show_status(options)

    def show_status(self, options):
        """Show current system status"""
        try:
            # Get status using asyncio
            status = asyncio.run(ambulance_system.get_system_status())

            # Format and display
            if options['format'] == 'json':
                self.output_json(status)
            elif options['format'] == 'simple':
                self.output_simple(status)
            else:
                self.output_table(status)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error getting system status: {e}')
            )

    def watch_status(self, options):
        """Watch status continuously"""
        try:
            import os
            while True:
                # Clear screen
                os.system('clear' if os.name == 'posix' else 'cls')

                # Show header
                self.stdout.write(
                    self.style.SUCCESS(
                        f"🚑 Emergency Ambulance System Status - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                )
                self.stdout.write("=" * 70)

                # Show status
                status = asyncio.run(ambulance_system.get_system_status())
                self.output_table(status)

                self.stdout.write(
                    f"\n⏱️  Refreshing every {options['interval']} seconds... (Press Ctrl+C to stop)"
                )

                # Wait for next refresh
                asyncio.run(asyncio.sleep(options['interval']))

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n👋 Monitoring stopped'))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error in watch mode: {e}')
            )

    def output_table(self, status):
        """Output status in table format"""
        # Connection Status
        conn_state = status['connection_state']
        if conn_state == 'connected':
            conn_display = self.style.SUCCESS(f'🟢 {conn_state.upper()}')
        elif conn_state == 'connecting':
            conn_display = self.style.WARNING(f'🟡 {conn_state.upper()}')
        else:
            conn_display = self.style.ERROR(f'🔴 {conn_state.upper()}')

        # System Status
        initialized = status['initialized']
        init_display = self.style.SUCCESS('✅ YES') if initialized else self.style.ERROR('❌ NO')

        # Channel Usage
        active_channels = status['active_channels']
        max_channels = status['max_channels']
        channel_usage = f"{active_channels}/{max_channels}"
        if active_channels == max_channels:
            channel_display = self.style.ERROR(f'🔴 {channel_usage} (FULL)')
        elif active_channels > max_channels * 0.7:
            channel_display = self.style.WARNING(f'🟡 {channel_usage}')
        else:
            channel_display = self.style.SUCCESS(f'🟢 {channel_usage}')

        # Format timestamps
        last_ping = self._format_timestamp(status['last_ping_time'])
        last_action = self._format_timestamp(status['last_successful_action'])

        # Display table
        self.stdout.write("\n📊 SYSTEM STATUS")
        self.stdout.write("-" * 50)
        self.stdout.write(f"AMI Connection:     {conn_display}")
        self.stdout.write(f"System Initialized: {init_display}")
        self.stdout.write(f"Reconnect Attempts: {status['reconnect_attempts']}")

        self.stdout.write("\n📞 CALL MANAGEMENT")
        self.stdout.write("-" * 50)
        self.stdout.write(f"Channel Usage:      {channel_display}")
        self.stdout.write(f"Active Calls:       {status['active_calls']}")
        self.stdout.write(f"Pending Calls:      {status['pending_calls']}")
        self.stdout.write(f"Call Results Cache: {status['call_results_count']}")

        self.stdout.write("\n⏰ TIMING INFO")
        self.stdout.write("-" * 50)
        self.stdout.write(f"Last Ping:          {last_ping}")
        self.stdout.write(f"Last Successful:    {last_action}")

    def output_simple(self, status):
        """Output status in simple format"""
        self.stdout.write(f"Connection: {status['connection_state']}")
        self.stdout.write(f"Initialized: {status['initialized']}")
        self.stdout.write(f"Channels: {status['active_channels']}/{status['max_channels']}")
        self.stdout.write(f"Active Calls: {status['active_calls']}")
        self.stdout.write(f"Pending Calls: {status['pending_calls']}")

    def output_json(self, status):
        """Output status in JSON format"""
        # Convert timestamps to readable format
        formatted_status = status.copy()
        formatted_status['last_ping_time_formatted'] = self._format_timestamp(status['last_ping_time'])
        formatted_status['last_successful_action_formatted'] = self._format_timestamp(status['last_successful_action'])
        formatted_status['timestamp'] = datetime.now().isoformat()

        self.stdout.write(json.dumps(formatted_status, indent=2))

    def _format_timestamp(self, timestamp):
        """Format timestamp for display"""
        if not timestamp:
            return "Never"

        try:
            dt = datetime.fromtimestamp(timestamp)
            now = datetime.now()

            # Calculate time difference
            diff = now - dt
            seconds = int(diff.total_seconds())

            if seconds < 60:
                return f"{seconds}s ago"
            elif seconds < 3600:
                minutes = seconds // 60
                return f"{minutes}m ago"
            elif seconds < 86400:
                hours = seconds // 3600
                return f"{hours}h ago"
            else:
                days = seconds // 86400
                return f"{days}d ago"

        except Exception:
            return "Unknown"