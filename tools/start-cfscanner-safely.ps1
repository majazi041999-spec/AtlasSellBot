param(
    [Parameter(Mandatory = $true)][string]$ScannerPath,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

function Get-UnsafeScanReason {
    $proxy = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    if ($proxy.ProxyEnable -eq 1 -or $proxy.AutoConfigURL) {
        return 'Windows proxy or PAC is enabled. Turn off the VPN and proxy before scanning.'
    }
    $adapters = @(Get-NetAdapter -IncludeHidden | Where-Object {
        $_.Status -eq 'Up' -and
        ($_.Name + ' ' + $_.InterfaceDescription) -match '(?i)tun|tap|vpn|wireguard|sing-box|clash|v2ray'
    })
    if ($adapters.Count -gt 0) {
        return 'An active VPN/TUN adapter was detected. Turn off the VPN before scanning.'
    }
    return $null
}

$scanner = Get-Item -LiteralPath $ScannerPath
if ($scanner.PSIsContainer -or $scanner.Name -ne 'WinCFScan.exe') {
    throw 'ScannerPath must point to WinCFScan.exe.'
}
$reason = Get-UnsafeScanReason
if ($reason) { throw $reason }
if ($CheckOnly) {
    Write-Output 'PASS: no active Windows proxy/PAC or recognizable VPN adapter detected.'
    exit 0
}

if (Get-Process -Name 'WinCFScan' -ErrorAction SilentlyContinue) {
    throw 'Close the existing WinCFScan instance before using this guarded launcher.'
}

Write-Output 'Run scans only on the raw operator connection. This guard cannot detect VPNs on another device/router.'
$process = Start-Process -FilePath $scanner.FullName -WorkingDirectory $scanner.DirectoryName -PassThru
try {
    while (-not $process.HasExited) {
        Start-Sleep -Seconds 1
        $reason = Get-UnsafeScanReason
        if ($reason) { throw $reason }
        $process.Refresh()
    }
} catch {
    if (-not $process.HasExited) {
        # Stop this launch's process tree, including scanner-owned test cores.
        & taskkill.exe /PID $process.Id /T /F | Out-Null
    }
    throw
} finally {
    $process.Dispose()
}
