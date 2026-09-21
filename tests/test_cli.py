"""`vpn-pulse` on the command line: init, run, doctor, server, probe, note — and no secret ever printed."""
import io
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from vpnpulse.cli import main
from vpnpulse.cli.common import Output
from vpnpulse.cli.doctor import https_check
from vpnpulse.i18n import Translator
from vpnpulse.config import load_config
from vpnpulse.dev.scenarios import FixtureReadModel, ScenarioCatalog
from vpnpulse.dev.seed import config_for, seed_scenario
from vpnpulse.storage import SqliteStore, apply_migrations, connect

ROOT = Path(__file__).parents[1]
CATALOG = ScenarioCatalog.load()
TOKEN = "123456789:AAExample-not-a-real-token-value"
ADMIN_CHECKS = ("servers", "probes", "collector", "queue")


class Sink(Output):
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.errors: list[str] = []
        super().__init__(out=self.lines.append, err=self.errors.append)

    @property
    def text(self) -> str:
        return "\n".join(self.lines + self.errors)


def run_cli(*argv) -> tuple[int, Sink]:
    sink = Sink()
    code = main([str(a) for a in argv], out=sink)
    return code, sink


def init_install(tmp_path, *extra) -> Path:
    code, sink = run_cli("init", "--dir", tmp_path / "inst", "--language", "ru", "--contact-url", "https://t.me/example_admin", *extra)
    assert code == 0, sink.text
    return tmp_path / "inst" / "config.yaml"


# ---------- run (from the previous increment, now on the config-aware CLI) ----------
def test_run_demo_once_writes_snapshots_and_prints_transitions(tmp_path):
    db = tmp_path / "demo.sqlite3"
    code, sink = run_cli("run", "--demo", "--once", "--db", db, "--quiet")
    assert code == 0
    assert any("s1: unknown → operational" in line for line in sink.lines) and any("s3: unknown → operational" in line for line in sink.lines)
    connection = connect(db)
    assert connection.execute("SELECT count(*) FROM state_snapshots WHERE state = 'operational'").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM probes WHERE kind IN ('pc', 'android', 'abroad')").fetchone()[0] == 3
    code, sink = run_cli("run", "--demo", "--once", "--db", db, "--quiet")
    assert code == 0 and sink.lines == []
    assert connection.execute("SELECT count(*) FROM state_transitions").fetchone()[0] == 3


def example_config(tmp_path, **overrides) -> Path:
    config = yaml.safe_load((ROOT / "contracts" / "config.example.yaml").read_text(encoding="utf-8"))
    config.pop("telegram", None)  # the example points at a token file that does not exist on a test machine
    config.pop("storage", None)
    config.update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_run_with_a_real_config_and_no_collectors_stays_silent(tmp_path):
    db = tmp_path / "live.sqlite3"
    code, sink = run_cli("run", "--config", example_config(tmp_path), "--once", "--db", db, "--quiet")
    assert code == 0 and sink.lines == [], sink.text
    connection = connect(db)
    assert [r[0] for r in connection.execute("SELECT id FROM servers ORDER BY display_order").fetchall()] == ["primary-vpn", "backup-vpn"]
    assert connection.execute("SELECT count(*) FROM state_snapshots WHERE state = 'unknown'").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM state_transitions").fetchone()[0] == 0


def test_run_refuses_a_configured_but_missing_token_file(tmp_path):
    cfg = example_config(tmp_path, telegram={"bot_token_file": str(tmp_path / "absent.token"), "group_chat_id": "-100"})
    code, sink = run_cli("run", "--config", cfg, "--once", "--db", tmp_path / "x.sqlite3", "--quiet")
    assert code == 2 and "token file" in sink.text and "missing" in sink.text


def test_run_requires_config_or_demo(tmp_path, monkeypatch):
    monkeypatch.delenv("VPN_PULSE_CONFIG", raising=False)
    code, sink = run_cli("run", "--once", "--db", tmp_path / "x.sqlite3", "--quiet")
    assert code == 2 and "--config" in sink.text


def test_run_takes_database_and_telegram_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN + "\n"))
    cfg = init_install(tmp_path, "--telegram-token-stdin", "--group-chat-id", "-1001234567890")
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    code, sink = run_cli("run", "--config", cfg, "--once", "--quiet")
    assert code == 0, sink.text
    assert Path(config["storage"]["database"]).exists()
    # a missing token file is a doctor-grade failure, not a silent fallback to the console
    Path(config["telegram"]["bot_token_file"]).unlink()
    code, sink = run_cli("run", "--config", cfg, "--once", "--quiet")
    assert code == 2 and "token file" in sink.text and TOKEN not in sink.text


# ---------- init ----------
def test_init_creates_the_layout_and_never_prints_the_token(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN + "\n"))
    code, sink = run_cli("init", "--dir", tmp_path / "inst", "--language", "en", "--timezone", "Europe/Riga",
                         "--telegram-token-stdin", "--group-chat-id", "-1001234567890", "--admin-chat-id", "42")
    assert code == 0, sink.text
    assert TOKEN not in sink.text and TOKEN[:12] not in sink.text
    cfg = tmp_path / "inst" / "config.yaml"
    config = load_config(cfg, ROOT / "contracts" / "config.schema.json")
    assert config["app"] == {"default_language": "en", "languages": ["en", "ru"], "timezone": "Europe/Riga"}
    assert config["servers"] == [] and config["telegram"]["group_chat_id"] == "-1001234567890" and config["telegram"]["admin_chat_id"] == "42"
    assert TOKEN not in cfg.read_text(encoding="utf-8")
    token_file = Path(config["telegram"]["bot_token_file"])
    assert token_file.read_text(encoding="utf-8").strip() == TOKEN
    if os.name == "posix":
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_file.parent.stat().st_mode) == 0o700
    db = Path(config["storage"]["database"])
    assert db.exists()
    assert connect(db).execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
    # a second init refuses to clobber the file unless told to
    code, sink = run_cli("init", "--dir", tmp_path / "inst")
    assert code == 2 and "--force" in sink.text
    code, sink = run_cli("init", "--dir", tmp_path / "inst", "--force")
    assert code == 0 and "telegram" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))


def test_init_needs_both_telegram_values_or_neither(tmp_path):
    code, sink = run_cli("init", "--dir", tmp_path / "a", "--group-chat-id", "-100")
    assert code == 2 and "both" in sink.text
    (tmp_path / "token.txt").write_text(TOKEN + "\n", encoding="utf-8")
    code, sink = run_cli("init", "--dir", tmp_path / "b", "--telegram-token-file", tmp_path / "token.txt")
    assert code == 2 and "both" in sink.text and TOKEN not in sink.text


def test_output_redacts_registered_secrets():
    sink = Sink()
    sink.secret(TOKEN)
    sink.line(f"token={TOKEN} ok")
    sink.error(f"failed with {TOKEN}")
    sink.json({"token": TOKEN})
    assert TOKEN not in sink.text and sink.text.count("[REDACTED]") == 3


# ---------- server ----------
def test_server_add_list_remove_round_trip(tmp_path, monkeypatch):
    cfg = init_install(tmp_path)
    monkeypatch.setenv("VPN_PULSE_CONFIG", str(cfg))
    code, sink = run_cli("server", "add", "--id", "nl-1", "--type", "awg-docker", "--name-ru", "Сервер NL", "--name-en", "Server NL", "--country", "nl", "--priority", "10", "--collector-ref", "collector-nl-1")
    assert code == 0, sink.text
    code, sink = run_cli("--config", cfg, "server", "add", "--id", "fi-1", "--type", "hiddify", "--name-ru", "Сервер FI", "--name-en", "Server FI", "--country", "FI", "--disabled")
    assert code == 0, sink.text
    config = load_config(cfg, ROOT / "contracts" / "config.schema.json")
    assert [s["id"] for s in config["servers"]] == ["nl-1", "fi-1"]
    assert config["servers"][0] == {"id": "nl-1", "type": "awg-docker", "name": {"ru": "Сервер NL", "en": "Server NL"}, "country_code": "NL", "enabled": True, "recommended_priority": 10, "collector_ref": "collector-nl-1"}
    assert config["servers"][1]["enabled"] is False

    code, sink = run_cli("server", "add", "--id", "nl-1", "--type", "awg-host", "--name-ru", "x", "--name-en", "x", "--country", "NL")
    assert code == 2 and "already" in sink.text
    code, sink = run_cli("server", "add", "--id", "vpn.example.org", "--type", "awg-host", "--name-ru", "x", "--name-en", "x", "--country", "NL")
    assert code == 2 and "hostname" in sink.text
    assert [s["id"] for s in yaml.safe_load(cfg.read_text(encoding="utf-8"))["servers"]] == ["nl-1", "fi-1"]

    code, sink = run_cli("server", "list", "--json")
    rows = json.loads(sink.text)
    assert [(r["id"], r["enabled"], r["state"]) for r in rows] == [("nl-1", True, "unknown"), ("fi-1", False, None)]
    code, sink = run_cli("server", "list", "--lang", "en")
    assert code == 0 and "nl-1" in sink.lines[0] and "Server NL" in sink.lines[0] and "no data yet" in sink.lines[0] and "disabled" in sink.lines[1]

    code, sink = run_cli("server", "remove", "missing", "--yes")
    assert code == 1
    code, sink = run_cli("server", "remove", "fi-1", "--yes")
    assert code == 0 and "VPN itself is untouched" in sink.text
    assert [s["id"] for s in load_config(cfg, ROOT / "contracts" / "config.schema.json")["servers"]] == ["nl-1"]


# ---------- probe ----------
def test_probe_enroll_code_is_single_use_and_never_audited(tmp_path, monkeypatch):
    cfg = init_install(tmp_path)
    monkeypatch.setenv("VPN_PULSE_CONFIG", str(cfg))
    code, sink = run_cli("probe", "enroll", "pc", "--minutes", "5")
    assert code == 0, sink.text
    printed = next(line.strip() for line in sink.lines if re.fullmatch(r"\s+[A-Za-z0-9_-]{20,}", line))
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    connection = connect(Path(config["storage"]["database"]))
    store = SqliteStore(connection, analytics_schema=ROOT / "contracts" / "analytics-events.schema.json", config=config)
    assert store.consume_enrollment(printed) == {"kind": "pc", "capabilities": ["report_pc"]}
    assert store.consume_enrollment(printed) is None
    audit = connection.execute("SELECT action, target_public_id, details_json FROM audit_entries").fetchall()
    assert [(a[0], a[1]) for a in audit] == [("probe.enroll_code", "pc")]
    assert printed not in json.dumps([tuple(a) for a in audit])
    assert printed not in connection.execute("SELECT hex(code_hash) FROM probe_enrollments").fetchone()[0]

    code, sink = run_cli("probe", "list")
    assert code == 0 and "no probes enrolled" in sink.text
    token, summary = store.register_probe("pc", ["report_pc"], "0.1")
    code, sink = run_cli("probe", "list", "--json")
    rows = json.loads(sink.text)
    assert [(r["id"], r["kind"], r["status"]) for r in rows] == [(summary["id"], "pc", "stale")]
    assert token not in sink.text
    code, sink = run_cli("probe", "revoke", summary["id"], "--yes")
    assert code == 0 and store.probe_by_token(token) is None
    code, sink = run_cli("probe", "revoke", "probe-nope", "--yes")
    assert code == 1
    code, sink = run_cli("probe", "enroll", "pc", "--minutes", "0")
    assert code == 2


# ---------- note ----------
def test_note_set_show_clear(tmp_path, monkeypatch):
    cfg = init_install(tmp_path)
    monkeypatch.setenv("VPN_PULSE_CONFIG", str(cfg))
    run_cli("server", "add", "--id", "nl-1", "--type", "awg-docker", "--name-ru", "Сервер", "--name-en", "Server", "--country", "NL")
    code, sink = run_cli("note", "show")
    assert code == 0 and "no note has ever been published" in sink.text
    code, sink = run_cli("note", "set", "Плановые работы", "--expires", "2099-01-01T12:00:00Z", "--server", "nl-1")
    assert code == 0 and "until 2099-01-01 12:00 UTC" in sink.text
    code, sink = run_cli("note", "show")
    assert sink.lines == ["Плановые работы [nl-1] (until 2099-01-01T12:00:00Z)"]
    code, sink = run_cli("note", "set", "x", "--server", "ghost")
    assert code == 2
    code, sink = run_cli("note", "set", "Готово", "--expires", "23:59")
    assert code == 0
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    connection = connect(Path(config["storage"]["database"]))
    assert connection.execute("SELECT count(*) FROM admin_notes WHERE status = 'active'").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM admin_notes WHERE status = 'replaced'").fetchone()[0] == 1
    code, sink = run_cli("note", "clear")
    assert code == 0 and "note cleared" in sink.text
    code, sink = run_cli("note", "show")
    assert "no active note" in sink.text
    assert [a[0] for a in connection.execute("SELECT action FROM audit_entries ORDER BY rowid").fetchall()] == ["note.put", "note.put", "note.delete"]


# ---------- doctor ----------
def seeded(tmp_path, scenario: str) -> tuple[Path, Path]:
    db = tmp_path / f"{scenario}.sqlite3"
    connection = connect(db)
    apply_migrations(connection, ROOT / "migrations")
    config = seed_scenario(connection, CATALOG, scenario, datetime.now(UTC), contact_url="https://t.me/example_admin")
    connection.close()
    cfg = tmp_path / f"{scenario}.yaml"
    cfg.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cfg, db


@pytest.mark.parametrize("scenario", ["clean_install", "unknown", "operational", "degraded", "no_pc"])
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_doctor_says_what_the_admin_screen_says(tmp_path, scenario, lang):
    cfg, db = seeded(tmp_path, scenario)
    code, sink = run_cli("doctor", "--config", cfg, "--db", db, "--json", "--lang", lang)
    summary = json.loads(sink.text)
    expected = FixtureReadModel(CATALOG, default_scenario=scenario).admin_overview(lang)["doctor"]
    got = [i for i in summary["items"] if i["check"] in ADMIN_CHECKS]
    assert got == expected["items"]
    local = [i for i in summary["items"] if i["check"] not in ADMIN_CHECKS]
    # information the Mini App cannot give: no Telegram yet; no server helpers yet (only once there are servers)
    assert [(i["check"], i["state"]) for i in local] == [("telegram", "ok")] + ([("collectors", "ok")] if scenario != "clean_install" else [])
    assert code == {"ok": 0, "warn": 1, "fail": 2}[summary["result"]]
    assert summary["result"] == expected["result"]


def test_doctor_exit_codes_sections_and_local_checks(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN + "\n"))
    cfg = init_install(tmp_path, "--telegram-token-stdin", "--group-chat-id", "-1001234567890")
    monkeypatch.setenv("VPN_PULSE_CONFIG", str(cfg))
    code, sink = run_cli("doctor")
    assert code == 2 and sink.lines[0] == "doctor: FAIL"
    assert sink.lines[1].startswith("  [FAIL] servers: Подключите первый сервер  →  vpn-pulse server add")
    assert sink.lines[2].startswith("  [WARN] probes: После сервера привяжите пробники  →  vpn-pulse probe enroll pc")
    assert "telegram" not in sink.text  # configured and readable: nothing to say
    code, sink = run_cli("doctor", "--config", init_install(tmp_path / "plain"), "--json")
    plain = json.loads(sink.text)
    assert code == 2 and [i["state"] for i in plain["items"]] == ["fail", "warn", "ok"] and plain["next_command"] == "vpn-pulse server add"  # no servers: nothing to say about collectors
    code, sink = run_cli("doctor", "telegram", "--json")
    detail = json.loads(sink.text)
    assert code == 0 and detail["items"] == [] and "token file" in detail["details"][0] and TOKEN not in sink.text
    code, sink = run_cli("doctor", "storage")
    assert code == 0 and any("schema version: 2" in line for line in sink.lines)
    # the token file disappears: a failure with the same words as the Admin screen would use
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    Path(config["telegram"]["bot_token_file"]).unlink()
    code, sink = run_cli("doctor", "--json")
    assert code == 2 and any(i["check"] == "telegram" and i["state"] == "fail" for i in json.loads(sink.text)["items"])
    # no database at all
    code, sink = run_cli("doctor", "--db", tmp_path / "nowhere.sqlite3", "--json")
    items = json.loads(sink.text)["items"]
    assert code == 2 and items[0] == {"check": "storage", "state": "fail", "next": "База данных не создана — выполните vpn-pulse init", "command": "vpn-pulse init"}


def test_doctor_reports_an_invalid_config_without_a_traceback(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("version: 1\napp: {default_language: fr}\n", encoding="utf-8")
    code, sink = run_cli("doctor", "--config", cfg)
    assert code == 2 and "config invalid" in sink.text and "Traceback" not in sink.text
    code, sink = run_cli("doctor", "--config", tmp_path / "missing.yaml")
    assert code == 2 and "not found" in sink.text


def test_doctor_https_requires_an_https_public_url():
    item, details = https_check({"app": {"public_url": "http://monitor.example"}}, Translator(), "en")
    assert item["state"] == "fail" and item["check"] == "https"
    assert "https URL" in details[0]


def test_doctor_https_reports_dns_failure(monkeypatch):
    def failed(*args, **kwargs): raise OSError("not resolved")
    monkeypatch.setattr("vpnpulse.cli.doctor.socket.getaddrinfo", failed)
    item, details = https_check({"app": {"public_url": "https://monitor.example/app/"}}, Translator(), "en")
    assert item["state"] == "fail" and "does not resolve" in details[0]


def test_doctor_https_validates_hostname_and_certificate_expiry(monkeypatch):
    class Context:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class TLS(Context):
        def getpeercert(self): return {"notAfter": "Dec 31 23:59:59 2099 GMT"}
    class SSLContext:
        def wrap_socket(self, raw, server_hostname):
            assert server_hostname == "monitor.example"; return TLS()
    monkeypatch.setattr("vpnpulse.cli.doctor.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.0.2.1", 443))])
    monkeypatch.setattr("vpnpulse.cli.doctor.socket.create_connection", lambda *a, **k: Context())
    monkeypatch.setattr("vpnpulse.cli.doctor.ssl.create_default_context", lambda: SSLContext())
    item, details = https_check({"app": {"public_url": "https://monitor.example/app/"}}, Translator(), "en")
    assert item is None and details[0].startswith("DNS:") and "hostname valid" in details[1]


def test_doctor_https_warns_before_certificate_expiry(monkeypatch):
    class Context:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class TLS(Context):
        def getpeercert(self): return {"notAfter": "Oct 01 00:00:00 2026 GMT"}
    class SSLContext:
        def wrap_socket(self, raw, server_hostname): return TLS()
    monkeypatch.setattr("vpnpulse.cli.doctor.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.0.2.1", 443))])
    monkeypatch.setattr("vpnpulse.cli.doctor.socket.create_connection", lambda *a, **k: Context())
    monkeypatch.setattr("vpnpulse.cli.doctor.ssl.create_default_context", lambda: SSLContext())
    item, _ = https_check({"app": {"public_url": "https://monitor.example/"}}, Translator(), "en",
                          datetime(2026, 9, 21, tzinfo=UTC))
    assert item["state"] == "warn" and "10 days" in item["next"]
