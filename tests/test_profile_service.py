from datetime import UTC, datetime
from pathlib import Path

import pytest

from vpnpulse.auth import Identity
from vpnpulse.profile_service import ProfileService, ProfileServiceError
from vpnpulse.storage import SqliteStore, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 22, tzinfo=UTC)
KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class FakeProvisioner:
    def __init__(self, failure=None): self.calls, self.failure = 0, failure
    def issue(self, **kwargs):
        self.calls += 1
        if self.failure: raise self.failure
        return {"address": kwargs["address"], "preshared_key": "one-time-value", "server_public_key": "public"}
    def revoke(self, **kwargs):
        self.calls += 1
        if self.failure: raise self.failure
        return {"ok": True}
    def inspect(self, **kwargs): return {"ok": True, "fingerprints": []}


def setup(tmp_path, provisioner):
    db = connect(tmp_path / "service.sqlite3"); apply_migrations(db, ROOT / "migrations")
    db.execute("INSERT INTO servers VALUES ('s1','s1','awg-host',1,1,?,?)", (NOW.isoformat(), NOW.isoformat()))
    config = {"access": {"member_registry_enabled": True, "grants_enabled": True, "issuance_enabled": True},
              "servers": [{"id": "s1", "access": {"issuance_enabled": True, "maintenance": False}}]}
    repo = SqliteStore(db, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json",
                       config=config, pepper="pepper", identity_key="identity", now=lambda: NOW)
    member = repo.record_membership(Identity(1, "member"), "active", source="admin_import", now=NOW)
    repo.grant_access(member, "s1", actor="owner", reason="test", now=NOW)
    return db, ProfileService(repo, config, {"servers": {"s1": {"addresses": ["fd00::100/128"]}}}, provisioner), member


def test_delivery_secret_is_returned_once_and_never_persisted(tmp_path):
    db, service, member = setup(tmp_path, FakeProvisioner())
    result = service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="one")
    assert result["delivery"]["preshared_key"] == "one-time-value"
    replay = service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="one")
    assert replay["delivery"] is None
    dump = " ".join(str(row) for table in ("vpn_profiles", "profile_operations") for row in db.execute(f"SELECT * FROM {table}").fetchall())
    assert "one-time-value" not in dump


def test_unknown_provisioner_result_blocks_retry_for_review(tmp_path):
    db, service, member = setup(tmp_path, FakeProvisioner(TimeoutError()))
    with pytest.raises(ProfileServiceError, match="provisioner_result_unknown"):
        service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="timeout")
    assert db.execute("SELECT state FROM vpn_profiles").fetchone()[0] == "needs_review"


def test_definite_issue_failure_quarantines_address(tmp_path):
    db, service, member = setup(tmp_path, FakeProvisioner(RuntimeError("rejected")))
    with pytest.raises(ProfileServiceError, match="provisioner_failed"):
        service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="failed")
    assert db.execute("SELECT state FROM vpn_profiles").fetchone()[0] == "failed"
    assert db.execute("SELECT state FROM address_leases").fetchone()[0] == "quarantine"


def test_revoke_is_idempotent_and_quarantines_address(tmp_path):
    db, service, member = setup(tmp_path, FakeProvisioner())
    issued = service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="issue")
    revoked = service.revoke(member_id=member, profile_id=issued["profile_id"], idempotency_key="revoke")
    assert revoked["profile_state"] == "revoked"
    replay = service.revoke(member_id=member, profile_id=issued["profile_id"], idempotency_key="revoke")
    assert replay["replayed"] is True
    assert db.execute("SELECT state FROM address_leases").fetchone()[0] == "quarantine"


def test_reconciliation_reports_missing_and_never_deletes_unmanaged(tmp_path):
    provisioner = FakeProvisioner(); db, service, member = setup(tmp_path, provisioner)
    service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="issue")
    report = service.reconcile(server_id="s1")
    assert report["ok"] is False and len(report["missing_managed"]) == 1
    assert db.execute("SELECT state FROM vpn_profiles").fetchone()[0] == "delivered"


def test_ban_schedules_and_processes_immediate_revoke(tmp_path):
    db, service, member = setup(tmp_path, FakeProvisioner())
    issued = service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="issue")
    service.store.record_membership(Identity(1, "member"), "banned", source="chat_member", now=NOW)
    result = service.process_lifecycle_jobs()
    assert result == {"processed": 1, "failed": 0}
    assert service.store.member_profiles(member)[0]["state"] == "revoked"
    assert issued["profile_id"]


def test_failed_lifecycle_job_uses_retry_backoff(tmp_path):
    provisioner = FakeProvisioner()
    db, service, member = setup(tmp_path, provisioner)
    service.issue(member_id=member, server_id="s1", public_key=KEY, idempotency_key="issue")
    service.store.record_membership(Identity(1, "member"), "banned", source="chat_member", now=NOW)
    provisioner.failure = RuntimeError("offline")
    assert service.process_lifecycle_jobs() == {"processed": 0, "failed": 1}
    assert service.store.due_lifecycle_jobs(now=NOW) == []
    row = db.execute("SELECT state,attempts,due_at FROM access_lifecycle_jobs").fetchone()
    assert row[0] == "failed" and row[1] == 1 and row[2] > NOW.isoformat()
