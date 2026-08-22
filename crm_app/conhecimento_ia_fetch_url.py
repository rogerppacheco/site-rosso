# crm_app/conhecimento_ia_fetch_url.py
"""
Busca conteúdo de URLs para alimentar a base de conhecimento da IA.
Extrai texto com BeautifulSoup. Opção de crawlar páginas do mesmo domínio.
"""
import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RecordPAP-ConhecimentoIA/1.0; +https://recordpap.com.br)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
MAX_PAGES_CRAWL = 30
MAX_CHARS_PAGE = 100_000


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _same_domain(url: str, base_domain: str) -> bool:
    try:
        return urlparse(url).netloc == base_domain
    except Exception:
        return False


def _extract_text(html: str, url: str = "") -> str:
    """Extrai texto legível do HTML removendo scripts e estilos."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "form", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Reduz linhas em branco e espaços excessivos
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return (text.strip() or "")[:MAX_CHARS_PAGE]
    except Exception as e:
        logger.warning("[Conhecimento IA] Erro ao extrair texto de %s: %s", url, e)
        return ""


def fetch_url(url: str) -> str:
    """
    Busca uma URL e retorna o texto extraído da página.
    Retorna string vazia em caso de erro.
    """
    url = _normalize_url(url)
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _extract_text(resp.text, url)
    except requests.exceptions.RequestException as e:
        logger.warning("[Conhecimento IA] Erro ao buscar URL %s: %s", url, e)
        return ""
    except Exception as e:
        logger.warning("[Conhecimento IA] Erro ao processar URL %s: %s", url, e)
        return ""


def fetch_url_and_crawl(url: str, max_pages: int = MAX_PAGES_CRAWL) -> tuple[str, str]:
    """
    Busca a URL e, em seguida, todas as páginas do mesmo domínio encontradas nos links.
    Retorna (texto_completo, titulo_primeira_pagina).
    """
    url = _normalize_url(url)
    if not url:
        return "", ""
    try:
        domain = urlparse(url).netloc
        seen = {url}
        to_visit = [url]
        all_parts = []
        title_first = ""

        while to_visit and len(seen) <= max_pages:
            current = to_visit.pop(0)
            try:
                resp = requests.get(
                    current, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                text = _extract_text(resp.text, current)
                if text:
                    titulo = ""
                    if soup.title and soup.title.string:
                        titulo = soup.title.string.strip()[:200]
                    if not title_first and titulo:
                        title_first = titulo
                    all_parts.append(f"[Página: {titulo or current}]\n{text}")

                if len(seen) < max_pages:
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        full = urljoin(current, href)
                        parsed = urlparse(full)
                        if parsed.scheme not in ("http", "https"):
                            continue
                        if parsed.netloc != domain:
                            continue
                        # Remove fragmento e normaliza
                        full = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        if parsed.query:
                            full += "?" + parsed.query
                        if full not in seen:
                            seen.add(full)
                            to_visit.append(full)
            except requests.exceptions.RequestException as e:
                logger.debug("[Conhecimento IA] Falha ao buscar %s: %s", current, e)
            except Exception as e:
                logger.debug("[Conhecimento IA] Erro ao processar %s: %s", current, e)

        if not all_parts:
            return "", ""
        return "\n\n---\n\n".join(all_parts), title_first
    except Exception as e:
        logger.warning("[Conhecimento IA] Erro no crawl de %s: %s", url, e)
        return "", ""
