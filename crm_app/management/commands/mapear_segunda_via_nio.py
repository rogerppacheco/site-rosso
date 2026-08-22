"""
Mapeamento automático do fluxo de 2ª via de conta no site da Nio.

Abre o navegador na página:
  https://www.niointernet.com.br/ajuda/servicos/segunda-via/

A cada navegação OU ao pressionar Enter no terminal, captura:
- URL atual
- Inputs (CPF/CNPJ, etc.) com id, name, placeholder e seletores sugeridos
- Botões (texto, data-* e seletores)
- Links relevantes

O mapa é salvo em: crm_app/data/nio_segunda_via_map.json

Uso:
  python manage.py mapear_segunda_via_nio

  Navegue manualmente pela página. Cada mudança de URL será registrada.
  Pressione Enter no terminal para capturar o estado atual (útil em SPAs).
  Ctrl+C para salvar e sair.
"""
import json
import threading
from pathlib import Path

from django.core.management.base import BaseCommand

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

URL_SEGUNDA_VIA = "https://www.niointernet.com.br/ajuda/servicos/segunda-via/"
OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "nio_segunda_via_map.json"

# Flag para captura manual (thread-safe)
_capture_requested = False
_capture_lock = threading.Lock()


def _set_capture_requested(value: bool):
    global _capture_requested
    with _capture_lock:
        _capture_requested = value


def _get_capture_requested() -> bool:
    with _capture_lock:
        return _capture_requested


def _capture_page_state(page):
    """Extrai estado da página: inputs, botões, links e sugere seletores."""
    try:
        data = page.evaluate("""() => {
            const result = {
                url: window.location.href,
                title: document.title,
                inputs: [],
                buttons: [],
                links: [],
                iframes: []
            };
            // Inputs
            document.querySelectorAll('input, textarea, select').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return; // invisível
                const sel = {};
                if (el.id) sel.id = '#' + el.id;
                if (el.name) sel.name = '[name="' + el.name + '"]';
                if (el.placeholder) sel.placeholder = '[placeholder*="' + el.placeholder.substring(0,30) + '"]';
                result.inputs.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || el.tagName,
                    id: el.id || null,
                    name: el.name || null,
                    placeholder: (el.placeholder || '').substring(0, 80),
                    selectors: sel
                });
            });
            // Botões e elementos clicáveis com role=button
            document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"], a.btn, [data-context*="btn"], form button, form [type="submit"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return;
                const text = (el.textContent || '').trim().substring(0, 60);
                const sel = {};
                if (el.id) sel.id = '#' + el.id;
                if (el.getAttribute('data-context')) sel.dataContext = '[data-context="' + el.getAttribute('data-context') + '"]';
                if (text) sel.text = 'button:has-text("' + text.substring(0, 30) + '")';
                result.buttons.push({
                    tag: el.tagName.toLowerCase(),
                    text: text,
                    dataContext: el.getAttribute('data-context') || null,
                    selectors: sel
                });
            });
            // Links (principalmente os que parecem "Acesso rápido", "Consultar", etc.)
            document.querySelectorAll('a[href]').forEach(el => {
                const text = (el.textContent || '').trim().substring(0, 80);
                const href = el.getAttribute('href') || '';
                if (!href || href === '#' || href.startsWith('javascript:')) return;
                result.links.push({
                    text: text,
                    href: href.startsWith('/') ? window.location.origin + href : href,
                    selectors: el.id ? {'id': '#' + el.id} : (text ? {'text': 'a:has-text("' + text.substring(0, 40) + '")'} : {})
                });
            });
            // iframes (podem conter o formulário)
            document.querySelectorAll('iframe[src]').forEach(el => {
                result.iframes.push({
                    src: el.getAttribute('src'),
                    id: el.id || null
                });
            });
            return result;
        }""")
        return data
    except Exception as e:
        return {"error": str(e), "url": page.url}


def _save_map(steps):
    """Salva o mapa em JSON."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(steps, f, indent=2, ensure_ascii=False)
    return str(OUTPUT_FILE)


def _input_thread():
    """Thread que lê Enter do terminal."""
    global _capture_requested
    try:
        while True:
            input("\n>> Pressione Enter para capturar estado atual (Ctrl+C para sair)...\n")
            _set_capture_requested(True)
    except (EOFError, KeyboardInterrupt):
        pass


class Command(BaseCommand):
    help = "Mapeia o fluxo de 2ª via Nio clicando em cada etapa e capturando seletores automaticamente"

    def add_arguments(self, parser):
        parser.add_argument(
            "--headless",
            action="store_true",
            help="Rodar navegador em modo headless (não recomendado para mapeamento)",
        )
        parser.add_argument(
            "--capture-once",
            action="store_true",
            help="Captura uma vez e sai (útil para testar se a página carrega corretamente)",
        )

    def handle(self, *args, **options):
        if not HAS_PLAYWRIGHT:
            self.stderr.write(self.style.ERROR("Playwright não está instalado. Rode: pip install playwright && playwright install chromium"))
            return

        self.stdout.write(self.style.SUCCESS("\n[MAPEAMENTO] 2a Via Nio\n"))
        self.stdout.write(f"URL: {URL_SEGUNDA_VIA}\n")
        self.stdout.write("Navegue pela página. Cada mudança de URL será registrada automaticamente.\n")
        self.stdout.write("Pressione Enter no terminal para capturar o estado atual (útil em SPAs).\n")
        self.stdout.write("Ctrl+C para salvar o mapa e sair.\n")

        steps = []
        last_url = None

        def on_navigate():
            nonlocal last_url
            try:
                url = page.url
                if url and url != last_url:
                    last_url = url
                    state = _capture_page_state(page)
                    if "error" not in state:
                        steps.append({"trigger": "navigation", **state})
                        self.stdout.write(self.style.SUCCESS(f"  [OK] Capturado (navegacao): {url[:80]}..."))
                        n_in = len(state.get("inputs", []))
                        n_btn = len(state.get("buttons", []))
                        self.stdout.write(f"    inputs={n_in}, botões={n_btn}, links={len(state.get('links', []))}")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  [!] Erro ao capturar: {e}"))

        def on_load():
            try:
                on_navigate()
            except Exception:
                pass

        # Thread para ler Enter
        t = threading.Thread(target=_input_thread, daemon=True)
        t.start()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=options.get("headless", False))
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                )
                page = context.new_page()

                page.on("load", on_load)

                page.goto(URL_SEGUNDA_VIA, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                on_load()

                if options.get("capture_once"):
                    self.stdout.write(self.style.SUCCESS("\n[OK] Modo --capture-once: salvando e saindo..."))
                else:
                    self.stdout.write("\nNavegue pela página. Pressione Enter para capturar ou Ctrl+C para sair.\n")

                # Loop: aguarda capturas manuais ou fim
                max_wait_sec = 5 if options.get("capture_once") else 3600
                waited = 0
                while waited < max_wait_sec:
                    page.wait_for_timeout(500)
                    waited += 1
                    if _get_capture_requested():
                        _set_capture_requested(False)
                        state = _capture_page_state(page)
                        if "error" not in state:
                            steps.append({"trigger": "manual", **state})
                            self.stdout.write(self.style.SUCCESS(f"  [OK] Capturado (manual): {state.get('url', '')[:80]}"))
                            n_in = len(state.get("inputs", []))
                            n_btn = len(state.get("buttons", []))
                            self.stdout.write(f"    inputs={n_in}, botões={n_btn}")

        except KeyboardInterrupt:
            self.stdout.write("\n\nSalvando mapa...")
        finally:
            pass

        if steps:
            path = _save_map(steps)
            self.stdout.write(self.style.SUCCESS(f"\n[OK] Mapa salvo em: {path}"))
            self.stdout.write(f"   Total de etapas capturadas: {len(steps)}")
        else:
            self.stdout.write(self.style.WARNING("\n[!] Nenhuma etapa capturada."))
