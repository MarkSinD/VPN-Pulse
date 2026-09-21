# Hyper-V PC probe reference setup

This directory supports the manual R-17 route-isolation spike. It is experimental until the route
matrix is completed on the target hardware, and it does not enroll a persistent
agent. Run `new-probe-vm.ps1` from elevated PowerShell with an existing Hyper-V switch and a fresh
SSH public key. The script downloads the official Ubuntu 24.04 Azure VHD, creates a Generation 2 VM
with 1 GiB RAM and one vCPU, attaches a NoCloud `CIDATA` disk, disables checkpoints, and configures
automatic start/save.

```powershell
.\new-probe-vm.ps1 -SwitchName ExternalWiFi -ManagementSwitchName 'Default Switch' `
  -ManagementAddress '192.0.2.10/24' `
  -AuthorizedKey (Get-Content .\probe_vm_ed25519.pub -Raw)
```

The script refuses to replace an existing VM or create a switch. Creating an external switch can
briefly disconnect the host and therefore remains an explicit administrator action. Wi-Fi adapters
and drivers differ: first prove the guest obtains a LAN DHCP address and keeps the home exit while
the host VPN is active.

`ManagementSwitchName` is optional. When supplied, `ManagementAddress` must be an unused static CIDR
on that switch's host subnet. The VM starts with a second adapter for SSH, without a gateway. The
generated NoCloud network configuration gives the external DHCP route metric 10, so probe traffic
prefers the independent external path. Verify this inside the guest with
`ip -4 route`; the management switch is an access path, not evidence of route isolation.

The Ubuntu Azure VHD can vary in how it discovers a NoCloud `CIDATA` disk outside Azure. Confirm that
the `probe` account exists and `cloud-init status --wait` completes before adding any server peers.

Inside the guest, install a userspace AmneziaWG engine matching the target servers and create one
profile per target. `pc-check.sh PROFILE TARGET_ID EXPECTED_EXIT_IP [NAMESPACE]` creates a namespace
with no physical default route, moves one userspace interface into it, adds the tunnel-only default
route, then checks a fresh handshake, HTTPS 204, and the expected VPN exit. Its JSON output resembles
one normalized probe result. Profiles and expected addresses are private deployment inputs.
