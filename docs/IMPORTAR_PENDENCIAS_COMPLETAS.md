# 📋 Importar Todas as Pendências em Produção

Este guia explica como importar a lista completa de 103 pendências em produção.

## 📁 Arquivo

O arquivo `scripts/pendencias_completas.csv` contém todas as 103 pendências que precisam ser cadastradas.

## 🚀 Como Importar em Produção

### Opção 1: Via Railway CLI (Recomendado)

```bash
# 1. Fazer upload do arquivo CSV para o Railway (ou copiar conteúdo)
# 2. Conectar ao Railway
railway login
railway link

# 3. Executar o comando (ajuste o caminho do arquivo)
railway run python manage.py importar_pendencias --arquivo scripts/pendencias_completas.csv
```

### Opção 2: Via Interface Web do Railway

1. Acesse https://railway.app/
2. Selecione seu projeto
3. Vá em "Deployments" → Deployment mais recente → "Open Shell"
4. Execute:
   ```bash
   python manage.py importar_pendencias --arquivo scripts/pendencias_completas.csv
   ```

### Opção 3: Criar Arquivo Direto no Servidor

Se preferir, você pode criar o arquivo CSV diretamente no shell do Railway:

```bash
# No shell do Railway, crie o arquivo
cat > pendencias.csv << 'EOF'
nome,tipo_pendencia
0009-ABRIR CHAMADO PEDIDO NÃO CONCLUÍDO,CLIENTE
7079-ACESSO IMPO. OBRA,CLIENTE
... (resto do conteúdo)
EOF

# Execute a importação
python manage.py importar_pendencias --arquivo pendencias.csv
```

## 📊 O que o Script Faz

1. **Lê o arquivo CSV** com todas as pendências
2. **Verifica se já existe** no banco (case-insensitive)
3. **Cria apenas as que não existem**
4. **Ignora as que já existem** (sem erro)
5. **Mostra relatório completo**:
   - ✓ Criadas: Quantas foram criadas
   - ⊙ Já existiam: Quantas já existiam no banco
   - ✗ Erros: Lista de erros (se houver)

## ⚠️ Importante

- O script **não duplica** pendências que já existem
- Usa verificação case-insensitive (ignora maiúsculas/minúsculas)
- Todas as operações são em transação (ou tudo ou nada)
- Se ocorrer erro, nenhuma pendência é salva

## ✅ Após a Importação

Depois de executar, verifique:

1. Acesse o sistema em produção
2. Vá em "Cadastros Gerais" → "Pendências"
3. Verifique se todas as pendências foram importadas
4. Confira se estão ordenadas alfabeticamente

## 🔍 Verificar Pendências no Banco

Para ver quantas pendências existem:

```bash
# No shell do Railway ou localmente
python manage.py shell

# No shell Python:
from crm_app.models import MotivoPendencia
print(f"Total: {MotivoPendencia.objects.count()}")
for p in MotivoPendencia.objects.all().order_by('nome'):
    print(f"{p.id}: {p.nome} ({p.tipo_pendencia})")
```
