"""
Document Processing Tasks
Celery tasks for asynchronous document processing
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from celery import Task

from celery_app import celery_app
from database import Document, DocumentStatus, SessionLocal
from storage.s3_service import s3_storage
from structured_processor import StructuredDocumentProcessor

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task with database session management"""

    _db = None

    @property
    def db(self):
        """Lazy database session"""
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        """Close database session after task completion"""
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(base=DatabaseTask, bind=True, name="tasks.process_document_async")
def process_document_async(self, document_id: int, file_path: str, user_id: int):
    """
    Process a document asynchronously

    Args:
        document_id: Database document ID
        file_path: Local file path or S3 key
        user_id: User ID for multi-tenant isolation

    Returns:
        dict: Processing result
    """
    logger.info(
        f"🔄 Celery task started: process_document_async(document_id={document_id})"
    )

    try:
        # Get document from database
        doc = self.db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"❌ Document ID={document_id} not found in database")
            return {"status": "error", "message": "Document not found"}

        # Update status to processing
        doc.status = DocumentStatus.PROCESSING
        self.db.commit()
        logger.info(f"📝 Document status updated to PROCESSING")

        # Download file from S3 if using S3
        if s3_storage.use_s3:
            logger.info(f"📥 Downloading file from S3: {file_path}")
            try:
                file_content = s3_storage.download_file(file_path)

                # Save to temporary local file for processing
                temp_path = Path(f"/tmp/{document_id}_{Path(file_path).name}")
                with open(temp_path, "wb") as f:
                    f.write(file_content)

                processing_file_path = str(temp_path)
                logger.info(f"✅ File downloaded to temp: {processing_file_path}")
            except Exception as e:
                logger.error(f"❌ Failed to download from S3: {str(e)}")
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"Failed to download file from S3: {str(e)}"
                self.db.commit()
                return {"status": "error", "message": str(e)}
        else:
            # Use local file path directly
            processing_file_path = file_path
            logger.info(f"📂 Using local file: {processing_file_path}")

        # Process document with AI
        try:
            logger.info(f"🤖 Starting AI processing...")
            processor = StructuredDocumentProcessor()
            result = processor.process_document(processing_file_path)

            if result["status"] == "success":
                # Save extracted data to database
                doc.extracted_data_json = result["extracted_data"].model_dump_json()
                doc.status = DocumentStatus.COMPLETED
                doc.processed_date = datetime.utcnow()
                self.db.commit()

                logger.info(f"✅ Document processed successfully: ID={document_id}")

                # Clean up temp file if using S3
                if s3_storage.use_s3 and Path(processing_file_path).exists():
                    os.remove(processing_file_path)
                    logger.info(f"🗑️  Cleaned up temp file: {processing_file_path}")

                return {
                    "status": "success",
                    "document_id": document_id,
                    "extracted_data": result["extracted_data"].model_dump(),
                }
            else:
                # Processing failed
                error_msg = result.get("error", "Unknown processing error")
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_msg
                self.db.commit()

                logger.error(f"❌ Document processing failed: {error_msg}")

                # Clean up temp file
                if s3_storage.use_s3 and Path(processing_file_path).exists():
                    os.remove(processing_file_path)

                return {"status": "error", "message": error_msg}

        except Exception as e:
            # Exception during processing
            error_msg = f"Processing exception: {str(e)}"
            doc.status = DocumentStatus.FAILED
            doc.error_message = error_msg
            self.db.commit()

            logger.error(f"❌ Exception during processing: {error_msg}")
            import traceback

            logger.error(f"Traceback:\n{traceback.format_exc()}")

            # Clean up temp file
            if s3_storage.use_s3 and Path(processing_file_path).exists():
                os.remove(processing_file_path)

            raise  # Re-raise for Celery retry mechanism

    except Exception as e:
        logger.error(f"❌ Critical error in Celery task: {str(e)}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")

        # Try to update document status
        try:
            doc = self.db.query(Document).filter(Document.id == document_id).first()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"Critical task error: {str(e)}"
                self.db.commit()
        except:
            pass

        raise  # Re-raise for Celery retry


@celery_app.task(
    base=DatabaseTask, bind=True, name="tasks.process_bulk_documents_async"
)
def process_bulk_documents_async(
    self, document_ids: list, file_paths: list, user_id: int
):
    """
    Process multiple documents asynchronously

    Args:
        document_ids: List of document IDs
        file_paths: List of file paths or S3 keys
        user_id: User ID for multi-tenant isolation

    Returns:
        dict: Bulk processing result
    """
    logger.info(
        f"🔄 Celery task started: process_bulk_documents_async(count={len(document_ids)})"
    )

    results = []
    successful = 0
    failed = 0

    # Process each document
    for doc_id, file_path in zip(document_ids, file_paths):
        try:
            # Call single document processing task
            result = process_document_async(doc_id, file_path, user_id)

            results.append(
                {"document_id": doc_id, "status": result.get("status", "error")}
            )

            if result.get("status") == "success":
                successful += 1
            else:
                failed += 1

        except Exception as e:
            logger.error(f"❌ Failed to process document ID={doc_id}: {str(e)}")
            results.append(
                {"document_id": doc_id, "status": "error", "message": str(e)}
            )
            failed += 1

    logger.info(
        f"✅ Bulk processing completed: {successful} successful, {failed} failed"
    )

    return {
        "status": "completed",
        "total": len(document_ids),
        "successful": successful,
        "failed": failed,
        "results": results,
    }


@celery_app.task(name="tasks.cleanup_old_files")
def cleanup_old_files(days: int = 365):
    """
    Cleanup old files from S3 or local storage

    Args:
        days: Delete files older than this many days

    Returns:
        dict: Cleanup result
    """
    logger.info(f"🧹 Starting cleanup: files older than {days} days")

    from datetime import timedelta

    from database import SessionLocal

    db = SessionLocal()
    deleted_count = 0

    try:
        # Find old documents
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        old_docs = db.query(Document).filter(Document.created_at < cutoff_date).all()

        logger.info(f"Found {len(old_docs)} documents to clean up")

        for doc in old_docs:
            try:
                # Delete file from storage
                if s3_storage.delete_file(doc.file_path):
                    # Delete database record
                    db.delete(doc)
                    deleted_count += 1
                    logger.info(f"✅ Deleted document ID={doc.id}")
            except Exception as e:
                logger.error(f"❌ Failed to delete document ID={doc.id}: {str(e)}")

        db.commit()
        logger.info(f"✅ Cleanup completed: {deleted_count} documents deleted")

        return {
            "status": "success",
            "deleted_count": deleted_count,
            "total_found": len(old_docs),
        }

    except Exception as e:
        logger.error(f"❌ Cleanup failed: {str(e)}")
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
