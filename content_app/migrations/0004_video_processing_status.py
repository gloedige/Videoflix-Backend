import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('content_app', '0003_alter_video_options')]

    operations = [
        migrations.AddField(
            model_name='video', name='processing_status',
            field=models.CharField(default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='video', name='processing_key',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name='video', name='processing_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='video', name='hls_path',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]