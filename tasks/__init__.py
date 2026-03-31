"""Tasks module - background processing and queue management"""

from .queue_manager import DocumentQueueManager, trigger_next_queued_document

__all__ = ["DocumentQueueManager", "trigger_next_queued_document"]
