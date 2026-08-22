# 🔍 Diagnóstico do Problema - Importação FPD

## 📋 Situação Relatada

**Usuário:** Roger  
**Data:** 31/12/2024 22:53:20  
**Arquivo:** 1067098.xlsb  
**Problema:** "Já fiz o processo de importação duas vezes e não tem nada no banco com os dados que importei"

---

## 🕵️ Investigação Realizada

### 1. Verificação do Log de Importação

**Dados do log:**
```
Nome do arquivo: 1067098.xlsb
Usuário: Roger
Status: SUCESSO ✅
Total de linhas: 2.574
Total processadas: 0 ❌
Total erros: 0
Duração: 11 segundos
Valor importado: R$ 0,00
```

**Conclusão Inicial:**
- ✅ Arquivo foi lido com sucesso (2.574 linhas)
- ✅ Não houve erros de formato/parsing
- ❌ **ZERO registros foram salvos no banco**
- ⏱️ Processamento rápido (11s) indica que não houve tentativas de salvar

---

## 🎯 Diagnóstico: Causa Raiz

### O problema está na lógica da view `ImportarFPDView`

**Código problemático (antes da refatoração):**
```python
for index, row in df.iterrows():
    try:
        nr_ordem = str(row['nr_ordem']).strip()
        
        # PROBLEMA: Só tenta salvar se contrato existir
        contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
        
        # Se chegou aqui, contrato existe → salva dados
        # ...código de salvamento...
        
    except ContratoM10.DoesNotExist:
        # PROBLEMA: Apenas incrementa contador, não salva nada
        registros_nao_encontrados += 1
        continue  # Pula para próxima linha
```

**O que aconteceu:**
1. View leu as 2.574 linhas do arquivo
2. Para CADA linha, tentou buscar `ContratoM10` com o `nr_ordem`
3. Como **NENHUM** contrato foi encontrado:
   - Incrementou `registros_nao_encontrados` 2.574 vezes
   - Não salvou nada
   - Continuou para próxima linha
4. No final: status "SUCESSO" (arquivo lido) mas 0 registros salvos

---

## 📊 Verificação nos Bancos de Dados

### Tabela: `ImportacaoFPD`
```sql
SELECT COUNT(*) FROM ImportacaoFPD;
-- Resultado: 0 registros
```

### Tabela: `ContratoM10`
```sql
SELECT COUNT(*) FROM ContratoM10;
-- Resultado: 322 contratos

SELECT COUNT(*) FROM ContratoM10 WHERE ordem_servico IS NOT NULL;
-- Verificar quantos têm O.S preenchida
```

### Tabela: `FaturaM10` (campos FPD)
```sql
SELECT COUNT(*) FROM FaturaM10 
WHERE id_contrato_fpd IS NOT NULL;
-- Resultado: 0 (confirmando que nenhum dado FPD foi salvo)
```

---

## 🔍 Por Que Isso Aconteceu?

### Possíveis Causas:

#### 1. **Os números de O.S do arquivo FPD não correspondem aos do banco CRM**

**Exemplo:**
- Arquivo FPD tem: `OS-12345`, `OS-67890`, `OS-11111`
- Banco CRM tem: `OS-99999`, `OS-88888`, `OS-77777`
- Resultado: 0 matches = 0 registros salvos

**Como verificar:**
```python
# Script para comparar
import pandas as pd

# Ler arquivo FPD
df = pd.read_excel('1067098.xlsb')
os_fpd = set(df['nr_ordem'].astype(str).str.strip())

# Buscar O.S no banco
from crm_app.models import ContratoM10
os_crm = set(ContratoM10.objects.values_list('ordem_servico', flat=True))

# Comparar
em_comum = os_fpd & os_crm
print(f"O.S no FPD: {len(os_fpd)}")
print(f"O.S no CRM: {len(os_crm)}")
print(f"Em comum: {len(em_comum)}")
```

#### 2. **Formato diferente de O.S**

**Possibilidades:**
- FPD: `12345` (sem prefixo)
- CRM: `OS-12345` (com prefixo)

Ou vice-versa.

**Como verificar:**
```python
# Ver primeiras O.S de cada fonte
print("FPD:", df['nr_ordem'].head(10).tolist())
print("CRM:", ContratoM10.objects.values_list('ordem_servico', flat=True)[:10])
```

#### 3. **Campo `ordem_servico` vazio no `ContratoM10`**

**Problema:**
- Contratos M10 foram importados
- Mas campo `ordem_servico` está NULL/vazio

**Como verificar:**
```sql
SELECT COUNT(*) FROM ContratoM10 WHERE ordem_servico IS NULL OR ordem_servico = '';
```

Se retornar 322 (todos), então o problema é que nenhum contrato tem O.S cadastrada!

#### 4. **Espaços ou caracteres invisíveis**

**Problema:**
- `"OS-12345 "` (com espaço no final) ≠ `"OS-12345"`

**Solução já implementada:**
```python
nr_ordem = str(row['nr_ordem']).strip()  # Remove espaços
```

Mas pode ter outros caracteres invisíveis.

---

## ✅ Soluções Propostas

### Solução 1: Verificar e Corrigir Dados

**Passo a passo:**

1. **Verificar formato das O.S no FPD:**
```python
import pandas as pd
df = pd.read_excel('1067098.xlsb')
print("Primeiras 10 O.S do FPD:")
print(df['nr_ordem'].head(10))
```

2. **Verificar formato das O.S no CRM:**
```python
from crm_app.models import ContratoM10
print("Primeiras 10 O.S do CRM:")
for c in ContratoM10.objects.all()[:10]:
    print(f"ID: {c.id} | O.S: '{c.ordem_servico}'")
```

3. **Comparar e ajustar:**
- Se FPD tem `12345` e CRM tem `OS-12345`: Adicionar prefixo
- Se FPD tem `OS-12345` e CRM tem `12345`: Remover prefixo

### Solução 2: Importar Contratos M10 Primeiro

**Se o problema é falta de dados no CRM:**

1. Verificar se existe arquivo de contratos M10
2. Importar contratos ANTES de importar FPD
3. Garantir que campo `ordem_servico` seja preenchido
4. Depois importar FPD novamente

### Solução 3: Relaxar Condição de Match (Avançado)

**Modificar a view para salvar mesmo sem match:**

```python
# Opção A: Salvar em ImportacaoFPD sem FK (permite análise posterior)
ImportacaoFPD.objects.create(
    nr_ordem=nr_ordem,
    contrato_m10=None,  # Sem FK
    # ...outros campos...
)

# Opção B: Criar tabela temporária de staging
class ImportacaoFPDStaging(models.Model):
    # Todos os campos do FPD
    # Sem FKs obrigatórias
    # Processar depois com script de matching
```

### Solução 4: Script de Normalização e Match

**Criar script que:**
1. Lê arquivo FPD
2. Normaliza números de O.S (remove espaços, padroniza formato)
3. Tenta fazer match com múltiplas estratégias:
   - Match exato
   - Match sem prefixo
   - Match com Levenshtein distance (similaridade)
4. Gera relatório de matches e não-matches
5. Permite decisão manual antes de importar

---

## 🛠️ Como Usar o Novo Sistema de Validação

### Agora você pode:

1. **Acessar `/validacao-fpd/`**
2. **Ver o log da importação:**
   - Status: SUCESSO (arquivo foi processado)
   - Processadas: 0 (NENHUM registro salvo)
   - Total linhas: 2.574
3. **Clicar no botão 👁️ para ver detalhes**
4. **Verificar a lista de O.S não encontradas** (primeiras 20 serão exibidas)
5. **Entender o problema visualmente**

### Próxima importação:

Quando você fizer uma nova importação (após corrigir o problema):

1. Faça o upload do arquivo
2. Vá imediatamente para `/validacao-fpd/`
3. Veja o log em tempo real
4. Se status for ⚠️ PARCIAL:
   - Clique em 👁️
   - Veja quais O.S falharam
   - Corrija apenas essas
5. Se status for ✅ SUCESSO:
   - Parabéns! Tudo funcionou!

---

## 📊 Estatísticas Atuais

```
Base de Dados (31/12/2024):
┌──────────────────────────────────┬─────────┐
│ Tabela                           │ Registros│
├──────────────────────────────────┼─────────┤
│ ContratoM10                      │ 322     │
│ ImportacaoFPD                    │ 0       │
│ LogImportacaoFPD                 │ 1       │
│ FaturaM10 (com dados FPD)        │ 0       │
└──────────────────────────────────┴─────────┘

Conclusão:
- ✅ 322 contratos M10 no banco
- ❌ 0 dados FPD importados
- ⚠️ 1 tentativa de importação registrada (falhou silenciosamente)
```

---

## 🎯 Ação Recomendada AGORA

### Passo 1: Investigar Dados
```python
# Execute este script:
python ver_comparacao_os.py  # (criar script abaixo)
```

**Script `ver_comparacao_os.py`:**
```python
import os
import django
import pandas as pd

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10

# Ler arquivo FPD
print("Lendo arquivo FPD...")
df = pd.read_excel('1067098.xlsb')
os_fpd = df['nr_ordem'].astype(str).str.strip().unique()

print(f"\n📄 Arquivo FPD:")
print(f"   Total O.S únicas: {len(os_fpd)}")
print(f"   Primeiras 10: {os_fpd[:10].tolist()}")

# Buscar O.S no banco
print(f"\n🏢 Banco CRM:")
os_crm = list(ContratoM10.objects.exclude(
    ordem_servico__isnull=True
).values_list('ordem_servico', flat=True))

print(f"   Total O.S únicas: {len(os_crm)}")
print(f"   Primeiras 10: {os_crm[:10]}")

# Comparar
em_comum = set(os_fpd) & set(os_crm)
so_fpd = set(os_fpd) - set(os_crm)
so_crm = set(os_crm) - set(os_fpd)

print(f"\n🔍 ANÁLISE:")
print(f"   ✅ Em comum: {len(em_comum)} ({len(em_comum)/len(os_fpd)*100:.1f}% do FPD)")
print(f"   ❌ Só no FPD: {len(so_fpd)}")
print(f"   ⚠️  Só no CRM: {len(so_crm)}")

if len(em_comum) > 0:
    print(f"\n✅ BOAS NOTÍCIAS: {len(em_comum)} O.S podem ser importadas!")
    print(f"   Exemplos: {list(em_comum)[:5]}")
else:
    print(f"\n❌ PROBLEMA CRÍTICO: NENHUMA O.S em comum!")
    print(f"\n   Comparando formatos:")
    print(f"   FPD exemplo: '{os_fpd[0]}'")
    print(f"   CRM exemplo: '{os_crm[0] if os_crm else 'VAZIO'}'")
    print(f"\n   Possíveis causas:")
    print(f"   1. Formato diferente (OS-12345 vs 12345)")
    print(f"   2. Base CRM não tem O.S cadastradas")
    print(f"   3. Arquivo FPD é de outra base/período")

if len(so_fpd) > 0:
    print(f"\n❌ O.S que falharam (primeiras 20):")
    for os in list(so_fpd)[:20]:
        print(f"   • {os}")
```

### Passo 2: Corrigir Baseado no Resultado

**Se "✅ Em comum > 0":**
- Reimporte o arquivo
- Agora deveria funcionar!

**Se "❌ Em comum = 0":**
- Identifique o padrão (formato)
- Ajuste uma das bases ou crie script de conversão
- Depois reimporte

### Passo 3: Validar Resultado
1. Acesse `/validacao-fpd/`
2. Veja o novo log
3. Confirme que `total_processadas > 0`
4. Verifique `total_contratos_nao_encontrados` (deveria ser baixo)

---

## 📞 Suporte Adicional

Se após seguir este diagnóstico o problema persistir:

1. **Compartilhe os resultados do script `ver_comparacao_os.py`**
2. **Informe:**
   - Quantas O.S em comum foram encontradas
   - Exemplos de O.S do FPD vs CRM
   - Se campo `ordem_servico` está preenchido no CRM
3. **Considere:**
   - Enviar amostra do arquivo FPD (primeiras 10 linhas)
   - Exportar amostra da tabela ContratoM10

---

**Diagnóstico realizado em:** Janeiro 2025  
**Status:** ✅ Problema identificado - Aguardando validação de dados  
**Próximo passo:** Executar script de comparação
