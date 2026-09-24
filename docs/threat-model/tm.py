"""pytm threat model for the CA-firm job allocation system.

Models the real architecture from docs/ARCHITECTURE.md section 2-4: the Tauri
desktop app never talks to Postgres directly, FastAPI is the sole data-plane
gateway and re-verifies every JWT itself, Postgres RLS is the tenant-isolation
backstop. Text findings only - no dfd()/seq() diagram output, since those need
graphviz/plantuml this project has no other use for.

Run: uv run --with pytm python docs/threat-model/tm.py --report docs/threat-model/report.md --describe-only
Or for the raw finding list: uv run --with pytm python docs/threat-model/tm.py --list
"""

from pytm import TM, Actor, Boundary, Classification, Controls, Data, Dataflow, Lifetime, Server, Datastore

tm = TM("CA-firm job allocation system")
tm.description = "Tauri desktop app -> FastAPI -> Supabase (Auth + Postgres/RLS), per docs/ARCHITECTURE.md"
tm.isOrdered = True

internet = Boundary("Internet")
firm_machine = Boundary("Firm's own machine")
supabase_managed = Boundary("Supabase (managed, third-party)")

owner = Actor("Owner (firm admin)")
owner.inBoundary = firm_machine
employee = Actor("Employee")
employee.inBoundary = firm_machine

tauri_app = Server("Tauri desktop app (React frontend)")
tauri_app.inBoundary = firm_machine
tauri_app.controls = Controls(usesSecureFunctions=True)  # Tauri secure storage for the JWT, per ARCHITECTURE.md §4 step 3

fastapi = Server("FastAPI backend")
fastapi.inBoundary = internet
fastapi.controls = Controls(
    isHardened=True,
    validatesInput=True,
    hasAccessControl=True,
    implementsPOLP=True,  # role-gate dependencies, ARCHITECTURE.md §11
)

supabase_auth = Server("Supabase Auth (JWKS + Custom Access Token Hook)")
supabase_auth.inBoundary = supabase_managed
supabase_auth.controls = Controls(usesMFA=False, implementsAuthenticationScheme=True)  # MFA explicitly deferred, ARCHITECTURE.md §4

postgres = Datastore("Supabase Postgres (RLS)")
postgres.inBoundary = supabase_managed
postgres.controls = Controls(isEncryptedAtRest=True, hasAccessControl=True)  # RLS tenant backstop, ARCHITECTURE.md §5

jwt_data = Data(
    "JWT (firm_id + role in app_metadata)",
    classification=Classification.SENSITIVE,
    isCredentials=True,
    credentialsLife=Lifetime.SHORT,  # 1 hour default token lifetime, ARCHITECTURE.md §4 "Resolved 2026-09-03"
)

business_data = Data(
    "Firm business data (tasks, employees, job types)",
    classification=Classification.SENSITIVE,
    isPII=True,  # employee names/emails
)

login_creds = Data("Login email + password", classification=Classification.SECRET, isCredentials=True)

df1 = Dataflow(tauri_app, supabase_auth, "1. Login credentials")
df1.protocol = "HTTPS"
df1.isEncrypted = True
df1.data = login_creds

df2 = Dataflow(supabase_auth, tauri_app, "2. JWT issued (app_metadata: firm_id, role, must_change_password)")
df2.protocol = "HTTPS"
df2.isEncrypted = True
df2.data = jwt_data

df3 = Dataflow(tauri_app, fastapi, "3. API request, Authorization: Bearer <JWT>")
df3.protocol = "HTTPS"
df3.isEncrypted = True
df3.authenticatesDestination = False  # no cert pinning noted anywhere in DEPLOYMENT.md - flag, not assume
df3.data = business_data

df4 = Dataflow(fastapi, supabase_auth, "4. Verify JWT signature via JWKS")
df4.protocol = "HTTPS"
df4.isEncrypted = True

df5 = Dataflow(fastapi, postgres, "5. SET LOCAL app.current_tenant; query")
df5.protocol = "Postgres wire protocol (via connection pool)"
df5.isEncrypted = True
df5.data = business_data

df3_resp = Dataflow(fastapi, tauri_app, "3r. API response")
df3_resp.protocol = "HTTPS"
df3_resp.isEncrypted = True
df3_resp.isResponse = True
df3_resp.responseTo = df3
df3_resp.data = business_data

tm.process()
