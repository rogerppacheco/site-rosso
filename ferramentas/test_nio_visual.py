"""
Script para testar API Nio COM NAVEGADOR VISÍVEL e PASSO A PASSO
"""
import os
import sys
sys.path.insert(0, 'C:/site-record')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

import json
import time
from playwright.sync_api import sync_playwright

# Configurações
CPF = '12886868620'
SITE_URL = "https://negociacao.niointernet.com.br"
PARAMS_URL = f"{SITE_URL}/negociar/params"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

print('='*80)
print('🌐 TESTE VISUAL DA API NIO - NAVEGADOR ABERTO')
print('='*80)
print(f'\n📋 CPF: {CPF}')
print('⏱️  O navegador ficará aberto para você acompanhar...\n')
time.sleep(2)

try:
    with sync_playwright() as p:
        print('🚀 PASSO 1: Iniciando navegador Chromium...')
        browser = p.chromium.launch(
            headless=False,  # NAVEGADOR VISÍVEL
            slow_mo=1000     # Atraso de 1s entre ações para visualizar
        )
        
        print('📄 PASSO 2: Criando contexto do navegador...')
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        
        print(f'🌍 PASSO 3: Abrindo página: {SITE_URL}')
        page = context.new_page()
        page.goto(SITE_URL, wait_until="networkidle", timeout=30000)
        print('✅ Página carregada!')
        time.sleep(3)
        
        print('\n🔑 PASSO 4: Buscando token no localStorage...')
        try:
            ls = page.evaluate(
                "() => ({ token: localStorage.getItem('token'), apiServerUrl: localStorage.getItem('apiServerUrl') })"
            )
            if ls and ls.get("token"):
                print(f'✅ Token encontrado no localStorage!')
                print(f'   Token (primeiros 50): {ls["token"][:50]}...')
                print(f'   API URL: {ls["apiServerUrl"]}')
                token = ls["token"]
                api_url = ls["apiServerUrl"]
            else:
                print('⚠️ Token não encontrado no localStorage')
                token = None
                api_url = None
        except Exception as e:
            print(f'❌ Erro ao ler localStorage: {e}')
            token = None
            api_url = None
        
        if not token:
            print('\n🔄 PASSO 5: Tentando buscar via /negociar/params...')
            try:
                resp = context.request.get(
                    PARAMS_URL,
                    headers={
                        "Accept": "text/plain, */*;q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                        "User-Agent": UA,
                        "Referer": SITE_URL,
                    },
                    timeout=30000,
                )
                print(f'📡 Status da resposta: {resp.status}')
                if resp.status == 200:
                    enc = resp.text()
                    print(f'✅ Recebido: {enc[:100]}...')
                    # Aqui precisaríamos descriptografar se necessário
                else:
                    print(f'❌ Falha na requisição: status {resp.status}')
            except Exception as e:
                print(f'❌ Erro na requisição: {e}')
        
        if token and api_url:
            print(f'\n🔐 PASSO 6: Obtendo Session ID...')
            import requests
            session = requests.Session()
            session_url = api_url.rstrip("/") + "/authentication/sessionId"
            headers = {"Accept": "application/json", "Authorization": token}
            
            resp = session.get(session_url, headers=headers, timeout=20)
            print(f'📡 Status: {resp.status_code}')
            
            if resp.status_code == 200:
                session_data = resp.json()
                session_id = session_data.get("token")
                print(f'✅ Session ID obtido!')
                print(f'   Session (primeiros 50): {session_id[:50]}...')
                
                print(f'\n💳 PASSO 7: Consultando dívidas do CPF {CPF}...')
                debts_url = api_url.rstrip("/") + f"/debts/customers/{CPF}?offset=0&limit=10&origin=nio"
                headers = {
                    "Accept": "application/json",
                    "Authorization": token,
                    "Session-Id": session_id,
                }
                
                resp = session.get(debts_url, headers=headers, timeout=30)
                print(f'📡 Status: {resp.status_code}')
                
                if resp.status_code == 200:
                    data = resp.json()
                    print('\n✅ RESPOSTA DA API:')
                    print('='*80)
                    print(json.dumps(data, indent=2, ensure_ascii=False))
                    print('='*80)
                    
                    # Análise das faturas
                    debts = data.get('debts', [])
                    print(f'\n📊 Total de dívidas: {len(debts)}')
                    
                    for i, debt in enumerate(debts, 1):
                        print(f'\n--- DÍVIDA {i} ---')
                        print(f'Produto: {debt.get("productName")}')
                        print(f'Origin: {debt.get("origin")}')
                        print(f'Deal Code: {debt.get("dealCode")}')
                        
                        invoices = debt.get('invoices', [])
                        print(f'Faturas: {len(invoices)}')
                        
                        for j, inv in enumerate(invoices, 1):
                            print(f'\n  FATURA {j}:')
                            print(f'    Valor: R$ {inv.get("amount")}')
                            print(f'    Vencimento: {inv.get("dueDate")}')
                            print(f'    Expiração: {inv.get("expirationDate")}')
                            print(f'    Status: {inv.get("status")}')
                            print(f'    Cód. Barras: {inv.get("barCode")}')
                            pix = inv.get("originalPixCode") or inv.get("pixCode") or ""
                            print(f'    PIX (primeiros 80): {pix[:80]}...')
                else:
                    print(f'❌ Erro na consulta: {resp.status_code}')
                    print(f'   Resposta: {resp.text[:200]}')
        
        print('\n\n⏸️  NAVEGADOR FICARÁ ABERTO POR 30 SEGUNDOS PARA VOCÊ EXPLORAR...')
        print('   Pressione Ctrl+C para fechar antes se desejar.\n')
        
        for i in range(30, 0, -5):
            print(f'   Fechando em {i} segundos...')
            time.sleep(5)
        
        print('\n🔒 Fechando navegador...')
        browser.close()
        print('✅ Teste concluído!')

except KeyboardInterrupt:
    print('\n\n⚠️ Interrompido pelo usuário.')
except Exception as e:
    print(f'\n\n❌ ERRO: {e}')
    import traceback
    traceback.print_exc()

print('\n' + '='*80)
print('FIM DO TESTE')
print('='*80)
