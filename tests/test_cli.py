"""`vpn-pulse run` from the command line: one demo run, one live run without collectors yet."""
from pathlib import Path

import pytest

from vpnpulse.cli import main
from vpnpulse.storage import connect

ROOT = Path(__file__).parents[1]


def test_run_demo_once_writes_snapshots_and_prints_transitions(tmp_path, capsys):
    db = tmp_path / "demo.sqlite3"
    assert main(["run", "--demo", "--once", "--db", str(db), "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "s1: unknown → operational" in out and "s3: unknown → operational" in out
    connection = connect(db)
    assert connection.execute("SELECT count(*) FROM state_snapshots WHERE state = 'operational'").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM probes WHERE kind IN ('pc', 'android', 'abroad')").fetchone()[0] == 3
    assert connection.execute("SELECT result FROM collection_runs").fetchone()[0] == "ok"
    # a second invocation is a restart: nothing changes, nothing is repeated
    assert main(["run", "--demo", "--once", "--db", str(db), "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert connection.execute("SELECT count(*) FROM state_transitions").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM notification_queue").fetchone()[0] == 0


def test_run_with_a_real_config_and_no_collectors_stays_silent(tmp_path, capsys):
    db = tmp_path / "live.sqlite3"
    assert main(["run", "--config", str(ROOT / "contracts" / "config.example.yaml"), "--once", "--db", str(db), "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    connection = connect(db)
    assert [r[0] for r in connection.execute("SELECT id FROM servers ORDER BY display_order").fetchall()] == ["primary-vpn", "backup-vpn"]
    # no observations yet → unknown, which is not a change from the start, so no transition and no message
    assert connection.execute("SELECT count(*) FROM state_snapshots WHERE state = 'unknown'").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM state_transitions").fetchone()[0] == 0


def test_run_requires_config_or_demo(tmp_path):
    with pytest.raises(SystemExit):
        main(["run", "--once", "--db", str(tmp_path / "x.sqlite3"), "--quiet"])
