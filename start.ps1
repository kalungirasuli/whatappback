param(
    [switch]$Build,
    [switch]$NoDocker
)

Write-Host "=== whatAppseller — One Command Start ===" -ForegroundColor Cyan

# 1. Start Docker infrastructure
if (-not $NoDocker) {
    Write-Host "[1/5] Starting Docker services (Postgres, Redis, Qdrant, MinIO, Ollama)..." -ForegroundColor Yellow
    $composeCmd = "docker compose -f docker/docker-compose.yml up -d"
    if ($Build) { $composeCmd += " --build" }
    Invoke-Expression $composeCmd
    if ($LASTEXITCODE -ne 0) { Write-Host "Docker compose failed" -ForegroundColor Red; exit 1 }
    Write-Host "  Docker services started" -ForegroundColor Green
}

# 2. Wait for healthy services
Write-Host "[2/5] Waiting for services..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# 3. Run database migrations
Write-Host "[3/5] Running database migrations..." -ForegroundColor Yellow
alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "Migrations failed" -ForegroundColor Red; exit 1 }
Write-Host "  Migrations applied" -ForegroundColor Green

# 4. Start the three services in background
Write-Host "[4/5] Starting Python services..." -ForegroundColor Yellow

$root = $PSScriptRoot

# API server (port 8002)
$apiJob = Start-Job -Name "whatAppseller-API" -ScriptBlock {
    Set-Location -LiteralPath $using:root
    uvicorn src.api.main:app --host 0.0.0.0 --port 8002 --reload
}

# Webhook gateway (port 8000)
$webhookJob = Start-Job -Name "whatAppseller-Webhook" -ScriptBlock {
    Set-Location -LiteralPath $using:root
    uvicorn src.gateway.main:app --host 0.0.0.0 --port 8000 --reload
}

# Worker (background message processor)
$workerJob = Start-Job -Name "whatAppseller-Worker" -ScriptBlock {
    Set-Location -LiteralPath $using:root
    python -m src.workers.router
}

Write-Host "  API on http://localhost:8002" -ForegroundColor Green
Write-Host "  Webhook on http://localhost:8000" -ForegroundColor Green
Write-Host "  Worker running in background" -ForegroundColor Green

# 5. Show status
Write-Host "[5/5] All services started!" -ForegroundColor Cyan
Write-Host "`nEndpoints:" -ForegroundColor White
Write-Host "  REST API:     http://localhost:8002" -ForegroundColor White
Write-Host "  Webhook:      http://localhost:8000" -ForegroundColor White
Write-Host "  Health:       http://localhost:8002/health" -ForegroundColor White
Write-Host "`nImport postman_collection.json into Postman to test." -ForegroundColor White
Write-Host "`nRun './stop.ps1' to stop all services." -ForegroundColor Yellow
