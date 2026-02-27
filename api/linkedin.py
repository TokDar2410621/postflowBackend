import json
import base64
import secrets
import requests
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import LinkedInAccount, PublishedPost


import logging

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
LINKEDIN_ASSETS_URL = "https://api.linkedin.com/v2/assets"
LINKEDIN_DOCUMENTS_URL = "https://api.linkedin.com/rest/documents"
LINKEDIN_POSTS_URL = "https://api.linkedin.com/rest/posts"


@api_view(['GET'])
def linkedin_auth(request):
    """Redirige vers la page d'autorisation LinkedIn (flow login uniquement)"""
    state_token = secrets.token_urlsafe(32)
    cache.set(f'oauth_state:{state_token}', {'action': 'login', 'user_id': ''}, timeout=600)

    params = {
        'response_type': 'code',
        'client_id': settings.LINKEDIN_CLIENT_ID,
        'redirect_uri': settings.LINKEDIN_REDIRECT_URI,
        'scope': 'openid profile email w_member_social',
        'state': state_token,
    }
    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"
    return redirect(auth_url)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def linkedin_init_auth(request):
    """Initie le flow OAuth LinkedIn connect (token via Authorization header, pas en URL)"""
    action = request.data.get('action', 'connect')
    user_id = str(request.user.id)

    state_token = secrets.token_urlsafe(32)
    cache.set(f'oauth_state:{state_token}', {'action': action, 'user_id': user_id}, timeout=600)

    params = {
        'response_type': 'code',
        'client_id': settings.LINKEDIN_CLIENT_ID,
        'redirect_uri': settings.LINKEDIN_REDIRECT_URI,
        'scope': 'openid profile email w_member_social',
        'state': state_token,
    }
    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"
    return Response({'auth_url': auth_url})


@api_view(['GET'])
def linkedin_callback(request):
    """Callback OAuth - échange le code contre un token"""
    code = request.GET.get('code')
    error = request.GET.get('error')
    raw_state = request.GET.get('state', '')

    # Valider le state token via le cache (one-time use)
    state_data = cache.get(f'oauth_state:{raw_state}')
    if not state_data:
        return redirect(f"{settings.FRONTEND_URL}?linkedin_error=invalid_state")
    cache.delete(f'oauth_state:{raw_state}')

    state = state_data.get('action', 'connect')
    state_user_id_str = state_data.get('user_id', '')
    state_user_id = int(state_user_id_str) if state_user_id_str else None

    if error:
        return redirect(f"{settings.FRONTEND_URL}?linkedin_error={error}")

    if not code:
        return redirect(f"{settings.FRONTEND_URL}?linkedin_error=no_code")

    # Échanger le code contre un access token
    token_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': settings.LINKEDIN_REDIRECT_URI,
        'client_id': settings.LINKEDIN_CLIENT_ID,
        'client_secret': settings.LINKEDIN_CLIENT_SECRET,
    }

    token_response = requests.post(LINKEDIN_TOKEN_URL, data=token_data)

    if token_response.status_code != 200:
        return redirect(f"{settings.FRONTEND_URL}?linkedin_error=token_failed")

    token_json = token_response.json()
    access_token = token_json['access_token']
    expires_in = token_json.get('expires_in', 3600)

    # Récupérer les infos utilisateur LinkedIn
    headers = {'Authorization': f'Bearer {access_token}'}
    userinfo_response = requests.get(LINKEDIN_USERINFO_URL, headers=headers)

    if userinfo_response.status_code != 200:
        return redirect(f"{settings.FRONTEND_URL}?linkedin_error=userinfo_failed")

    userinfo = userinfo_response.json()
    linkedin_id = userinfo.get('sub')
    name = userinfo.get('name', '')
    email = userinfo.get('email', '')

    expires_at = timezone.now() + timedelta(seconds=expires_in)

    if state == 'login':
        # --- Flow LOGIN : créer/trouver un User Django + JWT ---
        existing_account = LinkedInAccount.objects.filter(linkedin_id=linkedin_id).select_related('user').first()

        if existing_account and existing_account.user:
            # Utilisateur existant → mettre à jour le token LinkedIn
            user = existing_account.user
            existing_account.access_token = access_token
            existing_account.expires_at = expires_at
            existing_account.name = name
            existing_account.save()
        else:
            # Chercher un User existant avec le même email (fusion de comptes)
            user = None
            if email:
                user = User.objects.filter(email=email).first()

            if not user:
                # Aucun compte existant → créer un nouveau User
                username = name.replace(' ', '_').lower() if name else f'linkedin_{linkedin_id}'
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f'{base_username}_{counter}'
                    counter += 1

                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=name.split(' ')[0] if name else '',
                    last_name=' '.join(name.split(' ')[1:]) if name and ' ' in name else '',
                )

            # Lier le compte LinkedIn au User (existant ou nouveau)
            LinkedInAccount.objects.update_or_create(
                linkedin_id=linkedin_id,
                defaults={
                    'user': user,
                    'name': name,
                    'access_token': access_token,
                    'expires_at': expires_at,
                }
            )

        # Générer les JWT tokens
        refresh = RefreshToken.for_user(user)
        auth_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email or '',
            },
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }
        # Encoder en base64 URL-safe pour passer via redirect
        encoded = base64.urlsafe_b64encode(json.dumps(auth_data).encode()).decode()
        return redirect(f"{settings.FRONTEND_URL}?linkedin_auth={encoded}")

    else:
        # --- Flow CONNECT : lier le compte LinkedIn à l'utilisateur ---
        connect_user = None
        if state_user_id:
            try:
                connect_user = User.objects.get(pk=state_user_id)
            except User.DoesNotExist:
                pass

        LinkedInAccount.objects.update_or_create(
            linkedin_id=linkedin_id,
            defaults={
                'user': connect_user,
                'name': name,
                'access_token': access_token,
                'expires_at': expires_at,
            }
        )
        return redirect(f"{settings.FRONTEND_URL}?linkedin_connected=true&name={name}")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def linkedin_status(request):
    """Vérifie si un compte LinkedIn est connecté"""
    account = LinkedInAccount.objects.filter(user=request.user).first()

    if not account:
        return Response({'connected': False})

    if account.is_expired:
        return Response({
            'connected': False,
            'expired': True,
            'name': account.name
        })

    return Response({
        'connected': True,
        'name': account.name,
        'linkedin_id': account.linkedin_id
    })


def upload_image_to_linkedin(account, image_file):
    """Upload une image vers LinkedIn et retourne l'URN de l'asset"""
    headers = {
        'Authorization': f'Bearer {account.access_token}',
        'Content-Type': 'application/json',
        'X-Restli-Protocol-Version': '2.0.0',
    }

    # Étape 1: Enregistrer l'upload
    register_data = {
        'registerUploadRequest': {
            'recipes': ['urn:li:digitalmediaRecipe:feedshare-image'],
            'owner': f'urn:li:person:{account.linkedin_id}',
            'serviceRelationships': [
                {
                    'relationshipType': 'OWNER',
                    'identifier': 'urn:li:userGeneratedContent'
                }
            ]
        }
    }

    register_response = requests.post(
        f'{LINKEDIN_ASSETS_URL}?action=registerUpload',
        json=register_data,
        headers=headers
    )

    if register_response.status_code not in [200, 201]:
        raise Exception(f"Erreur enregistrement upload: {register_response.text}")

    register_result = register_response.json()
    upload_url = register_result['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset_urn = register_result['value']['asset']

    # Étape 2: Upload le fichier binaire
    image_content = image_file.read()
    upload_headers = {
        'Authorization': f'Bearer {account.access_token}',
    }

    upload_response = requests.put(upload_url, data=image_content, headers=upload_headers)

    if upload_response.status_code not in [200, 201]:
        raise Exception(f"Erreur upload image: {upload_response.text}")

    return asset_urn


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def linkedin_publish(request):
    """Publie un post sur LinkedIn avec images optionnelles"""
    content = request.data.get('content')
    images = request.FILES.getlist('images')

    if images:
        from .views import validate_uploaded_images
        img_error = validate_uploaded_images(images)
        if img_error:
            return Response({'error': img_error}, status=status.HTTP_400_BAD_REQUEST)

    if not content:
        return Response(
            {'error': 'Le contenu du post est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    account = LinkedInAccount.objects.filter(user=request.user).first()

    if not account:
        return Response(
            {'error': 'Aucun compte LinkedIn connecté'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    if account.is_expired:
        return Response(
            {'error': 'Le token LinkedIn a expiré, reconnectez-vous'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Upload des images si présentes
    image_urns = []
    for image in images[:5]:
        try:
            image_urn = upload_image_to_linkedin(account, image)
            image_urns.append(image_urn)
        except Exception as e:
            return Response(
                {'error': f'Erreur upload image: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # Créer le post via l'API LinkedIn (ugcPosts)
    headers = {
        'Authorization': f'Bearer {account.access_token}',
        'Content-Type': 'application/json',
        'X-Restli-Protocol-Version': '2.0.0',
    }

    # Format UGC Posts
    post_data = {
        'author': f'urn:li:person:{account.linkedin_id}',
        'lifecycleState': 'PUBLISHED',
        'specificContent': {
            'com.linkedin.ugc.ShareContent': {
                'shareCommentary': {
                    'text': content
                },
                'shareMediaCategory': 'NONE'
            }
        },
        'visibility': {
            'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
        }
    }

    # Ajouter les images si présentes
    if image_urns:
        media_list = []
        for asset_urn in image_urns:
            media_list.append({
                'status': 'READY',
                'media': asset_urn
            })

        post_data['specificContent']['com.linkedin.ugc.ShareContent']['shareMediaCategory'] = 'IMAGE'
        post_data['specificContent']['com.linkedin.ugc.ShareContent']['media'] = media_list

    response = requests.post(LINKEDIN_UGC_POSTS_URL, json=post_data, headers=headers)

    if response.status_code in [200, 201]:
        # Extraire l'ID du post LinkedIn
        response_data = response.json()
        linkedin_post_id = response_data.get('id', '')

        # Sauvegarder dans PublishedPost pour les analytics
        tone = request.data.get('tone', '')
        PublishedPost.objects.create(
            user=request.user,
            linkedin_post_id=linkedin_post_id,
            content=content,
            has_images=len(image_urns) > 0,
            tone=tone
        )

        return Response({
            'success': True,
            'message': 'Post publié avec succès sur LinkedIn!'
        })
    else:
        error_msg = response.json().get('message', 'Erreur inconnue')
        return Response(
            {'error': f'Erreur LinkedIn: {error_msg}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def linkedin_disconnect(request):
    """Déconnecte le compte LinkedIn"""
    LinkedInAccount.objects.filter(user=request.user).delete()
    return Response({'success': True, 'message': 'Compte LinkedIn déconnecté'})


# --- Stats LinkedIn ---

LINKEDIN_STATS_URL = "https://api.linkedin.com/rest/memberCreatorPostAnalytics"
LINKEDIN_API_VERSION = "202506"


def fetch_post_stats(account, linkedin_post_id):
    """Récupère les stats d'un post via l'API memberCreatorPostAnalytics.
    Retourne un dict {likes, comments, views, shares} ou None en cas d'erreur.
    Nécessite le scope r_member_postAnalytics."""
    from urllib.parse import quote

    if account.is_expired:
        return None

    encoded_urn = quote(linkedin_post_id, safe='')

    # Déterminer le type d'URN (share ou ugcPost)
    if 'share' in linkedin_post_id:
        entity_param = f"(share:{encoded_urn})"
    else:
        entity_param = f"(ugc:{encoded_urn})"

    headers = {
        'Authorization': f'Bearer {account.access_token}',
        'LinkedIn-Version': LINKEDIN_API_VERSION,
        'X-Restli-Protocol-Version': '2.0.0',
    }

    stats = {}

    # Récupérer chaque métrique via memberCreatorPostAnalytics
    for metric, key in [('REACTION', 'likes'), ('COMMENT', 'comments'),
                        ('IMPRESSION', 'views'), ('RESHARE', 'shares')]:
        try:
            resp = requests.get(
                f"{LINKEDIN_STATS_URL}?q=entity&entity={entity_param}&queryType={metric}&aggregation=TOTAL",
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get('elements', [])
                stats[key] = elements[0].get('count', 0) if elements else 0
            else:
                stats[key] = None
        except Exception:
            stats[key] = None

    # Si aucune métrique n'a fonctionné, retourner None
    if all(v is None for v in stats.values()):
        return None

    return stats


def update_all_post_stats():
    """Met à jour les stats de tous les posts publiés récents (< 90 jours).
    Retourne le nombre de posts mis à jour."""
    import time
    from datetime import timedelta as td

    cutoff = timezone.now() - td(days=90)
    posts = PublishedPost.objects.filter(
        linkedin_post_id__gt='',
        published_at__gte=cutoff
    ).select_related('user')

    updated_count = 0
    accounts_cache = {}

    for post in posts:
        # Récupérer le LinkedInAccount correspondant
        user_id = post.user_id
        if user_id not in accounts_cache:
            account = LinkedInAccount.objects.filter(user_id=user_id).first() if user_id else \
                      LinkedInAccount.objects.filter(user__isnull=True).first()
            accounts_cache[user_id] = account

        account = accounts_cache[user_id]
        if not account or account.is_expired:
            continue

        stats = fetch_post_stats(account, post.linkedin_post_id)
        if stats:
            update_fields = ['stats_updated_at']
            if stats.get('likes') is not None:
                post.likes = stats['likes']
                update_fields.append('likes')
            if stats.get('comments') is not None:
                post.comments = stats['comments']
                update_fields.append('comments')
            if stats.get('views') is not None:
                post.views = stats['views']
                update_fields.append('views')
            if stats.get('shares') is not None:
                post.shares = stats['shares']
                update_fields.append('shares')
            post.stats_updated_at = timezone.now()
            post.save(update_fields=update_fields)
            updated_count += 1

        # Rate limiting
        time.sleep(0.5)

    return updated_count


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refresh_stats(request):
    """Déclenche une MAJ immédiate des stats pour l'utilisateur courant"""
    import time

    account = LinkedInAccount.objects.filter(user=request.user).first()
    posts = PublishedPost.objects.filter(user=request.user, linkedin_post_id__gt='')

    if not account:
        return Response({'error': 'Aucun compte LinkedIn connecté'}, status=status.HTTP_401_UNAUTHORIZED)

    if account.is_expired:
        return Response({'error': 'Token LinkedIn expiré, reconnectez-vous'}, status=status.HTTP_401_UNAUTHORIZED)

    updated = 0
    for post in posts[:50]:  # Limiter à 50 posts max par refresh
        stats = fetch_post_stats(account, post.linkedin_post_id)
        if stats:
            update_fields = ['stats_updated_at']
            if stats.get('likes') is not None:
                post.likes = stats['likes']
                update_fields.append('likes')
            if stats.get('comments') is not None:
                post.comments = stats['comments']
                update_fields.append('comments')
            if stats.get('views') is not None:
                post.views = stats['views']
                update_fields.append('views')
            if stats.get('shares') is not None:
                post.shares = stats['shares']
                update_fields.append('shares')
            post.stats_updated_at = timezone.now()
            post.save(update_fields=update_fields)
            updated += 1
        time.sleep(0.3)

    return Response({
        'updated': updated,
        'message': f'{updated} post(s) mis à jour'
    })


# --- Publication de carousels (documents PDF) ---

def upload_document_to_linkedin(account, pdf_bytes):
    """Upload un PDF vers LinkedIn via l'API Documents et retourne le document URN."""
    headers = {
        'Authorization': f'Bearer {account.access_token}',
        'Content-Type': 'application/json',
        'LinkedIn-Version': LINKEDIN_API_VERSION,
    }

    # Étape 1: Initialiser l'upload
    init_data = {
        'initializeUploadRequest': {
            'owner': f'urn:li:person:{account.linkedin_id}',
        }
    }

    init_response = requests.post(
        f'{LINKEDIN_DOCUMENTS_URL}?action=initializeUpload',
        json=init_data,
        headers=headers,
        timeout=30,
    )

    if init_response.status_code not in [200, 201]:
        logger.error(f"Document init upload failed: {init_response.status_code} {init_response.text}")
        raise Exception(f"Erreur initialisation upload: {init_response.text}")

    init_result = init_response.json()
    upload_url = init_result['value']['uploadUrl']
    document_urn = init_result['value']['document']

    # Étape 2: Upload le PDF
    upload_headers = {
        'Authorization': f'Bearer {account.access_token}',
        'Content-Type': 'application/pdf',
    }

    upload_response = requests.put(
        upload_url,
        data=pdf_bytes,
        headers=upload_headers,
        timeout=60,
    )

    if upload_response.status_code not in [200, 201]:
        logger.error(f"Document upload failed: {upload_response.status_code} {upload_response.text}")
        raise Exception(f"Erreur upload document: {upload_response.text}")

    return document_urn


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def linkedin_publish_carousel(request):
    """Publie un carousel (document PDF) sur LinkedIn."""
    caption = request.data.get('caption', '')
    pdf_file = request.FILES.get('pdf')

    if not pdf_file:
        return Response(
            {'error': 'Le fichier PDF est requis'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Vérifier le type et la taille
    if pdf_file.content_type != 'application/pdf':
        return Response(
            {'error': 'Le fichier doit etre un PDF'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if pdf_file.size > 50 * 1024 * 1024:  # 50MB max LinkedIn
        return Response(
            {'error': 'Le PDF est trop volumineux (max 50MB)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account = LinkedInAccount.objects.filter(user=request.user).first()

    if not account:
        return Response(
            {'error': 'Aucun compte LinkedIn connecte'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if account.is_expired:
        return Response(
            {'error': 'Le token LinkedIn a expire, reconnectez-vous'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Upload du document
    try:
        pdf_bytes = pdf_file.read()
        document_urn = upload_document_to_linkedin(account, pdf_bytes)
    except Exception as e:
        logger.error(f"Carousel upload error: {e}")
        return Response(
            {'error': f'Erreur upload: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Créer le post avec le document via Posts API
    headers = {
        'Authorization': f'Bearer {account.access_token}',
        'Content-Type': 'application/json',
        'LinkedIn-Version': LINKEDIN_API_VERSION,
    }

    post_data = {
        'author': f'urn:li:person:{account.linkedin_id}',
        'commentary': caption,
        'visibility': 'PUBLIC',
        'distribution': {
            'feedDistribution': 'MAIN_FEED',
            'targetEntities': [],
            'thirdPartyDistributionChannels': [],
        },
        'content': {
            'media': {
                'id': document_urn,
                'title': caption[:100] if caption else 'Carousel',
            }
        },
        'lifecycleState': 'PUBLISHED',
    }

    response = requests.post(
        LINKEDIN_POSTS_URL,
        json=post_data,
        headers=headers,
        timeout=30,
    )

    if response.status_code in [200, 201]:
        # Extraire l'ID du post
        linkedin_post_id = response.headers.get('x-restli-id', '')

        PublishedPost.objects.create(
            user=request.user,
            linkedin_post_id=linkedin_post_id,
            content=caption,
            has_images=False,
            tone='',
        )

        return Response({
            'success': True,
            'message': 'Carousel publie avec succes sur LinkedIn!',
        })
    else:
        error_detail = response.text
        logger.error(f"LinkedIn post creation failed: {response.status_code} {error_detail}")
        return Response(
            {'error': f'Erreur LinkedIn: {error_detail}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
