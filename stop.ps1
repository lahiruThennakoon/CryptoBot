<#
    CryptoBot - stop everything started by start.ps1
    ASCII only: PowerShell 5.1 misreads unicode dashes/quotes in unsigned scripts.

    Usage:
        .\stop.ps1              # stop app processes, leave the database running
        .\stop.ps1 -All         # also stop the postgres/redis containers
        .\stop.ps1 -Wipe        # -All plus DELETE the database volume (destroys data)
#>

[CmdletBinding()]
param([switch]$All, [switch]$Wipe)

$root = $PSScriptRoot
function Ok([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Say([string]$m, [string]$c = "White") { Write-Host $m -ForegroundColor $c }

Say "Stopping CryptoBot..." "Cyan"

# Close the launcher windows (titles are set by start.ps1)
$titles = @("CryptoBot - API", "CryptoBot - Market data", "CryptoBot - Paper trader",
            "CryptoBot - Dashboard")
$closed = 0
foreach ($proc in Get-Process powershell, pwsh -ErrorAction SilentlyContinue) {
    if ($proc.MainWindowTitle -and ($titles -contains $proc.MainWindowTitle)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $closed++
    }
}
Ok "closed $closed service window(s)"

# Anything still holding our ports (e.g. a dashboard that moved to 3001)
foreach ($port in 8000, 3000, 3001, 3002) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $owner = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($owner -and ($owner.ProcessName -in @("python", "node", "uvicorn"))) {
            Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
            Ok "freed port $port ($($owner.ProcessName))"
        }
    }
}

if ($All -or $Wipe) {
    Push-Location $root
    if ($Wipe) {
        Say ""
        Say "WARNING: -Wipe deletes the database volume (candles, trades, reports)." "Yellow"
        $answer = Read-Host "Type DELETE to confirm"
        if ($answer -eq "DELETE") {
            docker compose down -v | Out-Null
            Ok "containers stopped and data volume deleted"
        } else {
            Say "cancelled - data kept" "Yellow"
            docker compose down | Out-Null
            Ok "containers stopped, data kept"
        }
    } else {
        docker compose down | Out-Null
        Ok "postgres/redis containers stopped (data kept)"
    }
    Pop-Location
} else {
    Ok "database left running (use -All to stop it too)"
}

Say ""
Say "Stopped. Nothing trades while these processes are down; no real money was ever involved." "Cyan"
