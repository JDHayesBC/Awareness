"""Haven — Token and password authentication."""

import hashlib
import bcrypt
from fastapi import Request, HTTPException


def hash_token(token: str) -> str:
    """SHA-256 hash a token for storage."""
    return hashlib.sha256(token.strip().encode()).hexdigest()


def verify_token(provided: str, stored_hash: str) -> bool:
    """Verify a token against its stored hash."""
    return hash_token(provided) == stored_hash


def hash_password(password: str) -> str:
    """Bcrypt hash a password for storage."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its stored bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


async def get_current_user_id(request: Request, db) -> str:
    """Extract and validate Bearer token from request. Returns user_id."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    token_h = hash_token(token)
    user = await db.get_user_by_token_hash(token_h)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user["id"]
