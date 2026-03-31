"""
Encryption utilities for sensitive data

Provides encryption for MFA secrets and backup codes.
Uses Fernet (symmetric encryption) from cryptography library.
"""

import base64
import os
from typing import Optional

import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config import settings


class EncryptionService:
    """Handles encryption and decryption of sensitive data"""

    _fernet: Optional[Fernet] = None

    @classmethod
    def _get_fernet(cls) -> Fernet:
        """
        Get or create Fernet cipher

        Uses ENCRYPTION_KEY from settings. If not set, derives from SECRET_KEY.
        """
        if cls._fernet is not None:
            return cls._fernet

        # Get encryption key from settings
        encryption_key = settings.encryption_key

        if not encryption_key:
            # Derive from JWT_SECRET_KEY if ENCRYPTION_KEY not set
            # Use PBKDF2 to derive a proper 32-byte key
            if not settings.jwt_secret_key:
                raise ValueError(
                    "Either ENCRYPTION_KEY or JWT_SECRET_KEY must be set in environment"
                )

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"mfa_encryption_salt",  # Fixed salt for consistency
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(
                kdf.derive(settings.jwt_secret_key.encode())
            )
        else:
            # Use provided encryption key
            key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key

        cls._fernet = Fernet(key)
        return cls._fernet

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """
        Encrypt a string

        Args:
            plaintext: String to encrypt

        Returns:
            Encrypted string (base64-encoded)
        """
        if not plaintext:
            return ""

        fernet = cls._get_fernet()
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """
        Decrypt a string

        Args:
            ciphertext: Encrypted string (base64-encoded)

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""

        fernet = cls._get_fernet()
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()


class BackupCodeHasher:
    """Handles hashing and verification of MFA backup codes"""

    @staticmethod
    def hash_code(code: str) -> str:
        """
        Hash a backup code using bcrypt

        Args:
            code: Plaintext backup code

        Returns:
            Bcrypt hash of the code
        """
        # Use cost factor 12 (good balance of security and performance)
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(code.encode(), salt)
        return hashed.decode()

    @staticmethod
    def verify_code(code: str, hashed_code: str) -> bool:
        """
        Verify a backup code against its hash

        Args:
            code: Plaintext code to verify
            hashed_code: Bcrypt hash to compare against

        Returns:
            True if code matches hash
        """
        try:
            return bcrypt.checkpw(code.encode(), hashed_code.encode())
        except Exception:
            return False


# Convenience functions for direct import
def encrypt_mfa_secret(secret: str) -> str:
    """
    Encrypt MFA TOTP secret before storing in database

    Args:
        secret: TOTP secret (base32 string from pyotp)

    Returns:
        Encrypted secret
    """
    return EncryptionService.encrypt(secret)


def decrypt_mfa_secret(encrypted_secret: str) -> str:
    """
    Decrypt MFA TOTP secret from database

    Args:
        encrypted_secret: Encrypted secret from database

    Returns:
        Plaintext TOTP secret
    """
    return EncryptionService.decrypt(encrypted_secret)


def hash_backup_code(code: str) -> str:
    """
    Hash a single backup code

    Args:
        code: Plaintext backup code

    Returns:
        Bcrypt hash
    """
    return BackupCodeHasher.hash_code(code)


def verify_backup_code(code: str, hashed_code: str) -> bool:
    """
    Verify a backup code

    Args:
        code: Plaintext code from user
        hashed_code: Stored hash

    Returns:
        True if valid
    """
    return BackupCodeHasher.verify_code(code, hashed_code)
