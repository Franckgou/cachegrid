# Getting Started with CacheGrid

This guide will get you up and running with CacheGrid in under 5 minutes.

## 🚀 Quick Start (Docker)

The fastest way to try CacheGrid:

```bash
# 1. Start CacheGrid
docker run -d --name cachegrid -p 8080:8080 cachegrid:latest

# 2. Test it works
curl http://localhost:8080/health

# 3. Set your first cache entry
curl -X PUT "http://localhost:8080/cache/hello" \
  -H "Content-Type: application/json" \
  -d '"Hello CacheGrid!"'

# 4. Get it back
curl "http://localhost:8080/cache/hello"

# 5. Check cache stats
curl "http://localhost:8080/stats"
```

## 📦 Development Setup

If you want to develop or modify CacheGrid:

```bash
# 1. Clone the repository
git clone https://github.com/your-username/cachegrid.git
cd cachegrid

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the development server
cd src
python -m uvicorn cachegrid.api.server:app --reload --host 0.0.0.0 --port 8080

# 4. Test it works
curl http://localhost:8080/health
```

## 🐍 Using the Python Client

```bash
# 1. Start CacheGrid (if not already running)
docker-compose up -d

# 2. Run the Python examples
cd examples/python
python basic_usage.py
```

## 🧪 Running Tests

```bash
# 1. Make sure CacheGrid is running
docker-compose up -d

# 2. Install test dependencies
pip install pytest pytest-asyncio

# 3. Run the tests
pytest tests/ -v

# 4. Run just the client tests
pytest tests/test_client_sdk.py -v
```

## 🔧 Configuration Options

### Basic Configuration

```bash
# Set cache size and memory limits
docker run -d \
  -e CACHEGRID_MAX_SIZE=20000 \
  -e CACHEGRID_MAX_MEMORY_MB=1024 \
  -p 8080:8080 \
  cachegrid:latest
```

### Using Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  cachegrid:
    image: cachegrid:latest
    ports:
      - "8080:8080"
    environment:
      - CACHEGRID_MAX_SIZE=10000
      - CACHEGRID_MAX_MEMORY_MB=512
      - CACHEGRID_LOG_LEVEL=info
```

## 📊 Monitoring Your Cache

### Check Health and Stats

```bash
# Health check
curl "http://localhost:8080/health"

# Detailed statistics
curl "http://localhost:8080/stats"

# List current keys
curl "http://localhost:8080/admin/keys?limit=10"
```

### Load Testing

```bash
# Run built-in load test
curl -X POST "http://localhost:8080/test/load?num_operations=1000&operation_type=mixed"

# Check performance
curl "http://localhost:8080/stats"
```

## 🔌 Integration Examples

### Simple Web App Cache

```python
# app.py - Simple Flask integration
from flask import Flask, jsonify
from cachegrid.client import SyncCacheGridClient
import time

app = Flask(__name__)
cache = SyncCacheGridClient(['localhost:8080'])

@app.route('/time')
def get_time():
    with cache:
        # Try cache first
        cached_time = cache.get('current_time')
        if cached_time:
            return jsonify({'time': cached_time, 'source': 'cache'})
        
        # Generate new time and cache it
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        cache.set('current_time', current_time, ttl=10)  # Cache for 10 seconds
        
        return jsonify({'time': current_time, 'source': 'generated'})

if __name__ == '__main__':
    app.run(debug=True)
```

### Session Storage

```python
# session_example.py
import asyncio
from cachegrid.client import CacheGridClient

async def session_example():
    async with CacheGridClient(['localhost:8080']) as client:
        # Store user session
        session_data = {
            'user_id': 'user123',
            'login_time': '2024-01-01T10:00:00',
            'preferences': {'theme': 'dark', 'language': 'en'}
        }
        
        # Session expires in 2 hours
        await client.set('session:user123', session_data, ttl=7200)
        
        # Retrieve session
        session = await client.get('session:user123')
        print(f"Session: {session}")

if __name__ == "__main__":
    asyncio.run(session_example())
```

## 🚨 Troubleshooting

### CacheGrid Won't Start

```bash
# Check Docker logs
docker logs cachegrid

# Check if port is in use
netstat -tulpn | grep 8080

# Try a different port
docker run -d -p 8081:8080 cachegrid:latest
```

### Can't Connect from Python Client

```bash
# Make sure CacheGrid is running
curl http://localhost:8080/health

# Check firewall/network settings
telnet localhost 8080

# Try with explicit host
python -c "
import asyncio
from cachegrid.client import CacheGridClient

async def test():
    try:
        async with CacheGridClient(['localhost:8080'], timeout=10) as client:
            health = await client.health()
            print('✅ Connection successful:', health)
    except Exception as e:
        print('❌ Connection failed:', e)

asyncio.run(test())
"
```

### Performance Issues

```bash
# Check cache hit ratio
curl "http://localhost:8080/stats" | grep hit_ratio

# Increase cache size if hit ratio is low
docker run -d \
  -e CACHEGRID_MAX_SIZE=50000 \
  -e CACHEGRID_MAX_MEMORY_MB=2048 \
  -p 8080:8080 \
  cachegrid:latest

# Monitor performance during load
watch -n 1 'curl -s "http://localhost:8080/stats"'
```

## 🎯 Next Steps

Once you have CacheGrid running:

1. **Integrate with your app**: Use the Python client in your existing projects
2. **Monitor performance**: Check `/stats` endpoint regularly  
3. **Tune configuration**: Adjust `MAX_SIZE` and `MAX_MEMORY_MB` based on your needs
4. **Run load tests**: Use the built-in load testing endpoint
5. **Set up monitoring**: Create dashboards for your cache metrics

## 📚 Further Reading

- [Full README](README.md) - Complete documentation
- [API Documentation](http://localhost:8080/docs) - Interactive API docs (when server is running)
- [Examples](examples/) - More integration examples
- [Tests](tests/) - How the system is tested

## 💡 Pro Tips

1. **Start small**: Begin with default settings and tune based on usage
2. **Monitor hit ratios**: Aim for >90% hit ratio for good performance
3. **Use TTL wisely**: Set appropriate expiration times for your data
4. **Batch operations**: Use `get_multi` and `set_multi` for better performance
5. **Health checks**: Always check `/health` in production deployments

---

Happy caching! 🚀