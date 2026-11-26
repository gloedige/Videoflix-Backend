import subprocess
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from auth_app.models import CustomUser
from content_app import tasks
from content_app.models import Video


class VideoProcessingTest(TestCase):
    """Verify video processing through its worker and video-list interfaces."""

    def setUp(self):
        """Isolate uploaded files and create a small, silent video fixture."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.directory.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.fixture = Path(self.directory.name) / 'source.mp4'
        subprocess.run([
            'ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
            'color=c=blue:s=64x48:r=5:d=1', '-pix_fmt', 'yuv420p',
            str(self.fixture),
        ], check=True)

    def test_silent_video_becomes_visible_after_all_outputs_exist(self):
        """A silent video yields a thumbnail and three HLS variants before listing."""
        with patch('django_rq.get_queue'):
            video = Video.objects.create(
                title='Film', description='A film',
                file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            )
        tasks.process_video(video.pk)
        video.refresh_from_db()
        self.assertTrue(video.thumbnail and Path(video.thumbnail.path).is_file())
        for resolution in ('480p', '720p', '1080p'):
            playlists = list(Path(self.directory.name).rglob(f'{resolution}/index.m3u8'))
            self.assertEqual(len(playlists), 1)
            self.assertTrue(list(playlists[0].parent.glob('*.ts')))
        client = APIClient()
        client.force_authenticate(user=CustomUser.objects.create_user(username='viewer'))
        self.assertEqual([item['id'] for item in client.get('/api/video/').data], [video.pk])

    def test_invalid_video_is_hidden_and_failure_is_visible_in_admin(self):
        """Invalid uploads are not listed and their processing failure is visible."""
        with patch('django_rq.get_queue'):
            video = Video.objects.create(
                title='Broken', description='Invalid file',
                file=SimpleUploadedFile('broken.mp4', b'not a video'),
            )
        with self.assertLogs('content_app.tasks', level='ERROR'):
            tasks.process_video(video.pk)
        admin = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='password',
        )
        self.client.force_login(admin)
        response = self.client.get(f'/admin/content_app/video/{video.pk}/change/')
        self.assertContains(response, 'failed')
        self.assertContains(response, 'Video processing failed; see logs.')
        client = APIClient()
        client.force_authenticate(user=admin)
        self.assertEqual(client.get('/api/video/').data, [])

    def test_removing_thumbnail_hides_video_until_recreated(self):
        """Removing a thumbnail in the admin hides an otherwise completed video."""
        video = Video.objects.create(
            title='Film', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
        )
        tasks.process_video(video.pk)
        admin = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='password',
        )
        self.client.force_login(admin)
        response = self.client.post(f'/admin/content_app/video/{video.pk}/change/', {
            'title': 'Film', 'description': 'A film', 'category': 'Uncategorized',
            'thumbnail-clear': 'on', '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        client = APIClient()
        client.force_authenticate(user=admin)
        self.assertEqual(client.get('/api/video/').data, [])
        video.refresh_from_db()
        self.assertNotEqual(video.processing_status, 'ready')
        previous_hls = video.hls_path
        with self.captureOnCommitCallbacks(execute=True):
            tasks.process_thumbnail(video.pk, video.processing_key)
        video.refresh_from_db()
        self.assertEqual(video.hls_path, previous_hls)
        self.assertTrue((Path(self.directory.name) / previous_hls / '480p' / 'index.m3u8').is_file())
        self.assertTrue(Path(video.thumbnail.path).is_file())
        self.assertEqual([item['id'] for item in client.get('/api/video/').data], [video.pk])

    def test_missing_ffmpeg_outputs_never_publish_the_video(self):
        """A successful process exit without output files does not publish a video."""
        video = Video.objects.create(
            title='Missing files', description='Incomplete',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
        )
        with patch('content_app.tasks.subprocess.run'), self.assertLogs('content_app.tasks', level='ERROR'):
            tasks.process_video(video.pk)
        client = APIClient()
        client.force_authenticate(user=CustomUser.objects.create_user(username='viewer'))
        self.assertEqual(client.get('/api/video/').data, [])

    def test_manual_thumbnail_is_preserved(self):
        """Processing keeps a manually uploaded thumbnail instead of replacing it."""
        video = Video.objects.create(
            title='Manual image', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            thumbnail=SimpleUploadedFile('manual.jpg', b'manual image'),
        )
        tasks.process_video(video.pk)
        client = APIClient()
        client.force_authenticate(user=CustomUser.objects.create_user(username='viewer'))
        response = client.get('/api/video/')
        self.assertEqual(len(response.data), 1)
        self.assertTrue(response.data[0]['thumbnail_url'].endswith('/manual.jpg'))
        self.assertEqual(Path(video.thumbnail.path).read_bytes(), b'manual image')

    def test_queue_failure_is_visible_after_admin_upload(self):
        """An upload remains hidden and reports a queue error when Redis is unavailable."""
        admin = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='password',
        )
        self.client.force_login(admin)
        with (patch('django_rq.get_queue', side_effect=ConnectionError('offline')),
              self.assertLogs('content_app.signals', level='ERROR'),
              self.captureOnCommitCallbacks(execute=True)):
            response = self.client.post('/admin/content_app/video/add/', {
                'title': 'Queued', 'description': 'Film', 'category': 'Drama',
                'file': SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            })
        self.assertEqual(response.status_code, 302)
        video = Video.objects.get(title='Queued')
        change = self.client.get(f'/admin/content_app/video/{video.pk}/change/')
        self.assertContains(change, 'Queue unavailable; see logs.')
        client = APIClient()
        client.force_authenticate(user=admin)
        self.assertEqual(client.get('/api/video/').data, [])

    def test_replacing_source_hides_the_old_generation(self):
        """Replacing an already processed source hides its previous generation."""
        video = Video.objects.create(
            title='Film', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
        )
        tasks.process_video(video.pk)
        admin = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='password',
        )
        self.client.force_login(admin)
        response = self.client.post(f'/admin/content_app/video/{video.pk}/change/', {
            'title': 'Film', 'description': 'A film', 'category': 'Uncategorized',
            'file': SimpleUploadedFile('replacement.mp4', self.fixture.read_bytes()),
        })
        self.assertEqual(response.status_code, 302)
        client = APIClient()
        client.force_authenticate(user=admin)
        self.assertEqual(client.get('/api/video/').data, [])

    def test_reprocessing_preserves_hls_referenced_by_another_video(self):
        """A different video's active HLS directory survives reprocessing."""
        video = Video.objects.create(
            title='Original', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            thumbnail=SimpleUploadedFile('manual.jpg', b'manual'),
        )
        tasks.process_video(video.pk)
        video.refresh_from_db()
        old_path = video.hls_path
        Video.objects.bulk_create([Video(
            title='Other', description='Shared HLS', file='videos/other.mp4',
            thumbnail='thumbnails/other.jpg', hls_path=old_path, processing_status='ready',
        )])
        Video.objects.filter(pk=video.pk).update(processing_status='pending', processing_key=uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            tasks.process_video(video.pk)
        self.assertTrue((Path(self.directory.name) / old_path / '480p' / 'index.m3u8').is_file())

    def test_cleanup_error_does_not_remove_new_generation(self):
        """A failed old-directory deletion must not undo the successful new video."""
        video = Video.objects.create(
            title='Original', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            thumbnail=SimpleUploadedFile('manual.jpg', b'manual'),
        )
        tasks.process_video(video.pk)
        video.refresh_from_db()
        old_path = video.hls_path
        Video.objects.filter(pk=video.pk).update(processing_status='pending', processing_key=uuid.uuid4())
        with (patch('content_app.tasks.shutil.rmtree', side_effect=OSError('denied')),
              self.assertLogs('content_app.tasks', level='ERROR'),
              self.captureOnCommitCallbacks(execute=True)):
            tasks.process_video(video.pk)
        video.refresh_from_db()
        self.assertEqual(video.processing_status, 'ready')
        self.assertNotEqual(video.hls_path, old_path)
        self.assertTrue((Path(self.directory.name) / video.hls_path / '480p' / 'index.m3u8').is_file())

    def test_reprocessing_removes_unreferenced_old_generation_after_commit(self):
        """A successfully replaced, unreferenced generation is removed only after commit."""
        video = Video.objects.create(
            title='Original', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            thumbnail=SimpleUploadedFile('manual.jpg', b'manual'),
        )
        tasks.process_video(video.pk)
        video.refresh_from_db()
        old_directory = Path(self.directory.name) / video.hls_path
        Video.objects.filter(pk=video.pk).update(processing_status='pending', processing_key=uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            tasks.process_video(video.pk)
            self.assertTrue(old_directory.is_dir())
        video.refresh_from_db()
        self.assertFalse(old_directory.exists())
        self.assertTrue((Path(self.directory.name) / video.hls_path / '480p' / 'index.m3u8').is_file())

    def test_failed_publication_keeps_previous_generation(self):
        """Without a thumbnail publication fails without replacing the old HLS path."""
        video = Video.objects.create(
            title='Original', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
        )
        tasks.process_video(video.pk)
        video.refresh_from_db()
        old_path = video.hls_path
        Video.objects.filter(pk=video.pk).update(
            processing_status='pending', processing_key=uuid.uuid4(), thumbnail='',
        )
        with patch('content_app.tasks.convert_video', return_value=''), self.captureOnCommitCallbacks(execute=True):
            tasks.process_video(video.pk)
        video.refresh_from_db()
        self.assertEqual(video.processing_status, 'failed')
        self.assertEqual(video.hls_path, old_path)
        self.assertTrue((Path(self.directory.name) / old_path / '480p' / 'index.m3u8').is_file())

    def test_reprocessing_preserves_old_directory_with_referenced_thumbnail(self):
        """An existing thumbnail inside the old HLS directory remains accessible."""
        video = Video.objects.create(
            title='Original', description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
        )
        tasks.process_video(video.pk)
        video.refresh_from_db()
        thumbnail_path = Path(video.thumbnail.path)
        Video.objects.filter(pk=video.pk).update(processing_status='pending', processing_key=uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            tasks.process_video(video.pk)
        video.refresh_from_db()
        self.assertEqual(video.processing_status, 'ready')
        self.assertTrue(thumbnail_path.is_file())
        self.assertEqual(Path(video.thumbnail.path), thumbnail_path)