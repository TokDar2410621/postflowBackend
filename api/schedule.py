import base64
import io
import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ScheduledPost, LinkedInAccount
from .linkedin import upload_image_to_linkedin, LINKEDIN_UGC_POSTS_URL
import requests

logger = logging.getLogger(__name__)


@api_view(['GET'])
def list_scheduled_posts(request):
    """Liste les posts programmés de l'utilisateur"""
    if request.user.is_authenticated:
        posts = ScheduledPost.objects.filter(user=request.user)
    else:
        posts = ScheduledPost.objects.filter(user__isnull=True)

    date_range = request.query_params.get('date_range')
    if date_range == '7':
        posts = posts.filter(scheduled_at__gte=timezone.now() - timedelta(days=7))
    elif date_range == '30':
        posts = posts.filter(scheduled_at__gte=timezone.now() - timedelta(days=30))

    search = request.query_params.get('search')
    if search:
        posts = posts.filter(content__icontains=search)

    data = [{
        'id': post.id,
        'content': post.content,
        'scheduled_at': post.scheduled_at.isoformat(),
        'status': post.status,
        'error_message': post.error_message,
        'published_at': post.published_at.isoformat() if post.published_at else None,
        'created_at': post.created_at.isoformat(),
        'has_images': bool(post.images_data),
        'images_count': len(post.images_data) if post.images_data else 0,
    } for post in posts]

    return Response(data)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def schedule_post(request):
    """Programmer un post pour publication ultérieure (avec images optionnelles)"""
    content = request.data.get('content')
    scheduled_at_str = request.data.get('scheduled_at')
    images = request.FILES.getlist('images')

    if not content:
        return Response(
            {'error': 'Le contenu du post est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not scheduled_at_str:
        return Response(
            {'error': 'La date de programmation est requise'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_str.replace('Z', '+00:00'))
        if timezone.is_naive(scheduled_at):
            scheduled_at = timezone.make_aware(scheduled_at)
    except ValueError:
        return Response(
            {'error': 'Format de date invalide'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if scheduled_at <= timezone.now():
        return Response(
            {'error': 'La date de programmation doit être dans le futur'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Encoder les images en base64 pour le stockage
    images_data = []
    for img in images[:5]:  # Max 5 images
        img_bytes = img.read()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        mime_type = getattr(img, 'content_type', 'image/jpeg')
        images_data.append({'data': img_b64, 'mime_type': mime_type})

    post = ScheduledPost.objects.create(
        user=request.user if request.user.is_authenticated else None,
        content=content,
        scheduled_at=scheduled_at,
        images_data=images_data,
        status='pending'
    )

    return Response({
        'id': post.id,
        'content': post.content,
        'scheduled_at': post.scheduled_at.isoformat(),
        'status': post.status,
        'has_images': len(images_data) > 0,
        'message': 'Post programmé avec succès'
    }, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def cancel_scheduled_post(request, pk):
    """Annuler un post programmé"""
    try:
        if request.user.is_authenticated:
            post = ScheduledPost.objects.get(pk=pk, user=request.user)
        else:
            post = ScheduledPost.objects.get(pk=pk, user__isnull=True)
    except ScheduledPost.DoesNotExist:
        return Response(
            {'error': 'Post programmé non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )

    if post.status != 'pending':
        return Response(
            {'error': 'Ce post ne peut pas être annulé'},
            status=status.HTTP_400_BAD_REQUEST
        )

    post.status = 'cancelled'
    post.save()

    return Response({'success': True, 'message': 'Post programmé annulé'})


@api_view(['PUT'])
def update_scheduled_post(request, pk):
    """Modifier le contenu et/ou la date d'un post programmé"""
    try:
        if request.user.is_authenticated:
            post = ScheduledPost.objects.get(pk=pk, user=request.user)
        else:
            post = ScheduledPost.objects.get(pk=pk, user__isnull=True)
    except ScheduledPost.DoesNotExist:
        return Response(
            {'error': 'Post programmé non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )

    if post.status != 'pending':
        return Response(
            {'error': 'Seuls les posts en attente peuvent être modifiés'},
            status=status.HTTP_400_BAD_REQUEST
        )

    content = request.data.get('content')
    scheduled_at_str = request.data.get('scheduled_at')

    if content is not None:
        if not content.strip():
            return Response(
                {'error': 'Le contenu ne peut pas être vide'},
                status=status.HTTP_400_BAD_REQUEST
            )
        post.content = content

    if scheduled_at_str is not None:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace('Z', '+00:00'))
            if timezone.is_naive(scheduled_at):
                scheduled_at = timezone.make_aware(scheduled_at)
        except ValueError:
            return Response(
                {'error': 'Format de date invalide'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if scheduled_at <= timezone.now():
            return Response(
                {'error': 'La date de programmation doit être dans le futur'},
                status=status.HTTP_400_BAD_REQUEST
            )
        post.scheduled_at = scheduled_at

    post.save()

    return Response({
        'id': post.id,
        'content': post.content,
        'scheduled_at': post.scheduled_at.isoformat(),
        'status': post.status,
        'message': 'Post modifié avec succès'
    })


def publish_scheduled_posts():
    """Publish scheduled posts whose time has arrived.

    Uses select_for_update(skip_locked=True) to prevent race conditions
    when multiple workers run this job simultaneously.
    """
    now = timezone.now()
    published_count = 0

    # Process one post at a time with row-level locking
    while True:
        with transaction.atomic():
            post = (
                ScheduledPost.objects
                .select_for_update(skip_locked=True)
                .filter(status='pending', scheduled_at__lte=now)
                .first()
            )

            if post is None:
                break

            try:
                # Find user's LinkedIn account
                if post.user:
                    account = LinkedInAccount.objects.filter(user=post.user).first()
                else:
                    account = LinkedInAccount.objects.filter(user__isnull=True).first()

                if not account:
                    post.status = 'failed'
                    post.error_message = 'Aucun compte LinkedIn connecté'
                    post.save()
                    logger.warning(f'Scheduled post {post.id}: no LinkedIn account')
                    continue

                if account.is_expired:
                    post.status = 'failed'
                    post.error_message = 'Token LinkedIn expiré'
                    post.save()
                    logger.warning(f'Scheduled post {post.id}: token expired')
                    continue

                # Upload images if any
                image_urns = []
                if post.images_data:
                    for img_info in post.images_data:
                        try:
                            img_bytes = base64.b64decode(img_info['data'])
                            img_file = io.BytesIO(img_bytes)
                            img_file.content_type = img_info.get('mime_type', 'image/jpeg')
                            image_urn = upload_image_to_linkedin(account, img_file)
                            image_urns.append(image_urn)
                        except Exception as e:
                            logger.warning(f'Scheduled post {post.id}: image upload failed: {e}')

                # Publish to LinkedIn
                headers = {
                    'Authorization': f'Bearer {account.access_token}',
                    'Content-Type': 'application/json',
                    'X-Restli-Protocol-Version': '2.0.0',
                }

                post_data = {
                    'author': f'urn:li:person:{account.linkedin_id}',
                    'lifecycleState': 'PUBLISHED',
                    'specificContent': {
                        'com.linkedin.ugc.ShareContent': {
                            'shareCommentary': {
                                'text': post.content
                            },
                            'shareMediaCategory': 'IMAGE' if image_urns else 'NONE'
                        }
                    },
                    'visibility': {
                        'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
                    }
                }

                # Attach images if uploaded
                if image_urns:
                    post_data['specificContent']['com.linkedin.ugc.ShareContent']['media'] = [
                        {'status': 'READY', 'media': urn} for urn in image_urns
                    ]

                response = requests.post(LINKEDIN_UGC_POSTS_URL, json=post_data, headers=headers)

                if response.status_code in [200, 201]:
                    post.status = 'published'
                    post.published_at = timezone.now()
                    post.save()
                    published_count += 1
                    logger.info(f'Scheduled post {post.id} published successfully')
                else:
                    error_msg = response.json().get('message', 'Unknown error')
                    post.status = 'failed'
                    post.error_message = f'Erreur LinkedIn: {error_msg}'
                    post.save()
                    logger.error(f'Scheduled post {post.id} failed: {error_msg}')

            except Exception as e:
                post.status = 'failed'
                post.error_message = str(e)
                post.save()
                logger.exception(f'Scheduled post {post.id} exception: {e}')

    if published_count > 0:
        logger.info(f'publish_scheduled_posts: {published_count} published')
    return published_count
