"""JWT *verification* only — Supabase Auth owns hashing/issuance (CODING_STRUCTURE.md §2).

Checklist implemented here, verbatim from ARCHITECTURE.md §4 (itself checked against
supabase/auth/jwt-fields.md + owasp-asvs-5 v9-self-contained-tokens):
  1. Algorithm allowlist — RS256/ES256 only, passed explicitly (never trust the token's own `alg`).
  2. Key source — this project's own JWKS endpoint only, never a `jku`/`x5u` header.
  3. `exp`/`nbf` — checked by PyJWT automatically.
  4. `iss` — must match this Supabase project's issuer URL.
  5. `aud` — must be "authenticated"; PyJWT only checks this if passed explicitly.
"""

from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import settings

_ALGORITHMS = ["RS256", "ES256"]
_jwks_client = PyJWKClient(settings.JWKS_URL)


class InvalidTokenError(Exception):
    pass


def verify_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a Supabase-issued access token. Raises InvalidTokenError on any failure."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            audience="authenticated",
            issuer=settings.JWT_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
