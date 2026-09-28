release: playwright install && sh scripts/migrate_unpooled.sh && python manage.py createcachetable
web: sh scripts/start_web.sh
scheduler: python manage.py run_scheduler
pap_worker: celery -A core_config worker --concurrency=1 --max-tasks-per-child=15 --loglevel=info
pap_beat: celery -A core_config beat --loglevel=info