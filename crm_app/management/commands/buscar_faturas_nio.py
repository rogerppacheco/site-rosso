from django.core.management.base import BaseCommand
from crm_app.models import ContratoM10, FaturaM10
from crm_app.services_nio import buscar_fatura_nio_por_cpf
from datetime import datetime


class Command(BaseCommand):
    help = 'Busca automaticamente faturas no site da Nio para contratos com CPF'

    def add_arguments(self, parser):
        parser.add_argument(
            '--safra-id',
            type=int,
            help='ID da safra para processar (opcional)',
        )
        parser.add_argument(
            '--contrato-id',
            type=int,
            help='ID de um contrato específico (opcional)',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=10,
            help='Número máximo de contratos a processar (padrão: 10)',
        )

    def handle(self, *args, **options):
        safra_id = options.get('safra_id')
        contrato_id = options.get('contrato_id')
        limite = options.get('limite')

        self.stdout.write(self.style.WARNING('\n🤖 Iniciando busca automática de faturas no site da Nio...\n'))

        # Filtra contratos
        queryset = ContratoM10.objects.exclude(cpf_cliente__isnull=True).exclude(cpf_cliente='')

        if contrato_id:
            queryset = queryset.filter(id=contrato_id)
        elif safra_id:
            queryset = queryset.filter(safra_id=safra_id)

        queryset = queryset[:limite]
        total_contratos = queryset.count()

        if total_contratos == 0:
            self.stdout.write(self.style.WARNING('⚠️  Nenhum contrato com CPF encontrado.\n'))
            return

        self.stdout.write(f'📋 {total_contratos} contrato(s) serão processados.\n')

        sucesso = 0
        erro = 0
        sem_dados = 0

        for idx, contrato in enumerate(queryset, 1):
            self.stdout.write(f'\n[{idx}/{total_contratos}] Processando: {contrato.numero_contrato} - {contrato.cliente_nome}')
            self.stdout.write(f'  CPF: {contrato.cpf_cliente}')

            try:
                # Busca fatura no site da Nio
                dados = buscar_fatura_nio_por_cpf(contrato.cpf_cliente)

                if not dados:
                    self.stdout.write(self.style.ERROR('  ❌ Não foi possível buscar a fatura'))
                    erro += 1
                    continue

                if not any([dados['valor'], dados['codigo_pix'], dados['codigo_barras']]):
                    self.stdout.write(self.style.WARNING('  ⚠️  Fatura sem dados disponíveis'))
                    sem_dados += 1
                    continue

                # Atualiza/cria primeira fatura
                fatura, created = FaturaM10.objects.get_or_create(
                    contrato=contrato,
                    numero_fatura=1,
                    defaults={
                        'valor': dados['valor'] or 0,
                        'data_vencimento': dados['data_vencimento'] or datetime.now().date(),
                        'status': 'NAO_PAGO'
                    }
                )

                # Atualiza campos
                if dados['valor']:
                    fatura.valor = dados['valor']
                    self.stdout.write(f'  💰 Valor: R$ {dados["valor"]:.2f}')

                if dados['data_vencimento']:
                    fatura.data_vencimento = dados['data_vencimento']
                    self.stdout.write(f'  📅 Vencimento: {dados["data_vencimento"].strftime("%d/%m/%Y")}')

                if dados['codigo_pix']:
                    fatura.codigo_pix = dados['codigo_pix']
                    self.stdout.write('  ✅ Código PIX capturado')

                if dados['codigo_barras']:
                    fatura.codigo_barras = dados['codigo_barras']
                    self.stdout.write('  ✅ Código de barras capturado')

                if dados['pdf_url']:
                    fatura.pdf_url = dados['pdf_url']
                    self.stdout.write('  🔗 Link do PDF salvo')

                fatura.save()
                self.stdout.write(self.style.SUCCESS('  ✅ Fatura salva com sucesso!'))
                sucesso += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ❌ Erro: {str(e)}'))
                erro += 1

        # Resumo
        self.stdout.write(self.style.SUCCESS(f'\n\n📊 RESUMO:'))
        self.stdout.write(f'  ✅ Sucesso: {sucesso}')
        self.stdout.write(f'  ❌ Erro: {erro}')
        self.stdout.write(f'  ⚠️  Sem dados: {sem_dados}')
        self.stdout.write(f'  📋 Total: {total_contratos}\n')
