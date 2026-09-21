from pathlib import Path
import subprocess
import os


ROOT = Path(__file__).parents[1]
DEPLOY = ROOT / "deploy" / "pc-probe"


def test_manual_check_is_valid_shell_and_has_no_direct_fallback():
    script = DEPLOY / "pc-check.sh"
    bash = Path(r"C:\Program Files\Git\bin\bash.exe") if os.name == "nt" else Path("/bin/bash")
    subprocess.run([str(bash), "-n", str(script)], check=True)
    text = script.read_text(encoding="utf-8")
    assert 'ip netns add "$NS"' in text
    assert 'ip netns exec "$NS" ip route add default dev "$IFACE"' in text
    assert 'ip netns exec "$NS" curl' in text
    assert 'ip netns del "$NS"' in text


def test_manual_check_requires_expected_exit_and_checks_all_three_results():
    text = (DEPLOY / "pc-check.sh").read_text(encoding="utf-8")
    assert "EXPECTED_EXIT" in text and '"$tunnel_ip" = "$EXPECTED_EXIT"' in text
    for check in ("control_internet", "handshake", "https"):
        assert f'"check":"{check}"' in text


def test_hyper_v_provisioning_is_key_only_bounded_and_non_destructive():
    script = (DEPLOY / "new-probe-vm.ps1").read_text(encoding="utf-8")
    seed = (DEPLOY / "cloud-init" / "user-data.example").read_text(encoding="utf-8")
    assert "Get-VMSwitch -Name $SwitchName" in script
    assert "New-VMSwitch" not in script
    assert "already exists; this script never replaces" in script
    assert "MemoryBytes = 1GB" in script and "Set-VMProcessor" in script
    assert "AutomaticStartAction Start" in script and "AutomaticStopAction Save" in script
    assert "ManagementSwitchName" in script
    assert "route-metric: 10" in script and "ManagementAddress" in script
    assert "-StaticMacAddress" in script
    assert "REPLACE_WITH_NETWORK_SETUP" in script and "bootcmd:" in script and "netplan apply" in script
    assert "lock_passwd: true" in seed and "ssh_pwauth: false" in seed
