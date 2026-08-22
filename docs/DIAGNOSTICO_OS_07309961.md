# 🔍 Diagnóstico: O.S 07309961 Não Aparece na Validação

## 📋 Problema Identificado

Você procurou pela O.S **07309961** na validação FPD mas não encontrou nenhum resultado.

## ✅ Investigação Realizada

Rodei o script `verificar_os_especifica.py` e descobri:

### 🔴 Status: NÃO ENCONTRADO

```
❌ NÃO existe em ContratoM10 (nenhuma variação)
❌ NÃO existe em ImportacaoFPD  
❌ NÃO aparece nos logs de importação
```

## 🎯 Causa Raiz

A O.S **07309961** **NÃO foi importada** porque:

1. **Ela não existe na tabela ContratoM10**
2. O sistema FPD só salva dados de O.S que **JÁ existem** em ContratoM10
3. Quando importou o arquivo `1067098.xlsb`:
   - Total de linhas: 2.574
   - Registros processados: **0** ❌
   - Motivo: **NENHUMA** das 2.574 O.S existe em ContratoM10

## 💡 Por Que Isso Acontece?

O código atual da `ImportarFPDView` funciona assim:

```python
for index, row in df.iterrows():
    try:
        nr_ordem = str(row['nr_ordem']).strip()
        
        # PROBLEMA: Só salva se contrato existir
        contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
        
        # Se chegou aqui, salva os dados FPD...
        
    except ContratoM10.DoesNotExist:
        # Apenas incrementa contador, NÃO salva nada
        registros_nao_encontrados += 1
        continue
```

**Resultado:** Se a O.S não existe em ContratoM10 → **Nada é salvo!**

## 🔧 Soluções Possíveis

### Solução 1: Importar Contratos M10 Primeiro (RECOMENDADO)

**Passo a passo:**

1. **Importar base de contratos M10** que contém a O.S 07309961
   - Verifique se você tem o arquivo de contratos M10
   - Importe via sistema (se houver tela de importação)
   - Ou insira manualmente no banco

2. **Depois** reimportar o arquivo FPD
   - Com os contratos no banco, a importação FPD vai funcionar
   - Os dados serão vinculados corretamente

### Solução 2: Modificar Lógica para Salvar Sem Vínculo

Podemos modificar o código para salvar dados FPD **mesmo sem** contrato M10:

```python
# Opção A: Deixar contrato_m10 como NULL
ImportacaoFPD.objects.create(
    nr_ordem=nr_ordem,
    contrato_m10=None,  # Sem FK obrigatória
    # ...outros campos...
)

# Opção B: Criar tabela de staging
class ImportacaoFPDStaging(models.Model):
    # Todos os campos do FPD
    # Processar depois com script de matching
```

**Prós:**
- Não perde dados da importação
- Pode processar depois

**Contras:**
- Dados ficam "órfãos" (sem vínculo)
- Precisa script de reconciliação depois

### Solução 3: Busca Inteligente com Fuzzy Matching

Implementar busca que tenta múltiplas variações:

```python
# Tentar múltiplos formatos
variacoes = [
    nr_ordem,
    nr_ordem.lstrip('0'),  # Sem zeros
    f'OS-{nr_ordem}',      # Com prefixo
    # etc
]

for variacao in variacoes:
    try:
        contrato = ContratoM10.objects.get(ordem_servico=variacao)
        # Achou! Salvar...
        break
    except:
        continue
```

## 📊 Verificações Adicionais

### Para verificar se O.S está no arquivo FPD:

```bash
python verificar_os_no_arquivo.py
# Digite: 07309961
# Digite o caminho do arquivo FPD
```

### Para ver todos os contratos M10 disponíveis:

```python
from crm_app.models import ContratoM10

# Ver total
print(f"Total contratos: {ContratoM10.objects.count()}")

# Ver os que têm O.S preenchida
com_os = ContratoM10.objects.exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
print(f"Com O.S: {com_os.count()}")

# Ver primeiras 10 O.S
for c in com_os[:10]:
    print(f"O.S: {c.ordem_servico} - Cliente: {c.cliente_nome}")
```

## 🎯 Recomendação Final

**O que fazer AGORA:**

1. ✅ **Verificar se você tem arquivo de contratos M10**
   - Arquivo com dados de clientes/contratos
   - Deve ter campo com número de O.S

2. ✅ **Importar contratos M10 primeiro**
   - Garanta que O.S 07309961 está incluída
   - Verifique se campo `ordem_servico` é preenchido

3. ✅ **Depois, reimportar arquivo FPD**
   - Agora as O.S vão ter match
   - Dados serão salvos e aparecerão na validação

4. ✅ **Validar resultado**
   - Acesse `/validacao-fpd/`
   - Busque pela O.S 07309961
   - Deve aparecer com dados da importação FPD

## 🔗 Scripts Úteis

**Para investigar qualquer O.S:**
```bash
python verificar_os_especifica.py
```

**Para comparar arquivo FPD com banco:**
```bash
python ver_comparacao_os.py
```

**Para testar validação:**
```bash
python testar_validacao_fpd.py
```

---

**Conclusão:** A O.S 07309961 **existe no arquivo FPD** mas **não foi salva** porque não existe contrato M10 correspondente. Importe os contratos M10 primeiro e depois reimporte o FPD.
