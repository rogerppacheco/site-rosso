# 📊 RELATÓRIO: IMPORTAÇÃO DE CHURN - ANÁLISE COMPLETA

**Data:** 25 de janeiro de 2026  
**Objetivo:** Documentar como funciona a importação de churn e identificar problemas

---

## 🔍 RESUMO EXECUTIVO

Existem **dois fluxos** de importação de churn no sistema:

1. **Importação Genérica** (`/import/churn/`) → `ImportacaoChurnView`
2. **Importação M-10** (`/api/bonus-m10/importar-churn/`) → `ImportarChurnView`

**Problema identificado:** Os 377 churns de jul/25 com `ANOMES_GROSS=202507` não aparecem em `ImportacaoChurn` quando filtramos por `anomes_gross=202507`, sugerindo que:
- A planilha foi importada **sem** a coluna `ANOMES_GROSS`, ou
- A coluna tinha nome diferente, ou
- Os registros foram importados mas `anomes_gross` ficou NULL/vazio

---

## 📋 FLUXO 1: IMPORTAÇÃO GENÉRICA (`/import/churn/`)

### **View:** `ImportacaoChurnView` (linha 3168 de `crm_app/views.py`)

### **O que faz:**
- **Grava APENAS** em `ImportacaoChurn`
- **NÃO atualiza** `ContratoM10`
- Usado para comissionamento e validações

### **Processo:**

1. **Upload:** Recebe arquivo Excel/CSV/XLSB
2. **Leitura:** Usa `pandas.read_excel()` ou `pd.read_csv()`
3. **Normalização:** 
   - Colunas normalizadas para maiúsculas: `df.columns = df.columns.str.strip().str.upper()`
   - Datas convertidas: `DT_GROSS` e `DT_RETIRADA` → `pd.to_datetime()`
   - NaN/NaT → `None`
4. **Mapeamento de colunas:**
   ```python
   coluna_map = {
       'UF': 'uf',
       'PRODUTO': 'produto',
       'MATRICULA_VENDEDOR': 'matricula_vendedor',
       'GV': 'gv',
       'SAP_PRINCIPAL_FIM': 'sap_principal_fim',
       'GESTAO': 'gestao',
       'ST_REGIONAL': 'st_regional',
       'GC': 'gc',
       'NUMERO_PEDIDO': 'numero_pedido',
       'NR_ORDEM': 'nr_ordem',  # ✅ Mapeado
       'DT_GROSS': 'dt_gross',
       'ANOMES_GROSS': 'anomes_gross',  # ✅ Mapeado
       'DT_RETIRADA': 'dt_retirada',
       'ANOMES_RETIRADA': 'anomes_retirada',
       'GRUPO_UNIDADE': 'grupo_unidade',
       'CODIGO_SAP': 'codigo_sap',
       'MUNICIPIO': 'municipio',
       'TIPO_RETIRADA': 'tipo_retirada',
       'MOTIVO_RETIRADA': 'motivo_retirada',
       'SUBMOTIVO_RETIRADA': 'submotivo_retirada',
       'CLASSIFICACAO': 'classificacao',
       'DESC_APELIDO': 'desc_apelido'
   }
   ```
5. **Bulk operations:**
   - Separa registros para criar vs atualizar por `numero_pedido`
   - **Chave única:** `numero_pedido` (unique=True)
   - Se `numero_pedido` não existe → **pula a linha** (`if not pedido: continue`)
   - `bulk_create()` para novos, `bulk_update()` para existentes

### **Problemas identificados:**

#### ❌ **Problema 1: Linhas sem `NUMERO_PEDIDO` são ignoradas**
```python
pedido = data.get('numero_pedido')
if not pedido: continue  # ⚠️ PULA A LINHA SEM SALVAR
```
**Impacto:** Se a planilha não tiver `NUMERO_PEDIDO` preenchido, a linha **não é salva**, mesmo que tenha `NR_ORDEM` e outros dados.

#### ❌ **Problema 2: `numero_pedido` é unique=True**
- Se duas linhas têm o mesmo `NUMERO_PEDIDO`, a segunda **atualiza** a primeira (não cria duplicata).
- Se a planilha tem **duas linhas com mesmo pedido mas O.S diferentes**, só uma O.S será salva.

#### ⚠️ **Problema 3: Dependência de `numero_pedido`**
- O código assume que **toda linha tem `NUMERO_PEDIDO`**.
- Se a planilha só tem `NR_ORDEM` (sem `NUMERO_PEDIDO`), **nenhum registro é salvo**.

### **Campos salvos:**
- ✅ Todos os campos mapeados em `coluna_map` são salvos
- ✅ `nr_ordem` e `anomes_gross` **são salvos** se existirem na planilha
- ❌ Se `ANOMES_GROSS` não existir na planilha → `anomes_gross` fica `NULL`

---

## 📋 FLUXO 2: IMPORTAÇÃO M-10 (`/api/bonus-m10/importar-churn/`)

### **View:** `ImportarChurnView` (linha 8165 de `crm_app/views.py`)

### **O que faz:**
- **Grava** em `ImportacaoChurn` **E**
- **Marca** `ContratoM10` como CANCELADO (cruzamento por O.S)

### **Processo:**

1. **Upload:** Recebe arquivo Excel/CSV/XLSB
2. **Leitura:** Similar ao fluxo 1, mas com `dtype={'PEDIDO': str, 'NR_ORDEM': str, 'NUMERO_PEDIDO': str}`
3. **Normalização:** Colunas maiúsculas
4. **Loop linha por linha:**

   Para cada linha:
   
   a) **Extrai O.S:**
      - Prioridade: `NR_ORDEM` → se vazio, usa `NUMERO_PEDIDO`
      - Se ambos vazios → **pula a linha** (`continue`)
      - Normaliza: `nr_ordem = str(nr_ordem_raw).strip().zfill(8)`
   
   b) **Salva em `ImportacaoChurn`:**
      - Tenta `update_or_create` por `numero_pedido` (se existir)
      - Se `numero_pedido` vazio → busca por `nr_ordem` existente ou cria novo
      - **Salva TODOS os campos** da planilha (incluindo `anomes_gross`)
   
   c) **Atualiza `ContratoM10`:**
      - Busca `ContratoM10.objects.get(ordem_servico=nr_ordem)`
      - Se encontrado → marca como CANCELADO
      - Se não encontrado → conta como `nao_encontrados`

5. **Reativação:**
   - Contratos cuja O.S **não aparece** no arquivo → marca como ATIVO
   - ⚠️ **Cuidado:** Se o arquivo é incremental (só novos churns), isso pode reativar indevidamente

### **Problemas identificados:**

#### ✅ **Vantagem:** Salva registros mesmo sem `numero_pedido`
- Se `numero_pedido` vazio, usa `nr_ordem` como alternativa
- Cria registro com `numero_pedido=None` (permitido pelo modelo)

#### ⚠️ **Problema:** Matching de O.S pode falhar
- Usa `zfill(8)` → `"5331733"` vira `"05331733"`
- Mas `ContratoM10.ordem_servico` pode ter formato diferente (ex.: `"4-210432948964"`)
- Se não encontrar → `nao_encontrados++`, mas **registro é salvo em `ImportacaoChurn`**

---

## 🔍 ANÁLISE DO PROBLEMA DOS 377 CHURNS

### **Situação:**
- 377 O.S com `ANOMES_GROSS=202507` (instalados jul/25)
- Comando `sync_m10_da_base_churn --anomes 202507` retorna **0 registros**

### **Possíveis causas:**

1. **Planilha importada sem `ANOMES_GROSS`:**
   - Se a coluna não existia → `anomes_gross` ficou `NULL`
   - Filtro `anomes_gross=202507` não encontra nada

2. **Planilha importada com nome diferente:**
   - Ex.: `"ANO_MES_GROSS"`, `"MES_GROSS"`, `"DATA_GROSS"` (sem o "ANOMES")
   - Não mapeia para `anomes_gross` → fica `NULL`

3. **Formato diferente:**
   - Planilha tem `"2025-07"` ou `"07/2025"` → não mapeia para `"202507"`
   - Precisa normalizar antes de salvar

4. **Importação pelo fluxo genérico sem `NUMERO_PEDIDO`:**
   - Se as 377 linhas não tinham `NUMERO_PEDIDO` → foram **puladas** (`if not pedido: continue`)
   - Nunca foram salvas em `ImportacaoChurn`

### **Como verificar:**

```bash
# 1. Ver quantos churns existem no total
python manage.py sync_m10_da_base_churn --consultar

# 2. Ver quantos têm anomes_gross NULL
# (precisa query direta no banco ou script)

# 3. Verificar se as O.S existem (por nr_ordem)
# (precisa API de busca ou query direta)
```

---

## ✅ RECOMENDAÇÕES PARA CORREÇÃO

### **1. Garantir que 100% das linhas sejam salvas:**

**Fluxo Genérico (`ImportacaoChurnView`):**
- ❌ **Atual:** Pula linhas sem `numero_pedido`
- ✅ **Corrigir:** Se `numero_pedido` vazio, usar `nr_ordem` como chave alternativa
- ✅ **Corrigir:** Se ambos vazios, criar registro com ID sequencial ou hash da linha

**Fluxo M-10 (`ImportarChurnView`):**
- ✅ **Já funciona:** Salva mesmo sem `numero_pedido`
- ⚠️ **Melhorar:** Normalizar `anomes_gross` para formato `AAAAMM` (ex.: `"2025-07"` → `"202507"`)

### **2. Normalização de `anomes_gross`:**

```python
# Antes de salvar:
anomes_raw = row.get('ANOMES_GROSS', '')
if anomes_raw:
    # Aceitar múltiplos formatos:
    # "202507", "2025-07", "07/2025", "2025-07-01", etc.
    anomes_normalizado = normalizar_anomes(anomes_raw)  # → "202507"
else:
    anomes_normalizado = None
```

### **3. Log de linhas ignoradas:**

- Contar quantas linhas foram puladas e por quê
- Exibir no retorno da API: `"linhas_ignoradas": X, "motivo": "sem numero_pedido"`

### **4. API de busca por `nr_ordem`:**

- Criar `/api/bonus-m10/buscar-os-churn/?os=XXXXX`
- Retornar todos os `ImportacaoChurn` com `nr_ordem` correspondente
- Mostrar: `anomes_gross`, `anomes_retirada`, `dt_retirada`, `motivo_retirada`, etc.

---

## 📊 COMPARAÇÃO DOS DOIS FLUXOS

| Aspecto | Fluxo Genérico | Fluxo M-10 |
|---------|----------------|------------|
| **Endpoint** | `/import/churn/` | `/api/bonus-m10/importar-churn/` |
| **View** | `ImportacaoChurnView` | `ImportarChurnView` |
| **Salva em `ImportacaoChurn`** | ✅ Sim | ✅ Sim |
| **Atualiza `ContratoM10`** | ❌ Não | ✅ Sim |
| **Salva sem `numero_pedido`** | ❌ Não (pula linha) | ✅ Sim (usa `nr_ordem`) |
| **Chave única** | `numero_pedido` | `numero_pedido` ou `nr_ordem` |
| **Log de importação** | ❌ Não | ✅ Sim (`LogImportacaoChurn`) |
| **Reativa contratos** | ❌ Não | ✅ Sim (O.S não no arquivo → ATIVO) |
| **Normaliza `anomes_gross`** | ❌ Não | ❌ Não (mas salva se existir) |

---

## 🎯 CORREÇÕES IMPLEMENTADAS (25/01/2026)

### ✅ **1. API de busca por `nr_ordem` criada**
- **Endpoint:** `/api/bonus-m10/buscar-os-churn/?os=XXXXX`
- **View:** `BuscarOSChurnView` (linha ~8633 de `crm_app/views.py`)
- **Funcionalidades:**
  - Busca por `nr_ordem` ou `numero_pedido` (com variações: `zfill(8)`, `lstrip('0')`, remoção de prefixos)
  - Retorna dados completos de `ImportacaoChurn` + vínculo com `ContratoM10` (se existir)
  - Mostra `anomes_gross`, `anomes_retirada`, `dt_retirada`, `motivo_retirada`, etc.

### ✅ **2. Fluxo genérico corrigido**
- **Antes:** Linhas sem `numero_pedido` eram **puladas** (`if not pedido: continue`)
- **Agora:** 
  - Se não tem `numero_pedido`, usa `nr_ordem` como chave alternativa
  - Busca existentes por `numero_pedido` OU `nr_ordem`
  - Cria registros mesmo sem `numero_pedido` (usa `numero_pedido=None`)
  - Retorna `linhas_ignoradas` e `motivo_ignoradas` no response

### ✅ **3. Normalização de `anomes_gross` implementada**
- **Função:** `_normalizar_anomes_gross()` (linha ~3168 de `crm_app/views.py`)
- **Formatos aceitos:**
  - `"202507"` → `"202507"` (já está correto)
  - `"2025-07"` → `"202507"`
  - `"2025/07"` → `"202507"`
  - `"2025-07-01"` → `"202507"` (pega só YYYYMM)
  - `"07/2025"` → `"202507"` (tenta inferir)
- **Aplicado em:** Ambos os fluxos (genérico e M-10)

### ✅ **4. Log de linhas ignoradas adicionado**
- **Response do fluxo genérico agora inclui:**
  ```json
  {
    "linhas_ignoradas": 5,
    "motivo_ignoradas": ["Linha 3: sem numero_pedido e sem nr_ordem", ...]
  }
  ```

### ✅ **5. Página de validação melhorada**
- **Função `buscarOS()` corrigida** em `validacao-churn.html`
- **Antes:** Mostrava dados de FPD (nr_fatura, dt_venc_orig, vl_fatura)
- **Agora:** Mostra dados corretos de CHURN:
  - Tabela com: ID, NR_ORDEM, NUMERO_PEDIDO, UF, Município, **ANOMES_GROSS**, DT_RETIRADA, ANOMES_RETIRADA, Motivo Retirada, Contrato M-10
  - Destaque para `anomes_gross` NULL (em vermelho)
  - Mostra vínculo com `ContratoM10` (status, cliente, safra)
  - Botão "Voltar" para retornar à lista de logs

---

## 📊 RESUMO DAS CORREÇÕES

| Item | Status | Descrição |
|------|--------|-----------|
| API busca por O.S | ✅ | `/api/bonus-m10/buscar-os-churn/` criada |
| Salvar sem `numero_pedido` | ✅ | Fluxo genérico agora salva usando `nr_ordem` |
| Normalização `anomes_gross` | ✅ | Função `_normalizar_anomes_gross()` implementada |
| Log de linhas ignoradas | ✅ | Response inclui `linhas_ignoradas` e `motivo_ignoradas` |
| Página de validação | ✅ | `buscarOS()` mostra dados corretos de CHURN |

---

## 🔍 COMO USAR A NOVA FUNCIONALIDADE

### **1. Buscar O.S na página de validação:**
```
1. Acesse: /validacao-churn/
2. No campo "Buscar O.S", digite o número (ex.: 05444203)
3. Pressione Enter ou clique em "Buscar"
4. Veja os resultados em tabela com todos os dados de churn
```

### **2. Verificar se importação salvou 100%:**
```
1. Após importar planilha pelo fluxo genérico (/import/churn/)
2. Verifique o response JSON:
   - "linhas_ignoradas": 0 → ✅ Tudo foi salvo
   - "linhas_ignoradas": > 0 → ⚠️ Algumas linhas foram puladas (ver "motivo_ignoradas")
```

### **3. Consultar O.S específica via API:**
```bash
GET /api/bonus-m10/buscar-os-churn/?os=05444203
Authorization: Bearer <token>

Response:
{
  "total": 1,
  "os": "05444203",
  "variantes_tentadas": ["05444203", "05444203"],
  "registros": [
    {
      "id": 123,
      "nr_ordem": "05444203",
      "numero_pedido": "...",
      "anomes_gross": "202507",  // ✅ Normalizado
      "dt_retirada": "2025-08-15",
      "contrato_m10": {...}
    }
  ]
}
```

---

**Documentado em:** 25/01/2026  
**Status:** ✅ **CORREÇÕES IMPLEMENTADAS E TESTADAS**
