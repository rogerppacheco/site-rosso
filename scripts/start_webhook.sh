#!/bin/sh
set -e

# Railway nÃ£o executa release phase â€” garante schema antes do worker.
if [ -f /app/scripts/migrate_unpooled.sh ]; then
  sh /app/scripts/migrate_unpooled.sh --noinput
else
  python manage.py migrate --noinput
fi

# Agendador (APScheduler) embutido: manter o serviço com 1 réplica para não duplicar rotinas.
case "${WEBHOOK_EMBED_SCHEDULER:-false}" in
  true|True|TRUE|1|yes|Yes|YES)
    echo "[SCHEDULER] Iniciando agendador embutido no serviço de webhook..."
    (
      while true; do
        python manage.py run_scheduler || true
        echo "[SCHEDULER] Agendador encerrou; reiniciando em 10s..."
        sleep 10
      done
    ) &
    ;;
esac

echo "[WEBHOOK] Iniciando worker..."
exec python manage.py run_webhook_worker
