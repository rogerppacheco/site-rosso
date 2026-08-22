# Scheduler em serviço dedicado

O APScheduler **não** roda mais dentro do Gunicorn. Tarefas automáticas ficam em um processo separado.

## Comandos

| Processo | Comando |
|----------|---------|
| Web (HTTP) | `gunicorn gestao_equipes.wsgi ...` |
| Scheduler | `python manage.py run_scheduler` |

## Railway (automático)

Passo a passo completo (token GitHub ou terminal): **`docs/DEPLOY_RAILWAY_AUTOMATICO.md`**

Resumo — GitHub Actions (recomendado):

1. Token em [railway.app/account/tokens](https://railway.app/account/tokens)
2. Secret `RAILWAY_TOKEN` no GitHub
3. Actions → **Railway scheduler setup** → Run workflow

Ou no PowerShell:

```powershell
$env:RAILWAY_TOKEN = "seu_token"
powershell -ExecutionPolicy Bypass -File scripts\railway_setup_scheduler.ps1
```

O script cria o serviço `site-record-scheduler`, copia as variáveis do web, faz deploy e usa `Dockerfile.scheduler` + `railway.scheduler.toml`.

Depois, no painel Railway (serviço scheduler): **Settings → Config-as-code** → `/railway.scheduler.toml` e **Replicas = 1**.

Serviço **web**: continua com `Dockerfile` (Gunicorn). **Não** roda mais o scheduler.

## Local

Terminal 1: `python manage.py runserver`  
Terminal 2: `python manage.py run_scheduler`

## Jobs (inalterados)

- Faturas Nio — diário 00:05
- Performance — verificação a cada 1 min
- Boas-vindas — fila a cada 5 min
- Sonax fallback — a cada 2 min
