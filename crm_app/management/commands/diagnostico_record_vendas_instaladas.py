"""
Diagnóstico venda por venda das divergências de "Instaladas" no módulo Record Vendas.

Compara, para um vendedor e mês:
1) Visão de Equipe > Instalados (endpoint relatorios/performance-vendas)
2) Dashboard (endpoint dashboard-resumo)
3) Painel Performance > Mensal (endpoint performance-painel)

Uso:
  python manage.py diagnostico_record_vendas_instaladas --vendedor Alex --ano 2026 --mes 3
  python manage.py diagnostico_record_vendas_instaladas --vendedor alex --mes 3 --ano 2026 --limite 200
  python manage.py diagnostico_record_vendas_instaladas --vendedor alex --ano 2026 --mes 3 --csv c:/tmp/diff_instaladas.csv
"""
from __future__ import annotations

import csv
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from crm_app.models import Venda


def _proximo_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


class Command(BaseCommand):
    help = "Diagnóstico de divergência de instaladas: Equipe vs Dashboard vs Performance"

    def add_arguments(self, parser):
        parser.add_argument("--vendedor", required=True, help="Username ou parte do nome (ex.: Alex)")
        parser.add_argument("--vendedor-id", type=int, default=None, help="Força o ID do vendedor (opcional)")
        parser.add_argument("--ano", type=int, required=True, help="Ano de referência (ex.: 2026)")
        parser.add_argument("--mes", type=int, required=True, help="Mês de referência (1-12)")
        parser.add_argument("--limite", type=int, default=120, help="Limite de linhas de detalhe")
        parser.add_argument("--csv", default="", help="Caminho CSV de saída (opcional)")

    def handle(self, *args, **options):
        ano = int(options["ano"])
        mes = int(options["mes"])
        if mes < 1 or mes > 12:
            self.stdout.write(self.style.ERROR("Mês inválido. Use 1-12."))
            return

        vendedor_raw = (options["vendedor"] or "").strip()
        limite = int(options["limite"] or 120)
        csv_path = (options["csv"] or "").strip()

        User = get_user_model()
        vendedor_id_forcado = options.get("vendedor_id")
        vendedor = None
        if vendedor_id_forcado:
            vendedor = User.objects.filter(id=vendedor_id_forcado).first()
            if not vendedor:
                self.stdout.write(self.style.ERROR(f"Vendedor com id={vendedor_id_forcado} não encontrado."))
                return
        else:
            vendedor = User.objects.filter(username__iexact=vendedor_raw).first()
            if not vendedor:
                candidatos = list(
                    User.objects.filter(
                        Q(username__icontains=vendedor_raw)
                        | Q(first_name__icontains=vendedor_raw)
                        | Q(last_name__icontains=vendedor_raw)
                    )
                    .order_by("username")
                    .values("id", "username", "first_name", "last_name", "is_active")[:20]
                )
                if not candidatos:
                    vendedor = None
                elif len(candidatos) == 1:
                    vendedor = User.objects.filter(id=candidatos[0]["id"]).first()
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            "Mais de um vendedor encontrado. Rode novamente com --vendedor-id para evitar ambiguidade."
                        )
                    )
                    for c in candidatos:
                        nome = f"{c.get('first_name') or ''} {c.get('last_name') or ''}".strip() or "-"
                        self.stdout.write(
                            f"  id={c['id']} username={c['username']} nome={nome} ativo={c['is_active']}"
                        )
                    return
        if not vendedor:
            self.stdout.write(self.style.ERROR(f"Vendedor não encontrado: {vendedor_raw!r}"))
            return

        inicio = date(ano, mes, 1)
        fim_exclusivo = _proximo_mes(inicio)

        # 1) VISÃO DE EQUIPE > INSTALADOS (PerformanceVendasView)
        # Regras atuais:
        # - ativo=True
        # - status_tratamento preenchido
        # - status_esteira != CANCELADA (ou nulo)
        # - total_mes_instalado: status INSTALADA + data efetiva no mês (física ou OSAB)
        filtro_base_equipe = (
            Q(ativo=True)
            & Q(status_tratamento__isnull=False)
            & (Q(status_esteira__isnull=True) | ~Q(status_esteira__nome__iexact="CANCELADA"))
        )
        qs_equipe = Venda.objects.filter(
            filtro_base_equipe,
            vendedor_id=vendedor.id,
            status_esteira__nome__iexact="INSTALADA",
            data_pedido__date__gte=inicio,
        )
        ids_equipe = set(qs_equipe.values_list("id", flat=True))

        # 2) DASHBOARD (DashboardResumoView -> total_instaladas)
        qs_dashboard = Venda.objects.filter(
            ativo=True,
            vendedor_id=vendedor.id,
            status_esteira__nome__iexact="INSTALADA",
            data_instalacao__gte=inicio,
            data_instalacao__lt=fim_exclusivo,
        )
        ids_dashboard = set(qs_dashboard.values_list("id", flat=True))

        # 3) PERFORMANCE MENSAL (PainelPerformanceView -> instaladas)
        # Regras atuais:
        # - ativo=True
        # - ordem_servico preenchida (inclui reemissão no mensal)
        # - status_esteira == INSTALADA
        # - data efetiva no mês:
        #     data_instalacao_fisica no mês OU (sem física e data_instalacao no mês)
        filtro_os = Q(ativo=True) & ~Q(ordem_servico="") & Q(ordem_servico__isnull=False)
        filtro_data_efetiva = (
            (Q(data_instalacao_fisica__isnull=False) & Q(data_instalacao_fisica__gte=inicio) & Q(data_instalacao_fisica__lt=fim_exclusivo))
            | (Q(data_instalacao_fisica__isnull=True) & Q(data_instalacao__gte=inicio) & Q(data_instalacao__lt=fim_exclusivo))
        )
        qs_performance = Venda.objects.filter(
            filtro_os,
            vendedor_id=vendedor.id,
            status_esteira__nome__iexact="INSTALADA",
        ).filter(filtro_data_efetiva)
        ids_performance = set(qs_performance.values_list("id", flat=True))

        uniao_ids = ids_equipe | ids_dashboard | ids_performance
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"Vendedor: {vendedor.username} (id={vendedor.id})"))
        self.stdout.write(self.style.NOTICE(f"Período: {inicio} a {fim_exclusivo} (fim exclusivo)"))
        self.stdout.write("")
        self.stdout.write("--- CONTAGENS ---")
        self.stdout.write(f"Visão Equipe > Instalados: {len(ids_equipe)}")
        self.stdout.write(f"Dashboard > Instaladas: {len(ids_dashboard)}")
        self.stdout.write(f"Performance > Mensal > Instaladas: {len(ids_performance)}")
        self.stdout.write("")

        self._print_diff("Equipe - Dashboard", ids_equipe, ids_dashboard)
        self._print_diff("Equipe - Performance", ids_equipe, ids_performance)
        self._print_diff("Dashboard - Performance", ids_dashboard, ids_performance)

        self.stdout.write("")
        self.stdout.write("--- DIAGNÓSTICO VENDA POR VENDA (diferenças) ---")
        ids_divergentes = sorted(
            vid
            for vid in uniao_ids
            if not (
                (vid in ids_equipe)
                and (vid in ids_dashboard)
                and (vid in ids_performance)
            )
        )
        if not ids_divergentes:
            self.stdout.write(self.style.SUCCESS("Nenhuma divergência entre as 3 visões para esse vendedor/mês."))
            return

        qs_det = (
            Venda.objects.filter(id__in=ids_divergentes)
            .select_related("status_esteira", "status_tratamento", "cliente")
            .only(
                "id",
                "ordem_servico",
                "data_pedido",
                "data_criacao",
                "data_instalacao",
                "data_instalacao_fisica",
                "status_esteira__nome",
                "status_tratamento__nome",
                "cliente__nome_razao_social",
            )
            .order_by("id")
        )

        linhas = []
        for v in qs_det:
            status_nome = ((v.status_esteira.nome if v.status_esteira else "") or "").strip()
            status_up = status_nome.upper()
            is_inst_exata = status_up == "INSTALADA"
            is_inst_contains = "INSTALADA" in status_up
            is_inst_outro_pdv = status_up == "INSTALADA OUTRO PDV"
            has_os = bool(v.ordem_servico and str(v.ordem_servico).strip())
            has_status_trat = v.status_tratamento_id is not None
            data_pedido_date = v.data_pedido.date() if v.data_pedido else None

            motivo = []
            if not has_os:
                motivo.append("sem_os")
            if not has_status_trat:
                motivo.append("sem_status_tratamento")
            if data_pedido_date and data_pedido_date < inicio:
                motivo.append("data_pedido_antes_mes")
            if not (v.data_instalacao and inicio <= v.data_instalacao < fim_exclusivo):
                motivo.append("fora_mes_data_instalacao_osab")
            dt_efetiva = v.data_instalacao_fisica or v.data_instalacao
            if not (dt_efetiva and inicio <= dt_efetiva < fim_exclusivo):
                motivo.append("fora_mes_data_efetiva")
            if is_inst_contains and not is_inst_exata:
                motivo.append("status_instalada_nao_exata")
            if is_inst_outro_pdv:
                motivo.append("status_instalada_outro_pdv")

            linhas.append(
                {
                    "id": v.id,
                    "cliente": (v.cliente.nome_razao_social if v.cliente else "-")[:60],
                    "status": status_nome or "-",
                    "equipe": "S" if v.id in ids_equipe else "N",
                    "dashboard": "S" if v.id in ids_dashboard else "N",
                    "performance": "S" if v.id in ids_performance else "N",
                    "os": v.ordem_servico or "-",
                    "dt_pedido": str(data_pedido_date) if data_pedido_date else "-",
                    "dt_inst_osab": str(v.data_instalacao) if v.data_instalacao else "-",
                    "dt_inst_fisica": str(v.data_instalacao_fisica) if v.data_instalacao_fisica else "-",
                    "motivos": ",".join(motivo) if motivo else "regra_especifica_da_tela",
                }
            )

        for row in linhas[: max(limite, 1)]:
            self.stdout.write(
                f"id={row['id']} | EQ={row['equipe']} DB={row['dashboard']} PF={row['performance']} "
                f"| status={row['status']} | os={row['os']} | pedido={row['dt_pedido']} "
                f"| osab={row['dt_inst_osab']} | fisica={row['dt_inst_fisica']} | motivos={row['motivos']}"
            )

        if len(linhas) > limite:
            self.stdout.write(
                self.style.WARNING(f"... {len(linhas) - limite} linhas adicionais omitidas (use --limite maior).")
            )

        # Extra: procurar status que "contêm INSTALADA" mas não são exatamente INSTALADA.
        # Ajuda a validar o caso "INSTALADA OUTRO PDV".
        self.stdout.write("")
        self.stdout.write("--- STATUS COM 'INSTALADA' MAS DIFERENTE DE 'INSTALADA' ---")
        qs_status_nao_exato = Venda.objects.filter(
            vendedor_id=vendedor.id,
            ativo=True,
            status_esteira__nome__icontains="INSTALADA",
        ).exclude(status_esteira__nome__iexact="INSTALADA")
        ids_status_nao_exato = list(qs_status_nao_exato.values_list("id", flat=True))
        self.stdout.write(f"Total (qualquer período): {len(ids_status_nao_exato)}")
        if ids_status_nao_exato:
            amostra = list(
                qs_status_nao_exato.select_related("status_esteira")
                .only("id", "status_esteira__nome", "data_instalacao", "data_instalacao_fisica", "ordem_servico")
                .order_by("-id")[: min(30, len(ids_status_nao_exato))]
            )
            for v in amostra:
                self.stdout.write(
                    f"  id={v.id} status={v.status_esteira.nome if v.status_esteira else '-'} "
                    f"os={v.ordem_servico or '-'} osab={v.data_instalacao} fisica={v.data_instalacao_fisica}"
                )

        if csv_path:
            self._write_csv(csv_path, linhas)
            self.stdout.write(self.style.SUCCESS(f"CSV gerado: {csv_path}"))

    def _print_diff(self, titulo: str, a: set[int], b: set[int]) -> None:
        self.stdout.write(f"[{titulo}]")
        self.stdout.write(f"  Só no primeiro: {len(a - b)} | Só no segundo: {len(b - a)}")

    def _write_csv(self, path: str, rows: list[dict]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "cliente",
                    "status",
                    "equipe",
                    "dashboard",
                    "performance",
                    "os",
                    "dt_pedido",
                    "dt_inst_osab",
                    "dt_inst_fisica",
                    "motivos",
                ],
            )
            w.writeheader()
            for row in rows:
                w.writerow(row)
