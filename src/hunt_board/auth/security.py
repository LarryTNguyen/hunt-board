from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWKClient

from hunt_board.core.config import Settings, get_settings


class TokenVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class SupabaseIdentity:
    auth_user_id: UUID
    email: str
    provider: str
    email_verified: bool
    claims: dict[str, Any]


def normalize_email(value: str) -> str:
    return value.strip().casefold()


class SupabaseJWTVerifier:
    def __init__(self, settings: Settings):
        if not settings.supabase_url or not settings.supabase_jwt_issuer:
            raise TokenVerificationError("Supabase authentication is not configured")
        self.settings = settings
        self.jwks = PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=300,
        )

    def verify(self, token: str) -> SupabaseIdentity:
        try:
            signing_key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256", "EdDSA"],
                audience=self.settings.supabase_jwt_audience,
                issuer=self.settings.supabase_jwt_issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except ExpiredSignatureError as exc:
            raise TokenVerificationError("Access token has expired") from exc
        except (InvalidTokenError, ValueError, OSError) as exc:
            raise TokenVerificationError("Access token is invalid") from exc

        email = claims.get("email")
        if not isinstance(email, str) or not normalize_email(email):
            raise TokenVerificationError("Access token has no usable email claim")
        try:
            auth_user_id = UUID(str(claims["sub"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise TokenVerificationError("Access token subject is invalid") from exc

        app_metadata = claims.get("app_metadata")
        user_metadata = claims.get("user_metadata")
        provider = app_metadata.get("provider") if isinstance(app_metadata, dict) else None
        amr = claims.get("amr")
        if not provider and isinstance(amr, list) and amr:
            first = amr[0]
            provider = first.get("method") if isinstance(first, dict) else None
        provider = str(provider or "unknown")
        verified = bool(
            claims.get("email_verified")
            or claims.get("email_confirmed_at")
            or (isinstance(user_metadata, dict) and user_metadata.get("email_verified"))
            or provider in {"google", "magiclink", "otp"}
        )
        return SupabaseIdentity(
            auth_user_id=auth_user_id,
            email=normalize_email(email),
            provider=provider,
            email_verified=verified,
            claims=claims,
        )


@lru_cache(maxsize=1)
def get_token_verifier() -> SupabaseJWTVerifier:
    return SupabaseJWTVerifier(get_settings())
