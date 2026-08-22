import os, sys
from datetime import datetime
from pathlib import Path
import django
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model
from crm_app.models import Venda, RegraComissaoFaixa
from crm_app.services.adiantamento_sabado_service import (
    calcular_descontos_adiantamento_sabado_folha,
    venda_entra_estorno_adiantamento_sabado_mes,
)
from crm_app.comissao_folha_service import valor_comissao_tabela_adiantamento, plano_tipo_to_chave
from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

U = get_user_model()
g = U.objects.get(username__iexact="GEOVANNE")
di = datetime(2026, 5, 1)
df = datetime(2026, 6, 1)
print("Estornos Geovanne:", calcular_descontos_adiantamento_sabado_folha(g, di, df))
for v in Venda.objects.filter(vendedor=g, adiantamento_sabado_marcado=True).select_related("status_esteira"):
    st = v.status_esteira.nome if v.status_esteira else "-"
    entra = venda_entra_estorno_adiantamento_sabado_mes(v, di.date(), df.date())
    print(f"  #{v.id} {st} val={v.adiantamento_sabado_valor} abertura={v.data_abertura} estorno={entra} os={v.ordem_servico}")

v = Venda.objects.select_related("plano", "cliente").get(pk=6506)
fa = RegraComissaoFaixa.objects.filter(finalidade="COMISSAO").order_by("id").first()
ch = plano_tipo_to_chave(v.plano.nome if v.plano else "", tipo_cliente_comissao(v))
tab = valor_comissao_tabela_adiantamento(v, fa, ch)
print(f"\n#6506 {v.cliente.nome_razao_social[:40]}")
print(f"  antecipacao_comissao={v.antecipacao_comissao} sab_marcado={v.adiantamento_sabado_marcado}")
print(f"  plano.comissao_base={v.plano.comissao_base} tabela_1a_faixa={tab}")
