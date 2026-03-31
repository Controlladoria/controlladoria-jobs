"""
Celery Application
Background task processing for document uploads and AI processing
"""

from celery import Celery

from config import settings

# Initialize Celery app
celery_app = Celery(
    "dresystem",
    broker=settings.celery_broker_url or settings.redis_url,
    backend=settings.celery_result_backend or settings.redis_url,
    include=["tasks.document_tasks"],  # Import task modules
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    # Performance settings
    task_acks_late=True,  # Acknowledge task after completion (for reliability)
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    task_time_limit=settings.celery_task_time_limit,  # Max 10 minutes per task
    task_soft_time_limit=settings.celery_task_time_limit - 60,  # Soft limit (9 min)
    # Result settings
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,  # Store extended task info
    # Retry settings
    task_autoretry_for=(Exception,),  # Auto-retry on any exception
    task_retry_kwargs={"max_retries": 3, "countdown": 5},  # 3 retries, 5 sec delay
    # Monitoring
    task_track_started=True,  # Track when task starts
    task_send_sent_event=True,  # Send task-sent events
)

# Task routes (optional - for organizing tasks)
celery_app.conf.task_routes = {
    "tasks.document_tasks.process_document_async": {"queue": "documents"},
    "tasks.document_tasks.process_bulk_documents_async": {"queue": "bulk"},
}

if __name__ == "__main__":
    celery_app.start()
