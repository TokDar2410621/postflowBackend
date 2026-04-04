import logging
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import InstagramAccount

logger = logging.getLogger(__name__)

FB_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
FB_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
FB_GRAPH_URL = "https://graph.facebook.com/v21.0"

# Instagram needs page permissions + instagram_basic + instagram_content_publish
SCOPES = "pages_show_list,instagram_basic,instagram_content_publish"


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def instagram_init_auth(request):
    """Generate Instagram OAuth URL (via Facebook)"""
    state = secrets.token_urlsafe(32)
    cache.set(f'instagram_oauth:{state}', {
        'user_id': str(request.user.id),
    }, timeout=600)

    params = {
        'client_id': settings.FACEBOOK_APP_ID,
        'redirect_uri': settings.INSTAGRAM_REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
        'response_type': 'code',
    }
    return Response({'auth_url': f"{FB_AUTH_URL}?{urlencode(params)}"})


@api_view(['GET'])
def instagram_callback(request):
    """Instagram OAuth callback — exchange code, find IG business account"""
    code = request.GET.get('code')
    state = request.GET.get('state', '')
    error = request.GET.get('error')
    frontend = getattr(settings, 'FRONTEND_URL', 'http://localhost:8080')

    if error:
        return redirect(f"{frontend}/profile?instagram_error={error}")

    cached = cache.get(f'instagram_oauth:{state}')
    if not cached:
        return redirect(f"{frontend}/profile?instagram_error=invalid_state")

    cache.delete(f'instagram_oauth:{state}')
    user_id = cached['user_id']

    # Exchange code for short-lived token
    token_resp = requests.get(FB_TOKEN_URL, params={
        'client_id': settings.FACEBOOK_APP_ID,
        'client_secret': settings.FACEBOOK_APP_SECRET,
        'redirect_uri': settings.INSTAGRAM_REDIRECT_URI,
        'code': code,
    }, timeout=10)

    if not token_resp.ok:
        logger.error(f"Instagram token exchange failed: {token_resp.text}")
        return redirect(f"{frontend}/profile?instagram_error=token_failed")

    short_token = token_resp.json()['access_token']

    # Exchange for long-lived token
    ll_resp = requests.get(FB_TOKEN_URL, params={
        'grant_type': 'fb_exchange_token',
        'client_id': settings.FACEBOOK_APP_ID,
        'client_secret': settings.FACEBOOK_APP_SECRET,
        'fb_exchange_token': short_token,
    }, timeout=10)

    if ll_resp.ok:
        ll_data = ll_resp.json()
        access_token = ll_data['access_token']
        expires_in = ll_data.get('expires_in', 5184000)
    else:
        access_token = short_token
        expires_in = 3600

    # Get user's pages
    pages_resp = requests.get(f"{FB_GRAPH_URL}/me/accounts", params={
        'access_token': access_token,
    }, timeout=10)

    if not pages_resp.ok:
        return redirect(f"{frontend}/profile?instagram_error=pages_failed")

    pages = pages_resp.json().get('data', [])

    # Find Instagram Business Account linked to a page
    ig_account = None
    fb_page_id = ''
    for page in pages:
        ig_resp = requests.get(
            f"{FB_GRAPH_URL}/{page['id']}",
            params={
                'fields': 'instagram_business_account',
                'access_token': access_token,
            },
            timeout=10,
        )
        if ig_resp.ok:
            ig_data = ig_resp.json().get('instagram_business_account')
            if ig_data:
                ig_account = ig_data
                fb_page_id = page['id']
                break

    if not ig_account:
        return redirect(f"{frontend}/profile?instagram_error=no_instagram_business")

    ig_id = ig_account['id']

    # Get Instagram profile info
    ig_profile_resp = requests.get(
        f"{FB_GRAPH_URL}/{ig_id}",
        params={
            'fields': 'username,name,profile_picture_url',
            'access_token': access_token,
        },
        timeout=10,
    )

    ig_profile = ig_profile_resp.json() if ig_profile_resp.ok else {}

    try:
        django_user = DjangoUser.objects.get(id=user_id)
    except DjangoUser.DoesNotExist:
        return redirect(f"{frontend}/profile?instagram_error=user_not_found")

    InstagramAccount.objects.update_or_create(
        instagram_id=ig_id,
        defaults={
            'user': django_user,
            'username': ig_profile.get('username', ''),
            'name': ig_profile.get('name', ''),
            'profile_picture_url': ig_profile.get('profile_picture_url', ''),
            'access_token': access_token,
            'fb_page_id': fb_page_id,
            'token_expires_at': timezone.now() + __import__('datetime').timedelta(seconds=expires_in),
        },
    )
    return redirect(f"{frontend}/profile?instagram_connected=1")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def instagram_status(request):
    try:
        acc = request.user.instagram_account
        return Response({
            'connected': True,
            'username': acc.username,
            'name': acc.name,
            'profile_picture_url': acc.profile_picture_url,
        })
    except InstagramAccount.DoesNotExist:
        return Response({'connected': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def instagram_disconnect(request):
    try:
        request.user.instagram_account.delete()
    except InstagramAccount.DoesNotExist:
        pass
    return Response({'success': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def instagram_publish(request):
    """Publie un post Instagram (image requise pour Instagram)"""
    content = request.data.get('content', '').strip()
    image_url = request.data.get('image_url', '').strip()

    if not image_url:
        return Response(
            {'error': 'Instagram requiert une image. Fournissez image_url.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        acc = request.user.instagram_account
    except InstagramAccount.DoesNotExist:
        return Response({'error': 'Instagram non connecte'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Step 1: Create media container
        container_resp = requests.post(
            f"{FB_GRAPH_URL}/{acc.instagram_id}/media",
            data={
                'image_url': image_url,
                'caption': content,
                'access_token': acc.access_token,
            },
            timeout=30,
        )

        if not container_resp.ok:
            logger.error(f"Instagram container creation failed: {container_resp.text}")
            return Response({'error': 'Echec creation du media Instagram'}, status=status.HTTP_400_BAD_REQUEST)

        container_id = container_resp.json()['id']

        # Step 2: Publish the container
        publish_resp = requests.post(
            f"{FB_GRAPH_URL}/{acc.instagram_id}/media_publish",
            data={
                'creation_id': container_id,
                'access_token': acc.access_token,
            },
            timeout=30,
        )

        if publish_resp.ok:
            post_id = publish_resp.json()['id']
            return Response({
                'success': True,
                'post_id': post_id,
                'message': 'Post publie sur Instagram',
            })

        logger.error(f"Instagram publish failed: {publish_resp.text}")
        return Response({'error': 'Echec de la publication Instagram'}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Instagram publish error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
