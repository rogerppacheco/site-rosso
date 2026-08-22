import os, sys
from pathlib import Path
import django
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()
from crm_app.models import Venda
from crm_app.comissao_folha_service import annotate_data_folha_comissao

v = Venda.objects.get(pk=6750)
ann = annotate_data_folha_comissao(Venda.objects.filter(pk=6750)).first()
print("status", v.status_esteira.nome if v.status_esteira else None)
print("data_criacao", v.data_criacao)
print("data_instalacao", v.data_instalacao)
print("data_instalacao_fisica", getattr(v, "data_instalacao_fisica", None))
print("data_folha_comissao", getattr(ann, "data_folha_comissao", None))
print("data_abertura", v.data_abertura)
print("adiantamento_sabado_marcado_em", v.adiantamento_sabado_marcado_em)
