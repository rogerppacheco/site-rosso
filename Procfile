release: playwright install && sh scripts/migrate_unpooled.sh && python manage.py createcachetable
web: sh scripts/start_web.sh
scheduler: python manage.py run_scheduler