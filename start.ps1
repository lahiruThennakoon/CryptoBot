<#
    CryptoBot - one-command launcher (Windows PowerShell)
    ASCII only: PowerShell 5.1 misreads unicode dashes/quotes in unsigned scripts.

    Usage:
        .\start.ps1                 # full stack: db, api, collector, trader, dashboard
        .\start.ps1 -NoTrader       # everything except the paper-trading runtime
        .\start.ps1 -Reinstall      # re-install python/node dependencies
        .\start.ps1 -SkipDocker     # if postgres/redis already run elsewhere

    Live-money trading is NOT possible from this script (or anywhere in this
    app): it starts paper mode only.
#>

[CmdletBinding()]
param(
    [switch]$NoTrader,
    [switch]$NoCollector,
    [switch]$Reinstall,
    [switch]$SkipDocker,
    [int]$DashboardPort = 3000
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$dashboard = Join-Path $root "dashboard"
$venv = Join-Path $backend ".venv"
$activate = Join-Path $venv "Scripts\Activate.ps1"

function Say([string]$msg, [string]$colour = "White") { Write-Host $msg -ForegroundColor $colour }
function Step([string]$msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "  OK   $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "  WARN $msg" -ForegroundColor Yellow }
function Die([string]$msg) { Write-Host "  FAIL $msg" -ForegroundColor Red; exit 1 }

function Have([string]$exe) { return [bool](Get-Command $exe -ErrorAction SilentlyContinue) }

function Wait-Port([string]$targetHost, [int]$port, [int]$timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect($targetHost, $port)
            $client.Close()
            return $true
        } catch { Start-Sleep -Milliseconds 700 }
    }
    return $false
}

function New-Secret([int]$byteCount = 32) {
    $buffer = New-Object 'System.Byte[]' $byteCount
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return ([Convert]::ToBase64String($buffer) -replace '[^A-Za-z0-9]', '')
}

function Set-EnvValue([string]$file, [string]$key, [string]$value) {
    $lines = @(Get-Content $file)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$key\s*=") { $found = $true; "$key=$value" } else { $line }
    }
    if (-not $found) { $out += "$key=$value" }
    Set-Content -Path $file -Value $out -Encoding UTF8
}

function Get-EnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return $null }
    foreach ($line in Get-Content $file) {
        if ($line -match "^\s*$key\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Start-Terminal([string]$title, [string]$workDir, [string]$command) {
    $inner = "`$host.UI.RawUI.WindowTitle='CryptoBot - $title'; Set-Location '$workDir'; $command"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $inner) | Out-Null
    Ok "launched: $title"
}

Say "==========================================================" "Cyan"
Say " CryptoBot launcher - paper trading only, live is disabled" "Cyan"
Say "==========================================================" "Cyan"

# --- 1. prerequisites -------------------------------------------------
Step "Checking prerequisites"
$python = $null
if (Have "python") { $python = "python" } elseif (Have "py") { $python = "py" }
if (-not $python) { Die "Python 3.12+ not found. Install from python.org and tick 'Add python.exe to PATH'." }
Ok "python: $((& $python --version) 2>&1)"
if (-not (Have "node")) { Die "Node.js 20+ not found. Install from nodejs.org (LTS)." }
Ok "node: $(node --version)"
if (-not $SkipDocker) {
    if (-not (Have "docker")) { Die "Docker not found. Install Docker Desktop, or use -SkipDocker with your own postgres/redis." }
    try { docker info 2>&1 | Out-Null; Ok "docker is running" }
    catch { Die "Docker is installed but not running. Start Docker Desktop and retry." }
}

# --- 2. configuration -------------------------------------------------
Step "Checking configuration"
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Ok "created .env from .env.example"
}
$secret = Get-EnvValue $envFile "API_SECRET_KEY"
if ([string]::IsNullOrWhiteSpace($secret) -or $secret -like "generate_*" -or $secret -eq "dev-only-not-secret") {
    $secret = New-Secret
    Set-EnvValue $envFile "API_SECRET_KEY" $secret
    Ok "generated a random API_SECRET_KEY"
} else { Ok "API_SECRET_KEY present" }

$localEnv = Join-Path $dashboard ".env.local"
if (-not (Test-Path $localEnv)) {
    Copy-Item (Join-Path $dashboard ".env.local.example") $localEnv
}
Set-EnvValue $localEnv "NEXT_PUBLIC_API_TOKEN" $secret
Set-EnvValue $localEnv "NEXT_PUBLIC_API_URL" "http://127.0.0.1:8000"
Ok "dashboard token synced with the API key"

$testnetKey = Get-EnvValue $envFile "BINANCE_TESTNET_API_KEY"
if ([string]::IsNullOrWhiteSpace($testnetKey) -or $testnetKey -like "your_*") {
    Warn "No Binance Testnet key in .env - market data and account calls will fail."
    Warn "Get free keys at https://testnet.binance.vision (GitHub login), then edit .env."
}
$aiKey = Get-EnvValue $envFile "ANTHROPIC_API_KEY"
if ([string]::IsNullOrWhiteSpace($aiKey)) { Warn "No ANTHROPIC_API_KEY - the AI assistant panel stays disabled (everything else works)." }

# --- 3. database + cache ----------------------------------------------
if (-not $SkipDocker) {
    Step "Starting PostgreSQL and Redis"
    Push-Location $root
    docker compose up -d postgres redis | Out-Null
    Pop-Location
    if (Wait-Port "127.0.0.1" 5432 90) { Ok "postgres is accepting connections" }
    else { Die "postgres did not become ready in 90s. Check: docker compose logs postgres" }
    if (Wait-Port "127.0.0.1" 6379 30) { Ok "redis is accepting connections" }
    else { Warn "redis not reachable - controls may be degraded" }
}

# --- 4. python environment --------------------------------------------
Step "Preparing the Python environment"
if ($Reinstall -and (Test-Path $venv)) { Remove-Item -Recurse -Force $venv; Ok "removed old venv" }
$needInstall = $false
if (-not (Test-Path $activate)) {
    Push-Location $backend
    & $python -m venv .venv
    Pop-Location
    Ok "created virtual environment"
    $needInstall = $true
} elseif ($Reinstall) { $needInstall = $true }

. $activate
if ($needInstall -or -not (Have "cryptobot")) {
    Say "  installing backend dependencies (this takes a minute)..." "Gray"
    Push-Location $backend
    pip install -e ".[dev,ml]" --quiet
    Pop-Location
    Ok "backend dependencies installed"
} else { Ok "backend dependencies already installed" }

# --- 5. database schema -----------------------------------------------
Step "Applying database migrations"
Push-Location $backend
$versions = Join-Path $backend "alembic\versions"
if (-not (Test-Path $versions)) { New-Item -ItemType Directory -Path $versions | Out-Null }
$migrationCount = (Get-ChildItem $versions -Filter "*.py" -ErrorAction SilentlyContinue | Measure-Object).Count
if ($migrationCount -eq 0) {
    alembic revision --autogenerate -m "initial schema" | Out-Null
    Ok "generated the initial migration"
} else {
    # models may have gained tables since the last migration; harmless if not
    alembic revision --autogenerate -m "sync models" 2>$null | Out-Null
}
alembic upgrade head | Out-Null
Ok "schema is up to date"
Pop-Location

# --- 6. health check ---------------------------------------------------
Step "Running diagnostics"
Push-Location $backend
cryptobot doctor
Pop-Location

# --- 7. dashboard dependencies ------------------------------------------
Step "Preparing the dashboard"
$nodeModules = Join-Path $dashboard "node_modules"
if ($Reinstall -and (Test-Path $nodeModules)) { Remove-Item -Recurse -Force $nodeModules }
if (-not (Test-Path $nodeModules)) {
    Say "  installing dashboard dependencies (this takes a minute)..." "Gray"
    Push-Location $dashboard
    npm install --no-fund --no-audit
    Pop-Location
    Ok "dashboard dependencies installed"
} else { Ok "dashboard dependencies already installed" }

# --- 8. launch everything -----------------------------------------------
Step "Launching services in separate windows"
$activateCmd = ". '$activate';"
Start-Terminal "API" $backend "$activateCmd uvicorn cryptobot.api.main:app --host 127.0.0.1 --port 8000"
if (Wait-Port "127.0.0.1" 8000 45) { Ok "API is up on http://127.0.0.1:8000" }
else { Warn "API did not open port 8000 yet - check its window for errors" }

if (-not $NoCollector) { Start-Terminal "Market data" $backend "$activateCmd cryptobot collect" }
if (-not $NoTrader) { Start-Terminal "Paper trader" $backend "$activateCmd cryptobot trade" }
Start-Terminal "Dashboard" $dashboard "npm run dev"

# --- 9. open the browser --------------------------------------------------
Step "Waiting for the dashboard"
$port = $DashboardPort
if (-not (Wait-Port "127.0.0.1" $port 90)) {
    foreach ($candidate in 3001, 3002, 3003) {
        if (Wait-Port "127.0.0.1" $candidate 5) { $port = $candidate; break }
    }
}
$url = "http://localhost:$port"
if (Wait-Port "127.0.0.1" $port 5) {
    Start-Process $url
    Ok "dashboard open at $url"
} else {
    Warn "Dashboard not reachable yet. Check its window, then open $url manually."
}

Say ""
Say "==========================================================" "Cyan"
Say " Running. Four windows opened:" "Cyan"
Say "   API           http://127.0.0.1:8000/api/v1/health"
Say "   Dashboard     $url"
Say "   Market data   collecting candles for enabled pairs"
Say "   Paper trader  simulated trading, no real money"
Say ""
Say " First run tips:" "Cyan"
Say "   - Import history for charts and the strategy lab:"
Say "       cd backend; .\.venv\Scripts\activate"
Say "       cryptobot import-history --symbol BTCUSDT --interval 1h --days 730"
Say "   - Stop everything:  .\stop.ps1"
Say ""
Say " Reminder: paper mode only. No profit is guaranteed; losing" "Yellow"
Say " periods are expected, and live trading stays disabled." "Yellow"
Say "==========================================================" "Cyan"
