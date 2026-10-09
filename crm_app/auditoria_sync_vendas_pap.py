"""Cruza a fila da auditoria com o histórico do botão Buscar do PAP.

PEDIDO_GERADO com O.S. vai para a esteira. Agenda completa fica AGENDADO.
Sem data ou turno, fica PENDENCIADA com a pendência 7030 (falta de slot).
VENDA_NAO_CONFIRMADA tenta reprovar pelo status secundário.
ANALISE_BO reprova como DUPLICIDADE se o CPF já tem pedido com O.S. na esteira.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.historico_pap import map_pedido_api, normalizar_pedido
from crm_app.models import HistoricoAlteracaoVenda, HistoricoPapPedido, StatusCRM, Venda
from crm_app.utils import (
    buscar_venda_os_ja_cadastrada,
    is_member,
    mensagem_os_ja_cadastrada,
    resolver_motivo_pendencia_por_texto_pap,
)

logger = logging.getLogger(__name__)

GRUPOS_SYNC = (
    "Diretoria",
    "Admin",
    "BackOffice",
    "Supervisor",
    "Auditoria",
    "Qualidade",
)

_STATUS_SUCESSO = {"CADASTRADA", "AUDITADA", "APROVADA", "SEM TRATAMENTO"}
_OS_RE = re.compile(r"^(?:\d{8}|\d-\d{12})$")
_STOP = {
    "DE", "DA", "DO", "DAS", "DOS", "EM", "PARA", "COM", "NA", "NO",
    "QUE", "POR", "JA", "UM", "UMA",
}

# Motivo do PAP (trecho) → nomes possíveis no catálogo de tratamento, do mais específico ao mais curto.
_ALIASES_SECUNDARIO = (
    (
        ("JA EXISTE OS", "EXISTE OS EM ABERTO", "OS EM ABERTO", "OS ABERTA", "PEDIDO EM ABERTO"),
        ("JA CONSTA PEDIDO", "CONSTA PEDIDO"),
    ),
    (
        ("DUPLIC",),
        ("DUPLICIDADE", "PEDIDO DUPLICADO", "DUPLICADO"),
    ),
)


def _fold(valor) -> str:
    texto = "" if valor is None else str(valor)
    nfd = unicodedata.normalize("NFD", texto)
    sem = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    sem = sem.upper().replace("_", " ")
    return re.sub(r"[^A-Z0-9]+", " ", sem).strip()


def _chave(valor) -> str:
    return _fold(valor).replace(" ", "_")


def _tokens(texto: str) -> set[str]:
    return {t for t in _fold(texto).split() if len(t) >= 4 and t not in _STOP}


def _digitos(valor) -> str:
    return re.sub(r"\D", "", "" if valor is None else str(valor))


def _variantes_documento(valor) -> set[str]:
    d = _digitos(valor)
    if not d:
        return set()
    vals = {d}
    if len(d) == 11:
        vals.add(f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}")
    elif len(d) == 14:
        vals.add(f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}")
    return vals


def _candidatos_reprova(statuses) -> list[tuple[object, str]]:
    out = []
    for st in statuses:
        nome = _fold(getattr(st, "nome", ""))
        if not nome or nome in _STATUS_SUCESSO or nome.startswith("APROVADA"):
            continue
        out.append((st, nome))
    return out


def _primeiro_fragmento(cands, fragmentos) -> object | None:
    for frag in fragmentos:
        alvo = _fold(frag)
        hits = [st for st, nome in cands if alvo and alvo in nome]
        if hits:
            hits.sort(key=lambda st: (len(_fold(st.nome)), st.nome))
            return hits[0]
    return None


def resolver_status_reprova(texto_secundario, statuses) -> tuple[object | None, str]:
    """Casa o status secundário do PAP com um status de tratamento já cadastrado."""
    original = ("" if texto_secundario is None else str(texto_secundario)).strip()
    texto = _fold(original)
    if not texto:
        return None, "Status secundário vazio."

    cands = _candidatos_reprova(statuses)
    for keywords, alvos in _ALIASES_SECUNDARIO:
        if any(k in texto for k in keywords):
            encontrado = _primeiro_fragmento(cands, alvos)
            if encontrado:
                return encontrado, ""
            legivel = " ou ".join(f'"{a}"' for a in alvos)
            return None, (
                f'Status secundário "{original}" não tem equivalente cadastrado ({legivel}).'
            )

    for st, nome in cands:
        if nome == texto:
            return st, ""

    contidos = []
    for st, nome in cands:
        menor = min(len(nome), len(texto))
        if menor >= 8 and (nome in texto or texto in nome):
            contidos.append(st)
    if contidos:
        contidos.sort(key=lambda st: abs(len(_fold(st.nome)) - len(texto)))
        return contidos[0], ""

    texto_tokens = _tokens(texto)
    melhor = None
    melhor_score = 0
    for st, nome in cands:
        nt = _tokens(nome)
        if not nt or not nt <= texto_tokens:
            continue
        if len(nt) < 2 and max(len(t) for t in nt) < 10:
            continue
        if len(nt) > melhor_score:
            melhor = st
            melhor_score = len(nt)
    if melhor:
        return melhor, ""
    return None, f'Status secundário "{original}" não corresponde a nenhum status de tratamento.'


def buscar_status_por_nome(statuses, *nomes):
    folded = [(st, _fold(st.nome)) for st in statuses]
    for nome in nomes:
        alvo = _fold(nome)
        for st, fn in folded:
            if fn == alvo:
                return st
    return _primeiro_fragmento(folded, nomes)


def extrair_os(valor) -> tuple[str, str]:
    bruto = ("" if valor is None else str(valor)).strip()
    if not bruto:
        return "", "ausente"
    compacto = re.sub(r"\s+", "", bruto)
    if _OS_RE.fullmatch(compacto):
        return compacto, ""
    return "", "invalida"


def parse_data_instalacao(valor):
    s = ("" if valor is None else str(valor)).strip()
    if not s:
        return None
    if "T" in s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    for fmt, tamanho in (("%d/%m/%Y %H:%M", 16), ("%d/%m/%Y", 10), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:tamanho], fmt).date()
        except ValueError:
            continue
    return None


def normalizar_periodo(valor) -> str:
    texto = _fold(valor)
    if "MANH" in texto:
        return "MANHA"
    # Noite não existe no cadastro da venda; grava como Tarde.
    if "TARD" in texto or "NOIT" in texto:
        return "TARDE"
    return ""


def _rotulo_periodo(codigo: str) -> str:
    return {"MANHA": "Manhã", "TARDE": "Tarde"}.get(codigo, codigo)


def linha_do_historico(hp) -> dict:
    payload = hp.payload if isinstance(hp.payload, dict) else {}
    mapeado = map_pedido_api(payload, getattr(hp, "tipo_venda", "") or "VENDA") if payload else {}
    tem_dado = any(
        mapeado.get(k)
        for k in ("status_primario", "status_secundario", "os_instalacao", "data_instalacao", "periodo_instalacao")
    )
    if not tem_dado:
        mapeado = {
            "pedido": payload.get("pedido") or payload.get("Pedido") or hp.numero_pedido,
            "status_primario": (
                payload.get("status_primario")
                or payload.get("Status primário")
                or payload.get("chaveStatusPrimario")
                or ""
            ),
            "status_secundario": (
                payload.get("status_secundario")
                or payload.get("Status secundário")
                or payload.get("subStatus")
                or ""
            ),
            "os_instalacao": payload.get("os_instalacao") or payload.get("OS instalação") or "",
            "data_instalacao": payload.get("data_instalacao") or payload.get("Data instalação") or "",
            "periodo_instalacao": payload.get("periodo_instalacao") or payload.get("Período instalação") or "",
            "cpf": payload.get("cpf") or payload.get("CPF") or "",
            "cliente": payload.get("cliente") or payload.get("Cliente") or "",
        }
    if not mapeado.get("status_primario"):
        mapeado["status_primario"] = getattr(hp, "status", "") or ""
    if not mapeado.get("pedido"):
        mapeado["pedido"] = hp.numero_pedido
    return mapeado


def _chave_pedido(valor) -> str:
    norm = normalizar_pedido(valor)
    if norm:
        return norm
    return _digitos(valor)


def _item(venda, pedido, linha, status_aplicado, detalhe) -> dict:
    cliente = getattr(venda, "cliente", None)
    return {
        "venda_id": venda.id,
        "pedido": pedido or (venda.pedido_pap or ""),
        "cliente": (getattr(cliente, "nome_razao_social", "") or "") if cliente else "",
        "cpf": (getattr(cliente, "cpf_cnpj", "") or "") if cliente else "",
        "status_primario": (linha or {}).get("status_primario") or "",
        "status_secundario": (linha or {}).get("status_secundario") or "",
        "status_aplicado": status_aplicado or "",
        "detalhe": detalhe,
    }


def _encerrar_sessao(venda_id: int, motivo: str, status_nome: str) -> None:
    try:
        from crm_app.models import SessaoTratamento
        from crm_app.services import tempo_tratamento_service as tt_svc

        tt_svc.encerrar_sessoes_venda(
            venda_id,
            SessaoTratamento.MODULO_AUDITORIA,
            motivo,
            status_resultado=status_nome,
        )
    except Exception:
        logger.exception("Falha ao encerrar sessão de tratamento da venda #%s", venda_id)


def _gravar_historico(venda, usuario, texto: str, extra: dict | None = None) -> None:
    alteracoes = {"status_tratamento": texto, "origem": "sincronizar_vendas_pap"}
    if extra:
        alteracoes.update(extra)
    HistoricoAlteracaoVenda.objects.create(
        venda=venda,
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        alteracoes=alteracoes,
    )


def _anexar_observacao(venda, nota: str) -> None:
    atual = (venda.observacoes or "").strip()
    if nota in atual:
        return
    venda.observacoes = f"{atual}\n{nota}".strip() if atual else nota


def _outra_venda_na_esteira(venda, documentos: set[str]):
    if not documentos:
        return None
    return (
        Venda.objects.filter(
            ativo=True,
            cliente__cpf_cnpj__in=documentos,
            status_esteira__isnull=False,
        )
        .exclude(pk=venda.pk)
        .exclude(Q(ordem_servico__isnull=True) | Q(ordem_servico__exact=""))
        .select_related("cliente", "status_esteira")
        .order_by("-id")
        .first()
    )


def _aplicar_esteira(venda, usuario, linha, catalogo) -> tuple[str, str, str]:
    os_valor, os_erro = extrair_os(linha.get("os_instalacao"))
    data = parse_data_instalacao(linha.get("data_instalacao"))
    periodo = normalizar_periodo(linha.get("periodo_instalacao"))
    if os_erro == "ausente":
        return "inalterado", "", "Sem informação suficiente: O.S. instalação."
    if os_erro == "invalida":
        bruto = linha.get("os_instalacao")
        return "inalterado", "", f'Sem informação suficiente: O.S. instalação inválida ("{bruto}").'
    if not catalogo["cadastrada"]:
        return "inalterado", "", "Status CADASTRADA não está cadastrado."

    conflito = buscar_venda_os_ja_cadastrada(os_valor, excluir_venda_id=venda.id)
    if conflito:
        return "inalterado", "", mensagem_os_ja_cadastrada(os_valor, conflito)

    agenda_completa = bool(data and periodo)
    if agenda_completa:
        if not catalogo["agendado"]:
            return "inalterado", "", "Status AGENDADO não está cadastrado."
        esteira = catalogo["agendado"]
        motivo = None
        rotulo_esteira = "AGENDADO"
    else:
        if not catalogo["pendenciada"]:
            return "inalterado", "", "Status de esteira PENDENCIADA não está cadastrado."
        if not catalogo["motivo_7030"]:
            return "inalterado", "", "Pendência 7030 (falta de slot) não está cadastrada."
        esteira = catalogo["pendenciada"]
        motivo = catalogo["motivo_7030"]
        rotulo_esteira = "PENDENCIADA"

    with transaction.atomic():
        venda.ordem_servico = os_valor
        venda.data_agendamento = data
        venda.periodo_agendamento = periodo or None
        venda.status_tratamento = catalogo["cadastrada"]
        venda.status_esteira = esteira
        venda.motivo_pendencia = motivo
        venda.data_abertura = timezone.now()
        venda.auditor_atual = None
        venda.save()
        _gravar_historico(
            venda,
            usuario,
            f"Auditoria finalizada via PAP: {rotulo_esteira}",
            {
                "ordem_servico": os_valor,
                "data_agendamento": data.isoformat() if data else "",
                "periodo_agendamento": periodo,
                "status_esteira": rotulo_esteira,
                "motivo_pendencia": getattr(motivo, "nome", "") or "",
            },
        )
        _encerrar_sessao(venda.id, "CADASTRADO", rotulo_esteira)

    if agenda_completa:
        noite = "NOIT" in _fold(linha.get("periodo_instalacao"))
        turno = _rotulo_periodo(periodo)
        if noite:
            turno += " (Noite no PAP)"
        detalhe = (
            f"O.S. {os_valor} · instalação {data.strftime('%d/%m/%Y')} · {turno}. "
            "Status CADASTRADA e esteira AGENDADO."
        )
        return "esteira", "CADASTRADA", detalhe

    faltas = []
    if not data:
        faltas.append("data")
    if not periodo:
        bruto_periodo = (linha.get("periodo_instalacao") or "").strip()
        if bruto_periodo:
            faltas.append(f'turno "{bruto_periodo}"')
        else:
            faltas.append("turno")
    nome_motivo = getattr(motivo, "nome", "") or "7030"
    detalhe = (
        f"O.S. {os_valor}. Agenda incompleta ({', '.join(faltas)}). "
        f"Esteira PENDENCIADA, pendência {nome_motivo}."
    )
    return "esteira", nome_motivo, detalhe


def _aplicar_reprova(venda, usuario, status_obj, nota: str, detalhe: str) -> tuple[str, str, str]:
    if venda.status_tratamento_id == status_obj.id:
        return "inalterado", status_obj.nome, f"Já estava com o status {status_obj.nome}."
    with transaction.atomic():
        venda.status_tratamento = status_obj
        venda.auditor_atual = None
        _anexar_observacao(venda, nota[:500])
        venda.save()
        _gravar_historico(
            venda,
            usuario,
            f"Auditoria reprovada via PAP: {status_obj.nome}",
            {"motivo_pap": nota},
        )
        _encerrar_sessao(venda.id, "REPROVADO", status_obj.nome)
    return "reprovado", status_obj.nome, detalhe


def _processar_venda(venda, usuario, linha, catalogo) -> tuple[str, str, str]:
    primario = _chave(linha.get("status_primario"))
    if primario == "PEDIDO_GERADO":
        return _aplicar_esteira(venda, usuario, linha, catalogo)

    if primario == "VENDA_NAO_CONFIRMADA":
        status_obj, motivo = resolver_status_reprova(linha.get("status_secundario"), catalogo["tratamentos"])
        if not status_obj:
            return "inalterado", "", motivo
        secundario = (linha.get("status_secundario") or "").strip()
        nota = f"[Sincronização PAP] VENDA_NAO_CONFIRMADA: {secundario}"
        detalhe = f'PAP: "{secundario}" → {status_obj.nome}.'
        return _aplicar_reprova(venda, usuario, status_obj, nota, detalhe)

    if primario == "ANALISE_BO":
        docs = set()
        docs |= _variantes_documento(linha.get("cpf"))
        if venda.cliente_id:
            docs |= _variantes_documento(venda.cliente.cpf_cnpj)
        if not docs:
            return "inalterado", "", "CPF ausente para verificar duplicidade."
        outra = _outra_venda_na_esteira(venda, docs)
        if not outra:
            return "inalterado", "", "ANALISE_BO sem outro pedido deste CPF já na esteira com O.S."
        status_dup = catalogo["duplicidade"]
        if not status_dup:
            return "inalterado", "", 'Status de tratamento "DUPLICIDADE" não está cadastrado.'
        esteira_nome = getattr(getattr(outra, "status_esteira", None), "nome", "") or ""
        nota = (
            f"[Sincronização PAP] ANALISE_BO: CPF já possui a venda #{outra.id} "
            f"na esteira (O.S. {outra.ordem_servico})."
        )
        detalhe = (
            f"CPF já tem a venda #{outra.id} na esteira "
            f"(O.S. {outra.ordem_servico}"
            + (f", {esteira_nome}" if esteira_nome else "")
            + ") → DUPLICIDADE."
        )
        return _aplicar_reprova(venda, usuario, status_dup, nota, detalhe)

    legivel = (linha.get("status_primario") or "vazio").strip() or "vazio"
    return "inalterado", "", f'Status primário "{legivel}" não altera a venda.'


def sincronizar_vendas_com_pap(*, usuario) -> dict:
    vendas = list(
        Venda.objects.filter(
            ativo=True,
            status_tratamento__isnull=False,
            status_esteira__isnull=True,
        )
        .exclude(status_tratamento__estado__iexact="FECHADO")
        .select_related("cliente", "status_tratamento", "vendedor")
        .order_by("-id")
    )
    tratamentos = list(StatusCRM.objects.filter(tipo="Tratamento"))
    catalogo = {
        "tratamentos": tratamentos,
        "cadastrada": buscar_status_por_nome(tratamentos, "CADASTRADA"),
        "duplicidade": buscar_status_por_nome(tratamentos, "DUPLICIDADE"),
        "agendado": StatusCRM.objects.filter(tipo="Esteira", nome__iexact="AGENDADO").first(),
        "pendenciada": (
            StatusCRM.objects.filter(tipo="Esteira", nome__iexact="PENDENCIADA").first()
            or StatusCRM.objects.filter(tipo="Esteira", nome__icontains="PENDEN")
            .exclude(nome__icontains="CANCEL")
            .first()
        ),
        "motivo_7030": resolver_motivo_pendencia_por_texto_pap("7030"),
    }

    com_protocolo = []
    sem_protocolo = 0
    chaves = []
    for venda in vendas:
        chave = _chave_pedido(venda.pedido_pap)
        if not chave:
            sem_protocolo += 1
            continue
        com_protocolo.append((venda, chave))
        chaves.append(chave)

    historicos = {}
    if chaves:
        for hp in HistoricoPapPedido.objects.filter(numero_pedido__in=chaves):
            historicos[_chave_pedido(hp.numero_pedido) or hp.numero_pedido] = hp

    grupos = {"esteira": [], "reprovadas": [], "inalteradas": []}
    for venda, chave in com_protocolo:
        hp = historicos.get(chave)
        if not hp:
            grupos["inalteradas"].append(
                _item(
                    venda,
                    chave,
                    {},
                    "",
                    "Pedido não encontrado na base do PAP. Use Buscar do PAP antes de sincronizar.",
                )
            )
            continue
        linha = linha_do_historico(hp)
        try:
            resultado, aplicado, detalhe = _processar_venda(venda, usuario, linha, catalogo)
        except Exception:
            logger.exception("Falha ao sincronizar venda #%s com o PAP", venda.id)
            resultado, aplicado, detalhe = "inalterado", "", "Falha ao gravar esta venda."
        bucket = {"esteira": "esteira", "reprovado": "reprovadas", "inalterado": "inalteradas"}[resultado]
        grupos[bucket].append(_item(venda, linha.get("pedido") or chave, linha, aplicado, detalhe))

    return {
        "resumo": {
            "analisadas": len(com_protocolo),
            "esteira": len(grupos["esteira"]),
            "reprovadas": len(grupos["reprovadas"]),
            "inalteradas": len(grupos["inalteradas"]),
            "sem_protocolo": sem_protocolo,
        },
        "esteira": grupos["esteira"],
        "reprovadas": grupos["reprovadas"],
        "inalteradas": grupos["inalteradas"],
    }


class AuditoriaSincronizarVendasPapView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, GRUPOS_SYNC):
            return Response({"detail": "Permissão negada."}, status=403)
        try:
            dados = sincronizar_vendas_com_pap(usuario=request.user)
        except Exception:
            logger.exception("Falha ao sincronizar vendas da auditoria com o PAP")
            return Response(
                {"detail": "Não foi possível sincronizar as vendas com o PAP."},
                status=500,
            )
        return Response(dados)
