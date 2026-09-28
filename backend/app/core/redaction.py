"""Strip database-echoed values out of exception text before it reaches a log line or Sentry.

`hide_parameters=True` (core/db.py) removes SQLAlchemy's own `[parameters: {...}]`, but Postgres
puts the offending data in ITS message too, and psycopg passes it through verbatim. Shapes captured
from a real Postgres 17 (tests/core/test_redaction_hostile.py provokes each one live, with hostile
values):

    invalid input syntax for type uuid: "<the value>"    <- echoed in the first line; may span lines
    DETAIL:  Key (name)=(<the value>) already exists.    <- unique / foreign-key violation
    DETAIL:  Failing row contains (5, null, <whole row>) <- NOT NULL / CHECK violation
    CONTEXT:  JSON data, line 1: <the value>...          <- may continue on later lines
    LINE 1: INSERT ... VALUES ('<the value>')            <- the statement with an inline literal
    [parameters: {'v': '<the value>'}]                   <- SQLAlchemy, if hide_parameters is off

For a CA-firm SaaS those values are client-confidential (names, task descriptions), and would
otherwise land in Railway's logs and in a third party (Sentry): Logging_Cheat_Sheet.md "Data to
exclude: commercially-sensitive information", TCASVS 3.2.3, ASVS 16.2.5. The SQL text, constraint
names, exception class and traceback frames are kept: the error stays debuggable, the data does not
travel.

How it is built, and why (2026-09-21, after an independent review found four leaks in the first
version):
  * Line based, one pass, no regex over attacker-controlled text except patterns anchored to a
    fixed literal with no nested quantifiers. The first version used `.*?` under DOTALL on the
    whole text, which was quadratic (16 KB took 17 s). ASVS 1.3.12;
    Input_Validation_Cheat_Sheet.md "not using any-character wildcards".
  * Input is cut to _MAX_INPUT before any work, so the cost is bounded whatever an attacker sends.
  * A value's end is found by STRUCTURE, never by a blank line (a client's text has paragraphs)
    and never by a line that merely looks like "Word: ..." or "  + item" (a client's text has
    those too). After a message the only genuine terminators are the ones Python and SQLAlchemy
    really emit there: a chain marker followed by a Traceback line, and SQLAlchemy's own last
    `[SQL: ...]` / `(Background on this error ...)` lines. A `Traceback` or a `File "..."` line
    never directly follows a message, so they are NOT terminators.
  * Lines are split on "\\n" only. str.splitlines() also splits on U+2028, U+0085, \\x0b..., which
    a hostile value could use to fake the start of a line that Python's own traceback treats as
    one line.
  * ExceptionGroup tracebacks put a rail ("  | ") in front of every line and draw separators
    ("  +-+---- 1 ----"); the rail is peeled off before a line is classified and put back on
    output. Whether the text IS such a traceback is decided by its FIRST line only (a value can
    never be the first line; a review forged the layout with two lines inside a value).
  * A message with no label and no class prefix (`time zone "<v>" not recognized`) is recognised by
    a list of Postgres message templates, and the leftmost echo opener wins. Boundary: the shapes
    this app can produce, not every Postgres message, and not translated ones.
  * Fails CLOSED (ASVS 16.5.3): if anything inside raises, the raw text is never returned.

KNOWN LIMIT (root cause D, recorded in docs/OBSERVABILITY.md): text alone cannot tell a client
value that reproduces a WHOLE genuine terminator (a chain marker, a blank line and a Traceback
line) from the real thing, so such a value can still end redaction early. The complete fix is to
render exceptions from the exception object instead of from text; not done in batch 1.

It only touches text that looks like a database error, so ordinary exception messages pass through
untouched.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

_MAX_INPUT: Final = 65_536
_WITHHELD: Final = "[exception text withheld: redaction failed]"

# A content rail of an ExceptionGroup traceback ("  | "), and the separators it draws. Both
# anchored, with one literal after a run of spaces or dashes: linear. A line like "  + item" is
# neither, so it stays ordinary text.
_RAIL: Final = re.compile(r" +\|(?: |$)")
_SEPARATOR: Final = re.compile(r" +\+(?:-\+)?-{8,}(?: \d+ -{8,})?")
# The class-qualified head of an exception line: "psycopg.errors.X: message".
_CLASS_HEAD: Final = re.compile(r"[A-Za-z_][\w.]*: ")

_PARAMETERS: Final = "[parameters:"
_LABELS: Final = ("DETAIL:  ", "CONTEXT:  ", "HINT:  ", "QUERY:  ")
# Message templates only Postgres prints. A bare message with no label and no class prefix, such
# as `time zone "<v>" not recognized` or `invalid input syntax for type uuid: "<v>"`, is
# recognised by these. Coverage boundary, stated: the shapes this app can produce (bound-parameter
# errors, constraint violations, PL/pgSQL EXECUTE); not every message Postgres has, and not
# translated (lc_messages) ones.
_PG_TEMPLATES: Final = (
    "invalid input syntax for type ",
    "invalid input value for enum ",
    "invalid value for parameter ",
    " is out of range for type ",
    "value too long for type ",
    'time zone "',
    "malformed array literal",
    "duplicate key value violates ",
    "null value in column ",
    " violates foreign key constraint ",
    " violates check constraint ",
    " violates not-null constraint ",
)
# What an echoed value follows on a message line: `: "<v>"`, `value "<v>"`, `time zone "<v>"`.
_ECHO_OPENERS: Final = (': "', 'value "', 'time zone "')
_SQLA_MARKERS: Final = ("[SQL: ", "[SQL parameters hidden", "(Background on this error at:")
_CHAIN: Final = (
    "The above exception was the direct cause of the following exception:",
    "During handling of the above exception, another exception occurred:",
)
_TRACEBACK_HEADS: Final = ("Traceback (most recent call last):", "+ Exception Group Traceback")

_Part = tuple[str, str, bool]  # (rail, content, is_separator)


class _Shape(NamedTuple):
    parts: list[_Part]
    sqlalchemy_format: bool
    group_format: bool
    last_marker: dict[str, int]


def _split_rail(line: str) -> _Part:
    """A rail is only ever peeled once: what follows it is the real line."""
    if _SEPARATOR.fullmatch(line):
        return line, "", True
    m = _RAIL.match(line)
    if m is None:
        return "", line, False
    return m.group(0), line[m.end() :], False


def _label_of(content: str) -> str | None:
    for label in _LABELS:
        if content.startswith(label):
            return label.rstrip()
    if content.startswith("LINE ") and content[5:].split(":", 1)[0].isdigit():
        return content.split(":", 1)[0] + ":"
    if content.startswith(_PARAMETERS):
        return _PARAMETERS
    return None


def _redacted_label(rail: str, label: str) -> str:
    return (
        f"{rail}[parameters: [redacted]]" if label == _PARAMETERS else f"{rail}{label}  [redacted]"
    )


def _message_start(content: str) -> int | None:
    """Where an exception's message begins if this line is the head of one; None otherwise."""
    m = _CLASS_HEAD.match(content)
    if m is not None:
        return m.end()
    if content.startswith(("(psycopg", "(sqlalchemy")):
        close = content.find(") ")
        return close + 2 if close != -1 else 0
    return None


def _scrub_head(content: str) -> str | None:
    """The line with an echoed value cut out, or None if the line echoes nothing.

    The value may run on over the next lines, so a scrubbed line always starts a skip.
    """
    head_at = _message_start(content)
    start = head_at if head_at is not None else 0
    # The LEFTMOST opener wins: a value that itself contains `: "` must not be able to move the cut
    # to the right of where its own first character sits.
    found = [(at, opener) for opener in _ECHO_OPENERS if (at := content.find(opener, start)) != -1]
    if not found:
        return None
    at, opener = min(found)
    return f'{content[: at + len(opener) - 1]}"[redacted]"'


def _looks_like_db_error(parts: list[_Part]) -> bool:
    return any(
        "psycopg" in c
        or "sqlalchemy" in c
        or _label_of(c) is not None
        or any(template in c for template in _PG_TEMPLATES)
        for _, c, _ in parts
    )


def _is_group_first_line(first: _Part) -> bool:
    """Python's own opening line of an ExceptionGroup traceback: the header of a raised group, or,
    for a group that was never raised (no traceback of its own), its railed `Name: msg (N
    sub-exceptions)` line. Only the FIRST line counts, so a client value can never be it."""
    rail, content, _ = first
    if not rail:
        return content.lstrip(" ").startswith("+ Exception Group Traceback")
    return "sub-exception" in content and content.endswith(")")


def _shape_of(text: str) -> _Shape:
    parts = [_split_rail(line) for line in text.split("\n")]
    contents = [c for _, c, _ in parts]
    return _Shape(
        parts,
        sqlalchemy_format=any(
            c.startswith(("(psycopg", "(sqlalchemy")) or "sqlalchemy.exc." in c for c in contents
        ),
        # A separator is only genuine in an ExceptionGroup traceback, and there EVERY message line
        # carries a rail, so a client value cannot reproduce a rail-less separator there. Whether
        # the text IS such a traceback is decided by its FIRST line, Python's own header: a value
        # can never be the first line, whereas a header found anywhere else could be the value's
        # (an independent review forged it with two lines). A group that follows a chain (its
        # first line is an ordinary traceback) is therefore not recognised: separators then do
        # not end a value, so redaction over-removes; it never under-removes.
        group_format=_is_group_first_line(parts[0]),
        last_marker={
            m: max((i for i, c in enumerate(contents) if c.startswith(m)), default=-1)
            for m in _SQLA_MARKERS
        },
    )


def _ends_value(shape: _Shape, i: int) -> bool:
    """Is line i a genuine terminator of a value that started earlier? Structure only."""
    _, content, separator = shape.parts[i]
    if separator:
        return shape.group_format
    for marker in _SQLA_MARKERS:
        if content.startswith(marker):
            # only SQLAlchemy emits these, and only the LAST one of its kind is the real one
            return shape.sqlalchemy_format and i == shape.last_marker[marker]
    if content.startswith(_CHAIN):
        follows = shape.parts[i + 1 : i + 3]
        return (
            len(follows) == 2
            and follows[0][1] == ""
            and follows[1][1].lstrip(" ").startswith(_TRACEBACK_HEADS)
        )
    return False


def _redact_db_error_text(text: str) -> str:
    shape = _shape_of(text)
    if not _looks_like_db_error(shape.parts):
        return text
    kept: list[str] = []
    skipping = False
    for i, (rail, content, _) in enumerate(shape.parts):
        label = _label_of(content)
        if label is not None:
            kept.append(_redacted_label(rail, label))
            skipping = True
            continue
        if skipping and not _ends_value(shape, i):
            continue  # still inside the value
        skipping = False
        # Any un-indented line may be the head of an error message that echoes a value: the bare
        # message of a psycopg error has no class prefix, and an application log line may put it
        # after other text.
        scrubbed = _scrub_head(content) if content != "" and not content.startswith(" ") else None
        if scrubbed is not None:
            kept.append(rail + scrubbed)
            skipping = True
            continue
        kept.append(rail + content)
    return "\n".join(kept)


def redact_db_values(text: str) -> str:
    """Remove database-echoed client values from exception text.

    Never raises, and never returns the raw text on failure.
    """
    try:
        return _redact_db_error_text(text[:_MAX_INPUT])
    except Exception:  # a non-str argument lands here too, and fails closed
        return _WITHHELD
