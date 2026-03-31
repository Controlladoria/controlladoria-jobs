"""
FastAPI dependencies for authentication
Provides dependency injection for current user
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import OrgMembership, User, UserSession, get_db

from .security import verify_token

# HTTP Bearer token scheme
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Get the current authenticated user from JWT token

    Args:
        credentials: HTTP Bearer token credentials
        db: Database session

    Returns:
        User object if authenticated

    Raises:
        HTTPException: If token is invalid or user not found
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_token(token, token_type="access")

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if session is still active (supports token revocation via logout)
    session_id = payload.get("sid")
    if session_id:
        session = db.query(UserSession).filter_by(id=session_id, is_active=True).first()
        if not session or session.is_expired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked or expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Hydrate organization context: set role and active org from OrgMembership
    org_id = payload.get("org_id")
    if org_id is None and user.active_org_id:
        org_id = user.active_org_id

    if org_id:
        membership = db.query(OrgMembership).filter_by(
            user_id=user.id, organization_id=int(org_id), is_active=True
        ).first()
        if membership:
            user.role = membership.role  # Override role per active org
            user._active_org_id = int(org_id)
            user._active_membership = membership
        else:
            # User is not a member of this org — fall back to first available
            user._active_org_id = user.active_org_id
    else:
        user._active_org_id = None

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get the current active user

    Args:
        current_user: Current user from get_current_user

    Returns:
        User object if active

    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get the current admin user
    Requires user to be active AND have admin role

    Args:
        current_user: Current active user from get_current_active_user

    Returns:
        User object if admin

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    return current_user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Get the current user if authenticated, None otherwise
    Useful for endpoints that work with or without authentication

    Args:
        credentials: HTTP Bearer token credentials
        db: Database session

    Returns:
        User object if authenticated, None otherwise
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = verify_token(token, token_type="access")

    if payload is None:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    user = db.query(User).filter(User.id == int(user_id)).first()
    return user
