from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    MotivoViewSet, PresencaViewSet, DiaNaoUtilViewSet,
    MinhaEquipeListView, TodosUsuariosListView,
    ConfirmacaoPresencaDiaView,
    RelatorioFinanceiroView, ExportarRelatorioFinanceiroExcelView
)

router = DefaultRouter()
router.register(r'motivos', MotivoViewSet, basename='motivo')
# CORREÇÃO: Mudado de 'presenca' para 'registros' para atender ao frontend que chama /api/presenca/registros/
router.register(r'registros', PresencaViewSet, basename='presenca') 
router.register(r'dias-nao-uteis', DiaNaoUtilViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('minha-equipe/', MinhaEquipeListView.as_view(), name='minha-equipe'),
    path('todos-usuarios/', TodosUsuariosListView.as_view(), name='todos-usuarios'),
    path('confirmacao-dia/', ConfirmacaoPresencaDiaView.as_view(), name='confirmacao-dia'),

    # Rotas financeiras
    path('relatorio-financeiro/', RelatorioFinanceiroView.as_view(), name='relatorio-financeiro'),
    path('relatorio-financeiro/excel/', ExportarRelatorioFinanceiroExcelView.as_view(), name='relatorio-financeiro-excel'),
]