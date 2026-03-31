"""
Subscription middleware
Ensures users have active subscriptions for protected operations
"""

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_active_user
from config import settings
from database import OrgMembership, Subscription, SubscriptionStatus, User, get_db


async def require_active_subscription(
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
) -> Subscription:
    """
    Dependency to ensure user has an active subscription.

    Multi-org aware: checks the subscription for the user's active organization.
    Falls back to user-level subscription for backward compatibility.

    Raises HTTPException if:
    - No subscription exists
    - Trial has expired
    - Subscription is not active
    - Team member exceeds seat limit (plan downgrade scenario)

    Returns:
        Subscription object if valid
    """
    subscription = None

    # Try org-based subscription first (multi-org support)
    org_id = getattr(user, '_active_org_id', None) or user.active_org_id
    if org_id:
        subscription = db.query(Subscription).filter(
            Subscription.organization_id == org_id
        ).first()

    # Fallback: user-level subscription (legacy / backward compat)
    if not subscription:
        subscription = (
            db.query(Subscription).filter(Subscription.user_id == user.id).first()
        )

    # Auto-create trial subscription for new users
    if not subscription:
        from plan_features import get_default_plan
        default_plan = get_default_plan(db)
        trial_end = datetime.utcnow() + timedelta(days=settings.stripe_trial_days)
        subscription = Subscription(
            user_id=user.id,
            organization_id=org_id,  # Link to org if available
            stripe_customer_id=f"trial_{user.id}",  # Placeholder until Stripe checkout
            status=SubscriptionStatus.TRIALING,
            trial_end=trial_end,
            plan_id=default_plan.id if default_plan else None,
            max_users=default_plan.max_users if default_plan else 1,
        )
        db.add(subscription)
        try:
            db.commit()
            db.refresh(subscription)
        except Exception:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erro ao criar assinatura de teste. Tente novamente.",
            )

    # Check if trialing and trial expired
    if subscription.status == SubscriptionStatus.TRIALING:
        if subscription.trial_end and subscription.trial_end < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Trial has expired. Please subscribe to continue.",
            )

    # Check subscription status
    if subscription.status not in [
        SubscriptionStatus.TRIALING,
        SubscriptionStatus.ACTIVE,
    ]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Subscription is {subscription.status.value}. Please update your subscription.",
        )

    # Seat enforcement for org members
    if org_id:
        # Count active members in this org
        member_count = db.query(OrgMembership).filter(
            OrgMembership.organization_id == org_id,
            OrgMembership.is_active == True,
        ).count()

        if member_count > subscription.max_users:
            # Check if current user is within allowed seats (ordered by join date)
            allowed_members = (
                db.query(OrgMembership.user_id)
                .filter(
                    OrgMembership.organization_id == org_id,
                    OrgMembership.is_active == True,
                )
                .order_by(OrgMembership.joined_at.asc())
                .limit(subscription.max_users)
                .all()
            )
            allowed_ids = {m.user_id for m in allowed_members}
            if user.id not in allowed_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="O plano da sua organização foi atualizado para um número menor de licenças. "
                           "Entre em contato com o administrador da sua organização ou com o suporte.",
                )
    elif user.parent_user_id:
        # Legacy seat enforcement for unmigrated users
        owner = db.query(User).filter(User.id == user.parent_user_id).first()
        if owner:
            owner_sub = db.query(Subscription).filter(Subscription.user_id == owner.id).first()
            if owner_sub:
                team_members = (
                    db.query(User)
                    .filter(User.parent_user_id == owner.id, User.is_active == True)
                    .order_by(User.created_at.asc())
                    .all()
                )
                allowed_seats = owner_sub.max_users - 1
                if len(team_members) > allowed_seats:
                    allowed_ids = {m.id for m in team_members[:allowed_seats]}
                    if user.id not in allowed_ids:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="O plano da sua organização foi atualizado para um número menor de licenças. "
                                   "Entre em contato com o administrador da sua organização ou com o suporte.",
                        )

    return subscription
