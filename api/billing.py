import logging
from datetime import datetime

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Subscription, UsageRecord

logger = logging.getLogger('api')

stripe.api_key = settings.STRIPE_SECRET_KEY


# ========== Utility functions ==========

def check_generation_limit(user):
    """
    Vérifie si l'utilisateur peut générer du contenu.
    Returns (can_generate, error_response)
    """
    if not user.is_authenticated:
        return True, None

    sub, _ = Subscription.objects.get_or_create(user=user)
    limits = settings.PLAN_LIMITS.get(sub.plan, settings.PLAN_LIMITS['free'])
    max_generations = limits['generations_per_month']

    if max_generations is None:  # unlimited
        return True, None

    now = timezone.now()
    usage, _ = UsageRecord.objects.get_or_create(
        user=user, year=now.year, month=now.month
    )

    if usage.generation_count >= max_generations:
        return False, Response({
            'error': f'Limite de {max_generations} générations/mois atteinte. Passez au plan supérieur.',
            'code': 'GENERATION_LIMIT_REACHED',
            'usage': {
                'current': usage.generation_count,
                'limit': max_generations,
            },
        }, status=status.HTTP_403_FORBIDDEN)

    return True, None


def increment_usage(user):
    """Incrémente le compteur de générations du mois."""
    if not user.is_authenticated:
        return
    now = timezone.now()
    usage, _ = UsageRecord.objects.get_or_create(
        user=user, year=now.year, month=now.month
    )
    usage.generation_count += 1
    usage.save(update_fields=['generation_count', 'updated_at'])


def get_plan_limits(user):
    """Retourne les limites du plan de l'utilisateur."""
    if not user.is_authenticated:
        return settings.PLAN_LIMITS['free']
    sub, _ = Subscription.objects.get_or_create(user=user)
    return settings.PLAN_LIMITS.get(sub.plan, settings.PLAN_LIMITS['free'])


# ========== API Endpoints ==========

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def billing_status(request):
    """Retourne le statut d'abonnement, usage et limites."""
    sub, _ = Subscription.objects.get_or_create(user=request.user)
    now = timezone.now()
    usage, _ = UsageRecord.objects.get_or_create(
        user=request.user, year=now.year, month=now.month
    )
    limits = settings.PLAN_LIMITS.get(sub.plan, settings.PLAN_LIMITS['free'])

    return Response({
        'plan': sub.plan,
        'status': sub.status,
        'is_active': sub.is_active,
        'cancel_at_period_end': sub.cancel_at_period_end,
        'current_period_end': sub.current_period_end.isoformat() if sub.current_period_end else None,
        'usage': {
            'generation_count': usage.generation_count,
            'generation_limit': limits['generations_per_month'],
        },
        'limits': {
            'themes_count': limits['themes_count'],
            'infographic_templates': limits['infographic_templates'],
            'social_accounts': limits['social_accounts'],
            'watermark': limits['watermark'],
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    """Crée une session Stripe Checkout pour l'abonnement."""
    plan = request.data.get('plan')

    price_map = {
        'pro': settings.STRIPE_PRICE_PRO_MONTHLY,
        'business': settings.STRIPE_PRICE_BUSINESS_MONTHLY,
    }
    price_id = price_map.get(plan)
    if not price_id:
        return Response({'error': 'Plan invalide'}, status=status.HTTP_400_BAD_REQUEST)

    sub, _ = Subscription.objects.get_or_create(user=request.user)

    # Créer ou récupérer le client Stripe
    if not sub.stripe_customer_id:
        customer = stripe.Customer.create(
            email=request.user.email,
            metadata={'user_id': str(request.user.id), 'username': request.user.username},
        )
        sub.stripe_customer_id = customer.id
        sub.save(update_fields=['stripe_customer_id'])

    frontend_url = settings.FRONTEND_URL.rstrip('/')

    session = stripe.checkout.Session.create(
        customer=sub.stripe_customer_id,
        mode='subscription',
        payment_method_types=['card'],
        line_items=[{'price': price_id, 'quantity': 1}],
        success_url=f'{frontend_url}/pricing?session_id={{CHECKOUT_SESSION_ID}}&success=1',
        cancel_url=f'{frontend_url}/pricing?canceled=1',
        metadata={'user_id': str(request.user.id), 'plan': plan},
        subscription_data={
            'metadata': {'user_id': str(request.user.id), 'plan': plan},
        },
    )

    return Response({'checkout_url': session.url})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_portal_session(request):
    """Crée une session Stripe Customer Portal."""
    sub, _ = Subscription.objects.get_or_create(user=request.user)

    if not sub.stripe_customer_id:
        return Response(
            {'error': 'Aucun abonnement Stripe trouvé'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    frontend_url = settings.FRONTEND_URL.rstrip('/')
    session = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f'{frontend_url}/profile',
    )

    return Response({'portal_url': session.url})


# ========== Webhook ==========

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def stripe_webhook(request):
    """Gère les événements webhook Stripe."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning(f"Stripe webhook verification failed: {e}")
        return HttpResponse(status=400)

    event_type = event['type']
    data_object = event['data']['object']

    if event_type == 'checkout.session.completed':
        _handle_checkout_completed(data_object)
    elif event_type == 'customer.subscription.updated':
        _handle_subscription_updated(data_object)
    elif event_type == 'customer.subscription.deleted':
        _handle_subscription_deleted(data_object)
    elif event_type == 'invoice.payment_failed':
        _handle_payment_failed(data_object)
    else:
        logger.info(f"Unhandled Stripe event: {event_type}")

    return HttpResponse(status=200)


def _handle_checkout_completed(session):
    """Après un checkout réussi, active l'abonnement."""
    user_id = session.get('metadata', {}).get('user_id')
    plan = session.get('metadata', {}).get('plan', 'pro')
    stripe_subscription_id = session.get('subscription')
    stripe_customer_id = session.get('customer')

    if not user_id:
        logger.error("checkout.session.completed missing user_id in metadata")
        return

    try:
        sub = Subscription.objects.get(user_id=int(user_id))
    except Subscription.DoesNotExist:
        sub = Subscription(user_id=int(user_id))

    sub.plan = plan
    sub.status = 'active'
    sub.stripe_customer_id = stripe_customer_id
    sub.stripe_subscription_id = stripe_subscription_id

    if stripe_subscription_id:
        try:
            stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
            sub.current_period_start = datetime.fromtimestamp(
                stripe_sub.current_period_start, tz=timezone.utc
            )
            sub.current_period_end = datetime.fromtimestamp(
                stripe_sub.current_period_end, tz=timezone.utc
            )
        except Exception as e:
            logger.error(f"Error fetching subscription details: {e}")

    sub.save()
    logger.info(f"Checkout completed: user {user_id} -> plan {plan}")


def _handle_subscription_updated(stripe_sub):
    """Met à jour le plan/statut suite à un changement."""
    try:
        sub = Subscription.objects.get(stripe_subscription_id=stripe_sub['id'])
    except Subscription.DoesNotExist:
        logger.warning(f"subscription.updated: no local sub for {stripe_sub['id']}")
        return

    status_map = {
        'active': 'active',
        'past_due': 'past_due',
        'canceled': 'canceled',
        'incomplete': 'incomplete',
        'trialing': 'active',
        'unpaid': 'past_due',
    }
    sub.status = status_map.get(stripe_sub['status'], 'active')
    sub.cancel_at_period_end = stripe_sub.get('cancel_at_period_end', False)

    sub.current_period_start = datetime.fromtimestamp(
        stripe_sub['current_period_start'], tz=timezone.utc
    )
    sub.current_period_end = datetime.fromtimestamp(
        stripe_sub['current_period_end'], tz=timezone.utc
    )

    # Déterminer le plan en fonction du price_id
    items = stripe_sub.get('items', {}).get('data', [])
    if items:
        price_id = items[0].get('price', {}).get('id', '')
        if price_id == settings.STRIPE_PRICE_PRO_MONTHLY:
            sub.plan = 'pro'
        elif price_id == settings.STRIPE_PRICE_BUSINESS_MONTHLY:
            sub.plan = 'business'

    sub.save()
    logger.info(f"Subscription updated: user {sub.user_id} -> {sub.plan} ({sub.status})")


def _handle_subscription_deleted(stripe_sub):
    """Abonnement annulé — downgrade vers free."""
    try:
        sub = Subscription.objects.get(stripe_subscription_id=stripe_sub['id'])
    except Subscription.DoesNotExist:
        return

    sub.plan = 'free'
    sub.status = 'canceled'
    sub.stripe_subscription_id = ''
    sub.cancel_at_period_end = False
    sub.current_period_start = None
    sub.current_period_end = None
    sub.save()
    logger.info(f"Subscription deleted: user {sub.user_id} downgraded to free")


def _handle_payment_failed(invoice):
    """Paiement échoué — marque past_due."""
    stripe_sub_id = invoice.get('subscription')
    if not stripe_sub_id:
        return

    try:
        sub = Subscription.objects.get(stripe_subscription_id=stripe_sub_id)
        sub.status = 'past_due'
        sub.save(update_fields=['status'])
        logger.info(f"Payment failed: user {sub.user_id} marked past_due")
    except Subscription.DoesNotExist:
        pass
