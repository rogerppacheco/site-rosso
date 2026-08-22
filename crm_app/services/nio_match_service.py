"""
Match estrito CRM ↔ Nio para preencher PIX, barras e valor.

Só grava quando o casamento é único (1 fatura CRM e 1 fatura Nio na mesma
data de vencimento). Duplicidade, divergência de valor ou ausência de par
são só registradas — nada é aplicado.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Sequence

from django.core.cache import cache
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

STATUS_MATCH = 'MATCH'
STATUS_AMBIGUO = 'AMBIGUO'
STATUS_SEM_MATCH = 'SEM_MATCH'
STATUS_DIVERGENCIA_VALOR = 'DIVERGENCIA_VALOR'
STATUS_SEM_VENCIMENTO = 'SEM_VENCIMENTO'
STATUS_ERRO = 'ERRO'
STATUS_SEM_CPF = 'SEM_CPF'
STATUS_SEM_DIVIDAS = 'SEM_DIVIDAS'

TIPO_BUSCA_NOTURNO = 'MATCH_NOTURNO'
CACHE_LOCK_KEY = 'match_nio_noturno_lock'
CACHE_LOCK_TTL = 1140  # 19 min — um lote tem de caber no intervalo de 20 min
TOLERANCIA_VALOR = Decimal('0.05')
NUMERO_FATURA_MIN = 1
NUMERO_FATURA_MAX = 10


def parse_valor(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == '':
        return None
    if isinstance(raw, Decimal):
        return raw.quantize(Decimal('0.01'))
    if isinstance(raw, (int, float)):
        return Decimal(str(raw)).quantize(Decimal('0.01'))
    texto = str(raw).strip()
    if not texto:
        return None
    if ',' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    try:
        return Decimal(texto).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def parse_data_nio(raw: Any) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and len(raw) >= 8:
        try:
            s = raw[:10].replace('/', '-')
            if '-' in s and len(s) >= 10:
                return datetime.strptime(s[:10], '%Y-%m-%d').date()
            digits = re.sub(r'\D', '', raw)[:8]
            if len(digits) == 8:
                return datetime.strptime(digits, '%Y%m%d').date()
        except (TypeError, ValueError):
            return None
    return None


def valores_divergem(valor_crm: Any, valor_nio: Any) -> bool:
    """True só quando os dois valores existem (> 0) e diferem além da tolerância."""
    crm = parse_valor(valor_crm)
    nio = parse_valor(valor_nio)
    if crm is None or crm <= 0 or nio is None:
        return False
    return abs(crm - nio) > TOLERANCIA_VALOR


def fatura_liberada_para_consulta_nio(
    fatura: Any,
    *,
    hoje: Optional[date] = None,
    contrato: Any = None,
) -> bool:
    """True se a fatura 1–10 já deve existir na Nio hoje.

    Fatura 1: disponível ~3 dias após a instalação.
    Faturas 2–10: disponíveis 3 dias antes do vencimento (mês da competência).
    Sem data de disponibilidade, só consulta a partir do mês do vencimento.
    """
    ref = hoje or timezone.localdate()
    try:
        numero = int(getattr(fatura, 'numero_fatura', 0) or 0)
    except (TypeError, ValueError):
        return False
    if numero < NUMERO_FATURA_MIN or numero > NUMERO_FATURA_MAX:
        return False

    disp = getattr(fatura, 'data_disponibilidade', None)
    if disp is None and contrato is not None:
        calc = getattr(contrato, 'calcular_data_disponibilidade', None)
        if callable(calc):
            try:
                disp = calc(numero)
            except Exception:
                disp = None
    if disp is not None:
        return disp <= ref

    venc = getattr(fatura, 'data_vencimento', None)
    if venc is None and contrato is not None:
        calc_v = getattr(contrato, 'calcular_vencimento_fatura_n', None)
        if callable(calc_v):
            try:
                venc = calc_v(numero)
            except Exception:
                venc = None
    if venc is None:
        return False
    return (venc.year, venc.month) <= (ref.year, ref.month)


def normalizar_fatura_nio(inv: dict[str, Any]) -> dict[str, Any]:
    dv = parse_data_nio(
        inv.get('data_vencimento') or inv.get('due_date_raw') or inv.get('dueDate')
    )
    pix = (inv.get('codigo_pix') or inv.get('pix') or inv.get('originalPixCode') or '') or ''
    barras = (inv.get('codigo_barras') or inv.get('barcode') or inv.get('barCode') or '') or ''
    return {
        'data_vencimento': dv,
        'valor': inv.get('valor', inv.get('amount')),
        'codigo_pix': str(pix).strip(),
        'codigo_barras': str(barras).strip(),
        'invoice_id': str(inv.get('invoice_id') or inv.get('id') or ''),
        'debt_id': str(inv.get('debt_id') or ''),
        'mes_referencia': str(inv.get('mes_referencia') or inv.get('reference_month') or ''),
        'status_nio': str(inv.get('status_nio') or inv.get('status') or ''),
    }


def _chave_nio(item: dict[str, Any], idx: int) -> str:
    return item.get('invoice_id') or f'idx-{idx}-{item.get("data_vencimento")}'


def decidir_matches(
    faturas_crm: Sequence[Any],
    faturas_nio: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Decide match/ambíguo/divergência sem gravar nada.

    Regra: 1 fatura CRM e 1 fatura Nio com a **mesma data de vencimento**.
    Duas faturas (CRM ou Nio) no mesmo dia → AMBIGUO, não aplica.
    """
    nio_norm = [normalizar_fatura_nio(x) for x in faturas_nio]

    crm_por_data: dict[date, list[Any]] = defaultdict(list)
    nio_por_data: dict[date, list[tuple[int, dict[str, Any]]]] = defaultdict(list)

    decisoes: list[dict[str, Any]] = []
    sem_venc: list[Any] = []

    for fatura in faturas_crm:
        venc = getattr(fatura, 'data_vencimento', None)
        if not venc:
            sem_venc.append(fatura)
            continue
        crm_por_data[venc].append(fatura)

    for idx, item in enumerate(nio_norm):
        venc = item.get('data_vencimento')
        if venc:
            nio_por_data[venc].append((idx, item))

    datas_ambiguas = {
        d for d, lst in crm_por_data.items() if len(lst) > 1
    } | {
        d for d, lst in nio_por_data.items() if len(lst) > 1
    }

    for fatura in sem_venc:
        decisoes.append(_decisao(
            fatura,
            STATUS_SEM_VENCIMENTO,
            'Fatura sem data de vencimento no CRM — não casa automaticamente.',
        ))

    nio_usadas: set[str] = set()
    for fatura in faturas_crm:
        venc = getattr(fatura, 'data_vencimento', None)
        if not venc:
            continue
        if venc in datas_ambiguas:
            n_crm = len(crm_por_data.get(venc, []))
            n_nio = len(nio_por_data.get(venc, []))
            decisoes.append(_decisao(
                fatura,
                STATUS_AMBIGUO,
                (
                    f'Duas ou mais faturas na mesma data {venc.strftime("%d/%m/%Y")} '
                    f'(CRM: {n_crm}, Nio: {n_nio}). Match não aplicado.'
                ),
                nio=_primeiro_nio(nio_por_data.get(venc)),
            ))
            continue
        candidatos = nio_por_data.get(venc, [])
        if not candidatos:
            decisoes.append(_decisao(
                fatura,
                STATUS_SEM_MATCH,
                f'Sem fatura Nio com vencimento {venc.strftime("%d/%m/%Y")}.',
            ))
            continue
        _idx, nio = candidatos[0]
        chave = _chave_nio(nio, _idx)
        if chave in nio_usadas:
            decisoes.append(_decisao(
                fatura,
                STATUS_AMBIGUO,
                'Opção Nio já associada a outra fatura do contrato.',
                nio=nio,
            ))
            continue
        if valores_divergem(getattr(fatura, 'valor', None), nio.get('valor')):
            decisoes.append(_decisao(
                fatura,
                STATUS_DIVERGENCIA_VALOR,
                (
                    f'Valor CRM R$ {parse_valor(fatura.valor)} ≠ '
                    f'Nio R$ {parse_valor(nio.get("valor"))} na data '
                    f'{venc.strftime("%d/%m/%Y")}. Não aplicado.'
                ),
                nio=nio,
            ))
            continue
        nio_usadas.add(chave)
        decisoes.append(_decisao(
            fatura,
            STATUS_MATCH,
            f'Match único por vencimento {venc.strftime("%d/%m/%Y")}.',
            nio=nio,
            salvar=True,
        ))
    return decisoes


def _primeiro_nio(pares: Optional[list[tuple[int, dict[str, Any]]]]) -> Optional[dict[str, Any]]:
    if not pares:
        return None
    return pares[0][1]


def _decisao(
    fatura: Any,
    status: str,
    motivo: str,
    *,
    nio: Optional[dict[str, Any]] = None,
    salvar: bool = False,
) -> dict[str, Any]:
    venc_crm = getattr(fatura, 'data_vencimento', None)
    venc_nio = (nio or {}).get('data_vencimento')
    return {
        'fatura_id': getattr(fatura, 'id', None),
        'numero_fatura': getattr(fatura, 'numero_fatura', None),
        'status': status,
        'motivo': motivo,
        'salvar': bool(salvar),
        'vencimento_crm': venc_crm.isoformat() if venc_crm else '',
        'vencimento_nio': venc_nio.isoformat() if venc_nio else '',
        'valor_crm': str(getattr(fatura, 'valor', '') or ''),
        'valor_nio': str((nio or {}).get('valor') or ''),
        'nio': nio,
        'fatura': fatura,
    }


def aplicar_match_na_fatura(fatura: Any, nio: dict[str, Any]) -> list[str]:
    """Grava PIX, barras, valor (se vazio) e confirma vencimento. Retorna campos."""
    campos: list[str] = []
    pix = (nio.get('codigo_pix') or '').strip()
    barras = (nio.get('codigo_barras') or '').strip()
    if pix and pix != (getattr(fatura, 'codigo_pix', None) or ''):
        fatura.codigo_pix = pix
        campos.append('codigo_pix')
    if barras and barras != (getattr(fatura, 'codigo_barras', None) or ''):
        fatura.codigo_barras = barras[:100]
        campos.append('codigo_barras')
    valor_nio = parse_valor(nio.get('valor'))
    valor_crm = parse_valor(getattr(fatura, 'valor', None))
    if valor_nio is not None and valor_nio > 0 and (valor_crm is None or valor_crm <= 0):
        fatura.valor = valor_nio
        campos.append('valor')
    venc_nio = nio.get('data_vencimento')
    if venc_nio and getattr(fatura, 'data_vencimento', None) != venc_nio:
        fatura.data_vencimento = venc_nio
        campos.append('data_vencimento')
    if campos:
        campos.append('atualizado_em')
        fatura.status_busca = 'SUCESSO'
        fatura.erro_busca = None
        fatura.origem_busca = 'AUTOMATICA'
        fatura.ultima_busca_em = timezone.now()
        campos.extend(['status_busca', 'erro_busca', 'origem_busca', 'ultima_busca_em'])
        fatura.save(update_fields=list(dict.fromkeys(campos)))
    return [c for c in campos if c != 'atualizado_em']


def consultar_e_decidir_contrato(contrato: Any) -> dict[str, Any]:
    """Consulta a API Nio e decide matches das faturas abertas do contrato."""
    from crm_app.models import FaturaM10
    from crm_app.nio_api import consultar_dividas_nio

    cpf = re.sub(r'\D', '', str(getattr(contrato, 'cpf_cliente', None) or ''))
    if len(cpf) < 11:
        return {
            'ok': False,
            'status': STATUS_SEM_CPF,
            'motivo': 'CPF ausente ou inválido',
            'decisoes': [],
        }
    hoje = timezone.localdate()
    faturas = list(
        FaturaM10.objects.filter(
            contrato=contrato,
            numero_fatura__gte=NUMERO_FATURA_MIN,
            numero_fatura__lte=NUMERO_FATURA_MAX,
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO'],
        ).order_by('numero_fatura')
    )
    faturas = [
        f for f in faturas
        if fatura_liberada_para_consulta_nio(f, hoje=hoje, contrato=contrato)
    ]
    if not faturas:
        return {
            'ok': True,
            'status': 'AINDA_NAO_DISPONIVEL',
            'motivo': 'Nenhuma fatura 1–10 no mês/disponibilidade para consultar a Nio hoje',
            'decisoes': [],
        }

    try:
        api = consultar_dividas_nio(cpf, offset=0, limit=50, headless=True)
    except Exception as exc:
        logger.exception('[MatchNio] Falha API contrato=%s', getattr(contrato, 'id', None))
        return {
            'ok': False,
            'status': STATUS_ERRO,
            'motivo': str(exc)[:300],
            'decisoes': [],
        }
    if api.get('erro_400'):
        return {
            'ok': False,
            'status': STATUS_ERRO,
            'motivo': str(api.get('detail') or 'CPF não encontrado na Nio')[:300],
            'decisoes': [],
        }
    invoices = api.get('invoices') or []
    if not invoices:
        return {
            'ok': True,
            'status': STATUS_SEM_DIVIDAS,
            'motivo': 'CPF sem dívidas no momento na Nio',
            'decisoes': [
                _decisao(f, STATUS_SEM_DIVIDAS, 'CPF sem dívidas na Nio')
                for f in faturas
            ],
        }
    decisoes = decidir_matches(faturas, invoices)
    aplicadas = 0
    for dec in decisoes:
        if not dec.get('salvar'):
            fatura = dec.get('fatura')
            if fatura is not None:
                fatura.status_busca = 'ERRO' if dec['status'] != STATUS_MATCH else 'SUCESSO'
                fatura.erro_busca = dec['motivo'][:500]
                fatura.origem_busca = 'AUTOMATICA'
                fatura.ultima_busca_em = timezone.now()
                fatura.save(update_fields=[
                    'status_busca', 'erro_busca', 'origem_busca', 'ultima_busca_em',
                ])
            continue
        fatura = dec.get('fatura')
        nio = dec.get('nio') or {}
        if fatura is None:
            continue
        campos = aplicar_match_na_fatura(fatura, nio)
        dec['alteracoes'] = campos
        if campos:
            aplicadas += 1
        else:
            fatura.status_busca = 'SUCESSO'
            fatura.erro_busca = None
            fatura.origem_busca = 'AUTOMATICA'
            fatura.ultima_busca_em = timezone.now()
            fatura.save(update_fields=[
                'status_busca', 'erro_busca', 'origem_busca', 'ultima_busca_em',
            ])
    return {
        'ok': True,
        'status': 'OK',
        'motivo': '',
        'decisoes': decisoes,
        'aplicadas': aplicadas,
    }


def obter_segunda_via_atualizada(contrato: Any, fatura: Any) -> dict[str, Any]:
    """Consulta Nio na hora do clique «Quero a 2ª via» e devolve PIX fresco se único."""
    resultado = consultar_e_decidir_contrato(contrato)
    alvo_id = getattr(fatura, 'id', None)
    dec = next(
        (d for d in resultado.get('decisoes') or [] if d.get('fatura_id') == alvo_id),
        None,
    )
    if dec and dec.get('salvar') and dec.get('nio'):
        nio = dec['nio']
        fatura.refresh_from_db()
        return {
            'ok': True,
            'fonte': 'nio_fresco',
            'status': STATUS_MATCH,
            'motivo': dec.get('motivo') or '',
            'codigo_pix': nio.get('codigo_pix') or fatura.codigo_pix or '',
            'codigo_barras': nio.get('codigo_barras') or fatura.codigo_barras or '',
            'fatura': fatura,
        }
    pix_crm = (getattr(fatura, 'codigo_pix', None) or '').strip()
    barras_crm = (getattr(fatura, 'codigo_barras', None) or '').strip()
    return {
        'ok': bool(pix_crm or barras_crm),
        'fonte': 'crm',
        'status': (dec or {}).get('status') or resultado.get('status') or STATUS_ERRO,
        'motivo': (dec or {}).get('motivo') or resultado.get('motivo') or '',
        'codigo_pix': pix_crm,
        'codigo_barras': barras_crm,
        'fatura': fatura,
    }


def em_janela_noturna(agora: Optional[datetime] = None) -> bool:
    dt = timezone.localtime(agora) if agora else timezone.localtime()
    return dt.hour >= 22 or dt.hour < 7


def inicio_janela_noturna(agora: Optional[datetime] = None) -> datetime:
    dt = timezone.localtime(agora) if agora else timezone.localtime()
    base = dt.date()
    if dt.hour < 7:
        base = base - timedelta(days=1)
    naive = datetime.combine(base, time(22, 0))
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return naive


def queryset_contratos_pendentes_match():
    from crm_app.models import ContratoM10, FaturaM10
    from crm_app.services.qualidade_service import pode_tratar_contrato

    hoje = timezone.localdate()
    mes_fim = date(hoje.year, hoje.month, 28) + timedelta(days=4)
    mes_fim = mes_fim.replace(day=1) - timedelta(days=1)
    abertas_incompletas = FaturaM10.objects.filter(
        contrato_id=OuterRef('pk'),
        numero_fatura__gte=NUMERO_FATURA_MIN,
        numero_fatura__lte=NUMERO_FATURA_MAX,
        status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO'],
    ).filter(
        Q(codigo_pix__isnull=True)
        | Q(codigo_pix='')
        | Q(codigo_barras__isnull=True)
        | Q(codigo_barras='')
        | Q(valor__isnull=True)
        | Q(valor=0)
    ).filter(
        Q(data_disponibilidade__lte=hoje)
        | Q(data_disponibilidade__isnull=True, data_vencimento__lte=mes_fim)
    )
    qs = (
        ContratoM10.objects.filter(status_contrato='ATIVO')
        .exclude(Q(cpf_cliente__isnull=True) | Q(cpf_cliente=''))
        .filter(Exists(abertas_incompletas))
        .order_by('id')
        .select_related('venda')
    )
    return [c for c in qs if pode_tratar_contrato(c)]


def _resumo_de_decisoes(decisoes: list[dict[str, Any]]) -> dict[str, int]:
    resumo = {
        'match': 0,
        'ambiguo': 0,
        'sem_match': 0,
        'divergencia_valor': 0,
        'erro': 0,
        'outros': 0,
    }
    mapa = {
        STATUS_MATCH: 'match',
        STATUS_AMBIGUO: 'ambiguo',
        STATUS_SEM_MATCH: 'sem_match',
        STATUS_DIVERGENCIA_VALOR: 'divergencia_valor',
        STATUS_ERRO: 'erro',
        STATUS_SEM_DIVIDAS: 'sem_match',
        STATUS_SEM_VENCIMENTO: 'sem_match',
        STATUS_SEM_CPF: 'erro',
    }
    for d in decisoes:
        chave = mapa.get(d.get('status') or '', 'outros')
        resumo[chave] = resumo.get(chave, 0) + 1
    return resumo


def _detalhe_log(contrato: Any, dec: dict[str, Any]) -> dict[str, Any]:
    return {
        'contrato': getattr(contrato, 'numero_contrato', '') or '',
        'os': getattr(contrato, 'ordem_servico', '') or '',
        'cliente': (getattr(contrato, 'cliente_nome', None) or '')[:60],
        'fatura': dec.get('numero_fatura'),
        'status': dec.get('status'),
        'mensagem': dec.get('motivo') or '',
        'salvo': bool(dec.get('salvar')),
        'alteracoes': dec.get('alteracoes') or [],
        'vencimento_crm': dec.get('vencimento_crm') or '',
        'vencimento_nio': dec.get('vencimento_nio') or '',
    }


def processar_lote_match_noturno(*, limite: int = 30, forcar: bool = False) -> dict[str, Any]:
    """Processa um lote na janela 22h–7h e acumula relatório em HistoricoBuscaFatura."""
    from crm_app.models import HistoricoBuscaFatura

    agora = timezone.localtime()
    if not forcar and not em_janela_noturna(agora):
        return {'ok': True, 'pulado': True, 'motivo': 'fora da janela 22h–7h'}

    if not cache.add(CACHE_LOCK_KEY, '1', timeout=CACHE_LOCK_TTL):
        return {'ok': True, 'pulado': True, 'motivo': 'lote anterior ainda em execução'}

    try:
        inicio = inicio_janela_noturna(agora)
        historico = (
            HistoricoBuscaFatura.objects.filter(
                tipo_busca=TIPO_BUSCA_NOTURNO,
                inicio_em__gte=inicio,
            )
            .order_by('id')
            .first()
        )
        if historico is None:
            historico = HistoricoBuscaFatura.objects.create(
                tipo_busca=TIPO_BUSCA_NOTURNO,
                status='EM_ANDAMENTO',
                mensagem='Match noturno Nio iniciado (22h–7h)',
                logs={'progresso': {}, 'detalhes': [], 'contratos_ids': [], 'resumo': {}},
            )
        elif historico.status == 'CONCLUIDA':
            historico.status = 'EM_ANDAMENTO'
            historico.save(update_fields=['status'])

        logs = historico.logs if isinstance(historico.logs, dict) else {}
        vistos: list[int] = list(logs.get('contratos_ids') or [])
        detalhes: list[dict[str, Any]] = list(logs.get('detalhes') or [])
        resumo = logs.get('resumo') or {}

        pendentes = [
            c for c in queryset_contratos_pendentes_match()
            if c.id not in set(vistos)
        ]
        lote = pendentes[: max(1, int(limite))]
        processados = 0
        for contrato in lote:
            vistos.append(contrato.id)
            processados += 1
            resultado = consultar_e_decidir_contrato(contrato)
            decisoes = resultado.get('decisoes') or []
            if not decisoes and not resultado.get('ok'):
                detalhes.append({
                    'contrato': contrato.numero_contrato or '',
                    'os': contrato.ordem_servico or '',
                    'cliente': (contrato.cliente_nome or '')[:60],
                    'status': resultado.get('status') or STATUS_ERRO,
                    'mensagem': resultado.get('motivo') or 'Falha na consulta Nio',
                    'salvo': False,
                })
                resumo['erro'] = int(resumo.get('erro') or 0) + 1
            for dec in decisoes:
                item = _detalhe_log(contrato, dec)
                detalhes.append(item)
                parte = _resumo_de_decisoes([dec])
                for k, v in parte.items():
                    resumo[k] = int(resumo.get(k) or 0) + v
            historico.total_contratos = len(vistos)
            historico.total_faturas = int(resumo.get('match') or 0) + int(resumo.get('ambiguo') or 0) + int(
                resumo.get('sem_match') or 0
            ) + int(resumo.get('divergencia_valor') or 0) + int(resumo.get('erro') or 0)
            historico.faturas_sucesso = int(resumo.get('match') or 0)
            historico.faturas_erro = (
                int(resumo.get('ambiguo') or 0)
                + int(resumo.get('sem_match') or 0)
                + int(resumo.get('divergencia_valor') or 0)
                + int(resumo.get('erro') or 0)
            )
            historico.mensagem = (
                f'Match {resumo.get("match") or 0} · ambíguo {resumo.get("ambiguo") or 0} · '
                f'sem match {resumo.get("sem_match") or 0} · divergência {resumo.get("divergencia_valor") or 0}'
            )
            historico.logs = {
                'progresso': {
                    'contratos_feitos': len(vistos),
                    'contratos_total': len(vistos) + max(0, len(pendentes) - processados),
                    'ultimo_contrato': contrato.numero_contrato or str(contrato.id),
                },
                'detalhes': detalhes[-250:],
                'contratos_ids': vistos[-4000:],
                'resumo': resumo,
            }
            historico.save(update_fields=[
                'total_contratos', 'total_faturas', 'faturas_sucesso',
                'faturas_erro', 'mensagem', 'logs',
            ])

        restam = max(0, len(pendentes) - processados)
        if restam == 0:
            historico.status = 'CONCLUIDA'
            historico.termino_em = timezone.now()
            if historico.inicio_em:
                historico.duracao_segundos = (
                    historico.termino_em - historico.inicio_em
                ).total_seconds()
            historico.mensagem = (historico.mensagem or '') + ' · janela concluída ou sem pendentes'
            historico.save(update_fields=[
                'status', 'termino_em', 'duracao_segundos', 'mensagem',
            ])

        return {
            'ok': True,
            'historico_id': historico.id,
            'processados': processados,
            'restam': restam,
            'resumo': resumo,
        }
    finally:
        cache.delete(CACHE_LOCK_KEY)


def finalizar_janela_noturna() -> dict[str, Any]:
    """Fecha o histórico da noite às 7h, mesmo se ainda houver pendentes."""
    from crm_app.models import HistoricoBuscaFatura

    inicio = inicio_janela_noturna()
    qs = HistoricoBuscaFatura.objects.filter(
        tipo_busca=TIPO_BUSCA_NOTURNO,
        inicio_em__gte=inicio,
        status='EM_ANDAMENTO',
    )
    n = 0
    for h in qs:
        h.status = 'CONCLUIDA'
        h.termino_em = timezone.now()
        if h.inicio_em:
            h.duracao_segundos = (h.termino_em - h.inicio_em).total_seconds()
        h.mensagem = (h.mensagem or '') + ' · encerrado às 07:00'
        h.save(update_fields=['status', 'termino_em', 'duracao_segundos', 'mensagem'])
        n += 1
    return {'ok': True, 'finalizados': n}


def ultimo_relatorio_match_noturno() -> dict[str, Any]:
    from crm_app.models import HistoricoBuscaFatura

    h = (
        HistoricoBuscaFatura.objects.filter(tipo_busca=TIPO_BUSCA_NOTURNO)
        .order_by('-inicio_em')
        .first()
    )
    if not h:
        return {
            'existe': False,
            'mensagem': 'Nenhuma execução do match noturno ainda.',
        }
    logs = h.logs if isinstance(h.logs, dict) else {}
    return {
        'existe': True,
        'id': h.id,
        'status': h.status,
        'inicio_em': h.inicio_em.isoformat() if h.inicio_em else '',
        'termino_em': h.termino_em.isoformat() if h.termino_em else '',
        'mensagem': h.mensagem or '',
        'resumo': logs.get('resumo') or {},
        'progresso': logs.get('progresso') or {},
        'detalhes': (logs.get('detalhes') or [])[-40:],
        'faturas_sucesso': h.faturas_sucesso,
        'faturas_erro': h.faturas_erro,
        'total_contratos': h.total_contratos,
    }
