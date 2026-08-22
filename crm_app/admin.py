from django.contrib import admin
from .models import (
    SafraM10, ContratoM10, FaturaM10, HistoricoBuscaFatura,
    ImportacaoAgendamento, ImportacaoRecompra, ImportacaoFPD, LogImportacaoFPD,
    ImportacaoChurn, LogImportacaoChurn, PapBoEmUso, FilaEsperaPAP,
    RegraComissaoFaixa, ConfigComissaoVendedor,
    ImportacaoEstabelecimentoCNPJ, LogImportacaoEstabelecimentoCNPJ,
    CepLocalidade,
    FunilVendaWppTentativa, FunilVendaWppEvento,
    HistoricoAtendimentoIACliente,
    SessaoTratamento, RelatorioTratamentoConfig,
    WhatsAppTarifaOficial, HistoricoCustoWhatsAppOficial,
    CidadeOfertaEspecial,
)


@admin.register(SafraM10)
class SafraM10Admin(admin.ModelAdmin):
    list_display = ('mes_referencia', 'total_instalados', 'total_ativos', 'total_elegivel_bonus', 'valor_bonus_total')
    list_filter = ('mes_referencia',)
    search_fields = ('mes_referencia',)


@admin.register(ContratoM10)
class ContratoM10Admin(admin.ModelAdmin):
    list_display = (
        'ordem_servico', 
        'numero_contrato_definitivo', 
        'status_fatura_fpd',
        'data_vencimento_fpd',
        'data_pagamento_fpd',
        'elegivel_bonus', 
        'teve_downgrade'
    )
    list_filter = ('elegivel_bonus', 'teve_downgrade', 'status_fatura_fpd')
    search_fields = ('ordem_servico', 'numero_contrato_definitivo', 'venda__cliente__nome_razao_social')
    raw_id_fields = ('venda',)
    readonly_fields = (
        'criado_em', 
        'atualizado_em', 
        'data_ultima_sincronizacao_fpd',
        'data_vencimento_fpd',
        'data_pagamento_fpd',
        'status_fatura_fpd',
        'valor_fatura_fpd',
        'nr_dias_atraso_fpd'
    )
    
    fieldsets = (
        ('Identificação', {
            'fields': ('numero_contrato', 'ordem_servico', 'numero_contrato_definitivo', 'venda', 'safra')
        }),
        ('Cliente', {
            'fields': ('cliente_nome', 'cpf_cliente', 'vendedor')
        }),
        ('Plano', {
            'fields': ('plano_original', 'plano_atual', 'valor_plano', 'data_instalacao')
        }),
        ('Status', {
            'fields': ('status_contrato', 'teve_downgrade', 'elegivel_bonus', 'data_cancelamento', 'motivo_cancelamento')
        }),
        ('Dados FPD (Preenchidos Automaticamente)', {
            'fields': (
                'status_fatura_fpd',
                'data_vencimento_fpd', 
                'data_pagamento_fpd', 
                'valor_fatura_fpd',
                'nr_dias_atraso_fpd',
                'data_ultima_sincronizacao_fpd'
            ),
            'classes': ('collapse',)
        }),
        ('Observações', {
            'fields': ('observacao',)
        }),
        ('Auditoria', {
            'fields': ('criado_em', 'atualizado_em'),
            'classes': ('collapse',)
        }),
    )


@admin.register(FaturaM10)
class FaturaM10Admin(admin.ModelAdmin):
    list_display = ('contrato', 'numero_fatura', 'valor', 'data_vencimento', 'status')
    list_filter = ('status', 'numero_fatura')
    search_fields = ('contrato__numero_contrato', 'numero_fatura_operadora')
    raw_id_fields = ('contrato',)


@admin.register(ImportacaoAgendamento)
class ImportacaoAgendamentoAdmin(admin.ModelAdmin):
    list_display = ('cd_nrba', 'nr_ordem', 'dt_agendamento', 'nm_municipio', 'sg_uf', 'st_ba', 'criado_em')
    list_filter = ('sg_uf', 'st_ba', 'dt_agendamento', 'anomes')
    search_fields = ('cd_nrba', 'nr_ordem', 'nm_municipio', 'nm_gc')
    date_hierarchy = 'dt_agendamento'
    list_per_page = 50
    ordering = ['-dt_agendamento', '-criado_em']

@admin.register(ImportacaoRecompra)
class ImportacaoRecompraAdmin(admin.ModelAdmin):
    list_display = ('nr_ordem', 'nm_municipio', 'sg_uf', 'st_ordem', 'dt_venda_particao', 'resultado', 'created_at')
    list_filter = ('sg_uf', 'st_ordem', 'resultado', 'created_at', 'ds_anomes')
    search_fields = ('nr_ordem', 'nm_municipio', 'nm_seg', 'nm_regional', 'nm_diretoria')
    date_hierarchy = 'dt_venda_particao'
    list_per_page = 50
    ordering = ['-dt_venda_particao', '-created_at']
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ImportacaoFPD)
class ImportacaoFPDAdmin(admin.ModelAdmin):
    list_display = ('nr_ordem', 'indicador', 'nm_seg', 'id_contrato', 'nr_fatura', 'ds_status_fatura', 'dt_venc_orig', 'dt_pagamento', 'vl_fatura', 'importada_em')
    list_filter = ('indicador', 'nm_seg', 'ds_status_fatura', 'match_status', 'dt_venc_orig', 'importada_em')
    search_fields = ('nr_ordem', 'id_contrato', 'nr_fatura', 'nm_seg', 'contrato_m10__numero_contrato')
    date_hierarchy = 'dt_venc_orig'
    list_per_page = 100
    ordering = ['-importada_em', 'nr_ordem']
    raw_id_fields = ('contrato_m10',)
    readonly_fields = ('importada_em', 'atualizada_em')


@admin.register(LogImportacaoFPD)
class LogImportacaoFPDAdmin(admin.ModelAdmin):
    list_display = ('nome_arquivo', 'usuario', 'status_badge', 'total_linhas', 'sucesso', 'erros', 'data_importacao')
    list_filter = ('status', 'data_importacao')
    search_fields = ('nome_arquivo', 'usuario__username', 'mensagem')
    date_hierarchy = 'data_importacao'
    list_per_page = 50
    ordering = ['-data_importacao']
    readonly_fields = ('data_importacao',)
    
    def status_badge(self, obj):
        cores = {
            'SUCESSO': 'green',
            'ERRO': 'red',
            'PARCIAL': 'orange'
        }
        return f'<span style="background-color: {cores.get(obj.status, "gray")}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">{obj.status}</span>'
    status_badge.short_description = 'Status'
    status_badge.allow_tags = True


@admin.register(ImportacaoChurn)
class ImportacaoChurnAdmin(admin.ModelAdmin):
    list_display = ('nr_ordem', 'numero_pedido', 'uf', 'produto', 'dt_retirada', 'motivo_retirada', 'tipo_retirada')
    list_filter = ('uf', 'tipo_retirada', 'dt_retirada', 'anomes_retirada')
    search_fields = ('nr_ordem', 'numero_pedido', 'municipio', 'gc', 'codigo_sap')
    date_hierarchy = 'dt_retirada'
    list_per_page = 100
    ordering = ['-dt_retirada', 'nr_ordem']


@admin.register(LogImportacaoChurn)
class LogImportacaoChurnAdmin(admin.ModelAdmin):
    list_display = ('nome_arquivo', 'usuario', 'status_badge', 'total_linhas', 'total_processadas', 'cancelados_display', 'reativados_display', 'duracao_display', 'iniciado_em')
    list_filter = ('status', 'iniciado_em', 'finalizado_em')
    search_fields = ('nome_arquivo', 'usuario__username', 'mensagem_erro')
    date_hierarchy = 'iniciado_em'
    list_per_page = 50
    ordering = ['-iniciado_em']
    readonly_fields = ('iniciado_em', 'finalizado_em', 'duracao_segundos', 'tamanho_arquivo', 'detalhes_json')
    
    def status_badge(self, obj):
        cores = {
            'PROCESSANDO': 'blue',
            'SUCESSO': 'green',
            'ERRO': 'red',
            'PARCIAL': 'orange'
        }
        return f'<span style="background-color: {cores.get(obj.status, "gray")}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">{obj.status}</span>'
    status_badge.short_description = 'Status'
    status_badge.allow_tags = True
    
    def cancelados_display(self, obj):
        return f'{obj.total_contratos_cancelados} cancelados'
    cancelados_display.short_description = 'Cancelados'
    
    def reativados_display(self, obj):
        return f'{obj.total_contratos_reativados} reativados'
    reativados_display.short_description = 'Reativados'
    
    def duracao_display(self, obj):
        if obj.duracao_segundos:
            return f'{obj.duracao_segundos}s'
        return '-'
    duracao_display.short_description = 'Duração'


@admin.register(HistoricoBuscaFatura)
class HistoricoBuscaFaturaAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'tipo_busca',
        'safra',
        'inicio_em',
        'duracao_display',
        'total_faturas',
        'faturas_sucesso',
        'faturas_erro',
        'status_badge'
    )
    list_filter = ('tipo_busca', 'status', 'safra', 'inicio_em')
    search_fields = ('safra', 'mensagem')
    readonly_fields = (
        'inicio_em',
        'termino_em',
        'duracao_segundos',
        'total_contratos',
        'total_faturas',
        'faturas_sucesso',
        'faturas_erro',
        'faturas_nao_disponiveis',
        'faturas_retry',
        'tempo_medio_fatura',
        'tempo_min_fatura',
        'tempo_max_fatura',
        'logs'
    )
    
    fieldsets = (
        ('Identificação', {
            'fields': ('tipo_busca', 'safra', 'usuario', 'status')
        }),
        ('Tempo de Execução', {
            'fields': ('inicio_em', 'termino_em', 'duracao_segundos')
        }),
        ('Estatísticas', {
            'fields': (
                'total_contratos',
                'total_faturas',
                'faturas_sucesso',
                'faturas_erro',
                'faturas_nao_disponiveis',
                'faturas_retry'
            )
        }),
        ('Performance', {
            'fields': ('tempo_medio_fatura', 'tempo_min_fatura', 'tempo_max_fatura')
        }),
        ('Detalhes', {
            'fields': ('mensagem', 'logs'),
            'classes': ('collapse',)
        })
    )
    
    def duracao_display(self, obj):
        if obj.duracao_segundos:
            minutos = int(obj.duracao_segundos / 60)
            segundos = obj.duracao_segundos % 60
            if minutos > 0:
                return f'{minutos}m {segundos:.1f}s'
            return f'{segundos:.1f}s'
        return '-'
    duracao_display.short_description = 'Duração'
    
    def status_badge(self, obj):
        colors = {
            'EM_ANDAMENTO': 'warning',
            'CONCLUIDA': 'success',
            'ERRO': 'danger',
            'CANCELADA': 'secondary'
        }
        color = colors.get(obj.status, 'secondary')
        return f'<span class="badge bg-{color}">{obj.get_status_display()}</span>'
    status_badge.short_description = 'Status'
    status_badge.allow_tags = True


@admin.register(PapBoEmUso)
class PapBoEmUsoAdmin(admin.ModelAdmin):
    list_display = ('bo_usuario', 'vendedor_telefone', 'locked_at', 'sessao_whatsapp_id')
    list_filter = ('locked_at',)
    search_fields = ('vendedor_telefone', 'bo_usuario__username')


@admin.register(FilaEsperaPAP)
class FilaEsperaPAPAdmin(admin.ModelAdmin):
    list_display = ('telefone', 'tipo_acao', 'created_at', 'sessao_whatsapp_id')
    list_filter = ('tipo_acao', 'created_at')
    search_fields = ('telefone',)
    ordering = ('created_at',)


@admin.register(RegraComissaoFaixa)
class RegraComissaoFaixaAdmin(admin.ModelAdmin):
    list_display = ('perfil', 'finalidade', 'vendedor', 'faixa_nome', 'min_vendas', 'max_vendas')
    list_filter = ('perfil', 'finalidade')
    search_fields = ('faixa_nome', 'vendedor__username')
    raw_id_fields = ('vendedor',)


@admin.register(ConfigComissaoVendedor)
class ConfigComissaoVendedorAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'perfil_comissao', 'usar_valor_manual')
    list_filter = ('perfil_comissao', 'usar_valor_manual')
    search_fields = ('usuario__username',)
    raw_id_fields = ('usuario',)


@admin.register(CidadeOfertaEspecial)
class CidadeOfertaEspecialAdmin(admin.ModelAdmin):
    list_display = ('municipio', 'uf', 'ativo', 'atualizado_em')
    list_filter = ('uf', 'ativo')
    search_fields = ('municipio', 'municipio_normalizado', 'uf')
    ordering = ('uf', 'municipio')


@admin.register(ImportacaoEstabelecimentoCNPJ)
class ImportacaoEstabelecimentoCNPJAdmin(admin.ModelAdmin):
    list_display = ('cnpj_completo', 'nome_fantasia', 'cnae_fiscal', 'uf', 'codigo_municipio', 'situacao_cadastral', 'importada_em')
    list_filter = ('situacao_cadastral', 'uf', 'cnae_fiscal')
    search_fields = ('cnpj_completo', 'cnpj_raiz', 'nome_fantasia', 'logradouro', 'bairro')
    list_per_page = 50
    ordering = ['-importada_em']


@admin.register(CepLocalidade)
class CepLocalidadeAdmin(admin.ModelAdmin):
    list_display = ('cep', 'localidade', 'uf')
    search_fields = ('cep', 'localidade', 'uf')
    list_filter = ('uf',)
    ordering = ['cep']


@admin.register(LogImportacaoEstabelecimentoCNPJ)
class LogImportacaoEstabelecimentoCNPJAdmin(admin.ModelAdmin):
    list_display = ('nome_arquivo', 'usuario', 'status', 'total_linhas', 'total_importadas', 'total_erros', 'duracao_segundos', 'iniciado_em')
    list_filter = ('status', 'iniciado_em')
    search_fields = ('nome_arquivo',)
    ordering = ['-iniciado_em']


class FunilVendaWppEventoInline(admin.TabularInline):
    model = FunilVendaWppEvento
    extra = 0
    readonly_fields = ('criado_em', 'etapa_codigo', 'funil_estagio', 'tipo_evento', 'payload')
    can_delete = False


@admin.register(FunilVendaWppTentativa)
class FunilVendaWppTentativaAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'telefone', 'usuario', 'status', 'funil_estagio_max', 'protocolo_pap', 'iniciado_em', 'finalizado_em',
    )
    list_filter = ('status', 'funil_estagio_max')
    search_fields = ('telefone', 'protocolo_pap', 'usuario__username')
    readonly_fields = ('iniciado_em', 'atualizado_em')
    raw_id_fields = ('usuario', 'sessao_whatsapp')
    inlines = [FunilVendaWppEventoInline]


@admin.register(HistoricoAtendimentoIACliente)
class HistoricoAtendimentoIAClienteAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'criado_em',
        'venda',
        'telefone',
        'intencao',
        'fonte_resposta',
        'origem',
        'avisos_bo_enviados',
    )
    list_filter = ('intencao', 'fonte_resposta', 'origem', 'criado_em')
    search_fields = (
        'telefone',
        'mensagem_cliente',
        'resposta_sistema',
        'venda__id',
        'venda__ordem_servico',
        'venda__cliente__nome_razao_social',
    )
    readonly_fields = ('criado_em',)
    raw_id_fields = ('venda',)
    date_hierarchy = 'criado_em'
    ordering = ('-criado_em',)


@admin.register(SessaoTratamento)
class SessaoTratamentoAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'venda',
        'usuario',
        'modulo',
        'iniciado_em',
        'finalizado_em',
        'duracao_segundos',
        'motivo_fim',
        'status_resultado',
    )
    list_filter = ('modulo', 'motivo_fim', 'iniciado_em')
    search_fields = (
        'venda__id',
        'venda__ordem_servico',
        'usuario__username',
        'usuario__first_name',
    )
    raw_id_fields = ('venda', 'usuario')
    date_hierarchy = 'iniciado_em'
    ordering = ('-iniciado_em',)


@admin.register(RelatorioTratamentoConfig)
class RelatorioTratamentoConfigAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'ativo',
        'destino_telefone',
        'horario_envio',
        'incluir_auditoria',
        'incluir_esteira',
        'limite_outlier_minutos',
        'timeout_ociosidade_minutos',
        'atualizado_em',
    )


@admin.register(WhatsAppTarifaOficial)
class WhatsAppTarifaOficialAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'utility_brl',
        'marketing_brl',
        'authentication_brl',
        'service_brl',
        'atualizado_em',
    )


@admin.register(HistoricoCustoWhatsAppOficial)
class HistoricoCustoWhatsAppOficialAdmin(admin.ModelAdmin):
    list_display = (
        'criado_em',
        'tipo_envio',
        'categoria',
        'template_name',
        'custo_estimado_brl',
        'sucesso',
        'telefone',
        'origem',
    )
    list_filter = ('categoria', 'tipo_envio', 'sucesso')
    search_fields = ('telefone', 'template_name', 'message_id')
    date_hierarchy = 'criado_em'
    ordering = ('-criado_em',)
