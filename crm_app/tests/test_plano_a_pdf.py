#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de teste para verificar se o download de PDF no Plano A está funcionando.

Uso (a partir da raiz do projeto):
    python crm_app/tests/test_plano_a_pdf.py <CPF>
    ou: python -m crm_app.tests.test_plano_a_pdf <CPF>
Exemplo:
    python crm_app/tests/test_plano_a_pdf.py 12345678901
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

import logging
from crm_app.services_nio import _buscar_fatura_playwright, buscar_fatura_nio_por_cpf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def testar_plano_a_direto(cpf):
    """Testa a função _buscar_fatura_playwright diretamente (Plano A)."""
    print("\n" + "=" * 80)
    print("TESTE 1: Função _buscar_fatura_playwright (Plano A direto)")
    print("=" * 80)
    try:
        resultado = _buscar_fatura_playwright(cpf)
        if not resultado:
            print("❌ ERRO: Função retornou None")
            return False
        print(f"\n✅ Função executada com sucesso!")
        print(f"\n📊 Resultados:")
        print(f"  - Valor: {resultado.get('valor')}")
        print(f"  - Código PIX: {'✅ Presente' if resultado.get('codigo_pix') else '❌ Ausente'}")
        print(f"  - Código de Barras: {'✅ Presente' if resultado.get('codigo_barras') else '❌ Ausente'}")
        print(f"  - Data Vencimento: {resultado.get('data_vencimento')}")
        print(f"  - PDF URL: {resultado.get('pdf_url', '❌ Não disponível')}")
        print(f"  - PDF Path: {resultado.get('pdf_path', '❌ Não disponível')}")
        print(f"  - PDF Filename: {resultado.get('pdf_filename', '❌ Não disponível')}")
        pdf_path = resultado.get("pdf_path")
        if pdf_path:
            if os.path.exists(pdf_path):
                tamanho = os.path.getsize(pdf_path)
                print(f"\n✅ PDF BAIXADO COM SUCESSO!")
                print(f"  - Caminho: {pdf_path}")
                print(f"  - Tamanho: {tamanho} bytes ({tamanho/1024:.2f} KB)")
                return True
            print(f"\n❌ ERRO: pdf_path indicado mas arquivo não existe: {pdf_path}")
            return False
        print(f"\n⚠️ AVISO: PDF não foi baixado (pdf_path não presente no resultado)")
        return False
    except Exception as e:
        print(f"\n❌ ERRO durante execução: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def testar_plano_a_completo(cpf):
    """Testa buscar_fatura_nio_por_cpf com incluir_pdf=True (Plano A completo)."""
    print("\n" + "=" * 80)
    print("TESTE 2: Função buscar_fatura_nio_por_cpf com incluir_pdf=True (Plano A completo)")
    print("=" * 80)
    try:
        resultado = buscar_fatura_nio_por_cpf(cpf, incluir_pdf=True, usar_plano_b=False)
        if not resultado:
            print("❌ ERRO: Função retornou None")
            return False
        print(f"\n✅ Função executada com sucesso!")
        print(f"\n📊 Resultados:")
        print(f"  - Método usado: {resultado.get('metodo_usado', 'N/A')}")
        print(f"  - Valor: {resultado.get('valor')}")
        pdf_path = resultado.get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            tamanho = os.path.getsize(pdf_path)
            print(f"\n✅ PDF BAIXADO COM SUCESSO! ({tamanho/1024:.2f} KB)")
            return True
        print(f"\n⚠️ AVISO: PDF não foi baixado")
        return False
    except Exception as e:
        print(f"\n❌ ERRO durante execução: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) < 2:
        print("❌ ERRO: CPF não fornecido")
        print("\nUso: python crm_app/tests/test_plano_a_pdf.py <CPF>")
        sys.exit(1)
    import re
    cpf_limpo = re.sub(r"\D", "", sys.argv[1])
    if len(cpf_limpo) != 11:
        print(f"❌ ERRO: CPF inválido. Deve ter 11 dígitos.")
        sys.exit(1)
    print("\n" + "=" * 80)
    print(f"TESTE DE DOWNLOAD DE PDF - PLANO A | CPF: {cpf_limpo}")
    print("=" * 80)
    sucesso_1 = testar_plano_a_direto(cpf_limpo)
    sucesso_2 = testar_plano_a_completo(cpf_limpo)
    print("\n" + "=" * 80)
    print("RESUMO FINAL")
    print("=" * 80)
    print(f"Teste 1 (_buscar_fatura_playwright): {'✅ PASSOU' if sucesso_1 else '❌ FALHOU'}")
    print(f"Teste 2 (buscar_fatura_nio_por_cpf): {'✅ PASSOU' if sucesso_2 else '❌ FALHOU'}")
    sys.exit(0 if (sucesso_1 or sucesso_2) else 1)


if __name__ == "__main__":
    main()
