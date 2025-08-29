#!/usr/bin/env python3
"""
Debug script to test imports step by step in Docker environment
"""

import os
import sys


def test_import(module_name, description):
    """Test importing a module and report success/failure"""
    try:
        __import__(module_name)
        print(f"✅ {description}: SUCCESS")
        return True
    except Exception as e:
        print(f"❌ {description}: FAILED - {e}")
        return False


def main():
    print("🔍 Testing imports step by step...")
    print(f"Python path: {sys.path}")
    print(f"Current directory: {os.getcwd()}")
    print(f"Files in current directory: {os.listdir('.')}")

    # Test basic imports
    test_import("fastapi", "FastAPI")
    test_import("uvicorn", "Uvicorn")

    # Test config imports
    test_import("config", "Config module")
    test_import("config.settings", "Settings module")

    # Test app imports
    test_import("app", "App module")
    test_import("app.auth", "Auth module")
    test_import("app.auth.admin_auth", "Admin auth module")
    test_import("app.api", "API module")
    test_import("app.api.web", "Web API module")

    # Test main import
    test_import("main", "Main module")

    print("\n🎯 Import test completed!")


if __name__ == "__main__":
    main()
