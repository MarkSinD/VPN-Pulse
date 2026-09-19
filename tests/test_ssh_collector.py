"""SshCollector: helper JSON → contract payloads, human activity, failures as codes; the map; the loop."""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
import yaml

from vpnpulse.collectors import SshCollector, SshTarget, build_collectors, load_collectors_map, unreferenced
from vpnpulse.collectors.ssh import ERROR_CODES, classify_failure
from vpnpulse.config import ConfigurationError
from vpnpulse.pipeline import Pipeline
from vpnpulse.storage import SqliteReadModel, apply_migrations, connect

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "contracts" / "collector-observation.schema.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
TARGET = SshTarget(host="lv-1.internal", key_file=Path("/etc/vpn-pulse/secrets/collector-lv-1.key"), known_hosts_file=Path("/etc/vpn-pulse/secrets/collector-lv-1.known_hosts"))
CONFIG = {
    "version": 1,
    "app": {"default_language": "ru", "languages": ["ru", "en"], "timezone": "UTC"},
    "servers": [
        {"id": "lv-1", "type": "awg-host", "name": {"ru": "Сервер 1", "en": "Server 1"}, "country_code": "LV", "enabled": True, "recommended_priority": 10, "collector_ref": "collector-lv-1"},
        {"id": "nl-1", "type": "awg-docker", "name": {"ru": "Сервер 2", "en": "Server 2"}, "country_code": "NL", "enabled": True, "recommended_priority": 20},
    ],
    "monitoring": {"collection_interval_seconds": 60, "pc_target_interval_seconds": 60, "probe_deadline_seconds": 20, "confirmations": 2, "freshness_seconds": 180},
    "retention": {"observations_days": 7, "aggregates_days": 90, "events_days": 180, "analytics_raw_days": 30, "audit_days": 365},
}


def helper_json(**overrides) -> dict:
    payload = {
        "schema": 1, "kind": "awg-host", "observed_at": int(NOW.timestamp()),
        "engine": {"ok": True, "listening": True},
        "peers": {"count": 10, "handshake_ages": [12, 90, 400, 7200, 100000, -1, -1, -1, -1, -1], "rx_bytes": 1_000_000, "tx_bytes": 2_000_000},
        "system": {"cpu_percent": 7, "memory_percent": 61, "swap_percent": 3, "disk_percent": 56, "uptime_s": 3456789,
                   "kernel": "5.15.0-76-generic", "kernels_installed": ["5.15.0-76-generic", "5.15.0-191-generic"],
                   "dkms_module": "amneziawg", "dkms_built_for": ["5.15.0-76-generic"], "awg_version": "v1.0.20240712",
                   "congestion_control": "bbr", "qdisc": "fq"},
        "dns": None, "errors": [],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return payload


class FakeSsh:
    """Stands in for subprocess.run: records the command line, answers from a script."""

    def __init__(self, answers) -> None:
        self.answers = list(answers)
        self.commands: list[list[str]] = []

    def __call__(self, command, timeout):
        self.commands.append(command)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            code, stdout, stderr = answer
            return subprocess.CompletedProcess(command, code, stdout, stderr)
        return subprocess.CompletedProcess(command, 0, json.dumps(answer), "")


def validate(metrics: dict) -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(metrics)


def test_success_becomes_a_contract_payload_and_human_activity():
    ssh = FakeSsh([helper_json()])
    collector = SshCollector("lv-1", TARGET, name="collector-lv-1", runner=ssh)
    observations = collector.collect(NOW)
    assert [o.source for o in observations] == ["collector", "human_activity"]
    main, humans = observations
    assert main.result == "success" and main.observed_at == NOW and main.error_code is None
    validate(main.metrics)
    m = main.metrics
    assert m["connections"] == {"amneziawg": 2}  # handshakes within 180 s
    assert m["profiles"] == {"issued": 10, "ever_connected": 5, "active_24h": 4, "last_connection_at": "2026-09-19T11:59:48Z"}
    assert m["resources"] == {"traffic_mbps": None, "cpu_percent": 7, "memory_percent": 61, "swap_percent": 3, "peak_connections_24h": None}
    assert [c["check"] for c in m["service_checks"]] == ["ssh", "engine", "port"] and all(c["ok"] for c in m["service_checks"])
    assert [c["id"] for c in m["components"]] == ["amneziawg", "tuning"]
    assert m["components"][0] == {"id": "amneziawg", "name": "AmneziaWG", "version": "v1.0.20240712", "note_key": "server.software.kernel", "note": None}
    assert [a["code"] for a in m["attention"]] == ["KERNEL_MODULE_MISMATCH"]
    assert m["attention"][0]["severity"] == "high" and "Перезагрузка" in m["attention"][0]["message"]["ru"] and "reboot" in m["attention"][0]["message"]["en"]
    assert m["diagnostics"]["kernel_newest_installed"] == "5.15.0-191-generic" and m["diagnostics"]["ssh_ok"] is True
    assert humans.result == "success" and humans.metrics == {"connections": {"amneziawg": 2}}
    # the ssh command line: batch, strict host key, pinned file, the collector's own key, nothing interactive
    command = ssh.commands[0]
    assert command[0] == "ssh" and "BatchMode=yes" in command and "StrictHostKeyChecking=yes" in command and "IdentitiesOnly=yes" in command
    assert f"UserKnownHostsFile={TARGET.known_hosts_file}" in command and str(TARGET.key_file) in command and command[-2] == f"{TARGET.user}@{TARGET.host}"


def test_no_fresh_handshakes_is_not_human_activity_and_traffic_needs_two_runs():
    ssh = FakeSsh([
        helper_json(peers={"handshake_ages": [500, -1], "count": 2, "rx_bytes": 1000, "tx_bytes": 1000}),
        helper_json(observed_at=int((NOW + timedelta(seconds=60)).timestamp()), peers={"handshake_ages": [560, -1], "count": 2, "rx_bytes": 751_000, "tx_bytes": 1000}),
        helper_json(observed_at=int((NOW + timedelta(seconds=120)).timestamp()), peers={"handshake_ages": [620, -1], "count": 2, "rx_bytes": 10, "tx_bytes": 10}),
    ])
    collector = SshCollector("lv-1", TARGET, runner=ssh)
    first = collector.collect(NOW)
    assert [o.source for o in first] == ["collector"] and first[0].metrics["connections"] == {"amneziawg": 0}
    assert first[0].metrics["resources"]["traffic_mbps"] is None
    second = collector.collect(NOW + timedelta(seconds=60))
    assert second[0].metrics["resources"]["traffic_mbps"] == 0.1  # 750 000 bytes × 8 / 60 s
    third = collector.collect(NOW + timedelta(seconds=120))
    assert third[0].metrics["resources"]["traffic_mbps"] is None  # counters reset: no rate this run, no negative numbers
    for observation in first + second + third:
        validate(observation.metrics)


def test_findings_disk_swap_ddns_tuning_and_a_docker_engine():
    payload = helper_json(kind="awg-docker", system={"disk_percent": 91, "swap_percent": 55, "congestion_control": "hybla", "kernels_installed": ["6.8.0-124-generic"], "kernel": "6.8.0-124-generic", "dkms_module": "", "dkms_built_for": []},
                          dns={"configured": True, "resolves": True, "matches_public_ip": False})
    collector = SshCollector("nl-1", TARGET, runner=FakeSsh([payload]))
    main = collector.collect(NOW)[0]
    validate(main.metrics)
    assert [a["code"] for a in main.metrics["attention"]] == ["DISK_PRESSURE", "DDNS_MISMATCH", "TUNING_LOST"]
    assert main.metrics["attention"][0]["message"]["ru"] == "Диск 91%, swap 55%. Есть что освободить."
    assert main.metrics["attention"][2]["message"]["en"] == "Network tuning lost: congestion control is hybla instead of bbr."
    assert [c["check"] for c in main.metrics["service_checks"]] == ["ssh", "engine", "port", "dns", "ddns"]
    assert main.metrics["service_checks"][4] == {"check": "ddns", "ok": False}
    assert [c["id"] for c in main.metrics["components"]] == ["amneziawg", "tuning", "ddns"]
    assert main.metrics["components"][0]["note_key"] == "server.software.docker" and main.metrics["components"][1]["name"] == "HYBLA"


def test_helper_dump_failure_keeps_system_facts_but_no_connection_numbers():
    payload = helper_json(engine={"ok": False, "listening": None}, peers={"count": 0, "handshake_ages": [], "rx_bytes": 0, "tx_bytes": 0}, errors=["DUMP_FAILED"])
    main = SshCollector("lv-1", TARGET, runner=FakeSsh([payload])).collect(NOW)[0]
    validate(main.metrics)
    assert main.result == "success"  # SSH worked; what it could not read is null, not zero
    assert main.metrics["connections"] == {"amneziawg": None} and main.metrics["profiles"]["issued"] is None
    assert [a["code"] for a in main.metrics["attention"]] == ["KERNEL_MODULE_MISMATCH", "ENGINE_UNREADABLE"]
    assert main.metrics["service_checks"][1] == {"check": "engine", "ok": False} and main.metrics["service_checks"][2] == {"check": "port", "ok": None}


@pytest.mark.parametrize("answer, code", [
    (subprocess.TimeoutExpired(["ssh"], 20), "SSH_TIMEOUT"),
    ((255, "", "ssh: connect to host lv-1.internal port 22: Connection timed out"), "SSH_UNREACHABLE"),
    ((255, "", "Permission denied (publickey)."), "SSH_AUTH_FAILED"),
    ((255, "", "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@ Host key verification failed."), "SSH_HOST_KEY_MISMATCH"),
    ((1, "", "helper config missing"), "HELPER_FAILED"),
    ((0, "not json at all", ""), "HELPER_INVALID_ANSWER"),
    ((0, json.dumps({"schema": 99}), ""), "HELPER_INVALID_ANSWER"),
    (OSError("ssh not found"), "HELPER_FAILED"),
])
def test_failures_are_codes_without_hosts(answer, code):
    main = SshCollector("lv-1", TARGET, runner=FakeSsh([answer])).collect(NOW)[0]
    assert main.source == "collector" and main.result == "failure" and main.error_code == code
    validate(main.metrics)
    assert main.metrics["service_checks"] == [{"check": "ssh", "ok": False}] and main.metrics["diagnostics"] == {"code": code, "ssh_ok": False}
    assert "lv-1.internal" not in json.dumps(main.metrics) and "22" not in main.error_code


def test_classify_failure_prefers_the_most_specific_reason():
    assert classify_failure(255, "Host key verification failed.") == ERROR_CODES["hostkey"]
    assert classify_failure(255, "Permission denied (publickey,password).") == ERROR_CODES["auth"]
    assert classify_failure(255, "") == ERROR_CODES["connect"]
    assert classify_failure(2, "something in the helper") == ERROR_CODES["helper"]


def test_a_helper_clock_far_from_ours_does_not_move_the_observation():
    main = SshCollector("lv-1", TARGET, runner=FakeSsh([helper_json(observed_at=int(NOW.timestamp()) - 3600)])).collect(NOW)[0]
    assert main.observed_at == NOW


# ---------- the collectors map ----------
def write_map(tmp_path: Path, entries: dict) -> Path:
    path = tmp_path / "secrets" / "collectors.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"version": 1, "collectors": entries}), encoding="utf-8")
    return path


def test_map_is_validated_and_paired_with_servers(tmp_path):
    path = write_map(tmp_path, {
        "collector-lv-1": {"kind": "awg-host", "host": "lv-1.internal", "key_file": "collector-lv-1.key", "known_hosts_file": "collector-lv-1.known_hosts"},
        "collector-orphan": {"kind": "awg-docker", "host": "x.internal", "key_file": "x.key", "known_hosts_file": "x.kh", "enabled": False},
    })
    collectors_map = load_collectors_map(path)
    collectors = build_collectors(CONFIG, collectors_map, base_dir=path.parent)
    assert [c.server_id for c in collectors] == ["lv-1"] and collectors[0].name == "collector-lv-1"
    assert collectors[0].target.key_file == path.parent / "collector-lv-1.key" and collectors[0].target.user == "vpnpulse" and collectors[0].target.port == 22
    assert unreferenced(CONFIG, collectors_map) == (["nl-1"], ["collector-orphan"])


@pytest.mark.parametrize("entries, fragment", [
    ({"collector-lv-1": {"kind": "awg-host", "host": "h"}}, "key_file"),
    ({"collector-lv-1": {"kind": "ftp", "host": "h", "key_file": "k", "known_hosts_file": "kh"}}, "kind"),
    ({"Bad Name": {"kind": "awg-host", "host": "h", "key_file": "k", "known_hosts_file": "kh"}}, "Bad Name"),
    ({"collector-lv-1": {"kind": "awg-host", "host": "h", "key_file": "k", "known_hosts_file": "kh", "password": "hunter2"}}, "password"),
])
def test_map_rejects_bad_entries_without_echoing_secrets(tmp_path, entries, fragment):
    path = write_map(tmp_path, entries)
    with pytest.raises(ConfigurationError) as error:
        load_collectors_map(path)
    assert "schema validation failed" in str(error.value)
    assert "hunter2" not in str(error.value) and "Bad Name" not in str(error.value)


def test_the_loop_turns_helper_answers_into_states(tmp_path):
    connection = connect(tmp_path / "loop.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    ssh = FakeSsh([helper_json(observed_at=int((NOW + timedelta(seconds=60 * i)).timestamp())) for i in range(3)])
    collector = SshCollector("lv-1", TARGET, name="collector-lv-1", runner=ssh)
    sent = []
    pipeline = Pipeline(connection, CONFIG, collectors=[collector], notifier=lambda t, p: sent.append(t) or True, now=lambda: NOW)
    for i in range(3):
        pipeline.run_once(NOW + timedelta(seconds=60 * i))
    read_model = SqliteReadModel(connection, CONFIG, now=lambda: NOW + timedelta(seconds=120))
    status = read_model.status("admin")
    lv = next(c for c in status["servers"] if c["id"] == "lv-1")
    nl = next(c for c in status["servers"] if c["id"] == "nl-1")
    assert lv["state"] == "operational" and nl["state"] == "unknown"  # humans confirm lv-1; nl-1 has no source yet
    detail = read_model.admin_server("lv-1")
    assert [a["code"] for a in detail["attention_items"]] == ["KERNEL_MODULE_MISMATCH"]
    member = read_model.server("lv-1", "member")
    assert member["components"][0]["name"] == "AmneziaWG" and member["resources"]["cpu_percent"] == 7
    assert sent == []  # the first evaluation tells nobody
    assert connection.execute("SELECT count(*) FROM observations WHERE source_kind = 'human_activity'").fetchone()[0] == 3
