"""Simple in-memory cache with TTL for performance optimization.

This module provides a lightweight caching mechanism for expensive database queries.
The cache is process-local and will be cleared on server restart.

For production deployments with multiple workers, consider using Redis or similar.

Enhanced for Phase 8E-008 with:
- Hit/miss statistics tracking
- Per-prefix statistics for monitoring Why Chain cache effectiveness
- Configurable max entries to prevent memory bloat
- Cache warmup support
"""

from datetime import datetime, timedelta
from typing import Any, TypeVar, Callable
from functools import wraps
from dataclasses import dataclass, field
import logging
import threading

logger = logging.getLogger("vizzy.cache")

T = TypeVar("T")


@dataclass
class CacheStats:
    """Statistics for cache operations.

    Tracks hits, misses, and other metrics for monitoring cache effectiveness.
    """
    hits: int = 0
    misses: int = 0
    expirations: int = 0
    evictions: int = 0
    sets: int = 0
    deletes: int = 0

    @property
    def total_requests(self) -> int:
        """Total number of get requests."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as a percentage (0-100)."""
        if self.total_requests == 0:
            return 0.0
        return (self.hits / self.total_requests) * 100

    @property
    def miss_rate(self) -> float:
        """Cache miss rate as a percentage (0-100)."""
        return 100.0 - self.hit_rate

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary for JSON serialization."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "expirations": self.expirations,
            "evictions": self.evictions,
            "sets": self.sets,
            "deletes": self.deletes,
            "total_requests": self.total_requests,
            "hit_rate": round(self.hit_rate, 2),
            "miss_rate": round(self.miss_rate, 2),
        }

    def reset(self) -> None:
        """Reset all statistics to zero."""
        self.hits = 0
        self.misses = 0
        self.expirations = 0
        self.evictions = 0
        self.sets = 0
        self.deletes = 0


class SimpleCache:
    """Simple in-memory cache with TTL (Time To Live).

    Thread-safe for read operations. Write operations should be considered
    eventually consistent in multi-threaded environments.

    Enhanced with statistics tracking and max entries limit.
    """

    def __init__(self, default_ttl: int = 300, max_entries: int = 10000):
        """Initialize the cache.

        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
            max_entries: Maximum number of entries to store (default: 10000)
        """
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._lock = threading.RLock()

        # Global statistics
        self._stats = CacheStats()

        # Per-prefix statistics for monitoring specific cache types
        self._prefix_stats: dict[str, CacheStats] = {}

        # Track last access time for LRU-style eviction
        self._access_times: dict[str, datetime] = {}

    def _get_prefix(self, key: str) -> str:
        """Extract the prefix from a cache key for statistics."""
        # Keys are typically formatted as "import:{id}:{type}:..." or "{type}:{id}:..."
        parts = key.split(":")
        if len(parts) >= 2:
            # For import-scoped keys, use the type portion
            if parts[0] == "import" and len(parts) >= 3:
                return parts[2]
            return parts[0]
        return "default"

    def _get_prefix_stats(self, key: str) -> CacheStats:
        """Get or create stats for a key's prefix."""
        prefix = self._get_prefix(key)
        if prefix not in self._prefix_stats:
            self._prefix_stats[prefix] = CacheStats()
        return self._prefix_stats[prefix]

    def _evict_if_needed(self) -> int:
        """Evict oldest entries if cache is at capacity.

        Returns the number of entries evicted.
        """
        if len(self._cache) < self._max_entries:
            return 0

        # Evict 10% of entries to avoid frequent eviction
        to_evict = max(1, self._max_entries // 10)
        evicted = 0

        # Sort by access time, evict oldest
        sorted_keys = sorted(
            self._access_times.keys(),
            key=lambda k: self._access_times.get(k, datetime.min)
        )

        for key in sorted_keys[:to_evict]:
            if key in self._cache:
                del self._cache[key]
                evicted += 1
            if key in self._access_times:
                del self._access_times[key]

        if evicted > 0:
            self._stats.evictions += evicted
            logger.info(f"Cache eviction: removed {evicted} oldest entries")

        return evicted

    def get(self, key: str) -> Any | None:
        """Get a value from the cache.

        Args:
            key: The cache key

        Returns:
            The cached value, or None if not found or expired
        """
        prefix_stats = self._get_prefix_stats(key)

        if key not in self._cache:
            self._stats.misses += 1
            prefix_stats.misses += 1
            return None

        value, expires = self._cache[key]
        if datetime.now() > expires:
            # Expired - clean up and return None
            with self._lock:
                if key in self._cache:
                    del self._cache[key]
                if key in self._access_times:
                    del self._access_times[key]
            self._stats.misses += 1
            self._stats.expirations += 1
            prefix_stats.misses += 1
            prefix_stats.expirations += 1
            logger.debug(f"Cache miss (expired): {key}")
            return None

        self._stats.hits += 1
        prefix_stats.hits += 1
        self._access_times[key] = datetime.now()
        logger.debug(f"Cache hit: {key}")
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value in the cache.

        Args:
            key: The cache key
            value: The value to cache
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        with self._lock:
            self._evict_if_needed()

            ttl = ttl if ttl is not None else self._default_ttl
            expires = datetime.now() + timedelta(seconds=ttl)
            self._cache[key] = (value, expires)
            self._access_times[key] = datetime.now()

            self._stats.sets += 1
            self._get_prefix_stats(key).sets += 1
            logger.debug(f"Cache set: {key} (ttl={ttl}s)")

    def delete(self, key: str) -> bool:
        """Delete a specific key from the cache.

        Args:
            key: The cache key to delete

        Returns:
            True if the key was found and deleted, False otherwise
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._access_times:
                    del self._access_times[key]
                self._stats.deletes += 1
                self._get_prefix_stats(key).deletes += 1
                logger.debug(f"Cache delete: {key}")
                return True
        return False

    def invalidate(self, pattern: str | None = None) -> int:
        """Invalidate cache entries matching a pattern.

        Args:
            pattern: Substring pattern to match against keys.
                    If None, clears the entire cache.

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                self._access_times.clear()
                self._stats.deletes += count
                logger.info(f"Cache cleared: {count} entries")
                return count

            keys_to_delete = [k for k in self._cache if pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
                if key in self._access_times:
                    del self._access_times[key]
                self._stats.deletes += 1
                self._get_prefix_stats(key).deletes += 1

            if keys_to_delete:
                logger.info(f"Cache invalidated: {len(keys_to_delete)} entries matching '{pattern}'")
            return len(keys_to_delete)

    def invalidate_import(self, import_id: int) -> int:
        """Invalidate all cache entries for a specific import.

        Args:
            import_id: The import ID to invalidate

        Returns:
            Number of entries invalidated
        """
        return self.invalidate(f"import:{import_id}")

    def cleanup_expired(self) -> int:
        """Remove all expired entries from the cache.

        Returns:
            Number of entries removed
        """
        with self._lock:
            now = datetime.now()
            expired_keys = [k for k, (_, expires) in self._cache.items() if now > expires]
            for key in expired_keys:
                del self._cache[key]
                if key in self._access_times:
                    del self._access_times[key]
                self._stats.expirations += 1
                self._get_prefix_stats(key).expirations += 1

            if expired_keys:
                logger.debug(f"Cache cleanup: {len(expired_keys)} expired entries removed")
            return len(expired_keys)

    @property
    def size(self) -> int:
        """Return the current number of entries in the cache."""
        return len(self._cache)

    @property
    def max_size(self) -> int:
        """Return the maximum number of entries allowed."""
        return self._max_entries

    @property
    def global_stats(self) -> CacheStats:
        """Return the global cache statistics object."""
        return self._stats

    def get_prefix_stats(self, prefix: str) -> CacheStats | None:
        """Get statistics for a specific cache prefix.

        Args:
            prefix: The cache key prefix (e.g., 'why_chain', 'contribution')

        Returns:
            CacheStats for the prefix, or None if no data exists
        """
        return self._prefix_stats.get(prefix)

    def get_all_prefix_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all tracked prefixes.

        Returns:
            Dictionary mapping prefix to stats dict
        """
        return {
            prefix: stats.to_dict()
            for prefix, stats in self._prefix_stats.items()
        }

    def reset_stats(self) -> None:
        """Reset all statistics to zero."""
        self._stats.reset()
        for stats in self._prefix_stats.values():
            stats.reset()
        logger.info("Cache statistics reset")

    def stats(self) -> dict[str, Any]:
        """Return comprehensive cache statistics.

        Returns:
            Dictionary with cache statistics including hit/miss rates
        """
        now = datetime.now()
        expired_count = sum(1 for _, (_, expires) in self._cache.items() if now > expires)
        return {
            "total_entries": len(self._cache),
            "max_entries": self._max_entries,
            "expired_entries": expired_count,
            "active_entries": len(self._cache) - expired_count,
            "default_ttl_seconds": self._default_ttl,
            "global": self._stats.to_dict(),
            "by_prefix": self.get_all_prefix_stats(),
        }

    def get_keys_by_prefix(self, prefix: str) -> list[str]:
        """Get all cache keys matching a prefix.

        Args:
            prefix: The prefix to match

        Returns:
            List of matching cache keys
        """
        return [k for k in self._cache.keys() if prefix in k]

    def get_entries_info(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get information about cached entries for debugging.

        Args:
            limit: Maximum entries to return

        Returns:
            List of dicts with key, expires, and size info
        """
        now = datetime.now()
        entries = []
        for i, (key, (value, expires)) in enumerate(self._cache.items()):
            if i >= limit:
                break
            entries.append({
                "key": key,
                "expires_in_seconds": max(0, (expires - now).total_seconds()),
                "is_expired": now > expires,
                "value_type": type(value).__name__,
            })
        return entries


# Global cache instance
cache = SimpleCache(default_ttl=300)


def cached(key_prefix: str, ttl: int | None = None):
    """Decorator for caching function results.

    Args:
        key_prefix: Prefix for the cache key
        ttl: Time-to-live in seconds (uses default if not specified)

    Example:
        @cached("clusters", ttl=60)
        def get_clusters(import_id: int) -> list[ClusterInfo]:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Build cache key from function arguments
            key_parts = [key_prefix]

            # Add positional args to key
            for arg in args:
                if isinstance(arg, (int, str, float, bool)):
                    key_parts.append(str(arg))

            # Add keyword args to key (sorted for consistency)
            for k, v in sorted(kwargs.items()):
                if isinstance(v, (int, str, float, bool)):
                    key_parts.append(f"{k}={v}")

            cache_key = ":".join(key_parts)

            # Check cache first
            result = cache.get(cache_key)
            if result is not None:
                return result

            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        return wrapper
    return decorator


def cache_key_for_import(prefix: str, import_id: int, *args) -> str:
    """Generate a cache key for import-specific data.

    Args:
        prefix: The cache key prefix (e.g., "clusters", "nodes")
        import_id: The import ID
        *args: Additional key components

    Returns:
        A formatted cache key string
    """
    parts = [f"import:{import_id}", prefix] + [str(a) for a in args]
    return ":".join(parts)
