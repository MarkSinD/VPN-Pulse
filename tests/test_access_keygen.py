import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]


def test_javascript_x25519_matches_cryptography_and_destroys_secret():
    private = bytes(range(32))
    expected = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.add_script_tag(path=ROOT / "web" / "src" / "access-keygen.js")
        actual = page.evaluate("value => Array.from(VpnPulseAccessKeys.derivePublicKey(new Uint8Array(value)))", list(private))
        pair = page.evaluate("""() => {
          const pair = VpnPulseAccessKeys.generate();
          const publicKey = pair.publicKey;
          const config = pair.buildConfig({address:'fd00::100/128',dns:['2001:db8::53'],serverPublicKey:'server-key',presharedKey:'psk',endpoint:'example.invalid:1234',HeaderProtectionKey:'header-key'});
          pair.destroy();
          let destroyed = false; try { pair.buildConfig({}); } catch (_) { destroyed = true; }
          return {publicKey, config, destroyed};
        }""")
        browser.close()
    assert bytes(actual) == expected
    assert len(base64.b64decode(pair["publicKey"])) == 32
    assert "PrivateKey = " in pair["config"] and "DNS = 2001:db8::53" in pair["config"]
    assert "HeaderProtectionKey = header-key" in pair["config"] and pair["destroyed"] is True
