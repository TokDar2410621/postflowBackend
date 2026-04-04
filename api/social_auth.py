"""
Shared social auth utilities.
Finds existing users across all providers to prevent duplicate accounts.
"""
import logging

from django.contrib.auth.models import User

from .models import (
    LinkedInAccount, TwitterAccount, FacebookAccount, InstagramAccount,
    UserProfile, Subscription,
)

logger = logging.getLogger(__name__)


def find_user_by_social(provider: str, provider_id: str, email: str = '') -> User | None:
    """
    Find an existing Django user by:
    1. The same provider account (e.g. facebook_id)
    2. Any other linked social account with the same email
    3. Django user with the same email

    Returns the User if found, None otherwise.
    """
    # 1. Check if this provider account already exists
    account = None
    if provider == 'facebook':
        account = FacebookAccount.objects.filter(facebook_id=provider_id).select_related('user').first()
    elif provider == 'twitter':
        account = TwitterAccount.objects.filter(twitter_id=provider_id).select_related('user').first()
    elif provider == 'linkedin':
        account = LinkedInAccount.objects.filter(linkedin_id=provider_id).select_related('user').first()
    elif provider == 'instagram':
        account = InstagramAccount.objects.filter(instagram_id=provider_id).select_related('user').first()

    if account and account.user:
        return account.user

    # 2. Find by email across all users
    if email:
        user = User.objects.filter(email=email).first()
        if user:
            return user

    return None


def create_user(username_base: str, email: str = '', first_name: str = '', last_name: str = '') -> User:
    """
    Create a new Django user with unique username, plus UserProfile and Subscription.
    """
    username = username_base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{username_base}_{counter}'
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
    )
    UserProfile.objects.get_or_create(user=user)
    Subscription.objects.get_or_create(user=user, defaults={'plan': 'free', 'status': 'active'})

    return user


def find_or_create_user(provider: str, provider_id: str, email: str = '', name: str = '', fallback_username: str = '') -> User:
    """
    Find existing user or create a new one.
    Prevents duplicate accounts across providers.
    """
    user = find_user_by_social(provider, provider_id, email)
    if user:
        # Update email if user doesn't have one and we got one from this provider
        if email and not user.email:
            user.email = email
            user.save(update_fields=['email'])
        return user

    # Create new user
    username_base = fallback_username or name.replace(' ', '_').lower() or f'{provider}_{provider_id}'
    first_name = name.split(' ')[0] if name else ''
    last_name = ' '.join(name.split(' ')[1:]) if name and ' ' in name else ''

    return create_user(username_base, email, first_name, last_name)
