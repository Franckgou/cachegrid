"""
tests/test_client_sdk.py
Test suite for CacheGrid Python Client SDK
"""

import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cachegrid.client.python_client import (
    CacheGridClient, SyncCacheGridClient,
    CacheGridError, CacheGridConnectionError, CacheGridTimeoutError
)

@pytest.mark.asyncio
class TestCacheGridClient:
    """Test async CacheGrid client"""
    
    async def test_client_initialization(self):
        """Test client initialization with different host formats"""
        # Single host string
        client1 = CacheGridClient('localhost:8080')
        assert len(client1.config.hosts) == 1
        assert client1.config.hosts[0] == 'http://localhost:8080'
        
        # Multiple hosts
        client2 = CacheGridClient(['localhost:8080', 'localhost:8081'])
        assert len(client2.config.hosts) == 2
        
        # Hosts with http prefix
        client3 = CacheGridClient(['http://localhost:8080'])
        assert client3.config.hosts[0] == 'http://localhost:8080'
    
    async def test_context_manager(self):
        """Test async context manager functionality"""
        async with CacheGridClient(['localhost:8080']) as client:
            assert client.session is not None
        
        # Session should be closed after context
        assert client.session is None or client.session.closed
    
    @pytest.mark.integration
    async def test_basic_operations(self):
        """Test basic cache operations against live server"""
        async with CacheGridClient(['localhost:8080'], timeout=5.0) as client:
            # Test set and get
            test_key = f"test_{int(time.time())}"
            test_value = {"message": "Hello World", "timestamp": time.time()}
            
            success = await client.set(test_key, test_value)
            assert success is True
            
            retrieved = await client.get(test_key)
            assert retrieved == test_value
            
            # Test non-existent key
            missing = await client.get("nonexistent_key_12345")
            assert missing is None
            
            # Test delete
            deleted = await client.delete(test_key)
            assert deleted is True
            
            # Verify deletion
            after_delete = await client.get(test_key)
            assert after_delete is None
    
    @pytest.mark.integration
    async def test_ttl_operations(self):
        """Test TTL functionality"""
        async with CacheGridClient(['localhost:8080']) as client:
            test_key = f"ttl_test_{int(time.time())}"
            
            # Set with short TTL
            await client.set(test_key, "temporary_value", ttl=1.0)
            
            # Should exist immediately
            value = await client.get(test_key)
            assert value == "temporary_value"
            
            # Wait for expiration
            await asyncio.sleep(1.5)
            
            # Should be expired
            expired_value = await client.get(test_key)
            assert expired_value is None
    
    @pytest.mark.integration
    async def test_batch_operations(self):
        """Test batch set and get operations"""
        async with CacheGridClient(['localhost:8080']) as client:
            timestamp = int(time.time())
            test_items = {
                f"batch_test_1_{timestamp}": {"id": 1, "name": "Item 1"},
                f"batch_test_2_{timestamp}": {"id": 2, "name": "Item 2"},
                f"batch_test_3_{timestamp}": {"id": 3, "name": "Item 3"}
            }
            
            # Test batch set
            items_set = await client.set_multi(test_items, ttl=3600)
            assert items_set == len(test_items)
            
            # Test batch get
            keys = list(test_items.keys())
            keys.append("nonexistent_key")  # Add non-existent key
            
            results = await client.get_multi(keys)
            
            # Should get all existing items
            assert len(results) == len(test_items)
            for key, expected_value in test_items.items():
                assert results[key] == expected_value
            
            # Non-existent key should not be in results
            assert "nonexistent_key" not in results
    
    @pytest.mark.integration
    async def test_administrative_operations(self):
        """Test administrative operations"""
        async with CacheGridClient(['localhost:8080']) as client:
            # Test health check
            health = await client.health()
            assert health.get('status') in ['healthy', 'degraded']
            assert 'uptime_seconds' in health
            
            # Test stats
            stats = await client.stats()
            assert 'current_size' in stats
            assert 'hit_ratio' in stats
            assert isinstance(stats['hit_ratio'], (int, float))
            
            # Test key listing
            keys = await client.keys(limit=10)
            assert isinstance(keys, list)
            
            # Test pattern matching
            await client.set('pattern_test_1', 'value1')
            await client.set('pattern_test_2', 'value2')
            await client.set('other_key', 'value3')
            
            pattern_keys = await client.keys(pattern='pattern_test_')
            assert len(pattern_keys) >= 2
            assert all('pattern_test_' in key for key in pattern_keys)
    
    @pytest.mark.integration
    async def test_convenience_methods(self):
        """Test convenience methods like increment and expire"""
        async with CacheGridClient(['localhost:8080']) as client:
            counter_key = f"counter_{int(time.time())}"
            
            # Test increment on new key
            result = await client.increment(counter_key, 5)
            assert result == 5
            
            # Test increment on existing key
            result = await client.increment(counter_key, 3)
            assert result == 8
            
            # Test exists
            exists = await client.exists(counter_key)
            assert exists is True
            
            non_exists = await client.exists("definitely_nonexistent_key")
            assert non_exists is False
            
            # Test expire
            expire_key = f"expire_test_{int(time.time())}"
            await client.set(expire_key, "will_expire")
            
            expire_success = await client.expire(expire_key, 1.0)
            assert expire_success is True
    
    async def test_error_handling(self):
        """Test error handling and resilience"""
        # Test with non-existent server
        client = CacheGridClient(['localhost:9999'], timeout=1.0, max_retries=1)
        
        # Operations should return None/False gracefully, not raise exceptions
        result = await client.get('test')
        assert result is None
        
        success = await client.set('test', 'value')
        assert success is False
        
        stats = await client.stats()
        assert stats == {}
    
    async def test_host_failover(self):
        """Test failover between multiple hosts"""
        # Mix of bad and good hosts
        hosts = ['localhost:9999', 'localhost:8080']
        
        async with CacheGridClient(hosts, timeout=2.0, max_retries=2) as client:
            # Should work despite first host being down
            test_key = f"failover_test_{int(time.time())}"
            success = await client.set(test_key, "failover_success")
            assert success is True
            
            value = await client.get(test_key)
            assert value == "failover_success"

class TestSyncCacheGridClient:
    """Test synchronous CacheGrid client"""
    
    def test_sync_client_initialization(self):
        """Test sync client initialization"""
        client = SyncCacheGridClient(['localhost:8080'])
        assert client._client is not None
    
    @pytest.mark.integration
    def test_sync_context_manager(self):
        """Test sync context manager"""
        with SyncCacheGridClient(['localhost:8080']) as client:
            # Test basic operations
            test_key = f"sync_test_{int(time.time())}"
            
            success = client.set(test_key, "sync_value")
            assert success is True
            
            value = client.get(test_key)
            assert value == "sync_value"
            
            deleted = client.delete(test_key)
            assert deleted is True
    
    @pytest.mark.integration
    def test_sync_batch_operations(self):
        """Test sync batch operations"""
        with SyncCacheGridClient(['localhost:8080']) as client:
            timestamp = int(time.time())
            test_items = {
                f"sync_batch_1_{timestamp}": "value1",
                f"sync_batch_2_{timestamp}": "value2"
            }
            
            items_set = client.set_multi(test_items)
            assert items_set == len(test_items)
            
            results = client.get_multi(list(test_items.keys()))
            assert len(results) == len(test_items)
    
    @pytest.mark.integration
    def test_sync_stats(self):
        """Test sync stats and health"""
        with SyncCacheGridClient(['localhost:8080']) as client:
            stats = client.stats()
            assert 'current_size' in stats
            
            health = client.health()
            assert 'status' in health

@pytest.mark.integration
class TestClientIntegration:
    """Integration tests with live CacheGrid server"""
    
    async def test_concurrent_clients(self):
        """Test multiple concurrent clients"""
        async def client_task(client_id: int):
            async with CacheGridClient(['localhost:8080']) as client:
                # Each client sets and gets its own keys
                for i in range(10):
                    key = f"concurrent_{client_id}_{i}"
                    value = f"value_{client_id}_{i}"
                    
                    await client.set(key, value)
                    retrieved = await client.get(key)
                    assert retrieved == value
        
        # Run multiple clients concurrently
        tasks = [client_task(i) for i in range(5)]
        await asyncio.gather(*tasks)
    
    async def test_load_testing(self):
        """Basic load testing"""
        async with CacheGridClient(['localhost:8080']) as client:
            # Set many keys rapidly
            tasks = []
            for i in range(100):
                tasks.append(client.set(f"load_test_{i}", f"value_{i}"))
            
            results = await asyncio.gather(*tasks)
            successful_sets = sum(1 for r in results if r)
            assert successful_sets >= 95  # Allow for some failures
            
            # Get many keys rapidly
            get_tasks = []
            for i in range(100):
                get_tasks.append(client.get(f"load_test_{i}"))
            
            get_results = await asyncio.gather(*get_tasks)
            successful_gets = sum(1 for r in get_results if r is not None)
            assert successful_gets >= 95
    
    async def test_memory_pressure(self):
        """Test behavior under memory pressure"""
        async with CacheGridClient(['localhost:8080']) as client:
            # Create large values to test memory limits
            large_value = "x" * 10000  # 10KB string
            
            # Set many large values
            for i in range(50):
                key = f"memory_test_{i}"
                await client.set(key, large_value)
            
            # Check that cache is still responsive
            health = await client.health()
            assert health.get('status') in ['healthy', 'degraded']
            
            stats = await client.stats()
            assert stats.get('current_size', 0) > 0

# Fixtures for integration tests
@pytest.fixture(scope="session")
def check_server():
    """Check if CacheGrid server is running before integration tests"""
    import urllib.request
    try:
        urllib.request.urlopen('http://localhost:8080/health', timeout=5)
        return True
    except:
        pytest.skip("CacheGrid server not running on localhost:8080")

# Mark integration tests
pytestmark = pytest.mark.usefixtures("check_server")

# Performance benchmarks
@pytest.mark.benchmark
class TestClientPerformance:
    """Performance benchmarks for client operations"""
    
    @pytest.mark.asyncio
    async def test_set_performance(self, benchmark):
        """Benchmark SET operations"""
        async with CacheGridClient(['localhost:8080']) as client:
            
            async def set_operation():
                await client.set(f"perf_test_{time.time()}", "test_value")
            
            await benchmark(set_operation)
    
    @pytest.mark.asyncio
    async def test_get_performance(self, benchmark):
        """Benchmark GET operations"""
        async with CacheGridClient(['localhost:8080']) as client:
            # Pre-populate
            await client.set("perf_get_test", "test_value")
            
            async def get_operation():
                await client.get("perf_get_test")
            
            await benchmark(get_operation)
    
    @pytest.mark.asyncio
    async def test_batch_performance(self, benchmark):
        """Benchmark batch operations"""
        async with CacheGridClient(['localhost:8080']) as client:
            items = {f"batch_perf_{i}": f"value_{i}" for i in range(10)}
            
            async def batch_operation():
                await client.set_multi(items)
                await client.get_multi(list(items.keys()))
            
            await benchmark(batch_operation)

if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])