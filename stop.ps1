Write-Host "=== Stopping whatAppseller ===" -ForegroundColor Cyan

# Stop background Python processes
Get-Job -Name "whatAppseller-*" | Stop-Job -PassThru | Remove-Job
Write-Host "Python services stopped" -ForegroundColor Green

# Stop Docker services
docker compose -f docker/docker-compose.yml down
Write-Host "Docker services stopped" -ForegroundColor Green

Write-Host "All services stopped." -ForegroundColor Cyan
