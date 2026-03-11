"""
Unit tests for auth_service (password + JWT) and user_service (signup/login).

Deterministic — no real DB, no real API keys.
DB interactions are mocked with unittest.mock.

Run:
    python -m pytest tests/test_auth.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services import auth_service
from app.services.auth_service import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: str = "test-uuid-1234",
    email: str = "user@example.com",
    password: str = "plaintextpass",
    name: Optional[str] = "Test User",
    is_active: bool = True,
) -> MagicMock:
    """Return a mock that looks like a User ORM object."""
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.password_hash = hash_password(password)
    user.name = name
    user.is_active = is_active
    user.created_at = datetime.now(timezone.utc)
    return user


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:

    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mypassword")
        assert hashed != "mypassword"

    def test_verify_correct_password(self):
        hashed = hash_password("correct_horse")
        assert verify_password("correct_horse", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct_horse")
        assert verify_password("wrong_horse", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt uses a random salt per hash."""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2

    def test_verify_still_works_with_different_hashes(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert verify_password("same_password", h1) is True
        assert verify_password("same_password", h2) is True


# ---------------------------------------------------------------------------
# JWT creation + decoding
# ---------------------------------------------------------------------------


class TestJWT:

    def test_token_is_string(self):
        token = create_access_token(sub="user-123")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_returns_correct_sub(self):
        token = create_access_token(sub="user-abc")
        payload = decode_token(token)
        assert payload["sub"] == "user-abc"

    def test_decode_contains_exp(self):
        token = create_access_token(sub="user-abc")
        payload = decode_token(token)
        assert "exp" in payload

    def test_decode_expired_token_raises_401(self):
        """Token with 0-minute expiry should be immediately expired."""
        token = create_access_token(sub="user-abc", expires_minutes=0)
        # 0-minute token is expired immediately after creation
        import time
        time.sleep(1)  # ensure it expires
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_decode_invalid_token_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_token("not.a.valid.jwt")
        assert exc_info.value.status_code == 401

    def test_decode_tampered_token_raises_401(self):
        """Modifying the signature should fail verification."""
        import base64
        from fastapi import HTTPException

        token = create_access_token(sub="user-abc")
        parts = token.split(".")
        # Flip one character in the signature
        bad_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        bad_token = ".".join([parts[0], parts[1], bad_sig])
        with pytest.raises(HTTPException) as exc_info:
            decode_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_different_secrets_produce_different_tokens(self):
        """Tokens signed with different secrets must not verify against each other."""
        import os
        from fastapi import HTTPException

        original_secret = auth_service.JWT_SECRET
        token_a = create_access_token(sub="user-1")

        # Patch the module-level secret
        auth_service.JWT_SECRET = "completely_different_secret"
        try:
            with pytest.raises(HTTPException):
                decode_token(token_a)
        finally:
            auth_service.JWT_SECRET = original_secret


# ---------------------------------------------------------------------------
# User service — signup
# ---------------------------------------------------------------------------


class TestUserServiceSignup:

    def test_signup_creates_user(self):
        from app.services.user_service import signup

        mock_db = MagicMock()
        new_user = _make_user()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = None  # email not taken
            mock_repo.create.return_value = new_user

            result = signup(mock_db, email="test@example.com", password="password123")

        mock_repo.create.assert_called_once()
        # Password hash passed, not plaintext
        call_kwargs = mock_repo.create.call_args.kwargs
        assert call_kwargs["password_hash"] != "password123"
        assert result is new_user

    def test_signup_duplicate_email_raises_409(self):
        from fastapi import HTTPException
        from app.services.user_service import signup

        mock_db = MagicMock()
        existing_user = _make_user()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = existing_user  # email taken

            with pytest.raises(HTTPException) as exc_info:
                signup(mock_db, email="test@example.com", password="password123")

        assert exc_info.value.status_code == 409

    def test_signup_normalizes_email_to_lowercase(self):
        from app.services.user_service import signup

        mock_db = MagicMock()
        new_user = _make_user()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = None
            mock_repo.create.return_value = new_user

            signup(mock_db, email="TEST@EXAMPLE.COM", password="password123")

        call_kwargs = mock_repo.create.call_args.kwargs
        assert call_kwargs["email"] == "test@example.com"


# ---------------------------------------------------------------------------
# User service — login
# ---------------------------------------------------------------------------


class TestUserServiceLogin:

    def test_login_returns_token_and_user(self):
        from app.services.user_service import login

        mock_db = MagicMock()
        user = _make_user(password="correct_pass")

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = user
            mock_repo.set_last_login.return_value = None

            token, returned_user = login(mock_db, email="user@example.com", password="correct_pass")

        assert isinstance(token, str) and len(token) > 10
        assert returned_user is user

    def test_login_wrong_password_raises_401(self):
        from fastapi import HTTPException
        from app.services.user_service import login

        mock_db = MagicMock()
        user = _make_user(password="correct_pass")

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = user

            with pytest.raises(HTTPException) as exc_info:
                login(mock_db, email="user@example.com", password="wrong_pass")

        assert exc_info.value.status_code == 401

    def test_login_unknown_email_raises_401(self):
        from fastapi import HTTPException
        from app.services.user_service import login

        mock_db = MagicMock()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                login(mock_db, email="nobody@example.com", password="any_pass")

        assert exc_info.value.status_code == 401

    def test_login_inactive_user_raises_403(self):
        from fastapi import HTTPException
        from app.services.user_service import login

        mock_db = MagicMock()
        inactive_user = _make_user(password="correct_pass", is_active=False)

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_email.return_value = inactive_user

            with pytest.raises(HTTPException) as exc_info:
                login(mock_db, email="user@example.com", password="correct_pass")

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# User service — get_current_user
# ---------------------------------------------------------------------------


class TestGetCurrentUser:

    def _make_credentials(self, token: str) -> MagicMock:
        creds = MagicMock()
        creds.credentials = token
        return creds

    def test_valid_token_returns_user(self):
        from app.services.user_service import get_current_user

        user = _make_user(user_id="uid-999")
        token = create_access_token(sub="uid-999")
        creds = self._make_credentials(token)
        mock_db = MagicMock()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_id.return_value = user
            result = get_current_user(credentials=creds, db=mock_db)

        assert result is user

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException
        from app.services.user_service import get_current_user

        creds = self._make_credentials("bad.token.here")
        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401

    def test_user_not_found_raises_401(self):
        from fastapi import HTTPException
        from app.services.user_service import get_current_user

        token = create_access_token(sub="nonexistent-id")
        creds = self._make_credentials(token)
        mock_db = MagicMock()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_id.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401

    def test_inactive_user_raises_403(self):
        from fastapi import HTTPException
        from app.services.user_service import get_current_user

        inactive_user = _make_user(user_id="uid-999", is_active=False)
        token = create_access_token(sub="uid-999")
        creds = self._make_credentials(token)
        mock_db = MagicMock()

        with patch("app.services.user_service.user_repository") as mock_repo:
            mock_repo.get_by_id.return_value = inactive_user

            with pytest.raises(HTTPException) as exc_info:
                get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 403
