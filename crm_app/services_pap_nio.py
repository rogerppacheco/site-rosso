# crm_app/services_pap_nio.py
"""
Serviço de automação para vendas no PAP Nio via Playwright.
Permite que vendedores autorizados realizem vendas pelo WhatsApp.
"""

import base64
import os
import re
import unicodedata
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from django.conf import settings

logger = logging.getLogger(__name__)

# Tentar importar Playwright
try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.warning("[PAP NIO] Playwright não instalado. Automação PAP desabilitada.")

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

PAP_LOGIN_URL = "https://pap.niointernet.com.br/"
PAP_VTAL_LOGIN_URL = "https://login.vtal.com/nidp/saml2/sso"
PAP_NOVO_PEDIDO_URL = "https://pap.niointernet.com.br/administrativo/novo-pedido"
PAP_CONSULTA_OS_URL = "https://pap.niointernet.com.br/administrativo/consulta-os"
DEFAULT_TIMEOUT = 30000  # 30 segundos
STORAGE_STATE_DIR = getattr(settings, 'PAP_SESSIONS_DIR', os.path.join(settings.BASE_DIR, 'pap_sessions'))

# Semáforo para limitar sessões PAP simultâneas (evita sobrecarga)
_pap_semaphore = threading.Semaphore(2)  # Máximo 2 sessões simultâneas

# =============================================================================
# SELETORES DO SITE PAP NIO
# =============================================================================

SELETORES = {
    # Login Vtal (IDs podem mudar; fallbacks por placeholder/type)
    'login': {
        'matricula': '#inputMatricula, input[placeholder*="Login"], input[name*="matricula"], input[name*="username"], input[name*="login"], input[type="text"]:not([type="search"])',
        'senha': '#passwordInput, input[placeholder*="Senha"], input[placeholder*="OTP"], input[name*="password"], input[name*="senha"], input[type="password"]',
        'btn_login': 'button:has-text("EFETUAR"), button:has-text("Login"), button[type="submit"]',
    },
    
    # Etapa 1: Identificação PDV
    'etapa1': {
        'uf': 'input[placeholder*="UF"]',
        'pdv': 'input[placeholder*="PDV"]',
        # Campo de busca do vendedor: o PAP já mudou placeholder (ex.: só "Vendedor"); manter lista ampla.
        'matricula_vendedor': 'input[placeholder*="matrícula"]',
        'lista_vendedores': 'li',
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 2: Consulta de Viabilidade
    'etapa2': {
        'cep': 'input[placeholder=" "]',
        'numero': 'input[type="number"]',
        'sem_numero': 'input[type="checkbox"]',
        'btn_buscar': 'button:has-text("Buscar")',
        'endereco_instalacao': 'input[placeholder="Endereço de instalação"]',
        'endereco_resultado': 'input[disabled]',
        'lista_enderecos': 'li',
        'referencia': 'input[name="referencia"], input[placeholder*="referência"], input[placeholder*="Referência"], input[placeholder*="referencia"], textarea[placeholder*="referência"], textarea[placeholder*="Referência"]',
        'complementos': 'ul[class*="fQkuQJ"] li, ul[class*="cUdcXF"] li, input[placeholder*="omplemento"] ~ ul li, div:has(input[placeholder*="omplemento"]) ul li',
        'sem_complemento': '#semComplemento, input[id="semComplemento"], label[for="semComplemento"]',
        'btn_avancar': 'button:has-text("Avançar")',
        'btn_continuar_modal': 'button:has-text("Continuar")',
    },
    
    # Etapa 3: Cadastro do Cliente
    'etapa3': {
        'cpf': 'input[name="documento"]',
        'btn_buscar': 'button:has-text("Buscar")',
        'nome_cliente': 'input[disabled][value], input[name*="nome"]',  # Nome vem preenchido
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 4: Contato (campos: name contato, confirmacaoContato, contatoSecundario, email, confirmarEmail)
    'etapa4': {
        'celular_principal': 'input#contato, input[name="contato"]',
        'confirmar_celular': 'input#confirmacaoContato, input[name="confirmacaoContato"]',
        'celular_secundario': 'input#contatoSecundario, input[name="contatoSecundario"]',
        'email': 'input#email, input[name="email"]',
        'confirmar_email': 'input#confirmarEmail, input[name="confirma-email"]',
        'resultado_credito': '.resultado-credito, [class*="credito"], [class*="analise"]',
        'btn_continuar': 'button:has-text("Continuar")',
        'btn_avancar': 'button:has-text("Avançar")',
        'modal_atencao': 'h2:has-text("Atenção!")',
        'btn_modal_ok': 'button:has-text("Ok")',
    },
    
    # Etapa 5: Pagamento/Ofertas (values: BOLETO, CREDITO, DACC)
    'etapa5': {
        'forma_boleto': 'input[value="BOLETO"], label:has-text("Boleto")',
        'forma_cartao': 'input[value="CREDITO"], label:has-text("Cartão de Crédito")',
        'forma_debito': 'input[value="DACC"], label:has-text("Débito em Conta")',
        'banco_input': 'input[placeholder*="Selecione o Banco"], input[placeholder*="Banco"]',
        'agencia': 'input[name="agencia"]',
        'conta': 'input[name="conta"]',
        'digito': 'input[name="digito"]',
        'plano_1giga': 'label:has-text("1 Giga"), [class*="card"]:has-text("1 Giga")',
        'plano_700mega': 'label:has-text("700 Mega"), [class*="card"]:has-text("700 Mega")',
        'plano_500mega': 'label:has-text("500 Mega"), [class*="card"]:has-text("500 Mega")',
        'btn_servicos': 'button:has-text("Serviços disponíveis")',
        'card_fixo': 'div.sc-kUQWMX.bwZXDo:has-text("Fixo"), div.bwZXDo:has-text("Fixo"), div.sc-dcmekm.dBGnOE:has-text("Fixo")',
        'btn_fechar_modal_x': 'button:has(svg path[d*="M19 6.41"]), button[aria-label="Close"], button[aria-label="Fechar"]',
        'btn_streaming': 'button:has-text("Streaming e canais on-line")',
        'opcao_hbomax': 'div:has-text("HBO Max") div.sc-jIyBzM.bSKio, div:has-text("HBO Max") img',
        'opcao_globoplay_premium': 'div:has-text("Plano Premium"):not(:has-text("Padrão")) div.sc-jIyBzM.bSKio, div:has-text("Plano Premium") div.sc-jIyBzM img',
        'opcao_globoplay_basico': 'div:has-text("Plano Padrão com Anúncios") div.sc-jIyBzM.bSKio, div:has-text("Plano Padrão") div.sc-jIyBzM img',
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 6: Resumo
    'etapa6': {
        'status_biometria': '[class*="biometria"], [class*="status"]',
        'btn_abrir_os': 'button:has-text("Abrir OS"), button:has-text("Abrir O.S")',
    },
    
    # Etapa 7: Agendamento
    'etapa7': {
        'calendario': '[class*="calendario"], [class*="calendar"]',
        'data_disponivel': '[class*="disponivel"], [class*="available"]',
        'turno_manha': 'input[value*="manha"], label:has-text("Manhã")',
        'turno_tarde': 'input[value*="tarde"], label:has-text("Tarde")',
        'btn_confirmar': 'button:has-text("Confirmar")',
    },

    # Consulta OS (menu lateral e tela de filtros)
    'consulta_os': {
        'menu_consulta_os': 'a[href*="consulta-os"], span:has-text("Consulta OS"), div.sc-kAzzGY:has(img), [class*="sc-kAzzGY"]',
        'filtros': 'span.titulo-filtro:has-text("Filtros"), .titulo-filtro, span:has-text("Filtros")',
        'input_cpf_cnpj': 'input.input-text-filter[placeholder="Digite o CPF/CNPJ..."], input.input-text-filter',
        'btn_filtrar': 'button.btn-filters-new, button:has-text("Filtrar")',
        'periodo_de': 'input[placeholder*="De"], input[name*="dataInicio"], input[id*="periodo"], input[aria-label*="De"]',
        'periodo_ate': 'input[placeholder*="Até"], input[name*="dataFim"], input[id*="ate"]',
        'table_body_cells': 'td.MuiTableCell-root.MuiTableCell-body',
        'table_rows': 'table tbody tr, [class*="MuiTableBody"] tr',
        'link_detalhar': 'a.detalhar-link[href*="detalhe-os"]',
        'detalhe_status_agendamento': 'span.sc-jrOYZv.ldMRLh, span.ldMRLh',
    },
}

# Seletores OR para o campo "vendedor / matrícula" na etapa Novo Pedido (UI do PAP varia)
SELETORES_MATRICULA_VENDEDOR = [
    'input[placeholder*="matrícula"]',
    'input[placeholder*="matricula"]',
    'input[placeholder*="Matrícula"]',
    'input[placeholder*="vendedor"]',
    'input[placeholder*="Vendedor"]',
    'input[aria-label*="matrícula"]',
    'input[aria-label*="matricula"]',
    'input[aria-label*="vendedor"]',
    'input[aria-label*="Vendedor"]',
    'input[name*="vendedor"]',
    'input[name*="matricula"]',
    'input[id*="vendedor"]',
    'input[id*="matricula"]',
    'input[id*="Vendedor"]',
    'form input[type="search"]',
    '[class*="etapa"] input[type="search"]',
]

SELETORES_MATRICULA_VENDEDOR_CSS = ", ".join(SELETORES_MATRICULA_VENDEDOR)

# Dropdown de vendedor (MUI Autocomplete / portal React — estrutura varia no PAP)
SELETORES_LISTA_VENDEDOR_ITENS = [
    '[role="listbox"] [role="option"]',
    '[role="listbox"] li',
    'ul[role="listbox"] li',
    '.MuiAutocomplete-listbox [role="option"]',
    '.MuiAutocomplete-listbox li',
    '.MuiAutocomplete-popper [role="option"]',
    '.MuiAutocomplete-popper li',
    'div[id^="menu-"] [role="option"]',
    'div[id^="menu-"] li',
    'ul[class*="menu"] li',
    'ul[class*="dropdown"] li',
    'ul[class*="autocomplete"] li',
    'ul[class*="fQkuQJ"] li',
    'ul[class*="cUdcXF"] li',
    'li[class*="option"]',
    'div[role="option"]',
]

# Código retornado quando o modal "OPS, OCORREU UM ERRO!" aparece no PAP (erro do portal; orientar abrir chamado Nio)
PAP_ERRO_PORTAL_NIO = "PAP_ERRO_PORTAL_NIO"

# Fluxo CRÉDITO (parar_no_modal_credito): não concluir sem o modal "Resultado da análise de crédito" visível
# (evita falso "aprovado" se a etapa de pagamento carregar antes do modal).
MSG_CREDITO_SEM_TELA_RESULTADO = (
    "A tela com o resultado da consulta de crédito não foi exibida. "
    "Digite *CRÉDITO* e envie o CPF ou CNPJ novamente para repetir a consulta."
)

# Após reset do portal (ex.: modal "Ocorreu um erro" + Ok → Etapa 1), até qual subpasso reaplicar
# para alinhar o browser com a etapa atual do WhatsApp. Ver PAPNioAutomation.tentar_recuperar_portal_reset_etapa1.
# 0=só novo pedido (tela CEP); 1=viabilidade ok; 2=+CPF; 3=+contato; 4=+forma; 5=+débito se houver ou já em planos;
# 6=+plano; 7=+fixo; 8=+portabilidade fixo; 9=+streaming e Avançar até resumo.
WPP_ETAPA_REPLAY_TARGET_SN = {
    "venda_cep": 0,
    "venda_numero": 0,
    "venda_referencia": 0,
    "venda_selecionar_endereco": 1,
    "venda_selecionar_complemento": 1,
    "venda_posse_consultar_outro": 1,
    "venda_indisponivel_voltar": 1,
    "venda_corrigir_celular": 3,
    "venda_corrigir_email": 3,
    "venda_corrigir_cpf": 2,
    "venda_cpf": 1,
    "venda_celular": 2,
    "venda_celular_sec": 2,
    "venda_email": 3,
    "venda_forma_pagamento": 3,
    "venda_debito_banco": 4,
    "venda_debito_agencia": 4,
    "venda_debito_conta": 4,
    "venda_debito_digito": 4,
    "venda_plano": 5,
    "venda_fixo": 6,
    "venda_fixo_portabilidade": 7,
    "venda_fixo_portabilidade_numero": 7,
    "venda_fixo_portabilidade_operadora": 7,
    "venda_streaming": 8,
    "venda_streaming_opcoes": 8,
    "venda_confirmar": 9,
    "venda_aguardando_confirmacao": 9,
    "venda_aguardando_biometria": 9,
    "venda_aguardando_abrir_os": 9,
    "venda_agendamento_dia": 9,
    "venda_agendamento_confirmar_data": 9,
    "venda_agendamento_periodo": 9,
    "venda_agendamento_confirmar_turno": 9,
    "venda_agendamento_sim_agendar": 9,
    "venda_agendamento_final": 9,
}

# =============================================================================
# CLASSE PRINCIPAL DE AUTOMAÇÃO
# =============================================================================

class PAPNioAutomation:
    """
    Classe para automatizar vendas no PAP Nio.
    Cada instância representa uma sessão de venda.
    """
    
    def __init__(
        self,
        matricula_pap: str,
        senha_pap: str,
        vendedor_nome: str = None,
        headless: bool = True,
        capture_screenshots: bool = None,
        run_id: str = None,
        optimize_for_credit: bool = False,
        slow_mo: Optional[int] = None,
        record_trace: bool = False,
    ):
        """
        Inicializa a automação PAP.
        
        Args:
            matricula_pap: Matrícula do vendedor no PAP
            senha_pap: Senha + OTP do PAP
            vendedor_nome: Nome do vendedor (para logs)
            headless: Se False, abre o navegador visível (para testes)
            capture_screenshots: Se True, salva screenshot em cada etapa (produção). None = usa settings.PAP_CAPTURE_SCREENSHOTS
            run_id: Identificador da sessão (ex: sessao_id) para nomear os arquivos de screenshot
            optimize_for_credit: Reduz esperas fixas no fluxo de consulta de crédito
            slow_mo: Milissegundos entre ações do Playwright (None = 300 se headless False, 0 se headless)
            record_trace: Se True, grava trace Playwright (inspect em trace.playwright.dev) sem exigir todos os screenshots
        """
        self.matricula_pap = matricula_pap
        self.senha_pap = senha_pap
        self.vendedor_nome = vendedor_nome or matricula_pap
        self.headless = headless
        if capture_screenshots is None:
            try:
                from django.conf import settings
                capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
            except Exception:
                capture_screenshots = False
        self.capture_screenshots = capture_screenshots
        self.run_id = run_id or str(int(time.time()))
        self.optimize_for_credit = optimize_for_credit
        self.slow_mo = slow_mo
        self.record_trace = record_trace

        self.playwright = None  # sync_playwright instance; precisa .stop() para encerrar event loop
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        self.etapa_atual = 0
        self.dados_pedido: Dict[str, Any] = {}
        self.erros: list = []
        self.numero_pedido: Optional[str] = None
        
        # Estado da sessão
        self.logado = False
        self.sessao_iniciada = False
        self._pap_slot_held = False  # slot do semáforo global (liberar mesmo se login falhar antes de sessao_iniciada)
        self._trace_started = False  # Trace Playwright para inspecionar cliques em produção
        self._cache_matriculas_pap_dropdown: List[str] = []
        self._vendedores_api_matriculas: List[str] = []
        self._listener_vendedor_ativo: bool = False
        self._credito_apis_pos_avancar: set[str] = set()

        # Storage state para manter cookies
        self.storage_state_path = os.path.join(
            STORAGE_STATE_DIR, 
            f'pap_session_{self.matricula_pap}.json'
        )
    
    def _garantir_diretorio_sessoes(self):
        """Garante que o diretório de sessões existe"""
        os.makedirs(STORAGE_STATE_DIR, exist_ok=True)

    def _invalidar_storage_state(self) -> None:
        """Remove cookies salvos do BO (evita sessão fantasma que cai no IdP V.tal)."""
        try:
            if self.storage_state_path and os.path.exists(self.storage_state_path):
                os.remove(self.storage_state_path)
                logger.info("[PAP] Storage state invalidado: %s", self.storage_state_path)
        except OSError as exc:
            logger.warning("[PAP] Falha ao remover storage state: %s", exc)

    def _recriar_contexto_sem_storage(self) -> None:
        """Novo contexto sem cookies — após sessão expirada ou falha de login."""
        self._invalidar_storage_state()
        if self.page:
            try:
                self.page.close()
            except Exception:
                pass
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 960},
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(25000)

    def _capture_screenshot(
        self,
        step_name: str,
        wait_selector: str = None,
        wait_timeout_ms: int = 15000,
        *,
        forcar: bool = False,
    ) -> None:
        """
        Salva screenshot em downloads/ e opcionalmente R2.
        Por padrão só roda com capture_screenshots; use forcar=True em falhas quando
        PAP_SCREENSHOTS_R2 estiver ligado (ver _capture_screenshot_falha_etapa1).
        """
        from django.conf import settings
        pode = self.capture_screenshots or forcar
        if not pode or not self.page:
            return
        try:
            # Esperar elemento indicar que a tela está pronta (evita print do loading/spinner)
            if wait_selector:
                try:
                    self.page.wait_for_selector(wait_selector, state="visible", timeout=wait_timeout_ms)
                except Exception:
                    pass
            # Pequena pausa para a UI terminar de pintar (React/animations)
            self.page.wait_for_timeout(800)
            base_dir = getattr(settings, 'BASE_DIR', None)
            if not base_dir:
                return
            downloads_dir = os.path.join(base_dir, 'downloads')
            os.makedirs(downloads_dir, exist_ok=True)
            safe_run = str(self.run_id).replace(os.sep, '_').replace('..', '_')[:50]
            safe_step = re.sub(r'[^\w\-]', '_', step_name)[:40]
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"pap_venda_{safe_run}_{safe_step}_{ts}.png"
            filepath = os.path.join(downloads_dir, filename)
            self.page.screenshot(path=filepath, full_page=False)
            logger.info(f"[PAP] Screenshot salvo: {filename}")
            # Enviar para R2 se configurado
            if getattr(settings, 'PAP_SCREENSHOTS_R2', False):
                try:
                    from crm_app.cloudflare_r2_service import CloudflareR2Storage
                    folder = getattr(settings, 'PAP_R2_FOLDER', 'PAP_Screenshots')
                    with open(filepath, 'rb') as f:
                        uploader = CloudflareR2Storage()
                        web_url = uploader.upload_file(f, folder, filename)
                    logger.info(f"[PAP] Screenshot enviado ao R2: {web_url or filename}")
                except Exception as e_od:
                    logger.warning(f"[PAP] Erro ao enviar screenshot ao R2: {e_od}")
        except Exception as e:
            if "Execution context was destroyed" not in str(e) and "context was destroyed" not in str(e):
                logger.warning(f"[PAP] Erro ao salvar screenshot: {e}")

    def _capture_screenshot_falha_etapa1(self, step_name: str, wait_selector: str = None, wait_timeout_ms: int = 0) -> None:
        """
        Screenshot diagnóstico na Etapa 1 (novo pedido / vendedor).
        Grava se PAP_CAPTURE_SCREENSHOTS OU PAP_SCREENSHOTS_R2 estiver ativo
        (assim dá para só subir falhas ao R2 sem printar todas as etapas).
        """
        from django.conf import settings
        forcar = self.capture_screenshots or getattr(settings, "PAP_SCREENSHOTS_R2", False)
        self._capture_screenshot(step_name, wait_selector=wait_selector, wait_timeout_ms=wait_timeout_ms, forcar=forcar)

    def _highlight_element(self, selector_or_element, duration_ms: int = 800) -> None:
        """
        Destaca visualmente um elemento (outline vermelho) antes de um clique, para debug.
        Se capture_screenshots estiver ativo, tira screenshot após highlight para ver onde vai clicar.
        """
        if not self.page:
            return
        try:
            el = selector_or_element if hasattr(selector_or_element, 'evaluate') else self.page.query_selector(selector_or_element)
            if not el:
                return
            el.evaluate("""el => {
                el.dataset._pap_original_outline = el.style.outline || '';
                el.style.outline = '3px solid red';
                el.style.outlineOffset = '2px';
            }""")
            self.page.wait_for_timeout(duration_ms)
            if self.capture_screenshots:
                self._capture_screenshot("_highlight_clique", wait_selector=None, wait_timeout_ms=0)
            el.evaluate("""el => {
                el.style.outline = el.dataset._pap_original_outline || '';
                el.style.outlineOffset = '';
            }""")
        except Exception as e:
            logger.debug(f"[PAP] Highlight ignorado: {e}")

    def _set_valor_react(self, selector: str, valor: str) -> bool:
        """
        Define valor em campo React de forma que o estado seja atualizado.
        
        Args:
            selector: Seletor CSS do campo
            valor: Valor a ser definido
            
        Returns:
            True se sucesso, False se erro
        """
        try:
            self.page.evaluate(f'''
                (function() {{
                    const element = document.querySelector('{selector}');
                    if (!element) return false;
                    
                    // Método para React
                    const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
                    const prototype = Object.getPrototypeOf(element);
                    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
                    
                    if (valueSetter && valueSetter !== prototypeValueSetter) {{
                        prototypeValueSetter.call(element, '{valor}');
                    }} else if (valueSetter) {{
                        valueSetter.call(element, '{valor}');
                    }} else {{
                        element.value = '{valor}';
                    }}
                    
                    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    element.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    
                    return true;
                }})()
            ''')
            return True
        except Exception as e:
            logger.error(f"[PAP] Erro ao definir valor em {selector}: {e}")
            return False

    def _preencher_campo_formulario(self, selector: str, valor: str) -> bool:
        """
        Preenche campo do formulário PAP usando fill+Tab (dispara validação React do portal).
        Fallback para _set_valor_react quando fill falhar.
        """
        if not self.page:
            return False
        elemento = self.page.query_selector(selector)
        if not elemento or not elemento.is_visible():
            return False
        try:
            elemento.click(timeout=3000)
            elemento.fill(str(valor))
            self.page.keyboard.press("Tab")
            return True
        except Exception as exc:
            logger.debug(
                "[PAP] fill+Tab falhou em %s: %s — tentando _set_valor_react",
                selector,
                exc,
            )
            return self._set_valor_react(selector, valor)

    def _garantir_sessao_etapa_viabilidade(self) -> Tuple[bool, str]:
        """
        Garante sessão na etapa 2 sem recarregar novo-pedido quando o CEP já está visível.

        O goto de garantir_sessao_ativa descarta o pedido em andamento (volta à etapa 1).
        """
        if not self.page:
            return False, "Página não iniciada."
        if self._esta_no_idp_vtal() or self._sessao_expirada_detectada():
            return self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
        cep_el = self.page.query_selector(SELETORES['etapa2']['cep'])
        if cep_el and cep_el.is_visible() and self._sessao_pap_autenticada():
            return True, "Sessão ativa na etapa de viabilidade."
        return self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)

    def _pedido_nova_fibra_em_andamento(self) -> bool:
        """True quando a tela indica pedido Nova Fibra além da etapa 1 (identificação)."""
        if not self.page or not self._sessao_pap_autenticada():
            return False
        if self._etapa2_formulario_documento_visivel():
            return True
        if self._ainda_na_etapa4_contato():
            return True
        cep_el = self.page.query_selector(SELETORES['etapa2']['cep'])
        if cep_el and cep_el.is_visible():
            return True
        inp_contato = self.page.query_selector('input#contato, input[name="contato"]')
        if inp_contato and inp_contato.is_visible():
            return True
        for sel in (
            'h2:has-text("Disponível")',
            'h2:has-text("Indisponível")',
            'button:has-text("Continuar")',
        ):
            el = self.page.query_selector(sel)
            if el and el.is_visible():
                return True
        return False

    def _garantir_sessao_sem_descartar_pedido(self) -> Tuple[bool, str]:
        """
        Garante sessão válida sem recarregar novo-pedido quando há pedido em andamento.

        O goto de garantir_sessao_ativa descarta o pedido em andamento (volta à etapa 1).
        """
        if not self.page:
            return False, "Página não iniciada."
        if self._esta_no_idp_vtal() or self._sessao_expirada_detectada():
            return self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
        if not self._sessao_pap_autenticada():
            return self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
        if self.etapa_atual >= 2 or self._pedido_nova_fibra_em_andamento():
            return True, "Sessão ativa no pedido em andamento."
        return self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)

    def _etapa3_garantir_tela_documento(self) -> None:
        """Avança da viabilidade para o formulário CPF/CNPJ quando o portal ainda não exibiu o campo."""
        if not self.page or self._etapa2_formulario_documento_visivel():
            return
        btn_cont = self.page.query_selector('button:has-text("Continuar")')
        if btn_cont and btn_cont.is_visible():
            btn_cont.click()
            self.page.wait_for_timeout(500 if self.optimize_for_credit else 1200)
            return
        btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
        if btn_avancar and btn_avancar.is_visible():
            btn_avancar.click()
            self.page.wait_for_timeout(500 if self.optimize_for_credit else 1200)

    def _credito_pool_osab_headless(self) -> bool:
        """Crédito em produção: pool OSAB + headless — teclado/JS only, sem dropdown lento."""
        return bool(self.optimize_for_credit and self.headless)

    def _url_validacao_sessao_pos_login(self) -> str:
        """Rota para provar sessão após login. Crédito vai direto ao novo-pedido (evita Consulta OS)."""
        if self.optimize_for_credit:
            return PAP_NOVO_PEDIDO_URL
        return PAP_CONSULTA_OS_URL

    def _ja_na_tela_novo_pedido_etapa1(self) -> bool:
        """True se a SPA já está em /novo-pedido com o campo vendedor visível."""
        if not self.page or not self._sessao_pap_autenticada():
            return False
        try:
            url = (self.page.url or "").lower()
        except Exception:
            return False
        if "novo-pedido" not in url:
            return False
        inp = self._query_matricula_vendedor_input()
        return bool(inp and inp.is_visible())

    def _aguardar_botao_buscar_etapa2(self, timeout_ms: int = 10000):
        """Aguarda o botão Buscar habilitar após preencher CEP/número."""
        if not self.page:
            return None
        seletor = f"{SELETORES['etapa2']['btn_buscar']}:not([disabled])"
        try:
            self.page.wait_for_selector(seletor, state="visible", timeout=timeout_ms)
        except Exception:
            pass
        return self.page.query_selector(seletor)

    def _clicar_elemento(self, selector: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
        """
        Clica em um elemento com tratamento de erros.
        
        Args:
            selector: Seletor CSS do elemento
            timeout: Timeout em ms
            
        Returns:
            True se sucesso, False se erro
        """
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            self.page.click(selector)
            return True
        except Exception as e:
            logger.error(f"[PAP] Erro ao clicar em {selector}: {e}")
            return False
    
    def _esperar_elemento(self, selector: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
        """
        Espera um elemento aparecer na página.
        
        Args:
            selector: Seletor CSS do elemento
            timeout: Timeout em ms
            
        Returns:
            True se encontrado, False se timeout
        """
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False
    
    def _extrair_texto(self, selector: str) -> Optional[str]:
        """Extrai texto de um elemento"""
        try:
            element = self.page.query_selector(selector)
            if element:
                return element.inner_text()
            return None
        except Exception:
            return None

    def _extrair_protocolo_pedido(self) -> Optional[str]:
        """Extrai o protocolo do pedido (título, URL, conteúdo). Ex: 'Novo pedido - 202602082408770809'."""
        try:
            self.page.wait_for_timeout(500)
            fontes = [
                lambda: self.page.title() or "",
                lambda: self.page.url or "",
                lambda: self.page.content() or "",
            ]
            for fonte in fontes:
                texto = fonte()
                for pat in [
                    r'Novo pedido\s*[-–]\s*(\d{10,25})',
                    r'novo-pedido[/-](\d+)',
                    r'protocolo[:\s]*(\d+)',
                    r'pedido[:\s]*(\d{12,25})',
                ]:
                    m = re.search(pat, texto, re.I)
                    if m:
                        protocolo = m.group(1)
                        self.dados_pedido['protocolo'] = protocolo
                        return protocolo
            return self.dados_pedido.get('protocolo')
        except Exception:
            return self.dados_pedido.get('protocolo')

    # =========================================================================
    # MÉTODOS DE ETAPAS
    # =========================================================================
    
    def iniciar_sessao(self) -> Tuple[bool, str]:
        """
        Inicia a sessão no navegador e faz login no PAP.
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        if not HAS_PLAYWRIGHT:
            return False, "Playwright não está instalado no servidor."
        
        self._garantir_diretorio_sessoes()
        
        try:
            if not _pap_semaphore.acquire(timeout=180):
                logger.warning("[PAP] Semáforo ocupado (>180s) — outras automações podem estar travadas.")
                return False, "Sistema PAP ocupado. Aguarde e tente novamente em instantes."
            self._pap_slot_held = True
            logger.info(f"[PAP] Iniciando sessão para {self.vendedor_nome}")
            
            self.playwright = sync_playwright().start()
            playwright = self.playwright
            launch_opts: Dict[str, Any] = {"headless": self.headless}
            if self.headless:
                launch_opts["args"] = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            _sm = self.slow_mo
            if _sm is None and not self.headless:
                _sm = 300  # pausa entre ações para visualizar cliques
            if _sm is not None:
                launch_opts["slow_mo"] = int(_sm)
            self.browser = playwright.chromium.launch(**launch_opts)
            
            # Tentar carregar sessão existente
            storage_state = self.storage_state_path if os.path.exists(self.storage_state_path) else None
            
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                # Altura maior: drawer de streaming tem Salvar no rodapé (abaixo da dobra em 800px).
                viewport={"width": 1280, "height": 960},
                storage_state=storage_state,
            )
            if self.headless:
                self.context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )
            
            self.page = self.context.new_page()
            # Timeout padrão alto para evitar "Timeout 5000ms" em produção (rede/React lentos)
            self.page.set_default_timeout(25000)
            self.sessao_iniciada = True

            # Trace: grava todas as ações para inspecionar no Playwright Trace Viewer (ver onde os cliques foram feitos)
            if self.capture_screenshots or self.record_trace:
                try:
                    self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    self._trace_started = True
                    logger.info("[PAP] Trace iniciado (gravação de ações para debug)")
                except Exception as e:
                    logger.warning(f"[PAP] Trace não iniciado: {e}")

            # Navegar para o PAP (modo rápido evita networkidle — economiza ~10–20s no STATUS)
            goto_timeout = 45000 if self.optimize_for_credit else 60000
            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=goto_timeout)
            self.page.wait_for_timeout(200 if self.optimize_for_credit else 1000)
            if self.optimize_for_credit:
                try:
                    self.page.wait_for_load_state("load", timeout=8000)
                except Exception:
                    pass
            else:
                try:
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    try:
                        self.page.wait_for_load_state("load", timeout=20000)
                    except Exception:
                        pass
            self.page.wait_for_timeout(400 if self.optimize_for_credit else 2500)

            # Verificar se precisa fazer login (URL ou formulário de login visível).
            # Retry se a página navegou e o contexto anterior foi destruído.
            current_url = ""
            login_form_visivel = None
            for _ in range(3):
                try:
                    current_url = self.page.url or ""
                    login_form_visivel = (
                        self.page.query_selector('#inputMatricula') or
                        self.page.query_selector('#passwordInput') or
                        self.page.query_selector('input[placeholder*="Login"]') or
                        self.page.query_selector('input[type="password"]')
                    )
                    break
                except Exception as e:
                    if "Execution context was destroyed" in str(e) or "context was destroyed" in str(e):
                        logger.warning("[PAP] Página ainda navegando, aguardando e tentando novamente...")
                        self.page.wait_for_timeout(2500)
                        continue
                    raise

            precisa_login = (
                "login.vtal.com" in current_url
                or ("login" in current_url.lower() and "pap.niointernet.com.br" not in current_url)
                or bool(login_form_visivel)
                or not self._sessao_pap_autenticada()
            )
            if precisa_login:
                sucesso, msg = self._fazer_login()
                if not sucesso:
                    self._fechar_sessao()
                    return False, msg

            # Cookies antigos podem “parecer” logados na home e cair no IdP ao abrir rota protegida.
            # Crédito: validar direto em novo-pedido (economiza goto Consulta OS + novo-pedido).
            ok_probe, msg_probe = self.garantir_sessao_ativa(self._url_validacao_sessao_pos_login())
            if not ok_probe:
                self._fechar_sessao()
                return False, msg_probe

            self.logado = True
            # Screenshot só depois da primeira tela do PAP carregar (evita print do spinner)
            self._capture_screenshot(
                "01_login_ok",
                wait_selector=f"{SELETORES['etapa1']['matricula_vendedor']}, button:has-text('Avançar')",
                wait_timeout_ms=8000,
            )

            # Salvar estado da sessão
            try:
                self.context.storage_state(path=self.storage_state_path)
            except Exception as e:
                logger.warning(f"[PAP] Erro ao salvar estado da sessão: {e}")
            
            return True, "Sessão iniciada com sucesso!"
            
        except Exception as e:
            logger.error(f"[PAP] Erro ao iniciar sessão: {e}")
            self._fechar_sessao()
            return False, f"Erro ao iniciar sessão: {str(e)}"
    
    def _contexto_destruido(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "execution context was destroyed" in msg or "context was destroyed" in msg

    def _pagina_navegando(self, exc: Exception) -> bool:
        """Playwright rejeita leitura de URL/DOM durante redirect (SSO, novo-pedido)."""
        msg = str(exc).lower()
        return self._contexto_destruido(exc) or (
            "page is navigating" in msg or "unable to retrieve content" in msg
        )

    def _page_content_seguro(self, tentativas: int = 3, pausa_ms: int = 600) -> str:
        """Lê HTML com retry quando o PAP ainda está redirecionando."""
        if not self.page:
            return ""
        ultimo_erro: Optional[Exception] = None
        for tentativa in range(tentativas):
            try:
                return self.page.content() or ""
            except Exception as exc:
                ultimo_erro = exc
                if self._pagina_navegando(exc) and tentativa < tentativas - 1:
                    self.page.wait_for_timeout(pausa_ms)
                    continue
                break
        if ultimo_erro:
            logger.debug("[PAP] _page_content_seguro falhou: %s", ultimo_erro)
        return ""

    def _pagina_indica_credito_negado(self, pagina_texto: str) -> bool:
        """Evita falso 'negado' em textos genéricos da etapa de ofertas."""
        lower = (pagina_texto or "").lower()
        if "crédito negado" in lower or "credito negado" in lower:
            return True
        if "negado" in lower and "aprovado" not in lower:
            return any(
                termo in lower
                for termo in ("crédito", "credito", "análise de crédito", "analise de credito")
            )
        return False

    def _ler_motivo_credito_negado(self) -> str:
        """Lê no modal de resultado a justificativa da negativa (ex.: débito na Nio)."""
        if not self.page:
            return ""
        from crm_app.services.credito_pap_service import extrair_motivo_negativa

        titulos = (
            'h2:has-text("Resultado da análise de crédito")',
            'h2:has-text("Resultado análise de crédito")',
            'h1:has-text("Resultado da análise de crédito")',
            'h3:has-text("Resultado da análise de crédito")',
            'h2:has-text("Crédito negado")',
        )
        for seletor in titulos:
            try:
                titulo = self.page.query_selector(seletor)
            except Exception:
                titulo = None
            if not titulo:
                continue
            motivo = extrair_motivo_negativa(
                self._extrair_texto_ao_redor_titulo(titulo)
            )
            if motivo:
                return motivo
        return ""

    def _pagina_carregando_apos_credito(self) -> bool:
        """Overlay/spinner enquanto o PAP consulta crédito ou catálogo de ofertas."""
        if not self.page:
            return False
        try:
            carregando = self.page.evaluate(
                """() => {
                    const lower = (document.body?.innerText || '').toLowerCase();
                    const frases = [
                        'consultando o catálogo de ofertas',
                        'consultando o catalogo de ofertas',
                        'consultando catálogo',
                        'consultando catalogo',
                        'consultando o crédito',
                        'consultando o credito',
                        'analisando crédito',
                        'analisando credito',
                    ];
                    if (frases.some((f) => lower.includes(f))) return true;
                    const progress = document.querySelector(
                        '.MuiCircularProgress-root, [role="progressbar"]'
                    );
                    if (progress) {
                        const r = progress.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                    return false;
                }"""
            )
            if carregando:
                return True
        except Exception:
            pass
        pagina_lower = self._page_content_seguro(tentativas=1, pausa_ms=200).lower()
        return any(
            termo in pagina_lower
            for termo in (
                "consultando o catálogo de ofertas",
                "consultando o catalogo de ofertas",
                "consultando catálogo",
                "consultando catalogo",
            )
        )

    def _radios_pagamento_visiveis(self) -> bool:
        """Radios BOLETO/CREDITO/DACC realmente visíveis na tela (não só no DOM)."""
        if not self.page:
            return False
        try:
            return bool(
                self.page.evaluate(
                    """() => {
                        const vals = ['BOLETO','CREDITO','DACC'];
                        for (const inp of document.querySelectorAll('input[type="radio"]')) {
                            if (!vals.includes(inp.value)) continue;
                            const style = window.getComputedStyle(inp);
                            const rect = inp.getBoundingClientRect();
                            if (
                                rect.width > 0 && rect.height > 0
                                && style.visibility !== 'hidden'
                                && style.display !== 'none'
                            ) {
                                return true;
                            }
                        }
                        return false;
                    }"""
                )
            )
        except Exception:
            return False

    def _secao_pagamento_ofertas_visivel(self) -> bool:
        """Seção real da etapa 5, distinta do overlay de loading na etapa 4."""
        if not self.page:
            return False
        for sel in (
            'span:has-text("Forma de pagamento")',
            'div:has-text("Escolher ofertas")',
        ):
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _ainda_na_etapa4_contato(self) -> bool:
        """Formulário de contato ainda dominante (ex.: overlay 'Consultando ofertas' na etapa 4)."""
        if not self.page:
            return False
        try:
            return bool(
                self.page.evaluate(
                    """() => {
                        const lower = (document.body?.innerText || '').toLowerCase();
                        const temContato =
                            lower.includes('celular principal')
                            || lower.includes('confirme o celular')
                            || (lower.includes('e-mail') && lower.includes('contato'));
                        const temPagamento =
                            lower.includes('forma de pagamento')
                            || lower.includes('escolher ofertas');
                        const radios = [...document.querySelectorAll('input[type="radio"]')]
                            .filter((i) => ['BOLETO', 'CREDITO', 'DACC'].includes(i.value));
                        const radiosVis = radios.some((i) => {
                            const r = i.getBoundingClientRect();
                            const st = window.getComputedStyle(i);
                            return (
                                r.width > 0 && r.height > 0
                                && st.visibility !== 'hidden'
                                && st.display !== 'none'
                            );
                        });
                        return temContato && !temPagamento && !radiosVis;
                    }"""
                )
            )
        except Exception:
            return False

    def _aguardar_fim_carregamento_credito(self, timeout_ms: int = 45000) -> bool:
        """Aguarda sumir o overlay 'Consultando o catálogo de ofertas' etc."""
        if not self.page:
            return False
        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            if not self._pagina_carregando_apos_credito():
                return True
            self.page.wait_for_timeout(500)
        return not self._pagina_carregando_apos_credito()

    def _etapa5_pagamento_visivel(self, *, exigir_ui_pronta: bool = False) -> bool:
        """Detecta etapa 5 (ofertas/pagamento) mesmo quando o PAP pula o modal de crédito."""
        if not self.page:
            return False
        if self._pagina_carregando_apos_credito():
            return False
        if exigir_ui_pronta and self._ainda_na_etapa4_contato():
            return False
        if self._radios_pagamento_visiveis():
            return True
        if self._secao_pagamento_ofertas_visivel():
            return True
        for sel in ('input[value="BOLETO"]', 'input[value="CREDITO"]', 'input[value="DACC"]'):
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return True
            except Exception:
                continue
        if exigir_ui_pronta:
            return False
        pagina_lower = self._page_content_seguro(tentativas=2, pausa_ms=400).lower()
        if pagina_lower and "consultando" not in pagina_lower:
            if "ofertas" in pagina_lower and (
                "pagamento" in pagina_lower or "forma de pagamento" in pagina_lower
            ):
                return True
        apis = getattr(self, "_credito_apis_pos_avancar", set()) or set()
        if apis.intersection({"analise_credito", "proposta_credito", "ofertas"}):
            return True
        return False

    def _marcar_api_credito_pos_avancar(self, url: str) -> None:
        """Registra APIs do PAP disparadas após Avançar na etapa de contato."""
        url_lower = (url or "").lower()
        if "pap-api.niointernet.com.br" not in url_lower:
            return
        if "analisecredito" in url_lower:
            self._credito_apis_pos_avancar.add("analise_credito")
        if "propostacredito" in url_lower:
            self._credito_apis_pos_avancar.add("proposta_credito")
        if "vendas/ofertas" in url_lower:
            self._credito_apis_pos_avancar.add("ofertas")

    def _aguardar_pagina_estavel(self, retries: int = 3, delay_ms: int = 2500) -> None:
        """Aguarda redirects SSO terminarem antes de ler URL/DOM."""
        if not self.page:
            return
        if self.optimize_for_credit:
            retries = 1
            delay_ms = 800
        for _ in range(retries):
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_timeout(300 if self.optimize_for_credit else 1500)
            try:
                _ = self.page.url
                return
            except Exception as e:
                if self._contexto_destruido(e):
                    self.page.wait_for_timeout(delay_ms)
                    continue
                raise

    def _ler_url_e_conteudo(self) -> Tuple[str, str]:
        """Lê URL e HTML com retry quando o SSO ainda está redirecionando."""
        for tentativa in range(4):
            try:
                return (self.page.url or ""), (self.page.content() or "")
            except Exception as e:
                if self._pagina_navegando(e) and tentativa < 3:
                    logger.warning("[PAP] Página ainda navegando (login), aguardando...")
                    self.page.wait_for_timeout(2500)
                    continue
                raise
        return "", ""

    def _formulario_login_visivel(self) -> Optional[Any]:
        """Detecta formulário de login tolerando redirect SSO em andamento."""
        if not self.page:
            return None
        for tentativa in range(3):
            try:
                return (
                    self.page.query_selector('#inputMatricula')
                    or self.page.query_selector('#passwordInput')
                    or self.page.query_selector('input[placeholder*="Login"]')
                    or self.page.query_selector('input[type="password"]')
                )
            except Exception as e:
                if self._contexto_destruido(e) and tentativa < 2:
                    logger.warning(
                        "[PAP] Página ainda navegando ao checar login, aguardando..."
                    )
                    self._aguardar_pagina_estavel(retries=2, delay_ms=2000)
                    continue
                raise
        return None

    def _ler_url_atual(self) -> str:
        """Lê URL atual com retry quando o SSO ainda redireciona."""
        if not self.page:
            return ""
        for tentativa in range(4):
            try:
                return self.page.url or ""
            except Exception as e:
                if self._pagina_navegando(e) and tentativa < 3:
                    logger.warning("[PAP] URL indisponível durante navegação, aguardando...")
                    self.page.wait_for_timeout(2000)
                    continue
                raise
        return ""

    def _fazer_login(self) -> Tuple[bool, str]:
        """
        Realiza o login no PAP via Vtal.
        Trata "upstream request timeout" do SSO com recarregamento e nova tentativa.
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        max_tentativas = 3
        for tentativa in range(1, max_tentativas + 1):
            try:
                logger.info(f"[PAP] Fazendo login para {self.matricula_pap} (tentativa {tentativa}/{max_tentativas})")
                self._aguardar_pagina_estavel()

                # Garantir que estamos na página de login (pode ter vindo de retry após timeout)
                current_url, pagina_html = self._ler_url_e_conteudo()
                if self._pagina_senha_expirada(pagina=pagina_html, url=current_url):
                    self._capture_screenshot("00_err_senha_expirada", forcar=True)
                    logger.warning("[PAP] Senha expirada para %s (antes do formulário)", self.matricula_pap)
                    return False, self._mensagem_senha_pap_expirada()
                if "login.vtal.com" in current_url and "upstream request timeout" in pagina_html.lower():
                    logger.warning("[PAP] Erro upstream timeout detectado, recarregando página de login...")
                    self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                    self._aguardar_pagina_estavel()
                
                # Aguardar formulário (evita query_selector durante redirect SSO)
                sel_timeout = 10000 if self.optimize_for_credit else 15000
                try:
                    self.page.wait_for_selector(
                        '#inputMatricula, input[placeholder*="Login"], input[name*="matricula"], input[type="text"]',
                        state="visible",
                        timeout=sel_timeout,
                    )
                except Exception as e_sel:
                    if self._pagina_senha_expirada():
                        self._capture_screenshot("00_err_senha_expirada", forcar=True)
                        return False, self._mensagem_senha_pap_expirada()
                    raise e_sel
                self.page.wait_for_selector(
                    '#passwordInput, input[type="password"], input[placeholder*="Senha"]',
                    state="visible",
                    timeout=8000 if self.optimize_for_credit else 10000,
                )

                if self._pagina_senha_expirada():
                    self._capture_screenshot("00_err_senha_expirada", forcar=True)
                    logger.warning("[PAP] Senha expirada para %s (formulário visível)", self.matricula_pap)
                    return False, self._mensagem_senha_pap_expirada()
                
                # Preencher matrícula e senha (tentar vários seletores)
                for sel in ['#inputMatricula', 'input[placeholder*="Login"]', 'input[name*="matricula"]', 'input[name*="username"]']:
                    try:
                        self.page.fill(sel, self.matricula_pap, timeout=5000)
                        break
                    except Exception:
                        continue
                for sel in ['#passwordInput', 'input[type="password"]', 'input[placeholder*="Senha"]']:
                    try:
                        self.page.fill(sel, self.senha_pap, timeout=5000)
                        break
                    except Exception:
                        continue
                
                # Clicar no botão de login (sem query_selector — mesmo problema de contexto)
                clicou = False
                for sel_btn in [
                    'button:has-text("EFETUAR")',
                    'button:has-text("Entrar")',
                    'button:has-text("ENTRAR")',
                    'button:has-text("Acessar")',
                    'button:has-text("Login")',
                    'button[type="submit"]',
                    'input[type="submit"]',
                    '[role="button"]:has-text("Entrar")',
                    SELETORES['login']['btn_login'],
                ]:
                    try:
                        self.page.click(sel_btn, timeout=5000)
                        clicou = True
                        break
                    except Exception:
                        continue
                if not clicou:
                    # Algumas versões do IdP V.tal submetem o formulário apenas
                    # pelo Enter no campo de senha e não expõem button[type=submit].
                    self._capture_screenshot(
                        "00_login_sem_botao_submit",
                        forcar=True,
                    )
                    try:
                        self.page.keyboard.press("Enter")
                        clicou = True
                        logger.warning(
                            "[PAP] Botão de login não localizado; formulário "
                            "submetido com Enter."
                        )
                    except Exception:
                        return False, "Botão de login não encontrado no PAP."

                # Aguardar a página reagir (redirecionamento ou mensagem de erro).
                # Tempo suficiente para o redirect do SSO evitar "Execution context was destroyed".
                self.page.wait_for_timeout(1500 if self.optimize_for_credit else 3500)

                if self._pagina_senha_expirada():
                    self._capture_screenshot("00_err_senha_expirada", forcar=True)
                    return False, self._mensagem_senha_pap_expirada()

                # Validar: se aparecer "Login failed, please try again" (ou similar), não avançar
                if self._pagina_tem_erro_login():
                    if self._pagina_senha_expirada():
                        return False, self._mensagem_senha_pap_expirada()
                    logger.warning("[PAP] Login falhou: mensagem de erro detectada na tela.")
                    return False, "Login falhou. Verifique matrícula, senha e OTP (se exigido). Tente novamente."

                # Aguardar redirecionamento para PAP (pode haver múltiplos redirects via SSO)
                try:
                    self.page.wait_for_url(
                        lambda url: "pap.niointernet.com.br" in url and "login" not in url.lower(),
                        timeout=14000 if self.optimize_for_credit else 22000
                    )
                    # Nova checagem: às vezes o redirect mostra PAP mas ainda com iframe de erro
                    if self._pagina_senha_expirada():
                        return False, self._mensagem_senha_pap_expirada()
                    if self._pagina_tem_erro_login():
                        return False, "Login falhou. Verifique matrícula, senha e OTP (se exigido). Tente novamente."
                    logger.info(f"[PAP] Login bem-sucedido para {self.matricula_pap}")
                    return True, "Login realizado com sucesso!"
                except Exception:
                    current_url, pagina = self._ler_url_e_conteudo()
                    pagina = pagina.lower()
                    if self._pagina_senha_expirada(pagina=pagina, url=current_url):
                        self._capture_screenshot("00_err_senha_expirada", forcar=True)
                        return False, self._mensagem_senha_pap_expirada()
                    # Se a tela mostra erro de login, falhar de forma clara
                    if self._pagina_tem_erro_login():
                        return False, "Login falhou. Verifique matrícula, senha e OTP (se exigido). Tente novamente."
                    # FAST PASS / OTP no app: headless não consegue aprovar — falha explícita.
                    if self._pagina_login_vtal_travada(pagina=pagina, url=current_url):
                        logger.warning("[PAP] Login travado no FAST PASS/OTP V.tal (url=%s)", current_url[:120])
                        return False, self._mensagem_falha_login_vtal()
                    # Sucesso mesmo com exceção (ex: timeout no wait mas URL já correta)
                    if self._sessao_pap_autenticada():
                        return True, "Login realizado com sucesso!"
                    # Erro upstream timeout do SSO - recarregar e tentar de novo
                    if "upstream request timeout" in pagina:
                        logger.warning("[PAP] SSO retornou 'upstream request timeout', tentando novamente...")
                        if tentativa < max_tentativas:
                            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                            self.page.wait_for_selector(SELETORES['login']['matricula'], state="visible", timeout=15000)
                            continue
                        return False, "SSO indisponível (upstream timeout). Tente novamente em instantes."
                    return False, "Falha no login. Verifique matrícula e senha."
                
            except Exception as e:
                logger.error(f"[PAP] Erro no login (tentativa {tentativa}): {e}")
                if self._pagina_senha_expirada():
                    self._capture_screenshot("00_err_senha_expirada", forcar=True)
                    return False, self._mensagem_senha_pap_expirada()
                if self._contexto_destruido(e) and tentativa < max_tentativas:
                    logger.warning("[PAP] Contexto destruído no login — aguardando redirect e tentando de novo...")
                    self.page.wait_for_timeout(1500 if self.optimize_for_credit else 3000)
                    continue
                if tentativa < max_tentativas:
                    try:
                        logger.warning(
                            "[PAP] Reiniciando contexto sem cookies (tentativa %s/%s)",
                            tentativa + 1,
                            max_tentativas,
                        )
                        self._recriar_contexto_sem_storage()
                        self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                        self._aguardar_pagina_estavel()
                    except Exception:
                        pass
                    continue
                return False, f"Erro no login: {str(e)}"
        
        return False, "Falha no login após múltiplas tentativas."

    def _sessao_pap_autenticada(self) -> bool:
        """True somente se a URL atual for o PAP autenticado (não o IdP V.tal)."""
        if not self.page:
            return False
        try:
            url = (self.page.url or "").lower()
        except Exception:
            return False
        if "login.vtal.com" in url:
            return False
        if "pap.niointernet.com.br" not in url:
            return False
        # Evita considerar a própria tela de login do PAP como autenticada.
        if "/login" in url and "administrativo" not in url:
            return False
        return True

    def _esta_no_idp_vtal(self, url: str = "") -> bool:
        """True se a URL atual for o IdP V.tal (não o PAP)."""
        url = (url or "").lower()
        if not url and self.page:
            try:
                url = (self.page.url or "").lower()
            except Exception:
                return False
        return "login.vtal.com" in url

    def _pagina_login_vtal_travada(self, pagina: str = "", url: str = "") -> bool:
        """Detecta SSO V.tal preso em FAST PASS / 'Processando o login'."""
        if not self._esta_no_idp_vtal(url=url):
            return False
        pagina = (pagina or "").lower()
        sinais = (
            "processando o login",
            "fast pass",
            "memorize o código",
            "memorize o codigo",
            "v.tal fast pass",
            "senha + otp",
        )
        if any(s in pagina for s in sinais):
            return True
        if not pagina and self.page:
            try:
                pagina = (self.page.content() or "").lower()
            except Exception:
                # No IdP sem conseguir ler o DOM: trata como travado.
                return True
            return any(s in pagina for s in sinais)
        # No IdP sem sinais explícitos: ainda assim não autenticou no PAP.
        return True

    @staticmethod
    def _mensagem_falha_login_vtal() -> str:
        return (
            "Login V.tal travado em FAST PASS/OTP (aprovação no app). "
            "Use um BO com login senha sem FAST PASS ou aprove no app e tente de novo."
        )

    def _relogin_pap(self, target_url: Optional[str] = None) -> Tuple[bool, str]:
        """
        Força login limpo (sem cookies) e, se informado, navega para target_url
        validando que não caiu de novo no IdP V.tal.
        """
        logger.warning("[PAP] Relogin automático (url atual=%s)", (self.page.url or "")[:120] if self.page else "-")
        self._fechar_modal_sessao_expirada()
        try:
            # Apagar apenas o arquivo de storage não remove cookies/JWT do contexto
            # já aberto. A V.tal continuava recebendo a sessão expirada e entrava
            # em um ciclo PAP → IdP → PAP → IdP.
            self._recriar_contexto_sem_storage()
            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            self._aguardar_pagina_estavel()
        except Exception as e:
            self.logado = False
            logger.warning("[PAP] Falha ao criar contexto limpo no relogin: %s", e)
            return False, "Não foi possível reiniciar a sessão PAP para refazer o login."

        ok, msg = self._fazer_login()
        if not ok or not self._sessao_pap_autenticada():
            self.logado = False
            if self._pagina_login_vtal_travada(url=(self.page.url or "") if self.page else ""):
                return False, self._mensagem_falha_login_vtal()
            return False, f"Sessão expirada e relogin falhou: {msg}"

        self.logado = True
        try:
            self.context.storage_state(path=self.storage_state_path)
        except Exception as e:
            logger.debug("[PAP] Salvar storage após relogin: %s", e)

        if target_url:
            try:
                self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                self.page.wait_for_timeout(400 if self.optimize_for_credit else 1500)
            except Exception as e:
                logger.warning("[PAP] goto após relogin: %s", e)
            if self._esta_no_idp_vtal() or not self._sessao_pap_autenticada():
                self.logado = False
                if self._pagina_login_vtal_travada(url=(self.page.url or "") if self.page else ""):
                    return False, self._mensagem_falha_login_vtal()
                return False, "Relogin OK, mas a rota protegida voltou ao login V.tal."

        return True, "Sessão restaurada com sucesso."

    def _mensagem_senha_pap_expirada(self) -> str:
        mat = (self.matricula_pap or "").strip() or "este login"
        return (
            f"Senha do PAP expirada para *{mat}*. "
            "Atualize a senha no portal V.tal e cadastre a nova senha no pool de BOs "
            "antes de tentar novamente."
        )

    def _pagina_senha_expirada(self, pagina: str = "", url: str = "") -> bool:
        """True se o IdP V.tal exibe o banner 'Sua senha expirou.'"""
        pagina = (pagina or "").lower()
        if not pagina and self.page:
            try:
                pagina = (self.page.content() or "").lower()
            except Exception:
                try:
                    pagina = (self.page.inner_text("body") or "").lower()
                except Exception:
                    pagina = ""
        if not pagina:
            return False
        sinais = (
            "sua senha expirou",
            "senha expirou",
            "password has expired",
            "password expired",
            "senha expirada",
        )
        if any(s in pagina for s in sinais):
            return True
        # Banner visível (mais confiável que HTML genérico)
        if self.page:
            try:
                loc = self.page.get_by_text(re.compile(r"sua\s+senha\s+expirou", re.I))
                if loc.count() > 0 and loc.first.is_visible():
                    return True
            except Exception:
                pass
        return False

    def _pagina_tem_erro_login(self) -> bool:
        """
        Verifica se a página exibe mensagem de erro de login (ex.: "Login failed, please try again.").
        Retorna True se o erro estiver presente, para não avançar como se o login tivesse sucesso.
        """
        if not self.page:
            return False
        for tentativa in range(2):
            try:
                content = (self.page.content() or "").lower()
                url = (self.page.url or "").lower()
                break
            except Exception as e:
                if ("Execution context was destroyed" in str(e) or "context was destroyed" in str(e)) and tentativa == 0:
                    self.page.wait_for_timeout(2000)
                    continue
                return False
        try:
            if self._pagina_senha_expirada(pagina=content, url=url):
                logger.warning("[PAP] Senha expirada detectada no IdP V.tal.")
                return True
            # Textos que indicam falha de login (inglês e português)
            if "login failed" in content or "please try again" in content:
                logger.warning("[PAP] Mensagem de erro de login detectada (Login failed / please try again).")
                return True
            if "login falhou" in content or "tente novamente" in content:
                logger.warning("[PAP] Mensagem de erro de login detectada (pt).")
                return True
            if "credenciais inválidas" in content or "invalid credentials" in content:
                logger.warning("[PAP] Mensagem de erro de login detectada (credenciais).")
                return True
            # Se ainda estamos em página de login após o clique, e há indicação de erro
            if ("login" in url or "vtal.com" in url) and ("error" in content or "alert" in content):
                if "failed" in content or "falhou" in content or "inválid" in content:
                    return True
            return False
        except Exception as e:
            logger.debug(f"[PAP] Verificação de erro de login: {e}")
            return False

    def _sessao_expirada_detectada(self) -> bool:
        """
        Detecta quando a sessão do PAP foi invalidada por outro login ou timeout no IdP Vtal.
        Inclui a tela de logout: login.vtal.com/.../logout*.html com "Sessão finalizada".
        """
        if not self.page:
            return False
        try:
            url = (self.page.url or "").lower()
            # Logout explícito do IdP (ex.: /nidp/logout_vtal/logout.html)
            if "login.vtal.com" in url and "logout" in url:
                return True
            # Qualquer tela do IdP Vtal sem PAP aberto costuma indicar sessão perdida no fluxo
            if "login.vtal.com" in url:
                return True
        except Exception:
            pass
        try:
            content = (self.page.content() or "").lower()
        except Exception:
            return False
        sinais = (
            "não autorizado",
            "nao autorizado",
            "sessão expirada",
            "sessao expirada",
            "sessão finalizada",
            "sessao finalizada",
            "feche seu navegador",
            "logar novamente no portal",
        )
        return any(s in content for s in sinais)

    def _fechar_modal_sessao_expirada(self) -> None:
        """Tenta fechar modal de sessão expirada para liberar a UI antes do relogin."""
        if not self.page:
            return
        for sel in ['button:has-text("OK")', 'button:has-text("Ok")', 'button:has-text("Fechar")']:
            try:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(200 if self.optimize_for_credit else 400)
                    return
            except Exception:
                continue

    def garantir_sessao_ativa(self, target_url: Optional[str] = None) -> Tuple[bool, str]:
        """
        Garante que a sessão no PAP ainda está válida.

        Cookies/storage podem deixar a home do PAP aberta e só falhar ao abrir rota
        protegida (Consulta OS). Por isso, quando target_url é informado, navega até
        ela e só considera OK se permanecer autenticado no PAP.
        """
        if not self.page:
            return False, "Página não iniciada."
        try:
            if self._esta_no_idp_vtal() or self._sessao_expirada_detectada():
                return self._relogin_pap(target_url)

            if target_url:
                try:
                    self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    logger.warning("[PAP] goto target em garantir_sessao: %s", e)
                # Cookie/JWT inválido pode mostrar PAP por 1–2s e só depois redirecionar ao IdP.
                settle_ms = 1200 if self.optimize_for_credit else 2000
                self.page.wait_for_timeout(settle_ms)
                try:
                    self.page.wait_for_load_state("load", timeout=5000 if self.optimize_for_credit else 8000)
                except Exception:
                    pass
                self.page.wait_for_timeout(400 if self.optimize_for_credit else 800)
                if (
                    self._esta_no_idp_vtal()
                    or self._sessao_expirada_detectada()
                    or not self._sessao_pap_autenticada()
                ):
                    logger.warning(
                        "[PAP] Rota protegida caiu no IdP V.tal (url=%s). Relogin...",
                        (self.page.url or "")[:120],
                    )
                    return self._relogin_pap(target_url)
                return True, "Sessão ativa."

            if not self._sessao_pap_autenticada():
                return self._relogin_pap(None)
            return True, "Sessão ativa."
        except Exception as e:
            self.logado = False
            return False, f"Erro ao validar/restaurar sessão: {e}"

    def _pap_garantir_sessao_antes_resumo(self) -> Tuple[bool, str]:
        """
        Antes da etapa 6 (resumo/biometria): se o IdP deslogou, tenta relogin.
        Retorna (True, '') para continuar; (False, msg) para abortar (pedido perdido ou falha).
        """
        if not self.page:
            return False, "Página não iniciada."
        if not self._sessao_expirada_detectada():
            return True, ""
        logger.warning("[PAP] Sessão inativa na etapa resumo/biometria; relogin automático.")
        ok, msg = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
        if not ok:
            return False, f"Sessão expirou e relogin falhou: {msg}"
        return False, (
            "Sessão do portal foi renovada; o pedido em tela foi perdido. "
            "Digite *VENDER* para reenviar ou continue no PAP manualmente."
        )

    def esperar_selector_com_keepalive_sessao(
        self,
        selector: str,
        timeout_ms: int = 90000,
        poll_ms: int = 5000,
        target_after_relogin: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Espera um seletor visível em fatias de poll_ms. Entre fatias, se a sessão Vtal cair
        (logout / «Sessão finalizada»), tenta relogin. Se precisar relogar, o pedido atual no
        browser em geral se perde — retorna (False, mensagem) para o chamador decidir.
        """
        if not self.page:
            return False, "Página não iniciada."
        target_after_relogin = target_after_relogin or PAP_NOVO_PEDIDO_URL
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            if self._sessao_expirada_detectada():
                logger.warning("[PAP] Sessão perdida durante espera (selector); relogin automático.")
                ok, msg = self.garantir_sessao_ativa(target_after_relogin)
                if not ok:
                    return False, f"Sessão expirou durante a espera e relogin falhou: {msg}"
                return (
                    False,
                    "Sessão do portal expirou durante a espera; reconexão feita. "
                    "O pedido em tela pode ter sido perdido — use *CONSULTAR* ou *VENDER* conforme o caso.",
                )
            # Modal "Ocorreu um erro" (ex.: falha ao abrir OS) bloqueia a UI — não esperar o timeout inteiro
            if self._pap_modal_titulo_ocorreu_erro_visivel():
                trecho_m = self._pap_extrair_texto_modal_proximo_a_titulo_erro()
                self._pap_fechar_modal_ocorreu_erro_h3_ok()
                self.page.wait_for_timeout(400)
                low_m = (trecho_m or "").lower()
                if (
                    "não foi possível abrir o pedido" in low_m
                    or "nao foi possivel abrir o pedido" in low_m
                    or "abrir o pedido" in low_m
                ):
                    return (
                        False,
                        "O portal exibiu erro ao abrir o pedido/OS durante a espera pelo agendamento. "
                        "Tente mais tarde ou abra chamado na Nio; o fluxo pode ter voltado à Etapa 1.",
                    )
                return (
                    False,
                    (trecho_m or "Ocorreu um erro no portal").strip()[:400],
                )
            restante_ms = max(1000, int((deadline - time.monotonic()) * 1000))
            chunk = min(poll_ms, restante_ms)
            try:
                self.page.wait_for_selector(selector, state="visible", timeout=chunk)
                return True, None
            except Exception:
                continue
        return False, f"Timeout ({timeout_ms} ms) aguardando: {selector[:160]}"

    def _dispensar_modais_novo_pedido(self) -> None:
        """Fecha modais/overlays que impedem ver o formulário (tutorial, avisos)."""
        if not self.page:
            return
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(200 if self.optimize_for_credit else 350)
        except Exception:
            pass
        for _ in range(2):
            fechou = False
            for sel in (
                'button[aria-label="Close"]',
                'button[aria-label="Fechar"]',
                'button:has-text("Entendi")',
                'button:has-text("OK")',
                'button:has-text("Ok")',
                'button:has-text("Fechar")',
            ):
                try:
                    el = self.page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        self.page.wait_for_timeout(300 if self.optimize_for_credit else 450)
                        fechou = True
                except Exception:
                    continue
            if not fechou:
                break

    def _esperar_campo_matricula_vendedor(self, timeout_ms: int, modo_rapido: bool) -> bool:
        """True se o campo de vendedor/matrícula (etapa 1) estiver visível."""
        if not self.page:
            return False
        # Se caiu no IdP no meio da espera, não gastar o timeout inteiro.
        if self._esta_no_idp_vtal() or self._sessao_expirada_detectada():
            logger.warning(
                "[PAP] IdP/sessão inválida ao esperar matrícula (url=%s)",
                (self._ler_url_atual() or "")[:120],
            )
            return False
        try:
            self.page.wait_for_selector(
                SELETORES_MATRICULA_VENDEDOR_CSS,
                state="visible",
                timeout=min(timeout_ms, 4000 if modo_rapido else 6000),
            )
            return True
        except Exception:
            if self._esta_no_idp_vtal() or self._sessao_expirada_detectada():
                return False
        chunk = max(1200, min(3500, timeout_ms // max(1, len(SELETORES_MATRICULA_VENDEDOR) // 3)))
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        for sel in SELETORES_MATRICULA_VENDEDOR:
            if time.monotonic() >= deadline:
                break
            if self._esta_no_idp_vtal() or self._sessao_expirada_detectada():
                return False
            try:
                restante = max(800, int((deadline - time.monotonic()) * 1000))
                self.page.wait_for_selector(
                    sel,
                    state="visible",
                    timeout=min(chunk if modo_rapido else min(chunk + 800, 5000), restante),
                )
                return True
            except Exception:
                continue
        # Último recurso: combobox/autocomplete por rótulo próximo
        try:
            loc = self.page.get_by_label(re.compile(r"vendedor|matrícula|matricula", re.I))
            if loc.count() > 0:
                loc.first.wait_for(state="visible", timeout=4000)
                return True
        except Exception:
            pass
        return False

    def _mensagem_falha_etapa1_sem_matricula(self) -> str:
        """Mensagem correta conforme a URL real (IdP vs PAP)."""
        url = ""
        try:
            url = self.page.url or ""
        except Exception:
            pass
        if self._pagina_senha_expirada(url=url):
            return self._mensagem_senha_pap_expirada()
        if self._esta_no_idp_vtal(url=url) or "login.vtal.com" in url.lower():
            return (
                "Sessão do PAP caiu no login V.tal ao abrir Novo Pedido "
                f"(login={self.matricula_pap or '?'}). "
                "Tente novamente; se repetir, verifique senha/OTP do BO."
            )
        if "pap.niointernet.com.br" not in url.lower():
            return (
                "Não foi possível acessar a página de novo pedido. "
                f"URL: {(url or '?')[:100]}"
            )
        return (
            "Não foi possível acessar a página de novo pedido "
            "(campo matrícula não encontrado e menu 'Novo Pedido' não clicável)."
        )

    def _query_matricula_vendedor_input(self):
        """Retorna o elemento input do vendedor ou None."""
        if not self.page:
            return None
        estrategias_locator = [
            'label:has-text("Vendedor") ~ div input, label:has-text("Vendedor") + div input',
            'div:has(> label:has-text("Vendedor")) input',
            'div:has(span:has-text("Vendedor")) input[type="text"], div:has(span:has-text("Vendedor")) input[type="search"]',
        ]
        for sel in estrategias_locator:
            try:
                loc = self.page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return loc.element_handle()
            except Exception:
                continue
        try:
            loc = self.page.get_by_placeholder(re.compile(r"vendedor|matr[ií]cula", re.I)).first
            if loc.count() > 0 and loc.is_visible():
                return loc.element_handle()
        except Exception:
            pass
        for sel in SELETORES_MATRICULA_VENDEDOR:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return el
            except Exception:
                continue
        try:
            loc = self.page.get_by_label(re.compile(r"vendedor|matrícula|matricula", re.I))
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first.element_handle()
        except Exception:
            pass
        return None

    def _instalar_listener_vendedores_api(self) -> None:
        """Captura matrículas das respostas JSON do autocomplete (mais robusto que só DOM)."""
        if self._listener_vendedor_ativo or not self.page:
            return

        def _handler(response) -> None:
            try:
                if response.status < 200 or response.status >= 300:
                    return
                self._marcar_api_credito_pos_avancar(response.url or "")
                ctype = (response.headers.get("content-type") or "").lower()
                if "json" not in ctype:
                    return
                body = response.json()
                mats = self._extrair_matriculas_de_json_recursivo(body)
                if not mats:
                    return
                novas = 0
                for mat in mats:
                    if mat not in self._vendedores_api_matriculas:
                        self._vendedores_api_matriculas.append(mat)
                        novas += 1
                if novas:
                    logger.info(
                        "[PAP] API vendedores: +%s matrícula(s) (%s)",
                        novas,
                        (response.url or "")[:100],
                    )
            except Exception:
                pass

        self.page.on("response", _handler)
        self._listener_vendedor_ativo = True

    def _normalizar_matricula_vendedor(self, valor: str) -> Optional[str]:
        """Normaliza matrícula para TT123456 quando possível."""
        if not valor:
            return None
        texto = str(valor).strip().upper()
        match = re.search(r"\b(TT\d{4,})\b", texto, re.I)
        if match:
            return match.group(1).upper()
        digitos = re.sub(r"\D", "", texto)
        if len(digitos) >= 5:
            return f"TT{digitos}"
        return None

    def _extrair_matricula_de_texto_vendedor(self, texto: str) -> Optional[str]:
        """Extrai matrícula TT do texto exibido no dropdown ou JSON."""
        if not texto:
            return None
        match = re.search(r"\b(TT\d{4,})\b", str(texto).strip(), re.I)
        if match:
            return match.group(1).upper()
        return self._normalizar_matricula_vendedor(texto)

    def _extrair_matriculas_de_json_recursivo(self, data: Any) -> List[str]:
        """Varre JSON de API do PAP em busca de matrículas TT."""
        encontradas: List[str] = []
        vistos: set[str] = set()

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                for chave, valor in node.items():
                    chave_lower = str(chave).lower()
                    if isinstance(valor, str):
                        mat = self._extrair_matricula_de_texto_vendedor(valor)
                        if mat and mat not in vistos:
                            vistos.add(mat)
                            encontradas.append(mat)
                    elif isinstance(valor, (dict, list)):
                        _walk(valor)
                    elif isinstance(valor, (int, float)) and "matric" in chave_lower:
                        mat = self._normalizar_matricula_vendedor(str(int(valor)))
                        if mat and mat not in vistos:
                            vistos.add(mat)
                            encontradas.append(mat)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)
            elif isinstance(node, str):
                mat = self._extrair_matricula_de_texto_vendedor(node)
                if mat and mat not in vistos:
                    vistos.add(mat)
                    encontradas.append(mat)

        _walk(data)
        return encontradas

    def _coletar_matriculas_dom_via_js(self) -> List[str]:
        """Varre poppers/portals visíveis em busca de matrículas TT (fallback DOM)."""
        if not self.page:
            return []
        try:
            raw = self.page.evaluate(
                """(headless) => {
                    const re = /\\bTT\\d{4,}\\b/gi;
                    const seen = new Set();
                    const out = [];
                    const roots = [
                        ...document.querySelectorAll('[role="listbox"], [class*="Popper"], [class*="popper"], [class*="Autocomplete"], [id^="menu-"]'),
                    ];
                    for (const root of roots) {
                        if (!root) continue;
                        if (!headless && root.offsetParent === null) continue;
                        const text = (root.innerText || root.textContent || '').trim();
                        if (!text) continue;
                        let m;
                        while ((m = re.exec(text)) !== null) {
                            const mat = m[0].toUpperCase();
                            if (!seen.has(mat)) {
                                seen.add(mat);
                                out.push(mat);
                            }
                        }
                    }
                    return out;
                }""",
                self.headless,
            )
            if isinstance(raw, list):
                return [str(m).upper() for m in raw if m]
        except Exception as exc:
            logger.debug("[PAP] Scan JS lista vendedor: %s", exc)
        return []

    def _digitar_no_campo_vendedor(self, termo: str) -> bool:
        """Digita no autocomplete disparando eventos React (headless)."""
        if not self.page or not termo:
            return False
        if not self._focar_campo_vendedor():
            return False
        matricula_input = self._query_matricula_vendedor_input()
        if not matricula_input:
            return False
        delay_tecla = 130 if (self.headless or self.optimize_for_credit) else 90
        try:
            matricula_input.fill("")
            self.page.wait_for_timeout(250)
            matricula_input.press_sequentially(termo, delay=delay_tecla)
            return True
        except Exception as exc:
            logger.debug("[PAP] press_sequentially vendedor: %s", exc)
        try:
            matricula_input.evaluate(
                """(el, valor) => {
                    el.focus();
                    el.value = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    const proto = Object.getPrototypeOf(el);
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(el, valor);
                    else el.value = valor;
                    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: valor, inputType: 'insertText' }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                termo,
            )
            return True
        except Exception as exc:
            logger.debug("[PAP] evaluate digitar vendedor: %s", exc)
            return False

    def _abrir_popup_vendedor_mui(self) -> bool:
        """Abre o popup do MUI Autocomplete (seta / combobox)."""
        if not self.page:
            return False
        seletores_botao = [
            'div:has(input[placeholder*="Vendedor"]) button[aria-label*="Open"]',
            'div:has(input[placeholder*="vendedor"]) button[aria-label*="Open"]',
            '[class*="Autocomplete"] button[class*="popupIndicator"]',
            '[class*="Autocomplete"] button[aria-label*="Open"]',
        ]
        for sel in seletores_botao:
            try:
                btn = self.page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(400)
                    return True
            except Exception:
                continue
        return False

    def _matriculas_da_rede_vendedor(self) -> List[str]:
        """Matrículas capturadas via interceptação de API durante digitação."""
        return list(dict.fromkeys(self._vendedores_api_matriculas or []))

    def _redirecionar_se_rota_bloqueia_novo_pedido(self) -> bool:
        """
        Se o navegador cair em rotas laterais (ex.: /administrativo/download) onde não há
        formulário de vendedor, força goto direto em novo-pedido. Evita falso negativo
        “matrícula não encontrada” quando o menu ou um clique desvia a SPA.
        """
        try:
            url = (self.page.url or "").lower()
        except Exception:
            return False
        if "pap.niointernet.com.br" not in url:
            return False
        bloqueadas = ("/administrativo/download", "/administrativo/download/")
        if not any(b in url for b in bloqueadas):
            return False
        logger.warning(
            "[PAP] URL fora do fluxo novo pedido (%s); forçando goto novo-pedido.",
            (self.page.url or "")[:180],
        )
        try:
            self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=35000)
            self.page.wait_for_timeout(600)
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            self._dispensar_modais_novo_pedido()
            return True
        except Exception as e:
            logger.warning("[PAP] Falha ao redirecionar para novo-pedido após rota bloqueada: %s", e)
            return False

    def _clicar_menu_novo_pedido(self) -> bool:
        """
        Clica no item do menu lateral "Novo Pedido" (fallback quando goto não abre o formulário).
        Retorna True se encontrou e clicou, False caso contrário.
        """
        # Locators Playwright (acessibilidade + texto) — mais estáveis que só CSS
        def _apos_clique_menu() -> None:
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass

        # Menu hambúrger / drawer fechado em viewports menores
        try:
            loc_abrir = self.page.get_by_role("button", name=re.compile(r"menu|abrir|navega", re.I))
            if loc_abrir.count() > 0:
                b = loc_abrir.first
                if b.is_visible():
                    logger.info("[PAP] Abrindo menu lateral (botão menu)")
                    b.click(timeout=4000)
                    self.page.wait_for_timeout(500)
        except Exception:
            pass

        for nome, loc in (
            ("link role Novo pedido", self.page.get_by_role("link", name=re.compile(r"Novo\s+pedido", re.I))),
            ("menuitem Novo pedido", self.page.get_by_role("menuitem", name=re.compile(r"Novo\s+pedido", re.I))),
            ("button role Novo pedido", self.page.get_by_role("button", name=re.compile(r"Novo\s+pedido", re.I))),
            ("aside/nav link", self.page.locator("aside a, nav a, [role='navigation'] a").filter(has_text=re.compile(r"Novo\s+pedido", re.I))),
            ("a[href*=novo-pedido]", self.page.locator("a[href*='novo-pedido']")),
            ("button texto Novo Pedido", self.page.locator("button:has-text('Novo Pedido')")),
        ):
            try:
                if loc.count() < 1:
                    continue
                alvo = loc.first
                alvo.wait_for(state="visible", timeout=8000)
                try:
                    alvo.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                logger.info(f"[PAP] Fallback: clicando menu Novo Pedido ({nome})")
                if self.capture_screenshots:
                    try:
                        h = alvo.element_handle()
                        if h:
                            self._highlight_element(h, duration_ms=500)
                    except Exception:
                        pass
                alvo.click(timeout=12000, force=True)
                _apos_clique_menu()
                return True
            except Exception as e:
                logger.debug(f"[PAP] Menu Novo Pedido ({nome}): {e}")
                continue

        seletores_menu = [
            'a[href*="novo-pedido"]',
            'a:has-text("Novo Pedido")',
            '[href*="novo-pedido"]',
            'nav a:has-text("Novo Pedido")',
            'a:has-text("Novo pedido")',
            "//a[contains(@href,'novo-pedido')]",
            "//*[contains(text(),'Novo Pedido') and (self::a or self::button or ancestor::a)]",
        ]
        for sel in seletores_menu:
            try:
                if sel.startswith("//"):
                    el = self.page.query_selector(f"xpath={sel}")
                else:
                    el = self.page.query_selector(sel)
                if el and el.is_visible():
                    logger.info(f"[PAP] Fallback: clicando no menu 'Novo Pedido' (seletor: {sel[:50]}...)")
                    if self.capture_screenshots:
                        self._highlight_element(el, duration_ms=500)
                    el.click()
                    self.page.wait_for_timeout(1500)
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=12000)
                    except Exception:
                        pass
                    return True
            except Exception as e:
                logger.debug(f"[PAP] Menu Novo Pedido seletor {sel[:30]}: {e}")
                continue
        return False

    # No PAP, "Filtros" é um span.titulo-filtro (não <a>/<button>).
    _SELETOR_FILTROS_CONSULTA_OS = (
        'span.titulo-filtro:has-text("Filtros"), .titulo-filtro:has-text("Filtros"), '
        'span:has-text("Filtros"), button:has-text("Filtros"), '
        '[role="button"]:has-text("Filtros")'
    )
    _SELETOR_INPUT_CPF_FILTRO = (
        'input.input-text-filter[placeholder="Digite o CPF/CNPJ..."], input.input-text-filter'
    )
    _SELETOR_CONSULTA_OS_PRONTA = (
        'input.input-text-filter[placeholder*="CPF"], '
        'span.titulo-filtro:has-text("Filtros"), .titulo-filtro, '
        'button:has-text("Filtros"), button.btn-filters-new'
    )

    def _tela_consulta_os_carregada(self, timeout_ms: int = 5000) -> bool:
        """Verifica se a tela Consulta OS está pronta (controles visíveis, não só a URL)."""
        if not self.page:
            return False
        try:
            self.page.wait_for_selector(
                self._SELETOR_CONSULTA_OS_PRONTA,
                state="visible",
                timeout=timeout_ms,
            )
            return True
        except Exception:
            return False

    def _diagnosticar_tela_consulta_os(self) -> None:
        """Registra URL e trecho do DOM para depurar ausência do controle Filtros."""
        if not self.page:
            return
        try:
            url = (self.page.url or "")[:160]
            info = self.page.evaluate(
                """() => {
                    const textos = Array.from(document.querySelectorAll('span, button, a, [role="button"], h1, h2, label'))
                        .map(n => (n.textContent || '').trim())
                        .filter(t => t && t.length < 40)
                        .slice(0, 40);
                    const classes = Array.from(document.querySelectorAll('[class*="filtro"], [class*="Filtro"], [class*="filter"]'))
                        .map(n => n.className)
                        .slice(0, 10);
                    return {
                        title: document.title || '',
                        bodyLen: (document.body && document.body.innerText || '').length,
                        textos,
                        classes,
                    };
                }"""
            )
            logger.warning(
                "[PAP] Diagnóstico Consulta OS url=%s title=%s bodyLen=%s textos=%s classes_filtro=%s",
                url,
                (info or {}).get("title"),
                (info or {}).get("bodyLen"),
                (info or {}).get("textos"),
                (info or {}).get("classes"),
            )
        except Exception as e:
            logger.warning("[PAP] Diagnóstico Consulta OS falhou: %s (url=%s)", e, (self.page.url or "")[:120])

    def _abrir_menu_lateral_se_fechado(self) -> None:
        """Abre drawer/menu lateral quando colapsado (viewports menores)."""
        if not self.page:
            return
        try:
            loc_abrir = self.page.get_by_role(
                "button", name=re.compile(r"menu|abrir|navega", re.I)
            )
            if loc_abrir.count() > 0:
                botao = loc_abrir.first
                if botao.is_visible():
                    logger.info("[PAP] Abrindo menu lateral (botão menu)")
                    botao.click(timeout=4000)
                    self.page.wait_for_timeout(500)
        except Exception:
            pass

    def _clicar_menu_consulta_os_via_sidebar(self) -> bool:
        """Clica em Consulta OS no menu lateral (padrão estável pós-login em SPA)."""
        if not self.page:
            return False
        self._abrir_menu_lateral_se_fechado()

        def _apos_clique() -> None:
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass

        for nome, loc in (
            (
                "link role Consulta OS",
                self.page.get_by_role("link", name=re.compile(r"Consulta\s+OS", re.I)),
            ),
            (
                "menuitem Consulta OS",
                self.page.get_by_role("menuitem", name=re.compile(r"Consulta\s+OS", re.I)),
            ),
            (
                "aside/nav link",
                self.page.locator("aside a, nav a, [role='navigation'] a").filter(
                    has_text=re.compile(r"Consulta\s+OS", re.I)
                ),
            ),
            ("a[href*=consulta-os]", self.page.locator("a[href*='consulta-os']")),
            ("button texto Consulta OS", self.page.locator("button:has-text('Consulta OS')")),
        ):
            try:
                if loc.count() < 1:
                    continue
                alvo = loc.first
                alvo.wait_for(state="visible", timeout=8000)
                try:
                    alvo.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                logger.info("[PAP] Clicando menu Consulta OS (%s)", nome)
                if self.capture_screenshots:
                    try:
                        handle = alvo.element_handle()
                        if handle:
                            self._highlight_element(handle, duration_ms=500)
                    except Exception:
                        pass
                alvo.click(timeout=12000, force=True)
                _apos_clique()
                return True
            except Exception as e:
                logger.debug("[PAP] Menu Consulta OS (%s): %s", nome, e)
                continue

        seletores_menu = [
            'a[href*="consulta-os"]',
            'a:has-text("Consulta OS")',
            'span:has-text("Consulta OS")',
            "//span[contains(text(),'Consulta OS')]",
            "//a[contains(@href,'consulta-os')]",
        ]
        for sel in seletores_menu:
            try:
                if sel.startswith("//"):
                    el = self.page.query_selector(f"xpath={sel}")
                else:
                    el = self.page.query_selector(sel)
                if el and el.is_visible():
                    logger.info("[PAP] Clicando menu Consulta OS (seletor: %s...)", sel[:50])
                    if self.capture_screenshots:
                        self._highlight_element(el, duration_ms=500)
                    el.click()
                    _apos_clique()
                    return True
            except Exception as e:
                logger.debug("[PAP] Menu Consulta OS seletor %s: %s", sel[:30], e)
                continue
        return False

    def _navegar_consulta_os_url_direta(self, rapido: bool) -> bool:
        """
        Navega via URL direta. ERR_ABORTED é comum em SPA (redirect interrompe goto);
        valida pelos controles da tela (Filtros/input), não só pela URL.
        """
        if not self.page:
            return False
        try:
            self.page.goto(PAP_CONSULTA_OS_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("[PAP] goto Consulta OS: %s", e)

        # SPA do PAP demora a hidratar os controles após o goto.
        self.page.wait_for_timeout(800 if rapido else 1500)
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000 if rapido else 12000)
        except Exception:
            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass

        timeout_pronta = 15000 if rapido else 20000
        if self._tela_consulta_os_carregada(timeout_pronta):
            logger.info("[PAP] Navegação para Consulta OS OK (URL direta)")
            return True

        # Segunda chance: reload leve da rota (às vezes o 1º paint fica sem o toolbar).
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=20000)
            self.page.wait_for_timeout(1000)
            if self._tela_consulta_os_carregada(12000):
                logger.info("[PAP] Navegação para Consulta OS OK (URL direta, após reload)")
                return True
        except Exception as e:
            logger.debug("[PAP] Reload Consulta OS: %s", e)

        logger.warning(
            "[PAP] Consulta OS sem controles após URL direta (url=%s)",
            (self.page.url or "")[:120],
        )
        self._diagnosticar_tela_consulta_os()
        return False

    def _clicar_menu_consulta_os(self) -> Tuple[bool, str]:
        """
        Acessa a tela Consulta OS (menu lateral ou URL).
        Retorna (True, msg) se a tela ficou pronta; (False, motivo) caso contrário.
        """
        rapido = self.optimize_for_credit
        ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_CONSULTA_OS_URL)
        if not ok_sessao:
            logger.warning("[PAP] Sessão inválida antes da Consulta OS: %s", msg_sessao)
            return False, msg_sessao

        if self._tela_consulta_os_carregada(2000):
            logger.info("[PAP] Já na tela Consulta OS")
            return True, "Já na tela Consulta OS"

        # SPA do PAP pode ainda estar finalizando redirect pós-login
        self._aguardar_pagina_estavel(retries=2, delay_ms=1500 if rapido else 2500)
        self.page.wait_for_timeout(800 if rapido else 2000)

        for tentativa in range(1, 3):
            # STATUS (modo rápido): URL direta primeiro — evita ~6s abrindo menu lateral
            if rapido and self._navegar_consulta_os_url_direta(rapido):
                return True, "Consulta OS via URL direta"

            if self._clicar_menu_consulta_os_via_sidebar():
                if self._tela_consulta_os_carregada(12000 if rapido else 20000):
                    logger.info("[PAP] Navegação para Consulta OS OK (menu lateral)")
                    return True, "Consulta OS via menu lateral"

            if not rapido and self._navegar_consulta_os_url_direta(rapido):
                return True, "Consulta OS via URL direta"

            logger.warning(
                "[PAP] Tentativa %s/2 Consulta OS sem sucesso (url=%s)",
                tentativa,
                (self.page.url or "")[:120],
            )
            # Se caiu no IdP no meio do caminho, tenta relogin antes da 2ª tentativa.
            if self._esta_no_idp_vtal():
                ok_re, msg_re = self._relogin_pap(PAP_CONSULTA_OS_URL)
                if ok_re and self._tela_consulta_os_carregada(8000):
                    return True, "Consulta OS após relogin"
                if not ok_re:
                    return False, msg_re
            self.page.wait_for_timeout(1000)

        if self._esta_no_idp_vtal():
            if self._pagina_login_vtal_travada(url=(self.page.url or "")):
                return False, self._mensagem_falha_login_vtal()
            return False, "Sessão PAP redirecionou para login V.tal. Tente novamente."
        return False, "Não foi possível acessar a tela Consulta OS."

    def _localizar_controle_filtros_consulta_os(self, timeout_ms: int = 6000) -> Optional[Any]:
        """Retorna o locator do controle Filtros, priorizando span.titulo-filtro (não <a>/<button>)."""
        # PAP real: span.titulo-filtro. Evitar a:has-text("Filtros") — gera timeout falso e
        # no código legado a exceção do click vazava sem tratamento.
        seletores = [
            'span.titulo-filtro:has-text("Filtros")',
            '.titulo-filtro:has-text("Filtros")',
            'span.titulo-filtro',
            'span:text-is("Filtros")',
            'button:has-text("Filtros")',
            '[role="button"]:has-text("Filtros")',
            'text=Filtros',
        ]
        # Primeiro seletor leva o timeout cheio; os demais são tentativas rápidas.
        for idx, sel in enumerate(seletores):
            try:
                loc = self.page.locator(sel).first
                loc.wait_for(state="visible", timeout=timeout_ms if idx == 0 else 1200)
                return loc
            except Exception:
                continue
        return None

    def _abrir_painel_filtros_consulta_os(self, rapido: bool = False) -> Tuple[bool, str]:
        """
        Abre o painel de Filtros na Consulta OS e garante o campo CPF/CNPJ visível.

        No PAP o controle é um span.titulo-filtro e o painel costuma abrir no hover;
        em algumas versões/respostas lentas o click no span também funciona.
        """
        if not self.page:
            return False, "Sessão PAP indisponível."

        # Se o IdP roubou a sessão, tenta relogin antes de desistir dos filtros.
        if self._esta_no_idp_vtal(url=(self.page.url or "")):
            ok_re, msg_re = self._relogin_pap(PAP_CONSULTA_OS_URL)
            if not ok_re:
                return False, msg_re

        input_selector = self._SELETOR_INPUT_CPF_FILTRO
        hover_wait = 250 if rapido else 400
        click_wait = 400 if rapido else 600
        # STATUS em modo rápido ainda precisa de margem: a SPA hidrata o toolbar depois do URL.
        timeout_ms = 12000 if not rapido else 10000

        # Já aberto (ex.: sessão anterior deixou o painel visível).
        try:
            if self.page.locator(input_selector).first.is_visible(timeout=500):
                return True, "Painel de Filtros já aberto."
        except Exception:
            pass

        filtros_loc = self._localizar_controle_filtros_consulta_os(timeout_ms=timeout_ms)
        if filtros_loc is None:
            # Retry: espera networkidle e recarrega a rota uma vez.
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
            filtros_loc = self._localizar_controle_filtros_consulta_os(timeout_ms=8000)
        if filtros_loc is None:
            try:
                if "consulta-os" in (self.page.url or "").lower():
                    self.page.reload(wait_until="domcontentloaded", timeout=20000)
                else:
                    self.page.goto(PAP_CONSULTA_OS_URL, wait_until="domcontentloaded", timeout=30000)
                self.page.wait_for_timeout(1500)
                filtros_loc = self._localizar_controle_filtros_consulta_os(timeout_ms=12000)
            except Exception as e:
                logger.warning("[PAP] Retry navegação Consulta OS para Filtros: %s", e)
        if filtros_loc is None:
            logger.warning("[PAP] Controles de Filtros não apareceram na Consulta OS")
            self._diagnosticar_tela_consulta_os()
            return False, "Tela Consulta OS não exibiu o controle de Filtros."

        # Preferência: hover (comportamento nativo do PAP).
        try:
            filtros_loc.hover(timeout=timeout_ms)
            self.page.wait_for_timeout(hover_wait)
            self.page.wait_for_selector(input_selector, state="visible", timeout=timeout_ms)
            return True, "Painel de Filtros aberto (hover)."
        except Exception as e:
            logger.debug("[PAP] Hover em Filtros não abriu o painel: %s", e)

        # Fallback: click no span/botão (mesmo seletor do fluxo legado).
        try:
            filtros_loc.click(force=True, timeout=timeout_ms)
            self.page.wait_for_timeout(click_wait)
            self.page.wait_for_selector(input_selector, state="visible", timeout=timeout_ms)
            return True, "Painel de Filtros aberto (click)."
        except Exception as e:
            logger.warning("[PAP] Click em Filtros falhou: %s", e)

        # Último recurso: dispatch de mouseenter/click via JS no elemento com texto Filtros.
        try:
            aberto = self.page.evaluate(
                """() => {
                    const candidatos = Array.from(document.querySelectorAll(
                        'span.titulo-filtro, .titulo-filtro, span, button, a, [role="button"]'
                    ));
                    const el = candidatos.find(n => {
                        const t = (n.textContent || '').trim();
                        return t === 'Filtros' || (t.startsWith('Filtros') && t.length < 20);
                    });
                    if (!el) return false;
                    el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                    el.click();
                    return true;
                }"""
            )
            if aberto:
                self.page.wait_for_timeout(click_wait)
                self.page.wait_for_selector(input_selector, state="visible", timeout=timeout_ms)
                return True, "Painel de Filtros aberto (JS)."
        except Exception as e:
            logger.warning("[PAP] Fallback JS em Filtros falhou: %s", e)

        return False, "Painel de Filtros não abriu ou campo CPF/CNPJ não encontrado."

    def abrir_consulta_os_e_filtrar_cpf(self, cpf: str) -> Tuple[bool, str]:
        """
        Após login no PAP: acessa Consulta OS, clica em Filtros e preenche o CPF/CNPJ.
        Não extrai resultado da tabela; apenas deixa a tela filtrada para o usuário.
        Args:
            cpf: CPF apenas dígitos (11 ou 14 para CNPJ).
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            cpf_limpo = re.sub(r'\D', '', cpf) if cpf else ""
            if not cpf_limpo:
                return False, "CPF/CNPJ inválido (vazio)."

            if not self.logado:
                sucesso, msg = self.iniciar_sessao()
                if not sucesso:
                    return False, msg
            else:
                ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_CONSULTA_OS_URL)
                if not ok_sessao:
                    return False, msg_sessao

            # Ir para Consulta OS (URL direta ou menu)
            if self.capture_screenshots:
                self._capture_screenshot("consulta_os_01_antes", wait_selector=None, wait_timeout_ms=0)
            ok_menu, msg_menu = self._clicar_menu_consulta_os()
            if not ok_menu:
                return False, msg_menu
            self.page.wait_for_timeout(1500)

            ok_filtros, msg_filtros = self._abrir_painel_filtros_consulta_os(rapido=False)
            if not ok_filtros:
                return False, msg_filtros
            logger.info("[PAP] %s", msg_filtros)

            # Preencher CPF/CNPJ no input do filtro (force=True evita interceptação pelo MuiDrawer)
            input_selector = self._SELETOR_INPUT_CPF_FILTRO
            locator_cpf = self.page.locator(input_selector).first
            if locator_cpf.count() == 0:
                return False, "Não foi possível encontrar o campo CPF/CNPJ nos filtros."
            locator_cpf.fill(cpf_limpo, force=True, timeout=10000)
            self.page.wait_for_timeout(500)
            if self.capture_screenshots:
                self._capture_screenshot("consulta_os_02_cpf_preenchido", wait_selector=None, wait_timeout_ms=0)
            logger.info(f"[PAP] CPF/CNPJ preenchido nos filtros da Consulta OS: {cpf_limpo[:3]}***")
            return True, "Consulta OS aberta e filtro por CPF/CNPJ aplicado."
        except Exception as e:
            logger.exception(f"[PAP] abrir_consulta_os_e_filtrar_cpf: {e}")
            return False, str(e)

    def _screenshot_consulta_os_return_path(self, full_page: Optional[bool] = None) -> Optional[str]:
        """
        Tira screenshot da tela atual (Consulta OS) e retorna o caminho do arquivo.
        Usado para enviar a imagem no WhatsApp. Sempre salva, independente de capture_screenshots.
        """
        if not self.page:
            return None
        if full_page is None:
            full_page = not self.optimize_for_credit
        try:
            from django.conf import settings
            base_dir = getattr(settings, 'BASE_DIR', None)
            if not base_dir:
                return None
            downloads_dir = os.path.join(base_dir, 'downloads')
            os.makedirs(downloads_dir, exist_ok=True)
            safe_run = str(self.run_id).replace(os.sep, '_').replace('..', '_')[:50]
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"consulta_os_{safe_run}_{ts}.png"
            filepath = os.path.join(downloads_dir, filename)
            self.page.wait_for_timeout(100 if self.optimize_for_credit else 300)
            self.page.screenshot(path=filepath, full_page=full_page)
            logger.info(f"[PAP] Screenshot Consulta OS salvo: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"[PAP] Erro ao salvar screenshot Consulta OS: {e}")
            return None

    @staticmethod
    def _mensagem_erro_playwright(exc: BaseException) -> str:
        """Resume erros do Playwright sem o Call log (evita poluir relatório WhatsApp)."""
        msg = str(exc).strip() or exc.__class__.__name__
        # Primeira linha costuma ser "Locator.click: Timeout 5000ms exceeded."
        primeira = msg.splitlines()[0].strip()
        if "Timeout" in primeira and "locator(" in msg.lower():
            # Extrai seletor quando existir: waiting for locator("...")
            m = re.search(r'locator\("([^"]+)"\)', msg)
            if m:
                sel = m.group(1)
                if "Filtros" in sel:
                    return "Controle Filtros não encontrado na Consulta OS (timeout)."
                if "detalhe-os" in sel or "detalhar" in sel.lower():
                    return "Link Detalhar da OS não encontrado (timeout)."
                return f"Elemento não encontrado no PAP (timeout): {sel[:60]}"
            return primeira[:120]
        return primeira[:200]

    def consulta_os_por_cpf_com_resultado(
        self,
        cpf: str,
        numero_os_filtro: Optional[str] = None,
        os_prioridade_crm: Optional[set] = None,
    ) -> Tuple[bool, str, List[Dict[str, Any]], Optional[str]]:
        """
        Fluxo completo: login, Consulta OS, Filtros, CPF, período 30 dias, Filtrar.
        Lê a tabela e por linha detecta se existe link Detalhar (nao_pertence_pdv=False) ou não (não pertence ao PDV).
        Para cada linha com link Detalhar: abre o detalhe, extrai status_agendamento, agendamento, pendência e tira screenshot da tela de detalhe.
        Se numero_os_filtro for informado, filtra o resultado para retornar somente aquela OS (comparando com e sem zeros à esquerda).
        Returns:
            (sucesso, mensagem, lista de dicts com status/plano/numero_os/data_hora, nao_pertence_pdv,
             e quando tem Detalhar: status_agendamento, agendamento, pendencia, detail_screenshot_path),
            list_screenshot_path (screenshot da lista; usado quando só 1 pedido e não pertence ao PDV).
            Se não houver pedidos: (True, "no_results", [], list_screenshot_path).
        """
        try:
            return self._consulta_os_por_cpf_com_resultado_impl(
                cpf,
                numero_os_filtro=numero_os_filtro,
                os_prioridade_crm=os_prioridade_crm,
            )
        except Exception as e:
            # Nunca deixar Locator.click/Timeout vazar sem tratamento (sync esteira / STATUS).
            logger.warning("[PAP] consulta_os_por_cpf_com_resultado: %s", e)
            return False, self._mensagem_erro_playwright(e), [], None

    def _consulta_os_por_cpf_com_resultado_impl(
        self,
        cpf: str,
        numero_os_filtro: Optional[str] = None,
        os_prioridade_crm: Optional[set] = None,
    ) -> Tuple[bool, str, List[Dict[str, Any]], Optional[str]]:
        from datetime import timedelta
        cpf_limpo = re.sub(r'\D', '', cpf) if cpf else ""
        if not cpf_limpo:
            return False, "CPF/CNPJ inválido (vazio).", [], None

        if not self.logado:
            sucesso, msg = self.iniciar_sessao()
            if not sucesso:
                return False, msg, [], None
        else:
            ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_CONSULTA_OS_URL)
            if not ok_sessao:
                return False, msg_sessao, [], None

        rapido = self.optimize_for_credit
        ok_menu, msg_menu = self._clicar_menu_consulta_os()
        if not ok_menu:
            return False, msg_menu, [], None
        self.page.wait_for_timeout(350 if rapido else 1000)

        ok_filtros, msg_filtros = self._abrir_painel_filtros_consulta_os(rapido=rapido)
        if not ok_filtros:
            return False, msg_filtros, [], None
        logger.info("[PAP] %s", msg_filtros)

        input_selector = self._SELETOR_INPUT_CPF_FILTRO
        # Preencher CPF/CNPJ e clicar Filtrar (reduzidos waits para agilizar)
        locator_cpf = self.page.locator(input_selector).first
        try:
            if locator_cpf.count() == 0:
                return False, "Campo CPF/CNPJ não encontrado nos filtros.", [], None
            locator_cpf.fill(cpf_limpo, force=True, timeout=8000)
        except Exception as e:
            logger.warning(f"[PAP] fill CPF com force falhou: {e}")
            return False, f"Não foi possível preencher CPF/CNPJ no filtro: {e}", [], None
        self.page.wait_for_timeout(150)

        # Período: últimos 30 dias (já costuma vir preenchido; preenche só se necessário)
        hoje = datetime.now().date()
        data_ate = hoje
        data_de = hoje - timedelta(days=30)
        str_de = data_de.strftime("%d/%m/%Y")
        str_ate = data_ate.strftime("%d/%m/%Y")
        date_inputs = self.page.query_selector_all('input[type="date"], input[placeholder*="/"], input[placeholder*="De"], input[placeholder*="Até"]')
        if len(date_inputs) >= 2:
            try:
                date_inputs[0].fill(str_de)
                self.page.wait_for_timeout(80)
                date_inputs[1].fill(str_ate)
                self.page.wait_for_timeout(80)
            except Exception:
                pass
        self.page.wait_for_timeout(100)

        # Clicar em Filtrar
        btn_selector = 'button.btn-filters-new, button:has-text("Filtrar")'
        locator_btn = self.page.locator(btn_selector).first
        try:
            if locator_btn.count() == 0:
                return False, "Botão 'Filtrar' não encontrado.", [], None
            locator_btn.click(force=True, timeout=8000)
        except Exception as e:
            logger.warning(f"[PAP] click Filtrar falhou: {e}")
            return False, f"Não foi possível clicar em Filtrar: {e}", [], None
        # Esperar a tabela de resultados carregar (pode demorar; colunas: STATUS, PLANO, NÚMERO DA OS, DATA E HORA [DA CRIAÇÃO], DETALHES)
        try:
            self.page.wait_for_selector(
                'td.MuiTableCell-root.MuiTableCell-body, table tbody td, [class*="MuiTableCell-body"]',
                state="visible",
                timeout=12000 if not rapido else 10000,
            )
            self.page.wait_for_timeout(250 if rapido else 800)
        except Exception as e:
            logger.debug(f"[PAP] Espera da tabela Consulta OS: {e}")
        self.page.wait_for_timeout(200 if rapido else 500)

        # Ler tabela: 4 colunas de dados (0=STATUS, 1=PLANO, 2=NÚMERO DA OS, 3=DATA E HORA); 5ª coluna = DETALHES (link "Detalhar" ou vazio)
        detalhes: List[Dict[str, Any]] = []
        try:
            # Tentar por linhas da tabela
            rows = self.page.query_selector_all(SELETORES['consulta_os']['table_rows'])
            for row in rows:
                cells = row.query_selector_all('td.MuiTableCell-root.MuiTableCell-body, td[class*="MuiTableCell"], td')
                if len(cells) >= 4:
                    status = (cells[0].inner_text() or "").strip()
                    plano = (cells[1].inner_text() or "").strip()
                    numero_os = (cells[2].inner_text() or "").strip()
                    data_hora = (cells[3].inner_text() or "").strip()
                    # 5ª célula (DETALHES): se não tiver link "Detalhar" = pedido não pertence ao PDV
                    tem_detalhar = False
                    detalhe_href = None
                    if len(cells) >= 5:
                        cell_detalhes = cells[4]
                        link = cell_detalhes.query_selector('a.detalhar-link[href*="detalhe-os"], a[href*="detalhe-os"]')
                        if link:
                            tem_detalhar = True
                            try:
                                detalhe_href = link.get_attribute("href")
                            except Exception:
                                pass
                        if not tem_detalhar and "detalhar" in (cell_detalhes.inner_text() or "").lower():
                            tem_detalhar = True
                    item = {
                        "status": status,
                        "plano": plano,
                        "numero_os": numero_os,
                        "data_hora": data_hora,
                        "nao_pertence_pdv": not tem_detalhar,
                        "detalhe_href": detalhe_href,
                    }
                    if status or plano or numero_os or data_hora:
                        detalhes.append(item)
            # Fallback: todas as células em sequência (4 ou 5 colunas por linha)
            if not detalhes:
                cells_direct = self.page.query_selector_all(
                    'td.MuiTableCell-root.MuiTableCell-body, td[class*="MuiTableCell-body"], table tbody td'
                )
                if cells_direct:
                    col_per_row = 5 if len(cells_direct) >= 5 and len(cells_direct) % 5 == 0 else 4
                    if len(cells_direct) % col_per_row != 0:
                        col_per_row = 4
                    idx = 0
                    while idx + 4 <= len(cells_direct):
                        status = (cells_direct[idx].inner_text() or "").strip()
                        plano = (cells_direct[idx + 1].inner_text() or "").strip()
                        numero_os = (cells_direct[idx + 2].inner_text() or "").strip()
                        data_hora = (cells_direct[idx + 3].inner_text() or "").strip()
                        tem_detalhar = False
                        detalhe_href_fb = None
                        if col_per_row >= 5 and idx + 5 <= len(cells_direct):
                            cell_d = cells_direct[idx + 4]
                            link_fb = cell_d.query_selector(
                                'a.detalhar-link[href*="detalhe-os"], a[href*="detalhe-os"]'
                            )
                            if link_fb:
                                tem_detalhar = True
                                try:
                                    detalhe_href_fb = link_fb.get_attribute("href")
                                except Exception:
                                    pass
                            elif "detalhar" in (cell_d.inner_text() or "").lower():
                                tem_detalhar = True
                        if status or plano or numero_os or data_hora:
                            detalhes.append({
                                "status": status,
                                "plano": plano,
                                "numero_os": numero_os,
                                "data_hora": data_hora,
                                "nao_pertence_pdv": not tem_detalhar,
                                "detalhe_href": detalhe_href_fb,
                            })
                        idx += col_per_row
        except Exception as e:
            logger.warning(f"[PAP] Erro ao ler tabela Consulta OS: {e}")

        # Se for consulta por OS (via filtro), reduzir a lista antes de abrir detalhes para evitar abrir várias OS do mesmo CPF
        if detalhes and numero_os_filtro:
            filtro_raw = re.sub(r"\D", "", str(numero_os_filtro)).strip()
            filtro_sem_zero = (filtro_raw.lstrip("0") or filtro_raw) if filtro_raw else ""
            if filtro_raw:
                filtrados = []
                for d in detalhes:
                    os_tbl = re.sub(r"\D", "", str(d.get("numero_os") or "")).strip()
                    os_tbl_sem_zero = os_tbl.lstrip("0") or os_tbl
                    if os_tbl == filtro_raw or os_tbl_sem_zero == filtro_sem_zero:
                        filtrados.append(d)
                detalhes = filtrados

        from crm_app.utils import ordenar_detalhes_pap_por_os_prioridade

        detalhes = ordenar_detalhes_pap_por_os_prioridade(detalhes, os_prioridade_crm or set())

        list_screenshot_path = None

        # Para cada OS que tem link Detalhar: abrir detalhe, extrair dados + Pendência e tirar screenshot da tela de detalhe
        if detalhes:
            for row in detalhes:
                if row.get("nao_pertence_pdv"):
                    continue
                num_os = (row.get("numero_os") or "").strip()
                if not num_os:
                    continue
                st_ag, ag_texto, pendencia, detail_screenshot_path = self.abrir_detalhe_os_e_extrair(
                    num_os, detalhe_href=row.get("detalhe_href")
                )
                if st_ag is not None:
                    row["status_agendamento"] = st_ag
                if ag_texto is not None:
                    row["agendamento"] = ag_texto
                if pendencia is not None:
                    row["pendencia"] = pendencia
                if detail_screenshot_path:
                    row["detail_screenshot_path"] = detail_screenshot_path

        # Screenshot da lista só quando necessário (sem print de detalhe / não pertence ao PDV)
        if detalhes:
            precisa_lista = any(
                row.get("nao_pertence_pdv") or not row.get("detail_screenshot_path")
                for row in detalhes
            )
            if precisa_lista:
                list_screenshot_path = self._screenshot_consulta_os_return_path()

        if detalhes:
            return True, "ok", detalhes, list_screenshot_path
        list_screenshot_path = self._screenshot_consulta_os_return_path()
        return True, "no_results", [], list_screenshot_path

    _RE_PENDENCIA_CODIGO_PAP = re.compile(r"^\d{4}\s*-\s*.+", re.I)

    def _extrair_valor_rotulo_detalhe_pap(self, rotulo_exato: str) -> Optional[str]:
        """
        Lê o valor ao lado de um rótulo exato na tela de detalhe OS
        (ex.: rótulo <span>Pendência</span> → valor <span>7029 - AGENDAMENTO DO PEDIDO</span>).
        """
        try:
            label = self.page.get_by_text(rotulo_exato, exact=True).first
            if label.count() == 0:
                return None
            candidatos = []
            for loc in (
                label.locator("xpath=following-sibling::span[1]"),
                label.locator("xpath=../span[contains(@class,'fLfXPS')]"),
                label.locator("xpath=../following-sibling::span[1]"),
                label.locator("xpath=ancestor::*[1]//span[contains(@class,'fLfXPS')]"),
            ):
                try:
                    if loc.count() > 0:
                        t = (loc.first.inner_text() or "").strip()
                        if t and t.lower() != rotulo_exato.lower():
                            candidatos.append(t)
                except Exception:
                    pass
            for t in candidatos:
                if self._RE_PENDENCIA_CODIGO_PAP.match(t) or rotulo_exato != "Pendência":
                    return t
            return candidatos[0] if candidatos else None
        except Exception:
            return None

    def _buscar_pendencia_codigo_detalhe_pap(self) -> Optional[str]:
        """Busca texto de pendência com código (7029 - …), ignorando rótulos genéricos."""
        try:
            t_rotulo = self._extrair_valor_rotulo_detalhe_pap("Pendência")
            if t_rotulo and self._RE_PENDENCIA_CODIGO_PAP.match(t_rotulo.strip()):
                return t_rotulo.strip()
        except Exception:
            pass
        try:
            for s in self.page.locator("span.sc-gOhSNZ.fLfXPS, span.fLfXPS").all():
                t = (s.inner_text() or "").strip()
                if t and self._RE_PENDENCIA_CODIGO_PAP.match(t):
                    return t
        except Exception:
            pass
        try:
            for s in self.page.locator(
                "span.sc-jrOYZv.ldMRLh, span.ldMRLh, span.sc-gOhSNZ.fLfXPS"
            ).all():
                t = (s.inner_text() or "").strip()
                if t and self._RE_PENDENCIA_CODIGO_PAP.match(t):
                    return t
        except Exception:
            pass
        return None

    def abrir_detalhe_os_e_extrair(
        self, numero_os: str, detalhe_href: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Na tela de Consulta OS (após filtrar), abre o link Detalhar da OS e extrai na página de detalhe:
        - Status agendamento: valor ao lado do rótulo "Status agendamento"
        - Agendamento: valor ao lado do rótulo "Agendamento"
        - Pendência: valor ao lado do rótulo "Pendência" (ex.: "7029 - AGENDAMENTO DO PEDIDO")
        Tira screenshot da tela de detalhe antes de voltar.
        Returns:
            (status_agendamento, agendamento, pendencia, screenshot_path)
        """
        num = (numero_os or "").strip()
        num_sem_zero = num.lstrip("0") or num
        try:
            link = None
            href = (detalhe_href or "").strip()
            if href:
                link = self.page.locator(f'a.detalhar-link[href="{href}"]').first
                if link.count() == 0:
                    link = self.page.locator(f'a[href="{href}"]').first
                if link.count() == 0:
                    frag = href.split("detalhe-os/")[-1].strip("/")
                    if frag:
                        link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{frag}"]').first
            if not link or link.count() == 0:
                link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{num}"]').first
            if link.count() == 0 and num_sem_zero != num:
                link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{num_sem_zero}"]').first
            if link.count() == 0:
                logger.warning("[PAP] Link Detalhar não encontrado para OS %s (href=%s)", num, href or "-")
                return None, None, None, None
            rapido = self.optimize_for_credit
            link.click(force=True, timeout=5000)
            if rapido:
                try:
                    self.page.wait_for_url(re.compile(r"detalhe-os", re.I), timeout=8000)
                except Exception:
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                self.page.wait_for_timeout(200)
            else:
                self.page.wait_for_timeout(1500)
                url_atual = self.page.url
                if "detalhe-os" not in (url_atual or ""):
                    self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            status_agendamento = None
            agendamento_texto = None
            pendencia_texto = None
            # Status agendamento
            try:
                loc_st = self.page.get_by_text("Status agendamento", exact=False).locator(
                    ".."
                ).locator(
                    "span.ldMRLh, span.sc-jrOYZv.ldMRLh, span.sc-gOhSNZ.fLfXPS"
                ).first
                if loc_st.count() > 0:
                    status_agendamento = (loc_st.inner_text() or "").strip()
            except Exception:
                pass
            # Agendamento (exact=True evita casar com o rótulo "Status agendamento")
            try:
                loc_ag = self.page.get_by_text("Agendamento", exact=True).locator(
                    ".."
                ).locator(
                    "span.ldMRLh, span.sc-jrOYZv.ldMRLh, span.sc-gOhSNZ.fLfXPS"
                ).first
                if loc_ag.count() > 0:
                    agendamento_texto = (loc_ag.inner_text() or "").strip()
            except Exception:
                pass
            # Pendência (ex.: "7029 - AGENDAMENTO DO PEDIDO") — rótulo exato, não "Pendência Cliente"
            pendencia_texto = self._buscar_pendencia_codigo_detalhe_pap()
            # Fallback: outros spans do detalhe
            if not status_agendamento or not agendamento_texto or not pendencia_texto:
                spans = self.page.locator(
                    'span.sc-jrOYZv.ldMRLh, span.ldMRLh, span.sc-gOhSNZ.fLfXPS'
                ).all()
                for s in spans:
                    t = (s.inner_text() or "").strip()
                    if not t:
                        continue
                    if re.match(r'\d{2}/\d{2}/\d{4}\s*-\s*(Tarde|Manhã)', t) and not agendamento_texto:
                        agendamento_texto = t
                    if ("concluído" in t.lower() or "sucesso" in t.lower()) and not status_agendamento:
                        status_agendamento = t
                    if self._RE_PENDENCIA_CODIGO_PAP.match(t) and not pendencia_texto:
                        pendencia_texto = t
            if pendencia_texto and not self._RE_PENDENCIA_CODIGO_PAP.match(pendencia_texto):
                codigo_ok = self._buscar_pendencia_codigo_detalhe_pap()
                if codigo_ok:
                    pendencia_texto = codigo_ok
            self.page.wait_for_timeout(150 if rapido else 300)
            detail_screenshot_path = self._screenshot_consulta_os_return_path()
            self.page.go_back()
            if rapido:
                self.page.wait_for_timeout(400)
                try:
                    self.page.wait_for_selector(
                        'td.MuiTableCell-root.MuiTableCell-body, table tbody tr',
                        state="visible",
                        timeout=5000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(150)
            else:
                self.page.wait_for_timeout(1000)
                try:
                    self.page.wait_for_selector(
                        'td.MuiTableCell-root.MuiTableCell-body, table tbody tr',
                        state="visible",
                        timeout=10000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(400)
            return (
                status_agendamento or None,
                agendamento_texto or None,
                pendencia_texto or None,
                detail_screenshot_path,
            )
        except Exception as e:
            logger.warning(f"[PAP] abrir_detalhe_os_e_extrair {numero_os}: {e}")
            try:
                self.page.go_back()
            except Exception:
                pass
            return None, None, None, None

    def _variantes_busca_matricula_vendedor(self, matricula: str) -> List[str]:
        """Gera termos de busca para o autocomplete de vendedor (formato do PAP varia)."""
        m = (matricula or "").strip()
        if not m:
            return []
        variantes: List[str] = []
        for candidato in (m, m.upper(), m.lower()):
            if candidato and candidato not in variantes:
                variantes.append(candidato)
        digitos = re.sub(r"\D", "", m)
        if digitos and digitos not in variantes:
            variantes.append(digitos)
        upper = m.upper()
        if upper.startswith("TT") and len(upper) > 2:
            sem_prefixo = upper[2:]
            if sem_prefixo not in variantes:
                variantes.append(sem_prefixo)
        return variantes

    def _texto_item_vendedor_invalido(self, texto: str) -> bool:
        t = (texto or "").lower().strip()
        return (
            not t
            or "nenhum resultado" in t
            or "sem resultado" in t
            or "não encontr" in t
            or "nao encontr" in t
        )

    def _extrair_matricula_de_item_vendedor(self, texto: str) -> Optional[str]:
        """Extrai TT123456 do texto exibido no dropdown de vendedor."""
        return self._extrair_matricula_de_texto_vendedor(texto)

    def _debounce_lista_vendedor_ms(self, paciente: bool = False) -> int:
        """Headless no servidor precisa de mais tempo para o autocomplete do PAP."""
        if paciente or self.headless:
            return 3200 if self.optimize_for_credit else 4000
        return 1200 if self.optimize_for_credit else 1500

    def _timeout_lista_vendedor_ms(self, paciente: bool = False) -> int:
        if paciente or self.headless:
            return 18000 if self.optimize_for_credit else 22000
        return 12000 if self.optimize_for_credit else 15000

    def _coletar_itens_lista_vendedor(self, relaxar_visibilidade: bool = False) -> List[Any]:
        """Itens do dropdown de vendedor. Em headless, relaxa is_visible() se necessário."""
        if not self.page:
            return []
        seletores = list(SELETORES_LISTA_VENDEDOR_ITENS) + [SELETORES["etapa1"]["lista_vendedores"]]

        def _filtrar(itens: List[Any], exigir_visivel: bool) -> List[Any]:
            candidatos = itens
            if exigir_visivel:
                candidatos = [el for el in itens if el.is_visible()]
            return [
                el for el in candidatos
                if not self._texto_item_vendedor_invalido(el.inner_text() or "")
                and self._extrair_matricula_de_item_vendedor(el.inner_text() or "")
            ]

        for sel in seletores:
            try:
                itens = self.page.query_selector_all(sel)
                validos = _filtrar(itens, exigir_visivel=True)
                if validos:
                    return validos
                if relaxar_visibilidade or self.headless:
                    validos = _filtrar(itens, exigir_visivel=False)
                    if validos:
                        logger.info(
                            "[PAP] Lista vendedor coletada (visibilidade relaxada): %s itens",
                            len(validos),
                        )
                        return validos
            except Exception:
                continue
        return []

    def _matriculas_de_itens_vendedor(self, itens: List[Any]) -> List[str]:
        """Extrai matrículas TT dos itens visíveis do dropdown."""
        encontradas: List[str] = []
        vistos: set[str] = set()
        for item in itens:
            mat = self._extrair_matricula_de_item_vendedor(item.inner_text() or "")
            if mat and mat not in vistos:
                vistos.add(mat)
                encontradas.append(mat)
        return encontradas

    def _atualizar_cache_matriculas_pap(self, itens: List[Any]) -> List[str]:
        """Guarda matrículas vistas no dropdown para o fluxo de crédito."""
        mats = self._matriculas_de_itens_vendedor(itens)
        if mats:
            self._cache_matriculas_pap_dropdown = mats
        return mats

    def obter_cache_matriculas_pap_dropdown(self) -> List[str]:
        return list(self._cache_matriculas_pap_dropdown or [])

    def _termos_gatilho_lista_vendedor(self, matricula_alvo: Optional[str] = None) -> List[str]:
        """
        Termos que costumam abrir o autocomplete de vendedor no PAP.
        Termos curtos (T, TT) não disparam a API; matrícula inexistente lista o PDV inteiro.
        """
        termos: List[str] = []
        if matricula_alvo:
            termos.extend(self._variantes_busca_matricula_vendedor(matricula_alvo))
        termos.extend(
            [
                "999999",
                "000000",
                "TT999999",
                "478091",
                "478",
                "652",
                "TT4",
                "TT6",
                "T",
                "TT",
                "4",
                "7",
            ]
        )
        vistos: set[str] = set()
        unicos: List[str] = []
        for termo in termos:
            t = (termo or "").strip()
            if t and t not in vistos:
                vistos.add(t)
                unicos.append(t)
        return unicos

    def _focar_campo_vendedor(self) -> bool:
        """Clica e foca o autocomplete de vendedor (scroll no headless)."""
        matricula_input = self._query_matricula_vendedor_input()
        if not matricula_input or not self.page:
            return False
        try:
            matricula_input.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            matricula_input.click()
            matricula_input.focus()
            return True
        except Exception as e:
            logger.warning("[PAP] Falha ao focar campo vendedor: %s", e)
            return False

    def _mesclar_fontes_matriculas_vendedor(
        self, itens_dom: List[Any], paciente: bool = False
    ) -> List[str]:
        """Combina matrículas do DOM, scan JS e interceptação de API."""
        mats = self._matriculas_de_itens_vendedor(itens_dom)
        for fonte in (self._coletar_matriculas_dom_via_js(), self._matriculas_da_rede_vendedor()):
            for mat in fonte:
                if mat not in mats:
                    mats.append(mat)
        if mats:
            self._cache_matriculas_pap_dropdown = mats
        elif paciente or self.headless:
            logger.warning(
                "[PAP] Nenhuma matrícula vendedor (dom=%s api=%s js=%s headless=%s)",
                len(itens_dom),
                len(self._matriculas_da_rede_vendedor()),
                len(self._coletar_matriculas_dom_via_js()),
                self.headless,
            )
        return mats

    def _disparar_itens_lista_vendedor(
        self, matricula_alvo: Optional[str] = None, paciente: bool = False
    ) -> List[Any]:
        """Tenta abrir o dropdown de vendedor e retorna itens visíveis."""
        if not self.page:
            return []
        debounce_ms = self._debounce_lista_vendedor_ms(paciente=paciente)
        timeout_list = self._timeout_lista_vendedor_ms(paciente=paciente)
        seletor_lista = ", ".join(SELETORES_LISTA_VENDEDOR_ITENS[:8])
        relaxar = paciente or self.headless

        if not self._focar_campo_vendedor():
            logger.warning("[PAP] Campo vendedor não encontrado ao abrir lista")
            return []

        self._abrir_popup_vendedor_mui()
        self.page.wait_for_timeout(500 if paciente else 350)
        itens_popup = self._coletar_itens_lista_vendedor(relaxar_visibilidade=relaxar)
        if itens_popup:
            logger.info("[PAP] Lista vendedor aberta via popup MUI (%s itens)", len(itens_popup))
            return itens_popup

        gatilhos_prioritarios = ("999999", "478091", "478", "TT478091", "652271", "TT652")
        for gatilho in gatilhos_prioritarios:
            try:
                if not self._digitar_no_campo_vendedor(gatilho):
                    continue
                try:
                    self.page.wait_for_selector(seletor_lista, state="attached", timeout=timeout_list)
                except Exception:
                    pass
                self.page.wait_for_timeout(debounce_ms)
                itens = self._coletar_itens_lista_vendedor(relaxar_visibilidade=relaxar)
                if itens:
                    logger.info(
                        "[PAP] Lista vendedor aberta com gatilho '%s' (%s itens, headless=%s)",
                        gatilho,
                        len(itens),
                        self.headless,
                    )
                    return itens
                rede = self._matriculas_da_rede_vendedor()
                if rede:
                    logger.info(
                        "[PAP] Matrículas via API após gatilho '%s': %s",
                        gatilho,
                        rede[:8],
                    )
            except Exception as e:
                logger.debug("[PAP] gatilho lista vendedor termo=%s: %s", gatilho, e)

        try:
            if self._focar_campo_vendedor():
                matricula_input = self._query_matricula_vendedor_input()
                if matricula_input:
                    matricula_input.fill("")
                    self.page.wait_for_timeout(400)
                    matricula_input.press("ArrowDown")
                    self.page.wait_for_timeout(debounce_ms)
                    itens = self._coletar_itens_lista_vendedor(relaxar_visibilidade=relaxar)
                    if itens:
                        logger.info("[PAP] Lista vendedor aberta com ArrowDown (%s itens)", len(itens))
                        return itens
        except Exception as e:
            logger.debug("[PAP] ArrowDown lista vendedor: %s", e)

        for termo in self._termos_gatilho_lista_vendedor(matricula_alvo):
            try:
                if not self._digitar_no_campo_vendedor(termo):
                    continue
                try:
                    self.page.wait_for_selector(seletor_lista, state="attached", timeout=timeout_list)
                except Exception:
                    pass
                self.page.wait_for_timeout(debounce_ms)
                itens = self._coletar_itens_lista_vendedor(relaxar_visibilidade=relaxar)
                if itens:
                    logger.info(
                        "[PAP] Lista vendedor aberta com gatilho '%s' (%s itens)",
                        termo,
                        len(itens),
                    )
                    return itens
                logger.debug("[PAP] Gatilho '%s' não abriu lista de vendedores", termo)
            except Exception as e:
                logger.debug("[PAP] gatilho lista vendedor termo=%s: %s", termo, e)
        return []

    def _abrir_dropdown_vendedor_e_coletar(self, paciente: bool = False) -> List[str]:
        """Abre o autocomplete de vendedor e coleta matrículas visíveis no PDV."""
        if not self.page:
            return []
        itens = self._disparar_itens_lista_vendedor(paciente=paciente)
        return self._mesclar_fontes_matriculas_vendedor(itens, paciente=paciente)

    def listar_matriculas_vendedor_no_pap(
        self, forcar_recarga: bool = False, paciente: bool = False
    ) -> List[str]:
        """
        Lê matrículas disponíveis no autocomplete de vendedor do PDV logado.
        Usado no crédito para não escolher TT da OSAB que não existem neste portal.
        """
        if not forcar_recarga and self._cache_matriculas_pap_dropdown:
            return list(self._cache_matriculas_pap_dropdown)
        if self.page:
            self._instalar_listener_vendedores_api()
            espera = 5000 if (paciente or self.headless) else 1500
            if self.optimize_for_credit and not paciente and not self.headless:
                espera = 1500
            self.page.wait_for_timeout(espera)
        encontradas = self._abrir_dropdown_vendedor_e_coletar(paciente=paciente)
        logger.info("[PAP] Matrículas no dropdown vendedor deste PDV: %s", len(encontradas))
        if encontradas:
            logger.info("[PAP] Amostra vendedores PDV: %s", encontradas[:10])
        elif not paciente:
            logger.warning(
                "[PAP] Lista vendedor vazia (headless=%s fast=%s)",
                self.headless,
                self.optimize_for_credit,
            )
        return encontradas

    def _selecionar_vendedor_clicando_na_lista_aberta(self, matricula_norm: str) -> bool:
        """Crédito: abre lista ampla do PDV e clica no item da matrícula exata."""
        if not self.page or not matricula_norm:
            return False
        itens = self._disparar_itens_lista_vendedor(matricula_norm, paciente=self.headless)
        self._atualizar_cache_matriculas_pap(itens)
        for item in itens:
            mat_item = self._extrair_matricula_de_item_vendedor(item.inner_text() or "")
            if mat_item == matricula_norm:
                logger.info("[PAP] Vendedor selecionado na lista (crédito): %s", mat_item)
                item.click()
                self.page.wait_for_timeout(400)
                return True
        return False

    def _botao_avancar_etapa1_habilitado(self) -> bool:
        """Indica se a etapa 1 aceita avançar (vendedor selecionado)."""
        if not self.page:
            return False
        try:
            btn = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            return btn is not None
        except Exception:
            return False

    def _clicar_opcao_vendedor_via_js(self, matricula_norm: str) -> bool:
        """Clica na opção do autocomplete via DOM (headless, sem depender de is_visible)."""
        if not self.page or not matricula_norm:
            return False
        try:
            clicou = self.page.evaluate(
                """(matricula) => {
                    const alvo = (matricula || '').toUpperCase();
                    const digitos = alvo.replace(/\\D/g, '');
                    const seletores = [
                        '[role="option"]',
                        '[role="listbox"] li',
                        '.MuiAutocomplete-option',
                        'li[class*="option"]',
                        'li',
                    ];
                    for (const sel of seletores) {
                        for (const el of document.querySelectorAll(sel)) {
                            const txt = (el.innerText || el.textContent || '').trim().toUpperCase();
                            if (!txt || txt.includes('NENHUM') || txt.includes('SEM RESULTADO')) {
                                continue;
                            }
                            const txtDigitos = txt.replace(/\\D/g, '');
                            if (txt.includes(alvo) || (digitos && txtDigitos.includes(digitos))) {
                                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }""",
                matricula_norm,
            )
            if clicou:
                self.page.wait_for_timeout(800)
                if self._botao_avancar_etapa1_habilitado():
                    logger.info("[PAP] Vendedor selecionado via JS: %s", matricula_norm)
                    return True
        except Exception as exc:
            logger.debug("[PAP] JS click vendedor: %s", exc)
        return False

    def _selecionar_vendedor_por_teclado(self, matricula_norm: str) -> bool:
        """Digita a matrícula e confirma com teclado (ArrowDown/Enter)."""
        if not self.page or not matricula_norm:
            return False
        if not self._focar_campo_vendedor():
            return False
        if not self._digitar_no_campo_vendedor(matricula_norm):
            return False
        debounce_ms = 1200 if self._credito_pool_osab_headless() else self._debounce_lista_vendedor_ms(paciente=self.headless)
        self.page.wait_for_timeout(debounce_ms)
        matricula_input = self._query_matricula_vendedor_input()
        if not matricula_input:
            return False
        sequencias = (["ArrowDown", "Enter"], ["Enter"], ["Tab"])
        pausa_tecla_ms = 250 if self._credito_pool_osab_headless() else 450
        for seq in sequencias:
            try:
                for tecla in seq:
                    matricula_input.press(tecla)
                    self.page.wait_for_timeout(pausa_tecla_ms)
                if self._botao_avancar_etapa1_habilitado():
                    logger.info(
                        "[PAP] Vendedor confirmado por teclado (%s): %s",
                        "+".join(seq),
                        matricula_norm,
                    )
                    return True
            except Exception as exc:
                logger.debug("[PAP] teclado vendedor seq=%s: %s", seq, exc)
        return False

    def _selecionar_vendedor_matricula_etapa1(self, matricula_vendedor: str) -> bool:
        """
        Preenche o autocomplete de vendedor na etapa 1 e seleciona a opção correspondente.
        """
        matricula_input = self._query_matricula_vendedor_input()
        if not matricula_input or not self.page:
            return False

        matricula_norm = (matricula_vendedor or "").strip().upper()
        credito_headless = self._credito_pool_osab_headless()
        if matricula_norm and (self.optimize_for_credit or self.headless):
            for metodo, fn in (
                ("teclado", lambda: self._selecionar_vendedor_por_teclado(matricula_norm)),
                ("js", lambda: self._clicar_opcao_vendedor_via_js(matricula_norm)),
            ):
                try:
                    if fn():
                        return True
                except Exception as exc:
                    logger.debug("[PAP] seleção vendedor (%s): %s", metodo, exc)
            if credito_headless:
                logger.warning(
                    "[PAP] Crédito headless: TT %s não selecionada via teclado/JS; "
                    "falha rápida (sem gatilhos de dropdown).",
                    matricula_norm,
                )
                return False
            if self.optimize_for_credit and self._selecionar_vendedor_clicando_na_lista_aberta(matricula_norm):
                return True

        if credito_headless:
            return False

        rapido = self.optimize_for_credit
        debounce_ms = 600 if rapido else 900

        for termo in self._variantes_busca_matricula_vendedor(matricula_vendedor):
            try:
                if not self._digitar_no_campo_vendedor(termo):
                    continue
                seletor_visivel = ", ".join(SELETORES_LISTA_VENDEDOR_ITENS[:6])
                try:
                    self.page.wait_for_selector(
                        seletor_visivel,
                        state="visible",
                        timeout=7000 if rapido else 10000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(debounce_ms)

                digitos_termo = re.sub(r"\D", "", termo)
                for item in self._coletar_itens_lista_vendedor(relaxar_visibilidade=self.headless):
                    texto = (item.inner_text() or "").strip()
                    if self._texto_item_vendedor_invalido(texto):
                        continue
                    texto_upper = texto.upper()
                    termo_upper = termo.upper()
                    digitos_texto = re.sub(r"\D", "", texto)
                    if (
                        termo_upper in texto_upper
                        or (digitos_termo and digitos_termo in digitos_texto)
                    ):
                        logger.info(
                            "[PAP] Vendedor selecionado (termo=%s): %s",
                            termo,
                            texto[:80],
                        )
                        item.click()
                        self.page.wait_for_timeout(400)
                        return True
                try:
                    opt = self.page.locator(
                        f'[role="option"]:has-text("{matricula_norm}"), '
                        f'li:has-text("{matricula_norm}")'
                    ).first
                    if opt.count() > 0 and opt.is_visible():
                        opt.click()
                        self.page.wait_for_timeout(400)
                        logger.info("[PAP] Vendedor selecionado via locator: %s", matricula_norm)
                        return True
                except Exception:
                    pass
            except Exception as e:
                logger.debug("[PAP] Busca vendedor termo=%s: %s", termo, e)
                continue
        return False

    def _pagina_parece_auditoria_pedidos(self, url: str, pagina_html: str) -> bool:
        """Detecta tela de auditoria sem confundir com /novo-pedido."""
        url_lower = (url or "").lower()
        if "novo-pedido" in url_lower:
            return False
        pagina_lower = (pagina_html or "").lower()
        return (
            "auditoria" in url_lower
            or "auditoria de pedidos" in pagina_lower
            or "auditoria de pedido" in pagina_lower
        )

    def _preparar_novo_pedido_etapa1(self) -> Tuple[bool, str]:
        """Navega até o formulário da etapa 1 com o campo de vendedor visível."""
        modo_rapido_credito = self.optimize_for_credit

        if self._ja_na_tela_novo_pedido_etapa1():
            logger.info("[PAP] Já na tela novo-pedido (etapa 1); pulando navegação duplicada.")
            self._dispensar_modais_novo_pedido()
            self._redirecionar_se_rota_bloqueia_novo_pedido()
            self._instalar_listener_vendedores_api()
            return True, ""

        ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
        if not ok_sessao:
            return False, msg_sessao

        if self.capture_screenshots:
            self._capture_screenshot("01a_antes_novo_pedido", wait_selector=None, wait_timeout_ms=0)

        url_antes_goto = self._ler_url_atual()
        ja_em_novo_pedido = "novo-pedido" in (url_antes_goto or "").lower()
        if not ja_em_novo_pedido:
            try:
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"[PAP] goto domcontentloaded: {e}, tentando load...")
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="load", timeout=30000)
        else:
            logger.info("[PAP] URL já é novo-pedido após validação de sessão; pulando segundo goto.")
        self.page.wait_for_timeout(200 if modo_rapido_credito else 1000)
        self._aguardar_pagina_estavel()
        if not modo_rapido_credito:
            try:
                self.page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                try:
                    self.page.wait_for_load_state("load", timeout=20000)
                except Exception:
                    pass
        elif ja_em_novo_pedido:
            try:
                self.page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass

        url_atual = self._ler_url_atual()
        if "pap.niointernet.com.br" in (url_atual or "") and "novo-pedido" not in (url_atual or "").lower():
            logger.info(f"[PAP] URL sem novo-pedido ({url_atual[:80]}...), tentando menu lateral.")
            self._clicar_menu_novo_pedido()
            self.page.wait_for_timeout(800 if modo_rapido_credito else 1500)
            url_atual = self._ler_url_atual()
        login_form = self._formulario_login_visivel()
        precisa_login = (
            self._esta_no_idp_vtal(url=url_atual)
            or ("login" in url_atual.lower() and "pap.niointernet.com.br" not in url_atual)
        )
        if not precisa_login and login_form:
            # Evita re-login quando iniciar_sessao acabou de autenticar e a SPA ainda renderiza.
            if self._sessao_pap_autenticada() and self._query_matricula_vendedor_input():
                logger.debug("[PAP] Formulário login ignorado — sessão PAP ativa com campo vendedor visível.")
            else:
                precisa_login = True
        if precisa_login:
            sucesso, msg = self._fazer_login()
            if not sucesso:
                self._capture_screenshot_falha_etapa1("01_err_login_pap", wait_selector=None, wait_timeout_ms=0)
                return False, msg
            self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(300 if modo_rapido_credito else 1000)
            self._aguardar_pagina_estavel()
            url_atual = self._ler_url_atual()

        if "pap.niointernet.com.br" not in url_atual:
            logger.warning(f"[PAP] URL atual: {url_atual}")
            self._capture_screenshot_falha_etapa1("01_err_url_fora_pap", wait_selector=None, wait_timeout_ms=0)
            return False, f"Não foi possível acessar a página de novo pedido. URL: {url_atual[:80]}..."

        if self.capture_screenshots:
            self._capture_screenshot("01b_apos_goto_novo_pedido", wait_selector=None, wait_timeout_ms=800)

        self._dispensar_modais_novo_pedido()

        try:
            pagina_atual_html = self.page.content() or ""
        except Exception:
            pagina_atual_html = ""
        if self._pagina_parece_auditoria_pedidos(url_atual, pagina_atual_html):
            logger.info("[PAP] Tela de auditoria detectada; tentando menu 'Novo Pedido'.")
            self._clicar_menu_novo_pedido()
            self._dispensar_modais_novo_pedido()

        self._redirecionar_se_rota_bloqueia_novo_pedido()

        t_first = 12000 if modo_rapido_credito else 16000
        matricula_visivel = self._esperar_campo_matricula_vendedor(t_first, modo_rapido_credito)

        # Sessão "fantasma": URL chegou em novo-pedido e depois caiu no IdP V.tal.
        if not matricula_visivel and (
            self._esta_no_idp_vtal() or self._sessao_expirada_detectada()
        ):
            if self._pagina_senha_expirada():
                self._capture_screenshot_falha_etapa1("01_err_senha_expirada", wait_selector=None, wait_timeout_ms=0)
                return False, self._mensagem_senha_pap_expirada()
            logger.warning(
                "[PAP] Novo pedido sem matrícula e URL no IdP — tentando relogin limpo uma vez"
            )
            ok_login, msg_login = self._relogin_pap(PAP_NOVO_PEDIDO_URL)
            if not ok_login:
                self._capture_screenshot_falha_etapa1("01_err_relogin_etapa1", wait_selector=None, wait_timeout_ms=0)
                return False, msg_login
            self._dispensar_modais_novo_pedido()
            matricula_visivel = self._esperar_campo_matricula_vendedor(
                12000 if modo_rapido_credito else 16000,
                modo_rapido_credito,
            )

        if not matricula_visivel:
            logger.warning("[PAP] Campo matrícula não encontrado após goto. Tentando menu 'Novo Pedido' e nova espera...")
            if self._clicar_menu_novo_pedido():
                if self.capture_screenshots:
                    self._capture_screenshot("01c_apos_clique_menu_novo_pedido", wait_selector=None, wait_timeout_ms=800)
                self._dispensar_modais_novo_pedido()
                matricula_visivel = self._esperar_campo_matricula_vendedor(
                    9000 if modo_rapido_credito else 14000,
                    modo_rapido_credito,
                )

        if not matricula_visivel:
            self._redirecionar_se_rota_bloqueia_novo_pedido()
            matricula_visivel = self._esperar_campo_matricula_vendedor(
                8000 if modo_rapido_credito else 12000,
                modo_rapido_credito,
            )

        if not matricula_visivel:
            logger.warning("[PAP] Ainda sem campo matrícula; recarregando rota novo-pedido uma vez...")
            try:
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="load", timeout=35000)
                self.page.wait_for_timeout(800 if modo_rapido_credito else 1500)
                self._dispensar_modais_novo_pedido()
                matricula_visivel = self._esperar_campo_matricula_vendedor(
                    10000 if modo_rapido_credito else 15000,
                    modo_rapido_credito,
                )
            except Exception as e:
                logger.warning(f"[PAP] Retry goto novo-pedido: {e}")

        if not matricula_visivel:
            try:
                logger.error("[PAP] Falha etapa1 novo pedido. URL=%s", (self.page.url or "")[:160])
            except Exception:
                pass
            self._capture_screenshot_falha_etapa1("01_err_campo_matricula_invisivel", wait_selector=None, wait_timeout_ms=0)
            return False, self._mensagem_falha_etapa1_sem_matricula()

        if not self._query_matricula_vendedor_input():
            self._capture_screenshot_falha_etapa1("01_err_query_matricula_none", wait_selector=None, wait_timeout_ms=0)
            return False, (
                "Não foi possível localizar o campo de vendedor/matrícula no formulário. "
                "O portal pode ter alterado a página."
            )
        self._instalar_listener_vendedores_api()
        return True, ""

    def _concluir_novo_pedido_etapa1(self, matricula_vendedor: str) -> Tuple[bool, str]:
        """Seleciona vendedor na etapa 1 e avança para a tela de CEP."""
        selecionou_vendedor = self._selecionar_vendedor_matricula_etapa1(matricula_vendedor)
        credito_headless = self._credito_pool_osab_headless()

        if credito_headless and not selecionou_vendedor:
            logger.info(
                "[PAP] Crédito headless: TT %s indisponível no PDV — tentando próximo da fila.",
                matricula_vendedor,
            )
            return (
                False,
                f"Matrícula {matricula_vendedor} não encontrada no PAP deste PDV. "
                "Verifique o cadastro em Gestão de Acessos.",
            )

        timeout_avancar = 8000 if self.optimize_for_credit else 12000
        try:
            self.page.wait_for_selector(
                'button:has-text("Avançar"):not([disabled])',
                state="visible",
                timeout=timeout_avancar,
            )
        except Exception:
            pass
        btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
        if not btn_avancar:
            lista_items = self._coletar_itens_lista_vendedor()
            mats_visiveis = self._atualizar_cache_matriculas_pap(lista_items)
            try:
                n_li = len(lista_items)
                amostras = [(i.inner_text() or "")[:80] for i in lista_items[:5]]
                logger.warning(
                    "[PAP] Etapa1 sem botão Avançar. matricula=%s selecionou=%s n_li=%s cache=%s amostras=%s",
                    matricula_vendedor,
                    selecionou_vendedor,
                    n_li,
                    len(mats_visiveis),
                    amostras,
                )
            except Exception as log_e:
                logger.warning("[PAP] Etapa1 sem botão Avançar (log lista falhou): %s", log_e)
            self._capture_screenshot_falha_etapa1("01_err_sem_bot_avancar_apos_vendedor", wait_selector=None, wait_timeout_ms=0)
            if not selecionou_vendedor:
                if self.optimize_for_credit and mats_visiveis:
                    return (
                        False,
                        f"Matrícula {matricula_vendedor} não está entre os {len(mats_visiveis)} "
                        "vendedores deste PDV.",
                    )
                return (
                    False,
                    f"Matrícula {matricula_vendedor} não encontrada no PAP deste PDV. "
                    "Verifique o cadastro em Gestão de Acessos.",
                )
            return False, "Não foi possível selecionar o vendedor. Verifique a matrícula."
        if self.capture_screenshots:
            self._highlight_element(btn_avancar, duration_ms=400)
        btn_avancar.click()
        self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=10000)
        self._extrair_protocolo_pedido()
        self.etapa_atual = 1
        self.dados_pedido['matricula_vendedor'] = matricula_vendedor
        if self.capture_screenshots:
            self._capture_screenshot("01d_etapa1_concluida", wait_selector=SELETORES['etapa2']['cep'], wait_timeout_ms=3000)
        return True, "Etapa 1 concluída! Vendedor selecionado."

    def iniciar_novo_pedido(self, matricula_vendedor: str) -> Tuple[bool, str]:
        """
        Inicia um novo pedido (Etapa 1).
        
        Args:
            matricula_vendedor: Matrícula do vendedor que está fazendo a venda
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            logger.info(f"[PAP] Iniciando novo pedido - Vendedor: {matricula_vendedor}")
            ok_prep, msg_prep = self._preparar_novo_pedido_etapa1()
            if not ok_prep:
                return False, msg_prep
            return self._concluir_novo_pedido_etapa1(matricula_vendedor)
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 1: {e}")
            try:
                self._capture_screenshot_falha_etapa1("01_excecao_etapa1", wait_selector=None, wait_timeout_ms=0)
            except Exception:
                pass
            return False, f"Erro na Etapa 1: {str(e)}"

    def validar_tela_pronta_para_cep(self, timeout_ms: int = 8000) -> Tuple[bool, str]:
        """
        Verifica se a página está na etapa correta para digitar CEP (tela de novo pedido - etapa endereço).
        Só retorna True se o campo CEP ou o formulário de viabilidade estiver visível.
        """
        if not self.page:
            return False, "Sessão não está aberta."
        try:
            cep_sel = (
                self.page.query_selector(SELETORES['etapa2']['cep']) or
                self.page.query_selector('input[placeholder=" "]') or
                self.page.query_selector('input[type="number"]') or
                self.page.query_selector('button:has-text("Buscar")')
            )
            if cep_sel and cep_sel.is_visible():
                logger.info("[PAP] Tela validada: formulário de CEP/endereço visível.")
                return True, "Tela pronta para CEP."
            pausa = 200 if self.optimize_for_credit else 800
            self.page.wait_for_timeout(pausa)
            cep_sel = self.page.query_selector(SELETORES['etapa2']['cep']) or self.page.query_selector('button:has-text("Buscar")')
            if cep_sel and cep_sel.is_visible():
                return True, "Tela pronta para CEP."
            return False, "Tela de endereço (CEP) não está visível. A página pode não ter carregado corretamente."
        except Exception as e:
            logger.warning(f"[PAP] Validação da tela CEP: {e}")
            return False, f"Não foi possível validar a tela: {str(e)}"

    def obter_nome_operador_logado(self) -> str:
        """
        Extrai o nome do operador (backoffice) logado no portal a partir do elemento
        que exibe "Olá, <br> NOME DO OPERADOR" (ex.: #operador ou div.Operador-info).
        Retorna string vazia se não encontrar.
        """
        if not self.page:
            return ""
        try:
            # Tentar #operador ou .Operador-info primeiro (estrutura: div com "Olá," e nome após <br>)
            el = self.page.query_selector('#operador') or self.page.query_selector('div.Operador-info')
            if not el:
                # Fallback: qualquer div que contenha "Olá," seguido do nome
                el = self.page.query_selector('div:has-text("Olá")')
            if not el:
                return ""
            texto = (el.inner_text() or "").strip()
            if not texto:
                return ""
            # Remover "Olá," (com vírgula e variações) e pegar o restante como nome
            texto = re.sub(r'^Olá\s*,?\s*', '', texto, flags=re.I).strip()
            # Se tiver quebra de linha, o nome costuma estar na segunda parte
            partes = [p.strip() for p in texto.split('\n') if p.strip()]
            nome = partes[-1] if partes else texto
            return nome.strip() if nome else ""
        except Exception as e:
            logger.warning(f"[PAP] obter_nome_operador_logado: {e}")
            return ""

    def etapa2_viabilidade(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """
        Etapa 2: Consulta de viabilidade.
        Fluxo: CEP + Número -> Buscar -> aguardar endereço resolver ->
        preencher Referência (obrigatório) -> Avançar -> aguardar modal.
        """
        try:
            logger.info(f"[PAP] Etapa 2 - CEP: {cep}, Número: {numero}, Referência: {referencia}")
            ok_sessao, msg_sessao = self._garantir_sessao_etapa_viabilidade()
            if not ok_sessao:
                return False, msg_sessao, None

            # Avançar da etapa 1 já foi feito em iniciar_novo_pedido; garantir que estamos na tela CEP
            try:
                self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=5000)
            except Exception:
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if btn_avancar:
                    btn_avancar.click()
                    self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=10000)
                    self._extrair_protocolo_pedido()

            # 1. Preencher CEP
            cep_limpo = re.sub(r'\D', '', cep)
            if not self._preencher_campo_formulario(SELETORES['etapa2']['cep'], cep_limpo):
                self._set_valor_react(SELETORES['etapa2']['cep'], cep_limpo)

            # 2. Preencher número (ou marcar "Sem número")
            if str(numero).strip().upper() in ("SN", "S/N", "S N"):
                sem_numero = self.page.query_selector(SELETORES['etapa2']['sem_numero'])
                if sem_numero and not sem_numero.is_checked():
                    sem_numero.click()
            else:
                if not self._preencher_campo_formulario(SELETORES['etapa2']['numero'], str(numero)):
                    self._set_valor_react(SELETORES['etapa2']['numero'], str(numero))

            self._wait_etapa2_ms(400, 800)

            # 3. Clicar em Buscar (aguardar habilitar — React valida CEP/número após blur)
            timeout_buscar = 8000 if self.optimize_for_credit else 12000
            btn_buscar = self._aguardar_botao_buscar_etapa2(timeout_ms=timeout_buscar)
            if not btn_buscar:
                if not self._preencher_campo_formulario(SELETORES['etapa2']['cep'], cep_limpo):
                    self._set_valor_react(SELETORES['etapa2']['cep'], cep_limpo)
                if str(numero).strip().upper() not in ("SN", "S/N", "S N"):
                    if not self._preencher_campo_formulario(SELETORES['etapa2']['numero'], str(numero)):
                        self._set_valor_react(SELETORES['etapa2']['numero'], str(numero))
                btn_buscar = self._aguardar_botao_buscar_etapa2(timeout_ms=5000)
            if not btn_buscar:
                btn_desabilitado = self.page.query_selector(SELETORES['etapa2']['btn_buscar'])
                logger.warning(
                    "[PAP] Buscar indisponível após preencher CEP=%s numero=%s (botão existe=%s, disabled=%s)",
                    cep_limpo,
                    numero,
                    bool(btn_desabilitado),
                    (btn_desabilitado.get_attribute("disabled") if btn_desabilitado else None),
                )
                if self.capture_screenshots:
                    self._capture_screenshot(
                        "02_err_buscar_indisponivel",
                        wait_selector=SELETORES['etapa2']['cep'],
                        wait_timeout_ms=1000,
                    )
                return False, "Botão Buscar não disponível. Verifique CEP e número.", None
            btn_buscar.click()
            
            # 4. Aguardar o endereço ser resolvido - espera inteligente (retorna assim que elemento aparecer)
            # Primeiro: Endereço de instalação OU Referência
            end_inst_sel = SELETORES['etapa2']['endereco_instalacao']
            ref_selector = SELETORES['etapa2']['referencia']
            try:
                self.page.wait_for_selector(
                    f'{end_inst_sel}, {ref_selector}, h2:has-text("OPS, OCORREU UM ERRO")',
                    state="visible",
                    timeout=15000
                )
            except Exception:
                pass
            self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
            # Modal OPS na consulta: clicar "Tentar novamente" e reenviar Buscar (até 2 tentativas)
            for _ops_tentativa in range(2):
                if not self.verificar_modal_erro_ops_visivel():
                    break
                if not self._fechar_modal_erro_ops():
                    return False, PAP_ERRO_PORTAL_NIO, None
                self.page.wait_for_timeout(800 if self.optimize_for_credit else 1200)
                btn_buscar_retry = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
                if btn_buscar_retry and btn_buscar_retry.is_visible():
                    btn_buscar_retry.click()
                try:
                    self.page.wait_for_selector(
                        f'{end_inst_sel}, {ref_selector}, h2:has-text("OPS, OCORREU UM ERRO")',
                        state="visible",
                        timeout=15000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
            if self.verificar_modal_erro_ops_visivel():
                return False, PAP_ERRO_PORTAL_NIO, None
            
            # 4b. Verificar múltiplos endereços (dropdown "Endereço de instalação")
            for end_sel in [
                end_inst_sel,
                'input[placeholder="Endereço de instalação"]',
                'input[placeholder*="ndereço de instalação"]',
                'input[placeholder*="Endereço"]',
            ]:
                inp_end_inst = self.page.query_selector(end_sel)
                if not inp_end_inst:
                    continue
                try:
                    inp_end_inst.click()
                    self.page.wait_for_timeout(350 if self.optimize_for_credit else 1000)
                    for sel_ul in [
                        'input[placeholder="Endereço de instalação"] ~ ul li',
                        'input[placeholder*="Endereço"] ~ ul li',
                        '[role="listbox"] li', '[role="option"]',
                        'ul.sc-fQkuQJ.cUdcXF li', 'ul[class*="fQkuQJ"] li',
                        'ul[class*="cUdcXF"] li', 'ul li.sc-epGmkI',
                        'ul[class*="dropdown"] li', 'ul[class*="menu"] li',
                    ]:
                        lis = [el for el in self.page.query_selector_all(sel_ul) if el.is_visible()]
                        enderecos = []
                        for li in lis:
                            txt = (li.inner_text() or "").strip()
                            if len(txt) > 15 and (" - " in txt or ", " in txt) and any(u in txt.upper() for u in ["MG", "SP", "RJ", "BA", "PR", "RS", "SC", "DF", "ES", "GO"]):
                                enderecos.append({'indice': len(enderecos) + 1, 'texto': txt})
                        if len(enderecos) >= 2:
                            self.dados_pedido['cep'] = cep
                            self.dados_pedido['numero'] = str(numero)
                            # Viabilidade não concluída: usuário precisa escolher o endereço
                            return False, "Múltiplos endereços. Escolha um:", {'_codigo': 'MULTIPLOS_ENDERECOS', 'lista': enderecos}
                        elif len(enderecos) == 1:
                            target_txt = enderecos[0]['texto']
                            for li in lis:
                                if (li.inner_text() or "").strip() == target_txt:
                                    li.click()
                                    self.page.wait_for_timeout(400)
                                    break
                        if enderecos or lis:
                            break
                    else:
                        self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
                    break
                except Exception:
                    pass
            
            # 4c. Aguardar Referência (se ainda não apareceu)
            try:
                self.page.wait_for_selector(ref_selector, state="visible", timeout=8000)
            except Exception:
                for sel in [
                    'input[placeholder*="eferência"]',
                    'textarea[placeholder*="eferência"]',
                    'input[id*="referencia"], input[name*="referencia"]',
                    'textarea[id*="referencia"], textarea[name*="referencia"]',
                ]:
                    try:
                        self.page.wait_for_selector(sel, state="visible", timeout=3000)
                        ref_selector = sel
                        break
                    except Exception:
                        continue

            # 5. Preencher Referência (obrigatório) - usar fill para disparar eventos
            ref_preenchido = False
            ref_input = self.page.query_selector(ref_selector)
            if ref_input and ref_input.is_visible():
                ref_input.click()
                self.page.wait_for_timeout(200)
                ref_input.fill(referencia)
                self.page.keyboard.press("Tab")
                ref_preenchido = True
                logger.info(f"[PAP] Referência preenchida (seletor): {referencia!r}")
            if not ref_preenchido:
                # Fallback: label "Referência (Obrigatório)" ou "Referência"
                for label_text in ["Referência (Obrigatório)", "Referência", "referência", "Ponto de referência"]:
                    try:
                        ref_loc = self.page.get_by_label(label_text, exact=False)
                        if ref_loc.count() > 0:
                            ref_loc.first.click()
                            self.page.wait_for_timeout(200)
                            ref_loc.first.fill(referencia)
                            self.page.keyboard.press("Tab")
                            ref_preenchido = True
                            logger.info(f"[PAP] Referência preenchida (label {label_text!r}): {referencia!r}")
                            break
                    except Exception:
                        continue
            if not ref_preenchido:
                for inp in self.page.query_selector_all('input:not([disabled]):not([type="hidden"]), textarea:not([disabled])'):
                    if not inp.is_visible():
                        continue
                    ph = (inp.get_attribute("placeholder") or "")
                    name = (inp.get_attribute("name") or "")
                    id_attr = (inp.get_attribute("id") or "")
                    if "referência" in ph.lower() or "referencia" in ph.lower() or "referencia" in name.lower() or "referencia" in id_attr.lower():
                        inp.click()
                        self.page.wait_for_timeout(200)
                        inp.fill(referencia)
                        self.page.keyboard.press("Tab")
                        ref_preenchido = True
                        logger.info(f"[PAP] Referência preenchida (fallback input): {referencia!r}")
                        break
            if not ref_preenchido:
                logger.warning("[PAP] Campo Referência não encontrado ou não preenchido - botão Avançar pode permanecer desabilitado")

            self._wait_etapa2_ms(350, 1500)

            tratado = self._tratar_complementos_etapa2(cep, numero, referencia)
            if tratado is not None:
                return tratado

            # 6. Clicar Avançar e tratar modal
            return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, referencia)
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 2: {e}")
            return False, f"Erro na Etapa 2: {str(e)}", None

    def etapa2_modal_posse_clicar_consultar_outro(self) -> Tuple[bool, str]:
        """
        Clica em "Consultar outro endereço" no modal "Posse encontrada".
        Retorna à tela de consulta (CEP, Número) para o usuário informar novo endereço.
        """
        try:
            btn = self.page.query_selector('button:has-text("Consultar outro endereço")')
            if not btn:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const b = btns.find(x => x.textContent && x.textContent.includes('Consultar outro endereço'));
                    if (b) b.click();
                }""")
            else:
                btn.click(force=True, timeout=3000)
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=5000)
            except Exception:
                pass
            return True, "Pronto para consultar outro endereço."
        except Exception as e:
            logger.error(f"[PAP] etapa2_modal_posse_clicar_consultar_outro: {e}")
            return False, str(e)

    def etapa2_modal_indisponivel_clicar_voltar(self) -> Tuple[bool, str]:
        """
        Clica em "Voltar" no modal "Indisponível" (sem viabilidade técnica).
        Fecha o modal e retorna à tela de consulta (CEP, Número).
        """
        try:
            btn = self.page.query_selector('button:has-text("Voltar")')
            if not btn:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const b = btns.find(x => x.textContent && x.textContent.trim() === 'Voltar');
                    if (b) b.click();
                }""")
            else:
                btn.click(force=True, timeout=3000)
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_selector('button:has-text("Buscar"):not([disabled])', state="visible", timeout=5000)
            except Exception:
                try:
                    self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=5000)
                except Exception:
                    pass
            return True, "Pronto para consultar outro endereço."
        except Exception as e:
            logger.error(f"[PAP] etapa2_modal_indisponivel_clicar_voltar: {e}")
            return False, str(e)
    
    def etapa2_preparar_nova_consulta_endereco(
        self, codigo_bloqueio: str = ""
    ) -> Tuple[bool, str]:
        """
        Fecha o modal que bloqueou o endereço e volta ao formulário de CEP.

        Usado no crédito para reconsultar com o endereço padrão da automação
        quando o endereço do cliente não tem viabilidade ou já tem posse.
        """
        if not self.page:
            return False, "Página do PAP indisponível."
        codigo = (codigo_bloqueio or "").upper()
        # Pedido encontrado e Posse usam "Consultar outro endereço";
        # Indisponível usa "Voltar".
        acoes = (
            [self.etapa2_modal_indisponivel_clicar_voltar,
             self.etapa2_modal_posse_clicar_consultar_outro]
            if codigo == "INDISPONIVEL_TECNICO"
            else [self.etapa2_modal_posse_clicar_consultar_outro,
                  self.etapa2_modal_indisponivel_clicar_voltar]
        )
        ultimo_erro = ""
        for acao in acoes:
            try:
                acao()
            except Exception as e:
                ultimo_erro = str(e)
                continue
            if self._etapa2_formulario_cep_visivel():
                return True, "Formulário de CEP pronto para nova consulta."
        return False, ultimo_erro or "Formulário de CEP não reapareceu."

    def _etapa2_formulario_cep_visivel(self) -> bool:
        try:
            campo = self.page.query_selector(SELETORES['etapa2']['cep'])
            return bool(campo and campo.is_visible())
        except Exception:
            return False

    def _wait_etapa2_ms(self, rapido_ms: int, normal_ms: int) -> None:
        if self.page:
            self.page.wait_for_timeout(rapido_ms if self.optimize_for_credit else normal_ms)

    def _seletores_lista_complemento(self) -> List[str]:
        return [
            'ul.sc-fQkuQJ.cUdcXF li',
            'ul[class*="fQkuQJ"] li',
            'ul[class*="cUdcXF"] li',
            'ul li.sc-epGmkI',
            'input[placeholder*="omplemento"] ~ ul li',
            'div:has(input[placeholder*="omplemento"]) ul li',
        ]

    def _query_input_complemento(self):
        if not self.page:
            return None
        return self.page.query_selector(
            'input[placeholder*="omplemento"], input[placeholder*="Complemento"]'
        )

    def _valor_complemento_no_input(self) -> str:
        inp = self._query_input_complemento()
        if not inp or not inp.is_visible():
            return ""
        try:
            return (inp.input_value() or "").strip()
        except Exception:
            return ""

    def _complemento_ja_selecionado(self) -> Tuple[bool, str]:
        val = self._valor_complemento_no_input()
        if not val:
            return False, ""
        lower = val.lower()
        if lower in ("complemento", "selecione", "selecionar", "opcional"):
            return False, ""
        return True, val

    def _coletar_itens_complemento_visiveis(self) -> List[Any]:
        if not self.page:
            return []
        for sel in self._seletores_lista_complemento():
            try:
                lis = self.page.query_selector_all(sel)
                vis = [
                    el for el in lis
                    if el.is_visible() and (el.inner_text() or "").strip()
                ]
                if vis:
                    return vis
            except Exception:
                continue
        return []

    def _abrir_dropdown_complemento_se_necessario(self) -> List[Any]:
        itens = self._coletar_itens_complemento_visiveis()
        if itens:
            return itens
        inp = self._query_input_complemento()
        if not inp:
            return []
        try:
            inp.click()
            self._wait_etapa2_ms(250, 700)
            try:
                self.page.wait_for_selector(
                    'ul[class*="fQkuQJ"] li, ul[class*="cUdcXF"] li',
                    state="visible",
                    timeout=1500 if self.optimize_for_credit else 3000,
                )
            except Exception:
                pass
        except Exception:
            pass
        return self._coletar_itens_complemento_visiveis()

    def _listar_complementos_dropdown(self) -> List[dict]:
        itens = self._abrir_dropdown_complemento_se_necessario()
        return [
            {"indice": i + 1, "texto": (el.inner_text() or "").strip()}
            for i, el in enumerate(itens)
            if (el.inner_text() or "").strip()
        ]

    def _tratar_complementos_etapa2(
        self, cep: str, numero: str, referencia: str
    ) -> Optional[Tuple[bool, str, Optional[Any]]]:
        """
        Complemento já preenchido → Avançar direto.
        Crédito: auto-seleciona opção 1 na mesma passagem (evita reabrir dropdown).
        Venda: retorna COMPLEMENTOS para o usuário escolher.
        """
        ja, texto_ja = self._complemento_ja_selecionado()
        if ja:
            logger.info("[PAP] Complemento já preenchido (%r) — avançando", texto_ja)
            return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, referencia)

        complementos = self._listar_complementos_dropdown()
        if not complementos:
            return None

        self.dados_pedido["cep"] = cep
        self.dados_pedido["numero"] = str(numero)
        self.dados_pedido["referencia"] = referencia

        if self.optimize_for_credit:
            ok, msg = self._selecionar_complemento_por_indice(1, itens_precarregados=True)
            if ok:
                return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, referencia)
            return False, msg or "Falha ao selecionar complemento.", None

        return True, "Complementos encontrados. Escolha uma opção:", {
            "_codigo": "COMPLEMENTOS",
            "lista": complementos,
        }

    def _selecionar_complemento_por_indice(
        self, indice: int, itens_precarregados: bool = False
    ) -> Tuple[bool, str]:
        ja, texto = self._complemento_ja_selecionado()
        if ja:
            logger.info("[PAP] Complemento já selecionado (%r) — pulando clique", texto)
            return True, "Complemento já selecionado."

        if itens_precarregados:
            vis = self._coletar_itens_complemento_visiveis()
        else:
            vis = self._abrir_dropdown_complemento_se_necessario()

        if indice > 0 and indice <= len(vis):
            texto_item = (vis[indice - 1].inner_text() or "").strip()
            if texto_item:
                vis[indice - 1].click()
                self._wait_etapa2_ms(200, 500)
                logger.info("[PAP] Complemento selecionado (índice %s): %r", indice, texto_item)
                return True, "Complemento selecionado."
        return False, "Índice de complemento inválido ou lista não encontrada."

    def etapa2_selecionar_sem_complemento(self) -> Tuple[bool, str]:
        """Marca 'Sem complemento' via check() (interação real) e força revalidação clicando no Avançar."""
        try:
            # 1. Fechar dropdown do complemento (etapa2_viabilidade abre ao detectar)
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
            # 2. Marcar checkbox com Playwright check() - interação real, React atualiza
            try:
                self.page.check('#semComplemento', force=True)
            except Exception:
                lbl = self.page.query_selector('label[for="semComplemento"]')
                if lbl and lbl.is_visible():
                    lbl.click()
            self.page.wait_for_timeout(400)
            # 3. Clicar no botão Avançar para disparar revalidação (habilita o botão)
            btn = self.page.query_selector('button:has-text("Avançar")')
            if btn and btn.is_visible():
                btn.click(force=True)
                self.page.wait_for_timeout(500)
            return True, "Sem complemento selecionado."
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_sem_complemento: {e}")
            return False, str(e)

    def etapa2_selecionar_complemento(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um complemento da lista (ex.: Loja 1, Loja 2, Casa A).
        Args:
            indice: 1-based (1 = primeiro complemento)
        """
        try:
            return self._selecionar_complemento_por_indice(indice)
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_complemento: {e}")
            return False, str(e)

    def etapa2_clicar_avancar_apos_complemento(self, cep: str = "", numero: str = "") -> Tuple[bool, str, Optional[list]]:
        """
        Clica Avançar após o usuário ter selecionado complemento ou "Sem complemento".
        A Referência já foi preenchida antes. Retorno igual a etapa2_viabilidade (sucesso, msg, extra).
        """
        ref = self.dados_pedido.get('referencia', '')
        return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, ref)

    def etapa2_credito_selecionar_complemento_e_avancar(
        self, cep: str, numero: str, indice_complemento: int
    ) -> Tuple[bool, str, Optional[Any]]:
        """
        Fluxo CRÉDITO: quando o PAP lista complementos obrigatórios, o portal pode não aceitar
        apenas "Sem complemento". Seleciona um item da lista (1 = primeiro) e avança a viabilidade.
        """
        if indice_complemento < 1:
            return False, "Índice de complemento inválido (use 1, 2, 3…).", None
        ja, texto = self._complemento_ja_selecionado()
        if ja:
            logger.info("[PAP] Crédito: complemento já preenchido (%r) — só Avançar", texto)
            return self.etapa2_clicar_avancar_apos_complemento(cep, numero)
        ok, msg_sel = self._selecionar_complemento_por_indice(indice_complemento)
        if not ok:
            return False, msg_sel or "Falha ao selecionar complemento.", None
        return self.etapa2_clicar_avancar_apos_complemento(cep, numero)

    def selecionar_endereco(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um endereço da lista quando há múltiplos.
        
        Args:
            indice: Índice do endereço (1-based)
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            lista_enderecos = self.page.query_selector_all(SELETORES['etapa2']['lista_enderecos'])
            if indice > 0 and indice <= len(lista_enderecos):
                lista_enderecos[indice - 1].click()
                return True, "Endereço selecionado!"
            return False, "Índice de endereço inválido."
        except Exception as e:
            return False, f"Erro ao selecionar endereço: {str(e)}"

    def etapa2_selecionar_endereco_instalacao(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um endereço do dropdown "Endereço de instalação" (quando há múltiplos).
        Args:
            indice: Índice 1-based (1 = primeiro endereço)
        """
        try:
            inp = self.page.query_selector(SELETORES['etapa2']['endereco_instalacao'])
            if inp:
                inp.click()
                self.page.wait_for_timeout(600)
            for sel in [
                'input[placeholder="Endereço de instalação"] ~ ul li',
                'ul.sc-fQkuQJ.cUdcXF li', 'ul[class*="fQkuQJ"] li', 'ul[class*="cUdcXF"] li',
            ]:
                lis = [el for el in self.page.query_selector_all(sel) if el.is_visible()]
                enderecos = [
                    {'i': i + 1, 'li': li}
                    for i, li in enumerate(lis)
                    if len((li.inner_text() or "").strip()) > 20
                    and (" - " in (li.inner_text() or "") or ", " in (li.inner_text() or ""))
                ]
                if indice > 0 and indice <= len(enderecos):
                    enderecos[indice - 1]['li'].click()
                    self.page.wait_for_timeout(500)
                    return True, "Endereço selecionado."
                if enderecos:
                    break
            return False, "Índice de endereço inválido."
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_endereco_instalacao: {e}")
            return False, str(e)

    def etapa2_preencher_referencia_e_continuar(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """
        Preenche Referência e clica Avançar (após seleção de endereço quando havia múltiplos).
        Retorno igual a etapa2_viabilidade: (sucesso, msg, extra) com extra podendo ser COMPLEMENTOS, POSSE_ENCONTRADA, etc.
        """
        try:
            # Esperar formulário estabilizar após seleção do endereço (evita preencher durante validação/piscar da página)
            self.page.wait_for_timeout(1200)
            ref_selector = SELETORES['etapa2']['referencia']
            try:
                self.page.wait_for_selector(ref_selector, state="visible", timeout=8000)
            except Exception:
                ref_selector = 'input[name="referencia"]'
                try:
                    self.page.wait_for_selector(ref_selector, state="visible", timeout=5000)
                except Exception:
                    for sel in ['input[placeholder*="eferência"]', 'textarea[placeholder*="eferência"]', 'input[id*="referencia"]', 'textarea[id*="referencia"]']:
                        try:
                            self.page.wait_for_selector(sel, state="visible", timeout=2000)
                            ref_selector = sel
                            break
                        except Exception:
                            continue
            ref_preenchido = False
            ref_input = self.page.query_selector(ref_selector)
            if ref_input and ref_input.is_visible():
                ref_input.click()
                self.page.wait_for_timeout(200)
                ref_input.fill(referencia)
                self.page.keyboard.press("Tab")
                ref_preenchido = True
                logger.info(f"[PAP] Referência preenchida (seleção endereço): {referencia!r}")
            if not ref_preenchido:
                for label_text in ["Referência (Obrigatório)", "Referência", "referência", "Ponto de referência"]:
                    try:
                        ref_loc = self.page.get_by_label(label_text, exact=False)
                        if ref_loc.count() > 0:
                            ref_loc.first.click()
                            self.page.wait_for_timeout(200)
                            ref_loc.first.fill(referencia)
                            self.page.keyboard.press("Tab")
                            ref_preenchido = True
                            logger.info(f"[PAP] Referência preenchida (label {label_text!r}, seleção endereço): {referencia!r}")
                            break
                    except Exception:
                        continue
            if not ref_preenchido:
                for inp in self.page.query_selector_all('input:not([disabled]):not([type="hidden"]), textarea:not([disabled])'):
                    if not inp.is_visible():
                        continue
                    ph = (inp.get_attribute("placeholder") or "")
                    name = (inp.get_attribute("name") or "")
                    id_attr = (inp.get_attribute("id") or "")
                    if "referência" in ph.lower() or "referencia" in ph.lower() or "referencia" in name.lower() or "referencia" in id_attr.lower():
                        inp.click()
                        self.page.wait_for_timeout(200)
                        inp.fill(referencia)
                        self.page.keyboard.press("Tab")
                        ref_preenchido = True
                        logger.info(f"[PAP] Referência preenchida (fallback input, seleção endereço): {referencia!r}")
                        break
            if not ref_preenchido:
                logger.warning("[PAP] Campo Referência não encontrado em etapa2_preencher_referencia_e_continuar - botão Avançar pode permanecer desabilitado")
            # Garantir que o valor foi realmente preenchido (página pode ter limpado por validação)
            if referencia and ref_preenchido:
                self.page.wait_for_timeout(400)
                try:
                    inp_check = (
                        self.page.query_selector(ref_selector)
                        or self.page.query_selector('input[name="referencia"]')
                        or self.page.query_selector('input[placeholder*="eferência"]')
                        or self.page.query_selector('textarea[name="referencia"]')
                    )
                    if inp_check and inp_check.is_visible():
                        val = (inp_check.input_value() or "").strip()
                        if not val:
                            logger.info("[PAP] Campo referência estava vazio após fill; tentando preencher novamente.")
                            inp_check.click()
                            self.page.wait_for_timeout(200)
                            inp_check.fill(referencia)
                            self.page.keyboard.press("Tab")
                            self.page.wait_for_timeout(400)
                except Exception as e:
                    logger.debug("[PAP] Verificação do valor da referência: %s", e)
            # Esperar rede/página estabilizar antes de Avançar (reduz efeito de validação que desabilita o botão)
            try:
                self.page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                self.page.wait_for_timeout(500)
            self._wait_etapa2_ms(250, 400)
            tratado = self._tratar_complementos_etapa2(cep, numero, referencia)
            if tratado is not None:
                return tratado
            # Sem complementos: clicar Avançar
            return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, referencia)
        except Exception as e:
            logger.error(f"[PAP] etapa2_preencher_referencia_e_continuar: {e}")
            return False, str(e), None

    def _etapa2_formulario_documento_visivel(self) -> bool:
        """PAP às vezes pula o modal de viabilidade e exibe direto o cadastro (CPF/CNPJ)."""
        if not self.page:
            return False
        try:
            inp = self.page.query_selector('input[name="documento"]')
            if inp and inp.is_visible():
                return True
            loc = self.page.locator(
                'input[placeholder*="CPF"], input[placeholder*="CNPJ"], '
                'input[placeholder*="cpf"], input[placeholder*="cnpj"]'
            )
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    def _etapa2_resultado_de_modal_bloqueante(
        self,
        modal_bloqueante: Dict[str, str],
        cep: str,
        numero: str,
        referencia: str,
    ) -> Tuple[bool, str, Optional[Any]]:
        """Converte modal Posse/Pedido/Indisponível no retorno padrão da etapa 2."""
        codigo = modal_bloqueante["codigo"]
        if codigo == PAP_ERRO_PORTAL_NIO:
            self._fechar_modal_erro_ops()
            return False, PAP_ERRO_PORTAL_NIO, None
        self._capture_screenshot(
            f"02_modal_{codigo.lower()}",
            forcar=True,
        )
        msg = self._mensagem_usuario_modal_bloqueante(
            modal_bloqueante,
            etapa="endereco",
            cep=cep,
            numero=numero,
            referencia=referencia,
        )
        # Pedido encontrado no endereço ≡ posse para o fallback de crédito / VENDER.
        if codigo == "PEDIDO_ENCONTRADO":
            codigo = "POSSE_ENCONTRADA"
        if codigo == "PAP_OCORREU_ERRO":
            return False, msg, None
        if codigo == "INDISPONIVEL_TECNICO":
            msg = msg + "\n\nDigite outro *CEP* ou *CONCLUIR* para sair."
        else:
            msg = (
                msg
                + "\n\nDigite outro *CEP* para consultar outro endereço "
                "ou *CONCLUIR* para sair."
            )
        return False, msg, codigo

    def _etapa2_concluir_endereco_viavel(
        self, cep: str, numero: str, referencia: str, motivo_log: str = ""
    ) -> Tuple[bool, str, Optional[Any]]:
        if motivo_log:
            logger.info("[PAP] Etapa2: endereço viável — %s", motivo_log)
        btn_cont = self.page.query_selector('button:has-text("Continuar")')
        if btn_cont and btn_cont.is_visible():
            btn_cont.click()
            try:
                self.page.wait_for_selector('input[name="documento"]', state="visible", timeout=20000)
            except Exception:
                self.page.wait_for_timeout(3000)
        elif not self._etapa2_formulario_documento_visivel():
            try:
                self.page.wait_for_selector('input[name="documento"]', state="visible", timeout=15000)
            except Exception:
                self.page.wait_for_timeout(2000)

        # Pedido/Posse encontrado às vezes abre DEPOIS do Continuar / tela de CPF.
        self.page.wait_for_timeout(700 if self.optimize_for_credit else 1200)
        modal_bloqueante = self._ler_modal_bloqueante_pap()
        if modal_bloqueante and modal_bloqueante.get("codigo") in (
            "POSSE_ENCONTRADA",
            "PEDIDO_ENCONTRADO",
            "INDISPONIVEL_TECNICO",
            PAP_ERRO_PORTAL_NIO,
            "PAP_OCORREU_ERRO",
        ):
            logger.warning(
                "[PAP] Etapa2: modal %s após parecer viável — não avançando com este endereço",
                modal_bloqueante.get("codigo"),
            )
            return self._etapa2_resultado_de_modal_bloqueante(
                modal_bloqueante, cep, numero, referencia
            )

        self._capture_screenshot(
            "02_viabilidade_disponivel",
            wait_selector='input[name="documento"]',
            wait_timeout_ms=5000,
        )
        self.etapa_atual = 2
        self.dados_pedido['cep'] = cep
        self.dados_pedido['numero'] = numero
        self.dados_pedido['referencia'] = referencia
        self._extrair_protocolo_pedido()
        return True, "Etapa 2 concluída! Endereço viável.", None

    def _etapa2_interpretar_resultado_viabilidade(
        self, cep: str, numero: str, referencia: str
    ) -> Optional[Tuple[bool, str, Optional[Any]]]:
        """Interpreta modal/texto/tela CPF após consulta de viabilidade. None = ainda aguardando."""
        if self.verificar_modal_erro_ops_visivel():
            self._fechar_modal_erro_ops()
            return False, PAP_ERRO_PORTAL_NIO, None

        # IMPORTANTE: checar Pedido/Posse/Indisponível ANTES do formulário CPF.
        # O PAP pode deixar o input documento no DOM (ou já na etapa 3) com o
        # modal bloqueante por cima — tratar CPF visível como sucesso fazia o
        # crédito seguir sem cair no endereço padrão.
        modal_bloqueante = self._ler_modal_bloqueante_pap()
        if modal_bloqueante and modal_bloqueante.get("codigo") in (
            "POSSE_ENCONTRADA",
            "PEDIDO_ENCONTRADO",
            "INDISPONIVEL_TECNICO",
            PAP_ERRO_PORTAL_NIO,
            "PAP_OCORREU_ERRO",
        ):
            return self._etapa2_resultado_de_modal_bloqueante(
                modal_bloqueante, cep, numero, referencia
            )

        if self._etapa2_formulario_documento_visivel():
            return self._etapa2_concluir_endereco_viavel(
                cep, numero, referencia,
                motivo_log="formulário CPF visível (PAP pulou modal de viabilidade)",
            )
        pagina_lower = self._page_content_seguro(tentativas=2, pausa_ms=350).lower()
        if "posse encontrada" in pagina_lower or (
            "pedido" in pagina_lower and "em andamento" in pagina_lower
        ) or "pedido encontrado" in pagina_lower:
            endereco = self._formatar_linha_endereco(cep, numero, referencia)
            return False, (
                "❌ *Posse encontrada*\n\n"
                "Não é possível abrir um pedido para o endereço consultado "
                "pois já existe um pedido em andamento.\n\n"
                f"📍 *Endereço consultado:* {endereco}\n\n"
                "Digite outro *CEP* para consultar outro endereço ou *CONCLUIR* para sair."
            ), "POSSE_ENCONTRADA"
        if (
            "indisponível" in pagina_lower
            or "indisponivel" in pagina_lower
            or "sem viabilidade técnica" in pagina_lower
        ):
            endereco = self._formatar_linha_endereco(cep, numero, referencia)
            return False, (
                "❌ *Endereço indisponível*\n\n"
                "Sem viabilidade técnica para o endereço consultado.\n\n"
                f"📍 *Endereço consultado:* {endereco}\n\n"
                "Digite outro *CEP* ou *CONCLUIR* para sair."
            ), "INDISPONIVEL_TECNICO"
        if "disponível" in pagina_lower or "disponivel" in pagina_lower:
            return self._etapa2_concluir_endereco_viavel(cep, numero, referencia)
        return None

    def _etapa2_clicar_avancar_e_tratar_modal(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """Clica Avançar e trata modal de viabilidade (Disponível, Posse, Indisponível)."""
        try:
            modal_sel = (
                'h2:has-text("Disponível"), h2:has-text("Indisponível"), '
                'h1:has-text("Posse encontrada"), h2:has-text("Posse encontrada"), '
                'h3:has-text("Posse encontrada"), '
                'h1:has-text("Pedido encontrado"), h2:has-text("Pedido encontrado"), '
                'h3:has-text("Pedido encontrado"), '
                'h2:has-text("OPS, OCORREU UM ERRO")'
            )
            modal_el = self.page.query_selector(modal_sel)
            spinner = self.page.query_selector('div[class*="spinner"]')
            rapido = self.optimize_for_credit
            # Se modal já visível: pular clique. Se spinner visível: Avançar já foi clicado, aguardar resultado.
            if modal_el and modal_el.is_visible():
                self.page.wait_for_timeout(250 if rapido else 500)
            elif spinner and spinner.is_visible():
                pass
            else:
                try:
                    self.page.wait_for_selector(
                        'button:has-text("Avançar"):not([disabled])',
                        state="visible",
                        timeout=4000,
                    )
                except Exception:
                    pass
                btn = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if not btn:
                    resultado_imediato = self._etapa2_interpretar_resultado_viabilidade(cep, numero, referencia)
                    if resultado_imediato is not None:
                        return resultado_imediato
                    return False, "Botão Avançar não habilitou.", None
                btn.click(force=True)
                self.page.wait_for_timeout(700 if rapido else 2000)

            loops = 36 if rapido else 30
            pausa_ms = 500 if rapido else 600
            resultado: Optional[Tuple[bool, str, Optional[Any]]] = None
            for poll in range(1, loops + 1):
                self.page.wait_for_timeout(pausa_ms)
                resultado = self._etapa2_interpretar_resultado_viabilidade(cep, numero, referencia)
                if resultado is not None:
                    if resultado[0]:
                        logger.info(
                            "[PAP] Etapa2: viabilidade OK no poll %d/%d (%.1fs)",
                            poll, loops, poll * (pausa_ms / 1000),
                        )
                    return resultado

            try:
                self.page.wait_for_selector(modal_sel, state="visible", timeout=8000 if rapido else 12000)
                resultado = self._etapa2_interpretar_resultado_viabilidade(cep, numero, referencia)
                if resultado is not None:
                    return resultado
            except Exception:
                pass

            url_atual = ""
            try:
                url_atual = self.page.url or ""
            except Exception:
                pass
            snippet = ""
            try:
                snippet = (self.page.inner_text("body") or "")[:400]
            except Exception:
                pass
            logger.warning(
                "[PAP] Etapa2: resultado de viabilidade não reconhecido. URL=%s snippet=%r",
                url_atual,
                snippet,
            )
            return False, "Não foi possível obter o resultado da viabilidade.", None
        except Exception as e:
            logger.error(f"[PAP] _etapa2_clicar_avancar_e_tratar_modal: {e}")
            return False, str(e), None

    def _preencher_cpf_representante_apos_consultar_cnpj(self, cpf_rep_limpo: str) -> Tuple[bool, str]:
        """
        Após clicar em Buscar/Consultar com CNPJ, o PAP exibe dois botões:
        "Dados da empresa" e "Dados do representante legal". Só então o campo
        cpfRepresentante fica disponível — não adianta clicar antes do Buscar.
        """
        try:
            t_btn = 25000 if self.optimize_for_credit else 40000
            t_inp = 25000 if self.optimize_for_credit else 35000
            self.page.wait_for_timeout(500 if self.optimize_for_credit else 1000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass

            # Esperar qualquer um dos blocos CNPJ (empresa ou representante) — confirma que a consulta respondeu
            try:
                self.page.wait_for_selector(
                    'button:has-text("Dados do representante legal"), button:has-text("Dados da empresa")',
                    state="visible",
                    timeout=t_btn,
                )
            except Exception:
                logger.warning("[PAP] Botões CNPJ (empresa/representante) não apareceram no tempo esperado; seguindo tentativas.")

            # Não usar o primeiro button.sc-eklfrZ (seria "Dados da empresa"); filtrar pelo texto.
            clicou = False
            for locator in (
                self.page.get_by_role("button", name=re.compile(r"Dados\s+do\s+representante\s+legal", re.I)),
                self.page.locator('button:has-text("Dados do representante legal")').first,
                self.page.locator("button.sc-eklfrZ.jZwwQY").filter(
                    has_text=re.compile(r"representante\s+legal", re.I)
                ).first,
            ):
                try:
                    locator.wait_for(state="visible", timeout=min(t_btn, 15000))
                    locator.click(timeout=t_btn, force=True)
                    clicou = True
                    logger.info("[PAP] CNPJ: clicado em 'Dados do representante legal'")
                    break
                except Exception as e_try:
                    logger.debug(f"[PAP] Tentativa botão representante: {e_try}")
                    continue
            if not clicou:
                return False, (
                    "Não foi possível localizar o botão 'Dados do representante legal' após consultar o CNPJ. "
                    "O portal pode ter alterado a tela."
                )

            self.page.wait_for_timeout(500 if self.optimize_for_credit else 1000)
            sel_rep = 'input[name="cpfRepresentante"]'
            try:
                self.page.wait_for_selector(sel_rep, state="visible", timeout=t_inp)
            except Exception:
                try:
                    self.page.wait_for_selector(sel_rep, state="attached", timeout=10000)
                    self.page.locator(sel_rep).first.scroll_into_view_if_needed()
                    self.page.wait_for_timeout(400)
                    self.page.wait_for_selector(sel_rep, state="visible", timeout=t_inp)
                except Exception:
                    pass
            inp_rep = self.page.query_selector(sel_rep)
            if inp_rep:
                try:
                    inp_rep.click()
                except Exception:
                    self.page.locator(sel_rep).first.click(force=True, timeout=8000)
                inp_rep = self.page.query_selector(sel_rep)
                if inp_rep:
                    inp_rep.fill(cpf_rep_limpo)
                    self.page.keyboard.press("Tab")
            else:
                self._set_valor_react(sel_rep, cpf_rep_limpo)
            return True, ""
        except Exception as e:
            logger.error(f"[PAP] _preencher_cpf_representante_apos_consultar_cnpj: {e}")
            return False, f"Não foi possível preencher CPF do representante legal: {e}"
    
    def _etapa3_ler_valor_input(self, *selectors: str) -> str:
        """Lê value/texto do primeiro input visível entre os seletores."""
        if not self.page:
            return ""
        for sel in selectors:
            try:
                el = self.page.query_selector(sel)
                if not el:
                    continue
                val = (el.get_attribute("value") or el.input_value() or el.inner_text() or "").strip()
                if val:
                    return val
            except Exception:
                continue
        return ""

    def _etapa3_documento_invalido_visivel(self) -> bool:
        """True só se a mensagem 'Documento inválido' estiver visível (não no HTML oculto)."""
        if not self.page:
            return False
        try:
            loc = self.page.get_by_text(re.compile(r"documento\s+inv[aá]lido", re.I))
            if loc.count() <= 0:
                return False
            return bool(loc.first.is_visible())
        except Exception:
            return False

    def _etapa3_cliente_carregado(self) -> bool:
        """True quando a consulta Receita preencheu nome/mãe ou liberou Avançar."""
        if not self.page:
            return False
        try:
            btn = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn and btn.is_visible():
                return True
        except Exception:
            pass
        nome = self._etapa3_ler_valor_input(
            'input[name="nome"]',
            'input[name="nomeCompleto"]',
            'input[name*="nome"]:not([name*="Mae"]):not([name*="mae"])',
        )
        mae = self._etapa3_ler_valor_input('input[name="nomeMae"]', 'input[name*="mae"]')
        # Nome real costuma ter letras; máscara da mãe tem '*'.
        if nome and re.search(r"[A-Za-zÀ-ÿ]", nome):
            return True
        if mae and ("*" in mae or re.search(r"[A-Za-zÀ-ÿ]", mae)):
            return True
        return False

    def _etapa3_preencher_documento(self, cpf_selector: str, cpf_limpo: str) -> bool:
        """
        Preenche CPF/CNPJ respeitando máscara React (fill() costuma ser limpo no blur).
        Digita caractere a caractere — igual ao preenchimento manual.
        """
        if not self.page or not cpf_limpo:
            return False
        try:
            loc = self.page.locator(cpf_selector).first
            loc.wait_for(state="visible", timeout=10000)
            loc.click(timeout=5000)
            # Seleciona tudo e apaga (máscaras ignoram fill vazio às vezes)
            try:
                loc.press("Control+A")
                loc.press("Backspace")
            except Exception:
                try:
                    loc.fill("")
                except Exception:
                    pass
            # Digitação lenta para a máscara 000.000.000-00 / CNPJ aplicar
            delay_ms = 35 if self.optimize_for_credit else 50
            try:
                loc.press_sequentially(cpf_limpo, delay=delay_ms)
            except Exception:
                # Playwright antigo: type()
                loc.type(cpf_limpo, delay=delay_ms)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(400 if self.optimize_for_credit else 700)
            atual = re.sub(
                r"\D",
                "",
                self._etapa3_ler_valor_input(cpf_selector, 'input[name="documento"]'),
            )
            if atual == cpf_limpo:
                logger.info("[PAP] Etapa3: documento preenchido via digitação (%s dígitos)", len(cpf_limpo))
                return True
            # Fallback React setter + re-leitura
            logger.warning(
                "[PAP] Etapa3: digitação deixou doc=%r — tentando _set_valor_react",
                atual,
            )
            self._set_valor_react(cpf_selector, cpf_limpo)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(400)
            atual = re.sub(
                r"\D",
                "",
                self._etapa3_ler_valor_input(cpf_selector, 'input[name="documento"]'),
            )
            ok = atual == cpf_limpo
            if not ok:
                logger.error(
                    "[PAP] Etapa3: falha ao preencher documento (campo=%r esperado=%s)",
                    atual,
                    cpf_limpo,
                )
            return ok
        except Exception as e:
            logger.error("[PAP] Etapa3: erro ao preencher documento: %s", e)
            return False

    def _etapa3_ainda_na_tela_cadastro(self) -> bool:
        """True se o formulário de CPF/CNPJ (etapa 3) ainda está visível."""
        if not self.page:
            return False
        try:
            doc = self.page.query_selector('input[name="documento"]')
            if doc and doc.is_visible():
                return True
        except Exception:
            pass
        # Voltou para CEP da etapa 2?
        try:
            h = self.page.get_by_text(re.compile(r"consulta de viabilidade", re.I))
            if h.count() > 0 and h.first.is_visible():
                return False
        except Exception:
            pass
        try:
            cep = self.page.query_selector(
                'input[placeholder*="CEP"], input[placeholder*="Endereço ou CEP"], input[name="cep"]'
            )
            if cep and cep.is_visible():
                return False
        except Exception:
            pass
        return False

    def _etapa3_url_parece_consulta_documento(self, url: str) -> bool:
        u = (url or "").lower()
        return any(
            trecho in u
            for trecho in (
                "consultareceita",
                "consulta-receita",
                "consulta_receita",
                "/receita",
                "cadastrocliente",
                "cadastro-cliente",
                "novafibra/consulta",
                "portal/novafibra/consulta",
            )
        )

    def _etapa3_clicar_buscar_documento(self) -> bool:
        """
        Clica o Buscar do CPF/CNPJ e tenta confirmar que a API da Receita disparou.

        Em produção o clique Playwright às vezes não acionava a request — por isso
        esperamos a response e temos fallbacks (force, Enter, click JS).
        """
        if not self.page:
            return False
        if not self._etapa3_ainda_na_tela_cadastro():
            logger.warning("[PAP] Etapa3: tela de cadastro não está visível — não clicando Buscar")
            return False

        btn = None
        sel_usado = ""
        candidatos = [
            'div:has(> input[name="documento"]) button:has-text("Buscar"):not([disabled])',
            'div:has(input[name="documento"]) >> button:has-text("Buscar"):not([disabled])',
            'form:has(input[name="documento"]) button:has-text("Buscar"):not([disabled])',
        ]
        for sel in candidatos:
            try:
                loc = self.page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    btn = loc
                    sel_usado = sel
                    break
            except Exception:
                continue
        if btn is None:
            try:
                botoes = self.page.locator('button:has-text("Buscar"):not([disabled])')
                n = min(botoes.count(), 5)
                for i in range(n):
                    cand = botoes.nth(i)
                    if not cand.is_visible():
                        continue
                    box = cand.bounding_box() or {}
                    if box.get("y", 0) < 200:
                        continue
                    btn = cand
                    sel_usado = f"fallback_idx_{i}"
                    break
            except Exception as e:
                logger.debug("[PAP] Etapa3 Buscar fallback: %s", e)
        if btn is None:
            return False

        def _disparar_e_aguardar(acao, rotulo: str) -> bool:
            try:
                with self.page.expect_response(
                    lambda r: self._etapa3_url_parece_consulta_documento(r.url),
                    timeout=18000,
                ) as info:
                    acao()
                resp = info.value
                logger.info(
                    "[PAP] Etapa3: Buscar (%s) → API %s status=%s",
                    rotulo,
                    (resp.url or "")[:110],
                    resp.status,
                )
                return True
            except Exception as e:
                logger.warning("[PAP] Etapa3: Buscar (%s) sem API Receita: %s", rotulo, e)
                return False

        if _disparar_e_aguardar(
            lambda: btn.click(force=True, timeout=5000),
            f"click:{sel_usado[:60]}",
        ):
            return True

        # Enter no campo documento (alguns formulários só submetem assim)
        def _enter_documento():
            self.page.locator('input[name="documento"]').first.focus()
            self.page.keyboard.press("Enter")

        if _disparar_e_aguardar(_enter_documento, "Enter no documento"):
            return True

        # Click nativo no DOM (bypassa hit-target do Playwright)
        if _disparar_e_aguardar(
            lambda: self.page.evaluate(
                """() => {
                    const inp = document.querySelector('input[name="documento"]');
                    if (!inp) return false;
                    const root = inp.closest('form') || inp.closest('div') || document.body;
                    const btn = [...root.querySelectorAll('button')].find(
                        (b) => /buscar/i.test((b.textContent || '').trim()) && !b.disabled
                    );
                    if (!btn) return false;
                    btn.click();
                    return true;
                }"""
            ),
            "JS click",
        ):
            return True

        # Último recurso: clica mesmo sem confirmar a API (espera na etapa seguinte)
        try:
            btn.click(force=True, timeout=5000)
            logger.warning("[PAP] Etapa3: Buscar clicado sem confirmação de API (%s)", sel_usado[:60])
            return True
        except Exception:
            return False

    def _etapa3_modal_bloqueio_endereco(self) -> Optional[str]:
        """Se Pedido/Posse encontrado estiver visível, retorna código normalizado."""
        modal = self._ler_modal_bloqueante_pap()
        if not modal:
            # Texto solto na página (modal com markup atípico)
            try:
                body = (self.page.inner_text("body") or "").lower()
            except Exception:
                body = ""
            if "pedido encontrado" in body or (
                "pedido" in body and "em andamento" in body and "endere" in body
            ):
                return "POSSE_ENCONTRADA"
            if "posse encontrada" in body:
                return "POSSE_ENCONTRADA"
            return None
        codigo = modal.get("codigo") or ""
        if codigo == "PEDIDO_ENCONTRADO":
            return "POSSE_ENCONTRADA"
        if codigo in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return codigo
        return None

    def _diagnostico_etapa3_falha(self, cpf_limpo: str) -> str:
        """Loga e retorna resumo do estado da tela após falha na consulta de documento."""
        if not self.page:
            return "página inexistente"
        try:
            url = (self.page.url or "")[:160]
        except Exception:
            url = "?"
        doc_val = self._etapa3_ler_valor_input(
            'input[name="documento"]',
            'input[name=documento]',
            'input#documento',
        )
        nome = self._etapa3_ler_valor_input(
            'input[name="nome"]',
            'input[name="nomeCompleto"]',
            'input[name*="nome"]:not([name*="Mae"]):not([name*="mae"])',
        )
        mae = self._etapa3_ler_valor_input('input[name="nomeMae"]', 'input[name*="mae"]')
        dt = self._etapa3_ler_valor_input(
            'input[name="dataNascimento"]',
            'input[name*="nascimento"]',
        )
        avancar_ok = False
        avancar_disabled = None
        try:
            btn = self.page.query_selector('button:has-text("Avançar")')
            if btn:
                avancar_disabled = btn.get_attribute("disabled") is not None or (
                    (btn.get_attribute("aria-disabled") or "").lower() == "true"
                )
                avancar_ok = not avancar_disabled and btn.is_visible()
        except Exception:
            pass
        alertas: list[str] = []
        for padrao in (
            r"documento\s+inv[aá]lido",
            r"ops,?\s+ocorreu\s+um\s+erro",
            r"aten[cç][aã]o",
            r"n[aã]o\s+foi\s+poss[ií]vel",
            r"cpf\s+n[aã]o\s+encontrado",
            r"cliente\s+n[aã]o\s+encontrado",
        ):
            try:
                loc = self.page.get_by_text(re.compile(padrao, re.I))
                if loc.count() > 0 and loc.first.is_visible():
                    alertas.append((loc.first.inner_text() or "")[:120].strip())
            except Exception:
                continue
        digitos_doc = re.sub(r"\D", "", doc_val or "")
        na_cadastro = self._etapa3_ainda_na_tela_cadastro()
        bloqueio = self._etapa3_modal_bloqueio_endereco()
        snippet = ""
        try:
            snippet = re.sub(r"\s+", " ", (self.page.inner_text("body") or ""))[:220]
        except Exception:
            pass
        resumo = (
            f"url={url} | tela_cadastro={na_cadastro} | bloqueio={bloqueio!r} | "
            f"doc_campo={doc_val[:20]!r} digitos={digitos_doc} "
            f"(esperado={cpf_limpo}) | nome={nome[:40]!r} | mae={mae[:40]!r} | "
            f"nasc={dt!r} | avancar_ok={avancar_ok} disabled={avancar_disabled} | "
            f"alertas={alertas[:3]!r} | body={snippet!r}"
        )
        logger.error("[PAP] Etapa3 diagnóstico falha: %s", resumo)
        try:
            self._capture_screenshot(
                "03_err_cpf_nao_carregou",
                wait_selector=None,
                wait_timeout_ms=0,
                forcar=True,
            )
        except Exception:
            pass
        return resumo

    def etapa3_cadastro_cliente(self, cpf: str, cpf_representante: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Etapa 3: Cadastro do cliente.
        Campo CPF/CNPJ: input[name="documento"]
        """
        try:
            logger.info(
                "[PAP] Etapa 3 - consultando documento (%s dígitos)",
                len(re.sub(r"\D", "", cpf or "")),
            )
            ok_sessao, msg_sessao = self._garantir_sessao_sem_descartar_pedido()
            if not ok_sessao:
                return False, msg_sessao, None

            # Se o modal Pedido/Posse ficou para trás da etapa 2, não preencher CPF.
            modal_atrasado = self._ler_modal_bloqueante_pap()
            if modal_atrasado and modal_atrasado.get("codigo") in (
                "PEDIDO_ENCONTRADO",
                "POSSE_ENCONTRADA",
            ):
                self._capture_screenshot("03_err_modal_pedido_posse", forcar=True)
                logger.warning(
                    "[PAP] Etapa3: modal %s ainda visível — bloqueio de endereço não tratado na etapa 2",
                    modal_atrasado.get("codigo"),
                )
                return False, (
                    "Já existe pedido/posse em andamento neste endereço "
                    "(modal Pedido encontrado). A análise deveria usar o endereço padrão."
                ), None

            self._etapa3_garantir_tela_documento()
            self.page.wait_for_timeout(400 if self.optimize_for_credit else 1200)
            
            # Aguardar campo CPF/CNPJ (documento) aparecer - timeout alto (rede/React podem demorar em produção)
            cpf_selector = None
            for sel in [
                SELETORES['etapa3']['cpf'],
                'input[name="documento"]',
                'input[name=documento]',
                'input#documento, input[id="documento"]',
                'input[placeholder*="CPF"], input[placeholder*="cpf"], input[placeholder*="ocumento"]',
                'input[aria-label*="CPF"], input[aria-label*="ocumento"]',
            ]:
                try:
                    self.page.wait_for_selector(sel, state="visible", timeout=25000)
                    cpf_selector = sel
                    break
                except Exception:
                    continue
            if not cpf_selector:
                cpf_selector = 'input[name=documento]'
                self.page.wait_for_selector(cpf_selector, state="visible", timeout=25000)
            
            # Preencher CPF/CNPJ digitando (máscara React — fill() apaga o valor)
            cpf_limpo = re.sub(r'\D', '', cpf)
            if not self._etapa3_preencher_documento(cpf_selector, cpf_limpo):
                self._diagnostico_etapa3_falha(cpf_limpo)
                return False, (
                    "Não foi possível preencher o CPF/CNPJ no formulário do PAP "
                    "(máscara do campo). Tente novamente."
                ), None

            # CNPJ: o CPF do representante só pode ser preenchido DEPOIS de Buscar/Consultar
            # (o portal mostra os botões "Dados da empresa" e "Dados do representante legal").
            if len(cpf_limpo) == 14:
                cpf_rep_chk = re.sub(r'\D', '', str(cpf_representante or ''))
                if len(cpf_rep_chk) != 11:
                    return False, "Para CNPJ, informe um CPF válido do representante legal.", None
            
            # Dar tempo para o site validar o documento (evita clicar em Buscar com botão desabilitado)
            self.page.wait_for_timeout(800 if self.optimize_for_credit else 1500)
            if not self._etapa3_ainda_na_tela_cadastro():
                logger.error("[PAP] Etapa3: após preencher documento a tela voltou da etapa 3")
                self._diagnostico_etapa3_falha(cpf_limpo)
                return False, (
                    "O portal saiu da tela de cadastro do cliente após preencher o CPF. "
                    "Digite *CRÉDITO* para tentar novamente."
                ), None
            if self._etapa3_documento_invalido_visivel():
                self._diagnostico_etapa3_falha(cpf_limpo)
                return False, "Documento inválido.", None

            # Aguardar Buscar habilitar (máscara/React) e clicar no da etapa 3
            buscou = False
            for _ in range(10):
                if not self._etapa3_ainda_na_tela_cadastro():
                    logger.error("[PAP] Etapa3: tela de cadastro sumiu antes do Buscar")
                    self._diagnostico_etapa3_falha(cpf_limpo)
                    return False, (
                        "O portal voltou para a consulta de viabilidade antes de buscar o CPF. "
                        "Digite *CRÉDITO* para tentar novamente."
                    ), None
                if self._etapa3_clicar_buscar_documento():
                    buscou = True
                    break
                if self._etapa3_documento_invalido_visivel():
                    self._diagnostico_etapa3_falha(cpf_limpo)
                    return False, "Documento inválido.", None
                self.page.wait_for_timeout(500)
            if not buscou:
                self._diagnostico_etapa3_falha(cpf_limpo)
                return False, "Documento inválido ou CPF não encontrado. Verifique o número digitado.", None

            # CNPJ: após consultar, abrir "Dados do representante legal" e preencher o CPF
            if len(cpf_limpo) == 14:
                cpf_rep_limpo = re.sub(r'\D', '', str(cpf_representante or ''))
                ok_rep, msg_rep = self._preencher_cpf_representante_apos_consultar_cnpj(cpf_rep_limpo)
                if not ok_rep:
                    return False, msg_rep, None

            # Esperar resultado real da Receita — NÃO usar input[disabled][value] genérico
            # (campos vazios disabled fazem a espera acabar cedo e o Avançar ainda fica cinza).
            timeout_resultado = 28000 if self.optimize_for_credit else 35000
            deadline = time.monotonic() + (timeout_resultado / 1000.0)
            while time.monotonic() < deadline:
                if self.verificar_modal_erro_ops_visivel():
                    self._fechar_modal_erro_ops()
                    self._diagnostico_etapa3_falha(cpf_limpo)
                    return False, PAP_ERRO_PORTAL_NIO, None
                bloqueio = self._etapa3_modal_bloqueio_endereco()
                if bloqueio:
                    self._diagnostico_etapa3_falha(cpf_limpo)
                    logger.warning(
                        "[PAP] Etapa3: bloqueio de endereço após Buscar (%s)",
                        bloqueio,
                    )
                    return False, (
                        "Já existe pedido/posse neste endereço. "
                        "A análise deve usar o endereço padrão."
                    ), {"bloqueio_endereco": bloqueio}
                if self._etapa3_documento_invalido_visivel():
                    self._diagnostico_etapa3_falha(cpf_limpo)
                    return False, "Documento inválido.", None
                if self._etapa3_cliente_carregado():
                    break
                self.page.wait_for_timeout(500)
            else:
                # Uma retentativa de Buscar (Receita/API às vezes não dispara no 1º clique)
                logger.warning("[PAP] Etapa3: sem dados do cliente após Buscar — retentando clique")
                if self._etapa3_clicar_buscar_documento():
                    retry_deadline = time.monotonic() + 18.0
                    while time.monotonic() < retry_deadline:
                        if self.verificar_modal_erro_ops_visivel():
                            self._fechar_modal_erro_ops()
                            self._diagnostico_etapa3_falha(cpf_limpo)
                            return False, PAP_ERRO_PORTAL_NIO, None
                        bloqueio = self._etapa3_modal_bloqueio_endereco()
                        if bloqueio:
                            self._diagnostico_etapa3_falha(cpf_limpo)
                            return False, (
                                "Já existe pedido/posse neste endereço. "
                                "A análise deve usar o endereço padrão."
                            ), {"bloqueio_endereco": bloqueio}
                        if self._etapa3_cliente_carregado():
                            break
                        self.page.wait_for_timeout(500)
            
            # Modal "OPS, OCORREU UM ERRO!" após consultar documento (portal instável → orientar chamado Nio)
            if self.verificar_modal_erro_ops_visivel():
                self._fechar_modal_erro_ops()
                self._diagnostico_etapa3_falha(cpf_limpo)
                return False, PAP_ERRO_PORTAL_NIO, None
            
            self._capture_screenshot("03_cpf_cliente_ok", wait_selector='button:has-text("Avançar"):not([disabled])', wait_timeout_ms=5000)
            # Extrair dados do cliente (nome, nome_mae mascarado, mês da data **/MM/**** para CRM)
            dados_cliente = {}
            nome_val = self._etapa3_ler_valor_input(
                'input[name="nome"]',
                'input[name="nomeCompleto"]',
                SELETORES['etapa3']['nome_cliente'],
            )
            if nome_val:
                dados_cliente['nome'] = nome_val
            mae_val = self._etapa3_ler_valor_input('input[name="nomeMae"]', 'input[name*="mae"]')
            if mae_val:
                dados_cliente['nome_mae'] = mae_val
            dt_val = self._etapa3_ler_valor_input(
                'input[name="dataNascimento"]',
                'input[name*="nascimento"]',
            )
            if dt_val:
                match = re.search(r'/(\d{1,2})/', dt_val)
                if match:
                    try:
                        dados_cliente['mes_nascimento'] = int(match.group(1))
                    except ValueError:
                        pass
            
            # Verificar se pode avançar (ou se os dados do cliente já carregaram — Avançar pode atrasar 1 frame)
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not btn_avancar and self._etapa3_cliente_carregado():
                self.page.wait_for_timeout(800)
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                self.etapa_atual = 3
                self.dados_pedido['cpf_cliente'] = cpf
                if cpf_representante:
                    self.dados_pedido['cpf_representante_legal'] = cpf_representante
                self.dados_pedido['nome_cliente'] = dados_cliente.get('nome', '')
                self.dados_pedido['nome_mae'] = dados_cliente.get('nome_mae', '')
                self.dados_pedido['mes_nascimento'] = dados_cliente.get('mes_nascimento')
                return True, f"Cliente encontrado: {dados_cliente.get('nome', 'N/A')}", dados_cliente

            diag = self._diagnostico_etapa3_falha(cpf_limpo)
            # Mensagem curta no WhatsApp + detalhe técnico nos logs/screenshot
            return False, f"CPF não encontrado ou inválido. Detalhe: {diag[:220]}", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 3: {e}")
            try:
                self._diagnostico_etapa3_falha(re.sub(r"\D", "", cpf or ""))
            except Exception:
                pass
            return False, f"Erro na Etapa 3: {str(e)}", None
    
    def _etapa4_limpar_todos_campos_contato(self) -> None:
        """Limpa todos os campos da etapa Contato (principal, confirmação, secundário, email, confirmação) para nova tentativa."""
        try:
            for sel in [
                'input#contato, input[name="contato"]',
                'input#confirmacaoContato, input[name="confirmacaoContato"]',
                'input#contatoSecundario, input[name="contatoSecundario"]',
                'input#email, input[name="email"]',
                'input#confirmarEmail, input[name="confirma-email"]',
            ]:
                inp = self.page.query_selector(sel)
                if inp and inp.is_visible():
                    inp.fill('')
            self.page.wait_for_timeout(300)
        except Exception as e:
            logger.warning(f"[PAP] _etapa4_limpar_todos_campos_contato: {e}")

    def _etapa4_codigo_rejeicao_contato_da_pagina(self, pagina_lower: str) -> Optional[str]:
        """Classifica texto do modal Atenção: telefone/e-mail rejeitado ou inválido."""
        pagina = (pagina_lower or "").lower()
        if (
            "excede" in pagina
            or "repetições" in pagina
            or "repeticoes" in pagina
            or "celular já utilizado" in pagina
            or "celular ja utilizado" in pagina
            or "celular inválido" in pagina
            or "celular invalido" in pagina
        ):
            if "celular inválido" in pagina or "celular invalido" in pagina:
                return "CELULAR_INVALIDO"
            return "TELEFONE_REJEITADO"
        if "email" in pagina and ("usado" in pagina or "pedido anterior" in pagina):
            return "EMAIL_REJEITADO"
        if (
            "e-mail inválido" in pagina
            or "email inválido" in pagina
            or "e-mail invalido" in pagina
            or "email invalido" in pagina
            or "preencha um e-mail válido" in pagina
            or "preencha um email válido" in pagina
            or "preencha um e-mail valido" in pagina
            or "preencha um email valido" in pagina
        ):
            return "EMAIL_INVALIDO"
        return None

    def _etapa4_tratar_modal_atencao_contato(self) -> Optional[str]:
        """
        Fecha o modal Atenção! se estiver aberto e devolve o código de rejeição.

        O PAP às vezes demora alguns segundos após o Avançar para validar o
        e-mail; por isso esta checagem também roda durante a espera do modal
        de crédito (não só no loop curto inicial).
        """
        if not self.page:
            return None
        modal = self.page.query_selector('h2:has-text("Atenção!")')
        if not modal:
            return None
        try:
            if not modal.is_visible():
                return None
        except Exception:
            return None
        pagina = (self._page_content_seguro(tentativas=2, pausa_ms=200) or "").lower()
        codigo = self._etapa4_codigo_rejeicao_contato_da_pagina(pagina)
        texto_modal = self._extrair_texto_ao_redor_titulo(modal) or ""
        btn_ok = self.page.query_selector('button:has-text("Ok")')
        if btn_ok:
            try:
                btn_ok.click(force=True, timeout=3000)
                self.page.wait_for_timeout(300 if self.optimize_for_credit else 500)
            except Exception:
                pass
        if codigo:
            self._etapa4_limpar_todos_campos_contato()
            logger.info(
                "[PAP] [CRÉDITO] Modal Atenção classificado como %s: %s",
                codigo,
                (texto_modal or "(sem texto)").replace("\n", " ")[:200],
            )
        elif texto_modal:
            logger.warning(
                "[PAP] [CRÉDITO] Modal Atenção sem classificação: %s",
                texto_modal.replace("\n", " ")[:300],
            )
        return codigo

    def etapa4_contato(self, celular: str, email: str, celular_secundario: str = None, parar_no_modal_credito: bool = False) -> Tuple[bool, str, Optional[str], Optional[str]]:
        """
        Etapa 4: Informações de contato e análise de crédito.
        Campos: contato, confirmacaoContato, contatoSecundario, email, confirmarEmail
        Trata modal "Atenção!" (telefone/email repetidos, e-mail inválido) e modal de crédito.
        Em erro de celular (inválido/já utilizado/excede repetições): limpa TODOS os campos antes de retornar.
        
        parar_no_modal_credito: se True (fluxo análise de crédito via WhatsApp), NÃO clica em Continuar
        após obter o resultado - evita enviar link de biometria. Retorna com o resultado e encerra.
        
        Returns:
            Tuple (sucesso, mensagem, resultado_credito, screenshot_modal_b64)
            screenshot_modal_b64: base64 da imagem do modal de resultado (quando visível), para envio no WhatsApp.
            Códigos/mensagens de erro comuns: TELEFONE_REJEITADO, EMAIL_REJEITADO, EMAIL_INVALIDO, CREDITO_NEGADO,
            MSG_CREDITO_SEM_TELA_RESULTADO (modal de resultado não exibido — repetir *CRÉDITO* com o documento).
        """
        try:
            logger.info(
                "[PAP] Etapa 4 - preenchendo contato real "
                "(telefone=%s dígitos, email_configurado=%s)",
                len(re.sub(r"\D", "", celular or "")),
                bool(email),
            )
            modo_rapido_credito = self.optimize_for_credit and parar_no_modal_credito
            ok_sessao, msg_sessao = self._garantir_sessao_sem_descartar_pedido()
            if not ok_sessao:
                return False, msg_sessao, None, None

            contato_selector = 'input#contato, input[name="contato"]'
            contato_visivel = self.page.query_selector(contato_selector)
            contato_visivel = bool(contato_visivel and contato_visivel.is_visible())

            if not contato_visivel:
                # A página mantém botões "Avançar" de etapas anteriores no DOM.
                # Escolher explicitamente o último botão visível evita clicar em
                # elemento oculto/stale.
                botoes_avancar = self.page.locator('button:has-text("Avançar")')
                clicou = False
                for indice in reversed(range(botoes_avancar.count())):
                    botao = botoes_avancar.nth(indice)
                    if botao.is_visible() and botao.is_enabled():
                        botao.scroll_into_view_if_needed()
                        botao.click()
                        clicou = True
                        break
                if not clicou:
                    return (
                        False,
                        "Botão Avançar da etapa de cadastro não está disponível.",
                        None,
                        None,
                    )

                # A API de duplicidade do PAP pode levar mais de 15 s. Em redes
                # lentas, aguardar até 45 s e repetir o clique uma única vez se
                # a etapa 3 continuar visível. Também mapeia modais bloqueantes
                # (Pedido encontrado / Posse / erro do portal).
                transicao_selector = (
                    f'{contato_selector}, '
                    'h1:has-text("Pedido encontrado"), '
                    'h2:has-text("Pedido encontrado"), '
                    'h3:has-text("Pedido encontrado"), '
                    'h1:has-text("Posse encontrada"), '
                    'h2:has-text("Posse encontrada"), '
                    'h3:has-text("Posse encontrada"), '
                    'h2:has-text("OPS, OCORREU UM ERRO"), '
                    'h2:has-text("Atenção!")'
                )
                for tentativa_transicao in range(2):
                    try:
                        self.page.wait_for_selector(
                            transicao_selector,
                            state="visible",
                            timeout=25000 if tentativa_transicao == 0 else 20000,
                        )
                        contato = self.page.query_selector(contato_selector)
                        contato_visivel = bool(
                            contato and contato.is_visible()
                        )
                        if contato_visivel:
                            break
                        modal_bloqueante = self._ler_modal_bloqueante_pap()
                        if modal_bloqueante:
                            self._capture_screenshot(
                                f"04_modal_{modal_bloqueante['codigo'].lower()}",
                                forcar=True,
                            )
                            if modal_bloqueante["codigo"] == PAP_ERRO_PORTAL_NIO:
                                self._fechar_modal_erro_ops()
                                return False, PAP_ERRO_PORTAL_NIO, None, None
                            msg_modal = self._mensagem_usuario_modal_bloqueante(
                                modal_bloqueante,
                                etapa="contato",
                            )
                            return False, msg_modal, None, None
                        # Atenção! sem classificação específica: extrai texto e informa.
                        modal_atencao = self.page.query_selector(
                            'h2:has-text("Atenção!")'
                        )
                        if modal_atencao and modal_atencao.is_visible():
                            texto_atencao = self._extrair_texto_ao_redor_titulo(
                                modal_atencao
                            )
                            self._capture_screenshot(
                                "04_modal_atencao_bloqueio",
                                forcar=True,
                            )
                            btn_ok = self.page.query_selector(
                                'button:has-text("Ok")'
                            )
                            if btn_ok:
                                btn_ok.click()
                            return (
                                False,
                                (
                                    "❌ *Atenção!*\n\n"
                                    f"{texto_atencao or 'O PAP bloqueou o avanço nesta etapa.'}\n\n"
                                    "Não foi possível avançar para a análise de crédito "
                                    "com este cliente."
                                ),
                                None,
                                None,
                            )
                    except Exception:
                        if self.verificar_modal_erro_ops_visivel():
                            self._capture_screenshot(
                                "04_erro_portal_antes_contato",
                                forcar=True,
                            )
                            self._fechar_modal_erro_ops()
                            return False, PAP_ERRO_PORTAL_NIO, None, None
                        modal_bloqueante = self._ler_modal_bloqueante_pap()
                        if modal_bloqueante:
                            self._capture_screenshot(
                                f"04_modal_{modal_bloqueante['codigo'].lower()}",
                                forcar=True,
                            )
                            msg_modal = self._mensagem_usuario_modal_bloqueante(
                                modal_bloqueante,
                                etapa="contato",
                            )
                            return False, msg_modal, None, None
                        if tentativa_transicao == 0:
                            botao = self.page.locator(
                                'button:has-text("Avançar"):visible'
                            ).last
                            try:
                                if botao.is_enabled():
                                    logger.warning(
                                        "[PAP] Etapa 4 não carregou em 25s; "
                                        "repetindo clique em Avançar."
                                    )
                                    botao.click()
                            except Exception:
                                pass

                if not contato_visivel:
                    modal_bloqueante = self._ler_modal_bloqueante_pap()
                    if modal_bloqueante:
                        self._capture_screenshot(
                            f"04_modal_{modal_bloqueante['codigo'].lower()}",
                            forcar=True,
                        )
                        msg_modal = self._mensagem_usuario_modal_bloqueante(
                            modal_bloqueante,
                            etapa="contato",
                        )
                        return False, msg_modal, None, None
                    self._capture_screenshot(
                        "04_erro_formulario_contato_nao_abriu",
                        forcar=True,
                    )
                    return (
                        False,
                        "O PAP não abriu o formulário de contato após 45 segundos.",
                        None,
                        None,
                    )
            
            # Fechar modal "Atenção!" se já estiver aberto (ex: de tentativa anterior)
            modal_atencao = self.page.query_selector('h2:has-text("Atenção!")')
            if modal_atencao:
                btn_ok = self.page.query_selector('button:has-text("Ok")')
                if btn_ok:
                    btn_ok.click()
                    self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
            
            celular_limpo = re.sub(r'\D', '', celular)
            
            # Preencher celular principal e confirmação
            inp_contato = self.page.query_selector('input#contato, input[name="contato"]')
            inp_confirmar = self.page.query_selector('input#confirmacaoContato, input[name="confirmacaoContato"]')
            if inp_contato:
                inp_contato.fill(celular_limpo)
            if inp_confirmar:
                inp_confirmar.fill(celular_limpo)
            
            # Celular secundário (opcional)
            if celular_secundario:
                cel_sec_limpo = re.sub(r'\D', '', celular_secundario)
                inp_sec = self.page.query_selector('input#contatoSecundario, input[name="contatoSecundario"]')
                if inp_sec:
                    inp_sec.fill(cel_sec_limpo)
            
            # E-mail e confirmação
            inp_email = self.page.query_selector('input#email, input[name="email"]')
            inp_confirmar_email = self.page.query_selector('input#confirmarEmail, input[name="confirma-email"]')
            if inp_email:
                inp_email.fill(email)
            if inp_confirmar_email:
                inp_confirmar_email.fill(email)
            
            # Disparar validação (Tab para sair do último campo)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(300 if modo_rapido_credito else 800)
            
            pagina_lower = self.page.content().lower()
            # Celular inválido ou já utilizado (mensagem inline ou validação)
            if "celular inválido" in pagina_lower or "celular já utilizado" in pagina_lower:
                self._etapa4_limpar_todos_campos_contato()
                return False, "CELULAR_INVALIDO", None, None
            
            # Verificar modal "Atenção!" (email já usado ou inválido) - pode aparecer ao validar
            codigo_pre = self._etapa4_tratar_modal_atencao_contato()
            if codigo_pre:
                return False, codigo_pre, None, None
            
            # Clicar Avançar para disparar análise de crédito
            t_avancar = time.time()
            self._credito_apis_pos_avancar = set()
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
            else:
                self.page.keyboard.press("Tab")
                self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if btn_avancar:
                    btn_avancar.click()
            
            # Verificar modal "Atenção!" e modal "OPS, OCORREU UM ERRO!" (erro do portal)
            # Em crédito: mais tentativas — a validação de e-mail do Nio costuma
            # demorar alguns segundos após o Avançar.
            loops_atencao = 12 if modo_rapido_credito else 8
            pausa_atencao_ms = 400 if modo_rapido_credito else 500
            for _ in range(loops_atencao):
                self.page.wait_for_timeout(pausa_atencao_ms)
                if self.verificar_modal_erro_ops_visivel():
                    self._fechar_modal_erro_ops()
                    return False, PAP_ERRO_PORTAL_NIO, None, None
                codigo_atencao = self._etapa4_tratar_modal_atencao_contato()
                if codigo_atencao:
                    return False, codigo_atencao, None, None
            t_apos_atencao = time.time()
            if parar_no_modal_credito:
                logger.info("[PAP] [CRÉDITO] Etapa4: loop Atenção=%.1fs (desde clique Avançar)", t_apos_atencao - t_avancar)
            
            # Fluxo crédito: priorizar modal; fallback etapa 5 só com UI pronta (sem overlay de loading).
            # Fluxo venda: pode encerrar antes se Etapa 5 aparecer sem modal (aprovação todas as formas).
            modal_apareceu = False
            etapa5_apos_credito = False
            poll_iteracao = 0
            loops_modal = 50 if modo_rapido_credito else 36
            pausa_modal_ms = 350 if modo_rapido_credito else 600
            for _ in range(loops_modal):
                self.page.wait_for_timeout(pausa_modal_ms)
                poll_iteracao += 1
                if self.verificar_modal_erro_ops_visivel():
                    self._fechar_modal_erro_ops()
                    return False, PAP_ERRO_PORTAL_NIO, None, None
                codigo_atencao = self._etapa4_tratar_modal_atencao_contato()
                if codigo_atencao:
                    return False, codigo_atencao, None, None
                pagina_texto = self._page_content_seguro(tentativas=2, pausa_ms=350).lower()
                carregando = self._pagina_carregando_apos_credito()
                etapa5_visivel = (
                    False
                    if (parar_no_modal_credito and carregando)
                    else self._etapa5_pagamento_visivel(
                        exigir_ui_pronta=parar_no_modal_credito
                    )
                )
                modal_credito = self.page.query_selector('h2:has-text("Resultado da análise de crédito")')
                negado_pagina = self._pagina_indica_credito_negado(pagina_texto)
                if carregando and parar_no_modal_credito and poll_iteracao % 6 == 0:
                    logger.info(
                        "[PAP] [CRÉDITO] Etapa4: aguardando fim do loading (poll=%d, apis=%s)",
                        poll_iteracao,
                        sorted(self._credito_apis_pos_avancar),
                    )
                if parar_no_modal_credito and etapa5_visivel and not negado_pagina:
                    etapa5_apos_credito = True
                    logger.info(
                        "[PAP] [CRÉDITO] Etapa4: etapa pagamento visível sem modal "
                        "(PAP pulou popup — tratando como aprovação todas as formas, poll=%d, apis=%s)",
                        poll_iteracao,
                        sorted(self._credito_apis_pos_avancar),
                    )
                    break
                # Só atalho quando NÃO é fluxo crédito: etapa 5 visível e modal não apareceu = todas as formas
                if not parar_no_modal_credito and etapa5_visivel and not (modal_credito and modal_credito.is_visible()):
                    self.etapa_atual = 4
                    self.dados_pedido['celular'] = celular
                    self.dados_pedido['email'] = email
                    if celular_secundario:
                        self.dados_pedido['celular_sec'] = celular_secundario
                    return True, "Análise de crédito: APROVADO! (Elegível para todas as formas de pagamento)", "Elegível para todas as formas de pagamento", None
                if modal_credito and modal_credito.is_visible():
                    modal_apareceu = True
                    t_modal_visivel = time.time()
                    if parar_no_modal_credito:
                        logger.info(
                            "[PAP] [CRÉDITO] Etapa4: modal 'Resultado análise crédito' visível em %.1fs (poll=%d x %.1fs)",
                            t_modal_visivel - t_avancar, poll_iteracao, (pausa_modal_ms / 1000),
                        )
                    break
            if not modal_apareceu:
                try:
                    self.page.wait_for_selector(
                        'h2:has-text("Resultado da análise de crédito")',
                        state="visible",
                        timeout=12000 if modo_rapido_credito else 10000,
                    )
                    modal_apareceu = True
                    t_modal_visivel = time.time()
                    if parar_no_modal_credito:
                        logger.info(
                            "[PAP] [CRÉDITO] Etapa4: modal visível via wait_for_selector em %.1fs (após %d iterações)",
                            t_modal_visivel - t_avancar, poll_iteracao,
                        )
                except Exception:
                    if self.verificar_modal_erro_ops_visivel():
                        self._fechar_modal_erro_ops()
                        return False, PAP_ERRO_PORTAL_NIO, None, None
                    pass
            if parar_no_modal_credito and not modal_apareceu and not etapa5_apos_credito:
                for extra in range(60):
                    self.page.wait_for_timeout(500)
                    codigo_atencao = self._etapa4_tratar_modal_atencao_contato()
                    if codigo_atencao:
                        return False, codigo_atencao, None, None
                    if self._pagina_carregando_apos_credito():
                        continue
                    pagina_extra = self._page_content_seguro(tentativas=2, pausa_ms=300).lower()
                    if self._pagina_indica_credito_negado(pagina_extra):
                        break
                    modal_extra = self.page.query_selector(
                        'h2:has-text("Resultado da análise de crédito")'
                    )
                    if modal_extra and modal_extra.is_visible():
                        modal_apareceu = True
                        logger.info(
                            "[PAP] [CRÉDITO] Etapa4: modal visível na fase extra (extra=%d)",
                            extra + 1,
                        )
                        break
                    if self._etapa5_pagamento_visivel(exigir_ui_pronta=True):
                        etapa5_apos_credito = True
                        logger.info(
                            "[PAP] [CRÉDITO] Etapa4: etapa pagamento detectada após poll "
                            "(extra=%d, apis=%s)",
                            extra + 1,
                            sorted(self._credito_apis_pos_avancar),
                        )
                        break
            self.page.wait_for_timeout(300 if modo_rapido_credito else 800)
            if parar_no_modal_credito and modal_apareceu:
                logger.info("[PAP] [CRÉDITO] Etapa4: total desde Avançar até leitura/screenshot=%.1fs", time.time() - t_avancar)
            if self.verificar_modal_erro_ops_visivel():
                self._fechar_modal_erro_ops()
                return False, PAP_ERRO_PORTAL_NIO, None, None
            pagina_texto = self._page_content_seguro().lower()
            if parar_no_modal_credito and not modal_apareceu and etapa5_apos_credito:
                if self._pagina_carregando_apos_credito():
                    self._aguardar_fim_carregamento_credito(
                        timeout_ms=12000 if modo_rapido_credito else 30000
                    )
                modal_tardio = self.page.query_selector(
                    'h2:has-text("Resultado da análise de crédito")'
                )
                if modal_tardio and modal_tardio.is_visible():
                    modal_apareceu = True
                    logger.info("[PAP] [CRÉDITO] Etapa4: modal apareceu após aguardar fim do loading")
                elif not self._etapa5_pagamento_visivel(exigir_ui_pronta=True):
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: etapa 5 não confirmada após loading; "
                        "não concluir como aprovado. apis=%s",
                        sorted(self._credito_apis_pos_avancar),
                    )
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
            if parar_no_modal_credito and not modal_apareceu and etapa5_apos_credito:
                screenshot_b64 = None
                try:
                    screenshot_bytes = self.page.screenshot(type="png")
                    if screenshot_bytes:
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                except Exception as ex:
                    logger.warning(
                        "[PAP] Falha ao capturar screenshot etapa5 pós-crédito: %s", ex
                    )
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                if celular_secundario:
                    self.dados_pedido['celular_sec'] = celular_secundario
                return (
                    True,
                    "Análise de crédito: APROVADO! (Elegível para todas as formas de pagamento)",
                    "Elegível para todas as formas de pagamento",
                    screenshot_b64,
                )
            if parar_no_modal_credito and not modal_apareceu:
                neg_sem_modal = self._pagina_indica_credito_negado(pagina_texto)
                if not neg_sem_modal:
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: modal 'Resultado da análise de crédito' não apareceu; "
                        "não concluir como aprovado (etapa 5 ou texto isolado não bastam). apis=%s",
                        sorted(self._credito_apis_pos_avancar),
                    )
                    self._capture_screenshot(
                        "04_err_sem_modal_credito",
                        wait_selector=None,
                        wait_timeout_ms=0,
                        forcar=True,
                    )
                    try:
                        url_final = (self.page.url or "")[:160]
                        trecho = (pagina_texto or "")[:400].replace("\n", " ")
                        logger.warning(
                            "[PAP] [CRÉDITO] Etapa4 sem modal — url=%s texto=%s",
                            url_final,
                            trecho,
                        )
                    except Exception:
                        pass
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
            # Normalizar para comparação: acentos e variações (cartão/cartao, etc.)
            pagina_norm = unicodedata.normalize("NFD", pagina_texto)
            pagina_norm = "".join(c for c in pagina_norm if unicodedata.category(c) != "Mn")
            # Crédito negado - capturar screenshot do modal e fechar antes de retornar
            if self._pagina_indica_credito_negado(pagina_texto):
                screenshot_b64 = None
                # O motivo é lido antes de fechar o modal, senão o texto some.
                motivo_negativa = self._ler_motivo_credito_negado()
                try:
                    screenshot_bytes = self.page.screenshot(type="png")
                    if screenshot_bytes:
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                except Exception as ex:
                    logger.warning("[PAP] Falha ao capturar screenshot do modal de crédito (negado): %s", ex)
                for btn_text in ['Consultar outro CPF/CNPJ', 'Ok', 'Fechar']:
                    btn = self.page.query_selector(f'button:has-text("{btn_text}")')
                    if btn:
                        try:
                            btn.click()
                            self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
                        except Exception:
                            pass
                        break
                if motivo_negativa:
                    logger.info(
                        "[PAP] Análise de crédito negada. Motivo do modal: %s",
                        motivo_negativa,
                    )
                return False, "CREDITO_NEGADO", motivo_negativa or None, screenshot_b64
            # Crédito aprovado (todas formas ou apenas cartão): exige modal visível no fluxo CRÉDITO
            if "crédito aprovado" in pagina_texto or "credito aprovado" in pagina_texto:
                if parar_no_modal_credito and not modal_apareceu:
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: texto de aprovado sem modal oficial; tratando como sem resultado."
                    )
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
                screenshot_b64 = None
                try:
                    screenshot_bytes = self.page.screenshot(type="png")
                    if screenshot_bytes:
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                except Exception as ex:
                    logger.warning("[PAP] Falha ao capturar screenshot do modal de crédito (aprovado): %s", ex)
                # Detectar "apenas/somente cartão": variações com e sem acento (pagina_norm = texto sem acentos)
                # Frase do site: "Elegível apenas para a forma de pagamento: Cartão de Crédito"
                indicadores_apenas_cartao = (
                    ("elegivel apenas para" in pagina_norm and "cartao" in pagina_norm)
                    or ("apenas" in pagina_norm and "cartao" in pagina_norm)
                    or ("somente" in pagina_norm and "cartao" in pagina_norm)
                    or ("so cartao" in pagina_norm)
                    or ("apenas para cartao" in pagina_norm)
                )
                indicador_todas_formas = (
                    "todas as formas" in pagina_norm
                    or "todas as formas de pagamento" in pagina_norm
                )
                if indicadores_apenas_cartao and not indicador_todas_formas:
                    resultado_credito = "Elegível apenas para Cartão de Crédito"
                    logger.info("[PAP] Análise de crédito: aprovado APENAS para Cartão de Crédito (modal detectado).")
                else:
                    resultado_credito = "Elegível para todas as formas de pagamento"
                    logger.info("[PAP] Análise de crédito: aprovado para todas as formas de pagamento (modal detectado).")
                # Não clicar Continuar quando parar_no_modal_credito (evita enviar link biometria)
                if not parar_no_modal_credito:
                    try:
                        self.page.locator('button:has-text("Continuar")').first.click(force=True, timeout=5000)
                        self.page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        self.page.evaluate("""() => {
                            const btns = [...document.querySelectorAll('button')];
                            const c = btns.find(b => b.textContent.includes('Continuar'));
                            if (c) c.click();
                        }""")
                        self.page.wait_for_timeout(2000)
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                if celular_secundario:
                    self.dados_pedido['celular_sec'] = celular_secundario
                return True, f"Análise de crédito: APROVADO! ({resultado_credito})", resultado_credito, screenshot_b64
            # Etapa 5 visível sem modal (fluxo venda ou crédito já tratado acima)
            if self._etapa5_pagamento_visivel(exigir_ui_pronta=parar_no_modal_credito):
                if parar_no_modal_credito and not modal_apareceu and not etapa5_apos_credito:
                    etapa5_apos_credito = True
                if parar_no_modal_credito and not modal_apareceu and not etapa5_apos_credito:
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: etapa pagamento visível sem modal de resultado; não concluir como aprovado."
                    )
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                if celular_secundario:
                    self.dados_pedido['celular_sec'] = celular_secundario
                return True, "Análise de crédito: APROVADO! (Elegível para todas as formas de pagamento)", "Elegível para todas as formas de pagamento", None
            return False, "Não foi possível obter resultado da análise de crédito.", None, None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 4: {e}")
            return False, f"Erro na Etapa 4: {str(e)}", None, None
    
    def _etapa5_garantir_pagina(self):
        """Garante que a página da etapa 5 (pagamento/ofertas) está carregada."""
        timeout_ms = 35000
        self.page.wait_for_timeout(350)

        def _fechar_continuar_modal_credito():
            try:
                loc = self.page.locator('button:has-text("Continuar")').first
                if loc.is_visible(timeout=900):
                    loc.click(force=True, timeout=5000)
                    self.page.wait_for_timeout(500)
            except Exception:
                pass

        def _expandir_secao_forma_pagamento():
            for sel in (
                'span:has-text("Forma de pagamento")',
                'div:has-text("Forma de pagamento")',
                'button:has-text("Forma de pagamento")',
            ):
                try:
                    el = self.page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        self.page.wait_for_timeout(400)
                        return
                except Exception:
                    continue

        # Radios da forma de pagamento (value fixo no PAP); não exige name="radio-group" (UI muda).
        radio_js_fn = """() => {
            const vals = ['BOLETO','CREDITO','DACC'];
            for (const inp of document.querySelectorAll('input[type="radio"]')) {
                if (vals.includes(inp.value)) return true;
            }
            return false;
        }"""

        deadline = time.time() + (timeout_ms / 1000.0)
        last_err = None
        for _ in range(6):
            _fechar_continuar_modal_credito()
            _expandir_secao_forma_pagamento()
            remaining_ms = max(1500, int((deadline - time.time()) * 1000))
            try:
                self.page.wait_for_function(radio_js_fn, timeout=min(8000, remaining_ms))
                return
            except Exception as e:
                last_err = e
            try:
                self.page.keyboard.press("PageDown")
                self.page.wait_for_timeout(250)
                self.page.keyboard.press("End")
                self.page.wait_for_timeout(350)
            except Exception:
                pass
            if time.time() >= deadline:
                break

        try:
            self.page.wait_for_selector(
                'input[type="radio"][value="BOLETO"], input[type="radio"][value="CREDITO"], input[type="radio"][value="DACC"]',
                state="attached",
                timeout=max(2000, int((deadline - time.time()) * 1000)),
            )
            return
        except Exception as e:
            last_err = e

        _fechar_continuar_modal_credito()
        _expandir_secao_forma_pagamento()

        try:
            self.page.locator(
                'input[name="radio-group"][value="BOLETO"], input[name="radio-group"][value="CREDITO"], input[name="radio-group"][value="DACC"]'
            ).first.wait_for(state="attached", timeout=12000)
            return
        except Exception as e:
            last_err = e

        try:
            self.page.locator('input[name="radio-group"]').first.wait_for(state="attached", timeout=8000)
            return
        except Exception as e:
            last_err = e

        # Textos visíveis (acentos / capitalização diferentes no React)
        for pattern in (
            re.compile(r"Boleto"),
            re.compile(r"Cart[aã]o.*[Cc]r[eé]dito"),
            re.compile(r"D[eé]bito.*[Cc]onta"),
            re.compile(r"forma\s+de\s+pagamento", re.I),
        ):
            try:
                self.page.get_by_text(pattern).first.wait_for(state="visible", timeout=7000)
                return
            except Exception as e:
                last_err = e
                continue

        if last_err:
            raise last_err
        raise TimeoutError("_etapa5_garantir_pagina: sem indicadores de forma de pagamento")

    def etapa5_selecionar_forma_pagamento(self, forma_pagamento: str) -> Tuple[bool, str]:
        """Seleciona a forma de pagamento na etapa 5 (Boleto/Cartão/Débito)."""
        try:
            self._etapa5_garantir_pagina()
            forma_map = {'boleto': 'BOLETO', 'cartao': 'CREDITO', 'cartão': 'CREDITO', 'debito': 'DACC', 'débito': 'DACC'}
            valor = forma_map.get(forma_pagamento.lower().strip(), 'BOLETO')
            self.page.wait_for_timeout(500)
            # Expandir seção "Forma de pagamento" se estiver colapsada
            try:
                header = self.page.query_selector('div:has-text("Forma de pagamento")')
                if header:
                    header.click()
                    self.page.wait_for_timeout(400)
            except Exception:
                pass
            radio = self.page.query_selector(f'input[type="radio"][value="{valor}"]')
            if not radio:
                radio = self.page.query_selector(f'input[name="radio-group"][value="{valor}"]')
            if not radio:
                radio = self.page.query_selector(f'input[value="{valor}"]')
            if radio:
                try:
                    radio.click(force=True)
                except Exception:
                    self.page.evaluate(f"""() => {{
                        const r = document.querySelector('input[value="{valor}"], input[name="radio-group"][value="{valor}"]');
                        if (r) r.click();
                    }}""")
            else:
                lbl_text = {'BOLETO': 'Boleto', 'CREDITO': 'Cartão de Crédito', 'DACC': 'Débito em Conta'}.get(valor, 'Boleto')
                lbl = self.page.query_selector(f'label:has-text("{lbl_text}")')
                if lbl:
                    lbl.click(force=True)
            self.page.wait_for_timeout(600)
            checked = self.page.query_selector(f'input[value="{valor}"]:checked, input[name="radio-group"][value="{valor}"]:checked')
            if not checked:
                logger.warning(f"[PAP] Forma {valor} pode não ter sido selecionada - radio não está checked")
            self.dados_pedido['forma_pagamento'] = forma_pagamento
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar forma: {e}")
            return False, str(e)

    def etapa5_preencher_debito(self, banco: str, agencia: str, conta: str, digito: str) -> Tuple[bool, str]:
        """Preenche campos de débito em conta. Chamar após selecionar forma débito."""
        try:
            self._etapa5_garantir_pagina()
            inp_banco = self.page.query_selector(SELETORES['etapa5']['banco_input'])
            if inp_banco and banco:
                inp_banco.click()
                inp_banco.fill(banco)
                self.page.wait_for_timeout(500)
                opt = self.page.query_selector(f'[role="option"]:has-text("{banco[:10]}"), li:has-text("{banco[:10]}")')
                if opt:
                    opt.click()
            if agencia:
                self.page.fill('input[name="agencia"]', agencia)
            if conta:
                self.page.fill('input[name="conta"]', conta)
            if digito:
                self.page.fill('input[name="digito"]', digito)
            self.dados_pedido['banco_dacc'] = banco
            self.dados_pedido['agencia_dacc'] = agencia
            self.dados_pedido['conta_dacc'] = conta
            self.dados_pedido['digito_dacc'] = digito
            self.page.wait_for_timeout(500)
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao preencher débito: {e}")
            return False, str(e)

    def etapa5_selecionar_plano(self, plano: str) -> Tuple[bool, str]:
        """Seleciona o plano (oferta): 1 Giga, 700 Mega ou 500 Mega. Clica no card/container correto."""
        try:
            self._etapa5_garantir_pagina()
            self.page.wait_for_timeout(500)
            plano_map = {'1giga': ('1 Giga', 'Velocidade 1 Giga'), '700mega': ('700 Mega', 'Velocidade 700 Mega'), '500mega': ('500 Mega', 'Velocidade 500 Mega')}
            txt_plano, txt_vel = plano_map.get(plano.lower().strip(), ('500 Mega', 'Velocidade 500 Mega'))
            # Encontrar o li "Velocidade X Mega/Giga" e clicar no card pai (evita clicar no card errado)
            li_vel = self.page.query_selector(f'li:has-text("Velocidade {txt_plano}")')
            if li_vel:
                li_vel.evaluate("""el => {
                    const card = el.closest('[class*="card"], [class*="Card"], [class*="sc-"]');
                    if (card) card.click();
                    else el.click();
                }""")
            else:
                card = self.page.query_selector(f'[class*="card"]:has-text("{txt_plano}")')
                if not card:
                    card = self.page.query_selector(f'div:has-text("{txt_plano}"):has-text("Velocidade")')
                if not card:
                    card = self.page.query_selector(f'label:has-text("{txt_plano}")')
                if card:
                    card.click(force=True)
            self.page.wait_for_timeout(600)
            self.dados_pedido['plano'] = plano
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar plano: {e}")
            return False, str(e)

    def etapa5_verificar_plano_selecionado_no_dom(self, plano: str) -> Tuple[bool, str]:
        """
        Confere no DOM da etapa 5 se o plano desejado está selecionado (sem clicar de novo).
        O PAP usa <li> com ícone SVG (MuiSvgIcon check em círculo) + texto "Velocidade X", sem radio nativo.
        Deve ser chamado logo após etapa5_selecionar_plano, antes de Fixo/Streaming.
        """
        pl = plano.lower().strip()
        if pl not in ("1giga", "700mega", "500mega"):
            return True, ""
        try:
            r = self.page.evaluate(
                """(planoKey) => {
                    const norm = (t) => (t || '').replace(/\\s+/g, ' ').trim();
                    const mapNeed = {
                        '1giga': '1 Giga',
                        '700mega': '700 Mega',
                        '500mega': '500 Mega',
                    };
                    const needShort = mapNeed[planoKey] || '500 Mega';
                    const needLine = 'Velocidade ' + needShort;

                    function matchSpeedLine(li) {
                        const t = norm(li.textContent);
                        if (!t.includes('Velocidade')) return false;
                        if (planoKey === '500mega') return /Velocidade\\s+500\\s+Mega/i.test(t);
                        if (planoKey === '700mega') return /Velocidade\\s+700\\s+Mega/i.test(t);
                        if (planoKey === '1giga') return /Velocidade\\s+1\\s*Giga/i.test(t);
                        return false;
                    }

                    function isCheckmarkSvg(li) {
                        const svg = li && li.querySelector('svg');
                        if (!svg) return false;
                        if (svg.classList && svg.classList.contains('MuiSvgIcon-root')) {
                            const paths = svg.querySelectorAll('path');
                            for (const p of paths) {
                                const d = (p.getAttribute('d') || '');
                                if (d.includes('M12 2C6.48')) return true;
                                if (d.includes('M9 16.17')) return true;
                                if (d.includes('M4.25 4.25')) return true;
                            }
                        }
                        const paths = svg.querySelectorAll('path');
                        for (const p of paths) {
                            const d = (p.getAttribute('d') || '');
                            if (d.length > 40 && (d.includes('M12 2C6') || d.includes('12 2C6.48'))) return true;
                        }
                        return false;
                    }

                    const lis = [...document.querySelectorAll('li')];
                    for (const li of lis) {
                        if (!matchSpeedLine(li)) continue;
                        if (isCheckmarkSvg(li)) return { ok: true, msg: '' };
                    }

                    for (const li of lis) {
                        if (!matchSpeedLine(li)) continue;
                        const svg = li.querySelector('svg');
                        if (svg && svg.querySelector('path[d*="M12 2C6"]')) return { ok: true, msg: '' };
                    }

                    for (const li of lis) {
                        if (!matchSpeedLine(li)) continue;
                        const inp = li.querySelector('input[type=radio], input[type=checkbox]');
                        if (inp && inp.checked) return { ok: true, msg: '' };
                    }

                    let outroComCheck = '';
                    for (const li of lis) {
                        const t = norm(li.textContent);
                        if (!/Velocidade\\s+(1\\s*Giga|700\\s*Mega|500\\s*Mega)/i.test(t)) continue;
                        if (!isCheckmarkSvg(li)) continue;
                        const m = t.match(/Velocidade\\s+(1\\s*Giga|700\\s*Mega|500\\s*Mega)/i);
                        outroComCheck = m ? m[0] : t.slice(0, 80);
                        break;
                    }
                    return {
                        ok: false,
                        msg: outroComCheck
                            ? ('Outra velocidade com ícone de confirmação: ' + outroComCheck
                                + ' (esperado: ' + needLine + ').')
                            : ('Não encontramos o <li> com texto "' + needLine + '" e SVG de check (ex.: path M12 2C6.48). '
                                + 'Confira no navegador se o card certo está selecionado.'),
                    };
                }""",
                pl,
            )
            if r and r.get("ok"):
                return True, ""
            return False, (r or {}).get("msg") or "Validação do plano falhou."
        except Exception as e:
            logger.warning("[PAP] etapa5_verificar_plano_selecionado_no_dom: %s", e)
            return False, str(e)

    def etapa5_selecionar_plano_com_validacao(self, plano: str) -> Tuple[bool, str]:
        """
        Seleciona o plano e valida no DOM antes de seguir para serviços adicionais.
        Repete a seleção uma vez se a validação falhar (sem resetar Fixo/Streaming — ainda não foram preenchidos).
        """
        ultimo_erro = ""
        for tentativa in range(2):
            ok, msg = self.etapa5_selecionar_plano(plano)
            if not ok:
                return False, msg
            self.page.wait_for_timeout(500)
            vok, vmsg = self.etapa5_verificar_plano_selecionado_no_dom(plano)
            if vok:
                return True, "OK"
            ultimo_erro = vmsg
            logger.warning(
                "[PAP] Plano não confirmado no DOM após seleção (tentativa %s/2): %s",
                tentativa + 1,
                vmsg,
            )
            if tentativa == 0:
                self.page.wait_for_timeout(400)
        return (
            False,
            (ultimo_erro or "Plano não confirmado no portal.")
            + " Ajuste manualmente a velocidade antes de continuar ou repita a etapa do plano.",
        )

    def verificar_modal_erro_ops_visivel(self) -> bool:
        """Verifica se o modal 'OPS, OCORREU UM ERRO!' está visível na página (h2 ou div com esse texto)."""
        try:
            if not self.page:
                return False
            el = self.page.query_selector('h2:has-text("OPS, OCORREU UM ERRO")') or self.page.query_selector('h2:has-text("OPS, OCORREU UM ERRO!")')
            if el and el.is_visible():
                return True
            if "OPS, OCORREU UM ERRO" in (self.page.content() or ""):
                return True
            return False
        except Exception:
            return False

    # Títulos conhecidos que impedem avançar no PAP (viabilidade / cadastro / contato).
    _MODAIS_BLOQUEANTES = (
        ("Posse encontrada", "POSSE_ENCONTRADA"),
        ("Pedido encontrado", "PEDIDO_ENCONTRADO"),
        ("Indisponível", "INDISPONIVEL_TECNICO"),
        ("OPS, OCORREU UM ERRO", PAP_ERRO_PORTAL_NIO),
        ("OPS, OCORREU UM ERRO!", PAP_ERRO_PORTAL_NIO),
        ("Ocorreu um erro", "PAP_OCORREU_ERRO"),
    )

    @staticmethod
    def _formatar_linha_endereco(
        cep: str = "",
        numero: str = "",
        referencia: str = "",
        logradouro: str = "",
    ) -> str:
        """Monta linha legível do endereço consultado (sem dados sensíveis extras)."""
        partes: list[str] = []
        if logradouro:
            partes.append(str(logradouro).strip())
        if cep:
            cep_limpo = re.sub(r"\D", "", str(cep))
            partes.append(f"CEP {cep_limpo}")
        if numero:
            partes.append(f"nº {str(numero).strip()}")
        if referencia:
            partes.append(str(referencia).strip())
        return " · ".join(partes) if partes else "endereço informado"

    def _extrair_texto_ao_redor_titulo(self, titulo_el: Any) -> str:
        """Sobe no DOM a partir do título até achar o bloco do modal com o texto completo."""
        try:
            root = titulo_el.evaluate(
                """e => {
                  let n = e;
                  for (let i = 0; i < 14 && n; i++) {
                    if (n.getAttribute && n.getAttribute('role') === 'dialog') {
                      return (n.innerText || '').trim();
                    }
                    const cls = (n.className && String(n.className)) || '';
                    if (
                      cls.includes('modal') ||
                      cls.includes('Modal') ||
                      cls.includes('MuiDialog') ||
                      cls.includes('sc-')
                    ) {
                      const t = (n.innerText || '').trim();
                      if (t.length > 20 && t.length < 5000) return t;
                    }
                    n = n.parentElement;
                  }
                  return (e.parentElement && e.parentElement.innerText) || (e.innerText || '');
                }"""
            )
            return str(root or "").strip()[:2500]
        except Exception:
            try:
                return (titulo_el.inner_text() or "").strip()[:800]
            except Exception:
                return ""

    def _ler_modal_bloqueante_pap(self) -> Optional[Dict[str, str]]:
        """
        Detecta modal que impede avançar e extrai título + texto exibido ao usuário.

        Returns:
            dict com codigo, titulo, texto (corpo limpo) ou None.
        """
        if not self.page:
            return None
        for titulo, codigo in self._MODAIS_BLOQUEANTES:
            for tag in ("h1", "h2", "h3", "h4"):
                try:
                    el = self.page.query_selector(f'{tag}:has-text("{titulo}")')
                    if not el or not el.is_visible():
                        continue
                    bruto = self._extrair_texto_ao_redor_titulo(el)
                    linhas = [
                        ln.strip()
                        for ln in (bruto or "").splitlines()
                        if ln.strip()
                    ]
                    # Remove botões do rodapé do texto enviado ao usuário.
                    ignore = {
                        "consultar outro cpf/cnpj",
                        "consultar outro endereço",
                        "consultar outro endereco",
                        "salvar interesse",
                        "voltar",
                        "ok",
                        "tentar novamente",
                        "continuar",
                    }
                    corpo_linhas = [
                        ln
                        for ln in linhas
                        if ln.lower() not in ignore
                        and titulo.lower() not in ln.lower()
                    ]
                    corpo = "\n".join(corpo_linhas).strip()
                    return {
                        "codigo": codigo,
                        "titulo": titulo,
                        "texto": corpo or bruto or titulo,
                    }
                except Exception:
                    continue
        return None

    def _mensagem_usuario_modal_bloqueante(
        self,
        modal: Dict[str, str],
        *,
        etapa: str,
        cep: str = "",
        numero: str = "",
        referencia: str = "",
        logradouro: str = "",
    ) -> str:
        """Mensagem WhatsApp com o que o PAP mostrou e o contexto da etapa."""
        titulo = (modal.get("titulo") or "Atenção").strip()
        texto = (modal.get("texto") or "").strip()
        partes = [f"❌ *{titulo}*", ""]
        if texto:
            partes.append(texto)
            partes.append("")
        if etapa in ("endereco", "viabilidade", "etapa2"):
            endereco = self._formatar_linha_endereco(
                cep=cep,
                numero=numero,
                referencia=referencia,
                logradouro=logradouro,
            )
            partes.append(f"📍 *Endereço consultado:* {endereco}")
            partes.append("")
            partes.append(
                "Não foi possível concluir a viabilidade neste endereço."
            )
        elif etapa in ("contato", "cadastro", "etapa3", "etapa4"):
            partes.append(
                "Não foi possível avançar para a análise de crédito "
                "com este cliente."
            )
        else:
            partes.append("Não foi possível continuar no PAP.")
        return "\n".join(partes).strip()

    def _fechar_modal_erro_ops(self) -> bool:
        """
        Fecha o modal 'OPS, OCORREU UM ERRO!' clicando em 'Tentar novamente'.
        Usa vários seletores (texto, role, classes styled-components) e fallback via JS.
        Retorna True somente se o clique foi disparado; False se o modal não estava visível ou o botão não foi encontrado.
        """
        try:
            if not self.page:
                return False
            if not self.verificar_modal_erro_ops_visivel():
                return False
            clicked = False
            # 1) get_by_role (melhor para acessibilidade / texto variando)
            try:
                first = self.page.get_by_role("button", name=re.compile(r"tentar\s+novamente", re.I)).first
                if first.is_visible():
                    first.click(timeout=8000)
                    clicked = True
            except Exception as e_try:
                logger.debug("[PAP] _fechar_modal_erro_ops get_by_role: %s", e_try)
            # 2) Botão no mesmo bloco do h2 OPS (estrutura sc-gKLXLV / sc-* do PAP)
            if not clicked:
                try:
                    b = (
                        self.page.locator("div:has(h2:has-text('OPS'))")
                        .locator("button")
                        .filter(has_text=re.compile(r"tentar\s+novamente", re.I))
                        .first
                    )
                    if b.is_visible():
                        b.click(timeout=8000)
                        clicked = True
                except Exception as e_try:
                    logger.debug("[PAP] _fechar_modal_erro_ops escopo OPS: %s", e_try)
            # 3) :has-text clássico
            if not clicked:
                btn = self.page.query_selector('button:has-text("Tentar novamente")')
                if btn and btn.is_visible():
                    btn.click()
                    clicked = True
            # 4) Classe do botão (ex.: sc-hXhGGG eOQbpS no portal Nio)
            if not clicked:
                for sel in (
                    'button.sc-hXhGGG',
                    'button[class*="sc-hXhGGG"]',
                    'div.sc-gKLXLV button',
                    'div[class*="sc-gKLXLV"] button',
                ):
                    try:
                        cand = self.page.query_selector(sel)
                        if cand and cand.is_visible():
                            txt = (cand.inner_text() or "").strip().lower()
                            if "tentar" in txt and "novamente" in txt:
                                cand.click()
                                clicked = True
                                break
                    except Exception:
                        continue
            # 5) Fallback: qualquer button com o texto
            if not clicked:
                clicked = bool(
                    self.page.evaluate(
                        """
                        () => {
                          const btns = [...document.querySelectorAll('button')];
                          const b = btns.find(x => /tentar\\s*novamente/i.test((x.textContent || '').trim()));
                          if (b) { b.click(); return true; }
                          return false;
                        }
                        """
                    )
                )
            if clicked:
                self.page.wait_for_timeout(800 if not self.optimize_for_credit else 400)
                logger.warning("[PAP] Modal 'OPS, OCORREU UM ERRO!': clicado em 'Tentar novamente'.")
                return True
            logger.warning("[PAP] Modal OPS visível mas botão 'Tentar novamente' não encontrado.")
            return False
        except Exception as e:
            logger.warning("[PAP] _fechar_modal_erro_ops: %s", e)
            return False

    def _pap_detectar_texto_modal_visivel(self) -> str:
        """Texto agregado de diálogos/modais visíveis (MUI e genéricos)."""
        partes = []
        try:
            for sel in ('[role="dialog"]', '.MuiDialog-root', '[class*="Dialog"]'):
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    t = (el.inner_text() or "").strip()
                    if t and len(t) > 2:
                        partes.append(t[:1200])
        except Exception:
            pass
        return "\n".join(partes)

    def _pap_modal_erro_aparente(self, texto: str) -> bool:
        if not texto:
            return False
        low = texto.lower()
        if "nenhum erro" in low or "sem erro" in low or "0 erro" in low:
            return False
        markers = (
            "error",
            "erro",
            "falha",
            "não foi possível",
            "nao foi possivel",
            "tente novamente",
            "ops,",
            "ocorreu um erro",
        )
        return any(m in low for m in markers)

    def _pap_fechar_dialogos_erro_conhecidos(self) -> Tuple[bool, str]:
        """
        Fecha modais de erro genéricos (título/corpo com error, erro, falha).
        Retorna (fechou_algum, trecho_do_texto_visto).
        """
        texto_antes = self._pap_detectar_texto_modal_visivel()
        fechou = False
        try:
            for btn_txt in (
                "OK",
                "Ok",
                "Entendi",
                "Fechar",
                "Fechar dialog",
                "Tentar novamente",
                "Continuar",
            ):
                btn = self.page.query_selector(
                    f'[role="dialog"] button:has-text("{btn_txt}"), '
                    f'.MuiDialog-root button:has-text("{btn_txt}")'
                )
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(500)
                    fechou = True
                    break
            if not fechou:
                xbtn = self.page.query_selector(
                    '[role="dialog"] button[aria-label="Close"], '
                    '.MuiDialog-root button[aria-label="Close"]'
                )
                if xbtn and xbtn.is_visible():
                    xbtn.click()
                    self.page.wait_for_timeout(500)
                    fechou = True
        except Exception as e:
            logger.debug("[PAP] _pap_fechar_dialogos_erro_conhecidos: %s", e)
        return fechou, (texto_antes or "")[:400]

    def _pap_modal_titulo_ocorreu_erro_visivel(self) -> bool:
        """True se h2/h3 'Ocorreu um erro' estiver visível (portal Nio usa h2 em vários builds)."""
        try:
            if not self.page:
                return False
            for sel in (
                'h2:has-text("Ocorreu um erro")',
                'h3:has-text("Ocorreu um erro")',
            ):
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return True
            return "Ocorreu um erro" in (self.page.content() or "")
        except Exception:
            return False

    def _pap_extrair_texto_modal_proximo_a_titulo_erro(self) -> str:
        """Texto do bloco do modal (para decidir se é erro ao abrir pedido/OS)."""
        try:
            for sel in ('h2:has-text("Ocorreu um erro")', 'h3:has-text("Ocorreu um erro")'):
                el = self.page.query_selector(sel)
                if not el or not el.is_visible():
                    continue
                try:
                    root = el.evaluate(
                        """e => {
                          let n = e;
                          for (let i = 0; i < 12 && n; i++) {
                            if (n.getAttribute && n.getAttribute('role') === 'dialog') return n.innerText || '';
                            const cls = (n.className && String(n.className)) || '';
                            if (cls.includes('modal') || cls.includes('Modal') || cls.includes('sc-')) {
                              const t = (n.innerText || '').trim();
                              if (t.length > 20 && t.length < 4000) return t;
                            }
                            n = n.parentElement;
                          }
                          return (e.closest('div') || e).innerText || '';
                        }"""
                    )
                    if root and len(str(root).strip()) > 5:
                        return str(root).strip()[:2000]
                except Exception:
                    pass
                try:
                    return (el.evaluate("e => (e.closest('div') || e).innerText || ''") or "")[:2000]
                except Exception:
                    return (el.inner_text() or "")[:800]
        except Exception:
            pass
        return ""

    def _pap_fechar_modal_ocorreu_erro_h3_ok(self) -> bool:
        """
        Fecha modal 'Ocorreu um erro' (h2 ou h3) clicando em Ok.
        O PAP costuma usar styled-components (ex.: div.sc-*) sem role=\"dialog\" — por isso vários fallbacks.
        """
        try:
            if not self.page:
                return False
            if not self._pap_modal_titulo_ocorreu_erro_visivel():
                return False
            clicked = False
            try:
                box = self.page.locator(
                    "div:has(h2:has-text('Ocorreu um erro')), div:has(h3:has-text('Ocorreu um erro'))"
                ).first
                if box.is_visible():
                    for label in ("Ok", "OK"):
                        try:
                            b = box.locator(f"button:has-text('{label}')").first
                            if b.is_visible():
                                b.click(timeout=5000)
                                clicked = True
                                break
                        except Exception:
                            continue
            except Exception as e_try:
                logger.debug("[PAP] fechar modal ocorreu erro (box): %s", e_try)
            if not clicked:
                for sel in (
                    '[role="dialog"] button:has-text("Ok")',
                    '[role="dialog"] button:has-text("OK")',
                    '.MuiDialog-root button:has-text("Ok")',
                    'button:has-text("Ok")',
                    'button:has-text("OK")',
                ):
                    try:
                        btn = self.page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue
            if not clicked:
                clicked = bool(
                    self.page.evaluate(
                        """
                        () => {
                          const heads = [...document.querySelectorAll('h2, h3')];
                          const h = heads.find(el => /ocorreu\\s+um\\s+erro/i.test((el.textContent || '').trim()));
                          if (!h) return false;
                          let root = h.closest('[role="dialog"]') || h.parentElement;
                          for (let depth = 0; depth < 14 && root; depth++) {
                            const btns = [...root.querySelectorAll('button')];
                            const okb = btns.find(b => /^ok$/i.test((b.textContent || '').trim()));
                            if (okb && okb.offsetParent !== null) { okb.click(); return true; }
                            root = root.parentElement;
                          }
                          const vis = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
                          const greenOk = vis.find(b => /^ok$/i.test((b.textContent || '').trim()));
                          if (greenOk) { greenOk.click(); return true; }
                          return false;
                        }
                        """
                    )
                )
            if clicked:
                self.page.wait_for_timeout(600)
                logger.warning("[PAP] Modal 'Ocorreu um erro' fechado (Ok).")
                return True
            self._pap_fechar_dialogos_erro_conhecidos()
            return False
        except Exception as e:
            logger.debug("[PAP] _pap_fechar_modal_ocorreu_erro_h3_ok: %s", e)
            return False

    def detectar_tela_etapa1_identificacao_pdv(self) -> bool:
        """True se o fluxo voltou à identificação PDV (Etapa 1 / matrícula vendedor)."""
        try:
            if not self.page:
                return False
            span = self.page.locator('span:has-text("Etapa 1")').first
            if not span.is_visible():
                return False
            mi = self._query_matricula_vendedor_input()
            return bool(mi and mi.is_visible())
        except Exception:
            return False

    def _pap_merge_dados_sessao_para_replay(self, dados_sessao: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Une dados da sessão WhatsApp com dados_pedido já preenchidos na automação (replay após reset)."""
        out: Dict[str, Any] = {}
        try:
            out.update(self.dados_pedido or {})
        except Exception:
            pass
        if dados_sessao:
            out.update(dados_sessao)
        return out

    def _pap_replay_viabilidade_com_dados(self, d: Dict[str, Any]) -> Tuple[bool, str, Any]:
        """
        Refaz consulta de viabilidade e ramificações (múltiplos endereços / complementos) usando dados salvos.
        Retorno extra: None=disponível e Continuar aplicado; dict MULTIPLOS/COMPLEMENTOS=parado na escolha;
        POSSE_ENCONTRADA / INDISPONIVEL_TECNICO = erro.
        """
        cep = (d.get("cep") or "").strip()
        numero = d.get("numero", "")
        ref = (d.get("referencia") or "").strip()
        if not cep or numero is None or numero == "" or not ref:
            return False, "Dados de endereço incompletos para recuperação automática.", None
        numero_s = str(numero).strip()
        sucesso, msg, extra = self.etapa2_viabilidade(cep, numero_s, ref)
        if isinstance(extra, dict) and extra.get("_codigo") == "MULTIPLOS_ENDERECOS":
            idx = d.get("pap_replay_endereco_idx")
            if idx is None or str(idx).strip() == "":
                return True, "", extra
            try:
                idx_i = int(idx)
            except (TypeError, ValueError):
                return False, "Índice de endereço salvo inválido para replay.", None
            ok_sel, msg_sel = self.etapa2_selecionar_endereco_instalacao(idx_i)
            if not ok_sel:
                return False, msg_sel or "Replay endereço", None
            sucesso2, msg2, extra2 = self.etapa2_preencher_referencia_e_continuar(cep, numero_s, ref)
            return self._pap_replay_resolve_pos_referencia(cep, numero_s, ref, sucesso2, msg2, extra2, d)
        if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
            return self._pap_replay_complemento_ou_avancar(cep, numero_s, ref, d, extra)
        if extra in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return False, msg, extra
        if sucesso:
            return True, msg or "", None
        if msg == PAP_ERRO_PORTAL_NIO:
            return False, msg, None
        return False, msg or "Viabilidade", None

    def _pap_replay_resolve_pos_referencia(
        self,
        cep: str,
        numero_s: str,
        ref: str,
        sucesso2: bool,
        msg2: str,
        extra2: Any,
        d: Dict[str, Any],
    ) -> Tuple[bool, str, Any]:
        if isinstance(extra2, dict) and extra2.get("_codigo") == "COMPLEMENTOS":
            return self._pap_replay_complemento_ou_avancar(cep, numero_s, ref, d, extra2)
        if extra2 in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return False, msg2, extra2
        if sucesso2:
            return True, msg2 or "", None
        if msg2 == PAP_ERRO_PORTAL_NIO:
            return False, msg2, None
        return False, msg2 or "Referência/viabilidade", None

    def _pap_replay_complemento_ou_avancar(
        self, cep: str, numero_s: str, ref: str, d: Dict[str, Any], extra_comp: dict
    ) -> Tuple[bool, str, Any]:
        esc = (d.get("pap_replay_complemento_escolha") or "").strip()
        if not esc:
            return True, "", extra_comp
        esc_up = esc.upper()
        if esc_up in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
            ok_c, msg_c = self.etapa2_selecionar_sem_complemento()
        elif esc.isdigit():
            ok_c, msg_c = self.etapa2_selecionar_complemento(int(esc))
        else:
            return False, "Complemento salvo inválido para replay.", None
        if not ok_c:
            return False, msg_c or "Replay complemento", None
        sucesso3, msg3, extra3 = self.etapa2_clicar_avancar_apos_complemento(cep, numero_s)
        if extra3 in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return False, msg3, extra3
        if sucesso3:
            return True, msg3 or "", None
        if msg3 == PAP_ERRO_PORTAL_NIO:
            return False, msg3, None
        return False, msg3 or "Avançar pós-complemento", None

    def _pap_replay_target_sn_para_etapa(self, etapa_whatsapp: str) -> int:
        if not etapa_whatsapp:
            return 0
        if etapa_whatsapp in WPP_ETAPA_REPLAY_TARGET_SN:
            return WPP_ETAPA_REPLAY_TARGET_SN[etapa_whatsapp]
        if etapa_whatsapp.startswith("venda_") and etapa_whatsapp not in (
            "venda_erro_retry",
            "venda_aguardando_pap",
            "venda_confirmar_matricula",
        ):
            return 9
        return 0

    def _pap_executar_replay_ate_target_sn(
        self, d: Dict[str, Any], matricula_vendedor: str, target_sn: int
    ) -> Tuple[bool, str]:
        """Executa subpassos 0..target_sn para alinhar o PAP com a sessão WhatsApp."""
        if target_sn < 0:
            return True, ""
        ok, msg = self.iniciar_novo_pedido(matricula_vendedor)
        if not ok:
            return False, msg
        if target_sn < 1:
            return True, ""
        v_ok, v_msg, v_extra = self._pap_replay_viabilidade_com_dados(d)
        if not v_ok:
            return False, v_msg or "Replay viabilidade"
        if isinstance(v_extra, dict) and v_extra.get("_codigo") in ("MULTIPLOS_ENDERECOS", "COMPLEMENTOS"):
            if target_sn <= 1:
                return True, ""
            return False, "Faltam pap_replay_endereco_idx ou pap_replay_complemento_escolha para concluir o replay."
        if target_sn < 2:
            return True, ""
        cpf = re.sub(r"\D", "", (d.get("cpf_cliente") or ""))
        if len(cpf) < 11:
            return False, "CPF do cliente ausente nos dados salvos."
        ok3, msg3, _ = self.etapa3_cadastro_cliente(cpf)
        if not ok3:
            return False, msg3 or "Replay etapa 3"
        if target_sn < 3:
            return True, ""
        cel = re.sub(r"\D", "", (d.get("celular") or ""))
        email = (d.get("email") or "").strip()
        if not cel or not email:
            return False, "Celular ou e-mail ausente nos dados salvos."
        cel_sec = d.get("celular_sec") or None
        if cel_sec:
            cel_sec = re.sub(r"\D", "", str(cel_sec)) or None
        ok4, msg4, _, _ = self.etapa4_contato(cel, email, celular_secundario=cel_sec, parar_no_modal_credito=False)
        if not ok4:
            if msg4 == PAP_ERRO_PORTAL_NIO:
                return False, msg4
            return False, msg4 or "Replay contato"
        if target_sn < 4:
            return True, ""
        forma = (d.get("forma_pagamento") or "").strip().lower()
        if forma not in ("boleto", "cartao", "debito"):
            return False, "Forma de pagamento ausente ou inválida nos dados salvos."
        okf, msgf = self.etapa5_selecionar_forma_pagamento(forma)
        if not okf:
            return False, msgf or "Replay forma pagamento"
        if target_sn < 5:
            return True, ""
        if forma == "debito":
            banco = (d.get("banco") or d.get("banco_dacc") or "").strip()
            agencia = (d.get("agencia") or d.get("agencia_dacc") or "").strip()
            conta = (d.get("conta") or d.get("conta_dacc") or "").strip()
            digito = (d.get("digito") or d.get("digito_dacc") or "").strip()
            if not (banco and agencia and conta and digito):
                return False, "Dados de débito em conta incompletos nos dados salvos."
            okd, msgd = self.etapa5_preencher_debito(banco, agencia, conta, digito)
            if not okd:
                return False, msgd or "Replay débito"
        if target_sn < 6:
            return True, ""
        plano = (d.get("plano") or "").strip().lower()
        if plano not in ("1giga", "700mega", "500mega"):
            return False, "Plano ausente nos dados salvos."
        okp, msgp = self.etapa5_selecionar_plano_com_validacao(plano)
        if not okp:
            return False, msgp or "Replay plano"
        if target_sn < 7:
            return True, ""
        tem_fixo = bool(d.get("tem_fixo"))
        okfx, msgfx = self.etapa5_selecionar_fixo(tem_fixo)
        if not okfx:
            return False, msgfx or "Replay fixo"
        if target_sn < 8:
            return True, ""
        if tem_fixo:
            quer = bool(d.get("fixo_portabilidade"))
            num_p = (d.get("fixo_portabilidade_numero") or "").strip()
            op_p = (d.get("fixo_portabilidade_operadora") or "").strip()
            okpb, msgpb = self.etapa5_fixo_finalizar_portabilidade(quer, num_p, op_p)
            if not okpb:
                return False, msgpb or "Replay portabilidade fixo"
        if target_sn < 9:
            return True, ""
        tem_st = bool(d.get("tem_streaming"))
        sop = (d.get("streaming_opcoes") or "").strip()
        oks, msgs = self.etapa5_selecionar_streaming(tem_st, sop, plano)
        if not oks:
            return False, msgs or "Replay streaming"
        oka, msga = self.etapa5_clicar_avancar()
        if not oka:
            return False, msga or "Replay avançar pós-ofertas"
        return True, ""

    def tentar_recuperar_portal_reset_etapa1(
        self,
        dados_sessao: Optional[Dict[str, Any]],
        matricula_vendedor: str,
        etapa_whatsapp: str,
    ) -> Tuple[bool, str]:
        """
        Detecta modal 'Ocorreu um erro' e/ou retorno à Etapa 1 e reaplica o fluxo com dados salvos.
        Retorna (True, "") se não havia reset ou a recuperação foi ok; (False, msg) em falha.
        """
        if not self.page or not matricula_vendedor:
            return True, ""
        try:
            self._pap_fechar_modal_ocorreu_erro_h3_ok()
            self._fechar_modal_erro_ops()
            if self._pap_modal_erro_aparente(self._pap_detectar_texto_modal_visivel()):
                self._pap_fechar_dialogos_erro_conhecidos()
                self.page.wait_for_timeout(400)
        except Exception as e:
            logger.debug("[PAP] tentar_recuperar: fechar modais: %s", e)
        if not self.detectar_tela_etapa1_identificacao_pdv():
            return True, ""
        if not etapa_whatsapp or etapa_whatsapp in (
            "inicial",
            "venda_aguardando_pap",
            "venda_confirmar_matricula",
            "venda_erro_retry",
        ):
            return True, ""
        d = self._pap_merge_dados_sessao_para_replay(dados_sessao)
        target = self._pap_replay_target_sn_para_etapa(etapa_whatsapp)
        logger.warning(
            "[PAP] Reset para Etapa 1 detectado — reaplicando fluxo até sn=%s (etapa_wpp=%s).",
            target,
            etapa_whatsapp,
        )
        ok, msg = self._pap_executar_replay_ate_target_sn(d, matricula_vendedor, target)
        if ok:
            return True, ""
        return False, msg or "Falha ao reaplicar dados após reset do portal."

    def _pap_tratar_modais_apos_acao_pap(self) -> Tuple[bool, str]:
        """
        Após cliques (Consultar Biometria, Abrir OS): OPS do portal + diálogos com 'error'/erro.
        Trata também o modal h2/h3 'Ocorreu um erro' (sem role=dialog), comum após Abrir OS falhar.
        Retorna (pode_continuar, mensagem_erro_ou_vazia). Se pode_continuar False, houve erro explícito.
        """
        try:
            self._fechar_modal_erro_ops()
            self.page.wait_for_timeout(400)
            if self._pap_modal_titulo_ocorreu_erro_visivel():
                trecho_modal = self._pap_extrair_texto_modal_proximo_a_titulo_erro()
                self._pap_fechar_modal_ocorreu_erro_h3_ok()
                self.page.wait_for_timeout(400)
                low = (trecho_modal or "").lower()
                if (
                    "não foi possível abrir o pedido" in low
                    or "nao foi possivel abrir o pedido" in low
                    or "abrir o pedido" in low
                ):
                    return (
                        False,
                        "O portal não conseguiu abrir o pedido/OS. "
                        "A mensagem pede para tentar mais tarde; em geral o fluxo volta à Etapa 1. "
                        "Abra chamado na Nio se necessário ou inicie nova venda.",
                    )
                return False, (trecho_modal.strip()[:500] if trecho_modal else "O portal exibiu 'Ocorreu um erro'.")
            txt = self._pap_detectar_texto_modal_visivel()
            if self._pap_modal_erro_aparente(txt):
                self._pap_fechar_dialogos_erro_conhecidos()
                logger.warning("[PAP] Modal de erro detectado após ação: %s", txt[:200])
                return False, txt.strip()[:500]
            return True, ""
        except Exception as e:
            logger.debug("[PAP] _pap_tratar_modais_apos_acao_pap: %s", e)
            return True, ""

    def pap_inspecionar_contexto_etapa(self) -> Dict[str, Any]:
        """
        Indica onde o fluxo parece estar (para recuperação e logs após timeout/erro).
        """
        out: Dict[str, Any] = {
            "url": "",
            "provavel": "desconhecido",
            "tem_abrir_os": False,
            "tem_consultar_biometria": False,
            "tem_periodo_agendamento": False,
            "trecho_modal": "",
        }
        try:
            out["url"] = self.page.url or ""
            u = out["url"].lower()
            if "novo-pedido" in u and "administrativo" in u:
                out["provavel"] = "fluxo_pedido"
            btn_os = self.page.query_selector(
                'button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])'
            )
            out["tem_abrir_os"] = bool(btn_os and btn_os.is_visible())
            btn_cb = self.page.query_selector('button:has-text("Consultar Biometria")')
            out["tem_consultar_biometria"] = bool(btn_cb and btn_cb.is_visible())
            per = self.page.query_selector(
                'h3:has-text("Período"), [class*="react-datepicker"], h2:has-text("Agendamento"), h3:has-text("Agendamento")'
            )
            out["tem_periodo_agendamento"] = bool(per and per.is_visible())
            out["trecho_modal"] = self._pap_detectar_texto_modal_visivel()[:300]
            if out["tem_periodo_agendamento"]:
                out["provavel"] = "agendamento"
            elif out["tem_abrir_os"] or out["tem_consultar_biometria"]:
                out["provavel"] = "resumo_biometria"
        except Exception as e:
            logger.debug("[PAP] pap_inspecionar_contexto_etapa: %s", e)
        return out

    def _etapa5_bloquear_backdrop_drawer_mui(self) -> None:
        """
        O PAP usa drawer/modal MUI: clique na área escura (backdrop) fecha o painel e
        interrompe o fluxo antes do Salvar. Desabilita pointer-events no backdrop.
        """
        try:
            self.page.evaluate(
                """
                () => {
                  document.querySelectorAll(
                    '.MuiBackdrop-root, .MuiModal-backdrop, [class*="MuiBackdrop-root"]'
                  ).forEach((el) => {
                    if (el instanceof HTMLElement) {
                      if (el.dataset.papBackdropPe === undefined) {
                        el.dataset.papBackdropPe = el.style.pointerEvents || '';
                      }
                      el.style.pointerEvents = 'none';
                    }
                  });
                }
                """
            )
        except Exception as ex:
            logger.debug("[PAP] _etapa5_bloquear_backdrop_drawer_mui: %s", ex)

    def _etapa5_restaurar_backdrop_drawer_mui(self) -> None:
        """Restaura o backdrop após concluir o painel (opcional; ao fechar o drawer o nó some)."""
        try:
            self.page.evaluate(
                """
                () => {
                  document.querySelectorAll(
                    '.MuiBackdrop-root, .MuiModal-backdrop, [class*="MuiBackdrop-root"]'
                  ).forEach((el) => {
                    if (!(el instanceof HTMLElement)) return;
                    const prev = el.dataset.papBackdropPe;
                    if (prev !== undefined) {
                      el.style.pointerEvents = prev;
                      delete el.dataset.papBackdropPe;
                    }
                  });
                }
                """
            )
        except Exception:
            pass

    def _etapa5_drawer_titulo_servicos_visivel(self) -> bool:
        """True se o painel lateral de serviços adicionais está aberto (título visível)."""
        try:
            t = self.page.get_by_text("Escolher serviços adicionais", exact=False).first
            return t.is_visible()
        except Exception:
            return False

    def _etapa5_ui_fixo_portabilidade_visivel(self) -> bool:
        """True se já dá para preencher portabilidade ou clicar Salvar no fluxo Fixo."""
        try:
            if self.page.locator("#contatoPortabilidade").count() > 0:
                if self.page.locator("#contatoPortabilidade").first.is_visible():
                    return True
            if self.page.locator('select[name="operadora"]').count() > 0:
                if self.page.locator('select[name="operadora"]').first.is_visible():
                    return True
            if self.page.locator('label:has-text("Cliente deseja fazer portabilidade")').count() > 0:
                if self.page.locator('label:has-text("Cliente deseja fazer portabilidade")').first.is_visible():
                    return True
            loc = self.page.locator("button.sc-guDjWT.gIsNuI").filter(has_text="Salvar")
            if loc.count() > 0 and loc.first.is_visible():
                return True
            loc2 = self.page.get_by_role("button", name=re.compile(r"^\s*Salvar\s*$", re.I))
            if loc2.count() > 0:
                for i in range(loc2.count()):
                    b = loc2.nth(i)
                    if b.is_visible() and (b.inner_text() or "").strip() == "Salvar":
                        return True
        except Exception:
            pass
        return False

    def _etapa5_fixo_servico_marcado_no_drawer(self) -> bool:
        """True se o add-on Fixo já foi selecionado (checkbox / aria-checked no card)."""
        try:
            try:
                ac = self.page.locator('div:has-text("Fixo") [aria-checked="true"]')
                if ac.count() > 0 and ac.first.is_visible():
                    return True
            except Exception:
                pass
            for sel in (
                'div:has-text("Fixo") input[type="checkbox"]',
                'div:has-text("Faça ligações") input[type="checkbox"]',
            ):
                inp = self.page.locator(sel).first
                if inp.count() == 0:
                    continue
                try:
                    if inp.is_checked():
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _etapa5_drawer_fixo_pronto(self) -> bool:
        """Portabilidade/Salvar visível OU Fixo já marcado (o site só mostra a próxima etapa depois)."""
        return self._etapa5_ui_fixo_portabilidade_visivel() or self._etapa5_fixo_servico_marcado_no_drawer()

    def _etapa5_scroll_painel_lateral_ate_rodape(self) -> None:
        """Garante scroll até o rodapé do drawer (Salvar fica embaixo)."""
        try:
            self.page.evaluate(
                """
                () => {
                  const salvarBtn = [...document.querySelectorAll('button.sc-guDjWT.gIsNuI')].find(
                    b => (b.textContent || '').trim() === 'Salvar'
                  ) || [...document.querySelectorAll('button')].find(
                    b => (b.textContent || '').trim() === 'Salvar'
                  );
                  const alvo =
                    salvarBtn ||
                    document.querySelector('#contatoPortabilidade') ||
                    document.querySelector('select[name="operadora"]');
                  if (!alvo) return;
                  let p = alvo;
                  for (let i = 0; i < 22 && p; i++) {
                    const st = window.getComputedStyle(p);
                    if (p.scrollHeight > p.clientHeight + 2 || /auto|scroll/.test(st.overflowY || '')) {
                      try { p.scrollTop = p.scrollHeight; } catch (e) {}
                    }
                    p = p.parentElement;
                  }
                }
                """
            )
            self.page.wait_for_timeout(200)
        except Exception:
            pass

    def _etapa5_drawer_streaming_titulo_visivel(self) -> bool:
        try:
            t = self.page.get_by_text("Escolher plataformas", exact=False).first
            return t.is_visible()
        except Exception:
            return False

    def _etapa5_locator_drawer_streaming(self):
        """Container do drawer lateral de streaming (título Escolher plataformas…)."""
        try:
            for sel in (
                'aside:has-text("Escolher plataformas")',
                'div:has-text("Escolher plataformas de streaming")',
            ):
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    c = loc.first
                    if c.is_visible():
                        return c
        except Exception:
            pass
        return None

    def _etapa5_scroll_drawer_streaming_ate_salvar(self) -> None:
        """Scroll no drawer de streaming: cards + botão Salvar ficam em áreas roláveis separadas."""
        try:
            self.page.evaluate(
                """
                () => {
                  const titulo = [...document.querySelectorAll('div, aside, header, section')].find(
                    el => (el.textContent || '').includes('Escolher plataformas')
                  );
                  let n = titulo;
                  for (let i = 0; i < 24 && n; i++) {
                    if (n.scrollHeight > n.clientHeight + 2) {
                      try { n.scrollTop = n.scrollHeight; } catch (e) {}
                    }
                    n = n.parentElement;
                  }
                  document.querySelectorAll(
                    '.MuiDrawer-paper, aside, [class*="Drawer-paper"], [class*="sc-kqEXUp"]'
                  ).forEach(el => {
                    try { el.scrollTop = el.scrollHeight; } catch (e) {}
                  });
                  const b = [...document.querySelectorAll('button.sc-guDjWT.gIsNuI')].find(
                    x => (x.textContent || '').trim() === 'Salvar' &&
                      (x.closest('aside') || x.closest('[class*="Drawer"]') || x.closest('div'))
                  );
                  if (b) {
                    try { b.scrollIntoView({ block: 'end', inline: 'nearest' }); } catch (e) {}
                  }
                }
                """
            )
            self.page.wait_for_timeout(280)
        except Exception:
            pass

    def _etapa5_streaming_map_opcao_para_preco(self, o: str, skip_padrao: bool) -> Optional[str]:
        o = (o or "").lower()
        if "hbomax" in o or o == "hbo":
            return "44,90"
        if "globoplay_premium" in o or (
            "premium" in o and "basico" not in o and "padrao" not in o and "padrão" not in o
        ):
            return "39,90"
        if ("globoplay_basico" in o or "basico" in o or "padrão" in o or "padrao" in o) and not skip_padrao:
            return "22,90"
        return None

    def _etapa5_clicar_preco_streaming(self, preco: str) -> bool:
        """Clica no preço (div.sc-hQfrgq.frojRS) correspondente, ex.: R$ 44,90."""
        dr = self._etapa5_locator_drawer_streaming()
        roots = []
        if dr is not None:
            roots.append(dr)
        roots.append(self.page.locator("body"))
        for root in roots:
            for sel in (
                f'div.sc-hQfrgq.frojRS:has-text("{preco}")',
                f'div.frojRS:has-text("{preco}")',
                f'div:has-text("R$ {preco}")',
            ):
                try:
                    el = root.locator(sel).first
                    if el.is_visible():
                        el.scroll_into_view_if_needed()
                        el.click(timeout=8000)
                        self.page.wait_for_timeout(400)
                        return True
                except Exception:
                    continue
        try:
            ok = self.page.evaluate(
                """(preco) => {
                  const nodes = [...document.querySelectorAll('div.sc-hQfrgq.frojRS, div.frojRS')];
                  const el = nodes.find(n => (n.innerText || '').includes(preco));
                  if (!el) return false;
                  el.click();
                  return true;
                }""",
                preco,
            )
            self.page.wait_for_timeout(400)
            return bool(ok)
        except Exception:
            return False

    def _etapa5_streaming_preco_parece_selecionado(self, preco: str) -> bool:
        """Verifica input/aria-checked/Mui-checked na linha do card que contém o preço."""
        try:
            return bool(
                self.page.evaluate(
                    """(preco) => {
                  const nodes = [...document.querySelectorAll('div.sc-hQfrgq.frojRS, div.frojRS')];
                  const priceEl = nodes.find(n => (n.innerText || '').includes(preco));
                  if (!priceEl) return false;
                  let card = priceEl;
                  for (let i = 0; i < 16 && card; i++) {
                    const inp = card.querySelector(
                      'input[type="checkbox"]:checked, input[type="radio"]:checked'
                    );
                    if (inp) return true;
                    const ac = card.querySelector('[aria-checked="true"]');
                    if (ac) return true;
                    if (card.querySelector('.Mui-checked, [class*="Mui-checked"], [class*="MuiSwitch"]')) {
                      return true;
                    }
                    card = card.parentElement;
                  }
                  return false;
                }""",
                    preco,
                )
            )
        except Exception:
            return False

    def _etapa5_clicar_servicos_disponiveis(self) -> bool:
        """Abre o drawer clicando apenas no botão 'Serviços disponíveis'."""
        try:
            loc_btn = self.page.get_by_role(
                "button", name=re.compile(r"Serviços\s*disponíveis", re.I)
            )
            if loc_btn.count() > 0:
                b0 = loc_btn.first
                if b0.is_visible():
                    b0.scroll_into_view_if_needed()
                    b0.click(timeout=8000)
                    return True
            el = self.page.query_selector(SELETORES["etapa5"]["btn_servicos"])
            if not el:
                el = self.page.query_selector('button.sc-izfUZz:has-text("Serviços disponíveis")')
            if not el:
                el = self.page.query_selector('button.fVoKDo:has-text("Serviços disponíveis")')
            if not el or not el.is_visible():
                return False
            el.scroll_into_view_if_needed()
            el.click()
            return True
        except Exception:
            return False

    def _etapa5_clicar_opcao_fixo_no_drawer(self) -> bool:
        """
        Marca o serviço Fixo. No PAP atual: preço R$ 30,00 em div.sc-hQfrgq.frojRS ou checkbox/img no card.
        """
        drawer = self._etapa5_locator_drawer_paper_visivel()
        scopes = []
        if drawer is not None:
            scopes.append(drawer)
        scopes.append(self.page.locator("body"))

        for scope in scopes:
            for sel in [
                "div.sc-hQfrgq.frojRS",
                'div.frojRS:has-text("30,00")',
                'div:has-text("R$ 30,00")',
                'div:has-text("Fixo") input[type="checkbox"]',
                'div:has-text("Faça ligações") input[type="checkbox"]',
                'div:has-text("Fixo") img[src^="data:image/png"]',
                'div:has-text("Fixo") img[src^="data:image"]',
                'div:has-text("Fixo"):has-text("30,00") img',
                'div:has-text("Fixo"):has-text("R$ 30") img',
                'div:has-text("Fixo") img',
                'div.sc-kUQWMX.bwZXDo:has-text("Fixo") img',
                'div.bwZXDo:has-text("Fixo") img',
                'div:has-text("Fixo"):has-text("Faça ligações") img',
                'div.sc-kUQWMX.bwZXDo:has-text("Fixo")',
                'div.bwZXDo:has-text("Fixo")',
                'div.sc-dcmekm.dBGnOE:has-text("Fixo")',
                SELETORES["etapa5"]["card_fixo"],
                'div:has-text("Fixo"):has-text("Faça ligações")',
                'div:has-text("Fixo"):has-text("R$ 30,00")',
                'div:has-text("Fixo"):has-text("R$ 30")',
            ]:
                try:
                    el = scope.locator(sel).first
                    if el.is_visible():
                        el.scroll_into_view_if_needed()
                        el.click(timeout=8000)
                        self.page.wait_for_timeout(550)
                        if self._etapa5_fixo_servico_marcado_no_drawer() or self._etapa5_drawer_fixo_pronto():
                            return True
                except Exception:
                    continue

        try:
            clicked = self.page.evaluate(
                r"""
                () => {
                  const precisaFixo30 = (txt) =>
                    /R\$\s*30\s*[,.]\s*00/i.test(txt || '') ||
                    /^[\s]*30\s*[,.]\s*00[\s]*$/i.test((txt || '').trim());
                  const prices = document.querySelectorAll('div.sc-hQfrgq.frojRS, div.frojRS');
                  for (const price of prices) {
                    const raw = price.innerText || '';
                    if (!precisaFixo30(raw)) continue;
                    let el = price;
                    for (let i = 0; i < 14 && el; i++) {
                      const block = el.textContent || '';
                      if (block.includes('Fixo')) {
                        price.click();
                        return 'price';
                      }
                      el = el.parentElement;
                    }
                  }
                  const cards = document.querySelectorAll('div');
                  for (const card of cards) {
                    const t = card.textContent || '';
                    if (!t.includes('Fixo')) continue;
                    if (!/R\$\s*30\s*[,.]\s*00/i.test(t)) continue;
                    const cb = card.querySelector('input[type="checkbox"]');
                    if (cb) { cb.click(); return 'checkbox'; }
                    const im = card.querySelector('img[src^="data:image"]');
                    if (im) { im.click(); return 'img'; }
                    const pr = card.querySelector('div.frojRS, div.sc-hQfrgq');
                    if (pr) {
                      const pt = pr.innerText || '';
                      if (precisaFixo30(pt)) { pr.click(); return 'frojRS'; }
                    }
                  }
                  return '';
                }
                """
            )
            self.page.wait_for_timeout(700)
            if clicked and (
                self._etapa5_fixo_servico_marcado_no_drawer() or self._etapa5_drawer_fixo_pronto()
            ):
                logger.info("[PAP] Clique Fixo via JS (%s)", clicked)
                return True
        except Exception as ex:
            logger.debug("[PAP] clique Fixo evaluate: %s", ex)
        return False

    def _etapa5_garantir_drawer_fixo_para_portabilidade(self, max_ciclos: int = 3) -> Tuple[bool, str]:
        """
        Garante que o drawer 'Escolher serviços adicionais' está aberto e o painel Fixo
        (portabilidade / Salvar) está acessível — reabre e remarca Fixo se necessário.
        """
        for ciclo in range(max_ciclos):
            self._etapa5_bloquear_backdrop_drawer_mui()
            if self._etapa5_drawer_titulo_servicos_visivel() and self._etapa5_drawer_fixo_pronto():
                logger.info("[PAP] Drawer Fixo/Portabilidade OK (ciclo %s)", ciclo + 1)
                return True, ""
            logger.warning(
                "[PAP] Drawer Fixo incompleto; reabrindo (ciclo %s/%s)",
                ciclo + 1,
                max_ciclos,
            )
            if not self._etapa5_drawer_titulo_servicos_visivel():
                if not self._etapa5_clicar_servicos_disponiveis():
                    self._etapa5_restaurar_backdrop_drawer_mui()
                    return False, "Não foi possível clicar em 'Serviços disponíveis' para reabrir o painel."
                try:
                    self.page.wait_for_selector(
                        'text=Escolher serviços adicionais', timeout=15000
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(400)
                self._etapa5_bloquear_backdrop_drawer_mui()
            if not self._etapa5_clicar_opcao_fixo_no_drawer():
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Não foi possível marcar a opção Fixo no painel."
            self.page.wait_for_timeout(700)
            self._etapa5_bloquear_backdrop_drawer_mui()
            if self._etapa5_drawer_fixo_pronto():
                logger.info("[PAP] Fixo marcado ou portabilidade visível (ciclo %s)", ciclo + 1)
                return True, ""

        if self._etapa5_drawer_fixo_pronto():
            return True, ""
        return False, "Painel Fixo/portabilidade não ficou disponível após várias tentativas."

    def _etapa5_locator_drawer_paper_visivel(self):
        """
        Locator do painel branco lateral (serviços adicionais / streaming), não o backdrop.
        Prefere painéis que expõem o botão Salvar.
        """
        try:
            salvar_rx = re.compile(r"^\s*Salvar\s*$", re.I)
            selectors = (
                "div.MuiDrawer-paperAnchorRight",
                "div.MuiDrawer-paper.MuiDrawer-paperAnchorRight",
                '[class*="Drawer-paperAnchorRight"]',
                "aside.MuiDrawer-paper",
            )
            found_any = None
            for sel in selectors:
                loc = self.page.locator(sel)
                try:
                    n = loc.count()
                except Exception:
                    continue
                for i in range(n):
                    p = loc.nth(i)
                    try:
                        if not p.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        if p.get_by_role("button", name=salvar_rx).count() > 0:
                            return p
                    except Exception:
                        pass
                    if found_any is None:
                        found_any = p
            try:
                dialogs = self.page.get_by_role("dialog")
                nd = dialogs.count()
                for i in range(nd):
                    d = dialogs.nth(i)
                    if not d.is_visible():
                        continue
                    if d.get_by_role("button", name=salvar_rx).count() > 0:
                        return d
            except Exception:
                pass
            for sel in (
                'aside:has-text("Escolher serviços adicionais")',
                'aside:has-text("Escolher plataformas")',
                'div:has-text("Escolher serviços adicionais"):has(button:has-text("Salvar"))',
            ):
                try:
                    loc = self.page.locator(sel)
                    if loc.count() == 0:
                        continue
                    cand = loc.first
                    if not cand.is_visible():
                        continue
                    if cand.get_by_role("button", name=salvar_rx).count() > 0:
                        return cand
                    if cand.locator("button.sc-guDjWT.gIsNuI").count() > 0:
                        return cand
                except Exception:
                    continue
            return found_any
        except Exception:
            return None

    def _etapa5_clicar_salvar_painel(self) -> bool:
        """
        Clica no botão "Salvar" do painel lateral (Fixo/Streaming).
        Prioriza o drawer MUI visível para não acionar o backdrop nem outro Salvar da página.
        NÃO usar "Salvar Interesse". Classes atuais incluem sc-guDjWT gIsNuI.
        """
        try:
            self.page.wait_for_timeout(400)
            self._etapa5_scroll_painel_lateral_ate_rodape()
            salvar_rx = re.compile(r"^\s*Salvar\s*$", re.I)
            try:
                btns_sc = self.page.locator("button.sc-guDjWT.gIsNuI")
                for j in range(btns_sc.count() - 1, -1, -1):
                    bx = btns_sc.nth(j)
                    try:
                        if not bx.is_visible():
                            continue
                        tx = (bx.inner_text() or "").strip()
                        if tx != "Salvar" or "Interesse" in tx:
                            continue
                        bx.scroll_into_view_if_needed()
                        bx.click(force=True, timeout=8000)
                        self.page.wait_for_timeout(500)
                        return True
                    except Exception:
                        continue
            except Exception:
                pass
            roots = []
            paper = self._etapa5_locator_drawer_paper_visivel()
            if paper is not None:
                roots.append(paper)
            roots.append(self.page)

            def _try_salvar_em_root(root, use_force: bool) -> bool:
                try:
                    loc = root.get_by_role("button", name=salvar_rx)
                    for i in range(loc.count()):
                        b = loc.nth(i)
                        try:
                            if not b.is_visible():
                                continue
                            t = (b.inner_text() or "").strip()
                            if "Interesse" in t or t != "Salvar":
                                continue
                            b.scroll_into_view_if_needed()
                            b.click(force=use_force, timeout=8000)
                            self.page.wait_for_timeout(500)
                            return True
                        except Exception:
                            continue
                except Exception:
                    pass
                for sel in [
                    "button.sc-guDjWT.gIsNuI",
                    "button.gIsNuI.sc-guDjWT",
                    'button.sc-guDjWT:has-text("Salvar")',
                    "button.sc-izfUZz.eKoZwI",
                    "button.eKoZwI.sc-izfUZz",
                    'button[class*="gIsNuI"][class*="sc-guDjWT"]',
                ]:
                    try:
                        bl = root.locator(sel).first
                        if not bl.is_visible():
                            continue
                        tx = (bl.inner_text() or "").strip()
                        if tx != "Salvar" or "Interesse" in tx:
                            continue
                        cls = bl.get_attribute("class") or ""
                        if "dCaJBF" in cls or "hBqtbW" in cls:
                            continue
                        bl.scroll_into_view_if_needed()
                        bl.click(force=use_force, timeout=8000)
                        self.page.wait_for_timeout(500)
                        return True
                    except Exception:
                        continue
                return False

            for root in roots:
                if _try_salvar_em_root(root, use_force=False):
                    return True
            for root in roots:
                if _try_salvar_em_root(root, use_force=True):
                    return True

            for sel in ['[role="button"]:has-text("Salvar")', 'div[role="button"]:has-text("Salvar")']:
                try:
                    for el in self.page.query_selector_all(sel):
                        if not el or not el.is_visible():
                            continue
                        tx = (el.inner_text() or "").strip()
                        if tx != "Salvar" or "Interesse" in tx:
                            continue
                        el.scroll_into_view_if_needed()
                        el.click(force=True)
                        self.page.wait_for_timeout(500)
                        return True
                except Exception:
                    continue
            for sel in ['button.sc-izfUZz:has-text("Salvar")', '[class*="eKoZwI"]:has-text("Salvar")', 'button:has-text("Salvar")']:
                try:
                    btn = self.page.query_selector(sel)
                    if btn:
                        txt = (btn.inner_text() or "").strip()
                        if txt == "Salvar" and btn.is_visible():
                            cls = btn.get_attribute("class") or ""
                            if "dCaJBF" in cls or "hBqtbW" in cls:
                                continue
                            btn.scroll_into_view_if_needed()
                            btn.click()
                            self.page.wait_for_timeout(500)
                            return True
                except Exception:
                    continue
            btns = self.page.query_selector_all("button")
            for b in reversed(btns):
                txt = (b.inner_text() or "").strip()
                if txt == "Salvar":
                    cls = b.get_attribute("class") or ""
                    if "dCaJBF" in cls or "hBqtbW" in cls:
                        continue
                    if b.is_visible():
                        try:
                            b.scroll_into_view_if_needed()
                            b.click()
                            self.page.wait_for_timeout(500)
                            return True
                        except Exception:
                            pass
            logger.warning("[PAP] _etapa5_clicar_salvar_painel: nenhum botão Salvar visível encontrado")
            return False
        except Exception as e:
            logger.error(f"[PAP] _etapa5_clicar_salvar_painel: {e}")
            return False

    def _fechar_modal_servicos_adicionais(self) -> bool:
        """Fecha o modal 'Escolher serviços adicionais' se estiver aberto (X ou Escape)."""
        try:
            if "Escolher serviços adicionais" not in (self.page.content() or ""):
                return False
            # Tentar botão X (aria-label, classe close, ou ícone ×)
            btn_x = self.page.query_selector('button[aria-label="Close"], button[aria-label="Fechar"], [class*="close"] button, button:has-text("×")')
            if btn_x:
                btn_x.click()
                self.page.wait_for_timeout(400)
                return True
            # Fallback: tecla Escape fecha a maioria dos modais
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
            return True
        except Exception:
            return False

    def _etapa5_clicar_fechar_modal_x(self) -> bool:
        """Clica no botão X para fechar o modal que abre à direita (Fixo/Streaming)."""
        try:
            for sel in [
                SELETORES['etapa5']['btn_fechar_modal_x'],
                'button:has(svg path[d*="M19 6.41"])',
                'button[aria-label="Close"]',
                'button[aria-label="Fechar"]',
                '[class*="close"] button',
            ]:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(400)
                    return True
            return False
        except Exception as e:
            logger.warning(f"[PAP] _etapa5_clicar_fechar_modal_x: {e}")
            return False

    def etapa5_selecionar_fixo(self, tem_fixo: bool) -> Tuple[bool, str]:
        """
        Seleciona Fixo (R$ 30/mês).
        Abre "Serviços disponíveis", bloqueia backdrop, marca Fixo (preferindo o ícone img)
        e confirma que o painel lateral está pronto para portabilidade/Salvar.
        """
        try:
            self._etapa5_garantir_pagina()
            self.dados_pedido['tem_fixo'] = tem_fixo
            if not tem_fixo:
                return True, "OK"
            if not self._etapa5_clicar_servicos_disponiveis():
                return False, "Botão 'Serviços disponíveis' não encontrado."
            self.page.wait_for_timeout(400)
            try:
                self.page.wait_for_selector(
                    'text=Escolher serviços adicionais', timeout=15000
                )
            except Exception:
                logger.warning("[PAP] Título do drawer de serviços não apareceu a tempo.")
            self._etapa5_bloquear_backdrop_drawer_mui()
            self.page.wait_for_timeout(300)
            if not self._etapa5_clicar_opcao_fixo_no_drawer():
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Opção Fixo não encontrada no painel de serviços adicionais."

            ok, msg = self._etapa5_garantir_drawer_fixo_para_portabilidade(max_ciclos=2)
            if not ok:
                return False, msg or "Painel Fixo não ficou pronto."
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar fixo: {e}")
            return False, str(e)

    def etapa5_fixo_finalizar_portabilidade(
        self,
        quer_portabilidade: bool,
        numero_port: str = "",
        operadora_texto: str = "",
    ) -> Tuple[bool, str]:
        """
        Com o painel Fixo já aberto (após etapa5_selecionar_fixo(True)):
        opcionalmente marca portabilidade, preenche número e operadora, e clica Salvar.
        Se não houver bloco de portabilidade no DOM, apenas Salvar (compatível com layout antigo).
        """
        try:
            self._etapa5_garantir_pagina()
            self.page.wait_for_timeout(400)
            ok_g, msg_g = self._etapa5_garantir_drawer_fixo_para_portabilidade(max_ciclos=3)
            if not ok_g:
                return False, msg_g or "Painel Fixo não está aberto; não foi possível reabrir."
            self._etapa5_bloquear_backdrop_drawer_mui()
            self._etapa5_scroll_painel_lateral_ate_rodape()
            drawer = self._etapa5_locator_drawer_paper_visivel()
            ctx = drawer if drawer is not None else self.page
            port_lbl = ctx.locator('label:has-text("Cliente deseja fazer portabilidade")').first
            try:
                has_port = port_lbl.is_visible()
            except Exception:
                has_port = False
            if has_port:
                try:
                    cb = port_lbl.locator('input[type="checkbox"]')
                    if cb.count() > 0:
                        want = bool(quer_portabilidade)
                        try:
                            checked = cb.is_checked()
                        except Exception:
                            checked = False
                        if want and not checked:
                            port_lbl.click()
                            self.page.wait_for_timeout(250)
                        elif not want and checked:
                            port_lbl.click()
                            self.page.wait_for_timeout(250)
                    elif quer_portabilidade:
                        port_lbl.click()
                        self.page.wait_for_timeout(250)
                except Exception as ex:
                    logger.warning("[PAP] etapa5_fixo_finalizar_portabilidade: toggle portabilidade: %s", ex)
                if quer_portabilidade:
                    digits = re.sub(r"\D", "", numero_port or "")
                    if len(digits) < 10:
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return False, "Número para portabilidade inválido (informe DDD + número fixo)."
                    inp = self.page.query_selector("#contatoPortabilidade, input[name='contatoPortabilidade']")
                    if inp:
                        inp.fill(digits)
                        self.page.wait_for_timeout(200)
                    needle = (operadora_texto or "").strip()
                    if len(needle) < 2:
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return False, "Informe a operadora de origem (ex.: Vivo, Claro, Tim)."
                    sel_el = self.page.query_selector('select[name="operadora"]')
                    if not sel_el:
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return False, "Campo operadora não encontrado no painel."
                    matched = False
                    needle_l = needle.lower()
                    for opt in self.page.query_selector_all('select[name="operadora"] option'):
                        val = (opt.get_attribute("value") or "").strip()
                        if not val:
                            continue
                        label = (opt.inner_text() or "").strip()
                        if needle_l in label.lower() or label.lower() in needle_l:
                            try:
                                self.page.select_option('select[name="operadora"]', value=val)
                                matched = True
                                break
                            except Exception:
                                continue
                    if not matched:
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return (
                            False,
                            "Operadora não encontrada na lista. Tente o nome curto (ex.: Vivo, Claro, OI, Tim).",
                        )
            # Salvar fica no rodapé do painel lateral; sem scroll o Playwright não acha "visível"
            try:
                for scroll_sel in (
                    'select[name="operadora"]',
                    "#contatoPortabilidade",
                    'label:has-text("portabilidade")',
                    'button:has-text("Salvar")',
                ):
                    eloc = ctx.locator(scroll_sel).first
                    try:
                        if eloc.is_visible():
                            eloc.scroll_into_view_if_needed()
                            self.page.wait_for_timeout(150)
                    except Exception:
                        pass
                self.page.evaluate("""() => {
                    const roots = document.querySelectorAll('aside, [class*="Drawer"], [class*="drawer"], [role="dialog"]');
                    roots.forEach(r => { try { r.scrollTop = r.scrollHeight; } catch (e) {} });
                }""")
                self.page.wait_for_timeout(200)
            except Exception:
                pass
            if not self._etapa5_clicar_salvar_painel():
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Botão Salvar do painel Fixo não encontrado."
            self._etapa5_restaurar_backdrop_drawer_mui()
            self.dados_pedido["fixo_portabilidade"] = quer_portabilidade
            if quer_portabilidade:
                self.dados_pedido["fixo_portabilidade_numero"] = re.sub(r"\D", "", numero_port or "")
                self.dados_pedido["fixo_portabilidade_operadora"] = (operadora_texto or "").strip()
            self.page.wait_for_timeout(400)
            return True, "OK"
        except Exception as e:
            logger.error("[PAP] etapa5_fixo_finalizar_portabilidade: %s", e)
            self._etapa5_restaurar_backdrop_drawer_mui()
            return False, str(e)

    def etapa5_selecionar_streaming(self, tem_streaming: bool, streaming_opcoes: str = None, plano: str = "") -> Tuple[bool, str]:
        """
        Seleciona streaming no drawer "Escolher plataformas de streaming…".
        Clica nos preços em div.sc-hQfrgq.frojRS (44,90 / 39,90 / 22,90), valida seleção e Salvar.
        Premium e Padrão Globoplay são excludentes; 700Mb/1Gb não oferece Padrão.
        """
        try:
            self._etapa5_garantir_pagina()
            self.dados_pedido['tem_streaming'] = tem_streaming
            self.dados_pedido['streaming_opcoes'] = (streaming_opcoes or '').strip()
            if not tem_streaming:
                return True, "OK"

            plano_lower = (plano or self.dados_pedido.get("plano", "")).lower()
            skip_padrao = "700mega" in plano_lower or "1giga" in plano_lower
            opts = [x.strip() for x in (streaming_opcoes or "").lower().replace(" ", "").split(",") if x.strip()]
            if not opts:
                return False, "Nenhuma opção de streaming informada (streaming_opcoes vazio)."

            precos: List[str] = []
            for o in opts:
                p = self._etapa5_streaming_map_opcao_para_preco(o, skip_padrao)
                if p:
                    precos.append(p)
            if not precos:
                return False, "Opções de streaming não reconhecidas (use hbomax, globoplay_premium, globoplay_basico, etc.)."

            if "39,90" in precos and "22,90" in precos:
                precos = [x for x in precos if x != "22,90"]
                logger.info("[PAP] Globoplay Premium e Padrão juntos: mantendo só Premium (39,90).")

            btn_ok = False
            try:
                lb = self.page.get_by_role(
                    "button",
                    name=re.compile(r"Streaming\s+e\s+canais\s+on[-\s]?line", re.I),
                )
                if lb.count() > 0:
                    b0 = lb.first
                    if b0.is_visible():
                        b0.scroll_into_view_if_needed()
                        b0.click(timeout=8000)
                        btn_ok = True
            except Exception:
                pass
            if not btn_ok:
                btn_stream = self.page.query_selector(SELETORES["etapa5"]["btn_streaming"])
                if not btn_stream:
                    btn_stream = self.page.query_selector(
                        'button.sc-wRHdD:has-text("Streaming e canais on-line")'
                    )
                if not btn_stream:
                    btn_stream = self.page.query_selector(
                        'button.sc-izfUZz:has-text("Streaming e canais on-line")'
                    )
                if not btn_stream:
                    btn_stream = self.page.query_selector('div:has-text("Streaming e canais on-line")')
                if not btn_stream or not btn_stream.is_visible():
                    return False, "Botão 'Streaming e canais on-line' não encontrado."
                try:
                    btn_stream.scroll_into_view_if_needed()
                    btn_stream.click()
                except Exception:
                    self.page.evaluate("(el) => el.click()", btn_stream)

            self.page.wait_for_timeout(500)
            try:
                self.page.wait_for_selector('text=Escolher plataformas', timeout=15000)
            except Exception:
                pass
            if not self._etapa5_drawer_streaming_titulo_visivel():
                return (
                    False,
                    "Drawer de streaming não abriu (texto 'Escolher plataformas' não visível).",
                )
            self._etapa5_bloquear_backdrop_drawer_mui()
            self.page.wait_for_timeout(300)
            self._etapa5_scroll_drawer_streaming_ate_salvar()

            for preco in precos:
                self._etapa5_scroll_drawer_streaming_ate_salvar()
                if not self._etapa5_clicar_preco_streaming(preco):
                    self._etapa5_restaurar_backdrop_drawer_mui()
                    return False, f"Não foi possível clicar na linha do streaming (preço R$ {preco})."
                if not self._etapa5_streaming_preco_parece_selecionado(preco):
                    logger.warning("[PAP] Streaming R$ %s: seleção não confirmada; repetindo clique.", preco)
                    self._etapa5_clicar_preco_streaming(preco)
                    self.page.wait_for_timeout(450)
                if not self._etapa5_streaming_preco_parece_selecionado(preco):
                    self._etapa5_restaurar_backdrop_drawer_mui()
                    return (
                        False,
                        f"Streaming R$ {preco} não ficou selecionado (checkbox/estado não detectado).",
                    )

            self.page.wait_for_timeout(500)
            self._etapa5_scroll_drawer_streaming_ate_salvar()
            self._etapa5_scroll_painel_lateral_ate_rodape()

            salvar_ok = self._etapa5_clicar_salvar_painel()
            if not salvar_ok:
                self.page.wait_for_timeout(600)
                self._etapa5_scroll_drawer_streaming_ate_salvar()
                self._etapa5_scroll_painel_lateral_ate_rodape()
                salvar_ok = self._etapa5_clicar_salvar_painel()
            if not salvar_ok:
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Botão Salvar do painel de streaming não encontrado ou não clicável."

            self._etapa5_restaurar_backdrop_drawer_mui()
            self.page.wait_for_timeout(400)
            try:
                if "Escolher plataformas" in (self.page.content() or ""):
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(200)
            except Exception:
                pass
            self.page.wait_for_timeout(200)
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar streaming: {e}")
            try:
                self._etapa5_restaurar_backdrop_drawer_mui()
            except Exception:
                pass
            return False, str(e)

    def etapa5_clicar_avancar(self) -> Tuple[bool, str]:
        """Clica em Avançar para ir da etapa 5 (pagamento/ofertas) para etapa 6 (biometria)."""
        try:
            self._etapa5_garantir_pagina()
            # Fechar modal "Escolher serviços adicionais" se estiver aberto (bloqueia o Avançar)
            self._fechar_modal_servicos_adicionais()
            self.page.wait_for_timeout(400)
            plano_dp = (self.dados_pedido.get("plano") or "").strip().lower()
            # Não reaplicar o plano aqui: isso resetaria Fixo/Streaming já configurados.
            self.page.wait_for_timeout(400)
            # Aguardar spinner sumir (se houver)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=3000)
            except Exception:
                pass
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not btn_avancar:
                return False, "Botão Avançar não disponível ou desabilitado."
            btn_avancar.click()
            self.page.wait_for_load_state("networkidle", timeout=10000)
            if plano_dp in ("1giga", "700mega", "500mega"):
                try:
                    self.page.wait_for_selector('h2:has-text("Resumo")', state="visible", timeout=25000)
                except Exception:
                    logger.warning("[PAP] Título Resumo não apareceu no tempo esperado após Avançar.")
                ok_v, msg_v, lido = self.etapa6_validar_plano_resumo(plano_dp)
                if not ok_v:
                    logger.error("[PAP] Validação plano Resumo falhou: %s (lido=%r)", msg_v, lido)
                    return False, msg_v
            self.etapa_atual = 5
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao clicar Avançar: {e}")
            return False, str(e)

    def etapa5_pagamento_plano(
        self,
        forma_pagamento: str,
        plano: str,
        tem_fixo: bool = False,
        tem_streaming: bool = False,
        streaming_opcoes: str = None,
        banco: str = None,
        agencia: str = None,
        conta: str = None,
        digito: str = None,
    ) -> Tuple[bool, str]:
        """
        Etapa 5: Forma de pagamento, plano e serviços adicionais (chamada única).
        Usado pelo fluxo WhatsApp. Para fluxo incremental (terminal), use os métodos
        etapa5_selecionar_* e etapa5_clicar_avancar.
        """
        try:
            sucesso, msg = self.etapa5_selecionar_forma_pagamento(forma_pagamento)
            if not sucesso:
                return False, msg
            if forma_pagamento.lower() == 'debito' and (banco or agencia or conta or digito):
                sucesso, msg = self.etapa5_preencher_debito(banco or '', agencia or '', conta or '', digito or '')
                if not sucesso:
                    return False, msg
            sucesso, msg = self.etapa5_selecionar_plano_com_validacao(plano)
            if not sucesso:
                return False, msg
            sucesso, msg = self.etapa5_selecionar_fixo(tem_fixo)
            if not sucesso:
                return False, msg
            if tem_fixo:
                sucesso, msg = self.etapa5_fixo_finalizar_portabilidade(
                    quer_portabilidade=False, numero_port="", operadora_texto=""
                )
                if not sucesso:
                    return False, msg
            sucesso, msg = self.etapa5_selecionar_streaming(tem_streaming, streaming_opcoes, plano)
            if not sucesso:
                return False, msg
            sucesso, msg = self.etapa5_clicar_avancar()
            if not sucesso:
                return False, msg
            return True, f"Plano {plano.upper()} com pagamento via {forma_pagamento.upper()}!"
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 5: {e}")
            return False, f"Erro na Etapa 5: {str(e)}"
    
    def obter_resumo_pedido_para_cliente(self) -> str:
        """
        Monta o resumo do pedido a partir dos dados coletados no fluxo.
        Inclui Fixo e streaming na seção de serviços adicionais apenas quando contratados (com preços).
        Endereço no padrão: Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP.
        """
        d = self.dados_pedido
        nome = d.get('nome_cliente') or 'Cliente'
        cep = d.get('cep') or ''
        numero = d.get('numero') or ''
        ref = d.get('referencia') or ''
        # Endereço completo no padrão (ViaCEP): Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP
        endereco = self._formatar_endereco_completo(cep, numero, ref) if cep else ""
        if not endereco:
            partes = []
            if (str(cep or '').strip()): partes.append(f"CEP {cep}")
            if (str(numero or '').strip()): partes.append(f"Nº {numero}")
            if (str(ref or '').strip()): partes.append(f"Ref: {ref}")
            endereco = ", ".join(partes) if partes else (ref if ref else "Endereço a confirmar")
        plano = (d.get('plano') or '500mega').upper()
        forma_raw = (d.get('forma_pagamento') or '').upper()
        cartao = 'CREDITO' in forma_raw or 'CARTÃO' in forma_raw or 'CARTAO' in forma_raw
        valor_map = {
            '500MEGA': ('R$ 100,00/mês', 'R$ 90,00/mês'),
            '700MEGA': ('R$ 130,00/mês', 'R$ 120,00/mês'),
            '1GIGA': ('R$ 160,00/mês', 'R$ 150,00/mês'),
        }
        par = valor_map.get(plano.upper(), ('R$ --', 'R$ --'))
        valor = par[1] if cartao else par[0]
        plano_label = plano.replace('MEGA', ' Mega').replace('GIGA', ' Giga')
        forma_raw_val = (d.get('forma_pagamento') or 'Boleto').strip().lower()
        forma_display_map = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito', 'cartão': 'Cartão de Crédito', 'debito': 'Débito em Conta', 'débito': 'Débito em Conta'}
        forma = forma_display_map.get(forma_raw_val) or forma_raw_val.replace('credito', 'Cartão').replace('dacc', 'Débito').replace('boleto', 'Boleto').title()
        # Serviços adicionais com preços
        linhas_adic = []
        if d.get('tem_fixo'):
            linhas_adic.append("• Fixo: R$ 30,00/mês")
        opts_raw = (d.get('streaming_opcoes') or '').lower().replace(' ', '')
        opts_set = set(x.strip() for x in opts_raw.split(',') if x.strip())
        precos_streaming = [
            ('hbomax', 'HBO Max', 'R$ 44,90/mês'),
            ('globoplay_premium', 'Globoplay – Plano Premium', 'R$ 39,90/mês'),
            ('globoplay_basico', 'Globoplay – Plano Padrão com Anúncios', 'R$ 22,90/mês'),
        ]
        for key, label, preco in precos_streaming:
            if key in opts_set:
                linhas_adic.append(f"• {label}: {preco}")
        partes_apos_forma = []
        if linhas_adic:
            partes_apos_forma.append("✨ *Serviços adicionais:*\n" + "\n".join(linhas_adic))
        if d.get("tem_fixo") and d.get("fixo_portabilidade"):
            raw_num = re.sub(r"\D", "", str(d.get("fixo_portabilidade_numero") or ""))
            op_p = (d.get("fixo_portabilidade_operadora") or "").strip() or "—"
            if len(raw_num) >= 10:
                if len(raw_num) == 11:
                    num_fmt = f"({raw_num[:2]}) {raw_num[2:7]}-{raw_num[7:]}"
                else:
                    num_fmt = f"({raw_num[:2]}) {raw_num[2:6]}-{raw_num[6:]}"
            else:
                num_fmt = d.get("fixo_portabilidade_numero") or raw_num or "—"
            partes_apos_forma.append(
                f"📲 *Portabilidade do fixo:* {num_fmt} — operadora *{op_p}*"
            )
        bloco_apos_forma = (
            "\n\n".join(partes_apos_forma) + "\n\n" if partes_apos_forma else ""
        )
        texto_fatura = (
            "Sua primeira fatura irá vencer *25 dias* após a instalação da internet; nos demais meses, "
            "o vencimento segue o ciclo de *30 em 30 dias*.\n\n"
        )
        return (
            "📋 *RESUMO DO PEDIDO*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *Cliente:* {nome}\n\n"
            f"📍 *Endereço:*\n{endereco}\n\n"
            f"📦 *Plano:* {plano_label} – {valor}\n\n"
            f"💳 *Forma de pagamento:* {forma}\n\n"
            f"{bloco_apos_forma}"
            f"📅 *Fidelidade:* 12 meses\n\n"
            "💰 *Taxa de habilitação:*\n"
            "Você ganha isenção da taxa de habilitação se permanecer no mínimo 12 meses conosco.\n\n"
            f"{texto_fatura}"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Para confirmar, responda *SIM*."
        )

    def etapa6_extrair_resumo_oferta(self) -> Tuple[bool, str]:
        """
        Etapa 6: Extrai o resumo da oferta (Detalhes da oferta) da página.
        
        Returns:
            Tuple (sucesso, texto_resumo)
        """
        try:
            logger.info("[PAP] Etapa 6 - Extraindo resumo da oferta")
            self.page.wait_for_load_state("networkidle", timeout=10000)
            linhas = []
            # Detalhes da oferta - pegar seção inteira (título + conteúdo abaixo)
            secao = self.page.query_selector('div:has-text("Detalhes da oferta")')
            if secao:
                try:
                    # Pegar container pai que engloba título + conteúdo
                    texto = secao.evaluate("el => { const p = el.closest('div') || el.parentElement; return (p ? p.innerText : el.innerText) || ''; }")
                    if isinstance(texto, str) and texto.strip() and len(texto.strip()) > 5:
                        linhas.append(texto.strip())
                except Exception:
                    pass
                if not linhas:
                    try:
                        texto = secao.inner_text()
                        if texto:
                            linhas.append(texto.strip())
                    except Exception:
                        pass
            # Fallback: blocos com plano, preço
            if not linhas:
                blocos = self.page.query_selector_all('div:has-text("Nio Fibra"), div:has-text("Giga"), div:has-text("Mega"), div:has-text("R$")')
                vistos = set()
                for b in blocos[:8]:
                    try:
                        t = (b.inner_text() or "").strip()
                        if t and len(t) < 120 and t not in vistos:
                            vistos.add(t)
                            linhas.append(t)
                    except Exception:
                        pass
            resumo = "\n".join(linhas) if linhas else "Resumo da oferta não disponível."
            self.dados_pedido['resumo_oferta'] = resumo
            return True, resumo
        except Exception as e:
            logger.error(f"[PAP] Erro ao extrair resumo: {e}")
            return False, f"Erro: {str(e)}"

    def _obter_endereco_via_cep(self, cep: str, numero: str = "", complemento: str = "") -> str:
        """Consulta ViaCEP e retorna endereço completo."""
        try:
            import requests
            cep_limpo = re.sub(r'\D', '', str(cep or ''))[:8]
            if len(cep_limpo) != 8:
                return ""
            url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            d = r.json()
            if d.get('erro'):
                return ""
            logradouro = d.get('logradouro', '')
            bairro = d.get('bairro', '')
            localidade = d.get('localidade', '')
            uf = d.get('uf', '')
            cep_fmt = d.get('cep', cep_limpo)
            partes = [p for p in [logradouro, numero, complemento, bairro, f"{localidade}-{uf}", f"CEP {cep_fmt}"] if p]
            return ", ".join(partes)
        except Exception as e:
            logger.warning(f"[PAP] ViaCEP erro: {e}")
            return ""

    def _formatar_endereco_completo(self, cep: str, numero: str = "", complemento: str = "") -> str:
        """
        Retorna endereço no padrão: Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP
        Ex.: R. Cachopa, 108 - Casa 1 - São João, Betim - MG, 32655-612
        Complemento (ex.: referencia) vem após o número da fachada.
        """
        try:
            import requests
            cep_limpo = re.sub(r'\D', '', str(cep or ''))[:8]
            if len(cep_limpo) != 8:
                return ""
            url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            d = r.json()
            if d.get('erro'):
                return ""
            logradouro = (d.get('logradouro') or '').strip()
            bairro = (d.get('bairro') or '').strip()
            localidade = (d.get('localidade') or '').strip()
            uf = (d.get('uf') or '').strip()
            cep_fmt = d.get('cep', cep_limpo)
            numero_s = str(numero or '').strip()
            complemento_s = str(complemento or '').strip()
            # Formato: Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP
            parte1 = f"{logradouro}, {numero_s}" if logradouro else (numero_s or "")
            if complemento_s:
                parte1 = f"{parte1} - {complemento_s}" if parte1 else complemento_s
            parte2 = f"{bairro}, {localidade} - {uf}, {cep_fmt}" if bairro else f"{localidade} - {uf}, {cep_fmt}"
            if parte1 and parte2:
                return f"{parte1} - {parte2}"
            if parte2:
                return parte2
            return f"{parte1}, {cep_fmt}" if parte1 else ""
        except Exception as e:
            logger.warning(f"[PAP] _formatar_endereco_completo: {e}")
            return ""

    def _plano_normalizar_de_texto_resumo(self, texto: str) -> Optional[str]:
        """Converte texto exibido no PAP (ex.: '1 Giga', '500 Mega') para chave interna."""
        if not texto:
            return None
        t = texto.replace("\u00a0", " ").lower().strip()
        if re.search(r"\b1\s*giga\b", t):
            return "1giga"
        if re.search(r"\b700\s*mega\b", t):
            return "700mega"
        if re.search(r"\b500\s*mega\b", t):
            return "500mega"
        return None

    def etapa6_ler_plano_detalhes_oferta_resumo(self) -> Tuple[bool, str]:
        """
        Na tela Resumo, lê o plano exibido em Detalhes da oferta (ex.: div com 1 Giga / 500 Mega).
        """
        try:
            self.page.wait_for_selector('h2:has-text("Resumo")', state="visible", timeout=20000)
        except Exception:
            return False, ""
        try:
            raw = self.page.evaluate(
                r"""() => {
                  const pick = (t) => (t || '').trim();
                  const el1 = document.querySelector('div.sc-kOnlKp.bVXyze');
                  if (el1) {
                    const t = pick(el1.textContent);
                    if (/Mega|Giga/i.test(t) && t.length < 80) return t;
                  }
                  for (const el2 of document.querySelectorAll('[class*="bVXyze"]')) {
                    const t = pick(el2.textContent);
                    if (/Mega|Giga/i.test(t) && t.length < 80) return t;
                  }
                  const h2 = [...document.querySelectorAll('h2')].find(
                    (e) => pick(e.textContent) === 'Resumo'
                  );
                  const root = h2
                    ? h2.closest('main') || h2.closest('[class*="sc-"]') || document.body
                    : document.body;
                  const cand = root.querySelectorAll('div, span');
                  for (const k of cand) {
                    const t = pick(k.textContent);
                    if (/^1\s*Giga$/i.test(t) || /^700\s*Mega$/i.test(t) || /^500\s*Mega$/i.test(t)) {
                      return t;
                    }
                  }
                  const blob = (root.innerText || '').replace(/\s+/g, ' ');
                  const m = blob.match(/\b(1\s*Giga|700\s*Mega|500\s*Mega)\b/i);
                  if (m) return m[1].replace(/\s+/g, ' ').trim();
                  return '';
                }"""
            )
            return True, (raw or "").strip()
        except Exception as e:
            logger.warning("[PAP] etapa6_ler_plano_detalhes_oferta_resumo: %s", e)
            return False, ""

    def etapa6_validar_plano_resumo(self, plano_interno: str) -> Tuple[bool, str, str]:
        """
        Garante que o plano em Detalhes da oferta confere com o escolhido no fluxo.
        Retorna (ok, mensagem_erro_vazia_se_ok, texto_lido).
        """
        esp = (plano_interno or self.dados_pedido.get("plano") or "").strip().lower()
        if esp not in ("1giga", "700mega", "500mega"):
            return True, "", ""
        ok_r, lido = self.etapa6_ler_plano_detalhes_oferta_resumo()
        if not ok_r or not lido:
            return (
                False,
                "Não foi possível ler o plano na tela Resumo (Detalhes da oferta). "
                "Confira no navegador se a oferta está correta antes de seguir.",
                lido or "",
            )
        achado = self._plano_normalizar_de_texto_resumo(lido)
        if achado is None:
            return (
                False,
                f"Plano na tela Resumo não reconhecido ({lido!r}). Esperado: {esp}. Ajuste manualmente no PAP.",
                lido,
            )
        if achado != esp:
            mapa = {"1giga": "1 Giga", "700mega": "700 Mega", "500mega": "500 Mega"}
            return (
                False,
                f"Plano no PAP ({lido!r}) não confere com o escolhido no fluxo ({mapa.get(esp, esp)}). "
                "O portal pode ter resetado a oferta ao abrir serviços; corrija no site ou reinicie a venda.",
                lido,
            )
        return True, "", lido

    def _etapa6_avancar_ate_tela_biometria(self, max_cliques: int = 3) -> None:
        """
        Se o usuário voltou no navegador, o portal pode exibir só a etapa anterior (ex.: Resumo/ofertas)
        com *Avançar* em vez da etapa 6 com biometria. Clica Avançar até aparecer Abrir OS ou
        Consultar Biometria, ou até não haver mais Avançar habilitado.
        """
        sel_abrir = (
            'button:has-text("Abrir OS"):not([disabled]), '
            'button:has-text("Abrir O.S"):not([disabled]), '
            'button:has-text("Abrir O.S."):not([disabled])'
        )
        sel_consultar = 'button:has-text("Consultar Biometria"), button.btn-consult-new'

        def _vis(el):
            try:
                return el and el.is_visible()
            except Exception:
                return False

        for i in range(max_cliques):
            btn_os = self.page.query_selector(sel_abrir)
            if _vis(btn_os):
                return
            btn_c = self.page.query_selector(sel_consultar)
            if _vis(btn_c):
                return
            btn_av = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not _vis(btn_av):
                return
            logger.info(
                "[PAP] Etapa 6 - Clicando Avançar para atingir a tela de biometria "
                "(ex.: voltou no navegador; passo %s/%s)",
                i + 1,
                max_cliques,
            )
            try:
                btn_av.click()
            except Exception as e:
                logger.warning("[PAP] Etapa 6 - Falha ao clicar Avançar: %s", e)
                return
            self.page.wait_for_timeout(1000)
            try:
                self.page.wait_for_selector("div.spinner", state="hidden", timeout=12000)
            except Exception:
                self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

    def etapa6_consultar_biometria(self) -> Tuple[bool, str]:
        """Clica no botão Consultar Biometria na etapa 6."""
        try:
            pode, err = self._pap_garantir_sessao_antes_resumo()
            if not pode:
                return False, err
            self._etapa6_avancar_ate_tela_biometria()
            logger.info("[PAP] Etapa 6 - Clicando Consultar Biometria")
            btn = self.page.query_selector('button:has-text("Consultar Biometria"), button.btn-consult-new')
            if not btn:
                return False, "Botão Consultar Biometria não encontrado."
            btn.click()
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            self.page.wait_for_timeout(800)
            ok_modal, err_modal = self._pap_tratar_modais_apos_acao_pap()
            if not ok_modal and err_modal:
                return False, f"Portal exibiu erro após consultar biometria: {err_modal}"
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao consultar biometria: {e}")
            return False, str(e)

    def etapa6_verificar_biometria(self, consultar_primeiro: bool = False) -> Tuple[bool, str, bool]:
        """
        Etapa 6: Verificar status da biometria.

        Fonte da verdade: (1) botão "Abrir OS" habilitado = biometria aprovada;
        (2) texto explícito de aprovação no contexto do rótulo Biometria (aprovada/apto/liberado);
        Não inferir aprovação só por estar na tela Resumo sem "pendente" (evita falso positivo).

        Args:
            consultar_primeiro: Se True, clica em "Consultar Biometria" antes de verificar (para atualizar status)

        Returns:
            Tuple (sucesso, mensagem, biometria_aprovada)
        """
        try:
            logger.info("[PAP] Etapa 6 - Verificando biometria")

            pode, err = self._pap_garantir_sessao_antes_resumo()
            if not pode:
                return False, err, False

            # Aguardar spinner desaparecer (bloqueia cliques)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
            except Exception:
                self.page.wait_for_timeout(2000)

            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            # Voltar no navegador pode deixar a tela na etapa anterior (só Avançar). Ir à etapa 6 antes de consultar.
            self._etapa6_avancar_ate_tela_biometria()

            def _btn_abrir_os_visivel():
                return self.page.query_selector(
                    'button:has-text("Abrir OS"):not([disabled]), '
                    'button:has-text("Abrir O.S"):not([disabled]), '
                    'button:has-text("Abrir O.S."):not([disabled])'
                )

            # 1) Sempre checar Abrir OS *antes* de "Consultar Biometria": após aprovação o portal
            #    pode ocultar a linha Biometria; clicar em Consultar sem necessidade gera falso "pendente".
            btn_abrir_os = _btn_abrir_os_visivel()
            if btn_abrir_os:
                self.dados_pedido["_pap_biometria_aprovada"] = True
                self.etapa_atual = 6
                return True, "Biometria APROVADA! Pronto para abrir O.S.", True

            # 2) Consultar só se pedido e ainda não há Abrir OS (atualiza status quando pendente)
            if consultar_primeiro:
                ok_c, msg_c = self.etapa6_consultar_biometria()
                if not ok_c:
                    return False, msg_c, False
                self.page.wait_for_timeout(2500)
                try:
                    self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
                except Exception:
                    self.page.wait_for_timeout(2000)
                btn_abrir_os = _btn_abrir_os_visivel()
                if btn_abrir_os:
                    self.dados_pedido["_pap_biometria_aprovada"] = True
                    self.etapa_atual = 6
                    return True, "Biometria APROVADA! Pronto para abrir O.S.", True

            # Última tentativa: às vezes após consulta o portal volta a mostrar só Avançar
            self._etapa6_avancar_ate_tela_biometria(max_cliques=2)

            btn_abrir_os = _btn_abrir_os_visivel()
            if btn_abrir_os:
                self.dados_pedido["_pap_biometria_aprovada"] = True
                self.etapa_atual = 6
                return True, "Biometria APROVADA! Pronto para abrir O.S.", True

            # 2) Restringir "pendente" ao contexto da biometria (evitar falso "pendente" em texto da tela Resumo)
            span_biometria = self.page.query_selector('span:has-text("Biometria")')
            contexto_biometria = ""
            if span_biometria:
                try:
                    # Texto da linha/célula ou do container que contém o label Biometria
                    contexto_biometria = (
                        span_biometria.evaluate(
                            "el => (el.closest('tr') || el.closest('div'))?.innerText || el.innerText || ''"
                        ) or ""
                    ).lower()
                except Exception:
                    contexto_biometria = (span_biometria.inner_text() or "").lower()
            biometria_pendente = (
                'pendente' in contexto_biometria
                or 'aguardando' in contexto_biometria
                or 'em análise' in contexto_biometria
            )
            biometria_aprovada_texto = False
            if contexto_biometria:
                biometria_aprovada_texto = any(
                    x in contexto_biometria
                    for x in (
                        'aprovad',
                        'apto',
                        'liberad',
                        'concluíd',
                        'concluid',
                        'validad',
                        'documento apto',
                    )
                )

            if span_biometria and biometria_aprovada_texto and not biometria_pendente:
                self.dados_pedido["_pap_biometria_aprovada"] = True
                self.etapa_atual = 6
                return True, "Biometria APROVADA (status na linha Biometria). Pronto para abrir O.S.", True

            if self.dados_pedido.get("_pap_biometria_aprovada"):
                return True, "Biometria já aprovada neste pedido.", True

            if biometria_pendente:
                return True, "Biometria PENDENTE. Peça ao cliente para realizar a biometria e digite CONSULTAR para verificar novamente.", False
            return False, "Biometria não aprovada ou não disponível.", False

        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 6: {e}")
            return False, f"Erro na Etapa 6: {str(e)}", False
    
    def etapa7_ir_para_agendamento(self) -> Tuple[bool, str]:
        """Clica em Abrir OS e aguarda a tela de Agendamento aparecer.
        O portal executa 9 validações ('Consultando os slots para agendamento' 1 de 9 ... 9 de 9)
        antes de exibir a tela; timeout alto para não falhar durante as validações."""
        try:
            btn = self.page.query_selector(
                'button:has-text("Abrir OS"):not([disabled]), '
                'button:has-text("Abrir O.S"):not([disabled]), '
                'button:has-text("Abrir O.S."):not([disabled])'
            )
            if not btn:
                ctx = self.pap_inspecionar_contexto_etapa()
                return (
                    False,
                    f"Botão Abrir OS não disponível. Onde parece estar: {ctx.get('provavel')} — "
                    f"consulte biometria no PAP e use CONSULTAR de novo.",
                )
            btn.click()
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            ok_modal, err_modal = self._pap_tratar_modais_apos_acao_pap()
            if not ok_modal and err_modal:
                ctx = self.pap_inspecionar_contexto_etapa()
                return (
                    False,
                    f"Modal de erro no portal após Abrir OS: {err_modal} "
                    f"(tela provável: {ctx.get('provavel')}). Feche o aviso no navegador se ainda estiver aberto "
                    f"e tente CONSULTAR novamente.",
                )
            # 9 validações no portal; aguardar até 90s — seletores alternativos (UI muda entre builds)
            sel_ag = (
                'h3:has-text("Período"), h2:has-text("Período"), '
                'p:has-text("Período"), span:has-text("Período"), '
                '[class*="react-datepicker"], .react-datepicker, '
                'h2:has-text("Agendamento"), h3:has-text("Agendamento"), '
                '[class*="Agendamento"], [class*="agendamento"]'
            )
            _t7_ms = int(getattr(settings, "PAP_ETAPA7_AGENDAMENTO_TIMEOUT_MS", 120000) or 120000)
            ok_wait, err_wait = self.esperar_selector_com_keepalive_sessao(
                sel_ag,
                timeout_ms=max(90000, _t7_ms),
                poll_ms=5000,
                target_after_relogin=PAP_NOVO_PEDIDO_URL,
            )
            if not ok_wait:
                if err_wait and "Sessão do portal expirou durante a espera" in err_wait:
                    return False, err_wait
                ctx = self.pap_inspecionar_contexto_etapa()
                logger.error(
                    "[PAP] etapa7 timeout aguardando UI. url=%s ctx=%s err=%s",
                    ctx.get("url"),
                    ctx,
                    err_wait,
                )
                return (
                    False,
                    f"{err_wait or 'timeout'} Onde parece estar: {ctx.get('provavel')}. "
                    f"Se voltou ao início do pedido ou há aviso de erro, corrija no PAP e repita CONSULTAR. "
                    f"Modal visível: {ctx.get('trecho_modal')[:180] if ctx.get('trecho_modal') else '(nenhum)'}",
                )
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return True, "Tela de Agendamento exibida."
        except Exception as e:
            logger.error(f"[PAP] etapa7_ir_para_agendamento: {e}")
            ctx = self.pap_inspecionar_contexto_etapa()
            return False, f"{e} (contexto: {ctx.get('provavel')})"

    def etapa7_obter_datas_disponiveis(self) -> Tuple[bool, str, list]:
        """Extrai as datas disponíveis no calendário (dias clicáveis). Retorna lista de números de dia."""
        try:
            dias = self.page.query_selector_all('.react-datepicker__day:not(.react-datepicker__day--disabled):not(.react-datepicker__day--outside-month)')
            nums = []
            for d in dias:
                txt = (d.inner_text() or "").strip()
                if txt.isdigit() and 1 <= int(txt) <= 31:
                    nums.append(int(txt))
            nums = sorted(set(nums))
            return True, "OK", nums
        except Exception as e:
            logger.error(f"[PAP] etapa7_obter_datas: {e}")
            return False, str(e), []

    def etapa7_selecionar_data_e_obter_periodos(self, dia: int) -> Tuple[bool, str, list]:
        """Clica no dia no calendário e retorna os períodos disponíveis. Períodos: [{idx, label}]."""
        try:
            # Tentar por aria-label ou classe (ex: day-10, day-011)
            elem = self.page.query_selector(f'.react-datepicker__day[aria-label="day-{dia}"], .react-datepicker__day[aria-label="day-{dia:02d}"]')
            if not elem:
                elem = self.page.query_selector(f'.react-datepicker__day--0{dia:02d}:not(.react-datepicker__day--disabled)')
            if not elem:
                elems = self.page.query_selector_all('.react-datepicker__day:not(.react-datepicker__day--disabled)')
                for e in elems:
                    if (e.inner_text() or "").strip() == str(dia):
                        elem = e
                        break
            if not elem:
                return False, f"Dia {dia} não encontrado no calendário.", []
            elem.click()
            self.page.wait_for_timeout(1500)
            # Períodos: 2 (08h às 12h - Manhã, 13h às 18h - Tarde) ou 4 (08h-10h, 10h-12h, 13h-15h, 15h-18h)
            # Garantir ordem do DOM e reconhecer ambos os formatos
            periodos = self._etapa7_obter_lista_periodos()
            labels = []
            for i, p in enumerate(periodos):
                lbl = (p.inner_text() or "").strip()
                if lbl:
                    labels.append({"idx": i + 1, "label": lbl})
            return True, "OK", labels
        except Exception as e:
            logger.error(f"[PAP] etapa7_selecionar_data: {e}")
            return False, str(e), []

    def _etapa7_obter_lista_periodos(self):
        """Retorna lista de elementos li de período em ordem do DOM.
        Reconhece 2 períodos (08h às 12h - Manhã, 13h às 18h - Tarde) ou 4 períodos."""
        # Padrão "Xh às Yh" (ex.: 08h às 12h - Manhã, 13h às 18h - Tarde)
        try:
            all_li = self.page.query_selector_all('li')
            periodos = []
            pattern = re.compile(r'\d+h\s*às\s*\d+h', re.IGNORECASE)
            for li in all_li:
                text = (li.inner_text() or "").strip()
                if pattern.search(text):
                    periodos.append(li)
            if periodos:
                return periodos
        except Exception as e:
            logger.debug("[PAP] _etapa7_obter_lista_periodos (regex): %s", e)
        # Fallback: li com Manhã ou Tarde
        periodos = self.page.query_selector_all('li:has-text("Manhã"), li:has-text("Tarde")')
        if periodos:
            return periodos
        return self.page.query_selector_all('li:has-text("às")')

    def etapa7_selecionar_periodo(self, indice: int) -> Tuple[bool, str]:
        """Seleciona o período pelo índice. NÃO clica em Agendar (apenas seleciona o turno)."""
        try:
            periodos = self._etapa7_obter_lista_periodos()
            if indice < 1 or indice > len(periodos):
                return False, f"Período {indice} inválido."
            periodos[indice - 1].click()
            self.page.wait_for_timeout(500)
            return True, "Período selecionado. (Botão Agendar não acionado.)"
        except Exception as e:
            logger.error(f"[PAP] etapa7_selecionar_periodo: {e}")
            return False, str(e)

    def etapa7_clicar_agendar(self) -> Tuple[bool, str]:
        """
        Clica em Agendar e aguarda o modal "Agendado para" aparecer.
        O número do pedido NÃO está neste modal - aparece depois de clicar Continuar.
        Returns: (sucesso, mensagem)
        """
        try:
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=5000)
            except Exception:
                pass
            btn = self.page.query_selector('button:has-text("Agendar")')
            if not btn:
                return False, "Botão Agendar não encontrado."
            try:
                btn.click(force=True, timeout=5000)
            except Exception:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const ag = btns.find(x => x.textContent && x.textContent.includes('Agendar'));
                    if (ag) ag.click();
                }""")
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_selector('h3:has-text("Agendado para")', state="visible", timeout=12000)
            self.page.wait_for_timeout(500)
            return True, "Modal de confirmação exibido."
        except Exception as e:
            logger.error(f"[PAP] etapa7_clicar_agendar: {e}")
            return False, str(e)

    def etapa7_modal_clicar_continuar(self) -> Tuple[bool, str, Optional[str]]:
        """
        Clica em Continuar no modal "Agendado para", aguarda o modal "Sucesso!",
        extrai o número da OS e clica em Ok.
        Returns: (sucesso, mensagem, numero_pedido)
        """
        try:
            btn = self.page.query_selector('button:has-text("Continuar")')
            if not btn:
                return False, "Botão Continuar não encontrado no modal.", None
            try:
                btn.click(force=True, timeout=5000)
            except Exception:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const c = btns.find(x => x.textContent && x.textContent.includes('Continuar'));
                    if (c) c.click();
                }""")
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.page.wait_for_timeout(1500)
            # Aguarda o modal "Sucesso!"
            try:
                self.page.wait_for_selector('h3:has-text("Sucesso!")', state="visible", timeout=15000)
            except Exception:
                pass
            self.page.wait_for_timeout(500)
            # Extrai o número da OS do span "Concluída a abertura da OS número XXXX, pedido salvo"
            numero_os = None
            span = self.page.query_selector('span:has-text("Concluída a abertura")')
            if span:
                texto = span.inner_text() or ""
                m = re.search(r'OS número (\d+)[,\s]+pedido salvo', texto, re.I)
                if m:
                    numero_os = m.group(1)
            if not numero_os:
                pagina = self.page.content()
                m = re.search(r'Concluída a abertura da OS número (\d+)[,\s]*pedido salvo', pagina, re.I)
                if m:
                    numero_os = m.group(1)
            if numero_os:
                self.dados_pedido['numero_pedido_agendamento'] = numero_os
                self.dados_pedido['numero_os'] = numero_os
                self.numero_pedido = numero_os
            # Clica em Ok para fechar o modal
            btn_ok = self.page.query_selector('button:has-text("Ok")')
            if btn_ok:
                try:
                    btn_ok.click(force=True, timeout=3000)
                except Exception:
                    self.page.evaluate("""() => {
                        const btns = [...document.querySelectorAll('button')];
                        const ok = btns.find(x => x.textContent && x.textContent.trim() === 'Ok');
                        if (ok) ok.click();
                    }""")
            self.page.wait_for_timeout(1000)
            if numero_os:
                return True, f"Agendamento realizado! Número do pedido: {numero_os}", numero_os
            return True, "Agendamento realizado! (Número do pedido não identificado.)", None
        except Exception as e:
            logger.error(f"[PAP] etapa7_modal_clicar_continuar: {e}")
            return False, str(e), None

    def etapa7_modal_fechar(self) -> Tuple[bool, str]:
        """
        Fecha o modal "Agendado para" clicando no X.
        Retorna para a tela de calendário para o usuário alterar data/turno.
        """
        try:
            for sel in [
                'button:has(img.img)',
                'button:has(img[alt=""])',
                '[aria-label="Fechar"]',
                '[aria-label="Close"]',
                'button[class*="close"]',
                '[class*="modal"] button:has(svg)',
                '[class*="Modal"] button:has(svg)',
            ]:
                btn = self.page.query_selector(sel)
                if btn:
                    try:
                        btn.click(force=True, timeout=3000)
                        self.page.wait_for_timeout(1000)
                        return True, "Modal fechado."
                    except Exception:
                        continue
            self.page.evaluate("""() => {
                const modal = document.querySelector('h3');
                if (modal && modal.textContent && modal.textContent.includes('Agendado')) {
                    const container = modal.closest('[class*="modal"], [class*="Modal"], [role="dialog"]') || modal.closest('div');
                    const btns = container ? container.querySelectorAll('button, [role="button"]') : [];
                    const xBtn = [...btns].find(b => {
                        const txt = (b.textContent || '').trim();
                        const hasSvg = b.querySelector('svg') || b.querySelector('img');
                        return hasSvg && !txt.includes('Continuar') && txt.length < 5;
                    });
                    if (xBtn) xBtn.click();
                }
            }""")
            self.page.wait_for_timeout(1000)
            return True, "Modal fechado."
        except Exception as e:
            logger.error(f"[PAP] etapa7_modal_fechar: {e}")
            return False, str(e)

    def etapa7_abrir_os(self, data_agendamento: str = None, turno: str = 'manha') -> Tuple[bool, str, Optional[str]]:
        """
        Etapa 7: Abrir O.S. e agendar instalação.
        
        Args:
            data_agendamento: Data no formato DD/MM/YYYY (se None, usa primeira disponível)
            turno: 'manha' ou 'tarde'
            
        Returns:
            Tuple (sucesso, mensagem, numero_os)
        """
        try:
            logger.info(f"[PAP] Etapa 7 - Abrindo O.S. Data: {data_agendamento}, Turno: {turno}")
            
            # Clicar em Abrir OS
            btn_abrir_os = self.page.query_selector('button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])')
            if btn_abrir_os:
                btn_abrir_os.click()
                self.page.wait_for_selector('button:has-text("Confirmar"), [class*="calendario"], [class*="calendar"]', state="visible", timeout=10000)
            else:
                return False, "Botão Abrir O.S. não disponível. Verifique a biometria.", None
            
            # Se data específica foi informada, tentar encontrar
            if data_agendamento:
                data_elem = self.page.query_selector(f'[data-date="{data_agendamento}"], :has-text("{data_agendamento}")')
                if data_elem:
                    data_elem.click()
            else:
                # Clicar na primeira data disponível
                data_disponivel = self.page.query_selector(SELETORES['etapa7']['data_disponivel'])
                if data_disponivel:
                    data_disponivel.click()
            
            # Selecionar turno
            turno_selector = SELETORES['etapa7']['turno_manha'] if turno.lower() == 'manha' else SELETORES['etapa7']['turno_tarde']
            turno_elem = self.page.query_selector(turno_selector)
            if turno_elem:
                turno_elem.click()
            
            # Confirmar e aguardar conclusão
            btn_confirmar = self.page.query_selector('button:has-text("Confirmar"):not([disabled])')
            if btn_confirmar:
                btn_confirmar.click()
                # Aguardar página de sucesso ou número da OS
                self.page.wait_for_load_state("networkidle", timeout=15000)
            
            # Extrair número da O.S.
            pagina_texto = self.page.content()
            
            # Procurar padrões de número de pedido/OS
            padrao_os = re.search(r'(\d{15,20})', pagina_texto)
            padrao_pedido = re.search(r'Pedido[:\s]*(\d+)', pagina_texto, re.IGNORECASE)
            
            numero_os = None
            if padrao_os:
                numero_os = padrao_os.group(1)
            elif padrao_pedido:
                numero_os = padrao_pedido.group(1)
            
            if numero_os:
                self.etapa_atual = 7
                self.numero_pedido = numero_os
                self.dados_pedido['numero_os'] = numero_os
                self.dados_pedido['data_agendamento'] = data_agendamento
                self.dados_pedido['turno'] = turno
                return True, f"🎉 VENDA CONCLUÍDA!\n\nNúmero do Pedido: {numero_os}", numero_os
            else:
                # Verificar se houve sucesso mesmo sem extrair número
                if 'sucesso' in pagina_texto.lower() or 'concluído' in pagina_texto.lower():
                    return True, "Venda concluída! Número do pedido não identificado.", None
                return False, "Não foi possível confirmar a abertura da O.S.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 7: {e}")
            return False, f"Erro na Etapa 7: {str(e)}", None
    
    def _clicar_sair(self) -> bool:
        """Clica em Sair para fazer logout. Usa force e JS se overlay interceptar."""
        try:
            if not self.page:
                return False
            sair = self.page.query_selector('#sair, p#sair, [id="sair"]')
            if sair:
                try:
                    sair.click(force=True, timeout=3000)
                except Exception:
                    self.page.evaluate("""() => {
                        const el = document.querySelector('#sair, p#sair, [id="sair"]');
                        if (el) el.click();
                    }""")
                self.page.wait_for_timeout(1500)
                return True
            return False
        except Exception as e:
            logger.warning(f"[PAP] Erro ao clicar Sair: {e}")
            return False

    def _fechar_sessao(self, *, fazer_logout: bool = False):
        """
        Fecha o navegador e libera recursos.

        Por padrão NÃO clica em Sair: reaproveita cookies no próximo run
        (login repetido no IdP V.tal pode bloquear a conta). Relogin limpo
        (_relogin_pap) só ocorre quando a sessão realmente expirou.
        Use fazer_logout=True apenas quando for obrigatório encerrar no PAP.
        """
        tinha_sessao = self.sessao_iniciada
        try:
            if not tinha_sessao:
                return
            # Salvar trace antes de fechar (permite ver cada clique no https://trace.playwright.dev)
            if getattr(self, '_trace_started', False) and self.context:
                try:
                    from django.conf import settings as _st
                    base_dir = getattr(_st, 'BASE_DIR', None)
                    if base_dir:
                        downloads_dir = os.path.join(base_dir, 'downloads')
                        os.makedirs(downloads_dir, exist_ok=True)
                        safe_run = str(self.run_id).replace(os.sep, '_').replace('..', '_')[:50]
                        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                        trace_path = os.path.join(downloads_dir, f"pap_trace_{safe_run}_{ts}.zip")
                        self.context.tracing.stop(path=trace_path)
                        logger.info(f"[PAP] Trace salvo: {os.path.basename(trace_path)} (abrir em https://trace.playwright.dev)")
                except Exception as e:
                    logger.warning(f"[PAP] Erro ao salvar trace: {e}")
                self._trace_started = False
            fez_logout = False
            if fazer_logout and self.page:
                fez_logout = bool(self._clicar_sair())
            if self.context:
                if fez_logout:
                    # Após Sair, cookies ficam inválidos — não persistir.
                    self._invalidar_storage_state()
                elif self._sessao_pap_autenticada():
                    try:
                        self.context.storage_state(path=self.storage_state_path)
                        logger.info(
                            "[PAP] Storage state preservado para reuso: %s",
                            os.path.basename(self.storage_state_path),
                        )
                    except Exception as e:
                        logger.debug("[PAP] Salvar storage no fechamento: %s", e)
                else:
                    # Sessão já caída no IdP: storage antigo só atrapalha o próximo run.
                    self._invalidar_storage_state()

            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
                self.playwright = None
        except Exception as e:
            logger.error(f"[PAP] Erro ao fechar sessão: {e}")
        finally:
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
                self.playwright = None
            if self._pap_slot_held:
                try:
                    _pap_semaphore.release()
                except ValueError:
                    pass
                self._pap_slot_held = False
            self.sessao_iniciada = False
            if tinha_sessao or self.vendedor_nome:
                logger.info(f"[PAP] Sessão encerrada para {self.vendedor_nome}")
    
    def __del__(self):
        """Destrutor para garantir limpeza de recursos"""
        if self.sessao_iniciada:
            self._fechar_sessao()


# =============================================================================
# GERENCIADOR DE SESSÕES DE VENDA VIA WHATSAPP
# =============================================================================

# Cache de sessões ativas (por telefone do vendedor)
_sessoes_venda: Dict[str, Dict] = {}
_sessoes_lock = threading.Lock()


def obter_sessao_venda(telefone: str) -> Optional[Dict]:
    """Obtém a sessão de venda ativa para um telefone"""
    with _sessoes_lock:
        return _sessoes_venda.get(telefone)


def criar_sessao_venda(telefone: str, usuario_id: int, dados: Dict) -> Dict:
    """Cria uma nova sessão de venda"""
    with _sessoes_lock:
        _sessoes_venda[telefone] = {
            'usuario_id': usuario_id,
            'etapa': 'inicio',
            'dados': dados,
            'automacao': None,
            'criado_em': datetime.now(),
            'atualizado_em': datetime.now(),
        }
        return _sessoes_venda[telefone]


def atualizar_sessao_venda(telefone: str, etapa: str = None, dados: Dict = None, automacao: Any = None):
    """Atualiza uma sessão de venda existente"""
    with _sessoes_lock:
        if telefone in _sessoes_venda:
            if etapa:
                _sessoes_venda[telefone]['etapa'] = etapa
            if dados:
                _sessoes_venda[telefone]['dados'].update(dados)
            if automacao is not None:
                _sessoes_venda[telefone]['automacao'] = automacao
            _sessoes_venda[telefone]['atualizado_em'] = datetime.now()


def encerrar_sessao_venda(telefone: str):
    """Encerra uma sessão de venda"""
    with _sessoes_lock:
        if telefone in _sessoes_venda:
            sessao = _sessoes_venda[telefone]
            if sessao.get('automacao'):
                try:
                    sessao['automacao']._fechar_sessao()
                except:
                    pass
            del _sessoes_venda[telefone]


def limpar_sessoes_expiradas(timeout_minutos: int = 30):
    """Remove sessões que expiraram"""
    with _sessoes_lock:
        agora = datetime.now()
        expiradas = []
        for telefone, sessao in _sessoes_venda.items():
            delta = (agora - sessao['atualizado_em']).total_seconds() / 60
            if delta > timeout_minutos:
                expiradas.append(telefone)
        
        for telefone in expiradas:
            if _sessoes_venda[telefone].get('automacao'):
                try:
                    _sessoes_venda[telefone]['automacao']._fechar_sessao()
                except:
                    pass
            del _sessoes_venda[telefone]
            logger.info(f"[PAP] Sessão expirada removida: {telefone}")
