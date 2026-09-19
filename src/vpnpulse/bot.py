"""The bot's conversational side: answer `/start` with a button that opens the Mini App.

Everything else — outage and recovery messages — is sent by the monitoring loop through the
notification queue; this process only listens. It is the single `getUpdates` consumer of the token
(a second one would steal updates), reads only private-chat messages, replies to `/start` (and
`/help`) in the sender's language with one Web App button, and ignores every other update. It
stores nothing: no user ids, no texts, no counters.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from vpnpulse.i18n import Translator

log = logging.getLogger("vpnpulse.bot")

COMMANDS = ("/start", "/help")


class TelegramBot:
    def __init__(
        self,
        token: str,
        app_url: str,
        *,
        default_language: str = "ru",
        translator: Translator | None = None,
        opener: Callable | None = None,
        timeout: int = 50,
    ) -> None:
        self.token = token
        self.app_url = app_url
        self.default_language = default_language
        self.i18n = translator or Translator()
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.offset: int | None = None
        self._stop = False

    # ---------- Bot API ----------
    def _call(self, method: str, **params) -> dict | None:
        body = json.dumps(params).encode()
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/{method}", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self.opener(request, timeout=self.timeout + 10) as response:
                payload = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            log.warning("bot api %s: http %s", method, error.code)
            return None
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("bot api %s failed: %s", method, type(error).__name__)
            return None
        if not payload.get("ok"):
            log.warning("bot api %s: %s", method, str(payload.get("description", ""))[:80])
            return None
        return payload.get("result")

    # ---------- one poll ----------
    def poll_once(self) -> int:
        """Fetch pending updates, answer the commands, advance the offset. Returns the number of replies."""
        params = {"timeout": self.timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._call("getUpdates", **params)
        if updates is None:
            raise ConnectionError("getUpdates failed")  # run_forever backs off instead of spinning
        if not updates:
            return 0
        replies = 0
        for update in updates:
            self.offset = int(update.get("update_id", 0)) + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            text = (message.get("text") or "").strip()
            if chat.get("type") != "private" or not text:
                continue
            command = text.split()[0].split("@")[0].lower()
            if command not in COMMANDS:
                continue
            lang = (message.get("from") or {}).get("language_code", "")
            lang = "en" if str(lang).lower().startswith("en") else ("ru" if str(lang).lower().startswith("ru") else self.default_language)
            if self.reply(chat["id"], lang):
                replies += 1
        return replies

    def reply(self, chat_id: int, lang: str) -> bool:
        keyboard = {"inline_keyboard": [[{"text": self.i18n.t(lang, "bot.open"), "web_app": {"url": self.app_url}}]]}
        return self._call("sendMessage", chat_id=chat_id, text=self.i18n.t(lang, "bot.start"), reply_markup=keyboard, disable_notification=True) is not None

    # ---------- the loop ----------
    def stop(self) -> None:
        self._stop = True

    def run_forever(self, *, sleep: Callable[[float], None] = time.sleep) -> None:
        failures = 0
        while not self._stop:
            try:
                self.poll_once()
                failures = 0
            except Exception as error:  # noqa: BLE001 - keep listening; the failure type is logged
                failures = min(failures + 1, 6)
                log.error("bot poll failed: %s", type(error).__name__)
                sleep(min(60, 2 ** failures))
