import logging
import os
from io import BytesIO

import requests
from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import FileResponse
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RecordApoia

logger = logging.getLogger(__name__)


def record_apoia_arquivo_existe_local(arquivo_record):
    """Verifica se o arquivo físico existe no MEDIA_ROOT/storage."""
    if not arquivo_record.arquivo or not arquivo_record.arquivo.name:
        return False
    try:
        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if media_root:
            return os.path.exists(os.path.join(media_root, arquivo_record.arquivo.name))
        return default_storage.exists(arquivo_record.arquivo.name)
    except Exception as e:
        logger.warning("Erro ao verificar arquivo local Record Apoia %s: %s", arquivo_record.id, e)
        return False


def record_apoia_disponivel(arquivo_record):
    """Arquivo utilizável: existe no disco ou possui URL de backup (R2)."""
    if arquivo_record.url_externa:
        return True
    return record_apoia_arquivo_existe_local(arquivo_record)


def record_apoia_ler_bytes(arquivo_record):
    """
    Lê bytes do arquivo local ou baixa da url_externa (R2).
    Raises FileNotFoundError se não houver fonte disponível.
    """
    if record_apoia_arquivo_existe_local(arquivo_record):
        arquivo_field = arquivo_record.arquivo
        try:
            if default_storage.exists(arquivo_field.name):
                with default_storage.open(arquivo_field.name, 'rb') as f:
                    return f.read()
        except Exception:
            pass
        arquivo_field.open('rb')
        try:
            return arquivo_field.read()
        finally:
            arquivo_field.close()

    if arquivo_record.url_externa:
        resp = requests.get(arquivo_record.url_externa, timeout=90)
        resp.raise_for_status()
        return resp.content

    raise FileNotFoundError(
        f"Arquivo indisponível (id={arquivo_record.id}, titulo={arquivo_record.titulo})"
    )


def espelhar_record_apoia_r2(arquivo_record, conteudo_bytes):
    """Envia cópia para o R2 e grava url_externa no registro."""
    if not conteudo_bytes:
        return None
    try:
        from crm_app.cloudflare_r2_service import CloudflareR2Storage

        nome = arquivo_record.nome_original or os.path.basename(arquivo_record.arquivo.name or 'arquivo')
        uploader = CloudflareR2Storage()
        url = uploader.upload_file_and_get_download_url(
            BytesIO(conteudo_bytes),
            folder_name='Record_Apoia',
            filename=nome,
        )
        if url:
            arquivo_record.url_externa = url
            arquivo_record.save(update_fields=['url_externa'])
            logger.info("[Record Apoia] Backup R2 salvo: %s (id=%s)", nome, arquivo_record.id)
        return url
    except Exception as e:
        logger.warning(
            "[Record Apoia] Falha ao espelhar no R2 (id=%s): %s",
            arquivo_record.id,
            e,
        )
        return None

class RecordApoiaUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            arquivos = request.FILES.getlist('arquivo')
            if not arquivos:
                return Response({'error': 'Nenhum arquivo enviado'}, status=400)
            
            titulo = request.data.get('titulo', '').strip()
            descricao = request.data.get('descricao', '').strip()
            categoria = request.data.get('categoria', '').strip()
            tags = request.data.get('tags', '').strip()
            
            resultados = []
            erros = []
            
            for arquivo in arquivos:
                try:
                    # Validar arquivo
                    if arquivo.size > 100 * 1024 * 1024:  # 100MB
                        erros.append({
                            'arquivo': arquivo.name,
                            'erro': 'Arquivo muito grande (máximo 100MB)'
                        })
                        continue
                    
                    # Usar o título fornecido ou o nome do arquivo
                    titulo_arquivo = titulo if titulo else arquivo.name
                    if len(arquivos) > 1 and titulo:
                        # Se múltiplos arquivos e título fornecido, usar título + nome do arquivo
                        titulo_arquivo = f"{titulo} - {arquivo.name}"
                    
                    # Determinar tipo_arquivo baseado na extensão
                    tipo_arquivo = 'OUTRO'
                    if arquivo.name:
                        ext = arquivo.name.split('.')[-1].lower()
                        if ext in ['pdf']:
                            tipo_arquivo = 'PDF'
                        elif ext in ['doc', 'docx']:
                            tipo_arquivo = 'WORD'
                        elif ext in ['xls', 'xlsx']:
                            tipo_arquivo = 'EXCEL'
                        elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                            tipo_arquivo = 'IMAGEM'
                        elif ext in ['mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm']:
                            tipo_arquivo = 'VIDEO'
                    
                    # Ler bytes antes do save para backup R2 (disco local no Railway é efêmero)
                    arquivo.seek(0)
                    conteudo_bytes = arquivo.read()
                    arquivo.seek(0)

                    # Criar registro
                    record = RecordApoia.objects.create(
                        titulo=titulo_arquivo,
                        descricao=descricao,
                        categoria=categoria,
                        tags=tags,
                        arquivo=arquivo,
                        nome_original=arquivo.name,
                        tipo_arquivo=tipo_arquivo,
                        tamanho_bytes=len(conteudo_bytes),
                        usuario_upload=request.user
                    )

                    espelhar_record_apoia_r2(record, conteudo_bytes)

                    tamanho = len(conteudo_bytes)
                    if record.arquivo:
                        try:
                            tamanho = record.arquivo.size or tamanho
                        except (FileNotFoundError, IOError, OSError, AttributeError):
                            pass
                    
                    resultados.append({
                        'id': record.id,
                        'titulo': record.titulo,
                        'nome_original': record.nome_original,
                        'tamanho': tamanho,
                        'tipo': record.get_tipo_arquivo_display(),
                        'criado_em': record.data_upload.isoformat() if record.data_upload else None
                    })
                except Exception as e:
                    logger.error(f"Erro ao fazer upload de {arquivo.name}: {e}")
                    erros.append({
                        'arquivo': arquivo.name,
                        'erro': str(e)
                    })
            
            if resultados and not erros:
                return Response({
                    'sucesso': True,
                    'message': f'{len(resultados)} arquivo(s) enviado(s) com sucesso',
                    'resultados': resultados
                })
            elif resultados:
                return Response({
                    'sucesso': True,
                    'message': f'{len(resultados)} arquivo(s) enviado(s), {len(erros)} erro(s)',
                    'resultados': resultados,
                    'erros': erros,
                    'total_enviados': len(resultados),
                    'total_erros': len(erros)
                }, status=207)  # Multi-Status
            else:
                return Response({
                    'error': 'Nenhum arquivo foi enviado com sucesso',
                    'erros': erros
                }, status=400)
                
        except Exception as e:
            logger.error(f"Erro no upload: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            busca = request.query_params.get('busca', '').strip()
            categoria_filtro = request.query_params.get('categoria', '').strip()
            
            queryset = RecordApoia.objects.filter(ativo=True)
            
            if busca:
                queryset = queryset.filter(
                    Q(titulo__icontains=busca) |
                    Q(descricao__icontains=busca) |
                    Q(tags__icontains=busca) |
                    Q(categoria__icontains=busca)
                )
            
            if categoria_filtro:
                queryset = queryset.filter(categoria__iexact=categoria_filtro)
            
            queryset = queryset.order_by('-data_upload')
            
            # Importar settings para verificar caminho do arquivo
            from django.conf import settings
            from django.utils import timezone
            
            # Função auxiliar para formatar tamanho
            def formatar_tamanho_bytes(bytes_size):
                if bytes_size == 0:
                    return '0 Bytes'
                k = 1024
                sizes = ['Bytes', 'KB', 'MB', 'GB']
                i = 0
                size = float(bytes_size)
                while size >= k and i < len(sizes) - 1:
                    size /= k
                    i += 1
                return f"{round(size, 2)} {sizes[i]}"
            
            arquivos = []
            for arq in queryset:
                try:
                    # Verificar se o arquivo existe antes de adicionar à lista
                    arquivo_existe = False
                    tamanho = 0
                    
                    if not record_apoia_disponivel(arq):
                        logger.warning(
                            "Arquivo %s (%s) indisponível (sem disco e sem url_externa) - pulando listagem",
                            arq.id,
                            arq.titulo,
                        )
                        continue

                    arquivo_existe = record_apoia_arquivo_existe_local(arq)
                    tamanho = arq.tamanho_bytes or 0
                    if arquivo_existe:
                        try:
                            tamanho = arq.arquivo.size or tamanho
                        except (FileNotFoundError, IOError, OSError, AttributeError):
                            pass
                    elif arq.url_externa and not tamanho:
                        tamanho = arq.tamanho_bytes or 0
                    
                    # Formatar data
                    data_upload_formatada = None
                    if arq.data_upload:
                        data_upload_formatada = timezone.localtime(arq.data_upload).strftime('%d/%m/%Y %H:%M')
                    
                    arquivos.append({
                        'id': arq.id,
                        'titulo': arq.titulo,
                        'descricao': arq.descricao or '',
                        'categoria': arq.categoria or '',
                        'tags': arq.tags or '',
                        'tipo_arquivo': arq.tipo_arquivo,
                        'tipo_arquivo_display': arq.get_tipo_arquivo_display(),
                        'tamanho_bytes': tamanho,
                        'tamanho_formatado': formatar_tamanho_bytes(tamanho),
                        'data_upload': data_upload_formatada,
                        'downloads_count': arq.downloads_count or 0,
                        'usuario_upload': arq.usuario_upload.username if arq.usuario_upload else 'Desconhecido'
                    })
                except Exception as e:
                    logger.error(f"Erro ao processar arquivo {arq.id}: {e}")
                    continue
            
            # Obter categorias únicas para filtros
            categorias = RecordApoia.objects.filter(ativo=True).exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct()
            categorias = sorted(set(categorias))
            
            # Paginação simples
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            total = len(arquivos)
            start = (page - 1) * page_size
            end = start + page_size
            arquivos_paginados = arquivos[start:end]
            
            return Response({
                'success': True,
                'arquivos': arquivos_paginados,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': (total + page_size - 1) // page_size,
                'categorias': categorias
            })
            
        except Exception as e:
            logger.error(f"Erro na listagem: {e}")
            import traceback
            return Response({
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=500)


class RecordApoiaEditView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, arquivo_id):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            arquivo = RecordApoia.objects.get(id=arquivo_id)
            
            titulo = request.data.get('titulo', '').strip()
            descricao = request.data.get('descricao', '').strip()
            categoria = request.data.get('categoria', '').strip()
            tags = request.data.get('tags', '').strip()
            
            if titulo:
                arquivo.titulo = titulo
            if descricao is not None:
                arquivo.descricao = descricao
            if categoria is not None:
                arquivo.categoria = categoria
            if tags is not None:
                arquivo.tags = tags
            
            arquivo.save()
            
            return Response({
                'sucesso': True,
                'mensagem': 'Arquivo atualizado com sucesso',
                'arquivo': {
                    'id': arquivo.id,
                    'titulo': arquivo.titulo,
                    'descricao': arquivo.descricao,
                    'categoria': arquivo.categoria,
                    'tags': arquivo.tags
                }
            })
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao editar: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaToggleActiveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, arquivo_id):
        """Inativa ou ativa um arquivo (toggle do campo ativo)"""
        try:
            arquivo = RecordApoia.objects.get(id=arquivo_id)
            
            # Alternar estado ativo
            arquivo.ativo = not arquivo.ativo
            arquivo.save()
            
            acao = 'ativado' if arquivo.ativo else 'inativado'
            
            return Response({
                'sucesso': True,
                'mensagem': f'Arquivo {acao} com sucesso',
                'ativo': arquivo.ativo
            })
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao alterar status: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, arquivo_id):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            arquivo = RecordApoia.objects.get(id=arquivo_id)
            
            # Deletar arquivo físico do disco (se existir)
            if arquivo.arquivo and arquivo.arquivo.name:
                try:
                    # Tentar deletar usando o storage do Django
                    arquivo.arquivo.delete(save=False)
                    logger.info(f"Arquivo físico deletado: {arquivo.arquivo.name}")
                except Exception as delete_file_error:
                    # Se não conseguir deletar o arquivo físico, apenas logar o erro mas continuar
                    logger.warning(f"Erro ao deletar arquivo físico {arquivo.arquivo.name}: {delete_file_error}")
            
            # Marcar como inativo (soft delete)
            arquivo.ativo = False
            arquivo.save()
            
            return Response({'sucesso': True, 'mensagem': 'Arquivo removido com sucesso'})
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao deletar: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaDiagnosticoView(APIView):
    """
    View para diagnosticar problemas com arquivos do Record Apoia.
    Verifica se os arquivos físicos existem no servidor.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            from django.conf import settings
            import os
            
            # Buscar todos os arquivos ativos
            arquivos = RecordApoia.objects.filter(ativo=True)
            
            diagnosticos = {
                'total_arquivos': arquivos.count(),
                'arquivos_com_problema': [],
                'arquivos_ok': 0,
                'pastas_verificadas': {},
                'media_root': getattr(settings, 'MEDIA_ROOT', 'Não configurado')
            }
            
            for arquivo in arquivos:
                existe_fisico = False
                caminho_completo = None
                
                if arquivo.arquivo and arquivo.arquivo.name:
                    caminho_relativo = arquivo.arquivo.name
                    media_root = getattr(settings, 'MEDIA_ROOT', None)
                    
                    if media_root:
                        caminho_completo = os.path.join(media_root, caminho_relativo)
                        existe_fisico = os.path.exists(caminho_completo)
                        
                        # Verificar pasta e listar arquivos reais
                        pasta = os.path.dirname(caminho_completo)
                        if pasta not in diagnosticos['pastas_verificadas']:
                            arquivos_reais = []
                            if os.path.exists(pasta):
                                try:
                                    arquivos_reais = [f for f in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, f))]
                                except (PermissionError, OSError) as e:
                                    logger.warning(f"Erro ao listar pasta {pasta}: {e}")
                            
                            diagnosticos['pastas_verificadas'][pasta] = {
                                'existe': os.path.exists(pasta),
                                'arquivos_na_pasta': len(arquivos_reais),
                                'lista_arquivos': arquivos_reais  # Lista completa dos arquivos encontrados
                            }
                    else:
                        # Tentar usar storage
                        existe_fisico = default_storage.exists(caminho_relativo)
                        caminho_completo = caminho_relativo
                    
                    if existe_fisico:
                        diagnosticos['arquivos_ok'] += 1
                    else:
                        diagnosticos['arquivos_com_problema'].append({
                            'id': arquivo.id,
                            'titulo': arquivo.titulo,
                            'nome_original': arquivo.nome_original,
                            'caminho_esperado': caminho_completo,
                            'caminho_relativo': caminho_relativo,
                            'criado_em': arquivo.data_upload.isoformat() if arquivo.data_upload else None
                        })
            
            diagnosticos['total_com_problema'] = len(diagnosticos['arquivos_com_problema'])
            
            return Response(diagnosticos)
            
        except Exception as e:
            logger.error(f"Erro no diagnóstico: {e}")
            import traceback
            return Response({
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=500)


class RecordApoiaBuscarView(APIView):
    """
    View para buscar arquivos específicos no Record Apoia (incluindo inativos).
    Útil para encontrar e limpar arquivos problemáticos.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            busca = request.query_params.get('busca', '').strip()
            incluir_inativos = request.query_params.get('incluir_inativos', 'false').lower() == 'true'
            
            if not busca:
                return Response({'error': 'Parâmetro "busca" é obrigatório'}, status=400)
            
            queryset = RecordApoia.objects.all()
            
            if not incluir_inativos:
                queryset = queryset.filter(ativo=True)
            
            # Buscar por título ou nome original
            from django.db.models import Q
            queryset = queryset.filter(
                Q(titulo__icontains=busca) | Q(nome_original__icontains=busca)
            )
            
            arquivos = []
            for arq in queryset[:50]:  # Limitar a 50 resultados
                arquivos.append({
                    'id': arq.id,
                    'titulo': arq.titulo,
                    'nome_original': arq.nome_original,
                    'ativo': arq.ativo,
                    'data_upload': arq.data_upload.isoformat() if arq.data_upload else None
                })
            
            return Response({
                'success': True,
                'arquivos': arquivos,
                'total': len(arquivos)
            })
            
        except Exception as e:
            logger.error(f"Erro na busca: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaAdminOrfaosView(APIView):
    """
    View administrativa para listar arquivos órfãos:
    - Arquivos inativos que ainda têm arquivo no disco (podem ser limpos)
    - Arquivos ativos que não têm arquivo no disco (registros órfãos)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Apenas para administradores
        try:
            from crm_app.views import is_member
        except ImportError:
            return Response({'error': 'Função is_member não encontrada'}, status=500)
        
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({'error': 'Acesso negado. Apenas administradores podem acessar esta página.'}, status=403)
        
        try:
            from django.conf import settings
            import os
            from django.utils import timezone
            
            inativos_com_arquivo = []
            ativos_sem_arquivo = []
            
            # Buscar todos os arquivos
            todos_arquivos = RecordApoia.objects.all()
            
            for arquivo in todos_arquivos:
                arquivo_existe = False
                caminho_completo = None
                
                if arquivo.arquivo and arquivo.arquivo.name:
                    media_root = getattr(settings, 'MEDIA_ROOT', None)
                    if media_root:
                        caminho_completo = os.path.join(media_root, arquivo.arquivo.name)
                        arquivo_existe = os.path.exists(caminho_completo)
                    else:
                        arquivo_existe = default_storage.exists(arquivo.arquivo.name)
                
                # Arquivos inativos que ainda têm arquivo no disco
                if not arquivo.ativo and arquivo_existe:
                    inativos_com_arquivo.append({
                        'id': arquivo.id,
                        'titulo': arquivo.titulo,
                        'nome_original': arquivo.nome_original,
                        'caminho': arquivo.arquivo.name if arquivo.arquivo else None,
                        'data_upload': timezone.localtime(arquivo.data_upload).strftime('%d/%m/%Y %H:%M') if arquivo.data_upload else None,
                        'tipo': arquivo.get_tipo_arquivo_display(),
                        'tamanho_bytes': arquivo.tamanho_bytes or 0
                    })
                
                # Ativos sem arquivo local e sem backup R2
                if arquivo.ativo and not record_apoia_disponivel(arquivo) and arquivo.arquivo and arquivo.arquivo.name:
                    ativos_sem_arquivo.append({
                        'id': arquivo.id,
                        'titulo': arquivo.titulo,
                        'nome_original': arquivo.nome_original,
                        'caminho_esperado': caminho_completo,
                        'data_upload': timezone.localtime(arquivo.data_upload).strftime('%d/%m/%Y %H:%M') if arquivo.data_upload else None,
                        'tipo': arquivo.get_tipo_arquivo_display()
                    })
            
            return Response({
                'success': True,
                'inativos_com_arquivo': inativos_com_arquivo,
                'ativos_sem_arquivo': ativos_sem_arquivo,
                'total_inativos_com_arquivo': len(inativos_com_arquivo),
                'total_ativos_sem_arquivo': len(ativos_sem_arquivo)
            })
            
        except Exception as e:
            logger.error(f"Erro ao listar arquivos órfãos: {e}")
            import traceback
            return Response({
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=500)


class RecordApoiaAdminLimparOrfaosView(APIView):
    """
    View administrativa para limpar arquivos órfãos:
    - Deletar arquivos físicos de registros inativos
    - Deletar registros ativos que não têm arquivo no disco
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Apenas para administradores
        try:
            from crm_app.views import is_member
        except ImportError:
            return Response({'error': 'Função is_member não encontrada'}, status=500)
        
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({'error': 'Acesso negado. Apenas administradores podem executar esta ação.'}, status=403)
        
        try:
            from django.conf import settings
            import os
            
            tipo_limpeza = request.data.get('tipo', 'todos')  # 'inativos', 'sem_arquivo', 'todos'
            
            limpos = []
            erros = []
            
            if tipo_limpeza in ['inativos', 'todos']:
                # Limpar arquivos físicos de registros inativos
                inativos = RecordApoia.objects.filter(ativo=False)
                for arquivo in inativos:
                    if arquivo.arquivo and arquivo.arquivo.name:
                        try:
                            media_root = getattr(settings, 'MEDIA_ROOT', None)
                            if media_root:
                                caminho_completo = os.path.join(media_root, arquivo.arquivo.name)
                                if os.path.exists(caminho_completo):
                                    os.remove(caminho_completo)
                                    limpos.append({
                                        'id': arquivo.id,
                                        'titulo': arquivo.titulo,
                                        'acao': 'arquivo_fisico_deletado'
                                    })
                                    logger.info(f"Arquivo físico deletado: {caminho_completo}")
                        except Exception as e:
                            erros.append({
                                'id': arquivo.id,
                                'titulo': arquivo.titulo,
                                'erro': str(e)
                            })
                            logger.error(f"Erro ao deletar arquivo físico {arquivo.arquivo.name}: {e}")
            
            if tipo_limpeza in ['sem_arquivo', 'todos']:
                # Deletar registros ativos que não têm arquivo no disco
                todos_ativos = RecordApoia.objects.filter(ativo=True)
                for arquivo in todos_ativos:
                    if arquivo.arquivo and arquivo.arquivo.name:
                        arquivo_existe = False
                        media_root = getattr(settings, 'MEDIA_ROOT', None)
                        if media_root:
                            caminho_completo = os.path.join(media_root, arquivo.arquivo.name)
                            arquivo_existe = os.path.exists(caminho_completo)
                        else:
                            arquivo_existe = default_storage.exists(arquivo.arquivo.name)
                        
                        if not arquivo_existe:
                            try:
                                limpos.append({
                                    'id': arquivo.id,
                                    'titulo': arquivo.titulo,
                                    'acao': 'registro_deletado'
                                })
                                arquivo.delete()  # Hard delete do registro
                                logger.info(f"Registro órfão deletado: {arquivo.id} - {arquivo.titulo}")
                            except Exception as e:
                                erros.append({
                                    'id': arquivo.id,
                                    'titulo': arquivo.titulo,
                                    'erro': str(e)
                                })
                                logger.error(f"Erro ao deletar registro {arquivo.id}: {e}")
            
            return Response({
                'success': True,
                'mensagem': f'{len(limpos)} item(s) limpo(s)',
                'limpos': limpos,
                'total_limpos': len(limpos),
                'erros': erros,
                'total_erros': len(erros)
            })
            
        except Exception as e:
            logger.error(f"Erro ao limpar arquivos órfãos: {e}")
            import traceback
            return Response({
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=500)


class RecordApoiaDownloadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, arquivo_id):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            arquivo = RecordApoia.objects.get(id=arquivo_id, ativo=True)
            
            if not record_apoia_disponivel(arquivo):
                return Response({'error': 'Arquivo não encontrado no servidor'}, status=404)

            is_preview = request.query_params.get('preview', 'false').lower() == 'true'

            if not is_preview:
                arquivo.downloads_count = (arquivo.downloads_count or 0) + 1
                arquivo.save(update_fields=['downloads_count'])

            try:
                if record_apoia_arquivo_existe_local(arquivo):
                    file_handle = arquivo.arquivo.open('rb')
                    file_response = FileResponse(
                        file_handle,
                        as_attachment=not is_preview,
                        filename=arquivo.nome_original
                    )
                elif arquivo.url_externa:
                    conteudo = record_apoia_ler_bytes(arquivo)
                    file_response = FileResponse(
                        BytesIO(conteudo),
                        as_attachment=not is_preview,
                        filename=arquivo.nome_original,
                    )
                else:
                    return Response({'error': 'Arquivo não encontrado no disco'}, status=404)
                
                # Para imagens em preview, definir content-type apropriado
                if is_preview and arquivo.tipo_arquivo == 'IMAGEM':
                    ext = arquivo.nome_original.split('.')[-1].lower() if arquivo.nome_original else ''
                    content_types = {
                        'jpg': 'image/jpeg',
                        'jpeg': 'image/jpeg',
                        'png': 'image/png',
                        'gif': 'image/gif',
                        'webp': 'image/webp',
                        'bmp': 'image/bmp'
                    }
                    if ext in content_types:
                        file_response['Content-Type'] = content_types[ext]
                
                return file_response
                
            except FileNotFoundError:
                logger.error(f"Arquivo não encontrado no disco: {arquivo.arquivo.name}")
                return Response({'error': 'Arquivo não encontrado no disco'}, status=404)
            except Exception as e:
                logger.error(f"Erro ao abrir arquivo: {e}")
                return Response({'error': f'Erro ao acessar arquivo: {str(e)}'}, status=500)
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao fazer download: {e}")
            return Response({'error': str(e)}, status=500)
