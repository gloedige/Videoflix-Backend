import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urljoin

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from auth_app.models import CustomUser
from content_app import tasks
from content_app.models import Video


class ProtectedMediaTest(TestCase):
    """Verify access to media through the HTTP interface."""

    def setUp(self):
        """Create isolated media files and an authenticated viewer."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(MEDIA_ROOT=self.directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.file = Path(self.directory.name) / 'thumbnails' / 'image.jpg'
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b'image data')
        self.user = CustomUser.objects.create_user(username='viewer', password='password')

    def test_existing_media_requires_authentication(self):
        """Anonymous users cannot access an existing media file."""
        response = APIClient().get('/media/thumbnails/image.jpg')
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_user_can_read_existing_media(self):
        """An authenticated viewer can read a media file."""
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get('/media/thumbnails/image.jpg')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content), b'image data')

    def test_original_and_hls_files_require_authentication(self):
        """Existing source videos and HLS files cannot be accessed anonymously."""
        for name in ('videos/source.mp4', 'hls/1/a/480p/000.ts'):
            path = Path(self.directory.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'file')
            with self.subTest(name=name):
                self.assertIn(APIClient().get('/media/' + name).status_code, (401, 403))

    def test_video_list_thumbnail_url_requires_cookie(self):
        """The serialized thumbnail URL is accessible only with a valid cookie."""
        Video.objects.bulk_create([Video(
            title='Ready', description='A video', file='videos/source.mp4',
            thumbnail='thumbnails/image.jpg', processing_status='ready',
        )])
        client = APIClient()
        client.cookies['access_token'] = str(RefreshToken.for_user(self.user).access_token)
        url = client.get('/api/video/').data[0]['thumbnail_url']
        self.assertEqual(APIClient().get(url).status_code, 401)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'image data')

    def test_media_symlink_outside_root_is_not_served(self):
        """Authenticated users cannot follow media symlinks outside MEDIA_ROOT."""
        with TemporaryDirectory() as external:
            secret = Path(external) / 'secret.txt'
            secret.write_text('secret')
            (Path(self.directory.name) / 'link.txt').symlink_to(secret)
            client = APIClient()
            client.force_authenticate(user=self.user)
            self.assertEqual(client.get('/media/link.txt').status_code, 404)


class StreamingEndpointTest(TestCase):
    """Verify HLS streaming over the API."""

    def setUp(self):
        """Create a ready video and its isolated HLS files."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(MEDIA_ROOT=self.directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = CustomUser.objects.create_user(username='viewer', password='password')
        self.video = Video.objects.bulk_create([Video(
            title='Ready', description='A video', file='videos/source.mp4',
            thumbnail='thumbnails/image.jpg', processing_status='ready', hls_path='hls/1/generation',
        )])[0]
        self.variant = Path(self.directory.name) / self.video.hls_path / '480p'
        self.variant.mkdir(parents=True)
        (self.variant / 'index.m3u8').write_text('#EXTM3U\n#EXTINF:4.0,\n000.ts\n#EXT-X-ENDLIST\n')
        (self.variant / '000.ts').write_bytes(b'segment')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_authenticated_playlist_is_served(self):
        """A ready video's playlist is available with the HLS content type."""
        response = self.client.get(f'/api/video/{self.video.pk}/480p/index.m3u8')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.apple.mpegurl')
        self.assertIn(b'000.ts', response.content)

    def test_authenticated_segment_is_served_without_trailing_slash(self):
        """An authenticated viewer receives the TS bytes at the segment URL."""
        response = self.client.get(f'/api/video/{self.video.pk}/480p/000.ts')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'video/MP2T')
        self.assertEqual(b''.join(response.streaming_content), b'segment')

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
    def test_multiple_segments_are_not_subject_to_generic_api_throttle(self):
        """Segment requests do not exhaust the general per-user API quota."""
        with patch('rest_framework.throttling.UserRateThrottle.get_rate', return_value='1/day'):
            for _ in range(2):
                response = self.client.get(f'/api/video/{self.video.pk}/480p/000.ts')
                self.assertEqual(response.status_code, 200)
                b''.join(response.streaming_content)

    def test_streaming_endpoints_require_valid_authentication(self):
        """Both HLS endpoints reject missing and invalid access tokens."""
        for suffix in ('index.m3u8', '000.ts'):
            path = f'/api/video/{self.video.pk}/480p/{suffix}'
            for token in (None, 'invalid'):
                client = APIClient()
                if token:
                    client.cookies['access_token'] = token
                with self.subTest(path=path, token=token):
                    self.assertEqual(client.get(path).status_code, 401)

    def test_missing_and_invalid_streams_return_404(self):
        """Unknown videos, resolutions, filenames, and missing files return 404."""
        paths = (
            '/api/video/99999/480p/index.m3u8',
            f'/api/video/{self.video.pk}/bad/index.m3u8',
            f'/api/video/{self.video.pk}/720p/index.m3u8',
            f'/api/video/{self.video.pk}/480p/001.ts',
            f'/api/video/{self.video.pk}/480p/secret.txt',
            f'/api/video/{self.video.pk}/480p/000.ts/',
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_unready_video_does_not_stream(self):
        """A pending video remains unavailable even if files already exist."""
        Video.objects.filter(pk=self.video.pk).update(processing_status='pending')
        for name in ('index.m3u8', '000.ts'):
            self.assertEqual(self.client.get(f'/api/video/{self.video.pk}/480p/{name}').status_code, 404)

    def test_ffmpeg_playlist_and_segment_with_cookie(self):
        """A real FFmpeg playlist resolves to a cookie-protected segment endpoint."""
        fixture = Path(self.directory.name) / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'color=s=64x48:r=5:d=1', '-pix_fmt', 'yuv420p',
                        str(fixture)], check=True)
        video = Video.objects.create(title='Real', description='A video',
                                     file=SimpleUploadedFile('source.mp4', fixture.read_bytes()))
        tasks.process_video(video.pk)
        client = APIClient()
        client.cookies['access_token'] = str(RefreshToken.for_user(self.user).access_token)
        playlist_url = f'/api/video/{video.pk}/480p/index.m3u8'
        playlist = client.get(playlist_url)
        self.assertEqual(playlist.status_code, 200)
        segments = [line for line in playlist.content.decode().splitlines() if line and not line.startswith('#')]
        self.assertTrue(segments)
        segment = client.get(urljoin(playlist_url, segments[0]))
        self.assertEqual(segment.status_code, 200)
        self.assertEqual(segment['Content-Type'], 'video/MP2T')
        self.assertTrue(b''.join(segment.streaming_content))