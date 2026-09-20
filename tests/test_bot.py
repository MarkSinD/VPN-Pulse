"""The bot listener: /start → one Web App button in the installation's language, everything else ignored, offset advances, failures back off."""
import io
import json
import urllib.error

from vpnpulse.bot import TelegramBot

TOKEN = "123456789:AAExample-not-a-real-token-value"
APP = "https://monitor.example.org/app/mvp.html"


class FakeBotApi:
    def __init__(self, updates):
        self.updates = list(updates)
        self.calls = []
        self.fail = False

    def __call__(self, request, timeout=None):
        method = request.full_url.rsplit("/", 1)[1]
        body = json.loads(request.data or b"{}")
        self.calls.append((method, body))
        if self.fail:
            raise urllib.error.URLError("offline")
        if method == "getUpdates":
            offset = body.get("offset", 0)
            result = [u for u in self.updates if u["update_id"] >= offset]
        else:
            result = {"message_id": 1}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Response(json.dumps({"ok": True, "result": result}).encode())


def update(uid, text, chat_type="private", lang="ru", chat_id=555):
    return {"update_id": uid, "message": {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": chat_id, "language_code": lang}, "text": text}}


def test_start_gets_one_button_in_the_installations_language_and_nothing_else_is_answered():
    api = FakeBotApi([
        update(1, "/start"),
        update(2, "/start@connection_bot", lang="en", chat_id=777),
        update(3, "hello there"),
        update(4, "/start", chat_type="supergroup", chat_id=-100123),
        update(5, "/help", lang="de"),
    ])
    bot = TelegramBot(TOKEN, APP, opener=api, timeout=1)
    assert bot.poll_once() == 3
    sent = [b for m, b in api.calls if m == "sendMessage"]
    assert [s["chat_id"] for s in sent] == [555, 777, 555]
    assert all(s["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == APP for s in sent)
    # the phone's language does not matter: the community has one default, the app has the switch
    assert all("Нажмите кнопку" in s["text"] and s["reply_markup"]["inline_keyboard"][0][0]["text"] == "Открыть статус" for s in sent)
    assert all(s["disable_notification"] for s in sent)
    assert bot.offset == 6
    # the next poll asks from the offset and finds nothing new
    assert bot.poll_once() == 0
    assert api.calls[-1] == ("getUpdates", {"timeout": 1, "allowed_updates": ["message"], "offset": 6})


def test_an_english_installation_answers_in_english():
    api = FakeBotApi([update(1, "/start", lang="ru")])
    assert TelegramBot(TOKEN, APP, default_language="en", opener=api, timeout=1).poll_once() == 1
    sent = [b for m, b in api.calls if m == "sendMessage"][0]
    assert "Tap the button" in sent["text"] and sent["reply_markup"]["inline_keyboard"][0][0]["text"] == "Open the status"


def test_failures_back_off_and_stop_is_honoured():
    api = FakeBotApi([])
    bot = TelegramBot(TOKEN, APP, opener=api, timeout=1)
    api.fail = True
    naps = []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 3:
            bot.stop()

    bot.run_forever(sleep=nap)
    assert naps == [2, 4, 8]
