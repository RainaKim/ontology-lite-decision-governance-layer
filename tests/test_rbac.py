"""
tests/test_rbac.py — Unit tests for RBAC role enforcement.

Tests call the dependency function directly with mock User objects.
No TestClient needed — avoids httpx version incompatibilities.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from app.services.rbac_service import require_role, require_admin, require_manager_up, require_any


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_user(role: str) -> MagicMock:
    """Return a mock that looks like an authenticated User ORM object."""
    user = MagicMock()
    user.id = "test-uuid"
    user.email = "test@example.com"
    user.role = role
    user.is_active = True
    return user


def _call_dep(dep_factory, role: str):
    """
    Simulate FastAPI calling the dependency.

    dep_factory — result of require_role(...) i.e. the _dep function.
    """
    user = _make_user(role)
    # _dep expects current_user as argument (injected by FastAPI via Depends)
    return dep_factory(current_user=user)


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def _dep(self):
        return require_role("ADMIN")

    def test_admin_allowed(self):
        result = _call_dep(self._dep(), "ADMIN")
        assert result.role == "ADMIN"

    def test_manager_denied(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_dep(self._dep(), "MANAGER")
        assert exc_info.value.status_code == 403

    def test_user_denied(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_dep(self._dep(), "USER")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_manager_up (ADMIN | MANAGER)
# ---------------------------------------------------------------------------


class TestRequireManagerUp:
    def _dep(self):
        return require_role("ADMIN", "MANAGER")

    def test_admin_allowed(self):
        result = _call_dep(self._dep(), "ADMIN")
        assert result.role == "ADMIN"

    def test_manager_allowed(self):
        result = _call_dep(self._dep(), "MANAGER")
        assert result.role == "MANAGER"

    def test_user_denied(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_dep(self._dep(), "USER")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_any (ADMIN | MANAGER | USER)
# ---------------------------------------------------------------------------


class TestRequireAny:
    def _dep(self):
        return require_role("ADMIN", "MANAGER", "USER")

    def test_admin_allowed(self):
        result = _call_dep(self._dep(), "ADMIN")
        assert result.role == "ADMIN"

    def test_manager_allowed(self):
        result = _call_dep(self._dep(), "MANAGER")
        assert result.role == "MANAGER"

    def test_user_allowed(self):
        result = _call_dep(self._dep(), "USER")
        assert result.role == "USER"

    def test_unknown_role_denied(self):
        with pytest.raises(HTTPException) as exc_info:
            _call_dep(self._dep(), "UNKNOWN_ROLE")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------


class TestAliases:
    """Verify that require_admin / require_manager_up / require_any work identically."""

    def test_require_admin_alias(self):
        user = _make_user("ADMIN")
        result = require_admin(current_user=user)
        assert result.role == "ADMIN"

    def test_require_manager_up_alias_admin(self):
        result = require_manager_up(current_user=_make_user("ADMIN"))
        assert result.role == "ADMIN"

    def test_require_manager_up_alias_manager(self):
        result = require_manager_up(current_user=_make_user("MANAGER"))
        assert result.role == "MANAGER"

    def test_require_any_alias_user(self):
        result = require_any(current_user=_make_user("USER"))
        assert result.role == "USER"
