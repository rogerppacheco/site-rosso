"""
Script COMPLETO para extrair dados do Nio seguindo o fluxo correto:
1. Digita CPF → Consultar
2. Ver detalhes → Pagar conta
3. Pagar com Pix → Copiar chave PIX → Voltar
4. Gerar Boleto → Copiar código de barras
"""
import os
import sys
from urllib.parse import urlparse
sys.path.insert(0, 'C:/site-record')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

import time
import re
from playwright.sync_api import sync_playwright

# Configurações
CPF = '07919117640'
SITE_URL = "https://negociacao.niointernet.com.br"

print('='*80)
print('👤 EXTRAÇÃO COMPLETA DE DADOS DO NIO')
print('='*80)
print(f'\n📋 CPF: {CPF}')
print('👀 Acompanhe visualmente no navegador!\n')
time.sleep(2)

try:
    with sync_playwright() as p:
        print('🚀 Iniciando navegador...')
        browser = p.chromium.launch(headless=False, slow_mo=500)
        
        state_path = os.path.join(os.path.dirname(__file__), '.playwright_state.json')
        storage_state = state_path if os.path.exists(state_path) else None
        downloads_dir = os.path.join(os.path.dirname(__file__), 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
            storage_state=storage_state,
            accept_downloads=True
        )
        
        page = context.new_page()
        
        # PASSO 1: Navegar e digitar CPF
        print(f'\n🌍 PASSO 1: Navegando para {SITE_URL}')
        page.goto(SITE_URL, wait_until="networkidle", timeout=30000)
        print('✅ Página carregada!')
        time.sleep(2)
        
        print('\n⌨️  PASSO 2: Digitando CPF...')
        campo_cpf = page.locator('input[type="text"]').first
        campo_cpf.fill(CPF)
        print(f'✅ CPF {CPF} digitado!')
        time.sleep(2)
        
        # Pausa para reCAPTCHA
        print('\n' + '='*80)
        print('🔐 RESOLVA O RECAPTCHA (SE APARECER)')
        print('='*80)
        confirmacao = input('\n>>> Digite SIM quando pronto >>> ').strip().upper()
        if confirmacao != 'SIM':
            confirmacao = input('>>> Digite SIM >>> ').strip().upper()
        print('✅ Continuando...\n')
        
        # PASSO 3: Clicar em Consultar
        print('🖱️  PASSO 3: Clicando em "Consultar"...')
        btn_consultar = page.locator('button:has-text("Consultar")').first
        btn_consultar.click()
        time.sleep(3)
        page.wait_for_load_state("networkidle", timeout=30000)
        print('✅ Consultado!')
        time.sleep(2)
        
        # PASSO 4: Clicar em "Ver detalhes"
        print('\n📋 PASSO 4: Expandindo "Ver detalhes"...')
        ver_detalhes = page.locator('text=/ver detalhes/i').first
        if ver_detalhes.count() > 0:
            ver_detalhes.scroll_into_view_if_needed()
            time.sleep(1)
            ver_detalhes.click()
            print('✅ Expandido!')
            time.sleep(2)
        
        # Extrai vencimento da tabela expandida
        html_expandido = page.content()
        data_matches = re.findall(r'(\d{2}/\d{2}/\d{4})', html_expandido)
        vencimento = data_matches[0] if data_matches else ''
        print(f'📅 Vencimento encontrado: {vencimento}')
        
        # PASSO 5: Clicar em "Pagar conta"
        print('\n💳 PASSO 5: Clicando em "Pagar conta"...')
        pagar_btn = page.locator('button:has-text("Pagar conta")').first
        pagar_btn.scroll_into_view_if_needed()
        time.sleep(1)
        pagar_btn.click()
        print('🖱️  Clicado!')
        time.sleep(2)
        
        # Aguarda página "Contas pra pagamento"
        print('⏳ Aguardando página carregar...')
        page.wait_for_url('**/payment**', timeout=15000)
        time.sleep(2)
        print('✅ Página "Contas pra pagamento" carregada!')
        
        # Extrai VALOR correto na página de pagamento
        html_pagamento = page.content()
        print('\n💰 PASSO 6: Extraindo VALOR...')
        print('👀 VEJA NO NAVEGADOR: primeira coluna "Valor"')
        
        # Procura por "130,00" ou qualquer valor em R$
        valor_match = re.search(r'R\$\s*&nbsp;\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_pagamento, re.IGNORECASE)
        if not valor_match:
            valor_match = re.search(r'R\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_pagamento, re.IGNORECASE)
        
        if valor_match:
            valor = valor_match.group(1)
            print(f'✅ VALOR: R$ {valor}')
        else:
            valor = ''
            print('⚠️  Valor não encontrado')
        
        # PASSO 7: Clicar em "Pagar com Pix"
        print('\n🔑 PASSO 7: Clicando em "Pagar com Pix"...')
        print('👀 VEJA NO NAVEGADOR: botão ficará VERDE')
        
        # Procura pelo div com data-context (mais robusto e específico)
        pix_btn = page.locator('div[data-context="btn_container_pagar-online"]').first
        if pix_btn.count() > 0:
            pix_btn.scroll_into_view_if_needed()
            time.sleep(1)
            pix_btn.click()
            print('🖱️  Clicado!')
            time.sleep(3)
            
            # Aguarda a URL mudar para paymentpix (mais confiável que networkidle)
            try:
                page.wait_for_url('**/paymentpix**', timeout=10000)
            except:
                print('⏳ Aguardando carregamento...')
                time.sleep(2)
            
            print('✅ Página "PIX PRA PAGAMENTO" carregada!')
            
            # Extrai código PIX
            html_pix = page.content()
            print('\n📱 PASSO 8: Extraindo CÓDIGO PIX...')
            print('👀 VEJA NO NAVEGADOR: QR Code + chave PIX')
            
            # Procura pela chave PIX padrão (00020126...)
            pix_matches = re.findall(r'00020126[0-9a-zA-Z]{100,}', html_pix)
            if not pix_matches:
                # Se não encontrar, procura por qualquer sequência longa de números/letras
                pix_matches = re.findall(r'[a-zA-Z0-9]{80,150}', html_pix)
            
            if pix_matches:
                codigo_pix = pix_matches[0]
                print(f'✅ PIX encontrado: {codigo_pix[:50]}...')
            else:
                codigo_pix = ''
                print('⚠️  Código PIX não encontrado')
            
            # VOLTA para página anterior
            print('\n⬅️  PASSO 9: Voltando para "Contas pra pagamento"...')
            page.go_back()
            time.sleep(2)
            
            # Aguarda a URL voltar ao payment (mais confiável)
            try:
                page.wait_for_url('**/payment**', timeout=10000)
            except:
                print('⏳ Aguardando carregamento...')
                time.sleep(2)
            
            print('✅ Voltou!')
        else:
            print('⚠️  Botão "Pagar com Pix" não encontrado')
            print('   Procurando alternativas...')
            # Tenta variações com seletores alternativos
            pix_btn = page.locator('p:text-is("Pagar com Pix")').first
            if pix_btn.count() > 0:
                print('✅ Encontrado via seletor p:text-is!')
                pix_btn.locator('xpath=ancestor::div[contains(@style, "cursor: pointer")]').click()
                time.sleep(3)
                page.wait_for_load_state("networkidle", timeout=15000)
            codigo_pix = ''
        
        # PASSO 10: Clicar em "Gerar Boleto"
        print('\n📊 PASSO 10: Clicando em "Gerar Boleto"...')
        print('👀 VEJA NO NAVEGADOR: botão ficará AZUL')
        
        # Procura pelo div com data-context (mais robusto e específico)
        boleto_btn = page.locator('div[data-context="btn_container_gerar-boleto"]').first
        if boleto_btn.count() > 0:
            boleto_btn.scroll_into_view_if_needed()
            time.sleep(1)
            boleto_btn.click()
            print('🖱️  Clicado!')
            time.sleep(3)
            
            # Aguarda a URL mudar para paymentbillet (mais confiável que networkidle)
            try:
                page.wait_for_url('**/paymentbillet**', timeout=10000)
            except:
                print('⏳ Aguardando carregamento...')
                time.sleep(2)
            
            print('✅ Página "BOLETO PARA PAGAMENTO" carregada!')
            
            # Extrai código de barras
            html_boleto = page.content()
            print('\n📋 PASSO 11: Extraindo CÓDIGO DE BARRAS...')
            print('👀 VEJA NO NAVEGADOR: código de barras visível')

            codigo_barras = ''

            # 1) Tenta copiar pelo botão da página (valor mais confiável)
            try:
                copiar_barras_btn = page.locator('text="Copiar código de barras"').first
                if copiar_barras_btn.count() > 0:
                    copiar_barras_btn.click()
                    time.sleep(0.5)
                    cb_text = page.evaluate('navigator.clipboard.readText()')
                    match_cb = re.search(r'\d{44,50}', cb_text or '')
                    if match_cb:
                        codigo_barras = match_cb.group(0)
                        print(f'✅ CÓDIGO DE BARRAS (clipboard): {codigo_barras}')
            except Exception as e:
                print(f'⚠️  Falha ao ler clipboard: {e}')

            # 2) Fallback: regex no HTML (escolhe candidato que começa com 0339 ou o primeiro)
            if not codigo_barras:
                codigos = re.findall(r'\b(\d{44,50})\b', html_boleto)
                if codigos:
                    preferidos = [c for c in codigos if c.startswith('0339')]
                    codigo_barras = preferidos[0] if preferidos else codigos[0]
                    print(f'✅ CÓDIGO DE BARRAS (HTML): {codigo_barras}')
                else:
                    print('⚠️  Código de barras não encontrado')

            # PASSO 12: Baixar PDF da fatura
            print('\n📄 PASSO 12: Capturando link do PDF da fatura...')
            pdf_url_capturado = ''
            try:
                with context.expect_page(timeout=8000) as popup_info:
                    page.locator('text="Baixar PDF"').first.click()
                pdf_page = popup_info.value
                pdf_page.wait_for_load_state()
                pdf_page.wait_for_timeout(3000)
                pdf_url_capturado = pdf_page.url
                print(f'✅ Link do PDF: {pdf_url_capturado}')
                pdf_page.close()
            except Exception as e2:
                print(f'⚠️  Não foi possível capturar o link do PDF: {e2}')
        else:
            print('⚠️  Botão "Gerar Boleto" não encontrado')
            print('   Procurando alternativas...')
            # Tenta variações com seletores alternativos
            boleto_btn = page.locator('p:text-is("Gerar Boleto")').first
            if boleto_btn.count() > 0:
                print('✅ Encontrado via seletor p:text-is!')
                boleto_btn.locator('xpath=ancestor::div[contains(@style, "cursor: pointer")]').click()
                time.sleep(3)
                page.wait_for_load_state("networkidle", timeout=15000)
            codigo_barras = ''
        
        # RESUMO FINAL
        print('\n' + '='*80)
        print('📋 RESUMO FINAL - DADOS EXTRAÍDOS')
        print('='*80)
        print(f'\n💰 Valor:         R$ {valor if valor else "❌ Não encontrado"}')
        print(f'📅 Vencimento:    {vencimento if vencimento else "❌ Não encontrado"}')
        print(f'🔑 Código PIX:    {codigo_pix[:60] if codigo_pix else "❌ Não encontrado"}{"..." if len(codigo_pix) > 60 else ""}')
        print(f'📊 Código Barras: {codigo_barras if codigo_barras else "❌ Não encontrado"}')
        
        # Screenshot final
        print('\n📸 Capturando screenshot...')
        screenshot_path = 'nio_completo.png'
        try:
            page.screenshot(path=screenshot_path, full_page=True, timeout=60000)
            print(f'✅ Screenshot: {screenshot_path}')
        except Exception as e:
            print(f'⚠️  Não foi possível capturar screenshot: {e}')
        
        print('\n\n⏸️  Navegador ficará aberto 30 segundos para você conferir...\n')
        for i in range(30, 0, -5):
            print(f'   Fechando em {i} segundos...')
            time.sleep(5)
        
        context.storage_state(path=state_path)
        browser.close()
        print('\n✅ Concluído!')

except KeyboardInterrupt:
    print('\n\n⚠️  Interrompido pelo usuário.')
except Exception as e:
    print(f'\n\n❌ ERRO: {e}')
    import traceback
    traceback.print_exc()

print('\n' + '='*80)
print('FIM')
print('='*80)
