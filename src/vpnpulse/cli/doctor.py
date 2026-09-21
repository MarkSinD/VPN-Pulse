"""`vpn-pulse doctor [section]` — one next step per warning, the same texts the Admin screen shows.

The data-derived checks (servers, probes, collector, queue) come from `SqliteReadModel.admin_overview`,
so the terminal and the Mini App never disagree; the local checks (storage, telegram) look at the
files the Mini App cannot see. Exit code: 0 ok, 1 warnings, 2 failures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, UTC
from pathlib import Path
import socket
import ssl
from urllib.parse import urlparse

from vpnpulse.cli.common import CliError, Output, config_path_of, lang_of, load_public_config, make_read_model, open_database, resolve_db, secret_file_status
from vpnpulse.i18n import Translator

SECTIONS = ("servers", "probes", "collector", "queue", "storage", "telegram", "https", "collectors")
EXIT = {"ok": 0, "warn": 1, "fail": 2}


def add_parser(commands, parents) -> None:
    p = commands.add_parser("doctor", parents=parents, help="check the installation and print one next step per warning")
    p.add_argument("section", nargs="?", choices=SECTIONS, help="only this check, with details")
    p.add_argument("--json", action="store_true", help="machine-readable result (the Admin screen's doctor shape plus local checks)")
    p.set_defaults(handler=command_doctor)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _age(value: str | None, now: datetime) -> str:
    at = _dt(value)
    if at is None:
        return "never"
    minutes = int((now - at).total_seconds() // 60)
    return f"{minutes} min ago" if minutes < 120 else f"{minutes // 60} h ago"


def collectors_checks(config: dict, config_path: Path | None, i18n: Translator, lang: str) -> list[dict]:
    """The collectors map: servers without a helper (probes only), keys and pinned host keys that are not in place."""
    from vpnpulse.cli.run import collectors_map_path
    from vpnpulse.collectors import load_collectors_map, unreferenced
    from vpnpulse.config import ConfigurationError

    servers = [s for s in config.get("servers", []) if s.get("enabled", True)]
    if not servers:
        return []
    path = collectors_map_path(config, config_path)
    if path is None or not path.exists():
        # information, not a warning: probes are evidence on their own and a demo has no servers to read
        first = servers[0]["id"]
        return [{"check": "collectors", "state": "ok", "next": i18n.t(lang, "doctor.collectors.none"), "command": f"vpn-pulse collector keygen {first} --host <server>"}]
    try:
        collectors_map = load_collectors_map(path)
    except ConfigurationError:
        return [{"check": "collectors", "state": "fail", "next": i18n.t(lang, "doctor.collectors.invalid"), "command": "vpn-pulse collector list"}]
    items: list[dict] = []
    without, _ = unreferenced(config, collectors_map)
    if without:
        items.append({"check": "collectors", "state": "warn", "next": i18n.t(lang, "doctor.collectors.missing", servers=", ".join(without)), "command": f"vpn-pulse collector keygen {without[0]} --host <server>"})
    for ref, entry in (collectors_map.get("collectors") or {}).items():
        if not entry.get("enabled", True):
            continue
        server_id = next((s["id"] for s in servers if s.get("collector_ref") == ref), None)
        if server_id is None:
            continue
        if secret_file_status(path.parent / entry["key_file"]) != "ok":
            items.append({"check": "collectors", "state": "fail", "next": i18n.t(lang, "doctor.collectors.key", collector=ref), "command": f"vpn-pulse collector keygen {server_id} --host <server> --force"})
        elif secret_file_status(path.parent / entry["known_hosts_file"]) != "ok":
            items.append({"check": "collectors", "state": "warn", "next": i18n.t(lang, "doctor.collectors.pin", collector=ref), "command": f"vpn-pulse collector pin {server_id}"})
    return items


def https_check(config: dict, i18n: Translator, lang: str, now: datetime | None = None) -> tuple[dict | None, list[str]]:
    """Resolve and validate the configured HTTPS endpoint without sending application data."""
    public_url = (config.get("app") or {}).get("public_url")
    if not public_url:
        return None, [i18n.t(lang, "doctor.https.missing")]
    parsed = urlparse(public_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ({"check": "https", "state": "fail", "next": i18n.t(lang, "doctor.https.invalid"),
                 "command": "vpn-pulse doctor https"}, ["app.public_url must be an https URL"])
    host = parsed.hostname
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError:
        return ({"check": "https", "state": "fail", "next": i18n.t(lang, "doctor.https.dns"),
                 "command": "vpn-pulse doctor https"}, [f"DNS: {host} does not resolve"])
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                certificate = tls.getpeercert()
    except (OSError, ssl.SSLError):
        return ({"check": "https", "state": "fail", "next": i18n.t(lang, "doctor.https.tls"),
                 "command": "vpn-pulse doctor https"}, [f"DNS: {host} resolves ({len(addresses)} address(es))", "TLS certificate validation failed"])
    expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(certificate["notAfter"]), UTC)
    days = int((expiry - (now or datetime.now(UTC))).total_seconds() // 86400)
    details = [f"DNS: {host} resolves ({len(addresses)} address(es))", f"TLS: hostname valid; certificate expires in {days} days"]
    if days < 0:
        return ({"check": "https", "state": "fail", "next": i18n.t(lang, "doctor.https.expired"), "command": "vpn-pulse doctor https"}, details)
    if days < 14:
        return ({"check": "https", "state": "warn", "next": i18n.t(lang, "doctor.https.expiring", days=days), "command": "vpn-pulse doctor https"}, details)
    return None, details


def local_checks(config: dict, db_path: Path, i18n: Translator, lang: str, config_path: Path | None = None) -> tuple[list[dict], object]:
    """storage, telegram and collectors items; returns (items, connection or None)."""
    items: list[dict] = []
    connection = None
    if not db_path.exists():
        items.append({"check": "storage", "state": "fail", "next": i18n.t(lang, "doctor.storage.missing"), "command": "vpn-pulse init"})
    else:
        try:
            connection = open_database(db_path)
            connection.execute("SELECT count(*) FROM servers").fetchone()
        except Exception:  # noqa: BLE001 - any failure to open is the finding itself
            connection = None
            items.append({"check": "storage", "state": "fail", "next": i18n.t(lang, "doctor.storage.broken"), "command": "vpn-pulse doctor storage"})
    telegram = config.get("telegram") or {}
    if not telegram:
        # information, not a warning: an installation without Telegram is whole (messages go to the console)
        items.append({"check": "telegram", "state": "ok", "next": i18n.t(lang, "doctor.telegram.missing"), "command": "vpn-pulse doctor telegram"})
    else:
        status = secret_file_status(Path(telegram["bot_token_file"]))
        if status in ("missing", "empty"):
            items.append({"check": "telegram", "state": "fail", "next": i18n.t(lang, "doctor.telegram.tokenMissing"), "command": "vpn-pulse doctor telegram"})
        elif status == "permissions":
            items.append({"check": "telegram", "state": "warn", "next": i18n.t(lang, "doctor.telegram.permissions"), "command": f"chmod 600 {telegram['bot_token_file']}"})
    https_item, _ = https_check(config, i18n, lang)
    if https_item:
        items.append(https_item)
    items.extend(collectors_checks(config, config_path, i18n, lang))
    return items, connection


def run_doctor(config: dict, db_path: Path, lang: str, config_path: Path | None = None) -> tuple[dict, object]:
    i18n = Translator()
    local, connection = local_checks(config, db_path, i18n, lang, config_path)
    items: list[dict] = []
    if connection is not None:
        items.extend(make_read_model(connection, config, translator=i18n).admin_overview(lang)["doctor"]["items"])
    items.extend(local)
    items.sort(key=lambda i: {"fail": 0, "warn": 1}.get(i["state"], 2))  # failures, warnings, information; the Admin screen's order within
    result = "fail" if any(i["state"] == "fail" for i in items) else "warn" if any(i["state"] == "warn" for i in items) else "ok"
    findings = [i for i in items if i["state"] != "ok"]
    return {"result": result, "items": items, "next_command": findings[0]["command"] if findings else None}, connection


def command_doctor(args: argparse.Namespace, out: Output) -> int:
    config_path = config_path_of(args)
    config = load_public_config(config_path)
    lang = lang_of(args, config)
    db_path = resolve_db(args, config)
    summary, connection = run_doctor(config, db_path, lang, config_path)
    if args.section:
        summary["items"] = [i for i in summary["items"] if i["check"] == args.section]
        summary["result"] = "fail" if any(i["state"] == "fail" for i in summary["items"]) else "warn" if any(i["state"] == "warn" for i in summary["items"]) else "ok"
        findings = [i for i in summary["items"] if i["state"] != "ok"]
        summary["next_command"] = findings[0]["command"] if findings else None
        summary["details"] = section_details(args.section, config, db_path, connection, config_path, lang)
    if args.json:
        out.json(summary)
        return EXIT[summary["result"]]
    label = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    out.line(f"doctor: {label[summary['result']]}" + (f" ({args.section})" if args.section else ""))
    for item in summary["items"]:
        line = f"  [{label[item['state']]}] {item['check']}: {item['next']}"
        if item.get("command"):
            line += f"  →  {item['command']}"
        out.line(line)
    if args.section:
        for line in summary["details"]:
            out.line(f"  {line}")
    if not any(i["state"] != "ok" for i in summary["items"]) and not args.section:
        out.line("  every check passed")
    return EXIT[summary["result"]]


def collectors_details(config: dict, config_path: Path | None, connection) -> list[str]:
    """Map entries with the server each serves and the last collection per server — never a host."""
    from vpnpulse.cli.run import collectors_map_path
    from vpnpulse.collectors import load_collectors_map, unreferenced
    from vpnpulse.config import ConfigurationError

    path = collectors_map_path(config, config_path)
    if path is None:
        return ["no collectors map configured (storage.collectors_file): servers are read through probes only"]
    if not path.exists():
        return [f"collectors map not found: {path.name} — vpn-pulse collector keygen <server> --host <server>"]
    try:
        collectors_map = load_collectors_map(path)
    except ConfigurationError as error:
        return [str(error)]
    servers = {s.get("collector_ref"): s["id"] for s in config.get("servers", []) if s.get("enabled", True)}
    lines = []
    for ref, entry in (collectors_map.get("collectors") or {}).items():
        state = "disabled" if not entry.get("enabled", True) else "ok" if all(secret_file_status(path.parent / entry[k]) == "ok" for k in ("key_file", "known_hosts_file")) else "key or host key missing"
        last = ""
        if connection is not None and ref in servers:
            row = connection.execute(
                "SELECT observed_at, result, error_code FROM observations WHERE server_id = ? AND source_kind = 'collector' ORDER BY observed_at DESC LIMIT 1", (servers[ref],)
            ).fetchone()
            last = f", last collection {row[1]} {_age(row[0], datetime.now(UTC))}" + (f" ({row[2]})" if row[2] else "") if row else ", no collection yet"
        lines.append(f"{ref}: {entry.get('kind', '?')} → {servers.get(ref, 'no server refers to it')} [{state}]{last}")
    without, _ = unreferenced(config, collectors_map)
    if without:
        lines.append("servers without a helper (probes only): " + ", ".join(without))
    return lines or ["the map has no entries"]


def section_details(section: str, config: dict, db_path: Path, connection, config_path: Path | None = None, lang: str = "en") -> list[str]:
    now = datetime.now(UTC)
    if section == "collectors":
        return collectors_details(config, config_path, connection)
    if section == "storage":
        lines = [f"database: {db_path}"]
        if db_path.exists():
            lines.append(f"size: {db_path.stat().st_size // 1024} KiB")
        if connection is not None:
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            counts = {t: connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("observations", "events", "probes", "notification_queue")}
            lines.append(f"schema version: {version}; " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return lines
    if section == "telegram":
        telegram = config.get("telegram") or {}
        if not telegram:
            return ["not configured: messages are printed by vpn-pulse run; add telegram.bot_token_file and telegram.group_chat_id to config.yaml"]
        return [
            f"token file: {telegram['bot_token_file']} — {secret_file_status(Path(telegram['bot_token_file']))}",
            f"group chat: {telegram['group_chat_id']}; admin chat: {telegram.get('admin_chat_id', 'same as the group')}",
        ]
    if section == "https":
        return https_check(config, Translator(), lang, now)[1]
    if connection is None:
        return ["database unavailable"]
    if section == "servers":
        cards = make_read_model(connection, config).status("admin")["servers"]
        if not cards:
            return ["no servers configured"]
        return [f"{c['id']}: {c['state']}{' (stale)' if c['freshness']['is_stale'] else ''}, observed {_age(c['freshness']['observed_at'], now)}" for c in cards]
    if section == "probes":
        probes = make_read_model(connection, config).admin_probes()
        if not probes:
            return ["no probes enrolled"]
        return [f"{p['id']}: {p['kind']} {p['status']}, last report {_age(p['last_seen_at'], now)}" for p in probes]
    if section == "collector":
        row = connection.execute("SELECT started_at, finished_at, result, error_code FROM collection_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if row is None:
            return ["no collection run yet — is vpn-pulse run running?"]
        runs = connection.execute("SELECT count(*) FROM collection_runs WHERE started_at >= ?", ((now.replace(hour=0, minute=0, second=0, microsecond=0)).isoformat().replace("+00:00", "Z"),)).fetchone()[0]
        return [f"last run: {row[2] or 'running'} {_age(row[1] or row[0], now)}" + (f" ({row[3]})" if row[3] else ""), f"runs today: {runs}"]
    if section == "queue":
        pending = connection.execute("SELECT count(*), MIN(created_at) FROM notification_queue WHERE state = 'pending'").fetchone()
        failed = connection.execute("SELECT count(*) FROM notification_queue WHERE state = 'failed'").fetchone()[0]
        sent = connection.execute("SELECT count(*) FROM notification_queue WHERE state = 'sent'").fetchone()[0]
        lines = [f"pending: {pending[0]}" + (f" (oldest {_age(pending[1], now)})" if pending[1] else ""), f"sent: {sent}, failed: {failed}"]
        return lines
    raise CliError(f"unknown section {section}")
