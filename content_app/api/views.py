import logging
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from content_app.api.serializers import VideoListSerializer
from content_app.models import Video

logger = logging.getLogger(__name__)
HLS_RESOLUTIONS = frozenset(('480p', '720p', '1080p'))


def private_response(response):
    """Prevent shared caches from storing a protected file response."""
    response['Cache-Control'] = 'private, no-store'
    return response


def hls_file(movie_id, resolution, name):
    """Return a safe existing HLS file path for a ready video or raise 404."""
    if resolution not in HLS_RESOLUTIONS:
        raise Http404
    video = get_object_or_404(Video, pk=movie_id, processing_status='ready')
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / video.hls_path / resolution / name).resolve()
    if not video.hls_path or not target.is_relative_to(root) or not target.is_file():
        logger.warning('HLS file unavailable for video %s resolution %s', movie_id, resolution)
        raise Http404
    return target


class VideoPlaylistView(APIView):
    """Serve the authenticated HLS playlist for a video resolution."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, movie_id, resolution):
        """Return the requested HLS playlist or a 404 response."""
        path = hls_file(movie_id, resolution, 'index.m3u8')
        try:
            data = path.read_bytes()
        except OSError:
            logger.exception('Could not read HLS playlist for video %s', movie_id)
            raise Http404
        return private_response(HttpResponse(data, content_type='application/vnd.apple.mpegurl'))


class VideoSegmentView(APIView):
    """Serve generated HLS transport stream segments to authenticated users."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = ()

    def get(self, request, movie_id, resolution, segment):
        """Stream a valid segment file, or return 404 if unavailable."""
        if not re.fullmatch(r'[0-9]{3,}\.ts', segment):
            raise Http404
        path = hls_file(movie_id, resolution, segment)
        try:
            return private_response(FileResponse(path.open('rb'), content_type='video/MP2T'))
        except OSError:
            logger.exception('Could not read HLS segment for video %s', movie_id)
            raise Http404


class ProtectedMediaView(APIView):
    """Serve locally stored media only to authenticated users."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, media_path):
        """Return a media file inside MEDIA_ROOT, or 404 for invalid paths."""
        root = Path(settings.MEDIA_ROOT).resolve()
        target = (root / media_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise Http404
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        try:
            return private_response(FileResponse(target.open('rb'), content_type=content_type))
        except OSError:
            raise Http404


class VideoListView(ListAPIView):
    """List available video metadata for authenticated users."""

    permission_classes = (IsAuthenticated,)
    serializer_class = VideoListSerializer
    queryset = Video.objects.filter(processing_status='ready', thumbnail__isnull=False).exclude(thumbnail='')