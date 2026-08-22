# crm_app/whatsapp_webhook_handler.py
"""
Handler para processar mensagens do WhatsApp e executar comandos:
- DFV / CDOE
- Viabilidade  
- Status
- Fatura
"""
import re
import os
import queue
import time
import logging
import threading
from datetime import datetime
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Pendências etapa 6: aguardando confirmação do cliente ("sim") ou "bio ok" do vendedor
_pending_client_confirm = {}  # telefone_cliente_normalizado -> {event, vendedor_telefone, consultar_queue, ...}
_pending_by_vendedor = {}  # vendedor_telefone_normalizado -> chave_cliente (para CONSULTAR encontrar a fila)
_pending_bio_ok = {}  # vendedor_telefone_normalizado -> {event, ...}
_pending_lock = threading.Lock()

# Automações PAP em andamento (agendamento - usuário seleciona dia/período via mensagem)
_automacoes_pap_ativas = {}  # sessao_id -> {automacao, dados, vendedor_id, bo_usuario_id, telefone}
_automacoes_lock = threading.Lock()

# Worker threads PAP: a automação Playwright deve ser usada na MESMA thread onde foi criada.
# Cada sessão tem uma fila de comandos; o worker processa e envia respostas via WhatsApp.
_pap_worker_queues = {}  # sessao_id -> queue.Queue()
_pap_worker_lock = threading.Lock()

# Timeout da sessão VENDER: sem comando do usuário por este tempo (segundos), a sessão encerra.
SESSION_TIMEOUT_SECONDS = 600  # 10 min
# Prorrogação: cada ESTENDER adiciona mais este tempo (minutos) e há um limite de prorrogações.
EXTEND_SESSION_MINUTES = 5
MAX_EXTEND_SESSION_COUNT = 3  # no máximo 3 prorrogações (ex.: +5 min cada = até 10+15 = 25 min extra)

# Evita enviar a lista de faturas duas vezes quando o webhook é disparado em duplicidade (ex.: Z-API/WhatsApp).
_fatura_cpf_lock = threading.Lock()

# Idempotência: não enviar a mesma resposta duas vezes para o mesmo messageId (Z-API pode reenviar o webhook).
_webhook_reply_message_ids = {}  # messageId -> timestamp
_webhook_reply_ttl = 300  # segundos
_webhook_reply_lock = threading.Lock()

# Evita execução duplicada do preenchimento do formulário de Inclusão (duas abas abertas)
_inclusao_form_em_execucao = set()  # telefone_normalizado
_inclusao_form_lock = threading.Lock()


def _registrar_estatistica(telefone, comando):
    """
    Registra uma estatística de mensagem enviada pelo bot
    Tenta identificar o vendedor pelo telefone
    """
    try:
        from crm_app.models import EstatisticaBotWhatsApp

        # Mesma busca usada no fluxo do bot (DDD, 8/9 dígitos, máscaras no cadastro)
        vendedor = _buscar_usuario_por_telefone(telefone)

        # Criar registro de estatística
        EstatisticaBotWhatsApp.objects.create(
            telefone=telefone,
            vendedor=vendedor,
            comando=comando
        )
        
        if vendedor:
            logger.debug(f"[Estatística] Registrado {comando} para vendedor {vendedor.username}")
        else:
            logger.debug(f"[Estatística] Registrado {comando} para telefone {telefone} (vendedor não identificado)")
            
    except Exception as e:
        logger.error(f"[Estatística] Erro ao registrar estatística: {e}", exc_info=True)


def formatar_telefone(telefone):
    """Normaliza telefone removendo caracteres não numéricos"""
    if not telefone:
        return ""
    telefone_limpo = "".join(filter(str.isdigit, str(telefone)))
    # Remove prefixo 55 se tiver
    if telefone_limpo.startswith('55') and len(telefone_limpo) > 12:
        telefone_limpo = telefone_limpo[2:]
    return telefone_limpo


def _strip_whatsapp_jid(val):
    """Remove sufixo @s.whatsapp.net / @c.us do identificador (Z-API / Baileys)."""
    if val is None:
        return val
    s = str(val).strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    return s


def _texto_confirmacao_cliente_pap(protocolo_exibicao: str = "") -> str:
    """Mensagem ao cliente após SIM; protocolo_exibicao = YYYYMMDDHHMM + seq (4 dígitos)."""
    proto = (protocolo_exibicao or "").strip()
    msg = "✅ *Confirmado!* O vendedor receberá a confirmação."
    if proto:
        msg += f"\n\n📋 *Protocolo:* {proto}"
    return msg


def _chave_telefone(telefone):
    """Chave única para dicionários de pendência (dígitos normalizados)."""
    return formatar_telefone(telefone) or ""


def _chaves_telefone_variantes(telefone):
    """Retorna variantes da chave para matching robusto (ex: 31986791000 e 5531986791000).
    Inclui variante 31X vs 319 (API pode enviar 10 dígitos 31+8 ou 11 dígitos 31+9+8).
    """
    base = formatar_telefone(telefone) or ""
    if not base:
        return []
    chaves = [base]
    # Garantir que temos a versão sem 55 para números nacionais
    if base.startswith('55') and len(base) > 11:
        chaves.append(base[2:])  # sem 55
    elif len(base) >= 10 and not base.startswith('55'):
        chaves.append('55' + base)  # com 55
    # Número nacional (sem 55) para variantes 10 <-> 11 dígitos
    nacional = base[2:] if base.startswith('55') and len(base) > 11 else base
    if len(nacional) == 10:
        # 10 dígitos (ex: 3195157538 ou 3188804000): gerar 11 dígitos (DDD+9+resto)
        chaves.append(nacional[:2] + '9' + nacional[2:])
        chaves.append('55' + nacional[:2] + '9' + nacional[2:])
    if len(nacional) == 11 and nacional[2] == '9':
        # 11 dígitos (ex: 31995157538): gerar 10 dígitos (remover o 9 após DDD)
        chaves.append(nacional[:2] + nacional[3:])
        chaves.append('55' + nacional[:2] + nacional[3:])
    if len(base) == 12 and base.startswith('55') and len(base) >= 5 and base[4] != '9':
        chaves.append(base[:4] + '9' + base[4:])
    if len(base) == 13 and base.startswith('55') and len(base) >= 6 and base[4] == '9':
        chaves.append(base[:4] + base[5:])
    return list(dict.fromkeys(chaves))


def _digits_only(s):
    """Retorna apenas os dígitos da string (para comparar números com formatação)."""
    if not s:
        return ""
    return "".join(filter(str.isdigit, str(s)))


def _usuario_ativo_por_telefone(telefone):
    """
    Retorna o usuário ativo associado ao número de WhatsApp, ou None.
    Consulta os 3 campos (tel_whatsapp, tel_whatsapp_2, tel_whatsapp_3).
    Aceita número com ou sem 9 após DDD e com ou sem formatação no banco.
    Apenas usuários ativos (is_active=True) podem interagir com o bot.
    """
    try:
        from django.db.models import Q
        from usuarios.models import Usuario
        chaves = _chaves_telefone_variantes(telefone) or [formatar_telefone(telefone) or '']
        chaves = [c for c in chaves if c]
        # 1) Busca por icontains (número sem formatação no banco)
        for tel_var in chaves:
            usuario = Usuario.objects.filter(is_active=True).filter(
                Q(tel_whatsapp__icontains=tel_var) |
                Q(tel_whatsapp_2__icontains=tel_var) |
                Q(tel_whatsapp_3__icontains=tel_var)
            ).first()
            if usuario:
                return usuario
        # 2) Fallback: match por dígitos (quando o cadastro tem espaço/traço, ex: "31 99515-7538")
        usuarios_ativos = Usuario.objects.filter(is_active=True).only(
            'id', 'tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3'
        )
        chaves_digits = [ _digits_only(c) for c in chaves ]
        for u in usuarios_ativos:
            for campo in (u.tel_whatsapp, u.tel_whatsapp_2, u.tel_whatsapp_3):
                if not campo:
                    continue
                stored = _digits_only(campo)
                if not stored:
                    continue
                for busca in chaves_digits:
                    if not busca:
                        continue
                    if busca == stored or (len(stored) >= 10 and (busca in stored or stored in busca)):
                        return u
        return None
    except Exception as e:
        logger.warning(f"[Webhook] Erro ao buscar usuário por telefone: {e}")
        return None


def _saudacao_por_hora():
    """Retorna 'Bom Dia', 'Boa Tarde' ou 'Boa Noite' conforme o horário (timezone do servidor)."""
    try:
        hora = timezone.localtime(timezone.now()).hour
        if hora < 12:
            return "Bom Dia"
        if hora < 18:
            return "Boa Tarde"
        return "Boa Noite"
    except Exception:
        return "Olá"


def _formatar_primeira_mensagem_automatica(mensagem, usuario):
    """
    Formata a primeira mensagem após palavra-chave: Saudação Nome:\n\nMensagem
    Sem colchetes na saudação. Nome com primeira letra maiúscula e resto minúsculo (nome próprio).
    """
    if not mensagem or not str(mensagem).strip():
        return mensagem
    saudacao = _saudacao_por_hora()
    nome = (usuario.first_name or usuario.username or "Usuário").strip() if usuario else "Usuário"
    if not nome:
        nome = usuario.username if usuario else "Usuário"
    # Primeira letra maiúscula, resto minúsculo (nome próprio)
    if len(nome) > 1:
        nome = nome[0].upper() + nome[1:].lower()
    elif nome:
        nome = nome.upper()
    return f"{saudacao} {nome}:\n\n{mensagem.strip()}"


def limpar_texto_cep_cpf(texto):
    """Remove pontos, traços e espaços (para CEP e CPF)"""
    if not texto:
        return ""
    return re.sub(r'[\s.\-/]', '', str(texto))


def classificar_identificador_status(texto: str) -> tuple[Optional[str], str, str]:
    """
    Detecta se a entrada do fluxo Status é CPF/CNPJ ou O.S.

    Padrões conhecidos do CRM:
    - CPF: 11 dígitos (aceita máscara)
    - CNPJ: 14 dígitos (mesmo fluxo de CPF na consulta)
    - O.S: 8 dígitos (ex: 08907507) ou X-12dígitos (ex: 4-212051254235)

    Retorna: (tipo ('CPF'|'OS')|None, valor_normalizado, mensagem_erro).
    """
    bruto = (texto or '').strip()
    msg_ajuda = (
        "❌ Não identifiquei se é *CPF* ou *O.S*.\n\n"
        "• CPF: 11 dígitos (ex: 12345678901)\n"
        "• CNPJ: 14 dígitos\n"
        "• O.S: 8 dígitos (ex: 08907507) ou formato X-12dígitos "
        "(ex: 4-212051254235)\n\n"
        "Digite novamente ou *CANCELAR* para sair:"
    )
    if not bruto:
        return None, '', (
            "❌ Informe o *CPF* ou a *O.S* do cliente.\n\n"
            "• CPF: 11 dígitos\n"
            "• O.S: 8 dígitos (ex: 08907507) ou X-12dígitos "
            "(ex: 4-212051254235)\n\n"
            "Digite novamente ou *CANCELAR* para sair:"
        )

    # Formato O.S com hífen (mantém como cadastrado no CRM)
    if re.fullmatch(r'\d-\d{12}', bruto):
        return 'OS', bruto, ''

    digitos = re.sub(r'\D', '', bruto)
    if len(digitos) == 11:
        return 'CPF', digitos, ''
    if len(digitos) == 14:
        return 'CPF', digitos, ''
    if len(digitos) == 8:
        return 'OS', digitos, ''
    # O.S digitada sem hífen: 1 + 12 dígitos
    if len(digitos) == 13:
        return 'OS', f'{digitos[0]}-{digitos[1:]}', ''

    return None, bruto, msg_ajuda


def _consultar_status_e_disparar_online(
    sessao: Any,
    telefone_formatado: str,
    tipo: str,
    valor: str,
    etapa_retry: str = 'status_documento',
) -> str:
    """Consulta status no CRM e, se houver CPF válido, dispara consulta online no PAP."""
    from crm_app.utils import consultar_status_venda_com_decisao

    label = 'CPF' if tipo == 'CPF' else 'O.S'
    logger.info('[Webhook] Consultando status por %s: %s', tipo, valor)
    try:
        resultado_status, fazer_consulta_online, cpf_para_consulta = (
            consultar_status_venda_com_decisao(tipo, valor)
        )
    except Exception as e:
        logger.exception('[Webhook] Erro ao consultar status por %s: %s', tipo, e)
        sessao.etapa = etapa_retry
        sessao.save(update_fields=['etapa'])
        return '❌ Erro ao consultar status. Tente novamente em instantes.'

    resposta = f'🔎 Buscando pedido por {label}...\n\n{resultado_status}'
    os_filtro = valor if tipo == 'OS' else None

    if fazer_consulta_online and cpf_para_consulta:
        run_id = str(int(time.time() * 1000))
        dados: dict[str, Any] = {
            'status_online_run_id': run_id,
            'status_online_started_at': time.time(),
        }
        if os_filtro:
            dados['os_filtro'] = os_filtro
        sessao.etapa = 'status_aguardando_online'
        sessao.dados_temp = dados
        sessao.save()
        from crm_app.services.pap_dispatcher import despachar_pap

        despachar_pap(
            'status_online',
            telefone_formatado,
            {
                'telefone': telefone_formatado,
                'cpf': cpf_para_consulta,
                'os_filtro': os_filtro,
                'run_id': run_id,
            },
            _executar_consulta_status_online_background,
            (telefone_formatado, cpf_para_consulta, os_filtro, run_id),
            prioridade=1,
        )
        resposta += '\n\n⏳ Consultando também no PAP (status online)... Aguarde.'
    else:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
    return resposta


_MSG_STATUS_PEDIR_IDENTIFICADOR = (
    "Para consultar o status do pedido, digite o *CPF* ou o número da *O.S* "
    "do cliente:\n\n"
    "• CPF: 11 dígitos (ex: 12345678901)\n"
    "• O.S: 8 dígitos (ex: 08907507) ou formato X-12dígitos "
    "(ex: 4-212051254235)\n\n"
    "Ou digite *CANCELAR* para sair."
)


def _normalizar_celular_digitos(celular: str) -> str:
    """Retorna apenas os dígitos do celular (para comparar com lista de rejeitados)."""
    if not celular:
        return ""
    return re.sub(r"\D", "", str(celular))


def _formatar_status_portugues(status):
    """Traduz status para português"""
    status_upper = str(status).upper()
    traducoes = {
        'OVERDUE': 'Atrasado',
        'PENDING': 'Pendente',
        'EM ABERTO': 'Em Aberto',
        'ABERTO': 'Em Aberto',
        'OPEN': 'Em Aberto',
        'VENCIDA': 'Vencida',
        'VENCIDO': 'Vencido',
        'LATE': 'Atrasado',
        'PAID': 'Pago',
        'PAGO': 'Pago',
    }
    return traducoes.get(status_upper, status)


def _formatar_data_brasileira(data_str):
    """Converte data de formato YYYYMMDD ou YYYY-MM-DD para dd/mm/aaaa"""
    if not data_str:
        return None
    
    try:
        # Formato YYYYMMDD (ex: 20251230)
        if isinstance(data_str, str) and len(data_str) == 8 and data_str.isdigit():
            from datetime import datetime
            data = datetime.strptime(data_str, '%Y%m%d')
            return data.strftime('%d/%m/%Y')
        
        # Formato YYYY-MM-DD (ex: 2025-12-30)
        elif isinstance(data_str, str) and '-' in data_str:
            from datetime import datetime
            data = datetime.strptime(data_str, '%Y-%m-%d')
            return data.strftime('%d/%m/%Y')
        
        # Já está formatado ou é objeto date
        elif hasattr(data_str, 'strftime'):
            return data_str.strftime('%d/%m/%Y')
        
        # Tentar parsear outros formatos
        else:
            from datetime import datetime
            # Tenta vários formatos comuns
            for fmt in ['%Y-%m-%d', '%Y%m%d', '%d/%m/%Y', '%d-%m-%Y']:
                try:
                    data = datetime.strptime(str(data_str), fmt)
                    return data.strftime('%d/%m/%Y')
                except:
                    continue
            
            return str(data_str)  # Retorna original se não conseguir converter
    except Exception as e:
        logger.warning(f"[Webhook] Erro ao formatar data {data_str}: {e}")
        return str(data_str)


def _build_serve_pdf_url(request, filename):
    """
    Gera URL pública do PDF com token assinado (para Z-API buscar o arquivo).
    Só funciona se o servidor for acessível pela internet (ex.: Railway, ngrok).
    """
    import hmac
    import base64
    if not request or not filename:
        return ""
    secret = (getattr(settings, "SECRET_KEY", "") or "").encode("utf-8")
    sig = hmac.new(secret, filename.encode("utf-8"), "sha256").hexdigest()[:32]
    payload_b64 = base64.urlsafe_b64encode(filename.encode("utf-8")).decode("utf-8").rstrip("=")
    token = f"{payload_b64}.{sig}"
    return request.build_absolute_uri(f"/api/crm/serve-pdf/{token}/")


def _enviar_pdf_whatsapp(whatsapp_service, telefone, invoice, caption=None):
    """
    Envia o PDF da fatura via WhatsApp se estiver disponível (localmente ou via URL).
    Retorna True se enviou com sucesso, False caso contrário.
    
    Args:
        whatsapp_service: Instância do WhatsAppService
        telefone: Número do destinatário
        invoice: Dicionário com informações da fatura (incluindo pdf_path, pdf_url, etc)
        caption: Mensagem de legenda para o PDF (opcional)
    """
    pdf_path = invoice.get('pdf_path', '')
    pdf_url = invoice.get('pdf_url', '') or invoice.get('pdf_onedrive_url', '')
    pdf_filename = invoice.get('pdf_filename', 'fatura.pdf')
    
    logger.info(f"[Webhook] 📄 _enviar_pdf_whatsapp chamado")
    logger.info(f"[Webhook] PDF path: {pdf_path}")
    logger.info(f"[Webhook] PDF URL: {pdf_url}")
    logger.info(f"[Webhook] PDF filename: {pdf_filename}")
    logger.info(f"[Webhook] Telefone: {telefone}")
    print(f"[Webhook] Iniciando _enviar_pdf_whatsapp: path={pdf_path}, url={pdf_url}, filename={pdf_filename}")
    
    # Prioridade 1: Tentar enviar via URL (mais rápido e eficiente)
    if pdf_url:
        logger.info(f"[Webhook] 📎 Tentando enviar PDF via URL: {pdf_url}")
        print(f"[Webhook] Enviando PDF via URL: {pdf_url}")
        try:
            sucesso = whatsapp_service.enviar_pdf_url(telefone, pdf_url, pdf_filename, caption=caption)
            if sucesso:
                logger.info(f"[Webhook] ✅ PDF enviado com sucesso via URL: {pdf_filename}")
                print(f"[Webhook] ✅ PDF enviado com sucesso via URL")
                return True
            else:
                logger.warning(f"[Webhook] ⚠️ Falha ao enviar PDF via URL, tentando método local...")
                print(f"[Webhook] ⚠️ Falha via URL, tentando local...")
        except Exception as e:
            logger.error(f"[Webhook] ❌ Erro ao enviar PDF via URL: {type(e).__name__}: {e}")
            print(f"[Webhook] ❌ Erro via URL: {e}")
            # Continuar para tentar método local
    
    # Prioridade 2: Tentar enviar via arquivo local (base64)
    if not pdf_path:
        logger.warning(f"[Webhook] ⚠️ PDF path vazio e URL não disponível, não é possível enviar")
        print(f"[Webhook] ⚠️ PDF path vazio e URL não disponível")
        return False
    
    try:
        import base64
        
        # Verificar se o arquivo existe
        if not os.path.exists(pdf_path):
            logger.warning(f"[Webhook] ❌ PDF não encontrado no caminho: {pdf_path}")
            print(f"[Webhook] ❌ Arquivo não existe: {pdf_path}")
            return False
        
        logger.info(f"[Webhook] ✅ Arquivo PDF encontrado, lendo...")
        print(f"[Webhook] Arquivo encontrado, tamanho: {os.path.getsize(pdf_path)} bytes")
        
        # Ler arquivo e converter para base64
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        logger.info(f"[Webhook] PDF lido e convertido para base64")
        logger.info(f"[Webhook] Tamanho original: {len(pdf_bytes)} bytes")
        logger.info(f"[Webhook] Tamanho base64: {len(pdf_base64)} chars")
        print(f"[Webhook] PDF convertido: {len(pdf_bytes)} bytes -> {len(pdf_base64)} chars base64")
        
        # Enviar via WhatsApp
        logger.info(f"[Webhook] Enviando PDF via WhatsApp (base64): {pdf_filename} ({len(pdf_bytes)} bytes)")
        if caption:
            logger.info(f"[Webhook] Com caption: {caption[:100]}...")
        print(f"[Webhook] Chamando enviar_pdf_b64...")
        sucesso = whatsapp_service.enviar_pdf_b64(telefone, pdf_base64, pdf_filename, caption=caption)
        
        if sucesso:
            logger.info(f"[Webhook] ✅ PDF enviado com sucesso via WhatsApp: {pdf_filename}")
            print(f"[Webhook] ✅ PDF enviado com sucesso")
        else:
            logger.warning(f"[Webhook] ⚠️ Falha ao enviar PDF via WhatsApp: {pdf_filename}")
            print(f"[Webhook] ⚠️ Falha ao enviar PDF")
        
        return sucesso
    except FileNotFoundError as fnfe:
        logger.error(f"[Webhook] ❌ Arquivo não encontrado: {fnfe}")
        print(f"[Webhook] ❌ FILE NOT FOUND: {fnfe}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        logger.error(f"[Webhook] ❌ Erro ao enviar PDF via WhatsApp: {type(e).__name__}: {e}")
        print(f"[Webhook] ❌ EXCEÇÃO: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def _formatar_detalhes_fatura(invoice, cpf, incluir_pdf=False):
    """
    Formata os detalhes de uma fatura para envio via WhatsApp.
    """
    resposta_parts = [f"✅ *FATURA ENCONTRADA*\n"]
    
    # Valor
    valor = invoice.get('amount', 0)
    if valor:
        try:
            valor_formatado = float(valor) if valor else 0
            resposta_parts.append(f"💰 *Valor:* R$ {valor_formatado:.2f}")
        except:
            resposta_parts.append(f"💰 *Valor:* {valor}")
    
    # Data de vencimento (formatada em dd/mm/aaaa)
    data_vencimento = invoice.get('due_date_raw') or invoice.get('data_vencimento')
    if data_vencimento:
        data_formatada = _formatar_data_brasileira(data_vencimento)
        resposta_parts.append(f"📅 *Vencimento:* {data_formatada}")
    
    # Status (traduzido para português)
    status = invoice.get('status', '')
    if status:
        status_pt = _formatar_status_portugues(status)
        emoji_status = "🔴" if status.upper() in ['ATRASADO', 'ATRASADA', 'VENCIDA', 'VENCIDO', 'OVERDUE', 'LATE'] else "🟡"
        resposta_parts.append(f"{emoji_status} *Status:* {status_pt}")
    
    # Mês de referência
    mes_ref = invoice.get('reference_month', '')
    if mes_ref:
        resposta_parts.append(f"📆 *Referência:* {mes_ref}")
    
    # Código PIX
    codigo_pix = invoice.get('pix', '') or invoice.get('codigo_pix', '')
    if codigo_pix:
        # Remover backticks do início e fim do código PIX se existirem
        codigo_pix_limpo = codigo_pix.strip('`').strip()
        resposta_parts.append(f"\n💳 *PIX:*\n{codigo_pix_limpo}")
    
    # Código de barras
    codigo_barras = invoice.get('barcode', '') or invoice.get('codigo_barras', '')
    if codigo_barras:
        # Remover backticks do início e fim do código de barras se existirem
        codigo_barras_limpo = codigo_barras.strip('`').strip()
        resposta_parts.append(f"\n📄 *Código de Barras:*\n{codigo_barras_limpo}")
    
    # PDF (não incluir link na mensagem - será enviado como anexo)
    # O PDF será enviado separadamente como anexo, então não precisamos incluir o link na mensagem
    # if incluir_pdf:
    #     # Removido: não incluir link do PDF na mensagem
    #     pass
    
    return "\n".join(resposta_parts)


# =============================================================================
# FUNÇÕES PARA FLUXO DE ANÁLISE DE CRÉDITO VIA WHATSAPP
# =============================================================================

# Endereço fixo para análise de crédito (loja)
CREDITO_CEP_FIXO = "32140000"
CREDITO_NUMERO_FIXO = "712"
CREDITO_REFERENCIA_FIXA = "do lado da mecânica"
CREDITO_ENDERECO_ALVO = "Avenida Fernão Dias"  # Para selecionar em múltiplos endereços
CREDITO_LIMITE_DIARIO = 15
CREDITO_INTERVALO_MIN_SEG = 60  # 1 minuto entre análises
STATUS_ONLINE_MAX_WAIT_SECONDS = 180  # evita sessão "presa" em aguardando_online


def _buscar_usuario_por_telefone(telefone: str):
    """Busca usuário ativo por qualquer um dos 3 números de WhatsApp."""
    from usuarios.models import Usuario
    telefone_limpo = re.sub(r'\D', '', telefone)
    telefones_variantes = {telefone_limpo}
    if telefone_limpo.startswith('55') and len(telefone_limpo) > 11:
        telefones_variantes.add(telefone_limpo[2:])
    if not telefone_limpo.startswith('55') and len(telefone_limpo) >= 10:
        telefones_variantes.add('55' + telefone_limpo)
    if len(telefone_limpo) >= 8:
        telefones_variantes.add(telefone_limpo[-8:])
    if len(telefone_limpo) >= 9:
        telefones_variantes.add(telefone_limpo[-9:])
    for tel_var in telefones_variantes:
        usuario = Usuario.objects.filter(
            is_active=True
        ).extra(
            where=["REPLACE(REPLACE(REPLACE(REPLACE(tel_whatsapp, '-', ''), ' ', ''), '(', ''), ')', '') LIKE %s"],
            params=[f'%{tel_var}%']
        ).first()
        if usuario:
            return usuario
    for tel_var in telefones_variantes:
        usuario = Usuario.objects.filter(tel_whatsapp__icontains=tel_var, is_active=True).first()
        if usuario:
            return usuario
        usuario = Usuario.objects.filter(tel_whatsapp_2__icontains=tel_var, is_active=True).first()
        if usuario:
            return usuario
        usuario = Usuario.objects.filter(tel_whatsapp_3__icontains=tel_var, is_active=True).first()
        if usuario:
            return usuario
    return None


def _primeiro_nome_usuario(usuario) -> str:
    """Retorna primeiro nome amigável para mensagens do bot."""
    try:
        nome = (usuario.get_full_name() or "").strip()
    except Exception:
        nome = ""
    base = nome or (getattr(usuario, "first_name", "") or "").strip() or (getattr(usuario, "username", "") or "").strip()
    if not base:
        return "BackOffice"
    return base.split()[0]


def _verificar_limites_credito(usuario) -> tuple:
    """
    Verifica limites de análise de crédito.
    Returns: (ok: bool, msg_erro: str ou None)
    - 1 min desde o fim da última análise
    - 15 por dia (horário Brasília)
    """
    from crm_app.models import AnaliseCreditoHistorico
    from django.utils import timezone
    import pytz
    tz_brasilia = pytz.timezone('America/Sao_Paulo')
    agora = timezone.now()
    agora_br = agora.astimezone(tz_brasilia)
    # Limite 1 min: última análise
    ultima = AnaliseCreditoHistorico.objects.filter(usuario=usuario).order_by('-criado_em').first()
    if ultima:
        diff_seg = (agora - ultima.criado_em).total_seconds()
        if diff_seg < CREDITO_INTERVALO_MIN_SEG:
            faltam = int(CREDITO_INTERVALO_MIN_SEG - diff_seg)
            return False, f"Aguarde *{faltam} segundos* para fazer outra análise."
    # Limite 15 por dia
    inicio_hoje = agora_br.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_hoje_utc = inicio_hoje.astimezone(pytz.utc)
    count_hoje = AnaliseCreditoHistorico.objects.filter(
        usuario=usuario,
        criado_em__gte=inicio_hoje_utc
    ).count()
    if count_hoje >= CREDITO_LIMITE_DIARIO:
        return False, "Limite diário de análises atingido (15/dia). Tente novamente amanhã."
    return True, None


def _iniciar_fluxo_credito(telefone: str, sessao) -> str:
    """
    Inicia o fluxo de análise de crédito via WhatsApp.
    Valida autorizar_analise_credito_wpp e limites (1 min, 15/dia).
    """
    usuario = _buscar_usuario_por_telefone(telefone)
    if not usuario:
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Seu número não está cadastrado no sistema.\n"
            "Verifique se o campo WhatsApp está preenchido no seu cadastro."
        )
    if not getattr(usuario, 'autorizar_analise_credito_wpp', False):
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Você não está autorizado a fazer análise de crédito pelo WhatsApp.\n"
            "Solicite que marquem a opção 'Autorizar fazer análise de crédito pelo Wpp' no seu cadastro."
        )
    ok, msg_erro = _verificar_limites_credito(usuario)
    if not ok:
        return f"❌ {msg_erro}"
    sessao.etapa = 'credito_cpf'
    sessao.dados_temp = {'usuario_id': usuario.id, 'usuario_nome': usuario.get_full_name() or usuario.username}
    sessao.save()
    return (
        "🔍 *ANÁLISE DE CRÉDITO*\n\n"
        "Digite o *CPF ou CNPJ* a ser consultado (apenas números):\n\n"
        "Se for CNPJ, em seguida vou pedir o CPF do representante legal.\n\n"
        "Ou digite *CANCELAR* para sair."
    )


def _run_django_sync(func, timeout_seconds: int = 120):
    """Executa operações Django/ORM/WhatsApp em thread sem event loop (evita SynchronousOnlyOperation após Playwright)."""
    import queue
    q = queue.Queue()
    def worker():
        try:
            import django.db
            django.db.close_old_connections()
            func()
            q.put(None)
        except Exception as e:
            q.put(e)
    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        exc = q.get()
        if exc is not None:
            raise exc
    elif t.is_alive():
        logger.error(
            "[Webhook] _run_django_sync expirou após %ss — resposta WhatsApp pode não ter sido enviada.",
            timeout_seconds,
        )


def _run_orm_returning(callable, timeout_seconds: int = 60):
    """Executa callable ORM em thread dedicada e retorna o valor (após Playwright async context)."""
    result: list = [None]
    exc_holder: list = [None]

    def worker() -> None:
        try:
            import django.db
            django.db.close_old_connections()
            result[0] = callable()
        except Exception as e:
            exc_holder[0] = e

    t = threading.Thread(target=worker, name="orm-sync-returning")
    t.start()
    t.join(timeout=timeout_seconds)
    if exc_holder[0]:
        raise exc_holder[0]
    if t.is_alive():
        raise TimeoutError(f"_run_orm_returning expirou após {timeout_seconds}s")
    return result[0]


def _executar_analise_credito_background(telefone: str, usuario_id: int, documento: str, cpf_representante: str = None):
    """
    Thread: executa análise de crédito no PAP (login BO, viabilidade fixa, etapa3 CPF, etapa4 random).
    Envia resultado via WhatsApp e salva em AnaliseCreditoHistorico.
    """
    from usuarios.models import Usuario
    from crm_app.models import AnaliseCreditoHistorico, SessaoWhatsapp
    from crm_app.services_pap_nio import PAPNioAutomation
    from crm_app.pool_bo_pap import (
        obter_login_bo,
        liberar_bo,
        MSG_TODOS_ACESSOS_EM_USO,
        obter_mensagem_fila_ocupado,
        atualizar_historico_consulta_pap_resultado,
    )
    from crm_app.services.assertiva_localize_service import (
        AssertivaError,
        AssertivaLocalizeService,
        DadosCreditoAssertiva,
    )
    from crm_app.services.credito_pap_service import (
        CODIGOS_EMAIL_RECUSADO,
        CODIGOS_TELEFONE_RECUSADO,
        ORIGEM_PADRAO as ORIGEM_ENDERECO_PADRAO,
        EnderecoCredito,
        SeletorContatosCredito,
        classificar_formas_pagamento,
        consultar_viabilidade_com_fallback,
        montar_tentativas_endereco,
        resumo_origem_dados,
    )
    from crm_app.services.credito_contato_repo import RepositorioEmailsRecusadosPap
    from crm_app.controle_tts_service import (
        obter_matricula_tt_para_credito_pap,
        pular_tt_credito_indisponivel,
        registrar_uso_tt_credito,
    )
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.cadastro_venda_whatsapp import validar_cpf_ou_cnpj_whatsapp
    import re

    usuario = Usuario.objects.get(id=usuario_id)
    documento_limpo = re.sub(r'\D', '', documento or "")
    if len(documento_limpo) not in (11, 14):
        WhatsAppService().enviar_mensagem_texto(telefone, "❌ Documento inválido (use CPF com 11 dígitos ou CNPJ com 14 dígitos). Digite *CRÉDITO* para tentar novamente.")
        try:
            s = SessaoWhatsapp.objects.get(telefone=telefone)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        return

    # Validar documento (CPF/CNPJ) antes de abrir PAP — falha rápida, evita timeout na Etapa 3
    doc_validado, err_val = validar_cpf_ou_cnpj_whatsapp(documento)
    if err_val or not doc_validado:
        WhatsAppService().enviar_mensagem_texto(telefone, "❌ Documento inválido. Digite um CPF (11) ou CNPJ (14) válido. Digite *CRÉDITO* para tentar novamente.")
        try:
            s = SessaoWhatsapp.objects.get(telefone=telefone)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        return
    documento_limpo = doc_validado
    cpf_rep_limpo = re.sub(r'\D', '', str(cpf_representante or ""))
    if len(documento_limpo) == 14 and len(cpf_rep_limpo) != 11:
        WhatsAppService().enviar_mensagem_texto(
            telefone,
            "❌ Para consulta por CNPJ, preciso do CPF do representante legal (11 dígitos). Digite *CRÉDITO* para tentar novamente.",
        )
        try:
            s = SessaoWhatsapp.objects.get(telefone=telefone)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        return

    analise_historico = AnaliseCreditoHistorico.objects.create(
        usuario=usuario,
        cpf_consultado=documento_limpo,
        telefone_solicitante=telefone,
        status_execucao=AnaliseCreditoHistorico.STATUS_PENDENTE,
    )

    # Preenchido durante a automação (endereço/contatos efetivamente usados) e
    # gravado em qualquer desfecho, inclusive quando o PAP falha no meio.
    registro_execucao: dict[str, Any] = {}

    def _atualizar_analise_historico(**campos: Any) -> None:
        """Persiste cada etapa sem perder a consulta se o PAP falhar depois."""
        from django.utils import timezone

        campos = {**registro_execucao, **campos}
        campos["atualizado_em"] = timezone.now()
        AnaliseCreditoHistorico.objects.filter(
            pk=analise_historico.pk
        ).update(**campos)

    dados_assertiva: Optional[DadosCreditoAssertiva] = None
    if getattr(settings, "ASSERTIVA_CREDITO_ENABLED", False):
        try:
            dados_assertiva = AssertivaLocalizeService().consultar_para_credito(
                documento_limpo
            )
            # Nenhum campo é obrigatório: cada dado ausente cai no plano B
            # (celular sorteado, e-mail validado do pool, endereço padrão da
            # automação). O que faltou fica registrado para auditoria.
            campos_ausentes: list[str] = []
            if not dados_assertiva.telefone_principal:
                campos_ausentes.append("telefone")
            if not dados_assertiva.email_principal:
                campos_ausentes.append("e-mail")
            if not dados_assertiva.endereco:
                campos_ausentes.append("endereço")
            endereco_snapshot = dados_assertiva.endereco
            snapshot_assertiva = {
                "telefones": list(dados_assertiva.telefones),
                "emails": list(dados_assertiva.emails),
                "endereco": (
                    {
                        "cep": endereco_snapshot.cep,
                        "numero": endereco_snapshot.numero,
                        "referencia": endereco_snapshot.referencia,
                        "logradouro": endereco_snapshot.logradouro,
                    }
                    if endereco_snapshot
                    else None
                ),
            }
            _atualizar_analise_historico(
                assertiva_consultada=True,
                assertiva_dados=snapshot_assertiva,
                assertiva_erro=(
                    f"Assertiva sem {', '.join(campos_ausentes)}; "
                    "usando dados padrão da automação nesses campos."
                    if campos_ausentes
                    else ""
                ),
            )
            logger.info(
                "[CRÉDITO] Assertiva consultada: telefones=%s, emails=%s, endereco=%s",
                len(dados_assertiva.telefones),
                len(dados_assertiva.emails),
                bool(dados_assertiva.endereco),
            )
            if campos_ausentes:
                logger.info(
                    "[CRÉDITO] Assertiva sem %s; a automação completará esses "
                    "campos com os dados padrão.",
                    ", ".join(campos_ausentes),
                )
        except AssertivaError as exc:
            logger.warning(
                "[CRÉDITO] Consulta Assertiva indisponível (%s); seguindo com "
                "dados padrão da automação.",
                exc,
            )
            _atualizar_analise_historico(
                assertiva_consultada=False,
                assertiva_erro=str(exc)[:4000],
            )

    bo_usuario, msg_erro = obter_login_bo(telefone, None, tipo_automacao='credito')
    if not bo_usuario:
        _atualizar_analise_historico(
            status_execucao=AnaliseCreditoHistorico.STATUS_ERRO,
            resultado_detalhe=(msg_erro or "Login PAP indisponível")[:200],
        )
        if msg_erro == MSG_TODOS_ACESSOS_EM_USO:
            WhatsAppService().enviar_mensagem_texto(telefone, obter_mensagem_fila_ocupado(telefone, 'credito'))
        else:
            WhatsAppService().enviar_mensagem_texto(telefone, f"{msg_erro}\n\nDigite *CRÉDITO* para tentar novamente.")
        try:
            s = SessaoWhatsapp.objects.get(telefone=telefone)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        return

    automacao = None
    tempo_inicio = time.time()
    tempos = {}  # medição por etapa para reduzir tempo (meta: < 1 min)
    def _marcar_hist(sucesso: bool, mensagem: str = ""):
        try:
            atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=telefone,
                bo_usuario=bo_usuario,
                tipo_automacao='credito',
                sucesso=sucesso,
                mensagem_resultado=mensagem,
            )
            _atualizar_analise_historico(
                status_execucao=(
                    AnaliseCreditoHistorico.STATUS_SUCESSO
                    if sucesso
                    else AnaliseCreditoHistorico.STATUS_ERRO
                ),
                resultado_detalhe=(mensagem or "")[:200] or None,
            )
        except Exception:
            logger.exception(
                "[CRÉDITO] Falha ao atualizar histórico da consulta %s",
                analise_historico.pk,
            )
    try:
        bo_primeiro_nome = _primeiro_nome_usuario(bo_usuario)
        WhatsAppService().enviar_mensagem_texto(
            telefone,
            f"🙋‍♂️ Sou o BO *{bo_primeiro_nome}* e vou tratar sua consulta.\n\n⏳ Consultando crédito no PAP... Aguarde.",
        )
        headless = getattr(settings, 'PAP_HEADLESS', True)
        # Crédito precisa ser rápido: screenshots/trace desativados por padrão neste fluxo.
        capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS_CREDITO', False)
        optimize_for_credit = getattr(settings, 'PAP_CREDITO_FAST_MODE', True)
        automacao = PAPNioAutomation(
            matricula_pap=bo_usuario.matricula_pap,
            senha_pap=bo_usuario.senha_pap,
            vendedor_nome=f"Credito-{usuario.username}",
            headless=headless,
            capture_screenshots=capture_screenshots,
            optimize_for_credit=optimize_for_credit,
        )
        t0 = time.time()
        sucesso, msg = automacao.iniciar_sessao()
        tempos['login'] = round(time.time() - t0, 1)
        if not sucesso:
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, msg)
            WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Erro ao acessar PAP: {msg}\n\nDigite *CRÉDITO* para tentar novamente.")
            _resetar_sessao_credito(telefone)
            return
        logger.info("[CRÉDITO] Tempo: login=%ss (acumulado=%ss)", tempos['login'], round(time.time() - tempo_inicio, 1))

        matricula_fallback = (usuario.matricula_pap or bo_usuario.matricula_pap or "").strip()
        matricula_pedido = None
        sucesso = False
        msg = ""
        t0 = time.time()
        excluir_tt: set[str] = set()

        ok_prep, msg_prep = automacao._preparar_novo_pedido_etapa1()
        if not ok_prep:
            automacao._fechar_sessao()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, msg_prep)
            WhatsAppService().enviar_mensagem_texto(
                telefone,
                f"❌ Erro ao iniciar pedido: {msg_prep}\n\nDigite *CRÉDITO* para tentar novamente.",
            )
            _resetar_sessao_credito(telefone)
            return

        # Sempre lê a lista real do PDV e percorre em sequência (1º, 2º…).
        # Evita matrículas da OSAB que não existem no PAP deste login BO.
        forcar_osab = bool(
            getattr(settings, "PAP_CREDITO_SKIP_LISTA_VENDEDORES", False)
        )
        matriculas_pap: list[str] = []
        if forcar_osab:
            logger.warning(
                "[CRÉDITO] PAP_CREDITO_SKIP_LISTA_VENDEDORES=1 — pool OSAB (legado)"
            )
        else:
            matriculas_pap = automacao.listar_matriculas_vendedor_no_pap()
            if not matriculas_pap:
                automacao._cache_matriculas_pap_dropdown = []
                matriculas_pap = automacao.listar_matriculas_vendedor_no_pap(
                    forcar_recarga=True
                )
            if not matriculas_pap:
                automacao._cache_matriculas_pap_dropdown = []
                logger.warning(
                    "[CRÉDITO] Lista vendedores vazia — tentativa paciente"
                )
                matriculas_pap = automacao.listar_matriculas_vendedor_no_pap(
                    forcar_recarga=True,
                    paciente=True,
                )

        usar_pool_osab = forcar_osab or not matriculas_pap
        if usar_pool_osab:
            if not forcar_osab:
                automacao._capture_screenshot_falha_etapa1(
                    "01_err_lista_vendedores_vazia",
                    wait_selector=None,
                    wait_timeout_ms=0,
                )
                logger.warning(
                    "[CRÉDITO] Dropdown vazio após tentativas — fallback pool OSAB"
                )
            candidatos_pap: list = []
            max_tentativas_tt = 8
        else:
            candidatos_pap = list(matriculas_pap)
            max_tentativas_tt = min(max(5, len(candidatos_pap)), 10)
            logger.info(
                "[CRÉDITO] Lista PAP sequencial: %s matrícula(s) — amostra: %s",
                len(candidatos_pap),
                candidatos_pap[:8],
            )

        bo_matricula_cursor = (bo_usuario.matricula_pap or "").strip()
        for tentativa_tt in range(1, max_tentativas_tt + 1):
            if not usar_pool_osab:
                cache_pap = automacao.obter_cache_matriculas_pap_dropdown()
                if cache_pap:
                    candidatos_pap = cache_pap
            matricula_pedido = _run_orm_returning(
                lambda fb=matricula_fallback, ex=set(excluir_tt), cand=None if usar_pool_osab else list(candidatos_pap), bo=bo_matricula_cursor, seq=not usar_pool_osab: obter_matricula_tt_para_credito_pap(
                    fb,
                    excluir=ex,
                    candidatos=cand,
                    bo_matricula=bo,
                    sequencial_pap=seq,
                )
            )
            logger.info(
                "[CRÉDITO] TT sequencial (tentativa %s/%s): %s",
                tentativa_tt,
                max_tentativas_tt,
                matricula_pedido,
            )
            sucesso, msg = automacao._concluir_novo_pedido_etapa1(matricula_pedido)
            if sucesso:
                _run_django_sync(
                    lambda m=matricula_pedido: registrar_uso_tt_credito(m)
                )
                break
            msg_lower = (msg or "").lower()
            tt_indisponivel = (
                "não encontrada no pap" in msg_lower
                or "nao encontrada no pap" in msg_lower
                or "não está entre os" in msg_lower
                or "nao esta entre os" in msg_lower
                or "não foi possível selecionar o vendedor" in msg_lower
                or "nao foi possivel selecionar o vendedor" in msg_lower
            )
            if tt_indisponivel and tentativa_tt < max_tentativas_tt:
                logger.warning(
                    "[CRÉDITO] TT %s indisponível no PAP; tentando outro da fila.",
                    matricula_pedido,
                )
                _run_django_sync(
                    lambda m=matricula_pedido: pular_tt_credito_indisponivel(m)
                )
                excluir_tt.add(matricula_pedido)
                continue
            break
        tempos['pedido'] = round(time.time() - t0, 1)
        if not sucesso:
            automacao._fechar_sessao()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, msg)
            WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Erro ao iniciar pedido: {msg}\n\nDigite *CRÉDITO* para tentar novamente.")
            _resetar_sessao_credito(telefone)
            return
        logger.info("[CRÉDITO] Tempo: pedido=%ss (acumulado=%ss)", tempos['pedido'], round(time.time() - tempo_inicio, 1))

        t0 = time.time()
        ok_tela, msg_tela = automacao.validar_tela_pronta_para_cep()
        tempos['tela'] = round(time.time() - t0, 1)
        if not ok_tela:
            automacao._fechar_sessao()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, msg_tela)
            WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Página não pronta: {msg_tela}\n\nDigite *CRÉDITO* para tentar novamente.")
            _resetar_sessao_credito(telefone)
            return
        logger.info("[CRÉDITO] Tempo: tela=%ss (acumulado=%ss)", tempos['tela'], round(time.time() - tempo_inicio, 1))

        # Etapa 2: endereço real da Assertiva primeiro; sem viabilidade, cai para
        # o endereço padrão da automação (registrado no histórico da consulta).
        endereco_assertiva = dados_assertiva.endereco if dados_assertiva else None
        tentativas_endereco = montar_tentativas_endereco(
            endereco_assertiva,
            endereco_padrao=EnderecoCredito(
                cep=CREDITO_CEP_FIXO,
                numero=CREDITO_NUMERO_FIXO,
                referencia=CREDITO_REFERENCIA_FIXA,
                logradouro=CREDITO_ENDERECO_ALVO,
                origem=ORIGEM_ENDERECO_PADRAO,
            ),
        )
        t0 = time.time()
        resultado_endereco = consultar_viabilidade_com_fallback(
            automacao,
            tentativas_endereco,
        )
        sucesso = resultado_endereco.sucesso
        msg = resultado_endereco.mensagem
        endereco_usado = resultado_endereco.endereco
        registro_execucao["endereco_utilizado"] = {
            **(endereco_usado.como_dict() if endereco_usado else {}),
            "viavel": sucesso,
            "bloqueios": resultado_endereco.bloqueios,
        }
        tempos['etapa2'] = round(time.time() - t0, 1)
        logger.info("[CRÉDITO] Tempo: etapa2=%ss (acumulado=%ss)", tempos['etapa2'], round(time.time() - tempo_inicio, 1))

        if not sucesso:
            automacao._fechar_sessao()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, msg)
            prefixo = "" if (msg or "").lstrip().startswith("❌") else "❌ "
            WhatsAppService().enviar_mensagem_texto(
                telefone,
                f"{prefixo}{msg}\n\nDigite *CRÉDITO* para tentar novamente.",
            )
            _resetar_sessao_credito(telefone)
            return
        if resultado_endereco.usou_fallback:
            logger.warning(
                "[CRÉDITO] Consulta seguiu com endereço padrão da automação "
                "(bloqueios: %s).",
                "; ".join(resultado_endereco.bloqueios) or "-",
            )

        # Etapa 3: Documento (CPF/CNPJ)
        t0 = time.time()
        sucesso, msg, extra_etapa3 = automacao.etapa3_cadastro_cliente(
            documento_limpo, cpf_representante=cpf_rep_limpo or None
        )
        # Pedido/Posse encontrado só aparece após Buscar o CPF neste endereço:
        # fecha o modal, consulta o CEP padrão e refaz a etapa 3.
        bloqueio_end = (
            (extra_etapa3 or {}).get("bloqueio_endereco")
            if isinstance(extra_etapa3, dict)
            else None
        )
        # Retry só se ainda estávamos no endereço da Assertiva.
        if (
            not sucesso
            and bloqueio_end
            and endereco_usado
            and endereco_usado.origem != ORIGEM_ENDERECO_PADRAO
            and len(tentativas_endereco) > 1
        ):
            endereco_padrao = tentativas_endereco[-1]
            logger.warning(
                "[CRÉDITO] Etapa3 bloqueou endereço assertiva (%s) — "
                "reconsultando com endereço padrão %s/%s",
                bloqueio_end,
                endereco_padrao.cep,
                endereco_padrao.numero,
            )
            ok_reset, msg_reset = automacao.etapa2_preparar_nova_consulta_endereco(
                bloqueio_end
            )
            if ok_reset:
                from crm_app.services.credito_pap_service import _executar_etapa2

                ok_padrao, msg_padrao, _extra_padrao = _executar_etapa2(
                    automacao, endereco_padrao
                )
                if ok_padrao:
                    bloqueio_resumo = (
                        f"assertiva:{endereco_usado.cep}/{endereco_usado.numero} "
                        f"- {bloqueio_end} (etapa3)"
                    )
                    resultado_endereco.endereco = endereco_padrao
                    resultado_endereco.bloqueios.append(bloqueio_resumo)
                    resultado_endereco.sucesso = True
                    endereco_usado = endereco_padrao
                    registro_execucao["endereco_utilizado"] = {
                        **endereco_padrao.como_dict(),
                        "viavel": True,
                        "bloqueios": list(resultado_endereco.bloqueios),
                    }
                    sucesso, msg, extra_etapa3 = automacao.etapa3_cadastro_cliente(
                        documento_limpo, cpf_representante=cpf_rep_limpo or None
                    )
                else:
                    msg = msg_padrao or msg
                    sucesso = False
            else:
                logger.warning(
                    "[CRÉDITO] Não foi possível voltar ao CEP após bloqueio etapa3: %s",
                    msg_reset,
                )
        tempos['etapa3'] = round(time.time() - t0, 1)
        if not sucesso:
            automacao._fechar_sessao()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, msg)
            prefixo = "" if (msg or "").lstrip().startswith("❌") else "❌ "
            WhatsAppService().enviar_mensagem_texto(
                telefone,
                f"{prefixo}{msg}\n\nDigite *CRÉDITO* para tentar novamente.",
            )
            _resetar_sessao_credito(telefone)
            return
        logger.info("[CRÉDITO] Tempo: etapa3=%ss (acumulado=%ss)", tempos['etapa3'], round(time.time() - tempo_inicio, 1))

        # Etapa 4: contatos reais da Assertiva; quando o PAP recusa todos, o
        # seletor volta para celular aleatório e e-mail validado do pool.
        seletor_contatos = SeletorContatosCredito(
            telefones=dados_assertiva.telefones if dados_assertiva else (),
            emails=dados_assertiva.emails if dados_assertiva else (),
            repositorio=RepositorioEmailsRecusadosPap(),
        )
        contato = seletor_contatos.atual()
        max_tentativas = 6
        screenshot_credito_b64 = None
        erro_contato = ""
        t0 = time.time()
        for tentativa in range(max_tentativas):
            sucesso, msg, resultado_credito, screenshot_credito_b64 = automacao.etapa4_contato(
                contato.telefone,
                contato.email,
                celular_secundario=contato.telefone_secundario,
                parar_no_modal_credito=True,
            )
            if sucesso or msg == "CREDITO_NEGADO":
                break
            if msg in CODIGOS_TELEFONE_RECUSADO:
                contato = seletor_contatos.proximo_telefone()
                logger.info(
                    "[CRÉDITO] Telefone recusado/inválido pelo PAP (%s); "
                    "nova origem=%s.",
                    msg,
                    contato.origem_telefone,
                )
                continue
            if msg in CODIGOS_EMAIL_RECUSADO:
                contato = seletor_contatos.email_recusado(msg)
                logger.info(
                    "[CRÉDITO] E-mail recusado pelo PAP (%s); nova origem=%s.",
                    msg,
                    contato.origem_email,
                )
                continue
            erro_contato = msg or "Falha na etapa de contato."
            break
        else:
            erro_contato = (
                "Não foi possível validar telefone/e-mail no PAP após "
                f"{max_tentativas} tentativas."
            )
        registro_execucao["origem_contato"] = seletor_contatos.origem_contato
        registro_execucao["contato_utilizado"] = contato.como_dict()
        if erro_contato:
            automacao._fechar_sessao()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(False, erro_contato)
            if erro_contato.lstrip().startswith("❌"):
                texto_erro = f"{erro_contato}\n\nDigite *CRÉDITO* para tentar novamente."
            else:
                texto_erro = (
                    f"❌ Erro na análise: {erro_contato}\n\n"
                    "Digite *CRÉDITO* para tentar novamente."
                )
            WhatsAppService().enviar_mensagem_texto(telefone, texto_erro)
            _resetar_sessao_credito(telefone)
            return
        tempos['etapa4'] = round(time.time() - t0, 1)
        logger.info("[CRÉDITO] Tempo: etapa4=%ss (acumulado=%ss)", tempos['etapa4'], round(time.time() - tempo_inicio, 1))

        aprovado = msg != "CREDITO_NEGADO" and sucesso
        resultado_detalhe = (resultado_credito or "") if sucesso else None
        # No negado, a etapa 4 devolve o motivo lido no modal em resultado_credito.
        motivo_negativa = "" if aprovado else (resultado_credito or "")
        formas_pagamento = (
            classificar_formas_pagamento(resultado_detalhe) if aprovado else ""
        )
        tempo_decorrido = round(time.time() - tempo_inicio, 1)
        # Resumo de tempos para análise (meta: total < 60s)
        logger.info(
            "[CRÉDITO] Tempo total: %ss | login=%ss, pedido=%ss, tela=%ss, etapa2=%ss, etapa3=%ss, etapa4=%ss",
            tempo_decorrido,
            tempos.get('login', '-'),
            tempos.get('pedido', '-'),
            tempos.get('tela', '-'),
            tempos.get('etapa2', '-'),
            tempos.get('etapa3', '-'),
            tempos.get('etapa4', '-'),
        )
        automacao._fechar_sessao()  # fechar na thread do Playwright
        # Playwright cria event loop na thread; ORM/WhatsApp precisam rodar em thread sem event loop
        def _salvar_e_enviar():
            import django.db
            django.db.close_old_connections()
            _atualizar_analise_historico(
                aprovado=aprovado,
                resultado_detalhe=resultado_detalhe,
                formas_pagamento=formas_pagamento,
                motivo_negativa=motivo_negativa[:300],
                status_execucao=AnaliseCreditoHistorico.STATUS_SUCESSO,
            )
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(
                True,
                resultado_detalhe
                or motivo_negativa
                or msg
                or "Consulta concluída com sucesso.",
            )
            _resetar_sessao_credito(telefone)
            if aprovado:
                resp = f"✅ *Crédito APROVADO!*\n\n{resultado_detalhe or 'Elegível para formas de pagamento disponíveis.'}"
            else:
                resp = "❌ *Crédito NEGADO* para este CPF."
                if motivo_negativa:
                    resp += f"\n\n📄 _Motivo informado pelo PAP: {motivo_negativa}_"
            if resultado_endereco.usou_fallback:
                resp += (
                    "\n\n📍 _O endereço cadastral do cliente não tem viabilidade; "
                    "a análise seguiu com o endereço padrão da automação._"
                )
            resp += f"\n\n{resumo_origem_dados(contato, resultado_endereco.endereco)}"
            resp += f"\n\n⏱ _{tempo_decorrido}s_"
            if screenshot_credito_b64:
                try:
                    WhatsAppService().enviar_imagem_b64(telefone, screenshot_credito_b64, caption=resp)
                except Exception as e_img:
                    logger.warning("[CRÉDITO] Erro ao enviar imagem do modal, enviando só texto: %s", e_img)
                    WhatsAppService().enviar_mensagem_texto(telefone, resp)
            else:
                WhatsAppService().enviar_mensagem_texto(telefone, resp)
        _run_django_sync(_salvar_e_enviar)
    except Exception as e:
        logger.exception("[CRÉDITO] Erro ao executar análise: %s", e)
        tempo_decorrido_erro = round(time.time() - tempo_inicio, 1)
        if automacao:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass
        def _erro_cleanup():
            try:
                liberar_bo(bo_usuario.id, telefone)
            except Exception:
                pass
            _marcar_hist(False, str(e))
            _resetar_sessao_credito(telefone)
            msg_erro = f"❌ Erro ao consultar crédito: {e}\n\nDigite *CRÉDITO* para tentar novamente.\n\n⏱ _{tempo_decorrido_erro}s_"
            WhatsAppService().enviar_mensagem_texto(telefone, msg_erro)
        _run_django_sync(_erro_cleanup)


def _resetar_sessao_credito(telefone: str):
    try:
        from crm_app.models import SessaoWhatsapp
        s = SessaoWhatsapp.objects.get(telefone=telefone)
        s.etapa = 'inicial'
        s.dados_temp = {}
        s.save()
    except Exception:
        pass


# =============================================================================
# FLUXO BIO (Consulta biometria no Br Pronto / ged360 por CPF)
# =============================================================================

def _iniciar_fluxo_bio(telefone: str, sessao) -> str:
    """Inicia consulta de biometria no Br Pronto via WhatsApp (comando BIO)."""
    usuario = _buscar_usuario_por_telefone(telefone)
    if not usuario:
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Seu número não está cadastrado no sistema.\n"
            "Verifique se o campo WhatsApp está preenchido no seu cadastro."
        )
    if not getattr(usuario, "autorizar_consulta_bio_wpp", False):
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Você não está autorizado a consultar biometria pelo WhatsApp.\n"
            "Solicite que marquem *Autorizar consulta Bio pelo Wpp* no seu cadastro (Governança)."
        )
    sessao.etapa = "bio_cpf"
    sessao.dados_temp = {
        "usuario_id": usuario.id,
        "usuario_nome": usuario.get_full_name() or usuario.username,
    }
    sessao.save()
    return (
        "🔍 *CONSULTA DE BIOMETRIA (Br Pronto)*\n\n"
        "Digite o *CPF* para consultar (apenas números):\n\n"
        "Ou digite *CANCELAR* para sair."
    )


def _resetar_sessao_bio(telefone: str) -> None:
    try:
        from crm_app.models import SessaoWhatsapp

        s = SessaoWhatsapp.objects.get(telefone=telefone)
        s.etapa = "inicial"
        s.dados_temp = {}
        s.save()
    except Exception:
        pass


def _formatar_resposta_bio(resultado: dict) -> str:
    """Monta mensagem WhatsApp a partir do resultado da consulta Br Pronto."""
    registros = resultado.get("registros") or []
    if resultado.get("aprovada"):
        data = resultado.get("data_mais_recente_apta") or ""
        return (
            "✅ *Biometria APROVADA*\n\n"
            'Status: *Doc. Apto para Venda*\n'
            + (f"Data envio mais recente: {data}\n" if data else "")
            + f"Registros encontrados: {len(registros)}"
        )
    if not registros:
        return (
            "⚠️ *Nenhum registro de biometria*\n\n"
            "Não há resultados no Relatório Detalhado para este CPF."
        )
    # Lista resumo dos status encontrados
    status_unicos: list[str] = []
    for r in registros:
        st = (r.get("resultado_analise") or "").strip() or "(vazio)"
        if st not in status_unicos:
            status_unicos.append(st)
    linhas = "\n".join(f"• {s}" for s in status_unicos[:8])
    return (
        "⏳ *Biometria NÃO apta para venda*\n\n"
        'Não há *"Doc. Apto para Venda"* para este CPF.\n\n'
        f"Status encontrados ({len(registros)} registro(s)):\n{linhas}"
    )


def _executar_consulta_bio_background(telefone: str, usuario_id: int, cpf: str) -> None:
    """
    Thread: reserva login Br Pronto do pool, consulta ged360 e envia resultado
    (texto + print da tela do relatório quando disponível).
    Sempre libera o lock e o serviço garante logoff no GED.
    """
    from django.conf import settings
    from usuarios.models import Usuario
    from crm_app.services_brpronto import consultar_biometria_brpronto
    from crm_app.pool_brpronto import (
        obter_login_brpronto,
        liberar_login_brpronto,
        MSG_TODOS_BRPRONTO_EM_USO,
    )
    from crm_app.whatsapp_service import WhatsAppService

    cpf_limpo = re.sub(r"\D", "", cpf)
    if len(cpf_limpo) != 11:
        WhatsAppService().enviar_mensagem_texto(
            telefone,
            "❌ CPF inválido (precisa 11 dígitos). Digite *BIO* para tentar novamente.",
        )
        _resetar_sessao_bio(telefone)
        return

    bo_usuario, msg_erro = obter_login_brpronto(telefone, origem="bio")
    if not bo_usuario:
        WhatsAppService().enviar_mensagem_texto(
            telefone,
            f"{msg_erro or MSG_TODOS_BRPRONTO_EM_USO}\n\nDigite *BIO* para tentar novamente.",
        )
        _resetar_sessao_bio(telefone)
        return

    tempo_inicio = time.time()
    try:
        headless = getattr(settings, "BRPRONTO_HEADLESS", True)
        sucesso, msg, resultado = consultar_biometria_brpronto(
            login=bo_usuario.brpronto_login or "",
            senha=bo_usuario.brpronto_senha or "",
            cpf=cpf_limpo,
            dominio=bo_usuario.brpronto_dominio or None,
            headless=headless,
        )
        tempo = round(time.time() - tempo_inicio, 1)
        whatsapp = WhatsAppService()
        if not sucesso:
            whatsapp.enviar_mensagem_texto(
                telefone,
                f"❌ Erro na consulta Br Pronto:\n{msg}\n\nDigite *BIO* para tentar novamente.\n\n⏱ _{tempo}s_",
            )
        else:
            corpo = _formatar_resposta_bio(resultado)
            caption = f"{corpo}\n\n⏱ _{tempo}s_"
            screenshot_b64 = (resultado or {}).get("screenshot_b64")
            if screenshot_b64:
                try:
                    whatsapp.enviar_imagem_b64(telefone, screenshot_b64, caption=caption)
                except Exception as e_img:
                    logger.warning(
                        "[BIO BrPronto] Erro ao enviar print, enviando só texto: %s",
                        e_img,
                    )
                    whatsapp.enviar_mensagem_texto(telefone, caption)
            else:
                whatsapp.enviar_mensagem_texto(telefone, caption)
    except Exception as e:
        logger.exception("[BIO BrPronto] Erro: %s", e)
        tempo = round(time.time() - tempo_inicio, 1)
        WhatsAppService().enviar_mensagem_texto(
            telefone,
            f"❌ Erro ao consultar biometria: {e}\n\nDigite *BIO* para tentar novamente.\n\n⏱ _{tempo}s_",
        )
    finally:
        liberar_login_brpronto(bo_usuario.id, telefone)
        _resetar_sessao_bio(telefone)


# =============================================================================
# FLUXO PEDIDO (Consulta OS no PAP por CPF)
# =============================================================================

def _iniciar_fluxo_pedido(telefone: str, sessao) -> str:
    """
    Inicia o fluxo de consulta de pedido/OS via WhatsApp.
    Login no PAP igual a crédito/vender; depois abre Consulta OS, Filtros e preenche CPF.
    Usa a mesma autorização que crédito (autorizar_analise_credito_wpp) e pool BO.
    """
    usuario = _buscar_usuario_por_telefone(telefone)
    if not usuario:
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Seu número não está cadastrado no sistema.\n"
            "Verifique se o campo WhatsApp está preenchido no seu cadastro."
        )
    if not getattr(usuario, 'autorizar_analise_credito_wpp', False):
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Você não está autorizado a consultar pedido pelo WhatsApp.\n"
            "Solicite que marquem a opção 'Autorizar fazer análise de crédito pelo Wpp' no seu cadastro."
        )
    sessao.etapa = 'pedido_cpf'
    sessao.dados_temp = {'usuario_id': usuario.id, 'usuario_nome': usuario.get_full_name() or usuario.username}
    sessao.save()
    return (
        "📋 *CONSULTA DE PEDIDO / O.S.*\n\n"
        "Digite o *CPF ou CNPJ* para consultar (apenas números):\n\n"
        "Ou digite *CANCELAR* para sair."
    )


def _resetar_sessao_pedido(telefone: str):
    try:
        from crm_app.models import SessaoWhatsapp
        s = SessaoWhatsapp.objects.get(telefone=telefone)
        s.etapa = 'inicial'
        s.dados_temp = {}
        s.save()
    except Exception:
        pass


def _executar_consulta_pedido_background(telefone: str, usuario_id: int, cpf: str):
    """
    Thread: loga no PAP, abre Consulta OS, período 30 dias, Filtrar, lê tabela e tira screenshot.
    Se houver pedido(s): envia mensagem com Status/Data/Plano e imagem da tela.
    Se não houver: envia "Não tem pedido com 30 dias" e imagem da tela.
    """
    import base64
    from usuarios.models import Usuario
    from crm_app.models import SessaoWhatsapp
    from crm_app.services_pap_nio import PAPNioAutomation
    from crm_app.pool_bo_pap import (
        obter_login_bo,
        liberar_bo,
        MSG_TODOS_ACESSOS_EM_USO,
        obter_mensagem_fila_ocupado,
        atualizar_historico_consulta_pap_resultado,
    )
    from crm_app.whatsapp_service import WhatsAppService

    usuario = Usuario.objects.get(id=usuario_id)
    cpf_limpo = re.sub(r'\D', '', cpf)
    if len(cpf_limpo) not in (11, 14):
        WhatsAppService().enviar_mensagem_texto(
            telefone,
            "❌ CPF/CNPJ inválido (precisa 11 ou 14 dígitos). Digite *PEDIDO* para tentar novamente."
        )
        _resetar_sessao_pedido(telefone)
        return

    bo_usuario, msg_erro = obter_login_bo(telefone, None, tipo_automacao='pedido')
    if not bo_usuario:
        if msg_erro == MSG_TODOS_ACESSOS_EM_USO:
            WhatsAppService().enviar_mensagem_texto(telefone, obter_mensagem_fila_ocupado(telefone, 'pedido'))
        else:
            WhatsAppService().enviar_mensagem_texto(
                telefone,
                f"{msg_erro}\n\nDigite *PEDIDO* para tentar novamente."
            )
        _resetar_sessao_pedido(telefone)
        return

    automacao = None
    tempo_inicio = time.time()
    def _marcar_hist(sucesso: bool, mensagem: str = ""):
        try:
            atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=telefone,
                bo_usuario=bo_usuario,
                tipo_automacao='pedido',
                sucesso=sucesso,
                mensagem_resultado=mensagem,
            )
        except Exception:
            pass
    try:
        headless = getattr(settings, 'PAP_HEADLESS', True)
        capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
        automacao = PAPNioAutomation(
            matricula_pap=bo_usuario.matricula_pap,
            senha_pap=bo_usuario.senha_pap,
            vendedor_nome=f"Pedido-{usuario.username}",
            headless=headless,
            capture_screenshots=capture_screenshots,
        )
        os_prioridade_crm = set()

        def _carregar_os_prioridade_pedido():
            nonlocal os_prioridade_crm
            from crm_app.utils import obter_os_prioridade_crm_por_cpf
            os_prioridade_crm = obter_os_prioridade_crm_por_cpf(cpf_limpo)

        _run_django_sync(_carregar_os_prioridade_pedido)

        sucesso, msg, detalhes, list_screenshot_path = automacao.consulta_os_por_cpf_com_resultado(
            cpf_limpo, os_prioridade_crm=os_prioridade_crm
        )
        tempo_decorrido = round(time.time() - tempo_inicio, 1)
        automacao._fechar_sessao()

        def _finalizar():
            import django.db
            django.db.close_old_connections()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(sucesso, msg)
            _resetar_sessao_pedido(telefone)
            whatsapp = WhatsAppService()
            if not sucesso:
                resp = f"❌ {msg}\n\nDigite *PEDIDO* para tentar novamente.\n\n⏱ _{tempo_decorrido}s_"
                whatsapp.enviar_mensagem_texto(telefone, resp)
                return
            if msg == "no_results" or not detalhes:
                caption = (
                    "📋 *Consulta de pedido*\n\n"
                    "Não tem pedido com 30 dias para este CPF/CNPJ.\n\n"
                    f"⏱ _{tempo_decorrido}s_"
                )
            else:
                n = len(detalhes)
                partes = ["✅ *Existe(m) pedido(s)*, segue detalhes abaixo:\n\n"] if n > 1 else ["✅ *Existe um pedido*, segue detalhes abaixo:\n\n"]
                for i, d in enumerate(detalhes):
                    status = d.get("status", "")
                    data_hora = d.get("data_hora", "")
                    plano = d.get("plano", "")
                    numero_os = d.get("numero_os", "")
                    if n > 1:
                        partes.append(f"📌 *Pedido {i + 1}/{n}* (OS {numero_os})\n")
                    partes.append(
                        f"• *Status:* {status}\n"
                        f"• *Data:* {data_hora}\n"
                        f"• *Plano:* {plano}\n"
                        f"• *Nº OS:* {numero_os}"
                    )
                    if i < len(detalhes) - 1:
                        partes.append("\n\n")
                    partes.append("\n")
                partes.append(f"\n⏱ _{tempo_decorrido}s_")
                caption = "".join(partes)
            if list_screenshot_path and os.path.isfile(list_screenshot_path):
                try:
                    with open(list_screenshot_path, "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode("utf-8")
                    whatsapp.enviar_imagem_b64(telefone, img_b64, caption=caption)
                except Exception as e_img:
                    logger.warning("[PEDIDO] Erro ao enviar imagem, enviando só texto: %s", e_img)
                    whatsapp.enviar_mensagem_texto(telefone, caption)
            else:
                whatsapp.enviar_mensagem_texto(telefone, caption)

        _run_django_sync(_finalizar)
    except Exception as e:
        logger.exception("[PEDIDO] Erro ao executar consulta: %s", e)
        tempo_decorrido_erro = round(time.time() - tempo_inicio, 1)
        if automacao:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass

        def _erro_cleanup():
            try:
                liberar_bo(bo_usuario.id, telefone)
            except Exception:
                pass
            _marcar_hist(False, str(e))
            _resetar_sessao_pedido(telefone)
            msg_erro = (
                f"❌ Erro ao consultar pedido: {e}\n\n"
                f"Digite *PEDIDO* para tentar novamente.\n\n⏱ _{tempo_decorrido_erro}s_"
            )
            WhatsAppService().enviar_mensagem_texto(telefone, msg_erro)

        _run_django_sync(_erro_cleanup)


def _executar_consulta_status_online_background(
    telefone: str,
    cpf: str,
    os_filtro: str = None,
    run_id: str = None,
):
    """
    Thread: após Status no CRM, consulta online no PAP (Consulta OS + Detalhar quando houver link).
    Opcionalmente sincroniza venda (AGENDADO → INSTALADA + data instal.) quando PAP indica concluído.
    Envia resultado via WhatsApp e reseta sessão.
    """
    import base64
    from usuarios.models import Usuario
    from crm_app.models import SessaoWhatsapp
    from crm_app.services_pap_nio import PAPNioAutomation
    from crm_app.pool_bo_pap import (
        obter_login_bo,
        liberar_bo,
        MSG_TODOS_ACESSOS_EM_USO,
        obter_mensagem_fila_ocupado,
        atualizar_historico_consulta_pap_resultado,
    )
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.utils import (
        montar_legenda_pedido_status_pap,
        obter_os_prioridade_crm_por_cpf,
        sincronizar_venda_crm_apos_status_pap,
    )

    cpf_limpo = re.sub(r'\D', '', cpf)
    if len(cpf_limpo) not in (11, 14):
        return
    bo_usuario, msg_erro = obter_login_bo(telefone, None, tipo_automacao='status')
    if not bo_usuario:
        if msg_erro == MSG_TODOS_ACESSOS_EM_USO:
            WhatsAppService().enviar_mensagem_texto(telefone, obter_mensagem_fila_ocupado(telefone, 'status'))
        else:
            WhatsAppService().enviar_mensagem_texto(
                telefone,
                f"{msg_erro}\n\nConsulta online (PAP) não realizada. Digite *STATUS* para tentar novamente."
            )
        try:
            s = SessaoWhatsapp.objects.get(telefone=telefone)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        return

    automacao = None
    tempo_inicio = time.time()
    def _marcar_hist(sucesso: bool, mensagem: str = ""):
        try:
            atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=telefone,
                bo_usuario=bo_usuario,
                tipo_automacao='status',
                sucesso=sucesso,
                mensagem_resultado=mensagem,
            )
        except Exception:
            pass
    try:
        logger.info(
            "[STATUS ONLINE] Iniciando consulta PAP para %s (OS filtro=%s, CPF=%s***).",
            telefone,
            os_filtro or "-",
            cpf_limpo[:3] if cpf_limpo else "",
        )
        headless = getattr(settings, 'PAP_HEADLESS', True)
        capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
        optimize_fast = getattr(settings, 'PAP_STATUS_FAST_MODE', True)
        automacao = PAPNioAutomation(
            matricula_pap=bo_usuario.matricula_pap,
            senha_pap=bo_usuario.senha_pap,
            vendedor_nome="Status-Online",
            headless=headless,
            capture_screenshots=capture_screenshots,
            optimize_for_credit=optimize_fast,
        )
        sucesso, msg = automacao.iniciar_sessao()
        if not sucesso:
            logger.warning("[STATUS ONLINE] Falha ao iniciar sessão PAP: %s", msg)

            def _falha_login():
                liberar_bo(bo_usuario.id, telefone)
                _marcar_hist(False, msg)
                WhatsAppService().enviar_mensagem_texto(
                    telefone,
                    f"❌ Erro PAP: {msg}\n\nDigite *STATUS* para tentar novamente.",
                )
                try:
                    s = SessaoWhatsapp.objects.get(telefone=telefone)
                    s.etapa = 'inicial'
                    s.dados_temp = {}
                    s.save()
                except Exception:
                    pass

            _run_django_sync(_falha_login)
            return

        os_prioridade_crm = set()

        def _carregar_os_prioridade():
            nonlocal os_prioridade_crm
            os_prioridade_crm = obter_os_prioridade_crm_por_cpf(cpf_limpo)

        _run_django_sync(_carregar_os_prioridade)

        sucesso, msg, detalhes, list_screenshot_path = automacao.consulta_os_por_cpf_com_resultado(
            cpf_limpo, numero_os_filtro=os_filtro, os_prioridade_crm=os_prioridade_crm
        )
        tempo_decorrido = round(time.time() - tempo_inicio, 1)
        automacao._fechar_sessao()

        def _finalizar():
            import django.db
            django.db.close_old_connections()
            liberar_bo(bo_usuario.id, telefone)
            _marcar_hist(sucesso, msg)
            # Evitar mandar resultado "atrasado" se o usuário iniciou outra consulta (run_id diferente)
            if run_id:
                try:
                    s = SessaoWhatsapp.objects.get(telefone=telefone)
                    if s.etapa != 'status_aguardando_online' or (s.dados_temp or {}).get('status_online_run_id') != run_id:
                        return
                except Exception:
                    return
            # Resetar sessão só se for a consulta atual
            try:
                s = SessaoWhatsapp.objects.get(telefone=telefone)
                if (not run_id) or ((s.dados_temp or {}).get('status_online_run_id') == run_id):
                    s.etapa = 'inicial'
                    s.dados_temp = {}
                    s.save()
            except Exception:
                pass
            whatsapp = WhatsAppService()
            if not sucesso:
                whatsapp.enviar_mensagem_texto(
                    telefone,
                    f"❌ Consulta online (PAP): {msg}\n\n⏱ _{tempo_decorrido}s_"
                )
                return
            if msg == "no_results" or not detalhes:
                whatsapp.enviar_mensagem_texto(
                    telefone,
                    "📡 *Status online (PAP)*\n\n"
                    "Não tem pedido com 30 dias para este CPF/CNPJ.\n\n"
                    f"⏱ _{tempo_decorrido}s_",
                )
            else:
                try:
                    sincronizar_venda_crm_apos_status_pap(cpf_limpo, detalhes, os_filtro=os_filtro)
                except Exception as e_sync:
                    logger.warning("[STATUS ONLINE] Sync CRM: %s", e_sync)

                pedidos_com_print = []
                pedidos_so_texto = []
                for d in detalhes:
                    path = d.get("detail_screenshot_path")
                    if (
                        not d.get("nao_pertence_pdv")
                        and path
                        and os.path.isfile(path)
                    ):
                        pedidos_com_print.append(d)
                    else:
                        pedidos_so_texto.append(d)

                enviou_algo = False
                try:
                    for d in pedidos_com_print:
                        legenda = montar_legenda_pedido_status_pap(d, tempo_decorrido)
                        with open(d["detail_screenshot_path"], "rb") as f:
                            img_b64 = base64.b64encode(f.read()).decode("utf-8")
                        if whatsapp.enviar_imagem_b64(telefone, img_b64, caption=legenda):
                            enviou_algo = True
                        else:
                            logger.warning(
                                "[STATUS ONLINE] Z-API não confirmou imagem OS %s",
                                d.get("numero_os"),
                            )
                            whatsapp.enviar_mensagem_texto(telefone, legenda)
                            enviou_algo = True

                    if pedidos_so_texto:
                        if (
                            not pedidos_com_print
                            and list_screenshot_path
                            and os.path.isfile(list_screenshot_path)
                        ):
                            legenda_lista = "\n".join(
                                montar_legenda_pedido_status_pap(d, tempo_decorrido)
                                for d in pedidos_so_texto
                            )
                            with open(list_screenshot_path, "rb") as f:
                                img_b64 = base64.b64encode(f.read()).decode("utf-8")
                            if whatsapp.enviar_imagem_b64(
                                telefone, img_b64, caption=legenda_lista
                            ):
                                enviou_algo = True
                            else:
                                whatsapp.enviar_mensagem_texto(telefone, legenda_lista)
                                enviou_algo = True
                        else:
                            for d in pedidos_so_texto:
                                legenda = montar_legenda_pedido_status_pap(
                                    d, tempo_decorrido
                                )
                                whatsapp.enviar_mensagem_texto(telefone, legenda)
                                enviou_algo = True

                    if not enviou_algo:
                        whatsapp.enviar_mensagem_texto(
                            telefone,
                            f"📡 *Status online (PAP)*\n\nPedidos encontrados, sem imagem disponível.\n\n⏱ _{tempo_decorrido}s_",
                        )
                except Exception as e_img:
                    logger.warning("[STATUS ONLINE] Erro ao enviar resultado: %s", e_img)
                    for d in detalhes:
                        whatsapp.enviar_mensagem_texto(
                            telefone,
                            montar_legenda_pedido_status_pap(d, tempo_decorrido),
                        )

        _run_django_sync(_finalizar)
        logger.info("[STATUS ONLINE] Finalizado para %s em %.1fs (sucesso=%s).", telefone, tempo_decorrido, sucesso)
    except Exception as e:
        logger.exception("[STATUS ONLINE] Erro: %s", e)
        tempo_decorrido = round(time.time() - tempo_inicio, 1)
        if automacao:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass
        def _erro_cleanup():
            try:
                liberar_bo(bo_usuario.id, telefone)
            except Exception:
                pass
            _marcar_hist(False, str(e))
            # Resetar sessão só se for a consulta atual
            if run_id:
                try:
                    s = SessaoWhatsapp.objects.get(telefone=telefone)
                    if s.etapa == 'status_aguardando_online' and (s.dados_temp or {}).get('status_online_run_id') == run_id:
                        s.etapa = 'inicial'
                        s.dados_temp = {}
                        s.save()
                except Exception:
                    pass
            else:
                try:
                    s = SessaoWhatsapp.objects.get(telefone=telefone)
                    s.etapa = 'inicial'
                    s.dados_temp = {}
                    s.save()
                except Exception:
                    pass
            WhatsAppService().enviar_mensagem_texto(
                telefone,
                f"❌ Erro na consulta online (PAP): {e}\n\nDigite *STATUS* para tentar novamente.\n\n⏱ _{tempo_decorrido}s_"
            )
        _run_django_sync(_erro_cleanup)
    finally:
        if automacao:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass


# =============================================================================
# FUNÇÕES PARA FLUXO DE VENDA VIA WHATSAPP
# =============================================================================

def _iniciar_fluxo_venda(telefone: str, sessao) -> str:
    """
    Inicia o fluxo de venda via WhatsApp.
    Verifica se o usuário está autorizado (qualquer perfil com autorização).
    
    Args:
        telefone: Número do telefone do usuário
        sessao: Sessão do WhatsApp
        
    Returns:
        Mensagem de resposta
    """
    from usuarios.models import Usuario
    from django.db.models import Q
    
    # Limpar telefone - remover tudo que não for número
    telefone_limpo = re.sub(r'\D', '', telefone)
    logger.info(f"[VENDA] Buscando usuário para telefone: {telefone} -> limpo: {telefone_limpo}")
    
    usuario = None
    
    # Criar variantes do telefone para busca
    telefones_variantes = set()
    telefones_variantes.add(telefone_limpo)
    
    # Sem DDI (55)
    if telefone_limpo.startswith('55') and len(telefone_limpo) > 11:
        telefones_variantes.add(telefone_limpo[2:])  # Remove 55
    
    # Com DDI (55)
    if not telefone_limpo.startswith('55') and len(telefone_limpo) >= 10:
        telefones_variantes.add('55' + telefone_limpo)
    
    # Últimos 8 e 9 dígitos (número local)
    if len(telefone_limpo) >= 8:
        telefones_variantes.add(telefone_limpo[-8:])
    if len(telefone_limpo) >= 9:
        telefones_variantes.add(telefone_limpo[-9:])
    
    logger.info(f"[VENDA] Variantes de telefone para busca: {telefones_variantes}")
    
    # Buscar usuário ativo com qualquer uma das variantes
    for tel_var in telefones_variantes:
        # Buscar onde o campo tel_whatsapp contenha os dígitos
        usuarios_encontrados = Usuario.objects.filter(
            is_active=True
        ).extra(
            where=["REPLACE(REPLACE(REPLACE(REPLACE(tel_whatsapp, '-', ''), ' ', ''), '(', ''), ')', '') LIKE %s"],
            params=[f'%{tel_var}%']
        )
        
        if usuarios_encontrados.exists():
            usuario = usuarios_encontrados.first()
            logger.info(f"[VENDA] Usuário encontrado: {usuario.username} (ID: {usuario.id})")
            break
    
    # Fallback: busca simples por contains
    if not usuario:
        for tel_var in telefones_variantes:
            usuario = Usuario.objects.filter(
                tel_whatsapp__icontains=tel_var, 
                is_active=True
            ).first()
            if usuario:
                logger.info(f"[VENDA] Usuário encontrado (fallback): {usuario.username}")
                break
    
    if not usuario:
        logger.warning(f"[VENDA] Nenhum usuário encontrado para telefone: {telefone_limpo}")
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Seu número não está cadastrado no sistema.\n"
            "Verifique se o campo WhatsApp está preenchido no seu cadastro."
        )
    
    # Verificar se está autorizado para venda sem auditoria
    if not getattr(usuario, 'autorizar_venda_sem_auditoria', False):
        logger.warning(f"[VENDA] Usuário {usuario.username} não está autorizado (autorizar_venda_sem_auditoria=False)")
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Você não está autorizado a realizar vendas pelo WhatsApp.\n"
            "Solicite que marquem a opção 'Autorizar venda sem auditoria' no seu cadastro."
        )
    
    # Vendedor só precisa de matrícula (para ser selecionado no PAP como vendedor da venda).
    # O login no PAP usa credenciais de perfil BackOffice (pool).
    if not usuario.matricula_pap:
        logger.warning(f"[VENDA] Usuário {usuario.username} sem matrícula PAP")
        return (
            "⚠️ *CONFIGURAÇÃO INCOMPLETA*\n\n"
            "Sua matrícula PAP não está configurada.\n"
            "Preencha o campo 'Matrícula PAP' no seu cadastro para poder ser identificado como vendedor."
        )
    
    # Iniciar fluxo de venda
    sessao.etapa = 'venda_confirmar_matricula'
    sessao.dados_temp = {
        'vendedor_id': usuario.id,
        'vendedor_nome': usuario.get_full_name() or usuario.username,
        'matricula_pap': usuario.matricula_pap,
    }
    sessao.save()
    
    logger.info(f"[VENDA] Iniciando fluxo para usuário {usuario.username} (perfil: {usuario.perfil})")
    
    return (
        f"🛒 *NOVA VENDA - PAP NIO*\n\n"
        f"Tempo médio do fluxo (seguindo rápido todas as etapas, com biometria pronta e *SIM* do cliente já respondido): cerca de 3 a 5 minutos.\n\n"
        f"Confirma que deseja iniciar uma nova venda?\n\n"
        f"Toque em *SIM* ou *CANCELAR*, ou digite *SIM* / *CANCELAR*."
    )


def _processar_correcao_credito(telefone: str, sessao, dados: dict, mensagem_limpa: str, campo: str) -> str:
    """Processa correção de celular/email/cpf quando análise de crédito falha (como no terminal)."""
    from crm_app.whatsapp_service import WhatsAppService
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Cancelado. Digite *VENDER* para iniciar novamente."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    celular_sec = dados.get('celular_sec', '') or None
    
    cmd_queue = ctx.get('cmd_queue')
    if campo == 'celular':
        celular_limpo = limpar_texto_cep_cpf(mensagem_limpa)
        if not celular_limpo or len(celular_limpo) < 10:
            return "❌ Celular inválido. Digite o celular com DDD (10 ou 11 dígitos):"
        cel_dig = _normalizar_celular_digitos(celular_limpo)
        rejeitados = dados.get('celulares_rejeitados') or []
        if cel_dig and cel_dig in rejeitados:
            return "⚠️ Este número já foi recusado pelo sistema. Digite outro celular com DDD:"
        dados['celular'] = celular_limpo
        celular, email = celular_limpo, dados.get('email', '')
        # Playwright roda na worker thread: enfileirar etapa4 para evitar "Cannot switch to a different thread"
        if cmd_queue:
            sessao.dados_temp = dados
            sessao.save()
            cmd_queue.put({'action': 'etapa4', 'celular': celular, 'email': email, 'celular_sec': celular_sec})
            return "⏳ Processando... Aguarde alguns instantes. Você receberá a resposta em seguida."
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    elif campo == 'email':
        email_raw = mensagem_limpa
        if '@' not in email_raw or '.' not in email_raw:
            return "❌ E-mail inválido. Digite um e-mail válido:"
        dados['email'] = email_raw.lower()
        celular, email = dados.get('celular', ''), dados['email']
        if cmd_queue:
            sessao.dados_temp = dados
            sessao.save()
            cmd_queue.put({'action': 'etapa4', 'celular': celular, 'email': email, 'celular_sec': celular_sec})
            return "⏳ Processando... Aguarde alguns instantes. Você receberá a resposta em seguida."
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    else:
        cpf_limpo = limpar_texto_cep_cpf(mensagem_limpa)
        if not cpf_limpo or len(cpf_limpo) != 11:
            return "❌ CPF inválido. Digite o CPF completo (11 dígitos):"
        dados['cpf_cliente'] = cpf_limpo
        sessao.dados_temp = dados
        sessao.save()
        sucesso, msg, _ = automacao.etapa3_cadastro_cliente(cpf_limpo)
        if not sucesso:
            if msg == "PAP_ERRO_PORTAL_NIO":
                return "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
            return f"❌ Cadastro: {msg}\n\nDigite outro CPF ou *CANCELAR*."
        celular, email = dados.get('celular', ''), dados.get('email', '')
        sucesso, msg, _, _ = automacao.etapa4_contato(celular, email, celular_secundario=celular_sec)
        if not sucesso:
            if msg == "PAP_ERRO_PORTAL_NIO":
                return "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
            if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                sessao.etapa = 'venda_corrigir_celular'
                sessao.save()
                return "⚠️ O número excede repetições ou é inválido. Digite outro celular com DDD:"
            if msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                sessao.etapa = 'venda_corrigir_email'
                sessao.save()
                return "⚠️ E-mail já usado ou inválido. Digite outro e-mail:"
            if msg == "CREDITO_NEGADO":
                return "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou *CANCELAR*:"
            return f"❌ {msg}\n\nDigite *CANCELAR* para sair."
        threading.Thread(target=_continuar_apos_correcao_credito, args=(telefone, sessao.id, dict(dados)), daemon=True).start()
        return "✅ Crédito aprovado!\n\n⏳ Continuando o processamento... Aguarde."


def _continuar_apos_correcao_credito(telefone: str, sessao_id: int, dados: dict):
    """Continua o fluxo após correção de crédito (etapa5 em diante)."""
    import django
    django.setup()
    from crm_app.models import SessaoWhatsapp
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.pool_bo_pap import liberar_bo, atualizar_historico_consulta_pap_resultado
    from usuarios.models import Usuario
    
    whatsapp = WhatsAppService()
    def enviar(m):
        try:
            whatsapp.enviar_mensagem_texto(telefone, m)
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao enviar: {e}")
    
    bo_usuario_hist = Usuario.objects.filter(id=dados.get('bo_usuario_id')).first()
    _hist_fechado = {'done': False}
    def _marcar_hist(sucesso: bool, mensagem: str = ""):
        if _hist_fechado['done'] or not bo_usuario_hist:
            return
        try:
            atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=telefone,
                bo_usuario=bo_usuario_hist,
                tipo_automacao='vender',
                sucesso=sucesso,
                mensagem_resultado=mensagem,
            )
            _hist_fechado['done'] = True
        except Exception:
            pass

    def resetar(sucesso: bool = False, mensagem: str = ""):
        _marcar_hist(sucesso, mensagem)
        try:
            s = SessaoWhatsapp.objects.get(id=sessao_id)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        liberar_bo(dados.get('bo_usuario_id'), telefone)
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao_id)
    if not ctx:
        return
    automacao = ctx['automacao']
    vendedor_matricula = dados.get('matricula_pap') or ctx.get('vendedor_matricula')
    
    try:
        sucesso, msg = automacao.etapa5_selecionar_forma_pagamento(dados.get('forma_pagamento', 'boleto'))
        if not sucesso:
            automacao._fechar_sessao()
            with _automacoes_lock:
                _automacoes_pap_ativas.pop(sessao_id, None)
                resetar(False, msg)
            enviar(f"❌ Erro na forma de pagamento: {msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        if dados.get('forma_pagamento') == 'debito':
            sucesso, msg = automacao.etapa5_preencher_debito(
                dados.get('banco', ''), dados.get('agencia', ''), dados.get('conta', ''), dados.get('digito', ''))
            if not sucesso:
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar(False, msg)
                enviar(f"❌ Erro no débito: {msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        for step_name, step_fn in [
            ('plano', lambda: automacao.etapa5_selecionar_plano_com_validacao(dados.get('plano', '500mega'))),
            ('fixo', lambda: automacao.etapa5_selecionar_fixo(dados.get('tem_fixo', False))),
        ]:
            sucesso, msg = step_fn()
            if not sucesso:
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar(False, msg)
                enviar(f"❌ Erro: {msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        if dados.get('tem_fixo'):
            sucesso, msg = automacao.etapa5_fixo_finalizar_portabilidade(
                bool(dados.get('fixo_portabilidade')),
                (dados.get('fixo_portabilidade_numero') or ''),
                (dados.get('fixo_portabilidade_operadora') or ''),
            )
            if not sucesso:
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar(False, msg)
                enviar(f"❌ Erro: {msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        for step_name, step_fn in [
            ('streaming', lambda: automacao.etapa5_selecionar_streaming(
                bool(dados.get('tem_streaming', False)), dados.get('streaming_opcoes') or '', dados.get('plano', '500mega'))),
            ('avançar', lambda: automacao.etapa5_clicar_avancar()),
        ]:
            sucesso, msg = step_fn()
            if not sucesso:
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar(False, msg)
                enviar(f"❌ Erro: {msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        _executar_venda_pap_etapa6_em_diante(
            telefone=telefone, sessao_id=sessao_id, dados=dados, automacao=automacao,
            vendedor_matricula=vendedor_matricula, vendedor_id=ctx.get('vendedor_id'),
            vendedor_nome=ctx.get('vendedor_nome'), bo_usuario_id=ctx.get('bo_usuario_id'),
            enviar_resultado=enviar, resetar_sessao_e_liberar_bo=resetar
        )
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro ao continuar após correção: {e}")
        try:
            automacao._fechar_sessao()
        except Exception:
            pass
        with _automacoes_lock:
            _automacoes_pap_ativas.pop(sessao_id, None)
        resetar(False, str(e))
        enviar(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")


def _processar_viabilidade_selecionar_endereco(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str, webhook_t0=None) -> str:
    """Processa seleção de endereço quando há múltiplos (como no terminal etapa 24). webhook_t0 para exibir ⏱ na resposta do worker."""
    from crm_app.whatsapp_service import WhatsAppService
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Cancelado. Digite *VENDER* para iniciar novamente."
    
    if not mensagem.isdigit():
        lista = dados.get('viabilidade_lista_enderecos', [])
        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
        return f"❌ Digite o número do endereço (ex: 1, 2)\n\n{linha}"
    
    idx = int(mensagem)
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    put_payload = {
        'action': 'selecionar_endereco',
        'idx': idx,
        'cep': dados.get('cep', ''),
        'numero': dados.get('numero', ''),
        'referencia': dados.get('referencia', ''),
    }
    if webhook_t0 is not None:
        put_payload['worker_t0'] = webhook_t0
    if not ctx:
        return _marcar_sessao_erro_retry(sessao, dados, 'venda_selecionar_endereco', put_payload)
    
    cmd_queue = ctx.get('cmd_queue')
    if cmd_queue:
        cmd_queue.put(put_payload)
        return "⏳ Processando endereço... Aguarde alguns instantes."
    
    automacao = ctx['automacao']
    cep, numero, ref = dados.get('cep', ''), dados.get('numero', ''), dados.get('referencia', '')
    sucesso, msg = automacao.etapa2_selecionar_endereco_instalacao(idx)
    if not sucesso:
        return f"❌ {msg}\n\nDigite outro número ou *CANCELAR*."
    
    sucesso2, msg2, extra2 = automacao.etapa2_preencher_referencia_e_continuar(cep, numero, ref)
    if not sucesso2:
        if extra2 == "POSSE_ENCONTRADA":
            sessao.etapa = 'venda_posse_consultar_outro'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        if extra2 == "INDISPONIVEL_TECNICO":
            sessao.etapa = 'venda_indisponivel_voltar'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente."
    
    if isinstance(extra2, dict) and extra2.get('_codigo') == 'COMPLEMENTOS':
        with _automacoes_lock:
            _automacoes_pap_ativas[sessao.id]['phase'] = 'viabilidade_complemento'
            _automacoes_pap_ativas[sessao.id]['dados'] = dados
        lista = extra2.get('lista', [])
        sessao.etapa = 'venda_selecionar_complemento'
        sessao.dados_temp = {**dados, 'viabilidade_lista_complementos': lista}
        sessao.save()
        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
        return f"📋 *Complementos encontrados:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO* se não tiver, ou o *número* do complemento (ex: 1, 2, 3):"
    
    # Sucesso - manter automação aberta para próximas etapas (igual ao teste)
    with _automacoes_lock:
        _automacoes_pap_ativas[sessao.id] = {
            'automacao': automacao, 'phase': 'venda',
            'dados': dados, 'bo_usuario_id': dados.get('bo_usuario_id'), 'telefone': telefone,
            'vendedor_id': dados.get('vendedor_id'), 'vendedor_matricula': dados.get('matricula_pap'),
            'vendedor_nome': dados.get('vendedor_nome', ''),
        }
    sessao.etapa = 'venda_cpf'
    sessao.dados_temp = dados
    sessao.save()
    protocolo = automacao.dados_pedido.get('protocolo', '')
    msg_ok = "✅ Endereço disponível!"
    if protocolo:
        msg_ok += f"\n📋 Protocolo: {protocolo}"
    return msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"


def _processar_viabilidade_selecionar_complemento(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str, webhook_t0=None) -> str:
    """Processa seleção de complemento (como no terminal etapa 25). webhook_t0 para exibir ⏱ na resposta do worker."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Cancelado. Digite *VENDER* para iniciar novamente."
    
    escolha = mensagem.strip().upper()
    if escolha not in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N") and not escolha.isdigit():
        lista = dados.get('viabilidade_lista_complementos', [])
        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
        return f"❌ Digite *0* ou *SEM COMPLEMENTO*, ou o número do complemento (ex: 1)\n\n{linha}"
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    put_payload = {
        'action': 'selecionar_complemento',
        'escolha': mensagem.strip(),
        'cep': dados.get('cep', ''),
        'numero': dados.get('numero', ''),
    }
    if webhook_t0 is not None:
        put_payload['worker_t0'] = webhook_t0
    if not ctx:
        return _marcar_sessao_erro_retry(sessao, dados, 'venda_selecionar_complemento', put_payload)
    
    cmd_queue = ctx.get('cmd_queue')
    if cmd_queue:
        cmd_queue.put(put_payload)
        return "⏳ Processando complemento... Aguarde alguns instantes."
    
    if escolha in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
        sucesso, msg = ctx['automacao'].etapa2_selecionar_sem_complemento()
    else:
        sucesso, msg = ctx['automacao'].etapa2_selecionar_complemento(int(escolha))
    
    automacao = ctx['automacao']
    if not sucesso:
        return f"❌ {msg}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número do complemento (ex: 1):"
    
    cep, numero = dados.get('cep', ''), dados.get('numero', '')
    sucesso2, msg2, extra2 = automacao.etapa2_clicar_avancar_apos_complemento(cep, numero)
    if not sucesso2:
        if extra2 == "POSSE_ENCONTRADA":
            sessao.etapa = 'venda_posse_consultar_outro'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        if extra2 == "INDISPONIVEL_TECNICO":
            sessao.etapa = 'venda_indisponivel_voltar'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente."
    
    # Sucesso - manter automação aberta para próximas etapas (igual ao teste)
    with _automacoes_lock:
        _automacoes_pap_ativas[sessao.id] = {
            'automacao': automacao, 'phase': 'venda',
            'dados': dados, 'bo_usuario_id': dados.get('bo_usuario_id'), 'telefone': telefone,
            'vendedor_id': dados.get('vendedor_id'), 'vendedor_matricula': dados.get('matricula_pap'),
            'vendedor_nome': dados.get('vendedor_nome', ''),
        }
    sessao.etapa = 'venda_cpf'
    sessao.dados_temp = dados
    sessao.save()
    protocolo = automacao.dados_pedido.get('protocolo', '')
    msg_ok = "✅ Endereço disponível!"
    if protocolo:
        msg_ok += f"\n📋 Protocolo: {protocolo}"
    return msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"


def _processar_viabilidade_posse(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa posse encontrada - outro CEP ou CONCLUIR (como no terminal etapa 30)."""
    from crm_app.pool_bo_pap import liberar_bo, atualizar_historico_consulta_pap_resultado
    
    if mensagem_limpa == 'CONCLUIR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão encerrada. Digite *VENDER* para iniciar novamente."
    
    cep_novo = limpar_texto_cep_cpf(mensagem_limpa)
    if len(cep_novo) < 8:
        return "❌ CEP inválido. Digite 8 dígitos para consultar outro endereço ou *CONCLUIR* para sair."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    put_payload = {'action': 'modal_posse_voltar', 'cep_novo': cep_novo}
    if not ctx:
        return _marcar_sessao_erro_retry(sessao, dados, 'venda_posse_consultar_outro', put_payload)
    
    cmd_queue = ctx.get('cmd_queue')
    if cmd_queue:
        cmd_queue.put(put_payload)
        return "⏳ Processando... Aguarde alguns instantes."
    ok, _ = ctx['automacao'].etapa2_modal_posse_clicar_consultar_outro()
    if not ok:
        return f"⚠️ Erro ao voltar à consulta.\n\nDigite outro CEP ou *CONCLUIR*."
    
    dados['cep'] = cep_novo
    sessao.dados_temp = dados
    sessao.etapa = 'venda_numero'
    sessao.save()
    return f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)"


def _processar_viabilidade_indisponivel(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa indisponível técnico - outro CEP ou CONCLUIR (como no terminal etapa 31)."""
    if mensagem_limpa == 'CONCLUIR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão encerrada. Digite *VENDER* para iniciar novamente."
    
    cep_novo = limpar_texto_cep_cpf(mensagem_limpa)
    if len(cep_novo) < 8:
        return "❌ CEP inválido. Digite 8 dígitos para consultar outro endereço ou *CONCLUIR* para sair."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    put_payload = {'action': 'modal_indisponivel_voltar', 'cep_novo': cep_novo}
    if not ctx:
        return _marcar_sessao_erro_retry(sessao, dados, 'venda_indisponivel_voltar', put_payload)
    
    cmd_queue = ctx.get('cmd_queue')
    if cmd_queue:
        cmd_queue.put(put_payload)
        return "⏳ Processando... Aguarde alguns instantes."
    ok, _ = ctx['automacao'].etapa2_modal_indisponivel_clicar_voltar()
    if not ok:
        return f"⚠️ Erro ao voltar à consulta.\n\nDigite outro CEP ou *CONCLUIR*."
    
    dados['cep'] = cep_novo
    sessao.dados_temp = dados
    sessao.etapa = 'venda_numero'
    sessao.save()
    return f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)"


def _processar_agendamento_dia(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str) -> str:
    """Processa seleção do dia no agendamento. Envia comando para a thread da automação (evita greenlet/thread)."""
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.pool_bo_pap import liberar_bo
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if not mensagem.isdigit():
        datas = dados.get('agendamento_datas', [])
        return f"❌ Digite o número do dia (ex: 10)\n\nDatas disponíveis: {', '.join(str(d) for d in datas)}\n\nOu *CANCELAR* para sair."
    
    dia = int(mensagem)
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    agendamento_queue = ctx.get('agendamento_queue')
    if not agendamento_queue:
        return "❌ Sessão de agendamento indisponível. Digite *VENDER* para iniciar novamente."
    response_queue = queue.Queue()
    try:
        agendamento_queue.put({'cmd': 'dia', 'dia': dia, 'response_queue': response_queue})
        sucesso, msg, periodos = response_queue.get(timeout=45)
    except queue.Empty:
        return "❌ Timeout ao processar. Digite o dia novamente ou *CANCELAR*."
    except Exception as e:
        logger.exception("[VENDA PAP] _processar_agendamento_dia: %s", e)
        return f"❌ Erro: {e}\n\nDigite outro dia ou *CANCELAR*."
    if not sucesso:
        return f"❌ {msg}\n\nDigite outro dia ou *CANCELAR*."
    
    dados['agendamento_dia'] = dia
    dados['agendamento_periodos'] = periodos or []
    sessao.dados_temp = dados
    sessao.etapa = 'venda_agendamento_confirmar_data'
    sessao.save()
    
    if not periodos:
        return "⚠️ Nenhum período disponível para este dia.\n\nDigite outro dia ou *CANCELAR*."
    
    return f"✅ Dia *{dia}* selecionado.\n\nDeseja *CONFIRMAR* a data ou *ALTERAR*?"


def _processar_agendamento_confirmar_data(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa CONFIRMAR ou ALTERAR data (como no terminal etapa 121)."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if mensagem_limpa == 'ALTERAR':
        sessao.etapa = 'venda_agendamento_dia'
        sessao.save()
        datas = dados.get('agendamento_datas', [])
        return f"📅 Datas disponíveis: {', '.join(str(d) for d in datas)}\n\nDigite o *número do dia* (ex: 10) ou *CANCELAR*:"
    
    if mensagem_limpa in ('CONFIRMAR', 'SIM', 'S'):
        periodos = dados.get('agendamento_periodos', [])
        sessao.etapa = 'venda_agendamento_periodo'
        sessao.save()
        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
        return f"✅ Data confirmada!\n\n*Períodos disponíveis:*\n{linha}\n\nDigite o *número do período* (ex: 1) ou *CANCELAR*:"
    
    return "Digite *CONFIRMAR* para a data ou *ALTERAR* para escolher outra."


def _processar_agendamento_periodo(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str) -> str:
    """Processa seleção do período no agendamento. Envia comando para a thread da automação."""
    from crm_app.whatsapp_service import WhatsAppService
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if not mensagem.isdigit():
        periodos = dados.get('agendamento_periodos', [])
        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
        return f"❌ Digite o número do período\n\n{linha}\n\nOu *CANCELAR* para sair."
    
    idx = int(mensagem)
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    agendamento_queue = ctx.get('agendamento_queue')
    if not agendamento_queue:
        return "❌ Sessão de agendamento indisponível. Digite *VENDER* para iniciar novamente."
    response_queue = queue.Queue()
    try:
        agendamento_queue.put({'cmd': 'periodo', 'idx': idx, 'response_queue': response_queue})
        sucesso, msg = response_queue.get(timeout=45)
    except queue.Empty:
        return "❌ Timeout ao processar. Digite o período novamente ou *CANCELAR*."
    except Exception as e:
        logger.exception("[VENDA PAP] _processar_agendamento_periodo: %s", e)
        return f"❌ Erro: {e}\n\nDigite outro período ou *CANCELAR*."
    if not sucesso:
        return f"❌ {msg}\n\nDigite outro período ou *CANCELAR*."
    
    periodos = dados.get('agendamento_periodos', [])
    label = periodos[idx - 1]['label'] if idx <= len(periodos) else f"Período {idx}"
    dados['agendamento_turno_label'] = label
    sessao.dados_temp = dados
    sessao.etapa = 'venda_agendamento_confirmar_turno'
    sessao.save()
    
    return f"✅ Turno *{label}* selecionado.\n\nDeseja *CONFIRMAR* o turno ou *ALTERAR*?"


def _processar_agendamento_confirmar_turno(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa CONFIRMAR, ALTERAR ou número do período (1/2) para trocar turno no site."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    # Se enviou número do período (ex: 2 para Tarde), selecionar no site e atualizar label
    if mensagem_limpa.isdigit():
        return _processar_agendamento_periodo(telefone, sessao, dados, mensagem_limpa, mensagem_limpa)
    if mensagem_limpa == 'ALTERAR':
        periodos = dados.get('agendamento_periodos', [])
        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
        return f"*Períodos disponíveis:*\n{linha}\n\nDigite o *número do período* (ex: 1) ou *CANCELAR*:"
    if mensagem_limpa in ('CONFIRMAR', 'SIM', 'S'):
        dia = dados.get('agendamento_dia', '?')
        label = dados.get('agendamento_turno_label', '?')
        sessao.etapa = 'venda_agendamento_sim_agendar'
        sessao.save()
        return f"✅ Turno confirmado!\n\nPodemos agendar para o dia *{dia}* e turno *{label}*?\n\nDigite *SIM* para confirmar e agendar, ou *CANCELAR* para sair."
    
    return "Digite *CONFIRMAR* para o turno ou *ALTERAR* para escolher outro."


def _processar_agendamento_sim_agendar(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa SIM para agendar - envia comando para a thread clicar em Agendar."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if mensagem_limpa not in ('SIM', 'S'):
        dia = dados.get('agendamento_dia', '?')
        label = dados.get('agendamento_turno_label', '?')
        return f"Digite *SIM* para agendar (dia {dia}, turno {label}) ou *CANCELAR* para sair."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    agendamento_queue = ctx.get('agendamento_queue')
    if not agendamento_queue:
        return "❌ Sessão de agendamento indisponível. Digite *VENDER* para iniciar novamente."
    response_queue = queue.Queue()
    try:
        agendamento_queue.put({'cmd': 'sim_agendar', 'response_queue': response_queue})
        sucesso, msg = response_queue.get(timeout=45)
    except queue.Empty:
        return "❌ Timeout ao processar. Digite *SIM* para tentar novamente ou *CANCELAR*."
    except Exception as e:
        logger.exception("[VENDA PAP] _processar_agendamento_sim_agendar: %s", e)
        return f"❌ Erro: {e}\n\nDigite *SIM* para tentar novamente ou *CANCELAR*."
    if not sucesso:
        return f"❌ {msg}\n\nDigite *SIM* para tentar novamente ou *CANCELAR*."
    
    sessao.etapa = 'venda_agendamento_final'
    sessao.save()
    
    dia = dados.get('agendamento_dia', '?')
    label = dados.get('agendamento_turno_label', '?')
    return f"📅 *Agendado para* dia *{dia}* e turno *{label}*\n\nDigite *SIM* ou *CONFIRMAR* para concluir (clicar Continuar) ou *ALTERAR* para escolher outra data/turno."


def _processar_agendamento_final(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa confirmação final - envia comando para a thread clicar em Continuar no modal."""
    from crm_app.whatsapp_service import WhatsAppService
    from usuarios.models import Usuario
    from crm_app.cadastro_venda_pap import cadastrar_venda_pap_no_crm
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'venda_agendamento_dia'
        sessao.dados_temp = {**dados, 'agendamento_datas': dados.get('agendamento_datas', [])}
        sessao.save()
        return f"📅 Para escolher outra data:\n\nDatas disponíveis: {', '.join(str(d) for d in dados.get('agendamento_datas', []))}\n\nDigite o número do dia ou *CANCELAR* para sair."
    
    if mensagem_limpa not in ('SIM', 'S', 'CONFIRMAR'):
        return "Digite *SIM* ou *CONFIRMAR* para concluir, ou *CANCELAR* para escolher outra data."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    vendedor_id = ctx.get('vendedor_id')
    agendamento_queue = ctx.get('agendamento_queue')
    if not agendamento_queue:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão de agendamento indisponível. Digite *VENDER* para iniciar novamente."
    response_queue = queue.Queue()
    try:
        agendamento_queue.put({'cmd': 'final', 'response_queue': response_queue})
        result = response_queue.get(timeout=45)
    except queue.Empty:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Timeout ao concluir. Digite *VENDER* para iniciar novamente."
    except Exception as e:
        logger.exception("[VENDA PAP] _processar_agendamento_final: %s", e)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ Erro: {e}\n\nDigite *VENDER* para iniciar novamente."
    # Thread já fechou sessão e liberou BO; result = (sucesso, msg, numero_os, dados_pedido)
    sucesso = result[0] if len(result) > 0 else False
    msg = result[1] if len(result) > 1 else ""
    numero_os = result[2] if len(result) > 2 else None
    dados_pedido = result[3] if len(result) > 3 else {}
    try:
        from crm_app.funil_venda_wpp_service import funil_finalizar_concluido, funil_finalizar_erro
        if sucesso:
            funil_finalizar_concluido(sessao)
        else:
            funil_finalizar_erro(sessao, str(msg or "")[:2000])
    except Exception:
        pass
    sessao.etapa = 'inicial'
    sessao.dados_temp = {}
    sessao.save()
    if not sucesso:
        return f"❌ {msg}\n\nDigite *VENDER* para iniciar novamente."
    try:
        from crm_app.controle_tts_service import marcar_tt_tratado_apos_geracao_os

        mat_tt = (dados.get("matricula_tt_pap_pedido") or "").strip()
        if mat_tt and numero_os:
            marcar_tt_tratado_apos_geracao_os(mat_tt)
    except Exception as e:
        logger.warning("[VENDA PAP] Controle TT após O.S.: %s", e)
    try:
        vendedor = Usuario.objects.get(id=vendedor_id)
        dados_crm = {**dados, **dados_pedido}
        cadastrar_venda_pap_no_crm(dados_crm, numero_os or "", vendedor=vendedor)
    except Exception as e:
        logger.error(f"[VENDA PAP] Erro ao cadastrar no CRM: {e}")
    return (
        f"🎉 *VENDA CONCLUÍDA COM SUCESSO!*\n\n"
        f"📋 Número do Pedido: *{numero_os or 'N/A'}*\n\n"
        f"A venda foi registrada no CRM.\n\n"
        f"Digite *VENDER* para iniciar uma nova venda."
    )


def _encerrar_automacao_pap(sessao_id: int, bo_usuario_id, telefone: str):
    """Encerra automação PAP (agendamento, viabilidade ou crédito) e libera o BO."""
    from crm_app.pool_bo_pap import liberar_bo, atualizar_historico_consulta_pap_resultado
    from usuarios.models import Usuario
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao_id)
    if ctx:
        q = ctx.get('agendamento_queue') or ctx.get('cmd_queue')
        if q:
            try:
                q.put({'action': 'STOP'})
            except Exception:
                pass
        # Se há agendamento_queue, a thread da automação fará pop e _fechar_sessao ao receber STOP
        if ctx.get('agendamento_queue'):
            return
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.pop(sessao_id, None)
    if ctx:
        try:
            ctx['automacao']._fechar_sessao()
        except Exception:
            pass
    if bo_usuario_id:
        try:
            bo_usuario = Usuario.objects.filter(id=bo_usuario_id).first()
            if bo_usuario:
                atualizar_historico_consulta_pap_resultado(
                    vendedor_telefone=telefone,
                    bo_usuario=bo_usuario,
                    tipo_automacao='vender',
                    sucesso=False,
                    mensagem_resultado="Cancelado/encerrado pelo usuário.",
                )
        except Exception:
            pass
        liberar_bo(bo_usuario_id, telefone)


def _marcar_sessao_erro_retry(sessao, dados: dict, etapa_erro: str, ultimo_cmd_erro: dict) -> str:
    """
    Quando a automação perde o contexto (ctx não está em _automacoes_pap_ativas),
    marca a sessão para estado de retry e retorna mensagem oferecendo REPETIR ou VENDER.
    """
    if not dados:
        dados = sessao.dados_temp or {}
    dados = dict(dados)
    dados['_etapa_erro'] = etapa_erro
    dados['_ultimo_cmd_erro'] = ultimo_cmd_erro
    sessao.etapa = 'venda_erro_retry'
    sessao.dados_temp = dados
    sessao.save()
    return (
        "❌ A conexão com a automação foi perdida (sessão expirada ou instável).\n\n"
        "Digite *REPETIR* para tentar a última etapa novamente ou *VENDER* para iniciar do zero."
    )


def _mensagem_sessao_expirada(sessao, dados: dict, etapa_atual: str, ultimo_cmd_erro: dict = None) -> str:
    """
    Usado quando ctx = _automacoes_pap_ativas.get(sessao.id) é None (sessão expirada).
    Possíveis causas: (1) timeout 10 min sem comando, (2) site PAP deslogou e a thread encerrou,
    (3) requisição caiu em outra réplica (contexto é em memória por processo).
    Se houver dados salvos (dados_temp com CEP/CPF/etc.), marca para retry e oferece REPETIR.
    """
    logger.warning(
        "[VENDER] Sessão expirada: sessao_id=%s etapa=%s has_dados=%s (ctx ausente: timeout, PAP deslogou ou outra réplica)",
        sessao.id, etapa_atual, bool(dados),
    )
    if dados and (dados.get('cep') or dados.get('cpf_cliente') or dados.get('celular')):
        # Salvar estado para permitir REPETIR quando o contexto existir (ex.: mesma réplica)
        return _marcar_sessao_erro_retry(sessao, dados, etapa_atual, ultimo_cmd_erro or {'action': etapa_atual})
    sessao.etapa = 'inicial'
    sessao.dados_temp = {}
    sessao.save()
    return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."


def _formatar_streaming_resumo(dados: dict) -> str:
    """Texto do streaming para o resumo (só usado quando tem_streaming é verdadeiro): opções com preços ou Sim."""
    if not dados.get('tem_streaming'):
        return ""
    opts_raw = (dados.get('streaming_opcoes') or '').lower().replace(' ', '')
    opts_set = set(x.strip() for x in opts_raw.split(',') if x.strip())
    precos = [
        ('hbomax', 'HBO Max', 'R$ 44,90/mês'),
        ('globoplay_premium', 'Globoplay Premium', 'R$ 39,90/mês'),
        ('globoplay_basico', 'Globoplay Padrão', 'R$ 22,90/mês'),
    ]
    partes = [f"{label} {preco}" for key, label, preco in precos if key in opts_set]
    return "; ".join(partes) if partes else "Sim"


def _texto_formas_pagamento_por_credito(resultado_credito: str) -> tuple:
    """
    Retorna (texto_msg, formas_map) para a etapa de forma de pagamento conforme o resultado do crédito.
    - Se resultado_credito == "Elegível apenas para Cartão de Crédito": só opção 2 (Cartão).
    - Caso contrário: 1=Boleto, 2=Cartão, 3=Débito em Conta.
    A mensagem deixa explícito se aprovou todas as formas ou apenas cartão, para evitar envio errado ao cliente.
    """
    apenas_cartao = (resultado_credito or '').strip() == "Elegível apenas para Cartão de Crédito"
    if apenas_cartao:
        return (
            "💳 *ETAPA 4: PAGAMENTO*\n\n"
            "Crédito aprovado *apenas para Cartão de Crédito* (boleto e débito não liberados).\n\n"
            "2️⃣ Cartão de Crédito\n\n"
            "Digite *2* para continuar:",
            {'2': 'cartao'},
        )
    return (
        "💳 *ETAPA 4: PAGAMENTO*\n\n"
        "Crédito aprovado para *todas as formas de pagamento* (Boleto, Cartão ou Débito).\n\n"
        "Escolha a forma de pagamento:\n\n"
        "1️⃣ Boleto\n"
        "2️⃣ Cartão de Crédito\n"
        "3️⃣ Débito em Conta\n\n"
        "Digite o número da opção:",
        {'1': 'boleto', '2': 'cartao', '3': 'debito'},
    )


def _texto_etapa5_planos(forma_pagamento: str) -> str:
    """Retorna o texto da ETAPA 5 (lista de planos). Cartão de crédito tem desconto de R$ 10."""
    if (forma_pagamento or '').strip().lower() == 'cartao':
        return (
            "📦 *ETAPA 5: PLANO*\n\n"
            "Escolha o plano:\n\n"
            "1️⃣ Nio Fibra Ultra 1 Giga - R$ 150,00/mês\n"
            "2️⃣ Nio Fibra Super 700 Mega - R$ 120,00/mês\n"
            "3️⃣ Nio Fibra Essencial 500 Mega - R$ 90,00/mês\n\n"
            "Digite o número da opção:"
        )
    return (
        "📦 *ETAPA 5: PLANO*\n\n"
        "Escolha o plano:\n\n"
        "1️⃣ Nio Fibra Ultra 1 Giga - R$ 160,00/mês\n"
        "2️⃣ Nio Fibra Super 700 Mega - R$ 130,00/mês\n"
        "3️⃣ Nio Fibra Essencial 500 Mega - R$ 100,00/mês\n\n"
        "Digite o número da opção:"
    )


def _montar_resumo_venda_e_pedir_confirmar(dados: dict) -> str:
    """Monta o resumo da venda e pede confirmação (fluxo unificado com terminal)."""
    cpf = dados.get('cpf_cliente', '')
    celular = dados.get('celular', '')
    forma = (dados.get('forma_pagamento') or '').strip().lower()
    # Cartão de crédito: desconto de R$ 10 nos planos
    if forma == 'cartao':
        plano_nome = {
            '1giga': 'Nio Fibra Ultra 1 Giga - R$ 150,00/mês',
            '700mega': 'Nio Fibra Super 700 Mega - R$ 120,00/mês',
            '500mega': 'Nio Fibra Essencial 500 Mega - R$ 90,00/mês'
        }
    else:
        plano_nome = {
            '1giga': 'Nio Fibra Ultra 1 Giga - R$ 160,00/mês',
            '700mega': 'Nio Fibra Super 700 Mega - R$ 130,00/mês',
            '500mega': 'Nio Fibra Essencial 500 Mega - R$ 100,00/mês'
        }
    forma_nome = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito', 'debito': 'Débito em Conta'}
    cpf_fmt = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf
    cel_fmt = f"({celular[:2]}) {celular[2:7]}-{celular[7:]}" if len(celular) >= 10 else celular
    nome_cliente = (dados.get('nome_cliente') or '').strip() or 'Não informado'
    linhas_endereco = [
        f"CEP: {dados.get('cep', '')}",
        f"Número: {dados.get('numero', '')}",
    ]
    logradouro = (dados.get('logradouro') or '').strip()
    if logradouro:
        linhas_endereco.insert(1, f"Logradouro: {logradouro}")
    bairro = (dados.get('bairro') or '').strip()
    if bairro:
        linhas_endereco.append(f"Bairro: {bairro}")
    cidade = (dados.get('cidade') or '').strip()
    if cidade:
        linhas_endereco.append(f"Cidade: {cidade}")
    referencia = (dados.get('referencia') or '').strip()
    if referencia:
        linhas_endereco.append(f"Referência: {referencia}")
    bloco_endereco = "\n".join(linhas_endereco)
    linhas_pos_plano = []
    if dados.get("tem_fixo"):
        linhas_pos_plano.append("📞 *Fixo:* Sim – R$ 30,00/mês")
    if dados.get("tem_fixo") and dados.get("fixo_portabilidade"):
        linhas_pos_plano.append(
            f"📲 *Portabilidade fixo:* Sim — {dados.get('fixo_portabilidade_numero', '')} "
            f"({dados.get('fixo_portabilidade_operadora', '')})"
        )
    elif dados.get("tem_fixo"):
        linhas_pos_plano.append("📲 *Portabilidade fixo:* Não")
    if dados.get("tem_streaming"):
        linhas_pos_plano.append(f"📺 *Streaming:* {_formatar_streaming_resumo(dados)}")
    bloco_pos_plano = ("\n".join(linhas_pos_plano) + "\n\n") if linhas_pos_plano else ""
    return (
        f"📋 *RESUMO DO PEDIDO NIO FIBRA*\n\n"
        f"👤 *Cliente:* {nome_cliente}\n"
        f"CPF: {cpf_fmt}\n"
        f"Celular: {cel_fmt}\n"
        f"E-mail: {dados.get('email', '')}\n\n"
        f"📍 *Endereço:*\n"
        f"{bloco_endereco}\n\n"
        f"💳 *Pagamento:* {forma_nome.get(dados.get('forma_pagamento', ''), '')}\n"
        f"📦 *Plano:* {plano_nome.get(dados.get('plano', ''), '')}\n"
        f"{bloco_pos_plano}"
        f"📅 *Fidelidade:* 12 meses\n\n"
        f"💰 *Taxa de habilitação:*\n"
        f"Você ganha isenção da taxa de habilitação se permanecer no mínimo 12 meses conosco.\n\n"
        f"Sua primeira fatura irá vencer *25 dias* após a instalação da internet; nos demais meses, "
        f"o vencimento segue o ciclo de *30 em 30 dias*.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Confirma a venda?\n\n"
        f"Digite *CONFIRMAR* para enviar ao PAP\n"
        f"Digite *CANCELAR* para desistir"
    )


def _pap_marcar_confirmacao_sim_cliente_no_bd(sessao_id: int, dados: dict, celular_cliente_fallback: str = "") -> int:
    """
    Marca PapConfirmacaoCliente como confirmado para a sessão (protocolo de envio gerado).
    Retorna quantas linhas foram atualizadas (0 se já estava confirmado ou sem registro).
    """
    from crm_app.models import PapConfirmacaoCliente
    from crm_app.pap_protocolo_confirmacao_envio import gerar_protocolo_confirmacao_envio

    dados = dados or {}
    celular_ref = (
        dados.get("celular")
        or dados.get("celular_principal")
        or (celular_cliente_fallback or "")
    )
    chaves_cel = list(
        dict.fromkeys([_chave_telefone(celular_ref)] + (_chaves_telefone_variantes(celular_ref) or []))
    )
    chaves_cel = [c for c in chaves_cel if c]
    proto_envio = gerar_protocolo_confirmacao_envio()
    n = 0
    if chaves_cel:
        n = PapConfirmacaoCliente.objects.filter(
            sessao_id=sessao_id,
            celular_cliente__in=chaves_cel,
            confirmado=False,
        ).update(confirmado=True, protocolo_confirmacao_envio=proto_envio)
    if n == 0:
        n = PapConfirmacaoCliente.objects.filter(sessao_id=sessao_id, confirmado=False).update(
            confirmado=True, protocolo_confirmacao_envio=proto_envio
        )
    return n


def _forcar_sim_confirmacao_cliente_pap(sessao, telefone_vendedor: str) -> str:
    """
    Homologação: marca PapConfirmacaoCliente como confirmado e acorda a worker (event + fila CONSULTAR).
    Só efetivo se settings.PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE.
    """
    from django.conf import settings as dj_settings

    if not getattr(dj_settings, "PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE", False):
        return (
            "⚠️ Comando *FORCAR_SIM* não está habilitado. "
            "Defina a variável de ambiente *PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE=true* no servidor (somente homologação)."
        )

    dados = sessao.dados_temp or {}
    n = _pap_marcar_confirmacao_sim_cliente_no_bd(sessao.id, dados, "")
    chave_v = _chave_telefone(telefone_vendedor)
    with _pending_lock:
        kc = _pending_by_vendedor.get(chave_v)
        pend = _pending_client_confirm.get(kc) if kc else None
    if pend and pend.get("sessao_id") == sessao.id:
        try:
            pend["event"].set()
        except Exception:
            pass
        try:
            q = pend.get("consultar_queue")
            if q is not None:
                q.put_nowait(1)
        except Exception:
            pass
    if n == 0 and not pend:
        return (
            "⚠️ Não há registro pendente de confirmação para esta sessão "
            "(o resumo ainda não foi registrado ou já foi confirmado). "
            "Aguarde o envio do resumo ao cliente ou digite *CONSULTAR*."
        )
    logger.info("[VENDA PAP] FORCAR_SIM: sessao_id=%s atualizados=%s", sessao.id, n)
    return (
        "✅ *SIM do cliente forçado* (modo homologação).\n\n"
        "O sistema foi acionado como após um *CONSULTAR*. Aguarde a próxima mensagem do bot ou digite *CONSULTAR* de novo."
    )


def _processar_etapa_venda(telefone: str, mensagem: str, sessao, etapa: str, webhook_t0=None) -> str:
    """
    Processa as etapas do fluxo de venda.
    webhook_t0: instante do início do request (time.monotonic()) para exibir tempo na mensagem 'Acesso reservado'.
    
    Args:
        telefone: Número do telefone
        mensagem: Mensagem recebida
        sessao: Sessão do WhatsApp
        etapa: Etapa atual
        
    Returns:
        Mensagem de resposta
    """
    from usuarios.models import Usuario
    from crm_app.services_pap_nio import (
        PAPNioAutomation, 
        obter_sessao_venda, 
        criar_sessao_venda,
        atualizar_sessao_venda,
        encerrar_sessao_venda
    )
    import threading
    
    dados = sessao.dados_temp or {}
    mensagem_limpa = mensagem.strip().upper()
    
    # Comando para cancelar em qualquer etapa
    if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
        # Encerra automação (se houver) e libera BO
        if etapa and etapa.startswith('venda_'):
            try:
                from crm_app.funil_venda_wpp_service import funil_finalizar_abandonado
                funil_finalizar_abandonado(sessao, 'cancelar_comando')
            except Exception:
                pass
            _encerrar_automacao_pap(sessao.id, (dados or {}).get('bo_usuario_id'), telefone)
        encerrar_sessao_venda(telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Venda cancelada. Digite *VENDER* para iniciar novamente."

    # Comando ESTENDER: prorroga o tempo da sessão (evita encerrar por inatividade)
    if mensagem_limpa == 'ESTENDER' and etapa and etapa.startswith('venda_') and etapa != 'venda_erro_retry':
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if ctx:
            q = ctx.get('cmd_queue')
            if q:
                try:
                    q.put({'action': 'ESTENDER'})
                    ext = ctx.get('extension_count', 0)
                    restantes = max(0, MAX_EXTEND_SESSION_COUNT - ext - 1)
                    return (
                        "⏱ Sua solicitação de *prorrogação* foi enviada. "
                        "Em alguns segundos você receberá a confirmação."
                        + (f" (Você pode prorrogar mais %d vez(es).)" % restantes if restantes > 0 else "")
                    )
                except Exception:
                    pass
        return "⚠️ Não foi possível prorrogar agora. Continue digitando os dados ou digite *VENDER* para iniciar novamente."
    
    # Comando REPETIR: reenviar último comando ao worker (após erro, dados já salvos)
    if etapa == 'venda_erro_retry':
        if mensagem_limpa == 'REPETIR':
            ultimo_cmd = (dados or {}).get('_ultimo_cmd_erro')
            with _automacoes_lock:
                ctx = _automacoes_pap_ativas.get(sessao.id)
            if not ultimo_cmd:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return "❌ Não há comando para repetir. Digite *VENDER* para iniciar novamente."
            if not ctx:
                return (
                    "❌ A automação ainda não está conectada (ex.: outra sessão pode estar usando o login).\n\n"
                    "Digite *REPETIR* em alguns segundos para tentar de novo ou *VENDER* para iniciar uma nova venda."
                )
            cmd_queue = ctx.get('cmd_queue')
            if cmd_queue:
                cmd_queue.put(ultimo_cmd)
                return "⏳ Tentando novamente... Aguarde alguns instantes. Você receberá a resposta em seguida."
            return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
        return "Digite *REPETIR* para tentar a última etapa novamente ou *VENDER* para iniciar do zero."
    
    # --- ETAPA: Confirmar matrícula ---
    if etapa == 'venda_confirmar_matricula':
        # Helpers PAP worker (usados pela thread SIM e por venda_referencia); definidos aqui para a thread enxergar _pap_worker_loop
        from crm_app.whatsapp_service import WhatsAppService
        def _executar_ops_django_sync(func):
            """Executa operações Django em thread limpa (evita SynchronousOnlyOperation após Playwright)."""
            q = queue.Queue()
            def run():
                try:
                    import django.db
                    django.db.close_old_connections()
                    func()
                    q.put(None)
                except Exception as e:
                    q.put(e)
            t = threading.Thread(target=run)
            t.start()
            t.join(timeout=60)
            if not q.empty():
                exc = q.get()
                if exc:
                    raise exc

        def _run_sync_returning(callable):
            """Executa callable em thread e retorna o valor (para leituras Django no PAP worker)."""
            result = [None]
            exc_holder = [None]
            def run():
                try:
                    import django.db
                    django.db.close_old_connections()
                    result[0] = callable()
                except Exception as e:
                    exc_holder[0] = e
            t = threading.Thread(target=run)
            t.start()
            t.join(timeout=60)
            if exc_holder[0]:
                raise exc_holder[0]
            return result[0]

        def _pap_worker_loop(cmd_queue, sessao_id, telefone, bo_id):
            """Loop do worker: processa comandos na mesma thread da automação (evita 'cannot switch to different thread')."""
            from crm_app.models import SessaoWhatsapp
            from crm_app.pool_bo_pap import liberar_bo
            while True:
                try:
                    with _automacoes_lock:
                        ctx = _automacoes_pap_ativas.get(sessao_id)
                    if not ctx:
                        break
                    now_ts = time.monotonic()
                    deadline = ctx.get('session_deadline')
                    if deadline is None:
                        deadline = now_ts + SESSION_TIMEOUT_SECONDS
                        with _automacoes_lock:
                            if sessao_id in _automacoes_pap_ativas:
                                _automacoes_pap_ativas[sessao_id]['session_deadline'] = deadline
                    remaining = max(0, deadline - now_ts)
                    if remaining <= 0:
                        logger.info("[VENDER] Sessão encerrada por tempo (10 min sem comando ou limite de prorrogação)")
                        break
                    cmd = cmd_queue.get(timeout=min(60, remaining))
                except queue.Empty:
                    continue
                if cmd.get('action') == 'STOP':
                    break
                if cmd.get('action') == 'ESTENDER':
                    with _automacoes_lock:
                        ctx = _automacoes_pap_ativas.get(sessao_id)
                    if not ctx:
                        break
                    ext = ctx.get('extension_count', 0)
                    if ext >= MAX_EXTEND_SESSION_COUNT:
                        def _msg_limite():
                            WhatsAppService().enviar_mensagem_texto(
                                telefone,
                                "⚠️ Limite de prorrogações atingido (máx. %d). Continue o atendimento ou digite *CANCELAR*."
                                % MAX_EXTEND_SESSION_COUNT,
                            )
                        _executar_ops_django_sync(_msg_limite)
                    else:
                        with _automacoes_lock:
                            if sessao_id in _automacoes_pap_ativas:
                                _automacoes_pap_ativas[sessao_id]['extension_count'] = ext + 1
                                _automacoes_pap_ativas[sessao_id]['session_deadline'] = time.monotonic() + (EXTEND_SESSION_MINUTES * 60)
                        restantes = MAX_EXTEND_SESSION_COUNT - ext - 1
                        def _msg_ok():
                            WhatsAppService().enviar_mensagem_texto(
                                telefone,
                                "⏱ Tempo *estendido* em mais %d min. Você pode prorrogar mais %d vez(es)."
                                % (EXTEND_SESSION_MINUTES, restantes),
                            )
                        _executar_ops_django_sync(_msg_ok)
                    continue
                try:
                    with _automacoes_lock:
                        ctx = _automacoes_pap_ativas.get(sessao_id)
                    if not ctx:
                        break
                    automacao = ctx['automacao']
                    dados = ctx.get('dados', {})
                    action = cmd.get('action')

                    matricula_replay = (
                        ctx.get('vendedor_matricula')
                        or (dados or {}).get('matricula_pap')
                        or ''
                    )
                    if matricula_replay:
                        etapa_wpp_cur = _run_sync_returning(
                            lambda: (SessaoWhatsapp.objects.get(id=sessao_id).etapa or '')
                        )
                        dados_merge = {**(ctx.get('dados') or {}), **(dados or {})}
                        ok_rec, msg_rec = automacao.tentar_recuperar_portal_reset_etapa1(
                            dados_merge, str(matricula_replay), etapa_wpp_cur or ''
                        )
                        if not ok_rec:
                            def _sync_recuperacao_falhou():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                d_fail = dict(sess.dados_temp or {})
                                d_fail['_ultimo_cmd_erro'] = cmd
                                sess.dados_temp = d_fail
                                sess.etapa = 'venda_erro_retry'
                                sess.save()
                                with _automacoes_lock:
                                    if sessao_id in _automacoes_pap_ativas:
                                        _automacoes_pap_ativas[sessao_id]['dados'] = d_fail
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "⚠️ O portal voltou para a *Etapa 1* após um erro e *não foi possível reaplicar* todos os dados automaticamente.\n\n"
                                    f"Detalhe: {msg_rec}\n\n"
                                    "Digite *REPETIR* para tentar de novo ou *VENDER* para recomeçar.",
                                )
                            _executar_ops_django_sync(_sync_recuperacao_falhou)
                            continue
                        merged_ctx = automacao._pap_merge_dados_sessao_para_replay(
                            _run_sync_returning(lambda: (SessaoWhatsapp.objects.get(id=sessao_id).dados_temp or {}))
                        )
                        with _automacoes_lock:
                            if sessao_id in _automacoes_pap_ativas:
                                _automacoes_pap_ativas[sessao_id]['dados'] = merged_ctx
                        dados = merged_ctx

                    if action == 'etapa2_viabilidade':
                        cep_v = cmd.get('cep', '')
                        numero_v = cmd.get('numero', '')
                        referencia_v = cmd.get('referencia', '')
                        sucesso, msg, extra = automacao.etapa2_viabilidade(cep_v, numero_v, referencia_v)
                        # Códigos especiais primeiro: viabilidade só está concluída quando não há escolha pendente
                        if isinstance(extra, dict) and extra.get('_codigo') == 'MULTIPLOS_ENDERECOS':
                            lista = extra.get('lista', [])
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_endereco', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            # Incluir referencia no dados_temp para que, ao usuário escolher "1", o cmd tenha referencia
                            dados_multi = {**dados, 'referencia': referencia_v, 'viabilidade_lista_enderecos': lista}
                            def _multi():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_selecionar_endereco'
                                sess.dados_temp = dados_multi
                                sess.save()
                                linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Múltiplos endereços:*\n\n{linha}\n\nDigite o *número* do endereço (ex: 1, 2):")
                            _executar_ops_django_sync(_multi)
                        elif isinstance(extra, dict) and extra.get('_codigo') == 'COMPLEMENTOS':
                            lista = extra.get('lista', [])
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_complemento', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            def _comp():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_selecionar_complemento'
                                sess.dados_temp = {**dados, 'viabilidade_lista_complementos': lista}
                                sess.save()
                                linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Complementos:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número do complemento:")
                            _executar_ops_django_sync(_comp)
                        elif extra == "POSSE_ENCONTRADA":
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_posse', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            def _posse():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_posse_consultar_outro'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, msg + "\n\nDigite outro *CEP* ou *CONCLUIR*:")
                            _executar_ops_django_sync(_posse)
                        elif extra == "INDISPONIVEL_TECNICO":
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_indisponivel', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            def _indisp():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_indisponivel_voltar'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, msg + "\n\nDigite outro *CEP* ou *CONCLUIR*:")
                            _executar_ops_django_sync(_indisp)
                        elif msg == "PAP_ERRO_PORTAL_NIO":
                            automacao._fechar_sessao()
                            def _ops_portal():
                                liberar_bo(bo_id, telefone)
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'inicial'
                                sess.dados_temp = {}
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
                                )
                            _executar_ops_django_sync(_ops_portal)
                        elif sucesso:
                            # Viabilidade realmente concluída (endereço único ou já escolhido)
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            protocolo = automacao.dados_pedido.get('protocolo', '')
                            msg_viab = "✅ Endereço disponível para instalação!"
                            if protocolo:
                                msg_viab += f"\n📋 Protocolo: {protocolo}"
                            msg_viab += "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"
                            def _ok_viab():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                try:
                                    from crm_app.funil_venda_wpp_service import funil_registrar_protocolo
                                    funil_registrar_protocolo(sess, protocolo or '')
                                except Exception:
                                    pass
                                d_v = dict(sess.dados_temp or {})
                                d_v.pop('pap_replay_endereco_idx', None)
                                d_v.pop('pap_replay_complemento_escolha', None)
                                sess.dados_temp = d_v
                                sess.etapa = 'venda_cpf'
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, msg_viab)
                            _executar_ops_django_sync(_ok_viab)
                        else:
                            automacao._fechar_sessao()
                            def _indisp_fim():
                                liberar_bo(bo_id, telefone)
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'inicial'
                                sess.dados_temp = {}
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Endereço indisponível. {msg}\n\nDigite *VENDER* para tentar novamente.")
                            _executar_ops_django_sync(_indisp_fim)
                        continue

                    if action == 'etapa3':
                        cpf = cmd.get('cpf', '')
                        sucesso, msg, _ = automacao.etapa3_cadastro_cliente(cpf)
                        def _sync_etapa3():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            if sucesso:
                                dados = sess.dados_temp or {}
                                dados['cpf_cliente'] = cpf
                                sess.etapa = 'venda_celular'
                                sess.dados_temp = dados
                                sess.save()
                                try:
                                    from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
                                    funil_registrar_evento_sessao(sess, 'venda_cpf', {'cpf_cliente': cpf})
                                except Exception:
                                    pass
                                with _automacoes_lock:
                                    if sessao_id in _automacoes_pap_ativas:
                                        _automacoes_pap_ativas[sessao_id]['dados'] = dados
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    f"✅ {msg}\n\n📱 *ETAPA 3: CONTATO*\n\nDigite o *celular principal* do cliente (com DDD):"
                                )
                            else:
                                if msg == "PAP_ERRO_PORTAL_NIO":
                                    _encerrar_automacao_pap(sessao_id, (sess.dados_temp or {}).get('bo_usuario_id'), telefone)
                                    sess.etapa = 'inicial'
                                    sess.dados_temp = {}
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
                                    )
                                else:
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        f"❌ Cadastro: {msg}\n\nDigite outro CPF ou *CANCELAR*."
                                    )
                        _executar_ops_django_sync(_sync_etapa3)
                    elif action == 'etapa4':
                        celular = cmd.get('celular', '')
                        email = cmd.get('email', '')
                        celular_sec = cmd.get('celular_sec') or None
                        sucesso, msg, resultado_credito, _ = automacao.etapa4_contato(celular, email, celular_secundario=celular_sec)
                        def _sync_etapa4():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['email'] = email
                            if resultado_credito:
                                dados['resultado_credito'] = resultado_credito
                            try:
                                from crm_app.funil_venda_wpp_service import funil_registrar_credito
                                if resultado_credito:
                                    funil_registrar_credito(sess, resultado_credito)
                            except Exception:
                                pass
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                                    rejeitados = list(dados.get('celulares_rejeitados') or [])
                                    # Apenas o número que estava como principal é marcado como recusado (o secundário pode ser usado como novo principal)
                                    cel_principal_dig = _normalizar_celular_digitos(dados.get('celular', ''))
                                    if cel_principal_dig and cel_principal_dig not in rejeitados:
                                        rejeitados.append(cel_principal_dig)
                                    dados['celulares_rejeitados'] = rejeitados
                                    dados['celular'] = ''
                                    dados['celular_sec'] = ''
                                    dados['email'] = ''
                                    sess.etapa = 'venda_celular'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "⚠️ O número excede repetições ou é inválido. Vamos recomeçar os dados de contato.\n\n"
                                        "Digite o *celular principal* do cliente (com DDD):"
                                    )
                                elif msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                                    sess.etapa = 'venda_corrigir_email'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(telefone, "⚠️ E-mail já usado ou inválido. Digite outro e-mail:")
                                elif msg == "CREDITO_NEGADO":
                                    sess.etapa = 'venda_corrigir_cpf'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(telefone, "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou *CANCELAR*:")
                                elif msg == "PAP_ERRO_PORTAL_NIO":
                                    _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                                    sess.etapa = 'inicial'
                                    sess.dados_temp = {}
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
                                    )
                                else:
                                    WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg}\n\nDigite *CANCELAR* para sair.")
                            else:
                                dados.pop('celulares_rejeitados', None)
                                sess.etapa = 'venda_forma_pagamento'
                                sess.dados_temp = dados
                                sess.save()
                                texto_formas, _ = _texto_formas_pagamento_por_credito(dados.get('resultado_credito', ''))
                                WhatsAppService().enviar_mensagem_texto(telefone, "✅ Crédito aprovado!\n\n" + texto_formas)
                        _executar_ops_django_sync(_sync_etapa4)
                    elif action == 'etapa5_forma':
                        forma = cmd.get('forma', 'boleto')
                        sucesso, msg = automacao.etapa5_selecionar_forma_pagamento(forma)
                        def _sync_etapa5_forma():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['forma_pagamento'] = forma
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Forma de pagamento: {msg}\n\nDigite 1, 2 ou 3:")
                            else:
                                if forma == 'debito':
                                    sess.etapa = 'venda_debito_banco'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "✅ Pagamento: *Débito em Conta*\n\n"
                                        "🏦 Banco: 1=Itaú 2=Banrisul 3=Santander 4=BB 5=Bradesco 6=Nubank\n\nDigite o número do banco:"
                                    )
                                else:
                                    sess.etapa = 'venda_plano'
                                    sess.dados_temp = dados
                                    sess.save()
                                    forma_nome = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito'}
                                    texto_planos = _texto_etapa5_planos(forma or '')
                                    msg_etapa5 = f"✅ Pagamento: *{forma_nome.get(forma, forma)}*\n\n{texto_planos}"
                                    worker_t0 = cmd.get('worker_t0')
                                    if worker_t0 is not None:
                                        msg_etapa5 += "\n\n⏱ _%.1fs_" % round(time.monotonic() - worker_t0, 1)
                                    WhatsAppService().enviar_mensagem_texto(telefone, msg_etapa5)
                        _executar_ops_django_sync(_sync_etapa5_forma)
                    elif action == 'etapa5_debito':
                        sucesso, msg = automacao.etapa5_preencher_debito(
                            cmd.get('banco', ''), cmd.get('agencia', ''),
                            cmd.get('conta', ''), cmd.get('digito', ''),
                        )
                        def _sync_etapa5_debito():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Débito: {msg}\n\nDigite novamente o dígito:")
                            else:
                                sess.etapa = 'venda_plano'
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "✅ Débito preenchido!\n\n" + _texto_etapa5_planos('debito')
                                )
                        _executar_ops_django_sync(_sync_etapa5_debito)
                    elif action == 'etapa5_plano':
                        plano = cmd.get('plano', '500mega')
                        sucesso, msg = automacao.etapa5_selecionar_plano_com_validacao(plano)
                        def _sync_etapa5_plano():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['plano'] = plano
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Plano: {msg}\n\nDigite 1, 2 ou 3:")
                            else:
                                sess.etapa = 'venda_fixo'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, "✅ Plano selecionado!\n\n📞 Tem *Fixo* (R$ 30/mês)?\n\n1️⃣ Sim\n2️⃣ Não\n\nDigite o número:")
                        _executar_ops_django_sync(_sync_etapa5_plano)
                    elif action == 'etapa5_fixo':
                        tem_fixo = cmd.get('tem_fixo', False)
                        sucesso, msg = automacao.etapa5_selecionar_fixo(tem_fixo)
                        def _sync_etapa5_fixo():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['tem_fixo'] = tem_fixo
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Fixo: {msg}\n\nDigite 1 ou 2:")
                            else:
                                if tem_fixo:
                                    sess.etapa = 'venda_fixo_portabilidade'
                                else:
                                    sess.etapa = 'venda_streaming'
                                sess.dados_temp = dados
                                sess.save()
                                if tem_fixo:
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "✅ Fixo selecionado no PAP!\n\n"
                                        "📞 *Portabilidade do fixo*\n\n"
                                        "O cliente deseja *portar* o número fixo de outra operadora?\n\n"
                                        "1️⃣ Sim\n"
                                        "2️⃣ Não\n\n"
                                        "Digite o número:",
                                    )
                                else:
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "✅ Fixo registrado!\n\n📺 Quer *Streaming*?\n\n1️⃣ Sim\n2️⃣ Não\n\nDigite o número:",
                                    )
                        _executar_ops_django_sync(_sync_etapa5_fixo)
                    elif action == 'etapa5_fixo_portabilidade':
                        quer = cmd.get('quer_portabilidade', False)
                        numero = cmd.get('numero_port', '') or ''
                        operadora = cmd.get('operadora_texto', '') or ''
                        sucesso, msg = automacao.etapa5_fixo_finalizar_portabilidade(quer, numero, operadora)

                        def _sync_etapa5_fixo_port():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['fixo_portabilidade'] = quer
                            if quer:
                                dados['fixo_portabilidade_numero'] = numero
                                dados['fixo_portabilidade_operadora'] = operadora
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    f"❌ Portabilidade/Salvar fixo: {msg}\n\n"
                                    "Verifique os dados ou tente de novo.",
                                )
                            else:
                                sess.etapa = 'venda_streaming'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "✅ Fixo e portabilidade registrados!\n\n"
                                    "📺 Quer *Streaming*?\n\n"
                                    "1️⃣ Sim\n"
                                    "2️⃣ Não\n\n"
                                    "Digite o número:",
                                )

                        _executar_ops_django_sync(_sync_etapa5_fixo_port)
                    elif action == 'etapa5_streaming_avancar':
                        tem_stream = cmd.get('tem_streaming', False)
                        streaming_opcoes = cmd.get('streaming_opcoes', '')
                        plano = cmd.get('plano', '500mega')
                        def _get_sess_dados():
                            s = SessaoWhatsapp.objects.get(id=sessao_id)
                            return s, s.dados_temp or {}
                        sess, dados = _run_sync_returning(_get_sess_dados)
                        dados['tem_streaming'] = tem_stream
                        dados['streaming_opcoes'] = streaming_opcoes
                        sucesso, msg = automacao.etapa5_selecionar_streaming(tem_stream, streaming_opcoes, plano)
                        if not sucesso:
                            def _sync_streaming_err():
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Streaming: {msg}\n\nDigite 1 ou 2:")
                            _executar_ops_django_sync(_sync_streaming_err)
                        else:
                            sucesso2, msg2 = automacao.etapa5_clicar_avancar()
                            if not sucesso2:
                                _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                                def _sync_avancar_err():
                                    s = SessaoWhatsapp.objects.get(id=sessao_id)
                                    s.etapa = 'inicial'
                                    s.dados_temp = {}
                                    s.save()
                                    WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Erro ao avançar: {msg2}\n\nDigite *VENDER* para tentar novamente.")
                                _executar_ops_django_sync(_sync_avancar_err)
                            else:
                                def enviar(m):
                                    def _():
                                        try:
                                            WhatsAppService().enviar_mensagem_texto(telefone, m)
                                        except Exception as e:
                                            logger.error(f"[VENDA PAP] Erro ao enviar: {e}")
                                    _executar_ops_django_sync(_)
                                def resetar():
                                    def _():
                                        try:
                                            s = SessaoWhatsapp.objects.get(id=sessao_id)
                                            s.etapa = 'inicial'
                                            s.dados_temp = {}
                                            s.save()
                                        except Exception:
                                            pass
                                        from crm_app.pool_bo_pap import liberar_bo
                                        liberar_bo(dados.get('bo_usuario_id'), telefone)
                                    _executar_ops_django_sync(_)
                                _executar_venda_pap_etapa6_em_diante(
                                    telefone, sessao_id, dados, automacao,
                                    ctx.get('vendedor_matricula') or dados.get('matricula_pap'),
                                    ctx.get('vendedor_id') or dados.get('vendedor_id'),
                                    ctx.get('vendedor_nome') or dados.get('vendedor_nome', ''),
                                    dados.get('bo_usuario_id'),
                                    enviar, resetar,
                                )
                    elif action == 'selecionar_endereco':
                        idx = cmd.get('idx', 1)
                        cep, numero, ref = cmd.get('cep', ''), cmd.get('numero', ''), cmd.get('referencia', '')
                        sucesso, msg = automacao.etapa2_selecionar_endereco_instalacao(idx)
                        dados = _run_sync_returning(lambda: (SessaoWhatsapp.objects.get(id=sessao_id).dados_temp or {}))
                        if not sucesso:
                            def _sync_sel_err():
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg}\n\nDigite outro número ou *CANCELAR*.")
                            _executar_ops_django_sync(_sync_sel_err)
                        else:
                            sucesso2, msg2, extra2 = automacao.etapa2_preencher_referencia_e_continuar(cep, numero, ref)
                            # Encerrar automação no worker thread (não dentro do sync) para evitar "Cannot switch to a different thread"
                            if not sucesso2 and extra2 != "POSSE_ENCONTRADA" and extra2 != "INDISPONIVEL_TECNICO":
                                _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                            worker_t0 = cmd.get('worker_t0')
                            def _sync_sel_resposta():
                                import time
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                if not sucesso2:
                                    if extra2 == "POSSE_ENCONTRADA":
                                        sess.etapa = 'venda_posse_consultar_outro'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    elif extra2 == "INDISPONIVEL_TECNICO":
                                        sess.etapa = 'venda_indisponivel_voltar'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    else:
                                        sess.etapa = 'inicial'
                                        sess.dados_temp = {}
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente.")
                                elif isinstance(extra2, dict) and extra2.get('_codigo') == 'COMPLEMENTOS':
                                    with _automacoes_lock:
                                        ctx_up = _automacoes_pap_ativas.get(sessao_id) or {}
                                        ctx_up['phase'] = 'viabilidade_complemento'
                                        ctx_up['dados'] = dados
                                        ctx_up['cmd_queue'] = cmd_queue
                                        _automacoes_pap_ativas[sessao_id] = ctx_up
                                    lista = extra2.get('lista', [])
                                    sess.etapa = 'venda_selecionar_complemento'
                                    sess.dados_temp = {
                                        **dados,
                                        'viabilidade_lista_complementos': lista,
                                        'pap_replay_endereco_idx': cmd.get('idx', dados.get('pap_replay_endereco_idx')),
                                    }
                                    sess.save()
                                    linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                    WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Complementos encontrados:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO* se não tiver, ou o *número* do complemento (ex: 1, 2, 3):")
                                else:
                                    dados_sel = {**dados, 'pap_replay_endereco_idx': cmd.get('idx', 1)}
                                    with _automacoes_lock:
                                        _automacoes_pap_ativas[sessao_id] = {
                                            'automacao': automacao, 'phase': 'venda',
                                            'dados': dados_sel, 'bo_usuario_id': dados_sel.get('bo_usuario_id'), 'telefone': telefone,
                                            'vendedor_id': dados_sel.get('vendedor_id'), 'vendedor_matricula': dados_sel.get('matricula_pap'),
                                            'vendedor_nome': dados_sel.get('vendedor_nome', ''), 'cmd_queue': cmd_queue,
                                        }
                                    sess.etapa = 'venda_cpf'
                                    sess.dados_temp = dados_sel
                                    sess.save()
                                    protocolo = automacao.dados_pedido.get('protocolo', '')
                                    msg_ok = "✅ Endereço disponível!" + (f"\n📋 Protocolo: {protocolo}" if protocolo else "")
                                    elapsed = (time.monotonic() - worker_t0) if worker_t0 is not None else 0
                                    msg_ok += "\n\n⏱ _%.1fs_" % round(elapsed, 1)
                                    WhatsAppService().enviar_mensagem_texto(telefone, msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:")
                            _executar_ops_django_sync(_sync_sel_resposta)
                    elif action == 'modal_posse_voltar':
                        cep_novo = cmd.get('cep_novo', '')
                        automacao.etapa2_modal_posse_clicar_consultar_outro()
                        def _sync_modal_posse():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['cep'] = cep_novo
                            sess.etapa = 'venda_numero'
                            sess.dados_temp = dados
                            sess.save()
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            WhatsAppService().enviar_mensagem_texto(telefone, f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)")
                        _executar_ops_django_sync(_sync_modal_posse)
                    elif action == 'modal_indisponivel_voltar':
                        cep_novo = cmd.get('cep_novo', '')
                        automacao.etapa2_modal_indisponivel_clicar_voltar()
                        def _sync_modal_indisp():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['cep'] = cep_novo
                            sess.etapa = 'venda_numero'
                            sess.dados_temp = dados
                            sess.save()
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            WhatsAppService().enviar_mensagem_texto(telefone, f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)")
                        _executar_ops_django_sync(_sync_modal_indisp)
                    elif action == 'selecionar_complemento':
                        escolha = cmd.get('escolha', '')  # '0' ou 'sem' ou número
                        cep, numero = cmd.get('cep', ''), cmd.get('numero', '')
                        dados = _run_sync_returning(lambda: (SessaoWhatsapp.objects.get(id=sessao_id).dados_temp or {}))
                        if escolha.upper() in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
                            sucesso, msg = automacao.etapa2_selecionar_sem_complemento()
                        elif escolha.isdigit():
                            sucesso, msg = automacao.etapa2_selecionar_complemento(int(escolha))
                        else:
                            sucesso, msg = False, "Opção inválida"
                        if not sucesso:
                            def _sync_comp_err():
                                lista = dados.get('viabilidade_lista_complementos', [])
                                linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número (ex: 1)\n\n{linha}")
                            _executar_ops_django_sync(_sync_comp_err)
                        else:
                            sucesso2, msg2, extra2 = automacao.etapa2_clicar_avancar_apos_complemento(cep, numero)
                            if not sucesso2 and extra2 != "POSSE_ENCONTRADA" and extra2 != "INDISPONIVEL_TECNICO":
                                _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                            def _sync_comp_resposta():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                if not sucesso2:
                                    if extra2 == "POSSE_ENCONTRADA":
                                        sess.etapa = 'venda_posse_consultar_outro'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    elif extra2 == "INDISPONIVEL_TECNICO":
                                        sess.etapa = 'venda_indisponivel_voltar'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    else:
                                        sess.etapa = 'inicial'
                                        sess.dados_temp = {}
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente.")
                                else:
                                    dados_comp = {**dados, 'pap_replay_complemento_escolha': (escolha or '').strip()}
                                    with _automacoes_lock:
                                        _automacoes_pap_ativas[sessao_id] = {
                                            'automacao': automacao, 'phase': 'venda',
                                            'dados': dados_comp, 'bo_usuario_id': dados_comp.get('bo_usuario_id'), 'telefone': telefone,
                                            'vendedor_id': dados_comp.get('vendedor_id'), 'vendedor_matricula': dados_comp.get('matricula_pap'),
                                            'vendedor_nome': dados_comp.get('vendedor_nome', ''), 'cmd_queue': cmd_queue,
                                        }
                                    sess.etapa = 'venda_cpf'
                                    sess.dados_temp = dados_comp
                                    sess.save()
                                    protocolo = automacao.dados_pedido.get('protocolo', '')
                                    msg_ok = "✅ Endereço disponível!" + (f"\n📋 Protocolo: {protocolo}" if protocolo else "")
                                    worker_t0 = cmd.get('worker_t0')
                                    if worker_t0 is not None:
                                        import time
                                        elapsed = time.monotonic() - worker_t0
                                        msg_ok += "\n\n⏱ _%.1fs_" % round(elapsed, 1)
                                    WhatsAppService().enviar_mensagem_texto(telefone, msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:")
                            _executar_ops_django_sync(_sync_comp_resposta)
                except Exception as e:
                    logger.exception(f"[PAP Worker] Erro ao processar comando: {e}")
                    retry_count = cmd.get('_retry_count', 0)
                    if retry_count < 1:
                        try:
                            cmd_retry = {**cmd, '_retry_count': retry_count + 1}
                            cmd_queue.put(cmd_retry)
                            logger.info("[PAP Worker] Repetindo comando automaticamente (tentativa %s)", retry_count + 2)
                        except Exception:
                            pass
                        else:
                            continue
                    def _sync_send_error():
                        try:
                            from crm_app.models import SessaoWhatsapp
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            d = dict(sess.dados_temp or {})
                            d['_ultimo_cmd_erro'] = cmd
                            sess.dados_temp = d
                            sess.etapa = 'venda_erro_retry'
                            sess.save()
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = d
                            err_str = str(e).lower()
                            if "timeout" in err_str or "timed out" in err_str:
                                msg_erro = (
                                    "⏱ O site está demorando para responder na etapa atual.\n\n"
                                    "Seus dados foram salvos. Digite *REPETIR* para tentar novamente ou *CANCELAR* para sair."
                                )
                            else:
                                msg_erro = (
                                    f"❌ Ocorreu um erro: {e}\n\n"
                                    "Seus dados foram salvos. Digite *REPETIR* para tentar a última etapa novamente ou *CANCELAR* para sair."
                                )
                            WhatsAppService().enviar_mensagem_texto(telefone, msg_erro)
                        except Exception as sync_err:
                            logger.warning("[PAP Worker] Erro ao salvar sessão/notificar: %s", sync_err)
                            try:
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente."
                                )
                            except Exception:
                                pass
                    try:
                        _executar_ops_django_sync(_sync_send_error)
                    except Exception:
                        pass

        if mensagem_limpa in ('SIM', 'S'):
            # Obter login BackOffice do pool (seleção randômica entre disponíveis para automação VENDER)
            from crm_app.pool_bo_pap import obter_login_bo, MSG_TODOS_ACESSOS_EM_USO, obter_mensagem_fila_ocupado
            bo_usuario, erro = obter_login_bo(
                vendedor_telefone=telefone,
                sessao_whatsapp_id=sessao.id,
                tipo_automacao='vender',
            )
            if erro:
                if erro == MSG_TODOS_ACESSOS_EM_USO:
                    return obter_mensagem_fila_ocupado(telefone, 'vender')
                return erro
            # Guardar bo_usuario_id; a thread fará login + novo pedido + validar tela e só então pedirá CEP
            dados['bo_usuario_id'] = bo_usuario.id
            sessao.dados_temp = dados
            sessao.etapa = 'venda_aguardando_pap'  # só vai para venda_cep quando a tela estiver pronta
            sessao.save()

            cmd_queue = queue.Queue()

            def _thread_login_novo_pedido_e_worker(webhook_t0=None):
                """Executa login, novo pedido e valida tela na MESMA thread do worker (Playwright exige isso).
                webhook_t0: instante do início do request (time.monotonic()) para exibir tempo real na mensagem 'Acesso reservado'.
                """
                import time
                import django
                django.db.close_old_connections()
                t0 = time.monotonic()
                from crm_app.models import SessaoWhatsapp
                from usuarios.models import Usuario
                from crm_app.services_pap_nio import PAPNioAutomation
                from crm_app.pool_bo_pap import liberar_bo
                from django.conf import settings
                automacao = None  # para poder fechar e salvar trace no except
                try:
                    logger.info("[VENDER] Thread login/novo pedido iniciada para sessao_id=%s", sessao.id)
                    sess = SessaoWhatsapp.objects.get(id=sessao.id)
                    dados_t = sess.dados_temp or {}
                    bo_id = dados_t.get('bo_usuario_id')
                    if not bo_id:
                        sess.etapa = 'inicial'
                        sess.dados_temp = {}
                        sess.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, "❌ Sessão inválida. Digite *VENDER* para iniciar novamente.")
                        return
                    bo = Usuario.objects.get(id=bo_id)
                    vendedor_matricula = dados_t.get('matricula_pap')
                    headless = getattr(settings, 'PAP_HEADLESS', True)
                    capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
                    # Na thread de login sempre gravar trace (pap_trace_*.zip) para poder debugar falhas
                    gravar_trace = True
                    automacao = PAPNioAutomation(
                        matricula_pap=bo.matricula_pap,
                        senha_pap=bo.senha_pap,
                        vendedor_nome=dados_t.get('vendedor_nome', ''),
                        headless=headless,
                        run_id=str(sess.id),
                        capture_screenshots=capture_screenshots or gravar_trace,
                    )
                    # 1) Login
                    sucesso_login, msg_login = automacao.iniciar_sessao()
                    logger.info("[VENDER] Tempo até login: %.1fs", time.monotonic() - t0)
                    if not sucesso_login:
                        automacao._fechar_sessao()
                        liberar_bo(bo_id, telefone)
                        sess.etapa = 'inicial'
                        sess.dados_temp = {}
                        sess.save()
                        WhatsAppService().enviar_mensagem_texto(
                            telefone,
                            f"❌ *Erro ao acessar PAP*\n\n{msg_login}\n\nDigite *VENDER* para tentar novamente."
                        )
                        return
                    # 2) Novo pedido + TT do vendedor
                    sucesso_novo, msg_novo = automacao.iniciar_novo_pedido(vendedor_matricula)
                    logger.info("[VENDER] Tempo até novo pedido: %.1fs", time.monotonic() - t0)
                    if not sucesso_novo:
                        automacao._fechar_sessao()
                        liberar_bo(bo_id, telefone)
                        sess.etapa = 'inicial'
                        sess.dados_temp = {}
                        sess.save()
                        WhatsAppService().enviar_mensagem_texto(
                            telefone,
                            f"❌ *Erro ao iniciar pedido*\n\n{msg_novo}\n\nDigite *VENDER* para tentar novamente."
                        )
                        return
                    # 3) Validar que a tela está pronta para CEP (nada é pedido sem tela válida)
                    ok_tela, msg_tela = automacao.validar_tela_pronta_para_cep()
                    logger.info("[VENDER] Tempo até tela CEP validada: %.1fs", time.monotonic() - t0)
                    if not ok_tela:
                        automacao._fechar_sessao()
                        liberar_bo(bo_id, telefone)
                        sess.etapa = 'inicial'
                        sess.dados_temp = {}
                        sess.save()
                        WhatsAppService().enviar_mensagem_texto(
                            telefone,
                            f"❌ *Página não pronta*\n\n{msg_tela}\n\nDigite *VENDER* para tentar novamente."
                        )
                        return
                    # Nome do operador logado no portal (ex.: "Olá, ARIADNY STHER...")
                    nome_operador = (automacao.obter_nome_operador_logado() or "").strip()
                    # Se o usuário cancelou enquanto conectava, não registrar nem pedir CEP.
                    # DB/save neste thread falha (Playwright deixa event loop no thread → SynchronousOnlyOperation).
                    # Rodar verificação de etapa e save + envio WhatsApp em thread separado (sem event loop).
                    etapa_result = [None]

                    def _db_get_etapa():
                        try:
                            s = SessaoWhatsapp.objects.using("default").get(pk=sessao.id)
                            etapa_result[0] = s.etapa or "venda_aguardando_pap"
                        except Exception as _e:
                            logger.warning("[VENDER] Não foi possível verificar etapa (thread): %s", _e)
                            etapa_result[0] = "venda_aguardando_pap"

                    t_etapa = threading.Thread(target=_db_get_etapa)
                    t_etapa.start()
                    t_etapa.join(timeout=10)
                    etapa_atual = etapa_result[0] or "venda_aguardando_pap"
                    if etapa_atual != "venda_aguardando_pap":
                        automacao._fechar_sessao()
                        liberar_bo(bo_id, telefone)
                        return
                    # Registrar automação (em memória) e pedir CEP
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sess.id] = {
                            'automacao': automacao, 'phase': 'venda',
                            'dados': dados_t, 'bo_usuario_id': bo_id, 'telefone': telefone,
                            'vendedor_id': dados_t.get('vendedor_id'), 'vendedor_matricula': vendedor_matricula,
                            'vendedor_nome': dados_t.get('vendedor_nome', ''),
                            'cmd_queue': cmd_queue,
                            'session_deadline': time.monotonic() + SESSION_TIMEOUT_SECONDS,
                            'extension_count': 0,
                        }
                    # Save + enviar mensagem em thread sem event loop (evita SynchronousOnlyOperation)
                    _notify_t0 = webhook_t0 if webhook_t0 is not None else time.monotonic()

                    def _db_save_e_notify(t0=_notify_t0, nome_op=nome_operador):
                        from crm_app.whatsapp_service import WhatsAppService
                        import time
                        try:
                            s = SessaoWhatsapp.objects.using("default").get(pk=sessao.id)
                            s.etapa = "venda_cep"
                            s.save(update_fields=["etapa"])
                            elapsed = time.monotonic() - t0
                            if nome_op:
                                primeiro_nome = (nome_op.split()[0] if nome_op.strip() else nome_op).strip().title()
                                saudacao = (
                                    f"✅ Olá, meu nome é *{primeiro_nome}* e vou guiar você na ativação! Bora lá?\n\n"
                                )
                            else:
                                saudacao = "✅ Acesso reservado!\n\n"
                            msg = (
                                saudacao
                                + "📍 *ETAPA 1: ENDEREÇO*\n\n"
                                + "Digite o *CEP* do endereço de instalação.\n"
                                + "(Se precisar de mais tempo, digite *ESTENDER* para prorrogar.)\n\n"
                                + "⏱ _%.1fs_" % round(elapsed, 1)
                            )
                            WhatsAppService().enviar_mensagem_texto(telefone, msg)
                        except Exception as _e:
                            logger.exception("[VENDER] Erro ao salvar etapa e notificar: %s", _e)

                    t_save = threading.Thread(target=_db_save_e_notify)
                    t_save.start()
                    t_save.join(timeout=15)
                    _pap_worker_loop(cmd_queue, sess.id, telefone, bo_id)
                except Exception as e:
                    logger.exception("[VENDER] Erro na thread login/novo pedido")
                    if automacao is not None:
                        try:
                            automacao._fechar_sessao()  # salva trace (pap_trace_*.zip) mesmo quando falha
                        except Exception:
                            pass
                    sessao_id_exc = sessao.id
                    telefone_exc = telefone
                    msg_erro = str(e)

                    def _db_reset_e_notify():
                        from crm_app.whatsapp_service import WhatsAppService
                        bo_id_liberar = None
                        try:
                            s = SessaoWhatsapp.objects.using("default").get(pk=sessao_id_exc)
                            bo_id_liberar = (s.dados_temp or {}).get("bo_usuario_id")
                            s.etapa = "inicial"
                            s.dados_temp = {}
                            s.save(update_fields=["etapa", "dados_temp"])
                        except Exception as db_err:
                            logger.warning("[VENDER] Erro ao resetar sessão no except: %s", db_err)
                        if bo_id_liberar:
                            try:
                                liberar_bo(bo_id_liberar, telefone_exc)
                            except Exception:
                                pass
                        try:
                            WhatsAppService().enviar_mensagem_texto(
                                telefone_exc,
                                f"❌ Erro ao conectar ao PAP: {msg_erro}\n\nDigite *VENDER* para tentar novamente."
                            )
                        except Exception:
                            pass

                    t_reset = threading.Thread(target=_db_reset_e_notify)
                    t_reset.start()
                    t_reset.join(timeout=15)

            t = threading.Thread(target=_thread_login_novo_pedido_e_worker, kwargs={"webhook_t0": webhook_t0})
            t.daemon = True
            t.start()
            return (
                "⏳ Conectando ao PAP e abrindo novo pedido...\n\n"
                "Aguarde alguns segundos. Quando a tela estiver pronta, você receberá a confirmação e poderá digitar o *CEP*."
            )
        if mensagem_limpa in ('CANCELAR', 'NAO', 'NÃO'):
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return "❌ Venda cancelada. Digite *VENDER* para iniciar novamente."
        return "❌ Responda *SIM* (ou toque no botão) para iniciar, ou *CANCELAR* para sair."
    
    # --- ETAPA: Aguardando PAP (login + novo pedido em andamento) ---
    if etapa == 'venda_aguardando_pap':
        return "⏳ Ainda conectando ao PAP e abrindo novo pedido. Aguarde a confirmação para digitar o *CEP*."

    # --- ETAPA: CEP ---
    elif etapa == 'venda_cep':
        cep_limpo = limpar_texto_cep_cpf(mensagem)
        if not cep_limpo or len(cep_limpo) < 8:
            return "❌ CEP inválido. Digite o CEP completo (8 dígitos):"
        
        dados['cep'] = cep_limpo
        try:
            from crm_app.funil_venda_wpp_service import funil_iniciar_com_cep
            funil_iniciar_com_cep(sessao, dados, cep_limpo)
            dados = sessao.dados_temp or {}
        except Exception:
            pass
        sessao.dados_temp = dados
        sessao.etapa = 'venda_numero'
        sessao.save()
        
        return (
            f"✅ CEP: *{cep_limpo}*\n\n"
            f"Agora digite o *número* do endereço:\n"
            f"(ou digite *SN* se não houver número)"
        )
    
    # --- ETAPA: Número ---
    elif etapa == 'venda_numero':
        numero = mensagem.strip()
        if mensagem_limpa == 'SN':
            numero = 'S/N'
        
        dados['numero'] = numero
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
            funil_registrar_evento_sessao(sessao, 'venda_numero', {'numero': numero})
            dados = sessao.dados_temp or {}
        except Exception:
            pass
        sessao.dados_temp = dados
        sessao.etapa = 'venda_referencia'
        sessao.save()
        
        return (
            f"✅ Número: *{numero}*\n\n"
            f"Digite uma *referência* do endereço:\n"
            f"(ex: Próximo ao mercado, casa azul, etc.)"
        )
    
    # --- ETAPA: Referência ---
    elif etapa == 'venda_referencia':
        referencia = mensagem.strip()
        if len(referencia) < 3:
            return "❌ Referência muito curta. Digite uma referência mais detalhada:"

        dados['referencia'] = referencia
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
            funil_registrar_evento_sessao(sessao, 'venda_referencia', {'referencia': referencia})
            dados = sessao.dados_temp or {}
        except Exception:
            pass
        sessao.dados_temp = dados
        sessao.save()

        # Se a automação já foi aberta no SIM (login + novo pedido), só enfileirar viabilidade
        with _automacoes_lock:
            ctx_existente = _automacoes_pap_ativas.get(sessao.id)
        if ctx_existente and ctx_existente.get('automacao') and ctx_existente.get('cmd_queue'):
            ctx_existente['cmd_queue'].put({
                'action': 'etapa2_viabilidade',
                'cep': dados.get('cep', ''),
                'numero': dados.get('numero', ''),
                'referencia': referencia,
            })
            return "⏳ Consultando viabilidade do endereço... Aguarde. Você receberá a resposta em seguida."

        # Fallback: automação ainda não aberta (ex.: servidor reiniciou) — abre sessão, novo pedido e viabilidade
        from usuarios.models import Usuario
        from crm_app.services_pap_nio import PAPNioAutomation
        from crm_app.whatsapp_service import WhatsAppService
        from crm_app.pool_bo_pap import liberar_bo
        import threading

        def _executar_ops_django_sync(func):
            """Executa operações Django em thread limpa (evita SynchronousOnlyOperation após Playwright)."""
            q = queue.Queue()
            def run():
                try:
                    import django.db
                    django.db.close_old_connections()
                    func()
                    q.put(None)
                except Exception as e:
                    q.put(e)
            t = threading.Thread(target=run)
            t.start()
            t.join(timeout=60)
            if not q.empty():
                exc = q.get()
                if exc:
                    raise exc

        def _run_sync_returning(callable):
            """Executa callable em thread e retorna o valor (para leituras Django no PAP worker)."""
            result = [None]
            exc_holder = [None]
            def run():
                try:
                    import django.db
                    django.db.close_old_connections()
                    result[0] = callable()
                except Exception as e:
                    exc_holder[0] = e
            t = threading.Thread(target=run)
            t.start()
            t.join(timeout=60)
            if exc_holder[0]:
                raise exc_holder[0]
            return result[0]

        def _pap_worker_loop(cmd_queue, sessao_id, telefone, bo_id):
            """Loop do worker: processa comandos na mesma thread da automação (evita 'cannot switch to different thread')."""
            from crm_app.models import SessaoWhatsapp
            from crm_app.pool_bo_pap import liberar_bo
            while True:
                try:
                    with _automacoes_lock:
                        ctx = _automacoes_pap_ativas.get(sessao_id)
                    if not ctx:
                        break
                    now_ts = time.monotonic()
                    deadline = ctx.get('session_deadline')
                    if deadline is None:
                        deadline = now_ts + SESSION_TIMEOUT_SECONDS
                        with _automacoes_lock:
                            if sessao_id in _automacoes_pap_ativas:
                                _automacoes_pap_ativas[sessao_id]['session_deadline'] = deadline
                    remaining = max(0, deadline - now_ts)
                    if remaining <= 0:
                        logger.info("[VENDER] Sessão encerrada por tempo (10 min sem comando ou limite de prorrogação)")
                        break
                    cmd = cmd_queue.get(timeout=min(60, remaining))
                except queue.Empty:
                    continue
                if cmd.get('action') == 'STOP':
                    break
                if cmd.get('action') == 'ESTENDER':
                    with _automacoes_lock:
                        ctx = _automacoes_pap_ativas.get(sessao_id)
                    if not ctx:
                        break
                    ext = ctx.get('extension_count', 0)
                    if ext >= MAX_EXTEND_SESSION_COUNT:
                        def _msg_limite():
                            WhatsAppService().enviar_mensagem_texto(
                                telefone,
                                "⚠️ Limite de prorrogações atingido (máx. %d). Continue o atendimento ou digite *CANCELAR*."
                                % MAX_EXTEND_SESSION_COUNT,
                            )
                        _executar_ops_django_sync(_msg_limite)
                    else:
                        with _automacoes_lock:
                            if sessao_id in _automacoes_pap_ativas:
                                _automacoes_pap_ativas[sessao_id]['extension_count'] = ext + 1
                                _automacoes_pap_ativas[sessao_id]['session_deadline'] = time.monotonic() + (EXTEND_SESSION_MINUTES * 60)
                        restantes = MAX_EXTEND_SESSION_COUNT - ext - 1
                        def _msg_ok():
                            WhatsAppService().enviar_mensagem_texto(
                                telefone,
                                "⏱ Tempo *estendido* em mais %d min. Você pode prorrogar mais %d vez(es)."
                                % (EXTEND_SESSION_MINUTES, restantes),
                            )
                        _executar_ops_django_sync(_msg_ok)
                    continue
                try:
                    with _automacoes_lock:
                        ctx = _automacoes_pap_ativas.get(sessao_id)
                    if not ctx:
                        break
                    automacao = ctx['automacao']
                    dados = ctx.get('dados', {})
                    action = cmd.get('action')

                    matricula_replay = (
                        ctx.get('vendedor_matricula')
                        or (dados or {}).get('matricula_pap')
                        or ''
                    )
                    if matricula_replay:
                        etapa_wpp_cur = _run_sync_returning(
                            lambda: (SessaoWhatsapp.objects.get(id=sessao_id).etapa or '')
                        )
                        dados_merge = {**(ctx.get('dados') or {}), **(dados or {})}
                        ok_rec, msg_rec = automacao.tentar_recuperar_portal_reset_etapa1(
                            dados_merge, str(matricula_replay), etapa_wpp_cur or ''
                        )
                        if not ok_rec:
                            def _sync_recuperacao_falhou():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                d_fail = dict(sess.dados_temp or {})
                                d_fail['_ultimo_cmd_erro'] = cmd
                                sess.dados_temp = d_fail
                                sess.etapa = 'venda_erro_retry'
                                sess.save()
                                with _automacoes_lock:
                                    if sessao_id in _automacoes_pap_ativas:
                                        _automacoes_pap_ativas[sessao_id]['dados'] = d_fail
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "⚠️ O portal voltou para a *Etapa 1* após um erro e *não foi possível reaplicar* todos os dados automaticamente.\n\n"
                                    f"Detalhe: {msg_rec}\n\n"
                                    "Digite *REPETIR* para tentar de novo ou *VENDER* para recomeçar.",
                                )
                            _executar_ops_django_sync(_sync_recuperacao_falhou)
                            continue
                        merged_ctx = automacao._pap_merge_dados_sessao_para_replay(
                            _run_sync_returning(lambda: (SessaoWhatsapp.objects.get(id=sessao_id).dados_temp or {}))
                        )
                        with _automacoes_lock:
                            if sessao_id in _automacoes_pap_ativas:
                                _automacoes_pap_ativas[sessao_id]['dados'] = merged_ctx
                        dados = merged_ctx

                    if action == 'etapa2_viabilidade':
                        cep_v = cmd.get('cep', '')
                        numero_v = cmd.get('numero', '')
                        referencia_v = cmd.get('referencia', '')
                        sucesso, msg, extra = automacao.etapa2_viabilidade(cep_v, numero_v, referencia_v)
                        # Códigos especiais primeiro: viabilidade só está concluída quando não há escolha pendente
                        if isinstance(extra, dict) and extra.get('_codigo') == 'MULTIPLOS_ENDERECOS':
                            lista = extra.get('lista', [])
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_endereco', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            # Incluir referencia no dados_temp para que, ao usuário escolher "1", o cmd tenha referencia
                            dados_multi = {**dados, 'referencia': referencia_v, 'viabilidade_lista_enderecos': lista}
                            def _multi():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_selecionar_endereco'
                                sess.dados_temp = dados_multi
                                sess.save()
                                linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Múltiplos endereços:*\n\n{linha}\n\nDigite o *número* do endereço (ex: 1, 2):")
                            _executar_ops_django_sync(_multi)
                        elif isinstance(extra, dict) and extra.get('_codigo') == 'COMPLEMENTOS':
                            lista = extra.get('lista', [])
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_complemento', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            def _comp():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_selecionar_complemento'
                                sess.dados_temp = {**dados, 'viabilidade_lista_complementos': lista}
                                sess.save()
                                linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Complementos:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número do complemento:")
                            _executar_ops_django_sync(_comp)
                        elif extra == "POSSE_ENCONTRADA":
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_posse', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            def _posse():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_posse_consultar_outro'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, msg + "\n\nDigite outro *CEP* ou *CONCLUIR*:")
                            _executar_ops_django_sync(_posse)
                        elif extra == "INDISPONIVEL_TECNICO":
                            with _automacoes_lock:
                                _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'phase': 'viabilidade_indisponivel', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': ctx.get('cmd_queue') or cmd_queue}
                            def _indisp():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'venda_indisponivel_voltar'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, msg + "\n\nDigite outro *CEP* ou *CONCLUIR*:")
                            _executar_ops_django_sync(_indisp)
                        elif msg == "PAP_ERRO_PORTAL_NIO":
                            automacao._fechar_sessao()
                            def _ops_portal():
                                liberar_bo(bo_id, telefone)
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'inicial'
                                sess.dados_temp = {}
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
                                )
                            _executar_ops_django_sync(_ops_portal)
                        elif sucesso:
                            # Viabilidade realmente concluída (endereço único ou já escolhido)
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            protocolo = automacao.dados_pedido.get('protocolo', '')
                            msg_viab = "✅ Endereço disponível para instalação!"
                            if protocolo:
                                msg_viab += f"\n📋 Protocolo: {protocolo}"
                            msg_viab += "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"
                            def _ok_viab():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                try:
                                    from crm_app.funil_venda_wpp_service import funil_registrar_protocolo
                                    funil_registrar_protocolo(sess, protocolo or '')
                                except Exception:
                                    pass
                                d_v = dict(sess.dados_temp or {})
                                d_v.pop('pap_replay_endereco_idx', None)
                                d_v.pop('pap_replay_complemento_escolha', None)
                                sess.dados_temp = d_v
                                sess.etapa = 'venda_cpf'
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, msg_viab)
                            _executar_ops_django_sync(_ok_viab)
                        else:
                            automacao._fechar_sessao()
                            def _indisp_fim():
                                liberar_bo(bo_id, telefone)
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                sess.etapa = 'inicial'
                                sess.dados_temp = {}
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Endereço indisponível. {msg}\n\nDigite *VENDER* para tentar novamente.")
                            _executar_ops_django_sync(_indisp_fim)
                        continue

                    if action == 'etapa3':
                        cpf = cmd.get('cpf', '')
                        sucesso, msg, _ = automacao.etapa3_cadastro_cliente(cpf)
                        def _sync_etapa3():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            if sucesso:
                                dados = sess.dados_temp or {}
                                dados['cpf_cliente'] = cpf
                                sess.etapa = 'venda_celular'
                                sess.dados_temp = dados
                                sess.save()
                                try:
                                    from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
                                    funil_registrar_evento_sessao(sess, 'venda_cpf', {'cpf_cliente': cpf})
                                except Exception:
                                    pass
                                with _automacoes_lock:
                                    if sessao_id in _automacoes_pap_ativas:
                                        _automacoes_pap_ativas[sessao_id]['dados'] = dados
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    f"✅ {msg}\n\n📱 *ETAPA 3: CONTATO*\n\nDigite o *celular principal* do cliente (com DDD):"
                                )
                            else:
                                if msg == "PAP_ERRO_PORTAL_NIO":
                                    _encerrar_automacao_pap(sessao_id, (sess.dados_temp or {}).get('bo_usuario_id'), telefone)
                                    sess.etapa = 'inicial'
                                    sess.dados_temp = {}
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
                                    )
                                else:
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        f"❌ Cadastro: {msg}\n\nDigite outro CPF ou *CANCELAR*."
                                    )
                        _executar_ops_django_sync(_sync_etapa3)
                    elif action == 'etapa4':
                        celular = cmd.get('celular', '')
                        email = cmd.get('email', '')
                        celular_sec = cmd.get('celular_sec') or None
                        sucesso, msg, resultado_credito, _ = automacao.etapa4_contato(celular, email, celular_secundario=celular_sec)
                        def _sync_etapa4():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['email'] = email
                            if resultado_credito:
                                dados['resultado_credito'] = resultado_credito
                            try:
                                from crm_app.funil_venda_wpp_service import funil_registrar_credito
                                if resultado_credito:
                                    funil_registrar_credito(sess, resultado_credito)
                            except Exception:
                                pass
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                                    rejeitados = list(dados.get('celulares_rejeitados') or [])
                                    # Apenas o número que estava como principal é marcado como recusado (o secundário pode ser usado como novo principal)
                                    cel_principal_dig = _normalizar_celular_digitos(dados.get('celular', ''))
                                    if cel_principal_dig and cel_principal_dig not in rejeitados:
                                        rejeitados.append(cel_principal_dig)
                                    dados['celulares_rejeitados'] = rejeitados
                                    dados['celular'] = ''
                                    dados['celular_sec'] = ''
                                    dados['email'] = ''
                                    sess.etapa = 'venda_celular'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "⚠️ O número excede repetições ou é inválido. Vamos recomeçar os dados de contato.\n\n"
                                        "Digite o *celular principal* do cliente (com DDD):"
                                    )
                                elif msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                                    sess.etapa = 'venda_corrigir_email'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(telefone, "⚠️ E-mail já usado ou inválido. Digite outro e-mail:")
                                elif msg == "CREDITO_NEGADO":
                                    sess.etapa = 'venda_corrigir_cpf'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(telefone, "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou *CANCELAR*:")
                                elif msg == "PAP_ERRO_PORTAL_NIO":
                                    _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                                    sess.etapa = 'inicial'
                                    sess.dados_temp = {}
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
                                    )
                                else:
                                    WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg}\n\nDigite *CANCELAR* para sair.")
                            else:
                                dados.pop('celulares_rejeitados', None)
                                sess.etapa = 'venda_forma_pagamento'
                                sess.dados_temp = dados
                                sess.save()
                                texto_formas, _ = _texto_formas_pagamento_por_credito(dados.get('resultado_credito', ''))
                                WhatsAppService().enviar_mensagem_texto(telefone, "✅ Crédito aprovado!\n\n" + texto_formas)
                        _executar_ops_django_sync(_sync_etapa4)
                    elif action == 'etapa5_forma':
                        forma = cmd.get('forma', 'boleto')
                        sucesso, msg = automacao.etapa5_selecionar_forma_pagamento(forma)
                        def _sync_etapa5_forma():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['forma_pagamento'] = forma
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Forma de pagamento: {msg}\n\nDigite 1, 2 ou 3:")
                            else:
                                if forma == 'debito':
                                    sess.etapa = 'venda_debito_banco'
                                    sess.dados_temp = dados
                                    sess.save()
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "✅ Pagamento: *Débito em Conta*\n\n"
                                        "🏦 Banco: 1=Itaú 2=Banrisul 3=Santander 4=BB 5=Bradesco 6=Nubank\n\nDigite o número do banco:"
                                    )
                                else:
                                    sess.etapa = 'venda_plano'
                                    sess.dados_temp = dados
                                    sess.save()
                                    forma_nome = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito'}
                                    texto_planos = _texto_etapa5_planos(forma or '')
                                    msg_etapa5 = f"✅ Pagamento: *{forma_nome.get(forma, forma)}*\n\n{texto_planos}"
                                    worker_t0 = cmd.get('worker_t0')
                                    if worker_t0 is not None:
                                        msg_etapa5 += "\n\n⏱ _%.1fs_" % round(time.monotonic() - worker_t0, 1)
                                    WhatsAppService().enviar_mensagem_texto(telefone, msg_etapa5)
                        _executar_ops_django_sync(_sync_etapa5_forma)
                    elif action == 'etapa5_debito':
                        sucesso, msg = automacao.etapa5_preencher_debito(
                            cmd.get('banco', ''), cmd.get('agencia', ''),
                            cmd.get('conta', ''), cmd.get('digito', ''),
                        )
                        def _sync_etapa5_debito():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Débito: {msg}\n\nDigite novamente o dígito:")
                            else:
                                sess.etapa = 'venda_plano'
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "✅ Débito preenchido!\n\n" + _texto_etapa5_planos('debito')
                                )
                        _executar_ops_django_sync(_sync_etapa5_debito)
                    elif action == 'etapa5_plano':
                        plano = cmd.get('plano', '500mega')
                        sucesso, msg = automacao.etapa5_selecionar_plano_com_validacao(plano)
                        def _sync_etapa5_plano():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['plano'] = plano
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Plano: {msg}\n\nDigite 1, 2 ou 3:")
                            else:
                                sess.etapa = 'venda_fixo'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(telefone, "✅ Plano selecionado!\n\n📞 Tem *Fixo* (R$ 30/mês)?\n\n1️⃣ Sim\n2️⃣ Não\n\nDigite o número:")
                        _executar_ops_django_sync(_sync_etapa5_plano)
                    elif action == 'etapa5_fixo':
                        tem_fixo = cmd.get('tem_fixo', False)
                        sucesso, msg = automacao.etapa5_selecionar_fixo(tem_fixo)
                        def _sync_etapa5_fixo():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['tem_fixo'] = tem_fixo
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Fixo: {msg}\n\nDigite 1 ou 2:")
                            else:
                                if tem_fixo:
                                    sess.etapa = 'venda_fixo_portabilidade'
                                else:
                                    sess.etapa = 'venda_streaming'
                                sess.dados_temp = dados
                                sess.save()
                                if tem_fixo:
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "✅ Fixo selecionado no PAP!\n\n"
                                        "📞 *Portabilidade do fixo*\n\n"
                                        "O cliente deseja *portar* o número fixo de outra operadora?\n\n"
                                        "1️⃣ Sim\n"
                                        "2️⃣ Não\n\n"
                                        "Digite o número:",
                                    )
                                else:
                                    WhatsAppService().enviar_mensagem_texto(
                                        telefone,
                                        "✅ Fixo registrado!\n\n📺 Quer *Streaming*?\n\n1️⃣ Sim\n2️⃣ Não\n\nDigite o número:",
                                    )
                        _executar_ops_django_sync(_sync_etapa5_fixo)
                    elif action == 'etapa5_fixo_portabilidade':
                        quer = cmd.get('quer_portabilidade', False)
                        numero = cmd.get('numero_port', '') or ''
                        operadora = cmd.get('operadora_texto', '') or ''
                        sucesso, msg = automacao.etapa5_fixo_finalizar_portabilidade(quer, numero, operadora)

                        def _sync_etapa5_fixo_port():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['fixo_portabilidade'] = quer
                            if quer:
                                dados['fixo_portabilidade_numero'] = numero
                                dados['fixo_portabilidade_operadora'] = operadora
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            if not sucesso:
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    f"❌ Portabilidade/Salvar fixo: {msg}\n\n"
                                    "Verifique os dados ou tente de novo.",
                                )
                            else:
                                sess.etapa = 'venda_streaming'
                                sess.dados_temp = dados
                                sess.save()
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    "✅ Fixo e portabilidade registrados!\n\n"
                                    "📺 Quer *Streaming*?\n\n"
                                    "1️⃣ Sim\n"
                                    "2️⃣ Não\n\n"
                                    "Digite o número:",
                                )

                        _executar_ops_django_sync(_sync_etapa5_fixo_port)
                    elif action == 'etapa5_streaming_avancar':
                        tem_stream = cmd.get('tem_streaming', False)
                        streaming_opcoes = cmd.get('streaming_opcoes', '')
                        plano = cmd.get('plano', '500mega')
                        def _get_sess_dados():
                            s = SessaoWhatsapp.objects.get(id=sessao_id)
                            return s, s.dados_temp or {}
                        sess, dados = _run_sync_returning(_get_sess_dados)
                        dados['tem_streaming'] = tem_stream
                        dados['streaming_opcoes'] = streaming_opcoes
                        sucesso, msg = automacao.etapa5_selecionar_streaming(tem_stream, streaming_opcoes, plano)
                        if not sucesso:
                            def _sync_streaming_err():
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Streaming: {msg}\n\nDigite 1 ou 2:")
                            _executar_ops_django_sync(_sync_streaming_err)
                        else:
                            sucesso2, msg2 = automacao.etapa5_clicar_avancar()
                            if not sucesso2:
                                _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                                def _sync_avancar_err():
                                    s = SessaoWhatsapp.objects.get(id=sessao_id)
                                    s.etapa = 'inicial'
                                    s.dados_temp = {}
                                    s.save()
                                    WhatsAppService().enviar_mensagem_texto(telefone, f"❌ Erro ao avançar: {msg2}\n\nDigite *VENDER* para tentar novamente.")
                                _executar_ops_django_sync(_sync_avancar_err)
                            else:
                                def enviar(m):
                                    def _():
                                        try:
                                            WhatsAppService().enviar_mensagem_texto(telefone, m)
                                        except Exception as e:
                                            logger.error(f"[VENDA PAP] Erro ao enviar: {e}")
                                    _executar_ops_django_sync(_)
                                def resetar():
                                    def _():
                                        try:
                                            s = SessaoWhatsapp.objects.get(id=sessao_id)
                                            s.etapa = 'inicial'
                                            s.dados_temp = {}
                                            s.save()
                                        except Exception:
                                            pass
                                        from crm_app.pool_bo_pap import liberar_bo
                                        liberar_bo(dados.get('bo_usuario_id'), telefone)
                                    _executar_ops_django_sync(_)
                                _executar_venda_pap_etapa6_em_diante(
                                    telefone, sessao_id, dados, automacao,
                                    ctx.get('vendedor_matricula') or dados.get('matricula_pap'),
                                    ctx.get('vendedor_id') or dados.get('vendedor_id'),
                                    ctx.get('vendedor_nome') or dados.get('vendedor_nome', ''),
                                    dados.get('bo_usuario_id'),
                                    enviar, resetar,
                                )
                    elif action == 'selecionar_endereco':
                        idx = cmd.get('idx', 1)
                        cep, numero, ref = cmd.get('cep', ''), cmd.get('numero', ''), cmd.get('referencia', '')
                        sucesso, msg = automacao.etapa2_selecionar_endereco_instalacao(idx)
                        dados = _run_sync_returning(lambda: (SessaoWhatsapp.objects.get(id=sessao_id).dados_temp or {}))
                        if not sucesso:
                            def _sync_sel_err():
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg}\n\nDigite outro número ou *CANCELAR*.")
                            _executar_ops_django_sync(_sync_sel_err)
                        else:
                            sucesso2, msg2, extra2 = automacao.etapa2_preencher_referencia_e_continuar(cep, numero, ref)
                            # Encerrar automação no worker thread (não dentro do sync) para evitar "Cannot switch to a different thread"
                            if not sucesso2 and extra2 != "POSSE_ENCONTRADA" and extra2 != "INDISPONIVEL_TECNICO":
                                _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                            worker_t0 = cmd.get('worker_t0')
                            def _sync_sel_resposta():
                                import time
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                if not sucesso2:
                                    if extra2 == "POSSE_ENCONTRADA":
                                        sess.etapa = 'venda_posse_consultar_outro'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    elif extra2 == "INDISPONIVEL_TECNICO":
                                        sess.etapa = 'venda_indisponivel_voltar'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    else:
                                        sess.etapa = 'inicial'
                                        sess.dados_temp = {}
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente.")
                                elif isinstance(extra2, dict) and extra2.get('_codigo') == 'COMPLEMENTOS':
                                    with _automacoes_lock:
                                        ctx_up = _automacoes_pap_ativas.get(sessao_id) or {}
                                        ctx_up['phase'] = 'viabilidade_complemento'
                                        ctx_up['dados'] = dados
                                        ctx_up['cmd_queue'] = cmd_queue
                                        _automacoes_pap_ativas[sessao_id] = ctx_up
                                    lista = extra2.get('lista', [])
                                    sess.etapa = 'venda_selecionar_complemento'
                                    sess.dados_temp = {
                                        **dados,
                                        'viabilidade_lista_complementos': lista,
                                        'pap_replay_endereco_idx': cmd.get('idx', dados.get('pap_replay_endereco_idx')),
                                    }
                                    sess.save()
                                    linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                    WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Complementos encontrados:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO* se não tiver, ou o *número* do complemento (ex: 1, 2, 3):")
                                else:
                                    dados_sel = {**dados, 'pap_replay_endereco_idx': cmd.get('idx', 1)}
                                    with _automacoes_lock:
                                        _automacoes_pap_ativas[sessao_id] = {
                                            'automacao': automacao, 'phase': 'venda',
                                            'dados': dados_sel, 'bo_usuario_id': dados_sel.get('bo_usuario_id'), 'telefone': telefone,
                                            'vendedor_id': dados_sel.get('vendedor_id'), 'vendedor_matricula': dados_sel.get('matricula_pap'),
                                            'vendedor_nome': dados_sel.get('vendedor_nome', ''), 'cmd_queue': cmd_queue,
                                        }
                                    sess.etapa = 'venda_cpf'
                                    sess.dados_temp = dados_sel
                                    sess.save()
                                    protocolo = automacao.dados_pedido.get('protocolo', '')
                                    msg_ok = "✅ Endereço disponível!" + (f"\n📋 Protocolo: {protocolo}" if protocolo else "")
                                    elapsed = (time.monotonic() - worker_t0) if worker_t0 is not None else 0
                                    msg_ok += "\n\n⏱ _%.1fs_" % round(elapsed, 1)
                                    WhatsAppService().enviar_mensagem_texto(telefone, msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:")
                            _executar_ops_django_sync(_sync_sel_resposta)
                    elif action == 'modal_posse_voltar':
                        cep_novo = cmd.get('cep_novo', '')
                        automacao.etapa2_modal_posse_clicar_consultar_outro()
                        def _sync_modal_posse():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['cep'] = cep_novo
                            sess.etapa = 'venda_numero'
                            sess.dados_temp = dados
                            sess.save()
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            WhatsAppService().enviar_mensagem_texto(telefone, f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)")
                        _executar_ops_django_sync(_sync_modal_posse)
                    elif action == 'modal_indisponivel_voltar':
                        cep_novo = cmd.get('cep_novo', '')
                        automacao.etapa2_modal_indisponivel_clicar_voltar()
                        def _sync_modal_indisp():
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            dados = sess.dados_temp or {}
                            dados['cep'] = cep_novo
                            sess.etapa = 'venda_numero'
                            sess.dados_temp = dados
                            sess.save()
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = dados
                            WhatsAppService().enviar_mensagem_texto(telefone, f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)")
                        _executar_ops_django_sync(_sync_modal_indisp)
                    elif action == 'selecionar_complemento':
                        escolha = cmd.get('escolha', '')  # '0' ou 'sem' ou número
                        cep, numero = cmd.get('cep', ''), cmd.get('numero', '')
                        dados = _run_sync_returning(lambda: (SessaoWhatsapp.objects.get(id=sessao_id).dados_temp or {}))
                        if escolha.upper() in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
                            sucesso, msg = automacao.etapa2_selecionar_sem_complemento()
                        elif escolha.isdigit():
                            sucesso, msg = automacao.etapa2_selecionar_complemento(int(escolha))
                        else:
                            sucesso, msg = False, "Opção inválida"
                        if not sucesso:
                            def _sync_comp_err():
                                lista = dados.get('viabilidade_lista_complementos', [])
                                linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                                WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número (ex: 1)\n\n{linha}")
                            _executar_ops_django_sync(_sync_comp_err)
                        else:
                            sucesso2, msg2, extra2 = automacao.etapa2_clicar_avancar_apos_complemento(cep, numero)
                            if not sucesso2 and extra2 != "POSSE_ENCONTRADA" and extra2 != "INDISPONIVEL_TECNICO":
                                _encerrar_automacao_pap(sessao_id, dados.get('bo_usuario_id'), telefone)
                            def _sync_comp_resposta():
                                sess = SessaoWhatsapp.objects.get(id=sessao_id)
                                if not sucesso2:
                                    if extra2 == "POSSE_ENCONTRADA":
                                        sess.etapa = 'venda_posse_consultar_outro'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    elif extra2 == "INDISPONIVEL_TECNICO":
                                        sess.etapa = 'venda_indisponivel_voltar'
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                                    else:
                                        sess.etapa = 'inicial'
                                        sess.dados_temp = {}
                                        sess.save()
                                        WhatsAppService().enviar_mensagem_texto(telefone, f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente.")
                                else:
                                    dados_comp = {**dados, 'pap_replay_complemento_escolha': (escolha or '').strip()}
                                    with _automacoes_lock:
                                        _automacoes_pap_ativas[sessao_id] = {
                                            'automacao': automacao, 'phase': 'venda',
                                            'dados': dados_comp, 'bo_usuario_id': dados_comp.get('bo_usuario_id'), 'telefone': telefone,
                                            'vendedor_id': dados_comp.get('vendedor_id'), 'vendedor_matricula': dados_comp.get('matricula_pap'),
                                            'vendedor_nome': dados_comp.get('vendedor_nome', ''), 'cmd_queue': cmd_queue,
                                        }
                                    sess.etapa = 'venda_cpf'
                                    sess.dados_temp = dados_comp
                                    sess.save()
                                    protocolo = automacao.dados_pedido.get('protocolo', '')
                                    msg_ok = "✅ Endereço disponível!" + (f"\n📋 Protocolo: {protocolo}" if protocolo else "")
                                    worker_t0 = cmd.get('worker_t0')
                                    if worker_t0 is not None:
                                        import time
                                        elapsed = time.monotonic() - worker_t0
                                        msg_ok += "\n\n⏱ _%.1fs_" % round(elapsed, 1)
                                    WhatsAppService().enviar_mensagem_texto(telefone, msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:")
                            _executar_ops_django_sync(_sync_comp_resposta)
                except Exception as e:
                    logger.exception(f"[PAP Worker] Erro ao processar comando: {e}")
                    retry_count = cmd.get('_retry_count', 0)
                    if retry_count < 1:
                        try:
                            cmd_retry = {**cmd, '_retry_count': retry_count + 1}
                            cmd_queue.put(cmd_retry)
                            logger.info("[PAP Worker] Repetindo comando automaticamente (tentativa %s)", retry_count + 2)
                        except Exception:
                            pass
                        else:
                            continue
                    def _sync_send_error():
                        try:
                            from crm_app.models import SessaoWhatsapp
                            sess = SessaoWhatsapp.objects.get(id=sessao_id)
                            d = dict(sess.dados_temp or {})
                            d['_ultimo_cmd_erro'] = cmd
                            sess.dados_temp = d
                            sess.etapa = 'venda_erro_retry'
                            sess.save()
                            with _automacoes_lock:
                                if sessao_id in _automacoes_pap_ativas:
                                    _automacoes_pap_ativas[sessao_id]['dados'] = d
                            err_str = str(e).lower()
                            if "timeout" in err_str or "timed out" in err_str:
                                msg_erro = (
                                    "⏱ O site está demorando para responder na etapa atual.\n\n"
                                    "Seus dados foram salvos. Digite *REPETIR* para tentar novamente ou *CANCELAR* para sair."
                                )
                            else:
                                msg_erro = (
                                    f"❌ Ocorreu um erro: {e}\n\n"
                                    "Seus dados foram salvos. Digite *REPETIR* para tentar a última etapa novamente ou *CANCELAR* para sair."
                                )
                            WhatsAppService().enviar_mensagem_texto(telefone, msg_erro)
                        except Exception as sync_err:
                            logger.warning("[PAP Worker] Erro ao salvar sessão/notificar: %s", sync_err)
                            try:
                                WhatsAppService().enviar_mensagem_texto(
                                    telefone,
                                    f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente."
                                )
                            except Exception:
                                pass
                    try:
                        _executar_ops_django_sync(_sync_send_error)
                    except Exception:
                        pass

        def consultar_viabilidade_thread(cmd_queue):
            """Executa viabilidade e, se automação ativa, entra no loop do worker (mesma thread = sem erro Playwright)."""
            import django
            from crm_app.models import SessaoWhatsapp
            django.db.close_old_connections()
            bo_id = dados.get('bo_usuario_id')
            if not bo_id:
                def _sessao_invalida():
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    WhatsAppService().enviar_mensagem_texto(
                        telefone,
                        "❌ Sessão inválida. Digite *VENDER* para iniciar novamente."
                    )
                _executar_ops_django_sync(_sessao_invalida)
                return
            try:
                bo = Usuario.objects.get(id=bo_id)
                vendedor_matricula = dados.get('matricula_pap')
                from django.conf import settings
                headless = getattr(settings, 'PAP_HEADLESS', True)
                automacao = PAPNioAutomation(
                    matricula_pap=bo.matricula_pap,
                    senha_pap=bo.senha_pap,
                    vendedor_nome=dados.get('vendedor_nome', ''),
                    headless=headless,
                    run_id=str(sessao.id),
                )
                sucesso_login, msg_login = automacao.iniciar_sessao()
                if not sucesso_login:
                    automacao._fechar_sessao()
                    def _fail_login():
                        liberar_bo(bo_id, telefone)
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        texto = f"❌ *Erro ao acessar PAP*\n\n{msg_login}\n\nDigite *VENDER* para tentar novamente."
                        WhatsAppService().enviar_mensagem_texto(telefone, texto)
                    _executar_ops_django_sync(_fail_login)
                    return
                sucesso_novo, msg_novo = automacao.iniciar_novo_pedido(vendedor_matricula)
                if not sucesso_novo:
                    automacao._fechar_sessao()
                    def _fail_pedido():
                        liberar_bo(bo_id, telefone)
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        texto = f"❌ *Erro ao iniciar pedido*\n\n{msg_novo}\n\nDigite *VENDER* para tentar novamente."
                        WhatsAppService().enviar_mensagem_texto(telefone, texto)
                    _executar_ops_django_sync(_fail_pedido)
                    return
                sucesso, msg, extra = automacao.etapa2_viabilidade(
                    dados.get('cep', ''),
                    dados.get('numero', ''),
                    referencia,
                )
                # Códigos especiais primeiro: viabilidade só está concluída quando não há escolha pendente
                if isinstance(extra, dict) and extra.get('_codigo') == 'MULTIPLOS_ENDERECOS':
                    lista = extra.get('lista', [])
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_endereco', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': cmd_queue}
                    sessao.etapa = 'venda_selecionar_endereco'
                    sessao.dados_temp = {**dados, 'viabilidade_lista_enderecos': lista}
                    linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                    msg_multi = f"📋 *Múltiplos endereços encontrados:*\n\n{linha}\n\nDigite o *número* do endereço desejado (ex: 1, 2):"

                    def _multi_enderecos():
                        sessao.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, msg_multi)
                    _executar_ops_django_sync(_multi_enderecos)
                    _pap_worker_loop(cmd_queue, sessao.id, telefone, bo_id)
                elif isinstance(extra, dict) and extra.get('_codigo') == 'COMPLEMENTOS':
                    lista = extra.get('lista', [])
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_complemento', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': cmd_queue}
                    sessao.etapa = 'venda_selecionar_complemento'
                    sessao.dados_temp = {**dados, 'viabilidade_lista_complementos': lista}
                    linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                    msg_comp = f"📋 *Complementos encontrados:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO* se não tiver complemento, ou o *número* do complemento (ex: 1, 2, 3):"

                    def _complementos():
                        sessao.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, msg_comp)
                    _executar_ops_django_sync(_complementos)
                    _pap_worker_loop(cmd_queue, sessao.id, telefone, bo_id)
                elif extra == "POSSE_ENCONTRADA":
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_posse', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': cmd_queue}
                    sessao.etapa = 'venda_posse_consultar_outro'
                    sessao.dados_temp = dados
                    msg_posse = msg + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."

                    def _posse():
                        sessao.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, msg_posse)
                    _executar_ops_django_sync(_posse)
                    _pap_worker_loop(cmd_queue, sessao.id, telefone, bo_id)
                elif extra == "INDISPONIVEL_TECNICO":
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_indisponivel', 'bo_usuario_id': bo_id, 'telefone': telefone, 'cmd_queue': cmd_queue}
                    sessao.etapa = 'venda_indisponivel_voltar'
                    sessao.dados_temp = dados
                    msg_indisp = msg + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."

                    def _indisponivel():
                        sessao.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, msg_indisp)
                    _executar_ops_django_sync(_indisponivel)
                    _pap_worker_loop(cmd_queue, sessao.id, telefone, bo_id)
                elif sucesso:
                    # Viabilidade realmente concluída (endereço único ou já escolhido)
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {
                            'automacao': automacao, 'phase': 'venda',
                            'dados': dados, 'bo_usuario_id': bo_id, 'telefone': telefone,
                            'vendedor_id': dados.get('vendedor_id'), 'vendedor_matricula': dados.get('matricula_pap'),
                            'vendedor_nome': dados.get('vendedor_nome', ''),
                            'cmd_queue': cmd_queue,
                        }
                    protocolo = automacao.dados_pedido.get('protocolo', '')
                    msg_viab = "✅ Endereço disponível para instalação!"
                    if protocolo:
                        msg_viab += f"\n📋 Protocolo: {protocolo}"
                    msg_viab += "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"

                    def _ok_viabilidade():
                        sessao.etapa = 'venda_cpf'
                        sessao.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, msg_viab)
                    _executar_ops_django_sync(_ok_viabilidade)
                    _pap_worker_loop(cmd_queue, sessao.id, telefone, bo_id)
                else:
                    automacao._fechar_sessao()
                    texto = f"❌ Endereço indisponível. Motivo: {msg}\n\nDigite *VENDER* para tentar novamente."

                    def _indisp_fim():
                        liberar_bo(bo_id, telefone)
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        WhatsAppService().enviar_mensagem_texto(telefone, texto)
                    _executar_ops_django_sync(_indisp_fim)
            except Exception as e:
                err_msg = f"❌ Erro ao consultar viabilidade: {e}\n\nDigite *VENDER* para tentar novamente."
                def _except_handler():
                    liberar_bo(bo_id, telefone)
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    WhatsAppService().enviar_mensagem_texto(telefone, err_msg)
                _executar_ops_django_sync(_except_handler)

        # Fila de comandos para o worker (evita "cannot switch to a different thread")
        cmd_queue = queue.Queue()

        def _run_viabilidade_e_worker():
            consultar_viabilidade_thread(cmd_queue)

        resposta = "⏳ Consultando viabilidade do endereço... Aguarde alguns instantes. Você receberá a resposta em seguida."
        thread = threading.Thread(target=_run_viabilidade_e_worker)
        thread.daemon = True
        thread.start()
        return resposta
    
    # --- ETAPAS: Viabilidade (múltiplos endereços, complementos, posse, indisponível) ---
    elif etapa == 'venda_selecionar_endereco':
        return _processar_viabilidade_selecionar_endereco(telefone, sessao, dados, mensagem_limpa, mensagem.strip(), webhook_t0=webhook_t0)
    elif etapa == 'venda_selecionar_complemento':
        return _processar_viabilidade_selecionar_complemento(telefone, sessao, dados, mensagem_limpa, mensagem.strip(), webhook_t0=webhook_t0)
    elif etapa == 'venda_posse_consultar_outro':
        return _processar_viabilidade_posse(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_indisponivel_voltar':
        return _processar_viabilidade_indisponivel(telefone, sessao, dados, mensagem_limpa)
    
    # --- ETAPAS: Correção de crédito (como no terminal) ---
    elif etapa == 'venda_corrigir_celular':
        return _processar_correcao_credito(telefone, sessao, dados, mensagem_limpa, 'celular')
    elif etapa == 'venda_corrigir_email':
        return _processar_correcao_credito(telefone, sessao, dados, mensagem_limpa, 'email')
    elif etapa == 'venda_corrigir_cpf':
        return _processar_correcao_credito(telefone, sessao, dados, mensagem_limpa, 'cpf')
    
    # --- ETAPA: CPF ---
    elif etapa == 'venda_cpf':
        cpf_limpo = limpar_texto_cep_cpf(mensagem)
        if not cpf_limpo or len(cpf_limpo) != 11:
            return "❌ CPF inválido. Digite o CPF completo (11 dígitos):"
        
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({'action': 'etapa3', 'cpf': cpf_limpo})
            return "⏳ Consultando cadastro do cliente... Aguarde alguns instantes. Você receberá a resposta em seguida."
        # Fallback se não houver fila (sessão antiga)
        automacao = ctx['automacao']
        sucesso, msg, _ = automacao.etapa3_cadastro_cliente(cpf_limpo)
        if not sucesso:
            if msg == "PAP_ERRO_PORTAL_NIO":
                _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
            return f"❌ Cadastro: {msg}\n\nDigite outro CPF ou *CANCELAR*."
        dados['cpf_cliente'] = cpf_limpo
        sessao.dados_temp = dados
        sessao.etapa = 'venda_celular'
        sessao.save()
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
            funil_registrar_evento_sessao(sessao, 'venda_cpf', {'cpf_cliente': cpf_limpo})
        except Exception:
            pass
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        return f"✅ {msg}\n\n📱 *ETAPA 3: CONTATO*\n\nDigite o *celular principal* do cliente (com DDD):"
    
    # --- ETAPA: Celular ---
    elif etapa == 'venda_celular':
        celular_limpo = limpar_texto_cep_cpf(mensagem)
        if not celular_limpo or len(celular_limpo) < 10:
            return "❌ Celular inválido. Digite o celular com DDD (10 ou 11 dígitos):"
        cel_dig = _normalizar_celular_digitos(celular_limpo)
        rejeitados = dados.get('celulares_rejeitados') or []
        if cel_dig and cel_dig in rejeitados:
            return "⚠️ Este número já foi recusado pelo sistema. Digite outro celular principal (com DDD):"
        dados['celular'] = celular_limpo
        sessao.dados_temp = dados
        sessao.etapa = 'venda_celular_sec'
        sessao.save()
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
            funil_registrar_evento_sessao(sessao, 'venda_celular', {'celular': celular_limpo})
        except Exception:
            pass
        return (
            f"✅ Celular: *({celular_limpo[:2]}) {celular_limpo[2:7]}-{celular_limpo[7:]}*\n\n"
            f"📱 Digite o *celular secundário* do cliente (com DDD):"
        )
    
    # --- ETAPA: Celular secundário (obrigatório) ---
    elif etapa == 'venda_celular_sec':
        celular_sec = limpar_texto_cep_cpf(mensagem)
        if not celular_sec or len(celular_sec) < 10:
            return "❌ Celular inválido. Digite o celular secundário com DDD (10 ou 11 dígitos):"
        sec_dig = _normalizar_celular_digitos(celular_sec)
        principal_dig = _normalizar_celular_digitos(dados.get('celular', ''))
        if sec_dig == principal_dig:
            return "⚠️ O celular secundário não pode ser igual ao principal. Digite outro número:"
        rejeitados = dados.get('celulares_rejeitados') or []
        if sec_dig and sec_dig in rejeitados:
            return "⚠️ Este número já foi recusado pelo sistema. Digite outro celular secundário:"
        dados['celular_sec'] = celular_sec
        sessao.dados_temp = dados
        sessao.etapa = 'venda_email'
        sessao.save()
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
            funil_registrar_evento_sessao(sessao, 'venda_celular_sec', {'celular_sec': celular_sec})
        except Exception:
            pass
        return (
            f"✅ Celular secundário registrado.\n\n"
            f"📧 Digite o *e-mail* do cliente:"
        )
    
    # --- ETAPA: Email ---
    elif etapa == 'venda_email':
        email = mensagem.strip().lower()
        if '@' not in email or '.' not in email:
            return "❌ E-mail inválido. Digite um e-mail válido:"
        
        dados['email'] = email
        sessao.dados_temp = dados
        sessao.save()
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_evento_sessao
            funil_registrar_evento_sessao(sessao, 'venda_email', {'email': email})
        except Exception:
            pass
        
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _mensagem_sessao_expirada(sessao, dados, 'venda_email', {
                'action': 'etapa4', 'celular': dados.get('celular', ''), 'email': email,
                'celular_sec': dados.get('celular_sec', '') or None,
            })
        
        cmd_queue = ctx.get('cmd_queue')
        # Validar antes de enviar: não aceitar números já rejeitados pelo sistema
        rejeitados = dados.get('celulares_rejeitados') or []
        cel_dig = _normalizar_celular_digitos(dados.get('celular', ''))
        sec_dig = _normalizar_celular_digitos(dados.get('celular_sec', '') or '')
        if cel_dig and cel_dig in rejeitados:
            dados['celular'] = ''
            dados['celular_sec'] = ''
            dados['email'] = ''
            sessao.dados_temp = dados
            sessao.etapa = 'venda_celular'
            sessao.save()
            return "⚠️ Este número (principal) já foi recusado pelo sistema. Digite o *celular principal* do cliente (com DDD):"
        if sec_dig and sec_dig in rejeitados:
            dados['celular_sec'] = ''
            dados['email'] = ''
            sessao.dados_temp = dados
            sessao.etapa = 'venda_celular_sec'
            sessao.save()
            return "⚠️ Este número (secundário) já foi recusado pelo sistema. Digite outro celular secundário:"
        if cmd_queue:
            cmd_queue.put({
                'action': 'etapa4',
                'celular': dados.get('celular', ''),
                'email': email,
                'celular_sec': dados.get('celular_sec', '') or None,
            })
            return "⏳ Consultando crédito... Aguarde alguns instantes. Você receberá a resposta em seguida."
        automacao = ctx['automacao']
        celular_sec = dados.get('celular_sec', '') or None
        sucesso, msg, resultado_credito, _ = automacao.etapa4_contato(
            dados.get('celular', ''),
            email,
            celular_secundario=celular_sec
        )
        if not sucesso:
            if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                rejeitados = list(dados.get('celulares_rejeitados') or [])
                # Apenas o número que estava como principal é marcado como recusado (o secundário pode ser usado como novo principal)
                cel_principal_dig = _normalizar_celular_digitos(dados.get('celular', ''))
                if cel_principal_dig and cel_principal_dig not in rejeitados:
                    rejeitados.append(cel_principal_dig)
                dados['celulares_rejeitados'] = rejeitados
                dados['celular'] = ''
                dados['celular_sec'] = ''
                dados['email'] = ''
                sessao.dados_temp = dados
                sessao.etapa = 'venda_celular'
                sessao.save()
                with _automacoes_lock:
                    if sessao.id in _automacoes_pap_ativas:
                        _automacoes_pap_ativas[sessao.id]['dados'] = dados
                return (
                    "⚠️ O número excede repetições ou é inválido. Vamos recomeçar os dados de contato.\n\n"
                    "Digite o *celular principal* do cliente (com DDD):"
                )
            if msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                with _automacoes_lock:
                    _automacoes_pap_ativas[sessao.id] = {**ctx, 'phase': 'corrigir_credito', 'dados': dados}
                sessao.etapa = 'venda_corrigir_email'
                sessao.save()
                return "⚠️ E-mail já usado ou inválido. Digite outro e-mail:"
            if msg == "CREDITO_NEGADO":
                with _automacoes_lock:
                    _automacoes_pap_ativas[sessao.id] = {**ctx, 'phase': 'corrigir_credito', 'dados': dados}
                sessao.etapa = 'venda_corrigir_cpf'
                sessao.save()
                return "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou *CANCELAR*:"
            if msg == "PAP_ERRO_PORTAL_NIO":
                _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return "⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde."
            return f"❌ {msg}\n\nDigite *CANCELAR* para sair."
        dados.pop('celulares_rejeitados', None)
        if resultado_credito:
            dados['resultado_credito'] = resultado_credito
        try:
            from crm_app.funil_venda_wpp_service import funil_registrar_credito
            if resultado_credito:
                funil_registrar_credito(sessao, resultado_credito)
        except Exception:
            pass
        sessao.dados_temp = dados
        sessao.etapa = 'venda_forma_pagamento'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        texto_formas, _ = _texto_formas_pagamento_por_credito(dados.get('resultado_credito', ''))
        return f"✅ Crédito aprovado!\n\n{texto_formas}"
    
    # --- ETAPA: Forma de Pagamento ---
    elif etapa == 'venda_forma_pagamento':
        resultado_credito = (dados or {}).get('resultado_credito', '')
        _, formas = _texto_formas_pagamento_por_credito(resultado_credito)
        if mensagem_limpa not in formas:
            opcoes = "1, 2 ou 3" if len(formas) > 1 else "2 (Cartão de Crédito)"
            return f"❌ Opção inválida. Digite {opcoes}:"
        
        forma = formas[mensagem_limpa]
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _mensagem_sessao_expirada(sessao, dados, 'venda_forma_pagamento', {'action': 'etapa5_forma', 'forma': forma})
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({'action': 'etapa5_forma', 'forma': forma, 'worker_t0': time.monotonic()})
            return "⏳ Processando forma de pagamento... Aguarde alguns instantes."
        sucesso, msg = ctx['automacao'].etapa5_selecionar_forma_pagamento(forma)
        if not sucesso:
            return f"❌ Forma de pagamento: {msg}\n\nDigite 1, 2 ou 3:"
        dados['forma_pagamento'] = forma
        sessao.dados_temp = dados
        if forma == 'debito':
            sessao.etapa = 'venda_debito_banco'
        else:
            sessao.etapa = 'venda_plano'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        forma_nome = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito', 'debito': 'Débito em Conta'}
        if forma == 'debito':
            return (
                f"✅ Pagamento: *Débito em Conta*\n\n"
                f"🏦 Banco: 1=Itaú 2=Banrisul 3=Santander 4=BB 5=Bradesco 6=Nubank\n\n"
                f"Digite o número do banco:"
            )
        return (
            f"✅ Pagamento: *{forma_nome[forma]}*\n\n"
            f"{_texto_etapa5_planos(forma)}"
        )
    
    # --- ETAPA: Débito - Banco ---
    elif etapa == 'venda_debito_banco':
        banco_map = {'1': 'Banco Itau S/A', '2': 'Banrisul', '3': 'Banco Santander', '4': 'Banco do Brasil', '5': 'Banco Bradesco', '6': 'Nubank'}
        banco = banco_map.get(mensagem_limpa, '')
        if not banco:
            return "❌ Opção inválida. Digite 1, 2, 3, 4, 5 ou 6:"
        dados['banco'] = banco
        sessao.dados_temp = dados
        sessao.etapa = 'venda_debito_agencia'
        sessao.save()
        return f"✅ Banco: *{banco}*\n\n🏦 Digite a *agência*:"
    
    # --- ETAPA: Débito - Agência ---
    elif etapa == 'venda_debito_agencia':
        dados['agencia'] = mensagem.strip()
        sessao.dados_temp = dados
        sessao.etapa = 'venda_debito_conta'
        sessao.save()
        return "📋 Digite a *conta*:"
    
    # --- ETAPA: Débito - Conta ---
    elif etapa == 'venda_debito_conta':
        dados['conta'] = mensagem.strip()
        sessao.dados_temp = dados
        sessao.etapa = 'venda_debito_digito'
        sessao.save()
        return "🔢 Digite o *dígito*:"
    
    # --- ETAPA: Débito - Dígito ---
    elif etapa == 'venda_debito_digito':
        dados['digito'] = mensagem.strip()
        sessao.dados_temp = dados
        sessao.save()
        
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(sessao, dados, 'venda_debito_digito', {
                'action': 'etapa5_debito',
                'banco': dados.get('banco', ''),
                'agencia': dados.get('agencia', ''),
                'conta': dados.get('conta', ''),
                'digito': dados.get('digito', ''),
            })
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({
                'action': 'etapa5_debito',
                'banco': dados.get('banco', ''),
                'agencia': dados.get('agencia', ''),
                'conta': dados.get('conta', ''),
                'digito': dados.get('digito', ''),
            })
            return "⏳ Processando débito... Aguarde alguns instantes."
        
        sucesso, msg = ctx['automacao'].etapa5_preencher_debito(
            dados.get('banco', ''),
            dados.get('agencia', ''),
            dados.get('conta', ''),
            dados.get('digito', ''),
        )
        if not sucesso:
            return f"❌ Débito: {msg}\n\nDigite novamente o dígito:"
        
        sessao.etapa = 'venda_plano'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        
        return (
            f"✅ Débito preenchido!\n\n"
            f"{_texto_etapa5_planos('debito')}"
        )
    
    # --- ETAPA: Plano ---
    elif etapa == 'venda_plano':
        planos = {'1': '1giga', '2': '700mega', '3': '500mega'}
        if mensagem_limpa not in planos:
            return "❌ Opção inválida. Digite 1, 2 ou 3:"
        
        plano = planos[mensagem_limpa]
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(sessao, dados, 'venda_plano', {'action': 'etapa5_plano', 'plano': plano})
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({'action': 'etapa5_plano', 'plano': plano})
            return "⏳ Processando plano... Aguarde alguns instantes."
        
        sucesso, msg = ctx['automacao'].etapa5_selecionar_plano_com_validacao(plano)
        if not sucesso:
            return f"❌ Plano: {msg}\n\nDigite 1, 2 ou 3:"
        
        dados['plano'] = plano
        sessao.dados_temp = dados
        sessao.etapa = 'venda_fixo'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        
        forma = (dados.get('forma_pagamento') or '').strip().lower()
        if forma == 'cartao':
            plano_nome = {
                '1giga': 'Nio Fibra Ultra 1 Giga - R$ 150,00/mês',
                '700mega': 'Nio Fibra Super 700 Mega - R$ 120,00/mês',
                '500mega': 'Nio Fibra Essencial 500 Mega - R$ 90,00/mês'
            }
        else:
            plano_nome = {
                '1giga': 'Nio Fibra Ultra 1 Giga - R$ 160,00/mês',
                '700mega': 'Nio Fibra Super 700 Mega - R$ 130,00/mês',
                '500mega': 'Nio Fibra Essencial 500 Mega - R$ 100,00/mês'
            }
        return (
            f"✅ Plano: *{plano_nome[plano]}*\n\n"
            f"📞 Tem *Fixo* (R$ 30/mês)?\n\n"
            f"1️⃣ Sim\n"
            f"2️⃣ Não\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Fixo ---
    elif etapa == 'venda_fixo':
        if mensagem_limpa not in ('1', '2'):
            return "❌ Opção inválida. Digite 1 (Sim) ou 2 (Não):"
        tem_fixo = mensagem_limpa == '1'
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(sessao, dados, 'venda_fixo', {'action': 'etapa5_fixo', 'tem_fixo': tem_fixo})
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({'action': 'etapa5_fixo', 'tem_fixo': tem_fixo})
            return "⏳ Processando... Aguarde alguns instantes."
        
        sucesso, msg = ctx['automacao'].etapa5_selecionar_fixo(tem_fixo)
        if not sucesso:
            return f"❌ Fixo: {msg}\n\nDigite 1 ou 2:"
        
        dados['tem_fixo'] = tem_fixo
        sessao.dados_temp = dados
        if tem_fixo:
            sessao.etapa = 'venda_fixo_portabilidade'
        else:
            sessao.etapa = 'venda_streaming'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        
        if tem_fixo:
            return (
                "✅ Fixo selecionado no PAP!\n\n"
                "📞 *Portabilidade do fixo*\n\n"
                "O cliente deseja *portar* o número fixo de outra operadora?\n\n"
                "1️⃣ Sim\n"
                "2️⃣ Não\n\n"
                "Digite o número:"
            )
        return (
            f"✅ Fixo: Não\n\n"
            f"📺 Tem *Streaming*?\n\n"
            f"1️⃣ Sim\n"
            f"2️⃣ Não\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Fixo — portabilidade (após escolher Fixo = Sim) ---
    elif etapa == 'venda_fixo_portabilidade':
        if mensagem_limpa not in ('1', '2'):
            return "❌ Opção inválida. Digite 1 (Sim) ou 2 (Não):"
        quer = mensagem_limpa == '1'
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(
                sessao,
                dados,
                'venda_fixo_portabilidade',
                {
                    'action': 'etapa5_fixo_portabilidade',
                    'quer_portabilidade': quer,
                    'numero_port': '',
                    'operadora_texto': '',
                },
            )
        cmd_queue = ctx.get('cmd_queue')
        if not quer:
            if cmd_queue:
                cmd_queue.put({
                    'action': 'etapa5_fixo_portabilidade',
                    'quer_portabilidade': False,
                    'numero_port': '',
                    'operadora_texto': '',
                })
                return "⏳ Salvando fixo no PAP... Aguarde alguns instantes."
            sucesso, msg = ctx['automacao'].etapa5_fixo_finalizar_portabilidade(False, '', '')
            if not sucesso:
                return f"❌ Portabilidade/Salvar fixo: {msg}\n\nDigite 1 (com portabilidade) ou 2 (sem):"
            dados['fixo_portabilidade'] = False
            sessao.dados_temp = dados
            sessao.etapa = 'venda_streaming'
            sessao.save()
            with _automacoes_lock:
                if sessao.id in _automacoes_pap_ativas:
                    _automacoes_pap_ativas[sessao.id]['dados'] = dados
            return (
                "✅ Fixo registrado (sem portabilidade)!\n\n"
                "📺 Tem *Streaming*?\n\n"
                "1️⃣ Sim\n"
                "2️⃣ Não\n\n"
                "Digite o número da opção:"
            )
        sessao.dados_temp = dados
        sessao.etapa = 'venda_fixo_portabilidade_numero'
        sessao.save()
        return (
            "📞 Digite o *número do fixo com DDD* que será portado "
            "(somente números, ex.: 3133334444):"
        )
    
    elif etapa == 'venda_fixo_portabilidade_numero':
        digitos = re.sub(r'\D', '', mensagem.strip())
        if len(digitos) < 10 or len(digitos) > 13:
            return "❌ Número inválido. Informe DDD + número (10 a 13 dígitos):"
        dados['fixo_portabilidade_numero'] = digitos
        sessao.dados_temp = dados
        sessao.etapa = 'venda_fixo_portabilidade_operadora'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        return (
            "🏢 Digite o nome da *operadora de origem* do fixo "
            "(ex.: Vivo, Claro, Tim, OI FIXO — como no cadastro do PAP):"
        )
    
    elif etapa == 'venda_fixo_portabilidade_operadora':
        operadora_txt = (mensagem or '').strip()
        if len(operadora_txt) < 2:
            return "❌ Nome muito curto. Digite a operadora (ex.: Vivo, Claro):"
        numero = dados.get('fixo_portabilidade_numero') or ''
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(
                sessao,
                dados,
                'venda_fixo_portabilidade_operadora',
                {
                    'action': 'etapa5_fixo_portabilidade',
                    'quer_portabilidade': True,
                    'numero_port': numero,
                    'operadora_texto': operadora_txt,
                },
            )
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({
                'action': 'etapa5_fixo_portabilidade',
                'quer_portabilidade': True,
                'numero_port': numero,
                'operadora_texto': operadora_txt,
            })
            return "⏳ Enviando portabilidade ao PAP... Aguarde alguns instantes."
        sucesso, msg = ctx['automacao'].etapa5_fixo_finalizar_portabilidade(True, numero, operadora_txt)
        if not sucesso:
            return f"❌ Portabilidade: {msg}\n\nDigite novamente o nome da operadora:"
        dados['fixo_portabilidade'] = True
        dados['fixo_portabilidade_operadora'] = operadora_txt
        sessao.dados_temp = dados
        sessao.etapa = 'venda_streaming'
        sessao.save()
        with _automacoes_lock:
            if sessao.id in _automacoes_pap_ativas:
                _automacoes_pap_ativas[sessao.id]['dados'] = dados
        return (
            "✅ Fixo e portabilidade registrados!\n\n"
            "📺 Tem *Streaming*?\n\n"
            "1️⃣ Sim\n"
            "2️⃣ Não\n\n"
            "Digite o número da opção:"
        )
    
    # --- ETAPA: Aguardando confirmação (SIM) do cliente ---
    elif etapa == 'venda_aguardando_confirmacao':
        if mensagem_limpa in ('FORCAR_SIM', 'SIM_FORCADO', 'FORÇAR_SIM', 'FORCAR SIM'):
            return _forcar_sim_confirmacao_cliente_pap(sessao, telefone)
        if mensagem_limpa == 'CONSULTAR':
            chave_vendedor = _chave_telefone(telefone)
            with _pending_lock:
                chave_cliente = _pending_by_vendedor.get(chave_vendedor)
                pend = _pending_client_confirm.get(chave_cliente) if chave_cliente else None
            if pend and pend.get('consultar_queue') is not None:
                try:
                    pend['consultar_queue'].put_nowait(1)
                except Exception:
                    pass
                return "⏳ Consultando SIM e biometria no sistema... Você receberá a resposta em seguida."
            from crm_app.models import PapConfirmacaoCliente
            try:
                sessao.refresh_from_db()
            except Exception:
                pass
            # Só considerar "Confirmado" se existir registro desta SESSÃO E do CELULAR do cliente da venda
            # (evita falso positivo quando outro número ou sessão foi marcado por engano)
            dados_temp = sessao.dados_temp or {}
            celular = dados_temp.get('celular') or dados_temp.get('celular_principal') or ''
            chaves_cel = list(dict.fromkeys(
                [_chave_telefone(celular)] + (_chaves_telefone_variantes(celular) or [])
            ))
            chaves_cel = [c for c in chaves_cel if c]
            if chaves_cel:
                confirmado = PapConfirmacaoCliente.objects.filter(
                    sessao_id=sessao.id, confirmado=True, celular_cliente__in=chaves_cel
                ).exists()
            else:
                confirmado = PapConfirmacaoCliente.objects.filter(
                    sessao_id=sessao.id, confirmado=True
                ).exists()
            logger.info(
                "[VENDA PAP] CONSULTAR: sessao_id=%s, confirmado=%s (chaves_cel=%s)",
                sessao.id, confirmado, chaves_cel[:5] if chaves_cel else [],
            )
            if not confirmado and chaves_cel:
                # Fallback legado: apenas por sessão (não deveria ser necessário com a regra acima)
                confirmado = PapConfirmacaoCliente.objects.filter(
                    celular_cliente__in=chaves_cel, confirmado=True, sessao_id=sessao.id
                ).exists()
                if confirmado:
                    logger.info("[VENDA PAP] CONSULTAR fallback: confirmado=True por celular_cliente (sessao_id=%s)", sessao.id)
            status_sim = "✅ Confirmado" if confirmado else "⏳ Aguardando"
            status_bio = "Será verificada após o cliente confirmar (SIM)." if not confirmado else "Em andamento no sistema (após confirmação do cliente)."
            return (
                "📋 *Consulta: SIM do cliente e Biometria*\n\n"
                f"Cliente (SIM): {status_sim}\n"
                f"Biometria: {status_bio}\n\n"
                "Digite *CONSULTAR* quando quiser validar os dois novamente."
            )
        _hint_forcar = ""
        if getattr(settings, "PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE", False):
            _hint_forcar = "\n\n_Homologação: digite *FORCAR_SIM* para simular o SIM do cliente._"
        return (
            "⏳ Aguardando confirmação (*SIM*) do cliente.\n\n"
            "Digite *CONSULTAR* a qualquer momento para ver o status do SIM do cliente e da biometria."
            + _hint_forcar
        )
    
    # --- ETAPA: Streaming ---
    elif etapa == 'venda_streaming':
        if mensagem_limpa not in ('1', '2'):
            return "❌ Opção inválida. Digite 1 (Sim) ou 2 (Não):"
        tem_stream = mensagem_limpa == '1'
        dados['tem_streaming'] = tem_stream
        sessao.dados_temp = dados
        sessao.save()
        
        if tem_stream:
            sessao.etapa = 'venda_streaming_opcoes'
            sessao.save()
            return (
                "✅ Streaming: Sim\n\n"
                "Escolha a opção de Streaming:\n\n"
                "1️⃣ HBO + Globoplay Premium\n"
                "2️⃣ HBO + Globoplay Básico\n"
                "3️⃣ Globoplay Básico\n"
                "4️⃣ Globoplay Premium\n"
                "5️⃣ HBO Max\n\n"
                "Digite o número da opção:"
            )
        
        # Streaming: Não - executar no site e ir direto para etapa6 (igual ao teste)
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(sessao, dados, 'venda_streaming', {
                'action': 'etapa5_streaming_avancar',
                'tem_streaming': False,
                'streaming_opcoes': '',
                'plano': dados.get('plano', '500mega'),
            })
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({
                'action': 'etapa5_streaming_avancar',
                'tem_streaming': False,
                'streaming_opcoes': '',
                'plano': dados.get('plano', '500mega'),
            })
            sessao.etapa = 'venda_aguardando_confirmacao'
            sessao.save()
            return "⏳ Processando e enviando resumo... Aguarde alguns instantes."
        
        automacao = ctx['automacao']
        plano = dados.get('plano', '500mega')
        sucesso, msg = automacao.etapa5_selecionar_streaming(False, '', plano)
        if not sucesso:
            return f"❌ Streaming: {msg}\n\nDigite 1 ou 2:"
        sucesso, msg = automacao.etapa5_clicar_avancar()
        if not sucesso:
            _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return f"❌ Erro ao avançar: {msg}\n\nDigite *VENDER* para tentar novamente."
        
        from crm_app.whatsapp_service import WhatsAppService
        from crm_app.pool_bo_pap import liberar_bo
        whatsapp = WhatsAppService()
        def enviar(m):
            try:
                whatsapp.enviar_mensagem_texto(telefone, m)
            except Exception as e:
                logger.error(f"[VENDA PAP] Erro ao enviar: {e}")
        def resetar():
            from crm_app.models import SessaoWhatsapp
            try:
                s = SessaoWhatsapp.objects.get(id=sessao.id)
                s.etapa = 'inicial'
                s.dados_temp = {}
                s.save()
            except Exception:
                pass
            liberar_bo(dados.get('bo_usuario_id'), telefone)
        
        sessao.etapa = 'venda_aguardando_confirmacao'
        sessao.save()
        threading.Thread(
            target=_executar_venda_pap_etapa6_em_diante,
            args=(
                telefone, sessao.id, dados, automacao,
                ctx.get('vendedor_matricula') or dados.get('matricula_pap'),
                ctx.get('vendedor_id') or dados.get('vendedor_id'),
                ctx.get('vendedor_nome') or dados.get('vendedor_nome', ''),
                dados.get('bo_usuario_id'),
                enviar, resetar,
            ),
            daemon=True,
        ).start()
        return "⏳ Enviando resumo ao cliente e aguardando confirmação... Aguarde."
    
    # --- ETAPA: Streaming opções ---
    elif etapa == 'venda_streaming_opcoes':
        st_map = {'1': 'hbomax,globoplay_premium', '2': 'hbomax,globoplay_basico', '3': 'globoplay_basico', '4': 'globoplay_premium', '5': 'hbomax'}
        streaming_opcoes = st_map.get(mensagem_limpa, '')
        if not streaming_opcoes:
            return "❌ Opção inválida. Digite 1, 2, 3, 4 ou 5:"
        dados['streaming_opcoes'] = streaming_opcoes
        sessao.dados_temp = dados
        sessao.save()
        
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            return _marcar_sessao_erro_retry(sessao, dados, 'venda_streaming_opcoes', {
                'action': 'etapa5_streaming_avancar',
                'tem_streaming': True,
                'streaming_opcoes': streaming_opcoes,
                'plano': dados.get('plano', '500mega'),
            })
        
        cmd_queue = ctx.get('cmd_queue')
        if cmd_queue:
            cmd_queue.put({
                'action': 'etapa5_streaming_avancar',
                'tem_streaming': True,
                'streaming_opcoes': streaming_opcoes,
                'plano': dados.get('plano', '500mega'),
            })
            sessao.etapa = 'venda_aguardando_confirmacao'
            sessao.save()
            return "⏳ Processando e enviando resumo... Aguarde alguns instantes."
        
        automacao = ctx['automacao']
        plano = dados.get('plano', '500mega')
        sucesso, msg = automacao.etapa5_selecionar_streaming(True, streaming_opcoes, plano)
        if not sucesso:
            return f"❌ Streaming: {msg}\n\nDigite 1, 2, 3, 4 ou 5:"
        sucesso, msg = automacao.etapa5_clicar_avancar()
        if not sucesso:
            _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return f"❌ Erro ao avançar: {msg}\n\nDigite *VENDER* para tentar novamente."
        
        from crm_app.whatsapp_service import WhatsAppService
        from crm_app.pool_bo_pap import liberar_bo
        whatsapp = WhatsAppService()
        def enviar(m):
            try:
                whatsapp.enviar_mensagem_texto(telefone, m)
            except Exception as e:
                logger.error(f"[VENDA PAP] Erro ao enviar: {e}")
        def resetar():
            from crm_app.models import SessaoWhatsapp
            try:
                s = SessaoWhatsapp.objects.get(id=sessao.id)
                s.etapa = 'inicial'
                s.dados_temp = {}
                s.save()
            except Exception:
                pass
            liberar_bo(dados.get('bo_usuario_id'), telefone)
        
        sessao.etapa = 'venda_aguardando_confirmacao'
        sessao.save()
        threading.Thread(
            target=_executar_venda_pap_etapa6_em_diante,
            args=(
                telefone, sessao.id, dados, automacao,
                ctx.get('vendedor_matricula') or dados.get('matricula_pap'),
                ctx.get('vendedor_id') or dados.get('vendedor_id'),
                ctx.get('vendedor_nome') or dados.get('vendedor_nome', ''),
                dados.get('bo_usuario_id'),
                enviar, resetar,
            ),
            daemon=True,
        ).start()
        return "⏳ Enviando resumo ao cliente e aguardando confirmação... Aguarde."
    
    # --- ETAPA: Confirmar Venda ---
    elif etapa == 'venda_confirmar':
        if mensagem_limpa != 'CONFIRMAR':
            if mensagem_limpa == 'CANCELAR':
                from crm_app.pool_bo_pap import liberar_bo
                bo_id = dados.get('bo_usuario_id')
                if bo_id:
                    liberar_bo(bo_id, telefone)
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return "❌ Venda cancelada. Digite *VENDER* para iniciar novamente."
            return "Digite *CONFIRMAR* para enviar a venda ou *CANCELAR* para desistir:"
        
        # Iniciar automação PAP
        sessao.etapa = 'venda_processando'
        sessao.save()
        
        return _executar_venda_pap(telefone, sessao, dados)
    
    # --- ETAPA: Processando (aguardando biometria) ---
    elif etapa == 'venda_aguardando_biometria':
        if mensagem_limpa in ['VERIFICAR', 'STATUS', 'CONSULTAR']:
            return _verificar_biometria_venda(telefone, sessao, dados)
        return (
            "⏳ *AGUARDANDO BIOMETRIA*\n\n"
            "O cliente precisa completar a biometria via WhatsApp.\n\n"
            "Quando o cliente completar, digite *VERIFICAR* para continuar.\n"
            "Ou digite *CANCELAR* para desistir."
        )
    
    # --- ETAPA: Aguardando usuário confirmar "Abrir O.S." (após CONSULTAR com SIM + biometria OK) ---
    elif etapa == 'venda_aguardando_abrir_os':
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if not ctx:
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
        if mensagem_limpa in ('SIM', 'S'):
            q = ctx.get('abrir_os_queue')
            if q:
                try:
                    q.put_nowait('abrir_os')
                except Exception:
                    pass
            return "⏳ Abrindo O.S. e carregando agendamento... Aguarde."
        if mensagem_limpa in ('NAO', 'NÃO', 'N'):
            q = ctx.get('abrir_os_queue')
            if q:
                try:
                    q.put_nowait('cancelar')
                except Exception:
                    pass
            with _automacoes_lock:
                _automacoes_pap_ativas.pop(sessao.id, None)
            sessao.etapa = 'venda_aguardando_confirmacao'
            sessao.save()
            return "OK. Digite *CONSULTAR* quando quiser validar SIM e biometria e abrir O.S."
        return "Responda *SIM* para abrir O.S. (ir para agendamento) ou *NÃO* para cancelar."

    # --- ETAPAS: Agendamento (fluxo passo a passo como no terminal) ---
    elif etapa == 'venda_agendamento_dia':
        return _processar_agendamento_dia(telefone, sessao, dados, mensagem_limpa, mensagem.strip())
    elif etapa == 'venda_agendamento_confirmar_data':
        return _processar_agendamento_confirmar_data(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_agendamento_periodo':
        return _processar_agendamento_periodo(telefone, sessao, dados, mensagem_limpa, mensagem.strip())
    elif etapa == 'venda_agendamento_confirmar_turno':
        return _processar_agendamento_confirmar_turno(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_agendamento_sim_agendar':
        return _processar_agendamento_sim_agendar(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_agendamento_final':
        return _processar_agendamento_final(telefone, sessao, dados, mensagem_limpa)
    
    return "❓ Etapa não reconhecida. Digite *VENDER* para iniciar novamente."


def _executar_venda_pap(telefone: str, sessao, dados: dict) -> str:
    """
    Executa a venda no sistema PAP via automação em background.
    Usa credenciais de BackOffice (pool) para login; matrícula do vendedor
    para atribuição da venda.
    """
    import threading
    from usuarios.models import Usuario
    
    sessao.etapa = 'venda_processando'
    sessao.save()
    
    vendedor_id = dados.get('vendedor_id')
    bo_usuario_id = dados.get('bo_usuario_id')
    if not bo_usuario_id:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ *ERRO*\n\nSessão inválida. Digite *VENDER* para iniciar novamente."
    try:
        vendedor = Usuario.objects.get(id=vendedor_id)
        from crm_app.controle_tts_service import obter_matricula_tt_para_novo_pedido_pap

        vendedor_matricula = obter_matricula_tt_para_novo_pedido_pap((vendedor.matricula_pap or "").strip())
        dados["matricula_tt_pap_pedido"] = vendedor_matricula
        sessao.dados_temp = dados
        sessao.save(update_fields=["dados_temp"])
        vendedor_nome = vendedor.get_full_name() or vendedor.username
        bo_usuario = Usuario.objects.get(id=bo_usuario_id)
        bo_matricula = bo_usuario.matricula_pap
        bo_senha = bo_usuario.senha_pap
    except Usuario.DoesNotExist:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ *ERRO*\n\nUsuário não encontrado."
    
    def executar_em_background():
        _executar_venda_pap_background(
            telefone,
            sessao.id,
            dados,
            vendedor_id,
            vendedor_matricula,
            vendedor_nome,
            bo_usuario_id,
            bo_matricula,
            bo_senha,
        )
    
    thread = threading.Thread(target=executar_em_background, daemon=True)
    thread.start()
    
    return (
        "⏳ *PROCESSANDO VENDA...*\n\n"
        "Estou acessando o sistema PAP Nio para registrar sua venda.\n"
        "Isso pode levar alguns segundos.\n\n"
        "Aguarde a confirmação..."
    )


def _executar_venda_pap_etapa6_em_diante(
    telefone: str, sessao_id: int, dados: dict, automacao,
    vendedor_matricula: str, vendedor_id, vendedor_nome: str, bo_usuario_id: int,
    enviar_resultado, resetar_sessao_e_liberar_bo,
):
    """Executa etapa 6 (resumo, sim, biometria) e 7 (agendamento) - usado após etapa5 ou após correção de crédito."""
    from crm_app.models import SessaoWhatsapp
    from crm_app.whatsapp_service import WhatsAppService
    
    try:
        resumo_txt = automacao.obter_resumo_pedido_para_cliente()
        celular_cliente = dados.get('celular', '') or automacao.dados_pedido.get('celular', '')
        msg_cliente = resumo_txt
        try:
            from crm_app.services.whatsapp.nio_templates import enviar_confirmacao_pedido_pap

            dados_tpl = dict(automacao.dados_pedido or {})
            dados_tpl.update({k: v for k, v in (dados or {}).items() if v})
            ok_btn, _, canal = enviar_confirmacao_pedido_pap(
                celular_cliente, dados_tpl, resumo_txt
            )
            if not ok_btn:
                WhatsAppService.para_cliente().enviar_mensagem_texto(
                    celular_cliente,
                    f"{msg_cliente}\n\nPara confirmar, responda *CORRETO* ou *SIM*.",
                )
            else:
                logger.info("[VENDA PAP] Resumo cliente canal=%s", canal)
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao enviar resumo ao cliente: {e}")
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado("❌ Erro ao enviar resumo ao cliente.\n\nDigite *VENDER* para tentar novamente.")
            return
        def _registrar_pap_e_etapa_sync():
            try:
                from crm_app.models import PapConfirmacaoCliente
                cel_norm = _chave_telefone(celular_cliente)
                # Apenas o número principal pode confirmar com SIM (secundário não é aceito)
                celulares_reg = [cel_norm] if cel_norm else []
                proto = (dados.get("protocolo") or automacao.dados_pedido.get("protocolo") or "").strip()
                for c in celulares_reg:
                    PapConfirmacaoCliente.objects.filter(celular_cliente=c, confirmado=False, sessao_id=sessao_id).delete()
                    PapConfirmacaoCliente.objects.create(
                        celular_cliente=c,
                        confirmado=False,
                        sessao_id=sessao_id,
                        protocolo_pedido=proto or None,
                    )
                SessaoWhatsapp.objects.filter(id=sessao_id).update(etapa='venda_aguardando_confirmacao')
            except Exception as e:
                logger.warning("[VENDA PAP] Falha ao registrar PapConfirmacaoCliente/etapa: %s", e)

        t_sync = threading.Thread(target=_registrar_pap_e_etapa_sync, name="pap-registro-sync")
        t_sync.start()
        t_sync.join(timeout=10)
        if t_sync.is_alive():
            logger.warning("[VENDA PAP] Timeout ao registrar PapConfirmacaoCliente/etapa em thread sync")
        celular_mask = celular_cliente
        if len(celular_mask) >= 6:
            celular_mask = f"({celular_mask[-11:-9]}) {celular_mask[-9:-4]}-{celular_mask[-4:]}" if len(celular_mask) >= 11 else celular_mask[:4] + "****"
        enviar_resultado(
            "✅ *Resumo enviado ao cliente* " + f"(cel: {celular_mask}).\n\n"
            "Aguardando confirmação (*SIM*) do cliente.\n\n"
            "Você pode digitar *CONSULTAR* a qualquer momento para ver o status do SIM e da biometria."
        )
        evt_cliente = threading.Event()
        consultar_queue = queue.Queue()
        chave_cliente = _chave_telefone(celular_cliente)
        chave_vendedor = _chave_telefone(telefone)
        pend_dict = {
            'event': evt_cliente, 'vendedor_telefone': telefone, 'automacao': automacao,
            'dados': dados, 'sessao_id': sessao_id, 'consultar_queue': consultar_queue,
            'enviar_resultado': enviar_resultado,
        }
        todas_chaves_cliente = list(dict.fromkeys([chave_cliente] + (_chaves_telefone_variantes(celular_cliente) or [])))
        pend_dict['_chaves_pending'] = todas_chaves_cliente
        with _pending_lock:
            for k in todas_chaves_cliente:
                _pending_client_confirm[k] = pend_dict
            _pending_by_vendedor[chave_vendedor] = chave_cliente
        logger.info("[VENDA PAP] Pending SIM registrado: celular_cliente=%s, chaves=%s", celular_cliente, todas_chaves_cliente)
        if getattr(settings, "DEBUG", False) and getattr(
            settings, "PAP_WHATSAPP_AUTO_SIM_CLIENTE_LOCAL", False
        ):
            try:
                _pap_marcar_confirmacao_sim_cliente_no_bd(sessao_id, dados, celular_cliente)
                try:
                    evt_cliente.set()
                except Exception:
                    pass
                try:
                    consultar_queue.put_nowait(1)
                except Exception:
                    pass
                logger.info(
                    "[VENDA PAP] Auto-confirmação SIM do cliente (DEBUG + PAP_WHATSAPP_AUTO_SIM_CLIENTE_LOCAL)"
                )
                enviar_resultado(
                    "🔧 *Modo desenvolvimento:* o *SIM* do cliente foi confirmado automaticamente no banco.\n\n"
                    "O fluxo segue como após *CONSULTAR*. Aguarde a próxima mensagem ou digite *CONSULTAR*."
                )
            except Exception as e_auto:
                logger.warning("[VENDA PAP] Auto SIM local falhou: %s", e_auto)
        deadline = time.monotonic() + 600
        abrir_os_solicitado = False
        from crm_app.services_pap_nio import PAP_NOVO_PEDIDO_URL
        iter_keepalive = 0
        while time.monotonic() < deadline and not evt_cliente.is_set():
            try:
                consultar_queue.get(timeout=30)
            except queue.Empty:
                iter_keepalive += 1
                # A cada ~5 min (10 × 30 s): valida sessão Vtal/PAP (evita travar em «Sessão finalizada»)
                if iter_keepalive % 10 == 0:
                    try:
                        exp_antes = automacao._sessao_expirada_detectada()
                        ok_s, msg_s = automacao.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
                        if exp_antes and ok_s:
                            enviar_resultado(
                                "⚠️ *Sessão do portal PAP expirou* (timeout). Reconectamos automaticamente.\n\n"
                                "Se o *pedido sumiu* da tela, digite *VENDER* para reenviar os dados ou continue no PAP."
                            )
                        elif not ok_s:
                            logger.warning("[VENDA PAP] keepalive sessão: %s", msg_s)
                    except Exception as e_ka:
                        logger.warning("[VENDA PAP] keepalive sessão: %s", e_ka)
                continue
            # CONSULTAR solicitado: clicar Consultar Biometria no PAP e enviar status (SIM + biometria)
            try:
                automacao.etapa6_consultar_biometria()
                automacao.page.wait_for_timeout(2500)
            except Exception as e:
                logger.warning("[VENDA PAP] Erro ao consultar biometria no PAP: %s", e)
            # Só considerar confirmado se o registro for do celular do cliente desta venda (evita falso positivo)
            celular_ref = (dados or {}).get('celular') or (dados or {}).get('celular_principal') or ''
            chaves_cel_consulta = list(dict.fromkeys(
                [_chave_telefone(celular_ref)] + (_chaves_telefone_variantes(celular_ref) or [])
            ))
            chaves_cel_consulta = [c for c in chaves_cel_consulta if c]
            # Consulta ao DB em thread dedicada para evitar "async context" (Django SynchronousOnlyOperation)
            def _query_confirmado():
                from crm_app.models import PapConfirmacaoCliente
                if chaves_cel_consulta:
                    return PapConfirmacaoCliente.objects.filter(
                        sessao_id=sessao_id, confirmado=True, celular_cliente__in=chaves_cel_consulta
                    ).exists()
                return PapConfirmacaoCliente.objects.filter(sessao_id=sessao_id, confirmado=True).exists()
            _result_confirmado = [None]
            def _run_query():
                try:
                    _result_confirmado[0] = _query_confirmado()
                except Exception as e:
                    logger.warning("[VENDA PAP] Erro ao consultar PapConfirmacaoCliente: %s", e)
            _t = threading.Thread(target=_run_query, name="pap-consultar-sim")
            _t.start()
            _t.join(timeout=5)
            confirmado = _result_confirmado[0] if _result_confirmado[0] is not None else False
            status_sim = "✅ Confirmado" if confirmado else "⏳ Aguardando"
            try:
                sucesso_bio, msg_bio, biometria_ok = automacao.etapa6_verificar_biometria(consultar_primeiro=False)
                status_bio = "✅ Aprovada" if biometria_ok else ("⏳ Pendente" if sucesso_bio else (f"⏳ {(msg_bio or '')[:50]}"))
            except Exception as e:
                logger.warning("[VENDA PAP] Erro ao verificar biometria: %s", e)
                status_bio = "⏳ Erro ao verificar"
            if confirmado and biometria_ok:
                enviar_resultado(
                    f"📋 *Consulta: SIM do cliente e Biometria*\n\n"
                    f"Cliente (SIM): {status_sim}\n"
                    f"Biometria: {status_bio}\n\n"
                    "✅ *Ambos aprovados no sistema.*\n\n"
                    "Deseja *abrir O.S.* (ir para agendamento)? Responda *SIM* ou *NÃO*.",
                    botoes=[
                        {"id": "pap_abrir_os_sim", "type": "REPLY", "label": "SIM"},
                        {"id": "pap_abrir_os_nao", "type": "REPLY", "label": "NÃO"},
                    ],
                )
                abrir_os_queue = queue.Queue()
                with _automacoes_lock:
                    _automacoes_pap_ativas[sessao_id] = {
                        'automacao': automacao, 'dados': dados, 'vendedor_id': vendedor_id,
                        'bo_usuario_id': bo_usuario_id, 'telefone': telefone,
                        'abrir_os_queue': abrir_os_queue,
                    }
                def _upd_abrir_os():
                    try:
                        SessaoWhatsapp.objects.filter(id=sessao_id).update(etapa='venda_aguardando_abrir_os')
                    except Exception as e:
                        logger.warning("[VENDA PAP] Falha ao atualizar etapa venda_aguardando_abrir_os: %s", e)
                _tu = threading.Thread(target=_upd_abrir_os, name="pap-etapa-abrir-os")
                _tu.start()
                _tu.join(timeout=5)
                try:
                    cmd_abrir = abrir_os_queue.get(timeout=300)
                    if cmd_abrir == 'abrir_os':
                        abrir_os_solicitado = True
                        break
                    # cancelar: usuário disse NÃO, voltar ao loop
                    with _automacoes_lock:
                        _automacoes_pap_ativas.pop(sessao_id, None)
                    def _upd_back():
                        try:
                            SessaoWhatsapp.objects.filter(id=sessao_id).update(etapa='venda_aguardando_confirmacao')
                        except Exception:
                            pass
                    threading.Thread(target=_upd_back, name="pap-etapa-back").start()
                except queue.Empty:
                    with _automacoes_lock:
                        _automacoes_pap_ativas.pop(sessao_id, None)
                    def _upd_back():
                        try:
                            SessaoWhatsapp.objects.filter(id=sessao_id).update(etapa='venda_aguardando_confirmacao')
                        except Exception:
                            pass
                    threading.Thread(target=_upd_back, name="pap-etapa-back").start()
            else:
                enviar_resultado(
                    f"📋 *Consulta: SIM do cliente e Biometria*\n\n"
                    f"Cliente (SIM): {status_sim}\n"
                    f"Biometria: {status_bio}\n\n"
                    "Digite *CONSULTAR* quando quiser validar novamente."
                )
        with _pending_lock:
            for k in pend_dict.get('_chaves_pending', [chave_cliente]):
                _pending_client_confirm.pop(k, None)
            _pending_by_vendedor.pop(chave_vendedor, None)
        if not abrir_os_solicitado and not evt_cliente.is_set():
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado("⏳ *Timeout*: Cliente não confirmou em 10 minutos.\n\nDigite *VENDER* para iniciar novamente.")
            return
        if not abrir_os_solicitado:
            while True:
                sucesso, msg, biometria_ok = automacao.etapa6_verificar_biometria()
                if biometria_ok:
                    break
                enviar_resultado(f"⏳ *BIOMETRIA PENDENTE*\n\n{msg}\n\nPeça ao cliente para realizar a biometria.\nQuando concluir, digite *BIO OK* para consultar.")
                def _upd_etapa_bio():
                    try:
                        SessaoWhatsapp.objects.filter(id=sessao_id).update(etapa='venda_aguardando_biometria')
                    except Exception as e:
                        logger.warning("[VENDA PAP] Falha ao atualizar etapa aguardando_biometria: %s", e)
                _tb = threading.Thread(target=_upd_etapa_bio, name="pap-etapa-bio")
                _tb.start()
                _tb.join(timeout=5)
                evt_bio = threading.Event()
                chave_vendedor_bio = _chave_telefone(telefone)
                with _pending_lock:
                    _pending_bio_ok[chave_vendedor_bio] = {'event': evt_bio, 'automacao': automacao, 'dados': dados}
                evt_bio.wait(timeout=600)
                with _pending_lock:
                    _pending_bio_ok.pop(chave_vendedor_bio, None)
                if not evt_bio.is_set():
                    automacao._fechar_sessao()
                    resetar_sessao_e_liberar_bo()
                    enviar_resultado("⏳ *Timeout*: Biometria.\n\nDigite *VENDER* para iniciar novamente.")
                    return
                automacao.etapa6_consultar_biometria()
                automacao.page.wait_for_timeout(2000)
            # Biometria OK: perguntar se deseja abrir O.S. (não ir direto para agendamento)
            enviar_resultado(
                "✅ *SIM do cliente e Biometria aprovados no sistema.*\n\n"
                "Deseja *abrir O.S.* (ir para agendamento)? Responda *SIM* ou *NÃO*.",
                botoes=[
                    {"id": "pap_abrir_os_sim", "type": "REPLY", "label": "SIM"},
                    {"id": "pap_abrir_os_nao", "type": "REPLY", "label": "NÃO"},
                ],
            )
            abrir_os_queue = queue.Queue()
            with _automacoes_lock:
                _automacoes_pap_ativas[sessao_id] = {
                    'automacao': automacao, 'dados': dados, 'vendedor_id': vendedor_id,
                    'bo_usuario_id': bo_usuario_id, 'telefone': telefone,
                    'abrir_os_queue': abrir_os_queue,
                }
            def _upd_etapa_abrir_os():
                try:
                    SessaoWhatsapp.objects.filter(id=sessao_id).update(etapa='venda_aguardando_abrir_os')
                except Exception as e:
                    logger.warning("[VENDA PAP] Falha ao atualizar etapa venda_aguardando_abrir_os: %s", e)
            _t_abrir = threading.Thread(target=_upd_etapa_abrir_os, name="pap-etapa-abrir-os-2")
            _t_abrir.start()
            _t_abrir.join(timeout=5)
            try:
                cmd_abrir = abrir_os_queue.get(timeout=600)
                if cmd_abrir == 'cancelar':
                    with _automacoes_lock:
                        _automacoes_pap_ativas.pop(sessao_id, None)
                    automacao._fechar_sessao()
                    resetar_sessao_e_liberar_bo()
                    return
            except queue.Empty:
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo()
                enviar_resultado("⏳ *Timeout*: Não houve confirmação para abrir O.S.\n\nDigite *VENDER* para iniciar novamente.")
                return
        sucesso, msg = automacao.etapa7_ir_para_agendamento()
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO AGENDAMENTO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        ok, _, datas = automacao.etapa7_obter_datas_disponiveis()
        if not ok or not datas:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado("❌ Não foi possível obter datas.\n\nDigite *VENDER* para tentar novamente.")
            return
        agendamento_queue = queue.Queue()
        with _automacoes_lock:
            _automacoes_pap_ativas[sessao_id] = {
                'automacao': automacao, 'dados': dados, 'vendedor_id': vendedor_id,
                'bo_usuario_id': bo_usuario_id, 'telefone': telefone,
                'agendamento_queue': agendamento_queue,
            }
        _err_sessao = [None]
        def _atualizar_sessao_agendamento():
            try:
                s = SessaoWhatsapp.objects.get(id=sessao_id)
                s.etapa = 'venda_agendamento_dia'
                s.dados_temp = {**(s.dados_temp or {}), **dados, 'agendamento_datas': datas}
                s.save()
            except Exception as e:
                _err_sessao[0] = e
        _t = threading.Thread(target=_atualizar_sessao_agendamento, name="pap-sessao-agendamento")
        _t.start()
        _t.join(timeout=10)
        if _err_sessao[0]:
            e = _err_sessao[0]
            logger.error(f"[VENDA PAP] Erro ao atualizar sessão: {e}")
            automacao._fechar_sessao()
            with _automacoes_lock:
                _automacoes_pap_ativas.pop(sessao_id, None)
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")
            return
        enviar_resultado(f"📅 *AGENDAMENTO - Selecione o dia*\n\nDatas disponíveis: {', '.join(str(d) for d in datas)}\n\nDigite o *número do dia* (ex: 10) ou *CANCELAR*.")

        # Loop na MESMA thread que possui a automação: processa dia, período, sim_agendar, final
        AGENDAMENTO_TIMEOUT = 600
        while True:
            try:
                cmd = agendamento_queue.get(timeout=AGENDAMENTO_TIMEOUT)
            except queue.Empty:
                logger.warning("[VENDA PAP] Agendamento timeout (sem comando)")
                break
            if cmd is None or cmd.get('action') == 'STOP' or cmd.get('cmd') == 'cancelar':
                break
            if cmd.get('cmd') == 'dia':
                dia = cmd.get('dia')
                rq = cmd.get('response_queue')
                try:
                    sucesso, msg, periodos = automacao.etapa7_selecionar_data_e_obter_periodos(dia)
                    if rq:
                        rq.put((sucesso, msg, periodos))
                except Exception as e:
                    logger.exception("[VENDA PAP] etapa7_selecionar_data_e_obter_periodos: %s", e)
                    if rq:
                        rq.put((False, str(e), None))
            elif cmd.get('cmd') == 'periodo':
                idx = cmd.get('idx')
                rq = cmd.get('response_queue')
                try:
                    sucesso, msg = automacao.etapa7_selecionar_periodo(idx)
                    if rq:
                        rq.put((sucesso, msg))
                except Exception as e:
                    logger.exception("[VENDA PAP] etapa7_selecionar_periodo: %s", e)
                    if rq:
                        rq.put((False, str(e)))
            elif cmd.get('cmd') == 'sim_agendar':
                rq = cmd.get('response_queue')
                try:
                    sucesso, msg = automacao.etapa7_clicar_agendar()
                    if rq:
                        rq.put((sucesso, msg))
                except Exception as e:
                    logger.exception("[VENDA PAP] etapa7_clicar_agendar: %s", e)
                    if rq:
                        rq.put((False, str(e)))
            elif cmd.get('cmd') == 'final':
                rq = cmd.get('response_queue')
                dados_pedido = getattr(automacao, 'dados_pedido', None) or {}
                try:
                    sucesso, msg, numero_os = automacao.etapa7_modal_clicar_continuar()
                    if rq:
                        rq.put((sucesso, msg, numero_os, dados_pedido))
                except Exception as e:
                    logger.exception("[VENDA PAP] etapa7_modal_clicar_continuar: %s", e)
                    if rq:
                        rq.put((False, str(e), None, dados_pedido))
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar_sessao_e_liberar_bo(sucesso, msg)
                break

        # Se saiu do loop por timeout ou cancelar (não por 'final'), encerra
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.pop(sessao_id, None)
        if ctx:
            try:
                ctx['automacao']._fechar_sessao()
            except Exception:
                pass
            resetar_sessao_e_liberar_bo()
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro etapa6+: {e}")
        try:
            automacao._fechar_sessao()
        except Exception:
            pass
        with _automacoes_lock:
            _automacoes_pap_ativas.pop(sessao_id, None)
        resetar_sessao_e_liberar_bo()
        enviar_resultado(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")


def _executar_venda_pap_background(
    telefone: str,
    sessao_id: int,
    dados: dict,
    vendedor_id: int,
    vendedor_matricula: str,
    vendedor_nome: str,
    bo_usuario_id: int,
    bo_matricula: str,
    bo_senha: str,
):
    """
    Executa a automação PAP em background (thread separada).
    Login com credenciais BO; matrícula do vendedor para atribuição da venda.
    Libera o BO ao final (sucesso, erro ou biometria pendente).
    """
    import django
    django.setup()

    from crm_app.models import SessaoWhatsapp
    from usuarios.models import Usuario
    from crm_app.services_pap_nio import PAPNioAutomation
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.pool_bo_pap import liberar_bo

    whatsapp = WhatsAppService()

    def enviar_resultado(mensagem: str, botoes: list = None):
        """
        Envia mensagem para o cliente durante a automação em background.
        Se `botoes` vier preenchido, envia como REPLY (send-button-actions).
        """
        try:
            if botoes:
                whatsapp.enviar_mensagem_com_botoes_reply(
                    telefone,
                    mensagem,
                    botoes,
                )
            else:
                whatsapp.enviar_mensagem_texto(telefone, mensagem)
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao enviar resultado: {e}")

    bo_usuario_hist = Usuario.objects.filter(id=bo_usuario_id).first()
    _hist_fechado = {'done': False}

    def _marcar_hist(sucesso: bool, mensagem: str = ""):
        if _hist_fechado['done'] or not bo_usuario_hist:
            return
        try:
            atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=telefone,
                bo_usuario=bo_usuario_hist,
                tipo_automacao='vender',
                sucesso=sucesso,
                mensagem_resultado=mensagem,
            )
            _hist_fechado['done'] = True
        except Exception:
            pass

    def resetar_sessao_e_liberar_bo(sucesso: bool = False, mensagem: str = ""):
        """Reseta sessão e libera o BO para o pool"""
        _marcar_hist(sucesso, mensagem)
        try:
            sessao = SessaoWhatsapp.objects.get(id=sessao_id)
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao resetar sessão: {e}")
        liberar_bo(bo_usuario_id, telefone)

    try:
        logger.info(f"[VENDA PAP] Iniciando automação em background para {vendedor_nome} (BO id={bo_usuario_id})")

        from django.conf import settings
        headless = getattr(settings, 'PAP_HEADLESS', True)
        automacao = PAPNioAutomation(
            matricula_pap=bo_matricula,
            senha_pap=bo_senha,
            vendedor_nome=vendedor_nome,
            headless=headless,
            run_id=str(sessao_id),
        )
        
        # Etapa 0: Iniciar sessão
        sucesso, msg = automacao.iniciar_sessao()
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO NO LOGIN PAP*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 1: Iniciar novo pedido
        sucesso, msg = automacao.iniciar_novo_pedido(vendedor_matricula)
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO NA ETAPA 1*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 2: Viabilidade
        sucesso, msg, enderecos = automacao.etapa2_viabilidade(
            dados.get('cep', ''),
            dados.get('numero', ''),
            dados.get('referencia', '')
        )
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            if msg == "PAP_ERRO_PORTAL_NIO":
                enviar_resultado("⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde.")
            else:
                enviar_resultado(f"❌ *ERRO NA VIABILIDADE*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 3: Cadastro do cliente
        sucesso, msg, cliente = automacao.etapa3_cadastro_cliente(dados.get('cpf_cliente', ''))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            if msg == "PAP_ERRO_PORTAL_NIO":
                enviar_resultado("⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde.")
            else:
                enviar_resultado(f"❌ *ERRO NO CADASTRO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 4: Contato (com celular secundário como no terminal)
        celular_sec = dados.get('celular_sec', '') or None
        sucesso, msg, credito, _ = automacao.etapa4_contato(
            dados.get('celular', ''),
            dados.get('email', ''),
            celular_secundario=celular_sec
        )
        if not sucesso:
            if msg == "PAP_ERRO_PORTAL_NIO":
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo(False, msg)
                enviar_resultado("⚠️ O portal do PAP está com problemas no momento. Por favor, abra um chamado na *Nio* para que possamos verificar.\n\nDigite *VENDER* para tentar novamente mais tarde.")
                return
            # Manter sessão e permitir correção (como no terminal)
            etapa_correcao = None
            txt = ""
            if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                etapa_correcao = 'venda_corrigir_celular'
                txt = ("⚠️ O número excede repetições. Digite outro celular:" if msg == "TELEFONE_REJEITADO"
                       else "⚠️ Celular inválido. Digite um número válido com DDD:")
            elif msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                etapa_correcao = 'venda_corrigir_email'
                txt = ("⚠️ E-mail já usado em pedido anterior. Digite outro e-mail:" if msg == "EMAIL_REJEITADO"
                       else "⚠️ E-mail inválido. Digite um e-mail válido:")
            elif msg == "CREDITO_NEGADO":
                etapa_correcao = 'venda_corrigir_cpf'
                txt = "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou CANCELAR para sair:"
            if etapa_correcao:
                with _automacoes_lock:
                    _automacoes_pap_ativas[sessao_id] = {
                        'automacao': automacao, 'phase': 'corrigir_credito',
                        'dados': dados, 'vendedor_id': vendedor_id, 'vendedor_matricula': vendedor_matricula,
                        'vendedor_nome': vendedor_nome, 'bo_usuario_id': bo_usuario_id,
                        'telefone': telefone,
                    }
                _err_corr = [None]
                def _upd_sessao_correcao():
                    try:
                        s = SessaoWhatsapp.objects.get(id=sessao_id)
                        s.etapa = etapa_correcao
                        s.dados_temp = dados
                        s.save()
                    except Exception as e:
                        _err_corr[0] = e
                _tc = threading.Thread(target=_upd_sessao_correcao, name="pap-sessao-correcao")
                _tc.start()
                _tc.join(timeout=10)
                if _err_corr[0]:
                    e = _err_corr[0]
                    logger.error(f"[VENDA PAP] Erro ao atualizar sessão: {e}")
                    automacao._fechar_sessao()
                    resetar_sessao_e_liberar_bo(False, str(e))
                    enviar_resultado(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")
                    return
                enviar_resultado(txt)
            else:
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo(False, msg)
                enviar_resultado(f"❌ *ERRO NA ANÁLISE DE CRÉDITO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 5: Pagamento e Plano (passo a passo como no terminal)
        sucesso, msg = automacao.etapa5_selecionar_forma_pagamento(dados.get('forma_pagamento', 'boleto'))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO NA FORMA DE PAGAMENTO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        if dados.get('forma_pagamento') == 'debito':
            sucesso, msg = automacao.etapa5_preencher_debito(
                dados.get('banco', ''),
                dados.get('agencia', ''),
                dados.get('conta', ''),
                dados.get('digito', ''),
            )
            if not sucesso:
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo(False, msg)
                enviar_resultado(f"❌ *ERRO NO DÉBITO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        sucesso, msg = automacao.etapa5_selecionar_plano_com_validacao(dados.get('plano', '500mega'))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO NO PLANO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        sucesso, msg = automacao.etapa5_selecionar_fixo(dados.get('tem_fixo', False))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO NO FIXO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        plano = dados.get('plano', '500mega')
        streaming_opcoes = dados.get('streaming_opcoes') or ''
        sucesso, msg = automacao.etapa5_selecionar_streaming(
            bool(dados.get('tem_streaming', False)),
            streaming_opcoes,
            plano
        )
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO NO STREAMING*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        sucesso, msg = automacao.etapa5_clicar_avancar()
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo(False, msg)
            enviar_resultado(f"❌ *ERRO AO AVANÇAR*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        _executar_venda_pap_etapa6_em_diante(
            telefone=telefone, sessao_id=sessao_id, dados=dados, automacao=automacao,
            vendedor_matricula=vendedor_matricula, vendedor_id=vendedor_id, vendedor_nome=vendedor_nome,
            bo_usuario_id=bo_usuario_id, enviar_resultado=enviar_resultado,
            resetar_sessao_e_liberar_bo=resetar_sessao_e_liberar_bo
        )
        
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro na execução em background: {e}")
        resetar_sessao_e_liberar_bo(False, str(e))
        enviar_resultado(f"❌ *ERRO INESPERADO*\n\n{str(e)}\n\nDigite *VENDER* para tentar novamente.")


def _verificar_biometria_venda(telefone: str, sessao, dados: dict) -> str:
    """
    Verifica o status da biometria e continua a venda se aprovada.
    """
    automacao = dados.get('automacao_instancia')
    
    if not automacao:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    try:
        # Verificar biometria
        sucesso, msg, biometria_ok = automacao.etapa6_verificar_biometria()
        
        if not biometria_ok:
            return (
                f"⏳ *BIOMETRIA AINDA PENDENTE*\n\n"
                f"{msg}\n\n"
                f"Aguarde o cliente completar e digite *VERIFICAR* novamente.\n"
                f"Ou digite *CANCELAR* para desistir."
            )
        
        # Biometria OK - Abrir OS
        sucesso, msg, numero_os = automacao.etapa7_abrir_os(
            turno=dados.get('turno', 'manha')
        )
        
        automacao._fechar_sessao()
        
        if not sucesso:
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return f"❌ *ERRO AO ABRIR O.S.*\n\n{msg}"
        
        # SUCESSO! Mesclar dados da automação e cadastrar no CRM
        from usuarios.models import Usuario
        from crm_app.cadastro_venda_pap import cadastrar_venda_pap_no_crm
        vendedor = Usuario.objects.get(id=dados.get('vendedor_id'))
        dados_crm = {**dados, **automacao.dados_pedido}
        try:
            from crm_app.controle_tts_service import marcar_tt_tratado_apos_geracao_os

            mat_tt = (dados.get("matricula_tt_pap_pedido") or "").strip()
            if mat_tt and numero_os:
                marcar_tt_tratado_apos_geracao_os(mat_tt)
        except Exception as e:
            logger.warning("[VENDA PAP] Controle TT após O.S. (VERIFICAR): %s", e)
        cadastrar_venda_pap_no_crm(dados_crm, numero_os or "", vendedor=vendedor)
        
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        
        return (
            f"🎉 *VENDA CONCLUÍDA COM SUCESSO!*\n\n"
            f"📋 Número do Pedido: *{numero_os or 'N/A'}*\n\n"
            f"A venda foi registrada no CRM.\n\n"
            f"Digite *VENDER* para iniciar uma nova venda."
        )
        
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro ao verificar biometria: {e}")
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ *ERRO*\n\n{str(e)}\n\nDigite *VENDER* para iniciar novamente."


def _buscar_record_apoia_por_texto(busca_texto, sessao):
    """
    Busca no Record Apoia por tag/título/descrição/categoria.
    - 0 resultados: retorna None.
    - 1 resultado: prepara material_para_envio na sessão e retorna mensagem de envio.
    - 2+ resultados: seta etapa material_selecionar e retorna lista numerada.
    """
    if not busca_texto or len(busca_texto.strip()) < 2:
        return None
    import base64
    from django.db.models import Q
    from crm_app.models import RecordApoia

    from crm_app.record_apoia_api import record_apoia_disponivel, record_apoia_ler_bytes

    busca_texto = busca_texto.strip()
    arquivos_qs = RecordApoia.objects.filter(ativo=True).filter(
        Q(tags__icontains=busca_texto) |
        Q(titulo__icontains=busca_texto) |
        Q(descricao__icontains=busca_texto) |
        Q(categoria__icontains=busca_texto)
    ).order_by('-data_upload')[:10]

    arquivos = [a for a in arquivos_qs if record_apoia_disponivel(a)]

    if not arquivos:
        return None

    if len(arquivos) == 1:
        arquivo = arquivos[0]
        arquivo.downloads_count += 1
        arquivo.save(update_fields=['downloads_count'])
        try:
            arquivo_field = arquivo.arquivo
            if not arquivo_field or not arquivo_field.name:
                return f"❌ Arquivo \"{arquivo.titulo}\" não encontrado."
            try:
                arquivo_bytes = record_apoia_ler_bytes(arquivo)
                arquivo_b64 = base64.b64encode(arquivo_bytes).decode('utf-8')
            except (FileNotFoundError, IOError, OSError) as e:
                logger.error(f"[Webhook] Erro ao ler arquivo Record Apoia id={arquivo.id}: {e}")
                return (
                    f"❌ Arquivo \"{arquivo.titulo}\" não está disponível no servidor.\n\n"
                    "Peça ao administrador para reenviar o material no Record Apoia "
                    "(Administração → Limpar registro órfão e fazer upload novamente)."
                )

            nome_arquivo = arquivo.nome_original
            if arquivo.tipo_arquivo == 'IMAGEM':
                resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📷 {arquivo.titulo}"
                sessao.dados_temp = {
                    'material_para_envio': {
                        'tipo': 'IMAGEM',
                        'base64': arquivo_b64,
                        'nome': nome_arquivo,
                        'titulo': arquivo.titulo,
                        'descricao': arquivo.descricao or '',
                    }
                }
            else:
                tamanho_bytes = len(arquivo_bytes) if arquivo_bytes else (len(arquivo_b64) * 3 // 4)
                tamanho_mb = tamanho_bytes / (1024 * 1024)
                pdf_url = arquivo.url_externa or None
                if tamanho_mb > 5 and not pdf_url:
                    try:
                        from crm_app.cloudflare_r2_service import CloudflareR2Storage
                        from io import BytesIO
                        file_obj = BytesIO(arquivo_bytes) if arquivo_bytes else BytesIO(base64.b64decode(arquivo_b64))
                        storage = CloudflareR2Storage()
                        pdf_url = storage.upload_file_and_get_download_url(
                            file_obj, folder_name='WhatsApp_Materiais', filename=nome_arquivo
                        )
                    except Exception as e:
                        logger.warning("[Webhook] Erro R2 para material: %s", e)
                resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}"
                material_data = {
                    'tipo': 'DOCUMENTO',
                    'nome': nome_arquivo,
                    'titulo': arquivo.titulo,
                    'tipo_display': arquivo.get_tipo_arquivo_display(),
                }
                if pdf_url:
                    material_data['url'] = pdf_url
                else:
                    material_data['base64'] = arquivo_b64
                sessao.dados_temp = {'material_para_envio': material_data}

            sessao.etapa = 'inicial'
            sessao.save()
            return resposta
        except Exception as e:
            logger.exception("[Webhook] Erro ao preparar arquivo Record Apoia: %s", e)
            return f"❌ Erro ao processar arquivo: {str(e)}"

    arquivos_lista = list(arquivos)
    arquivos_ids_lista = [arq.id for arq in arquivos_lista]
    resposta_parts = [f"📚 *MATERIAIS ENCONTRADOS* para \"{busca_texto}\":\n"]
    for idx, arq in enumerate(arquivos_lista, 1):
        resposta_parts.append(f"{idx}. {arq.titulo} ({arq.get_tipo_arquivo_display()})")
        if arq.descricao:
            desc_curta = arq.descricao[:50] + "..." if len(arq.descricao) > 50 else arq.descricao
            resposta_parts.append(f"   {desc_curta}")
    resposta_parts.append(f"\n📋 Digite o *NÚMERO* do material desejado (1 a {len(arquivos_lista)}):")
    sessao.etapa = 'material_selecionar'
    sessao.dados_temp = {'busca': busca_texto, 'arquivos_ids': arquivos_ids_lista}
    sessao.save()
    return "\n".join(resposta_parts)


_CAPTION_WHATSAPP_MAX = 1024


def _truncar_caption_whatsapp(texto, max_len=_CAPTION_WHATSAPP_MAX):
    """Limita legenda ao tamanho aceito pelo WhatsApp."""
    if not texto:
        return ""
    texto = str(texto).strip()
    if len(texto) <= max_len:
        return texto
    return texto[: max_len - 1].rstrip() + "…"


def _caption_padrao_material(material_para_envio):
    """Legenda mínima quando não há texto de resposta do bot."""
    titulo = material_para_envio.get('titulo') or material_para_envio.get('nome') or 'Material'
    if material_para_envio.get('tipo') == 'IMAGEM':
        caption = f"📷 {titulo}"
    else:
        tipo_disp = material_para_envio.get('tipo_display') or 'Documento'
        caption = f"📄 {titulo}\nTipo: {tipo_disp}"
    desc = (material_para_envio.get('descricao') or '').strip()
    if desc:
        caption += f"\n{desc[:200]}"
    return _truncar_caption_whatsapp(caption)


def _enviar_material_record_apoia_whatsapp(whatsapp_service, telefone, material_para_envio, caption=None):
    """
    Envia material Record Apoia (imagem ou documento) com legenda no mesmo envio.
    Retorna True se a mídia foi enviada com sucesso.
    """
    if not material_para_envio:
        return False
    legenda = _truncar_caption_whatsapp(caption) if caption else _caption_padrao_material(material_para_envio)
    try:
        if material_para_envio.get('tipo') == 'IMAGEM':
            ok = whatsapp_service.enviar_imagem_b64(
                telefone, material_para_envio['base64'], legenda
            )
        else:
            pdf_url = material_para_envio.get('url')
            base64_data = material_para_envio.get('base64', '')
            nome = material_para_envio.get('nome') or 'documento.pdf'
            if pdf_url:
                ok = whatsapp_service.enviar_pdf_url(telefone, pdf_url, nome, caption=legenda)
            elif base64_data:
                ok = whatsapp_service.enviar_pdf_b64(telefone, base64_data, nome, caption=legenda)
            else:
                logger.error("[Webhook] Material sem url nem base64: %s", nome)
                return False
        if ok:
            logger.info(
                "[Webhook] ✅ Material enviado com legenda: %s",
                material_para_envio.get('nome'),
            )
        else:
            logger.error(
                "[Webhook] ❌ Falha ao enviar material: %s",
                material_para_envio.get('nome'),
            )
        return bool(ok)
    except Exception as e:
        logger.error("[Webhook] ❌ Erro ao enviar material com legenda: %s", e)
        return False


def processar_resposta_gc_antecipar(telefone_remetente, mensagem_texto):
    """
    Se a mensagem for do número do GC e no formato [O.S], antecipada|não antecipada|solicitado,
    registra a resposta no sistema e envia a mensagem padronizada ao vendedor.
    Aceita texto adicional após ':' ou em linhas seguintes (complemento ao vendedor).
    Retorna True se processou (e deve encerrar o webhook); False caso contrário.
    """
    if not mensagem_texto or not (mensagem_texto or "").strip():
        return False
    from crm_app.antecipar_instalacao_utils import (
        buscar_solicitacao_gc_pendente_por_os,
        mensagem_resposta_gc_para_vendedor,
        parse_mensagem_resposta_gc_antecipar,
    )
    from crm_app.models import AnteciparInstalacaoConfig
    from crm_app.whatsapp_service import WhatsAppService
    config = AnteciparInstalacaoConfig.objects.first()
    if not config or not (getattr(config, 'telefone_gc', None) or "").strip():
        return False
    gc_norm = formatar_telefone(config.telefone_gc)
    rem_norm = formatar_telefone(telefone_remetente)
    if not gc_norm or not rem_norm or gc_norm != rem_norm:
        return False
    msg = (mensagem_texto or "").strip()
    parsed = parse_mensagem_resposta_gc_antecipar(msg)
    if not parsed:
        return False
    os_digits, resposta_gc, complemento = parsed
    sol = buscar_solicitacao_gc_pendente_por_os(os_digits)
    if not sol:
        logger.info(f"[Webhook] Resposta GC: O.S {os_digits} não encontrada ou já respondida.")
        return False
    tipo_sol = getattr(sol, 'tipo_solicitacao', None) or 'antecipacao'
    comp = (complemento or '').strip()[:2000]
    msg_vendedor = mensagem_resposta_gc_para_vendedor(
        sol.ordem_servico or os_digits, resposta_gc, tipo_sol, comp
    )
    if not msg_vendedor:
        return False
    vendedor = sol.venda.vendedor if sol.venda else None
    telefone_vendedor = (getattr(vendedor, 'tel_whatsapp', None) or "").strip() if vendedor else ""
    enviado = False
    if telefone_vendedor:
        try:
            svc = WhatsAppService()
            ok, _ = svc.enviar_mensagem_texto(telefone_vendedor, msg_vendedor)
            enviado = ok
        except Exception as e:
            logger.exception("Erro ao enviar WhatsApp resposta GC ao vendedor: %s", e)
    sol.resposta_gc = resposta_gc
    sol.resposta_gc_em = timezone.now()
    sol.resposta_gc_por = None  # automático via WhatsApp
    sol.resposta_gc_complemento_vendedor = comp
    sol.save(update_fields=['resposta_gc', 'resposta_gc_em', 'resposta_gc_por', 'resposta_gc_complemento_vendedor'])
    logger.info(f"[Webhook] Resposta GC registrada: O.S {os_digits} -> {resposta_gc}; mensagem ao vendedor: {'enviada' if enviado else 'não enviada'}")
    return True


def _buscar_buttons_response_zapi(d, _depth=0):
    """Localiza resposta de botão no payload Z-API (busca recursiva)."""
    if _depth > 14 or not isinstance(d, dict):
        return None
    for key in (
        "buttonsResponseMessage",
        "buttonResponseMessage",
        "buttonActionsResponseMessage",
        "templateButtonReplyMessage",
        "nativeFlowResponseMessage",
        "interactiveResponseMessage",
        "buttonReply",
        "replyButton",
    ):
        br = d.get(key)
        if isinstance(br, dict):
            return br
    # Dict plano com campos típicos de clique em botão
    if any(d.get(k) for k in ("buttonId", "selectedButtonId", "selectedId")):
        if any(d.get(k) for k in ("message", "selectedButtonText", "text", "selectedDisplayText")):
            return d
    for v in d.values():
        if isinstance(v, dict):
            br = _buscar_buttons_response_zapi(v, _depth + 1)
            if br is not None:
                return br
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    br = _buscar_buttons_response_zapi(item, _depth + 1)
                    if br is not None:
                        return br
    return None


def _extrair_dados_botao_zapi(data) -> tuple[str, str]:
    """Retorna (buttonId, texto do botão) do payload Z-API."""
    br = _buscar_buttons_response_zapi(data)
    if not br:
        for key in ('buttonId', 'selectedButtonId', 'selectedId'):
            if data.get(key):
                br = data
                break
    if not br:
        return '', ''
    bid = (
        br.get('buttonId')
        or br.get('selectedButtonId')
        or br.get('selectedId')
        or br.get('id')
        or ''
    ).strip()
    msg = (
        br.get('message')
        or br.get('selectedButtonText')
        or br.get('selectedDisplayText')
        or br.get('text')
        or ''
    ).strip()
    return bid, msg


# IDs de botões Z-API (send-button-actions) → texto equivalente ao que o usuário digitaria
_BTN_ZAPI_ID_PARA_COMANDO = {
    "pap_confirmar_sim": "SIM",
    "pap_agenda_confirmar": "CONFIRMAR",
    "pap_agenda_alterar": "ALTERAR",
    "pap_agenda_cancelar": "CANCELAR",
    "pap_agenda_sim": "SIM",
    "pap_abrir_os_sim": "SIM",
    "pap_abrir_os_nao": "NAO",
    "pap_venda_confirmar_envio": "CONFIRMAR",
    "pap_venda_iniciar_sim": "SIM",
    "pap_venda_iniciar_cancelar": "CANCELAR",
    "cdoe_uf_MG": "MG",
    "cdoe_uf_ES": "ES",
    "cdoe_uf_RJ": "RJ",
    "cdoe_uf_SP": "SP",
    "cdoe_uf_PR": "PR",
    "cdoe_uf_SC": "SC",
    "cdoe_uf_RS": "RS",
}


def _texto_efetivo_botao_zapi(data):
    """Se o payload só trouxe botão sem texto, devolve o comando mapeado pelo buttonId."""
    br = _buscar_buttons_response_zapi(data)
    if not br:
        return ""
    bid = (
        br.get("buttonId")
        or br.get("selectedButtonId")
        or br.get("id")
        or ""
    ).strip()
    if bid in _BTN_ZAPI_ID_PARA_COMANDO:
        return _BTN_ZAPI_ID_PARA_COMANDO[bid]
    msg = (
        br.get("message")
        or br.get("selectedButtonText")
        or br.get("text")
        or ""
    ).strip()
    return msg or ""


def _extrair_texto_lista_opcoes_zapi(data) -> str:
    """Extrai seleção de option-list (cidade etc.) do webhook Z-API."""
    if not isinstance(data, dict):
        return ""

    def _from_dict(d: dict) -> str:
        if not isinstance(d, dict):
            return ""
        for key in (
            "selectedRowId",
            "selectedOptionId",
            "optionId",
            "id",
            "title",
            "description",
            "message",
            "text",
        ):
            val = d.get(key)
            if val is not None and str(val).strip():
                # Prefere id se for cdoe_cid_N; senão título/texto
                pass
        oid = (
            d.get("selectedRowId")
            or d.get("selectedOptionId")
            or d.get("optionId")
            or d.get("id")
            or ""
        )
        title = (
            d.get("title")
            or d.get("description")
            or d.get("message")
            or d.get("text")
            or ""
        )
        oid_s = str(oid).strip()
        title_s = str(title).strip()
        if oid_s.startswith("cdoe_cid_"):
            return oid_s
        return title_s or oid_s

    for key in (
        "listResponseMessage",
        "listResponse",
        "optionListResponse",
        "selectedOption",
    ):
        block = data.get(key)
        if isinstance(block, dict):
            txt = _from_dict(block)
            if txt:
                return txt
        # nested singleSelectReply
        if isinstance(block, dict):
            nested = block.get("singleSelectReply") or block.get("selectedRow")
            if isinstance(nested, dict):
                txt = _from_dict(nested)
                if txt:
                    return txt

    # busca rasa em message
    msg = data.get("message")
    if isinstance(msg, dict):
        for key in ("listResponseMessage", "listResponse", "interactiveResponseMessage"):
            block = msg.get(key)
            if isinstance(block, dict):
                txt = _from_dict(block.get("singleSelectReply") or block)
                if txt:
                    return txt
    return ""


def _aplicar_resposta_botao_zapi(data, mensagem_texto):
    """
    Clique em botão (ex.: send-button-actions) vem como buttonsResponseMessage;
    mapeia ids conhecidos para o comando textual esperado pelo fluxo.
    """
    lista_txt = _extrair_texto_lista_opcoes_zapi(data)
    if lista_txt and not (mensagem_texto or "").strip():
        mensagem_texto = lista_txt

    br = _buscar_buttons_response_zapi(data)
    if not br:
        return mensagem_texto
    bid = (
        br.get("buttonId")
        or br.get("selectedButtonId")
        or br.get("id")
        or ""
    ).strip()
    msg = (
        br.get("message")
        or br.get("selectedButtonText")
        or br.get("text")
        or ""
    ).strip()
    if bid in _BTN_ZAPI_ID_PARA_COMANDO:
        padrao = _BTN_ZAPI_ID_PARA_COMANDO[bid]
        return (msg or padrao).strip()
    if bid.startswith("cdoe_uf_"):
        return bid.replace("cdoe_uf_", "") or msg
    if bid.startswith("cdoe_cid_"):
        return bid
    if bid.startswith('pa_') and msg:
        return msg.strip()
    if bid.startswith('pa_'):
        from crm_app.esteira_posso_antecipar_service import parse_button_id_posso_antecipar
        pa = parse_button_id_posso_antecipar(bid)
        if pa:
            return pa['resposta_completa']
    if bid.startswith('pr_'):
        from crm_app.esteira_posso_reagendar_service import parse_button_id_posso_reagendar
        pr = parse_button_id_posso_reagendar(bid)
        if pr:
            if pr.get('acao') == 'sim':
                return 'Sim'
            if pr.get('acao') == 'nao':
                return 'Não'
            if pr.get('acao') == 'turno':
                return 'Manhã' if pr.get('turno') == 'MANHA' else 'Tarde'
            if pr.get('acao') == 'data' and pr.get('data'):
                d = pr['data']
                return d.strftime('%d/%m/%Y')
    if bid.startswith('la_'):
        from crm_app.esteira_lista_agendamento_vendedor_service import parse_button_id_lista_agendamento
        la = parse_button_id_lista_agendamento(bid)
        if la:
            acao = la.get('acao')
            if acao == 'ciente':
                return 'Estou ciente'
            if acao == 'reagendar':
                return 'Reagendar pedido'
            if acao == 'mais':
                return 'Próximos'
            if acao == 'turno':
                return 'Manhã' if la.get('turno') == 'MANHA' else 'Tarde'
            if acao == 'data' and la.get('data'):
                return la['data'].strftime('%d/%m/%Y')
            if acao == 'pedido':
                return f"Pedido #{la.get('venda_id')}"
    if bid == "pap_confirmar_sim":
        return (msg or "SIM").strip()
    if not (mensagem_texto or "").strip() and msg:
        return msg.strip()
    return mensagem_texto


def _venda_tentar_enviar_resposta_com_botoes(telefone_formatado, sessao, resposta_texto):
    """
    Etapas PAP que pedem SIM/CONFIRMAR/ALTERAR: envia botões REPLY e retorna None para não duplicar o texto.
    Se a API falhar, devolve o texto original para envio normal.
    """
    if not resposta_texto or not str(resposta_texto).strip():
        return resposta_texto
    et = (getattr(sessao, "etapa", None) or "").strip()
    from crm_app.whatsapp_service import WhatsAppService

    botoes = None
    if et == "venda_agendamento_confirmar_data":
        botoes = [
            {"id": "pap_agenda_confirmar", "type": "REPLY", "label": "CONFIRMAR"},
            {"id": "pap_agenda_alterar", "type": "REPLY", "label": "ALTERAR"},
        ]
    elif et == "venda_agendamento_confirmar_turno":
        botoes = [
            {"id": "pap_agenda_confirmar", "type": "REPLY", "label": "CONFIRMAR"},
            {"id": "pap_agenda_alterar", "type": "REPLY", "label": "ALTERAR"},
        ]
    elif et == "venda_agendamento_sim_agendar":
        botoes = [
            {"id": "pap_agenda_sim", "type": "REPLY", "label": "SIM"},
            {"id": "pap_agenda_cancelar", "type": "REPLY", "label": "CANCELAR"},
        ]
    elif et == "venda_agendamento_final":
        botoes = [
            {"id": "pap_agenda_confirmar", "type": "REPLY", "label": "CONFIRMAR"},
            {"id": "pap_agenda_alterar", "type": "REPLY", "label": "ALTERAR"},
            {"id": "pap_agenda_cancelar", "type": "REPLY", "label": "CANCELAR"},
        ]
    elif et == "venda_confirmar":
        botoes = [
            {"id": "pap_venda_confirmar_envio", "type": "REPLY", "label": "CONFIRMAR"},
            {"id": "pap_agenda_cancelar", "type": "REPLY", "label": "CANCELAR"},
        ]
    elif et == "venda_confirmar_matricula":
        botoes = [
            {"id": "pap_venda_iniciar_sim", "type": "REPLY", "label": "SIM"},
            {"id": "pap_venda_iniciar_cancelar", "type": "REPLY", "label": "CANCELAR"},
        ]
    elif et == "venda_aguardando_abrir_os":
        botoes = [
            {"id": "pap_abrir_os_sim", "type": "REPLY", "label": "SIM"},
            {"id": "pap_abrir_os_nao", "type": "REPLY", "label": "NÃO"},
        ]
    if not botoes:
        return resposta_texto
    ws = WhatsAppService()
    ok, _ = ws.enviar_mensagem_com_botoes_reply(
        telefone_formatado, resposta_texto.strip(), botoes
    )
    if ok:
        logger.info(
            "[Webhook] Etapa %s: resposta enviada com botões REPLY (Z-API)", et
        )
        return None
    return resposta_texto


def _pap_confirmacao_queryset_prioriza_protocolo(qs):
    """Pendências com protocolo_pedido preenchido vêm antes (evita cruzar com registro legado sem protocolo)."""
    from django.db.models import Case, When, Value, IntegerField

    return qs.annotate(
        _prio_proto=Case(
            When(protocolo_pedido__isnull=False, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by("-_prio_proto", "-criado_em")


def _enviar_relato_roubo_para_gc(sessao, telefone_formatado_usuario, usuario_whatsapp):
    """Consolida dados do fluxo ROUBO e envia para o telefone do GC configurado."""
    try:
        from crm_app.models import AnteciparInstalacaoConfig
        from crm_app.whatsapp_service import WhatsAppService

        dados = dict((sessao.dados_temp or {}).get('roubo', {}))
        identificador = (dados.get('identificador') or '').strip()
        tipo_id = dados.get('tipo_identificador') or 'nao_informado'
        print_url = (dados.get('print_url') or '').strip()
        print_tipo = (dados.get('print_tipo') or '').strip()

        if not identificador or not print_url:
            return False, "Dados incompletos para envio ao GC."

        config = AnteciparInstalacaoConfig.objects.first()
        telefone_gc = formatar_telefone((getattr(config, 'telefone_gc', '') or '').strip()) if config else ''
        if not telefone_gc:
            return False, "Telefone do GC nao configurado."

        nome_usuario = ""
        try:
            nome_usuario = (usuario_whatsapp.get_full_name() or usuario_whatsapp.username or "").strip()
        except Exception:
            nome_usuario = ""

        msg_gc = (
            "ALERTA - ROUBO\n\n"
            f"Solicitante: {nome_usuario or 'N/A'}\n"
            f"Telefone: {telefone_formatado_usuario}\n"
            f"Identificador ({tipo_id}): {identificador}\n"
            f"Print ({print_tipo or 'arquivo'}): {print_url}"
        )

        ok, _ = WhatsAppService().enviar_mensagem_texto(telefone_gc, msg_gc)
        return bool(ok), ("Enviado ao GC" if ok else "Falha ao enviar WhatsApp para o GC.")
    except Exception as e:
        logger.exception("[Webhook] Erro ao enviar relato ROUBO ao GC: %s", e)
        return False, "Erro interno ao enviar relato ao GC."


def processar_webhook_whatsapp(data, request=None):
    """
    Processa mensagens recebidas do WhatsApp via webhook.
    request: opcional, usado para gerar URL do PDF (serve-pdf) e enviar documento por URL na Z-API.
    
    Formato esperado do data (Z-API):
    {
        "phone": "5511999999999",
        "message": {
            "text": "Fachada"
        }
    }
    
    Ou formato alternativo:
    {
        "from": "5511999999999",
        "body": "Fachada"
    }
    """
    from django.conf import settings as django_settings

    from crm_app.whatsapp_webhook_normalizer import normalizar_webhook
    data = normalizar_webhook(data)

    if getattr(django_settings, 'WHATSAPP_WEBHOOK_FASTPATH', True):
        from crm_app.whatsapp_webhook_fastpath import avaliar_fastpath_zapi
        rapido = avaliar_fastpath_zapi(data)
        if rapido is not None:
            return rapido

    from crm_app.models import SessaoWhatsapp
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.utils import (
        consultar_viabilidade_kmz,
        consultar_status_venda,
        consultar_status_venda_com_decisao,
        consultar_andamento_agendamentos
    )
    from crm_app.nio_api import consultar_dividas_nio

    if django_settings.DEBUG:
        logger.debug("[Webhook] Payload recebido (keys): %s", list(data.keys()) if isinstance(data, dict) else type(data))
    else:
        logger.debug(
            "[Webhook] type=%s phone=%s isGroup=%s",
            (data or {}).get('type') if isinstance(data, dict) else None,
            (data or {}).get('phone') if isinstance(data, dict) else None,
            (data or {}).get('isGroup') if isinstance(data, dict) else None,
        )
    
    # Ignorar mensagens enviadas pelo próprio bot (evita eco e resposta duplicada)
    from_me = data.get('fromMe') or data.get('isFromMe') or data.get('from_me')
    if not from_me and isinstance(data.get('message'), dict):
        from_me = data['message'].get('fromMe') or data['message'].get('isFromMe') or data['message'].get('from_me')
    if from_me:
        logger.info("[Webhook] Ignorando mensagem do próprio bot (fromMe=True)")
        return {'status': 'ok', 'mensagem': 'Ignorando mensagem do próprio bot'}
    
    # Extrair telefone e mensagem do payload (Z-API pode usar phone, from, text.participant, etc.)
    telefone = data.get('phone') or data.get('from') or data.get('phoneNumber') or data.get('phone_number')
    if not telefone and isinstance(data.get('text'), dict):
        telefone = data['text'].get('participant')
    if not telefone and isinstance(data.get('message'), dict):
        telefone = (data.get('message') or {}).get('participant')
    is_group = bool(data.get('isGroup') or (isinstance(telefone, str) and '-group' in telefone))
    participant_phone = data.get('participantPhone') or data.get('participant_phone')
    if not participant_phone and isinstance(data.get('text'), dict):
        participant_phone = data['text'].get('participant')
    if not participant_phone and isinstance(data.get('message'), dict):
        participant_phone = (data.get('message') or {}).get('participant')
    if is_group and participant_phone:
        telefone_usuario = participant_phone  # Para identificar quem enviou (lookup usuário)
    else:
        telefone_usuario = telefone

    telefone = _strip_whatsapp_jid(telefone)
    telefone_usuario = _strip_whatsapp_jid(telefone_usuario)
    participant_phone = _strip_whatsapp_jid(participant_phone)

    from crm_app.whatsapp_telefone_blocklist import telefone_esta_bloqueado
    if (
        telefone_esta_bloqueado(telefone)
        or telefone_esta_bloqueado(telefone_usuario)
        or telefone_esta_bloqueado(participant_phone)
    ):
        logger.info(
            "[Webhook] Telefone bloqueado ignorado: telefone=%s usuario=%s participant=%s",
            telefone,
            telefone_usuario,
            participant_phone,
        )
        return {'status': 'ok', 'mensagem': 'Telefone bloqueado'}

    # Extrair mensagem antes do return de grupo (para permitir resposta do GC em grupo)
    mensagem_texto = ""
    if 'text' in data and isinstance(data['text'], dict):
        mensagem_texto = data['text'].get('message') or data['text'].get('text') or data['text'].get('body') or ""
    if not mensagem_texto:
        if 'message' in data:
            if isinstance(data['message'], dict):
                mensagem_texto = data['message'].get('text') or data['message'].get('body') or data['message'].get('message') or ""
            else:
                mensagem_texto = str(data['message'])
        else:
            mensagem_texto = data.get('text') or data.get('body') or data.get('message') or data.get('content') or ""
    if not mensagem_texto:
        if 'data' in data and isinstance(data['data'], dict):
            mensagem_texto = data['data'].get('text') or data['data'].get('body') or data['data'].get('message') or ""
        if 'payload' in data and isinstance(data['payload'], dict):
            mensagem_texto = data['payload'].get('text') or data['payload'].get('body') or data['payload'].get('message') or ""
    if isinstance(mensagem_texto, dict):
        mensagem_texto = mensagem_texto.get('message') or mensagem_texto.get('text') or mensagem_texto.get('body') or str(mensagem_texto)
    elif not isinstance(mensagem_texto, str):
        mensagem_texto = str(mensagem_texto) if mensagem_texto else ""
    mensagem_texto = (mensagem_texto or "").strip()
    mensagem_texto = _aplicar_resposta_botao_zapi(data, mensagem_texto).strip()
    if not mensagem_texto:
        mensagem_texto = (_texto_efetivo_botao_zapi(data) or "").strip()
    if _buscar_buttons_response_zapi(data):
        bid_dbg, msg_dbg = _extrair_dados_botao_zapi(data)
        logger.info(
            "[Webhook] buttonsResponseMessage presente; texto efetivo: %r buttonId=%r",
            mensagem_texto,
            bid_dbg or '-',
        )

    # Ignorar mensagens de grupo — exceto se for resposta do GC (formato [O.S], antecipada|não antecipada|solicitado)
    if is_group:
        if mensagem_texto and processar_resposta_gc_antecipar(participant_phone or telefone, mensagem_texto):
            return {'status': 'ok', 'mensagem': 'Resposta GC registrada'}
        logger.info("[Webhook] Mensagem de grupo ignorada - bot não responde em grupos")
        return {'status': 'ok', 'mensagem': 'Mensagem de grupo ignorada'}

    # Extrair URL de imagem (Z-API: image.imageUrl) - para etapa inclusao_foto
    image_url = None
    if 'image' in data and isinstance(data.get('image'), dict):
        image_url = data['image'].get('imageUrl') or data['image'].get('image')
    elif data.get('imageUrl'):
        image_url = data.get('imageUrl')
    if image_url:
        logger.info(f"[Webhook] Imagem detectada: {image_url[:80]}...")
    # Extrair URL de documento (Z-API: document.documentUrl ou document como URL) - para etapa inclusao_comprovante
    document_url = None
    if 'document' in data:
        doc = data['document']
        if isinstance(doc, dict):
            document_url = doc.get('documentUrl') or doc.get('document') or doc.get('url')
        elif isinstance(doc, str) and doc.startswith('http'):
            document_url = doc
    if not document_url and data.get('documentUrl'):
        document_url = data.get('documentUrl')
    if document_url:
        logger.info(f"[Webhook] Documento detectado: {document_url[:80]}...")
    
    logger.info(f"[Webhook] Telefone extraído: {telefone}, is_group={is_group}, participant_phone={participant_phone}")
    logger.info(f"[Webhook] Telefone para usuário (lookup): {telefone_usuario}")
    logger.info(f"[Webhook] Mensagem extraída: {mensagem_texto!r}")
    
    # Ignorar webhooks só de reação (emoji) - não têm texto/anexo, evitar 500
    from crm_app.esteira_posso_antecipar_service import (
        _extrair_reference_message_id_zapi as _ref_msg_zapi,
        buscar_solicitacao_por_mensagem_whatsapp,
    )
    from crm_app.esteira_posso_reagendar_service import buscar_sessao_por_mensagem_whatsapp as buscar_sessao_reagendar_ref
    from crm_app.esteira_lista_agendamento_vendedor_service import (
        buscar_sessao_por_mensagem_whatsapp as buscar_sessao_lista_agendamento_ref,
    )
    _bid_early, _bmsg_early = _extrair_dados_botao_zapi(data)
    tem_resposta_botao = bool(_buscar_buttons_response_zapi(data) or _bid_early or _bmsg_early)
    ref_early = _ref_msg_zapi(data)
    if (
        not mensagem_texto
        and not image_url
        and not document_url
        and not tem_resposta_botao
        and ref_early
        and telefone_usuario
    ):
        tel_early = formatar_telefone(telefone_usuario)
        if tel_early and buscar_solicitacao_por_mensagem_whatsapp(ref_early, tel_early):
            tem_resposta_botao = True
            if _bmsg_early:
                mensagem_texto = _bmsg_early
            logger.info(
                '[Webhook] Clique em botão posso antecipar (ref=%r) texto=%r',
                ref_early,
                (_bmsg_early or mensagem_texto or '')[:60],
            )
        elif tel_early and buscar_sessao_reagendar_ref(ref_early, tel_early):
            tem_resposta_botao = True
            if _bmsg_early:
                mensagem_texto = _bmsg_early
            logger.info(
                '[Webhook] Clique em botão posso reagendar (ref=%r) texto=%r',
                ref_early,
                (_bmsg_early or mensagem_texto or '')[:60],
            )
        elif tel_early and buscar_sessao_lista_agendamento_ref(ref_early, tel_early):
            tem_resposta_botao = True
            if _bmsg_early:
                mensagem_texto = _bmsg_early
            logger.info(
                '[Webhook] Clique em botão lista agendamento (ref=%r) texto=%r',
                ref_early,
                (_bmsg_early or mensagem_texto or '')[:60],
            )
    if not mensagem_texto and not image_url and not document_url and not tem_resposta_botao:
        if 'reaction' in data:
            logger.debug("[Webhook] Reação (emoji) ignorada - sem texto/anexo")
            return {'status': 'ok', 'mensagem': 'Reação ignorada'}
        logger.debug("[Webhook] Sem texto/anexo: telefone=%s", telefone)
        return {'status': 'ok', 'mensagem': 'Webhook sem conteúdo ignorado'}
    if not telefone:
        logger.warning(f"[Webhook] Dados incompletos: telefone vazio")
        return {'status': 'erro', 'mensagem': 'Telefone não informado'}

    import time
    _webhook_t0 = time.monotonic()  # provisório: medir tempo de cada etapa (retorno ao usuário)

    telefone_formatado = formatar_telefone(telefone)  # chat (grupo ou direto) - para enviar resposta
    telefone_formatado_usuario = formatar_telefone(telefone_usuario)  # quem enviou - para lookup usuário
    mensagem_limpa = (mensagem_texto or "").strip().upper()
    
    logger.info(f"[Webhook] Mensagem recebida de {telefone_formatado_usuario} (chat={telefone_formatado}): {mensagem_texto!r}")
    logger.info(f"[Webhook] Mensagem limpa (uppercase): {mensagem_limpa}")

    # --- Resposta do GC (Antecipar Instalação): [O.S], antecipada|não antecipada|solicitado — atualiza sistema e manda msg ao vendedor
    if mensagem_texto and processar_resposta_gc_antecipar(telefone_formatado_usuario, mensagem_texto):
        return {'status': 'ok', 'mensagem': 'Resposta GC registrada'}

    # --- Resposta vendedor (lista diária de agendamentos: ciência / reagendar)
    button_id_la, texto_botao_la = _extrair_dados_botao_zapi(data)
    if not mensagem_texto and texto_botao_la:
        mensagem_texto = texto_botao_la
    from crm_app.esteira_lista_agendamento_vendedor_service import (
        _extrair_reference_message_id_zapi as _ref_msg_lista,
        deve_tentar_lista_agendamento,
        processar_resposta_lista_agendamento,
    )
    ref_msg_la = _ref_msg_lista(data)
    if (button_id_la or '').startswith('la_') or deve_tentar_lista_agendamento(
        mensagem_texto or '',
        button_id=button_id_la,
        reference_message_id=ref_msg_la,
        telefone=telefone_formatado_usuario,
    ):
        try:
            if ref_msg_la or button_id_la:
                logger.info(
                    '[Webhook] Lista agendamento: ref=%r buttonId=%r texto=%r',
                    ref_msg_la or '-',
                    button_id_la or '-',
                    (mensagem_texto or '')[:60],
                )
            if processar_resposta_lista_agendamento(
                telefone_formatado_usuario,
                mensagem_texto,
                button_id=button_id_la,
                reference_message_id=ref_msg_la,
            ):
                return {'status': 'ok', 'mensagem': 'Resposta lista agendamento vendedor'}
        except Exception as e:
            logger.warning('[Webhook] Erro lista agendamento vendedor: %s', e, exc_info=True)

    # --- Resposta consultor (Posso reagendar? — pendência na esteira)
    button_id_pr, texto_botao_pr = _extrair_dados_botao_zapi(data)
    if not mensagem_texto and texto_botao_pr:
        mensagem_texto = texto_botao_pr
    from crm_app.esteira_posso_reagendar_service import (
        _extrair_reference_message_id_zapi as _ref_msg_reagendar,
        deve_tentar_posso_reagendar,
        processar_resposta_posso_reagendar_consultor,
    )
    ref_msg_pr = _ref_msg_reagendar(data)
    if (button_id_pr or '').startswith('pr_') or deve_tentar_posso_reagendar(
        mensagem_texto or '',
        button_id=button_id_pr,
        reference_message_id=ref_msg_pr,
        telefone=telefone_formatado_usuario,
    ):
        try:
            if ref_msg_pr or button_id_pr:
                logger.info(
                    '[Webhook] Posso reagendar: ref=%r buttonId=%r texto=%r',
                    ref_msg_pr or '-',
                    button_id_pr or '-',
                    (mensagem_texto or '')[:60],
                )
            if processar_resposta_posso_reagendar_consultor(
                telefone_formatado_usuario,
                mensagem_texto,
                button_id=button_id_pr,
                reference_message_id=ref_msg_pr,
            ):
                return {'status': 'ok', 'mensagem': 'Resposta posso reagendar consultor'}
        except Exception as e:
            logger.warning('[Webhook] Erro posso reagendar consultor: %s', e, exc_info=True)

    # --- Resposta vendedor (Posso antecipar? — esteira): só se parecer resposta ou botão pa_*
    button_id_pa, texto_botao_pa = _extrair_dados_botao_zapi(data)
    if not mensagem_texto and texto_botao_pa:
        mensagem_texto = texto_botao_pa
    from crm_app.esteira_posso_antecipar_service import (
        _extrair_reference_message_id_zapi,
        deve_tentar_posso_antecipar,
        processar_resposta_posso_antecipar_vendedor,
    )
    ref_msg_pa = _extrair_reference_message_id_zapi(data)
    if deve_tentar_posso_antecipar(
        mensagem_texto or '',
        button_id=button_id_pa,
        reference_message_id=ref_msg_pa,
        telefone=telefone_formatado_usuario,
    ):
        try:
            if ref_msg_pa or button_id_pa:
                logger.info(
                    '[Webhook] Posso antecipar: ref=%r buttonId=%r texto=%r',
                    ref_msg_pa or '-',
                    button_id_pa or '-',
                    (mensagem_texto or '')[:60],
                )
            if processar_resposta_posso_antecipar_vendedor(
                telefone_formatado_usuario,
                mensagem_texto,
                button_id=button_id_pa,
                reference_message_id=ref_msg_pa,
            ):
                return {'status': 'ok', 'mensagem': 'Resposta posso antecipar vendedor'}
        except Exception as e:
            logger.warning('[Webhook] Erro posso antecipar vendedor: %s', e, exc_info=True)

    # --- Resposta do CLIENTE (SIM/CONFIRMAR/CORRETO) antes de exigir usuário ativo ---
    # Quando o sistema envia "RESUMO DO PEDIDO... responda SIM" ao cliente (fluxo PAP ou
    # resumo enviado da auditoria), a resposta vem do número do cliente, que não é usuário interno.
    # Tratar aqui para não rejeitar com "não pertence a nenhum usuário ativo".
    from crm_app.services.whatsapp.nio_templates import (
        BTN_CORRETO,
        BTN_CORRIGIR,
        BTN_ENTENDI,
        BTN_FALAR_ATENDENTE,
        BTN_FALAR_SUPORTE,
        BTN_INFORMAR_PREVISAO,
        BTN_JA_PAGUEI,
        BTN_REAGENDAR,
        BTN_SEGUNDA_VIA,
        BTN_SUPORTE,
        classificar_botao,
        enviar_instalacao_confirmada,
    )

    botao_meta = classificar_botao(mensagem_texto) or classificar_botao(mensagem_limpa)

    if mensagem_limpa in ['SIM', 'S', 'CONFIRMAR', 'CORRETO'] or botao_meta == BTN_CORRETO:
        chave = _chave_telefone(telefone_formatado_usuario)
        chaves_tentar = _chaves_telefone_variantes(telefone_formatado_usuario) or [chave]
        with _pending_lock:
            pend_cliente = next((_pending_client_confirm.get(k) for k in chaves_tentar if _pending_client_confirm.get(k)), None)
        if pend_cliente:
            from crm_app.pap_protocolo_confirmacao_envio import gerar_protocolo_confirmacao_envio

            proto_envio = gerar_protocolo_confirmacao_envio()
            try:
                from crm_app.models import PapConfirmacaoCliente

                sessao_id_pend = pend_cliente.get('sessao_id')
                for k in (chaves_tentar or [chave]):
                    updated = PapConfirmacaoCliente.objects.filter(
                        celular_cliente=k, confirmado=False, sessao_id=sessao_id_pend
                    ).update(confirmado=True, protocolo_confirmacao_envio=proto_envio)
                    if updated:
                        logger.info(f"[Webhook] [Cliente] PapConfirmacaoCliente confirmado (sessao_id={sessao_id_pend}, celular={k})")
                        break
            except Exception as e:
                logger.warning(f"[Webhook] Erro ao marcar PapConfirmacaoCliente (cliente): {e}", exc_info=True)
            pend_cliente['event'].set()
            try:
                msg_cliente = _texto_confirmacao_cliente_pap(proto_envio)
                WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg_cliente)
            except Exception:
                pass
            return {'status': 'ok', 'mensagem': 'Confirmado pelo cliente'}
        # Fallback: confirmação só no BD (ex.: outro replica não tem o in-memory pend)
        try:
            from crm_app.models import PapConfirmacaoCliente, Venda
            pend_bd = _pap_confirmacao_queryset_prioriza_protocolo(
                PapConfirmacaoCliente.objects.filter(
                    celular_cliente__in=chaves_tentar, confirmado=False
                )
            ).first()
            if pend_bd:
                from crm_app.pap_protocolo_confirmacao_envio import gerar_protocolo_confirmacao_envio

                proto_envio = gerar_protocolo_confirmacao_envio()
                pend_bd.confirmado = True
                pend_bd.protocolo_confirmacao_envio = proto_envio
                pend_bd.save(update_fields=["confirmado", "protocolo_confirmacao_envio"])
                logger.info(f"[Webhook] [Cliente] PapConfirmacaoCliente confirmado via BD (celular={pend_bd.celular_cliente})")
                with _pending_lock:
                    for _k, _v in _pending_client_confirm.items():
                        if _v.get('sessao_id') == pend_bd.sessao_id:
                            _v['event'].set()
                            break
                try:
                    # Resumo da auditoria: mesmo protocolo de envio (YYYYMMDDHHMM + seq) na venda
                    if getattr(pend_bd, "venda_id", None) and pend_bd.venda_id:
                        venda = Venda.objects.filter(id=pend_bd.venda_id).first()
                        if venda and not venda.protocolo_confirmacao_auditoria:
                            now = timezone.now()
                            venda.cliente_confirmou_auditoria = True
                            venda.protocolo_confirmacao_auditoria = proto_envio
                            venda.data_confirmacao_auditoria = now
                            venda.save(
                                update_fields=[
                                    "cliente_confirmou_auditoria",
                                    "protocolo_confirmacao_auditoria",
                                    "data_confirmacao_auditoria",
                                ]
                            )
                            logger.info(
                                f"[Webhook] [Auditoria] Protocolo confirmação venda {venda.id}: {proto_envio}"
                            )
                    msg_cliente = _texto_confirmacao_cliente_pap(proto_envio)
                    WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg_cliente)
                except Exception:
                    pass
                return {'status': 'ok', 'mensagem': 'Confirmado pelo cliente (BD)'}
        except Exception as e:
            logger.warning(f"[Webhook] Erro ao confirmar PapConfirmacaoCliente (BD): {e}", exc_info=True)

    # CORRIGIR / Falar com atendente no resumo do pedido (template Meta)
    if botao_meta in (BTN_CORRIGIR, BTN_FALAR_ATENDENTE):
        chave = _chave_telefone(telefone_formatado_usuario)
        chaves_tentar = _chaves_telefone_variantes(telefone_formatado_usuario) or [chave]
        try:
            from crm_app.models import PapConfirmacaoCliente

            pend_bd = PapConfirmacaoCliente.objects.filter(
                celular_cliente__in=chaves_tentar, confirmado=False
            ).order_by("-criado_em").first()
            if pend_bd or botao_meta == BTN_FALAR_ATENDENTE:
                if botao_meta == BTN_CORRIGIR:
                    msg = (
                        "Sem problemas. Informe o que precisa ser corrigido "
                        "(endereço, plano, pagamento, dados pessoais) e um especialista dará continuidade."
                    )
                else:
                    msg = "Em breve um especialista irá falar contigo."
                try:
                    WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg)
                except Exception:
                    pass
                return {
                    "status": "ok",
                    "mensagem": f"Resumo pedido botão={botao_meta}",
                }
        except Exception as e:
            logger.warning("[Webhook] Erro CORRIGIR/atendente: %s", e, exc_info=True)
    
    # Se este número tem resumo enviado da auditoria (pendência de confirmação, sessao=None),
    # não enviar "usuário não ativo" — orientar a responder SIM ou CONFIRMAR.
    chave = _chave_telefone(telefone_formatado_usuario)
    chaves_tentar_ua = _chaves_telefone_variantes(telefone_formatado_usuario) or [chave]
    try:
        from crm_app.models import PapConfirmacaoCliente
        pendente_auditoria = PapConfirmacaoCliente.objects.filter(
            celular_cliente__in=chaves_tentar_ua, confirmado=False, sessao__isnull=True
        ).exists()
        if pendente_auditoria:
            try:
                WhatsAppService.para_cliente().enviar_mensagem_texto(
                    telefone_formatado,
                    "Para confirmar o resumo do plano, toque em *CORRETO* ou responda *SIM* / *CONFIRMAR*.\n"
                    "Se algo estiver errado, toque em *CORRIGIR*."
                )
            except Exception as e:
                logger.warning(f"[Webhook] Erro ao enviar orientação resumo auditoria: {e}")
            return {'status': 'ok', 'mensagem': 'Aguardando confirmação do cliente (resumo auditoria)'}
    except Exception as e:
        logger.warning(f"[Webhook] Erro ao verificar pendência resumo auditoria: {e}", exc_info=True)
    
    # --- Resposta ao lembrete de instalação (esteira): SIM / NÃO / CANCELAR / SUPORTE ---
    try:
        from datetime import timedelta
        from crm_app.models import LembreteInstalacaoEnviado
        chave_lembrete = _chave_telefone(telefone_formatado_usuario)
        chaves_lembrete = _chaves_telefone_variantes(telefone_formatado_usuario) or [chave_lembrete]
        limite_envio = timezone.now() - timedelta(hours=48)
        lembrete = LembreteInstalacaoEnviado.objects.filter(
            telefone__in=chaves_lembrete,
            respondido_em__isnull=True,
            data_envio__gte=limite_envio,
        ).order_by('-data_envio').select_related('venda').first()
        if lembrete:
            periodo = lembrete.periodo_agendamento or ''
            if periodo == 'MANHA':
                horario_texto = '8h às 12h'
            else:
                horario_texto = '13h às 18h'
            texto_resposta = (mensagem_texto or '').strip() or mensagem_limpa or ''
            agora = timezone.now()
            venda = lembrete.venda
            campos_venda = ['cliente_resposta_lembrete_instalacao', 'data_resposta_lembrete_instalacao', 'cliente_confirmou_lembrete_instalacao']

            from crm_app.services.whatsapp.nio_templates import BTN_CONFIRMAR as _BTN_CONF

            confirmou = (
                mensagem_limpa in ['SIM', 'S', 'CONFIRMAR', 'CONFIRMO', 'OK', 'CERTO', 'PODE SER', 'POSSO']
                or botao_meta == _BTN_CONF
            )

            if confirmou:
                data_ref = lembrete.data_agendamento or timezone.localdate()
                periodo_ref = lembrete.periodo_agendamento or periodo
                try:
                    data_txt = data_ref.strftime('%d/%m/%Y')
                except Exception:
                    data_txt = str(data_ref)
                fallback = (
                    f"Confirmação registrada!\n"
                    f"Sua instalação Nio Fibra está confirmada para {data_txt}, "
                    f"das {horario_texto}.\n"
                    "Nosso técnico entrará em contato por ligação e WhatsApp quando estiver a caminho."
                )
                try:
                    enviar_instalacao_confirmada(
                        telefone_formatado, data_ref, periodo_ref, fallback
                    )
                except Exception:
                    try:
                        WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, fallback)
                    except Exception:
                        pass
                lembrete.respondido_em = agora
                lembrete.save(update_fields=['respondido_em'])
                venda.cliente_confirmou_lembrete_instalacao = True
                venda.cliente_resposta_lembrete_instalacao = texto_resposta[:2000] if texto_resposta else None
                venda.data_resposta_lembrete_instalacao = agora
                venda.save(update_fields=campos_venda)
                return {'status': 'ok', 'mensagem': 'Confirmação instalação (SIM/Confirmar)'}
            if (
                mensagem_limpa == 'SUPORTE'
                or botao_meta in (BTN_SUPORTE, BTN_FALAR_SUPORTE)
                or mensagem_limpa in ['NAO', 'NÃO', 'NAO QUERO', 'NÃO QUERO', 'CANCELAR', 'CANCELAR INSTALACAO', 'DESISTIR']
            ):
                msg = "Em breve um especialista irá falar contigo"
                try:
                    WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg)
                except Exception:
                    pass
                lembrete.respondido_em = agora
                lembrete.save(update_fields=['respondido_em'])
                venda.cliente_confirmou_lembrete_instalacao = False
                venda.cliente_resposta_lembrete_instalacao = texto_resposta[:2000] if texto_resposta else None
                venda.data_resposta_lembrete_instalacao = agora
                venda.save(update_fields=campos_venda)
                return {'status': 'ok', 'mensagem': 'Resposta lembrete instalação (não/suporte)'}
            if botao_meta == BTN_REAGENDAR or mensagem_limpa == 'REAGENDAR':
                msg = (
                    "Para reagendar, envie o *dia* e o *período* desejados (manhã ou tarde). "
                    "Ex.: 20/08 manhã"
                )
                try:
                    WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg)
                except Exception:
                    pass
                # Mantém lembrete aberto para a próxima mensagem com a nova data
                venda.cliente_confirmou_lembrete_instalacao = False
                venda.cliente_resposta_lembrete_instalacao = texto_resposta[:2000] if texto_resposta else None
                venda.data_resposta_lembrete_instalacao = agora
                venda.save(update_fields=campos_venda)
                return {'status': 'ok', 'mensagem': 'Lembrete instalação — pedir reagendamento'}
            if botao_meta == BTN_ENTENDI:
                lembrete.respondido_em = agora
                lembrete.save(update_fields=['respondido_em'])
                return {'status': 'ok', 'mensagem': 'Instalação — Entendi'}
            # Qualquer outra resposta: tenta atendimento com dados do pedido; senão escalona humano
            msg = None
            if texto_resposta:
                try:
                    from crm_app.services.whatsapp_ia_config_service import ia_clientes_venda_habilitada

                    if ia_clientes_venda_habilitada():
                        from crm_app.cliente_atendimento_ia_service import processar_mensagem_cliente_venda

                        msg = processar_mensagem_cliente_venda(
                            telefone_formatado_usuario, texto_resposta, origem="LEMBRETE_INSTALACAO"
                        )
                except Exception as e_lem_ia:
                    logger.warning("[Webhook] Resposta IA cliente (lembrete): %s", e_lem_ia)
            if not msg:
                msg = "Em breve um especialista irá falar contigo"
            try:
                WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg)
            except Exception:
                pass
            lembrete.respondido_em = agora
            lembrete.save(update_fields=['respondido_em'])
            venda.cliente_confirmou_lembrete_instalacao = False
            venda.cliente_resposta_lembrete_instalacao = texto_resposta[:2000] if texto_resposta else None
            venda.data_resposta_lembrete_instalacao = agora
            venda.save(update_fields=campos_venda)
            return {'status': 'ok', 'mensagem': 'Resposta lembrete instalação (outro)'}
    except Exception as e:
        logger.warning(f"[Webhook] Erro ao processar lembrete instalação: {e}", exc_info=True)

    # --- Botões de cobrança (template Meta fatura) ---
    if botao_meta in (BTN_SEGUNDA_VIA, BTN_JA_PAGUEI, BTN_FALAR_SUPORTE, BTN_INFORMAR_PREVISAO):
        try:
            from crm_app.services.qualidade_service import (
                montar_mensagem_cobranca_roteiro1,
                registrar_resposta_cliente_qualidade,
                resolver_contexto_cobranca_por_telefone,
            )

            ctx_cob = resolver_contexto_cobranca_por_telefone(
                telefone_formatado_usuario, dias=14
            )
            fatura_ctx = (ctx_cob or {}).get("fatura")
            contrato_ctx = (ctx_cob or {}).get("contrato")

            if botao_meta == BTN_FALAR_SUPORTE:
                if contrato_ctx:
                    registrar_resposta_cliente_qualidade(
                        contrato=contrato_ctx,
                        fatura=fatura_ctx,
                        telefone=telefone_formatado,
                        texto=BTN_FALAR_SUPORTE,
                        origem="botao",
                    )
                WhatsAppService.para_cliente().enviar_mensagem_texto(
                    telefone_formatado, "Em breve um especialista irá falar contigo."
                )
                return {"status": "ok", "mensagem": "Cobrança — suporte"}

            if botao_meta == BTN_INFORMAR_PREVISAO:
                if contrato_ctx:
                    registrar_resposta_cliente_qualidade(
                        contrato=contrato_ctx,
                        fatura=fatura_ctx,
                        telefone=telefone_formatado,
                        texto=BTN_INFORMAR_PREVISAO,
                        origem="botao",
                    )
                WhatsAppService.para_cliente().enviar_mensagem_texto(
                    telefone_formatado,
                    "Perfeito. Qual a *data prevista de pagamento*?\n"
                    "Responda no formato *DD/MM/AAAA* (exemplo: 25/08/2026).",
                )
                return {"status": "ok", "mensagem": "Cobrança — informar previsão"}

            if botao_meta == BTN_JA_PAGUEI:
                if contrato_ctx:
                    registrar_resposta_cliente_qualidade(
                        contrato=contrato_ctx,
                        fatura=fatura_ctx,
                        telefone=telefone_formatado,
                        texto=BTN_JA_PAGUEI,
                        origem="botao",
                    )
                WhatsAppService.para_cliente().enviar_mensagem_texto(
                    telefone_formatado,
                    "Obrigado! Se possível, envie o *comprovante de pagamento* nesta conversa "
                    "para agilizarmos a baixa. A confirmação pode levar até 5 dias úteis.",
                )
                return {"status": "ok", "mensagem": "Cobrança — já paguei"}

            # Quero a 2ª via — consulta PIX fresco na Nio (o do CRM pode ter expirado)
            if fatura_ctx and contrato_ctx:
                registrar_resposta_cliente_qualidade(
                    contrato=contrato_ctx,
                    fatura=fatura_ctx,
                    telefone=telefone_formatado,
                    texto=BTN_SEGUNDA_VIA,
                    origem="botao",
                )
                try:
                    WhatsAppService.para_cliente().enviar_mensagem_texto(
                        telefone_formatado,
                        "Consultando a *2ª via atualizada* na Nio. Um instante…",
                        variar=False,
                    )
                except Exception:
                    logger.warning("[Webhook] Falha aviso 2ª via", exc_info=True)
                from crm_app.services.nio_match_service import (
                    STATUS_AMBIGUO,
                    obter_segunda_via_atualizada,
                )

                via = obter_segunda_via_atualizada(contrato_ctx, fatura_ctx)
                fatura_msg = via.get("fatura") or fatura_ctx
                pix = (via.get("codigo_pix") or getattr(fatura_msg, "codigo_pix", None) or "").strip()
                barras = (
                    via.get("codigo_barras") or getattr(fatura_msg, "codigo_barras", None) or ""
                ).strip()
                if pix:
                    fatura_msg.codigo_pix = pix
                if barras:
                    fatura_msg.codigo_barras = barras
                if pix or barras:
                    msg = montar_mensagem_cobranca_roteiro1(contrato_ctx, fatura_msg)
                    if via.get("status") == STATUS_AMBIGUO:
                        msg = (
                            "Encontramos mais de uma fatura na mesma data, "
                            "então não atualizamos o PIX automaticamente. "
                            "Segue o que temos no cadastro — se não funcionar, "
                            "fale com o suporte.\n\n"
                            + msg
                        )
                    elif via.get("fonte") == "nio_fresco":
                        msg = "Segue a *2ª via atualizada* (PIX gerado agora na Nio).\n\n" + msg
                    WhatsAppService.para_cliente().enviar_mensagem_texto(
                        telefone_formatado, msg, variar=False
                    )
                    return {"status": "ok", "mensagem": "Cobrança — 2ª via enviada"}
                WhatsAppService.para_cliente().enviar_mensagem_texto(
                    telefone_formatado,
                    "Não localizei um PIX atualizado nesta consulta. "
                    "Um especialista vai te atender em breve.",
                )
                return {"status": "ok", "mensagem": "Cobrança — 2ª via sem PIX"}
            WhatsAppService.para_cliente().enviar_mensagem_texto(
                telefone_formatado,
                "Para enviar a 2ª via, responda com o *CPF* do titular "
                "ou aguarde um especialista.",
            )
            return {"status": "ok", "mensagem": "Cobrança — 2ª via sem contexto"}
        except Exception as e:
            logger.warning("[Webhook] Erro botão cobrança: %s", e, exc_info=True)

    # --- Texto livre do cliente após cobrança Qualidade (janela 14 dias) ---
    try:
        texto_livre_cob = (mensagem_texto or mensagem_limpa or "").strip()
        if texto_livre_cob and botao_meta not in (
            BTN_SEGUNDA_VIA,
            BTN_JA_PAGUEI,
            BTN_FALAR_SUPORTE,
            BTN_INFORMAR_PREVISAO,
        ):
            from crm_app.services.qualidade_service import (
                extrair_data_promessa_texto,
                gravar_promessa_pagamento_qualidade,
                registrar_resposta_cliente_qualidade,
                resolver_contexto_cobranca_por_telefone,
            )

            ctx_txt = resolver_contexto_cobranca_por_telefone(
                telefone_formatado_usuario, dias=14
            )
            if ctx_txt and ctx_txt.get("contrato"):
                fatura_txt = ctx_txt.get("fatura")
                data_promessa = extrair_data_promessa_texto(texto_livre_cob)
                if data_promessa and fatura_txt:
                    gravou = gravar_promessa_pagamento_qualidade(
                        fatura_txt,
                        data_promessa,
                        contrato=ctx_txt["contrato"],
                        telefone=telefone_formatado,
                    )
                    if gravou:
                        WhatsAppService.para_cliente().enviar_mensagem_texto(
                            telefone_formatado,
                            "Previsão registrada: *"
                            f"{data_promessa.strftime('%d/%m/%Y')}*. "
                            "Obrigado! Assim que o pagamento for identificado, "
                            "o sinal é regularizado.",
                        )
                        return {"status": "ok", "mensagem": "Cobrança — promessa gravada"}
                registrar_resposta_cliente_qualidade(
                    contrato=ctx_txt["contrato"],
                    fatura=fatura_txt,
                    telefone=telefone_formatado,
                    texto=texto_livre_cob,
                    origem="texto",
                )
                logger.info(
                    "[Webhook] Texto livre cobrança gravado contrato=%s",
                    getattr(ctx_txt["contrato"], "id", None),
                )
                # Não retorna: deixa outros fluxos (boas-vindas etc.) avaliarem.
    except Exception as e:
        logger.debug("[Webhook] Texto livre cobrança: %s", e, exc_info=True)

    # --- Resposta ao boas-vindas: gravar TODAS as mensagens do cliente (histórico completo) ---
    try:
        from datetime import timedelta as _td
        from crm_app.models import BoasVindasEnviado, MensagemClienteBoasVindas
        chave_bv = _chave_telefone(telefone_formatado_usuario)
        chaves_bv = _chaves_telefone_variantes(telefone_formatado_usuario) or [chave_bv]
        limite_bv = timezone.now() - _td(days=30)
        # Busca o envio mais recente para este telefone (para continuar recebendo mensagens)
        bv = BoasVindasEnviado.objects.filter(
            telefone__in=chaves_bv,
            data_envio__gte=limite_bv,
        ).order_by('-data_envio').select_related('venda').first()
        if bv:
            texto_resposta = (mensagem_texto or '').strip() or mensagem_limpa or ''
            agora_bv = timezone.now()
            # Sempre registra cada mensagem no histórico
            MensagemClienteBoasVindas.objects.create(
                boas_vindas_enviado=bv,
                texto=texto_resposta[:5000] if texto_resposta else '',
                direcao='ENTRADA',
            )
            # Primeira resposta: marca respondido_em e sugere status via IA
            if bv.respondido_em is None:
                bv.respondido_em = agora_bv
                bv.save(update_fields=['respondido_em'])
                try:
                    from crm_app.services.whatsapp_ia_config_service import ia_boas_vindas_sugestao_habilitada

                    if ia_boas_vindas_sugestao_habilitada():
                        from crm_app.ai_chat_service import sugerir_status_boas_vindas
                        bv.sugestao_status_ia = sugerir_status_boas_vindas(texto_resposta)
                        bv.save(update_fields=['sugestao_status_ia'])
                except Exception as e_ia:
                    logger.warning(f"[Webhook] IA sugestão boas-vindas: {e_ia}")
            # Atualiza sempre a última mensagem na venda (para exibição rápida)
            venda_bv = bv.venda
            venda_bv.cliente_resposta_boas_vindas = texto_resposta[:2000] if texto_resposta else None
            venda_bv.data_resposta_boas_vindas = agora_bv
            venda_bv.save(update_fields=['cliente_resposta_boas_vindas', 'data_resposta_boas_vindas'])
            if texto_resposta:
                try:
                    from crm_app.services.whatsapp_ia_config_service import ia_clientes_venda_habilitada

                    if ia_clientes_venda_habilitada():
                        from crm_app.cliente_atendimento_ia_service import processar_mensagem_cliente_venda

                        resp_bv = processar_mensagem_cliente_venda(
                            telefone_formatado_usuario, texto_resposta, origem="BOAS_VINDAS"
                        )
                        if resp_bv:
                            WhatsAppService.para_cliente().enviar_mensagem_texto(
                                telefone_formatado, resp_bv
                            )
                except Exception as e_bv_ia:
                    logger.warning("[Webhook] Resposta IA cliente (boas-vindas): %s", e_bv_ia)
            return {'status': 'ok', 'mensagem': 'Resposta boas-vindas registrada'}
    except Exception as e:
        logger.warning(f"[Webhook] Erro ao processar resposta boas-vindas: {e}", exc_info=True)
    
    # PAP: confirmação do cliente (SIM) / BIO OK antes de tratar "contato externo" (cliente não é usuário interno).
    etapa_sessao = None
    try:
        etapa_sessao = SessaoWhatsapp.objects.filter(telefone=telefone_formatado).values_list('etapa', flat=True).first()
    except Exception:
        pass
    sim_no_fluxo_vender = (mensagem_limpa in ['SIM', 'S'] and etapa_sessao == 'venda_confirmar_matricula')

    chave = _chave_telefone(telefone_formatado_usuario)
    chaves_tentar = _chaves_telefone_variantes(telefone_formatado_usuario) or [chave]
    with _pending_lock:
        pend_cliente = next((_pending_client_confirm.get(k) for k in chaves_tentar if _pending_client_confirm.get(k)), None)
        pend_bio = next((_pending_bio_ok.get(k) for k in chaves_tentar if _pending_bio_ok.get(k)), None)

    if not sim_no_fluxo_vender and pend_cliente and mensagem_limpa in ['SIM', 'S', 'CONFIRMAR']:
        from crm_app.pap_protocolo_confirmacao_envio import gerar_protocolo_confirmacao_envio

        proto_envio = gerar_protocolo_confirmacao_envio()
        try:
            from crm_app.models import PapConfirmacaoCliente

            sessao_id_pend = pend_cliente.get('sessao_id')
            for k in (chaves_tentar or [chave]):
                updated = PapConfirmacaoCliente.objects.filter(
                    celular_cliente=k, confirmado=False, sessao_id=sessao_id_pend
                ).update(confirmado=True, protocolo_confirmacao_envio=proto_envio)
                if updated:
                    logger.info(f"[Webhook] PapConfirmacaoCliente marcado confirmado=True (sessao_id={sessao_id_pend}, celular={k})")
                    break
        except Exception as e:
            logger.warning(f"[Webhook] Erro ao marcar PapConfirmacaoCliente (pend_cliente): {e}", exc_info=True)
        pend_cliente['event'].set()
        try:
            msg_cliente = _texto_confirmacao_cliente_pap(proto_envio)
            WhatsAppService.para_cliente().enviar_mensagem_texto(telefone_formatado, msg_cliente)
        except Exception:
            pass
        return {'status': 'ok', 'mensagem': 'Confirmado pelo cliente'}

    if not sim_no_fluxo_vender and mensagem_limpa in ['SIM', 'S', 'CONFIRMAR']:
        try:
            from crm_app.models import PapConfirmacaoCliente
            from crm_app.pap_protocolo_confirmacao_envio import gerar_protocolo_confirmacao_envio

            chaves = chaves_tentar or [chave]
            with _pending_lock:
                keys_pending = list(_pending_client_confirm.keys())
            logger.info(
                "[Webhook] [DEBUG] Cliente respondeu SIM. Telefone=%s, chaves_tentar=%s, keys_no_pending=%s",
                telefone_formatado, chaves, keys_pending[:20] if len(keys_pending) > 20 else keys_pending,
            )
            for k in chaves:
                pend = _pap_confirmacao_queryset_prioriza_protocolo(
                    PapConfirmacaoCliente.objects.filter(celular_cliente=k, confirmado=False)
                ).first()
                logger.info(f"[Webhook] [DEBUG] Chave '{k}': pendente encontrado={pend is not None}")
                if pend:
                    if pend.sessao_id:
                        sessao_pend_etapa = SessaoWhatsapp.objects.filter(
                            id=pend.sessao_id
                        ).values_list('etapa', flat=True).first()
                        if sessao_pend_etapa != 'venda_aguardando_confirmacao':
                            logger.info(
                                "[Webhook] [DEBUG] Ignorando SIM: pendente da sessão %s (etapa=%s) não está em venda_aguardando_confirmacao",
                                pend.sessao_id, sessao_pend_etapa,
                            )
                            continue
                    proto_envio = gerar_protocolo_confirmacao_envio()
                    pend.confirmado = True
                    pend.protocolo_confirmacao_envio = proto_envio
                    pend.save(update_fields=["confirmado", "protocolo_confirmacao_envio"])
                    logger.info(f"[Webhook] PapConfirmacaoCliente marcado confirmado=True (celular={k}, sessao_id={pend.sessao_id})")
                    try:
                        msg_cliente = _texto_confirmacao_cliente_pap(proto_envio)
                        WhatsAppService.para_cliente().enviar_mensagem_texto(
                            telefone_formatado, msg_cliente
                        )
                    except Exception:
                        pass
                    return {'status': 'ok', 'mensagem': 'Confirmado pelo cliente (BD)'}
            logger.info(f"[Webhook] [DEBUG] Nenhum PapConfirmacaoCliente pendente encontrado para chaves {chaves}")
        except Exception as e:
            logger.warning(f"[Webhook] Erro ao marcar PapConfirmacaoCliente: {e}", exc_info=True)

    if pend_bio and mensagem_limpa in ['BIO OK', 'BIOOK', 'CONSULTAR']:
        pend_bio['event'].set()
        try:
            WhatsAppService().enviar_mensagem_texto(telefone_formatado, "⏳ Consultando biometria...")
        except Exception:
            pass
        return {'status': 'ok', 'mensagem': 'BIO OK recebido'}

    # Verificar se o número está associado a um usuário ativo (em grupo, usar participant_phone)
    usuario_whatsapp = _usuario_ativo_por_telefone(telefone_formatado_usuario)
    if not usuario_whatsapp:
        # Cliente com telefone cadastrado em venda: resposta com dados do pedido + aviso BO/Diretoria
        if mensagem_texto and (mensagem_texto or "").strip():
            try:
                from crm_app.services.whatsapp_ia_config_service import ia_clientes_venda_habilitada

                if ia_clientes_venda_habilitada():
                    from crm_app.cliente_atendimento_ia_service import processar_mensagem_cliente_venda

                    resposta_cliente = processar_mensagem_cliente_venda(
                        telefone_formatado_usuario,
                        (mensagem_texto or "").strip(),
                        origem="WEBHOOK",
                    )
                    if resposta_cliente:
                        try:
                            WhatsAppService.para_cliente().enviar_mensagem_texto(
                                telefone_formatado, resposta_cliente
                            )
                        except Exception as e:
                            logger.exception(
                                "[Webhook] Erro ao enviar resposta atendimento cliente (venda): %s", e
                            )
                        return {
                            'status': 'ok',
                            'mensagem': 'Cliente (venda cadastrada): resposta e aviso BO/Diretoria',
                        }
            except Exception as e:
                logger.warning("[Webhook] Atendimento cliente venda falhou: %s", e, exc_info=True)

        # Contato externo sem venda: IA acolhedora ou fallback profissional.
        from crm_app.services.whatsapp_ia_config_service import ia_contatos_externos_habilitada

        if not ia_contatos_externos_habilitada():
            logger.info("[Webhook] IA contatos externos desabilitada — ignorando %s", telefone_formatado)
            return {'status': 'ok', 'mensagem': 'IA externa desabilitada'}
        mensagem_enviar = None
        try:
            from crm_app.ai_chat_service import responder_com_ia
            mensagem_enviar = responder_com_ia(
                (mensagem_texto or "").strip(),
                nome_vendedor="",
                contexto_externo=True,
            )
        except Exception as e:
            logger.warning("[Webhook] IA para contato externo falhou: %s", e)
        if not mensagem_enviar or not str(mensagem_enviar).strip():
            mensagem_enviar = (
                "Recebemos sua mensagem. Em breve um de nossos analistas retornará o contato. "
                "Agradecemos a compreensão."
            )
        try:
            WhatsAppService().enviar_mensagem_texto(telefone_formatado, mensagem_enviar)
        except Exception as e:
            logger.exception("[Webhook] Erro ao enviar resposta para contato externo: %s", e)
        return {'status': 'ok', 'mensagem': 'Contato externo: resposta enviada'}
    
    # Inicializar serviço WhatsApp
    whatsapp_service = WhatsAppService()
    
    # Buscar ou criar sessão
    sessao, created = SessaoWhatsapp.objects.get_or_create(
        telefone=telefone_formatado,
        defaults={'etapa': 'inicial', 'dados_temp': {}}
    )
    
    # Resetar sessão antiga (mais de 30 minutos sem interação)
    if not created:
        tempo_decorrido = timezone.now() - sessao.updated_at
        if tempo_decorrido.total_seconds() > 1800:  # 30 minutos
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
    
    etapa_atual = sessao.etapa
    dados_temp = sessao.dados_temp or {}

    # Usuário ativo mas não autorizado a chamar no bot: aviso uma vez por dia; no mesmo dia, sem resposta.
    if not getattr(usuario_whatsapp, 'autorizado_chamar_no_bot', True):
        hoje = timezone.localdate()
        if sessao.data_ultimo_aviso_nao_autorizado != hoje:
            try:
                whatsapp_service.enviar_mensagem_texto(
                    telefone_formatado,
                    "Seu usuário não está liberado para acesso ao bot."
                )
            except Exception as e:
                logger.warning(f"[Webhook] Erro ao enviar aviso não autorizado: {e}", exc_info=True)
            SessaoWhatsapp.objects.filter(id=sessao.id).update(data_ultimo_aviso_nao_autorizado=hoje)
        return {'status': 'ok', 'mensagem': 'Usuário não autorizado a chamar no bot'}

    def _enviar_material_record_apoia_da_sessao(caption=None):
        """Envia material Record Apoia da sessão com legenda (sem mensagem de texto separada)."""
        if not sessao:
            return False
        try:
            sessao.refresh_from_db()
        except Exception:
            pass
        material_para_envio = (sessao.dados_temp or {}).get('material_para_envio')
        if not material_para_envio:
            return False
        logger.info("[Webhook] Material detectado, enviando com legenda...")
        enviado = _enviar_material_record_apoia_whatsapp(
            whatsapp_service, telefone_formatado, material_para_envio, caption=caption
        )
        if enviado:
            dados = dict(sessao.dados_temp or {})
            dados.pop('material_para_envio', None)
            sessao.dados_temp = dados
            sessao.save(update_fields=['dados_temp'])
        return enviado

    def _enviar_resposta_e_retornar(resposta_texto):
        """Envia material com legenda; só manda texto separado se não houver mídia ou se o envio falhar."""
        caption = None
        if resposta_texto and str(resposta_texto).strip():
            _elapsed = time.monotonic() - _webhook_t0
            caption = (resposta_texto.strip() + f"\n\n⏱ _{_elapsed:.1f}s_").strip()
        material_enviado = _enviar_material_record_apoia_da_sessao(caption=caption)
        if not material_enviado and caption:
            try:
                ok_envio, resp_envio = whatsapp_service.enviar_mensagem_texto(
                    telefone_formatado, caption
                )
                if not ok_envio:
                    logger.error(
                        "[Webhook] Falha ao enviar resposta para %s: %s",
                        telefone_formatado,
                        resp_envio,
                    )
                else:
                    message_id = None
                    if isinstance(resp_envio, dict):
                        message_id = (
                            resp_envio.get("messageId")
                            or resp_envio.get("zaapId")
                            or resp_envio.get("id")
                        )
                    logger.info(
                        "[Webhook] Resposta enviada para %s messageId=%s",
                        telefone_formatado,
                        message_id,
                    )
            except Exception as e:
                logger.exception(f"[Webhook] Erro ao enviar mensagem ao usuário: {e}")
        return {'status': 'ok', 'mensagem': resposta_texto or 'Processado com sucesso'}

    def _com_prefixo_primeira_mensagem(texto):
        """Prefixa a primeira mensagem após palavra-chave com [Saudação] Nome: (usuario_whatsapp já validado)."""
        return _formatar_primeira_mensagem_automatica(texto, usuario_whatsapp)

    try:
        # Identificar comando ou processar resposta
        resposta = None
        
        # === COMANDOS INICIAIS ===
        logger.info(f"[Webhook] Verificando comando. Mensagem limpa: '{mensagem_limpa}'")
        logger.info(f"[Webhook] Mensagem original: '{mensagem_texto}'")
        logger.info(f"[Webhook] Etapa atual: {etapa_atual}")
        
        # Verificação mais flexível - aceita comandos com ou sem acentuação, maiúsculas/minúsculas
        mensagem_sem_acentos = mensagem_limpa.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')

        # Comandos de comissão (somente Diretoria/Admin no WhatsApp)
        try:
            from crm_app.whatsapp_comissao_service import (
                ETAPA_ADIANT_COMISSAO_INST_ESCOLHA,
                ETAPA_ADIANT_SABADO_ESCOLHA,
                limpar_fluxo_adiant_comissao_inst_sessao,
                limpar_fluxo_adiant_sabado_sessao,
                mensagem_eh_comando_comissao_reservado,
                pode_acesso_comissao_whatsapp_wpp,
                processar_escolha_adiant_comissao_inst_sessao,
                processar_escolha_adiant_sabado_sessao,
                processar_whatsapp_comissao,
            )

            if sessao.etapa == ETAPA_ADIANT_SABADO_ESCOLHA:
                if mensagem_limpa in ['MENU', 'AJUDA', 'HELP', 'OPCOES', 'OPÇÕES', 'OPCOES', 'OPÇOES']:
                    limpar_fluxo_adiant_sabado_sessao(sessao)
                    sessao.refresh_from_db()
                else:
                    _r_esc = processar_escolha_adiant_sabado_sessao(
                        sessao, usuario_whatsapp, mensagem_texto, mensagem_limpa
                    )
                    if _r_esc is not None:
                        sessao.refresh_from_db()
                        return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(_r_esc))

            if sessao.etapa == ETAPA_ADIANT_COMISSAO_INST_ESCOLHA:
                if mensagem_limpa in ['MENU', 'AJUDA', 'HELP', 'OPCOES', 'OPÇÕES', 'OPCOES', 'OPÇOES']:
                    limpar_fluxo_adiant_comissao_inst_sessao(sessao)
                    sessao.refresh_from_db()
                else:
                    _r_ci = processar_escolha_adiant_comissao_inst_sessao(
                        sessao, usuario_whatsapp, mensagem_texto, mensagem_limpa
                    )
                    if _r_ci is not None:
                        sessao.refresh_from_db()
                        return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(_r_ci))

            if pode_acesso_comissao_whatsapp_wpp(usuario_whatsapp):
                _resp_comissao = processar_whatsapp_comissao(
                    usuario_whatsapp, mensagem_texto, mensagem_limpa, sessao=sessao
                )
                if _resp_comissao is not None:
                    sessao.refresh_from_db()
                    return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(_resp_comissao))
            elif mensagem_eh_comando_comissao_reservado(mensagem_texto, mensagem_limpa):
                return _enviar_resposta_e_retornar(
                    _com_prefixo_primeira_mensagem(
                        '❌ Comandos de comissão pelo WhatsApp são restritos a *Diretoria* ou *Admin*.'
                    )
                )
        except Exception as e_com:
            logger.exception("[Webhook] Erro nos comandos de comissão WhatsApp: %s", e_com)

        # Comando FATURA (Nio Negociar / API)
        if mensagem_limpa in ['FATURA', 'FATURAS']:
            logger.info(f"[Webhook] Comando FATURA reconhecido!")
            sessao.etapa = 'fatura_cpf'
            sessao.dados_temp = {}
            sessao.save()
            _registrar_estatistica(telefone_formatado, 'FATURA')
            resposta = "Por favor, digite o CPF do titular da fatura (apenas números):"
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando CONTA (2ª via - site sem reCAPTCHA)
        if mensagem_limpa in ['CONTA', 'CONTAS']:
            logger.info(f"[Webhook] Comando CONTA reconhecido!")
            sessao.etapa = 'conta_cpf'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "Digite o CPF para consultar a conta (2ª via, apenas números):"
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando VIABILIDADE
        if mensagem_limpa in ['VIABILIDADE', 'VIABILIDADES']:
            logger.info(f"[Webhook] Comando VIABILIDADE reconhecido!")
            sessao.etapa = 'viabilidade_cep'
            sessao.dados_temp = {}
            sessao.save()
            _registrar_estatistica(telefone_formatado, 'VIABILIDADE')
            resposta = "Por favor, digite o CEP do endereço para consulta de viabilidade (apenas números):"
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando NOVA VENDA (cadastrar venda no CRM via WhatsApp)
        if mensagem_limpa in ['NOVA VENDA', 'CADASTRAR VENDA', 'CADASTRO VENDA']:
            logger.info(f"[Webhook] Comando NOVA VENDA reconhecido!")
            sessao.etapa = 'cadastro_venda_origem'
            sessao.dados_temp = {'vendedor_id': usuario_whatsapp.id}
            sessao.save()
            resposta = ("📋 *Cadastro de Venda no CRM*\n\n"
                        "A venda é *Via APP* ou *Sem APP*?\n\n"
                        "Responda: *APP* ou *SEM APP*\n"
                        "(Digite *CANCELAR* para sair)")
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando INCLUSÃO (solicitar viabilidade via formulário) — exige autorização por usuário
        if mensagem_limpa in ['INCLUSAO', 'INCLUSÃO', 'INCLUSAO']:
            try:
                usuario_whatsapp = _buscar_usuario_por_telefone(telefone_formatado)
                if not getattr(usuario_whatsapp, 'autorizar_inclusao_wpp', False):
                    resposta = (
                        "❌ *ACESSO NEGADO*\n\n"
                        "Você não está autorizado a usar Inclusão/Viabilidade pelo WhatsApp.\n"
                        "Solicite que marquem a opção 'Autorizar Inclusão/Viabilidade pelo Wpp' no seu cadastro."
                    )
                    return _enviar_resposta_e_retornar(resposta)
            except Exception as e:
                # Coluna autorizar_inclusao_wpp pode não existir se a migration ainda não foi aplicada
                if 'autorizar_inclusao_wpp' in str(e):
                    logger.warning("[Webhook] Erro ao verificar autorizar_inclusao_wpp (migration pendente?): %s", e)
                else:
                    raise
            logger.info(f"[Webhook] Comando INCLUSÃO reconhecido!")
            sessao.etapa = 'inclusao_cep'
            sessao.dados_temp = {}
            sessao.save()
            resposta = ("📋 *Solicitação de Viabilidade (Inclusão)*\n\n"
                        "Digite o *CEP* do endereço (apenas números).\n"
                        "Ou digite *CANCELAR* para sair.")
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando STATUS
        if mensagem_limpa in ['STATUS', 'SITUACAO', 'SITUAÇÃO']:
            logger.info(f"[Webhook] Comando STATUS reconhecido!")
            # Se já existe uma consulta online em andamento, não reinicia o fluxo (evita misturar respostas)
            try:
                if sessao.etapa == 'status_aguardando_online':
                    dados_online = sessao.dados_temp or {}
                    started_at = float(dados_online.get('status_online_started_at') or 0)
                    tempo_espera = time.time() - started_at if started_at else 0
                    if started_at and tempo_espera > STATUS_ONLINE_MAX_WAIT_SECONDS:
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        resposta = (
                            "❌ Não foi possível concluir a conexão com o PAP a tempo.\n\n"
                            "Digite *STATUS* para tentar novamente."
                        )
                    else:
                        resposta = "⏳ Consultando status online no PAP... Aguarde. Você receberá a resposta em seguida."
                    return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))
            except Exception:
                pass
            sessao.etapa = 'status_documento'
            sessao.dados_temp = {}
            sessao.save()
            _registrar_estatistica(telefone_formatado, 'STATUS')
            resposta = _MSG_STATUS_PEDIR_IDENTIFICADOR
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))
        # FACHADA desativada: redireciona para DFV (sem registrar estatística nem abrir fluxo)
        if etapa_atual == 'inicial' and ('FACHADA' in mensagem_limpa or 'FACADA' in mensagem_limpa):
            logger.info("[Webhook] Comando FACHADA reconhecido (desativado → DFV)")
            resposta = (
                "A consulta de fachadas agora é pelo *DFV*.\n"
                "Envie *DFV* no chat para consultar online a base de viabilidade da Nio."
            )
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # DFV: consulta ao vivo no Power BI por CEP
        if etapa_atual == 'inicial' and mensagem_limpa == 'DFV':
            logger.info("[Webhook] Comando DFV reconhecido!")
            from django.conf import settings as _dfv_settings

            if not getattr(_dfv_settings, 'DFV_POWERBI_ENABLED', True):
                resposta = (
                    "⚠️ A consulta *DFV* (Power BI ao vivo) está temporariamente indisponível.\n"
                    "Tente novamente em instantes ou use *CDOE* se souber o código do CDO."
                )
                return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

            sessao.etapa = 'dfv_cep'
            sessao.dados_temp = {}
            sessao.save()
            _registrar_estatistica(telefone_formatado, 'DFV')
            resposta = (
                "Por favor, digite o *CEP* para consultar fachadas no Power BI ao vivo "
                "(Sudeste, SP e Sul — apenas números; hífen é aceito):"
            )
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # CDOE: consulta ao vivo no Power BI por CODIGO_CDO (código → UF → cidade? → rua → números)
        if etapa_atual == 'inicial' and (
            mensagem_limpa == 'CDOE' or mensagem_limpa.startswith('CDOE ')
        ):
            logger.info("[Webhook] Comando CDOE reconhecido!")
            from django.conf import settings as _dfv_settings

            if not getattr(_dfv_settings, 'DFV_POWERBI_ENABLED', True):
                resposta = (
                    "⚠️ A consulta *CDOE* (Power BI ao vivo) está temporariamente indisponível.\n"
                    "Tente novamente em instantes ou use *DFV* com o CEP."
                )
                return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

            codigo_inline = mensagem_limpa[4:].strip() if mensagem_limpa.startswith('CDOE ') else ''
            _registrar_estatistica(telefone_formatado, 'CDOE')

            if codigo_inline:
                from crm_app.services.dfv_powerbi_service import CDOE_UFS, limpar_codigo_cdo

                codigo_limpo = limpar_codigo_cdo(codigo_inline)
                if not codigo_limpo:
                    resposta = (
                        "❌ Código inválido. Digite *CDOE* e informe o código "
                        "(ex.: 28005 ou CDOE-28005)."
                    )
                    return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))
                sessao.etapa = 'cdoe_uf'
                sessao.dados_temp = {'cdoe_codigo_informado': codigo_limpo}
                sessao.save()
                resposta = (
                    f"Código *{codigo_limpo}* anotado.\n"
                    "Agora escolha o *estado (UF)* da consulta:\n"
                    f"• {'  • '.join(f'*{uf}*' for uf in CDOE_UFS)}\n\n"
                    "Ou *CANCELAR* para sair."
                )
                texto_uf = _com_prefixo_primeira_mensagem(resposta)
                try:
                    opcoes_uf = [
                        {
                            "id": f"cdoe_uf_{uf}",
                            "title": uf,
                            "description": f"Consultar CDOE em {uf}",
                        }
                        for uf in CDOE_UFS
                    ]
                    ok_lista, _ = whatsapp_service.enviar_lista_opcoes(
                        telefone_formatado,
                        texto_uf,
                        opcoes_uf,
                        titulo_lista="Estados (UF)",
                        botao_label="Escolher UF",
                    )
                    if ok_lista:
                        return {'status': 'ok', 'mensagem': resposta}
                except Exception:
                    logger.debug("[Webhook] Falha lista UF CDOE", exc_info=True)
                return _enviar_resposta_e_retornar(texto_uf)
            else:
                sessao.etapa = 'cdoe_codigo'
                sessao.dados_temp = {}
                sessao.save()
                resposta = (
                    "Digite o *número/código da CDOE*.\n"
                    "Ex.: *28005* ou *CDOE-28005*\n\n"
                    "Ou envie *CANCELAR* para sair."
                )
                return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando MATERIAL
        if mensagem_limpa in ['MATERIAL', 'MATERIAIS']:
            logger.info(f"[Webhook] Comando MATERIAL reconhecido!")
            sessao.etapa = 'material_buscar'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "Digite a palavra-chave para buscar materiais ou documentos (ex: boleto, contrato, instalacao):"
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Comando RECORD APOIA / APOIA (repositório de arquivos - mesmo fluxo que Material)
        if mensagem_limpa in ['APOIA', 'RECORD APOIA', 'RECORDAPOIA']:
            logger.info(f"[Webhook] Comando RECORD APOIA/APOIA reconhecido!")
            sessao.etapa = 'material_buscar'
            sessao.dados_temp = {}
            sessao.save()
            resposta = (
                "📁 *Record Apoia* – Buscar arquivos/materiais\n\n"
                "Digite a *palavra-chave* para buscar (ex: Globoplay, boleto, contrato, instalacao):"
            )
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))
        
        elif mensagem_limpa in ['ANDAMENTO', 'ANDAMENTOS']:
            logger.info(f"[Webhook] Comando ANDAMENTO reconhecido!")
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            resposta = consultar_andamento_agendamentos(telefone_formatado)
            _registrar_estatistica(telefone_formatado, 'ANDAMENTO')
            if resposta is None:
                resposta = "Nenhum agendamento encontrado para hoje."
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))
        
        elif mensagem_limpa in ['CREDITO', 'CRÉDITO']:
            logger.info(f"[Webhook] Comando CRÉDITO reconhecido!")
            resposta = _iniciar_fluxo_credito(telefone_formatado, sessao)
            _registrar_estatistica(telefone_formatado, 'CREDITO')
            if not resposta:
                resposta = "Não foi possível iniciar o fluxo. Tente novamente."
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        elif mensagem_limpa in ['VENDER', 'VENDA', 'NOVA VENDA']:
            logger.info(f"[Webhook] Comando VENDER reconhecido!")
            resposta = _iniciar_fluxo_venda(telefone_formatado, sessao)
            _registrar_estatistica(telefone_formatado, 'VENDER')
            if not resposta:
                resposta = "Não foi possível iniciar o fluxo de venda. Tente novamente."
            try:
                sessao.refresh_from_db()
            except Exception:
                pass
            _elapsed_v = time.monotonic() - _webhook_t0
            texto_vender = (
                _com_prefixo_primeira_mensagem(resposta).strip() + f"\n\n⏱ _{_elapsed_v:.1f}s_"
            ).strip()
            alt_v = _venda_tentar_enviar_resposta_com_botoes(telefone_formatado, sessao, texto_vender)
            if alt_v is None:
                return {'status': 'ok', 'mensagem': resposta}
            try:
                whatsapp_service.enviar_mensagem_texto(telefone_formatado, alt_v.strip())
            except Exception as e:
                logger.exception(f"[Webhook] Erro ao enviar VENDER (fallback texto): {e}")
            return {'status': 'ok', 'mensagem': resposta}

        elif mensagem_limpa in ['ROUBO']:
            logger.info("[Webhook] Comando ROUBO reconhecido!")
            sessao.etapa = 'roubo_identificador'
            sessao.dados_temp = {'roubo': {}}
            sessao.save()
            resposta = (
                "Entendi. Para abrir o alerta, informe o *CPF* ou a *O.S.* (somente numeros)."
            )
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        elif mensagem_limpa in ['PEDIDO', 'PEDIDOS']:
            logger.info(f"[Webhook] Comando PEDIDO reconhecido!")
            resposta = _iniciar_fluxo_pedido(telefone_formatado, sessao)
            _registrar_estatistica(telefone_formatado, 'PEDIDO')
            if not resposta:
                resposta = "Não foi possível iniciar o fluxo. Tente novamente."
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        elif mensagem_limpa in ['BIO', 'BIOMETRIA']:
            logger.info("[Webhook] Comando BIO reconhecido!")
            resposta = _iniciar_fluxo_bio(telefone_formatado, sessao)
            _registrar_estatistica(telefone_formatado, 'BIO')
            if not resposta:
                resposta = "Não foi possível iniciar o fluxo. Tente novamente."
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))
        
        elif mensagem_limpa in ['MENU', 'AJUDA', 'HELP', 'OPCOES', 'OPÇÕES', 'OPCOES', 'OPÇOES']:
            logger.info(f"[Webhook] Comando MENU/AJUDA reconhecido!")
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            from crm_app.whatsapp_comissao_service import pode_acesso_comissao_whatsapp_wpp

            linhas_menu = [
                "📋 *MENU*\n\n",
                "Escolha uma opção:\n",
                "• *DFV* - Consultar fachadas por CEP (Power BI ao vivo)\n",
                "• *CDOE* - Consultar endereços por código do CDO (Power BI)\n",
                "• *Viabilidade* - Consultar viabilidade por CEP e número\n",
                "• *Inclusão* - Solicitar viabilidade (formulário)\n",
                "• *Status* - Consultar status de pedido\n",
                "• *Fatura* - Consultar fatura por CPF (Nio Negociar)\n",
                "• *Conta* - 2ª via de conta por CPF (site Nio)\n",
                "• *Material* - Buscar materiais/documentos\n",
                "• *Apoia* - Record Apoia (buscar arquivos por palavra-chave)\n",
                "• *Andamento* - Ver agendamentos do dia\n",
                "• *Crédito* - Consultar análise de crédito por CPF\n",
                "• *Pedido* - Consultar pedido/O.S. por CPF no PAP\n",
                "• *Bio* - Consultar resultado da biometria no Br Pronto\n",
                "• *Vender* - Realizar venda pelo WhatsApp 🆕\n",
                "• *Nova Venda* - Cadastrar venda no CRM (Via APP ou Sem APP)",
            ]
            if pode_acesso_comissao_whatsapp_wpp(usuario_whatsapp):
                linhas_menu.append(
                    "\n• *Comissao* - Bônus, desconto, adiant. comissão/sábado (digite *COMISSAO* para ajuda)"
                )
            resposta = ''.join(linhas_menu)
            return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta))

        # Mensagem livre na etapa inicial: pode ser busca de material (Record Apoia) ou dúvida (IA).
        # Se parecer pergunta/dúvida ou pedido de planos Nio, tentar a IA primeiro; senão tentar Record Apoia e depois IA como fallback.
        _mensagem_strip = (mensagem_texto or "").strip()
        _msg_lower = _mensagem_strip.lower()
        _parece_pergunta = (
            len(_mensagem_strip) >= 2
            and (
                "?" in _mensagem_strip
                or "dúvida" in _msg_lower
                or "duvida" in _msg_lower
                or "como " in _msg_lower
                or "qual " in _msg_lower
                or "quero saber" in _msg_lower
                or "instalou" in _msg_lower
                or "status do pedido" in _msg_lower
                or "plano" in _msg_lower
                or "planos" in _msg_lower
                or "liste" in _msg_lower
                or "listar" in _msg_lower
                or "características" in _msg_lower
                or "caracteristicas" in _msg_lower
                or ("nio" in _msg_lower and ("varejo" in _msg_lower or "empresarial" in _msg_lower))
            )
        )
        if etapa_atual == 'inicial' and _mensagem_strip and _parece_pergunta:
            try:
                from crm_app.services.whatsapp_ia_config_service import ia_vendedores_duvidas_habilitada

                if ia_vendedores_duvidas_habilitada():
                    from crm_app.ai_chat_service import responder_com_ia
                    nome_vendedor = (usuario_whatsapp.get_full_name() or usuario_whatsapp.username or "").strip() or None
                    resposta_ia = responder_com_ia(_mensagem_strip, nome_vendedor=nome_vendedor)
                    if resposta_ia:
                        logger.info("[Webhook] Resposta enviada via IA (mensagem identificada como pergunta).")
                        return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta_ia))
                    # IA não respondeu (sem chave ou cota excedida) → mensagem de fallback
                    resposta_fallback = (
                        "No momento não consigo responder dúvidas por aqui. "
                        "Digite *MENU* para ver os comandos disponíveis ou fale com seu gestor."
                    )
                    return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta_fallback))
            except Exception as e:
                logger.warning("[Webhook] Fallback IA (pergunta) falhou: %s", e)
        # Busca direta por tag do Record Apoia (sem precisar digitar Material/Apoia)
        if etapa_atual == 'inicial' and mensagem_texto and len(mensagem_texto.strip()) >= 2:
            try:
                logger.info(f"[Webhook] Busca direta por tag Record Apoia: \"{mensagem_texto.strip()}\"")
                resposta_busca = _buscar_record_apoia_por_texto(mensagem_texto.strip(), sessao)
                if resposta_busca is not None:
                    return _enviar_resposta_e_retornar(_com_prefixo_primeira_mensagem(resposta_busca))
            except Exception as e:
                logger.exception("[Webhook] Erro na busca direta Record Apoia: %s", e)
        
        # === PROCESSAMENTO POR ETAPA ===
        elif etapa_atual.startswith('roubo_'):
            dt = sessao.dados_temp or {}
            dados_roubo = dict(dt.get('roubo') or {})

            if etapa_atual == 'roubo_identificador':
                ident = re.sub(r'\D', '', mensagem_texto or '')
                if not ident:
                    resposta = "Nao consegui identificar. Envie o *CPF* ou a *O.S.* (somente numeros)."
                    return _enviar_resposta_e_retornar(resposta)

                tipo = 'cpf' if len(ident) == 11 else 'os'
                dados_roubo['tipo_identificador'] = tipo
                dados_roubo['identificador'] = ident
                sessao.etapa = 'roubo_print'
                sessao.dados_temp = {**dt, 'roubo': dados_roubo}
                sessao.save()
                resposta = "Agora envie um *print da conversa do WhatsApp*."
                return _enviar_resposta_e_retornar(resposta)

            if etapa_atual == 'roubo_print':
                url_anexo = (image_url or document_url or '').strip()
                if not url_anexo:
                    resposta = "Preciso do print para continuar. Envie a *imagem/arquivo* da conversa."
                    return _enviar_resposta_e_retornar(resposta)

                dados_roubo['print_url'] = url_anexo
                dados_roubo['print_tipo'] = 'imagem' if image_url else 'documento'
                sessao.etapa = 'roubo_tem_mais'
                sessao.dados_temp = {**dt, 'roubo': dados_roubo}
                sessao.save()
                resposta = "Tem mais alguma informacao? Responda *SIM* ou *NAO*."
                return _enviar_resposta_e_retornar(resposta)

            if etapa_atual == 'roubo_tem_mais':
                if mensagem_limpa in ['SIM', 'S']:
                    ok_gc, detalhe = _enviar_relato_roubo_para_gc(
                        sessao=sessao,
                        telefone_formatado_usuario=telefone_formatado_usuario,
                        usuario_whatsapp=usuario_whatsapp,
                    )
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    if ok_gc:
                        resposta = "Perfeito. Dados consolidados e enviados ao *GC*."
                    else:
                        resposta = f"Registro concluido, mas nao consegui enviar ao GC agora. Motivo: {detalhe}"
                    return _enviar_resposta_e_retornar(resposta)

                if mensagem_limpa in ['NAO', 'NÃO', 'N']:
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    resposta = "Certo, fluxo encerrado sem envio ao GC."
                    return _enviar_resposta_e_retornar(resposta)

                resposta = "Responda apenas *SIM* ou *NAO*."
                return _enviar_resposta_e_retornar(resposta)

            resposta = "Digite *ROUBO* para iniciar novamente."
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'fachada_cep':
            # Sessões antigas ainda na etapa fachada_cep: redireciona para DFV
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            resposta = (
                "A consulta de fachadas agora é pelo *DFV*.\n"
                "Envie *DFV* no chat para consultar online a base de viabilidade da Nio."
            )
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'dfv_cep':
            from crm_app.services.dfv_powerbi_service import (
                DfvPowerBiDisabled,
                DfvPowerBiError,
                DfvPowerBiTimeout,
                consultar_fachadas_por_cep,
                formatar_resposta_dfv_powerbi,
                limpar_cep as limpar_cep_dfv,
            )

            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_resposta_e_retornar("Consulta *DFV* cancelada.")

            cep_limpo = limpar_cep_dfv(mensagem_texto)
            if len(cep_limpo) != 8:
                resposta = (
                    "❌ CEP inválido. Digite o CEP completo com 8 dígitos "
                    "(hífen é aceito, ex.: 30130-000):"
                )
                return _enviar_resposta_e_retornar(resposta)

            logger.info("[Webhook] DFV Power BI — consultando CEP=%s", cep_limpo)
            try:
                # Aviso rápido para não parecer travado (consulta pode levar alguns segundos)
                try:
                    whatsapp_service.enviar_mensagem_texto(
                        telefone_formatado,
                        f"🔎 Consultando Power BI ao vivo para o CEP *{cep_limpo}*...",
                    )
                except Exception:
                    logger.debug("[Webhook] Falha ao enviar aviso DFV", exc_info=True)

                registros = consultar_fachadas_por_cep(cep_limpo)
                partes = formatar_resposta_dfv_powerbi(cep_limpo, registros)
            except DfvPowerBiDisabled:
                partes = [
                    "⚠️ A consulta *DFV* (Power BI ao vivo) está temporariamente indisponível.\n"
                    "Tente novamente em instantes ou use *CDOE* se souber o código do CDO."
                ]
            except DfvPowerBiTimeout:
                partes = [
                    "❌ Não foi possível consultar o Power BI agora (tempo esgotado).\n"
                    "Tente novamente em instantes ou use *CDOE* se souber o código do CDO."
                ]
            except DfvPowerBiError as exc:
                logger.warning("[Webhook] DFV Power BI erro CEP=%s: %s", cep_limpo, exc)
                partes = [
                    "❌ Não foi possível consultar o Power BI agora.\n"
                    "Tente novamente em instantes ou use *CDOE* se souber o código do CDO."
                ]
            except Exception as exc:
                logger.exception("[Webhook] DFV Power BI falha inesperada CEP=%s: %s", cep_limpo, exc)
                partes = [
                    "❌ Não foi possível consultar o Power BI agora.\n"
                    "Tente novamente em instantes."
                ]

            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()

            # Envia fatiado (mensagens longas) — sem misturar com base local
            for idx, parte in enumerate(partes):
                texto = parte if idx > 0 else _com_prefixo_primeira_mensagem(parte)
                try:
                    _elapsed = time.monotonic() - _webhook_t0
                    if idx == len(partes) - 1:
                        texto = (texto.strip() + f"\n\n⏱ _{_elapsed:.1f}s_").strip()
                    whatsapp_service.enviar_mensagem_texto(telefone_formatado, texto)
                except Exception as e:
                    logger.exception("[Webhook] Erro ao enviar parte DFV %s: %s", idx + 1, e)
            return {'status': 'ok', 'mensagem': partes[0] if partes else 'ok'}

        elif etapa_atual in (
            'cdoe_codigo',
            'cdoe_uf',
            'cdoe_escolher_cidade',
            'cdoe_escolher_rua',
        ):
            from crm_app.services.dfv_powerbi_service import (
                CDOE_UFS,
                DfvPowerBiDisabled,
                DfvPowerBiError,
                DfvPowerBiTimeout,
                consultar_fachadas_por_cdo,
                filtrar_grupos_por_cidade,
                formatar_numeros_rua_cdoe,
                formatar_pedido_cidade_cdoe,
                formatar_resumo_cdoe,
                limpar_codigo_cdo,
                limpar_uf,
                listar_cidades_cdoe,
                montar_grupos_rua_cdoe,
                resolver_cidade_escolhida,
            )

            def _enviar_partes_cdoe(partes_msg, prefixar_primeira: bool = True):
                for idx, parte in enumerate(partes_msg):
                    texto = (
                        _com_prefixo_primeira_mensagem(parte)
                        if prefixar_primeira and idx == 0
                        else parte
                    )
                    try:
                        _elapsed = time.monotonic() - _webhook_t0
                        if idx == len(partes_msg) - 1:
                            texto = (texto.strip() + f"\n\n⏱ _{_elapsed:.1f}s_").strip()
                        whatsapp_service.enviar_mensagem_texto(telefone_formatado, texto)
                    except Exception as e:
                        logger.exception("[Webhook] Erro ao enviar parte CDOE %s: %s", idx + 1, e)
                return {'status': 'ok', 'mensagem': partes_msg[0] if partes_msg else 'ok'}

            def _pedir_uf_cdoe(codigo_ref: str, prefixar: bool = True):
                resposta_uf = (
                    f"Código *{codigo_ref}* anotado.\n"
                    "Agora escolha o *estado (UF)* da consulta:\n"
                    f"• {'  • '.join(f'*{uf}*' for uf in CDOE_UFS)}\n\n"
                    "Ou *CANCELAR* para sair."
                )
                texto_uf = (
                    _com_prefixo_primeira_mensagem(resposta_uf) if prefixar else resposta_uf
                )
                try:
                    opcoes_uf = [
                        {
                            "id": f"cdoe_uf_{uf}",
                            "title": uf,
                            "description": f"Consultar CDOE em {uf}",
                        }
                        for uf in CDOE_UFS
                    ]
                    ok_lista, _ = whatsapp_service.enviar_lista_opcoes(
                        telefone_formatado,
                        texto_uf,
                        opcoes_uf,
                        titulo_lista="Estados (UF)",
                        botao_label="Escolher UF",
                    )
                    if ok_lista:
                        return {'status': 'ok', 'mensagem': resposta_uf}
                except Exception:
                    logger.debug("[Webhook] Falha lista UF CDOE", exc_info=True)
                return _enviar_resposta_e_retornar(texto_uf)

            def _apos_consulta_cdoe(codigo_encontrado: str, uf_val: str, registros):
                grupos = montar_grupos_rua_cdoe(registros)
                if not grupos:
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    return _enviar_partes_cdoe(
                        formatar_resumo_cdoe(codigo_encontrado, [])
                    )

                cidades = listar_cidades_cdoe(grupos)
                if len(cidades) > 1:
                    sessao.etapa = 'cdoe_escolher_cidade'
                    sessao.dados_temp = {
                        'cdoe_codigo': codigo_encontrado,
                        'cdoe_uf': uf_val,
                        'cdoe_cidades': cidades,
                        'cdoe_grupos': grupos,
                    }
                    sessao.save()
                    partes_cid = formatar_pedido_cidade_cdoe(
                        codigo_encontrado, uf_val, cidades
                    )
                    # Tenta lista interativa (botão) com as cidades reais do Power BI
                    try:
                        opcoes = [
                            {
                                "id": f"cdoe_cid_{i}",
                                "title": str(c)[:24],
                                "description": f"{uf_val} — opção {i}",
                            }
                            for i, c in enumerate(cidades[:10], start=1)
                        ]
                        ok_lista, _ = whatsapp_service.enviar_lista_opcoes(
                            telefone_formatado,
                            partes_cid[0],
                            opcoes,
                            titulo_lista="Cidades",
                            botao_label="Escolher cidade",
                        )
                        if ok_lista:
                            # Se a lista couber em 1 mensagem e a lista API enviou o texto, ok
                            for extra in partes_cid[1:]:
                                whatsapp_service.enviar_mensagem_texto(
                                    telefone_formatado, extra
                                )
                            return {'status': 'ok', 'mensagem': partes_cid[0]}
                    except Exception:
                        logger.debug(
                            "[Webhook] Lista cidades CDOE indisponível; usa texto",
                            exc_info=True,
                        )
                    return _enviar_partes_cdoe(partes_cid)

                # Uma cidade só — vai direto para ruas
                sessao.etapa = 'cdoe_escolher_rua'
                sessao.dados_temp = {
                    'cdoe_codigo': codigo_encontrado,
                    'cdoe_uf': uf_val,
                    'cdoe_grupos': grupos,
                }
                sessao.save()
                return _enviar_partes_cdoe(formatar_resumo_cdoe(codigo_encontrado, grupos))

            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_resposta_e_retornar("Consulta *CDOE* cancelada.")

            if etapa_atual == 'cdoe_escolher_rua':
                dados_cdoe = sessao.dados_temp or {}
                grupos = dados_cdoe.get('cdoe_grupos') or []
                codigo_cdo = dados_cdoe.get('cdoe_codigo') or ''
                try:
                    idx_rua = int(re.sub(r'\D', '', mensagem_limpa) or '0')
                except ValueError:
                    idx_rua = 0
                if idx_rua < 1 or idx_rua > len(grupos):
                    resposta = (
                        f"❌ Opção inválida. Digite o *número da rua* (1 a {len(grupos)}) "
                        "ou *CANCELAR* para sair."
                    )
                    return _enviar_resposta_e_retornar(resposta)

                grupo = grupos[idx_rua - 1]
                partes = formatar_numeros_rua_cdoe(codigo_cdo, grupo)
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_partes_cdoe(partes)

            if etapa_atual == 'cdoe_escolher_cidade':
                dados_cdoe = sessao.dados_temp or {}
                cidades = dados_cdoe.get('cdoe_cidades') or []
                grupos = dados_cdoe.get('cdoe_grupos') or []
                codigo_cdo = dados_cdoe.get('cdoe_codigo') or ''
                cidade = resolver_cidade_escolhida(mensagem_texto or mensagem_limpa, cidades)
                if not cidade:
                    resposta = (
                        f"❌ Cidade inválida. Digite o *número* (1 a {len(cidades)}) "
                        "ou o nome da cidade, ou *CANCELAR*."
                    )
                    return _enviar_resposta_e_retornar(resposta)
                grupos_cid = filtrar_grupos_por_cidade(grupos, cidade)
                sessao.etapa = 'cdoe_escolher_rua'
                sessao.dados_temp = {
                    'cdoe_codigo': codigo_cdo,
                    'cdoe_uf': dados_cdoe.get('cdoe_uf') or '',
                    'cdoe_grupos': grupos_cid,
                }
                sessao.save()
                return _enviar_partes_cdoe(formatar_resumo_cdoe(codigo_cdo, grupos_cid))

            if etapa_atual == 'cdoe_codigo':
                codigo_limpo = limpar_codigo_cdo(mensagem_texto)
                if not codigo_limpo:
                    resposta = (
                        "❌ Código inválido. Digite o número/código da CDOE "
                        "(ex.: *28005* ou *CDOE-28005*), ou *CANCELAR*:"
                    )
                    return _enviar_resposta_e_retornar(resposta)
                sessao.etapa = 'cdoe_uf'
                sessao.dados_temp = {'cdoe_codigo_informado': codigo_limpo}
                sessao.save()
                return _pedir_uf_cdoe(codigo_limpo, prefixar=False)

            # etapa cdoe_uf
            uf_limpo = limpar_uf(mensagem_limpa or mensagem_texto)
            if not uf_limpo:
                resposta = (
                    "❌ UF inválida. Escolha uma destas: "
                    f"*{', '.join(CDOE_UFS)}*, ou *CANCELAR*."
                )
                return _enviar_resposta_e_retornar(resposta)

            codigo_informado = (sessao.dados_temp or {}).get('cdoe_codigo_informado') or ''
            if not codigo_informado:
                sessao.etapa = 'cdoe_codigo'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_resposta_e_retornar(
                    "Digite novamente o *código da CDOE* (ex.: 28005):"
                )

            logger.info(
                "[Webhook] CDOE Power BI — codigo=%s UF=%s",
                codigo_informado,
                uf_limpo,
            )
            try:
                try:
                    whatsapp_service.enviar_mensagem_texto(
                        telefone_formatado,
                        f"🔎 Consultando Power BI para *{codigo_informado}* em *{uf_limpo}*...",
                    )
                except Exception:
                    logger.debug("[Webhook] Falha ao enviar aviso CDOE", exc_info=True)

                registros, codigo_encontrado = consultar_fachadas_por_cdo(
                    codigo_informado, uf=uf_limpo
                )
            except DfvPowerBiDisabled:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_partes_cdoe(
                    [
                        "⚠️ A consulta *CDOE* (Power BI ao vivo) está temporariamente indisponível.\n"
                        "Tente novamente em instantes ou use *DFV* com o CEP."
                    ]
                )
            except DfvPowerBiTimeout:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_partes_cdoe(
                    [
                        "❌ Não foi possível consultar o Power BI agora (tempo esgotado).\n"
                        "Tente novamente em instantes ou use *DFV* com o CEP."
                    ]
                )
            except DfvPowerBiError as exc:
                logger.warning(
                    "[Webhook] CDOE Power BI erro codigo=%s: %s", codigo_informado, exc
                )
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_partes_cdoe(
                    [
                        "❌ Não foi possível consultar o Power BI agora.\n"
                        "Tente novamente em instantes ou use *DFV* com o CEP."
                    ]
                )
            except Exception as exc:
                logger.exception(
                    "[Webhook] CDOE falha inesperada codigo=%s: %s",
                    codigo_informado,
                    exc,
                )
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_partes_cdoe(
                    [
                        "❌ Não foi possível consultar o Power BI agora.\n"
                        "Tente novamente em instantes."
                    ]
                )

            return _apos_consulta_cdoe(codigo_encontrado, uf_limpo, registros)
        
        elif etapa_atual == 'viabilidade_cep':
            cep_limpo = limpar_texto_cep_cpf(mensagem_texto)
            if not cep_limpo or len(cep_limpo) < 8:
                resposta = "❌ CEP inválido. Por favor, digite o CEP completo:"
            else:
                sessao.etapa = 'viabilidade_numero'
                sessao.dados_temp = {'cep': cep_limpo}
                sessao.save()
                resposta = "Ok (Modo Mapa)! Agora digite o NÚMERO da fachada para localizarmos no mapa:"
        
        elif etapa_atual == 'viabilidade_numero':
            numero = mensagem_texto.strip()
            cep = dados_temp.get('cep', '')
            if not numero:
                resposta = "❌ Número inválido. Por favor, digite o número da fachada:"
            else:
                logger.info(f"[Webhook] Consultando viabilidade: CEP={cep}, Num={numero}")
                resultado_viabilidade = consultar_viabilidade_kmz(cep, numero)
                resposta = f"🛰️ Geolocalizando e analisando mancha (KMZ)...\n\n{resultado_viabilidade}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()

        # --- CADASTRO DE VENDA NO CRM (Nova Venda via WhatsApp) ---
        elif etapa_atual.startswith('cadastro_venda_'):
            if mensagem_limpa == 'CANCELAR':
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "Cadastro de venda cancelado. Digite *MENU* para ver as opções."
                return _enviar_resposta_e_retornar(resposta)

            from crm_app.cadastro_venda_whatsapp import (
                validar_cpf_ou_cnpj_whatsapp,
                validar_telefone_brasil,
                consultar_viacep_whatsapp,
                cadastrar_venda_crm,
            )
            from crm_app.models import Plano, FormaPagamento

            dt = sessao.dados_temp
            forma_entrada = dt.get('forma_entrada', '')
            eh_sem_app = forma_entrada == 'SEM_APP'

            # --- Origem: APP ou SEM_APP ---
            if etapa_atual == 'cadastro_venda_origem':
                if 'APP' in mensagem_limpa and 'SEM' not in mensagem_limpa:
                    sessao.etapa = 'cadastro_venda_fixo'
                    sessao.dados_temp = {**dt, 'forma_entrada': 'APP'}
                    sessao.save()
                    resposta = "A venda tem *telefone fixo*? Responda *SIM* ou *NAO*:"
                elif 'SEM' in mensagem_limpa and 'APP' in mensagem_limpa:
                    sessao.etapa = 'cadastro_venda_fixo'
                    sessao.dados_temp = {**dt, 'forma_entrada': 'SEM_APP'}
                    sessao.save()
                    resposta = "A venda tem *telefone fixo*? Responda *SIM* ou *NAO*:"
                else:
                    resposta = "Responda *APP* (Via APP) ou *SEM APP* (Sem APP):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Tem fixo ---
            if etapa_atual == 'cadastro_venda_fixo':
                tem_fixo = mensagem_limpa in ['SIM', 'S']
                sessao.dados_temp = {**dt, 'tem_fixo': tem_fixo}
                # Perguntar "Gerada O.S. automática?" apenas se o usuário tem a opção no cadastro (autorizar_venda_automatica)
                from usuarios.models import Usuario as UsuarioModel
                try:
                    mostrar_gerada_os = bool(UsuarioModel.objects.filter(pk=usuario_whatsapp.pk).values_list('autorizar_venda_automatica', flat=True).first())
                except Exception:
                    mostrar_gerada_os = False
                if mostrar_gerada_os:
                    sessao.etapa = 'cadastro_venda_gerada_os'
                    sessao.save()
                    resposta = "Foi *Gerada O.S. automática*? Responda *SIM* ou *NAO*:"
                else:
                    sessao.dados_temp = {**sessao.dados_temp, 'gerada_os_automatica': False}
                    sessao.etapa = 'cadastro_venda_cpf'
                    sessao.save()
                    resposta = "Digite o *CPF ou CNPJ* do cliente (apenas números):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Gerada O.S. automática ---
            if etapa_atual == 'cadastro_venda_gerada_os':
                gerada = mensagem_limpa in ['SIM', 'S']
                sessao.dados_temp = {**dt, 'gerada_os_automatica': gerada}
                sessao.etapa = 'cadastro_venda_cpf'
                sessao.save()
                resposta = "Digite o *CPF ou CNPJ* do cliente (apenas números):"
                return _enviar_resposta_e_retornar(resposta)

            # --- CPF/CNPJ ---
            if etapa_atual == 'cadastro_venda_cpf':
                cpf_limpo, err = validar_cpf_ou_cnpj_whatsapp(mensagem_texto)
                if err:
                    resposta = f"❌ {err}\n\nDigite o CPF ou CNPJ (apenas números):"
                    return _enviar_resposta_e_retornar(resposta)
                from crm_app.models import Cliente as ClienteCRM
                cliente_existente = ClienteCRM.objects.filter(cpf_cnpj=cpf_limpo).first()
                if cliente_existente:
                    sessao.dados_temp = {**dt, 'cliente_cpf_cnpj': cpf_limpo, 'cliente_nome_razao_social': (cliente_existente.nome_razao_social or '').strip().upper() or f'Cliente {cpf_limpo}', 'cliente_ja_cadastrado': True}
                    sessao.etapa = 'cadastro_venda_tel1'
                    sessao.save()
                    resposta = "✅ Cliente já cadastrado.\n\nDigite o *Telefone 1 (WhatsApp)* do cliente (DDD + número, 11 dígitos):"
                else:
                    sessao.dados_temp = {**dt, 'cliente_cpf_cnpj': cpf_limpo}
                    sessao.etapa = 'cadastro_venda_nome'
                    sessao.save()
                    resposta = "Digite o *Nome completo* (ou Razão Social) do cliente:"
                return _enviar_resposta_e_retornar(resposta)

            # --- Nome ---
            if etapa_atual == 'cadastro_venda_nome':
                nome = (mensagem_texto or "").strip().upper()
                if not nome:
                    resposta = "Digite o nome completo do cliente:"
                    return _enviar_resposta_e_retornar(resposta)
                sessao.dados_temp = {**dt, 'cliente_nome_razao_social': nome}
                sessao.etapa = 'cadastro_venda_tel1'
                sessao.save()
                resposta = "Digite o *Telefone 1 (WhatsApp)* do cliente (DDD + número, apenas números, 11 dígitos):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Telefone 1 ---
            if etapa_atual == 'cadastro_venda_tel1':
                tel1, err = validar_telefone_brasil(mensagem_texto)
                if err:
                    resposta = f"❌ {err}\n\nDigite o Telefone 1 (11 dígitos):"
                    return _enviar_resposta_e_retornar(resposta)
                sessao.dados_temp = {**dt, 'telefone1': tel1}
                sessao.etapa = 'cadastro_venda_tel2'
                sessao.save()
                resposta = "Digite o *Telefone 2* (contato secundário, 11 dígitos):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Telefone 2 ---
            if etapa_atual == 'cadastro_venda_tel2':
                tel2, err = validar_telefone_brasil(mensagem_texto)
                if err:
                    resposta = f"❌ {err}\n\nDigite o Telefone 2 (11 dígitos):"
                    return _enviar_resposta_e_retornar(resposta)
                tel1 = dt.get('telefone1', '')
                if tel2 == tel1:
                    resposta = "❌ O Telefone 2 deve ser diferente do Telefone 1. Digite outro número:"
                    return _enviar_resposta_e_retornar(resposta)
                sessao.dados_temp = {**dt, 'telefone2': tel2}
                sessao.save()
                if eh_sem_app:
                    sessao.etapa = 'cadastro_venda_cep'
                    sessao.save()
                    resposta = "Digite o *CEP* do endereço de instalação (8 dígitos):"
                else:
                    # Via APP: não pergunta plano/forma de pagamento, vai direto para observações
                    sessao.etapa = 'cadastro_venda_observacoes'
                    sessao.save()
                    resposta = "Digite *observações* (ou *PULAR* para nenhuma):"
                return _enviar_resposta_e_retornar(resposta)

            # --- [SEM_APP apenas] Quer informar plano? (etapa usada só em fluxos que listam plano depois do endereço) ---
            if etapa_atual == 'cadastro_venda_quer_plano':
                if mensagem_limpa == '1' or mensagem_limpa == 'SIM':
                    planos = list(Plano.objects.filter(ativo=True).order_by('nome').values_list('id', 'nome')[:15])
                    opts = "\n".join([f"{i+1}. {n}" for i, (id_p, n) in enumerate(planos)])
                    sessao.dados_temp = {**dt, '_planos_list': [(id_p, n) for id_p, n in planos]}
                    sessao.etapa = 'cadastro_venda_plano'
                    sessao.save()
                    resposta = f"Escolha o *Plano* (digite o número):\n{opts}"
                else:
                    sessao.etapa = 'cadastro_venda_observacoes'
                    sessao.save()
                    resposta = "Digite *observações* (ou *PULAR* para nenhuma):"
                return _enviar_resposta_e_retornar(resposta)

            # --- CEP (SEM_APP) ---
            if etapa_atual == 'cadastro_venda_cep':
                cep_limpo = re.sub(r'\D', '', mensagem_texto or '')[:8]
                if len(cep_limpo) != 8:
                    resposta = "❌ CEP deve ter 8 dígitos. Digite o CEP:"
                    return _enviar_resposta_e_retornar(resposta)
                viacep = consultar_viacep_whatsapp(cep_limpo)
                if not viacep:
                    resposta = "❌ CEP não encontrado. Digite outro CEP ou *CANCELAR*:"
                    return _enviar_resposta_e_retornar(resposta)
                logr = viacep.get('logradouro') or viacep.get('localidade') or ''
                sessao.dados_temp = {**dt, 'cep': viacep.get('cep', cep_limpo), 'viacep': viacep}
                sessao.etapa = 'cadastro_venda_numero'
                sessao.save()
                resposta = f"✅ CEP: {logr}\n\nDigite o *número* do endereço (ou S/N):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Número, complemento, bairro, cidade, estado, ponto ref ---
            if etapa_atual == 'cadastro_venda_numero':
                num = (mensagem_texto or "").strip().upper() or "S/N"
                sessao.dados_temp = {**dt, 'numero_residencia': num}
                vc = dt.get('viacep') or {}
                sessao.dados_temp['logradouro'] = vc.get('logradouro') or ''
                sessao.dados_temp['bairro'] = vc.get('bairro') or ''
                sessao.dados_temp['cidade'] = vc.get('localidade') or ''
                sessao.dados_temp['estado'] = (vc.get('uf') or '').upper()[:2]
                sessao.etapa = 'cadastro_venda_complemento'
                sessao.save()
                resposta = "Digite o *complemento* (ou *PULAR*):"
                return _enviar_resposta_e_retornar(resposta)

            if etapa_atual == 'cadastro_venda_complemento':
                compl = (mensagem_texto or "").strip().upper() if (mensagem_texto or "").strip().upper() != 'PULAR' else ''
                sessao.dados_temp = {**dt, 'complemento': compl or None}
                sessao.etapa = 'cadastro_venda_ponto_ref'
                sessao.save()
                resposta = "Digite o *ponto de referência* do endereço:"
                return _enviar_resposta_e_retornar(resposta)

            if etapa_atual == 'cadastro_venda_ponto_ref':
                ref = (mensagem_texto or "").strip().upper()
                sessao.dados_temp = {**dt, 'ponto_referencia': ref or None}
                planos = list(Plano.objects.filter(ativo=True).order_by('nome').values_list('id', 'nome')[:15])
                opts = "\n".join([f"{i+1}. {n}" for i, (id_p, n) in enumerate(planos)])
                sessao.dados_temp['_planos_list'] = [(id_p, n) for id_p, n in planos]
                sessao.etapa = 'cadastro_venda_plano'
                sessao.save()
                resposta = f"Escolha o *Plano* (digite o número):\n{opts}"
                return _enviar_resposta_e_retornar(resposta)

            # --- Plano (por número) ---
            if etapa_atual == 'cadastro_venda_plano':
                planos_list = dt.get('_planos_list') or []
                try:
                    idx = int(mensagem_limpa)
                    if 1 <= idx <= len(planos_list):
                        plano_id, _ = planos_list[idx - 1]
                        sessao.dados_temp = {**dt, 'plano': plano_id}
                        formas = list(FormaPagamento.objects.filter(ativo=True).order_by('nome').values_list('id', 'nome')[:15])
                        opts = "\n".join([f"{i+1}. {n}" for i, (id_f, n) in enumerate(formas)])
                        sessao.dados_temp['_formas_list'] = [(id_f, n) for id_f, n in formas]
                        sessao.etapa = 'cadastro_venda_forma_pagamento'
                        sessao.save()
                        resposta = f"Escolha a *Forma de Pagamento* (digite o número):\n{opts}"
                    else:
                        resposta = "Número inválido. Digite o número do plano:"
                except ValueError:
                    resposta = "Digite o número do plano (ex: 1, 2, 3):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Forma de pagamento ---
            if etapa_atual == 'cadastro_venda_forma_pagamento':
                formas_list = dt.get('_formas_list') or []
                try:
                    idx = int(mensagem_limpa)
                    if 1 <= idx <= len(formas_list):
                        forma_id, _ = formas_list[idx - 1]
                        sessao.dados_temp = {**dt, 'forma_pagamento': forma_id}
                        if eh_sem_app:
                            sessao.etapa = 'cadastro_venda_nome_mae'
                            sessao.save()
                            resposta = "Digite o *Nome da Mãe* do cliente (ou *PULAR*):"
                        else:
                            sessao.etapa = 'cadastro_venda_observacoes'
                            sessao.save()
                            resposta = "Digite *observações* (ou *PULAR*):"
                    else:
                        resposta = "Número inválido. Digite o número da forma de pagamento:"
                except ValueError:
                    resposta = "Digite o número da forma de pagamento:"
                return _enviar_resposta_e_retornar(resposta)

            # --- Nome da mãe ---
            if etapa_atual == 'cadastro_venda_nome_mae':
                nome_mae = (mensagem_texto or "").strip().upper() if (mensagem_texto or "").strip().upper() != 'PULAR' else None
                sessao.dados_temp = {**dt, 'nome_mae': nome_mae}
                sessao.etapa = 'cadastro_venda_data_nasc'
                sessao.save()
                resposta = "Digite a *Data de Nascimento* (DD/MM/AAAA) ou *PULAR*:"
                return _enviar_resposta_e_retornar(resposta)

            # --- Data nascimento ---
            if etapa_atual == 'cadastro_venda_data_nasc':
                dn = None
                if (mensagem_texto or "").strip().upper() != 'PULAR':
                    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                        try:
                            dn = datetime.strptime((mensagem_texto or "").strip()[:10], fmt).date()
                            break
                        except ValueError:
                            continue
                sessao.dados_temp = {**dt, 'data_nascimento': dn}
                sessao.etapa = 'cadastro_venda_email'
                sessao.save()
                resposta = "Digite o *E-mail* do cliente (ou *PULAR*):"
                return _enviar_resposta_e_retornar(resposta)

            # --- E-mail ---
            if etapa_atual == 'cadastro_venda_email':
                email = (mensagem_texto or "").strip() if (mensagem_texto or "").strip().upper() != 'PULAR' else None
                if email and '@' not in email:
                    resposta = "E-mail inválido. Digite um e-mail válido ou *PULAR*:"
                    return _enviar_resposta_e_retornar(resposta)
                sessao.dados_temp = {**dt, 'cliente_email': email or ''}
                cpf_len = len(re.sub(r'\D', '', dt.get('cliente_cpf_cnpj', '')))
                if cpf_len == 14:
                    sessao.etapa = 'cadastro_venda_cpf_rep'
                    sessao.save()
                    resposta = "CNPJ informado. Digite o *CPF do Representante Legal* (11 dígitos):"
                else:
                    sessao.etapa = 'cadastro_venda_observacoes'
                    sessao.save()
                    resposta = "Digite *observações* (ou *PULAR*):"
                return _enviar_resposta_e_retornar(resposta)

            # --- CPF Representante (CNPJ) ---
            if etapa_atual == 'cadastro_venda_cpf_rep':
                cpf_rep, err = validar_cpf_ou_cnpj_whatsapp(mensagem_texto)
                if err or (cpf_rep and len(cpf_rep) != 11):
                    resposta = "❌ Digite um CPF válido (11 dígitos) do representante legal:"
                    return _enviar_resposta_e_retornar(resposta)
                sessao.dados_temp = {**dt, 'cpf_representante_legal': cpf_rep}
                sessao.etapa = 'cadastro_venda_nome_rep'
                sessao.save()
                resposta = "Digite o *Nome do Representante Legal*:"
                return _enviar_resposta_e_retornar(resposta)

            # --- Nome Representante ---
            if etapa_atual == 'cadastro_venda_nome_rep':
                nome_rep = (mensagem_texto or "").strip().upper()
                sessao.dados_temp = {**dt, 'nome_representante_legal': nome_rep}
                sessao.etapa = 'cadastro_venda_observacoes'
                sessao.save()
                resposta = "Digite *observações* (ou *PULAR*):"
                return _enviar_resposta_e_retornar(resposta)

            # --- Observações e SALVAR (sempre envia resposta de sucesso ou erro ao usuário) ---
            if etapa_atual == 'cadastro_venda_observacoes':
                try:
                    obs = (mensagem_texto or "").strip() if (mensagem_texto or "").strip().upper() != 'PULAR' else None
                    sessao.dados_temp = {**dt, 'observacoes': obs}
                    sessao.save()
                    payload = {k: v for k, v in sessao.dados_temp.items() if not k.startswith('_') and k != 'vendedor_id'}
                    payload['forma_entrada'] = payload.get('forma_entrada') or 'APP'
                    payload['tem_fixo'] = payload.get('tem_fixo', False)
                    payload['gerada_os_automatica'] = payload.get('gerada_os_automatica', False)
                    vendedor_id = sessao.dados_temp.get('vendedor_id')
                    from usuarios.models import Usuario
                    vendedor = Usuario.objects.filter(pk=vendedor_id, is_active=True).first() if vendedor_id else usuario_whatsapp
                    if not vendedor:
                        vendedor = usuario_whatsapp
                    venda_id, err = cadastrar_venda_crm(payload, vendedor)
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    if err:
                        resposta = f"❌ *Erro ao salvar:*\n{err}\n\nDigite *MENU* para tentar novamente."
                        return _enviar_resposta_e_retornar(resposta)
                    try:
                        nome_cliente = dt.get('cliente_nome_razao_social') or 'N/A'
                        msg_backoffice = (
                            f"Sua venda, do cliente {nome_cliente} foi recebida pelo backOffice, está na etapa da auditoria, "
                            f"aguarde o tratamento e acompanhe o status pelo bot, enviando a palavra \"Status\".\n"
                            f"Protocolo: {venda_id}"
                        )
                        WhatsAppService().enviar_mensagem_texto(vendedor.tel_whatsapp or telefone_formatado, msg_backoffice)
                    except Exception:
                        pass
                    resposta = f"✅ *Venda cadastrada com sucesso!*\n\nID da venda: *#{venda_id}*\n\nVocê receberá confirmação no WhatsApp. Digite *MENU* para outras opções."
                    return _enviar_resposta_e_retornar(resposta)
                except Exception as e:
                    logger.exception(f"[Webhook] Erro ao processar cadastro_venda_observacoes: {e}")
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    resposta = f"❌ *Ocorreu um erro* ao salvar a venda. Tente novamente ou digite *MENU*.\n\nDetalhe: {str(e)[:200]}"
                    return _enviar_resposta_e_retornar(resposta)

        # --- INCLUSÃO (Solicitação de viabilidade via formulário) ---
        elif etapa_atual.startswith('inclusao_'):
            if mensagem_limpa == 'CANCELAR':
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "Solicitação cancelada. Digite *MENU* para ver as opções."
                return _enviar_resposta_e_retornar(resposta)

            from crm_app.services_inclusao_viabilidade import (
                consultar_viacep,
                buscar_coordenadas,
                obter_tipo_logradouro,
                baixar_street_view,
                formatar_cep,
                preencher_formulario_inclusao,
            )

            if etapa_atual == 'inclusao_cep':
                cep_limpo = limpar_texto_cep_cpf(mensagem_texto)
                if not cep_limpo or len(cep_limpo) < 8:
                    resposta = "❌ CEP inválido. Digite o CEP completo (8 dígitos) ou *CANCELAR*:"
                else:
                    viacep = consultar_viacep(cep_limpo)
                    if not viacep:
                        resposta = "❌ CEP não encontrado. Digite outro CEP ou *CANCELAR*:"
                    else:
                        sessao.etapa = 'inclusao_numero'
                        sessao.dados_temp = {'cep': cep_limpo, 'viacep': viacep}
                        sessao.save()
                        end = viacep.get('logradouro') or viacep.get('localidade') or cep_limpo
                        resposta = f"✅ CEP encontrado: {end}\n\nDigite o *número da fachada* (se SN ou sem número, informe 0):"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_numero':
                num = mensagem_texto.strip().upper()
                if num in ('SN', 'S/N', 'SEM NÚMERO', 'SEM NUMERO'):
                    num = '0'
                elif num.isdigit():
                    num = num
                else:
                    num = mensagem_texto.strip()
                sessao.etapa = 'inclusao_complementos'
                sessao.dados_temp = {**dados_temp, 'numero_fachada': num}
                sessao.save()
                resposta = "Digite os *complementos* (Quadra, lote, apto, casa...). Se não houver, escreva *sem complementos*:"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_complementos':
                comp = mensagem_texto.strip()
                if not comp:
                    comp = "sem complementos"
                elif comp.upper() in ('NAO', 'NÃO', 'N', 'SEM'):
                    comp = "sem complementos"
                sessao.etapa = 'inclusao_vizinhos'
                sessao.dados_temp = {**dados_temp, 'complementos': comp}
                sessao.save()
                resposta = "Digite as *fachadas/lotes vizinhos* no formato:\nFrente xx, Direita xx, Esquerda xx\n\n(Informe os 3 valores que souber):"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_vizinhos':
                viz = mensagem_texto.strip()
                if not viz:
                    resposta = "Por favor, informe as fachadas vizinhas (Frente xx, Direita xx, Esquerda xx):"
                    return _enviar_resposta_e_retornar(resposta)
                viacep = dados_temp.get('viacep', {})
                logr = viacep.get('logradouro', '')
                cidade = viacep.get('localidade', '')
                uf = viacep.get('uf', '')
                numero = dados_temp.get('numero_fachada', '0')
                endereco_completo = f"{logr}, {numero}, {cidade} - {uf}, Brasil"
                coords = buscar_coordenadas(endereco_completo)
                if coords:
                    lat, lng = coords['lat'], coords['lng']
                    coord_str = f"{lat:.14f}, {lng:.14f}"
                    maps_link = f"https://www.google.com/maps?q={lat},{lng}"
                    sessao.etapa = 'inclusao_coordenadas'
                    sessao.dados_temp = {**dados_temp, 'fachadas_vizinhos': viz, 'coordenadas_preview': coord_str, 'maps_link': maps_link, 'coords_lat': lat, 'coords_lng': lng}
                    sessao.save()
                    resposta = (f"📍 Coordenadas encontradas:\n{coord_str}\n\n"
                                f"🔗 Confira no mapa: {maps_link}\n\n"
                                f"As coordenadas caem no endereço correto? Responda *SIM* ou digite as coordenadas manualmente (formato: -xx.xxxxxx, -xx.xxxxxxx):")
                else:
                    sessao.etapa = 'inclusao_coordenadas'
                    sessao.dados_temp = {**dados_temp, 'fachadas_vizinhos': viz}
                    sessao.save()
                    resposta = "Não foi possível obter coordenadas automaticamente. Digite as coordenadas manualmente (formato: -xx.xxxxxx, -xx.xxxxxxx) ou copie do Google Maps:"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_coordenadas':
                if mensagem_limpa in ('SIM', 'S'):
                    coord_str = dados_temp.get('coordenadas_preview', '')
                    if coord_str:
                        sessao.etapa = 'inclusao_foto'
                        sessao.dados_temp = {**dados_temp, 'coordenadas': coord_str}
                        sessao.save()
                        resposta = "Tentando obter foto do Street View automaticamente...\n\nSe não houver foto disponível, *envie uma foto* do local (Google Street View ou satélite):"
                    else:
                        resposta = "Erro ao confirmar coordenadas. Tente novamente."
                else:
                    coord_str = mensagem_texto.strip()
                    if coord_str and (',' in coord_str or ' ' in coord_str):
                        parts = re.sub(r'\s+', ' ', coord_str).replace(',', ' ').split()
                        lat_val, lng_val = dados_temp.get('coords_lat'), dados_temp.get('coords_lng')
                        if len(parts) >= 2:
                            try:
                                lat_val = float(parts[0])
                                lng_val = float(parts[1])
                            except (ValueError, TypeError):
                                pass
                        sessao.etapa = 'inclusao_foto'
                        sessao.dados_temp = {**dados_temp, 'coordenadas': coord_str, 'coords_lat': lat_val, 'coords_lng': lng_val}
                        sessao.save()
                        resposta = "Tentando obter foto do Street View...\n\nSe não houver foto, *envie uma imagem* do local:"
                    else:
                        resposta = "Digite as coordenadas no formato: -xx.xxxxxx, -xx.xxxxxxx"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_foto':
                foto_path = None
                if image_url:
                    try:
                        import requests as req
                        r = req.get(image_url, timeout=15)
                        if r.status_code == 200:
                            import tempfile
                            fd, foto_path = tempfile.mkstemp(suffix='.jpg', prefix='inclusao_')
                            os.close(fd)
                            with open(foto_path, 'wb') as f:
                                f.write(r.content)
                            logger.info(f"[Inclusão] Foto recebida do usuário salva em {foto_path}")
                    except Exception as e:
                        logger.warning(f"[Inclusão] Erro ao baixar imagem: {e}")
                if not foto_path:
                    lat = dados_temp.get('coords_lat')
                    lng = dados_temp.get('coords_lng')
                    if lat is not None and lng is not None:
                        foto_path = baixar_street_view(lat, lng)
                if foto_path:
                    sessao.etapa = 'inclusao_comprovante'
                    sessao.dados_temp = {**dados_temp, 'foto_path': foto_path, 'comprovantes_paths': []}
                    sessao.save()
                    resposta = "✅ Foto recebida.\n\nDeseja anexar *comprovante de endereço*? (PDF ou imagem)\n\nEnvie o(s) arquivo(s) ou digite *pronto* para continuar:"
                else:
                    resposta = "Por favor, *envie uma foto* do local (Google Street View ou satélite são aceitas):"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_comprovante':
                comprovantes = list(dados_temp.get('comprovantes_paths') or [])
                arquivo_baixado = None
                if image_url:
                    try:
                        import requests as req
                        r = req.get(image_url, timeout=15)
                        if r.status_code == 200:
                            import tempfile
                            fd, path = tempfile.mkstemp(suffix='.jpg', prefix='inclusao_comp_')
                            os.close(fd)
                            with open(path, 'wb') as f:
                                f.write(r.content)
                            comprovantes.append(path)
                            arquivo_baixado = True
                            logger.info(f"[Inclusão] Comprovante (imagem) salvo: {path}")
                    except Exception as e:
                        logger.warning(f"[Inclusão] Erro ao baixar imagem comprovante: {e}")
                elif document_url:
                    try:
                        import requests as req
                        r = req.get(document_url, timeout=15)
                        if r.status_code == 200:
                            import tempfile
                            ext = '.pdf'
                            ct = r.headers.get('Content-Type', '')
                            if 'image' in ct:
                                ext = '.jpg' if 'jpeg' in ct or 'jpg' in ct else '.png'
                            fd, path = tempfile.mkstemp(suffix=ext, prefix='inclusao_comp_')
                            os.close(fd)
                            with open(path, 'wb') as f:
                                f.write(r.content)
                            comprovantes.append(path)
                            arquivo_baixado = True
                            logger.info(f"[Inclusão] Comprovante (documento) salvo: {path}")
                    except Exception as e:
                        logger.warning(f"[Inclusão] Erro ao baixar documento comprovante: {e}")
                if mensagem_limpa in ['PRONTO', 'PULAR', 'CONTINUAR', 'NÃO', 'NAO']:
                    sessao.etapa = 'inclusao_observacoes'
                    sessao.dados_temp = {**dados_temp, 'comprovantes_paths': comprovantes}
                    sessao.save()
                    resposta = "Digite as *observações de vendas* (opcional - pode enviar em branco):"
                elif arquivo_baixado:
                    sessao.dados_temp = {**dados_temp, 'comprovantes_paths': comprovantes}
                    sessao.save()
                    resposta = f"✅ Comprovante recebido. Envie mais ou digite *pronto* para continuar:"
                else:
                    resposta = "Envie um comprovante (PDF ou imagem) ou digite *pronto* para pular:"
                return _enviar_resposta_e_retornar(resposta)

            elif etapa_atual == 'inclusao_enviando':
                return _enviar_resposta_e_retornar("⏳ Enviando solicitação de viabilidade... Aguarde.")
            elif etapa_atual == 'inclusao_confirmar':
                if mensagem_limpa in ['CANCELAR', 'NAO', 'NÃO', 'DESISTIR']:
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    resposta = "Envio cancelado. Digite *MENU* para ver as opções."
                    return _enviar_resposta_e_retornar(resposta)
                if mensagem_limpa not in ['SIM', 'S', 'CONFIRMAR', 'ENVIAR']:
                    resposta = ("⚠️ Para enviar, confirme que as informações e anexos são verdadeiros.\n\n"
                                "Digite *SIM* para enviar ou *CANCELAR* para desistir.")
                    return _enviar_resposta_e_retornar(resposta)
                with _inclusao_form_lock:
                    if telefone_formatado in _inclusao_form_em_execucao:
                        return _enviar_resposta_e_retornar("⏳ Enviando solicitação de viabilidade... Aguarde.")
                    _inclusao_form_em_execucao.add(telefone_formatado)
                try:
                    from crm_app.services_inclusao_viabilidade import criar_demanda_inclusao

                    dados_finais = {**dados_temp, 'observacoes': dados_temp.get('observacoes', '')}
                    foto_path = dados_temp.get('foto_path')
                    comprovantes = dados_temp.get('comprovantes_paths') or []
                    arquivos_paths = [foto_path] + comprovantes if foto_path else list(comprovantes)
                    arquivos_paths = [p for p in arquivos_paths if p and os.path.isfile(p)]
                    sessao.etapa = 'inclusao_enviando'
                    sessao.save(update_fields=['etapa'])
                    # Railway não preenche o Google Forms (sessão Google bloqueada).
                    # Cria demanda na Auditoria; auditor envia via extensão Chrome local.
                    sucesso, msg = criar_demanda_inclusao(
                        dados_finais,
                        arquivos_paths=arquivos_paths,
                        telefone_solicitante=telefone_formatado,
                        solicitante=usuario_whatsapp,
                    )
                    for p in arquivos_paths:
                        try:
                            if p and os.path.isfile(p):
                                os.unlink(p)
                        except Exception:
                            pass
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    resposta = msg if sucesso else f"❌ {msg}"
                    return _enviar_resposta_e_retornar(resposta)
                finally:
                    with _inclusao_form_lock:
                        _inclusao_form_em_execucao.discard(telefone_formatado)
            elif etapa_atual == 'inclusao_observacoes':
                obs = mensagem_texto.strip() if mensagem_texto else ''
                sessao.dados_temp = {**dados_temp, 'observacoes': obs}
                sessao.etapa = 'inclusao_confirmar'
                sessao.save()
                resposta = (
                    "⚠️ *Confirmação antes de enviar*\n\n"
                    "Confirme que você *não* está tentando criar um complemento ou fachada que não existe "
                    "para recompra, ou anexar fotos/comprovante que não sejam verdadeiros, ou algo que possa "
                    "prejudicar a Record como parceiro Nio.\n\n"
                    "Ao confirmar, a solicitação irá para a *Auditoria* (envio ao Google Forms pelo auditor).\n\n"
                    "Digite *SIM* para enviar ou *CANCELAR* para desistir."
                )
                return _enviar_resposta_e_retornar(resposta)
        
        elif etapa_atual in ('status_documento', 'status_tipo', 'status_cpf', 'status_os'):
            # status_tipo/cpf/os: etapas antigas — ainda aceitas até a sessão expirar
            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "❌ Cancelado. Digite *STATUS* para consultar novamente."
                return _enviar_resposta_e_retornar(resposta)

            # Quem ainda está no menu 1/2 antigo: orienta a enviar o identificador direto
            if mensagem_limpa in ['1', '2', 'CPF', 'OS', 'O.S']:
                sessao.etapa = 'status_documento'
                sessao.dados_temp = {}
                sessao.save()
                resposta = (
                    "Agora basta enviar o *CPF* ou a *O.S* diretamente "
                    "(sem escolher 1 ou 2).\n\n"
                    f"{_MSG_STATUS_PEDIR_IDENTIFICADOR}"
                )
                return _enviar_resposta_e_retornar(resposta)

            tipo_id, valor_id, erro_id = classificar_identificador_status(mensagem_texto)
            if not tipo_id:
                sessao.etapa = 'status_documento'
                sessao.save(update_fields=['etapa'])
                resposta = erro_id
                return _enviar_resposta_e_retornar(resposta)

            resposta = _consultar_status_e_disparar_online(
                sessao,
                telefone_formatado,
                tipo_id,
                valor_id,
                etapa_retry='status_documento',
            )
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'status_aguardando_online':
            dados_online = dados_temp or {}
            started_at = float(dados_online.get('status_online_started_at') or 0)
            tempo_espera = time.time() - started_at if started_at else 0
            if started_at and tempo_espera > STATUS_ONLINE_MAX_WAIT_SECONDS:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = (
                    "❌ Não foi possível concluir a conexão com o PAP a tempo.\n\n"
                    "Digite *STATUS* para tentar novamente."
                )
            else:
                resposta = "⏳ Consultando status online no PAP... Aguarde. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'credito_aguardando':
            resposta = "⏳ Consultando crédito... Aguarde. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'credito_cpf':
            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "❌ Cancelado. Digite *CRÉDITO* para consultar novamente."
            else:
                doc_limpo = limpar_texto_cep_cpf(mensagem_texto)
                if not doc_limpo or len(doc_limpo) not in (11, 14) or not doc_limpo.isdigit():
                    resposta = "❌ Documento inválido. Digite um CPF (11) ou CNPJ (14) ou *CANCELAR*:"
                else:
                    usuario_id = dados_temp.get('usuario_id')
                    if not usuario_id:
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        resposta = "❌ Sessão expirada. Digite *CRÉDITO* para iniciar novamente."
                    else:
                        if len(doc_limpo) == 14:
                            sessao.etapa = 'credito_cnpj_representante'
                            sessao.dados_temp = {**(dados_temp or {}), 'documento_credito': doc_limpo}
                            sessao.save()
                            resposta = "✅ CNPJ recebido.\n\nAgora digite o *CPF do representante legal* (11 dígitos), ou *CANCELAR*:"
                        else:
                            # Persistir aguardando ANTES do despacho evita corrida
                            # em que o worker reseta a sessão e este save sobrescreve.
                            sessao.etapa = 'credito_aguardando'
                            sessao.save()
                            from crm_app.services.pap_dispatcher import despachar_pap
                            despachar_pap(
                                'analise_credito',
                                telefone_formatado,
                                {
                                    'telefone': telefone_formatado,
                                    'usuario_id': usuario_id,
                                    'documento': doc_limpo,
                                    'cpf_representante': None,
                                },
                                _executar_analise_credito_background,
                                (telefone_formatado, usuario_id, doc_limpo, None),
                            )
                            resposta = "⏳ Consultando crédito... Aguarde alguns instantes. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'credito_cnpj_representante':
            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "❌ Cancelado. Digite *CRÉDITO* para consultar novamente."
            else:
                cpf_rep = limpar_texto_cep_cpf(mensagem_texto)
                if not cpf_rep or len(cpf_rep) != 11 or not cpf_rep.isdigit():
                    resposta = "❌ CPF do representante inválido. Digite 11 dígitos ou *CANCELAR*:"
                else:
                    usuario_id = dados_temp.get('usuario_id')
                    doc_cnpj = (dados_temp or {}).get('documento_credito')
                    if not usuario_id or not doc_cnpj:
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        resposta = "❌ Sessão expirada. Digite *CRÉDITO* para iniciar novamente."
                    else:
                        sessao.etapa = 'credito_aguardando'
                        sessao.save()
                        from crm_app.services.pap_dispatcher import despachar_pap
                        despachar_pap(
                            'analise_credito',
                            telefone_formatado,
                            {
                                'telefone': telefone_formatado,
                                'usuario_id': usuario_id,
                                'documento': doc_cnpj,
                                'cpf_representante': cpf_rep,
                            },
                            _executar_analise_credito_background,
                            (telefone_formatado, usuario_id, doc_cnpj, cpf_rep),
                        )
                        resposta = "⏳ Consultando crédito para o CNPJ... Aguarde alguns instantes. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'pedido_aguardando':
            resposta = "⏳ Consultando pedido... Aguarde. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'pedido_cpf':
            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "❌ Cancelado. Digite *PEDIDO* para consultar novamente."
            else:
                cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
                if not cpf_limpo or len(cpf_limpo) not in (11, 14) or not cpf_limpo.isdigit():
                    resposta = "❌ CPF/CNPJ inválido. Digite 11 (CPF) ou 14 (CNPJ) dígitos, ou *CANCELAR*:"
                else:
                    usuario_id = dados_temp.get('usuario_id')
                    if not usuario_id:
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        resposta = "❌ Sessão expirada. Digite *PEDIDO* para iniciar novamente."
                    else:
                        from crm_app.services.pap_dispatcher import despachar_pap
                        despachar_pap(
                            'consulta_pedido',
                            telefone_formatado,
                            {
                                'telefone': telefone_formatado,
                                'usuario_id': usuario_id,
                                'cpf': cpf_limpo,
                            },
                            _executar_consulta_pedido_background,
                            (telefone_formatado, usuario_id, cpf_limpo),
                        )
                        sessao.etapa = 'pedido_aguardando'
                        sessao.save()
                        resposta = "⏳ Consultando pedido no PAP... Aguarde alguns instantes. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'bio_aguardando':
            resposta = "⏳ Consultando biometria no Br Pronto... Aguarde. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'bio_cpf':
            if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                resposta = "❌ Cancelado. Digite *BIO* para consultar novamente."
            else:
                cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
                if not cpf_limpo or len(cpf_limpo) != 11 or not cpf_limpo.isdigit():
                    resposta = "❌ CPF inválido. Digite 11 dígitos, ou *CANCELAR*:"
                else:
                    usuario_id = dados_temp.get('usuario_id')
                    if not usuario_id:
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        resposta = "❌ Sessão expirada. Digite *BIO* para iniciar novamente."
                    else:
                        import threading
                        t = threading.Thread(
                            target=_executar_consulta_bio_background,
                            args=(telefone_formatado, usuario_id, cpf_limpo),
                            daemon=True,
                        )
                        t.start()
                        sessao.etapa = 'bio_aguardando'
                        sessao.save()
                        resposta = "⏳ Consultando biometria no Br Pronto... Aguarde alguns instantes. Você receberá a resposta em seguida."
            return _enviar_resposta_e_retornar(resposta)

        elif etapa_atual == 'conta_cpf':
            # CONTA = 2ª via pelo site (sem reCAPTCHA)
            cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
            cpf_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
            if not cpf_valido:
                resposta = "❌ CPF inválido. Digite o CPF completo (11 dígitos, apenas números):"
            else:
                try:
                    from django.conf import settings
                    from crm_app.services_nio import buscar_fatura_segunda_via_site
                    headless_conta = getattr(settings, 'PAP_HEADLESS', True)
                    invoices = buscar_fatura_segunda_via_site(
                        cpf_limpo, incluir_pdf=True, headless=headless_conta
                    )
                    if not invoices:
                        cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}"
                        resposta = f"🔎 Consultando 2ª via para CPF {cpf_formatado}...\n\nNenhuma conta encontrada para este CPF."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                    else:
                        invoice = invoices[0]
                        resposta = _formatar_detalhes_fatura(invoice, cpf_limpo, incluir_pdf=True)
                        if invoice.get('pdf_path') or invoice.get('pdf_url'):
                            sessao.dados_temp = {'invoice_para_pdf': invoice}
                        else:
                            sessao.dados_temp = {}
                        sessao.etapa = 'inicial'
                        sessao.save()
                except Exception as e:
                    logger.exception(f"[Webhook] Erro ao buscar conta (2ª via): {e}")
                    resposta = "❌ Erro ao consultar a conta. Tente novamente em instantes."
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
        
        elif etapa_atual == 'fatura_cpf':
            cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
            
            # Validar apenas formato básico (11 dígitos)
            # A API da Nio é quem valida se o CPF existe na base deles
            # Não validamos dígito verificador aqui porque o site da Nio aceita CPFs
            # que podem não passar na validação rigorosa mas existem na base deles
            cpf_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
            
            if not cpf_valido:
                resposta = "❌ CPF inválido. Por favor, digite o CPF completo (11 dígitos, apenas números):"
            else:
                with _fatura_cpf_lock:
                    sessao.refresh_from_db()
                    dados_temp = sessao.dados_temp or {}
                    # Evitar processar duas vezes quando o webhook é disparado em duplicidade (ex.: Z-API)
                    if dados_temp.get('processando_pdf'):
                        resposta = "⏳ Ainda processando sua fatura. Aguarde um momento..."
                        return _enviar_resposta_e_retornar(resposta)
                    if sessao.etapa == 'fatura_selecionar' and dados_temp.get('cpf') == cpf_limpo:
                        n = len(dados_temp.get('faturas', []))
                        resposta = f"📋 Lista já enviada. Digite o *NÚMERO* da fatura (1 a {n}) que deseja ver os detalhes:"
                        return _enviar_resposta_e_retornar(resposta)
                    logger.info(f"[Webhook] Buscando TODAS as faturas para CPF: {cpf_limpo}")
                    try:
                        from django.conf import settings
                        headless_fatura = getattr(settings, 'PAP_HEADLESS', True)  # False = ver navegador (igual Vender)
                        todas_invoices = []
                        offset = 0
                        limit = 50  # Aumentar limite por requisição
                        max_tentativas = 5  # Evitar loop infinito
                        for tentativa in range(max_tentativas):
                            resultado = consultar_dividas_nio(cpf_limpo, offset=offset, limit=limit, headless=headless_fatura)
                            invoices_lote = resultado.get('invoices', [])
                            if not invoices_lote:
                                break
                            todas_invoices.extend(invoices_lote)
                            if len(invoices_lote) < limit:
                                break
                            offset += limit
                            logger.info(f"[Webhook] Buscando mais faturas: offset={offset}, já encontradas={len(todas_invoices)}")
                        
                        invoices = todas_invoices
                        logger.info(f"[Webhook] Total de faturas encontradas: {len(invoices)}")
                        
                        if not invoices:
                            # Quando a API retorna 200 mas sem faturas (caso do site que mostra "0 contas pra pagar")
                            # Formatar CPF para exibição (XXX.XXX.XXX-XX)
                            cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}"
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n✅ *CPF: {cpf_formatado}*\n\nOlá Cliente, você tem *0 contas* pra pagar.\n\nEste CPF não possui faturas em aberto no momento."
                            sessao.etapa = 'inicial'
                            sessao.dados_temp = {}
                            sessao.save()
                        else:
                            # Separar faturas por status (aceitar tanto uppercase quanto lowercase)
                            # Status pode vir como "overdue", "OVERDUE", "em aberto", "EM ABERTO", etc
                            todas_faturas = []
                            faturas_atrasadas = []
                            faturas_aberto = []
                            outras = []
                            
                            for inv in invoices:
                                status = str(inv.get('status', '')).upper()
                                if status in ['ATRASADO', 'ATRASADA', 'VENCIDA', 'VENCIDO', 'OVERDUE', 'LATE']:
                                    faturas_atrasadas.append(inv)
                                elif status in ['EM ABERTO', 'ABERTO', 'OPEN', 'PENDENTE']:
                                    faturas_aberto.append(inv)
                                else:
                                    outras.append(inv)  # Incluir outras também
                            
                            # Ordenar: atrasadas primeiro, depois abertas, depois outras
                            todas_faturas = faturas_atrasadas + faturas_aberto + outras
                            
                            logger.info(f"[Webhook] Faturas encontradas: {len(invoices)} total | {len(faturas_atrasadas)} atrasadas | {len(faturas_aberto)} em aberto | {len(outras)} outras")
                            
                            if len(todas_faturas) == 1:
                                # Se só tem uma, mostra direto mas busca PDF também
                                invoice = todas_faturas[0]
                                # Marcar logo no início para evitar que outro webhook (duplicado) processe de novo
                                sessao.dados_temp = (sessao.dados_temp or {}) | {'processando_pdf': True, 'cpf': cpf_limpo}
                                sessao.save(update_fields=['dados_temp', 'updated_at'])
                                
                                # Tentar buscar PDF via API primeiro (mais rápido) — a menos que FORCE_FATURA_PDF_PLAYWRIGHT=true (debug)
                                # Segunda-via já traz pdf_path; não usar API (sem debt_id)
                                force_pdf_playwright = getattr(settings, 'FORCE_FATURA_PDF_PLAYWRIGHT', False)
                                eh_segunda_via = invoice.get('source') == 'segunda_via_site'
                                if not force_pdf_playwright and not eh_segunda_via:
                                    print(f"[DEBUG PDF] 🔍 ETAPA 1: Tentando buscar PDF via API...")
                                    logger.info(f"[DEBUG PDF] 🔍 ETAPA 1: Tentando buscar PDF via API para fatura única")
                                    logger.info(f"[DEBUG PDF] Parâmetros: debt_id={invoice.get('debt_id')}, invoice_id={invoice.get('invoice_id')}, cpf={cpf_limpo}, ref={invoice.get('reference_month')}")
                                    print(f"[DEBUG PDF] debt_id={invoice.get('debt_id')}, invoice_id={invoice.get('invoice_id')}, cpf={cpf_limpo}")
                                    
                                    try:
                                        from crm_app.nio_api import get_invoice_pdf_url
                                        import requests
                                        session = requests.Session()
                                        
                                        api_base = resultado.get('api_base', '')
                                        token = resultado.get('token', '')
                                        session_id = resultado.get('session_id', '')
                                        
                                        print(f"[DEBUG PDF] api_base={api_base}, token={'SIM' if token else 'NÃO'}, session_id={'SIM' if session_id else 'NÃO'}")
                                        logger.info(f"[DEBUG PDF] api_base={api_base}, token presente={bool(token)}, session_id presente={bool(session_id)}")
                                        
                                        pdf_url = get_invoice_pdf_url(
                                            api_base,
                                            token,
                                            session_id,
                                            invoice.get('debt_id', ''),
                                            invoice.get('invoice_id', ''),
                                            cpf_limpo,
                                            invoice.get('reference_month', ''),
                                            session
                                        )
                                        
                                        print(f"[DEBUG PDF] Resultado get_invoice_pdf_url: {pdf_url}")
                                        logger.info(f"[DEBUG PDF] Resultado get_invoice_pdf_url: {pdf_url}")
                                        
                                        if pdf_url:
                                            invoice['pdf_url'] = pdf_url
                                            print(f"[DEBUG PDF] ✅ PDF encontrado via API: {pdf_url[:100]}...")
                                            logger.info(f"[DEBUG PDF] ✅ PDF encontrado via API para fatura única: {pdf_url[:100]}...")
                                        else:
                                            print(f"[DEBUG PDF] ❌ PDF não encontrado via API (retornou None)")
                                            logger.warning(f"[DEBUG PDF] ❌ PDF não encontrado via API (retornou None)")
                                    except Exception as e:
                                        print(f"[DEBUG PDF] ❌ ERRO ao buscar PDF via API: {type(e).__name__}: {e}")
                                        logger.warning(f"[DEBUG PDF] ❌ Erro ao buscar PDF via API para fatura única: {e}")
                                        import traceback
                                        logger.error(f"[DEBUG PDF] Traceback: {traceback.format_exc()}")
                                        print(f"[DEBUG PDF] Traceback: {traceback.format_exc()}")
                                else:
                                    print(f"[DEBUG PDF] 🔧 FORCE_FATURA_PDF_PLAYWRIGHT=true: pulando API, indo direto para Playwright (para você ver os cliques)")
                                    logger.info(f"[DEBUG PDF] FORCE_FATURA_PDF_PLAYWRIGHT ativo - PDF será buscado via navegador")
                                    invoice.pop('pdf_url', None)
                                    invoice.pop('pdf_path', None)
                                
                                # Se não encontrou via API (ou FORCE_FATURA_PDF_PLAYWRIGHT), tenta baixar como humano (Playwright)
                                print(f"[DEBUG PDF] 🔍 ETAPA 2: Verificando se precisa baixar via Playwright...")
                                print(f"[DEBUG PDF] invoice.get('pdf_url')={invoice.get('pdf_url')}")
                                print(f"[DEBUG PDF] invoice.get('pdf_path')={invoice.get('pdf_path')}")
                                logger.info(f"[DEBUG PDF] Verificando necessidade de download via Playwright: pdf_url={bool(invoice.get('pdf_url'))}, pdf_path={bool(invoice.get('pdf_path'))}")
                                
                                if ((not invoice.get('pdf_url') and not invoice.get('pdf_path')) or force_pdf_playwright) and not eh_segunda_via:
                                    print(f"[DEBUG PDF] 🔍 ETAPA 3: Iniciando download via Playwright...")
                                    logger.info(f"[DEBUG PDF] 🔍 ETAPA 3: Tentando baixar PDF como humano para fatura única...")
                                    logger.warning("[DEBUG PDF] ⚠️ A página Nio usa reCAPTCHA; o download via navegador costuma falhar. Preferir PDF via API.")
                                    
                                    try:
                                        # Importar função diretamente do módulo (função privada)
                                        import crm_app.services_nio as nio_services
                                        mes_ref = invoice.get('reference_month', '')
                                        data_venc = invoice.get('due_date_raw') or invoice.get('data_vencimento', '')
                                        
                                        print(f"[DEBUG PDF] Parâmetros Playwright: CPF={cpf_limpo}, mes_ref={mes_ref}, data_venc={data_venc}")
                                        logger.info(f"[DEBUG PDF] Parâmetros: CPF={cpf_limpo}, mes_ref={mes_ref}, data_venc={data_venc}")
                                        
                                        # headless=False abre o navegador para você acompanhar os cliques (PAP_HEADLESS=false)
                                        headless_pdf = getattr(settings, 'PAP_HEADLESS', True)
                                        # Passar token/session para injetar na página e habilitar o botão Consultar (evita reCAPTCHA)
                                        api_base = resultado.get('api_base', '')
                                        token = resultado.get('token', '')
                                        session_id = resultado.get('session_id', '')
                                        has_token = bool(api_base and token and session_id)
                                        print(f"[DEBUG PDF] Token para Playwright: api_base={bool(api_base)}, token={bool(token)}, session_id={bool(session_id)} => injetar={has_token}")
                                        logger.info(f"[DEBUG PDF] Token para Playwright: injetar={has_token} (api_base={bool(api_base)}, token={bool(token)}, session_id={bool(session_id)})")
                                        pdf_result = nio_services._baixar_pdf_como_humano(
                                            cpf_limpo, mes_ref, data_venc,
                                            headless=headless_pdf,
                                            api_base=api_base or None,
                                            token=token or None,
                                            session_id=session_id or None,
                                        )
                                        
                                        # Remover flag de processamento após concluir
                                        if sessao:
                                            sessao.dados_temp.pop('processando_pdf', None)
                                            sessao.save(update_fields=['dados_temp', 'updated_at'])
                                            print(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                            logger.info(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                        
                                        print(f"[DEBUG PDF] Resultado _baixar_pdf_como_humano: {pdf_result}")
                                        print(f"[DEBUG PDF] Tipo do resultado: {type(pdf_result)}")
                                        logger.info(f"[DEBUG PDF] Resultado _baixar_pdf_como_humano: {pdf_result}, tipo: {type(pdf_result)}")
                                        
                                        if pdf_result:
                                            # pdf_result pode ser dict (com local_path e onedrive_url) ou string (caminho antigo)
                                            if isinstance(pdf_result, dict):
                                                invoice['pdf_path'] = pdf_result.get('local_path')
                                                invoice['pdf_onedrive_url'] = pdf_result.get('onedrive_url')
                                                invoice['pdf_filename'] = pdf_result.get('filename')
                                                
                                                print(f"[DEBUG PDF] ✅ PDF baixado (dict): local_path={pdf_result.get('local_path')}, onedrive_url={pdf_result.get('onedrive_url')}")
                                                logger.info(f"[DEBUG PDF] ✅ PDF baixado (dict): local_path={pdf_result.get('local_path')}, onedrive_url={pdf_result.get('onedrive_url')}")
                                                
                                                if pdf_result.get('onedrive_url'):
                                                    print(f"[DEBUG PDF] ✅ PDF enviado para OneDrive: {pdf_result['onedrive_url']}")
                                                    logger.info(f"[DEBUG PDF] ✅ PDF baixado e enviado para OneDrive (fatura única): {pdf_result['onedrive_url']}")
                                                else:
                                                    print(f"[DEBUG PDF] ✅ PDF baixado localmente: {pdf_result['local_path']}")
                                                    logger.info(f"[DEBUG PDF] ✅ PDF baixado localmente (fatura única): {pdf_result['local_path']}")
                                            else:
                                                # Compatibilidade com formato antigo (string)
                                                invoice['pdf_path'] = pdf_result
                                                print(f"[DEBUG PDF] ✅ PDF baixado (string): {pdf_result}")
                                                logger.info(f"[DEBUG PDF] ✅ PDF baixado com sucesso para fatura única: {pdf_result}")
                                        else:
                                            print(f"[DEBUG PDF] ❌ Falha ao baixar PDF - retornou None")
                                            logger.warning(f"[DEBUG PDF] ❌ Falha ao baixar PDF como humano para fatura única - retornou None")
                                    except Exception as e:
                                        print(f"[DEBUG PDF] ❌ ERRO ao baixar PDF: {type(e).__name__}: {e}")
                                        logger.error(f"[DEBUG PDF] ❌ Erro ao baixar PDF como humano para fatura única: {e}")
                                        import traceback
                                        tb = traceback.format_exc()
                                        logger.error(f"[DEBUG PDF] Traceback completo:\n{tb}")
                                        print(f"[DEBUG PDF] Traceback completo:\n{tb}")
                                else:
                                    print(f"[DEBUG PDF] ⏭️ Pulando download via Playwright - PDF já disponível")
                                    logger.info(f"[DEBUG PDF] ⏭️ Pulando download via Playwright - PDF já disponível")
                                
                                resposta = _formatar_detalhes_fatura(invoice, cpf_limpo, incluir_pdf=True)
                                
                                # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                                print(f"[DEBUG PDF] 🔍 ETAPA 4: Verificando se PDF está disponível para envio...")
                                print(f"[DEBUG PDF] invoice.get('pdf_path')={invoice.get('pdf_path')}")
                                print(f"[DEBUG PDF] invoice.get('pdf_url')={invoice.get('pdf_url')}")
                                print(f"[DEBUG PDF] invoice.get('pdf_onedrive_url')={invoice.get('pdf_onedrive_url')}")
                                logger.info(f"[DEBUG PDF] Verificando disponibilidade de PDF: pdf_path={bool(invoice.get('pdf_path'))}, pdf_url={bool(invoice.get('pdf_url'))}, pdf_onedrive_url={bool(invoice.get('pdf_onedrive_url'))}")
                                
                                if invoice.get('pdf_path') or invoice.get('pdf_url') or invoice.get('pdf_onedrive_url'):
                                    # Se tem pdf_onedrive_url, usar como pdf_url
                                    if invoice.get('pdf_onedrive_url') and not invoice.get('pdf_url'):
                                        invoice['pdf_url'] = invoice.get('pdf_onedrive_url')
                                        print(f"[DEBUG PDF] ✅ Usando pdf_onedrive_url como pdf_url: {invoice['pdf_url']}")
                                        logger.info(f"[DEBUG PDF] ✅ Usando pdf_onedrive_url como pdf_url")
                                    
                                    sessao.dados_temp = {'invoice_para_pdf': invoice}
                                    print(f"[DEBUG PDF] ✅ PDF disponível - salvo na sessão para envio")
                                    logger.info(f"[DEBUG PDF] ✅ PDF disponível - salvo na sessão para envio")
                                else:
                                    sessao.dados_temp = {}
                                    print(f"[DEBUG PDF] ❌ PDF NÃO disponível - sessão limpa")
                                    logger.warning(f"[DEBUG PDF] ❌ PDF NÃO disponível - sessão limpa")
                                
                                sessao.etapa = 'inicial'
                                sessao.save()
                            else:
                                # Lista todas e pede para escolher
                                resposta_parts = [
                                    f"🔎 *FATURAS ENCONTRADAS* para CPF {cpf_limpo}:\n"
                                ]
                                
                                for idx, inv in enumerate(todas_faturas, 1):
                                    valor = inv.get('amount', 0)
                                    status = inv.get('status', '')
                                    data_venc = inv.get('due_date_raw') or inv.get('data_vencimento', '')
                                    mes_ref = inv.get('reference_month', '')
                                    
                                    # Formatar valor
                                    valor_str = f"R$ {valor:.2f}" if isinstance(valor, (int, float)) else str(valor)
                                    
                                    # Ícone de status (aceitar lowercase também)
                                    status_upper = str(status).upper()
                                    if status_upper in ['ATRASADO', 'ATRASADA', 'VENCIDA', 'VENCIDO', 'OVERDUE', 'LATE']:
                                        emoji = "🔴"
                                    elif status_upper in ['EM ABERTO', 'ABERTO', 'OPEN', 'PENDENTE']:
                                        emoji = "🟡"
                                    else:
                                        emoji = "⚪"
                                    
                                    # Formatar data e status
                                    data_venc_formatada = _formatar_data_brasileira(data_venc) or data_venc
                                    status_pt = _formatar_status_portugues(status)
                                    
                                    resposta_parts.append(
                                        f"{emoji} *{idx}.* {valor_str} | Venc: {data_venc_formatada} | {status_pt}"
                                    )
                                    if mes_ref:
                                        resposta_parts.append(f"   📅 Ref: {mes_ref}")
                                
                                resposta_parts.append(
                                    f"\n📋 Digite o *NÚMERO* da fatura que deseja ver os detalhes (1 a {len(todas_faturas)}):"
                                )
                                
                                resposta = "\n".join(resposta_parts)
                                
                                # Salvar faturas na sessão para recuperar depois
                                sessao.etapa = 'fatura_selecionar'
                                sessao.dados_temp = {
                                    'cpf': cpf_limpo,
                                    'faturas': todas_faturas,
                                    'token': resultado.get('token'),
                                    'api_base': resultado.get('api_base'),
                                    'session_id': resultado.get('session_id'),
                                }
                                sessao.save()
                            
                    except Exception as e:
                        logger.error(f"[Webhook] Erro ao buscar faturas: {e}")
                        import traceback
                        traceback.print_exc()
                        # Tratamento de erros mais específico
                        erro_msg = str(e)
                        
                        # Verificar apenas formato básico (11 dígitos)
                        cpf_formato_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
                        cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}" if cpf_formato_valido else cpf_limpo
                        
                        if "400" in erro_msg or "Bad Request" in erro_msg:
                            if cpf_formato_valido:
                                resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n✅ *CPF: {cpf_formatado}*\n\nOlá Cliente, você tem *0 contas* pra pagar.\n\nEste CPF não possui faturas em aberto no momento."
                            else:
                                resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nCPF não encontrado na base da Nio ou dados inválidos.\n\nVerifique se o CPF está correto e tente novamente."
                        elif "401" in erro_msg or "Unauthorized" in erro_msg:
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro de autenticação com a API da Nio.\n\nTente novamente em alguns instantes."
                        elif "404" in erro_msg or "Not Found" in erro_msg:
                            if cpf_formato_valido:
                                resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n✅ *CPF: {cpf_formatado}*\n\nOlá Cliente, você tem *0 contas* pra pagar.\n\nEste CPF não possui faturas em aberto no momento."
                            else:
                                resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *FATURAS NÃO ENCONTRADAS*\n\nNão encontrei nenhuma fatura para este CPF."
                        else:
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro ao buscar faturas: {erro_msg}\n\nTente novamente em alguns instantes."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
        
        elif etapa_atual == 'fatura_negocia_cpf':
            cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
            
            # Validar apenas formato básico (11 dígitos)
            cpf_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
            
            if not cpf_valido:
                resposta = "❌ CPF inválido. Por favor, digite o CPF completo (11 dígitos, apenas números):"
            else:
                logger.info(f"[Webhook] Buscando fatura via PLANO B (Nio Negocia) para CPF: {cpf_limpo}")
                try:
                    # Importar função do Plano B diretamente
                    import crm_app.services_nio as nio_services
                    
                    # Chamar diretamente o Plano B (sem tentar Plano A)
                    resultado_plano_b = nio_services._buscar_fatura_nio_negocia(
                        cpf_limpo,
                        numero_contrato=None,  # Pode ser passado depois se necessário
                        incluir_pdf=True,
                        mes_referencia=None
                    )
                    
                    if resultado_plano_b and (resultado_plano_b.get('valor') or resultado_plano_b.get('codigo_pix') or resultado_plano_b.get('codigo_barras')):
                        # Formatar como invoice para usar a função de formatação existente
                        # Converter data_vencimento para string se for date object
                        data_venc = resultado_plano_b.get('data_vencimento')
                        if data_venc and hasattr(data_venc, 'strftime'):
                            # Se for date object, converter para string YYYYMMDD
                            data_venc_str = data_venc.strftime('%Y%m%d')
                        else:
                            data_venc_str = data_venc
                        
                        invoice = {
                            'amount': resultado_plano_b.get('valor'),  # Campo esperado pela função de formatação
                            'valor': resultado_plano_b.get('valor'),  # Backup
                            'pix': resultado_plano_b.get('codigo_pix'),  # Campo esperado pela função de formatação
                            'codigo_pix': resultado_plano_b.get('codigo_pix'),  # Backup
                            'barcode': resultado_plano_b.get('codigo_barras'),  # Campo esperado pela função de formatação
                            'codigo_barras': resultado_plano_b.get('codigo_barras'),  # Backup
                            'data_vencimento': data_venc_str,  # String formatada
                            'due_date_raw': data_venc_str,  # Campo esperado pela função de formatação
                            'pdf_url': resultado_plano_b.get('pdf_url'),
                            'pdf_path': resultado_plano_b.get('pdf_path'),
                            'status': 'Pendente',
                            'reference_month': None,
                            'metodo_usado': 'nio_negocia'
                        }
                        
                        # Formatar resposta
                        resposta = _formatar_detalhes_fatura(invoice, cpf_limpo, incluir_pdf=True)
                        
                        # Adicionar informação sobre o método usado
                        resposta += f"\n\n🔧 *Método:* Plano B (Nio Negocia)"
                        
                        # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                        if invoice.get('pdf_path') or invoice.get('pdf_url'):
                            sessao.dados_temp = {'invoice_para_pdf': invoice}
                        else:
                            sessao.dados_temp = {}
                        sessao.etapa = 'inicial'
                        sessao.save()
                        
                        logger.info(f"[Webhook] ✅ Plano B (Nio Negocia) retornou dados válidos")
                    else:
                        # Formatar CPF para exibição
                        cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}"
                        resposta = f"🔎 Buscando faturas via Plano B (Nio Negocia) para o cliente {cpf_limpo}...\n\n❌ *CPF: {cpf_formatado}*\n\nNão foi possível encontrar faturas usando o método Nio Negocia.\n\nTente usar o comando *Fatura* para buscar pelo método padrão."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        logger.warning(f"[Webhook] ⚠️ Plano B (Nio Negocia) não retornou dados válidos")
                        
                except Exception as e:
                    logger.error(f"[Webhook] ❌ Erro ao buscar fatura via Plano B (Nio Negocia): {e}")
                    import traceback
                    traceback.print_exc()
                    resposta = f"❌ Erro ao buscar fatura via Plano B (Nio Negocia): {str(e)}\n\nTente novamente ou use o comando *Fatura* para buscar pelo método padrão."
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
        
        elif etapa_atual == 'material_buscar':
            try:
                busca_texto = (mensagem_texto or '').strip()
                if not busca_texto or len(busca_texto) < 2:
                    resposta = "❌ Por favor, digite pelo menos 2 caracteres para buscar:"
                    return _enviar_resposta_e_retornar(resposta)
                logger.info(f"[Webhook] Buscando materiais com tag: {busca_texto}")
                resposta = _buscar_record_apoia_por_texto(busca_texto, sessao)
                if resposta is None:
                    resposta = (
                        f"❌ *MATERIAL NÃO ENCONTRADO*\n\n"
                        f"Não encontrei materiais com a tag \"{busca_texto}\".\n\n"
                        "Tente buscar com outras palavras-chave."
                    )
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                return _enviar_resposta_e_retornar(resposta)
            except Exception as e:
                logger.exception("[Webhook] Erro ao buscar material: %s", e)
                resposta = f"❌ Erro ao buscar material: {str(e)}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return _enviar_resposta_e_retornar(resposta)
        
        elif etapa_atual == 'material_selecionar':
            try:
                numero_escolhido = mensagem_texto.strip()
                if not numero_escolhido:
                    resposta = None  # Mensagem vazia: não enviar erro
                elif not numero_escolhido.isdigit():
                    resposta = "❌ Por favor, digite apenas o NÚMERO do material (ex: 1, 2, 3...):"
                else:
                    from crm_app.models import RecordApoia
                    import base64
                    
                    # Buscar sessão diretamente do banco para garantir dados mais recentes
                    from crm_app.models import SessaoWhatsapp
                    sessao_atualizada = SessaoWhatsapp.objects.get(id=sessao.id)
                    dados_temp_atualizado = sessao_atualizada.dados_temp or {}
                    
                    logger.info(f"[Webhook] DEBUG material_selecionar - sessao.id: {sessao_atualizada.id}, etapa: {sessao_atualizada.etapa}")
                    logger.info(f"[Webhook] DEBUG material_selecionar - dados_temp do banco: {dados_temp_atualizado}")
                    logger.info(f"[Webhook] DEBUG material_selecionar - tipo de dados_temp: {type(dados_temp_atualizado)}")
                    
                    idx = int(numero_escolhido) - 1
                    arquivos_ids = dados_temp_atualizado.get('arquivos_ids', [])
                    
                    if not arquivos_ids or len(arquivos_ids) == 0:
                        logger.error(f"[Webhook] arquivos_ids está vazio na sessão! dados_temp: {dados_temp_atualizado}, sessao.id: {sessao_atualizada.id}")
                        logger.error(f"[Webhook] DEBUG - Tentando buscar sessão completa do banco novamente...")
                        # Última tentativa: buscar sessão completa novamente
                        try:
                            sessao_db = SessaoWhatsapp.objects.values('dados_temp', 'etapa').get(id=sessao_atualizada.id)
                            logger.error(f"[Webhook] DEBUG - dados_temp do values(): {sessao_db.get('dados_temp')}, etapa: {sessao_db.get('etapa')}")
                        except Exception as db_error:
                            logger.error(f"[Webhook] DEBUG - Erro ao buscar do banco: {db_error}")
                        
                        resposta = "❌ Erro: Lista de materiais não encontrada. Por favor, busque novamente."
                        sessao_atualizada.etapa = 'inicial'
                        sessao_atualizada.dados_temp = {}
                        sessao_atualizada.save()
                    elif idx < 0 or idx >= len(arquivos_ids):
                        # Não responder: evita mensagem fantasma (webhook duplicado)
                        logger.info(f"[Webhook] material_selecionar: número fora do intervalo ({numero_escolhido}), ignorando sem resposta.")
                        resposta = None
                    else:
                        arquivo_id = arquivos_ids[idx]
                        arquivo = RecordApoia.objects.get(id=arquivo_id, ativo=True)
                        arquivo.downloads_count += 1
                        arquivo.save(update_fields=['downloads_count'])
                        
                        try:
                            # Ler arquivo do FileField
                            arquivo_field = arquivo.arquivo
                            if not arquivo_field or not arquivo_field.name:
                                resposta = f"❌ Arquivo \"{arquivo.titulo}\" não encontrado."
                                sessao.etapa = 'inicial'
                                sessao.dados_temp = {}
                                sessao.save()
                            else:
                                try:
                                    # Tentar ler o arquivo usando o método do FileField
                                    try:
                                        arquivo_field.open('rb')
                                        arquivo_bytes = arquivo_field.read()
                                        arquivo_field.close()
                                    except (FileNotFoundError, IOError, OSError) as e:
                                        logger.error(f"[Webhook] Erro ao ler arquivo (método 1) {arquivo_field.name}: {e}")
                                        # Tentar usar storage como fallback
                                        from django.core.files.storage import default_storage
                                        if default_storage.exists(arquivo_field.name):
                                            with default_storage.open(arquivo_field.name, 'rb') as f:
                                                arquivo_bytes = f.read()
                                        else:
                                            raise e
                                    
                                    arquivo_b64 = base64.b64encode(arquivo_bytes).decode('utf-8')
                                    nome_arquivo = arquivo.nome_original
                                    
                                    # Preparar mensagem de resposta
                                    if arquivo.tipo_arquivo == 'IMAGEM':
                                        resposta = f"✅ *MATERIAL SELECIONADO*\n\n📷 {arquivo.titulo}"
                                        # Armazenar dados do arquivo para envio após a mensagem
                                        sessao.dados_temp = {
                                            'material_para_envio': {
                                                'tipo': 'IMAGEM',
                                                'base64': arquivo_b64,
                                                'nome': nome_arquivo,
                                                'titulo': arquivo.titulo,
                                                'descricao': arquivo.descricao
                                            }
                                        }
                                    else:
                                        # DOCUMENTO: Verificar se é grande e fazer upload para R2 se necessário
                                        tamanho_bytes = len(arquivo_bytes) if arquivo_bytes else (len(arquivo_b64) * 3 // 4)
                                        tamanho_mb = tamanho_bytes / (1024 * 1024)
                                        
                                        pdf_url = None
                                        usar_url = tamanho_mb > 5  # Usar URL se arquivo > 5MB
                                        
                                        if usar_url:
                                            logger.info(f"[Webhook] Arquivo grande ({tamanho_mb:.2f} MB), fazendo upload para R2...")
                                            try:
                                                from crm_app.cloudflare_r2_service import CloudflareR2Storage
                                                from io import BytesIO
                                                
                                                file_obj = BytesIO(arquivo_bytes) if arquivo_bytes else BytesIO(base64.b64decode(arquivo_b64))
                                                
                                                storage = CloudflareR2Storage()
                                                pdf_url = storage.upload_file_and_get_download_url(
                                                    file_obj, 
                                                    folder_name='WhatsApp_Materiais',
                                                    filename=nome_arquivo
                                                )
                                                
                                                logger.info(f"[Webhook] ✅ Upload para R2 concluído: {pdf_url}")
                                                print(f"[Webhook] ✅ Upload R2: {pdf_url}")
                                            except Exception as e:
                                                logger.error(f"[Webhook] ❌ Erro ao fazer upload para R2: {e}")
                                                logger.warning(f"[Webhook] ⚠️ Continuando com base64 como fallback")
                                                print(f"[Webhook] ❌ Erro R2: {e}, usando base64")
                                                pdf_url = None
                                        
                                        resposta = f"✅ *MATERIAL SELECIONADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}"
                                        # Armazenar dados do arquivo para envio após a mensagem
                                        material_data = {
                                            'tipo': 'DOCUMENTO',
                                            'nome': nome_arquivo,
                                            'titulo': arquivo.titulo,
                                            'tipo_display': arquivo.get_tipo_arquivo_display()
                                        }
                                        
                                        # Adicionar URL se disponível (preferível), senão base64
                                        if pdf_url:
                                            material_data['url'] = pdf_url
                                            logger.info(f"[Webhook] Material preparado com URL (R2)")
                                        else:
                                            material_data['base64'] = arquivo_b64
                                            logger.info(f"[Webhook] Material preparado com base64")
                                        
                                        sessao.dados_temp = {
                                            'material_para_envio': material_data
                                        }
                                    
                                    sessao.etapa = 'inicial'
                                    sessao.save()
                                    
                                    # Incrementar contador de downloads
                                    arquivo.downloads_count += 1
                                    arquivo.save(update_fields=['downloads_count'])
                                except (FileNotFoundError, IOError, OSError) as e:
                                    logger.error(f"[Webhook] Erro ao acessar arquivo {arquivo_field.name if arquivo_field else 'N/A'}: {e}")
                                    resposta = f"❌ Arquivo \"{arquivo.titulo}\" não encontrado no servidor. O arquivo pode ter sido removido ou há um problema no armazenamento."
                                    sessao.etapa = 'inicial'
                                    sessao.dados_temp = {}
                                    sessao.save()
                        except Exception as e:
                            logger.error(f"[Webhook] Erro ao enviar arquivo selecionado: {e}")
                            import traceback
                            traceback.print_exc()
                            resposta = f"❌ Erro ao processar arquivo: {str(e)}"
                            sessao.etapa = 'inicial'
                            sessao.dados_temp = {}
                            sessao.save()
            except Exception as e:
                logger.error(f"[Webhook] Erro ao processar seleção de material: {e}")
                resposta = f"❌ Erro ao processar seleção: {str(e)}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        elif etapa_atual == 'fatura_selecionar':
            try:
                sessao.refresh_from_db()
                dados_temp = sessao.dados_temp or {}
                if dados_temp.get('processando_pdf'):
                    resposta = "⏳ Ainda processando sua fatura. Aguarde um momento..."
                    return _enviar_resposta_e_retornar(resposta)
                numero_escolhido = mensagem_texto.strip()
                if not numero_escolhido:
                    resposta = None  # Mensagem vazia: não enviar erro para não duplicar
                elif not numero_escolhido.isdigit():
                    resposta = "❌ Por favor, digite apenas o NÚMERO da fatura (ex: 1, 2, 3...):"
                else:
                    idx = int(numero_escolhido) - 1
                    faturas = dados_temp.get('faturas', [])
                    
                    if idx < 0 or idx >= len(faturas):
                        # Não responder: evita mensagem fantasma (webhook duplicado com 0, 3, etc.)
                        logger.info(f"[Webhook] fatura_selecionar: número fora do intervalo ({numero_escolhido}), ignorando sem resposta.")
                        resposta = None
                    else:
                        invoice = faturas[idx]
                        cpf = dados_temp.get('cpf', '')
                        # Marcar logo para evitar processamento duplicado (webhook em duplicidade)
                        sessao.dados_temp = (sessao.dados_temp or {}) | {'processando_pdf': True}
                        sessao.save(update_fields=['dados_temp', 'updated_at'])
                        
                        # Tentar buscar PDF via API primeiro (mais rápido)
                        try:
                            from crm_app.nio_api import get_invoice_pdf_url
                            token = dados_temp.get('token')
                            api_base = dados_temp.get('api_base')
                            session_id = dados_temp.get('session_id')
                            
                            if token and api_base and session_id:
                                import requests
                                session = requests.Session()
                                pdf_url = get_invoice_pdf_url(
                                    api_base, token, session_id,
                                    invoice.get('debt_id', ''),
                                    invoice.get('invoice_id', ''),
                                    cpf,
                                    invoice.get('reference_month', ''),
                                    session
                                )
                                if pdf_url:
                                    invoice['pdf_url'] = pdf_url
                                    logger.info(f"[Webhook] PDF encontrado via API: {pdf_url[:100]}...")
                        except Exception as e:
                            logger.warning(f"[Webhook] Erro ao buscar PDF via API: {e}")
                        
                        # Se não encontrou via API, tenta baixar como humano (Playwright)
                        if not invoice.get('pdf_url') and not invoice.get('pdf_path'):
                            try:
                                # Importar função diretamente do módulo (função privada)
                                import crm_app.services_nio as nio_services
                                mes_ref = invoice.get('reference_month', '')
                                data_venc = invoice.get('due_date_raw') or invoice.get('data_vencimento', '')
                                
                                logger.info(f"[Webhook] Tentando baixar PDF como humano...")
                                logger.info(f"[Webhook] Parâmetros: CPF={cpf}, mes_ref={mes_ref}, data_venc={data_venc}")
                                
                                headless_pdf = getattr(settings, 'PAP_HEADLESS', True)
                                # Passar token/session se tiver na sessão (lista de faturas guarda isso)
                                api_base = dados_temp.get('api_base')
                                token = dados_temp.get('token')
                                session_id = dados_temp.get('session_id')
                                pdf_result = nio_services._baixar_pdf_como_humano(
                                    cpf, mes_ref, data_venc,
                                    headless=headless_pdf,
                                    api_base=api_base,
                                    token=token,
                                    session_id=session_id,
                                )
                                
                                # Remover flag de processamento após concluir
                                if sessao:
                                    sessao.dados_temp.pop('processando_pdf', None)
                                    sessao.save(update_fields=['dados_temp', 'updated_at'])
                                    print(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                    logger.info(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                
                                if pdf_result:
                                    # pdf_result pode ser dict (com local_path e onedrive_url) ou string (caminho antigo)
                                    if isinstance(pdf_result, dict):
                                        invoice['pdf_path'] = pdf_result.get('local_path')
                                        invoice['pdf_onedrive_url'] = pdf_result.get('onedrive_url')
                                        invoice['pdf_filename'] = pdf_result.get('filename')
                                        
                                        if pdf_result.get('onedrive_url'):
                                            logger.info(f"[Webhook] ✅ PDF baixado e enviado para OneDrive: {pdf_result['onedrive_url']}")
                                        else:
                                            logger.info(f"[Webhook] ✅ PDF baixado localmente: {pdf_result['local_path']}")
                                    else:
                                        # Compatibilidade com formato antigo (string)
                                        invoice['pdf_path'] = pdf_result
                                        logger.info(f"[Webhook] ✅ PDF baixado com sucesso: {pdf_result}")
                                else:
                                    logger.warning(f"[Webhook] ⚠️ Falha ao baixar PDF como humano - retornou None")
                            except Exception as e:
                                logger.error(f"[Webhook] ❌ Erro ao baixar PDF como humano: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        # Formatar resposta com detalhes completos
                        resposta = _formatar_detalhes_fatura(invoice, cpf, incluir_pdf=True)
                        
                        # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                        if invoice.get('pdf_path') or invoice.get('pdf_url'):
                            sessao.dados_temp = {'invoice_para_pdf': invoice}
                        else:
                            sessao.dados_temp = {}
                        sessao.etapa = 'inicial'
                        sessao.save()
            except Exception as e:
                logger.error(f"[Webhook] Erro ao processar seleção de fatura: {e}")
                resposta = f"❌ Erro ao processar seleção: {str(e)}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        # === PROCESSAMENTO DE ETAPAS DE VENDA ===
        elif etapa_atual.startswith('venda_'):
            logger.info(f"[Webhook] Processando etapa de venda: {etapa_atual}")
            resposta = _processar_etapa_venda(telefone_formatado, mensagem_texto, sessao, etapa_atual, webhook_t0=_webhook_t0)
            resposta = _venda_tentar_enviar_resposta_com_botoes(telefone_formatado, sessao, resposta)
        
        else:
            # Menu só aparece quando o usuário pede (MENU/AJUDA). Mensagem não reconhecida não gera resposta.
            # Exceção: SIM em etapa inicial (sem confirmação pendente) → responder para não deixar usuário sem retorno
            if etapa_atual == 'inicial' and mensagem_limpa in ['SIM', 'S']:
                resposta = "Não há confirmação pendente no momento. Digite *MENU* para ver as opções."
            else:
                resposta = None
                # Fallback: mensagem livre na etapa inicial → IA (Groq/Gemini) responde no contexto do sistema
                if etapa_atual == 'inicial' and mensagem_texto and mensagem_texto.strip():
                    try:
                        from crm_app.services.whatsapp_ia_config_service import ia_vendedores_duvidas_habilitada

                        if ia_vendedores_duvidas_habilitada():
                            from crm_app.ai_chat_service import responder_com_ia
                            nome_vendedor = (usuario_whatsapp.get_full_name() or usuario_whatsapp.username or "").strip() or None
                            resposta_ia = responder_com_ia(mensagem_texto.strip(), nome_vendedor=nome_vendedor)
                            if resposta_ia:
                                resposta = resposta_ia
                                logger.info("[Webhook] Resposta enviada via IA (contexto do sistema).")
                            else:
                                logger.info("[Webhook] IA não retornou resposta para mensagem livre (etapa inicial). Enviando fallback.")
                                resposta = "Olá! Digite *MENU* para ver os comandos disponíveis."
                    except Exception as e:
                        logger.warning("[Webhook] Fallback IA falhou: %s", e)
                        resposta = "Olá! Digite *MENU* para ver os comandos disponíveis."
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
        
        # PRIMEIRO: Verificar se já há um processamento em andamento para evitar duplicação
        if sessao and sessao.dados_temp.get('processando_pdf'):
            tempo_processamento = timezone.now() - sessao.updated_at
            if tempo_processamento.total_seconds() < 300:  # Menos de 5 minutos
                print(f"[DEBUG] ⚠️ Processamento de PDF já em andamento para {telefone_formatado} (há {tempo_processamento.total_seconds():.1f}s), ignorando webhook duplicado")
                logger.warning(f"[Webhook] Processamento de PDF já em andamento para {telefone_formatado} (há {tempo_processamento.total_seconds():.1f}s), ignorando webhook duplicado")
                return {'status': 'ok', 'mensagem': 'Processamento em andamento'}
            else:
                # Se passou mais de 5 minutos, limpar a flag (pode ter travado)
                print(f"[DEBUG] ⚠️ Flag processando_pdf antiga (há {tempo_processamento.total_seconds():.1f}s), limpando...")
                logger.warning(f"[Webhook] Flag processando_pdf antiga (há {tempo_processamento.total_seconds():.1f}s), limpando...")
                sessao.dados_temp.pop('processando_pdf', None)
                sessao.save(update_fields=['dados_temp', 'updated_at'])
        
        # PRIMEIRO: Verificar se há PDF/material para enviar com legenda (resposta do bot)
        arquivo_enviado = False
        pdf_enviado_com_caption = False
        material_enviado_com_caption = False
        
        if sessao:
            invoice_para_pdf = sessao.dados_temp.get('invoice_para_pdf')
            material_para_envio = sessao.dados_temp.get('material_para_envio')
            
            if invoice_para_pdf and resposta:
                print(f"[DEBUG PDF] 🔍 ETAPA 5: PDF detectado na sessão, preparando envio com caption...")
                print(f"[DEBUG PDF] invoice_para_pdf keys: {list(invoice_para_pdf.keys())}")
                print(f"[DEBUG PDF] pdf_path={invoice_para_pdf.get('pdf_path')}")
                print(f"[DEBUG PDF] pdf_url={invoice_para_pdf.get('pdf_url')}")
                print(f"[DEBUG PDF] pdf_onedrive_url={invoice_para_pdf.get('pdf_onedrive_url')}")
                logger.info(f"[DEBUG PDF] 🔍 ETAPA 5: PDF detectado, preparando envio com caption...")
                logger.info(f"[DEBUG PDF] invoice_para_pdf keys: {list(invoice_para_pdf.keys())}")
                logger.info(f"[DEBUG PDF] pdf_path={invoice_para_pdf.get('pdf_path')}, pdf_url={invoice_para_pdf.get('pdf_url')}, pdf_onedrive_url={invoice_para_pdf.get('pdf_onedrive_url')}")
                
                # VALIDAÇÃO: Verificar se PDF existe e não está vazio antes de enviar
                pdf_path = invoice_para_pdf.get('pdf_path')
                pdf_valido = False
                
                if pdf_path and os.path.exists(pdf_path):
                    tamanho = os.path.getsize(pdf_path)
                    print(f"[DEBUG PDF] 📊 Validando PDF antes de enviar: {pdf_path}, tamanho: {tamanho} bytes")
                    logger.info(f"[DEBUG PDF] 📊 Validando PDF antes de enviar: {pdf_path}, tamanho: {tamanho} bytes")
                    
                    if tamanho < 100:
                        print(f"[DEBUG PDF] ❌ PDF muito pequeno ({tamanho} bytes), provavelmente vazio")
                        logger.error(f"[DEBUG PDF] ❌ PDF muito pequeno ({tamanho} bytes), provavelmente vazio")
                        # Remover PDF inválido da sessão
                        invoice_para_pdf.pop('pdf_path', None)
                    else:
                        # Verificar cabeçalho PDF
                        try:
                            with open(pdf_path, 'rb') as f:
                                header = f.read(4)
                                if not header.startswith(b'%PDF'):
                                    print(f"[DEBUG PDF] ❌ PDF não tem cabeçalho válido")
                                    logger.error(f"[DEBUG PDF] ❌ PDF não tem cabeçalho válido")
                                    invoice_para_pdf.pop('pdf_path', None)
                                else:
                                    pdf_valido = True
                                    print(f"[DEBUG PDF] ✅ PDF válido: {tamanho} bytes")
                                    logger.info(f"[DEBUG PDF] ✅ PDF válido: {tamanho} bytes")
                        except Exception as e_val:
                            print(f"[DEBUG PDF] ❌ Erro ao validar PDF: {e_val}")
                            logger.error(f"[DEBUG PDF] ❌ Erro ao validar PDF: {e_val}")
                            invoice_para_pdf.pop('pdf_path', None)
                
                # Se PDF é válido, enviar com a resposta como caption
                if pdf_valido or invoice_para_pdf.get('pdf_url') or invoice_para_pdf.get('pdf_onedrive_url'):
                    # Idempotência: evitar enviar PDF+mensagem duas vezes para o mesmo messageId (webhook duplicado)
                    message_id_pdf = (data or {}).get('messageId')
                    skip_pdf_duplicate = False
                    if message_id_pdf:
                        with _webhook_reply_lock:
                            now = time.time()
                            expired = [mid for mid, ts in list(_webhook_reply_message_ids.items()) if now - ts > _webhook_reply_ttl]
                            for mid in expired:
                                del _webhook_reply_message_ids[mid]
                            if message_id_pdf in _webhook_reply_message_ids:
                                skip_pdf_duplicate = True
                                logger.info(f"[Webhook] Resposta PDF já enviada para messageId={message_id_pdf[:20]}..., ignorando duplicata (bloco PDF).")
                    if skip_pdf_duplicate:
                        resposta = None
                        pdf_enviado_com_caption = True
                        print(f"[DEBUG PDF] ⏭️ Duplicata ignorada (messageId já respondido)")
                        logger.info(f"[DEBUG PDF] ⏭️ Duplicata ignorada (messageId já respondido)")
                    else:
                        if message_id_pdf:
                            with _webhook_reply_lock:
                                _webhook_reply_message_ids[message_id_pdf] = time.time()
                        # Se temos PDF local e não temos URL, gerar URL pública (serve-pdf) para Z-API buscar
                        if pdf_valido and not invoice_para_pdf.get('pdf_url') and not invoice_para_pdf.get('pdf_onedrive_url') and request:
                            try:
                                pdf_filename = os.path.basename(pdf_path)
                                serve_url = _build_serve_pdf_url(request, pdf_filename)
                                if serve_url:
                                    invoice_para_pdf["pdf_url"] = serve_url
                                    print(f"[DEBUG PDF] 📎 URL do PDF para Z-API: {serve_url[:80]}...")
                                    logger.info(f"[DEBUG PDF] PDF será enviado via URL (serve-pdf)")
                            except Exception as e_build:
                                print(f"[DEBUG PDF] ⚠️ Não foi possível gerar URL do PDF: {e_build}")
                                logger.warning(f"[DEBUG PDF] URL do PDF não gerada: {e_build}")
                        # Usar a resposta formatada como caption
                        caption_para_pdf = resposta
                        print(f"[DEBUG PDF] 📝 Enviando PDF com caption (primeiros 100 chars): {caption_para_pdf[:100]}...")
                        logger.info(f"[DEBUG PDF] 📝 Enviando PDF com caption")
                        
                        resultado_envio = _enviar_pdf_whatsapp(whatsapp_service, telefone_formatado, invoice_para_pdf, caption=caption_para_pdf)
                        print(f"[DEBUG PDF] Resultado do envio: {resultado_envio}")
                        logger.info(f"[DEBUG PDF] Resultado do envio: {resultado_envio}")
                        if resultado_envio:
                            arquivo_enviado = True
                            pdf_enviado_com_caption = True
                            # PDF já enviado com caption no payload; não enviar texto em separado (evita 2ª mensagem duplicada)
                            # IMPORTANTE: Limpar resposta para não enviar mensagem duplicada
                            resposta = None
                            pdf_enviado_com_caption = True  # Garantir que está marcado
                            print(f"[DEBUG PDF] ✅ PDF e mensagem enviados, resposta limpa (None), pdf_enviado_com_caption={pdf_enviado_com_caption}")
                            logger.info(f"[DEBUG PDF] ✅ PDF e mensagem enviados, resposta limpa (None), pdf_enviado_com_caption={pdf_enviado_com_caption}")
                        else:
                            # Se PDF não foi enviado, manter resposta para enviar normalmente
                            print(f"[DEBUG PDF] ⚠️ PDF não foi enviado, resposta será enviada normalmente")
                            logger.warning(f"[DEBUG PDF] ⚠️ PDF não foi enviado, resposta será enviada normalmente")
                    
            elif material_para_envio:
                caption_material = None
                if resposta and resposta.strip():
                    _elapsed_mat = time.monotonic() - _webhook_t0
                    caption_material = (resposta.strip() + f"\n\n⏱ _{_elapsed_mat:.1f}s_").strip()
                logger.info("[Webhook] Material detectado, enviando com legenda...")
                if _enviar_material_record_apoia_whatsapp(
                    whatsapp_service,
                    telefone_formatado,
                    material_para_envio,
                    caption=caption_material,
                ):
                    arquivo_enviado = True
                    material_enviado_com_caption = True
                    resposta = None
                    if sessao:
                        dados = dict(sessao.dados_temp or {})
                        dados.pop('material_para_envio', None)
                        sessao.dados_temp = dados
                        sessao.save(update_fields=['dados_temp'])
        
        # DEPOIS: Enviar resposta via WhatsApp (só se não foi enviada como legenda do PDF/material)
        # Idempotência: não enviar duas vezes para o mesmo messageId (Z-API pode reenviar o webhook)
        message_id = (data or {}).get('messageId')
        skip_duplicate = False
        if message_id:
            with _webhook_reply_lock:
                now = time.time()
                # Limpar entradas expiradas
                expired = [mid for mid, ts in _webhook_reply_message_ids.items() if now - ts > _webhook_reply_ttl]
                for mid in expired:
                    del _webhook_reply_message_ids[mid]
                if message_id in _webhook_reply_message_ids:
                    skip_duplicate = True
                    logger.info(f"[Webhook] Resposta já enviada para messageId={message_id[:20]}..., ignorando duplicata.")
        # IMPORTANTE: Verificar se resposta não foi enviada como legenda de PDF/material
        if (
            resposta
            and resposta.strip()
            and not pdf_enviado_com_caption
            and not material_enviado_com_caption
            and not skip_duplicate
        ):
            print(
                f"[DEBUG] Enviando resposta final: pdf_caption={pdf_enviado_com_caption}, "
                f"material_caption={material_enviado_com_caption}"
            )
            logger.info(
                "[Webhook] Enviando resposta final (texto): pdf_caption=%s, material_caption=%s",
                pdf_enviado_com_caption,
                material_enviado_com_caption,
            )
            try:
                # Provisório: tempo desde o recebimento da mensagem até esta resposta
                _elapsed = time.monotonic() - _webhook_t0
                resposta_com_tempo = (resposta.strip() + f"\n\n⏱ _{_elapsed:.1f}s_").strip()
                logger.info(f"[Webhook] Preparando para enviar resposta para {telefone_formatado}")
                logger.info(f"[Webhook] Resposta a ser enviada: {resposta_com_tempo[:100]}...")
                
                # Dividir mensagem se muito longa (limite WhatsApp ~4096 caracteres)
                mensagens = [resposta_com_tempo[i:i+4000] for i in range(0, len(resposta_com_tempo), 4000)]
                logger.info(f"[Webhook] Dividindo em {len(mensagens)} mensagem(ns)")
                
                for idx, msg in enumerate(mensagens):
                    logger.info(f"[Webhook] Enviando mensagem {idx+1}/{len(mensagens)} para {telefone_formatado}")
                    sucesso, resultado = whatsapp_service.enviar_mensagem_texto(telefone_formatado, msg)
                    if sucesso:
                        logger.info(f"[Webhook] Mensagem {idx+1} enviada com sucesso: {resultado}")
                    else:
                        logger.error(f"[Webhook] Erro ao enviar mensagem {idx+1}: {resultado}")
                
                logger.info(f"[Webhook] Resposta enviada para {telefone_formatado}")
                # Marcar como já respondido para este messageId (evitar duplicata se Z-API reenviar o webhook)
                if message_id:
                    with _webhook_reply_lock:
                        _webhook_reply_message_ids[message_id] = time.time()
                
                # Limpar dados temporários APENAS se arquivo foi enviado E não estamos na etapa material_selecionar
                # (precisamos manter arquivos_ids na etapa material_selecionar para o usuário escolher)
                if arquivo_enviado and sessao and sessao.etapa != 'material_selecionar':
                    sessao.dados_temp = {}
                    sessao.save(update_fields=['dados_temp'])
                    logger.info(f"[Webhook] Dados temporários limpos após envio de arquivo")
            except Exception as e:
                logger.error(f"[Webhook] Erro ao enviar resposta: {e}")
                import traceback
                traceback.print_exc()
                return {'status': 'erro', 'mensagem': f'Erro ao enviar resposta: {str(e)}'}
        
        return {'status': 'ok', 'mensagem': 'Processado com sucesso'}
    
    except Exception as e:
        logger.exception(f"[Webhook] Erro ao processar mensagem: {e}")
        return {'status': 'erro', 'mensagem': str(e)}
