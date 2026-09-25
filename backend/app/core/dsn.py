from urllib.parse import parse_qs

from pydantic import PostgresDsn

# A DB connection to one of these never leaves the host, so there is no network segment to
# intercept — local dev and CI's postgres service container both connect this way. Every other
# host is treated as remote and must prove TLS with full cert validation.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def require_tls_for_remote_hosts(v: PostgresDsn) -> PostgresDsn:
    """ASVS 5 §12.3.1 ("encrypted protocol for all ... database connections; no fallback to
    cleartext") + §12.3.2 ("TLS clients validate received certificates"). DEPLOYMENT.md §2 already
    mandates `sslmode=verify-full` on the Railway→Supabase leg; this makes it impossible to *boot*
    (or, for ops/db_check.py, to *run*) against a remote Postgres without it. `verify-full`
    specifically — `require`/`prefer` encrypt but skip cert validation, so they satisfy §12.3.1 but
    not §12.3.2. Loopback is the one exemption (see `LOOPBACK_HOSTS`).

    Checked against every host in the DSN, not just the first: a multi-host failover URL can connect
    to any of them, so a loopback-first/remote-second DSN must still be caught (found in code
    review, 2026-09-14 — the original version only inspected hosts()[0]).

    Extracted 2026-09-19 from config.py so the API and the ops tooling share ONE definition of the
    rule (code-review root cause A: a rule copied to a second call site drifts).
    """
    remote_hosts = [h["host"] for h in v.hosts() if h["host"] not in LOOPBACK_HOSTS]
    if not remote_hosts:
        return v
    if parse_qs(v.query or "").get("sslmode") != ["verify-full"]:
        raise ValueError(
            f"remote DB host(s) {remote_hosts!r} must use sslmode=verify-full "
            "(ASVS 12.3, DEPLOYMENT.md §2) — encrypt and validate the certificate"
        )
    return v
