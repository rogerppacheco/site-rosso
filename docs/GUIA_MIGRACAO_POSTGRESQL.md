# 🚀 GUIA COMPLETO: Migração MySQL → PostgreSQL (Railway)

## STATUS ATUAL:
✅ PostgreSQL (Railway): Criado e online
✅ Backup JSON: backup_mysql_producao_20260102_221849.json
✅ Conexões: Testadas e funcionando

---

## PASSO 1: CONFIGURAR SETTINGS PARA POSTGRESQL

Edite: `gestao_equipes/settings.py`

Encontre a seção DATABASES e altere para:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'railway',
        'USER': 'postgres',
        'PASSWORD': 'tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz',
        'HOST': 'maglev.proxy.rlwy.net',
        'PORT': '56422',
        'ATOMIC_REQUESTS': True,
        'CONN_MAX_AGE': 600,
    }
}
```

**IMPORTANTE**: Este é um passo LOCAL apenas. A produção continua em MySQL!

---

## PASSO 2: PREPARAR BANCO POSTGRESQL

```bash
# Instalar pacotes necessários
pip install psycopg2-binary

# Criar tabelas no PostgreSQL
python manage.py migrate --run-syncdb

# Carregar dados do backup
python manage.py loaddata backup_mysql_producao_20260102_221849.json
```

---

## PASSO 3: TESTAR LOCALMENTE

```bash
# Verificar dados importados
python manage.py dbshell

# Ou no Python:
python manage.py shell
>>> from crm_app.models import Cliente
>>> Cliente.objects.count()  # Deve retornar o mesmo que MySQL
```

---

## PASSO 4: CONFIGURAR NO RAILWAY

```bash
# No painel do Railway, serviço web → aba Variables, defina:
#   DATABASE_URL = (a connection string do serviço Postgres do projeto)

# Deploy (automático ao enviar para main)
git add .
git commit -m "PREP: Pronto para migrar para PostgreSQL"
git push origin main

# O app detecta DATABASE_URL e usa PostgreSQL
```

---

## PASSO 5: MONITORAR

```bash
# Ver logs
railway logs

# Verificar no banco PostgreSQL
railway connect Postgres
```

---

## ⚠️ IMPORTANTE:

1. **LOCAL**: Use PostgreSQL (ou SQLite) para testar
2. **RAILWAY**: Use a variável de ambiente DATABASE_URL do serviço Postgres

---

## PRÓXIMOS PASSOS:

1. ✋ Avise quando completar PASSO 1 (editar settings.py)
2. Vou ajudar com PASSO 2 se tiver erros
3. Depois testamos localmente
4. Só depois migra para produção

**Quer começar?**
