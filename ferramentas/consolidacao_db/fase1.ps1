# Fase 1 - Consolidacao DB: estrutura + dados nos schemas sysr/syncwa
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase1.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ProjectCentral = "7171eee1-2c6e-446a-b7a9-880d3786c51a"
$ProjectSysr = "fe553432-2a22-46cc-b347-ee669ff4aba3"
$ProjectSyncwa = "df858945-8b79-46f2-aad8-980bc4bfc925"

Write-Host "=== Fase 1: Deploy estrutura + migracao de dados ===" -ForegroundColor Cyan

$centralUrl = (railway variables --kv -p $ProjectCentral -s site-record -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
$sysrUrl = (railway variables --kv -p $ProjectSysr -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''
$syncwaUrl = (railway variables --kv -p $ProjectSyncwa -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''

if (-not $centralUrl -or -not $sysrUrl -or -not $syncwaUrl) {
    Write-Host "ERRO: URLs nao encontradas (central/sysr/syncwa)" -ForegroundColor Red
    exit 1
}

# 1) SyncWA: baseline Prisma + dados
Write-Host "`n[1/4] SyncWA: baseline + dados -> schema syncwa" -ForegroundColor Yellow
python ferramentas/consolidacao_db/deploy_baseline.py --database-url $centralUrl --target syncwa --force
if ($LASTEXITCODE -ne 0) { exit 1 }

python ferramentas/consolidacao_db/migrar_schema_pg.py `
    --source-url $syncwaUrl --target-url $centralUrl `
    --source-schema public --target-schema syncwa `
    --skip-schema
if ($LASTEXITCODE -ne 0) { exit 1 }

python ferramentas/consolidacao_db/registrar_prisma_migrations.py --database-url $centralUrl --target syncwa
if ($LASTEXITCODE -ne 0) { exit 1 }

# 2) SysR: dump completo public -> sysr (CRM + Evolution no mesmo Postgres)
Write-Host "`n[2/4] SysR: DDL + dados public -> schema sysr" -ForegroundColor Yellow
python ferramentas/consolidacao_db/migrar_schema_pg.py `
    --source-url $sysrUrl --target-url $centralUrl `
    --source-schema public --target-schema sysr --force
if ($LASTEXITCODE -ne 0) { exit 1 }

python ferramentas/consolidacao_db/registrar_prisma_migrations.py --database-url $centralUrl --target sysr
if ($LASTEXITCODE -ne 0) { exit 1 }

# 3) Smoke tests
Write-Host "`n[3/4] Smoke test SyncWA" -ForegroundColor Yellow
python ferramentas/consolidacao_db/smoke_test_fase1.py `
    --source-url $syncwaUrl --target-url $centralUrl `
    --source-schema public --target-schema syncwa
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[4/4] Smoke test SysR" -ForegroundColor Yellow
python ferramentas/consolidacao_db/smoke_test_fase1.py `
    --source-url $sysrUrl --target-url $centralUrl `
    --source-schema public --target-schema sysr
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`nFase 1 concluida." -ForegroundColor Green
Write-Host "Proximo passo Fase 2: apontar DATABASE_URL das APIs para o central (?schema=sysr / ?schema=syncwa)." -ForegroundColor Cyan
