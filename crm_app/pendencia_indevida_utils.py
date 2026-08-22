"""Pendência indevida na esteira — registro, anexos e envio ao GC."""
import base64
import logging
import mimetypes
import os

from django.core.files.base import ContentFile

from .models import AnteciparInstalacaoConfig, PendenciaIndevidaAnexo, PendenciaIndevidaRegistro
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

LIMITES_MB = {
    'imagem': 6,
    'video': 20,
    'audio': 20,
}

EXT_IMAGEM = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
EXT_VIDEO = {'.mp4', '.webm', '.mov'}
EXT_AUDIO = {'.mp3', '.ogg', '.wav', '.m4a', '.aac'}


def _get_config_gc():
    config = AnteciparInstalacaoConfig.objects.first()
    if not config:
        config = AnteciparInstalacaoConfig.objects.create(telefone_gc='', nome_gc='')
    return config


def classificar_anexo(uploaded):
    nome = (getattr(uploaded, 'name', '') or '').lower()
    ext = os.path.splitext(nome)[1]
    if ext in EXT_IMAGEM:
        return 'imagem'
    if ext in EXT_VIDEO:
        return 'video'
    if ext in EXT_AUDIO:
        return 'audio'
    ct = (getattr(uploaded, 'content_type', '') or '').lower()
    if ct.startswith('image/'):
        return 'imagem'
    if ct.startswith('video/'):
        return 'video'
    if ct.startswith('audio/'):
        return 'audio'
    return None


def validar_anexo(uploaded):
    tipo = classificar_anexo(uploaded)
    if not tipo:
        return None, None, 'Formato não permitido. Use imagem (JPG/PNG), vídeo (MP4) ou áudio (MP3/OGG/WAV).'
    raw = uploaded.read()
    uploaded.seek(0)
    limite = LIMITES_MB[tipo] * 1024 * 1024
    if len(raw) > limite:
        return None, None, f'Arquivo muito grande (máx. {LIMITES_MB[tipo]} MB para {tipo}).'
    return tipo, raw, None


def montar_mensagem_pendencia_indevida(venda, motivo_nome, observacao, usuario):
    os_num = (venda.ordem_servico or '—').strip()
    cliente = venda.cliente.nome_razao_social if venda.cliente else '—'
    vendedor = ''
    if venda.vendedor:
        vendedor = venda.vendedor.get_full_name() or venda.vendedor.username
    auditor = ''
    if usuario:
        auditor = usuario.get_full_name() or usuario.username
    return (
        f"Pendência indevida registrada\n\n"
        f"Pedido (O.S.): {os_num}\n"
        f"Cliente: {cliente}\n"
        f"Vendedor: {vendedor}\n"
        f"Motivo da pendência (sistema): {motivo_nome or '—'}\n"
        f"Observação: {(observacao or '—').strip()}\n"
        f"Marcado por: {auditor}"
    )


def _arquivo_para_b64(raw, mime):
    b64 = base64.b64encode(raw).decode('ascii')
    return f"data:{mime};base64,{b64}"


def _mime_por_tipo(tipo, nome):
    if tipo == 'imagem':
        ext = os.path.splitext(nome)[1].lower()
        if ext in ('.png',):
            return 'image/png'
        if ext in ('.webp',):
            return 'image/webp'
        if ext in ('.gif',):
            return 'image/gif'
        return 'image/jpeg'
    if tipo == 'video':
        return 'video/mp4'
    return 'audio/mpeg'


def enviar_gc_pendencia_indevida(telefone_gc, mensagem, anexos_qs):
    """Envia ao GC: texto na legenda da 1ª imagem; demais mídias em mensagens separadas."""
    if not telefone_gc:
        return False, ['Telefone do GC não configurado.']
    svc = WhatsAppService()
    erros = []
    anexos = list(anexos_qs)
    imagens = [a for a in anexos if a.tipo == 'imagem']
    outros = [a for a in anexos if a.tipo != 'imagem']

    enviado = False
    caption_max = 1024
    usar_legenda = len(mensagem) <= caption_max

    if imagens:
        primeiro = imagens[0]
        with primeiro.arquivo.open('rb') as f:
            raw = f.read()
        mime = _mime_por_tipo('imagem', primeiro.nome_original or 'foto.jpg')
        data_url = _arquivo_para_b64(raw, mime)
        cap = mensagem if usar_legenda else f"Pendência indevida — {primeiro.nome_original or 'anexo'}"
        if svc.enviar_imagem_b64(telefone_gc, data_url, caption=cap):
            enviado = True
        else:
            erros.append('GC: falha ao enviar imagem.')
        if not usar_legenda:
            ok, _ = svc.enviar_mensagem_texto(telefone_gc, mensagem)
            if ok:
                enviado = True
            else:
                erros.append('GC: falha ao enviar texto.')
        for extra in imagens[1:]:
            with extra.arquivo.open('rb') as f:
                raw = f.read()
            mime = _mime_por_tipo('imagem', extra.nome_original or 'foto.jpg')
            if not svc.enviar_imagem_b64(telefone_gc, _arquivo_para_b64(raw, mime), caption=''):
                erros.append(f'GC: falha imagem {extra.nome_original}')
    elif outros or not anexos:
        ok, resp = svc.enviar_mensagem_texto(telefone_gc, mensagem)
        if ok:
            enviado = True
        else:
            erros.append(f'GC: texto — {resp}')

    for an in outros:
        with an.arquivo.open('rb') as f:
            raw = f.read()
        nome = an.nome_original or os.path.basename(an.arquivo.name) or 'anexo'
        ext = os.path.splitext(nome)[1].lstrip('.').lower() or 'mp4'
        b64 = base64.b64encode(raw).decode('ascii')
        if not svc.enviar_pdf_b64(telefone_gc, b64, nome_arquivo=nome):
            erros.append(f'GC: falha ao enviar {nome}')

    return enviado, erros


def registrar_pendencia_indevida(
    *,
    usuario,
    venda,
    motivo_pendencia,
    observacao,
    tem_evidencia,
    arquivos_upload,
):
    from .models import MotivoPendencia

    motivo_nome = ''
    if motivo_pendencia:
        if isinstance(motivo_pendencia, MotivoPendencia):
            motivo_nome = motivo_pendencia.nome
        else:
            m = MotivoPendencia.objects.filter(pk=motivo_pendencia).first()
            motivo_nome = m.nome if m else ''

    if tem_evidencia and not arquivos_upload:
        return None, False, 'Com evidência marcada, anexe ao menos um arquivo.'

    mensagem = montar_mensagem_pendencia_indevida(venda, motivo_nome, observacao, usuario)
    motivo_obj = None
    if motivo_pendencia:
        if hasattr(motivo_pendencia, 'pk'):
            motivo_obj = motivo_pendencia
        else:
            from .models import MotivoPendencia
            motivo_obj = MotivoPendencia.objects.filter(pk=int(motivo_pendencia)).first()

    registro = PendenciaIndevidaRegistro.objects.create(
        venda=venda,
        usuario=usuario,
        motivo_pendencia=motivo_obj,
        observacao=(observacao or '')[:4000],
        tem_evidencia=bool(tem_evidencia),
        mensagem_enviada=mensagem[:4000],
    )

    for up in arquivos_upload or []:
        tipo, raw, err = validar_anexo(up)
        if err:
            registro.erros = list(registro.erros or []) + [err]
            registro.save(update_fields=['erros'])
            continue
        nome = getattr(up, 'name', 'anexo') or 'anexo'
        PendenciaIndevidaAnexo.objects.create(
            registro=registro,
            arquivo=ContentFile(raw, name=nome),
            nome_original=nome[:255],
            tipo=tipo,
        )

    config = _get_config_gc()
    telefone_gc = (config.telefone_gc or '').strip()
    enviado_gc, erros_env = enviar_gc_pendencia_indevida(
        telefone_gc, mensagem, registro.anexos.all(),
    )
    registro.enviado_gc = enviado_gc
    registro.erros = list(registro.erros or []) + erros_env
    registro.save(update_fields=['enviado_gc', 'erros'])

    sucesso = enviado_gc or (not tem_evidencia and not telefone_gc)
    if not telefone_gc:
        msg = 'Registro salvo. Telefone do GC não configurado — WhatsApp não enviado.'
    elif enviado_gc:
        msg = 'Pendência indevida registrada e comunicação enviada ao GC.'
        if registro.erros:
            msg += ' Avisos: ' + '; '.join(registro.erros[:2])
    elif tem_evidencia:
        msg = 'Registro salvo, mas falha ao enviar ao GC: ' + ('; '.join(registro.erros) if registro.erros else 'erro desconhecido')
    else:
        msg = 'Pendência indevida registrada (sem evidência).'
        if enviado_gc:
            msg += ' Mensagem enviada ao GC.'

    return registro, enviado_gc or not tem_evidencia, msg
