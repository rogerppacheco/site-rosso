import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from crm_app.models import ImportacaoOsab, Venda

OSS = [
    "10414358",
    "10375236",
    "10396320",
    "10481041",
    "10269250",
    "10199105",
    "10264232",
    "10392328",
    "10290065",
    "10504736",
]

print("venda_id|os|venda_abertura|venda_criacao|osab_abertura", flush=True)
for os_num in OSS:
    v = Venda.objects.filter(ordem_servico=os_num).order_by("-id").first()
    imp = ImportacaoOsab.objects.filter(numero_ba=os_num).order_by("-id").first()
    va = v.data_abertura.date() if v and v.data_abertura else ""
    vc = v.data_criacao.date() if v and v.data_criacao else ""
    oa = imp.data_abertura.date() if imp and imp.data_abertura else ""
    print(f"{getattr(v, 'id', '')}|{os_num}|{va}|{vc}|{oa}", flush=True)
