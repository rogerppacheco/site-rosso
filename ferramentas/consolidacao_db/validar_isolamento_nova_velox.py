import os, psycopg2
url = os.environ["DATABASE_UNPOOLED_URL"]
conn = psycopg2.connect(url)
cur = conn.cursor()
for schema in ("public", "nova_velox"):
    cur.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE'",
        (schema,),
    )
    print(f"{schema}_tables", cur.fetchone()[0])
cur.execute(
    "SELECT tablename FROM pg_tables WHERE schemaname='nova_velox' "
    "AND tablename IN ('django_migrations','auth_user','crm_venda') ORDER BY 1"
)
print("nova_velox_key_tables", [r[0] for r in cur.fetchall()])
cur.execute("SELECT count(*) FROM nova_velox.django_migrations")
print("nova_velox_migration_rows", cur.fetchone()[0])
cur.execute("SELECT count(*) FROM public.django_migrations")
print("public_migration_rows", cur.fetchone()[0])
cur.close()
conn.close()
