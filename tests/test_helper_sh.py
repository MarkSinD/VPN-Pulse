"""deploy/helper: the server-side scripts on fake tools — key-free output, honest about failures.

`vpn-pulse-dump` gets a dump with a private key, a preshared key, endpoints and allowed IPs and
must print none of them (secret canary). `vpn-pulse-helper` assembles the JSON the collector
parses from a fake /proc, fake `dkms`, `ss`, `df`, `ip`, `tc`, `getent` and the sanitized dump.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "deploy" / "helper"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")

# canaries shaped like WireGuard keys (43 base64 chars + "=") but obviously not keys — secret scanners
# must not mistake the test for a leak, and the scripts must never print them
PRIVATE_KEY = "CANARYPRIVATE000000000000000000000000000000="
PEER_KEY = "CANARYPEERPUB000000000000000000000000000000="
PSK = "CANARYPRESHARED0000000000000000000000000000="
DUMP = "\n".join([
    f"{PRIVATE_KEY}\tSERVERPUBKEY0000000000000000000000000000000=\t51820\toff",
    f"{PEER_KEY}\t{PSK}\t203.0.113.7:51820\t10.8.1.2/32\t{{h1}}\t123456\t654321\toff",
    f"peerTwo00000000000000000000000000000000000=\t(none)\t(none)\t10.8.1.3/32\t0\t0\t0\toff",
    f"peerThree0000000000000000000000000000000000=\t(none)\t198.51.100.9:4000\t10.8.1.4/32\t{{h3}}\t10\t20\toff",
])


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fake_tools(tmp_path: Path, *, dump: str, listening_port: str = "51820", congestion: str = "bbr") -> tuple[Path, dict]:
    """A PATH with shell fakes and a /proc-like tree; returns (bin dir, extra environment)."""
    bin_dir = tmp_path / "bin"
    write(bin_dir / "sudo", '#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n', True)
    write(bin_dir / "awg", f'#!/bin/sh\n[ "$1" = "--version" ] && {{ echo "amneziawg-tools v1.0.20240712 - https://example.invalid"; exit 0; }}\ncat "{(tmp_path / "dump.txt").as_posix()}"\n', True)
    write(bin_dir / "docker", f'#!/bin/sh\ncat "{(tmp_path / "dump.txt").as_posix()}"\n', True)
    write(bin_dir / "ss", f'#!/bin/sh\necho "UNCONN 0 0 0.0.0.0:{listening_port} 0.0.0.0:*"\necho "UNCONN 0 0 [::]:{listening_port} [::]:*"\n', True)
    write(bin_dir / "dkms", '#!/bin/sh\necho "amneziawg/1.0.0, 5.15.0-76-generic, x86_64: installed"\necho "amneziawg/1.0.0, 5.15.0-60-generic, x86_64: built"\n', True)
    write(bin_dir / "df", '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\necho "/dev/sda2 15000000 8250000 6750000 55% /"\n', True)
    write(bin_dir / "uname", '#!/bin/sh\necho 5.15.0-76-generic\n', True)
    write(bin_dir / "ip", '#!/bin/sh\ncase "$*" in *route*) echo "default via 203.0.113.1 dev ens18 proto static";; *addr*) echo "2: ens18 inet 203.0.113.10/24 brd 203.0.113.255 scope global ens18";; esac\n', True)
    write(bin_dir / "tc", '#!/bin/sh\necho "qdisc fq 8001: root refcnt 2 limit 10000p"\n', True)
    write(bin_dir / "getent", '#!/bin/sh\n[ "$2" = "vpn.example.org" ] && echo "203.0.113.10 STREAM vpn.example.org" || exit 2\n', True)
    write(tmp_path / "dump.txt", dump)
    proc = tmp_path / "proc"
    write(proc / "stat", "cpu  1000 0 500 8000 100 0 50 0 0 0\ncpu0 1000 0 500 8000 100 0 50 0 0 0\n")
    write(proc / "meminfo", "MemTotal:        980000 kB\nMemFree:          90000 kB\nMemAvailable:    420000 kB\nSwapTotal:      2000000 kB\nSwapFree:       1600000 kB\n")
    write(proc / "uptime", "3456789.12 3000000.00\n")
    write(proc / "sys" / "net" / "ipv4" / "tcp_congestion_control", congestion + "\n")
    modules = tmp_path / "modules"
    for kernel, complete in (("5.15.0-76-generic", True), ("5.15.0-191-generic", True), ("5.15.0-56-generic", False)):
        (modules / kernel).mkdir(parents=True)
        if complete:
            write(modules / kernel / "modules.dep", "")
    write(tmp_path / "helper.conf", "KIND=awg-host\nIFACE=awg0\nDOMAIN=vpn.example.org\n")
    env = {
        "VPN_PULSE_HELPER_CONF": (tmp_path / "helper.conf").as_posix(),
        "VPN_PULSE_DUMP": (HELPER / "vpn-pulse-dump").as_posix(),
        "VPN_PULSE_PROC": proc.as_posix(),
        "VPN_PULSE_MODULES": modules.as_posix(),
        "VPN_PULSE_CPU_SAMPLE": "0",
    }
    return bin_dir, env


def run_script(script: str, bin_dir: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    merged = {**os.environ, **env, "PATH": bin_dir.as_posix() + os.pathsep + os.environ.get("PATH", "")}
    # Git Bash may prepend its own tools at startup. Put the fakes first afterwards.
    command = [BASH, "-c", 'bin="$1"; command -v cygpath >/dev/null && bin=$(cygpath -u "$bin"); export PATH="$bin:$PATH"; shift; exec sh "$@"', "helper-test", bin_dir.as_posix(), (HELPER / script).as_posix(), *args]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=merged, timeout=60)


def dump_now() -> str:
    now = int(time.time())
    return DUMP.replace("{h1}", str(now - 30)).replace("{h3}", str(now - 7200))


def test_dump_prints_ages_and_counters_but_never_keys_endpoints_or_ports(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now())
    result = run_script("vpn-pulse-dump", bin_dir, env)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "listening 1"
    assert [line.split()[0] for line in lines[1:]] == ["peer", "peer", "peer"]
    assert all(len(line.split()) == 4 for line in lines[1:])
    for secret in (PRIVATE_KEY, PEER_KEY, PSK, "203.0.113.7", "10.8.1.2", "51820", "SERVERPUBKEY"):
        assert secret not in result.stdout, secret
    assert lines[2] == "peer 0 0 0"  # never handshaked


def test_dump_refuses_a_shape_it_does_not_understand(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump="only-one-column\nweird peer line without numbers\n")
    result = run_script("vpn-pulse-dump", bin_dir, env)
    assert result.returncode == 3
    assert result.stdout.strip() == ""


def test_dump_reports_a_silent_port(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now(), listening_port="1")
    result = run_script("vpn-pulse-dump", bin_dir, env)
    assert result.stdout.splitlines()[0] == "listening 0"


def test_dump_does_not_emit_partial_results_before_a_malformed_peer(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now() + "\nmalformed secret peer\n")
    result = run_script("vpn-pulse-dump", bin_dir, env)
    assert result.returncode == 3 and result.stdout == ""


@pytest.mark.parametrize("option", ["--iface", "--container", "--domain"])
def test_installer_rejects_shell_syntax_before_writing_config(tmp_path, option):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now())
    write(bin_dir / "id", "#!/bin/sh\necho 0\n", True)
    result = run_script("install-helper.sh", bin_dir, env, "--kind", "awg-host", "--pubkey", "ssh-ed25519 AAAAC3 test", option, "x;touch injected", "--dry-run")
    assert result.returncode == 2 and "invalid" in result.stderr


def test_dump_inside_a_container_uses_docker_exec(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now())
    write(tmp_path / "helper.conf", "KIND=awg-docker\nIFACE=awg0\nCONTAINER=amnezia-awg\n")
    result = run_script("vpn-pulse-dump", bin_dir, env)
    assert result.returncode == 0 and result.stdout.count("peer ") == 3


def test_helper_assembles_key_free_json_from_the_system(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now())
    result = run_script("vpn-pulse-helper", bin_dir, env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == 1 and payload["kind"] == "awg-host" and payload["errors"] == []
    assert payload["engine"] == {"ok": True, "listening": True}
    peers = payload["peers"]
    assert peers["count"] == 3 and peers["rx_bytes"] == 123466 and peers["tx_bytes"] == 654341
    ages = peers["handshake_ages"]
    assert len(ages) == 3 and ages[1] == -1 and 25 <= ages[0] <= 40 and 7195 <= ages[2] <= 7210
    system = payload["system"]
    assert system["kernel"] == "5.15.0-76-generic"
    assert sorted(system["kernels_installed"]) == ["5.15.0-191-generic", "5.15.0-76-generic"]  # the leftover directory is not a kernel
    assert system["dkms_module"] == "amneziawg" and system["dkms_built_for"] == ["5.15.0-76-generic"]  # "built" is not "installed"
    assert system["memory_percent"] == 57 and system["swap_percent"] == 20 and system["disk_percent"] == 55
    assert system["uptime_s"] == 3456789 and system["awg_version"] == "v1.0.20240712"
    assert system["congestion_control"] == "bbr" and system["qdisc"] == "fq"
    assert payload["dns"] == {"configured": True, "resolves": True, "matches_public_ip": True}
    for secret in (PRIVATE_KEY, PEER_KEY, PSK, "203.0.113", "10.8.1", "51820", "vpn.example.org"):
        assert secret not in result.stdout, secret


def test_helper_stays_honest_when_the_dump_fails(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump="garbage\n")
    result = run_script("vpn-pulse-helper", bin_dir, env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["errors"] == ["DUMP_FAILED"] and payload["engine"] == {"ok": False, "listening": None}
    assert payload["peers"] == {"count": 0, "handshake_ages": [], "rx_bytes": 0, "tx_bytes": 0}
    assert payload["system"]["kernel"] == "5.15.0-76-generic"  # the rest is still reported


def test_helper_without_a_domain_reports_no_dns_block(tmp_path):
    bin_dir, env = fake_tools(tmp_path, dump=dump_now(), congestion="hybla")
    write(tmp_path / "helper.conf", "KIND=awg-host\nIFACE=awg0\n")
    payload = json.loads(run_script("vpn-pulse-helper", bin_dir, env).stdout)
    assert payload["dns"] is None and payload["system"]["congestion_control"] == "hybla"


def test_install_helper_parses_arguments_and_dry_runs_without_root(tmp_path):
    assert subprocess.run([BASH, "-n", str(HELPER / "install-helper.sh")], capture_output=True).returncode == 0
    result = subprocess.run([BASH, str(HELPER / "install-helper.sh"), "--help"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0 and "--kind" in result.stdout and "sudoers" in result.stdout
    result = subprocess.run([BASH, str(HELPER / "install-helper.sh"), "--kind", "awg-host", "--pubkey", "ssh-ed25519 AAAAC3 test", "--dry-run"], capture_output=True, text=True, encoding="utf-8")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        assert result.returncode == 0 and "dry run: nothing was changed" in result.stdout
    else:
        assert result.returncode == 2 and "run as root" in result.stderr  # never silently does root things
