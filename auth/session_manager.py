"""
Session Management Service

Enforces device limits and prevents account sharing abuse:
- Max 2 active sessions per user
- Allowed: 1 mobile + 1 desktop/laptop
- NOT allowed: Multiple desktop/laptop sessions
- Automatically kicks oldest session when limit exceeded
"""

import secrets
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from user_agents import parse as parse_user_agent

from sqlalchemy.orm import Session

from database import User, UserSession


class SessionManager:
    """Manages user sessions and enforces device limits"""

    # Session configuration
    SESSION_DURATION_DAYS = 30  # How long sessions last
    MAX_SESSIONS = 2  # Maximum active sessions per user

    @staticmethod
    def detect_device_info(user_agent_string: str) -> dict:
        """
        Parse user agent string to detect device type, OS, browser

        Returns dict with: device_type, device_os, browser, device_name
        """
        ua = parse_user_agent(user_agent_string)

        # Determine device type
        if ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        else:
            device_type = "desktop"

        # Get OS
        device_os = ua.os.family  # Windows, Linux, Mac OS X, iOS, Android, etc.

        # Get browser
        browser = ua.browser.family  # Chrome, Firefox, Safari, Edge, etc.

        # Human-readable device name
        device_name = f"{browser} on {device_os}"

        return {
            "device_type": device_type,
            "device_os": device_os,
            "browser": browser,
            "device_name": device_name,
        }

    @staticmethod
    def count_device_types(sessions: List[UserSession]) -> dict:
        """Count sessions by device type"""
        counts = {"mobile": 0, "tablet": 0, "desktop": 0}
        for session in sessions:
            if session.device_type in counts:
                counts[session.device_type] += 1
        return counts

    @staticmethod
    def is_compatible_device_combo(sessions: List[UserSession], new_device_type: str) -> bool:
        """
        Check if adding a new device type is allowed

        Rules:
        - 1 mobile + 1 desktop/tablet = OK
        - 2 desktops = NOT OK
        - 2 mobiles = NOT OK
        - 1 mobile + 1 tablet = OK (tablet treated as desktop)
        """
        if len(sessions) == 0:
            return True

        if len(sessions) == 1:
            existing = sessions[0].device_type
            # Allow if one is mobile and other is desktop/tablet
            if existing == "mobile" and new_device_type in ["desktop", "tablet"]:
                return True
            if new_device_type == "mobile" and existing in ["desktop", "tablet"]:
                return True
            # Otherwise not allowed (same type)
            return False

        # If already 2 sessions, need to kick one out
        return False

    @staticmethod
    def create_session(
        user: User,
        user_agent: str,
        ip_address: str,
        db: Session,
    ) -> Tuple[UserSession, List[UserSession]]:
        """
        Create a new session for user

        Returns:
            Tuple of (new_session, kicked_sessions)
            - new_session: The newly created session
            - kicked_sessions: List of sessions that were deactivated
        """
        # Detect device info
        device_info = SessionManager.detect_device_info(user_agent)

        import hashlib

        # Generate device fingerprint
        device_fingerprint = hashlib.sha256(
            f"{user_agent}{ip_address}".encode()
        ).hexdigest()

        # Check if there's already an active session for this exact device
        existing_session = (
            db.query(UserSession)
            .filter_by(user_id=user.id, is_active=True)
            .filter(UserSession.device_fingerprint == device_fingerprint)
            .first()
        )

        if existing_session:
            # Reuse existing session from same device - just update activity
            existing_session.last_activity = datetime.utcnow()
            existing_session.expires_at = datetime.utcnow() + timedelta(days=SessionManager.SESSION_DURATION_DAYS)
            db.commit()
            db.refresh(existing_session)
            return existing_session, []

        # Get active sessions (excluding current device since we checked above)
        active_sessions = (
            db.query(UserSession)
            .filter_by(user_id=user.id, is_active=True)
            .order_by(UserSession.created_at.asc())  # Oldest first
            .all()
        )

        kicked_sessions = []

        # Only kick sessions if we would exceed MAX_SESSIONS with new session
        if len(active_sessions) >= SessionManager.MAX_SESSIONS:
            # Kick oldest session(s) to make room
            to_kick = active_sessions[: len(active_sessions) - SessionManager.MAX_SESSIONS + 1]
            for session in to_kick:
                session.is_active = False
                kicked_sessions.append(session)

        # Create new session for this device
        session_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(days=SessionManager.SESSION_DURATION_DAYS)

        new_session = UserSession(
            id=session_id,
            user_id=user.id,
            device_type=device_info["device_type"],
            device_os=device_info["device_os"],
            device_name=device_info["device_name"],
            browser=device_info["browser"],
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            expires_at=expires_at,
            is_active=True,
        )

        db.add(new_session)
        db.commit()
        db.refresh(new_session)

        return new_session, kicked_sessions

    @staticmethod
    def get_active_sessions(user_id: int, db: Session) -> List[UserSession]:
        """Get all active sessions for a user"""
        return (
            db.query(UserSession)
            .filter_by(user_id=user_id, is_active=True)
            .filter(UserSession.expires_at > datetime.utcnow())
            .order_by(UserSession.last_activity.desc())
            .all()
        )

    @staticmethod
    def validate_session(session_id: str, db: Session) -> Optional[UserSession]:
        """
        Validate a session ID

        Returns session if valid, None otherwise
        """
        session = db.query(UserSession).filter_by(id=session_id, is_active=True).first()

        if not session:
            return None

        # Check if expired
        if session.is_expired:
            session.is_active = False
            db.commit()
            return None

        # Update last activity
        session.last_activity = datetime.utcnow()
        db.commit()

        return session

    @staticmethod
    def revoke_session(session_id: str, db: Session) -> bool:
        """
        Revoke a specific session

        Returns True if session was found and revoked
        """
        session = db.query(UserSession).filter_by(id=session_id).first()
        if session:
            session.is_active = False
            db.commit()
            return True
        return False

    @staticmethod
    def revoke_all_sessions(user_id: int, db: Session, except_session_id: Optional[str] = None) -> int:
        """
        Revoke all sessions for a user

        Args:
            user_id: User ID
            db: Database session
            except_session_id: Optional session ID to keep active

        Returns:
            Number of sessions revoked
        """
        query = db.query(UserSession).filter_by(user_id=user_id, is_active=True)

        if except_session_id:
            query = query.filter(UserSession.id != except_session_id)

        sessions = query.all()
        count = len(sessions)

        for session in sessions:
            session.is_active = False

        db.commit()
        return count

    @staticmethod
    def cleanup_expired_sessions(db: Session) -> int:
        """
        Clean up expired sessions (run periodically)

        Returns number of sessions cleaned up
        """
        expired_sessions = (
            db.query(UserSession)
            .filter(UserSession.expires_at < datetime.utcnow())
            .filter_by(is_active=True)
            .all()
        )

        count = len(expired_sessions)

        for session in expired_sessions:
            session.is_active = False

        db.commit()
        return count
