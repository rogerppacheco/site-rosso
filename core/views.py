from datetime import date

from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import RegraAutomacao
from .serializers import RegraAutomacaoSerializer

# Autenticação para ignorar CSRF na API (Útil se usar Sessão com Ajax, mas o JWT é o principal aqui)
class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return 

# --- VIEWSET DA NOVA REGRA DE AUTOMAÇÃO ---
class IsAdminDiretoria(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'is_superuser', False):
            return True
        return user.groups.filter(name__in=['Admin', 'Diretoria']).exists()


class RegraAutomacaoViewSet(viewsets.ModelViewSet):
    queryset = RegraAutomacao.objects.all().order_by("-id")
    serializer_class = RegraAutomacaoSerializer
    # --- CORREÇÃO: Adicionado JWTAuthentication para aceitar o Token do Frontend ---
    authentication_classes = (CsrfExemptSessionAuthentication, BasicAuthentication, JWTAuthentication)
    permission_classes = [IsAuthenticated, IsAdminDiretoria]

# --- SUAS VIEWS DE TEMPLATE ---
class IndexView(TemplateView):
    template_name = "frontend/public/index.html"

class AreaInternaView(TemplateView):
    template_name = "frontend/public/area-interna.html"


class AnteciparInstalacaoView(TemplateView):
    template_name = "antecipar-instalacao.html"

class GovernancaView(TemplateView):
    # Ajustado para o caminho correto se estiver usando a pasta public
    template_name = "public/governanca.html"


class PainelSegundaView(TemplateView):
    """Painel do Agente Financeiro (checklist toda segunda). HTML sempre servido; acesso Diretoria/Admin conferido no front via JWT (como área interna)."""
    template_name = "painel-segunda.html"

class PresencaView(TemplateView):
    template_name = "frontend/public/presenca.html"

class CrmVendasView(TemplateView):
    template_name = "frontend/public/crm_vendas.html"

class ConsultaCpfView(TemplateView):
    template_name = "frontend/public/index.html"

class ConsultaTratamentoView(TemplateView):
    template_name = "frontend/public/area-interna.html"

class AuditoriaView(TemplateView):
    template_name = "frontend/public/auditoria.html"

class SalvarOsabView(TemplateView):
    template_name = "frontend/public/salvar_osab.html"

class SalvarChurnView(TemplateView):
    template_name = "frontend/public/salvar_churn.html"

# --- VIEW DO CALENDÁRIO FISCAL ---
def calendario_fiscal_view(request, ano=None, mes=None):
    """
    Exibe o calendário fiscal do mês (GET) ou processa atualização em lote (POST).
    Delega toda a lógica ao CalendarioFiscalService e apenas monta a resposta.
    """
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month

    if request.method == "POST":
        from core.services.calendario_fiscal_service import atualizar_dias_fiscais_lote

        atualizar_dias_fiscais_lote(
            dias_ids=request.POST.getlist("dia_id"),
            pesos_venda=request.POST.getlist("peso_venda"),
            pesos_inst=request.POST.getlist("peso_instalacao"),
            obs_list=request.POST.getlist("observacao"),
        )
        redirect_url = f"/calendario/{ano}/{mes}/"
        if request.GET.get("modo") == "iframe":
            redirect_url += "?modo=iframe"
        return redirect(redirect_url)

    from core.services.calendario_fiscal_service import obter_contexto_calendario

    context = obter_contexto_calendario(
        ano=int(ano),
        mes=int(mes),
        modo_iframe=request.GET.get("modo") == "iframe",
    )
    return render(request, "core/calendario_fiscal.html", context)