from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Reprova como DUPLICIDADE as vendas automáticas (PAP) da fila de auditoria cuja O.S. "
        "já está em uma venda da esteira, e vincula o pedido PAP à venda da esteira."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Aplica as alterações. Sem isso, apenas simula (dry-run).",
        )

    def handle(self, *args, **options):
        from crm_app.models import HistoricoAlteracaoVenda, StatusCRM, Venda

        confirmar = options["confirmar"]
        st_dup = StatusCRM.objects.filter(nome__iexact="DUPLICIDADE", tipo="Tratamento").first()
        if not st_dup:
            self.stdout.write(self.style.ERROR("Status de tratamento 'DUPLICIDADE' não encontrado."))
            return

        auditoria = (
            Venda.objects.filter(ativo=True, status_tratamento__isnull=False, status_esteira__isnull=True)
            .exclude(status_tratamento__estado__iexact="FECHADO")
            .exclude(pedido_pap__isnull=True)
            .exclude(pedido_pap="")
            .exclude(ordem_servico__isnull=True)
            .exclude(ordem_servico="")
            .select_related("cliente", "status_tratamento")
            .order_by("-id")
        )

        esteira_por_os: dict[str, list] = {}
        esteira = (
            Venda.objects.filter(ativo=True, status_esteira__isnull=False)
            .exclude(ordem_servico__isnull=True)
            .exclude(ordem_servico="")
            .select_related("status_esteira")
        )
        for e in esteira:
            esteira_por_os.setdefault(e.ordem_servico.strip(), []).append(e)

        reprovadas = 0
        vinculadas = 0
        self.stdout.write("aud_id|cliente|O.S.|pedido_pap -> esteira_id(status)|vincula_pedido")

        for v in auditoria:
            os_val = v.ordem_servico.strip()
            matches = [e for e in esteira_por_os.get(os_val, []) if e.id != v.id]
            if not matches:
                continue
            alvo = max(matches, key=lambda e: e.id)
            vincular = len(matches) == 1 and not (alvo.pedido_pap or "").strip()
            nome = (v.cliente.nome_razao_social if v.cliente_id else "")[:30]
            self.stdout.write(
                f"{v.id}|{nome}|{os_val}|{v.pedido_pap} -> "
                f"{','.join(f'{e.id}({e.status_esteira.nome})' for e in matches)}|{'SIM' if vincular else 'NAO'}"
            )
            reprovadas += 1
            if vincular:
                vinculadas += 1
            if not confirmar:
                continue

            pedido = v.pedido_pap
            nota = (
                f"[{timezone.localtime():%d/%m/%Y %H:%M}] Duplicidade da venda #{alvo.id} "
                f"(O.S. {os_val}) na esteira - reprovação automática."
            )
            with transaction.atomic():
                v.status_tratamento = st_dup
                v.auditor_atual = None
                v.observacoes = f"{v.observacoes}\n{nota}".strip() if v.observacoes else nota
                campos = ["status_tratamento", "auditor_atual", "observacoes"]
                if vincular:
                    v.pedido_pap = None
                    campos.append("pedido_pap")
                v.save(update_fields=campos)
                HistoricoAlteracaoVenda.objects.create(
                    venda=v,
                    usuario=None,
                    alteracoes={
                        "status_tratamento": "DUPLICIDADE",
                        "motivo": f"Mesma O.S. {os_val} da venda #{alvo.id} na esteira (reprovação em lote).",
                        "pedido_pap_transferido_para": alvo.id if vincular else None,
                        "pedido_pap": pedido,
                    },
                )
                if vincular:
                    Venda.objects.filter(pk=alvo.pk).update(pedido_pap=pedido)
                    HistoricoAlteracaoVenda.objects.create(
                        venda=alvo,
                        usuario=None,
                        alteracoes={
                            "pedido_pap": pedido,
                            "motivo": f"Pedido PAP vinculado a partir da venda duplicada #{v.id}.",
                        },
                    )
            try:
                from crm_app.models import SessaoTratamento
                from crm_app.services import tempo_tratamento_service as tt_svc

                tt_svc.encerrar_sessoes_venda(
                    v.id,
                    SessaoTratamento.MODULO_AUDITORIA,
                    SessaoTratamento.MOTIVO_REPROVADO,
                    status_resultado=st_dup.nome,
                )
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS("-" * 40))
        if not confirmar:
            self.stdout.write(self.style.WARNING("DRY-RUN: nenhuma venda foi alterada. Use --confirmar para aplicar."))
        self.stdout.write(f"Vendas reprovadas como DUPLICIDADE: {reprovadas}")
        self.stdout.write(f"Pedidos PAP vinculados à venda da esteira: {vinculadas}")
