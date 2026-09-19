"""`vpn-pulse collector keygen | pin | test | list` and the loop's use of the collectors map."""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import vpnpulse.cli.collector as collector_cli
from test_cli import init_install, run_cli
from test_ssh_collector import helper_json
from vpnpulse.cli.common import Output
from vpnpulse.cli.run import real_collectors

HAS_SSH_KEYGEN = shutil.which("ssh-keygen") is not None
HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleHostKeyNotRealNotRealNotRealNotRe host"


def add_server(cfg: Path, server_id: str = "lv-1", kind: str = "awg-host") -> None:
    code, sink = run_cli("server", "add", "--config", cfg, "--id", server_id, "--type", kind, "--name-ru", "Сервер", "--name-en", "Server", "--country", "LV", "--priority", "10")
    assert code == 0, sink.text


@pytest.mark.skipif(not HAS_SSH_KEYGEN, reason="ssh-keygen is not installed")
def test_keygen_makes_a_private_key_a_map_entry_and_the_install_command(tmp_path):
    cfg = init_install(tmp_path)
    add_server(cfg)
    code, sink = run_cli("collector", "keygen", "lv-1", "--host", "lv-1.internal", "--config", cfg)
    assert code == 0, sink.text
    secrets = cfg.parent / "secrets"
    key = secrets / "collector-lv-1.key"
    assert key.exists() and (secrets / "collector-lv-1.key.pub").exists()
    if sys.platform != "win32":
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
    private = key.read_text(encoding="utf-8")
    assert "PRIVATE KEY" in private and private.strip().splitlines()[1] not in sink.text  # never printed
    public = (secrets / "collector-lv-1.key.pub").read_text(encoding="utf-8").strip()
    assert "install-helper.sh --kind awg-host --iface awg0 --pubkey '" + public + "'" in sink.text
    collectors_map = yaml.safe_load((secrets / "collectors.yaml").read_text(encoding="utf-8"))
    assert collectors_map["collectors"]["collector-lv-1"] == {"kind": "awg-host", "host": "lv-1.internal", "port": 22, "user": "vpnpulse", "key_file": "collector-lv-1.key", "known_hosts_file": "collector-lv-1.known_hosts", "timeout_seconds": 20, "enabled": True}
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert config["servers"][0]["collector_ref"] == "collector-lv-1" and config["storage"]["collectors_file"] == "secrets/collectors.yaml"
    assert "lv-1.internal" not in cfg.read_text(encoding="utf-8")  # the host stays out of the public configuration
    # a second run refuses to overwrite silently
    code, sink = run_cli("collector", "keygen", "lv-1", "--host", "lv-1.internal", "--config", cfg)
    assert code == 2 and "--force" in sink.text
    code, sink = run_cli("collector", "list", "--config", cfg)
    assert code == 0 and "collector-lv-1" in sink.text and "key=ok" in sink.text and "host-key=missing" in sink.text


def test_keygen_validates_its_arguments(tmp_path):
    cfg = init_install(tmp_path)
    add_server(cfg)
    assert run_cli("collector", "keygen", "lv-1", "--host", "bad host name", "--config", cfg)[0] == 2
    assert run_cli("collector", "keygen", "lv-1", "--host", "h", "--user", "Root!", "--config", cfg)[0] == 2
    assert run_cli("collector", "keygen", "ghost", "--host", "h", "--config", cfg)[0] == 2
    add_server(cfg, "fi-1", "hiddify")
    code, sink = run_cli("collector", "keygen", "fi-1", "--host", "h", "--config", cfg)
    assert code == 2 and "--kind" in sink.text


def fake_openssh(monkeypatch, scan_stdout: str, fingerprint: str = "SHA256:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ"):
    monkeypatch.setattr(collector_cli.shutil, "which", lambda name: f"/fake/{name}")

    def run(command, **kwargs):
        tool = Path(command[0]).name
        if tool == "ssh-keyscan":
            return subprocess.CompletedProcess(command, 0, scan_stdout, "")
        if tool == "ssh-keygen" and "-lf" in command:
            return subprocess.CompletedProcess(command, 0, f"256 {fingerprint} host (ED25519)\n", "")
        raise AssertionError(f"unexpected tool {tool}")

    monkeypatch.setattr(collector_cli.subprocess, "run", run)


def prepared_entry(tmp_path: Path) -> Path:
    cfg = init_install(tmp_path)
    add_server(cfg)
    secrets = cfg.parent / "secrets"
    (secrets / "collectors.yaml").write_text(yaml.safe_dump({"version": 1, "collectors": {"collector-lv-1": {
        "kind": "awg-host", "host": "lv-1.internal", "key_file": "collector-lv-1.key", "known_hosts_file": "collector-lv-1.known_hosts"}}}), encoding="utf-8")
    marker = "OPENSSH PRIVATE KEY-----"  # assembled here so the private-data scan of this repository stays clean
    (secrets / "collector-lv-1.key").write_text(f"-----BEGIN {marker}\nfake\n-----END {marker}\n", encoding="utf-8")
    (secrets / "collector-lv-1.key").chmod(0o600)
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    config["servers"][0]["collector_ref"] = "collector-lv-1"
    config["storage"]["collectors_file"] = "secrets/collectors.yaml"
    cfg.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cfg


def test_pin_stores_the_host_key_and_refuses_a_wrong_fingerprint(tmp_path, monkeypatch):
    cfg = prepared_entry(tmp_path)
    fake_openssh(monkeypatch, f"# lv-1.internal:22 SSH-2.0\nlv-1.internal ssh-rsa AAAAB3RSA\nlv-1.internal {HOST_KEY}\n")
    code, sink = run_cli("collector", "pin", "lv-1", "--fingerprint", "SHA256:wrongwrongwrongwrongwrongwrongwrongwrongwro", "--config", cfg)
    assert code == 2 and "does not match" in sink.text and not (cfg.parent / "secrets" / "collector-lv-1.known_hosts").exists()
    code, sink = run_cli("collector", "pin", "lv-1", "--config", cfg)
    assert code == 0 and "SHA256:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ" in sink.text
    pinned = (cfg.parent / "secrets" / "collector-lv-1.known_hosts").read_text(encoding="utf-8").strip()
    assert pinned == f"lv-1.internal {HOST_KEY}"  # the ed25519 line is preferred over rsa
    code, sink = run_cli("collector", "pin", "lv-1", "--fingerprint", "SHA256:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ", "--config", cfg)
    assert code == 0


def test_pin_needs_a_reachable_server(tmp_path, monkeypatch):
    cfg = prepared_entry(tmp_path)
    fake_openssh(monkeypatch, "")
    code, sink = run_cli("collector", "pin", "lv-1", "--config", cfg)
    assert code == 2 and "no host key" in sink.text


def test_test_reports_coverage_not_values(tmp_path, monkeypatch):
    cfg = prepared_entry(tmp_path)
    (cfg.parent / "secrets" / "collector-lv-1.known_hosts").write_text(f"lv-1.internal {HOST_KEY}\n", encoding="utf-8")
    (cfg.parent / "secrets" / "collector-lv-1.known_hosts").chmod(0o600)
    import vpnpulse.collectors.ssh as ssh_module

    monkeypatch.setattr(ssh_module, "_run", lambda command, timeout: subprocess.CompletedProcess(command, 0, json.dumps(helper_json()), ""))
    code, sink = run_cli("collector", "test", "lv-1", "--config", cfg)
    assert code == 0, sink.text
    assert "collector-lv-1: OK" in sink.text and "KERNEL_MODULE_MISMATCH" in sink.text and "connections" in sink.text
    assert "lv-1.internal" not in sink.text and "5.15.0" not in sink.text and "10" not in sink.text.split("OK", 1)[1].split("attention")[0]
    code, sink = run_cli("collector", "test", "lv-1", "--json", "--config", cfg)
    payload = json.loads(sink.lines[0])
    assert payload["result"] == "success" and payload["human_activity"] is True and payload["coverage"]["connections"].startswith("1/1")
    monkeypatch.setattr(ssh_module, "_run", lambda command, timeout: subprocess.CompletedProcess(command, 255, "", "Permission denied (publickey)."))
    code, sink = run_cli("collector", "test", "lv-1", "--config", cfg)
    assert code == 1 and "SSH_AUTH_FAILED" in sink.text and "install-helper.sh" in sink.text


def test_test_refuses_to_run_without_the_pinned_host_key(tmp_path):
    cfg = prepared_entry(tmp_path)
    code, sink = run_cli("collector", "test", "lv-1", "--config", cfg)
    assert code == 2 and "known_hosts" in sink.text and "missing" in sink.text


def test_run_builds_real_collectors_from_the_map_and_refuses_a_missing_one(tmp_path):
    cfg = prepared_entry(tmp_path)
    (cfg.parent / "secrets" / "collector-lv-1.known_hosts").write_text(f"lv-1.internal {HOST_KEY}\n", encoding="utf-8")
    (cfg.parent / "secrets" / "collector-lv-1.known_hosts").chmod(0o600)
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    collectors = real_collectors(config, cfg, Output(out=lambda _: None, err=lambda _: None))
    assert [c.name for c in collectors] == ["collector-lv-1"] and collectors[0].target.host == "lv-1.internal"
    (cfg.parent / "secrets" / "collectors.yaml").unlink()
    from vpnpulse.cli.common import CliError

    with pytest.raises(CliError) as error:
        real_collectors(config, cfg, Output(out=lambda _: None, err=lambda _: None))
    assert "collectors map not found" in str(error.value)
    config["storage"].pop("collectors_file")
    assert real_collectors(config, cfg, Output(out=lambda _: None, err=lambda _: None)) == []
