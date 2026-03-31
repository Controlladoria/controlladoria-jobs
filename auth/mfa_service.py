"""
Multi-Factor Authentication Service

Supports:
1. TOTP (Google Authenticator, Authy, etc.)
2. Email codes (6-digit codes sent via email)

Security:
- TOTP secrets are encrypted at rest using Fernet encryption
- Backup codes are hashed using bcrypt (one-way hash)
"""

import json
import pyotp
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from database import User
from auth.encryption import (
    encrypt_mfa_secret,
    decrypt_mfa_secret,
    hash_backup_code,
    verify_backup_code,
)


class MFAService:
    """Handles TOTP and Email MFA operations"""

    # Email MFA code storage (in production, use Redis for better performance)
    _email_codes = {}  # {user_id: {"code": "123456", "expires_at": datetime}}

    @staticmethod
    def generate_totp_secret() -> str:
        """Generate a new TOTP secret for Google Authenticator"""
        return pyotp.random_base32()

    @staticmethod
    def get_totp_provisioning_uri(user_email: str, secret: str, issuer: str = "ControlladorIA") -> str:
        """
        Get provisioning URI for QR code generation

        Args:
            user_email: User's email address
            secret: TOTP secret
            issuer: App name (shows in Google Authenticator)

        Returns:
            otpauth:// URI for QR code
        """
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=user_email, issuer_name=issuer)

    @staticmethod
    def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
        """
        Verify TOTP code from Google Authenticator

        Args:
            secret: User's TOTP secret
            code: 6-digit code from authenticator app
            window: Time window tolerance (1 = ±30 seconds)

        Returns:
            True if code is valid
        """
        if not secret or not code:
            return False

        totp = pyotp.TOTP(secret)
        # verify() accepts codes from current window and ±window intervals
        return totp.verify(code, valid_window=window)

    @staticmethod
    def generate_backup_codes(count: int = 10) -> List[str]:
        """
        Generate backup codes for account recovery

        Returns list of 10-character alphanumeric codes
        """
        codes = []
        for _ in range(count):
            # Generate 10-character code (5 groups of 2, like: AB12-CD34-EF56-GH78-IJ90)
            code = "-".join(
                [
                    secrets.token_hex(1).upper()
                    for _ in range(5)
                ]
            )
            codes.append(code)
        return codes

    @staticmethod
    def hash_backup_codes(codes: List[str]) -> str:
        """
        Hash backup codes before storing

        Each code is hashed individually using bcrypt.
        Stored as JSON array of bcrypt hashes.

        Args:
            codes: List of plaintext backup codes

        Returns:
            JSON string containing array of bcrypt hashes
        """
        hashed_codes = [hash_backup_code(code.upper().strip()) for code in codes]
        return json.dumps(hashed_codes)

    @staticmethod
    def verify_backup_code(user: User, code: str, db: Session) -> bool:
        """
        Verify and consume a backup code (one-time use)

        Checks code against bcrypt hashes stored in database.
        If valid, removes the used hash (one-time use).

        Args:
            user: User object
            code: Plaintext backup code from user
            db: Database session

        Returns:
            True if code is valid
        """
        if not user.mfa_backup_codes:
            return False

        try:
            backup_code_hashes = json.loads(user.mfa_backup_codes)
        except json.JSONDecodeError:
            return False

        # Normalize user input
        code_normalized = code.upper().strip()

        # Check if code matches any stored hash
        for i, stored_hash in enumerate(backup_code_hashes):
            if verify_backup_code(code_normalized, stored_hash):
                # Valid code found - remove it (one-time use)
                backup_code_hashes.pop(i)
                user.mfa_backup_codes = json.dumps(backup_code_hashes)
                db.commit()
                return True

        return False

    @staticmethod
    def enable_totp_mfa(user: User, secret: str, backup_codes: List[str], db: Session):
        """
        Enable TOTP MFA for user

        Encrypts the TOTP secret before storing in database.
        Hashes backup codes using bcrypt.

        Args:
            user: User object
            secret: TOTP secret (base32 string)
            backup_codes: List of plaintext backup codes
            db: Database session
        """
        user.mfa_enabled = True
        user.mfa_method = "totp"
        user.mfa_secret = encrypt_mfa_secret(secret)  # Encrypted storage
        user.mfa_backup_codes = MFAService.hash_backup_codes(backup_codes)
        user.mfa_enabled_at = datetime.utcnow()
        db.commit()

    @staticmethod
    def enable_email_mfa(user: User, backup_codes: List[str], db: Session):
        """Enable Email MFA for user"""
        user.mfa_enabled = True
        user.mfa_method = "email"
        user.mfa_secret = None  # Email MFA doesn't need a secret
        user.mfa_backup_codes = MFAService.hash_backup_codes(backup_codes)
        user.mfa_enabled_at = datetime.utcnow()
        db.commit()

    @staticmethod
    def disable_mfa(user: User, db: Session):
        """Disable MFA for user"""
        user.mfa_enabled = False
        user.mfa_method = None
        user.mfa_secret = None
        user.mfa_backup_codes = None
        db.commit()

    # ========== EMAIL MFA ==========

    @staticmethod
    def generate_email_code() -> str:
        """Generate 6-digit code for email MFA"""
        return f"{secrets.randbelow(1000000):06d}"

    @staticmethod
    def store_email_code(user_id: int, code: str, expires_in_minutes: int = 10):
        """
        Store email code temporarily

        In production, use Redis with TTL for better performance
        """
        expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
        MFAService._email_codes[user_id] = {
            "code": code,
            "expires_at": expires_at,
            "attempts": 0,
        }

    @staticmethod
    def verify_email_code(user_id: int, code: str) -> bool:
        """
        Verify email MFA code

        Returns True if code is valid
        """
        if user_id not in MFAService._email_codes:
            return False

        stored = MFAService._email_codes[user_id]

        # Check expiration
        if datetime.utcnow() > stored["expires_at"]:
            del MFAService._email_codes[user_id]
            return False

        # Check attempts (max 5)
        if stored["attempts"] >= 5:
            del MFAService._email_codes[user_id]
            return False

        # Increment attempts
        stored["attempts"] += 1

        # Check code
        if stored["code"] == code:
            # Valid code - clean up
            del MFAService._email_codes[user_id]
            return True

        return False

    @staticmethod
    def clear_email_code(user_id: int):
        """Clear stored email code"""
        if user_id in MFAService._email_codes:
            del MFAService._email_codes[user_id]

    @staticmethod
    async def send_email_mfa_code(user: User, code: str):
        """
        Send MFA code via email

        Args:
            user: User object
            code: 6-digit code to send
        """
        from email_service import email_service

        await email_service.send_mfa_code_email(
            to=user.email,
            user_name=user.full_name or user.email.split("@")[0],
            code=code,
        )
