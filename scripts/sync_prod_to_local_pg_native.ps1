param(
    [string]$ProdDatabaseUrl,
    [string]$LocalDatabaseUrl,
    [switch]$NoPrompt
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

function Invoke-External {
    param(
        [string]$Exe,
        [string[]]$Arguments
    )

    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: $Exe $($Arguments -join ' ')"
    }
}

function Decode-UrlComponent {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }

    return [System.Uri]::UnescapeDataString($Value)
}

function Parse-DbUrl {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        throw "URL de banco vazia."
    }

    if ($Url -notmatch '^(postgres|postgresql)://') {
        throw "A URL '$Url' nao eh PostgreSQL valida."
    }

    $uri = [System.Uri]$Url
    if ([string]::IsNullOrWhiteSpace($uri.Host)) {
        throw "Host nao encontrado na URL: $Url"
    }
    if ([string]::IsNullOrWhiteSpace($uri.AbsolutePath) -or $uri.AbsolutePath -eq "/") {
        throw "Nome do banco nao encontrado na URL: $Url"
    }

    $userInfoParts = $uri.UserInfo.Split(":", 2)
    $username = Decode-UrlComponent -Value $userInfoParts[0]
    $password = $null
    if ($userInfoParts.Length -gt 1) {
        $password = Decode-UrlComponent -Value $userInfoParts[1]
    }

    return [ordered]@{
        host = $uri.Host
        port = $(if ($uri.Port -gt 0) { $uri.Port } else { 5432 })
        database = $uri.AbsolutePath.TrimStart("/")
        username = $username
        password = $password
        raw = $Url
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$resolvedProdUrl = $ProdDatabaseUrl
if ([string]::IsNullOrWhiteSpace($resolvedProdUrl)) { $resolvedProdUrl = $env:DATABASE_PUBLIC_URL }
if ([string]::IsNullOrWhiteSpace($resolvedProdUrl)) { $resolvedProdUrl = $env:PROD_DATABASE_URL }
if ([string]::IsNullOrWhiteSpace($resolvedProdUrl)) { $resolvedProdUrl = $env:DATABASE_URL }
if ([string]::IsNullOrWhiteSpace($resolvedProdUrl)) {
    throw "Nao encontrei URL de producao. Informe -ProdDatabaseUrl ou defina DATABASE_PUBLIC_URL."
}

$resolvedLocalUrl = $LocalDatabaseUrl
if ([string]::IsNullOrWhiteSpace($resolvedLocalUrl)) { $resolvedLocalUrl = $env:LOCAL_DATABASE_URL }
if ([string]::IsNullOrWhiteSpace($resolvedLocalUrl)) {
    throw "Nao encontrei URL local. Informe -LocalDatabaseUrl ou defina LOCAL_DATABASE_URL."
}

$prod = Parse-DbUrl -Url $resolvedProdUrl
$local = Parse-DbUrl -Url $resolvedLocalUrl

if ($prod.host -eq "host" -or $prod.database -eq "banco") {
    throw "URL de producao parece placeholder. Informe a URL real."
}

$pgDumpPath = (Get-Command pg_dump -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
$pgRestorePath = (Get-Command pg_restore -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
$psqlPath = (Get-Command psql -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)

if (-not $pgDumpPath) { throw "pg_dump nao encontrado no PATH. Instale PostgreSQL client tools." }
if (-not $pgRestorePath) { throw "pg_restore nao encontrado no PATH. Instale PostgreSQL client tools." }
if (-not $psqlPath) { throw "psql nao encontrado no PATH. Instale PostgreSQL client tools." }

$backupsDir = Join-Path $repoRoot "backups"
if (-not (Test-Path $backupsDir)) {
    New-Item -Path $backupsDir -ItemType Directory | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpFile = Join-Path $backupsDir "prod_pg_dump_$timestamp.dump"

Write-Host "Repositorio: $repoRoot"
Write-Host "Origem (producao): $($prod.host):$($prod.port)/$($prod.database)"
Write-Host "Destino (local): $($local.host):$($local.port)/$($local.database)"
Write-Host "Arquivo dump: $dumpFile"

Confirm-OrExit -Prompt "Isso vai APAGAR o banco local de destino e restaurar com dados de producao" -Skip:$NoPrompt

$previousPgPassword = $env:PGPASSWORD

try {
    Write-Step "Gerando dump nativo da producao (pg_dump custom format)"
    $env:PGPASSWORD = $prod.password
    Invoke-External -Exe $pgDumpPath -Arguments @(
        "-h", $prod.host,
        "-p", "$($prod.port)",
        "-U", $prod.username,
        "-d", $prod.database,
        "-F", "c",
        "-f", $dumpFile,
        "--no-owner",
        "--no-privileges",
        "--verbose"
    )

    if (-not (Test-Path $dumpFile) -or ((Get-Item $dumpFile).Length -eq 0)) {
        throw "Dump nao foi gerado corretamente em: $dumpFile"
    }

    Write-Step "Recriando banco local de destino"
    $env:PGPASSWORD = $local.password
    Invoke-External -Exe $psqlPath -Arguments @(
        "-h", $local.host,
        "-p", "$($local.port)",
        "-U", $local.username,
        "-d", "postgres",
        "-v", "ON_ERROR_STOP=1",
        "-c", "DROP DATABASE IF EXISTS ""$($local.database)"";"
    )
    Invoke-External -Exe $psqlPath -Arguments @(
        "-h", $local.host,
        "-p", "$($local.port)",
        "-U", $local.username,
        "-d", "postgres",
        "-v", "ON_ERROR_STOP=1",
        "-c", "CREATE DATABASE ""$($local.database)"";"
    )

    Write-Step "Restaurando dump no banco local (pg_restore)"
    Invoke-External -Exe $pgRestorePath -Arguments @(
        "-h", $local.host,
        "-p", "$($local.port)",
        "-U", $local.username,
        "-d", $local.database,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--verbose",
        $dumpFile
    )

    Write-Step "Conferencia basica (contagem de tabelas)"
    Invoke-External -Exe $psqlPath -Arguments @(
        "-h", $local.host,
        "-p", "$($local.port)",
        "-U", $local.username,
        "-d", $local.database,
        "-v", "ON_ERROR_STOP=1",
        "-c", "SELECT COUNT(*) AS total_tabelas FROM pg_tables WHERE schemaname='public';"
    )

    Write-Host ""
    Write-Host "Sincronizacao nativa concluida com sucesso." -ForegroundColor Green
    Write-Host "Dump salvo em: $dumpFile"
}
finally {
    if ($null -ne $previousPgPassword) {
        $env:PGPASSWORD = $previousPgPassword
    }
    else {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}
