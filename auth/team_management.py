"""
Team Management Utilities

Helper functions for multi-user/team management features.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import secrets
from sqlalchemy.orm import Session

from database import User, TeamInvitation, Subscription


def get_company_users(user_id: int, db: Session) -> List[User]:
    """
    Get all users in the same company (super admin + team members)

    Args:
        user_id: User ID (can be super admin or member)
        db: Database session

    Returns:
        List of all users in the company
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        return []

    if user.role == "super_admin":
        # Get all members of this super admin
        members = db.query(User).filter_by(parent_user_id=user.id, is_active=True).all()
        return [user] + members
    else:
        # Get super admin and all siblings
        if not user.parent_user_id:
            return [user]

        super_admin = db.query(User).filter_by(id=user.parent_user_id).first()
        if not super_admin:
            return [user]

        siblings = (
            db.query(User)
            .filter_by(parent_user_id=super_admin.id, is_active=True)
            .all()
        )
        return [super_admin] + siblings


def get_super_admin(user: User, db: Session) -> Optional[User]:
    """
    Get the super admin for a user

    Args:
        user: User object
        db: Database session

    Returns:
        Super admin user, or None if user is already super admin
    """
    if user.role == "super_admin":
        return user

    if user.parent_user_id:
        return db.query(User).filter_by(id=user.parent_user_id).first()

    return None


def can_invite_more_users(user: User, db: Session) -> Tuple[bool, str]:
    """
    Check if super admin can invite more users

    Args:
        user: Super admin user
        db: Database session

    Returns:
        Tuple of (can_invite: bool, reason: str)
    """
    if user.role != "super_admin":
        return False, "Apenas administradores podem convidar membros"

    # Get subscription
    subscription = db.query(Subscription).filter_by(user_id=user.id).first()
    if not subscription:
        return False, "Nenhuma assinatura encontrada"

    if not subscription.is_active:
        return (
            False,
            "Sua assinatura não está ativa. Renove para convidar membros.",
        )

    # Check if plan supports team management
    from plan_features import has_plan_feature, TEAM_MANAGEMENT
    if not has_plan_feature(subscription.plan, TEAM_MANAGEMENT):
        return False, "Seu plano não inclui gestão de equipe. Faça upgrade para o plano Pro ou Max."

    # Count current users (admin + active members)
    current_count = 1 + db.query(User).filter(
        User.parent_user_id == user.id, User.is_active == True
    ).count()

    # Count pending invitations
    pending_count = (
        db.query(TeamInvitation)
        .filter(
            TeamInvitation.inviter_user_id == user.id,
            TeamInvitation.accepted_at == None,
            TeamInvitation.is_cancelled == False,
            TeamInvitation.expires_at > datetime.utcnow(),
        )
        .count()
    )

    total_used = current_count + pending_count

    if total_used >= subscription.max_users:
        return (
            False,
            f"Limite de {subscription.max_users} usuário(s) atingido. "
            f"Faça upgrade do seu plano para adicionar mais membros.",
        )

    return True, ""


def get_seat_usage(user: User, db: Session) -> dict:
    """
    Get current seat usage for super admin's subscription

    Args:
        user: Super admin user
        db: Database session

    Returns:
        Dict with seat usage info
    """
    if user.role != "super_admin":
        admin = get_super_admin(user, db)
        if admin:
            user = admin
        else:
            return {"used": 0, "max": 0, "available": 0}

    subscription = db.query(Subscription).filter_by(user_id=user.id).first()
    if not subscription:
        return {"used": 0, "max": 0, "available": 0}

    # Count current users
    current_count = 1 + db.query(User).filter(
        User.parent_user_id == user.id, User.is_active == True
    ).count()

    # Count pending invitations
    pending_count = (
        db.query(TeamInvitation)
        .filter(
            TeamInvitation.inviter_user_id == user.id,
            TeamInvitation.accepted_at == None,
            TeamInvitation.is_cancelled == False,
            TeamInvitation.expires_at > datetime.utcnow(),
        )
        .count()
    )

    total_used = current_count + pending_count
    max_users = subscription.max_users
    available = max(0, max_users - total_used)

    return {
        "used": current_count,
        "pending": pending_count,
        "total_used": total_used,
        "max": max_users,
        "available": available,
    }


def create_invitation_token() -> str:
    """Generate a secure random token for invitation"""
    return secrets.token_urlsafe(32)


def create_invitation(
    inviter: User, email: str, db: Session, role: str = "viewer"
) -> Tuple[Optional[TeamInvitation], Optional[str]]:
    """
    Create a new team invitation

    Args:
        inviter: User creating the invitation (must have team.invite permission)
        email: Email to invite
        db: Database session
        role: Role to assign (owner, admin, accountant, bookkeeper, viewer)

    Returns:
        Tuple of (invitation, error_message)
    """
    from auth.permissions import has_permission, Permission

    # Validate inviter has team.invite permission
    if not has_permission(inviter, Permission.TEAM_INVITE):
        return None, "Você não tem permissão para convidar membros"

    # Check if can invite more users
    can_invite, reason = can_invite_more_users(inviter, db)
    if not can_invite:
        return None, reason

    # Check if email already exists as a user
    existing_user = db.query(User).filter_by(email=email.lower()).first()
    if existing_user:
        return None, "Este email já está cadastrado no sistema"

    # Check if there's already a pending invitation
    existing_invitation = (
        db.query(TeamInvitation)
        .filter_by(
            inviter_user_id=inviter.id, email=email.lower(), is_cancelled=False
        )
        .filter(TeamInvitation.accepted_at == None)
        .filter(TeamInvitation.expires_at > datetime.utcnow())
        .first()
    )

    if existing_invitation:
        return (
            None,
            "Já existe um convite pendente para este email. Reenvie ou cancele o convite anterior.",
        )

    # Create invitation with role
    invitation = TeamInvitation(
        inviter_user_id=inviter.id,
        email=email.lower(),
        role=role,
        token=create_invitation_token(),
        expires_at=datetime.utcnow() + timedelta(days=7),  # Expires in 7 days
        created_at=datetime.utcnow(),
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    return invitation, None


def validate_invitation_token(token: str, db: Session) -> Tuple[Optional[TeamInvitation], Optional[str]]:
    """
    Validate an invitation token

    Args:
        token: Invitation token
        db: Database session

    Returns:
        Tuple of (invitation, error_message)
    """
    invitation = db.query(TeamInvitation).filter_by(token=token).first()

    if not invitation:
        return None, "Convite não encontrado ou inválido"

    if invitation.is_cancelled:
        return None, "Este convite foi cancelado"

    if invitation.accepted_at:
        return None, "Este convite já foi aceito"

    if invitation.is_expired:
        return None, "Este convite expirou. Solicite um novo convite ao administrador."

    return invitation, None


def accept_invitation(
    invitation: TeamInvitation, new_user: User, db: Session
) -> None:
    """
    Mark invitation as accepted

    Args:
        invitation: TeamInvitation object
        new_user: Newly created user
        db: Database session
    """
    invitation.accepted_at = datetime.utcnow()
    db.commit()


def cancel_invitation(invitation_id: int, user: User, db: Session) -> Tuple[bool, str]:
    """
    Cancel a pending invitation

    Args:
        invitation_id: Invitation ID to cancel
        user: User canceling (must have team.remove permission)
        db: Database session

    Returns:
        Tuple of (success, message)
    """
    from auth.permissions import has_permission, Permission

    if not has_permission(user, Permission.TEAM_REMOVE):
        return False, "Você não tem permissão para cancelar convites"

    invitation = db.query(TeamInvitation).filter_by(id=invitation_id, inviter_user_id=user.id).first()

    if not invitation:
        return False, "Convite não encontrado"

    if invitation.accepted_at:
        return False, "Não é possível cancelar um convite já aceito"

    invitation.is_cancelled = True
    db.commit()

    return True, "Convite cancelado com sucesso"


def remove_team_member(member_id: int, admin: User, db: Session) -> Tuple[bool, str]:
    """
    Remove a team member

    Args:
        member_id: User ID to remove
        admin: User removing the member (must have team.remove permission)
        db: Database session

    Returns:
        Tuple of (success, message)
    """
    from auth.permissions import has_permission, Permission

    if not has_permission(admin, Permission.TEAM_REMOVE):
        return False, "Você não tem permissão para remover membros"

    member = db.query(User).filter_by(id=member_id, parent_user_id=admin.id).first()

    if not member:
        return False, "Membro não encontrado ou não pertence à sua equipe"

    if member.role == "super_admin":
        return False, "Não é possível remover o administrador"

    # Mark as inactive instead of deleting (keep audit trail)
    member.is_active = False
    db.commit()

    return True, f"Membro {member.full_name} removido com sucesso"


def get_team_members_and_invitations(user: User, db: Session) -> dict:
    """
    Get all team members and pending invitations for display

    Args:
        user: Super admin user
        db: Database session

    Returns:
        Dict with members and invitations
    """
    if user.role != "super_admin":
        return {"members": [], "pending_invitations": [], "seats": {"used": 0, "max": 0}}

    # Get active team members
    members = (
        db.query(User)
        .filter_by(parent_user_id=user.id, is_active=True)
        .order_by(User.created_at.desc())
        .all()
    )

    # Get pending invitations
    pending_invitations = (
        db.query(TeamInvitation)
        .filter(
            TeamInvitation.inviter_user_id == user.id,
            TeamInvitation.accepted_at == None,
            TeamInvitation.is_cancelled == False,
            TeamInvitation.expires_at > datetime.utcnow(),
        )
        .order_by(TeamInvitation.created_at.desc())
        .all()
    )

    # Get seat usage
    seats = get_seat_usage(user, db)

    return {
        "members": members,
        "pending_invitations": pending_invitations,
        "seats": seats,
    }


def get_organization_owner_id(user, db=None) -> int:
    """
    Get the organization owner's user_id.
    Team members share data via the owner's ID (parent_user_id).
    If user IS the owner (no parent), returns their own ID.
    """
    if user.parent_user_id is None:
        return user.id
    return user.parent_user_id
