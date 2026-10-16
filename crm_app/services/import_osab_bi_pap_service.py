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
    try:
        el = frame.get_by_text(re.compile(r"Exporta[cç][aã]o\s*[-–—]\s*OSAB", re.I)).first
        return bool(el.count() and el.is_visible())
    except Exception:
        return False


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
        if _ja_na_pagina_osab(frame):
            return True

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
            page.wait_for_timeout(2200)
            if _ja_na_pagina_osab(frame) or _PAT_PAGINA_OSAB.search(_texto_visivel_bi(frame)):
                if not _ja_na_pagina_osab(frame):
                    _clicar_navegacao_por_texto(frame, page, _PAT_NAV_OSAB)
                    page.wait_for_timeout(1500)
                if _ja_na_pagina_osab(frame):
                    return True
            # Dentro da página, abas internas (Dinâmica - OSAB)
            if _clicar_navegacao_por_texto(frame, page, _PAT_NAV_OSAB):
                page.wait_for_timeout(2000)
                if _ja_na_pagina_osab(frame):
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

def _garantir_filtros_todos(frame, page) -> None:
    """
    Melhor esforço: se um slicer dropdown não mostra «Todos», abre e escolhe Todos.
    RLS do usuário PAP ainda pode limitar a base.
    """
    # Esperar visual principal
    try:
        frame.get_by_text(re.compile(r"Exporta[cç][aã]o\s*-\s*OSAB", re.I)).first.wait_for(
            state="visible", timeout=45000
        )
    except Exception:
        logger.warning("[OSAB BI] Título «Exportação - OSAB» ainda não visível; seguindo.")

    page.wait_for_timeout(1500)

    # Combobox / botões de slicer com valor atual ≠ Todos
    slicers = frame.locator(
        '[role="combobox"], button.slicer-dropdown, .slicer-dropdown-menu, '
        '.slicer-header, [aria-haspopup="listbox"]'
    )
    try:
        n = min(slicers.count(), 12)
    except Exception:
        n = 0

    for i in range(n):
        try:
            s = slicers.nth(i)
            if not s.is_visible():
                continue
            texto = (s.inner_text(timeout=1500) or "").strip()
            if not texto or re.search(r"\btodos\b", texto, re.I):
                continue
            # Ignora controles de dia/slider
            if re.search(r"^\d+\s*$|dia\b", texto, re.I):
                continue
            s.click(timeout=3000)
            page.wait_for_timeout(500)
            opcao = frame.get_by_role(
                "option", name=re.compile(r"^\s*Todos\s*$", re.I)
            ).first
            if opcao.count() == 0:
                opcao = frame.get_by_text(re.compile(r"^\s*Todos\s*$", re.I)).first
            if opcao.count():
                opcao.click(timeout=3000)
                page.wait_for_timeout(800)
            else:
                page.keyboard.press("Escape")
        except Exception as exc:
            logger.debug("[OSAB BI] Slicer %s: %s", i, exc)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass


def _exportar_dados_layout_atual(frame, page) -> Path:
    """⋯ na tabela Exportação - OSAB → Exportar dados → Dados com layout atual → Exportar."""
    # Focar o visual da tabela (hover no título ajuda a mostrar o menu)
    titulo = frame.get_by_text(re.compile(r"Exporta[cç][aã]o\s*-\s*OSAB", re.I)).first
    try:
        titulo.scroll_into_view_if_needed(timeout=8000)
        titulo.hover(timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(600)

    more = None
    # Preferir o menu do visual que contém o título Exportação - OSAB
    try:
        visual = frame.locator(
            "visual-container, visual-container-modern, .visualContainer, .visual-container-component"
        ).filter(has_text=re.compile(r"Exporta[cç][aã]o\s*-\s*OSAB", re.I)).first
        visual.hover(timeout=5000)
        more = visual.locator(
            'button[aria-label*="Mais opções" i], button[aria-label*="More options" i], '
            'button[title*="Mais opções" i], button[title*="More options" i]'
        ).first
        if more.count() == 0:
            more = None
    except Exception:
        more = None

    if more is None:
        for sel in (
            'button[aria-label*="Mais opções" i]',
            'button[aria-label*="More options" i]',
            'button[title*="Mais opções" i]',
            'button[title*="More options" i]',
        ):
            try:
                cand = frame.locator(sel)
                for j in range(min(cand.count(), 8)):
                    btn = cand.nth(j)
                    if btn.is_visible():
                        more = btn
                        break
                if more:
                    break
            except Exception:
                continue

    if more is None:
        more = frame.get_by_role("button", name=re.compile(r"Mais opções|More options", re.I)).first
        more.wait_for(state="visible", timeout=12000)

    more.click(timeout=8000)
    page.wait_for_timeout(500)

    exportar_item = frame.get_by_text(re.compile(r"^\s*Exportar dados\s*$", re.I)).first
    if exportar_item.count() == 0:
        exportar_item = page.get_by_text(re.compile(r"^\s*Exportar dados\s*$", re.I)).first
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
