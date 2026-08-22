"""
Sincronização noturna/manual da esteira (AGENDADO/PENDENCIADA) via consulta PAP (fluxo STATUS).
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple

from django.conf import settings
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

logger = logging.getLogger(__name__)

TELEFONE_JOB = 'SYNC-ESTEIRA-PAP'


def _run_django_sync(func, timeout_seconds: int = 120):
    """Executa ORM Django em thread dedicada (evita SynchronousOnlyOperation após Playwright)."""
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

    t = threading.Thread(target=worker, daemon=True, name='sync-esteira-orm')
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        kind, payload = q.get()
        if kind == 'err':
            raise payload
        return payload
    if t.is_alive():
        logger.error('[SYNC ESTEIRA] _run_django_sync expirou após %ss.', timeout_seconds)
        raise TimeoutError('django_sync_timeout')
    raise TimeoutError('django_sync_timeout')


def _aguardar_login_bo_safe(
    contador_uso_bo: Dict[int, int],
    *,
    timeout_seg: int = 900,
    intervalo_seg: int = 45,
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Aloca BO STATUS com ORM em thread limpa.

    O Playwright deixa event loop no thread do job; chamar aguardar_login_bo
    direto nesse thread após a 1ª consulta causa SynchronousOnlyOperation.
    """
    from crm_app.pool_bo_pap import (
        MSG_TODOS_ACESSOS_EM_USO,
        TIPO_AUTOMACAO_STATUS,
        obter_login_bo,
    )

    deadline = time.time() + max(30, timeout_seg)
    while time.time() < deadline:
        bo, err = _run_django_sync(
            lambda: obter_login_bo(
                TELEFONE_JOB,
                None,
                tipo_automacao=TIPO_AUTOMACAO_STATUS,
                contador_uso_por_bo=contador_uso_bo,
            ),
            timeout_seconds=60,
        )
        if bo:
            return bo, None
        if err and 'Nenhum login BackOffice' in (err or ''):
            return None, err
        time.sleep(max(15, intervalo_seg))
    return None, MSG_TODOS_ACESSOS_EM_USO


def _cfg(nome: str, default):
    return getattr(settings, nome, default)


def _hora_inicio() -> int:
    return int(_cfg('SYNC_ESTEIRA_HORA_INICIO', 22))


def _hora_fim() -> int:
    return int(_cfg('SYNC_ESTEIRA_HORA_FIM', 7))


def _max_por_hora() -> int:
    return int(_cfg('SYNC_ESTEIRA_MAX_POR_HORA', 40))


def _dentro_janela_horario(agora=None) -> bool:
    """Janela 22h–07h (horário local)."""
    agora = agora or timezone.localtime()
    h = agora.hour
    ini, fim = _hora_inicio(), _hora_fim()
    if ini > fim:
        return h >= ini or h < fim
    return ini <= h < fim


def job_em_andamento() -> bool:
    encerrar_execucoes_orfas()
    from crm_app.models import SyncStatusEsteiraExecucao

    return SyncStatusEsteiraExecucao.objects.filter(
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO
    ).exists()


def execucao_em_andamento() -> Optional['SyncStatusEsteiraExecucao']:
    encerrar_execucoes_orfas()
    from crm_app.models import SyncStatusEsteiraExecucao

    return (
        SyncStatusEsteiraExecucao.objects.filter(
            status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO
        )
        .order_by('-iniciado_em')
        .first()
    )


def queryset_vendas_elegiveis():
    from crm_app.models import Venda

    hoje = timezone.localdate()
    amanha = hoje + timedelta(days=1)

    return (
        Venda.objects.filter(
            ativo=True,
            status_esteira__isnull=False,
            status_esteira__estado__iexact='ABERTO',
        )
        .filter(
            Q(status_esteira__nome__iexact='AGENDADO')
            | Q(status_esteira__nome__iexact='PENDENCIADA')
        )
        .exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico='')
        .select_related('cliente', 'vendedor', 'status_esteira', 'motivo_pendencia')
        .annotate(
            _prio_data=Case(
                When(data_agendamento=hoje, then=Value(0)),
                When(data_agendamento=amanha, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
            _prio_status=Case(
                When(status_esteira__nome__iexact='AGENDADO', then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by('_prio_data', '_prio_status', 'data_criacao')
    )


def _cpf_cnpj_venda(venda) -> str:
    from crm_app.utils import limpar_texto

    if not venda.cliente or not venda.cliente.cpf_cnpj:
        return ''
    return limpar_texto(venda.cliente.cpf_cnpj)


def _pausa_aleatoria_entre_pedidos():
    if random.random() < 0.45:
        lo = int(_cfg('SYNC_ESTEIRA_INTERVALO_CURTO_MIN_SEG', 120))
        hi = int(_cfg('SYNC_ESTEIRA_INTERVALO_CURTO_MAX_SEG', 300))
    else:
        lo = int(_cfg('SYNC_ESTEIRA_INTERVALO_LONGO_MIN_SEG', 300))
        hi = int(_cfg('SYNC_ESTEIRA_INTERVALO_LONGO_MAX_SEG', 600))
    seg = random.randint(lo, max(lo + 1, hi))
    logger.info('[SYNC ESTEIRA] Pausa %ss antes do próximo pedido.', seg)
    time.sleep(seg)


def _registrar_consulta_hora(consultas_hora: Deque[float]):
    agora = time.time()
    consultas_hora.append(agora)
    limite = agora - 3600
    while consultas_hora and consultas_hora[0] < limite:
        consultas_hora.popleft()


def _aguardar_limite_hora(consultas_hora: Deque[float]):
    while len(consultas_hora) >= _max_por_hora():
        if not consultas_hora:
            break
        espera = max(30, consultas_hora[0] + 3600 - time.time())
        logger.info('[SYNC ESTEIRA] Limite %s/hora — aguardando %.0fs.', _max_por_hora(), espera)
        time.sleep(min(espera, 120))


def _telefones_usuario(usuario) -> List[str]:
    out = []
    for attr in ('tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3'):
        raw = (getattr(usuario, attr, None) or '').strip()
        dig = re.sub(r'\D', '', raw)
        if len(dig) >= 10:
            out.append(dig)
    return list(dict.fromkeys(out))


def _usuarios_diretoria_backoffice_admin():
    from usuarios.models import Usuario

    return (
        Usuario.objects.filter(is_active=True, groups__name__in=['BackOffice', 'Diretoria', 'Admin'])
        .distinct()
        .only('id', 'username', 'tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3')
    )


def _enviar_whatsapp_vendedor(venda) -> bool:
    from crm_app.utils import montar_mensagem_whatsapp_esteira_vendedor
    from crm_app.whatsapp_service import WhatsAppService

    if not venda.vendedor or not venda.vendedor.tel_whatsapp:
        return False
    msg = montar_mensagem_whatsapp_esteira_vendedor(venda, prefixo_atualizacao=True)
    if not msg:
        return False
    try:
        ok, _ = WhatsAppService().enviar_mensagem_texto(venda.vendedor.tel_whatsapp, msg)
        return bool(ok)
    except Exception as e:
        logger.warning('[SYNC ESTEIRA] Falha WhatsApp vendedor venda #%s: %s', venda.id, e)
        return False


def _enviar_relatorio_destinatarios(texto: str) -> int:
    from crm_app.whatsapp_service import WhatsAppService

    svc = WhatsAppService()
    enviados = 0
    vistos = set()
    for u in _usuarios_diretoria_backoffice_admin():
        for tel in _telefones_usuario(u):
            if tel in vistos:
                continue
            vistos.add(tel)
            try:
                ok, _ = svc.enviar_mensagem_texto(tel, texto)
                if ok:
                    enviados += 1
            except Exception as e:
                logger.debug('[SYNC ESTEIRA] Falha relatório para %s: %s', u.username, e)
    return enviados


def _montar_relatorio_final(execucao, detalhes: List[dict]) -> str:
    modo = 'Manual' if execucao.modo == execucao.MODO_MANUAL else 'Automático'
    linhas = [
        f'📊 *Relatório sync esteira PAP* ({modo})',
        '',
        f'🆔 Execução #{execucao.id}',
        f'📦 Total elegível: {execucao.total_pedidos}',
        f'✅ Processados: {execucao.processados}',
        f'🔄 Atualizados: {execucao.atualizados}',
        f'➖ Sem alteração: {execucao.sem_alteracao}',
        f'❌ Erros: {execucao.erros}',
        f'⚠️ Ignorados (sem CPF/CNPJ): {execucao.ignorados_sem_cpf}',
    ]
    atualizados = [d for d in detalhes if d.get('alterou')]
    if atualizados:
        linhas.append('')
        linhas.append('*Atualizações:*')
        for item in atualizados[:25]:
            linhas.append(
                f"• OS {item.get('os', '?')} — {item.get('status_anterior', '?')} → {item.get('status_novo', '?')}"
            )
        if len(atualizados) > 25:
            linhas.append(f'… e mais {len(atualizados) - 25}.')
    # Só erros finais (ignora a 1ª tentativa marcada como aguardando_retry).
    erros = [d for d in detalhes if d.get('erro') and not d.get('aguardando_retry')]
    if erros:
        linhas.append('')
        linhas.append('*Erros:*')
        for item in erros[:15]:
            err = re.sub(r'\s+', ' ', str(item.get('erro') or '?')).strip()
            linhas.append(f"• Venda #{item.get('venda_id')} OS {item.get('os', '?')}: {err[:120]}")
    ignorados = [d for d in detalhes if d.get('ignorado_sem_cpf')]
    if ignorados:
        linhas.append('')
        linhas.append(f'*Sem CPF/CNPJ:* {len(ignorados)} pedido(s).')
    return '\n'.join(linhas)


def _msg_indica_sessao_invalida(msg: str) -> bool:
    """Erros que exigem fechar o browser e abrir sessão nova no próximo pedido."""
    m = (msg or '').lower()
    sinais = (
        'v.tal',
        'vtal',
        'sessão',
        'sessao',
        'login',
        'fast pass',
        'consulta os',
        'filtros',
        'locator.click',
        'timeout',
        'page closed',
        'target closed',
        'browser has been closed',
        'context was destroyed',
        'execution context',
    )
    return any(s in m for s in sinais)


class _SessaoPapSyncHolder:
    """
    Reutiliza o mesmo browser/BO entre pedidos do sync.

    Antes cada venda fazia login completo no PAP (N logins = timeouts em Filtros / V.tal).
    """

    def __init__(self) -> None:
        self.automacao = None
        self.bo_usuario = None
        self.consultas = 0

    @property
    def max_consultas_por_sessao(self) -> int:
        return int(_cfg('SYNC_ESTEIRA_MAX_CONSULTAS_POR_SESSAO', 20))

    def fechar(self) -> None:
        from crm_app.pool_bo_pap import liberar_bo

        if self.automacao is not None:
            try:
                self.automacao._fechar_sessao()
            except Exception:
                pass
            self.automacao = None
        if self.bo_usuario is not None:
            bo_id = self.bo_usuario.id
            try:
                _run_django_sync(lambda: liberar_bo(bo_id, TELEFONE_JOB))
            except Exception as e:
                logger.warning('[SYNC ESTEIRA] Falha ao liberar BO %s: %s', bo_id, e)
            self.bo_usuario = None
        self.consultas = 0

    def _garantir_sessao(self, contador_uso_bo: Dict[int, int]) -> Tuple[bool, str]:
        from crm_app.services_pap_nio import PAPNioAutomation

        if (
            self.automacao is not None
            and self.bo_usuario is not None
            and getattr(self.automacao, 'logado', False)
            and self.consultas < self.max_consultas_por_sessao
        ):
            return True, ''

        self.fechar()

        # ORM em thread limpa: após a 1ª consulta Playwright este thread fica "async".
        bo_usuario, msg_erro = _aguardar_login_bo_safe(
            contador_uso_bo,
            timeout_seg=900,
            intervalo_seg=45,
        )
        if not bo_usuario:
            return False, msg_erro or 'login_indisponivel'

        contador_uso_bo[bo_usuario.id] = contador_uso_bo.get(bo_usuario.id, 0) + 1
        headless = getattr(settings, 'PAP_HEADLESS', True)
        capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
        optimize_fast = getattr(settings, 'PAP_STATUS_FAST_MODE', True)
        automacao = PAPNioAutomation(
            matricula_pap=bo_usuario.matricula_pap,
            senha_pap=bo_usuario.senha_pap,
            vendedor_nome='Sync-Esteira',
            headless=headless,
            capture_screenshots=capture_screenshots,
            optimize_for_credit=optimize_fast,
        )
        sucesso, msg = automacao.iniciar_sessao()
        if not sucesso:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass
            from crm_app.pool_bo_pap import liberar_bo

            _run_django_sync(lambda: liberar_bo(bo_usuario.id, TELEFONE_JOB))
            return False, msg

        self.automacao = automacao
        self.bo_usuario = bo_usuario
        self.consultas = 0
        logger.info(
            '[SYNC ESTEIRA] Sessão PAP aberta (BO=%s, máx=%s consultas).',
            getattr(bo_usuario, 'username', bo_usuario.id),
            self.max_consultas_por_sessao,
        )
        return True, ''

    def consultar(
        self,
        venda,
        *,
        contador_uso_bo: Dict[int, int],
    ) -> Tuple[bool, str, list, Optional[str]]:
        from crm_app.pool_bo_pap import (
            TIPO_AUTOMACAO_STATUS,
            atualizar_historico_consulta_pap_resultado,
        )
        from crm_app.services_pap_nio import PAPNioAutomation
        from crm_app.utils import obter_os_prioridade_crm_por_cpf

        cpf = _cpf_cnpj_venda(venda)
        if len(cpf) not in (11, 14):
            return False, 'sem_cpf', [], None

        os_num = (venda.ordem_servico or '').strip()
        os_prioridade = obter_os_prioridade_crm_por_cpf(cpf)

        ok_sessao, msg_sessao = self._garantir_sessao(contador_uso_bo)
        if not ok_sessao:
            return False, msg_sessao, [], None

        bo_usuario = self.bo_usuario
        automacao = self.automacao
        tempo_inicio = time.time()
        try:
            sucesso, msg, detalhes, _ = automacao.consulta_os_por_cpf_com_resultado(
                cpf,
                numero_os_filtro=os_num,
                os_prioridade_crm=os_prioridade,
            )
            tempo = round(time.time() - tempo_inicio, 1)
            self.consultas += 1
            _run_django_sync(
                lambda: atualizar_historico_consulta_pap_resultado(
                    vendedor_telefone=TELEFONE_JOB,
                    bo_usuario=bo_usuario,
                    tipo_automacao=TIPO_AUTOMACAO_STATUS,
                    sucesso=sucesso,
                    mensagem_resultado=f'{msg} ({tempo}s)',
                )
            )
            if not sucesso and _msg_indica_sessao_invalida(msg):
                logger.warning(
                    '[SYNC ESTEIRA] Sessão invalidada após venda #%s: %s',
                    venda.id,
                    (msg or '')[:160],
                )
                self.fechar()
            elif self.consultas >= self.max_consultas_por_sessao:
                logger.info(
                    '[SYNC ESTEIRA] Reciclando sessão após %s consultas.',
                    self.consultas,
                )
                self.fechar()
            return sucesso, msg, detalhes or [], None
        except Exception as e:
            logger.exception('[SYNC ESTEIRA] Erro PAP venda #%s: %s', venda.id, e)
            err_msg = PAPNioAutomation._mensagem_erro_playwright(e)
            _run_django_sync(
                lambda: atualizar_historico_consulta_pap_resultado(
                    vendedor_telefone=TELEFONE_JOB,
                    bo_usuario=bo_usuario,
                    tipo_automacao=TIPO_AUTOMACAO_STATUS,
                    sucesso=False,
                    mensagem_resultado=err_msg,
                )
            )
            self.fechar()
            return False, err_msg, [], None


def _consultar_pap_pedido(
    venda,
    *,
    contador_uso_bo: Dict[int, int],
    sessao: Optional[_SessaoPapSyncHolder] = None,
) -> Tuple[bool, str, list, Optional[str]]:
    """Consulta um pedido no PAP. Preferir `sessao` compartilhada no job."""
    if sessao is not None:
        return sessao.consultar(venda, contador_uso_bo=contador_uso_bo)

    # Fallback isolado (testes / chamada avulsa): abre e fecha na hora.
    holder = _SessaoPapSyncHolder()
    try:
        return holder.consultar(venda, contador_uso_bo=contador_uso_bo)
    finally:
        holder.fechar()


def _processar_um_pedido(
    venda,
    *,
    contador_uso_bo: Dict[int, int],
    retry: bool = False,
    sessao: Optional[_SessaoPapSyncHolder] = None,
) -> dict:
    from crm_app.models import Venda
    from crm_app.utils import sincronizar_venda_crm_apos_status_pap

    os_num = (venda.ordem_servico or '').strip()
    cpf = _cpf_cnpj_venda(venda)
    base = {
        'venda_id': venda.id,
        'os': os_num,
        'retry': retry,
        'alterou': False,
    }
    if len(cpf) not in (11, 14):
        return {**base, 'ignorado_sem_cpf': True}

    sucesso, msg, detalhes, _ = _consultar_pap_pedido(
        venda, contador_uso_bo=contador_uso_bo, sessao=sessao,
    )
    if not sucesso:
        return {**base, 'erro': msg or 'falha_pap', 'retentar': True}

    if msg == 'no_results' or not detalhes:
        return {**base, 'sem_alteracao': True, 'detalhe': 'sem_resultado_pap'}

    pos_pap: dict = {}

    def _pos_pap():
        alteracoes = sincronizar_venda_crm_apos_status_pap(cpf, detalhes, os_filtro=os_num)
        if not alteracoes:
            pos_pap['resultado'] = {**base, 'sem_alteracao': True}
            return
        item = alteracoes[0]
        venda_atual = Venda.objects.select_related(
            'cliente', 'vendedor', 'status_esteira', 'motivo_pendencia'
        ).get(pk=venda.id)
        wpp = False
        if item.get('alterou') and item.get('notificar_whatsapp', True):
            wpp = _enviar_whatsapp_vendedor(venda_atual)
        pos_pap['resultado'] = {
            **base,
            **item,
            'whatsapp_vendedor': wpp,
        }

    _run_django_sync(_pos_pap)
    return pos_pap.get('resultado', {**base, 'sem_alteracao': True})


def _atualizar_execucao(execucao, **kwargs):
    """Persiste progresso em thread ORM limpa (Playwright polui o thread do job)."""
    exec_id = execucao.id

    def _do():
        from crm_app.models import SyncStatusEsteiraExecucao

        e = SyncStatusEsteiraExecucao.objects.get(pk=exec_id)
        rj = kwargs.get('relatorio_json')
        if rj is None:
            rj = dict(e.relatorio_json or {})
        else:
            rj = dict(rj)
        rj['_heartbeat'] = timezone.now().isoformat()
        local_kwargs = {**kwargs, 'relatorio_json': rj}
        for k, v in local_kwargs.items():
            setattr(e, k, v)
        e.save(update_fields=list(local_kwargs.keys()))
        return local_kwargs

    saved = _run_django_sync(_do, timeout_seconds=60)
    for k, v in saved.items():
        setattr(execucao, k, v)


def _status_execucao(execucao_id: int) -> str:
    from crm_app.models import SyncStatusEsteiraExecucao

    return _run_django_sync(
        lambda: SyncStatusEsteiraExecucao.objects.values_list('status', flat=True).get(pk=execucao_id),
        timeout_seconds=30,
    )


def _minutos_sem_progresso(execucao) -> Optional[float]:
    hb = (execucao.relatorio_json or {}).get('_heartbeat')
    ref = execucao.iniciado_em
    if hb:
        try:
            parsed = datetime.fromisoformat(hb.replace('Z', '+00:00'))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            ref = parsed
        except (TypeError, ValueError):
            pass
    if not ref:
        return None
    return (timezone.now() - ref).total_seconds() / 60.0


def _stale_minutos() -> int:
    return int(_cfg('SYNC_ESTEIRA_STALE_MINUTES', 75))


def encerrar_execucoes_orfas(*, motivo: str = '') -> int:
    """Marca como interrompido jobs em_andamento sem heartbeat recente (ex.: deploy matou a thread)."""
    from crm_app.models import SyncStatusEsteiraExecucao

    limite_min = _stale_minutos()
    encerradas = 0
    msg = motivo or (
        f'Encerrado automaticamente — sem progresso há mais de {limite_min} min '
        '(possível reinício do servidor ou travamento).'
    )
    for execucao in SyncStatusEsteiraExecucao.objects.filter(
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
    ):
        minutos = _minutos_sem_progresso(execucao)
        if minutos is None or minutos < limite_min:
            continue
        _atualizar_execucao(
            execucao,
            status=SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO,
            finalizado_em=timezone.now(),
            mensagem_erro=msg[:2000],
        )
        encerradas += 1
        logger.warning(
            '[SYNC ESTEIRA] Execução órfã #%s encerrada (%.0f min sem progresso).',
            execucao.id,
            minutos,
        )
    return encerradas


def cancelar_execucao(execucao_id: int, *, usuario=None) -> Tuple[bool, str]:
    """Marca a execução como interrompida no banco (o loop do job verifica a cada pedido)."""
    from crm_app.models import SyncStatusEsteiraExecucao

    encerrar_execucoes_orfas()
    quem = getattr(usuario, 'username', None) or 'sistema'
    # Update direto: não usa a thread ORM do job (evita timeout se Playwright estiver ocupado).
    updated = SyncStatusEsteiraExecucao.objects.filter(
        pk=execucao_id,
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
    ).update(
        status=SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO,
        finalizado_em=timezone.now(),
        mensagem_erro=f'Cancelado por {quem}.'[:2000],
    )
    if updated:
        logger.info('[SYNC ESTEIRA] Execução #%s cancelada por %s.', execucao_id, quem)
        return True, ''
    if not SyncStatusEsteiraExecucao.objects.filter(pk=execucao_id).exists():
        return False, 'Execução não encontrada.'
    return False, 'Execução não está em andamento.'


def executar_job(execucao_id: int) -> None:
    from crm_app.models import SyncStatusEsteiraExecucao

    try:
        execucao = SyncStatusEsteiraExecucao.objects.get(pk=execucao_id)
    except SyncStatusEsteiraExecucao.DoesNotExist:
        logger.error('[SYNC ESTEIRA] Execução #%s não encontrada.', execucao_id)
        return

    if execucao.status != SyncStatusEsteiraExecucao.STATUS_PENDENTE:
        logger.warning('[SYNC ESTEIRA] Execução #%s não está pendente (%s).', execucao_id, execucao.status)
        return

    vendas = list(queryset_vendas_elegiveis())
    fila: List = list(vendas)
    retentativas: List = []
    detalhes: List[dict] = []
    contador_uso_bo: Dict[int, int] = {}
    consultas_hora: Deque[float] = deque()
    sessao_pap = _SessaoPapSyncHolder()

    _atualizar_execucao(
        execucao,
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
        total_pedidos=len(vendas),
        relatorio_json={'detalhes': []},
    )
    logger.info('[SYNC ESTEIRA] Iniciando execução #%s (%s) — %s pedidos.', execucao_id, execucao.modo, len(vendas))

    processados = atualizados = sem_alteracao = erros = ignorados = 0
    primeira = True

    try:
        while fila or retentativas:
            status_atual = _status_execucao(execucao_id)
            if status_atual != SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
                logger.info('[SYNC ESTEIRA] Execução #%s interrompida externamente.', execucao_id)
                execucao.status = status_atual
                break

            if execucao.modo == SyncStatusEsteiraExecucao.MODO_AUTOMATICO and not _dentro_janela_horario():
                logger.info('[SYNC ESTEIRA] Fora da janela 22h–07h — encerrando execução automática.')
                break

            if retentativas:
                venda = retentativas.pop(0)
                retry = True
            else:
                venda = fila.pop(0)
                retry = False

            if not primeira:
                _pausa_aleatoria_entre_pedidos()
            primeira = False

            _aguardar_limite_hora(consultas_hora)

            try:
                resultado = _processar_um_pedido(
                    venda,
                    contador_uso_bo=contador_uso_bo,
                    retry=retry,
                    sessao=sessao_pap,
                )
            except Exception as e:
                logger.exception('[SYNC ESTEIRA] Falha inesperada venda #%s', venda.id)
                sessao_pap.fechar()
                resultado = {
                    'venda_id': venda.id,
                    'os': venda.ordem_servico,
                    'erro': str(e)[:300],
                    'retentar': True,
                }

            _registrar_consulta_hora(consultas_hora)

            # processados = pedidos finalizados (não tentativas). Retry reprocessa o mesmo
            # pedido; contar tentativas fazia o badge passar de total (ex.: 152/85).
            if resultado.get('ignorado_sem_cpf'):
                processados += 1
                ignorados += 1
                detalhes.append(resultado)
            elif resultado.get('erro'):
                if resultado.get('retentar') and not retry:
                    retentativas.append(venda)
                    detalhes.append({**resultado, 'aguardando_retry': True})
                else:
                    processados += 1
                    erros += 1
                    detalhes.append(resultado)
            elif resultado.get('alterou'):
                processados += 1
                atualizados += 1
                detalhes.append(resultado)
            else:
                processados += 1
                sem_alteracao += 1
                detalhes.append(resultado)

            _atualizar_execucao(
                execucao,
                processados=processados,
                atualizados=atualizados,
                sem_alteracao=sem_alteracao,
                erros=erros,
                ignorados_sem_cpf=ignorados,
                relatorio_json={'detalhes': detalhes[-200:]},
            )
    finally:
        sessao_pap.fechar()

    status_final = SyncStatusEsteiraExecucao.STATUS_CONCLUIDO
    status_atual = _status_execucao(execucao_id)
    execucao.status = status_atual
    if status_atual == SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
        if fila or retentativas:
            status_final = SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO
    else:
        status_final = status_atual

    _atualizar_execucao(
        execucao,
        status=status_final,
        finalizado_em=timezone.now(),
        processados=processados,
        atualizados=atualizados,
        sem_alteracao=sem_alteracao,
        erros=erros,
        ignorados_sem_cpf=ignorados,
        relatorio_json={'detalhes': detalhes},
    )

    try:
        texto = _montar_relatorio_final(execucao, detalhes)
        _run_django_sync(lambda: _enviar_relatorio_destinatarios(texto), timeout_seconds=180)
    except Exception as e:
        logger.exception('[SYNC ESTEIRA] Falha ao enviar relatório: %s', e)

    if erros or status_final == SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO:
        try:
            alerta = (
                f'⚠️ *Sync esteira PAP* — execução #{execucao.id}\n\n'
                f'Status: {status_final}\n'
                f'Erros: {erros}\n'
                f'Pendentes na fila: {len(fila) + len(retentativas)}'
            )
            _run_django_sync(lambda: _enviar_relatorio_destinatarios(alerta), timeout_seconds=180)
        except Exception:
            pass

    logger.info(
        '[SYNC ESTEIRA] Execução #%s finalizada (%s). proc=%s att=%s err=%s',
        execucao_id,
        status_final,
        processados,
        atualizados,
        erros,
    )


def tentar_iniciar_automatico() -> bool:
    from crm_app.models import SyncStatusEsteiraExecucao

    if job_em_andamento():
        logger.info('[SYNC ESTEIRA] Automático ignorado — job manual/em andamento.')
        return False
    if not _dentro_janela_horario():
        logger.info('[SYNC ESTEIRA] Automático fora da janela horária.')
        return False
    execucao = SyncStatusEsteiraExecucao.objects.create(
        modo=SyncStatusEsteiraExecucao.MODO_AUTOMATICO,
        status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
    )
    try:
        executar_job(execucao.id)
    except Exception as e:
        logger.exception('[SYNC ESTEIRA] Erro fatal execução automática #%s: %s', execucao.id, e)
        try:
            _run_django_sync(
                lambda: SyncStatusEsteiraExecucao.objects.filter(
                    pk=execucao.id,
                    status__in=[
                        SyncStatusEsteiraExecucao.STATUS_PENDENTE,
                        SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
                    ],
                ).update(
                    status=SyncStatusEsteiraExecucao.STATUS_ERRO,
                    mensagem_erro=str(e)[:2000],
                    finalizado_em=timezone.now(),
                ),
                timeout_seconds=60,
            )
        except Exception:
            logger.exception('[SYNC ESTEIRA] Falha ao marcar execução #%s como erro.', execucao.id)
        return False
    return True


def criar_e_iniciar_execucao_manual(*, usuario=None) -> Tuple[Optional[int], Optional[str]]:
    """Inicia sync manual em thread (API / interface)."""
    from crm_app.models import SyncStatusEsteiraExecucao

    if job_em_andamento():
        return None, 'Já existe uma sincronização em andamento.'

    execucao = SyncStatusEsteiraExecucao.objects.create(
        modo=SyncStatusEsteiraExecucao.MODO_MANUAL,
        status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
        iniciado_por=usuario,
    )

    def _runner():
        import django.db

        django.db.close_old_connections()
        try:
            executar_job(execucao.id)
        except Exception as e:
            logger.exception('[SYNC ESTEIRA] Erro fatal execução #%s: %s', execucao.id, e)
            try:
                _run_django_sync(
                    lambda: SyncStatusEsteiraExecucao.objects.filter(pk=execucao.id).update(
                        status=SyncStatusEsteiraExecucao.STATUS_ERRO,
                        mensagem_erro=str(e)[:2000],
                        finalizado_em=timezone.now(),
                    ),
                    timeout_seconds=60,
                )
            except Exception:
                SyncStatusEsteiraExecucao.objects.filter(pk=execucao.id).update(
                    status=SyncStatusEsteiraExecucao.STATUS_ERRO,
                    mensagem_erro=str(e)[:2000],
                    finalizado_em=timezone.now(),
                )
            try:
                _run_django_sync(
                    lambda: _enviar_relatorio_destinatarios(
                        f'❌ *Sync esteira PAP* falhou (#{execucao.id})\n\n{str(e)[:500]}'
                    ),
                    timeout_seconds=120,
                )
            except Exception:
                pass
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=_runner, name=f'sync-esteira-{execucao.id}', daemon=True)
    t.start()
    return execucao.id, None
