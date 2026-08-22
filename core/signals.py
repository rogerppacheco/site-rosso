from django.db.models.signals import post_save
from django.dispatch import receiver

# IMPORTANTE: Importando do crm_app, não mais do core
from crm_app.models import CdoiSolicitacao 
from .services import processar_regra_automacao

@receiver(post_save, sender=CdoiSolicitacao)
def gatilho_novo_cdoi(sender, instance, created, **kwargs):
    """
    Quando um CdoiSolicitacao é criado no crm_app, verifica se há regras
    de automação no core e dispara as mensagens.
    """
    if created:
        print(f"--- Novo CDOI Detectado: {instance.nome_condominio} ---")
        # Chama o serviço passando o nome do evento e o objeto criado
        processar_regra_automacao('NOVO_CDOI', instance)