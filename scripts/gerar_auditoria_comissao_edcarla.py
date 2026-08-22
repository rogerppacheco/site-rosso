"""Gera planilha de auditoria detalhada da comissão Edcarla (maio/2026)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_excel import gerar_xlsx_auditoria_comissao
from crm_app.comissao_folha_service import calcular_folha_mes
from crm_app.models import Venda


def _carregar_dados_venda(venda_ids: list[int]) -> tuple[dict[int, str], dict[int, str]]:
    formas: dict[int, str] = {}
    documentos: dict[int, str] = {}
    qs = (
        Venda.objects.filter(id__in=venda_ids)
        .select_related("forma_pagamento", "cliente")
        .only("id", "forma_pagamento__nome", "cliente__cpf_cnpj")
    )
    for venda in qs:
        formas[venda.id] = (venda.forma_pagamento.nome if venda.forma_pagamento else "") or ""
        documentos[venda.id] = (venda.cliente.cpf_cnpj if venda.cliente else "") or ""
    return formas, documentos


def main() -> None:
    ano, mes = 2026, 5
    consultor = get_user_model().objects.filter(username__iexact="EDCARLA").first()
    if not consultor:
        raise SystemExit("Vendedora EDCARLA não encontrada.")

    folha = calcular_folha_mes(ano, mes, vendedor_id=consultor.id, use_effective_date_for_display=True)
    vendedor_data = next(
        (v for v in folha.get("vendedores", []) if v.get("vendedor_id") == consultor.id),
        None,
    )
    if not vendedor_data:
        raise SystemExit("Sem dados de folha para maio/2026.")

    venda_ids = [
        int(x["venda_id"])
        for x in vendedor_data.get("extrato") or []
        if x.get("venda_id") is not None
    ]
    formas, documentos = _carregar_dados_venda(venda_ids)

    # Enriquecer extrato com CPF/CNPJ na aba Vendas via cópia dos dados
    extrato_enriquecido = []
    for linha in vendedor_data.get("extrato") or []:
        item = dict(linha)
        vid = item.get("venda_id")
        if vid is not None:
            item["cpf_cnpj"] = documentos.get(int(vid), "")
        extrato_enriquecido.append(item)
    vendedor_data = {**vendedor_data, "extrato": extrato_enriquecido}

    periodo = folha.get("periodo", f"{mes:02d}/{ano}")
    xlsx = gerar_xlsx_auditoria_comissao(vendedor_data, periodo, formas_pagamento=formas)

    saida_dir = BASE_DIR / "data" / "comissao_export"
    saida_dir.mkdir(parents=True, exist_ok=True)
    nome_arquivo = f"EDCARLA_auditoria_comissao_{mes:02d}_{ano}.xlsx"
    caminho = saida_dir / nome_arquivo
    caminho.write_bytes(xlsx.getvalue())

    resumo = vendedor_data.get("resumo") or {}
    print(f"Planilha gerada: {caminho}")
    print(f"Liquido: R$ {float(resumo.get('liquido') or 0):.2f}")
    print(f"Vendas no extrato: {len(extrato_enriquecido)}")


if __name__ == "__main__":
    main()
