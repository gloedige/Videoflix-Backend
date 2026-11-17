from content_app.tasks import convert_480p

from .models import Video
import os
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=Video)
def video_post_save(sender, instance, created, **kwargs):
    '''
    Signal handler for post_save of Video model.
    Prints a message indicating whether the video was created or updated.
    '''
    if created:
        convert_480p(instance.file.path)
        print("Video was created!")
    else:
        print("Video was updated!")


@receiver(post_delete, sender=Video)
def video_post_delete(sender, instance, **kwargs):
    '''
    Signal handler for post_delete of Video model.
    Deletes the associated video file from the filesystem if it exists.
    '''
    print("Video was deleted!")

    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)