from django.db import models
from django.contrib.auth.models import Group

# ---------------------------------------------------------
# 1. Calendário Fiscal (MANTIDO)
# ---------------------------------------------------------
class DiaFiscal(models.Model):
    data = models.DateField(unique=True)
    
    peso_venda = models.DecimalField(
        max_digits=3, decimal_places=2, default=1.00, verbose_name="Peso Venda (DU_VB)"
    )
    
    peso_instalacao = models.DecimalField(
        max_digits=3, decimal_places=2, default=1.00, verbose_name="Peso Instalação (DU_GROSS)"
    )
    
    feriado = models.BooleanField(default=False, verbose_name="É Feriado?")
    observacao = models.CharField(max_length=100, blank=True, null=True, verbose_name="Obs")

    class Meta:
        ordering = ['data']
        verbose_name = "Dia Fiscal"
        verbose_name_plural = "Calendário Fiscal"

    def __str__(self):
        return f"{self.data.strftime('%d/%m/%Y')} - VB: {self.peso_venda}"

# ---------------------------------------------------------
# 2. Regra de Automação (NOVO - Substitui ConfiguracaoEnvio)
# ---------------------------------------------------------
class RegraAutomacao(models.Model):
    EVENTO_CHOICES = [
        ('NOVO_CDOI', 'Novo CDOI Solicitado (Record Vertical)'),
        # Futuramente você pode adicionar: ('NOVA_VENDA', 'Nova Venda Realizada'),
    ]

    nome = models.CharField(max_length=100, help_text="Ex: Aviso Backoffice - Novo CDOI")
    ativo = models.BooleanField(default=True)
    evento_gatilho = models.CharField(max_length=50, choices=EVENTO_CHOICES, default='NOVO_CDOI')
    
    # Armazena lista de IDs (JIDs) dos grupos do WhatsApp. Ex: ["12036...g.us"]
    destinos_grupos = models.JSONField(default=list, blank=True, verbose_name="Grupos de Destino (IDs)")
    
    # Armazena lista de números individuais extras
    destinos_numeros = models.JSONField(default=list, blank=True, verbose_name="Números Individuais")

    template_mensagem = models.TextField(
        verbose_name="Modelo da Mensagem",
        help_text="Variáveis disponíveis: {id}, {cliente}, {sindico}, {contato}, {total_hps}, {usuario}, {link}",
        default="🔔 *NOVO CDOI*\nCliente: {cliente}\nResp: {usuario}"
    )

    def __str__(self):
        return f"{self.nome} ({self.get_evento_gatilho_display()})"

    class Meta:
        verbose_name = "Regra de Automação"
        verbose_name_plural = "Regras de Automação"