import json

from vpnpulse.profile_delivery import TelegramProfileSender


def test_sender_builds_multipart_without_logging_or_persisting_profile():
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps({"ok": True}).encode()

    def opener(request, timeout):
        captured["request"] = request
        return Response()

    profile = "[Interface]\nPrivateKey = secret\n[Peer]\nPublicKey = server\n"
    assert TelegramProfileSender("token", opener=opener)(123, "vpn-s1.conf", profile) is True
    request = captured["request"]
    assert request.full_url.endswith("/bottoken/sendDocument")
    assert b'filename="vpn-s1.conf"' in request.data and profile.encode() in request.data
