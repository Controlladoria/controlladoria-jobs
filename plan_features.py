"""
Plan Features — Helper module for plan-based feature gating

Feature keys are just strings stored in the Plan.features JSON column.
This module provides constants for known feature keys and helper functions
to query plans from the database.

The Plan table is the single source of truth for all plan definitions.
Stakeholders can edit plan names, features, visibility, and seat limits
directly in the database without code changes.
"""

from typing import Optional, List

from sqlalchemy.orm import Session

# ─── FEATURE KEY CONSTANTS ─────────────────────────────────────────────────────
# These are referenced in code for feature gating.
# New features can be added to the Plan.features JSON anytime without migrations.

CASH_FLOW_DIRECT = "cash_flow_direct"
TEAM_MANAGEMENT = "team_management"
API_ACCESS = "api_access"
PRIORITY_SUPPORT = "priority_support"
WHITE_LABEL = "white_label"  # Max plan: custom org logo on exports


# ─── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def get_default_plan(db: Session):
    """Get the default plan (used for trials)"""
    from database import Plan
    return db.query(Plan).filter(Plan.is_default == True).first()


def get_plan_by_slug(db: Session, slug: str):
    """Get a plan by its slug identifier"""
    from database import Plan
    return db.query(Plan).filter(Plan.slug == slug).first()


def get_plan_by_stripe_price_id(db: Session, price_id: str):
    """Get a plan by its Stripe price ID"""
    from database import Plan
    if not price_id:
        return None
    return db.query(Plan).filter(Plan.stripe_price_id == price_id).first()


def get_active_plans(db: Session) -> list:
    """Get all active (visible) plans ordered by sort_order"""
    from database import Plan
    return (
        db.query(Plan)
        .filter(Plan.is_active == True)
        .order_by(Plan.sort_order)
        .all()
    )


def has_plan_feature(plan, feature_key: str) -> bool:
    """
    Check if a plan has a specific feature (claims-based check).

    Args:
        plan: Plan object (or None)
        feature_key: Feature key string (e.g., "cash_flow_direct")

    Returns:
        True if the plan has the feature, False otherwise
    """
    if plan is None:
        return False
    features = getattr(plan, "features", None)
    if not features or not isinstance(features, dict):
        return False
    return features.get(feature_key, False)
