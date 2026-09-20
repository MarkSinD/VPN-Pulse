"""The cross-server probe agent (deploy/probe-abroad): one check in a namespace, the report, the queue, enrollment."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
loader = importlib.machinery.SourceFileLoader("probe_abroad", str(ROOT / "deploy" / "probe-abroad" / "vpn-pulse-probe-abroad"))
probe = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(probe)

NOW = 1_700_000_000
TARGET = "192.0.2.1"  # the target's tunnel address (documentation range)


def config(tmp_path: Path, **extra) -> dict:
    """What read_config() would give for a minimal file, on a temporary layout."""
    peers = tmp_path / "peers"
    peers.mkdir(exist_ok=True)
    (peers / "backup.conf").write_text("[Interface]\nAddress = 192.0.2.250/32\nPrivateKey = x\n[Peer]\nAllowedIPs = 192.0.2.1/32\n", encoding="utf-8")
    path = tmp_path / "config"
    path.write_text(f"API_URL=https://monitor.example.org\nTOKEN_FILE={tmp_path / 'token'}\nPEERS_DIR={peers}\nSTATE_DIR={tmp_path / 'state'}\n"
                    f"SOCKET_DIR={tmp_path / 'sock'}\nTARGETS=backup={TARGET}\n" + "".join(f"{k}={v}\n" for k, v in extra.items()), encoding="utf-8")
    return probe.read_config(str(path))


class Runner:
    """Records every command; answers like the real tools would."""

    def __init__(self, *, ping=0, handshake=NOW - 3, fail_at=None, socket_dir=None):
        self.commands = []
        self.ping, self.handshake, self.fail_at, self.socket_dir = ping, handshake, fail_at, socket_dir

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if self.fail_at and self.fail_at in command:
            return subprocess.CompletedProcess(command, 1, "", "error")
        if command[0].endswith("amneziawg-go") and self.socket_dir:  # the userspace engine opens its control socket
            self.socket_dir.mkdir(exist_ok=True)
            (self.socket_dir / f"{command[1]}.sock").write_text("", encoding="utf-8")
        if "strip" in command:
            return subprocess.CompletedProcess(command, 0, "[Interface]\nPrivateKey = x\n[Peer]\nAllowedIPs = 192.0.2.1/32\n", "")
        if "latest-handshakes" in command:
            return subprocess.CompletedProcess(command, 0, f"peerkey\t{self.handshake}\n", "")
        if "ping" in command:
            return subprocess.CompletedProcess(command, self.ping, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_a_check_builds_the_tunnel_in_the_namespace_and_tears_it_down(tmp_path):
    runner = Runner()
    result = probe.check_target(config(tmp_path), "backup", TARGET, runner, clock=lambda: NOW)
    assert result["result"] == "success" and result["check"] == "handshake" and "error_code" not in result
    inside = ["ip", "netns", "exec", "vpprobe"]
    assert ["ip", "link", "add", "vpprobe0", "type", "amneziawg"] in runner.commands  # created outside: keeps the host's route to the endpoint
    assert ["ip", "link", "set", "vpprobe0", "netns", "vpprobe"] in runner.commands
    assert inside + ["ip", "address", "add", "192.0.2.250/32", "dev", "vpprobe0"] in runner.commands
    assert inside + ["ip", "route", "add", TARGET + "/32", "dev", "vpprobe0"] in runner.commands
    assert inside + ["ping", "-c", "2", "-W", "3", TARGET] in runner.commands
    assert runner.commands[-2] == inside + ["ip", "link", "delete", "vpprobe0"] and runner.commands[-1] == ["ip", "link", "delete", "vpprobe0"]
    assert runner.commands[0] == inside + ["ip", "link", "delete", "vpprobe0"]  # leftovers of a crashed run go first
    assert inside + ["awg", "show", "vpprobe0", "latest-handshakes"] in runner.commands


def test_the_userspace_engine_creates_the_interface_itself(tmp_path):
    conf = config(tmp_path, ENGINE="userspace", AWG_GO="/opt/awg/amneziawg-go", AWG="/opt/awg/awg", AWG_LOADER="/lib/ld-musl-x86_64.so.1")
    runner = Runner(socket_dir=tmp_path / "sock")
    result = probe.check_target(conf, "backup", TARGET, runner, clock=lambda: NOW)
    assert result["result"] == "success"
    assert ["/opt/awg/amneziawg-go", "vpprobe0"] in runner.commands and not any(c[:3] == ["ip", "link", "add"] for c in runner.commands)
    assert ["/lib/ld-musl-x86_64.so.1", "/opt/awg/awg", "setconf", "vpprobe0", "/dev/stdin"] in runner.commands
    assert ["ip", "netns", "exec", "vpprobe", "/lib/ld-musl-x86_64.so.1", "/opt/awg/awg", "show", "vpprobe0", "latest-handshakes"] in runner.commands
    # no control socket → the engine did not start → setup failure, still torn down
    (tmp_path / "sock" / "vpprobe0.sock").unlink()
    silent = Runner()
    result = probe.check_target(conf, "backup", TARGET, silent, clock=lambda: NOW)
    assert result["error_code"] == "TUNNEL_SETUP_FAILED" and silent.commands[-1] == ["ip", "link", "delete", "vpprobe0"]


def test_a_stale_handshake_or_a_lost_ping_is_a_failure_with_a_code(tmp_path):
    conf = config(tmp_path)
    stale = probe.check_target(conf, "backup", TARGET, Runner(handshake=NOW - 120), clock=lambda: NOW)
    assert (stale["result"], stale["error_code"]) == ("failure", "HANDSHAKE_FAILED")
    never = probe.check_target(conf, "backup", TARGET, Runner(handshake=0), clock=lambda: NOW)
    assert never["error_code"] == "HANDSHAKE_FAILED"
    lost = probe.check_target(conf, "backup", TARGET, Runner(ping=1), clock=lambda: NOW)
    assert (lost["result"], lost["error_code"]) == ("failure", "PING_FAILED")


def test_a_setup_failure_still_tears_down(tmp_path):
    runner = Runner(fail_at="setconf")
    result = probe.check_target(config(tmp_path), "backup", TARGET, runner, clock=lambda: NOW)
    assert result["error_code"] == "TUNNEL_SETUP_FAILED"
    assert not any("ping" in c for c in runner.commands)
    assert runner.commands[-1] == ["ip", "link", "delete", "vpprobe0"]


def test_config_and_targets_parse_and_require_the_essentials(tmp_path):
    path = tmp_path / "config"
    path.write_text("# comment\nAPI_URL = https://monitor.example.org\nTOKEN_FILE=/t\nTARGETS=a=192.0.2.1, b=192.0.2.2\n", encoding="utf-8")
    values = probe.read_config(str(path))
    assert values["API_URL"] == "https://monitor.example.org" and values["NETNS"] == "vpprobe" and values["ENGINE"] == "kernel"
    assert probe.parse_targets(values["TARGETS"]) == {"a": "192.0.2.1", "b": "192.0.2.2"}
    assert probe.awg_command(values) == ["awg"]
    path.write_text("API_URL=x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        probe.read_config(str(path))
    path.write_text("API_URL=x\nTOKEN_FILE=t\nTARGETS=a=1\nENGINE=docker\n", encoding="utf-8")
    with pytest.raises(ValueError):
        probe.read_config(str(path))


def test_the_queue_drops_old_rows_and_caps_the_rest(tmp_path):
    conf = config(tmp_path)
    probe.save_queue(conf, [{"queued_at": NOW - 90_000, "report": {}}, {"queued_at": NOW - 10, "report": {}}] * 800)
    rows = probe.load_queue(conf, clock=lambda: NOW)
    assert len(rows) == 750 and all(r["queued_at"] == NOW - 10 for r in rows)
    if os.name == "posix":
        assert probe.queue_path(conf).stat().st_mode & 0o777 == 0o600


def test_a_tick_checks_only_allowed_targets_and_posts_one_report(tmp_path, monkeypatch):
    conf = config(tmp_path)
    Path(conf["TOKEN_FILE"]).write_text("secret\n", encoding="utf-8")
    calls = []

    def api(url, **kwargs):
        calls.append((url, kwargs))
        return {"targets": [{"id": "backup"}, {"id": "other"}]} if url.endswith("/probe/config") else {"accepted": True}

    monkeypatch.setattr(probe, "request_json", api)
    monkeypatch.setattr(probe, "check_target", lambda cfg, t, a, r, c: {"target_id": t, "check": "handshake", "result": "success", "duration_ms": 1})
    assert probe.tick(conf, clock=lambda: NOW) == 0
    url, kwargs = calls[-1]
    assert url.endswith("/api/v1/probe/reports") and kwargs["token"] == "secret"
    report = kwargs["payload"]
    assert report["network"] == {"type": "abroad", "ip_family": "ipv4", "route_verified": True}
    assert [r["target_id"] for r in report["results"]] == ["backup"] and report["schema_version"] == 1
    assert probe.load_queue(conf) == []


def test_reports_wait_in_the_queue_and_go_out_oldest_first(tmp_path, monkeypatch):
    conf = config(tmp_path)
    Path(conf["TOKEN_FILE"]).write_text("secret\n", encoding="utf-8")
    state = {"down": True, "sent": []}

    def api(url, **kwargs):
        if url.endswith("/probe/config"):
            return {"targets": [{"id": "backup"}]}
        if state["down"]:
            raise OSError("unreachable")
        state["sent"].append(kwargs["payload"]["report_id"])
        return {"accepted": True}

    monkeypatch.setattr(probe, "request_json", api)
    monkeypatch.setattr(probe, "check_target", lambda cfg, t, a, r, c: {"target_id": t, "check": "handshake", "result": "failure", "duration_ms": 1, "error_code": "HANDSHAKE_FAILED"})
    assert probe.tick(conf, clock=lambda: NOW) == 1 and probe.tick(conf, clock=lambda: NOW + 60) == 1
    queued = probe.load_queue(conf, clock=lambda: NOW + 60)
    assert [row["queued_at"] for row in queued] == [NOW, NOW + 60]
    state["down"] = False
    assert probe.tick(conf, clock=lambda: NOW + 120) == 0
    assert len(state["sent"]) == 3 and state["sent"][0] == queued[0]["report"]["report_id"]
    assert probe.load_queue(conf) == []


def test_enroll_stores_the_token_for_the_owner_only(tmp_path, monkeypatch):
    conf = config(tmp_path)
    monkeypatch.setattr(probe, "request_json", lambda *a, **k: {"token": "abc"})
    probe.enroll(conf, "code")
    token = Path(conf["TOKEN_FILE"])
    assert token.read_text(encoding="utf-8").strip() == "abc"
    if os.name == "posix":
        assert token.stat().st_mode & 0o777 == 0o600
