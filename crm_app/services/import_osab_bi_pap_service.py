"""
Exporta a grade «Exportação - OSAB» do Power BI (aba Dinâmica - OSAB) no portal PAP
e dispara a importação OSAB do CRM (Central de Importações).

Conta: CredencialRoboPAP com função IMPORT_OSAB_BI.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

FUNCAO_ROBO = "IMPORT_OSAB_BI"
PAP_DASHBOARD_URL = "https://pap.niointernet.com.br/administrativo/dashboard"


@dataclass
class ResultadoImportOsabBi:
    ok: bool
    detail: str
    matricula: str = ""
    arquivo: str = ""
    bytes_arquivo: int = 0
    log_id: Optional[int] = None
    log_status: str = ""


def _obter_robo(*, matricula: str = "") -> Any:
    from usuarios.models import CredencialRoboPAP

    qs = CredencialRoboPAP.objects.filter(funcao=FUNCAO_ROBO, ativo=True)
    if matricula:
        qs = qs.filter(matricula__iexact=matricula.strip())
    robo = qs.order_by("id").first()
    if not robo:
        raise ValueError(
            "Nenhuma conta Contas de Serviço PAP com função "
            "«Importação OSAB (BI Dinâmica)» ativa. Cadastre em Governança."
        )
    return robo


def _trancar_robo(robo) -> bool:
    from usuarios.models import CredencialRoboPAP

    with transaction.atomic():
        locked = (
            CredencialRoboPAP.objects.select_for_update()
            .filter(pk=robo.pk, ativo=True)
            .first()
        )
        if not locked:
            return False
        if locked.em_uso:
            logger.warning(
                "[OSAB BI] Conta %s já em uso (ultimo_uso=%s).",
                locked.matricula,
                locked.ultimo_uso,
            )
            return False
        locked.em_uso = True
        locked.ultimo_uso = timezone.now()
        locked.save(update_fields=["em_uso", "ultimo_uso"])
    return True


def _liberar_robo(robo_id: int) -> None:
    from usuarios.models import CredencialRoboPAP

    CredencialRoboPAP.objects.filter(pk=robo_id, em_uso=True).update(
        em_uso=False, ultimo_uso=timezone.now()
    )


_IFRAME_BI = 'iframe[src*="powerbi.com"], iframe[src*="app.powerbi.com"]'
_PAT_PAGINA_OSAB = re.compile(
    r"Din[aá]mica\s*[-–—]\s*OSAB|Exporta[cç][aã]o\s*[-–—]\s*OSAB",
    re.I,
)
_PAT_NAV_OSAB = re.compile(
    r"Din[aá]mica.*OSAB|OSAB.*Din[aá]mica|Din[aá]mica\s*Exporta",
    re.I,
)


def _sair_tela_cheia(page) -> None:
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    for sel in (
        'button:has-text("Sair do modo tela cheia")',
        'button:has-text("Fechar modo tela cheia")',
        'button[aria-label*="tela cheia" i]',
    ):
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=2000)
                page.wait_for_timeout(300)
        except Exception:
            continue


def _texto_visivel_bi(frame, limite: int = 800) -> str:
    try:
        txt = frame.locator("body").inner_text(timeout=5000) or ""
        return re.sub(r"\s+", " ", txt).strip()[:limite]
    except Exception:
        return ""


def _ja_na_pagina_osab(frame) -> bool:
    """True se a grade OSAB (ou sinais claros da página Dinâmica OSAB) estão visíveis."""
    sinais = (
        r"Exporta[cç][aã]o\s*[-–—]\s*OSAB",
        r"Agendamento Futuro",
        r"NR\s*ORDEM",
        r"DATA HORA\s*[-–—]\s*ATUALIZA",
    )
    try:
        for pat in sinais:
            el = frame.get_by_text(re.compile(pat, re.I)).first
            if el.count() and el.is_visible():
                # Evita falso positivo em outras páginas: exige Exportação OU (Agendamento+OSAB no texto)
                if re.search(r"Exporta[cç][aã]o\s*[-–—]\s*OSAB", pat, re.I):
                    return True
        txt = _texto_visivel_bi(frame, 1200)
        if re.search(r"Exporta[cç][aã]o\s*[-–—]\s*OSAB", txt, re.I):
            return True
        if re.search(r"Din[aá]mica\s*[-–—]\s*OSAB", txt, re.I) and re.search(
            r"Agendamento Futuro|NR\s*ORDEM|REDE", txt, re.I
        ):
            return True
    except Exception:
        return False
    return False


def _aguardar_grade_osab(frame, page, timeout_ms: int = 45000) -> bool:
    fim = time.time() + (timeout_ms / 1000.0)
    while time.time() < fim:
        if _ja_na_pagina_osab(frame):
            return True
        page.wait_for_timeout(1000)
    return _ja_na_pagina_osab(frame)


def _listar_frames_bi(page):
    n = page.locator(_IFRAME_BI).count()
    return [page.frame_locator(_IFRAME_BI).nth(i) for i in range(n)]


def _aguardar_qualquer_bi(page, timeout_ms: int = 90000) -> None:
    fim = time.time() + (timeout_ms / 1000.0)
    while time.time() < fim:
        for frame in _listar_frames_bi(page):
            amostra = _texto_visivel_bi(frame, 200)
            if amostra and len(amostra) > 40:
                logger.info("[OSAB BI] Embed com conteúdo detectado.")
                return
        page.wait_for_timeout(1500)
    logger.warning("[OSAB BI] Timeout aguardando conteúdo nos iframes Power BI.")


def _abrir_menu_paginas_extra(frame, page) -> None:
    """Abre o overflow «…» da barra de páginas do Power BI, se existir."""
    for sel in (
        'button[aria-label*="mais páginas" i]',
        'button[aria-label*="More pages" i]',
        'button[aria-label*="páginas do relatório" i]',
        'button[aria-label*="Report pages" i]',
        'button[title*="mais" i]',
        '.explorationNavigation button.more',
        'button:has-text("…")',
        'button:has-text("...")',
    ):
        try:
            btn = frame.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=3000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue


def _clicar_navegacao_por_texto(frame, page, padrao: re.Pattern) -> bool:
    locs = [
        frame.get_by_role("tab", name=padrao),
        frame.get_by_role("button", name=padrao),
        frame.get_by_role("menuitem", name=padrao),
        frame.get_by_text(padrao),
        frame.locator(
            '.explorationNavigation button, .sectionList button, '
            '[class*="pageNavigation"] button, [class*="page-navigation"] button, '
            '[class*="navigation"] button, div[role="tab"], span[role="tab"], '
            'li[role="option"], div[role="option"]'
        ).filter(has_text=padrao),
    ]
    for loc in locs:
        try:
            el = loc.first
            if el.count() == 0:
                continue
            el.scroll_into_view_if_needed(timeout=4000)
            el.click(timeout=6000, force=True)
            page.wait_for_timeout(2200)
            return True
        except Exception:
            continue
    return False


def _varrer_paginas_bi(frame, page, max_cliques: int = 16) -> bool:
    """
    Percorre a barra de páginas do relatório até achar Exportação - OSAB.
    O embed às vezes abre em «Visão Parceiro», não em Dinâmica.
    """
    if _ja_na_pagina_osab(frame):
        return True

    _abrir_menu_paginas_extra(frame, page)
    if _clicar_navegacao_por_texto(frame, page, _PAT_NAV_OSAB):
        page.wait_for_timeout(2000)
        if _aguardar_grade_osab(frame, page, timeout_ms=60000):
            return True
        # Mesmo sem título Exportação, se o nav era Dinâmica - OSAB, fica nesta página
        if re.search(r"Din[aá]mica\s*[-–—]\s*OSAB", _texto_visivel_bi(frame), re.I):
            return True

    # Atalho: clicar direto no item de navegação «Dinâmica - OSAB» (sem FPD)
    try:
        atalho = frame.locator(
            '.explorationNavigation button, .sectionList button, '
            '[class*="pageNavigation"] button, div[role="tab"]'
        ).filter(has_text=re.compile(r"^\s*Din[aá]mica\s*[-–—]\s*OSAB\s*$", re.I)).first
        if atalho.count():
            logger.info("[OSAB BI] Atalho: clicando Dinâmica - OSAB na barra de páginas")
            atalho.click(timeout=5000, force=True)
            page.wait_for_timeout(2500)
            _aguardar_grade_osab(frame, page, timeout_ms=60000)
            return True
    except Exception as exc:
        logger.debug("[OSAB BI] Atalho Dinâmica falhou: %s", exc)

    # Itens visíveis na navegação (rodapé / lista de páginas)
    nav = frame.locator(
        '.explorationNavigation button, .sectionList button, '
        '[class*="pageNavigation"] button, [class*="navigationPane"] button, '
        '[class*="page-nav"] button, div[role="tab"]'
    )
    try:
        total = min(nav.count(), max_cliques)
    except Exception:
        total = 0

    vistos: set[str] = set()
    for i in range(total):
        try:
            btn = nav.nth(i)
            if not btn.is_visible():
                continue
            nome = re.sub(r"\s+", " ", (btn.inner_text(timeout=1500) or "").strip())
            if not nome or nome in vistos:
                continue
            vistos.add(nome)
            logger.info("[OSAB BI] Tentando página do relatório: %s", nome[:80])
            btn.click(timeout=5000, force=True)
            page.wait_for_timeout(2500)

            # Nome da página já é Dinâmica - OSAB: esperar a grade (não pular adiante).
            if re.search(r"Din[aá]mica\s*[-–—]\s*OSAB", nome, re.I) and not re.search(
                r"FPD|SPD|TPD", nome, re.I
            ):
                logger.info("[OSAB BI] Página Dinâmica - OSAB aberta; aguardando grade…")
                if _aguardar_grade_osab(frame, page, timeout_ms=60000):
                    return True
                logger.warning(
                    "[OSAB BI] Grade lenta; seguindo mesmo assim nesta página. Amostra: %s",
                    _texto_visivel_bi(frame, 300),
                )
                return True

            # Páginas intermediárias: checagem curta (não esperar 8s em cada uma)
            if _aguardar_grade_osab(frame, page, timeout_ms=2500):
                return True
            if _PAT_PAGINA_OSAB.search(_texto_visivel_bi(frame)):
                if _clicar_navegacao_por_texto(frame, page, _PAT_NAV_OSAB):
                    if _aguardar_grade_osab(frame, page, timeout_ms=30000):
                        return True
            if _clicar_navegacao_por_texto(frame, page, _PAT_NAV_OSAB):
                if _aguardar_grade_osab(frame, page, timeout_ms=20000):
                    return True
        except Exception as exc:
            logger.debug("[OSAB BI] Página %s: %s", i, exc)

    # Setas da navegação (quando há overflow)
    for seta in (
        'button[aria-label*="próxima" i]',
        'button[aria-label*="Next" i]',
        'button[aria-label*="next page" i]',
        'button[aria-label*="página seguinte" i]',
    ):
        for _ in range(8):
            try:
                btn = frame.locator(seta).first
                if not (btn.count() and btn.is_visible()):
                    break
                btn.click(timeout=3000)
                page.wait_for_timeout(1200)
                if _clicar_navegacao_por_texto(frame, page, _PAT_NAV_OSAB):
                    page.wait_for_timeout(2000)
                    if _ja_na_pagina_osab(frame):
                        return True
            except Exception:
                break

    return _ja_na_pagina_osab(frame)


def _obter_frame_dinamica_osab(page):
    """Escolhe o iframe certo e navega até a grade Exportação - OSAB."""
    frames = _listar_frames_bi(page)
    if not frames:
        raise RuntimeError("Iframe do Power BI não encontrado no Dashboard.")

    # Preferir frame que já mostre OSAB / Dinâmica / Exportação
    for idx, frame in enumerate(frames):
        amostra = _texto_visivel_bi(frame)
        if _ja_na_pagina_osab(frame):
            logger.info("[OSAB BI] Frame %s já na Exportação - OSAB.", idx)
            return frame
        if _PAT_NAV_OSAB.search(amostra) or re.search(r"\bOSAB\b", amostra, re.I):
            logger.info("[OSAB BI] Frame %s menciona OSAB; navegando…", idx)
            if _varrer_paginas_bi(frame, page):
                return frame

    # Varre todos os frames (o dashboard pode embutir «Visão Parceiro» e «Dinâmica»)
    for idx, frame in enumerate(frames):
        logger.info("[OSAB BI] Varrendo páginas do frame %s/%s…", idx + 1, len(frames))
        if _varrer_paginas_bi(frame, page):
            return frame

    amostras = " | ".join(_texto_visivel_bi(f, 180) for f in frames)
    raise RuntimeError(
        "Não foi possível abrir a página «Dinâmica - OSAB» / «Exportação - OSAB» "
        f"no Power BI. Amostra: {amostras or '(vazio)'}"
    )

_PAT_ANOMES = re.compile(
    r"ANOMES\s*(DA\s*)?VENDA|ANO\s*[-/]?\s*M[EÊ]S\s*(DA\s*)?VENDA",
    re.I,
)
_PAT_TODOS = re.compile(r"^\s*Todos\s*$", re.I)
_PAT_EXPORTAR_DADOS = re.compile(r"Exportar\s+dados|Export\s+data", re.I)
_VISUAL_SEL = (
    "visual-container, visual-container-modern, .visualContainer, "
    ".visual-container-component, .visual-pivotTable, .visual-tableEx"
)


_PAT_SELECT_ALL = re.compile(
    r"^\s*(Todos|Selecionar\s+tudo|Select\s+all)\s*$",
    re.I,
)


def _localizar_visual_anomes(frame):
    """Visual do slicer ANOMES da Venda (exclui a grade Exportação)."""
    try:
        candidatos = frame.locator(_VISUAL_SEL).filter(has_text=_PAT_ANOMES)
        n = candidatos.count()
    except Exception:
        n = 0
    melhor = None
    melhor_len = 10**9
    for i in range(min(n, 8)):
        v = candidatos.nth(i)
        try:
            txt = re.sub(r"\s+", " ", (v.inner_text(timeout=1500) or "").strip())
        except Exception:
            continue
        if not _PAT_ANOMES.search(txt):
            continue
        # A grade Exportação - OSAB é enorme e pode mencionar ANOMES nas colunas
        if re.search(r"Exporta[cç][aã]o\s*[-–—]\s*OSAB", txt, re.I):
            continue
        if len(txt) < melhor_len:
            melhor = v
            melhor_len = len(txt)
    if melhor is not None:
        return melhor
    # Fallback pelo rótulo exato
    rotulo = frame.get_by_text(re.compile(r"^\s*ANOMES\s+da\s+Venda\s*$", re.I)).first
    if rotulo.count() == 0:
        return None
    try:
        pai = rotulo.locator(
            "xpath=ancestor::visual-container[1] | "
            "ancestor::*[contains(@class,'visual-container')][1]"
        ).first
        if pai.count():
            return pai
    except Exception:
        pass
    return rotulo


def _texto_slicer_anomes(frame) -> str:
    """Lê o texto do visual/slicer ANOMES da Venda (vazio se não achar)."""
    visual = _localizar_visual_anomes(frame)
    if visual is None:
        return ""
    try:
        return re.sub(r"\s+", " ", (visual.inner_text(timeout=2000) or "").strip())
    except Exception:
        return ""


def _anomes_esta_todos(texto: str) -> bool:
    """True se header/texto indica Todos / (Todos), sem YYYYMM (ex.: 202610)."""
    if not texto:
        return False
    if re.search(r"\b20\d{4}\b", texto):
        return False
    # Header puro "(Todos)" / "Todos" ou bloco com rótulo ANOMES
    if re.search(r"\(\s*Todos\s*\)|^\s*Todos\s*$", texto, re.I):
        return True
    if _PAT_ANOMES.search(texto) and re.search(r"\bTodos\b", texto, re.I):
        return True
    return False


def _valor_header_anomes(visual) -> str:
    """Valor exibido no header do dropdown (ex.: 202610 ou Todos)."""
    for sel in (
        ".slicer-restatement",
        ".slicerDropdownHeader",
        "[class*='restatement']",
        "[class*='slicer-dropdown']",
        '[role="combobox"]',
    ):
        try:
            loc = visual.locator(sel).first
            if loc.count():
                t = re.sub(r"\s+", " ", (loc.inner_text(timeout=1500) or "").strip())
                if t:
                    return t
        except Exception:
            continue
    try:
        return re.sub(r"\s+", " ", (visual.inner_text(timeout=1500) or "").strip())
    except Exception:
        return ""


def _click_bbox_centro(page, locator, *, label: str = "", modifiers: list | None = None) -> bool:
    """Clique por coordenadas no centro do elemento (mais confiável no embed BI)."""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        box = locator.bounding_box()
        if not box or box["width"] < 2 or box["height"] < 2:
            return False
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        mods = modifiers or []
        logger.info(
            "[OSAB BI] Clique bbox %s em (%.0f, %.0f) mods=%s",
            label or "el",
            x,
            y,
            mods,
        )
        page.mouse.click(x, y, modifiers=mods)
        page.wait_for_timeout(500)
        return True
    except Exception as exc:
        logger.debug("[OSAB BI] Clique bbox falhou (%s): %s", label, exc)
        return False


def _ctrl_key_name(page) -> str:
    """Control no Windows/Linux; Meta no macOS (Playwright)."""
    try:
        if page.evaluate("() => /Mac|iPhone|iPad/.test(navigator.platform)"):
            return "Meta"
    except Exception:
        pass
    return "Control"


def _abrir_dropdown_anomes(visual, page, frame) -> None:
    """
    Abre o dropdown do slicer ANOMES clicando no valor YYYYMM / restatement
    DENTRO do visual ANOMES — nunca no Status da Ordem vizinho.
    """
    visual.scroll_into_view_if_needed(timeout=6000)
    page.wait_for_timeout(200)

    # 1) Valor YYYYMM visível no header do próprio visual (ex.: 202610)
    try:
        valor = visual.get_by_text(re.compile(r"^\s*20\d{4}\s*$")).first
        if valor.count() and valor.is_visible():
            if _click_bbox_centro(page, valor, label="ANOMES-YYYYMM"):
                return
            valor.click(timeout=4000)
            page.wait_for_timeout(700)
            return
    except Exception:
        pass

    # 2) Restatement / combobox restrito ao visual ANOMES
    for sel in (
        ".slicer-restatement",
        ".slicerDropdownHeader",
        "[class*='restatement']",
        '[role="combobox"]',
        "button.slicer-dropdown",
    ):
        try:
            trig = visual.locator(sel).first
            if trig.count() and trig.is_visible():
                if _click_bbox_centro(page, trig, label=f"ANOMES-{sel}"):
                    return
        except Exception:
            continue

    # 3) Rótulo «ANOMES da Venda» → clicar um pouco à direita/abaixo (área do valor)
    try:
        rotulo = frame.get_by_text(re.compile(r"^\s*ANOMES\s+da\s+Venda\s*$", re.I)).first
        if rotulo.count():
            box = rotulo.bounding_box()
            if box:
                # Valor do dropdown fica tipicamente abaixo do rótulo
                page.mouse.click(box["x"] + min(60, box["width"] / 2), box["y"] + box["height"] + 14)
                page.wait_for_timeout(700)
                return
    except Exception:
        pass

    if not _click_bbox_centro(page, visual, label="ANOMES-visual"):
        visual.click(timeout=4000, force=True)
        page.wait_for_timeout(700)


def _popup_slicer_raiz(frame, page):
    """Raiz do popup do dropdown slicer (iframe ou host)."""
    seletores = (
        ".slicer-dropdown-popup",
        "[class*='slicer-dropdown-popup']",
        ".slicerDropdownPopup",
        "div.slicer-dropdown-menu",
        "[class*='slicerPopup']",
        '[role="listbox"]',
    )
    for root in (frame, page):
        for sel in seletores:
            try:
                pops = root.locator(sel)
                n = min(pops.count(), 6)
                for i in range(n):
                    pop = pops.nth(i)
                    try:
                        if pop.is_visible():
                            return pop, root
                    except Exception:
                        continue
            except Exception:
                continue
    return None, frame


def _header_anomes_ok(header: str, texto: str) -> bool:
    """True se ANOMES está em Todos / multi-seleção (não um único YYYYMM)."""
    import unicodedata

    def _norm(s: str) -> str:
        # NFC + strip acentos para casar «Seleções múltiplas» mesmo com NFD
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", s).strip()

    h = _norm(header)
    t = _norm(texto)
    if _anomes_esta_todos(t) or _anomes_esta_todos(h):
        return True
    # Um único mês (202610) = NÃO ok
    if re.fullmatch(r"20\d{4}", h):
        return False
    # Ctrl+clique Power BI → «Seleções múltiplas» / Multiple selections / Todos
    if re.search(
        r"selecoes\s+multiplas|multiple\s+selections|\btodos\b|\ball\b",
        h,
        re.I,
    ):
        return True
    if re.search(
        r"selecoes\s+multiplas|multiple\s+selections|\btodos\b",
        t,
        re.I,
    ):
        return True
    if len(re.findall(r"20\d{4}", h)) >= 2:
        return True
    if re.search(r"selecionad", h, re.I) and not re.fullmatch(r"20\d{4}", h):
        return True
    return False


def _limpar_filtro_slicer(visual, page, frame=None) -> bool:
    """Hover no slicer e clica borracha Limpar seleções → Power BI volta para Todos."""
    try:
        visual.scroll_into_view_if_needed(timeout=5000)
        visual.hover(timeout=4000)
        page.wait_for_timeout(500)
        # Ícones do visual aparecem no hover (chrome do container)
        seletores = (
            'button[aria-label*="Limpar seleções" i]',
            'button[aria-label*="Clear selections" i]',
            'button[aria-label*="Limpar" i]',
            'button[aria-label*="Clear" i]',
            'button[title*="Limpar" i]',
            'button[title*="Clear" i]',
            ".slicer-header-clear",
            ".clearButton",
            "button.vcClearBtn",
            '[data-testid*="clear" i]',
            'button[aria-label*="Reset" i]',
        )
        roots = [visual]
        if frame is not None:
            roots.append(frame)
        for root in roots:
            for sel in seletores:
                try:
                    btns = root.locator(sel)
                    for i in range(min(btns.count(), 4)):
                        btn = btns.nth(i)
                        if not btn.is_visible():
                            continue
                        logger.info("[OSAB BI] Clicando Limpar seleções (%s)…", sel[:40])
                        if not _click_bbox_centro(page, btn, label="ANOMES-clear"):
                            btn.click(timeout=4000, force=True)
                            page.wait_for_timeout(900)
                        return True
                except Exception:
                    continue
        # Fallback: botão clear vizinho ao rótulo ANOMES
        if frame is not None:
            try:
                rotulo = frame.get_by_text(
                    re.compile(r"^\s*ANOMES\s+da\s+Venda\s*$", re.I)
                ).first
                if rotulo.count():
                    box = rotulo.bounding_box()
                    if box:
                        # Ícone limpar costuma ficar à direita do header do visual
                        page.mouse.move(box["x"] + box["width"] + 40, box["y"] + 8)
                        page.wait_for_timeout(400)
                        for sel in seletores[:6]:
                            btn = frame.locator(sel).first
                            if btn.count() and btn.is_visible():
                                btn.click(timeout=4000, force=True)
                                page.wait_for_timeout(900)
                                return True
            except Exception:
                pass
    except Exception as exc:
        logger.debug("[OSAB BI] Limpar slicer: %s", exc)
    return False


def _marcar_todos_no_popup(frame, page) -> bool:
    """
    No popup ANOMES com CONTROL pressionado (padrão Power BI do usuário):
    Ctrl+clique em «Todos»/Select all, ou Ctrl+clique em cada mês.
    Sempre libera Control no finally.
    """
    pop, _root = _popup_slicer_raiz(frame, page)
    if pop is None:
        logger.warning("[OSAB BI] Popup do slicer ANOMES não encontrado.")
        return False

    try:
        amostra = re.sub(r"\s+", " ", (pop.inner_text(timeout=2000) or ""))[:200]
        logger.info("[OSAB BI] Popup ANOMES amostra: %r", amostra)
    except Exception:
        pass

    try:
        pop.evaluate(
            """(el) => {
                el.scrollTop = 0;
                el.querySelectorAll(
                    '.scroll-bar-view-port, .scrollbar-inner, [class*=scroll]'
                ).forEach((s) => { try { s.scrollTop = 0; } catch (e) {} });
            }"""
        )
        page.wait_for_timeout(300)
    except Exception:
        pass

    ctrl = _ctrl_key_name(page)
    mods = [ctrl]
    logger.info("[OSAB BI] Segurando %s para multi-seleção no slicer ANOMES…", ctrl)
    page.keyboard.down(ctrl)
    try:
        # 1) Ctrl+clique em Select all / Selecionar tudo / Todos
        for pat in (
            re.compile(r"Select\s+all", re.I),
            re.compile(r"Selecionar\s+tudo", re.I),
            re.compile(r"^\s*Todos\s*$", re.I),
        ):
            try:
                locs = pop.get_by_text(pat)
                for i in range(min(locs.count(), 4)):
                    item = locs.nth(i)
                    txt = re.sub(r"\s+", " ", (item.inner_text(timeout=800) or "").strip())
                    if re.fullmatch(r"20\d{4}", txt):
                        continue
                    row = item.locator(
                        "xpath=ancestor::*[contains(@class,'slicerItem') or "
                        "contains(@class,'slicer-item') or @role='option'][1]"
                    ).first
                    alvo = row if row.count() else item
                    logger.info("[OSAB BI] Ctrl+clique opção: %r", txt[:50] or pat.pattern)
                    if _click_bbox_centro(page, alvo, label="ANOMES-select-all", modifiers=mods):
                        page.wait_for_timeout(500)
                        return True
                    alvo.click(timeout=4000, modifiers=mods)
                    page.wait_for_timeout(600)
                    return True
            except Exception:
                continue

        # 2) Ctrl+clique em cada mês (multi-select Power BI)
        marcados = 0
        meses = pop.get_by_text(re.compile(r"^\s*20\d{4}\s*$"))
        n = min(meses.count(), 48)
        logger.info("[OSAB BI] Ctrl+clique em até %s meses…", n)
        for i in range(n):
            mes = meses.nth(i)
            try:
                row = mes.locator(
                    "xpath=ancestor::*[contains(@class,'slicerItem') or "
                    "contains(@class,'slicer-item') or @role='option'][1]"
                ).first
                alvo = row if row.count() else mes
                checked = False
                try:
                    cb = alvo.locator(
                        "input[type='checkbox']:checked, "
                        "[aria-checked='true'], .slicerCheckbox.selected"
                    ).first
                    checked = bool(cb.count())
                except Exception:
                    checked = False
                if checked:
                    marcados += 1
                    continue
                if _click_bbox_centro(page, alvo, label=f"ANOMES-ctrl-mes-{i}", modifiers=mods):
                    marcados += 1
                else:
                    alvo.click(timeout=2500, modifiers=mods)
                    marcados += 1
                page.wait_for_timeout(220)
            except Exception:
                continue

        if marcados >= 2:
            logger.info("[OSAB BI] ANOMES: Ctrl+clique em %s meses.", marcados)
            page.wait_for_timeout(400)
            return True
        logger.warning("[OSAB BI] Ctrl+clique marcou só %s item(ns).", marcados)
        return False
    finally:
        try:
            page.keyboard.up(ctrl)
            logger.info("[OSAB BI] %s liberado.", ctrl)
        except Exception:
            pass


def _fechar_popup_slicer(page) -> None:
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(350)
    except Exception:
        pass


def _forcar_anomes_todos(frame, page) -> bool:
    """
    Abre ANOMES da Venda e marca Todos com CONTROL pressionado (Ctrl+clique),
    conforme uso manual no Power BI. Confirma header ≠ YYYYMM.
    """
    logger.info("[OSAB BI] Garantindo slicer ANOMES DA VENDA = Todos…")
    visual = _localizar_visual_anomes(frame)
    if visual is None:
        logger.warning("[OSAB BI] Slicer ANOMES da Venda não encontrado.")
        _salvar_debug_bi(page, "anomes_nao_encontrado")
        return False

    header0 = _valor_header_anomes(visual)
    texto0 = _texto_slicer_anomes(frame)
    logger.info("[OSAB BI] ANOMES header atual: %r", (header0 or texto0)[:80])
    if _header_anomes_ok(header0, texto0):
        logger.info("[OSAB BI] ANOMES DA VENDA já em Todos.")
        _salvar_debug_bi(page, "anomes_ja_todos")
        return True

    logger.info("[OSAB BI] Abrindo dropdown ANOMES (depois Ctrl+clique Todos/meses)…")
    try:
        _abrir_dropdown_anomes(visual, page, frame)
    except Exception as exc:
        logger.warning("[OSAB BI] Falha ao abrir ANOMES: %s", exc)
        _salvar_debug_bi(page, "anomes_nao_confirmado")
        return False

    _salvar_debug_bi(page, "anomes_popup_aberto")
    ok = _marcar_todos_no_popup(frame, page)
    _fechar_popup_slicer(page)
    page.wait_for_timeout(1000)

    visual = _localizar_visual_anomes(frame) or visual
    header = _valor_header_anomes(visual)
    texto = _texto_slicer_anomes(frame)
    logger.info("[OSAB BI] ANOMES após Ctrl+clique: header=%r texto=%r", header[:60], texto[:80])
    _salvar_debug_bi(page, "anomes_apos_ctrl")

    if _header_anomes_ok(header, texto):
        logger.info(
            "[OSAB BI] ANOMES DA VENDA confirmado em Todos/multi (header=%r, ctrl_ok=%s).",
            header[:60],
            ok,
        )
        _salvar_debug_bi(page, "anomes_todos_ok")
        return True

    # Uma reabertura com Ctrl (só se ainda for um único mês)
    logger.warning("[OSAB BI] Header ainda %r; 2ª tentativa Ctrl+clique…", header)
    try:
        _abrir_dropdown_anomes(visual, page, frame)
        ok = _marcar_todos_no_popup(frame, page)
        _fechar_popup_slicer(page)
        page.wait_for_timeout(1000)
        visual = _localizar_visual_anomes(frame) or visual
        header = _valor_header_anomes(visual)
        texto = _texto_slicer_anomes(frame)
        logger.info("[OSAB BI] ANOMES 2ª tentativa: header=%r", (header or "")[:60])
        if ok and _header_anomes_ok(header, texto):
            logger.info("[OSAB BI] ANOMES DA VENDA confirmado em Todos (Ctrl 2ª).")
            _salvar_debug_bi(page, "anomes_todos_ok")
            return True
    except Exception as exc:
        logger.debug("[OSAB BI] 2ª tentativa Ctrl: %s", exc)
        _fechar_popup_slicer(page)

    logger.error(
        "[OSAB BI] ANOMES DA VENDA NÃO ficou em Todos (permaneceu %r).",
        _valor_header_anomes(_localizar_visual_anomes(frame) or visual)[:80],
    )
    _salvar_debug_bi(page, "anomes_nao_confirmado")
    return False


def _garantir_filtros_todos(frame, page) -> None:
    """Garante ANOMES DA VENDA = Todos; falha se o header continuar com YYYYMM."""
    try:
        frame.get_by_text(re.compile(r"Exporta[cç][aã]o\s*-\s*OSAB", re.I)).first.wait_for(
            state="visible", timeout=45000
        )
    except Exception:
        logger.warning("[OSAB BI] Título «Exportação - OSAB» ainda não visível; seguindo.")

    page.wait_for_timeout(1200)
    if not _forcar_anomes_todos(frame, page):
        raise RuntimeError(
            "Filtro ANOMES DA VENDA não ficou em «Todos» "
            "(ainda mostra mês tipo 202610). Exportação abortada."
        )
    page.wait_for_timeout(800)


def _menu_exportar_visivel(frame, page) -> bool:
    """True se o item «Exportar dados» / «Export data» está no DOM (iframe ou host)."""
    for root in (frame, page):
        try:
            if root.get_by_role("menuitem", name=_PAT_EXPORTAR_DADOS).count():
                return True
        except Exception:
            pass
        try:
            if root.get_by_text(_PAT_EXPORTAR_DADOS).count():
                return True
        except Exception:
            pass
    return False


def _salvar_debug_bi(page, nome: str) -> None:
    try:
        debug_dir = Path(
            getattr(settings, "MEDIA_ROOT", tempfile.gettempdir())
        ) / "osab_bi_exports" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"{stamp}_{nome}.png"
        page.screenshot(path=str(path), full_page=True)
        logger.info("[OSAB BI] Screenshot debug: %s", path)
    except Exception as exc:
        logger.debug("[OSAB BI] Screenshot debug falhou: %s", exc)


def _localizar_visual_tabela_osab(frame):
    """Retorna o locator do visual da grade Exportação - OSAB (ou None)."""
    filtros = (
        re.compile(r"Exporta[cç][aã]o\s*[-–—]\s*OSAB", re.I),
        re.compile(r"\bNR\s*ORDEM\b", re.I),
        re.compile(r"\bMATRICULA\s*VENDEDOR\b", re.I),
    )
    for pat in filtros:
        try:
            visuals = frame.locator(_VISUAL_SEL).filter(has_text=pat)
            if visuals.count():
                return visuals.last
        except Exception:
            continue
    return None


def _selecionar_visual_tabela(frame, page) -> None:
    """
    Clica no corpo da tabela Exportação - OSAB para selecionar o visual.
    Sem isso o Power BI não habilita «Exportar dados» no menu ⋯.
    """
    visual = _localizar_visual_tabela_osab(frame)
    if visual is None:
        # Fallback: título da grade
        titulo = frame.get_by_text(
            re.compile(r"Exporta[cç][aã]o\s*[-–—]\s*OSAB", re.I)
        ).first
        if titulo.count() == 0:
            raise RuntimeError("Visual da tabela Exportação - OSAB não encontrado.")
        visual = titulo

    visual.scroll_into_view_if_needed(timeout=8000)
    page.wait_for_timeout(300)

    # Preferir célula/header da grade (corpo), não só o título
    alvo = visual.locator(
        ".pivotTable, .tableEx, .innerContainer, "
        "[role='grid'], [role='table'], "
        ".columnHeaders, .mid-viewport, canvas, .visual-container-container"
    ).first
    if alvo.count() == 0:
        alvo = visual

    logger.info("[OSAB BI] Clicando na tabela para selecionar o visual…")
    try:
        alvo.click(timeout=5000, position={"x": 40, "y": 40})
    except Exception:
        try:
            alvo.click(timeout=5000, force=True)
        except Exception:
            box = visual.bounding_box()
            if box:
                page.mouse.click(box["x"] + min(80, box["width"] / 2), box["y"] + min(60, box["height"] / 2))
            else:
                raise RuntimeError("Não foi possível clicar na tabela Exportação - OSAB.")
    page.wait_for_timeout(700)
    _salvar_debug_bi(page, "tabela_selecionada")


def _abrir_mais_opcoes_uma_vez(more, page, frame) -> bool:
    """Um caminho estável: hover + clique (force se necessário). Sem spam de Escape."""
    more.scroll_into_view_if_needed(timeout=5000)
    more.hover(timeout=4000)
    page.wait_for_timeout(250)
    try:
        more.click(timeout=5000)
    except Exception:
        more.click(timeout=5000, force=True)
    for _ in range(16):
        if _menu_exportar_visivel(frame, page):
            return True
        page.wait_for_timeout(200)
    return False


def _clicar_mais_opcoes_tabela(frame, page) -> None:
    """Seleciona a tabela, depois abre ⋯ desse visual (1–2 candidatos no máximo)."""
    _selecionar_visual_tabela(frame, page)

    visual = _localizar_visual_tabela_osab(frame)
    more = None
    if visual is not None:
        visual.hover(timeout=4000)
        page.wait_for_timeout(300)
        btn = visual.locator(
            '[data-testid="visual-more-options-btn"], '
            'button.vcMenuBtn, '
            'button[aria-label*="Mais opções" i], '
            'button[aria-label*="More options" i]'
        ).first
        if btn.count():
            more = btn

    if more is None:
        # Último ⋯ da página (tabela costuma ficar abaixo)
        cand = frame.locator(
            '[data-testid="visual-more-options-btn"], '
            'button.vcMenuBtn[aria-label*="Mais opções" i], '
            'button[aria-label*="More options" i]'
        )
        if cand.count() == 0:
            _salvar_debug_bi(page, "sem_mais_opcoes")
            raise RuntimeError("Botão «Mais opções» do visual não encontrado.")
        more = cand.last

    logger.info("[OSAB BI] Abrindo Mais opções do visual selecionado…")
    if _abrir_mais_opcoes_uma_vez(more, page, frame):
        logger.info("[OSAB BI] Menu com «Exportar dados» aberto.")
        _salvar_debug_bi(page, "menu_exportar_aberto")
        return

    # Uma única re-tentativa: re-seleciona tabela + force click
    logger.info("[OSAB BI] Re-selecionando tabela e tentando ⋯ novamente…")
    _selecionar_visual_tabela(frame, page)
    more.hover(timeout=3000)
    page.wait_for_timeout(200)
    more.click(timeout=5000, force=True)
    for _ in range(16):
        if _menu_exportar_visivel(frame, page):
            logger.info("[OSAB BI] Menu com «Exportar dados» aberto (2ª tentativa).")
            _salvar_debug_bi(page, "menu_exportar_aberto")
            return
        page.wait_for_timeout(200)

    _salvar_debug_bi(page, "menu_exportar_nao_abriu")
    raise RuntimeError(
        "Após selecionar a tabela, o menu «Exportar dados» não apareceu no ⋯."
    )


def _exportar_dados_layout_atual(frame, page) -> Path:
    """Clica na tabela → ⋯ → Exportar dados → Dados com layout atual → Exportar."""
    _salvar_debug_bi(page, "antes_export")
    _clicar_mais_opcoes_tabela(frame, page)

    exportar_item = None
    for root in (frame, page):
        try:
            loc = root.get_by_role("menuitem", name=_PAT_EXPORTAR_DADOS).first
            if loc.count():
                exportar_item = loc
                break
        except Exception:
            pass
        try:
            loc = root.get_by_text(_PAT_EXPORTAR_DADOS).first
            if loc.count():
                exportar_item = loc
                break
        except Exception:
            pass
    if exportar_item is None:
        _salvar_debug_bi(page, "sem_item_exportar")
        raise RuntimeError("Item «Exportar dados» não encontrado após selecionar a tabela.")
    exportar_item.click(timeout=10000)
    page.wait_for_timeout(800)

    # Diálogo pode estar no iframe ou no host
    dialog_root = page
    layout = None
    for root in (frame, page):
        try:
            loc = root.get_by_text(
                re.compile(r"Dados com layout atual", re.I)
            ).first
            if loc.count():
                layout = loc
                dialog_root = root
                break
        except Exception:
            continue
    if layout is None:
        raise RuntimeError("Opção «Dados com layout atual» não apareceu no diálogo de exportação.")

    layout.click(timeout=8000)
    page.wait_for_timeout(400)

    btn_export = None
    for root in (dialog_root, frame, page):
        try:
            # Botão primário Exportar (não o item de menu)
            cand = root.get_by_role("button", name=re.compile(r"^\s*Exportar\s*$", re.I))
            if cand.count():
                btn_export = cand.last
                break
        except Exception:
            continue
    if btn_export is None:
        raise RuntimeError("Botão «Exportar» do diálogo não encontrado.")

    downloads_dir = Path(
        getattr(settings, "MEDIA_ROOT", tempfile.gettempdir())
    ) / "osab_bi_exports"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    with page.expect_download(timeout=180000) as dl_info:
        btn_export.click(timeout=10000)
    download = dl_info.value
    suggested = download.suggested_filename or f"osab_bi_{int(time.time())}.xlsx"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = downloads_dir / f"{stamp}_{suggested}"
    download.save_as(str(dest))
    logger.info("[OSAB BI] Download salvo: %s (%s bytes)", dest, dest.stat().st_size)
    return dest


def _disparar_importacao_crm(path: Path, *, enviar_whatsapp: bool = False) -> tuple[int, str]:
    from django.contrib.auth import get_user_model

    from crm_app.models import LogImportacaoOSAB
    from crm_app.views import ImportacaoOsabView

    User = get_user_model()
    usuario = (
        User.objects.filter(is_superuser=True, is_active=True).order_by("id").first()
        or User.objects.filter(is_active=True).order_by("id").first()
    )
    content = path.read_bytes()
    nome = path.name
    log = LogImportacaoOSAB.objects.create(
        usuario=usuario,
        nome_arquivo=nome,
        status="PROCESSANDO",
        tamanho_arquivo=len(content),
        enviar_whatsapp=enviar_whatsapp,
        mensagem="Importação automática via BI Dinâmica OSAB (PAP).",
    )
    view = ImportacaoOsabView()
    view._processar_osab_interno(log.id, content, nome, enviar_whatsapp)
    log.refresh_from_db()
    return log.id, log.status or ""


def exportar_e_importar_osab_bi(
    *,
    matricula: str = "",
    headless: bool = True,
    enviar_whatsapp: bool = False,
    pular_importacao: bool = False,
) -> ResultadoImportOsabBi:
    """
    Fluxo completo: login PAP (conta robô) → Dashboard → Dinâmica OSAB →
    filtros Todos → export layout atual → import OSAB CRM.
    """
    robo = _obter_robo(matricula=matricula)
    if not _trancar_robo(robo):
        return ResultadoImportOsabBi(
            ok=False,
            detail=f"Conta {robo.matricula} em uso por outro processo.",
            matricula=robo.matricula,
        )

    from crm_app.services_pap_nio import PAPNioAutomation

    pap = PAPNioAutomation(
        matricula_pap=robo.matricula,
        senha_pap=robo.senha,
        vendedor_nome=f"OSAB_BI_{robo.matricula}",
        headless=headless,
        slow_mo=450 if not headless else 0,
        url_pos_login=PAP_DASHBOARD_URL,
        optimize_for_credit=False,
    )
    arquivo: Optional[Path] = None
    try:
        ok, msg = pap.iniciar_sessao()
        if not ok:
            return ResultadoImportOsabBi(
                ok=False,
                detail=f"Login PAP falhou: {msg}",
                matricula=robo.matricula,
            )

        page = pap.page
        assert page is not None
        _sair_tela_cheia(page)

        if "dashboard" not in (page.url or "").lower():
            page.goto(PAP_DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            _sair_tela_cheia(page)

        # Aguardar embed Power BI e navegar até Dinâmica / Exportação - OSAB
        page.wait_for_selector(_IFRAME_BI, timeout=90000)
        page.wait_for_timeout(8000)
        _aguardar_qualquer_bi(page, timeout_ms=90000)
        frame = _obter_frame_dinamica_osab(page)
        page.wait_for_timeout(2000)
        _garantir_filtros_todos(frame, page)
        page.wait_for_timeout(2000)

        arquivo = _exportar_dados_layout_atual(frame, page)
        size = arquivo.stat().st_size if arquivo.exists() else 0
        if size < 64:
            return ResultadoImportOsabBi(
                ok=False,
                detail="Arquivo exportado vazio ou inválido.",
                matricula=robo.matricula,
                arquivo=str(arquivo),
                bytes_arquivo=size,
            )

        if pular_importacao:
            return ResultadoImportOsabBi(
                ok=True,
                detail="Exportação concluída (importação pulada).",
                matricula=robo.matricula,
                arquivo=str(arquivo),
                bytes_arquivo=size,
            )

        log_id, log_status = _disparar_importacao_crm(
            arquivo, enviar_whatsapp=enviar_whatsapp
        )
        ok_import = log_status in ("SUCESSO", "PARCIAL", "PROCESSANDO")
        return ResultadoImportOsabBi(
            ok=ok_import,
            detail=f"Importação OSAB finalizada com status {log_status}.",
            matricula=robo.matricula,
            arquivo=str(arquivo),
            bytes_arquivo=size,
            log_id=log_id,
            log_status=log_status,
        )
    except Exception as exc:
        logger.exception("[OSAB BI] Falha no fluxo automático")
        return ResultadoImportOsabBi(
            ok=False,
            detail=str(exc)[:2000],
            matricula=robo.matricula,
            arquivo=str(arquivo) if arquivo else "",
        )
    finally:
        try:
            pap._fechar_sessao(fazer_logout=False)
        except Exception:
            pass
        _liberar_robo(robo.pk)
