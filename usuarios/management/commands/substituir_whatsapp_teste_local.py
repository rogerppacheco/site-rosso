"""
Substitui WhatsApp 1/2/3 de todos os usuários por números de teste (evita disparar
mensagens reais ao testar com dump de produção). Uso típico só no banco local.

Campos: tel_whatsapp, tel_whatsapp_2, tel_whatsapp_3 (modelo Usuario).
"""
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


def _gerar_wa3_aleatorio() -> str:
    """11 dígitos (formato celular BR sem +55), apenas números."""
    return "21" + "".join(str(secrets.randbelow(10)) for _ in range(9))


def _connection_usa_banco_local() -> tuple[bool, str]:
    """
    Retorna (True, detalhe) se o destino parece ser máquina local (testes).
    Host remoto (Railway, RDS, etc.) retorna False.
    """
    cfg = connection.settings_dict
    engine = (cfg.get("ENGINE") or "").lower()
    name = cfg.get("NAME") or ""
    host = (cfg.get("HOST") or "").strip().lower()

    if "sqlite" in engine:
        return True, f"SQLite ({name})"

    # Postgres/MySQL: socket local ou TCP só em loopback
    if host in ("", "localhost", "127.0.0.1", "::1"):
        return True, f"{engine.split('.')[-1]} host={host or '(padrão local/socket)'} db={name}"

    return False, f"{engine.split('.')[-1]} host={host} db={name}"


class Command(BaseCommand):
    help = (
        "Define tel_whatsapp / tel_whatsapp_2 / tel_whatsapp_3 iguais para todos "
        "os usuários (teste local). Por padrão só GRAVA se o HOST do banco for local."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--wa1",
            default="21979630377",
            help="WhatsApp 1 (principal; sistema envia notificações para este).",
        )
        parser.add_argument(
            "--wa2",
            default="3198880400",
            help="WhatsApp 2.",
        )
        parser.add_argument(
            "--wa3",
            default="",
            help="WhatsApp 3. Se vazio, gera um número aleatório (mesmo valor para todos).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Grava mesmo com DEBUG=False (não desbloqueia banco remoto).",
        )
        parser.add_argument(
            "--allow-remote-database",
            action="store_true",
            dest="allow_remote",
            help=(
                "Permite GRAVAR mesmo com host de banco não-local (ex.: produção). "
                "Use só se souber exatamente o que está fazendo."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra quantos registros seriam alterados, sem gravar.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        local_ok, destino = _connection_usa_banco_local()

        if not settings.DEBUG and not options["force"] and not dry:
            raise CommandError(
                "DEBUG está False. Para gravar assim mesmo, use --force. "
                "Ou use --dry-run só para simular."
            )

        if not local_ok and not dry:
            if not options["allow_remote"]:
                raise CommandError(
                    "O Django não está conectado a um banco ‘local’ típico "
                    f"({destino}). Este comando não altera produção por engano. "
                    "Confira DATABASE_URL (localhost). "
                    "Se realmente precisar gravar nesse host, repita com --allow-remote-database."
                )

        wa1 = (options["wa1"] or "").strip()
        wa2 = (options["wa2"] or "").strip()
        wa3_opt = (options["wa3"] or "").strip()
        wa3 = wa3_opt if wa3_opt else _gerar_wa3_aleatorio()

        User = get_user_model()
        total = User.objects.count()

        aviso = "" if local_ok else " [HOST REMOTO]"
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY-RUN{aviso}: destino={destino} — {total} usuário(s). "
                    f"Seriam gravados — wa1={wa1!r} wa2={wa2!r} wa3={wa3!r}"
                )
            )
            return

        if not local_ok:
            self.stdout.write(
                self.style.WARNING(
                    f"Gravando em host não-local (--allow-remote-database): {destino}"
                )
            )

        with transaction.atomic():
            atualizados = User.objects.all().update(
                tel_whatsapp=wa1,
                tel_whatsapp_2=wa2,
                tel_whatsapp_3=wa3,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"OK ({destino}): {atualizados} usuário(s) atualizado(s). "
                f"wa1={wa1!r} wa2={wa2!r} wa3={wa3!r}"
            )
        )
