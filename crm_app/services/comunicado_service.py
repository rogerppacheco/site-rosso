"""Regras de negócio para envio de comunicados (Record Informa)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Iterable

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from crm_app.models import Comunicado, GrupoDisparo
from crm_app.performance_helpers import calcular_pct_representatividade
from crm_app.whatsapp_service import WhatsAppService

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

logger = logging.getLogger(__name__)

User = get_user_model()

USUARIOS_SISTEMA_EXCLUIDOS = ['OSAB_IMPORT', 'admin', 'root']

PERFIL_FILTRO_Q = {
    'VENDEDOR': Q(perfil__nome__icontains='vendedor') | Q(perfil__cod_perfil__iexact='vendedor'),
    'SUPERVISOR': Q(perfil__nome__icontains='supervisor') | Q(perfil__cod_perfil__iexact='supervisor'),
    'BACKOFFICE': Q(perfil__nome__icontains='backoffice') | Q(perfil__cod_perfil__iexact='backoffice'),
    'DIRETORIA': Q(perfil__nome__icontains='diretoria') | Q(perfil__cod_perfil__iexact='diretoria'),
}

PERFIL_GRUPO_TERMOS = {
    'DIRETORIA': ['Diretoria', 'diretor'],
    'BACKOFFICE': ['BackOffice', 'Back Office', 'backoffice'],
    'SUPERVISOR': ['Supervisor', 'supervisor'],
    'VENDEDOR': ['Vendedor', 'vendedor'],
}


def _filtro_vendas_mes_referencia() -> Q:
    """Mesma base do painel de performance: O.S. cadastrada, ativa, sem reemissão."""
    return (
        Q(vendas__ativo=True)
        & ~Q(vendas__ordem_servico='')
        & Q(vendas__ordem_servico__isnull=False)
        & Q(vendas__status_tratamento__nome__iexact='CADASTRADA')
        & Q(vendas__reemissao=False)
    )


def comunicado_usa_envio_individual(comunicado: Comunicado) -> bool:
    """Envio direto ao WhatsApp do usuário quando há filtros granulares ou perfil Vendedor."""
    if comunicado.perfil_destino == 'VENDEDOR':
        return True
    if comunicado.vendedor_id:
        return True
    if comunicado.canal_alvo and comunicado.canal_alvo != 'TODOS':
        return True
    cluster = (comunicado.cluster_alvo or '').strip()
    if cluster and cluster.upper() != 'TODOS':
        return True
    if (comunicado.status_destinatarios or 'somente_ativos') != 'somente_ativos':
        return True
    if (comunicado.representatividade_minima or 0) > 0:
        return True
    return False


def _aplicar_filtro_status(qs: QuerySet, status_destinatarios: str) -> QuerySet:
    status = (status_destinatarios or 'somente_ativos').strip().lower()
    if status == 'somente_ativos':
        return qs.filter(is_active=True)
    if status == 'somente_inativos':
        return qs.filter(is_active=False)
    return qs


def _aplicar_filtro_perfil(qs: QuerySet, perfil_destino: str) -> QuerySet:
    if perfil_destino == 'TODOS':
        return qs
    filtro_perfil = PERFIL_FILTRO_Q.get(perfil_destino)
    if filtro_perfil:
        return qs.filter(filtro_perfil)
    return qs


def _aplicar_filtro_representatividade(
    usuarios: Iterable[AbstractUser],
    representatividade_minima: int,
    referencia: date | None = None,
) -> list[AbstractUser]:
    min_rep = int(representatividade_minima or 0)
    if min_rep <= 0:
        return list(usuarios)

    hoje = referencia or timezone.localdate()
    inicio_mes = hoje.replace(day=1)
    filtro_mes = _filtro_vendas_mes_referencia() & Q(
        vendas__data_abertura__date__gte=inicio_mes,
        vendas__data_abertura__date__lte=hoje,
    )
    ids = [u.id for u in usuarios]
    if not ids:
        return []

    volumes = (
        User.objects.filter(id__in=ids)
        .annotate(volume_mes=Count('vendas', filter=filtro_mes))
        .values('id', 'volume_mes')
    )
    total_geral = sum(int(v['volume_mes'] or 0) for v in volumes)
    elegiveis_ids = {
        v['id']
        for v in volumes
        if calcular_pct_representatividade(v['volume_mes'] or 0, total_geral) >= min_rep
    }
    return [u for u in usuarios if u.id in elegiveis_ids]


def resolver_destinatarios_individuais(comunicado: Comunicado) -> list[AbstractUser]:
    """Retorna usuários elegíveis para envio individual conforme filtros do comunicado."""
    if comunicado.vendedor_id:
        vendedor = (
            User.objects.filter(pk=comunicado.vendedor_id)
            .select_related('perfil')
            .first()
        )
        return [vendedor] if vendedor and vendedor.tel_whatsapp else []

    qs = (
        User.objects.exclude(username__in=USUARIOS_SISTEMA_EXCLUIDOS)
        .exclude(tel_whatsapp__isnull=True)
        .exclude(tel_whatsapp='')
        .select_related('perfil')
    )
    qs = _aplicar_filtro_status(qs, comunicado.status_destinatarios)
    qs = _aplicar_filtro_perfil(qs, comunicado.perfil_destino)

    canal = (comunicado.canal_alvo or 'TODOS').strip()
    if canal and canal.upper() != 'TODOS':
        qs = qs.filter(canal__iexact=canal)

    cluster = (comunicado.cluster_alvo or '').strip()
    if cluster and cluster.upper() != 'TODOS':
        qs = qs.filter(cluster__iexact=cluster)

    usuarios = list(qs.order_by('username'))
    return _aplicar_filtro_representatividade(usuarios, comunicado.representatividade_minima)


def resolver_grupos_whatsapp(comunicado: Comunicado) -> list[str]:
    """Retorna chat_ids de grupos ativos conforme perfil (envio legado por grupo)."""
    if comunicado.perfil_destino == 'TODOS':
        grupos_ativos = GrupoDisparo.objects.filter(ativo=True)
    else:
        termos = PERFIL_GRUPO_TERMOS.get(comunicado.perfil_destino, [comunicado.perfil_destino])
        filtro_nome = Q()
        for termo in termos:
            filtro_nome |= Q(nome__icontains=termo)
        grupos_ativos = GrupoDisparo.objects.filter(Q(ativo=True) & filtro_nome)
    return list(grupos_ativos.values_list('chat_id', flat=True))


def comunicado_deve_enviar_agora(comunicado: Comunicado, agora: datetime | None = None) -> bool:
    """Verifica se data/hora programada já passou ou é agora."""
    referencia = agora or timezone.now()
    hora_envio = comunicado.hora_programada
    if isinstance(hora_envio, time):
        datetime_envio = datetime.combine(comunicado.data_programada, hora_envio)
        if timezone.is_naive(datetime_envio):
            datetime_envio = timezone.make_aware(datetime_envio)
    else:
        datetime_envio = referencia
    return datetime_envio <= referencia


def processar_envio_comunicado(comunicado: Comunicado) -> bool:
    """
    Processa e envia um comunicado via WhatsApp.
    Usa envio individual (tel_whatsapp) quando há filtros granulares; caso contrário, grupos.
    """
    try:
        if not comunicado_deve_enviar_agora(comunicado):
            return False

        whatsapp_service = WhatsAppService()
        mensagem = comunicado.mensagem or ''
        sucesso_total = True
        destinos_enviados = 0

        if comunicado_usa_envio_individual(comunicado):
            destinatarios = resolver_destinatarios_individuais(comunicado)
            if not destinatarios:
                logger.warning(
                    "Nenhum destinatário individual encontrado para comunicado %s",
                    comunicado.id,
                )
                comunicado.status = 'ERRO'
                comunicado.save(update_fields=['status'])
                return False

            for usuario in destinatarios:
                telefone = (usuario.tel_whatsapp or '').strip()
                if not telefone:
                    continue
                try:
                    resultado, _ = whatsapp_service.enviar_mensagem_texto(
                        telefone, mensagem, variar=False
                    )
                    destinos_enviados += 1
                    if not resultado:
                        sucesso_total = False
                        logger.error(
                            "Erro ao enviar comunicado %s para %s",
                            comunicado.id,
                            usuario.username,
                        )
                except Exception as exc:
                    sucesso_total = False
                    logger.error(
                        "Exceção ao enviar comunicado %s para %s: %s",
                        comunicado.id,
                        usuario.username,
                        exc,
                    )
        else:
            grupos_ids = resolver_grupos_whatsapp(comunicado)
            if not grupos_ids:
                logger.warning(
                    "Nenhum grupo encontrado para perfil %s (comunicado %s)",
                    comunicado.perfil_destino,
                    comunicado.id,
                )
                comunicado.status = 'ERRO'
                comunicado.save(update_fields=['status'])
                return False

            for grupo_id in grupos_ids:
                try:
                    resultado, _ = whatsapp_service.enviar_mensagem_texto(
                        grupo_id, mensagem, variar=False
                    )
                    destinos_enviados += 1
                    if not resultado:
                        sucesso_total = False
                        logger.error(
                            "Erro ao enviar comunicado %s para grupo %s",
                            comunicado.id,
                            grupo_id,
                        )
                except Exception as exc:
                    sucesso_total = False
                    logger.error(
                        "Exceção ao enviar comunicado %s para grupo %s: %s",
                        comunicado.id,
                        grupo_id,
                        exc,
                    )

        if destinos_enviados == 0:
            comunicado.status = 'ERRO'
            comunicado.save(update_fields=['status'])
            return False

        comunicado.status = 'ENVIADO' if sucesso_total else 'ERRO'
        comunicado.save(update_fields=['status'])
        return sucesso_total

    except Exception as exc:
        logger.error("Erro ao processar comunicado %s: %s", comunicado.id, exc)
        comunicado.status = 'ERRO'
        comunicado.save(update_fields=['status'])
        return False
