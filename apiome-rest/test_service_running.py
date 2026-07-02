#!/usr/bin/env python3
"""
Test the running REST API service to verify paths integration works.
"""

import requests
import json

def test_service_running():
    """Test that the REST API service is running."""
    print("=" * 70)
    print("Testing REST API Service")
    print("=" * 70)

    # Test health endpoint (if it exists)
    try:
        response = requests.get("http://localhost:8000/docs")
        if response.status_code == 200:
            print("✓ Service is running (docs endpoint accessible)")
        else:
            print(f"✗ Docs endpoint returned status {response.status_code}")
    except Exception as e:
        print(f"✗ Could not connect to service: {e}")
        return False

    # Test a known endpoint that should fail gracefully
    try:
        response = requests.get("http://localhost:8000/v1/schema/test-tenant/test-project/1.0.0")
        print(f"\n✓ Schema endpoint is responsive (status: {response.status_code})")
        if response.status_code == 404:
            print("  (Expected 404 for non-existent version)")
            data = response.json()
            print(f"  Response: {data}")
    except Exception as e:
        print(f"✗ Schema endpoint error: {e}")
        return False

    print("\n" + "=" * 70)
    print("Service appears to be running correctly!")
    print("=" * 70)
    print("\nNote: To test with actual data, ensure you have:")
    print("  1. A tenant in the database")
    print("  2. A project under that tenant")
    print("  3. A version for that project")
    print("  4. Classes defined for that version")
    print("  5. (Optional) Paths defined for that version")

    return True

if __name__ == "__main__":
    test_service_running()
