# scripts/testar_lead_login.py
"""
Teste local do login e fluxo de criação de Lead no site Comercial Blink (automação Lead).
Abre o navegador VISÍVEL e executa os cliques passo a passo para você acompanhar.

=== DESENHO DOS CLIQUES (passo a passo) ===
  --- LOGIN ---
  0. Abrir URL: https://blinktelecom.my.site.com/comercial/login
  1. Preencher usuário (input#username): recordpap@gmail.com
  2. Preencher senha (input#password): Alpap123
  3. Clicar botão "Fazer login" (input#Login)
  4. Aguardar redirecionamento

  --- PÓS-LOGIN (criar lead) ---
  5. Clicar em "Leads" (span com texto Leads)
  6. Clicar em "Criar" (a.forceActionLink title="Criar")
  7. Modal: manter "Blink Fibra" selecionado; clicar "Avançar" (span.label.bBody)
  8. Formulário (dados virão do usuário via WhatsApp no futuro):
     - Primeiro Nome (input[name="firstName"] / #input-110)
     - Sobrenome (input[name="lastName"] / #input-112)
     - Tratamento: manter "nenhum" (não pedir ao usuário)
     - Telefone celular com DDD (input[name="MobilePhone"] / #input-150)
     - CPF (input[name="CPF__c"] / #input-209)
     - Canal de atendimento: selecionar "Externo" (combobox, sempre fixo)
     - CEP (input combobox "Pesquisar endereço" / #combobox-input-347) -> escolher da lista
     - Número da fachada (input[name="Numero__c"] / #input-306)
  9. Clicar "Salvar e criar" (button[name="SaveAndNew"])

Tratamento de erros:
  - Se o endereço (CEP) não for selecionado: mensagem "O endereço não foi selecionado."
  - Se aparecer "Encontramos um obstáculo." na página: extrair mensagem, fechar diálogo e informar que o lead não foi criado.

Uso:
    cd c:\\site-record
    python scripts/testar_lead_login.py              # execução normal
    python scripts/testar_lead_login.py --passo-a-passo   # pausa antes de cada passo (mapear seletores)

Requisito: playwright instalado (pip install playwright && playwright install chromium)
"""
import time
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Instale o Playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

# Configuração do login (altere se quiser testar com outros dados)
URL_LOGIN = "https://blinktelecom.my.site.com/comercial/login"
USUARIO = "recordpap@gmail.com"
SENHA = "Alpap123"

# Dados de teste para o formulário do lead (em produção vêm do usuário via WhatsApp)
PRIMEIRO_NOME = "João"
SOBRENOME = "Silva Santos"
TELEFONE_DDD = "11987654321"
CPF_CLIENTE = "12345678909"  # 11 dígitos
CEP = "01310100"  # Exemplo SP
NUMERO_FACHADA = "100"

# Seletores - Login
SELETOR_USUARIO = "input#username"
SELETOR_USUARIO_FALLBACK = "input[name='username'], input[type='email'], input[placeholder*='sername'], input[placeholder*='mail']"
SELETOR_SENHA = "input#password"
SELETOR_SENHA_FALLBACK = "input[name='pw'], input[type='password']"
SELETOR_BOTAO_LOGIN = "input#Login"
SELETOR_BOTAO_FALLBACK = "input[type='submit'][value='Fazer login'], button[type='submit']"

# Seletores - Pós-login (Leads, Criar, Modal, Formulário)
SELETOR_LEADS = "span:has-text('Leads')"
SELETOR_CRIAR = "a.forceActionLink[title='Criar'], a[title='Criar']"
SELETOR_AVANCAR_MODAL = "span.label.bBody:has-text('Avançar'), span:has-text('Avançar')"
SELETOR_PRIMEIRO_NOME = "input[name='firstName']"
SELETOR_PRIMEIRO_NOME_FB = "input#input-110, input[placeholder='Primeiro Nome']"
SELETOR_SOBRENOME = "input[name='lastName']"
SELETOR_SOBRENOME_FB = "input#input-112, input[placeholder='Sobrenome']"
SELETOR_TELEFONE = "input[name='MobilePhone']"
SELETOR_TELEFONE_FB = "input#input-150"
SELETOR_CPF = "input[name='CPF__c']"
SELETOR_CPF_FB = "input#input-209"
SELETOR_CANAL_ATENDIMENTO = "button[aria-label='Canal de atendimento'], button#combobox-button-235"
SELETOR_OPCAO_EXTERNO = "[role='listbox'] [role='option']:has-text('Externo'), li:has-text('Externo'), [data-value='Externo']"
# CEP: combobox de endereço (LWC id dinâmico, ex: combobox-input-362)
# Usar APENAS seletores que identifiquem o campo de endereço (evitar outro combobox com "Search...")
SELETOR_CEP = "input[placeholder='Pesquisar endereço'], input[aria-label='Pesquisa de endereço']"
SELETOR_CEP_FB = "input[id^='combobox-input-'][placeholder='Pesquisar endereço']"
SELETOR_CEP_COMBO = "input[id^='combobox-input-'][aria-label='Pesquisa de endereço']"
# Não usar input[role='combobox'] sozinho: pega o primeiro combobox da página (ex: Search)
SELETOR_OPCAO_ENDERECO = "[role='listbox'] [role='option'], [id^='dropdown-element-'] li, ul[role='listbox'] li"
SELETOR_NUMERO_FACHADA = "input[name='Numero__c']"
SELETOR_NUMERO_FACHADA_FB = "input#input-306"
SELETOR_SALVAR_CRIAR = "button[name='SaveAndNew']"
SELETOR_SALVAR_CRIAR_FB = "button:has-text('Salvar e criar')"

# Campos de endereço (preenchidos ao selecionar CEP) - para verificar se endereço foi selecionado
SELETOR_RUA = "textarea[name='street'], input[name='street']"
SELETOR_CEP_PREENCHIDO = "input[name='postalCode']"
SELETOR_CIDADE = "input[name='city']"

# --- Pós-criação do lead: fluxo até Consultar Serasa ---
SELETOR_BOTAO_FECHAR_MODAL = "button[title='Cancelar e fechar'], button.slds-modal__close"
# CEP: dentro da seção "Buscar CEP" para não confundir com campo Número (que também pode ter maxlength)
SELETOR_CEP_BUSCAR = "input[maxlength='8'][pattern='[0-9]{8}']"
SELETOR_BOTAO_BUSCAR = "button:has-text('Buscar')"
# Número da fachada: usar label "Número" para não preencher o campo CEP
SELETOR_NUMERO_FACHADA_2 = "input[id^='input-'][type='text']"
SELETOR_SALVAR = "button:has-text('Salvar'), span.label.bBody:has-text('Salvar')"
SELETOR_MARCAR_STATUS_CONCLUIDO = "span:has-text('Marcar Status como concluído(a)')"
SELETOR_AVANCAR = "button:has-text('Avançar')"
SELETOR_RELACIONADO = "span.title:has-text('Relacionado')"
SELETOR_ADICIONAR_PRODUTOS = "div[title='Adicionar produtos'], div:has-text('Adicionar produtos')"
SELETOR_MODAL_CATALOGO = "h1:has-text('Selecionar catálogo de preços')"
SELETOR_MODAL_ADICIONAR_PRODUTOS = "h2:has-text('Adicionar Produtos')"
PRODUTO_NOME = "600 Mega - Sócio Torcedor América"
SELETOR_CHECKBOX_PRODUTO = "span.slds-checkbox--faux, span.slds-checkbox_faux"
SELETOR_MODAL_EDITAR_PRODUTOS = "h2:has-text('Editar Produtos selecionados')"
SELETOR_QUANTIDADE = "input[role='spinbutton'], input#input-991"
SELETOR_MARCAR_FASE_CONCLUIDO = "span:has-text('Marcar Fase como concluído(a)')"
SELETOR_CONSULTAR_SERASA = "button:has-text('Consultar Serasa'), button[name='Opportunity.Consultar_Serasa_v2']"
SELETOR_MODAL_SERASA = "h2:has-text('Consultar Serasa')"
SELETOR_RESULTADO_SERASA = "p:has-text('Consulta realizada com sucesso')"
SELETOR_CONCLUIR = "button:has-text('Concluir')"


def verificar_endereco_preenchido(page, timeout_espera: float = 1.5) -> bool:
    """
    Verifica se, após digitar CEP e tentar selecionar, os campos de endereço foram preenchidos.
    Retorna True se pelo menos um deles (Rua, Cidade ou CEP) tiver valor.
    """
    time.sleep(timeout_espera)
    try:
        el_cep = page.query_selector(SELETOR_CEP_PREENCHIDO)
        if el_cep:
            v = el_cep.input_value() or ""
            if v.strip():
                return True
        el_rua = page.query_selector(SELETOR_RUA)
        if el_rua:
            v = el_rua.input_value() if hasattr(el_rua, "input_value") else ""
            if v and str(v).strip():
                return True
        el_cidade = page.query_selector(SELETOR_CIDADE)
        if el_cidade:
            v = el_cidade.input_value() or ""
            if v.strip():
                return True
    except Exception:
        pass
    return False


def verificar_erro_obstaculo(page) -> tuple:
    """
    Verifica se na página aparece o diálogo ou banner 'Encontramos um obstáculo.' (Salesforce).
    O erro pode vir como dialog separado ou como banner dentro do modal do formulário (h2 + detalhe).
    Retorna (True, mensagem_erro) se encontrar; (False, None) caso contrário.
    """
    try:
        # 1) Diálogo separado (role=dialog com o título)
        dialog = page.get_by_role("dialog", name="Encontramos um obstáculo.")
        if dialog.count() > 0 and dialog.first.is_visible():
            msg = "Encontramos um obstáculo."
            try:
                listas = page.locator("ul.errorsList.slds-list_dotted li, .pageLevelErrors ul li")
                if listas.count() > 0:
                    msg = listas.first.inner_text().strip() or msg
            except Exception:
                pass
            return (True, msg)

        # 2) Texto "Encontramos um obstáculo." em qualquer lugar (ex.: h2 no banner dentro do modal)
        loc_obst = page.get_by_text("Encontramos um obstáculo.", exact=False)
        if loc_obst.count() > 0 and loc_obst.first.is_visible():
            msg = "Encontramos um obstáculo."
            try:
                # Detalhe no mesmo bloco: "Já existe um lead com esse telefone" ou "Revise os erros"
                for detail in ["Já existe um lead com esse telefone", "Revise os erros nesta página", "já existe um lead com esse telefone"]:
                    d = page.get_by_text(detail, exact=False)
                    if d.count() > 0 and d.first.is_visible():
                        msg = d.first.inner_text().strip()
                        break
                if msg == "Encontramos um obstáculo.":
                    # Tentar pegar texto de lista de erros perto do título
                    listas = page.locator("ul.errorsList.slds-list_dotted li, .pageLevelErrors ul li, [class*='slds-theme_error'] li, [class*='error'] li")
                    for i in range(min(listas.count(), 3)):
                        t = listas.nth(i).inner_text().strip()
                        if t and len(t) > 10:
                            msg = t
                            break
            except Exception:
                pass
            return (True, msg)

        # 3) Só a mensagem de telefone duplicado (às vezes aparece sem o título "Encontramos um obstáculo.")
        dup = page.get_by_text("Já existe um lead com esse telefone", exact=False)
        if dup.count() > 0 and dup.first.is_visible():
            try:
                return (True, dup.first.inner_text().strip())
            except Exception:
                return (True, "Já existe um lead com esse telefone.")
    except Exception:
        pass
    return (False, None)


def fechar_dialogo_erro(page) -> None:
    """Tenta fechar o diálogo de erro (botão Fechar ou X)."""
    try:
        btn = page.get_by_role("button", name="Fechar caixa de diálogo de erro")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            time.sleep(0.5)
            return
        close = page.locator("button[title*='Fechar'], .slds-popover__close button").first
        if close.is_visible():
            close.click()
            time.sleep(0.5)
    except Exception:
        pass


def is_erro_telefone_duplicado(msg_erro: str) -> bool:
    """Verifica se a mensagem de obstáculo é 'já existe um lead com esse telefone'."""
    if not msg_erro:
        return False
    msg = msg_erro.lower().strip()
    return ("já existe" in msg and "telefone" in msg) or "lead com esse telefone" in msg


def log(msg: str) -> None:
    print(f"  [LEAD] {msg}")


def fechar_modal_localizacao(page) -> None:
    """
    Fecha apenas o modal do navegador 'Saber sua localização' (geolocalização),
    clicando em 'Nunca permitir' ou no X **dentro desse modal**. Não toca no modal
    'Criar lead' (evita fechar o formulário por engano).
    """
    try:
        # Escopo: só o modal que contém "Saber sua localização" (não o modal do lead)
        modal_loc = page.locator("[role='dialog'], div").filter(has_text="Saber sua localização").first
        if modal_loc.count() == 0:
            return
        modal_loc.wait_for(state="visible", timeout=2000)
        # Dentro desse modal apenas: "Nunca permitir" ou X
        btn = modal_loc.get_by_role("button", name="Nunca permitir")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click(timeout=2000)
            log("Modal de localização fechado (Nunca permitir).")
            time.sleep(0.5)
            return
        btn = modal_loc.get_by_text("Nunca permitir", exact=False).first
        if btn.is_visible():
            btn.click(timeout=2000)
            log("Modal de localização fechado (Nunca permitir).")
            time.sleep(0.5)
            return
        # X apenas dentro do modal de localização (não o do lead)
        x_btn = modal_loc.locator("button[aria-label*='echar'], button[title*='echar'], button").first
        if x_btn.is_visible():
            x_btn.click(timeout=2000)
            log("Modal de localização fechado (X).")
            time.sleep(0.5)
    except Exception:
        pass


def passo_clique(page, seletor: str, descricao: str, fallback: str = None, timeout: int = 10000) -> bool:
    """Aguarda elemento, clica e registra. Retorna True se ok."""
    try:
        el = page.wait_for_selector(seletor, timeout=timeout)
        if el:
            log(f"Clique: {descricao} (seletor: {seletor})")
            el.click()
            time.sleep(0.5)
            return True
    except Exception as e:
        log(f"Seletor principal falhou: {seletor} -> {e}")
    if fallback:
        try:
            el = page.wait_for_selector(fallback, timeout=3000)
            if el:
                log(f"Clique (fallback): {descricao} (seletor: {fallback})")
                el.click()
                time.sleep(0.5)
                return True
        except Exception as e2:
            log(f"Fallback falhou: {fallback} -> {e2}")
    return False


def passo_preencher(page, seletor: str, valor: str, descricao: str, fallback: str = None, timeout: int = 10000) -> bool:
    """Preenche campo e registra. Retorna True se ok."""
    try:
        el = page.wait_for_selector(seletor, timeout=timeout)
        if el:
            log(f"Preencher: {descricao} -> '{valor}' (seletor: {seletor})")
            el.click()
            time.sleep(0.2)
            el.fill("")
            el.fill(valor)
            time.sleep(0.3)
            return True
    except Exception as e:
        log(f"Seletor principal falhou: {seletor} -> {e}")
    if fallback:
        try:
            el = page.wait_for_selector(fallback, timeout=3000)
            if el:
                log(f"Preencher (fallback): {descricao} (seletor: {fallback})")
                el.click()
                time.sleep(0.2)
                el.fill("")
                el.fill(valor)
                time.sleep(0.3)
                return True
        except Exception as e2:
            log(f"Fallback falhou: {fallback} -> {e2}")
    return False


def passo_clique_por_texto(page, texto: str, descricao: str, timeout: int = 10000) -> bool:
    """Clica em elemento que contém o texto (ex.: 'Leads', 'Avançar')."""
    try:
        el = page.get_by_text(texto, exact=False).first
        el.wait_for(state="visible", timeout=timeout)
        log(f"Clique (por texto): {descricao} -> '{texto}'")
        el.click()
        time.sleep(0.5)
        return True
    except Exception as e:
        log(f"Clique por texto '{texto}' falhou: {e}")
    return False


def main():
    print("\n=== Teste de login LEAD (Comercial Blink - criação de Lead) ===\n")
    print(f"URL: {URL_LOGIN}")
    print(f"Usuário: {USUARIO}")
    print("Senha: ******")
    print("\nNavegador abrindo em modo VISÍVEL. Acompanhe os cliques.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
            permissions=[],  # não conceder geolocalização; evita prompt "Saber sua localização"
        )
        page = context.new_page()

        try:
            log("Abrindo página de login...")
            page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            log("Passo 1: Preencher usuário (email)")
            ok_user = passo_preencher(
                page,
                SELETOR_USUARIO,
                USUARIO,
                "Campo Username / Email",
                fallback=SELETOR_USUARIO_FALLBACK,
            )
            if not ok_user:
                print("\n[ERRO] Não foi possível encontrar o campo de usuário.")
                time.sleep(30)
                return

            time.sleep(0.8)

            log("Passo 2: Preencher senha")
            ok_pw = passo_preencher(
                page,
                SELETOR_SENHA,
                SENHA,
                "Campo Senha",
                fallback=SELETOR_SENHA_FALLBACK,
            )
            if not ok_pw:
                print("\n[ERRO] Não foi possível encontrar o campo de senha.")
                time.sleep(30)
                return

            time.sleep(0.8)

            log("Passo 3: Clicar em 'Fazer login'")
            ok_btn = passo_clique(
                page,
                SELETOR_BOTAO_LOGIN,
                "Botão Fazer login",
                fallback=SELETOR_BOTAO_FALLBACK,
            )
            if not ok_btn:
                print("\n[ERRO] Não foi possível encontrar o botão de login.")
                time.sleep(30)
                return

            log("Aguardando página pós-login (Bem vindo Blinker!)...")
            try:
                page.get_by_text("Bem vindo Blinker!", exact=False).first.wait_for(state="visible", timeout=20000)
                log("Página pronta para interação.")
            except Exception:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
            time.sleep(0.5)
            log(f"URL atual: {page.url}")

            log("Passo 5: Clicar em 'Leads'")
            if not passo_clique(page, SELETOR_LEADS, "Menu Leads") and not passo_clique_por_texto(page, "Leads", "Menu Leads"):
                if not passo_clique_por_texto(page, "Leads", "Menu Leads"):
                    print("[ERRO] Não foi possível clicar em Leads.")
                    time.sleep(30)
                    return
            time.sleep(2)

            log("Passo 6: Clicar em 'Criar'")
            if not passo_clique(page, SELETOR_CRIAR, "Botão Criar") and not passo_clique_por_texto(page, "Criar", "Botão Criar"):
                print("[ERRO] Não encontrou 'Criar'.")
                time.sleep(30)
                return
            time.sleep(2)

            log("Passo 7: Modal - clicar 'Avançar' (manter Blink Fibra)")
            if not passo_clique(page, SELETOR_AVANCAR_MODAL, "Botão Avançar") and not passo_clique_por_texto(page, "Avançar", "Botão Avançar"):
                print("[ERRO] Não encontrou 'Avançar'.")
                time.sleep(30)
                return
            time.sleep(1)

            # Modal do formulário "Novo Lead" pode demorar a abrir; esperar o campo Primeiro Nome ficar visível
            log("Aguardando formulário do lead (modal pode demorar a abrir)...")
            form_visivel = False
            try:
                page.locator(SELETOR_PRIMEIRO_NOME).first.wait_for(state="visible", timeout=20000)
                form_visivel = True
                log("Formulário do lead visível.")
            except Exception:
                try:
                    page.locator(SELETOR_PRIMEIRO_NOME_FB).first.wait_for(state="visible", timeout=5000)
                    form_visivel = True
                    log("Formulário do lead visível (fallback).")
                except Exception:
                    try:
                        page.get_by_label("Primeiro Nome", exact=False).first.wait_for(state="visible", timeout=5000)
                        form_visivel = True
                        log("Formulário do lead visível (por label).")
                    except Exception:
                        try:
                            page.get_by_placeholder("Primeiro Nome", exact=False).first.wait_for(state="visible", timeout=5000)
                            form_visivel = True
                            log("Formulário do lead visível (por placeholder).")
                        except Exception:
                            log("Aguardando formulário: timeout; tentando preencher mesmo assim.")
            time.sleep(0.5)

            log("Passo 8: Preencher formulário do lead (dados de teste)")

            if not passo_preencher(page, SELETOR_PRIMEIRO_NOME, PRIMEIRO_NOME, "Primeiro Nome", fallback=SELETOR_PRIMEIRO_NOME_FB):
                print("[ERRO] Campo Primeiro Nome não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            if not passo_preencher(page, SELETOR_SOBRENOME, SOBRENOME, "Sobrenome", fallback=SELETOR_SOBRENOME_FB):
                print("[ERRO] Campo Sobrenome não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            if not passo_preencher(page, SELETOR_TELEFONE, TELEFONE_DDD, "Telefone (DDD + celular)", fallback=SELETOR_TELEFONE_FB):
                print("[ERRO] Campo Telefone não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            if not passo_preencher(page, SELETOR_CPF, CPF_CLIENTE, "CPF", fallback=SELETOR_CPF_FB):
                print("[ERRO] Campo CPF não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            log("Passo 8b: Canal de atendimento -> Externo")
            try:
                btn_canal = page.wait_for_selector(SELETOR_CANAL_ATENDIMENTO, timeout=5000)
                if btn_canal:
                    btn_canal.click()
                    time.sleep(1)
                    opt = page.locator(SELETOR_OPCAO_EXTERNO).first
                    if opt.count() > 0:
                        opt.click()
                        log("Selecionado 'Externo' no canal de atendimento")
                    else:
                        page.keyboard.press("Escape")
            except Exception as ex:
                log(f"Canal (Externo) não encontrado ou já selecionado: {ex}")
            time.sleep(0.5)

            fechar_modal_localizacao(page)
            time.sleep(0.5)

            log("Passo 8c: CEP - preencher e selecionar sugestão de endereço")
            # NÃO pressionar Escape aqui: no Salesforce o Escape fecha o modal "Criar lead".
            # Dar tempo para o bloco de endereço do formulário renderizar (LWC pode carregar depois)
            time.sleep(1)
            cep_locator = None
            timeout_cep = 10000
            # 1) get_by_placeholder perfura Shadow DOM (LWC); tentar na página inteira primeiro
            try:
                loc = page.get_by_placeholder("Pesquisar endereço", exact=True)
                loc.first.wait_for(state="visible", timeout=timeout_cep)
                if loc.first.is_visible():
                    cep_locator = loc.first
                    log("Campo CEP encontrado via: get_by_placeholder('Pesquisar endereço')")
            except Exception:
                pass
            if not cep_locator:
                try:
                    loc = page.get_by_placeholder("Pesquisar endereço", exact=False)
                    if loc.count() > 0:
                        loc.first.wait_for(state="visible", timeout=timeout_cep)
                        if loc.first.is_visible():
                            cep_locator = loc.first
                            log("Campo CEP encontrado via: get_by_placeholder (partial)")
                except Exception:
                    pass
            if not cep_locator:
                try:
                    loc = page.get_by_label("Pesquisa de endereço", exact=False)
                    if loc.count() > 0:
                        loc.first.wait_for(state="visible", timeout=timeout_cep)
                        if loc.first.is_visible():
                            cep_locator = loc.first
                            log("Campo CEP encontrado via: get_by_label('Pesquisa de endereço')")
                except Exception:
                    pass
            if not cep_locator:
                for desc, seletor in [
                    ("placeholder/aria-label", "input[placeholder='Pesquisar endereço'], input[aria-label='Pesquisa de endereço']"),
                    ("combobox+placeholder", "input[id^='combobox-input-'][placeholder='Pesquisar endereço']"),
                    ("placeholder contains", "input[placeholder*='endereço']"),
                ]:
                    try:
                        loc = page.locator(seletor).first
                        loc.wait_for(state="visible", timeout=5000)
                        if loc.is_visible():
                            cep_locator = loc
                            log(f"Campo CEP encontrado via: {desc}")
                            break
                    except Exception:
                        pass
            if not cep_locator:
                try:
                    modal = page.locator(".slds-modal__container, .modal-container").first
                    loc = modal.locator("input[placeholder='Pesquisar endereço'], input[aria-label='Pesquisa de endereço'], input[placeholder*='endereço']").first
                    loc.wait_for(state="visible", timeout=5000)
                    if loc.is_visible():
                        cep_locator = loc
                        log("Campo CEP encontrado via: dentro do modal")
                except Exception:
                    pass
            if cep_locator:
                try:
                    cep_locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                time.sleep(0.3)
                try:
                    cep_locator.click()
                    time.sleep(0.2)
                    cep_locator.fill(CEP)
                except Exception:
                    try:
                        cep_locator.click(force=True)
                        time.sleep(0.2)
                        cep_locator.fill(CEP)
                    except Exception as e:
                        log(f"Falha ao preencher CEP: {e}")
                        cep_locator = None
                if cep_locator:
                    log(f"CEP digitado: {CEP}; aguardando lista de sugestões...")
                    # Esperar a lista de endereços aparecer antes de selecionar (primeira interação)
                    listbox_ok = False
                    for _ in range(15):
                        time.sleep(0.5)
                        try:
                            lb = page.locator("[role='listbox']").first
                            if lb.count() > 0 and lb.is_visible():
                                listbox_ok = True
                                log("Lista de endereços visível.")
                                break
                        except Exception:
                            pass
                        try:
                            if page.get_by_text(CEP[:5], exact=False).first.is_visible():
                                listbox_ok = True
                                log("Sugestão de CEP visível.")
                                break
                        except Exception:
                            pass
                    if not listbox_ok:
                        log("Lista não apareceu em 7.5s; tentando selecionar mesmo assim.")
                    time.sleep(0.3)
                    page.keyboard.press("ArrowDown")
                    time.sleep(0.3)
                    page.keyboard.press("Enter")
                    log("Teclado: ArrowDown + Enter (selecionar primeira sugestão)")
                    # Clicar na sugestão por texto como reforço (primeira interação)
                    cep_formatado = f"{CEP[:5]}-{CEP[5:]}" if len(CEP) >= 8 else CEP
                    try:
                        sug = page.get_by_text(cep_formatado, exact=False).first
                        sug.wait_for(state="visible", timeout=2000)
                        if sug.is_visible():
                            sug.click()
                            log("Sugestão selecionada (clique no CEP)")
                            time.sleep(0.5)
                    except Exception:
                        pass
                    # Garantir que endereço foi aplicado antes de seguir: esperar campos rua/CEP/cidade
                    for tentativa in range(10):
                        if verificar_endereco_preenchido(page, timeout_espera=0.5):
                            log("Endereço confirmado no formulário.")
                            break
                        time.sleep(0.6)
                    else:
                        log("[AVISO] Campos de endereço podem não ter sido preenchidos.")
            else:
                log("[AVISO] Campo CEP não encontrado.")
            time.sleep(1)

            if not cep_locator:
                print("\n[ERRO] Campo CEP não encontrado. O lead NÃO será salvo sem endereço.")
                time.sleep(30)
                browser.close()
                return

            # Tratamento de erro 1: endereço não selecionado
            if not verificar_endereco_preenchido(page):
                print("\n[ERRO] O endereço não foi selecionado. Selecione uma sugestão da lista após digitar o CEP.")
                time.sleep(30)
                browser.close()
                return

            if not passo_preencher(page, SELETOR_NUMERO_FACHADA, NUMERO_FACHADA, "Número da fachada", fallback=SELETOR_NUMERO_FACHADA_FB):
                print("[ERRO] Campo Número fachada não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.8)

            log("Passo 9: Clicar 'Salvar e criar'")
            if not passo_clique(page, SELETOR_SALVAR_CRIAR, "Salvar e criar", fallback=SELETOR_SALVAR_CRIAR_FB) and not passo_clique_por_texto(page, "Salvar e criar", "Salvar e criar"):
                print("[ERRO] Botão 'Salvar e criar' não encontrado.")
                time.sleep(30)
                return

            # Dar tempo para a resposta do servidor e o banner de erro (ex.: "Encontramos um obstáculo.") aparecer
            time.sleep(4)
            tem_obstaculo, msg_erro = verificar_erro_obstaculo(page)
            if not tem_obstaculo:
                # Rechecar após mais 2s (erro pode vir com atraso no modal)
                time.sleep(2)
                tem_obstaculo, msg_erro = verificar_erro_obstaculo(page)
            if not tem_obstaculo:
                time.sleep(1)
                tem_obstaculo, msg_erro = verificar_erro_obstaculo(page)

            # Tratamento de erro 2: "Encontramos um obstáculo."
            if tem_obstaculo:
                lead_criado_com_retry = False
                # Caso especial: telefone já cadastrado -> pedir outro número e tentar de novo
                if is_erro_telefone_duplicado(msg_erro):
                    fechar_dialogo_erro(page)
                    time.sleep(0.8)
                    tentativas = 0
                    max_tentativas = 20
                    while tentativas < max_tentativas:
                        print("\n  [LEAD] Já existe um lead com esse telefone.")
                        print(f"  Detalhe: {msg_erro}")
                        try:
                            novo = input("  Digite outro número (DDD + celular, ex: 11987654322) ou Enter para encerrar: ").strip()
                        except (KeyboardInterrupt, EOFError):
                            print("\nEncerrado.")
                            break
                        if not novo:
                            print("  Encerrando sem criar lead.")
                            break
                        if len(novo) < 10 or not novo.isdigit():
                            print("  Número inválido. Use apenas dígitos (ex: 11987654322).")
                            continue
                        log(f"Alterando telefone para {novo} e tentando salvar novamente...")
                        fechar_dialogo_erro(page)
                        time.sleep(0.3)
                        if not passo_preencher(page, SELETOR_TELEFONE, novo, "Telefone (novo)", fallback=SELETOR_TELEFONE_FB):
                            log("Campo telefone não encontrado após fechar diálogo.")
                            break
                        time.sleep(0.5)
                        if not passo_clique(page, SELETOR_SALVAR_CRIAR, "Salvar e criar", fallback=SELETOR_SALVAR_CRIAR_FB) and not passo_clique_por_texto(page, "Salvar e criar", "Salvar e criar"):
                            log("Botão Salvar e criar não encontrado.")
                            break
                        time.sleep(2)
                        tem_obstaculo, msg_erro = verificar_erro_obstaculo(page)
                        if not tem_obstaculo:
                            lead_criado_com_retry = True
                            log("Lead criado com o novo número.")
                            break
                        if not is_erro_telefone_duplicado(msg_erro):
                            print("\n[ERRO] Encontramos um obstáculo. O lead NÃO foi criado.")
                            print(f"Detalhe: {msg_erro}")
                            fechar_dialogo_erro(page)
                            break
                        tentativas += 1
                    else:
                        print("\n  Limite de tentativas atingido.")
                    if not lead_criado_com_retry:
                        time.sleep(30)
                        browser.close()
                        return
                else:
                    # Outro tipo de obstáculo
                    print("\n[ERRO] Encontramos um obstáculo. O lead NÃO foi criado.")
                    print(f"Detalhe: {msg_erro}")
                    fechar_dialogo_erro(page)
                    print("\nNavegador permanecerá aberto por 30 segundos.")
                    time.sleep(30)
                    browser.close()
                    print("\nFim do teste (lead não criado).")
                    return

            log(f"URL final: {page.url}")

            # --- Aguardar tela pronta: máscara de loading some e, se o modal "Novo lead" aparecer, fechar ---
            try:
                # 1) Esperar a máscara de loading sumir (evita clique interceptado)
                mask = page.locator("div.siteforceSpinnerManager .mask, div.mask").first
                mask.wait_for(state="hidden", timeout=15000)
                log("Máscara de loading sumiu.")
            except Exception:
                log("Aguardando máscara de loading: timeout (seguindo mesmo assim).")
            time.sleep(2)  # Dar tempo para o modal "Novo lead" aparecer (ele pode vir com atraso)

            # --- Fluxo pós-lead: fechar modal, CEP/Buscar, fachada, Salvar, status, avançar, relacionado, produtos, Serasa ---
            nome_cliente = f"{PRIMEIRO_NOME} {SOBRENOME}"
            try:
                log("Passo 10: Fechar modal (Cancelar e fechar)")
                # Esperar o modal "Novo lead" aparecer (até 5s); se aparecer, fechar
                modal_novo_lead = page.get_by_role("dialog").filter(has_text="Novo lead").first
                try:
                    modal_novo_lead.wait_for(state="visible", timeout=5000)
                except Exception:
                    pass
                if modal_novo_lead.is_visible():
                    # Garantir que a máscara não está bloqueando o clique
                    try:
                        page.locator("div.mask").first.wait_for(state="hidden", timeout=5000)
                    except Exception:
                        pass
                    page.locator(SELETOR_BOTAO_FECHAR_MODAL).first.click(timeout=5000)
                    time.sleep(1.5)
                    log("Modal fechado.")
                else:
                    log("Modal 'Novo lead' não apareceu; pulando fechamento.")
            except Exception as e:
                log(f"Fechar modal: {e}")

            # Validar que estamos na tela do lead (seção Buscar CEP visível) antes de CEP/Número
            try:
                # Esperar a página do lead: entity "Lead" e/ou seção "Buscar CEP"
                page.get_by_text("Lead", exact=True).first.wait_for(state="visible", timeout=15000)
                log("Tela do lead (entity Lead) visível.")
            except Exception:
                pass
            try:
                page.locator("div, section").filter(has_text="Buscar CEP").first.wait_for(state="visible", timeout=15000)
                log("Seção Buscar CEP visível.")
            except Exception as e:
                log(f"Aviso: seção Buscar CEP não visível: {e}")

            try:
                log("Passo 11: Preencher CEP (campo Buscar CEP) e clicar Buscar")
                # Usar label 'CEP' ou escopo 'Buscar CEP' para NÃO preencher o campo Número por engano
                cep_input = None
                try:
                    cep_input = page.get_by_label("CEP", exact=False).first
                    cep_input.wait_for(state="visible", timeout=5000)
                except Exception:
                    pass
                if not cep_input or not cep_input.is_visible():
                    secao = page.locator("div, section").filter(has_text="Buscar CEP").first
                    cep_input = secao.locator("input[maxlength='8']").first
                    cep_input.wait_for(state="visible", timeout=5000)
                cep_input.fill(CEP)
                time.sleep(0.3)
                page.locator(SELETOR_BOTAO_BUSCAR).first.click(timeout=5000)
                # Aguardar o endereço carregar e o campo Número ficar habilitado (LWC pode demorar)
                time.sleep(3)
            except Exception as e:
                log(f"CEP/Buscar: {e}")

            try:
                log("Passo 12: Preencher Número (fachada) e Salvar")
                # Escopo: só a seção de endereço (Buscar CEP / Logradouro) para o campo Número da fachada.
                secao_endereco = page.locator("div, section").filter(has_text="Buscar CEP").filter(has_text="Logradouro").first
                secao_endereco.wait_for(state="visible", timeout=8000)
                num_input = None
                # 1) Por label "Número" dentro da seção (evita dropdown de telefones)
                try:
                    num_input = secao_endereco.get_by_label("Número", exact=False).first
                    num_input.wait_for(state="visible", timeout=3000)
                    if num_input.is_disabled():
                        num_input = None
                except Exception:
                    num_input = None
                # 2) Célula da tabela que contém "Número:" e o input (estrutura c-busca-c-e-p)
                if not num_input or not num_input.is_visible():
                    try:
                        num_input = secao_endereco.locator("td").filter(has_text="Número").locator("input[type='text']").first
                        num_input.wait_for(state="visible", timeout=3000)
                    except Exception:
                        num_input = None
                # 3) Primeiro input type=text sem maxlength=8 e não desabilitado (ordem: Número, Complemento)
                if not num_input or not num_input.is_visible():
                    try:
                        num_input = secao_endereco.locator("input.slds-input[type='text']:not([maxlength='8'])").first
                        num_input.wait_for(state="visible", timeout=3000)
                    except Exception:
                        num_input = secao_endereco.locator("input[type='text']:not([maxlength='8'])").first
                        num_input.wait_for(state="visible", timeout=3000)
                if num_input:
                    # Garantir que está habilitado (após Buscar CEP o LWC pode demorar a habilitar)
                    for _ in range(10):
                        try:
                            if not num_input.is_disabled():
                                break
                            time.sleep(1)
                        except Exception:
                            time.sleep(1)
                    try:
                        num_input.wait_for(state="visible", timeout=2000)
                        num_input.fill(NUMERO_FACHADA)
                        time.sleep(0.5)
                        page.locator(SELETOR_SALVAR).first.click(timeout=5000)
                        time.sleep(2)
                        log("Número da fachada preenchido e Salvar clicado.")
                    except Exception as fill_err:
                        log(f"Número fachada/Salvar: {fill_err}")
                else:
                    log("Número fachada/Salvar: campo Número não encontrado na seção de endereço.")
            except Exception as e:
                log(f"Número fachada/Salvar: {e}")

            try:
                log("Passo 13: Marcar Status como concluído(a)")
                page.get_by_text("Marcar Status como concluído(a)", exact=False).first.click(timeout=5000)
                time.sleep(1.5)
            except Exception as e:
                log(f"Marcar Status: {e}")

            try:
                log("Passo 14: Clicar Avançar")
                page.locator(SELETOR_AVANCAR).first.click(timeout=5000)
                time.sleep(2)
            except Exception as e:
                log(f"Avançar: {e}")

            try:
                log("Passo 15: Clicar Relacionado")
                page.get_by_text("Relacionado", exact=False).first.click(timeout=5000)
                time.sleep(1.5)
            except Exception as e:
                log(f"Relacionado: {e}")

            try:
                log(f"Passo 16: Clicar na oportunidade (nome do cliente: {nome_cliente})")
                page.get_by_role("link", name=nome_cliente).first.click(timeout=8000)
                time.sleep(2)
            except Exception as e:
                log(f"Link oportunidade: {e}")

            try:
                log("Passo 17: Clicar em Relacionado (novamente)")
                page.get_by_text("Relacionado", exact=False).first.click(timeout=5000)
                time.sleep(1.5)
            except Exception as e:
                log(f"Relacionado 2: {e}")

            try:
                log("Passo 18: Adicionar produtos")
                page.get_by_text("Adicionar produtos", exact=False).first.click(timeout=5000)
                time.sleep(2)
            except Exception as e:
                log(f"Adicionar produtos: {e}")

            try:
                log("Passo 19: Modal catálogo - clicar Salvar")
                page.get_by_text("Selecionar catálogo de preços", exact=False).first.wait_for(state="visible", timeout=5000)
                page.get_by_text("Salvar", exact=False).first.click(timeout=5000)
                time.sleep(2)
            except Exception as e:
                log(f"Modal catálogo: {e}")

            try:
                log("Passo 20: Modal Adicionar Produtos - selecionar produto")
                page.get_by_text("Adicionar Produtos", exact=False).first.wait_for(state="visible", timeout=8000)
                time.sleep(1)
                row = page.locator("tr").filter(has_text=PRODUTO_NOME).first
                row.wait_for(state="visible", timeout=5000)
                row.locator(SELETOR_CHECKBOX_PRODUTO).first.click(timeout=3000)
                time.sleep(0.5)
                page.get_by_text("Avançar", exact=False).first.click(timeout=5000)
                time.sleep(2)
            except Exception as e:
                try:
                    page.get_by_text(PRODUTO_NOME, exact=False).first.click(timeout=3000)
                    time.sleep(0.5)
                    page.get_by_text("Avançar", exact=False).first.click(timeout=5000)
                    time.sleep(2)
                except Exception as e2:
                    log(f"Selecionar produto (fallback): {e2}")

            try:
                log("Passo 21: Editar Produtos - Quantidade 1 e Salvar")
                page.get_by_text("Editar Produtos selecionados", exact=False).first.wait_for(state="visible", timeout=8000)
                qtd = page.locator(SELETOR_QUANTIDADE).first
                qtd.wait_for(state="visible", timeout=5000)
                qtd.fill("1")
                time.sleep(0.5)
                page.get_by_text("Salvar", exact=False).first.click(timeout=5000)
                time.sleep(2)
            except Exception as e:
                log(f"Editar quantidade: {e}")

            try:
                log("Passo 22: Marcar Fase como concluído(a)")
                page.get_by_text("Marcar Fase como concluído(a)", exact=False).first.click(timeout=5000)
                time.sleep(1.5)
            except Exception as e:
                log(f"Marcar Fase: {e}")

            try:
                log("Passo 23: Consultar Serasa")
                page.locator(SELETOR_CONSULTAR_SERASA).first.click(timeout=5000)
                time.sleep(3)
            except Exception as e:
                log(f"Consultar Serasa: {e}")

            resultado_serasa = None
            try:
                log("Passo 24: Ler resultado da consulta Serasa")
                page.get_by_text("Consultar Serasa", exact=False).first.wait_for(state="visible", timeout=8000)
                par = page.locator(SELETOR_RESULTADO_SERASA).first
                par.wait_for(state="visible", timeout=5000)
                texto = par.inner_text()
                resultado_serasa = "APROVADO" if "aprovado" in texto.lower() and "não" not in texto.lower() else "REPROVADO"
                log(f"Resultado Serasa: {texto.strip()} -> {resultado_serasa}")
            except Exception as e:
                log(f"Ler resultado Serasa: {e}")

            try:
                log("Passo 25: Concluir (fechar modal Serasa)")
                page.locator(SELETOR_CONCLUIR).first.click(timeout=5000)
                time.sleep(1.5)
            except Exception as e:
                log(f"Concluir: {e}")

            if resultado_serasa:
                print(f"\n--- Fluxo concluído. Resultado consulta Serasa: {resultado_serasa} ---")
            else:
                print("\n--- Fluxo concluído. Verifique a tela. ---")
            print("Navegador permanecerá aberto por 60 segundos para você inspecionar.")
            time.sleep(60)

        except Exception as e:
            print(f"\n[ERRO] {e}")
            import traceback
            traceback.print_exc()
            time.sleep(30)
        finally:
            browser.close()

    print("\nFim do teste.")


if __name__ == "__main__":
    main()
