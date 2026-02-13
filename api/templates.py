from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import PromptTemplate


@api_view(['GET'])
def list_templates(request):
    """Liste les templates de l'utilisateur"""
    if request.user.is_authenticated:
        templates = PromptTemplate.objects.filter(user=request.user)
    else:
        templates = PromptTemplate.objects.filter(user__isnull=True)

    data = [{
        'id': t.id,
        'name': t.name,
        'description': t.description,
        'default_tone': t.default_tone,
        'prompt_prefix': t.prompt_prefix,
        'prompt_suffix': t.prompt_suffix,
        'is_default': t.is_default,
        'created_at': t.created_at.isoformat(),
        'updated_at': t.updated_at.isoformat(),
    } for t in templates]

    return Response(data)


@api_view(['POST'])
def create_template(request):
    """Crée un nouveau template"""
    name = request.data.get('name', '').strip()
    description = request.data.get('description', '')
    default_tone = request.data.get('default_tone', 'professionnel')
    prompt_prefix = request.data.get('prompt_prefix', '')
    prompt_suffix = request.data.get('prompt_suffix', '')
    is_default = request.data.get('is_default', False)

    if not name:
        return Response(
            {'error': 'Le nom du template est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Valider le tone
    valid_tones = ['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique']
    if default_tone not in valid_tones:
        default_tone = 'professionnel'

    user = request.user if request.user.is_authenticated else None

    # Si c'est un template par défaut, désactiver les autres
    if is_default:
        if user:
            PromptTemplate.objects.filter(user=user, is_default=True).update(is_default=False)
        else:
            PromptTemplate.objects.filter(user__isnull=True, is_default=True).update(is_default=False)

    template = PromptTemplate.objects.create(
        user=user,
        name=name,
        description=description,
        default_tone=default_tone,
        prompt_prefix=prompt_prefix,
        prompt_suffix=prompt_suffix,
        is_default=is_default,
    )

    return Response({
        'id': template.id,
        'name': template.name,
        'description': template.description,
        'default_tone': template.default_tone,
        'prompt_prefix': template.prompt_prefix,
        'prompt_suffix': template.prompt_suffix,
        'is_default': template.is_default,
        'created_at': template.created_at.isoformat(),
        'updated_at': template.updated_at.isoformat(),
    }, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
def update_template(request, pk):
    """Met à jour un template"""
    try:
        if request.user.is_authenticated:
            template = PromptTemplate.objects.get(pk=pk, user=request.user)
        else:
            template = PromptTemplate.objects.get(pk=pk, user__isnull=True)
    except PromptTemplate.DoesNotExist:
        return Response(
            {'error': 'Template non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )

    name = request.data.get('name', template.name).strip()
    if not name:
        return Response(
            {'error': 'Le nom du template est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    template.name = name
    template.description = request.data.get('description', template.description)
    template.default_tone = request.data.get('default_tone', template.default_tone)
    template.prompt_prefix = request.data.get('prompt_prefix', template.prompt_prefix)
    template.prompt_suffix = request.data.get('prompt_suffix', template.prompt_suffix)

    is_default = request.data.get('is_default', template.is_default)
    if is_default and not template.is_default:
        # Désactiver les autres templates par défaut
        user = request.user if request.user.is_authenticated else None
        if user:
            PromptTemplate.objects.filter(user=user, is_default=True).update(is_default=False)
        else:
            PromptTemplate.objects.filter(user__isnull=True, is_default=True).update(is_default=False)
    template.is_default = is_default

    template.save()

    return Response({
        'id': template.id,
        'name': template.name,
        'description': template.description,
        'default_tone': template.default_tone,
        'prompt_prefix': template.prompt_prefix,
        'prompt_suffix': template.prompt_suffix,
        'is_default': template.is_default,
        'created_at': template.created_at.isoformat(),
        'updated_at': template.updated_at.isoformat(),
    })


@api_view(['DELETE'])
def delete_template(request, pk):
    """Supprime un template"""
    try:
        if request.user.is_authenticated:
            template = PromptTemplate.objects.get(pk=pk, user=request.user)
        else:
            template = PromptTemplate.objects.get(pk=pk, user__isnull=True)
    except PromptTemplate.DoesNotExist:
        return Response(
            {'error': 'Template non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )

    template.delete()
    return Response({'success': True, 'message': 'Template supprimé'})
