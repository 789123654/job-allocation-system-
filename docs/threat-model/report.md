# pytm threat model — curated findings (2026-09-25)

Source: `docs/threat-model/tm.py`, modeling the real flow from `docs/ARCHITECTURE.md` §2-4
(Tauri app → FastAPI → Supabase Auth/Postgres). Regenerate the raw match list with:

```
uv run --with pytm python docs/threat-model/tm.py --json /tmp/findings.json
```

pytm's built-in threat library is generic (covers any web app), not aware of this project's
actual stack. Of 166 raw matches, most are noise for a Python/FastAPI + React/TS + Postgres app
with no file uploads, no SOAP/LDAP/XML, and no server-rendered HTML — listed at the bottom so
the noise is visible, not hidden. What's below is the filtered, relevant subset only.

## Already covered by the existing design

- **AA04 — Exploiting Trust in Client**: `ARCHITECTURE.md` §3 already states the frontend is
  never trusted for authorization decisions; FastAPI re-checks everything server-side.
- **AC17 — Session Hijacking (server-side)**: mitigated by independent JWT verification on every
  request, 1-hour token lifetime, and the live `is_active` re-check added 2026-09-03.
- **CR06 / DS06 / DR01 — channel manipulation, data leak, unprotected sensitive data**: every
  flow in the model is HTTPS, so this is covered as long as HTTPS is actually enforced in
  production (worth a final check once the real Railway deployment exists, `DEPLOYMENT.md` §13).
- **AC23 — Credentials Disclosure** on login: Supabase Auth owns password hashing/storage, not
  reimplemented here.

## Real open items — worth a look

- **CR03 — Dictionary-based Password Attack**: this is the same gap `ARCHITECTURE.md` §4 already
  flagged and left unresolved — Supabase's documented rate-limit table doesn't explicitly list
  plain email+password sign-in. pytm independently landing on the same gap is a second signal to
  actually check the Auth dashboard before launch, not a new finding.
- **SC02–SC05 (XSS variants)** on the Tauri/React frontend: React escapes by default; grepped
  `frontend/src` for `dangerouslySetInnerHTML` (2026-09-25) — zero matches, nothing opts out of
  React's escaping. Closed, not just assumed.
- **DE04 — Audit Log Manipulation** on Postgres: no audit/activity log for Owner actions
  (creating employees, editing tasks) is documented as existing yet — a real Phase 2+ candidate if
  the firm ever needs to answer "who changed this."
- **`df3` (API request) flagged `authenticatesDestination=False`**: the Tauri client has no TLS
  certificate pinning. Low priority at single-firm pilot scale on a trusted setup — worth
  remembering if the app is ever used over untrusted public networks.

## Not applicable — pytm's generic library, not this stack

SSI Injection, LDAP Injection, SOAP Array Overflow, XML Attribute Blowup, PHP Remote File
Inclusion, Format String Injection, Relative Path Traversal (no file uploads), HTTP Request
Smuggling (no reverse proxy in front of FastAPI yet). These matched because pytm's default
threat library fires on any generic Server/Process element, not because they're real risks here.
