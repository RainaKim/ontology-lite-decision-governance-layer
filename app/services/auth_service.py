"""
app/services/auth_service.py — Password hashing + JWT utilities.

Env vars:
  JWT_SECRET              (required in production)
  JWT_ALG                 default "HS256"
  ACCESS_TOKEN_EXPIRES_MIN  default 60

No DB access. Stateless pure functions.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, status
from jwt.exceptions import ExpiredSignatureError, PyJWTError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET: str = os.environ.get("JWT_SECRET", "CHANGE_ME_in_production")
JWT_ALG: str = os.environ.get("JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRES_MIN: int = int(os.environ.get("ACCESS_TOKEN_EXPIRES_MIN", "60"))

# ---------------------------------------------------------------------------
# Password hashing (bcrypt — direct, no passlib)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if password matches the stored hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(
    sub: str,
    expires_minutes: Optional[int] = None,
) -> str:
    """
    Create a signed HS256 JWT.

    sub — the subject claim (user ID as string).
    """
    if expires_minutes is None:
        expires_minutes = ACCESS_TOKEN_EXPIRES_MIN

    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": sub,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT. Returns the payload dict on success.

    Raises:
        HTTPException 401 — token is expired or invalid.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
