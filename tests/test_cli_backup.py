from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest
import yaml

from test_cli import init_install, run_cli


def prepared(tmp_path: Path) -> tuple[Path, Path]:
    config = init_install(tmp_path)
    code, sink = run_cli("demo", "seed", "--config", config)
    assert code == 0, sink.text
    secret = config.parent / "secrets" / "sample.token"
    secret.write_text("CANARY-BACKUP-SECRET\n", encoding="utf-8")
    secret.chmod(0o600)
    (config.parent / "run.env").write_text("VPN_PULSE_RUN_ARGS=--demo\n", encoding="utf-8")
    return config, Path(yaml.safe_load(config.read_text(encoding="utf-8"))["storage"]["database"])


def make_backup(config: Path, destination: Path, *extra: str) -> Path:
    code, sink = run_cli("backup", "--config", config, "--to", destination, *extra)
    assert code == 0, sink.text
    archives = list(destination.glob("vpn-pulse-backup-*.tar"))
    assert len(archives) == 1
    return archives[0]


def test_backup_contains_online_database_config_secrets_run_env_and_manifest(tmp_path):
    config, db = prepared(tmp_path)
    archive = make_backup(config, tmp_path / "backups")
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        assert {"MANIFEST.json", "config.yaml", "run.env", "data/vpnpulse.sqlite3", "secrets/sample.token"} <= names
        manifest = json.load(tar.extractfile("MANIFEST.json"))
    assert manifest["schema_version"] > 0 and manifest["app_version"] == "0.1.0"
    assert archive.stat().st_size > db.stat().st_size
    if os.name == "posix":
        assert archive.stat().st_mode & 0o777 == 0o600


def test_backup_json_and_keep_remove_oldest(tmp_path, monkeypatch):
    config, _ = prepared(tmp_path)
    destination = tmp_path / "backups"
    import vpnpulse.cli.backup as module
    moments = iter([__import__("datetime").datetime(2026, 1, 1, 0, 0, i // 2, tzinfo=__import__("datetime").UTC) for i in range(6)])
    class Clock:
        @classmethod
        def now(cls, tz=None): return next(moments)
    monkeypatch.setattr(module, "datetime", Clock)
    for _ in range(3):
        code, sink = run_cli("backup", "--config", config, "--to", destination, "--keep", "2", "--json")
        assert code == 0 and json.loads(sink.lines[0])["schema_version"] > 0
    assert len(list(destination.glob("*.tar"))) == 2


def test_restore_into_empty_directory_and_permissions(tmp_path):
    config, _ = prepared(tmp_path)
    archive = make_backup(config, tmp_path / "backups")
    target = tmp_path / "restored"
    code, sink = run_cli("restore", archive, "--config", config, "--into", target)
    assert code == 0 and "integrity_check: ok" in sink.text
    assert sqlite3.connect(target / "data/vpnpulse.sqlite3").execute("select count(*) from servers").fetchone()[0] == 3
    assert (target / "secrets/sample.token").read_text().strip() == "CANARY-BACKUP-SECRET"
    if os.name == "posix":
        assert (target / "secrets").stat().st_mode & 0o777 == 0o700
        assert (target / "secrets/sample.token").stat().st_mode & 0o777 == 0o600


def test_restore_into_nonempty_directory_refuses(tmp_path):
    config, _ = prepared(tmp_path)
    archive = make_backup(config, tmp_path / "backups")
    target = tmp_path / "restored"; target.mkdir(); (target / "keep").write_text("x")
    code, sink = run_cli("restore", archive, "--config", config, "--into", target)
    assert code == 2 and "not empty" in sink.text and (target / "keep").read_text() == "x"


def rewrite_archive(source: Path, destination: Path, mutate) -> None:
    with tarfile.open(source) as old, tarfile.open(destination, "w") as new:
        for member in old.getmembers():
            data = old.extractfile(member).read() if member.isfile() else None
            if data is not None:
                data = mutate(member.name, data)
                member.size = len(data)
                new.addfile(member, io.BytesIO(data))
            else:
                new.addfile(member)


def test_restore_refuses_checksum_mismatch(tmp_path):
    config, _ = prepared(tmp_path)
    archive = make_backup(config, tmp_path / "backups")
    corrupt = tmp_path / "corrupt.tar"
    rewrite_archive(archive, corrupt, lambda name, data: data + b"x" if name == "config.yaml" else data)
    code, sink = run_cli("restore", corrupt, "--config", config, "--dry-run")
    assert code == 2 and "checksum mismatch" in sink.text


def test_restore_refuses_newer_schema_and_dry_run_writes_nothing(tmp_path):
    config, _ = prepared(tmp_path)
    archive = make_backup(config, tmp_path / "backups")
    future = tmp_path / "future.tar"
    def mutate(name, data):
        if name == "MANIFEST.json":
            value = json.loads(data); value["schema_version"] = 999999; return json.dumps(value).encode()
        return data
    rewrite_archive(archive, future, mutate)
    code, sink = run_cli("restore", future, "--config", config, "--dry-run")
    assert code == 2 and "newer schema" in sink.text
    target = tmp_path / "never-created"
    code, sink = run_cli("restore", archive, "--config", config, "--into", target, "--dry-run")
    assert code == 0 and "nothing was restored" in sink.text and not target.exists()


def test_in_place_restore_requires_yes_and_makes_backups(tmp_path):
    config, db = prepared(tmp_path)
    archive = make_backup(config, tmp_path / "backups")
    original = sqlite3.connect(db).execute("select count(*) from servers").fetchone()[0]
    connection = sqlite3.connect(db); connection.execute("delete from servers"); connection.commit(); connection.close()
    assert run_cli("restore", archive, "--config", config)[0] == 2
    code, sink = run_cli("restore", archive, "--config", config, "--yes")
    assert code == 0 and "start the services" in sink.text
    assert sqlite3.connect(db).execute("select count(*) from servers").fetchone()[0] == original
    assert list(db.parent.glob(db.name + ".bak-*"))
