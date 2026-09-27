"""
Script para SIMULAR HUMANO navegando no site da Nio
COM CLIQUES E DIGITAÇÃO VISÍVEIS
"""
import os
import sys
sys.path.insert(0, 'C:/site-bn')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

import time
from playwright.sync_api import sync_playwright

# Configurações
CPF = '12886868620'
SITE_URL = "https://negociacao.niointernet.com.br"

print('='*80)
print('👤 SIMULANDO NAVEGAÇÃO HUMANA NO SITE DA NIO')
print('='*80)
print(f'\n📋 CPF a consultar: {CPF}')
print('⏱️  Navegador ficará aberto com cliques lentos para visualizar...\n')
time.sleep(2)

try:
    with sync_playwright() as p:
        print('🚀 Iniciando navegador visível...')
        browser = p.chromium.launch(
            headless=False,
            slow_mo=500  # 500ms de delay entre cada ação
        )
        
        print('📄 Criando contexto...')
        # Carrega cookies salvos se existirem
        state_path = os.path.join(os.path.dirname(__file__), '.playwright_state.json')
        storage_state = None
        if os.path.exists(state_path):
            print(f'✅ Carregando cookies salvos de: {state_path}')
            storage_state = state_path
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
            storage_state=storage_state
        )
        
        page = context.new_page()
        
        print(f'\n🌍 PASSO 1: Navegando para {SITE_URL}')
        page.goto(SITE_URL, wait_until="networkidle", timeout=30000)
        print('✅ Página carregada!')
        time.sleep(3)
        
        print('\n🔍 PASSO 2: Procurando campo de CPF/CNPJ...')
        # Tenta encontrar campo de input para CPF
        try:
            # Possíveis seletores para o campo de CPF
            selectors_cpf = [
                'input[placeholder*="CPF"]',
                'input[placeholder*="CNPJ"]',
                'input[name*="cpf"]',
                'input[name*="document"]',
                'input[id*="cpf"]',
                'input[type="text"]'
            ]
            
            campo_cpf = None
            for selector in selectors_cpf:
                try:
                    if page.locator(selector).count() > 0:
                        campo_cpf = page.locator(selector).first
                        print(f'✅ Campo encontrado com seletor: {selector}')
                        break
                except:
                    continue
            
            if campo_cpf:
                print(f'⌨️  PASSO 3: Digitando CPF {CPF} no campo...')
                campo_cpf.click()
                time.sleep(1)
                campo_cpf.fill(CPF)
                print('✅ CPF digitado!')
                time.sleep(2)
                
                print('\n' + '='*80)
                print('🔐 VERIFICAÇÃO DE RECAPTCHA')
                print('='*80)
                print('\n👀 Veja o navegador - pode aparecer reCAPTCHA')
                print('✅ Se aparecer, resolva agora no navegador')
                print('⏸️  Esperando confirmação...\n')
                
                confirmacao = input('>>> Digite SIM quando reCAPTCHA estiver OK (ou já não aparecer) >>> ').strip().upper()
                
                if confirmacao != 'SIM':
                    print('\n⚠️  Digite SIM para continuar:')
                    confirmacao = input('>>> SIM >>> ').strip().upper()
                
                if confirmacao == 'SIM':
                    print('\n✅ Prosseguindo com a consulta...')
                    time.sleep(1)
                else:
                    print('\n❌ Cancelado.')
                    raise Exception('Usuário não confirmou')
                
                print('\n🔍 PASSO 4: Procurando botão de consulta...')
                # Possíveis botões de consulta
                botoes_consulta = [
                    'button:has-text("Consultar")',
                    'button:has-text("Buscar")',
                    'button:has-text("Pesquisar")',
                    'button[type="submit"]',
                    'input[type="submit"]',
                    '.btn-primary',
                    '.btn-consultar'
                ]
                
                botao_encontrado = False
                for selector in botoes_consulta:
                    try:
                        if page.locator(selector).count() > 0:
                            print(f'✅ Botão encontrado: {selector}')
                            print('🖱️  PASSO 5: Clicando no botão...')
                            page.locator(selector).first.click()
                            botao_encontrado = True
                            break
                    except:
                        continue
                
                if botao_encontrado:
                    print('⏳ Botão clicado! Aguardando resultados...')
                    time.sleep(3)
                    
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(3)
                    
                    print('\n📊 PASSO 6: Analisando resultados na tela...')
                    print('\n' + '='*80)
                    print('🔍 PROCURANDO DETALHES DA FATURA')
                    print('='*80)
                    
                    # Captura todo o HTML
                    html_content = page.content()
                    
                    # Procura por "Ver detalhes"
                    print('\n📌 PASSO 6.1: Procurando botão "Ver detalhes"...')
                    try:
                        ver_detalhes = page.locator('text=/ver detalhes/i').first
                        if ver_detalhes.count() > 0:
                            print('✅ Botão "Ver detalhes" encontrado!')
                            print('� VEJA NO NAVEGADOR: Botão ficará destacado em VERDE')
                            # Destaca visualmente no navegador
                            ver_detalhes.evaluate('el => el.style.background = "#00ff00"')
                            ver_detalhes.scroll_into_view_if_needed()
                            time.sleep(2)
                            
                            print('🖱️  Clicando para expandir fatura...\n')
                            ver_detalhes.click()
                            time.sleep(3)
                        else:
                            print('⚠️  Botão "Ver detalhes" não encontrado')
                    except Exception as e:
                        print(f'⚠️  Erro ao clicar: {e}')
                    
                    # Após expandir, captura novo HTML
                    html_content = page.content()
                    
                    # VALOR
                    print('\n💰 PASSO 6.2: Extraindo VALOR...')
                    print('👀 VEJA NO NAVEGADOR: Procurando valor na tela...')
                    import re
                    # Regex mais tolerante para capturar valor (aceita espaços e caracteres especiais)
                    valor_match = re.search(r'R\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_content, re.IGNORECASE)
                    if not valor_match:
                        # Tenta padrão mais simples
                        valor_match = re.search(r'(\d+[.,]\d{2})', html_content)
                    
                    if valor_match:
                        valor = valor_match.group(1)
                        print(f'✅ VALOR ENCONTRADO: R$ {valor}')
                        # Tenta destacar visualmente procurando por "R$" seguido do valor
                        try:
                            # Procura o elemento que contém "Valor da dívida"
                            valor_elem = page.locator('text=/valor.*dívida/i').first
                            if valor_elem.count() > 0:
                                valor_elem.evaluate('el => { el.style.background = "yellow"; el.style.padding = "5px"; el.style.border = "3px solid red"; }')
                                valor_elem.scroll_into_view_if_needed()
                                print('🟡 VALOR destacado em AMARELO com borda VERMELHA no navegador!')
                                time.sleep(2)
                        except:
                            pass
                    else:
                        valor = ''
                        print('⚠️  Valor não encontrado no HTML')
                    
                    # VENCIMENTO
                    print('\n📅 PASSO 6.3: Extraindo VENCIMENTO...')
                    print('👀 VEJA NO NAVEGADOR: Procurando data na tela...')
                    # Procura por padrões de data (DD/MM/YYYY ou YYYY-MM-DD)
                    data_matches = re.findall(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', html_content)
                    if data_matches:
                        vencimento = data_matches[0]
                        print(f'✅ VENCIMENTO ENCONTRADO: {vencimento}')
                        # Tenta destacar visualmente
                        try:
                            data_elem = page.locator(f'text=/{re.escape(vencimento)}/').first
                            if data_elem.count() > 0:
                                data_elem.evaluate('el => { el.style.background = "lightblue"; el.style.padding = "5px"; el.style.border = "3px solid blue"; }')
                                data_elem.scroll_into_view_if_needed()
                                print('🔵 VENCIMENTO destacado em AZUL CLARO com borda AZUL no navegador!')
                                time.sleep(2)
                        except:
                            pass
                    else:
                        vencimento = ''
                        print('⚠️  Vencimento não encontrado')
                    
                    # AGORA CLICA EM "PAGAR CONTA" para ver código de barras e PIX
                    print('\n💳 PASSO 6.4: Clicando em "Pagar conta" para ver códigos...')
                    print('👀 VEJA NO NAVEGADOR: Procurando botão "Pagar conta"...')
                    try:
                        pagar_btn = page.locator('button:has-text("Pagar conta")').first
                        if pagar_btn.count() > 0:
                            print('✅ Botão "Pagar conta" encontrado!')
                            print('👀 VEJA NO NAVEGADOR: Botão ficará destacado em ROXO')
                            pagar_btn.evaluate('el => el.style.background = "#9c27b0"')
                            pagar_btn.scroll_into_view_if_needed()
                            time.sleep(2)
                            
                            print('🖱️  Clicando em "Pagar conta"...\n')
                            pagar_btn.click()
                            time.sleep(3)
                            
                            # Aguarda nova página carregar
                            page.wait_for_load_state("networkidle", timeout=30000)
                            time.sleep(2)
                            
                            # Captura novo HTML com os códigos
                            html_content = page.content()
                        else:
                            print('⚠️  Botão "Pagar conta" não encontrado')
                    except Exception as e:
                        print(f'⚠️  Erro ao clicar em "Pagar conta": {e}')
                    
                    # CÓDIGO DE BARRAS
                    print('\n📊 PASSO 6.5: Extraindo CÓDIGO DE BARRAS...')
                    print('👀 VEJA NO NAVEGADOR: Procurando código de barras...')
                    # Padrão típico: 44-48 dígitos
                    codigos = re.findall(r'\b(\d{44,48})\b', html_content)
                    if codigos:
                        codigo_barras = codigos[0]
                        print(f'✅ CÓDIGO DE BARRAS ENCONTRADO: {codigo_barras}')
                        # Tenta destacar visualmente
                        try:
                            barras_elem = page.locator(f'text=/{re.escape(codigo_barras)}/').first
                            if barras_elem.count() > 0:
                                barras_elem.evaluate('el => { el.style.background = "lightgreen"; el.style.padding = "5px"; el.style.border = "3px solid green"; }')
                                barras_elem.scroll_into_view_if_needed()
                                print('🟢 CÓDIGO DE BARRAS destacado em VERDE CLARO com borda VERDE no navegador!')
                                time.sleep(3)
                        except:
                            pass
                    else:
                        # Tenta procurar em texto mais específico
                        print('   Tentando padrão alternativo...')
                        codigos_alt = re.findall(r'(\d{4}[\s\.]?\d{4}[\s\.]?\d{4}[\s\.]?\d{4}|\d{44,})', html_content)
                        if codigos_alt:
                            codigo_barras = codigos_alt[0].replace(' ', '').replace('.', '')
                            print(f'✅ CÓDIGO DE BARRAS ENCONTRADO: {codigo_barras}')
                        else:
                            codigo_barras = ''
                            print('⚠️  Código de barras não encontrado')
                    
                    # PIX
                    print('\n🔑 PASSO 6.6: Extraindo CÓDIGO PIX...')
                    print('👀 VEJA NO NAVEGADOR: Procurando código PIX...')
                    # Procura por padrão PIX (geralmente 32 caracteres alfanuméricos ou mais)
                    pix_matches = re.findall(r'[a-f0-9]{32,}', html_content, re.IGNORECASE)
                    if pix_matches:
                        codigo_pix = pix_matches[0]
                        print(f'✅ CÓDIGO PIX ENCONTRADO: {codigo_pix[:50]}...')
                        # Tenta destacar visualmente
                        try:
                            pix_elem = page.locator(f'text=/{re.escape(codigo_pix[:30])}/i').first
                            if pix_elem.count() > 0:
                                pix_elem.evaluate('el => { el.style.background = "orange"; el.style.padding = "5px"; el.style.border = "3px solid darkorange"; }')
                                pix_elem.scroll_into_view_if_needed()
                                print('🟠 CÓDIGO PIX destacado em LARANJA com borda LARANJA ESCURO no navegador!')
                                time.sleep(3)
                        except:
                            pass
                    else:
                        codigo_pix = ''
                        print('⚠️  Código PIX não encontrado')
                    
                    # RESUMO FINAL
                    print('\n' + '='*80)
                    print('📋 RESUMO DOS DADOS EXTRAÍDOS')
                    print('='*80)
                    print(f'\n💰 Valor:        {valor if valor else "❌ Não encontrado"}')
                    print(f'📅 Vencimento:   {vencimento if vencimento else "❌ Não encontrado"}')
                    print(f'📊 Código Barras: {codigo_barras if codigo_barras else "❌ Não encontrado"}')
                    print(f'🔑 Código PIX:    {codigo_pix if codigo_pix else "❌ Não encontrado"}')
                    
                    # Screenshot
                    print('\n📸 Capturando screenshot da página expandida...')
                    screenshot_path = 'nio_resultado.png'
                    page.screenshot(path=screenshot_path, full_page=True)
                    print(f'✅ Screenshot salvo em: {screenshot_path}')
                    
                else:
                    print('❌ Botão de consulta não encontrado')
                    print('   Elementos de botão visíveis na página:')
                    botoes = page.locator('button').all()
                    for btn in botoes[:5]:
                        try:
                            print(f'      - {btn.text_content()[:50]}')
                        except:
                            pass
            
            else:
                print('❌ Campo de CPF não encontrado')
                print('   Campos de input visíveis na página:')
                inputs = page.locator('input').all()
                for inp in inputs[:5]:
                    try:
                        print(f'      - {inp.get_attribute("placeholder") or inp.get_attribute("name") or "sem label"}')
                    except:
                        pass
        
        except Exception as e:
            print(f'\n❌ Erro durante navegação: {e}')
            import traceback
            traceback.print_exc()
        
        print('\n\n📋 ESTRUTURA DA PÁGINA ATUAL:')
        print('='*80)
        # Mostra estrutura básica
        try:
            title = page.title()
            url = page.url
            print(f'Título: {title}')
            print(f'URL: {url}')
        except:
            pass
        
        print('\n\n⏸️  Navegador ficará aberto por 60 segundos...')
        print('   Explore manualmente e pressione Ctrl+C para fechar.\n')
        
        for i in range(60, 0, -10):
            print(f'   Fechando em {i} segundos...')
            time.sleep(10)
        
        print('\n💾 Salvando cookies...')
        context.storage_state(path=state_path)
        
        print('🔒 Fechando navegador...')
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

