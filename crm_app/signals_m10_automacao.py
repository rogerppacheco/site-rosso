"""
AUTOMAÇÃO BÔNUS M-10 - SISTEMA INTELIGENTE

Este arquivo contém os signals que automatizam toda a criação e linking do M-10:
1. Quando uma Venda é criada/atualizada com data_instalacao → cria ContratoM10
2. Quando ContratoM10 é criado → busca automaticamente no FPD
3. Quando encontra FPD → preenche numero_contrato_definitivo
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import datetime

from .models import Venda, ContratoM10, SafraM10, ImportacaoFPD


# ============================================================================
# SINAL 1: QUANDO VENDA É SALVA → CRIA CONTRATO M-10 AUTOMATICAMENTE
# ============================================================================

@receiver(post_save, sender=Venda)
def criar_contrato_m10_automatico(sender, instance, created, **kwargs):
    """
    Quando uma Venda é criada ou atualizada com:
    - ativo = True
    - status_esteira = INSTALADA
    - data_instalacao preenchida
    - ordem_servico preenchida
    
    Então cria ou atualiza um ContratoM10 automaticamente.
    """
    
    # Verifica se a venda tem os dados mínimos para criar M-10
    if not instance.ativo or not instance.data_instalacao or not instance.ordem_servico:
        return
    
    # Verifica se o status da esteira é INSTALADA
    if not instance.status_esteira or instance.status_esteira.nome.upper() != 'INSTALADA':
        return
    
    # Verifica se já existe um contrato com esta OS (para evitar UNIQUE constraint)
    contrato_existente = ContratoM10.objects.filter(ordem_servico=instance.ordem_servico).first()
    if contrato_existente:
        # Atualiza o contrato existente se necessário
        contrato_existente.venda = instance
        contrato_existente.cliente_nome = instance.cliente.nome_razao_social if instance.cliente else ''
        contrato_existente.save()
        return
    
    # Encontrar ou criar a SafraM10 do mês da instalação
    mes_referencia = instance.data_instalacao.replace(day=1)
    safra_str = instance.data_instalacao.strftime('%Y-%m')
    
    safra_m10, created_safra = SafraM10.objects.get_or_create(
        mes_referencia=mes_referencia,
        defaults={
            'total_instalados': 0,
            'total_ativos': 0,
            'total_elegivel_bonus': 0,
            'valor_bonus_total': 0,
        }
    )
    
    # Criar o ContratoM10
    numero_contrato = f"{instance.id}-{instance.ordem_servico}"
    
    try:
        contrato_m10 = ContratoM10.objects.create(
            numero_contrato=numero_contrato,
            safra=safra_str,  # CharField, não objeto
            venda=instance,
            ordem_servico=instance.ordem_servico,
            cliente_nome=instance.cliente.nome_razao_social if instance.cliente else '',
            cpf_cliente=instance.cliente.cpf_cnpj if instance.cliente else '',
            vendedor=instance.vendedor,
            data_instalacao=instance.data_instalacao,
            plano_original=instance.plano.nome if instance.plano else 'N/A',
            plano_atual=instance.plano.nome if instance.plano else 'N/A',
            valor_plano=instance.plano.valor if instance.plano and hasattr(instance.plano, 'valor') else 0,
            status_contrato='ATIVO',
            elegivel_bonus=False,
        )
        
        # Se foi criado, tenta sincronizar com FPD
        sincronizar_com_fpd(contrato_m10, instance.ordem_servico)
    except Exception as e:
        print(f"❌ Erro ao criar ContratoM10 para Venda {instance.id}: {e}")


# ============================================================================
# SINAL 2: QUANDO CONTRATO M-10 É CRIADO → BUSCA NO FPD
# ============================================================================

@receiver(post_save, sender=ContratoM10)
def sincronizar_contrato_m10_com_fpd(sender, instance, created, **kwargs):
    """
    Quando um ContratoM10 é criado, tenta automaticamente sincronizar
    com a base de ImportacaoFPD buscando pela ordem_servico.
    """
    
    if created and instance.ordem_servico:
        sincronizar_com_fpd(instance, instance.ordem_servico)


# ============================================================================
# FUNÇÃO AUXILIAR: SINCRONIZAÇÃO COM FPD
# ============================================================================

def sincronizar_com_fpd(contrato_m10, ordem_servico):
    """
    Busca um registro em ImportacaoFPD com a mesma ordem_servico
    e preenche automaticamente o numero_contrato_definitivo.
    
    Busca por:
    - nr_ordem = ordem_servico
    - ou numero_os = ordem_servico
    """
    
    if not ordem_servico:
        return False
    
    try:
        # Tenta encontrar o FPD pela ordem de serviço
        fpd = ImportacaoFPD.objects.filter(
            nr_ordem=ordem_servico
        ).first()
        
        # Se não encontrar, tenta alternativas
        if not fpd:
            fpd = ImportacaoFPD.objects.filter(
                numero_os=ordem_servico
            ).first()
        
        # Se encontrou o FPD, vincula e preenche todos os dados disponíveis
        if fpd and fpd.id_contrato:
            contrato_m10.numero_contrato_definitivo = fpd.id_contrato
            contrato_m10.data_vencimento_fpd = fpd.dt_venc_orig
            contrato_m10.data_pagamento_fpd = fpd.dt_pagamento
            contrato_m10.status_fatura_fpd = fpd.ds_status_fatura
            contrato_m10.valor_fatura_fpd = fpd.vl_fatura
            contrato_m10.nr_dias_atraso_fpd = fpd.nr_dias_atraso
            contrato_m10.data_ultima_sincronizacao_fpd = timezone.now()
            contrato_m10.save(update_fields=[
                'numero_contrato_definitivo', 
                'data_vencimento_fpd',
                'data_pagamento_fpd',
                'status_fatura_fpd',
                'valor_fatura_fpd',
                'nr_dias_atraso_fpd',
                'data_ultima_sincronizacao_fpd'
            ])
            
            # Se tinha ImportacaoFPD.contrato_m10 vazio, vincula também
            if not fpd.contrato_m10:
                fpd.contrato_m10 = contrato_m10
                fpd.save(update_fields=['contrato_m10'])
            
            return True
        
    except Exception as e:
        print(f"[ERRO] Ao sincronizar FPD: {e}")
        return False
    
    return False


# ============================================================================
# SINAL 3: QUANDO IMPORTACAOFPD É CRIADA → TENTA VINCULAR A M-10
# ============================================================================

@receiver(post_save, sender=ImportacaoFPD)
def vincular_fpd_a_m10(sender, instance, created, **kwargs):
    """
    Quando um registro ImportacaoFPD é criado, tenta automaticamente
    encontrar um ContratoM10 com a mesma ordem_servico e fazer o linking.
    """
    
    if created and instance.nr_ordem and not instance.contrato_m10:
        try:
            # Busca ContratoM10 com a mesma ordem_servico
            contrato_m10 = ContratoM10.objects.filter(
                ordem_servico=instance.nr_ordem
            ).first()
            
            if contrato_m10:
                # Vincula o FPD ao ContratoM10
                instance.contrato_m10 = contrato_m10
                instance.save(update_fields=['contrato_m10'])
                
                # Preenche todos os dados FPD disponíveis
                if instance.id_contrato and not contrato_m10.numero_contrato_definitivo:
                    contrato_m10.numero_contrato_definitivo = instance.id_contrato
                    contrato_m10.data_vencimento_fpd = instance.dt_venc_orig
                    contrato_m10.data_pagamento_fpd = instance.dt_pagamento
                    contrato_m10.status_fatura_fpd = instance.ds_status_fatura
                    contrato_m10.valor_fatura_fpd = instance.vl_fatura
                    contrato_m10.nr_dias_atraso_fpd = instance.nr_dias_atraso
                    contrato_m10.data_ultima_sincronizacao_fpd = timezone.now()
                    contrato_m10.save(update_fields=[
                        'numero_contrato_definitivo',
                        'data_vencimento_fpd',
                        'data_pagamento_fpd',
                        'status_fatura_fpd',
                        'valor_fatura_fpd',
                        'nr_dias_atraso_fpd',
                        'data_ultima_sincronizacao_fpd'
                    ])
                
        except Exception as e:
            print(f"[ERRO] Ao vincular FPD a M-10: {e}")


# ============================================================================
# SINAL 4: PRE-SAVE NO VENDA → VALIDAR STATUS
# ============================================================================

@receiver(pre_save, sender=Venda)
def validar_venda_antes_de_salvar(sender, instance, **kwargs):
    """
    Antes de salvar, valida se a venda atende aos critérios mínimos.
    """
    
    # Se a venda tem data_instalacao mas não tem ordem_servico, avisa
    if instance.data_instalacao and not instance.ordem_servico:
        print(f"[AVISO] Venda {instance.id} tem instalação mas sem O.S definida")
    
    # Se mudou para inativo e tem ContratoM10, marca como cancelado
    if instance.pk:  # Se é atualização
        venda_antiga = Venda.objects.get(pk=instance.pk)
        if venda_antiga.ativo and not instance.ativo:
            # Venda ficou inativa - marcar ContratoM10 como cancelado
            ContratoM10.objects.filter(
                venda=instance,
                status_contrato='ATIVO'
            ).update(
                status_contrato='CANCELADO',
                data_cancelamento=timezone.now().date()
            )
