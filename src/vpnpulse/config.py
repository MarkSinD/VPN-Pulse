from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml


class ConfigurationError(ValueError):
    """Raised when a public configuration does not match the contract."""


def load_config(path: Path, schema_path: Path) -> dict[str, Any]:
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(config)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, jsonschema.ValidationError) as error:
        raise ConfigurationError(str(error)) from error
    return config
