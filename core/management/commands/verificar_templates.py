import os
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Verifica onde o Django está procurando templates e se os arquivos existem'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== INICIANDO VERIFICAÇÃO DE TEMPLATES ==='))
        
        base_dir = str(settings.BASE_DIR)
        self.stdout.write(f"BASE_DIR do projeto: {base_dir}")
        
        dirs = settings.TEMPLATES[0]['DIRS']
        self.stdout.write(f"\nDiretórios configurados no settings.py (DIRS):")
        
        found = False
        
        for d in dirs:
            d = str(d) # Garante string
            self.stdout.write(f" -> Verificando pasta: {d}")
            
            if os.path.exists(d):
                self.stdout.write(self.style.SUCCESS(f"    [OK] Pasta existe."))
                
                # Tenta achar a pasta 'core' dentro
                core_path = os.path.join(d, 'core')
                if os.path.exists(core_path):
                    self.stdout.write(self.style.SUCCESS(f"    [OK] Subpasta 'core' encontrada dentro de templates."))
                    
                    # Tenta achar o arquivo
                    file_path = os.path.join(core_path, 'calendario_fiscal.html')
                    if os.path.exists(file_path):
                        self.stdout.write(self.style.SUCCESS(f"    [SUCESSO] Arquivo 'calendario_fiscal.html' ENCONTRADO em: {file_path}"))
                        found = True
                    else:
                        self.stdout.write(self.style.WARNING(f"    [FALHA] Arquivo 'calendario_fiscal.html' NÃO existe dentro de {core_path}"))
                        self.stdout.write(f"    Conteúdo da pasta core: {os.listdir(core_path)}")
                else:
                    self.stdout.write(self.style.WARNING(f"    [AVISO] Não existe subpasta 'core' aqui. (O Django procura 'core/calendario_fiscal.html')"))
                    self.stdout.write(f"    Conteúdo da pasta templates: {os.listdir(d)}")
            else:
                self.stdout.write(self.style.ERROR(f"    [ERRO] Esta pasta configurada NÃO EXISTE no disco."))

        if not found:
            self.stdout.write(self.style.ERROR("\n[CONCLUSÃO] O Django não encontrou o arquivo em nenhum lugar configurado."))
            self.stdout.write("Certifique-se de criar a pasta 'core' DENTRO da pasta 'templates' e colocar o arquivo lá.")
        else:
            self.stdout.write(self.style.SUCCESS("\n[CONCLUSÃO] O arquivo existe e deveria funcionar. Tente reiniciar o servidor."))