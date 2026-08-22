param(
    [string]$OutputDir = "backups",
    [switch]$IncludeSecrets
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Parse-DbUrl {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $null
    }

    try {
        $uri = [System.Uri]$Url
        return [ordered]@{
            raw = $Url
            scheme = $uri.Scheme
            host = $uri.Host
            port = $uri.Port
            database = $uri.AbsolutePath.TrimStart("/")
            username = $uri.UserInfo.Split(":")[0]
            has_password = ($uri.UserInfo -like "*:*")
        }
    }
    catch {
        return [ordered]@{
            raw = $Url
            parse_error = "URL invalida para parser Uri"
        }
    }
}

function Mask-Secrets {
    param([hashtable]$Data)

    $copy = @{}
    foreach ($key in $Data.Keys) {
        $value = $Data[$key]
        if ($null -eq $value) {
            $copy[$key] = $null
            continue
        }

        if ($key -match "PASSWORD|TOKEN|SECRET|URL") {
            $copy[$key] = "[REDACTED]"
        }
        else {
            $copy[$key] = $value
        }
    }
    return $copy
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$targetDir = Join-Path $repoRoot $OutputDir
if (-not (Test-Path $targetDir)) {
    New-Item -Path $targetDir -ItemType Directory | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$jsonFile = Join-Path $targetDir "railway_db_variables_$timestamp.json"
$txtFile = Join-Path $targetDir "railway_db_variables_$timestamp.txt"

$databaseUrl = $env:DATABASE_URL
$databasePublicUrl = $env:DATABASE_PUBLIC_URL
$postgresUser = $env:POSTGRES_USER
$postgresDb = $env:POSTGRES_DB
$postgresPassword = $env:POSTGRES_PASSWORD

$varsRaw = @{
    DATABASE_URL = $databaseUrl
    DATABASE_PUBLIC_URL = $databasePublicUrl
    POSTGRES_USER = $postgresUser
    POSTGRES_PASSWORD = $postgresPassword
    POSTGRES_DB = $postgresDb
    PGHOST = $env:PGHOST
    PGPORT = $env:PGPORT
    PGUSER = $env:PGUSER
    PGPASSWORD = $env:PGPASSWORD
    PGDATABASE = $env:PGDATABASE
}

$varsOutput = $varsRaw
if (-not $IncludeSecrets) {
    $varsOutput = Mask-Secrets -Data $varsRaw
}

$report = [ordered]@{
    generated_at = (Get-Date).ToString("s")
    in_railway_shell = -not [string]::IsNullOrWhiteSpace($databaseUrl)
    selected_database_hint = if ($databasePublicUrl) { "DATABASE_PUBLIC_URL" } elseif ($databaseUrl) { "DATABASE_URL" } else { "nenhuma" }
    parsed_database_url = Parse-DbUrl -Url $databaseUrl
    parsed_database_public_url = Parse-DbUrl -Url $databasePublicUrl
    raw_variables = $varsOutput
}

$report | ConvertTo-Json -Depth 6 | Out-File -FilePath $jsonFile -Encoding utf8

$lines = @()
$lines += "Relatorio Railway DB Variables"
$lines += "Gerado em: $($report.generated_at)"
$lines += "Em railway shell: $($report.in_railway_shell)"
$lines += "Variavel preferida para acesso externo: DATABASE_PUBLIC_URL"
$lines += ""
$lines += "Resumo:"
$lines += "- DATABASE_URL host: $($report.parsed_database_url.host)"
$lines += "- DATABASE_URL db: $($report.parsed_database_url.database)"
$lines += "- DATABASE_PUBLIC_URL host: $($report.parsed_database_public_url.host)"
$lines += "- DATABASE_PUBLIC_URL db: $($report.parsed_database_public_url.database)"
$lines += ""
$lines += "Arquivo JSON completo: $jsonFile"
$lines += "Observacao: segredos redigidos por padrao."

$lines | Out-File -FilePath $txtFile -Encoding utf8

Write-Host "Relatorio criado com sucesso:"
Write-Host "- $jsonFile"
Write-Host "- $txtFile"
if (-not $IncludeSecrets) {
    Write-Host "Segredos foram redigidos. Use -IncludeSecrets se realmente precisar."
}
