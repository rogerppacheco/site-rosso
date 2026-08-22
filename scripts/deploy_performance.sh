#!/bin/bash
# Script de Deploy das Melhorias de Performance
# Uso: bash deploy_performance.sh

echo "=========================================="
echo "Deploy de Melhorias de Performance"
echo "Site Record - PostgreSQL"
echo "=========================================="
echo ""

# Verificar se está em produção
if [ "$DJANGO_ENV" != "production" ]; then
    echo "⚠️  AVISO: Este script deve ser executado em PRODUÇÃO"
    read -p "Continuar mesmo assim? (s/N): " confirm
    if [ "$confirm" != "s" ]; then
        echo "Deploy cancelado."
        exit 0
    fi
fi

# 1. Backup do banco
echo "📦 Passo 1: Criando backup do banco..."
BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
pg_dump -U $DB_USER -h $DB_HOST $DB_NAME > $BACKUP_FILE

if [ $? -eq 0 ]; then
    echo "✓ Backup criado: $BACKUP_FILE"
else
    echo "✗ Erro ao criar backup. Deploy cancelado."
    exit 1
fi

# 2. Verificar conexão com banco
echo ""
echo "🔌 Passo 2: Verificando conexão com PostgreSQL..."
python -c "from django.db import connection; connection.ensure_connection(); print('✓ Conexão OK')" 2>&1

if [ $? -ne 0 ]; then
    echo "✗ Erro na conexão. Deploy cancelado."
    exit 1
fi

# 3. Aplicar migrations
echo ""
echo "🔄 Passo 3: Aplicando migrations..."
echo "   (Isso pode levar 5-15 minutos devido ao CREATE INDEX CONCURRENTLY)"
echo ""

python manage.py migrate crm_app --verbosity 2

if [ $? -eq 0 ]; then
    echo "✓ Migrations aplicadas com sucesso"
else
    echo "✗ Erro ao aplicar migrations"
    echo "   Você pode restaurar o backup com:"
    echo "   psql -U $DB_USER -h $DB_HOST $DB_NAME < $BACKUP_FILE"
    exit 1
fi

# 4. Validar índices
echo ""
echo "🔍 Passo 4: Validando índices criados..."
python scripts/validar_performance.py

# 5. Testar endpoints críticos
echo ""
echo "🧪 Passo 5: Testando endpoints críticos..."

# Teste de auditoria
echo "   - Testando /api/vendas/?flow=auditoria"
curl -s -o /dev/null -w "Status: %{http_code}, Tempo: %{time_total}s\n" \
    -H "Authorization: Token $API_TOKEN" \
    "http://localhost:8000/api/vendas/?flow=auditoria&limit=10"

# Teste de esteira
echo "   - Testando /api/vendas/?flow=esteira"
curl -s -o /dev/null -w "Status: %{http_code}, Tempo: %{time_total}s\n" \
    -H "Authorization: Token $API_TOKEN" \
    "http://localhost:8000/api/vendas/?flow=esteira&limit=10"

# 6. Restart do serviço (se necessário)
echo ""
echo "🔄 Passo 6: Reiniciando serviço..."
if command -v systemctl &> /dev/null; then
    sudo systemctl restart gunicorn
    echo "✓ Serviço reiniciado"
else
    echo "⚠️  Reinicie o serviço manualmente"
fi

# 7. Resumo final
echo ""
echo "=========================================="
echo "✅ Deploy Concluído!"
echo "=========================================="
echo ""
echo "📊 Próximos Passos:"
echo "   1. Monitorar logs por 30 minutos"
echo "   2. Testar telas de auditoria/esteira"
echo "   3. Validar tempo de resposta das APIs"
echo "   4. Executar importação OSAB de teste"
echo ""
echo "📁 Backup salvo em: $BACKUP_FILE"
echo ""
echo "📖 Documentação completa:"
echo "   - docs/OTIMIZACAO_PERFORMANCE_POSTGRESQL.md"
echo "   - MELHORIAS_PERFORMANCE_IMPLEMENTADAS.md"
echo ""
echo "🔍 Para análise detalhada de performance:"
echo "   python scripts/validar_performance.py"
echo ""
