#!/usr/bin/env python3
"""
Script for creating a database from scratch, bypassing SQLite migration issues
"""

import os
import sys

from sqlalchemy.orm import sessionmaker

from app.database.connection import engine
from app.models.database import Base

sys.path.append(".")


def create_fresh_database():
    """Create a new database with current structure"""
    print("🗄️ Creating new database with correct structure...")

    try:
        # Remove old database if exists
        if os.path.exists("whatsapp_digest.db"):
            os.remove("whatsapp_digest.db")
            print("✅ Old database removed")

        # Create all tables with new structure
        Base.metadata.create_all(bind=engine)
        print("✅ Database created with current structure")

        # Create session for adding test data
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()

        # Add test user
        from app.auth.security import get_password_hash
        from app.models.database import User

        test_user = User(
            id=1,
            username="testuser",
            email="test@example.com",
            hashed_password=get_password_hash("testpass123"),
            whatsapp_connected=False,
            whatsapp_auto_reconnect=True,
            digest_interval_hours=4,
            is_active=True,
        )

        db.add(test_user)
        db.commit()
        db.refresh(test_user)
        print("✅ Test user created (ID: 1)")

        # Create default settings for test user
        from app.core.user_utils import create_default_user_settings

        create_default_user_settings(test_user.id, db)
        print("✅ Default settings created for test user")

        # Verify that all fields are actually created
        print("📋 Database structure verification:")
        print(f"   • whatsapp_last_seen: {hasattr(test_user, 'whatsapp_last_seen')}")
        print(
            f"   • whatsapp_auto_reconnect: {hasattr(test_user, 'whatsapp_auto_reconnect')}"
        )
        print(f"   • updated_at: {hasattr(test_user, 'updated_at')}")

        # Check table structure directly
        from sqlalchemy import inspect

        inspector = inspect(engine)
        user_columns = [col["name"] for col in inspector.get_columns("users")]
        print(f"   • Users columns: {user_columns}")

        db.close()
        return True

    except Exception as e:
        print(f"❌ Database creation error: {e}")
        return False


if __name__ == "__main__":
    success = create_fresh_database()

    if success:
        print("\n🎉 Database ready for testing!")
        print("📋 Structure includes all fields for persistent monitoring:")
        print("   • whatsapp_last_seen - last connection time")
        print("   • whatsapp_auto_reconnect - auto-reconnection")
        print("   • auto_added - auto-added chats")
        print("   • ai_analyzed - AI analysis")
        print("   • processing_attempts - processing attempts")
        print("\n🚀 Now you can test webhooks!")
    else:
        print("\n❌ Failed to create database")
        sys.exit(1)
