"""
Document Queue Manager (Item 8 - Upload Queue)

Limits concurrent document processing to prevent system overload.
Documents exceeding MAX_CONCURRENT are queued with a position number.
When a document finishes processing, the next queued document starts automatically.

Usage in upload endpoint:
    queue_manager = DocumentQueueManager(db)
    result = queue_manager.enqueue(document_id, file_path, background_tasks)

Usage after processing completes (inside background task):
    trigger_next_queued_document(process_func)
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from database import Document, DocumentStatus

logger = logging.getLogger(__name__)

# Maximum number of documents being processed simultaneously
MAX_CONCURRENT = 3


@dataclass
class EnqueueResult:
    """Result of enqueueing a document"""

    document_id: int
    queued: bool  # True if queued (not processing immediately)
    queue_position: Optional[int] = None  # Position in queue (None if processing)
    message: str = ""


class DocumentQueueManager:
    """
    Manages document processing queue.

    Limits concurrent processing to MAX_CONCURRENT documents.
    Excess documents are queued and processed in FIFO order.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_processing_count(self) -> int:
        """Get number of documents currently being processed"""
        return (
            self.db.query(func.count(Document.id))
            .filter(Document.status == DocumentStatus.PROCESSING)
            .scalar()
            or 0
        )

    def get_queue_length(self) -> int:
        """Get number of documents waiting in queue"""
        return (
            self.db.query(func.count(Document.id))
            .filter(
                and_(
                    Document.status == DocumentStatus.PENDING,
                    Document.queue_position.isnot(None),
                )
            )
            .scalar()
            or 0
        )

    def get_next_queue_position(self) -> int:
        """Get the next available queue position"""
        max_pos = (
            self.db.query(func.max(Document.queue_position))
            .filter(Document.queue_position.isnot(None))
            .scalar()
        )
        return (max_pos or 0) + 1

    def enqueue(
        self,
        document_id: int,
        file_path: str,
        process_func: Callable,
        background_tasks=None,
    ) -> EnqueueResult:
        """
        Enqueue a document for processing.

        If under MAX_CONCURRENT, starts processing immediately.
        Otherwise, assigns a queue position and waits.

        Args:
            document_id: Document ID to process
            file_path: Path to the file
            process_func: Background processing function to call
            background_tasks: FastAPI BackgroundTasks instance

        Returns:
            EnqueueResult with queue status
        """
        processing_count = self.get_processing_count()

        if processing_count < MAX_CONCURRENT:
            # Under limit - process immediately
            if background_tasks:
                background_tasks.add_task(process_func, document_id, file_path)
            else:
                # Scheduler/retry context — no BackgroundTasks available, use thread
                t = threading.Thread(
                    target=process_func,
                    args=(document_id, file_path),
                    daemon=True,
                    name=f"retry-doc-{document_id}",
                )
                t.start()

            logger.info(
                f"Queue: Document {document_id} processing immediately "
                f"({processing_count + 1}/{MAX_CONCURRENT} slots used)"
            )

            return EnqueueResult(
                document_id=document_id,
                queued=False,
                message="Processamento iniciado imediatamente.",
            )
        else:
            # Over limit - queue it
            position = self.get_next_queue_position()
            doc = self.db.query(Document).get(document_id)

            if doc:
                doc.queue_position = position
                doc.queued_at = datetime.utcnow()
                self.db.commit()

            logger.info(
                f"Queue: Document {document_id} queued at position {position} "
                f"({MAX_CONCURRENT}/{MAX_CONCURRENT} slots full, "
                f"{self.get_queue_length()} in queue)"
            )

            return EnqueueResult(
                document_id=document_id,
                queued=True,
                queue_position=position,
                message=f"Documento na fila de processamento (posição {position}). "
                f"Você pode tomar um café enquanto processamos!",
            )

    def process_next(self, process_func: Callable) -> Optional[int]:
        """
        Start processing the next queued document (if any and under limit).

        Launches the process_func in a new thread since this is called
        from inside a background task (no BackgroundTasks available).

        Args:
            process_func: Background processing function (document_id, file_path)

        Returns:
            Document ID that started processing, or None if nothing to process
        """
        processing_count = self.get_processing_count()

        if processing_count >= MAX_CONCURRENT:
            return None

        # Get next queued document (lowest position)
        next_doc = (
            self.db.query(Document)
            .filter(
                and_(
                    Document.status == DocumentStatus.PENDING,
                    Document.queue_position.isnot(None),
                )
            )
            .order_by(Document.queue_position.asc())
            .first()
        )

        if not next_doc:
            return None

        # Capture values before clearing (avoid lazy-load issues after commit)
        doc_id = next_doc.id
        doc_file_path = next_doc.file_path

        # Clear queue position and mark for processing
        next_doc.queue_position = None
        next_doc.queued_at = None
        self.db.commit()

        # Start processing in a new daemon thread
        t = threading.Thread(
            target=process_func,
            args=(doc_id, doc_file_path),
            daemon=True,
            name=f"queue-process-doc-{doc_id}",
        )
        t.start()

        logger.info(
            f"Queue: Document {doc_id} dequeued and started processing "
            f"({processing_count + 1}/{MAX_CONCURRENT} slots used)"
        )

        return doc_id

    def get_queue_status(self) -> dict:
        """
        Get current queue status information.

        Returns:
            Dict with queue info for API response
        """
        processing_count = self.get_processing_count()
        queue_length = self.get_queue_length()

        return {
            "processing_count": processing_count,
            "max_concurrent": MAX_CONCURRENT,
            "queue_length": queue_length,
            "slots_available": max(0, MAX_CONCURRENT - processing_count),
            "estimated_wait_minutes": queue_length * 2,  # ~2 min per document
        }

    def get_document_queue_position(self, document_id: int) -> Optional[int]:
        """Get the queue position for a specific document"""
        doc = self.db.query(Document).get(document_id)
        if doc and doc.queue_position is not None:
            return doc.queue_position
        return None


def trigger_next_queued_document(process_func: Callable) -> Optional[int]:
    """
    Convenience function to trigger the next queued document.

    Called from inside process_document_background after a document
    finishes (COMPLETED or FAILED). Creates its own DB session.

    Args:
        process_func: The process_document_background function

    Returns:
        Document ID that started processing, or None
    """
    from database import SessionLocal

    db = None
    try:
        db = SessionLocal()
        queue_manager = DocumentQueueManager(db)
        return queue_manager.process_next(process_func)
    except Exception as e:
        logger.error(f"Queue: Error triggering next document: {e}")
        return None
    finally:
        if db:
            db.close()
