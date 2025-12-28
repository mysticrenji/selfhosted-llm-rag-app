#!/usr/bin/env python3
"""Reset password for a user."""
import os
import sys

# Set local database connection
os.environ["AUTH_DATABASE_URL"] = "postgresql://langfuse:langfuse@localhost:5432/ragauth"  # pragma: allowlist secret

sys.path.insert(0, os.path.dirname(__file__))

from app.auth import get_db, get_user_by_username, hash_password, init_db


def reset_password(username: str, new_password: str):
    """Reset password for a user."""
    init_db()
    db = next(get_db())

    user = get_user_by_username(db, username)
    if not user:
        print(f"❌ User '{username}' not found")
        return

    # Update password
    user.hashed_password = hash_password(new_password)
    db.commit()
    print(f"✅ Password updated for user '{username}'")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python reset-password.py <username> <new_password>")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    reset_password(username, password)
