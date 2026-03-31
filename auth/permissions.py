"""
Role-Based Access Control (RBAC) with Claims/Permissions

Comprehensive permission system with granular roles and claims.
Replaces simple is_admin boolean with flexible role-based permissions.
"""

from enum import Enum
from functools import lru_cache
from typing import List, Set
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from database import User


def require_super_admin(user: User) -> None:
    """
    Check if user is a super admin, raise exception if not

    Args:
        user: User object

    Raises:
        HTTPException: 403 if user is not super admin
    """
    if not user or user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem acessar este recurso",
        )


def can_access_billing(user: User) -> bool:
    """
    Check if user can access billing/subscription pages

    Only super admins can manage billing.

    Args:
        user: User object

    Returns:
        True if user can access billing
    """
    return user and user.role == "super_admin"


def can_manage_team(user: User) -> bool:
    """
    Check if user can manage team (invite/remove members)

    Only super admins can manage team.

    Args:
        user: User object

    Returns:
        True if user can manage team
    """
    return user and user.role == "super_admin"


def get_accessible_user_ids(user: User, db: Session) -> list:
    """
    Get all user IDs whose documents this user can access.

    Multi-org aware: scopes to active organization's members.
    Falls back to legacy parent_user_id logic for unmigrated users.

    **PERFORMANCE**: Results are cached on the user object for the duration of the request
    to avoid repeated database queries (called 64+ times per request).

    Args:
        user: User object (with _active_org_id hydrated by get_current_user)
        db: Database session

    Returns:
        List of accessible user IDs
    """
    # Check if already cached on user object (request-level cache)
    cache_attr = '_accessible_user_ids_cache'
    if hasattr(user, cache_attr):
        return getattr(user, cache_attr)

    from database import OrgMembership

    org_id = getattr(user, '_active_org_id', None) or getattr(user, 'active_org_id', None)

    if org_id:
        # Org-aware query: return all active member user_ids in this organization
        members = db.query(OrgMembership.user_id).filter_by(
            organization_id=org_id, is_active=True
        ).all()
        result = [m.user_id for m in members]
        # Ensure current user is always included
        if user.id not in result:
            result.append(user.id)
    else:
        # Legacy fallback for unmigrated users (parent_user_id based)
        from auth.team_management import get_company_users
        company_users = get_company_users(user.id, db)
        result = [u.id for u in company_users]

    # Store in request-level cache
    setattr(user, cache_attr, result)

    return result


def get_active_org_id(user: User) -> int | None:
    """Get the active organization ID for the current user."""
    return getattr(user, '_active_org_id', None) or getattr(user, 'active_org_id', None)


def document_org_filter(query, user: User, db: Session):
    """
    Apply org-aware filtering to a document query.

    For users with an active org: filter by org_id on documents.
    Documents without org_id (pre-migration) are included if user_id matches.
    Falls back to user_id filtering for legacy users.
    """
    from database import Document
    from sqlalchemy import or_

    org_id = get_active_org_id(user)
    accessible_ids = get_accessible_user_ids(user, db)

    if org_id:
        # Show documents belonging to this org OR owned by accessible users with no org_id (legacy)
        return query.filter(
            or_(
                Document.organization_id == org_id,
                # Legacy documents: owned by accessible users, no org assigned
                (Document.organization_id.is_(None)) & (Document.user_id.in_(accessible_ids)),
            )
        )
    else:
        # Legacy fallback: user_id only
        return query.filter(Document.user_id.in_(accessible_ids))


def verify_document_access(doc, user: User, db: Session) -> bool:
    """
    Check if a user has access to a specific document.
    Used for single-document lookups after fetching by ID.
    """
    if doc is None:
        return False
    org_id = get_active_org_id(user)
    if org_id:
        # Document must belong to this org, OR be a legacy doc owned by an accessible user
        if doc.organization_id == org_id:
            return True
        if doc.organization_id is None:
            accessible_ids = get_accessible_user_ids(user, db)
            return doc.user_id in accessible_ids
        return False
    else:
        # Legacy: check user_id
        accessible_ids = get_accessible_user_ids(user, db)
        return doc.user_id in accessible_ids


# ============================================================================
# CLAIMS-BASED PERMISSION SYSTEM
# ============================================================================


class Permission(str, Enum):
    """
    Granular permissions (claims) that can be assigned to roles
    """

    # Document permissions
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_WRITE = "documents.write"
    DOCUMENTS_DELETE = "documents.delete"
    DOCUMENTS_EXPORT = "documents.export"

    # Report permissions
    REPORTS_VIEW = "reports.view"
    REPORTS_EXPORT = "reports.export"
    REPORTS_ADVANCED = "reports.advanced"  # DRE, Balance Sheet, Cash Flow

    # Client/Supplier permissions
    CLIENTS_READ = "clients.read"
    CLIENTS_WRITE = "clients.write"
    CLIENTS_DELETE = "clients.delete"

    # Team management permissions
    TEAM_VIEW = "team.view"
    TEAM_INVITE = "team.invite"
    TEAM_REMOVE = "team.remove"
    TEAM_MANAGE_ROLES = "team.manage_roles"

    # Billing/Subscription permissions
    BILLING_VIEW = "billing.view"
    BILLING_MANAGE = "billing.manage"

    # Admin permissions
    ADMIN_DASHBOARD = "admin.dashboard"
    ADMIN_VIEW_USERS = "admin.view_users"
    ADMIN_VIEW_AUDIT_LOGS = "admin.view_audit_logs"
    ADMIN_VIEW_CONTACT_SUBMISSIONS = "admin.view_contact_submissions"

    # API permissions
    API_ACCESS = "api.access"
    API_KEYS_MANAGE = "api.keys.manage"

    # Account permissions
    ACCOUNT_MANAGE = "account.manage"  # Manage own account settings


class Role(str, Enum):
    """
    Predefined roles with associated permissions
    """

    # Organization owner - has ALL permissions, cannot be removed
    OWNER = "owner"

    # Administrator - full access except billing management
    ADMIN = "admin"

    # Accountant - full document and report access, no team management
    ACCOUNTANT = "accountant"

    # Bookkeeper - can create/edit documents, limited reports
    BOOKKEEPER = "bookkeeper"

    # Viewer - read-only access to documents and basic reports
    VIEWER = "viewer"

    # API User - programmatic access via API keys
    API_USER = "api_user"


# Permission mapping for each role
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.OWNER: {
        # Owner has ALL permissions
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.DOCUMENTS_DELETE,
        Permission.DOCUMENTS_EXPORT,
        Permission.REPORTS_VIEW,
        Permission.REPORTS_EXPORT,
        Permission.REPORTS_ADVANCED,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.CLIENTS_DELETE,
        Permission.TEAM_VIEW,
        Permission.TEAM_INVITE,
        Permission.TEAM_REMOVE,
        Permission.TEAM_MANAGE_ROLES,
        Permission.BILLING_VIEW,
        Permission.BILLING_MANAGE,
        Permission.ADMIN_DASHBOARD,
        Permission.ADMIN_VIEW_USERS,
        Permission.ADMIN_VIEW_AUDIT_LOGS,
        Permission.ADMIN_VIEW_CONTACT_SUBMISSIONS,
        Permission.API_ACCESS,
        Permission.API_KEYS_MANAGE,
        Permission.ACCOUNT_MANAGE,
    },
    Role.ADMIN: {
        # Admin has everything except billing management
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.DOCUMENTS_DELETE,
        Permission.DOCUMENTS_EXPORT,
        Permission.REPORTS_VIEW,
        Permission.REPORTS_EXPORT,
        Permission.REPORTS_ADVANCED,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.CLIENTS_DELETE,
        Permission.TEAM_VIEW,
        Permission.TEAM_INVITE,
        Permission.TEAM_REMOVE,
        Permission.TEAM_MANAGE_ROLES,
        Permission.BILLING_VIEW,  # Can view but not manage
        Permission.ADMIN_DASHBOARD,
        Permission.ADMIN_VIEW_USERS,
        Permission.ADMIN_VIEW_AUDIT_LOGS,
        Permission.ADMIN_VIEW_CONTACT_SUBMISSIONS,
        Permission.API_ACCESS,
        Permission.API_KEYS_MANAGE,
        Permission.ACCOUNT_MANAGE,
    },
    Role.ACCOUNTANT: {
        # Accountant - full document and report access, no team/billing
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.DOCUMENTS_DELETE,
        Permission.DOCUMENTS_EXPORT,
        Permission.REPORTS_VIEW,
        Permission.REPORTS_EXPORT,
        Permission.REPORTS_ADVANCED,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.CLIENTS_DELETE,
        Permission.TEAM_VIEW,  # Can see team members
        Permission.ACCOUNT_MANAGE,
    },
    Role.BOOKKEEPER: {
        # Bookkeeper - can create/edit documents, basic reports
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.DOCUMENTS_EXPORT,
        Permission.REPORTS_VIEW,
        Permission.REPORTS_EXPORT,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.TEAM_VIEW,
        Permission.ACCOUNT_MANAGE,
    },
    Role.VIEWER: {
        # Viewer - read-only access
        Permission.DOCUMENTS_READ,
        Permission.REPORTS_VIEW,
        Permission.CLIENTS_READ,
        Permission.TEAM_VIEW,
        Permission.ACCOUNT_MANAGE,
    },
    Role.API_USER: {
        # API User - programmatic access
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.REPORTS_VIEW,
        Permission.CLIENTS_READ,
        Permission.API_ACCESS,
    },
}


def get_role_permissions(role: str) -> Set[Permission]:
    """
    Get all permissions for a given role

    Args:
        role: The role string (e.g., "owner", "admin")

    Returns:
        Set of permissions for the role
    """
    try:
        role_enum = Role(role)
        return ROLE_PERMISSIONS.get(role_enum, set())
    except ValueError:
        # Invalid role, return empty set
        return set()


def has_permission(user: User, permission: Permission) -> bool:
    """
    Check if a user has a specific permission

    Checks both:
    1. Role-based permissions (from ROLE_PERMISSIONS mapping)
    2. User-specific claims (from user_claims table)

    Args:
        user: The user object
        permission: The permission to check

    Returns:
        True if user has permission, False otherwise
    """
    if not user or not user.role:
        return False

    # Check role-based permissions first
    role_perms = get_role_permissions(user.role)
    if permission in role_perms:
        return True

    # Check user-specific claims (overrides/additions to role)
    # User claims are loaded via relationship: user.claims
    if hasattr(user, 'claims') and user.claims:
        for claim in user.claims:
            if claim.claim_type == permission.value and claim.is_valid:
                return claim.claim_value.lower() == "true"

    return False


def has_any_permission(user: User, permissions: List[Permission]) -> bool:
    """
    Check if a user has ANY of the specified permissions

    Args:
        user: The user object
        permissions: List of permissions to check

    Returns:
        True if user has at least one permission, False otherwise
    """
    if not user or not user.role:
        return False

    role_perms = get_role_permissions(user.role)
    return any(perm in role_perms for perm in permissions)


def has_all_permissions(user: User, permissions: List[Permission]) -> bool:
    """
    Check if a user has ALL of the specified permissions

    Args:
        user: The user object
        permissions: List of permissions to check

    Returns:
        True if user has all permissions, False otherwise
    """
    if not user or not user.role:
        return False

    role_perms = get_role_permissions(user.role)
    return all(perm in role_perms for perm in permissions)


def require_permission(user: User, permission: Permission) -> None:
    """
    Require user to have a specific permission, raise 403 if not

    Args:
        user: The user object
        permission: The required permission

    Raises:
        HTTPException: 403 if user doesn't have permission
    """
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acesso negado. Permissão necessária: {permission.value}",
        )


def require_any_permission(user: User, permissions: List[Permission]) -> None:
    """
    Require user to have ANY of the specified permissions, raise 403 if not

    Args:
        user: The user object
        permissions: List of permissions (user needs at least one)

    Raises:
        HTTPException: 403 if user doesn't have any permission
    """
    if not has_any_permission(user, permissions):
        perm_names = ", ".join([p.value for p in permissions])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acesso negado. Permissão necessária: uma de [{perm_names}]",
        )


def is_owner(user: User) -> bool:
    """Check if user is organization owner"""
    return user and user.role == Role.OWNER.value


def is_admin_or_owner(user: User) -> bool:
    """Check if user is admin or owner"""
    return user and user.role in (Role.OWNER.value, Role.ADMIN.value)


def can_manage_team_new(user: User) -> bool:
    """Check if user can manage team members (new permission system)"""
    return has_permission(user, Permission.TEAM_INVITE)


def can_manage_billing_new(user: User) -> bool:
    """Check if user can manage billing (new permission system)"""
    return has_permission(user, Permission.BILLING_MANAGE)


def can_access_admin_dashboard_new(user: User) -> bool:
    """Check if user can access admin dashboard (new permission system)"""
    return has_permission(user, Permission.ADMIN_DASHBOARD)


# Role display info for frontend
ROLE_INFO = {
    "owner": {
        "display_name": "Proprietário",
        "description": "Dono da organização com acesso completo a todas as funcionalidades",
        "badge_color": "purple",
        "icon": "👑",
    },
    "admin": {
        "display_name": "Administrador",
        "description": "Acesso completo exceto gerenciamento de assinatura",
        "badge_color": "blue",
        "icon": "🛡️",
    },
    "accountant": {
        "display_name": "Contador",
        "description": "Acesso completo a documentos e relatórios avançados",
        "badge_color": "green",
        "icon": "📊",
    },
    "bookkeeper": {
        "display_name": "Auxiliar Contábil",
        "description": "Pode criar e editar documentos, relatórios básicos",
        "badge_color": "cyan",
        "icon": "📝",
    },
    "viewer": {
        "display_name": "Visualizador",
        "description": "Acesso somente leitura a documentos e relatórios",
        "badge_color": "gray",
        "icon": "👁️",
    },
    "api_user": {
        "display_name": "Usuário API",
        "description": "Acesso programático via API keys",
        "badge_color": "orange",
        "icon": "🔑",
    },
}


def get_role_info(role: str) -> dict:
    """Get display info for a role"""
    return ROLE_INFO.get(role, {
        "display_name": role.title(),
        "description": "Função personalizada",
        "badge_color": "gray",
        "icon": "👤",
    })
