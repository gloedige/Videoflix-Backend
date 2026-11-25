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
