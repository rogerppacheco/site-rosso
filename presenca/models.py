# presenca/models.py
from django.db import models
from django.conf import settings

class MotivoAusencia(models.Model):
    motivo = models.CharField(max_length=255, unique=True)
    gera_desconto = models.BooleanField(default=False)

    def __str__(self):
        return self.motivo

class Presenca(models.Model):
    colaborador = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.CASCADE, 
        related_name='presencas'
    )
    data = models.DateField()
    motivo = models.ForeignKey(MotivoAusencia, on_delete=models.SET_NULL, null=True, blank=True)
    observacao = models.TextField(blank=True, null=True)
    status = models.BooleanField(default=True)
    
    lancado_por = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='presencas_lancadas'
    )

    # --- CAMPOS NOVOS ADICIONADOS AQUI ---
    criado_em = models.DateTimeField(auto_now_add=True, null=True) # Registra a data/hora de criação
    editado_em = models.DateTimeField(auto_now=True, null=True)     # Registra a data/hora da última edição
    editado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='presencas_editadas'
    )

    class Meta:
        unique_together = ('colaborador', 'data')
        indexes = [
            models.Index(fields=['colaborador', 'data']),
        ]

    def __str__(self):
        estado = "Presente" if self.status else f"Ausente ({self.motivo})"
        return f"{self.colaborador.username} - {self.data} - {estado}"

class ConfirmacaoPresencaDia(models.Model):
    """
    Confirmação do dia de presença via selfie com o time.
    O supervisor/líder tira uma foto (câmera ao vivo) com data e local; a imagem
    é enviada por WhatsApp à Diretoria.
    """
    data = models.DateField(db_index=True)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='confirmacoes_presenca_dia'
    )
    foto_url = models.URLField(max_length=500, blank=True)  # reservado; selfies vão por WhatsApp
    latitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Confirmação de presença (selfie do dia)"
        verbose_name_plural = "Confirmações de presença (selfies)"
        # Um supervisor pode ter apenas uma confirmação por data (ou permitir várias; ajuste conforme regra)
        unique_together = [['data', 'supervisor']]
        ordering = ['-data', '-criado_em']

    def __str__(self):
        return f"{self.data} - {self.supervisor.username}"


class DiaNaoUtil(models.Model):
    data = models.DateField(unique=True)
    descricao = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.data} - {self.descricao}"


class LogLembretePresencaSupervisor(models.Model):
    """Controle de idempotência dos lembretes WhatsApp e falta automática às 12h."""

    SLOT_CHOICES = [
        ("10h", "Lembrete 10h"),
        ("11h", "Lembrete 11h"),
        ("12h_falta", "Falta automática 12h"),
    ]

    data = models.DateField(db_index=True)
    slot = models.CharField(max_length=20, choices=SLOT_CHOICES)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="logs_lembrete_presenca",
    )
    sucesso = models.BooleanField(default=False)
    detalhe = models.CharField(max_length=500, blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log lembrete presença supervisor"
        verbose_name_plural = "Logs lembretes presença supervisor"
        unique_together = [["data", "slot", "supervisor"]]
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"{self.data} {self.slot} — {self.supervisor_id}"