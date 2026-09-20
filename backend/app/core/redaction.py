"""Strip database-echoed values out of exception text before it reaches a log line or Sentry.

`hide_parameters=True` (core/db.py) removes SQLAlchemy's own `[parameters: {...}]`, but Postgres
puts the offending data in ITS message too, and psycopg passes it through verbatim. Shapes captured
from a real Postgres 17 (tests/core/test_redaction.py exercises each one live):

    invalid input syntax for type uuid: "<the value>"          <- value echoed in the first line
    DETAIL:  Key (name)=(<the value>) already exists.          <- unique violation
    DETAIL:  Failing row contains (5, null, <whole row>).      <- NOT NULL / CHECK violation
    CONTEXT:  JSON data, line 1: <the value>...                <- may continue on later lines

For a CA-firm SaaS those values are client-confidential (names, task descriptions), and they would
otherwise land in Railway's logs and in a third party (Sentry) — Logging_Cheat_Sheet.md "Data to
exclude: commercially-sensitive information", TCASVS 3.2.3, ASVS 16.2.5. The SQL text, constraint
names, error class and traceback are kept: the error stays debuggable, the data does not travel.

Best effort by nature (it recognises Postgres's message shapes), which is why it is a second layer
behind not putting data in the message at all; it only touches text that looks like a database
error, so ordinary exception messages pass through untouched.
"""

import re

_DIAG_LINE = re.compile(r"^(DETAIL|CONTEXT):  ")
# A DETAIL/CONTEXT value can span lines (a multi-line description in a failing row). It ends at the
# next line that is structural rather than data.
_STRUCTURAL_LINE = re.compile(
    r"^(?:\[SQL|\(Background on|The above exception|During handling|Traceback)|^\s*File \""
)
_ECHOED_QUOTED_VALUE = re.compile(r': ".*?"(?=\n(?:DETAIL:|CONTEXT:|\[SQL)|\Z)', re.DOTALL)
_LOOKS_LIKE_DB_ERROR = re.compile(r"psycopg|^(?:DETAIL|CONTEXT):  ", re.MULTILINE)


def redact_db_values(text: str) -> str:
    if not _LOOKS_LIKE_DB_ERROR.search(text):
        return text
    text = _ECHOED_QUOTED_VALUE.sub(': "[redacted]"', text)
    kept: list[str] = []
    skipping = False
    for line in text.split("\n"):
        diag = _DIAG_LINE.match(line)
        if diag:
            kept.append(f"{diag.group(1)}:  [redacted]")
            skipping = True
        elif skipping and (line == "" or _STRUCTURAL_LINE.match(line)):
            skipping = False
            kept.append(line)
        elif not skipping:
            kept.append(line)
    return "\n".join(kept)
