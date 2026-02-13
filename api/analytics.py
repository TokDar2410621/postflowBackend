from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Avg, Count
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone
from datetime import timedelta

from .models import PublishedPost


@api_view(['GET'])
def get_analytics_summary(request):
    """Récupère un résumé des statistiques"""
    if request.user.is_authenticated:
        posts = PublishedPost.objects.filter(user=request.user)
    else:
        posts = PublishedPost.objects.filter(user__isnull=True)

    # Stats globales
    totals = posts.aggregate(
        total_views=Sum('views'),
        total_likes=Sum('likes'),
        total_comments=Sum('comments'),
        total_shares=Sum('shares'),
        post_count=Count('id')
    )

    # Moyenne par post
    averages = posts.aggregate(
        avg_views=Avg('views'),
        avg_likes=Avg('likes'),
        avg_comments=Avg('comments'),
        avg_shares=Avg('shares')
    )

    # Stats des 7 derniers jours
    week_ago = timezone.now() - timedelta(days=7)
    recent_posts = posts.filter(published_at__gte=week_ago)
    recent_totals = recent_posts.aggregate(
        views=Sum('views'),
        likes=Sum('likes'),
        comments=Sum('comments'),
        shares=Sum('shares'),
        count=Count('id')
    )

    # Calcul du taux d'engagement moyen
    total_engagement = (totals['total_likes'] or 0) + (totals['total_comments'] or 0) + (totals['total_shares'] or 0)
    total_views = totals['total_views'] or 0
    engagement_rate = round((total_engagement / total_views * 100) if total_views > 0 else 0, 2)

    return Response({
        'totals': {
            'views': totals['total_views'] or 0,
            'likes': totals['total_likes'] or 0,
            'comments': totals['total_comments'] or 0,
            'shares': totals['total_shares'] or 0,
            'posts': totals['post_count'] or 0,
            'engagement_rate': engagement_rate
        },
        'averages': {
            'views': round(averages['avg_views'] or 0, 1),
            'likes': round(averages['avg_likes'] or 0, 1),
            'comments': round(averages['avg_comments'] or 0, 1),
            'shares': round(averages['avg_shares'] or 0, 1)
        },
        'last_7_days': {
            'views': recent_totals['views'] or 0,
            'likes': recent_totals['likes'] or 0,
            'comments': recent_totals['comments'] or 0,
            'shares': recent_totals['shares'] or 0,
            'posts': recent_totals['count'] or 0
        }
    })


@api_view(['GET'])
def get_analytics_chart(request):
    """Récupère les données pour les graphiques"""
    if request.user.is_authenticated:
        posts = PublishedPost.objects.filter(user=request.user)
    else:
        posts = PublishedPost.objects.filter(user__isnull=True)

    # Période (par défaut 30 jours)
    days = int(request.query_params.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)

    # Données par jour
    daily_data = posts.filter(published_at__gte=start_date).annotate(
        date=TruncDate('published_at')
    ).values('date').annotate(
        views=Sum('views'),
        likes=Sum('likes'),
        comments=Sum('comments'),
        shares=Sum('shares'),
        posts=Count('id')
    ).order_by('date')

    # Stats par ton
    tone_stats = posts.values('tone').annotate(
        count=Count('id'),
        total_views=Sum('views'),
        total_likes=Sum('likes'),
        avg_engagement=Avg('likes') + Avg('comments') + Avg('shares')
    ).order_by('-count')

    return Response({
        'daily': list(daily_data),
        'by_tone': list(tone_stats)
    })


@api_view(['GET'])
def get_top_posts(request):
    """Récupère les posts les plus performants"""
    if request.user.is_authenticated:
        posts = PublishedPost.objects.filter(user=request.user)
    else:
        posts = PublishedPost.objects.filter(user__isnull=True)

    # Critère de tri (défaut: engagement total)
    sort_by = request.query_params.get('sort', 'engagement')
    limit = min(int(request.query_params.get('limit', 10)), 50)

    if sort_by == 'views':
        posts = posts.order_by('-views')
    elif sort_by == 'likes':
        posts = posts.order_by('-likes')
    elif sort_by == 'comments':
        posts = posts.order_by('-comments')
    elif sort_by == 'shares':
        posts = posts.order_by('-shares')
    else:
        # Engagement total = likes + comments + shares
        from django.db.models import F
        posts = posts.annotate(
            engagement=F('likes') + F('comments') + F('shares')
        ).order_by('-engagement')

    top_posts = posts[:limit]

    result = []
    for post in top_posts:
        result.append({
            'id': post.id,
            'content': post.content[:200] + '...' if len(post.content) > 200 else post.content,
            'published_at': post.published_at.isoformat(),
            'views': post.views,
            'likes': post.likes,
            'comments': post.comments,
            'shares': post.shares,
            'engagement_rate': post.engagement_rate,
            'tone': post.tone,
            'has_images': post.has_images
        })

    return Response(result)


@api_view(['POST'])
def update_post_stats(request, pk):
    """Met à jour manuellement les stats d'un post (pour simulation/test)"""
    try:
        if request.user.is_authenticated:
            post = PublishedPost.objects.get(pk=pk, user=request.user)
        else:
            post = PublishedPost.objects.get(pk=pk, user__isnull=True)

        post.views = request.data.get('views', post.views)
        post.likes = request.data.get('likes', post.likes)
        post.comments = request.data.get('comments', post.comments)
        post.shares = request.data.get('shares', post.shares)
        post.stats_updated_at = timezone.now()
        post.save()

        return Response({
            'id': post.id,
            'views': post.views,
            'likes': post.likes,
            'comments': post.comments,
            'shares': post.shares,
            'engagement_rate': post.engagement_rate
        })
    except PublishedPost.DoesNotExist:
        return Response({'error': 'Post non trouvé'}, status=status.HTTP_404_NOT_FOUND)
