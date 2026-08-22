from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

# IMPORTAÇÃO DAS VIEWS DE AUTH (DO APP USUARIOS)
from usuarios.views import LoginView, DefinirNovaSenhaView

# Record Apoia APIs
from .esteira_gestao_aproveitamento_api import GestaoAproveitamentoEsteiraView
from .esteira_churn_tratamento_api import EsteiraChurnTratamentoView
from .record_apoia_api import (
    RecordApoiaUploadView,
    RecordApoiaListView,
    RecordApoiaDownloadView,
    RecordApoiaDeleteView,
    RecordApoiaEditView,
    RecordApoiaToggleActiveView,
    RecordApoiaDiagnosticoView,
    RecordApoiaBuscarView,
    RecordApoiaAdminOrfaosView,
    RecordApoiaAdminLimparOrfaosView,
)

# IMPORTAÇÕES ESPECÍFICAS DE VIEWS
from .views_whatsapp_ia_governanca import (
    whatsapp_ia_config_view,
    whatsapp_telefones_sem_ia_view,
    whatsapp_telefone_sem_ia_detail_view,
)
from .pedido_ajuda_gc_api import (
    EtapaErroAjudaGcListCreateView,
    EtapaErroAjudaGcDetailView,
    PedidoAjudaGcContextoView,
    PedidoAjudaGcEnviarView,
    PedidoAjudaGcExportarView,
)
from .views import (
    listar_screenshots_debug,
    baixar_screenshot_debug,
    buscar_fatura_nio_bonus_m10,
    duplicar_venda,
    liberar_pap_bo_view,
    historico_consultas_pap_bo_view,
    consultar_biometria_brpronto_view,
    # ViewSets
    VendaViewSet, 
    ClienteViewSet, 
    ComissaoOperadoraViewSet,
    ComunicadoViewSet,
    EstatisticasBotWhatsAppView,
    LancamentoFinanceiroViewSet,
    PainelSegundaAPIView,
    GrupoDisparoViewSet,

    # Views Genéricas (List/Detail)
    OperadoraListCreateView, OperadoraDetailView,
    PlanoListCreateView, PlanoDetailView,
    FormaPagamentoListCreateView, FormaPagamentoDetailView,
    StatusCRMListCreateView, StatusCRMDetailView,
    MotivoPendenciaListCreateView, MotivoPendenciaDetailView,
    StatusAgendamentoListCreateView, StatusAgendamentoDetailView,
    CidadeOfertaEspecialListCreateView, CidadeOfertaEspecialDetailView,
    CidadeOfertaEspecialSincronizarView,
    RegraComissaoListCreateView, RegraComissaoDetailView,
    RegraComissaoFaixaListCreateView, RegraComissaoFaixaDetailView,
    RegraComissaoFaixaExportarView, RegraComissaoFaixaImportarView,
    ComissaoMatrizView,
    ConfigComissaoVendedorListView, ConfigComissaoVendedorDetailView,
    ConfigComissaoVendedorSalvarMesView,
    ConfigComissaoVendedorExportarView, ConfigComissaoVendedorImportarView,
    CampanhaListCreateView, CampanhaDetailView,
    
    # Dashboards e Importações
    DashboardResumoView,
    VendasStatusCountView,
    ListaVendedoresView,
    ComissionamentoView,
    FolhaComissionamentoView,
    FecharPagamentoView,
    ReabrirPagamentoView,
    HistoricoPagamentoDetalheView,
    GerarRelatorioPDFView,
    EnviarExtratoEmailView,
    ImportacaoOsabView, ImportacaoOsabDetailView, DownloadRelatorioOSABView, CancelarImportacaoOSABView, ReverterImportacaoOSABView, AnaliseComparacaoOSABView, LimparImportacaoOSABView, LimparBaseDFVView, LimparBaseCNPJView,
    ControleTTsAPIView, ControleTTTratadoAPIView, ControleTTsProximoAPIView,
    ImportacaoChurnView, ImportacaoChurnDetailView,
    ImportacaoCicloPagamentoView,
    PerformanceVendasView,
    ImportacaoLegadoView,
    ImportacaoAgendamentoView,
    ImportacaoRecompraView,
    LogsImportacaoLegadoView,
    LogsImportacaoAgendamentoView,
    CancelarImportacaoAgendamentoView,
    LogsImportacaoFPDView,
    LogsImportacaoOSABView,
    LogsImportacaoDFVView,
    LogsImportacaoRecompraView,
    
    # NOVAS VIEWS (Mapas, ZAP, Performance)
    api_verificar_whatsapp,
    api_verificar_email,
    enviar_comissao_whatsapp,
    enviar_folha_extrato_whatsapp,
    exportar_folha_extrato_pdf,
    exportar_comissionamento_resumo_excel,
    exportar_comissionamento_extrato_excel,
    enviar_resultado_campanha_whatsapp,
    ImportarKMLView,        
    ImportarDFVView,
    ImportarCNPJView,
    ImportarGdpPrecoView,
    LogsImportacaoCNPJView,
    LogsImportacaoGdpPrecoView,
    PrecoPlanoGdpLookupView,
    WebhookWhatsAppView,
    serve_pdf_view,
    listar_grupos_whatsapp_api,
    VerificarPermissaoGestaoView,
    
    # Performance (API e Exportação)
    PainelPerformanceView,
    ExportarPerformanceExcelView,
    EnviarImagemPerformanceView, 
    ConfigurarAutomacaoView,
    
    # View da Página HTML (Render)
    page_painel_performance,
    
    # Relatório Campanha
    relatorio_resultado_campanha,

    # --- NOVAS VIEWS DE CONFIRMAÇÃO E REVERSÃO DE DESCONTOS ---
    PendenciasDescontoView,
    ConfirmarDescontosEmMassaView,
    HistoricoDescontosAutoView,
    ReverterDescontoMassaView,
    AdiantamentosEsteiraView,

    # --- CDOI (Record Vertical) ---
    CdoiCreateView,  # Criação
    CdoiListView,    # Listagem (NOVO)
    CdoiDashboardView,
    CnpjEstabelecimentosCdoiView,
    CnpjMunicipiosCdoiView,
    CnpjCnaesCdoiView,
    CnpjBairrosCdoiView,
    CnpjUfsCdoiView,
    CdoiUpdateView,  # Edição/Status (NOVO)
    ViaCepProxyView,
    NominatimProxyView,
    page_cdoi_novo,  # Página HTML
    
    # --- PRÉ-VENDAS PÚBLICAS ---
    GerarLinkPublicoPreVendaView,
    PreVendaPublicaFormView,
    PreVendasPorAcionamentoView,
    prevenda_publica_landing,
    
    # --- BÔNUS M-10 & FPD ---
    SafraM10ListView,
    DashboardM10View,
    DashboardFPDView,
    ContratoM10DetailView,
    ImportarFPDView,
    ImportarChurnView,
    AtualizarFaturasView,
    ExportarM10View,
    ExportarAgendamentosDiaView,
    ExportarAgendadosPendentesEsteiraView,
    EnviarLembreteInstalacaoView,
    EnviarPossoAnteciparVendedorView,
    EnviarPossoReagendarConsultorView,
    EnviarBoasVindasView,
    BoasVindasInstalacoesView,
    BoasVindasRetornosView,
    BoasVindasDetalheView,
    BoasVindasStatusListView,
    BoasVindasSugestaoIAView,
    BoasVindasEnviarGestaoView,
    BoasVindasAgendarView,
    BoasVindasFilaStatusView,
    WhatsAppCustosOficiaisView,
    page_bonus_m10,
    NioDividasView,
    BuscarAnteciparInstalacaoView,
    SolicitarAnteciparInstalacaoView,
    ConfigAnteciparInstalacaoView,
    ConfigEsteiraVendasView,
    EnviarRelatorioPendenciaClienteView,
    HistoricoAnteciparInstalacaoView,
    ExportarHistoricoAnteciparInstalacaoView,
    RespostaGCAnteciparInstalacaoView,
)

# Importar módulo de views de análise de buscas
from . import views_analise_busca
from . import conhecimento_ia_api
from . import vtop_api
from .auditoria_ligacoes_api import (
    AuditoriaLigacaoHistoricoView,
    AuditoriaLigacaoListView,
    AuditoriaLigacaoOpcoesView,
    AuditoriaLigacaoSincronizarLoteView,
    AuditoriaLigacaoSincronizarView,
    AuditoriaLigacaoStartView,
    AuditoriaLigacaoWebhookView,
)
from .auditoria_sem_slot_api import AuditoriaSemSlotEnviarView, AuditoriaSemSlotRelatorioView
from .auditoria_inclusao_api import (
    DemandaInclusaoListView,
    DemandaInclusaoDetailView,
    DemandaInclusaoIniciarView,
    DemandaInclusaoConcluirView,
    DemandaInclusaoErroView,
)
from .pendencia_indevida_api import PendenciaIndevidaRegistrarView, PendenciaIndevidaRelatorioView
from .funil_venda_wpp_api import FunilVendaWppTentativaDetailView, FunilVendaWppTentativaListView
from .esteira_sync_status_pap_api import (
    SyncStatusEsteiraCancelarView,
    SyncStatusEsteiraIniciarView,
    SyncStatusEsteiraStatusView,
)
from .esteira_consulta_status_pap_api import (
    ConsultaStatusEsteiraCancelarView,
    ConsultaStatusEsteiraIniciarView,
    ConsultaStatusEsteiraStatusView,
)
from .esteira_nio_reagendamento_api import (
    NioReagendamentoCancelarView,
    NioReagendamentoIniciarView,
    NioReagendamentoStatusView,
    NioReagendamentoUnitarioView,
)
from .tempo_tratamento_api import (
    encerrar_sessao_view,
    enviar_relatorio_tratamento_view,
    iniciar_sessao_view,
    ping_sessao_view,
    relatorio_tratamento_view,
)

router = DefaultRouter()
router.register(r'vendas', VendaViewSet, basename='venda')
router.register(r'clientes', ClienteViewSet, basename='cliente')
router.register(r'comissoes-operadora', ComissaoOperadoraViewSet, basename='comissao-operadora')
router.register(r'comunicados', ComunicadoViewSet, basename='comunicados')
router.register(r'grupos-disparo', GrupoDisparoViewSet, basename='grupos-disparo')
router.register(r'lancamentos-financeiros', LancamentoFinanceiroViewSet, basename='lancamentos-financeiros')

urlpatterns = [
    # Rotas específicas de vendas ANTES do router (evita que "enviar-boas-vindas" seja interpretado como pk)
    path('vendas/enviar-boas-vindas/', EnviarBoasVindasView.as_view(), name='enviar-boas-vindas'),
    # Boas-Vindas Gestão (ferramenta dedicada)
    path('boas-vindas/instalacoes/', BoasVindasInstalacoesView.as_view(), name='boas-vindas-instalacoes'),
    path('boas-vindas/retornos/', BoasVindasRetornosView.as_view(), name='boas-vindas-retornos'),
    path('boas-vindas/retornos/<int:pk>/', BoasVindasDetalheView.as_view(), name='boas-vindas-detalhe'),
    path('boas-vindas/status/', BoasVindasStatusListView.as_view(), name='boas-vindas-status'),
    path('boas-vindas/sugestao-ia/', BoasVindasSugestaoIAView.as_view(), name='boas-vindas-sugestao-ia'),
    path('boas-vindas/enviar/', BoasVindasEnviarGestaoView.as_view(), name='boas-vindas-enviar'),
    path('boas-vindas/agendar/', BoasVindasAgendarView.as_view(), name='boas-vindas-agendar'),
    path('boas-vindas/fila-status/', BoasVindasFilaStatusView.as_view(), name='boas-vindas-fila-status'),
    path('whatsapp-oficial/custos/', WhatsAppCustosOficiaisView.as_view(), name='whatsapp-oficial-custos'),
    # Consulta CNPJ na Receita (antes do router — evita 404 se a action não estiver registrada)
    path(
        'clientes/dados-cnpj/',
        ClienteViewSet.as_view({'get': 'dados_cnpj'}),
        name='cliente-dados-cnpj-direct',
    ),
    path('', include(router.urls)),
    path('painel-segunda/', PainelSegundaAPIView.as_view(), name='painel-segunda-api'),
    path('serve-pdf/<str:token>/', serve_pdf_view, name='serve-pdf'),
    path('duplicar-venda/', duplicar_venda, name='duplicar-venda'),
    path('liberar-pap-bo/', liberar_pap_bo_view, name='liberar-pap-bo'),
    path('historico-consultas-pap-bo/', historico_consultas_pap_bo_view, name='historico-consultas-pap-bo'),
    path('whatsapp-ia-config/', whatsapp_ia_config_view, name='whatsapp-ia-config'),
    path('whatsapp-telefones-sem-ia/', whatsapp_telefones_sem_ia_view, name='whatsapp-telefones-sem-ia'),
    path('whatsapp-telefones-sem-ia/<int:pk>/', whatsapp_telefone_sem_ia_detail_view, name='whatsapp-telefone-sem-ia-detail'),
    path('funil-venda-wpp/tentativas/', FunilVendaWppTentativaListView.as_view(), name='funil-venda-wpp-tentativas'),
    path('funil-venda-wpp/tentativas/<int:pk>/', FunilVendaWppTentativaDetailView.as_view(), name='funil-venda-wpp-tentativa-detail'),
    path('consultar-biometria-brpronto/', consultar_biometria_brpronto_view, name='consultar-biometria-brpronto'),
    # --- Endpoint para busca automática de fatura NIO (Bonus M-10) ---
    path('bonus-m10/buscar-fatura-nio/', buscar_fatura_nio_bonus_m10, name='buscar-fatura-nio-bonus-m10'),
    
    # --- ROTA DA NOVA CENTRAL DE IMPORTAÇÕES (MENU) ---
    path('importacoes/', TemplateView.as_view(template_name='importacoes.html'), name='central-importacoes'),

    # --- Auth ---
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/definir-senha/', DefinirNovaSenhaView.as_view(), name='definir-senha'),

    # --- Cadastros Gerais ---
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadora-list'),
    path('operadoras/<int:pk>/', OperadoraDetailView.as_view(), name='operadora-detail'),
    
    path('planos/', PlanoListCreateView.as_view(), name='plano-list'),
    path('planos/<int:pk>/', PlanoDetailView.as_view(), name='plano-detail'),

    path('formas-pagamento/', FormaPagamentoListCreateView.as_view(), name='forma-pagamento-list'),
    path('formas-pagamento/<int:pk>/', FormaPagamentoDetailView.as_view(), name='forma-pagamento-detail'),

    path('campanhas/', CampanhaListCreateView.as_view(), name='campanha-list'),
    path('campanhas/<int:pk>/', CampanhaDetailView.as_view(), name='campanha-detail'),
    
    path('campanhas/<int:campanha_id>/resultado/', relatorio_resultado_campanha, name='resultado-campanha'),
    path('campanhas/enviar-resultado-whatsapp/', enviar_resultado_campanha_whatsapp, name='enviar-resultado-campanha-whatsapp'),

    path('status/', StatusCRMListCreateView.as_view(), name='status-list'),
    path('status/<int:pk>/', StatusCRMDetailView.as_view(), name='status-detail'),
    
    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivo-list'),
    path('motivos-pendencia/<int:pk>/', MotivoPendenciaDetailView.as_view(), name='motivo-detail'),
    path('status-agendamento/', StatusAgendamentoListCreateView.as_view(), name='status-agendamento-list'),
    path('status-agendamento/<int:pk>/', StatusAgendamentoDetailView.as_view(), name='status-agendamento-detail'),
    path('cidades-oferta-especial/', CidadeOfertaEspecialListCreateView.as_view(), name='cidade-oferta-especial-list'),
    path('cidades-oferta-especial/sincronizar/', CidadeOfertaEspecialSincronizarView.as_view(), name='cidade-oferta-especial-sincronizar'),
    path('cidades-oferta-especial/<int:pk>/', CidadeOfertaEspecialDetailView.as_view(), name='cidade-oferta-especial-detail'),
    path('etapas-erro-ajuda-gc/', EtapaErroAjudaGcListCreateView.as_view(), name='etapas-erro-ajuda-gc-list'),
    path('etapas-erro-ajuda-gc/<int:pk>/', EtapaErroAjudaGcDetailView.as_view(), name='etapas-erro-ajuda-gc-detail'),
    path('pedido-ajuda-gc/contexto/', PedidoAjudaGcContextoView.as_view(), name='pedido-ajuda-gc-contexto'),
    path('pedido-ajuda-gc/enviar/', PedidoAjudaGcEnviarView.as_view(), name='pedido-ajuda-gc-enviar'),
    path('pedido-ajuda-gc/exportar/', PedidoAjudaGcExportarView.as_view(), name='pedido-ajuda-gc-exportar'),

    path('regras-comissao/', RegraComissaoListCreateView.as_view(), name='regra-list'),
    path('regras-comissao/<int:pk>/', RegraComissaoDetailView.as_view(), name='regra-detail'),
    path('regras-comissao-faixa/', RegraComissaoFaixaListCreateView.as_view(), name='regra-faixa-list'),
    path('regras-comissao-faixa/exportar/', RegraComissaoFaixaExportarView.as_view(), name='regra-faixa-exportar'),
    path('regras-comissao-faixa/importar/', RegraComissaoFaixaImportarView.as_view(), name='regra-faixa-importar'),
    path('regras-comissao-faixa/<int:pk>/', RegraComissaoFaixaDetailView.as_view(), name='regra-faixa-detail'),
    path('comissao-matriz/', ComissaoMatrizView.as_view(), name='comissao-matriz'),
    path('config-comissao-vendedor/', ConfigComissaoVendedorListView.as_view(), name='config-comissao-vendedor-list'),
    path('config-comissao-vendedor/salvar-mes/', ConfigComissaoVendedorSalvarMesView.as_view(), name='config-comissao-vendedor-salvar-mes'),
    path('config-comissao-vendedor/exportar/', ConfigComissaoVendedorExportarView.as_view(), name='config-comissao-vendedor-exportar'),
    path('config-comissao-vendedor/importar/', ConfigComissaoVendedorImportarView.as_view(), name='config-comissao-vendedor-importar'),
    path('config-comissao-vendedor/<int:user_id>/', ConfigComissaoVendedorDetailView.as_view(), name='config-comissao-vendedor-detail'),

    # --- Dashboards e Utilitários ---
    path('dashboard-resumo/', DashboardResumoView.as_view(), name='dashboard-resumo'),
    path('vendas-status-count/', VendasStatusCountView.as_view(), name='vendas-status-count'),
    path('lista-vendedores/', ListaVendedoresView.as_view(), name='lista-vendedores'),
    
    # --- Comissionamento ---
    path('comissionamento/', ComissionamentoView.as_view(), name='comissionamento'),
    path('comissionamento/folha/', FolhaComissionamentoView.as_view(), name='comissionamento-folha'),
    path('comissionamento/historico-detalhe/', HistoricoPagamentoDetalheView.as_view(), name='comissionamento-historico-detalhe'),
    path('fechar-pagamento/', FecharPagamentoView.as_view(), name='fechar-pagamento'),
    path('reabrir-pagamento/', ReabrirPagamentoView.as_view(), name='reabrir-pagamento'),
    path('gerar-relatorio-pdf/', GerarRelatorioPDFView.as_view(), name='gerar-relatorio-pdf'),
    path('enviar-extrato-email/', EnviarExtratoEmailView.as_view(), name='enviar-extrato-email'),
    path('comissionamento/whatsapp/', enviar_comissao_whatsapp, name='enviar-whatsapp-comissao'),
    path('comissionamento/enviar-folha-extrato-whatsapp/', enviar_folha_extrato_whatsapp, name='enviar-folha-extrato-whatsapp'),
    path('comissionamento/exportar-folha-extrato-pdf/', exportar_folha_extrato_pdf, name='exportar-folha-extrato-pdf'),
    path('comissionamento/exportar-resumo-excel/', exportar_comissionamento_resumo_excel, name='exportar-comissionamento-resumo-excel'),
    path('comissionamento/exportar-extrato-excel/', exportar_comissionamento_extrato_excel, name='exportar-comissionamento-extrato-excel'),
    
    # --- NOVAS ROTAS DE CONFIRMAÇÃO E REVERSÃO ---
    path('comissionamento/pendencias-desconto/', PendenciasDescontoView.as_view(), name='pendencias-desconto'),
    path('comissionamento/confirmar-descontos/', ConfirmarDescontosEmMassaView.as_view(), name='confirmar-descontos'),
    path('comissionamento/historico-auto/', HistoricoDescontosAutoView.as_view(), name='historico-auto'),
    path('comissionamento/reverter-auto/', ReverterDescontoMassaView.as_view(), name='reverter-auto'),
    path('comissionamento/adiantamentos-esteira/', AdiantamentosEsteiraView.as_view(), name='adiantamentos-esteira'),

    # --- Importações ---
    path('import/osab/', ImportacaoOsabView.as_view(), name='importacao-osab'),
    path('import/osab/<int:pk>/', ImportacaoOsabDetailView.as_view(), name='importacao-osab-detail'),
    path('controle-tts/', ControleTTsAPIView.as_view(), name='controle-tts-api'),
    path('controle-tts/proximo/', ControleTTsProximoAPIView.as_view(), name='controle-tts-proximo-api'),
    path('controle-tts/tratado/', ControleTTTratadoAPIView.as_view(), name='controle-tts-tratado-api'),
    path('import/osab/analise/', AnaliseComparacaoOSABView.as_view(), name='analise-osab'),
    path('import/churn/', ImportacaoChurnView.as_view(), name='importacao-churn'),
    path('import/churn/<int:pk>/', ImportacaoChurnDetailView.as_view(), name='importacao-churn-detail'),
    path('import/ciclo-pagamento/', ImportacaoCicloPagamentoView.as_view(), name='importacao-ciclo-pagamento'),
    
    # --- Mapas e ZAP ---
    path('importar-kml/', ImportarKMLView.as_view(), name='importar-kml'),
    path('importar-dfv/', ImportarDFVView.as_view(), name='importar-dfv'),
    path('importar-cnpj/', ImportarCNPJView.as_view(), name='importar-cnpj'),
    path('importar-gdp/', ImportarGdpPrecoView.as_view(), name='importar-gdp'),
    path('logs-importacao-gdp/', LogsImportacaoGdpPrecoView.as_view(), name='logs-importacao-gdp'),
    path('preco-plano-gdp/', PrecoPlanoGdpLookupView.as_view(), name='preco-plano-gdp'),
    path('logs-importacao-cnpj/', LogsImportacaoCNPJView.as_view(), name='logs-importacao-cnpj'),
    # Webhook WhatsApp - URL para configurar no Z-API / Evolution / WhatsAtende:
    # Produção Z-API: https://www.recordpap.com.br/api/crm/webhook-whatsapp/
    # WhatsAtende:    https://www.recordpap.com.br/api/crm/webhook-whatsapp/<WHATSATENDE_WEBHOOK_TOKEN>/
    path('webhook-whatsapp/', WebhookWhatsAppView.as_view(), name='webhook-whatsapp'),
    path(
        'webhook-whatsapp/<str:webhook_token>/',
        WebhookWhatsAppView.as_view(),
        name='webhook-whatsapp-token',
    ),
    
    # Validação WhatsApp (Duas rotas para compatibilidade)
    path('verificar-zap/<str:telefone>/', api_verificar_whatsapp, name='verificar-zap-path'), # Rota antiga
    path('whatsapp/verificar/', api_verificar_whatsapp, name='verificar-zap-query'),          # Rota nova do CDOI
    
    # Validação E-mail
    path('verificar-email/<str:email>/', api_verificar_email, name='verificar-email'),
    
    # --- Performance ---
    path('relatorios/performance-vendas/', PerformanceVendasView.as_view(), name='performance-vendas'),
    path('performance-painel/', PainelPerformanceView.as_view(), name='api-performance-painel'),
    
    # --- Estatísticas Bot WhatsApp ---
    path('estatisticas-bot/', EstatisticasBotWhatsAppView.as_view(), name='estatisticas-bot'),
    path('performance-painel/exportar/', ExportarPerformanceExcelView.as_view(), name='exportar-performance-excel'),
    path('performance-painel/enviar-whatsapp/', EnviarImagemPerformanceView.as_view(), name='enviar-performance-zap'),
    
    # --- Exportação e Lembrete Agendamentos (Esteira) ---
    path('esteira/exportar-agendamentos/', ExportarAgendamentosDiaView.as_view(), name='exportar-agendamentos-dia'),
    path('esteira/exportar-agendados-pendentes/', ExportarAgendadosPendentesEsteiraView.as_view(), name='exportar-agendados-pendentes-esteira'),
    path('esteira/enviar-lembrete-instalacao/', EnviarLembreteInstalacaoView.as_view(), name='enviar-lembrete-instalacao'),
    path('esteira/posso-antecipar/<int:venda_id>/', EnviarPossoAnteciparVendedorView.as_view(), name='esteira-posso-antecipar'),
    path('esteira/posso-reagendar/<int:venda_id>/', EnviarPossoReagendarConsultorView.as_view(), name='esteira-posso-reagendar'),
    path('esteira/sync-status-pap/iniciar/', SyncStatusEsteiraIniciarView.as_view(), name='esteira-sync-status-pap-iniciar'),
    path('esteira/sync-status-pap/cancelar/', SyncStatusEsteiraCancelarView.as_view(), name='esteira-sync-status-pap-cancelar'),
    path('esteira/sync-status-pap/status/', SyncStatusEsteiraStatusView.as_view(), name='esteira-sync-status-pap-status'),
    path('esteira/consulta-status-pap/iniciar/', ConsultaStatusEsteiraIniciarView.as_view(), name='esteira-consulta-status-pap-iniciar'),
    path('esteira/consulta-status-pap/cancelar/', ConsultaStatusEsteiraCancelarView.as_view(), name='esteira-consulta-status-pap-cancelar'),
    path('esteira/consulta-status-pap/status/', ConsultaStatusEsteiraStatusView.as_view(), name='esteira-consulta-status-pap-status'),
    path('esteira/nio-reagendamento/iniciar/', NioReagendamentoIniciarView.as_view(), name='esteira-nio-reagendamento-iniciar'),
    path('esteira/nio-reagendamento/cancelar/', NioReagendamentoCancelarView.as_view(), name='esteira-nio-reagendamento-cancelar'),
    path('esteira/nio-reagendamento/status/', NioReagendamentoStatusView.as_view(), name='esteira-nio-reagendamento-status'),
    path('esteira/nio-reagendamento/<int:venda_id>/', NioReagendamentoUnitarioView.as_view(), name='esteira-nio-reagendamento-unitario'),
    path('esteira/gestao-aproveitamento/', GestaoAproveitamentoEsteiraView.as_view(), name='esteira-gestao-aproveitamento'),
    path('esteira/churn-tratamento/', EsteiraChurnTratamentoView.as_view(), name='esteira-churn-tratamento'),
    path('integracao/listar-grupos/', listar_grupos_whatsapp_api, name='listar-grupos-zapi'),
    
    # --- Debug Screenshots (Nio Negocia) ---
    path('debug/screenshots/', listar_screenshots_debug, name='listar-screenshots-debug'),
    path('debug/screenshots/<str:nome_arquivo>/', baixar_screenshot_debug, name='baixar-screenshot-debug'),
    path('verificar-permissao-gestao/', VerificarPermissaoGestaoView.as_view(), name='verificar-permissao-gestao'),
    path('import/legado/', ImportacaoLegadoView.as_view(), name='importacao-legado'),
    path('import/agendamento/', ImportacaoAgendamentoView.as_view(), name='importacao-agendamento'),
    path('import/recompra/', ImportacaoRecompraView.as_view(), name='importacao-recompra'),
    
    # --- Logs de Importações ---
    path('logs-legado/', LogsImportacaoLegadoView.as_view(), name='logs-legado'),
    path('logs-agendamento/', LogsImportacaoAgendamentoView.as_view(), name='logs-agendamento'),
    path('logs-agendamento/<int:log_id>/cancelar/', CancelarImportacaoAgendamentoView.as_view(), name='logs-agendamento-cancelar'),
    path('logs-fpd/', LogsImportacaoFPDView.as_view(), name='logs-fpd'),
    path('logs-osab/', LogsImportacaoOSABView.as_view(), name='logs-osab'),
    path('logs-osab/<int:log_id>/relatorio/', DownloadRelatorioOSABView.as_view(), name='logs-osab-relatorio'),
    path('logs-osab/<int:log_id>/cancelar/', CancelarImportacaoOSABView.as_view(), name='logs-osab-cancelar'),
    path('logs-osab/<int:log_id>/reverter/', ReverterImportacaoOSABView.as_view(), name='logs-osab-reverter'),
    path('import/osab/limpar/', LimparImportacaoOSABView.as_view(), name='limpar-osab'),
    path('import/dfv/limpar/', LimparBaseDFVView.as_view(), name='limpar-dfv'),
    path('import/cnpj/limpar/', LimparBaseCNPJView.as_view(), name='limpar-cnpj'),
    path('logs-dfv/', LogsImportacaoDFVView.as_view(), name='logs-dfv'),
    path('logs-recompra/', LogsImportacaoRecompraView.as_view(), name='logs-recompra'),
    
    # --- RECORD APOIA (Repositório de Arquivos) ---
    path('record-apoia/upload/', RecordApoiaUploadView.as_view(), name='record-apoia-upload'),
    path('record-apoia/list/', RecordApoiaListView.as_view(), name='record-apoia-list'),
    path('record-apoia/download/<int:arquivo_id>/', RecordApoiaDownloadView.as_view(), name='record-apoia-download'),
    path('record-apoia/edit/<int:arquivo_id>/', RecordApoiaEditView.as_view(), name='record-apoia-edit'),
    path('record-apoia/toggle-active/<int:arquivo_id>/', RecordApoiaToggleActiveView.as_view(), name='record-apoia-toggle-active'),
    path('record-apoia/delete/<int:arquivo_id>/', RecordApoiaDeleteView.as_view(), name='record-apoia-delete'),
    path('record-apoia/diagnostico/', RecordApoiaDiagnosticoView.as_view(), name='record-apoia-diagnostico'),
    path('record-apoia/buscar/', RecordApoiaBuscarView.as_view(), name='record-apoia-buscar'),
    path('record-apoia/admin/orfaos/', RecordApoiaAdminOrfaosView.as_view(), name='record-apoia-admin-orfaos'),
    path('record-apoia/admin/limpar-orfaos/', RecordApoiaAdminLimparOrfaosView.as_view(), name='record-apoia-admin-limpar-orfaos'),
    
    # --- Conhecimento IA (upload PDF/Excel/PPT para alimentar o bot) ---
    path('conhecimento-ia/list/', conhecimento_ia_api.ConhecimentoIAListView.as_view(), name='conhecimento-ia-list'),
    path('conhecimento-ia/upload/', conhecimento_ia_api.ConhecimentoIAUploadView.as_view(), name='conhecimento-ia-upload'),
    path('conhecimento-ia/delete/<int:doc_id>/', conhecimento_ia_api.ConhecimentoIADeleteView.as_view(), name='conhecimento-ia-delete'),
    path('conhecimento-ia/toggle-ativo/<int:doc_id>/', conhecimento_ia_api.ConhecimentoIAToggleAtivoView.as_view(), name='conhecimento-ia-toggle'),
    path('conhecimento-ia/reprocessar/<int:doc_id>/', conhecimento_ia_api.ConhecimentoIAReprocessarView.as_view(), name='conhecimento-ia-reprocessar'),
    path('conhecimento-ia/urls/', conhecimento_ia_api.ConhecimentoIAUrlListView.as_view(), name='conhecimento-ia-urls-list'),
    path('conhecimento-ia/urls/add/', conhecimento_ia_api.ConhecimentoIAUrlAddView.as_view(), name='conhecimento-ia-urls-add'),
    path('conhecimento-ia/urls/delete/<int:url_id>/', conhecimento_ia_api.ConhecimentoIAUrlDeleteView.as_view(), name='conhecimento-ia-urls-delete'),
    path('conhecimento-ia/urls/toggle-ativo/<int:url_id>/', conhecimento_ia_api.ConhecimentoIAUrlToggleAtivoView.as_view(), name='conhecimento-ia-urls-toggle'),
    path('conhecimento-ia/urls/reprocessar/<int:url_id>/', conhecimento_ia_api.ConhecimentoIAUrlReprocessarView.as_view(), name='conhecimento-ia-urls-reprocessar'),
    
    # --- ROTAS EXTRAS ---
    path('grupos-disparo-api/', listar_grupos_whatsapp_api, name='listar_grupos_api'),
    path('automacao-performance/', ConfigurarAutomacaoView.as_view(), name='automacao_performance'),
    path('enviar-imagem-performance/', EnviarImagemPerformanceView.as_view(), name='enviar_imagem_performance'),
    
    # --- CDOI (Record Vertical) ---
    path('cdoi/novo/', CdoiCreateView.as_view(), name='api-cdoi-novo'),
    path('cdoi/listar/', CdoiListView.as_view(), name='api-cdoi-listar'),
    path('cdoi/dashboard/', CdoiDashboardView.as_view(), name='api-cdoi-dashboard'),
    path('cdoi/cnpj-estabelecimentos/', CnpjEstabelecimentosCdoiView.as_view(), name='api-cdoi-cnpj-estabelecimentos'),
    path('cdoi/cnpj-municipios/', CnpjMunicipiosCdoiView.as_view(), name='api-cdoi-cnpj-municipios'),
    path('cdoi/cnpj-cnaes/', CnpjCnaesCdoiView.as_view(), name='api-cdoi-cnpj-cnaes'),
    path('cdoi/cnpj-bairros/', CnpjBairrosCdoiView.as_view(), name='api-cdoi-cnpj-bairros'),
    path('cdoi/cnpj-ufs/', CnpjUfsCdoiView.as_view(), name='api-cdoi-cnpj-ufs'),
    path('cdoi/editar/<int:pk>/', CdoiUpdateView.as_view(), name='api-cdoi-editar'),
    path('cdoi/viacep/<str:cep>/', ViaCepProxyView.as_view(), name='api-cdoi-viacep'),
    path('cdoi/nominatim/', NominatimProxyView.as_view(), name='api-cdoi-nominatim'),
    # SmartRiser / V.top — automação a partir do Gestão CDOI
    path('cdoi/<int:pk>/vtop/iniciar/', vtop_api.CdoiVtopIniciarView.as_view(), name='api-cdoi-vtop-iniciar'),
    path('cdoi/<int:pk>/vtop/senha-pronta/', vtop_api.CdoiVtopSenhaProntaView.as_view(), name='api-cdoi-vtop-senha-pronta'),
    path('cdoi/<int:pk>/vtop/status/', vtop_api.CdoiVtopStatusView.as_view(), name='api-cdoi-vtop-status'),
    path('cdoi/<int:pk>/vtop/fechar/', vtop_api.CdoiVtopFecharView.as_view(), name='api-cdoi-vtop-fechar'),
    path('cdoi/<int:pk>/vtop/payload/', vtop_api.CdoiVtopPayloadPreviewView.as_view(), name='api-cdoi-vtop-payload'),
    path('cdoi/vtop/status/', vtop_api.CdoiVtopStatusView.as_view(), name='api-cdoi-vtop-status-global'),
    path('cdoi/vtop/fechar/', vtop_api.CdoiVtopFecharView.as_view(), name='api-cdoi-vtop-fechar-global'),
    path('cdoi/vtop/invalidar-sessao/', vtop_api.CdoiVtopInvalidarSessaoView.as_view(), name='api-cdoi-vtop-invalidar'),
    # Proxy ViaCEP genérico (auditoria, crm_vendas, etc.) — evita CORS ao chamar do frontend
    path('viacep/<str:cep>/', ViaCepProxyView.as_view(), name='api-viacep'),

    # --- PRÉ-VENDAS PÚBLICAS ---
    path('prevenda/gerar-link/<int:cdoi_id>/', GerarLinkPublicoPreVendaView.as_view(), name='api-prevenda-gerar-link'),
    path('prevenda/publica/<str:codigo>/', PreVendaPublicaFormView.as_view(), name='api-prevenda-publica-form'),
    path('prevenda/por-cdoi/<int:cdoi_id>/', PreVendasPorAcionamentoView.as_view(), name='api-prevenda-por-cdoi'),

    # --- Integração Nio (dívidas/PIX/barras) ---
    path('nio/dividas/', NioDividasView.as_view(), name='nio-dividas'),

    # --- Antecipar Instalação (solicitação ao GC Nio) ---
    path('antecipar-instalacao/buscar/', BuscarAnteciparInstalacaoView.as_view(), name='antecipar-instalacao-buscar'),
    path('antecipar-instalacao/solicitar/', SolicitarAnteciparInstalacaoView.as_view(), name='antecipar-instalacao-solicitar'),
    path('antecipar-instalacao/config/', ConfigAnteciparInstalacaoView.as_view(), name='antecipar-instalacao-config'),
    path('antecipar-instalacao/historico/', HistoricoAnteciparInstalacaoView.as_view(), name='antecipar-instalacao-historico'),
    path('antecipar-instalacao/historico/exportar/', ExportarHistoricoAnteciparInstalacaoView.as_view(), name='antecipar-instalacao-historico-exportar'),
    path('antecipar-instalacao/solicitacao/<int:pk>/resposta/', RespostaGCAnteciparInstalacaoView.as_view(), name='antecipar-instalacao-resposta-gc'),

    # --- Auditoria: sem slot na agenda (comunicação GC) ---
    path('auditoria/sem-slot/enviar/', AuditoriaSemSlotEnviarView.as_view(), name='auditoria-sem-slot-enviar'),
    path('auditoria/sem-slot/relatorio/', AuditoriaSemSlotRelatorioView.as_view(), name='auditoria-sem-slot-relatorio'),

    # --- Auditoria: Inclusão/Viabilidade (Forms via extensão Chrome) ---
    path(
        'auditoria/inclusao-viabilidade/',
        DemandaInclusaoListView.as_view(),
        name='auditoria-inclusao-list',
    ),
    path(
        'auditoria/inclusao-viabilidade/<int:pk>/',
        DemandaInclusaoDetailView.as_view(),
        name='auditoria-inclusao-detail',
    ),
    path(
        'auditoria/inclusao-viabilidade/<int:pk>/iniciar/',
        DemandaInclusaoIniciarView.as_view(),
        name='auditoria-inclusao-iniciar',
    ),
    path(
        'auditoria/inclusao-viabilidade/<int:pk>/concluir/',
        DemandaInclusaoConcluirView.as_view(),
        name='auditoria-inclusao-concluir',
    ),
    path(
        'auditoria/inclusao-viabilidade/<int:pk>/erro/',
        DemandaInclusaoErroView.as_view(),
        name='auditoria-inclusao-erro',
    ),

    # --- Tempo de tratamento (auditoria e esteira) ---
    path('tratamento/iniciar/', iniciar_sessao_view, name='tratamento-iniciar'),
    path('tratamento/ping/', ping_sessao_view, name='tratamento-ping'),
    path('tratamento/encerrar/', encerrar_sessao_view, name='tratamento-encerrar'),
    path('tratamento/relatorio/', relatorio_tratamento_view, name='tratamento-relatorio'),
    path('tratamento/enviar-relatorio/', enviar_relatorio_tratamento_view, name='tratamento-enviar-relatorio'),

    # --- Esteira: config e pendência indevida ---
    path('esteira/config/', ConfigEsteiraVendasView.as_view(), name='esteira-vendas-config'),
    path(
        'esteira/relatorio-pendencia-cliente/enviar/',
        EnviarRelatorioPendenciaClienteView.as_view(),
        name='esteira-relatorio-pendencia-cliente-enviar',
    ),
    path('pendencia-indevida/registrar/', PendenciaIndevidaRegistrarView.as_view(), name='pendencia-indevida-registrar'),
    path('pendencia-indevida/relatorio/', PendenciaIndevidaRelatorioView.as_view(), name='pendencia-indevida-relatorio'),

    # --- Auditoria de ligações (Sonax click2call / Zenvia Voice) ---
    path('auditoria/ligacoes/opcoes/', AuditoriaLigacaoOpcoesView.as_view(), name='auditoria-ligacao-opcoes'),
    path('auditoria/ligacoes/historico/', AuditoriaLigacaoHistoricoView.as_view(), name='auditoria-ligacao-historico'),
    path('auditoria/ligacoes/<int:venda_id>/iniciar/', AuditoriaLigacaoStartView.as_view(), name='auditoria-ligacao-iniciar'),
    path('auditoria/ligacoes/<int:venda_id>/', AuditoriaLigacaoListView.as_view(), name='auditoria-ligacao-listar'),
    path('auditoria/ligacoes/<int:ligacao_id>/sincronizar/', AuditoriaLigacaoSincronizarView.as_view(), name='auditoria-ligacao-sincronizar'),
    path('auditoria/ligacoes/sincronizar-lote/', AuditoriaLigacaoSincronizarLoteView.as_view(), name='auditoria-ligacao-sincronizar-lote'),
    path('auditoria/ligacoes/webhook/', AuditoriaLigacaoWebhookView.as_view(), name='auditoria-ligacao-webhook'),
    
    # --- Análise de Buscas de Faturas ---
    path('analise-buscas/', views_analise_busca.AnaliseBuscasView.as_view(), name='analise-buscas'),
    path('analise-buscas/metricas-tempo-real/', views_analise_busca.MetricasTempoRealView.as_view(), name='metricas-tempo-real'),
]