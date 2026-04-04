import base64
import json
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import FacebookAccount, UserProfile, Subscription

logger = logging.getLogger(__name__)

FB_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
FB_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
FB_GRAPH_URL = "https://graph.facebook.com/v21.0"

SCOPES = "pages_manage_posts,pages_read_engagement,pages_show_list,public_profile,email"


@api_view(['GET'])
@permission_classes([AllowAny])
def facebook_auth(request):
    """Facebook login (unauthenticated) — redirect to Facebook OAuth"""
    state = secrets.token_urlsafe(32)
    cache.set(f'facebook_oauth:{state}', {
        'action': 'login',
    }, timeout=600)

    params = {
        'client_id': settings.FACEBOOK_APP_ID,
        'redirect_uri': settings.FACEBOOK_REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
        'response_type': 'code',
    }
    return redirect(f"{FB_AUTH_URL}?{urlencode(params)}")


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def facebook_init_auth(request):
    """Facebook connect (authenticated) — generate OAuth URL"""
    state = secrets.token_urlsafe(32)
    cache.set(f'facebook_oauth:{state}', {
        'action': 'connect',
        'user_id': str(request.user.id),
    }, timeout=600)

    params = {
        'client_id': settings.FACEBOOK_APP_ID,
        'redirect_uri': settings.FACEBOOK_REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
        'response_type': 'code',
    }
    return Response({'auth_url': f"{FB_AUTH_URL}?{urlencode(params)}"})


def _exchange_token(code):
    """Exchange code for long-lived token"""
    token_resp = requests.get(FB_TOKEN_URL, params={
        'client_id': settings.FACEBOOK_APP_ID,
        'client_secret': settings.FACEBOOK_APP_SECRET,
        'redirect_uri': settings.FACEBOOK_REDIRECT_URI,
        'code': code,
    }, timeout=10)

    if not token_resp.ok:
        logger.error(f"Facebook token exchange failed: {token_resp.text}")
        return None, 0

    short_token = token_resp.json()['access_token']

    # Exchange for long-lived token (60 days)
    ll_resp = requests.get(FB_TOKEN_URL, params={
        'grant_type': 'fb_exchange_token',
        'client_id': settings.FACEBOOK_APP_ID,
        'client_secret': settings.FACEBOOK_APP_SECRET,
        'fb_exchange_token': short_token,
    }, timeout=10)

    if ll_resp.ok:
        ll_data = ll_resp.json()
        return ll_data['access_token'], ll_data.get('expires_in', 5184000)

    return short_token, 3600


def _get_fb_profile(access_token):
    """Get Facebook user profile"""
    me_resp = requests.get(f"{FB_GRAPH_URL}/me", params={
        'fields': 'id,name,email,picture.type(large)',
        'access_token': access_token,
    }, timeout=10)
    return me_resp.json() if me_resp.ok else None


def _get_fb_pages(access_token):
    """Get user's Facebook pages"""
    pages_resp = requests.get(f"{FB_GRAPH_URL}/me/accounts", params={
        'access_token': access_token,
    }, timeout=10)

    if pages_resp.ok:
        pages = pages_resp.json().get('data', [])
        if pages:
            return pages[0]['id'], pages[0]['access_token']
    return '', ''


@api_view(['GET'])
def facebook_callback(request):
    """Facebook OAuth callback — handles both login and connect flows"""
    code = request.GET.get('code')
    state = request.GET.get('state', '')
    error = request.GET.get('error')
    frontend = getattr(settings, 'FRONTEND_URL', 'http://localhost:8080')

    if error:
        return redirect(f"{frontend}/login?facebook_error={error}")

    cached = cache.get(f'facebook_oauth:{state}')
    if not cached:
        return redirect(f"{frontend}/login?facebook_error=invalid_state")

    cache.delete(f'facebook_oauth:{state}')
    action = cached.get('action', 'connect')

    # Exchange code for token
    access_token, expires_in = _exchange_token(code)
    if not access_token:
        return redirect(f"{frontend}/login?facebook_error=token_failed")

    # Get profile
    me = _get_fb_profile(access_token)
    if not me:
        return redirect(f"{frontend}/login?facebook_error=userinfo_failed")

    fb_id = me['id']
    name = me.get('name', '')
    email = me.get('email', '')
    picture = me.get('picture', {}).get('data', {}).get('url', '')

    # Get pages
    page_id, page_access_token = _get_fb_pages(access_token)

    if action == 'login':
        # --- Login flow: find or create Django user ---
        existing_account = FacebookAccount.objects.filter(facebook_id=fb_id).select_related('user').first()

        if existing_account and existing_account.user:
            user = existing_account.user
            existing_account.access_token = access_token
            existing_account.page_id = page_id
            existing_account.page_access_token = page_access_token
            existing_account.name = name
            existing_account.profile_picture_url = picture
            existing_account.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            existing_account.save()
        else:
            # Find existing user by email or create new one
            user = None
            if email:
                user = DjangoUser.objects.filter(email=email).first()

            if not user:
                username = name.replace(' ', '_').lower() if name else f'fb_{fb_id}'
                base_username = username
                counter = 1
                while DjangoUser.objects.filter(username=username).exists():
                    username = f'{base_username}_{counter}'
                    counter += 1

                user = DjangoUser.objects.create_user(
                    username=username,
                    email=email,
                    first_name=name.split(' ')[0] if name else '',
                    last_name=' '.join(name.split(' ')[1:]) if name and ' ' in name else '',
                )
                UserProfile.objects.get_or_create(user=user)
                Subscription.objects.get_or_create(user=user, defaults={'plan': 'free', 'status': 'active'})

            FacebookAccount.objects.update_or_create(
                facebook_id=fb_id,
                defaults={
                    'user': user,
                    'name': name,
                    'profile_picture_url': picture,
                    'access_token': access_token,
                    'page_id': page_id,
                    'page_access_token': page_access_token,
                    'token_expires_at': timezone.now() + timedelta(seconds=expires_in),
                },
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        auth_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email or '',
                'is_staff': user.is_staff,
            },
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }
        encoded = base64.urlsafe_b64encode(json.dumps(auth_data).encode()).decode()
        return redirect(f"{frontend}?facebook_auth={encoded}")

    else:
        # --- Connect flow: link to existing user ---
        user_id = cached.get('user_id')
        try:
            django_user = DjangoUser.objects.get(id=user_id)
        except DjangoUser.DoesNotExist:
            return redirect(f"{frontend}/profile?facebook_error=user_not_found")

        FacebookAccount.objects.update_or_create(
            facebook_id=fb_id,
            defaults={
                'user': django_user,
                'name': name,
                'profile_picture_url': picture,
                'access_token': access_token,
                'page_id': page_id,
                'page_access_token': page_access_token,
                'token_expires_at': timezone.now() + timedelta(seconds=expires_in),
            },
        )
        return redirect(f"{frontend}/profile?facebook_connected=1")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def facebook_status(request):
    try:
        acc = request.user.facebook_account
        return Response({
            'connected': True,
            'name': acc.name,
            'profile_picture_url': acc.profile_picture_url,
            'has_page': bool(acc.page_id),
        })
    except FacebookAccount.DoesNotExist:
        return Response({'connected': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def facebook_disconnect(request):
    try:
        request.user.facebook_account.delete()
    except FacebookAccount.DoesNotExist:
        pass
    return Response({'success': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def facebook_publish(request):
    """Publie un post sur la page Facebook de l'utilisateur"""
    content = request.data.get('content', '').strip()
    if not content:
        return Response({'error': 'Contenu requis'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        acc = request.user.facebook_account
    except FacebookAccount.DoesNotExist:
        return Response({'error': 'Facebook non connecte'}, status=status.HTTP_400_BAD_REQUEST)

    if not acc.page_id or not acc.page_access_token:
        return Response({'error': 'Aucune page Facebook connectee'}, status=status.HTTP_400_BAD_REQUEST)

    image = request.FILES.get('image')

    try:
        if image:
            resp = requests.post(
                f"{FB_GRAPH_URL}/{acc.page_id}/photos",
                data={'message': content, 'access_token': acc.page_access_token},
                files={'source': (image.name, image.read(), image.content_type)},
                timeout=30,
            )
        else:
            resp = requests.post(
                f"{FB_GRAPH_URL}/{acc.page_id}/feed",
                data={'message': content, 'access_token': acc.page_access_token},
                timeout=15,
            )

        if resp.ok:
            post_id = resp.json().get('id', resp.json().get('post_id', ''))
            return Response({
                'success': True,
                'post_id': post_id,
                'message': 'Post publie sur Facebook',
            })

        logger.error(f"Facebook publish failed: {resp.text}")
        return Response({'error': 'Echec de la publication Facebook'}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Facebook publish error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
