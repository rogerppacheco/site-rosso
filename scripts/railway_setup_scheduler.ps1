# Configura e faz deploy do serviço Railway "scheduler" (mesmo projeto do site-record).
# Pré-requisito: railway login  (uma vez, se aparecer Unauthorized)
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\railway_setup_scheduler.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

# Projeto production site-record: pleasing-recreation (nao melodious-hope/viabilidade)
$ProjectId = if ($env:RAILWAY_PROJECT_ID) { $env:RAILWAY_PROJECT_ID } else { "7171eee1-2c6e-446a-b7a9-880d3786c51a" }
$WebService = if ($env:RAILWAY_WEB_SERVICE) { $env:RAILWAY_WEB_SERVICE } else { "" }
$SchedulerService = if ($env:RAILWAY_SCHEDULER_SERVICE) { $env:RAILWAY_SCHEDULER_SERVICE } else { "site-record-scheduler" }
$GitHubRepo = "rogerppacheco/site-record"

function Test-RailwayAuth {
    $out = railway whoami 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Railway nao autenticado. Execute no terminal:" -ForegroundColor Yellow
        Write-Host "  railway login" -ForegroundColor Cyan
        Write-Host "Depois rode este script de novo." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Railway: $out" -ForegroundColor Green
}

function Get-WebServiceName {
    if ($WebService) { return $WebService }
    $status = railway service status --json 2>$null | ConvertFrom-Json
    if ($status -and $status.services) {
        foreach ($s in $status.services) {
            $n = $s.name
            if ($n -and $n -notmatch 'scheduler|postgres|redis|mysql' -and $n -notmatch 'Scheduler') {
                return $n
            }
        }
    }
    return "site-record"
}

Write-Host "=== Railway: servico scheduler (site-record) ===" -ForegroundColor Cyan
Test-RailwayAuth

Write-Host "Vinculando projeto $ProjectId ..." -ForegroundColor Gray
railway link -p $ProjectId -e production 2>$null
if ($LASTEXITCODE -ne 0) {
    railway link -p $ProjectId
}

$webName = Get-WebServiceName
Write-Host "Servico web de referencia: $webName" -ForegroundColor Gray

$existing = railway service status --json 2>$null | ConvertFrom-Json
$hasScheduler = $false
if ($existing -and $existing.services) {
    foreach ($s in $existing.services) {
        if ($s.name -eq $SchedulerService) { $hasScheduler = $true }
    }
}

if (-not $hasScheduler) {
    Write-Host "Criando servico '$SchedulerService' (repo $GitHubRepo) ..." -ForegroundColor Yellow
    railway add --service $SchedulerService --repo $GitHubRepo
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Falha ao criar servico. Crie manualmente: + New Service > GitHub > $GitHubRepo" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Servico '$SchedulerService' ja existe." -ForegroundColor Green
}

Write-Host "Copiando variaveis do web -> scheduler (pode levar 1-2 min) ..." -ForegroundColor Yellow
railway link -p $ProjectId -s $webName -e production | Out-Null
$kvLines = @(railway variables --kv 2>$null)
railway link -p $ProjectId -s $SchedulerService -e production | Out-Null

$count = 0
foreach ($line in $kvLines) {
    if (-not $line -or $line -notmatch '=') { continue }
    $key = $line.Split('=', 2)[0]
    if ($key -match '^RAILWAY_') { continue }
    railway variables --set $line --skip-deploys 2>$null | Out-Null
    $count++
}
Write-Host "Variaveis copiadas: $count" -ForegroundColor Green

Write-Host "Deploy do scheduler ..." -ForegroundColor Yellow
railway up --detach -s $SchedulerService -e production
if ($LASTEXITCODE -ne 0) {
    Write-Host "Deploy via CLI falhou. No Railway, abra o servico '$SchedulerService' e clique Deploy." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "IMPORTANTE (uma vez no painel Railway):" -ForegroundColor Yellow
Write-Host "  Servico '$SchedulerService' > Settings > Config-as-code" -ForegroundColor White
Write-Host "  Arquivo: /railway.scheduler.toml" -ForegroundColor Cyan
Write-Host "  Replicas: 1 (Settings > Scaling)" -ForegroundColor Cyan
Write-Host "  Sem dominio publico (nao precisa de URL)" -ForegroundColor Gray
Write-Host ""
Write-Host "Servico web: nao deve rodar run_scheduler (scheduler removido do Gunicorn)." -ForegroundColor Green
Write-Host "Concluido." -ForegroundColor Green
