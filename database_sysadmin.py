"""
System Admin Database Models

Separate tables for platform operators (business team) to manage the entire SaaS.
Completely isolated from customer users for security.
"""

from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, ForeignKey,
    JSON, Numeric, Date, Index, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from database import Base
import enum


class SystemAdminPermission(str, enum.Enum):
    """Granular permissions for system administrators"""
    # User management
    VIEW_ALL_USERS = "view_all_users"
    IMPERSONATE_USERS = "impersonate_users"
    MANAGE_USERS = "manage_users"

    # Support
    VIEW_TICKETS = "view_tickets"
    MANAGE_TICKETS = "manage_tickets"

    # System monitoring
    VIEW_METRICS = "view_metrics"
    VIEW_ERRORS = "view_errors"
    EXPORT_DATA = "export_data"

    # Configuration
    MANAGE_BILLING = "manage_billing"
    MANAGE_SYSTEM_CONFIG = "manage_system_config"

    # Danger zone
    DELETE_USERS = "delete_users"
    MODIFY_SUBSCRIPTIONS = "modify_subscriptions"


class SystemAdmin(Base):
    """
    Platform operators (you, partners, employees)

    Completely separate from customer User accounts.
    Can authenticate via password OR MS Entra/SSO (future).
    """
    __tablename__ = "system_admins"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)

    # Password auth (local accounts)
    hashed_password = Column(String(255), nullable=True)  # Nullable for SSO-only accounts

    # SSO/External auth (MS Entra, Okta, etc.)
    external_auth_provider = Column(String(50), nullable=True)  # "ms_entra", "okta", "google"
    external_user_id = Column(String(255), nullable=True, unique=True)  # Provider's user ID
    external_metadata = Column(JSON, nullable=True)  # Additional SSO data

    # Permissions (JSON array of permission strings)
    permissions = Column(JSON, nullable=False, default=list)
    # Example: ["view_all_users", "impersonate_users", "view_metrics"]

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_super_admin = Column(Boolean, default=False, nullable=False)  # Full access

    # Activity tracking
    last_login = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    login_count = Column(Integer, default=0, nullable=False)

    # MFA (required for all sysadmins)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret = Column(String(255), nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_admin_id = Column(Integer, ForeignKey('system_admins.id'), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    created_by = relationship("SystemAdmin", remote_side=[id], foreign_keys=[created_by_admin_id])
    impersonation_sessions = relationship("ImpersonationSession", back_populates="sysadmin")
    audit_logs = relationship("SystemAdminAuditLog", back_populates="sysadmin")

    def has_permission(self, permission: SystemAdminPermission) -> bool:
        """Check if admin has specific permission"""
        if self.is_super_admin:
            return True
        return permission.value in (self.permissions or [])


class ImpersonationSession(Base):
    """
    Track when sysadmins impersonate customers for support/debugging

    Critical for compliance and audit trail.
    """
    __tablename__ = "impersonation_sessions"

    id = Column(Integer, primary_key=True, index=True)

    # Who is impersonating
    sysadmin_id = Column(Integer, ForeignKey('system_admins.id'), nullable=False, index=True)
    sysadmin_email = Column(String(255), nullable=False)  # Denormalized for fast lookup

    # Target customer
    target_user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    target_user_email = Column(String(255), nullable=False)

    # Justification (required)
    reason = Column(Text, nullable=False)
    # Examples: "Debug upload error - Ticket #123", "Customer requested assistance"

    # Session tracking
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Security
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Actions taken during session (append-only log)
    actions_taken = Column(JSON, default=list, nullable=False)
    # Example: [{"timestamp": "2026-01-29T10:00:00", "action": "viewed_documents", "details": {...}}]

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    auto_expire_at = Column(DateTime, nullable=False)  # Max 1 hour from start

    # Relationships
    sysadmin = relationship("SystemAdmin", back_populates="impersonation_sessions")

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_impersonation_sysadmin_date', 'sysadmin_id', 'started_at'),
        Index('idx_impersonation_target_date', 'target_user_id', 'started_at'),
        Index('idx_impersonation_active', 'is_active', 'auto_expire_at'),
    )


class SystemAdminAuditLog(Base):
    """
    Audit trail for ALL sysadmin actions

    Immutable log - never delete, only append.
    """
    __tablename__ = "system_admin_audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Who did it
    sysadmin_id = Column(Integer, ForeignKey('system_admins.id'), nullable=False, index=True)
    sysadmin_email = Column(String(255), nullable=False)

    # What they did
    action = Column(String(100), nullable=False, index=True)
    # Examples: "login", "impersonate_user", "view_errors", "update_subscription"

    entity_type = Column(String(50), nullable=True)  # "user", "ticket", "subscription"
    entity_id = Column(Integer, nullable=True)

    # Context
    description = Column(Text, nullable=True)
    context_data = Column(JSON, nullable=True)  # Additional context (renamed from metadata)

    # Request details
    endpoint = Column(String(255), nullable=True)
    method = Column(String(10), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Impersonation context
    was_impersonating = Column(Boolean, default=False, nullable=False)
    impersonation_session_id = Column(Integer, ForeignKey('impersonation_sessions.id'), nullable=True)
    impersonated_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    sysadmin = relationship("SystemAdmin", back_populates="audit_logs")

    # Indexes for analytics
    __table_args__ = (
        Index('idx_sysadmin_audit_action_date', 'action', 'created_at'),
        Index('idx_sysadmin_audit_entity', 'entity_type', 'entity_id'),
        Index('idx_sysadmin_audit_impersonation', 'was_impersonating', 'created_at'),
    )


class ErrorLog(Base):
    """
    Comprehensive error tracking across the entire platform

    Automatically captured by global exception handler.
    """
    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Who encountered the error
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    user_email = Column(String(255), nullable=True)
    organization_id = Column(Integer, nullable=True, index=True)  # Parent user ID

    # Error details
    error_type = Column(String(100), nullable=False, index=True)  # Exception class name
    error_message = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=True)

    # Request context
    endpoint = Column(String(255), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)

    # Request data (sanitized - no passwords!)
    request_body = Column(JSON, nullable=True)
    request_headers = Column(JSON, nullable=True)
    query_params = Column(JSON, nullable=True)

    # Client info
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Performance
    response_time_ms = Column(Integer, nullable=True)

    # Resolution tracking
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_admin_id = Column(Integer, ForeignKey('system_admins.id'), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Linked to support ticket (no FK due to circular dependency)
    related_ticket_id = Column(Integer, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_error_user_date', 'user_id', 'created_at'),
        Index('idx_error_endpoint_date', 'endpoint', 'created_at'),
        Index('idx_error_type_date', 'error_type', 'created_at'),
        Index('idx_error_org_date', 'organization_id', 'created_at'),
        Index('idx_error_unresolved', 'is_resolved', 'created_at'),
    )


class SupportTicket(Base):
    """
    Customer support ticket system

    Auto-created from contact forms, can also be manually created.
    """
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, nullable=False, index=True)
    # Format: TKT-2026-00123

    # Customer
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    user_email = Column(String(255), nullable=True)  # For non-authenticated contacts
    user_name = Column(String(255), nullable=True)

    # Ticket details
    subject = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)

    # Classification
    status = Column(
        SQLEnum('open', 'assigned', 'in_progress', 'waiting_customer', 'resolved', 'closed', name='ticket_status'),
        default='open',
        nullable=False,
        index=True
    )
    priority = Column(
        SQLEnum('low', 'medium', 'high', 'urgent', name='ticket_priority'),
        default='medium',
        nullable=False,
        index=True
    )
    category = Column(String(50), nullable=True, index=True)
    # "billing", "technical", "feature_request", "bug", "question"

    # Assignment
    assigned_to_admin_id = Column(Integer, ForeignKey('system_admins.id'), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)

    # SLA tracking
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    first_response_at = Column(DateTime, nullable=True)  # First admin reply
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # Metrics
    response_time_minutes = Column(Integer, nullable=True)  # first_response - created
    resolution_time_hours = Column(Integer, nullable=True)  # resolved - created

    # Linked resources (error_log FK removed due to circular dependency)
    related_error_log_id = Column(Integer, nullable=True)
    related_document_id = Column(Integer, ForeignKey('documents.id'), nullable=True)

    # Metadata
    tags = Column(JSON, default=list, nullable=False)  # ["urgent", "vip_customer", "bug"]
    custom_fields = Column(JSON, nullable=True)

    # Relationships
    messages = relationship("TicketMessage", back_populates="ticket", order_by="TicketMessage.created_at")
    assigned_to = relationship("SystemAdmin")

    # Indexes
    __table_args__ = (
        Index('idx_ticket_status_priority', 'status', 'priority'),
        Index('idx_ticket_assigned', 'assigned_to_admin_id', 'status'),
        Index('idx_ticket_user', 'user_id', 'status'),
    )


class TicketMessage(Base):
    """Messages/replies within a support ticket"""
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey('support_tickets.id'), nullable=False, index=True)

    # Author
    author_type = Column(String(20), nullable=False)  # "customer", "sysadmin"
    author_id = Column(Integer, nullable=False)  # User ID or SystemAdmin ID
    author_name = Column(String(255), nullable=False)
    author_email = Column(String(255), nullable=False)

    # Message
    message = Column(Text, nullable=False)
    is_internal_note = Column(Boolean, default=False, nullable=False)  # Only sysadmins see

    # Attachments
    attachments = Column(JSON, default=list, nullable=False)
    # [{"filename": "screenshot.png", "s3_key": "...", "size": 12345}]

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    edited_at = Column(DateTime, nullable=True)

    # Relationships
    ticket = relationship("SupportTicket", back_populates="messages")


class DailyMetrics(Base):
    """
    Pre-aggregated daily metrics for fast dashboard loading

    Background job calculates these once per day.
    """
    __tablename__ = "daily_metrics"

    date = Column(Date, primary_key=True, index=True)

    # User metrics
    active_users_24h = Column(Integer, default=0, nullable=False)
    active_users_7d = Column(Integer, default=0, nullable=False)
    new_registrations = Column(Integer, default=0, nullable=False)
    trial_conversions = Column(Integer, default=0, nullable=False)
    churned_users = Column(Integer, default=0, nullable=False)
    total_users = Column(Integer, default=0, nullable=False)

    # Usage metrics
    documents_processed = Column(Integer, default=0, nullable=False)
    api_calls_total = Column(Integer, default=0, nullable=False)
    ai_tokens_used = Column(Integer, default=0, nullable=False)
    storage_bytes_used = Column(Numeric(20, 0), default=0, nullable=False)

    # Revenue metrics (in cents to avoid floating point issues)
    mrr_cents = Column(Numeric(15, 0), default=0, nullable=False)  # Monthly Recurring Revenue
    arr_cents = Column(Numeric(15, 0), default=0, nullable=False)  # Annual Recurring Revenue
    new_revenue_cents = Column(Numeric(15, 0), default=0, nullable=False)
    churned_revenue_cents = Column(Numeric(15, 0), default=0, nullable=False)

    # System health
    errors_count = Column(Integer, default=0, nullable=False)
    avg_response_time_ms = Column(Integer, default=0, nullable=False)
    p95_response_time_ms = Column(Integer, default=0, nullable=False)
    uptime_percentage = Column(Numeric(5, 2), default=100.00, nullable=False)

    # Support metrics
    tickets_created = Column(Integer, default=0, nullable=False)
    tickets_resolved = Column(Integer, default=0, nullable=False)
    avg_resolution_time_hours = Column(Numeric(10, 2), nullable=True)

    # Metadata
    calculated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    calculation_duration_seconds = Column(Integer, nullable=True)
