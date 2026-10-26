#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Padrões Regex Centralizados para Análise de Logs SAS
====================================================

Este módulo centraliza todos os padrões regex utilizados para extração de dados
dos logs SAS, garantindo consistência e facilitando manutenção.

Organização:
- PERFORMANCE: Métricas de performance e execução
- PROCESS_TYPE: Classificação de tipos de processo
- AREA: Áreas SAS (WORK, SASHELP, etc.)
- SESSION_INFO: Informações de sessão e usuário
- DATABASE_OBJECTS: Objetos de banco de dados (tabelas, libnames, arquivos)
- EXPENSIVE_QUERIES: Detecção de queries custosas
- CODE_CATEGORY: Categorização de código (USER_QUERY vs PROCESS)
- ERROR: Mensagens de erro e warning
"""

# ============================================================================
# PERFORMANCE METRICS - Métricas de Performance e Execução
# ============================================================================

PERFORMANCE_PATTERNS = {
    # Tempos de execução
    'real_time': r'(?i)real\s+time\s+([\d\.:]+)\s*(?:seconds?)?',
    'user_cpu_time': r'(?i)user\s+cpu\s+time\s+([\d\.:]+)\s*(?:seconds?)?',
    'system_cpu_time': r'(?i)system\s+cpu\s+time\s+([\d\.:]+)\s*(?:seconds?)?',
    'cpu_time': r'(?i)cpu\s+time\s+([\d\.:]+)\s*(?:seconds?)?',
    'system_time': r'(?i)system\s+time\s+([\d\.]+)',

    # Memória
    'memory': r'(?i)\bmemory\s+([\d\.]+)',
    'os_memory': r'(?i)OS\s+Memory\s+([\d\.]+)',
    'memory_usage': r'(?i)memory\s+([\d\.]+)\s*(MB|GB|KB)?',

    # Métricas de SO
    'page_faults': r'(?i)Page\s+Faults\s+(\d+)$',
    'page_swaps': r'(?i)Page\s+Swaps\s+(\d+)$',
    'page_reclaims': r'(?i)Page\s+Reclaims\s+(\d+)',

    # Context Switches (ordem importante: involuntary primeiro, depois voluntary)
    'involuntary_context_switches': r'(?i)\bInvoluntary\s+Context\s+Switches\s+(\d+)',
    'voluntary_context_switches': r'(?i)\bVoluntary\s+Context\s+Switches\s+(\d+)',

    # Operações de I/O
    'block_input_operations': r'(?i)Block\s+Input\s+Operations\s+(\d+)',
    'block_output_operations': r'(?i)Block\s+Output\s+Operations\s+(\d+)',

    # Step e Switch Count
    'step_count': r'(?i)Step\s+Count\s+(\d+)',
    'switch_count': r'(?i)Switch\s+Count\s+(\d+)',
    'step_and_switch_count': r'(?i)Step\s+Count\s+(\d+).*?Switch\s+Count\s+(\d+)',

    # Timestamp da execução do step
    'step_timestamp': r'(?i)Timestamp\s+(.+)$',

    # Linhas lidas/escritas
    'lines_read': r'(\d+)\s+lines\s+read',
    'lines_written': r'(\d+)\s+lines\s+written',

    # Detecção de bloco de métricas de performance
    'performance_block_start': r'(?i)(?:NOTE:\s+)?PROCEDURE\s+\w+\s+used\s+\(Total\s+process\s+time\):',

    # Detecção de linha de métrica
    'metric_line': r'(?i)(?:^\s+)?(real\s+time|user\s+cpu\s+time|system\s+cpu\s+time|memory|os\s+memory|timestamp|page\s+faults|page\s+swaps|page\s+reclaims|step\s+count|switch\s+count|voluntary|involuntary|block\s+input|block\s+output)',

    # Real time com formato MM:SS.ss (ex: 1:06.49)
    'real_time_formatted': r'(?i)real\s+time\s+(\d+):(\d+\.\d+)',
}

# ============================================================================
# PROCESS TYPE - Classificação de Tipos de Processo
# ============================================================================

PROCESS_TYPE_PATTERNS = {
    'modelo': r'PROC\s+(NEURAL|DM|FOREST|SVM|HPFOREST|HPNEURAL|MODEL|FORECAST|ARIMA|TIMESERIES|AUTOREG)',
    'analitico': r'PROC\s+(MEANS|FREQ|TABULATE|SUMMARY|UNIVARIATE|REG|LOGISTIC|GLM|MIXED|GENMOD|PHREG)',
    'etl_sql': r'PROC\s+SQL',
    'etl_proc': r'PROC\s+(IMPORT|EXPORT|LOAD|DBLOAD|SORT|TRANSPOSE|STANDARDIZE)',
    'etl_data': r'DATA\s+\w+\s*;',
    'etl_set_merge': r'SET\s+|MERGE\s+',
    'operacional': r'PROC\s+(PRINT|CONTENTS|DATASETS|CATALOG)',
}

# ============================================================================
# AREA - Áreas SAS (WORK, SASHELP, etc.)
# ============================================================================

AREA_PATTERNS = [
    r'\b(WORK)\.',
    r'\b(SASHELP)\.',
    r'\b(SASUSER)\.',
    r'\b(LIBRARY)\.',
    r'(\w+):\s*NOTE:',
]

# ============================================================================
# SESSION INFO - Informações de Sessão e Usuário
# ============================================================================

SESSION_INFO_PATTERNS = {
    # Padrão completo: timestamp level [session] :user_id - content
    'full_pattern': r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d{3})\s+(\w+)\s+\[(\d+)\]\s+:([^\s]+)\s+-\s+(.*)',
    # Padrão sem user_id: timestamp level [session] - content
    'without_user': r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d{3})\s+(\w+)\s+\[(\d+)\]\s+-\s+(.*)',
}

# ============================================================================
# CODE CATEGORY - Categoria de Código (USER_QUERY vs PROCESS)
# ============================================================================

CODE_CATEGORY_PATTERNS = {
    'numbered_select': r'^\s*\d+\s+SELECT\s+',
    'simple_select': r'SELECT\s+.*\s+FROM\s+\w+\.\w+',
    'complex_query': r'JOIN|WHERE.*=|GROUP\s+BY|HAVING',
}

# ============================================================================
# ERROR MESSAGES - Mensagens de Erro
# ============================================================================

ERROR_PATTERNS = {
    'error_prefix': r'^(ERROR|WARNING|NOTE):\s*',
}

# ============================================================================
# DATABASE OBJECTS - Objetos de Banco de Dados
# ============================================================================

DATABASE_OBJECT_PATTERNS = {
    # Libname (PATH)
    'libname': r'libname\s+(\w+)\s+["\']([^"\']+)["\']',
    
    # Tabelas (TABLE)
    'table_patterns': [
        # Padrões de origem (FROM, JOIN)
        r'FROM\s+(\w+)\.(\w+)',
        r'JOIN\s+(\w+)\.(\w+)',
        r'INNER\s+JOIN\s+(\w+)\.(\w+)',
        r'LEFT\s+JOIN\s+(\w+)\.(\w+)',
        r'RIGHT\s+JOIN\s+(\w+)\.(\w+)',
        r'FULL\s+JOIN\s+(\w+)\.(\w+)',
        # Padrões de destino (INTO, CREATE TABLE, UPDATE)
        r'INTO\s+(\w+)\.(\w+)',
        r'CREATE\s+TABLE\s+(\w+)\.(\w+)',
        r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\.(\w+)',
        r'UPDATE\s+(\w+)\.(\w+)',
        r'DELETE\s+FROM\s+(\w+)\.(\w+)',
    ],
    
    # Arquivos (FILE)
    'file_patterns': [
        r'NOTE:\s+The\s+autoexec\s+file,\s+([^\s]+)',
        r'file\s+([^\s]+)',
        r'filename\s+\w+\s+["\']([^"\']+)["\']',
    ],
}

# ============================================================================
# EXPENSIVE QUERIES - Queries Custosas
# ============================================================================

EXPENSIVE_QUERY_PATTERNS = {
    'cpu_time': r'cpu\s+time\s+(\d+\.?\d*)',
    'real_time': r'real\s+time\s+(\d+\.?\d*)',
    'time_with_unit': r'(\d+\.?\d*)\s+(seconds?|minutes?)',
}
