# Deploy das Melhorias de Performance - Windows PowerShell
# Uso: .\deploy_performance.ps1

Write-Host "==========================================`n" -ForegroundColor Cyan
Write-Host "Deploy de Melhorias de Performance" -ForegroundColor Cyan
Write-Host "Site Rosso - PostgreSQL" -ForegroundColor Cyan
Write-Host "==========================================`n" -ForegroundColor Cyan

# 1. Verificar ambiente
Write-Host "📋 Passo 1: Verificando ambiente..." -ForegroundColor Yellow

if ($env:DATABASE_URL -notmatch "postgres") {
    Write-Host "⚠️  AVISO: Variável DATABASE_URL não detectada ou não é PostgreSQL" -ForegroundColor Red
    $confirm = Read-Host "Continuar mesmo assim? (s/N)"
    if ($confirm -ne "s") {
        Write-Host "Deploy cancelado." -ForegroundColor Red
        exit 0
    }
}

# 2. Backup do banco (se em produção com acesso direto)
Write-Host "`n📦 Passo 2: Backup do banco..." -ForegroundColor Yellow
$backupFile = "backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"

Write-Host "⚠️  Certifique-se de ter um backup recente do banco de dados!" -ForegroundColor Yellow
Write-Host "   Se estiver usando um serviço gerenciado (AWS RDS, Azure, etc)," -ForegroundColor Yellow
Write-Host "   faça o backup pelo painel do provedor." -ForegroundColor Yellow
$confirm = Read-Host "`nBackup confirmado? (s/N)"
if ($confirm -ne "s") {
    Write-Host "Deploy cancelado. Faça o backup antes de continuar." -ForegroundColor Red
    exit 0
}

# 3. Verificar conexão com banco
Write-Host "`n🔌 Passo 3: Verificando conexão com PostgreSQL..." -ForegroundColor Yellow
python -c "from django.db import connection; connection.ensure_connection(); print('✓ Conexão OK')" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Erro na conexão. Deploy cancelado." -ForegroundColor Red
    exit 1
}

# 4. Aplicar migrations
Write-Host "`n🔄 Passo 4: Aplicando migrations..." -ForegroundColor Yellow
Write-Host "   (Isso pode levar 5-15 minutos devido ao CREATE INDEX CONCURRENTLY)" -ForegroundColor Gray
Write-Host ""

python manage.py migrate crm_app --verbosity 2

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Migrations aplicadas com sucesso" -ForegroundColor Green
} else {
    Write-Host "✗ Erro ao aplicar migrations" -ForegroundColor Red
    Write-Host "   Restaure o backup se necessário" -ForegroundColor Red
    exit 1
}

# 5. Validar índices
Write-Host "`n🔍 Passo 5: Validando índices criados..." -ForegroundColor Yellow
python scripts\validar_performance.py

# 6. Resumo final
Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "✅ Deploy Concluído!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 Próximos Passos:" -ForegroundColor Yellow
Write-Host "   1. Acessar a aplicação e testar as telas" -ForegroundColor White
Write-Host "   2. Monitorar logs por 30 minutos" -ForegroundColor White
Write-Host "   3. Validar tempo de resposta (esperado < 500ms)" -ForegroundColor White
Write-Host "   4. Executar importação OSAB de teste" -ForegroundColor White
Write-Host ""
Write-Host "📖 Documentação completa:" -ForegroundColor Yellow
Write-Host "   - docs\OTIMIZACAO_PERFORMANCE_POSTGRESQL.md" -ForegroundColor White
Write-Host "   - MELHORIAS_PERFORMANCE_IMPLEMENTADAS.md" -ForegroundColor White
Write-Host ""
Write-Host "🔍 Para análise detalhada de performance:" -ForegroundColor Yellow
Write-Host "   python scripts\validar_performance.py" -ForegroundColor White
Write-Host ""

# Pausar para usuário ler
Read-Host "Pressione Enter para finalizar"
