from content_app.tasks import convert_480p

from .models import Video
import os
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import django_rq

@receiver(post_save, sender=Video)
def video_post_save(sender, instance, created, **kwargs):
    '''
    Signal handler for post_save of Video model.
    Prints a message indicating whether the video was created or updated.
    '''
    if created:
        queue = django_rq.get_queue('default', autocommit=True)
        queue.enqueue(convert_480p, instance.file.path)
        print("Video was created!")
    else:
        print("Video was updated!")

def get_video_file_path(instance, postfix):
    '''
    Constructs the file path for a derivative video file based on the original file and the given postfix.
    '''
    base, ext = os.path.splitext(instance.file.path)
    return f"{base}_{postfix}{ext}"