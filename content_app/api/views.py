from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from content_app.api.serializers import VideoListSerializer
from content_app.models import Video


class VideoListView(ListAPIView):
    """List available video metadata for authenticated users."""

    permission_classes = (IsAuthenticated,)
    serializer_class = VideoListSerializer
    queryset = Video.objects.filter(processing_status='ready').exclude(thumbnail='')