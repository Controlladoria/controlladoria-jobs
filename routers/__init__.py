"""
API Routers
Organized by domain for better separation of concerns
"""

from .account import router as account_router
from .admin import router as admin_router
from .auth import router as auth_router
from .billing import router as billing_router
from .contact import router as contact_router
from .documents import router as documents_router
from .initial_balance import router as initial_balance_router
from .organizations import router as organizations_router
from .org_settings import router as org_settings_router
from .sessions import router as sessions_router
from .team import router as team_router
from .transactions import router as transactions_router

__all__ = [
    "account_router",
    "admin_router",
    "auth_router",
    "billing_router",
    "contact_router",
    "documents_router",
    "initial_balance_router",
    "organizations_router",
    "org_settings_router",
    "sessions_router",
    "team_router",
    "transactions_router",
]
