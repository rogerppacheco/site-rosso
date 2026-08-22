"""
Teste local de busca de fatura (crm_app.services_nio).
Uso (a partir da raiz do projeto): python scripts/debug/test_busca_fatura_local.py
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from crm_app.services_nio import buscar_fatura_nio_por_cpf

if __name__ == "__main__":
    cpf = input("Digite o CPF para buscar a fatura: ").strip()
    print("[DEBUG] Iniciando busca de fatura para:", cpf)
    resultado = buscar_fatura_nio_por_cpf(cpf, incluir_pdf=True)
    print("[DEBUG] Resultado da busca:", resultado)
