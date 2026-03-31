"""
Redis Cache Service
High-performance caching layer for database queries and AI results
"""

import json
import pickle
from functools import wraps
from typing import Any, Callable, Optional

import redis
from redis.exceptions import RedisError

from config import settings


class RedisCache:
    """Redis cache service with connection pooling"""

    def __init__(self):
        """Initialize Redis connection pool"""
        try:
            self.redis_client = redis.from_url(
                settings.redis_url,
                max_connections=settings.redis_max_connections,
                decode_responses=False,  # We'll handle encoding/decoding
                socket_timeout=5,
                socket_connect_timeout=5,
            )

            # Test connection
            self.redis_client.ping()
            print(f"[OK] Redis connected: {settings.redis_url}")
            self.enabled = True
        except RedisError as e:
            print(f"[WARN]  Redis connection failed: {str(e)}")
            print("   Caching is disabled. Application will continue without cache.")
            self.redis_client = None
            self.enabled = False

    def _serialize(self, value: Any) -> bytes:
        """Serialize value for storage"""
        try:
            # Try JSON first (faster, human-readable in Redis)
            return json.dumps(value).encode("utf-8")
        except (TypeError, ValueError):
            # Fallback to pickle for complex objects
            return pickle.dumps(value)

    def _deserialize(self, value: bytes) -> Any:
        """Deserialize value from storage"""
        if not value:
            return None

        try:
            # Try JSON first
            return json.loads(value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Fallback to pickle
            return pickle.loads(value)

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if not self.enabled:
            return None

        try:
            value = self.redis_client.get(key)
            if value is None:
                return None
            return self._deserialize(value)
        except RedisError as e:
            print(f"[WARN]  Redis GET error for key '{key}': {str(e)}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value in cache

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (default from settings)

        Returns:
            bool: True if successful
        """
        if not self.enabled:
            return False

        try:
            serialized = self._serialize(value)
            ttl = ttl or settings.redis_cache_ttl

            if ttl:
                self.redis_client.setex(key, ttl, serialized)
            else:
                self.redis_client.set(key, serialized)

            return True
        except RedisError as e:
            print(f"[WARN]  Redis SET error for key '{key}': {str(e)}")
            return False

    def delete(self, key: str) -> bool:
        """
        Delete value from cache

        Args:
            key: Cache key

        Returns:
            bool: True if deleted
        """
        if not self.enabled:
            return False

        try:
            result = self.redis_client.delete(key)
            return result > 0
        except RedisError as e:
            print(f"[WARN]  Redis DELETE error for key '{key}': {str(e)}")
            return False

    def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern

        Args:
            pattern: Key pattern (e.g., "user:123:*")

        Returns:
            int: Number of keys deleted
        """
        if not self.enabled:
            return 0

        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except RedisError as e:
            print(
                f"[WARN]  Redis DELETE_PATTERN error for pattern '{pattern}': {str(e)}"
            )
            return 0

    def exists(self, key: str) -> bool:
        """
        Check if key exists in cache

        Args:
            key: Cache key

        Returns:
            bool: True if exists
        """
        if not self.enabled:
            return False

        try:
            return self.redis_client.exists(key) > 0
        except RedisError as e:
            print(f"[WARN]  Redis EXISTS error for key '{key}': {str(e)}")
            return False

    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """
        Increment counter

        Args:
            key: Cache key
            amount: Increment amount

        Returns:
            int: New value or None if error
        """
        if not self.enabled:
            return None

        try:
            return self.redis_client.incrby(key, amount)
        except RedisError as e:
            print(f"[WARN]  Redis INCREMENT error for key '{key}': {str(e)}")
            return None

    def cached(
        self,
        key_prefix: str,
        ttl: Optional[int] = None,
        key_func: Optional[Callable] = None,
    ):
        """
        Decorator for caching function results

        Args:
            key_prefix: Prefix for cache key
            ttl: Cache TTL in seconds
            key_func: Custom function to generate cache key from args

        Usage:
            @cache.cached("user_stats", ttl=300)
            def get_user_stats(user_id: int):
                # Expensive DB query
                return stats
        """

        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Generate cache key
                if key_func:
                    cache_key = f"{key_prefix}:{key_func(*args, **kwargs)}"
                else:
                    # Default: use first arg as key
                    arg_key = args[0] if args else "default"
                    cache_key = f"{key_prefix}:{arg_key}"

                # Try to get from cache
                cached_value = self.get(cache_key)
                if cached_value is not None:
                    print(f"[HIT] Cache HIT: {cache_key}")
                    return cached_value

                # Cache miss - call function
                print(f"[MISS] Cache MISS: {cache_key}")
                result = func(*args, **kwargs)

                # Store in cache
                self.set(cache_key, result, ttl=ttl)

                return result

            return wrapper

        return decorator

    def invalidate_user_cache(self, user_id: int):
        """
        Invalidate all cache entries for a user

        Args:
            user_id: User ID
        """
        patterns = [
            f"user:{user_id}:*",
            f"user_docs:{user_id}:*",
            f"user_stats:{user_id}:*",
            f"reports:{user_id}:*",
        ]

        total_deleted = 0
        for pattern in patterns:
            deleted = self.delete_pattern(pattern)
            total_deleted += deleted

        if total_deleted > 0:
            print(
                f"[DEL]  Invalidated {total_deleted} cache entries for user {user_id}"
            )

    def get_stats(self) -> dict:
        """
        Get Redis statistics

        Returns:
            dict: Redis info
        """
        if not self.enabled:
            return {"enabled": False}

        try:
            info = self.redis_client.info()
            return {
                "enabled": True,
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            }
        except RedisError as e:
            print(f"[WARN]  Redis INFO error: {str(e)}")
            return {"enabled": False, "error": str(e)}

    def flush_all(self):
        """
        Clear all cache (use with caution!)
        """
        if not self.enabled:
            return

        try:
            self.redis_client.flushdb()
            print("[DEL]  Cleared all cache")
        except RedisError as e:
            print(f"[WARN]  Redis FLUSH error: {str(e)}")


# Global cache instance
cache = RedisCache()
