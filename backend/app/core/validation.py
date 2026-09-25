"""Shared Pydantic field types for request input.

`NoNulStr` — every free-text/filter string field the client controls needs this, not just the
ones a NUL byte happened to reach first. A NUL byte (U+0000) is a valid Unicode codepoint, so
Pydantic's plain `str` never rejects it — but psycopg encodes every bound string parameter as a
C string, and Postgres's `text`/`varchar` columns reject NUL outright, regardless of whether the
value is used in an INSERT or a WHERE clause (the crash happens client-side, at parameter
encoding, before the query ever reaches the server). Found by Schemathesis fuzzing
`POST /job-types`'s `name` field, 2026-09-08 (docs/SECURITY_AUDIT_CHECKLIST.md) — applied here to
every other field with the same shape, not just the one that happened to crash first.

`OffsetQuery`/`LimitQuery` — every `list_*` route's pagination params, previously hand-copied at
4 call sites (code-review finding #10, 2026-09-14: the explanatory comment about Postgres's bigint
OFFSET overflow was copy-pasted correctly everywhere, but the bound itself had no single source of
truth). `le=1_000_000` on offset avoids a raw 500 from Postgres's bigint OFFSET overflow instead of
a clean 422 (found by Schemathesis, 2026-09-08, docs/SECURITY_AUDIT_CHECKLIST.md).
"""

from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator


def _reject_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("must not contain a NUL byte")
    return value


NoNulStr = Annotated[str, AfterValidator(_reject_nul)]

OffsetQuery = Annotated[int, Query(ge=0, le=1_000_000)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]
