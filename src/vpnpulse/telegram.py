"""Telegram-backed membership: who may open the Mini App.

`role_for` asks the Bot API whether the user is in the configured group (`getChatMember`); the
configured administrator id is `admin`. Answers are cached for a few minutes so a burst of
sessions costs one request, and a Telegram outage keeps the last known answer instead of
throwing everybody out. Only ids travel to Telegram — never names, never messages.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

log = logging.getLogger("vpnpulse.telegram")

MEMBER_STATUSES = {"creator", "administrator", "member"}


class TelegramMembership:
    def __init__(
        self,
        token: str,
        group_chat_id: str | int,
        admin_ids: set[int] | None = None,
        *,
        opener: Callable | None = None,
        cache_seconds: int = 300,
        timeout: float = 10.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.token = token
        self.group_chat_id = group_chat_id
        self.admin_ids = set(admin_ids or ())
        self.opener = opener or urllib.request.urlopen
        self.ttl = timedelta(seconds=cache_seconds)
        self.timeout = timeout
        self.now = now or (lambda: datetime.now(UTC))
        self._cache: dict[int, tuple[datetime, str | None]] = {}

    def _ask(self, user_id: int) -> str | None:
        query = urllib.parse.urlencode({"chat_id": self.group_chat_id, "user_id": user_id})
        request = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/getChatMember?{query}")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            if error.code in (400, 403):  # user not found in the chat or the bot is not in it
                return None
            raise
        if not payload.get("ok"):
            return None
        status = (payload.get("result") or {}).get("status")
        if status in MEMBER_STATUSES:
            return "member"
        if status == "restricted" and (payload.get("result") or {}).get("is_member"):
            return "member"
        return None

    def role_for(self, telegram_user_id: int) -> str | None:
        if telegram_user_id in self.admin_ids:
            return "admin"
        now = self.now()
        cached = self._cache.get(telegram_user_id)
        if cached and now - cached[0] < self.ttl:
            return cached[1]
        try:
            role = self._ask(telegram_user_id)
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("telegram membership check failed: %s", type(error).__name__)
            return cached[1] if cached else None  # keep the last answer through an outage; new faces wait
        self._cache[telegram_user_id] = (now, role)
        return role


class NoMembership:
    """No Telegram configured yet: nobody gets a session (health and static files still work)."""

    def role_for(self, telegram_user_id: int) -> str | None:
        return None
