# Fase 0 - Consolidacao DB: schemas sysr/syncwa, inventario e backup.
# Uso: powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase0.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ProjectCentral = "7171eee1-2c6e-446a-b7a9-880d3786c51a"
$ProjectSysr = "fe553432-2a22-46cc-b347-ee669ff4aba3"
$ProjectSyncwa = "df858945-8b79-46f2-aad8-980bc4bfc925"
$BackupDir = Join-Path $RepoRoot "backups\consolidacao_db"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "=== Fase 0: Consolidacao DB (schemas sysr + syncwa) ===" -ForegroundColor Cyan

$RailwayCentral = @("-p", $ProjectCentral, "-s", "site-record", "-e", "production")

# 1) Criar schemas no banco central
Write-Host "`n[1/4] Criando schemas sysr e syncwa no banco central..." -ForegroundColor Yellow
railway run @RailwayCentral -- python ferramentas/consolidacao_db/criar_schemas.py
if ($LASTEXITCODE -ne 0) { exit 1 }

# 2) Inventario — central
Write-Host "`n[2/4] Inventario banco central..." -ForegroundColor Yellow
railway run @RailwayCentral -- python ferramentas/consolidacao_db/inventario_banco.py --label central
if ($LASTEXITCODE -ne 0) { exit 1 }

# 3) Inventario — sysr isolado
Write-Host "`n[3/4] Inventario banco sysr-vendas-api (isolado)..." -ForegroundColor Yellow
$sysrUrl = (railway variables --kv -p $ProjectSysr -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''
if (-not $sysrUrl) { Write-Host "ERRO: DATABASE_PUBLIC_URL sysr nao encontrada" -ForegroundColor Red; exit 1 }
$env:DATABASE_URL = $sysrUrl
python ferramentas/consolidacao_db/inventario_banco.py --label sysr_isolado
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) { exit 1 }

# 4) Inventario — syncwa isolado
Write-Host "`n[4/4] Inventario banco syncwa (isolado)..." -ForegroundColor Yellow
$syncwaUrl = (railway variables --kv -p $ProjectSyncwa -s Postgres -e production 2>$null | Where-Object { $_ -match '^DATABASE_PUBLIC_URL=' }) -replace '^DATABASE_PUBLIC_URL=', ''
if (-not $syncwaUrl) { Write-Host "ERRO: DATABASE_PUBLIC_URL syncwa nao encontrada" -ForegroundColor Red; exit 1 }
$env:DATABASE_URL = $syncwaUrl
python ferramentas/consolidacao_db/inventario_banco.py --label syncwa_isolado
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) { exit 1 }

# Backup opcional se pg_dump existir
$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if ($pgDump) {
    Write-Host "`n[Extra] Backup pg_dump banco central..." -ForegroundColor Yellow
    $centralUrl = (railway variables --kv -p $ProjectCentral -s site-record -e production 2>$null | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
    $dumpFile = Join-Path $BackupDir "central_${Stamp}.dump"
    & pg_dump $centralUrl -Fc -f $dumpFile
    Write-Host "Backup: $dumpFile" -ForegroundColor Green
} else {
    Write-Host "`n[Extra] pg_dump nao encontrado - pule backup local ou instale PostgreSQL client." -ForegroundColor Gray
}

Write-Host "`nFase 0 concluida. Relatorios em: $BackupDir" -ForegroundColor Green
Write-Host 'Proximo passo Fase 1 - prisma migrate deploy nos schemas sysr/syncwa no central.' -ForegroundColor Cyan
