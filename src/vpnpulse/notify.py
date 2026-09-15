"""Messengers for the notification queue: a recording fake, a console printer and a Telegram sender.

Messages are built from the RU/EN dictionaries (`bot.*` keys) and the public server names, so
a notification never carries hosts, addresses or member data. `TelegramNotifier` talks to the Bot
API with the standard library only and reports failures as `False` so the queue retries later.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from vpnpulse.i18n import Translator

log = logging.getLogger("vpnpulse.notify")


class MessageFormatter:
    def __init__(self, config: dict, translator: Translator | None = None) -> None:
        self.config = config
        self.i18n = translator or Translator()
        self.lang = (config.get("app") or {}).get("default_language", "ru")

    def server_name(self, server_id: str) -> str:
        for s in self.config.get("servers", []):
            if s["id"] == server_id:
                name = s.get("name")
                return name.get(self.lang) or name.get("ru") if isinstance(name, dict) else str(name)
        return server_id

    def text(self, template_key: str, params: dict) -> str:
        return self.i18n.t(self.lang, template_key, server=self.server_name(params.get("server_id", "")), state=self.i18n.t(self.lang, "status.state." + params.get("state", "unknown")))


class FakeNotifier:
    """Records what would have been sent; `fail_times` simulates an unavailable messenger."""

    def __init__(self, formatter: MessageFormatter | None = None, fail_times: int = 0) -> None:
        self.formatter = formatter
        self.sent: list[tuple[str, str, dict]] = []
        self.fail_times = fail_times

    def __call__(self, template_key: str, params: dict) -> bool:
        if self.fail_times > 0:
            self.fail_times -= 1
            return False
        text = self.formatter.text(template_key, params) if self.formatter else template_key
        self.sent.append((template_key, text, params))
        return True


class ConsoleNotifier:
    """Prints what would be sent — `vpn-pulse run` without Telegram credentials (demo, first runs)."""

    def __init__(self, formatter: MessageFormatter, out: Callable[[str], None] | None = None) -> None:
        self.formatter = formatter
        self.out = out or (lambda line: print(line, flush=True))

    def __call__(self, template_key: str, params: dict) -> bool:
        self.out(f"[{params.get('destination', 'group')}] {self.formatter.text(template_key, params)}")
        return True


class TelegramNotifier:
    """Sends queue messages to the group (members) or the administrator chat via the Bot API."""

    def __init__(self, formatter: MessageFormatter, *, token_file: Path, group_chat_id: str | int, admin_chat_id: str | int | None = None, opener: Callable | None = None, timeout: float = 10.0) -> None:
        self.formatter = formatter
        self.token_file = Path(token_file)
        self.group_chat_id = group_chat_id
        self.admin_chat_id = admin_chat_id or group_chat_id
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout

    def _token(self) -> str:
        return self.token_file.read_text(encoding="utf-8").strip()

    def __call__(self, template_key: str, params: dict) -> bool:
        destination = params.get("destination", "group")
        chat_id = self.admin_chat_id if destination == "admin" else self.group_chat_id
        body = json.dumps({"chat_id": chat_id, "text": self.formatter.text(template_key, params), "disable_notification": destination == "admin"}).encode()
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self._token()}/sendMessage", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read() or b"{}")
            return bool(payload.get("ok", True))
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("telegram send failed: %s", type(error).__name__)
            return False
