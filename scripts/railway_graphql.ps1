param(
    [Parameter(Mandatory = $true)][string]$Query,
    [string]$VariablesJson = "{}"
)
$token = $env:RAILWAY_TOKEN
if (-not $token) { throw "RAILWAY_TOKEN ausente" }
$headers = @{
    Authorization  = "Bearer $token"
    "Content-Type" = "application/json"
}
$body = @{ query = $Query; variables = ($VariablesJson | ConvertFrom-Json) } | ConvertTo-Json -Compress -Depth 20
$r = Invoke-RestMethod -Uri "https://backboard.railway.com/graphql/v2" -Method Post -Headers $headers -Body $body
if ($r.errors) { throw ($r.errors | ConvertTo-Json -Compress) }
return $r.data
