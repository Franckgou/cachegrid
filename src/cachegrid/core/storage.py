"""
src/cachegrid/core/storage.py
Advanced storage backends and eviction policies for CacheGrid
"""

import time
import heapq
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Iterator
from dataclasses import dataclass
from collections import OrderedDict, defaultdict
import logging

logger = logging.getLogger(__name__)

@dataclass
class StorageItem:
    """Enhanced storage item with comprehensive metadata"""
    key: str
    value: Any
    created_at: float
    ttl: Optional[float] = None
    access_count: int = 0
    last_accessed: float = None
    size_bytes: int = 0
    tags: List[str] = None
    
    def __post_init__(self):
        if self.last_accessed is None:
            self.last_accessed = self.created_at
        if self.tags is None:
            self.tags = []
        if self.size_bytes == 0:
            self.size_bytes = self._estimate_size()
    
    @property
    def is_expired(self) -> bool:
        """Check if item has expired"""
        if self.ttl is None:
            return False
        return time.time() > (self.created_at + self.ttl)
    
    @property
    def age_seconds(self) -> float:
        """Get age in seconds"""
        return time.time() - self.created_at
    
    @property
    def time_since_access(self) -> float:
        """Time since last access"""
        return time.time() - self.last_accessed
    
    def _estimate_size(self) -> int:
        """Estimate memory size of the item"""
        # Simplified size estimation
        key_size = len(self.key.encode('utf-8'))
        value_size = len(str(self.value).encode('utf-8'))
        metadata_size = 200  # Estimate for object overhead
        return key_size + value_size + metadata_size

class EvictionPolicy(ABC):
    """Abstract base class for eviction policies"""
    
    @abstractmethod
    def on_access(self, key: str, item: StorageItem) -> None:
        """Called when an item is accessed"""
        pass
    
    @abstractmethod
    def on_insert(self, key: str, item: StorageItem) -> None:
        """Called when an item is inserted"""
        pass
    
    @abstractmethod
    def on_remove(self, key: str) -> None:
        """Called when an item is removed"""
        pass
    
    @abstractmethod
    def select_victim(self, storage: Dict[str, StorageItem]) -> Optional[str]:
        """Select a key to evict"""
        pass

class LRUEvictionPolicy(EvictionPolicy):
    """Least Recently Used eviction policy"""
    
    def __init__(self):
        self.access_order = OrderedDict()
    
    def on_access(self, key: str, item: StorageItem) -> None:
        """Move key to end (most recent)"""
        self.access_order.move_to_end(key)
    
    def on_insert(self, key: str, item: StorageItem) -> None:
        """Add key to end"""
        self.access_order[key] = True
    
    def on_remove(self, key: str) -> None:
        """Remove key from tracking"""
        self.access_order.pop(key, None)
    
    def select_victim(self, storage: Dict[str, StorageItem]) -> Optional[str]:
        """Select least recently used key"""
        if self.access_order:
            return next(iter(self.access_order))
        return None

class LFUEvictionPolicy(EvictionPolicy):
    """Least Frequently Used eviction policy"""
    
    def __init__(self):
        self.frequency_heap = []  # Min heap of (frequency, timestamp, key)
        self.key_to_freq = {}
        self.counter = 0
    
    def on_access(self, key: str, item: StorageItem) -> None:
        """Update frequency count"""
        old_freq = self.key_to_freq.get(key, 0)
        new_freq = old_freq + 1
        self.key_to_freq[key] = new_freq
        
        # Add to heap with new frequency
        heapq.heappush(self.frequency_heap, (new_freq, self.counter, key))
        self.counter += 1
    
    def on_insert(self, key: str, item: StorageItem) -> None:
        """Initialize frequency for new key"""
        self.key_to_freq[key] = 1
        heapq.heappush(self.frequency_heap, (1, self.counter, key))
        self.counter += 1
    
    def on_remove(self, key: str) -> None:
        """Remove key from tracking"""
        self.key_to_freq.pop(key, None)
    
    def select_victim(self, storage: Dict[str, StorageItem]) -> Optional[str]:
        """Select least frequently used key"""
        while self.frequency_heap:
            freq, timestamp, key = heapq.heappop(self.frequency_heap)
            
            # Check if this entry is still valid
            if key in self.key_to_freq and self.key_to_freq[key] == freq:
                return key
        
        return None

class TTLEvictionPolicy(EvictionPolicy):
    """Time-To-Live based eviction (expires items first)"""
    
    def __init__(self):
        self.expiry_heap = []  # Min heap of (expiry_time, key)
    
    def on_access(self, key: str, item: StorageItem) -> None:
        """No special handling for access in TTL policy"""
        pass
    
    def on_insert(self, key: str, item: StorageItem) -> None:
        """Track expiry time if TTL is set"""
        if item.ttl is not None:
            expiry_time = item.created_at + item.ttl
            heapq.heappush(self.expiry_heap, (expiry_time, key))
    
    def on_remove(self, key: str) -> None:
        """No special cleanup needed"""
        pass
    
    def select_victim(self, storage: Dict[str, StorageItem]) -> Optional[str]:
        """Select item that expires soonest"""
        current_time = time.time()
        
        while self.expiry_heap:
            expiry_time, key = heapq.heappop(self.expiry_heap)
            
            # Check if key still exists and hasn't been updated
            if key in storage:
                item = storage[key]
                if item.ttl is not None and (item.created_at + item.ttl) <= current_time:
                    return key
        
        return None

class AdvancedStorage:
    """
    Advanced storage engine with pluggable eviction policies,
    tag-based operations, and comprehensive monitoring
    """
    
    def __init__(self, 
                 max_size: int = 10000,
                 max_memory_mb: int = 100,
                 eviction_policy: Optional[EvictionPolicy] = None):
        
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.storage: Dict[str, StorageItem] = {}
        self.tag_index: Dict[str, set] = defaultdict(set)
        
        # Use LRU as default eviction policy
        self.eviction_policy = eviction_policy or LRUEvictionPolicy()
        
        # Metrics
        self.total_memory_bytes = 0
        self.access_count = 0
        self.hit_count = 0
        self.miss_count = 0
        self.eviction_count = 0
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info(f"AdvancedStorage initialized: max_size={max_size}, "
                   f"max_memory={max_memory_mb}MB, policy={type(self.eviction_policy).__name__}")
    
    def get(self, key: str) -> Optional[Any]:
        """Get item by key"""
        with self._lock:
            self.access_count += 1
            
            if key not in self.storage:
                self.miss_count += 1
                return None
            
            item = self.storage[key]
            
            # Check expiration
            if item.is_expired:
                self._remove_item(key)
                self.miss_count += 1
                return None
            
            # Update access metadata
            item.last_accessed = time.time()
            item.access_count += 1
            
            # Notify eviction policy
            self.eviction_policy.on_access(key, item)
            
            self.hit_count += 1
            return item.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None, 
            tags: Optional[List[str]] = None) -> bool:
        """Set item with optional TTL and tags"""
        with self._lock:
            current_time = time.time()
            
            # Create new item
            item = StorageItem(
                key=key,
                value=value,
                created_at=current_time,
                ttl=ttl,
                tags=tags or []
            )
            
            # If key exists, remove old version first
            if key in self.storage:
                self._remove_item(key)
            
            # Check if we need to make space
            while (len(self.storage) >= self.max_size or 
                   self.total_memory_bytes + item.size_bytes > self.max_memory_bytes):
                
                if not self._evict_one():
                    # Could not evict anything, storage might be full of non-evictable items
                    logger.warning("Unable to evict items to make space")
                    return False
            
            # Add new item
            self.storage[key] = item
            self.total_memory_bytes += item.size_bytes
            
            # Update tag index
            for tag in item.tags:
                self.tag_index[tag].add(key)
            
            # Notify eviction policy
            self.eviction_policy.on_insert(key, item)
            
            return True
    
    def delete(self, key: str) -> bool:
        """Delete item by key"""
        with self._lock:
            if key in self.storage:
                self._remove_item(key)
                return True
            return False
    
    def clear(self) -> int:
        """Clear all items"""
        with self._lock:
            count = len(self.storage)
            self.storage.clear()
            self.tag_index.clear()
            self.total_memory_bytes = 0
            return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive storage statistics"""
        with self._lock:
            hit_ratio = self.hit_count / self.access_count if self.access_count > 0 else 0
            
            return {
                "current_size": len(self.storage),
                "max_size": self.max_size,
                "memory_usage_bytes": self.total_memory_bytes,
                "max_memory_bytes": self.max_memory_bytes,
                "memory_usage_percent": (self.total_memory_bytes / self.max_memory_bytes) * 100,
                "access_count": self.access_count,
                "hit_count": self.hit_count,
                "miss_count": self.miss_count,
                "hit_ratio": hit_ratio,
                "eviction_count": self.eviction_count,
                "tag_count": len(self.tag_index),
                "eviction_policy": type(self.eviction_policy).__name__
            }
    
    def get_keys(self, pattern: Optional[str] = None) -> List[str]:
        """Get all keys, optionally filtered by pattern"""
        with self._lock:
            keys = list(self.storage.keys())
            if pattern:
                keys = [k for k in keys if pattern in k]
            return keys
    
    def _remove_item(self, key: str) -> None:
        """Internal method to remove an item"""
        if key in self.storage:
            item = self.storage[key]
            
            # Remove from tag index
            for tag in item.tags:
                self.tag_index[tag].discard(key)
                if not self.tag_index[tag]:  # Remove empty tag sets
                    del self.tag_index[tag]
            
            # Update memory usage
            self.total_memory_bytes -= item.size_bytes
            
            # Remove from storage
            del self.storage[key]
            
            # Notify eviction policy
            self.eviction_policy.on_remove(key)
    
    def _evict_one(self) -> bool:
        """Evict one item according to the eviction policy"""
        victim_key = self.eviction_policy.select_victim(self.storage)
        
        if victim_key:
            self._remove_item(victim_key)
            self.eviction_count += 1
            logger.debug(f"Evicted key: {victim_key}")
            return True
        
        return False
