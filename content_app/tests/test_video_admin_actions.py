import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from auth_app.models import CustomUser
from content_app import tasks
from content_app.models import Video


class VideoAdminActionsTest(TestCase):
    """Test processing actions through the admin and video list."""

    def setUp(self):
        """Provide an admin, isolated media storage, and a short silent video."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(MEDIA_ROOT=self.directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        fixture = Path(self.directory.name) / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'color=s=64x48:r=5:d=1', '-pix_fmt', 'yuv420p',
                        str(fixture)], check=True)
        self.video = Video.objects.create(
            title='Existing', description='A video',
            file=SimpleUploadedFile('source.mp4', fixture.read_bytes()),
        )
        self.admin = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='password',
        )
        self.client.force_login(self.admin)

    def test_existing_video_can_be_processed_from_admin(self):
        """An existing pending video becomes listed after an admin starts its job."""
        with patch('django_rq.get_queue') as queue, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/admin/content_app/video/', {
                'action': 'start_processing', '_selected_action': [str(self.video.pk)],
            })
        self.assertEqual(response.status_code, 302)
        queue.return_value.enqueue.assert_called_once()
        task, *args = queue.return_value.enqueue.call_args.args
        task(*args)
        client = APIClient()
        client.force_authenticate(user=self.admin)
        self.assertEqual([item['id'] for item in client.get('/api/video/').data], [self.video.pk])

    def test_normal_action_skips_queued_and_processing_videos(self):
        """The normal action does not enqueue a second active job."""
        for state in ('queued', 'processing'):
            with self.subTest(state=state):
                Video.objects.filter(pk=self.video.pk).update(processing_status=state)
                with patch('django_rq.get_queue') as queue, self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post('/admin/content_app/video/', {
                        'action': 'start_processing', '_selected_action': [str(self.video.pk)],
                    })
                self.assertEqual(response.status_code, 302)
                queue.return_value.enqueue.assert_not_called()
                self.video.refresh_from_db()
                self.assertEqual(self.video.processing_status, state)

    def test_force_recovery_invalidates_previous_generation(self):
        """Explicit recovery starts a new job and prevents the old job publishing."""
        old_key = self.video.processing_key
        Video.objects.filter(pk=self.video.pk).update(processing_status='processing')
        with patch('django_rq.get_queue') as queue, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/admin/content_app/video/', {
                'action': 'recover_processing', '_selected_action': [str(self.video.pk)],
            })
        self.assertEqual(response.status_code, 302)
        queue.return_value.enqueue.assert_called_once()
        tasks.process_video(self.video.pk, str(old_key))
        client = APIClient()
        client.force_authenticate(user=self.admin)
        self.assertEqual(client.get('/api/video/').data, [])
        task, *args = queue.return_value.enqueue.call_args.args
        task(*args)
        self.assertEqual([item['id'] for item in client.get('/api/video/').data], [self.video.pk])

    def test_failed_video_can_be_reprocessed(self):
        """An administrator can retry a failed video and clear its error."""
        Video.objects.filter(pk=self.video.pk).update(
            processing_status='failed', processing_error='Previous error',
        )
        with patch('django_rq.get_queue') as queue, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/admin/content_app/video/', {
                'action': 'start_processing', '_selected_action': [str(self.video.pk)],
            })
        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, 'queued')
        self.assertEqual(self.video.processing_error, '')
        task, *args = queue.return_value.enqueue.call_args.args
        task(*args)
        client = APIClient()
        client.force_authenticate(user=self.admin)
        self.assertEqual([item['id'] for item in client.get('/api/video/').data], [self.video.pk])

    def test_view_only_staff_cannot_start_processing(self):
        """Staff with only view permission cannot start a processing action."""
        user = CustomUser.objects.create_user(username='viewer', password='password', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='view_video'))
        self.client.force_login(user)
        with patch('django_rq.get_queue') as queue, self.captureOnCommitCallbacks(execute=True):
            self.client.post('/admin/content_app/video/', {
                'action': 'start_processing', '_selected_action': [str(self.video.pk)],
            })
        queue.return_value.enqueue.assert_not_called()

    def test_queue_error_is_visible_after_admin_action(self):
        """An unavailable queue leaves a visible failure instead of a stuck job."""
        with (patch('django_rq.get_queue', side_effect=ConnectionError('offline')),
              self.assertLogs('content_app.signals', level='ERROR'),
              self.captureOnCommitCallbacks(execute=True)):
            self.client.post('/admin/content_app/video/', {
                'action': 'start_processing', '_selected_action': [str(self.video.pk)],
            })
        response = self.client.get(f'/admin/content_app/video/{self.video.pk}/change/')
        self.assertContains(response, 'Queue unavailable; see logs.')
        self.assertContains(response, 'failed')