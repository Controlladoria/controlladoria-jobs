"""
Global exception handlers for FastAPI
Provides consistent error response format across all endpoints
"""

import logging
import traceback
from datetime import datetime
from typing import Union

from fastapi import Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from exceptions import ControlladorIAException

logger = logging.getLogger(__name__)


def create_error_response(
    code: str,
    message: str,
    status_code: int,
    details: dict = None,
    path: str = None,
    request_id: str = None,
) -> dict:
    """
    Create standardized error response

    Args:
        code: Error code (e.g., "VALIDATION_ERROR")
        message: Human-readable error message
        status_code: HTTP status code
        details: Additional error details
        path: Request path
        request_id: Unique request ID for tracking

    Returns:
        Standardized error response dictionary
    """
    error_response = {
        "error": {
            "code": code,
            "message": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    }

    if details:
        error_response["error"]["details"] = details

    if path:
        error_response["error"]["path"] = path

    if request_id:
        error_response["error"]["request_id"] = request_id

    # Add HTTP status code for reference
    error_response["error"]["status_code"] = status_code

    return error_response


async def controlladoria_exception_handler(
    request: Request, exc: ControlladorIAException
) -> JSONResponse:
    """
    Handler for custom ControlladorIA exceptions

    Provides consistent formatting for all custom exceptions
    """
    logger.error(
        f"ControlladorIAException: {exc.code} - {exc.message}",
        extra={
            "code": exc.code,
            "status_code": exc.status_code,
            "details": exc.details,
            "path": request.url.path,
        },
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
            path=request.url.path,
        ),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handler for FastAPI HTTPException

    Wraps FastAPI exceptions in standardized format
    """
    logger.warning(
        f"HTTPException: {exc.status_code} - {exc.detail}",
        extra={"status_code": exc.status_code, "path": request.url.path},
    )

    # Map status codes to error codes
    code_mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }

    code = code_mapping.get(exc.status_code, "HTTP_ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=code,
            message=str(exc.detail),
            status_code=exc.status_code,
            path=request.url.path,
        ),
    )


async def validation_exception_handler(
    request: Request, exc: Union[RequestValidationError, PydanticValidationError]
) -> JSONResponse:
    """
    Handler for Pydantic validation errors

    Formats validation errors in a user-friendly way
    """
    logger.warning(
        f"ValidationError at {request.url.path}",
        extra={
            "errors": exc.errors() if hasattr(exc, "errors") else str(exc),
            "path": request.url.path,
        },
    )

    # Extract validation errors
    errors = []
    if hasattr(exc, "errors"):
        for error in exc.errors():
            field = " -> ".join(str(loc) for loc in error.get("loc", []))
            errors.append(
                {
                    "field": field,
                    "message": error.get("msg", "Validation error"),
                    "type": error.get("type", "value_error"),
                }
            )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=create_error_response(
            code="VALIDATION_ERROR",
            message="Falha na validação da requisição",
            status_code=422,
            details={"errors": errors},
            path=request.url.path,
        ),
    )


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """
    Handler for rate limit exceeded errors

    Provides information about rate limiting
    """
    logger.warning(
        f"Rate limit exceeded at {request.url.path}",
        extra={
            "path": request.url.path,
            "remote_addr": request.client.host if request.client else None,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=create_error_response(
            code="RATE_LIMIT_EXCEEDED",
            message="Muitas requisições. Por favor, tente novamente mais tarde.",
            status_code=429,
            details={
                "limit": str(exc),
                "retry_after": "Por favor, aguarde antes de fazer outra requisição",
            },
            path=request.url.path,
        ),
    )


async def database_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """
    Handler for database errors

    Provides safe error messages without exposing database details
    """
    logger.error(
        f"Database error at {request.url.path}: {str(exc)}",
        extra={"path": request.url.path, "error_type": type(exc).__name__},
        exc_info=True,
    )

    # Don't expose database details to users
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=create_error_response(
            code="DATABASE_ERROR",
            message="Ocorreu um erro no banco de dados. Por favor, tente novamente mais tarde.",
            status_code=500,
            path=request.url.path,
        ),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unexpected exceptions

    Logs full error details but returns safe message to users
    """
    # Log full exception with traceback
    logger.error(
        f"Unhandled exception at {request.url.path}: {str(exc)}",
        extra={
            "path": request.url.path,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        },
        exc_info=True,
    )

    # Also log the full traceback
    logger.error(f"Traceback:\n{traceback.format_exc()}")

    # Return generic error message (don't expose internal details)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=create_error_response(
            code="INTERNAL_SERVER_ERROR",
            message="Ocorreu um erro inesperado. Nossa equipe foi notificada.",
            status_code=500,
            path=request.url.path,
        ),
    )
