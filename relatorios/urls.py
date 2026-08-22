# relatorios/urls.py

from django.urls import path
from .views import RelatorioPrevisaoView, RelatorioDescontosView, RelatorioFinalView

urlpatterns = [
    path('previsao/', RelatorioPrevisaoView.as_view(), name='relatorio_previsao'),
    path('descontos/', RelatorioDescontosView.as_view(), name='relatorio_descontos'),
    path('semanal/', RelatorioFinalView.as_view(), name='relatorio_final'),
]