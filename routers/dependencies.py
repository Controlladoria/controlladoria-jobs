"""
Shared dependencies for routers
Multi-tenant isolation and common utilities
"""

from typing import List
from fastapi import Depends
from sqlalchemy.orm import Session

from auth.dependencies import get_current_active_user
from auth.permissions import get_accessible_user_ids
from database import User, get_db


def get_tenant_user_ids(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> List[int]:
    """
    Get list of user IDs accessible to current user (tenant isolation)

    Returns:
        List of user IDs in current user's tenant
        - For regular users: [their own ID]
        - For team members: [their ID + parent's ID]
        - For owners/admins: [their ID + all invited users]

    Use this in ALL queries that access user data to enforce multi-tenant isolation
    """
    return get_accessible_user_ids(current_user, db)


def require_tenant_access(
    resource_user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> bool:
    """
    Check if current user has access to a resource owned by resource_user_id

    Raises HTTPException if access denied
    """
    from fastapi import HTTPException, status

    accessible_ids = get_accessible_user_ids(current_user, db)
    if resource_user_id not in accessible_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar este recurso"
        )
    return True
