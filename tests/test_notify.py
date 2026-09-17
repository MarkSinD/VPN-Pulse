"""`TelegramNotifier` — the real Bot API adapter on a fake transport.

What leaves the process is checked here: the URL (token from the file, read at send time), the
JSON body (chat per destination, the public text, silent delivery for the administrator) and how
the answers map to the queue's retry contract (`False` = try again later).
"""
import io
import json
import urllib.error
from pathlib import Path

import pytest

from vpnpulse.notify import MessageFormatter, TelegramNotifier

CONFIG = {
    "app": {"default_language": "ru", "languages": ["ru", "en"]},
    "servers": [{"id": "s2", "type": "awg-docker", "name": {"ru": "Сервер 2", "en": "Server 2"}, "country_code": "NL", "enabled": True, "recommended_priority": 20}],
}


class BotApi:
    """Records sendMessage requests; answers from a script (payload, HTTP error or a dead network)."""

    def __init__(self, answers=None) -> None:
        self.requests: list[tuple[str, dict, float | None]] = []
        self.answers = list(answers or [])

    def __call__(self, request, timeout=None):
        self.requests.append((request.full_url, json.loads(request.data), timeout))
        answer = self.answers.pop(0) if self.answers else {"ok": True, "result": {"message_id": len(self.requests)}}
        if isinstance(answer, Exception):
            raise answer

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Response(json.dumps(answer).encode())


@pytest.fixture
def token_file(tmp_path) -> Path:
    path = tmp_path / "bot.token"
    path.write_text("123456:ABC-first\n", encoding="utf-8")
    return path


def test_group_and_admin_messages_go_to_their_chats_with_public_text(token_file):
    api = BotApi()
    notifier = TelegramNotifier(MessageFormatter(CONFIG), token_file=token_file, group_chat_id="-1001234567890", admin_chat_id=99, opener=api)

    assert notifier("bot.unavailable", {"server_id": "s2", "state": "unavailable", "destination": "group"}) is True
    assert notifier("bot.degraded", {"server_id": "s2", "state": "degraded", "destination": "admin"}) is True

    (url_group, body_group, timeout), (url_admin, body_admin, _) = api.requests
    assert url_group == url_admin == "https://api.telegram.org/bot123456:ABC-first/sendMessage"
    assert timeout == 10.0
    assert body_group == {"chat_id": "-1001234567890", "text": body_group["text"], "disable_notification": False}
    assert body_admin == {"chat_id": 99, "text": body_admin["text"], "disable_notification": True}
    # only the public name travels: no server id, no host, no id of anybody
    assert "Сервер 2" in body_group["text"] and "s2" not in body_group["text"] and "s2" not in body_admin["text"]
    assert body_group["text"].startswith("🔴") and "Сервер 2" in body_admin["text"]


def test_admin_chat_defaults_to_the_group_and_english_texts_follow_the_config(token_file):
    api = BotApi()
    config = {**CONFIG, "app": {"default_language": "en", "languages": ["ru", "en"]}}
    notifier = TelegramNotifier(MessageFormatter(config), token_file=token_file, group_chat_id="-100777", opener=api)
    assert notifier("bot.recovered", {"server_id": "s2", "state": "operational", "destination": "admin"}) is True
    url, body, _ = api.requests[0]
    assert body["chat_id"] == "-100777" and body["disable_notification"] is True
    assert "Server 2" in body["text"] and "Сервер" not in body["text"]


def test_failures_report_false_so_the_queue_retries(token_file):
    api = BotApi(answers=[
        {"ok": False, "error_code": 429, "description": "Too Many Requests"},
        urllib.error.URLError("temporary failure in name resolution"),
        OSError("connection reset"),
        {"ok": True},
    ])
    notifier = TelegramNotifier(MessageFormatter(CONFIG), token_file=token_file, group_chat_id="-100777", opener=api)
    params = {"server_id": "s2", "state": "unavailable", "destination": "group"}
    assert notifier("bot.unavailable", params) is False  # Telegram said no
    assert notifier("bot.unavailable", params) is False  # no network
    assert notifier("bot.unavailable", params) is False  # socket died
    assert notifier("bot.unavailable", params) is True  # and then it went through
    assert len(api.requests) == 4


def test_token_is_read_at_send_time_and_never_cached(token_file):
    api = BotApi()
    notifier = TelegramNotifier(MessageFormatter(CONFIG), token_file=token_file, group_chat_id="-100777", opener=api)
    params = {"server_id": "s2", "state": "unavailable", "destination": "group"}
    assert notifier("bot.unavailable", params) is True
    token_file.write_text("123456:ABC-rotated\n", encoding="utf-8")  # the operator rotated the token; no restart
    assert notifier("bot.unavailable", params) is True
    assert [url.rsplit("/bot", 1)[1].split("/")[0] for url, _, _ in api.requests] == ["123456:ABC-first", "123456:ABC-rotated"]
    token_file.unlink()
    with pytest.raises(FileNotFoundError):
        notifier("bot.unavailable", params)  # a missing token is a configuration error, not a retry
