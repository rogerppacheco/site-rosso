"""Utilitários para comunicação — agenda disponível não atende o cliente (auditoria)."""
import base64
import logging

from .models import AnteciparInstalacaoConfig, AuditoriaSemSlotGC
from .services.destinos_operacionais_service import obter_destinos_operacionais
from .whatsapp_service import WhatsAppService


def _get_config_gc():
    config = AnteciparInstalacaoConfig.objects.first()
    if not config:
        config = AnteciparInstalacaoConfig.objects.create(telefone_gc='', nome_gc='')
    return config


def _imagem_para_data_url_e_bytes(uploaded):
    if not uploaded:
        return None, None, None, 'Imagem do print do PAP é obrigatória.'
    raw = uploaded.read()
    if len(raw) > 6 * 1024 * 1024:
        return None, None, None, 'Imagem muito grande (máx. 6 MB).'
    ct = (uploaded.content_type or '').lower().split(';')[0].strip()
    if ct not in ('image/jpeg', 'image/jpg', 'image/png', 'image/webp'):
        return None, None, None, 'Use imagem JPG, PNG ou WEBP.'
    if 'png' in ct:
        mime = 'image/png'
    elif 'webp' in ct:
        mime = 'image/webp'
    else:
        mime = 'image/jpeg'
    b64 = base64.b64encode(raw).decode('ascii')
    data_url = f"data:{mime};base64,{b64}"
    nome = getattr(uploaded, 'name', 'print_pap.jpg') or 'print_pap.jpg'
    return data_url, raw, nome, None

logger = logging.getLogger(__name__)

TURNO_LABEL = {'MANHA': 'Manhã', 'TARDE': 'Tarde'}

PERFIS_AUDITORIA = ['Diretoria', 'Admin', 'BackOffice', 'Supervisor', 'Auditoria', 'Qualidade', 'Gerente de Contas']


def endereco_completo_venda(venda):
    """Monta endereço no mesmo padrão da aba 3 da auditoria."""
    parts = []
    if venda.logradouro:
        parts.append((venda.logradouro or '').strip().title())
    if venda.numero_residencia:
        parts.append(str(venda.numero_residencia).strip())
    comp = (venda.complemento or '').strip()
    if comp:
        parts.append(comp.title())
    bairro = (venda.bairro or '').strip()
    cidade = (venda.cidade or '').strip()
    uf = (venda.estado or '').strip().upper()
    cep = (venda.cep or '').strip()
    if bairro or cidade:
        loc = bairro.title() if bairro else ''
        if cidade:
            loc = f"{loc}, {cidade.title()}" if loc else cidade.title()
        if uf:
            loc = f"{loc} - {uf}"
        parts.append(loc)
    elif uf:
        parts.append(uf)
    if cep:
        parts.append(cep)
    ref = (venda.ponto_referencia or '').strip()
    if ref:
        parts.append(ref.title())
    return ', '.join(p for p in parts if p)


def endereco_completo_dict(dados):
    """Monta endereço a partir do dict coletado no frontend (auditoria)."""

    class _End:
        pass

    v = _End()
    v.logradouro = dados.get('logradouro', '')
    v.numero_residencia = dados.get('numero') or dados.get('numero_residencia', '')
    v.complemento = dados.get('complemento', '')
    v.bairro = dados.get('bairro', '')
    v.cidade = dados.get('cidade', '')
    v.estado = dados.get('estado') or dados.get('uf', '')
    v.cep = dados.get('cep', '')
    v.ponto_referencia = dados.get('referencia', '')
    return endereco_completo_venda(v)


def formatar_telefones_contato(tel1, tel2):
    t1 = (tel1 or '').strip()
    t2 = (tel2 or '').strip()
    if t1 and t2:
        return f"{t1} e {t2}"
    return t1 or t2 or ''


def montar_mensagem_sem_slot(uf, ordem_servico, endereco, data_desejada, turno_desejado, telefones):
    turno_txt = TURNO_LABEL.get((turno_desejado or '').upper(), turno_desejado or '')
    if hasattr(data_desejada, 'strftime'):
        data_txt = data_desejada.strftime('%d/%m/%Y')
    else:
        data_txt = str(data_desejada or '')
    return (
        f"Sem SLOT em {(uf or '').upper()}\n\n"
        f"Pedido: {ordem_servico}\n"
        f"Endereço: {endereco}\n"
        f"Data e turno que o cliente deseja: {data_txt} - {turno_txt}\n"
        f"Tel. de contato: {telefones}"
    )


def destinatarios_configurados():
    """Telefones individuais + grupos WhatsApp da configuração operacional."""
    return obter_destinos_operacionais(_get_config_gc())


def destinatarios_gc_e_diretoria():
    """
    Compatibilidade: retorna (primeiro_telefone, demais_telefones).

    Diretoria não é mais destino automático — apenas telefones_destino.
    """
    destinos = destinatarios_configurados()
    telefones = destinos['telefones']
    if not telefones:
        return '', []
    return telefones[0], telefones[1:]


def validar_endereco_completo_venda(venda):
    campos = [
        ('CEP', venda.cep),
        ('Logradouro', venda.logradouro),
        ('Número', venda.numero_residencia),
        ('Bairro', venda.bairro),
        ('Cidade', venda.cidade),
        ('UF', venda.estado),
    ]
    faltando = [nome for nome, val in campos if not (val and str(val).strip())]
    return faltando


def processar_envio_sem_slot(
    *,
    usuario,
    venda,
    ordem_servico,
    uf,
    endereco,
    data_agendamento_cadastrada,
    turno_agendamento_cadastrado,
    data_desejada_cliente,
    turno_desejado_cliente,
    telefone_contato,
    imagem_upload,
):
    """
    Envia imagem com legenda (texto completo) aos destinos configurados (telefones e grupos).
    Se a mensagem exceder o limite da legenda, envia texto e imagem separados.
    Persiste AuditoriaSemSlotGC. Retorna (registro, sucesso_parcial, mensagem_resumo).
    """
    from django.core.files.base import ContentFile

    img_data_url, img_bytes, img_nome, img_err = _imagem_para_data_url_e_bytes(imagem_upload)
    if img_err:
        return None, False, img_err

    mensagem = montar_mensagem_sem_slot(
        uf, ordem_servico, endereco, data_desejada_cliente,
        turno_desejado_cliente, telefone_contato,
    )
    destinos_cfg = destinatarios_configurados()
    destinos = []
    for i, tel in enumerate(destinos_cfg['telefones']):
        destinos.append(('telefone', tel, tel))
    for grupo in destinos_cfg['grupos']:
        destinos.append(('grupo', grupo.chat_id, grupo.nome or grupo.chat_id))

    if not destinos:
        return None, False, (
            'Nenhum destino configurado. Defina grupos e/ou telefones WhatsApp '
            'em Antecipar Instalação > Configuração.'
        )

    enviado_individual = False
    enviados_individuais = []
    enviados_grupos = []
    erros = []
    # WhatsApp limita legenda da imagem (~1024 caracteres)
    caption_max = 1024
    usar_legenda_completa = len(mensagem) <= caption_max
    caption_img = mensagem if usar_legenda_completa else f"Print PAP — Pedido {ordem_servico}"

    try:
        svc = WhatsAppService()
        for tipo, destino, rotulo in destinos:
            if not img_data_url:
                erros.append(f'{rotulo}: imagem ausente')
                continue
            if not usar_legenda_completa:
                ok_txt, resp_txt = svc.enviar_mensagem_texto(destino, mensagem)
                if not ok_txt:
                    erros.append(f'{rotulo}: texto — {resp_txt}')
            ok_img = svc.enviar_imagem_b64(destino, img_data_url, caption=caption_img)
            if not ok_img:
                erros.append(f'{rotulo}: imagem — falha no envio')
                continue
            if tipo == 'telefone':
                enviado_individual = True
                enviados_individuais.append(destino)
            else:
                enviados_grupos.append({'chat_id': destino, 'nome': rotulo})
    except Exception as e:
        logger.exception("Erro ao enviar WhatsApp sem slot: %s", e)
        erros.append(str(e))

    create_kw = dict(
        usuario=usuario,
        venda=venda,
        ordem_servico=ordem_servico or '',
        uf=(uf or '').upper()[:2],
        endereco_completo=endereco or '',
        data_agendamento_cadastrada=data_agendamento_cadastrada,
        turno_agendamento_cadastrado=turno_agendamento_cadastrado or '',
        data_desejada_cliente=data_desejada_cliente,
        turno_desejado_cliente=turno_desejado_cliente,
        telefone_contato=telefone_contato or '',
        mensagem_enviada=mensagem[:4000],
        enviado_gc=enviado_individual,
        enviados_diretoria=enviados_individuais,
        enviados_grupos=enviados_grupos,
        erros=erros,
    )
    if img_bytes is not None:
        create_kw['imagem_anexo'] = ContentFile(img_bytes, name=img_nome or 'print_pap.jpg')
    registro = AuditoriaSemSlotGC.objects.create(**create_kw)

    enviado_teams = False
    try:
        from crm_app.services.teams_notification_service import (
            enviar_teams_operacional,
            media_url_absoluta,
        )

        img_url = None
        if registro.imagem_anexo:
            img_url = media_url_absoluta(registro.imagem_anexo.name)
        ok_teams, _ = enviar_teams_operacional(
            titulo=f"Sem SLOT — {(uf or '').upper()}",
            texto=mensagem,
            source="auditoria-sem-slot",
            image_url=img_url,
        )
        if ok_teams:
            enviado_teams = True
            AuditoriaSemSlotGC.objects.filter(pk=registro.pk).update(enviado_teams=True)
    except Exception as e:
        logger.warning("[Sem SLOT] Falha ao notificar Teams: %s", e)
        erros.append(f'Teams: {e}')

    sucesso = enviado_individual or bool(enviados_grupos) or enviado_teams
    if sucesso and erros:
        msg = 'Enviado com avisos: ' + '; '.join(erros[:3])
    elif sucesso:
        partes = []
        if enviados_individuais:
            partes.append(f'{len(enviados_individuais)} contato(s)')
        if enviados_grupos:
            partes.append(f'{len(enviados_grupos)} grupo(s)')
        destino_txt = ' e '.join(partes) if partes else 'destinos configurados'
        msg = (
            f'Comunicação enviada aos destinos configurados ({destino_txt})'
            + (
                ' (texto na legenda da imagem).'
                if usar_legenda_completa
                else ' (texto e imagem em mensagens separadas — legenda muito longa).'
            )
        )
    else:
        msg = 'Falha no envio: ' + ('; '.join(erros) if erros else 'erro desconhecido')
    return registro, sucesso, msg
