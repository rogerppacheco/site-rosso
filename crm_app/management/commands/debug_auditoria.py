from django.core.management.base import BaseCommand
from crm_app.models import Venda, StatusCRM

class Command(BaseCommand):
    help = 'Investiga uma venda especifica (Padrao ID 9)'

    def add_arguments(self, parser):
        # Permite passar o ID como argumento (ex: debug_auditoria 9)
        parser.add_argument('venda_id', type=int, nargs='?', default=9)

    def handle(self, *args, **options):
        v_id = options['venda_id']
        self.stdout.write(f"\n=== INVESTIGANDO VENDA #{v_id} ===\n")
        
        # 1. Tenta buscar ignorando o filtro de 'ativo=True'
        try:
            v = Venda.objects.get(id=v_id)
        except Venda.DoesNotExist:
            self.stdout.write(f"[CRÍTICO] A venda #{v_id} NÃO EXISTE no banco de dados.")
            return

        # 2. Imprime os detalhes
        self.stdout.write(f"Cliente: {v.cliente}")
        self.stdout.write(f"Vendedor: {v.vendedor} (ID: {v.vendedor.id if v.vendedor else 'N/A'})")
        self.stdout.write(f"Data Criação: {v.data_criacao}")
        self.stdout.write(f"Ativo: {v.ativo}  <-- SE ESTIVER 'False', ELA NÃO APARECE!")
        self.stdout.write(f"Status Tratamento: {v.status_tratamento}")
        self.stdout.write(f"Status Esteira: {v.status_esteira}")
        
        self.stdout.write("\n--- DIAGNÓSTICO DE AUDITORIA ---")
        
        motivos_ocultacao = []

        if not v.ativo:
            motivos_ocultacao.append("A venda está Inativa (Excluída).")
            
        if not v.status_tratamento:
            motivos_ocultacao.append("Status de Tratamento está vazio (None).")
            
        if v.status_esteira:
            motivos_ocultacao.append(f"Já possui Status de Esteira ({v.status_esteira}). Saiu da auditoria.")

        if not motivos_ocultacao:
            self.stdout.write("[OK] Os dados técnicos parecem corretos para aparecer na Auditoria.")
            self.stdout.write("POSSÍVEL CAUSA: Filtro de Permissão.")
            self.stdout.write(f"Se você está logado como {v.vendedor}, deveria ver.")
            self.stdout.write("Se você é Supervisor/Backoffice, verifique se tem acesso a este vendedor.")
        else:
            self.stdout.write("[FALHA] A venda está oculta pelos seguintes motivos:")
            for m in motivos_ocultacao:
                self.stdout.write(f" - {m}")