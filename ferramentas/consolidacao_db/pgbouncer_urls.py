"""Helpers para montar URLs pooled/unpooled no cutover PgBouncer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gestao_equipes.database import (  # noqa: E402
    build_django_pooled_url,
    build_prisma_urls,
    normalize_postgres_url,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera URLs pooled/unpooled para cutover PgBouncer")
    parser.add_argument("--pooled-public", required=True, help="DATABASE_PUBLIC_URL (PgBouncer)")
    parser.add_argument("--unpooled-public", required=True, help="DATABASE_PUBLIC_UNPOOLED_URL")
    parser.add_argument("--schema", choices=("public", "sysr", "syncwa"), default="public")
    args = parser.parse_args()

    pooled = args.pooled_public
    unpooled = args.unpooled_public

    if args.schema == "public":
        django_runtime = build_django_pooled_url(pooled)
        django_unpooled = normalize_postgres_url(unpooled)
        prisma = None
    else:
        prisma = build_prisma_urls(pooled, unpooled, args.schema)
        django_runtime = None
        django_unpooled = None

    out = {
        "schema": args.schema,
        "django": {
            "DATABASE_URL": django_runtime,
            "DATABASE_UNPOOLED_URL": django_unpooled,
        },
        "prisma": prisma,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
