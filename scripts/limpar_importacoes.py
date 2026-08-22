"""Script para limpar dados de todas as tabelas de importação/monitoramento.
Use com cautela: limpa registros de DFV, KML/Mapa, OSAB, Churn, Agendamentos,
Recompra, FPD, M-10 (Safra/Contrato/Fatura) e Ciclo de Pagamento.
"""
import os
import sys
from pathlib import Path
import django

# Garantir que o diretório do projeto esteja no sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.db import transaction

from crm_app.models import (
    ImportacaoFPD,
    LogImportacaoFPD,
    ImportacaoAgendamento,
    ImportacaoRecompra,
    ImportacaoChurn,
    ImportacaoOsab,
    DFV,
    AreaVenda,
    CicloPagamento,
    SafraM10,
    ContratoM10,
    FaturaM10,
)
from osab.models import Osab


TARGETS = [
    ("ImportacaoFPD", ImportacaoFPD),
    ("LogImportacaoFPD", LogImportacaoFPD),
    ("ImportacaoAgendamento", ImportacaoAgendamento),
    ("ImportacaoRecompra", ImportacaoRecompra),
    ("ImportacaoChurn", ImportacaoChurn),
    ("ImportacaoOsab", ImportacaoOsab),
    ("Osab", Osab),
    ("DFV", DFV),
    ("AreaVenda (KML/Mapa)", AreaVenda),
    ("FaturaM10", FaturaM10),
    ("ContratoM10", ContratoM10),
    ("SafraM10", SafraM10),
    ("CicloPagamento", CicloPagamento),
]


def clear_model(model):
    qs = model.objects.all()
    count = qs.count()
    qs.delete()
    return count


def run():
    results = []
    with transaction.atomic():
        # Ordem importa para evitar FK: Fatura -> Contrato -> Safra
        ordered = [
            "ImportacaoFPD",
            "LogImportacaoFPD",
            "ImportacaoAgendamento",
            "ImportacaoRecompra",
            "ImportacaoChurn",
            "ImportacaoOsab",
            "Osab",
            "DFV",
            "AreaVenda (KML/Mapa)",
            "FaturaM10",
            "ContratoM10",
            "SafraM10",
            "CicloPagamento",
        ]
        name_to_model = {name: model for name, model in TARGETS}
        for name in ordered:
            model = name_to_model[name]
            deleted = clear_model(model)
            results.append((name, deleted))
    print("LIMPEZA CONCLUÍDA:")
    for name, deleted in results:
        print(f"- {name}: {deleted} registros apagados")


if __name__ == "__main__":
    run()
