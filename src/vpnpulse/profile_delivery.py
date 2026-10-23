"""One-shot delivery of a client-built profile through Telegram."""
from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request
from collections.abc import Callable

log = logging.getLogger(__name__)


class TelegramProfileSender:
    def __init__(self, token: str, *, opener: Callable | None = None, timeout: float = 15.0) -> None:
        self.token = token
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout

    def __call__(self, telegram_user_id: int, filename: str, content: str) -> bool:
        boundary = "----VPNPulse" + secrets.token_hex(12)
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{telegram_user_id}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\nVPN-профиль готов. Импортируйте файл в AmneziaVPN.\r\n".encode("utf-8"),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
            content.encode("utf-8"),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendDocument", data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                result = json.loads(response.read() or b"{}")
            return result.get("ok") is True
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("telegram profile delivery failed: %s", type(error).__name__)
            return False
