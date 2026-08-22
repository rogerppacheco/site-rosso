# Cria/configura serviço Railway "site-record-pap" (worker Playwright dedicado).
# Pré-requisito: railway login
#
# Uso: powershell -ExecutionPolicy Bypass -File scripts\railway_setup_pap.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ProjectId = if ($env:RAILWAY_PROJECT_ID) { $env:RAILWAY_PROJECT_ID } else { "7171eee1-2c6e-446a-b7a9-880d3786c51a" }
$WebService = if ($env:RAILWAY_WEB_SERVICE) { $env:RAILWAY_WEB_SERVICE } else { "site-record" }
$PapService = if ($env:RAILWAY_PAP_SERVICE) { $env:RAILWAY_PAP_SERVICE } else { "site-record-pap" }
$GitHubRepo = "rogerppacheco/site-record"

Write-Host "=== Railway: servico PAP ($PapService) ===" -ForegroundColor Cyan
railway whoami 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Execute: railway login" -ForegroundColor Yellow
    exit 1
}

railway link -p $ProjectId -e production 2>$null

$existing = railway service status --json 2>$null | ConvertFrom-Json
$hasPap = $false
if ($existing -and $existing.services) {
    foreach ($s in $existing.services) {
        if ($s.name -eq $PapService) { $hasPap = $true }
    }
}

if (-not $hasPap) {
    Write-Host "Criando servico '$PapService' ..." -ForegroundColor Yellow
    railway add --service $PapService --repo $GitHubRepo
    if ($LASTEXITCODE -ne 0) { exit 1 }
} else {
    Write-Host "Servico '$PapService' ja existe." -ForegroundColor Green
}

Write-Host "Copiando variaveis do web -> pap ..." -ForegroundColor Yellow
railway link -p $ProjectId -s $WebService -e production | Out-Null
$kvLines = @(railway variables --kv 2>$null)
railway link -p $ProjectId -s $PapService -e production | Out-Null

foreach ($line in $kvLines) {
    if (-not $line -or $line -notmatch '=') { continue }
    $key = $line.Split('=', 2)[0]
    if ($key -match '^RAILWAY_') { continue }
    railway variable set "${line}" --skip-deploys 2>$null | Out-Null
}

railway variable set PAP_WORKER_MODE=True --skip-deploys
railway variable set PAP_USE_DEDICATED_WORKER=False --skip-deploys
railway variable set WHATSAPP_WEBHOOK_ASYNC=True --skip-deploys

Write-Host "Ativando fila PAP no servico web ..." -ForegroundColor Yellow
railway link -p $ProjectId -s $WebService -e production | Out-Null
railway variable set PAP_USE_DEDICATED_WORKER=True --skip-deploys

Write-Host ""
Write-Host "Concluido. No painel Railway:" -ForegroundColor Green
Write-Host "  1. Servico $PapService -> Settings -> Config-as-code -> /railway.pap.toml"
Write-Host "  2. Faca deploy (push ou railway up --service $PapService)"
Write-Host "  3. Servico web: healthcheck /health/ (railway.toml)"
Write-Host "  4. Opcional: SENTRY_DSN no web e pap"
