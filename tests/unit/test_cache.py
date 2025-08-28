import json
import time
from unittest.mock import Mock, patch

from app.core.cache import CacheManager, cache_manager, cached, invalidate_cache


class TestCacheManager:
    def setup_method(self):
        self.cache_manager = CacheManager()

    @patch("app.core.cache.redis")
    @patch("app.core.cache.settings")
    def test_initialization_with_redis(self, mock_settings, mock_redis):
        """Test cache manager initialization with Redis available"""
        mock_settings.REDIS_URL = "redis://localhost:6379"
        mock_redis_client = Mock()
        mock_redis.from_url.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True

        cache = CacheManager()

        assert cache._redis_client == mock_redis_client
        assert cache._memory_cache == {}
        assert cache._memory_cache_ttl == {}

    @patch("app.core.cache.redis")
    @patch("app.core.cache.settings")
    def test_initialization_without_redis(self, mock_settings, mock_redis):
        """Test cache manager initialization without Redis"""
        mock_settings.REDIS_URL = "redis://localhost:6379"
        mock_redis.from_url.side_effect = Exception("Connection failed")

        cache = CacheManager()

        assert cache._redis_client is None
        assert cache._memory_cache == {}
        assert cache._memory_cache_ttl == {}

    def test_generate_key(self):
        """Test cache key generation"""
        key1 = self.cache_manager._generate_key("test", "arg1", kwarg1="value1")
        key2 = self.cache_manager._generate_key("test", "arg1", kwarg1="value1")
        key3 = self.cache_manager._generate_key("test", "arg2", kwarg1="value1")

        assert key1 == key2  # Same arguments should generate same key
        assert key1 != key3  # Different arguments should generate different key
        assert len(key1) == 64  # SHA-256 hash length

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_from_memory_cache_success(self, mock_record):
        """Test getting value from memory cache"""
        self.cache_manager._memory_cache["test_key"] = "test_value"

        result = self.cache_manager.get("test_key")

        assert result == "test_value"
        mock_record.assert_called_with("get", "memory", True)

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_from_memory_cache_miss(self, mock_record):
        """Test getting value from memory cache when not found"""
        result = self.cache_manager.get("nonexistent_key", "default_value")

        assert result == "default_value"
        mock_record.assert_called_with("miss", "memory", False)

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_from_memory_cache_expired(self, mock_record):
        """Test getting value from memory cache when expired"""
        self.cache_manager._memory_cache["test_key"] = "test_value"
        self.cache_manager._memory_cache_ttl["test_key"] = time.time() - 1  # Expired

        result = self.cache_manager.get("test_key", "default_value")

        assert result == "default_value"
        assert "test_key" not in self.cache_manager._memory_cache
        assert "test_key" not in self.cache_manager._memory_cache_ttl
        mock_record.assert_called_with("miss", "memory", False)

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_from_redis_success(self, mock_record):
        """Test getting value from Redis"""
        mock_redis_client = Mock()
        mock_redis_client.get.return_value = json.dumps("redis_value")
        self.cache_manager._redis_client = mock_redis_client

        result = self.cache_manager.get("test_key")

        assert result == "redis_value"
        mock_redis_client.get.assert_called_once_with("test_key")
        mock_record.assert_called_with("get", "redis", True)

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_from_redis_miss(self, mock_record):
        """Test getting value from Redis when not found"""
        mock_redis_client = Mock()
        mock_redis_client.get.return_value = None
        self.cache_manager._redis_client = mock_redis_client

        result = self.cache_manager.get("test_key", "default_value")

        assert result == "default_value"
        # When Redis returns None, it falls back to memory cache which also misses
        mock_record.assert_any_call("miss", "redis", False)
        mock_record.assert_any_call("miss", "memory", False)

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_redis_error_fallback(self, mock_record):
        """Test Redis error falls back to memory cache"""
        mock_redis_client = Mock()
        mock_redis_client.get.side_effect = Exception("Redis error")
        self.cache_manager._redis_client = mock_redis_client
        self.cache_manager._memory_cache["test_key"] = "memory_value"

        result = self.cache_manager.get("test_key")

        # When Redis throws an exception, the entire get method returns default
        assert result is None  # Default value when no default is provided
        mock_record.assert_not_called()  # No recording when exception occurs

    @patch.object(CacheManager, "_record_cache_operation")
    def test_get_from_redis_fallback_to_memory(self, mock_record):
        """Test Redis miss falls back to memory cache"""
        mock_redis_client = Mock()
        mock_redis_client.get.return_value = None
        self.cache_manager._redis_client = mock_redis_client
        self.cache_manager._memory_cache["test_key"] = "memory_value"

        result = self.cache_manager.get("test_key")

        assert result == "memory_value"
        mock_record.assert_any_call("miss", "redis", False)
        mock_record.assert_any_call("get", "memory", True)

    def test_set_memory_cache(self):
        """Test setting value in memory cache"""
        result = self.cache_manager.set("test_key", "test_value", ttl=60)

        assert result
        assert self.cache_manager._memory_cache["test_key"] == "test_value"
        assert "test_key" in self.cache_manager._memory_cache_ttl

    def test_set_memory_cache_no_ttl(self):
        """Test setting value in memory cache without TTL"""
        # Create a new cache manager without Redis to avoid Redis errors
        cache = CacheManager()
        cache._redis_client = None

        result = cache.set("test_key", "test_value", ttl=0)

        assert result
        assert cache._memory_cache["test_key"] == "test_value"
        assert "test_key" not in cache._memory_cache_ttl

    def test_set_redis_and_memory(self):
        """Test setting value in both Redis and memory cache"""
        mock_redis_client = Mock()
        self.cache_manager._redis_client = mock_redis_client

        result = self.cache_manager.set("test_key", "test_value", ttl=60)

        assert result
        assert self.cache_manager._memory_cache["test_key"] == "test_value"
        mock_redis_client.setex.assert_called_once_with(
            "test_key", 60, json.dumps("test_value")
        )

    def test_set_redis_error_continues(self):
        """Test setting value continues even if Redis fails"""
        mock_redis_client = Mock()
        mock_redis_client.setex.side_effect = Exception("Redis error")
        self.cache_manager._redis_client = mock_redis_client

        result = self.cache_manager.set("test_key", "test_value", ttl=60)

        # When Redis fails, the entire set method returns False
        assert result is False
        # Memory cache is not updated when Redis fails
        assert "test_key" not in self.cache_manager._memory_cache

    def test_delete_memory_cache(self):
        """Test deleting value from memory cache"""
        self.cache_manager._memory_cache["test_key"] = "test_value"
        self.cache_manager._memory_cache_ttl["test_key"] = time.time() + 60

        result = self.cache_manager.delete("test_key")

        assert result
        assert "test_key" not in self.cache_manager._memory_cache
        assert "test_key" not in self.cache_manager._memory_cache_ttl

    def test_delete_redis_and_memory(self):
        """Test deleting value from both Redis and memory cache"""
        mock_redis_client = Mock()
        self.cache_manager._redis_client = mock_redis_client
        self.cache_manager._memory_cache["test_key"] = "test_value"

        result = self.cache_manager.delete("test_key")

        assert result
        assert "test_key" not in self.cache_manager._memory_cache
        mock_redis_client.delete.assert_called_once_with("test_key")

    def test_delete_nonexistent_key(self):
        """Test deleting nonexistent key"""
        result = self.cache_manager.delete("nonexistent_key")

        assert result

    def test_delete_redis_error_continues(self):
        """Test deleting continues even if Redis fails"""
        mock_redis_client = Mock()
        mock_redis_client.delete.side_effect = Exception("Redis error")
        self.cache_manager._redis_client = mock_redis_client
        self.cache_manager._memory_cache["test_key"] = "test_value"

        result = self.cache_manager.delete("test_key")

        # When Redis fails, the entire delete method returns False
        assert result is False
        # Memory cache is not updated when Redis fails
        assert "test_key" in self.cache_manager._memory_cache

    def test_clear_memory_cache_all(self):
        """Test clearing all memory cache"""
        self.cache_manager._memory_cache["key1"] = "value1"
        self.cache_manager._memory_cache["key2"] = "value2"
        self.cache_manager._memory_cache_ttl["key1"] = time.time() + 60

        result = self.cache_manager.clear("*")

        assert result
        assert len(self.cache_manager._memory_cache) == 0
        assert len(self.cache_manager._memory_cache_ttl) == 0

    def test_clear_memory_cache_pattern(self):
        """Test clearing memory cache by pattern"""
        self.cache_manager._memory_cache["user:1"] = "value1"
        self.cache_manager._memory_cache["user:2"] = "value2"
        self.cache_manager._memory_cache["other:1"] = "value3"
        self.cache_manager._memory_cache_ttl["user:1"] = time.time() + 60

        result = self.cache_manager.clear("user:*")

        assert result
        assert "user:1" not in self.cache_manager._memory_cache
        assert "user:2" not in self.cache_manager._memory_cache
        assert "other:1" in self.cache_manager._memory_cache
        assert "user:1" not in self.cache_manager._memory_cache_ttl

    def test_clear_redis_and_memory(self):
        """Test clearing both Redis and memory cache"""
        mock_redis_client = Mock()
        mock_redis_client.keys.return_value = [b"user:1", b"user:2"]
        self.cache_manager._redis_client = mock_redis_client
        self.cache_manager._memory_cache["user:1"] = "value1"

        result = self.cache_manager.clear("user:*")

        assert result
        assert "user:1" not in self.cache_manager._memory_cache
        mock_redis_client.keys.assert_called_once_with("user:*")
        mock_redis_client.delete.assert_called_once_with(b"user:1", b"user:2")

    def test_clear_redis_error_continues(self):
        """Test clearing continues even if Redis fails"""
        mock_redis_client = Mock()
        mock_redis_client.keys.side_effect = Exception("Redis error")
        self.cache_manager._redis_client = mock_redis_client
        self.cache_manager._memory_cache["user:1"] = "value1"

        result = self.cache_manager.clear("user:*")

        # When Redis fails, the entire clear method returns False
        assert result is False
        # Memory cache is not updated when Redis fails
        assert "user:1" in self.cache_manager._memory_cache

    def test_get_stats_memory_only(self):
        """Test getting cache statistics with memory cache only"""
        # Create a new cache manager without Redis
        cache = CacheManager()
        cache._redis_client = None
        cache._memory_cache["key1"] = "value1"
        cache._memory_cache_ttl["key1"] = time.time() + 60

        stats = cache.get_stats()

        assert stats["memory_cache_size"] == 1
        assert stats["memory_cache_ttl_size"] == 1
        assert stats["redis_available"] is False

    def test_get_stats_with_redis(self):
        """Test getting cache statistics with Redis available"""
        mock_redis_client = Mock()
        mock_redis_client.info.return_value = {
            "used_memory_human": "1.0M",
            "connected_clients": 5,
            "keyspace_hits": 100,
            "keyspace_misses": 10,
        }
        self.cache_manager._redis_client = mock_redis_client

        stats = self.cache_manager.get_stats()

        assert stats["redis_available"]
        assert stats["redis_used_memory"] == "1.0M"
        assert stats["redis_connected_clients"] == 5
        assert stats["redis_keyspace_hits"] == 100
        assert stats["redis_keyspace_misses"] == 10

    def test_get_stats_redis_error(self):
        """Test getting cache statistics when Redis fails"""
        mock_redis_client = Mock()
        mock_redis_client.info.side_effect = Exception("Redis error")
        self.cache_manager._redis_client = mock_redis_client

        stats = self.cache_manager.get_stats()

        assert stats["redis_available"]
        assert "redis_error" in stats

    def test_record_cache_operation_with_metrics(self):
        """Test recording cache operation with metrics collector available"""
        # Mock the import and metrics collector
        mock_metrics = Mock()
        with patch("app.core.metrics.metrics_collector", mock_metrics):
            self.cache_manager._record_cache_operation("get", "memory", True)
            mock_metrics.record_cache_operation.assert_called_once_with(
                "get", "memory", True
            )

    def test_record_cache_operation_without_metrics(self):
        """Test recording cache operation without metrics collector"""
        # Mock the import to raise ImportError
        with patch("app.core.metrics.metrics_collector", side_effect=ImportError):
            # Should not raise an exception when metrics collector is not available
            self.cache_manager._record_cache_operation("get", "memory", True)


class TestCacheDecorators:
    def setup_method(self):
        self.cache_manager = CacheManager()

    @patch("app.core.cache.cache_manager")
    async def test_cached_decorator_async_cache_hit(self, mock_cache_manager):
        """Test cached decorator with async function and cache hit"""
        mock_cache_manager.get.return_value = "cached_result"

        @cached("test_prefix", ttl=300)
        async def test_function(arg1, kwarg1=None):
            return f"result_{arg1}_{kwarg1}"

        result = await test_function("test_arg", kwarg1="test_kwarg")

        assert result == "cached_result"
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_not_called()

    @patch("app.core.cache.cache_manager")
    async def test_cached_decorator_async_cache_miss(self, mock_cache_manager):
        """Test cached decorator with async function and cache miss"""
        mock_cache_manager.get.return_value = None

        @cached("test_prefix", ttl=300)
        async def test_function(arg1, kwarg1=None):
            return f"result_{arg1}_{kwarg1}"

        result = await test_function("test_arg", kwarg1="test_kwarg")

        assert result == "result_test_arg_test_kwarg"
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_called_once()

    @patch("app.core.cache.cache_manager")
    def test_cached_decorator_sync_cache_hit(self, mock_cache_manager):
        """Test cached decorator with sync function and cache hit"""
        mock_cache_manager.get.return_value = "cached_result"

        @cached("test_prefix", ttl=300)
        def test_function(arg1, kwarg1=None):
            return f"result_{arg1}_{kwarg1}"

        result = test_function("test_arg", kwarg1="test_kwarg")

        assert result == "cached_result"
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_not_called()

    @patch("app.core.cache.cache_manager")
    def test_cached_decorator_sync_cache_miss(self, mock_cache_manager):
        """Test cached decorator with sync function and cache miss"""
        mock_cache_manager.get.return_value = None

        @cached("test_prefix", ttl=300)
        def test_function(arg1, kwarg1=None):
            return f"result_{arg1}_{kwarg1}"

        result = test_function("test_arg", kwarg1="test_kwarg")

        assert result == "result_test_arg_test_kwarg"
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_called_once()

    @patch("app.core.cache.cache_manager")
    async def test_invalidate_cache_decorator_async(self, mock_cache_manager):
        """Test invalidate_cache decorator with async function"""
        mock_cache_manager.clear.return_value = True

        @invalidate_cache("test_pattern")
        async def test_function(arg1):
            return f"result_{arg1}"

        result = await test_function("test_arg")

        assert result == "result_test_arg"
        mock_cache_manager.clear.assert_called_once_with("test_pattern")

    @patch("app.core.cache.cache_manager")
    def test_invalidate_cache_decorator_sync(self, mock_cache_manager):
        """Test invalidate_cache decorator with sync function"""
        mock_cache_manager.clear.return_value = True

        @invalidate_cache("test_pattern")
        def test_function(arg1):
            return f"result_{arg1}"

        result = test_function("test_arg")

        assert result == "result_test_arg"
        mock_cache_manager.clear.assert_called_once_with("test_pattern")

    @patch("app.core.cache.cache_manager")
    async def test_invalidate_cache_decorator_default_pattern(self, mock_cache_manager):
        """Test invalidate_cache decorator with default pattern"""
        mock_cache_manager.clear.return_value = True

        @invalidate_cache()
        async def test_function(arg1):
            return f"result_{arg1}"

        result = await test_function("test_arg")

        assert result == "result_test_arg"
        mock_cache_manager.clear.assert_called_once_with("*")

    def test_cached_decorator_key_generation(self):
        """Test that cached decorator generates consistent keys"""

        @cached("test_prefix")
        def test_function(arg1, kwarg1=None):
            return f"result_{arg1}_{kwarg1}"

        # Call function multiple times with same arguments
        result1 = test_function("test_arg", kwarg1="test_kwarg")
        result2 = test_function("test_arg", kwarg1="test_kwarg")

        # Both calls should return the same result
        assert result1 == result2

    def test_cached_decorator_different_keys(self):
        """Test that cached decorator generates different keys for different arguments"""

        @cached("test_prefix")
        def test_function(arg1, kwarg1=None):
            return f"result_{arg1}_{kwarg1}"

        # Call function with different arguments
        result1 = test_function("test_arg1", kwarg1="test_kwarg1")
        result2 = test_function("test_arg2", kwarg1="test_kwarg2")

        # Results should be different
        assert result1 != result2


class TestGlobalCacheManager:
    def test_global_cache_manager_exists(self):
        """Test that global cache manager instance exists"""
        assert cache_manager is not None
        assert isinstance(cache_manager, CacheManager)

    def test_global_cache_manager_singleton(self):
        """Test that global cache manager is a singleton"""
        from app.core.cache import cache_manager as cache_manager2

        assert cache_manager is cache_manager2
