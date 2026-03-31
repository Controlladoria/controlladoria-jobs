"""
System Admin Authentication

Future-proof authentication layer supporting:
- Local password authentication
- MS Entra (Azure AD) SSO
- SAML/OAuth2 providers (Okta, Google, etc.)

Architecture allows seamless migration to external identity providers.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from database_sysadmin import SystemAdmin, SystemAdminAuditLog, ImpersonationSession
from config import settings

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings for sysadmin tokens (separate from customer tokens)
SYSADMIN_SECRET_KEY = settings.jwt_secret_key + "_SYSADMIN"  # Different key for isolation
SYSADMIN_ALGORITHM = "HS256"
SYSADMIN_ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours (shorter than customer tokens)

# Bearer token scheme
security = HTTPBearer()


class SysAdminAuthProvider:
    """
    Abstract authentication provider interface

    Allows plugging in different identity providers:
    - LocalAuthProvider (password-based)
    - MSEntraAuthProvider (Azure AD SSO)
    - OktaAuthProvider (Okta SSO)
    - GoogleAuthProvider (Google Workspace)
    """

    def authenticate(self, credentials: Dict[str, Any], db: Session) -> Optional[SystemAdmin]:
        """Authenticate and return SystemAdmin if valid"""
        raise NotImplementedError

    def get_user_info(self, external_user_id: str) -> Dict[str, Any]:
        """Fetch user info from external provider"""
        raise NotImplementedError


class LocalAuthProvider(SysAdminAuthProvider):
    """Local password-based authentication (current implementation)"""

    def authenticate(self, credentials: Dict[str, Any], db: Session) -> Optional[SystemAdmin]:
        """
        Authenticate with email + password

        Args:
            credentials: {"email": "...", "password": "..."}
            db: Database session

        Returns:
            SystemAdmin if valid, None otherwise
        """
        email = credentials.get("email")
        password = credentials.get("password")

        if not email or not password:
            return None

        # Find sysadmin by email
        sysadmin = db.query(SystemAdmin).filter(
            SystemAdmin.email == email,
            SystemAdmin.is_active == True
        ).first()

        if not sysadmin:
            return None

        # Verify password
        if not sysadmin.hashed_password:
            # SSO-only account, no password set
            return None

        if not pwd_context.verify(password, sysadmin.hashed_password):
            return None

        # Check MFA (TODO: implement TOTP verification)
        if sysadmin.mfa_enabled:
            # mfa_code = credentials.get("mfa_code")
            # if not verify_totp(sysadmin.mfa_secret, mfa_code):
            #     return None
            pass  # MFA verification placeholder

        return sysadmin


class MSEntraAuthProvider(SysAdminAuthProvider):
    """
    Microsoft Entra (Azure AD) SSO authentication

    TODO: Implement when scaling
    - OIDC flow with MS Graph API
    - JWT validation from Azure
    - User provisioning from Entra
    """

    def authenticate(self, credentials: Dict[str, Any], db: Session) -> Optional[SystemAdmin]:
        """
        Authenticate with MS Entra token

        Args:
            credentials: {"ms_token": "...", "id_token": "..."}
        """
        # TODO: Implement MS Entra flow
        # 1. Validate JWT from Azure
        # 2. Extract user email/ID
        # 3. Find or create SystemAdmin with external_auth_provider="ms_entra"
        # 4. Sync permissions from Azure groups
        raise NotImplementedError("MS Entra SSO not yet implemented")

    def get_user_info(self, external_user_id: str) -> Dict[str, Any]:
        """Fetch user from MS Graph API"""
        # TODO: Call Microsoft Graph API
        raise NotImplementedError


# Current provider (can be swapped later)
current_auth_provider = LocalAuthProvider()


def create_sysadmin_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Create JWT token for sysadmin authentication

    Token includes special claims for impersonation support.
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=SYSADMIN_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "sysadmin",  # Distinguish from customer tokens
    })

    encoded_jwt = jwt.encode(to_encode, SYSADMIN_SECRET_KEY, algorithm=SYSADMIN_ALGORITHM)
    return encoded_jwt


def create_impersonation_token(
    sysadmin: SystemAdmin,
    target_user_id: int,
    impersonation_session_id: int,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create special JWT for impersonating a customer

    Token contains both sysadmin ID and customer ID.
    Frontend sees customer context, backend tracks sysadmin.
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=1)  # Max 1 hour

    token_data = {
        "user_id": target_user_id,  # Customer being impersonated (frontend uses this)
        "sysadmin_id": sysadmin.id,  # Real operator
        "sysadmin_email": sysadmin.email,
        "is_impersonation": True,
        "impersonation_session_id": impersonation_session_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "impersonation",
    }

    encoded_jwt = jwt.encode(token_data, SYSADMIN_SECRET_KEY, algorithm=SYSADMIN_ALGORITHM)
    return encoded_jwt


async def get_current_sysadmin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> SystemAdmin:
    """
    Dependency to get current authenticated sysadmin

    Validates JWT token and returns SystemAdmin.
    Raises 401 if invalid or expired.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate system admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token = credentials.credentials
        payload = jwt.decode(token, SYSADMIN_SECRET_KEY, algorithms=[SYSADMIN_ALGORITHM])

        # Check token type
        token_type = payload.get("type")
        if token_type not in ["sysadmin", "impersonation"]:
            raise credentials_exception

        sysadmin_id: int = payload.get("sysadmin_id") or payload.get("sub")
        if sysadmin_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    # Load sysadmin from database
    sysadmin = db.query(SystemAdmin).filter(SystemAdmin.id == sysadmin_id).first()

    if sysadmin is None:
        raise credentials_exception

    if not sysadmin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System admin account is deactivated"
        )

    return sysadmin


async def get_impersonation_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[Dict[str, Any]]:
    """
    Extract impersonation context from token if present

    Returns:
        {
            "sysadmin_id": 1,
            "target_user_id": 456,
            "impersonation_session_id": 789,
            "is_impersonating": True
        }
        or None if not impersonating
    """
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SYSADMIN_SECRET_KEY, algorithms=[SYSADMIN_ALGORITHM])

        if payload.get("is_impersonation"):
            # Verify session is still active
            session_id = payload.get("impersonation_session_id")
            session = db.query(ImpersonationSession).filter(
                ImpersonationSession.id == session_id,
                ImpersonationSession.is_active == True,
                ImpersonationSession.auto_expire_at > datetime.utcnow()
            ).first()

            if not session:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Impersonation session expired or invalid"
                )

            return {
                "sysadmin_id": payload.get("sysadmin_id"),
                "target_user_id": payload.get("user_id"),
                "impersonation_session_id": session_id,
                "is_impersonating": True,
            }

    except JWTError:
        pass

    return None


def require_permission(permission: str):
    """
    Dependency factory for permission-based access control

    Usage:
        @app.get("/sysadmin/users")
        async def list_users(
            sysadmin: SystemAdmin = Depends(require_permission("view_all_users"))
        ):
            ...
    """
    async def permission_checker(
        sysadmin: SystemAdmin = Depends(get_current_sysadmin)
    ) -> SystemAdmin:
        if not sysadmin.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}"
            )
        return sysadmin

    return permission_checker


def log_sysadmin_action(
    db: Session,
    sysadmin: SystemAdmin,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request_context: Optional[Dict[str, Any]] = None,
    impersonation_context: Optional[Dict[str, Any]] = None
):
    """
    Log sysadmin action to audit trail

    CRITICAL: Call this for EVERY sysadmin action
    """
    audit_log = SystemAdminAuditLog(
        sysadmin_id=sysadmin.id,
        sysadmin_email=sysadmin.email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        metadata=metadata,
        endpoint=request_context.get("endpoint") if request_context else None,
        method=request_context.get("method") if request_context else None,
        ip_address=request_context.get("ip_address") if request_context else None,
        user_agent=request_context.get("user_agent") if request_context else None,
        was_impersonating=bool(impersonation_context),
        impersonation_session_id=impersonation_context.get("impersonation_session_id") if impersonation_context else None,
        impersonated_user_id=impersonation_context.get("target_user_id") if impersonation_context else None,
    )

    db.add(audit_log)
    db.commit()


def hash_password(password: str) -> str:
    """Hash password for storage"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


# Helper functions for MS Entra migration (future)

def migrate_to_external_auth(
    sysadmin: SystemAdmin,
    provider: str,
    external_user_id: str,
    external_metadata: Dict[str, Any],
    db: Session
):
    """
    Migrate sysadmin from local auth to external provider

    Steps:
    1. Link external ID
    2. Optionally remove local password
    3. Sync permissions from provider
    """
    sysadmin.external_auth_provider = provider
    sysadmin.external_user_id = external_user_id
    sysadmin.external_metadata = external_metadata

    # Option: Keep local password as backup, or remove it
    # sysadmin.hashed_password = None  # Force SSO only

    db.commit()

    log_sysadmin_action(
        db=db,
        sysadmin=sysadmin,
        action="migrate_to_sso",
        description=f"Migrated to {provider} SSO",
        metadata={"provider": provider, "external_id": external_user_id}
    )


def sync_permissions_from_provider(sysadmin: SystemAdmin, db: Session):
    """
    Sync permissions from external provider (MS Entra groups, etc.)

    Example: Map Azure AD groups to permissions
    - "SysAdmin-ViewUsers" → view_all_users
    - "SysAdmin-Impersonate" → impersonate_users
    """
    # TODO: Implement when adding MS Entra
    pass
