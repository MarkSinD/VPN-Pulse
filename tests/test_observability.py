import json
import logging

from vpnpulse.observability import JsonFormatter


def test_json_log_redacts_nested_secret_fields():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "fallback", (), None)
    record.event = "probe_report"
    record.trace_id = "trace-123"
    record.details = {"token": "secret", "nested": {"private_key": "secret", "ok": True}}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "probe_report"
    assert payload["details"]["token"] == "[REDACTED]"
    assert payload["details"]["nested"]["private_key"] == "[REDACTED]"
    assert payload["details"]["nested"]["ok"] is True
