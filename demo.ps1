<#
    CryptoBot - DEMO launcher (Windows PowerShell)
    ASCII only: PowerShell 5.1 misreads unicode dashes/quotes in unsigned scripts.

    Starts the full stack and runs the demo strategy, which trades eagerly on
    1-minute candles so you can watch the pipeline work within minutes.

        .\demo.ps1                # start everything in demo mode
        .\demo.ps1 -SkipDocker    # you run postgres/redis yourself
        .\demo.ps1 -Reinstall     # rebuild dependencies first
        .\stop.ps1                # stop everything

    WHAT THE DEMO IS
      demo_pulse enters whenever it is flat, on purpose. It has NO trading
      edge and will slowly lose simulated money to fees and spread. That is
      the honest lesson it teaches. Its results are never evidence for the
      graduation criteria, and no real money is ever involved.
#>

[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$Reinstall,
    [int]$DashboardPort = 3000
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$activate = Join-Path $backend ".venv\Scripts\Activate.ps1"

function Say([string]$m, [string]$c = "White") { Write-Host $m -ForegroundColor $c }
function Ok([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  WARN $m" -ForegroundColor Yellow }

Say "==============================================================" "Magenta"
Say " CryptoBot DEMO - eager trading so you can SEE it work" "Magenta"
Say "==============================================================" "Magenta"
Say " The demo strategy trades every few minutes on purpose." "Yellow"
Say " It has NO edge and will lose small simulated amounts to" "Yellow"
Say " costs. Nothing here is real money or evidence of anything." "Yellow"
Say "==============================================================" "Magenta"
Say ""

# Reuse the main launcher for all setup, but without its normal trader window.
# Hashtable splatting (NOT array splatting): arrays bind positionally, which
# would send "-NoTrader" into -DashboardPort.
$startParams = @{
    NoTrader      = $true
    DashboardPort = $DashboardPort
}
if ($SkipDocker) { $startParams["SkipDocker"] = $true }
if ($Reinstall) { $startParams["Reinstall"] = $true }

& (Join-Path $root "start.ps1") @startParams
if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    Say "Setup failed above - fix that first, then re-run .\demo.ps1" "Red"
    exit 1
}

# Demo needs 1-minute candles; make sure some history exists so the strategy
# passes warmup immediately instead of waiting ~20 minutes for live candles.
Say ""
Say "=== Seeding 1-minute candles for an immediate start" "Cyan"
Push-Location $backend
. $activate
try {
    cryptobot import-history --symbol BTCUSDT --interval 1m --days 2
    Ok "1m history imported for BTCUSDT"
} catch {
    Warn "Could not import 1m history - the demo will still run, but the first"
    Warn "trade waits for about 20 live 1-minute candles."
}
Pop-Location

# Start the demo trader in its own window.
$inner = "`$host.UI.RawUI.WindowTitle='CryptoBot - Paper trader'; " +
         "Set-Location '$backend'; . '$activate'; cryptobot trade --demo"
Start-Process powershell -ArgumentList @("-NoExit", "-Command", $inner) | Out-Null
Ok "demo trader launched"

Say ""
Say "==============================================================" "Magenta"
Say " Demo running. What to watch on the dashboard:" "Magenta"
Say "   Overview      -> Recent fills, Open positions, equity curve"
Say "   Overview      -> 'Daily result after fees' bars appear as trades close"
Say "   Trading pairs -> Signal column changes, 'why?' shows the reasoning"
Say "   Cost reality  -> the fee arithmetic you are watching happen live"
Say ""
Say " Expect the first trade within a few minutes, then activity"
Say " every few minutes. Exits show as stop_loss, take_profit or"
Say " max_holding_period. Try Emergency stop with a position open."
Say ""
Say " When finished:" "Cyan"
Say "   .\stop.ps1                     # stop everything"
Say "   cryptobot trade                # back to the real, selective strategies"
Say ""
Say " Reminder: demo results are NOT evidence. The real strategies" "Yellow"
Say " trade rarely by design, and no profit is ever guaranteed." "Yellow"
Say "==============================================================" "Magenta"
