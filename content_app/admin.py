import uuid

from django.contrib import admin
from django.db import transaction

from .models import Video
from .signals import enqueue_video


def schedule_video(video_id, recover=False):
    """Schedule an eligible video ID, optionally replacing a stuck generation."""
    key = uuid.uuid4()
    statuses = ('queued', 'processing') if recover else ('pending', 'failed', 'ready')
    with transaction.atomic():
        changed = Video.objects.filter(pk=video_id, processing_status__in=statuses).update(
            processing_key=key, processing_status='pending', processing_error='')
        if changed:
            transaction.on_commit(lambda: enqueue_video(video_id, key))
    return bool(changed)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    actions = ('start_processing', 'recover_processing')
    list_display = ('title', 'category', 'processing_status', 'created_at', 'updated_at')
    search_fields = ('title', 'description', 'category')
    list_filter = ('category', 'created_at', 'updated_at')
    readonly_fields = ('processing_status', 'processing_error', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'category', 'file', 'thumbnail')
        }),
        ('Processing', {
            'fields': ('processing_status', 'processing_error')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    @admin.action(description='Start video processing', permissions=['change'])
    def start_processing(self, request, queryset):
        """Schedule selected eligible videos and report the count to the admin."""
        count = sum(schedule_video(video_id) for video_id in queryset.values_list('pk', flat=True))
        self.message_user(request, f'Processing requested for {count} video(s); check their status for errors.')

    @admin.action(description='Recover stuck video processing (invalidates previous job)', permissions=['change'])
    def recover_processing(self, request, queryset):
        """Replace selected stuck generations and report the scheduled count."""
        count = sum(schedule_video(video_id, recover=True) for video_id in queryset.values_list('pk', flat=True))
        self.message_user(request, f'Recovery requested for {count} video(s); check their status for errors.')
