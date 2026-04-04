"""
Database setup and ORM models
Using SQLAlchemy for easy migration to PostgreSQL later
"""

import enum
import os
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, JSON, Numeric, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.pool import StaticPool

# Import settings which properly handles .env files with quotes
from config import settings

# Database configuration - use pydantic settings which strips quotes automatically
DATABASE_URL = settings.database_url

# For SQLite, we need special config for FastAPI async compatibility
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
else:
    # PostgreSQL/Production configuration with proper connection pooling
    # FOR 500K+ USERS - Highly scalable configuration
    # Each API server instance can handle ~50-100 req/sec with these settings
    # Scale horizontally with load balancer for higher throughput
    engine = create_engine(
        DATABASE_URL,
        pool_size=50,  # Base pool size (50 persistent connections)
        max_overflow=100,  # Allow 100 additional connections on demand (total: 150)
        pool_timeout=10,  # Wait max 10s for connection (fail fast if overloaded)
        pool_recycle=1800,  # Recycle connections after 30 minutes (prevents stale connections)
        pool_pre_ping=True,  # Verify connections before using (auto-reconnect on DB restart)
        echo=False,  # Set to True for SQL logging (debug only)
        connect_args={
            "connect_timeout": 5,  # Fast connection timeout (5s)
            "options": "-c statement_timeout=15000",  # Query timeout 15s (fail fast on slow queries)
            "keepalives": 1,  # Enable TCP keepalives
            "keepalives_idle": 30,  # Start keepalives after 30s idle
            "keepalives_interval": 10,  # Keepalive interval
            "keepalives_count": 5,  # Max keepalive probes
        },
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DocumentStatus(str, enum.Enum):
    """Document processing status"""

    PENDING = "pending"
    PROCESSING = "processing"
    PENDING_VALIDATION = "pending_validation"  # Item 9: Awaiting user review
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"  # Item 4: Cancelled by cancellation NF


class Document(Base):
    """
    Main document table
    Stores uploaded files and their processing status
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    # File information
    file_name = Column(String(255), nullable=False, index=True)  # Indexed for search
    file_type = Column(String(50), nullable=False)  # pdf, jpg, png
    file_path = Column(String(500), nullable=False)  # path to stored file
    file_size = Column(Integer)
    file_hash = Column(String(64), nullable=True, index=True)  # SHA256 hash for duplicate detection

    # Processing status
    status = Column(
        SQLEnum(DocumentStatus),
        default=DocumentStatus.PENDING,
        nullable=False,
        index=True,
    )  # Indexed for filtering
    error_message = Column(Text, nullable=True)

    # Extracted structured data (stored as JSON text)
    extracted_data_json = Column(Text, nullable=True)

    # Denormalized fields for quick filtering (extracted from JSON)
    department = Column(String(100), nullable=True, index=True)  # Cost center/department
    category = Column(String(100), nullable=True, index=True)  # Transaction category

    # Timestamps
    upload_date = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )  # Indexed for sorting
    processed_date = Column(DateTime, nullable=True)

    # CNPJ validation warning (Item 7 - warn instead of block)
    cnpj_mismatch = Column(Boolean, default=False, nullable=False, server_default="false")
    cnpj_warning_message = Column(Text, nullable=True)

    # Upload queue (Item 8 - prevent overload)
    queue_position = Column(Integer, nullable=True)
    queued_at = Column(DateTime, nullable=True)

    # Background retry support (nightly retry of failed documents)
    retry_count = Column(Integer, default=0, nullable=False, server_default="0")
    max_retries_exhausted = Column(Boolean, default=False, nullable=False, server_default="false")
    last_retry_at = Column(DateTime, nullable=True)

    # NFe cancellation support (Item 4)
    is_cancellation = Column(Boolean, default=False, nullable=False, server_default="false")
    cancelled_by_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    cancels_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)

    # User reference (for multi-user support)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )  # Indexed for multi-user queries

    # Organization reference (for multi-org isolation)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )  # Documents scoped to the org that was active at upload time

    # Client reference (optional - for tracking who gave/received money)
    client_id = Column(
        Integer, ForeignKey("clients.id"), nullable=True, index=True
    )  # Indexed for client filtering

    # Composite indexes for common query patterns
    __table_args__ = (
        Index(
            "idx_status_upload_date", "status", "upload_date"
        ),  # For filtering by status and sorting by date
        Index(
            "idx_user_status", "user_id", "status"
        ),  # For user-specific status queries
        Index("idx_user_client", "user_id", "client_id"),  # For client filtering
    )

    # Relationships
    user = relationship("User", back_populates="documents")
    client = relationship("Client", backref="documents")
    validation_rows = relationship("DocumentValidationRow", back_populates="document", cascade="all, delete-orphan")
    cancelled_by = relationship("Document", foreign_keys=[cancelled_by_document_id], remote_side="Document.id", uselist=False)
    cancels_document = relationship("Document", foreign_keys=[cancels_document_id], remote_side="Document.id", uselist=False)

    def __repr__(self):
        return f"<Document(id={self.id}, file_name='{self.file_name}', status='{self.status}')>"


class DocumentValidationRow(Base):
    """
    Validation rows for document review (Item 9)
    Each row represents a single transaction extracted from the document,
    pending user review and approval.
    """

    __tablename__ = "document_validation_rows"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    row_index = Column(Integer, nullable=False)  # Order within document

    # Extracted data (editable by user during validation)
    description = Column(String(500), nullable=True)
    transaction_date = Column(String(20), nullable=True)  # ISO date string
    amount = Column(Integer, nullable=True)  # Amount in cents
    category = Column(String(100), nullable=True)
    transaction_type = Column(String(20), nullable=True)  # income/expense/gasto/investimento

    # Validation status
    is_validated = Column(Boolean, default=False, nullable=False, server_default="false")
    validated_at = Column(DateTime, nullable=True)

    # Original AI-extracted data (preserved for audit trail)
    original_data_json = Column(Text, nullable=True)

    # User who validated
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    # Relationships
    document = relationship("Document", back_populates="validation_rows")

    __table_args__ = (
        Index("idx_validation_doc_row", "document_id", "row_index"),
        Index("idx_validation_doc_validated", "document_id", "is_validated"),
    )

    def __repr__(self):
        return f"<DocumentValidationRow(id={self.id}, doc={self.document_id}, row={self.row_index})>"


class ContactSubmission(Base):
    """
    Contact form submissions table
    Stores contact requests from users
    """

    __tablename__ = "contact_submissions"

    id = Column(Integer, primary_key=True, index=True)

    # Contact information
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False, index=True)  # Indexed for search
    phone = Column(String(20), nullable=True)
    message = Column(Text, nullable=False)

    # Metadata
    submitted_date = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )  # Indexed for sorting
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)

    # Status
    read = Column(
        Integer, default=0, index=True
    )  # Indexed for filtering unread messages
    replied = Column(Integer, default=0)  # 0 = not replied, 1 = replied

    # Composite index for filtering unread messages by date
    __table_args__ = (Index("idx_read_submitted", "read", "submitted_date"),)

    def __repr__(self):
        return f"<ContactSubmission(id={self.id}, name='{self.name}', email='{self.email}')>"


class Organization(Base):
    """
    Organization table
    Stores company data (moved from User model for multi-org support).
    Each org has exactly one owner, multiple members, and its own subscription.
    """

    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)

    # Company identity
    company_name = Column(String(255), nullable=False)  # Razão social
    cnpj = Column(String(50), nullable=False, unique=True, index=True)

    # Company data (from CNPJ lookup)
    trade_name = Column(String(255), nullable=True)
    cnae_code = Column(String(20), nullable=True)
    cnae_description = Column(String(500), nullable=True)
    company_address_street = Column(String(500), nullable=True)
    company_address_number = Column(String(20), nullable=True)
    company_address_complement = Column(String(255), nullable=True)
    company_address_district = Column(String(255), nullable=True)
    company_address_city = Column(String(255), nullable=True)
    company_address_state = Column(String(2), nullable=True)
    company_address_zip = Column(String(10), nullable=True)
    capital_social = Column(Numeric(15, 2), nullable=True)
    company_size = Column(String(100), nullable=True)
    legal_nature = Column(String(255), nullable=True)
    company_phone = Column(String(50), nullable=True)
    company_email = Column(String(255), nullable=True)
    company_status = Column(String(50), nullable=True)
    company_opened_at = Column(String(20), nullable=True)
    is_simples_nacional = Column(Boolean, nullable=True)
    is_mei = Column(Boolean, nullable=True)

    # Extended CNPJ data (from BrasilAPI)
    qsa_partners = Column(JSON, nullable=True)
    cnaes_secundarios = Column(JSON, nullable=True)
    company_address_type = Column(String(50), nullable=True)
    is_headquarters = Column(Boolean, nullable=True)
    ibge_code = Column(String(10), nullable=True)
    regime_tributario = Column(String(100), nullable=True)
    simples_desde = Column(String(20), nullable=True)
    simples_excluido_em = Column(String(20), nullable=True)
    main_partner_name = Column(String(500), nullable=True)
    main_partner_qualification = Column(String(255), nullable=True)

    # Custom branding (White Label plan feature)
    logo_url = Column(String(500), nullable=True)  # S3 key or URL for org's custom logo

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    memberships = relationship("OrgMembership", back_populates="organization", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="organization", uselist=False, foreign_keys="[Subscription.organization_id]")
    invitations = relationship("OrgInvitation", back_populates="organization", cascade="all, delete-orphan")
    bank_accounts = relationship("OrgBankAccount", back_populates="organization", cascade="all, delete-orphan")
    initial_balances = relationship("OrgInitialBalance", back_populates="organization", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Organization(id={self.id}, name='{self.company_name}', cnpj='{self.cnpj}')>"


class OrgMembership(Base):
    """
    Organization membership table
    Links users to organizations with roles. A user can belong to multiple orgs.
    Each org has exactly one 'owner' membership.
    """

    __tablename__ = "org_memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # owner/admin/accountant/bookkeeper/viewer/api_user

    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_org"),
        Index("idx_org_membership_org_active", "organization_id", "is_active"),
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="memberships")
    organization = relationship("Organization", back_populates="memberships")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])

    def __repr__(self):
        return f"<OrgMembership(user_id={self.user_id}, org_id={self.organization_id}, role='{self.role}')>"


class OrgInvitation(Base):
    """
    Cross-org invitation table
    For inviting existing users to join another organization.
    Requires approval (user clicks accept link in email).
    """

    __tablename__ = "org_invitations"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    inviter_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # Set if invitee already has an account
    target_email = Column(String(255), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="viewer")
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)

    # Status
    accepted_at = Column(DateTime, nullable=True)
    declined_at = Column(DateTime, nullable=True)
    is_cancelled = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="invitations")
    inviter = relationship("User", foreign_keys=[inviter_user_id])
    target_user = relationship("User", foreign_keys=[target_user_id])

    @property
    def is_valid(self) -> bool:
        """Check if invitation is still valid"""
        return (
            not self.is_cancelled
            and self.accepted_at is None
            and self.declined_at is None
            and self.expires_at > datetime.utcnow()
        )

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.utcnow()

    def __repr__(self):
        return f"<OrgInvitation(id={self.id}, org_id={self.organization_id}, email='{self.target_email}')>"


class User(Base):
    """
    User table
    Stores user account information
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # Authentication
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    # Profile information
    full_name = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=False)
    cnpj = Column(String(50), nullable=False, unique=True, index=True)  # Brazilian company tax ID (XX.XXX.XXX/XXXX-XX), increased to handle migration duplicates

    # Company data (auto-filled from CNPJ lookup)
    trade_name = Column(String(255), nullable=True)  # Nome fantasia
    cnae_code = Column(String(20), nullable=True)  # CNAE principal code (e.g. "62.01-5-01")
    cnae_description = Column(String(500), nullable=True)  # CNAE description
    company_address_street = Column(String(500), nullable=True)  # Logradouro
    company_address_number = Column(String(20), nullable=True)  # Número
    company_address_complement = Column(String(255), nullable=True)  # Complemento
    company_address_district = Column(String(255), nullable=True)  # Bairro
    company_address_city = Column(String(255), nullable=True)  # Município
    company_address_state = Column(String(2), nullable=True)  # UF
    company_address_zip = Column(String(10), nullable=True)  # CEP
    capital_social = Column(Numeric(15, 2), nullable=True)  # Capital social
    company_size = Column(String(100), nullable=True)  # Porte (ME, EPP, etc.)
    legal_nature = Column(String(255), nullable=True)  # Natureza jurídica
    company_phone = Column(String(50), nullable=True)  # Telefone principal
    company_email = Column(String(255), nullable=True)  # Email comercial
    company_status = Column(String(50), nullable=True)  # Situação cadastral (Ativa, Baixada, etc.)
    company_opened_at = Column(String(20), nullable=True)  # Data de abertura
    is_simples_nacional = Column(Boolean, nullable=True)  # Optante pelo Simples Nacional
    is_mei = Column(Boolean, nullable=True)  # Microempreendedor Individual

    # Additional company data (from BrasilAPI full response)
    qsa_partners = Column(JSON, nullable=True)  # QSA partners array: [{nome, qual, data_entrada}, ...]
    cnaes_secundarios = Column(JSON, nullable=True)  # Secondary CNAEs array: [{codigo, descricao}, ...]
    company_address_type = Column(String(50), nullable=True)  # Tipo de logradouro (Rua, Avenida, etc.)
    is_headquarters = Column(Boolean, nullable=True)  # True = Matriz, False = Filial
    ibge_code = Column(String(10), nullable=True)  # Código IBGE do município
    regime_tributario = Column(String(100), nullable=True)  # Regime tributário (1=MEI, 2=Simples, 3=Lucro Presumido/Real)
    simples_desde = Column(String(20), nullable=True)  # Data de opção pelo Simples Nacional
    simples_excluido_em = Column(String(20), nullable=True)  # Data de exclusão do Simples Nacional
    main_partner_name = Column(String(500), nullable=True)  # Sócio-administrador principal (pre-filled for user validation)
    main_partner_qualification = Column(String(255), nullable=True)  # Qualificação do sócio principal

    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_admin = Column(
        Boolean, default=False, nullable=False, index=True
    )  # Admin role flag
    email_verified_at = Column(DateTime, nullable=True)
    email_verification_token = Column(String(255), nullable=True, index=True)
    email_verification_token_created_at = Column(DateTime, nullable=True)  # For 24h expiry

    # Trial management (managed on our side, not Stripe)
    trial_end_date = Column(DateTime, nullable=True)  # When free trial ends

    # Multi-organization support
    active_org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)  # Currently active organization

    # Team management (legacy fields — kept for backward compatibility, deprecated)
    role = Column(String(20), default="owner", nullable=False, index=True)  # Overwritten per-request from OrgMembership
    parent_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # DEPRECATED: use OrgMembership
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # DEPRECATED: use OrgMembership.invited_by_user_id
    invited_at = Column(DateTime, nullable=True)  # DEPRECATED

    # Multi-Factor Authentication (MFA)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_method = Column(String(20), nullable=True)  # 'totp' (Google Authenticator) or 'email'
    mfa_secret = Column(String(255), nullable=True)  # TOTP secret (encrypted)
    mfa_backup_codes = Column(Text, nullable=True)  # JSON array of backup codes (encrypted)
    mfa_enabled_at = Column(DateTime, nullable=True)  # When MFA was enabled

    # Legal Compliance (LGPD / GDPR)
    agreed_to_terms = Column(Boolean, default=False, nullable=False)  # Agreed to Terms of Service
    agreed_to_terms_at = Column(DateTime, nullable=True)  # When user agreed to terms
    agreed_to_privacy = Column(Boolean, default=False, nullable=False)  # Agreed to Privacy Policy
    agreed_to_privacy_at = Column(DateTime, nullable=True)  # When user agreed to privacy policy

    # User Preferences
    theme_preference = Column(String(20), default="system", nullable=False)  # 'light', 'dark', 'system'
    font_size_mobile = Column(String(10), default="medium", nullable=False)  # 'small', 'medium', 'large'
    font_size_desktop = Column(String(10), default="medium", nullable=False)  # 'small', 'medium', 'large'
    report_tab_order = Column(String(100), default="dre,balanco,fluxo,indicadores", nullable=False)  # comma-separated tab order

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login = Column(DateTime, nullable=True, index=True)  # Track last login for activity monitoring

    # Relationships
    documents = relationship("Document", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")
    password_resets = relationship("PasswordReset", back_populates="user")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    claims = relationship("UserClaim", foreign_keys="[UserClaim.user_id]", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")

    # Organization relationships
    memberships = relationship("OrgMembership", foreign_keys="[OrgMembership.user_id]", back_populates="user", cascade="all, delete-orphan")
    active_organization = relationship("Organization", foreign_keys=[active_org_id])

    # Team relationships (legacy — kept for backward compat)
    team_members = relationship("User", foreign_keys=[parent_user_id], backref="super_admin", remote_side=[id])
    invited_by = relationship("User", foreign_keys=[invited_by_user_id], remote_side=[id])

    def __repr__(self):
        return (
            f"<User(id={self.id}, email='{self.email}', company='{self.company_name}')>"
        )


class UserSession(Base):
    """
    User Session table
    Tracks active user sessions for device management and account sharing prevention
    """

    __tablename__ = "user_sessions"

    id = Column(String(64), primary_key=True)  # Session token (JWT jti or UUID)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Device information
    device_type = Column(String(20), nullable=False)  # mobile, desktop, tablet
    device_os = Column(String(50), nullable=True)  # Windows, Linux, macOS, iOS, Android
    device_name = Column(String(255), nullable=True)  # Browser + OS from user agent
    browser = Column(String(50), nullable=True)  # Chrome, Firefox, Safari, Edge

    # Network information
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6

    # Session lifecycle
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Trusted device (skip MFA for 30 days)
    is_trusted_device = Column(Boolean, default=False, nullable=False)
    device_fingerprint = Column(String(255), nullable=True)  # Hash of user agent + IP
    trusted_until = Column(DateTime, nullable=True)  # When trust expires

    # Relationships
    user = relationship("User", back_populates="sessions")

    # Indexes for fast lookups
    __table_args__ = (
        Index("ix_user_sessions_user_active", "user_id", "is_active"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    @property
    def is_expired(self) -> bool:
        """Check if session has expired"""
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if session is valid (active and not expired)"""
        return self.is_active and not self.is_expired

    def __repr__(self):
        return f"<UserSession(id={self.id}, user_id={self.user_id}, device={self.device_type})>"


class UserClaim(Base):
    """
    User Claims table
    Stores custom claims/permissions for users (overrides role defaults)
    """

    __tablename__ = "user_claims"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Claim name (e.g., "documents.delete", "admin.dashboard")
    claim_type = Column(String(100), nullable=False, index=True)

    # Claim value (usually "true", but can be JSON for complex claims)
    claim_value = Column(String(255), nullable=False, default="true")

    # Metadata
    granted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True, comment="Optional expiration")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="claims")
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])

    # Indexes
    __table_args__ = (
        Index("ix_user_claims_user_claim", "user_id", "claim_type", unique=True),
    )

    @property
    def is_expired(self) -> bool:
        """Check if claim has expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if claim is valid (not expired)"""
        return not self.is_expired

    def __repr__(self):
        return f"<UserClaim(user_id={self.user_id}, claim='{self.claim_type}')>"


class APIKey(Base):
    """
    API Keys table
    Allows users to generate API keys for programmatic access
    """

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)

    # API Key components (format: dre_keyid_secret)
    # key_id: Visible identifier (first 32 chars: "dre_abcd1234...")
    # key_hash: SHA-256 hash of the full secret part
    key_id = Column(String(32), unique=True, nullable=False, index=True, comment="First part of API key (visible)")
    key_hash = Column(String(128), nullable=False, comment="Hashed secret part")

    # Metadata
    name = Column(String(100), nullable=False, comment="User-friendly name")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Permissions (JSON array of permission strings)
    # Example: ["documents.read", "documents.write", "reports.view"]
    # If null/empty, inherits from user's role permissions
    permissions = Column(Text, nullable=True, comment="Custom permissions JSON")

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, comment="Optional expiration date")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="api_keys")

    # Indexes for fast lookups
    __table_args__ = (
        Index("ix_api_keys_user_active", "user_id", "is_active"),
    )

    @property
    def is_expired(self) -> bool:
        """Check if API key has expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if API key is valid (active and not expired)"""
        return self.is_active and not self.is_expired

    def __repr__(self):
        return f"<APIKey(id={self.id}, name='{self.name}', user_id={self.user_id})>"


class SubscriptionStatus(str, enum.Enum):
    """Subscription status enum"""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"


class Subscription(Base):
    """
    Subscription table
    Stores user subscription information from Stripe
    """

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_subscription_user_org"),
    )

    # Foreign keys
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )  # Per-org billing (nullable for backward compat during migration)

    # Stripe IDs
    stripe_customer_id = Column(String(255), nullable=False, index=True)
    stripe_subscription_id = Column(String(255), nullable=True, index=True)
    stripe_price_id = Column(String(255), nullable=True)

    # Subscription status
    status = Column(
        SQLEnum(SubscriptionStatus),
        default=SubscriptionStatus.TRIALING,
        nullable=False,
        index=True,
    )

    # Trial information
    trial_start = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)

    # Billing period
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)

    # Cancellation
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    canceled_at = Column(DateTime, nullable=True)

    # Team management (multi-user support)
    max_users = Column(Integer, default=1, nullable=False)  # Maximum users allowed on this plan

    # Plan reference (source of truth for features)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True, index=True)
    plan = relationship("Plan")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    organization = relationship("Organization", back_populates="subscription", foreign_keys=[organization_id])

    @property
    def is_active(self) -> bool:
        """Check if subscription is active (including trial)"""
        return self.status in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]

    def __repr__(self):
        return f"<Subscription(id={self.id}, user_id={self.user_id}, org_id={self.organization_id}, status='{self.status}')>"


class Plan(Base):
    """
    Plan table — Single source of truth for subscription tiers.

    Plans are database-driven and fully dynamic:
    - Stakeholders can rename plans, change features, toggle visibility
    - Feature gating uses the `features` JSON column (claims-based)
    - No hardcoded plan names or feature flags in code
    """

    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    max_users = Column(Integer, default=1, nullable=False)
    price_monthly_brl = Column(Integer, default=0, nullable=False)
    stripe_price_id = Column(String(255), nullable=True, unique=True, index=True)
    features = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    is_highlighted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self):
        return f"<Plan(id={self.id}, slug='{self.slug}', display_name='{self.display_name}')>"


class PasswordReset(Base):
    """
    Password reset tokens table
    Stores password reset tokens with expiration
    """

    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Token
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    user = relationship("User", back_populates="password_resets")

    def __repr__(self):
        return (
            f"<PasswordReset(id={self.id}, user_id={self.user_id}, used={self.used})>"
        )


class TeamInvitation(Base):
    """
    Team invitation table
    Stores invitations sent by super admins to invite team members
    """

    __tablename__ = "team_invitations"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign key - who sent the invitation
    inviter_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Invitation details
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    role = Column(String(20), nullable=False, default="viewer", comment="Role to assign when invitation is accepted")
    expires_at = Column(DateTime, nullable=False)

    # Status
    accepted_at = Column(DateTime, nullable=True)
    is_cancelled = Column(Boolean, default=False, nullable=False)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    inviter = relationship("User", foreign_keys=[inviter_user_id])

    @property
    def is_valid(self) -> bool:
        """Check if invitation is still valid"""
        return (
            not self.is_cancelled
            and self.accepted_at is None
            and self.expires_at > datetime.utcnow()
        )

    @property
    def is_expired(self) -> bool:
        """Check if invitation has expired"""
        return self.expires_at <= datetime.utcnow()

    def __repr__(self):
        return (
            f"<TeamInvitation(id={self.id}, email='{self.email}', valid={self.is_valid})>"
        )


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully")


def get_db():
    """
    Dependency for FastAPI to get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChartOfAccountsEntry(Base):
    """
    Chart of Accounts (Plano de Contas)
    Customizable per user with default Brazilian accounts
    """

    __tablename__ = "chart_of_accounts"

    id = Column(Integer, primary_key=True, index=True)

    # User reference (multi-tenant)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Account identification
    account_code = Column(String(20), nullable=False, index=True)  # e.g., "1.01.001"
    account_name = Column(String(255), nullable=False)  # e.g., "Caixa"

    # Account type and nature
    account_type = Column(
        String(50), nullable=False, index=True
    )  # ativo_circulante, passivo_circulante, etc.
    account_nature = Column(String(10), nullable=False)  # debit or credit

    # Description
    description = Column(Text, nullable=True)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_system_account = Column(
        Boolean, default=False, nullable=False
    )  # Cannot be deleted if True

    # Current balance (cached for performance)
    current_balance = Column(
        Integer, default=0, nullable=False
    )  # Stored in cents to avoid decimal issues

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Composite index for user + code uniqueness
    __table_args__ = (
        Index("idx_user_account_code", "user_id", "account_code", unique=True),
        Index("idx_user_account_type", "user_id", "account_type"),
    )

    # Relationships
    user = relationship("User", backref="chart_of_accounts")
    journal_entry_lines = relationship("JournalEntryLine", back_populates="account")

    def __repr__(self):
        return f"<ChartOfAccountsEntry(code={self.account_code}, name='{self.account_name}')>"


class JournalEntry(Base):
    """
    Journal Entry (Lançamento Contábil)
    Double-entry bookkeeping transactions
    """

    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)

    # User reference (multi-tenant)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Entry metadata
    entry_date = Column(
        DateTime, nullable=False, index=True
    )  # Date of the economic event
    entry_number = Column(String(50), nullable=True)  # Optional sequential number
    description = Column(Text, nullable=False)  # Description of the transaction

    # Source tracking
    source_type = Column(
        String(50), nullable=True, index=True
    )  # 'automatic', 'manual', 'adjustment', 'closing'
    source_document_id = Column(
        Integer, ForeignKey("documents.id"), nullable=True, index=True
    )  # Link to document if auto-generated

    # Status
    is_posted = Column(Boolean, default=True, nullable=False)  # False for draft entries
    is_reversed = Column(
        Boolean, default=False, nullable=False
    )  # True if entry was reversed
    reversal_of_entry_id = Column(
        Integer, ForeignKey("journal_entries.id"), nullable=True
    )  # Link to original entry if this is a reversal

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=True)  # User email or 'system'
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Composite indexes
    __table_args__ = (
        Index("idx_user_entry_date", "user_id", "entry_date"),
        Index("idx_user_source_type", "user_id", "source_type"),
    )

    # Relationships
    user = relationship("User", backref="journal_entries")
    source_document = relationship("Document", backref="journal_entries")
    lines = relationship(
        "JournalEntryLine", back_populates="journal_entry", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<JournalEntry(id={self.id}, date={self.entry_date}, description='{self.description[:30]}')>"


class JournalEntryLine(Base):
    """
    Journal Entry Line (Linha do Lançamento)
    Individual debit or credit line in a journal entry
    """

    __tablename__ = "journal_entry_lines"

    id = Column(Integer, primary_key=True, index=True)

    # Parent journal entry
    journal_entry_id = Column(
        Integer, ForeignKey("journal_entries.id"), nullable=False, index=True
    )

    # Account reference
    account_id = Column(
        Integer, ForeignKey("chart_of_accounts.id"), nullable=False, index=True
    )

    # Debit or Credit
    debit_amount = Column(Integer, default=0, nullable=False)  # Stored in cents
    credit_amount = Column(Integer, default=0, nullable=False)  # Stored in cents

    # Description (optional, can override parent description)
    description = Column(Text, nullable=True)

    # Line order within entry
    line_order = Column(Integer, default=0, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Composite indexes
    __table_args__ = (
        Index("idx_entry_line_order", "journal_entry_id", "line_order"),
        Index("idx_account_entry", "account_id", "journal_entry_id"),
    )

    # Relationships
    journal_entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("ChartOfAccountsEntry", back_populates="journal_entry_lines")

    def __repr__(self):
        amount = self.debit_amount if self.debit_amount > 0 else self.credit_amount
        type_str = "D" if self.debit_amount > 0 else "C"
        return f"<JournalEntryLine({type_str}: {amount/100:.2f})>"


class AuditLog(Base):
    """
    Audit trail for all document changes
    Tracks who changed what, when, and why for compliance
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # User who made the change
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Document reference (if applicable) - NO foreign key to preserve audit history after deletion
    # Document name is preserved in changes_summary field
    document_id = Column(Integer, nullable=True, index=True)

    # Action details
    action = Column(String(50), nullable=False, index=True)  # create, update, delete
    entity_type = Column(String(50), nullable=False)  # document, transaction, etc
    entity_id = Column(Integer, nullable=True)

    # Change tracking
    before_value = Column(Text, nullable=True)  # JSON string of old value
    after_value = Column(Text, nullable=True)  # JSON string of new value
    changes_summary = Column(String(500), nullable=True)  # Human-readable summary

    # Request context
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Composite indexes
    __table_args__ = (
        Index("idx_audit_user_document", "user_id", "document_id"),
    )

    # Relationships
    user = relationship("User", backref="audit_logs")
    # No relationship to Document - document_id is just a reference (no FK)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action='{self.action}', user_id={self.user_id})>"


class Client(Base):
    """
    Clients/Customers table
    Track companies or people who give/receive money
    """

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)

    # User reference (multi-tenant)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Client information
    name = Column(String(255), nullable=False, index=True)
    legal_name = Column(String(255), nullable=True)
    tax_id = Column(String(20), nullable=True, index=True)  # CNPJ/CPF
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)

    # Client type
    client_type = Column(
        String(20), nullable=False, default="customer", index=True
    )  # customer, supplier, both

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Notes
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Composite index for user + name uniqueness
    __table_args__ = (
        Index("idx_user_client_name", "user_id", "name"),
        Index("idx_user_tax_id", "user_id", "tax_id"),
    )

    # Relationships
    user = relationship("User", backref="clients")

    def __repr__(self):
        return f"<Client(id={self.id}, name='{self.name}', type='{self.client_type}')>"


class KnownItem(Base):
    """
    Known Items table
    Tracks recurring items across documents for an organization.
    Used to inject context into AI prompts for better categorization.
    """

    __tablename__ = "known_items"

    id = Column(Integer, primary_key=True, index=True)

    # Organization owner's user_id (shared across team members)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Item name, UPPERCASE normalized, stripped of quantity prefixes
    name = Column(String(255), nullable=False)

    # User-editable "Known As" display label (e.g., "Controle de Pragas")
    alias = Column(String(255), nullable=True)

    # DRE V2 category key
    category = Column(String(100), nullable=True)

    # income or expense
    transaction_type = Column(String(20), nullable=True)

    # Usage tracking
    times_appeared = Column(Integer, default=1, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Unique constraint: one entry per item name per organization
    __table_args__ = (
        Index("ix_known_items_user_name", "user_id", "name", unique=True),
    )

    # Relationships
    user = relationship("User", backref="known_items")

    def __repr__(self):
        return f"<KnownItem(id={self.id}, name='{self.name}', alias='{self.alias}', appeared={self.times_appeared})>"


class OrgBankAccount(Base):
    """
    Bank accounts belonging to an organization.
    Used for tracking company bank details and initial balances.
    Bank codes/names can be looked up via BrasilAPI /banks/v1.
    """

    __tablename__ = "org_bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Bank identification
    bank_code = Column(String(10), nullable=False)        # e.g. "001"
    bank_name = Column(String(255), nullable=False)        # e.g. "Banco do Brasil S.A."
    agency = Column(String(20), nullable=False)            # e.g. "1234-5"
    account_number = Column(String(30), nullable=False)    # e.g. "12345-6"
    account_type = Column(String(30), nullable=False, default="checking")  # checking/savings/investment
    account_nickname = Column(String(100), nullable=True)  # e.g. "Conta Principal"

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="bank_accounts")

    def __repr__(self):
        return f"<OrgBankAccount(id={self.id}, bank={self.bank_code}, account={self.account_number})>"


class OrgInitialBalance(Base):
    """
    Initial balance sheet data for an organization.
    Collected via the multi-step questionnaire wizard.
    Values are added to calculated balances from journal entries/documents.
    One record per org per reference date.
    """

    __tablename__ = "org_initial_balances"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    reference_date = Column(Date, nullable=False)

    # === ATIVO CIRCULANTE (Current Assets) ===
    cash_and_equivalents = Column(Numeric(15, 2), default=0, server_default="0")
    short_term_investments = Column(Numeric(15, 2), default=0, server_default="0")
    accounts_receivable = Column(Numeric(15, 2), default=0, server_default="0")
    inventory = Column(Numeric(15, 2), default=0, server_default="0")
    prepaid_expenses = Column(Numeric(15, 2), default=0, server_default="0")

    # === ATIVO NÃO CIRCULANTE (Non-Current Assets) ===
    long_term_receivables = Column(Numeric(15, 2), default=0, server_default="0")
    long_term_investments = Column(Numeric(15, 2), default=0, server_default="0")

    # === IMOBILIZADO (Fixed Assets - individual items) ===
    fixed_assets_land = Column(Numeric(15, 2), default=0, server_default="0")
    fixed_assets_buildings = Column(Numeric(15, 2), default=0, server_default="0")
    fixed_assets_machinery = Column(Numeric(15, 2), default=0, server_default="0")
    fixed_assets_vehicles = Column(Numeric(15, 2), default=0, server_default="0")
    fixed_assets_furniture = Column(Numeric(15, 2), default=0, server_default="0")
    fixed_assets_computers = Column(Numeric(15, 2), default=0, server_default="0")
    fixed_assets_other = Column(Numeric(15, 2), default=0, server_default="0")
    accumulated_depreciation = Column(Numeric(15, 2), default=0, server_default="0")

    # === INTANGÍVEL (Intangible Assets) ===
    intangible_assets = Column(Numeric(15, 2), default=0, server_default="0")
    accumulated_amortization = Column(Numeric(15, 2), default=0, server_default="0")

    # === PASSIVO CIRCULANTE (Current Liabilities) ===
    suppliers_payable = Column(Numeric(15, 2), default=0, server_default="0")
    short_term_loans = Column(Numeric(15, 2), default=0, server_default="0")
    labor_obligations = Column(Numeric(15, 2), default=0, server_default="0")
    tax_obligations = Column(Numeric(15, 2), default=0, server_default="0")
    other_current_liabilities = Column(Numeric(15, 2), default=0, server_default="0")

    # === PASSIVO NÃO CIRCULANTE (Non-Current Liabilities) ===
    long_term_loans = Column(Numeric(15, 2), default=0, server_default="0")
    long_term_financing = Column(Numeric(15, 2), default=0, server_default="0")
    provisions_long_term = Column(Numeric(15, 2), default=0, server_default="0")        # Provisões (LP)
    deferred_tax_liabilities = Column(Numeric(15, 2), default=0, server_default="0")    # Passivos Fiscais Diferidos

    # === PATRIMÔNIO LÍQUIDO (Equity - user inputs) ===
    reserves_and_adjustments = Column(Numeric(15, 2), default=0, server_default="0")    # Reservas e Ajustes

    # Bank account balances: [{bank_account_id: int, balance: float}, ...]
    bank_account_balances = Column(JSON, nullable=True)

    # Metadata
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Unique: one initial balance per org per date
    __table_args__ = (
        UniqueConstraint('organization_id', 'reference_date', name='uq_org_initial_balance'),
    )

    # Relationships
    organization = relationship("Organization", back_populates="initial_balances")

    def __repr__(self):
        return f"<OrgInitialBalance(id={self.id}, org={self.organization_id}, date={self.reference_date}, completed={self.is_completed})>"


if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Done!")
