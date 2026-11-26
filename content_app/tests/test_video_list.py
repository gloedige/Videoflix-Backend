from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from auth_app.models import CustomUser
from content_app.models import Video


class VideoListEndpointTest(TestCase):
	"""Test the authenticated video metadata endpoint."""

	def setUp(self):
		"""Create an API client for each test."""
		self.client = APIClient()

	def authenticate(self):
		"""Authenticate the client using the access-token cookie."""
		user = CustomUser.objects.create_user(
			username='viewer@example.com',
			email='viewer@example.com',
			password='strong-test-password',
		)
		self.client.cookies['access_token'] = str(RefreshToken.for_user(user).access_token)

	def test_video_list_requires_authentication(self):
		"""Reject requests without a valid access token."""
		response = self.client.get('/api/video/')

		self.assertEqual(response.status_code, 401)

	def test_video_list_returns_metadata_newest_first(self):
		"""Return the documented metadata fields ordered by creation time descending."""
		self.authenticate()
		older = Video.objects.create(
			title='Older film', description='Older description', file='videos/older.mp4',
			thumbnail='thumbnails/older.jpg', category='Drama', processing_status='ready',
		)
		newer = Video.objects.create(
			title='Newer film', description='Newer description', file='videos/newer.mp4',
			thumbnail='thumbnails/newer.jpg', category='Comedy', processing_status='ready',
		)
		Video.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
		Video.objects.filter(pk=newer.pk).update(created_at=timezone.now())

		response = self.client.get('/api/video/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item['id'] for item in response.data], [newer.pk, older.pk])
		self.assertEqual(set(response.data[0]), {
			'id', 'created_at', 'title', 'description', 'thumbnail_url', 'category',
		})
		self.assertTrue(response.data[0]['thumbnail_url'].endswith('/media/thumbnails/newer.jpg'))
		self.assertEqual(response.data[0]['category'], 'Comedy')

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