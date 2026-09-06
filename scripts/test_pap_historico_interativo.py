"""Script interativo para testar o Histórico PAP com navegador visível (headless=False).

Uso:
  python scripts/test_pap_historico_interativo.py
  ou
  python scripts/test_pap_historico_interativo.py --matricula 12345 --senha minhasenha
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

# Configurar path do projeto e Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-12345")
os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    import django
    django.setup()
except Exception as e:
    print(f"[AVISO] Django setup parcial: {e}")

from playwright.sync_api import sync_playwright

from crm_app.historico_pap import (
    PAP_HISTORICO_URL,
    extrair_lista_api,
    map_pedido_api,
    montar_url_vendas,
    montar_xlsx_historico,
    STATUS_LISTA_PADRAO,
)
from crm_app.historico_pap_service import (
    JS_TOKEN,
    _fetch_json_http,
    _headers_auth,
    salvar_token_cache,
    validar_e_decodificar_jwt,
)


def main():
    parser = argparse.ArgumentParser(description="Teste interativo do Histórico PAP com navegador visível.")
    parser.add_argument("--matricula", help="Matrícula do PAP", default="")
    parser.add_argument("--senha", help="Senha do PAP", default="")
    parser.add_argument("--token", help="Bearer Token direto (se já tiver copiado)", default="")
    parser.add_argument("--dias", type=int, help="Quantos dias retroativos buscar", default=7)
    args = parser.parse_args()

    matricula = args.matricula.strip()
    senha = args.senha.strip()
    token_manual = args.token.strip()

    # Se já passou token manual, testa direto via HTTP sem abrir browser
    if token_manual:
        print("\n>>> [1/3] Validando Token Manual informado...")
        ok, pay, clean = validar_e_decodificar_jwt(token_manual)
        if not ok:
            print(f"[ERRO] Token inválido: {clean}")
            return
        print(f"[OK] Token JWT válido! Subject={pay.get('sub')}, Expira em={pay.get('exp')}")
        testar_api_http(clean, args.dias)
        return

    print("\n==================================================================")
    print("      TESTE INTERATIVO DO HISTÓRICO PAP COM NAVEGADOR ABERTO      ")
    print("==================================================================")

    sessions_dir = os.path.join(os.getcwd(), "pap_sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    session_file = os.path.join(sessions_dir, f"pap_session_{matricula or 'atual'}.json")

    tem_sessao_salva = os.path.exists(session_file)

    with sync_playwright() as p:
        print("[INFO] Abrindo Chromium na tela (headless=False)...")
        browser = p.chromium.launch(
            headless=False,
            slow_mo=100,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context_opts = {
            "viewport": {"width": 1366, "height": 768},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if tem_sessao_salva:
            print(f"[INFO] Carregando cookies da sessão existente: {session_file}")
            context_opts["storage_state"] = session_file

        context = browser.new_context(**context_opts)
        page = context.new_page()

        # Ocultar indicador de automação contra WAF
        try:
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception:
            pass

        token_capturado = {"auth": ""}

        def on_req(r):
            try:
                h = r.headers.get("authorization") or r.headers.get("Authorization") or ""
                if h:
                    val = h[7:].strip() if h.lower().startswith("bearer ") else h.strip()
                    if val.startswith("eyJ") and "." in val:
                        token_capturado["auth"] = val
            except Exception:
                pass

        page.on("request", on_req)

        # 1. Navegar para o PAP (direto ao Histórico se já temos sessão salva)
        url_inicial = PAP_HISTORICO_URL if tem_sessao_salva else "https://pap.niointernet.com.br/"
        print(f"\n>>> [1/4] Acessando {url_inicial} ...", flush=True)
        page.goto(url_inicial, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        # 2. Verificar se precisa logar
        url_atual = page.url or ""
        print(f"[INFO] URL atual após carregamento inicial: {url_atual}", flush=True)

        jwt_token = ""
        # Verificar se já temos token (ex: sessão reaproveitada)
        for _ in range(5):
            tok_candidato = token_capturado["auth"] or page.evaluate(JS_TOKEN)
            if tok_candidato:
                ok, pay, clean = validar_e_decodificar_jwt(tok_candidato)
                if ok:
                    jwt_token = clean
                    print(f"[OK] Sessão ativa reconhecida! Usuário: {pay.get('sub')}", flush=True)
                    break
            page.wait_for_timeout(1000)

        if not jwt_token:
            if matricula and senha:
                print(f"[INFO] Preenchendo credenciais automáticas para matrícula {matricula}...")
                try:
                    page.wait_for_selector(
                        '#inputMatricula, input[placeholder*="Login"], input[name*="matricula"], input[type="text"]',
                        state="visible",
                        timeout=10000,
                    )
                    for sel in ['#inputMatricula', 'input[placeholder*="Login"]', 'input[name*="matricula"]', 'input[name*="username"]', 'input[type="text"]']:
                        try:
                            page.fill(sel, matricula, timeout=2000)
                            break
                        except Exception:
                            pass

                    for sel in ['#passwordInput', 'input[type="password"]', 'input[placeholder*="Senha"]']:
                        try:
                            page.fill(sel, senha, timeout=2000)
                            break
                        except Exception:
                            pass

                    print("[INFO] Clicando no botão de login...")
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
                    ]:
                        try:
                            page.click(sel_btn, timeout=2000)
                            clicou = True
                            break
                        except Exception:
                            pass
                    if not clicou:
                        page.keyboard.press("Enter")

                    page.wait_for_timeout(3000)
                    conteudo = (page.content() or "").lower()
                    if "login failed" in conteudo or "senha inválida" in conteudo or "bloquead" in conteudo or "falhou" in conteudo:
                        print("\n[ERRO CRÍTICO] Falha de autenticação detectada na tela da V.tal!")
                        print("[SEGURANÇA] Parando a execução para evitar tentativas repetidas e bloqueio da conta.")
                        return
                except Exception as e:
                    print(f"[AVISO] Preenchimento automático: {e}")
            else:
                print("\n" + "=" * 65)
                print("[>>>] POR FAVOR, FAÇA SEU LOGIN DIRETAMENTE NO NAVEGADOR ABERTO")
                print("      (O script aguarda você logar e detectará o sucesso automaticamente)")
                print("=" * 65 + "\n")

            print("[INFO] Aguardando você concluir o login no navegador aberto (tempo: até 10 minutos)...")
            tempo_limite = time.time() + 600
            last_msg = time.time()
            while time.time() < tempo_limite:
                try:
                    if page.is_closed():
                        print("[AVISO] O navegador foi fechado.")
                        return

                    # 1. Verificar se token JWT já chegou por rede
                    if token_capturado["auth"]:
                        ok, pay, clean = validar_e_decodificar_jwt(token_capturado["auth"])
                        if ok:
                            jwt_token = clean
                            print("\n[OK] Login concluído! Token JWT interceptado da rede!")
                            break

                    # 2. Verificar se token JWT está no localStorage/sessionStorage
                    tok_ls = page.evaluate(JS_TOKEN)
                    if tok_ls:
                        ok, pay, clean = validar_e_decodificar_jwt(tok_ls)
                        if ok:
                            jwt_token = clean
                            print("\n[OK] Login concluído! Token JWT obtido do armazenamento da página!")
                            break

                    # 3. Verificar se a URL saiu da tela de login e já está no sistema PAP
                    u = page.url or ""
                    if (
                        "pap.niointernet.com.br" in u
                        and "login" not in u.lower()
                        and "vtal.com" not in u.lower()
                        and "identidade" not in u.lower()
                        and "nidp" not in u.lower()
                    ):
                        # Já estamos dentro do PAP! Pode navegar para o Histórico para disparar os requests
                        print("\n[OK] Login concluído! Página principal do PAP detectada.")
                        break

                except Exception:
                    pass

                if time.time() - last_msg >= 15:
                    segundos_restantes = int(tempo_limite - time.time())
                    minutos = segundos_restantes // 60
                    seg = segundos_restantes % 60
                    print(f"[INFO] Aguardando você realizar o login no navegador aberto... ({minutos}m {seg:02d}s restantes)")
                    last_msg = time.time()

            if not jwt_token:
                u = page.url or ""
                if "pap.niointernet.com.br" not in u or "login" in u.lower() or "vtal" in u.lower():
                    print("\n[ERRO] Tempo limite esgotado sem conclusão do login no navegador.")
                    return

        # Salvar estado da sessão atualizada
        try:
            context.storage_state(path=session_file)
            atual_file = os.path.join(sessions_dir, "pap_session_atual.json")
            if session_file != atual_file:
                context.storage_state(path=atual_file)
            print(f"[OK] Sessão salva em: {session_file}")
        except Exception as e:
            print(f"[AVISO] Falha ao salvar storage state: {e}")

        # 3. Navegar até o Histórico
        print("\n>>> [2/4] Navegando para o Histórico Administrativo...")
        page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        # 4. Extrair Token da página se ainda não tínhamos
        print("\n>>> [3/4] Extraindo Bearer Token JWT...")
        if not jwt_token:
            for _ in range(15):
                if token_capturado["auth"]:
                    ok, pay, clean = validar_e_decodificar_jwt(token_capturado["auth"])
                    if ok:
                        jwt_token = clean
                        print("[OK] Token capturado diretamente do cabeçalho de rede da SPA!")
                        break
                tok_ls = page.evaluate(JS_TOKEN)
                if tok_ls:
                    ok, pay, clean = validar_e_decodificar_jwt(tok_ls)
                    if ok:
                        jwt_token = clean
                        print("[OK] Token capturado do localStorage da página!")
                        break
                page.wait_for_timeout(1000)

        if not jwt_token:
            print("[ERRO] Não foi possível extrair um token JWT válido.")
            print("Chaves no localStorage:", page.evaluate("() => Object.keys(localStorage)"))
            return

        ok, pay, clean = validar_e_decodificar_jwt(jwt_token)
        if not ok:
            print(f"[ERRO] Token extraído é inválido: {clean}")
            return

        print(f"\n[SUCESSO] Token JWT autenticado!")
        print(f"  - Subject: {pay.get('sub')}")
        if pay.get('exp'):
            dt_exp = datetime.fromtimestamp(float(pay['exp'])).strftime('%d/%m/%Y %H:%M:%S')
            print(f"  - Expira em: {dt_exp}")

        salvar_token_cache(matricula, clean, pay.get("exp"))

        # 5. Testar a API de busca de vendas
        print("\n>>> [4/4] Testando consulta à API do Histórico PAP...")
        testar_api(clean, args.dias, page=page)

        print("\n[CONCLUÍDO] Teste finalizado! Navegador permanecerá aberto por 60 segundos (ou feche a janela quando desejar)...")
        for _ in range(60):
            try:
                if page.is_closed():
                    break
                page.wait_for_timeout(1000)
            except Exception:
                break


def testar_api(token: str, dias: int = 7, page=None):
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    data_ini = f"{inicio.isoformat()}T00:00:00-03:00"
    data_fim = f"{hoje.isoformat()}T23:59:59-03:00"

    tipos = ["VENDA", "INTERESSE", "PRE_VENDA"]
    headers = _headers_auth(token)
    total_encontrados = 0
    linhas_excel = []

    for tipo in tipos:
        tipo_api = "INTERESSE_SALVO" if tipo == "INTERESSE" else tipo
        status_filtro = "PRE_VENDA" if tipo == "PRE_VENDA" else ("MINHAS_PENDENCIAS" if tipo == "INTERESSE" else STATUS_LISTA_PADRAO)
        url = montar_url_vendas(
            data_inicio=data_ini,
            data_fim=data_fim,
            pdv="",
            tipo_api=tipo_api,
            page=1,
            limit=15,
            status=status_filtro,
        )
        print(f"\n[GET] Consultando tipo: {tipo} ({inicio} até {hoje})...")
        if page:
            from crm_app.historico_pap_service import _fetch_json
            resp = _fetch_json(page, url, token=token)
        else:
            resp = _fetch_json_http(url, headers)

        if not resp.get("ok"):
            print(f"  [FALHA] HTTP {resp.get('status')}: {resp.get('error')} - Preview: {resp.get('preview')}")
            continue

        lista, total = extrair_lista_api(resp.get("json"))
        print(f"  [OK] Sucesso! Total retornado na API: {total} registros (Página 1: {len(lista)} itens)")
        total_encontrados += total

        for item in lista:
            linhas_excel.append(map_pedido_api(item, tipo))
            if len(linhas_excel) <= 3:
                print(f"    - Pedido: {item.get('numeroPedido')} | Cliente: {item.get('cliente')} | Status: {item.get('status')}")

    if linhas_excel:
        xlsx_bytes = montar_xlsx_historico(linhas_excel)
        nome_arquivo = f"teste_historico_{hoje}.xlsx"
        with open(nome_arquivo, "wb") as f:
            f.write(xlsx_bytes)
        print(f"\n[SUCESSO COMPLETO] Planilha gerada com sucesso: {nome_arquivo} ({len(linhas_excel)} linhas, {len(xlsx_bytes)} bytes)")
    else:
        print(f"\n[INFO] Nenhum pedido retornado no período de {inicio} a {hoje} (ou base vazia para os filtros).")


if __name__ == "__main__":
    main()
