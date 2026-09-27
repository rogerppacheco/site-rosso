"""Escopo central de visibilidade e escrita por operadora."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from django.db.models import Q, QuerySet


def usuario_tem_bypass_operadora(usuario: object) -> bool:
    """Admin e superusuário enxergam tudo, inclusive registros sem operadora."""
    if not getattr(usuario, 'is_authenticated', False):
        return False
    if getattr(usuario, 'is_superuser', False):
        return True

    perfil = getattr(usuario, 'perfil', None)
    perfil_nome = (getattr(perfil, 'nome', '') or '').strip().casefold()
    if perfil_nome == 'admin':
        return True

    groups = getattr(usuario, 'groups', None)
    return bool(groups and groups.filter(name__iexact='Admin').exists())


def operadora_ids_permitidas(usuario: object) -> Optional[frozenset[int]]:
    """
    Retorna os IDs permitidos ou ``None`` quando o usuário pode ver todas.

    Campo vazio significa todas as operadoras cadastradas. Isso não libera
    registros sem operadora; somente Admin possui esse bypass.
    """
    if usuario_tem_bypass_operadora(usuario):
        return None
    if not getattr(usuario, 'is_authenticated', False):
        return frozenset()

    cache_attr = '_operadora_ids_permitidas_cache'
    if hasattr(usuario, cache_attr):
        return getattr(usuario, cache_attr)

    manager = getattr(usuario, 'operadoras_permitidas', None)
    ids = frozenset(manager.values_list('id', flat=True)) if manager else frozenset()
    resultado: Optional[frozenset[int]] = ids or None
    setattr(usuario, cache_attr, resultado)
    return resultado


def usuario_pode_acessar_operadora(usuario: object, operadora_id: Optional[int]) -> bool:
    """Valida acesso a uma operadora concreta para leitura ou escrita."""
    if usuario_tem_bypass_operadora(usuario):
        return True
    if not operadora_id:
        return False
    permitidas = operadora_ids_permitidas(usuario)
    return permitidas is None or int(operadora_id) in permitidas


def filtrar_planos_por_operadora(
    queryset: QuerySet,
    usuario: object,
    *,
    campo_operadora: str = 'operadora_id',
) -> QuerySet:
    """Filtra models que possuem vínculo direto com Operadora."""
    if usuario_tem_bypass_operadora(usuario):
        return queryset
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return queryset
    return queryset.filter(**{f'{campo_operadora}__in': permitidas})


def filtrar_vendas_por_operadora(
    queryset: QuerySet,
    usuario: object,
    *,
    campo_plano: str = 'plano',
) -> QuerySet:
    """
    Filtra Venda ou models que chegam a ela por um prefixo.

    Exemplos de ``campo_plano``: ``plano``, ``venda__plano`` e
    ``contrato__venda__plano``.
    """
    return queryset.filter(q_vendas_por_operadora(usuario, campo_plano=campo_plano))


def q_vendas_por_operadora(
    usuario: object,
    *,
    campo_plano: str = 'plano',
) -> Q:
    """Retorna o predicado de operadora para filtros e agregações."""
    if usuario_tem_bypass_operadora(usuario):
        return Q()
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return Q(**{f'{campo_plano}__operadora__isnull': False})
    return Q(**{f'{campo_plano}__operadora_id__in': permitidas})


def filtrar_clientes_por_operadora(queryset: QuerySet, usuario: object) -> QuerySet:
    """Mantém clientes com ao menos uma venda visível ao usuário."""
    if usuario_tem_bypass_operadora(usuario):
        return queryset
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return queryset.filter(
            vendas__plano__operadora__isnull=False,
        ).distinct()
    return queryset.filter(
        vendas__plano__operadora_id__in=permitidas,
    ).distinct()


def filtrar_campanhas_por_operadora(queryset: QuerySet, usuario: object) -> QuerySet:
    """Campanhas sem planos são globais; as demais exigem plano visível."""
    if usuario_tem_bypass_operadora(usuario):
        return queryset
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return queryset
    return queryset.filter(
        Q(planos_elegiveis__isnull=True)
        | Q(planos_elegiveis__operadora_id__in=permitidas)
    ).distinct()


def limitar_ids_operadora(
    ids_solicitados: Iterable[int],
    usuario: object,
) -> frozenset[int]:
    """Cruza uma seleção explícita com o escopo permitido."""
    solicitados = frozenset(int(item) for item in ids_solicitados)
    permitidas = operadora_ids_permitidas(usuario)
    if usuario_tem_bypass_operadora(usuario) or permitidas is None:
        return solicitados
    return solicitados & permitidas


def validar_plano_para_usuario(
    usuario: object,
    plano: object | None,
    *,
    exigir_plano: bool = True,
) -> str | None:
    """
    Valida se o usuário pode usar o plano informado na escrita.

    Retorna ``None`` quando permitido, ou mensagem de erro em português.
    Usuários sem bypass precisam de plano com operadora no escopo; Admin
    pode gravar sem plano (registros legados / casos especiais).
    """
    if usuario_tem_bypass_operadora(usuario):
        return None
    if plano is None:
        if exigir_plano:
            return 'Selecione um plano de uma operadora permitida.'
        return None
    operadora_id = getattr(plano, 'operadora_id', None)
    if not usuario_pode_acessar_operadora(usuario, operadora_id):
        return 'Você não possui acesso à operadora deste plano.'
    return None


def assert_plano_permitido(
    usuario: object,
    plano: object | None,
    *,
    exigir_plano: bool = True,
) -> None:
    """Levanta ``PermissionError`` se o plano estiver fora do escopo."""
    erro = validar_plano_para_usuario(
        usuario,
        plano,
        exigir_plano=exigir_plano,
    )
    if erro:
        raise PermissionError(erro)
