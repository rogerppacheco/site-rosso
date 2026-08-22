#!/usr/bin/env bash
# Configura e faz deploy do serviço Railway "site-record-scheduler".
# Requer: RAILWAY_TOKEN (conta Railway) — https://railway.app/account/tokens
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PROJECT_ID="${RAILWAY_PROJECT_ID:-7171eee1-2c6e-446a-b7a9-880d3786c51a}"
SCHEDULER_SERVICE="${RAILWAY_SCHEDULER_SERVICE:-site-record-scheduler}"
WEB_SERVICE="${RAILWAY_WEB_SERVICE:-}"
GITHUB_REPO="${RAILWAY_GITHUB_REPO:-rogerppacheco/site-record}"
ENV_NAME="${RAILWAY_ENVIRONMENT:-production}"

if ! command -v railway >/dev/null 2>&1; then
  echo "Instalando Railway CLI..."
  npm install -g @railway/cli
fi

if [ -z "${RAILWAY_TOKEN:-}" ]; then
  echo "ERRO: defina RAILWAY_TOKEN (token de conta em railway.app/account/tokens)"
  exit 1
fi

echo "=== Railway: serviço scheduler ==="
if ! railway whoami 2>/dev/null; then
  echo "ERRO: RAILWAY_TOKEN inválido ou expirado. Gere um novo em railway.app/account/tokens"
  exit 1
fi

railway link -p "$PROJECT_ID" -e "$ENV_NAME" || railway link -p "$PROJECT_ID"

if [ -z "$WEB_SERVICE" ]; then
  WEB_SERVICE="$(railway service status --json 2>/dev/null | python3 -c "
import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    sys.exit(0)
for s in data.get('services') or []:
    n=s.get('name') or ''
    low=n.lower()
    if 'scheduler' in low or 'postgres' in low or 'redis' in low or 'mysql' in low:
        continue
    if n:
        print(n)
        break
" 2>/dev/null || true)"
fi
WEB_SERVICE="${WEB_SERVICE:-site-record}"
echo "Serviço web de referência: $WEB_SERVICE"

HAS_SCHEDULER=0
if railway service status --json 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
names=[(s.get('name') or '') for s in (data.get('services') or [])]
sys.exit(0 if '$SCHEDULER_SERVICE' in names else 1)
" 2>/dev/null; then
  HAS_SCHEDULER=1
fi

if [ "$HAS_SCHEDULER" -eq 0 ]; then
  echo "Criando serviço $SCHEDULER_SERVICE ..."
  railway add --service "$SCHEDULER_SERVICE" --repo "$GITHUB_REPO"
fi

echo "Copiando variáveis do web para o scheduler..."
railway link -p "$PROJECT_ID" -s "$WEB_SERVICE" -e "$ENV_NAME"
KV_LINES="$(railway variables --kv 2>/dev/null || true)"
railway link -p "$PROJECT_ID" -s "$SCHEDULER_SERVICE" -e "$ENV_NAME"

COUNT=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  case "$line" in
    RAILWAY_*=*) continue ;;
    *=*) ;;
    *) continue ;;
  esac
  railway variables --set "$line" --skip-deploys >/dev/null 2>&1 || true
  COUNT=$((COUNT + 1))
done <<< "$KV_LINES"
echo "Variáveis copiadas: $COUNT"

echo "Deploy do scheduler..."
railway up --detach -s "$SCHEDULER_SERVICE" -e "$ENV_NAME"

echo ""
echo "No painel Railway (serviço $SCHEDULER_SERVICE):"
echo "  Settings → Config-as-code → /railway.scheduler.toml"
echo "  Scaling → Replicas = 1"
echo "Concluído."
