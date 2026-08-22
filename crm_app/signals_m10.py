# crm_app/signals_m10.py
"""
Signals para automatizar contratos Qualidade (legado M-10) a partir de Venda instalada.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ContratoM10, SafraM10, Venda

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Venda)
def criar_ou_atualizar_contrato_m10(sender, instance: Venda, created: bool, **kwargs) -> None:
    """Quando a venda fica INSTALADA com O.S., garante ContratoM10 na safra de instalação."""
    if not instance.ativo or not instance.data_instalacao:
        return

    status_nome = ''
    if instance.status_esteira_id:
        status_nome = (instance.status_esteira.nome or '').strip().upper()
    if status_nome and status_nome != 'INSTALADA':
        return

    os_val = (instance.ordem_servico or '').strip() or None
    numero = os_val or f'VENDA_{instance.id}'

    try:
        contrato = None
        if os_val:
            contrato = ContratoM10.objects.filter(ordem_servico=os_val).first()
        if contrato is None:
            contrato = ContratoM10.objects.filter(numero_contrato=numero).first()

        cliente = instance.cliente
        plano_nome = instance.plano.nome if instance.plano else 'N/D'
        plano_valor = instance.plano.valor if instance.plano else 0
        cliente_nome = cliente.nome_razao_social if cliente else 'N/D'
        cpf = cliente.cpf_cnpj if cliente else ''

        if contrato is None:
            contrato = ContratoM10(
                numero_contrato=numero,
                ordem_servico=os_val,
            )

        contrato.venda = instance
        contrato.cliente_nome = cliente_nome
        if cpf:
            contrato.cpf_cliente = cpf
        contrato.vendedor = instance.vendedor
        contrato.data_instalacao = instance.data_instalacao
        contrato.plano_original = contrato.plano_original or plano_nome
        contrato.plano_atual = plano_nome
        contrato.valor_plano = plano_valor or contrato.valor_plano or 0
        if getattr(contrato, 'orfao', False) and cpf:
            contrato.orfao = False
            obs = contrato.observacao or ''
            if 'Órfão' in obs or 'órfão' in obs.lower():
                contrato.observacao = (obs + ' | Vinculado à venda automaticamente').strip(' |')
        contrato.save()

        try:
            contrato.criar_ou_atualizar_faturas()
        except Exception:
            logger.exception('Falha ao criar faturas Qualidade OS=%s', os_val)

        mes_ref = instance.data_instalacao.replace(day=1)
        SafraM10.objects.get_or_create(
            mes_referencia=mes_ref,
            defaults={
                'total_instalados': 0,
                'total_ativos': 0,
                'total_elegivel_bonus': 0,
                'valor_bonus_total': 0,
            },
        )
    except Exception:
        logger.exception('Erro ao processar Venda %s no Qualidade/M10', instance.id)
