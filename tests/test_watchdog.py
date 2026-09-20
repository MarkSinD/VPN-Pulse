from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "deploy/watchdog/vpn-pulse-watchdog"
loader = importlib.machinery.SourceFileLoader("vpn_pulse_watchdog", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
watchdog = importlib.util.module_from_spec(spec); loader.exec_module(watchdog)


class Response:
    def __init__(self, payload, status=200): self.payload, self.status = payload, status
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit): return json.dumps(self.payload).encode()


class Opener:
    def __init__(self, ready=True, telegram_ok=True):
        self.ready = ready
        self.telegram_ok = telegram_ok
        self.messages = []
    def open(self, request, timeout=10):
        if request.full_url.endswith("/health/ready"):
            if isinstance(self.ready, Exception): raise self.ready
            return Response({"ready": self.ready})
        body = __import__("urllib.parse").parse.parse_qs(request.data.decode())
        self.messages.append(body)
        return Response({"ok": self.telegram_ok})


def config(tmp_path):
    token = tmp_path / "token"; token.write_text("CANARY-WATCHDOG-TOKEN")
    return {"URL": "https://monitor.example.org", "ADMIN_CHAT_ID": "123456789", "TOKEN_FILE": str(token), "LANG": "ru", "STATE_DIR": str(tmp_path / "state")}


def test_two_failures_are_quiet_and_third_alerts(tmp_path):
    cfg, opener = config(tmp_path), Opener(False)
    assert watchdog.tick(cfg, now=0, opener=opener).startswith("fail")
    assert watchdog.tick(cfg, now=60, opener=opener).startswith("fail") and not opener.messages
    assert watchdog.tick(cfg, now=120, opener=opener) == "alert" and len(opener.messages) == 1
    assert "Приложение статуса" in opener.messages[0]["text"][0]
    assert "disable_notification" not in opener.messages[0]


def test_fourth_failure_does_not_repeat_alert(tmp_path):
    cfg, opener = config(tmp_path), Opener(False)
    for when in (0, 60, 120): watchdog.tick(cfg, now=when, opener=opener)
    assert watchdog.tick(cfg, now=180, opener=opener).startswith("fail") and len(opener.messages) == 1


def test_repeat_alert_waits_six_hours(tmp_path):
    cfg, opener = config(tmp_path), Opener(False)
    for when in (0, 60, 120): watchdog.tick(cfg, now=when, opener=opener)
    assert watchdog.tick(cfg, now=120 + watchdog.SIX_HOURS, opener=opener) == "alert"
    assert len(opener.messages) == 2


def test_recovery_sends_once_and_resets(tmp_path):
    cfg, opener = config(tmp_path), Opener(False)
    for when in (0, 60, 120): watchdog.tick(cfg, now=when, opener=opener)
    opener.ready = True
    assert watchdog.tick(cfg, now=180, opener=opener) == "recovered"
    assert "снова отвечает" in opener.messages[-1]["text"][0]
    assert watchdog.tick(cfg, now=240, opener=opener) == "ok" and len(opener.messages) == 2


def test_not_ready_for_six_minutes_alerts(tmp_path):
    cfg, opener = config(tmp_path), Opener(False)
    assert watchdog.tick(cfg, now=0, opener=opener).startswith("fail")
    state = watchdog.load_state(Path(cfg["STATE_DIR"]) / "state.json")
    state["consecutive_failures"] = 1; watchdog.save_state(Path(cfg["STATE_DIR"]) / "state.json", state)
    assert watchdog.tick(cfg, now=360, opener=opener) == "alert"


def test_telegram_failure_is_retried(tmp_path):
    cfg, opener = config(tmp_path), Opener(False, telegram_ok=False)
    for when in (0, 60): watchdog.tick(cfg, now=when, opener=opener)
    assert watchdog.tick(cfg, now=120, opener=opener) == "fail telegram"
    assert watchdog.load_state(Path(cfg["STATE_DIR"]) / "state.json")["alerted"] is False
    opener.telegram_ok = True
    assert watchdog.tick(cfg, now=180, opener=opener) == "alert"


def test_config_defaults_and_rejects_invalid_language(tmp_path):
    path = tmp_path / "config"
    path.write_text("URL=https://monitor.example.org\nADMIN_CHAT_ID=123\n")
    assert watchdog.read_config(str(path))["LANG"] == "ru"
    path.write_text("URL=https://monitor.example.org\nADMIN_CHAT_ID=123\nLANG=xx\n")
    try: watchdog.read_config(str(path)); assert False
    except ValueError as error: assert "LANG" in str(error)
