"""Create and restore complete, integrity-checked VPN Pulse backups."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from vpnpulse import __version__
from vpnpulse.cli.common import CliError, Output, config_path_of, load_public_config, migrations_dir, resolve_db

DB_MEMBER = "data/vpnpulse.sqlite3"


def add_parsers(commands, parents) -> None:
    backup = commands.add_parser("backup", parents=parents, help="create a complete on-demand backup archive")
    backup.add_argument("--to", type=Path, default=None, help="archive directory (default: backups next to the database)")
    backup.add_argument("--keep", type=int, default=5, help="number of newest archives to keep (default: 5)")
    backup.add_argument("--json", action="store_true")
    backup.set_defaults(handler=command_backup)
    restore = commands.add_parser("restore", parents=parents, help="verify and restore a backup archive")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--into", type=Path, default=None, help="restore into a new directory for a rehearsal")
    restore.add_argument("--yes", action="store_true", help="confirm an in-place restore")
    restore.add_argument("--dry-run", action="store_true", help="verify and describe without writing")
    restore.set_defaults(handler=command_restore)


def _known_schema_version() -> int:
    versions = [int(p.name.split("_", 1)[0]) for p in migrations_dir().glob("[0-9][0-9][0-9][0-9]_*.sql")]
    return max(versions, default=0)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _secret_roots(config: dict, config_path: Path) -> list[Path]:
    def relative_to_config(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else config_path.parent / path

    roots = {config_path.parent / "secrets"}
    storage = config.get("storage") or {}
    collectors = storage.get("collectors_file")
    if collectors:
        roots.add(relative_to_config(collectors).parent)
    token = (config.get("telegram") or {}).get("bot_token_file")
    if token:
        roots.add(relative_to_config(token).parent)
    existing = [p.resolve() for p in roots if p.exists() and p.is_dir()]
    if len(existing) > 1:
        raise CliError("secret files span multiple directories; place them together before backup")
    return existing


def command_backup(args: argparse.Namespace, out: Output) -> int:
    if args.keep < 1:
        raise CliError("--keep must be at least 1")
    config_path = config_path_of(args)
    config = load_public_config(config_path)
    assert config_path is not None
    db_path = resolve_db(args, config)
    if not db_path.exists():
        raise CliError(f"database not found: {db_path}")
    destination = args.to or db_path.parent / "backups"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = destination / f"vpn-pulse-backup-{stamp}.tar"
    if archive.exists():
        raise CliError(f"backup already exists: {archive}; wait one second and retry")
    with tempfile.TemporaryDirectory(prefix="vpn-pulse-backup-") as raw:
        stage = Path(raw)
        staged_db = stage / DB_MEMBER
        staged_db.parent.mkdir(parents=True)
        source = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(staged_db)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        shutil.copy2(config_path, stage / "config.yaml")
        roots = _secret_roots(config, config_path)
        if roots:
            shutil.copytree(roots[0], stage / "secrets")
        run_env = config_path.parent / "run.env"
        if run_env.is_file():
            shutil.copy2(run_env, stage / "run.env")
        files = []
        for path in sorted(p for p in stage.rglob("*") if p.is_file()):
            rel = path.relative_to(stage).as_posix()
            files.append({"path": rel, "sha256": _sha(path), "size": path.stat().st_size})
        check = sqlite3.connect(staged_db)
        try:
            row = check.execute("SELECT max(version) FROM schema_migrations").fetchone()
            schema_version = int(row[0] or 0)
        finally:
            check.close()
        manifest = {"created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "app_version": __version__, "schema_version": schema_version, "files": files}
        (stage / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with tarfile.open(archive, "w") as tar:
            for path in sorted(stage.rglob("*")):
                tar.add(path, arcname=path.relative_to(stage).as_posix(), recursive=False)
    os.chmod(archive, 0o600)
    archives = sorted(destination.glob("vpn-pulse-backup-*.tar"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in archives[args.keep:]:
        old.unlink()
        removed.append(str(old))
    payload = {"archive": str(archive), "size": archive.stat().st_size, "schema_version": schema_version, "copy_command": f"scp <host>:{archive} .", "removed": removed}
    if args.json:
        out.json(payload)
    else:
        out.line(f"backup: {archive}")
        out.line(f"size: {payload['size']} bytes; schema_version: {schema_version}")
        for old in removed:
            out.line(f"removed old backup: {old}")
        out.line(f"copy it off the host when needed: {payload['copy_command']}")
    return 0


def _verify_archive(archive: Path, target: Path) -> dict:
    if not archive.is_file():
        raise CliError(f"backup archive not found: {archive}")
    try:
        with tarfile.open(archive, "r") as tar:
            members = tar.getmembers()
            for member in members:
                path = Path(member.name)
                if member.issym() or member.islnk() or path.is_absolute() or ".." in path.parts:
                    raise CliError("backup contains an unsafe path or link")
            tar.extractall(target, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise CliError(f"backup archive cannot be read ({type(error).__name__})") from error
    manifest_path = target / "MANIFEST.json"
    if not manifest_path.is_file():
        raise CliError("backup has no MANIFEST.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise CliError("backup manifest is invalid") from error
    if int(manifest.get("schema_version", -1)) > _known_schema_version():
        raise CliError("backup is from a newer schema version — update the application first")
    expected = {item["path"]: item for item in manifest.get("files", []) if isinstance(item, dict) and "path" in item}
    if not expected or DB_MEMBER not in expected or "config.yaml" not in expected:
        raise CliError("backup manifest is incomplete")
    actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file() and p.name != "MANIFEST.json"}
    if actual != set(expected):
        raise CliError("backup file list does not match its manifest")
    for rel, item in expected.items():
        path = target / rel
        if path.stat().st_size != item.get("size") or _sha(path) != item.get("sha256"):
            raise CliError(f"backup checksum mismatch: {rel}")
    return manifest


def _integrity(db: Path) -> None:
    connection = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if result != "ok":
        raise CliError(f"restored database integrity check failed: {result}")


def command_restore(args: argparse.Namespace, out: Output) -> int:
    config_path = config_path_of(args)
    config = load_public_config(config_path)
    assert config_path is not None
    with tempfile.TemporaryDirectory(prefix="vpn-pulse-restore-") as raw:
        stage = Path(raw)
        manifest = _verify_archive(args.archive, stage)
        _integrity(stage / DB_MEMBER)
        out.line(f"backup verified: schema_version {manifest['schema_version']}; integrity_check: ok")
        if args.dry_run:
            out.line("dry run: nothing was restored")
            return 0
        if args.into:
            if args.into.exists() and any(args.into.iterdir()):
                raise CliError(f"restore target is not empty: {args.into}")
            args.into.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / "config.yaml", args.into / "config.yaml")
            (args.into / "data").mkdir(mode=0o700)
            shutil.copy2(stage / DB_MEMBER, args.into / DB_MEMBER)
            if (stage / "secrets").exists():
                shutil.copytree(stage / "secrets", args.into / "secrets")
            if (stage / "run.env").exists():
                shutil.copy2(stage / "run.env", args.into / "run.env")
            _secure_layout(args.into)
            out.line(f"rehearsal restore: {args.into}; integrity_check: ok")
            return 0
        if not args.yes:
            raise CliError("in-place restore requires --yes; stop vpn-pulse-run vpn-pulse-api vpn-pulse-bot first")
        db_path = resolve_db(args, config)
        secrets_path = config_path.parent / "secrets"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        copies = [(stage / "config.yaml", config_path), (stage / DB_MEMBER, db_path)]
        if (stage / "run.env").exists():
            copies.append((stage / "run.env", config_path.parent / "run.env"))
        for source, destination in copies:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.copy2(destination, destination.with_name(destination.name + f".bak-{stamp}"))
            shutil.copy2(source, destination)
        if (stage / "secrets").exists():
            if secrets_path.exists():
                shutil.copytree(secrets_path, secrets_path.with_name(secrets_path.name + f".bak-{stamp}"))
                shutil.rmtree(secrets_path)
            shutil.copytree(stage / "secrets", secrets_path)
        _secure_layout(config_path.parent, explicit_db=db_path)
        _integrity(db_path)
        out.line(f"restored config, database and secrets; integrity_check: ok; backups end in .bak-{stamp}")
        out.line("start the services: systemctl start vpn-pulse-run vpn-pulse-api vpn-pulse-bot")
    return 0


def _secure_layout(base: Path, explicit_db: Path | None = None) -> None:
    for directory in (base / "data", base / "secrets"):
        if directory.exists():
            os.chmod(directory, 0o700)
    files = [base / "config.yaml", base / "run.env"]
    if explicit_db:
        files.append(explicit_db)
    else:
        files.append(base / DB_MEMBER)
    if (base / "secrets").exists():
        files.extend(p for p in (base / "secrets").rglob("*") if p.is_file())
    for path in files:
        if path.exists():
            os.chmod(path, 0o600)
