"""
Custom exception classes for DreSystem
Provides domain-specific exceptions with structured error responses
"""

from typing import Any, Dict, Optional


class DreSystemException(Exception):
    """Base exception for all DreSystem errors"""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(DreSystemException):
    """Authentication failed"""

    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code="AUTHENTICATION_ERROR",
            status_code=401,
            details=details,
        )


class AuthorizationError(DreSystemException):
    """Insufficient permissions"""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code="AUTHORIZATION_ERROR",
            status_code=403,
            details=details,
        )


class ResourceNotFoundError(DreSystemException):
    """Recurso não encontrado"""

    def __init__(
        self,
        message: str = "Recurso não encontrado",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message, code="RESOURCE_NOT_FOUND", status_code=404, details=details
        )


class ValidationError(DreSystemException):
    """Data validation failed"""

    def __init__(
        self,
        message: str = "Validation failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message, code="VALIDATION_ERROR", status_code=400, details=details
        )


class PaymentError(DreSystemException):
    """Payment processing error"""

    def __init__(
        self,
        message: str = "Payment processing failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message, code="PAYMENT_ERROR", status_code=402, details=details
        )


class SubscriptionError(DreSystemException):
    """Subscription issue"""

    def __init__(
        self,
        message: str = "Subscription error",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message, code="SUBSCRIPTION_ERROR", status_code=403, details=details
        )


class FileProcessingError(DreSystemException):
    """File processing error"""

    def __init__(
        self,
        message: str = "File processing failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code="FILE_PROCESSING_ERROR",
            status_code=422,
            details=details,
        )


class RateLimitError(DreSystemException):
    """Rate limit exceeded"""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details=details,
        )


class DatabaseError(DreSystemException):
    """Database operation error"""

    def __init__(
        self, message: str = "Database error", details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message, code="DATABASE_ERROR", status_code=500, details=details
        )


class ExternalServiceError(DreSystemException):
    """External service (Stripe, AI, etc.) error"""

    def __init__(
        self,
        message: str = "External service error",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details=details,
        )
