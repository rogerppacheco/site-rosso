"""
Lista vendas INSTALADA que entram no recorte da API (Minhas Vendas / badge)
mas não entram no critério do card "Vendas instaladas" do dashboard (OSAB no mês).

Uso:
  python manage.py diagnostico_badge_vs_dashboard --username Gleice
  python manage.py diagnostico_badge_vs_dashboard --username Gleice --ano 2026 --mes 3
"""
from __future__ import annotations

from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from crm_app.models import Venda


class Command(BaseCommand):
    help = 'Compara INSTALADA: lista consultor vs dashboard (OSAB mês fechado)'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='Gleice', help='Username do vendedor')
        parser.add_argument('--ano', type=int, default=None)
        parser.add_argument('--mes', type=int, default=None, help='1-12')

    def handle(self, *args, **options):
        User = get_user_model()
        uname = (options['username'] or '').strip()
        u = User.objects.filter(username__iexact=uname).first()
        if not u:
            u = User.objects.filter(Q(username__icontains=uname) | Q(first_name__icontains=uname)).first()
        if not u:
            self.stderr.write(self.style.ERROR(f'Usuário não encontrado: {uname!r}'))
            return

        hoje = timezone.localtime(timezone.now()).date()
        ano = options['ano'] or hoje.year
        mes = options['mes'] or hoje.month
        inicio_d = date(ano, mes, 1)
        if mes == 12:
            fim_ex_d = date(ano + 1, 1, 1)
        else:
            fim_ex_d = date(ano, mes + 1, 1)

        inicio = timezone.make_aware(datetime(ano, mes, 1, 0, 0, 0))

        self.stdout.write(f'Usuário: {u.id} {u.username} ({u.get_full_name() or "-"})')
        self.stdout.write(f'Período dashboard (OSAB): [{inicio_d}, {fim_ex_d})')
        self.stdout.write('')

        qs_lista = (
            Venda.objects.filter(vendedor=u, ativo=True)
            .filter(Q(data_criacao__gte=inicio) | Q(data_instalacao__gte=inicio_d))
            .filter(status_esteira__nome__iexact='INSTALADA')
        )
        qs_dash = Venda.objects.filter(
            vendedor=u,
            ativo=True,
            status_esteira__nome__iexact='INSTALADA',
            data_instalacao__gte=inicio_d,
            data_instalacao__lt=fim_ex_d,
        )

        ids_lista = set(qs_lista.values_list('id', flat=True))
        ids_dash = set(qs_dash.values_list('id', flat=True))
        so_lista = sorted(ids_lista - ids_dash)

        self.stdout.write(f'INSTALADA (recorte lista consultor): {len(ids_lista)}')
        self.stdout.write(f'INSTALADA (critério dashboard mês): {len(ids_dash)}')
        self.stdout.write(f'Só na lista/badge, não no dashboard: {len(so_lista)}')
        self.stdout.write('')

        if not so_lista:
            self.stdout.write(
                self.style.WARNING(
                    'Nenhuma diferença. Se no site ainda aparece 33 vs 34, este ambiente '
                    'não usa o mesmo banco que o navegador (confira DATABASE_URL / .env).'
                )
            )
            return

        self.stdout.write(self.style.NOTICE('Detalhe (candidatos à venda “extra” no badge):'))
        for vid in so_lista:
            v = Venda.objects.select_related('cliente').get(pk=vid)
            nome = v.cliente.nome_razao_social if v.cliente else '-'
            self.stdout.write(
                f'  id={v.id} | criação={v.data_criacao} | OSAB={v.data_instalacao} | '
                f'física={getattr(v, "data_instalacao_fisica", None)} | OS={v.ordem_servico or "-"} | {nome[:50]}'
            )
