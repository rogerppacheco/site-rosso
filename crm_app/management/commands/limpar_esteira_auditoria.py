"""
Limpa filas operacionais de auditoria e esteira (Opção A).

Não apaga linhas de Venda. Não mexe em INSTALADA/CANCELADA.
Não apaga histórico PAP (use --incluir-historico-pap se precisar).

Uso:
  python manage.py limpar_esteira_auditoria
  python manage.py limpar_esteira_auditoria --confirmar
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q


class Command(BaseCommand):
    help = "Limpa filas de auditoria/esteira aberta (Opção A) sem apagar vendas instaladas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Executa a limpeza. Sem isto, só simula (dry-run).",
        )
        parser.add_argument(
            "--incluir-historico-pap",
            action="store_true",
            help="Também apaga HistoricoPapPedido e HistoricoPapBusca.",
        )

    def handle(self, *args, **options):
        from crm_app import models as m

        confirmar = bool(options["confirmar"])
        incluir_pap = bool(options["incluir_historico_pap"])

        qs_auditoria = m.Venda.objects.filter(
            status_tratamento__isnull=False,
            status_esteira__isnull=True,
        )
        qs_esteira_aberta = (
            m.Venda.objects.filter(
                status_esteira__isnull=False,
                status_esteira__estado__iexact="ABERTO",
            ).exclude(status_esteira__nome__icontains="CANCELAD")
        )
        qs_filas = m.Venda.objects.filter(
            Q(id__in=qs_auditoria.values("id")) | Q(id__in=qs_esteira_aberta.values("id"))
        )

        satelites = [
            ("AuditoriaLigacao", m.AuditoriaLigacao.objects.all()),
            ("VendaEsteiraEvento", m.VendaEsteiraEvento.objects.all()),
            ("AuditoriaSemSlotGC", m.AuditoriaSemSlotGC.objects.all()),
            ("PendenciaIndevidaAnexo", m.PendenciaIndevidaAnexo.objects.all()),
            ("PendenciaIndevidaRegistro", m.PendenciaIndevidaRegistro.objects.all()),
            ("SyncStatusEsteiraExecucao", m.SyncStatusEsteiraExecucao.objects.all()),
            ("SessaoTratamento", m.SessaoTratamento.objects.all()),
            ("PendenciaClienteMsgEnviada", m.PendenciaClienteMsgEnviada.objects.all()),
            ("LembreteInstalacaoEnviado", m.LembreteInstalacaoEnviado.objects.all()),
            ("PossoAnteciparVendedorEnviado", m.PossoAnteciparVendedorEnviado.objects.all()),
            ("PapConfirmacaoCliente", m.PapConfirmacaoCliente.objects.all()),
            ("PedidoAjudaGc", m.PedidoAjudaGc.objects.all()),
            ("NioReagendamentoItem", m.NioReagendamentoItem.objects.all()),
            ("NioReagendamentoExecucao", m.NioReagendamentoExecucao.objects.all()),
        ]

        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING("Opção A — limpar filas auditoria/esteira aberta"))
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(f"Fila auditoria: {qs_auditoria.count()}")
        self.stdout.write(f"Esteira aberta: {qs_esteira_aberta.count()}")
        self.stdout.write(f"Vendas a resetar (união): {qs_filas.count()}")
        for nome, qs in satelites:
            self.stdout.write(f"  {nome}: {qs.count()}")
        if incluir_pap:
            self.stdout.write(f"  HistoricoPapPedido: {m.HistoricoPapPedido.objects.count()}")
            self.stdout.write(f"  HistoricoPapBusca: {m.HistoricoPapBusca.objects.count()}")
        self.stdout.write("")

        if not confirmar:
            self.stdout.write(self.style.WARNING("DRY-RUN — nenhum dado alterado."))
            self.stdout.write("Para executar: python manage.py limpar_esteira_auditoria --confirmar")
            return

        self.stdout.write(self.style.ERROR("EXECUTANDO LIMPEZA..."))
        with transaction.atomic():
            for nome, qs in satelites:
                n = qs.count()
                if n:
                    qs.delete()
                self.stdout.write(self.style.SUCCESS(f"OK {nome}: {n} removidos"))

            if incluir_pap:
                n1 = m.HistoricoPapPedido.objects.count()
                n2 = m.HistoricoPapBusca.objects.count()
                m.HistoricoPapPedido.objects.all().delete()
                m.HistoricoPapBusca.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f"OK HistoricoPapPedido: {n1}"))
                self.stdout.write(self.style.SUCCESS(f"OK HistoricoPapBusca: {n2}"))

            update_fields = {
                "status_tratamento": None,
                "status_esteira": None,
                "auditor_atual": None,
                "motivo_pendencia": None,
            }
            # Campos opcionais se existirem no model
            for campo in (
                "biometria_aprovada",
                "biometria_consultada_em",
                "biometria_data_apta",
                "protocolo_confirmacao_auditoria",
                "data_confirmacao_auditoria",
                "cliente_confirmou_lembrete_instalacao",
                "cliente_resposta_lembrete_instalacao",
                "data_resposta_lembrete_instalacao",
            ):
                if hasattr(m.Venda, campo):
                    update_fields[campo] = None if campo != "biometria_aprovada" and campo != "cliente_confirmou_lembrete_instalacao" else None
                    # BooleanFields: set False/None carefully
                    f = m.Venda._meta.get_field(campo)
                    if getattr(f, "null", False):
                        update_fields[campo] = None
                    elif f.get_internal_type() == "BooleanField":
                        update_fields[campo] = False
                    else:
                        update_fields[campo] = None

            ids = list(qs_filas.values_list("id", flat=True))
            atualizadas = 0
            if ids:
                atualizadas = m.Venda.objects.filter(id__in=ids).update(**update_fields)
            self.stdout.write(self.style.SUCCESS(f"OK Vendas resetadas (filas): {atualizadas}"))

        # Pós-checagem
        aud = m.Venda.objects.filter(
            status_tratamento__isnull=False, status_esteira__isnull=True
        ).count()
        est = (
            m.Venda.objects.filter(
                status_esteira__isnull=False, status_esteira__estado__iexact="ABERTO"
            )
            .exclude(status_esteira__nome__icontains="CANCELAD")
            .count()
        )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Limpeza concluída."))
        self.stdout.write(self.style.SUCCESS(f"Fila auditoria restante: {aud}"))
        self.stdout.write(self.style.SUCCESS(f"Esteira aberta restante: {est}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
