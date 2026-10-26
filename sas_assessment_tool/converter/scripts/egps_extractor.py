# egps_extractor_v1.py — variante de migração (IA / Databricks / DBT).
#
# Gera .txt com metadados mínimos e corpo SAS na ordem dos fluxos do project.xml: cada task tem blocos de comentário
# INÍCIO/FIM com TASK, ORDEM EXECUÇÃO (001…), fluxo e ficheiro fonte; o interior da task está sem comentários SAS.
# Inclui código embedded aceite do project.xml após as tasks do fluxo (linha ORIGEM: project.xml no cabeçalho).
# Export tasks seguem como PROC EXPORT com o mesmo formato de task. Órfãos e ingestão sintética de logs não entram no corpo.
#
# O extrator canónico continua em egps_extractor.py. CLI: --eg-style / --clean são ignorados na composição do corpo v1.

import html
import os
import zipfile
import xml.etree.ElementTree as ET
import glob
import sys
import re
import hashlib
from collections import defaultdict, deque
from datetime import datetime, timezone

DEFAULT_INPUT_FOLDER = r'./received_egps'
DEFAULT_OUTPUT_FOLDER = r'./text_egps'

# Variáveis %LET padrão do SAS EG (Excluídas)
LET_EXCLUDED_NAMES = frozenset({
    '_CLIENTTASKLABEL', '_CLIENTPROCESSFLOWNAME', '_CLIENTPROJECTPATH',
    '_CLIENTPROJECTPATHHOST', '_CLIENTPROJECTNAME', '_SASPROGRAMFILE', '_SASPROGRAMFILEHOST'
})

# Librefs SAS a ignorar ao qualificar saídas LIB.membro a partir do código (WORK, etc.)
_EXCLUDED_SAS_LIBREFS_FOR_OUTPUT_QUALIFY = frozenset({
    'WORK', 'SASUSER', 'SASHELP', 'SASTMP', 'TEMP', 'USER', 'MAPPING',
})
_SAS_OUTPUT_MEMBER_TOKEN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
# ex.: CART.BASE_PERF_120_WO_&DT_BASE — evitar ((?:…*)+)&: com text_clean numa linha gigante = backtracking catastrófico.
_LIB_MEMBER_AMP_MACRO_DYNAMIC_RE = re.compile(
    r'\b([A-Za-z_][A-Za-z0-9_]{0,31})\.([A-Za-z_][A-Za-z0-9_]{0,31})&([A-Za-z_][A-Za-z0-9_]{0,31})\b',
    re.IGNORECASE,
)

# =====================================================================
# LISTAS DE BLOQUEIO DE SUJEIRA (SQL RESERVED E FUNCTIONS)
# =====================================================================
SQL_RESERVED = frozenset({
    'SELECT', 'WHERE', 'ON', 'AND', 'OR', 'LEFT', 'RIGHT', 'INNER', 'OUTER',
    'CROSS', 'AS', 'GROUP', 'ORDER', 'BY', 'HAVING', 'LIMIT', 'CASE', 'WHEN',
    'THEN', 'ELSE', 'END', 'IN', 'EXISTS', 'BETWEEN', 'LIKE', 'UNION', 'ALL',
    'DISTINCT', 'FROM', 'JOIN', 'SET', 'DATA', 'RUN', 'NULL', 'IS', 'NOT',
    'CONNECTION', 'CREATE', 'TABLE', 'VIEW', 'DROP', 'ALTER', 'IF', 'DO',
    'WHILE', 'UNTIL', 'MACRO', 'MEND', 'LET', 'PUT', 'INPUT', 'FORMAT',
    'INFORMAT', 'LENGTH', 'ATTRIB', 'KEEP', 'RENAME', 'QUIT', 'PROC'
})

SQL_FUNCTIONS = frozenset({
    'ISNULL', 'COALESCE', 'CONVERT', 'DATEDIFF', 'ROUND', 'SUM', 'MAX', 'MIN',
    'AVG', 'COUNT', 'CAST', 'SUBSTRING', 'LTRIM', 'RTRIM',
    'UPPER', 'LOWER', 'REPLACE', 'YEAR', 'MONTH', 'DAY', 'DATEPART', 'CHARINDEX', 'PATINDEX'
})

# project.* em heurística BQ genérica (CONNECT TO BIGQUERY)
_BQ_FQTN_EXCLUDE_FIRST = frozenset({
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'ON', 'AND', 'OR', 'CASE', 'WHEN', 'THEN',
    'ELSE', 'END', 'UNION', 'GROUP', 'ORDER', 'HAVING', 'INTO', 'LEFT', 'RIGHT',
    'FULL', 'INNER', 'CROSS', 'OUTER', 'DISTINCT', 'LIMIT', 'OFFSET', 'NOT', 'BETWEEN',
    'WITH', 'AS', 'IN', 'IS', 'NULL', 'LIKE', 'OVER', 'ROW', 'ROWS', 'TRUE', 'FALSE',
    'CAST', 'SET', 'FOR', 'ALL', 'ANY', 'SOME', 'BY', 'AT', 'TO', 'DATE', 'TIME',
    'KEY', 'USE', 'IF',
})

# Engines de conexão para LIBNAME
CONNECTION_ENGINES = (
    'ODBC', 'OLEDB', 'ORACLE', 'TERADATA', 'POSTGRES', 'SQLSERVER', 'SQLSVR', 'MYSQL',
    'DB2', 'SYBASE', 'REDSHIFT', 'SNOWFLAKE', 'BIGQUERY', 'HIVE', 'SPARK', 'HADOOP'
)

# Extensões para heurística de caminho em texto / FILENAME / LIBNAME→ficheiro
_KNOWN_DATA_FILE_EXTENSIONS = (
    'xlsx', 'xlsm', 'xls', 'xlsb', 'csv', 'txt', 'tsv', 'dat', 'zip', 'gz',
    'sas', 'ss2', 'json', 'xml', 'yaml', 'yml', 'parquet', 'orc',
    'sas7bdat', 'sd7', 'rtf', 'pdf', 'htm', 'html', 'mdb', 'accdb',
)
_FILE_EXT_ALT = '|'.join(_KNOWN_DATA_FILE_EXTENSIONS)

# --- CONFIGURAÇÃO DE COMPLEXIDADE (DBT-FIRST) ---
COMPLEXITY_WEIGHTS = {
    'PROC IML': 100,
    'PROC OPTMODEL': 100,
    'PROC LUA': 100,
    'PROC PYTHON': 100,
    'PROC DS2': 90,
    'PROC FCMP': 85,
    'DATA _NULL_': 80,
    'HASH': 70,
    'CALL EXECUTE': 45,
    'MODIFY': 30,
    'PROC FORMAT': 25,
    'PROC HTTP': 25,
    '%INCLUDE': 20,
    'PROC DATASETS': 20,
    'FILENAME ': 12,
    'PROC APPEND': 15,
    'PROC COPY': 15,
    'PROC REG': 15,
    'PROC SUMMARY': 12,
    'INFILE ': 10,
    'PROC COMPARE': 10,
    'PROC CONTENTS': 10,
    'DO UNTIL': 40,
    'DO WHILE': 40,
    'GOTO': 40,
    'ARRAY': 15,
    'RETAIN': 10,
    'PROC TRANSPOSE': 10,
    '%MACRO': 5,
    'PROC SQL': 0,
    'MERGE': 0,
    'SET': 0
}

# --- Indicadores de natureza consultiva (propósito do código; independente de COMPLEXITY_WEIGHTS / TARGET_ARCH) ---
CONSULTIVE_INDICATORS = {
    'positive_proc': {
        'PROC PRINT': 4,
        'PROC REPORT': 5,
        'PROC TABULATE': 5,
        'PROC FREQ': 4,
        'PROC MEANS': 4,
        'PROC UNIVARIATE': 4,
        'PROC GCHART': 3,
        'PROC SGPLOT': 4,
    },
    'ods_destination_weight': {
        'PDF': 6,
        'HTML': 4,
        'HTML5': 4,
        'PHTML': 4,
        'LISTING': 2,
        'EXCEL': 6,
        'EXCELXP': 5,
        'RTF': 5,
        'WORD': 5,
        'POWERPOINT': 5,
        'TAGSETS.EXCELXP': 5,
    },
    'proc_export_document': 5,
    'negative': {
        'create_table_perm': 10,
        'insert_into': 6,
        'update_sql': 6,
        'delete_from': 6,
        'proc_append': 8,
        'data_perm_output': 7,
    },
}

# Bónus quando não há saídas permanentes lib.membro (alinhado a relatórios só leitura / ODS)
CONSULTIVE_PERM_OUTPUTS_EMPTY_BONUS = 15

# Extensões consideradas saída “documento” (não tabela SAS nativa) em PROC EXPORT
_CONSULTIVE_DOC_EXPORT_EXTS = frozenset({
    'pdf', 'htm', 'html', 'xlsx', 'xlsm', 'xls', 'xlsb', 'rtf', 'doc', 'docx',
    'odt', 'ppt', 'pptx', 'csv', 'txt', 'xml', 'lst',
})


def get_flow_execution_order(container_element):
    if container_element is None:
        return []

    elements = container_element.findall(".//Element")
    all_nodes = set()
    for el in elements:
        eid = el.get("ID")
        if not eid:
            id_child = el.find("ID")
            if id_child is not None and id_child.text:
                eid = id_child.text.strip()
        if eid:
            all_nodes.add(normalize_id(eid))

    adj_list = defaultdict(list)
    in_degree = {node: 0 for node in all_nodes}

    links = container_element.findall(".//Link")
    for link in links:
        u = normalize_id(link.get("From"))
        v = normalize_id(link.get("To"))

        if u in all_nodes and v in all_nodes:
            adj_list[u].append(v)
            in_degree[v] += 1

    queue = deque([node for node in all_nodes if in_degree[node] == 0])
    sorted_order = []

    while queue:
        u = queue.popleft()
        sorted_order.append(u)
        for v in adj_list[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    leftovers = all_nodes - set(sorted_order)
    if leftovers:
        sorted_order.extend(sorted(list(leftovers)))

    return sorted_order


def get_pfd_execution_order(scope_element):
    """
    SAS EG 7.x: fluxo em <PFD><Process><Element><ID>CodeTask-...</ID> com <Dependencies><DepID>.
    IDs no XML são normalizados; pastas no ZIP são .../CodeTask-xxx/code.sas — ver resolve_code_buffer_key.
    """
    if scope_element is None:
        return []
    pfd = scope_element.find(".//PFD")
    if pfd is None:
        return []

    proc_list = []
    for proc in pfd.findall("Process"):
        tid = None
        elwrap = proc.find("Element")
        if elwrap is not None:
            id_el = elwrap.find("ID")
            if id_el is not None and id_el.text:
                tid = normalize_id(id_el.text.strip())
        proc_list.append((proc, tid))

    all_nodes = set()
    for _proc, tid in proc_list:
        if tid:
            all_nodes.add(tid)

    adj_list = defaultdict(list)
    in_degree = {n: 0 for n in all_nodes}

    for proc, tid in proc_list:
        if not tid:
            continue
        for dep in proc.findall("Dependencies/DepID"):
            if not dep.text:
                continue
            d = normalize_id(dep.text.strip())
            if d not in all_nodes:
                all_nodes.add(d)
                in_degree[d] = 0
            adj_list[d].append(tid)
            in_degree[tid] += 1

    queue = deque([node for node in all_nodes if in_degree[node] == 0])
    sorted_order = []
    while queue:
        u = queue.popleft()
        sorted_order.append(u)
        for v in adj_list[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    leftovers = all_nodes - set(sorted_order)
    if leftovers:
        sorted_order.extend(sorted(list(leftovers)))
    return sorted_order


def build_code_buffer_task_tail_index(code_buffer):
    """Mapeia codetask-xxx (último segmento do path do ZIP) -> chave normalizada em code_buffer."""
    m = {}
    for k in code_buffer:
        segs = k.replace("\\", "/").rstrip("/").split("/")
        if segs:
            m[normalize_id(segs[-1])] = k
    return m


def resolve_code_buffer_key(guid, code_buffer, task_tail_index):
    if not guid:
        return None
    if guid in code_buffer:
        return guid
    return task_tail_index.get(guid)


def clean_sas_code_flow_linked_only(code_buffer, flow_orders):
    """
    Código SAS só de nós que pertencem a algum Container/fluxo do project.xml.
    EG 7.x: fluxos PFD dentro de Element; IDs CodeTask-xxx alinhados ao último segmento do path no ZIP.
    Se não houver fluxos definidos (flow_orders vazio), usa todo o code_buffer (paridade com EGP sem lineage).
    Se houver fluxos mas nenhum código casar, não faz fallback para órfãos (evita falsos IMPORTED FILES).
    """
    if not code_buffer:
        return ""
    task_tail_index = build_code_buffer_task_tail_index(code_buffer)
    parts = []
    for flow_name in sorted(flow_orders.keys()):
        for guid in flow_orders[flow_name]:
            key = resolve_code_buffer_key(guid, code_buffer, task_tail_index)
            if key and key in code_buffer:
                parts.append(code_buffer[key])
    joined = "\n".join(parts)
    cleaned = remove_sas_comments(joined)
    if not flow_orders:
        if not cleaned.strip():
            cleaned = remove_sas_comments("\n".join(code_buffer.values()))
    return cleaned


def analyze_complexity(sas_code, source_type=""):
    if source_type == 'SQL Query':
        # Pass-through NÃO é SQL nativo. `CONNECT TO` / `EXECUTE (...)` mandam o comando
        # para Sybase/SQL Server/BigQuery por fora do SAS, com o dialeto DELES. Declarar
        # DBT_BQ aqui fazia o conversor tentar gerar BigQuery a partir de código que nem
        # é SAS — e o task de Query Builder passa por aqui com source_type 'SQL Query'
        # mesmo quando o corpo é pass-through. Reusa o mesmo detector que o inventário
        # de inputs já aplica (has_passthrough_sql). 70 é o limiar de DATABRICKS abaixo.
        if has_passthrough_sql(sas_code):
            return "DATABRICKS", 70, "SQL pass-through em task de SQL Query"
        return "DBT_BQ", 0, "Native SQL"

    upper_code = sas_code.upper()
    raw_score = 0
    reasons = []

    for keyword, weight in COMPLEXITY_WEIGHTS.items():
        count = upper_code.count(keyword)
        if count > 0 and weight > 0:
            points = count * weight
            raw_score += points
            reasons.append(f"{keyword} ({count}x | +{points})")

    final_score = min(raw_score, 100)

    if final_score >= 70:
        target = "DATABRICKS"
    else:
        target = "DBT_BQ"

    if final_score == 0:
        reasons_str = "Standard Logic (SQL Compatible)"
    else:
        reasons_str = ", ".join(reasons)

    return target, final_score, reasons_str


def analyze_macro_scopes(text):
    if not text: return [], []

    global_stmts = re.findall(r'%global\s+([^;]+);', text, re.IGNORECASE)
    explicit_globals = set()
    for g_block in global_stmts:
        vars_in_block = g_block.replace(',', ' ').split()
        for v in vars_in_block:
            clean_v = v.strip().upper()
            if clean_v and not clean_v.startswith('&'):
                explicit_globals.add(clean_v)

    macro_defs = re.findall(r'%macro\s+[a-zA-Z0-9_]+\s*\(([^)]*)\)', text, re.IGNORECASE)
    macro_params = set()
    for params in macro_defs:
        raw_list = params.split(',')
        for p in raw_list:
            p_name = p.split('=')[0].strip().upper()
            if p_name:
                macro_params.add(p_name)

    return sorted(list(explicit_globals)), sorted(list(macro_params))


def clean_table_token(token):
    clean_token = re.sub(r'[\(\)\[\]\{\}\'\"`]', '', token)
    clean_token = clean_token.rstrip(',;')
    clean_token = clean_token.split('/*')[0].split('//')[0].split('--')[0]
    clean_token = clean_token.strip().upper()
    # SAS: '.' imediato após &macro termina a referência (ex.: CARNEIRO.BASE_3040_&SAFRA. → vírgula vazia no split)
    parts = clean_token.split('.')
    while len(parts) > 1 and parts[-1] == '':
        parts = parts[:-1]
    return '.'.join(parts).strip().upper()


def is_valid_table(name):
    if not name or name.isdigit(): return False
    if len(name) <= 1: return False

    if not re.match(r'^[A-Z_&][A-Z0-9_.&\-]*$', name, re.IGNORECASE):
        return False

    parts = name.split('.')
    # Rejeita 'WORK.', 'Z6.', 'YYMMN6.' (formatos SAS após vírgula) e 'lib..'
    if any(not (p or '').strip() for p in parts):
        return False
    if len(parts) > 1:
        if len(parts[0]) == 1:  # Bloqueia A.Tabela, mas aceita PE.Tabela
            return False

    first_part = parts[0]
    if first_part.upper() in SQL_RESERVED or name.upper() in SQL_RESERVED: return False
    if first_part.upper() in SQL_FUNCTIONS or name.upper() in SQL_FUNCTIONS: return False
    if first_part.upper() in {'CONNECTION'}: return False

    return True


_DATASTEP_READ_SKIP_TOKENS = frozenset({
    'BY', 'END', 'WHERE', 'OR', 'AND', 'NOT', 'NULL', 'THEN', 'ELSE', 'TO', 'DO',
    'DROP', 'KEEP', 'FIRSTOBS', 'OBS', 'IN', 'INDEX', 'KEY', 'UNIQUE', 'NOBS', 'POINT',
    'CNTLLEV', 'GENMAX', 'GENNUM', 'LABEL', 'RENAME', 'KEYRESET',
})

def _slice_balanced_parens(text, open_pos):
    """open_pos no carácter '('. Devolve (interior, posição após ')') de fecho correspondente."""
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != '(':
        return '', open_pos
    depth = 0
    for i in range(open_pos, len(text)):
        c = text[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[open_pos + 1:i], i + 1
    return text[open_pos + 1:], len(text)


def _leading_dataset_name(raw_token):
    """Nome até primeiro espaço ou '(' (opções SAS tipo (WHERE=)); suporta `quoted`."""
    raw_token = raw_token.strip().strip(',').rstrip(';')
    if not raw_token:
        return ''
    if raw_token.startswith('`'):
        j = raw_token.find('`', 1)
        return raw_token[1:j] if j > 1 else ''
    m = re.match(r'^([A-Za-z0-9_&.\-]+)', raw_token)
    return m.group(1) if m else ''


def _capture_sql_table_token_at(text, pos):
    if pos >= len(text):
        return None
    if text[pos] == '`':
        j = text.find('`', pos + 1)
        return text[pos + 1:j] if j > pos else None
    m = re.match(r'([A-Za-z0-9_&.\-]+)', text[pos:])
    return m.group(1) if m else None


# match(s, pos) — nunca usar re.match(pat, s[i:]) num loop: cópia O(n) × i ⇒ O(n²).
_WITH_SQL_PREFIX_RE = re.compile(r'(?is)\Awith\s+')
_SELECT_AT_POS_RE = re.compile(r'\bselect\b', re.IGNORECASE)


def _strip_with_clause_for_from_scan(sql_one_line):
    """
    Remove o prefixo WITH ... até ao primeiro SELECT ao nível superior (fora de parênteses),
    para localizar o SELECT principal e as suas cláusulas FROM.
    """
    s = (sql_one_line or '').strip()
    m = _WITH_SQL_PREFIX_RE.match(s)
    if not m:
        return s
    i = m.end()
    n = len(s)
    depth = 0
    while i < n:
        c = s[i]
        if c == '(':
            depth += 1
            i += 1
        elif c == ')':
            depth -= 1
            i += 1
        elif depth == 0:
            if _SELECT_AT_POS_RE.match(s, i):
                return s[i:].strip()
            i += 1
        else:
            i += 1
    return s


def _register_qualified_table_read(raw_token, source_tag, inputs, work_reads, provenance):
    base = _leading_dataset_name(raw_token)
    if not base:
        return
    token = clean_table_token(base)
    if not token or '.' not in token or not is_valid_table(token):
        return
    inputs.add(token)
    provenance.setdefault(token, set()).add(source_tag)
    if token.upper().startswith('WORK.'):
        work_reads.add(token)


def _collect_datastep_set_merge_update(text_clean, inputs, work_reads, provenance):
    for kw, tag in (
        (r'\bSET\s+', 'DATA Step - SET'),
        (r'\bMERGE\s+', 'DATA Step - MERGE'),
        (r'\bUPDATE\s+', 'DATA Step - UPDATE'),
    ):
        for m in re.finditer(kw + r'([^;]+);', text_clean, re.IGNORECASE):
            clause = m.group(1).strip()
            if kw == r'\bUPDATE\s+':
                if re.search(r'\bSET\s+[A-Za-z_][A-Za-z0-9_]*\s*=', clause, re.IGNORECASE):
                    continue
            else:
                if '=' in clause and not re.search(r'\([^)]*=', clause):
                    continue
                # Não usar WHERE aqui: (WHERE=(...)) em opções de dataset dispara falso positivo.
                if re.search(
                    r'\b(?:SELECT|FROM|JOIN|DECLARE|EXECUTE)\b', clause, re.IGNORECASE
                ):
                    continue
            for seg in clause.split(','):
                seg = seg.strip()
                if not seg:
                    continue
                for raw in seg.split():
                    if raw.endswith('=') or re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s*=', raw):
                        continue
                    lead = _leading_dataset_name(raw)
                    up = lead.upper() if lead else ''
                    if not lead or up in _DATASTEP_READ_SKIP_TOKENS:
                        continue
                    if lead.startswith('('):
                        continue
                    _register_qualified_table_read(raw, tag, inputs, work_reads, provenance)


# Janela máx. PROC … RUN/QUIT — evita .*? com re.DOTALL sobre megabytes (pode travar horas).
_PROC_BLOCK_MAX_SPAN = 500_000


def _strip_c_style_block_comments_linear(text):
    """Remove /* … */ em O(n). O regex re.DOTALL com .*? em ficheiros SAS enormes é catastrófico."""
    if not text:
        return ""
    parts = []
    i, n = 0, len(text)
    start = 0
    while i < n:
        if text[i] == '/' and i + 1 < n and text[i + 1] == '*':
            parts.append(text[start:i])
            j = text.find('*/', i + 2)
            if j == -1:
                parts.append(text[i:])
                return ''.join(parts)
            i = j + 2
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return ''.join(parts)


def _iter_proc_blocks_to_run_or_quit(text, proc_token, max_span=None):
    """Fragmentos PROC <token> … RUN;/QUIT; com fim procurado só numa janela (sem DOTALL global)."""
    if max_span is None:
        max_span = _PROC_BLOCK_MAX_SPAN
    if not text:
        return
    rx = re.compile(rf'\bPROC\s+{re.escape(proc_token)}\b', re.IGNORECASE)
    term = re.compile(r'(?:\bRUN\s*;|\bQUIT\s*;)', re.IGNORECASE)
    for m in rx.finditer(text):
        start = m.start()
        window = text[start:start + max_span]
        tm = term.search(window)
        if not tm:
            continue
        yield text[start:start + tm.end()]


def remove_sql_comments(sql_text):
    """Comentários SQL nativos dentro de pass-through (/* */ e -- linha)."""
    if not sql_text:
        return ""
    s = _strip_c_style_block_comments_linear(sql_text)
    s = re.sub(r'--[^\n\r]*', '', s)
    return s


def _pass_through_execute_inner_regions(text_clean):
    """Intervalos [start, end) do interior dos parênteses de FROM CONNECTION TO / EXECUTE (para não re-parse SAS)."""
    regions = []
    for m in re.finditer(r'\bFROM\s+CONNECTION\s+TO\s+[A-Za-z0-9_]+\s*\(', text_clean, re.IGNORECASE):
        open_i = m.end() - 1
        _, close_end = _slice_balanced_parens(text_clean, open_i)
        regions.append((open_i, close_end))
    for m in re.finditer(r'\bEXECUTE\s*\(', text_clean, re.IGNORECASE):
        open_i = m.end() - 1
        _, close_end = _slice_balanced_parens(text_clean, open_i)
        regions.append((open_i, close_end))
    return regions


def _merge_intervals_sorted(iv):
    """Funde [a,b) sobrepostos ou contíguos."""
    if not iv:
        return []
    iv = sorted(iv)
    merged = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(x[0], x[1]) for x in merged]


def _apply_blank_regions(s, regions):
    """
    Substitui cada [a,b) por espaços. Uma cópia por região sobre todo o texto era O(k×len(s))
    e travava projetos com centenas de pass-throughs.
    """
    if not regions or not s:
        return s
    n = len(s)
    iv = [(a, b) for a, b in regions if 0 <= a < b <= n]
    if not iv:
        return s
    iv = _merge_intervals_sorted(iv)
    parts = []
    pos = 0
    for a, b in iv:
        if a > pos:
            parts.append(s[pos:a])
        parts.append(' ' * (b - a))
        pos = b
    parts.append(s[pos:])
    return ''.join(parts)


def _is_valid_native_bare_table(name):
    """Identificador simples em SQL nativo (ex.: dual, temp)."""
    if not name or len(name) < 2:
        return False
    u = name.upper()
    if u in SQL_RESERVED or u in SQL_FUNCTIONS:
        return False
    return bool(re.match(r'^[A-Z_][A-Z0-9_]*$', name, re.IGNORECASE))


def _likely_sql_column_alias_false_positive(token: str) -> bool:
    """
    Heurística: identificadores típicos de coluna DW (CD_*, NM_*, …) sem qualificação schema.tabela
    não são tratados como tabela em pass-through (evita ruído tipo CD_NATUREZA_SOLICITACAO na lista SELECT).
    """
    if not token or "." in token:
        return False
    u = token.upper()
    if re.match(r"^(CD|NM|DS|ID|DT|VL|QT|NR)_[A-Z][A-Z0-9_]*$", u):
        return True
    # DW text / observation columns (e.g. OB_SOLICITACAO) — not bare tables in pass-through.
    if re.match(r"^OB_[A-Z][A-Z0-9_]*$", u):
        return True
    return False


def _register_pass_through_native_table(
    token_raw, engine, source_tag, inputs, work_reads, provenance, pass_through_engine_by_table
):
    """
    Regista leitura vinda de SQL nativo (schema.tabela ou tabela). engine = valor de CONNECT TO (ex.: SYBASEIQ).
    """
    base = _leading_dataset_name(token_raw)
    if not base:
        return
    token = clean_table_token(base)
    if not token:
        return
    if _likely_sql_column_alias_false_positive(token):
        return
    if any(not (p or '').strip() for p in token.split('.')):
        return
    if token.upper().startswith('WORK.'):
        inputs.add(token)
        provenance.setdefault(token, set()).add(source_tag)
        work_reads.add(token)
        return
    if '.' in token:
        if not is_valid_table(token):
            return
    else:
        if not _is_valid_native_bare_table(token):
            return
    inputs.add(token)
    provenance.setdefault(token, set()).add(source_tag)
    pass_through_engine_by_table[token.upper()] = engine.upper()


def _native_sql_from_join_scan(frag, engine, inputs, work_reads, provenance, pass_through_engine_by_table):
    """FROM/JOIN sobre fragmento SQL já limpo (comentários removidos) e colapsado."""
    if not frag:
        return
    frag = re.sub(r'\s+', ' ', frag.strip())
    frag = _strip_with_clause_for_from_scan(frag)
    eng = engine.upper()
    tag_from = f'Pass-Through Native ({eng}) - FROM'
    tag_join = f'Pass-Through Native ({eng}) - JOIN'
    for m in re.finditer(r'\bFROM\s+(?!CONNECTION\s+TO)(?!\()', frag, re.IGNORECASE):
        if not _proc_sql_from_is_table_clause(frag, m.start()):
            continue
        pos = m.end()
        while pos < len(frag) and frag[pos] in ' \t':
            pos += 1
        if pos < len(frag) and frag[pos] == '(':
            continue
        body = _from_clause_body_upto_stop(frag, pos)
        for tok, kind in _tables_from_from_clause_body(body):
            tag = tag_from if kind == 'from' else tag_join
            _register_pass_through_native_table(
                tok, eng, tag, inputs, work_reads, provenance, pass_through_engine_by_table
            )


def _collect_explicit_pass_through_native_sql(
    text_clean, connect_engine_map, inputs, work_reads, provenance, pass_through_engine_by_table
):
    """
    Passo 1–2: FROM CONNECTION TO alias (...) com SQL nativo.
    connect_engine_map: alias/libref -> motor (build_db_mapping inclui CONNECT TO ... AS ...).
    """
    for m in re.finditer(
        r'\bFROM\s+CONNECTION\s+TO\s+([A-Za-z0-9_]+)\s*\(', text_clean, re.IGNORECASE
    ):
        alias = m.group(1).upper()
        engine = connect_engine_map.get(alias, alias)
        open_i = m.end() - 1
        inner, _ = _slice_balanced_parens(text_clean, open_i)
        native = remove_sql_comments(inner)
        native_one = re.sub(r'\s+', ' ', native).strip()
        _native_sql_from_join_scan(
            native_one, engine, inputs, work_reads, provenance, pass_through_engine_by_table
        )
        _register_bq_fqtns_from_native_sql_fragment(
            native_one, engine, inputs, work_reads, provenance, pass_through_engine_by_table
        )


def _collect_execute_native_sql(
    text_clean, inputs, work_reads, provenance, pass_through_engine_by_table
):
    """EXECUTE (... BY ...) — SQL nativo; motor etiquetado EXECUTE se não houver contexto."""
    for m in re.finditer(r'\bEXECUTE\s*\(', text_clean, re.IGNORECASE):
        open_i = m.end() - 1
        inner, _ = _slice_balanced_parens(text_clean, open_i)
        native = remove_sql_comments(inner)
        native_one = re.sub(r'\s+', ' ', native).strip()
        _native_sql_from_join_scan(
            native_one, 'EXECUTE', inputs, work_reads, provenance, pass_through_engine_by_table
        )
        _register_bq_fqtns_from_native_sql_fragment(
            native_one, 'EXECUTE', inputs, work_reads, provenance, pass_through_engine_by_table
        )


# Referência completa ao projeto GCP BigQuery usado nestes EGPs (case-insensitive no match).
_BQ_PASS_THROUGH_FQTN_RE = re.compile(
    r'\b(bv-pdbd-prd)\.([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\b',
    re.IGNORECASE,
)
# project.dataset.table dentro de CONNECT TO BIGQUERY (project com hífen permitido)
_BQ_GENERIC_FQTN_RE = re.compile(
    r'(?i)(?<![`.\w-])'
    r'([a-z][a-z0-9_-]{1,100})\.'
    r'([a-zA-Z_][a-zA-Z0-9_]{0,100})\.'
    r'([a-zA-Z_][a-zA-Z0-9_]{0,100})'
    r'(?![`.\w])',
)


def _fragment_sql_for_bq_ftn_scan(native_one: str) -> str:
    """
    Restringe a deteção de identificadores BQ/SQL a cláusulas FROM/JOIN (corpos) e UPDATE … SET,
    evitando falsos positivos a partir da lista de colunas do SELECT (ex.: colunas tipo CD_*).
    """
    if not native_one:
        return ""
    s = _strip_with_clause_for_from_scan(native_one)
    s = re.sub(r"\s+", " ", s.strip())
    chunks: list[str] = []
    for m in re.finditer(r"\bFROM\s+(?!CONNECTION\s+TO)(?!\()", s, re.IGNORECASE):
        if not _proc_sql_from_is_table_clause(s, m.start()):
            continue
        pos = m.end()
        while pos < len(s) and s[pos] in " \t":
            pos += 1
        if pos < len(s) and s[pos] == "(":
            continue
        body = _from_clause_body_upto_stop(s, pos)
        if body:
            chunks.append(body)
    for m in re.finditer(r"\bUPDATE\s+([`A-Za-z0-9_.\-]+)\s+SET\b", s, re.IGNORECASE):
        chunks.append(m.group(1).strip())
    return " ".join(chunks)


def _register_bq_fqtns_from_native_sql_fragment(
    native_one, connect_context_engine, inputs, work_reads, provenance, pass_through_engine_by_table
):
    """
    bv-pdbd / project.dataset.table só em regiões FROM/JOIN/UPDATE (não no SELECT).
    """
    if not native_one:
        return
    eng_u = (connect_context_engine or "").upper()
    snippet = _fragment_sql_for_bq_ftn_scan(native_one)
    if eng_u != "BIGQUERY" and "BV-PDBD-PRD" not in snippet.upper() and "BV-PDBD-PRD" not in native_one.upper():
        return
    if not snippet.strip() and eng_u != "BIGQUERY":
        return
    scan_text = snippet if snippet.strip() else native_one
    ctx_tag = eng_u if eng_u else "BIGQUERY"
    tag_bv = f"Pass-Through Native ({ctx_tag}) - BQ fully-qualified identifier"
    tag_gen = f"Pass-Through Native ({ctx_tag}) - BQ inferred 3-part identifier"
    seen = set()
    for m in _BQ_PASS_THROUGH_FQTN_RE.finditer(scan_text):
        fqtn = f"{m.group(1).upper()}.{m.group(2).upper()}.{m.group(3).upper()}"
        seen.add(fqtn)
        _register_pass_through_native_table(
            fqtn,
            "BIGQUERY",
            tag_bv,
            inputs,
            work_reads,
            provenance,
            pass_through_engine_by_table,
        )
    if eng_u == "BIGQUERY":
        for m in _BQ_GENERIC_FQTN_RE.finditer(scan_text):
            p1, p2, p3 = m.group(1), m.group(2), m.group(3)
            if p1.upper() in _BQ_FQTN_EXCLUDE_FIRST:
                continue
            fqtn = f"{p1.upper()}.{p2.upper()}.{p3.upper()}"
            if fqtn in seen:
                continue
            seen.add(fqtn)
            _register_pass_through_native_table(
                fqtn,
                "BIGQUERY",
                tag_gen,
                inputs,
                work_reads,
                provenance,
                pass_through_engine_by_table,
            )


def _proc_sql_from_is_table_clause(frag, from_match_start):
    """
    True se FROM inicia cláusula de tabela (FROM x / FROM x,y).
    False para SAS: DISCONNECT FROM libref — caso contrário \\bFROM\\b dispara
    e o 'corpo' até ao próximo WHERE engole o SELECT inteiro (falsos Z6., YYMMN6., etc.).
    """
    i = from_match_start - 1
    while i >= 0 and frag[i] in ' \t':
        i -= 1
    j = i
    while j >= 0 and (frag[j].isalnum() or frag[j] in '_'):
        j -= 1
    prev = frag[j + 1:i + 1].upper()
    return prev != 'DISCONNECT'


_FROM_CLAUSE_STOP_RE = re.compile(
    r'\b(?:WHERE|SELECT|GROUP|ORDER|HAVING|UNION|EXCEPT|INTERSECT|FETCH|OFFSET)\b',
    re.IGNORECASE,
)


def _from_clause_body_upto_stop(frag, start_pos):
    """
    Texto após FROM até um delimitador em profundidade de parênteses 0.

    Inclui SELECT como parada: em T-SQL colado sem ';' aparece
    ``INTO #04 FROM #03 SELECT DISTINCT ...``; o primeiro WHERE pode estar só no
    segundo SELECT — o corpo do FROM não pode engolir a lista de colunas (falsos
    positivos tipo OB_SOLICITACAO, A.NU_SOLICITACAO como "tabelas").
    Literais entre aspas simples ignoram parênteses (evita depth falso em strings).

    Subconsultas: ``SELECT`` dentro de ``( ... )`` não corta o corpo do FROM
    (depth > 0). Cada ``FROM`` no fragmento continua a ser encontrado pelo scan
    global; tabelas em subconsultas (ex.: ``FROM t`` dentro de ``JOIN (SELECT ...
    FROM t)``) não deixam de ser registadas. O match ``FROM (SELECT ...)`` em que o
    ``(`` segue imediatamente a ``FROM`` mantém-se excluído à parte; o ``FROM``
    interior é tratado noutra ocorrência.
    """
    rest = frag[start_pos:]
    if not rest or not rest.strip():
        return ""
    depth = 0
    i = 0
    n = len(rest)
    in_squote = False
    while i < n:
        c = rest[i]
        if in_squote:
            if c == "'" and i + 1 < n and rest[i + 1] == "'":
                i += 2
                continue
            if c == "'":
                in_squote = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth = max(0, depth - 1)
        elif depth == 0:
            m = _FROM_CLAUSE_STOP_RE.match(rest, i)
            if m:
                return rest[:i].strip()
        i += 1
    return rest.strip()


def _tables_from_from_clause_body(body):
    """
    Extrai tabelas de `a, b JOIN c JOIN d` (OUTER em JOIN, split por profundidade).
    """
    body = (body or '').strip()
    if not body or body.startswith('('):
        return []
    parts = re.split(
        r'\b(?:NATURAL\s+)?(?:(?:LEFT|RIGHT|FULL|INNER|OUTER|CROSS)\s+)?JOIN\b',
        body,
        flags=re.IGNORECASE,
    )
    found = []
    first = parts[0].strip()
    for seg in first.split(','):
        seg = seg.strip()
        if not seg or seg.startswith('('):
            continue
        tok = _capture_sql_table_token_at(seg, 0)
        if tok:
            found.append((tok, 'from'))
    for p in parts[1:]:
        p = p.strip()
        if not p or p.startswith('('):
            continue
        tok = _capture_sql_table_token_at(p, 0)
        if tok:
            found.append((tok, 'join'))
    return found


def _sql_from_join_in_fragment(fragment, tag_from, tag_join, inputs, work_reads, provenance):
    if not fragment:
        return
    frag = re.sub(r'\s+', ' ', fragment)
    frag = _strip_with_clause_for_from_scan(frag)
    for m in re.finditer(r'\bFROM\s+(?!CONNECTION\s+TO)(?!\()', frag, re.IGNORECASE):
        if not _proc_sql_from_is_table_clause(frag, m.start()):
            continue
        pos = m.end()
        while pos < len(frag) and frag[pos] in ' \t':
            pos += 1
        if pos < len(frag) and frag[pos] == '(':
            continue
        body = _from_clause_body_upto_stop(frag, pos)
        for tok, kind in _tables_from_from_clause_body(body):
            tag = tag_from if kind == 'from' else tag_join
            _register_qualified_table_read(tok, tag, inputs, work_reads, provenance)


def _collect_proc_data_equals(text_clean, inputs, work_reads, provenance):
    for m in re.finditer(r'\bPROC\s+([A-Za-z0-9_]+)\b', text_clean, re.IGNORECASE):
        start = m.start()
        end = text_clean.find(';', start)
        if end < 0:
            end = len(text_clean)
        chunk = text_clean[start:end]
        proc = m.group(1).upper()
        dm = re.search(r'\bDATA\s*=\s*([A-Za-z0-9_.\-&]+|`[^`]+`)', chunk, re.IGNORECASE)
        if not dm:
            continue
        tag = f'PROC {proc} - DATA='
        _register_qualified_table_read(dm.group(1), tag, inputs, work_reads, provenance)


def _collect_proc_sql_from_join(sas_sql_scan_text, inputs, work_reads, provenance):
    """Um passe: blocos PROC SQL já estão no texto com pass-through em branco."""
    _sql_from_join_in_fragment(
        sas_sql_scan_text, 'PROC SQL - FROM', 'PROC SQL - JOIN', inputs, work_reads, provenance
    )


def _format_table_read_provenance(provenance):
    if not provenance:
        return None
    parts = []
    for tbl in sorted(provenance.keys(), key=str.upper):
        tags = '; '.join(sorted(provenance[tbl]))
        parts.append(f'{tbl} [{tags}]')
    return 'TABLE_READ_PROVENANCE (Flow): ' + ', '.join(parts)


def _prescan_connect_to_aliases_in_raw_text(full_text):
    """
    Texto SAS bruto (antes de remove_sas_comments): captura CONNECT TO motor AS alias.
    Exportações SAS costumam deixar a macro ConexaoIQ (com o connect real) dentro de /* */,
    que depois some — assim ainda resolvemos DBCON -> SASIOSIQ para FROM CONNECTION TO dbcon.
    build_db_mapping(código ativo) sobrescreve a mesma chave se existir.
    """
    found = {}
    if not full_text:
        return found
    for m in re.finditer(
        r'\bCONNECT\s+TO\s+([A-Za-z0-9_]+)(?:\s+AS\s+([A-Za-z0-9_]+))?',
        full_text,
        re.IGNORECASE,
    ):
        engine = m.group(1).upper()
        alias = m.group(2).upper() if m.group(2) else engine
        found[alias] = engine
    return found


def normalize_sas_let_value(raw):
    v = (raw or '').strip()
    if not v:
        return ''
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        v = v[1:-1].strip()
    return v.strip()


def build_let_dictionary_from_sas_text(sas_text):
    """
    Último %LET por nome no texto (ordem de ocorrência). Chaves UPPER.
    """
    if not sas_text:
        return {}
    out = {}
    for name, value in re.findall(
        r'%LET\s+([A-Za-z0-9_]+)\s*=\s*([^;]*);', sas_text, re.IGNORECASE | re.DOTALL
    ):
        nu = name.upper()
        if nu in LET_EXCLUDED_NAMES:
            continue
        out[nu] = normalize_sas_let_value(value)
    return out


def build_let_dictionary_from_project_xml(xml_text):
    if not xml_text:
        return {}
    text = xml_text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return build_let_dictionary_from_sas_text(text)


def merge_project_and_code_let_dictionaries(xml_lets, code_lets):
    """Valores do código SAS sobrescrevem os do project.xml para o mesmo nome."""
    merged = dict(xml_lets or {})
    merged.update(code_lets or {})
    return merged


def _split_macro_args_depth_zero(inner):
    """Divide argumentos de chamada macro por vírgulas ao nível superior (prof. parênteses 0)."""
    inner = inner or ''
    parts = []
    cur = []
    depth = 0
    in_squote = False
    i = 0
    n = len(inner)
    while i < n:
        c = inner[i]
        if in_squote:
            if c == "'" and i + 1 < n and inner[i + 1] == "'":
                cur.append("'")
                cur.append("'")
                i += 2
                continue
            if c == "'":
                in_squote = False
            cur.append(c)
            i += 1
            continue
        if c == "'":
            in_squote = True
            cur.append(c)
            i += 1
            continue
        if c == '(':
            depth += 1
            cur.append(c)
        elif c == ')':
            depth = max(0, depth - 1)
            cur.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        parts.append(''.join(cur).strip())
    return parts


def _resolve_sas_macro_arg_to_literal(token, lets):
    """
    Expande referências &MACRO num fragmento que é um argumento SAS (remove ``.``
    terminal típico de ``&VAR.`` antes de falhar na 1ª tentativa).
    """
    if not token or not lets:
        return None
    t = token.strip()
    exp = _try_expand_macro_refs_in_identifier(t, lets)
    if exp:
        return exp
    if t.endswith('.'):
        exp2 = _try_expand_macro_refs_in_identifier(t[:-1], lets)
        if exp2:
            return exp2
    return None


_PROC_SAFRA_INVOCATION_RE = re.compile(r'%\s*PROC_SAFRA\s*\(', re.IGNORECASE)


def proc_safra_runtime_safra_literals_from_text(text, lets):
    """
    Valores literais passados ao 2.º argumento de ``%PROC_SAFRA(...)`` (parâmetro SAFRA),
    para alinhar criações ``UNIAO_GERAL_&SAFRA._2`` a leituras ``UNIAO_GERAL_&V_DT_AAAAMM_M2._2``.
    Tupla ordenada única para uso em ``_resolve_io_token_keys``.
    """
    if not text or not lets:
        return ()
    seen = set()
    ordered = []
    for m in _PROC_SAFRA_INVOCATION_RE.finditer(text):
        open_paren = m.end() - 1
        inner, _ = _slice_balanced_parens(text, open_paren)
        if not inner:
            continue
        args = _split_macro_args_depth_zero(inner)
        if len(args) < 2:
            continue
        lit = _resolve_sas_macro_arg_to_literal(args[1], lets)
        if not lit or '&' in lit or '%' in lit:
            continue
        lu = lit.upper().rstrip('.')
        if lu not in seen:
            seen.add(lu)
            ordered.append(lu)
    return tuple(ordered)


def _try_expand_macro_refs_in_identifier(name, lets):
    """
    Substitui &MACRO por valor do dicionário lets (chaves upper). Devolve None se ficar & ou % residual.
    """
    if not name or not lets:
        return None
    if '&' not in name:
        return name.upper()

    def repl(m):
        k = m.group(1).upper()
        if k not in lets:
            return m.group(0)
        v = normalize_sas_let_value(lets[k])
        if not v or any(c in v for c in '&%'):
            return m.group(0)
        return v

    new = re.sub(r'&([A-Za-z0-9_]+)\b', repl, name, flags=re.IGNORECASE)
    if '&' in new or '%' in new:
        return None
    return new.upper()


def _resolve_qualified_read_token_with_lets(tok, lets):
    """CARNEIRO.BASE_3040_&SAFRA → CARNEIRO.BASE_3040_202601 quando SAFRA está em lets."""
    base = clean_table_token(_leading_dataset_name(tok))
    if not base or '.' not in base or '&' not in base:
        return None
    lib, mem = base.split('.', 1)
    resolved_mem = _try_expand_macro_refs_in_identifier(mem, lets)
    if not resolved_mem:
        return None
    cand = f'{lib.upper()}.{resolved_mem}'
    return cand if is_valid_table(cand) else None


def _resolve_output_token_with_lets(raw_token, lets):
    """Membro ou lib.membro com & → nome resolvido; devolve original se não resolver."""
    if not raw_token or not lets or '&' not in raw_token:
        return raw_token
    base = clean_table_token(raw_token)
    if not base:
        return raw_token
    if '.' in base:
        lib, mem = base.split('.', 1)
        rm = _try_expand_macro_refs_in_identifier(mem, lets)
        if rm:
            cand = f'{lib.upper()}.{rm}'
            if is_valid_table(cand):
                return cand
        return raw_token
    ru = _try_expand_macro_refs_in_identifier(base, lets)
    if ru and _SAS_OUTPUT_MEMBER_TOKEN_RE.match(ru):
        return ru
    return raw_token


def _apply_let_resolution_to_io_scan(inputs, dynamic_tables, work_table_reads, provenance, lets):
    """
    Promove leituras dinâmicas/ com & a tokens estáticos quando todos os macros resolvem via lets.
    Atualiza inputs, work_table_reads, provenance e reduz dynamic_tables.
    """
    if not lets:
        return

    _TAG_RES_DYN = 'Resolved dynamic lib.member&macro (%LET)'
    _TAG_RES_AMP = 'Resolved qualified read (%LET)'

    still_dynamic = set()
    for dyn in dynamic_tables:
        d = (dyn or '').strip().upper()
        m = re.match(r'^([A-Z0-9_]+)\.([A-Z0-9_]+)\{([A-Z0-9_]+)\}$', d)
        if m:
            lib_u, pref, mac = m.group(1), m.group(2), m.group(3)
            if mac not in lets:
                still_dynamic.add(dyn)
                continue
            suf = normalize_sas_let_value(lets[mac]).strip().upper()
            if not suf or any(c in suf for c in '&%.'):
                still_dynamic.add(dyn)
                continue
            resolved = f'{lib_u}.{pref}{suf}'
            if not is_valid_table(resolved):
                still_dynamic.add(dyn)
                continue
            inputs.add(resolved)
            provenance.setdefault(resolved, set()).add(_TAG_RES_DYN)
            if resolved.startswith('WORK.'):
                work_table_reads.add(resolved)
            continue
        m2 = re.match(r'^\{([A-Z0-9_]+)\}\.([A-Z0-9_]+)$', d)
        if m2:
            mac_lib, mac_tab = m2.group(1), m2.group(2)
            if mac_lib not in lets or mac_tab not in lets:
                still_dynamic.add(dyn)
                continue
            lib_part = normalize_sas_let_value(lets[mac_lib]).strip().upper()
            tab_part = normalize_sas_let_value(lets[mac_tab]).strip().upper()
            if not lib_part or not tab_part or any(c in lib_part + tab_part for c in '&%'):
                still_dynamic.add(dyn)
                continue
            resolved = f'{lib_part}.{tab_part}'
            if not is_valid_table(resolved):
                still_dynamic.add(dyn)
                continue
            inputs.add(resolved)
            provenance.setdefault(resolved, set()).add(_TAG_RES_DYN)
            if resolved.startswith('WORK.'):
                work_table_reads.add(resolved)
            continue
        still_dynamic.add(dyn)

    dynamic_tables.clear()
    dynamic_tables.update(still_dynamic)

    extra_reads = set()
    for t in list(inputs):
        if '&' not in t:
            continue
        r = _resolve_qualified_read_token_with_lets(t, lets)
        if r:
            extra_reads.add(r)
            tags = provenance.pop(t, None)
            if tags:
                provenance.setdefault(r, set()).update(tags)
            pr = provenance.setdefault(r, set())
            if _TAG_RES_DYN not in pr:
                pr.add(_TAG_RES_AMP)
            if r.startswith('WORK.'):
                work_table_reads.add(r)
    inputs.update(extra_reads)
    drop = {t for t in list(inputs) if '&' in t and _resolve_qualified_read_token_with_lets(t, lets)}
    for t in drop:
        inputs.discard(t)


def scan_sas_dependencies(full_text, let_values=None):
    """
    Devolve:
      macros_used, macros_def, inputs, outputs, dynamic_tables,
      work_table_reads (lib.membro WORK.*), table_read_provenance (str ou None),
      pass_through_engine_by_table (dict: tabela.upper() -> motor CONNECT TO, ex.: SYBASEIQ).

    Leituras de tabela: comentários SAS removidos antes do scan; SQL nativo em pass-through
    com comentários SQL removidos e motor resolvido via CONNECT TO ... AS ...
    V6: bv-pdbd-prd.*.* e (em CONNECT TO BIGQUERY) project.dataset.table genérico no pass-through.
    Outputs só-MEMBRO ficam não qualificados (WORK implícita) — nunca promovidos a
    LIB.membro por evidência de leitura (fix 2026-08-11; antiga heurística V6 removida).
    V8: let_values (dict nome_macro UPPER → valor) expande lib.membro&mac, leituras com & e reduz DYNAMIC REFS.
    """
    if not full_text:
        return [], [], [], [], [], [], None, {}

    connect_prescan = _prescan_connect_to_aliases_in_raw_text(full_text)
    base = remove_sas_comments(full_text)
    # Colapso: um único scan linear no motor regex (inputs/leituras), troca memória extra por velocidade.
    text_clean = re.sub(r'\s+', ' ', base)

    lets = let_values if let_values is not None else build_let_dictionary_from_sas_text(base)

    macros_used = set(re.findall(r'&([a-zA-Z0-9_]+)', base))
    macros_defined = set(re.findall(r'%let\s+([A-Za-z0-9_]+)\s*=', base, re.IGNORECASE))

    inputs = set()
    outputs = set()
    dynamic_tables = set()
    work_table_reads = set()
    provenance = defaultdict(set)
    pass_through_engine_by_table = {}

    connect_engine_map = build_db_mapping(base)
    for _al, _eng in connect_prescan.items():
        connect_engine_map.setdefault(_al, _eng)
    _collect_explicit_pass_through_native_sql(
        text_clean, connect_engine_map, inputs, work_table_reads, provenance, pass_through_engine_by_table
    )
    _collect_execute_native_sql(
        text_clean, inputs, work_table_reads, provenance, pass_through_engine_by_table
    )
    sas_sql_scan_text = _apply_blank_regions(text_clean, _pass_through_execute_inner_regions(text_clean))

    for m in re.finditer(r'\bDATA\s+([^;]+);', text_clean, re.IGNORECASE):
        content = m.group(1).strip()
        if '=' in content and not re.search(r'\([^)]*=', content):
            continue
        if re.search(r'\b(?:SELECT|FROM|WHERE|JOIN|DECLARE|EXECUTE)\b', content, re.IGNORECASE):
            continue

        content = re.sub(r'\([^)]*\)', '', content)
        for raw_token in content.split():
            token = clean_table_token(raw_token)
            if is_valid_table(token) and token != '_NULL_':
                outputs.add(token)

    for m in re.finditer(
        r'\b(?:CREATE\s+TABLE|CREATE\s+VIEW|INSERT\s+INTO|UPDATE|MODIFY)\s+([A-Za-z0-9_.\-&]+)',
        text_clean, re.IGNORECASE
    ):
        token = clean_table_token(m.group(1))
        if is_valid_table(token):
            outputs.add(token)

    for m in re.finditer(r'\b(?:OUT|BASE)\s*=\s*([A-Za-z0-9_.\-&]+)', text_clean, re.IGNORECASE):
        token = clean_table_token(m.group(1))
        if is_valid_table(token):
            outputs.add(token)

    for m in re.finditer(
        r'\b(?:CREATE\s+(?:TABLE|VIEW)|INSERT\s+INTO|UPDATE|MODIFY)\s+`([^`]+)`', base, re.IGNORECASE
    ):
        token = clean_table_token(m.group(1))
        if is_valid_table(token):
            outputs.add(token)

    # Não usar [^;]+ entre IMPORT e OUT= no texto inteiro — retrocesso com blocos enormes sem ';'.
    for blk in _iter_proc_blocks_to_run_or_quit(base, 'IMPORT'):
        for m in re.finditer(r'\bOUT\s*=\s*([A-Z0-9_.]+)', blk, re.IGNORECASE):
            token = clean_table_token(m.group(1))
            if is_valid_table(token):
                outputs.add(token)

    _collect_datastep_set_merge_update(text_clean, inputs, work_table_reads, provenance)
    _collect_proc_data_equals(text_clean, inputs, work_table_reads, provenance)
    _collect_proc_sql_from_join(sas_sql_scan_text, inputs, work_table_reads, provenance)

    for m in re.finditer(r'\b(?:SET|MERGE)\s+`([^`]+)`', base, re.IGNORECASE):
        token = clean_table_token(m.group(1))
        if is_valid_table(token) and '.' in token:
            _register_qualified_table_read(
                m.group(1), 'DATA Step - SET/MERGE (backtick)', inputs, work_table_reads, provenance
            )

    for p in _gather_explicit_file_paths_from_sas_code(base):
        u = p.strip()
        if len(u) > 3:
            inputs.add(u.upper())

    dynamic_matches = re.findall(r'&([A-Za-z0-9_]+)\.\.([A-Za-z0-9_]+)', text_clean)
    for m_lib, m_tab in dynamic_matches:
        dynamic_tables.add(f'{{{m_lib.upper()}}}.{m_tab.upper()}')

    # lib.membro&macro (membro ≤32 chars SAS; ver _LIB_MEMBER_AMP_MACRO_DYNAMIC_RE)
    for m in _LIB_MEMBER_AMP_MACRO_DYNAMIC_RE.finditer(text_clean):
        lib_u = m.group(1).upper()
        if lib_u in _EXCLUDED_SAS_LIBREFS_FOR_OUTPUT_QUALIFY:
            continue
        pref = m.group(2).upper()
        mac = m.group(3).upper()
        dynamic_tables.add(f'{lib_u}.{pref}{{{mac}}}')

    if lets:
        outputs = {_resolve_output_token_with_lets(o, lets) for o in outputs}

    # Escrita só-membro (DATA X; / CREATE TABLE X ...) é WORK implícita: não qualificar
    # com LIBNAME por evidência de leitura — "DATA X; SET LIB.X" viraria falso output LIB.X
    # (e falsa auto-produção/aresta de linhagem). Escrita permanente exige LIB.membro ou
    # path explícito no próprio alvo da escrita.

    if lets:
        _apply_let_resolution_to_io_scan(
            inputs, dynamic_tables, work_table_reads, provenance, lets
        )

    prov_line = _format_table_read_provenance(provenance)

    return (
        list(macros_used),
        list(macros_defined),
        sorted(inputs),
        sorted(outputs),
        sorted(dynamic_tables),
        sorted(work_table_reads),
        prov_line,
        dict(pass_through_engine_by_table),
    )


def extract_procs_used(text):
    if not text: return []
    pattern = re.compile(r'\bPROC\s+([A-Z0-9_]+)', re.IGNORECASE)
    return sorted(list(set(m.group(1).upper() for m in pattern.finditer(text))))


def has_data_step(text):
    if not text: return False
    return bool(re.search(r'\bDATA\s+[a-zA-Z0-9_.&]+\s*;', text, re.IGNORECASE))


def count_data_steps(text):
    if not text: return 0
    return len(re.findall(r'\bDATA\s+[a-zA-Z0-9_.&]+\s*;', text, re.IGNORECASE))


def extract_connection_librefs(text):
    """LIBNAME com motor de BD + CONNECT TO + * … LIBNAME … (comentário) com motor."""
    if not text:
        return []
    part = '|'.join(re.escape(e) for e in CONNECTION_ENGINES)
    pattern = re.compile(r'\bLIBNAME\s+([A-Z0-9_]+)\s+(?:' + part + r')\b', re.IGNORECASE)
    found = {m.group(1).upper() for m in pattern.finditer(text)}
    cstar = re.compile(
        r'(?im)^\s*\*\s*[^;\n]*\bLIBNAME\s+([A-Za-z0-9_]+)\s+(?:' + part + r')\b',
        re.IGNORECASE,
    )
    for m in cstar.finditer(text):
        found.add(m.group(1).upper())
    for k in build_db_mapping(text).keys():
        found.add(k)
    return sorted(found)


def build_db_mapping(text):
    mapping = {}
    engines_str = '|'.join(CONNECTION_ENGINES)
    pattern_lib = re.compile(r'\bLIBNAME\s+([A-Z0-9_]+)\s+(' + engines_str + r')\b', re.IGNORECASE)
    for m in pattern_lib.finditer(text):
        mapping[m.group(1).upper()] = m.group(2).upper()

    pattern_conn = re.compile(r'\bCONNECT\s+TO\s+([A-Z0-9_]+)(?:\s+AS\s+([A-Z0-9_]+))?', re.IGNORECASE)
    for m in pattern_conn.finditer(text):
        engine = m.group(1).upper()
        alias = m.group(2).upper() if m.group(2) else engine
        mapping[alias] = engine

    return mapping


def collect_explicit_libref_names(full_text):
    """
    Librefs com LIBNAME explícito no código ou em linha * … ; alias CONNECT TO (build_db_mapping).
    Usado para não listar IMPORTED_LIBNAMES por mero prefixo de tabela qualificada sem LIBNAME.
    """
    if not full_text:
        return set()
    names = set()
    for m in re.finditer(r'\bLIBNAME\s+([A-Za-z0-9_]+)\s+', full_text, re.IGNORECASE):
        names.add(m.group(1).upper())
    for k in build_db_mapping(full_text).keys():
        names.add(k)
    for m in re.finditer(r'(?im)^\s*\*\s*[^;\n]*\bLIBNAME\s+([A-Za-z0-9_]+)\s+', full_text):
        names.add(m.group(1).upper())
    return names


def _resolve_io_token_keys(token, lets, proc_safra_safra_literals=None):
    """
    Chaves canónicas para cruzar input/output (mesmo nome lógico com macros distintos).
    proc_safra_safra_literals: valores do 2.º arg de %PROC_SAFRA(...) — imita SAFRA no corpo da macro.
    """
    keys = set()

    def add_key(raw):
        if not raw:
            return
        k = clean_table_token(raw).upper()
        keys.add(k)
        if k.startswith('WORK.'):
            keys.add(k[5:])

    def collect_with_lets(tok, L):
        if not tok:
            return
        add_key(tok)
        if not L or '&' not in (tok or ''):
            return
        base_one = clean_table_token(tok)
        zx = _try_expand_macro_refs_in_identifier(base_one, L)
        if zx:
            add_key(zx)
        r = _resolve_qualified_read_token_with_lets(tok, L)
        if r:
            add_key(r)
        ro = _resolve_output_token_with_lets(tok, L)
        if ro and isinstance(ro, str):
            add_key(ro)

    collect_with_lets(token, lets)
    if proc_safra_safra_literals:
        for lit in proc_safra_safra_literals:
            alt = dict(lets or {})
            alt['SAFRA'] = lit
            collect_with_lets(token, alt)
    return {k for k in keys if k}


def _output_key_set(outputs, lets, proc_safra_safra_literals=None):
    acc = set()
    for o in outputs or []:
        acc |= _resolve_io_token_keys(o, lets, proc_safra_safra_literals)
    return acc


def _input_is_same_script_reuse(inp, output_keys, lets, proc_safra_safra_literals=None):
    if not output_keys or not inp:
        return False
    for k in _resolve_io_token_keys(inp, lets, proc_safra_safra_literals):
        if k in output_keys:
            return True
    return False


def extract_included_scripts(text):
    if not text: return []
    pattern = re.compile(r'\%(?:include|inc)\s*\(?\s*["\']([^"\']+)["\']\s*\)?\s*;?', re.IGNORECASE)
    matches = pattern.findall(text)
    return sorted(list(set(m.strip() for m in matches if len(m.strip()) > 3)))


def has_passthrough_sql(text):
    if not text: return False
    if re.search(r'\bCONNECT\s+TO\b', text, re.IGNORECASE): return True
    if re.search(r'\bEXECUTE\s*\(', text, re.IGNORECASE): return True
    return False


def build_file_references_summary(file_inventory_map):
    from collections import Counter
    if not file_inventory_map: return "0 paths"
    ext_counter = Counter()
    for path in file_inventory_map:
        _, ext = os.path.splitext(path)
        clean_ext = ext.lower().replace('.', '') or 'no_ext'
        ext_counter[clean_ext] += 1
    total = len(file_inventory_map)
    parts = [f"{k}: {v}" for k, v in sorted(ext_counter.items())]
    return f"{total} paths ({', '.join(parts)})"


def get_content_hash(content):
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def try_decode(bytes_content):
    """
    Decode text from SAS exports, EGP zips, and Windows-saved scripts.

    Order matters: a file can be mostly UTF-8 with one invalid byte (e.g. CP1252
    ``Ç`` as lone 0xC7). UTF-8 then fails, but blind ``utf-16`` can still
    "succeed" on arbitrary bytes and mangle the whole buffer (wrong codepoints).
    We try UTF-8, then Windows-1252 / Latin-1, and only treat as UTF-16 when
    BOM is present or the byte pattern looks like UTF-16 (high NUL ratio).
    """
    if not bytes_content:
        return ""

    if bytes_content.startswith(b"\xef\xbb\xbf"):
        return bytes_content[3:].decode("utf-8", errors="replace")
    if bytes_content.startswith(b"\xff\xfe"):
        return bytes_content[2:].decode("utf-16-le", errors="replace")
    if bytes_content.startswith(b"\xfe\xff"):
        return bytes_content[2:].decode("utf-16-be", errors="replace")

    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return bytes_content.decode(enc)
        except UnicodeDecodeError:
            continue

    n = min(len(bytes_content), 4096)
    if n >= 2 and len(bytes_content) % 2 == 0:
        chunk = bytes_content[:n]
        null_ratio = chunk.count(0) / float(n)
        if null_ratio > 0.12:
            for enc in ("utf-16-le", "utf-16-be"):
                try:
                    return bytes_content.decode(enc)
                except UnicodeDecodeError:
                    continue
            try:
                return bytes_content.decode("utf-16")
            except UnicodeDecodeError:
                pass

    return bytes_content.decode("utf-8", errors="replace")


def get_text_safe(element, tag_name):
    if element is None: return None
    child = element.find(tag_name)
    if child is not None and child.text: return child.text
    return None


def get_element_full_text(elem):
    if elem is None:
        return ""
    raw = "".join(elem.itertext()) if hasattr(elem, "itertext") else (elem.text or "")
    raw = raw.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    return raw


def clean_sas_code(text):
    if not text: return ""
    text = text.replace('\ufeff', '').replace('\x00', '').replace('ï»¿', '')
    lines = text.replace('\r\n', '\n').split('\n')
    cleaned_lines = []
    last_line_was_empty = False
    for line in lines:
        stripped_line = line.rstrip()
        if not stripped_line:
            if not last_line_was_empty:
                cleaned_lines.append("")
                last_line_was_empty = True
        else:
            cleaned_lines.append(stripped_line)
            last_line_was_empty = False
    return "\n".join(cleaned_lines).strip()


def extract_libname_definitions(full_text):
    if not full_text: return []
    pattern = re.compile(r'LIBNAME\s+([A-Z0-9_]+)\s+(?:[A-Z0-9_]+\s+)?(?:["\'])([^"\']+)(?:["\'])', re.IGNORECASE)
    pattern_alt = re.compile(r'LIBNAME\s+([A-Z0-9_]+)\s+["\']?(/[a-zA-Z0-9._/-]+|\\+[a-zA-Z0-9._\-\\]+)["\']?',
                             re.IGNORECASE)

    matches = pattern.findall(full_text) + pattern_alt.findall(full_text)
    results = []
    for lib, path in matches:
        if len(path.strip()) > 2:
            results.append(f"{lib.upper()} = {path.strip()}")
    return sorted(list(set(results)))


def _libname_path_dict_from_sas_base(base):
    """LIBREF -> caminho físico (pastas LIBNAME), alinhado a DETECTED_LIBNAMES no cabeçalho."""
    d = {}
    for pair in extract_libname_definitions(base):
        if '=' in pair:
            k, v = pair.split('=', 1)
            d[k.strip().upper()] = v.strip()
    return d


def _sas_qualified_reads_full_project_tokens(inputs_full, libname_dict):
    """
    lib.membro estáticos do scan sobre todo o código do .txt (inclui nós não ligados ao fluxo EG).
    Complementa EXTERNAL INPUTS / INTERNAL READS (que usam só clean_flow_linked no EGP).
    """
    if not inputs_full or not libname_dict:
        return []
    roots = {k.upper() for k in libname_dict.keys()}
    out = set()
    for t in inputs_full:
        s = (t or '').strip()
        if not s or '&' in s or '%' in s or '{' in s:
            continue
        if '/' in s or '\\' in s or re.match(r'^[A-Za-z]:[/\\]', s):
            continue
        if '.' not in s or s.upper().startswith('WORK.'):
            continue
        lib = s.split('.', 1)[0].strip().upper()
        if lib not in roots:
            continue
        tok = clean_table_token(s)
        if not tok or '.' not in tok or not is_valid_table(tok):
            continue
        out.add(tok)
    return sorted(out)


def extract_sas_comment_text_aggregate(raw_text):
    """
    Texto contido em comentários SAS: blocos /* … */ e declarações * … ; / %* … ;
    (mesma correção de typo *? → */ que remove_sas_comments). Usado para inventário
    de referências que não entram no scan executável.
    """
    if not raw_text:
        return ""
    t = raw_text
    if '*?' in t and '/*' in t:
        t = re.sub(r'(/\*[^\n]*?)\*\?\s*', r'\1 */ ', t)
    bodies = []
    masked = list(t)
    i, n = 0, len(t)
    while i < n:
        if t[i] == '/' and i + 1 < n and t[i + 1] == '*':
            j = t.find('*/', i + 2)
            if j == -1:
                bodies.append(t[i + 2 :])
                for k in range(i, n):
                    masked[k] = ' '
                break
            bodies.append(t[i + 2 : j])
            for k in range(i, j + 2):
                masked[k] = ' '
            i = j + 2
            continue
        i += 1
    masked_s = ''.join(masked)
    for m in re.finditer(r'(?:^|;)\s*(?:\*|%\*)([^;]+);', masked_s, re.MULTILINE):
        bodies.append(m.group(1))
    return '\n'.join(bodies)


def _qualified_read_upper_set_from_inputs(inputs_list, libname_dict):
    if not libname_dict:
        return set()
    toks = _sas_qualified_reads_full_project_tokens(inputs_list, libname_dict)
    return {x.upper() for x in toks}


def _perm_output_display_by_upper(outputs_list):
    """lib.membro permanente (não WORK) -> mapa UPPER -> token canónico."""
    m = {}
    for o in outputs_list or []:
        if not o or '.' not in o:
            continue
        if o.upper().startswith('WORK.'):
            continue
        tok = clean_table_token(o)
        if not tok or '.' not in tok:
            continue
        m.setdefault(tok.upper(), tok)
    return m


def compute_comment_only_qualified_io(raw_text, libname_dict, outputs_clean_list=None):
    """
    Leituras/escritas qualificadas presentes só em comentários (não no código executável após strip).
    outputs_clean_list: saídas já obtidas de scan_sas_dependencies(clean); se None, recalcula.
    """
    if not raw_text or not libname_dict:
        return [], []
    clean = remove_sas_comments(raw_text)
    comment_blob = extract_sas_comment_text_aggregate(raw_text).strip()
    if not comment_blob:
        return [], []

    clean_s = re.sub(r'\s+', ' ', clean.strip())
    com_s = re.sub(r'\s+', ' ', comment_blob)

    _, _, inputs_act, outputs_act, _, _, _, _ = scan_sas_dependencies(clean_s)
    _, _, inputs_com, outputs_com, _, _, _, _ = scan_sas_dependencies(com_s)

    if outputs_clean_list is not None:
        outputs_act = outputs_clean_list

    q_act = _qualified_read_upper_set_from_inputs(inputs_act, libname_dict)
    q_com = _qualified_read_upper_set_from_inputs(inputs_com, libname_dict)
    reads_upper = q_com - q_act
    qualified_com = _sas_qualified_reads_full_project_tokens(inputs_com, libname_dict)
    read_toks = sorted(
        [t for t in qualified_com if t.upper() in reads_upper],
        key=str.upper,
    )

    w_act = set(_perm_output_display_by_upper(outputs_act).keys())
    w_com_map = _perm_output_display_by_upper(outputs_com)
    writes_only = sorted(
        (w_com_map[u] for u in w_com_map if u not in w_act),
        key=str.upper,
    )
    return read_toks, writes_only


def extract_libname_physical_path_roots(full_text):
    """
    Caminhos físicos atribuídos a LIBNAME (pastas SAS, não ficheiros de ingestão).
    Usado para não duplicar em IMPORTED FILES / scan de ficheiros — já constam em DETECTED_LIBNAMES.
    """
    roots = set()
    if not full_text:
        return roots
    for m in re.finditer(
        r'\bLIBNAME\s+[A-Za-z0-9_]+\s+(?:[A-Za-z0-9_]+\s+)?["\']([^"\']+)["\']',
        full_text,
        re.IGNORECASE,
    ):
        p = decode_eg_path_string(m.group(1).strip())
        if len(p) < 2:
            continue
        key = p.replace("\\", "/").rstrip("/").lower()
        roots.add(key)
    return roots


def normalize_path_for_libname_compare(path_str):
    """Path sem sufixo [SHEET=], normalizado para comparar com raiz LIBNAME."""
    base = path_str.split("[SHEET=", 1)[0].strip()
    return base.replace("\\", "/").rstrip("/").lower()


def remove_sas_comments(text):
    if not text:
        return ""
    # Typo comum: /* ... *? em vez de */
    if '*?' in text and '/*' in text:
        text = re.sub(r'(/\*[^\n]*?)\*\?\s*', r'\1 */ ', text)
    text = _strip_c_style_block_comments_linear(text)
    text = re.sub(r'(^|;)\s*(?:\*|%\*)[^;]+;', r'\1', text)
    # Linha só com comentário estilo * ... ; (open code; pode colidir com SQL raro)
    text = re.sub(r'(?m)^\s*\*[^;\n\r]*;\s*\n', '\n', text)
    return text


def analyze_consultive_nature(sas_code, perm_outputs):
    """
    Classifica o propósito do código: CONSULTIVE, DATA_TRANSFORMATION ou HYBRID.
    Usa texto já limpo de comentários SAS quando o caller passa sas_code pós-remove_sas_comments;
    aplica remove_sas_comments de forma idempotente para evitar falsos positivos.
    perm_outputs: lista de saídas permanentes (lib.membro, fora de WORK), como no cabeçalho.
    """
    if not sas_code or not sas_code.strip():
        return 'CONSULTIVE', 0, []

    text = remove_sas_comments(sas_code)
    upper = text.upper()

    pos = 0
    neg = 0
    ods_exts = set()

    pp = CONSULTIVE_INDICATORS['positive_proc']
    for proc_phrase, w in pp.items():
        if proc_phrase == 'PROC PRINT':
            n = 0
            for m in re.finditer(r'\bPROC\s+PRINT\b', text, re.IGNORECASE):
                tail = text[m.end(): min(len(text), m.end() + 24)].lstrip()
                if tail.upper().startswith('TO'):
                    continue
                n += 1
        else:
            proc_name = proc_phrase.replace('PROC ', '')
            n = len(
                re.findall(rf'\bPROC\s+{re.escape(proc_name)}\b', text, re.IGNORECASE)
            )
        pos += n * w

    ods_map_ext = {
        'PDF': 'pdf', 'HTML': 'html', 'HTML5': 'html', 'PHTML': 'html',
        'LISTING': 'lst', 'EXCEL': 'xlsx', 'EXCELXP': 'xml', 'RTF': 'rtf',
        'WORD': 'docx', 'POWERPOINT': 'pptx', 'TAGSETS.EXCELXP': 'xml',
    }
    ods_w = CONSULTIVE_INDICATORS['ods_destination_weight']
    for m in re.finditer(
        r'\bODS\s+(PDF|HTML5|HTML|PHTML|LISTING|EXCEL|EXCELXP|RTF|WORD|POWERPOINT|TAGSETS\.EXCELXP)\b',
        text,
        re.IGNORECASE,
    ):
        dest = m.group(1).upper()
        if dest == 'TAGSETS.EXCELXP':
            dest_key = 'TAGSETS.EXCELXP'
        else:
            dest_key = dest
        w = ods_w.get(dest_key, 4)
        pos += w
        ext = ods_map_ext.get(dest_key) or ods_map_ext.get(dest, dest.lower())
        if ext:
            ods_exts.add(ext)

    for m in re.finditer(
        r'\bODS\s+\w+\s[^;]*?FILE\s*=\s*["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    ):
        path = decode_eg_path_string(m.group(1).strip())
        ext = os.path.splitext(path)[1].lower().lstrip('.')
        if ext:
            ods_exts.add(ext)

    exp_w = CONSULTIVE_INDICATORS['proc_export_document']
    for block in _iter_proc_blocks_to_run_or_quit(text, 'EXPORT'):
        for path_m in re.finditer(
            r'(?:OUTFILE|FILE|DATAFILE)\s*=\s*["\']([^"\']+)["\']',
            block,
            re.IGNORECASE,
        ):
            path = decode_eg_path_string(path_m.group(1).strip())
            ext = os.path.splitext(path)[1].lower().lstrip('.')
            if ext in _CONSULTIVE_DOC_EXPORT_EXTS:
                pos += exp_w
                ods_exts.add(ext)

    nw = CONSULTIVE_INDICATORS['negative']

    for m in re.finditer(
        r'\bCREATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)',
        text,
        re.IGNORECASE,
    ):
        if m.group(1).upper() != 'WORK':
            neg += nw['create_table_perm']

    neg += len(re.findall(r'\bINSERT\s+INTO\b', upper)) * nw['insert_into']

    for m in re.finditer(
        r'\bUPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)',
        text,
        re.IGNORECASE,
    ):
        if m.group(1).upper() != 'WORK':
            neg += nw['update_sql']

    neg += len(re.findall(r'\bDELETE\s+FROM\b', upper)) * nw['delete_from']
    neg += len(re.findall(r'\bPROC\s+APPEND\b', upper)) * nw['proc_append']

    for m in re.finditer(r'\bDATA\s+([^;{]+?);', text, re.IGNORECASE):
        clause = m.group(1).strip()
        if not clause or re.match(r'^\s*/', clause):
            continue
        slash = clause.find('/')
        if slash != -1:
            clause = clause[:slash].strip()
        for raw in clause.split():
            raw = raw.strip().strip(',').rstrip(';')
            if not raw or raw.upper().startswith('('):
                continue
            lead = _leading_dataset_name(raw)
            if not lead or lead.upper() == '_NULL_':
                continue
            if '.' not in lead:
                continue
            lib = lead.split('.', 1)[0].upper().replace('`', '').strip()
            if lib and lib != 'WORK':
                neg += nw['data_perm_output']

    perm_bonus = 0
    if not perm_outputs:
        perm_bonus = CONSULTIVE_PERM_OUTPUTS_EMPTY_BONUS

    consultive_signal = pos + perm_bonus
    transform_signal = neg
    consultive_score = consultive_signal - transform_signal

    if transform_signal >= 18 and consultive_signal < transform_signal - 2:
        classification = 'DATA_TRANSFORMATION'
    elif consultive_signal >= 15 and transform_signal <= 10:
        classification = 'CONSULTIVE'
    elif consultive_signal > 8 and transform_signal > 8:
        classification = 'HYBRID'
    elif consultive_score >= 5:
        classification = 'CONSULTIVE'
    elif transform_signal > consultive_signal + 3:
        classification = 'DATA_TRANSFORMATION'
    else:
        classification = 'HYBRID'

    return classification, consultive_score, sorted(ods_exts)


def decode_eg_path_string(s):
    """Caminhos vindos de XML / export SAS podem conter &amp; etc."""
    if not s:
        return s
    return (
        s.replace("&amp;amp;", "&")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .strip()
    )


def _is_plausible_filesystem_path(p):
    """
    Distingue caminho/URL de ficheiro de filerefs curtos (ex.: FILENAME x TEMP).
    """
    if not p:
        return False
    p = p.strip().strip('"').strip("'")
    if len(p) < 3:
        return False
    pl = p.lower()
    if pl in {'temp', 'dummy', 'null', 'stdout', 'stdin', 'stderr'}:
        return False
    if p.startswith(('mailto:', 'smtp:')):
        return False
    if re.match(r'^[^/\s\\:]+$', p) and '.' not in p:
        return False
    if p.startswith(('http://', 'https://', 'ftp://')):
        return True
    if re.match(r'^[a-zA-Z]:[/\\]', p):
        return True
    if p.startswith(('\\\\', '//')):
        return True
    if p.startswith(('/', '\\')):
        return True
    if '$' in p and ('/' in p or '\\' in p):
        return True
    if re.search(rf'\.(?:{_FILE_EXT_ALT})\b', p, re.IGNORECASE):
        return True
    return False


def _gather_explicit_file_paths_from_sas_code(text_content):
    """
    Caminhos de ficheiro explícitos em instruções SAS (inputs).
    Não inclui DATAFILE=/FILE= fora de PROC IMPORT (evita PROC EXPORT / artefactos).
    """
    found = set()
    if not text_content:
        return found
    text = decode_eg_path_string(text_content)

    for m in re.finditer(
        r'%\s*(?:INCLUDE|INC)\s*\(?\s*["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    ):
        p = m.group(1).strip()
        if len(p) > 1:
            found.add(p)

    for m in re.finditer(
        r'%\s*(?:INCLUDE|INC)\s+(?!["\'])([^\s;]+)',
        text,
        re.IGNORECASE,
    ):
        p = m.group(1).strip().rstrip(';')
        if len(p) > 3 and (
            re.search(r'\.(?:sas|sas7bdat)\b', p, re.IGNORECASE)
            or _is_plausible_filesystem_path(p)
        ):
            found.add(p)

    for m in re.finditer(
        r'\bFILENAME\s+[A-Za-z0-9_.]+\s+["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    ):
        p = m.group(1).strip()
        if _is_plausible_filesystem_path(p):
            found.add(p)

    for m in re.finditer(
        r'\bFILENAME\s+[A-Za-z0-9_.]+\s*\(([^)]*)\)',
        text,
        re.IGNORECASE,
    ):
        inner = m.group(1)
        for qm in re.finditer(r'["\']([^"\']+)["\']', inner):
            p = qm.group(1).strip()
            if _is_plausible_filesystem_path(p):
                found.add(p)

    for m in re.finditer(
        r'\bLIBNAME\s+[A-Za-z0-9_]+\s+(?:EXCEL|ACCESS|XLSX|XLS)\b[^;]*?["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    ):
        p = m.group(1).strip()
        if _is_plausible_filesystem_path(p):
            found.add(p)

    for m in re.finditer(
        r'\bINFILE(?!\s+(?:DATALINES|DATALINES4|CARDS)\b)\s+["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    ):
        p = m.group(1).strip()
        if len(p) > 1:
            found.add(p)

    for m in re.finditer(r'\bINFILE\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE):
        p = m.group(1).strip()
        if len(p) > 1:
            found.add(p)

    for blk in _iter_proc_blocks_to_run_or_quit(text, 'IMPORT'):
        for sm in re.finditer(
            r'\b(?:DATAFILE|FILE)\s*=\s*["\']([^"\']+)["\']',
            blk,
            re.IGNORECASE,
        ):
            p = sm.group(1).strip()
            if len(p) > 1:
                found.add(p)

    return found


def _blank_proc_export_blocks(text):
    """Remove blocos PROC EXPORT … RUN/QUIT do texto (sem alocar milhões de espaços)."""
    if not text:
        return text
    proc_rx = re.compile(r'\bPROC\s+EXPORT\b', re.IGNORECASE)
    term = re.compile(r'(?:\bRUN\s*;|\bQUIT\s*;)', re.IGNORECASE)
    parts = []
    pos = 0
    ms = _PROC_BLOCK_MAX_SPAN
    for m in proc_rx.finditer(text):
        parts.append(text[pos:m.start()])
        window = text[m.start():m.start() + ms]
        tm = term.search(window)
        if tm:
            pos = m.start() + tm.end()
        else:
            nxt = proc_rx.search(text, m.end())
            end_blk = nxt.start() if nxt else len(text)
            pos = end_blk
    parts.append(text[pos:])
    return ''.join(parts)


def find_paths_in_text(text_content):
    if not text_content: return []

    text_content = decode_eg_path_string(text_content)
    text_content = _blank_proc_export_blocks(text_content)
    # Windows com / ou \\; Unix/Linux: /… não logo após "letter:" (evita /sub de C:/sub/…)
    regex = (
        rf'('
        rf'(?:[a-zA-Z]:[/\\][^\n\r<*?"]+?\.(?:{_FILE_EXT_ALT})\b)'
        rf'|(?:[a-zA-Z]:\\[^\n\r<*?"]+?\.(?:{_FILE_EXT_ALT})\b)'
        rf'|(?:\\\\[^\n\r<*?"]+?\.(?:{_FILE_EXT_ALT})\b)'
        rf'|(?:(?<![a-zA-Z]:)/[^\n\r<*?"]+?\.(?:{_FILE_EXT_ALT})\b)'
        rf')'
    )
    matches = re.findall(regex, text_content, re.IGNORECASE)

    valid = set()
    for m in matches:
        clean = m.strip()
        if len(clean) < 8 or clean.startswith('/*'): continue

        if "SAS Temporary Files" in clean or ("Flow" in clean and ".xml" in clean) or ".egp" in clean: continue
        if "<" in clean or ">" in clean: continue

        if "saswork" in clean.lower() or "sas_work" in clean.lower(): continue
        if "temp" in clean.lower() and "/sas/" in clean.lower(): continue

        valid.add(clean)

    return list(valid)


def collect_external_file_paths_from_sas_code(text_content):
    """
    Referências a ficheiros externos em código SAS (não inclui LIBNAME BASE → pasta; ver DETECTED_LIBNAMES).
    Entrada: texto já sem comentários SAS (usar remove_sas_comments antes).

    Captura:
      - %INCLUDE / %INC (aspas ou caminho/.sas sem aspas)
      - FILENAME ref 'path' e FILENAME ref ('p1' 'p2' …)
      - LIBNAME … EXCEL|ACCESS|XLS(X) 'ficheiro'
      - INFILE 'path', INFILE=
      - PROC IMPORT … DATAFILE=|FILE= (só dentro do bloco … RUN/QUIT)
      - Heurística find_paths_in_text (ext. .sas, .json, .parquet, …)
    """
    if not text_content:
        return []
    found = set(_gather_explicit_file_paths_from_sas_code(text_content))

    for p in find_paths_in_text(text_content):
        found.add(p)

    out = []
    for p in found:
        p = p.strip()
        if len(p) < 2 or p.startswith("/*"):
            continue
        if "<" in p or ">" in p:
            continue
        if "SAS Temporary Files" in p or ".egp" in p.lower():
            continue
        if "Flow" in p and ".xml" in p:
            continue
        out.append(p)
    return sorted(set(out))


def is_sas_ephemeral_import_path(path):
    """
    WORK/saswork e nomes #LN* são artefactos de sessão SAS, não ficheiros de projeto no EGP.
    Exclui da linha IMPORTED FILES (paridade com o que o EG mostra como importações reais).
    """
    if not path or len(path.strip()) < 4:
        return True
    stem = path.split("[SHEET=")[0].strip()
    u = stem.upper()
    low = stem.lower().replace("\\", "/")
    if "SASWORK" in u or "SAS_WORK" in u or "/saswork/" in low:
        return True
    if re.search(r"#LN\d+", u):
        return True
    if "SAS TEMPORARY FILES" in u:
        return True
    return False


def embedded_xml_has_persistent_file_path(raw_code):
    """
    Blocos 'Import Data Wizard' no XML podem incluir PROC IMPORT com caminho real (ex.: N:\\...\\LTV.xlsx).
    Só devem ser descartados quando não há referência a ficheiro persistente (só ruído saswork/#LN).
    """
    dec = decode_eg_path_string(raw_code)
    for m in re.finditer(
        rf'(?:[a-zA-Z]:\\|/)[^\n\r;]+?\.(?:{_FILE_EXT_ALT})\b', dec, re.IGNORECASE):
        cand = m.group(0).strip().rstrip(';').strip('"').strip("'")
        if len(cand) > 8 and not is_sas_ephemeral_import_path(cand):
            return True
    return False


def extract_import_task_dest_member(xml_txt):
    m = re.search(r"<DestMember>([^<]+)</DestMember>", xml_txt, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_import_task_output_member_fallback(xml_txt):
    """project.xml pode omitir DestMember mas traz ExpectedOutputDataList/Member."""
    m = re.search(
        r"<ExpectedOutputDataList>[\s\S]*?<Member>([^<]+)</Member>", xml_txt, re.IGNORECASE
    )
    return m.group(1).strip() if m else ""


def extract_import_task_parent_shortcut(xml_txt):
    """Parent do atalho de ficheiro ou, em alguns EG, apenas InputIDs."""
    pm = re.search(r"<Parent>\s*([^<]+)</Parent>", xml_txt, re.IGNORECASE)
    if pm:
        return pm.group(1).strip()
    im = re.search(
        r"<InputIDs>\s*(ShortCutToFile-[A-Za-z0-9]+)\s*</InputIDs>", xml_txt, re.IGNORECASE
    )
    return im.group(1).strip() if im else ""


def extract_import_task_source_type(xml_txt):
    m = re.search(r"<SourceType>([^<]+)</SourceType>", xml_txt, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def build_eg_external_file_shortcut_map(project_xml_text):
    """
    EG 7.x: atalhos de ficheiro externos usam `<ShortCutID>ShortCutToFile-…</ShortCutID>` e `<DNA>`
    embutido com `<FullPath>…</FullPath>`. O selector XML `.//ExternalFile/ExternalFile` falha com frequência
    (namespaces / árvores variáveis); varremos o project.xml já decodificado com regex estável sobre o texto.
    """
    sid_to_path = {}
    txt = (project_xml_text or "").strip()
    if not txt:
        return sid_to_path
    doc = html.unescape(decode_eg_path_string(txt))
    for m in re.finditer(
        r"<ShortCutID>(ShortCutToFile-[A-Za-z0-9]+)</ShortCutID>.*?<DNA>(.*?)</DNA>",
        doc,
        re.DOTALL | re.IGNORECASE,
    ):
        sid = m.group(1).strip()
        inner = html.unescape(m.group(2))
        m_fp = re.search(r"<FullPath>([^<]+)</FullPath>", inner, re.IGNORECASE)
        if not m_fp:
            continue
        fp_raw = decode_eg_path_string(m_fp.group(1).strip())
        if len(fp_raw) > 5:
            sid_to_path[sid] = fp_raw
    return sid_to_path


def extract_import_task_selected_table_sheet(xml_txt):
    """
    Folha / intervalo Excel em Import Tasks EG (ex.: True\\x7fPrazo_Medio\\x7f em SelectedTableOrRange).
    """
    m = re.search(r"<SelectedTableOrRange>[^\x7f]*\x7f([^\x7f]+)\x7f", xml_txt)
    if not m:
        return ""
    name = m.group(1).strip()
    if not name or len(name) > 64:
        return ""
    if not re.match(r"^[A-Za-z0-9_.\- ]+$", name):
        return ""
    return name


def extract_import_task_sheet_from_eg_label(xml_txt):
    """
    EG grava no Element/Label textos do tipo:
    Import Data (DE_PARA_DRE_VAREJO_BD.xlsx[CONTA])
    A serialização ET do ImportTask muitas vezes não inclui WorksheetName; sem [SHEET=] todas as
    ingestões do mesmo ficheiro colapsam numa única linha após dedupe_imported_files_metadata.
    """
    m = re.search(
        r"<Label>[^<]*?Import Data\s*\([^<]*?\.(?:xlsx|xlsm|xls)\s*\[([^\]]{1,64})\][^<]*</Label>",
        xml_txt,
        re.IGNORECASE,
    )
    if not m:
        return ""
    name = m.group(1).strip()
    if not name or len(name) > 64:
        return ""
    if not re.match(r"^[A-Za-z0-9_.\- ]+$", name):
        return ""
    return name


def sas_metadata_path_display(path_str):
    """Alinha metadados a exports SAS/EG (P&amp;C no caminho; folhas macro ex. &ref. sem escapar)."""
    if not path_str:
        return path_str
    if "[SHEET=" in path_str:
        base, sep, tail = path_str.partition("[SHEET=")
        return base.replace("&", "&amp;") + sep + tail
    return path_str.replace("&", "&amp;")


def dedupe_file_inventory_map_items(path_origin_pairs):
    """
    Chave única = caminho base + folha ([SHEET=...]); todas as abas do mesmo .xlsx são listadas.
    """
    best = {}
    for p, o in path_origin_pairs:
        base, sep, sheet = p.partition("[SHEET=")
        key = (base.strip().lower(), sheet.strip().lower() if sep else "")
        if key not in best or len(p) > len(best[key][0]):
            best[key] = (p, o)
    return sorted(best.values(), key=lambda x: x[0].lower())


def dedupe_imported_files_metadata(paths):
    """Uma entrada por caminho completo (incl. [SHEET=] distinto por aba)."""
    best = {}
    for p in paths:
        key = p.strip().lower()
        if key not in best or len(p) > len(best[key]):
            best[key] = p
    return sorted(best.values())


def parse_import_task_log_datafile(log_text):
    """
    result.log de Import Task: 'Source file:' pode partir-se em várias linhas 's N ...'
    até ao .xlsx; 'Output data: WORK.membro' associa o ficheiro ao WORK.
    """
    if not log_text:
        return None, None
    log_text = log_text.replace("\r\n", "\n").replace("\r", "\n")
    m_out = re.search(r"Output data:\s*WORK\.(\w+)", log_text, re.IGNORECASE)
    if not m_out:
        return None, None
    member = m_out.group(1).strip()
    m_sf = re.search(r"Source file:\s*([^\n]+)", log_text, re.IGNORECASE)
    if not m_sf:
        return member, None
    base = m_sf.group(1).strip()
    rest = log_text[m_sf.end():]
    parts = [base]
    while True:
        m = re.match(r"\n\s*s\s+\d+\s+([^\n]+)", rest)
        if not m:
            break
        line = m.group(1).strip()
        rest = rest[m.end() :]
        if re.match(r"Server:", line, re.IGNORECASE):
            break
        parts.append(line)
        if re.search(r"\.(?:xlsx?|csv|txt)\b", line, re.IGNORECASE):
            break
    if len(parts) == 1:
        full = parts[0]
    else:
        sub = parts[1]
        for frag in parts[2:]:
            frag = frag.strip()
            if not frag:
                continue
            if sub.rstrip().endswith(("\\", "/")) or frag.startswith(("\\", "/")):
                sub += frag
            else:
                sub += " " + frag
        root = parts[0].rstrip()
        if root.endswith(("\\", "/")):
            full = root + sub
        else:
            full = root + "\\" + sub
    full = decode_eg_path_string(full.replace("&amp;", "&"))
    if not re.search(r"\.(?:xlsx?|csv|txt)\b", full, re.IGNORECASE):
        return member, None
    return member, full


def normalize_id(raw_id):
    if not raw_id: return ""
    return raw_id.replace('{', '').replace('}', '').lower()


def map_process_flows(root):
    pf_map = {}
    if root is None: return pf_map
    for container in root.findall(".//Container"):
        lbl_tag = container.find("Label")
        container_label = lbl_tag.text if lbl_tag is not None else "Unknown Flow"
        for element_ref in container.findall(".//Element"):
            ref_id = element_ref.get("ID")
            if ref_id:
                norm_id = normalize_id(ref_id)
                pf_map[norm_id] = container_label
                pf_map[ref_id] = container_label
    return pf_map


def find_real_table_name(root, element_id, node_map, _vistos=None):
    """Nome real da tabela por trás de um elemento, seguindo atalhos (ShortCutToData).

    `_vistos` é guarda de CICLO, não detalhe interno: a recursão desce por
    `Parent`/`INPUTID`, e um atalho que aponta (direta ou indiretamente) para si mesmo
    estourava RecursionError — que não falha só esta chamada, derruba a extração do
    `.egp` inteiro. Ciclo devolve "WORK.UNKNOWN_TABLE", a mesma resposta de "não sei"
    que a função já dá para elemento ausente ou sem Label.

    Conjunto de visitados em vez de teto de profundidade: detecta o ciclo exatamente,
    sem inventar um limite para cadeia de atalhos legítima (que é rasa, mas o teto
    silenciaria a errada e a funda do mesmo jeito)."""
    if not element_id: return "WORK.UNKNOWN_TABLE"
    if _vistos is None:
        _vistos = set()
    if element_id in _vistos:
        return "WORK.UNKNOWN_TABLE"
    _vistos.add(element_id)
    target_elem = None
    for elem in root.findall(".//Element"):
        eid = get_text_safe(elem, "ID") or elem.get("ID")
        if eid == element_id:
            target_elem = elem
            break
    if target_elem is None:
        return f"WORK.{node_map.get(element_id, 'UNKNOWN_TABLE')}"
    el_type = target_elem.find("Type")
    type_str = el_type.text if el_type is not None else ""
    if "ShortCutToData" in type_str:
        parent_id = get_text_safe(target_elem, ".//Parent")
        if parent_id: return find_real_table_name(root, parent_id, node_map, _vistos)
        input_id = get_text_safe(target_elem, ".//INPUTID")
        if input_id: return find_real_table_name(root, input_id, node_map, _vistos)
    label = get_text_safe(target_elem, "Label")
    if label:
        clean_label = label.replace('[', '').replace(']', '')
        if "WORK." in clean_label: return clean_label.strip()
        return f"WORK.{clean_label.strip()}"
    return "WORK.UNKNOWN_TABLE"


def generate_proc_export_structure(root, export_task_elem, node_map, minimal_comments=False):
    task_xml = export_task_elem.find("EXPORT_TASK")
    if task_xml is None: return None
    outfile = get_text_safe(task_xml, "EXPORT_OUTPUTFILEPATHNAME")
    if not outfile: return None
    filetype = get_text_safe(task_xml, "EXPORT_OUTPUTFILETYPE") or "xlsx"
    input_id = get_text_safe(task_xml, "EXPORT_ELEMENT")
    table_name = find_real_table_name(root, input_id, node_map)
    dbms = 'xlsx' if 'xlsx' in filetype.lower() else 'csv'
    core = [
        f"PROC EXPORT DATA={table_name}",
        f"    OUTFILE='{outfile}'",
        f"    DBMS={dbms} REPLACE;",
        "RUN;"
    ]
    if minimal_comments:
        return "\n".join(core)
    return "\n".join([
        "/* [MIGRATION ALERT] EXPORTAÇÃO DETECTADA (METADADOS) */",
        f"/* Fonte Rastreada: {table_name} */",
        *core
    ])


def generate_proc_import_structure(label, hard_path, minimal_comments=False):
    sheet = ""
    clean_path = hard_path

    if "[SHEET=" in hard_path:
        parts = hard_path.split("[SHEET=", 1)
        clean_path = parts[0]
        if len(parts) > 1:
            sheet = parts[1].replace("]", "").replace("'", "").strip()

    safe_name = label.strip()
    if "." not in safe_name:
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', safe_name)
        safe_name = re.sub(r'_+', '_', safe_name)
        safe_name = f"WORK.{safe_name}"

    dbms = "EXCEL" if "xls" in os.path.splitext(clean_path)[1].lower() else "DLM"
    sheet_cmd = f" SHEET='{sheet}';" if sheet else ""

    proc = f'PROC IMPORT OUT={safe_name} DATAFILE="{clean_path}" DBMS={dbms} REPLACE; GETNAMES=YES;{sheet_cmd} RUN;'
    if minimal_comments:
        return proc
    return (
        "/* [DATA NODE DETECTED - IMPLICIT] */\n"
        "/* Arquivo encontrado nos metadados (Import Data). */\n"
        + proc
    )


def _normalize_eg_datasource_token(raw):
    """Normaliza texto interno de ActiveDataSource / DataSourceState (delimitador EG 0x7F, espaços)."""
    if not raw:
        return None
    s = (
        raw.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .strip()
    )
    if not s:
        return None
    s = re.sub(r"[\x00-\x1f\x7f]+", ".", s)
    s = re.sub(r"\s+", ".", s)
    s = re.sub(r"\.{2,}", ".", s).strip(".")
    return s if s else None


def _eg_xml_token_is_plausible_dataset(s):
    """LIB.MEMBER estilo SAS (membro pode incluir &macro)."""
    if not s or "." not in s:
        return False
    parts = s.split(".", 1)
    if len(parts) != 2:
        return False
    lib, mem = parts[0].strip(), parts[1].strip()
    if not lib or not mem:
        return False
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$", lib):
        return False
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_&]{0,200}$", mem):
        return False
    return True


def extract_eg_data_references_from_project_xml(xml_text):
    """
    Extrai referências a datasets registadas no project.xml do Enterprise Guide
    (ActiveDataSource, DataSourceState, TableState). Complementa o scan SAS quando
    a UI EG associa tabelas que nem sempre aparecem da mesma forma no código exportado.
    """
    canonical_by_upper = {}
    if not (xml_text and xml_text.strip()):
        return []

    def _ingest_raw(raw):
        norm = _normalize_eg_datasource_token(raw)
        if norm and _eg_xml_token_is_plausible_dataset(norm):
            canonical_by_upper.setdefault(norm.upper(), norm)

    def _local_tag(el):
        t = el.tag
        return t.rsplit("}", 1)[-1] if t.startswith("{") else t

    try:
        xt = re.sub(r'\sxmlns="[^"]+"', "", xml_text.strip(), count=1)
        root = ET.fromstring(xt)
        for el in root.iter():
            if _local_tag(el) in ("ActiveDataSource", "DataSourceState", "TableState"):
                _ingest_raw(el.text or "")
    except ET.ParseError:
        pass

    if not canonical_by_upper:
        for tag in ("ActiveDataSource", "DataSourceState", "TableState"):
            for m in re.finditer(rf"<{tag}>([^<]*)</{tag}>", xml_text, re.IGNORECASE):
                _ingest_raw((m.group(1) or "").strip())

    return sorted(canonical_by_upper.values(), key=str.upper)


def _flow_linked_io_upper_tokens(
    inputs_flow, outputs_flow, internal_reads_display, work_tbl_reads_flow
):
    """Conjunto normalizado (upper) de tabelas já cobertas pelo scan SAS no fluxo."""
    s = set()
    for lst in (inputs_flow, outputs_flow, internal_reads_display, work_tbl_reads_flow):
        if not lst:
            continue
        for t in lst:
            u = (t or "").replace("`", "").replace('"', "").replace("'", "").strip().upper()
            if u:
                s.add(u)
    return s


def extract_let_from_project_xml(xml_text):
    if not xml_text: return []
    text = xml_text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    matches = re.findall(r'%LET\s+([A-Za-z0-9_]+)\s*=\s*([^;]*);', text, re.IGNORECASE | re.DOTALL)
    seen = {}
    for name, value in matches:
        if name.upper() not in LET_EXCLUDED_NAMES:
            seen[name] = value.strip()
    return [f"%LET {k}={v};" for k, v in seen.items()]


def eg_style_task_preamble(node_label, flow_name, project_abspath):
    """Preâmbulo próximo ao export SAS EG/Studio: comentário Label + %LET _CLIENT*."""
    def clean(s):
        return (s or "").replace(";", " ").replace("\n", " ").replace("\r", " ").strip()

    nl, fl = clean(node_label), clean(flow_name)
    pp = clean(project_abspath).replace("\\", "/")
    return (
        f"/* Label: {nl} */\n"
        f"%LET _CLIENTTASKLABEL = {nl};\n"
        f"%LET _CLIENTPROCESSFLOWNAME = {fl};\n"
        f"%LET _CLIENTPROJECTPATH = {pp};\n"
    )


def sas_export_style_preamble(node_label, flow_name, project_abspath, project_filename):
    """Preâmbulo alinhado ao export oficial (SAS EG): Label + %LET com valores entre aspas."""
    def sas_quote(s):
        t = (s or "").replace("'", "''")
        return "'" + t + "'"

    nl = (node_label or "").replace("\n", " ").replace("\r", " ").strip()
    fl = (flow_name or "").replace("\n", " ").replace("\r", " ").strip()
    pp = (project_abspath or "").replace("\\", "/")
    pfn = (project_filename or os.path.basename(project_abspath) or "").replace("\n", " ").strip()
    return (
        f"/* Label: {nl} */\n"
        f"%LET _CLIENTTASKLABEL={sas_quote(nl)};\n"
        f"%LET _CLIENTPROCESSFLOWNAME={sas_quote(fl)};\n"
        f"%LET _CLIENTPROJECTPATH={sas_quote(pp)};\n"
        "%LET _CLIENTPROJECTPATHHOST='';\n"
        f"%LET _CLIENTPROJECTNAME={sas_quote(pfn)};\n"
        "%LET _SASPROGRAMFILE='';\n"
        "%LET _SASPROGRAMFILEHOST='';\n\n"
    )


def _v1_comment_escape(text):
    """Evita fechar blocos /* … */ por acidente dentro de linhas de comentário SAS."""
    return (text or "").replace("*/", "* /").replace("\r\n", "\n").replace("\r", "\n")


def _v1_task_banner_start(flow_name, task_label, exec_ord, origin_file, source_type, *, from_project_xml=False):
    """Cabeçalho visual de task (preservado no .txt v1 — não passa por strip global de comentários)."""
    lines = [
        "/* =========================INÍCIO TASK========================= */",
        f"/* TASK: {_v1_comment_escape(task_label)} */",
        f"/* ORDEM EXECUÇÃO: {exec_ord:03d} */",
        f"/* FLUXO: {_v1_comment_escape(flow_name)} */",
        "/* ORDEM: Sequencial (Topological Sort) */",
        f"/* NOME DO NÓ: {_v1_comment_escape(task_label)} */",
        f"/* TIPO: {_v1_comment_escape(source_type)} */",
        f"/* ARQUIVO FONTE: {_v1_comment_escape(origin_file)} */",
    ]
    if from_project_xml:
        lines.append("/* ORIGEM: Código persistido em project.xml (embedded / wizard / task) */")
    lines.append("/* =========================INÍCIO TASK========================= */")
    return "\n".join(lines) + "\n"


def _v1_task_banner_end(task_label, exec_ord):
    return (
        "\n/* =========================FIM TASK=========================== */\n"
        f"/* TASK: {_v1_comment_escape(task_label)} */\n"
        f"/* ORDEM EXECUÇÃO: {exec_ord:03d} */\n"
        "/* =========================FIM TASK=========================== */\n\n"
    )


def extract_code_from_egp(egp_path, output_folder, business_area="", eg_style=False, clean_output=False):
    """
    Extrai EGP/ZIP em .txt para migração: corpo SAS com blocos INÍCIO/FIM TASK por nó na ordem dos fluxos do
    project.xml; interior de cada task sem comentários SAS; inclui Export (metadados) e código embedded
    aceite do project.xml (com ORIGEM XML no cabeçalho). Metadados START…END reduzidos.
    eg_style / clean_output não alteram o texto SAS emitido (mantidos por compatibilidade de assinatura).
    """
    if not os.path.exists(egp_path): return

    project_abspath = os.path.abspath(egp_path)
    base_name, ext = os.path.splitext(os.path.basename(egp_path))
    file_extension = ext.lower()
    project_filename = f"{base_name}{file_extension}"
    output_file = os.path.join(output_folder, f"{base_name}.txt")
    print(f"-> Processando EGP/ZIP: {base_name}{file_extension}...")

    active_blocks = []
    recovered_blocks = []
    export_blocks = []
    embedded_code_blocks = []

    full_code_accumulator = ""
    processed_hashes = set()
    file_inventory_map = {}
    project_xml_text = ""

    flow_orders = {}
    guid_to_flow_name = {}
    code_buffer = {}
    code_metadata = {}

    try:
        with zipfile.ZipFile(egp_path, 'r') as z:
            shortcut_to_path = {}
            file_list = sorted(z.namelist())
            node_map = {}
            root = None
            proj_xml_path = next((f for f in file_list if f.lower() == 'project.xml'), None)

            if proj_xml_path:
                with z.open(proj_xml_path) as f:
                    try:
                        raw_proj = f.read()
                        xml_text = try_decode(raw_proj)
                        project_xml_text = xml_text
                        xml_text = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
                        root = ET.fromstring(xml_text)

                        for elem in root.findall(".//Element"):
                            el_id = get_text_safe(elem, "ID") or elem.get("ID")
                            el_lbl = get_text_safe(elem, "Label")
                            if el_id and el_lbl:
                                node_map[normalize_id(el_id)] = el_lbl
                                node_map[el_id] = el_lbl

                        def _unique_flow_key(base_label, existing_keys):
                            k = (base_label or "Unknown Flow").strip() or "Unknown Flow"
                            if k not in existing_keys:
                                return k
                            n = 2
                            while f"{k} ({n})" in existing_keys:
                                n += 1
                            return f"{k} ({n})"

                        for container in root.findall(".//Container"):
                            lbl_tag = container.find("Label")
                            flow_label = lbl_tag.text if lbl_tag is not None else "Unknown Flow"
                            ordered_ids = get_flow_execution_order(container)
                            if not ordered_ids:
                                continue
                            fk = _unique_flow_key(flow_label, flow_orders)
                            flow_orders[fk] = ordered_ids
                            for guid in ordered_ids:
                                guid_to_flow_name[guid] = fk

                        for i, elem in enumerate(root.findall(".//Element")):
                            if elem.find(".//PFD") is None:
                                continue
                            ordered_ids = get_pfd_execution_order(elem)
                            if not ordered_ids:
                                continue
                            flow_label = get_text_safe(elem, "Label") or f"PFD Flow {i}"
                            fk = _unique_flow_key(flow_label, flow_orders)
                            flow_orders[fk] = ordered_ids
                            for guid in ordered_ids:
                                guid_to_flow_name[guid] = fk

                        if root is not None:
                            for file_node in root.findall(".//Element[@Type='SAS.EG.ProjectElements.ExternalFile']"):
                                lbl = get_text_safe(file_node, "Label")
                                path_node = file_node.find(".//Table/Path")
                                if path_node is not None and path_node.text:
                                    file_inventory_map[path_node.text] = "METADATA FILE"
                            try:
                                shortcut_to_path.update(build_eg_external_file_shortcut_map(project_xml_text))
                                for _fp in shortcut_to_path.values():
                                    if _fp and _fp not in file_inventory_map:
                                        file_inventory_map[_fp] = "METADATA FILE"
                            except Exception:
                                pass

                    except Exception as e:
                        print(f"  [AVISO] XML Parse / Lineage: {e}")

            folder_contents = {}
            for f in file_list:
                parts = f.replace('\\', '/').split('/')
                if len(parts) >= 2:
                    folder = "/".join(parts[:-1])
                    name = parts[-1].lower()
                    if folder not in folder_contents:
                        folder_contents[folder] = []
                    folder_contents[folder].append(name)

            for folder, files in folder_contents.items():
                origin_file = ""
                source_type = ""
                if 'code.sas' in files:
                    origin_file = f"{folder}/code.sas"
                    source_type = "SAS Program"
                elif 'query.sql' in files:
                    origin_file = f"{folder}/query.sql"
                    source_type = "SQL Query"

                if not origin_file: continue

                try:
                    raw_bytes = z.read(origin_file)
                    code_content = clean_sas_code(try_decode(raw_bytes))
                    if not code_content: continue
                except:
                    continue

                h = get_content_hash(code_content)
                if h not in processed_hashes:
                    processed_hashes.add(h)

                norm_id = normalize_id(folder)
                node_name = node_map.get(norm_id, node_map.get(folder, folder))
                code_buffer[norm_id] = code_content
                code_metadata[norm_id] = {
                    'node_name': node_name, 'source_type': source_type,
                    'origin_file': origin_file
                }

            task_tail_index = build_code_buffer_task_tail_index(code_buffer)
            processed_guids = set()
            seen_flow_buf_keys = set()
            migration_chunks = []
            raw_segments = []
            exec_ord = 1

            for flow_name in sorted(flow_orders.keys()):
                for guid in flow_orders[flow_name]:
                    buf_key = resolve_code_buffer_key(guid, code_buffer, task_tail_index)
                    if buf_key is None:
                        continue
                    if buf_key in seen_flow_buf_keys:
                        continue
                    seen_flow_buf_keys.add(buf_key)
                    meta = code_metadata[buf_key]
                    raw_src = code_buffer[buf_key]
                    stripped = remove_sas_comments(raw_src).strip()
                    task_label = meta['node_name']
                    migration_chunks.append(
                        _v1_task_banner_start(
                            flow_name, task_label, exec_ord,
                            meta['origin_file'], meta['source_type'], from_project_xml=False,
                        )
                        + stripped
                        + "\n"
                        + _v1_task_banner_end(task_label, exec_ord)
                    )
                    raw_segments.append(raw_src)
                    exec_ord += 1

                    if clean_output:
                        block = (
                            sas_export_style_preamble(
                                meta['node_name'], flow_name, project_abspath, project_filename)
                            + f"{raw_src}\n\n"
                        )
                    else:
                        eg_pre = (
                            eg_style_task_preamble(meta['node_name'], flow_name, project_abspath)
                            if eg_style else ""
                        )
                        block = (
                            eg_pre
                            + "/* ================================================== */\n"
                            f"/* FLUXO: {flow_name} */\n"
                            f"/* ORDEM: Sequencial (Topological Sort) */\n"
                            f"/* NOME DO NÓ: {meta['node_name']} */\n"
                            f"/* TIPO: {meta['source_type']} */\n"
                            f"/* ARQUIVO FONTE: {meta['origin_file']} */\n"
                            "/* ================================================== */\n"
                            f"{raw_src}\n\n"
                        )
                    active_blocks.append(block)
                    processed_guids.add(buf_key)

            if not migration_chunks and code_buffer:
                fb_flow = "(sem fluxo EG no project.xml)"
                for k in sorted(code_buffer.keys()):
                    meta = code_metadata[k]
                    raw_src = code_buffer[k]
                    stripped = remove_sas_comments(raw_src).strip()
                    task_label = meta['node_name']
                    migration_chunks.append(
                        _v1_task_banner_start(
                            fb_flow, task_label, exec_ord,
                            meta['origin_file'], meta['source_type'], from_project_xml=False,
                        )
                        + stripped
                        + "\n"
                        + _v1_task_banner_end(task_label, exec_ord)
                    )
                    raw_segments.append(raw_src)
                    exec_ord += 1

            for guid, content in code_buffer.items():
                if guid not in processed_guids:
                    meta = code_metadata[guid]
                    if clean_output:
                        block = (
                            sas_export_style_preamble(
                                meta['node_name'], "(orphan / no flow)", project_abspath, project_filename)
                            + f"{content}\n\n"
                        )
                    else:
                        eg_pre = (
                            eg_style_task_preamble(meta['node_name'], "(orphan / no flow)", project_abspath)
                            if eg_style else ""
                        )
                        block = (
                            eg_pre
                            + "/* ================================================== */\n"
                            f"/* [UNLINKED / RECOVERED NODE] */\n"
                            f"/* STATUS: Orphans (No Flow) */\n"
                            f"/* NOME DO NÓ: {meta['node_name']} */\n"
                            f"/* TIPO: {meta['source_type']} */\n"
                            "/* ================================================== */\n"
                            f"{content}\n\n"
                        )
                    recovered_blocks.append(block)

            v1_pending_embedded = []
            if root is not None:
                try:
                    for elem in root.findall(".//Element"):
                        try:
                            task_code_node = elem.find(".//Code/TaskCode")
                            if task_code_node is None:
                                task_code_node = elem.find(".//Code/SubmittedCode")

                            text_node = elem.find(".//TextElement/Text")
                            raw_code = ""

                            if task_code_node is not None:
                                raw_code = get_element_full_text(task_code_node)

                            if not raw_code.strip() and text_node is not None and elem.get("Type") == "SAS.EG.ProjectElements.Code":
                                raw_code = get_element_full_text(text_node)

                            if not raw_code.strip():
                                continue

                            raw_code_norm = re.sub(r'\s+', ' ', raw_code).lower()
                            if not embedded_xml_has_persistent_file_path(raw_code):
                                if (
                                    "import data wizard" in raw_code_norm
                                    or "/saswork/" in raw_code_norm
                                    or "sas_work" in raw_code_norm
                                ):
                                    continue

                            code_content = clean_sas_code(raw_code)
                            label = get_text_safe(elem, "Label") or "Embedded Task (XML)"

                            content_hash = get_content_hash(code_content)
                            if content_hash in processed_hashes:
                                continue
                            processed_hashes.add(content_hash)

                            v1_pending_embedded.append((label, code_content))

                            if clean_output:
                                block = (
                                    sas_export_style_preamble(
                                        label, "(embedded in project.xml)", project_abspath, project_filename)
                                    + f"{code_content}\n\n"
                                )
                            else:
                                eg_pre = (
                                    eg_style_task_preamble(label, "(embedded in project.xml)", project_abspath)
                                    if eg_style else ""
                                )
                                block = (
                                    eg_pre
                                    + "/* ================================================== */\n"
                                    f"/* NOME DO NÓ: {label} */\n"
                                    "/* TIPO: Embedded Code (Wizard/Task/Program) */\n"
                                    "/* ORIGEM: project.xml */\n"
                                    "/* ================================================== */\n"
                                    f"{code_content}\n\n"
                                )
                            embedded_code_blocks.append(block)
                        except Exception as code_item_err:
                            pass
                except Exception as code_loop_err:
                    pass

            for label, code_content in v1_pending_embedded:
                stripped = remove_sas_comments(code_content).strip()
                xml_flow = "(embedded — project.xml)"
                migration_chunks.append(
                    _v1_task_banner_start(
                        xml_flow, label, exec_ord,
                        "project.xml", "Embedded Code (Wizard/Task/Program)", from_project_xml=True,
                    )
                    + stripped
                    + "\n"
                    + _v1_task_banner_end(label, exec_ord)
                )
                raw_segments.append(code_content)
                exec_ord += 1

            clean_flow_linked = clean_sas_code_flow_linked_only(code_buffer, flow_orders)
            for p in collect_external_file_paths_from_sas_code(clean_flow_linked):
                if p not in file_inventory_map:
                    file_inventory_map[p] = "CODE REF"

            if root is not None:
                for export_elem in root.findall(".//Element[@Type='SAS.EG.ProjectElements.ExportTask']"):
                    export_code = generate_proc_export_structure(
                        root, export_elem, node_map, minimal_comments=clean_output)
                    if export_code:
                        h = get_content_hash(export_code)
                        if h not in processed_hashes:
                            processed_hashes.add(h)
                            lbl = get_text_safe(export_elem, "Label") or "Export Task"
                            if clean_output:
                                block = (
                                    sas_export_style_preamble(
                                        lbl, "Export (Metadados)", project_abspath, project_filename)
                                    + f"{export_code}\n\n"
                                )
                            else:
                                block = (
                                    "/* ================================================== */\n"
                                    f"/* NOME DO NÓ: {lbl} */\n"
                                    "/* FLUXO: Export (Metadados) */\n"
                                    "/* TIPO: SAS Task (Export Structured) */\n"
                                    "/* ================================================== */\n"
                                    f"{export_code}\n\n"
                                )
                            export_blocks.append(block)
                            stripped_exp = remove_sas_comments(export_code).strip()
                            migration_chunks.append(
                                _v1_task_banner_start(
                                    "Export (Metadados)", lbl, exec_ord,
                                    "(ExportTask metadata)", "SAS Task (Export Structured)", from_project_xml=False,
                                )
                                + stripped_exp
                                + "\n"
                                + _v1_task_banner_end(lbl, exec_ord)
                            )
                            raw_segments.append(export_code)
                            exec_ord += 1

            _v1_body_raw_for_scan = "\n\n".join(x for x in raw_segments if x and str(x).strip())
            clean_full_code = remove_sas_comments(_v1_body_raw_for_scan)
            full_code_accumulator = _v1_body_raw_for_scan
            _v1_migration_output = "".join(migration_chunks)

            exported_files = []
            for block in export_blocks:
                m = re.search(r"OUTFILE='([^']+)'", block)
                if m: exported_files.append(m.group(1))

            regex_manual_exports = re.compile(
                r'\b(?:OUTFILE|FILE)\s*=\s*["\']([^"\']+)["\']|\bFILE\s+["\']([^"\']+)["\']', re.IGNORECASE)
            for m in regex_manual_exports.findall(clean_full_code):
                path = m[0] or m[1]
                if len(path) > 3: exported_files.append(path)

            exported_files = sorted(list(set(exported_files)))
            exported_basenames = {os.path.basename(p).lower().strip(' "\'') for p in exported_files}

            # Caminhos em logs/XML internos: só extensões conhecidas (paridade com listagem EG).
            # Evita FILENAME/LIBNAME/%INC de histórico em ficheiros do zip.
            for file_name in file_list:
                if file_name.lower() == 'project.xml':
                    continue
                base_fn = os.path.basename(file_name.replace('\\', '/')).lower()
                if base_fn in ('code.sas', 'query.sql'):
                    continue
                try:
                    raw = z.read(file_name)
                    txt = clean_sas_code(try_decode(raw))
                    if len(txt) > 20:
                        clean_txt = remove_sas_comments(txt)
                        for p in find_paths_in_text(clean_txt):
                            if p not in file_inventory_map:
                                file_inventory_map[p] = "METADATA/LOG"
                except Exception:
                    continue

            import_task_xmls = []

            for file_name in file_list:
                if "importtask" in file_name.lower() and file_name.lower().endswith('.xml'):
                    try:
                        raw = z.read(file_name)
                        import_task_xmls.append(try_decode(raw))
                    except:
                        continue

            if root is not None:
                for elem in root.findall(".//Element[@Type='SAS.EG.ProjectElements.ImportTask']"):
                    try:
                        import_task_xmls.append(ET.tostring(elem, encoding='unicode'))
                    except:
                        import_task_xmls.append(get_element_full_text(elem))

            import_log_work_to_file = {}
            for file_name in file_list:
                fn_norm = file_name.replace("\\", "/").lower()
                if "importtask" not in fn_norm or not fn_norm.endswith("result.log"):
                    continue
                try:
                    log_txt = clean_sas_code(try_decode(z.read(file_name)))
                except Exception:
                    continue
                mem, fpath = parse_import_task_log_datafile(log_txt)
                if mem and fpath:
                    k = mem.upper()
                    prev = import_log_work_to_file.get(k)
                    if not prev or len(fpath) > len(prev):
                        import_log_work_to_file[k] = fpath

            work_temp_inputs_map = {}

            for xml_txt in import_task_xmls:
                xml_dec = decode_eg_path_string(xml_txt)
                path_matches = set(re.findall(
                    r'([a-zA-Z]:\\[^\n\r<*?"]+?\.(?:xlsx|xlsm|xls|csv|txt)|\\\\[^\n\r<*?"]+?\.(?:xlsx|xlsm|xls|csv|txt)|/[^\n\r<*?"]+?\.(?:xlsx|xlsm|xls|csv|txt))',
                    xml_dec, re.IGNORECASE))
                for dm in re.findall(r'DATAFILE\s*=\s*"([^"]+)"', xml_dec, re.IGNORECASE):
                    path_matches.add(decode_eg_path_string(dm.strip()))
                for sm in re.findall(
                    r'(?:Source File|File path)\s*:\s*([^\n\r<]+?\.(?:xlsx|xlsm|xls|csv|txt))\b',
                    xml_dec, re.IGNORECASE):
                    path_matches.add(decode_eg_path_string(sm.strip()))

                wrote_path_from_xml = False
                for raw_path in path_matches:
                    raw_path = raw_path.strip()
                    if len(raw_path) > 5 and not raw_path.startswith('/*'):
                        if "saswork" in raw_path.lower() or "sas_work" in raw_path.lower():
                            continue

                        path_str = decode_eg_path_string(raw_path)

                        sheet_name = ""

                        sheet_match = re.search(r'<(?:WorksheetName|Worksheet|Sheet|SheetName|WORKSHEETNAME)[^>]*>\s*([^<]+)\s*</', xml_txt, re.IGNORECASE)
                        if not sheet_match:
                            sheet_match = re.search(r'(?:WorksheetName|Worksheet|Sheet|SheetName)\s*=\s*["\']([^"\']+)["\']', xml_txt, re.IGNORECASE)
                        if not sheet_match:
                            sheet_match = re.search(r'Name\s*=\s*["\'](?:WorksheetName|Worksheet|Sheet|SheetName)["\'][^>]*?Value\s*=\s*["\']([^"\']+)["\']', xml_txt, re.IGNORECASE)

                        if sheet_match:
                            clean_sheet = sheet_match.group(1).strip()
                            if clean_sheet.lower() not in ('true', 'false', 'yes', 'no', '0', '1') and len(clean_sheet) < 50:
                                clean_sheet = clean_sheet.replace("&amp;amp;", "&").replace("&amp;", "&")
                                sheet_name = f"[SHEET='{clean_sheet}']"
                        if not sheet_name:
                            sel_sh = extract_import_task_selected_table_sheet(xml_dec)
                            if sel_sh:
                                sheet_name = f"[SHEET='{sel_sh}']"
                        if not sheet_name:
                            lbl_sh = extract_import_task_sheet_from_eg_label(xml_txt)
                            if lbl_sh:
                                sheet_name = f"[SHEET='{lbl_sh}']"

                        out_table = os.path.splitext(os.path.basename(path_str))[0]
                        out_match = re.search(r'<OutputData>([^<]+)</OutputData>', xml_txt, re.IGNORECASE)
                        if out_match:
                            out_name = out_match.group(1).strip()
                            if "TEMP" not in out_name.upper() and out_name:
                                out_table = out_name.split('.')[-1] if '.' in out_name else out_name

                        base_stem = os.path.splitext(os.path.basename(path_str))[0]
                        out_table = re.sub(r'[^a-zA-Z0-9_]', '', out_table) or re.sub(
                            r'[^a-zA-Z0-9_]', '', base_stem) or "IMPORT"

                        file_inventory_map[path_str + sheet_name] = f"METADATA IMPORT WIZARD|{out_table}"
                        wrote_path_from_xml = True

                if not wrote_path_from_xml:
                    dm = (
                        extract_import_task_dest_member(xml_dec)
                        or extract_import_task_output_member_fallback(xml_dec)
                    )
                    st = extract_import_task_source_type(xml_dec)
                    if dm:
                        sheet_name = ""
                        sheet_match = re.search(r'<(?:WorksheetName|Worksheet|Sheet|SheetName|WORKSHEETNAME)[^>]*>\s*([^<]+)\s*</', xml_txt, re.IGNORECASE)
                        if sheet_match:
                            cs = sheet_match.group(1).strip()
                            if cs.lower() not in ('true', 'false', 'yes', 'no', '0', '1') and len(cs) < 50:
                                cs = cs.replace("&amp;amp;", "&").replace("&amp;", "&")
                                sheet_name = f"[SHEET='{cs}']"
                        if not sheet_name:
                            sel_sh = extract_import_task_selected_table_sheet(xml_dec)
                            if sel_sh:
                                sheet_name = f"[SHEET='{sel_sh}']"
                        if not sheet_name:
                            lbl_sh = extract_import_task_sheet_from_eg_label(xml_txt)
                            if lbl_sh:
                                sheet_name = f"[SHEET='{lbl_sh}']"
                        resolved = import_log_work_to_file.get(dm.upper())
                        parent_id = extract_import_task_parent_shortcut(xml_dec)
                        if not resolved and parent_id:
                            cand_fp = shortcut_to_path.get(parent_id)
                            if cand_fp:
                                resolved = cand_fp
                        if resolved:
                            inv_key = resolved + sheet_name
                            res_clean = resolved.lower()
                            drop_keys = [
                                k for k, o in list(file_inventory_map.items())
                                if o == "METADATA/LOG"
                                and k.split("[SHEET=", 1)[0].strip().lower() == res_clean
                            ]
                            for dk in drop_keys:
                                del file_inventory_map[dk]
                            file_inventory_map[inv_key] = f"METADATA IMPORT TASK WORK|{dm}|{st or ''}"
                            work_temp_inputs_map[dm.upper()] = (dm, inv_key)
                        else:
                            st_l = (st or "").lower()
                            pseudo_ext = ".csv" if "textfile" in st_l or st_l == "text" else ".xlsx"
                            msg = (
                                f"{dm}{pseudo_ext}{sheet_name} "
                                f"(path not resolved from ImportTask log)"
                            )
                            work_temp_inputs_map.setdefault(dm.upper(), (dm, msg))

            work_temp_file_inputs = sorted(
                work_temp_inputs_map.values(),
                key=lambda t: str(t[0]).upper(),
            )

            data_blocks = []
            for path, origin in sorted(file_inventory_map.items()):
                if origin == "METADATA/LOG":
                    if os.path.basename(path).lower().strip(' "\'') in exported_basenames:
                        continue
                    filename = os.path.basename(path)
                    import_code = generate_proc_import_structure(
                        filename, path, minimal_comments=clean_output)
                    if clean_output:
                        data_blocks.append(f"{import_code}\n\n")
                    else:
                        data_blocks.append(
                            "/* FLUXO: 00. Ingestão (Detectado em Logs/Meta) */\n"
                            f"{import_code}\n\n"
                        )

            for path, origin in sorted(file_inventory_map.items()):
                if "METADATA IMPORT WIZARD" in origin:
                    clean_path_for_check = path.split("[SHEET=")[0].strip()
                    if os.path.basename(clean_path_for_check).lower().strip(' "\'') in exported_basenames:
                        continue

                    table_name = origin.split("|")[1] if "|" in origin else os.path.basename(clean_path_for_check)
                    import_code = generate_proc_import_structure(
                        table_name, path, minimal_comments=clean_output)
                    if clean_output:
                        data_blocks.append(f"{import_code}\n\n")
                    else:
                        data_blocks.append(
                            "/* FLUXO: 00. Ingestão (Detectado via Import Wizard) */\n"
                            f"{import_code}\n\n"
                        )

            for path, origin in sorted(file_inventory_map.items()):
                if origin.startswith("METADATA IMPORT TASK WORK"):
                    clean_path_for_check = path.split("[SHEET=")[0].strip()
                    if os.path.basename(clean_path_for_check).lower().strip(' "\'') in exported_basenames:
                        continue
                    parts = origin.split("|")
                    table_name = parts[1] if len(parts) > 1 else os.path.basename(clean_path_for_check)
                    import_code = generate_proc_import_structure(
                        table_name, path, minimal_comments=clean_output)
                    if clean_output:
                        data_blocks.append(f"{import_code}\n\n")
                    else:
                        data_blocks.append(
                            "/* FLUXO: 00. Ingestão (Import Task → WORK, log do EGP) */\n"
                            f"{import_code}\n\n"
                        )


            imported_files = []
            libname_roots = extract_libname_physical_path_roots(clean_full_code)

            for proc_str in _iter_proc_blocks_to_run_or_quit(clean_flow_linked, 'IMPORT'):
                file_m = re.search(
                    r'(?:DATAFILE|FILE|INFILE)\s*=\s*["\']([^"\']+)["\']', proc_str, re.IGNORECASE)
                if file_m:
                    path = decode_eg_path_string(file_m.group(1).strip())
                    sheet_m = re.search(r'SHEET\s*=\s*["\']([^"\']+)["\']', proc_str, re.IGNORECASE)
                    if sheet_m:
                        path += f"[SHEET='{sheet_m.group(1).strip()}']"
                    if len(path) > 3 and not is_sas_ephemeral_import_path(path):
                        if normalize_path_for_libname_compare(path) not in libname_roots:
                            imported_files.append(path)

            regex_manual_imports = re.compile(
                r'\b(?:INFILE|DATAFILE)\s*=\s*["\']([^"\']+)["\']'
                r'|\bINFILE(?!\s+(?:DATALINES|DATALINES4|CARDS)\b)\s+["\']([^"\']+)["\']',
                re.IGNORECASE,
            )
            for m in regex_manual_imports.findall(clean_flow_linked):
                path = decode_eg_path_string((m[0] or m[1]).strip())
                if len(path) > 3 and not is_sas_ephemeral_import_path(path):
                    if normalize_path_for_libname_compare(path) not in libname_roots:
                        imported_files.append(path)

            for path, origin in file_inventory_map.items():
                if origin == "METADATA/LOG":
                    continue
                clean_path = path.split("[SHEET=")[0].strip()
                if is_sas_ephemeral_import_path(path):
                    continue
                if normalize_path_for_libname_compare(path) in libname_roots:
                    continue
                if os.path.basename(clean_path).lower().strip(' "\'') not in exported_basenames:
                    imported_files.append(path)

            imported_files = dedupe_imported_files_metadata(sorted(set(imported_files)))

            for p in imported_files:
                if "[SHEET=" not in p:
                    continue
                base_l = p.split("[SHEET=", 1)[0].strip().lower()
                for k in list(file_inventory_map.keys()):
                    if file_inventory_map[k] != "CODE REF":
                        continue
                    if k.split("[SHEET=", 1)[0].strip().lower() != base_l:
                        continue
                    if "[SHEET=" in k:
                        continue
                    del file_inventory_map[k]
                if p not in file_inventory_map:
                    file_inventory_map[p] = "CODE REF"

            for _k in list(file_inventory_map.keys()):
                if file_inventory_map.get(_k) != "CODE REF":
                    continue
                if normalize_path_for_libname_compare(_k) in libname_roots:
                    del file_inventory_map[_k]


            included_scripts = extract_included_scripts(clean_full_code)
            code_lets = build_let_dictionary_from_sas_text(remove_sas_comments(clean_full_code))
            xml_lets = build_let_dictionary_from_project_xml(project_xml_text)
            merged_lets = merge_project_and_code_let_dictionaries(xml_lets, code_lets)
            proc_safra_safra_literals = proc_safra_runtime_safra_literals_from_text(
                clean_flow_linked, merged_lets
            )
            (
                macros_used, macros_def, inputs, outputs, dyn_tables, _, _, _pt_full,
            ) = scan_sas_dependencies(clean_full_code, merged_lets)
            (
                _, _, inputs_flow, outputs_flow, dyn_tables_flow,
                work_tbl_reads_flow, tbl_prov_flow, pass_through_engine_flow,
            ) = scan_sas_dependencies(clean_flow_linked, merged_lets)
            lib_defs = extract_libname_definitions(clean_full_code)
            lib_paths_full = _libname_path_dict_from_sas_base(clean_full_code)
            explicit_globals, macro_parameters = analyze_macro_scopes(clean_full_code)
            target, score, reasons = analyze_complexity(clean_full_code)

            # I/O do cabeçalho: só nós no fluxo EG (exclui órfãos / histórico no .txt)
            perm_outputs = [
                t for t in outputs_flow
                if '.' in t and not t.upper().startswith('WORK.')
            ]
            purpose_cls, consultive_score_val, ods_outputs_exts = analyze_consultive_nature(
                clean_flow_linked, perm_outputs
            )
            out_keys = _output_key_set(outputs_flow, merged_lets, proc_safra_safra_literals)
            same_script_re_reads = [
                t
                for t in inputs_flow
                if t not in outputs_flow
                and _input_is_same_script_reuse(t, out_keys, merged_lets, proc_safra_safra_literals)
            ]
            raw_external_inputs = [
                t
                for t in inputs_flow
                if t not in outputs_flow
                and not _input_is_same_script_reuse(t, out_keys, merged_lets, proc_safra_safra_literals)
                and (
                    ('.' in t and not t.upper().startswith('WORK.'))
                    or (pass_through_engine_flow and pass_through_engine_flow.get(t.upper()))
                )
            ]
            work_reads_upper = {x.upper() for x in work_tbl_reads_flow}
            internal_reads_display = [
                t for t in inputs_flow
                if t not in raw_external_inputs and t.upper() not in work_reads_upper
            ]

            engines_map = build_db_mapping(clean_full_code)
            valid_librefs = collect_explicit_libref_names(clean_full_code)

            enriched_external_inputs = []
            imported_libnames = set()
            exported_libnames = set()

            for t in perm_outputs:
                if '.' in t and not t.startswith('`'):
                    prefix = t.split('.')[0].upper()
                    if prefix != 'WORK':
                        exported_libnames.add(prefix)

            for t in raw_external_inputs:
                t_check = re.sub(r'&[A-Za-z0-9_]+(\.)?', '', t).strip('.')
                pt_eng = pass_through_engine_flow.get(t.upper()) if pass_through_engine_flow else None
                if pt_eng:
                    enriched_external_inputs.append(f"{t} [{pt_eng}]")
                    continue

                if '`' in t or (t_check.count('.') >= 2 and '..' not in t_check and '.DBO.' not in t_check.upper() and not t_check.upper().startswith('WORK.')):
                    enriched_external_inputs.append(f"{t} [BIGQUERY/GCP]")
                elif '.DBO.' in t_check.upper():
                    prefix = t.split('.')[0].upper()
                    if prefix in valid_librefs:
                        imported_libnames.add(prefix)
                    enriched_external_inputs.append(f"{t} [SQL Server/Sybase]")
                elif '.' in t:
                    prefix = t.split('.')[0].strip('`').upper()
                    if prefix in valid_librefs:
                        imported_libnames.add(prefix)
                    if prefix in engines_map:
                        enriched_external_inputs.append(f"{t} [{engines_map[prefix]}]")
                    else:
                        enriched_external_inputs.append(f"{t} [SAS/Local]")
                else:
                    enriched_external_inputs.append(t)

            imported_libnames = sorted(list(imported_libnames))
            exported_libnames = sorted(list(exported_libnames))

            _lines_body = _v1_migration_output.strip()
            if _lines_body:
                _lines_body += "\n"
            lines_of_code = sum(1 for line in _lines_body.splitlines() if line.strip())
            procs_list = extract_procs_used(clean_full_code)
            has_ds = has_data_step(clean_full_code)
            count_ds = count_data_steps(clean_full_code)
            conn_libs = extract_connection_librefs(full_code_accumulator)
            is_passthrough = has_passthrough_sql(full_code_accumulator)
            created_at_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            project_lets = extract_let_from_project_xml(project_xml_text)

            sas_external_file_paths = [
                p for p in collect_external_file_paths_from_sas_code(clean_flow_linked)
                if not is_sas_ephemeral_import_path(p)
                and normalize_path_for_libname_compare(p) not in libname_roots
            ]

            migration_task_count = max(0, exec_ord - 1)

            header = [
                "START_METADATA",
                "EXTRACTOR: egps_extractor_v1 (tasks por fluxo project.xml + comentários de início/fim; interior sem comentários)",
                f"PROJECT: {base_name}",
                f"PROJECT_EXTENSION: {file_extension}",
                f"CREATED_AT: {created_at_utc}",
                f"BUSINESS_AREA: {business_area if business_area else '(none)'}",
                f"TARGET_ARCH: {target} (Score: {score})",
                f"PURPOSE_CLASSIFICATION: {purpose_cls}",
                f"CONSULTIVE_SCORE: {consultive_score_val}",
                f"ODS_OUTPUTS_DETECTED: {', '.join(ods_outputs_exts) if ods_outputs_exts else '(none)'}",
                f"TRIGGERS: {reasons}",
                "-" * 40,
                f"LINES_OF_CODE: {lines_of_code}",
                f"CODE_TASKS_COUNT: {migration_task_count}",
                f"DETECTED_PROCS: {', '.join(procs_list) if procs_list else 'none'}",
                f"HAS_DATA_STEP: {'Yes' if has_ds else 'No'} ({count_ds}x)",
                f"HAS_PASSTHROUGH: {'Yes' if is_passthrough else 'No'}",
                "-" * 40,
                f"DETECTED_LIBNAMES: {'; '.join(lib_defs)}",
                f"DETECTED_MACROS_DEFINED: {', '.join(sorted(macros_def))}",
                f"DETECTED_MACROS_USED: {', '.join(sorted(macros_used))}",
                f"MACRO_SCOPE_GLOBALS: {', '.join(explicit_globals) if explicit_globals else '(none)'}",
                f"MACRO_SCOPE_PARAMS: {', '.join(macro_parameters) if macro_parameters else '(none)'}",
                f"CONNECTION_LIBS: {', '.join(conn_libs) if conn_libs else '(none)'}",
                f"INCLUDED SCRIPTS (Dependencies): {', '.join(included_scripts) if included_scripts else '(none)'}",
                "-" * 40,
                "[[ I/O INVENTORY ]]",
                f"EXTERNAL INPUTS (Requires Ingestion): {', '.join(enriched_external_inputs) if enriched_external_inputs else '(none)'}",
                f"SAME-SCRIPT RE-READS (output→read in same script; not external ingestion): {', '.join(same_script_re_reads) if same_script_re_reads else '(none)'}",
                f"IMPORTED_LIBNAMES: {', '.join(imported_libnames) if imported_libnames else '(none)'}",
                f"EXPORTED_LIBNAMES: {', '.join(exported_libnames) if exported_libnames else '(none)'}",
                f"IMPORTED FILES (Requires Ingestion): {', '.join(sas_metadata_path_display(p) for p in imported_files) if imported_files else '(none)'}",
                *(
                    [f"TEMP/DISCARDED_FILE_INPUT: {', '.join(f'WORK.{dm} <- {sas_metadata_path_display(rhs)}' for dm, rhs in sorted(work_temp_file_inputs, key=lambda t: t[0].upper()))}"]
                    if work_temp_file_inputs else []
                ),
                *(
                    [f"TEMP/DISCARDED_TABLE_INPUT: {', '.join(work_tbl_reads_flow)}"]
                    if work_tbl_reads_flow else []
                ),
                *(
                    [tbl_prov_flow]
                    if tbl_prov_flow else []
                ),
                f"EXTERNAL FILE PATHS (fluxo EG): {', '.join(sas_metadata_path_display(p) for p in sas_external_file_paths) if sas_external_file_paths else '(none)'}",
                f"INTERNAL READS (Temp/Local): {', '.join(internal_reads_display) if internal_reads_display else '(none)'}",
                "-" * 40,
                f"PERMANENT OUTPUTS (Target Marts): {', '.join(perm_outputs) if perm_outputs else '(none)'}",
                f"EXPORTED FILES (Artifacts): {', '.join(exported_files) if exported_files else '(none)'}",
                f"TEMP/DISCARDED OUTPUTS: {', '.join([t for t in outputs_flow if t not in perm_outputs])}",
                f"DYNAMIC REFS (Ambiguous): {', '.join(dyn_tables_flow)}",
                "-" * 40,
            ]
            if project_lets:
                header.append("[[ PROJECT LETS (Global Parameters) ]]")
                header.extend(project_lets)
                header.append("")

            final_code = _v1_migration_output.strip()
            if final_code:
                final_code += "\n"

            header.extend(["END_METADATA", "=" * 80 + "\n"])

            with open(output_file, 'w', encoding='utf-8') as out:
                out.write("\n".join(header) + final_code)

                print(
                    f"   [OK] v1 {output_file} | Área: {business_area if business_area else 'Raiz'} | "
                    f"Score: {score} | Tasks (fluxo+XML+export): {migration_task_count} | Ext.Inputs: {len(enriched_external_inputs)}")

    except Exception as e:
        print(f"  [ERRO CRÍTICO] {e}")
        import traceback
        traceback.print_exc()


def _sanitize_txt_stem(name: str) -> str:
    """Stem seguro para nome de ficheiro .txt no Windows (caracteres inválidos → _)."""
    s = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200] if len(s) > 200 else s


def extract_code_from_sas(
    sas_path,
    output_folder,
    business_area="",
    project_label="",
    output_stem=None,
):
    """
    Lê .sas / .txt e aplica o motor de análise estática SAS (scan com %LET; sem project.xml EG).

    project_label: se preenchido (modo pasta-projeto), PROJECT nos metadados = este valor em vez do nome do .sas.
    FILE_SAS nos metadados: sempre o ficheiro-fonte analisado (basename de sas_path), para o relatório 06 do orquestrador.
    output_stem: nome do .txt de saída sem extensão; default = base_name do ficheiro fonte.
    """
    if not os.path.exists(sas_path):
        return

    base_name, ext = os.path.splitext(os.path.basename(sas_path))
    file_extension = ext.lower()
    stem_out = _sanitize_txt_stem(output_stem) if output_stem else _sanitize_txt_stem(base_name)
    output_file = os.path.join(output_folder, f"{stem_out}.txt")
    display_project = project_label.strip() if (project_label and str(project_label).strip()) else base_name
    file_sas_line = os.path.basename(sas_path)

    print(f"-> Processando Script Puro: {base_name}{file_extension}... (PROJECT={display_project})")

    try:
        # 1. Leitura do arquivo físico
        with open(sas_path, 'rb') as f:
            raw_bytes = f.read()
            full_code_accumulator = clean_sas_code(try_decode(raw_bytes))

        # 2. Varredura Estática
        clean_full_code = remove_sas_comments(full_code_accumulator)
        clean_flow_linked = clean_full_code  # script único: sem project.xml; equivalente ao agregado EG
        included_scripts = extract_included_scripts(clean_full_code)

        file_inventory_map = {}
        for p in collect_external_file_paths_from_sas_code(clean_full_code):
            file_inventory_map[p] = "CODE REF"

        exported_files = []
        regex_manual_exports = re.compile(
            r'\b(?:OUTFILE|FILE)\s*=\s*["\']([^"\']+)["\']|\bFILE\s+["\']([^"\']+)["\']', re.IGNORECASE)
        for m in regex_manual_exports.findall(clean_full_code):
            path = m[0] or m[1]
            if len(path) > 3: exported_files.append(path)

        exported_files = sorted(list(set(exported_files)))
        exported_basenames = {os.path.basename(p).lower().strip(' "\'') for p in exported_files}

        merged_lets = build_let_dictionary_from_sas_text(remove_sas_comments(clean_full_code))
        proc_safra_safra_literals = proc_safra_runtime_safra_literals_from_text(
            clean_flow_linked, merged_lets
        )
        (
            macros_used, macros_def, inputs, outputs, dyn_tables,
            work_tbl_reads, tbl_prov, pass_through_engine_flow,
        ) = scan_sas_dependencies(clean_full_code, merged_lets)
        lib_defs = extract_libname_definitions(clean_full_code)
        lib_paths_full = _libname_path_dict_from_sas_base(clean_full_code)
        sas_reads_full_project = _sas_qualified_reads_full_project_tokens(inputs, lib_paths_full)
        comment_only_reads, comment_only_writes = compute_comment_only_qualified_io(
            full_code_accumulator, lib_paths_full, outputs_clean_list=outputs
        )
        explicit_globals, macro_parameters = analyze_macro_scopes(clean_full_code)
        target, score, reasons = analyze_complexity(clean_full_code)

        # 3. Inteligência de Lineage
        perm_outputs = [t for t in outputs if '.' in t and not t.upper().startswith('WORK.')]
        purpose_cls, consultive_score_val, ods_outputs_exts = analyze_consultive_nature(
            clean_flow_linked, perm_outputs
        )
        out_keys = _output_key_set(outputs, merged_lets, proc_safra_safra_literals)
        same_script_re_reads = [
            t
            for t in inputs
            if t not in outputs
            and _input_is_same_script_reuse(t, out_keys, merged_lets, proc_safra_safra_literals)
        ]
        raw_external_inputs = [
            t
            for t in inputs
            if t not in outputs
            and not _input_is_same_script_reuse(t, out_keys, merged_lets, proc_safra_safra_literals)
            and (
                ('.' in t and not t.upper().startswith('WORK.'))
                or (pass_through_engine_flow and pass_through_engine_flow.get(t.upper()))
            )
        ]
        work_reads_upper = {x.upper() for x in work_tbl_reads}
        internal_reads_display = [
            t for t in inputs
            if t not in raw_external_inputs and t.upper() not in work_reads_upper
        ]

        engines_map = build_db_mapping(clean_full_code)
        valid_librefs = collect_explicit_libref_names(clean_full_code)

        enriched_external_inputs = []
        imported_libnames = set()
        exported_libnames = set()

        for t in perm_outputs:
            if '.' in t and not t.startswith('`'):
                prefix = t.split('.')[0].upper()
                if prefix != 'WORK':
                    exported_libnames.add(prefix)

        for t in raw_external_inputs:
            t_check = re.sub(r'&[A-Za-z0-9_]+(\.)?', '', t).strip('.')
            pt_eng = pass_through_engine_flow.get(t.upper()) if pass_through_engine_flow else None
            if pt_eng:
                enriched_external_inputs.append(f"{t} [{pt_eng}]")
                continue

            if '`' in t or (t_check.count(
                    '.') >= 2 and '..' not in t_check and '.DBO.' not in t_check.upper() and not t_check.upper().startswith(
                'WORK.')):
                enriched_external_inputs.append(f"{t} [BIGQUERY/GCP]")
            elif '.DBO.' in t_check.upper():
                prefix = t.split('.')[0].upper()
                if prefix in valid_librefs:
                    imported_libnames.add(prefix)
                enriched_external_inputs.append(f"{t} [SQL Server/Sybase]")
            elif '.' in t:
                prefix = t.split('.')[0].strip('`').upper()
                if prefix in valid_librefs:
                    imported_libnames.add(prefix)
                if prefix in engines_map:
                    enriched_external_inputs.append(f"{t} [{engines_map[prefix]}]")
                else:
                    enriched_external_inputs.append(f"{t} [SAS/Local]")
            else:
                enriched_external_inputs.append(t)

        imported_libnames = sorted(list(imported_libnames))
        exported_libnames = sorted(list(exported_libnames))

        lines_of_code = sum(1 for line in full_code_accumulator.splitlines() if line.strip())
        procs_list = extract_procs_used(clean_full_code)
        has_ds = has_data_step(clean_full_code)
        count_ds = count_data_steps(clean_full_code)
        conn_libs = extract_connection_librefs(full_code_accumulator)
        is_passthrough = has_passthrough_sql(full_code_accumulator)

        imported_files = []
        libname_roots = extract_libname_physical_path_roots(clean_full_code)

        for proc_str in _iter_proc_blocks_to_run_or_quit(clean_flow_linked, 'IMPORT'):
            file_m = re.search(
                r'(?:DATAFILE|FILE|INFILE)\s*=\s*["\']([^"\']+)["\']', proc_str, re.IGNORECASE)
            if file_m:
                path = decode_eg_path_string(file_m.group(1).strip())
                sheet_m = re.search(r'SHEET\s*=\s*["\']([^"\']+)["\']', proc_str, re.IGNORECASE)
                if sheet_m:
                    path += f"[SHEET='{sheet_m.group(1).strip()}']"
                if len(path) > 3 and not is_sas_ephemeral_import_path(path):
                    if normalize_path_for_libname_compare(path) not in libname_roots:
                        imported_files.append(path)

        regex_manual_imports = re.compile(
            r'\b(?:INFILE|DATAFILE)\s*=\s*["\']([^"\']+)["\']'
            r'|\bINFILE(?!\s+(?:DATALINES|DATALINES4|CARDS)\b)\s+["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        for m in regex_manual_imports.findall(clean_flow_linked):
            path = decode_eg_path_string((m[0] or m[1]).strip())
            if len(path) > 3 and not is_sas_ephemeral_import_path(path):
                if normalize_path_for_libname_compare(path) not in libname_roots:
                    imported_files.append(path)

        for path, origin in file_inventory_map.items():
            if origin == "METADATA/LOG":
                continue
            if is_sas_ephemeral_import_path(path):
                continue
            if normalize_path_for_libname_compare(path) in libname_roots:
                continue
            clean_path = path.split("[SHEET=")[0].strip()
            if os.path.basename(clean_path).lower().strip(' "\'') not in exported_basenames:
                imported_files.append(path)

        imported_files = dedupe_imported_files_metadata(sorted(set(imported_files)))

        for p in imported_files:
            if "[SHEET=" not in p:
                continue
            base_l = p.split("[SHEET=", 1)[0].strip().lower()
            for k in list(file_inventory_map.keys()):
                if file_inventory_map[k] != "CODE REF":
                    continue
                if k.split("[SHEET=", 1)[0].strip().lower() != base_l:
                    continue
                if "[SHEET=" in k:
                    continue
                del file_inventory_map[k]
            if p not in file_inventory_map:
                file_inventory_map[p] = "CODE REF"

        for _k in list(file_inventory_map.keys()):
            if file_inventory_map.get(_k) != "CODE REF":
                continue
            if normalize_path_for_libname_compare(_k) in libname_roots:
                del file_inventory_map[_k]

        inv_items = dedupe_file_inventory_map_items(file_inventory_map.items())
        inv_lines = [
            f"[CODE REF] {sas_metadata_path_display(p)}"
            for p, _o in inv_items
        ]

        sas_external_file_paths = [
            p for p in collect_external_file_paths_from_sas_code(clean_flow_linked)
            if not is_sas_ephemeral_import_path(p)
            and normalize_path_for_libname_compare(p) not in libname_roots
        ]

        file_summary = build_file_references_summary(file_inventory_map)

        created_at_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # 5. Geração do Cabeçalho Padrão
        header = [
            "START_METADATA",
            f"PROJECT: {display_project}",
            f"FILE_SAS: {file_sas_line}",
            f"PROJECT_EXTENSION: {file_extension}",
            f"CREATED_AT: {created_at_utc}",
            f"BUSINESS_AREA: {business_area if business_area else '(none)'}",
            f"TARGET_ARCH: {target} (Score: {score})",
            f"PURPOSE_CLASSIFICATION: {purpose_cls}",
            f"CONSULTIVE_SCORE: {consultive_score_val}",
            f"ODS_OUTPUTS_DETECTED: {', '.join(ods_outputs_exts) if ods_outputs_exts else '(none)'}",
            f"TRIGGERS: {reasons}",
            "-" * 40,
            f"LINES_OF_CODE: {lines_of_code}",
            f"CODE_TASKS_COUNT: 1 (Single Script)",
            f"DETECTED_PROCS: {', '.join(procs_list) if procs_list else 'none'}",
            f"HAS_DATA_STEP: {'Yes' if has_ds else 'No'} ({count_ds}x)",
            f"HAS_PASSTHROUGH: {'Yes' if is_passthrough else 'No'}",
            "-" * 40,
            f"DETECTED_LIBNAMES: {'; '.join(lib_defs)}",
            f"DETECTED_MACROS_DEFINED: {', '.join(sorted(macros_def))}",
            f"DETECTED_MACROS_USED: {', '.join(sorted(macros_used))}",
            f"MACRO_SCOPE_GLOBALS: {', '.join(explicit_globals) if explicit_globals else '(none)'}",
            f"MACRO_SCOPE_PARAMS: {', '.join(macro_parameters) if macro_parameters else '(none)'}",
            f"CONNECTION_LIBS: {', '.join(conn_libs) if conn_libs else '(none)'}",
            f"INCLUDED SCRIPTS (Dependencies): {', '.join(included_scripts) if included_scripts else '(none)'}",
            "-" * 40,
            "[[ I/O INVENTORY ]]",
            f"EXTERNAL INPUTS (Requires Ingestion): {', '.join(enriched_external_inputs) if enriched_external_inputs else '(none)'}",
            f"SAME-SCRIPT RE-READS (output→read in same script; not external ingestion): {', '.join(same_script_re_reads) if same_script_re_reads else '(none)'}",
            f"IMPORTED_LIBNAMES: {', '.join(imported_libnames) if imported_libnames else '(none)'}",
            f"EXPORTED_LIBNAMES: {', '.join(exported_libnames) if exported_libnames else '(none)'}",
            f"IMPORTED FILES (Requires Ingestion): {', '.join(sas_metadata_path_display(p) for p in imported_files) if imported_files else '(none)'}",
            *(
                [f"TEMP/DISCARDED_TABLE_INPUT: {', '.join(work_tbl_reads)}"]
                if work_tbl_reads else []
            ),
            *(
                [tbl_prov]
                if tbl_prov else []
            ),
            f"EXTERNAL FILE PATHS (SAS scan — INFILE/INFILE=/FILENAME/%INC/LIBNAME EXCEL|ACCESS|PROC IMPORT + heurística ext.; sem raízes LIBNAME pasta): {', '.join(sas_metadata_path_display(p) for p in sas_external_file_paths) if sas_external_file_paths else '(none)'}",
            f"INTERNAL READS (Temp/Local): {', '.join(internal_reads_display) if internal_reads_display else '(none)'}",
            f"SAS QUALIFIED READS (Full project .txt, incl. outside EG flow): {', '.join(sas_reads_full_project) if sas_reads_full_project else '(none)'}",
            *(
                [f"COMMENT-ONLY QUALIFIED READS (SAS comments only, not executable scan): {', '.join(comment_only_reads)}"]
                if comment_only_reads else []
            ),
            *(
                [f"COMMENT-ONLY QUALIFIED WRITES (DATA in SAS comments only, not executable scan): {', '.join(comment_only_writes)}"]
                if comment_only_writes else []
            ),
            "-" * 40,
            f"PERMANENT OUTPUTS (Target Marts): {', '.join(perm_outputs) if perm_outputs else '(none)'}",
            f"EXPORTED FILES (Artifacts): {', '.join(exported_files) if exported_files else '(none)'}",
            f"TEMP/DISCARDED OUTPUTS: {', '.join([t for t in outputs if t not in perm_outputs])}",
            f"DYNAMIC REFS (Ambiguous): {', '.join(dyn_tables)}",
            "-" * 40,
            f"FILE_REFERENCES_SUMMARY: {file_summary}",
            "-" * 40,
        ]

        header.extend(["[[ FILE INVENTORY ]]", "\n".join(inv_lines) if inv_lines else "(none)", "", "END_METADATA",
                       "=" * 80 + "\n"])

        with open(output_file, 'w', encoding='utf-8') as out:
            out.write("\n".join(header) + full_code_accumulator)

        print(
            f"   [OK] Extraído: {output_file} | Área: {business_area if business_area else 'Raiz'} | Score: {score} | Ext. Inputs: {len(enriched_external_inputs)}")

    except Exception as e:
        print(f"  [ERRO CRÍTICO] Falha ao ler o script {base_name}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if not os.path.exists(DEFAULT_OUTPUT_FOLDER):
        os.makedirs(DEFAULT_OUTPUT_FOLDER)
    print("egps_extractor_v1 — saída em", DEFAULT_OUTPUT_FOLDER, "(.txt para migração IA; ver doc no topo do ficheiro)")
    cli_args = [a for a in sys.argv[1:] if a]
    eg_style = "--eg-style" in cli_args
    clean_output = "--clean" in cli_args
    cli_args = [a for a in cli_args if a not in ("--eg-style", "--clean")]
    input_target = cli_args[0] if cli_args else DEFAULT_INPUT_FOLDER

    if os.path.isfile(input_target):
        # Aceita tanto .sas quanto .txt como scripts puros
        if input_target.lower().endswith(('.sas', '.txt')):
            extract_code_from_sas(input_target, DEFAULT_OUTPUT_FOLDER)
        else:
            extract_code_from_egp(
                input_target, DEFAULT_OUTPUT_FOLDER,
                eg_style=eg_style and not clean_output, clean_output=clean_output)

    elif os.path.isdir(input_target):
        # 1. Varre a pasta Raiz (agora incluindo *.txt)
        for ext in ("*.egp", "*.zip", "*.sas", "*.txt"):
            for f_path in glob.glob(os.path.join(input_target, ext)):
                if f_path.lower().endswith(('.sas', '.txt')):
                    extract_code_from_sas(f_path, DEFAULT_OUTPUT_FOLDER, business_area="")
                else:
                    extract_code_from_egp(
                        f_path, DEFAULT_OUTPUT_FOLDER, business_area="",
                        eg_style=eg_style and not clean_output, clean_output=clean_output)

        # 2. Varre as Subpastas (Business Areas): ficheiros directamente na pasta da área
        subfolders = [f.path for f in os.scandir(input_target) if f.is_dir()]
        for folder in subfolders:
            area_name = os.path.basename(folder)
            for ext in ("*.egp", "*.zip", "*.sas", "*.txt"):
                for f_path in glob.glob(os.path.join(folder, ext)):
                    if f_path.lower().endswith(('.sas', '.txt')):
                        extract_code_from_sas(f_path, DEFAULT_OUTPUT_FOLDER, business_area=area_name)
                    else:
                        extract_code_from_egp(
                            f_path, DEFAULT_OUTPUT_FOLDER, business_area=area_name,
                            eg_style=eg_style and not clean_output, clean_output=clean_output)

            # 3. Pastas-projeto sob a área (ex.: Area/MeuDiretorio/*.sas) — PROJECT = nome do diretório; FILE_SAS na metadata
            try:
                for entry in os.scandir(folder):
                    if not entry.is_dir():
                        continue
                    project_dir = entry.path
                    sas_in_project = sorted(glob.glob(os.path.join(project_dir, "*.sas")))
                    if not sas_in_project:
                        continue
                    project_label = os.path.basename(project_dir)
                    for f_path in sas_in_project:
                        bn, _ = os.path.splitext(os.path.basename(f_path))
                        stem = _sanitize_txt_stem(f"{area_name}__{project_label}__{bn}")
                        extract_code_from_sas(
                            f_path,
                            DEFAULT_OUTPUT_FOLDER,
                            business_area=area_name,
                            project_label=project_label,
                            output_stem=stem,
                        )
            except OSError:
                pass
    else:
        print(f"Aviso: '{input_target}' não encontrado.")