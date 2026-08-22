"""
Serviço de registro de presença: criação/atualização atômica do registro
colaborador+data com tratamento de race condition (IntegrityError).

Centraliza a regra de negócio: um único registro por (colaborador, data);
na primeira criação define lancado_por, em atualizações define editado_por.
Em caso de IntegrityError (chave duplicada por concorrência), tenta recuperar
o registro existente e atualizar em vez de falhar para o usuário.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.db import IntegrityError, transaction

from presenca.models import Presenca

logger = logging.getLogger(__name__)


class PresencaServiceError(Exception):
    """Erro de validação ou regra do serviço de presença."""

    pass


def registrar_presenca(
    colaborador_id: int,
    data_registro: Any,
    status: bool = True,
    motivo_id: Optional[int] = None,
    observacao: str = "",
    usuario: Any = None,
) -> tuple[Presenca, bool]:
    """
    Cria ou atualiza o registro de presença para (colaborador, data).
    Em criação define lancado_por; em atualização define editado_por.
    Em IntegrityError (duplicate key), tenta buscar o registro existente e
    atualizar para não falhar em cenários de requisições simultâneas.

    Returns:
        Tupla (instância Presenca, created: bool).

    Raises:
        PresencaServiceError: Quando colaborador_id ou data_registro estão ausentes.
    """
    if not colaborador_id or not data_registro:
        raise PresencaServiceError("Colaborador e data são obrigatórios.")

    try:
        with transaction.atomic():
            obj, created = Presenca.objects.update_or_create(
                colaborador_id=colaborador_id,
                data=data_registro,
                defaults={
                    "status": status,
                    "motivo_id": motivo_id,
                    "observacao": observacao or "",
                    "editado_por": usuario,
                },
            )
            if created:
                obj.lancado_por = usuario
                obj.editado_por = None
                obj.save(update_fields=["lancado_por", "editado_por"])
            obj.refresh_from_db()
            return obj, created

    except IntegrityError as e:
        error_str = str(e)
        logger.debug("Presenca IntegrityError: %s", error_str)
        if "duplicar valor da chave" in error_str or "duplicate key" in error_str.lower():
            try:
                obj = Presenca.objects.get(
                    colaborador_id=colaborador_id,
                    data=data_registro,
                )
                obj.status = status
                obj.motivo_id = motivo_id
                obj.observacao = observacao or ""
                obj.editado_por = usuario
                obj.save(update_fields=["status", "motivo_id", "observacao", "editado_por", "editado_em"])
                obj.refresh_from_db()
                return obj, False
            except Presenca.DoesNotExist:
                pass
        raise PresencaServiceError(
            "Erro de integridade: Já existe um registro para este colaborador nesta data."
        )
