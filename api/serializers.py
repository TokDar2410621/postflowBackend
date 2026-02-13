from rest_framework import serializers
from .models import GeneratedPost


class GeneratePostSerializer(serializers.Serializer):
    summary = serializers.CharField(required=False, allow_blank=True, default='')
    tone = serializers.ChoiceField(
        choices=['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique'],
        default='professionnel'
    )


class GeneratedPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedPost
        fields = ['id', 'summary', 'tone', 'generated_content', 'created_at']
        read_only_fields = ['id', 'generated_content', 'created_at']
