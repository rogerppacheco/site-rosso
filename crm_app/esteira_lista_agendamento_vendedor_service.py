"""Lista diária de agendamentos ao vendedor: imagem + ciência / pedido de reagendar (WhatsApp)."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from django.utils import timezone

from crm_app.esteira_posso_antecipar_service import (
    _chaves_telefone_busca,
    _extrair_message_id_resposta_zapi,
    _extrair_reference_message_id_zapi,
    _normalizar_telefone_chave,
    telefone_vendedor_para_envio_sistema,
)
from crm_app.esteira_posso_reagendar_service import gerar_tres_datas_opcao

logger = logging.getLogger(__name__)

HORAS_LIMITE_SESSAO = 72
PREFIXO_BOTAO = 'la_'
SLOT_MANHA = 'MANHA'
SLOT_TARDE = 'TARDE'


def formatar_lista_agendamento_exibicao(venda) -> str:
    """Texto/badge da coluna na esteira."""
    status = (getattr(venda, 'vendedor_lista_agendamento_status', None) or '').strip().upper()
    if status == 'CIENTE':
        return 'Ciente'
    if status == 'REAGENDAR':
        d = getattr(venda, 'vendedor_lista_reagendar_data', None)
        t = getattr(venda, 'vendedor_lista_reagendar_turno', None)
        turno = 'Manhã' if t == 'MANHA' else ('Tarde' if t == 'TARDE' else '')
        if d and turno:
            return f'Reagendar — {d.strftime("%d/%m")} {turno}'
        if d:
            return f'Reagendar — {d.strftime("%d/%m")}'
        return 'Reagendar'
    if (
        getattr(venda, 'data_envio_lista_agendamento', None)
        and not getattr(venda, 'data_resposta_lista_agendamento', None)
    ):
        return 'Aguardando'
    resp = (getattr(venda, 'vendedor_lista_agendamento_resposta', None) or '').strip()
    if resp:
        return resp[:80]
    return '-'


def _ids_do_envio(envio) -> list[int]:
    try:
        raw = json.loads(envio.venda_ids_json or '[]')
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    out: list[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _formatar_data_botao(d: date) -> str:
    dias = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
    return f'{dias[d.weekday()]} {d.strftime("%d/%m")}'


def _label_pedido_botao(venda) -> str:
    os_txt = (getattr(venda, 'ordem_servico', None) or '').strip()
    if os_txt:
        return f'OS {os_txt}'[:20]
    return f'#{venda.id}'[:20]


def montar_botoes_iniciais(envio_id: int) -> list[dict[str, str]]:
    eid = int(envio_id)
    return [
        {'id': f'{PREFIXO_BOTAO}{eid}_ciente', 'type': 'REPLY', 'label': 'Estou ciente'},
        {'id': f'{PREFIXO_BOTAO}{eid}_reagendar', 'type': 'REPLY', 'label': 'Reagendar pedido'},
    ]


def montar_botoes_datas(envio_id: int, datas: list[date]) -> list[dict[str, str]]:
    eid = int(envio_id)
    return [
        {
            'id': f'{PREFIXO_BOTAO}{eid}_dt_{d.strftime("%Y%m%d")}',
            'type': 'REPLY',
            'label': _formatar_data_botao(d)[:20],
        }
        for d in datas[:3]
    ]


def montar_botoes_turno(envio_id: int) -> list[dict[str, str]]:
    eid = int(envio_id)
    return [
        {'id': f'{PREFIXO_BOTAO}{eid}_manha', 'type': 'REPLY', 'label': 'Manhã'},
        {'id': f'{PREFIXO_BOTAO}{eid}_tarde', 'type': 'REPLY', 'label': 'Tarde'},
    ]


def parse_button_id_lista_agendamento(button_id: str) -> Optional[dict[str, Any]]:
    """
    la_{envio_id}_ciente|reagendar|mais|manha|tarde|ped_{venda_id}|dt_YYYYMMDD
    """
    bid = (button_id or '').strip()
    m = re.match(
        rf'^{PREFIXO_BOTAO}(\d+)_(ciente|reagendar|mais|manha|tarde)$',
        bid,
        re.IGNORECASE,
    )
    if m:
        eid = int(m.group(1))
        acao = m.group(2).lower()
        if acao == 'ciente':
            return {'envio_id': eid, 'acao': 'ciente'}
        if acao == 'reagendar':
            return {'envio_id': eid, 'acao': 'reagendar'}
        if acao == 'mais':
            return {'envio_id': eid, 'acao': 'mais'}
        if acao == 'manha':
            return {'envio_id': eid, 'acao': 'turno', 'turno': 'MANHA'}
        return {'envio_id': eid, 'acao': 'turno', 'turno': 'TARDE'}

    m_ped = re.match(rf'^{PREFIXO_BOTAO}(\d+)_ped_(\d+)$', bid, re.IGNORECASE)
    if m_ped:
        return {
            'envio_id': int(m_ped.group(1)),
            'acao': 'pedido',
            'venda_id': int(m_ped.group(2)),
        }

    m_dt = re.match(rf'^{PREFIXO_BOTAO}(\d+)_dt_(\d{{8}})$', bid, re.IGNORECASE)
    if m_dt:
        ds = m_dt.group(2)
        try:
            data_escolhida = date(int(ds[0:4]), int(ds[4:6]), int(ds[6:8]))
        except (TypeError, ValueError):
            return None
        return {'envio_id': int(m_dt.group(1)), 'acao': 'data', 'data': data_escolhida}
    return None


def _enviar_botoes(telefone: str, mensagem: str, botoes: list, footer: str = '') -> tuple[bool, str]:
    from crm_app.whatsapp_service import WhatsAppService

    ok, resp = WhatsAppService().enviar_mensagem_com_botoes_reply(
        telefone, mensagem, botoes, footer=footer,
    )
    return bool(ok), _extrair_message_id_resposta_zapi(resp)


def _enviar_texto(telefone: str, mensagem: str) -> bool:
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.whatsapp_webhook_handler import formatar_telefone

    tel = formatar_telefone(telefone)
    if not tel:
        return False
    ok, _ = WhatsAppService().enviar_mensagem_texto(tel, mensagem, variar=False)
    return bool(ok)


def _enviar_imagem(telefone: str, img_b64: str, caption: str = '') -> bool:
    from crm_app.whatsapp_service import WhatsAppService

    resp = WhatsAppService().enviar_imagem_b64(telefone, img_b64, caption=caption)
    return bool(resp)


def consultar_vendas_do_turno(
    *,
    data_ref: date,
    periodo: str,
    vendedor_id: Optional[int] = None,
):
    from crm_app.models import Venda

    qs = (
        Venda.objects.filter(
            data_agendamento=data_ref,
            periodo_agendamento=periodo,
            vendedor_id__isnull=False,
        )
        .select_related('cliente', 'vendedor', 'status_agendamento')
        .order_by('vendedor_id', 'id')
    )
    if vendedor_id:
        qs = qs.filter(vendedor_id=vendedor_id)
    return qs


def gerar_imagem_lista_agendamento_b64(
    vendas: list,
    *,
    data_ref: date,
    periodo: str,
) -> Optional[str]:
    """Gera PNG base64 (data URL) no padrão da tabela anexa."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error('Pillow não disponível para gerar imagem da lista de agendamento.')
        return None

    from crm_app.whatsapp_service import WhatsAppService

    turno_txt = 'MANHÃ' if periodo == SLOT_MANHA else 'TARDE'
    data_turno = f'{data_ref.strftime("%d/%m")} - {turno_txt}'

    linhas: list[dict[str, str]] = []
    for v in vendas:
        nome = ''
        if getattr(v, 'cliente', None):
            nome = (v.cliente.nome_razao_social or '').strip()
        os_txt = (getattr(v, 'ordem_servico', None) or '').strip() or '—'
        status_nome = ''
        if getattr(v, 'status_agendamento', None):
            status_nome = (v.status_agendamento.nome or '').strip()
        linhas.append({
            'cliente': (nome or '—').upper(),
            'pedido': os_txt.upper(),
            'data_turno': data_turno,
            'status': (status_nome or '—').upper(),
        })

    svc = WhatsAppService()
    f_header = svc._font_performance('arial', 18)
    f_cell = svc._font_performance('arial', 16)

    W = 980
    H_HEADER = 44
    H_LINHA = 40
    PAD = 12
    H = PAD + H_HEADER + (max(len(linhas), 1) * H_LINHA) + PAD

    # Colunas: cliente | pedido | data-turno | status
    col_w = [320, 180, 200, 240]
    col_x = [PAD + 8]
    for w in col_w[:-1]:
        col_x.append(col_x[-1] + w)

    cor_fundo = (255, 255, 255)
    cor_header = (33, 37, 41)
    cor_texto = (33, 37, 41)
    cor_borda = (180, 180, 180)
    cor_zebra = (248, 249, 250)

    img = Image.new('RGB', (W, H), color=cor_fundo)
    d = ImageDraw.Draw(img)

    y = PAD
    d.rectangle([(PAD, y), (W - PAD, y + H_HEADER)], outline=cor_borda, width=1)
    headers = ['NOME DO CLIENTE', 'PEDIDO', 'DATA - TURNO', 'STATUS AGENDAMENTO']
    for i, titulo in enumerate(headers):
        d.text((col_x[i], y + H_HEADER // 2), titulo, fill=cor_header, anchor='lm', font=f_header)
    y += H_HEADER

    if not linhas:
        d.rectangle([(PAD, y), (W - PAD, y + H_LINHA)], outline=cor_borda, width=1)
        d.text((W / 2, y + H_LINHA // 2), 'SEM AGENDAMENTOS', fill=cor_texto, anchor='mm', font=f_cell)
    else:
        for idx, row in enumerate(linhas):
            bg = cor_zebra if idx % 2 else cor_fundo
            d.rectangle([(PAD, y), (W - PAD, y + H_LINHA)], fill=bg, outline=cor_borda, width=1)
            vals = [row['cliente'][:34], row['pedido'][:22], row['data_turno'], row['status'][:28]]
            for i, val in enumerate(vals):
                d.text((col_x[i], y + H_LINHA // 2), val, fill=cor_texto, anchor='lm', font=f_cell)
            y += H_LINHA

    buffered = io.BytesIO()
    img.save(buffered, format='PNG')
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{img_str}'


def _ja_enviado_hoje(vendedor_id: int, data_ref: date, periodo: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorEnviado

    return ListaAgendamentoVendedorEnviado.objects.filter(
        vendedor_id=vendedor_id,
        data_referencia=data_ref,
        periodo=periodo,
    ).exists()


def _montar_botoes_pedidos(envio_id: int, vendas: list, offset: int) -> tuple[list[dict[str, str]], int]:
    """
    Páginas de pedidos (máx. 3 botões WhatsApp).
    Se há mais itens após a página: 2 pedidos + 'Próximos'; senão até 3 pedidos.
    Retorna (botoes, novo_offset).
    """
    eid = int(envio_id)
    restantes = vendas[offset:]
    if not restantes:
        return [], offset

    tem_mais = len(restantes) > 3
    if tem_mais:
        pagina = restantes[:2]
        botoes = [
            {
                'id': f'{PREFIXO_BOTAO}{eid}_ped_{v.id}',
                'type': 'REPLY',
                'label': _label_pedido_botao(v),
            }
            for v in pagina
        ]
        botoes.append({'id': f'{PREFIXO_BOTAO}{eid}_mais', 'type': 'REPLY', 'label': 'Próximos'})
        return botoes, offset + 2

    pagina = restantes[:3]
    botoes = [
        {
            'id': f'{PREFIXO_BOTAO}{eid}_ped_{v.id}',
            'type': 'REPLY',
            'label': _label_pedido_botao(v),
        }
        for v in pagina
    ]
    return botoes, offset + len(pagina)


def _vendas_do_envio(envio):
    from crm_app.models import Venda

    ids = _ids_do_envio(envio)
    if not ids:
        return []
    by_id = {
        v.id: v
        for v in Venda.objects.filter(id__in=ids).select_related('cliente', 'status_agendamento')
    }
    return [by_id[i] for i in ids if i in by_id]


def _enviar_escolha_pedidos(sessao, telefone: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorSessao

    vendas = _vendas_do_envio(sessao.envio)
    if not vendas:
        _enviar_texto(telefone, 'Não há pedidos neste envio para reagendar.')
        return False

    offset = int(sessao.offset_pedidos or 0)
    if offset >= len(vendas):
        offset = 0
        sessao.offset_pedidos = 0

    botoes, _ = _montar_botoes_pedidos(sessao.envio_id, vendas, offset)
    if not botoes:
        _enviar_texto(telefone, 'Não há mais pedidos nesta lista.')
        return False

    pagina_atual = (offset // 2) + 1 if len(vendas) > 3 else 1
    total_paginas = max(1, (len(vendas) + 1) // 2) if len(vendas) > 3 else 1
    msg = (
        f'Qual pedido deseja *reagendar*?\n'
        f'(página {pagina_atual}'
        + (f' de ~{total_paginas}' if total_paginas > 1 else '')
        + ')\n\nToque no botão da O.S. correspondente.'
    )
    ok, msg_id = _enviar_botoes(telefone, msg, botoes, footer='Reagendar pedido')
    if not ok:
        return False

    sessao.etapa = ListaAgendamentoVendedorSessao.ETAPA_ESCOLHER_PEDIDO
    update_fields = ['etapa', 'atualizado_em']
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        update_fields.append('whatsapp_message_id')
    sessao.save(update_fields=update_fields)
    return True


def enviar_lista_para_vendedor(
    vendedor,
    vendas: list,
    *,
    data_ref: date,
    periodo: str,
) -> dict[str, Any]:
    """Envia imagem + botões a um vendedor. Não envia se lista vazia."""
    from crm_app.models import ListaAgendamentoVendedorEnviado, ListaAgendamentoVendedorSessao, Venda

    resultado: dict[str, Any] = {'ok': False, 'enviado': False, 'detail': ''}
    if not vendas:
        resultado['detail'] = 'Sem pedidos.'
        return resultado

    telefone, err = telefone_vendedor_para_envio_sistema(vendas[0])
    if not telefone:
        # Fallback: usar tel do vendedor passado (mesmo critério do helper)
        tel = (getattr(vendedor, 'tel_whatsapp', None) or '').strip()
        if not tel:
            resultado['detail'] = err or 'Vendedor sem WhatsApp.'
            return resultado
        telefone = tel

    if _ja_enviado_hoje(vendedor.id, data_ref, periodo):
        resultado['ok'] = True
        resultado['detail'] = 'Já enviado neste turno.'
        return resultado

    img_b64 = gerar_imagem_lista_agendamento_b64(vendas, data_ref=data_ref, periodo=periodo)
    if not img_b64:
        resultado['detail'] = 'Falha ao gerar imagem.'
        return resultado

    turno_txt = 'manhã' if periodo == SLOT_MANHA else 'tarde'
    caption = (
        f'Seus agendamentos de *{data_ref.strftime("%d/%m/%Y")}* ({turno_txt}) — '
        f'{len(vendas)} pedido(s).'
    )
    if not _enviar_imagem(telefone, img_b64, caption=caption):
        resultado['detail'] = 'Falha ao enviar imagem.'
        return resultado

    tel_chave = _normalizar_telefone_chave(telefone) or telefone
    envio = ListaAgendamentoVendedorEnviado.objects.create(
        telefone=tel_chave,
        vendedor=vendedor,
        data_referencia=data_ref,
        periodo=periodo,
        venda_ids_json=json.dumps([v.id for v in vendas]),
    )

    msg_botoes = (
        'Confirme a ciência dos agendamentos ou solicite reagendar um pedido.\n\n'
        'Toque em um dos botões abaixo:'
    )
    ok_btn, msg_id = _enviar_botoes(
        telefone,
        msg_botoes,
        montar_botoes_iniciais(envio.id),
        footer=f'{data_ref.strftime("%d/%m")} {turno_txt}',
    )
    if not ok_btn:
        resultado['detail'] = 'Imagem enviada, mas falha nos botões.'
        # Mantém o log; sessão não criada
        return resultado

    if msg_id:
        envio.whatsapp_message_id = msg_id
        envio.save(update_fields=['whatsapp_message_id'])

    ListaAgendamentoVendedorSessao.objects.create(
        envio=envio,
        telefone=tel_chave,
        vendedor=vendedor,
        etapa=ListaAgendamentoVendedorSessao.ETAPA_INICIAL,
        whatsapp_message_id=msg_id or '',
    )

    agora = timezone.now()
    Venda.objects.filter(id__in=[v.id for v in vendas]).update(
        data_envio_lista_agendamento=agora,
        vendedor_lista_agendamento_status=None,
        vendedor_lista_reagendar_data=None,
        vendedor_lista_reagendar_turno=None,
        vendedor_lista_agendamento_resposta=None,
        data_resposta_lista_agendamento=None,
    )

    resultado['ok'] = True
    resultado['enviado'] = True
    resultado['detail'] = f'Enviado a {getattr(vendedor, "username", vendedor.id)} ({len(vendas)} pedidos).'
    logger.info(
        '[ListaAgendamento] Enviado vendedor=%s periodo=%s qtd=%s messageId=%s',
        getattr(vendedor, 'username', vendedor.id),
        periodo,
        len(vendas),
        msg_id or '-',
    )
    return resultado


def processar_disparo_lista_agendamento(periodo: str) -> dict[str, Any]:
    """Job do scheduler: agrupa por vendedor e dispara."""
    periodo = (periodo or '').upper()
    if periodo not in (SLOT_MANHA, SLOT_TARDE):
        return {'ok': False, 'detail': 'Período inválido.', 'enviados': 0}

    data_ref = timezone.localdate()
    vendas = list(consultar_vendas_do_turno(data_ref=data_ref, periodo=periodo))
    if not vendas:
        logger.info('[ListaAgendamento] Sem vendas para %s %s', data_ref, periodo)
        return {'ok': True, 'detail': 'Sem vendas.', 'enviados': 0}

    por_vendedor: dict[int, list] = {}
    for v in vendas:
        por_vendedor.setdefault(v.vendedor_id, []).append(v)

    enviados = 0
    erros: list[str] = []
    for _vid, lista in por_vendedor.items():
        vendedor = lista[0].vendedor
        try:
            res = enviar_lista_para_vendedor(
                vendedor, lista, data_ref=data_ref, periodo=periodo,
            )
            if res.get('enviado'):
                enviados += 1
            elif not res.get('ok'):
                erros.append(res.get('detail') or 'erro')
        except Exception as exc:
            logger.exception('[ListaAgendamento] Erro vendedor=%s', _vid)
            erros.append(str(exc))

    return {
        'ok': True,
        'detail': f'Enviados={enviados}, erros={len(erros)}',
        'enviados': enviados,
        'erros': erros,
    }


def _sessao_ativa_qs(telefone: str = ''):
    from crm_app.models import ListaAgendamentoVendedorSessao

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_SESSAO)
    qs = ListaAgendamentoVendedorSessao.objects.filter(
        finalizado_em__isnull=True,
        criado_em__gte=limite,
    ).exclude(
        etapa__in=(
            ListaAgendamentoVendedorSessao.ETAPA_CIENTE,
            ListaAgendamentoVendedorSessao.ETAPA_CONCLUIDO,
        )
    )
    if telefone:
        chaves = _chaves_telefone_busca(telefone)
        if chaves:
            qs = qs.filter(telefone__in=chaves)
    return qs.select_related('envio', 'vendedor', 'venda_escolhida')


def buscar_sessao_por_mensagem_whatsapp(reference_message_id: str, telefone: str = ''):
    from crm_app.models import ListaAgendamentoVendedorSessao

    ref = (reference_message_id or '').strip()
    if not ref:
        return None
    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_SESSAO)
    qs = ListaAgendamentoVendedorSessao.objects.filter(
        whatsapp_message_id=ref,
        criado_em__gte=limite,
        finalizado_em__isnull=True,
    ).select_related('envio', 'vendedor', 'venda_escolhida')
    if telefone:
        chaves = _chaves_telefone_busca(telefone)
        if chaves:
            qs = qs.filter(telefone__in=chaves)
    return qs.order_by('-criado_em').first()


def buscar_sessao_por_envio(envio_id: int, telefone: str = ''):
    if not envio_id:
        return None
    return (
        _sessao_ativa_qs(telefone)
        .filter(envio_id=int(envio_id))
        .order_by('-criado_em')
        .first()
    )


def deve_tentar_lista_agendamento(
    mensagem_texto: str,
    *,
    button_id: str = '',
    reference_message_id: str = '',
    telefone: str = '',
) -> bool:
    if button_id and (
        button_id.startswith(PREFIXO_BOTAO) or parse_button_id_lista_agendamento(button_id)
    ):
        return True
    ref = (reference_message_id or '').strip()
    if ref and telefone and buscar_sessao_por_mensagem_whatsapp(ref, telefone):
        return True
    return False


def _marcar_vendas_ciente(envio, agora: datetime) -> None:
    from crm_app.models import Venda

    ids = _ids_do_envio(envio)
    if not ids:
        return
    Venda.objects.filter(id__in=ids).update(
        vendedor_lista_agendamento_status=Venda.STATUS_LISTA_AGENDAMENTO_CIENTE,
        vendedor_lista_agendamento_resposta='Estou ciente',
        data_resposta_lista_agendamento=agora,
        vendedor_lista_reagendar_data=None,
        vendedor_lista_reagendar_turno=None,
    )


def _marcar_venda_reagendar(venda, data_esc: date, turno: str, agora: datetime) -> str:
    from crm_app.models import Venda

    turno_txt = 'Manhã' if turno == 'MANHA' else 'Tarde'
    resumo = f'Solicitou reagendar — {data_esc.strftime("%d/%m/%Y")} ({turno_txt})'
    venda.vendedor_lista_agendamento_status = Venda.STATUS_LISTA_AGENDAMENTO_REAGENDAR
    venda.vendedor_lista_reagendar_data = data_esc
    venda.vendedor_lista_reagendar_turno = turno
    venda.vendedor_lista_agendamento_resposta = resumo
    venda.data_resposta_lista_agendamento = agora
    venda.save(update_fields=[
        'vendedor_lista_agendamento_status',
        'vendedor_lista_reagendar_data',
        'vendedor_lista_reagendar_turno',
        'vendedor_lista_agendamento_resposta',
        'data_resposta_lista_agendamento',
    ])
    return resumo


def _finalizar_sessao(sessao, etapa_final: str) -> None:
    agora = timezone.now()
    sessao.etapa = etapa_final
    sessao.finalizado_em = agora
    sessao.save(update_fields=['etapa', 'finalizado_em', 'atualizado_em'])
    envio = sessao.envio
    if not envio.respondido_em:
        envio.respondido_em = agora
        envio.save(update_fields=['respondido_em'])


def _etapa_inicial(sessao, parsed: dict, telefone: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorSessao

    if parsed.get('acao') == 'ciente':
        agora = timezone.now()
        _marcar_vendas_ciente(sessao.envio, agora)
        _finalizar_sessao(sessao, ListaAgendamentoVendedorSessao.ETAPA_CIENTE)
        _enviar_texto(telefone, 'Ciência registrada para os agendamentos desta lista. Obrigado!')
        return True

    if parsed.get('acao') == 'reagendar':
        vendas = _vendas_do_envio(sessao.envio)
        if len(vendas) == 1:
            sessao.venda_escolhida = vendas[0]
            sessao.etapa = ListaAgendamentoVendedorSessao.ETAPA_DATA
            sessao.save(update_fields=['venda_escolhida', 'etapa', 'atualizado_em'])
            return _enviar_opcoes_data(sessao, telefone)
        sessao.offset_pedidos = 0
        sessao.save(update_fields=['offset_pedidos', 'atualizado_em'])
        return _enviar_escolha_pedidos(sessao, telefone)

    return False


def _enviar_opcoes_data(sessao, telefone: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorSessao

    datas = gerar_tres_datas_opcao()
    venda = sessao.venda_escolhida
    os_txt = (getattr(venda, 'ordem_servico', None) or '').strip() or f'#{venda.id}'
    msg = (
        f'Pedido O.S. *{os_txt}*: em qual dia deseja *reagendar*?\n\n'
        'Escolha uma das 3 datas:'
    )
    ok, msg_id = _enviar_botoes(
        telefone,
        msg,
        montar_botoes_datas(sessao.envio_id, datas),
        footer=f'O.S. {os_txt}'[:60],
    )
    if not ok:
        _enviar_texto(telefone, 'Não consegui enviar as datas. Tente novamente ou avise o backoffice.')
        return True
    sessao.etapa = ListaAgendamentoVendedorSessao.ETAPA_DATA
    update_fields = ['etapa', 'atualizado_em']
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        update_fields.append('whatsapp_message_id')
    sessao.save(update_fields=update_fields)
    return True


def _etapa_escolher_pedido(sessao, parsed: dict, telefone: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorSessao, Venda

    if parsed.get('acao') == 'mais':
        vendas = _vendas_do_envio(sessao.envio)
        # Avança pelo mesmo critério de página (2 itens quando há "Próximos")
        offset = int(sessao.offset_pedidos or 0)
        restantes = len(vendas) - offset
        if restantes > 3:
            sessao.offset_pedidos = offset + 2
        else:
            sessao.offset_pedidos = offset + min(3, max(restantes, 0))
        sessao.save(update_fields=['offset_pedidos', 'atualizado_em'])
        return _enviar_escolha_pedidos(sessao, telefone)

    if parsed.get('acao') != 'pedido':
        return False
    venda_id = parsed.get('venda_id')
    ids = set(_ids_do_envio(sessao.envio))
    if not venda_id or venda_id not in ids:
        _enviar_texto(telefone, 'Pedido inválido para esta lista.')
        return True
    venda = Venda.objects.filter(id=venda_id).first()
    if not venda:
        _enviar_texto(telefone, 'Pedido não encontrado.')
        return True
    sessao.venda_escolhida = venda
    sessao.save(update_fields=['venda_escolhida', 'atualizado_em'])
    return _enviar_opcoes_data(sessao, telefone)


def _etapa_data(sessao, parsed: dict, telefone: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorSessao

    if parsed.get('acao') != 'data':
        return False
    data_esc = parsed.get('data')
    if not data_esc:
        return False
    sessao.data_escolhida = data_esc
    sessao.etapa = ListaAgendamentoVendedorSessao.ETAPA_TURNO
    sessao.save(update_fields=['data_escolhida', 'etapa', 'atualizado_em'])

    os_txt = ''
    if sessao.venda_escolhida_id:
        os_txt = (getattr(sessao.venda_escolhida, 'ordem_servico', None) or '').strip()
        if not os_txt:
            os_txt = f'#{sessao.venda_escolhida_id}'
    msg = (
        f'O.S. *{os_txt or "—"}*: para *{data_esc.strftime("%d/%m/%Y")}*, qual turno?'
    )
    ok, msg_id = _enviar_botoes(
        telefone,
        msg,
        montar_botoes_turno(sessao.envio_id),
        footer='Turno',
    )
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        sessao.save(update_fields=['whatsapp_message_id', 'atualizado_em'])
    return bool(ok)


def _etapa_turno(sessao, parsed: dict, telefone: str) -> bool:
    from crm_app.models import ListaAgendamentoVendedorSessao

    if parsed.get('acao') != 'turno':
        return False
    turno = parsed.get('turno')
    if turno not in ('MANHA', 'TARDE') or not sessao.venda_escolhida_id or not sessao.data_escolhida:
        return False

    agora = timezone.now()
    sessao.periodo_escolhido = turno
    sessao.save(update_fields=['periodo_escolhido', 'atualizado_em'])
    resumo = _marcar_venda_reagendar(
        sessao.venda_escolhida, sessao.data_escolhida, turno, agora,
    )
    _finalizar_sessao(sessao, ListaAgendamentoVendedorSessao.ETAPA_CONCLUIDO)
    os_txt = (getattr(sessao.venda_escolhida, 'ordem_servico', None) or '').strip() or f'#{sessao.venda_escolhida_id}'
    _enviar_texto(
        telefone,
        f'Solicitação registrada para O.S. *{os_txt}*: *{resumo}*.\n'
        'O agendamento no CRM *não foi alterado* — a equipe irá analisar.',
    )
    return True


def processar_resposta_lista_agendamento(
    telefone_remetente,
    mensagem_texto,
    *,
    button_id: str = '',
    reference_message_id: str = '',
) -> bool:
    if not deve_tentar_lista_agendamento(
        mensagem_texto or '',
        button_id=button_id,
        reference_message_id=reference_message_id,
        telefone=telefone_remetente,
    ):
        return False

    parsed = parse_button_id_lista_agendamento(button_id) if button_id else None
    ref = (reference_message_id or '').strip()

    logger.info(
        '[ListaAgendamento] Processando tel=%s btn=%r ref=%r',
        telefone_remetente,
        button_id or '-',
        ref or '-',
    )

    sessao = None
    if ref:
        sessao = buscar_sessao_por_mensagem_whatsapp(ref, telefone_remetente)
    if sessao is None and parsed:
        sessao = buscar_sessao_por_envio(parsed['envio_id'], telefone_remetente)
    if sessao is None:
        ativas = list(_sessao_ativa_qs(telefone_remetente).order_by('-criado_em')[:1])
        sessao = ativas[0] if len(ativas) == 1 else None

    if not sessao:
        if parsed or ref:
            _enviar_texto(
                telefone_remetente,
                'Não encontrei a lista de agendamentos pendente. Pode ter expirado.',
            )
            return True
        return False

    if sessao.finalizado_em:
        _enviar_texto(telefone_remetente, 'Esta lista já foi respondida. Avise o backoffice se precisar alterar.')
        return True

    if not parsed:
        _enviar_texto(telefone_remetente, 'Use os *botões* da mensagem da lista de agendamentos.')
        return True

    from crm_app.models import ListaAgendamentoVendedorSessao

    etapa = sessao.etapa
    if etapa == ListaAgendamentoVendedorSessao.ETAPA_INICIAL:
        return _etapa_inicial(sessao, parsed, telefone_remetente)
    if etapa == ListaAgendamentoVendedorSessao.ETAPA_ESCOLHER_PEDIDO:
        return _etapa_escolher_pedido(sessao, parsed, telefone_remetente)
    if etapa == ListaAgendamentoVendedorSessao.ETAPA_DATA:
        return _etapa_data(sessao, parsed, telefone_remetente)
    if etapa == ListaAgendamentoVendedorSessao.ETAPA_TURNO:
        return _etapa_turno(sessao, parsed, telefone_remetente)
    return False
