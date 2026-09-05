"""Self-check for the JWT verification checklist in ARCHITECTURE.md §4 — no network/DB needed, the
JWKS fetch itself is mocked. Verifies the checklist is actually enforced, not just described.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import security

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _make_token(**overrides: object) -> str:
    now = int(time.time())
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "aud": "authenticated",
        "iss": security.settings.JWT_ISSUER,
        "exp": now + 3600,
        "app_metadata": {"firm_id": "22222222-2222-2222-2222-222222222222", "role": "owner"},
        **overrides,
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _mock_jwks(  # pyright: ignore[reportUnusedFunction] — autouse pytest fixture, run by pytest
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reaching into the module-private client is the point of this test — swapping the real
    # network call for a fixed key, not a leak to fix.
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=_PUBLIC_KEY),
    )


def test_valid_token_verifies() -> None:
    claims = security.verify_access_token(_make_token())
    assert claims["app_metadata"]["firm_id"] == "22222222-2222-2222-2222-222222222222"


def test_wrong_audience_rejected() -> None:
    # SonarQube S5778: only one call inside pytest.raises, so a bug that made _make_token() itself
    # raise couldn't be mistaken for verify_access_token correctly rejecting the token.
    token = _make_token(aud="something-else")
    with pytest.raises(security.InvalidTokenError):
        security.verify_access_token(token)


def test_wrong_issuer_rejected() -> None:
    token = _make_token(iss="https://attacker.example/auth/v1")
    with pytest.raises(security.InvalidTokenError):
        security.verify_access_token(token)


def test_expired_token_rejected() -> None:
    token = _make_token(exp=int(time.time()) - 10)
    with pytest.raises(security.InvalidTokenError):
        security.verify_access_token(token)


def test_algorithm_confusion_rejected() -> None:
    """The classic attack: sign with HS256 using the RSA *public* key (PEM bytes) as the HMAC
    secret. Must be rejected because `algorithms=` never includes HS256 — never because the
    signature happens to fail (ARCHITECTURE.md §4 item 1: allowlist, not trust-the-header).

    Hand-built (not `jwt.encode`) — PyJWT itself refuses to *encode* with a PEM key as an HMAC
    secret, which would hide the thing this test is actually checking: that a forged token built
    by a tool without that guard still can't get past `verify_access_token`'s algorithm allowlist.
    """
    import base64
    import hashlib
    import hmac
    import json

    from cryptography.hazmat.primitives import serialization

    public_pem = _PUBLIC_KEY.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(
        json.dumps(
            {
                "sub": "x",
                "aud": "authenticated",
                "iss": security.settings.JWT_ISSUER,
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    )
    mac = hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256)
    signature = b64url(mac.digest())
    forged = f"{header}.{payload}.{signature}"

    with pytest.raises(security.InvalidTokenError):
        security.verify_access_token(forged)
