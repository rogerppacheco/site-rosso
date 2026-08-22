# Fase 2 - Cutover: aponta APIs para Postgres central (schemas sysr/syncwa)
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase2.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $RepoRoot

$ProjectCentral = "7171eee1-2c6e-446a-b7a9-880d3786c51a"
$ProjectSysr = "fe553432-2a22-46cc-b347-ee669ff4aba3"
$ProjectSyncwa = "df858945-8b79-46f2-aad8-980bc4bfc925"
$BackupDir = Join-Path $RepoRoot "backups\consolidacao_db"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "=== Fase 2: Cutover DATABASE_URL -> Postgres central ===" -ForegroundColor Cyan

$centralUrl = (railway variables --kv -p $ProjectCentral -s site-record -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
if (-not $centralUrl) {
    Write-Host "ERRO: DATABASE_URL central nao encontrada" -ForegroundColor Red
    exit 1
}

$sysrOld = (railway variables --kv -p $ProjectSysr -s sysr-vendas-api -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
$syncwaOld = (railway variables --kv -p $ProjectSyncwa -s syncwa-api -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
$evoOld = (railway variables --kv -p $ProjectSysr -s evolution-api -e production 2>$null | Where-Object { $_ -match '^DATABASE_CONNECTION_URI=' }) -replace '^DATABASE_CONNECTION_URI=', ''

function Set-RailwayVar {
    param(
        [string]$Project,
        [string]$Service,
        [string]$Key,
        [string]$Value
    )
    $Value | railway variable set $Key --stdin -p $Project -s $Service -e production
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

$sysrNew = "${centralUrl}?schema=sysr"
$syncwaNew = "${centralUrl}?schema=syncwa"
$evoNew = "${centralUrl}?schema=sysr"

$backup = @{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    central_base = $centralUrl
    sysr_vendas_api = @{ DATABASE_URL = $sysrOld }
    syncwa_api = @{ DATABASE_URL = $syncwaOld }
    evolution_api = @{ DATABASE_CONNECTION_URI = $evoOld }
    new_urls = @{
        sysr_vendas_api = $sysrNew
        syncwa_api = $syncwaNew
        evolution_api = $evoNew
    }
}
$backupFile = Join-Path $BackupDir "cutover_backup_$Stamp.json"
$backup | ConvertTo-Json -Depth 4 | Set-Content -Path $backupFile -Encoding UTF8
Write-Host "Backup URLs: $backupFile" -ForegroundColor Gray

Write-Host "`n[1/3] sysr-vendas-api -> schema sysr" -ForegroundColor Yellow
Set-RailwayVar -Project $ProjectSysr -Service sysr-vendas-api -Key DATABASE_URL -Value $sysrNew

Write-Host "`n[2/3] syncwa-api -> schema syncwa" -ForegroundColor Yellow
Set-RailwayVar -Project $ProjectSyncwa -Service syncwa-api -Key DATABASE_URL -Value $syncwaNew

Write-Host "`n[3/3] evolution-api -> schema sysr (mesmo Postgres CRM/Evolution)" -ForegroundColor Yellow
Set-RailwayVar -Project $ProjectSysr -Service evolution-api -Key DATABASE_CONNECTION_URI -Value $evoNew

Write-Host "`n[4/6] Corrigir _prisma_migrations (Prisma migrate deploy no startup)" -ForegroundColor Yellow
python ferramentas/consolidacao_db/fix_prisma_migrations_cutover.py --database-url $centralUrl --target syncwa
if ($LASTEXITCODE -ne 0) { exit 1 }

$sysrIsoladoUrl = (railway variables --kv -p $ProjectSysr -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''
python ferramentas/consolidacao_db/copiar_prisma_migrations_sysr.py --source-url $sysrIsoladoUrl --target-url $centralUrl
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[5/6] Redeploy syncwa-api + evolution-api" -ForegroundColor Yellow
railway redeploy -p $ProjectSyncwa -s syncwa-api -e production -y
railway redeploy -p $ProjectSysr -s evolution-api -e production -y

Write-Host "`nAguardando redeploy (90s)..." -ForegroundColor Gray
Start-Sleep -Seconds 90

Write-Host "`n[6/6] Health checks ===" -ForegroundColor Cyan
$checks = @(
    @{ Name = "sysr-vendas-api"; Url = "https://sysr-vendas-api-production.up.railway.app/api/health" }
    @{ Name = "syncwa-api"; Url = "https://api.sysr.com.br/health" }
    @{ Name = "evolution-api"; Url = "https://evolution-api-production-8bbb.up.railway.app" }
)

$failed = 0
foreach ($check in $checks) {
    try {
        $resp = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 30
        Write-Host "OK $($check.Name): HTTP $($resp.StatusCode)" -ForegroundColor Green
        if ($resp.Content.Length -lt 500) {
            Write-Host "  $($resp.Content)" -ForegroundColor DarkGray
        }
    } catch {
        $failed++
        Write-Host "FALHA $($check.Name): $($_.Exception.Message)" -ForegroundColor Red
    }
}

if ($failed -gt 0) {
    Write-Host "`nAlguns health checks falharam. Rollback manual via $backupFile" -ForegroundColor Red
    exit 1
}

Write-Host "`nFase 2 concluida. APIs no Postgres central." -ForegroundColor Green
Write-Host "Fase 3: observar 7 dias e desligar Postgres isolados." -ForegroundColor Cyan
