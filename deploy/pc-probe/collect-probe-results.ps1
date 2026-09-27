[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SshKey,
    [string]$ManagementAddress = '192.0.2.2',
    [ValidateSet('on', 'off')][string]$Label = 'on',
    [string]$OutputDirectory = "$PWD\probe-results"
)

$ErrorActionPreference = 'Stop'
$ssh = 'C:\Program Files\Git\usr\bin\ssh.exe'
$scp = 'C:\Program Files\Git\usr\bin\scp.exe'
if (-not (Test-Path -LiteralPath $ssh)) { throw 'Git for Windows SSH was not found.' }
$key = (Resolve-Path -LiteralPath $SshKey).Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

if (-not (Test-NetConnection -ComputerName $ManagementAddress -Port 22 -InformationLevel Quiet)) {
    throw 'SSH is unreachable. Disable the host VPN, wait five seconds, and retry.'
}
$options = @('-F','NUL','-i',$key,'-o','BatchMode=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=NUL')
$done = "/var/lib/vpn-pulse/r17/matrix-$Label.done"
& $ssh @options "probe@$ManagementAddress" "sudo test -f $done"
if ($LASTEXITCODE -ne 0) { throw "The $($Label.ToUpperInvariant()) matrix has not finished." }
& $scp @options "probe@${ManagementAddress}:/var/lib/vpn-pulse/r17/matrix-$Label.*" $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Could not copy the probe results.' }
Write-Host "$($Label.ToUpperInvariant()) results copied to: $OutputDirectory"
