from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from gestao_equipes.views_health import HealthView, MetricsView, ReadyView

# --- IMPORTS DAS VIEWS NECESSÁRIAS ---
from usuarios.views import LoginView
from core.views import calendario_fiscal_view, RegraAutomacaoViewSet, PainelSegundaView
from crm_app.views_whatsapp_admin import (
    whatsapp_config_api,
    whatsapp_disconnect_api,
    whatsapp_qrcode_api,
    whatsapp_status_api,
)
from crm_app.views import (
    page_painel_performance, 
    page_cdoi_novo,
    prevenda_publica_landing,
    page_bonus_m10,
    page_qualidade,
    page_boas_vindas,
    page_validacao_fpd,
    page_validacao_churn,
    page_validacao_osab,
    page_validacao_agendamento,
    page_validacao_legado,
    page_validacao_dfv,
    page_validacao_recompra,
    page_record_apoia,
    page_conhecimento_ia,
    listar_grupos_whatsapp_api,
    SafraM10ListView,
    DashboardM10View,
    DashboardFPDView,
    ContratoM10DetailView,
    VendedoresM10View,
    PopularSafraM10View,
    ImportarFPDView,
    LogsImportacaoFPDView,
    LogsImportacaoOSABView,
    ImportarChurnView,
    AtualizarFaturasView,
    ExportarM10View,
    DadosFPDView,
    ListarImportacoesFPDView,
    BuscarOSFPDView,
    BuscarOSChurnView,
    ListarLogsImportacaoFPDView,
    ListarLogsImportacaoChurnView,
    FaturaM10ListView,
    FaturaM10DetailView,
    BuscarFaturaNioView,
    BuscarFaturasSafraView,
)
from crm_app.qualidade_api import (
    QualidadePeriodosView,
    QualidadeDashboardView,
    QualidadeSincronizarFaltantesView,
    QualidadeOrfaosView,
    QualidadeFaltamNoCrmView,
    QualidadeDashboardFpdNioView,
    QualidadeAtualizarContatoView,
    QualidadeHistoricoContatoView,
    QualidadeRegistrarLigacaoView,
    QualidadeEnviarCobrancaView,
    QualidadeContratoFaturasView,
    QualidadeFaturaPdfView,
    QualidadeFaturaUploadPdfView,
    QualidadeFaturaLimparConferenciaView,
    QualidadeBuscarNioOpcoesView,
    QualidadeAplicarNioOpcaoView,
    QualidadeStatusTratamentoView,
    QualidadeAtualizarStatusTratamentoView,
    QualidadeBuscaNioStatusView,
    QualidadeMatchNioUltimoView,
    QualidadeCobrancaPreviewView,
    QualidadeGestaoEnviosView,
    QualidadeEnviarAtrasadosView,
)

# --- CONFIGURAÇÃO DO ROUTER PARA REGRAS DE AUTOMAÇÃO ---
# Isso garante que a rota /api/regras-automacao/ exista na raiz da API
router = DefaultRouter()
router.register(r'regras-automacao', RegraAutomacaoViewSet, basename='regras-automacao')

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('ready/', ReadyView.as_view(), name='ready'),
    path('metrics/', MetricsView.as_view(), name='metrics'),
    path('admin/', admin.site.urls),

    # API AUTH
    path('api/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('login/', LoginView.as_view(), name='login_direct'),

    # --- ROTAS DE CORREÇÃO (PARA O FRONTEND FUNCIONAR) ---
    # 1. Registra as rotas do router (inclui /api/regras-automacao/)
    path('api/', include(router.urls)),
    
    # 2. Rotas WhatsApp (grupos + conexão Evolution admin)
    path('api/whatsapp/groups/', listar_grupos_whatsapp_api, name='whatsapp-groups-direct'),
    path('api/whatsapp/config/', whatsapp_config_api, name='whatsapp-config'),
    path('api/whatsapp/status/', whatsapp_status_api, name='whatsapp-status'),
    path('api/whatsapp/qrcode/', whatsapp_qrcode_api, name='whatsapp-qrcode'),
    path('api/whatsapp/disconnect/', whatsapp_disconnect_api, name='whatsapp-disconnect'),

    # APIS DO SISTEMA (Back-end)
    path('api/', include('djoser.urls')),
    path('api/', include('usuarios.urls')), 
    path('api/presenca/', include('presenca.urls')),
    path('api/crm/', include('crm_app.urls')),
    path('api/osab/', include('osab.urls')),
    path('api/relatorios/', include('relatorios.urls')),
    path('api/core/', include('core.urls')), 

    # PÁGINAS FRONTEND (HTML para o usuário)
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('design-preview/', TemplateView.as_view(template_name='preview_design.html'), name='design-preview'),
    path('area-interna/', TemplateView.as_view(template_name='area-interna.html'), name='area-interna'),
    path('controle-tts/', TemplateView.as_view(template_name='controle_tts.html'), name='controle-tts'),
    path('record-informa/', TemplateView.as_view(template_name='record_informa.html'), name='record-informa'),
    path('auditoria/', TemplateView.as_view(template_name='auditoria.html'), name='auditoria'),
    path('crm-vendas/', TemplateView.as_view(template_name='crm_vendas.html'), name='crm_vendas'),
    path('gestao-acessos/', TemplateView.as_view(template_name='gestao-acessos.html'), name='gestao-acessos'),
    path('governanca/', TemplateView.as_view(template_name='governanca.html'), name='governanca'),
    path('whatsapp-config/', TemplateView.as_view(template_name='whatsapp-config.html'), name='whatsapp-config'),
    path('funil-vendas/', TemplateView.as_view(template_name='funil-vendas.html'), name='funil-vendas'),
    path('presenca/', TemplateView.as_view(template_name='presenca.html'), name='presenca'),
    path('esteira/', TemplateView.as_view(template_name='esteira.html'), name='esteira'),
    path('comissionamento/', TemplateView.as_view(template_name='comissionamento.html'), name='comissionamento'),

    # Central de Importações
    path('importacoes/', TemplateView.as_view(template_name='importacoes.html'), name='central-importacoes'),

    # Telas de Importação Específicas
    path('importar-osab/', TemplateView.as_view(template_name='importar_osab.html'), name='importar-osab'),
    path('importar-churn/', TemplateView.as_view(template_name='importar_churn.html'), name='importar-churn'),
    path('importar-ciclo-pagamento/', TemplateView.as_view(template_name='importar_ciclo_pagamento.html'), name='importar-ciclo-pagamento'),
    path('importar-mapa/', TemplateView.as_view(template_name='importar_mapa.html'), name='importar-mapa'),
    path('importar-dfv/', TemplateView.as_view(template_name='importar_dfv.html'), name='page-importar-dfv'),
    path('importar-legado/', TemplateView.as_view(template_name='importar_legado.html'), name='importar-legado'),
    path('importar-agendamento/', TemplateView.as_view(template_name='importar_agendamento.html'), name='importar-agendamento'),
    path('importar-recompra/', TemplateView.as_view(template_name='importar_recompra.html'), name='importar-recompra'),
    path('importar-cnpj/', TemplateView.as_view(template_name='importar_cnpj.html'), name='importar-cnpj'),
    path('importar-gdp/', TemplateView.as_view(template_name='importar_gdp.html'), name='importar-gdp'),

    # CALENDÁRIO & PAINEL DE PERFORMANCE
    path('calendario/', calendario_fiscal_view, name='calendario_fiscal_atual'),
    path('calendario/<int:ano>/<int:mes>/', calendario_fiscal_view, name='calendario_fiscal'),
    path('painel-performance/', page_painel_performance, name='painel_performance'),
    path('painel-segunda/', PainelSegundaView.as_view(), name='painel_segunda'),

    # --- NOVO: RECORD VERTICAL (CDOI) ---
    path('cdoi-novo/', page_cdoi_novo, name='page_cdoi_novo'),
    path('prevenda-publica/<str:codigo>/', prevenda_publica_landing, name='prevenda-publica'),

    # --- NOVO: BÔNUS M-10 & FPD ---
    path('bonus-m10/', page_bonus_m10, name='page_bonus_m10'),
    path('boas-vindas/', page_boas_vindas, name='page_boas_vindas'),
    path('importar-fpd/', TemplateView.as_view(template_name='importar_fpd.html'), name='importar_fpd'),
    path('validacao-fpd/', page_validacao_fpd, name='page_validacao_fpd'),
    path('validacao-churn/', page_validacao_churn, name='page_validacao_churn'),
    path('validacao-osab/', page_validacao_osab, name='page_validacao_osab'),
    path('validacao-agendamento/', page_validacao_agendamento, name='page_validacao_agendamento'),
    path('validacao-legado/', page_validacao_legado, name='page_validacao_legado'),
    path('validacao-dfv/', page_validacao_dfv, name='page_validacao_dfv'),
    path('validacao-recompra/', page_validacao_recompra, name='page_validacao_recompra'),
    path('record-apoia/', page_record_apoia, name='page_record_apoia'),
    path('conhecimento-ia/', page_conhecimento_ia, name='page_conhecimento_ia'),

    # Antecipar Instalação (solicitação ao GC Nio)
    path('antecipar-instalacao/', TemplateView.as_view(template_name='antecipar-instalacao.html'), name='page_antecipar_instalacao'),
    
    # API Bônus M-10
    path('api/bonus-m10/safras/', SafraM10ListView.as_view(), name='api-bonus-m10-safras'),
    path('api/bonus-m10/safras/criar/', PopularSafraM10View.as_view(), name='api-bonus-m10-safras-criar'),
    path('api/bonus-m10/dashboard-m10/', DashboardM10View.as_view(), name='api-bonus-m10-dashboard'),
    path('api/bonus-m10/vendedores/', VendedoresM10View.as_view(), name='api-bonus-m10-vendedores'),
    path('api/bonus-m10/dashboard-fpd/', DashboardFPDView.as_view(), name='api-bonus-m10-dashboard-fpd'),
    path('api/bonus-m10/contratos/<int:pk>/', ContratoM10DetailView.as_view(), name='api-bonus-m10-contrato-detail'),
    path('api/bonus-m10/importar-fpd/', ImportarFPDView.as_view(), name='api-bonus-m10-importar-fpd'),
    path('api/bonus-m10/logs-fpd/', LogsImportacaoFPDView.as_view(), name='api-bonus-m10-logs-fpd'),
    path('api/bonus-m10/logs-osab/', LogsImportacaoOSABView.as_view(), name='api-bonus-m10-logs-osab'),
    path('api/bonus-m10/importar-churn/', ImportarChurnView.as_view(), name='api-bonus-m10-importar-churn'),
    path('api/bonus-m10/faturas/atualizar/', AtualizarFaturasView.as_view(), name='api-bonus-m10-atualizar-faturas'),
    path('api/bonus-m10/exportar/', ExportarM10View.as_view(), name='api-bonus-m10-exportar'),
    path('api/bonus-m10/dados-fpd/', DadosFPDView.as_view(), name='api-bonus-m10-dados-fpd'),
    path('api/bonus-m10/importacoes-fpd/', ListarImportacoesFPDView.as_view(), name='api-bonus-m10-importacoes-fpd'),
    path('api/bonus-m10/buscar-os-fpd/', BuscarOSFPDView.as_view(), name='api-bonus-m10-buscar-os-fpd'),
    path('api/bonus-m10/buscar-os-churn/', BuscarOSChurnView.as_view(), name='api-bonus-m10-buscar-os-churn'),
    path('api/bonus-m10/logs-importacao-fpd/', ListarLogsImportacaoFPDView.as_view(), name='api-bonus-m10-logs-importacao-fpd'),
    path('api/bonus-m10/logs-importacao-churn/', ListarLogsImportacaoChurnView.as_view(), name='api-bonus-m10-logs-importacao-churn'),
    
    # API Faturas M-10 (Novos endpoints)
    path('api/bonus-m10/faturas/', FaturaM10ListView.as_view(), name='api-faturas-m10-list'),
    path('api/bonus-m10/faturas/<int:pk>/', FaturaM10DetailView.as_view(), name='api-faturas-m10-detail'),
    path('api/bonus-m10/buscar-fatura-nio/', BuscarFaturaNioView.as_view(), name='api-buscar-fatura-nio'),
    path('api/bonus-m10/buscar-faturas-safra/', BuscarFaturasSafraView.as_view(), name='api-buscar-faturas-safra'),

    # Módulo Qualidade (UI unificada FPD + bônus)
    path('qualidade/', page_qualidade, name='page_qualidade'),
    path('api/qualidade/periodos/', QualidadePeriodosView.as_view(), name='api-qualidade-periodos'),
    path('api/qualidade/dashboard/', QualidadeDashboardView.as_view(), name='api-qualidade-dashboard'),
    path('api/qualidade/sincronizar-faltantes/', QualidadeSincronizarFaltantesView.as_view(), name='api-qualidade-sync'),
    path('api/qualidade/orfaos/', QualidadeOrfaosView.as_view(), name='api-qualidade-orfaos'),
    path('api/qualidade/faltam-no-crm/', QualidadeFaltamNoCrmView.as_view(), name='api-qualidade-faltam-crm'),
    path('api/qualidade/dashboard-fpd-nio/', QualidadeDashboardFpdNioView.as_view(), name='api-qualidade-dashboard-fpd-nio'),
    path('api/qualidade/contratos/<int:pk>/contato/', QualidadeAtualizarContatoView.as_view(), name='api-qualidade-contato'),
    path('api/qualidade/contratos/<int:pk>/historico-contato/', QualidadeHistoricoContatoView.as_view(), name='api-qualidade-historico-contato'),
    path('api/qualidade/contratos/<int:pk>/registrar-ligacao/', QualidadeRegistrarLigacaoView.as_view(), name='api-qualidade-registrar-ligacao'),
    path('api/qualidade/contratos/<int:pk>/enviar/', QualidadeEnviarCobrancaView.as_view(), name='api-qualidade-enviar'),
    path('api/qualidade/contratos/<int:pk>/faturas/', QualidadeContratoFaturasView.as_view(), name='api-qualidade-faturas'),
    path('api/qualidade/faturas/<int:pk>/pdf/', QualidadeFaturaPdfView.as_view(), name='api-qualidade-fatura-pdf'),
    path('api/qualidade/faturas/<int:pk>/upload-pdf/', QualidadeFaturaUploadPdfView.as_view(), name='api-qualidade-fatura-upload-pdf'),
    path('api/qualidade/faturas/<int:pk>/limpar-conferencia-fpd/', QualidadeFaturaLimparConferenciaView.as_view(), name='api-qualidade-fatura-limpar-conf'),
    path('api/qualidade/contratos/<int:pk>/buscar-nio/', QualidadeBuscarNioOpcoesView.as_view(), name='api-qualidade-buscar-nio'),
    path('api/qualidade/contratos/<int:pk>/aplicar-nio/', QualidadeAplicarNioOpcaoView.as_view(), name='api-qualidade-aplicar-nio'),
    path('api/qualidade/status-tratamento/', QualidadeStatusTratamentoView.as_view(), name='api-qualidade-status-tratamento'),
    path('api/qualidade/contratos/<int:pk>/status-tratamento/', QualidadeAtualizarStatusTratamentoView.as_view(), name='api-qualidade-atualizar-status-tratamento'),
    path('api/qualidade/busca-nio/<int:pk>/', QualidadeBuscaNioStatusView.as_view(), name='api-qualidade-busca-nio-status'),
    path('api/qualidade/match-nio/ultimo/', QualidadeMatchNioUltimoView.as_view(), name='api-qualidade-match-nio-ultimo'),
    path('api/qualidade/cobranca/preview/', QualidadeCobrancaPreviewView.as_view(), name='api-qualidade-cobranca-preview'),
    path('api/qualidade/cobranca/envios/', QualidadeGestaoEnviosView.as_view(), name='api-qualidade-cobranca-envios'),
    path('api/qualidade/cobranca/enviar-atrasados/', QualidadeEnviarAtrasadosView.as_view(), name='api-qualidade-enviar-atrasados'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)