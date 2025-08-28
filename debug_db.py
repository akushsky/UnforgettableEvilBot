#!/usr/bin/env python3
"""
Debug script to diagnose database connection issues in production
"""

import os
from urllib.parse import urlparse


def check_environment():
    """Check environment variables and dependencies"""
    print("🔍 Environment Check")
    print("=" * 50)

    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        print("✅ DATABASE_URL is set")
        print(f"   URL: {database_url}")

        # Parse URL to check format
        try:
            parsed = urlparse(database_url)
            print(f"   Scheme: {parsed.scheme}")
            print(f"   Host: {parsed.hostname}")
            print(f"   Port: {parsed.port}")
            print(f"   Database: {parsed.path[1:] if parsed.path else 'None'}")

            # Check if using old postgres:// format
            if parsed.scheme == "postgres":
                print(
                    "   ⚠️  WARNING: Using old 'postgres://' format. Should be 'postgresql://'"
                )
            elif parsed.scheme == "postgresql":
                print("   ✅ Using correct 'postgresql://' format")
            else:
                print(f"   ❌ Unknown scheme: {parsed.scheme}")

        except Exception as e:
            print(f"   ❌ Error parsing DATABASE_URL: {e}")
    else:
        print("❌ DATABASE_URL is not set")

    print()


def check_dependencies():
    """Check if required packages are installed"""
    print("📦 Dependency Check")
    print("=" * 50)

    try:
        import psycopg2

        print("✅ psycopg2 is installed")
    except ImportError:
        print("❌ psycopg2 is NOT installed")

    try:
        import psycopg2.binary

        # Check if it's actually working
        psycopg2.binary.__version__  # This will fail if not properly installed
        print("✅ psycopg2-binary is installed")
    except ImportError:
        print("❌ psycopg2-binary is NOT installed")

    try:
        import sqlalchemy

        print(f"✅ SQLAlchemy is installed (version: {sqlalchemy.__version__})")
    except ImportError:
        print("❌ SQLAlchemy is NOT installed")

    try:
        from sqlalchemy.dialects import postgresql

        # Check if dialect is actually available
        postgresql.dialect()  # This will fail if not properly installed
        print("✅ PostgreSQL dialect is available")
    except ImportError:
        print("❌ PostgreSQL dialect is NOT available")

    print()


def test_connection():
    """Test database connection"""
    print("🔌 Connection Test")
    print("=" * 50)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ Cannot test connection: DATABASE_URL not set")
        return

    try:
        from urllib.parse import urlparse

        import psycopg2

        parsed = urlparse(database_url)

        # Extract connection parameters
        host = parsed.hostname
        port = parsed.port or 5432
        database = parsed.path[1:] if parsed.path else None
        username = parsed.username
        password = parsed.password

        print(f"Attempting connection to: {host}:{port}/{database}")

        # Test direct psycopg2 connection
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=username,
            password=password,
            connect_timeout=10,
        )

        # Test a simple query
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()

        print("✅ Direct psycopg2 connection successful")
        print(f"   PostgreSQL version: {version[0]}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Direct psycopg2 connection failed: {e}")

    try:
        from sqlalchemy import create_engine

        # Test SQLAlchemy connection
        engine = create_engine(database_url, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            result = conn.execute("SELECT version();")
            version = result.fetchone()

        print("✅ SQLAlchemy connection successful")
        print(f"   PostgreSQL version: {version[0]}")

    except Exception as e:
        print(f"❌ SQLAlchemy connection failed: {e}")

    print()


def main():
    """Main debug function"""
    print("🐛 Database Connection Debug Tool")
    print("=" * 50)
    print()

    check_environment()
    check_dependencies()
    test_connection()

    print("🏁 Debug complete")


if __name__ == "__main__":
    main()
