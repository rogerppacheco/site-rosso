from datetime import datetime

from rest_framework import status, viewsets, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from presenca.models import MotivoAusencia, Presenca, DiaNaoUtil, ConfirmacaoPresencaDia
from presenca.serializers import (
    MotivoAusenciaSerializer,
    PresencaSerializer,
    DiaNaoUtilSerializer,
    ConfirmacaoPresencaDiaSerializer,
)
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer


# ---------------------------------------------------------------------------
# ViewSets enxutos (list/detail); create de Presenca delega ao serviço
# ---------------------------------------------------------------------------

class MotivoViewSet(viewsets.ModelViewSet):
    queryset = MotivoAusencia.objects.all().order_by("motivo")
    serializer_class = MotivoAusenciaSerializer
    permission_classes = [IsAuthenticated]


class PresencaViewSet(viewsets.ModelViewSet):
    serializer_class = PresencaSerializer
    permission_classes = [IsAuthenticated]
    resource_name = "presenca"
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        queryset = Presenca.objects.all()
        if self.action in ["destroy", "update", "partial_update", "retrieve"]:
            return queryset
        if user.is_superuser or user.groups.filter(
            name__in=["Diretoria", "Admin", "BackOffice"]
        ).exists():
            pass
        elif hasattr(user, "liderados") and user.liderados.exists():
            liderados_ids = list(user.liderados.values_list("id", flat=True))
            queryset = queryset.filter(colaborador_id__in=liderados_ids + [user.id])
        else:
            queryset = queryset.filter(colaborador=user)
        if self.action == "list":
            data_selecionada = self.request.query_params.get("data")
            if data_selecionada:
                queryset = queryset.filter(data=data_selecionada)
        return queryset

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            self.perform_destroy(instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Presenca.DoesNotExist:
            return Response(
                {"detail": "Registro não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        if "id" in data:
            del data["id"]
        colaborador_id = data.get("colaborador")
        data_registro = data.get("data")
        if not colaborador_id or not data_registro:
            return Response(
                {"detail": "Colaborador e data são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from presenca.services.presenca_service import (
                PresencaServiceError,
                registrar_presenca,
            )

            obj, created = registrar_presenca(
                colaborador_id=int(colaborador_id),
                data_registro=data_registro,
                status=data.get("status", True),
                motivo_id=data.get("motivo"),
                observacao=data.get("observacao", ""),
                usuario=request.user,
            )
            serializer = self.get_serializer(obj)
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )
        except PresencaServiceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(editado_por=request.user)
        return Response(serializer.data)


class DiaNaoUtilViewSet(viewsets.ModelViewSet):
    queryset = DiaNaoUtil.objects.all().order_by("-data")
    serializer_class = DiaNaoUtilSerializer
    permission_classes = [IsAuthenticated]


class MinhaEquipeListView(generics.ListAPIView):
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = getattr(self.request.user, "liderados", None)
        if qs is not None:
            liderados = qs.filter(is_active=True).order_by("first_name")
            if liderados.exists():
                return liderados
        if getattr(self.request.user, "vendedor_solo", False):
            return Usuario.objects.filter(id=self.request.user.id, is_active=True)
        return Usuario.objects.none()


class TodosUsuariosListView(generics.ListAPIView):
    from presenca.serializers import UsuarioPresencaSerializer

    serializer_class = UsuarioPresencaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return (
            Usuario.objects.filter(
                is_active=True, participa_controle_presenca=True
            )
            .select_related("perfil", "supervisor")
            .order_by("first_name")
        )


# ---------------------------------------------------------------------------
# Confirmação do dia com selfie (GET/POST/DELETE) — delega ao serviço
# ---------------------------------------------------------------------------

class ConfirmacaoPresencaDiaView(APIView):
    """
    GET: ?data=YYYY-MM-DD → confirmação do dia.
    POST: foto + data (WhatsApp Diretoria + confirmação no banco).
    DELETE: ?data=YYYY-MM-DD → exclui confirmação (Diretoria/Admin).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data_str = request.query_params.get("data")
        if not data_str:
            return Response(
                {"detail": "Parâmetro data (YYYY-MM-DD) é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data_dia = datetime.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Data inválida. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from presenca.services.confirmacao_presenca_service import obter_confirmacao_dia

        payload = obter_confirmacao_dia(data_dia, request.user)
        return Response(payload)

    def post(self, request):
        from presenca.services.confirmacao_presenca_service import (
            ConfirmacaoPresencaServiceError,
            usuario_pode_confirmar_presenca,
            registrar_selfie,
        )
        from presenca.serializers import ConfirmacaoPresencaDiaSerializer

        if not usuario_pode_confirmar_presenca(request.user):
            return Response(
                {"detail": "Sem permissão para confirmar presença do dia."},
                status=status.HTTP_403_FORBIDDEN,
            )
        foto = request.FILES.get("foto")
        data_str = request.data.get("data") or request.POST.get("data")
        if not foto or not data_str:
            return Response(
                {"detail": "Envie a foto (foto) e a data (data, YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data_dia = datetime.strptime(data_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Data inválida. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lat = request.data.get("latitude") or request.POST.get("latitude")
        lng = request.data.get("longitude") or request.POST.get("longitude")
        try:
            lat_f = float(lat) if lat not in (None, "") else None
        except (TypeError, ValueError):
            lat_f = None
        try:
            lng_f = float(lng) if lng not in (None, "") else None
        except (TypeError, ValueError):
            lng_f = None

        foto_bytes = foto.read()
        try:
            conf, created = registrar_selfie(
                usuario=request.user,
                data_dia=data_dia,
                foto_bytes=foto_bytes,
                latitude=lat_f,
                longitude=lng_f,
            )
        except ConfirmacaoPresencaServiceError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        serializer = ConfirmacaoPresencaDiaSerializer(conf)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        if not request.user.is_superuser and not request.user.groups.filter(
            name__in=["Diretoria", "Admin"]
        ).exists():
            return Response(
                {"detail": "Apenas Diretoria ou Admin podem excluir a foto."},
                status=status.HTTP_403_FORBIDDEN,
            )
        data_str = request.query_params.get("data")
        if not data_str:
            return Response(
                {"detail": "Parâmetro data (YYYY-MM-DD) é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data_dia = datetime.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Data inválida. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from presenca.services.confirmacao_presenca_service import excluir_confirmacao_dia

        excluir_confirmacao_dia(data_dia)
        return Response({"detail": "Foto excluída."}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Relatório financeiro (GET JSON e export Excel) — delega ao serviço
# ---------------------------------------------------------------------------

class RelatorioFinanceiroView(APIView):
    """GET ?inicio=YYYY-MM-DD&fim=YYYY-MM-DD → previsão e descontos por colaborador."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        inicio_str = request.query_params.get("inicio")
        fim_str = request.query_params.get("fim")
        if not inicio_str or not fim_str:
            return Response(
                {"error": "Datas obrigatórias."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dt_ini = datetime.strptime(inicio_str, "%Y-%m-%d").date()
            dt_fim = datetime.strptime(fim_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Data inválida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from presenca.services.relatorio_financeiro_service import gerar_relatorio_financeiro

        dados = gerar_relatorio_financeiro(dt_ini, dt_fim)
        return Response(dados)


class ExportarRelatorioFinanceiroExcelView(APIView):
    """GET ?inicio=YYYY-MM-DD&fim=YYYY-MM-DD → download Excel do relatório financeiro."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        inicio_str = request.query_params.get("inicio")
        fim_str = request.query_params.get("fim")
        if not inicio_str or not fim_str:
            return Response(
                {"error": "Parâmetros inicio e fim (YYYY-MM-DD) são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dt_ini = datetime.strptime(inicio_str, "%Y-%m-%d").date()
            dt_fim = datetime.strptime(fim_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Data inválida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from presenca.services.relatorio_financeiro_service import gerar_excel_http

        return gerar_excel_http(dt_ini, dt_fim, inicio_str, fim_str)
