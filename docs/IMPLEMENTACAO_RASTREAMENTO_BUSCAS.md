# 🚀 SISTEMA DE RASTREAMENTO E ANÁLISE DE BUSCAS DE FATURAS

## ✅ Implementações Concluídas

### 1. **Novos Campos no Modelo FaturaM10**
Adicionados campos de rastreamento completo:
- `origem_busca`: Manual, Automática, Safra ou Individual
- `status_busca`: Pendente, Sucesso, Erro ou Parcial
- `ultima_busca_em`: Timestamp da última tentativa
- `tempo_busca_segundos`: Tempo de execução (com 3 casas decimais)
- `tentativas_busca`: Contador de tentativas
- `erro_busca`: Mensagem de erro detalhada

### 2. **Novo Modelo HistoricoBuscaFatura**
Histórico completo de execuções com:
- **Métricas de Execução**: início, término, duração
- **Estatísticas**: contratos, faturas, sucessos, erros, não disponíveis, retries
- **Performance**: tempo médio/mínimo/máximo por fatura
- **Logs**: Status e logs detalhados em JSON

### 3. **Serviço de Busca Centralizado** (`services_busca_faturas.py`)
Classe `BuscaFaturaService` com:
- ✅ Rastreamento automático de origem e tempo
- ✅ Busca individual com métricas
- ✅ Busca por contrato com matching de vencimento
- ✅ **Retry automático** de erros (com limite de tentativas)
- ✅ Cálculo de estatísticas em tempo real
- ✅ Integração com histórico

### 4. **Comando Melhorado** (`buscar_faturas_nio_v2.py`)
Novo comando com:
- 🎯 Progress visual com porcentagem
- ⏱️ Estimativa de tempo restante
- 🔄 **Retry automático ao final** (padrão ativado)
- 📊 Métricas de performance detalhadas
- 📝 Histórico completo salvo automaticamente
- 🎨 Output colorido e organizado

**Uso:**
```bash
# Busca completa com retry
python manage.py buscar_faturas_nio_v2 --retry

# Busca de safra específica
python manage.py buscar_faturas_nio_v2 --safra 2026-01

# Customizar tentativas de retry
python manage.py buscar_faturas_nio_v2 --max-tentativas 5
```

### 5. **Dashboard de Análise** (Backend)
Novas views API:
- `/api/analise-buscas/`: Dashboard completo com estatísticas
  - Estatísticas gerais (total, sucesso, erros, taxa de sucesso)
  - Histórico das últimas 20 execuções
  - Performance diária
  - Estatísticas por tipo de busca
  - Top 10 faturas mais lentas
  - Faturas com erro persistente (3+ tentativas)
  
- `/api/analise-buscas/metricas-tempo-real/`: Atualização em tempo real
  - Execução em andamento (se houver)
  - Última execução
  - Faturas pendentes
  - Faturas com erro
  - Próxima execução agendada

### 6. **Frontend - Nova Aba de Análise**
Adicionada no `bonus_m10.html`:
- Tab "Análise de Buscas" ao lado de M-10 e FPD
- *(Estrutura HTML completa será criada no próximo passo)*

## 📊 Funcionalidades Principais

### Retry Automático
- ✅ Detecta automaticamente faturas com erro
- ✅ Tenta novamente até o limite de tentativas (padrão: 3)
- ✅ Marca como "desistência" após limite
- ✅ Estatísticas de retry incluídas no relatório

### Rastreamento de Origem
Cada fatura registra como foi buscada:
- **MANUAL**: Busca individual pelo usuário
- **AUTOMATICA**: Job agendado às 00:05
- **SAFRA**: Botão "Buscar Faturas Safra"
- **INDIVIDUAL**: Busca avulsa

### Métricas de Performance
- ⏱️ Tempo individual por fatura (milissegundos)
- 📊 Tempo médio, mínimo e máximo
- 📈 Taxa de sucesso em porcentagem
- 🎯 Identificação de gargalos

## 🔧 Próximos Passos

### Frontend Completo da Aba de Análise
Criar interface visual com:
- [ ] Cards de estatísticas principais
- [ ] Gráfico de performance diária (Chart.js)
- [ ] Tabela de execuções recentes
- [ ] Lista de faturas com problema
- [ ] Indicador de execução em tempo real
- [ ] Botão para forçar retry manual

### Melhorias Adicionais
- [ ] Notificações quando erros ultrapassam threshold
- [ ] Export de relatórios em PDF
- [ ] Comparação entre safras
- [ ] Alertas de performance degradada

## 📝 Migration Aplicada
```
crm_app/migrations/0059_faturam10_erro_busca_faturam10_origem_busca_and_more.py
```

## 🎉 Benefícios

1. **Visibilidade Total**: Sabe-se exatamente quando, como e por que cada fatura foi buscada
2. **Recuperação Automática**: Erros temporários são corrigidos automaticamente
3. **Análise de Performance**: Identifica gargalos e otimiza processo
4. **Auditoria Completa**: Histórico persistente de todas as execuções
5. **Melhores Práticas**: Observabilidade, métricas e rastreamento end-to-end

## 🚀 Como Usar

### Atualizar Scheduler para Novo Comando
Editar `crm_app/scheduler.py`:
```python
def buscar_faturas_automatico():
    try:
        logger.info("🤖 Iniciando busca automática de faturas no Nio...")
        # Usar novo comando com retry
        call_command('buscar_faturas_nio_v2', retry=True)
        logger.info("✅ Busca automática concluída com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro na busca automática: {str(e)}")
```

### Consultar Histórico via Shell
```python
from crm_app.models import HistoricoBuscaFatura

# Última execução
ultima = HistoricoBuscaFatura.objects.order_by('-inicio_em').first()
print(f"Duracao: {ultima.duracao_segundos}s")
print(f"Sucesso: {ultima.faturas_sucesso}")
print(f"Tempo médio: {ultima.tempo_medio_fatura}s")

# Faturas com erro persistente
from crm_app.models import FaturaM10
problemas = FaturaM10.objects.filter(
    status_busca='ERRO',
    tentativas_busca__gte=3
)
print(f"Faturas com problema: {problemas.count()}")
```

---
**Status**: ✅ Backend 100% completo | ⏳ Frontend 30% completo
**Data**: 02/01/2026
