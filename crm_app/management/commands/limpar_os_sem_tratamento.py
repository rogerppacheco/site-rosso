import re
from django.core.management.base import BaseCommand
from django.db import transaction

class Command(BaseCommand):
    help = 'Limpa O.S. de vendas em SEM TRATAMENTO e marca como DUPLICIDADE se o cliente já possuir outra venda com O.S. válida.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Executar as alterações no banco de dados. Sem isso, apenas simula (dry-run).',
        )

    def handle(self, *args, **options):
        from crm_app.models import Venda, StatusCRM, HistoricoAlteracaoVenda

        confirmar = options['confirmar']

        status_sem_tratamento = StatusCRM.objects.filter(nome__iexact='SEM TRATAMENTO', tipo='Tratamento').first()
        status_duplicidade = StatusCRM.objects.filter(nome__iexact='DUPLICIDADE', tipo='Tratamento').first()

        if not status_sem_tratamento or not status_duplicidade:
            self.stdout.write(self.style.ERROR("Erro: Status 'SEM TRATAMENTO' ou 'DUPLICIDADE' não encontrados."))
            return

        # Vendas em SEM TRATAMENTO com ordem_servico preenchida
        qs_auditoria = Venda.objects.filter(
            status_tratamento=status_sem_tratamento,
            ordem_servico__isnull=False
        ).exclude(ordem_servico__exact='')

        total = qs_auditoria.count()
        self.stdout.write(self.style.WARNING(f"Total de vendas 'SEM TRATAMENTO' com O.S. preenchida: {total}"))

        def os_valida(valor):
            if not valor:
                return False
            return bool(re.fullmatch(r'(\d{8}|\d-\d{12})', str(valor).strip()))

        marcadas_duplicidade = 0
        os_limpas = 0

        self.stdout.write("Analisando...")

        with transaction.atomic():
            for venda in qs_auditoria:
                # Buscar outras vendas do mesmo cliente
                outras_vendas = Venda.objects.filter(
                    cliente=venda.cliente
                ).exclude(
                    id=venda.id
                )
                
                is_duplicidade = False
                for outra in outras_vendas:
                    if os_valida(outra.ordem_servico):
                        is_duplicidade = True
                        break

                if is_duplicidade:
                    if confirmar:
                        venda.status_tratamento = status_duplicidade
                        venda.ordem_servico = None
                        venda.save()

                        HistoricoAlteracaoVenda.objects.create(
                            venda=venda,
                            usuario=None,
                            alteracoes={
                                'status_tratamento': "DUPLICIDADE", 
                                'ordem_servico': None,
                                'motivo': "Marcado via script: Cliente já possui outra venda com O.S. válida."
                            }
                        )
                    marcadas_duplicidade += 1
                else:
                    if confirmar:
                        venda.ordem_servico = None
                        venda.save()

                        HistoricoAlteracaoVenda.objects.create(
                            venda=venda,
                            usuario=None,
                            alteracoes={
                                'ordem_servico': None,
                                'motivo': "O.S. removida via script para permitir tratamento na auditoria."
                            }
                        )
                    os_limpas += 1

        self.stdout.write(self.style.SUCCESS("-" * 40))
        if not confirmar:
            self.stdout.write(self.style.WARNING("Modo DRY-RUN (simulação). Nenhuma venda foi alterada."))
            self.stdout.write(self.style.WARNING("Use --confirmar para aplicar as mudanças."))
        
        self.stdout.write(f"Vendas alteradas para DUPLICIDADE (cliente já tinha O.S): {marcadas_duplicidade}")
        self.stdout.write(f"Vendas apenas com a O.S. limpa para tratamento: {os_limpas}")
        self.stdout.write(self.style.SUCCESS("-" * 40))
