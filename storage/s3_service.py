"""
AWS S3 Storage Service
Handles file uploads, downloads, and deletions in S3
"""

import io
import os
import uuid
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

from config import settings


class S3StorageService:
    """S3 storage service for file operations"""

    def __init__(self):
        """Initialize S3 client"""
        self.use_s3 = settings.use_s3

        if self.use_s3:
            # Initialize S3 client with credentials from environment
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
                endpoint_url=settings.s3_endpoint_url
                or None,  # For S3-compatible services
            )
            self.bucket_name = settings.s3_bucket_name

            # Validate bucket exists
            try:
                self.s3_client.head_bucket(Bucket=self.bucket_name)
                print(f"[OK] S3 bucket '{self.bucket_name}' is accessible")
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code == "404":
                    print(f"[ERROR] S3 bucket '{self.bucket_name}' does not exist!")
                elif error_code == "403":
                    print(f"[ERROR] Access denied to S3 bucket '{self.bucket_name}'!")
                else:
                    print(f"[ERROR] S3 error: {str(e)}")
        else:
            print("[LOCAL] Using local filesystem storage (S3 disabled)")
            self.s3_client = None
            self.bucket_name = None

            # Ensure local upload directory exists
            os.makedirs("uploads", exist_ok=True)

    def generate_unique_filename(self, original_filename: str) -> str:
        """Generate unique filename with UUID prefix"""
        file_ext = Path(original_filename).suffix.lower()  # Always lowercase for consistency
        unique_id = str(uuid.uuid4())
        return f"{unique_id}{file_ext}"

    def upload_file(
        self,
        file_content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        user_id: Optional[int] = None,
    ) -> str:
        """
        Upload file to S3 or local filesystem

        Args:
            file_content: File bytes
            filename: Original filename
            content_type: MIME type
            user_id: User ID for multi-tenant organization

        Returns:
            str: File key/path for storage reference
        """
        unique_filename = self.generate_unique_filename(filename)

        # Organize files by user_id for multi-tenant isolation
        if user_id:
            file_key = f"users/{user_id}/{unique_filename}"
        else:
            file_key = f"uploads/{unique_filename}"

        if self.use_s3:
            # Upload to S3
            try:
                # URL encode filename for S3 metadata (S3 only accepts ASCII in metadata)
                # We still store the original filename in the database
                safe_filename = quote(filename, safe='')

                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=file_key,
                    Body=file_content,
                    ContentType=content_type,
                    ServerSideEncryption="AES256",  # Encrypt at rest
                    Metadata={
                        "original_filename": safe_filename,  # URL encoded to be ASCII-safe
                        "user_id": str(user_id) if user_id else "none",
                    },
                )
                print(f"[OK] Uploaded to S3: {file_key}")
                return file_key
            except ClientError as e:
                print(f"[ERROR] S3 upload failed: {str(e)}")
                raise Exception(f"Failed to upload file to S3: {str(e)}")
        else:
            # Save to local filesystem
            local_path = Path("uploads") / unique_filename
            local_path.parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, "wb") as f:
                f.write(file_content)

            print(f"[OK] Saved locally: {local_path}")
            return str(local_path)

    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        filename: str,
        content_type: str = "application/octet-stream",
        user_id: Optional[int] = None,
    ) -> str:
        """
        Upload file from file-like object (streaming, memory-efficient)

        **USE THIS for large files (>10MB)** to avoid loading entire file into memory.
        Streams file directly to S3 using multipart upload for files >5MB.

        Args:
            file_obj: File-like object (io.BytesIO, file handle, etc.)
            filename: Original filename
            content_type: MIME type
            user_id: User ID for multi-tenant organization

        Returns:
            str: File key/path for storage reference
        """
        unique_filename = self.generate_unique_filename(filename)

        # Organize files by user_id
        if user_id:
            file_key = f"users/{user_id}/{unique_filename}"
        else:
            file_key = f"uploads/{unique_filename}"

        if self.use_s3:
            # Stream upload to S3 (memory-efficient, uses multipart for large files)
            try:
                safe_filename = quote(filename, safe='')

                self.s3_client.upload_fileobj(
                    Fileobj=file_obj,
                    Bucket=self.bucket_name,
                    Key=file_key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "ServerSideEncryption": "AES256",
                        "Metadata": {
                            "original_filename": safe_filename,
                            "user_id": str(user_id) if user_id else "none",
                        },
                    },
                )
                print(f"[OK] Streamed to S3: {file_key}")
                return file_key
            except ClientError as e:
                print(f"[ERROR] S3 stream upload failed: {str(e)}")
                raise Exception(f"Failed to stream file to S3: {str(e)}")
        else:
            # Save to local filesystem (streaming)
            local_path = Path("uploads") / unique_filename
            local_path.parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, "wb") as f:
                # Stream in 8MB chunks
                while True:
                    chunk = file_obj.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)

            print(f"[OK] Streamed locally: {local_path}")
            return str(local_path)

    def validate_user_key(self, file_key: str, user_id: int) -> bool:
        """Validate that an S3 key belongs to the given user (defense-in-depth).

        Checks that the key follows the expected users/{user_id}/... pattern.
        Returns True if valid, False if the key doesn't match the user.
        """
        if self.use_s3:
            expected_prefix = f"users/{user_id}/"
            return file_key.startswith(expected_prefix)
        # Local filesystem uses UUID filenames, validated via DB query
        return True

    def download_file(self, file_key: str, user_id: Optional[int] = None) -> bytes:
        """
        Download file from S3 or local filesystem

        Args:
            file_key: S3 key or local path
            user_id: If provided, validates the key belongs to this user

        Returns:
            bytes: File content
        """
        if user_id is not None and not self.validate_user_key(file_key, user_id):
            raise PermissionError(f"Access denied: key does not belong to user {user_id}")

        if self.use_s3:
            # Download from S3
            try:
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name, Key=file_key
                )
                return response["Body"].read()
            except ClientError as e:
                print(f"[ERROR] S3 download failed: {str(e)}")
                raise Exception(f"Failed to download file from S3: {str(e)}")
        else:
            # Read from local filesystem
            local_path = Path(file_key)
            if not local_path.exists():
                raise FileNotFoundError(f"File not found: {file_key}")

            with open(local_path, "rb") as f:
                return f.read()

    def delete_file(self, file_key: str, user_id: Optional[int] = None) -> bool:
        """
        Delete file from S3 or local filesystem

        Args:
            file_key: S3 key or local path
            user_id: If provided, validates the key belongs to this user

        Returns:
            bool: True if deleted successfully
        """
        if user_id is not None and not self.validate_user_key(file_key, user_id):
            print(f"[ERROR] Access denied: key {file_key} does not belong to user {user_id}")
            return False
        if self.use_s3:
            # Delete from S3
            try:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_key)
                print(f"[OK] Deleted from S3: {file_key}")
                return True
            except ClientError as e:
                print(f"[ERROR] S3 deletion failed: {str(e)}")
                return False
        else:
            # Delete from local filesystem
            try:
                local_path = Path(file_key)
                if local_path.exists():
                    local_path.unlink()
                    print(f"[OK] Deleted locally: {file_key}")
                    return True
                return False
            except Exception as e:
                print(f"[ERROR] Local deletion failed: {str(e)}")
                return False

    def get_file_url(self, file_key: str, expires_in: int = 3600) -> str:
        """
        Generate presigned URL for file access (S3 only)

        Args:
            file_key: S3 key
            expires_in: URL expiration in seconds (default 1 hour)

        Returns:
            str: Presigned URL or local path
        """
        if self.use_s3:
            try:
                url = self.s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": file_key},
                    ExpiresIn=expires_in,
                )
                return url
            except ClientError as e:
                print(f"[ERROR] Failed to generate presigned URL: {str(e)}")
                raise Exception(f"Failed to generate file URL: {str(e)}")
        else:
            # For local filesystem, return the path (frontend will need to serve via API)
            return f"/api/files/{file_key}"

    def list_user_files(self, user_id: int, max_keys: int = 1000) -> list:
        """
        List all files for a user (S3 only)

        Args:
            user_id: User ID
            max_keys: Maximum number of files to return

        Returns:
            list: List of file keys
        """
        if self.use_s3:
            try:
                response = self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=f"users/{user_id}/",
                    MaxKeys=max_keys,
                )

                if "Contents" in response:
                    return [obj["Key"] for obj in response["Contents"]]
                return []
            except ClientError as e:
                print(f"[ERROR] Failed to list user files: {str(e)}")
                return []
        else:
            # For local filesystem, scan directory
            upload_dir = Path("uploads")
            if upload_dir.exists():
                return [str(f) for f in upload_dir.iterdir() if f.is_file()]
            return []

    def get_file_metadata(self, file_key: str) -> dict:
        """
        Get file metadata (S3 only)

        Args:
            file_key: S3 key or local path

        Returns:
            dict: File metadata
        """
        if self.use_s3:
            try:
                response = self.s3_client.head_object(
                    Bucket=self.bucket_name, Key=file_key
                )
                return {
                    "size": response.get("ContentLength", 0),
                    "content_type": response.get("ContentType", "unknown"),
                    "last_modified": response.get("LastModified"),
                    "metadata": response.get("Metadata", {}),
                }
            except ClientError as e:
                print(f"[ERROR] Failed to get file metadata: {str(e)}")
                return {}
        else:
            # For local filesystem, get file stats
            local_path = Path(file_key)
            if local_path.exists():
                stats = local_path.stat()
                return {
                    "size": stats.st_size,
                    "content_type": "unknown",
                    "last_modified": stats.st_mtime,
                }
            return {}


# Global S3 storage instance
s3_storage = S3StorageService()
