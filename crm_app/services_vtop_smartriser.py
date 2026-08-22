"""
Automação SmartRiser (V.top / V.tal) a partir do Gestão CDOI.

Princípios de sessão:
- NÃO faz logout em nenhum momento.
- Persiste cookies em storage_state (arquivo) após o login manual.
- Reusa a sessão nos próximos acionamentos — evita relogar o IdP corporativo.
- Login manual: abre o browser, aguarda o usuário digitar credenciais e
  o botão "Já coloquei a senha" no CDOI; só então clica em EFETUAR LOGIN.

Fluxo (passos):
  1. Login IdP (manual + clique automatizado)
  2. Portal V.top → card SmartRiser
  3. Brownfield (risers em HPs até 2024)
  4. FAB "+" → modal Cadastro de nova obra
  5. Preencher + Salvar obra
  6. Modal coordenadas (lat/long) + Salvar
  7. obra.jsp Cadastro → dados + anexos → disquete → validar
"""

from __future__ import annotations

import logging
import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Browser = BrowserContext = Page = None  # type: ignore
    sync_playwright = None  # type: ignore
    logger.warning("[VTOP] Playwright não instalado. Automação SmartRiser desabilitada.")

# =============================================================================
# URLs e configuração
# =============================================================================

VTOP_HOME_URL = "https://vtop.vtal.com/appvtop/"
VTOP_SMARTRISER_URL = "https://vtop.vtal.com/appvtop/smartriser/"
VTOP_LOGIN_URL = (
    "https://login.vtal.com/nidp/app/login"
    "?id=VtalCorpPwdLessId&sid=2&option=credential&sid=2"
    "&target=https%3A%2F%2Flogin.vtal.com%2Fnidp%2Foauth%2Fnam%2Fauthz"
    "%3Fclient_id%3D34132d5e-35ac-40c5-a2b3-2123a343ef13"
    "%26redirect_uri%3Dhttps%3A%2F%2Fvtop.vtal.com%2Fcallback%3Fw%3D1"
    "%26response_type%3Dcode%26scope%3Dvtal_operacao%26grant_type%3Dclient_credentials"
)

# Código parceiro SAP (mesmo padrão Inclusão / PDV Record)
CODIGO_SAP_PADRAO = "1068561"
# Pré-venda por obra = teto de 18% dos HPs do bloco (regra Record / SmartRiser)
PRE_VENDA_PCT_BLOCO = 0.18


def calcular_pre_venda_bloco(hps: int) -> int:
    """Retorna ceil(18% × HPs do bloco). Ex.: 16→3, 18→4."""
    hps_i = int(hps or 0)
    if hps_i <= 0:
        return 0
    return max(1, int(math.ceil(hps_i * PRE_VENDA_PCT_BLOCO)))

DEFAULT_TIMEOUT_MS = 30_000
LOGIN_WAIT_SECONDS = 15 * 60  # tempo máximo aguardando o usuário digitar a senha


def _storage_state_path() -> str:
    path = getattr(
        settings,
        "VTOP_STORAGE_STATE",
        os.path.join(settings.BASE_DIR, ".playwright_vtop_state.json"),
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _garantir_storage_state_arquivo() -> bool:
    """
    Garante arquivo de sessão Playwright.
    Em Railway o disco é efêmero — use VTOP_STORAGE_STATE_B64 (JSON em base64
    gerado localmente com scripts/teste_login_vtop.py + publicar_sessao_vtop_railway.py).
    """
    path = _storage_state_path()
    if os.path.isfile(path) and os.path.getsize(path) > 50:
        return True

    b64 = (getattr(settings, "VTOP_STORAGE_STATE_B64", None) or os.environ.get("VTOP_STORAGE_STATE_B64") or "").strip()
    if not b64:
        return False
    try:
        import base64

        raw = base64.b64decode(b64, validate=False)
        if raw[:1] != b"{":
            raw = b64.encode("utf-8")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(raw)
        logger.info(
            "[VTOP] Storage state materializado de VTOP_STORAGE_STATE_B64 (%s bytes) -> %s",
            len(raw),
            path,
        )
        return True
    except Exception:
        logger.exception("[VTOP] Falha ao materializar VTOP_STORAGE_STATE_B64")
        return False


def _headless() -> bool:
    return bool(getattr(settings, "VTOP_HEADLESS", False))


# =============================================================================
# Mapa de campos CDOI → V.top
# =============================================================================
#
# Gestão CDOI (CdoiSolicitacao)          →  SmartRiser
# --------------------------------------    ---------------------------------
# nome_condominio                        →  Cadastro: NOME DO CONDOMINIO
#                                           Obra: FACHADA (opcional / espelho do nome curto)
# nome_sindico                           →  Cadastro: NOME DO SÍNDICO
# contato_sindico                        →  Cadastro: NÚMERO DE CONTATO SÍNDICO/CONDOMÍNIO
# cep                                    →  (só no CDOI; V.top usa endereço estruturado)
# logradouro                             →  Obra: LOGRADOURO
# numero                                 →  Obra: NUM + Cadastro NUM FACHADA
# bairro                                 →  Obra: BAIRRO
# cidade                                 →  Obra: LOCALIDADE
# uf                                     →  Obra: UF
# latitude / longitude                   →  Modal mapa + LOCALIZAÇÃO
# total_hps                              →  Obra: QUANTIDADE UMS + Cadastro TOTAL DE HPs
# pre_venda                               →  Cadastro: PRÉ-VENDA = ceil(18% × HPs do bloco)
# infraestrutura_tipo + shaft + blocos   →  Cadastro: CARACTERÍSTICAS DO PRÉDIO
# blocos[].nome / andares / aptos        →  Cadastro: BLOCOS / ANDARES / texto características
# link_carta_sindico (R2)                →  Cadastro: CARTA DE AUTORIZAÇÃO (upload)
# link_fotos_fachada (R2)                →  Cadastro: FOTOS DA FACHADA (upload)
# id (CDOI)                              →  Obra: CDOI (código interno Record — conferir regra)
# —                                      →  Obra: COD SURVEY (vazio / manual se necessário)
# —                                      →  Obra: ESTAÇÃO / CÉLULA (vazio até termos regra)
# —                                      →  Obra: MÊS (default: mês atual no portal)
# —                                      →  Cadastro: CÓDIGO DO PARCEIRO (SAP) = 1068561
# complemento (montado dos blocos)       →  Obra: COMPLEMENTO


SELETORES: Dict[str, Dict[str, str]] = {
    "login": {
        "btn_efetuar": 'button:has-text("EFETUAR LOGIN"), button:has-text("EFETUAR"), button[type="submit"]',
    },
    "portal": {
        "card_smartriser": (
            'div:has-text("SmartRiser - Rede Inteligente Vertical"), '
            'a:has-text("SmartRiser"), '
            'text=SmartRiser - Rede Inteligente Vertical'
        ),
    },
    "smartriser": {
        "brownfield": (
            'text=/Brownfield.*risers.*2024/i, '
            'a:has-text("Brownfield"), '
            'div:has-text("Brownfield"):has-text("2024")'
        ),
        "fab_mais": (
            'button:has-text("+"), '
            '[aria-label="+"], '
            'button.btn-floating:has-text("+"), '
            '.fixed-action-btn a'
        ),
    },
    "obra_modal": {
        "titulo": 'text=Cadastro de nova obra',
        "cod_survey": 'input[name*="survey" i], label:has-text("COD SURVEY") ~ input, label:has-text("COD SURVEY") + input',
        "uf": 'select:near(:text("UF")), label:has-text("UF") ~ select, label:has-text("UF") + select',
        "localidade": 'input:near(:text("LOCALIDADE")), label:has-text("LOCALIDADE") ~ input',
        "estacao": 'input:near(:text("ESTAÇÃO")), label:has-text("ESTAÇÃO") ~ input, label:has-text("ESTACAO") ~ input',
        "mes": 'select:near(:text("MÊS")), label:has-text("MÊS") ~ select',
        "logradouro": 'input:near(:text("LOGRADOURO")), label:has-text("LOGRADOURO") ~ input',
        "num": 'input:near(:text("NUM")), label:has-text("NUM") ~ input',
        "fachada": 'input:near(:text("FACHADA")), label:has-text("FACHADA") ~ input',
        "bairro": 'input:near(:text("BAIRRO")), label:has-text("BAIRRO") ~ input',
        "complemento": 'input:near(:text("COMPLEMENTO")), label:has-text("COMPLEMENTO") ~ input',
        "celula": 'input:near(:text("CÉLULA")), label:has-text("CÉLULA") ~ input, label:has-text("CELULA") ~ input',
        "cdoi": 'input:near(:text("CDOI")), label:has-text("CDOI") ~ input',
        "qtd_ums": 'input:near(:text("QUANTIDADE UMS")), label:has-text("QUANTIDADE UMS") ~ input',
        "btn_salvar": 'button:has-text("Salvar")',
        "btn_cancelar": 'button:has-text("Cancelar")',
    },
    "coords_modal": {
        "titulo": 'text=/Selecione no mapa|Latitude/i',
        "latitude": 'input:near(:text("Latitude")), label:has-text("Latitude") ~ input, input[name*="lat" i]',
        "longitude": 'input:near(:text("Longitude")), label:has-text("Longitude") ~ input, input[name*="lng" i], input[name*="long" i]',
        "btn_procurar": 'button:has-text("Procurar")',
        "btn_salvar": 'button:has-text("Salvar")',
    },
    # Etapa 1 (Cadastro) em obra.jsp — IDs dinâmicos: edit_{obra_id}_1_{n}
    # Mapeado em 2026-08 (obra 9416 / BLOCO 05):
    #   _2 NOME DO CONDOMINIO
    #   _3 NOME DO SINDICO
    #   _4 NÚMERO DE CONTATO SÍNDICO/CONDOMINIO
    #   _5 CARTA DE AUTORIZAÇÃO (texto; anexo via fa-square-plus → addDocFoto)
    #   _6 CÓDIGO DO PARCEIRO (SAP)
    #   _7 QUANTIDADE DE BLOCOS… → #input_blocos #input_andares #input_total_hps #input_prevenda + edit_*_1_8
    #   _9 FOTOS DA FAIXADA DO CONDOMINIO (texto; anexo via +)
    # Botões: #btn_salvarEtapa | #btn_validarEtapa | #btn_reprovarEtapa
    "cadastro_obra": {
        "nome_condominio": "#edit_{obra_id}_1_2",
        "nome_sindico": "#edit_{obra_id}_1_3",
        "contato": "#edit_{obra_id}_1_4",
        "carta_texto": "#edit_{obra_id}_1_5",
        "codigo_sap": "#edit_{obra_id}_1_6",
        "caracteristicas": "#edit_{obra_id}_1_8",
        "fotos_texto": "#edit_{obra_id}_1_9",
        "input_blocos": "#input_blocos",
        "input_andares": "#input_andares",
        "input_total_hps": "#input_total_hps",
        "input_prevenda": "#input_prevenda",
        "btn_salvar_etapa": "#btn_salvarEtapa",
        "btn_validar_etapa": "#btn_validarEtapa",
        "btn_reprovar_etapa": "#btn_reprovarEtapa",
        "btn_salvar_disquete": "#btn_salvarEtapa, button[title*='Salvar' i]",
        "btn_validar": 'button:has(.fa-check), button[title*="validar" i], a:has(.fa-check)',
    },
}


class VtopStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    AWAITING_CREDENTIALS = "awaiting_credentials"
    CLICKING_LOGIN = "clicking_login"
    LOGGED_IN = "logged_in"
    NAVIGATING = "navigating"
    FILLING_OBRA = "filling_obra"
    FILLING_COORDS = "filling_coords"
    FILLING_CADASTRO = "filling_cadastro"
    UPLOADING = "uploading"
    SAVING = "saving"
    VALIDATING = "validating"
    DONE = "done"
    ERROR = "error"
    PAUSED = "paused"


@dataclass
class VtopJobState:
    cdoi_id: Optional[int] = None
    status: VtopStatus = VtopStatus.IDLE
    message: str = ""
    step: str = ""
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: str = ""
    session_valid: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        extras = dict(self.extras or {})
        extras.pop("vtop_senha", None)
        extras.pop("senha", None)
        extras.pop("_vtop_senha_runtime", None)
        return {
            "cdoi_id": self.cdoi_id,
            "status": self.status.value,
            "message": self.message,
            "step": self.step,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "session_valid": self.session_valid,
            "extras": extras,
            "needs_vtop_login": self.error == "needs_vtop_login",
        }


def _norm_nome_bloco(nome: str) -> str:
    """Normaliza nome de bloco/complemento para comparação (BLOCO 05 → BLOCO 5)."""
    s = (nome or "").strip().upper()
    # Grade Brownfield trunca com reticências (ADMINISTRA… / ADMINISTRA...)
    s = s.replace("…", "").replace("...", "").strip()
    m = re.match(r"BLOCO\s*0*(\d+)$", s)
    if m:
        return f"BLOCO {int(m.group(1))}"
    return (
        s.replace("Ç", "C")
        .replace("Ã", "A")
        .replace("Á", "A")
        .replace("Â", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Õ", "O")
        .replace("Ú", "U")
    )


def _bloco_equiv(a: str, b: str) -> bool:
    """True se os nomes representarem o mesmo complemento (tolera truncamento não-numérico)."""
    na, nb = _norm_nome_bloco(a), _norm_nome_bloco(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Nunca confundir BLOCO 1 com BLOCO 10 (startswith quebraria)
    if na.startswith("BLOCO ") or nb.startswith("BLOCO "):
        return False
    # ADMINISTRAÇÃO / ADMINISTRATIVO / ADMINISTRA… são o mesmo complemento de negócio
    if na.startswith("ADMINISTRA") and nb.startswith("ADMINISTRA"):
        return True
    # Truncado na lista (não numérico): PREFIX ≈ PREFIXO_LONGO
    curto, longo = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(curto) >= 6 and longo.startswith(curto):
        return True
    return False


def vtop_criar_permitido(payload: Optional[Dict[str, Any]] = None) -> bool:
    """
    Criação liberada por padrão.

    Anti-duplicação NÃO é esta flag — é o inventário Brownfield
    (mesmo logradouro+número+complemento → reusa, não cria).

    Bloqueio só se VTOP_BLOQUEAR_CRIAR_OBRA=true ou VTOP_PERMITIR_CRIAR_OBRA=false.
    """
    if bool(getattr(settings, "VTOP_BLOQUEAR_CRIAR_OBRA", False)):
        return False
    if not bool(getattr(settings, "VTOP_PERMITIR_CRIAR_OBRA", True)):
        return False
    # payload.permitir_criar=false explícito pode bloquear uma requisição
    if payload is not None and "permitir_criar" in payload and not payload.get("permitir_criar"):
        return False
    return True


def ler_etapa_obra_page(page) -> Optional[int]:
    """Lê obra.etapa no JS da página; None se indisponível."""
    try:
        etapa = page.evaluate(
            "() => (typeof obra !== 'undefined' && obra && obra.etapa != null ? obra.etapa : null)"
        )
        if etapa is None:
            return None
        return int(etapa)
    except Exception:
        return None



def persistir_vtop_obra_bloco(
    cdoi_id: Optional[int],
    nome_bloco: str,
    obra_id: str,
    etapa: Optional[int] = None,
    *,
    sobrescrever: bool = False,
) -> bool:
    """
    Grava o vínculo bloco → obra_id no CdoiBloco.
    Por padrão NÃO sobrescreve obra_id diferente (anti-duplicação / lista truncada).
    """
    if not cdoi_id or not obra_id or not nome_bloco:
        return False
    try:
        from django.utils import timezone
        from crm_app.models import CdoiBloco

        qs = CdoiBloco.objects.filter(solicitacao_id=int(cdoi_id))
        bloco = None
        for b in qs:
            if _bloco_equiv(b.nome_bloco, nome_bloco):
                bloco = b
                break
        if bloco is None:
            logger.warning(
                "[VTOP] Bloco '%s' não encontrado no CDOI %s para gravar obra_id=%s",
                nome_bloco,
                cdoi_id,
                obra_id,
            )
            return False
        atual = (bloco.vtop_obra_id or "").strip()
        novo = str(obra_id).strip()
        if atual and atual != novo and not sobrescrever:
            logger.warning(
                "[VTOP] Mantém obra_id=%s em '%s' (ignorou %s da lista) — use sobrescrever=True se for intencional",
                atual,
                bloco.nome_bloco,
                novo,
            )
            # Ainda atualiza etapa se veio
            if etapa is not None:
                try:
                    bloco.vtop_etapa = int(etapa)
                    bloco.vtop_sincronizado_em = timezone.now()
                    bloco.save(update_fields=["vtop_etapa", "vtop_sincronizado_em"])
                except (TypeError, ValueError):
                    pass
            return False
        bloco.vtop_obra_id = novo
        if etapa is not None:
            try:
                bloco.vtop_etapa = int(etapa)
            except (TypeError, ValueError):
                pass
        bloco.vtop_sincronizado_em = timezone.now()
        bloco.save(
            update_fields=["vtop_obra_id", "vtop_etapa", "vtop_sincronizado_em"]
        )
        logger.info(
            "[VTOP] Vínculo gravado CDOI=%s bloco=%s obra_id=%s etapa=%s",
            cdoi_id,
            bloco.nome_bloco,
            novo,
            etapa,
        )
        return True
    except Exception:
        logger.exception(
            "[VTOP] Falha ao gravar obra_id=%s no CDOI %s / bloco %s",
            obra_id,
            cdoi_id,
            nome_bloco,
        )
        return False


def montar_payload_cdoi(cdoi) -> Dict[str, Any]:
    """Converte CdoiSolicitacao (+ blocos) no dict base (ainda sem escolher 1 bloco)."""
    blocos = list(cdoi.blocos.all().order_by("nome_bloco"))
    blocos_data = [
        {
            "nome": b.nome_bloco,
            "andares": int(b.andares or 0),
            "aptos": int(b.unidades_por_andar or 0),
            "total": int(b.total_hps_bloco or (int(b.andares or 0) * int(b.unidades_por_andar or 0))),
            "obra_id": (b.vtop_obra_id or "").strip(),
            "vtop_etapa": b.vtop_etapa,
        }
        for b in blocos
    ]
    max_andares = max((b["andares"] for b in blocos_data), default=0)

    partes_caract: List[str] = []
    for b in blocos_data:
        partes_caract.append(
            f"{b['nome']}: {b['andares']} andares, {b['aptos']} ums/andar "
            f"({b['total']} HPs)"
        )
    infra = (cdoi.infraestrutura_tipo or "").strip()
    if infra:
        partes_caract.append(f"Infraestrutura: {infra}")
    partes_caract.append(f"Shaft/DG: {'sim' if cdoi.possui_shaft_dg else 'não'}")

    return {
        "cdoi_id": cdoi.id,
        "nome_condominio": (cdoi.nome_condominio or "").strip(),
        "nome_sindico": (cdoi.nome_sindico or "").strip(),
        "contato": re.sub(r"\D", "", cdoi.contato_sindico or ""),
        "cep": re.sub(r"\D", "", cdoi.cep or ""),
        "logradouro": (cdoi.logradouro or "").strip(),
        "numero": (cdoi.numero or "").strip(),
        "bairro": (cdoi.bairro or "").strip(),
        "cidade": (cdoi.cidade or "").strip(),
        "uf": (cdoi.uf or "").strip().upper(),
        "latitude": (cdoi.latitude or "").strip(),
        "longitude": (cdoi.longitude or "").strip(),
        # Totais do condomínio (referência). Por obra use payload_para_bloco().
        "total_hps_condominio": int(cdoi.total_hps or 0),
        "pre_venda": int(cdoi.pre_venda_minima or 0),
        "qtd_blocos": len(blocos_data),
        "max_andares": max_andares,
        "caracteristicas": "; ".join(partes_caract),
        "link_carta": cdoi.link_carta_sindico or "",
        "link_fachada": cdoi.link_fotos_fachada or "",
        "codigo_sap": getattr(settings, "VTOP_CODIGO_SAP", CODIGO_SAP_PADRAO),
        "cod_survey": "",
        "estacao": "",
        "celula": "",
        "cdoi_codigo": str(cdoi.id),
        "blocos": blocos_data,
        # Campos da obra atual — vazios até escolher o bloco
        "bloco_nome": "",
        "complemento": "",
        "total_hps": 0,
        "andares": 0,
        "aptos": 0,
    }


def payload_para_bloco(payload_base: Dict[str, Any], nome_bloco: str) -> Dict[str, Any]:
    """
    Monta payload de UMA obra SmartRiser a partir de um bloco do CDOI.

    Regra de negócio:
      - Cada nome de bloco (complemento) = uma obra separada
      - QUANTIDADE UMS = andares × aptos do bloco (ou total do bloco)
      - NÃO concatenar todos os blocos no complemento
    """
    alvo = (nome_bloco or "").strip().upper()
    escolhido = None
    for b in payload_base.get("blocos") or []:
        nome = str(b.get("nome") or "").strip()
        if nome.upper() == alvo:
            escolhido = b
            break
    if not escolhido:
        # tolerância: "BLOCO 5" == "BLOCO 05"
        m = re.match(r"BLOCO\s*0*(\d+)$", alvo)
        if m:
            num = m.group(1)
            for b in payload_base.get("blocos") or []:
                nome = str(b.get("nome") or "").strip().upper()
                m2 = re.match(r"BLOCO\s*0*(\d+)$", nome)
                if m2 and m2.group(1) == num:
                    escolhido = b
                    break
    if not escolhido:
        raise ValueError(f"Bloco '{nome_bloco}' não encontrado no payload CDOI.")

    andares = int(escolhido.get("andares") or 0)
    aptos = int(escolhido.get("aptos") or 0)
    total = int(escolhido.get("total") or 0) or (andares * aptos)
    nome_oficial = str(escolhido.get("nome") or nome_bloco).strip()

    out = dict(payload_base)
    out["bloco_nome"] = nome_oficial
    out["complemento"] = nome_oficial  # = nome do bloco no Gestão CDOI
    out["andares"] = andares
    out["aptos"] = aptos
    out["total_hps"] = total
    # Reabre obra já vinculada em vez de criar duplicata com o mesmo complemento
    obra_id = str(escolhido.get("obra_id") or "").strip()
    if obra_id:
        out["obra_id"] = obra_id
    elif out.get("obra_id"):
        # limpa obra_id de outro bloco se veio no base por engano
        out.pop("obra_id", None)
    # Características desta obra (= 1 bloco), não o condomínio inteiro
    out["caracteristicas"] = (
        f"{nome_oficial}: {andares} andares, {aptos} ums/andar ({total} HPs)"
    )
    # Pré-venda da obra = 18% (ceil) dos HPs do bloco — NÃO usar o total do condomínio
    out["pre_venda"] = calcular_pre_venda_bloco(total)
    return out


def baixar_anexo_temporario(url: str, prefix: str = "vtop_") -> Optional[str]:
    """
    Obtém arquivo local para upload.
    Aceita caminho local (Windows/Unix), file:// ou URL HTTP(S).
    """
    if not url:
        return None
    # Caminho local direto
    local = url
    if url.lower().startswith("file:"):
        local = urlparse(url).path
        if os.name == "nt" and local.startswith("/"):
            local = local.lstrip("/")
    if os.path.isfile(local):
        return local
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        suffix = Path(urlparse(url).path).suffix or ".bin"
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(resp.content)
        return path
    except Exception as exc:
        logger.exception("[VTOP] Falha ao baixar anexo %s: %s", url, exc)
        return None


class VtopSmartRiserService:
    """
    Singleton por processo: mantém o browser aberto entre passos.

    Uso típico (CDOI):
      svc.iniciar(cdoi_id, payload)     # abre browser; se precisa login → awaiting_credentials
      svc.signal_senha_pronta()         # botão no CDOI
      # thread interna clica EFETUAR LOGIN, salva storage, segue o fluxo
      svc.get_state()                   # polling da UI
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._credentials_event = threading.Event()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self.state = VtopJobState()

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._temp_files: List[str] = []
        self._payload_atual: Dict[str, Any] = {}

    # ------------------------------------------------------------------ status
    def _set(
        self,
        status: VtopStatus,
        message: str = "",
        step: str = "",
        error: str = "",
        **extras: Any,
    ) -> None:
        self.state.status = status
        self.state.message = message
        if step:
            self.state.step = step
        if error:
            self.state.error = error
        if extras:
            self.state.extras.update(extras)
        self.state.updated_at = datetime.now().isoformat(timespec="seconds")
        self.state.session_valid = self._storage_exists() and status not in (
            VtopStatus.AWAITING_CREDENTIALS,
            VtopStatus.CLICKING_LOGIN,
            VtopStatus.ERROR,
        )
        logger.info("[VTOP] %s | %s | %s", status.value, step or "-", message)

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            self.state.session_valid = self._storage_exists()
            return self.state.to_dict()

    def _storage_exists(self) -> bool:
        path = _storage_state_path()
        return os.path.isfile(path) and os.path.getsize(path) > 50

    # -------------------------------------------------------------- API pública
    def iniciar(
        self,
        cdoi_id: int,
        payload: Dict[str, Any],
        *,
        forcar_login: bool = False,
        pausar_apos: Optional[str] = None,
        somente_ate: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Inicia a automação em thread dedicada (Playwright exige mesma thread).

        pausar_apos / somente_ate: nome do passo (ex.: 'portal', 'brownfield',
        'obra_modal') — útil para mapear sem concluir o fluxo todo.
        """
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {
                    "ok": False,
                    "error": "Já existe uma automação V.top em andamento.",
                    "state": self.state.to_dict(),
                }
            if not HAS_PLAYWRIGHT:
                return {"ok": False, "error": "Playwright não instalado neste ambiente."}

            self._credentials_event.clear()
            self._stop_event.clear()
            self.state = VtopJobState(
                cdoi_id=cdoi_id,
                status=VtopStatus.STARTING,
                message="Iniciando navegador…",
                started_at=datetime.now().isoformat(timespec="seconds"),
                updated_at=datetime.now().isoformat(timespec="seconds"),
                extras={
                    "forcar_login": forcar_login,
                    "pausar_apos": pausar_apos,
                    "somente_ate": somente_ate,
                },
            )

            self._worker = threading.Thread(
                target=self._run_job,
                args=(payload, forcar_login, pausar_apos, somente_ate),
                name=f"vtop-cdoi-{cdoi_id}",
                daemon=True,
            )
            self._worker.start()
            return {"ok": True, "state": self.state.to_dict()}

    def signal_senha_pronta(self) -> Dict[str, Any]:
        """Chamado pelo botão 'Já coloquei a senha' no Gestão CDOI."""
        with self._lock:
            if self.state.status != VtopStatus.AWAITING_CREDENTIALS:
                return {
                    "ok": False,
                    "error": (
                        f"Não estamos aguardando senha (status={self.state.status.value}). "
                        "Inicie a automação primeiro."
                    ),
                    "state": self.state.to_dict(),
                }
            self._credentials_event.set()
            self._set(
                VtopStatus.CLICKING_LOGIN,
                "Sinal recebido — clicando em EFETUAR LOGIN…",
                step="login",
            )
            return {"ok": True, "state": self.state.to_dict()}

    def fechar_navegador(self, *, manter_sessao: bool = True) -> Dict[str, Any]:
        """Fecha o browser. Por padrão NÃO apaga o storage_state (não desloga)."""
        self._stop_event.set()
        self._credentials_event.set()  # desbloqueia wait se estiver em login
        with self._lock:
            self._cleanup_browser(salvar_sessao=manter_sessao)
            self._set(VtopStatus.IDLE, "Navegador fechado (sessão preservada)." if manter_sessao else "Navegador fechado.")
            return {"ok": True, "state": self.state.to_dict()}

    def invalidar_sessao(self) -> Dict[str, Any]:
        """Só use se a sessão estiver corrompida. Remove o storage_state."""
        path = _storage_state_path()
        try:
            if os.path.exists(path):
                os.remove(path)
            return {"ok": True, "message": "Sessão V.top invalidada. Será necessário login manual."}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    # --------------------------------------------------------------- worker
    def _run_job(
        self,
        payload: Dict[str, Any],
        forcar_login: bool,
        pausar_apos: Optional[str],
        somente_ate: Optional[str],
    ) -> None:
        try:
            # Senha só na memória desta execução — nunca vai para extras/logs
            payload = dict(payload or {})
            _senha_runtime = str(payload.pop("vtop_senha", "") or "")
            self._payload_atual = dict(payload)
            if _senha_runtime:
                self._payload_atual["_vtop_senha_runtime"] = _senha_runtime
            self._abrir_browser(forcar_login=forcar_login)
            if not self._garantir_logado(forcar_login=forcar_login):
                return
            self._payload_atual.pop("_vtop_senha_runtime", None)

            # Teste seguro: valida login e persiste storage_state sem navegar no SmartRiser
            if (somente_ate or "").lower() == "login":
                self._salvar_storage()
                self._set(
                    VtopStatus.DONE,
                    "Login OK — sessão salva em .playwright_vtop_state.json (sem deslogar).",
                    step="login",
                )
                return

            # ------------------------------------------------------------------
            # Fluxo padrão (produção):
            #   1) Inventário Brownfield no endereço
            #   2) Se já existir o MESMO complemento → reusa (não duplica)
            #   3) Senão → cria obra nova → Cadastro → salvar → validar
            #
            # Atalho: obra_id explícito + forcar_obra_id → reabre direto (sem lista).
            # ------------------------------------------------------------------
            obra_id_forcado = ""
            if payload.get("forcar_obra_id") and str(payload.get("obra_id") or "").strip():
                obra_id_forcado = str(payload.get("obra_id")).strip()

            if obra_id_forcado:
                payload["obra_id"] = obra_id_forcado
                self._payload_atual = dict(payload)
                passos = [
                    ("abrir_obra", lambda: self._passo_abrir_obra_existente(obra_id_forcado)),
                    ("concluir_cadastro", lambda: self._passo_concluir_cadastro_se_preciso(payload)),
                ]
            else:
                # Preferência do banco entra no inventário como "preferido", não pula a checagem
                preferido_db = self._resolver_obra_id_seguro(payload)
                if preferido_db and not payload.get("obra_id"):
                    payload["obra_id"] = preferido_db
                self._payload_atual = dict(payload)
                passos = [
                    ("portal", lambda: self._passo_portal()),
                    ("smartriser", lambda: self._passo_abrir_smartriser()),
                    ("brownfield", lambda: self._passo_brownfield()),
                    ("localizar", lambda: self._passo_tentar_reusar_obra_lista(payload)),
                    ("obra_modal", lambda: self._passo_abrir_modal_obra_se_preciso(payload)),
                    ("preencher_obra", lambda: self._passo_preencher_obra_se_preciso(payload)),
                    ("coords", lambda: self._passo_coords_se_preciso(payload)),
                    ("salvar_obra", lambda: self._passo_salvar_obra_modal_se_preciso(payload)),
                    ("coords_pos_salvar", lambda: self._passo_coords_pos_salvar_se_preciso(payload)),
                    ("concluir_cadastro", lambda: self._passo_concluir_cadastro_se_preciso(payload)),
                ]

            for nome, fn in passos:
                if self._stop_event.is_set():
                    self._set(VtopStatus.IDLE, "Interrompido pelo usuário.", step=nome)
                    return
                fn()
                if pausar_apos == nome:
                    self._set(
                        VtopStatus.PAUSED,
                        f"Pausado após passo '{nome}' para mapeamento.",
                        step=nome,
                    )
                    return
                if somente_ate == nome:
                    self._set(
                        VtopStatus.DONE,
                        f"Fluxo executado até '{nome}'.",
                        step=nome,
                    )
                    return

            self._salvar_storage()
            self._set(VtopStatus.DONE, "Fluxo SmartRiser concluído.", step="fim")
        except Exception as exc:
            logger.exception("[VTOP] Erro na automação: %s", exc)
            self._set(VtopStatus.ERROR, "Falha na automação.", error=str(exc))
        finally:
            self._limpar_temp_files()
            # Mantém o browser aberto em PAUSED/DONE para inspeção local;
            # em ERROR também mantém para debug (fechar pelo botão da UI).

    # ----------------------------------------------------------- browser/sessão
    def _abrir_browser(self, *, forcar_login: bool) -> None:
        self._set(VtopStatus.STARTING, "Abrindo Chromium…", step="browser")
        self._dialog_handler_installed = False
        # Materializa sessão do env (produção) antes de abrir o contexto
        if not forcar_login:
            _garantir_storage_state_arquivo()
        self.playwright = sync_playwright().start()
        launch_opts: Dict[str, Any] = {
            "headless": _headless(),
            "slow_mo": 0 if _headless() else 80,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        self.browser = self.playwright.chromium.launch(**launch_opts)

        storage = None if forcar_login else (
            _storage_state_path() if self._storage_exists() else None
        )
        self.context = self.browser.new_context(
            storage_state=storage,
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
        )
        self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(DEFAULT_TIMEOUT_MS)

    def _salvar_storage(self) -> None:
        if self.context:
            path = _storage_state_path()
            self.context.storage_state(path=path)
            logger.info("[VTOP] Sessão salva em %s", path)
            self.state.session_valid = True

    def _cleanup_browser(self, *, salvar_sessao: bool) -> None:
        try:
            if salvar_sessao and self.context:
                self._salvar_storage()
        except Exception:
            logger.exception("[VTOP] Falha ao salvar sessão no cleanup")
        for attr in ("page", "context", "browser"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
            setattr(self, attr, None)
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self._limpar_temp_files()

    def _limpar_temp_files(self) -> None:
        for path in self._temp_files:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._temp_files.clear()

    def _esta_logado(self) -> bool:
        assert self.page is not None
        url = (self.page.url or "").lower()
        if "login.vtal.com" in url or "nidp" in url:
            return False
        # Exige evidência real de portal autenticado (evita falso positivo só pela URL)
        try:
            if self.page.locator("text=/Olá\\s+[A-Za-zÀ-ú]/i").count() > 0:
                return True
            if self.page.locator("text=Bem vindo ao portal V.top").count() > 0:
                return True
            if self.page.locator("text=SmartRiser - Rede Inteligente Vertical").count() > 0:
                return True
        except Exception:
            pass
        return False

    def _garantir_logado(self, *, forcar_login: bool) -> bool:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Abrindo V.top…", step="login")
        self.page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
        time.sleep(1.5)

        if not forcar_login and self._esta_logado():
            self._salvar_storage()
            self._set(VtopStatus.LOGGED_IN, "Sessão reutilizada — login não necessário.", step="login")
            return True

        usuario = str((self._payload_atual or {}).get("vtop_usuario") or "").strip()
        senha = str(
            (self._payload_atual or {}).get("_vtop_senha_runtime")
            or (self._payload_atual or {}).get("vtop_senha")
            or ""
        )

        if "login.vtal.com" not in (self.page.url or ""):
            self.page.goto(VTOP_LOGIN_URL, wait_until="domcontentloaded")
            time.sleep(1)

        # Produção (headless) ou local com credenciais do modal → preenche automaticamente
        if usuario and senha:
            if not self._preencher_login_automatico(usuario, senha):
                return False
            # Limpa senha da memória do payload o quanto antes
            if self._payload_atual:
                self._payload_atual.pop("vtop_senha", None)
                self._payload_atual.pop("_vtop_senha_runtime", None)
            return True

        # Headless sem credenciais: não há janela para digitar — pede modal na UI
        if _headless():
            self._set(
                VtopStatus.ERROR,
                "Sessão V.top ausente. Informe usuário e senha no modal do Gestão CDOI "
                "(em produção o navegador roda no servidor e não abre na sua tela).",
                step="login",
                error="needs_vtop_login",
            )
            return False

        # Local com browser visível: fluxo antigo (digitar no Chromium)
        self._credentials_event.clear()
        self._set(
            VtopStatus.AWAITING_CREDENTIALS,
            "Digite login/senha no navegador e clique em «Já coloquei a senha» no Gestão CDOI.",
            step="login",
        )

        ok = self._credentials_event.wait(timeout=LOGIN_WAIT_SECONDS)
        if self._stop_event.is_set():
            return False
        if not ok:
            self._set(
                VtopStatus.ERROR,
                "Tempo esgotado aguardando confirmação de senha.",
                step="login",
                error="timeout_credentials",
            )
            return False

        self._clicar_efetuar_login()
        return self._confirmar_login_pos_clique()

    def _preencher_login_automatico(self, usuario: str, senha: str) -> bool:
        """Preenche usuário/senha na tela IdP V.tal (sem logar a senha)."""
        assert self.page is not None
        page = self.page
        self._set(
            VtopStatus.CLICKING_LOGIN,
            "Preenchendo login V.tal com credenciais do modal…",
            step="login",
        )
        try:
            # Campos comuns do NIDP / login corporativo
            user_loc = page.locator(
                'input[type="text"], input[type="email"], input[name*="user" i], '
                'input[id*="user" i], input[name*="Ecom_User" i], input#Ecom_User_ID'
            ).first
            pass_loc = page.locator(
                'input[type="password"], input[name*="pass" i], input[id*="pass" i], '
                'input[name*="Ecom_Password" i], input#Ecom_Password'
            ).first
            user_loc.wait_for(state="visible", timeout=20_000)
            user_loc.fill(usuario)
            pass_loc.fill(senha)
            page.wait_for_timeout(300)
            self._clicar_efetuar_login()
            return self._confirmar_login_pos_clique()
        except Exception as exc:
            logger.exception("[VTOP] Falha ao preencher login automático")
            self._set(
                VtopStatus.ERROR,
                "Não foi possível preencher o login V.tal automaticamente.",
                step="login",
                error=str(exc)[:200],
            )
            return False

    def _confirmar_login_pos_clique(self) -> bool:
        assert self.page is not None
        try:
            self.page.wait_for_url("**/appvtop/**", timeout=90_000)
        except Exception:
            self.page.wait_for_timeout(5000)

        if not self._esta_logado():
            self.page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
            time.sleep(2)

        if not self._esta_logado():
            self._set(
                VtopStatus.ERROR,
                "Login não confirmado após EFETUAR LOGIN. Verifique usuário/senha/MFA.",
                step="login",
                error="login_failed",
            )
            return False

        self._salvar_storage()
        self._set(VtopStatus.LOGGED_IN, "Login concluído e sessão salva.", step="login")
        return True

    def _clicar_efetuar_login(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.CLICKING_LOGIN, "Clicando em EFETUAR LOGIN…", step="login")
        # Se o usuário já clicou manualmente / MFA / redirect, não falhar
        if self._esta_logado():
            return
        url = (self.page.url or "").lower()
        if "vtop.vtal.com" in url and "login.vtal.com" not in url:
            return

        seletores = [
            'button:has-text("EFETUAR LOGIN")',
            'button:has-text("EFETUAR")',
            'input[type="submit"][value*="EFETUAR" i]',
            'button[type="submit"]',
            'input[type="submit"]',
        ]
        for sel in seletores:
            loc = self.page.locator(sel)
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=5_000)
                    return
            except Exception:
                continue

        # Última tentativa: Enter no campo senha
        try:
            pwd = self.page.locator('input[type="password"]').first
            if pwd.count() > 0 and pwd.is_visible():
                pwd.press("Enter")
                return
        except Exception:
            pass

        # Não explode se o botão sumiu (usuário pode ter logado à mão)
        logger.warning("[VTOP] Botão EFETUAR LOGIN não encontrado — aguardando redirect…")
        self.page.wait_for_timeout(3000)

    # ----------------------------------------------------------------- passos
    def _passo_portal(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Abrindo portal V.top…", step="portal")
        if "appvtop" not in (self.page.url or ""):
            self.page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(1000)

    def _passo_abrir_smartriser(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Clicando no card SmartRiser…", step="smartriser")
        page = self.page
        candidatos = [
            page.get_by_text("SmartRiser - Rede Inteligente Vertical", exact=False),
            page.get_by_text("SmartRiser", exact=False),
            page.locator("div", has_text=re.compile(r"SmartRiser", re.I)),
        ]
        for loc in candidatos:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                continue
        # Fallback: URL direta do SmartRiser
        logger.warning("[VTOP] Card SmartRiser não clicado — navegando pela URL direta.")
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

    def _passo_brownfield(self) -> None:
        assert self.page is not None
        self._set(
            VtopStatus.NAVIGATING,
            "Selecionando Brownfield (risers em HPs até 2024)…",
            step="brownfield",
        )
        page = self.page
        opcao_2024 = page.get_by_text(re.compile(r"Brownfield.*2024|HPs até 2024|HPs ate 2024", re.I))
        if opcao_2024.count() > 0:
            opcao_2024.first.click()
        else:
            page.get_by_text(re.compile(r"Brownfield", re.I)).first.click()
        page.wait_for_timeout(1500)

    def _resolver_obra_id_seguro(self, payload: Dict[str, Any]) -> str:
        """Prioriza obra_id do payload; senão lê CdoiBloco.vtop_obra_id."""
        oid = str(payload.get("obra_id") or "").strip()
        if oid:
            return oid
        cdoi_id = payload.get("cdoi_id")
        nome = str(payload.get("complemento") or payload.get("bloco_nome") or "").strip()
        if not cdoi_id or not nome:
            return ""
        try:
            from crm_app.models import CdoiBloco

            for b in CdoiBloco.objects.filter(solicitacao_id=int(cdoi_id)):
                if _bloco_equiv(b.nome_bloco, nome) and (b.vtop_obra_id or "").strip():
                    return str(b.vtop_obra_id).strip()
        except Exception:
            logger.exception("[VTOP] Falha ao resolver obra_id no banco")
        return ""

    def _listar_obras_endereco(self, logradouro: str, numero: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Inventário Brownfield do endereço: complemento → [{id, etapa_txt, joined}, …].

        Percorre paginação (15/página) e amplia "Exibir" quando possível.
        Retorna lista por complemento para detectar duplicatas.
        """
        assert self.page is not None
        page = self.page
        trecho = (logradouro or "").split()[-1] if logradouro else ""

        page.evaluate(
            """() => {
              const mg = document.querySelector("input[value='MG']");
              if (mg) { mg.disabled = false; if (!mg.checked) mg.click(); }
              // Amplia página se houver select de length (DataTables / similar)
              const sels = document.querySelectorAll('select');
              for (const s of sels) {
                const opts = [...s.options].map(o => o.value);
                if (opts.includes('100') || opts.includes('50') || opts.includes('-1')) {
                  s.value = opts.includes('-1') ? '-1' : (opts.includes('100') ? '100' : '50');
                  s.dispatchEvent(new Event('change', { bubbles: true }));
                  break;
                }
              }
              const b = document.getElementById('b_pesquisa');
              if (b) b.disabled = false;
              if (typeof pesquisaObras === 'function') pesquisaObras();
            }"""
        )
        page.wait_for_timeout(4500)

        colecionados: Dict[str, Dict[str, Any]] = {}
        for _pagina in range(30):  # hard cap
            rows = page.evaluate(
                """(args) => {
                  const { trecho, numero } = args;
                  const out = [];
                  document.querySelectorAll('[onclick*=\"mostrarObra\"]').forEach(el => {
                    const oc = el.getAttribute('onclick') || '';
                    const m = oc.match(/mostrarObra\\(\\s*[\"']?(\\d+)/);
                    if (!m) return;
                    const id = m[1];
                    const tr = el.closest('tr');
                    const tds = tr
                      ? [...tr.querySelectorAll('td')].map(td =>
                          (td.innerText || '').replace(/\\s+/g, ' ').trim())
                      : [];
                    const joined = tds.join(' | ');
                    const ju = joined.toUpperCase();
                    if (trecho && !ju.includes(String(trecho).toUpperCase())) return;
                    if (numero && !ju.includes(String(numero))) return;
                    let etapaTxt = '';
                    for (const td of tds) {
                      if (/^\\d+\\s*-\\s*/.test(td)) { etapaTxt = td; break; }
                    }
                    let comp = '';
                    for (const td of tds) {
                      const u = td.toUpperCase().trim();
                      if (u.startsWith('BLOCO') || u.includes('PORTARIA') ||
                          u.includes('ADMINISTRA') || u.includes('GARAGEM')) {
                        comp = td.trim();
                        break;
                      }
                    }
                    out.push({ id, tds, joined, etapaTxt, complemento: comp });
                  });
                  return out;
                }""",
                {"trecho": trecho, "numero": str(numero or "")},
            )
            for row in rows or []:
                oid = str(row.get("id") or "").strip()
                if not oid or oid in colecionados:
                    continue
                colecionados[oid] = row

            # Próxima página
            avancou = page.evaluate(
                """() => {
                  const candidates = [
                    ...document.querySelectorAll('a, button, span'),
                  ];
                  for (const el of candidates) {
                    const t = (el.innerText || el.textContent || '').trim();
                    const title = (el.getAttribute('title') || '').toLowerCase();
                    if (t === '›' || t === '>' || t === '»' || t.toLowerCase() === 'próximo' ||
                        t.toLowerCase() === 'proximo' || title.includes('next')) {
                      const dis = el.classList.contains('disabled') ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        el.hasAttribute('disabled');
                      if (!dis && el.offsetParent !== null) {
                        el.click();
                        return true;
                      }
                    }
                  }
                  // DataTables paginate_button next
                  const n = document.querySelector('.paginate_button.next:not(.disabled)');
                  if (n) { n.click(); return true; }
                  return false;
                }"""
            )
            if not avancou:
                break
            page.wait_for_timeout(2500)

        # Agrupa por complemento normalizado
        mapa: Dict[str, List[Dict[str, Any]]] = {}
        for oid, row in colecionados.items():
            comp = str(row.get("complemento") or "").strip()
            if not comp:
                continue
            chave = _norm_nome_bloco(comp)
            # Usar chave canônica do primeiro match de alias administrativo
            if chave.startswith("ADMINISTRA"):
                chave = "ADMINISTRACAO"
            item = {
                "id": oid,
                "complemento": comp,
                "etapa_txt": row.get("etapaTxt") or "",
                "joined": row.get("joined") or "",
            }
            mapa.setdefault(chave, []).append(item)

        self.state.extras["obras_endereco"] = {
            k: [x["id"] for x in v] for k, v in mapa.items()
        }
        self.state.extras["obras_endereco_detalhe"] = mapa
        # Persist dump for auditoria produção
        try:
            path = Path(settings.BASE_DIR) / "tmp_vtop_inventario_endereco.json"
            path.write_text(
                json.dumps(mapa, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.state.extras["inventario_path"] = str(path)
        except Exception:
            pass
        return mapa

    def _escolher_obra_da_lista(
        self,
        mapa: Dict[str, List[Dict[str, Any]]],
        complemento: str,
        preferido: str = "",
    ) -> str:
        """Escolhe 1 obra_id para o complemento; se houver duplicata, prefere ID do banco / maior etapa."""
        preferido = (preferido or "").strip()
        candidatos: List[Dict[str, Any]] = []
        for chave, itens in mapa.items():
            if _bloco_equiv(chave, complemento) or _bloco_equiv(
                (itens[0].get("complemento") if itens else ""), complemento
            ):
                candidatos.extend(itens)
        if not candidatos:
            return ""
        if preferido and any(str(c["id"]) == preferido for c in candidatos):
            return preferido

        def _rank(c: Dict[str, Any]) -> Tuple[int, int]:
            et = 0
            m = re.match(r"(\d+)", str(c.get("etapa_txt") or ""))
            if m:
                et = int(m.group(1))
            try:
                oid = int(c["id"])
            except Exception:
                oid = 0
            return (et, oid)

        # Prefere maior etapa; empate → maior id (mais recente)
        melhor = max(candidatos, key=_rank)
        if len(candidatos) > 1:
            ids = [c["id"] for c in candidatos]
            logger.warning(
                "[VTOP] Duplicatas para '%s': %s — usando %s",
                complemento,
                ids,
                melhor["id"],
            )
            self.state.extras.setdefault("duplicatas_detectadas", []).append(
                {"complemento": complemento, "ids": ids, "escolhido": melhor["id"]}
            )
        return str(melhor["id"])

    def _passo_tentar_reusar_obra_lista(self, payload: Dict[str, Any]) -> None:
        """
        Antes de criar: se o complemento já existir no endereço, reusa o ID
        (evita duplicar obra no mesmo endereço).
        """
        complemento = str(payload.get("complemento") or payload.get("bloco_nome") or "")
        logradouro = str(payload.get("logradouro") or "")
        numero = str(payload.get("numero") or "")
        self._set(
            VtopStatus.NAVIGATING,
            f"Inventário Brownfield: '{complemento}' em {logradouro} {numero}…",
            step="localizar",
        )
        mapa = self._listar_obras_endereco(logradouro, numero)
        preferido = str(payload.get("obra_id") or "").strip()
        encontrado = self._escolher_obra_da_lista(mapa, complemento, preferido=preferido)
        if encontrado:
            payload["obra_id"] = encontrado
            self._payload_atual = dict(payload)
            self.state.extras["obra_id"] = encontrado
            self.state.extras["reusada_da_lista"] = True
            persistir_vtop_obra_bloco(
                payload.get("cdoi_id"), complemento, encontrado
            )
            self._set(
                VtopStatus.NAVIGATING,
                f"Complemento '{complemento}' já existe (id={encontrado}) — reutilizando, não cria duplicata.",
                step="localizar",
            )
            self._passo_abrir_obra_existente(encontrado)
        else:
            # Não achou o mesmo complemento → caminho criar obra nova
            total = sum(len(v) for v in mapa.values())
            if total == 0:
                raise RuntimeError(
                    "Inventário Brownfield vazio neste endereço — não é seguro criar "
                    "(não deu para validar se o complemento já existe). "
                    "Confira filtros/UF/sessão e tente de novo."
                )
            # Descarta obra_id preferido do banco: lista é a fonte da verdade
            payload.pop("obra_id", None)
            self._payload_atual = dict(payload)
            self.state.extras["reusada_da_lista"] = False
            self.state.extras.pop("obra_id", None)
            if not vtop_criar_permitido(payload):
                raise RuntimeError(
                    f"Complemento '{complemento}' não existe na lista, mas criação "
                    "está bloqueada (VTOP_BLOQUEAR_CRIAR_OBRA / VTOP_PERMITIR_CRIAR_OBRA)."
                )
            self._set(
                VtopStatus.NAVIGATING,
                f"Complemento '{complemento}' ausente na grade ({total} obras no endereço) — criando obra nova.",
                step="localizar",
            )

    def _passo_concluir_cadastro_se_preciso(self, payload: Dict[str, Any]) -> None:
        """
        Fluxo idempotente de produção:
          - se etapa >= 2: só sincroniza banco e encerra
          - senão: preenche → salva (se botão visível) → valida → relê etapa
        Falha de anexo não aborta (salvo VTOP_ANEXO_OBRIGATORIO).
        """
        assert self.page is not None
        etapa = ler_etapa_obra_page(self.page)
        obra_id = str(
            self.state.extras.get("obra_id")
            or payload.get("obra_id")
            or self._detectar_obra_id()
            or ""
        )
        self.state.extras["obra_etapa_antes"] = etapa
        if etapa is not None and etapa >= 2:
            if obra_id:
                self._gravar_vinculo_obra(obra_id, etapa=etapa)
            self._set(
                VtopStatus.DONE,
                f"Obra {obra_id} já na etapa {etapa} — nada a criar/validar.",
                step="concluir_cadastro",
            )
            return

        try:
            self._passo_cadastro(payload)
        except Exception as exc:
            if getattr(settings, "VTOP_ANEXO_OBRIGATORIO", False):
                raise
            logger.exception("[VTOP] Cadastro com falha parcial (segue salvar/validar): %s", exc)
            self.state.extras["cadastro_parcial_erro"] = str(exc)

        btn_salvar = self.page.locator("#btn_salvarEtapa")
        if btn_salvar.count() and btn_salvar.first.is_visible():
            self._passo_salvar_disquete()
        else:
            logger.warning("[VTOP] #btn_salvarEtapa invisível — pulando salvar.")

        btn_val = self.page.locator("#btn_validarEtapa")
        if btn_val.count() and btn_val.first.is_visible():
            self._passo_validar()
        else:
            logger.warning("[VTOP] #btn_validarEtapa invisível — pulando validar.")

        self.page.wait_for_timeout(1500)
        etapa_depois = ler_etapa_obra_page(self.page)
        self.state.extras["obra_etapa_apos_validar"] = etapa_depois
        if obra_id and etapa_depois is not None:
            self._gravar_vinculo_obra(obra_id, etapa=etapa_depois)
        self._set(
            VtopStatus.VALIDATING,
            f"Cadastro concluído obra={obra_id} etapa={etapa_depois}.",
            step="concluir_cadastro",
        )

    def _passo_abrir_modal_obra_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self.state.extras["criando_obra"] = True
        self._passo_abrir_modal_obra()

    def _passo_preencher_obra_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self._passo_preencher_obra(payload, salvar=False)

    def _passo_coords_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self._passo_coordenadas(payload, salvar=bool(payload.get("salvar_coords")))

    def _passo_salvar_obra_modal_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        if not vtop_criar_permitido(payload):
            raise RuntimeError(
                "Criação bloqueada por configuração "
                "(VTOP_BLOQUEAR_CRIAR_OBRA / VTOP_PERMITIR_CRIAR_OBRA)."
            )
        self.state.extras["criando_obra"] = True
        self._passo_salvar_obra_modal()

    def _passo_coords_pos_salvar_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self._passo_coords_pos_salvar(payload)

    def _passo_abrir_modal_obra(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Abrindo formulário (+)…", step="obra_modal")
        page = self.page
        candidatos = [
            page.locator("#addUmaObra"),
            page.get_by_title("Adicionar obra manualmente"),
            page.locator("button:has(i.fa-square-plus)"),
            page.locator("i.fa-square-plus.icone_obra"),
        ]
        clicado = False
        for loc in candidatos:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    clicado = True
                    break
            except Exception:
                continue
        if not clicado:
            raise RuntimeError(
                "Não encontrei o botão #addUmaObra (Adicionar obra manualmente)."
            )
        page.get_by_text("Cadastro de nova obra").wait_for(state="visible", timeout=15_000)

    def _preencher_por_label(self, label: str, valor: str) -> bool:
        """Tenta preencher input/select associado ao label. Retorna True se conseguiu."""
        assert self.page is not None
        if valor is None or str(valor) == "":
            return False
        page = self.page
        # 1) get_by_label
        try:
            campo = page.get_by_label(re.compile(re.escape(label), re.I), exact=False)
            if campo.count() > 0:
                tag = campo.first.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    campo.first.select_option(label=str(valor))
                else:
                    campo.first.fill(str(valor))
                return True
        except Exception:
            pass
        # 2) texto do label → input irmão / seguinte
        try:
            lab = page.locator(f"label:has-text('{label}')").first
            if lab.count() > 0:
                for sel in ["xpath=following::input[1]", "xpath=following::select[1]", "xpath=../input", "xpath=../select"]:
                    alvo = lab.locator(sel)
                    if alvo.count() > 0:
                        tag = alvo.first.evaluate("el => el.tagName.toLowerCase()")
                        if tag == "select":
                            try:
                                alvo.first.select_option(value=str(valor))
                            except Exception:
                                alvo.first.select_option(label=str(valor))
                        else:
                            alvo.first.fill(str(valor))
                        return True
        except Exception:
            pass
        logger.warning("[VTOP] Campo não mapeado ainda: %s", label)
        return False

    def _fill_id(self, element_id: str, valor: str) -> bool:
        assert self.page is not None
        if valor is None or str(valor) == "":
            return False
        loc = self.page.locator(f"#{element_id}")
        if loc.count() == 0:
            logger.warning("[VTOP] #%s não encontrado", element_id)
            return False
        tag = loc.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            try:
                loc.first.select_option(value=str(valor))
            except Exception:
                loc.first.select_option(label=str(valor))
            return True

        # Alguns campos do modal nascem disabled até escolher UF / tipo
        disabled = False
        try:
            disabled = bool(loc.first.is_disabled())
        except Exception:
            pass
        if disabled:
            loc.first.evaluate(
                """(el, v) => {
                    el.removeAttribute('disabled');
                    el.value = v;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                str(valor),
            )
            return True

        loc.first.fill(str(valor))
        return True

    def _passo_preencher_obra(self, payload: Dict[str, Any], *, salvar: bool = False) -> None:
        """
        Preenche o modal 'Cadastro de nova obra' pelos IDs mapeados no DOM.

        Uma obra = um bloco (complemento = nome do bloco; UMS = HPs do bloco).
        """
        self._set(VtopStatus.FILLING_OBRA, "Preenchendo Cadastro de nova obra…", step="preencher_obra")
        assert self.page is not None

        complemento = (payload.get("complemento") or payload.get("bloco_nome") or "").strip()
        ums = str(payload.get("total_hps", "") or "")
        self.state.extras["obra_bloco"] = complemento
        self.state.extras["obra_ums"] = ums

        # UF primeiro — libera/condiciona LOCALIDADE e demais
        mapa = [
            ("sel_uf_obra", payload.get("uf", "")),
            ("input_cod_survey", payload.get("cod_survey", "")),
            ("input_localidade_abrev", payload.get("cidade", "")),
            ("input_estacao_abastecedora", payload.get("estacao", "")),
            ("input_logradouro", payload.get("logradouro", "")),
            ("input_num_fachada", payload.get("numero", "")),
            ("input_bairro", payload.get("bairro", "")),
            ("input_complemento", complemento),
            ("input_celula", payload.get("celula", "")),
            ("input_nome_cdo", payload.get("cdoi_codigo", "")),
            ("input_quantidade_ums", ums),
        ]
        ok: List[str] = []
        for eid, valor in mapa:
            if eid == "sel_uf_obra" and valor:
                if self._fill_id(eid, str(valor)):
                    ok.append(eid)
                    self.page.wait_for_timeout(800)
                continue
            if self._fill_id(eid, str(valor) if valor is not None else ""):
                ok.append(eid)
        self.state.extras["obra_campos_ok"] = ok
        self._set(
            VtopStatus.FILLING_OBRA,
            f"Obra '{complemento}' UMS={ums} ({len(ok)} campos). Salvar={'sim' if salvar else 'não'}.",
            step="preencher_obra",
        )
        if salvar:
            self._passo_salvar_obra_modal()

    def _passo_salvar_obra_modal(self) -> None:
        """
        Cria a obra (#b_criar_obra). No success o JS chama mostrarObra()
        e abre obra.jsp em nova aba (target=_blank).
        """
        assert self.page is not None
        assert self.context is not None
        self._set(VtopStatus.SAVING, "Clicando Salvar no modal da obra (#b_criar_obra)…", step="salvar_obra")
        page = self.page

        def _aceitar(dialog) -> None:
            logger.info("[VTOP] Dialog ao salvar obra: %s", dialog.message)
            dialog.accept()

        page.once("dialog", _aceitar)
        btn = page.locator("#b_criar_obra")
        popup = None
        try:
            with page.expect_popup(timeout=45_000) as popup_info:
                if btn.count() == 0:
                    page.get_by_role("button", name=re.compile(r"Salvar", re.I)).click()
                else:
                    btn.first.click()
            popup = popup_info.value
        except Exception:
            logger.warning("[VTOP] Popup obra.jsp não surgiu — tentando fallbacks.")
            if btn.count():
                try:
                    btn.first.click(timeout=2000)
                except Exception:
                    pass

        if popup is not None:
            popup.wait_for_load_state("domcontentloaded")
            self.page = popup
            page = self.page
            logger.info("[VTOP] Trocou para aba da obra: %s", page.url)

        obra_id = self._detectar_obra_id()
        if obra_id:
            self.state.extras["obra_id"] = obra_id
            self._gravar_vinculo_obra(obra_id)

        try:
            page.locator("#btn_salvarEtapa").wait_for(state="visible", timeout=45_000)
        except Exception:
            try:
                page.get_by_text(re.compile(r"NOME DO CONDOM", re.I)).first.wait_for(
                    state="visible", timeout=15_000
                )
            except Exception:
                logger.warning("[VTOP] Tela de cadastro pós-salvar não detectada. URL=%s", page.url)

        page.wait_for_timeout(1000)
        self.state.extras["url_apos_salvar_obra"] = page.url
        self._set(
            VtopStatus.SAVING,
            f"Obra salva (id={obra_id or '?'}). URL={page.url}",
            step="salvar_obra",
        )

    def _gravar_vinculo_obra(self, obra_id: str, etapa: Optional[int] = None) -> None:
        """Persiste obra_id/etapa no CdoiBloco do payload atual."""
        payload = self._payload_atual or {}
        nome = (
            payload.get("complemento")
            or payload.get("bloco_nome")
            or self.state.extras.get("obra_bloco")
            or ""
        )
        persistir_vtop_obra_bloco(
            payload.get("cdoi_id"),
            str(nome),
            str(obra_id),
            etapa=etapa,
        )

    def _detectar_obra_id(self) -> str:
        assert self.page is not None
        page = self.page
        for sel in ("input[name='id']", "input#id", "input[name='id_obra']"):
            loc = page.locator(sel)
            if loc.count() > 0:
                val = (loc.first.input_value() or "").strip()
                if val.isdigit():
                    return val
        m = re.search(r"edit_(\d+)_\d+_", page.content()[:200_000])
        if m:
            return m.group(1)
        m = re.search(r"[?&]id=(\d+)", page.url)
        if m:
            return m.group(1)
        return ""

    def _passo_abrir_obra_existente(self, obra_id: str) -> None:
        """Abre obra.jsp?id=… (GET funciona no SmartRiser atual)."""
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, f"Abrindo obra existente {obra_id}…", step="abrir_obra")
        url = f"{VTOP_SMARTRISER_URL}obra.jsp?id={obra_id}"
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.locator("#btn_salvarEtapa").wait_for(state="attached", timeout=60_000)
        # pesquisaCheckList preenche .item_checklist via AJAX
        self.page.locator(".item_checklist").first.wait_for(state="visible", timeout=60_000)
        self.page.wait_for_timeout(800)
        self.state.extras["obra_id"] = str(obra_id)
        self.state.extras["url_obra"] = self.page.url
        self._gravar_vinculo_obra(str(obra_id))
        self._set(VtopStatus.NAVIGATING, f"Obra {obra_id} aberta.", step="abrir_obra")

    def _passo_coords_pos_salvar(self, payload: Dict[str, Any]) -> None:
        """Só reabre mapa após salvar obra se as coords não foram gravadas no modal."""
        if payload.get("salvar_coords"):
            self._set(
                VtopStatus.FILLING_COORDS,
                "Coords já gravadas no modal — pulando coords pós-salvar.",
                step="coords_pos_salvar",
            )
            return
        self._passo_coordenadas(payload, salvar=True)

    def _abrir_modal_coordenadas(self) -> bool:
        """Abre o mapa clicando em img/icon_map.png (onclick=abrirMapa...)."""
        assert self.page is not None
        page = self.page
        # Já aberto?
        if page.locator("text=Latitude").count() > 0 or page.get_by_text(re.compile(r"^Latitude", re.I)).count() > 0:
            try:
                if page.get_by_text(re.compile(r"Latitude\s*:", re.I)).first.is_visible():
                    return True
            except Exception:
                pass

        # Seletor real mapeado no DevTools (ago/2026):
        # <th id="lat_long">...<a onclick="abrirMapa(-1,0,0,0,0)"><img src="img/icon_map.png"></a>
        candidatos = [
            page.locator('#lat_long a[onclick*="abrirMapa"]'),
            page.locator('#lat_long img[src*="icon_map.png"]'),
            page.locator('a[onclick*="abrirMapa"] img[src*="icon_map.png"]'),
            page.locator('img[src="img/icon_map.png"]'),
            page.locator('img[src*="icon_map.png"]'),
            page.locator('a[onclick*="abrirMapa"]'),
        ]
        for loc in candidatos:
            try:
                if loc.count() == 0:
                    continue
                alvo = loc.first
                if not alvo.is_visible():
                    continue
                alvo.click()
                page.wait_for_timeout(1200)
                if page.get_by_text(re.compile(r"Latitude", re.I)).count() > 0:
                    return True
            except Exception:
                continue

        # Fallback: chamar a função JS diretamente no contexto da página
        try:
            page.evaluate("() => { if (typeof abrirMapa === 'function') abrirMapa(-1,0,0,0,0); }")
            page.wait_for_timeout(1200)
            if page.get_by_text(re.compile(r"Latitude", re.I)).count() > 0:
                return True
        except Exception:
            pass
        return False

    def _preencher_inputs_coordenadas(self, lat: str, lng: str) -> bool:
        """Preenche #edit_lat e #edit_lon no modal do mapa."""
        assert self.page is not None
        page = self.page
        ok = False

        # IDs reais mapeados no DevTools (ago/2026)
        if page.locator("#edit_lat").count() > 0:
            page.locator("#edit_lat").fill(lat)
            ok = True
        if page.locator("#edit_lon").count() > 0:
            page.locator("#edit_lon").fill(lng)
            ok = True
        if ok:
            return True

        # Fallbacks
        for label, valor in (("Latitude", lat), ("Longitude", lng)):
            if self._preencher_por_label(label, valor):
                ok = True
        return ok

    def _passo_coordenadas(self, payload: Dict[str, Any], *, salvar: bool = False) -> None:
        lat = (payload.get("latitude") or "").strip()
        lng = (payload.get("longitude") or "").strip()
        if not lat or not lng:
            self._set(
                VtopStatus.FILLING_COORDS,
                "Lat/Long ausentes no payload — pulando coordenadas.",
                step="coords",
            )
            return

        assert self.page is not None
        self._set(
            VtopStatus.FILLING_COORDS,
            "Clicando icon_map.png e preenchendo lat/long…",
            step="coords",
        )
        aberto = self._abrir_modal_coordenadas()
        if not aberto:
            self._set(
                VtopStatus.FILLING_COORDS,
                "Não abriu o modal do mapa (icon_map.png / abrirMapa).",
                step="coords",
            )
            self.state.extras["coords_abertas"] = False
            return

        self.state.extras["coords_abertas"] = True
        page = self.page
        page.locator("#edit_lat").wait_for(state="visible", timeout=10_000)
        page.locator("#edit_lon").wait_for(state="visible", timeout=10_000)
        page.locator("#edit_lat").fill("")
        page.locator("#edit_lon").fill("")
        page.locator("#edit_lat").fill(lat)
        page.locator("#edit_lon").fill(lng)
        vlat = page.locator("#edit_lat").input_value()
        vlon = page.locator("#edit_lon").input_value()
        self.state.extras["coords_valores"] = {"lat": vlat, "lon": vlon}
        logger.info("[VTOP] Coords nos inputs: lat=%s lon=%s", vlat, vlon)

        # Procurar = setCoordenada() (ajax + reposiciona infoWindow)
        try:
            with page.expect_response(lambda r: "validalatlon" in (r.url or ""), timeout=15_000):
                page.locator("#b_map_procurar").click()
        except Exception:
            page.locator("#b_map_procurar").click()
        page.wait_for_timeout(2000)

        if not salvar:
            self.state.extras["coords_preenchidas"] = True
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Coords preenchidas ({lat}, {lng}) + Procurar — NÃO salvou o mapa.",
                step="coords",
            )
            return

        # Playwright descarta dialogs por padrão; preferir handler do context do script.
        def _aceitar_confirm(dialog) -> None:
            try:
                logger.info("[VTOP] Confirm mapa: %s", dialog.message)
                dialog.accept()
            except Exception as exc:
                logger.warning("[VTOP] Dialog mapa já tratado: %s", exc)

        if not getattr(self, "_dialog_via_context", False):
            page.once("dialog", _aceitar_confirm)
        page.locator("#b_salvar_coord").click()
        page.wait_for_timeout(1500)

        depois = page.evaluate(
            """() => ({
              span_lat: (document.querySelector('#span_lat')||{}).innerText || '',
              span_lon: (document.querySelector('#span_lon')||{}).innerText || '',
              input_lat: (document.querySelector('#input_lat')||{}).value || '',
              input_lon: (document.querySelector('#input_lon')||{}).value || '',
            })"""
        )
        self.state.extras["coords_apos_salvar"] = depois
        gravou = lat[:8] in str(depois.get("span_lat") or "") or lat[:8] in str(
            depois.get("input_lat") or ""
        )
        self.state.extras["coords_preenchidas"] = gravou

        if gravou:
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Coords salvas: {depois.get('span_lat')},{depois.get('span_lon')}",
                step="coords",
            )
            return

        # Bypass do confirm: grava direto nos campos (mesma lógica do OK do confirm)
        logger.warning("[VTOP] Confirm/salvar não gravou (%s) — gravando direto nos spans", depois)
        page.evaluate(
            """([lat, lon]) => {
              const latN = parseFloat(lat);
              const lonN = parseFloat(lon);
              const spanLat = document.querySelector('#span_lat');
              const spanLon = document.querySelector('#span_lon');
              const inputLat = document.querySelector('#input_lat');
              const inputLon = document.querySelector('#input_lon');
              if (spanLat) spanLat.innerHTML = latN.toFixed(7);
              if (spanLon) spanLon.innerHTML = lonN.toFixed(7);
              if (inputLat) inputLat.value = String(latN);
              if (inputLon) inputLon.value = String(lonN);
              const popup = document.querySelector('#popup_map');
              if (popup && window.jQuery) { window.jQuery(popup).fadeOut('fast'); }
              else if (popup) { popup.style.display = 'none'; }
            }""",
            [lat, lng],
        )
        page.wait_for_timeout(800)
        depois2 = page.evaluate(
            """() => ({
              span_lat: (document.querySelector('#span_lat')||{}).innerText || '',
              span_lon: (document.querySelector('#span_lon')||{}).innerText || '',
              input_lat: (document.querySelector('#input_lat')||{}).value || '',
              input_lon: (document.querySelector('#input_lon')||{}).value || '',
            })"""
        )
        self.state.extras["coords_apos_fallback"] = depois2
        gravou2 = lat[:8] in str(depois2.get("span_lat") or "") or lat[:8] in str(
            depois2.get("input_lat") or ""
        )
        self.state.extras["coords_preenchidas"] = gravou2
        if gravou2:
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Coords gravadas (fallback): {depois2.get('span_lat')},{depois2.get('span_lon')}",
                step="coords",
            )
        else:
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Falha ao gravar coords ({depois2}).",
                step="coords",
                error="coords_not_saved",
            )

    def _dump_campos_visiveis(self, outfile: str) -> List[Dict[str, Any]]:
        assert self.page is not None
        data = self.page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll('input, select, textarea, button, a, img'));
              return nodes.map(el => {
                const r = el.getBoundingClientRect();
                const cs = getComputedStyle(el);
                const visible = !!(r.width && r.height && cs.visibility !== 'hidden' && cs.display !== 'none');
                if (!visible && el.type !== 'file' && el.type !== 'hidden') return null;
                let label = '';
                if (el.id) {
                  const l = document.querySelector(`label[for="${el.id}"]`);
                  if (l) label = (l.innerText || '').trim();
                }
                if (!label) {
                  const row = el.closest('tr, .form-group, div');
                  if (row) label = (row.innerText || '').trim().split('\\n')[0].slice(0, 120);
                }
                return {
                  tag: el.tagName,
                  type: el.type || '',
                  id: el.id || '',
                  name: el.name || '',
                  value: (el.value || '').toString().slice(0, 80),
                  placeholder: el.placeholder || '',
                  title: el.title || '',
                  alt: el.alt || '',
                  src: (el.getAttribute('src') || '').slice(0, 120),
                  onclick: (el.getAttribute('onclick') || '').slice(0, 120),
                  label,
                  visible,
                  disabled: !!el.disabled,
                  options: el.tagName === 'SELECT'
                    ? Array.from(el.options).slice(0, 30).map(o => ({v: o.value, t: o.text}))
                    : undefined,
                };
              }).filter(Boolean);
            }"""
        )
        path = Path(settings.BASE_DIR) / outfile
        path.write_text(
            json.dumps({"url": self.page.url, "fields": data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[VTOP] Dump de campos: %s (%s itens)", path, len(data))
        self.state.extras["dom_dump"] = str(path)
        return data

    def _dump_checklist_cadastro(self, outfile: str = "tmp_vtop_dom_cadastro_obra.json") -> Dict[str, Any]:
        """Dump estruturado dos itens do checklist (rótulo + inputs)."""
        assert self.page is not None
        data = self.page.evaluate(
            """() => {
              const out = {url: location.href, header: {}, itens: []};
              ['cod_survey','uf','localidade_abrev','estacao_abastecedora','meta',
               'logradouro','num_fachada','bairro','complemento','celula','nome_cdo',
               'quantidade_ums'].forEach(id => {
                const el = document.getElementById(id);
                if (el) out.header[id] = (el.innerText || el.textContent || '').trim();
              });
              document.querySelectorAll('.item_checklist').forEach((div, idx) => {
                const labelEl = div.querySelector('table td');
                const label = labelEl ? (labelEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                const inputs = Array.from(div.querySelectorAll('input,select,textarea')).map(el => ({
                  id: el.id || '', type: el.type || el.tagName, value: (el.value || '').toString().slice(0, 120),
                  options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.value) : undefined,
                }));
                out.itens.push({idx, label, inputs});
              });
              return out;
            }"""
        )
        path = Path(settings.BASE_DIR) / outfile
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.state.extras["dom_dump"] = str(path)
        return data

    def _passo_cadastro(self, payload: Dict[str, Any]) -> None:
        assert self.page is not None
        self._set(VtopStatus.FILLING_CADASTRO, "Preenchendo aba Cadastro…", step="cadastro")
        page = self.page
        page.locator("#btn_salvarEtapa").wait_for(state="attached", timeout=45_000)
        page.locator(".item_checklist").first.wait_for(state="visible", timeout=45_000)
        page.wait_for_timeout(500)

        dump = self._dump_checklist_cadastro("tmp_vtop_dom_cadastro_obra.json")
        obra_id = self._detectar_obra_id() or str(payload.get("obra_id") or "")
        self.state.extras["obra_id"] = obra_id

        bloco = payload.get("bloco_nome") or payload.get("complemento") or ""
        andares = int(payload.get("andares") or 0)
        aptos = int(payload.get("aptos") or 0)
        ums = int(payload.get("total_hps") or 0)
        # Se a obra já existe, prioriza QUANTIDADE UMS do header (pode diferir do CDOI)
        try:
            ums_header = (page.locator("#quantidade_ums").inner_text(timeout=2000) or "").strip()
            if ums_header.isdigit() and int(ums_header) > 0:
                ums = int(ums_header)
                self.state.extras["ums_obra"] = ums
        except Exception:
            pass
        prev_bloco = calcular_pre_venda_bloco(ums)
        if payload.get("pre_venda_forcada") is not None:
            prev_bloco = int(payload["pre_venda_forcada"])
        caract = (payload.get("caracteristicas") or "").strip() or (
            f"{bloco}: {andares} andares, {aptos} ums/andar ({ums} HPs)"
        )
        # Recalcula texto se UMS da obra diferir do payload
        if ums and str(ums) not in caract:
            caract = f"{bloco}: {andares} andares × {aptos} ums/andar ({ums} HPs)" if andares and aptos else (
                f"{bloco}: {ums} HPs"
            )

        id_valores: Dict[str, str] = {}
        if obra_id:
            id_valores[f"edit_{obra_id}_1_2"] = str(payload.get("nome_condominio") or "")
            id_valores[f"edit_{obra_id}_1_3"] = str(payload.get("nome_sindico") or "")
            id_valores[f"edit_{obra_id}_1_4"] = str(payload.get("contato") or "")
            id_valores[f"edit_{obra_id}_1_6"] = str(payload.get("codigo_sap") or CODIGO_SAP_PADRAO)
            id_valores[f"edit_{obra_id}_1_8"] = caract

        id_valores["input_blocos"] = "1"
        id_valores["input_andares"] = str(andares)
        id_valores["input_total_hps"] = str(ums)
        id_valores["input_prevenda"] = str(prev_bloco)

        for item in dump.get("itens") or []:
            label_u = (item.get("label") or "").upper()
            inputs = item.get("inputs") or []
            edit_ids = [i["id"] for i in inputs if str(i.get("id", "")).startswith("edit_")]
            if not edit_ids:
                continue
            eid = edit_ids[0]
            # CARTA / FOTOS ficam vazios aqui (anexo via fa-square-plus → addDocFoto)
            if "CARTA" in label_u or "AUTORIZA" in label_u or "FOTO" in label_u or "FAIXADA" in label_u or "FACHADA" in label_u:
                continue
            if "NOME DO CONDOM" in label_u and "SIND" not in label_u:
                id_valores[eid] = str(payload.get("nome_condominio") or "")
            elif ("NOME DO SINDICO" in label_u or "NOME DO SÍNDICO" in label_u) and "CONTATO" not in label_u:
                id_valores[eid] = str(payload.get("nome_sindico") or "")
            elif "CONTATO" in label_u:
                id_valores[eid] = str(payload.get("contato") or "")
            elif "PARCEIRO" in label_u or "SAP" in label_u:
                id_valores[eid] = str(payload.get("codigo_sap") or CODIGO_SAP_PADRAO)
            elif "CARACTER" in label_u or "QUANTIDADE DE BLOCOS" in label_u:
                id_valores[eid] = caract

        preenchidos: List[str] = []
        for eid, valor in id_valores.items():
            if valor is None or valor == "":
                continue
            if self._fill_id(eid, str(valor)):
                preenchidos.append(f"{eid}={valor}")

        mapa_path = Path(settings.BASE_DIR) / "tmp_vtop_mapa_etapa_cadastro.json"
        mapa_path.write_text(
            json.dumps(
                {
                    "obra_id": obra_id,
                    "header": dump.get("header"),
                    "itens": dump.get("itens"),
                    "valores_enviados": id_valores,
                    "preenchidos": preenchidos,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.state.extras["cadastro_campos_ok"] = preenchidos
        self.state.extras["cadastro_mapa"] = str(mapa_path)

        if payload.get("anexar_arquivos") or payload.get("com_anexos"):
            self._set(VtopStatus.UPLOADING, "Tentando anexar carta/fachada…", step="upload")
            try:
                self._anexar_se_possivel(
                    "CARTA DE AUTORIZAÇÃO",
                    payload.get("link_carta") or "",
                    "carta_",
                    info="Carta sindico",
                )
                self._anexar_se_possivel(
                    "FOTOS DA FAIXADA",
                    payload.get("link_fachada") or "",
                    "fachada_",
                    info="Foto fachada",
                )
            except Exception as exc:
                logger.exception("[VTOP] Falha em anexos (não aborta): %s", exc)
                self.state.extras.setdefault("anexos_falha", []).append(str(exc))
                if getattr(settings, "VTOP_ANEXO_OBRIGATORIO", False):
                    raise

        self._set(
            VtopStatus.FILLING_CADASTRO,
            f"Cadastro preenchido ({len(preenchidos)} campos) obra={obra_id}.",
            step="cadastro",
        )

    def _anexar_se_possivel(self, label_hint: str, url: str, prefix: str, info: str = "") -> bool:
        """
        Anexa via popup addDocFoto:
          ícone fa-square-plus → #doc_foto_item + #informacoes + #btn_sub_foto → POST AddDocFoto
        """
        assert self.page is not None
        page = self.page
        if not url:
            logger.warning("[VTOP] Sem URL para anexar (%s)", label_hint)
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:url_vazia")
            return False

        path = baixar_anexo_temporario(url, prefix=prefix)
        if not path:
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:download_falhou")
            return False
        # Portal rejeita NOT_IMAGE; jfif → jpg (só marca temp se for conversão/download)
        path_orig = path
        path = self._garantir_imagem_jpg(path)
        if path != path_orig and not os.path.isfile(url) and not str(url).lower().startswith("file:"):
            # path_orig era download temp
            self._temp_files.append(path_orig)
        elif path == path_orig and not os.path.isfile(url) and not str(url).lower().startswith("file:"):
            self._temp_files.append(path)

        hint_u = label_hint.upper()
        candidatos = page.locator(".item_checklist")
        alvo = None
        for i in range(candidatos.count()):
            txt = (candidatos.nth(i).inner_text() or "").upper()
            # Match por palavra-chave do tipo de anexo (acentos/encoding variáveis no DOM)
            if "CARTA" in hint_u:
                if "CARTA" in txt and "AUTORIZA" in txt:
                    alvo = candidatos.nth(i)
                    break
            elif "FOTO" in hint_u or "FAI" in hint_u or "FACHADA" in hint_u:
                if "FOTO" in txt and ("FAI" in txt or "FACHADA" in txt):
                    alvo = candidatos.nth(i)
                    break
            elif hint_u[:12] in txt:
                alvo = candidatos.nth(i)
                break
        if alvo is None:
            logger.warning("[VTOP] Item checklist não encontrado: %s", label_hint)
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:item_nao_encontrado")
            return False

        plus = alvo.locator("i.fa-square-plus[onclick*='addDocFoto'], i[onclick*='addDocFoto']")
        if plus.count() == 0:
            plus = alvo.locator("i.fa-square-plus")
        if plus.count() == 0:
            logger.warning("[VTOP] Ícone addDocFoto não encontrado em: %s", label_hint)
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:icone_nao_encontrado")
            return False

        # Já tem arquivo vinculado? Não reenvia (evita duplicar carta/fachada).
        ja_tem = alvo.evaluate(
            """(el) => {
              if (el.querySelector('img[src*="doc"], img[src*="foto"], img.thumb, a[href*="Download"], a[href*="download"]'))
                return true;
              if (el.querySelector('i.fa-file, i.fa-file-image, i.fa-paperclip, i.fa-image'))
                return true;
              const txt = (el.innerText || '').toUpperCase();
              if (txt.includes('.JPG') || txt.includes('.JPEG') || txt.includes('.PNG') ||
                  txt.includes('.JFIF') || txt.includes('.PDF') || txt.includes('CARTA_') ||
                  txt.includes('FACHADA_'))
                return true;
              // contador visual comum: vários ícones de lixeira (remove doc) = já anexado
              if (el.querySelectorAll('i.fa-trash, i.fa-times, [onclick*="removeDoc"], [onclick*="RemoveDoc"]').length > 0)
                return true;
              return false;
            }"""
        )
        if ja_tem:
            logger.info("[VTOP] Anexo já presente — pulando upload (%s)", label_hint)
            self.state.extras.setdefault("anexos_pulados", []).append(label_hint)
            return True

        def _aceitar(dialog) -> None:
            try:
                logger.info("[VTOP] Dialog anexo: %s", dialog.message)
                dialog.accept()
            except Exception as exc:
                logger.warning("[VTOP] Dialog anexo já tratado: %s", exc)

        page.once("dialog", _aceitar)
        try:
            plus.first.click()
            page.locator("#doc_foto_item").wait_for(state="visible", timeout=10_000)
        except Exception as exc:
            logger.warning(
                "[VTOP] Popup de anexo não abriu (%s) — pulando upload: %s",
                label_hint,
                exc,
            )
            self.state.extras.setdefault("anexos_pulados", []).append(f"{label_hint}:popup")
            # tenta fechar lixo do popup
            try:
                if page.locator("#popup_foto").count() and page.locator("#popup_foto").is_visible():
                    page.locator("#b_cancelarNovaEstacao").click(timeout=2000)
            except Exception:
                pass
            return False

        page.locator("#doc_foto_item").set_input_files(path)
        legenda = (info or prefix.rstrip("_") or "anexo")[:30]
        page.locator("#informacoes").fill(legenda)
        btn_sub = page.locator("#btn_sub_foto")
        try:
            btn_sub.click(force=True, timeout=15_000)
        except Exception:
            # Popup do SmartRiser às vezes trava o click nativo
            page.evaluate(
                """() => {
                  const b = document.getElementById('btn_sub_foto');
                  if (b) b.click();
                }"""
            )
        page.wait_for_timeout(2500)
        # fecha popup se ainda aberto
        if page.locator("#popup_foto").count() and page.locator("#popup_foto").is_visible():
            try:
                page.locator("#b_cancelarNovaEstacao").click(timeout=2000)
            except Exception:
                pass
        logger.info("[VTOP] Anexo enviado (%s): %s", label_hint, path)
        self.state.extras.setdefault("anexos_ok", []).append(label_hint)
        return True

    def _garantir_imagem_jpg(self, path: str) -> str:
        """Converte jfif/webp/etc. para .jpg temporário quando necessário."""
        p = Path(path)
        suf = p.suffix.lower()
        if suf in {".jpg", ".jpeg", ".png", ".bmp"}:
            return path
        try:
            from PIL import Image

            img = Image.open(path)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            fd, out = tempfile.mkstemp(prefix="vtop_img_", suffix=".jpg")
            os.close(fd)
            img.save(out, format="JPEG", quality=90)
            self._temp_files.append(out)
            logger.info("[VTOP] Convertido anexo %s → %s", path, out)
            return out
        except Exception:
            logger.exception("[VTOP] Falha ao converter imagem %s", path)
            return path

    def _aceitar_dialogs(self) -> None:
        """Handler permanente: aceita confirms (mapa/validar) sem erro se já tratado."""
        assert self.page is not None
        if getattr(self, "_dialog_handler_installed", False):
            return

        def _on_dialog(dialog) -> None:
            try:
                logger.info("[VTOP] Dialog: %s", dialog.message)
                dialog.accept()
            except Exception as exc:
                logger.warning("[VTOP] Dialog já tratado/ignorado: %s", exc)

        self.page.on("dialog", _on_dialog)
        self._dialog_handler_installed = True

    def _passo_salvar_disquete(self) -> None:
        """Salva a etapa atual via #btn_salvarEtapa → salvarEtapa(..., false)."""
        assert self.page is not None
        self._set(VtopStatus.SAVING, "Salvando etapa Cadastro (#btn_salvarEtapa)…", step="salvar")
        page = self.page
        self._aceitar_dialogs()
        btn = page.locator("#btn_salvarEtapa")
        if btn.count() == 0:
            raise RuntimeError("#btn_salvarEtapa não encontrado.")
        if not btn.first.is_visible():
            logger.warning("[VTOP] #btn_salvarEtapa não visível; tentando clique mesmo assim.")
        btn.first.click(force=True)
        try:
            page.wait_for_function(
                """() => {
                  const el = document.querySelector('#carregando, .carregando, #atualizando');
                  if (!el) return true;
                  const cs = getComputedStyle(el);
                  return cs.display === 'none' || cs.visibility === 'hidden' || el.offsetParent === null;
                }""",
                timeout=30_000,
            )
        except Exception:
            page.wait_for_timeout(2500)
        page.wait_for_timeout(1000)
        self._set(VtopStatus.SAVING, "Etapa Cadastro salva.", step="salvar")

    def _passo_validar(self) -> None:
        """Valida etapa e avança (#btn_validarEtapa → confirm + salvarEtapa valida=true)."""
        assert self.page is not None
        self._set(VtopStatus.VALIDATING, "Validando etapa Cadastro…", step="validar")
        page = self.page
        self._aceitar_dialogs()
        btn = page.locator("#btn_validarEtapa")
        if btn.count() == 0:
            raise RuntimeError("#btn_validarEtapa não encontrado.")
        btn.first.click(force=True)
        page.wait_for_timeout(4000)
        etapa = ler_etapa_obra_page(page)
        self.state.extras["obra_etapa_apos_validar"] = etapa
        obra_id = str(self.state.extras.get("obra_id") or self._detectar_obra_id() or "")
        if obra_id and etapa is not None:
            self._gravar_vinculo_obra(obra_id, etapa=etapa)
        self._set(VtopStatus.VALIDATING, f"Etapa validada (obra.etapa={etapa}).", step="validar")


# Instância de processo (1 browser V.top por worker Django/local)
_service_lock = threading.Lock()
_service: Optional[VtopSmartRiserService] = None


def get_vtop_service() -> VtopSmartRiserService:
    global _service
    with _service_lock:
        if _service is None:
            _service = VtopSmartRiserService()
        return _service
