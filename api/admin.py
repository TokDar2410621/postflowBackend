from django.contrib import admin
from .models import GeneratedPost, LinkedInAccount


@admin.register(GeneratedPost)
class GeneratedPostAdmin(admin.ModelAdmin):
    list_display = ['id', 'tone', 'created_at']
    list_filter = ['tone', 'created_at']
    search_fields = ['summary', 'generated_content']
    readonly_fields = ['created_at']


@admin.register(LinkedInAccount)
class LinkedInAccountAdmin(admin.ModelAdmin):
    list_display = ['linkedin_id', 'name', 'expires_at', 'created_at']
    readonly_fields = ['linkedin_id', 'created_at', 'updated_at']
