import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from content_app import tasks
from content_app.models import Video


class ThumbnailPathTest(TestCase):
    '''Test cases for handling thumbnail paths and legacy thumbnail formats.'''
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=self.directory.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)

    @staticmethod
    def generate_variant(source, output, height):
        """Simulate generating an HLS variant for testing purposes."""
        output.mkdir(parents=True, exist_ok=True)
        (output / 'index.m3u8').write_text('playlist')
        (output / '000.ts').write_text('segment')

    @staticmethod
    def generate_thumbnail(source, output):
        """Simulate generating a thumbnail for testing purposes."""
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('thumbnail')

    def test_generated_path_and_legacy_thumbnail_survive_reprocessing(self):
        """Test that generated paths and legacy thumbnail formats survive reprocessing."""
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
        """Ensure that cleanup logic correctly handles both forward and backward slashes in paths."""
        video = Video.objects.create(title='Film', file='videos/source.mp4')
        old_path = 'hls/1/generation'
        for separator in ('/', '\\'):
            with self.subTest(separator=separator):
                prefix = old_path.replace('/', separator)
                Video.objects.filter(pk=video.pk).update(thumbnail=prefix + separator + 'thumbnail.jpg')
                self.assertFalse(tasks.check_thumbnails_not_in_old_hls(old_path))
                Video.objects.filter(pk=video.pk).update(thumbnail=prefix + '-other' + separator + 'thumbnail.jpg')
                self.assertTrue(tasks.check_thumbnails_not_in_old_hls(old_path))

    def test_thumbnail_publication_exception_removes_generated_file(self):
        """Ensure that an exception during thumbnail publication removes the generated file."""
        video = Video.objects.create(title='Film', file='videos/source.mp4', hls_path='hls/1/old')
        output = Path(self.directory.name) / f'thumbnails/generated/{video.pk}/{video.processing_key}.jpg'
        with (patch('content_app.tasks.generate_thumbnail', side_effect=self.generate_thumbnail),
              patch('content_app.tasks.publish_video', side_effect=RuntimeError('database error')),
              self.assertLogs('content_app.tasks', level='ERROR')):
            tasks.process_thumbnail(video.pk, video.processing_key)
        video.refresh_from_db()
        self.assertEqual(video.processing_status, 'failed')
        self.assertFalse(video.thumbnail)
        self.assertFalse(output.exists())
        self.assertEqual(video.hls_path, 'hls/1/old')

    def test_thumbnail_generation_exception_removes_partial_file(self):
        """Ensure that an exception during thumbnail generation removes the partial file."""
        video = Video.objects.create(title='Film', file='videos/source.mp4')
        output = Path(self.directory.name) / f'thumbnails/generated/{video.pk}/{video.processing_key}.jpg'

        def partial_thumbnail(source, destination):
            self.generate_thumbnail(source, destination)
            raise RuntimeError('generation failed')

        with (patch('content_app.tasks.generate_thumbnail', side_effect=partial_thumbnail),
              self.assertLogs('content_app.tasks', level='ERROR')):
            tasks.process_thumbnail(video.pk, video.processing_key)
        video.refresh_from_db()
        self.assertEqual(video.processing_status, 'failed')
        self.assertFalse(output.exists())

    def test_thumbnail_cleanup_error_does_not_prevent_failure_status(self):
        """Ensure that an error during thumbnail cleanup does not prevent the video from being marked as failed."""
        video = Video.objects.create(title='Film', file='videos/source.mp4')
        with (patch('content_app.tasks.generate_thumbnail', side_effect=self.generate_thumbnail),
              patch('content_app.tasks.publish_video', side_effect=RuntimeError('database error')),
              patch.object(Path, 'unlink', side_effect=OSError('permission denied')),
              self.assertLogs('content_app.tasks', level='ERROR') as logs):
            tasks.process_thumbnail(video.pk, video.processing_key)
        video.refresh_from_db()
        self.assertEqual(video.processing_status, 'failed')
        self.assertTrue(any('Could not remove' in message for message in logs.output))