"""
Lambda handler for expired verification token cleanup
(triggered by EventBridge, every 6 hours).

Copied from ControlladorIA/api.py cleanup_expired_verification_tokens().
"""

import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """EventBridge-triggered Lambda handler for token cleanup."""
    cleanup_expired_verification_tokens()
    return {"statusCode": 200, "body": "OK"}


def cleanup_expired_verification_tokens():
    """
    Clean up expired email verification tokens.
    Tokens older than 24 hours are cleared from users who haven't verified.

    Copied from ControlladorIA/api.py lines 345-380.
    """
    from database import SessionLocal, User

    logger.info("Starting expired verification token cleanup")
    db = SessionLocal()

    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        expired_users = db.query(User).filter(
            User.email_verification_token.isnot(None),
            User.is_verified == False,
            User.email_verification_token_created_at.isnot(None),
            User.email_verification_token_created_at < cutoff,
        ).all()

        cleaned_count = 0
        for user in expired_users:
            user.email_verification_token = None
            user.email_verification_token_created_at = None
            cleaned_count += 1

        db.commit()
        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} expired verification tokens")
        else:
            logger.info("No expired verification tokens to clean")

    except Exception as e:
        logger.error(f"Verification token cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()
