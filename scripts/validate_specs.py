"""Validate VPN Pulse contracts and dictionaries.

Checks: OpenAPI 3.1 structure and local $refs, JSON Schemas (draft 2020-12), the example
configuration against its schema, RU/EN dictionary key parity and placeholder parity, and the
absence of literal IP addresses outside documentation ranges in public contract files.

Run: python scripts/validate_specs.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DOC_RANGES = ("192.0.2.", "198.51.100.", "203.0.113.", "0.0.0.0", "127.0.0.1")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def load_json(relative: str) -> dict:
    with (ROOT / relative).open(encoding="utf-8") as source:
        return json.load(source)


def placeholders(value: str) -> set[str]:
    return set(re.findall(r"\{([a-zA-Z][a-zA-Z0-9_]*)\}", value))


def resolve_local_ref(document: dict, ref: str) -> None:
    assert ref.startswith("#/"), f"only local refs are expected, got {ref}"
    current = document
    for part in ref[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]


def visit(document: dict, value) -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            resolve_local_ref(document, value["$ref"])
        for child in value.values():
            visit(document, child)
    elif isinstance(value, list):
        for child in value:
            visit(document, child)


def main() -> int:
    config_schema = load_json("contracts/config.schema.json")
    analytics_schema = load_json("contracts/analytics-events.schema.json")
    ru = load_json("i18n/ru.json")
    en = load_json("i18n/en.json")
    with (ROOT / "contracts/openapi.yaml").open(encoding="utf-8") as source:
        openapi = yaml.safe_load(source)
    with (ROOT / "contracts/config.example.yaml").open(encoding="utf-8") as source:
        config_example = yaml.safe_load(source)

    assert openapi["openapi"].startswith("3.1"), "OpenAPI must use 3.1"
    assert openapi["paths"], "OpenAPI paths are empty"
    assert openapi["components"]["schemas"], "OpenAPI schemas are empty"
    assert config_schema["$schema"].endswith("2020-12/schema")
    assert analytics_schema["additionalProperties"] is False
    Draft202012Validator.check_schema(config_schema)
    Draft202012Validator.check_schema(analytics_schema)
    Draft202012Validator(config_schema).validate(config_example)
    visit(openapi, openapi)

    assert ru.keys() == en.keys(), (
        f"i18n mismatch: missing EN={sorted(ru.keys() - en.keys())}, missing RU={sorted(en.keys() - ru.keys())}"
    )
    for key in sorted(ru):
        assert placeholders(ru[key]) == placeholders(en[key]), (
            f"placeholder mismatch for {key}: RU={placeholders(ru[key])}, EN={placeholders(en[key])}"
        )
        assert "<" not in ru[key] and "<" not in en[key], f"HTML in translation {key}"

    for relative in (
        "contracts/openapi.yaml",
        "contracts/config.schema.json",
        "contracts/config.example.yaml",
        "contracts/analytics-events.schema.json",
        "i18n/ru.json",
        "i18n/en.json",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for match in IPV4.findall(text):
            assert match.startswith(DOC_RANGES), f"literal address {match} in {relative}"

    print(
        "specs OK: "
        f"{len(openapi['paths'])} API paths, "
        f"{len(openapi['components']['schemas'])} schemas, "
        f"{len(ru)} i18n keys"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
