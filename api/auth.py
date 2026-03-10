import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from .models import UserProfile, GeneratedPost, Subscription, UsageRecord

logger = logging.getLogger('api')


class LoginRateThrottle(AnonRateThrottle):
    scope = 'login'


class RegisterRateThrottle(AnonRateThrottle):
    scope = 'register'


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([RegisterRateThrottle])
def register(request):
    """Inscription d'un nouvel utilisateur"""
    username = request.data.get('username', '').strip()
    email = request.data.get('email', '').strip()
    password = request.data.get('password', '')

    if not username or not password or not email:
        return Response(
            {'error': 'Nom d\'utilisateur, email et mot de passe requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validation du mot de passe via les validateurs Django
    try:
        validate_password(password)
    except DjangoValidationError as e:
        return Response(
            {'error': e.messages[0]},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Message générique pour éviter l'énumération d'utilisateurs
    if User.objects.filter(username=username).exists() or (email and User.objects.filter(email=email).exists()):
        return Response(
            {'error': 'Impossible de créer ce compte. Veuillez vérifier vos informations.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password
    )
    UserProfile.objects.create(user=user)
    Subscription.objects.create(user=user, plan='free', status='active')

    # Générer les tokens JWT
    refresh = RefreshToken.for_user(user)

    return Response({
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        },
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login(request):
    """Connexion d'un utilisateur (par username ou email)"""
    identifier = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not identifier or not password:
        return Response(
            {'error': 'Identifiant et mot de passe requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Si l'identifiant contient un @, chercher le username correspondant à cet email
    if '@' in identifier:
        try:
            user_obj = User.objects.get(email=identifier)
            username = user_obj.username
        except User.DoesNotExist:
            username = identifier  # Laisse échouer normalement
    else:
        username = identifier

    user = authenticate(username=username, password=password)

    if not user:
        return Response(
            {'error': 'Identifiants invalides'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Générer les tokens JWT
    refresh = RefreshToken.for_user(user)

    return Response({
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        },
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
    })


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def profile(request):
    """Récupère ou met à jour le profil de l'utilisateur connecté"""
    user = request.user
    user_profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == 'PUT':
        kb = request.data.get('knowledge_base', {})
        fields = ['role', 'industry', 'expertise', 'target_audience',
                  'writing_style', 'bio', 'example_posts', 'additional_context']
        for field in fields:
            if field in kb:
                setattr(user_profile, field, kb[field])
        user_profile.save()
        return Response({'message': 'Profil mis à jour avec succès', 'knowledge_base': _serialize_profile(user_profile)})

    # GET
    linkedin_connected = hasattr(user, 'linkedin_account') and user.linkedin_account is not None
    linkedin_name = user.linkedin_account.name if linkedin_connected else None

    # Subscription info
    sub, _ = Subscription.objects.get_or_create(user=user)
    now = timezone.now()
    usage, _ = UsageRecord.objects.get_or_create(user=user, year=now.year, month=now.month)
    plan_limits = settings.PLAN_LIMITS.get(sub.plan, settings.PLAN_LIMITS['free'])

    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'linkedin_connected': linkedin_connected,
        'linkedin_name': linkedin_name,
        'knowledge_base': _serialize_profile(user_profile),
        'subscription': {
            'plan': sub.plan,
            'status': sub.status,
            'is_active': sub.is_active,
            'cancel_at_period_end': sub.cancel_at_period_end,
            'current_period_end': sub.current_period_end.isoformat() if sub.current_period_end else None,
        },
        'usage': {
            'generation_count': usage.generation_count,
            'generation_limit': plan_limits['generations_per_month'],
        },
    })


def _serialize_profile(profile):
    return {
        'role': profile.role,
        'industry': profile.industry,
        'expertise': profile.expertise,
        'target_audience': profile.target_audience,
        'writing_style': profile.writing_style,
        'bio': profile.bio,
        'example_posts': profile.example_posts,
        'additional_context': profile.additional_context,
        'updated_at': profile.updated_at.isoformat(),
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """Déconnexion - invalide le refresh token"""
    try:
        refresh_token = request.data.get('refresh')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        return Response({'success': True, 'message': 'Déconnexion réussie'})
    except Exception:
        return Response({'success': True, 'message': 'Déconnexion réussie'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def claim_session(request):
    """Rattache les posts anonymes (session_key) au compte de l'utilisateur connecté"""
    session_key = request.data.get('session_key', '').strip()
    if not session_key or len(session_key) > 64:
        return Response({'claimed': 0})

    claimed = GeneratedPost.objects.filter(
        session_key=session_key, user__isnull=True
    ).update(user=request.user, session_key='')

    return Response({'claimed': claimed})


class PasswordResetThrottle(AnonRateThrottle):
    scope = 'password_reset'


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([PasswordResetThrottle])
def password_reset_request(request):
    """Envoie un email de réinitialisation de mot de passe"""
    email = request.data.get('email', '').strip().lower()

    # Toujours répondre 200 pour ne pas révéler si l'email existe
    success_msg = {'message': 'Si un compte existe avec cet email, un lien de réinitialisation a été envoyé.'}

    if not email:
        return Response(success_msg)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(success_msg)

    # Générer le token et le uid encodé
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    frontend_url = settings.FRONTEND_URL.rstrip('/')
    reset_link = f"{frontend_url}/reset-password?uid={uid}&token={token}"

    try:
        send_mail(
            subject='PostFlow - Réinitialisation de votre mot de passe',
            message=f'Bonjour {user.username},\n\n'
                    f'Vous avez demandé la réinitialisation de votre mot de passe.\n\n'
                    f'Cliquez sur ce lien pour définir un nouveau mot de passe :\n'
                    f'{reset_link}\n\n'
                    f'Ce lien expire dans 24 heures.\n\n'
                    f'Si vous n\'avez pas demandé cette réinitialisation, ignorez cet email.\n\n'
                    f'L\'équipe PostFlow',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Erreur envoi email reset: {e}")
        return Response(
            {'error': 'Erreur lors de l\'envoi de l\'email. Réessayez plus tard.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(success_msg)


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """Confirme la réinitialisation du mot de passe avec uid + token"""
    uid = request.data.get('uid', '')
    token = request.data.get('token', '')
    new_password = request.data.get('password', '')

    if not uid or not token or not new_password:
        return Response(
            {'error': 'Données manquantes'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Décoder le uid
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response(
            {'error': 'Lien de réinitialisation invalide'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Vérifier le token
    if not default_token_generator.check_token(user, token):
        return Response(
            {'error': 'Lien expiré ou déjà utilisé'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Valider le nouveau mot de passe
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as e:
        return Response(
            {'error': e.messages[0]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Changer le mot de passe
    user.set_password(new_password)
    user.save()

    return Response({'message': 'Mot de passe réinitialisé avec succès'})
