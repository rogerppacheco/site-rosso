# crm_app/services_nio.py
"""
Serviço para automação de consulta de faturas no site da Nio Internet
"""
import json
import os
import re
import threading
from datetime import datetime
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

# Lock para evitar dois downloads de PDF simultâneos (evita fechar browser do outro)
_pdf_download_lock = threading.Lock()

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
    PdfReader = None


def _pdf_is_openable(path: str) -> bool:
    """Retorna True se o arquivo PDF existe, tem header %PDF e o pypdf consegue abrir (evita enviar PDF corrompido)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"%PDF":
                return False
    except Exception:
        return False
    if not HAS_PYPDF:
        return os.path.getsize(path) > 3000
    try:
        reader = PdfReader(path)
        return len(reader.pages) >= 1
    except Exception:
        return False

# URL do site Nio Negociar (mesmo que nio_api.SITE_URL)
NIO_BASE_URL = "https://negociacao.niointernet.com.br"
# Site 2ª via (sem reCAPTCHA)
NIO_SEGUNDA_VIA_URL = "https://www.niointernet.com.br/ajuda/servicos/segunda-via"
DEFAULT_STORAGE_STATE = getattr(settings, "NIO_STORAGE_STATE", os.path.join(settings.BASE_DIR, ".playwright_state.json"))


def _selector(key: str, default: str) -> str:
    """Selector configurável via settings (NIO_PDF_SELECTOR_*) ou env. Ex.: _selector('PAGAR_CONTA', 'button:has-text("Pagar conta")')"""
    setting_name = f"NIO_PDF_SELECTOR_{key}"
    return getattr(settings, setting_name, None) or os.getenv(setting_name) or default


def _resolver_recaptcha_nio(page) -> bool:
    """
    Obtém o site key do reCAPTCHA na página, chama a API de resolução (CapSolver/2captcha)
    e injeta o token na página, acionando o callback para habilitar o botão Consultar.
    Retorna True se resolveu e injetou, False caso contrário.
    """
    try:
        # Diagnóstico: obter site key e informações do widget (callback, textarea)
        diag = page.evaluate("""() => {
            const siteKeyEl = document.querySelector('.g-recaptcha[data-sitekey]');
            const siteKey = siteKeyEl ? siteKeyEl.getAttribute('data-sitekey') : null;
            let siteKeyFromIframe = null;
            const iframe = document.querySelector('iframe[src*="recaptcha"], iframe[src*="google.com/recaptcha"]');
            if (iframe && iframe.src) {
                const m = iframe.src.match(/[?&]k=([^&]+)/);
                if (m) siteKeyFromIframe = m[1];
            }
            const callbacks = [];
            document.querySelectorAll('[data-callback]').forEach(el => { callbacks.push(el.getAttribute('data-callback')); });
            const textarea = document.getElementById('g-recaptcha-response') || document.querySelector('textarea[name="g-recaptcha-response"]');
            const hasGrecaptcha = typeof window.grecaptcha !== 'undefined';
            return {
                siteKey: siteKey || siteKeyFromIframe,
                dataCallbacks: callbacks,
                hasTextarea: !!textarea,
                hasGrecaptcha: hasGrecaptcha,
                widgetCount: document.querySelectorAll('.g-recaptcha').length
            };
        }""")
        print(f"[PDF] reCAPTCHA diagnóstico: siteKey={bool(diag.get('siteKey'))}, dataCallbacks={diag.get('dataCallbacks')}, hasTextarea={diag.get('hasTextarea')}, hasGrecaptcha={diag.get('hasGrecaptcha')}, widgets={diag.get('widgetCount')}")

        site_key = diag.get("siteKey")
        if not site_key:
            print("[PDF] reCAPTCHA: site key não encontrado na página.")
            return False

        api_key = getattr(settings, "CAPTCHA_API_KEY", None) or os.getenv("CAPTCHA_API_KEY")
        if not api_key:
            print("[PDF] reCAPTCHA: CAPTCHA_API_KEY não configurado. Configure para resolver automaticamente.")
            return False

        page_url = page.url or NIO_BASE_URL + "/negociar"
        from crm_app.recaptcha_solver import RecaptchaSolver
        provider = getattr(settings, "CAPTCHA_PROVIDER", "capsolver") or os.getenv("CAPTCHA_PROVIDER", "capsolver")
        custom_url = getattr(settings, "RECAPTCHA_SOLVER_API_URL", None) or os.getenv("RECAPTCHA_SOLVER_API_URL")
        solver = RecaptchaSolver(api_key=api_key, provider=provider, custom_url=custom_url or None)
        print(f"[PDF] reCAPTCHA: resolvendo via {provider} (site_key={site_key[:20]}...).")
        token = solver.solve_recaptcha_v2(site_key, page_url)
        if not token:
            print("[PDF] reCAPTCHA: API não retornou token.")
            return False

        # Verificar se a página ainda está aberta (pode ter fechado durante a espera do solver)
        try:
            page.evaluate("() => 1")
        except Exception as e:
            print(f"[PDF] reCAPTCHA: página fechada durante espera do solver ({e}). Não injetando token.")
            return False

        # Injetar token: preencher g-recaptcha-response e acionar callback (data-callback ou nomes comuns)
        inject_result = page.evaluate(
            """(args) => {
                const token = args.token;
                const textarea = document.getElementById('g-recaptcha-response') || document.querySelector('textarea[name="g-recaptcha-response"]');
                let filled = false;
                if (textarea) {
                    textarea.value = token;
                    textarea.style.display = 'block';
                    textarea.dispatchEvent(new Event('change', { bubbles: true }));
                    textarea.dispatchEvent(new Event('input', { bubbles: true }));
                    filled = true;
                }
                const callbackName = document.querySelector('.g-recaptcha[data-callback]')?.getAttribute('data-callback')
                    || document.querySelector('[data-callback]')?.getAttribute('data-callback');
                let callbackCalled = false;
                if (callbackName && typeof window[callbackName] === 'function') {
                    try { window[callbackName](token); callbackCalled = true; } catch (e) { }
                }
                const commonNames = ['onRecaptchaSuccess', 'onRecaptchaSubmit', 'recaptchaCallback', 'handleRecaptcha', 'captchaCallback'];
                for (const name of commonNames) {
                    if (!callbackCalled && typeof window[name] === 'function') {
                        try { window[name](token); callbackCalled = true; break; } catch (e) { }
                    }
                }
                if (!callbackCalled && window.grecaptcha && window.grecaptcha.getResponse) {
                    try {
                        const clients = window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients;
                        if (clients && typeof clients === 'object') {
                            const keys = Object.keys(clients);
                            for (const k of keys) {
                                const c = clients[k];
                                if (c && c.callback) { try { c.callback(token); callbackCalled = true; break; } catch (e) { } }
                            }
                        }
                    } catch (e) { }
                }
                return { filled, callbackCalled };
            }""",
            {"token": token},
        )
        filled = inject_result.get("filled", False)
        callback_called = inject_result.get("callbackCalled", False)
        print(f"[PDF] reCAPTCHA: token preenchido no textarea={filled}, callback acionado={callback_called}")
        if not callback_called:
            print("[PDF] reCAPTCHA: a página Nio pode usar React/closure — o callback não está em window. O botão só habilita quando o site chama o callback interno após o reCAPTCHA.")
        return filled
    except Exception as e:
        print(f"[PDF] reCAPTCHA: erro ao resolver/injetar: {e}")
        import traceback
        traceback.print_exc()
        return False


def buscar_todas_faturas_nio_por_cpf(cpf, incluir_pdf=True):
    """
    Busca TODAS as faturas disponíveis no Nio para um CPF (para matching por vencimento)
    
    Args:
        cpf: CPF do cliente
        incluir_pdf: Se True, tenta buscar via Playwright para pegar PDF (mais lento)
                     Se False, usa apenas API (mais rápido, mas sem PDF)
    """
    cpf_limpo = re.sub(r'\D', '', cpf or '')
    if not cpf_limpo:
        return []

    # Se precisa do PDF, usa Playwright direto (scraping completo)
    if incluir_pdf and HAS_PLAYWRIGHT:
        try:
            print(f"[DEBUG] Buscando fatura via Playwright (com PDF) para CPF: {cpf_limpo}")
            result = buscar_fatura_segunda_via_site(cpf_limpo, incluir_pdf=True)
            return result if isinstance(result, list) else []
        except Exception as e:
            print(f"[ERRO] Falha ao buscar fatura via Playwright: {e}")
            return []


def buscar_fatura_segunda_via_site(cpf: str, incluir_pdf: bool = False, headless: bool = True):
    """
    Busca fatura no site 2ª via (www.niointernet.com.br) - sem reCAPTCHA.

    Fluxo mapeado:
    1) Preencher CPF em #cpf-cnpj
    2) Clicar seta (img.segunda-via__icon-button)
    3) Extrair referência do mês (div.resultados-entry__cell.title)
    4) Extrair valor (div.resultados-entry__cell.amount)
    5) Extrair vencimento (div.resultados-entry__cell.due-date)
    6) Extrair status (span.resultados-status-chip)
    7) Clicar seta para expandir (svg.resultados-entry__icon)
    8) Clicar "Gerar Pix" (#desktop-generate-pix)
    9) Clicar "Copiar Código" (#pixCopyButton) e ler clipboard
    10) Clicar Boleto -> #desktop-generate-boleto -> #barCodeCopyButton (clipboard = código de barras)
    11) PDF: expect_download ao clicar #downloadInvoice; fallback page.pdf() (nome: cpf_ddmmaaaa.pdf)
    """
    cpf_limpo = re.sub(r"\D", "", cpf or "")
    if not cpf_limpo:
        return []

    if not HAS_PLAYWRIGHT:
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800},
                accept_downloads=True,
            )
            context.grant_permissions(["clipboard-read"])
            page = context.new_page()

            page.goto(f"{NIO_SEGUNDA_VIA_URL}/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1500)

            # 1) Preencher CPF
            page.locator("#cpf-cnpj").fill(cpf_limpo)
            page.wait_for_timeout(500)

            # 2) Clicar na seta para consultar (img ou botão pai)
            page.locator("img.segunda-via__icon-button, .segunda-via__icon-button").first.click(timeout=8000)
            page.wait_for_timeout(2000)

            # Aguardar resultado (URL com /resultado/)
            try:
                page.wait_for_url("**/resultado/**", timeout=15000)
            except Exception:
                pass
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1500)

            # 3) Extrair referência do mês (Cobrança de Fevereiro)
            reference_month = None
            ref_el = page.locator("div.resultados-entry__cell.title").first
            if ref_el.count() > 0:
                reference_month = ref_el.inner_text().strip()

            # 4) Extrair valor
            valor = None
            valor_el = page.locator("div.resultados-entry__cell.amount").first
            if valor_el.count() > 0:
                texto = valor_el.inner_text()
                m = re.search(r"R\$\s*([\d.,]+)", texto)
                if m:
                    try:
                        valor = Decimal(m.group(1).replace(".", "").replace(",", "."))
                    except Exception:
                        valor = None

            # 5) Extrair vencimento
            data_vencimento = None
            venc_el = page.locator("div.resultados-entry__cell.due-date").first
            if venc_el.count() > 0:
                texto = venc_el.inner_text().strip()
                try:
                    data_vencimento = datetime.strptime(texto, "%d/%m/%Y").date()
                except Exception:
                    pass

            # 6) Extrair status
            status = ""
            status_el = page.locator("span.resultados-status-chip").first
            if status_el.count() > 0:
                status = status_el.inner_text().strip()

            # 7) Clicar seta para expandir (mostrar Gerar Pix etc)
            arrow_el = page.locator("svg.resultados-entry__icon").first
            if arrow_el.count() > 0:
                arrow_el.click(timeout=5000)
                page.wait_for_timeout(1500)

            # 8) Clicar Gerar Pix
            codigo_pix = None
            try:
                page.locator("#desktop-generate-pix").click(timeout=5000)
                page.wait_for_timeout(2000)

                # 9) Clicar Copiar Código e ler clipboard
                page.locator("#pixCopyButton").click(timeout=3000)
                page.wait_for_timeout(500)
                codigo_pix = page.evaluate(
                    """async () => {
                    try { return await navigator.clipboard.readText(); } catch (e) { return null; }
                }"""
                )
            except Exception as e:
                print(f"[SEGUNDA-VIA] Erro ao obter PIX: {e}")

            # 10) Clicar em Boleto (aba/opção de pagamento) -> Gerar boleto -> Copiar código de barras
            codigo_barras = None
            try:
                page.locator(".desktop-payment__item-title").filter(has_text="Boleto").first.click(timeout=5000)
                page.wait_for_timeout(1500)
                page.locator("#desktop-generate-boleto").click(timeout=5000)
                page.wait_for_timeout(2000)
                page.locator("#barCodeCopyButton").click(timeout=3000)
                page.wait_for_timeout(500)
                codigo_barras = page.evaluate(
                    """async () => {
                    try { return await navigator.clipboard.readText(); } catch (e) { return null; }
                }"""
                )
            except Exception as e:
                print(f"[SEGUNDA-VIA] Erro ao obter boleto/código de barras: {e}")

            # 11) PDF: como um humano — "imprimir" a página atual (valor, código de barras, vencimento visíveis)
            #    em vez de confiar no botão Download (que pode devolver PDF zerado/template do servidor).
            #    Fluxo: garantir área do boleto visível -> emular mídia de impressão -> page.pdf() -> salvar.
            pdf_path = None
            pdf_validado_nesta_execucao = False
            if incluir_pdf:
                downloads_dir = os.path.join(settings.BASE_DIR, "downloads")
                os.makedirs(downloads_dir, exist_ok=True)
                ddmmaaaa = data_vencimento.strftime("%d%m%Y") if data_vencimento else datetime.now().strftime("%d%m%Y")
                filename = f"{cpf_limpo}_{ddmmaaaa}.pdf"
                pdf_path = os.path.join(downloads_dir, filename)
                pdf_por_impressao_ok = False
                pdf_validado_nesta_execucao = False  # só anexar se geramos e validamos (pypdf) nesta execução

                # --- Diagnóstico: logar todas as respostas PDF da rede (URL e tamanho) ---
                pdf_respostas_diag = []

                def _on_response(response):
                    try:
                        ct = (response.headers.get("content-type") or "").lower()
                        if "application/pdf" in ct:
                            url = response.url
                            body = response.body()
                            size = len(body) if body else 0
                            pdf_respostas_diag.append({"url": url[:120], "size": size, "ok": body and body[:4] == b"%PDF"})
                            if body and size > 500 and body[:4] == b"%PDF":
                                cur = getattr(_on_response, "_captured", None)
                                if cur is None or size > len(cur):
                                    _on_response._captured = body
                    except Exception:
                        pass

                _on_response._captured = None
                page.on("response", _on_response)

                # --- Estratégia 1 (principal): PDF por impressão da página atual (como Ctrl+P -> Salvar como PDF) ---
                # O conteúdo do PDF está em #invoice-area (.download-contas), preenchido só ao clicar em #downloadInvoice.
                # Ver docs/INSPECAO_PDF_NIO_DEVTOOLS.md. Na página há vários #downloadInvoice (Pix/Boleto); usar o do Boleto.
                try:
                    # Preferir o botão Download dentro da área de detalhes do agendamento (contexto Boleto)
                    download_btn = page.locator("#scheduled-payment__details #downloadInvoice").first
                    try:
                        download_btn.wait_for(state="visible", timeout=4000)
                    except Exception:
                        download_btn = page.locator("#downloadInvoice").first
                    # Garantir que estamos na área do boleto e o botão Download está visível (pode estar em modal/aba)
                    for selector in ["#barCodeCopyButton", "#downloadInvoice"]:
                        try:
                            page.locator(selector).first.scroll_into_view_if_needed(timeout=3000)
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                    # Esperar o botão Download ficar visível (evita "element is not visible")
                    try:
                        download_btn.wait_for(state="visible", timeout=8000)
                    except Exception:
                        pass
                    # Tornar o botão visível se estiver em container oculto (ex.: overflow no modal)
                    try:
                        page.evaluate("""() => {
                            const inDetails = document.querySelector('#scheduled-payment__details #downloadInvoice');
                            const el = inDetails || document.querySelector('#downloadInvoice');
                            if (el) { el.scrollIntoView({ block: 'center' }); }
                        }""")
                        page.wait_for_timeout(400)
                    except Exception:
                        pass
                    # Neutralizar window.print para não abrir o diálogo de impressão ao clicar
                    page.evaluate("window.print = function() {}")
                    # Clicar em Download: isso chama populateInvoice() e preenche #invoice-area (valor, vencimento, código de barras)
                    download_btn.click(timeout=5000)
                    # Esperar o canvas do código de barras ser desenhado (evita PDF corrompido/inválido)
                    try:
                        page.wait_for_function(
                            "() => { const c = document.querySelector('#barcode-canvas'); return c && c.width > 0 && c.height > 0; }",
                            timeout=5000,
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(800)
                    # Emular mídia de impressão e gerar o PDF (a área #invoice-area já está preenchida)
                    page.emulate_media(media="print")
                    page.wait_for_timeout(2000)
                    for prefer_css in (True, False):  # tentar com e sem prefer_css_page_size (evita PDF corrompido)
                        if pdf_por_impressao_ok:
                            break
                        try:
                            page.pdf(
                                path=pdf_path,
                                print_background=True,
                                prefer_css_page_size=prefer_css,
                            )
                        except Exception:
                            continue
                        if os.path.exists(pdf_path):
                            sz = os.path.getsize(pdf_path)
                            with open(pdf_path, "rb") as f:
                                header = f.read(4)
                            if sz > 3000 and header == b"%PDF" and _pdf_is_openable(pdf_path):
                                pdf_por_impressao_ok = True
                                pdf_validado_nesta_execucao = True
                                print(f"[SEGUNDA-VIA] PDF gerado por impressão (prefer_css={prefer_css}): {sz} bytes, validado (pypdf)")
                                break
                            elif sz > 3000 and header == b"%PDF":
                                print(f"[SEGUNDA-VIA] PDF por impressão rejeitado (prefer_css={prefer_css}, não abre no pypdf), tentando outra opção")
                        else:
                            break
                    page.emulate_media(media="screen")
                    if not pdf_por_impressao_ok and os.path.exists(pdf_path):
                        with open(pdf_path, "rb") as f:
                            header = f.read(4)
                        sz = os.path.getsize(pdf_path)
                        if sz <= 3000 or header != b"%PDF":
                            print(f"[SEGUNDA-VIA] PDF por impressão inválido (size={sz}, header={header})")
                except Exception as e:
                    print(f"[SEGUNDA-VIA] PDF por impressão falhou: {e}")

                # --- Estratégia 2: se impressão não deu PDF válido, tentar download + rede ---
                if not pdf_por_impressao_ok:
                    try:
                        dl_btn = page.locator("#scheduled-payment__details #downloadInvoice").first
                        try:
                            dl_btn.wait_for(state="visible", timeout=3000)
                        except Exception:
                            dl_btn = page.locator("#downloadInvoice").first
                        with page.expect_download(timeout=15000) as dl_info:
                            dl_btn.click(timeout=5000)
                        download = dl_info.value
                        download.save_as(pdf_path)
                        page.wait_for_timeout(2500)
                    except Exception as e:
                        print(f"[SEGUNDA-VIA] Download pelo botão falhou: {e}")
                        page.wait_for_timeout(2000)

                    # Diagnóstico: imprimir o que a rede recebeu
                    for r in pdf_respostas_diag:
                        print(f"[SEGUNDA-VIA] [DIAG] PDF rede: url={r['url']}... size={r['size']} ok={r['ok']}")

                    size_downloaded = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
                    valid_download = False
                    if os.path.exists(pdf_path) and size_downloaded > 0:
                        try:
                            with open(pdf_path, "rb") as f:
                                valid_download = size_downloaded > 5000 and f.read(4) == b"%PDF"
                        except Exception:
                            pass
                    net_body = _on_response._captured
                    net_ok = net_body and len(net_body) > 5000 and net_body[:4] == b"%PDF"
                    if net_ok and (not valid_download or len(net_body) > size_downloaded):
                        with open(pdf_path, "wb") as f:
                            f.write(net_body)
                        print(f"[SEGUNDA-VIA] PDF usado da rede: {len(net_body)} bytes")
                    elif not valid_download and net_ok:
                        with open(pdf_path, "wb") as f:
                            f.write(net_body)
                        print(f"[SEGUNDA-VIA] Download inválido, usando PDF da rede: {len(net_body)} bytes")
                    elif not valid_download and not net_ok:
                        # Último recurso: page.pdf() sem emular print (já tentamos com print acima)
                        try:
                            page.locator("#barCodeCopyButton").first.scroll_into_view_if_needed(timeout=2000)
                            page.wait_for_timeout(500)
                            page.pdf(path=pdf_path, print_background=True)
                            if os.path.getsize(pdf_path) > 3000:
                                print(f"[SEGUNDA-VIA] PDF fallback page.pdf() (sem mídia print)")
                            else:
                                pdf_path = None
                        except Exception as e:
                            print(f"[SEGUNDA-VIA] PDF não gerado: {e}")
                            pdf_path = None

                    # Validar com pypdf: só anexar se o PDF abrir corretamente (evita "Não é possível abrir este arquivo")
                    if pdf_path and os.path.exists(pdf_path):
                        if _pdf_is_openable(pdf_path):
                            pdf_validado_nesta_execucao = True
                            print(f"[SEGUNDA-VIA] PDF Estratégia 2 validado (pypdf)")
                        else:
                            print(f"[SEGUNDA-VIA] PDF Estratégia 2 descartado (arquivo corrompido/não abre)")
                            pdf_path = None

            browser.close()

            invoice = {
                "amount": float(valor) if valor else None,
                "due_date_raw": data_vencimento.strftime("%Y-%m-%d") if data_vencimento else None,
                "data_vencimento": data_vencimento.strftime("%Y-%m-%d") if data_vencimento else None,
                "status": status or "EM ABERTO",
                "pix": codigo_pix,
                "codigo_pix": codigo_pix,
                "barcode": codigo_barras,
                "codigo_barras": codigo_barras,
                "reference_month": reference_month,
                "source": "segunda_via_site",
            }
            if pdf_path and os.path.exists(pdf_path) and pdf_validado_nesta_execucao:
                invoice["pdf_path"] = pdf_path
                invoice["pdf_filename"] = os.path.basename(pdf_path)

            return [invoice]

    except Exception as e:
        print(f"[SEGUNDA-VIA] Erro: {e}")
        import traceback
        traceback.print_exc()
        return []


def buscar_pdf_url_nio(cpf, debt_id, invoice_id, api_base, token, session_id):
    """
    Busca APENAS a URL do PDF usando Playwright com tokens da API.
    Injeta os tokens para pular captcha e navega pelo fluxo normal.
    
    Args:
        cpf: CPF do cliente
        debt_id: ID da dívida (da API)
        invoice_id: ID da invoice (da API)
        api_base: Base URL da API
        token: Token de autorização
        session_id: ID da sessão
    
    Returns:
        URL do PDF ou None
    """
    if not HAS_PLAYWRIGHT:
        return None
    
    try:
        from playwright.sync_api import sync_playwright
        
        print(f"🔍 [PDF] Buscando PDF via Playwright + API tokens para CPF: {cpf}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # Usa storage_state se disponível
            state_path = DEFAULT_STORAGE_STATE if os.path.exists(DEFAULT_STORAGE_STATE) else None
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800},
                storage_state=state_path,
                accept_downloads=True,
            )
            
            page = context.new_page()
            
            # Vai para a página inicial
            print(f"🔍 [PDF] Navegando para página inicial...")
            page.goto(f"{NIO_BASE_URL}/negociar", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1000)
            
            # Injeta os tokens da API no localStorage
            print(f"🔑 [PDF] Injetando tokens da API no navegador...")
            page.evaluate(f"""
                localStorage.setItem('token', '{token}');
                localStorage.setItem('apiServerUrl', '{api_base}');
                localStorage.setItem('sessionId', '{session_id}');
            """)
            
            # Recarrega para aplicar os tokens
            page.reload(wait_until="networkidle", timeout=10000)
            page.wait_for_timeout(1500)
            
            # Preenche o CPF e consulta
            print(f"🔍 [PDF] Consultando CPF...")
            page.locator('input[type="text"]').first.fill(cpf)
            page.wait_for_timeout(500)
            
            # O botão pode estar habilitado agora por causa dos tokens
            page.locator('button:has-text("Consultar")').first.click(timeout=10000)
            page.wait_for_timeout(2000)
            page.wait_for_load_state("networkidle", timeout=15000)
            
            # Clica em "ver detalhes" se existir
            ver_detalhes = page.locator('text=/ver detalhes/i').first
            if ver_detalhes.count() > 0:
                ver_detalhes.click()
                page.wait_for_timeout(1000)
            
            # Clica em "Pagar conta"
            print(f"🔍 [PDF] Navegando para página de pagamento...")
            page.locator('button:has-text("Pagar conta")').first.click(timeout=10000)
            page.wait_for_url('**/payment**', timeout=15000)
            page.wait_for_timeout(1500)
            
            # Clica em "Gerar boleto"
            print(f"🔍 [PDF] Gerando boleto...")
            page.locator('div[data-context="btn_container_gerar-boleto"]').first.click(timeout=10000)
            page.wait_for_url('**/paymentbillet**', timeout=10000)
            page.wait_for_timeout(1500)
            
            # Captura o PDF
            print(f"🔍 [PDF] Capturando link do PDF...")
            pdf_url = None
            with context.expect_page(timeout=10000) as popup_info:
                page.locator('text="Baixar PDF"').first.click()
            pdf_page = popup_info.value
            pdf_page.wait_for_load_state('networkidle', timeout=5000)
            pdf_url = pdf_page.url
            print(f'✅ [PDF] Link capturado: {pdf_url[:100]}...')
            pdf_page.close()
            
            browser.close()
            return pdf_url
                
    except Exception as e:
        print(f"❌ [PDF] Erro: {e}")
        import traceback
        traceback.print_exc()
        return None


def _buscar_fatura_playwright(cpf: str):
    """Fluxo headless replicando o script test_nio_completo.py"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        state_path = DEFAULT_STORAGE_STATE if os.path.exists(DEFAULT_STORAGE_STATE) else None
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
            storage_state=state_path,
            accept_downloads=True,
        )

        page = context.new_page()
        page.goto(NIO_BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        page.locator('input[type="text"]').first.fill(cpf)
        page.locator('button:has-text("Consultar")').first.click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle", timeout=20000)

        ver_detalhes = page.locator('text=/ver detalhes/i').first
        if ver_detalhes.count() > 0:
            ver_detalhes.click()
            page.wait_for_timeout(800)

        html_expandido = page.content()
        vencimento = None
        m = re.search(r'(\d{2}/\d{2}/\d{4})', html_expandido)
        if m:
            try:
                vencimento = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            except Exception:
                pass

        pagar_btn = page.locator('button:has-text("Pagar conta")').first
        pagar_btn.click()
        page.wait_for_url('**/payment**', timeout=15000)
        page.wait_for_timeout(1200)

        html_pagto = page.content()
        valor = None
        vm = re.search(r'R\$\s*&nbsp;\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_pagto, re.IGNORECASE)
        if not vm:
            vm = re.search(r'R\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_pagto, re.IGNORECASE)
        if vm:
            try:
                valor = Decimal(vm.group(1).replace('.', '').replace(',', '.'))
            except Exception:
                pass

        # PIX
        page.locator('div[data-context="btn_container_pagar-online"]').first.click()
        page.wait_for_url('**/paymentpix**', timeout=12000)
        page.wait_for_timeout(1200)
        html_pix = page.content()
        pix_matches = re.findall(r'00020126[0-9a-zA-Z]{100,}', html_pix)
        if not pix_matches:
            pix_matches = re.findall(r'[a-zA-Z0-9]{80,150}', html_pix)
        codigo_pix = pix_matches[0] if pix_matches else None

        # Volta para payment
        page.go_back()
        page.wait_for_url('**/payment**', timeout=12000)
        page.wait_for_timeout(800)

        # Boleto
        page.locator('div[data-context="btn_container_gerar-boleto"]').first.click()
        page.wait_for_url('**/paymentbillet**', timeout=12000)
        page.wait_for_timeout(1200)
        html_boleto = page.content()

        codigo_barras = None
        codigos = re.findall(r'\b(\d{44,50})\b', html_boleto)
        if codigos:
            preferidos = [c for c in codigos if c.startswith('0339')]
            codigo_barras = preferidos[0] if preferidos else codigos[0]

        # PDF - Captura o link quando abre o popup (na página do boleto)
        pdf_url = None
        try:
            print('🔍 [PDF] Tentando capturar link do PDF...')
            with context.expect_page(timeout=10000) as popup_info:
                page.locator('text="Baixar PDF"').first.click()
            pdf_page = popup_info.value
            pdf_page.wait_for_load_state('networkidle', timeout=5000)
            pdf_url = pdf_page.url
            print(f'✅ [PDF] Link capturado com sucesso: {pdf_url}')
            pdf_page.close()
        except Exception as e:
            print(f'⚠️ [PDF] Erro ao capturar link do PDF: {e}')
            import traceback
            traceback.print_exc()

        browser.close()

        return {
            'valor': valor,
            'codigo_pix': codigo_pix,
            'codigo_barras': codigo_barras,
            'data_vencimento': vencimento,
            'pdf_url': pdf_url,
        }


def _baixar_pdf_como_humano(
    cpf: str,
    mes_ref: str = "",
    data_venc: str = "",
    headless: Optional[bool] = None,
    api_base: Optional[str] = None,
    token: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Abre o site Nio Negociar, consulta o CPF, vai até a tela do boleto e baixa o PDF.
    Se api_base/token/session_id forem passados, injeta no localStorage (o site pode
    habilitar o botão Consultar quando já tem sessão; mesmo assim a página exige
    reCAPTCHA "Não sou um robô", que o sistema não resolve — use a API do PDF quando
    possível). Retorna dict com local_path, onedrive_url e filename, ou None em caso de falha.

    Args:
        cpf: CPF apenas números
        mes_ref: Mês de referência (ex: 202501)
        data_venc: Data de vencimento (informativo)
        headless: Se None, usa settings.PAP_HEADLESS
        api_base: URL base da API (para injetar na página)
        token: Token de autorização (para injetar)
        session_id: Session ID (para injetar)
    """
    if not HAS_PLAYWRIGHT or not sync_playwright:
        print("[PDF] Playwright não disponível. Instale: pip install playwright && playwright install chromium")
        return None

    if headless is None:
        headless = getattr(settings, "PAP_HEADLESS", True)

    # Pasta para salvar PDFs (mesma que outros downloads do projeto)
    downloads_dir = os.path.join(settings.BASE_DIR, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    safe_cpf = (cpf or "")[:8]
    safe_ref = (mes_ref or "").replace("/", "")[:6]
    filename = f"fatura_{safe_cpf}_{safe_ref}.pdf" if safe_ref else f"fatura_{safe_cpf}.pdf"
    local_path = os.path.join(downloads_dir, filename)

    inject_tokens = bool(api_base and token and session_id)
    print(f"[PDF] Debug: inject_tokens={inject_tokens}, api_base_len={len(api_base or '')}, token_len={len(token or '')}, session_id_len={len(session_id or '')}")

    try:
        with _pdf_download_lock:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)

                state_path = DEFAULT_STORAGE_STATE if os.path.exists(DEFAULT_STORAGE_STATE) else None
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    viewport={"width": 1280, "height": 800},
                    storage_state=state_path,
                    accept_downloads=True,
                )

                page = context.new_page()
                # load é mais estável que networkidle (evita timeout em páginas com polling)
                page.goto(f"{NIO_BASE_URL}/negociar", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                if inject_tokens:
                    # Injetar token/session para habilitar o botão Consultar (como em buscar_pdf_url_nio)
                    print("[PDF] Injetando token, apiServerUrl e sessionId no localStorage...")
                    try:
                        js = (
                            "() => { "
                            "localStorage.setItem('token', " + json.dumps(token) + "); "
                            "localStorage.setItem('apiServerUrl', " + json.dumps(api_base) + "); "
                            "localStorage.setItem('sessionId', " + json.dumps(session_id) + "); "
                            "}"
                        )
                        page.evaluate(js)
                        print("[PDF] localStorage injetado. Recarregando página...")
                    except Exception as e:
                        print(f"[PDF] Erro ao injetar localStorage: {e}")
                    page.reload(wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2500)

                # Preencher CPF e clicar em Consultar
                page.locator('input[type="text"]').first.fill(cpf)
                page.wait_for_timeout(800)
                # A página Nio exige reCAPTCHA "Não sou um robô"; resolver via API (CapSolver/2captcha) se configurado
                try:
                    page.wait_for_selector('button:has-text("Consultar"):not([disabled])', timeout=5000)
                    print("[PDF] Botão Consultar já habilitado.")
                except Exception:
                    if _resolver_recaptcha_nio(page):
                        page.wait_for_timeout(2000)
                    try:
                        page.wait_for_selector('button:has-text("Consultar"):not([disabled])', timeout=8000)
                        print("[PDF] Botão Consultar habilitado após reCAPTCHA.")
                    except Exception:
                        print("[PDF] Botão Consultar ainda disabled (reCAPTCHA não resolvido ou callback não acionado).")
                # Fallback: se o botão ainda estiver disabled (ex.: React não acionou callback), forçar habilitação e clique
                try:
                    still_disabled = page.evaluate("""() => {
                        const btn = Array.from(document.querySelectorAll('button')).find(b => (b.textContent || '').includes('Consultar'));
                        if (btn && btn.disabled) { btn.disabled = false; btn.removeAttribute('disabled'); return true; }
                        return false;
                    }""")
                    if still_disabled:
                        print("[PDF] Fallback: botão Consultar forçado como habilitado via JS.")
                except Exception:
                    pass
                page.locator('button:has-text("Consultar")').first.click(timeout=15000, force=True)
                page.wait_for_timeout(5000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)

                # Diagnóstico: o que apareceu na página após Consultar (para você ajustar selectors se precisar)
                try:
                    diag_page = page.evaluate("""() => {
                        const buttons = Array.from(document.querySelectorAll('button, [role="button"], a[href]')).map(el => (el.textContent || '').trim().slice(0, 50));
                        const dataCtx = Array.from(document.querySelectorAll('[data-context]')).map(el => el.getAttribute('data-context'));
                        return { url: window.location.href, buttons: buttons.filter(Boolean), dataContext: dataCtx };
                    }""")
                    url_atual = diag_page.get("url", "")
                    print(f"[PDF] Após Consultar — URL: {url_atual[:90]}...")
                    print(f"[PDF] Botões/links (amostra): {diag_page.get('buttons', [])[:15]}")
                    print(f"[PDF] data-context na página: {diag_page.get('dataContext', [])[:20]}")
                    if "/negociar" in url_atual and "payment" not in url_atual:
                        print("[PDF] Dica: URL ainda em /negociar — o backend pode ter rejeitado o reCAPTCHA; a lista acima mostra o que está visível.")
                except Exception:
                    pass

                # Ver detalhes (se houver mais de uma fatura)
                sel_ver_detalhes = _selector("VER_DETALHES", 'text=/ver detalhes/i')
                ver_detalhes = page.locator(sel_ver_detalhes).first
                if ver_detalhes.count() > 0:
                    ver_detalhes.click()
                    page.wait_for_timeout(1000)

                # Pagar conta: selector configurável + alternativas
                sel_pagar = _selector("PAGAR_CONTA", 'button:has-text("Pagar conta")')
                pagar_clicked = False
                for sel in [sel_pagar, 'button:has-text("Pagar conta")', 'div[data-context="btn_container_pagar-online"]', '[data-context*="pagar"]', 'text=/pagar conta/i', 'text=/pagar/i']:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0:
                            loc.click(timeout=8000)
                            pagar_clicked = True
                            print(f"[PDF] Clique em 'Pagar conta' com seletor: {sel[:60]}...")
                            break
                    except Exception as e:
                        continue
                if not pagar_clicked:
                    print("[PDF] Nenhum seletor encontrou 'Pagar conta'. Defina NIO_PDF_SELECTOR_PAGAR_CONTA no .env (ex.: button:has-text(\"Pagar conta\") ou div[data-context=\"btn_container_pagar-online\"]).")
                    raise RuntimeError("Botão/link 'Pagar conta' não encontrado. Ver log [PDF] Após Consultar para ajustar selector.")
                page.wait_for_url("**/payment**", timeout=15000)
                page.wait_for_timeout(1200)

                # Gerar boleto
                sel_gerar = _selector("GERAR_BOLETO", 'div[data-context="btn_container_gerar-boleto"]')
                page.locator(sel_gerar).first.click(timeout=10000)
                page.wait_for_url("**/paymentbillet**", timeout=12000)
                page.wait_for_timeout(1500)

                # Baixar PDF
                sel_baixar = _selector("BAIXAR_PDF", 'text="Baixar PDF"')
                pdf_url = None
                try:
                    with context.expect_page(timeout=15000) as popup_info:
                        page.locator(sel_baixar).first.click()
                    pdf_page = popup_info.value
                    pdf_page.wait_for_load_state("load", timeout=15000)
                    page.wait_for_timeout(1000)
                    pdf_url = pdf_page.url
                    print(f"[PDF] URL do PDF: {pdf_url[:100]}...")
                    if pdf_url and ".pdf" in pdf_url:
                        try:
                            resp = context.request.get(pdf_url, timeout=15000)
                            if resp and resp.status == 200:
                                body = resp.body()
                                with open(local_path, "wb") as f:
                                    f.write(body)
                                print(f"[PDF] Salvo em: {local_path}")
                        except Exception as e:
                            print(f"[PDF] Playwright request falhou ({e}), tentando requests...")
                        if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
                            r = requests.get(pdf_url, timeout=15)
                            if r.status_code == 200:
                                with open(local_path, "wb") as f:
                                    f.write(r.content)
                                print(f"[PDF] Salvo em: {local_path}")
                    pdf_page.close()
                except Exception as e:
                    print(f"[PDF] Erro ao obter PDF (popup/download): {e}")
                    import traceback
                    traceback.print_exc()

                browser.close()

                if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                    return {
                        "local_path": local_path,
                        "onedrive_url": None,
                        "filename": filename,
                    }
                if pdf_url:
                    return {
                        "local_path": None,
                        "onedrive_url": pdf_url,
                        "filename": filename,
                    }
                return None
    except Exception as e:
        print(f"[PDF] Erro em _baixar_pdf_como_humano: {e}")
        import traceback
        traceback.print_exc()
        return None
