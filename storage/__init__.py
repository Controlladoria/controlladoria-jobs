"""
Storage Module
Handles file storage (local filesystem or S3)
"""

from .s3_service import s3_storage

__all__ = ["s3_storage"]
