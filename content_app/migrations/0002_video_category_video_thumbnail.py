from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content_app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='category',
            field=models.CharField(default='Uncategorized', max_length=100),
        ),
        migrations.AddField(
            model_name='video',
            name='thumbnail',
            field=models.FileField(blank=True, null=True, upload_to='thumbnails/'),
        ),
    ]