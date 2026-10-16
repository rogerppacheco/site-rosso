"""Rotina: busca Histórico PAP (Funil) — Interesse e Venda.

Uso:
  python manage.py buscar_historico_pap_funil
  python manage.py buscar_historico_pap_funil --dias 7
  python manage.py buscar_historico_pap_funil --dias 30 --tipos INTERESSE,VENDA
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.historico_pap import MAX_DIAS_BUSCA, MAX_DIAS_RETROATIVOS_INTERESSE, tipos_solicitados


# Padrão da rotina diária (06:00): janela curta o suficiente para Interest+Venda.
DIAS_ROTINA_PADRAO = 7
TIPOS_ROTINA_PADRAO = ("INTERESSE", "VENDA")


class Command(BaseCommand):
    help = "Dispara busca do Histórico PAP no Funil (Interesse/Venda) para o período recente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=DIAS_ROTINA_PADRAO,
            help=f"Dias para trás (padrão {DIAS_ROTINA_PADRAO}; máx. {MAX_DIAS_BUSCA}).",
        )
        parser.add_argument(
            "--tipos",
            type=str,
            default=",".join(TIPOS_ROTINA_PADRAO),
            help='Tipos separados por vírgula (padrão "INTERESSE,VENDA").',
        )

    def handle(self, *args, **options):
        from crm_app.historico_pap_service import (
            busca_em_andamento,
            criar_e_iniciar_busca,
            obter_pausa_rotina_automatica,
        )

        pausa = obter_pausa_rotina_automatica()
        if pausa:
            self.stdout.write(self.style.ERROR(
                "[HistoricoPAP] Rotina PAUSADA após falha de login. "
                "Atualize matrícula/senha PAP na Governança para retomar. "
                f"Login: {pausa.get('login_pap') or '—'} | "
                f"Motivo: {pausa.get('motivo') or '—'}"
            ))
            return

        tipos = tipos_solicitados(
            [p.strip() for p in str(options["tipos"] or "").split(",") if p.strip()]
        )
        if not tipos:
            tipos = list(TIPOS_ROTINA_PADRAO)

        dias = max(1, min(int(options["dias"] or DIAS_ROTINA_PADRAO), MAX_DIAS_BUSCA))
        # Interesse no PAP só libera ~30 dias — corta a janela se pedirem mais.
        if "INTERESSE" in tipos:
            dias = min(dias, MAX_DIAS_RETROATIVOS_INTERESSE)

        fim = timezone.localdate()
        inicio = fim - timedelta(days=dias - 1)

        andamento = busca_em_andamento()
        if andamento:
            self.stdout.write(self.style.WARNING(
                f"Já há busca #{andamento.pk} em andamento "
                f"({andamento.status}: {andamento.mensagem or '—'}). Abortando."
            ))
            return

        self.stdout.write(
            f"[HistoricoPAP] Buscando {', '.join(tipos)} de "
            f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y} ({dias} dias)…"
        )
        busca_id, err = criar_e_iniciar_busca(
            None,
            data_inicio=inicio,
            data_fim=fim,
            pdv="",
            tipos=tipos,
            origem_automatica=True,
        )
        if err:
            self.stdout.write(self.style.ERROR(err))
            return
        self.stdout.write(self.style.SUCCESS(f"Busca #{busca_id} iniciada."))
