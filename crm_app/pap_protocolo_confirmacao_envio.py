"""
Protocolo de confirmação enviado ao cliente no WhatsApp (resumo PAP / auditoria).
Formato: YYYYMMDDHHMM + sequência 0001, 0002… por minuto (fuso America/São Paulo).
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone


@transaction.atomic
def gerar_protocolo_confirmacao_envio() -> str:
    from crm_app.models import PapProtocoloConfirmacaoSequencia

    janela = timezone.localtime().strftime("%Y%m%d%H%M")
    obj, _ = PapProtocoloConfirmacaoSequencia.objects.select_for_update().get_or_create(
        janela=janela,
        defaults={"ultimo": 0},
    )
    PapProtocoloConfirmacaoSequencia.objects.filter(pk=obj.pk).update(ultimo=F("ultimo") + 1)
    obj.refresh_from_db()
    return f"{janela}{int(obj.ultimo):04d}"
