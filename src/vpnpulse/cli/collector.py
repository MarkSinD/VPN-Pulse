"""`vpn-pulse collector keygen | pin | test | list` — the server side of connecting a server.

    keygen <server-id> --host H [--kind awg-host|awg-docker] [--user vpnpulse] [--port 22]
        a separate ed25519 key for this server only (0600 next to the other secrets), an entry in
        the collectors map, and the exact command the server owner runs there (install-helper.sh)
    pin <server-id> [--fingerprint SHA256:…]
        fetch the server's host key, show its fingerprint, store it as the pinned known_hosts file
        (StrictHostKeyChecking=yes from then on); with --fingerprint it refuses anything else
    test <server-id>
        one collection through the helper; prints the coverage (which fields came back), never values
        that could identify a host or a person
    list
        map entries and which server each serves

The collectors map (`storage.collectors_file`, default `secrets/collectors.yaml` next to
config.yaml) names hosts, so it lives with the secrets (0700 directory, 0600 file) — never in the
public configuration, never in git. Key and known_hosts paths in it are relative to that directory.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from vpnpulse.cli.common import CliError, Output, config_path_of, load_public_config, resolve_db, secret_file_status, write_config_atomic, write_secret_file
from vpnpulse.cli.run import collectors_map_path

KINDS = ("awg-host", "awg-docker")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/=]{43,44}$")


def add_parser(commands, parents) -> None:
    collector = commands.add_parser("collector", parents=parents, help="server helpers: keygen, pin, test, list")
    sub = collector.add_subparsers(dest="action", required=True)
    keygen = sub.add_parser("keygen", parents=parents, help="a collector key and a map entry for one server")
    keygen.add_argument("server_id")
    keygen.add_argument("--host", required=True, help="hostname, address or ssh alias of the server (private; goes to the map, not to config.yaml)")
    keygen.add_argument("--kind", choices=KINDS, default=None, help="default: the server's type from config.yaml")
    keygen.add_argument("--user", default="vpnpulse")
    keygen.add_argument("--port", type=int, default=22)
    keygen.add_argument("--force", action="store_true", help="replace an existing key and entry")
    keygen.set_defaults(handler=command_keygen)
    pin = sub.add_parser("pin", parents=parents, help="pin the server's host key")
    pin.add_argument("server_id")
    pin.add_argument("--fingerprint", default=None, help="expected SHA256:… fingerprint; refuse any other key")
    pin.set_defaults(handler=command_pin)
    test = sub.add_parser("test", parents=parents, help="one collection through the helper, coverage only")
    test.add_argument("server_id")
    test.add_argument("--json", action="store_true")
    test.set_defaults(handler=command_test)
    ls = sub.add_parser("list", parents=parents, help="map entries and the servers they serve")
    ls.set_defaults(handler=command_list)


# ---------- the map file ----------
def _paths(args):
    config_path = config_path_of(args)
    config = load_public_config(config_path)
    map_path = collectors_map_path(config, config_path)
    if map_path is None:
        map_path = config_path.parent / "secrets" / "collectors.yaml"
    return config, config_path, map_path


def _read_map(map_path: Path) -> dict:
    if not map_path.exists():
        return {"version": 1, "collectors": {}}
    from vpnpulse.collectors import load_collectors_map
    from vpnpulse.config import ConfigurationError

    try:
        return load_collectors_map(map_path)
    except ConfigurationError as error:
        raise CliError(str(error)) from error


def _write_map(map_path: Path, data: dict) -> None:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    write_secret_file(map_path, "# VPN Pulse collectors map — hosts and key paths; not for git (contracts/collectors.schema.json)\n" + text)


def _server(config: dict, server_id: str) -> dict:
    for server in config.get("servers", []):
        if server["id"] == server_id:
            return server
    raise CliError(f"server {server_id!r} is not in config.yaml (vpn-pulse server add first)")


def _entry(config: dict, collectors_map: dict, server_id: str) -> tuple[str, dict]:
    server = _server(config, server_id)
    ref = server.get("collector_ref")
    entry = (collectors_map.get("collectors") or {}).get(ref) if ref else None
    if not entry:
        raise CliError(f"server {server_id!r} has no collector entry yet (vpn-pulse collector keygen {server_id} --host …)")
    return ref, entry


# ---------- keygen ----------
def command_keygen(args: argparse.Namespace, out: Output) -> int:
    if not HOST_RE.match(args.host):
        raise CliError("--host must be a hostname, an address or an ssh alias")
    if not USER_RE.match(args.user):
        raise CliError("--user must be a plain unix user name")
    if not 1 <= args.port <= 65535:
        raise CliError("--port out of range")
    config, config_path, map_path = _paths(args)
    server = _server(config, args.server_id)
    kind = args.kind or ("awg-docker" if server.get("type") == "awg-docker" else "awg-host" if server.get("type") == "awg-host" else None)
    if kind is None:
        raise CliError(f"server type {server.get('type')!r} has no helper yet; pass --kind awg-host|awg-docker")
    collectors_map = _read_map(map_path)
    ref = f"collector-{args.server_id}"
    key_file = map_path.parent / f"{ref}.key"
    if (key_file.exists() or ref in collectors_map["collectors"]) and not args.force:
        raise CliError(f"{ref} already exists; pass --force to replace the key and the entry")
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        raise CliError("ssh-keygen is not installed (openssh-client)")
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.parent.chmod(0o700)
    for stale in (key_file, key_file.with_suffix(".key.pub")):
        if stale.exists():
            stale.unlink()
    result = subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", f"vpn-pulse {ref}", "-f", str(key_file)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CliError("ssh-keygen failed: " + (result.stderr.strip().splitlines() or ["?"])[-1][:120])
    key_file.chmod(0o600)
    public = key_file.with_suffix(".key.pub").read_text(encoding="utf-8").strip()
    collectors_map["collectors"][ref] = {
        "kind": kind, "host": args.host, "port": args.port, "user": args.user,
        "key_file": f"{ref}.key", "known_hosts_file": f"{ref}.known_hosts", "timeout_seconds": 20, "enabled": True,
    }
    _write_map(map_path, collectors_map)
    storage = config.setdefault("storage", {})
    if server.get("collector_ref") != ref or not storage.get("collectors_file"):
        server["collector_ref"] = ref
        if not storage.get("database"):
            storage["database"] = str(resolve_db(args, config))
        if not storage.get("collectors_file"):
            inside = map_path.is_relative_to(config_path.parent)
            storage["collectors_file"] = map_path.relative_to(config_path.parent).as_posix() if inside else str(map_path)
        write_config_atomic(config_path, config)
    out.line(f"Collector key for {args.server_id}: {key_file} (0600). Map entry {ref} in {map_path}.")
    out.line("")
    out.line("On the server, as root (install-helper.sh is in deploy/helper/ of this repository):")
    extra = "" if kind == "awg-host" else " --container amnezia-awg"
    out.line(f"    sudo ./install-helper.sh --kind {kind} --iface awg0{extra} --pubkey '{public}'")
    out.line("    (add --domain vpn.example.org when the server is reached by a name, for the DNS/DDNS checks)")
    out.line("")
    out.line(f"Then here: vpn-pulse collector pin {args.server_id}   and   vpn-pulse collector test {args.server_id}")
    return 0


# ---------- pin ----------
def command_pin(args: argparse.Namespace, out: Output) -> int:
    if args.fingerprint and not FINGERPRINT_RE.match(args.fingerprint):
        raise CliError("--fingerprint must look like SHA256:… (ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub on the server)")
    config, _, map_path = _paths(args)
    collectors_map = _read_map(map_path)
    ref, entry = _entry(config, collectors_map, args.server_id)
    keyscan, keygen = shutil.which("ssh-keyscan"), shutil.which("ssh-keygen")
    if keyscan is None or keygen is None:
        raise CliError("ssh-keyscan / ssh-keygen are not installed (openssh-client)")
    scan = subprocess.run([keyscan, "-T", "10", "-t", "ed25519,ecdsa,rsa", "-p", str(entry.get("port", 22)), entry["host"]], capture_output=True, text=True, check=False)
    lines = [line for line in scan.stdout.splitlines() if line and not line.startswith("#")]
    if not lines:
        raise CliError(f"no host key received from the server for {ref} (is it reachable on port {entry.get('port', 22)}?)")
    preferred = next((line for line in lines if " ssh-ed25519 " in line), lines[0])
    fp = subprocess.run([keygen, "-lf", "-"], input=preferred + "\n", capture_output=True, text=True, check=False)
    fingerprint = next((part for part in fp.stdout.split() if part.startswith("SHA256:")), None)
    if fingerprint is None:
        raise CliError("could not compute the host key fingerprint")
    if args.fingerprint and args.fingerprint != fingerprint:
        raise CliError(f"host key fingerprint {fingerprint} does not match --fingerprint; nothing pinned")
    known_hosts = map_path.parent / entry["known_hosts_file"]
    write_secret_file(known_hosts, preferred)
    out.line(f"Pinned the host key of {ref}: {fingerprint} → {known_hosts}")
    if not args.fingerprint:
        out.line("Compare it with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the server; re-run with --fingerprint to be strict.")
    return 0


# ---------- test ----------
def command_test(args: argparse.Namespace, out: Output) -> int:
    from vpnpulse.collectors import build_collectors

    config, _, map_path = _paths(args)
    collectors_map = _read_map(map_path)
    ref, entry = _entry(config, collectors_map, args.server_id)
    for name in ("key_file", "known_hosts_file"):
        status = secret_file_status(map_path.parent / entry[name])
        if status != "ok":
            raise CliError(f"{ref}: {entry[name]}: {status} (vpn-pulse collector keygen / pin)")
    collector = next(c for c in build_collectors(config, collectors_map, base_dir=map_path.parent) if c.server_id == args.server_id)
    from vpnpulse.cli.common import now_utc

    observations = collector.collect(now_utc())
    main = observations[0]
    if main.result != "success":
        out.line(f"{ref}: FAILED {main.error_code}")
        out.line({"SSH_TIMEOUT": "the server did not answer within the deadline", "SSH_UNREACHABLE": "no SSH connection — host, port, firewall",
                  "SSH_AUTH_FAILED": "the key is not accepted — was install-helper.sh run with this public key?",
                  "SSH_HOST_KEY_MISMATCH": "the pinned host key does not match — re-pin only if the server was legitimately reinstalled",
                  "HELPER_INVALID_ANSWER": "the helper answered with something other than its JSON — an old helper or a shell instead of the forced command",
                  }.get(main.error_code or "", "see journalctl on the server"))
        return 1
    coverage = {block: _coverage(value) for block, value in main.metrics.items() if block != "diagnostics"}
    payload = {"collector": ref, "result": "success", "coverage": coverage, "attention": [a["code"] for a in main.metrics.get("attention", [])],
               "human_activity": any(o.source == "human_activity" for o in observations)}
    if args.json:
        out.json(payload)
        return 0
    out.line(f"{ref}: OK")
    for block, fields in coverage.items():
        out.line(f"  {block:15s} {fields}")
    out.line(f"  attention       {', '.join(payload['attention']) or 'none'}")
    out.line(f"  human activity  {'yes' if payload['human_activity'] else 'no fresh handshakes'}")
    return 0


def _coverage(value) -> str:
    if isinstance(value, dict):
        known = [k for k, v in value.items() if v is not None]
        return f"{len(known)}/{len(value)}: " + ", ".join(known) if value else "empty"
    if isinstance(value, list):
        return f"{len(value)} items"
    return "?"


# ---------- list ----------
def command_list(args: argparse.Namespace, out: Output) -> int:
    from vpnpulse.collectors import unreferenced

    config, _, map_path = _paths(args)
    collectors_map = _read_map(map_path)
    servers_without, entries_without = unreferenced(config, collectors_map)
    by_ref = {s.get("collector_ref"): s["id"] for s in config.get("servers", []) if s.get("collector_ref")}
    out.line(f"collectors map: {map_path}")
    for ref, entry in (collectors_map.get("collectors") or {}).items():
        key = secret_file_status(map_path.parent / entry["key_file"])
        pinned = secret_file_status(map_path.parent / entry["known_hosts_file"])
        out.line(f"  {ref:28s} {entry['kind']:11s} server={by_ref.get(ref, '-'):12s} key={key} host-key={pinned}{'' if entry.get('enabled', True) else ' (disabled)'}")
    for server_id in servers_without:
        out.line(f"  server {server_id}: no collector (probes only) → vpn-pulse collector keygen {server_id} --host …")
    for ref in entries_without:
        out.line(f"  entry {ref}: no server refers to it")
    return 0
