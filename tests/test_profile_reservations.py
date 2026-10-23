from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vpnpulse.auth import Identity
from vpnpulse.storage import SqliteStore, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 22, tzinfo=UTC)
KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
KEY2 = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA="


def prepare(path):
    db = connect(path)
    apply_migrations(db, ROOT / "migrations")
    db.execute("INSERT OR IGNORE INTO servers VALUES ('s1','s1','awg-host',1,1,?,?)", (NOW.isoformat(), NOW.isoformat()))
    repo = SqliteStore(db, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json",
                       config={"access": {"member_registry_enabled": True}}, pepper="pepper", identity_key="identity")
    member = repo.record_membership(Identity(1, "member"), "active", source="admin_import", now=NOW)
    repo.grant_access(member, "s1", actor="owner", reason="test", now=NOW)
    return db, repo, member


def test_twenty_parallel_retries_create_one_profile(tmp_path):
    path = tmp_path / "profiles.sqlite3"
    _, _, member = prepare(path)

    def reserve(index):
        db = connect(path)
        repo = SqliteStore(db, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json", pepper="pepper")
        try:
            return repo.reserve_profile(member, "s1", KEY, ["fd00::100/128", "fd00::101/128"],
                                        idempotency_key=f"attempt-{index}", now=NOW)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(reserve, range(20)))
    db = connect(path)
    assert db.execute("SELECT count(*) FROM vpn_profiles").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM address_leases").fetchone()[0] == 1
    assert len({item["profile_id"] for item in results}) == 1


def test_idempotency_key_replays_same_operation(tmp_path):
    _, repo, member = prepare(tmp_path / "retry.sqlite3")
    first = repo.reserve_profile(member, "s1", KEY, ["fd00::100/128"], idempotency_key="same", now=NOW)
    second = repo.reserve_profile(member, "s1", KEY, ["fd00::100/128"], idempotency_key="same", now=NOW)
    assert first["profile_id"] == second["profile_id"] and second["replayed"] is True
    repo.set_profile_operation(first["operation_id"], "applied", now=NOW)
    repo.set_profile_operation(first["operation_id"], "delivered", now=NOW)
    assert repo.mark_profile_connected(first["profile_id"], NOW, now=NOW)
    assert repo.release_profile(first["profile_id"], now=NOW, quarantine_hours=24)
    status = repo.profile_pool_status("s1", ["fd00::100/128"], now=NOW)
    assert status == {"total": 1, "free": 0, "used_or_quarantined": 1, "exhausted": True, "low": True}


def test_idempotency_key_cannot_cross_member_boundary(tmp_path):
    _, repo, first_member = prepare(tmp_path / "isolation.sqlite3")
    second_member = repo.record_membership(Identity(2, "other"), "active", source="admin_import", now=NOW)
    repo.grant_access(second_member, "s1", actor="owner", reason="test", now=NOW)
    reservation = repo.reserve_profile(first_member, "s1", KEY, ["fd00::100/128", "fd00::101/128"],
                                       idempotency_key="shared", now=NOW)
    with pytest.raises(ValueError, match="idempotency key conflict"):
        repo.reserve_profile(second_member, "s1", KEY2, ["fd00::100/128", "fd00::101/128"],
                             idempotency_key="shared", now=NOW)
    repo.set_profile_operation(reservation["operation_id"], "delivered", now=NOW)
    with pytest.raises(ValueError, match="idempotency key conflict"):
        repo.reserve_profile_revoke(second_member, reservation["profile_id"], idempotency_key="shared", now=NOW)
