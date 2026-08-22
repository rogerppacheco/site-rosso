# Fase 4 - PgBouncer nativo Railway (transaction mode) no Postgres central
# Uso:
#   powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase4_pgbouncer.ps1 -WaitForPooling
#   powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase4_pgbouncer.ps1 -Cutover
#   powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase4_pgbouncer.ps1 -Cutover -Redeploy

param(
    [switch]$WaitForPooling,
    [switch]$Cutover,
    [switch]$Redeploy,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $RepoRoot

$ProjectBanco = "8db60e30-1dde-43f9-afaa-bfc19682fe0b"   # banco-de-dados
$ProjectSite = "7171eee1-2c6e-446a-b7a9-880d3786c51a"    # site-record
$ProjectSysr = "fe553432-2a22-46cc-b347-ee669ff4aba3"
$ProjectSyncwa = "df858945-8b79-46f2-aad8-980bc4bfc925"
$BackupDir = Join-Path $RepoRoot "backups\consolidacao_db"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Get-RailwayVar {
    param(
        [string]$Project,
        [string]$Service,
        [string]$Key
    )
    $line = railway variables --kv -p $Project -s $Service -e production 2>$null |
        Where-Object { $_ -match "^${Key}=" } |
        Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -replace "^${Key}=", "")
}

function Set-RailwayVar {
    param(
        [string]$Project,
        [string]$Service,
        [string]$Key,
        [string]$Value
    )
    if ($DryRun) {
        Write-Host "  [DRY-RUN] $Project / $Service : $Key" -ForegroundColor DarkGray
        return
    }
    $Value | railway variable set $Key --stdin -p $Project -s $Service -e production
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

function Get-PgBouncerServiceName {
    $json = railway service list -p $ProjectBanco -e production --json 2>$null
    if (-not $json) { return $null }
    $services = $json | ConvertFrom-Json
    foreach ($svc in $services) {
        $name = $svc.name
        if ($name -match 'pgbouncer') { return $name }
    }
    return $null
}

function Get-PoolingUrls {
    # Modo nativo (Postgres plugin novo): unpooled no proprio Postgres
    $nativeUnpooled = Get-RailwayVar -Project $ProjectBanco -Service "Postgres" -Key "DATABASE_PUBLIC_UNPOOLED_URL"
    if ($nativeUnpooled) {
        return @{
            mode = "native"
            pooledPublic = (Get-RailwayVar -Project $ProjectBanco -Service "Postgres" -Key "DATABASE_PUBLIC_URL")
            unpooledPublic = $nativeUnpooled
        }
    }

    # Modo template (postgres-ssl:17 — seu caso): servico PgBouncer separado
    $pgbSvc = Get-PgBouncerServiceName
    if (-not $pgbSvc) { return $null }

    $pooled = Get-RailwayVar -Project $ProjectBanco -Service $pgbSvc -Key "DATABASE_PUBLIC_URL"
    $unpooled = Get-RailwayVar -Project $ProjectBanco -Service "Postgres" -Key "DATABASE_PUBLIC_URL"
    if (-not $pooled -or -not $unpooled) { return $null }

    return @{
        mode = "template"
        pgbouncerService = $pgbSvc
        pooledPublic = $pooled
        unpooledPublic = $unpooled
    }
}

function Test-PoolingEnabled {
    return [bool](Get-PoolingUrls)
}

function Show-TemplateInstructions {
    Write-Host ''
    Write-Host '=== PgBouncer via TEMPLATE (seu Postgres postgres-ssl:17) ===' -ForegroundColor Cyan
    Write-Host @'
Seu Postgres e o template classico (postgres-ssl). Ele NAO tem o menu
"Database -> Config -> Connection Pooling". Esse menu so existe no Postgres
gerenciado novo do Railway.

Use o template PgBouncer (recomendado pela equipe Railway):

1. Abra o projeto banco-de-dados no painel
2. Clique com botao direito no canvas (area vazia) -> Add -> Template
3. Busque "PgBouncer" e escolha o template (codigo OpUzwe)
   Link direto: https://railway.com/template/OpUzwe
4. ANTES de clicar Deploy Template:
   - Abra as variaveis do template
   - POSTGRESQL_* devem referenciar o servico "Postgres" (fundo cinza = linkado)
   - Se nao linkar sozinho: Raw Editor do PgBouncer e troque namespace "Postgres"
5. Adicione variavel no PgBouncer: PGBOUNCER_POOL_MODE=transaction
6. Deploy Template
7. No servico PgBouncer -> Settings -> Networking -> gere dominio TCP publico
   (igual o Postgres tem maglev.proxy.rlwy.net:PORTA)
8. Confirme que o PgBouncer ficou Online e tem DATABASE_PUBLIC_URL

Unpooled (migrations): continua o DATABASE_PUBLIC_URL do servico Postgres original.
Pooled (runtime): DATABASE_PUBLIC_URL do servico PgBouncer novo.

Depois rode: fase4_pgbouncer.ps1 -Cutover -Redeploy
'@ -ForegroundColor Gray
    Write-Host "Painel: https://railway.com/project/$ProjectBanco" -ForegroundColor Gray
}

Write-Host "=== Fase 4: PgBouncer (Postgres central) ===" -ForegroundColor Cyan

if ($WaitForPooling -and -not $Cutover) {
    Show-TemplateInstructions
    $maxWait = 600
    $elapsed = 0
    while ($elapsed -lt $maxWait) {
        $urls = Get-PoolingUrls
        if ($urls) {
            Write-Host ''
            Write-Host "PgBouncer detectado (modo $($urls.mode))." -ForegroundColor Green
            break
        }
        Write-Host "Aguardando servico PgBouncer... (${elapsed}s / ${maxWait}s)" -ForegroundColor Yellow
        Start-Sleep -Seconds 15
        $elapsed += 15
    }
    if (-not (Get-PoolingUrls)) {
        Write-Host "ERRO: PgBouncer nao detectado apos ${maxWait}s." -ForegroundColor Red
        exit 1
    }
    Write-Host 'Proximo passo: fase4_pgbouncer.ps1 -Cutover com -Redeploy se desejar' -ForegroundColor Cyan
    exit 0
}

if (-not $Cutover) {
    Write-Host @"

Uso:
  -WaitForPooling  Instrucoes + aguarda servico PgBouncer no projeto
  -Cutover          Atualiza URLs pooled/unpooled em todos os servicos
  -Redeploy         Redeploy apos cutover (requer -Cutover)
  -DryRun           Simula sem alterar Railway

Exemplo completo:
  .\fase4_pgbouncer.ps1 -WaitForPooling
  .\fase4_pgbouncer.ps1 -Cutover -Redeploy
"@ -ForegroundColor Gray
    if (-not (Test-PoolingEnabled)) {
        Write-Host ''
        Write-Host 'Status: PgBouncer AINDA NAO detectado.' -ForegroundColor Yellow
        Write-Host 'Seu Postgres e template postgres-ssl (sem menu Connection Pooling).' -ForegroundColor Yellow
        Write-Host 'Rode com -WaitForPooling para ver o passo a passo do template.' -ForegroundColor Yellow
    } else {
        $u = Get-PoolingUrls
        Write-Host ''
        Write-Host "Status: PgBouncer OK (modo $($u.mode)) - pronto para Cutover." -ForegroundColor Green
    }
    exit 0
}

if (-not (Test-PoolingEnabled)) {
    Write-Host 'ERRO: PgBouncer ausente. Rode -WaitForPooling e siga o template OpUzwe.' -ForegroundColor Red
    exit 1
}

$pooling = Get-PoolingUrls
$pooledPublic = $pooling.pooledPublic
$unpooledPublic = $pooling.unpooledPublic

Write-Host ''
Write-Host "Modo: $($pooling.mode)" -ForegroundColor Gray
if ($pooling.pgbouncerService) {
    Write-Host "  servico pooler: $($pooling.pgbouncerService)" -ForegroundColor Gray
}

Write-Host "`nURLs central:" -ForegroundColor Gray
Write-Host "  pooled public:   $($pooledPublic.Substring(0, [Math]::Min(60, $pooledPublic.Length)))..."
Write-Host "  unpooled public: $($unpooledPublic.Substring(0, [Math]::Min(60, $unpooledPublic.Length)))..."

$djangoUrls = python ferramentas/consolidacao_db/pgbouncer_urls.py --pooled-public $pooledPublic --unpooled-public $unpooledPublic --schema public | ConvertFrom-Json
$sysrUrls = python ferramentas/consolidacao_db/pgbouncer_urls.py --pooled-public $pooledPublic --unpooled-public $unpooledPublic --schema sysr | ConvertFrom-Json
$syncwaUrls = python ferramentas/consolidacao_db/pgbouncer_urls.py --pooled-public $pooledPublic --unpooled-public $unpooledPublic --schema syncwa | ConvertFrom-Json

$siteServices = @("site-record", "site-record-webhook", "site-record-pap", "site-record-scheduler")

$backup = @{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    pooled_public = $pooledPublic
    unpooled_public = $unpooledPublic
    django = $djangoUrls.django
    sysr = $sysrUrls.prisma
    syncwa = $syncwaUrls.prisma
    site_services_before = @{}
}
foreach ($svc in $siteServices) {
    $backup.site_services_before[$svc] = @{
        DATABASE_URL = (Get-RailwayVar -Project $ProjectSite -Service $svc -Key "DATABASE_URL")
        DATABASE_UNPOOLED_URL = (Get-RailwayVar -Project $ProjectSite -Service $svc -Key "DATABASE_UNPOOLED_URL")
    }
}
$backupFile = Join-Path $BackupDir "pgbouncer_cutover_$Stamp.json"
$backup | ConvertTo-Json -Depth 6 | Set-Content -Path $backupFile -Encoding UTF8
Write-Host "Backup: $backupFile" -ForegroundColor Gray

Write-Host ''
Write-Host '[1/4] site-record (4 servicos Django): pooled + unpooled' -ForegroundColor Yellow
foreach ($svc in $siteServices) {
    Write-Host "  servico: $svc" -ForegroundColor Gray
    Set-RailwayVar -Project $ProjectSite -Service $svc -Key "DATABASE_URL" -Value $djangoUrls.django.DATABASE_URL
    Set-RailwayVar -Project $ProjectSite -Service $svc -Key "DATABASE_UNPOOLED_URL" -Value $djangoUrls.django.DATABASE_UNPOOLED_URL
    Set-RailwayVar -Project $ProjectSite -Service $svc -Key "PGBOUNCER_ENABLED" -Value "true"
    Set-RailwayVar -Project $ProjectSite -Service $svc -Key "DB_CONN_MAX_AGE" -Value "0"
}

Write-Host ''
Write-Host '[2/4] sysr-vendas-api (Prisma schema sysr)' -ForegroundColor Yellow
Set-RailwayVar -Project $ProjectSysr -Service "sysr-vendas-api" -Key "DATABASE_URL" -Value $sysrUrls.prisma.DATABASE_URL
Set-RailwayVar -Project $ProjectSysr -Service "sysr-vendas-api" -Key "DATABASE_DIRECT_URL" -Value $sysrUrls.prisma.DATABASE_DIRECT_URL

Write-Host ''
Write-Host '[3/4] syncwa-api (Prisma schema syncwa)' -ForegroundColor Yellow
Set-RailwayVar -Project $ProjectSyncwa -Service "syncwa-api" -Key "DATABASE_URL" -Value $syncwaUrls.prisma.DATABASE_URL
Set-RailwayVar -Project $ProjectSyncwa -Service "syncwa-api" -Key "DATABASE_DIRECT_URL" -Value $syncwaUrls.prisma.DATABASE_DIRECT_URL

Write-Host ''
Write-Host '[4/4] evolution-api (Prisma schema sysr)' -ForegroundColor Yellow
Set-RailwayVar -Project $ProjectSysr -Service "evolution-api" -Key "DATABASE_CONNECTION_URI" -Value $sysrUrls.prisma.DATABASE_URL
Set-RailwayVar -Project $ProjectSysr -Service "evolution-api" -Key "DATABASE_DIRECT_URL" -Value $sysrUrls.prisma.DATABASE_DIRECT_URL

Write-Host "`nSmoke test (unpooled)..." -ForegroundColor Yellow
python ferramentas/consolidacao_db/smoke_test_pgbouncer.py --pooled-url $djangoUrls.django.DATABASE_URL --unpooled-url $djangoUrls.django.DATABASE_UNPOOLED_URL
if ($LASTEXITCODE -ne 0) { exit 1 }

if ($Redeploy) {
    Write-Host "`nRedeploy servicos..." -ForegroundColor Yellow
    foreach ($svc in $siteServices) {
        railway redeploy -p $ProjectSite -s $svc -e production -y
    }
    railway redeploy -p $ProjectSysr -s sysr-vendas-api -e production -y
    railway redeploy -p $ProjectSysr -s evolution-api -e production -y
    railway redeploy -p $ProjectSyncwa -s syncwa-api -e production -y
    Write-Host "Redeploys disparados." -ForegroundColor Green
} else {
    Write-Host "`nCutover de variaveis concluido. Rode com -Redeploy para aplicar nos containers." -ForegroundColor Cyan
}

Write-Host "`nFase 4 cutover concluida." -ForegroundColor Green
