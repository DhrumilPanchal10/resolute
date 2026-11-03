"""Offline unit tests for auth.py (T2.4).

Uses a locally-generated RSA key pair — no Clerk API call, no network.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# Key-pair fixture shared across all tests in this module
# ---------------------------------------------------------------------------

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_KID = "test-kid-1"
_ALG = "RS256"


def _jwks_dict() -> dict[str, Any]:
    """JWKS JSON representation of the test public key."""
    from jwt.algorithms import RSAAlgorithm

    jwk = RSAAlgorithm.to_jwk(_PUBLIC_KEY)
    import json

    jwk_dict = json.loads(jwk)
    jwk_dict["kid"] = _KID
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = _ALG
    return {"keys": [jwk_dict]}


def _make_token(
    *,
    sub: str = "user_abc",
    org_id: str = "org_123",
    role: str = "support_engineer",
    exp_offset: int = 3600,  # seconds from now; negative = already expired
    kid: str = _KID,
    extra: dict | None = None,
) -> str:
    payload: dict[str, Any] = {
        "sub": sub,
        "org_id": org_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    if extra:
        payload.update(extra)

    priv_bytes = _PRIVATE_KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return jwt.encode(payload, priv_bytes, algorithm=_ALG, headers={"kid": kid})


# ---------------------------------------------------------------------------
# Setup: inject local JWKS before each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def inject_jwks():
    from agentcore.auth import _set_test_jwks

    _set_test_jwks(_jwks_dict())
    yield
    _set_test_jwks(None)  # clean up


# ---------------------------------------------------------------------------
# verify_jwt — happy path
# ---------------------------------------------------------------------------


class TestVerifyJWT:
    def test_valid_token_returns_claims(self) -> None:
        from agentcore.auth import verify_jwt

        token = _make_token(sub="u1", org_id="t1", role="lead")
        claims = verify_jwt(token)
        assert claims.user_id == "u1"
        assert claims.tenant_id == "t1"
        assert claims.role == "lead"

    def test_all_roles_accepted(self) -> None:
        from agentcore.auth import verify_jwt

        for role in ("support_engineer", "lead", "admin", "contractor"):
            token = _make_token(role=role)
            claims = verify_jwt(token)
            assert claims.role == role

    def test_raw_payload_included(self) -> None:
        from agentcore.auth import verify_jwt

        token = _make_token(extra={"custom": "value"})
        claims = verify_jwt(token)
        assert claims.raw["custom"] == "value"

    def test_no_org_id_falls_back_to_sub(self) -> None:
        from agentcore.auth import verify_jwt

        payload: dict[str, Any] = {
            "sub": "u_personal",
            "role": "support_engineer",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        priv_bytes = _PRIVATE_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        token = jwt.encode(payload, priv_bytes, algorithm=_ALG, headers={"kid": _KID})
        claims = verify_jwt(token)
        assert claims.tenant_id == "u_personal"


# ---------------------------------------------------------------------------
# verify_jwt — error cases
# ---------------------------------------------------------------------------


class TestVerifyJWTErrors:
    def test_expired_token_raises(self) -> None:
        from agentcore.auth import AuthError, verify_jwt

        token = _make_token(exp_offset=-10)
        with pytest.raises(AuthError, match="expired"):
            verify_jwt(token)

    def test_wrong_audience_raises(self) -> None:
        from agentcore.auth import AuthError, verify_jwt

        token = _make_token()
        # Pass a specific audience that the token doesn't satisfy
        with pytest.raises(AuthError, match="wrong audience"):
            verify_jwt(token, audience="https://app.example.com")

    def test_malformed_token_raises(self) -> None:
        from agentcore.auth import AuthError, verify_jwt

        with pytest.raises(AuthError, match="malformed"):
            verify_jwt("not.a.jwt")

    def test_unknown_kid_raises(self) -> None:
        from agentcore.auth import AuthError, verify_jwt

        token = _make_token(kid="unknown-kid")
        with pytest.raises(AuthError, match="unknown kid"):
            verify_jwt(token)

    def test_unknown_role_raises(self) -> None:
        from agentcore.auth import AuthError, verify_jwt

        token = _make_token(role="supervillain")
        with pytest.raises(AuthError, match="unknown role"):
            verify_jwt(token)

    def test_missing_sub_raises(self) -> None:
        from agentcore.auth import AuthError, verify_jwt

        payload: dict[str, Any] = {
            "role": "admin",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        priv_bytes = _PRIVATE_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        token = jwt.encode(payload, priv_bytes, algorithm=_ALG, headers={"kid": _KID})
        with pytest.raises(AuthError, match="missing sub"):
            verify_jwt(token)


# ---------------------------------------------------------------------------
# RBAC — permission matrix
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_support_engineer_can_read_ticket(self) -> None:
        from agentcore.auth import has_permission

        assert has_permission("support_engineer", "ticket", "read")

    def test_contractor_cannot_write_ticket(self) -> None:
        from agentcore.auth import has_permission

        assert not has_permission("contractor", "ticket", "write")

    def test_lead_can_approve(self) -> None:
        from agentcore.auth import has_permission

        assert has_permission("lead", "approval", "approve")

    def test_support_engineer_cannot_approve(self) -> None:
        from agentcore.auth import has_permission

        assert not has_permission("support_engineer", "approval", "approve")

    def test_only_admin_can_read_audit(self) -> None:
        from agentcore.auth import has_permission

        assert has_permission("admin", "audit", "read")
        assert not has_permission("lead", "audit", "read")
        assert not has_permission("support_engineer", "audit", "read")

    def test_only_admin_can_write_config(self) -> None:
        from agentcore.auth import has_permission

        assert has_permission("admin", "config", "write")
        assert not has_permission("lead", "config", "write")

    def test_unknown_resource_denied(self) -> None:
        from agentcore.auth import has_permission

        assert not has_permission("admin", "nonexistent", "action")


# ---------------------------------------------------------------------------
# FastAPI require_role dependency
# ---------------------------------------------------------------------------


class TestRequireRole:
    def _claims(self, role: str = "support_engineer"):
        from agentcore.auth import UserClaims

        return UserClaims(user_id="u1", tenant_id="t1", role=role, raw={"sub": "u1"})

    def test_allowed_role_passes(self) -> None:
        from agentcore.auth import require_role

        dep = require_role("lead", "admin")
        claims = self._claims("lead")
        result = dep(claims)
        assert result.role == "lead"

    def test_disallowed_role_raises_403(self) -> None:
        from fastapi import HTTPException

        from agentcore.auth import require_role

        dep = require_role("admin")
        claims = self._claims("support_engineer")
        with pytest.raises(HTTPException) as exc_info:
            dep(claims)
        assert exc_info.value.status_code == 403

    def test_multiple_allowed_roles(self) -> None:
        from agentcore.auth import require_role

        dep = require_role("lead", "admin", "support_engineer")
        for role in ("lead", "admin", "support_engineer"):
            result = dep(self._claims(role))
            assert result.role == role
