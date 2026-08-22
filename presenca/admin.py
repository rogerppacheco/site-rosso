from django.contrib import admin
from .models import Presenca, MotivoAusencia, DiaNaoUtil

@admin.register(MotivoAusencia)
class MotivoAusenciaAdmin(admin.ModelAdmin):
    """
    Classe de Admin para o modelo MotivoAusencia.
    - list_display: Mostra 'motivo' e 'gera_desconto' na listagem.
    - fields: Permite editar 'motivo' e 'gera_desconto' no formulário.
    - search_fields: Adiciona busca pelo campo 'motivo'.
    """
    list_display = ('motivo', 'gera_desconto')
    fields = ('motivo', 'gera_desconto') # Linha adicionada para a melhoria
    search_fields = ('motivo',)

@admin.register(DiaNaoUtil)
class DiaNaoUtilAdmin(admin.ModelAdmin):
    list_display = ('data', 'descricao')
    search_fields = ('descricao',)
    list_filter = ('data',)

@admin.register(Presenca)
class PresencaAdmin(admin.ModelAdmin):
    list_display = ('colaborador', 'data', 'status', 'motivo', 'lancado_por')
    list_filter = ('data', 'status', 'colaborador__username')
    search_fields = ('colaborador__username', 'data', 'observacao')
    autocomplete_fields = ['colaborador', 'motivo', 'lancado_por'] 

    fieldsets = (
        (None, {
            'fields': ('colaborador', 'data', 'status')
        }),
        ('Detalhes da Ausência', {
            'classes': ('collapse',),
            'fields': ('motivo', 'observacao'),
        }),
        ('Metadados', {
            'fields': ('lancado_por',),
        }),
    )