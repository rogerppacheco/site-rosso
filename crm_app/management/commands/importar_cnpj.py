# -*- coding: utf-8 -*-
r"""
Comando Django para importar arquivo(s) ESTABELE da Receita Federal a partir de um caminho local.

Para arquivos GRANDES (acima de ~1 GB / 17M linhas), use SEMPRE este comando no terminal,
e não o upload pela tela. Assim a importação não é interrompida por reinício do servidor
ou timeout do navegador.

Uso:
    # Um arquivo:
    python manage.py importar_cnpj "C:\caminho\K3241.K03200Y0.D60214.ESTABELE"

    # Todos os .ESTABELE de uma pasta (em ordem alfabética):
    python manage.py importar_cnpj "C:\Users\rogge\Downloads\download\BASE_CNPJ"

    python manage.py importar_cnpj /path/to/file.ESTABELE --cnae 8112500 --municipio 4123 --situacao 02
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


def _coletar_arquivos(path):
    """Retorna lista de Path: um arquivo ou todos .ESTABELE do diretório (ordenados)."""
    path = path.resolve()
    if path.is_file():
        return [path]
    if path.is_dir():
        arquivos = sorted(path.glob("*.ESTABELE")) + sorted(path.glob("*.estabele"))
        # remover duplicatas (Windows não diferencia maiúsculas)
        seen = set()
        out = []
        for p in arquivos:
            key = p.name.upper()
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out
    return []


class Command(BaseCommand):
    help = 'Importa arquivo(s) ESTABELE da Receita Federal (um arquivo ou todos de uma pasta)'

    def add_arguments(self, parser):
        parser.add_argument(
            'caminho',
            type=str,
            help='Caminho do arquivo .ESTABELE/.csv ou da pasta com vários .ESTABELE',
        )
        parser.add_argument('--cnae', type=str, default=None, help='Filtro CNAE (ex: 8112500)')
        parser.add_argument('--municipio', type=str, default=None, help='Filtro código município (ex: 4123)')
        parser.add_argument('--situacao', type=str, default='02', help='Filtro situação cadastral (02=Ativa)')
        parser.add_argument('--usuario', type=str, default=None, help='Username para o log (opcional)')

    def handle(self, *args, **options):
        from pathlib import Path
        from crm_app.models import LogImportacaoEstabelecimentoCNPJ
        from crm_app.services.cnpj_estabele_import_service import processar_arquivo_estabele

        base = Path(options['caminho'])
        if not base.exists():
            self.stderr.write(self.style.ERROR(f'Caminho não encontrado: {base}'))
            return

        arquivos = _coletar_arquivos(base)
        if not arquivos:
            self.stderr.write(
                self.style.ERROR(f'Nenhum arquivo .ESTABELE encontrado em {base}')
            )
            return

        if len(arquivos) > 1:
            self.stdout.write(self.style.NOTICE(f'Serão importados {len(arquivos)} arquivos em sequência.'))

        usuario = None
        if options.get('usuario'):
            usuario = User.objects.filter(username=options['usuario']).first()

        aplicar_filtros = bool(
            options.get('cnae') or options.get('municipio') or options.get('situacao')
        )

        total_importados_geral = 0
        for idx, path in enumerate(arquivos, 1):
            if len(arquivos) > 1:
                self.stdout.write('')
                self.stdout.write(self.style.NOTICE(f'[{idx}/{len(arquivos)}] {path.name}'))

            log = LogImportacaoEstabelecimentoCNPJ.objects.create(
                nome_arquivo=path.name,
                usuario=usuario,
                status='PROCESSANDO',
                tamanho_arquivo=path.stat().st_size,
            )
            self.stdout.write(f'  Log ID {log.id} | {path.stat().st_size / (1024*1024):.1f} MB')

            processar_arquivo_estabele(
                log_id=log.id,
                arquivo_path=str(path),
                aplicar_filtros=aplicar_filtros,
                cnae_fiscal=options.get('cnae'),
                codigo_municipio=options.get('municipio'),
                situacao_cadastral=options.get('situacao'),
            )

            log.refresh_from_db()
            total_importados_geral += log.total_importadas or 0
            self.stdout.write(
                self.style.SUCCESS(
                    f'  Concluído: {log.total_importadas:,} importados de {log.total_linhas:,} linhas. Status: {log.status}'
                )
            )

        if len(arquivos) > 1:
            self.stdout.write('')
            self.stdout.write(
                self.style.SUCCESS(f'Total: {len(arquivos)} arquivo(s), {total_importados_geral:,} registros importados.')
            )
