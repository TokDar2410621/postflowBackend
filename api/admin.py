from django.contrib import admin
from .models import GeneratedPost, LinkedInAccount, Subscription, UsageRecord, CartoonAvatar, CartoonUsageRecord


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


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'status', 'stripe_customer_id', 'current_period_end']
    list_filter = ['plan', 'status']
    search_fields = ['user__username', 'user__email', 'stripe_customer_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'year', 'month', 'generation_count']
    list_filter = ['year', 'month']
    search_fields = ['user__username']


@admin.register(CartoonAvatar)
class CartoonAvatarAdmin(admin.ModelAdmin):
    list_display = ['user', 'source_photo_url', 'created_at', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CartoonUsageRecord)
class CartoonUsageRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'year', 'month', 'cartoon_count']
    list_filter = ['year', 'month']
    search_fields = ['user__username']
