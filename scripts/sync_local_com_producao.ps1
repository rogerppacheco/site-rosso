# Sincroniza o repositório local com a versão em produção (Railway).
# Uso:
#   .\scripts\sync_local_com_producao.ps1              # abre o dashboard e pede o commit
#   .\scripts\sync_local_com_producao.ps1 -Commit a01625b  # sincroniza direto no commit

param(
    [string]$Commit = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "=== Sincronizar local com producao (Railway) ===" -ForegroundColor Cyan
Write-Host ""

if (-not $Commit) {
    Write-Host "No Railway, a versao em producao e o deploy ativo do seu servico." -ForegroundColor Gray
    Write-Host "O commit desse deploy aparece no Dashboard em: Projeto > Servico > Deployments (deploy Active)." -ForegroundColor Gray
    Write-Host ""
    $abrir = Read-Host "Abrir o dashboard do Railway no navegador? (s/n)"
    if ($abrir -eq "s" -or $abrir -eq "S") {
        try {
            railway open
        } catch {
            Write-Host "Se o Railway CLI nao estiver instalado: npm install -g @railway/cli e railway link" -ForegroundColor Yellow
            Start-Process "https://railway.app/dashboard"
        }
    }
    Write-Host ""
    $Commit = Read-Host "Cole o hash do commit do deploy ativo (ex: a01625b)"
    if ([string]::IsNullOrWhiteSpace($Commit)) {
        Write-Host "Nenhum commit informado. Saindo." -ForegroundColor Yellow
        exit 0
    }
}

# Garantir que temos o commit (pode ser hash curto)
Write-Host ""
Write-Host "Buscando do origin..." -ForegroundColor Yellow
git fetch origin 2>&1 | Out-Null

$rev = $null
try {
    $rev = git rev-parse --verify $Commit 2>&1
} catch {}
if (-not $rev -or $rev -match "fatal") {
    Write-Host "Commit '$Commit' nao encontrado. Verifique o hash e se o origin esta atualizado." -ForegroundColor Red
    exit 1
}

Write-Host "Sincronizando main local com $Commit..." -ForegroundColor Yellow
git checkout main 2>&1 | Out-Null
git reset --hard $Commit

Write-Host ""
Write-Host "OK. Seu main local esta agora no mesmo commit que esta em producao no Railway." -ForegroundColor Green
Write-Host "Para atualizar o GitHub (origin/main) com essa versao: git push origin main --force" -ForegroundColor Gray
