from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('content_app', '0002_video_category_video_thumbnail'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='video',
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Video',
                'verbose_name_plural': 'Videos',
            },
        ),
    ]