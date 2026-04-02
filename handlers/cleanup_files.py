"""
Lambda handler for file cleanup (triggered by EventBridge, daily at 2 AM).

Deletes files older than the retention period and orphaned files.
Copied from ControlladorIA/api.py cleanup_old_files().
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """EventBridge-triggered Lambda handler for file cleanup."""
    cleanup_old_files()
    return {"statusCode": 200, "body": "OK"}


def cleanup_old_files():
    """
    Scheduled job to clean up old files and orphaned files.
    - Deletes files older than retention period (default: 12 months)
    - Deletes orphaned files (in S3 but not in database)

    Copied from ControlladorIA/api.py lines 274-341.
    """
    from database import SessionLocal, Document

    if not settings.file_cleanup_enabled:
        logger.debug("File cleanup is disabled in settings")
        return

    logger.info("Starting scheduled file cleanup job")
    db = SessionLocal()

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=settings.file_retention_days)
        logger.debug(
            f"Deleting files older than {cutoff_date.date()} ({settings.file_retention_days} days)"
        )

        old_docs = db.query(Document).filter(Document.upload_date < cutoff_date).all()

        deleted_count = 0
        for doc in old_docs:
            try:
                if doc.file_path:
                    try:
                        from storage.s3_service import S3StorageService
                        s3 = S3StorageService()
                        s3.s3_client.delete_object(
                            Bucket=s3.bucket_name, Key=doc.file_path
                        )
                        logger.debug(f"Deleted S3 object: {doc.file_path}")
                    except Exception as e:
                        logger.error(f"Error deleting S3 object {doc.file_path}: {e}")

                db.delete(doc)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting old document {doc.id}: {e}")

        db.commit()
        logger.info(f"Deleted {deleted_count} old documents")

    except Exception as e:
        logger.error(f"File cleanup job failed: {e}")
        db.rollback()
    finally:
        db.close()
