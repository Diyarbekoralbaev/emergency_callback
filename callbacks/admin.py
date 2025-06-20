from django.contrib import admin
from .models import CallbackRequest, Rating


@admin.register(CallbackRequest)
class CallbackRequestAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'team', 'status', 'created_at', 'requested_by']
    list_filter = ['status', 'team', 'created_at', 'transferred']
    search_fields = ['phone_number', 'team__name', 'call_id']
    readonly_fields = ['call_id', 'uniqueid', 'channel', 'created_at', 'call_started_at', 'call_ended_at']

    fieldsets = (
        ('Request Information', {
            'fields': ('phone_number', 'team', 'status', 'requested_by')
        }),
        ('Call Details', {
            'fields': ('call_id', 'uniqueid', 'channel'),
            'classes': ('collapse',)
        }),
        ('Timing', {
            'fields': ('created_at', 'call_started_at', 'call_ended_at'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('error_message', 'transferred', 'additional_questions'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ['callback_request', 'rating', 'team', 'phone_number', 'timestamp']
    list_filter = ['rating', 'team', 'date']
    search_fields = ['phone_number', 'team__name', 'callback_request__call_id']
    readonly_fields = ['timestamp', 'date']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('callback_request', 'team')
