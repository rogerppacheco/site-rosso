"""
Diagnóstico: diferença entre contagem de INSTALADAS (mensal) na tela Performance,
na exportação Excel (aba Mês Atual) e no Dashboard (Record Vendas).

Replica as regras atuais de crm_app/views.py (PainelPerformanceView,
ExportarPerformanceExcelView, DashboardResumoView) sem alterar dados.

Uso:
  python manage.py diagnostico_diff_instaladas_mensal
  python manage.py diagnostico_diff_instaladas_mensal --ano 2026 --mes 3
  python manage.py diagnostico_diff_instaladas_mensal --gestao
  python manage.py diagnostico_diff_instaladas_mensal --consultor
  python manage.py diagnostico_diff_instaladas_mensal --canal PAP --cluster CLUSTER_1
  python manage.py diagnostico_diff_instaladas_mensal --limite-detalhes 30
  python manage.py diagnostico_diff_instaladas_mensal --csv-saida /tmp/diff_ids.csv

Notas:
  - O Painel hoje usa data_instalacao >= dia 1 do mês SEM limite superior (igual ao código).
  - O Dashboard usa intervalo [início do mês, primeiro dia do mês seguinte).
  - A aba "Mês Atual" do Excel inclui (criação no mês) OU (instalada no mês pela regra
    de datas); não exige OS para entrar pelo ramo "instalada no mês".
  - A coluna "instaladas" do Painel exige OS preenchida (filtro_os_com_reemissao).
"""
from __future__ import annotations

import csv
from datetime import date

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from crm_app.models import Venda


def _proximo_mes(d: date) -> date:
    return d + relativedelta(months=1)


def _users_base():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.filter(is_active=True).exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])


class Command(BaseCommand):
    help = 'Compara INSTALADAS mensal: Performance (tela) vs Export Performance vs Dashboard'

    def add_arguments(self, parser):
        parser.add_argument('--ano', type=int, default=None, help='Ano (default: mês atual)')
        parser.add_argument('--mes', type=int, default=None, help='Mês 1-12 (default: mês atual)')
        parser.add_argument(
            '--gestao',
            action='store_true',
            help='Simular perfil gestão (Painel/Export: data OSAB para instalação no mês)',
        )
        parser.add_argument(
            '--consultor',
            action='store_true',
            help='Simular perfil não-gestão (data física se preenchida, senão OSAB)',
        )
        parser.add_argument('--canal', default='', help='Filtro canal (ex.: PAP), vazio = todos')
        parser.add_argument('--cluster', default='', help='Filtro cluster, vazio = todos')
        parser.add_argument(
            '--limite-detalhes',
            type=int,
            default=25,
            help='Quantos IDs listar por categoria de diferença (default 25)',
        )
        parser.add_argument(
            '--csv-saida',
            default='',
            help='Se informado, grava CSV com colunas categoria,id_venda',
        )
        parser.add_argument(
            '--vendedor-ativo',
            default='todos',
            choices=('todos', 'ativos', 'inativos'),
            help='Alinhado ao Painel: todos|ativos|inativos (default: todos)',
        )

    def handle(self, *args, **options):
        hoje = timezone.localtime(timezone.now()).date()
        ano = options['ano'] or hoje.year
        mes = options['mes'] or hoje.month
        inicio_mes = date(ano, mes, 1)
        fim_mes_exclusivo = _proximo_mes(inicio_mes)

        if options['gestao'] and options['consultor']:
            self.stdout.write(self.style.ERROR('Use apenas um: --gestao ou --consultor'))
            return

        eh_gestao = True
        if options['consultor']:
            eh_gestao = False
        elif options['gestao']:
            eh_gestao = True
        else:
            # Default explícito: gestão (mesma leitura que Diretoria no Painel)
            eh_gestao = True

        users = _users_base()
        canal = (options['canal'] or '').strip()
        cluster = (options['cluster'] or '').strip()
        if canal:
            users = users.filter(canal__iexact=canal)
        if cluster:
            users = users.filter(cluster__iexact=cluster)

        va = options['vendedor_ativo']
        if va == 'ativos':
            users = users.filter(is_active=True)
        elif va == 'inativos':
            users = users.filter(is_active=False)
        # todos: sem filtro is_active

        user_ids = list(users.values_list('id', flat=True))
        if not user_ids:
            self.stdout.write(self.style.WARNING('Nenhum usuário na base filtrada.'))
            return

        # --- 1) Painel Performance: "instaladas" mensal (Count por vendedor, somamos IDs) ---
        filtro_os = (
            Q(ativo=True)
            & ~Q(ordem_servico='')
            & Q(ordem_servico__isnull=False)
        )
        filtro_inst = Q(status_esteira__nome__iexact='INSTALADA')

        if eh_gestao:
            filtro_data_performance = Q(data_instalacao__gte=inicio_mes)
        else:
            filtro_data_performance = (
                Q(data_instalacao_fisica__isnull=False) & Q(data_instalacao_fisica__gte=inicio_mes)
            ) | (
                Q(data_instalacao_fisica__isnull=True)
                & Q(data_instalacao__gte=inicio_mes)
            )

        qs_tela = (
            Venda.objects.filter(filtro_os & filtro_inst & filtro_data_performance, vendedor_id__in=user_ids)
            .order_by('id')
        )
        ids_tela = set(qs_tela.values_list('id', flat=True))

        # Versão alternativa: mês fechado [inicio, próximo_mês) — para comparar com Dashboard
        if eh_gestao:
            filtro_data_mes_fechado = Q(
                data_instalacao__gte=inicio_mes,
                data_instalacao__lt=fim_mes_exclusivo,
            )
        else:
            filtro_data_mes_fechado = (
                Q(data_instalacao_fisica__isnull=False)
                & Q(data_instalacao_fisica__gte=inicio_mes)
                & Q(data_instalacao_fisica__lt=fim_mes_exclusivo)
            ) | (
                Q(data_instalacao_fisica__isnull=True)
                & Q(data_instalacao__gte=inicio_mes)
                & Q(data_instalacao__lt=fim_mes_exclusivo)
            )

        ids_tela_mes_fechado = set(
            Venda.objects.filter(filtro_os & filtro_inst & filtro_data_mes_fechado, vendedor_id__in=user_ids)
            .values_list('id', flat=True)
        )

        # --- 2) Export Performance: aba Mês Atual (mesmo vendedor_id__in que o Painel; canal/cluster já em user_ids)
        vendas = Venda.objects.filter(ativo=True, vendedor_id__in=user_ids).select_related(
            'status_esteira', 'vendedor'
        )

        use_data_efetiva = not eh_gestao
        if use_data_efetiva:
            filtro_instalacao_mes_export = (
                Q(data_instalacao_fisica__isnull=False) & Q(data_instalacao_fisica__gte=inicio_mes)
            ) | (
                Q(data_instalacao_fisica__isnull=True) & Q(data_instalacao__gte=inicio_mes)
            )
        else:
            filtro_instalacao_mes_export = Q(data_instalacao__gte=inicio_mes)

        vendas_mes_export = vendas.filter(
            Q(data_criacao__date__gte=inicio_mes)
            | (Q(status_esteira__nome__iexact='INSTALADA') & filtro_instalacao_mes_export)
        ).distinct()

        ids_export_aba = set(vendas_mes_export.values_list('id', flat=True))

        ids_export_instaladas = set(
            vendas_mes_export.filter(status_esteira__nome__iexact='INSTALADA').values_list('id', flat=True)
        )

        # --- 3) Dashboard: intervalo do mês em data_instalacao (OSAB), equivalente a
        # data_instalacao__gte primeiro dia 00:00 e __lt primeiro dia mês seguinte (Venda.data_instalacao é DateField)
        qs_dash = Venda.objects.filter(
            ativo=True,
            vendedor_id__in=user_ids,
            status_esteira__nome__iexact='INSTALADA',
            data_instalacao__gte=inicio_mes,
            data_instalacao__lt=fim_mes_exclusivo,
        )

        ids_dashboard = set(qs_dash.values_list('id', flat=True))

        # --- Relatório ---
        lim = options['limite_detalhes']
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(f'Período: {inicio_mes} a {fim_mes_exclusivo} (exclusivo fim)'))
        self.stdout.write(
            f'Modo simulado: {"gestão (OSAB no Painel/Export)" if eh_gestao else "não-gestão (física/OSAB efetiva)"}'
        )
        self.stdout.write(
            f'Filtros: canal={canal or "(todos)"} cluster={cluster or "(todos)"} vendedor_ativo={va}'
        )
        self.stdout.write('')
        self.stdout.write('--- Contagens ---')
        self.stdout.write(f'Painel Performance (tela) instaladas — regra ATUAL (>= {inicio_mes}, sem teto): {len(ids_tela)}')
        self.stdout.write(
            f'Painel Performance instaladas — MÊS FECHADO [início, próximo_mês): {len(ids_tela_mes_fechado)}'
        )
        self.stdout.write(f'Dashboard (Record Vendas) instaladas — OSAB mês fechado: {len(ids_dashboard)}')
        self.stdout.write(f'Export aba "Mês Atual" — total de linhas (todas): {len(ids_export_aba)}')
        self.stdout.write(f'Export aba "Mês Atual" — só status INSTALADA: {len(ids_export_instaladas)}')
        self.stdout.write('')

        self.stdout.write('--- Diferenças de conjuntos (IDs) ---')
        self._diff('tela (>= início mês) vs Dashboard (mês fechado OSAB)', ids_tela, ids_dashboard, lim)
        self._diff('tela (>= início mês) vs tela (mês fechado)', ids_tela, ids_tela_mes_fechado, lim)
        self._diff('tela (>= início) vs Export INSTALADA na aba mês', ids_tela, ids_export_instaladas, lim)
        self._diff('Export INSTALADA vs tela (>= início)', ids_export_instaladas, ids_tela, lim)
        self._diff('Dashboard vs tela (>= início)', ids_dashboard, ids_tela, lim)

        # Explicação: só no export (instaladas), não na tela — típico sem OS
        so_export = ids_export_instaladas - ids_tela
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('--- Hipóteses para IDs só no Export (INSTALADA) e não no Painel ---'))
        self._explicar_sem_os(so_export, lim)

        self.stdout.write('')
        self.stdout.write(self.style.WARNING('--- Hipóteses para IDs só no Painel e não no Export (aba mês) ---'))
        so_tela = ids_tela - ids_export_aba
        self._explicar_somente_tela(so_tela, inicio_mes, lim)

        csv_path = (options['csv_saida'] or '').strip()
        if csv_path:
            self._gravar_csv(
                csv_path,
                [
                    ('painel_tela_ge_inicio', ids_tela),
                    ('painel_mes_fechado', ids_tela_mes_fechado),
                    ('dashboard_osab_mes_fechado', ids_dashboard),
                    ('export_aba_mes_todas', ids_export_aba),
                    ('export_aba_mes_somente_instalada', ids_export_instaladas),
                    ('so_export_instalada_nao_tela', so_export),
                    ('so_tela_nao_export_aba', so_tela),
                ],
            )
            self.stdout.write(self.style.SUCCESS(f'CSV gravado em: {csv_path}'))

    def _diff(self, titulo, a: set, b: set, lim: int):
        apenas_a = sorted(a - b)
        apenas_b = sorted(b - a)
        self.stdout.write(f'[{titulo}]')
        self.stdout.write(f'  só no primeiro conjunto: {len(apenas_a)}  |  só no segundo: {len(apenas_b)}')
        if apenas_a:
            self.stdout.write(f'  IDs (amostra): {apenas_a[:lim]}')
        if apenas_b:
            self.stdout.write(f'  IDs (amostra): {apenas_b[:lim]}')

    def _explicar_sem_os(self, ids: set, lim: int):
        if not ids:
            self.stdout.write('  (nenhum)')
            return
        amostra = list(ids)[: max(lim, 1)]
        qs = Venda.objects.filter(id__in=amostra).only(
            'id', 'ordem_servico', 'reemissao', 'data_instalacao', 'data_instalacao_fisica', 'status_esteira_id'
        )
        for v in qs:
            sem_os = not (v.ordem_servico and str(v.ordem_servico).strip())
            self.stdout.write(
                f'  id={v.id} sem_os={sem_os} reemissao={getattr(v, "reemissao", None)} '
                f'dt_osab={v.data_instalacao} dt_fisica={getattr(v, "data_instalacao_fisica", None)}'
            )

    def _explicar_somente_tela(self, ids: set, inicio_mes: date, lim: int):
        if not ids:
            self.stdout.write('  (nenhum)')
            return
        amostra = sorted(ids)[:lim]
        qs = Venda.objects.filter(id__in=amostra).only(
            'id',
            'data_criacao',
            'data_instalacao',
            'data_instalacao_fisica',
            'status_esteira_id',
        )
        for v in qs:
            dc = timezone.localtime(v.data_criacao).date() if v.data_criacao else None
            ramo = 'criacao_no_mes' if dc and dc >= inicio_mes else 'outro'
            self.stdout.write(
                f'  id={v.id} data_criacao_local={dc} ramo_export_esperado={ramo} '
                f'dt_osab={v.data_instalacao} dt_fisica={getattr(v, "data_instalacao_fisica", None)}'
            )

    def _gravar_csv(self, path: str, grupos: list[tuple[str, set]]):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['categoria', 'id_venda'])
            for nome, ids in grupos:
                for vid in sorted(ids):
                    w.writerow([nome, vid])
