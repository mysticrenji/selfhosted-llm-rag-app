#!/usr/bin/env python3
"""Delete a user from the database."""
import os
import sys

# Set local database connection
os.environ["AUTH_DATABASE_URL"] = "postgresql://langfuse:langfuse@localhost:5432/ragauth"  # pragma: allowlist secret

# Add the parent directory to path so we can import app module
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from app.auth import get_db, get_user_by_username, init_db


def delete_user(username: str):
    """Delete a user by username."""
    init_db()
    db = next(get_db())

    user = get_user_by_username(db, username)
    if not user:
        print(f"❌ User '{username}' not found")
        return

    # Delete user
    db.delete(user)
    db.commit()
    print(f"✅ User '{username}' deleted successfully")


def list_all_users():
    """List all users in the database."""
    init_db()
    db = next(get_db())

    from app.auth import User

    users = db.query(User).all()

    if not users:
        print("No users found in database")
        return

    print("\n📋 Current users:")
    print("-" * 60)
    for user in users:
        print(f"ID: {user.id:3d} | Username: {user.username:20s} | Email: {user.email}")
    print("-" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python delete-user.py <username>           # Delete a specific user")
        print("  python delete-user.py --list               # List all users")
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_all_users()
    else:
        username = sys.argv[1]
        delete_user(username)
