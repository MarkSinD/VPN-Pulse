from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import parse_qsl


class AuthenticationError(ValueError):
    pass


class MembershipChecker(Protocol):
    def role_for(self, telegram_user_id: int) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Identity:
    telegram_user_id: int
    role: str


def validate_telegram_init_data(
    init_data: str,
    *,
    bot_token: str,
    membership: MembershipChecker,
    now: datetime,
    max_age: timedelta = timedelta(minutes=5),
) -> Identity:
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as error:
        raise AuthenticationError("AUTH_MALFORMED") from error
    received_hash = values.pop("hash", None)
    if not received_hash:
        raise AuthenticationError("AUTH_HASH_MISSING")
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected):
        raise AuthenticationError("AUTH_INVALID")

    try:
        auth_date = datetime.fromtimestamp(int(values["auth_date"]), UTC)
        user = json.loads(values["user"])
        telegram_user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AuthenticationError("AUTH_MALFORMED") from error
    if auth_date > now + timedelta(seconds=30) or now - auth_date > max_age:
        raise AuthenticationError("AUTH_EXPIRED")

    role = membership.role_for(telegram_user_id)
    if role not in {"member", "admin"}:
        raise AuthenticationError("MEMBERSHIP_REQUIRED")
    return Identity(telegram_user_id, role)


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    identity: Identity
    expires_at: datetime


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, identity: Identity, now: datetime) -> Session:
        token = secrets.token_urlsafe(32)
        session = Session(token, identity, now + timedelta(minutes=30))
        self._sessions[self._key(token)] = session
        return session

    def get(self, token: str | None, now: datetime) -> Session | None:
        if not token:
            return None
        session = self._sessions.get(self._key(token))
        if session is None or session.expires_at <= now:
            return None
        return session

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(self._key(token), None)

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
