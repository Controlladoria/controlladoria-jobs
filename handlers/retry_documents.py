"""
Lambda handler for retrying failed documents
(triggered by EventBridge, daily at 2 AM).

Simplified version: resets FAILED documents to PENDING and sends
SQS messages so the process_document Lambda picks them up.
Does NOT do in-process reprocessing.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """EventBridge-triggered Lambda handler for document retry."""
    retry_failed_documents()
    return {"statusCode": 200, "body": "OK"}


def retry_failed_documents():
    """
    Find failed documents eligible for retry, reset to PENDING,
    and send SQS messages for reprocessing.

    Simplified from ControlladorIA/api.py retry_failed_documents().
    """
    import boto3
    from database import SessionLocal, Document, DocumentStatus

    if not settings.document_retry_enabled:
        logger.info("Document retry is disabled")
        return

    logger.info("Starting nightly retry of failed documents")
    db = SessionLocal()

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=settings.document_retry_max_age_days)

        failed_docs = db.query(Document).filter(
            Document.status == DocumentStatus.FAILED,
            Document.retry_count < settings.document_max_retries,
            Document.max_retries_exhausted == False,
            Document.is_cancellation == False,
            Document.upload_date > cutoff_date,
        ).order_by(Document.upload_date.asc()).all()

        if not failed_docs:
            logger.info("No failed documents to retry")
            return

        logger.info(f"Found {len(failed_docs)} failed documents eligible for retry")

        # Check file existence and send SQS messages
        sqs_kwargs = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            sqs_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            sqs_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        sqs = boto3.client("sqs", **sqs_kwargs)
        sqs_queue_url = settings.sqs_document_queue_url

        retried = 0
        skipped = 0

        for doc in failed_docs:
            # Check if file still exists in S3
            if doc.file_path:
                try:
                    s3_kwargs = {"region_name": settings.aws_region}
                    if settings.aws_access_key_id and settings.aws_secret_access_key:
                        s3_kwargs["aws_access_key_id"] = settings.aws_access_key_id
                        s3_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
                    s3 = boto3.client("s3", **s3_kwargs)
                    s3.head_object(Bucket=settings.s3_bucket_name, Key=doc.file_path)
                except Exception:
                    doc.max_retries_exhausted = True
                    doc.error_message = "Arquivo nao encontrado para reprocessamento"
                    db.commit()
                    skipped += 1
                    continue

            # Reset status and increment retry count
            doc.status = DocumentStatus.PENDING
            doc.error_message = None
            doc.retry_count += 1
            doc.last_retry_at = datetime.utcnow()
            db.commit()

            # Send SQS message for reprocessing
            try:
                sqs.send_message(
                    QueueUrl=sqs_queue_url,
                    MessageBody=json.dumps({
                        "document_id": doc.id,
                        "file_path": doc.file_path,
                    }),
                )
                retried += 1
                logger.info(
                    f"Retrying document {doc.id} ({doc.file_name}) - "
                    f"attempt {doc.retry_count}/{settings.document_max_retries}"
                )
            except Exception as e:
                logger.error(f"Failed to send SQS for document {doc.id}: {e}")

        logger.info(f"Retry complete: {retried} retried, {skipped} skipped")

    except Exception as e:
        logger.error(f"Document retry job failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
    finally:
        db.close()
