"""crud._generate_password must always satisfy Supabase's dashboard password policy (at least one
lowercase/uppercase/digit/symbol char) — plain secrets.token_urlsafe() only draws from
[A-Za-z0-9_-] and randomly failed this ~60% of the time (found via manual testing, 2026-09-16:
employee creation failed with AuthWeakPasswordError). Run many times since generation is random —
a regression back to an unconstrained generator would only fail this test probabilistically too,
but 500 runs makes that overwhelmingly likely to catch.
"""

import string

from app.crud import _generate_password  # pyright: ignore[reportPrivateUsage]


def test_generated_password_always_has_all_required_character_classes() -> None:
    symbols = "!@#$%^&*()-_=+"
    for _ in range(500):
        password = _generate_password()
        assert any(c in string.ascii_lowercase for c in password)
        assert any(c in string.ascii_uppercase for c in password)
        assert any(c in string.digits for c in password)
        assert any(c in symbols for c in password)
