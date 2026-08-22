from django.core.management.base import BaseCommand
from crm_app.models import Cliente, Venda
from django.db import transaction
import re

class Command(BaseCommand):
    help = 'Unifica clientes com mesmo CPF/CNPJ (migra vendas e deleta duplicados)'

    def handle(self, *args, **kwargs):
        self.stdout.write("Iniciando análise de duplicidades...")

        # 1. Agrupar clientes pelo CPF LIMPO
        clientes_por_cpf = {}
        all_clientes = Cliente.objects.all()

        for c in all_clientes:
            # Remove tudo que não é dígito
            cpf_limpo = re.sub(r'\D', '', c.cpf_cnpj)
            
            if cpf_limpo not in clientes_por_cpf:
                clientes_por_cpf[cpf_limpo] = []
            clientes_por_cpf[cpf_limpo].append(c)

        duplicados_resolvidos = 0
        cpfs_limpos = 0

        try:
            with transaction.atomic():
                for cpf, lista in clientes_por_cpf.items():
                    # Caso 1: Sem duplicidade, apenas verifica se precisa limpar a pontuação
                    if len(lista) == 1:
                        cliente = lista[0]
                        if cliente.cpf_cnpj != cpf:
                            cliente.cpf_cnpj = cpf
                            cliente.save()
                            cpfs_limpos += 1
                        continue

                    # Caso 2: Duplicidade encontrada
                    self.stdout.write(self.style.WARNING(f"--- Duplicidade no CPF {cpf} ({len(lista)} registros) ---"))
                    
                    # Ordena: Mantém preferencialmente quem já tem o CPF limpo, senão o ID mais antigo
                    # False < True, então (x.cpf_cnpj != cpf) coloca quem TEM o cpf limpo (False) primeiro
                    lista.sort(key=lambda x: (x.cpf_cnpj != cpf, x.id))
                    
                    principal = lista[0]
                    duplicados = lista[1:]

                    self.stdout.write(f"Manter Principal: ID {principal.id} - {principal.nome_razao_social}")

                    for dup in duplicados:
                        # 1. Migrar Vendas do duplicado para o principal
                        vendas_migradas = Venda.objects.filter(cliente=dup).update(cliente=principal)
                        if vendas_migradas > 0:
                            self.stdout.write(f"   -> {vendas_migradas} vendas migradas do ID {dup.id} para o principal.")
                        
                        # 2. Deletar o duplicado (agora vazio de vendas)
                        self.stdout.write(f"   -> Deletando cliente duplicado ID {dup.id} ({dup.nome_razao_social})")
                        dup.delete()
                        duplicados_resolvidos += 1

                    # 3. Garante que o principal fique com CPF limpo
                    if principal.cpf_cnpj != cpf:
                        principal.cpf_cnpj = cpf
                        principal.save()
                        cpfs_limpos += 1
                        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erro crítico durante o processo: {e}"))
            return

        self.stdout.write(self.style.SUCCESS(f"--------------------------------------------------"))
        self.stdout.write(self.style.SUCCESS(f"FIM! Clientes unificados/deletados: {duplicados_resolvidos}"))
        self.stdout.write(self.style.SUCCESS(f"Total de CPFs padronizados (limpos): {cpfs_limpos}"))