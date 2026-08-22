"""API: sem slot na agenda (auditoria) — envio ao GC e relatório diário."""
import logging
from datetime import datetime, timedelta
from io import BytesIO

import openpyxl
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .auditoria_sem_slot_utils import (
    PERFIS_AUDITORIA,
    endereco_completo_dict,
    endereco_completo_venda,
    formatar_telefones_contato,
    processar_envio_sem_slot,
    validar_endereco_completo_venda,
)
from .models import AuditoriaSemSlotGC, Venda
from .utils import is_member

logger = logging.getLogger(__name__)

TURNO_VALIDOS = {'MANHA', 'TARDE'}
# Evita reenvio por cliques repetidos no Confirmar enquanto a 1ª requisição ainda processa.
JANELA_ANTI_DUPLICATA = timedelta(minutes=5)
LOCK_ENVIO_SEGUNDOS = 120


def _resposta_duplicado(registro: AuditoriaSemSlotGC | None, mensagem: str) -> Response:
    if registro is None:
        return Response({
            'success': True,
            'detail': mensagem,
            'id': None,
            'enviado_gc': False,
            'erros': [],
            'duplicado': True,
        }, status=status.HTTP_200_OK)
    sucesso = bool(
        registro.enviado_gc
        or registro.enviados_diretoria
        or getattr(registro, 'enviados_grupos', None)
        or registro.enviado_teams
    )
    return Response({
        'success': sucesso,
        'detail': mensagem,
        'id': registro.id,
        'enviado_gc': registro.enviado_gc,
        'erros': registro.erros,
        'duplicado': True,
    }, status=status.HTTP_200_OK)


class AuditoriaSemSlotEnviarView(APIView):
    """POST multipart após venda CADASTRADA: envia WhatsApp aos destinos configurados."""
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, PERFIS_AUDITORIA):
            return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

        venda_id = request.data.get('venda_id')
        if not venda_id:
            return Response({'detail': 'venda_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            venda = Venda.objects.select_related('cliente').get(id=int(venda_id))
        except (Venda.DoesNotExist, TypeError, ValueError):
            return Response({'detail': 'Venda não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        st_nome = (venda.status_tratamento.nome or '').upper() if venda.status_tratamento else ''
        if st_nome != 'CADASTRADA':
            return Response(
                {'detail': 'A venda precisa estar com status CADASTRADA antes de enviar ao GC.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        faltando = validar_endereco_completo_venda(venda)
        if faltando:
            return Response(
                {'detail': f'Endereço incompleto na venda: {", ".join(faltando)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data_desejada = (request.data.get('data_desejada_cliente') or '').strip()
        turno_desejado = (request.data.get('turno_desejado_cliente') or '').strip().upper()
        if not data_desejada or turno_desejado not in TURNO_VALIDOS:
            return Response(
                {'detail': 'Informe data e turno desejados pelo cliente.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data_desejada_dt = datetime.strptime(data_desejada, '%Y-%m-%d').date()
        except ValueError:
            return Response({'detail': 'Data desejada inválida.'}, status=status.HTTP_400_BAD_REQUEST)

        ordem_servico = (request.data.get('ordem_servico') or venda.ordem_servico or '').strip()
        uf = (request.data.get('uf') or venda.estado or '').strip().upper()[:2]
        if not uf:
            return Response({'detail': 'UF do pedido é obrigatória.'}, status=status.HTTP_400_BAD_REQUEST)

        endereco = (request.data.get('endereco_completo') or '').strip()
        if not endereco:
            endereco = endereco_completo_venda(venda)

        tel1 = (request.data.get('telefone1') or venda.telefone1 or '').strip()
        tel2 = (request.data.get('telefone2') or venda.telefone2 or '').strip()
        telefone_contato = formatar_telefones_contato(tel1, tel2)
        if not telefone_contato:
            return Response({'detail': 'Informe ao menos um telefone de contato.'}, status=status.HTTP_400_BAD_REQUEST)

        imagem = request.FILES.get('imagem')
        if not imagem:
            return Response({'detail': 'Anexe o print do PAP (imagem obrigatória).'}, status=status.HTTP_400_BAD_REQUEST)

        data_ag_cad = venda.data_agendamento
        turno_ag_cad = (venda.periodo_agendamento or '').upper()
        if turno_ag_cad not in TURNO_VALIDOS:
            turno_ag_cad = ''

        # Idempotência: clique múltiplo no Confirmar gera várias POSTs quase simultâneas.
        # 1) Registro já persistido na janela → não reenvia.
        # 2) Lock em cache → bloqueia corrida enquanto o 1º envio ainda não gravou no banco.
        limite = timezone.now() - JANELA_ANTI_DUPLICATA
        recente = (
            AuditoriaSemSlotGC.objects
            .filter(venda_id=venda.id, criado_em__gte=limite)
            .order_by('-criado_em')
            .first()
        )
        if recente:
            logger.info(
                "[Sem SLOT] Ignorando envio duplicado venda_id=%s os=%s registro_id=%s",
                venda.id, ordem_servico, recente.id,
            )
            return _resposta_duplicado(
                recente,
                'Comunicação Sem SLOT já enviada há pouco para esta venda (evitado reenvio duplicado).',
            )

        lock_key = f'auditoria_sem_slot_envio_venda_{venda.id}'
        if not cache.add(lock_key, '1', timeout=LOCK_ENVIO_SEGUNDOS):
            logger.info(
                "[Sem SLOT] Lock ativo — ignorando envio concorrente venda_id=%s os=%s",
                venda.id, ordem_servico,
            )
            recente_lock = (
                AuditoriaSemSlotGC.objects
                .filter(venda_id=venda.id)
                .order_by('-criado_em')
                .first()
            )
            return _resposta_duplicado(
                recente_lock,
                'Envio Sem SLOT já em andamento para esta venda (evitado reenvio duplicado).',
            )

        try:
            registro, sucesso, msg = processar_envio_sem_slot(
                usuario=request.user,
                venda=venda,
                ordem_servico=ordem_servico,
                uf=uf,
                endereco=endereco,
                data_agendamento_cadastrada=data_ag_cad,
                turno_agendamento_cadastrado=turno_ag_cad,
                data_desejada_cliente=data_desejada_dt,
                turno_desejado_cliente=turno_desejado,
                telefone_contato=telefone_contato,
                imagem_upload=imagem,
            )
        finally:
            cache.delete(lock_key)

        if registro is None:
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': sucesso,
            'detail': msg,
            'id': registro.id,
            'enviado_gc': registro.enviado_gc,
            'erros': registro.erros,
            'duplicado': False,
        }, status=status.HTTP_200_OK)


class AuditoriaSemSlotRelatorioView(APIView):
    """GET ?data_inicio=&data_fim= (ou ?data= para um único dia) — exporta Excel."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, PERFIS_AUDITORIA):
            return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

        di = (request.query_params.get('data_inicio') or '').strip()
        df = (request.query_params.get('data_fim') or '').strip()
        data_unica = (request.query_params.get('data') or '').strip()
        try:
            if di or df:
                d_ini = datetime.strptime(di, '%Y-%m-%d').date() if di else timezone.localdate()
                d_fim = datetime.strptime(df, '%Y-%m-%d').date() if df else timezone.localdate()
            elif data_unica:
                d_ini = d_fim = datetime.strptime(data_unica, '%Y-%m-%d').date()
            else:
                d_ini = d_fim = timezone.localdate()
        except ValueError:
            return Response({'detail': 'Datas inválidas (use AAAA-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)
        if d_ini > d_fim:
            d_ini, d_fim = d_fim, d_ini

        qs = AuditoriaSemSlotGC.objects.filter(
            criado_em__date__gte=d_ini,
            criado_em__date__lte=d_fim,
        ).select_related('usuario', 'venda', 'venda__cliente', 'venda__vendedor').order_by('criado_em')

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Sem SLOT'
        headers = [
            'Data/Hora registro', 'O.S.', 'UF', 'Cliente', 'Vendedor', 'Auditor',
            'Endereço', 'Data agendada (cadastro)', 'Turno agendado (cadastro)',
            'Data desejada (cliente)', 'Turno desejado (cliente)', 'Telefones',
            'Enviado GC', 'Enviado e-mail', 'Erros',
        ]
        ws.append(headers)
        for r in qs:
            cliente = ''
            vendedor = ''
            if r.venda:
                if r.venda.cliente:
                    cliente = r.venda.cliente.nome_razao_social or ''
                if r.venda.vendedor:
                    vendedor = r.venda.vendedor.get_full_name() or r.venda.vendedor.username
            auditor = ''
            if r.usuario:
                auditor = r.usuario.get_full_name() or r.usuario.username
            ws.append([
                r.criado_em.strftime('%d/%m/%Y %H:%M') if r.criado_em else '',
                r.ordem_servico or '',
                r.uf or '',
                cliente,
                vendedor,
                auditor,
                r.endereco_completo or '',
                r.data_agendamento_cadastrada.strftime('%d/%m/%Y') if r.data_agendamento_cadastrada else '',
                r.get_turno_agendamento_cadastrado_display() if r.turno_agendamento_cadastrado else '',
                r.data_desejada_cliente.strftime('%d/%m/%Y') if r.data_desejada_cliente else '',
                r.get_turno_desejado_cliente_display() if r.turno_desejado_cliente else '',
                r.telefone_contato or '',
                'Sim' if r.enviado_gc else 'Não',
                'Sim' if r.enviado_email else 'Não',
                '; '.join(r.erros) if r.erros else '',
            ])

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        if d_ini == d_fim:
            filename = f"auditoria_sem_slot_{d_ini.strftime('%Y%m%d')}.xlsx"
        else:
            filename = f"auditoria_sem_slot_{d_ini.strftime('%Y%m%d')}_{d_fim.strftime('%Y%m%d')}.xlsx"
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
