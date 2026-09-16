"""install.sh: syntax, help, preflight and the dry run — the full flow runs in scripts/install_check.sh."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")


def sh(*args, env=None, timeout=120):
    merged = {**os.environ, **(env or {})}
    return subprocess.run([BASH, str(ROOT / "install.sh"), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=merged, timeout=timeout, cwd=ROOT)


def test_script_parses_and_documents_its_commands():
    assert subprocess.run([BASH, "-n", str(ROOT / "install.sh")], capture_output=True).returncode == 0
    assert subprocess.run([BASH, "-n", str(ROOT / "scripts" / "install_check.sh")], capture_output=True).returncode == 0
    result = sh("--help")
    assert result.returncode == 0
    for command in ("preflight", "demo", "install", "upgrade", "rollback", "uninstall"):
        assert command in result.stdout
    assert sh("bogus").returncode == 2


def test_preflight_changes_nothing_and_reports_every_check(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    result = sh("preflight", env={"VPN_PULSE_PREFIX": str(tmp_path / "opt")})
    assert "[1/7] Environment" in result.stdout
    for word in ("python", "disk", "systemd", "caddy", "source"):
        assert word in result.stdout
    assert "nothing was changed" in result.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert result.returncode in (0, 2)  # 2 only when this machine lacks python 3.12 + venv


def test_install_dry_run_prints_the_plan_and_creates_nothing(tmp_path):
    env = {
        "VPN_PULSE_PREFIX": str(tmp_path / "opt"), "VPN_PULSE_ETC": str(tmp_path / "etc"), "VPN_PULSE_DATA": str(tmp_path / "data"),
        "VPN_PULSE_UNIT_DIR": str(tmp_path / "units"), "VPN_PULSE_CADDY_DIR": str(tmp_path / "caddy"), "VPN_PULSE_BIN": str(tmp_path / "bin" / "vpn-pulse"),
    }
    result = sh("install", "--dry-run", "--yes", "--no-systemd", "--demo-data", "--language", "en", "--domain", "monitor.example.org", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "would:" in out and "dry run: nothing was changed" in out
    for fragment in ("create system user", "copy the application", "vpn-pulse init", "seed the demo scenario", "vpn-pulse.caddy", "vpn-pulse-api.service", "vpn-pulse doctor"):
        assert fragment in out, fragment
    assert not (tmp_path / "opt").exists() and not (tmp_path / "etc").exists() and not (tmp_path / "units").exists()
    for command in ("upgrade", "rollback", "uninstall"):
        result = sh(command, "--dry-run", "--yes", "--no-systemd", env=env)
        assert "nothing is installed" in result.stderr or "dry run" in result.stdout, (command, result.stdout, result.stderr)


def test_units_and_caddy_snippet_reference_the_installed_layout():
    api = (ROOT / "deploy" / "systemd" / "vpn-pulse-api.service").read_text(encoding="utf-8")
    run = (ROOT / "deploy" / "systemd" / "vpn-pulse-run.service").read_text(encoding="utf-8")
    for unit in (api, run):
        assert "User=vpn-pulse" in unit and "ProtectSystem=strict" in unit and "ReadWritePaths=/var/lib/vpn-pulse" in unit
        assert "/opt/vpn-pulse/current/venv/bin/vpn-pulse" in unit and "VPN_PULSE_CONFIG=/etc/vpn-pulse/config.yaml" in unit
    assert "serve --host 127.0.0.1 --port 8765" in api
    assert "EnvironmentFile=-/etc/vpn-pulse/run.env" in run and "$VPN_PULSE_RUN_ARGS" in run
    caddy = (ROOT / "deploy" / "caddy" / "vpn-pulse.caddy").read_text(encoding="utf-8")
    assert "{{DOMAIN}}" in caddy and "reverse_proxy 127.0.0.1:8765" in caddy and "log" not in caddy.split("{{DOMAIN}}")[1].split("reverse_proxy")[0]
