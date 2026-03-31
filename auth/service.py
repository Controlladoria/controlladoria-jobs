"""
Authentication service
Business logic for user registration, login, password reset
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from config import settings
from database import OrgMembership, Organization, PasswordReset, Subscription, SubscriptionStatus, User, UserSession
from email_service import email_service

from .models import TokenResponse, UserLogin, UserRegister
from .security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)


class AuthService:
    """Authentication service for user management"""

    @staticmethod
    def register_user(
        user_data: UserRegister, db: Session
    ) -> Tuple[User, TokenResponse]:
        """
        Register a new user and create initial subscription

        Args:
            user_data: User registration data
            db: Database session

        Returns:
            Tuple of (User, TokenResponse)

        Raises:
            HTTPException: If email already exists
        """
        # Check if email already exists
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já cadastrado",
            )

        # Check if CNPJ already exists (check both Organization and User tables)
        existing_org = db.query(Organization).filter(Organization.cnpj == user_data.cnpj).first()
        existing_cnpj = db.query(User).filter(User.cnpj == user_data.cnpj).first()
        if existing_org or existing_cnpj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Este CNPJ já está cadastrado em nossa plataforma. "
                    f"Se você acredita que não deveria haver uma conta com seu CNPJ, "
                    f"entre em contato conosco: {settings.support_email}"
                ),
            )

        # Generate email verification token
        verification_token = secrets.token_urlsafe(32)

        # Calculate trial end date (managed on our side, not Stripe)
        trial_end = datetime.utcnow() + timedelta(days=settings.stripe_trial_days)

        # Create user
        user = User(
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            full_name=user_data.full_name,
            company_name=user_data.company_name,
            cnpj=user_data.cnpj,
            # Company data from CNPJ lookup
            trade_name=user_data.trade_name,
            cnae_code=user_data.cnae_code,
            cnae_description=user_data.cnae_description,
            company_address_street=user_data.company_address_street,
            company_address_number=user_data.company_address_number,
            company_address_complement=user_data.company_address_complement,
            company_address_district=user_data.company_address_district,
            company_address_city=user_data.company_address_city,
            company_address_state=user_data.company_address_state,
            company_address_zip=user_data.company_address_zip,
            capital_social=user_data.capital_social,
            company_size=user_data.company_size,
            legal_nature=user_data.legal_nature,
            company_phone=user_data.company_phone,
            company_email=user_data.company_email,
            company_status=user_data.company_status,
            company_opened_at=user_data.company_opened_at,
            is_simples_nacional=user_data.is_simples_nacional,
            is_mei=user_data.is_mei,
            # Additional company data (from BrasilAPI full response)
            qsa_partners=user_data.qsa_partners,
            cnaes_secundarios=user_data.cnaes_secundarios,
            company_address_type=user_data.company_address_type,
            is_headquarters=user_data.is_headquarters,
            ibge_code=user_data.ibge_code,
            regime_tributario=user_data.regime_tributario,
            simples_desde=user_data.simples_desde,
            simples_excluido_em=user_data.simples_excluido_em,
            main_partner_name=user_data.main_partner_name,
            main_partner_qualification=user_data.main_partner_qualification,
            # Account settings
            is_active=True,
            is_verified=False,
            email_verification_token=verification_token,
            email_verification_token_created_at=datetime.utcnow(),
            trial_end_date=trial_end,
            agreed_to_terms=user_data.agreed_to_terms,
            agreed_to_terms_at=datetime.utcnow() if user_data.agreed_to_terms else None,
            agreed_to_privacy=user_data.agreed_to_privacy,
            agreed_to_privacy_at=datetime.utcnow() if user_data.agreed_to_privacy else None,
        )

        db.add(user)
        db.flush()  # Get user.id without committing

        # Create Organization from company data
        org = Organization(
            company_name=user_data.company_name,
            cnpj=user_data.cnpj,
            trade_name=user_data.trade_name,
            cnae_code=user_data.cnae_code,
            cnae_description=user_data.cnae_description,
            company_address_street=user_data.company_address_street,
            company_address_number=user_data.company_address_number,
            company_address_complement=user_data.company_address_complement,
            company_address_district=user_data.company_address_district,
            company_address_city=user_data.company_address_city,
            company_address_state=user_data.company_address_state,
            company_address_zip=user_data.company_address_zip,
            capital_social=user_data.capital_social,
            company_size=user_data.company_size,
            legal_nature=user_data.legal_nature,
            company_phone=user_data.company_phone,
            company_email=user_data.company_email,
            company_status=user_data.company_status,
            company_opened_at=user_data.company_opened_at,
            is_simples_nacional=user_data.is_simples_nacional,
            is_mei=user_data.is_mei,
            qsa_partners=user_data.qsa_partners,
            cnaes_secundarios=user_data.cnaes_secundarios,
            company_address_type=user_data.company_address_type,
            is_headquarters=user_data.is_headquarters,
            ibge_code=user_data.ibge_code,
            regime_tributario=user_data.regime_tributario,
            simples_desde=user_data.simples_desde,
            simples_excluido_em=user_data.simples_excluido_em,
            main_partner_name=user_data.main_partner_name,
            main_partner_qualification=user_data.main_partner_qualification,
        )
        db.add(org)
        db.flush()  # Get org.id

        # Create owner membership
        membership = OrgMembership(
            user_id=user.id,
            organization_id=org.id,
            role="owner",
            joined_at=datetime.utcnow(),
        )
        db.add(membership)

        # Set active org on user
        user.active_org_id = org.id
        db.commit()
        db.refresh(user)

        # Create trial subscription linked to organization
        from plan_features import get_default_plan
        default_plan = get_default_plan(db)
        subscription = Subscription(
            user_id=user.id,
            organization_id=org.id,  # Per-org billing
            stripe_customer_id="",  # Empty string for trial (will be set when user subscribes)
            stripe_subscription_id=None,
            stripe_price_id=None,
            status="trialing",
            trial_start=datetime.utcnow(),
            trial_end=trial_end,
            current_period_start=datetime.utcnow(),
            current_period_end=trial_end,
            plan_id=default_plan.id if default_plan else None,
            max_users=default_plan.max_users if default_plan else 1,
        )
        db.add(subscription)
        db.commit()

        # Send verification email (async, non-blocking)
        try:
            asyncio.create_task(
                email_service.send_verification_email(
                    to=user.email,
                    token=verification_token,
                    user_name=user.full_name or user.email.split("@")[0],
                )
            )
        except Exception as e:
            # Log email error but don't block registration
            print(f"Failed to send verification email: {str(e)}")

        # Send welcome email (async, non-blocking)
        try:
            asyncio.create_task(
                email_service.send_welcome_email(
                    to=user.email,
                    user_name=user.full_name or user.email.split("@")[0],
                    trial_days=settings.stripe_trial_days,
                )
            )
        except Exception as e:
            # Log email error but don't block registration
            print(f"Failed to send welcome email: {str(e)}")

        # Load claims for new user (same as login)
        from auth.permissions import get_role_permissions
        from database import UserClaim

        role_permissions = get_role_permissions(user.role)
        user_specific_claims = db.query(UserClaim).filter(
            UserClaim.user_id == user.id
        ).all()

        all_claims = set()
        for perm in role_permissions:
            all_claims.add(perm.value)
        for claim in user_specific_claims:
            if claim.is_valid:
                if claim.claim_value.lower() == "true":
                    all_claims.add(claim.claim_type)
                elif claim.claim_value.lower() == "false":
                    all_claims.discard(claim.claim_type)

        # Create tokens with claims (include org_id for multi-org support)
        org_id = user.active_org_id
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role, "org_id": org_id},
            claims=list(all_claims)
        )
        refresh_token = create_refresh_token(user.id)

        token_response = TokenResponse(
            access_token=access_token, refresh_token=refresh_token
        )

        return user, token_response

    @staticmethod
    def login_user(login_data: UserLogin, user_agent: str, ip_address: str, db: Session) -> TokenResponse:
        """
        Authenticate user and generate tokens

        Args:
            login_data: User login credentials
            user_agent: User-Agent header from request
            ip_address: IP address from request
            db: Database session

        Returns:
            TokenResponse with access and refresh tokens

        Raises:
            HTTPException: If credentials are invalid
        """
        from auth.session_manager import SessionManager

        # Find user by email
        user = db.query(User).filter(User.email == login_data.email).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="E-mail ou senha incorretos",
            )

        # Verify password
        if not verify_password(login_data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="E-mail ou senha incorretos",
            )

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Conta de usuário inativa"
            )

        # Check subscription for invited users (non-owners)
        if user.role != 'owner':
            # Find the owner of this organization
            owner = db.query(User).filter(
                User.company_tax_id == user.company_tax_id,
                User.role == 'owner'
            ).first()

            if owner:
                # Check if owner has active subscription
                from database import Subscription, SubscriptionStatus
                subscription = db.query(Subscription).filter(
                    Subscription.user_id == owner.id
                ).first()

                # Block login if owner has no subscription or inactive subscription
                has_active_sub = (
                    subscription and
                    subscription.status in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]
                )

                if not has_active_sub:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="A assinatura da organização está inativa. Entre em contato com o administrador."
                    )

        # Check if MFA is enabled and device is trusted
        if user.mfa_enabled:
            from .mfa_service import MFAService
            import hashlib

            # Generate device fingerprint
            device_fingerprint = hashlib.sha256(
                f"{user_agent}{ip_address}".encode()
            ).hexdigest()

            # Check if device is trusted and trust is still valid
            trusted_session = (
                db.query(UserSession)
                .filter_by(
                    user_id=user.id,
                    device_fingerprint=device_fingerprint,
                    is_trusted_device=True,
                    is_active=True
                )
                .filter(UserSession.trusted_until > datetime.utcnow())
                .first()
            )

            if not trusted_session:
                # Device not trusted - require MFA verification
                # Create temporary token for MFA verification (valid 5 minutes)
                temp_token = create_access_token(
                    data={"sub": str(user.id), "email": user.email, "temp": True},
                    expires_delta=timedelta(minutes=5)
                )

                # Send email code if using email MFA
                if user.mfa_method == "email":
                    code = MFAService.generate_email_code()
                    MFAService.store_email_code(user.id, code)
                    try:
                        asyncio.create_task(
                            MFAService.send_email_mfa_code(user, code)
                        )
                    except Exception as e:
                        # Log email error but don't block login
                        logging.warning(f"Failed to send MFA email: {str(e)}")

                raise HTTPException(
                    status_code=status.HTTP_202_ACCEPTED,
                    detail={
                        "mfa_required": True,
                        "mfa_method": user.mfa_method,
                        "temp_token": temp_token,
                        "message": "MFA verification required"
                    }
                )

        # Create session (tracks device, enforces 2-device limit)
        new_session, kicked_sessions = SessionManager.create_session(
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
            db=db
        )

        # Update last login timestamp
        user.last_login = datetime.utcnow()
        db.commit()

        # Log kicked sessions for debugging/notification
        if kicked_sessions:
            for session in kicked_sessions:
                logging.info(
                    f"Session kicked for user {user.id}: {session.device_name} "
                    f"(last active: {session.last_activity})"
                )

        # Load user claims from database
        from auth.permissions import get_role_permissions, Permission
        from database import UserClaim

        # Get role-based permissions
        role_permissions = get_role_permissions(user.role)

        # Get user-specific claims (overrides/additions)
        user_specific_claims = db.query(UserClaim).filter(
            UserClaim.user_id == user.id
        ).all()

        # Combine into final claims list
        all_claims = set()

        # Add role permissions
        for perm in role_permissions:
            all_claims.add(perm.value)

        # Add/override with user-specific claims
        for claim in user_specific_claims:
            if claim.is_valid:
                if claim.claim_value.lower() == "true":
                    all_claims.add(claim.claim_type)
                elif claim.claim_value.lower() == "false":
                    # Explicit deny - remove from claims
                    all_claims.discard(claim.claim_type)

        # Create tokens with claims (include session_id and org_id)
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role, "sid": new_session.id, "org_id": user.active_org_id},
            claims=list(all_claims)
        )
        refresh_token = create_refresh_token(user.id)

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    @staticmethod
    def refresh_access_token(refresh_token: str, db: Session) -> TokenResponse:
        """
        Generate new access token from refresh token

        Args:
            refresh_token: Refresh token
            db: Database session

        Returns:
            TokenResponse with new access token

        Raises:
            HTTPException: If refresh token is invalid
        """
        # Verify refresh token
        payload = verify_token(refresh_token, token_type="refresh")

        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido ou expirado",
            )

        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
            )

        # Find user
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado ou inativo",
            )

        # Load user claims (same logic as login)
        from auth.permissions import get_role_permissions
        from database import UserClaim

        role_permissions = get_role_permissions(user.role)
        user_specific_claims = db.query(UserClaim).filter(
            UserClaim.user_id == user.id
        ).all()

        all_claims = set()
        for perm in role_permissions:
            all_claims.add(perm.value)
        for claim in user_specific_claims:
            if claim.is_valid:
                if claim.claim_value.lower() == "true":
                    all_claims.add(claim.claim_type)
                elif claim.claim_value.lower() == "false":
                    all_claims.discard(claim.claim_type)

        # Create new tokens with claims (include org_id)
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role, "org_id": user.active_org_id},
            claims=list(all_claims)
        )
        new_refresh_token = create_refresh_token(user.id)

        return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)

    @staticmethod
    def request_password_reset(email: str, db: Session) -> str:
        """
        Create password reset token

        Args:
            email: User email
            db: Database session

        Returns:
            Reset token

        Raises:
            HTTPException: If user not found
        """
        # Find user
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Don't reveal if email exists or not (security best practice)
            # But still raise error to indicate completion
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="If the email exists, a password reset link has been sent",
            )

        # Generate reset token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)  # 1 hour expiry

        # Create password reset record
        reset = PasswordReset(
            user_id=user.id, token=token, expires_at=expires_at, used=False
        )

        db.add(reset)
        db.commit()

        # Send password reset email (async, non-blocking)
        try:
            asyncio.create_task(
                email_service.send_password_reset_email(
                    to=user.email,
                    token=token,
                    user_name=user.full_name or user.email.split("@")[0],
                )
            )
        except Exception as e:
            # Log email error but don't block operation
            print(f"Failed to send password reset email: {str(e)}")

        return token

    @staticmethod
    def confirm_password_reset(token: str, new_password: str, db: Session) -> bool:
        """
        Reset user password with token

        Args:
            token: Reset token
            new_password: New password
            db: Database session

        Returns:
            True if successful

        Raises:
            HTTPException: If token is invalid or expired
        """
        # Find reset token
        reset = (
            db.query(PasswordReset)
            .filter(PasswordReset.token == token, PasswordReset.used == False)
            .first()
        )

        if not reset:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token inválido ou já utilizado",
            )

        # Check expiration
        if reset.expires_at < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token expirado",
            )

        # Find user
        user = db.query(User).filter(User.id == reset.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
            )

        # Update password
        user.password_hash = hash_password(new_password)
        reset.used = True

        db.commit()

        return True

    @staticmethod
    def update_user_profile(user: User, update_data: dict, db: Session) -> User:
        """
        Update user profile

        Args:
            user: User to update
            update_data: Dictionary of fields to update
            db: Database session

        Returns:
            Updated user
        """
        # Update allowed fields
        if "full_name" in update_data and update_data["full_name"] is not None:
            user.full_name = update_data["full_name"]

        if "company_name" in update_data and update_data["company_name"] is not None:
            user.company_name = update_data["company_name"]

        if "cnpj" in update_data and update_data["cnpj"] is not None:
            user.cnpj = update_data["cnpj"]

        # Update company data fields (from CNPJ lookup)
        company_fields = [
            "trade_name", "cnae_code", "cnae_description",
            "company_address_street", "company_address_number", "company_address_complement",
            "company_address_district", "company_address_city", "company_address_state",
            "company_address_zip", "capital_social", "company_size", "legal_nature",
            "company_phone", "company_email", "company_status", "company_opened_at",
            "is_simples_nacional", "is_mei",
            # Additional fields from BrasilAPI
            "qsa_partners", "cnaes_secundarios", "company_address_type",
            "is_headquarters", "ibge_code", "regime_tributario",
            "simples_desde", "simples_excluido_em",
            "main_partner_name", "main_partner_qualification",
        ]
        for field in company_fields:
            if field in update_data:
                setattr(user, field, update_data[field])

        user.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(user)

        return user

    @staticmethod
    def verify_mfa_login(
        temp_token: str,
        mfa_code: str,
        trust_device: bool,
        user_agent: str,
        ip_address: str,
        db: Session
    ) -> TokenResponse:
        """
        Verify MFA code during login and issue full tokens

        Args:
            temp_token: Temporary token from initial login
            mfa_code: 6-digit MFA code (TOTP, Email, or backup code)
            trust_device: Whether to trust this device for 30 days
            user_agent: User-Agent header
            ip_address: IP address
            db: Database session

        Returns:
            TokenResponse with access and refresh tokens

        Raises:
            HTTPException: If MFA verification fails
        """
        from .mfa_service import MFAService
        from .session_manager import SessionManager
        import hashlib

        # Verify temp token
        payload = verify_token(temp_token, token_type="access")
        if not payload or not payload.get("temp"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token temporário inválido ou expirado"
            )

        user_id = payload.get("sub")
        user = db.query(User).filter(User.id == int(user_id)).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado ou inativo"
            )

        # Verify MFA code based on method
        code_valid = False

        if user.mfa_method == "totp":
            # Try TOTP code (decrypt secret first)
            from auth.encryption import decrypt_mfa_secret
            decrypted_secret = decrypt_mfa_secret(user.mfa_secret)
            code_valid = MFAService.verify_totp_code(decrypted_secret, mfa_code)
        elif user.mfa_method == "email":
            # Try Email code
            code_valid = MFAService.verify_email_code(user.id, mfa_code)

        # If TOTP/Email failed, try backup code
        if not code_valid:
            code_valid = MFAService.verify_backup_code(user, mfa_code, db)

        if not code_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Código inválido"
            )

        # Create session
        new_session, kicked_sessions = SessionManager.create_session(
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
            db=db
        )

        # Mark device as trusted if requested
        if trust_device:
            device_fingerprint = hashlib.sha256(
                f"{user_agent}{ip_address}".encode()
            ).hexdigest()
            new_session.is_trusted_device = True
            new_session.device_fingerprint = device_fingerprint
            new_session.trusted_until = datetime.utcnow() + timedelta(days=30)
            db.commit()

        # Load user claims
        from auth.permissions import get_role_permissions
        from database import UserClaim

        role_permissions = get_role_permissions(user.role)
        user_specific_claims = db.query(UserClaim).filter(
            UserClaim.user_id == user.id
        ).all()

        all_claims = set()
        for perm in role_permissions:
            all_claims.add(perm.value)
        for claim in user_specific_claims:
            if claim.is_valid:
                if claim.claim_value.lower() == "true":
                    all_claims.add(claim.claim_type)
                elif claim.claim_value.lower() == "false":
                    all_claims.discard(claim.claim_type)

        # Create tokens with claims (include session_id and org_id)
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role, "sid": new_session.id, "org_id": user.active_org_id},
            claims=list(all_claims)
        )
        refresh_token = create_refresh_token(user.id)

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
