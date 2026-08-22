"""Montagem e envio de pedidos de ajuda/socorro ao GC da Nio (e-mail + WhatsApp)."""

from __future__ import annotations

import base64
import logging
from email.mime.image import MIMEImage
from typing import Any, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from crm_app.models import AnteciparInstalacaoConfig, PedidoAjudaGc, Venda
from crm_app.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

PDV_PADRAO = '1068561'

ETAPAS_PADRAO_AUDITORIA: list[tuple[str, int]] = [
    ('Etapa 1: Identificação PDV', 1),
    ('Etapa 2: Consulta de viabilidade', 2),
    ('Etapa 3: Cadastro do cliente', 3),
    ('Etapa 4: Contato', 4),
    ('Etapa 5: Pagamento/Ofertas', 5),
    ('Etapa 6: Resumo', 6),
    ('Etapa 7: Abrir OS', 7),
]

ETAPAS_PADRAO_ESTEIRA: list[tuple[str, int]] = [
    ('Agendamento OCO, agenda e não muda o status', 1),
    ('Pedido instalado e não concluído', 2),
]


def obter_config_gc() -> AnteciparInstalacaoConfig:
    config = AnteciparInstalacaoConfig.objects.first()
    if not config:
        config = AnteciparInstalacaoConfig.objects.create(
            telefone_gc='',
            nome_gc='',
            email_gc='',
        )
    return config


def contato_do_usuario(usuario) -> str:
    """Contato da pessoa que reporta (preferência: WhatsApp do cadastro, depois e-mail)."""
    if not usuario:
        return ''
    tel = (getattr(usuario, 'tel_whatsapp', None) or '').strip()
    if tel:
        return tel
    email = (getattr(usuario, 'email', None) or '').strip()
    if email:
        return email
    nome = (getattr(usuario, 'get_full_name', lambda: '')() or '').strip()
    username = (getattr(usuario, 'username', None) or '').strip()
    return nome or username


def cpf_cnpj_da_venda(venda: Optional[Venda]) -> str:
    if not venda or not getattr(venda, 'cliente', None):
        return ''
    return (venda.cliente.cpf_cnpj or '').strip()


def numero_pedido_da_venda(venda: Optional[Venda]) -> str:
    if not venda:
        return ''
    return (venda.ordem_servico or '').strip() or str(venda.id)


def protocolo_registro_auditoria(venda: Optional[Venda]) -> str:
    """Protocolo de atendimento (confirmação / viabilidade) quando existir na venda."""
    if not venda:
        return ''
    proto = (getattr(venda, 'protocolo_confirmacao_auditoria', None) or '').strip()
    if proto:
        return proto
    return ''


def montar_mensagem_abrir_chamado_ti(dados: dict[str, Any]) -> str:
    """Máscara padrão para pedir ao GC abertura de chamado com TI (formato WhatsApp)."""
    linhas = [
        '*PEDIDO DE AJUDA — ABRIR CHAMADO COM TI*',
        '',
        f"*Nome do Gerente de Contas:* {dados.get('nome_gc') or 'NÃO INFORMADO'}",
        f"*PDV do usuário:* {dados.get('pdv') or PDV_PADRAO}",
        f"*Login BO (se houver):* {dados.get('login_bo') or 'NÃO INFORMADO'}",
        f"*Login vendedor:* {dados.get('login_vendedor') or 'NÃO INFORMADO'}",
        f"*CNPJ/CPF do cliente:* {dados.get('cpf_cnpj_cliente') or 'NÃO INFORMADO'}",
        f"*Número do Pedido (se houver):* {dados.get('numero_pedido') or 'NÃO INFORMADO'}",
        f"*Contato:* {dados.get('contato') or 'NÃO INFORMADO'}",
        f"*Qual etapa do erro:* {dados.get('etapa_erro') or 'NÃO INFORMADO'}",
        f"*Detalhar o cenário reportado:* {dados.get('detalhe_cenario') or 'NÃO INFORMADO'}",
        f"*Número do registro do atendimento:* {dados.get('numero_registro') or 'NÃO INFORMADO'}",
        '',
        '*Importante!* É obrigatório anexar as evidências contendo data e hora do erro.',
    ]
    return '\n'.join(linhas)


def montar_assunto_email_abrir_chamado_ti(
    etapa_erro: str,
    numero_pedido: str,
    numero_registro: str,
    *,
    ordem_servico: str = '',
    venda_id: Optional[int] = None,
) -> str:
    """
    Assunto: {ETAPA}_PEDIDO:{OS|protocolo}.
    Prefere O.S.; se não houver, usa o número do registro do atendimento.
    """
    import re

    etapa = re.sub(r'\s+', ' ', (etapa_erro or 'PEDIDO DE AJUDA').strip()).upper()
    os_real = (ordem_servico or '').strip()
    pedido = (numero_pedido or '').strip()
    registro = (numero_registro or '').strip()
    id_interno = str(venda_id) if venda_id is not None else ''

    if os_real:
        ref = os_real
    elif pedido and pedido != id_interno:
        ref = pedido
    elif registro:
        ref = registro
    elif pedido:
        ref = pedido
    else:
        ref = 'SEM_REFERENCIA'
    return f'{etapa}_PEDIDO:{ref}'


def mensagem_whatsapp_para_email_texto(mensagem: str) -> str:
    """Texto plano do e-mail: remove * do WhatsApp e preserva quebras (CRLF p/ Outlook)."""
    linhas = [(ln or '').replace('*', '') for ln in (mensagem or '').split('\n')]
    return '\r\n'.join(linhas)


def mensagem_whatsapp_para_email_html(mensagem: str) -> str:
    """HTML do e-mail com as mesmas quebras de linha do WhatsApp (rótulos em negrito)."""
    import html
    import re

    partes: list[str] = []
    for ln in (mensagem or '').split('\n'):
        if ln == '':
            partes.append('<br>')
            continue
        escapado = html.escape(ln)
        escapado = re.sub(r'\*(.+?)\*', r'<strong>\1</strong>', escapado)
        partes.append(escapado)
    corpo = '<br>\n'.join(partes)
    return (
        '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;'
        'line-height:1.45;color:#111;">'
        f'{corpo}'
        '</div>'
    )


def _validar_evidencia(uploaded) -> tuple[Optional[bytes], Optional[str], Optional[str], Optional[str]]:
    """Retorna (bytes, content_type, nome, erro)."""
    if not uploaded:
        return None, None, None, 'Anexe a evidência com data e hora do erro.'
    raw = uploaded.read()
    if len(raw) > 8 * 1024 * 1024:
        return None, None, None, 'Evidência muito grande (máx. 8 MB).'
    ct = (uploaded.content_type or '').lower().split(';')[0].strip()
    permitidos = {
        'image/jpeg',
        'image/jpg',
        'image/png',
        'image/webp',
        'application/pdf',
    }
    if ct not in permitidos:
        return None, None, None, 'Use imagem (JPG, PNG, WEBP) ou PDF.'
    nome = getattr(uploaded, 'name', 'evidencia') or 'evidencia'
    return raw, ct, nome, None


def enviar_email_gc(
    destino: str,
    assunto: str,
    corpo_texto: str,
    evidencia_bytes: Optional[bytes] = None,
    evidencia_nome: Optional[str] = None,
    evidencia_ct: Optional[str] = None,
    corpo_html: Optional[str] = None,
) -> tuple[bool, str]:
    destino = (destino or '').strip()
    if not destino:
        return False, 'E-mail do GC não configurado.'
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(
        settings, 'EMAIL_HOST_USER', None
    )
    if not from_email:
        return False, 'Remetente de e-mail não configurado (DEFAULT_FROM_EMAIL).'
    try:
        msg = EmailMultiAlternatives(
            subject=assunto,
            body=corpo_texto,
            from_email=from_email,
            to=[destino],
        )
        if corpo_html:
            msg.attach_alternative(corpo_html, 'text/html')
        if evidencia_bytes and evidencia_nome:
            ct = evidencia_ct or 'application/octet-stream'
            if ct.startswith('image/'):
                subtype = ct.split('/', 1)[-1]
                if subtype == 'jpg':
                    subtype = 'jpeg'
                img = MIMEImage(evidencia_bytes, _subtype=subtype)
                img.add_header('Content-Disposition', 'attachment', filename=evidencia_nome)
                msg.attach(img)
            else:
                msg.attach(evidencia_nome, evidencia_bytes, ct)
        msg.send(fail_silently=False)
        return True, ''
    except Exception as exc:
        logger.exception('[PedidoAjudaGC] Falha ao enviar e-mail: %s', exc)
        return False, str(exc)


def enviar_whatsapp_gc(
    telefone: str,
    mensagem: str,
    evidencia_bytes: Optional[bytes] = None,
    evidencia_ct: Optional[str] = None,
) -> tuple[bool, str]:
    telefone = (telefone or '').strip()
    if not telefone:
        return False, 'Telefone do GC não configurado.'
    try:
        svc = WhatsAppService()
        ok_txt, resp_txt = svc.enviar_mensagem_texto(telefone, mensagem, variar=False)
        if not ok_txt:
            return False, f'Falha no texto WhatsApp: {resp_txt}'
        if evidencia_bytes and evidencia_ct and evidencia_ct.startswith('image/'):
            b64 = base64.b64encode(evidencia_bytes).decode('ascii')
            ok_img, resp_img = svc.enviar_imagem_b64(
                telefone, b64, caption='Evidência do erro (pedido de ajuda)'
            )
            if not ok_img:
                return True, f'Texto enviado; falha na imagem: {resp_img}'
        elif evidencia_bytes and evidencia_ct == 'application/pdf':
            b64 = base64.b64encode(evidencia_bytes).decode('ascii')
            ok_pdf, resp_pdf = svc.enviar_pdf_b64(
                telefone, b64, nome_arquivo='evidencia.pdf', caption='Evidência do erro'
            )
            if not ok_pdf:
                return True, f'Texto enviado; falha no PDF: {resp_pdf}'
        return True, ''
    except Exception as exc:
        logger.exception('[PedidoAjudaGC] Falha WhatsApp: %s', exc)
        return False, str(exc)


def processar_pedido_abrir_chamado_ti(
    *,
    usuario,
    venda: Optional[Venda],
    origem: str,
    login_bo: str,
    login_vendedor: str,
    etapa_erro: str,
    detalhe_cenario: str,
    numero_registro: str,
    evidencia_upload,
    cpf_cnpj_override: str = '',
    numero_pedido_override: str = '',
    contato_override: str = '',
) -> tuple[Optional[PedidoAjudaGc], Optional[str]]:
    """
    Valida, monta mensagem, envia e-mail/WhatsApp e grava histórico.
    Retorna (pedido, mensagem_erro).
    """
    origem_norm = (origem or '').strip().lower()
    if origem_norm not in (PedidoAjudaGc.ORIGEM_AUDITORIA, PedidoAjudaGc.ORIGEM_ESTEIRA):
        return None, 'Origem inválida (use auditoria ou esteira).'

    login_bo = (login_bo or '').strip()
    login_vendedor = (login_vendedor or '').strip()
    etapa_erro = (etapa_erro or '').strip()
    detalhe_cenario = (detalhe_cenario or '').strip()
    numero_registro = (numero_registro or '').strip()

    if not login_bo:
        return None, 'Informe o Login BO.'
    if not login_vendedor:
        return None, 'Informe o Login vendedor.'
    if not etapa_erro:
        return None, 'Selecione a etapa do erro.'
    if not detalhe_cenario:
        return None, 'Detalhe o cenário reportado.'

    ev_bytes, ev_ct, ev_nome, ev_err = _validar_evidencia(evidencia_upload)
    if ev_err:
        return None, ev_err

    config = obter_config_gc()
    nome_gc = (config.nome_gc or '').strip()
    email_gc = (config.email_gc or '').strip()
    telefone_gc = (config.telefone_gc or '').strip()

    cpf_cnpj = (cpf_cnpj_override or '').strip() or cpf_cnpj_da_venda(venda)
    numero_pedido = (numero_pedido_override or '').strip() or numero_pedido_da_venda(venda)
    contato = (contato_override or '').strip() or contato_do_usuario(usuario)
    if origem_norm == PedidoAjudaGc.ORIGEM_AUDITORIA and not numero_registro:
        numero_registro = protocolo_registro_auditoria(venda)

    dados_msg = {
        'nome_gc': nome_gc or 'NÃO INFORMADO',
        'pdv': PDV_PADRAO,
        'login_bo': login_bo,
        'login_vendedor': login_vendedor,
        'cpf_cnpj_cliente': cpf_cnpj,
        'numero_pedido': numero_pedido,
        'contato': contato,
        'etapa_erro': etapa_erro,
        'detalhe_cenario': detalhe_cenario,
        'numero_registro': numero_registro,
    }
    mensagem = montar_mensagem_abrir_chamado_ti(dados_msg)

    pedido = PedidoAjudaGc(
        tipo=PedidoAjudaGc.TIPO_ABRIR_CHAMADO_TI,
        origem=origem_norm,
        usuario=usuario,
        venda=venda,
        nome_gc=nome_gc,
        email_gc=email_gc,
        telefone_gc=telefone_gc,
        pdv=PDV_PADRAO,
        login_bo=login_bo,
        login_vendedor=login_vendedor,
        cpf_cnpj_cliente=cpf_cnpj,
        numero_pedido=numero_pedido,
        contato=contato,
        etapa_erro=etapa_erro,
        detalhe_cenario=detalhe_cenario,
        numero_registro=numero_registro,
        mensagem_enviada=mensagem,
    )
    if evidencia_upload and ev_bytes is not None:
        from django.core.files.base import ContentFile

        evidencia_upload.seek(0)
        pedido.evidencia.save(ev_nome or 'evidencia', ContentFile(ev_bytes), save=False)

    erros: list[str] = []
    ordem_servico = (venda.ordem_servico or '').strip() if venda else ''
    assunto = montar_assunto_email_abrir_chamado_ti(
        etapa_erro,
        numero_pedido,
        numero_registro,
        ordem_servico=ordem_servico,
        venda_id=venda.id if venda else None,
    )
    ok_email, err_email = enviar_email_gc(
        email_gc,
        assunto=assunto,
        corpo_texto=mensagem_whatsapp_para_email_texto(mensagem),
        corpo_html=mensagem_whatsapp_para_email_html(mensagem),
        evidencia_bytes=ev_bytes,
        evidencia_nome=ev_nome,
        evidencia_ct=ev_ct,
    )
    pedido.enviado_email = ok_email
    if not ok_email and err_email:
        erros.append(f'E-mail: {err_email}')

    ok_wpp, err_wpp = enviar_whatsapp_gc(
        telefone_gc,
        mensagem,
        evidencia_bytes=ev_bytes,
        evidencia_ct=ev_ct,
    )
    pedido.enviado_whatsapp = ok_wpp
    if not ok_wpp and err_wpp:
        erros.append(f'WhatsApp: {err_wpp}')
    elif ok_wpp and err_wpp:
        erros.append(f'WhatsApp (parcial): {err_wpp}')

    pedido.erros = erros
    pedido.save()

    if not ok_email and not ok_wpp:
        return pedido, 'Não foi possível enviar por e-mail nem WhatsApp. Verifique a configuração do GC e do SMTP.'

    return pedido, None
