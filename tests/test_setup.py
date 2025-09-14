def test_environment():
    """Verify environment is set up correctly"""
    import sys
    assert sys.version_info >= (3, 9)
    
    # Test imports work
    import fastapi
    import asyncio
    import pytest
    
    print("Environment setup successful!")
