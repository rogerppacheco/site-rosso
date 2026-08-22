"""
Comando para verificar blocos cadastrados para um condomínio CDOI.
Uso: python manage.py verificar_blocos_cdoi "Nome do Condomínio"
"""
from django.core.management.base import BaseCommand
from crm_app.models import CdoiSolicitacao, CdoiBloco


class Command(BaseCommand):
    help = 'Verifica blocos cadastrados para um condomínio CDOI'

    def add_arguments(self, parser):
        parser.add_argument(
            'nome_condominio',
            type=str,
            nargs='?',
            help='Nome do condomínio (pode ser parcial)',
        )
        parser.add_argument(
            '--todos',
            action='store_true',
            help='Lista todos os condomínios com seus blocos',
        )

    def handle(self, *args, **options):
        nome_condominio = options.get('nome_condominio')
        listar_todos = options.get('todos', False)

        if listar_todos:
            # Lista todos os condomínios
            condominios = CdoiSolicitacao.objects.all().order_by('nome_condominio')
            self.stdout.write(self.style.SUCCESS(f'\n=== Total de Condomínios: {condominios.count()} ===\n'))
            
            for cdoi in condominios:
                blocos = cdoi.blocos.all()
                self.stdout.write(f'\n[cdoi] {cdoi.nome_condominio} (ID: {cdoi.id})')
                self.stdout.write(f'   Status: {cdoi.status}')
                self.stdout.write(f'   Total HPs: {cdoi.total_hps}')
                self.stdout.write(f'   Blocos cadastrados: {blocos.count()}')
                
                if blocos.exists():
                    for b in blocos:
                        self.stdout.write(
                            f'      - {b.nome_bloco}: {b.andares} andares, '
                            f'{b.unidades_por_andar} aptos/andar, '
                            f'Total: {b.total_hps_bloco} HPs'
                        )
                else:
                    self.stdout.write(self.style.WARNING('      [AVISO] Nenhum bloco cadastrado!'))
        
        elif nome_condominio:
            # Busca específica
            condominios = CdoiSolicitacao.objects.filter(
                nome_condominio__icontains=nome_condominio
            ).order_by('nome_condominio')
            
            if not condominios.exists():
                self.stdout.write(
                    self.style.ERROR(f'\n[ERRO] Nenhum condominio encontrado com o nome "{nome_condominio}"')
                )
                return
            
            self.stdout.write(
                self.style.SUCCESS(f'\n=== Encontrados {condominios.count()} condominio(s) ===\n')
            )
            
            for cdoi in condominios:
                blocos = cdoi.blocos.all()
                self.stdout.write(f'\n[CDOI] {self.style.SUCCESS(cdoi.nome_condominio)} (ID: {cdoi.id})')
                self.stdout.write(f'   CEP: {cdoi.cep}')
                self.stdout.write(f'   Cidade: {cdoi.cidade}-{cdoi.uf}')
                self.stdout.write(f'   Status: {cdoi.status}')
                self.stdout.write(f'   Total HPs (geral): {cdoi.total_hps}')
                self.stdout.write(f'   Pre-venda: {cdoi.pre_venda_minima}')
                self.stdout.write(f'   Criado em: {cdoi.data_criacao.strftime("%d/%m/%Y %H:%M")}')
                self.stdout.write(f'\n   Blocos cadastrados: {blocos.count()}')
                
                if blocos.exists():
                    total_hps_blocos = 0
                    for b in blocos:
                        total_hps_blocos += b.total_hps_bloco
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'      [OK] {b.nome_bloco}: '
                                f'{b.andares} andares, '
                                f'{b.unidades_por_andar} aptos/andar, '
                                f'Total: {b.total_hps_bloco} HPs'
                            )
                        )
                    
                    self.stdout.write(f'\n   Total HPs dos blocos: {total_hps_blocos}')
                    
                    if total_hps_blocos != cdoi.total_hps:
                        self.stdout.write(
                            self.style.WARNING(
                                f'   [ATENCAO] Total HPs dos blocos ({total_hps_blocos}) '
                                f'diferente do total geral ({cdoi.total_hps})!'
                            )
                        )
                else:
                    self.stdout.write(
                        self.style.ERROR('   [ERRO] NENHUM BLOCO CADASTRADO!')
                    )
                    self.stdout.write(
                        self.style.WARNING(
                            '   [AVISO] Este condominio nao possui blocos no banco de dados.'
                        )
                    )
        else:
            self.stdout.write(
                self.style.ERROR('\n[ERRO] Informe o nome do condominio ou use --todos')
            )
            self.stdout.write('\nUso:')
            self.stdout.write('  python manage.py verificar_blocos_cdoi "Conquista Bem Viver"')
            self.stdout.write('  python manage.py verificar_blocos_cdoi --todos')
