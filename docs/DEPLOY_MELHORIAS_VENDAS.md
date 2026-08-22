# 🚀 Deploy - Melhorias no Cadastro de Vendas

## 📋 Resumo das Mudanças

### 1. Campo "Tem Fixo"
- ✅ Novo campo `tem_fixo` no modelo `Venda`
- ✅ Migration criada: `0075_add_tem_fixo_to_venda.py`
- ✅ Interface: pergunta sobre fixo após selecionar APP/SEM_APP

### 2. Validação de Telefones
- ✅ Validação de DDD válido no Brasil (rejeita código 55)
- ✅ Validação de 11 dígitos obrigatórios
- ✅ Máscara automática de entrada: `(00) 00000-0000`
- ✅ Validação no backend (serializers) e frontend

## 🔧 Arquivos Modificados

```
crm_app/models.py                          (campo tem_fixo)
crm_app/serializers.py                     (validações de telefone)
crm_app/migrations/0075_add_tem_fixo_to_venda.py  (nova migration)
frontend/public/crm_vendas.html            (interface e validações)
```

## 📝 Passos para Deploy no Railway

### 1. Commit das Mudanças
```powershell
git add crm_app/models.py
git add crm_app/serializers.py
git add crm_app/migrations/0075_add_tem_fixo_to_venda.py
git add frontend/public/crm_vendas.html

git commit -m "feat: Adiciona campo tem_fixo e validação de telefones

- Adiciona campo tem_fixo no modelo Venda
- Implementa validação de DDD válido no Brasil (rejeita 55)
- Valida telefones com 11 dígitos obrigatórios
- Adiciona máscara automática de entrada
- Interface: pergunta sobre fixo ao cadastrar venda"

git push origin main
```

### 2. Deploy Automático no Railway
O Railway detectará automaticamente o push e fará o deploy. A migration será aplicada automaticamente se configurado no `railway.json` ou via release command.

### 3. Verificar Migration (se necessário)
Se a migration não for aplicada automaticamente, execute via Railway CLI ou dashboard:

```bash
railway run python manage.py migrate crm_app
```

### 4. Coletar Arquivos Estáticos (se necessário)
```bash
railway run python manage.py collectstatic --noinput
```

## ✅ Checklist Pós-Deploy

- [ ] Migration aplicada com sucesso
- [ ] Testar cadastro de nova venda (APP)
- [ ] Testar cadastro de nova venda (SEM_APP)
- [ ] Verificar pergunta sobre fixo aparece corretamente
- [ ] Testar validação de telefone com DDD inválido (ex: 55)
- [ ] Testar validação de telefone com menos de 11 dígitos
- [ ] Testar validação de telefone com DDD válido
- [ ] Verificar máscara automática funcionando
- [ ] Testar edição de venda existente
- [ ] Verificar se campo tem_fixo é salvo corretamente

## 🧪 Testes Recomendados

### Teste 1: Cadastro com Fixo
1. Clicar em "Nova Venda"
2. Selecionar "Via APP" ou "Sem APP"
3. Verificar se aparece pergunta "A venda terá telefone fixo?"
4. Selecionar "Sim, tem fixo"
5. Preencher dados e salvar
6. Verificar se `tem_fixo = true` no banco

### Teste 2: Validação de Telefone
1. Tentar cadastrar telefone com DDD 55 → Deve rejeitar
2. Tentar cadastrar telefone com 10 dígitos → Deve rejeitar
3. Tentar cadastrar telefone com DDD válido e 11 dígitos → Deve aceitar
4. Verificar formatação automática: `(11) 98765-4321`

### Teste 3: Edição
1. Editar uma venda existente
2. Verificar se campo tem_fixo é carregado corretamente
3. Alterar e salvar
4. Verificar se alteração foi persistida

## ⚠️ Observações Importantes

1. **Migration é segura**: Apenas adiciona um campo booleano com default=False, não afeta dados existentes
2. **Validação retroativa**: Vendas antigas sem validação de telefone continuarão funcionando
3. **Compatibilidade**: Mudanças são compatíveis com versões anteriores

## 🐛 Troubleshooting

### Erro: "Field 'tem_fixo' doesn't have a default"
**Solução**: A migration já define `default=False`, mas se ocorrer, verifique se a migration foi aplicada.

### Telefones antigos não passam na validação
**Solução**: Vendas antigas podem ter telefones em formatos diferentes. A validação só se aplica a novas vendas/edições.

### Interface não mostra pergunta sobre fixo
**Solução**: Verificar se o arquivo `crm_vendas.html` foi atualizado no servidor. Limpar cache do navegador.

## 📊 Status

**Data**: 24/01/2026  
**Status**: ✅ PRONTO PARA DEPLOY  
**Migration**: `0075_add_tem_fixo_to_venda.py`  
**Impacto**: Baixo (apenas adiciona campo e validações)

---

**Sucesso!** 🎉 As melhorias estão prontas para produção!
