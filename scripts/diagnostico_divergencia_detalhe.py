"""Detalhe fino das divergências Paulo / Geovanne / Patricia — maio/2026."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_service import (
    annotate_data_folha_comissao,
    calcular_folha_mes,
    get_valor_from_faixa,
    plano_tipo_to_chave,
    valor_comissao_tabela_adiantamento,
)
from crm_app.models import RegraComissao
from crm_app.models import RegraComissaoFaixa, Venda
from crm_app.services.adiantamento_sabado_service import (
    calcular_descontos_adiantamento_sabado_folha,
    comissao_ja_adiantada_venda,
    valor_pago_adiantamento_sabado_venda,
    venda_entra_estorno_adiantamento_sabado_mes,
)
from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

ANO, MES = 2026, 5
di = datetime(ANO, MES, 1)
df = datetime(ANO, MES + 1, 1) if MES < 12 else datetime(ANO + 1, 1, 1)
di_d = di.date()
df_d = df.date()

faixa_adiant = RegraComissaoFaixa.objects.filter(finalidade="COMISSAO").order_by("id").first()


def _faixa_regra_consultor(consultor):
    folha = calcular_folha_mes(ANO, MES, vendedor_id=consultor.id)
    vd = next((v for v in folha.get("vendedores", []) if v["vendedor_id"] == consultor.id), None)
    nome = (vd.get("resumo") or {}).get("faixa_aplicada") if vd else None
    if not nome:
        return None
    regra = RegraComissao.objects.filter(usuario=consultor, ativo=True).first()
    if not regra:
        return None
    return regra.faixas.filter(faixa_nome=nome, finalidade="COMISSAO").first()


def _faixa_valor(consultor, venda) -> float:
    faixa = _faixa_regra_consultor(consultor)
    chave = plano_tipo_to_chave(venda.plano.nome if venda.plano else "", tipo_cliente_comissao(venda))
    if not chave or not faixa:
        return 0.0
    v = get_valor_from_faixa(faixa, chave)
    return float(v or 0)


def analisar_paulo(consultor) -> None:
    print("\n" + "=" * 80)
    print("PAULO — vendas a pagar vs planilha financeiro")
    vendas = annotate_data_folha_comissao(
        Venda.objects.filter(vendedor=consultor, ativo=True, status_esteira__nome__iexact="INSTALADA")
    ).filter(data_folha_comissao__gte=di_d, data_folha_comissao__lt=df_d).select_related(
        "plano", "cliente", "forma_pagamento"
    )
    a_pagar = [v for v in vendas if not comissao_ja_adiantada_venda(v)]
    cartao = [v for v in a_pagar if v.forma_pagamento and "CRÉDITO" in (v.forma_pagamento.nome or "").upper()]
    soma_cartao = sum(_faixa_valor(consultor, v) for v in cartao)
    soma_todas = sum(_faixa_valor(consultor, v) for v in a_pagar)
    print(f"  Instaladas na folha: {vendas.count()}")
    print(f"  A pagar (nao antecipada): {len(a_pagar)} = R$ {soma_todas:.2f}")
    print(f"  A pagar CARTAO CREDITO: {len(cartao)} = R$ {soma_cartao:.2f}")
    for v in cartao:
        nome = (v.cliente.nome_razao_social or "")[:35]
        print(f"    #{v.id} {nome} | {_faixa_valor(consultor, v):.2f}")


def analisar_geovanne(consultor) -> None:
    print("\n" + "=" * 80)
    print("GEOVANNE — estorno sabado + vendas a pagar extras")
    estornos = calcular_descontos_adiantamento_sabado_folha(consultor, di, df)
    print(f"  Estornos sabado na folha maio: {len(estornos)} total R$ {sum(x['valor'] for x in estornos):.2f}")
    for e in estornos:
        print(f"    #{e['venda_id']} R${e['valor']:.2f} — {e['motivo']}")

    # Sabado marcado nao instalado / cancelada
    qs_sab = Venda.objects.filter(
        vendedor=consultor,
        ativo=True,
        adiantamento_sabado_marcado=True,
    ).exclude(adiantamento_sabado_valor__isnull=True).select_related("status_esteira", "cliente")
    print("\n  Todas vendas com adiant. sabado:")
    for v in qs_sab:
        st = (v.status_esteira.nome if v.status_esteira else "-")
        entra = venda_entra_estorno_adiantamento_sabado_mes(v, di_d, df_d)
        print(
            f"    #{v.id} | {st:12} | sab_val=R${float(v.adiantamento_sabado_valor or 0):.0f} "
            f"| abertura={v.data_abertura} | estorno_mes={entra} | os={v.ordem_servico}"
        )

    vendas = annotate_data_folha_comissao(
        Venda.objects.filter(vendedor=consultor, ativo=True, status_esteira__nome__iexact="INSTALADA")
    ).filter(data_folha_comissao__gte=di_d, data_folha_comissao__lt=df_d).select_related("cliente", "plano")
    a_pagar = [v for v in vendas if not comissao_ja_adiantada_venda(v)]
    print(f"\n  A pagar na folha ({len(a_pagar)}):")
    for v in a_pagar:
        nome = (v.cliente.nome_razao_social or "")[:30]
        val = _faixa_valor(consultor, v)
        sab = valor_pago_adiantamento_sabado_venda(v)
        print(f"    #{v.id} {nome:30} faixa=R${val:.0f} sab_pago=R${sab:.0f}")


def analisar_patricia(consultor) -> None:
    print("\n" + "=" * 80)
    print("PATRICIA — venda antecipada esteira #6506")
    v = Venda.objects.filter(pk=6506).select_related("plano", "cliente", "forma_pagamento").first()
    if not v:
        print("  Venda 6506 nao encontrada")
        return
    chave = plano_tipo_to_chave(v.plano.nome if v.plano else "", tipo_cliente_comissao(v))
    tabela = valor_comissao_tabela_adiantamento(v, faixa_adiant, chave)
    print(f"  #{v.id} {(v.cliente.nome_razao_social or '')[:40]}")
    print(f"  antecipacao_comissao={v.antecipacao_comissao}")
    print(f"  adiantamento_sabado_marcado={v.adiantamento_sabado_marcado}")
    print(f"  plano.comissao_base={v.plano.comissao_base if v.plano else None}")
    print(f"  tabela faixa adiantamento (1a faixa COMISSAO): R$ {tabela:.2f}")
    print(f"  faixa aplicada vendedor (5 instalados): R$ {_faixa_valor(consultor, v):.2f}")


def main() -> None:
    User = get_user_model()
    analisar_paulo(User.objects.get(username__iexact="PAULO"))
    analisar_geovanne(User.objects.get(username__iexact="GEOVANNE"))
    analisar_patricia(User.objects.get(username__iexact="PATRICIA"))


if __name__ == "__main__":
    main()
