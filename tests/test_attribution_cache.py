"""Tests for attribution caching functionality (Phase 8E-008).

These tests verify:
- In-memory cache statistics tracking (hits, misses, evictions)
- Two-tier caching (memory + database)
- Cache warming for common packages
- Cache invalidation when imports are modified
- Cache TTL and expiration
- Thread safety of cache operations
"""

import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from vizzy.models import (
    WhyChainQuery,
    WhyChainResult,
    AttributionPath,
    DependencyDirection,
    EssentialityStatus,
    Node,
)
from vizzy.services.cache import SimpleCache, CacheStats, cache_key_for_import


class TestCacheStats:
    """Tests for CacheStats dataclass."""

    def test_initial_state(self):
        """Test stats are initialized to zero."""
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.expirations == 0
        assert stats.sets == 0
        assert stats.deletes == 0

    def test_total_requests(self):
        """Test total_requests computation."""
        stats = CacheStats(hits=10, misses=5)
        assert stats.total_requests == 15

    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        stats = CacheStats(hits=80, misses=20)
        assert stats.hit_rate == 80.0

        # Edge case: no requests
        empty_stats = CacheStats()
        assert empty_stats.hit_rate == 0.0

    def test_miss_rate_calculation(self):
        """Test miss rate is complement of hit rate."""
        stats = CacheStats(hits=70, misses=30)
        assert stats.miss_rate == 30.0
        assert stats.hit_rate + stats.miss_rate == 100.0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        stats = CacheStats(hits=100, misses=25, evictions=5, sets=125)
        d = stats.to_dict()
        assert d["hits"] == 100
        assert d["misses"] == 25
        assert d["evictions"] == 5
        assert d["sets"] == 125
        assert d["total_requests"] == 125
        assert d["hit_rate"] == 80.0

    def test_reset(self):
        """Test reset clears all counters."""
        stats = CacheStats(hits=100, misses=25, evictions=5)
        stats.reset()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0


class TestSimpleCache:
    """Tests for SimpleCache class."""

    def test_basic_set_get(self):
        """Test basic set and get operations."""
        cache = SimpleCache(default_ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss(self):
        """Test that missing keys return None."""
        cache = SimpleCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        cache = SimpleCache(default_ttl=1)  # 1 second TTL
        cache.set("key1", "value1", ttl=1)

        # Should be there immediately
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(1.1)

        # Should be gone now
        assert cache.get("key1") is None

    def test_custom_ttl(self):
        """Test setting custom TTL per entry."""
        cache = SimpleCache(default_ttl=60)
        cache.set("short_lived", "value", ttl=1)
        cache.set("long_lived", "value", ttl=3600)

        time.sleep(1.1)

        assert cache.get("short_lived") is None
        assert cache.get("long_lived") == "value"

    def test_delete(self):
        """Test delete operation."""
        cache = SimpleCache()
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        assert cache.delete("key1") is False  # Already deleted

    def test_invalidate_pattern(self):
        """Test pattern-based invalidation."""
        cache = SimpleCache()
        cache.set("prefix1:key1", "value1")
        cache.set("prefix1:key2", "value2")
        cache.set("prefix2:key1", "value1")

        count = cache.invalidate("prefix1")
        assert count == 2
        assert cache.get("prefix1:key1") is None
        assert cache.get("prefix1:key2") is None
        assert cache.get("prefix2:key1") == "value1"

    def test_invalidate_import(self):
        """Test import-specific invalidation."""
        cache = SimpleCache()
        cache.set("import:1:data1", "value1")
        cache.set("import:1:data2", "value2")
        cache.set("import:2:data1", "value1")

        count = cache.invalidate_import(1)
        assert count == 2
        assert cache.get("import:1:data1") is None
        assert cache.get("import:2:data1") == "value1"

    def test_cleanup_expired(self):
        """Test cleanup of expired entries."""
        cache = SimpleCache()
        cache.set("key1", "value1", ttl=1)
        cache.set("key2", "value2", ttl=3600)

        time.sleep(1.1)

        count = cache.cleanup_expired()
        assert count == 1
        assert cache.get("key2") == "value2"

    def test_statistics_tracking(self):
        """Test that statistics are properly tracked."""
        cache = SimpleCache()

        # Set some values
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Hit
        cache.get("key1")
        cache.get("key1")

        # Miss
        cache.get("nonexistent")

        stats = cache.global_stats
        assert stats.sets == 2
        assert stats.hits == 2
        assert stats.misses == 1
        assert stats.hit_rate == pytest.approx(66.67, rel=0.1)

    def test_max_entries_eviction(self):
        """Test that cache evicts old entries when at capacity."""
        cache = SimpleCache(default_ttl=60, max_entries=10)

        # Fill the cache
        for i in range(15):
            cache.set(f"key{i}", f"value{i}")
            time.sleep(0.01)  # Ensure different access times

        # Should have evicted some entries
        assert cache.size <= 10
        assert cache.global_stats.evictions > 0

    def test_prefix_stats(self):
        """Test per-prefix statistics tracking."""
        cache = SimpleCache()

        # Set entries with different prefixes
        cache.set("import:1:why_chain:node1", "value")
        cache.set("import:1:why_chain:node2", "value")
        cache.set("import:1:contribution:data", "value")

        # Access with different patterns
        cache.get("import:1:why_chain:node1")  # Hit
        cache.get("import:1:why_chain:node3")  # Miss

        why_chain_stats = cache.get_prefix_stats("why_chain")
        assert why_chain_stats is not None
        assert why_chain_stats.hits == 1
        assert why_chain_stats.misses == 1

    def test_get_entries_info(self):
        """Test getting entry information for debugging."""
        cache = SimpleCache()
        cache.set("key1", "value1", ttl=60)
        cache.set("key2", [1, 2, 3], ttl=120)

        entries = cache.get_entries_info(limit=10)
        assert len(entries) == 2

        # Check structure
        entry = entries[0]
        assert "key" in entry
        assert "expires_in_seconds" in entry
        assert "is_expired" in entry
        assert "value_type" in entry

    def test_stats_method(self):
        """Test comprehensive stats() method."""
        cache = SimpleCache(default_ttl=300, max_entries=1000)
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("miss")

        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["max_entries"] == 1000
        assert stats["default_ttl_seconds"] == 300
        assert "global" in stats
        assert "by_prefix" in stats


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_cache_key_for_import(self):
        """Test cache key generation for import-scoped data."""
        key = cache_key_for_import("why_chain", 1, 123, 10, True)
        assert "import:1" in key
        assert "why_chain" in key
        assert "123" in key

    def test_unique_keys_for_different_params(self):
        """Test that different parameters produce different keys."""
        key1 = cache_key_for_import("why_chain", 1, 123, 10, True)
        key2 = cache_key_for_import("why_chain", 1, 123, 10, False)
        key3 = cache_key_for_import("why_chain", 1, 123, 20, True)
        key4 = cache_key_for_import("why_chain", 2, 123, 10, True)

        assert len({key1, key2, key3, key4}) == 4


class TestAttributionCache:
    """Tests for the attribution cache service.

    Note: These tests require mocking the database connection
    since we don't want to depend on a real database in unit tests.
    """

    @pytest.fixture
    def mock_db(self):
        """Fixture to mock database connection."""
        with patch('vizzy.services.attribution_cache.get_db') as mock:
            conn = MagicMock()
            cur = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=None)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
            mock.return_value = conn
            yield mock, conn, cur

    @pytest.fixture
    def sample_query(self):
        """Fixture for a sample WhyChainQuery."""
        return WhyChainQuery(
            target_node_id=123,
            import_id=1,
            direction=DependencyDirection.REVERSE,
            max_depth=10,
            max_paths=100,
            include_build_deps=True,
        )

    @pytest.fixture
    def sample_node(self):
        """Fixture for a sample Node."""
        return Node(
            id=123,
            import_id=1,
            drv_hash="abc123",
            drv_name="glibc-2.39",
            label="glibc-2.39",
            package_type="library",
            depth=5,
            closure_size=100,
            metadata=None,
        )

    def test_is_common_package(self):
        """Test common package detection."""
        from vizzy.services.attribution_cache import _is_common_package

        assert _is_common_package("glibc-2.39") is True
        assert _is_common_package("gcc-13.2.0") is True
        assert _is_common_package("python3.11-numpy") is True
        assert _is_common_package("my-custom-app") is False

    def test_build_attribution_cache_key(self):
        """Test cache key building."""
        from vizzy.services.attribution_cache import _build_attribution_cache_key

        key = _build_attribution_cache_key(123, 1, 10, True)
        assert "why_chain" in key
        assert "123" in key
        assert "1" in key.split(":")[1] or "import:1" in key

    def test_get_cached_attribution_memory_hit(self, sample_query):
        """Test that memory cache is checked first."""
        from vizzy.services.attribution_cache import (
            get_cached_attribution,
            cache_attribution_result,
            _build_attribution_cache_key,
        )
        from vizzy.services.cache import cache

        # Pre-populate memory cache
        mock_result = MagicMock(spec=WhyChainResult)
        cache_key = _build_attribution_cache_key(
            sample_query.target_node_id,
            sample_query.import_id,
            sample_query.max_depth,
            sample_query.include_build_deps,
        )
        cache.set(cache_key, mock_result, ttl=60)

        # Should get from memory, not hit database
        with patch('vizzy.services.attribution_cache.get_db') as mock_db:
            result = get_cached_attribution(
                sample_query.target_node_id,
                sample_query,
            )
            # Memory cache hit - should not call database
            # Note: The current implementation still checks DB on miss,
            # but we verify the return value is correct
            assert result is mock_result

        # Clean up
        cache.delete(cache_key)

    def test_invalidate_attribution_cache(self, mock_db):
        """Test cache invalidation clears both tiers."""
        from vizzy.services.attribution_cache import invalidate_attribution_cache
        from vizzy.services.cache import cache

        mock, conn, cur = mock_db
        cur.rowcount = 5

        # Pre-populate some cache entries
        cache.set("import:1:why_chain:node1", "value")
        cache.set("import:1:why_chain:node2", "value")

        counts = invalidate_attribution_cache(1)

        assert "memory" in counts
        assert "database" in counts
        assert counts["database"] == 5

    def test_cache_ttl_constants(self):
        """Test that TTL constants are reasonable values."""
        from vizzy.services.attribution_cache import (
            MEMORY_CACHE_TTL,
            DB_CACHE_TTL,
            COMMON_PACKAGE_TTL,
        )

        # Memory cache should be shorter than DB cache
        assert MEMORY_CACHE_TTL < DB_CACHE_TTL

        # Common packages should get longer TTL
        assert COMMON_PACKAGE_TTL >= DB_CACHE_TTL

        # All should be positive
        assert MEMORY_CACHE_TTL > 0
        assert DB_CACHE_TTL > 0
        assert COMMON_PACKAGE_TTL > 0


class TestCacheIntegration:
    """Integration tests for cache functionality.

    These tests verify the full cache flow but still mock the database.
    """

    def test_cache_decorator_flow(self):
        """Test the @cached decorator works correctly."""
        from vizzy.services.cache import cached, cache

        call_count = 0

        @cached("test_decorator", ttl=60)
        def expensive_function(arg1, arg2):
            nonlocal call_count
            call_count += 1
            return arg1 + arg2

        # First call - should compute
        result1 = expensive_function(1, 2)
        assert result1 == 3
        assert call_count == 1

        # Second call - should use cache
        result2 = expensive_function(1, 2)
        assert result2 == 3
        assert call_count == 1  # Not incremented

        # Different args - should compute again
        result3 = expensive_function(3, 4)
        assert result3 == 7
        assert call_count == 2

        # Clean up
        cache.invalidate("test_decorator")

    def test_thread_safety(self):
        """Test that cache operations are thread-safe."""
        import threading

        cache = SimpleCache(max_entries=100)
        errors = []

        def writer():
            for i in range(100):
                try:
                    cache.set(f"key{threading.current_thread().name}_{i}", i)
                except Exception as e:
                    errors.append(e)

        def reader():
            for i in range(100):
                try:
                    cache.get(f"key_any_{i}")
                except Exception as e:
                    errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=writer, name=f"writer_{i}")
            threads.append(t)
            t = threading.Thread(target=reader, name=f"reader_{i}")
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestCacheManagementAPI:
    """Tests for cache management API endpoints.

    These would typically be run with pytest-asyncio and test client.
    For now, we test the underlying functions.
    """

    def test_get_attribution_cache_stats_structure(self):
        """Test cache stats have expected structure."""
        from vizzy.services.cache import cache

        # Reset stats for clean test
        cache.reset_stats()

        # Perform some operations
        cache.set("test:key", "value")
        cache.get("test:key")
        cache.get("test:missing")

        stats = cache.stats()

        # Verify structure
        assert "total_entries" in stats
        assert "max_entries" in stats
        assert "global" in stats
        assert "by_prefix" in stats

        global_stats = stats["global"]
        assert "hits" in global_stats
        assert "misses" in global_stats
        assert "hit_rate" in global_stats

        # Clean up
        cache.delete("test:key")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
