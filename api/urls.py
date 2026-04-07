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
from . import billing
from . import cartoon
from . import pdf_views
from . import websearch
from . import autopilot
from . import knowledge_base
from . import facebook
from . import instagram
from . import adapt

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
    path('auth/delete-account/', auth.delete_account, name='delete_account'),

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
    path('auth/twitter/', twitter.twitter_auth, name='twitter_auth'),
    path('auth/twitter/init/', twitter.twitter_init_auth, name='twitter_init_auth'),
    path('auth/twitter/callback/', twitter.twitter_callback, name='twitter_callback'),
    path('twitter/status/', twitter.twitter_status, name='twitter_status'),
    path('twitter/disconnect/', twitter.twitter_disconnect, name='twitter_disconnect'),
    path('twitter/publish/', twitter.twitter_publish, name='twitter_publish'),

    # Facebook
    path('auth/facebook/', facebook.facebook_auth, name='facebook_auth'),
    path('auth/facebook/init/', facebook.facebook_init_auth, name='facebook_init_auth'),
    path('auth/facebook/callback/', facebook.facebook_callback, name='facebook_callback'),
    path('facebook/status/', facebook.facebook_status, name='facebook_status'),
    path('facebook/disconnect/', facebook.facebook_disconnect, name='facebook_disconnect'),
    path('facebook/publish/', facebook.facebook_publish, name='facebook_publish'),

    # Instagram
    path('auth/instagram/init/', instagram.instagram_init_auth, name='instagram_init_auth'),
    path('auth/instagram/callback/', instagram.instagram_callback, name='instagram_callback'),
    path('instagram/status/', instagram.instagram_status, name='instagram_status'),
    path('instagram/disconnect/', instagram.instagram_disconnect, name='instagram_disconnect'),
    path('instagram/publish/', instagram.instagram_publish, name='instagram_publish'),

    # Analytics
    # Repurpose (URL extraction)
    path('repurpose/extract/', repurpose.extract_url_content, name='extract_url_content'),
    path('repurpose/extract-ideas/', repurpose.extract_multi_posts, name='extract_multi_posts'),

    # Web search
    path('web/search/', websearch.web_search, name='web_search'),
    path('web/images/', websearch.web_image_search, name='web_image_search'),
    path('web/proxy-image/', websearch.proxy_image, name='proxy_image'),

    # Autopilot
    path('autopilot/config/', autopilot.get_autopilot_config, name='autopilot_config_get'),
    path('autopilot/config/update/', autopilot.update_autopilot_config, name='autopilot_config_update'),
    path('autopilot/queue/', autopilot.get_autopilot_queue, name='autopilot_queue'),
    path('autopilot/queue/<int:pk>/approve/', autopilot.approve_autopilot_post, name='autopilot_approve'),
    path('autopilot/queue/<int:pk>/reject/', autopilot.reject_autopilot_post, name='autopilot_reject'),
    path('autopilot/generate-now/', autopilot.trigger_generation, name='autopilot_generate'),
    path('autopilot/history/', autopilot.get_autopilot_history, name='autopilot_history'),

    # Knowledge Base
    path('knowledge-base/', knowledge_base.list_documents, name='kb_list'),
    path('knowledge-base/upload/', knowledge_base.upload_document, name='kb_upload'),
    path('knowledge-base/<int:pk>/delete/', knowledge_base.delete_document, name='kb_delete'),
    path('knowledge-base/stats/', knowledge_base.kb_stats, name='kb_stats'),

    # Drafts (saved variants / ideas)
    path('drafts/', views.list_drafts, name='list_drafts'),
    path('drafts/save/', views.save_drafts, name='save_drafts'),
    path('drafts/<int:pk>/', views.delete_draft, name='delete_draft'),

    # Convert between formats
    path('convert/to-carousel/', convert.convert_to_carousel, name='convert_to_carousel'),
    path('convert/to-infographic/', convert.convert_to_infographic, name='convert_to_infographic'),
    path('convert/to-post/', convert.convert_to_post, name='convert_to_post'),

    # Adapt (cross-platform)
    path('adapt/', adapt.adapt_post, name='adapt_post'),

    # PDF Export (Playwright server-side)
    path('carousel/export-pdf/', pdf_views.export_carousel_pdf, name='export_carousel_pdf'),
    path('cartoon-dialogue/export-pdf/', pdf_views.export_cartoon_pdf, name='export_cartoon_pdf'),

    # Cartoon Dialogue
    path('cartoon-dialogue/avatar/', cartoon.get_avatar, name='get_cartoon_avatar'),
    path('cartoon-dialogue/generate-avatar/', cartoon.generate_avatar, name='generate_cartoon_avatar'),
    path('cartoon-dialogue/validate-avatar/', cartoon.validate_avatar, name='validate_cartoon_avatar'),
    path('cartoon-dialogue/regenerate-avatar/', cartoon.regenerate_avatar, name='regenerate_cartoon_avatar'),
    path('cartoon-dialogue/generate/', cartoon.generate_cartoon_dialogue, name='generate_cartoon_dialogue'),

    # Billing / Stripe
    path('billing/status/', billing.billing_status, name='billing_status'),
    path('billing/create-checkout-session/', billing.create_checkout_session, name='create_checkout'),
    path('billing/create-portal-session/', billing.create_portal_session, name='create_portal'),
    path('billing/webhook/', billing.stripe_webhook, name='stripe_webhook'),

    path('analytics/', analytics.get_analytics_summary, name='analytics_summary'),
    path('analytics/chart/', analytics.get_analytics_chart, name='analytics_chart'),
    path('analytics/top/', analytics.get_top_posts, name='analytics_top'),
    path('analytics/refresh/', linkedin.refresh_stats, name='refresh_stats'),
]
