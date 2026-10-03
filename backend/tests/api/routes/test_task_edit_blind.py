"""Blind, attack-minded tests for PATCH /tasks/{task_id} (owner edits a task before start).

Written from the written contract only. The implementation was never read. Every test tries to
break the contract; none of them weaken an assertion to make a missing feature pass. Expected to
FAIL until the endpoint, the task_edits table, and the reassign/submit paths exist.

Real Postgres is required (the race test and the same-transaction test cannot be proven on SQLite).
No skips: missing env vars or a missing table fail the test loudly.
"""

import os
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

# ---------------------------------------------------------------------------
# infrastructure helpers
# ---------------------------------------------------------------------------


def _admin() -> Engine:
    # superuser/migration connection: plants and reads fixture data, bypasses RLS by construction
    return create_engine(os.environ["TEST_MIGRATIONS_DATABASE_URL"])


def _client() -> Any:
    # imported lazily so each thread builds its own TestClient; raise_server_exceptions=False so a
    # 500 comes back as a response we can assert on instead of an exception that aborts the test
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


_PROFILE_META: dict[UUID, tuple[UUID, str]] = {}
_key_cache: Any = None


def _signing_key() -> Any:
    # Same RS256 pattern as tests/api/test_notifications_real_db.py: the app verifies tokens against
    # a JWKS, so the test patches the key lookup to a locally generated public key.
    from cryptography.hazmat.primitives.asymmetric import rsa

    global _key_cache
    if _key_cache is None:
        _key_cache = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _key_cache


@pytest.fixture(autouse=True)
def _mock_jwks(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    from app.core import security

    key = _signing_key()
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=key.public_key()),
    )


def _bearer(profile_id: UUID) -> dict[str, str]:
    import jwt

    from app.core import security

    firm_id, role = _PROFILE_META[profile_id]
    token = jwt.encode(
        {
            "sub": str(profile_id),
            "aud": "authenticated",
            "iss": security.settings.JWT_ISSUER,
            "exp": int(time.time()) + 3600,
            "app_metadata": {"firm_id": str(firm_id), "role": role},
        },
        _signing_key(),
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _insert_firm(conn: Any) -> UUID:
    firm_id = uuid4()
    conn.execute(
        text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
        {"id": firm_id},
    )
    return firm_id


def _insert_profile(conn: Any, firm_id: UUID, role: str, active: bool = True) -> UUID:
    # is_active (boolean) is the real deactivation flag; must_change_password=false so the
    # profile can perform writes (ActiveProfileDep refuses writes while the flag is still true)
    pid = uuid4()
    conn.execute(
        text(
            "INSERT INTO profiles "
            "(id, firm_id, role, full_name, email, is_active, must_change_password) "
            "VALUES (:id, :fid, :role, 'x', :email, :active, false)"
        ),
        {"id": pid, "fid": firm_id, "role": role, "email": f"{pid}@example.com", "active": active},
    )
    _PROFILE_META[pid] = (firm_id, role)
    return pid


def _insert_task(
    conn: Any,
    firm_id: UUID,
    owner_id: UUID,
    assignee_id: UUID,
    status: str,
    title: str = "Original",
    description: str = "Original desc",
) -> UUID:
    task_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO tasks (id, firm_id, title, description, assigned_to, status, created_by) "
            "VALUES (:id, :fid, :title, :desc, :assignee, :status, :owner)"
        ),
        {
            "id": task_id,
            "fid": firm_id,
            "title": title,
            "desc": description,
            "assignee": assignee_id,
            "status": status,
            "owner": owner_id,
        },
    )
    return task_id


def _plant(
    world: SimpleNamespace,
    status: str,
    assignee: UUID | None = None,
    title: str = "Original",
    description: str = "Original desc",
) -> UUID:
    with world.admin.begin() as conn:
        return _insert_task(
            conn,
            world.firm_a,
            world.owner_a,
            assignee or world.employee_a,
            status,
            title,
            description,
        )


def _row(admin: Engine, task_id: UUID) -> dict[str, Any]:
    # SELECT * on purpose: the full-row snapshot catches changes to any column, including ones the
    # contract says must be ignored (status, firm_id, task_type, created_by, id, parent_task_id)
    with admin.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM tasks WHERE id = :t"), {"t": task_id}).mappings().one()
        )


def _history(admin: Engine, task_id: UUID) -> list[dict[str, Any]]:
    with admin.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT * FROM task_edits WHERE task_id = :t ORDER BY created_at"),
                {"t": task_id},
            ).mappings()
        ]


def _notified(admin: Engine, task_id: UUID) -> set[UUID]:
    with admin.connect() as conn:
        rows = conn.execute(
            text("SELECT recipient_id FROM notifications WHERE task_id = :t"), {"t": task_id}
        ).scalars()
        return set(rows)


def _denial_count(admin: Engine, firm_id: UUID) -> int:
    # ASSUMPTION: an access-denials table keyed by firm_id exists (crud/test_access_denials.py
    # is the place that would name it; not read here per isolation rules)
    with admin.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM access_denials WHERE firm_id = :fid"), {"fid": firm_id}
        ).scalar_one()


def _wipe(admin: Engine, firm_ids: list[UUID]) -> None:
    with admin.begin() as conn:
        for fid in firm_ids:
            # Dependents first: every table holding an FK into tasks, issues, job_types or profiles.
            for stmt in (
                "DELETE FROM notifications WHERE firm_id = :fid",
                "DELETE FROM task_edits WHERE firm_id = :fid",
                "DELETE FROM task_reviews WHERE firm_id = :fid",
                "DELETE FROM issues WHERE firm_id = :fid",
                "DELETE FROM idempotency_keys WHERE firm_id = :fid",
                "DELETE FROM access_denials WHERE firm_id = :fid",
                "DELETE FROM audit_log WHERE firm_id = :fid",
                "DELETE FROM job_types WHERE firm_id = :fid",
            ):
                conn.execute(text(stmt), {"fid": fid})
            conn.execute(text("DELETE FROM tasks WHERE firm_id = :fid"), {"fid": fid})
            conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": fid})
            conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": fid})
    admin.dispose()


@pytest.fixture
def world() -> Iterator[SimpleNamespace]:
    admin = _admin()
    with admin.begin() as conn:
        firm_a = _insert_firm(conn)
        firm_b = _insert_firm(conn)
        owner_a = _insert_profile(conn, firm_a, "owner")
        employee_a = _insert_profile(conn, firm_a, "employee")
        employee_a2 = _insert_profile(conn, firm_a, "employee")
        inactive_a = _insert_profile(conn, firm_a, "employee", active=False)
        owner_b = _insert_profile(conn, firm_b, "owner")
        employee_b = _insert_profile(conn, firm_b, "employee")
    w = SimpleNamespace(
        admin=admin,
        firm_a=firm_a,
        firm_b=firm_b,
        owner_a=owner_a,
        employee_a=employee_a,
        employee_a2=employee_a2,
        inactive_a=inactive_a,
        owner_b=owner_b,
        employee_b=employee_b,
    )
    yield w
    _wipe(admin, [firm_a, firm_b])


# ---------------------------------------------------------------------------
# C1 employee cannot edit
# ---------------------------------------------------------------------------


def test_c1_employee_cannot_edit_title_and_denial_is_recorded(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)
    denials_before = _denial_count(world.admin, world.firm_a)

    r = _client().patch(
        f"/tasks/{task_id}", json={"title": "Hijacked"}, headers=_bearer(world.employee_a)
    )

    assert r.status_code == 403
    assert _row(world.admin, task_id) == before
    assert _history(world.admin, task_id) == []
    assert _denial_count(world.admin, world.firm_a) > denials_before


@pytest.mark.parametrize(
    "body_key, body_value",
    [("assigned_to", "employee_a2"), ("assigned_to", None)],
)
def test_c1_employee_reassign_is_403_not_422(
    world: SimpleNamespace, body_key: str, body_value: str | None
) -> None:
    # authz must run before validation: a 422 here would reveal the validator ran for a non-owner
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)
    value = str(getattr(world, body_value)) if body_value else None

    r = _client().patch(
        f"/tasks/{task_id}", json={body_key: value}, headers=_bearer(world.employee_a)
    )

    assert r.status_code == 403
    assert _row(world.admin, task_id) == before


# ---------------------------------------------------------------------------
# C2 other firm's owner / unknown id -> 404, indistinguishable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{"title": "pwned"}, {"assigned_to": "employee_b"}],
)
def test_c2_owner_of_other_firm_gets_404_and_no_change(
    world: SimpleNamespace, body: dict[str, str]
) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)
    real_body = {k: str(getattr(world, v)) if k == "assigned_to" else v for k, v in body.items()}

    r = _client().patch(f"/tasks/{task_id}", json=real_body, headers=_bearer(world.owner_b))

    # 404, not 422 for the assigned_to case: existence/tenancy is checked before validation
    assert r.status_code == 404
    assert _row(world.admin, task_id) == before
    assert _history(world.admin, task_id) == []


def test_c2_cross_firm_and_unknown_id_are_indistinguishable(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")
    client = _client()

    cross = client.patch(f"/tasks/{task_id}", json={"title": "x"}, headers=_bearer(world.owner_b))
    unknown_id = uuid4()
    unknown = client.patch(
        f"/tasks/{unknown_id}", json={"title": "x"}, headers=_bearer(world.owner_b)
    )

    assert cross.status_code == 404
    assert unknown.status_code == 404
    assert cross.status_code == unknown.status_code
    # RFC 9457 "instance" echoes the request path, i.e. the id the caller itself sent; it is not
    # an existence signal. Compare everything else, and check each echoes its own requested path.
    cross_body = cross.json()
    unknown_body = unknown.json()
    assert cross_body.pop("instance") == f"/tasks/{task_id}"
    assert unknown_body.pop("instance") == f"/tasks/{unknown_id}"
    assert cross_body == unknown_body


# ---------------------------------------------------------------------------
# C3 blocked statuses -> 409, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["in_progress", "submitted", "completed", "billed"])
def test_c3_blocked_status_returns_409_and_row_unchanged(
    world: SimpleNamespace, status: str
) -> None:
    task_id = _plant(world, status)
    before = _row(world.admin, task_id)

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"title": "Too late", "assigned_to": str(world.employee_a2)},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 409
    assert _row(world.admin, task_id) == before
    assert _history(world.admin, task_id) == []
    assert _notified(world.admin, task_id) == set()


# ---------------------------------------------------------------------------
# C4 allowed statuses succeed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["created", "assigned"])
def test_c4_allowed_status_edit_succeeds(world: SimpleNamespace, status: str) -> None:
    task_id = _plant(world, status)

    r = _client().patch(
        f"/tasks/{task_id}", json={"title": "Edited"}, headers=_bearer(world.owner_a)
    )

    assert r.status_code == 200
    assert r.json()["title"] == "Edited"
    assert _row(world.admin, task_id)["title"] == "Edited"


@pytest.mark.parametrize("status", ["created", "assigned"])
def test_c4_allowed_status_reassign_succeeds(world: SimpleNamespace, status: str) -> None:
    task_id = _plant(world, status)

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"assigned_to": str(world.employee_a2)},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 200
    assert _row(world.admin, task_id)["assigned_to"] == world.employee_a2


# ---------------------------------------------------------------------------
# C5 assigned_to null -> 422
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{"assigned_to": None}, {"title": "Also edited", "assigned_to": None}],
)
def test_c5_null_assignee_is_422_and_nothing_applied(
    world: SimpleNamespace, body: dict[str, Any]
) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)

    r = _client().patch(f"/tasks/{task_id}", json=body, headers=_bearer(world.owner_a))

    assert r.status_code == 422
    assert _row(world.admin, task_id) == before  # title in the same body must not be applied
    assert _history(world.admin, task_id) == []
    assert _notified(world.admin, task_id) == set()


# ---------------------------------------------------------------------------
# C6 invalid assignee -> 422, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    ["owner_a", "inactive_a", "employee_b", "owner_b", "unknown", "malformed"],
)
def test_c6_invalid_assignee_is_422_and_unchanged(world: SimpleNamespace, target: str) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)
    if target == "unknown":
        value: str = str(uuid4())
    elif target == "malformed":
        value = "not-a-uuid"
    else:
        value = str(getattr(world, target))

    r = _client().patch(
        f"/tasks/{task_id}", json={"assigned_to": value}, headers=_bearer(world.owner_a)
    )

    assert r.status_code == 422
    assert _row(world.admin, task_id) == before
    assert _history(world.admin, task_id) == []
    if target in ("inactive_a", "employee_b", "owner_b", "owner_a"):
        assert getattr(world, target) not in _notified(world.admin, task_id)


# ---------------------------------------------------------------------------
# C7 mass assignment ignored
# ---------------------------------------------------------------------------


def test_c7_mass_assignment_keys_are_ignored(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)
    ignored = {
        "status": "completed",
        "firm_id": str(world.firm_b),
        "task_type": "hacked",
        "created_by": str(world.employee_a),
        "id": str(uuid4()),
        "parent_task_id": str(uuid4()),
    }

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"title": "Edited", **ignored},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 200
    after = _row(world.admin, task_id)
    assert after["title"] == "Edited"
    for col in before:
        if col in ("title", "updated_at"):
            continue
        assert after[col] == before[col], f"ignored key changed column {col}"
    assert _history(world.admin, task_id)[0]["changed_fields"] == {
        "title": {"old": "Original", "new": "Edited"}
    }  # ignored keys must not appear in history either


def test_c7_body_with_only_ignored_keys_changes_nothing(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"status": "completed", "firm_id": str(world.firm_b)},
        headers=_bearer(world.owner_a),
    )

    # no editable field present: a 422 is acceptable, a 200 with no change is acceptable, 500 is not
    assert r.status_code in (200, 422)
    assert _row(world.admin, task_id) == before
    assert _history(world.admin, task_id) == []


# ---------------------------------------------------------------------------
# C8 empty title -> 422
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
def test_c8_empty_or_whitespace_title_is_422(world: SimpleNamespace, title: str) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)

    r = _client().patch(f"/tasks/{task_id}", json={"title": title}, headers=_bearer(world.owner_a))

    assert r.status_code == 422
    assert _row(world.admin, task_id) == before
    assert _history(world.admin, task_id) == []


# ---------------------------------------------------------------------------
# C9 history content
# ---------------------------------------------------------------------------


def test_c9_history_row_has_exact_old_new_actor_and_firm(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"title": "Edited", "description": "New desc"},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 200
    rows = _history(world.admin, task_id)
    assert len(rows) == 1
    assert rows[0]["firm_id"] == world.firm_a
    assert rows[0]["task_id"] == task_id
    assert rows[0]["edited_by"] == world.owner_a
    assert rows[0]["changed_fields"] == {
        "title": {"old": "Original", "new": "Edited"},
        "description": {"old": "Original desc", "new": "New desc"},
    }


def test_c9_history_records_only_fields_that_actually_changed(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")

    _client().patch(
        f"/tasks/{task_id}",
        json={"title": "Original", "description": "New desc"},  # title is identical
        headers=_bearer(world.owner_a),
    )

    rows = _history(world.admin, task_id)
    assert len(rows) == 1
    assert set(rows[0]["changed_fields"].keys()) == {"description"}


def test_c9_noop_request_writes_no_history_row(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")

    _client().patch(
        f"/tasks/{task_id}",
        json={"title": "Original", "description": "Original desc"},
        headers=_bearer(world.owner_a),
    )
    _client().patch(
        f"/tasks/{task_id}",
        json={"assigned_to": str(world.employee_a)},  # already the assignee
        headers=_bearer(world.owner_a),
    )

    assert _history(world.admin, task_id) == []


# ---------------------------------------------------------------------------
# C10 history row and change share one transaction
# ---------------------------------------------------------------------------


def test_c10_failed_history_insert_rolls_back_the_change(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned")
    before = _row(world.admin, task_id)
    fn = f"blind_fail_edit_{uuid4().hex}"
    trg = f"blind_trg_{uuid4().hex}"
    with world.admin.begin() as conn:
        conn.execute(
            text(
                f"CREATE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'blind: forced history failure'; END $$"
            )
        )
        conn.execute(
            text(
                f"CREATE TRIGGER {trg} BEFORE INSERT ON task_edits "
                f"FOR EACH ROW EXECUTE FUNCTION {fn}()"
            )
        )
    try:
        r = _client().patch(
            f"/tasks/{task_id}", json={"title": "Should not stick"}, headers=_bearer(world.owner_a)
        )
        assert r.status_code != 200
        assert _row(world.admin, task_id) == before
        assert _history(world.admin, task_id) == []
    finally:
        with world.admin.begin() as conn:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trg} ON task_edits"))
            conn.execute(text(f"DROP FUNCTION IF EXISTS {fn}()"))


# ---------------------------------------------------------------------------
# C11 repeat of the same request is not a second history row
# ---------------------------------------------------------------------------


def test_c11_repeated_identical_request_does_not_duplicate_history(
    world: SimpleNamespace,
) -> None:
    task_id = _plant(world, "assigned")
    client = _client()
    body = {"title": "Edited once"}

    first = client.patch(f"/tasks/{task_id}", json=body, headers=_bearer(world.owner_a))
    second = client.patch(f"/tasks/{task_id}", json=body, headers=_bearer(world.owner_a))

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(_history(world.admin, task_id)) == 1
    assert _row(world.admin, task_id)["title"] == "Edited once"


# ---------------------------------------------------------------------------
# C12 notifications on reassign: old and new assignee
# ---------------------------------------------------------------------------


def test_c12_reassign_notifies_both_old_and_new_assignee(world: SimpleNamespace) -> None:
    task_id = _plant(world, "assigned", assignee=world.employee_a)

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"assigned_to": str(world.employee_a2)},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 200
    recipients = _notified(world.admin, task_id)
    assert world.employee_a2 in recipients, "new assignee not notified"
    assert world.employee_a in recipients, "old assignee not notified"


# ---------------------------------------------------------------------------
# C13 race: reassign vs old assignee's submit
# ---------------------------------------------------------------------------


def test_c13_reassign_vs_old_assignee_submit_never_produces_forbidden_state(
    world: SimpleNamespace,
) -> None:
    # Submitter identity is proven by the submit response (200 only for the old assignee's own
    # request) plus assigned_to; no submitted_by column is assumed.
    rounds = 10
    for round_no in range(rounds):
        task_id = _plant(world, "assigned", assignee=world.employee_a)
        barrier = threading.Barrier(2)
        results: dict[str, int] = {}
        errors: list[BaseException] = []

        # Loop values are bound as default arguments so each round's threads see their own round.
        def owner_reassign(
            barrier: threading.Barrier = barrier,
            task_id: UUID = task_id,
            results: dict[str, int] = results,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                c = _client()
                barrier.wait(timeout=5)
                r = c.patch(
                    f"/tasks/{task_id}",
                    json={"assigned_to": str(world.employee_a2)},
                    headers=_bearer(world.owner_a),
                )
                results["patch"] = r.status_code
            except BaseException as exc:  # surfaced below, never swallowed
                errors.append(exc)

        def old_assignee_submit(
            barrier: threading.Barrier = barrier,
            task_id: UUID = task_id,
            results: dict[str, int] = results,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                c = _client()
                barrier.wait(timeout=5)
                # submit is an Idempotency-Key route (routes/tasks.py) -- the header is required
                r = c.post(
                    f"/tasks/{task_id}/submit",
                    headers={**_bearer(world.employee_a), "Idempotency-Key": str(uuid4())},
                )
                results["submit"] = r.status_code
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=owner_reassign),
            threading.Thread(target=old_assignee_submit),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert errors == [], f"round {round_no}: {errors!r}"
        assert len(results) == 2, f"round {round_no}: a request never completed: {results}"
        patch_code, submit_code = results["patch"], results["submit"]
        assert patch_code in (200, 409), f"round {round_no}: patch={patch_code}"
        # 404: once the reassign commits, the old assignee can no longer see the task at all
        # (get_task's own-assignments rule), so the route answers 404 (API_SPEC: not 403).
        # 409: submit reached the row after the reassign but before its own lock.
        # 403: the assignee check ran after the reassign. Only 200 is the forbidden commit.
        assert submit_code in (200, 403, 404, 409), f"round {round_no}: submit={submit_code}"

        patch_won = patch_code == 200
        submit_won = submit_code == 200
        # exactly one of the two allowed outcomes; both-succeed is the forbidden double-commit,
        # both-fail means a lost update
        assert patch_won != submit_won, f"round {round_no}: patch={patch_code} submit={submit_code}"

        row = _row(world.admin, task_id)
        if patch_won:
            # outcome (a): reassign first, old assignee refused, task stays with new assignee
            assert row["assigned_to"] == world.employee_a2, f"round {round_no}"
            assert row["status"] == "assigned", f"round {round_no}"
        else:
            # outcome (b): submit first, reassign refused, submitted by the old assignee
            assert row["status"] == "submitted", f"round {round_no}"
            assert row["assigned_to"] == world.employee_a, f"round {round_no}"


# ---------------------------------------------------------------------------
# C14 injection-style values stored as plain text, never a 500
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, payload",
    [
        ("title", "'); DROP TABLE tasks; --"),
        ("title", "<script>alert(document.cookie)</script>"),
        ("description", '{"$ne": null} \' OR 1=1 --'),
        ("title", "a\x00b"),  # NUL byte: Postgres text rejects it; must be 422, not 500
    ],
)
def test_c14_injection_style_values_are_plain_text_or_422(
    world: SimpleNamespace, field: str, payload: str
) -> None:
    task_id = _plant(world, "assigned")

    r = _client().patch(f"/tasks/{task_id}", json={field: payload}, headers=_bearer(world.owner_a))

    assert r.status_code in (200, 422), f"status {r.status_code}"
    if r.status_code == 200:
        assert r.json()[field] == payload
        assert _row(world.admin, task_id)[field] == payload
    with world.admin.connect() as conn:
        # tasks table still intact and queryable after the payload was sent
        assert conn.execute(text("SELECT count(*) FROM tasks")).scalar_one() >= 1
