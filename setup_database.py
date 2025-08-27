#!/usr/bin/env python3
"""
Database setup script for PostgreSQL
This script will create the database and run migrations
"""

import subprocess
import sys
from pathlib import Path


def run_command(command, description):
    """Run a shell command and handle errors"""
    print(f"\n🔄 {description}...")
    try:
        # Split command into list for security
        if isinstance(command, str):
            import shlex

            cmd_list = shlex.split(command)
        else:
            cmd_list = command

        result = subprocess.run(cmd_list, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(e.stderr)
        return False


def main():
    """Main setup function"""
    print("🚀 Setting up PostgreSQL database for Unforgettable Evil Bot")

    # Check if we're in the right directory
    if not Path("alembic.ini").exists():
        print(
            "❌ Error: alembic.ini not found. Please run this script from the project root directory."
        )
        sys.exit(1)

    # Start PostgreSQL and Redis containers
    print("\n📦 Starting PostgreSQL and Redis containers...")
    if not run_command(
        "docker-compose -f docker-compose.dev.yml up -d postgres redis",
        "Starting development database containers",
    ):
        print("❌ Failed to start containers. Please check Docker is running.")
        sys.exit(1)

    # Wait for PostgreSQL to be ready
    print("\n⏳ Waiting for PostgreSQL to be ready...")
    if not run_command(
        "docker-compose -f docker-compose.dev.yml exec postgres pg_isready -U postgres",
        "Checking PostgreSQL readiness",
    ):
        print("⚠️  PostgreSQL may not be ready yet. Waiting 10 seconds...")
        import time

        time.sleep(10)

    # Run Alembic migrations
    print("\n🔧 Running database migrations...")
    if not run_command("alembic upgrade head", "Running Alembic migrations"):
        print(
            "❌ Migration failed. Please check your database connection and migration files."
        )
        sys.exit(1)

    print("\n🎉 Database setup completed successfully!")
    print("\n📋 Connection details:")
    print("  Host: localhost")
    print("  Port: 5432")
    print("  Database: unforgettable_evil_bot")
    print("  Username: postgres")
    print("  Password: postgres")
    print("\n💡 To connect to the database:")
    print("  psql -h localhost -U postgres -d unforgettable_evil_bot")
    print("\n🛑 To stop the containers:")
    print("  docker-compose -f docker-compose.dev.yml down")


if __name__ == "__main__":
    main()
