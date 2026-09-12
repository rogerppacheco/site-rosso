"""Sincroniza terceiros da NIO (Gestão de Terceiros) para o cache local.

Login automático usa matrícula/senha PAP de um usuário Diretoria.
Uso:
  python manage.py sincronizar_nio_terceiros
  python manage.py sincronizar_nio_terceiros --forcar-relogin
  python manage.py sincronizar_nio_terceiros --sem-cadastro
"""
from django.core.management.base import BaseCommand, CommandError

from usuarios.services_nio_terceiros import (
    NioTerceirosError,
    SessaoNioExpirada,
    garantir_sessao_nio,
    obter_usuario_diretor,
    sincronizar_da_nio,
    terceiros_para_preview,
)


class Command(BaseCommand):
    help = "Sincroniza a lista de terceiros NIO (login automático do Diretor se preciso)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--forcar-relogin",
            action="store_true",
            help="Ignora cookies salvos e faz login V.tal com o Diretor.",
        )
        parser.add_argument(
            "--sem-cadastro",
            action="store_true",
            help="Só lê a lista; não abre cada cadastro detalhado.",
        )

    def handle(self, *args, **options):
        diretor = obter_usuario_diretor()
        if diretor:
            self.stdout.write(
                f"Diretor para login: {diretor.username} ({diretor.matricula_pap})"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Nenhum Diretoria com matrícula/senha PAP — sync falhará se a sessão expirou."
                )
            )
        try:
            if options["forcar_relogin"]:
                garantir_sessao_nio(forcar_relogin=True)
            itens = sincronizar_da_nio(
                incluir_cadastro=not options["sem_cadastro"],
                renovar_sessao=not options["forcar_relogin"],
            )
            preview = terceiros_para_preview(itens)
            criar = sum(1 for p in preview if p.get("acao") == "criar")
            atualizar = sum(1 for p in preview if p.get("acao") == "atualizar")
            ok = sum(1 for p in preview if p.get("acao") == "ja_cadastrado")
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK: {len(itens)} terceiros | criar={criar} atualizar={atualizar} ja_cadastrado={ok}"
                )
            )
        except (SessaoNioExpirada, NioTerceirosError) as exc:
            raise CommandError(str(exc)) from exc
