import os, sys
from pathlib import Path
import django
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()
from django.contrib.auth import get_user_model
from crm_app.comissao_folha_service import calcular_folha_mes

u = get_user_model().objects.get(username__iexact="VIVIANE")
folha = calcular_folha_mes(2026, 6, vendedor_id=u.id)
vd = folha["vendedores"][0]
for linha in vd.get("extrato") or []:
    if linha.get("venda_id") == 6750:
        print("Junho extrato #6750:", linha)
        break
else:
    print("6750 nao no extrato junho")
r = vd["resumo"]
print(f"Junho liquido: R$ {float(r.get('liquido') or 0):.2f}")
print(f"Junho compl sabado: R$ {float(r.get('complemento_sabado_total') or 0):.2f}")
