import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_user():
    """Returns a configurable mock user. Override attributes as needed in tests."""
    user = MagicMock()
    user.id = 1
    user.email = "test@example.com"
    user.company_id = "nexus_dynamics"
    # role set by individual tests or default
    return user


@pytest.fixture
def mock_company():
    """Returns a MagicMock Company with common attributes."""
    company = MagicMock()
    company.id = 1
    company.company_name = "Test Company"
    company.domain_url = "example.com"
    company.auth_type = "local"
    company.sso_client_id = "client_id"
    company.sso_client_secret = "client_secret"
    company.sso_tenant_id = None
    return company
