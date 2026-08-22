# Fase 0 — Consolidação de bancos PostgreSQL (Railway)

Consolida **sysr-vendas-api** e **syncwa-api** no Postgres central do projeto `site-record`, usando schemas dedicados:

| Schema   | Aplicação        | ORM    |
|----------|------------------|--------|
| `public` | site-record (Django) | Django |
| `sysr`   | sysr-vendas-api  | Prisma |
| `syncwa` | syncwa-api       | Prisma |

## Pré-requisitos

- [Railway CLI](https://docs.railway.app/develop/cli) autenticada
- Python do projeto site-record (venv ou `railway run`)
- Opcional: `pg_dump` para backup local

## Fase 0 (preparação — sem cutover)

```powershell
cd c:\site-record
powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase0.ps1
```

O script:

1. Cria schemas `sysr` e `syncwa` no banco central (`00_criar_schemas.sql`)
2. Gera inventário JSON do central, sysr isolado e syncwa isolado em `backups/consolidacao_db/`
3. Opcionalmente faz `pg_dump` do central

### Prisma (já preparado nos repos)

- `C:\sysr_vendas\backend\prisma\schema.prisma` → `schemas = ["sysr"]`, `@@schema("sysr")`
- `C:\SyncWA\prisma\schema.prisma` → `schemas = ["syncwa"]`, `@@schema("syncwa")`
- `.env.example` atualizados com `?schema=sysr` / `?schema=syncwa`

Reaplicar patch se necessário:

```powershell
python ferramentas\consolidacao_db\patch_prisma_schemas.py
```

## Fase 1 (estrutura + dados — sem cutover de APIs)

```powershell
powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase1.ps1
```

O script:

1. **SyncWA:** baseline Prisma (`baseline_syncwa.sql`) + dados isolados → schema `syncwa`
2. **SysR:** pg_dump schema-only + data-only do Postgres isolado → schema `sysr` (CRM + Evolution)
3. Registra `_prisma_migrations` em cada schema
4. Smoke test com `COUNT(*)` exato (ignora `_prisma_migrations`)

### Regenerar baselines Prisma

```powershell
python ferramentas\consolidacao_db\gerar_baselines.py
```

## Fase 2 (cutover das APIs) — concluida em 23/06/2026

```powershell
powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase2.ps1
```

O script:

1. Backup das URLs antigas em `backups/consolidacao_db/cutover_backup_*.json`
2. Atualiza `DATABASE_URL` / `DATABASE_CONNECTION_URI` via `--stdin` (evita parsing de `?` no CLI)
3. Corrige `_prisma_migrations` (SyncWA + Evolution rodam `migrate deploy` no startup)
4. Redeploy syncwa-api e evolution-api
5. Health checks

### URLs atuais (producao)

| Servico | Variavel | Schema |
|---------|----------|--------|
| sysr-vendas-api | `DATABASE_URL` | `sysr` |
| syncwa-api | `DATABASE_URL` | `syncwa` |
| evolution-api | `DATABASE_CONNECTION_URI` | `sysr` |

Host: `maglev.proxy.rlwy.net:56422/railway` (Postgres central)

## Fase 3 (descomissionamento) — concluida em 23/06/2026

```powershell
powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase3.ps1
```

Postgres isolados removidos de `sysr-vendas-api` e `syncwa-platform`. Backups finais em `backups/consolidacao_db/isolado_*_final_*.dump`. Registro em `fase3_concluida.json`.

Servicos que permanecem: Redis (syncwa + sysr), n8n, evolution-api — todos apontando para o Postgres central onde aplicavel.

## Fase 4 (PgBouncer) — pendente cutover

### Por que nao aparece "Connection Pooling"?

O Postgres central usa a imagem **template classica** `postgres-ssl:17` (nao gerenciada).
Esse tipo **nao tem** o menu `Database → Config → Connection Pooling`.
Esse menu existe apenas no **Postgres gerenciado novo** do Railway.

**Solucao oficial (equipe Railway):** deploy do **template PgBouncer** no mesmo projeto.

### Passo a passo (template OpUzwe)

1. Abra https://railway.com/project/8db60e30-1dde-43f9-afaa-bfc19682fe0b
2. Clique direito no canvas → **Add** → **Template**
3. Busque **PgBouncer** → template [OpUzwe](https://railway.com/template/OpUzwe)
4. **Antes do Deploy:** variaveis `POSTGRESQL_*` devem referenciar o servico `Postgres` (fundo cinza)
5. No PgBouncer: `PGBOUNCER_POOL_MODE=transaction`
6. **Deploy Template**
7. Servico **PgBouncer** → **Settings** → **Networking** → habilite **TCP Proxy publico**
8. Rode o cutover:

```powershell
powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase4_pgbouncer.ps1 -WaitForPooling
powershell -ExecutionPolicy Bypass -File ferramentas\consolidacao_db\fase4_pgbouncer.ps1 -Cutover -Redeploy
```

| URL | Origem |
|-----|--------|
| Pooled (apps) | `DATABASE_PUBLIC_URL` do servico **PgBouncer** |
| Unpooled (migrations) | `DATABASE_PUBLIC_URL` do servico **Postgres** (inalterado) |

### Alternativa futura: pooling nativo

Se migrar para o Postgres gerenciado novo do Railway, o menu Connection Pooling
gera `DATABASE_PUBLIC_UNPOOLED_URL` automaticamente. O script `fase4_pgbouncer.ps1`
detecta os dois modos.

## Arquivos

| Arquivo | Função |
|---------|--------|
| `00_criar_schemas.sql` | DDL schemas + grants |
| `criar_schemas.py` | Executa SQL via Django no central |
| `inventario_banco.py` | Inventário tabelas/linhas → JSON |
| `gerar_baselines.py` | Regenera SQL via `prisma migrate diff` |
| `deploy_baseline.py` | Aplica baseline no central (SyncWA) |
| `migrar_schema_pg.py` | pg_dump schema/dados public → sysr/syncwa |
| `registrar_prisma_migrations.py` | Marca baseline como aplicada no Prisma |
| `smoke_test_fase1.py` | Valida contagens origem vs destino |
| `fase0.ps1` | Orquestra Fase 0 |
| `fix_prisma_migrations_cutover.py` | Marca migrations SyncWA como aplicadas |
| `copiar_prisma_migrations_sysr.py` | Copia historico Prisma Evolution/sysr |
| `fase2.ps1` | Orquestra Fase 2 (cutover) |
| `fase3.ps1` | Orquestra Fase 3 (desligar Postgres isolados) |
| `fase4_pgbouncer.ps1` | Cutover PgBouncer nativo Railway |
| `pgbouncer_urls.py` | Monta URLs pooled/unpooled por schema |
| `smoke_test_pgbouncer.py` | Valida conexao pooled + unpooled |
| `patch_prisma_schemas.py` | Aplica `@@schema` nos Prisma externos |

## Fora do escopo

- Redis do SyncWA (permanece isolado)
- Postgres n8n/Evolution no projeto sysr-vendas-api
