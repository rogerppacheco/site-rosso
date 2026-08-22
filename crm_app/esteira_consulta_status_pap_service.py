"""
Consulta STATUS PAP na Esteira usando a matrícula do usuário logado.

Escopo = aba/filtros atuais (não o lote noturno). Ritmo ~5–6 O.S./min.
Cancelar encerra o job e desloga a sessão PAP.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

TELEFONE_JOB_PREFIX = 'CONSULTA-ESTEIRA-PAP'
ABAS_CONSULTA_PERMITIDAS = frozenset({'TODOS', 'AGENDADO', 'PENDEN'})


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

    t = threading.Thread(target=worker, daemon=True, name='consulta-esteira-orm')
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        kind, payload = q.get()
        if kind == 'err':
            raise payload
        return payload
    if t.is_alive():
        logger.error('[CONSULTA ESTEIRA] _run_django_sync expirou após %ss.', timeout_seconds)
        raise TimeoutError('django_sync_timeout')
    raise TimeoutError('django_sync_timeout')


def _cfg(nome: str, default):
    return getattr(settings, nome, default)


def _intervalo_min() -> int:
    return int(_cfg('CONSULTA_ESTEIRA_INTERVALO_MIN_SEG', 8))


def _intervalo_max() -> int:
    return int(_cfg('CONSULTA_ESTEIRA_INTERVALO_MAX_SEG', 15))


def _validar_credenciais_pap(usuario) -> Tuple[bool, str]:
    matricula = (getattr(usuario, 'matricula_pap', None) or '').strip()
    senha = (getattr(usuario, 'senha_pap', None) or '').strip()
    if not matricula or not senha:
        return False, (
            'Seu usuário não tem matrícula/senha PAP vinculadas. '
            'Cadastre em Gestão de Acessos antes de consultar.'
        )
    return True, matricula


def _aba_permitida(aba: str) -> bool:
    a = (aba or '').strip().upper()
    if a in ABAS_CONSULTA_PERMITIDAS:
        return True
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', (aba or '').strip()))


def queryset_vendas_consulta_aba(filtros: Dict[str, Any]):
    """
    Queryset alinhado à aba/filtros da Esteira (o que o usuário vê).

    Ordem = mesma da tabela (`-data_criacao`): o 1º da tela é o 1º consultado.
    Respeita data, turno, status do agendamento, tipo/motivo de pendência, busca
    e filtros de coluna (Posso reagendar?, Posso antecipar?, O.S., vendedor, etc.).
    """
    from crm_app.models import Venda

    aba = (filtros.get('aba') or 'TODOS').strip()
    busca = (filtros.get('busca') or '').strip()
    turno = (filtros.get('periodo_agendamento') or '').strip().upper()
    status_ag = (filtros.get('status_agendamento') or '').strip()
    tipo_pend = (filtros.get('tipo_pendencia') or '').strip().upper()
    motivo_pend = (filtros.get('motivo_pendencia') or '').strip()
    colunas = filtros.get('colunas') if isinstance(filtros.get('colunas'), dict) else {}

    qs = (
        Venda.objects.filter(
            ativo=True,
            status_esteira__isnull=False,
            status_esteira__estado__iexact='ABERTO',
        )
        .filter(
            Q(status_esteira__nome__iexact='AGENDADO')
            | Q(status_esteira__nome__icontains='PENDEN')
        )
        .exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico='')
        .select_related(
            'cliente',
            'vendedor',
            'status_esteira',
            'motivo_pendencia',
            'status_agendamento',
            'plano',
            'editado_por',
        )
    )

    aba_u = aba.upper()
    if aba_u == 'PENDEN' or 'PENDEN' in aba_u:
        qs = qs.filter(status_esteira__nome__icontains='PENDEN')
    elif aba_u == 'AGENDADO':
        qs = qs.filter(status_esteira__nome__iexact='AGENDADO')
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', aba):
        qs = qs.filter(status_esteira__nome__iexact='AGENDADO', data_agendamento=aba)
    elif aba_u != 'TODOS':
        qs = qs.none()

    # Turno: aba Agendados ou data específica
    if turno in ('MANHA', 'TARDE') and (
        aba_u == 'AGENDADO' or re.match(r'^\d{4}-\d{2}-\d{2}$', aba)
    ):
        qs = qs.filter(periodo_agendamento=turno)

    # Status do agendamento: Agendados ou data
    if status_ag and (aba_u == 'AGENDADO' or re.match(r'^\d{4}-\d{2}-\d{2}$', aba)):
        sa_u = status_ag.upper()
        if sa_u in ('SEM', 'NULL', 'NONE', '0'):
            qs = qs.filter(status_agendamento__isnull=True)
        elif status_ag.isdigit():
            qs = qs.filter(status_agendamento_id=int(status_ag))

    if tipo_pend in ('CLIENTE', 'TECNICA') and (aba_u in ('PENDEN', 'TODOS') or 'PENDEN' in aba_u):
        if tipo_pend == 'CLIENTE':
            qs = qs.filter(
                motivo_pendencia__isnull=False,
                motivo_pendencia__tipo_pendencia__icontains='CLIENTE',
            )
        else:
            qs = qs.filter(motivo_pendencia__isnull=False).filter(
                Q(motivo_pendencia__tipo_pendencia__icontains='TÉCNICA')
                | Q(motivo_pendencia__tipo_pendencia__icontains='TECNICA')
            )

    if motivo_pend and (aba_u in ('PENDEN', 'TODOS') or 'PENDEN' in aba_u):
        mp_u = motivo_pend.upper()
        if mp_u in ('SEM', 'NULL', 'NONE', '0'):
            qs = qs.filter(motivo_pendencia__isnull=True)
        elif motivo_pend.isdigit():
            qs = qs.filter(motivo_pendencia_id=int(motivo_pend))

    if busca:
        search_clean = re.sub(r'\D', '', busca)
        filters = (
            Q(ordem_servico__icontains=busca)
            | Q(cliente__nome_razao_social__icontains=busca)
            | Q(cliente__cpf_cnpj__icontains=busca)
        )
        if search_clean:
            filters |= Q(cliente__cpf_cnpj__icontains=search_clean) | Q(
                ordem_servico__icontains=search_clean
            )
        qs = qs.filter(filters)

    qs = _aplicar_filtros_colunas_esteira(qs, colunas)

    # Mesma ordem da listagem da Esteira (1º da tabela = 1º consultado)
    return qs.order_by('-data_criacao', '-id')


def _aplicar_filtros_colunas_esteira(qs, colunas: Dict[str, Any]):
    """Aplica filtros da linha de colunas da Esteira (mesmo critério visual da tabela)."""
    from django.db.models import CharField, F, Func, Value
    from django.db.models.functions import Cast, Coalesce, Length

    if not colunas:
        return qs

    class ToChar(Func):
        function = 'to_char'
        output_field = CharField()

    class RegexpReplace(Func):
        function = 'regexp_replace'
        arity = 4
        output_field = CharField()

    def _txt(key: str) -> str:
        return str(colunas.get(key) or '').strip()

    def _len_digitos_doc():
        return Length(
            RegexpReplace(
                Coalesce(F('cliente__cpf_cnpj'), Value('')),
                Value(r'[^0-9]'),
                Value(''),
                Value('g'),
            )
        )

    id_f = _txt('id')
    if id_f:
        qs = qs.annotate(_id_txt=Cast('id', CharField())).filter(_id_txt__icontains=id_f)

    data_venda = _txt('data_venda')
    if data_venda:
        m_iso = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', data_venda)
        m_br = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', data_venda)
        if m_iso:
            qs = qs.filter(data_criacao__date=data_venda)
        elif m_br:
            d, m, y = m_br.groups()
            qs = qs.filter(data_criacao__date=f'{y}-{int(m):02d}-{int(d):02d}')
        else:
            qs = qs.annotate(
                _fmt_data_criacao=ToChar(F('data_criacao'), Value('DD/MM/YYYY'))
            ).filter(_fmt_data_criacao__icontains=data_venda)

    os_f = _txt('os')
    if os_f:
        qs = qs.filter(ordem_servico__icontains=os_f)

    tipo_col = _txt('tipo_pendencia_col')
    if tipo_col:
        qs = qs.filter(motivo_pendencia__tipo_pendencia__icontains=tipo_col)

    motivo_f = _txt('motivo')
    if motivo_f:
        qs = qs.filter(motivo_pendencia__nome__icontains=motivo_f)

    data_ag = _txt('data_agendada')
    if data_ag:
        m_iso = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', data_ag)
        m_br = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', data_ag)
        if m_iso:
            qs = qs.filter(data_agendamento=data_ag)
        elif m_br:
            d, m, y = m_br.groups()
            qs = qs.filter(data_agendamento=f'{y}-{int(m):02d}-{int(d):02d}')
        else:
            qs = qs.annotate(
                _fmt_data_agendamento=ToChar(F('data_agendamento'), Value('DD/MM/YYYY'))
            ).filter(_fmt_data_agendamento__icontains=data_ag)

    turno_f = _txt('turno')
    if turno_f:
        t = turno_f.lower().replace('ã', 'a').replace('á', 'a')
        if 'manh' in t:
            qs = qs.filter(periodo_agendamento='MANHA')
        elif 'tard' in t:
            qs = qs.filter(periodo_agendamento='TARDE')
        else:
            qs = qs.filter(periodo_agendamento__icontains=turno_f)

    cliente_f = _txt('cliente')
    if cliente_f:
        digitos = re.sub(r'\D', '', cliente_f)
        q_cli = (
            Q(cliente__nome_razao_social__icontains=cliente_f)
            | Q(cliente__cpf_cnpj__icontains=cliente_f)
        )
        if digitos:
            q_cli |= Q(cliente__cpf_cnpj__icontains=digitos)
        qs = qs.filter(q_cli)

    vendedor_f = _txt('vendedor')
    if vendedor_f:
        qs = qs.filter(
            Q(vendedor__first_name__icontains=vendedor_f)
            | Q(vendedor__last_name__icontains=vendedor_f)
            | Q(vendedor__username__icontains=vendedor_f)
        )

    ad_cnpj = _txt('adiant_cnpj').lower()
    if ad_cnpj == 'realizado':
        qs = qs.filter(flag_adiant_cnpj=True)
    elif ad_cnpj == 'pendente':
        qs = (
            qs.filter(flag_adiant_cnpj=False)
            .exclude(classificacao_mei='MEI')
            .annotate(_doc_digits=_len_digitos_doc())
            .filter(_doc_digits=14)
        )
    elif ad_cnpj in ('nao elegivel', 'não elegivel', 'nao_elegivel'):
        qs = (
            qs.filter(flag_adiant_cnpj=False)
            .annotate(_doc_digits=_len_digitos_doc())
            .filter(Q(classificacao_mei='MEI') | ~Q(_doc_digits=14))
        )

    ad_com = _txt('adiant_comissao').lower()
    if ad_com == 'sim':
        qs = qs.filter(antecipacao_comissao=True)
    elif ad_com in ('nao', 'não'):
        qs = qs.filter(antecipacao_comissao=False)

    ad_sab = _txt('adiant_sabado').lower()
    if ad_sab == 'marcado':
        qs = qs.filter(adiantamento_sabado_marcado=True)
    elif ad_sab in ('nao', 'não'):
        qs = qs.filter(adiantamento_sabado_marcado=False)
    elif ad_sab == 'quitado':
        qs = qs.filter(
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_quitado_em__isnull=False,
        )

    plano_f = _txt('plano')
    if plano_f:
        qs = qs.filter(plano__nome__icontains=plano_f)

    status_f = _txt('status')
    if status_f:
        qs = qs.filter(status_esteira__nome__icontains=status_f)

    conf_f = _txt('conf_cliente').lower()
    if conf_f == 'sim':
        qs = qs.filter(cliente_confirmou_lembrete_instalacao=True)
    elif conf_f in ('nao', 'não'):
        qs = qs.filter(cliente_confirmou_lembrete_instalacao=False)
    elif conf_f in ('-', 'sem'):
        qs = qs.filter(cliente_confirmou_lembrete_instalacao__isnull=True)

    # Posso antecipar? (select: sim / nao / aguardando)
    posso_ant = _txt('posso_antecip').lower()
    if posso_ant == 'sim':
        qs = qs.filter(vendedor_pode_antecipar=True)
    elif posso_ant in ('nao', 'não'):
        qs = qs.filter(vendedor_pode_antecipar=False)
    elif posso_ant == 'aguardando':
        qs = qs.filter(
            data_solicitacao_posso_antecipar__isnull=False,
            data_resposta_posso_antecipar__isnull=True,
            vendedor_pode_antecipar__isnull=True,
        )

    # Posso reagendar? (select: sim / nao / aguardando)
    posso_reag = _txt('posso_reagendar').lower()
    if posso_reag == 'sim':
        qs = qs.filter(consultor_pode_reagendar=True)
    elif posso_reag in ('nao', 'não'):
        qs = qs.filter(consultor_pode_reagendar=False)
    elif posso_reag == 'aguardando':
        qs = qs.filter(
            data_solicitacao_reagendar_consultor__isnull=False,
            data_resposta_reagendar_consultor__isnull=True,
            consultor_pode_reagendar__isnull=True,
        )

    resp_f = _txt('resp')
    if resp_f:
        qs = qs.filter(
            Q(editado_por__first_name__icontains=resp_f)
            | Q(editado_por__last_name__icontains=resp_f)
            | Q(editado_por__username__icontains=resp_f)
        )

    return qs


def _cpf_cnpj_venda(venda) -> str:
    from crm_app.utils import limpar_texto

    if not venda.cliente or not venda.cliente.cpf_cnpj:
        return ''
    return limpar_texto(venda.cliente.cpf_cnpj)


def _resumo_resultado_item(resultado: dict) -> dict:
    """Item compacto para o front (últimos processados)."""
    err = (resultado.get('erro') or '').strip()
    if resultado.get('ignorado_sem_cpf'):
        situacao = 'ignorado'
    elif err:
        situacao = 'erro'
    elif resultado.get('alterou'):
        situacao = 'atualizado'
    else:
        situacao = 'ok'
    return {
        'venda_id': resultado.get('venda_id'),
        'os': (resultado.get('os') or '').strip(),
        'situacao': situacao,
        'erro': err[:120] if err else '',
        'status_novo': (resultado.get('status_novo') or '')[:40],
        # Mesmo formato da célula na grade (dd/mm HH:MM), para o progresso ao vivo não perder a data.
        'em': timezone.localtime().strftime('%d/%m %H:%M'),
    }


def _montar_relatorio_json(
    *,
    filtros: dict,
    detalhes: List[dict],
    atual_venda_id: Optional[int] = None,
    atual_os: str = '',
    atual_fase: str = '',
    matricula: str = '',
) -> dict:
    ultimos = [
        _resumo_resultado_item(d)
        for d in detalhes
        if d and not d.get('aguardando_retry')
    ][-8:]
    return {
        'filtros': filtros,
        'detalhes': detalhes[-200:],
        'atual_venda_id': atual_venda_id,
        'atual_os': (atual_os or '').strip(),
        'atual_fase': atual_fase or '',
        'ultimos': ultimos,
        'matricula': (matricula or '').strip()[:50],
    }


def _telefones_usuario(usuario) -> List[str]:
    out = []
    for attr in ('tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3'):
        raw = (getattr(usuario, attr, None) or '').strip()
        dig = re.sub(r'\D', '', raw)
        if len(dig) >= 10:
            out.append(dig)
    return list(dict.fromkeys(out))


def _enviar_relatorio_operador(execucao, detalhes: List[dict]) -> None:
    """Resumo da consulta da aba para o usuário que iniciou (se tiver WhatsApp)."""
    from crm_app.whatsapp_service import WhatsAppService

    usuario = execucao.iniciado_por
    if not usuario:
        return
    tels = _telefones_usuario(usuario)
    if not tels:
        return
    aba = ((execucao.relatorio_json or {}).get('filtros') or {}).get('aba') or '?'
    linhas = [
        f'📋 *Consulta STATUS Esteira* #{execucao.id}',
        f'Aba/filtro: `{aba}`',
        f'Processados: {execucao.processados}/{execucao.total_pedidos}',
        f'Atualizados CRM: {execucao.atualizados}',
        f'Sem alteração: {execucao.sem_alteracao}',
        f'Erros: {execucao.erros}',
    ]
    errs = [d for d in detalhes if d.get('erro')]
    if errs:
        linhas.append('')
        linhas.append('*Erros:*')
        for item in errs[:8]:
            linhas.append(
                f"• OS {item.get('os', '?')}: {str(item.get('erro') or '')[:80]}"
            )
    texto = '\n'.join(linhas)
    svc = WhatsAppService()
    for tel in tels:
        try:
            svc.enviar_mensagem_texto(tel, texto, variar=False)
        except Exception as e:
            logger.debug('[CONSULTA ESTEIRA] Falha relatório operador %s: %s', tel, e)


def _pausa_interruptivel(execucao_id: int) -> bool:
    """
    Pausa aleatória entre pedidos (~5–6/min).
    Retorna False se a execução foi cancelada durante a espera.
    """
    from crm_app.models import SyncStatusEsteiraExecucao

    lo = _intervalo_min()
    hi = max(lo + 1, _intervalo_max())
    seg = random.randint(lo, hi)
    logger.info('[CONSULTA ESTEIRA] Pausa %ss antes do próximo pedido.', seg)
    fim = time.time() + seg
    while time.time() < fim:
        status = _run_django_sync(
            lambda: SyncStatusEsteiraExecucao.objects.values_list('status', flat=True).get(
                pk=execucao_id
            ),
            timeout_seconds=30,
        )
        if status != SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
            return False
        time.sleep(min(1.0, max(0.2, fim - time.time())))
    return True


def _msg_indica_sessao_invalida(msg: str) -> bool:
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
        'já está logado',
        'sessao ativa',
        'sessão ativa',
    )
    return any(s in m for s in sinais)


class _SessaoPapUsuarioHolder:
    """Sessão PAP com credenciais do usuário logado (sem reciclar no meio do lote)."""

    def __init__(self, usuario) -> None:
        self.usuario = usuario
        self.matricula = (getattr(usuario, 'matricula_pap', None) or '').strip()
        self.senha = (getattr(usuario, 'senha_pap', None) or '').strip()
        self.automacao = None
        self.consultas = 0
        self.telefone_job = f'{TELEFONE_JOB_PREFIX}-{getattr(usuario, "id", 0)}'

    def fechar(self) -> None:
        """Desloga (Sair) e fecha o browser."""
        if self.automacao is not None:
            try:
                self.automacao._fechar_sessao()
            except Exception:
                pass
            self.automacao = None
        self.consultas = 0

    def _garantir_sessao(self) -> Tuple[bool, str]:
        from crm_app.services_pap_nio import PAPNioAutomation

        if self.automacao is not None and getattr(self.automacao, 'logado', False):
            return True, ''

        self.fechar()
        headless = getattr(settings, 'PAP_HEADLESS', True)
        capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
        # Lote diurno: evita modo fast agressivo (mais “robô”).
        optimize_fast = False
        automacao = PAPNioAutomation(
            matricula_pap=self.matricula,
            senha_pap=self.senha,
            vendedor_nome=getattr(self.usuario, 'username', 'Consulta-Esteira') or 'Consulta-Esteira',
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
            return False, msg or 'Falha ao logar no PAP.'

        self.automacao = automacao
        self.consultas = 0
        logger.info(
            '[CONSULTA ESTEIRA] Sessão PAP aberta (matrícula=%s).',
            self.matricula,
        )
        return True, ''

    def consultar(self, venda) -> Tuple[bool, str, list]:
        from crm_app.services_pap_nio import PAPNioAutomation
        from crm_app.utils import obter_os_prioridade_crm_por_cpf

        cpf = _cpf_cnpj_venda(venda)
        if len(cpf) not in (11, 14):
            return False, 'sem_cpf', []

        os_num = (venda.ordem_servico or '').strip()
        # Após a 1ª consulta Playwright o thread fica "async"; ORM só em thread limpa.
        os_prioridade = _run_django_sync(
            lambda: obter_os_prioridade_crm_por_cpf(cpf),
            timeout_seconds=60,
        )

        ok_sessao, msg_sessao = self._garantir_sessao()
        if not ok_sessao:
            return False, msg_sessao, []

        automacao = self.automacao
        try:
            sucesso, msg, detalhes, _ = automacao.consulta_os_por_cpf_com_resultado(
                cpf,
                numero_os_filtro=os_num,
                os_prioridade_crm=os_prioridade,
            )
            self.consultas += 1
            if not sucesso and _msg_indica_sessao_invalida(msg):
                logger.warning(
                    '[CONSULTA ESTEIRA] Sessão invalidada após venda #%s: %s',
                    venda.id,
                    (msg or '')[:160],
                )
                self.fechar()
            return sucesso, msg, detalhes or []
        except Exception as e:
            logger.exception('[CONSULTA ESTEIRA] Erro PAP venda #%s: %s', venda.id, e)
            err_msg = PAPNioAutomation._mensagem_erro_playwright(e)
            self.fechar()
            return False, err_msg, []


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
        logger.warning('[CONSULTA ESTEIRA] Falha WhatsApp vendedor venda #%s: %s', venda.id, e)
        return False


def _processar_um_pedido(venda, *, sessao: _SessaoPapUsuarioHolder) -> dict:
    from crm_app.models import Venda
    from crm_app.utils import (
        registrar_auditoria_consulta_status_pap,
        sincronizar_venda_crm_apos_status_pap,
    )

    os_num = (venda.ordem_servico or '').strip()
    cpf = _cpf_cnpj_venda(venda)
    base = {
        'venda_id': venda.id,
        'os': os_num,
        'alterou': False,
    }
    if len(cpf) not in (11, 14):
        return {**base, 'ignorado_sem_cpf': True}

    def _auditar(erro: str = ''):
        v = Venda.objects.get(pk=venda.id)
        registrar_auditoria_consulta_status_pap(
            v, matricula=sessao.matricula, erro=erro
        )

    sucesso, msg, detalhes = sessao.consultar(venda)
    if not sucesso:
        err = (msg or 'falha_pap')[:255]
        _run_django_sync(lambda: _auditar(err))
        return {**base, 'erro': err}

    if msg == 'no_results' or not detalhes:
        _run_django_sync(lambda: _auditar(''))
        return {**base, 'sem_alteracao': True, 'detalhe': 'sem_resultado_pap'}

    pos_pap: dict = {}

    def _pos_pap():
        alteracoes = sincronizar_venda_crm_apos_status_pap(cpf, detalhes, os_filtro=os_num)
        v = Venda.objects.select_related(
            'cliente', 'vendedor', 'status_esteira', 'motivo_pendencia', 'status_agendamento'
        ).get(pk=venda.id)
        registrar_auditoria_consulta_status_pap(v, matricula=sessao.matricula, erro='')
        if not alteracoes:
            pos_pap['resultado'] = {**base, 'sem_alteracao': True}
            return
        item = alteracoes[0]
        wpp = False
        if item.get('alterou') and item.get('notificar_whatsapp', False):
            wpp = _enviar_whatsapp_vendedor(v)
        pos_pap['resultado'] = {
            **base,
            **item,
            'whatsapp_vendedor': wpp,
        }

    _run_django_sync(_pos_pap)
    return pos_pap.get('resultado', {**base, 'sem_alteracao': True})


def _atualizar_execucao(execucao, **kwargs):
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
        lambda: SyncStatusEsteiraExecucao.objects.values_list('status', flat=True).get(
            pk=execucao_id
        ),
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


# Sessão ativa por execução — cancelamento força logout imediato se possível
_sessoes_ativas: Dict[int, _SessaoPapUsuarioHolder] = {}
_sessoes_lock = threading.Lock()


def executar_job_consulta_aba(execucao_id: int) -> None:
    from crm_app.models import SyncStatusEsteiraExecucao

    try:
        execucao = SyncStatusEsteiraExecucao.objects.select_related('iniciado_por').get(
            pk=execucao_id
        )
    except SyncStatusEsteiraExecucao.DoesNotExist:
        logger.error('[CONSULTA ESTEIRA] Execução #%s não encontrada.', execucao_id)
        return

    if execucao.status != SyncStatusEsteiraExecucao.STATUS_PENDENTE:
        logger.warning(
            '[CONSULTA ESTEIRA] Execução #%s não está pendente (%s).',
            execucao_id,
            execucao.status,
        )
        return

    usuario = execucao.iniciado_por
    if not usuario:
        _atualizar_execucao(
            execucao,
            status=SyncStatusEsteiraExecucao.STATUS_ERRO,
            finalizado_em=timezone.now(),
            mensagem_erro='Execução sem usuário iniciador.',
        )
        return

    ok_cred, msg_cred = _validar_credenciais_pap(usuario)
    if not ok_cred:
        _atualizar_execucao(
            execucao,
            status=SyncStatusEsteiraExecucao.STATUS_ERRO,
            finalizado_em=timezone.now(),
            mensagem_erro=msg_cred[:2000],
        )
        return

    filtros = dict((execucao.relatorio_json or {}).get('filtros') or {})
    vendas = list(queryset_vendas_consulta_aba(filtros))
    fila: List = list(vendas)
    detalhes: List[dict] = []
    sessao = _SessaoPapUsuarioHolder(usuario)
    with _sessoes_lock:
        _sessoes_ativas[execucao_id] = sessao

    _atualizar_execucao(
        execucao,
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
        total_pedidos=len(vendas),
        relatorio_json=_montar_relatorio_json(filtros=filtros, detalhes=[], matricula=sessao.matricula),
    )
    logger.info(
        '[CONSULTA ESTEIRA] Início #%s (aba=%s) — %s pedidos, matrícula=%s.',
        execucao_id,
        filtros.get('aba'),
        len(vendas),
        sessao.matricula,
    )

    processados = atualizados = sem_alteracao = erros = ignorados = 0
    primeira = True

    try:
        while fila:
            status_atual = _status_execucao(execucao_id)
            if status_atual != SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
                logger.info('[CONSULTA ESTEIRA] Execução #%s interrompida.', execucao_id)
                execucao.status = status_atual
                break

            if not primeira:
                if not _pausa_interruptivel(execucao_id):
                    execucao.status = _status_execucao(execucao_id)
                    break
            primeira = False

            venda = fila.pop(0)
            os_atual = (venda.ordem_servico or '').strip()
            _atualizar_execucao(
                execucao,
                processados=processados,
                atualizados=atualizados,
                sem_alteracao=sem_alteracao,
                erros=erros,
                ignorados_sem_cpf=ignorados,
                relatorio_json=_montar_relatorio_json(
                    filtros=filtros,
                    detalhes=detalhes,
                    atual_venda_id=venda.id,
                    atual_os=os_atual,
                    atual_fase='consultando',
                    matricula=sessao.matricula,
                ),
            )

            try:
                resultado = _processar_um_pedido(venda, sessao=sessao)
            except Exception as e:
                logger.exception('[CONSULTA ESTEIRA] Falha inesperada venda #%s', venda.id)
                sessao.fechar()
                err_txt = str(e)[:255]
                try:
                    from crm_app.models import Venda as VendaModel
                    from crm_app.utils import registrar_auditoria_consulta_status_pap as _reg_aud

                    def _aud_err():
                        v = VendaModel.objects.get(pk=venda.id)
                        _reg_aud(v, matricula=sessao.matricula, erro=err_txt)

                    _run_django_sync(_aud_err)
                except Exception:
                    pass
                resultado = {
                    'venda_id': venda.id,
                    'os': os_atual,
                    'erro': err_txt,
                }

            if resultado.get('ignorado_sem_cpf'):
                processados += 1
                ignorados += 1
            elif resultado.get('erro'):
                processados += 1
                erros += 1
                if _msg_indica_sessao_invalida(str(resultado.get('erro') or '')):
                    detalhes.append(resultado)
                    _atualizar_execucao(
                        execucao,
                        processados=processados,
                        atualizados=atualizados,
                        sem_alteracao=sem_alteracao,
                        erros=erros,
                        ignorados_sem_cpf=ignorados,
                        mensagem_erro=(resultado.get('erro') or '')[:2000],
                        relatorio_json=_montar_relatorio_json(
                            filtros=filtros,
                            detalhes=detalhes,
                            atual_venda_id=venda.id,
                            atual_os=os_atual,
                            atual_fase='erro_sessao',
                            matricula=sessao.matricula,
                        ),
                    )
                    logger.warning(
                        '[CONSULTA ESTEIRA] Parando lote por sessão/login inválido: %s',
                        (resultado.get('erro') or '')[:160],
                    )
                    break
            elif resultado.get('alterou'):
                processados += 1
                atualizados += 1
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
                relatorio_json=_montar_relatorio_json(
                    filtros=filtros,
                    detalhes=detalhes,
                    atual_venda_id=None,
                    atual_os='',
                    atual_fase='entre_pedidos' if fila else 'finalizando',
                    matricula=sessao.matricula,
                ),
            )
    finally:
        sessao.fechar()
        with _sessoes_lock:
            _sessoes_ativas.pop(execucao_id, None)

    status_atual = _status_execucao(execucao_id)
    if status_atual == SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
        status_final = SyncStatusEsteiraExecucao.STATUS_CONCLUIDO
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
        relatorio_json=_montar_relatorio_json(
            filtros=filtros,
            detalhes=detalhes,
            atual_fase='concluido' if status_final == SyncStatusEsteiraExecucao.STATUS_CONCLUIDO else status_final,
            matricula=sessao.matricula,
        ),
    )
    logger.info(
        '[CONSULTA ESTEIRA] Fim #%s (%s). proc=%s att=%s err=%s',
        execucao_id,
        status_final,
        processados,
        atualizados,
        erros,
    )
    try:
        execucao.refresh_from_db()
    except Exception:
        pass
    try:
        _run_django_sync(lambda: _enviar_relatorio_operador(execucao, detalhes), timeout_seconds=120)
    except Exception as e:
        logger.debug('[CONSULTA ESTEIRA] Relatório operador falhou: %s', e)


def cancelar_consulta_aba(execucao_id: int, *, usuario=None) -> Tuple[bool, str]:
    """Cancela a consulta e desloga a sessão PAP imediatamente."""
    from crm_app.esteira_sync_status_pap_service import cancelar_execucao, encerrar_execucoes_orfas

    encerrar_execucoes_orfas()
    ok, err = cancelar_execucao(execucao_id, usuario=usuario)
    with _sessoes_lock:
        sessao = _sessoes_ativas.pop(execucao_id, None)
    if sessao is not None:
        try:
            sessao.fechar()
        except Exception:
            pass
    return ok, err


def criar_e_iniciar_consulta_aba(*, usuario, filtros: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], int]:
    """
    Inicia consulta da aba em thread.
    Retorna (execucao_id|None, erro|None, total_pedidos).
    """
    from crm_app.esteira_sync_status_pap_service import job_em_andamento
    from crm_app.models import SyncStatusEsteiraExecucao

    if not usuario or not usuario.is_authenticated:
        return None, 'Usuário não autenticado.', 0

    ok_cred, msg_cred = _validar_credenciais_pap(usuario)
    if not ok_cred:
        return None, msg_cred, 0

    aba = (filtros.get('aba') or '').strip()
    if not _aba_permitida(aba):
        return None, (
            'Consulta PAP disponível apenas nas abas Todos, Agendados, Pendentes '
            'ou em uma data específica.'
        ), 0

    if job_em_andamento():
        return None, 'Já existe uma sincronização/consulta PAP em andamento.', 0

    total = queryset_vendas_consulta_aba(filtros).count()
    if total <= 0:
        return None, 'Nenhum pedido elegível na aba/filtros atuais (AGENDADO/PENDENCIADA com O.S.).', 0

    execucao = SyncStatusEsteiraExecucao.objects.create(
        modo=SyncStatusEsteiraExecucao.MODO_CONSULTA_ABA,
        status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
        iniciado_por=usuario,
        total_pedidos=total,
        relatorio_json={'filtros': filtros, 'detalhes': []},
    )

    def _runner():
        import django.db

        django.db.close_old_connections()
        try:
            executar_job_consulta_aba(execucao.id)
        except Exception as e:
            logger.exception('[CONSULTA ESTEIRA] Erro fatal execução #%s: %s', execucao.id, e)
            try:
                SyncStatusEsteiraExecucao.objects.filter(pk=execucao.id).update(
                    status=SyncStatusEsteiraExecucao.STATUS_ERRO,
                    mensagem_erro=str(e)[:2000],
                    finalizado_em=timezone.now(),
                )
            except Exception:
                pass
            with _sessoes_lock:
                sessao = _sessoes_ativas.pop(execucao.id, None)
            if sessao is not None:
                try:
                    sessao.fechar()
                except Exception:
                    pass
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=_runner, name=f'consulta-esteira-{execucao.id}', daemon=True)
    t.start()
    return execucao.id, None, total
