"""Configuração da IA no atendimento WhatsApp (singleton + blocklist em banco)."""
from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from crm_app.models import WhatsAppIaConfig, WhatsAppTelefoneSemIa


def get_whatsapp_ia_config() -> WhatsAppIaConfig:
    return WhatsAppIaConfig.load()


def serializar_whatsapp_ia_config(cfg: WhatsAppIaConfig | None = None) -> dict[str, Any]:
    obj = cfg or get_whatsapp_ia_config()
    return {
        "ia_contatos_externos_ativa": obj.ia_contatos_externos_ativa,
        "ia_clientes_venda_ativa": obj.ia_clientes_venda_ativa,
        "ia_vendedores_duvidas_ativa": obj.ia_vendedores_duvidas_ativa,
        "ia_boas_vindas_sugestao_ativa": obj.ia_boas_vindas_sugestao_ativa,
        "atualizado_em": obj.atualizado_em.isoformat() if obj.atualizado_em else None,
    }


def atualizar_whatsapp_ia_config(dados: dict[str, Any], usuario) -> WhatsAppIaConfig:
    cfg = get_whatsapp_ia_config()
    campos_bool = (
        "ia_contatos_externos_ativa",
        "ia_clientes_venda_ativa",
        "ia_vendedores_duvidas_ativa",
        "ia_boas_vindas_sugestao_ativa",
    )
    update_fields: list[str] = []
    for campo in campos_bool:
        if campo in dados:
            setattr(cfg, campo, bool(dados[campo]))
            update_fields.append(campo)
    if update_fields:
        cfg.atualizado_por = usuario
        update_fields.extend(["atualizado_por", "atualizado_em"])
        cfg.save(update_fields=update_fields)
    return cfg


def ia_contatos_externos_habilitada() -> bool:
    return get_whatsapp_ia_config().ia_contatos_externos_ativa


def ia_clientes_venda_habilitada() -> bool:
    return get_whatsapp_ia_config().ia_clientes_venda_ativa


def ia_vendedores_duvidas_habilitada() -> bool:
    return get_whatsapp_ia_config().ia_vendedores_duvidas_ativa


def ia_boas_vindas_sugestao_habilitada() -> bool:
    return get_whatsapp_ia_config().ia_boas_vindas_sugestao_ativa


@receiver(post_save, sender=WhatsAppTelefoneSemIa)
@receiver(post_delete, sender=WhatsAppTelefoneSemIa)
def _invalidar_cache_blocklist(sender, **kwargs) -> None:
    from crm_app.whatsapp_telefone_blocklist import limpar_cache_blocklist

    limpar_cache_blocklist()
