from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from .models import UserProfile


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Inscription d'un nouvel utilisateur"""
    username = request.data.get('username', '').strip()
    email = request.data.get('email', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'error': 'Nom d\'utilisateur et mot de passe requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if len(password) < 6:
        return Response(
            {'error': 'Le mot de passe doit contenir au moins 6 caractères'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {'error': 'Ce nom d\'utilisateur existe déjà'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if email and User.objects.filter(email=email).exists():
        return Response(
            {'error': 'Cette adresse email est déjà utilisée'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password
    )
    UserProfile.objects.create(user=user)

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
def login(request):
    """Connexion d'un utilisateur"""
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'error': 'Nom d\'utilisateur et mot de passe requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

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

    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'linkedin_connected': linkedin_connected,
        'linkedin_name': linkedin_name,
        'knowledge_base': _serialize_profile(user_profile),
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
