import re
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

class Command(BaseCommand):
    help = 'Cruza as vendas na Auditoria com o HistoricoPapPedido para buscar a O.S. e avançar para a esteira (CADASTRADA -> AGENDADO).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Executar as alterações no banco de dados. Sem isso, apenas simula (dry-run).',
        )

    def handle(self, *args, **options):
        from crm_app.models import Venda, HistoricoPapPedido, StatusCRM, HistoricoAlteracaoVenda

        confirmar = options['confirmar']

        qs_auditoria = Venda.objects.filter(
            status_tratamento__isnull=False,
            status_esteira__isnull=True
        ).exclude(status_tratamento__estado__iexact='FECHADO')

        total_auditoria = qs_auditoria.count()
        self.stdout.write(self.style.WARNING(f"Total de vendas na auditoria: {total_auditoria}"))

        status_cadastrada = StatusCRM.objects.filter(nome__iexact='CADASTRADA', tipo='Tratamento').first()
        status_agendado = StatusCRM.objects.filter(nome__iexact='AGENDADO', tipo='Esteira').first()

        if not status_cadastrada or not status_agendado:
            self.stdout.write(self.style.ERROR("Erro: Status CADASTRADA ou AGENDADO não encontrados no banco de dados."))
            return

        def os_valida(valor):
            if not valor:
                return False
            return bool(re.fullmatch(r'(\d{8}|\d-\d{12})', str(valor).strip()))

        def extract_os_from_payload(payload):
            if not isinstance(payload, dict):
                return None
            
            # Tentar chaves conhecidas
            possiveis_chaves = [
                'OS instalação', 'os_instalacao', 'osInstalacao', 
                'ordem_servico', 'os', 'OS'
            ]
            for k in possiveis_chaves:
                if k in payload and payload[k]:
                    val = str(payload[k]).strip()
                    if os_valida(val):
                        return val

            # Busca genérica
            for k, v in payload.items():
                if isinstance(k, str) and 'os' in k.lower() and 'instala' in k.lower():
                    if v and os_valida(str(v).strip()):
                        return str(v).strip()
            
            return None

        sucesso = 0
        erros = 0
        sem_pap = 0
        sem_os = 0

        self.stdout.write("Analisando...")

        with transaction.atomic():
            for venda in qs_auditoria:
                pedido_pap = venda.pedido_pap
                if not pedido_pap:
                    sem_pap += 1
                    continue

                historico = HistoricoPapPedido.objects.filter(numero_pedido=pedido_pap).last()
                if not historico:
                    sem_pap += 1
                    continue

                # Pega OS da Venda (se já existir) ou do HistoricoPapPedido
                os_encontrada = None
                if os_valida(venda.ordem_servico):
                    os_encontrada = str(venda.ordem_servico).strip()
                elif historico.payload:
                    os_encontrada = extract_os_from_payload(historico.payload)

                if os_encontrada:
                    if confirmar:
                        venda.ordem_servico = os_encontrada
                        venda.status_tratamento = status_cadastrada
                        venda.data_abertura = timezone.now()
                        venda.status_esteira = status_agendado
                        venda.auditor_atual = None
                        venda.save()

                        HistoricoAlteracaoVenda.objects.create(
                            venda=venda,
                            usuario=None,
                            alteracoes={
                                'status_tratamento': "Auditoria finalizada via script: CADASTRADA", 
                                'dados_editados': True,
                                'ordem_servico': os_encontrada
                            }
                        )
                    sucesso += 1
                else:
                    sem_os += 1

        self.stdout.write(self.style.SUCCESS("-" * 40))
        if not confirmar:
            self.stdout.write(self.style.WARNING("Modo DRY-RUN (simulação). Nenhuma venda foi alterada."))
            self.stdout.write(self.style.WARNING("Use --confirmar para aplicar as mudanças."))
        
        self.stdout.write(f"Vendas processadas com O.S. (podem avançar): {sucesso}")
        self.stdout.write(f"Vendas sem histórico PAP ou sem pedido_pap: {sem_pap}")
        self.stdout.write(f"Vendas sem O.S. válida no PAP/CRM: {sem_os}")
        self.stdout.write(self.style.SUCCESS("-" * 40))
