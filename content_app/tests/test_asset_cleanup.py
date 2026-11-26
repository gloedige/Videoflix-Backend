import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from auth_app.models import CustomUser
from content_app import tasks
from content_app.models import Video


class VideoAssetCleanupTest(TestCase):
    """Verify replacement and deletion of video assets through Django admin."""

    def setUp(self):
        """Create an admin user and isolate uploaded media files."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(MEDIA_ROOT=self.directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.fixture = Path(self.directory.name) / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                'color=s=64x48:r=5:d=1', '-pix_fmt', 'yuv420p',
                str(self.fixture)], check=True)
        self.client.force_login(CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='password',
        ))

    def create_video(self, title='Film', thumbnail=None):
        """Create a video with small source bytes and an optional thumbnail."""
        return Video.objects.create(
            title=title, description='A film',
            file=SimpleUploadedFile('source.mp4', self.fixture.read_bytes()),
            thumbnail=thumbnail,
        )

    def test_replacing_source_removes_old_original_after_commit(self):
        """Replacing the source deletes the old file but retains the new one."""
        video = self.create_video()
        old_path = Path(video.file.path)
        with patch('django_rq.get_queue'), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'/admin/content_app/video/{video.pk}/change/', {
                'title': video.title, 'description': video.description,
                'category': video.category,
                'file': SimpleUploadedFile('replacement.mp4', b'replacement source'),
            })
        self.assertEqual(response.status_code, 302)
        video.refresh_from_db()
        self.assertFalse(old_path.exists())
        self.assertTrue(Path(video.file.path).is_file())

    def test_replacing_thumbnail_removes_old_thumbnail_after_commit(self):
        """Replacing a manually uploaded thumbnail removes its old stored file."""
        video = self.create_video(thumbnail=SimpleUploadedFile('poster.jpg', b'old poster'))
        old_path = Path(video.thumbnail.path)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'/admin/content_app/video/{video.pk}/change/', {
                'title': video.title, 'description': video.description,
                'category': video.category, 'file': video.file,
                'thumbnail': SimpleUploadedFile('new-poster.jpg', b'new poster'),
            })
        self.assertEqual(response.status_code, 302)
        video.refresh_from_db()
        self.assertFalse(old_path.exists())
        self.assertTrue(Path(video.thumbnail.path).is_file())

    def test_deleting_video_removes_source_thumbnail_and_hls_after_commit(self):
        """Deleting a video removes all its media assets after the DB commit."""
        video = self.create_video()
        with patch('django_rq.get_queue'):
            tasks.process_video(video.pk)
        video.refresh_from_db()
        paths = (Path(video.file.path), Path(video.thumbnail.path), Path(self.directory.name) / video.hls_path)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/admin/content_app/video/', {
                'action': 'delete_selected', '_selected_action': [str(video.pk)], 'post': 'yes',
            })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Video.objects.filter(pk=video.pk).exists())
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_deleting_video_preserves_assets_referenced_by_another_video(self):
        """Shared source, thumbnail, and HLS assets remain while referenced."""
        video = self.create_video(thumbnail=SimpleUploadedFile('poster.jpg', b'poster'))
        with patch('django_rq.get_queue'):
            tasks.process_video(video.pk)
        video.refresh_from_db()
        paths = (Path(video.file.path), Path(video.thumbnail.path), Path(self.directory.name) / video.hls_path)
        Video.objects.create(
            title='Reference', description='Shared assets', file=video.file.name,
            thumbnail=video.thumbnail.name, hls_path=video.hls_path, processing_status='ready',
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/admin/content_app/video/', {
                'action': 'delete_selected', '_selected_action': [str(video.pk)], 'post': 'yes',
            })
        self.assertEqual(response.status_code, 302)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(path.exists())

    def test_cleanup_refuses_media_root_and_paths_outside_hls_namespace(self):
        """Malformed legacy HLS paths cannot delete MEDIA_ROOT or other media."""
        root = Path(self.directory.name).resolve()
        protected = root / 'videos' / 'source.mp4'
        protected.parent.mkdir(parents=True)
        protected.write_bytes(b'keep')
        for unsafe_path in ('.', 'hls/..', 'thumbnails'):
            with self.subTest(path=unsafe_path):
                tasks.cleanup_old_hls(unsafe_path)
                self.assertTrue(protected.exists())
                self.assertTrue(root.exists())