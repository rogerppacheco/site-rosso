from django.core.management.base import BaseCommand
from crm_app.models import Cliente
import re
from django.db import IntegrityError

class Command(BaseCommand):
    help = 'Remove pontuação (pontos, traços, barras) dos CPFs/CNPJs dos clientes'

    def handle(self, *args, **kwargs):
        self.stdout.write("Iniciando limpeza de CPFs/CNPJs...")
        
        clientes = Cliente.objects.all()
        alterados = 0
        ignorados = 0

        for cliente in clientes:
            original = cliente.cpf_cnpj
            # Remove tudo que não for número
            limpo = re.sub(r'\D', '', original)

            if original != limpo:
                # Verifica se já existe outro cliente com esse CPF limpo
                if Cliente.objects.filter(cpf_cnpj=limpo).exclude(id=cliente.id).exists():
                    self.stdout.write(self.style.WARNING(f"DUPLICIDADE EVITADA: Cliente '{cliente.nome_razao_social}' (ID {cliente.id}) ficaria com CPF duplicado {limpo}. Mantido original."))
                    ignorados += 1
                else:
                    cliente.cpf_cnpj = limpo
                    try:
                        cliente.save()
                        alterados += 1
                    except IntegrityError:
                        self.stdout.write(self.style.ERROR(f"Erro ao salvar ID {cliente.id}"))

        self.stdout.write(self.style.SUCCESS(f"Processo finalizado!"))
        self.stdout.write(self.style.SUCCESS(f"Alterados: {alterados}"))
        self.stdout.write(self.style.WARNING(f"Ignorados (Duplicados): {ignorados}"))