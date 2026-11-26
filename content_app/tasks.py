import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q

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
    query = Video.objects.filter(pk=video_id, processing_key=key, processing_status__in=('pending', 'queued'))
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
        old_hls_path = video.hls_path
        if video.thumbnail:
            video.hls_path = relative_dir
        video.processing_status = 'ready' if video.thumbnail else 'failed'
        video.processing_error = '' if video.thumbnail else 'Thumbnail unavailable.'
        video.save(update_fields=['thumbnail', 'hls_path', 'processing_status', 'processing_error'])
        handle_old_hls_cleanup(relative_dir, video, old_hls_path)
        return video.processing_status == 'ready'

def handle_old_hls_cleanup(relative_dir, video, old_hls_path):
    """Schedule cleanup of the old HLS directory if the video is ready and the path has changed."""
    if video.processing_status == 'ready' and old_hls_path and old_hls_path != relative_dir:
        transaction.on_commit(lambda: cleanup_old_hls(old_hls_path))

def cleanup_old_hls(old_hls_path):
    """Remove the old HLS directory if it exists and is safe to delete."""
    try:
        parts = old_hls_path.split('/') if old_hls_path else []
        if len(parts) != 3 or parts[0] != 'hls' or not parts[1].isdigit():
            return
        uuid.UUID(parts[2])
        directory = (Path(settings.MEDIA_ROOT) / old_hls_path).resolve()
        root = Path(settings.MEDIA_ROOT).resolve()
        hls_root = (root / 'hls').resolve()
        if (directory != hls_root and directory.parent.parent == hls_root
                and directory.is_relative_to(root)
                and not Video.objects.filter(hls_path=old_hls_path).exists()
                and check_thumbnails_not_in_old_hls(old_hls_path)):
            remove_old_directory(directory)
    except Exception:
        logger.exception('Could not clean up old HLS directory %s', old_hls_path)


def cleanup_replaced_assets(file_name, thumbnail_name):
    """Remove replaced source and thumbnail files when no video references them."""
    cleanup_stored_file('file', file_name)
    cleanup_stored_file('thumbnail', thumbnail_name)


def cleanup_stored_file(field_name, name):
    """Delete an unreferenced stored file and log storage errors."""
    if not name or Video.objects.filter(**{field_name: name}).exists():
        return
    try:
        Video._meta.get_field(field_name).storage.delete(name)
    except Exception:
        logger.exception('Could not delete unreferenced %s file %s', field_name, name)


def cleanup_deleted_video_assets(file_name, thumbnail_name, hls_path):
    """Remove a deleted video's files after its DB row is committed."""
    cleanup_replaced_assets(file_name, thumbnail_name)
    cleanup_old_hls(hls_path)


def convert_video(video, output):
    """Generate the video's HLS variants and optional thumbnail under output."""
    for height in RESOLUTIONS:
        generate_variant(video.file.path, output / f'{height}p', height)
    if not video.thumbnail:
        generate_thumbnail(video.file.path, output / 'thumbnail.jpg')
        return (output / 'thumbnail.jpg').relative_to(settings.MEDIA_ROOT).as_posix()
    return ''


def process_thumbnail(video_id, generation):
    """Regenerate a missing thumbnail without recreating existing HLS files."""
    video = claim_video(video_id, generation)
    if not video:
        return
    relative = f'thumbnails/generated/{video_id}/{generation}.jpg'
    output = Path(settings.MEDIA_ROOT) / relative
    handle_thumbnail_generation(video_id, generation, video, relative, output)

def handle_thumbnail_generation(video_id, generation, video, relative, output):
    """Handle the generation of a thumbnail for a video, including error handling."""
    try:
        generate_thumbnail(video.file.path, output)
        if not publish_video(video_id, generation, video.hls_path, relative):
            output.unlink(missing_ok=True)
    except Exception:
        logger.exception('Thumbnail processing failed for video %s', video_id)
        remove_generated_thumbnail(output)
        update_video_processing_status(video_id, generation)

def remove_generated_thumbnail(output):
    """Remove the generated thumbnail file if it exists."""
    try:
        output.unlink(missing_ok=True)
    except OSError:
        logger.exception('Could not remove generated thumbnail %s', output)

def update_video_processing_status(video_id, generation):
    """Update the processing status of a video to failed due to thumbnail processing failure."""
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
    handle_video_processing(video_id, video, key, relative_dir, output)

def handle_video_processing(video_id, video, key, relative_dir, output):
    """Process the video and publish it, handling failures appropriately."""
    try:
        thumbnail = convert_video(video, output)
        if not publish_video(video_id, key, relative_dir, thumbnail):
            shutil.rmtree(output, ignore_errors=True)
    except Exception:
        logger.exception('Video processing failed for video %s', video_id)
        mark_video_processing_failed(video_id, key, output)

def mark_video_processing_failed(video_id, key, output):
    """Mark the video processing as failed and remove the output directory."""
    Video.objects.filter(pk=video_id, processing_key=key).update(
            processing_status='failed', processing_error='Video processing failed; see logs.')
    shutil.rmtree(output, ignore_errors=True)

def remove_old_directory(directory):
    """Remove the specified directory if it exists and is a directory."""
    if directory.exists() and directory.is_dir():
        shutil.rmtree(directory)

def check_thumbnails_not_in_old_hls(old_hls_path):
    """Check if there are no thumbnails referencing the old HLS path."""
    path = old_hls_path.replace('\\', '/').rstrip('/')
    return not Video.objects.filter(
        Q(thumbnail__startswith=path + '/')
        | Q(thumbnail__startswith=path.replace('/', '\\') + '\\')
    ).exists()