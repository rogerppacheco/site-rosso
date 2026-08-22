import os, sys
from pathlib import Path
import django
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()
from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda
for vid in [6503, 6532, 6102]:
    v = Venda.objects.get(pk=vid)
    print(
        f"#{vid} reemissao={v.reemissao} antecipacao={v.antecipacao_comissao} "
        f"sab={v.adiantamento_sabado_marcado} quitado={bool(v.adiantamento_sabado_quitado_em)} "
        f"ja_adiantada={comissao_ja_adiantada_venda(v)}"
    )
