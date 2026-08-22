"""
Comando de diagnóstico para RecordApoia
Verifica quantos arquivos estão no banco vs no disco e identifica problemas
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from crm_app.models import RecordApoia
import os

class Command(BaseCommand):
    help = 'Diagnóstico completo de arquivos RecordApoia (banco vs disco)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reativar',
            action='store_true',
            help='Reativa arquivos que estão inativos mas deveriam estar ativos',
        )

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("DIAGNOSTICO RECORD APOIA")
        self.stdout.write("=" * 80 + "\n")

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            self.stdout.write(self.style.ERROR("MEDIA_ROOT nao configurado!"))
            return

        self.stdout.write(f"MEDIA_ROOT: {media_root}\n")

        # Estatísticas gerais
        total_banco = RecordApoia.objects.count()
        total_ativos_banco = RecordApoia.objects.filter(ativo=True).count()
        total_inativos_banco = RecordApoia.objects.filter(ativo=False).count()

        self.stdout.write(f"Total no banco: {total_banco}")
        self.stdout.write(f"  - Ativos: {total_ativos_banco}")
        self.stdout.write(f"  - Inativos: {total_inativos_banco}\n")

        # Verificar arquivos ativos
        arquivos_ativos = RecordApoia.objects.filter(ativo=True)
        arquivos_ativos_ok = 0
        arquivos_ativos_faltando = []

        self.stdout.write("Verificando arquivos ATIVOS no banco...")
        for arq in arquivos_ativos:
            if arq.arquivo and arq.arquivo.name:
                caminho_completo = os.path.join(media_root, arq.arquivo.name)
                if os.path.exists(caminho_completo):
                    arquivos_ativos_ok += 1
                else:
                    arquivos_ativos_faltando.append({
                        'id': arq.id,
                        'titulo': arq.titulo,
                        'caminho': arq.arquivo.name
                    })

        self.stdout.write(f"  - Arquivos que existem no disco: {arquivos_ativos_ok}")
        self.stdout.write(f"  - Arquivos que NAO existem no disco: {len(arquivos_ativos_faltando)}\n")

        if arquivos_ativos_faltando:
            self.stdout.write(self.style.WARNING("Arquivos ATIVOS faltando no disco:"))
            for arq in arquivos_ativos_faltando[:10]:  # Mostrar apenas os 10 primeiros
                self.stdout.write(f"  - ID {arq['id']}: {arq['titulo']}")
                self.stdout.write(f"    Caminho: {arq['caminho']}")
            if len(arquivos_ativos_faltando) > 10:
                self.stdout.write(f"  ... e mais {len(arquivos_ativos_faltando) - 10} arquivos\n")

        # Verificar arquivos inativos
        arquivos_inativos = RecordApoia.objects.filter(ativo=False)
        arquivos_inativos_com_arquivo = []
        arquivos_inativos_sem_arquivo = []

        self.stdout.write("\nVerificando arquivos INATIVOS no banco...")
        for arq in arquivos_inativos:
            if arq.arquivo and arq.arquivo.name:
                caminho_completo = os.path.join(media_root, arq.arquivo.name)
                if os.path.exists(caminho_completo):
                    arquivos_inativos_com_arquivo.append({
                        'id': arq.id,
                        'titulo': arq.titulo,
                        'caminho': arq.arquivo.name,
                        'data_upload': arq.data_upload
                    })
                else:
                    arquivos_inativos_sem_arquivo.append(arq.id)

        self.stdout.write(f"  - Inativos COM arquivo no disco: {len(arquivos_inativos_com_arquivo)}")
        self.stdout.write(f"  - Inativos SEM arquivo no disco: {len(arquivos_inativos_sem_arquivo)}\n")

        if arquivos_inativos_com_arquivo:
            self.stdout.write(self.style.WARNING("Arquivos INATIVOS que AINDA EXISTEM no disco (podem ser reativados):"))
            for arq in arquivos_inativos_com_arquivo[:10]:
                self.stdout.write(f"  - ID {arq['id']}: {arq['titulo']} (upload: {arq['data_upload']})")
            if len(arquivos_inativos_com_arquivo) > 10:
                self.stdout.write(f"  ... e mais {len(arquivos_inativos_com_arquivo) - 10} arquivos\n")

        # Reativar se solicitado
        if options['reativar'] and arquivos_inativos_com_arquivo:
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write("REATIVANDO ARQUIVOS...")
            self.stdout.write("=" * 80 + "\n")
            
            confirmacao = input(f"Reativar {len(arquivos_inativos_com_arquivo)} arquivo(s)? (digite 'SIM' para confirmar): ").strip().upper()
            
            if confirmacao == 'SIM':
                ids_para_reativar = [arq['id'] for arq in arquivos_inativos_com_arquivo]
                RecordApoia.objects.filter(id__in=ids_para_reativar).update(ativo=True)
                self.stdout.write(self.style.SUCCESS(f"Reativados {len(ids_para_reativar)} arquivo(s)!"))
            else:
                self.stdout.write(self.style.WARNING("Operacao cancelada."))
        elif options['reativar']:
            self.stdout.write(self.style.WARNING("Nenhum arquivo inativo encontrado com arquivo no disco."))

        # Resumo
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RESUMO")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total no banco: {total_banco}")
        self.stdout.write(f"Ativos OK no disco: {arquivos_ativos_ok}")
        self.stdout.write(f"Ativos faltando no disco: {len(arquivos_ativos_faltando)}")
        self.stdout.write(f"Inativos com arquivo (possivelmente desativados incorretamente): {len(arquivos_inativos_com_arquivo)}")
        
        if arquivos_inativos_com_arquivo:
            self.stdout.write("\n" + self.style.WARNING(
                "Sugestao: Execute 'python manage.py diagnosticar_record_apoia --reativar' para reativar arquivos que foram desativados incorretamente."
            ))
