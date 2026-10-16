"""Match Assertiva para Interesses do Funil: CPF + telefones (dry-run gravável)."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

from crm_app.historico_pap import map_pedido_api
from crm_app.services.assertiva_localize_service import (
    AssertivaConfigurationError,
    AssertivaError,
    AssertivaLocalizeService,
)

logger = logging.getLogger(__name__)

_DOC_RE = re.compile(r"\D")
MATCH_KEY = "_assertiva_match"


def _fmt_cpf(val: str) -> str:
    d = _DOC_RE.sub("", val or "")
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return (val or "").strip()


def _fmt_phone(val: str) -> str:
    d = _DOC_RE.sub("", val or "")
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return (val or "").strip()


def _norm_nome(valor: str) -> str:
    s = unicodedata.normalize("NFKD", (valor or "").strip().upper())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s)


def _extrair_pessoas(resposta: Any) -> list[dict]:
    if not isinstance(resposta, dict):
        return []
    for chave in ("pessoas", "pessoasFisicas", "resultados", "lista", "items", "content"):
        lista = resposta.get(chave)
        if isinstance(lista, list):
            return [x for x in lista if isinstance(x, dict)]
    if resposta.get("cpf") or resposta.get("documento") or resposta.get("nome"):
        return [resposta]
    # Às vezes vem aninhado em data
    data = resposta.get("data")
    if isinstance(data, dict):
        return _extrair_pessoas(data)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _cpf_de_pessoa(pessoa: dict) -> str:
    for chave in ("cpf", "documento", "numeroDocumento"):
        dig = _DOC_RE.sub("", str(pessoa.get(chave) or ""))
        if len(dig) == 11:
            return dig
    for nested_key in ("cadastroBasico", "dadosCadastrais", "pessoa", "cadastro"):
        cad = pessoa.get(nested_key)
        if not isinstance(cad, dict):
            continue
        for chave in ("cpf", "documento"):
            dig = _DOC_RE.sub("", str(cad.get(chave) or ""))
            if len(dig) == 11:
                return dig
    return ""


def _nome_de_pessoa(pessoa: dict) -> str:
    for chave in ("nome", "nomeCompleto", "nomeCivil"):
        v = pessoa.get(chave)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for nested_key in ("cadastroBasico", "dadosCadastrais", "pessoa", "cadastro"):
        cad = pessoa.get(nested_key)
        if not isinstance(cad, dict):
            continue
        for chave in ("nome", "nomeCompleto", "nomeCivil"):
            v = cad.get(chave)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def serializar_match(payload: dict | None) -> dict:
    """Resumo do match para a listagem do Funil."""
    bloco = (payload or {}).get(MATCH_KEY) if isinstance(payload, dict) else None
    if not isinstance(bloco, dict):
        return {"assertiva_match": None}
    tels = bloco.get("telefones") or []
    if not isinstance(tels, list):
        tels = []
    return {
        "assertiva_match": {
            "status": bloco.get("status") or "",
            "via": bloco.get("via") or "",
            "cpf": bloco.get("cpf") or "",
            "cpf_formatado": bloco.get("cpf_formatado") or _fmt_cpf(bloco.get("cpf") or ""),
            "nome": bloco.get("nome") or "",
            "telefones": [str(t) for t in tels if t],
            "telefones_formatados": [
                _fmt_phone(t) for t in tels if t
            ],
            "qtd_candidatos": int(bloco.get("qtd_candidatos") or 0),
            "consultado_em": bloco.get("consultado_em") or "",
            "detalhe": bloco.get("detalhe") or "",
        }
    }


def listar_candidatos_match_assertiva(
    *,
    limite: int = 20,
    apenas_sem_cpf: bool = True,
    apenas_sem_match_unico: bool = True,
) -> dict:
    """Lista IDs de Interesses elegíveis para match Assertiva (mais recentes primeiro)."""
    from crm_app.models import HistoricoPapPedido

    limite = max(1, min(int(limite or 20), 100))
    qs = (
        HistoricoPapPedido.objects.filter(tipo_venda="INTERESSE")
        .order_by("-capturado_em")
        .only("id", "payload", "numero_pedido")
    )
    ids: list[int] = []
    protocolos: list[str] = []
    vistos = 0
    for ped in qs.iterator(chunk_size=300):
        vistos += 1
        payload = ped.payload if isinstance(ped.payload, dict) else {}
        mapped = map_pedido_api(payload, "INTERESSE")
        nome = (mapped.get("cliente") or payload.get("cliente") or "").strip()
        if len(nome.split()) < 2:
            continue
        dig = _DOC_RE.sub("", str(mapped.get("cpf") or payload.get("cpf") or ""))
        if apenas_sem_cpf and len(dig) == 11:
            continue
        bloco = payload.get(MATCH_KEY) if isinstance(payload.get(MATCH_KEY), dict) else None
        if apenas_sem_match_unico and bloco and bloco.get("status") == "match_unico" and bloco.get("cpf"):
            continue
        ids.append(ped.id)
        protocolos.append(ped.numero_pedido)
        if len(ids) >= limite:
            break
    return {
        "ok": True,
        "limite": limite,
        "ids": ids,
        "protocolos": protocolos,
        "qtd": len(ids),
        "varridos": vistos,
    }


def match_interesse_assertiva(pedido_id: int, *, forcar: bool = False) -> dict:
    """
    Busca CPF (nome/telefone) e, com CPF único, telefones cadastrais na Assertiva.
    Grava em payload._assertiva_match e preenche cpf no payload quando match único.
    """
    from crm_app.models import HistoricoPapPedido

    if not getattr(settings, "ASSERTIVA_CLIENT_ID", "") or not getattr(
        settings, "ASSERTIVA_CLIENT_SECRET", ""
    ):
        return {"ok": False, "detail": "Assertiva não configurada neste ambiente."}

    ped = HistoricoPapPedido.objects.filter(pk=pedido_id).first()
    if not ped:
        return {"ok": False, "detail": "Pedido não encontrado."}
    if (ped.tipo_venda or "").upper() != "INTERESSE":
        return {"ok": False, "detail": "Match Assertiva disponível só para Interesse."}

    payload = dict(ped.payload or {}) if isinstance(ped.payload, dict) else {}
    mapped = map_pedido_api(payload, "INTERESSE")
    nome = (mapped.get("cliente") or payload.get("cliente") or "").strip()
    if len(nome.split()) < 2:
        return {"ok": False, "detail": "Nome do cliente insuficiente para match."}

    existente = payload.get(MATCH_KEY) if isinstance(payload.get(MATCH_KEY), dict) else None
    if existente and existente.get("status") == "match_unico" and not forcar:
        return {
            "ok": True,
            "reutilizado": True,
            **serializar_match(payload),
            "detail": "Match já realizado. Use forçar para consultar de novo.",
        }

    tel = _DOC_RE.sub("", mapped.get("celular_principal") or mapped.get("celular_2") or "")
    if tel.startswith("55") and len(tel) in (12, 13):
        tel = tel[2:]
    uf = (mapped.get("uf") or "").strip().upper()[:2]
    cidade = (mapped.get("cidade") or "").strip()
    cep = _DOC_RE.sub("", mapped.get("cep") or "")

    svc = AssertivaLocalizeService()
    via = ""
    cpf = ""
    nome_assertiva = ""
    qtd = 0
    detalhe = ""
    status = "sem_match"
    telefones: list[str] = []

    try:
        # 1) Telefone do PAP, se existir
        if len(tel) in (10, 11):
            via = "telefone"
            raw = svc.consultar_por_telefone(tel, id_finalidade=1)
            pessoas = _extrair_pessoas(raw.get("resposta"))
            iguais = [p for p in pessoas if _norm_nome(_nome_de_pessoa(p)) == _norm_nome(nome)]
            candidatos = iguais or pessoas
            qtd = len(candidatos)
            if len(candidatos) == 1:
                p0 = candidatos[0]
                cpf = _cpf_de_pessoa(p0)
                nome_assertiva = _nome_de_pessoa(p0)
                if cpf and _norm_nome(nome_assertiva) == _norm_nome(nome):
                    status = "match_unico"
                elif cpf:
                    status = "match_unico_nome_diferente"
                    detalhe = "Telefone achou 1 CPF, mas o nome não bate exatamente."
                else:
                    status = "sem_cpf"
            elif len(candidatos) > 1:
                status = "multiplos"
                detalhe = f"{len(candidatos)} candidatos pelo telefone."

        # 2) Nome exato se ainda sem match único
        if status != "match_unico":
            via = "nome_exato" if not via else f"{via}+nome_exato"
            raw = svc.consultar_por_nome(
                nome,
                id_finalidade=1,
                nome_exato=True,
                uf=uf,
                cidade=cidade,
                cep=cep,
            )
            pessoas = _extrair_pessoas(raw.get("resposta"))
            iguais = [p for p in pessoas if _norm_nome(_nome_de_pessoa(p)) == _norm_nome(nome)]
            qtd = len(iguais) or len(pessoas)
            if len(iguais) == 1:
                p0 = iguais[0]
                cpf = _cpf_de_pessoa(p0)
                nome_assertiva = _nome_de_pessoa(p0)
                status = "match_unico" if cpf else "sem_cpf"
                detalhe = "" if cpf else "Nome único sem CPF no retorno."
            elif len(iguais) > 1:
                status = "multiplos"
                detalhe = f"{len(iguais)} pessoas com nome idêntico."
            elif status not in ("match_unico_nome_diferente", "multiplos"):
                status = "sem_match"
                detalhe = f"Assertiva retornou {len(pessoas)} resultado(s) sem nome idêntico."

        # 3) Com CPF único confiável → telefones via consulta CPF
        if status == "match_unico" and cpf:
            try:
                dados = svc.consultar_para_credito(cpf)
                telefones = list(dados.telefones or ())
                if dados.nome and not nome_assertiva:
                    nome_assertiva = dados.nome
            except AssertivaError as exc:
                detalhe = (detalhe + f" CPF ok; telefones: {exc}").strip()

    except AssertivaConfigurationError as exc:
        return {"ok": False, "detail": str(exc)}
    except AssertivaError as exc:
        msg = str(exc)
        if "horario" in msg.lower() or "horário" in msg.lower() or "neste horario" in msg.lower():
            return {
                "ok": False,
                "detail": "Assertiva indisponível neste horário (restrição do plano/grupo).",
            }
        return {"ok": False, "detail": msg}
    except Exception as exc:
        logger.exception("[ASSERTIVA MATCH] Falha pedido %s", pedido_id)
        return {"ok": False, "detail": f"Erro inesperado: {exc}"}

    agora = timezone.localtime().isoformat()
    bloco = {
        "status": status,
        "via": via,
        "cpf": cpf,
        "cpf_formatado": _fmt_cpf(cpf) if cpf else "",
        "nome": nome_assertiva or nome,
        "telefones": telefones,
        "qtd_candidatos": qtd,
        "consultado_em": agora,
        "detalhe": detalhe,
        "nome_pap": nome,
    }
    payload[MATCH_KEY] = bloco

    # Só grava CPF no registro quando match único confiável.
    if status == "match_unico" and cpf:
        payload["cpf"] = cpf
        dc = payload.get("dadosCliente")
        if not isinstance(dc, dict):
            dc = {}
        dc = dict(dc)
        dc["cpf"] = cpf
        if nome_assertiva:
            dc["nome"] = nome_assertiva
        if telefones:
            contatos = []
            for i, t in enumerate(telefones[:3]):
                contatos.append({"telefone": t, "ordem": i + 1})
            dc["contatos"] = contatos
        payload["dadosCliente"] = dc

    ped.payload = payload
    ped.save(update_fields=["payload"])

    return {
        "ok": True,
        "reutilizado": False,
        "gravou_cpf": bool(status == "match_unico" and cpf),
        **serializar_match(payload),
        "detail": {
            "match_unico": "CPF e telefones atualizados.",
            "match_unico_nome_diferente": detalhe or "Match por telefone com nome divergente — CPF não gravado.",
            "multiplos": detalhe or "Vários candidatos — CPF não gravado.",
            "sem_match": detalhe or "Nenhum match encontrado.",
            "sem_cpf": detalhe or "Match sem CPF no retorno.",
        }.get(status, detalhe or status),
    }
