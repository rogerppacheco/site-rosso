import os, sys
from pathlib import Path
import django
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from crm_app.models import Venda, LancamentoFinanceiro, RegraComissaoFaixa
from crm_app.views import _valor_adiantamento_base_comissao

# Paulo cartao
ids_paulo_cartao = [5707, 5763, 6126, 6154, 6444, 6549]
print("=== PAULO — vendas cartao na folha ===")
for vid in ids_paulo_cartao:
    v = Venda.objects.select_related("forma_pagamento", "cliente").get(pk=vid)
    fp = (v.forma_pagamento.nome if v.forma_pagamento else "-")
    print(f"  #{vid} {fp} | {(v.cliente.nome_razao_social or '')[:30]}")

# Geovanne Sueli/Maxwell
print("\n=== GEOVANNE — Sueli e Maxwell ===")
for vid in [6503, 6532]:
    v = Venda.objects.select_related("cliente", "status_esteira").get(pk=vid)
    print(
        f"  #{vid} {(v.cliente.nome_razao_social or '')[:30]} "
        f"antecip={v.antecipacao_comissao} sab={v.adiantamento_sabado_marcado} "
        f"status={(v.status_esteira.nome if v.status_esteira else '-')}"
    )
    lancs = LancamentoFinanceiro.objects.filter(
        tipo="ADIANTAMENTO_COMISSAO",
        metadados__venda_ids__contains=[vid],
    )
    for l in lancs[:3]:
        print(f"    lanc #{l.id} data={l.data} val={l.valor} meta={l.metadados}")

# Yago sabado
print("\n=== GEOVANNE — Yago #6102 sabado instalada ===")
v = Venda.objects.get(pk=6102)
print(
    f"  sab_marcado={v.adiantamento_sabado_marcado} val={v.adiantamento_sabado_valor} "
    f"quitado={v.adiantamento_sabado_quitado_em} antecip={v.antecipacao_comissao} "
    f"flag_desc={v.flag_desc_adiantamento_sabado}"
)

# Patricia 6506
print("\n=== PATRICIA — #6506 esteira ===")
v = Venda.objects.select_related("plano").get(pk=6506)
base = _valor_adiantamento_base_comissao(v)
fa = RegraComissaoFaixa.objects.filter(finalidade="COMISSAO").order_by("id").first()
print(f"  _valor_adiantamento_base_comissao={base}")
print(f"  1a faixa nome={fa.faixa_nome if fa else None} 500MB_PAP={fa.valor_500mb_pap if fa else None}")

# Lancamento esteira Patricia
lancs = LancamentoFinanceiro.objects.filter(
    usuario__username__iexact="PATRICIA",
    tipo="ADIANTAMENTO_COMISSAO",
    data__gte="2026-05-01",
    data__lt="2026-06-01",
)
print("\n=== PATRICIA — lancamentos ADIANTAMENTO_COMISSAO maio ===")
for l in lancs:
    print(f"  #{l.id} {l.data} R${l.valor} qtd={l.quantidade_vendas} meta={l.metadados}")
