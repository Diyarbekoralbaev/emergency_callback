from django.core.management.base import BaseCommand
import os

class Command(BaseCommand):
    help = 'Start Celery worker'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Celery worker...'))
        self.stdout.write(self.style.WARNING('Make sure Redis is running: redis-server'))
        self.stdout.write(self.style.WARNING('Run this command: celery -A emergency_callback worker --loglevel=info'))
