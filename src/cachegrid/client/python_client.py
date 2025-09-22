"""
src/cachegrid/client/python_client.py
Official Python client SDK for CacheGrid
"""

import asyncio
import aiohttp
import json
import time
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class CacheGridConfig:
    """Configuration for CacheGrid client"""
    hosts: List[str]
    timeout: float = 5.0
    max_retries: int = 3
    retry_delay: float = 0.1
    connection_pool_size: int = 100
    api_key: Optional[str] = None
    
class CacheGridError(Exception):
    """Base exception for CacheGrid client errors"""
    pass

class CacheGridConnectionError(CacheGridError):
    """Raised when connection to CacheGrid fails"""
    pass

class CacheGridTimeoutError(CacheGridError):
    """Raised when operation times out"""
    pass

class CacheGridClient:
    """
    Async Python client for CacheGrid
    
    Example usage:
        async with CacheGridClient(['localhost:8080']) as client:
            await client.set('key', 'value')
            value = await client.get('key')
    """
    
    def __init__(self, 
                 hosts: Union[str, List[str]], 
                 timeout: float = 5.0,
                 max_retries: int = 3,
                 api_key: Optional[str] = None):
        """
        Initialize CacheGrid client
        
        Args:
            hosts: Single host string or list of host strings (host:port format)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            api_key: Optional API key for authentication
        """
        if isinstance(hosts, str):
            hosts = [hosts]
        
        # Normalize host format
        normalized_hosts = []
        for host in hosts:
            if not host.startswith('http'):
                host = f'http://{host}'
            normalized_hosts.append(host.rstrip('/'))
        
        self.config = CacheGridConfig(
            hosts=normalized_hosts,
            timeout=timeout,
            max_retries=max_retries,
            api_key=api_key
        )
        
        self.session: Optional[aiohttp.ClientSession] = None
        self._current_host_index = 0
        self._health_status = {}
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def connect(self):
        """Establish connection to CacheGrid"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            connector = aiohttp.TCPConnector(
                limit=self.config.connection_pool_size,
                limit_per_host=50
            )
            
            headers = {}
            if self.config.api_key:
                headers['Authorization'] = f'Bearer {self.config.api_key}'
            
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers=headers
            )
        
        # Check initial connectivity
        await self._health_check_all_hosts()
    
    async def close(self):
        """Close client connection"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def _get_healthy_host(self) -> str:
        """Get a healthy host from the pool"""
        healthy_hosts = [
            host for host, healthy in self._health_status.items() 
            if healthy
        ]
        
        if not healthy_hosts:
            # If no hosts are marked healthy, try the first one
            # This handles the case where we haven't done health checks yet
            return self.config.hosts[0]
        
        # Simple round-robin selection
        host = healthy_hosts[self._current_host_index % len(healthy_hosts)]
        self._current_host_index += 1
        return host
    
    async def _health_check_all_hosts(self):
        """Check health of all configured hosts"""
        for host in self.config.hosts:
            try:
                url = f"{host}/health"
                async with self.session.get(url) as response:
                    self._health_status[host] = response.status == 200
            except Exception:
                self._health_status[host] = False
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic and host failover"""
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                host = await self._get_healthy_host()
                url = f"{host}{endpoint}"
                
                async with self.session.request(method, url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                        return {"exists": False, "value": None}
                    else:
                        error_text = await response.text()
                        raise CacheGridError(f"HTTP {response.status}: {error_text}")
                        
            except asyncio.TimeoutError as e:
                last_exception = CacheGridTimeoutError(f"Request timed out: {e}")
                # Mark host as unhealthy on timeout
                if 'host' in locals() and host in self._health_status:
                    self._health_status[host] = False
                    
            except aiohttp.ClientError as e:
                last_exception = CacheGridConnectionError(f"Connection error: {e}")
                # Mark host as unhealthy on connection error
                if 'host' in locals() and host in self._health_status:
                    self._health_status[host] = False
                    
            except Exception as e:
                last_exception = CacheGridError(f"Unexpected error: {e}")
            
            # Wait before retry
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (2 ** attempt))
        
        # All retries failed
        raise last_exception or CacheGridError("All retry attempts failed")
    
    # Core Cache Operations
    
    async def get(self, key: str) -> Any:
        """
        Get value by key
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        try:
            response = await self._request('GET', f'/cache/{key}')
            if response.get('exists', False):
                return response.get('value')
            return None
        except CacheGridError:
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        """
        Set key-value pair
        
        Args:
            key: Cache key
            value: Value to store
            ttl: Time to live in seconds
            
        Returns:
            True if successful
        """
        params = {}
        if ttl is not None:
            params['ttl'] = ttl
            
        try:
            await self._request('PUT', f'/cache/{key}', 
                              json=value, params=params)
            return True
        except CacheGridError:
            return False
    
    async def delete(self, key: str) -> bool:
        """
        Delete key
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if key was deleted
        """
        try:
            response = await self._request('DELETE', f'/cache/{key}')
            return response.get('deleted', False)
        except CacheGridError:
            return False
    
    async def exists(self, key: str) -> bool:
        """
        Check if key exists
        
        Args:
            key: Cache key
            
        Returns:
            True if key exists
        """
        try:
            response = await self._request('GET', f'/cache/{key}')
            return response.get('exists', False)
        except CacheGridError:
            return False
    
    # Batch Operations
    
    async def get_multi(self, keys: List[str]) -> Dict[str, Any]:
        """
        Get multiple keys in a single request
        
        Args:
            keys: List of cache keys
            
        Returns:
            Dictionary mapping keys to values (only existing keys included)
        """
        try:
            response = await self._request(
                'POST', '/cache/batch/get',
                json={'keys': keys}
            )
            
            results = {}
            for key, data in response.get('results', {}).items():
                if data.get('exists', False):
                    results[key] = data.get('value')
            
            return results
        except CacheGridError:
            return {}
    
    async def set_multi(self, items: Dict[str, Any], ttl: Optional[float] = None) -> int:
        """
        Set multiple key-value pairs
        
        Args:
            items: Dictionary of key-value pairs
            ttl: Time to live in seconds for all items
            
        Returns:
            Number of items successfully set
        """
        try:
            payload = {'items': items}
            if ttl is not None:
                payload['ttl'] = ttl
                
            response = await self._request(
                'POST', '/cache/batch/set',
                json=payload
            )
            
            return response.get('items_set', 0)
        except CacheGridError:
            return 0
    
    async def delete_multi(self, keys: List[str]) -> int:
        """
        Delete multiple keys
        
        Args:
            keys: List of cache keys to delete
            
        Returns:
            Number of keys successfully deleted
        """
        deleted_count = 0
        for key in keys:
            if await self.delete(key):
                deleted_count += 1
        return deleted_count
    
    # Administrative Operations
    
    async def clear(self) -> bool:
        """
        Clear all cache entries
        
        Returns:
            True if successful
        """
        try:
            await self._request('DELETE', '/cache', params={'confirm': 'true'})
            return True
        except CacheGridError:
            return False
    
    async def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dictionary containing cache statistics
        """
        try:
            return await self._request('GET', '/stats')
        except CacheGridError:
            return {}
    
    async def health(self) -> Dict[str, Any]:
        """
        Get health status
        
        Returns:
            Dictionary containing health information
        """
        try:
            return await self._request('GET', '/health')
        except CacheGridError:
            return {"status": "unhealthy"}
    
    async def keys(self, pattern: Optional[str] = None, limit: int = 100) -> List[str]:
        """
        List cache keys
        
        Args:
            pattern: Optional pattern to filter keys
            limit: Maximum number of keys to return
            
        Returns:
            List of cache keys
        """
        try:
            params = {'limit': limit}
            if pattern:
                params['pattern'] = pattern
                
            response = await self._request('GET', '/admin/keys', params=params)
            return response.get('keys', [])
        except CacheGridError:
            return []
    
    # Convenience methods
    
    async def increment(self, key: str, delta: int = 1) -> Optional[int]:
        """
        Increment a numeric value (atomic operation)
        
        Args:
            key: Cache key
            delta: Amount to increment
            
        Returns:
            New value after increment, or None if key doesn't exist or isn't numeric
        """
        # This is a simplified implementation
        # In a full implementation, this would be an atomic server-side operation
        current = await self.get(key)
        if current is None:
            current = 0
        
        try:
            new_value = int(current) + delta
            if await self.set(key, new_value):
                return new_value
        except (ValueError, TypeError):
            pass
        
        return None
    
    async def expire(self, key: str, ttl: float) -> bool:
        """
        Set TTL on existing key
        
        Args:
            key: Cache key
            ttl: Time to live in seconds
            
        Returns:
            True if TTL was set
        """
        # Get current value and reset with TTL
        value = await self.get(key)
        if value is not None:
            return await self.set(key, value, ttl)
        return False

# Synchronous wrapper for convenience
class SyncCacheGridClient:
    """
    Synchronous wrapper for CacheGridClient
    Useful for non-async code
    """
    
    def __init__(self, *args, **kwargs):
        self._client = CacheGridClient(*args, **kwargs)
        self._loop = None
    
    def _run_async(self, coro):
        """Run async operation in sync context"""
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(coro)
    
    def __enter__(self):
        self._run_async(self._client.connect())
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._run_async(self._client.close())
    
    def get(self, key: str) -> Any:
        return self._run_async(self._client.get(key))
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        return self._run_async(self._client.set(key, value, ttl))
    
    def delete(self, key: str) -> bool:
        return self._run_async(self._client.delete(key))
    
    def get_multi(self, keys: List[str]) -> Dict[str, Any]:
        return self._run_async(self._client.get_multi(keys))
    
    def set_multi(self, items: Dict[str, Any], ttl: Optional[float] = None) -> int:
        return self._run_async(self._client.set_multi(items, ttl))
    
    def stats(self) -> Dict[str, Any]:
        return self._run_async(self._client.stats())
    
    def health(self) -> Dict[str, Any]:
        return self._run_async(self._client.health())

# Example usage
async def example_usage():
    """Example demonstrating CacheGrid client usage"""
    
    # Initialize client
    async with CacheGridClient(['localhost:8080']) as client:
        
        # Basic operations
        await client.set('user:123', {'name': 'Alice', 'age': 30})
        user = await client.get('user:123')
        print(f"User: {user}")
        
        # TTL operations
        await client.set('session:abc', {'token': 'xyz123'}, ttl=3600)
        
        # Batch operations
        await client.set_multi({
            'product:1': {'name': 'Widget', 'price': 19.99},
            'product:2': {'name': 'Gadget', 'price': 29.99}
        })
        
        products = await client.get_multi(['product:1', 'product:2'])
        print(f"Products: {products}")
        
        # Administrative operations
        stats = await client.stats()
        print(f"Cache stats: {stats}")
        
        keys = await client.keys(pattern='product:')
        print(f"Product keys: {keys}")

def sync_example_usage():
    """Example using synchronous client"""
    
    with SyncCacheGridClient(['localhost:8080']) as client:
        # Basic operations
        client.set('sync_test', 'Hello from sync client!')
        value = client.get('sync_test')
        print(f"Sync value: {value}")
        
        # Check stats
        stats = client.stats()
        print(f"Current cache size: {stats.get('current_size', 0)}")

if __name__ == "__main__":
    print("🚀 CacheGrid Client SDK Examples")
    
    print("\n📝 Async Example:")
    asyncio.run(example_usage())
    
    print("\n📝 Sync Example:")
    sync_example_usage()
