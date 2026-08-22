# 📊 FLUXO: Validação e Atualização de Importações

## ANTES ❌

```
Arquivo FPD
    ↓
Para cada linha (O.S + Fatura):
    ↓
┌──────────────────────────────────┐
│ Procura em ImportacaoFPD?        │
├──────┬──────────────────────┬────┤
│ SIM  │        NÃO           │    │
│      │                      │    │
│ CRIA │       CRIA           │    │
│ novo │      novo            │    │
│      │                      │    │
└──────┴──────────────────────┴────┘

Problema: Mesma importação 2x = 2x registros
         (duplicados!) ❌
```

## DEPOIS ✅

```
Arquivo FPD
    ↓
Para cada linha (O.S + Fatura):
    ↓
┌──────────────────────────────────┐
│ Procura em ImportacaoFPD por:    │
│ NR_ORDEM + NR_FATURA?            │
├──────────┬──────────────────┐────┤
│ ENCONTROU│ NÃO ENCONTROU    │    │
│          │                  │    │
│ATUALIZA ✅│ CRIA ✅          │    │
│ todos os │ novo             │    │
│ campos   │ registro         │    │
│          │                  │    │
└──────────┴──────────────────┘────┘

Resultado: Mesma importação 2x = 1 registro atualizado
          (sem duplicação!) ✅
```

---

## 🔄 FLUXO DETALHADO

### Importação 1 (Arquivo inicial)
```
Arquivo: 3 O.S (123, 124, 125)

Sistema:
├─ O.S 123 + FAT1: Não existe → CRIA ✅
├─ O.S 124 + FAT2: Não existe → CRIA ✅
└─ O.S 125 + FAT3: Não existe → CRIA ✅

Log:
┌───────────────────────┐
│ ✅ Importação Sucesso │
│ Criados: 3            │
│ Atualizados: 0        │
│ Total: 3              │
└───────────────────────┘

Banco:
┌─────────────────────┐
│ ImportacaoFPD       │
├─────────────────────┤
│ 1. O.S 123, FAT1    │
│ 2. O.S 124, FAT2    │
│ 3. O.S 125, FAT3    │
└─────────────────────┘
```

### Importação 2 (Mesmo arquivo)
```
Arquivo: 3 O.S (123, 124, 125)

Sistema:
├─ O.S 123 + FAT1: Já existe → ATUALIZA ✅
├─ O.S 124 + FAT2: Já existe → ATUALIZA ✅
└─ O.S 125 + FAT3: Já existe → ATUALIZA ✅

Log:
┌───────────────────────┐
│ ✅ Importação Sucesso │
│ Criados: 0            │
│ Atualizados: 3        │
│ Total: 3              │
└───────────────────────┘

Banco:
┌──────────────────────────┐
│ ImportacaoFPD            │
├──────────────────────────┤
│ 1. O.S 123, FAT1 (UPD)   │
│ 2. O.S 124, FAT2 (UPD)   │
│ 3. O.S 125, FAT3 (UPD)   │
└──────────────────────────┘

Resultado: Mesmos 3 registros, atualizados
```

### Importação 3 (Arquivo com novo registro)
```
Arquivo: 4 O.S (123, 124, 125, 126)

Sistema:
├─ O.S 123 + FAT1: Já existe → ATUALIZA ✅
├─ O.S 124 + FAT2: Já existe → ATUALIZA ✅
├─ O.S 125 + FAT3: Já existe → ATUALIZA ✅
└─ O.S 126 + FAT4: Não existe → CRIA ✅

Log:
┌───────────────────────┐
│ ✅ Importação Sucesso │
│ Criados: 1            │
│ Atualizados: 3        │
│ Total: 4              │
└───────────────────────┘

Banco:
┌──────────────────────────┐
│ ImportacaoFPD            │
├──────────────────────────┤
│ 1. O.S 123, FAT1 (UPD)   │
│ 2. O.S 124, FAT2 (UPD)   │
│ 3. O.S 125, FAT3 (UPD)   │
│ 4. O.S 126, FAT4 (NEW)   │
└──────────────────────────┘

Resultado: 4 registros (3 atualizados, 1 novo)
```

---

## 🔑 Chave de Validação

```python
ImportacaoFPD.objects.update_or_create(
    nr_ordem=nr_ordem,           # Chave 1
    nr_fatura=nr_fatura,         # Chave 2
    defaults={                   # Valores atualizáveis
        'id_contrato': ...,
        'dt_venc_orig': ...,
        'vl_fatura': ...,
        'ds_status_fatura': ...,
        'contrato_m10': ...,
    }
)
```

**Funcionamento:**
- **Chave (NR_ORDEM + NR_FATURA):** Define qual registro é "o mesmo"
- **Defaults:** Campos atualizados a cada importação

---

## ✅ GARANTIAS

✅ Nenhum registro duplicado
✅ Importações repetidas atualizam dados
✅ Log diferencia criações e atualizações
✅ Tabela consistente sempre

---

## 📊 Comparação Visual

| Ação | Antes ❌ | Depois ✅ |
|------|---------|----------|
| **1ª import (3 reg)** | 3 criados ✅ | 3 criados ✅ |
| **2ª import (mesmos 3)** | 3 criados + 3 antigos = **6 duplicados** ❌ | 0 criados, 3 atualizados = **3 no total** ✅ |
| **3ª import (4 reg, 1 novo)** | **10 total, com muitas duplicadas** ❌ | 1 criado, 3 atualizados = **4 no total** ✅ |

---

## 🚀 Como Usar

```bash
# Importar arquivo (1ª vez)
POST /api/bonus-m10/importar-fpd/
File: arquivo.xlsx
→ Resultado: Criados X, Atualizados 0

# Importar mesmo arquivo (2ª vez)
POST /api/bonus-m10/importar-fpd/
File: arquivo.xlsx
→ Resultado: Criados 0, Atualizados X

# Importar arquivo com novos registros (3ª vez)
POST /api/bonus-m10/importar-fpd/
File: arquivo_atualizado.xlsx
→ Resultado: Criados Y, Atualizados X
```

---

## 🧹 Script de Validação

```bash
# Verificar integridade
python limpar_e_validar_fpd.py
Opção: 4

# Resultado
✅ Total: 2574 registros
✅ Sem duplicatas
✅ Todos com valores válidos
✅ Status distribuído corretamente
```

---

✨ **Validação automática em cada importação!** ✨
