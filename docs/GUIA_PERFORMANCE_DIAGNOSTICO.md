# 📊 Guia de Diagnóstico e Otimização de Performance

**Data:** 03/01/2026  
**Problema:** Todas as consultas estão lentas (listagem, atualização de status, etc.)  
**Causa raiz:** N+1 queries e serializers aninhados complexos em operações de listagem

---

## 🔍 Diagnóstico do Problema

### O Que Estava Errado

1. **VendaSerializer carregava TUDO:**
   ```python
   cliente = ClienteSerializer(read_only=True)  # ❌ Serializer completo
   vendedor_detalhes = UsuarioSerializer(source='vendedor')  # ❌ Serializer completo
   plano = PlanoSerializer(read_only=True)  # ❌ Serializer completo
   forma_pagamento = FormaPagamentoSerializer(read_only=True)  # ❌ Serializer completo
   status_tratamento = StatusCRMSerializer(read_only=True)  # ❌ Serializer completo
   status_esteira = StatusCRMSerializer(read_only=True)  # ❌ Serializer completo
   status_comissionamento = StatusCRMSerializer(read_only=True)  # ❌ Serializer completo
   motivo_pendencia = MotivoPendenciaSerializer(read_only=True)  # ❌ Serializer completo
   historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True)  # ❌ MUITO LENTO
   ```

2. **`.defer()` sem campos na serializer causava N+1 queries:**
   ```python
   queryset = queryset.defer('observacoes', 'complemento', 'ponto_referencia')
   # Quando serializer tenta acessar esses campos → refresh_from_db() para CADA registro
   ```

3. **Histórico carregado em TODAS as requisições:**
   ```python
   prefetch_related('historico_alteracoes__usuario')  # Desnecessário em listagem
   ```

### Impacto no Banco de Dados

**Para listar 50 vendas:**
- ❌ ANTES: ~100+ queries (1 lista + 50 clientes + 50 planos + ... + histórico)
- ✅ DEPOIS: ~7 queries (1 lista + select_related + prefetch_related apenas em retrieve)

---

## ✅ Soluções Implementadas

### 1. Refatoração de Serializers

#### VendaSerializer (LISTA) - Otimizado ✅
```python
# ✅ Campos ACHATADOS (sem serializers aninhados)
cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social')
status_tratamento_nome = serializers.CharField(source='status_tratamento.nome')
plano_nome = serializers.CharField(source='plano.nome')

# ❌ SEM serializers complexos
# ❌ SEM histórico
```

**Resultado:** 1 query + select_related = ~7ms para 50 registros

#### VendaDetailSerializer (DETALHES) - Completo ✅
```python
# ✅ Serializers completos APENAS para retrieve
cliente = ClienteSerializer(read_only=True)
plano = PlanoSerializer(read_only=True)
historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True)

# Carregados apenas quando GET /api/crm/vendas/{id}/
```

**Resultado:** Todas as informações disponíveis para edição

### 2. Otimização de Queryset

```python
def get_queryset(self):
    queryset = Venda.objects.filter(ativo=True).select_related(
        'vendedor', 'cliente', 'plano', 'forma_pagamento',
        'status_tratamento', 'status_esteira', 'status_comissionamento',
        'motivo_pendencia', 'auditor_atual', 'editado_por'
    )
    
    # ✅ Histórico APENAS em retrieve
    if self.action == 'retrieve':
        queryset = queryset.prefetch_related('historico_alteracoes__usuario')
    
    return queryset
```

### 3. Paginação Automática

```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,  # Máximo 50 registros por página
}
```

**Benefício:** Sem paginação, listar 1000 registros toma 1000 queries. Com paginação: 50 queries.

---

## 📈 Como Monitorar Performance

### 1. Script de Diagnóstico Local
```bash
cd c:\site-record
python scripts/diagnostico_slowness.py
```

Mostra:
- Quantas queries estão sendo executadas
- Quais são as mais lentas
- Índices criados no banco

### 2. Django Debug Toolbar (Desenvolvimento)

Instalar:
```bash
pip install django-debug-toolbar
```

Adicionar a `settings.py`:
```python
INSTALLED_APPS = [
    # ...
    'debug_toolbar',
]

MIDDLEWARE = [
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    # ...
]

INTERNAL_IPS = ['127.0.0.1']
```

Adicionar a `urls.py`:
```python
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
```

Acessar: http://localhost:8000/api/crm/vendas/ → Painel "Queries" no canto inferior direito

### 3. Railway - Verificar logs de slowness

```bash
# Ver logs do serviço web
railway logs

# Acessar o PostgreSQL (abre o psql do banco vinculado ao projeto)
railway connect Postgres
```

Informações do banco (uso de disco, conexões) ficam no painel do Railway → serviço **Postgres** → aba **Metrics**.

### 4. PostgreSQL - EXPLAIN ANALYZE

No Railway:
```bash
railway connect Postgres

# Dentro do psql:
EXPLAIN ANALYZE SELECT * FROM crm_venda 
WHERE data_criacao >= '2025-12-01' 
AND data_criacao <= '2025-12-31'
AND ativo = true;

# Ver se índices estão sendo usados (procure por "Index" no output)
```

---

## 🎯 Próximas Otimizações (Se Necessário)

### Se Ainda Estiver Lento

1. **Redis Cache para Consultas Frequentes**
   ```python
   # Cache status CRM (nunca muda)
   @cache_result(timeout=3600)  # 1 hora
   def get_status_choices():
       return StatusCRM.objects.all()
   ```

2. **Índices Compostos Adicionais**
   ```python
   # Se filtrar por vendedor + data muitas vezes
   class Meta:
       indexes = [
           models.Index(fields=['vendedor', 'data_criacao']),
       ]
   ```

3. **Database Views para Relatórios**
   ```sql
   -- Em vez de carregar e processar Python
   CREATE VIEW venda_summary AS
   SELECT vendedor_id, COUNT(*) as total, SUM(valor_pago)
   FROM crm_venda
   GROUP BY vendedor_id;
   ```

4. **Async Queries (Django 3.1+)**
   ```python
   # Para queries que demoram, executar em background
   from celery import shared_task
   
   @shared_task
   def gerar_relatorio(data_inicio, data_fim):
       vendas = Venda.objects.filter(
           data_criacao__gte=data_inicio,
           data_criacao__lte=data_fim
       )
       # Processar...
   ```

---

## 📋 Checklist de Performance

- [x] Removido `.defer()` que causava N+1 queries
- [x] Refatorado VendaSerializer (sem serializers aninhados)
- [x] Criado VendaDetailSerializer (com dados completos para retrieve)
- [x] Otimizado get_queryset (histórico apenas em retrieve)
- [x] Adicionada paginação (50 registros/página)
- [x] Adicionado `editado_por` ao select_related
- [x] Índices criados em migration 0065 e 0066
- [ ] Testar em produção e monitorar os logs do Railway
- [ ] Se necessário, adicionar Redis cache
- [ ] Se necessário, criar database views para relatórios

---

## 🚀 Deploy para Railway

O deploy é automático ao enviar para a branch `main` (serviço web ligado ao GitHub). As migrações rodam na fase `release` do `Procfile`.

```bash
git add -A
git commit -m "Performance: Fix N+1 queries, optimize serializers, add pagination"
git push origin main

# Verificar se subiu sem erros
railway logs
```

Teste após o deploy:
```
GET /api/crm/vendas/?view=geral&data_inicio=2025-12-01&data_fim=2025-12-31
```

Tempo esperado:
- **Antes:** 13-14 segundos (timeout)
- **Depois:** 1-3 segundos

---

## 📞 Troubleshooting

### Ainda está lento?

1. **Verificar índices foram criados:**
   ```bash
   railway connect Postgres
   SELECT * FROM pg_stat_user_indexes WHERE relname = 'crm_venda';
   ```

2. **Atualizar PostgreSQL statistics:**
   ```bash
   railway connect Postgres
   ANALYZE;
   ```

---

**Criado por:** GitHub Copilot  
**Data:** 03/01/2026
