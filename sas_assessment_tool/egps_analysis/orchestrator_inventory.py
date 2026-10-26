"""
orchestrator_inventory.py — orquestrador oficial: consome .txt gerados por egps_extractor.py (cabeçalho com
SAME-SCRIPT RE-READS, IMPORTED_LIBNAMES filtrado por LIBNAME explícito e CONNECTION_LIBS).
Marca source_type 'Connection -> libname_in|out' quando o libref coincide com CONNECTION_LIBS.

Relatório 06: por defeito (--report6-artifact-mode executable) não lista como table_in os suplementos de
diagnóstico (scan completo do .txt fora do fluxo, EG project.xml stale, só comentário). Use 'full' para o
agregador legado completo.
"""
import argparse
import os
import csv
import re
import sys
from collections import defaultdict, deque
from libname_resolver import parse_libmap_from_txt
import egp_decisoes

# Relatório 06 — filtro por direção (campo category)
# libname_in fica FORA das categorias de input (decisao 2026-06-12): o libref sozinho
# nao e dado concreto — as tabelas importadas da libname ja entram como table_in.
# As linhas libname_in continuam no relatorio 06 (scope 'all') como contexto.
_REPORT6_CATEGORIES_IN = frozenset({
    'file_in', 'table_in', 'script_in',
})
_REPORT6_CATEGORIES_OUT = frozenset({
    'table_out', 'libname_out', 'file_out',
})


def _parse_target_arch_technology(val):
    """
    Cabeçalho do .txt: TARGET_ARCH: DATABRICKS (Score: 100) ou DBT_BQ (Score: 0)
    → devolve só a tecnologia, sem o sufixo (Score: …).
    """
    if not val or val == '(none)':
        return ''
    s = val.strip()
    s = re.sub(r'\s*\(\s*Score\s*:\s*[^)]+\)\s*$', '', s, flags=re.IGNORECASE).strip()
    return s


# =====================================================================
# CONFIGURAÇÕES GERAIS
# =====================================================================
INPUT_FOLDER = r'./text_egps'

OUTPUT_REPORT_1 = r'01_prioridade_ingestao.csv'
OUTPUT_REPORT_2 = r'02_entregaveis_marts.csv'
OUTPUT_REPORT_3 = r'03_matriz_dependencias.csv'
OUTPUT_REPORT_4 = r'04_ondas_de_migracao.csv'
OUTPUT_REPORT_5 = r'05_prontidao_egp.csv'
OUTPUT_REPORT_6 = r'06_prontidao_tabela.csv'
OUTPUT_REPORT_7 = r'07_validacao_chameleon.csv'

CHAMELEON_CSV_PATH = r'./src/chameleon.csv'
INVENTARIO_CSV_PATH = r'./src/inventario_transacional.csv'
MODERN_OVERRIDE_CSV_PATH = r'./src/inputs_modernizados.csv'
# Decisões por EGP (excluir duplicata, renomear): valem na leitura do corpus, antes de
# qualquer relatório. Ver egp_decisoes.py.
DECISOES_CSV_PATH = r'./src/egps_decisoes.csv'
REPMAP_XLSX_PATH = r'./src/RepMap.xlsx'
CSV_DELIMITER = ','

# Librefs SAS típicos a excluir de inventário de ingestão (não são "tabelas externas")
_EXCLUDED_SAS_LIBREFS = frozenset({
    'WORK', 'SASUSER', 'SASHELP', 'SASTMP', 'TEMP', 'USER', 'MAPPING',
})
# Nome de libref SAS (engine BASE)
_SAS_LIBREF_TOKEN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,31}$')
# Membro de dataset SAS (simplificado; evita SQL/macros)
_SAS_MEMNAME_TOKEN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _canonical_table_key(name):
    """Chave de comparação para ligar a saída de um EGP à entrada de outro.

    Mesma normalização que o relatório 06 usa na deduplicação de table_in
    (remove crases/aspas, trim, upper). Sem ela, 'Lib.Tbl' e 'LIB.TBL' não
    casavam e as dependências cruzadas (relatórios 03/04) ficavam por ligar.
    """
    if not name:
        return ''
    return str(name).replace('`', '').replace('"', '').replace("'", "").strip().upper()


def _is_plausible_sas_lib_dot_member(name, *, require_lib_in_dict, libname_dict):
    """
    lib.membro concreto (sem macros), exclui WORK etc.
    Se require_lib_in_dict: só aceita se o libref estiver em DETECTED_LIBNAMES (corte de lixo em INTERNAL READS).
    """
    if not name or not isinstance(name, str):
        return False
    s = name.strip().replace('`', '').replace('"', '').replace("'", "")
    if not s or '&' in s or '%' in s:
        return False
    if s.count('.') != 1:
        return False
    lib, memb = s.split('.', 1)
    lib, memb = lib.strip(), memb.strip()
    if not lib or not memb:
        return False
    if '&' in memb or '(' in memb or ')' in memb or ' ' in memb:
        return False
    lu = lib.upper()
    if lu in _EXCLUDED_SAS_LIBREFS:
        return False
    if not _SAS_LIBREF_TOKEN_RE.match(lib):
        return False
    if not _SAS_MEMNAME_TOKEN_RE.match(memb):
        return False
    if require_lib_in_dict:
        return lu in (libname_dict or {})
    return True


def _refine_table_in_source_type(source, table_name, libname_dict):
    """
    Distingue tabela SAS resolvida via LIBNAME (path) vs libref genérico.
    Pass-through explícito: [SYBASEIQ], [ORACLE], [EXECUTE] — prefixo não é LIBNAME SAS.
    """
    src = (source or "").strip()
    src_u = src.upper()
    if 'BIGQUERY' in src_u or 'GCP' in src_u:
        return src if src else 'BIGQUERY/GCP'
    if 'SQL SERVER' in src_u or 'SYBASE' in src_u:
        return src if src else 'SQL Server/Sybase'
    # Preserva rótulos de proveniência (EG XML, scan completo, macro, comentário)
    if any(
        m in src
        for m in (
            'EG project.xml',
            'macro no membro',
            'scan completo',
            'só em comentário',
            '.sas7bdat sob LIBNAME',
        )
    ):
        return src if src else 'SAS/Local'
    if '.' not in (table_name or ''):
        return src if src else 'SAS/Local'
    lib = table_name.split('.', 1)[0].strip().upper()
    if (
        libname_dict
        and lib not in libname_dict
        and src_u
        and 'SAS/LOCAL' not in src_u
        and src_u not in ('LOCAL',)
    ):
        return src
    if libname_dict and lib in libname_dict:
        if not src or 'SAS/LOCAL' in src_u or src_u == 'LOCAL':
            return 'SAS/Local -> libname_in'
        if 'SAS' in src_u and 'LOCAL' in src_u:
            return 'SAS/Local -> libname_in'
    return src if src else 'SAS/Local'


# Um `.sas7bdat` lido por CAMINHO é o arquivo físico do dataset do LIBNAME que aponta para
# aquele diretório — não um "arquivo" a ingerir. Padrão real no corpus: o EGP descompacta em
# disco, lê via libname e recompacta (`x gunzip .../membro.sas7bdat.gz` … `set LIB.MEMBRO` …
# `x gzip …`). Sem a conversão o input fica `file_in` (categoria 'arquivo'), que NUNCA entra
# na árvore de modernização — o gate `if cat in ('table_in', 'table_out')` no main() — e por
# isso jamais pode ser marcado como já modernizado, mesmo com a tabela presente no BigQuery.
# Ver docs/analises/RELATORIO_INPUTS_SAS7BDAT_COMO_TABELA_2026-08-27.md e
# test_sas7bdat_como_tabela.py.
_SAS7BDAT_EXT_RE = re.compile(r'\.sas7bdat$', re.IGNORECASE)
_SAS7BDAT_SRC_LABEL = 'SAS/Local (.sas7bdat sob LIBNAME)'


def _norm_fs_dir(p):
    """Diretório canônico p/ comparar caminho de arquivo com path de LIBNAME."""
    p = (p or "").strip().strip("'\"").strip().replace("\\", "/")
    return re.sub(r'/+', '/', p).rstrip('/').upper()


def _sas7bdat_as_libname_table(file_path, libname_dict, prefer_libs=()):
    """'LIB.MEMBRO' quando `file_path` é um .sas7bdat DENTRO do diretório de um LIBNAME do
    projeto; None caso contrário (aí o input segue como 'arquivo', sem perda).

    O match é por diretório EXATO — nunca por prefixo — para não capturar subpastas de um
    libname pai. Conservador de propósito: membro com macro (`&safra.`) ou com entidade XML
    não desescapada (`&amp;`), nome fora do padrão SAS, libref excluído (WORK e afins) ou
    caminho sem diretório NÃO convertem.

    `prefer_libs`: librefs já vistos como prefixo de table_in no MESMO projeto. Quando mais de
    um libref aponta para o mesmo diretório (alias duplicado — ex.: EMPILHA e MARCACAO no
    mesmo path), reusar o já conhecido faz a linha casar com as safras irmãs já inventariadas.
    Sem preferência aplicável, escolhe o alfabeticamente menor (determinístico). O alias é
    mutável por EGP; a identidade real é (path físico, membro) e segue em artifact_path.
    """
    raw = (file_path or "").strip().replace("\\", "/")
    if not _SAS7BDAT_EXT_RE.search(raw) or "/" not in raw:
        return None
    head, _, base = raw.rpartition("/")
    member = _SAS7BDAT_EXT_RE.sub("", base).strip()
    if not member or not _SAS_MEMNAME_TOKEN_RE.match(member):
        return None
    alvo = _norm_fs_dir(head)
    if not alvo:
        return None
    libs = sorted(lib for lib, path in (libname_dict or {}).items()
                  if _norm_fs_dir(path) == alvo
                  and lib.strip().upper() not in _EXCLUDED_SAS_LIBREFS
                  and _SAS_LIBREF_TOKEN_RE.match(lib.strip()))
    if not libs:
        return None
    pref = {x.strip().upper() for x in (prefer_libs or ())}
    escolhido = next((l for l in libs if l.strip().upper() in pref), libs[0])
    return f"{escolhido.strip().upper()}.{member.upper()}"


def _connection_libs_frozenset(p_data):
    raw = (p_data or {}).get('connection_libs') or []
    return frozenset(x.strip().upper() for x in raw if x and str(x).strip())


def _libref_for_connection_overlay(artifact_name):
    """Primeiro segmento de LIB.MEMBRO, ou o próprio nome se for só o libref."""
    if not artifact_name:
        return ""
    s = artifact_name.replace('`', '').replace('"', '').replace("'", "").strip()
    if '.' in s:
        return s.split('.', 1)[0].strip().upper()
    return s.strip().upper()


def _apply_connection_source_type(cat, src_final, art, connection_set):
    """
    Librefs listados em CONNECTION_LIBS (metadados EG: motores LIBNAME + CONNECT TO) são
    conexões a SGBD; etiqueta source_type sem alterar category nem a árvore Chameleon/inventário.
    """
    if cat not in ('table_in', 'table_out', 'libname_in', 'libname_out'):
        return src_final
    if not connection_set:
        return src_final
    libref = _libref_for_connection_overlay(art)
    if not libref or libref not in connection_set:
        return src_final
    tag = "Connection -> libname_in" if cat in ('table_in', 'libname_in') else "Connection -> libname_out"
    base = (src_final or "").strip()
    if not base or base == tag:
        return tag
    if base.startswith(tag):
        return base
    return f"{tag} | {base}"


def _merge_inputs_with_filtered_internal(inputs_external, internal_raw_tokens, libname_dict):
    internal_objs = []
    for raw in internal_raw_tokens:
        raw = raw.strip()
        if not raw:
            continue
        if not _is_plausible_sas_lib_dot_member(
            raw, require_lib_in_dict=True, libname_dict=libname_dict
        ):
            continue
        internal_objs.append({'table': raw, 'source': 'SAS/Local'})
    return inputs_external + internal_objs


# Caminho de SO ou workbook: não é identificador lib.membro SAS (metadata EXTERNAL INPUTS pode trazer LIBNAME→ficheiro)
_FILEISH_EXT_RE = re.compile(
    r'\.(xlsx|xlsm|xls|xlsb|csv|txt|tsv|zip|gz|sas|json|xml|yaml|yml|parquet|orc|'
    r'sas7bdat|rtf|pdf|htm|html|mdb|accdb)(\s*\[|$)',
    re.IGNORECASE,
)
_FILEISH_EXT_END_RE = re.compile(
    r'\.(xlsx|xlsm|xls|xlsb|csv|txt|tsv|zip|gz|sas|json|xml|yaml|yml|parquet|orc|'
    r'sas7bdat|rtf|pdf|htm|html|mdb|accdb)$',
    re.IGNORECASE,
)


def _exclude_from_table_in_metadata_token(name):
    """
    Exclui de category table_in no relatório 06:
    - caminhos (/ \\ ou unidade Windows)
    - ficheiros por extensão (.xlsx, .csv, …), com ou sem sufixo [SHEET='...']
    - tokens com macro (& / %) — não são tabela concreta
    """
    if not name or not isinstance(name, str):
        return True
    s = name.strip()
    if '&' in s or '%' in s:
        return True
    # Notação V6: CART.TABELA_{MACRO} (membro com variável macro)
    if '{' in s and '.' in s and '/' not in s and '\\' not in s and not re.match(r'^[A-Za-z]:[/\\]', s):
        return False
    base = s.split('[', 1)[0].strip()
    if '/' in s or '\\' in s:
        return True
    if re.match(r'^[A-Za-z]:[/\\]', s):
        return True
    if _FILEISH_EXT_RE.search(base) or _FILEISH_EXT_END_RE.search(base):
        return True
    return False


def _filter_report6_by_scope(artifacts_list, scope):
    """
    scope: 'all' | 'in' | 'out'
    artifacts_list: list of (art, cat, src, pth)
    """
    s = (scope or 'all').strip().lower()
    if s == 'all':
        return artifacts_list
    if s == 'in':
        return [t for t in artifacts_list if t[1] in _REPORT6_CATEGORIES_IN]
    if s == 'out':
        return [t for t in artifacts_list if t[1] in _REPORT6_CATEGORIES_OUT]
    return artifacts_list


def _is_report6_supplemental_diagnostic_row(category, source_type):
    """
    Identifica linhas do relatório 06 adicionadas só como diagnóstico (não “executáveis” no fluxo EG):
    - scan completo do .txt (código órfão/histórico no ZIP)
    - project.xml EG (TableState / datasource UI envelhecido)
    - referências que existem apenas em comentários SAS

    primary inputs (EXTERNAL INPUTS), dynamic_refs, ficheiros, libnames e saídas reais têm outras fontes
    e não batem nestes marcadores.
    """
    s = (source_type or '').strip()
    if category == 'table_in':
        if 'scan completo .txt' in s:
            return True
        if 'EG project.xml' in s and 'não no scan do fluxo' in s:
            return True
        if 'só em comentário — não executado' in s:
            return True
        return False
    if category == 'table_out':
        if 'só em comentário — não executado' in s:
            return True
        return False
    return False


def _filter_report6_diagnostic_rows(artifacts_list, artifact_mode):
    """
    artifact_mode:
      'executable' (default) — omite table_in/table_out suplementares de diagnóstico (recomendado p/ governança).
      'full' — inclui todas as linhas (comportamento legado do agregador).
    """
    am = (artifact_mode or 'executable').strip().lower()
    if am == 'full':
        return artifacts_list
    return [t for t in artifacts_list if not _is_report6_supplemental_diagnostic_row(t[1], t[2])]


# =====================================================================

# Exports vindos de ExportTask do EG (task de wizard, SEM código SAS): o extractor
# sintetiza um `PROC EXPORT` a partir de EXPORT_TASK/EXPORT_OUTPUTFILEPATHNAME do
# project.xml. O arquivo resultante é uma cópia que o EG grava numa pasta de rede — não é
# entregável do EGP, e por isso NÃO conta como output (decisão do usuário 2026-08-18,
# levantada em Cobranças__14.PROTESTO_SELECAO_PUBLICO: protesto_.txt, protesto_carol_.txt,
# protesto_pesados_.txt e 20260209_BASE_PROTESTOS_FEVEREIRO.xlsx). Exports escritos à mão
# no código (PROC EXPORT/FILE=) continuam contando.
# Detecta pelo banner da task no corpo, então já vale para o corpus atual, sem re-extrair;
# depois da re-extração o próprio extractor deixa de listá-los no cabeçalho.
_EXPORT_TASK_BANNER = "(ExportTask metadata)"


def _export_task_outfiles(filepath):
    """Arquivos exportados por ExportTask do EG (metadados), lidos do corpo do .txt."""
    achados = set()
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            texto = f.read()
    except OSError:
        return achados
    if _EXPORT_TASK_BANNER not in texto:
        return achados
    for bloco in re.findall(
            re.escape(_EXPORT_TASK_BANNER) + r"(.*?)FIM TASK", texto, re.S):
        for m in re.findall(r"OUTFILE\s*=\s*'([^']+)'", bloco, re.I):
            achados.add(m.strip())
    return achados


def parse_txt_metadata(filepath):
    data = {
        'project': "UNKNOWN",
        'file_sas': "",
        'project_extension': "",
        'created_at': "",
        'business_area': "",
        'target_arch': "",
        'inputs': [],
        'outputs': [],
        'non_creator': [],
        'exports': [],
        'libnames': [],
        'libname_dict': {},
        'imported_libnames': [],
        'exported_libnames': [],
        'connection_libs': [],
        'files_read': [],
        'included_scripts': [],
        'dynamic_refs': [],
        'sas_reads_full': [],
        'eg_xml_only': [],
        'comment_only_reads': [],
        'comment_only_writes': [],
    }
    inputs_external = []
    internal_reads_raw = []

    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if "END_METADATA" in line:
                break

            line_stripped = line.strip()

            if line_stripped.startswith("PROJECT:"):
                data['project'] = line_stripped.split("PROJECT:", 1)[1].strip()

            elif line_stripped.startswith("FILE_SAS:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['file_sas'] = val

            elif line_stripped.startswith("PROJECT_EXTENSION:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['project_extension'] = val

            elif line_stripped.startswith("CREATED_AT:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['created_at'] = val

            elif line_stripped.startswith("BUSINESS_AREA:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['business_area'] = val

            elif line_stripped.startswith("TARGET_ARCH:"):
                val = line_stripped.split(":", 1)[1].strip()
                data['target_arch'] = _parse_target_arch_technology(val)

            elif line_stripped.startswith("EXTERNAL INPUTS (Requires Ingestion):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    raw_inputs = [x.strip() for x in val.split(",") if x.strip()]
                    for raw in raw_inputs:
                        source_type = ""
                        table_name = raw
                        match = re.search(r'^(.*?)\s*[\[\(]([^\]\)]+)[\]\)]$', raw)
                        if match:
                            table_name = match.group(1).strip()
                            source_type = match.group(2).strip()
                        elif ":" in raw:
                            parts = raw.split(":", 1)
                            source_type = parts[0].strip()
                            table_name = parts[1].strip()
                        inputs_external.append({'table': table_name, 'source': source_type})

            elif line_stripped.startswith(
                "SAME-SCRIPT RE-READS (output→read in same script; not external ingestion):"
            ):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    internal_reads_raw.extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith("INTERNAL READS (Temp/Local):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    internal_reads_raw.extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith("SAS QUALIFIED READS (Full project .txt, incl. outside EG flow):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['sas_reads_full'].extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith(
                "EG XML ONLY (not referenced in flow-linked SAS I/O scan):"
            ):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['eg_xml_only'].extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith("DYNAMIC REFS (Ambiguous):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['dynamic_refs'].extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith(
                "COMMENT-ONLY QUALIFIED READS (SAS comments only, not executable scan):"
            ):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['comment_only_reads'].extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith(
                "COMMENT-ONLY QUALIFIED WRITES (DATA in SAS comments only, not executable scan):"
            ):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['comment_only_writes'].extend(
                        [x.strip() for x in val.split(",") if x.strip()]
                    )

            elif line_stripped.startswith("IMPORTED FILES (Requires Ingestion):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['files_read'] = [x.strip() for x in val.split(",") if x.strip()]

            elif line_stripped.startswith("PERMANENT OUTPUTS (Target Marts):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['outputs'].extend([x.strip() for x in val.split(",") if x.strip()])

            elif line_stripped.startswith("TEMP/DISCARDED OUTPUTS:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['outputs'].extend([x.strip() for x in val.split(",") if x.strip()])


            elif line_stripped.startswith("NON_CREATOR_OUTPUTS"):
                # regra do criador (2026-08-12): outputs que o EGP só apensa/atualiza —
                # ficam no inventário (06) mas NÃO geram aresta produtor→consumidor.
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['non_creator'].extend([x.strip() for x in val.split(",") if x.strip()])
            elif line_stripped.startswith("EXPORTED FILES (Artifacts):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    # ExportTask do EG fica de fora (ver _export_task_outfiles)
                    _task_files = _export_task_outfiles(filepath)
                    data['exports'] = [x.strip() for x in val.split(",")
                                       if x.strip() and x.strip() not in _task_files]

            elif line_stripped.startswith("DETECTED_LIBNAMES:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)" and val != "":
                    data['libnames'] = [x.strip() for x in val.split(";") if x.strip()]
                    for pair in data['libnames']:
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            data['libname_dict'][k.strip().upper()] = v.strip()

            elif line_stripped.startswith("CONNECTION_LIBS:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['connection_libs'] = [x.strip() for x in val.split(",") if x.strip()]

            elif line_stripped.startswith("IMPORTED_LIBNAMES:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['imported_libnames'] = [x.strip().upper() for x in val.split(",") if x.strip()]

            elif line_stripped.startswith("EXPORTED_LIBNAMES:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['exported_libnames'] = [x.strip().upper() for x in val.split(",") if x.strip()]

            elif line_stripped.startswith("INCLUDED SCRIPTS (Dependencies):"):
                val = line_stripped.split(":", 1)[1].strip()
                if val and val != "(none)":
                    data['included_scripts'] = [x.strip() for x in val.split(",") if x.strip()]

    data['inputs'] = _merge_inputs_with_filtered_internal(
        inputs_external, internal_reads_raw, data['libname_dict']
    )
    return data


def format_list_for_csv(lst):
    if not lst: return "(Nenhum)", 0
    return f"({', '.join(lst)})", len(lst)


# =====================================================================
# LEITORES BLINDADOS DE ARQUIVOS EXTERNOS
# =====================================================================
def load_modernization_override(filepath):
    """Lista curada (autoritativa) input -> tabela modernizada (CSV ';' com colunas
    'Nome do input' e 'Nome Modernizado'). Chave normalizada (upper/strip) -> destino.
    Fecha o gap de remap de schema (dba/public -> trusted_*) que o Chameleon, indexado
    pela origem resolvida, nao liga a referencia DBA.*/PUBLIC.* do EGP."""
    m = {}
    if not os.path.exists(filepath):
        print(f"\n\u2139\ufe0f  Override de modernizacao '{filepath}' nao encontrado - ignorando.")
        return m
    with open(filepath, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter=';'):
            src = (row.get('Nome do input') or '').replace('`', '').replace('"', '').replace("'", '').strip().upper()
            dst = (row.get('Nome Modernizado') or '').strip().upper()
            if src:
                m[src] = dst
    print(f"  override de modernizacao: {len(m)} inputs autoritativos ({filepath})")
    return m


def load_chameleon_data(filepath):
    records = []
    if not os.path.exists(filepath):
        print(f"\n⚠️  AVISO: Arquivo '{filepath}' não encontrado. A validação Chameleon será pulada.")
        return records

    try:
        text = ""
        for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'latin1', 'utf-16']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    text = f.read()
                    if text: break
            except Exception:
                continue

        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return records

        try:
            dialect = csv.Sniffer().sniff(lines[0][:2048], delimiters=';,\t|')
            delim = dialect.delimiter
        except:
            delim = ';' if lines[0].count(';') >= lines[0].count(',') else ','

        reader = csv.DictReader(lines, delimiter=delim)
        headers = reader.fieldnames

        col_origem = None
        col_destino = None

        for h in headers:
            if not h: continue
            clean_h = h.strip().lower()
            if 'origem' in clean_h and 'tabela' in clean_h and 'work' not in clean_h:
                col_origem = h
            elif 'tabela' in clean_h and 'origem' not in clean_h and 'work' not in clean_h:
                col_destino = h

        if not col_origem and not col_destino:
            print(f"\n❌ ERRO: '{filepath}' não tem coluna de tabela origem/destino "
                  f"reconhecível (cabeçalhos lidos: {headers}). O catálogo NÃO foi "
                  f"carregado — sem ele, TODA tabela é classificada como 'a ingerir'. "
                  f"Confira o export do Chameleon (passo 2 do pipeline).")
            return records

        for row in reader:
            tb_origem_raw = str(row.get(col_origem, '')).strip(" '\"").upper() if col_origem else ''
            tb_destino_raw = str(row.get(col_destino, '')).strip(" '\"").upper() if col_destino else ''

            projeto = ""
            dataset = ""
            if tb_destino_raw and tb_destino_raw.count('.') >= 2:
                parts = tb_destino_raw.split('.')
                projeto = parts[0]
                dataset = parts[1]

            records.append({
                'NmTabelaOrigem': tb_origem_raw,
                'NmTabelaDestino': tb_destino_raw,
                'NmDataSet': dataset,
                'NmProjeto': projeto,
                'DsOrigem': str(row.get('DsOrigem', '')).strip()
            })

    except Exception as e:
        # NUNCA silencioso: este except cobria o corpo INTEIRO (abertura, sniff do
        # delimitador, header, parse das linhas) e devolvia [] sem uma palavra. Um
        # catálogo corrompido/truncado/re-encodado virava "nenhuma tabela modernizada"
        # com cara de resultado legítimo — e, como o retorno é uma lista vazia e não
        # uma exceção, o try/except de quem chama também nunca disparava.
        print(f"\n❌ ERRO ao ler '{filepath}': {type(e).__name__}: {e}\n"
              f"   O catálogo Chameleon NÃO foi carregado ({len(records)} linha(s) "
              f"aproveitada(s)). Sem ele, TODA tabela é classificada como 'a ingerir'.")

    return records


def load_inventario_data(filepath):
    inventario_map = {}
    if not os.path.exists(filepath):
        print(f"\n⚠️  AVISO: Arquivo '{filepath}' não encontrado. Validação de transacional legados pulada.")
        return inventario_map

    try:
        text = ""
        for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'latin1', 'utf-16']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    text = f.read()
                    if text: break
            except Exception:
                continue

        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return inventario_map

        try:
            dialect = csv.Sniffer().sniff(lines[0][:2048], delimiters=';,\t|')
            delim = dialect.delimiter
        except:
            delim = ';' if lines[0].count(';') >= lines[0].count(',') else ','

        reader = csv.DictReader(lines, delimiter=delim)
        headers = reader.fieldnames

        col_obj = None
        col_sgbd = None
        col_db = None

        for h in headers:
            if not h: continue
            clean_h = h.strip().lower()
            if 'nomeobjeto' in clean_h:
                col_obj = h
            elif 'fabricantesgbd' in clean_h or 'sgbd' in clean_h:
                col_sgbd = h
            elif 'database' in clean_h or 'db' == clean_h:
                col_db = h

        for row in reader:
            obj_raw = str(row.get(col_obj, '')).strip(" '\"").upper()
            db_raw = str(row.get(col_db, '')).strip(" '\"").upper() if col_db else ''
            sgbd_raw = str(row.get(col_sgbd, '')).strip(" '\"").upper() if col_sgbd else ''

            if obj_raw:
                chave_exata = f"{db_raw}.{obj_raw}" if db_raw else obj_raw
                inventario_map[chave_exata] = sgbd_raw

    except Exception as e:
        pass

    return inventario_map


def is_strict_match(art_clean, cham_val):
    if not cham_val or not art_clean: return False
    if art_clean == cham_val: return True
    if cham_val.endswith(f".{art_clean}"): return True
    if '.' in art_clean:
        prefix, table = art_clean.split('.', 1)
        if prefix in cham_val and cham_val.endswith(f".{table}"):
            return True
    return False


def main(prontidao_scope='all', report6_artifact_mode='executable'):
    """
    prontidao_scope: 'all' (default) — relatório 06 completo;
                     'in' — só categorias de entrada (file_in, table_in, script_in; libname_in é contexto, não input);
                     'out' — só categorias de saída (table_out, libname_out, file_out).
    Relatórios 01–05 não são filtrados.

    report6_artifact_mode: 'executable' (default) — relatório 06 sem suplementos de diagnóstico
      (scan completo .txt, EG project.xml “only”, só comentário);
      'full' — inclui essas linhas como no agregador anterior.
    """
    if not os.path.exists(INPUT_FOLDER):
        print(f"Erro: O diretório '{INPUT_FOLDER}' não existe.")
        return

    try:
        decisoes = egp_decisoes.carrega(DECISOES_CSV_PATH)
        corpus = egp_decisoes.aplica_ao_corpus(INPUT_FOLDER, decisoes)
    except egp_decisoes.DecisaoInvalida as e:
        print(f"\n❌ ABORTADO: {e}")
        sys.exit(2)
    if not corpus:
        print(f"Nenhum arquivo .txt encontrado em '{INPUT_FOLDER}'.")
        return

    print(f"🔍 Analisando {len(corpus)} projetos...")
    print(f"  decisões por EGP: {len(decisoes.excluidos)} excluídos, "
          f"{len(decisoes.renomes)} renomeados ({DECISOES_CSV_PATH})")

    chameleon_records = load_chameleon_data(CHAMELEON_CSV_PATH)
    # Pós-condição: arquivo presente mas 0 registros = catálogo quebrado, não "nada
    # modernizado". O corpus real tem milhares de linhas; seguir aqui produziria um
    # 06_prontidao_tabela.csv inteiro marcando 'a ingerir' — um relatório plausível e
    # completamente errado, que alimenta decisão de ingestão. Melhor parar.
    if os.path.exists(CHAMELEON_CSV_PATH) and not chameleon_records:
        print(f"\n❌ ABORTADO: '{CHAMELEON_CSV_PATH}' existe mas não produziu nenhum "
              f"registro utilizável.\n"
              f"   Rode o passo 2 do pipeline (gcp_bigquery_table_data_export.py) e "
              f"confira o arquivo antes de reexecutar.\n"
              f"   Para seguir mesmo assim (relatório sem validação de modernização), "
              f"renomeie/remova o arquivo — a ausência é tratada como 'pular validação'.")
        sys.exit(2)
    modern_override = load_modernization_override(MODERN_OVERRIDE_CSV_PATH)
    inventario_map = load_inventario_data(INVENTARIO_CSV_PATH)

    # RepMap como tradutor destino-IQ/libref -> base de origem ASE. O Chameleon e chaveado pela
    # origem (ex.: trusted_dbcred / dbcred.dbo.tbproposta); o SAS costuma referenciar o alias do
    # destino de replica no IQ (ex.: libref DBA). Sem essa ponte, DBA.TBPROPOSTA nao casa com a
    # modernizada trusted_dbcred.tbproposta mesmo ela existindo (DBsource=DBCRED -> DBtarget=DBA).
    _rep_rows = []
    _rep_key_index = {}
    _repmap_src_cache = {}
    if os.path.exists(REPMAP_XLSX_PATH):
        try:
            from validate_table_in_vs_repmap import (
                load_repmap_rows as _load_repmap_rows,
                repmap_derived_keys as _repmap_derived_keys,
                match_artifact as _match_artifact,
                norm_upper as _nu,
            )
            _rep_rows = _load_repmap_rows(REPMAP_XLSX_PATH)
            for _r in _rep_rows:
                for _k in _repmap_derived_keys(_r):
                    _rep_key_index.setdefault(_k, []).append(_r)
            print(f'  -> RepMap carregado: {len(_rep_rows)} linhas (ponte libref/destino IQ -> origem).')
        except Exception as _e:
            print(f'\n⚠️  AVISO: RepMap nao carregado ({_e}). Ponte de replica desativada.')
            _rep_rows = []
            _rep_key_index = {}
    else:
        print(f"\n⚠️  AVISO: '{REPMAP_XLSX_PATH}' nao encontrado. Ponte de replica desativada.")

    def _repmap_source_keys(art_clean):
        """Chaves 'DBsource.tabela' upper das linhas RepMap casadas com o artefato (ponte p/ Chameleon)."""
        if not _rep_rows:
            return set()
        cached = _repmap_src_cache.get(art_clean)
        if cached is not None:
            return cached
        keys = set()
        try:
            lvl, _desc, hits = _match_artifact(art_clean, _rep_rows, _rep_key_index)
            if lvl not in ('SKIP', 'NOT_FOUND'):
                for h in hits:
                    dbs = _nu(h['DBsource'])
                    for tb in (_nu(h['Tabela']), _nu(h['TabRep'])):
                        if dbs and tb:
                            keys.add(f'{dbs}.{tb}')
        except Exception:
            keys = set()
        _repmap_src_cache[art_clean] = keys
        return keys

    project_catalog = {}
    file_metadata = {}
    table_to_generator = {}
    table_to_producers = defaultdict(set)
    table_to_consumers = defaultdict(list)

    def _is_unresolved_macro_table(name):
        # placeholder de macro nao-resolvido (&VAR, {…}) nao e tabela real — fora do grafo de dependencias
        return any(ch in (name or '') for ch in ('&', '{', '}'))

    for arq in corpus:
        filepath = arq.caminho
        filename = os.path.basename(filepath)
        p_data = parse_txt_metadata(filepath)
        p_data['project'] = arq.projeto  # nome publicado (egp_decisoes)
        p_data['libmap'] = parse_libmap_from_txt(filepath)
        file_metadata[filename] = p_data
        proj = p_data['project']
        if proj in project_catalog:
            # projeto multi-ficheiro (sas_files/<projeto>/*.sas): unir I/O em vez de sobrescrever
            base = project_catalog[proj]
            seen_in = {i['table'] for i in base['inputs']}
            base['inputs'].extend(i for i in p_data['inputs'] if i['table'] not in seen_in)
            base['outputs'].extend(t for t in p_data['outputs'] if t not in base['outputs'])
            base['exports'].extend(e for e in p_data['exports'] if e not in base['exports'])
            base['files_read'].extend(x for x in p_data['files_read'] if x not in base['files_read'])
            base_lm = base.setdefault('libmap', {})
            for _lib, _paths in p_data.get('libmap', {}).items():
                base_lm.setdefault(_lib, set()).update(_paths)
        else:
            project_catalog[proj] = p_data

    def _member_key(name):
        m = (name or '').strip().strip('"').strip("'").replace('\\', '/')
        m = m.rsplit('/', 1)[-1]  # output físico (data '/caminho/tabela'): usa o basename
        m = m.upper().split('.')[-1]
        return re.sub(r'[^A-Z0-9_]', '', m)

    def _dataset_key(fname):
        b = (fname or '').strip().strip('"').strip("'").rsplit('/', 1)[-1]
        b = re.sub(r'\.sas7bdat$', '', b, flags=re.IGNORECASE)
        return re.sub(r'[^A-Z0-9_]', '', b.upper())

    proj_output_keys = defaultdict(set)
    out_member_index = defaultdict(set)
    for proj, data in project_catalog.items():
        _nc = {_canonical_table_key(t) for t in data.get('non_creator', ())}
        for tb in data['outputs']:
            if _is_unresolved_macro_table(tb):
                continue
            if _canonical_table_key(tb) in _nc:
                continue  # regra do criador: apensa/atualiza não é produtor
            k = _canonical_table_key(tb)
            table_to_producers[k].add(proj)
            proj_output_keys[proj].add(k)
            out_member_index[_member_key(tb)].add(proj)
        seen_cons = set()
        for inp_obj in data['inputs']:
            t = inp_obj['table']
            if t in seen_cons:
                continue
            seen_cons.add(t)
            table_to_consumers[t].append(proj)

    table_to_generator = {k: sorted(ps)[0] for k, ps in table_to_producers.items()}

    adj_list = defaultdict(list)
    in_degree = {proj: 0 for proj in project_catalog.keys()}
    matrix_rows = []
    seen_matrix = set()

    for proj, data in project_catalog.items():
        for inp_obj in data['inputs']:
            inp_table = inp_obj['table']
            if _is_unresolved_macro_table(inp_table):
                continue
            k_in = _canonical_table_key(inp_table)
            if k_in in proj_output_keys.get(proj, ()):
                # leitor TAMBEM escreve a tabela: partilha/append, nao e produtor→consumidor
                continue
            producers = table_to_producers.get(k_in, ())
            n_prod = len(producers)
            for generator in sorted(producers):
                if generator == proj:
                    continue
                if proj not in adj_list[generator]:
                    adj_list[generator].append(proj)
                    in_degree[proj] += 1
                if (proj, generator, inp_table) not in seen_matrix:
                    seen_matrix.add((proj, generator, inp_table))
                    matrix_rows.append([proj, generator, inp_table, n_prod])

    # vinculo extra: .sas7bdat lido (files_read) == dataset de SAIDA (table_out) de outro EGP
    # casa basename do .sas7bdat contra o MEMBRO do output; guards contra nome generico/ambiguo
    GENERIC_MEMBER = {"BASE", "DADOS", "TEMP", "AUX", "RESULTADO", "CARTEIRA",
                      "FINAL", "SAIDA", "TESTE", "HISTORICO", "RESUMO"}
    for proj, data in project_catalog.items():
        for fr in data.get('files_read', ()):
            if not fr.lower().endswith('.sas7bdat'):
                continue
            if any(ch in fr for ch in ('&', '{', '}')):
                continue
            key = _dataset_key(fr)
            if len(key) < 6 or key.isdigit() or key in GENERIC_MEMBER:
                continue
            producers = out_member_index.get(key)
            if not producers or proj in producers or len(producers) > 3:
                continue
            n_prod = len(producers)
            for generator in sorted(producers):
                if generator == proj:
                    continue
                if proj not in adj_list[generator]:
                    adj_list[generator].append(proj)
                    in_degree[proj] += 1
                rk = (proj, generator, fr)
                if rk not in seen_matrix:
                    seen_matrix.add(rk)
                    matrix_rows.append([proj, generator, fr, n_prod])

    # --- LINHAGEM POR PATH FISICO (SAS/Local): recupera arestas que o casamento por NOME
    #     perde quando o mesmo path tem nomes de libname DIFERENTES (alias). ADITIVO.
    def _split_lib_member(ref):
        c = _canonical_table_key(ref)
        lib, _sep, member = c.partition('.')
        return lib, member
    gen_path = defaultdict(set)
    proj_out_path = defaultdict(set)
    for proj, data in project_catalog.items():
        lm = data.get('libmap', {})
        _nc = {_canonical_table_key(t) for t in data.get('non_creator', ())}
        for tb in data['outputs']:
            if _is_unresolved_macro_table(tb):
                continue
            if _canonical_table_key(tb) in _nc:
                continue  # regra do criador: apensa/atualiza não é produtor
            if '/' in tb or '\\' in tb:
                # output físico (data '/caminho/tabela';): o produtor já declara o path —
                # entra direto na chave (dir, MEMBRO), normalizada como no libname_resolver
                # (lower, '/' único, sem barra final), casando consumidores via LIBNAME.
                pn = re.sub(r'/+', '/', tb.replace('\\', '/')).rstrip('/').lower()
                d, _, b = pn.rpartition('/')
                if d and b:
                    gen_path[(d, b.upper())].add(proj)
                    proj_out_path[proj].add((d, b.upper()))
                continue
            lib, member = _split_lib_member(tb)
            for p in lm.get(lib, ()):
                gen_path[(p, member)].add(proj)
                proj_out_path[proj].add((p, member))
    rec_path_edges = 0
    for proj, data in project_catalog.items():
        lm = data.get('libmap', {})
        for inp_obj in data['inputs']:
            inp_table = inp_obj['table']
            if _is_unresolved_macro_table(inp_table):
                continue
            lib, member = _split_lib_member(inp_table)
            for p in lm.get(lib, ()):
                key = (p, member)
                if key in proj_out_path.get(proj, ()):
                    continue
                gs = gen_path.get(key, ())
                n_prod = len(gs)
                for g in sorted(gs):
                    if g == proj:
                        continue
                    if proj not in adj_list[g]:
                        adj_list[g].append(proj)
                        in_degree[proj] += 1
                    rk = (proj, g, inp_table)
                    if rk not in seen_matrix:
                        seen_matrix.add(rk)
                        matrix_rows.append([proj, g, inp_table, n_prod])
                        rec_path_edges += 1
    print(f'  Linhagem por path: +{rec_path_edges} arestas recuperadas (alias de libname / mesmo path).')

    # --- CHAVE FISICA (path, MEMBRO) POR VIA -------------------------------------------
    # O casamento produtor<->consumidor JA e fisico (gen_path/proj_out_path acima), mas a
    # coluna Via_Tabela guarda so o alias do LADO CONSUMIDOR: a mesma tabela fisica sai como
    # COMPJUR.X para quem le e DB1351.X para quem escreve, e como INSIGHT./_INSIGHT./BASES.
    # em outros casos. Quem consome a chave por NOME (poda por produtor canonico no publish e
    # em _prune_edges/sas_output_producer_choice) casa por string e falha em silencio nesses
    # 15% de vias com alias divergente. Exportar a chave fisica permite chavear por identidade
    # em vez de nome. ADITIVO: coluna nova, nenhuma aresta muda.
    #
    # Preferencia: candidatos do consumidor INTERSECAO saidas fisicas do produtor (chave exata
    # da tabela compartilhada). Sem intersecao, cai nos candidatos do consumidor. Via com path
    # explicito (.sas7bdat lido) resolve direto, com a mesma normalizacao do libname_resolver.
    # Ambiguidade (>1 candidato) e exportada junta em ' | ' em vez de escolher arbitrariamente.
    def _phys_keys_for_via(consumer, via, producer):
        if '/' in via or '\\' in via:
            pn = re.sub(r'/+', '/', via.replace('\\', '/')).rstrip('/').lower()
            d, _, b = pn.rpartition('/')
            return [(d, b.upper())] if d and b else []
        lib, member = _split_lib_member(via)
        if not member:
            return []
        lm = project_catalog.get(consumer, {}).get('libmap', {})
        cand = {(p, member) for p in lm.get(lib, ())}
        inter = cand & proj_out_path.get(producer, set())
        return sorted(inter or cand)

    n_chave = n_ambigua = 0
    for row in matrix_rows:
        ks = _phys_keys_for_via(row[0], row[2], row[1])
        row.append(' | '.join(f'{p}::{m}' for p, m in ks))
        if ks:
            n_chave += 1
            if len(ks) > 1:
                n_ambigua += 1
    print(f'  Chave fisica por via: {n_chave}/{len(matrix_rows)} arestas com (path, MEMBRO) '
          f'resolvido ({n_ambigua} ambigua(s), >1 path candidato).')

    with open(OUTPUT_REPORT_1, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=CSV_DELIMITER)
        writer.writerow(['Tabela', 'Tipo_Origem', 'Qtd_Projetos_Impactados', 'Projetos_Dependentes'])
        for tb, consumers in sorted(table_to_consumers.items(), key=lambda i: len(i[1]), reverse=True):
            gen = table_to_generator.get(_canonical_table_key(tb))
            origem = f"Gerado Internamente ({gen})" if gen else "Requer Ingestão Externa"
            consumers_str, _ = format_list_for_csv(sorted(consumers))
            writer.writerow([tb, origem, len(consumers), consumers_str])

    with open(OUTPUT_REPORT_2, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=CSV_DELIMITER)
        # Add created_at
        writer.writerow(['Projeto', 'Tipo_Entregavel', 'Nome_Artefato', 'project_extension', 'created_at'])
        for proj, data in sorted(project_catalog.items()):
            ext = data.get('project_extension', '')
            created_at = data.get('created_at', '')
            for tb in data['outputs']: writer.writerow([proj, 'Tabela de Banco (Mart)', tb, ext, created_at])
            for exp in data['exports']: writer.writerow([proj, 'Arquivo Físico (Export)', exp, ext, created_at])

    with open(OUTPUT_REPORT_3, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=CSV_DELIMITER)
        # Add created_at
        writer.writerow(
            ['Projeto_Alvo (Precisa Migrar)', 'Depende_Do_Projeto', 'Via_Tabela', 'n_produtores', 'Via_Chave_Fisica', 'project_extension', 'created_at'])
        for row in sorted(matrix_rows):
            proj_alvo = row[0]
            ext = project_catalog[proj_alvo].get('project_extension', '')
            created_at = project_catalog[proj_alvo].get('created_at', '')
            writer.writerow(row + [ext, created_at])

    # Ondas via condensacao de SCC (Tarjan): membros de ciclo vao para a onda do
    # componente (rotulados 'Ciclo'); o restante (jusante) continua ordenavel —
    # criterio da consultoria: ciclo nao bloqueia o resto do plano.
    scc_index = {}
    _idx = {}
    _low = {}
    _on = {}
    _stk = []
    _ctr = [0]
    _sccs = []

    def _strongconnect(v0):
        work = [(v0, iter(adj_list.get(v0, ())))]
        _idx[v0] = _low[v0] = _ctr[0]; _ctr[0] += 1
        _stk.append(v0); _on[v0] = True
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in _idx:
                    _idx[w] = _low[w] = _ctr[0]; _ctr[0] += 1
                    _stk.append(w); _on[w] = True
                    work.append((w, iter(adj_list.get(w, ()))))
                    advanced = True
                    break
                elif _on.get(w):
                    _low[v] = min(_low[v], _idx[w])
            if advanced:
                continue
            work.pop()
            if work:
                _low[work[-1][0]] = min(_low[work[-1][0]], _low[v])
            if _low[v] == _idx[v]:
                comp = []
                while True:
                    w = _stk.pop(); _on[w] = False; comp.append(w)
                    if w == v:
                        break
                _sccs.append(comp)

    for _v in list(project_catalog.keys()):
        if _v not in _idx:
            _strongconnect(_v)
    for _ci, _comp in enumerate(_sccs):
        for _v in _comp:
            scc_index[_v] = _ci
    scc_members = {ci: comp for ci, comp in enumerate(_sccs)}

    cond_adj = defaultdict(set)
    cond_indeg = {ci: 0 for ci in scc_members}
    for u, vs in adj_list.items():
        for v in vs:
            cu, cv = scc_index[u], scc_index[v]
            if cu != cv and cv not in cond_adj[cu]:
                cond_adj[cu].add(cv)
                cond_indeg[cv] += 1

    ondas = {}
    queue = deque([ci for ci, deg in cond_indeg.items() if deg == 0])
    current_wave = 0
    while queue:
        level_size = len(queue)
        for _ in range(level_size):
            ci = queue.popleft()
            cyclic = len(scc_members[ci]) > 1
            for proj in scc_members[ci]:
                ondas[proj] = (f"Onda {current_wave} (Ciclo - quebrar manualmente)"
                               if cyclic else f"Onda {current_wave}")
            for cj in cond_adj[ci]:
                cond_indeg[cj] -= 1
                if cond_indeg[cj] == 0:
                    queue.append(cj)
        current_wave += 1

    with open(OUTPUT_REPORT_4, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=CSV_DELIMITER)
        # Add created_at
        writer.writerow(['Projeto', 'Onda_de_Conversao', 'Status_Orquestrador', 'project_extension', 'created_at'])
        for proj, onda in sorted(ondas.items(), key=lambda x: (x[1], x[0])):
            ext = project_catalog[proj].get('project_extension', '')
            created_at = project_catalog[proj].get('created_at', '')
            writer.writerow([proj, onda, "Bloqueado" if "ERRO" in onda else "Pronto", ext, created_at])

    print("📊 Gerando Relatório 5 (Blueprint de Prontidão)...")
    with open(OUTPUT_REPORT_5, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=CSV_DELIMITER)
        # Add created_at
        writer.writerow([
            'Projeto', 'Area', 'Onda de Migracao', 'Qtd Libnames', 'Libnames Mapeadas',
            'Qtd Scripts Incluidos', 'Scripts Incluidos', 'Qtd Arquivos Fisicos',
            'Arquivos_Consumidos', 'Qtd Tabelas Consumidas', 'Tabelas Consumidas',
            'Qtd Tabelas Geradas', 'Tabelas Geradas', 'Qtd Arquivos Exportados', 'Arquivos Exportados',
            'project_extension', 'created_at'
        ])

        for proj, onda in sorted(ondas.items(), key=lambda x: (x[1], x[0])):
            p_data = project_catalog[proj]
            inputs_only_names = [i['table'] for i in p_data['inputs']]

            libnames_str, count_lib = format_list_for_csv(p_data['libnames'])
            included_str, count_inc = format_list_for_csv(p_data['included_scripts'])
            files_read_str, count_files = format_list_for_csv(p_data['files_read'])
            inputs_str, count_inp = format_list_for_csv(inputs_only_names)
            outputs_str, count_out = format_list_for_csv(p_data['outputs'])
            exports_str, count_exp = format_list_for_csv(p_data['exports'])

            ext = p_data.get('project_extension', '')
            created_at = p_data.get('created_at', '')

            writer.writerow([
                proj, p_data.get('business_area', ''), onda, count_lib, libnames_str, count_inc, included_str,
                count_files, files_read_str, count_inp, inputs_str,
                count_out, outputs_str, count_exp, exports_str, ext, created_at
            ])

    print("📊 Gerando Relatório 6 (Prontidão Vertical + Chameleon + Inventário Unificado)...")

    with open(OUTPUT_REPORT_6, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=CSV_DELIMITER)

        # CABEÇALHO UNIFICADO (file_sas após project; project_extension, created_at, target_arch no final)
        writer.writerow([
            'project', 'file_sas', 'area', 'artifact', 'path', 'category', 'source_type',
            'status_validacao', 'chameleon_NmTabelaOrigem', 'chameleon_NmTabelaDestino',
            'chameleon_NmDataSet', 'chameleon_NmProjeto', 'chameleon_DsOrigem',
            'project_extension', 'created_at', 'target_arch'
        ])

        def clean_artifact(art):
            art = art.strip()
            if re.match(r'^[a-zA-Z]:\s+', art):
                art = art[2:].strip()
            return art

        def get_basename(filepath):
            return filepath.replace('\\', '/').split('/')[-1]

        for filename in sorted(file_metadata.keys()):
            p_data = file_metadata[filename]
            proj = p_data['project']
            artifacts_list = []

            ext = p_data.get('project_extension', '')
            created_at = p_data.get('created_at', '')
            target_arch_col = p_data.get('target_arch', '')
            file_sas_col = p_data.get('file_sas', '')

            # .sas7bdat dentro do diretório de um LIBNAME é TABELA, não arquivo. A resolução
            # fica adiada para depois do laço de `inputs`: precisa dos librefs já vistos como
            # table_in p/ desempatar alias duplicado e p/ deduplicar contra seen_table_in
            # quando a MESMA tabela também é lida por libname. Ver _sas7bdat_as_libname_table.
            sas7bdat_sob_libname = []
            for item in p_data.get('files_read', []):
                clean_item = clean_artifact(item)
                if _sas7bdat_as_libname_table(clean_item, p_data.get('libname_dict') or {}):
                    sas7bdat_sob_libname.append(clean_item)
                    continue
                artifacts_list.append((get_basename(clean_item), 'file_in', '', clean_item))

            for item in p_data.get('included_scripts', []):
                clean_item = clean_artifact(item)
                artifacts_list.append((get_basename(clean_item), 'script_in', '', clean_item))

            seen_table_in = set()

            for inp_obj in p_data.get('inputs', []):
                table_name = clean_artifact(inp_obj['table'])
                if _exclude_from_table_in_metadata_token(table_name):
                    continue
                artifact_path = ""
                if '.' in table_name:
                    lib_prefix = table_name.split('.')[0].upper()
                    if lib_prefix in p_data['libname_dict']:
                        artifact_path = clean_artifact(p_data['libname_dict'][lib_prefix])
                src_disp = _refine_table_in_source_type(
                    inp_obj.get('source', ''), table_name, p_data.get('libname_dict') or {}
                )
                artifacts_list.append((table_name, 'table_in', src_disp, artifact_path))
                seen_table_in.add(table_name.replace('`', '').replace('"', '').replace("'", "").strip().upper())

            def _append_supplemental_table_in(table_name, source_label):
                """True quando o token ficou REPRESENTADO como table_in (novo ou já visto);
                False só quando foi RECUSADO — aí cabe ao chamador decidir o fallback, em
                vez de o input sumir em silêncio."""
                tn = clean_artifact(table_name)
                if _exclude_from_table_in_metadata_token(tn):
                    return False
                key = tn.replace('`', '').replace('"', '').replace("'", "").strip().upper()
                if key in seen_table_in:
                    return True      # já representado por outra via (dedup desejada)
                seen_table_in.add(key)
                artifact_path = ""
                if '.' in tn:
                    lib_prefix = tn.split('.')[0].upper()
                    if lib_prefix in p_data.get('libname_dict', {}):
                        artifact_path = clean_artifact(p_data['libname_dict'][lib_prefix])
                src_disp = _refine_table_in_source_type(
                    source_label, tn, p_data.get('libname_dict') or {}
                )
                artifacts_list.append((tn, 'table_in', src_disp, artifact_path))
                return True

            for item in p_data.get('dynamic_refs', []):
                _append_supplemental_table_in(item, 'SAS/Local (macro no membro)')

            for item in p_data.get('sas_reads_full', []):
                _append_supplemental_table_in(item, 'SAS/Local (scan completo .txt)')

            for item in p_data.get('eg_xml_only', []):
                _append_supplemental_table_in(item, 'SAS/Local (EG project.xml — não no scan do fluxo)')

            for item in p_data.get('comment_only_reads', []):
                _append_supplemental_table_in(item, 'SAS/Local (só em comentário — não executado)')

            # Flush dos .sas7bdat sob LIBNAME (ver o laço de files_read). Roda por ÚLTIMO entre
            # os table_in para maximizar a dedup via seen_table_in e para que `prefer` já
            # enxergue todos os librefs usados pelo projeto.
            _prefer_libs = {k.split('.', 1)[0] for k in seen_table_in if '.' in k}
            for _p in sas7bdat_sob_libname:
                _tn = _sas7bdat_as_libname_table(
                    _p, p_data.get('libname_dict') or {}, _prefer_libs)
                # Fallback OBRIGATÓRIO: antes deste desvio, todo .sas7bdat entrava como
                # file_in. Ao passar a preferir table_in, a resolução que falha (ou o token
                # recusado) fazia o input DESAPARECER dos relatórios 01-06 sem aviso.
                # `_exclude_from_table_in_metadata_token` casa a extensão no FIM do nome, e
                # `LIB.MEMBRO` tem exatamente essa forma: um membro chamado CSV, TXT, ZIP,
                # SAS, XML… (`/dados/reneg/CSV.sas7bdat` -> `RENEG.CSV`) era recusado.
                # Perder o input é pior do que classificá-lo como arquivo.
                if not (_tn and _append_supplemental_table_in(_tn, _SAS7BDAT_SRC_LABEL)):
                    artifacts_list.append((get_basename(_p), 'file_in', '', _p))

            for lib in p_data.get('imported_libnames', []):
                lib_path_raw = p_data['libname_dict'].get(lib, lib)
                clean_path = clean_artifact(lib_path_raw)
                artifact_path = clean_path if clean_path != lib else ""
                artifacts_list.append((lib, 'libname_in', '', artifact_path))

            seen_table_out = set()
            for item in p_data.get('outputs', []):
                table_name = clean_artifact(item)
                artifact_path = ""
                if '.' in table_name:
                    lib_prefix = table_name.split('.')[0].upper()
                    if lib_prefix in p_data['libname_dict']:
                        artifact_path = clean_artifact(p_data['libname_dict'][lib_prefix])
                artifacts_list.append((table_name, 'table_out', '', artifact_path))
                k = table_name.replace('`', '').replace('"', '').replace("'", "").strip().upper()
                if k:
                    seen_table_out.add(k)

            co_src = 'SAS/Local (só em comentário — não executado)'
            for item in p_data.get('comment_only_writes', []):
                table_name = clean_artifact(item)
                k = table_name.replace('`', '').replace('"', '').replace("'", "").strip().upper()
                if not k or k in seen_table_out:
                    continue
                seen_table_out.add(k)
                artifact_path = ""
                if '.' in table_name:
                    lib_prefix = table_name.split('.')[0].upper()
                    if lib_prefix in p_data.get('libname_dict', {}):
                        artifact_path = clean_artifact(p_data['libname_dict'][lib_prefix])
                artifacts_list.append((table_name, 'table_out', co_src, artifact_path))

            for item in p_data.get('exports', []):
                clean_item = clean_artifact(item)
                artifacts_list.append((get_basename(clean_item), 'file_out', '', clean_item))

            for lib in p_data.get('exported_libnames', []):
                lib_path_raw = p_data['libname_dict'].get(lib, lib)
                clean_path = clean_artifact(lib_path_raw)
                artifact_path = clean_path if clean_path != lib else ""
                artifacts_list.append((lib, 'libname_out', '', artifact_path))

            scope_norm = (prontidao_scope or 'all').strip().lower()
            r6_mode = (report6_artifact_mode or 'executable').strip().lower()
            after_scope = _filter_report6_by_scope(artifacts_list, scope_norm)
            filtered_artifacts = _filter_report6_diagnostic_rows(after_scope, r6_mode)

            if not filtered_artifacts:
                if scope_norm == 'all':
                    writer.writerow(
                        [proj, file_sas_col, p_data.get('business_area', ''), '', '', '', '', '', '', '', '', '', '', ext, created_at, target_arch_col]
                    )
                continue

            for art, cat, src, pth in filtered_artifacts:

                status = "Não Encontrado"
                cham_row = {}
                src_final = src

                # Aplica as regras de Governança (Decision Tree)
                if cat in ('table_in', 'table_out'):
                    art_clean = art.replace('`', '').replace('"', '').replace("'", "").strip().upper()
                    is_bq = ("BIGQUERY" in src.upper() or "GCP" in src.upper())

                    if is_bq:
                        # 1. É BQ no EGP -> Ignora o resto e mantém a fonte!
                        status = "Nativa BigQuery (Identificada no EGP)"
                    else:
                        # 2. NÃO é BQ no EGP -> Vamos consultar o Chameleon
                        match_chameleon = False

                        for row in chameleon_records:
                            if is_strict_match(art_clean, row['NmTabelaDestino']):
                                status = "[Modernizada] Tabela utilizada presente no BigQuery"
                                cham_row = row
                                match_chameleon = True
                                break
                            elif is_strict_match(art_clean, row['NmTabelaOrigem']):
                                status = "[Identificado ajuste] Existe uma modernizada no BigQuery correspondente a esta tabela"
                                cham_row = row
                                match_chameleon = True
                                break

                        if not match_chameleon:
                            # 2b. Nao casou direto -> ponte via RepMap: traduz alias/destino IQ
                            #     (ex.: DBA) para a base de origem ASE (ex.: DBCRED) e re-sonda o Chameleon.
                            for _src_key in _repmap_source_keys(art_clean):
                                for row in chameleon_records:
                                    if is_strict_match(_src_key, row['NmTabelaDestino']) or is_strict_match(_src_key, row['NmTabelaOrigem']):
                                        status = "[Modernizada via replica] Tabela presente no BigQuery (origem resolvida via RepMap)"
                                        cham_row = row
                                        match_chameleon = True
                                        break
                                if match_chameleon:
                                    break

                        if match_chameleon:
                            # 2.1 Achou no Chameleon -> a fonte passa a refletir a ORIGEM REAL
                            #     do datalake (DsOrigem: SYBASE_ASE, SQL_SERVER, ...), em vez do
                            #     antigo marcador "Avaliar". O sinal "modernizada/decidir" já vive
                            #     em `status` ([Modernizada...]) e alimenta modernizada_auto no
                            #     publish; a coluna source_type passa a informar de onde a tabela
                            #     é importada — usado pelo app p/ classificar a origem.
                            _ds_origem = (cham_row.get('DsOrigem') or '').strip()
                            src_final = _ds_origem.upper() if _ds_origem else src_final
                        else:
                            # 3. Não é BQ e não achou no Chameleon -> Consulta o Inventário Transacional
                            if art_clean in inventario_map:
                                src_final = inventario_map[
                                    art_clean]  # Substitui pelo SGBD do Inventário (ex: SYBASE_ASE)
                                status = "Inventário Transacional (Match Exato 100%)"

                # Override autoritativo de modernizacao (FALLBACK): so quando chameleon/RepMap/
                # inventario NAO marcaram modernizado. Fecha o gap de remap de schema
                # (dba/public -> trusted_*) ausente no Chameleon (keyed pela origem resolvida).
                if cat in ('table_in', 'table_out') and 'MODERNIZADA' not in status.upper() and 'BIGQUERY' not in status.upper():
                    _ov_dest = modern_override.get(art_clean)
                    if _ov_dest:
                        status = "[Modernizada] Tabela presente no BigQuery (lista autoritativa de inputs modernizados)"
                        cham_row = {
                            'NmTabelaOrigem': cham_row.get('NmTabelaOrigem', ''),
                            'NmTabelaDestino': _ov_dest,
                            'NmDataSet': cham_row.get('NmDataSet', ''),
                            'NmProjeto': cham_row.get('NmProjeto', ''),
                            'DsOrigem': cham_row.get('DsOrigem', ''),
                        }

                src_final = _apply_connection_source_type(
                    cat, src_final, art, _connection_libs_frozenset(p_data)
                )

                writer.writerow([
                    proj,
                    file_sas_col,
                    p_data.get('business_area', ''),
                    art,
                    pth,
                    cat,
                    src_final,
                    status,
                    cham_row.get('NmTabelaOrigem', ''),
                    cham_row.get('NmTabelaDestino', ''),
                    cham_row.get('NmDataSet', ''),
                    cham_row.get('NmProjeto', ''),
                    cham_row.get('DsOrigem', ''),
                    ext,
                    created_at,
                    target_arch_col,
                ])

    print("\n✅ Concluído com Sucesso!")
    print(f"  -> {OUTPUT_REPORT_1} (Backlog para Time de Ingestão)")
    print(f"  -> {OUTPUT_REPORT_2} (Entregáveis para Validação)")
    print(f"  -> {OUTPUT_REPORT_3} (De-Para de Dependências)")
    print(f"  -> {OUTPUT_REPORT_4} (Cronograma para o Agente IA)")
    print(f"  -> {OUTPUT_REPORT_5} (Blueprint de Migração Atualizado)")
    scope_note = ""
    sn = (prontidao_scope or 'all').strip().lower()
    if sn == 'in':
        scope_note = " [apenas entradas: file_in, table_in, script_in — libname_in é contexto]"
    elif sn == 'out':
        scope_note = " [apenas saídas: table_out, libname_out, file_out]"
    else:
        scope_note = ""
    r6m = (report6_artifact_mode or 'executable').strip().lower()
    diag_note = "" if r6m == 'full' else " [artefatos: modo executable — sem suplementos de diagnóstico]"
    print(f"  -> {OUTPUT_REPORT_6} (Planilha Mestra: Artefatos + Paths + SGBD + Chameleon){scope_note}{diag_note}")

    # Passada ADITIVA de arestas por arquivo (PLANO_JUNCAO_ARQUIVOS_MACRO.md):
    # não altera nenhum relatório 01–07; só escreve o 08. Falha aqui não pode
    # derrubar o inventário principal.
    try:
        n8, d8 = gerar_arestas_arquivo(corpus)
        print(f"  -> {OUTPUT_REPORT_8} (Arestas por ARQUIVO c/ esqueleto de macro: "
              f"{n8} pares; {d8} descartados por fan-out degenerado) [NÃO entra no grafo/fecho]")
    except Exception as e:
        print(f"  [AVISO] {OUTPUT_REPORT_8} não gerado: {e}")


OUTPUT_REPORT_8 = r'08_arestas_arquivo.csv'


def gerar_arestas_arquivo(corpus):
    """Arestas EGP→EGP via arquivo exportado/importado, casadas por esqueleto de
    macro (macro_file_refs). Níveis: 1 = dir resolvido igual + esqueleto confiável;
    2 = esqueleto confiável, dir irresolvível em ≥1 lado; 3 = esqueleto genérico
    (guarda anti-REGRAS). Dirs resolvidos e CONFLITANTES nunca casam (cópias em
    pastas distintas são arquivos distintos). Fan-out >10 rebaixa p/ nível 3;
    >200 descarta o esqueleto (degenerado). 100% aditivo: só escreve o 08.
    `corpus` = egp_decisoes.aplica_ao_corpus (já sem os excluídos)."""
    from macro_file_refs import file_refs_de_arquivo

    outs_por_skel, ins_por_skel = defaultdict(list), defaultdict(list)
    for arq in corpus:
        path, projeto = arq.caminho, arq.stem
        try:
            refs = file_refs_de_arquivo(path)
        except Exception:
            continue
        for r in refs:
            alvo = outs_por_skel if r.lado == 'out' else ins_por_skel
            alvo[r.nome_skeleton].append((projeto, r))

    FANOUT_NIVEL3, FANOUT_DESCARTE = 10, 200
    linhas, descartados = [], 0
    for skel, outs in outs_por_skel.items():
        ins = ins_por_skel.get(skel)
        if not ins:
            continue
        candidatos, vistos = [], set()
        for proj_o, ro in outs:
            for proj_i, ri in ins:
                # dirs resolvidos dos dois lados e diferentes = arquivos distintos
                if ro.dir_resolvido and ri.dir_resolvido and ro.dir_resolvido != ri.dir_resolvido:
                    continue
                chave = (proj_o, proj_i, ro.dir_resolvido or ri.dir_resolvido)
                if chave in vistos:
                    continue
                vistos.add(chave)
                candidatos.append((proj_o, proj_i, ro, ri))
        if not candidatos:
            continue
        # fan-out é guarda contra colisão de NOME: só conta/pune pares sem
        # confirmação de diretório — par nível 1 (dir igual nos 2 lados) já tem
        # evidência forte e fica isento (hub legítimo tipo desconto_cobranca).
        sem_dir = [c for c in candidatos
                   if not (c[2].dir_resolvido and c[3].dir_resolvido)]
        if len(sem_dir) > FANOUT_DESCARTE:
            descartados += len(sem_dir)
            candidatos = [c for c in candidatos if c not in sem_dir]
        rebaixa = len(sem_dir) > FANOUT_NIVEL3
        for proj_o, proj_i, ro, ri in candidatos:
            confiavel = ro.confiavel and ri.confiavel
            nivel1 = bool(ro.dir_resolvido and ri.dir_resolvido)
            if not confiavel or (rebaixa and not nivel1):
                nivel = 3
            elif nivel1:
                nivel = 1
            else:
                nivel = 2
            flags = [f for f, cond in (
                ('releitura', proj_o == proj_i),
                ('generico', not confiavel),
                ('alto_fanout', rebaixa and not nivel1),
            ) if cond]
            linhas.append([
                proj_o, proj_i, skel,
                ro.dir_resolvido if nivel == 1 else '',
                nivel, ';'.join(flags),
                ro.path_bruto, ri.path_bruto,
            ])

    linhas.sort(key=lambda x: (x[4], x[2], x[0], x[1]))
    with open(OUTPUT_REPORT_8, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Projeto_Produtor', 'Projeto_Consumidor', 'Via_Arquivo_Skeleton',
                    'Dir_Resolvido', 'Nivel_Confianca', 'Flags',
                    'Arquivo_Produtor_Bruto', 'Arquivo_Consumidor_Bruto'])
        w.writerows(linhas)
    return len(linhas), descartados


if __name__ == "__main__":
    # Para gerar apenas entradas: --prontidao-scope in
    # Para gerar apenas saidas: --prontidao-scope out
    # Para gerar entradas e saidas: --prontidao-scope al ou nao passar paràmetros
    parser = argparse.ArgumentParser(
        description='Orquestrador de inventário SAS/EGP → CSVs 01–06 (07 reservado; entrada: .txt de egps_extractor.py).',
    )
    parser.add_argument(
        '--prontidao-scope',
        choices=('all', 'in', 'out'),
        default='all',
        help=(
            'Relatório 06 (06_prontidao_tabela.csv): all = todas as linhas (comportamento padrão); '
            'in = só categorias de entrada; out = só categorias de saída. '
            'Relatórios 01–05 são sempre gerados por completo.'
        ),
    )
    parser.add_argument(
        '--report6-artifact-mode',
        choices=('executable', 'full'),
        default='executable',
        dest='report6_artifact_mode',
        help=(
            "Relatório 06: 'executable' (default) exclui table_in/table_out suplementares vindos de "
            "scan completo do .txt, EG project.xml stale ou só comentário — alinha com o fluxo EG. "
            "'full' restaura o agregador completo (diagnóstico / legado)."
        ),
    )
    args = parser.parse_args()
    main(
        prontidao_scope=args.prontidao_scope,
        report6_artifact_mode=args.report6_artifact_mode,
    )