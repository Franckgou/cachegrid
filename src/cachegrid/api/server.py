"""
src/cachegrid/api/server.py
CacheGrid REST API - FastAPI Interface
Provides HTTP endpoints for cache operations with comprehensive error handling
"""

import asyncio
import time
import json
from typing import Any, Optional, Dict, List, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Path, Body, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Import our cache engine
from ..core.engine import CacheEngine

# Pydantic models for request/response validation
class CacheSetRequest(BaseModel):
    """Request model for setting cache values"""
    key: str = Field(..., min_length=1, max_length=250, description="Cache key")
    value: Any = Field(..., description="Value to store")
    ttl: Optional[float] = Field(None, gt=0, description="Time to live in seconds")
    
    class Config:
        schema_extra = {
            "example": {
                "key": "user:123",
                "value": {"name": "Alice", "age": 30},
                "ttl": 3600
            }
        }

class CacheGetResponse(BaseModel):
    """Response model for cache get operations"""
    key: str
    value: Any
    exists: bool
    hit: bool = True

class CacheStatsResponse(BaseModel):
    """Response model for cache statistics"""
    hits: int
    misses: int
    sets: int
    deletes: int
    evictions: int
    expired_items: int
    current_size: int
    max_size: int
    memory_usage_bytes: int
    hit_ratio: float
    memory_usage_mb: float

class HealthCheckResponse(BaseModel):
    """Response model for health checks"""
    status: str
    uptime_seconds: float
    cache_size: int
    hit_ratio: float
    memory_usage_mb: float
    last_check: float
    node_id: str = "node-1"  # Will be dynamic in distributed version

class BatchSetRequest(BaseModel):
    """Request model for batch set operations"""
    items: Dict[str, Any] = Field(..., description="Key-value pairs to set")
    ttl: Optional[float] = Field(None, gt=0, description="TTL for all items")
    
    class Config:
        schema_extra = {
            "example": {
                "items": {
                    "user:123": {"name": "Alice"},
                    "user:456": {"name": "Bob"}
                },
                "ttl": 3600
            }
        }

class BatchGetRequest(BaseModel):
    """Request model for batch get operations"""
    keys: List[str] = Field(..., min_items=1, description="Keys to retrieve")
    
    class Config:
        schema_extra = {
            "example": {
                "keys": ["user:123", "user:456", "session:abc"]
            }
        }

# Global cache engine instance
cache_engine: Optional[CacheEngine] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage cache engine lifecycle"""
    global cache_engine
    
    # Startup
    cache_engine = CacheEngine(max_size=10000, cleanup_interval=60)
    await cache_engine.start()
    print("🚀 CacheGrid API started successfully")
    
    yield
    
    # Shutdown
    if cache_engine:
        await cache_engine.stop()
    print("🛑 CacheGrid API shutdown complete")

# Create FastAPI app with lifespan management
app = FastAPI(
    title="CacheGrid API",
    description="High-performance distributed in-memory cache system",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware for web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get cache engine
async def get_cache_engine() -> CacheEngine:
    """Dependency to access cache engine"""
    if cache_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Cache engine not available"
        )
    return cache_engine

# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "timestamp": time.time()
        }
    )

# Health and Info Endpoints
@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint with basic info"""
    return {
        "service": "CacheGrid",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health", response_model=HealthCheckResponse)
async def health_check(engine: CacheEngine = Depends(get_cache_engine)):
    """Comprehensive health check"""
    try:
        health_data = await engine.health_check()
        return HealthCheckResponse(**health_data)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Health check failed: {str(e)}"
        )

@app.get("/stats", response_model=CacheStatsResponse)
async def get_stats(engine: CacheEngine = Depends(get_cache_engine)):
    """Get detailed cache statistics"""
    try:
        stats = await engine.stats()
        return CacheStatsResponse(**stats)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get stats: {str(e)}"
        )

# Core Cache Operations
@app.get("/cache/{key}")
async def get_cache_item(
    key: str = Path(..., description="Cache key to retrieve"),
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Get a single cache item by key"""
    try:
        value = await engine.get(key)
        
        if value is None:
            return CacheGetResponse(
                key=key,
                value=None,
                exists=False,
                hit=False
            )
        
        return CacheGetResponse(
            key=key,
            value=value,
            exists=True,
            hit=True
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get cache item: {str(e)}"
        )

@app.put("/cache/{key}")
async def set_cache_item(
    key: str = Path(..., description="Cache key"),
    value: Any = Body(..., description="Value to store"),
    ttl: Optional[float] = Query(None, gt=0, description="TTL in seconds"),
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Set a single cache item"""
    try:
        success = await engine.set(key, value, ttl)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to set cache item"
            )
        
        return {
            "success": True,
            "key": key,
            "ttl": ttl,
            "timestamp": time.time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to set cache item: {str(e)}"
        )

@app.post("/cache")
async def set_cache_item_post(
    request: CacheSetRequest,
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Set cache item via POST (alternative to PUT)"""
    try:
        success = await engine.set(request.key, request.value, request.ttl)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to set cache item"
            )
        
        return {
            "success": True,
            "key": request.key,
            "ttl": request.ttl,
            "timestamp": time.time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to set cache item: {str(e)}"
        )

@app.delete("/cache/{key}")
async def delete_cache_item(
    key: str = Path(..., description="Cache key to delete"),
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Delete a cache item"""
    try:
        deleted = await engine.delete(key)
        
        return {
            "success": True,
            "deleted": deleted,
            "key": key,
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete cache item: {str(e)}"
        )

@app.delete("/cache")
async def clear_cache(
    confirm: bool = Query(False, description="Confirm cache clear"),
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Clear all cache items (requires confirmation)"""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must set confirm=true to clear cache"
        )
    
    try:
        items_removed = await engine.clear()
        
        return {
            "success": True,
            "items_removed": items_removed,
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear cache: {str(e)}"
        )

# Batch Operations
@app.post("/cache/batch/get")
async def batch_get(
    request: BatchGetRequest,
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Get multiple cache items in a single request"""
    try:
        # Use the cache engine's batch get method
        results = await engine.cache.get_multi(request.keys)
        
        # Format response with hit/miss info
        response_data = {}
        for key in request.keys:
            if key in results:
                response_data[key] = {
                    "value": results[key],
                    "exists": True,
                    "hit": True
                }
            else:
                response_data[key] = {
                    "value": None,
                    "exists": False,
                    "hit": False
                }
        
        return {
            "success": True,
            "results": response_data,
            "requested_keys": len(request.keys),
            "found_keys": len(results),
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Batch get failed: {str(e)}"
        )

@app.post("/cache/batch/set")
async def batch_set(
    request: BatchSetRequest,
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Set multiple cache items in a single request"""
    try:
        # Use the cache engine's batch set method
        items_set = await engine.cache.set_multi(request.items, request.ttl)
        
        return {
            "success": True,
            "items_requested": len(request.items),
            "items_set": items_set,
            "ttl": request.ttl,
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Batch set failed: {str(e)}"
        )

# Administrative Endpoints
@app.get("/admin/keys")
async def list_keys(
    pattern: Optional[str] = Query(None, description="Filter keys by pattern"),
    limit: int = Query(100, ge=1, le=1000, description="Max keys to return"),
    engine: CacheEngine = Depends(get_cache_engine)
):
    """List cache keys (with optional filtering)"""
    try:
        keys = await engine.cache.get_keys(pattern)
        
        # Apply limit
        limited_keys = keys[:limit]
        
        return {
            "keys": limited_keys,
            "total_found": len(keys),
            "returned": len(limited_keys),
            "pattern": pattern,
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list keys: {str(e)}"
        )

# Performance Testing Endpoints
@app.post("/test/load")
async def load_test(
    num_operations: int = Query(1000, ge=1, le=100000),
    operation_type: str = Query("mixed", regex="^(get|set|mixed)$"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    engine: CacheEngine = Depends(get_cache_engine)
):
    """Run a load test on the cache"""
    
    async def run_load_test():
        """Background task to run load test"""
        start_time = time.time()
        
        try:
            if operation_type == "set":
                for i in range(num_operations):
                    await engine.set(f"load_test:{i}", f"value_{i}")
                    
            elif operation_type == "get":
                # First populate some data
                for i in range(min(1000, num_operations)):
                    await engine.set(f"load_test:{i}", f"value_{i}")
                
                # Now perform gets
                for i in range(num_operations):
                    await engine.get(f"load_test:{i % 1000}")
                    
            else:  # mixed
                for i in range(num_operations):
                    if i % 4 == 0:  # 25% writes
                        await engine.set(f"load_test:{i}", f"value_{i}")
                    else:  # 75% reads
                        await engine.get(f"load_test:{i % (num_operations // 4)}")
            
            end_time = time.time()
            duration = end_time - start_time
            ops_per_second = num_operations / duration if duration > 0 else 0
            
            print(f"Load test completed: {num_operations} {operation_type} operations "
                  f"in {duration:.3f}s ({ops_per_second:.0f} ops/sec)")
                  
        except Exception as e:
            print(f"Load test failed: {e}")
    
    # Start background task
    background_tasks.add_task(run_load_test)
    
    return {
        "message": f"Load test started: {num_operations} {operation_type} operations",
        "timestamp": time.time()
    }

# Development server
if __name__ == "__main__":
    print("🚀 Starting CacheGrid API Server")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
        access_log=True
    )
