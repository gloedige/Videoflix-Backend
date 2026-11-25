import logging
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.db import transaction

from content_app.models import Video

logger = logging.getLogger(__name__)
RESOLUTIONS = (480, 720, 1080)


def run_ffmpeg(arguments):
    """Run FFmpeg with arguments and raise on conversion failure."""
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', *arguments],
                   check=True, capture_output=True, timeout=900)


def generate_variant(source, output, height):
    """Generate an HLS playlist and segments for source at the target height."""
    output.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        '-i', str(source), '-vf', f'scale=-2:{height}', '-c:v', 'libx264',
        '-preset', 'veryfast', '-threads', '2', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-f', 'hls', '-hls_time', '4', '-hls_playlist_type',
        'vod', '-hls_segment_filename', str(output / '%03d.ts'),
        str(output / 'index.m3u8'),
    ])
    if not (output / 'index.m3u8').is_file() or not any(output.glob('*.ts')):
        raise FileNotFoundError(f'Incomplete HLS output at {height}p')


def generate_thumbnail(source, output):
    """Extract the first video frame from source into output."""
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(['-i', str(source), '-frames:v', '1', '-threads', '1', str(output)])
    if not output.is_file():
        raise FileNotFoundError('Thumbnail was not created')


def claim_video(video_id, key):
    """Claim the pending video generation identified by video_id and key."""
    query = Video.objects.filter(pk=video_id, processing_key=key, processing_status='pending')
    if not query.update(processing_status='processing', processing_error=''):
        return None
    return query.model.objects.filter(pk=video_id, processing_key=key).first()


def publish_video(video_id, key, relative_dir, generated_thumbnail):
    """Publish completed files if this generation is still current."""
    with transaction.atomic():
        video = Video.objects.select_for_update().filter(pk=video_id, processing_key=key).first()
        if not video or video.processing_status != 'processing':
            return False
        if not video.thumbnail and generated_thumbnail:
            video.thumbnail = generated_thumbnail
        video.hls_path = relative_dir
        video.processing_status = 'ready' if video.thumbnail else 'failed'
        video.processing_error = '' if video.thumbnail else 'Thumbnail unavailable.'
        video.save(update_fields=['thumbnail', 'hls_path', 'processing_status', 'processing_error'])
        return video.processing_status == 'ready'


def convert_video(video, output):
    """Generate the video's HLS variants and optional thumbnail under output."""
    for height in RESOLUTIONS:
        generate_variant(video.file.path, output / f'{height}p', height)
    if not video.thumbnail:
        generate_thumbnail(video.file.path, output / 'thumbnail.jpg')
        return str((output / 'thumbnail.jpg').relative_to(settings.MEDIA_ROOT))
    return ''


def process_thumbnail(video_id, generation):
    """Regenerate a missing thumbnail without recreating existing HLS files."""
    video = claim_video(video_id, generation)
    if not video:
        return
    relative = f'thumbnails/generated/{video_id}/{generation}.jpg'
    output = Path(settings.MEDIA_ROOT) / relative
    try:
        generate_thumbnail(video.file.path, output)
        if not publish_video(video_id, generation, video.hls_path, relative):
            output.unlink(missing_ok=True)
    except Exception:
        logger.exception('Thumbnail processing failed for video %s', video_id)
        Video.objects.filter(pk=video_id, processing_key=generation).update(
            processing_status='failed', processing_error='Thumbnail processing failed; see logs.')


def process_video(video_id, generation=None):
    """Process a pending video generation and publish it only on success."""
    video = Video.objects.filter(pk=video_id).first()
    if not video:
        return
    key = generation or video.processing_key
    video = claim_video(video_id, key)
    if not video:
        return
    relative_dir = f'hls/{video_id}/{key}'
    output = Path(settings.MEDIA_ROOT) / relative_dir
    try:
        thumbnail = convert_video(video, output)
        if not publish_video(video_id, key, relative_dir, thumbnail):
            shutil.rmtree(output, ignore_errors=True)
    except Exception:
        logger.exception('Video processing failed for video %s', video_id)
        Video.objects.filter(pk=video_id, processing_key=key).update(
            processing_status='failed', processing_error='Video processing failed; see logs.')
        shutil.rmtree(output, ignore_errors=True)