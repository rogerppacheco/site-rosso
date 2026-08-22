# 🔧 Como Corrigir Erro de Chave Duplicada no Upload FPD

## ❌ Erro
```
duplicate key value violates unique constraint "crm_app_faturam10_pkey"
DETAIL: Key (id)=(223) already exists.
```

## 🔍 Causa
A sequência do PostgreSQL está desatualizada. Isso acontece quando:
- Registros são inseridos manualmente no banco
- Dados são importados fora do Django ORM
- A sequência não é atualizada automaticamente

## ✅ Solução

### Opção 1: Via Railway CLI (Recomendado)

1. **Instalar Railway CLI** (se ainda não tiver):
   ```powershell
   npm install -g @railway/cli
   ```

2. **Fazer login no Railway**:
   ```powershell
   railway login
   ```

3. **Conectar ao projeto**:
   ```powershell
   railway link
   ```

4. **Executar o comando de correção**:
   ```powershell
   railway run python manage.py corrigir_sequencia_faturam10
   ```

### Opção 2: Via Dashboard do Railway

1. Acesse: https://railway.app
2. Faça login e selecione o projeto
3. Clique no **service** da aplicação
4. Vá na aba **"Deployments"** ou **"Shell"**
5. Execute:
   ```bash
   python manage.py corrigir_sequencia_faturam10
   ```

### Opção 3: Script Python Direto

Se preferir executar o script diretamente:

```powershell
railway run python ferramentas/corrigir_sequencia_faturam10.py
```

## 📋 O que o comando faz

1. ✅ Encontra o maior ID existente na tabela `FaturaM10`
2. ✅ Ajusta a sequência do PostgreSQL para o próximo valor disponível
3. ✅ Garante que novos registros não tentem usar IDs já existentes

## ⚠️ Importante

- **É seguro**: O comando apenas ajusta a sequência, não altera ou remove dados
- **Não destrutivo**: Não há risco de perda de dados
- **Rápido**: Execução em segundos

## 🎯 Após executar

Depois de executar o comando, tente fazer o upload do FPD novamente. O erro de chave duplicada não deve mais ocorrer.

## 🔄 Se o erro persistir

Se ainda ocorrer o erro após executar o comando:

1. Verifique se há registros com IDs muito altos:
   ```powershell
   railway run python manage.py shell
   ```
   ```python
   from crm_app.models import FaturaM10
   print(FaturaM10.objects.aggregate(max_id=Max('id')))
   ```

2. Execute o comando novamente:
   ```powershell
   railway run python manage.py corrigir_sequencia_faturam10
   ```

3. Se necessário, verifique a sequência manualmente:
   ```powershell
   railway run python manage.py dbshell
   ```
   ```sql
   SELECT currval(pg_get_serial_sequence('crm_app_faturam10', 'id'));
   SELECT MAX(id) FROM crm_app_faturam10;
   ```
