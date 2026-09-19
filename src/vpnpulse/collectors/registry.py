"""The collectors map: which helper answers for which server (contracts/collectors.schema.json).

The map is a private YAML file next to the secrets — it names hosts, so it never sits in the public
`config.yaml`; that file only says `servers[].collector_ref: <entry>`. `build_collectors` pairs the
two and returns one `SshCollector` per enabled server that has a matching, enabled entry; servers
without one are simply not collected (their evidence comes from probes), which `doctor` reports.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from vpnpulse.collectors.ssh import Runner, SshCollector, SshTarget
from vpnpulse.config import ConfigurationError
from vpnpulse.i18n import Translator


def _schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "collectors.schema.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("contracts/collectors.schema.json not found")


def load_collectors_map(path: Path) -> dict:
    """Read and validate the map; raises ConfigurationError with a message free of secrets."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = json.loads(_schema_path().read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(data)
    except OSError as error:
        raise ConfigurationError(f"collectors map {path.name}: {type(error).__name__}") from error
    except (yaml.YAMLError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"collectors map {path.name}: not valid YAML/JSON ({type(error).__name__})") from error
    except jsonschema.ValidationError as error:
        raise ConfigurationError(f"collectors map {path.name}: schema validation failed ({error.validator})") from error
    return data


def target_for(entry: dict, base_dir: Path) -> SshTarget:
    def path(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else base_dir / p

    return SshTarget(
        host=entry["host"],
        key_file=path(entry["key_file"]),
        known_hosts_file=path(entry["known_hosts_file"]),
        user=entry.get("user", "vpnpulse"),
        port=int(entry.get("port", 22)),
        timeout_seconds=int(entry.get("timeout_seconds", 20)),
    )


def build_collectors(config: dict, collectors_map: dict, *, base_dir: Path, translator: Translator | None = None, runner: Runner | None = None) -> list[SshCollector]:
    """One SshCollector per enabled server whose `collector_ref` names an enabled map entry."""
    freshness = int((config.get("monitoring") or {}).get("freshness_seconds", 180))
    entries = collectors_map.get("collectors") or {}
    out: list[SshCollector] = []
    for server in config.get("servers", []):
        if not server.get("enabled", True):
            continue
        ref = server.get("collector_ref")
        entry = entries.get(ref) if ref else None
        if not entry or not entry.get("enabled", True):
            continue
        out.append(SshCollector(server["id"], target_for(entry, base_dir), name=ref, freshness_seconds=freshness, translator=translator, runner=runner))
    return out


def unreferenced(config: dict, collectors_map: dict) -> tuple[list[str], list[str]]:
    """(servers without a usable entry, map entries no server refers to) — for doctor and `collector test`."""
    entries = collectors_map.get("collectors") or {}
    refs = {s.get("collector_ref") for s in config.get("servers", []) if s.get("enabled", True)}
    servers_without = [s["id"] for s in config.get("servers", []) if s.get("enabled", True) and not (s.get("collector_ref") in entries and entries[s["collector_ref"]].get("enabled", True))]
    entries_without = [name for name in entries if name not in refs]
    return servers_without, entries_without
