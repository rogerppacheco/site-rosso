# Fase 3 - Descomissiona Postgres isolados (sysr-vendas-api + syncwa-platform)
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase3.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $RepoRoot

$ProjectSysr = "fe553432-2a22-46cc-b347-ee669ff4aba3"
$ProjectSyncwa = "df858945-8b79-46f2-aad8-980bc4bfc925"
$ProjectCentral = "7171eee1-2c6e-446a-b7a9-880d3786c51a"
$BackupDir = Join-Path $RepoRoot "backups\consolidacao_db"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "=== Fase 3: Desligar Postgres isolados ===" -ForegroundColor Cyan

Write-Host "`n[1/4] Verificando APIs no Postgres central..." -ForegroundColor Yellow
$centralHost = "maglev.proxy.rlwy.net"
$checks = @(
    @{
        Name = "sysr-vendas-api"
        Url = "https://sysr-vendas-api-production.up.railway.app/api/health"
        DbVar = (railway variables --kv -p $ProjectSysr -s sysr-vendas-api -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
    }
    @{
        Name = "syncwa-api"
        Url = "https://api.sysr.com.br/health"
        DbVar = (railway variables --kv -p $ProjectSyncwa -s syncwa-api -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
    }
    @{
        Name = "evolution-api"
        Url = "https://evolution-api-production-8bbb.up.railway.app/"
        DbVar = (railway variables --kv -p $ProjectSysr -s evolution-api -e production 2>$null | Where-Object { $_ -match '^DATABASE_CONNECTION_URI=' }) -replace '^DATABASE_CONNECTION_URI=', ''
    }
)

foreach ($check in $checks) {
    if ($check.DbVar -notmatch [regex]::Escape($centralHost)) {
        Write-Host "ERRO: $($check.Name) nao aponta para o central ($centralHost)" -ForegroundColor Red
        Write-Host "  DATABASE: $($check.DbVar)" -ForegroundColor Red
        exit 1
    }
    try {
        $resp = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 25
        Write-Host "OK $($check.Name): HTTP $($resp.StatusCode) + DB central" -ForegroundColor Green
    } catch {
        Write-Host "ERRO: $($check.Name) health check falhou: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n[2/4] Backup final opcional (pg_dump isolados)..." -ForegroundColor Yellow
$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if ($pgDump) {
    $sysrUrl = (railway variables --kv -p $ProjectSysr -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''
    $syncwaUrl = (railway variables --kv -p $ProjectSyncwa -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''
    if ($sysrUrl) {
        $sysrDump = Join-Path $BackupDir "isolado_sysr_final_${Stamp}.dump"
        & pg_dump $sysrUrl -Fc -f $sysrDump
        if ($LASTEXITCODE -eq 0) { Write-Host "  Backup sysr: $sysrDump" -ForegroundColor Gray }
    }
    if ($syncwaUrl) {
        $syncwaDump = Join-Path $BackupDir "isolado_syncwa_final_${Stamp}.dump"
        & pg_dump $syncwaUrl -Fc -f $syncwaDump
        if ($LASTEXITCODE -eq 0) { Write-Host "  Backup syncwa: $syncwaDump" -ForegroundColor Gray }
    }
} else {
    Write-Host "  pg_dump nao encontrado - pulando backup final" -ForegroundColor Gray
}

Write-Host "`n[3/4] Removendo servico Postgres isolado (sysr-vendas-api)..." -ForegroundColor Yellow
$sysrPg = railway service list -p $ProjectSysr -e production --json 2>$null | ConvertFrom-Json
$sysrPgSvc = $sysrPg | Where-Object { $_.name -eq "Postgres" -or $_.serviceName -eq "Postgres" } | Select-Object -First 1
if ($sysrPgSvc) {
    $sysrPgId = if ($sysrPgSvc.id) { $sysrPgSvc.id } else { $sysrPgSvc.serviceId }
    railway service delete -p $ProjectSysr -s $sysrPgId -e production -y
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Write-Host "  Postgres sysr-vendas-api removido" -ForegroundColor Green
} else {
    Write-Host "  Postgres sysr-vendas-api ja removido" -ForegroundColor Gray
}

Write-Host "`n[4/4] Removendo servico Postgres isolado (syncwa-platform)..." -ForegroundColor Yellow
$syncwaPg = railway service list -p $ProjectSyncwa -e production --json 2>$null | ConvertFrom-Json
$syncwaPgSvc = $syncwaPg | Where-Object { $_.name -eq "Postgres" -or $_.serviceName -eq "Postgres" } | Select-Object -First 1
if ($syncwaPgSvc) {
    $syncwaPgId = if ($syncwaPgSvc.id) { $syncwaPgSvc.id } else { $syncwaPgSvc.serviceId }
    railway service delete -p $ProjectSyncwa -s $syncwaPgId -e production -y
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Write-Host "  Postgres syncwa-platform removido" -ForegroundColor Green
} else {
    Write-Host "  Postgres syncwa-platform ja removido" -ForegroundColor Gray
}

Write-Host "`nHealth check pos-remocao..." -ForegroundColor Cyan
Start-Sleep -Seconds 15
$failed = 0
foreach ($check in $checks) {
    try {
        $resp = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 25
        Write-Host "OK $($check.Name): HTTP $($resp.StatusCode)" -ForegroundColor Green
    } catch {
        $failed++
        Write-Host "FALHA $($check.Name): $($_.Exception.Message)" -ForegroundColor Red
    }
}

if ($failed -gt 0) {
    Write-Host "`nATENCAO: $failed health check(s) falharam apos remocao." -ForegroundColor Red
    exit 1
}

Write-Host "`nFase 3 concluida. Postgres isolados descomissionados." -ForegroundColor Green
Write-Host "Dados permanecem no central: schemas sysr + syncwa." -ForegroundColor Cyan
