"""
Sincroniza DU Vendas (peso_venda) e DU Instalação (peso_instalacao) de 2026
com os totais mensais de referência da Nio.

Uso:
    python manage.py sincronizar_du_nio_2026
    python manage.py sincronizar_du_nio_2026 --dry-run
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import DiaFiscal
from core.services.calendario_fiscal_service import _pesos_padrao_por_weekday
from presenca.models import DiaNaoUtil

# Referência Nio 2026 — DU Vendas (VB / B2C)
TARGET_DU_VENDAS: dict[int, float] = {
    1: 23.02,
    2: 20.30,
    3: 23.80,
    4: 22.10,
    5: 22.30,
    6: 23.20,
    7: 24.70,
    8: 23.20,
    9: 22.90,
    10: 23.30,
    11: 21.60,
    12: 21.20,
}

# Referência Nio 2026 — DU Instalação (Gross / VA / Nio)
TARGET_DU_INSTALACAO: dict[int, float] = {
    1: 24.80,
    2: 22.30,
    3: 25.30,
    4: 23.90,
    5: 24.20,
    6: 24.70,
    7: 26.30,
    8: 25.10,
    9: 24.60,
    10: 25.40,
    11: 23.40,
    12: 23.30,
}

# Feriados nacionais 2026 (complementa presenca.DiaNaoUtil)
FERIADOS_NACIONAIS_2026: dict[date, str] = {
    date(2026, 1, 1): "Ano Novo",
    date(2026, 2, 16): "Carnaval (segunda)",
    date(2026, 2, 17): "Carnaval (terça)",
    date(2026, 4, 3): "Sexta-feira Santa",
    date(2026, 4, 21): "Tiradentes",
    date(2026, 5, 1): "Dia do Trabalho",
    date(2026, 6, 4): "Corpus Christi",
    date(2026, 9, 7): "Independência",
    date(2026, 10, 12): "Nossa Senhora Aparecida",
    date(2026, 11, 2): "Finados",
    date(2026, 11, 20): "Consciência Negra",
    date(2026, 12, 25): "Natal",
}


def _q2(valor: float) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _carregar_feriados_2026() -> dict[date, str]:
    feriados = dict(FERIADOS_NACIONAIS_2026)
    for row in DiaNaoUtil.objects.filter(data__year=2026).values("data", "descricao"):
        feriados[row["data"]] = row["descricao"] or "Feriado"
    return feriados


def _escalar_pesos(
    pesos: list[float],
    alvo: float,
) -> list[Decimal]:
    """Escala pesos positivos para atingir o total mensal e corrige arredondamento."""
    base = [float(p) for p in pesos]
    soma = sum(base)
    if soma <= 0 or alvo <= 0:
        return [_q2(0) for _ in base]

    fator = alvo / soma
    escalados = [_q2(p * fator) if p > 0 else _q2(0) for p in base]

    diff = _q2(alvo) - sum(escalados)
    if diff == 0:
        return escalados

    # Ajuste fino no dia útil de maior peso para fechar o total exato.
    candidatos = [i for i, p in enumerate(base) if p > 0]
    if not candidatos:
        return escalados
    idx = max(candidatos, key=lambda i: escalados[i])
    escalados[idx] = _q2(float(escalados[idx]) + float(diff))
    return escalados


def _montar_pesos_mes(
    ano: int,
    mes: int,
    feriados: dict[date, str],
) -> list[tuple[date, Decimal, Decimal, bool, str]]:
    ultimo = calendar.monthrange(ano, mes)[1]
    dias: list[tuple[date, float, float, bool, str]] = []
    for dia in range(1, ultimo + 1):
        atual = date(ano, mes, dia)
        if atual in feriados:
            dias.append((atual, 0.0, 0.0, True, feriados[atual]))
            continue
        p_venda, p_inst = _pesos_padrao_por_weekday(atual)
        dias.append((atual, p_venda, p_inst, False, ""))

    pesos_vb = [d[1] for d in dias]
    pesos_gr = [d[2] for d in dias]
    vb_final = _escalar_pesos(pesos_vb, TARGET_DU_VENDAS[mes])
    gr_final = _escalar_pesos(pesos_gr, TARGET_DU_INSTALACAO[mes])

    return [
        (dias[i][0], vb_final[i], gr_final[i], dias[i][3], dias[i][4])
        for i in range(len(dias))
    ]


class Command(BaseCommand):
    help = "Ajusta DU Vendas e DU Instalação de 2026 para os totais mensais da Nio."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula sem gravar no banco.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = bool(options.get("dry_run"))
        ano = 2026
        feriados = _carregar_feriados_2026()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Sincronizando DU Nio {ano}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("Modo dry-run — nenhuma alteração será salva."))

        resumo: list[tuple[int, float, float, float, float]] = []

        with transaction.atomic():
            for mes in range(1, 13):
                registros = _montar_pesos_mes(ano, mes, feriados)
                for data_dia, p_vb, p_gr, eh_feriado, obs in registros:
                    if dry_run:
                        continue
                    DiaFiscal.objects.update_or_create(
                        data=data_dia,
                        defaults={
                            "peso_venda": p_vb,
                            "peso_instalacao": p_gr,
                            "feriado": eh_feriado,
                            "observacao": obs or None,
                        },
                    )

                tot_vb = float(sum(r[1] for r in registros))
                tot_gr = float(sum(r[2] for r in registros))
                resumo.append(
                    (mes, tot_vb, TARGET_DU_VENDAS[mes], tot_gr, TARGET_DU_INSTALACAO[mes])
                )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(f"{'Mês':>4} | {'VB calc':>7} | {'VB Nio':>7} | {'GR calc':>7} | {'GR Nio':>7}")
        self.stdout.write("-" * 44)
        for mes, vb, vb_alvo, gr, gr_alvo in resumo:
            ok_vb = "OK" if abs(vb - vb_alvo) < 0.011 else "!"
            ok_gr = "OK" if abs(gr - gr_alvo) < 0.011 else "!"
            self.stdout.write(
                f"{mes:4d} | {vb:7.2f} | {vb_alvo:7.2f} {ok_vb:>2} | "
                f"{gr:7.2f} | {gr_alvo:7.2f} {ok_gr:>2}"
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry-run concluído."))
        else:
            self.stdout.write(self.style.SUCCESS("\nCalendário fiscal 2026 sincronizado com a Nio."))
