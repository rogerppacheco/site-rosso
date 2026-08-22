"""Reseta jobs PAP travados em processando."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from crm_app.pap_job_fila import PapJobFila

IDS = [94, 109, 479]
n = PapJobFila.objects.filter(id__in=IDS, status="processando").update(
    status="pendente",
    iniciado_em=None,
    erro="",
)
print(f"Resetados: {n}")
for j in PapJobFila.objects.filter(id__in=IDS):
    print(f"  id={j.id} status={j.status} tipo={j.tipo}")
