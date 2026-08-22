# crm_app/pool_bo_pap.py
"""
Pool de logins BackOffice para automação PAP.

Vendedores (perfil Vendedor) não conseguem fazer vendas pelo site pap.niointernet.com.br.
Usuários com autorizar_venda_sem_auditoria usam logins de perfil BackOffice,
com seleção randômica entre os disponíveis e bloqueio para evitar conflitos.

Inclui fila de espera: quando todos os logins estão em uso, o usuário entra na fila
e é avisado por WhatsApp quando um login for liberado.
"""
import logging
import random
import re
from datetime import timedelta
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Timeout em minutos - locks mais antigos são considerados órfãos (sessão travou)
LOCK_TIMEOUT_MINUTOS = 30

# Mensagem retornada quando todos os BOs estão ocupados (webhook usa para detectar e enfileirar)
MSG_TODOS_ACESSOS_EM_USO = (
    "⚠️ *TODOS OS ACESSOS BACKOFFICE ESTÃO EM USO*\n\n"
    "No momento todos os logins de backoffice estão ocupados com outras vendas.\n\n"
    "Aguarde alguns minutos e tente novamente.\n\n"
    "Digite *VENDER* para tentar novamente."
)


def _limpar_locks_expirados():
    """Remove registros de BO em uso há mais de LOCK_TIMEOUT_MINUTOS."""
    from crm_app.models import PapBoEmUso

    limite = timezone.now() - timedelta(minutes=LOCK_TIMEOUT_MINUTOS)
    deletados = PapBoEmUso.objects.filter(locked_at__lt=limite).delete()
    if deletados[0] > 0:
        logger.info(f"[POOL BO] Liberados {deletados[0]} lock(s) expirado(s)")
    return deletados[0]


def _normalizar_telefone(telefone: str) -> str:
    return re.sub(r"\D", "", str(telefone or ""))


def _identificar_usuario_por_telefone(telefone: str):
    """
    Tenta identificar o usuário que chamou a automação a partir do telefone
    da sessão WhatsApp, considerando os campos de WhatsApp cadastrados.
    """
    from django.db.models import Q
    from usuarios.models import Usuario

    telefone_limpo = _normalizar_telefone(telefone)
    if not telefone_limpo:
        return None

    sufixo = telefone_limpo[-8:] if len(telefone_limpo) >= 8 else telefone_limpo
    filtro_base = Q()
    if sufixo:
        filtro_base = (
            Q(tel_whatsapp__endswith=sufixo)
            | Q(tel_whatsapp_2__endswith=sufixo)
            | Q(tel_whatsapp_3__endswith=sufixo)
        )

    candidatos = Usuario.objects.filter(is_active=True).filter(filtro_base).only(
        "id", "tel_whatsapp", "tel_whatsapp_2", "tel_whatsapp_3"
    )
    for usuario in candidatos:
        telefones_usuario = [
            _normalizar_telefone(usuario.tel_whatsapp),
            _normalizar_telefone(usuario.tel_whatsapp_2),
            _normalizar_telefone(usuario.tel_whatsapp_3),
        ]
        if telefone_limpo in telefones_usuario:
            return usuario
    return None


def _registrar_historico_consulta_pap(
    *,
    vendedor_telefone: str,
    bo_usuario,
    tipo_automacao: Optional[str],
) -> None:
    from crm_app.models import HistoricoConsultaAutomacaoPAP

    try:
        solicitante = _identificar_usuario_por_telefone(vendedor_telefone)
        HistoricoConsultaAutomacaoPAP.objects.create(
            solicitado_por=solicitante,
            telefone_solicitante=vendedor_telefone or "",
            tipo_automacao=tipo_automacao or "",
            login_pap_utilizado=bo_usuario,
            matricula_pap_utilizada=(bo_usuario.matricula_pap or ""),
            status_execucao=HistoricoConsultaAutomacaoPAP.STATUS_PENDENTE,
        )
    except Exception as exc:
        logger.warning("[POOL BO] Falha ao registrar histórico de consulta PAP: %s", exc)


def atualizar_historico_consulta_pap_resultado(
    *,
    vendedor_telefone: str,
    bo_usuario,
    tipo_automacao: Optional[str],
    sucesso: bool,
    mensagem_resultado: Optional[str] = None,
) -> None:
    """
    Atualiza o resultado final da consulta no histórico de automações PAP.
    Busca o registro mais recente em estado pendente para a combinação telefone/BO/tipo.
    """
    from crm_app.models import HistoricoConsultaAutomacaoPAP

    try:
        status = (
            HistoricoConsultaAutomacaoPAP.STATUS_SUCESSO
            if sucesso
            else HistoricoConsultaAutomacaoPAP.STATUS_ERRO
        )
        qs = (
            HistoricoConsultaAutomacaoPAP.objects.filter(
                telefone_solicitante=vendedor_telefone or "",
                login_pap_utilizado=bo_usuario,
                tipo_automacao=tipo_automacao or "",
                status_execucao=HistoricoConsultaAutomacaoPAP.STATUS_PENDENTE,
            )
            .order_by("-criado_em")
        )
        item = qs.first()
        if not item:
            return
        item.status_execucao = status
        item.mensagem_resultado = (mensagem_resultado or "")[:1000]
        item.save(update_fields=["status_execucao", "mensagem_resultado", "atualizado_em"])
    except Exception as exc:
        logger.warning("[POOL BO] Falha ao atualizar histórico de consulta PAP: %s", exc)


def limpar_sessoes_expiradas():
    """
    Limpa sessões BO (PapBoEmUso) com mais de LOCK_TIMEOUT_MINUTOS.
    Chamada automaticamente em obter_login_bo(); pode ser usada em cron ou manualmente.
    Retorna o número de registros removidos.
    """
    return _limpar_locks_expirados()


# Tipos de automação PAP (usados em obter_login_bo e PapBoEmUso)
TIPO_AUTOMACAO_VENDER = 'vender'
TIPO_AUTOMACAO_CREDITO = 'credito'
TIPO_AUTOMACAO_PEDIDO = 'pedido'
TIPO_AUTOMACAO_STATUS = 'status'

# Mensagem quando não há nenhum login BO liberado para aquela automação
def _msg_nenhum_bo_para_automacao(tipo_automacao: str) -> str:
    nomes = {
        TIPO_AUTOMACAO_VENDER: 'VENDER',
        TIPO_AUTOMACAO_CREDITO: 'CRÉDITO',
        TIPO_AUTOMACAO_PEDIDO: 'PEDIDO',
        TIPO_AUTOMACAO_STATUS: 'STATUS',
    }
    nome = nomes.get(tipo_automacao, tipo_automacao)
    return (
        f"⚠️ *Nenhum login BackOffice está liberado para esta ação ({nome})*\n\n"
        "Entre em contato com o administrador para liberar logins para esta automação na Governança (Logins PAP)."
    )


def obter_login_bo(
    vendedor_telefone: str,
    sessao_whatsapp_id: Optional[int] = None,
    tipo_automacao: Optional[str] = None,
    contador_uso_por_bo: Optional[dict] = None,
) -> Tuple[Optional["Usuario"], Optional[str]]:
    """
    Obtém um login BackOffice disponível para uso na automação PAP.

    Usa seleção randômica entre os BOs livres para o tipo de automação.
    Garante que o próximo vendedor não pegue o mesmo BO que outro em uso.

    Args:
        vendedor_telefone: Telefone do vendedor que está iniciando a ação
        sessao_whatsapp_id: ID da SessaoWhatsapp (opcional, para rastreamento)
        tipo_automacao: 'vender' | 'credito' | 'pedido' | 'status'. Se None, considera
            qualquer BO com login_pap_disponivel_para_automacao (comportamento legado).
        contador_uso_por_bo: opcional — dict {bo_id: n}; prioriza BOs com menor uso (sync noturno).

    Returns:
        (bo_usuario, None) em sucesso
        (None, "mensagem_erro") quando todos os BOs estão ocupados ou nenhum liberado para essa automação
    """
    from usuarios.models import Usuario
    from crm_app.models import PapBoEmUso

    _limpar_locks_expirados()

    # IDs dos BOs atualmente em uso
    ids_em_uso = set(
        PapBoEmUso.objects.values_list('bo_usuario_id', flat=True)
    )

    # Buscar usuários BackOffice com matrícula e senha configuradas e com login liberado para o bot
    bo_queryset = Usuario.objects.filter(
        perfil__cod_perfil__iexact='backoffice',
        is_active=True,
        matricula_pap__isnull=False,
        login_pap_disponivel_para_automacao=True,
    ).exclude(
        matricula_pap='',
    ).exclude(
        senha_pap__isnull=True,
    ).exclude(
        senha_pap='',
    )

    # Filtrar por automação: só BOs que têm o flag correspondente
    if tipo_automacao:
        if tipo_automacao == TIPO_AUTOMACAO_VENDER:
            bo_queryset = bo_queryset.filter(pap_automacao_vender=True)
        elif tipo_automacao == TIPO_AUTOMACAO_CREDITO:
            bo_queryset = bo_queryset.filter(pap_automacao_credito=True)
        elif tipo_automacao == TIPO_AUTOMACAO_PEDIDO:
            bo_queryset = bo_queryset.filter(pap_automacao_pedido=True)
        elif tipo_automacao == TIPO_AUTOMACAO_STATUS:
            bo_queryset = bo_queryset.filter(pap_automacao_status=True)

    # Excluir os que já estão em uso
    if ids_em_uso:
        bo_queryset = bo_queryset.exclude(id__in=ids_em_uso)

    bo_list = list(bo_queryset)
    if not bo_list:
        if tipo_automacao:
            return (None, _msg_nenhum_bo_para_automacao(tipo_automacao))
        return (None, MSG_TODOS_ACESSOS_EM_USO)

    if contador_uso_por_bo:
        bo_list.sort(key=lambda b: contador_uso_por_bo.get(b.id, 0))
    else:
        random.shuffle(bo_list)

    for bo_usuario in bo_list:
        try:
            with transaction.atomic():
                PapBoEmUso.objects.create(
                    bo_usuario=bo_usuario,
                    vendedor_telefone=vendedor_telefone,
                    sessao_whatsapp_id=sessao_whatsapp_id,
                    tipo_automacao=tipo_automacao or '',
                )
            logger.info(
                f"[POOL BO] BO {bo_usuario.username} (matricula {bo_usuario.matricula_pap}) "
                f"alocado para {vendedor_telefone} (automação={tipo_automacao or 'qualquer'})"
            )
            _registrar_historico_consulta_pap(
                vendedor_telefone=vendedor_telefone,
                bo_usuario=bo_usuario,
                tipo_automacao=tipo_automacao,
            )
            return bo_usuario, None
        except Exception as e:
            logger.debug(f"[POOL BO] BO {bo_usuario.id} indisponível: {e}")
            continue

    return (None, MSG_TODOS_ACESSOS_EM_USO)


def aguardar_login_bo(
    vendedor_telefone: str,
    tipo_automacao: str = TIPO_AUTOMACAO_STATUS,
    *,
    timeout_seg: int = 600,
    intervalo_seg: int = 45,
    contador_uso_por_bo: Optional[dict] = None,
) -> Tuple[Optional["Usuario"], Optional[str]]:
    """Espera até um login BO ficar livre ou estourar o timeout."""
    import time

    deadline = time.time() + max(30, timeout_seg)
    while time.time() < deadline:
        bo, err = obter_login_bo(
            vendedor_telefone,
            None,
            tipo_automacao=tipo_automacao,
            contador_uso_por_bo=contador_uso_por_bo,
        )
        if bo:
            return bo, None
        if err and "Nenhum login BackOffice" in (err or ""):
            return None, err
        time.sleep(max(15, intervalo_seg))
    return None, MSG_TODOS_ACESSOS_EM_USO


def adicionar_a_fila_pap(
    telefone: str,
    tipo_acao: str = "vender",
    sessao_whatsapp_id: Optional[int] = None,
) -> "FilaEsperaPAP":
    """
    Coloca o usuário na fila de espera (ou atualiza posição se já estiver).
    Remove entradas anteriores do mesmo telefone para evitar duplicidade.

    Args:
        telefone: Telefone do usuário
        tipo_acao: 'vender', 'pedido', 'status' ou 'credito'
        sessao_whatsapp_id: ID da SessaoWhatsapp (opcional)

    Returns:
        Instância de FilaEsperaPAP criada
    """
    from crm_app.models import FilaEsperaPAP

    FilaEsperaPAP.objects.filter(telefone=telefone).delete()
    entrada = FilaEsperaPAP.objects.create(
        telefone=telefone,
        tipo_acao=tipo_acao,
        sessao_whatsapp_id=sessao_whatsapp_id,
    )
    logger.info(f"[POOL BO] Entrada na fila: {telefone} (tipo={tipo_acao})")
    return entrada


def _notificar_proximo_da_fila() -> None:
    """
    Após liberar um login: pega o primeiro da fila, remove e envia WhatsApp
    avisando que um login foi liberado.
    """
    from crm_app.models import FilaEsperaPAP
    from crm_app.whatsapp_service import WhatsAppService

    entrada = FilaEsperaPAP.objects.order_by("created_at").first()
    if not entrada:
        return
    telefone = entrada.telefone
    tipo = entrada.tipo_acao or "vender"
    entrada.delete()
    logger.info(f"[POOL BO] Notificando próximo da fila: {telefone} (tipo={tipo})")

    comando = {"vender": "VENDER", "pedido": "PEDIDO", "status": "STATUS", "credito": "CRÉDITO"}.get(
        tipo, "VENDER"
    )
    msg = (
        "✅ *Um login PAP foi liberado!*\n\n"
        f"Digite *{comando}* agora para usar.\n\n"
        "Se demorar, outro usuário pode pegar o login e você será avisado de novo quando liberar."
    )
    try:
        WhatsAppService().enviar_mensagem_texto(telefone, msg)
        from django.core.cache import cache
        cache.set(f"pap_fila_notificado:{telefone}", "1", timeout=120)  # 2 min para mensagem "recolocado"
    except Exception as e:
        logger.exception(f"[POOL BO] Erro ao notificar fila para {telefone}: {e}")


def obter_mensagem_fila_ocupado(telefone: str, tipo_acao: str = "vender") -> str:
    """
    Adiciona o usuário à fila e retorna a mensagem a enviar (ocupado / recolocado).
    Usado pelo webhook quando obter_login_bo retorna MSG_TODOS_ACESSOS_EM_USO.
    """
    from django.core.cache import cache

    adicionar_a_fila_pap(telefone, tipo_acao=tipo_acao)
    comando = {"vender": "VENDER", "pedido": "PEDIDO", "status": "STATUS", "credito": "CRÉDITO"}.get(
        tipo_acao, "VENDER"
    )
    chave = f"pap_fila_notificado:{telefone}"
    if cache.get(chave):
        cache.delete(chave)
        return (
            "⚠️ *Login já ocupado novamente.*\n\n"
            "Você foi recolocado na fila. Avisaremos na próxima liberação.\n\n"
            f"Digite *{comando}* quando receber o aviso."
        )
    return (
        "📋 *Você está na fila.*\n\n"
        "Quando um login for liberado, avisaremos aqui.\n\n"
        f"Digite *{comando}* quando receber o aviso."
    )


def liberar_todos_bos() -> Tuple[int, str]:
    """
    Libera todos os logins PAP (remove todos os registros PapBoEmUso).
    Útil quando os logins ficaram travados sem uso (ex.: sessão caiu e o lock não foi liberado).
    Retorna (quantidade_liberada, mensagem).
    """
    from crm_app.models import PapBoEmUso

    try:
        total = PapBoEmUso.objects.count()
        if total == 0:
            return 0, "Nenhum login estava em uso."
        PapBoEmUso.objects.all().delete()
        logger.info(f"[POOL BO] Liberados todos os {total} BO(s) (logoff manual).")
        return total, f"Liberados {total} login(s) PAP. Eles voltam ao pool para o bot."
    except Exception as e:
        logger.exception(f"[POOL BO] Erro ao liberar todos: {e}")
        return 0, f"Erro ao liberar: {e}"


def liberar_bo(
    bo_usuario_id: int,
    vendedor_telefone: str,
) -> bool:
    """
    Libera o login BackOffice após conclusão da venda (sucesso, erro ou cancelamento).
    Se houver fila de espera, notifica o primeiro da fila por WhatsApp.

    Args:
        bo_usuario_id: ID do usuário BackOffice
        vendedor_telefone: Telefone do vendedor que estava usando

    Returns:
        True se liberou com sucesso, False caso contrário
    """
    from crm_app.models import PapBoEmUso

    try:
        deletados = PapBoEmUso.objects.filter(
            bo_usuario_id=bo_usuario_id,
            vendedor_telefone=vendedor_telefone,
        ).delete()
        if deletados[0] > 0:
            logger.info(
                f"[POOL BO] Liberado BO id={bo_usuario_id} usado por {vendedor_telefone}"
            )
            _notificar_proximo_da_fila()
        return deletados[0] > 0
    except Exception as e:
        logger.exception(f"[POOL BO] Erro ao liberar BO: {e}")
        return False
