# -*- coding: utf-8 -*-
"""
Serviço de importação de arquivos ESTABELE da Receita Federal (CNPJ).
Layout oficial: 30 colunas, separador ;, sem cabeçalho.
Processamento em streaming para suportar arquivos grandes.
"""
import csv
import logging
import os
import time
from pathlib import Path
from typing import Optional

from django.db import transaction
from django.utils import timezone

from crm_app.models import ImportacaoEstabelecimentoCNPJ, LogImportacaoEstabelecimentoCNPJ

logger = logging.getLogger(__name__)

# Layout oficial ESTABELE - ordem das colunas (índice 0-based)
LAYOUT_ESTABELE = [
    "cnpj_raiz", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
    "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral", "motivo_situacao_cadastral",
    "nome_cidade_exterior", "codigo_pais", "data_inicio_atividade", "cnae_fiscal",
    "cnae_secundarios", "tipo_logradouro", "logradouro", "numero", "complemento",
    "bairro", "cep", "uf", "codigo_municipio", "ddd_telefone_1", "telefone_1",
    "ddd_telefone_2", "telefone_2", "ddd_fax", "fax", "email",
    "situacao_especial", "data_situacao_especial",
]

BATCH_SIZE = 5000  # Registros por bulk_create
MAX_FIELD_LENGTH = 255  # Truncar campos longos
# Atualizar log a cada N linhas (evita muitos UPDATEs em arquivos gigantes)
LOG_UPDATE_EVERY = 250_000


def _truncate(val: str, max_len: int = MAX_FIELD_LENGTH) -> str:
    """Trunca string para caber no campo."""
    if not val:
        return ""
    s = str(val).strip()
    return s[:max_len] if len(s) > max_len else s


def _parse_row(row: list) -> Optional[dict]:
    """Converte uma linha do CSV (lista de strings) em dict para o modelo."""
    if len(row) < 30:
        return None
    data = {}
    for i, key in enumerate(LAYOUT_ESTABELE):
        val = row[i].strip() if i < len(row) else ""
        if key == "cnae_secundarios":
            data[key] = _truncate(val, 2000)  # TextField
        elif key == "email":
            data[key] = _truncate(val, 254)
        else:
            data[key] = _truncate(val)

    # CNPJ completo
    raiz = data.get("cnpj_raiz", "") or ""
    ordem = data.get("cnpj_ordem", "") or ""
    dv = data.get("cnpj_dv", "") or ""
    data["cnpj_completo"] = (raiz + ordem + dv)[:14]

    return data


def _detect_encoding(path: Path) -> str:
    """Detecta encoding do arquivo."""
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            with open(path, "r", encoding=enc) as f:
                f.readline()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "latin-1"


def processar_arquivo_estabele(
    log_id: int,
    arquivo_path: str,
    aplicar_filtros: bool = False,
    cnae_fiscal: Optional[str] = None,
    codigo_municipio: Optional[str] = None,
    situacao_cadastral: Optional[str] = None,
) -> None:
    """
    Processa arquivo ESTABELE e importa para ImportacaoEstabelecimentoCNPJ.

    Args:
        log_id: ID do LogImportacaoEstabelecimentoCNPJ
        arquivo_path: Caminho do arquivo no disco
        aplicar_filtros: Se True, aplica filtros opcionais
        cnae_fiscal: Filtro CNAE (ex: 8112500)
        codigo_municipio: Filtro município (ex: 4123 para BH)
        situacao_cadastral: Filtro situação (ex: 02 para Ativa)
    """
    log = LogImportacaoEstabelecimentoCNPJ.objects.get(id=log_id)
    path = Path(arquivo_path)
    if not path.exists():
        log.status = "ERRO"
        log.mensagem_erro = f"Arquivo não encontrado: {arquivo_path}"
        log.finalizado_em = timezone.now()
        log.save()
        return

    encoding = _detect_encoding(path)
    total_linhas = 0
    total_importadas = 0
    total_erros = 0
    batch = []
    inicio = time.monotonic()

    try:
        with open(path, "r", encoding=encoding, newline="", errors="replace") as f:
            reader = csv.reader(f, delimiter=";")
            for row in reader:
                total_linhas += 1
                if total_linhas % LOG_UPDATE_EVERY == 0 or total_linhas == 1:
                    LogImportacaoEstabelecimentoCNPJ.objects.filter(id=log_id).update(
                        total_linhas=total_linhas,
                        total_importadas=total_importadas,
                        total_erros=total_erros,
                        mensagem=f"Processando... {total_linhas:,} linhas lidas",
                    )

                data = _parse_row(row)
                if not data:
                    total_erros += 1
                    continue

                if aplicar_filtros:
                    cnae = (data.get("cnae_fiscal") or "").zfill(7)
                    municipio = (data.get("codigo_municipio") or "").strip()
                    sit = (data.get("situacao_cadastral") or "").zfill(2)
                    if cnae_fiscal and cnae != cnae_fiscal:
                        continue
                    if codigo_municipio and municipio != codigo_municipio:
                        continue
                    if situacao_cadastral and sit != situacao_cadastral:
                        continue

                batch.append(ImportacaoEstabelecimentoCNPJ(**data))
                if len(batch) >= BATCH_SIZE:
                    with transaction.atomic():
                        ImportacaoEstabelecimentoCNPJ.objects.bulk_create(batch)
                    total_importadas += len(batch)
                    batch = []

        if batch:
            with transaction.atomic():
                ImportacaoEstabelecimentoCNPJ.objects.bulk_create(batch)
            total_importadas += len(batch)

        duracao = int(time.monotonic() - inicio)
        log.status = "SUCESSO"
        log.total_linhas = total_linhas
        log.total_importadas = total_importadas
        log.total_erros = total_erros
        log.finalizado_em = timezone.now()
        log.duracao_segundos = duracao
        log.mensagem = f"Importação concluída. {total_importadas:,} estabelecimentos importados de {total_linhas:,} linhas."
        log.save()
        logger.info(f"[CNPJ] Importação {log_id} concluída: {total_importadas} registros em {duracao}s")

    except Exception as e:
        logger.exception(f"[CNPJ] Erro na importação {log_id}")
        log.status = "ERRO"
        log.mensagem_erro = str(e)[:2000]
        log.finalizado_em = timezone.now()
        log.duracao_segundos = int(time.monotonic() - inicio)
        log.total_linhas = total_linhas
        log.total_importadas = total_importadas
        log.total_erros = total_erros
        log.save()
