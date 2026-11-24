from django.urls import path, include
from content_app.api.views import VideoListView

urlpatterns = [
    path('video/', VideoListView.as_view(), name='video-list')
]