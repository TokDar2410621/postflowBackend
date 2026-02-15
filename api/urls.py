from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views
from . import linkedin
from . import auth
from . import schedule
from . import templates
from . import analytics
from . import images

urlpatterns = [
    # Auth
    path('auth/register/', auth.register, name='register'),
    path('auth/login/', auth.login, name='login'),
    path('auth/logout/', auth.logout, name='logout'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', auth.profile, name='profile'),

    # Posts
    path('generate/', views.generate_post, name='generate_post'),
    path('generate/variants/', views.generate_variants, name='generate_variants'),
    path('generate/variants/regenerate/', views.regenerate_single_variant, name='regenerate_single_variant'),
    path('generate/hashtags/', views.suggest_hashtags, name='suggest_hashtags'),
    path('posts/published/', views.list_published_posts, name='list_published_posts'),
    path('posts/', views.list_posts, name='list_posts'),
    path('posts/<int:pk>/', views.get_post, name='get_post'),

    # Scheduled Posts
    path('scheduled/', schedule.list_scheduled_posts, name='list_scheduled_posts'),
    path('scheduled/create/', schedule.schedule_post, name='schedule_post'),
    path('scheduled/<int:pk>/cancel/', schedule.cancel_scheduled_post, name='cancel_scheduled_post'),
    path('scheduled/<int:pk>/update/', schedule.update_scheduled_post, name='update_scheduled_post'),

    # Templates
    path('templates/', templates.list_templates, name='list_templates'),
    path('templates/create/', templates.create_template, name='create_template'),
    path('templates/<int:pk>/', templates.update_template, name='update_template'),
    path('templates/<int:pk>/delete/', templates.delete_template, name='delete_template'),

    # LinkedIn OAuth
    path('auth/linkedin/', linkedin.linkedin_auth, name='linkedin_auth'),
    path('auth/linkedin/callback', linkedin.linkedin_callback, name='linkedin_callback'),
    path('linkedin/status/', linkedin.linkedin_status, name='linkedin_status'),
    path('linkedin/publish/', linkedin.linkedin_publish, name='linkedin_publish'),
    path('linkedin/disconnect/', linkedin.linkedin_disconnect, name='linkedin_disconnect'),

    # Images (Pexels + Gemini)
    path('images/search/', images.search_images, name='search_images'),
    path('images/keywords/', images.suggest_image_keywords, name='suggest_image_keywords'),
    path('images/generate/', images.generate_image, name='generate_image'),

    # Analytics
    path('analytics/', analytics.get_analytics_summary, name='analytics_summary'),
    path('analytics/chart/', analytics.get_analytics_chart, name='analytics_chart'),
    path('analytics/top/', analytics.get_top_posts, name='analytics_top'),
    path('analytics/<int:pk>/update/', analytics.update_post_stats, name='update_post_stats'),
    path('analytics/refresh/', linkedin.refresh_stats, name='refresh_stats'),
]
