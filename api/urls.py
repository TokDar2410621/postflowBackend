from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views
from . import linkedin
from . import auth
from . import schedule
from . import templates
from . import analytics
from . import images
from . import carousel
from . import infographic
from . import comments
from . import twitter
from . import repurpose
from . import convert

urlpatterns = [
    # Auth
    path('auth/register/', auth.register, name='register'),
    path('auth/login/', auth.login, name='login'),
    path('auth/logout/', auth.logout, name='logout'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', auth.profile, name='profile'),
    path('auth/claim-session/', auth.claim_session, name='claim_session'),
    path('auth/password-reset/', auth.password_reset_request, name='password_reset_request'),
    path('auth/password-reset/confirm/', auth.password_reset_confirm, name='password_reset_confirm'),

    # Posts
    path('generate/', views.generate_post, name='generate_post'),
    path('generate/variants/', views.generate_variants, name='generate_variants'),
    path('generate/variants/regenerate/', views.regenerate_single_variant, name='regenerate_single_variant'),
    path('generate/hashtags/', views.suggest_hashtags, name='suggest_hashtags'),
    path('generate/hook/', views.regenerate_hook, name='regenerate_hook'),
    path('generate/first-comment/', views.generate_first_comment, name='generate_first_comment'),
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
    path('templates/<int:pk>/duplicate/', templates.duplicate_template, name='duplicate_template'),

    # LinkedIn OAuth
    path('auth/linkedin/', linkedin.linkedin_auth, name='linkedin_auth'),
    path('auth/linkedin/init/', linkedin.linkedin_init_auth, name='linkedin_init_auth'),
    path('auth/linkedin/callback', linkedin.linkedin_callback, name='linkedin_callback'),
    path('linkedin/status/', linkedin.linkedin_status, name='linkedin_status'),
    path('linkedin/publish/', linkedin.linkedin_publish, name='linkedin_publish'),
    path('linkedin/publish/carousel/', linkedin.linkedin_publish_carousel, name='linkedin_publish_carousel'),
    path('linkedin/disconnect/', linkedin.linkedin_disconnect, name='linkedin_disconnect'),

    # Images (Pexels + Gemini + HuggingFace)
    path('images/search/', images.search_images, name='search_images'),
    path('images/keywords/', images.suggest_image_keywords, name='suggest_image_keywords'),
    path('images/generate/', images.generate_image, name='generate_image'),
    path('images/generate-hf/', images.generate_image_hf, name='generate_image_hf'),

    # Carousel
    path('carousel/generate/', carousel.generate_carousel, name='generate_carousel'),
    path('carousel/generate-caption/', carousel.generate_carousel_caption, name='generate_carousel_caption'),

    # Infographic
    path('infographic/generate/', infographic.generate_infographic, name='generate_infographic'),
    path('infographic/generate-caption/', infographic.generate_infographic_caption, name='generate_infographic_caption'),

    # Comments (fetch, analyze, reply)
    path('comments/analyze/', comments.analyze_comments, name='analyze_comments'),
    path('comments/reply/', comments.reply_to_comment, name='reply_to_comment'),
    path('comments/<int:post_id>/', comments.fetch_comments, name='fetch_comments'),

    # Twitter/X OAuth + publish
    path('auth/twitter/init/', twitter.twitter_init_auth, name='twitter_init_auth'),
    path('auth/twitter/callback/', twitter.twitter_callback, name='twitter_callback'),
    path('twitter/status/', twitter.twitter_status, name='twitter_status'),
    path('twitter/disconnect/', twitter.twitter_disconnect, name='twitter_disconnect'),
    path('twitter/publish/', twitter.twitter_publish, name='twitter_publish'),

    # Analytics
    # Repurpose (URL extraction)
    path('repurpose/extract/', repurpose.extract_url_content, name='extract_url_content'),

    # Convert between formats
    path('convert/to-carousel/', convert.convert_to_carousel, name='convert_to_carousel'),
    path('convert/to-infographic/', convert.convert_to_infographic, name='convert_to_infographic'),
    path('convert/to-post/', convert.convert_to_post, name='convert_to_post'),

    path('analytics/', analytics.get_analytics_summary, name='analytics_summary'),
    path('analytics/chart/', analytics.get_analytics_chart, name='analytics_chart'),
    path('analytics/top/', analytics.get_top_posts, name='analytics_top'),
    path('analytics/refresh/', linkedin.refresh_stats, name='refresh_stats'),
]
