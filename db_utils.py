#!/usr/bin/env python3
"""
Database utilities for PostgreSQL operations
"""

import os
import subprocess
import sys


def run_command(command, description, check=True):
    """Run a shell command and handle errors"""
    print(f"\n🔄 {description}...")
    try:
        # Split command into list for security
        if isinstance(command, str):
            import shlex

            cmd_list = shlex.split(command)
        else:
            cmd_list = command

        result = subprocess.run(cmd_list, check=check, capture_output=True, text=True)
        if check:
            print(f"✅ {description} completed successfully")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(e.stderr)
        return False


def start_db():
    """Start PostgreSQL and Redis containers"""
    print("🚀 Starting PostgreSQL and Redis containers...")
    return run_command(
        "docker-compose -f docker-compose.dev.yml up -d postgres redis",
        "Starting development database containers",
    )


def stop_db():
    """Stop PostgreSQL and Redis containers"""
    print("🛑 Stopping PostgreSQL and Redis containers...")
    return run_command(
        "docker-compose -f docker-compose.dev.yml down",
        "Stopping development database containers",
    )


def reset_db():
    """Reset the database (drop and recreate)"""
    print("⚠️  Resetting database (this will delete all data)...")

    # Stop containers
    stop_db()

    # Remove volumes
    run_command(
        "docker volume rm unforgettableevilbot_postgres-dev-data unforgettableevilbot_redis-dev-data",
        "Removing database volumes",
        check=False,
    )

    # Start containers
    if start_db():
        import time

        print("⏳ Waiting for PostgreSQL to initialize...")
        time.sleep(10)

        # Run migrations
        return run_command("alembic upgrade head", "Running database migrations")
    return False


def migrate():
    """Run database migrations"""
    return run_command("alembic upgrade head", "Running database migrations")


def create_migration(message):
    """Create a new migration"""
    if not message:
        print("❌ Please provide a migration message")
        return False
    return run_command(
        f'alembic revision --autogenerate -m "{message}"',
        f"Creating migration: {message}",
    )


def show_status():
    """Show database status"""
    print("📊 Database Status:")
    run_command(
        "docker-compose -f docker-compose.dev.yml ps", "Container status", check=False
    )
    run_command("alembic current", "Current migration", check=False)


def connect_db():
    """Connect to the database using psql"""
    print("🔌 Connecting to PostgreSQL...")
    os.system(
        "docker-compose -f docker-compose.dev.yml exec postgres psql -U postgres -d unforgettable_evil_bot"
    )


def main():
    """Main CLI function"""
    if len(sys.argv) < 2:
        print(
            """
📚 Database Utilities

Usage: python db_utils.py <command>

Commands:
  start        - Start PostgreSQL and Redis containers
  stop         - Stop PostgreSQL and Redis containers
  reset        - Reset database (WARNING: deletes all data)
  migrate      - Run database migrations
  create <msg> - Create new migration with message
  status       - Show database and container status
  connect      - Connect to database with psql
        """
        )
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "start":
        start_db()
    elif command == "stop":
        stop_db()
    elif command == "reset":
        reset_db()
    elif command == "migrate":
        migrate()
    elif command == "create":
        if len(sys.argv) < 3:
            print("❌ Please provide a migration message")
            sys.exit(1)
        create_migration(sys.argv[2])
    elif command == "status":
        show_status()
    elif command == "connect":
        connect_db()
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
