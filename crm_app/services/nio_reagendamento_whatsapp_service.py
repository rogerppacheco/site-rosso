"""Reagendamento automático via bot WhatsApp Nio (7029) — esteira."""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

CODIGO_MOTIVO_7029 = '7029'
_job_lock = threading.Lock()


def _cfg(nome: str, default):
    return getattr(settings, nome, default)


def _run_django_sync(func, timeout_seconds: int = 120):
    import queue

    import django.db

    q = queue.Queue()

    def worker():
        try:
            django.db.close_old_connections()
            q.put(('ok', func()))
        except Exception as e:
            q.put(('err', e))
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=worker, daemon=True, name='nio-reagendamento-orm')
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        kind, payload = q.get()
        if kind == 'err':
            raise payload
        return payload
    raise TimeoutError('django_sync_timeout')


def extrair_codigo_motivo(nome_motivo: str) -> str:
    m = re.match(r'^(\d+)', (nome_motivo or '').strip())
    return m.group(1) if m else ''


def venda_elegivel_nio_reagendamento(venda) -> Tuple[bool, str]:
    """7029 CLIENTE pendenciada com CPF."""
    if not venda or not getattr(venda, 'ativo', True):
        return False, 'Venda inativa.'
    st = (venda.status_esteira.nome or '').upper() if venda.status_esteira else ''
    if 'PENDEN' not in st:
        return False, 'Status não é pendenciada.'
    if not venda.motivo_pendencia:
        return False, 'Sem motivo de pendência.'
    codigo = extrair_codigo_motivo(venda.motivo_pendencia.nome)
    if codigo != CODIGO_MOTIVO_7029:
        return False, 'Motivo não é 7029.'
    tipo = (venda.motivo_pendencia.tipo_pendencia or '').upper()
    if 'CLIENTE' not in tipo:
        return False, 'Tipo não é CLIENTE.'
    if not venda.cliente or not venda.cliente.cpf_cnpj:
        return False, 'Cliente sem CPF.'
    cpf = re.sub(r'\D', '', venda.cliente.cpf_cnpj)
    if len(cpf) != 11:
        return False, 'CPF inválido.'
    return True, ''


def queryset_vendas_elegiveis_nio(filtros: Optional[Dict[str, Any]] = None):
    """Pedidos 7029 CLIENTE da aba/filtros atuais."""
    from crm_app.esteira_consulta_status_pap_service import queryset_vendas_consulta_aba

    qs = queryset_vendas_consulta_aba(filtros or {'aba': 'PENDEN'})
    return qs.filter(
        motivo_pendencia__isnull=False,
        motivo_pendencia__nome__startswith=CODIGO_MOTIVO_7029,
        motivo_pendencia__tipo_pendencia__icontains='CLIENTE',
    ).select_related('cliente', 'motivo_pendencia', 'status_esteira')


def execucao_em_andamento():
    from crm_app.models import NioReagendamentoExecucao

    encerrar_execucoes_orfas()
    return (
        NioReagendamentoExecucao.objects.filter(
            status=NioReagendamentoExecucao.STATUS_EM_ANDAMENTO
        )
        .order_by('-iniciado_em')
        .first()
    )


def encerrar_execucoes_orfas(*, stale_minutos: int = 45) -> int:
    from crm_app.models import NioReagendamentoExecucao

    limite = timezone.now() - timezone.timedelta(minutes=stale_minutos)
    orfas = NioReagendamentoExecucao.objects.filter(
        status=NioReagendamentoExecucao.STATUS_EM_ANDAMENTO,
        iniciado_em__lt=limite,
    )
    n = orfas.update(
        status=NioReagendamentoExecucao.STATUS_ERRO,
        mensagem_erro='Execução expirou (sem progresso).',
        finalizado_em=timezone.now(),
    )
    return n


def _periodo_de_horario(inicio_hhmm: str) -> str:
    try:
        hora = int((inicio_hhmm or '08:00').split(':')[0])
        return 'MANHA' if hora < 13 else 'TARDE'
    except (ValueError, IndexError):
        return 'MANHA'


def _aplicar_sucesso_venda(venda, dados: dict, *, usuario=None) -> None:
    from crm_app.models import HistoricoAlteracaoVenda, Venda

    data_str = dados.get('data') or ''
    try:
        data_ag = datetime.strptime(data_str, '%d/%m/%Y').date()
    except ValueError:
        data_ag = None
    periodo = _periodo_de_horario(dados.get('inicio') or '')
    alteracoes: dict = {}
    if data_ag and venda.data_agendamento != data_ag:
        alteracoes['data_agendamento'] = {
            'de': str(venda.data_agendamento) if venda.data_agendamento else None,
            'para': str(data_ag),
        }
        venda.data_agendamento = data_ag
    if periodo and venda.periodo_agendamento != periodo:
        alteracoes['periodo_agendamento'] = {
            'de': venda.periodo_agendamento,
            'para': periodo,
        }
        venda.periodo_agendamento = periodo
    msg = (
        f"Agendado Nio: {data_str} {dados.get('inicio')}–{dados.get('fim')} "
        f"— {dados.get('endereco', '')[:120]}"
    )
    venda.nio_reagendamento_status = 'sucesso'
    venda.nio_reagendamento_em = timezone.now()
    venda.nio_reagendamento_msg = msg[:500]
    campos = [
        'data_agendamento',
        'periodo_agendamento',
        'nio_reagendamento_status',
        'nio_reagendamento_em',
        'nio_reagendamento_msg',
    ]
    venda.save(update_fields=campos)
    if alteracoes and usuario:
        HistoricoAlteracaoVenda.objects.create(
            venda=venda,
            usuario=usuario,
            alteracoes=alteracoes,
        )


def _marcar_falha_venda(venda, status: str, mensagem: str) -> None:
    venda.nio_reagendamento_status = status
    venda.nio_reagendamento_em = timezone.now()
    venda.nio_reagendamento_msg = (mensagem or '')[:500]
    venda.save(update_fields=['nio_reagendamento_status', 'nio_reagendamento_em', 'nio_reagendamento_msg'])


def _pausa_entre_pedidos() -> None:
    lo = int(_cfg('NIO_REAGENDAMENTO_INTERVALO_MIN_SEG', 30))
    hi = int(_cfg('NIO_REAGENDAMENTO_INTERVALO_MAX_SEG', 60))
    seg = random.randint(lo, max(lo + 1, hi))
    logger.info('[NIO REAGENDAMENTO] Pausa %ss antes do próximo pedido.', seg)
    time.sleep(seg)


def criar_e_iniciar_unitario(*, venda_id: int, usuario=None) -> Tuple[Optional[int], Optional[str]]:
    from crm_app.models import NioReagendamentoExecucao, NioReagendamentoItem, Venda

    if not _cfg('NIO_REAGENDAMENTO_ENABLED', False):
        return None, 'Reagendamento Nio desabilitado (NIO_REAGENDAMENTO_ENABLED).'

    if execucao_em_andamento():
        return None, 'Já existe um reagendamento Nio em andamento.'

    try:
        venda = Venda.objects.select_related('cliente', 'motivo_pendencia', 'status_esteira').get(
            pk=venda_id, ativo=True
        )
    except Venda.DoesNotExist:
        return None, 'Venda não encontrada.'

    ok, motivo = venda_elegivel_nio_reagendamento(venda)
    if not ok:
        return None, motivo

    execucao = NioReagendamentoExecucao.objects.create(
        modo=NioReagendamentoExecucao.MODO_UNITARIO,
        status=NioReagendamentoExecucao.STATUS_PENDENTE,
        iniciado_por=usuario,
        total_pedidos=1,
    )
    NioReagendamentoItem.objects.create(execucao=execucao, venda=venda)
    _iniciar_thread(execucao.id)
    return execucao.id, None


def criar_e_iniciar_massa(*, filtros: Dict[str, Any], usuario=None) -> Tuple[Optional[int], Optional[str], int]:
    from crm_app.models import NioReagendamentoExecucao, NioReagendamentoItem

    if not _cfg('NIO_REAGENDAMENTO_ENABLED', False):
        return None, 'Reagendamento Nio desabilitado (NIO_REAGENDAMENTO_ENABLED).', 0

    if execucao_em_andamento():
        return None, 'Já existe um reagendamento Nio em andamento.', 0

    vendas = list(queryset_vendas_elegiveis_nio(filtros))
    if not vendas:
        return None, 'Nenhum pedido 7029 CLIENTE elegível na aba/filtros atuais.', 0

    execucao = NioReagendamentoExecucao.objects.create(
        modo=NioReagendamentoExecucao.MODO_MASSA,
        status=NioReagendamentoExecucao.STATUS_PENDENTE,
        iniciado_por=usuario,
        total_pedidos=len(vendas),
        relatorio_json={'filtros': filtros},
    )
    NioReagendamentoItem.objects.bulk_create([
        NioReagendamentoItem(execucao=execucao, venda=v) for v in vendas
    ])
    _iniciar_thread(execucao.id)
    return execucao.id, None, len(vendas)


def cancelar_execucao(execucao_id: int, *, usuario=None) -> Tuple[bool, str]:
    from crm_app.models import NioReagendamentoExecucao

    execucao = NioReagendamentoExecucao.objects.filter(pk=execucao_id).first()
    if not execucao:
        return False, 'Execução não encontrada.'
    if execucao.status not in (
        NioReagendamentoExecucao.STATUS_PENDENTE,
        NioReagendamentoExecucao.STATUS_EM_ANDAMENTO,
    ):
        return False, 'Execução já finalizada.'
    execucao.cancelar_solicitado = True
    execucao.save(update_fields=['cancelar_solicitado'])
    return True, 'Cancelamento solicitado.'


def _iniciar_thread(execucao_id: int) -> None:
    def _runner():
        import django.db

        django.db.close_old_connections()
        try:
            executar_job(execucao_id)
        except Exception as e:
            logger.exception('[NIO REAGENDAMENTO] Erro fatal execução #%s: %s', execucao_id, e)
            try:
                _run_django_sync(lambda: _marcar_execucao_erro(execucao_id, str(e)))
            except Exception:
                pass
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=_runner, name=f'nio-reagendamento-{execucao_id}', daemon=True)
    t.start()


def _marcar_execucao_erro(execucao_id: int, msg: str) -> None:
    from crm_app.models import NioReagendamentoExecucao

    NioReagendamentoExecucao.objects.filter(pk=execucao_id).update(
        status=NioReagendamentoExecucao.STATUS_ERRO,
        mensagem_erro=(msg or '')[:2000],
        finalizado_em=timezone.now(),
    )


def _carregar_job(execucao_id: int) -> Tuple[int, Optional[int], List[int]]:
    from crm_app.models import NioReagendamentoExecucao, NioReagendamentoItem

    execucao = NioReagendamentoExecucao.objects.select_related('iniciado_por').get(pk=execucao_id)
    execucao.status = NioReagendamentoExecucao.STATUS_EM_ANDAMENTO
    execucao.save(update_fields=['status'])
    item_ids = list(
        execucao.itens.filter(status=NioReagendamentoItem.STATUS_PENDENTE)
        .order_by('id')
        .values_list('id', flat=True)
    )
    return execucao.id, execucao.iniciado_por_id, item_ids


def _preparar_item_nio(item_id: int, execucao_id: int) -> dict:
    from crm_app.models import NioReagendamentoExecucao, NioReagendamentoItem

    execucao = NioReagendamentoExecucao.objects.get(pk=execucao_id)
    item = NioReagendamentoItem.objects.select_related(
        'venda', 'venda__cliente', 'venda__motivo_pendencia', 'venda__status_esteira'
    ).get(pk=item_id)
    if execucao.cancelar_solicitado:
        item.status = NioReagendamentoItem.STATUS_CANCELADO
        item.mensagem = 'Cancelado pelo usuário.'
        item.finalizado_em = timezone.now()
        item.save(update_fields=['status', 'mensagem', 'finalizado_em'])
        return {'acao': 'pular'}

    venda = item.venda
    ok_eleg, motivo_eleg = venda_elegivel_nio_reagendamento(venda)
    if not ok_eleg:
        item.status = NioReagendamentoItem.STATUS_ERRO
        item.mensagem = motivo_eleg
        item.finalizado_em = timezone.now()
        item.save(update_fields=['status', 'mensagem', 'finalizado_em'])
        _marcar_falha_venda(venda, 'erro', motivo_eleg)
        execucao.processados += 1
        execucao.falhas += 1
        execucao.save(update_fields=['processados', 'falhas'])
        return {'acao': 'pular'}

    item.status = NioReagendamentoItem.STATUS_EM_ANDAMENTO
    item.iniciado_em = timezone.now()
    item.save(update_fields=['status', 'iniciado_em'])
    cpf = re.sub(r'\D', '', venda.cliente.cpf_cnpj or '')
    nome = (venda.cliente.nome_razao_social or '')[:80]
    return {'acao': 'reagendar', 'cpf': cpf, 'nome': nome, 'venda_id': venda.id}


def _salvar_resultado_item_nio(
    item_id: int,
    execucao_id: int,
    usuario_id: Optional[int],
    resultado,
) -> None:
    from django.contrib.auth import get_user_model

    from crm_app.models import NioReagendamentoExecucao, NioReagendamentoItem

    execucao = NioReagendamentoExecucao.objects.get(pk=execucao_id)
    item = NioReagendamentoItem.objects.select_related('venda').get(pk=item_id)
    venda = item.venda
    usuario = get_user_model().objects.filter(pk=usuario_id).first() if usuario_id else None

    item.finalizado_em = timezone.now()
    item.dados_json = resultado.dados or {}
    item.mensagem = resultado.mensagem[:500]
    item.status = resultado.status
    item.save(update_fields=['status', 'mensagem', 'dados_json', 'finalizado_em'])

    if resultado.ok and resultado.dados:
        _aplicar_sucesso_venda(venda, resultado.dados, usuario=usuario)
        execucao.sucessos += 1
    else:
        _marcar_falha_venda(venda, resultado.status, resultado.mensagem)
        execucao.falhas += 1

    execucao.processados += 1
    execucao.save(update_fields=['processados', 'sucessos', 'falhas'])


def _finalizar_job_nio(execucao_id: int, *, erro: Optional[str] = None) -> bool:
    from crm_app.models import NioReagendamentoExecucao

    execucao = NioReagendamentoExecucao.objects.get(pk=execucao_id)
    execucao.finalizado_em = timezone.now()
    if erro:
        execucao.status = NioReagendamentoExecucao.STATUS_ERRO
        execucao.mensagem_erro = erro[:2000]
        execucao.save(update_fields=['status', 'mensagem_erro', 'finalizado_em'])
        return False
    execucao.refresh_from_db(fields=['cancelar_solicitado'])
    if execucao.cancelar_solicitado:
        execucao.status = NioReagendamentoExecucao.STATUS_INTERROMPIDO
    else:
        execucao.status = NioReagendamentoExecucao.STATUS_CONCLUIDO
    execucao.save(update_fields=['status', 'finalizado_em'])
    return True


def _job_foi_cancelado(execucao_id: int) -> bool:
    from crm_app.models import NioReagendamentoExecucao

    return bool(
        NioReagendamentoExecucao.objects.filter(
            pk=execucao_id, cancelar_solicitado=True
        ).exists()
    )


def executar_job(execucao_id: int) -> bool:
    from crm_app.services.whatsapp.nio_bot_web import NioWhatsAppSession

    with _job_lock:
        _execucao_id, usuario_id, item_ids = _carregar_job(execucao_id)

        try:
            with NioWhatsAppSession() as sessao:
                for idx, item_id in enumerate(item_ids):
                    estado = _run_django_sync(
                        lambda iid=item_id: _preparar_item_nio(iid, _execucao_id)
                    )
                    if estado.get('acao') != 'reagendar':
                        continue

                    resultado = sessao.reagendar(
                        cpf=estado['cpf'], nome_esperado=estado['nome']
                    )
                    _run_django_sync(
                        lambda iid=item_id, res=resultado: _salvar_resultado_item_nio(
                            iid, _execucao_id, usuario_id, res
                        )
                    )

                    if idx < len(item_ids) - 1:
                        if not _run_django_sync(lambda: _job_foi_cancelado(_execucao_id)):
                            _pausa_entre_pedidos()

        except Exception as e:
            logger.exception('[NIO REAGENDAMENTO] Falha sessão WhatsApp: %s', e)
            return _run_django_sync(lambda: _finalizar_job_nio(_execucao_id, erro=str(e)))

        return _run_django_sync(lambda: _finalizar_job_nio(_execucao_id))


def serializar_execucao(execucao, *, em_andamento: bool) -> dict:
    ultimo_item = execucao.itens.order_by('-id').select_related('venda').first()
    return {
        'em_andamento': em_andamento,
        'id': execucao.id,
        'modo': execucao.modo,
        'status': execucao.status,
        'iniciado_em': execucao.iniciado_em.isoformat() if execucao.iniciado_em else None,
        'finalizado_em': execucao.finalizado_em.isoformat() if execucao.finalizado_em else None,
        'total_pedidos': execucao.total_pedidos,
        'processados': execucao.processados,
        'sucessos': execucao.sucessos,
        'falhas': execucao.falhas,
        'mensagem_erro': execucao.mensagem_erro or '',
        'ultimo_venda_id': ultimo_item.venda_id if ultimo_item else None,
        'ultimo_status': ultimo_item.status if ultimo_item else '',
        'ultimo_mensagem': (ultimo_item.mensagem or '')[:200] if ultimo_item else '',
    }
