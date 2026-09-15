"""Read side of the API: everything the member and admin screens need, behind one protocol.

The HTTP layer (`vpnpulse.api.app`) never decides what a server looks like; it asks a ReadModel
with the caller's role and language (from `Accept-Language`). Three implementations exist:
`StatusOnlyReadModel` wraps the historical `status_provider` callable (status list only),
`vpnpulse.dev.FixtureReadModel` serves the demo scenarios, and
`vpnpulse.storage.SqliteReadModel` reads a real database.

Every returned dict must already be contract-shaped (see contracts/openapi.yaml); the app adds
nothing but transport concerns (sessions, problem details, cookies, response validation).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

LANGUAGES = ("ru", "en")


def pick_language(accept_language: str | None, default: str = "ru") -> str:
    """First supported language of an Accept-Language header, else the default."""
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag[:2] in LANGUAGES:
            return tag[:2]
    return default if default in LANGUAGES else "ru"


class ReadModelUnavailable(RuntimeError):
    """The read side cannot answer right now (storage or collector down); the API replies 503."""

    def __init__(self, code: str = "STATUS_UNAVAILABLE") -> None:
        super().__init__(code)
        self.code = code


class ReadModel(Protocol):
    def status(self, role: str, lang: str) -> dict: ...

    def server(self, server_id: str, role: str, lang: str) -> dict | None: ...

    def metrics(self, server_id: str, period: str) -> dict | None: ...

    def events(self, filter: str, cursor: str | None, limit: int, role: str, lang: str) -> dict: ...

    def help(self, lang: str) -> dict: ...

    def admin_server(self, server_id: str, lang: str) -> dict | None: ...

    def admin_probes(self) -> list[dict]: ...

    def admin_overview(self, lang: str) -> dict: ...

    def readiness(self) -> dict: ...


class StatusOnlyReadModel:
    """Adapter for a plain `status_provider(role) -> dict`: details are derived from the cards."""

    def __init__(self, status_provider: Callable[[str], dict], contact_url: str | None = None) -> None:
        self._status = status_provider
        self._contact_url = contact_url

    def status(self, role: str, lang: str = "ru") -> dict:
        return self._status(role)

    def _card(self, server_id: str, role: str) -> dict | None:
        return next((item for item in self._status(role).get("servers", []) if item["id"] == server_id), None)

    def server(self, server_id: str, role: str, lang: str = "ru") -> dict | None:
        card = self._card(server_id, role)
        if card is None:
            return None
        return {**card, "protocols": [], "checks": card.get("sources", [])}

    def metrics(self, server_id: str, period: str) -> dict | None:
        if self._card(server_id, "member") is None:
            return None
        return {"server_id": server_id, "period": period, "coverage": 0, "points": []}

    def events(self, filter: str, cursor: str | None, limit: int, role: str = "member", lang: str = "ru") -> dict:
        return {"items": [], "next_cursor": None}

    def help(self, lang: str = "ru") -> dict:
        return {
            "step_keys": ["help.step1", "help.step2", "help.step3", "help.step4"],
            "contact_available": self._contact_url is not None,
            "contact_url": self._contact_url,
        }

    def admin_server(self, server_id: str, lang: str = "ru") -> dict | None:
        detail = self.server(server_id, "admin", lang)
        if detail is None:
            return None
        return {**detail, "attention": [], "attention_items": [], "diagnostics": {}}

    def admin_probes(self) -> list[dict]:
        return []

    def admin_overview(self, lang: str = "ru") -> dict:
        return {"attention_items": [], "doctor": {"result": "ok", "items": []}, "next_command": None}

    def readiness(self) -> dict:
        return {
            "ready": True,
            "checks": {
                "database": {"ok": True, "age_seconds": None},
                "collector": {"ok": True, "age_seconds": 0},
                "bot": {"ok": True, "age_seconds": 0},
            },
        }
