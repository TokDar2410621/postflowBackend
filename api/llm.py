"""
Multi-model text generation router.
Routes generation requests to the appropriate AI provider based on model ID.
"""
import requests
from django.conf import settings


MODELS = {
    'mistral': {
        'label': 'Mistral 7B',
        'plans': ['free', 'pro', 'business'],
    },
    'claude': {
        'label': 'Claude Sonnet 4',
        'plans': ['pro', 'business'],
    },
    'gemini': {
        'label': 'Gemini 2.5 Flash',
        'plans': ['pro', 'business'],
    },
    'gpt4o': {
        'label': 'GPT-4o',
        'plans': ['pro', 'business'],
    },
}

DEFAULT_MODEL_FREE = 'mistral'
DEFAULT_MODEL_PAID = 'claude'


def get_user_plan(user):
    """Get the user's subscription plan."""
    if not user or not user.is_authenticated:
        return 'free'
    from .models import Subscription
    try:
        sub = Subscription.objects.get(user=user)
        if sub.is_active:
            return sub.plan
    except Subscription.DoesNotExist:
        pass
    return 'free'


def validate_model_access(model_id, user_plan):
    """Returns (is_allowed, error_message)."""
    if model_id not in MODELS:
        return False, f"Modele inconnu: {model_id}"
    if user_plan not in MODELS[model_id]['plans']:
        return False, "Ce modele necessite un abonnement Pro ou Business."
    return True, None


def resolve_model(requested_model, user_plan):
    """Determine which model to use based on request and plan."""
    if not requested_model:
        return DEFAULT_MODEL_PAID if user_plan in ('pro', 'business') else DEFAULT_MODEL_FREE
    return requested_model


def generate_text(model_id, system_prompt, user_message, max_tokens=1024):
    """Route text generation to the appropriate provider."""
    if model_id == 'claude':
        return _generate_claude(system_prompt, user_message, max_tokens)
    elif model_id == 'gemini':
        return _generate_gemini(system_prompt, user_message, max_tokens)
    elif model_id == 'gpt4o':
        return _generate_openai(system_prompt, user_message, max_tokens)
    elif model_id == 'mistral':
        return _generate_mistral(system_prompt, user_message, max_tokens)
    else:
        raise ValueError(f"Modele inconnu: {model_id}")


def _generate_claude(system_prompt, user_message, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _generate_gemini(system_prompt, user_message, max_tokens):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[user_message],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text


def _generate_openai(system_prompt, user_message, max_tokens):
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


def _generate_mistral(system_prompt, user_message, max_tokens):
    HF_API_URL = "https://router.huggingface.co/hf-inference/models/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {"Authorization": f"Bearer {settings.HF_TOKEN}"}

    payload = {
        "inputs": f"<s>[INST] {system_prompt}\n\n{user_message} [/INST]",
        "parameters": {
            "max_new_tokens": max_tokens,
            "return_full_text": False,
        },
    }
    response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=90)

    if response.status_code == 429:
        raise Exception("Limite de requetes HuggingFace atteinte, reessayez plus tard.")
    if response.status_code == 503:
        raise Exception("Le modele est en cours de chargement, reessayez dans quelques secondes.")

    response.raise_for_status()
    result = response.json()

    if isinstance(result, list) and len(result) > 0:
        return result[0].get('generated_text', '')
    raise Exception("Reponse inattendue du modele Mistral")
