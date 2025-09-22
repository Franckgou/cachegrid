"""
src/cachegrid/core/engine.py
CacheGrid Core Engine - Single Node Implementation
Phase 1: High-performance in-memory cache with LRU eviction and TTL support
"""

import asyncio
import time
import json
import threading
from typing import Any, Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict
from collections import OrderedDict
import weakref
import logging

# Import our storage components
from .storage import AdvancedStorage, LRUEvictionPolicy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class CacheItem:
    """Represents a single cache entry with metadata"""
    value: Any
    created_at: float
    ttl: Optional[float] = None
    access_count: int = 0
    last_accessed: float = None
    
    def __post_init__(self):
        if self.last_accessed is None:
            self.last_accessed = self.created_at
    
    @property
    def is_expired(self) -> bool:
        """Check if item has expired based on TTL"""
        if self.ttl is None:
            return False
        return time.time() > (self.created_at + self.ttl)
    
    @property
    def age_seconds(self) -> float:
        """Get age of item in seconds"""
        return time.time() - self.created_at

@dataclass
class CacheStats:
    """Cache performance and usage statistics"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    expired_items: int = 0
    current_size: int = 0
    max_size: int = 0
    memory_usage_bytes: int = 0
    
    @property
    def hit_ratio(self) -> float:
        """Calculate cache hit ratio"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    @property
    def memory_usage_mb(self) -> float:
        """Get memory usage in MB"""
        return self.memory_usage_bytes / (1024 * 1024)

class LRUCache:
    """
    High-performance LRU cache with TTL support
    Thread-safe implementation using asyncio locks
    """
    
    def __init__(self, max_size: int = 1000, cleanup_interval: int = 60):
        self.max_size = max_size
        self.cleanup_interval = cleanup_interval
        
        # Main storage - OrderedDict provides O(1) operations and maintains order
        self._cache: OrderedDict[str, CacheItem] = OrderedDict()
        
        # Thread safety
        self._lock = asyncio.Lock()
        
        # Statistics
        self.stats = CacheStats(max_size=max_size)
        
        # Background cleanup task
        self._cleanup_task = None
        self._running = False
        
        logger.info(f"LRUCache initialized with max_size={max_size}")
    
    async def start(self):
        """Start background cleanup task"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_items())
        logger.info("Cache cleanup task started")
    
    async def stop(self):
        """Stop background cleanup task"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Cache cleanup task stopped")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value from cache
        Returns None if key doesn't exist or has expired
        """
        async with self._lock:
            if key not in self._cache:
                self.stats.misses += 1
                return None
            
            item = self._cache[key]
            
            # Check if expired
            if item.is_expired:
                del self._cache[key]
                self.stats.misses += 1
                self.stats.expired_items += 1
                self.stats.current_size -= 1
                return None
            
            # Update access info and move to end (most recently used)
            item.last_accessed = time.time()
            item.access_count += 1
            self._cache.move_to_end(key)
            
            self.stats.hits += 1
            return item.value
    
    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        """
        Store value in cache with optional TTL
        Returns True if successfully stored
        """
        async with self._lock:
            current_time = time.time()
            
            # Create new cache item
            item = CacheItem(
                value=value,
                created_at=current_time,
                ttl=ttl,
                last_accessed=current_time
            )
            
            # If key exists, we're updating
            if key in self._cache:
                self._cache[key] = item
                self._cache.move_to_end(key)
            else:
                # New key - check if we need to evict
                if len(self._cache) >= self.max_size:
                    await self._evict_lru()
                
                self._cache[key] = item
                self.stats.current_size += 1
            
            self.stats.sets += 1
            self._update_memory_usage()
            return True
    
    async def delete(self, key: str) -> bool:
        """
        Remove key from cache
        Returns True if key existed and was removed
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                self.stats.deletes += 1
                self.stats.current_size -= 1
                self._update_memory_usage()
                return True
            return False
    
    async def clear(self) -> int:
        """
        Clear all items from cache
        Returns number of items removed
        """
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self.stats.current_size = 0
            self._update_memory_usage()
            logger.info(f"Cache cleared - removed {count} items")
            return count
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get current cache statistics"""
        async with self._lock:
            self._update_memory_usage()
            return asdict(self.stats)
    
    async def get_keys(self, pattern: Optional[str] = None) -> List[str]:
        """Get all keys, optionally filtered by pattern"""
        async with self._lock:
            keys = list(self._cache.keys())
            if pattern:
                # Simple pattern matching - could be enhanced with regex
                keys = [k for k in keys if pattern in k]
            return keys
    
    async def get_multi(self, keys: List[str]) -> Dict[str, Any]:
        """Batch get operation for multiple keys"""
        result = {}
        for key in keys:
            value = await self.get(key)
            if value is not None:
                result[key] = value
        return result
    
    async def set_multi(self, items: Dict[str, Any], ttl: Optional[float] = None) -> int:
        """Batch set operation for multiple key-value pairs"""
        count = 0
        for key, value in items.items():
            if await self.set(key, value, ttl):
                count += 1
        return count
    
    async def _evict_lru(self):
        """Evict least recently used item"""
        if self._cache:
            # OrderedDict keeps items in order of insertion/access
            # First item is least recently used
            lru_key = next(iter(self._cache))
            del self._cache[lru_key]
            self.stats.evictions += 1
            self.stats.current_size -= 1
            logger.debug(f"Evicted LRU item: {lru_key}")
    
    async def _cleanup_expired_items(self):
        """Background task to clean up expired items"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                
                if not self._running:
                    break
                
                async with self._lock:
                    expired_keys = []
                    current_time = time.time()
                    
                    for key, item in self._cache.items():
                        if item.is_expired:
                            expired_keys.append(key)
                    
                    for key in expired_keys:
                        del self._cache[key]
                        self.stats.expired_items += 1
                        self.stats.current_size -= 1
                    
                    if expired_keys:
                        self._update_memory_usage()
                        logger.info(f"Cleaned up {len(expired_keys)} expired items")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
    
    def _update_memory_usage(self):
        """Estimate memory usage (simplified calculation)"""
        # This is a rough estimation - in production you'd want more accurate memory tracking
        total_size = 0
        for key, item in self._cache.items():
            # Estimate size of key + value + metadata
            key_size = len(key.encode('utf-8'))
            value_size = len(str(item.value).encode('utf-8'))  # Simplified
            metadata_size = 100  # Rough estimate for CacheItem overhead
            total_size += key_size + value_size + metadata_size
        
        self.stats.memory_usage_bytes = total_size

class CacheEngine:
    """
    Main cache engine that coordinates multiple cache instances
    Provides high-level interface for cache operations
    """
    
    def __init__(self, max_size: int = 10000, cleanup_interval: int = 60):
        self.cache = LRUCache(max_size=max_size, cleanup_interval=cleanup_interval)
        self._running = False
        self._start_time = None
        
    async def start(self):
        """Start the cache engine"""
        await self.cache.start()
        self._running = True
        self._start_time = time.time()
        logger.info("CacheEngine started successfully")
    
    async def stop(self):
        """Stop the cache engine"""
        await self.cache.stop()
        self._running = False
        logger.info("CacheEngine stopped")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key"""
        if not self._running:
            raise RuntimeError("Cache engine not started")
        return await self.cache.get(key)
    
    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        """Set key-value pair with optional TTL"""
        if not self._running:
            raise RuntimeError("Cache engine not started")
        return await self.cache.set(key, value, ttl)
    
    async def delete(self, key: str) -> bool:
        """Delete key"""
        if not self._running:
            raise RuntimeError("Cache engine not started")
        return await self.cache.delete(key)
    
    async def clear(self) -> int:
        """Clear all cache entries"""
        if not self._running:
            raise RuntimeError("Cache engine not started")
        return await self.cache.clear()
    
    async def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self._running:
            raise RuntimeError("Cache engine not started")
        return await self.cache.get_stats()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        stats = await self.stats()
        
        uptime = time.time() - self._start_time if self._start_time else 0
        
        return {
            "status": "healthy" if self._running else "stopped",
            "uptime_seconds": uptime,
            "cache_size": stats["current_size"],
            "hit_ratio": stats["hit_ratio"],
            "memory_usage_mb": stats["memory_usage_mb"],
            "last_check": time.time()
        }

# Example usage and testing
async def demo_cache_engine():
    """Demonstrate cache engine capabilities"""
    print("🚀 Starting CacheGrid Engine Demo")
    
    # Initialize cache engine
    engine = CacheEngine(max_size=5, cleanup_interval=10)
    await engine.start()
    
    try:
        # Basic operations
        print("\n📝 Basic Operations:")
        await engine.set("user:123", {"name": "Alice", "age": 30})
        await engine.set("user:456", {"name": "Bob", "age": 25})
        
        user = await engine.get("user:123")
        print(f"Retrieved user: {user}")
        
        # TTL operations
        print("\n⏰ TTL Operations:")
        await engine.set("session:abc", {"token": "xyz123"}, ttl=2.0)  # 2 seconds
        print(f"Session data: {await engine.get('session:abc')}")
        
        await asyncio.sleep(3)  # Wait for expiration
        print(f"Session after expiry: {await engine.get('session:abc')}")
        
        # Fill cache to test eviction
        print("\n🔄 LRU Eviction Test:")
        for i in range(10):
            await engine.set(f"item:{i}", f"value_{i}")
        
        # Check what's left (should only have last 5 due to max_size=5)
        stats = await engine.stats()
        print(f"Cache size after adding 10 items: {stats['current_size']}")
        print(f"Evictions: {stats['evictions']}")
        
        # Performance test
        print("\n⚡ Performance Test:")
        start_time = time.time()
        for i in range(1000):
            await engine.set(f"perf:{i}", f"value_{i}")
        set_time = time.time() - start_time
        
        start_time = time.time()
        for i in range(1000):
            await engine.get(f"perf:{i}")
        get_time = time.time() - start_time
        
        print(f"1000 SET operations: {set_time:.3f}s ({1000/set_time:.0f} ops/sec)")
        print(f"1000 GET operations: {get_time:.3f}s ({1000/get_time:.0f} ops/sec)")
        
        # Final stats
        print("\n📊 Final Statistics:")
        final_stats = await engine.stats()
        for key, value in final_stats.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.3f}")
            else:
                print(f"  {key}: {value}")
        
        # Health check
        print("\n🏥 Health Check:")
        health = await engine.health_check()
        for key, value in health.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.3f}")
            else:
                print(f"  {key}: {value}")
            
    finally:
        await engine.stop()
        print("\n✅ Demo completed successfully!")

if __name__ == "__main__":
    asyncio.run(demo_cache_engine())
