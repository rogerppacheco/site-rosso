# relatorios/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.db import connection
from django.db.utils import OperationalError
from datetime import datetime, timedelta
from django.http import HttpResponse
import pandas as pd
from io import BytesIO
import logging

# Configuração do logger para depuração
logger = logging.getLogger(__name__)

def get_dias_uteis_no_periodo(data_inicio, data_fim):
    """
    Função auxiliar para calcular dias úteis usando Python para maior compatibilidade.
    """
    # Busca os feriados no banco de dados de uma só vez
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT data FROM presenca_dianaoutil WHERE data BETWEEN %s AND %s",
            [data_inicio, data_fim]
        )
        feriados = {row[0] for row in cursor.fetchall()}

    dias_uteis = 0
    current_date = data_inicio
    while current_date <= data_fim:
        # weekday() em Python: Segunda-feira é 0 e Domingo é 6
        if current_date.weekday() < 5:  # Dias de 0 a 4 são dias de semana
            if current_date not in feriados:
                dias_uteis += 1
        current_date += timedelta(days=1)
    return dias_uteis

def validar_datas(request):
    """
    Função auxiliar para validar os parâmetros de data do request.
    """
    data_inicio_str = request.query_params.get('dataInicio')
    data_fim_str = request.query_params.get('dataFim')

    if not data_inicio_str or not data_fim_str:
        return None, None, Response(
            {"msg": "Os parâmetros 'dataInicio' e 'dataFim' são obrigatórios."},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
        return data_inicio, data_fim, None
    except ValueError:
        return None, None, Response(
            {"msg": "Formato de data inválido. Use AAAA-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST
        )

class RelatorioPrevisaoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_inicio, data_fim, error_response = validar_datas(request)
        if error_response:
            return error_response
        
        try:
            dias_uteis = get_dias_uteis_no_periodo(data_inicio, data_fim)

            query = """
                SELECT
                    CONCAT(u.first_name, ' ', u.last_name) as nome_completo,
                    u.valor_almoco,
                    u.valor_passagem
                FROM usuarios_usuario u
                WHERE u.is_active = true
            """
            with connection.cursor() as cursor:
                cursor.execute(query)
                usuarios = cursor.fetchall()
            
            dados_relatorio = []
            for user in usuarios:
                nome_completo, valor_almoco, valor_passagem = user
                valor_almoco = valor_almoco or 0
                valor_passagem = valor_passagem or 0
                auxilio_diario = valor_almoco + valor_passagem
                previsao_periodo = dias_uteis * auxilio_diario
                dados_relatorio.append({
                    'nome_completo': nome_completo.strip(),
                    'auxilio_diario': f"{auxilio_diario:.2f}",
                    'previsao_periodo': f"{previsao_periodo:.2f}",
                })
            
            return Response({
                "periodo": {"inicio": data_inicio, "fim": data_fim, "dias_uteis": dias_uteis},
                "dados": dados_relatorio
            })

        except Exception as e:
            logger.exception("Erro ao gerar relatório de previsão")
            return Response({"msg": f"Ocorreu um erro: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RelatorioDescontosView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_inicio, data_fim, error_response = validar_datas(request)
        if error_response:
            return error_response
        
        try:
            query = """
                SELECT
                    CONCAT(u.first_name, ' ', u.last_name) as nome_completo,
                    pp.data,
                    ma.motivo,
                    (u.valor_almoco + u.valor_passagem) as valor_desconto
                FROM presenca_presenca pp
                JOIN usuarios_usuario u ON pp.colaborador_id = u.id
                LEFT JOIN presenca_motivoausencia ma ON pp.motivo_id = ma.id
                WHERE pp.status = 0
                    AND ma.gera_desconto = true
                    AND pp.data BETWEEN %s AND %s
                ORDER BY u.first_name, pp.data
            """
            with connection.cursor() as cursor:
                cursor.execute(query, [data_inicio, data_fim])
                descontos = cursor.fetchall()

            dados_relatorio = []
            for item in descontos:
                nome_completo, data_falta, motivo, valor_desconto = item
                dados_relatorio.append({
                    'nome_completo': nome_completo.strip(),
                    'data': data_falta,
                    'motivo': motivo or "Não especificado",
                    'valor_desconto': f"{(valor_desconto or 0):.2f}"
                })

            return Response({
                "periodo": {"inicio": data_inicio, "fim": data_fim},
                "dados": dados_relatorio
            })
        
        except Exception as e:
            logger.exception("Erro ao gerar relatório de descontos")
            return Response({"msg": f"Ocorreu um erro: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RelatorioFinalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_inicio, data_fim, error_response = validar_datas(request)
        if error_response:
            return error_response
        
        try:
            dias_uteis = get_dias_uteis_no_periodo(data_inicio, data_fim)

            # Otimização: Buscar usuários e faltas em consultas separadas
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, CONCAT(first_name, ' ', last_name), valor_almoco, valor_passagem
                    FROM usuarios_usuario WHERE is_active = true
                """)
                usuarios_list = cursor.fetchall()

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT colaborador_id, COUNT(*)
                    FROM presenca_presenca pp
                    JOIN presenca_motivoausencia ma ON pp.motivo_id = ma.id
                    WHERE pp.status = 0
                      AND ma.gera_desconto = true
                      AND pp.data BETWEEN %s AND %s
                    GROUP BY colaborador_id
                """, [data_inicio, data_fim])
                faltas = dict(cursor.fetchall())

            dados_relatorio = []
            for user_id, nome_completo, valor_almoco, valor_passagem in usuarios_list:
                dias_falta_com_desconto = faltas.get(user_id, 0)
                
                valor_almoco = valor_almoco or 0
                valor_passagem = valor_passagem or 0
                
                dias_trabalhados = dias_uteis - dias_falta_com_desconto
                auxilio_diario = valor_almoco + valor_passagem
                
                total_a_receber_bruto = dias_uteis * auxilio_diario
                total_a_descontar = dias_falta_com_desconto * auxilio_diario
                valor_final_liquido = total_a_receber_bruto - total_a_descontar

                dados_relatorio.append({
                    'nome_completo': nome_completo.strip(),
                    'dias_uteis_periodo': dias_uteis,
                    'dias_trabalhados': dias_trabalhados,
                    'dias_falta_com_desconto': dias_falta_com_desconto,
                    'total_a_receber': f"{total_a_receber_bruto:.2f}",
                    'total_a_descontar': f"{total_a_descontar:.2f}",
                    'valor_final': f"{valor_final_liquido:.2f}"
                })

            return Response({
                "periodo": {"inicio": data_inicio, "fim": data_fim, "dias_uteis": dias_uteis},
                "dados": dados_relatorio
            })
        
        except Exception as e:
            logger.exception("Erro ao gerar relatório final")
            return Response({"msg": f"Ocorreu um erro: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ExportarRelatorioFinalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        dados_relatorio = request.data.get('dados')
        periodo = request.data.get('periodo')

        if not dados_relatorio:
            return Response({"msg": "Nenhum dado fornecido para exportação."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            df = pd.DataFrame(dados_relatorio)
            
            df.rename(columns={
                'nome_completo': 'Colaborador',
                'dias_uteis_periodo': 'Dias Úteis no Período',
                'dias_trabalhados': 'Dias Trabalhados',
                'dias_falta_com_desconto': 'Faltas com Desconto',
                'total_a_receber': 'Total a Receber (R$)',
                'total_a_descontar': 'Total a Descontar (R$)',
                'valor_final': 'Valor Final (R$)'
            }, inplace=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Relatorio Final')
            
            output.seek(0)

            filename = f"Relatorio_Final_{periodo.get('inicio', '')}_a_{periodo.get('fim', '')}.xlsx"
            response = HttpResponse(
                output,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'

            return response

        except Exception as e:
            logger.exception("Erro ao gerar arquivo Excel")
            return Response({"msg": f"Ocorreu um erro ao gerar o arquivo Excel: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)