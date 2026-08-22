"""
Comando Django para importar motivos de pendência em massa
Uso: python manage.py importar_pendencias --arquivo pendencias.csv
     python manage.py importar_pendencias --json pendencias.json
     python manage.py importar_pendencias --inline "Nome1,Tipo1|Nome2,Tipo2"
"""
import csv
import json
from django.core.management.base import BaseCommand
from django.db import transaction
from crm_app.models import MotivoPendencia


class Command(BaseCommand):
    help = 'Importa motivos de pendência em massa a partir de arquivo CSV, JSON ou lista inline'

    def add_arguments(self, parser):
        parser.add_argument(
            '--arquivo',
            type=str,
            help='Caminho para arquivo CSV com colunas: nome,tipo_pendencia',
        )
        parser.add_argument(
            '--json',
            type=str,
            help='Caminho para arquivo JSON com array de objetos: [{"nome": "...", "tipo_pendencia": "..."}]',
        )
        parser.add_argument(
            '--inline',
            type=str,
            help='Lista inline no formato: "Nome1,Tipo1|Nome2,Tipo2"',
        )

    def handle(self, *args, **options):
        pendencias = []
        
        # Opção 1: Arquivo CSV
        if options['arquivo']:
            try:
                with open(options['arquivo'], 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'nome' in row and row['nome'].strip():
                            pendencias.append({
                                'nome': row['nome'].strip(),
                                'tipo_pendencia': row.get('tipo_pendencia', '').strip() or 'Operacional'
                            })
                self.stdout.write(f"✓ {len(pendencias)} pendências carregadas do arquivo CSV")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erro ao ler arquivo CSV: {e}"))
                return
        
        # Opção 2: Arquivo JSON
        elif options['json']:
            try:
                with open(options['json'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('nome'):
                                pendencias.append({
                                    'nome': item['nome'].strip(),
                                    'tipo_pendencia': item.get('tipo_pendencia', '').strip() or 'Operacional'
                                })
                    else:
                        self.stdout.write(self.style.ERROR("JSON deve ser um array de objetos"))
                        return
                self.stdout.write(f"✓ {len(pendencias)} pendências carregadas do arquivo JSON")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erro ao ler arquivo JSON: {e}"))
                return
        
        # Opção 3: Lista inline
        elif options['inline']:
            try:
                for item in options['inline'].split('|'):
                    parts = item.split(',', 1)
                    if len(parts) >= 1 and parts[0].strip():
                        pendencias.append({
                            'nome': parts[0].strip(),
                            'tipo_pendencia': parts[1].strip() if len(parts) > 1 and parts[1].strip() else 'Operacional'
                        })
                self.stdout.write(f"✓ {len(pendencias)} pendências carregadas da lista inline")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erro ao processar lista inline: {e}"))
                return
        
        else:
            self.stdout.write(self.style.ERROR("Você deve especificar --arquivo, --json ou --inline"))
            self.stdout.write("Exemplo: python manage.py importar_pendencias --inline 'Pendencia1,Cliente|Pendencia2,Técnica'")
            return
        
        if not pendencias:
            self.stdout.write(self.style.WARNING("Nenhuma pendência encontrada para importar"))
            return
        
        # Importar pendências
        criadas = 0
        atualizadas = 0
        erros = []
        
        with transaction.atomic():
            for pendencia_data in pendencias:
                try:
                    # Verifica se já existe (case-insensitive)
                    nome_upper = pendencia_data['nome'].upper().strip()
                    existente = MotivoPendencia.objects.filter(nome__iexact=pendencia_data['nome']).first()
                    
                    if existente:
                        # Já existe, apenas informa
                        self.stdout.write(f"  ⊙ Já existe: {existente.nome} (ID: {existente.id})")
                    else:
                        # Cria nova pendência
                        obj = MotivoPendencia.objects.create(
                            nome=pendencia_data['nome'],
                            tipo_pendencia=pendencia_data['tipo_pendencia']
                        )
                        criadas += 1
                        self.stdout.write(f"  ✓ Criada: {obj.nome} ({obj.tipo_pendencia})")
                            
                except Exception as e:
                    erros.append(f"{pendencia_data['nome']}: {str(e)}")
                    self.stdout.write(self.style.ERROR(f"  ✗ Erro ao processar {pendencia_data['nome']}: {e}"))
        
        # Resumo
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 50))
        self.stdout.write(self.style.SUCCESS(f"✓ Importação concluída!"))
        self.stdout.write(self.style.SUCCESS(f"  Criadas: {criadas}"))
        self.stdout.write(self.style.SUCCESS(f"  Atualizadas: {atualizadas}"))
        self.stdout.write(self.style.SUCCESS(f"  Já existiam: {len(pendencias) - criadas - atualizadas - len(erros)}"))
        if erros:
            self.stdout.write(self.style.WARNING(f"  Erros: {len(erros)}"))
            for erro in erros:
                self.stdout.write(self.style.ERROR(f"    - {erro}"))
        self.stdout.write(self.style.SUCCESS("=" * 50))
