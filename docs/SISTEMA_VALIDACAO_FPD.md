# Sistema de Validação e Auditoria de Importações FPD

## 📋 Visão Geral

Sistema completo de logging e validação para importações de arquivos FPD (Faturamento, Pagamento e Débito) no BONUS M-10, permitindo monitoramento em tempo real, auditoria e diagnóstico de problemas.

## 🎯 Problema Resolvido

**Situação Anterior:**
- Importações falhavam silenciosamente quando O.S não encontradas no banco
- Sem registro de quais linhas falharam
- Sem visibilidade de estatísticas de importação
- Impossível debugar problemas de importação
- Usuário não sabia se importação teve sucesso parcial ou total

**Solução Implementada:**
- Logging completo de cada tentativa de importação
- Registro de exemplos de O.S que falharam (primeiros 20)
- Estatísticas detalhadas (linhas processadas, erros, valores)
- Interface profissional para visualização
- Filtros por status, data, usuário
- Histórico completo de importações

---

## 🗄️ Estrutura do Banco de Dados

### Modelo: `LogImportacaoFPD`

```python
class LogImportacaoFPD(models.Model):
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Sucesso Parcial'),
    ]
    
    # Informações do arquivo
    nome_arquivo = CharField(255)
    tamanho_arquivo = BigIntegerField  # bytes
    
    # Rastreabilidade
    usuario = ForeignKey(User)
    iniciado_em = DateTimeField(auto_now_add)
    finalizado_em = DateTimeField(null=True)
    duracao_segundos = DecimalField(null=True)
    
    # Status e resultados
    status = CharField(20, choices=STATUS_CHOICES)
    
    # Estatísticas
    total_linhas = IntegerField(default=0)
    total_processadas = IntegerField(default=0)
    total_erros = IntegerField(default=0)
    total_contratos_nao_encontrados = IntegerField(default=0)
    total_valor_importado = DecimalField(null=True)
    
    # Detalhes de erro
    mensagem_erro = TextField(null=True, blank=True)
    detalhes_json = JSONField(null=True, blank=True)
    
    # Exemplos de falhas
    exemplos_nao_encontrados = JSONField(null=True, blank=True)
    # Ex: ["OS-12345", "OS-67890", ...] (primeiros 20)
```

**Índices criados:**
- `idx_log_fpd_status` - Busca por status
- `idx_log_fpd_usuario` - Busca por usuário
- `idx_log_fpd_iniciado_em` - Busca por data

---

## 🔄 Fluxo de Importação Aprimorado

### 1. Início da Importação
```python
# Criar log com status PROCESSANDO
log_importacao = LogImportacaoFPD.objects.create(
    nome_arquivo=arquivo.name,
    tamanho_arquivo=arquivo.size,
    usuario=request.user,
    status='PROCESSANDO',
    iniciado_em=timezone.now()
)
```

### 2. Durante Processamento
```python
os_nao_encontradas = []  # Lista com primeiros 20 exemplos
erros_detalhados = []    # Lista com primeiros 10 erros

for index, row in df.iterrows():
    try:
        nr_ordem = str(row['nr_ordem']).strip()
        
        # Tentar encontrar contrato
        contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
        
        # Processar e salvar...
        registros_processados += 1
        total_valor += vl_fatura
        
    except ContratoM10.DoesNotExist:
        # Coletar exemplo (primeiros 20)
        if len(os_nao_encontradas) < 20:
            os_nao_encontradas.append(nr_ordem)
        registros_nao_encontrados += 1
        
    except Exception as e:
        # Coletar erro detalhado (primeiros 10)
        if len(erros_detalhados) < 10:
            erros_detalhados.append({
                'linha': index + 2,
                'nr_ordem': nr_ordem,
                'erro': str(e)
            })
        registros_erro += 1
```

### 3. Finalização
```python
# Atualizar log com resultados
log_importacao.finalizado_em = timezone.now()
log_importacao.duracao_segundos = log_importacao.calcular_duracao()
log_importacao.total_linhas = total_linhas
log_importacao.total_processadas = registros_processados
log_importacao.total_erros = registros_erro
log_importacao.total_contratos_nao_encontrados = registros_nao_encontrados
log_importacao.total_valor_importado = total_valor
log_importacao.exemplos_nao_encontrados = os_nao_encontradas

# Determinar status final
if registros_erro == total_linhas:
    log_importacao.status = 'ERRO'
elif registros_nao_encontrados > 0 or registros_erro > 0:
    log_importacao.status = 'PARCIAL'
else:
    log_importacao.status = 'SUCESSO'

log_importacao.save()
```

---

## 🔌 API de Logs

### Endpoint: `/api/bonus-m10/logs-importacao-fpd/`

**GET** - Listar logs com filtros e estatísticas

**Parâmetros de Query:**
```
?status=ERRO             # Filtrar por status (SUCESSO, ERRO, PARCIAL, PROCESSANDO)
&usuario_id=5            # Filtrar por usuário
&data_inicio=2025-01-01  # Data de início
&data_fim=2025-01-31     # Data de fim
&page=1                  # Página (default: 1)
&limit=50                # Resultados por página (default: 50)
&detalhes=true           # Incluir detalhes_json completo
```

**Resposta:**
```json
{
  "total": 45,
  "page": 1,
  "limit": 50,
  "total_pages": 1,
  
  "estatisticas_gerais": {
    "total_importacoes": 45,
    "total_linhas_processadas": 12350,
    "total_sucesso": 30,
    "total_erro": 5,
    "total_parcial": 10,
    "media_duracao_segundos": 8.5,
    "total_valor_importado": "2456789.50",
    "taxa_sucesso": 66.67
  },
  
  "logs": [
    {
      "id": 15,
      "nome_arquivo": "fpd_janeiro_2025.xlsx",
      "tamanho_arquivo": 524288,
      "usuario": {
        "id": 3,
        "username": "admin",
        "nome_completo": "Administrador Sistema"
      },
      "status": "PARCIAL",
      "iniciado_em": "2025-01-15T14:30:00Z",
      "finalizado_em": "2025-01-15T14:30:12Z",
      "duracao_segundos": 12.5,
      "total_linhas": 500,
      "total_processadas": 450,
      "total_erros": 0,
      "total_contratos_nao_encontrados": 50,
      "total_valor_importado": "125000.00",
      "mensagem_erro": null,
      "exemplos_nao_encontrados": [
        "OS-12345", "OS-67890", "OS-11111", 
        "OS-22222", "OS-33333", "OS-44444"
      ]
    }
  ]
}
```

---

## 🖥️ Interface de Validação

### Acesso
- **URL:** `/validacao-fpd/`
- **Permissões:** Usuário autenticado
- **Menu:** Importações → Validar FPD

### Recursos da Interface

#### 1. **Dashboard de Estatísticas**
Cards com métricas principais:
- ✅ Total de Importações
- ✅ Com Sucesso (verde)
- ❌ Com Erro (vermelho)
- ⚠️ Parciais (amarelo)
- 📄 Linhas Processadas
- 💰 Valor Total Importado

#### 2. **Filtros Avançados**
- Status (Todos, Sucesso, Erro, Parcial, Processando)
- Data Início
- Data Fim
- Busca por nome de arquivo

#### 3. **Tabela de Logs**
Colunas exibidas:
- Data/Hora
- Nome do Arquivo
- Usuário
- Status (badge colorido)
- Total Linhas
- Processadas
- Erros
- Não Encontrados
- Valor Total
- Duração

#### 4. **Detalhes Expandíveis**
Ao clicar no botão "👁️" em cada linha:
- Tamanho do arquivo
- Taxa de sucesso %
- Horário de início e fim
- Mensagem de erro (se houver)
- **Lista de O.S não encontradas** (com destaque visual)
- Dica de resolução

#### 5. **Funcionalidades Extras**
- 🔄 Botão flutuante de atualização
- ⏱️ Auto-refresh a cada 30 segundos
- 📄 Paginação
- 🔍 Busca em tempo real
- 📱 Layout responsivo

---

## 🎨 Design da Interface

### Badges de Status
```css
SUCESSO    → Verde (#28a745)  [✓ SUCESSO]
ERRO       → Vermelho (#e74a3b)  [✗ ERRO]
PARCIAL    → Amarelo (#f6c23e)  [⚠ PARCIAL]
PROCESSANDO → Azul (#4e73df)  [⟳ PROCESSANDO]
```

### Cards de Estatísticas
- Borda esquerda colorida por tipo
- Ícone temático em marca d'água
- Valor em destaque (fonte grande)
- Label descritiva em caixa alta

### Seção de Detalhes
- Fundo cinza claro
- Métricas em grid responsivo
- Lista de O.S não encontradas com tags
- Alert para erros

---

## 🔍 Exemplos de Uso

### Caso 1: Importação com Sucesso Total
```json
{
  "status": "SUCESSO",
  "total_linhas": 100,
  "total_processadas": 100,
  "total_erros": 0,
  "total_contratos_nao_encontrados": 0,
  "total_valor_importado": "50000.00",
  "exemplos_nao_encontrados": []
}
```
**Interface mostra:** Badge verde "SUCESSO", 100% de taxa de sucesso

### Caso 2: Importação Parcial (O.S não encontradas)
```json
{
  "status": "PARCIAL",
  "total_linhas": 100,
  "total_processadas": 85,
  "total_erros": 0,
  "total_contratos_nao_encontrados": 15,
  "total_valor_importado": "42500.00",
  "exemplos_nao_encontrados": [
    "OS-12345", "OS-67890", "OS-11111", 
    "OS-22222", "OS-33333", "OS-44444",
    "OS-55555", "OS-66666", "OS-77777"
  ]
}
```
**Interface mostra:** 
- Badge amarelo "PARCIAL"
- 85% de taxa de sucesso
- Lista com 9 exemplos + "... e mais 6"
- Dica: "Estas ordens de serviço não foram encontradas na base de Contratos M10"

### Caso 3: Erro Total
```json
{
  "status": "ERRO",
  "total_linhas": 100,
  "total_processadas": 0,
  "total_erros": 100,
  "mensagem_erro": "Formato de arquivo inválido",
  "exemplos_nao_encontrados": []
}
```
**Interface mostra:** 
- Badge vermelho "ERRO"
- Alert vermelho com mensagem de erro
- 0% de taxa de sucesso

---

## 🛠️ Configuração do Admin Django

### Visualização de Logs no Admin
```python
@admin.register(LogImportacaoFPD)
class LogImportacaoFPDAdmin(admin.ModelAdmin):
    list_display = (
        'nome_arquivo', 'usuario', 'status_badge', 
        'total_linhas', 'total_processadas', 'total_erros',
        'total_valor_display', 'duracao_display', 'iniciado_em'
    )
    list_filter = ('status', 'iniciado_em', 'finalizado_em')
    search_fields = ('nome_arquivo', 'usuario__username', 'mensagem_erro')
    date_hierarchy = 'iniciado_em'
    readonly_fields = (
        'iniciado_em', 'finalizado_em', 'duracao_segundos',
        'tamanho_arquivo', 'detalhes_json', 'exemplos_nao_encontrados'
    )
```

**Recursos:**
- Badge colorido de status
- Formatação de valor monetário
- Formatação de duração em segundos
- Filtros por status e data
- Busca por arquivo, usuário ou erro

---

## 📊 Métricas e KPIs

### Taxa de Sucesso
```
Taxa de Sucesso = (Importações SUCESSO / Total Importações) × 100
```

### Eficiência de Processamento
```
Eficiência = (Total Processadas / Total Linhas) × 100
```

### Tempo Médio de Importação
```
Média = Soma(duracao_segundos) / Total Importações
```

---

## 🚨 Tratamento de Erros

### Tipos de Falha

1. **Contrato Não Encontrado**
   - Incrementa `total_contratos_nao_encontrados`
   - Adiciona O.S à lista `exemplos_nao_encontrados` (máx 20)
   - Status final: PARCIAL (se houver processados) ou ERRO

2. **Erro de Formato/Parsing**
   - Incrementa `total_erros`
   - Adiciona à lista `erros_detalhados` (máx 10)
   - Salva mensagem em `mensagem_erro`

3. **Erro Crítico (Exception não tratada)**
   - Status: ERRO
   - `mensagem_erro` com traceback
   - `total_processadas` = registros antes da falha

### Estratégia de Rollback
- Cada linha é processada independentemente
- Se uma linha falha, continua processando as demais
- Transaction por linha (ou batch de 100 para performance)

---

## 🔐 Segurança e Permissões

- ✅ Autenticação obrigatória (JWT Token)
- ✅ Logs associados ao usuário que importou
- ✅ Histórico auditável (quem, quando, o quê)
- ✅ Dados sensíveis apenas para usuários autenticados
- ✅ CORS configurado para domínio

---

## 📈 Próximas Melhorias

### Curto Prazo
- [ ] Exportar logs para Excel/CSV
- [ ] Gráficos de tendência (Chart.js)
- [ ] Notificações por email em caso de erro
- [ ] Retry automático para O.S não encontradas

### Médio Prazo
- [ ] Dashboard executivo com métricas semanais/mensais
- [ ] Comparação de importações (diff)
- [ ] Sugestões inteligentes (ML) para O.S similares
- [ ] API Webhook para integração com outros sistemas

### Longo Prazo
- [ ] Scheduler para importações automáticas
- [ ] Validação pré-import (dry-run)
- [ ] Cache inteligente de ContratoM10
- [ ] Processamento assíncrono (Celery)

---

## 📝 Checklist de Deployment

✅ Migração `0051_add_log_importacao_fpd` aplicada
✅ Modelo `LogImportacaoFPD` criado
✅ View `ImportarFPDView` refatorada com logging
✅ API `ListarLogsImportacaoFPDView` implementada
✅ Admin `LogImportacaoFPDAdmin` registrado
✅ Rota `/api/bonus-m10/logs-importacao-fpd/` adicionada
✅ Template `validacao-fpd.html` criado
✅ View `page_validacao_fpd` criada
✅ Rota `/validacao-fpd/` adicionada
✅ Link no menu de importações

---

## 🤝 Contribuindo

Para adicionar novas funcionalidades ao sistema de validação:

1. **Backend:** Editar `ImportarFPDView` em `crm_app/views.py`
2. **API:** Adicionar endpoints em `crm_app/views.py`
3. **Frontend:** Editar `frontend/public/validacao-fpd.html`
4. **Modelo:** Adicionar campos em `LogImportacaoFPD` (+ migração)

---

## 📞 Suporte

Para dúvidas ou problemas:
- Verificar logs no admin Django: `/admin/crm_app/logimportacaofpd/`
- Consultar API diretamente: `/api/bonus-m10/logs-importacao-fpd/?status=ERRO`
- Revisar console do navegador (F12) para erros JavaScript

---

**Documentação criada em:** Janeiro 2025  
**Última atualização:** Janeiro 2025  
**Versão:** 1.0
