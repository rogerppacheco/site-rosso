# NOVA ESTRUTURA DO BÔNUS M-10

## 🎯 Objetivo
Simplificar o fluxo do Bônus M-10 para que:
- Toda venda instalada automaticamente caia no M-10
- O cruzamento com FPD seja automático sempre
- Não precise de processos manuais intermediários

## 📊 Mudanças Estruturais

### 1. REMOVER SafraM10
- ❌ Não precisamos mais agrupar por mês
- ✅ ContratoM10 pode estar diretamente ligado à Venda

### 2. SIMPLIFICAR ContratoM10
```python
class ContratoM10(models.Model):
    # Ligação direta com Venda (não mais com SafraM10)
    venda = models.ForeignKey('Venda', on_delete=models.CASCADE, related_name='contrato_m10')
    
    # Dados básicos (vêm da Venda)
    ordem_servico = models.CharField(max_length=100, unique=True)
    
    # Dados do FPD (preenchidos automaticamente via signal)
    numero_contrato_definitivo = models.CharField(max_length=100, null=True, blank=True)
    data_ultima_sincronizacao_fpd = models.DateTimeField(null=True, blank=True)
    
    # Status de elegibilidade
    elegivel_bonus = models.BooleanField(default=False)
    teve_downgrade = models.BooleanField(default=False)
    data_cancelamento = models.DateField(null=True, blank=True)
    motivo_cancelamento = models.CharField(max_length=255, blank=True, null=True)
```

### 3. USAR SIGNALS (Django Signals)
Quando uma Venda é criada/atualizada:
```
Evento: Venda.save()
  ↓
Signal: post_save(Venda)
  ↓
Ação 1: Criar/Atualizar ContratoM10
  ↓
Ação 2: Buscar ImportacaoFPD com mesma O.S
  ↓
Ação 3: Se encontrar, atualizar numero_contrato_definitivo
```

### 4. CRIAR VIEW PARA SINCRONIZAÇÃO MANUAL
- Endpoint para sincronizar FPD sob demanda
- Busca ImportacaoFPD que não foram vinculadas
- Atualiza numero_contrato_definitivo nos ContratoM10 existentes

## ✅ Benefícios
- Nenhum processo manual necessário
- Dados sempre sincronizados
- M-10 reflete o estado real das vendas
- FPD integrado automaticamente
