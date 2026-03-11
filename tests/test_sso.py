"""
tests/test_sso.py — Unit tests for SSO service (mocked httpx + DB).

Tests cover:
  - State JWT round-trip (_make_state / verify_state)
  - Authorization URL generation (Google + Azure)
  - Token exchange (Google + Azure) with mocked httpx responses
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest

from app.services import sso_service
from app.services.auth_service import JWT_ALG, JWT_SECRET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company(
    auth_type: str = "GOOGLE_SSO",
    sso_client_id: str = "client-id-123",
    sso_client_secret: str = "secret-xyz",
    sso_tenant_id: str | None = None,
) -> MagicMock:
    """Return a mock that looks like a Company ORM object."""
    c = MagicMock()
    c.id = "company-uuid-abc"
    c.company_name = "Test Corp"
    c.domain_url = "testcorp.example.com"
    c.auth_type = auth_type
    c.status = "ACTIVE"
    c.sso_client_id = sso_client_id
    c.sso_client_secret = sso_client_secret
    c.sso_tenant_id = sso_tenant_id
    return c


# ---------------------------------------------------------------------------
# State JWT tests
# ---------------------------------------------------------------------------


class TestStateJWT:
    def test_roundtrip(self):
        company_id = "company-abc"
        state = sso_service._make_state(company_id)
        result = sso_service.verify_state(state)
        assert result == company_id

    def test_expired_raises(self):
        from fastapi import HTTPException

        payload = {
            "company_id": "x",
            "nonce": "n",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        expired = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)
        with pytest.raises(HTTPException) as exc_info:
            sso_service.verify_state(expired)
        assert exc_info.value.status_code == 400

    def test_tampered_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            sso_service.verify_state("not.a.valid.jwt")
        assert exc_info.value.status_code == 400

    def test_missing_company_id_raises(self):
        from fastapi import HTTPException

        payload = {
            "nonce": "n",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        state = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)
        with pytest.raises(HTTPException) as exc_info:
            sso_service.verify_state(state)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Google auth URL tests
# ---------------------------------------------------------------------------


class TestGoogleAuthUrl:
    def test_url_contains_client_id(self):
        company = _make_company(auth_type="GOOGLE_SSO")
        url = sso_service.get_google_auth_url(company)
        assert "client-id-123" in url
        assert "accounts.google.com" in url
        assert "scope=openid" in url or "scope=" in url

    def test_no_client_id_raises(self):
        from fastapi import HTTPException

        company = _make_company(sso_client_id=None)
        with pytest.raises(HTTPException) as exc_info:
            sso_service.get_google_auth_url(company)
        assert exc_info.value.status_code == 400

    def test_state_embeds_company_id(self):
        company = _make_company(auth_type="GOOGLE_SSO")
        url = sso_service.get_google_auth_url(company)
        # Extract state param
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        state = params["state"][0]
        recovered = sso_service.verify_state(state)
        assert recovered == company.id


# ---------------------------------------------------------------------------
# Azure auth URL tests
# ---------------------------------------------------------------------------


class TestAzureAuthUrl:
    def test_url_contains_tenant(self):
        company = _make_company(
            auth_type="AZURE_SSO", sso_tenant_id="my-tenant-id"
        )
        url = sso_service.get_azure_auth_url(company)
        assert "my-tenant-id" in url
        assert "login.microsoftonline.com" in url

    def test_missing_tenant_raises(self):
        from fastapi import HTTPException

        company = _make_company(auth_type="AZURE_SSO", sso_tenant_id=None)
        with pytest.raises(HTTPException) as exc_info:
            sso_service.get_azure_auth_url(company)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Google token exchange tests (mocked httpx)
# ---------------------------------------------------------------------------


class TestExchangeGoogleCode:
    def _mock_http_responses(self, token_json: dict, userinfo_json: dict):
        """Return a context manager that mocks httpx.Client."""
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = token_json

        info_resp = MagicMock()
        info_resp.status_code = 200
        info_resp.json.return_value = userinfo_json

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = token_resp
        mock_client.get.return_value = info_resp

        return patch("app.services.sso_service.httpx.Client", return_value=mock_client)

    def test_success(self):
        company = _make_company(auth_type="GOOGLE_SSO")
        with self._mock_http_responses(
            {"access_token": "tok123"},
            {"email": "alice@corp.com", "name": "Alice", "sub": "g-sub-001"},
        ):
            result = sso_service.exchange_google_code("auth-code", company)

        assert result["email"] == "alice@corp.com"
        assert result["name"] == "Alice"
        assert result["sub"] == "g-sub-001"

    def test_token_error_raises(self):
        from fastapi import HTTPException

        company = _make_company(auth_type="GOOGLE_SSO")

        err_resp = MagicMock()
        err_resp.status_code = 400
        err_resp.json.return_value = {"error": "invalid_grant"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = err_resp

        with patch("app.services.sso_service.httpx.Client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                sso_service.exchange_google_code("bad-code", company)
        assert exc_info.value.status_code == 502

    def test_missing_email_raises(self):
        from fastapi import HTTPException

        company = _make_company(auth_type="GOOGLE_SSO")
        with self._mock_http_responses(
            {"access_token": "tok"},
            {"name": "No Email User"},  # no email field
        ):
            with pytest.raises(HTTPException) as exc_info:
                sso_service.exchange_google_code("code", company)
        assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# Azure token exchange tests (mocked httpx)
# ---------------------------------------------------------------------------


class TestExchangeAzureCode:
    def _make_id_token(self, claims: dict) -> str:
        """Create an unsigned-like JWT (RS256 header but HS256 signed — for decode without verify)."""
        return jwt.encode(claims, "unused", algorithm="HS256")

    def _mock_http_client(self, id_token: str, status_code: int = 200):
        token_resp = MagicMock()
        token_resp.status_code = status_code
        token_resp.json.return_value = {"id_token": id_token}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = token_resp
        return patch("app.services.sso_service.httpx.Client", return_value=mock_client)

    def test_success(self):
        company = _make_company(auth_type="AZURE_SSO", sso_tenant_id="tenant-1")
        id_token = self._make_id_token(
            {
                "email": "bob@azure.com",
                "name": "Bob",
                "sub": "az-sub-999",
                "exp": 9999999999,
            }
        )
        with self._mock_http_client(id_token):
            result = sso_service.exchange_azure_code("az-code", company)

        assert result["email"] == "bob@azure.com"
        assert result["name"] == "Bob"
        assert result["sub"] == "az-sub-999"

    def test_preferred_username_fallback(self):
        """Azure sometimes puts UPN in preferred_username instead of email."""
        company = _make_company(auth_type="AZURE_SSO", sso_tenant_id="tenant-1")
        id_token = self._make_id_token(
            {"preferred_username": "carol@corp.onmicrosoft.com", "sub": "x", "exp": 9999999999}
        )
        with self._mock_http_client(id_token):
            result = sso_service.exchange_azure_code("code", company)
        assert result["email"] == "carol@corp.onmicrosoft.com"

    def test_token_error_raises(self):
        from fastapi import HTTPException

        company = _make_company(auth_type="AZURE_SSO", sso_tenant_id="t")

        err_resp = MagicMock()
        err_resp.status_code = 400
        err_resp.json.return_value = {"error": "invalid_grant"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = err_resp

        with patch("app.services.sso_service.httpx.Client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                sso_service.exchange_azure_code("bad", company)
        assert exc_info.value.status_code == 502
