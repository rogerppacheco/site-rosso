# Cria/configura serviço Railway "site-record-webhook" (worker WhatsApp dedicado).
# Pré-requisito: railway login
#
# Uso: powershell -ExecutionPolicy Bypass -File scripts\railway_setup_webhook.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ProjectId = if ($env:RAILWAY_PROJECT_ID) { $env:RAILWAY_PROJECT_ID } else { "7171eee1-2c6e-446a-b7a9-880d3786c51a" }
$WebService = if ($env:RAILWAY_WEB_SERVICE) { $env:RAILWAY_WEB_SERVICE } else { "site-record" }
$WebhookService = if ($env:RAILWAY_WEBHOOK_SERVICE) { $env:RAILWAY_WEBHOOK_SERVICE } else { "site-record-webhook" }

Write-Host "=== Railway: servico webhook ($WebhookService) ===" -ForegroundColor Cyan
railway whoami 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Execute: railway login" -ForegroundColor Yellow
    exit 1
}

railway link -p $ProjectId -e production 2>$null

$existing = railway service list --json 2>$null | ConvertFrom-Json
$hasWebhook = $false
if ($existing) {
    foreach ($s in $existing) {
        if ($s.name -eq $WebhookService) { $hasWebhook = $true }
    }
}

if (-not $hasWebhook) {
    Write-Host "Criando servico '$WebhookService' (empty) ..." -ForegroundColor Yellow
    railway add --service $WebhookService --json 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Falha ao criar servico." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Servico '$WebhookService' ja existe." -ForegroundColor Green
}

Write-Host "Copiando variaveis do web -> webhook ..." -ForegroundColor Yellow
railway link -p $ProjectId -s $WebService -e production | Out-Null
$kvLines = @(railway variables --kv 2>$null)
railway link -p $ProjectId -s $WebhookService -e production | Out-Null

$count = 0
foreach ($line in $kvLines) {
    if (-not $line -or $line -notmatch '=') { continue }
    $key = $line.Split('=', 2)[0]
    if ($key -match '^RAILWAY_') { continue }
    railway variables --set $line --skip-deploys 2>$null | Out-Null
    $count++
}
Write-Host "Variaveis copiadas: $count" -ForegroundColor Green

railway variables --set "WHATSAPP_WORKER_MODE=True" --skip-deploys
railway variables --set "WHATSAPP_USE_DEDICATED_WORKER=False" --skip-deploys
railway variables --set "WHATSAPP_WEBHOOK_ASYNC=False" --skip-deploys
railway variables --set "PAP_USE_DEDICATED_WORKER=True" --skip-deploys

Write-Host "Ativando fila webhook no servico web ..." -ForegroundColor Yellow
railway link -p $ProjectId -s $WebService -e production | Out-Null
railway variables --set "WHATSAPP_USE_DEDICATED_WORKER=True" --skip-deploys
railway variables --set "WHATSAPP_WEBHOOK_ASYNC=True" --skip-deploys

Write-Host ""
Write-Host "Configure via GraphQL ou painel Railway:" -ForegroundColor Yellow
Write-Host "  Servico $WebhookService -> Config-as-code -> /railway.webhook.toml"
Write-Host "  Repo: rogerppacheco/site-record"
Write-Host ""
Write-Host "Deploy: railway up --detach -s $WebhookService" -ForegroundColor Cyan
Write-Host "Concluido." -ForegroundColor Green
