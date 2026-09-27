# Testing the PC probe on a second Windows laptop

Source code travels through GitHub. The prepared VM travels separately because its image contains
private VPN profiles and must never be committed, uploaded to a release, or shared through a public link.

## Files

Clone the test branch from the project's GitHub repository. Transfer the private bundle by USB or a
trusted local-network share. It contains the prepared VHDX, VM-only SSH key and settings file. Keep
that directory private and delete the transfer copy after the test is accepted.

## Import and ON test

Requirements: Windows 11 Pro, Hyper-V enabled, at least 4 GB free, Git for Windows, and a physical
network adapter suitable for an External Hyper-V switch.

1. Connect the laptop to the intended home network and turn its normal VPN **on**.
2. Open PowerShell as Administrator. Read the private settings and run:

```powershell
& .\deploy\pc-probe\import-probe-vm.ps1 `
  -VhdPath '<private-bundle>\VPNPulseProbe-os.vhdx' `
  -ExternalAdapter '<adapter name>' `
  -ExternalMac '<external MAC from settings>' `
  -ManagementMac '<management MAC from settings>' `
  -ManagementHostAddress '<management host address from settings>'
```

The network may disconnect for 5-15 seconds while the External switch is created. Leave the VPN on
for three minutes. The VM runs the three-target matrix itself; Windows does not need SSH access.

## Collect and OFF test

1. Turn the host VPN off and wait five seconds.
2. Run the collector with the private SSH key and management VM address from the settings file:

```powershell
& .\deploy\pc-probe\collect-probe-results.ps1 `
  -SshKey '<private-bundle>\id_ed25519' `
  -ManagementAddress '<management VM address from settings>' `
  -Label on
```

3. Keep the VPN off and run the OFF matrix:

```powershell
& 'C:\Program Files\Git\usr\bin\ssh.exe' -F NUL -i '<private-bundle>\id_ed25519' `
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL `
  probe@'<management VM address>' 'sudo /usr/local/sbin/run-r17-matrix off'
```

4. Copy the OFF results with the same collector:

```powershell
& .\deploy\pc-probe\collect-probe-results.ps1 `
  -SshKey '<private-bundle>\id_ed25519' `
  -ManagementAddress '<management VM address from settings>' `
  -Label off
```

5. Turn the VPN on again and return both result sets to the owner. A successful matrix has three JSON
   rows; every row reports successful handshake, HTTPS and `route_verified=true`.

Do not publish the VHDX, SSH key, settings, raw profiles, or result files containing real addresses.
