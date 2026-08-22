import os, sys
from pathlib import Path
import django
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()
from crm_app.models import LancamentoFinanceiro, Venda, HistoricoAlteracaoVenda
v = Venda.objects.get(pk=6506)
print("6506", v.antecipacao_comissao, v.adiantamento_sabado_marcado, v.reemissao)
for l in LancamentoFinanceiro.objects.filter(tipo="ADIANTAMENTO_COMISSAO", usuario_id=v.vendedor_id).order_by("-data")[:10]:
    ids = (l.metadados or {}).get("venda_ids") or []
    if 6506 in ids:
        print(f"  lanc #{l.id} {l.data} R${l.valor} ids={len(ids)}")
for h in HistoricoAlteracaoVenda.objects.filter(venda_id=6506).order_by("-id")[:5]:
    print(f"  hist {h.alteracoes}")
