import json
from pathlib import Path

import pytest

from vpnpulse.config import ConfigurationError, load_config


def _contracts_dir():
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "openapi.yaml").exists():
            return parent / "contracts"
    raise FileNotFoundError("contracts/ not found above tests/")

SCHEMA = _contracts_dir() / "config.schema.json"


def valid_config():
    return {
        "version": 1,
        "app": {"default_language": "ru", "languages": ["ru", "en"], "timezone": "UTC"},
        "servers": [
            {
                "id": "server-1",
                "type": "awg-host",
                "name": {"ru": "Сервер 1", "en": "Server 1"},
                "country_code": "LV",
                "enabled": True,
                "collector_ref": "collector-one"
            }
        ],
        "monitoring": {
            "collection_interval_seconds": 60,
            "pc_target_interval_seconds": 60,
            "probe_deadline_seconds": 20,
            "confirmations": 2,
            "freshness_seconds": 180
        },
        "retention": {
            "observations_days": 7,
            "aggregates_days": 90,
            "events_days": 180,
            "analytics_raw_days": 30,
            "audit_days": 365
        }
    }


def test_valid_generic_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(json.dumps(valid_config(), ensure_ascii=False), encoding="utf-8")
    assert load_config(path, SCHEMA)["servers"][0]["id"] == "server-1"


def test_unknown_config_field_is_rejected(tmp_path):
    config = valid_config()
    config["secret"] = "must-not-be-here"
    path = tmp_path / "config.yaml"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(path, SCHEMA)
