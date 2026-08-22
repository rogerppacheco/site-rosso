"""
Telefones ignorados pelo webhook WhatsApp (sem resposta, sem IA).
"""
from __future__ import annotations

from typing import FrozenSet, Iterable, Set

# Loop conhecido em produção (jun/2026): reprocessava mensagens do bot e estourava cota de IA.
_TELEFONES_BLOQUEADOS_PADRAO = frozenset({'12981750292'})

_CACHED_VARIANTES: FrozenSet[str] | None = None


def normalizar_telefone_blocklist(telefone: str) -> str:
    """Normaliza telefone para armazenamento/comparação na blocklist."""
    if not telefone:
        return ''
    limpo = ''.join(filter(str.isdigit, str(telefone)))
    if limpo.startswith('55') and len(limpo) > 12:
        limpo = limpo[2:]
    return limpo


def _normalizar_telefone(telefone: str) -> str:
    return normalizar_telefone_blocklist(telefone)


def _variantes_telefone(telefone: str) -> Set[str]:
    """Variantes de chave (com/sem 55, 10/11 dígitos) — alinhado ao webhook handler."""
    base = _normalizar_telefone(telefone)
    if not base:
        return set()
    chaves = {base}
    if base.startswith('55') and len(base) > 11:
        chaves.add(base[2:])
    elif len(base) >= 10 and not base.startswith('55'):
        chaves.add('55' + base)
    nacional = base[2:] if base.startswith('55') and len(base) > 11 else base
    if len(nacional) == 10:
        chaves.add(nacional[:2] + '9' + nacional[2:])
        chaves.add('55' + nacional[:2] + '9' + nacional[2:])
    if len(nacional) == 11 and nacional[2] == '9':
        chaves.add(nacional[:2] + nacional[3:])
        chaves.add('55' + nacional[:2] + nacional[3:])
    if len(base) == 12 and base.startswith('55') and base[4] != '9':
        chaves.add(base[:4] + '9' + base[4:])
    if len(base) == 13 and base.startswith('55') and base[4] == '9':
        chaves.add(base[:4] + base[5:])
    return chaves


def _telefones_extra_settings() -> Iterable[str]:
    try:
        from django.conf import settings
        return getattr(settings, 'WHATSAPP_TELEFONES_BLOQUEADOS', None) or ()
    except Exception:
        return ()


def _telefones_banco_dados() -> Iterable[str]:
    try:
        from crm_app.models import WhatsAppTelefoneSemIa

        return WhatsAppTelefoneSemIa.objects.filter(ativo=True).values_list('telefone', flat=True)
    except Exception:
        return ()


def get_variantes_bloqueadas() -> FrozenSet[str]:
    global _CACHED_VARIANTES
    if _CACHED_VARIANTES is not None:
        return _CACHED_VARIANTES
    variantes: Set[str] = set()
    for numero in _TELEFONES_BLOQUEADOS_PADRAO:
        variantes.update(_variantes_telefone(numero))
    for numero in _telefones_extra_settings():
        if numero:
            variantes.update(_variantes_telefone(str(numero).strip()))
    for numero in _telefones_banco_dados():
        if numero:
            variantes.update(_variantes_telefone(str(numero).strip()))
    _CACHED_VARIANTES = frozenset(variantes)
    return _CACHED_VARIANTES


def telefone_esta_bloqueado(telefone: str) -> bool:
    if not telefone:
        return False
    bloqueados = get_variantes_bloqueadas()
    return bool(_variantes_telefone(telefone) & bloqueados)


def limpar_cache_blocklist() -> None:
    """Útil em testes quando settings mudam."""
    global _CACHED_VARIANTES
    _CACHED_VARIANTES = None
