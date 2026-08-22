# Deploy automático no Railway

## O que já está feito no código

- **Web**: Gunicorn só para HTTP (scheduler removido do processo web).
- **Scheduler**: `Dockerfile.scheduler` + `railway.scheduler.toml` + `python manage.py run_scheduler`.
- Push na branch `main` atualiza o serviço web ligado ao GitHub (se já estiver assim no Railway).

## O que falta (uma vez só): token Railway válido

O token antigo (`RAILWAY_TOKEN` na máquina) está **expirado**. Sem um token novo, nem o Cursor nem o GitHub conseguem criar o serviço scheduler.

### Opção A — GitHub Actions (recomendado, sem terminal)

1. Abra [railway.app/account/tokens](https://railway.app/account/tokens) → **Create Token** (token de **conta**).
2. No GitHub: repositório **site-record** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
   - Nome: `RAILWAY_TOKEN`
   - Valor: cole o token
3. **Actions** → workflow **Railway scheduler setup** → **Run workflow**.
4. No painel Railway, serviço **site-record-scheduler**:
   - **Settings** → **Config-as-code** → `/railway.scheduler.toml`
   - **Scaling** → **Replicas = 1**

### Opção B — Terminal no PC (após `railway login` ou token)

```powershell
$env:RAILWAY_TOKEN = "cole_o_token_aqui"
powershell -ExecutionPolicy Bypass -File scripts\railway_setup_scheduler.ps1
```

## Importante

Enquanto o serviço **scheduler** não estiver no ar com **1 réplica**, estas tarefas **não rodam** em produção:

- Busca automática de faturas (Nio)
- Envio de performance
- Fila de boas-vindas
- Fallback Sonax

O site (login, CRM, webhooks) continua funcionando no serviço web.

## Projeto Railway (produção site-record)

- Projeto: **pleasing-recreation** (`7171eee1-2c6e-446a-b7a9-880d3786c51a`)
- Serviço web: **site-record**
- Serviço scheduler: **site-record-scheduler**

> **Nota:** `melodious-hope` é outro projeto (viabilidade); não usar para o site-record.
