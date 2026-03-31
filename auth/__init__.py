"""
Authentication module
Handles user authentication, JWT tokens, and password management
"""

from .api_key import is_auth_enabled, verify_api_key
from .dependencies import get_current_active_user, get_current_user, get_optional_user
from .security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    hash_password,
    verify_password,
    verify_token,
)
from .service import AuthService

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "get_password_hash",
    "get_current_user",
    "get_current_active_user",
    "get_optional_user",
    "AuthService",
    "verify_api_key",
    "is_auth_enabled",
]
