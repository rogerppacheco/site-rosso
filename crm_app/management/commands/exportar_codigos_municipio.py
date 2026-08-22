# -*- coding: utf-8 -*-
"""
Gera arquivo Excel com os códigos de município do IBGE (código 7 dígitos + nome).

Usa o arquivo crm_app/data/ibge_municipios.json. Se não existir, rode antes:
    python manage.py download_ibge_municipios

Uso:
    python manage.py exportar_codigos_municipio
    python manage.py exportar_codigos_municipio --arquivo C:\saida\municipios.xlsx
"""
from django.core.management.base import BaseCommand
import os


# Código IBGE 2 dígitos -> sigla UF (inverso do _UF_PREFIX)
_CODIGO_UF = {
    '11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA', '16': 'AP', '17': 'TO',
    '21': 'MA', '22': 'PI', '23': 'CE', '24': 'RN', '25': 'PB', '26': 'PE', '27': 'AL',
    '28': 'SE', '29': 'BA', '31': 'MG', '32': 'ES', '33': 'RJ', '35': 'SP', '41': 'PR',
    '42': 'SC', '43': 'RS', '50': 'MS', '51': 'MT', '52': 'GO', '53': 'DF',
}


class Command(BaseCommand):
    help = 'Exporta códigos de município IBGE para Excel'

    def add_arguments(self, parser):
        parser.add_argument(
            '--arquivo',
            type=str,
            default=None,
            help='Caminho do arquivo Excel de saída (padrão: crm_app/data/codigos_municipio_ibge.xlsx)',
        )

    def handle(self, *args, **options):
        from crm_app.ibge_municipios import _load_from_file, _get_data_path

        data = _load_from_file()
        if not data:
            self.stderr.write(
                self.style.ERROR(
                    'Arquivo ibge_municipios.json não encontrado. Rode: python manage.py download_ibge_municipios'
                )
            )
            return

        out_path = options.get('arquivo')
        if not out_path:
            base = os.path.dirname(_get_data_path())
            out_path = os.path.join(base, 'codigos_municipio_ibge.xlsx')

        try:
            import openpyxl
        except ImportError:
            self.stderr.write(self.style.ERROR('Instale openpyxl: pip install openpyxl'))
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Municípios IBGE'
        ws.append(['Código IBGE', 'UF', 'Nome do Município'])

        for codigo in sorted(data.keys(), key=lambda x: (x[:2], x)):
            nome = data[codigo]
            uf = _CODIGO_UF.get(codigo[:2], '') if len(codigo) >= 2 else ''
            ws.append([codigo, uf, nome])

        dir_out = os.path.dirname(os.path.abspath(out_path))
        if dir_out:
            os.makedirs(dir_out, exist_ok=True)
        wb.save(out_path)

        self.stdout.write(self.style.SUCCESS(f'Excel gerado: {out_path} ({len(data):,} municípios)'))
