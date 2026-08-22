# 📋 Plano Completo: Validações e Monitoramento de Importações

## 📊 Estado Atual

### ✅ **Processos com Validação Completa**
1. **FPD** (`LogImportacaoFPD`)
   - ✅ Modelo de log completo
   - ✅ API de logs (`/api/bonus-m10/logs-importacao-fpd/`)
   - ✅ Página de validação (`/validacao-fpd/`)
   - ✅ View `page_validacao_fpd`

2. **Churn** (`LogImportacaoChurn`)
   - ✅ Modelo de log completo
   - ✅ API de logs (precisa verificar endpoint)
   - ✅ Página de validação (`/validacao-churn/`)
   - ✅ View `page_validacao_churn`

---

### ⚠️ **Processos com Log MAS SEM Página de Validação**
3. **OSAB** (`LogImportacaoOSAB`)
   - ✅ Modelo de log existe
   - ✅ API de logs (`/api/crm/logs-osab/`)
   - ❌ **FALTA:** Página de validação
   - ❌ **FALTA:** View `page_validacao_osab`

4. **Agendamento** (`LogImportacaoAgendamento`)
   - ✅ Modelo de log existe
   - ✅ API de logs (`/api/crm/logs-agendamento/`)
   - ❌ **FALTA:** Página de validação
   - ❌ **FALTA:** View `page_validacao_agendamento`

5. **Legado** (`LogImportacaoLegado`)
   - ✅ Modelo de log existe
   - ✅ API de logs (`/api/crm/logs-legado/`)
   - ❌ **FALTA:** Página de validação
   - ❌ **FALTA:** View `page_validacao_legado`

6. **DFV** (`LogImportacaoDFV`)
   - ✅ Modelo de log existe
   - ✅ API de logs (`/api/crm/logs-dfv/`)
   - ❌ **FALTA:** Página de validação
   - ❌ **FALTA:** View `page_validacao_dfv`

---

### ❓ **Processos a Verificar**
7. **Recompra** (`ImportacaoRecompraView`)
   - ❓ Verificar se tem modelo de log
   - ❓ Verificar se tem API de logs
   - ❌ **FALTA:** Página de validação

8. **Ciclo Pagamento** (`ImportacaoCicloPagamentoView`)
   - ❓ Verificar se tem modelo de log
   - ❓ Verificar se tem API de logs
   - ❌ **FALTA:** Página de validação

---

## 🎯 Plano de Implementação

### Fase 1: Verificação e Preparação
1. ✅ Verificar quais processos têm modelos `LogImportacao*`
2. ✅ Verificar quais processos têm APIs de logs
3. ✅ Identificar campos específicos de cada processo

### Fase 2: Criar Páginas de Validação (Baseadas em `validacao-fpd.html`)

#### Padrão a Seguir:
- **Template HTML:** Copiar `validacao-fpd.html` como base
- **Estrutura:**
  - Cards de estatísticas (Total, Sucesso, Erro, Parcial, Processando)
  - Filtros (Status, Data, Arquivo)
  - Tabela de logs com detalhes
  - Botão "Nova Importação"

#### Processos a Implementar:
1. **validacao-osab.html**
   - Endpoint API: `/api/crm/logs-osab/`
   - Campos específicos: `total_atualizados`, `total_criados`, `ignorados_dt_ref`

2. **validacao-agendamento.html**
   - Endpoint API: `/api/crm/logs-agendamento/`
   - Campos específicos: `agendamentos_criados`, `agendamentos_atualizados`, `nao_encontrados`

3. **validacao-legado.html**
   - Endpoint API: `/api/crm/logs-legado/`
   - Campos específicos: `vendas_criadas`, `vendas_atualizadas`, `clientes_criados`

4. **validacao-dfv.html**
   - Endpoint API: `/api/crm/logs-dfv/`
   - Campos específicos: (verificar modelo)

5. **validacao-recompra.html** (se tiver log)
   - Endpoint API: (verificar)
   - Campos específicos: (verificar)

6. **validacao-ciclo-pagamento.html** (se tiver log)
   - Endpoint API: (verificar)
   - Campos específicos: (verificar)

### Fase 3: Criar Views Django

Para cada processo, criar view simples:
```python
def page_validacao_osab(request):
    """View para renderizar a página de validação de importações OSAB"""
    return render(request, 'validacao-osab.html')

def page_validacao_agendamento(request):
    """View para renderizar a página de validação de importações Agendamento"""
    return render(request, 'validacao-agendamento.html')

# ... etc
```

### Fase 4: Adicionar URLs

```python
# Em gestao_equipes/urls.py
path('validacao-osab/', page_validacao_osab, name='page_validacao_osab'),
path('validacao-agendamento/', page_validacao_agendamento, name='page_validacao_agendamento'),
path('validacao-legado/', page_validacao_legado, name='page_validacao_legado'),
path('validacao-dfv/', page_validacao_dfv, name='page_validacao_dfv'),
# ... etc
```

### Fase 5: Atualizar Menu de Importações

Adicionar cards de validação em `importacoes.html` na aba "Validações e Monitoramento"

---

## 📝 Estrutura de Cada Página de Validação

### 1. Header
- Título: "Validação de Importações [NOME]"
- Botão: "Nova Importação" → link para página de importação

### 2. Cards de Estatísticas
- Total de Importações
- Com Sucesso
- Com Erro
- Parciais
- Processando (se aplicável)
- Métricas específicas (Linhas processadas, Valores, etc)

### 3. Filtros
- Status (dropdown)
- Data Início (date picker)
- Data Fim (date picker)
- Buscar Arquivo (input text)
- Botões: Buscar | Limpar

### 4. Tabela de Logs
Colunas padrão:
- Data/Hora
- Arquivo
- Usuário
- Status (badge colorido)
- Total Linhas
- Processadas/Sucesso
- Erros
- Duração
- Ações (ver detalhes, se aplicável)

### 5. JavaScript
- Função para carregar dados da API
- Função para aplicar filtros
- Função para formatar datas
- Função para exibir badges de status
- Auto-refresh se houver PROCESSANDO

---

## 🔄 Próximos Passos Recomendados

1. **Verificar processos Recompra e Ciclo Pagamento**
   - Se não têm log, criar modelos `LogImportacaoRecompra` e `LogImportacaoCicloPagamento`
   - Adicionar logs nas views de importação

2. **Implementar página por página**
   - Começar com OSAB (mais usado?)
   - Depois Agendamento
   - Depois Legado
   - Depois DFV
   - Por último Recompra e Ciclo Pagamento

3. **Testar cada implementação**
   - Verificar se API retorna dados corretos
   - Verificar se filtros funcionam
   - Verificar se estatísticas estão corretas

4. **Atualizar menu central**
   - Adicionar todos os cards na aba de validações
   - Garantir que links funcionam

---

## 📌 Notas Importantes

- **Modelo Base:** `validacao-fpd.html` é o template de referência
- **API Pattern:** Todas seguem padrão `/api/crm/logs-[nome]/`
- **Consistência:** Manter mesmo padrão visual e funcional
- **Campos Específicos:** Cada processo pode ter métricas únicas
