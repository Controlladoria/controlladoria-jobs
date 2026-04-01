"""
Configuration Management
Centralized settings for the application
"""

import os
from typing import List

import boto3
from pydantic import field_validator
from pydantic_settings import BaseSettings


def _load_ssm_parameters() -> None:
    """If AWS_SSM_PREFIX is set, fetch all params under that prefix and inject as env vars.
    In deployed envs (Lambda), SSM becomes the config source.
    Locally, AWS_SSM_PREFIX is not set, so .env / env vars are used instead."""
    prefix = os.environ.get("AWS_SSM_PREFIX")
    if not prefix:
        return

    region = os.environ.get("AWS_REGION", "us-east-2")
    ssm = boto3.client("ssm", region_name=region)

    paginator = ssm.get_paginator("get_parameters_by_path")
    for page in paginator.paginate(Path=prefix, WithDecryption=True):
        for param in page["Parameters"]:
            # /controlladoria/dev/worker/DATABASE_URL → DATABASE_URL
            env_name = param["Name"].removeprefix(prefix)
            os.environ.setdefault(env_name, param["Value"])


# Load SSM before pydantic reads env vars
_load_ssm_parameters()


class Settings(BaseSettings):
    """Application settings"""

    @field_validator("cors_origins", "trusted_proxy_ips", "sysadmin_allowed_emails", "allowed_file_extensions", "allowed_mime_types", mode="before")
    @classmethod
    def parse_comma_separated_list(cls, v):
        """Accept both JSON arrays and plain comma-separated strings for list fields."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return v  # Already JSON — let pydantic parse it
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # Environment
    environment: str = "development"
    debug: bool = True

    # API Configuration
    api_title: str = "ControlladorIA API"
    api_version: str = "0.4.0"
    api_description: str = "Sistema de Processamento de Documentos Financeiros"

    # Database
    database_url: str = (
        "sqlite:///./dresystem.db"  # Use PostgreSQL in production: postgresql://user:pass@host:5432/db
    )

    # AI Provider — comma-separated for multi-provider round-robin: "gemini,nova,openai"
    # All listed providers are co-primaries. Unlisted providers with keys are implicit failover.
    ai_provider: str = "gemini"

    # Gemini (Google) — primary
    gemini_api_key: str = ""
    gemini_api_keys: str = ""  # Comma-separated for round-robin: "key1,key2,key3"
    gemini_model: str = "gemini-flash-lite-latest"  # Auto-picks latest Flash Lite

    # Amazon Nova (via AWS Bedrock) — secondary
    # Uses IAM credentials (aws_access_key_id/aws_secret_access_key below), not API keys
    nova_model: str = "us.amazon.nova-lite-v2:0"  # Cross-region inference
    nova_region: str = "us-east-2"  # Bedrock region

    # OpenAI — tertiary fallback
    openai_api_key: str = ""
    openai_api_keys: str = ""  # Comma-separated for round-robin: "sk-key1,sk-key2"
    openai_model: str = "gpt-5.4-nano"  # Cheapest: $0.20/1M input, $1.25/1M output

    # AI Failover & Key Pool
    ai_failover_enabled: bool = True  # Auto-switch provider when all keys for primary fail
    ai_key_unhealthy_threshold: int = 3  # Consecutive errors before marking key unhealthy
    ai_key_recovery_seconds: int = 300  # Seconds before unhealthy key is retried (5 min)

    # AI Response Caching (requires Redis - disabled by default)
    enable_ai_cache: bool = False  # Enable when Redis is available
    ai_cache_ttl: int = 86400  # 24 hours (same document = same result)

    # AI Retry Configuration
    ai_max_retries: int = 3
    ai_retry_delay: int = 1  # seconds
    ai_timeout: int = 60  # seconds

    # Authentication (legacy API key)
    api_key: str = ""

    # JWT Authentication
    jwt_secret_key: str = ""  # Generate with: openssl rand -hex 32
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Encryption (MFA secrets, sensitive data)
    encryption_key: str = ""  # Optional: Separate Fernet key for data encryption (generates from jwt_secret_key if not provided)

    # Stripe
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""  # Legacy (treated as basic)
    stripe_price_id_basic: str = ""  # Basic plan (R$ 99/month)
    stripe_price_id_pro: str = ""  # Pro plan (R$ 249/month)
    stripe_price_id_max: str = ""  # Max plan (R$ 399/month)
    stripe_trial_days: int = 15
    stripe_success_url: str = "http://localhost:3000/dashboard"
    stripe_cancel_url: str = "http://localhost:3000/pricing"

    # Email (Resend API for password reset, transactional emails)
    resend_api_key: str = ""
    from_email: str = "ControlladorIA <noreply@controllad oria.com>"
    admin_email: str = "admin@controllad oria.com"  # Receive contact form notifications
    support_email: str = "suporte@controllad oria.com"  # Support contact for CNPJ conflicts
    frontend_url: str = "http://localhost:3000"  # For email links

    # AWS S3 (File Storage)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket_name: str = ""
    s3_endpoint_url: str = ""  # Optional: for S3-compatible services
    use_s3: bool = False  # Set to True to use S3 instead of local filesystem

    # AWS SQS (Document Processing Queue)
    sqs_document_queue_url: str = ""  # SQS queue URL for retry → reprocess flow

    # Redis (Caching & Celery Broker)
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 300  # Cache TTL in seconds (5 minutes default)
    redis_max_connections: int = 50

    # Celery (Background Tasks)
    celery_broker_url: str = ""  # Usually same as redis_url
    celery_result_backend: str = ""  # Usually same as redis_url
    celery_task_time_limit: int = 600  # 10 minutes max per task

    # File Upload
    max_upload_size: int = 30 * 1024 * 1024  # 30MB
    allowed_file_extensions: List[str] = [
        ".pdf",
        ".xlsx",
        ".xls",
        ".xml",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        # V2 additions (Item 2 - partner feedback)
        ".txt",
        ".doc",
        ".docx",
        ".ofc",
        ".ofx",
    ]
    allowed_mime_types: List[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/xml",
        "text/xml",
        "image/jpeg",
        "image/png",
        "image/webp",
        # V2 additions (Item 2 - partner feedback)
        "text/plain",                    # .txt
        "application/msword",            # .doc
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/x-ofx",             # .ofx
        "application/x-ofc",             # .ofc
    ]

    # SERPRO CNPJ API (official Receita Federal data)
    # Sign up at https://loja.serpro.gov.br/consulta-cnpj/product/consultacnpj
    # Free trial: 30 days / 3,000 queries. When configured, used as primary source.
    serpro_consumer_key: str = ""  # OAuth2 Consumer Key from SERPRO portal
    serpro_consumer_secret: str = ""  # OAuth2 Consumer Secret from SERPRO portal
    serpro_api_url: str = "https://gateway.apiserpro.serpro.gov.br/consulta-cnpj-df/v2"  # Production. Trial: replace -df with -df-trial

    # Validation Settings
    enable_cnpj_validation: bool = True  # Strict CNPJ validation for Nota Fiscal uploads (rejects if user CNPJ doesn't match document)

    # Rate Limiting
    rate_limit_enabled: bool = True
    upload_rate_limit: str = "60/minute"
    contact_rate_limit: str = "5/hour"

    # Document Retry Settings (nightly retry of failed documents)
    document_retry_enabled: bool = True  # Enable 2 AM retry of failed uploads
    document_retry_hour: int = 2  # Hour to run retry job (0-23, default: 2 AM)
    document_max_retries: int = 3  # Max retry attempts before giving up
    document_retry_max_age_days: int = 30  # Don't retry docs older than 30 days

    # CORS (for development, restrict in production)
    cors_origins: List[str] = ["*"]
    cors_allow_credentials: bool = True

    # Trusted Proxy IPs (only trust X-Forwarded-For from these IPs)
    # Set to your load balancer/reverse proxy IPs in production
    # Empty list = never trust X-Forwarded-For (safest default)
    trusted_proxy_ips: List[str] = []

    # System Admin Configuration
    sysadmin_subdomain: str = "admin.controllad oria.com.br"  # Separate subdomain for sysadmin
    sysadmin_frontend_url: str = "https://admin.controllad oria.com.br"  # Production
    sysadmin_frontend_url_dev: str = "http://localhost:3001"  # Local dev
    sysadmin_allowed_emails: List[str] = []  # Whitelist (empty = allow all flagged sysadmins)

    # Poppler Path (for PDF processing)
    poppler_path: str = ""

    # Logging
    log_level: str = "INFO"
    log_file: str = "dresystem.log"

    # Localization
    language: str = "pt-BR"

    # File Cleanup
    file_cleanup_enabled: bool = True
    file_retention_days: int = 365  # 12 months
    cleanup_schedule_hour: int = 3  # Run at 3 AM daily
    cleanup_orphaned_files: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Create global settings instance
settings = Settings()
