#!/usr/bin/env python3
"""
Test runner for bridge connectivity functionality tests.

This script runs all the tests related to the bridge connectivity fixes:
- Unit tests for WhatsApp webhooks
- Integration tests for bridge connectivity
- Unit tests for bridge configuration
- Unit tests for startup script changes
"""

import subprocess
import sys
from pathlib import Path


def run_tests(test_patterns, verbose=True):
    """Run tests with the given patterns"""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-v" if verbose else "",
        "--tb=short",
        "--strict-markers",
        "--disable-warnings",
    ]

    # Add test patterns
    cmd.extend(test_patterns)

    # Filter out empty strings
    cmd = [arg for arg in cmd if arg]

    print(f"Running: {' '.join(cmd)}")
    print("-" * 80)

    # Get the project root directory (parent of scripts/)
    project_root = Path(__file__).parent.parent
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode


def main():
    """Main test runner function"""
    print("🧪 Running Bridge Connectivity Tests")
    print("=" * 80)

    # Get the project root directory
    project_root = Path(__file__).parent.parent

    # Test patterns for the new functionality (relative to project root)
    test_patterns = [
        "tests/unit/test_whatsapp_webhooks.py",
        "tests/integration/test_bridge_connectivity.py",
        "tests/unit/test_bridge_configuration.py",
        "tests/unit/test_startup_script.py",
    ]

    # Check if test files exist
    missing_tests = []
    for pattern in test_patterns:
        test_path = project_root / pattern
        if not test_path.exists():
            missing_tests.append(pattern)

    if missing_tests:
        print("❌ Missing test files:")
        for test in missing_tests:
            print(f"   - {test}")
        return 1

    print("✅ All test files found")
    print()

    # Run the tests
    exit_code = run_tests(test_patterns)

    print()
    print("=" * 80)
    if exit_code == 0:
        print("✅ All bridge connectivity tests passed!")
    else:
        print("❌ Some bridge connectivity tests failed!")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
