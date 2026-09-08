"""Generates a throwaway RSA keypair for the load test's local JWKS stub — never used for anything
but this, never committed (see .gitignore in this directory).

Run once before seed.py / before starting uvicorn. Persists to disk (private_key.pem, www/) instead
of living only in this process's memory, so seed.py (mints tokens) and `python -m http.server`
(serves the JWKS response, from the `www/` directory this writes) can run as two independent
processes against the *same* key without either importing the other.

`www/auth/v1/.well-known/jwks.json` mirrors Supabase's real JWKS path exactly — `config.py`'s
JWKS_URL is computed as f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", so pointing the target
server's SUPABASE_URL at wherever `www/` gets served (e.g. `python -m http.server 9999` from this
directory) makes app/core/security.py's real PyJWKClient resolve to this stub with zero code change.
"""

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

# Must match seed.py's _KID exactly — PyJWT's PyJWKClient filters out any JWKS key with no `kid`
# entirely (verified against the installed jwt/jwks_client.py: get_signing_keys requires
# jwk_set_key.key_id to be truthy) and matches a token's own `kid` header against it — a mismatch
# on either side means every request fails auth with "Unable to find a signing key that matches".
_KID = "loadtest-key-1"

_HERE = Path(__file__).parent


def main() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    private_key_path = _HERE / "private_key.pem"
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)  # kty/n/e only — kid/alg/use added below
    jwk.update(kid=_KID, alg="RS256", use="sig")
    jwks_dir = _HERE / "www" / "auth" / "v1" / ".well-known"
    jwks_dir.mkdir(parents=True, exist_ok=True)
    jwks_path = jwks_dir / "jwks.json"
    jwks_path.write_text(json.dumps({"keys": [jwk]}))

    print(f"Wrote {private_key_path} and {jwks_path} (kid={_KID})")


if __name__ == "__main__":
    main()
