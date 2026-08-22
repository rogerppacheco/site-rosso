from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from .models import Venda, ContratoM10, StatusCRM, LancamentoFinanceiro
from .whatsapp_service import WhatsAppService
import logging

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=Venda)
def verificar_mudanca_status(sender, instance, **kwargs):
    """
    Antes de salvar, captura o status atual do banco de dados para comparar depois.
    E também define status_esteira como AGENDADO quando reemissão é marcada.
    """
    if instance.pk:
        try:
            old_instance = Venda.objects.get(pk=instance.pk)
            # Armazena temporariamente na instância em memória
            instance._old_status_tratamento = old_instance.status_tratamento
            instance._old_status_esteira = old_instance.status_esteira
            instance._old_reemissao = old_instance.reemissao
            
            # Se reemissão foi marcada como True, definir status_esteira como AGENDADO
            if instance.reemissao and not old_instance.reemissao:
                try:
                    st_agendado = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                    instance.status_esteira = st_agendado
                except StatusCRM.DoesNotExist:
                    pass
        except Venda.DoesNotExist:
            pass

@receiver(post_save, sender=Venda)
def quitar_adiantamento_sabado_ao_instalar(sender, instance, created, **kwargs):
    """Qualquer save que leve a venda a INSTALADA quita adiantamento sábado pendente."""
    if created:
        return
    old_esteira = getattr(instance, '_old_status_esteira', None)
    if not instance.status_esteira:
        return
    try:
        from crm_app.services.adiantamento_sabado_service import (
            quitar_adiantamento_sabado_na_instalacao,
            status_esteira_eh_instalada,
        )
        if not status_esteira_eh_instalada(instance.status_esteira):
            return
        quitar_adiantamento_sabado_na_instalacao(instance, old_esteira)
    except Exception:
        logger.exception(
            'Erro ao quitar adiantamento sábado na instalação (signal) — venda #%s',
            instance.pk,
        )


@receiver(post_save, sender=Venda)
def disparar_whatsapp_cadastrada(sender, instance, created, **kwargs):
    """
    Após salvar, verifica se o status mudou para 'CADASTRADA' e envia msg ao vendedor.
    """
    if created:
        return  # Ignora vendas novas recém-criadas (só dispara na mudança)

    # Recupera os valores antigos guardados no pre_save
    old_tratamento = getattr(instance, '_old_status_tratamento', None)
    new_tratamento = instance.status_tratamento

    old_esteira = getattr(instance, '_old_status_esteira', None)
    new_esteira = instance.status_esteira

    gatilho_acionado = False

    # 1. Verifica mudança no Status de Tratamento (Auditoria)
    # Se o novo status é CADASTRADA e o antigo NÃO ERA CADASTRADA
    if new_tratamento and new_tratamento.nome.upper() == "CADASTRADA":
        if not old_tratamento or old_tratamento.nome.upper() != "CADASTRADA":
            gatilho_acionado = True

    # 2. Verifica mudança no Status de Esteira (caso use este campo também)
    elif new_esteira and new_esteira.nome.upper() == "CADASTRADA":
        if not old_esteira or old_esteira.nome.upper() != "CADASTRADA":
            gatilho_acionado = True

    if gatilho_acionado:
        logger.info(f"Venda #{instance.id} mudou para CADASTRADA.")

        # Verifica se tem vendedor vinculado
        if not instance.vendedor:
            logger.warning(f"Venda #{instance.id} sem vendedor. WhatsApp cancelado.")
            return

        # Verifica se o vendedor tem o WhatsApp cadastrado no perfil
        telefone_vendedor = instance.vendedor.tel_whatsapp
        
        if not telefone_vendedor:
            logger.warning(f"Vendedor {instance.vendedor.username} não tem 'Tel WhatsApp' cadastrado.")
            return

        try:
            logger.info(f"Enviando WhatsApp para vendedor {instance.vendedor.username} ({telefone_vendedor})...")
            service = WhatsAppService()
            
            # Chama o método de envio passando explicitamente o telefone do vendedor
            service.enviar_mensagem_cadastrada(instance, telefone_destino=telefone_vendedor)
            
        except Exception as e:
            logger.error(f"Erro ao enviar WhatsApp na venda #{instance.id}: {e}")


# Signal para criar/atualizar faturas automaticamente ao salvar contrato M-10
@receiver(post_save, sender=ContratoM10)
def criar_faturas_automatico(sender, instance, created, **kwargs):
    """
    Após criar um ContratoM10, garante as 10 faturas.
    Em updates, só completa faturas faltantes — não sobrescreve vencimento do FPD
    (protegido em ``criar_ou_atualizar_faturas`` quando há data_importacao_fpd).
    """
    try:
        if instance.data_instalacao:
            instance.criar_ou_atualizar_faturas()
            if created:
                logger.info(f"✅ Faturas criadas/atualizadas para contrato {instance.numero_contrato}")
    except Exception as e:
        logger.error(f"❌ Erro ao criar/atualizar faturas para {instance.numero_contrato}: {e}")


@receiver(pre_save, sender=LancamentoFinanceiro)
def _capturar_data_anterior_lancamento_folha(sender, instance, **kwargs) -> None:
    """Guarda o mês anterior do lançamento para invalidar cache se a data mudar."""
    if not instance.pk:
        return
    try:
        anterior = LancamentoFinanceiro.objects.only('data').get(pk=instance.pk)
        instance._data_folha_anterior = anterior.data
    except LancamentoFinanceiro.DoesNotExist:
        instance._data_folha_anterior = None


def _invalidar_cache_folha_por_data_lancamento(data) -> None:
    from crm_app.services.folha_comissionamento_cache import invalidar_folha_por_data

    invalidar_folha_por_data(data)


@receiver(post_save, sender=LancamentoFinanceiro)
def invalidar_cache_folha_apos_lancamento(sender, instance, **kwargs) -> None:
    """Bônus, descontos e adiantamentos manuais devem refletir na folha sem esperar TTL."""
    _invalidar_cache_folha_por_data_lancamento(instance.data)
    data_anterior = getattr(instance, '_data_folha_anterior', None)
    if data_anterior and data_anterior != instance.data:
        _invalidar_cache_folha_por_data_lancamento(data_anterior)


@receiver(post_delete, sender=LancamentoFinanceiro)
def invalidar_cache_folha_apos_excluir_lancamento(sender, instance, **kwargs) -> None:
    _invalidar_cache_folha_por_data_lancamento(instance.data)
