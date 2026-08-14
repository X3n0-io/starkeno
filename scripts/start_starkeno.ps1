# Avvia StarkEno: migrazione, poi i tre processi.
#
# L'ORDINE NON E' LIBERO. La migrazione va per prima: ogni processo controlla all'avvio
# che la revisione del database sia `head` e si rifiuta di partire se non lo e'. E' il
# solo punto del sistema dove fallire rumorosamente e' giusto — partire con uno schema
# disallineato produce `no such column` inghiottiti dai try/except e zero alert, che e'
# indistinguibile da una flotta sana.
#
# Ogni processo si avvia con `python -m`, MAI per percorso: per percorso gli import
# assoluti si rompono.

$ErrorActionPreference = "Stop"
$radice = Split-Path -Parent $PSScriptRoot
Set-Location $radice

# --- 1. schema -------------------------------------------------------------------
# Primo avvio su un `starkeno.db` che esiste gia' (creato dalla v0): serve prima
#   python -m alembic stamp 0001
# una volta sola, per dichiarare che il database e' gia' allo schema v0. Su un
# database nuovo il solo `upgrade head` basta.
Write-Host "[1/4] migrazione dello schema..." -ForegroundColor Cyan
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Migrazione fallita. Se il database esiste gia' dalla v0, esegui una volta:" -ForegroundColor Yellow
    Write-Host "    python -m alembic stamp 0001" -ForegroundColor Yellow
    exit 1
}

# --- 2. server MCP ---------------------------------------------------------------
Write-Host "[2/4] server MCP (porta 8765)..." -ForegroundColor Cyan
Start-Process python -ArgumentList "-m", "starkeno.mcp_server" -WorkingDirectory $radice

# --- 3. dashboard ----------------------------------------------------------------
Write-Host "[3/4] dashboard (porta 8000)..." -ForegroundColor Cyan
Start-Process python -ArgumentList "-m", "uvicorn", "starkeno.api:app", "--port", "8000" -WorkingDirectory $radice

# --- 4. supervisore --------------------------------------------------------------
# Ne parte UNO SOLO: il processo tiene un socket su una porta fissa e il secondo esce
# con un messaggio. Due supervisori insieme raddoppierebbero `episodes` e, con
# configurazioni diverse, aprirebbero e chiuderebbero gli stessi alert a vicenda.
Write-Host "[4/4] supervisore..." -ForegroundColor Cyan
Start-Process python -ArgumentList "-m", "starkeno.supervisor" -WorkingDirectory $radice

Write-Host ""
Write-Host "Avviati. Dashboard: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Log del supervisore: $radice\supervisor.log" -ForegroundColor Green
