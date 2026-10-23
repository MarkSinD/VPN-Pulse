from datetime import UTC, datetime
from pathlib import Path

from vpnpulse.auth import Identity
from vpnpulse.storage import SqliteStore, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 22, tzinfo=UTC)


def store(tmp_path, *, enabled=True):
    db = connect(tmp_path / "members.sqlite3")
    apply_migrations(db, ROOT / "migrations")
    config = {"access": {"member_registry_enabled": enabled}, "retention": {}}
    return db, SqliteStore(db, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json",
                           config=config, pepper="lookup-pepper", identity_key="separate-encryption-key",
                           now=lambda: NOW)


def test_session_binds_to_stable_member_and_encrypts_telegram_id(tmp_path):
    db, repo = store(tmp_path)
    first = repo.create_session(Identity(12345, "member", display_name="Ada User", username="ada"), NOW)
    second = repo.create_session(Identity(12345, "member", display_name="Ada Updated", username="ada"), NOW)
    assert first.identity.member_id == second.identity.member_id
    row = db.execute("SELECT telegram_id_ciphertext, display_name, telegram_user_hash FROM members").fetchone()
    assert b"12345" not in row[0] and row[1] == "Ada Updated"
    assert row[2] != __import__("hashlib").sha256(b"12345").digest()
    restored = repo.get_session(second.token, NOW)
    assert restored.identity.member_id == second.identity.member_id


def test_registry_disabled_keeps_existing_monitoring_session_behavior(tmp_path):
    db, repo = store(tmp_path, enabled=False)
    session = repo.create_session(Identity(12345, "member"), NOW)
    assert session.identity.member_id is None
    assert db.execute("SELECT count(*) FROM members").fetchone()[0] == 0


def test_registry_requires_separate_encryption_key(tmp_path):
    db = connect(tmp_path / "missing-key.sqlite3")
    apply_migrations(db, ROOT / "migrations")
    repo = SqliteStore(db, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json",
                       config={"access": {"member_registry_enabled": True}}, pepper="pepper")
    try:
        repo.create_session(Identity(1, "member"), NOW)
    except RuntimeError as error:
        assert "encryption key" in str(error)
    else:
        raise AssertionError("registry opened without an encryption key")


def test_chat_member_event_is_idempotent_and_offboarding_is_recorded(tmp_path):
    db, repo = store(tmp_path)
    identity = Identity(77, "member", display_name="Member")
    member_id = repo.record_membership(identity, "left", source="chat_member", external_event_id="update-1", now=NOW)
    assert repo.record_membership(identity, "left", source="chat_member", external_event_id="update-1", now=NOW) == member_id
    assert db.execute("SELECT membership_state FROM members WHERE id = ?", (member_id,)).fetchone()[0] == "left"
    assert db.execute("SELECT count(*) FROM membership_events WHERE external_event_id = 'update-1'").fetchone()[0] == 1


def test_identity_encryption_key_can_rotate_without_changing_member(tmp_path):
    db, repo = store(tmp_path)
    member_id = repo.record_membership(Identity(88, "member"), "active", source="admin_import", now=NOW)
    before = db.execute("SELECT telegram_id_ciphertext FROM members WHERE id = ?", (member_id,)).fetchone()[0]
    assert repo.rotate_identity_key("replacement-key") == 1
    after = db.execute("SELECT telegram_id_ciphertext FROM members WHERE id = ?", (member_id,)).fetchone()[0]
    assert before != after and repo.telegram_id_for_member(member_id) == 88
