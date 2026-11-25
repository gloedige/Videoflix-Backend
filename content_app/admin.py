from django.contrib import admin

from .models import Video


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'processing_status', 'created_at', 'updated_at')
    search_fields = ('title', 'description', 'category')
    list_filter = ('category', 'created_at', 'updated_at')
    readonly_fields = ('processing_status', 'processing_error', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'category', 'file', 'thumbnail')
        }),
        ('Processing', {
            'fields': ('processing_status', 'processing_error')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
