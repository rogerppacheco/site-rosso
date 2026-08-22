#!/bin/sh
set -e

# Railway nÃ£o executa release phase â€” garante schema antes do worker.
if [ -f /app/scripts/migrate_unpooled.sh ]; then
  sh /app/scripts/migrate_unpooled.sh --noinput
else
  python manage.py migrate --noinput
fi

echo "[WEBHOOK] Iniciando worker..."
exec python manage.py run_webhook_worker
