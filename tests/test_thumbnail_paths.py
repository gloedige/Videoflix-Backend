import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from content_app import tasks
from content_app.models import Video


class ThumbnailPathTest(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=self.directory.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)

    @staticmethod
    def generate_variant(source, output, height):
        output.mkdir(parents=True, exist_ok=True)
        (output / 'index.m3u8').write_text('playlist')
        (output / '000.ts').write_text('segment')

    @staticmethod
    def generate_thumbnail(source, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('thumbnail')

    def test_generated_path_and_legacy_thumbnail_survive_reprocessing(self):
        with patch('content_app.signals.enqueue_video'), \
             patch('content_app.tasks.generate_variant', side_effect=self.generate_variant), \
             patch('content_app.tasks.generate_thumbnail', side_effect=self.generate_thumbnail):
            video = Video.objects.create(title='Film', file='videos/source.mp4')
            tasks.process_video(video.pk)
            video.refresh_from_db()
            old_path = video.hls_path
            old_directory = Path(self.directory.name) / old_path
            self.assertEqual(video.thumbnail.name, f'{old_path}/thumbnail.jpg')

            # Existing records created on Windows may contain backslashes.
            legacy_thumbnail = video.thumbnail.name.replace('/', '\\')
            Video.objects.filter(pk=video.pk).update(
                thumbnail=legacy_thumbnail, processing_status='pending', processing_key=uuid.uuid4(),
            )
            with self.captureOnCommitCallbacks(execute=True):
                tasks.process_video(video.pk)
            video.refresh_from_db()
            self.assertEqual(video.processing_status, 'ready')
            self.assertNotEqual(video.hls_path, old_path)
            self.assertEqual(video.thumbnail.name, legacy_thumbnail)
            self.assertTrue((old_directory / 'thumbnail.jpg').is_file())
            self.assertTrue((old_directory / '480p' / 'index.m3u8').is_file())

    def test_cleanup_respects_path_boundaries_for_both_separators(self):
        video = Video.objects.create(title='Film', file='videos/source.mp4')
        old_path = 'hls/1/generation'
        for separator in ('/', '\\'):
            with self.subTest(separator=separator):
                prefix = old_path.replace('/', separator)
                Video.objects.filter(pk=video.pk).update(thumbnail=prefix + separator + 'thumbnail.jpg')
                self.assertFalse(tasks.check_thumbnails_not_in_old_hls(old_path))
                Video.objects.filter(pk=video.pk).update(thumbnail=prefix + '-other' + separator + 'thumbnail.jpg')
                self.assertTrue(tasks.check_thumbnails_not_in_old_hls(old_path))