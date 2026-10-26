#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analisador de Logs SAS
======================

Este módulo contém a lógica principal para analisar arquivos de log SAS,
extrair informações relevantes e persistir esses dados em um banco de dados Databricks SQL.

Funcionalidades:
        - Extração de métricas de performance (CPU, memória, tempo de execução)
        - Classificação de tipos de processo (ETL, analítico, modelo)
        - Detecção de informações de sessão e usuário
        - Identificação de mensagens de erro e warning
        - Detecção de queries custosas
        - Extração de objetos de banco de dados (tabelas, libnames, arquivos)

Configuração (.env):
    DATABRICKS_SERVER_HOSTNAME=seu-workspace.cloud.databricks.com
    DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/seu-warehouse-id
    DATABRICKS_CATALOG=bv_dev_db (opcional, padrão)
    DATABRICKS_SCHEMA=bv_migration_sas (opcional, padrão)

Tabela de destino:
    {catalog}.{schema}.log_base_final

Uso:
    from sas_log_analyzer import SASLogAnalyzer
    
    analyzer = SASLogAnalyzer(db_config, oauth_lock=None)
    analyzer.connect_database()
    result = analyzer.analyze_log_file('log_file.log')
    analyzer.save_to_database('log_file.log', result)
"""

import os
import re
import json
import time
import random
from databricks import sql
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import glob
from dotenv import load_dotenv
from regex_patterns import (
    PERFORMANCE_PATTERNS,
    DATABASE_OBJECT_PATTERNS,
    PROCESS_TYPE_PATTERNS,
    AREA_PATTERNS,
    SESSION_INFO_PATTERNS,
    ERROR_PATTERNS,
    EXPENSIVE_QUERY_PATTERNS,
)


class SASLogAnalyzer:
    """
    Analisador de Logs SAS para Databricks
    
    Esta classe fornece funcionalidades completas para análise de logs SAS,
    incluindo extração de métricas, detecção de dados sensíveis, identificação
    de blocos de código e persistência em Databricks SQL.
    
    Args:
        db_config: Dicionário com configuração do Databricks:
            - server_hostname: Hostname do workspace Databricks
            - http_path: HTTP path do SQL Warehouse
            - catalog: Catalog (opcional, padrão: bv_dev_db)
            - schema: Schema (opcional, padrão: bv_migration_sas)
            - full_table_name: Nome completo da tabela (catalog.schema.table)
        oauth_lock: Lock opcional para autenticação OAuth em processamento paralelo
    """
    
    def __init__(self, db_config: Dict[str, str], oauth_lock=None):
        """
        Inicializa o analisador com configuração do Databricks.
        
        Args:
            db_config: Configuração do Databricks (server_hostname, http_path, etc.)
            oauth_lock: Lock opcional para OAuth em processamento paralelo
        """
        self.db_config = db_config
        self.conn = None
        self.oauth_lock = oauth_lock  # Lock para OAuth em processamento paralelo
        
        # Padrões importados do módulo centralizado
        self.performance_patterns = PERFORMANCE_PATTERNS
    
    def connect_database(self):
        """
        Conecta ao Databricks SQL via OAuth U2M (Browser Login).
        
        Abre o navegador para autenticação OAuth e estabelece conexão com o Databricks.
        Usa lock opcional para evitar múltiplas abas do navegador em processamento paralelo.
        
        Returns:
            bool: True se a conexão foi estabelecida com sucesso, False caso contrário
        """
        try:
            # Usa lock se disponível (para processamento paralelo)
            if self.oauth_lock:
                self.oauth_lock.acquire()
            
            try:
                host = self.db_config.get('server_hostname')
                http_path = self.db_config.get('http_path')
                
                if not host or not http_path:
                    raise ValueError("server_hostname e http_path são obrigatórios no db_config")
                
                # Conecta usando OAuth U2M
                self.conn = sql.connect(
                    server_hostname=host,
                    http_path=http_path,
                    auth_type="databricks-oauth"
                )
                print("✅ Conexão com Databricks estabelecida com sucesso!")
                return True
            finally:
                if self.oauth_lock:
                    self.oauth_lock.release()
        except Exception as e:
            print(f"❌ Erro ao conectar com Databricks: {e}")
            if self.oauth_lock:
                self.oauth_lock.release()
            return False
    
    def _is_delta_concurrency_error(self, error: Exception) -> bool:
        """
        Verifica se o erro é de concorrência Delta Lake.
        
        Args:
            error: Exceção capturada
            
        Returns:
            bool: True se for erro de concorrência Delta Lake, False caso contrário
        """
        error_str = str(error).upper()
        return 'DELTA_METADATA_CHANGED' in error_str or 'METADATACHANGEDEXCEPTION' in error_str
    
    def _retry_with_backoff(self, func, max_retries=5, initial_delay=0.5):
        """
        Executa uma função com retry e exponential backoff.
        
        Usado para lidar com erros de concorrência Delta Lake, tentando novamente
        com delays crescentes e jitter aleatório.
        
        Args:
            func: Função a ser executada (sem argumentos)
            max_retries: Número máximo de tentativas (padrão: 5)
            initial_delay: Delay inicial em segundos (padrão: 0.5)
            
        Returns:
            Resultado da função se bem-sucedida
            
        Raises:
            Exception: Se todas as tentativas falharem
        """
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                if not self._is_delta_concurrency_error(e):
                    raise
                # Exponential backoff com jitter
                jitter = random.uniform(0, delay * 0.1)
                sleep_time = delay + jitter
                print(f"      ⚠️  Retry {attempt + 1}/{max_retries} em {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                delay *= 2
    
    def extract_session_info(self, line: str) -> Tuple[str, str, str, str, str]:
        """Extrai informações da sessão de uma linha de log"""
        # Padrão: timestamp level [session] :user_id - content
        # Exemplo: 2025-09-22T14:12:36,129 INFO  [00000003] :victoria.castro - NOTE: Unable...
        # user_id = "victoria.castro" (sem o :)
        # session_id = "00000003" (sem os [])
        pattern = SESSION_INFO_PATTERNS['full_pattern']
        match = re.match(pattern, line)
        
        if match:
            timestamp_str = match.group(1).replace(',', '.')  # Corrige formato timestamp
            try:
                # Converte para formato TIMESTAMP do Databricks
                from datetime import datetime
                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d %H:%M:%S.%f')
            except:
                timestamp = timestamp_str
            level = match.group(2)  # log_level (INFO, ERROR, WARNING, etc)
            session_id = match.group(3)  # session_id sem colchetes (00000003)
            user_id = match.group(4)  # user_id sem dois pontos (victoria.castro)
            content = match.group(5)
            return timestamp, level, session_id, user_id, content
        
        # Se não encontrou o padrão completo, tenta padrões alternativos
        # Padrão sem user_id: timestamp level [session] - content
        pattern2 = SESSION_INFO_PATTERNS['without_user']
        match2 = re.match(pattern2, line)
        if match2:
            timestamp_str = match2.group(1).replace(',', '.')
            try:
                from datetime import datetime
                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d %H:%M:%S.%f')
            except:
                timestamp = timestamp_str
            level = match2.group(2)
            session_id = match2.group(3)
            user_id = None
            content = match2.group(4)
            return timestamp, level, session_id, user_id, content
        
        return None, None, None, None, line
    
    def extract_area(self, line: str) -> Optional[str]:
        """Extrai área do log (ex: WORK, SASHELP, etc.)"""
        # Procura por referências a áreas comuns
        for pattern in AREA_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                if match.lastindex >= 1:
                    return match.group(1).strip() if match.group(1) else None
                elif '.' in match.group(0):
                    return match.group(0).replace('.', '').strip()
        
        return None
    
    def extract_error_message(self, line: str, log_level: str) -> Optional[str]:
        """Extrai mensagem de erro"""
        if log_level and log_level.upper() in ['ERROR', 'WARNING']:
            # Remove prefixos comuns (ERROR:, WARNING:, etc.)
            msg = re.sub(ERROR_PATTERNS['error_prefix'], '', line, flags=re.IGNORECASE)
            msg = msg.strip()
            if msg and len(msg) > 0:
                return msg[:1000]  # Limita tamanho
        return None

    def determine_type_process(self, line: str) -> Optional[str]:
        """
        Determina o tipo de processo SAS baseado no conteúdo da linha.
        
        Classifica processos em: ETL, ANALÍTICO, OPERACIONAL ou MODELO baseado
        nos comandos PROC e DATA encontrados.
        
        Args:
            line: Linha de log a ser analisada
            
        Returns:
            Tipo de processo ('ETL', 'ANALÍTICO', 'OPERACIONAL', 'MODELO') ou None
        """
        
        # MODELO: Machine Learning, Modelagem
        if re.search(PROCESS_TYPE_PATTERNS['modelo'], line, re.IGNORECASE):
            return 'MODELO'
        
        # ANALÍTICO: Análise estatística
        if re.search(PROCESS_TYPE_PATTERNS['analitico'], line, re.IGNORECASE):
            return 'ANALÍTICO'
        
        # ETL: SQL, Transformação, Load
        if re.search(PROCESS_TYPE_PATTERNS['etl_sql'], line, re.IGNORECASE):
            return 'ETL'
        if re.search(PROCESS_TYPE_PATTERNS['etl_proc'], line, re.IGNORECASE):
            return 'ETL'
        if re.search(PROCESS_TYPE_PATTERNS['etl_data'], line, re.IGNORECASE) and (re.search(PROCESS_TYPE_PATTERNS['etl_set_merge'], line, re.IGNORECASE)):
            return 'ETL'
        
        # OPERACIONAL: Consultas simples, manutenção
        if re.search(PROCESS_TYPE_PATTERNS['operacional'], line, re.IGNORECASE):
            return 'OPERACIONAL'
        
        return None
    
    def extract_extended_performance_metrics(self, line: str) -> Dict:
        """
        Extrai todas as métricas de performance de uma linha de log
        Usa os padrões centralizados de regex_patterns.py
        """
        metrics = {}
        
        # Real time (prioriza formato MM:SS.ss, depois tenta formato simples)
        real_time_formatted_match = re.search(PERFORMANCE_PATTERNS['real_time_formatted'], line)
        if real_time_formatted_match:
            try:
                minutes = int(real_time_formatted_match.group(1))
                seconds = float(real_time_formatted_match.group(2))
                metrics['real_time'] = minutes * 60 + seconds
            except (ValueError, IndexError):
                pass
        
        if 'real_time' not in metrics:
            real_match = re.search(PERFORMANCE_PATTERNS['real_time'], line)
            if real_match:
                try:
                    # Remove "seconds" se existir e converte para float
                    value_str = real_match.group(1)
                    metrics['real_time'] = float(value_str)
                except (ValueError, IndexError):
                    pass
        
        # User CPU time
        user_cpu_match = re.search(PERFORMANCE_PATTERNS['user_cpu_time'], line)
        if user_cpu_match:
            try:
                metrics['user_cpu_time'] = float(user_cpu_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # System CPU time
        system_cpu_match = re.search(PERFORMANCE_PATTERNS['system_cpu_time'], line)
        if system_cpu_match:
            try:
                metrics['system_cpu_time'] = float(system_cpu_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Memory (captura apenas o número, não o "k" - conforme padrão centralizado)
        memory_match = re.search(PERFORMANCE_PATTERNS['memory'], line)
        if memory_match:
            try:
                # O padrão captura apenas o número, assume que está em KB (mesmo que tenha "k" no log)
                value = float(memory_match.group(1))
                metrics['memory'] = int(value)
            except (ValueError, IndexError):
                pass
        
        # OS Memory (captura apenas o número - conforme padrão centralizado)
        os_memory_match = re.search(PERFORMANCE_PATTERNS['os_memory'], line)
        if os_memory_match:
            try:
                value = float(os_memory_match.group(1))
                metrics['os_memory'] = int(value)
            except (ValueError, IndexError):
                pass
        
        # System time
        system_time_match = re.search(PERFORMANCE_PATTERNS['system_time'], line)
        if system_time_match:
            try:
                metrics['system_time'] = float(system_time_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Page faults
        page_faults_match = re.search(PERFORMANCE_PATTERNS['page_faults'], line)
        if page_faults_match:
            try:
                metrics['page_faults'] = int(page_faults_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Page swaps
        page_swaps_match = re.search(PERFORMANCE_PATTERNS['page_swaps'], line)
        if page_swaps_match:
            try:
                metrics['page_swaps'] = int(page_swaps_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Page reclaims
        page_reclaims_match = re.search(PERFORMANCE_PATTERNS['page_reclaims'], line)
        if page_reclaims_match:
            try:
                metrics['page_reclaims'] = int(page_reclaims_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Step Count
        step_count_match = re.search(PERFORMANCE_PATTERNS['step_count'], line)
        if step_count_match:
            try:
                metrics['step_count'] = int(step_count_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Switch Count
        switch_count_match = re.search(PERFORMANCE_PATTERNS['switch_count'], line)
        if switch_count_match:
            try:
                metrics['switch_count'] = int(switch_count_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Context Switches - ordem importante: involuntary primeiro (mais específico)
        # Involuntary Context Switches (verifica primeiro para evitar conflito)
        invol_switches_match = re.search(PERFORMANCE_PATTERNS['involuntary_context_switches'], line)
        if invol_switches_match:
            try:
                metrics['involuntary_context_switches'] = int(invol_switches_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Voluntary Context Switches (verifica independentemente, mas apenas se não encontrou involuntary na mesma linha)
        # Isso evita que "voluntary" seja capturado incorretamente se a linha contém "involuntary"
        if not invol_switches_match:
            vol_switches_match = re.search(PERFORMANCE_PATTERNS['voluntary_context_switches'], line)
            if vol_switches_match:
                try:
                    metrics['voluntary_context_switches'] = int(vol_switches_match.group(1))
                except (ValueError, IndexError):
                    pass
        
        # Block Input Operations
        block_input_match = re.search(PERFORMANCE_PATTERNS['block_input_operations'], line)
        if block_input_match:
            try:
                metrics['block_input_operations'] = int(block_input_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Block Output Operations
        block_output_match = re.search(PERFORMANCE_PATTERNS['block_output_operations'], line)
        if block_output_match:
            try:
                metrics['block_output_operations'] = int(block_output_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Step Timestamp
        step_timestamp_match = re.search(PERFORMANCE_PATTERNS['step_timestamp'], line)
        if step_timestamp_match:
            try:
                metrics['step_timestamp'] = step_timestamp_match.group(1).strip()
            except (ValueError, IndexError):
                pass
        
        return metrics
    
    def extract_performance_metrics(self, line: str, user_id: str, session_id: str, line_number: int) -> Optional[Dict]:
        """Extrai métricas de performance de uma linha de log - CORRIGIDO"""
        metrics = {}
        
        # Padrões mais flexíveis para CPU e Real Time
        cpu_match = re.search(PERFORMANCE_PATTERNS['cpu_time'], line)
        real_match = re.search(PERFORMANCE_PATTERNS['real_time'], line)
        
        if cpu_match:
            try:
                metrics['cpu_time'] = float(cpu_match.group(1))
            except (ValueError, IndexError):
                pass
        if real_match:
            try:
                metrics['real_time'] = float(real_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Só retorna se encontrou pelo menos CPU ou Real time
        if metrics:
            metrics.update({
                'user_id': user_id,
                'session_id': session_id,
                'line_number': line_number,
                'step_name': f"Step_{line_number}",
                'step_type': 'PERFORMANCE_METRIC'
            })
            return metrics
        
        return None
    
    def extract_database_objects_corrected(self, line: str, user_id: str, line_number: int) -> List[Dict]:
        """Extrai schemas e tabelas utilizados em queries - CORRIGIDO"""
        objects = []
        
        # Valida line_number
        if line_number is None or line_number < 0 or line_number > 1000000:
            return objects
        
        # Padrão para libname (PATH)
        libname_match = re.search(DATABASE_OBJECT_PATTERNS['libname'], line, re.IGNORECASE)
        if libname_match:
            schema_name = libname_match.group(1)
            path_value = libname_match.group(2)
            objects.append({
                'object_type': 'PATH',
                'schema_name': schema_name,
                'table_name': path_value,
                'user_id': user_id,
                'context': line.strip(),
                'line_number': line_number
            })
        
        # Padrões para tabelas (TABLE)
        for pattern in DATABASE_OBJECT_PATTERNS['table_patterns']:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    schema_name = match.group(1)
                    table_name = match.group(2)
                    
                    objects.append({
                        'object_type': 'TABLE',
                        'schema_name': schema_name,
                        'table_name': table_name,
                        'user_id': user_id,
                        'context': line.strip(),
                        'line_number': line_number
                    })
        
        # Padrão para arquivos (FILE)
        for pattern in DATABASE_OBJECT_PATTERNS['file_patterns']:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                file_path = match.group(1)
                objects.append({
                    'object_type': 'FILE',
                    'schema_name': 'file',
                    'table_name': file_path,
                    'user_id': user_id,
                    'context': line.strip(),
                    'line_number': line_number
                })
        
        return objects

    def extract_all_performance_metrics_for_block(self, lines: List[str], end_line: int) -> Dict:
        """
        Extrai todas as métricas de performance de um bloco de código
        Procura nas próximas linhas após o fim do bloco por métricas de performance
        """
        metrics = {}
        
        # Procura nas próximas 30 linhas após o fim do bloco
        lookahead_limit = min(end_line + 30, len(lines))
        
        for j in range(end_line + 1, lookahead_limit):
            if j >= len(lines):
                break
            
            next_line = lines[j]
            _, _, _, _, next_content = self.extract_session_info(next_line)
            
            # Verifica se encontramos início de bloco de métricas
            is_performance_block = re.search(PERFORMANCE_PATTERNS['performance_block_start'], next_content)
            
            if is_performance_block:
                # Consolida métricas das próximas linhas
                consolidated = {}
                for k in range(j + 1, min(j + 20, len(lines))):
                    if k >= len(lines):
                        break
                    metric_line = lines[k]
                    _, _, _, _, metric_content = self.extract_session_info(metric_line)
                    
                    if not metric_content.strip():
                        break
                    
                    # Verifica se é linha de métrica
                    is_metric = re.search(PERFORMANCE_PATTERNS['metric_line'], metric_content)
                    if not is_metric:
                        break
                    
                    # Extrai todas as métricas usando padrões centralizados
                    # Usa a função de extração que já usa os padrões centralizados
                    line_metrics = self.extract_extended_performance_metrics(metric_line)
                    for key, value in line_metrics.items():
                        if key not in consolidated or consolidated[key] is None:
                            consolidated[key] = value
                    
                    # Extrai métricas adicionais específicas usando padrões centralizados
                    # Real time com formato MM:SS.ss (ex: 1:06.49 = 66.49 segundos) - prioridade sobre o padrão simples
                    real_time_formatted_match = re.search(PERFORMANCE_PATTERNS['real_time_formatted'], metric_content)
                    if real_time_formatted_match:
                        try:
                            minutes = int(real_time_formatted_match.group(1))
                            seconds = float(real_time_formatted_match.group(2))
                            consolidated['real_time'] = minutes * 60 + seconds
                        except (ValueError, IndexError):
                            pass
                    
                    # Step Count e Switch Count (pode estar na mesma linha)
                    step_and_switch_match = re.search(PERFORMANCE_PATTERNS['step_and_switch_count'], metric_content)
                    if step_and_switch_match:
                        try:
                            consolidated['step_count'] = int(step_and_switch_match.group(1))
                            consolidated['switch_count'] = int(step_and_switch_match.group(2))
                        except (ValueError, IndexError):
                            pass
                    else:
                        # Tenta Step Count separadamente
                        step_only_match = re.search(PERFORMANCE_PATTERNS['step_count'], metric_content)
                        if step_only_match:
                            try:
                                consolidated['step_count'] = int(step_only_match.group(1))
                            except (ValueError, IndexError):
                                pass
                        # Tenta Switch Count separadamente
                        switch_only_match = re.search(PERFORMANCE_PATTERNS['switch_count'], metric_content)
                        if switch_only_match:
                            try:
                                consolidated['switch_count'] = int(switch_only_match.group(1))
                            except (ValueError, IndexError):
                                pass
                    
                    # Page Reclaims (já extraído em extract_extended_performance_metrics, mas garante aqui)
                    if 'page_reclaims' not in consolidated:
                        page_reclaims_match = re.search(PERFORMANCE_PATTERNS['page_reclaims'], metric_content)
                        if page_reclaims_match:
                            try:
                                consolidated['page_reclaims'] = int(page_reclaims_match.group(1))
                            except (ValueError, IndexError):
                                pass
                    
                    # Context Switches - ordem importante: involuntary primeiro (mais específico)
                    # Involuntary Context Switches (verifica primeiro para evitar conflito)
                    invol_switches_match = re.search(PERFORMANCE_PATTERNS['involuntary_context_switches'], metric_content)
                    if invol_switches_match:
                        try:
                            consolidated['involuntary_context_switches'] = int(invol_switches_match.group(1))
                        except (ValueError, IndexError):
                            pass
                    
                    # Voluntary Context Switches (verifica independentemente, mas apenas se não encontrou involuntary na mesma linha)
                    # Isso evita que "voluntary" seja capturado incorretamente se a linha contém "involuntary"
                    if not invol_switches_match:
                        vol_switches_match = re.search(PERFORMANCE_PATTERNS['voluntary_context_switches'], metric_content)
                        if vol_switches_match:
                            try:
                                consolidated['voluntary_context_switches'] = int(vol_switches_match.group(1))
                            except (ValueError, IndexError):
                                pass
                    
                    # Block Input Operations
                    block_input_match = re.search(PERFORMANCE_PATTERNS['block_input_operations'], metric_content)
                    if block_input_match:
                        try:
                            consolidated['block_input_operations'] = int(block_input_match.group(1))
                        except (ValueError, IndexError):
                            pass
                    
                    # Block Output Operations
                    block_output_match = re.search(PERFORMANCE_PATTERNS['block_output_operations'], metric_content)
                    if block_output_match:
                        try:
                            consolidated['block_output_operations'] = int(block_output_match.group(1))
                        except (ValueError, IndexError):
                            pass
                    
                    # Step Timestamp (já extraído em extract_extended_performance_metrics, mas garante aqui)
                    if 'step_timestamp' not in consolidated:
                        step_timestamp_match = re.search(PERFORMANCE_PATTERNS['step_timestamp'], metric_content)
                        if step_timestamp_match:
                            try:
                                consolidated['step_timestamp'] = step_timestamp_match.group(1).strip()
                            except (ValueError, IndexError):
                                pass
                
                # Retorna as métricas consolidadas
                return consolidated
                
        return metrics

    def detect_expensive_queries(self, lines: List[str]) -> List[Dict]:
        """Detecta queries custosas - CORRIGIDO"""
        expensive_queries = []
        
        # Mantém contexto de user_id
        last_user_id = None
        
        for i, line in enumerate(lines):
            timestamp, level, session_id, user_id, content = self.extract_session_info(line)
            
            # Usa contexto se necessário
            if user_id is None or user_id == 'UNKNOWN':
                user_id = last_user_id
            else:
                last_user_id = user_id
            
            # Padrões para identificar queries custosas
            # Procura por "cpu time" OU "real time" na linha (podem estar em linhas separadas)
            cpu_match = re.search(EXPENSIVE_QUERY_PATTERNS['cpu_time'], line, re.IGNORECASE)
            real_match = re.search(EXPENSIVE_QUERY_PATTERNS['real_time'], line, re.IGNORECASE)
            
            cpu_time = None
            real_time = None
            
            if cpu_match:
                try:
                    cpu_time = float(cpu_match.group(1))
                except (ValueError, IndexError):
                    pass
            if real_match:
                try:
                    real_time = float(real_match.group(1))
                except (ValueError, IndexError):
                    pass
            
            # Se encontrou pelo menos um valor de tempo, verifica se é custoso
            # Busca o outro valor nas linhas próximas (até 2 linhas antes)
            if cpu_time is not None or real_time is not None:
                # Se só tem um, tenta buscar o outro nas linhas adjacentes
                if cpu_time is None and i > 0:
                    # Tenta linha anterior
                    prev_line = lines[i-1] if i > 0 else ""
                    cpu_match_prev = re.search(EXPENSIVE_QUERY_PATTERNS['cpu_time'], prev_line, re.IGNORECASE)
                    if cpu_match_prev:
                        try:
                            cpu_time = float(cpu_match_prev.group(1))
                        except:
                            pass
                
                if real_time is None and i > 0:
                    # Tenta linha anterior
                    prev_line = lines[i-1] if i > 0 else ""
                    real_match_prev = re.search(EXPENSIVE_QUERY_PATTERNS['real_time'], prev_line, re.IGNORECASE)
                    if real_match_prev:
                        try:
                            real_time = float(real_match_prev.group(1))
                        except:
                            pass
                
                # Considera custoso se CPU > 1 segundo ou Real > 5 segundos
                if (cpu_time and cpu_time > 1.0) or (real_time and real_time > 5.0):
                    # Constrói query_text a partir das linhas próximas
                    query_text = content[:500] if content else line[:500]
                    if not query_text.strip() and i > 0:
                        query_text = lines[max(0, i-2):i+1]
                        query_text = ' '.join([l.strip() for l in query_text if l.strip()])[:500]
                    
                    expensive_queries.append({
                        'query_text': query_text,
                        'cpu_time': cpu_time if cpu_time else 0.0,
                        'real_time': real_time if real_time else 0.0,
                        'user_id': user_id if user_id and user_id != 'UNKNOWN' else None,
                        'start_line': max(1, i - 1),  # Inclui linha anterior se necessário
                        'end_line': i + 1,
                        'line_number': i + 1
                    })
            
            # Padrões adicionais para queries custosas
            if 'NOTE:' in line and ('seconds' in line.lower() or 'minutes' in line.lower()):
                time_match = re.search(EXPENSIVE_QUERY_PATTERNS['time_with_unit'], line, re.IGNORECASE)
                if time_match:
                    time_value = float(time_match.group(1))
                    time_unit = time_match.group(2).lower()
                    
                    # Converte para segundos
                    if time_unit.startswith('minute'):
                        time_value *= 60
                    
                    if time_value > 5.0:  # Mais de 5 segundos
                        expensive_queries.append({
                            'query_text': (content[:500] if content else line[:500]),
                            'cpu_time': time_value,
                            'real_time': time_value,
                            'user_id': user_id if user_id and user_id != 'UNKNOWN' else None,
                            'start_line': i + 1,  # 1-based
                            'end_line': i + 1,  # 1-based
                            'line_number': i + 1  # 1-based
                        })
        
        return expensive_queries
    
    def analyze_log_file(self, log_file_path: str) -> Dict:
        """
        Analisa um arquivo de log SAS completo.
        
        Extrai todas as informações relevantes do arquivo de log, incluindo:
        - Métricas de performance
        - Objetos de banco de dados
        - Queries custosas
        
        Args:
            log_file_path: Caminho para o arquivo de log SAS (.log)
            
        Returns:
            Dicionário com os resultados da análise:
            - log_base: Lista de entradas de log completas
            - log_entries: Lista de entradas de log (compatibilidade)
            - performance_metrics: Lista de métricas de performance
            - database_objects: Lista de objetos de banco de dados
            - expensive_queries: Lista de queries custosas
        """
        print(f"Analisando arquivo: {log_file_path}")
        
        # Captura timestamp de início do processamento (usado para inserted_at)
        from datetime import datetime
        inserted_at = datetime.now()
        
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # Analisa cada linha
        log_entries = []  # Mantido para compatibilidade
        log_base_entries = []  # Nova estrutura completa
        performance_metrics = []
        database_objects = []
        expensive_queries = []
        
        # Mantém contexto para linhas sem formato padrão
        last_timestamp = None
        last_level = None
        last_session_id = None
        last_user_id = None
        current_client_project_name = None
        current_task = None
        current_process_flow_name = None
        current_project_path = None
        processed_lines = set()  # Linhas já processadas em blocos de métricas
        
        for i, line in enumerate(lines):
            timestamp, level, session_id, user_id, content = self.extract_session_info(line)
            
            # Se não encontrou formato padrão, usa contexto anterior ou valores padrão
            if timestamp is None:
                timestamp = last_timestamp
            else:
                last_timestamp = timestamp
                
            if level is None:
                level = last_level or 'UNKNOWN'
            else:
                last_level = level
                
            if session_id is None:
                session_id = last_session_id
            else:
                last_session_id = session_id
                
            if user_id is None:
                user_id = last_user_id
            else:
                last_user_id = user_id
            
            
            # Extrai métricas de performance
            perf_user_id = user_id if user_id and user_id != 'UNKNOWN' else None
            perf_session_id = session_id if session_id and session_id != 'UNKNOWN' else None
            perf_metric = self.extract_performance_metrics(line, perf_user_id, perf_session_id, i + 1)
            if perf_metric:
                performance_metrics.append(perf_metric)
            
            # Verifica se esta linha já foi processada como parte de um bloco de métricas
            if i in processed_lines:
                # Pula esta linha, mas ainda cria um registro básico (sem métricas duplicadas)
                extended_metrics = {}
            else:
                # Extrai métricas de performance estendidas da linha atual
                extended_metrics = self.extract_extended_performance_metrics(line)
                
                # Detecta se estamos em um bloco de métricas de performance
                is_performance_block_start = re.search(PERFORMANCE_PATTERNS['performance_block_start'], content)
                
                # Se detectamos início de bloco de métricas, consolida métricas das próximas linhas
                if is_performance_block_start:
                    # Consolida métricas das próximas linhas (até 20 linhas ou até linha vazia/não relacionada)
                    # Também tenta extrair da linha atual (pode ter métricas na mesma linha)
                    consolidated_metrics = extended_metrics.copy()
                    # Se a linha atual não tinha métricas, tenta extrair da linha completa
                    if not consolidated_metrics:
                        consolidated_metrics = self.extract_extended_performance_metrics(line)
                    lookahead_limit = min(i + 20, len(lines))
                    for j in range(i + 1, lookahead_limit):
                        if j >= len(lines):
                            break
                        next_line = lines[j]
                        _, next_level, next_session, next_user, next_content = self.extract_session_info(next_line)
                        
                        # Se a linha não tem session_id ou user_id, usa o contexto atual
                        if not next_session:
                            next_session = session_id
                        if not next_user:
                            next_user = user_id
                        
                        # Verifica se a linha ainda é parte do bloco de métricas
                        # Bloco termina quando encontra linha vazia ou conteúdo não relacionado
                        if not next_content.strip():
                            # Se linha vazia, marca como processada mas não adiciona métricas
                            processed_lines.add(j)
                            break
                        
                        # Verifica se é uma linha de métrica
                        is_metric_line = re.search(PERFORMANCE_PATTERNS['metric_line'], next_content)
                        if not is_metric_line:
                            break
                        
                        # Marca linha como processada
                        processed_lines.add(j)
                        
                        # Extrai métricas da linha seguinte
                        # Usa next_line completa para garantir que os padrões funcionem
                        next_metrics = self.extract_extended_performance_metrics(next_line)
                        # Consolida: se uma métrica já existe, mantém; se não existe, adiciona
                        for key, value in next_metrics.items():
                            if key not in consolidated_metrics or consolidated_metrics[key] is None:
                                consolidated_metrics[key] = value
                    
                    # Usa as métricas consolidadas
                    extended_metrics = consolidated_metrics
                else:
                    # Verifica se estamos em uma linha de métrica que faz parte de um bloco anterior
                    # (linha anterior iniciou o bloco mas não foi detectada corretamente)
                    if i > 0 and extended_metrics:
                        # Verifica se a linha anterior iniciou um bloco
                        prev_line = lines[i - 1] if i > 0 else ""
                        _, _, _, _, prev_content = self.extract_session_info(prev_line)
                        prev_is_performance_block = re.search(PERFORMANCE_PATTERNS['performance_block_start'], prev_content)
                        
                        # Se a linha anterior iniciou um bloco, esta linha já deveria ter sido processada
                        # Caso contrário, processa normalmente
                        if prev_is_performance_block:
                            # Esta linha deveria ter sido processada no lookahead, mas não foi
                            # Processa normalmente mas não cria registro duplicado
                            pass
            
            # Extrai objetos de banco
            db_user_id = user_id if user_id and user_id != 'UNKNOWN' else None
            db_objects = self.extract_database_objects_corrected(line, db_user_id, i + 1)
            database_objects.extend(db_objects)
            
            # Determina type_process
            type_process = self.determine_type_process(line)
            
            # Converte timestamp para log_date (datetime)
            log_date = None
            if timestamp:
                try:
                    from datetime import datetime
                    # timestamp vem no formato: '2025-09-22 14:12:36.129000' ou '2025-09-22T14:12:36,129'
                    timestamp_clean = timestamp.replace(',', '.').replace('T', ' ')
                    try:
                        log_date = datetime.strptime(timestamp_clean, '%Y-%m-%d %H:%M:%S.%f')
                    except ValueError:
                        try:
                            log_date = datetime.strptime(timestamp_clean, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            log_date = None
                except Exception:
                    log_date = None
            
            # Cria registro completo para log_base
            log_base_entry = {
                'log_file': os.path.basename(log_file_path),
                'line_number': i + 1,
                'log_level': level,
                'session_id': session_id,
                'user_id': user_id,
                'content': content.strip(),
                'log_date': log_date,
                'real_time': extended_metrics.get('real_time'),
                'user_cpu_time': extended_metrics.get('user_cpu_time'),
                'system_cpu_time': extended_metrics.get('system_cpu_time'),
                'memory': extended_metrics.get('memory'),
                'os_memory': extended_metrics.get('os_memory'),
                'system_time': extended_metrics.get('system_time'),
                'page_faults': extended_metrics.get('page_faults'),
                'page_swaps': extended_metrics.get('page_swaps'),
                'voluntary_context_switches': extended_metrics.get('voluntary_context_switches'),
                'involuntary_context_switches': extended_metrics.get('involuntary_context_switches'),
                'step_count': extended_metrics.get('step_count'),
                'switch_count': extended_metrics.get('switch_count'),
                'step_timestamp': extended_metrics.get('step_timestamp'),
                'type_process': type_process,
                'client_project_name': current_client_project_name,
                'task': current_task,
                'process_flow_name': current_process_flow_name,
                'project_path': current_project_path,
                'inserted_at': inserted_at
            }
            log_base_entries.append(log_base_entry)
            
            # Mantém log_entries para compatibilidade
            log_entries.append({
                'log_file': os.path.basename(log_file_path),
                'line_number': i + 1,
                'log_level': level,
                'session_id': session_id,
                'user_id': user_id,
                'content': content.strip(),
                'log_date': log_date,
                'inserted_at': inserted_at
            })
        
        # Detecta queries custosas
        expensive_queries = self.detect_expensive_queries(lines)
        
        # Adiciona inserted_at em todos os registros
        for item in performance_metrics:
            item['inserted_at'] = inserted_at
        for item in database_objects:
            item['inserted_at'] = inserted_at
        for item in expensive_queries:
            item['inserted_at'] = inserted_at
        
        return {
            'log_entries': log_entries,  # Mantido para compatibilidade
            'log_base': log_base_entries,  # Nova estrutura completa
            'performance_metrics': performance_metrics,
            'database_objects': database_objects,
            'expensive_queries': expensive_queries
        }
    
    def save_to_database(self, log_file_path: str, analysis_result: Dict):
        """
        Salva os resultados da análise no Databricks SQL.
        
        Insere os dados extraídos na tabela log_base_final usando inserção em lotes
        com fallback para inserção individual em caso de erro. Utiliza retry com
        exponential backoff para lidar com erros de concorrência Delta Lake.
        
        Args:
            log_file_path: Caminho do arquivo de log processado
            analysis_result: Dicionário com os resultados da análise (retornado por analyze_log_file)
            
        Nota:
            - Insere apenas dados em log_base_final (outras tabelas não são mais utilizadas)
            - Usa inserção em lotes de 500 registros para melhor performance
            - Faz commit após cada lote para garantir persistência
            - Trata automaticamente erros de concorrência Delta Lake
        """
        cursor = self.conn.cursor()
        
        log_base = analysis_result.get('log_base', [])
        
        if not log_base:
            print(f"      ℹ️  Nenhum dado para inserir")
            return
        
        # Obtém o nome completo da tabela do db_config
        full_table_name = self.db_config.get('full_table_name', 'log_base_final')
        
        print(f"      💾 Inserindo {len(log_base)} registro(s) em {full_table_name}...")
        
        # Prepara dados apenas com colunas que existem na tabela log_base_final
        # Colunas: log_file, line_number, log_level, session_id, user_id, content, log_date,
        #          real_time, user_cpu_time, system_cpu_time, memory, os_memory, system_time,
        #          page_faults, page_swaps, voluntary_context_switches, involuntary_context_switches,
        #          step_count, switch_count, step_timestamp,
        #          type_process, client_project_name, task, process_flow_name, project_path, inserted_at
        data_batch = [
            (
                entry.get('log_file'), entry.get('line_number'),
                entry.get('log_level'), entry.get('session_id'), entry.get('user_id'),
                entry.get('content'), entry.get('log_date'),
                entry.get('real_time'), entry.get('user_cpu_time'), entry.get('system_cpu_time'),
                entry.get('memory'), entry.get('os_memory'), entry.get('system_time'),
                entry.get('page_faults'), entry.get('page_swaps'),
                entry.get('voluntary_context_switches'), entry.get('involuntary_context_switches'),
                entry.get('step_count'), entry.get('switch_count'), entry.get('step_timestamp'),
                entry.get('type_process'), entry.get('client_project_name'), entry.get('task'),
                entry.get('process_flow_name'), entry.get('project_path'),
                entry.get('inserted_at')
            )
            for entry in log_base
        ]
        
        # SQL INSERT (Databricks usa ? como placeholder)
        # Total: 26 colunas (sem o id que é auto-gerado)
        # Colunas: log_file(1), line_number(2), log_level(3), session_id(4), user_id(5), content(6), log_date(7),
        #          real_time(8), user_cpu_time(9), system_cpu_time(10), memory(11), os_memory(12), system_time(13),
        #          page_faults(14), page_swaps(15), voluntary_context_switches(16), involuntary_context_switches(17),
        #          step_count(18), switch_count(19), step_timestamp(20),
        #          type_process(21), client_project_name(22), task(23), process_flow_name(24), project_path(25), inserted_at(26)
        insert_sql = f'''
            INSERT INTO {full_table_name}
            (log_file, line_number, log_level, session_id, user_id, content, log_date,
             real_time, user_cpu_time, system_cpu_time, memory, os_memory, system_time,
             page_faults, page_swaps, voluntary_context_switches, involuntary_context_switches,
             step_count, switch_count, step_timestamp,
             type_process, client_project_name, task, process_flow_name, project_path, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        
        # Insere em lotes usando executemany (mais rápido)
        # Se falhar, tenta inserir linha por linha apenas para aquele lote
        batch_size = 500
        inserted_count = 0
        total_batches = (len(data_batch) + batch_size - 1) // batch_size
        
        # Validação: verifica se a primeira linha tem 26 valores
        if data_batch and len(data_batch[0]) != 26:
            print(f"      ⚠️  AVISO: Primeira linha tem {len(data_batch[0])} valores, mas esperado 26!")
            print(f"      Valores: {data_batch[0]}")
            return
        
        print(f"      📦 Inserindo {len(data_batch)} registro(s) em {total_batches} lote(s) de {batch_size}...")
        
        for i in range(0, len(data_batch), batch_size):
            batch = data_batch[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            # Valida que todas as linhas do lote têm 26 valores
            invalid_rows = [idx for idx, row in enumerate(batch) if len(row) != 26]
            if invalid_rows:
                print(f"      ⚠️  Lote {batch_num}: {len(invalid_rows)} linha(s) com número incorreto de valores, pulando...")
                continue
            
            print(f"      📦 Processando lote {batch_num}/{total_batches} ({len(batch)} registros)...", end='', flush=True)
            
            def insert_batch():
                cursor.executemany(insert_sql, batch)
                self.conn.commit()
                return True
            
            try:
                self._retry_with_backoff(insert_batch, max_retries=5, initial_delay=0.5)
                inserted_count += len(batch)
                print(f" ✅")
            except Exception as e:
                # Se falhar em lote, tenta inserir individualmente apenas para este lote
                print(f"\n      ⚠️  Erro ao inserir lote {batch_num}, tentando inserção individual...")
                individual_success = 0
                
                for row_idx, row in enumerate(batch):
                    def insert_row():
                        cursor.execute(insert_sql, row)
                        self.conn.commit()
                        return True
                    
                    try:
                        self._retry_with_backoff(insert_row, max_retries=3, initial_delay=0.3)
                        individual_success += 1
                    except Exception as row_error:
                        # Ignora duplicatas
                        if "duplicate" in str(row_error).lower() or "already exists" in str(row_error).lower():
                            individual_success += 1
                            continue
                        # Log detalhado de erro de aridade
                        if "ARITY" in str(row_error) or "NOT_ENOUGH_DATA_COLUMNS" in str(row_error):
                            print(f"      ⚠️  Erro de aridade na linha {i + row_idx + 1}: {row_error}")
                            print(f"      Valores na linha: {len(row)} (esperado 26)")
                            if row:
                                print(f"      Primeiros 5 valores: {row[:5]}")
                            continue
                        print(f"      ⚠️  Erro ao inserir linha {i + row_idx + 1}: {row_error}")
                        continue
                
                inserted_count += individual_success
                print(f"      ✅ {individual_success}/{len(batch)} registros do lote {batch_num} inseridos individualmente")
        
        print(f"      ✅ {inserted_count}/{len(log_base)} registro(s) inserido(s) em {full_table_name}")
    
    def analyze_all_logs(self, log_directory: str = "log_files"):
        """
        Analisa todos os arquivos de log no diretório especificado.
        
        Processa todos os arquivos .log encontrados no diretório, analisa cada um
        e salva os resultados no Databricks. Este método é útil para processamento
        standalone, mas recomenda-se usar ingest_sas_logs.py para funcionalidades
        completas (processamento paralelo, verificação de duplicatas, etc.).
        
        Args:
            log_directory: Diretório contendo os arquivos de log (padrão: "log_files")
            
        Nota:
            - As tabelas devem ser criadas previamente usando ingest_sas_logs.py
            - Este método não suporta processamento paralelo
            - Para melhor performance, use ingest_sas_logs.py com --parallel
        """
        log_files = glob.glob(f"{log_directory}/*.log")
        
        if not log_files:
            print("Nenhum arquivo de log encontrado!")
            return
        
        print(f"Encontrados {len(log_files)} arquivos de log para analise")
        
        if not self.connect_database():
            return
        
        # Nota: create_tables() foi removido - tabelas são criadas pelo ingest_sas_logs.py
        
        for log_file in log_files:
            try:
                analysis_result = self.analyze_log_file(log_file)
                self.save_to_database(log_file, analysis_result)
                print(f"Analisado: {os.path.basename(log_file)}")
            except Exception as e:
                print(f"Erro ao analisar {log_file}: {e}")
        
        if self.conn:
            self.conn.close()
        print("Analise concluida!")


def main():
    """Função principal"""

    # Carrega variáveis do .env
    load_dotenv()
    
    # Configuração do Databricks (exemplo - normalmente vem de ingest_sas_logs.py)
    # Nota: Este main() é apenas para uso standalone. Para uso completo, use ingest_sas_logs.py
    
    db_config = {
        'server_hostname': os.getenv('DATABRICKS_SERVER_HOSTNAME'),
        'http_path': os.getenv('DATABRICKS_HTTP_PATH'),
        'catalog': os.getenv('DATABRICKS_CATALOG', 'bv_dev_db'),
        'schema': os.getenv('DATABRICKS_SCHEMA', 'bv_migration_sas'),
        'full_table_name': f"{os.getenv('DATABRICKS_CATALOG', 'bv_dev_db')}.{os.getenv('DATABRICKS_SCHEMA', 'bv_migration_sas')}.log_base_final"
    }
    
    # Cria o analisador
    analyzer = SASLogAnalyzer(db_config)
    
    # Executa a análise completa
    analyzer.analyze_all_logs()


if __name__ == "__main__":
    main()






