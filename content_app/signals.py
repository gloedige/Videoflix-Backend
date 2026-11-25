import logging
import uuid

import django_rq
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from content_app.models import Video
from content_app.tasks import process_thumbnail, process_video

logger = logging.getLogger(__name__)


def enqueue_video(video_id, generation, thumbnail_only=False):
    """Enqueue a committed video generation or record the queue failure."""
    try:
        task = process_thumbnail if thumbnail_only else process_video
        django_rq.get_queue('default').enqueue(task, video_id, str(generation))
    except Exception:
        logger.exception('Could not enqueue video %s', video_id)
        Video.objects.filter(pk=video_id, processing_key=generation).update(
            processing_status='failed', processing_error='Queue unavailable; see logs.')

@receiver(pre_save, sender=Video)
def prepare_video_update(sender, instance, **kwargs):
    """Invalidate readiness when an existing video loses its thumbnail."""
    if not instance.pk or kwargs.get('update_fields') is not None:
        return
    previous = Video.objects.filter(pk=instance.pk).first()
    if previous and previous.thumbnail and not instance.thumbnail:
        instance.processing_key = uuid.uuid4()
        instance.processing_status = 'pending'
        instance.processing_error = ''
        instance._thumbnail_reprocess = bool(previous.hls_path)
        instance._schedule_reprocess = True


@receiver(post_save, sender=Video)
def video_post_save(sender, instance, created, **kwargs):
    """Schedule required processing after the video change is committed."""
    if created or getattr(instance, '_schedule_reprocess', False):
        video_id, key = instance.pk, instance.processing_key
        thumbnail_only = getattr(instance, '_thumbnail_reprocess', False)
        transaction.on_commit(lambda: enqueue_video(video_id, key, thumbnail_only))