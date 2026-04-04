import base64
import hashlib
import json
import logging
import os
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
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import TwitterAccount
from .social_auth import find_or_create_user

logger = logging.getLogger(__name__)

TWITTER_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
TWITTER_USER_URL = "https://api.twitter.com/2/users/me"
TWITTER_TWEET_URL = "https://api.twitter.com/2/tweets"
TWITTER_REDIRECT_URI = os.getenv(
    'TWITTER_REDIRECT_URI',
    'https://web-production-c2691.up.railway.app/api/auth/twitter/callback/'
)


def _generate_pkce():
    code_verifier = secrets.token_urlsafe(43)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return code_verifier, code_challenge


def _basic_auth_header():
    credential = f"{settings.TWITTER_CLIENT_ID}:{settings.TWITTER_CLIENT_SECRET}"
    return base64.b64encode(credential.encode()).decode()


def _build_auth_url(state, code_challenge):
    params = {
        'response_type': 'code',
        'client_id': settings.TWITTER_CLIENT_ID,
        'redirect_uri': TWITTER_REDIRECT_URI,
        'scope': 'tweet.write tweet.read users.read offline.access',
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
    }
    return f"{TWITTER_AUTH_URL}?{urlencode(params)}"


@api_view(['GET'])
@permission_classes([AllowAny])
def twitter_auth(request):
    """Twitter login (unauthenticated) — redirect to Twitter OAuth"""
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    cache.set(f'twitter_oauth:{state}', {
        'action': 'login',
        'code_verifier': code_verifier,
    }, timeout=600)

    return redirect(_build_auth_url(state, code_challenge))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def twitter_init_auth(request):
    """Twitter connect (authenticated) — generate OAuth URL"""
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    cache.set(f'twitter_oauth:{state}', {
        'action': 'connect',
        'user_id': str(request.user.id),
        'code_verifier': code_verifier,
    }, timeout=600)

    return Response({'auth_url': _build_auth_url(state, code_challenge)})


@api_view(['GET'])
def twitter_callback(request):
    """Callback OAuth Twitter — handles both login and connect flows"""
    code = request.GET.get('code')
    state = request.GET.get('state', '')
    error = request.GET.get('error')
    frontend = getattr(settings, 'FRONTEND_URL', 'http://localhost:8080')

    if error:
        return redirect(f"{frontend}/login?twitter_error={error}")

    cached = cache.get(f'twitter_oauth:{state}')
    if not cached:
        return redirect(f"{frontend}/login?twitter_error=invalid_state")

    cache.delete(f'twitter_oauth:{state}')
    action = cached.get('action', 'connect')
    code_verifier = cached['code_verifier']

    # Exchange code for tokens
    token_resp = requests.post(
        TWITTER_TOKEN_URL,
        headers={
            'Authorization': f'Basic {_basic_auth_header()}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': TWITTER_REDIRECT_URI,
            'code_verifier': code_verifier,
        },
        timeout=10,
    )
    if not token_resp.ok:
        logger.error(f"Twitter token exchange failed: {token_resp.status_code} — {token_resp.text}")
        return redirect(f"{frontend}/login?twitter_error=token_failed")

    tokens = token_resp.json()
    access_token = tokens['access_token']
    refresh_token = tokens.get('refresh_token', '')
    expires_in = tokens.get('expires_in', 7200)

    # Get Twitter profile
    user_resp = requests.get(
        f"{TWITTER_USER_URL}?user.fields=profile_image_url,name",
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    if not user_resp.ok:
        return redirect(f"{frontend}/login?twitter_error=user_info_failed")

    tw = user_resp.json()['data']
    twitter_id = tw['id']
    username = tw['username']
    name = tw.get('name', '')
    profile_pic = tw.get('profile_image_url', '').replace('_normal', '_400x400')

    if action == 'login':
        # --- Login flow: find or create Django user ---
        user = find_or_create_user('twitter', twitter_id, '', name, username)

        TwitterAccount.objects.update_or_create(
            twitter_id=twitter_id,
            defaults={
                'user': user,
                'username': username,
                'name': name,
                'profile_picture_url': profile_pic,
                'access_token': access_token,
                'refresh_token': refresh_token,
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
        return redirect(f"{frontend}?twitter_auth={encoded}")

    else:
        # --- Connect flow: link to existing user ---
        user_id = cached.get('user_id')
        try:
            django_user = DjangoUser.objects.get(id=user_id)
        except DjangoUser.DoesNotExist:
            return redirect(f"{frontend}/profile?twitter_error=user_not_found")

        TwitterAccount.objects.update_or_create(
            twitter_id=twitter_id,
            defaults={
                'user': django_user,
                'username': username,
                'name': name,
                'profile_picture_url': profile_pic,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expires_at': timezone.now() + timedelta(seconds=expires_in),
            },
        )
        return redirect(f"{frontend}/profile?twitter_connected=1")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def twitter_status(request):
    try:
        acc = request.user.twitter_account
        return Response({
            'connected': True,
            'username': acc.username,
            'name': acc.name,
            'profile_picture_url': acc.profile_picture_url,
        })
    except TwitterAccount.DoesNotExist:
        return Response({'connected': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def twitter_disconnect(request):
    try:
        request.user.twitter_account.delete()
    except TwitterAccount.DoesNotExist:
        pass
    return Response({'success': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def twitter_publish(request):
    """Publie un tweet (280 chars max)"""
    content = request.data.get('content', '').strip()
    if not content:
        return Response({'error': 'Contenu requis'}, status=status.HTTP_400_BAD_REQUEST)

    if len(content) > 280:
        content = content[:277] + '...'

    try:
        acc = request.user.twitter_account
    except TwitterAccount.DoesNotExist:
        return Response({'error': 'Twitter non connecté'}, status=status.HTTP_400_BAD_REQUEST)

    resp = requests.post(
        TWITTER_TWEET_URL,
        headers={
            'Authorization': f'Bearer {acc.access_token}',
            'Content-Type': 'application/json',
        },
        json={'text': content},
        timeout=15,
    )

    if resp.ok:
        tweet_id = resp.json()['data']['id']
        return Response({
            'success': True,
            'tweet_id': tweet_id,
            'tweet_url': f"https://twitter.com/i/web/status/{tweet_id}",
        })

    return Response({'error': resp.json()}, status=status.HTTP_400_BAD_REQUEST)
