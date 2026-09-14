from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


REDACTED_KEYS = {
    "authorization",
    "init_data",
    "password",
    "private_key",
    "probe_token",
    "psk",
    "token",
}


def _safe(value, key: str | None = None):
    if key and key.lower() in REDACTED_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _safe(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": getattr(record, "service", "vpnpulse"),
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in ("trace_id", "duration_ms", "result", "details"):
            if hasattr(record, field):
                payload[field] = _safe(getattr(record, field), field)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
