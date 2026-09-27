[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VhdPath,
    [Parameter(Mandatory)][string]$ExternalAdapter,
    [Parameter(Mandatory)][string]$ExternalMac,
    [Parameter(Mandatory)][string]$ManagementMac,
    [string]$VmName = 'VPNPulseProbe',
    [string]$ExternalSwitch = 'VPNPulseExternal',
    [string]$ManagementSwitch = 'VPNPulseManagement',
    [string]$ManagementHostAddress = '192.0.2.1',
    [int]$ManagementPrefixLength = 24
)

$ErrorActionPreference = 'Stop'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run PowerShell as Administrator.' }

$vhd = (Resolve-Path -LiteralPath $VhdPath).Path
if (Get-VM -Name $VmName -ErrorAction SilentlyContinue) { throw "VM already exists: $VmName" }
if (-not (Get-NetAdapter -Name $ExternalAdapter -ErrorAction SilentlyContinue)) { throw "Network adapter was not found: $ExternalAdapter" }

if (-not (Get-VMSwitch -Name $ExternalSwitch -ErrorAction SilentlyContinue)) {
    Write-Host 'The host network may disconnect for 5-15 seconds while Hyper-V creates the external switch.'
    New-VMSwitch -Name $ExternalSwitch -NetAdapterName $ExternalAdapter -AllowManagementOS $true | Out-Null
}
if (-not (Get-VMSwitch -Name $ManagementSwitch -ErrorAction SilentlyContinue)) {
    New-VMSwitch -Name $ManagementSwitch -SwitchType Internal | Out-Null
}

$hostNic = Get-NetAdapter -Name "vEthernet ($ManagementSwitch)"
Get-NetIPAddress -InterfaceIndex $hostNic.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetIPAddress -Confirm:$false
New-NetIPAddress -InterfaceIndex $hostNic.ifIndex -IPAddress $ManagementHostAddress -PrefixLength $ManagementPrefixLength | Out-Null

New-VM -Name $VmName -Generation 2 -MemoryStartupBytes 1GB -VHDPath $vhd -SwitchName $ExternalSwitch | Out-Null
Set-VM -Name $VmName -ProcessorCount 1 -AutomaticStartAction Start -AutomaticStopAction Save
Set-VMFirmware -VMName $VmName -EnableSecureBoot Off
$external = Get-VMNetworkAdapter -VMName $VmName -Name 'Network Adapter'
Set-VMNetworkAdapter -VMNetworkAdapter $external -StaticMacAddress ($ExternalMac -replace '[:-]', '')
Add-VMNetworkAdapter -VMName $VmName -Name Management -SwitchName $ManagementSwitch -StaticMacAddress ($ManagementMac -replace '[:-]', '')
Start-VM -Name $VmName | Out-Null
Write-Host "Started $VmName. Keep the host VPN state unchanged until the autonomous check finishes."
