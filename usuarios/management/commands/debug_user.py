from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Diagnostico de permissoes de usuario'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Usuario {username} nao encontrado."))
            return

        self.stdout.write(self.style.SUCCESS(f"--- DIAGNOSTICO PARA: {user.username} ---"))
        self.stdout.write(f"Superuser: {user.is_superuser}")
        self.stdout.write(f"Staff: {user.is_staff}")
        self.stdout.write(f"Grupos: {[g.name for g in user.groups.all()]}")
        
        self.stdout.write("\n--- PERMISSOES EFETIVAS (get_all_permissions) ---")
        perms = user.get_all_permissions()
        
        # Verifica as permissoes criticas para o seu caso
        criticas = [
            'crm_app.change_venda',
            'crm_app.can_view_auditoria',
            'crm_app.can_view_esteira'
        ]
        
        for p in criticas:
            tem = p in perms
            msg = "OK" if tem else "FALTA"
            cor = self.style.SUCCESS if tem else self.style.ERROR
            self.stdout.write(cor(f"[{msg}] {p}"))

        self.stdout.write("\n--- LISTA COMPLETA DE PERMISSOES DO APP CRM ---")
        for p in sorted(perms):
            if 'crm_app' in p:
                self.stdout.write(p)