# osab/views.py

import pandas as pd
import numpy as np
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser

from usuarios.permissions import CheckAPIPermission
from .models import Osab

class UploadOsabView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'osab'
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        print("\n--- [LOG] INÍCIO DO PROCESSO DE UPLOAD OSAB ---")
        file_obj = request.FILES.get('file')
        
        if not file_obj:
            print("--- [ERRO] Nenhum arquivo foi enviado na requisição.")
            return Response({"error": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)
        
        print(f"--- [LOG] Arquivo recebido: {file_obj.name}")

        try:
            # --- 1. LEITURA DO ARQUIVO ---
            df = None
            file_name = file_obj.name
            
            try:
                print(f"--- [LOG] Tentando ler o arquivo '{file_name}'...")
                if file_name.endswith('.xlsb'):
                    df = pd.read_excel(file_obj, engine='pyxlsb')
                elif file_name.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(file_obj)
                else:
                    print(f"--- [ERRO] Formato de arquivo não suportado: {file_name}")
                    return Response({"error": "Formato de arquivo não suportado. Use .xlsx, .xls ou .xlsb."}, status=status.HTTP_400_BAD_REQUEST)
                
                print("--- [LOG] Arquivo lido com sucesso para o DataFrame Pandas.")

            except Exception as e:
                # Este é o ponto onde o seu erro "valid workbook part" acontece.
                print(f"\n--- [ERRO FATAL] Falha ao ler o arquivo Excel com Pandas ---")
                print(f"--- [ERRO DETALHE] {e}\n")
                return Response({
                    "error": f"Erro ao ler o arquivo: {e}",
                    "suggestion": "Este erro geralmente indica um arquivo corrompido ou uma incompatibilidade de versão da biblioteca (pandas, pyxlsb). Verifique se suas bibliotecas locais estão atualizadas (`pip install -r requirements.txt`)."
                }, status=status.HTTP_400_BAD_REQUEST)

            # --- 2. LIMPEZA E PREPARAÇÃO DOS DADOS ---
            print("--- [LOG] Normalizando nomes das colunas...")
            df.columns = [str(col).strip().upper() for col in df.columns]
            print(f"--- [LOG] Colunas encontradas: {df.columns.tolist()}")

            print("--- [LOG] Substituindo valores vazios (NaN e NaT para datas) por None...")
            df = df.replace({pd.NaT: None, np.nan: None})
            print("--- [LOG] Substituição concluída.")

            # --- 3. PROCESSAMENTO E GRAVAÇÃO NO BANCO ---
            osab_model_fields = [f.name for f in Osab._meta.get_fields()]
            erros = []
            registros_salvos = 0
            total_linhas = len(df)
            
            print(f"--- [LOG] Iniciando processamento de {total_linhas} linhas...")

            for index, row in df.iterrows():
                if row.get('DOCUMENTO') is None or row.get('SITUACAO') is None:
                    msg_erro = f"Linha {index + 2}: 'DOCUMENTO' e 'SITUACAO' são obrigatórios e não foram encontrados."
                    print(f"--- [AVISO] {msg_erro}")
                    erros.append(msg_erro)
                    continue

                osab_data = {}
                for col_name in df.columns:
                    field_name = col_name.lower()
                    if field_name in osab_model_fields:
                        osab_data[field_name] = row.get(col_name)

                try:
                    Osab.objects.create(**osab_data)
                    registros_salvos += 1
                except Exception as e:
                    msg_erro = f"Linha {index + 2}: Erro ao salvar no banco de dados: {e}"
                    print(f"--- [ERRO DB] {msg_erro}")
                    erros.append(msg_erro)

            print("--- [LOG] FIM DO PROCESSAMENTO ---")
            
            return Response({
                'message': 'Importação concluída.',
                'total_records': total_linhas,
                'saved_records': registros_salvos,
                'errors': erros
            }, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"\n--- [ERRO INESPERADO] Um erro não tratado ocorreu: {e}\n")
            return Response({"error": f"Ocorreu um erro inesperado no servidor: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
