"""
Comando para liberar manualmente BOs PAP travados (PapBoEmUso).

Use quando uma sessão de venda falhou e o BO ficou marcado como "em uso"
sem ser liberado (ex: timeout ao acessar PAP, crash, etc).

Quando a limpeza roda:
- Automático: a cada tentativa de VENDER, locks com mais de 30 min são removidos.
- Manual: use este comando para liberar agora.

Exemplos:
  python manage.py liberar_pap_bo --listar          # exibe BOs em uso
  python manage.py liberar_pap_bo --expirados       # remove só locks > 30 min
  python manage.py liberar_pap_bo --telefone=553188804000
  python manage.py liberar_pap_bo --todos           # libera TODOS os BOs
"""
from django.core.management.base import BaseCommand

from crm_app.models import PapBoEmUso
from crm_app.pool_bo_pap import limpar_sessoes_expiradas


class Command(BaseCommand):
    help = 'Libera manualmente BOs PAP travados (PapBoEmUso)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--telefone',
            type=str,
            help='Telefone do vendedor cujo BO deve ser liberado (ex: 553188804000)',
        )
        parser.add_argument(
            '--todos',
            action='store_true',
            help='Libera TODOS os BOs atualmente em uso',
        )
        parser.add_argument(
            '--expirados',
            action='store_true',
            help='Remove apenas locks com mais de 30 minutos (mesma regra automática)',
        )
        parser.add_argument(
            '--listar',
            action='store_true',
            help='Lista os BOs em uso sem liberar',
        )

    def handle(self, *args, **options):
        if options['listar']:
            self._listar()
            return

        if options['telefone']:
            self._liberar_por_telefone(options['telefone'])
        elif options['todos']:
            self._liberar_todos()
        elif options['expirados']:
            self._liberar_expirados()
        else:
            self.stdout.write(
                self.style.WARNING(
                    'Use --listar, --expirados, --telefone=NNNN ou --todos. '
                    'Exemplo: liberar_pap_bo --todos  (libera todos agora)'
                )
            )

    def _listar(self):
        qs = PapBoEmUso.objects.select_related('bo_usuario').all()
        if not qs.exists():
            self.stdout.write(self.style.SUCCESS('Nenhum BO em uso no momento.'))
            return
        self.stdout.write(f'BOs em uso ({qs.count()}):')
        for r in qs:
            self.stdout.write(
                f'  - BO: {r.bo_usuario.username} (id={r.bo_usuario_id}) | '
                f'Vendedor: {r.vendedor_telefone} | Locked: {r.locked_at}'
            )

    def _liberar_por_telefone(self, telefone: str):
        deletados = PapBoEmUso.objects.filter(vendedor_telefone=telefone).delete()
        n = deletados[0]
        if n > 0:
            self.stdout.write(self.style.SUCCESS(f'Liberado {n} BO(s) para telefone {telefone}'))
        else:
            self.stdout.write(
                self.style.WARNING(f'Nenhum BO encontrado para telefone {telefone}')
            )

    def _liberar_expirados(self):
        n = limpar_sessoes_expiradas()
        if n > 0:
            self.stdout.write(self.style.SUCCESS(f'Liberados {n} BO(s) expirado(s) (> 30 min).'))
        else:
            self.stdout.write(self.style.SUCCESS('Nenhum lock expirado para remover.'))

    def _liberar_todos(self):
        total = PapBoEmUso.objects.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('Nenhum BO em uso.'))
            return
        PapBoEmUso.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Liberados {total} BO(s).'))
