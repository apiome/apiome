#!/usr/bin/env python3
"""
Test script to verify the Swagger UI endpoint implementation.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_imports():
    """Test that all required modules can be imported."""
    try:
        from fastapi import FastAPI, HTTPException, Response, Header
        from fastapi.responses import JSONResponse, HTMLResponse
        from fastapi.openapi.docs import get_swagger_ui_html
        print("✓ All FastAPI imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

def test_app_structure():
    """Test that the app structure is correct."""
    try:
        from app.main import app
        print("✓ App imported successfully")

        # Count routes
        routes = [r for r in app.routes if hasattr(r, 'path')]
        print(f"✓ Total routes: {len(routes)}")

        # Check for swagger endpoint
        swagger_routes = [r for r in routes if 'swagger' in r.path]
        if swagger_routes:
            print(f"✓ Swagger UI endpoint found: {swagger_routes[0].path}")
        else:
            print("✗ Swagger UI endpoint not found")
            return False

        return True
    except Exception as e:
        print(f"✗ Error loading app: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("Testing Swagger UI endpoint implementation...\n")

    success = True
    success = test_imports() and success
    success = test_app_structure() and success

    print("\n" + "="*50)
    if success:
        print("✓ All tests passed!")
        print("\nThe Swagger UI endpoint is available at:")
        print("  /v1/{tenant-slug}/{project-slug}/{version-slug}/swagger")
    else:
        print("✗ Some tests failed")
        sys.exit(1)

if __name__ == "__main__":
    main()

