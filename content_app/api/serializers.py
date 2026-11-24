from rest_framework import serializers

from content_app.models import Video


class VideoListSerializer(serializers.ModelSerializer):
    """Serialize video metadata and an absolute thumbnail URL."""

    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = ['id', 'created_at', 'title', 'description', 'thumbnail_url', 'category']
        read_only_fields = fields

    def get_thumbnail_url(self, video):
        """Return the thumbnail URL, or null when no thumbnail is available."""
        if not video.thumbnail:
            return None
        url = video.thumbnail.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url