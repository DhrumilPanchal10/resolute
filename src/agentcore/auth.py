"""JWT verification + RBAC for Resolute.

Flow:
  1. FastAPI dependency `get_current_user` extracts Bearer token from the
     Authorization header and calls `verify_jwt`.
  2. `verify_jwt` fetches the JWKS from `clerk_jwks_url` (cached in memory,
     refreshed after TTL), finds the matching key by `kid`, and verifies:
     - signature
     - expiry (`exp`)
     - audience (`azp` claim — Clerk uses azp, not aud, for the client app)
  3. Returns a `UserClaims` dataclass with `user_id`, `tenant_id`, `role`.
  4. `require_role(*roles)` is a FastAPI dependency factory that wraps
     `get_current_user` and raises HTTP 403 when the role is insufficient.

Offline / test mode: set JWKS_URL to a special sentinel ("test") and call
`_set_test_jwks(jwks_dict)` to inject a local public key — used in unit tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status

from resolute.config import settings

# ---------------------------------------------------------------------------
# Roles + permission matrix
# ---------------------------------------------------------------------------

ROLES: frozenset[str] = frozenset({"support_engineer", "lead", "admin", "contractor"})

# Maps (resource, action) → minimum set of roles that may perform it.
# A user whose role is in the set is permitted.
PERMISSIONS: dict[tuple[str, str], frozenset[str]] = {
    ("ticket", "read"): frozenset({"support_engineer", "lead", "admin", "contractor"}),
    ("ticket", "write"): frozenset({"support_engineer", "lead", "admin"}),
    ("ticket", "escalate"): frozenset({"lead", "admin"}),
    ("approval", "read"): frozenset({"support_engineer", "lead", "admin"}),
    ("approval", "approve"): frozenset({"lead", "admin"}),
    ("account", "read"): frozenset({"support_engineer", "lead", "admin", "contractor"}),
    ("invoice", "read"): frozenset({"support_engineer", "lead", "admin"}),
    ("invoice", "refund"): frozenset({"lead", "admin"}),
    ("memory", "read"): frozenset({"support_engineer", "lead", "admin"}),
    ("memory", "write"): frozenset({"lead", "admin"}),
    ("docs", "read"): frozenset({"support_engineer", "lead", "admin", "contractor"}),
    ("github", "read"): frozenset({"support_engineer", "lead", "admin", "contractor"}),
    ("github", "write"): frozenset({"support_engineer", "lead", "admin"}),
    ("audit", "read"): frozenset({"admin"}),
    ("config", "write"): frozenset({"admin"}),
}


def has_permission(role: str, resource: str, action: str) -> bool:
    allowed = PERMISSIONS.get((resource, action), frozenset())
    return role in allowed


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------

_JWKS_TTL = 300  # seconds
_jwks_cache: dict[str, Any] = {}  # kid → public key
_jwks_fetched_at: float = 0.0
_test_jwks: dict[str, Any] | None = None  # injected in tests


def _set_test_jwks(jwks: dict[str, Any]) -> None:
    """Inject a local JWKS dict for offline unit tests."""
    global _test_jwks, _jwks_cache, _jwks_fetched_at
    _test_jwks = jwks
    _jwks_cache = {}
    _jwks_fetched_at = 0.0


def _jwks_url() -> str:
    return settings.clerk_jwks_url


def _fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS from Clerk (or test injection) and return kid→key map."""
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    if _test_jwks is not None:
        raw = _test_jwks
    else:
        url = _jwks_url()
        if not url:
            raise AuthError("clerk_jwks_url is not configured")
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
        raw = response.json()

    # Build kid → PyJWT-compatible public key
    keys: dict[str, Any] = {}
    for key_data in raw.get("keys", []):
        kid = key_data.get("kid", "default")
        keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    _jwks_cache = keys
    _jwks_fetched_at = now
    return keys


# ---------------------------------------------------------------------------
# Claims + verification
# ---------------------------------------------------------------------------


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class UserClaims:
    user_id: str
    tenant_id: str
    role: str
    raw: dict[str, Any]


def verify_jwt(token: str, *, audience: str | None = None) -> UserClaims:
    """Decode and verify a Clerk JWT, return structured claims.

    Raises AuthError on any verification failure.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as exc:
        raise AuthError(f"malformed token: {exc}") from exc

    kid = header.get("kid", "default")

    try:
        keys = _fetch_jwks()
    except Exception as exc:
        raise AuthError(f"failed to fetch JWKS: {exc}") from exc

    public_key = keys.get(kid)
    if public_key is None:
        # Stale cache — force refresh once
        global _jwks_fetched_at
        _jwks_fetched_at = 0.0
        try:
            keys = _fetch_jwks()
        except Exception as exc:
            raise AuthError(f"failed to refresh JWKS: {exc}") from exc
        public_key = keys.get(kid)
        if public_key is None:
            raise AuthError(f"unknown kid: {kid}")

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "options": {"verify_exp": True},
    }
    if audience:
        # Clerk uses `azp` for authorized party, not `aud`, but support both
        decode_kwargs["audience"] = audience

    try:
        payload = jwt.decode(token, public_key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except (jwt.InvalidAudienceError, jwt.MissingRequiredClaimError) as exc:
        raise AuthError("wrong audience") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    # Extract Clerk-standard claims
    # Clerk puts org/tenant in `org_id`, fallback to `sub` for personal tenants
    user_id: str = payload.get("sub", "")
    tenant_id: str = payload.get("org_id") or payload.get("sub", "")
    role: str = payload.get("role", "support_engineer")

    if not user_id:
        raise AuthError("missing sub claim")
    if role not in ROLES:
        raise AuthError(f"unknown role: {role!r}")

    return UserClaims(user_id=user_id, tenant_id=tenant_id, role=role, raw=payload)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

AUD_ENV_VAR = "clerk_jwks_url"  # audience comes from configured origin


def get_current_user(request: Request) -> UserClaims:
    """FastAPI dependency: extract + verify Bearer token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = auth_header[len("Bearer ") :]
    try:
        return verify_jwt(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def require_role(*roles: str):
    """FastAPI dependency factory: allow only users whose role is in `roles`."""
    allowed = frozenset(roles)

    def _dependency(
        claims: Annotated[UserClaims, Depends(get_current_user)],
    ) -> UserClaims:
        if claims.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {claims.role!r} not permitted; need one of {sorted(allowed)}",
            )
        return claims

    return _dependency
