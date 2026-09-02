#!/usr/bin/env python
"""Executa importação completa FPD + OSAB (Portal Parceiros) no ambiente local."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Evita UnicodeEncodeError no console Windows (prints com emoji em views.py)
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core_config.settings')
os.environ.setdefault('SECRET_KEY', 'local-dev-test-portal-parceiros-import')
os.environ.setdefault('DEBUG', 'True')

import django

django.setup()

from django.contrib.auth import get_user_model
from django.db import connection

from crm_app.models import ImportacaoFPD, ImportacaoOsab, LogImportacaoFPD, LogImportacaoOSAB
from crm_app.views import ImportacaoOsabView, ImportarFPDView

FPD_PATH = Path(r'c:\Users\rogge\Downloads\FPD_PORTAL PARCEIROS.xlsx')
OSAB_PATH = Path(r'c:\Users\rogge\Downloads\OSAB_PORTAL PARCEIROS.xlsx')


def patch_sqlite_statement_timeout() -> None:
    """Ignora SET LOCAL statement_timeout (PostgreSQL) ao rodar em SQLite local."""
    if connection.vendor != 'sqlite':
        return

    original_cursor = connection.cursor

    def cursor_wrapper(*args, **kwargs):
        cursor = original_cursor(*args, **kwargs)
        original_execute = cursor.execute

        def execute(sql, params=None):
            if isinstance(sql, str) and 'statement_timeout' in sql.lower():
                return None
            return original_execute(sql, params)

        cursor.execute = execute
        return cursor

    connection.cursor = cursor_wrapper


def ensure_user():
    User = get_user_model()
    user = User.objects.filter(is_superuser=True).first()
    if user:
        return user
    return User.objects.create_superuser(
        username='import_test',
        email='import_test@local.dev',
        password='import_test_local_only',
    )


def run_fpd(user) -> LogImportacaoFPD:
    if not FPD_PATH.is_file():
        raise FileNotFoundError(FPD_PATH)

    content = FPD_PATH.read_bytes()
    log = LogImportacaoFPD.objects.create(
        nome_arquivo=FPD_PATH.name,
        tamanho_arquivo=len(content),
        usuario=user,
        status='PROCESSANDO',
    )
    print(f'\n[FPD] Log #{log.id} — iniciando ({len(content):,} bytes)...')
    t0 = time.time()
    ImportarFPDView()._processar_fpd_interno(log.id, content, FPD_PATH.name, user.id)
    log.refresh_from_db()
    elapsed = time.time() - t0
    print(
        f'[FPD] Status={log.status} | linhas={log.total_linhas} | '
        f'sucesso={log.sucesso} | erros={log.erros} | '
        f'nao_encontrados={log.total_contratos_nao_encontrados} | '
        f'{elapsed:.1f}s'
    )
    if log.mensagem:
        print(f'[FPD] Mensagem: {log.mensagem[:300]}')
    if log.mensagem_erro:
        print(f'[FPD] Erro: {log.mensagem_erro[:500]}')
    return log


def run_osab(user) -> LogImportacaoOSAB:
    if not OSAB_PATH.is_file():
        raise FileNotFoundError(OSAB_PATH)

    content = OSAB_PATH.read_bytes()
    log = LogImportacaoOSAB.objects.create(
        nome_arquivo=OSAB_PATH.name,
        tamanho_arquivo=len(content),
        usuario=user,
        status='PROCESSANDO',
        enviar_whatsapp=False,
    )
    print(f'\n[OSAB] Log #{log.id} — iniciando ({len(content):,} bytes)...')
    t0 = time.time()
    ImportacaoOsabView()._processar_osab_interno(log.id, content, OSAB_PATH.name, False)
    log.refresh_from_db()
    elapsed = time.time() - t0
    print(
        f'[OSAB] Status={log.status} | total={log.total_registros} | '
        f'criados={log.criados} | atualizados={log.atualizados} | '
        f'vendas_encontradas={log.vendas_encontradas} | '
        f'{elapsed:.1f}s'
    )
    if log.mensagem:
        print(f'[OSAB] Mensagem: {log.mensagem[:300]}')
    if log.mensagem_erro:
        print(f'[OSAB] Erro: {log.mensagem_erro[:500]}')
    return log


def main() -> int:
    patch_sqlite_statement_timeout()
    user = ensure_user()
    print(f'Usuário de teste: {user.username} (id={user.id})')
    print(f'Banco: {connection.vendor}')

    before_fpd = ImportacaoFPD.objects.count()
    before_osab = ImportacaoOsab.objects.count()

    fpd_log = run_fpd(user)
    osab_log = run_osab(user)

    after_fpd = ImportacaoFPD.objects.count()
    after_osab = ImportacaoOsab.objects.count()

    print('\n=== RESUMO ===')
    print(f'ImportacaoFPD: {before_fpd} -> {after_fpd} (+{after_fpd - before_fpd})')
    print(f'ImportacaoOsab: {before_osab} -> {after_osab} (+{after_osab - before_osab})')
    print(f'Logs: FPD #{fpd_log.id} ({fpd_log.status}) | OSAB #{osab_log.id} ({osab_log.status})')

    ok = fpd_log.status in ('SUCESSO', 'PARCIAL') and osab_log.status in ('SUCESSO', 'PARCIAL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
