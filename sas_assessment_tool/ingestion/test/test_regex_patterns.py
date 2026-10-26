#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes Unitários para regex_patterns.py
========================================

Testa se os padrões regex estão corretos e funcionando.

Para executar os testes (a partir do diretório ingestion/):
    pytest test/test_regex_patterns.py -v
"""

import pytest
import re
import sys
from pathlib import Path

# Adiciona o diretório pai ao path para importar módulos
sys.path.insert(0, str(Path(__file__).parent.parent))

from regex_patterns import (
    PERFORMANCE_PATTERNS,
    PROCESS_TYPE_PATTERNS,
    AREA_PATTERNS,
    SESSION_INFO_PATTERNS,
    DATABASE_OBJECT_PATTERNS,
    ERROR_PATTERNS,
    EXPENSIVE_QUERY_PATTERNS,
)


class TestPerformancePatterns:
    """Testes para padrões de performance"""
    
    def test_real_time_pattern(self):
        """Testa padrão de real time"""
        line = "real time 1:06.49"
        match = re.search(PERFORMANCE_PATTERNS['real_time_formatted'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "1"
        assert match.group(2) == "06.49"
    
    def test_user_cpu_time_pattern(self):
        """Testa padrão de user CPU time"""
        line = "user cpu time 12.5 seconds"
        match = re.search(PERFORMANCE_PATTERNS['user_cpu_time'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "12.5"
    
    def test_memory_pattern(self):
        """Testa padrão de memory"""
        line = "memory 1024.5"
        match = re.search(PERFORMANCE_PATTERNS['memory'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "1024.5"
    
    def test_page_faults_pattern(self):
        """Testa padrão de page faults"""
        line = "Page Faults 1234"
        match = re.search(PERFORMANCE_PATTERNS['page_faults'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "1234"
    
    def test_step_count_pattern(self):
        """Testa padrão de step count"""
        line = "Step Count 5"
        match = re.search(PERFORMANCE_PATTERNS['step_count'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "5"


class TestProcessTypePatterns:
    """Testes para padrões de tipo de processo"""
    
    def test_etl_sql_pattern(self):
        """Testa padrão ETL SQL"""
        line = "PROC SQL;"
        match = re.search(PROCESS_TYPE_PATTERNS['etl_sql'], line, re.IGNORECASE)
        assert match is not None
    
    def test_analitico_pattern(self):
        """Testa padrão ANALÍTICO"""
        line = "PROC MEANS DATA=test;"
        match = re.search(PROCESS_TYPE_PATTERNS['analitico'], line, re.IGNORECASE)
        assert match is not None
    
    def test_modelo_pattern(self):
        """Testa padrão MODELO"""
        line = "PROC NEURAL DATA=test;"
        match = re.search(PROCESS_TYPE_PATTERNS['modelo'], line, re.IGNORECASE)
        assert match is not None


class TestAreaPatterns:
    """Testes para padrões de área"""
    
    def test_work_pattern(self):
        """Testa padrão WORK"""
        line = "NOTE: Data set WORK.TEST"
        match = None
        for pattern in AREA_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                break
        assert match is not None
    
    def test_sashelp_pattern(self):
        """Testa padrão SASHELP"""
        line = "NOTE: Using SASHELP.CLASS"
        match = None
        for pattern in AREA_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                break
        assert match is not None


class TestSessionInfoPatterns:
    """Testes para padrões de informação de sessão"""
    
    def test_full_pattern(self):
        """Testa padrão completo de sessão"""
        line = "2025-09-22T14:12:36,129 INFO [00000003] :victoria.castro - NOTE: Test"
        match = re.match(SESSION_INFO_PATTERNS['full_pattern'], line)
        assert match is not None
        assert match.group(2) == "INFO"
        assert match.group(3) == "00000003"
        assert match.group(4) == "victoria.castro"
    
    def test_without_user_pattern(self):
        """Testa padrão sem user_id"""
        line = "2025-09-22T14:12:36,129 INFO [00000003] - NOTE: Test"
        match = re.match(SESSION_INFO_PATTERNS['without_user'], line)
        assert match is not None
        assert match.group(2) == "INFO"
        assert match.group(3) == "00000003"


class TestDatabaseObjectPatterns:
    """Testes para padrões de objetos de banco de dados"""
    
    def test_libname_pattern(self):
        """Testa padrão de libname"""
        line = "libname testlib '/path/to/data';"
        match = re.search(DATABASE_OBJECT_PATTERNS['libname'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "testlib"
        assert match.group(2) == "/path/to/data"
    
    def test_table_from_pattern(self):
        """Testa padrão de tabela FROM"""
        line = "SELECT * FROM schema.table;"
        match = None
        for pattern in DATABASE_OBJECT_PATTERNS['table_patterns']:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                break
        assert match is not None
        assert match.group(1) == "schema"
        assert match.group(2) == "table"
    
    def test_table_join_pattern(self):
        """Testa padrão de tabela JOIN"""
        line = "SELECT * FROM t1 JOIN schema.table t2 ON t1.id = t2.id;"
        match = None
        for pattern in DATABASE_OBJECT_PATTERNS['table_patterns']:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                break
        assert match is not None


class TestErrorPatterns:
    """Testes para padrões de erro"""
    
    def test_error_prefix_pattern(self):
        """Testa padrão de prefixo de erro"""
        line = "ERROR: Variable not found"
        match = re.search(ERROR_PATTERNS['error_prefix'], line, re.IGNORECASE)
        assert match is not None
    
    def test_warning_prefix_pattern(self):
        """Testa padrão de prefixo de warning"""
        line = "WARNING: Division by zero"
        match = re.search(ERROR_PATTERNS['error_prefix'], line, re.IGNORECASE)
        assert match is not None


class TestExpensiveQueryPatterns:
    """Testes para padrões de queries custosas"""
    
    def test_cpu_time_pattern(self):
        """Testa padrão de CPU time"""
        line = "cpu time 2.5"
        match = re.search(EXPENSIVE_QUERY_PATTERNS['cpu_time'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "2.5"
    
    def test_real_time_pattern(self):
        """Testa padrão de real time"""
        line = "real time 6.0"
        match = re.search(EXPENSIVE_QUERY_PATTERNS['real_time'], line, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "6.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

