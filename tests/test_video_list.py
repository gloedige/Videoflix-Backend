from django.test import TestCase
from rest_framework.test import APIClient

from auth_app.models import CustomUser
from content_app.models import Video


class VideoAvailabilityTest(TestCase):
    """Verify which videos an authenticated viewer can see."""

    def test_unprocessed_video_is_not_listed(self):
        """A newly added video without completed processing is not listed."""
        user = CustomUser.objects.create_user(username='viewer', password='password')
        Video.objects.bulk_create([Video(
            title='Not ready', description='Processing', file='videos/source.mp4',
        )])
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/video/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_ready_video_without_thumbnail_is_not_listed(self):
        """A ready status alone does not make a video without a thumbnail visible."""
        user = CustomUser.objects.create_user(username='viewer', password='password')
        Video.objects.bulk_create([Video(
            title='Missing thumbnail', description='Incomplete', file='videos/source.mp4',
            thumbnail=None, processing_status='ready',
        )])
        client = APIClient()
        client.force_authenticate(user=user)
        self.assertEqual(client.get('/api/video/').data, [])