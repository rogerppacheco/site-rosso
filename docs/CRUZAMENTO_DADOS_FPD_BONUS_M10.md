# 📊 Cruzamento de Dados: FPD com BONUS M10

## 🎯 Objetivo

Cruzar dados do arquivo de importação FPD com a base BONUS M10 utilizando o campo **`nr_ordem`** (Número de Ordem) para recuperar e armazenar os dados essenciais:
- **ID_CONTRATO**
- **DT_PAGAMENTO**
- **DS_STATUS_FATURA**

---

## 🔄 Fluxo de Funcionamento

```
┌──────────────────────────────────────────┐
│  Arquivo FPD (Importação Operadora)      │
│  ┌────────────────────────────────────┐  │
│  │ NR_ORDEM  | ID_CONTRATO | DT_PAGA │  │
│  │ OS-00123  | ID-789      | 2025-01 │  │
│  └────────────────────────────────────┘  │
└────────────┬───────────────────────────────┘
             │
             ▼ Crossover por NR_ORDEM
┌────────────────────────────────────────────┐
│  ContratoM10.ordem_servico = NR_ORDEM      │
│  ✅ Encontrado: ContratoM10 com O.S        │
└────────────┬───────────────────────────────┘
             │
             ▼ Atualiza
┌────────────────────────────────────────────┐
│  FaturaM10 + ImportacaoFPD                 │
│  ✅ Armazena todos os dados               │
└────────────────────────────────────────────┘
```

---

## 📦 Alterações Implementadas

### 1. **Modelo FaturaM10** (Campos Novos)

Adicionados 4 campos para armazenar dados FPD:

```python
# Em FaturaM10
id_contrato_fpd = CharField(100)              # ID_CONTRATO da planilha
dt_pagamento_fpd = DateField()                # DT_PAGAMENTO da planilha
ds_status_fatura_fpd = CharField(50)          # DS_STATUS_FATURA da planilha
data_importacao_fpd = DateTimeField()         # Data da importação
```

**Localização:** [crm_app/models.py](crm_app/models.py#L718-L721)

---

### 2. **Novo Modelo: ImportacaoFPD**

Criado modelo para histórico completo de importações:

```python
class ImportacaoFPD(models.Model):
    """Histórico de importações FPD com dados detalhados"""
    
    # Chaves de identificação
    nr_ordem = CharField(100, db_index=True)      # O.S para cruzamento
    id_contrato = CharField(100)                  # ID_CONTRATO
    nr_fatura = CharField(100)                    # NR_FATURA
    
    # Datas e Valores
    dt_venc_orig = DateField()                    # Data de vencimento
    dt_pagamento = DateField(nullable=True)       # Data de pagamento
    ds_status_fatura = CharField(50)              # Status (PAGO, ABERTO, etc)
    vl_fatura = DecimalField()                    # Valor
    nr_dias_atraso = IntegerField()               # Dias em atraso
    
    # Relacionamento
    contrato_m10 = ForeignKey(ContratoM10)        # Link com contrato
```

**Localização:** [crm_app/models.py](crm_app/models.py#L857-L897)

**Características:**
- ✅ Índices em `nr_ordem`, `id_contrato`, `ds_status_fatura`, `dt_venc_orig`
- ✅ Unique together: `(nr_ordem, nr_fatura)` para evitar duplicatas
- ✅ Registra data de importação automaticamente

---

### 3. **View ImportarFPDView** (Refatorada)

Atualizada para:
1. ✅ Buscar contrato por `ordem_servico = nr_ordem`
2. ✅ Extrair ID_CONTRATO, DT_PAGAMENTO, DS_STATUS_FATURA
3. ✅ Armazenar dados em **FaturaM10** (tabela principal)
4. ✅ Armazenar dados em **ImportacaoFPD** (histórico)

```python
# Exemplo de dados armazenados
FaturaM10:
  - id_contrato_fpd: "ID-789"
  - dt_pagamento_fpd: 2025-01-15
  - ds_status_fatura_fpd: "PAGO"
  - data_importacao_fpd: 2025-12-31 10:30:00

ImportacaoFPD:
  - nr_ordem: "OS-00123"
  - id_contrato: "ID-789"
  - dt_pagamento: 2025-01-15
  - ds_status_fatura: "PAGO"
```

**Localização:** [crm_app/views.py](crm_app/views.py#L4926-L5048)

---

### 4. **Novas Views API**

#### A) `DadosFPDView`
Retorna todos os dados FPD vinculados a uma O.S

**Endpoint:** `GET /api/bonus-m10/dados-fpd/?os=NR_ORDEM`

**Resposta:**
```json
{
  "contrato": {
    "numero_contrato": "C-123",
    "cliente_nome": "Cliente XYZ",
    "ordem_servico": "OS-00123"
  },
  "importacoes_fpd": [
    {
      "id_contrato": "ID-789",
      "nr_fatura": "F-001",
      "dt_venc_orig": "2025-01-20",
      "dt_pagamento": "2025-01-15",
      "ds_status_fatura": "PAGO",
      "vl_fatura": "150.00",
      "nr_dias_atraso": 0,
      "importada_em": "2025-12-31T10:30:00"
    }
  ],
  "faturas_m10": [
    {
      "numero_fatura": 1,
      "id_contrato_fpd": "ID-789",
      "dt_pagamento_fpd": "2025-01-15",
      "ds_status_fatura_fpd": "PAGO",
      "status": "PAGO",
      "valor": "150.00",
      "data_importacao_fpd": "2025-12-31T10:30:00"
    }
  ]
}
```

**Localização:** [crm_app/views.py](crm_app/views.py#L5216-L5267)

---

#### B) `ListarImportacoesFPDView`
Lista importações FPD com filtros por status e mês

**Endpoint:** `GET /api/bonus-m10/importacoes-fpd/?status=PAGO&mes=2025-01`

**Parâmetros:**
- `status` - Filtra por DS_STATUS_FATURA (PAGO, ABERTO, VENCIDO, etc)
- `mes` - Filtra por mês de vencimento (formato: YYYY-MM)
- `page` - Página (padrão: 1)
- `limit` - Registros por página (padrão: 100)

**Resposta:**
```json
{
  "total": 150,
  "total_valor": "22500.00",
  "pagina": 1,
  "limit": 100,
  "dados": [
    {
      "nr_ordem": "OS-00123",
      "id_contrato": "ID-789",
      "nr_fatura": "F-001",
      "dt_venc_orig": "2025-01-20",
      "ds_status_fatura": "PAGO",
      "vl_fatura": "150.00",
      "contrato_m10": "C-123 - Cliente XYZ",
      "importada_em": "2025-12-31T10:30:00"
    }
  ]
}
```

**Localização:** [crm_app/views.py](crm_app/views.py#L5270-L5315)

---

### 5. **Rotas Registradas**

Adicionadas em [gestao_equipes/urls.py](gestao_equipes/urls.py):

```python
# Dados FPD por O.S
path('api/bonus-m10/dados-fpd/', DadosFPDView.as_view(), name='api-bonus-m10-dados-fpd'),

# Listagem com filtros
path('api/bonus-m10/importacoes-fpd/', ListarImportacoesFPDView.as_view(), name='api-bonus-m10-importacoes-fpd'),
```

---

## 🔧 Migration Aplicada

Arquivo: [crm_app/migrations/0050_add_fpd_fields.py](crm_app/migrations/0050_add_fpd_fields.py)

**Alterações:**
- ✅ `FaturaM10`: +4 campos (id_contrato_fpd, dt_pagamento_fpd, ds_status_fatura_fpd, data_importacao_fpd)
- ✅ Novo modelo `ImportacaoFPD` com 13 campos
- ✅ Índices criados para performance

**Status:** ✅ Aplicada com sucesso

---

## 📋 Uso Prático

### 1. **Importar Arquivo FPD**

```bash
POST /api/bonus-m10/importar-fpd/
Content-Type: multipart/form-data

file: fpd_2025_01.xlsx
```

**O que acontece:**
1. Lê arquivo Excel/CSV
2. Para cada linha (fatura):
   - Busca O.S em `ContratoM10.ordem_servico`
   - Se encontrar, atualiza `FaturaM10`
   - Cria/atualiza registro em `ImportacaoFPD`

**Resposta:**
```json
{
  "message": "Importação FPD concluída! 125 contratos atualizados, 5 não encontrados.",
  "atualizados": 125,
  "nao_encontrados": 5,
  "importacoes_fpd": 125
}
```

---

### 2. **Buscar Dados FPD de uma O.S**

```bash
GET /api/bonus-m10/dados-fpd/?os=OS-00123
```

Retorna:
- Dados do contrato M10
- Histórico completo de importações FPD
- Faturas vinculadas com campos FPD

---

### 3. **Listar Importações com Filtros**

```bash
# Todas as faturas PAGAS do janeiro/2025
GET /api/bonus-m10/importacoes-fpd/?status=PAGO&mes=2025-01

# Faturas VENCIDAS (paginado)
GET /api/bonus-m10/importacoes-fpd/?status=VENCIDO&page=1&limit=50
```

---

## 📊 Estrutura de Dados

### FaturaM10 (Tabela Existente + Campos FPD)
```
┌─────────────────────────────────┐
│ FaturaM10                       │
├─────────────────────────────────┤
│ id                              │
│ contrato_id (FK)                │
│ numero_fatura (1-10)            │
│ status (PAGO, NAO_PAGO, etc)    │
│ data_vencimento                 │
│ data_pagamento                  │
│ valor                           │
│                                 │
│ === NOVOS CAMPOS FPD ===        │
│ id_contrato_fpd                 │ ← ID_CONTRATO
│ dt_pagamento_fpd                │ ← DT_PAGAMENTO
│ ds_status_fatura_fpd            │ ← DS_STATUS_FATURA
│ data_importacao_fpd             │ ← Timestamp importação
└─────────────────────────────────┘
```

### ImportacaoFPD (Nova Tabela)
```
┌─────────────────────────────────┐
│ ImportacaoFPD                   │
├─────────────────────────────────┤
│ id (PK)                         │
│ nr_ordem (UK, indexed)          │ ← Chave cruzamento
│ id_contrato (indexed)           │
│ nr_fatura (UK com nr_ordem)     │
│ dt_venc_orig (indexed)          │
│ dt_pagamento                    │
│ ds_status_fatura (indexed)      │
│ vl_fatura                       │
│ nr_dias_atraso                  │
│ contrato_m10_id (FK)            │
│ importada_em (auto_now_add)     │
│ atualizada_em (auto_now)        │
└─────────────────────────────────┘
```

---

## ✅ Checklist de Validação

- [x] Campos adicionados em `FaturaM10`
- [x] Modelo `ImportacaoFPD` criado
- [x] ImportarFPDView refatorada para popular todos os campos
- [x] Duas novas Views API criadas
- [x] Rotas registradas
- [x] Migration criada e aplicada
- [x] Admin registrado para gerenciar ImportacaoFPD
- [x] Índices criados para performance

---

## 🚀 Próximos Passos (Opcional)

1. **Dashboard FPD** - Visualização gráfica dos dados importados
2. **Relatório de Reconciliação** - Comparar dados FPD com pagamentos
3. **Alertas Automáticos** - Notificar sobre faturas vencidas
4. **API de Auditoria** - Rastrear mudanças nos dados FPD

---

## 📞 Documentação Relacionada

- [SISTEMA_BONUS_M10_COMPLETO.md](SISTEMA_BONUS_M10_COMPLETO.md)
- [ARQUITETURA_M10_REFATORADA.md](ARQUITETURA_M10_REFATORADA.md)
