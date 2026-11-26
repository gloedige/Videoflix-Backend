import uuid

from django.db import models


class Video(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    file = models.FileField(upload_to='videos/')
    thumbnail = models.FileField(upload_to='thumbnails/', blank=True, null=True)
    processing_status = models.CharField(max_length=20, default='pending')
    processing_key = models.UUIDField(default=uuid.uuid4, editable=False)
    processing_error = models.TextField(blank=True, default='')
    hls_path = models.CharField(max_length=255, blank=True, default='')
    category = models.CharField(max_length=100, default='Uncategorized')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Video'
        verbose_name_plural = 'Videos'

    def __str__(self):
        return self.title
