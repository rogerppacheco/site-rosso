"""
Script DEBUG interativo - para na página "Contas pra pagamento"
e exibe todos os elementos disponíveis para você clicar
"""
import os
import sys
sys.path.insert(0, 'C:/site-bn')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

import time
from playwright.sync_api import sync_playwright

CPF = '12886868620'
SITE_URL = "https://negociacao.niointernet.com.br"

print('='*80)
print('🔍 MODO DEBUG - DESCOBRIR SELETORES')
print('='*80)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        state_path = '.playwright_state.json'
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
            storage_state=state_path if os.path.exists(state_path) else None
        )
        page = context.new_page()
        
        # Ir até "Contas pra pagamento"
        print(f'\n🌍 Navegando...')
        page.goto(SITE_URL, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        
        print('⌨️  Digitando CPF...')
        campo_cpf = page.locator('input[type="text"]').first
        campo_cpf.fill(CPF)
        time.sleep(2)
        
        print('🔐 Resolva o reCAPTCHA:')
        input('>>> Digite SIM quando pronto >>> ')
        
        print('🖱️  Clicando "Consultar"...')
        page.locator('button:has-text("Consultar")').first.click()
        time.sleep(3)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)
        
        print('📋 Expandindo "Ver detalhes"...')
        page.locator('text=/ver detalhes/i').first.click()
        time.sleep(2)
        
        print('💳 Clicando "Pagar conta"...')
        page.locator('button:has-text("Pagar conta")').first.click()
        time.sleep(2)
        page.wait_for_url('**/payment**', timeout=15000)
        time.sleep(3)
        
        print('\n' + '='*80)
        print('✅ CHEGAMOS NA PÁGINA "CONTAS PRA PAGAMENTO"')
        print('='*80)
        print('\n👀 ANALISANDO ELEMENTOS DISPONÍVEIS...\n')
        
        # Lista TODOS os botões
        buttons = page.locator('button').all()
        print(f'\n📊 TOTAL DE BOTÕES ENCONTRADOS: {len(buttons)}\n')
        
        botoes_encontrados = []
        for i, btn in enumerate(buttons):
            try:
                text = btn.text_content().strip()
                classes = btn.get_attribute('class') or ''
                role = btn.get_attribute('role') or 'button'
                
                if text and len(text) > 0:  # Só mostra se tiver texto
                    botoes_encontrados.append({
                        'index': i,
                        'text': text,
                        'classes': classes,
                        'role': role
                    })
                    
                    print(f'🔘 BOTÃO {i}:')
                    print(f'   Texto: "{text}"')
                    print(f'   Classes: {classes}')
                    print(f'   Selector (simple): button:has-text("{text[:40]}")')
                    print()
            except Exception as e:
                pass
        
        # Tenta com a classe CSS genérica
        print('\n' + '='*80)
        print('🎯 BUSCANDO POR PADRÃO CSS "sc-htpNat"')
        print('='*80 + '\n')
        
        elementos_sc = page.locator('.sc-htpNat').all()
        print(f'Encontrados {len(elementos_sc)} elementos com classe "sc-htpNat"\n')
        
        for i, elem in enumerate(elementos_sc[:20]):  # Mostra primeiros 20
            try:
                text = elem.text_content().strip()
                if text and len(text) < 100:
                    print(f'{i}: "{text}"')
            except:
                pass
        
        # Extrai HTML e salva
        print('\n' + '='*80)
        print('💾 SALVANDO HTML COMPLETO EM: debug_nio_payment.html')
        print('='*80)
        
        html = page.content()
        with open('debug_nio_payment.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print('✅ Arquivo salvo!\n')
        
        # Script JavaScript mais detalhado
        print('='*80)
        print('🔬 ANALISANDO COM JAVASCRIPT - ESTRUTURA DOS BOTÕES')
        print('='*80 + '\n')
        
        # Encontra divs/sections que contêm "Pagar com Pix" ou "Gerar Boleto"
        estrutura = page.evaluate('''() => {
            const resultado = [];
            
            // Procura por texto em qualquer elemento
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text.includes('Pagar com Pix') || text.includes('Gerar Boleto') || text.includes('Copiar')) {
                    // Encontrou! Pega o pai
                    let parent = node.parentElement;
                    resultado.push({
                        texto: text,
                        tag: parent.tagName,
                        classes: parent.className,
                        id: parent.id,
                        pai: parent.parentElement?.tagName,
                        paiClasses: parent.parentElement?.className
                    });
                }
            }
            return resultado;
        }''')
        
        print(f'Elementos encontrados: {len(estrutura)}\n')
        for elem in estrutura:
            print(f'Texto: "{elem["texto"]}"')
            print(f'  Tag: {elem["tag"]}, Classes: {elem["classes"]}')
            print(f'  ID: {elem["id"]}')
            print(f'  Pai: {elem["pai"]} ({elem["paiClasses"]})')
            print()
        
        print('\n' + '='*80)
        print('🎯 RECOMENDAÇÃO:')
        print('='*80)
        print('''
OPÇÕES ROBUSTAS PARA CLICAR NOS BOTÕES:

1. Procurar o button que contém um <p> com texto específico:
   button:has(p:text-is("Pagar com Pix"))
   button:has(p:text-is("Gerar Boleto"))

2. Procurar pela classe CSS + texto:
   .sc-htpNat:has-text("Pagar com Pix")

3. Procurar apenas pelo texto (mais simples):
   text="Pagar com Pix"
   text="Gerar Boleto"

4. Procurar o elemento pai se for um div:
   div:has-text("Pagar com Pix") >> button

Vou tentar agora com XPath robusto para extrair toda a estrutura...
        ''')
        
        # Usa XPath para encontrar os botões de forma mais robusta
        print('\n' + '='*80)
        print('🔍 TESTANDO SELETORES:')
        print('='*80 + '\n')
        
        seletores_teste = [
            'button:has-text("Pagar com Pix")',
            'button:has-text("Gerar Boleto")',
            'p:text-is("Pagar com Pix")',
            'p:text-is("Gerar Boleto")',
            'text="Pagar com Pix"',
            'text="Gerar Boleto"',
        ]
        
        for sel in seletores_teste:
            try:
                count = page.locator(sel).count()
                print(f'✅ "{sel}": encontrado {count} elemento(s)')
                if count > 0:
                    try:
                        elem = page.locator(sel).first
                        print(f'   → Texto: "{elem.text_content().strip()}"')
                    except:
                        pass
            except Exception as e:
                print(f'❌ "{sel}": erro - {str(e)[:50]}')
            print()
        
        print('\n' + '='*80)
        print('⏸️  NAVEGADOR ABERTO - EXPLORE E TIRE PRINT!')
        print('='*80)
        print('\nVocê pode:')
        print('1. Abrir DevTools (F12) e inspecionar os botões')
        print('2. Copiar seletores CSS exatos')
        print('3. Me mandar a estrutura correta')
        print('\nNavigador fechará em 180 segundos...\n')
        
        for i in range(180, 0, -30):
            print(f'   {i} segundos...')
            time.sleep(30)
        
        context.storage_state(path=state_path)
        browser.close()
        print('\n✅ Encerrado')

except KeyboardInterrupt:
    print('\n\n⚠️  Interrompido pelo usuário.')
except Exception as e:
    print(f'\n\n❌ ERRO: {e}')
    import traceback
    traceback.print_exc()

