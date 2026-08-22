# Finaliza scheduler no projeto correto (pleasing-recreation / site-record).
# Uso: $env:RAILWAY_TOKEN = "..." ; powershell -File scripts\railway_finish_scheduler.ps1
$ErrorActionPreference = "Stop"

$Token = $env:RAILWAY_TOKEN
if (-not $Token) { throw "Defina RAILWAY_TOKEN" }

$ProjectId = "7171eee1-2c6e-446a-b7a9-880d3786c51a"
$EnvId = "8f157a2b-2cad-4084-8cd4-dc384f810fa5"
$WebServiceId = "4e96e4c9-648b-43c2-ad1f-68614ff2a013"
$SchedulerName = "site-record-scheduler"
$GitHubRepo = "rogerppacheco/site-record"
$WrongProjectId = "c5f30c08-b32b-462e-9679-129064a82247"
$WrongSchedulerId = "170bacda-cb83-4b7a-8c0f-5d7fb6416624"

function Invoke-RailwayGql {
    param([string]$Query, [hashtable]$Variables = @{})
    $headers = @{
        Authorization  = "Bearer $Token"
        "Content-Type" = "application/json"
    }
    $payload = @{ query = $Query }
    if ($Variables.Count -gt 0) { $payload.variables = $Variables }
    $json = $payload | ConvertTo-Json -Compress -Depth 20
    $r = Invoke-RestMethod -Uri "https://backboard.railway.com/graphql/v2" -Method Post -Headers $headers -Body $json
    if ($r.errors) { throw ($r.errors | ConvertTo-Json -Compress) }
    return $r.data
}

Write-Host "=== Scheduler site-record (pleasing-recreation) ===" -ForegroundColor Cyan

# Remover scheduler criado por engano no projeto melodious-hope
try {
    Invoke-RailwayGql -Query 'mutation($id: String!) { serviceDelete(id: $id) }' -Variables @{ id = $WrongSchedulerId } | Out-Null
    Write-Host "Removido scheduler incorreto (melodious-hope)." -ForegroundColor Yellow
} catch {
    Write-Host "Scheduler incorreto: $($_.Exception.Message)" -ForegroundColor Gray
}

$project = Invoke-RailwayGql -Query @'
query($id: String!) {
  project(id: $id) {
    services { edges { node { id name } } }
  }
}
'@ -Variables @{ id = $ProjectId }

$schedulerId = $null
foreach ($edge in $project.project.services.edges) {
    if ($edge.node.name -eq $SchedulerName) {
        $schedulerId = $edge.node.id
        break
    }
}

if (-not $schedulerId) {
    $created = Invoke-RailwayGql -Query @'
mutation($input: ServiceCreateInput!) {
  serviceCreate(input: $input) { id name }
}
'@ -Variables @{
        input = @{
            projectId     = $ProjectId
            name          = $SchedulerName
            environmentId = $EnvId
        }
    }
    $schedulerId = $created.serviceCreate.id
    Write-Host "Servico criado: $SchedulerName ($schedulerId)" -ForegroundColor Green
} else {
    Write-Host "Servico ja existe: $SchedulerName ($schedulerId)" -ForegroundColor Green
}

# Variaveis do web (retorno JSON escalar; sem RAILWAY_*)
$varsData = Invoke-RailwayGql -Query @'
query($p: String!, $e: String!, $s: String!) {
  variables(projectId: $p, environmentId: $e, serviceId: $s)
}
'@ -Variables @{ p = $ProjectId; e = $EnvId; s = $WebServiceId }

$webVars = $varsData.variables
if ($webVars -is [string]) { $webVars = $webVars | ConvertFrom-Json }
if ($webVars.PSObject.Properties) {
    $pairs = $webVars.PSObject.Properties
} else {
    $pairs = @($webVars.GetEnumerator() | ForEach-Object { [PSCustomObject]@{ Name = $_.Key; Value = $_.Value } })
}

$copied = 0
foreach ($prop in $pairs) {
    $name = if ($prop.Name) { $prop.Name } else { $prop.Key }
    $value = if ($null -ne $prop.Value) { [string]$prop.Value } else { "" }
    if ($name -match '^RAILWAY_') { continue }
    Invoke-RailwayGql -Query @'
mutation($input: VariableUpsertInput!) {
  variableUpsert(input: $input)
}
'@ -Variables @{
        input = @{
            projectId     = $ProjectId
            environmentId = $EnvId
            serviceId     = $schedulerId
            name          = $name
            value         = $value
        }
    } | Out-Null
    $copied++
}
Write-Host "Variaveis copiadas: $copied" -ForegroundColor Green

# Configurar instancia: repo, dockerfile, start command, config file
Invoke-RailwayGql -Query @'
mutation($input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(input: $input)
}
'@ -Variables @{
    input = @{
        serviceId     = $schedulerId
        environmentId = $EnvId
        source        = @{ repo = $GitHubRepo }
        dockerfilePath = "Dockerfile.scheduler"
        startCommand   = "python manage.py run_scheduler"
        railwayConfigFile = "/railway.scheduler.toml"
    }
} | Out-Null
Write-Host "Instancia configurada (Dockerfile.scheduler + run_scheduler)." -ForegroundColor Green

# Deploy
$deploy = Invoke-RailwayGql -Query @'
mutation($input: ServiceInstanceDeployV2Input!) {
  serviceInstanceDeployV2(input: $input) {
    id status
  }
}
'@ -Variables @{
    input = @{
        serviceId     = $schedulerId
        environmentId = $EnvId
    }
}
Write-Host "Deploy disparado: $($deploy.serviceInstanceDeployV2.id) status=$($deploy.serviceInstanceDeployV2.status)" -ForegroundColor Green

# Atualizar link local do projeto
$configPath = Join-Path $env:USERPROFILE ".railway\config.json"
if (Test-Path $configPath) {
    $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($cfg.projects.'C:\site-record') {
        $cfg.projects.'C:\site-record'.project = $ProjectId
        $cfg.projects.'C:\site-record'.environment = $EnvId
        $cfg.projects.'C:\site-record'.name = "pleasing-recreation"
        $cfg.projects.'C:\site-record'.service = $WebServiceId
    }
    if ($cfg.user) { $cfg.user.token = $Token }
    $cfg | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding utf8NoBOM
}

Write-Host ""
Write-Host "Projeto: pleasing-recreation" -ForegroundColor Cyan
Write-Host "Web: site-record | Scheduler: $SchedulerName" -ForegroundColor Cyan
Write-Host "Confira no painel: Deploy do scheduler + Replicas = 1" -ForegroundColor Yellow
Write-Host "Concluido." -ForegroundColor Green
