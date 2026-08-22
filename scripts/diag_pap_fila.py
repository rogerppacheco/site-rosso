"""Diagnóstico rápido da fila PAP (rodar com railway run -s site-record-pap)."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.db.models import Count
from django.utils import timezone

from crm_app.models import HistoricoConsultaAutomacaoPAP
from crm_app.pap_job_fila import PapJobFila

print("=== FILA PAP (resumo por status) ===")
for st in ("pendente", "processando", "concluido", "erro"):
    print(f"  {st}: {PapJobFila.objects.filter(status=st).count()}")

print("\n=== JOBS processando (todos tipos) ===")
for j in PapJobFila.objects.filter(status="processando").order_by("iniciado_em"):
    ref = j.iniciado_em or j.criado_em
    age = timezone.now() - ref
    print(
        f"  id={j.id} tipo={j.tipo} tel=...{j.telefone[-6:]} "
        f"iniciado={j.iniciado_em} age={age} tent={j.tentativas}"
    )

print("\n=== ULTIMOS status_online ===")
for j in PapJobFila.objects.filter(tipo="status_online").order_by("-criado_em")[:10]:
    age = timezone.now() - j.criado_em
    print(
        f"  id={j.id} status={j.status} tel=...{j.telefone[-6:]} "
        f"criado={j.criado_em} age={age} tent={j.tentativas}"
    )

print("\n=== PENDENTES por tipo ===")
for row in (
    PapJobFila.objects.filter(status="pendente")
    .values("tipo")
    .annotate(n=Count("id"))
    .order_by("-n")
):
    print(f"  {row['tipo']}: {row['n']}")

print("\n=== JOBS TRAVADOS (detalhe) ===")
for jid in (94, 109, 479):
    j = PapJobFila.objects.filter(id=jid).first()
    if j:
        print(f"  id={j.id} tipo={j.tipo} status={j.status} tel={j.telefone}")
        print(f"    payload={j.payload}")
        if j.erro:
            print(f"    erro={j.erro[:120]}")

print("\n=== JOB USUARIO 553188804000 (se existir pendente) ===")
for j in PapJobFila.objects.filter(telefone__contains="8804000", status="pendente").order_by("-criado_em")[:3]:
    print(f"  id={j.id} tipo={j.tipo} criado={j.criado_em} payload={j.payload}")

print("\n=== HISTORICO status (ultimos 10) ===")
for h in (
    HistoricoConsultaAutomacaoPAP.objects.filter(tipo_automacao="status")
    .order_by("-criado_em")[:10]
):
    tel = h.telefone_solicitante[-6:] if h.telefone_solicitante else ""
    print(
        f"  id={h.id} status={h.status_execucao} tel=...{tel} "
        f"criado={h.criado_em} msg={str(h.mensagem_resultado)[:60]}"
    )
