"""
Resolução de destinos WhatsApp compartilhados (Antecipação e Sem SLOT).

Os destinos vêm de AnteciparInstalacaoConfig.grupos_destino e telefones_destino.
"""
from __future__ import annotations

from typing import Any

from crm_app.models import AnteciparInstalacaoConfig, GrupoDisparo


def _get_config() -> AnteciparInstalacaoConfig:
    config = AnteciparInstalacaoConfig.objects.first()
    if not config:
        config = AnteciparInstalacaoConfig.objects.create(telefone_gc='', nome_gc='')
    return config


def normalizar_telefone_destino(telefone: str) -> str:
    """Mantém apenas dígitos (e + inicial, se houver) para deduplicação."""
    raw = (telefone or '').strip()
    if not raw:
        return ''
    if raw.startswith('+'):
        digits = ''.join(c for c in raw[1:] if c.isdigit())
        return f'+{digits}' if digits else ''
    return ''.join(c for c in raw if c.isdigit())


def limpar_lista_telefones(telefones: list[Any] | None) -> list[str]:
    """Normaliza e deduplica lista de telefones preservando ordem de aparição."""
    resultado: list[str] = []
    vistos: set[str] = set()
    for item in telefones or []:
        tel = str(item or '').strip()
        key = normalizar_telefone_destino(tel)
        if not key or key in vistos:
            continue
        vistos.add(key)
        resultado.append(tel)
    return resultado


def obter_destinos_operacionais(
    config: AnteciparInstalacaoConfig | None = None,
) -> dict[str, Any]:
    """
    Retorna destinos configurados para Antecipação / Sem SLOT.

    Returns:
        {
            'telefones': list[str],
            'grupos': list[GrupoDisparo],  # apenas ativos com chat_id
        }
    """
    config = config or _get_config()
    telefones = limpar_lista_telefones(config.telefones_destino)

    if config.pk:
        grupos = list(
            config.grupos_destino.filter(ativo=True).exclude(chat_id='').order_by('nome')
        )
    else:
        grupos = []

    return {'telefones': telefones, 'grupos': grupos}


def tem_destinos_configurados(config: AnteciparInstalacaoConfig | None = None) -> bool:
    destinos = obter_destinos_operacionais(config)
    return bool(destinos['telefones'] or destinos['grupos'])


def serializar_destinos_config(config: AnteciparInstalacaoConfig) -> dict[str, Any]:
    """Payload de destinos para a API de configuração."""
    destinos = obter_destinos_operacionais(config)
    grupos_sel = destinos['grupos']
    if config.pk:
        grupo_ids = list(config.grupos_destino.filter(ativo=True).values_list('id', flat=True))
    else:
        grupo_ids = []

    return {
        'grupo_ids': grupo_ids,
        'grupos_destino': [
            {'id': g.id, 'nome': g.nome, 'chat_id': g.chat_id} for g in grupos_sel
        ],
        'telefones_destino': destinos['telefones'],
        # Compatibilidade com UI/API antiga (primeiro grupo / resumo)
        'grupo_id': grupo_ids[0] if grupo_ids else None,
        'grupo_nome': (
            ', '.join(g.nome for g in grupos_sel) if grupos_sel else None
        ),
    }


def aplicar_destinos_config(
    config: AnteciparInstalacaoConfig,
    *,
    grupo_ids: list[Any] | None = None,
    telefones_destino: list[Any] | None = None,
) -> None:
    """
    Atualiza destinos no config.

    - grupo_ids: lista de IDs de GrupoDisparo ativos
    - telefones_destino: lista de números WhatsApp
    Também sincroniza o FK legado `grupo` com o primeiro grupo selecionado.
    """
    if telefones_destino is not None:
        config.telefones_destino = limpar_lista_telefones(telefones_destino)

    if grupo_ids is not None:
        ids_limpos: list[int] = []
        for raw in grupo_ids:
            if raw is None or raw == '':
                continue
            try:
                ids_limpos.append(int(raw))
            except (TypeError, ValueError):
                continue
        grupos = list(
            GrupoDisparo.objects.filter(id__in=ids_limpos, ativo=True).order_by('nome')
        )
        # Preserva ordem enviada pelo cliente
        by_id = {g.id: g for g in grupos}
        ordenados = [by_id[i] for i in ids_limpos if i in by_id]
        config.grupos_destino.set(ordenados)
        config.grupo = ordenados[0] if ordenados else None
