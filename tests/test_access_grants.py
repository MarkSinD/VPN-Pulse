from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vpnpulse.auth import Identity
from vpnpulse.storage import SqliteStore, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 22, tzinfo=UTC)


def setup(tmp_path):
    db = connect(tmp_path / "grants.sqlite3")
    apply_migrations(db, ROOT / "migrations")
    db.execute("INSERT INTO servers VALUES ('s1','s1','awg-host',1,1,?,?)", (NOW.isoformat(), NOW.isoformat()))
    repo = SqliteStore(db, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json",
                       config={"access": {"member_registry_enabled": True}}, pepper="pepper",
                       identity_key="identity-key", now=lambda: NOW)
    member_id = repo.record_membership(Identity(42, "member"), "active", source="admin_import", now=NOW)
    return db, repo, member_id


def test_access_request_and_grant_are_idempotent(tmp_path):
    db, repo, member_id = setup(tmp_path)
    assert repo.request_access(member_id) == repo.request_access(member_id)
    first = repo.grant_access(member_id, "s1", actor="owner", reason="recommended")
    assert repo.grant_access(member_id, "s1", actor="owner", reason="again")["id"] == first["id"]
    assert db.execute("SELECT state FROM access_requests").fetchone()[0] == "approved"


def test_grant_suspend_resume_revoke_and_expiry(tmp_path):
    _, repo, member_id = setup(tmp_path)
    grant = repo.grant_access(member_id, "s1", actor="owner", reason="temporary", valid_until=NOW + timedelta(hours=1))
    assert repo.set_grant_state(grant["id"], "suspended")
    assert repo.set_grant_state(grant["id"], "active")
    assert repo.member_access(member_id, NOW + timedelta(hours=2))[0]["state"] == "expired"
    with pytest.raises(ValueError):
        repo.grant_access(member_id, "s1", actor="owner", reason="old", valid_until=NOW)


def test_coverage_contains_no_personal_data(tmp_path):
    _, repo, member_id = setup(tmp_path)
    assert member_id and repo.member_coverage() == {"known": 1, "active": 1, "left": 0, "banned": 0, "unknown": 0}
