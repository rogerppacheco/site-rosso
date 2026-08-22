# Redeploy limpo do sysr-vendas-api a partir de backend/
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\redeploy_sysr_vendas_api.ps1

$ErrorActionPreference = "Stop"
$Backend = "C:\sysr_vendas\backend"

Write-Host "=== Redeploy sysr-vendas-api (backend/) ===" -ForegroundColor Cyan
Set-Location $Backend

railway up --detach --ci --message "Deploy limpo sysr-vendas-api (backend root)"
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "Aguardando build (120s)..." -ForegroundColor Gray
Start-Sleep -Seconds 120

railway service status -p fe553432-2a22-46cc-b347-ee669ff4aba3 -s sysr-vendas-api -e production
try {
    $health = Invoke-WebRequest -Uri "https://sysr-vendas-api-production.up.railway.app/api/health" -UseBasicParsing -TimeoutSec 20
    Write-Host "Health: $($health.Content)" -ForegroundColor Green
} catch {
    Write-Host "Health check falhou: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`nPara deploys Git no monorepo, commite e push:" -ForegroundColor Cyan
Write-Host "  C:\sysr_vendas\railway.toml" -ForegroundColor Gray
Write-Host "  C:\sysr_vendas\Dockerfile" -ForegroundColor Gray
Write-Host "Ou defina Root Directory = backend no Railway (Settings)." -ForegroundColor Cyan
