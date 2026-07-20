"""Signed human-approval tokens for high-risk Actions."""

from __future__ import annotations

import os

import jwt

from app.auth.saas_authorization import (
    SAAS_AUTHORIZATION_JWT_ALGORITHMS_ENV_VAR,
    SAAS_AUTHORIZATION_JWT_ISSUER_ENV_VAR,
    SaasAuthorizationError,
)

APPROVAL_AUDIENCE = "semantic-action-approval"


def verify_action_approval(
    token: str,
    *,
    proposal_id: str,
    principal_id: str,
    scope_hash: str,
) -> str:
    key = os.environ.get("SAAS_ACTION_APPROVAL_JWT_KEY") or os.environ.get("SAAS_AUTHORIZATION_JWT_KEY")
    algorithms = [value.strip() for value in os.environ.get(SAAS_AUTHORIZATION_JWT_ALGORITHMS_ENV_VAR, "RS256").split(",") if value.strip()]
    issuer = os.environ.get("SAAS_ACTION_APPROVAL_JWT_ISSUER") or os.environ.get(
        SAAS_AUTHORIZATION_JWT_ISSUER_ENV_VAR,
        "saas-gateway",
    )
    issuer = issuer.strip()
    if not key or not algorithms or not issuer:
        raise SaasAuthorizationError("Action approval verification is not configured")
    try:
        claims = jwt.decode(
            token,
            key.replace("\\n", "\n"),
            algorithms=algorithms,
            audience=APPROVAL_AUDIENCE,
            issuer=issuer,
            options={
                "require": [
                    "exp",
                    "iat",
                    "iss",
                    "aud",
                    "sub",
                    "jti",
                    "proposal_id",
                    "scope_hash",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise SaasAuthorizationError("Invalid action approval token") from exc
    try:
        issued_at = int(claims["iat"])
        expires_at = int(claims["exp"])
        max_ttl = int(os.environ.get("SAAS_ACTION_APPROVAL_MAX_TTL_SECONDS", "300"))
    except (KeyError, TypeError, ValueError) as exc:
        raise SaasAuthorizationError("Invalid action approval token lifetime") from exc
    if max_ttl <= 0 or expires_at <= issued_at or expires_at - issued_at > max_ttl:
        raise SaasAuthorizationError("Action approval token lifetime exceeds policy")
    if claims.get("proposal_id") != proposal_id or claims.get("sub") != principal_id or claims.get("scope_hash") != scope_hash:
        raise SaasAuthorizationError("Action approval does not match proposal")
    return str(claims.get("approved_by") or principal_id)
