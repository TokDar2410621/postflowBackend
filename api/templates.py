from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PromptTemplate


def _template_to_dict(t):
    return {
        'id': t.id,
        'name': t.name,
        'description': t.description,
        'default_tone': t.default_tone,
        'prompt_prefix': t.prompt_prefix,
        'prompt_suffix': t.prompt_suffix,
        'is_default': t.is_default,
        'is_global': t.is_global,
        'created_at': t.created_at.isoformat(),
        'updated_at': t.updated_at.isoformat(),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_templates(request):
    """Liste les templates de l'utilisateur + les templates globaux"""
    templates = PromptTemplate.objects.filter(
        Q(user=request.user) | Q(is_global=True)
    ).distinct()

    return Response([_template_to_dict(t) for t in templates])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
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

    # Si c'est un template par défaut, désactiver les autres
    if is_default:
        PromptTemplate.objects.filter(user=request.user, is_default=True).update(is_default=False)

    template = PromptTemplate.objects.create(
        user=request.user,
        name=name,
        description=description,
        default_tone=default_tone,
        prompt_prefix=prompt_prefix,
        prompt_suffix=prompt_suffix,
        is_default=is_default,
    )

    return Response(_template_to_dict(template), status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_template(request, pk):
    """Met à jour un template (uniquement les templates personnels)"""
    try:
        template = PromptTemplate.objects.get(pk=pk, user=request.user, is_global=False)
    except PromptTemplate.DoesNotExist:
        return Response(
            {'error': 'Template non trouvé ou non modifiable'},
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
        PromptTemplate.objects.filter(user=request.user, is_default=True).update(is_default=False)
    template.is_default = is_default

    template.save()

    return Response(_template_to_dict(template))


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_template(request, pk):
    """Supprime un template (uniquement les templates personnels)"""
    try:
        template = PromptTemplate.objects.get(pk=pk, user=request.user, is_global=False)
    except PromptTemplate.DoesNotExist:
        return Response(
            {'error': 'Template non trouvé ou non supprimable'},
            status=status.HTTP_404_NOT_FOUND
        )

    template.delete()
    return Response({'success': True, 'message': 'Template supprimé'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def duplicate_template(request, pk):
    """Duplique un template (global ou personnel) en tant que template personnel"""
    try:
        template = PromptTemplate.objects.get(
            Q(pk=pk) & (Q(user=request.user) | Q(is_global=True))
        )
    except PromptTemplate.DoesNotExist:
        return Response(
            {'error': 'Template non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )

    new_template = PromptTemplate.objects.create(
        user=request.user,
        name=f"{template.name} (copie)",
        description=template.description,
        default_tone=template.default_tone,
        prompt_prefix=template.prompt_prefix,
        prompt_suffix=template.prompt_suffix,
        is_default=False,
        is_global=False,
    )

    return Response(_template_to_dict(new_template), status=status.HTTP_201_CREATED)
