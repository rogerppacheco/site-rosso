"""Normalização de telefone e destinatário (BR, grupos Z-API / Evolution)."""
from __future__ import annotations


def formatar_telefone_br(telefone: str | None) -> str:
    if not telefone:
        return ""
    telefone_limpo = "".join(filter(str.isdigit, str(telefone)))
    if telefone_limpo.startswith("55") and len(telefone_limpo) > 11:
        telefone_limpo = telefone_limpo[2:]
    if len(telefone_limpo) == 10 and telefone_limpo[2:3] != "9":
        telefone_limpo = telefone_limpo[:2] + "9" + telefone_limpo[2:]
    if len(telefone_limpo) in (10, 11):
        telefone_limpo = f"55{telefone_limpo}"
    return telefone_limpo


def destino_zapi(telefone_ou_grupo: str | None) -> str:
    """Formato Z-API: número BR ou ID-group."""
    if not telefone_ou_grupo:
        return ""

    s = str(telefone_ou_grupo).strip()
    if "-group" in s:
        return s
    if "-" in s and s.replace("-", "").isdigit():
        return s
    if "@g.us" in s:
        parte = s.split("@g.us")[0].strip()
        digitos = "".join(filter(str.isdigit, parte))
        if digitos.startswith("55") and len(digitos) > 15:
            digitos = digitos[2:]
        return digitos + "-group" if digitos else s

    digitos = "".join(filter(str.isdigit, s))
    if len(digitos) >= 15:
        if digitos.startswith("55") and len(digitos) > 15:
            digitos = digitos[2:]
        return digitos + "-group"

    return formatar_telefone_br(telefone_ou_grupo)


def destino_evolution(telefone_ou_grupo: str | None) -> str:
    """Formato Evolution: dígitos BR ou JID @g.us."""
    if not telefone_ou_grupo:
        return ""

    s = str(telefone_ou_grupo).strip()
    if "@g.us" in s:
        return s
    if "@s.whatsapp.net" in s:
        return s.split("@")[0]

    zapi = destino_zapi(telefone_ou_grupo)
    if "-group" in zapi:
        group_id = zapi.replace("-group", "")
        return f"{group_id}@g.us"
    if "-" in zapi and zapi.replace("-", "").isdigit():
        parts = zapi.split("-", 1)
        if len(parts[0]) >= 15:
            return f"{parts[0]}@g.us"
        return zapi

    return formatar_telefone_br(telefone_ou_grupo)


def strip_whatsapp_jid(identificador: str | None) -> str:
    if not identificador:
        return ""
    s = str(identificador).strip()
    for suffix in ("@s.whatsapp.net", "@c.us", "@g.us"):
        if suffix in s:
            s = s.split(suffix)[0]
    if s.endswith("-group"):
        s = s.replace("-group", "")
    return s
