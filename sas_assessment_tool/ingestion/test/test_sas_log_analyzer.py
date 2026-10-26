#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes Unitários para sas_log_analyzer.py
==========================================

Este módulo contém testes unitários para as funções principais do analisador de logs SAS.

Para executar os testes (a partir do diretório ingestion/):
    pytest test/test_sas_log_analyzer.py -v

Para executar com cobertura:
    pytest test/ --cov=sas_log_analyzer --cov=regex_patterns --cov-report=html
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Adiciona o diretório raiz do projeto ao path para importar módulos
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ingestion.sas_log_analyzer import SASLogAnalyzer


class TestSASLogAnalyzer:
    """Testes para a classe SASLogAnalyzer"""
    
    @pytest.fixture
    def analyzer(self):
        """Cria uma instância do analisador para testes"""
        db_config = {
            'server_hostname': 'test.databricks.com',
            'http_path': '/sql/1.0/warehouses/test',
            'catalog': 'test_catalog',
            'schema': 'test_schema',
            'full_table_name': 'test_catalog.test_schema.log_base_final'
        }
        return SASLogAnalyzer(db_config)
    
    def test_extract_session_info_full_pattern(self, analyzer):
        """Testa extração de informações de sessão com padrão completo"""
        line = "2025-09-22T14:12:36,129 INFO [00000003] :victoria.castro - NOTE: Unable to open"
        timestamp, level, session_id, user_id, content = analyzer.extract_session_info(line)
        
        assert timestamp is not None
        assert level == "INFO"
        assert session_id == "00000003"
        assert user_id == "victoria.castro"
        assert "NOTE: Unable to open" in content
    
    def test_extract_session_info_without_user(self, analyzer):
        """Testa extração de informações de sessão sem user_id"""
        line = "2025-09-22T14:12:36,129 INFO [00000003] - NOTE: Unable to open"
        timestamp, level, session_id, user_id, content = analyzer.extract_session_info(line)
        
        assert timestamp is not None
        assert level == "INFO"
        assert session_id == "00000003"
        assert user_id is None
        assert "NOTE: Unable to open" in content
    
    def test_extract_session_info_invalid_format(self, analyzer):
        """Testa extração com formato inválido"""
        line = "Linha sem formato padrão"
        timestamp, level, session_id, user_id, content = analyzer.extract_session_info(line)
        
        assert timestamp is None
        assert level is None
        assert session_id is None
        assert user_id is None
        assert content == line
    
    def test_extract_area_work(self, analyzer):
        """Testa extração de área WORK"""
        line = "NOTE: Data set WORK.TEST has 100 observations"
        area = analyzer.extract_area(line)
        assert area == "WORK"
    
    def test_extract_area_sashelp(self, analyzer):
        """Testa extração de área SASHELP"""
        line = "NOTE: Using SASHELP.CLASS"
        area = analyzer.extract_area(line)
        assert area == "SASHELP"
    
    def test_extract_area_none(self, analyzer):
        """Testa extração de área quando não há área"""
        line = "NOTE: Process completed"
        area = analyzer.extract_area(line)
        assert area is None
    
    def test_extract_error_message_error(self, analyzer):
        """Testa extração de mensagem de erro"""
        line = "ERROR: Variable not found"
        msg = analyzer.extract_error_message(line, "ERROR")
        assert msg == "Variable not found"
    
    def test_extract_error_message_warning(self, analyzer):
        """Testa extração de mensagem de warning"""
        line = "WARNING: Division by zero"
        msg = analyzer.extract_error_message(line, "WARNING")
        assert msg == "Division by zero"
    
    def test_extract_error_message_none(self, analyzer):
        """Testa extração quando não é erro"""
        line = "NOTE: Process completed"
        msg = analyzer.extract_error_message(line, "INFO")
        assert msg is None
    
    def test_determine_type_process_etl_sql(self, analyzer):
        """Testa classificação de processo ETL (SQL)"""
        line = "PROC SQL;"
        type_process = analyzer.determine_type_process(line)
        assert type_process == "ETL"
    
    def test_determine_type_process_etl_proc(self, analyzer):
        """Testa classificação de processo ETL (PROC)"""
        line = "PROC IMPORT DATAFILE='test.csv';"
        type_process = analyzer.determine_type_process(line)
        assert type_process == "ETL"
    
    def test_determine_type_process_analitico(self, analyzer):
        """Testa classificação de processo ANALÍTICO"""
        line = "PROC MEANS DATA=test;"
        type_process = analyzer.determine_type_process(line)
        assert type_process == "ANALÍTICO"
    
    def test_determine_type_process_modelo(self, analyzer):
        """Testa classificação de processo MODELO"""
        line = "PROC NEURAL DATA=test;"
        type_process = analyzer.determine_type_process(line)
        assert type_process == "MODELO"
    
    def test_determine_type_process_operacional(self, analyzer):
        """Testa classificação de processo OPERACIONAL"""
        line = "PROC PRINT DATA=test;"
        type_process = analyzer.determine_type_process(line)
        assert type_process == "OPERACIONAL"
    
    def test_determine_type_process_none(self, analyzer):
        """Testa classificação quando não há tipo"""
        line = "NOTE: Process completed"
        type_process = analyzer.determine_type_process(line)
        assert type_process is None
    
    def test_extract_extended_performance_metrics_real_time(self, analyzer):
        """Testa extração de métricas de performance - real time"""
        line = "real time 1:06.49"
        metrics = analyzer.extract_extended_performance_metrics(line)
        assert 'real_time' in metrics
        assert metrics['real_time'] == 66.49  # 1 minuto + 6.49 segundos
    
    def test_extract_extended_performance_metrics_user_cpu(self, analyzer):
        """Testa extração de métricas de performance - user CPU time"""
        line = "user cpu time 12.5 seconds"
        metrics = analyzer.extract_extended_performance_metrics(line)
        assert 'user_cpu_time' in metrics
        assert metrics['user_cpu_time'] == 12.5
    
    def test_extract_extended_performance_metrics_memory(self, analyzer):
        """Testa extração de métricas de performance - memory"""
        line = "memory 1024.5"
        metrics = analyzer.extract_extended_performance_metrics(line)
        assert 'memory' in metrics
        assert metrics['memory'] == 1024
    
    def test_extract_extended_performance_metrics_page_faults(self, analyzer):
        """Testa extração de métricas de performance - page faults"""
        line = "Page Faults 1234"
        metrics = analyzer.extract_extended_performance_metrics(line)
        assert 'page_faults' in metrics
        assert metrics['page_faults'] == 1234
    
    def test_extract_extended_performance_metrics_step_count(self, analyzer):
        """Testa extração de métricas de performance - step count"""
        line = "Step Count 5"
        metrics = analyzer.extract_extended_performance_metrics(line)
        assert 'step_count' in metrics
        assert metrics['step_count'] == 5
    
    def test_extract_database_objects_libname(self, analyzer):
        """Testa extração de objetos de banco - libname"""
        line = "libname testlib '/path/to/data';"
        objects = analyzer.extract_database_objects_corrected(line, "user1", 1)
        
        assert len(objects) > 0
        assert objects[0]['object_type'] == 'PATH'
        assert objects[0]['schema_name'] == 'testlib'
    
    def test_extract_database_objects_table_from(self, analyzer):
        """Testa extração de objetos de banco - tabela FROM"""
        line = "SELECT * FROM schema.table;"
        objects = analyzer.extract_database_objects_corrected(line, "user1", 1)
        
        assert len(objects) > 0
        assert objects[0]['object_type'] == 'TABLE'
        assert objects[0]['schema_name'] == 'schema'
        assert objects[0]['table_name'] == 'table'
    
    def test_extract_database_objects_table_join(self, analyzer):
        """Testa extração de objetos de banco - tabela JOIN"""
        line = "SELECT * FROM t1 JOIN schema.table t2 ON t1.id = t2.id;"
        objects = analyzer.extract_database_objects_corrected(line, "user1", 1)
        
        assert len(objects) > 0
        # Deve encontrar pelo menos a tabela do JOIN
        table_objects = [obj for obj in objects if obj['object_type'] == 'TABLE']
        assert len(table_objects) > 0
    
    def test_extract_database_objects_invalid_line_number(self, analyzer):
        """Testa extração com line_number inválido"""
        line = "SELECT * FROM schema.table;"
        objects = analyzer.extract_database_objects_corrected(line, "user1", None)
        assert len(objects) == 0
        
        objects = analyzer.extract_database_objects_corrected(line, "user1", -1)
        assert len(objects) == 0
    
    def test_detect_expensive_queries_cpu_time(self, analyzer):
        """Testa detecção de queries custosas - CPU time"""
        lines = [
            "2025-09-22T14:12:36,129 INFO [00000003] :user - NOTE: cpu time 2.5",
            "2025-09-22T14:12:36,130 INFO [00000003] :user - NOTE: Query completed"
        ]
        queries = analyzer.detect_expensive_queries(lines)
        
        assert len(queries) > 0
        assert queries[0]['cpu_time'] == 2.5
    
    def test_detect_expensive_queries_real_time(self, analyzer):
        """Testa detecção de queries custosas - real time"""
        lines = [
            "2025-09-22T14:12:36,129 INFO [00000003] :user - NOTE: real time 6.0",
            "2025-09-22T14:12:36,130 INFO [00000003] :user - NOTE: Query completed"
        ]
        queries = analyzer.detect_expensive_queries(lines)
        
        assert len(queries) > 0
        assert queries[0]['real_time'] == 6.0
    
    def test_detect_expensive_queries_not_expensive(self, analyzer):
        """Testa que queries não custosas não são detectadas"""
        lines = [
            "2025-09-22T14:12:36,129 INFO [00000003] :user - NOTE: cpu time 0.5",
            "2025-09-22T14:12:36,130 INFO [00000003] :user - NOTE: real time 3.0"
        ]
        queries = analyzer.detect_expensive_queries(lines)
        
        # CPU < 1.0 e Real < 5.0, não deve ser detectado
        assert len(queries) == 0
    
    def test_is_delta_concurrency_error(self, analyzer):
        """Testa detecção de erro de concorrência Delta Lake"""
        error = Exception("[DELTA_METADATA_CHANGED] MetadataChangedException")
        assert analyzer._is_delta_concurrency_error(error) is True
        
        error = Exception("Other error")
        assert analyzer._is_delta_concurrency_error(error) is False
    
    @patch('time.sleep')
    def test_retry_with_backoff_success(self, mock_sleep, analyzer):
        """Testa retry com backoff - sucesso na primeira tentativa"""
        func = Mock(return_value=True)
        result = analyzer._retry_with_backoff(func, max_retries=3, initial_delay=0.1)
        
        assert result is True
        assert func.call_count == 1
        mock_sleep.assert_not_called()
    
    @patch('time.sleep')
    def test_retry_with_backoff_retry(self, mock_sleep, analyzer):
        """Testa retry com backoff - sucesso após retry"""
        func = Mock(side_effect=[
            Exception("[DELTA_METADATA_CHANGED] Error"),
            Exception("[DELTA_METADATA_CHANGED] Error"),
            True
        ])
        result = analyzer._retry_with_backoff(func, max_retries=3, initial_delay=0.1)
        
        assert result is True
        assert func.call_count == 3
        assert mock_sleep.call_count == 2
    
    @patch('time.sleep')
    def test_retry_with_backoff_failure(self, mock_sleep, analyzer):
        """Testa retry com backoff - falha após todas as tentativas"""
        func = Mock(side_effect=Exception("[DELTA_METADATA_CHANGED] Error"))
        
        with pytest.raises(Exception):
            analyzer._retry_with_backoff(func, max_retries=3, initial_delay=0.1)
        
        assert func.call_count == 3
        assert mock_sleep.call_count == 2
    
    @patch('time.sleep')
    def test_retry_with_backoff_non_delta_error(self, mock_sleep, analyzer):
        """Testa retry com backoff - erro não Delta não é retentado"""
        func = Mock(side_effect=Exception("Other error"))
        
        with pytest.raises(Exception):
            analyzer._retry_with_backoff(func, max_retries=3, initial_delay=0.1)
        
        assert func.call_count == 1
        mock_sleep.assert_not_called()


class TestIntegration:
    """Testes de integração (requerem arquivos de log reais)"""
    
    @pytest.fixture
    def analyzer(self):
        """Cria uma instância do analisador para testes"""
        db_config = {
            'server_hostname': 'test.databricks.com',
            'http_path': '/sql/1.0/warehouses/test',
            'catalog': 'test_catalog',
            'schema': 'test_schema',
            'full_table_name': 'test_catalog.test_schema.log_base_final'
        }
        return SASLogAnalyzer(db_config)
    
    def test_analyze_log_file_structure(self, analyzer, tmp_path):
        """Testa estrutura do resultado de analyze_log_file"""
        # Cria arquivo de log de teste
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "2025-09-22T14:12:36,129 INFO [00000003] :user - NOTE: Test log line\n"
            "2025-09-22T14:12:36,130 INFO [00000003] :user - NOTE: real time 1.5 seconds\n"
        )
        
        result = analyzer.analyze_log_file(str(log_file))
        
        assert 'log_base' in result
        assert 'log_entries' in result
        assert 'performance_metrics' in result
        assert 'database_objects' in result
        assert 'expensive_queries' in result
        assert len(result['log_base']) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

