import logging
import uuid

import django_rq
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from content_app.models import Video
from content_app.tasks import (
    cleanup_deleted_video_assets,
    cleanup_replaced_assets,
    process_thumbnail,
    process_video,
)

logger = logging.getLogger(__name__)


def enqueue_video(video_id, generation, thumbnail_only=False):
    """Enqueue a committed video generation or record the queue failure."""
    query = Video.objects.filter(pk=video_id, processing_key=generation, processing_status='pending')
    if not query.update(processing_status='queued'):
        return
    try:
        task = process_thumbnail if thumbnail_only else process_video
        django_rq.get_queue('default').enqueue(task, video_id, str(generation))
    except Exception:
        logger.exception('Could not enqueue video %s', video_id)
        query.model.objects.filter(pk=video_id, processing_key=generation, processing_status='queued').update(
            processing_status='failed', processing_error='Queue unavailable; see logs.')

@receiver(pre_save, sender=Video)
def prepare_video_update(sender, instance, **kwargs):
    """Schedule fresh processing when the source or thumbnail changes."""
    if not instance.pk or kwargs.get('update_fields') is not None:
        return
    previous = Video.objects.filter(pk=instance.pk).first()
    if not previous:
        return
    old_file = previous.file.name if previous.file.name != instance.file.name else ''
    old_thumbnail = previous.thumbnail.name if previous.thumbnail.name != instance.thumbnail.name else ''
    instance._old_assets = (old_file, old_thumbnail)
    if previous.file.name != instance.file.name:
        if previous.thumbnail.name and previous.thumbnail.name == instance.thumbnail.name and previous.thumbnail.name.startswith(('hls/', 'thumbnails/generated/')):
            instance.thumbnail = None
        reset_processing(instance, thumbnail_only=False)
    elif previous.thumbnail and not instance.thumbnail:
        reset_processing(instance, thumbnail_only=bool(previous.hls_path))


def reset_processing(instance, thumbnail_only):
    """Mark an updated video pending for a new processing generation."""
    instance.processing_key = uuid.uuid4()
    instance.processing_status = 'pending'
    instance.processing_error = ''
    instance._thumbnail_reprocess = thumbnail_only
    instance._schedule_reprocess = True


@receiver(post_save, sender=Video)
def video_post_save(sender, instance, created, **kwargs):
    """Schedule required processing after the video change is committed."""
    if created or getattr(instance, '_schedule_reprocess', False):
        video_id, key = instance.pk, instance.processing_key
        thumbnail_only = getattr(instance, '_thumbnail_reprocess', False)
        transaction.on_commit(lambda: enqueue_video(video_id, key, thumbnail_only))
    old_assets = getattr(instance, '_old_assets', None)
    if any(old_assets or ()):
        transaction.on_commit(lambda assets=old_assets: cleanup_replaced_assets(*assets))
        del instance._old_assets


@receiver(post_delete, sender=Video)
def video_post_delete(sender, instance, **kwargs):
    """Clean up unreferenced media after the video deletion commits."""
    assets = (instance.file.name, instance.thumbnail.name, instance.hls_path)
    transaction.on_commit(lambda: cleanup_deleted_video_assets(*assets))