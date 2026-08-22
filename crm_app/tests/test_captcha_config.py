#!/usr/bin/env python
"""
Script para verificar a configuração do CAPTCHA.

Uso (a partir da raiz do projeto):
    python crm_app/tests/test_captcha_config.py
    ou: python -m crm_app.tests.test_captcha_config
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from django.conf import settings

print("=" * 60)
print("VERIFICAÇÃO DA CONFIGURAÇÃO DO CAPTCHA")
print("=" * 60)
print()

api_key = getattr(settings, "CAPTCHA_API_KEY", None)
provider = getattr(settings, "CAPTCHA_PROVIDER", None)

print(f"✅ CAPTCHA_PROVIDER: {provider}")
print()

if api_key:
    print(f"✅ CAPTCHA_API_KEY: {api_key[:30]}...{api_key[-10:]}")
    print(f"   Tamanho: {len(api_key)} caracteres")
    if api_key.startswith("CAP-"):
        print("   ✅ Formato válido para CapSolver (começa com 'CAP-')")
    else:
        print("   ⚠️  Formato não parece ser CapSolver (deveria começar com 'CAP-')")
    default_key = "CAP-4A266E1BA9DC47B87D28FBDE12A129014DB5B7EABC69D961115B3E184D497F85"
    if api_key == default_key:
        print("   ⚠️  ATENÇÃO: Usando valor padrão (default) do código!")
    else:
        print("   ✅ Não é o valor padrão do código")
    print()
    print("Status: CONFIGURADA ✅")
else:
    print("❌ CAPTCHA_API_KEY: NÃO CONFIGURADA")
    print("Status: NÃO CONFIGURADA ❌")

print()
print("=" * 60)
print("NOTA: A chave precisa ser obtida em:")
print("   https://capsolver.com/")
print("   ou")
print("   https://2captcha.com/")
print("=" * 60)
