import json
import sys

import pytest

from vpnpulse.provisioner import ProvisionerError, execute, parse_awg_config, validate_clients_table, validate_request

KEY1 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
KEY2 = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA="
PSK = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCA="


def fixture(tmp_path, *, clients=False):
    config = tmp_path / "awg0.conf"
    config.write_text(f"""[Interface]\nPrivateKey = secret\n[Peer]\nPublicKey = {KEY1}\nPresharedKey = {PSK}\nAllowedIPs = fd00::1/128\n""", encoding="utf-8")
    result = {"persistent_config": str(config), "writes_enabled": False}
    if clients:
        table = tmp_path / "clientsTable"
        table.write_text(json.dumps([{"clientId": KEY1}]), encoding="utf-8")
        result["clients_table"] = str(table)
    return result


def test_inspect_returns_only_counts_and_fingerprints(tmp_path):
    result = execute({"operation": "inspect"}, fixture(tmp_path, clients=True))
    assert result["peer_count"] == 1 and result["clients_table_count"] == 1
    assert "secret" not in json.dumps(result) and "AAAAAAAA" not in json.dumps(result)


def test_inspect_compares_persistent_and_live_peers(tmp_path):
    live = tmp_path / "inspect.py"
    live.write_text(
        "import sys\n"
        f"print('{KEY1}\\tpublic\\t1\\toff')\n"
        f"print('{KEY1}\\tpsk\\tendpoint\\tfd00::1/128\\t0\\t0\\t0\\t25')\n",
        encoding="utf-8",
    )
    cfg = fixture(tmp_path)
    cfg["inspect_command"] = [sys.executable, str(live)]
    result = execute({"operation": "inspect"}, cfg)
    assert result["live_checked"] is True
    assert result["live_peer_count"] == 1
    assert result["persistent_live_match"] is True


def test_issue_and_revoke_are_dry_run_when_writes_disabled(tmp_path):
    cfg = fixture(tmp_path)
    issue = execute({"operation": "issue", "public_key": KEY2, "allowed_ip": "fd00::2/128", "idempotency_key": "issue-1", "dry_run": True}, cfg)
    revoke = execute({"operation": "revoke", "public_key": KEY1, "idempotency_key": "revoke-1", "dry_run": True}, cfg)
    assert issue["would_change"] is True and revoke["would_change"] is True
    assert "fd00::2" not in cfg["persistent_config"]


def test_request_rejects_injection_paths_and_networks():
    with pytest.raises(ProvisionerError):
        validate_request({"operation": "inspect", "path": "/tmp/other"})
    with pytest.raises(ProvisionerError):
        validate_request({"operation": "issue", "public_key": KEY2, "allowed_ip": "fd00::/64", "idempotency_key": "bad-net", "dry_run": True})
    with pytest.raises(ProvisionerError):
        validate_request({"operation": "revoke", "public_key": "$(id)", "dry_run": True})


def test_parsers_fail_closed():
    with pytest.raises(ProvisionerError):
        parse_awg_config("[Peer]\nAllowedIPs = fd00::1/128")
    with pytest.raises(ProvisionerError):
        validate_clients_table({"not": "a list"})
    with pytest.raises(ProvisionerError, match="duplicate"):
        validate_clients_table([{"clientId": KEY1}, {"clientId": KEY1}])


def test_live_issue_replay_and_revoke_are_atomic(tmp_path):
    live = tmp_path / "live.py"
    live.write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text(' '.join(sys.argv[2:]))\n", encoding="utf-8")
    marker = tmp_path / "live.txt"
    cfg = fixture(tmp_path, clients=True)
    cfg.update({"writes_enabled": True, "live_command": [sys.executable, str(live), str(marker)],
                "journal_file": str(tmp_path / "journal.json")})
    request = {"operation": "issue", "public_key": KEY2, "allowed_ip": "fd00::2/128",
               "idempotency_key": "live-issue", "dry_run": False}
    issued = execute(request, cfg)
    assert issued["changed"] is True and issued["preshared_key"]
    assert KEY2 in (tmp_path / "awg0.conf").read_text(encoding="utf-8")
    assert any(row["clientId"] == KEY2 for row in json.loads((tmp_path / "clientsTable").read_text(encoding="utf-8")))
    replay = execute(request, cfg)
    assert replay["replayed"] is True and "preshared_key" not in replay
    assert issued["preshared_key"] not in (tmp_path / "journal.json").read_text(encoding="utf-8")
    revoked = execute({"operation": "revoke", "public_key": KEY2, "idempotency_key": "live-revoke", "dry_run": False}, cfg)
    assert revoked["changed"] is True and KEY2 not in (tmp_path / "awg0.conf").read_text(encoding="utf-8")
    assert all(row["clientId"] != KEY2 for row in json.loads((tmp_path / "clientsTable").read_text(encoding="utf-8")))


def test_failed_live_apply_restores_persistent_files(tmp_path):
    fail = tmp_path / "fail.py"; fail.write_text("raise SystemExit(3)\n", encoding="utf-8")
    cfg = fixture(tmp_path, clients=True)
    before_config = (tmp_path / "awg0.conf").read_text(encoding="utf-8")
    before_table = (tmp_path / "clientsTable").read_text(encoding="utf-8")
    cfg.update({"writes_enabled": True, "live_command": [sys.executable, str(fail)],
                "journal_file": str(tmp_path / "journal.json")})
    with pytest.raises(ProvisionerError, match="live apply failed"):
        execute({"operation": "issue", "public_key": KEY2, "allowed_ip": "fd00::2/128",
                 "idempotency_key": "fail-issue", "dry_run": False}, cfg)
    assert (tmp_path / "awg0.conf").read_text(encoding="utf-8") == before_config
    assert (tmp_path / "clientsTable").read_text(encoding="utf-8") == before_table
