"""
Week 3: Simple API Key Authentication
Provides basic authentication for the API
"""

import os
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

# API key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key() -> Optional[str]:
    """Get API key from environment"""
    return os.getenv("API_KEY", None)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Verify the API key from request header

    Usage in endpoint:
        @app.get("/protected")
        async def protected_route(api_key: str = Depends(verify_api_key)):
            return {"message": "Access granted"}
    """

    # If no API key is configured in environment, allow access
    expected_api_key = get_api_key()
    if not expected_api_key:
        return "no-auth-required"  # Authentication disabled

    # If API key is configured, validate it
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing. Please provide X-API-Key header.",
        )

    if api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key"
        )

    return api_key


def is_auth_enabled() -> bool:
    """Check if authentication is enabled"""
    return get_api_key() is not None
