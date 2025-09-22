#!/usr/bin/env python3
"""
docker/healthcheck.py
Health check script for CacheGrid containers
"""

import sys
import os
import json
import time

def basic_health_check():
    """Basic health check without external dependencies"""
    try:
        import urllib.request
        import urllib.error
        
        host = os.getenv('CACHEGRID_HOST', 'localhost')
        port = int(os.getenv('CACHEGRID_PORT', '8080'))
        url = f"http://{host}:{port}/health"
        
        # Try to connect to health endpoint
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                print(f"✅ Health check passed: {data.get('status', 'unknown')}")
                return True
            else:
                print(f"❌ Health check failed: HTTP {response.status}")
                return False
                
    except urllib.error.URLError as e:
        print(f"❌ Health check failed: Connection error - {e}")
        return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def advanced_health_check():
    """Advanced health check with cache operations test"""
    try:
        import urllib.request
        import urllib.parse
        
        host = os.getenv('CACHEGRID_HOST', 'localhost')
        port = int(os.getenv('CACHEGRID_PORT', '8080'))
        base_url = f"http://{host}:{port}"
        
        # Test SET operation
        test_key = f"healthcheck_{int(time.time())}"
        test_value = json.dumps({"test": True, "timestamp": time.time()})
        
        set_url = f"{base_url}/cache/{test_key}"
        req = urllib.request.Request(
            set_url, 
            data=test_value.encode(), 
            headers={'Content-Type': 'application/json'},
            method='PUT'
        )
        
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status not in [200, 201]:
                print(f"❌ SET operation failed: HTTP {response.status}")
                return False
        
        # Test GET operation
        with urllib.request.urlopen(f"{base_url}/cache/{test_key}", timeout=3) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                if data.get('exists') and data.get('hit'):
                    print("✅ Advanced health check passed: Cache operations working")
                    
                    # Cleanup - DELETE operation
                    del_req = urllib.request.Request(set_url, method='DELETE')
                    urllib.request.urlopen(del_req, timeout=3)
                    
                    return True
                else:
                    print(f"❌ GET operation returned unexpected data: {data}")
                    return False
            else:
                print(f"❌ GET operation failed: HTTP {response.status}")
                return False
                
    except Exception as e:
        print(f"⚠️  Advanced health check failed, falling back to basic: {e}")
        return basic_health_check()

def main():
    """Main health check function"""
    try:
        # Try advanced health check first
        if advanced_health_check():
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Health check error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
