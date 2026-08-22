param(
    [switch]$NoPrompt,
    [string]$ProdDatabaseUrl,
    [string]$LocalDatabaseUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Confirm-OrExit {
    param(
        [string]$Prompt,
        [switch]$Skip
    )

    if ($Skip) {
        return
    }

    $answer = Read-Host "$Prompt (digite SIM para continuar)"
    if ($answer -ne "SIM") {
        throw "Operacao cancelada pelo usuario."
    }
}

function Invoke-ManagePy {
    param(
        [string]$PythonPath,
        [string[]]$Arguments
    )

    & $PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: python $($Arguments -join ' ')"
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    throw "Python do venv nao encontrado em '.venv\Scripts\python.exe'. Ative/crie o venv antes."
}

# Prioridade de origem da URL de producao:
# 1) parametro -ProdDatabaseUrl
# 2) env DATABASE_PUBLIC_URL (Railway publico, ideal para execucao local)
# 3) env PROD_DATABASE_URL
# 4) env DATABASE_URL
$resolvedProdDatabaseUrl = $ProdDatabaseUrl
if ([string]::IsNullOrWhiteSpace($resolvedProdDatabaseUrl)) {
    $resolvedProdDatabaseUrl = $env:DATABASE_PUBLIC_URL
}
if ([string]::IsNullOrWhiteSpace($resolvedProdDatabaseUrl)) {
    $resolvedProdDatabaseUrl = $env:PROD_DATABASE_URL
}
if ([string]::IsNullOrWhiteSpace($resolvedProdDatabaseUrl)) {
    $resolvedProdDatabaseUrl = $env:DATABASE_URL
}

if ([string]::IsNullOrWhiteSpace($resolvedProdDatabaseUrl)) {
    throw "Nao encontrei URL de producao. Informe -ProdDatabaseUrl ou defina PROD_DATABASE_URL / DATABASE_PUBLIC_URL."
}

if ($resolvedProdDatabaseUrl -notmatch '^(postgres|postgresql|mysql|mysql2|mssql|oracle|sqlite)://') {
    throw "URL de producao invalida. Exemplo esperado: postgres://usuario:senha@host:5432/banco"
}

# Evita placeholders acidentais como usuario/senha/host/banco
$placeholderPattern = '://[^:]+:[^@]+@[^/:]+(?::\d+)?/[^/?]+'
if ($resolvedProdDatabaseUrl -match $placeholderPattern) {
    $candidateUser = $resolvedProdDatabaseUrl.Split("://")[1].Split(":")[0]
    $candidateHost = $resolvedProdDatabaseUrl.Split("@")[-1].Split(":")[0].Split("/")[0]
    $candidateDb = $resolvedProdDatabaseUrl.Split("/")[-1]
    if ($candidateUser -eq "usuario" -or $candidateHost -eq "host" -or $candidateDb -eq "banco") {
        throw "URL de producao parece placeholder (usuario/host/banco). Informe a URL real."
    }
}

$resolvedLocalDatabaseUrl = $LocalDatabaseUrl
if ([string]::IsNullOrWhiteSpace($resolvedLocalDatabaseUrl)) {
    $resolvedLocalDatabaseUrl = $env:LOCAL_DATABASE_URL
}

$localTargetLabel = "SQLite (db.sqlite3)"
if (-not [string]::IsNullOrWhiteSpace($resolvedLocalDatabaseUrl)) {
    if ($resolvedLocalDatabaseUrl -notmatch '^(postgres|postgresql|mysql|mysql2|mssql|oracle|sqlite)://') {
        throw "LOCAL_DATABASE_URL invalida. Exemplo esperado: postgresql://usuario:senha@localhost:5432/banco_local"
    }
    $localTargetLabel = $resolvedLocalDatabaseUrl
}

$backupsDir = Join-Path $repoRoot "backups"
if (-not (Test-Path $backupsDir)) {
    New-Item -Path $backupsDir -ItemType Directory | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpFile = Join-Path $backupsDir "prod_dump_$timestamp.json"

Write-Host "Repositorio: $repoRoot"
Write-Host "Arquivo de dump: $dumpFile"
Write-Host "Banco local alvo: $localTargetLabel"

Confirm-OrExit -Prompt "Isso vai APAGAR os dados locais e substituir por dados de producao" -Skip:$NoPrompt

$originalDatabaseUrl = $env:DATABASE_URL
$originalJawsDbUrl = $env:JAWSDB_URL

try {
    Write-Step "Exportando dados de producao para JSON"
    $env:DATABASE_URL = $resolvedProdDatabaseUrl
    $env:JAWSDB_URL = ""

    Invoke-ManagePy -PythonPath $pythonPath -Arguments @("manage.py", "dumpdata", "--output", $dumpFile, "--indent", "2")
    if (-not (Test-Path $dumpFile) -or ((Get-Item $dumpFile).Length -eq 0)) {
        throw "Dump nao foi gerado corretamente em: $dumpFile"
    }

    Write-Step "Preparando banco local"
    if ([string]::IsNullOrWhiteSpace($resolvedLocalDatabaseUrl)) {
        # Forca SQLite mesmo se existir DATABASE_URL/JAWSDB_URL no arquivo .env
        $env:DATABASE_URL = ""
        $env:JAWSDB_URL = ""
    }
    else {
        # Usa banco local configurado (ex.: PostgreSQL local)
        $env:DATABASE_URL = $resolvedLocalDatabaseUrl
        $env:JAWSDB_URL = ""
    }

    Invoke-ManagePy -PythonPath $pythonPath -Arguments @("manage.py", "migrate", "--noinput")
    Invoke-ManagePy -PythonPath $pythonPath -Arguments @("manage.py", "flush", "--noinput")

    Write-Step "Importando dump de producao no banco local"
    Invoke-ManagePy -PythonPath $pythonPath -Arguments @("manage.py", "loaddata", $dumpFile)

    Write-Step "Conferencia final"
    Invoke-ManagePy -PythonPath $pythonPath -Arguments @("manage.py", "check")

    Write-Host ""
    Write-Host "Sincronizacao concluida com sucesso." -ForegroundColor Green
    Write-Host "Dump salvo em: $dumpFile"
}
finally {
    if ($null -ne $originalDatabaseUrl) {
        $env:DATABASE_URL = $originalDatabaseUrl
    }
    else {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    }

    if ($null -ne $originalJawsDbUrl) {
        $env:JAWSDB_URL = $originalJawsDbUrl
    }
    else {
        Remove-Item Env:JAWSDB_URL -ErrorAction SilentlyContinue
    }
}
