[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$VMName = "VPNPulseProbe",
    [Parameter(Mandatory)][string]$SwitchName,
    [string]$ManagementSwitchName,
    [string]$ManagementAddress,
    [Parameter(Mandatory)][string]$AuthorizedKey,
    [string]$VMRoot = "$env:PUBLIC\Documents\Hyper-V\VPNPulseProbe",
    [string]$ImageUrl = "https://cloud-images.ubuntu.com/releases/server/24.04/release/ubuntu-24.04-server-cloudimg-amd64-azure.vhd.tar.gz",
    [UInt64]$MemoryBytes = 1GB,
    [UInt64]$DiskBytes = 12GB
)

$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session."
}
if (-not (Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue)) {
    throw "Hyper-V switch '$SwitchName' does not exist. Create or select it explicitly first."
}
if ($ManagementSwitchName) {
    if ($ManagementSwitchName -eq $SwitchName) {
        throw 'ManagementSwitchName must differ from SwitchName.'
    }
    if (-not (Get-VMSwitch -Name $ManagementSwitchName -ErrorAction SilentlyContinue)) {
        throw "Hyper-V management switch '$ManagementSwitchName' does not exist."
    }
    if ($ManagementAddress -notmatch '^\d{1,3}(\.\d{1,3}){3}/([1-9]|[12]\d|3[0-2])$') {
        throw 'ManagementAddress must be an IPv4 CIDR when ManagementSwitchName is used.'
    }
} elseif ($ManagementAddress) {
    throw 'ManagementAddress requires ManagementSwitchName.'
}
if ($AuthorizedKey -notmatch '^ssh-(ed25519|rsa|ecdsa-[^ ]+)\s+\S+') {
    throw "AuthorizedKey must be one OpenSSH public key."
}
if (Get-VM -Name $VMName -ErrorAction SilentlyContinue) {
    throw "VM '$VMName' already exists; this script never replaces a VM."
}

$archive = Join-Path $VMRoot "ubuntu-cloud.vhd.tar.gz"
$expanded = Join-Path $VMRoot "image"
$sourceVhd = Join-Path $expanded "ubuntu-24.04-server-cloudimg-amd64-azure.vhd"
$osDisk = Join-Path $VMRoot "$VMName-os.vhdx"
$seedDisk = Join-Path $VMRoot "$VMName-cidata.vhdx"

function New-UniqueHyperVMac {
    do {
        $candidate = '00155D' + [guid]::NewGuid().ToString('N').Substring(0, 6).ToUpperInvariant()
        $used = Get-VMNetworkAdapter -All -ErrorAction SilentlyContinue |
            Where-Object MacAddress -eq $candidate
    } while ($used)
    return $candidate
}

New-Item -ItemType Directory -Force -Path $VMRoot,$expanded | Out-Null
if (-not (Test-Path $archive)) {
    Invoke-WebRequest -Uri $ImageUrl -OutFile $archive
}
if (-not (Test-Path $sourceVhd)) {
    tar.exe -xzf $archive -C $expanded
    $found = Get-ChildItem $expanded -Filter '*azure.vhd' | Select-Object -First 1
    if (-not $found) { throw "The archive contains no Azure VHD." }
    if ($found.FullName -ne $sourceVhd) { Move-Item $found.FullName $sourceVhd }
}
# Windows tar preserves the cloud image's sparse layout. Hyper-V refuses to
# convert a sparse VHD, so materialize its ranges before calling Convert-VHD.
$sparseResult = & fsutil.exe sparse setflag $sourceVhd 0 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not clear the sparse attribute on the source VHD: $sparseResult"
}
Convert-VHD -Path $sourceVhd -DestinationPath $osDisk -VHDType Dynamic
Resize-VHD -Path $osDisk -SizeBytes $DiskBytes

New-VM -Name $VMName -Generation 2 -MemoryStartupBytes $MemoryBytes -VHDPath $osDisk -SwitchName $SwitchName | Out-Null
Set-VMNetworkAdapter -VMName $VMName -Name 'Network Adapter' -StaticMacAddress (New-UniqueHyperVMac)
if ($ManagementSwitchName) {
    Add-VMNetworkAdapter -VMName $VMName -Name Management -SwitchName $ManagementSwitchName `
        -StaticMacAddress (New-UniqueHyperVMac)
}

New-VHD -Path $seedDisk -Dynamic -SizeBytes 64MB | Out-Null
$mounted = Mount-VHD -Path $seedDisk -Passthru
try {
    $disk = $mounted | Get-Disk
    Initialize-Disk -Number $disk.Number -PartitionStyle MBR | Out-Null
    $partition = New-Partition -DiskNumber $disk.Number -UseMaximumSize -AssignDriveLetter
    Format-Volume -Partition $partition -FileSystem FAT -NewFileSystemLabel CIDATA -Confirm:$false | Out-Null
    $drive = ($partition | Get-Volume).DriveLetter + ':'
    $template = Get-Content (Join-Path $PSScriptRoot 'cloud-init\user-data.example') -Raw
    $userData = $template.Replace('ssh-ed25519 REPLACE_WITH_PUBLIC_KEY vpn-pulse-probe', $AuthorizedKey.Trim())
    $networkSetup = @"
runcmd:
  - [systemctl, enable, --now, ssh]
"@
    if ($ManagementSwitchName) {
        $externalMac = (Get-VMNetworkAdapter -VMName $VMName -Name 'Network Adapter').MacAddress -replace '(..)(?!$)', '$1:'
        $managementMac = (Get-VMNetworkAdapter -VMName $VMName -Name Management).MacAddress -replace '(..)(?!$)', '$1:'
        $netplan = @"
network:
  version: 2
  ethernets:
    external:
      match:
        macaddress: "$($externalMac.ToLowerInvariant())"
      set-name: external
      dhcp4: true
      dhcp4-overrides:
        route-metric: 10
    management:
      match:
        macaddress: "$($managementMac.ToLowerInvariant())"
      set-name: management
      dhcp4: false
      addresses: [$ManagementAddress]
"@
        $netplanBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($netplan))
        $networkSetup = @"
bootcmd:
  - [sh, -c, "printf '%s' '$netplanBase64' | base64 -d > /etc/netplan/60-vpn-pulse.yaml && chmod 0600 /etc/netplan/60-vpn-pulse.yaml && netplan apply"]
runcmd:
  - [systemctl, enable, --now, ssh]
"@
    }
    $userData = $userData.Replace('# REPLACE_WITH_NETWORK_SETUP', $networkSetup.TrimEnd())
    [IO.File]::WriteAllText((Join-Path $drive 'user-data'), $userData, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $drive 'meta-data'), "instance-id: $VMName`nlocal-hostname: vpn-pulse-probe`n", (New-Object Text.UTF8Encoding($false)))
    if ($ManagementSwitchName) {
        $networkConfig = @"
version: 2
ethernets:
  external:
    match:
      macaddress: "$($externalMac.ToLowerInvariant())"
    set-name: external
    dhcp4: true
    dhcp4-overrides:
      route-metric: 10
  management:
    match:
      macaddress: "$($managementMac.ToLowerInvariant())"
    set-name: management
    dhcp4: false
    addresses: [$ManagementAddress]
"@
        [IO.File]::WriteAllText((Join-Path $drive 'network-config'), $networkConfig, (New-Object Text.UTF8Encoding($false)))
    }
} finally {
    Dismount-VHD -Path $seedDisk
}

Set-VMProcessor -VMName $VMName -Count 1
Set-VMFirmware -VMName $VMName -EnableSecureBoot On -SecureBootTemplate MicrosoftUEFICertificateAuthority
Add-VMHardDiskDrive -VMName $VMName -Path $seedDisk
Set-VM -Name $VMName -AutomaticStartAction Start -AutomaticStopAction Save -CheckpointType Disabled
Start-VM -Name $VMName | Out-Null
Write-Host "VM started. Wait for DHCP, then inspect: Get-VMNetworkAdapter -VMName '$VMName' | Select -Expand IPAddresses"
