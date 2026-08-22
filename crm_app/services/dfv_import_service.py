"""
Serviço profissional para importação de arquivos DFV (Dados do Faturamento de Vendas).

Este módulo implementa as melhores práticas de desenvolvimento:
- Service Layer Pattern
- Logging estruturado
- Tratamento robusto de erros
- Gerenciamento eficiente de memória
- Progress tracking granular
- Validação de dados
- Transações atômicas
"""

import logging
import os
import re
import time
import traceback
from typing import Dict, List, Tuple, Optional, Set
from io import BytesIO, StringIO
from datetime import datetime, timedelta

import pandas as pd
from django.db import transaction, connection, connections
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError

from crm_app.models import DFV, LogImportacaoDFV

logger = logging.getLogger(__name__)

try:
    from psycopg2.extras import execute_values
except Exception:
    execute_values = None


class DFVImportError(Exception):
    """Exceção customizada para erros de importação DFV"""
    pass


class DFVImportService:
    """
    Serviço profissional para processamento de importação DFV.
    
    Responsabilidades:
    - Validação de arquivos CSV
    - Processamento em chunks para otimização de memória
    - Remoção eficiente de duplicados
    - Criação em lote de registros
    - Tracking granular de progresso
    - Tratamento robusto de erros
    """
    
    # Constantes de configuração
    CHUNK_SIZE_CLEANUP = 100_000  # Tamanho do chunk para limpeza de dados
    CHUNK_SIZE_PREPARATION = 20_000  # Tamanho do chunk para preparação de objetos (reduzido para evitar travamento)
    BATCH_SIZE_DELETE = 10_000  # Tamanho do lote para remoção de duplicados
    BATCH_SIZE_CREATE = 1_000  # Tamanho do lote para criação de registros
    BATCH_SIZE_CREATE_SUB = 500  # Sub-lote para inserção com progresso mais frequente
    PROGRESS_UPDATE_INTERVAL = 5  # Atualizar progresso a cada N chunks
    PREPARATION_PROGRESS_INTERVAL = 5_000  # Atualizar progresso a cada N registros durante preparação
    DB_IMPORT_LOCK_KEY = 93142761  # Chave fixa para lock global de importação (PostgreSQL)
    DB_IMPORT_LOCK_WAIT_SECONDS = 1800  # 30 minutos
    DB_IMPORT_LOCK_POLL_SECONDS = 5
    
    # Colunas obrigatórias
    REQUIRED_COLUMNS = ['CEP', 'NUM_FACHADA']
    
    # Colunas opcionais
    OPTIONAL_COLUMNS = [
        'UF', 'MUNICIPIO', 'LOGRADOURO', 'COMPLEMENTO', 
        'BAIRRO', 'TIPO_VIABILIDADE', 'TIPO_REDE', 'CELULA', 'NOME_CDO'
    ]
    
    def __init__(self, log_id: int):
        """
        Inicializa o serviço de importação.
        
        Args:
            log_id: ID do log de importação
        """
        self.log_id = log_id
        self.log: Optional[LogImportacaoDFV] = None
        self._load_log()
        
    def _load_log(self) -> None:
        """Carrega o log de importação do banco de dados"""
        try:
            self.log = LogImportacaoDFV.objects.get(id=self.log_id)
        except LogImportacaoDFV.DoesNotExist:
            raise DFVImportError(f"Log de importação {self.log_id} não encontrado")
    
    def _update_progress(
        self, 
        total_processed: Optional[int] = None,
        success: Optional[int] = None,
        message: Optional[str] = None,
        errors: Optional[int] = None
    ) -> None:
        """
        Atualiza o progresso da importação de forma atômica.
        
        Args:
            total_processed: Total de registros processados
            success: Total de registros criados com sucesso
            message: Mensagem de status atual
            errors: Total de erros encontrados
        """
        update_fields = {}
        
        if total_processed is not None:
            update_fields['total_processadas'] = total_processed
        if success is not None:
            update_fields['sucesso'] = success
        if message is not None:
            update_fields['mensagem'] = message
        if errors is not None:
            update_fields['erros'] = errors
            
        if update_fields:
            try:
                LogImportacaoDFV.objects.filter(id=self.log_id).update(**update_fields)
            except Exception as e:
                logger.error(f"[DFV] Erro ao atualizar progresso: {e}", exc_info=True)

    def _lock_db_connection(self):
        """Advisory locks exigem sessão dedicada — incompatível com PgBouncer transaction mode."""
        if 'unpooled' in connections:
            return connections['unpooled']
        return connection

    def _acquire_db_lock(self) -> None:
        """
        Garante que apenas uma importação DFV rode por vez no Postgres.
        Evita contenção de locks durante remoção de duplicados/criação.
        """
        lock_conn = self._lock_db_connection()
        if lock_conn.vendor != 'postgresql':
            return

        inicio = time.monotonic()
        while True:
            try:
                with lock_conn.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [self.DB_IMPORT_LOCK_KEY])
                    locked = cursor.fetchone()[0]
            except Exception as e:
                logger.warning(f"[DFV] Não foi possível verificar lock de importação: {e}")
                locked = False

            if locked:
                logger.info("[DFV] Lock global de importação adquirido")
                return

            # Atualiza o status enquanto aguarda na fila
            self._update_progress(
                message='Aguardando fila de importação... outro arquivo está em processamento.'
            )
            time.sleep(self.DB_IMPORT_LOCK_POLL_SECONDS)

            if time.monotonic() - inicio > self.DB_IMPORT_LOCK_WAIT_SECONDS:
                raise DFVImportError(
                    "Outra importação está em andamento por muito tempo. Tente novamente mais tarde."
                )

    def _release_db_lock(self) -> None:
        """Libera o lock global de importação no Postgres."""
        lock_conn = self._lock_db_connection()
        if lock_conn.vendor != 'postgresql':
            return
        try:
            with lock_conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [self.DB_IMPORT_LOCK_KEY])
        except Exception as e:
            logger.warning(f"[DFV] Não foi possível liberar lock de importação: {e}")
    
    def _validate_file(self, arquivo_bytes: Optional[bytes], arquivo_nome: str, arquivo_path: Optional[str] = None) -> None:
        """
        Valida o arquivo antes do processamento.
        
        Args:
            arquivo_bytes: Conteúdo do arquivo em bytes
            arquivo_nome: Nome do arquivo
            
        Raises:
            DFVImportError: Se o arquivo for inválido
        """
        if not arquivo_bytes and not arquivo_path:
            raise DFVImportError("Arquivo vazio")
        
        if not arquivo_nome.lower().endswith('.csv'):
            raise DFVImportError("Arquivo deve ter extensão .csv")
        
        # Validar tamanho mínimo (pelo menos alguns bytes)
        tamanho_bytes = 0
        if arquivo_bytes:
            tamanho_bytes = len(arquivo_bytes)
        elif arquivo_path and os.path.exists(arquivo_path):
            tamanho_bytes = os.path.getsize(arquivo_path)

        if tamanho_bytes < 100:
            raise DFVImportError("Arquivo muito pequeno para ser válido")
        
        logger.info(f"[DFV] Arquivo validado: {arquivo_nome} ({tamanho_bytes / (1024*1024):.2f} MB)")
    
    def _read_csv(self, arquivo_bytes: Optional[bytes], arquivo_path: Optional[str] = None) -> pd.DataFrame:
        """
        Lê o arquivo CSV com tratamento de encoding.
        
        Args:
            arquivo_bytes: Conteúdo do arquivo em bytes
            
        Returns:
            DataFrame do pandas com os dados
            
        Raises:
            DFVImportError: Se não conseguir ler o arquivo
        """
        arquivo_io = None
        if arquivo_bytes:
            arquivo_io = BytesIO(arquivo_bytes)
        
        # Tentar UTF-8 primeiro
        encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
        
        for encoding in encodings:
            try:
                if arquivo_path:
                    df = pd.read_csv(
                        arquivo_path,
                        sep=';',
                        dtype=str,
                        encoding=encoding,
                        low_memory=False,
                        on_bad_lines='skip',
                        engine='c',
                        memory_map=False,
                        na_filter=False
                    )
                else:
                    arquivo_io.seek(0)
                    df = pd.read_csv(
                        arquivo_io,
                        sep=';',
                        dtype=str,
                        encoding=encoding,
                        low_memory=False,
                        on_bad_lines='skip',
                        engine='c',
                        memory_map=False,
                        na_filter=False
                    )
                logger.info(f"[DFV] Arquivo lido com sucesso usando encoding: {encoding}")
                return df
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"[DFV] Erro ao ler CSV com encoding {encoding}: {e}")
                raise DFVImportError(f"Erro ao ler arquivo CSV: {str(e)}")
        
        raise DFVImportError("Não foi possível determinar o encoding do arquivo")
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normaliza os nomes das colunas do DataFrame.
        
        Args:
            df: DataFrame original
            
        Returns:
            DataFrame com colunas normalizadas
        """
        df.columns = [str(col).strip().upper() for col in df.columns]
        logger.debug(f"[DFV] Colunas normalizadas: {list(df.columns)[:10]}")
        return df
    
    def _validate_columns(self, df: pd.DataFrame) -> None:
        """
        Valida se as colunas obrigatórias estão presentes.
        
        Args:
            df: DataFrame a validar
            
        Raises:
            DFVImportError: Se colunas obrigatórias estiverem faltando
        """
        missing_columns = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing_columns:
            raise DFVImportError(
                f"Colunas obrigatórias não encontradas: {', '.join(missing_columns)}"
            )
    
    def _clean_cep(self, cep_str: str) -> str:
        """
        Limpa e normaliza um CEP, removendo caracteres não numéricos.
        
        Args:
            cep_str: String do CEP
            
        Returns:
            CEP limpo (apenas dígitos)
        """
        if not cep_str or pd.isna(cep_str):
            return ''
        return ''.join(filter(str.isdigit, str(cep_str)))
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Limpa e normaliza os dados do DataFrame.
        
        Args:
            df: DataFrame original
            
        Returns:
            DataFrame limpo com colunas cep_limpo e fachada_limpa
        """
        logger.info(f"[DFV] Iniciando limpeza de dados para {len(df)} registros")
        
        # Preencher NaN e converter para string
        df['CEP'] = df['CEP'].fillna('').astype(str)
        df['NUM_FACHADA'] = df['NUM_FACHADA'].fillna('').astype(str)
        
        # Processar em chunks para otimizar memória
        total_chunks = (len(df) + self.CHUNK_SIZE_CLEANUP - 1) // self.CHUNK_SIZE_CLEANUP
        
        df['cep_limpo'] = ''
        df['fachada_limpa'] = ''
        
        for i in range(0, len(df), self.CHUNK_SIZE_CLEANUP):
            chunk_num = (i // self.CHUNK_SIZE_CLEANUP) + 1
            end_idx = min(i + self.CHUNK_SIZE_CLEANUP, len(df))
            
            # Limpar CEP e fachada
            chunk_df = df.iloc[i:end_idx]
            df.loc[chunk_df.index, 'cep_limpo'] = chunk_df['CEP'].apply(self._clean_cep)
            df.loc[chunk_df.index, 'fachada_limpa'] = chunk_df['NUM_FACHADA'].str.strip()
            
            # Atualizar progresso periodicamente
            if chunk_num % self.PROGRESS_UPDATE_INTERVAL == 0:
                self._update_progress(
                    total_processed=end_idx,
                    message=f'Limpando dados... {chunk_num}/{total_chunks} chunks'
                )
                logger.debug(f"[DFV] Chunk {chunk_num}/{total_chunks} processado")
        
        logger.info(f"[DFV] Limpeza de dados concluída")
        return df
    
    def _filter_valid_rows(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        """
        Filtra linhas válidas (CEP e fachada não vazios).
        
        Args:
            df: DataFrame com dados limpos
            
        Returns:
            Tupla (DataFrame válido, número de linhas inválidas)
        """
        mask_valido = (df['cep_limpo'].str.len() > 0) & (df['fachada_limpa'].str.len() > 0)
        df_valido = df[mask_valido].copy()
        erros_count = (~mask_valido).sum()
        
        logger.info(
            f"[DFV] Linhas válidas: {len(df_valido)}/{len(df)} "
            f"(inválidas: {erros_count})"
        )
        
        return df_valido, int(erros_count)
    
    def _get_unique_pairs(self, df: pd.DataFrame) -> Set[Tuple[str, str]]:
        """
        Extrai pares únicos de (CEP, fachada).
        
        Args:
            df: DataFrame válido
            
        Returns:
            Set de tuplas (CEP, fachada)
        """
        logger.info("[DFV] Extraindo pares únicos (CEP, fachada)...")
        
        # Usar drop_duplicates para eficiência
        df_pares = df[['cep_limpo', 'fachada_limpa']].drop_duplicates()
        cep_fachada_set = set(
            zip(df_pares['cep_limpo'], df_pares['fachada_limpa'])
        )
        
        logger.info(f"[DFV] {len(cep_fachada_set)} pares únicos extraídos")
        return cep_fachada_set
    
    def _prepare_dfv_objects(
        self, 
        df: pd.DataFrame
    ) -> Tuple[List[DFV], int]:
        """
        Prepara objetos DFV a partir do DataFrame.
        
        Args:
            df: DataFrame válido
            
        Returns:
            Tupla (lista de objetos DFV, número de erros)
        """
        logger.info(f"[DFV] Preparando objetos DFV para {len(df)} registros...")
        
        registros_para_criar = []
        erros_count = 0
        erros_detalhados = []
        
        total_chunks = (len(df) + self.CHUNK_SIZE_PREPARATION - 1) // self.CHUNK_SIZE_PREPARATION
        
        processed_in_chunk = 0
        
        for chunk_idx in range(0, len(df), self.CHUNK_SIZE_PREPARATION):
            chunk_num = (chunk_idx // self.CHUNK_SIZE_PREPARATION) + 1
            chunk_df = df.iloc[chunk_idx:chunk_idx + self.CHUNK_SIZE_PREPARATION]
            
            logger.debug(
                f"[DFV] Processando chunk {chunk_num}/{total_chunks} "
                f"({len(chunk_df)} registros)..."
            )
            
            # Processar linha por linha com atualização de progresso mais frequente
            for row_idx, row_tuple in enumerate(chunk_df.itertuples(index=False)):
                try:
                    # Extrair valores
                    cep_val = getattr(row_tuple, 'cep_limpo', '')
                    fachada_val = getattr(row_tuple, 'fachada_limpa', '')
                    
                    # Extrair campos opcionais
                    optional_fields = {}
                    for col in self.OPTIONAL_COLUMNS:
                        if hasattr(row_tuple, col):
                            val = getattr(row_tuple, col, None)
                            if val and not pd.isna(val):
                                optional_fields[col.lower()] = str(val).strip()
                    
                    # Criar objeto DFV
                    obj = DFV(
                        cep=cep_val,
                        num_fachada=fachada_val,
                        **optional_fields
                    )
                    registros_para_criar.append(obj)
                    
                    processed_in_chunk += 1
                    total_processed_so_far = chunk_idx + processed_in_chunk
                    
                    # Atualizar progresso a cada N registros para mostrar que está progredindo
                    if processed_in_chunk % self.PREPARATION_PROGRESS_INTERVAL == 0:
                        self._update_progress(
                            total_processed=total_processed_so_far,
                            errors=erros_count,
                            message=f'Preparando objetos... {chunk_num}/{total_chunks} chunks ({total_processed_so_far}/{len(df)} registros)'
                        )
                        logger.debug(
                            f"[DFV] Chunk {chunk_num}/{total_chunks}: "
                            f"{processed_in_chunk}/{len(chunk_df)} registros processados no chunk, "
                            f"total: {len(registros_para_criar)} objetos preparados"
                        )
                    
                except Exception as e:
                    erros_count += 1
                    if len(erros_detalhados) < 10:
                        erros_detalhados.append(f"Erro ao criar objeto: {str(e)}")
                    logger.warning(f"[DFV] Erro ao criar objeto DFV: {e}")
            
            # Resetar contador para próximo chunk
            processed_in_chunk = 0
            
            # Atualizar progresso ao final de cada chunk
            total_processed_so_far = min(chunk_idx + self.CHUNK_SIZE_PREPARATION, len(df))
            self._update_progress(
                total_processed=total_processed_so_far,
                errors=erros_count,
                message=f'Preparando objetos... {chunk_num}/{total_chunks} chunks ({total_processed_so_far}/{len(df)} registros)'
            )
            
            logger.info(
                f"[DFV] Chunk {chunk_num}/{total_chunks} concluído. "
                f"Total de objetos preparados: {len(registros_para_criar)}"
            )
        
        logger.info(
            f"[DFV] Preparação concluída: {len(registros_para_criar)} objetos, "
            f"{erros_count} erros"
        )
        
        return registros_para_criar, erros_count
    
    def _remove_duplicates(self, cep_fachada_set: Set[Tuple[str, str]]) -> int:
        """
        Remove registros duplicados do banco de dados.
        
        Otimizado para usar sub-lotes menores e evitar queries OR gigantes
        que podem causar travamentos ou lentidão.
        
        Args:
            cep_fachada_set: Set de pares (CEP, fachada) únicos
            
        Returns:
            Número de registros removidos
        """
        total_no_banco = DFV.objects.count()
        
        if total_no_banco == 0:
            logger.info("[DFV] Banco vazio - pulando remoção de duplicados")
            return 0
        
        logger.info(
            f"[DFV] Iniciando remoção de duplicados. "
            f"Total no banco: {total_no_banco}, "
            f"Pares a verificar: {len(cep_fachada_set)}"
        )
        
        cep_fachada_list = list(cep_fachada_set)
        # Reduzir ainda mais o tamanho do sub-lote para evitar queries OR muito grandes
        # 100 pares por vez é mais seguro e evita queries OR gigantes
        sub_batch_size = 100  # Reduzido de 500 para 100 para evitar travamentos
        total_lotes = (len(cep_fachada_list) + self.BATCH_SIZE_DELETE - 1) // self.BATCH_SIZE_DELETE
        registros_removidos = 0
        
        # Atualizar status inicial
        self._update_progress(
            message=f'Removendo duplicados... 0/{total_lotes} lotes (0 removidos)'
        )
        
        for i in range(0, len(cep_fachada_list), self.BATCH_SIZE_DELETE):
            lote_num = (i // self.BATCH_SIZE_DELETE) + 1
            batch_cep_fachada = cep_fachada_list[i:i + self.BATCH_SIZE_DELETE]
            
            logger.info(
                f"[DFV] === INICIANDO LOTE {lote_num}/{total_lotes} === "
                f"({len(batch_cep_fachada)} pares, {len(batch_cep_fachada) // sub_batch_size} sub-lotes)"
            )
            
            # Atualizar progresso antes de processar o lote
            self._update_progress(
                message=f'Removendo duplicados... {lote_num}/{total_lotes} lotes ({registros_removidos} removidos)'
            )
            
            # Postgres: usar tabela temporária por sub-lote para reduzir locks
            if connection.vendor == 'postgresql' and execute_values:
                try:
                    table_name = DFV._meta.db_table
                    sub_lote_num = 0
                    for j in range(0, len(batch_cep_fachada), sub_batch_size):
                        sub_lote_num += 1
                        sub_batch = batch_cep_fachada[j:j + sub_batch_size]

                        tamanhos_sub = [len(sub_batch), 50, 20, 10]
                        for tentativa in range(1, 4):
                            try:
                                for tamanho in tamanhos_sub:
                                    partes = [
                                        sub_batch[i:i + tamanho]
                                        for i in range(0, len(sub_batch), tamanho)
                                    ]
                                    for parte in partes:
                                        with transaction.atomic():
                                            with connection.cursor() as cursor:
                                                cursor.execute("SET LOCAL statement_timeout = '60000ms'")
                                                cursor.execute(
                                                    """
                                                    CREATE TEMP TABLE IF NOT EXISTS dfv_dups_tmp (
                                                        cep text,
                                                        num_fachada text
                                                    ) ON COMMIT DROP
                                                    """
                                                )
                                                cursor.execute("TRUNCATE TABLE dfv_dups_tmp")
                                                execute_values(
                                                    cursor,
                                                    "INSERT INTO dfv_dups_tmp (cep, num_fachada) VALUES %s",
                                                    parte,
                                                    page_size=200
                                                )
                                                cursor.execute(
                                                    f"""
                                                    DELETE FROM {table_name} t
                                                    USING dfv_dups_tmp d
                                                    WHERE t.cep = d.cep AND t.num_fachada = d.num_fachada
                                                    """
                                                )
                                                count_deleted = cursor.rowcount or 0
                                                registros_removidos += count_deleted
                                    # se chegou aqui, deu certo com esse tamanho
                                    break
                                logger.debug(
                                    f"[DFV] Lote {lote_num}/{total_lotes}, sub-lote {sub_lote_num}: "
                                    f"deletados {count_deleted} registros (total: {registros_removidos})"
                                )
                                self._update_progress(
                                    message=f'Removendo duplicados... {lote_num}/{total_lotes} lotes ({registros_removidos} removidos)'
                                )
                                break
                            except Exception as e:
                                logger.warning(
                                    f"[DFV] Erro no delete (tentativa {tentativa}/3) "
                                    f"lote {lote_num}, sub-lote {sub_lote_num}: {e}"
                                )
                                if tentativa == 3:
                                    raise

                    logger.info(
                        f"[DFV] === LOTE {lote_num}/{total_lotes} CONCLUÍDO === "
                        f"Total removido até agora: {registros_removidos}"
                    )
                    continue
                except Exception as e:
                    logger.error(
                        f"[DFV] ERRO ao remover duplicados (temp table) no lote {lote_num}: {e}",
                        exc_info=True
                    )
                    # fallback para sub-lotes abaixo

            # Processar em sub-lotes menores para melhor performance (fallback)
            sub_lote_num = 0
            for j in range(0, len(batch_cep_fachada), sub_batch_size):
                sub_lote_num += 1
                sub_batch = batch_cep_fachada[j:j + sub_batch_size]
                
                logger.debug(
                    f"[DFV] Lote {lote_num}/{total_lotes}, sub-lote {sub_lote_num}: "
                    f"processando {len(sub_batch)} pares..."
                )
                
                try:
                    count_deleted = 0
                    if connection.vendor == 'postgresql' and execute_values:
                        # Postgres: DELETE usando VALUES para evitar IN grande e reduzir locks
                        table_name = DFV._meta.db_table
                        with connection.cursor() as cursor:
                            sql = f"""
                                DELETE FROM {table_name} t
                                USING (VALUES %s) AS v(cep, num_fachada)
                                WHERE t.cep = v.cep AND t.num_fachada = v.num_fachada
                            """
                            execute_values(cursor, sql, sub_batch, page_size=100)
                            count_deleted = cursor.rowcount
                    else:
                        # Fallback para outros bancos: manter estratégia de IDs
                        ids_para_deletar = []
                        micro_batch_size = 50
                        for k in range(0, len(sub_batch), micro_batch_size):
                            micro_batch = sub_batch[k:k + micro_batch_size]
                            q_objects = Q()
                            for cep, fachada in micro_batch:
                                q_objects |= Q(cep=cep, num_fachada=fachada)
                            if q_objects:
                                ids = list(DFV.objects.filter(q_objects).values_list('id', flat=True))
                                ids_para_deletar.extend(ids)
                        if ids_para_deletar:
                            delete_chunk_size = 1000
                            for delete_chunk_idx in range(0, len(ids_para_deletar), delete_chunk_size):
                                delete_chunk = ids_para_deletar[delete_chunk_idx:delete_chunk_idx + delete_chunk_size]
                                with transaction.atomic():
                                    count_deleted += DFV.objects.filter(id__in=delete_chunk).delete()[0]

                    if count_deleted:
                        registros_removidos += count_deleted

                    logger.debug(
                        f"[DFV] Lote {lote_num}/{total_lotes}, sub-lote {sub_lote_num}: "
                        f"deletados {count_deleted} registros (total: {registros_removidos})"
                    )
                    self._update_progress(
                        message=f'Removendo duplicados... {lote_num}/{total_lotes} lotes ({registros_removidos} removidos)'
                    )
                
                except Exception as e:
                    logger.error(
                        f"[DFV] ERRO ao remover duplicados no lote {lote_num}, "
                        f"sub-lote {sub_lote_num}: {e}",
                        exc_info=True
                    )
                    
                    # Tentar remoção individual como fallback para este sub-lote
                    logger.warning(
                        f"[DFV] Tentando remoção individual para sub-lote {sub_lote_num} com erro..."
                    )
                    for cep, fachada in sub_batch:
                        try:
                            with transaction.atomic():
                                deleted = DFV.objects.filter(cep=cep, num_fachada=fachada).delete()[0]
                                registros_removidos += deleted
                        except Exception as e2:
                            logger.warning(
                                f"[DFV] Erro ao remover individual CEP={cep}, fachada={fachada}: {e2}"
                            )
            
            # Atualizar progresso após processar o lote completo
            self._update_progress(
                message=f'Removendo duplicados... {lote_num}/{total_lotes} lotes ({registros_removidos} removidos)'
            )
            
            logger.info(
                f"[DFV] === LOTE {lote_num}/{total_lotes} CONCLUÍDO === "
                f"Total removido até agora: {registros_removidos}"
            )
        
        logger.info(f"[DFV] Remoção de duplicados concluída: {registros_removidos} removidos")
        return registros_removidos
    
    def _create_records(
        self, 
        registros_para_criar: List[DFV]
    ) -> Tuple[int, int]:
        """
        Cria registros no banco de dados em lotes.
        
        Args:
            registros_para_criar: Lista de objetos DFV para criar
            
        Returns:
            Tupla (número de sucessos, número de erros)
        """
        logger.info(f"[DFV] Iniciando criação de {len(registros_para_criar)} registros...")
        
        sucesso_count = 0
        erros_count = 0
        erros_detalhados = []
        
        total_batches = (len(registros_para_criar) + self.BATCH_SIZE_CREATE - 1) // self.BATCH_SIZE_CREATE
        
        self._update_progress(
            message=f'Criando registros... 0/{total_batches} lotes'
        )
        
        for i in range(0, len(registros_para_criar), self.BATCH_SIZE_CREATE):
            batch_num = (i // self.BATCH_SIZE_CREATE) + 1
            batch = registros_para_criar[i:i + self.BATCH_SIZE_CREATE]
            
            try:
                # Postgres: usar INSERT em massa com execute_values (bem mais rápido)
                if connection.vendor == 'postgresql' and execute_values:
                    now = timezone.now()
                    table_name = DFV._meta.db_table
                    columns = (
                        'uf', 'municipio', 'logradouro', 'num_fachada', 'complemento',
                        'cep', 'bairro', 'tipo_viabilidade', 'tipo_rede', 'celula',
                        'nome_cdo', 'data_importacao'
                    )
                    values = [
                        (
                            obj.uf, obj.municipio, obj.logradouro, obj.num_fachada, obj.complemento,
                            obj.cep, obj.bairro, obj.tipo_viabilidade, obj.tipo_rede, obj.celula,
                            obj.nome_cdo, now
                        )
                        for obj in batch
                    ]

                    def _sanitize_copy_value(val):
                        if val is None:
                            return r'\N'
                        text = str(val)
                        text = text.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
                        return text

                    def inserir_com_copy(valores):
                        if not valores:
                            return
                        data = StringIO()
                        for row in valores:
                            data.write('\t'.join(_sanitize_copy_value(v) for v in row))
                            data.write('\n')
                        data.seek(0)
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                cursor.execute("SET LOCAL statement_timeout = '60000ms'")
                                sql = f"COPY {table_name} ({', '.join(columns)}) FROM STDIN WITH (FORMAT text)"
                                cursor.copy_expert(sql, data)

                    def inserir_com_retry(valores, page_size, tentativas=3):
                        if not valores:
                            return
                        for tentativa in range(1, tentativas + 1):
                            try:
                                with transaction.atomic():
                                    with connection.cursor() as cursor:
                                        cursor.execute("SET LOCAL statement_timeout = '60000ms'")
                                        sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES %s"
                                        execute_values(cursor, sql, valores, page_size=page_size)
                                return
                            except Exception as e:
                                logger.warning(
                                    f"[DFV] Erro no insert em massa (tentativa {tentativa}/{tentativas}): {e}"
                                )
                                if tentativa == tentativas:
                                    raise

                    try:
                        # Inserir em sub-lotes para progresso mais frequente e menor risco de travamento
                        sub_size = min(self.BATCH_SIZE_CREATE_SUB, len(values))
                        for k in range(0, len(values), sub_size):
                            sub_values = values[k:k + sub_size]
                            sub_objs = batch[k:k + sub_size]
                            try:
                                try:
                                    inserir_com_copy(sub_values)
                                except Exception as e:
                                    logger.warning(f"[DFV] COPY falhou, fallback para INSERT em massa: {e}")
                                    inserir_com_retry(sub_values, page_size=min(sub_size, 500))
                                sucesso_count += len(sub_values)
                            except Exception as e:
                                # Fallback progressivo para o sub-lote com erro
                                logger.warning(
                                    f"[DFV] Falha no sub-lote (size={len(sub_values)}): {e}. "
                                    f"Tentando tamanhos menores."
                                )
                                sub_chunk_sizes = [200, 50, 10]
                                handled = False
                                for sub_chunk_size in sub_chunk_sizes:
                                    try:
                                        for m in range(0, len(sub_values), sub_chunk_size):
                                            sub_chunk_vals = sub_values[m:m + sub_chunk_size]
                                            inserir_com_retry(sub_chunk_vals, page_size=min(sub_chunk_size, len(sub_chunk_vals)), tentativas=2)
                                            sucesso_count += len(sub_chunk_vals)
                                        handled = True
                                        break
                                    except Exception as e_sub:
                                        logger.warning(
                                            f"[DFV] Falha ao inserir sub-lote (size={sub_chunk_size}): {e_sub}. "
                                            f"Tentando tamanho menor."
                                        )
                                if not handled:
                                    # Último recurso: salvar individualmente
                                    for obj in sub_objs:
                                        try:
                                            with transaction.atomic():
                                                obj.save()
                                            sucesso_count += 1
                                        except Exception as e_ind:
                                            erros_count += 1
                                            if len(erros_detalhados) < 100:
                                                erros_detalhados.append(
                                                    f"CEP={obj.cep} fachada={obj.num_fachada}: {str(e_ind)}"
                                                )
                            # Atualizar progresso a cada sub-lote
                            self._update_progress(
                                success=sucesso_count,
                                errors=erros_count,
                                message=f'Criando registros... {batch_num}/{total_batches} lotes ({sucesso_count} criados)'
                            )
                    except Exception:
                        # Fallback: dividir o lote e tentar novamente em partes menores
                        logger.warning(
                            f"[DFV] Dividindo lote {batch_num} para inserção menor devido a falha."
                        )
                        sub_chunk_size = 200
                        for k in range(0, len(values), sub_chunk_size):
                            sub_values = values[k:k + sub_chunk_size]
                            try:
                                inserir_com_retry(sub_values, page_size=200, tentativas=2)
                                sucesso_count += len(sub_values)
                            except Exception as e:
                                erros_count += len(sub_values)
                                if len(erros_detalhados) < 100:
                                    erros_detalhados.append(
                                        f"Falha insert em massa (lote {batch_num}): {str(e)}"
                                    )
                else:
                    # Fallback: usar bulk_create padrão
                    with transaction.atomic():
                        DFV.objects.bulk_create(batch, ignore_conflicts=False)
                    sucesso_count += len(batch)
                
                # Atualizar progresso
                self._update_progress(
                    success=sucesso_count,
                    message=f'Criando registros... {batch_num}/{total_batches} lotes ({sucesso_count} criados)'
                )
                
                if batch_num % self.PROGRESS_UPDATE_INTERVAL == 0:
                    logger.debug(
                        f"[DFV] Lote {batch_num}/{total_batches}: "
                        f"{sucesso_count}/{len(registros_para_criar)} registros criados"
                    )
                    
            except Exception as e:
                logger.warning(
                    f"[DFV] Erro no bulk_create (lote {batch_num}): {e}. "
                    f"Tentando inserção individual..."
                )
                
                # Fallback: inserir um por um
                for obj in batch:
                    try:
                        with transaction.atomic():
                            obj.save()
                        sucesso_count += 1
                    except Exception as e2:
                        erros_count += 1
                        if len(erros_detalhados) < 100:
                            erros_detalhados.append(
                                f"CEP={obj.cep} fachada={obj.num_fachada}: {str(e2)}"
                            )
                
                # Atualizar progresso mesmo com erros
                self._update_progress(
                    success=sucesso_count,
                    errors=erros_count,
                    message=f'Criando registros... {batch_num}/{total_batches} lotes ({sucesso_count} criados, {erros_count} erros)'
                )
        
        logger.info(
            f"[DFV] Criação concluída: {sucesso_count} sucessos, {erros_count} erros"
        )
        
        return sucesso_count, erros_count
    
    def _finalize_log(
        self,
        sucesso_count: int,
        erros_count: int,
        registros_removidos: int,
        erros_detalhados: List[str]
    ) -> None:
        """
        Finaliza o log de importação com os resultados.
        
        Args:
            sucesso_count: Número de registros criados com sucesso
            erros_count: Número de erros
            registros_removidos: Número de duplicados removidos
            erros_detalhados: Lista de mensagens de erro detalhadas
        """
        finalizado_em = timezone.now()
        
        # Calcular duração
        if self.log and self.log.iniciado_em:
            delta = finalizado_em - self.log.iniciado_em
            duracao_segundos = int(delta.total_seconds())
        else:
            duracao_segundos = 0
        
        # Preparar mensagens
        mensagem_erro_final = None
        if erros_detalhados:
            mensagem_erro_final = '\n'.join(erros_detalhados[:100])
            if len(erros_detalhados) > 100:
                mensagem_erro_final += f"\n... e mais {len(erros_detalhados) - 100} erros"
        
        # Determinar status final
        if erros_count > 0 and sucesso_count == 0:
            status_final = 'ERRO'
            mensagem_final = None
            if mensagem_erro_final:
                mensagem_erro_final += '\nNenhum registro foi importado com sucesso.'
        elif erros_count > 0:
            status_final = 'PARCIAL'
            mensagem_final = (
                f'Importação concluída parcialmente: {sucesso_count} registros importados '
                f'com sucesso, {erros_count} erros. {registros_removidos} registros duplicados removidos.'
            )
        else:
            status_final = 'SUCESSO'
            mensagem_final = (
                f'Importação concluída com sucesso: {sucesso_count} registros importados. '
                f'{registros_removidos} registros duplicados removidos e atualizados.'
            )
        
        # Atualizar log
        update_data = {
            'finalizado_em': finalizado_em,
            'duracao_segundos': duracao_segundos,
            'sucesso': sucesso_count,
            'erros': erros_count,
            'status': status_final,
        }
        
        if mensagem_final:
            update_data['mensagem'] = mensagem_final
        if mensagem_erro_final:
            update_data['mensagem_erro'] = mensagem_erro_final
        
        LogImportacaoDFV.objects.filter(id=self.log_id).update(**update_data)
        
        logger.info(
            f"[DFV] Importação finalizada - Log {self.log_id}: "
            f"status={status_final}, sucesso={sucesso_count}, "
            f"erros={erros_count}, removidos={registros_removidos}, "
            f"duração={duracao_segundos}s"
        )
    
    def process(self, arquivo_bytes: Optional[bytes], arquivo_nome: str, arquivo_path: Optional[str] = None) -> Dict:
        """
        Processa a importação completa do arquivo DFV.
        
        Este é o método principal que orquestra todo o processo:
        1. Validação do arquivo
        2. Leitura e normalização
        3. Limpeza de dados
        4. Remoção de duplicados
        5. Criação de registros
        
        Args:
            arquivo_bytes: Conteúdo do arquivo em bytes
            arquivo_nome: Nome do arquivo
            
        Returns:
            Dicionário com resultados da importação
            
        Raises:
            DFVImportError: Em caso de erro crítico
        """
        inicio = timezone.now()
        erros_detalhados = []
        
        lock_acquired = False
        try:
            # Atualizar status inicial
            LogImportacaoDFV.objects.filter(id=self.log_id).update(status='PROCESSANDO')
            logger.info(f"[DFV] Iniciando processamento - Log ID: {self.log_id}")
            
            # Garantir execução exclusiva da importação (Postgres)
            self._acquire_db_lock()
            lock_acquired = True
            
            # ETAPA 1: Validação
            self._validate_file(arquivo_bytes, arquivo_nome, arquivo_path)
            
            # ETAPA 2: Leitura do CSV
            self._update_progress(message='Lendo arquivo CSV...')
            df = self._read_csv(arquivo_bytes, arquivo_path)
            
            # ETAPA 3: Normalização de colunas
            df = self._normalize_columns(df)
            self._validate_columns(df)
            
            # Atualizar total de registros
            total_registros = len(df)
            LogImportacaoDFV.objects.filter(id=self.log_id).update(
                total_registros=total_registros,
                total_processadas=0,
                sucesso=0,
                tamanho_arquivo=len(arquivo_bytes) if arquivo_bytes else (os.path.getsize(arquivo_path) if arquivo_path else 0)
            )
            logger.info(f"[DFV] Total de registros no arquivo: {total_registros}")
            
            # ETAPA 4: Limpeza de dados
            self._update_progress(message='Limpando e normalizando dados...')
            df = self._clean_data(df)
            
            # ETAPA 5: Filtragem de linhas válidas
            df_valido, erros_invalidos = self._filter_valid_rows(df)
            erros_detalhados.extend(
                [f"Linha inválida: CEP ou fachada vazio"] * min(erros_invalidos, 10)
            )
            
            # Liberar memória do DataFrame original
            del df
            
            # ETAPA 6: Extração de pares únicos
            self._update_progress(message='Extraindo pares únicos...')
            cep_fachada_set = self._get_unique_pairs(df_valido)
            
            # ETAPA 7: Preparação de objetos
            self._update_progress(message='Preparando objetos DFV...')
            registros_para_criar, erros_preparacao = self._prepare_dfv_objects(df_valido)
            erros_detalhados.extend(
                [f"Erro ao preparar objeto"] * min(erros_preparacao, 10)
            )
            
            # Liberar memória do DataFrame válido
            del df_valido
            
            # ETAPA 8: Remoção de duplicados
            self._update_progress(message='Removendo registros duplicados...')
            registros_removidos = self._remove_duplicates(cep_fachada_set)
            
            # Liberar memória do set
            del cep_fachada_set
            
            # ETAPA 9: Criação de registros
            self._update_progress(message='Criando registros no banco de dados...')
            sucesso_count, erros_criacao = self._create_records(registros_para_criar)
            
            # Liberar memória da lista de objetos
            del registros_para_criar
            
            # ETAPA 10: Finalização
            self._finalize_log(
                sucesso_count=sucesso_count,
                erros_count=erros_invalidos + erros_preparacao + erros_criacao,
                registros_removidos=registros_removidos,
                erros_detalhados=erros_detalhados
            )
            
            return {
                'success': True,
                'log_id': self.log_id,
                'sucesso': sucesso_count,
                'erros': erros_invalidos + erros_preparacao + erros_criacao,
                'removidos': registros_removidos
            }
            
        except DFVImportError as e:
            logger.error(f"[DFV] Erro de importação: {e}", exc_info=True)
            self._handle_error(str(e))
            raise
            
        except Exception as e:
            logger.error(f"[DFV] Erro crítico inesperado: {e}", exc_info=True)
            self._handle_error(f"Erro fatal: {str(e)}")
            raise DFVImportError(f"Erro crítico: {str(e)}")
        finally:
            if lock_acquired:
                self._release_db_lock()
    
    def _handle_error(self, error_message: str) -> None:
        """
        Trata erros atualizando o log de importação.
        
        Args:
            error_message: Mensagem de erro
        """
        try:
            LogImportacaoDFV.objects.filter(id=self.log_id).update(
                status='ERRO',
                mensagem_erro=error_message,
                finalizado_em=timezone.now()
            )
        except Exception as e:
            logger.error(f"[DFV] Erro ao atualizar log de erro: {e}", exc_info=True)
