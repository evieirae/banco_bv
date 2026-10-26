#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Passo PUBLISH — sobe os reports saneados do pipeline para tabelas Delta no
Databricks, que servem de backend do app "Painel de Modernização SAS".

Origem (local):  06_prontidao_tabela.csv (inputs+outputs) · 03_matriz_dependencias.csv
                 (linhagem projeto→projeto) · 04_ondas_de_migracao.csv (ondas) ·
                 docs/analises/indi_231_vs_extracao_06.csv (flag de escopo Indicium) ·
                 text_egps/ (libnames, NON_CREATOR, LOC) e src/egps_decisoes.csv
                 (decisões por EGP, ver egp_decisoes.py).
Destino:         <catalog>.<schema>  (default bv_dev_db.monitoramento_sas)

Tabelas:
  sas_inputs_monitor   grão = input distinto (chave canônica). Colunas do pipeline
                       são atualizadas; colunas HUMANAS (status_humano, responsavel,
                       observacao, updated_*) são PRESERVADAS no MERGE. Linhas que
                       somem do pipeline viram orfao=true (aba de reconciliação).
  sas_lineage_edges    projeto_alvo → depende_do (+ via_tabelas) — full replace.
  sas_lineage_nodes    projeto: area, onda, n_inputs, n_outputs, escopo — full replace.
  sas_pipeline_metrics append: snapshot de métricas por refresh (histórico de progresso).

Dedup .sas: o extrator inventaria o MESMO arquivo .sas em dois papéis — `file_in`
(citado como caminho) e `script_in` (%INCLUDE-ado). Como a chave é "categoria::ARTEFATO",
isso duplicava o input no monitor (uma linha `arquivo` + uma `script`) e inflava
qtd_projetos/prontidão. `eff_categoria()` normaliza todo .sas para `script` (é código,
não dado a ingerir), unificando os dois numa única chave. Pode reaparecer se o extrator
mudar a forma de classificar — ver eff_categoria().

Dedup .sas7bdat: idem para TABELAS SAS. O mesmo dataset aparece como `table_in`
'lib.membro' (lido via libname) E como `file_in` '<membro>.sas7bdat' (o arquivo físico do
membro). Como artefato E categoria diferem ('tabela' vs 'arquivo'), viravam DUAS chaves no
monitor (dupla-conta a tabela). `_sas7bdat_dedup_members()` (pré-passe por projeto) marca
os membros lidos como lib.membro de forma NAO-AMBIGUA (1 libname, <=1 path físico) e o
build DESCARTA o file_in '<membro>.sas7bdat' do MESMO projeto — colapsa no lib.membro (a
forma rica: libname->path->origem SAS/Local). Arquivo .sas7bdat SEM par tabela, ou membro
AMBIGUO (homônimo no mesmo projeto), é PRESERVADO — nunca derruba input legítimo.

Conexão: databricks-sdk (mesmas envs do converter: DATABRICKS_HOST/TOKEN +
DATABRICKS_DEFAULT_WAREHOUSE_ID). Rode com o .env do converter carregado:
  cd converter && set -a && . ./.env && set +a && cd .. \
    && python egps_analysis/publish_to_databricks.py --apply

Sem --apply: dry-run (constrói tudo, imprime esquemas/contagens/amostra, NÃO conecta).
"""
import argparse
import html
import csv
import os
import re
import sys

import egp_decisoes         # excluir duplicata / renomear EGP (src/egps_decisoes.csv)
import identidade_guard     # guarda do ticket 25 (pura; ver docstring)
import identidade_reaplica  # reaplicacao do ticket 25 (semantica lida de prod)
import datetime
import collections
import uuid

import libname_resolver

# Regra de FAMÍLIA DE SAFRAS: importada de app/backend/familias.py em vez de duplicada aqui.
# O plano (.scratch/familias-safra, ticket 06) previa uma segunda cópia com nota de
# sincronia; importar é melhor e é possível porque o módulo é puro (só json/os/re) e mora no
# mesmo repo — uma regra, um lugar. O publish roda do repo (o app sincronizado para o
# Databricks não depende deste arquivo, então a seta é só nesta direção).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "backend"))
import familias  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__))
R06 = os.path.join(BASE, "06_prontidao_tabela.csv")
R03 = os.path.join(BASE, "03_matriz_dependencias.csv")
R04 = os.path.join(BASE, "04_ondas_de_migracao.csv")
INDI = os.path.join(BASE, "docs", "analises", "indi_231_vs_extracao_06.csv")
TXT_DIR = os.path.join(BASE, "text_egps")
# EGPs "casca" (spec §3.6, regras 22-27): antecessores absorvidos por um EGP Atualizado
# unificador (N:1) que NUNCA terão inventário próprio — não serão extraídos nem analisados
# como EGP individual, só precisam de 1 linha no funil (capaz de chegar a "Migrado") pra
# contabilizar a migração deles junto com a do unificador. Cadastro VERSIONADO, não runtime:
# sas_lineage_nodes é full-replace a cada publish, então um insert feito só pelo app sumiria
# na publicação seguinte — por isso a casca nasce aqui, junto com os nós reais.
EGPS_CASCA = os.path.join(BASE, "src", "egps_casca.csv")
# Decisões por EGP (egp_decisoes.py): o orquestrador já gera os CSVs com elas; aqui valem para
# o que o publish lê direto do corpus (libmap, NON_CREATOR, LOC) e do indi_231, cortam do
# escopo os outputs marcados, e o build() recusa CSV gerado sem elas.
DECISOES = os.path.join(BASE, "src", "egps_decisoes.csv")

# Schema de PRODUÇÃO. Escrever aqui com --apply exige --prod-confirm explícito (guarda
# anti-acidente; espelha a guarda do local_app.sh). O default de --schema é o sandbox _dev.
PROD_SCHEMA = "monitoramento_sas"

# libname_in NAO e input (decisao 2026-06-12): o libref sozinho nao e dado concreto —
# as tabelas importadas da libname ja entram individualmente como table_in.
IN_CATS = {"table_in": "tabela", "file_in": "arquivo", "script_in": "script"}
MODERN_MARKERS = ("BIGQUERY", "[MODERNIZADA]", "[MODERNIZADA VIA REPLICA]", "[IDENTIFICADO AJUSTE]")
# Override de área: projeto cuja área no extrator diverge da área "dona" na lista Indicium.
AREA_OVERRIDE = {"Banco Relacional__Processo de bonificação - taxas_v35 (2)": "Cartões"}
# rótulos da MESMA área que aparecem variados nas fontes (06 usa 'Cobranças'; DOR1 usa
# 'Cobrança Varejo') -> canonizados para UM nome único em todas as tabelas/abas.
AREA_CANON = {"Cobranças": "Cobrança", "Cobrança Varejo": "Cobrança"}
# Área preferida na desambiguação de area_principal (canônico de "Cobranças"/"Cobrança Varejo").
AREA_PREF = "Cobrança"

# universo do resumo = inputs do monitor + libname_in (re-incluído só p/ a aba Resumo)
RES_CATS = {"table_in": "tabela", "file_in": "arquivo", "script_in": "script", "libname_in": "lib"}
_TRANS_SRC = ("POSTGRES", "SYBASE", "SYBASEIQ", "IQ", "SQLSVR", "DBCON", "DBCONN", "ASE",
              "SQL_SERVER", "SQLSERVER", "MYSQL", "ORACLE")  # SGBDs vindos de DsOrigem (Chameleon)


def origem_bucket(source_types, categoria):
    """Classifica um input distinto num bucket de origem (prioridade)."""
    sts = {s.upper() for s in source_types if s}
    if any("BIGQUERY" in s for s in sts):
        return "BigQuery"
    if categoria == "lib":
        return "Libname_in"
    if categoria == "arquivo":
        return "Arquivo"
    if any(any(t in s for t in _TRANS_SRC) for s in sts):
        return "Transacional"
    return "SAS/Local"


def origem_input(source_types, categoria, produced):
    """Origem de um input do grão monitor (sas_inputs_monitor): 4-way para tabelas
    + Arquivo/Script para as demais categorias. Distinta de origem_bucket() (grão
    Resumo, com libname). `produced`=True quando o artefato é table_out de algum
    EGP do corpus → dependência intra-pipeline; senão SAS/Local sem produtor
    conhecido ("externo"). Prioridade: BigQuery > Arquivo/Script (categoria) >
    Transacional > SAS/Local (split por produced)."""
    sts = {s.upper() for s in source_types if s}
    if any("BIGQUERY" in s for s in sts):
        return "BigQuery"
    if categoria == "arquivo":
        return "Arquivo"
    if categoria == "script":
        return "Script"
    if any(any(t in s for t in _TRANS_SRC) for s in sts):
        return "Transacional"
    return "SAS/Local (dependência)" if produced else "SAS/Local (externo)"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def n(v):
    return str(v).strip() if v is not None else ""


def canon_area(v):
    """Nome canônico da área: normaliza e aplica AREA_CANON (une variantes da mesma área)."""
    a = n(v)
    return AREA_CANON.get(a, a)


def escolhe_area_principal(dor1_votes):
    """Área única do input p/ o funil por área do Resumo (grão = input distinto).

    `dor1_votes`: Counter área_canônica -> nº de EGPs (da lista DOR1) que consomem o input,
    i.e. as áreas que TÊM EGP associado a ESTE input. Regra (2026-07):
      1. sem área qualificada (nenhum EGP)      -> "(sem área)"  [ex.: inputs do Jurídico, 0 EGPs]
      2. AREA_PREF (Cobrança) entre as qualif.  -> AREA_PREF
      3. senão maior contagem de EGPs           -> essa área
      4. empate                                 -> ordem alfabética
    NÃO usa a área mais frequente do input (area_count): sem EGP, o input não é de área alguma.
    """
    if not dor1_votes:
        return "(sem área)"
    if AREA_PREF in dor1_votes:
        return AREA_PREF
    top = max(dor1_votes.values())
    return sorted(a for a, c in dor1_votes.items() if c == top)[0]


# ---- area_principal lastreada no FRONTIER (espelha backend/main.py) ----
# escolhe_area_principal() acima vota pela ponte DOR1, que só enxerga EGPs da lista
# Indicium: input consumido APENAS por EGP-dependência não recebe voto e fica "(sem área)"
# — virava linha órfã no funil por área "+ dependências" do Resumo (2026-08-12: 105 inputs
# não modernizados no dev, 143 em prod). O backend já corrigia isso em
# _recompute_area_principal(), mas SÓ quando alguém editava escopo no app; publish por CLI
# deixava a coluna defasada. As funções abaixo reproduzem o frontier (escopo ∪ dependências
# transitivas) para o publish fechar a conta sozinho, com a MESMA regra de voto.
# MANTENHA EM SINCRONIA com backend/main.py::_recompute_area_principal / _frontier_via.


def _fam_metrics(rows):
    """Métricas na unidade FAMÍLIA DE SAFRAS (ADR 0002), a partir das linhas de input do build.

    Família só é resolvida quando TODAS as suas safras estão — qualquer safra pendente
    segura a família (mesma régua do app). Regra importada de app/backend/familias.py: uma
    regra, um lugar."""
    if not rows:
        return {"inputs_familias": 0, "inputs_pendentes_familia": 0}
    chave = familias.resolve(rows, strict=False)["chave"]

    def _fk(r):
        return (r["categoria"], chave[(r["categoria"], (r["artifact"] or "").strip().upper())])

    return {"inputs_familias": len({_fk(r) for r in rows}),
            "inputs_pendentes_familia": len({_fk(r) for r in rows
                                             if r["modernizada_auto"] == "A ingerir"})}


def _eff_status_sql(sh="status_humano", auto="modernizada_auto"):
    """Status efetivo do input, em SQL (cópia fiel de main.py::_eff_status)."""
    norm = (f"CASE {sh} WHEN 'Disponível' THEN 'Modernizado' WHEN 'Sanitizada' THEN 'Sanitizado' "
            f"WHEN 'Descartada' THEN 'Sanitizado' WHEN 'Descartado' THEN 'Sanitizado' "
            f"WHEN 'Em análise' THEN 'Recebido' WHEN 'A ingerir' THEN 'A receber' "
            f"WHEN 'Não recebido' THEN 'A receber' WHEN 'Priorizado' THEN 'Recebido' "
            f"ELSE {sh} END")
    auto_def = (f"CASE {auto} WHEN 'Disponível' THEN 'Modernizado' "
                f"WHEN 'A ingerir' THEN 'A receber' ELSE 'Recebido' END")
    return f"coalesce(nullif({norm}, ''), {auto_def})"


def _modern_sql():
    return f"({_eff_status_sql()} IN ('Modernizado','Sanitizado'))"


def _transitive_upstream(base_set, dep_of, no_expand=frozenset()):
    """Fecho transitivo a montante (cópia fiel de main.py::_transitive_upstream): quem está
    em `no_expand` (despriorizado e contabilizado) entra no frontier mas não expande."""
    level = {p: 0 for p in base_set}
    frontier = set(base_set) - set(no_expand)
    hop = 0
    while frontier:
        hop += 1
        nxt = set()
        for p in frontier:
            for dep in dep_of.get(p, ()):
                if dep not in level:
                    level[dep] = hop
                    if dep not in no_expand:
                        nxt.add(dep)
        frontier = nxt
    return set(level)


def frontier_egps(edges_rows, base, no_expand, resolvidas, mantidas=frozenset()):
    """Frontier = escopo ∪ dependências transitivas. `edges_rows` já saem de build() podadas
    pelo produtor canônico; aqui cai a via já RESOLVIDA (input modernizado/sanitizado) —
    aresta sem via viva não puxa dependência (espelha _filter_vias_resolvidas_res).

    `mantidas`: pares (projeto_alvo, ARTIFACT upper) em que o consumidor declarou que a
    dependência segue viva apesar da via resolvida (tabela sas_egp_dep_mantida, botão
    "ainda é dependência"). ESPELHA main.py — se só um dos dois lados souber da exceção, o
    publish derruba do escopo exatamente os EGPs que alguém marcou para manter."""
    dep_of = {}
    for e in edges_rows:
        vias = [t.strip() for t in (e.get("via_tabelas") or "").split(" | ") if t.strip()]
        alvo = e.get("projeto_alvo")
        if vias and all(t.upper() in resolvidas and (alvo, t.upper()) not in mantidas
                        for t in vias):
            continue
        a, d = e["projeto_alvo"], e["depende_do"]
        if a and d and a != d:
            dep_of.setdefault(a, set()).add(d)
    return _transitive_upstream(base, dep_of, no_expand)


def recompute_area_principal(run, read_rows, data, t_nd, t_in, t_res, t_pipe):
    """Reescreve {t_res}.area_principal pela área do EGP consumidor no FRONTIER, com o mesmo
    voto de escolhe_area_principal (Cobrança > contagem > alfabética; sem voto -> "(sem área)").

    Roda DEPOIS do recompute de escopo_indi (o frontier parte do escopo VIGENTE, já
    re-derivado do sas_escopo). Grafo/áreas/consumo vêm do `data` que acabou de ser gravado
    (edges/nodes/egp_inputs são full replace no mesmo publish); do banco vêm só escopo,
    despriorizados e o status humano dos inputs (que o MERGE preserva).
    Reset + UPDATE por área em blocos de 400 — dentro de MODIFY, como o resto do recompute."""
    base = {r[0] for r in read_rows(f"SELECT projeto FROM {t_nd} WHERE escopo_indi = true") if r[0]}
    try:
        no_expand = {r[0] for r in read_rows(
            f"SELECT projeto FROM {t_pipe} WHERE status_migracao = 'Despriorizado e Contabilizado'")
            if r[0]}
    except RuntimeError:  # tabela ainda não existe no 1º publish
        no_expand = set()
    resolvidas = {str(r[0]).strip().upper() for r in read_rows(
        f"SELECT artifact FROM {t_in} WHERE categoria = 'tabela' AND ({_modern_sql()})")
        if r[0] and str(r[0]).strip()}
    try:
        t_depm = t_in.rsplit(".", 1)[0] + ".sas_egp_dep_mantida"
        mantidas = {(r[0], str(r[1]).strip().upper()) for r in read_rows(
            f"SELECT d.projeto, i.artifact FROM {t_depm} d "
            f"JOIN {t_in} i ON i.chave_canonica = d.chave_canonica")
            if r[0] and r[1] and str(r[1]).strip()}
    except RuntimeError:  # tabela ainda não existe (criada sob demanda pelo app)
        mantidas = set()
    frontier = frontier_egps(data["edges"], base, no_expand, resolvidas, mantidas)
    proj_area = {nd["projeto"]: nd["area"] for nd in data["nodes"]}
    votos = {}
    for r in data["egp_inputs"]:
        if r["projeto"] not in frontier:
            continue
        a = proj_area.get(r["projeto"])
        if a:
            votos.setdefault(r["chave_canonica"], collections.Counter())[a] += 1
    por_area = collections.defaultdict(list)
    for ch, v in votos.items():
        por_area[escolhe_area_principal(v)].append(ch)
    run(f"UPDATE {t_res} SET area_principal = '(sem área)'")
    n_ch = 0
    for area, chaves in sorted(por_area.items()):
        if area == "(sem área)":
            continue
        for i in range(0, len(chaves), 400):
            inlist = ", ".join(sql_lit(c) for c in chaves[i:i + 400])
            run(f"UPDATE {t_res} SET area_principal = {sql_lit(area)} "
                f"WHERE chave_canonica IN ({inlist})")
        n_ch += len(chaves)
    print(f"  area_principal recomputada no frontier: {len(base)} EGPs de escopo "
          f"+ {len(frontier) - len(base)} dependências -> {n_ch} inputs com área "
          f"({', '.join(f'{a}={len(c)}' for a, c in sorted(por_area.items()))})")


# Referência de macro NÃO resolvida no nome do artefato. `is_noise_table()` já descarta o
# equivalente em TABELAS (guard `'&' in a`), mas nunca rodou para `file_in` — daí 181
# pseudo-inputs `arquivo` em prod (`&arquivo..sas7bdat`, `ESTOQUE_&DSRefModel.sas7bdat`,
# `BA_ACORDO_&SAFRA..csv`), um deles vivo, no escopo e lido por 5 EGPs.
# `&amp;` porque egps_extractor.sas_metadata_path_display() re-escapa `&` de propósito, para
# alinhar a linha de metadados ao modo como SAS/EG renderiza caminhos — a forma escapada é a
# que chega no relatório 06, então o guard cobre as duas.
# EXCEÇÃO: abreviação com `&` LITERAL entre duas letras isoladas (P&L, P&C, A&B) — o
# docstring de egps_extractor.sas_metadata_path_display() já avisava disso, e o corpus tem
# um caso REAL com status humano: 'P&L_Cartoes_Real.v2.xlsx' (Profit & Loss, marcado
# Concluído). Sem a exceção o guard o descartaria. Exige as duas letras delimitadas por
# separador/borda, então 'tboriginacao&a0.' (macro de verdade) não é isentado.
_MACRO_ARTIFACT_RE = re.compile(r'&(?:amp;)?[A-Za-z_][A-Za-z0-9_]+')
_AMP_LITERAL_RE = re.compile(r'(?:^|[_\-/. ])[A-Za-z]&(?:amp;)?[A-Za-z](?=[_\-/. ]|$)')


def is_macro_artifact(art):
    """Artefato cujo nome carrega macro não expandida — padrão, não arquivo real."""
    s = art or ""
    if _AMP_LITERAL_RE.search(s):
        s = _AMP_LITERAL_RE.sub(" ", s)      # neutraliza a abreviação e reavalia o resto
    return bool(_MACRO_ARTIFACT_RE.search(s))


def is_noise_table(art):
    a = art.upper()
    if a.startswith(("WORK.", "DICTIONARY.", "SASHELP.", "SASUSER.")):
        return True
    if "&" in a or "{" in a or "}" in a:
        return True
    return a.endswith((".SAS7", ".SAS7BDAT"))


def path_de_arquivo(raw):
    """Path físico de input `arquivo`/`script`, como vem da coluna `path` do relatório 06.

    Essas categorias não precisam da resolução de libref que a TABELA precisa: o artifact
    é o próprio basename do path (verificado em 17/09/2026: 7.222 de 7.222 linhas
    file_in/script_in do 06). Desescapa entidade HTML que o extrator deixa passar
    (`&amp;` -> `&`). Caminho com macro-var não resolvida (`/&Modo_Exec./...`) é publicado
    como está: dizer "depende de macro" é informação, não erro — quem decide ingestão
    precisa ver que o caminho não é literal.
    """
    return html.unescape(n(raw)) or None


def canon(art):
    return art.strip().upper()


def is_work_implicit(art):
    """`data X;` sem libname nem path = WORK implícita (temporária por sessão) — não é
    output monitorável. Filtra SÓ o universo da aba Outputs (outputs/egp_outputs);
    produced_tables/proj_out (origem dos inputs) ficam intactos de propósito."""
    return "." not in art and "/" not in art and "\\" not in art


def is_sas_code(art):
    return canon(art).endswith(".SAS")


def build_project_libmap(corpus):
    """Devolve libs_for_project(projeto) -> {LIBREF_UPPER: set(paths físicos)}.

    Reusa libname_resolver.parse_libmap_from_txt sobre cada text_egps/<stem>.txt e
    aplica o MESMO fallback de build_stem_lib (docs/analises/aprofunda_saslocal_homonimos):
    além do próprio stem, agrega libnames dos stems IRMÃOS no folder-project
    (mesmo prefixo antes do último '__', ex.: 'area__proj__*') e dos stems com o mesmo
    tail (parte após o 1º '__', i.e. o stem sem o prefixo de área). Necessário porque
    o LIBNAME costuma estar definido num EGP irmão do mesmo projeto-pasta, não no .txt
    do consumidor (cobertura medida: ~63% dos stems têm libname de disco próprio).

    `corpus` = egp_decisoes.aplica_ao_corpus: sem os excluídos e com o stem já renomeado
    (sem isso o v1 do CPF_Contrato, publicado como `__v2`, leria os libnames do `__v2`
    pequeno descartado)."""
    stem_lib = {}
    for arq in corpus:
        stem_lib[arq.stem] = libname_resolver.parse_libmap_from_txt(arq.caminho)
    children = collections.defaultdict(list)   # folder-project prefix -> [stems]
    tail_index = collections.defaultdict(list)  # stem-sem-área (tail) -> [stems]
    for s in stem_lib:
        if "__" in s:
            children[s.rsplit("__", 1)[0]].append(s)
        tail_index[s.split("__", 1)[-1]].append(s)
    cache = {}

    def libs_for_project(proj):
        if proj in cache:
            return cache[proj]
        merged = collections.defaultdict(set)
        cands = {proj} if proj in stem_lib else set()
        cands.update(children.get(proj, []))
        if "__" in proj:
            cands.update(tail_index.get(proj.split("__", 1)[1], []))
        for s in cands:
            for lib, paths in stem_lib.get(s, {}).items():
                merged[lib].update(paths)
        cache[proj] = merged
        return merged

    return libs_for_project


def eff_categoria(cat, art, cat_map):
    """Categoria efetiva de um input.

    Um mesmo arquivo .sas costuma ser inventariado em DOIS papéis pelo extrator:
    `script_in` quando é %INCLUDE-ado (código puxado) e `file_in` quando é citado
    como caminho de arquivo. Como a chave_canonica é "categoria::ARTEFATO", isso
    fazia o mesmo .sas virar DUAS linhas no monitor (arquivo + script) e inflar
    qtd_projetos/prontidão. Aqui colapsamos: todo .sas é tratado como `script`
    (é código, não dado a ingerir), unificando os dois papéis numa única chave.
    """
    categoria = cat_map[cat]
    if categoria == "arquivo" and is_sas_code(art):
        return "script"
    return categoria


def _memb_sas7(art):
    """Membro (UPPER, sem diretório nem extensão) de um arquivo .sas7bdat."""
    b = (art or "").replace("\\", "/").rsplit("/", 1)[-1]
    if b.lower().endswith(".sas7bdat"):
        b = b[:-len(".sas7bdat")]
    return b.upper()



def build_non_creator_map(corpus):
    """projeto (stem do .txt, já renomeado) -> {canon(artefato)} da linha NON_CREATOR_OUTPUTS.
    Outputs que o EGP só apensa/atualiza (regra do criador). Txt sem a linha
    (corpus antigo) -> ausente do mapa: conservador, ninguém vira contribuinte.
    `corpus` = egp_decisoes.aplica_ao_corpus."""
    m = {}
    for arq in corpus:
        fp, stem = arq.caminho, arq.stem
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("NON_CREATOR_OUTPUTS"):
                        val = line.split(":", 1)[1].strip()
                        if val and val != "(none)":
                            m[stem] = {canon(x.strip()) for x in val.split(",") if x.strip()}
                        break
                    if line.startswith("END_METADATA"):
                        break
        except OSError:
            continue
    return m


def build_loc_tasks(corpus):
    """projeto (valor do header PROJECT:, a mesma chave que R06/orchestrator usa — não o
    stem do arquivo — já renomeado por egp_decisoes.aplica_ao_corpus) -> (LINES_OF_CODE
    somado, CODE_TASKS_COUNT somado). Projeto
    multi-arquivo (sas_files/<projeto>/*.sas) soma as partes, mesmo critério de fusão do
    orchestrator_inventory.main() p/ inputs/outputs. Alimenta os indicadores de "modelo
    intermediário" da aba EGPs (LOC baixo + output só consumido por outro EGP -> passo
    fino de transformação, candidato a ficar intermediário no dbt em vez de fato/dim)."""
    acc = collections.defaultdict(lambda: [0, 0])
    for arq in corpus:
        fp, proj, loc, tasks = arq.caminho, arq.projeto, 0, 0
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("END_METADATA"):
                        break
                    if line.startswith("LINES_OF_CODE:"):
                        try:
                            loc = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.startswith("CODE_TASKS_COUNT:"):
                        try:
                            tasks = int(line.split(":", 1)[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
        except OSError:
            continue
        acc[proj][0] += loc
        acc[proj][1] += tasks
    return {p: (v[0], v[1]) for p, v in acc.items()}


def _sas7bdat_dedup_members(libs_for_project):
    """Por projeto: membros lidos como lib.membro (table_in) de forma NAO-AMBIGUA — um
    unico libname e no maximo um path fisico resolvido. Um file_in '<membro>.sas7bdat' no
    MESMO projeto e o mesmo dataset fisico -> colapsa no lib.membro (senao dupla-conta a
    tabela como 'arquivo' + 'tabela'). Ambiguo (mesmo membro sob >1 libname/path no
    projeto) NAO entra: nao da p/ afirmar que e a mesma tabela (homonimo). Espelha o dedup
    de .sas (eff_categoria) e o colapso de [SHEET=] do extrator."""
    by_proj = collections.defaultdict(lambda: collections.defaultdict(set))
    with open(R06, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if n(r.get("category")) != "table_in":
                continue
            proj = n(r.get("project"))
            art = n(r.get("artifact"))
            if not proj or not art or is_noise_table(art) or "." not in art:
                continue
            lib, member = canon(art).split(".", 1)
            by_proj[proj][member.strip()].add(lib.strip())
    out = {}
    for proj, members in by_proj.items():
        safe = {m for m, libs in members.items()
                if len(libs) == 1
                and len(libs_for_project(proj).get(next(iter(libs)), ())) <= 1}
        if safe:
            out[proj] = safe
    return out


def load_indi_projects():
    projs = set()
    if not os.path.exists(INDI):
        return projs
    with open(INDI, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            st = r["status_extracao"]
            val = r["project_no_06 / observacao"]
            if st in ("exato", "variante"):
                projs.add(val.strip())
            elif st in ("provavel", "confirmado_area", "ingerido_extraido"):
                cand = val.split(" — ")[0].split(" (")[0].strip()
                if ":" in cand:
                    cand = cand.split(":")[-1].strip()
                projs.add(cand)
    return projs


def load_indi_project_areas():
    """project -> área DOR1 (rótulo do indi_231).

    Ponte para alinhar a atribuição de área da aba Resumo ao vocabulário do funil: o
    business_area do 06 (ex.: 'Cobranças') diverge do rótulo DOR1 do funil (ex.:
    'Cobrança Varejo'), e o funil soma 'Inputs não Modernizados' por nome de área.
    Mesma extração de projeto de load_indi_projects()."""
    areas = {}
    if not os.path.exists(INDI):
        return areas
    with open(INDI, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            st = r["status_extracao"]
            val = r["project_no_06 / observacao"]
            area = canon_area(r.get("area"))
            if not area:
                continue
            if st in ("exato", "variante"):
                areas[val.strip()] = area
            elif st in ("provavel", "confirmado_area", "ingerido_extraido"):
                cand = val.split(" — ")[0].split(" (")[0].strip()
                if ":" in cand:
                    cand = cand.split(":")[-1].strip()
                areas[cand] = area
    return areas


def load_indi_full():
    """Lista Indicium completa p/ a aba: egp_dor1, area, status_extracao, projeto resolvido
    (mesma extração de projeto do load_indi_projects; vazio para faltante)."""
    out = []
    if not os.path.exists(INDI):
        return out
    with open(INDI, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            st = n(r.get("status_extracao"))
            val = r.get("project_no_06 / observacao", "") or ""
            projeto = ""
            if st in ("exato", "variante"):
                projeto = val.strip()
            elif st in ("provavel", "confirmado_area", "ingerido_extraido"):
                cand = val.split(" — ")[0].split(" (")[0].strip()
                if ":" in cand:
                    cand = cand.split(":")[-1].strip()
                projeto = cand
            out.append({
                "egp_dor1": n(r.get("egp_dor1")),
                "area": canon_area(r.get("area")),
                "status_extracao": st,
                "projeto": projeto,
            })
    return out


def load_egps_casca(path=None):
    """EGPs "casca" (cadastro versionado, ver EGPS_CASCA acima): 1 linha por antecessor
    absorvido por um EGP Atualizado unificador, sem inventário próprio.

    `projeto = "<pasta>__<nome>"`, a mesma convenção dos nós reais — `pasta` é o rótulo CRU
    da área na extração e NÃO é necessariamente igual à `area` canônica ("Cobranças" na
    pasta vs "Cobrança" na coluna). Não unificar os dois.

    Arquivo ausente = lista vazia, não erro (nada de casca cadastrado ainda)."""
    out = []
    path = path or EGPS_CASCA
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pasta = (r.get("pasta") or "").strip()
            nome = (r.get("nome") or "").strip()
            if not pasta or not nome:
                continue
            out.append({
                "projeto": f"{pasta}__{nome}",
                "area": canon_area(r.get("area")),
                "unificado_em": (r.get("unificado_em") or "").strip(),
                "motivo": (r.get("motivo") or "").strip(),
            })
    return out


def _casca_artifact(projeto):
    return f"(casco — {projeto}, sem inventário real; ver src/egps_casca.csv)"


def build_casca_rows(cascas, existentes):
    """Linhas de uma casca no formato de nodes/inputs/egp_inputs. Casca que colide com um
    projeto REAL já existente é descartada (o real manda).

    Duas armadilhas medidas em 2026-09 moram aqui:

    • `escopo_indi=True` é gravado DIRETO, sem depender de sas_escopo — é a intenção do
      pedido: contar como migração em andamento assim que a casca existir. Ainda assim,
      sas_escopo precisa ganhar a linha (ver casca_escopo_rows), porque recompute_escopo()
      RESETA escopo_indi dos nós fora dali a cada edição de escopo — sem isso a flag se
      apaga sozinha no próximo recompute.

    • 1 input SINTÉTICO por casca: a aba EGPs não lê sas_lineage_nodes direto — a query
      agrupa a partir de sas_egp_inputs (grão projeto×input), então um EGP com ZERO inputs
      nunca gera linha no GROUP BY e fica invisível lá, mesmo com o nó existindo. Em vez de
      reescrever essa query central (usada por várias telas), cada casca ganha 1 input
      fictício já "Disponível" — não é trabalho, não entra na fila de ingestão — mas
      claramente rotulado (artifact começa com "(casco —") pra quem abrir o detalhe."""
    novas = [c for c in cascas if c["projeto"] not in existentes]
    nodes, inputs, egp_inputs = [], [], []
    for c in novas:
        proj, chave, art = c["projeto"], f"casco::{c['projeto']}", _casca_artifact(c["projeto"])
        nodes.append({
            "projeto": proj, "area": c["area"], "onda": "",
            "n_inputs": 1, "n_outputs": 0, "escopo_indi": True, "ciclo_id": 0,
        })
        inputs.append({
            "chave_canonica": chave,
            "artifact": art,
            "categoria": "tabela",
            "origem": "Casco (EGP unificado)",
            "source_types": "",
            "qtd_projetos": 1,
            "areas": c["area"],
            "escopo_indi": True,
            "modernizada_auto": "Disponível",
            "paths_fisicos": "",
            "n_paths_fisicos": 0,
        })
        egp_inputs.append({
            "projeto": proj, "area": c["area"], "onda": "", "escopo_indi": True,
            "ciclo_id": 0, "chave_canonica": chave, "artifact": art,
            "categoria": "tabela", "source_types": "", "modernizada_auto": "Disponível",
        })
    return {"cascas": novas, "nodes": nodes, "inputs": inputs, "egp_inputs": egp_inputs}


def casca_escopo_rows(cascas, existentes, cap):
    """Linhas de sas_escopo para as cascas ainda não cadastradas lá (`existentes` = projetos
    já presentes na tabela, ATIVOS ou NÃO — um soft-delete da gestão não pode ser
    ressuscitado pelo republish). Sem esta linha, recompute_escopo() apaga o escopo_indi da
    casca no primeiro recompute (§3.6 regra 24). status_extracao='exato' porque a casca ESTÁ
    no grafo: 'faltante' subcontaria o funil por área (e o self-heal do recompute a
    promoveria mesmo assim)."""
    return [{
        "id": uuid.uuid4().hex, "egp_dor1": c["projeto"], "area": c["area"],
        "status_extracao": "exato", "projeto": c["projeto"],
        "origem": "casca", "created_by": "casca", "created_at": cap,
    } for c in cascas if c["projeto"] not in existentes]


def compute_ciclo_ids(edge_pairs):
    """SCC (Tarjan) sobre o grafo dep->alvo. Retorna {projeto: ciclo_id} (id>=1 para
    membros de ciclo de tamanho>=2; 0 caso contrário) — usado pelo destaque visual."""
    import sys as _sys
    _sys.setrecursionlimit(100000)
    adj = collections.defaultdict(set)
    nodes = set()
    for (alvo, dep) in edge_pairs:
        nodes.add(alvo); nodes.add(dep)
        if alvo != dep:
            adj[dep].add(alvo)
    index, low, onst, stk, idx, comps = {}, {}, {}, [], [0], []

    def strong(v0):
        work = [(v0, iter(sorted(adj[v0])))]
        index[v0] = low[v0] = idx[0]; idx[0] += 1; stk.append(v0); onst[v0] = True
        while work:
            node, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = idx[0]; idx[0] += 1; stk.append(w); onst[w] = True
                    work.append((w, iter(sorted(adj[w])))); pushed = True; break
                elif onst.get(w):
                    low[node] = min(low[node], index[w])
            if pushed:
                continue
            for w in adj[node]:
                if onst.get(w):
                    low[node] = min(low[node], low[w])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stk.pop(); onst[w] = False; comp.append(w)
                    if w == node:
                        break
                comps.append(comp)
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])

    for v in sorted(nodes):
        if v not in index:
            strong(v)
    ciclo = {}
    cid = 0
    for comp in sorted(comps, key=lambda c: (-len(c), sorted(c))):
        if len(comp) >= 2:
            cid += 1
            for p in comp:
                ciclo[p] = cid
    return ciclo


def _nome_indi(projeto, decisoes):
    """Nome publicado de um projeto do indi_231 (o CPF_Contrato está lá pelo nome antigo; quem
    editar a linha para o nome que o app mostra também passa). Um EGP da lista Indicium que as
    decisões excluem é contradição, não detalhe: para."""
    if projeto in decisoes.renomes.values():  # já é o nome publicado de um renome
        return projeto
    novo = decisoes.nome(projeto)
    if novo is None:
        raise egp_decisoes.DecisaoInvalida(
            f"{projeto} está na lista Indicium (indi_231) e foi excluído em {DECISOES}; "
            f"decida qual dos dois vale")
    return novo


def _confere_outputs_fora(decisoes, egp_out):
    """tirar_output_do_escopo cujo prefixo não acha nenhum output do EGP é decisão que não se
    aplica (prefixo digitado errado): para, em vez de deixar os outputs no escopo calado."""
    for proj, prefixos in decisoes.outputs_fora().items():
        arts = [(er["artifact"] or "").upper() for er in egp_out.values() if er["projeto"] == proj]
        for prefixo in prefixos:
            if not any(a.startswith(prefixo) for a in arts):
                raise egp_decisoes.DecisaoInvalida(
                    f"tirar_output_do_escopo: nenhum output de {proj} começa com {prefixo} "
                    f"({DECISOES})")


def build(choices=None):
    decisoes = egp_decisoes.carrega(DECISOES)
    corpus = egp_decisoes.aplica_ao_corpus(TXT_DIR, decisoes)
    # dois nomes do indi_231 (o antigo e o publicado) no mesmo EGP semeariam o escopo duas vezes
    fontes = collections.defaultdict(set)
    for p in load_indi_projects():
        fontes[_nome_indi(p, decisoes)].add(p)
    duplos = {k: sorted(v) for k, v in fontes.items() if len(v) > 1}
    if duplos:
        raise egp_decisoes.DecisaoInvalida(
            f"indi_231 cita o mesmo EGP por dois nomes (renome em {DECISOES}): {duplos}")
    indi = set(fontes)
    proj_dor1_area = {_nome_indi(p, decisoes): a for p, a in load_indi_project_areas().items()}
    onda = {}
    if os.path.exists(R04):
        with open(R04, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                onda[r["Projeto"].strip()] = r["Onda_de_Conversao"].strip()

    # ---- inputs_monitor (grão = input distinto) + nodes I/O counts ----
    inputs = {}  # chave -> dict
    resumo = {}  # chave -> dict  (universo mais amplo: inclui libname_in, p/ aba Resumo)
    egp_in = {}  # (proj, chave) -> dict  (grão projeto×input, p/ aba EGP)
    proj_in = collections.defaultdict(set)
    proj_out = collections.defaultdict(set)
    proj_area = {}
    produced_tables = set()  # canon(art) de todo table_out (sem ruído) — p/ origem "dependência"
    macro_dropped = set()  # file_in com macro não expandida (ver is_macro_artifact) — logado no fim
    # ---- outputs (paralelo a inputs/egp_in): grão output distinto + grão EGP×output ----
    # libname_out fora do universo de outputs do app (decisão 2026-08-12): o libref
    # exportado não é um dado concreto — as tabelas escritas nele já entram como
    # table_out lib.membro; a linha de libname só duplicava/poluía a aba Outputs.
    OUT_CATS = {"table_out", "file_out"}
    outputs = {}  # canon(art) -> {"artifact","categoria","projetos":set,"modern":bool}
    egp_out = {}  # (proj, canon(art)) -> {"projeto","chave_canonica","artifact","categoria"}
    libs_for_project = build_project_libmap(corpus)
    sas7_dedup = _sas7bdat_dedup_members(libs_for_project)
    non_creator_by_proj = build_non_creator_map(corpus)
    with open(R06, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            proj = n(r.get("project"))
            art = n(r.get("artifact"))
            cat = n(r.get("category"))
            if not proj or not art:
                continue
            proj_area.setdefault(proj, AREA_OVERRIDE.get(proj, canon_area(r.get("area")) or "(sem área)"))
            # dedup .sas7bdat vs lib.membro (mesma tabela física, mesmo projeto) -> colapsa no
            # lib.membro; ver _sas7bdat_dedup_members. Arquivo .sas7bdat sem par tabela é preservado.
            if cat == "file_in" and art.lower().endswith(".sas7bdat") \
                    and _memb_sas7(art) in sas7_dedup.get(proj, ()):
                continue
            # coleta de outputs (roda ANTES do continue do table_out); table_out ruído é ignorado
            if cat in OUT_CATS and not (cat == "table_out" and (is_noise_table(art) or is_work_implicit(art))):
                ock = canon(art)
                orec = outputs.get(ock)
                if orec is None:
                    orec = outputs[ock] = {"artifact": art, "categoria": cat,
                                           "projetos": set(), "modern": False, "paths": set(),
                                           "contribs": set()}
                orec["projetos"].add(proj)
                if ock in non_creator_by_proj.get(proj, ()):
                    orec["contribs"].add(proj)
                _opath = n(r.get("path"))
                if _opath:
                    orec["paths"].add(_opath)
                _ost = n(r.get("status_validacao")).upper()
                if any(m in _ost for m in MODERN_MARKERS):
                    orec["modern"] = True
                egp_out.setdefault((proj, ock), {"projeto": proj, "chave_canonica": ock,
                                                 "artifact": art, "categoria": cat,
                                                 "apenas_contribui": ock in non_creator_by_proj.get(proj, ())})
            if cat == "table_out":
                if not is_noise_table(art):
                    proj_out[proj].add(canon(art))
                    produced_tables.add(canon(art))
                continue
            if cat in RES_CATS and not (cat == "table_in" and is_noise_table(art)) \
                    and not (cat == "file_in" and is_macro_artifact(art)):
                rcat = eff_categoria(cat, art, RES_CATS)
                rkey = f"{rcat}::{canon(art)}"
                rr = resumo.get(rkey)
                if rr is None:
                    rr = resumo[rkey] = {
                        "chave_canonica": rkey, "categoria": rcat,
                        "source_types": set(),
                        "projetos": set(), "modern": False,
                    }
                rr["source_types"].add(n(r.get("source_type")))
                rr["projetos"].add(proj)
                _stv = n(r.get("status_validacao")).upper()
                if any(m in _stv for m in MODERN_MARKERS):
                    rr["modern"] = True
            if cat not in IN_CATS:
                continue
            if cat in ("table_in",) and is_noise_table(art):
                continue
            # file_in com macro não expandida não é arquivo — é padrão parametrizado que o
            # extrator não resolveu. Paridade com o guard `'&' in a` de is_noise_table(),
            # que nunca rodou para arquivos. O descarte é LOGADO (nunca silencioso).
            if cat == "file_in" and is_macro_artifact(art):
                macro_dropped.add(canon(art))
                continue
            categoria = eff_categoria(cat, art, IN_CATS)
            key = f"{categoria}::{canon(art)}"
            rec = inputs.get(key)
            if rec is None:
                rec = inputs[key] = {
                    "chave_canonica": key, "artifact": art, "categoria": categoria,
                    "source_types": set(), "projetos": set(), "areas": set(),
                    "modern": False, "paths": set(),
                }
            rec["source_types"].add(n(r.get("source_type")))
            rec["projetos"].add(proj)
            rec["areas"].add(AREA_OVERRIDE.get(proj, canon_area(r.get("area")) or "(sem área)"))
            # Path de arquivo/script vem PRONTO do relatório; tabela continua resolvendo
            # libref->diretório pelo libmap (bloco mais abaixo). Não misturar as duas
            # fontes: para table_in a coluna `path` é o diretório do libname e entraria
            # com semântica diferente da que `paths_fisicos` tem hoje para tabela.
            if categoria != "tabela":
                _fp = path_de_arquivo(r.get("path"))
                if _fp:
                    rec["paths"].add(_fp)
            st = n(r.get("status_validacao")).upper()
            if any(m in st for m in MODERN_MARKERS):
                rec["modern"] = True
            proj_in[proj].add(canon(art))
            ek = (proj, key)
            er = egp_in.get(ek)
            if er is None:
                er = egp_in[ek] = {"projeto": proj, "chave_canonica": key, "artifact": art,
                                   "categoria": categoria, "source_types": set()}
            er["source_types"].add(n(r.get("source_type")))

    # ---- resolução de path físico (SAS/Local-tabela) por chave_canonica ----
    # Para cada input cuja origem é SAS/Local (categoria 'tabela', sem fonte BD/BigQuery),
    # resolvemos libref->path físico por PROJETO que o lê (grão projeto×input em egp_in),
    # com o libmap por projeto-pasta (build_project_libmap). Agregamos o conjunto de paths
    # distintos sobre todos os projetos. n_paths_fisicos>1 => HOMÔNIMO (1 nome = N tabelas
    # físicas). Membro = parte após o 1º ponto do artifact (UPPER).
    paths_por_chave = collections.defaultdict(set)  # chave_canonica -> set((path, member))
    saslocal_keys = set()       # chaves SAS/Local-tabela (X = inputs por nome)
    resolved_pairs = set()      # (path, member) distintos resolvidos
    unresolved_keys = set()     # chaves SAS/Local-tabela sem nenhum path resolvido
    for (proj, key), er in egp_in.items():
        rec = inputs[key]
        produced = canon(rec["artifact"]) in produced_tables
        origem = origem_input(rec["source_types"], rec["categoria"], produced)
        if not origem.startswith("SAS/Local"):
            continue
        art = canon(er["artifact"])
        if "." not in art:
            continue
        saslocal_keys.add(key)
        lib, member = art.split(".", 1)  # member = parte após o 1º ponto (UPPER)
        for p in libs_for_project(proj).get(lib, ()):
            paths_por_chave[key].add((p, member))
            resolved_pairs.add((p, member))
    for key in saslocal_keys:
        if not paths_por_chave.get(key):
            unresolved_keys.add(key)
    # Y = (path,member) distintos resolvidos + nomes (chaves) não-resolvidos distintos
    saslocal_resumo = {
        "x_nomes": len(saslocal_keys),
        "y_fisicas": len(resolved_pairs) + len(unresolved_keys),
    }

    inputs_rows = []
    for rec in inputs.values():
        dor = bool(rec["projetos"] & indi)
        if rec["categoria"] == "tabela":
            pm = paths_por_chave.get(rec["chave_canonica"], set())
            paths = sorted({p for (p, _m) in pm})
        else:
            # arquivo/script: n_paths_fisicos>1 = MESMO basename em pastas diferentes
            # (a chave canônica desses é o basename), que é homônimo de arquivo — mesma
            # leitura que a coluna já tem para tabela.
            paths = sorted(rec["paths"])
        inputs_rows.append({
            "chave_canonica": rec["chave_canonica"],
            "artifact": rec["artifact"],
            "categoria": rec["categoria"],
            "origem": origem_input(rec["source_types"], rec["categoria"],
                                   canon(rec["artifact"]) in produced_tables),
            "source_types": " | ".join(sorted(s for s in rec["source_types"] if s)),
            "qtd_projetos": len(rec["projetos"]),
            "areas": " | ".join(sorted(rec["areas"])),
            "escopo_indi": dor,
            "modernizada_auto": "Disponível" if rec["modern"] else "A ingerir",
            "paths_fisicos": " | ".join(paths),
            "n_paths_fisicos": len(paths),
        })

    # ---- lineage edges (agrega via tabelas) ----
    choices = choices or {}
    r03 = []
    with open(R03, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        c = rd.fieldnames
        for r in rd:
            alvo = r[c[0]].strip()
            dep = r[c[1]].strip()
            t = r[c[2]].strip()
            try:
                np_ = int(r.get("n_produtores") or 1)
            except (TypeError, ValueError):
                np_ = 1
            if alvo and dep and alvo != dep:
                r03.append((alvo, dep, t, np_))
    # poda por produtor canonico (sub-projeto 2): remove a via T de arestas cujo produtor
    # nao e o escolhido -> edges/ciclo/ondas nascem podados no proximo Processar. Self-heal:
    # so honra a escolha se o escolhido de fato produz T no report (evita orfao).
    prod_by_via = {}
    for alvo, dep, t, np_ in r03:
        prod_by_via.setdefault(t, set()).add(dep)
    eff = {t: p for t, p in choices.items() if p in prod_by_via.get(t, ())}
    edges = collections.defaultdict(set)
    edge_maxprod = collections.defaultdict(int)
    for alvo, dep, t, np_ in r03:
        if t in eff and eff[t] != dep:
            continue
        edges[(alvo, dep)].add(t)
        n_eff = 1 if t in eff else np_
        if n_eff > edge_maxprod[(alvo, dep)]:
            edge_maxprod[(alvo, dep)] = n_eff
    edges_rows = [{
        "projeto_alvo": a, "depende_do": d,
        "via_tabelas": " | ".join(sorted(ts)), "qtd_via": len(ts),
        "max_produtores": edge_maxprod[(a, d)] or 1,
    } for (a, d), ts in edges.items()]

    # ---- ciclo_id por projeto (SCC) p/ destaque visual de dependência cíclica ----
    ciclo = compute_ciclo_ids(set(edges))

    # ---- lineage nodes ----
    all_projs = set(proj_area) | {a for a, _ in edges} | {d for _, d in edges}
    # 06/03 gerados sem as decisões (orquestrador antigo, outro checkout) trazem de volta o
    # que elas tiram. Para aqui, antes de qualquer escrita.
    velhos = decisoes.nomes_proibidos() & all_projs
    if velhos:
        raise egp_decisoes.DecisaoInvalida(
            f"os CSVs do orquestrador trazem EGPs que {DECISOES} exclui ou renomeia "
            f"({', '.join(sorted(velhos)[:5])}): rode o orchestrator_inventory.py de novo")
    _confere_outputs_fora(decisoes, egp_out)
    nodes_rows = [{
        "projeto": p,
        "area": proj_area.get(p, "(sem área)"),
        "onda": onda.get(p, ""),
        "n_inputs": len(proj_in.get(p, ())),
        "n_outputs": len(proj_out.get(p, ())),
        "escopo_indi": p in indi,
        "ciclo_id": ciclo.get(p, 0),
    } for p in sorted(all_projs)]

    # EGPs "casca" (ver build_casca_rows/EGPS_CASCA): somados aqui, ANTES do loop de
    # interm_metrics logo abaixo — cada um cai no ramo `m is None` desse loop e herda
    # _interm_default (loc=0, sem output avaliado, todas as flags neutras).
    _casca = build_casca_rows(load_egps_casca(), {n["projeto"] for n in nodes_rows})
    nodes_rows.extend(_casca["nodes"])
    inputs_rows.extend(_casca["inputs"])
    all_projs |= {c["projeto"] for c in _casca["cascas"]}

    # ---- egp_inputs (grão projeto×input) p/ aba EGP (projeto -> inputs) ----
    egp_inputs_rows = [{
        "projeto": er["projeto"],
        "area": proj_area.get(er["projeto"], "(sem área)"),
        "onda": onda.get(er["projeto"], ""),
        "escopo_indi": er["projeto"] in indi,
        "ciclo_id": ciclo.get(er["projeto"], 0),
        "chave_canonica": er["chave_canonica"],
        "artifact": er["artifact"],
        "categoria": er["categoria"],
        "source_types": " | ".join(sorted(s for s in er["source_types"] if s)),
        "modernizada_auto": "Disponível" if inputs[er["chave_canonica"]]["modern"] else "A ingerir",
    } for er in egp_in.values()]
    egp_inputs_rows.extend(_casca["egp_inputs"])

    # ---- outputs_monitor (grão output distinto) + egp_outputs (grão EGP×output) ----
    # consumidores(o) = EGPs que leem 'o' como input (mesmo canon). proj_in guarda
    # canon(art) puro (não a chave prefixada), então casa com as chaves de outputs.
    consumers_by_name = {}
    for _p, _ins in proj_in.items():
        for _ck in _ins:
            consumers_by_name.setdefault(_ck, set()).add(_p)
    out_rows = []
    for ock, orec in outputs.items():
        prods = orec["projetos"]
        cons = consumers_by_name.get(ock, set())
        areas = sorted({proj_area.get(p, "") for p in prods if proj_area.get(p)})
        out_rows.append({
            "chave_canonica": ock,
            "artifact": orec["artifact"],
            "categoria": orec["categoria"],
            "areas": ", ".join(areas),
            "qtd_produtores": len(prods),
            "qtd_criadores": len(prods - orec.get("contribs", set())),
            "qtd_consumidores": len(cons),
            "terminal": len(cons) == 0,
            "modernizada_auto": "Disponível" if orec["modern"] else "A ingerir",
            # tirar_output_do_escopo (egp_decisoes): o par (EGP, output) cortado não conta
            "escopo_indi": any(p in indi and decisoes.output_no_escopo(p, orec["artifact"])
                               for p in prods),
            "paths_fisicos": " | ".join(sorted(orec["paths"])),
        })
    egp_out_rows = [{
        "projeto": er["projeto"],
        "area": proj_area.get(er["projeto"], "(sem área)"),
        "onda": onda.get(er["projeto"], ""),
        "escopo_indi": er["projeto"] in indi
                       and decisoes.output_no_escopo(er["projeto"], er["artifact"]),
        "chave_canonica": er["chave_canonica"],
        "artifact": er["artifact"],
        "categoria": er["categoria"],
        "apenas_contribui": bool(er.get("apenas_contribui")),
    } for er in egp_out.values()]

    # ---- indicadores de "modelo intermediário" por EGP (LOC + consumo por outro EGP) ----
    # Reusa a MESMA definição de consumidor/terminal já usada na aba Outputs
    # (consumers_by_name/out_rows, casamento por nome canônico) — não duplica linhagem com
    # regra própria; um EGP "100% p/ outro EGP" aqui bate com o que a aba Outputs já mostra
    # output a output (nenhuma recuperação por path físico aqui, igual à aba Outputs).
    # Auto-consumo (o próprio EGP lendo o que ele mesmo produziu) NÃO conta como "consumido
    # por outro EGP" — sempre subtrai o produtor do conjunto de consumidores (ver relatório
    # de EGPs auto-alimentados, docs/analises/relatorio_egps_auto_alimentados.md).
    # São indicadores SEPARADOS e não combinados num veredito — cabe ao analista cruzar
    # (LOC baixo + 100% p/ outro EGP + sem export = sinal forte; qualquer combinação
    # parcial fica visível igual, sem corte automático).
    loc_tasks = build_loc_tasks(corpus)
    outs_by_proj = collections.defaultdict(list)
    for er in egp_out.values():
        outs_by_proj[er["projeto"]].append(er["chave_canonica"])
    interm_metrics = {}
    for proj, ocks in outs_by_proj.items():
        n_outputs_aval = len(ocks)
        n_exports = sum(1 for ock in ocks if outputs.get(ock, {}).get("categoria") == "file_out")
        consumed = 0
        egp_consumers = set()
        for ock in ocks:
            cons = consumers_by_name.get(ock, set()) - {proj}
            if cons:
                consumed += 1
                egp_consumers |= cons
        pct = round(100 * consumed / n_outputs_aval, 1) if n_outputs_aval else 0.0
        loc, tasks = loc_tasks.get(proj, (0, 0))
        interm_metrics[proj] = {
            "loc": loc,
            "code_tasks_count": tasks,
            "n_outputs_avaliados": n_outputs_aval,
            "n_outputs_consumidos_por_outro_egp": consumed,
            "pct_outputs_consumidos_por_outro_egp": pct,
            "n_egps_consumidores": len(egp_consumers),
            "n_exports_arquivos": n_exports,
            "flag_output_100pct_egp": n_outputs_aval > 0 and pct == 100.0,
            "flag_algum_output_egp": consumed > 0,
            "flag_sem_export_arquivo": n_exports == 0,
            "flag_output_unico": n_outputs_aval == 1,
            "flag_hub_multiplos_consumidores": len(egp_consumers) >= 3,
        }
    _interm_default = {
        "n_outputs_avaliados": 0, "n_outputs_consumidos_por_outro_egp": 0,
        "pct_outputs_consumidos_por_outro_egp": 0.0, "n_egps_consumidores": 0,
        "n_exports_arquivos": 0, "flag_output_100pct_egp": False, "flag_algum_output_egp": False,
        "flag_sem_export_arquivo": True, "flag_output_unico": False,
        "flag_hub_multiplos_consumidores": False,
    }
    for row in nodes_rows:
        m = interm_metrics.get(row["projeto"])
        if m is None:
            loc, tasks = loc_tasks.get(row["projeto"], (0, 0))
            m = {**_interm_default, "loc": loc, "code_tasks_count": tasks}
        row.update(m)

    # ---- métricas (snapshot) ----
    def metrics_for(rows, scope_projects=None):
        if scope_projects is None:
            rs = rows
        else:
            rs = [r for r in rows if r["escopo_indi"]]
        tabs = [r for r in rs if r["categoria"] == "tabela"]
        # Unidade FAMÍLIA DE SAFRAS (docs/adr/0002), em métricas NOVAS — as de cima ficam
        # intactas de propósito: a série que a liderança já viu continua comparável, e o
        # degrau da unificação aparece como outra curva, não como a mesma métrica mudando
        # de significado no meio. A família só conta como resolvida quando TODAS as suas
        # safras estão (qualquer safra pendente segura a família).
        _fm = _fam_metrics(rs)
        # INPUT = table_in + file_in + script_in (IN_CATS). "tabela" é só o subconjunto table_in.
        return {
            "inputs_distintos": len(rs),
            "inputs_a_ingerir": sum(1 for r in rs if r["modernizada_auto"] == "A ingerir"),
            "inputs_disponiveis": sum(1 for r in rs if r["modernizada_auto"] == "Disponível"),
            "tabelas_distintas": len(tabs),
            "tabelas_a_ingerir": sum(1 for r in tabs if r["modernizada_auto"] == "A ingerir"),
            "tabelas_disponiveis": sum(1 for r in tabs if r["modernizada_auto"] == "Disponível"),
            "tabelas_compartilhadas": sum(1 for r in tabs if r["qtd_projetos"] >= 2),
            **_fm,
        }
    cap = now_iso()
    metrics_rows = []
    for scope, mp in (("base", metrics_for(inputs_rows)),
                      ("indi", metrics_for(inputs_rows, True))):
        for k, v in mp.items():
            metrics_rows.append({"captured_at": cap, "escopo": scope, "metric": k, "valor": v})
    metrics_rows.append({"captured_at": cap, "escopo": "base", "metric": "projetos", "valor": len(all_projs)})
    metrics_rows.append({"captured_at": cap, "escopo": "indi", "metric": "projetos",
                         "valor": sum(1 for nrow in nodes_rows if nrow["escopo_indi"])})

    # ---- resumo_inputs (input distinto: area_principal + origem_bucket) ----
    resumo_rows = []
    for rr in resumo.values():
        # area_principal = 1 área por input, via voto pela ponte projeto↔área DOR1
        # (vocabulário do funil/indi_231). dor1_votes = áreas que TÊM EGP consumindo este
        # input; a regra vive em escolhe_area_principal (input sem EGP -> "(sem área)").
        dor1_votes = collections.Counter(
            proj_dor1_area[pj] for pj in rr["projetos"] if pj in proj_dor1_area
        )
        area_principal = escolhe_area_principal(dor1_votes)
        resumo_rows.append({
            "chave_canonica": rr["chave_canonica"],
            "area_principal": area_principal,
            "origem_bucket": origem_bucket(rr["source_types"], rr["categoria"]),
            "escopo_indi": bool(rr["projetos"] & indi),
            "modernizada_auto": "Disponível" if rr["modern"] else "A ingerir",
        })

    # ---- funil_area (do indi_231: DOR1 / Enviados / Analisados) ----
    # 'ingerido_extraido' (recebido e processado) conta como Enviado E como Analisado.
    # Após dedup do projeto duplicado: escopo 230 · Enviados 229 · Analisados 229.
    ANALISADO = {"exato", "variante", "confirmado_area", "ingerido_extraido"}
    funil_acc = collections.defaultdict(lambda: [0, 0, 0])
    if os.path.exists(INDI):
        with open(INDI, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                a = canon_area(r.get("area"))
                stt = n(r.get("status_extracao"))
                funil_acc[a][0] += 1
                if stt != "faltante":
                    funil_acc[a][1] += 1
                if stt in ANALISADO:
                    funil_acc[a][2] += 1
    funil_rows = [{"area": a, "qtd_dor1": v[0], "egps_enviados": v[1], "egps_analisados": v[2]}
                  for a, v in sorted(funil_acc.items())]

    # mapa explodido chave→projeto (TODAS as categorias do resumo, inclui libname):
    # usado pelo recompute para re-derivar resumo.escopo_indi sem republish, fiel a
    # `bool(rr["projetos"] & indi)`. egp_inputs só cobre IN_CATS, então não basta.
    resumo_proj_rows = [{"chave_canonica": rr["chave_canonica"], "projeto": pj}
                        for rr in resumo.values() for pj in sorted(rr["projetos"]) if pj]

    return {"inputs": inputs_rows, "edges": edges_rows, "nodes": nodes_rows,
            "egp_inputs": egp_inputs_rows, "metrics": metrics_rows, "cap": cap,
            "n_ciclos": (max(ciclo.values()) if ciclo else 0),
            "resumo": resumo_rows, "resumo_proj": resumo_proj_rows,
            "funil": funil_rows,
            "indicium": [{**r, "projeto": _nome_indi(r["projeto"], decisoes)}
                         for r in load_indi_full()],
            "casca": _casca["cascas"],
            "saslocal_resumo": saslocal_resumo,
            "outputs": out_rows, "egp_outputs": egp_out_rows,
            "macro_dropped": sorted(macro_dropped)}


# ----------------------- SQL helpers -----------------------
def sql_lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    # Aspa escapada com \' e NÃO com '' : no Spark SQL `'O''Brien'` é lido como DOIS
    # literais adjacentes concatenados ("O" + "Brien"), então o apóstrofo some em
    # silêncio — não dá erro, grava o texto errado. Verificado no warehouse:
    #   SELECT 'O''Brien'  -> OBrien      (errado)
    #   SELECT 'O\'Brien'  -> O'Brien     (certo)
    # A contrabarra é escapada ANTES da aspa, senão a barra introduzida por \' seria
    # duplicada. Não confundir com sas_quote() em egps_extractor.py: aquilo gera código
    # SAS, onde '' É o escape correto.
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def insert_batches(table, cols, rows, batch=400):
    stmts = []
    collist = "(" + ", ".join(cols) + ")"
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        values = ",\n".join("(" + ", ".join(sql_lit(r.get(c)) for c in cols) + ")" for r in chunk)
        stmts.append(f"INSERT INTO {table} {collist} VALUES\n{values}")
    return stmts


def _load_choices(args):
    """Le sas_output_producer_choice (produtor canonico) p/ podar as arestas no publish —
    ondas/ciclo consistentes com a escolha. Tolerante: {} se tabela ausente / erro."""
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
        import time as _t
        w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
        resp = w.statement_execution.execute_statement(
            statement=f"SELECT chave_canonica, projeto_escolhido FROM {args.catalog}.{args.schema}.sas_output_producer_choice",
            warehouse_id=args.warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            _t.sleep(1)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            return {}
        rows = list(resp.result.data_array or []) if resp.result else []
        ch = {r[0]: r[1] for r in rows if r and r[0] and r[1]}
        if ch:
            print(f"  produtor canonico: {len(ch)} escolha(s) -> poda aplicada")
        return ch
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="conecta e escreve no Databricks (default: dry-run)")
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    # Default = sandbox _dev, NUNCA prod: um --apply sem --schema não pode atingir produção.
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas_dev"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"),
                    help="perfil do ~/.databrickscfg (OAuth/U2M); alternativa a DATABRICKS_HOST/TOKEN")
    ap.add_argument("--sem-reaplicar-identidade", action="store_true",
                    dest="sem_reaplicar_identidade",
                    help="nao reaplica os colapsos de sas_input_alias_canonico (ticket 25). "
                         "A guarda continua rodando e o publish falha se houver desfeito.")
    ap.add_argument("--prod-confirm", action="store_true",
                    help=f"obrigatório p/ --apply contra o schema de PROD ('{PROD_SCHEMA}')")
    args = ap.parse_args()

    # guarda anti-prod: escrever no schema de PROD exige --prod-confirm explícito. Impede o
    # acidente de um --apply manual cair em produção por causa do default (ver PROD_SCHEMA).
    if args.apply and args.schema == PROD_SCHEMA and not args.prod_confirm:
        ap.error(f"--apply contra PROD ('{args.catalog}.{args.schema}') requer --prod-confirm. "
                 f"Sem ele, use o sandbox (default --schema {args.catalog}.monitoramento_sas_dev).")
    if args.apply:
        _tgt = "PRODUÇÃO ⚠️" if args.schema == PROD_SCHEMA else "sandbox/dev"
        print(f"--apply vai ESCREVER em {args.catalog}.{args.schema}  [{_tgt}]")

    choices = _load_choices(args) if args.apply else {}
    try:
        data = build(choices)
    except egp_decisoes.DecisaoInvalida as e:
        print(f"\n❌ ABORTADO antes de escrever: {e}", file=sys.stderr)
        sys.exit(2)
    fq = f"{args.catalog}.{args.schema}"
    T_IN, T_ED, T_ND, T_MT = (f"{fq}.sas_inputs_monitor", f"{fq}.sas_lineage_edges",
                              f"{fq}.sas_lineage_nodes", f"{fq}.sas_pipeline_metrics")
    T_EGP = f"{fq}.sas_egp_inputs"
    T_OUT = f"{fq}.sas_outputs_monitor"
    T_EGP_OUT = f"{fq}.sas_egp_outputs"
    T_RES = f"{fq}.sas_resumo_inputs"
    T_RESP = f"{fq}.sas_resumo_proj"
    T_FUN = f"{fq}.sas_funil_area"
    T_AUD = f"{fq}.sas_inputs_audit"
    T_ESC = f"{fq}.sas_escopo"
    T_ESC_AUD = f"{fq}.sas_escopo_audit"
    STG = f"{fq}.sas_inputs_monitor_stg"

    print("== PUBLISH (build local) ==")
    print(f"  destino: {fq}")
    indi_rows = [r for r in data["inputs"] if r["escopo_indi"]]
    indi_ingerir = sum(1 for r in indi_rows if r["modernizada_auto"] == "A ingerir")
    indi_tab_ingerir = sum(1 for r in indi_rows if r["categoria"] == "tabela" and r["modernizada_auto"] == "A ingerir")
    print(f"  inputs_monitor : {len(data['inputs']):6d} linhas  "
          f"(INDI={len(indi_rows)} inputs · {indi_ingerir} a ingerir "
          f"[das quais {indi_tab_ingerir} tabelas])")
    # unidade FAMÍLIA DE SAFRAS (métricas novas, em paralelo às de cima — ADR 0002).
    # Impressa no dry-run de propósito: o degrau da unificação tem que ser visível ANTES
    # de escrever, não descoberto depois num gráfico.
    _mf = {k: v for k, v in _fam_metrics(data["inputs"]).items()}
    _mfi = {k: v for k, v in _fam_metrics(indi_rows).items()}
    print(f"    unidade família: {_mf['inputs_familias']} famílias/unidades no total "
          f"({_mf['inputs_pendentes_familia']} pendentes) · "
          f"INDI={_mfi['inputs_familias']} unidades ({_mfi['inputs_pendentes_familia']} pendentes)")
    print(f"  lineage_edges  : {len(data['edges']):6d}")
    print(f"  lineage_nodes  : {len(data['nodes']):6d}  ({data['n_ciclos']} clusters cíclicos; "
          f"{len(data['casca'])} casca(s) sem inventário próprio)")
    _n100 = sum(1 for r in data['nodes'] if r.get('flag_output_100pct_egp'))
    _nalgum = sum(1 for r in data['nodes'] if r.get('flag_algum_output_egp'))
    _nhub = sum(1 for r in data['nodes'] if r.get('flag_hub_multiplos_consumidores'))
    print(f"    indicadores intermediário: {_n100} EGPs 100% p/ outro EGP · "
          f"{_nalgum} com algum output p/ outro EGP · {_nhub} hub (>=3 consumidores)")
    print(f"  egp_inputs     : {len(data['egp_inputs']):6d}  (grão projeto×input)")
    print(f"  resumo_inputs  : {len(data['resumo']):6d}  (input distinto + origem/area)")
    print(f"  funil_area     : {len(data['funil']):6d}  (areas)")
    print(f"  pipeline_metrics:{len(data['metrics']):6d} (snapshot {data['cap']})")
    print(f"  outputs: {len(data['outputs'])} distintos, {len(data['egp_outputs'])} pares EGP×output")
    _sl = data["saslocal_resumo"]
    print(f"  SAS/Local: {_sl['x_nomes']} inputs por nome -> {_sl['y_fisicas']} tabelas fisicas distintas")
    # Só TABELA: desde que arquivo/script também publicam path, contar todas as categorias
    # aqui inflaria o indicador de homônimo de tabela (era 212, viraria 367) sem dizer isso.
    _homs = sum(1 for r in data["inputs"]
                if r["categoria"] == "tabela" and r["n_paths_fisicos"] > 1)
    print(f"  homonimos SAS/Local-tabela (n_paths_fisicos>1): {_homs}")
    _arq = [r for r in data["inputs"] if r["categoria"] in ("arquivo", "script")]
    _arq_ok = [r for r in _arq if r["n_paths_fisicos"] > 0]
    _arq_amb = [r for r in _arq if r["n_paths_fisicos"] > 1]
    print(f"  arquivo/script com path fisico: {len(_arq_ok)} de {len(_arq)}"
          + (f" ({100 * len(_arq_ok) // max(len(_arq), 1)}%)" if _arq else "")
          + f" · {len(_arq_amb)} em mais de uma pasta")
    # descarte NUNCA silencioso: um falso-positivo do guard de macro tem que aparecer aqui
    _md = data.get("macro_dropped") or []
    print(f"  file_in com macro nao expandida DESCARTADOS: {len(_md)}")
    for _a in _md[:8]:
        print(f"     - {_a}")
    if len(_md) > 8:
        print(f"     ... e mais {len(_md) - 8}")
    print("\n  amostra inputs:")
    for r in data["inputs"][:3]:
        print("   ", {k: r[k] for k in ("artifact", "categoria", "qtd_projetos", "escopo_indi", "modernizada_auto")})

    in_cols = ["chave_canonica", "artifact", "categoria", "origem", "source_types", "qtd_projetos",
               "areas", "escopo_indi", "modernizada_auto", "paths_fisicos", "n_paths_fisicos"]
    ed_cols = ["projeto_alvo", "depende_do", "via_tabelas", "qtd_via", "max_produtores"]
    nd_cols = ["projeto", "area", "onda", "n_inputs", "n_outputs", "escopo_indi", "ciclo_id",
               "loc", "code_tasks_count", "n_outputs_avaliados", "n_outputs_consumidos_por_outro_egp",
               "pct_outputs_consumidos_por_outro_egp", "n_egps_consumidores", "n_exports_arquivos",
               "flag_output_100pct_egp", "flag_algum_output_egp", "flag_sem_export_arquivo",
               "flag_output_unico", "flag_hub_multiplos_consumidores"]
    egp_cols = ["projeto", "area", "onda", "escopo_indi", "ciclo_id", "chave_canonica",
                "artifact", "categoria", "source_types", "modernizada_auto"]
    res_cols = ["chave_canonica", "area_principal", "origem_bucket", "escopo_indi", "modernizada_auto"]
    resp_cols = ["chave_canonica", "projeto"]
    fun_cols = ["area", "qtd_dor1", "egps_enviados", "egps_analisados"]
    esc_cols = ["id", "egp_dor1", "area", "status_extracao", "projeto", "origem", "created_by", "created_at"]
    mt_cols = ["captured_at", "escopo", "metric", "valor"]
    out_cols = ["chave_canonica", "artifact", "categoria", "areas", "qtd_produtores", "qtd_criadores",
                "qtd_consumidores", "terminal", "modernizada_auto", "escopo_indi", "paths_fisicos"]
    egp_out_cols = ["projeto", "area", "onda", "escopo_indi", "chave_canonica",
                    "artifact", "categoria", "apenas_contribui"]

    ddl = [
        f"CREATE SCHEMA IF NOT EXISTS {fq}",
        f"""CREATE TABLE IF NOT EXISTS {T_IN} (
  chave_canonica STRING, artifact STRING, categoria STRING, origem STRING, source_types STRING,
  qtd_projetos INT, areas STRING, escopo_indi BOOLEAN, modernizada_auto STRING,
  paths_fisicos STRING, n_paths_fisicos INT,
  status_humano STRING, etapa STRING, status STRING, responsavel STRING, observacao STRING,
  updated_at TIMESTAMP, updated_by STRING,
  orfao BOOLEAN, refreshed_at TIMESTAMP
) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {T_MT} (
  captured_at TIMESTAMP, escopo STRING, metric STRING, valor BIGINT
) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {T_AUD} (
  chave_canonica STRING, campo STRING, valor_antigo STRING, valor_novo STRING,
  updated_by STRING, updated_at TIMESTAMP
) USING DELTA""",
    ]

    if not args.apply:
        out = os.path.join(BASE, "docs", "analises", "publish_databricks.preview.sql")
        with open(out, "w", encoding="utf-8") as f:
            f.write(";\n\n".join(ddl) + ";\n")
            f.write(f"\n-- staging+merge de {T_IN}: {len(data['inputs'])} linhas (preview de 1 batch)\n")
            f.write(insert_batches(STG, in_cols, data["inputs"][:5])[0] + ";\n")
        print(f"\n[dry-run] DDL + amostra SQL → {out}")
        print("[dry-run] rode com --apply (após carregar o .env do converter) para escrever.")
        return

    # ---- APPLY ----
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
    except ImportError:
        print("ERRO: databricks-sdk não instalado no venv ativo.", file=sys.stderr)
        sys.exit(1)
    if not args.warehouse_id:
        print("ERRO: defina DATABRICKS_DEFAULT_WAREHOUSE_ID (carregue o .env do converter) ou use --warehouse-id.", file=sys.stderr)
        sys.exit(1)
    has_pat = bool(os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"))
    # oauth-m2m (service principal do app: DATABRICKS_CLIENT_ID/SECRET, HOST presente, sem TOKEN)
    has_m2m = bool(os.environ.get("DATABRICKS_CLIENT_ID") and os.environ.get("DATABRICKS_CLIENT_SECRET"))
    if not args.profile and not has_pat and not has_m2m:
        print("ERRO: auth ausente — defina DATABRICKS_HOST/TOKEN, DATABRICKS_CLIENT_ID/SECRET (oauth-m2m) ou passe --profile <perfil> do ~/.databrickscfg.", file=sys.stderr)
        sys.exit(1)

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    import time

    def run(sql):
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id,
            wait_timeout="50s", disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if (resp.status and resp.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:500]}")
        return resp

    def read_rows(sql):
        """run() + paginação dos chunks (INLINE devolve o 1º chunk; o resto vem por índice).
        Devolve lista de listas posicionais, na ordem das colunas do SELECT."""
        resp = run(sql)
        out, chunk = [], (resp.result if resp else None)
        while chunk is not None:
            out.extend(chunk.data_array or [])
            nxt = chunk.next_chunk_index
            if nxt is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(resp.statement_id, nxt)
        return out

    print("\n== APPLY ==")
    for d in ddl:
        run(d)
    print("  DDL ok (schema + inputs_monitor + metrics)")

    # CREATE IF NOT EXISTS não altera schema de tabela já existente em prod: garante a coluna origem
    try:
        run(f"SELECT origem FROM {T_IN} LIMIT 0")
    except Exception:
        run(f"ALTER TABLE {T_IN} ADD COLUMNS (origem STRING)")
        print("  coluna origem adicionada (ALTER) à tabela pré-existente")
    # idem para paths_fisicos/n_paths_fisicos (colunas DERIVADAS de resolução de path)
    try:
        run(f"SELECT paths_fisicos, n_paths_fisicos FROM {T_IN} LIMIT 0")
    except Exception:
        run(f"ALTER TABLE {T_IN} ADD COLUMNS (paths_fisicos STRING, n_paths_fisicos INT)")
        print("  colunas paths_fisicos/n_paths_fisicos adicionadas (ALTER) à tabela pré-existente")
    # idem para etapa/status (substituem status_humano — ver egps_analysis/scripts/
    # migrate_input_status_split.py p/ o backfill único dos dados legados)
    try:
        run(f"SELECT etapa, status FROM {T_IN} LIMIT 0")
    except Exception:
        run(f"ALTER TABLE {T_IN} ADD COLUMNS (etapa STRING, status STRING)")
        print("  colunas etapa/status adicionadas (ALTER) à tabela pré-existente")

    # staging full-replace + insert
    run(f"DROP TABLE IF EXISTS {STG}")
    run(f"""CREATE TABLE {STG} (
  chave_canonica STRING, artifact STRING, categoria STRING, origem STRING, source_types STRING,
  qtd_projetos INT, areas STRING, escopo_indi BOOLEAN, modernizada_auto STRING,
  paths_fisicos STRING, n_paths_fisicos INT
) USING DELTA""")
    batches = insert_batches(STG, in_cols, data["inputs"])
    for i, st in enumerate(batches, 1):
        run(st)
    print(f"  staging carregada: {len(data['inputs'])} linhas em {len(batches)} batches")

    run(f"""MERGE INTO {T_IN} t USING {STG} s ON t.chave_canonica = s.chave_canonica
WHEN MATCHED THEN UPDATE SET
  t.artifact=s.artifact, t.categoria=s.categoria, t.origem=s.origem, t.source_types=s.source_types,
  t.qtd_projetos=s.qtd_projetos, t.areas=s.areas, t.escopo_indi=s.escopo_indi,
  t.modernizada_auto=s.modernizada_auto, t.paths_fisicos=s.paths_fisicos,
  t.n_paths_fisicos=s.n_paths_fisicos, t.orfao=false, t.refreshed_at=current_timestamp()
WHEN NOT MATCHED THEN INSERT (
  chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, areas,
  escopo_indi, modernizada_auto, paths_fisicos, n_paths_fisicos, etapa, status, orfao, refreshed_at
) VALUES (
  s.chave_canonica, s.artifact, s.categoria, s.origem, s.source_types, s.qtd_projetos, s.areas,
  s.escopo_indi, s.modernizada_auto, s.paths_fisicos, s.n_paths_fisicos,
  CASE s.modernizada_auto WHEN 'Disponível' THEN 'Modernizado' ELSE 'A Receber' END,
  CASE s.modernizada_auto WHEN 'Disponível' THEN 'Concluído' ELSE 'A Iniciar' END,
  false, current_timestamp()
)""")
    run(f"UPDATE {T_IN} SET orfao=true WHERE chave_canonica NOT IN (SELECT chave_canonica FROM {STG})")
    run(f"DROP TABLE IF EXISTS {STG}")
    print("  MERGE ok (colunas humanas preservadas; órfãos marcados)")

    # edges / nodes — full replace
    run(f"DROP TABLE IF EXISTS {T_ED}")
    run(f"CREATE TABLE {T_ED} (projeto_alvo STRING, depende_do STRING, via_tabelas STRING, qtd_via INT, max_produtores INT) USING DELTA")
    for st in insert_batches(T_ED, ed_cols, data["edges"]):
        run(st)
    run(f"DROP TABLE IF EXISTS {T_ND}")
    run(f"""CREATE TABLE {T_ND} (projeto STRING, area STRING, onda STRING,
  n_inputs INT, n_outputs INT, escopo_indi BOOLEAN, ciclo_id INT,
  loc INT, code_tasks_count INT, n_outputs_avaliados INT,
  n_outputs_consumidos_por_outro_egp INT, pct_outputs_consumidos_por_outro_egp DOUBLE,
  n_egps_consumidores INT, n_exports_arquivos INT,
  flag_output_100pct_egp BOOLEAN, flag_algum_output_egp BOOLEAN,
  flag_sem_export_arquivo BOOLEAN, flag_output_unico BOOLEAN,
  flag_hub_multiplos_consumidores BOOLEAN) USING DELTA""")
    for st in insert_batches(T_ND, nd_cols, data["nodes"]):
        run(st)
    print(f"  lineage_edges ({len(data['edges'])}) + lineage_nodes ({len(data['nodes'])}) recriadas")

    # egp_inputs (grão projeto×input) — full replace
    run(f"DROP TABLE IF EXISTS {T_EGP}")
    run(f"""CREATE TABLE {T_EGP} (projeto STRING, area STRING, onda STRING, escopo_indi BOOLEAN,
  ciclo_id INT, chave_canonica STRING, artifact STRING, categoria STRING,
  source_types STRING, modernizada_auto STRING) USING DELTA""")
    for st in insert_batches(T_EGP, egp_cols, data["egp_inputs"]):
        run(st)
    print(f"  egp_inputs ({len(data['egp_inputs'])}) recriada")

    # outputs_monitor (grão output distinto) + egp_outputs (grão EGP×output) — full replace
    run(f"DROP TABLE IF EXISTS {T_OUT}")
    run(f"""CREATE TABLE {T_OUT} (chave_canonica STRING, artifact STRING, categoria STRING,
  areas STRING, qtd_produtores INT, qtd_criadores INT, qtd_consumidores INT, terminal BOOLEAN,
  modernizada_auto STRING, escopo_indi BOOLEAN, paths_fisicos STRING) USING DELTA""")
    for st in insert_batches(T_OUT, out_cols, data["outputs"]):
        run(st)
    run(f"DROP TABLE IF EXISTS {T_EGP_OUT}")
    run(f"""CREATE TABLE {T_EGP_OUT} (projeto STRING, area STRING, onda STRING,
  escopo_indi BOOLEAN, chave_canonica STRING, artifact STRING, categoria STRING, apenas_contribui BOOLEAN) USING DELTA""")
    for st in insert_batches(T_EGP_OUT, egp_out_cols, data["egp_outputs"]):
        run(st)
    print(f"  outputs: {len(data['outputs'])} distintos, {len(data['egp_outputs'])} pares EGP×output")

    # resumo_inputs + funil_area — full replace
    run(f"DROP TABLE IF EXISTS {T_RES}")
    run(f"""CREATE TABLE {T_RES} (chave_canonica STRING, area_principal STRING,
  origem_bucket STRING, escopo_indi BOOLEAN, modernizada_auto STRING) USING DELTA""")
    for st in insert_batches(T_RES, res_cols, data["resumo"]):
        run(st)
    run(f"DROP TABLE IF EXISTS {T_FUN}")
    run(f"""CREATE TABLE {T_FUN} (area STRING, qtd_dor1 INT,
  egps_enviados INT, egps_analisados INT) USING DELTA""")
    for st in insert_batches(T_FUN, fun_cols, data["funil"]):
        run(st)
    run(f"DROP TABLE IF EXISTS {T_RESP}")
    run(f"CREATE TABLE {T_RESP} (chave_canonica STRING, projeto STRING) USING DELTA")
    for st in insert_batches(T_RESP, resp_cols, data["resumo_proj"]):
        run(st)
    print(f"  resumo_inputs ({len(data['resumo'])}) + funil_area ({len(data['funil'])}) "
          f"+ resumo_proj ({len(data['resumo_proj'])}) recriadas")

    # escopo — tabela EDITAVEL persistente (semeada do CSV se vazia); NAO recriada (preserva edicoes)
    run(f"""CREATE TABLE IF NOT EXISTS {T_ESC} (id STRING, egp_dor1 STRING, area STRING,
  status_extracao STRING, projeto STRING, origem STRING, created_by STRING, created_at STRING) USING DELTA""")
    run(f"""CREATE TABLE IF NOT EXISTS {T_ESC_AUD} (id STRING, acao STRING, egp_dor1 STRING,
  projeto STRING, ator STRING, ts STRING) USING DELTA""")
    # pipeline de migração por EGP (funis da landing) — persistente, preserva edições
    run(f"""CREATE TABLE IF NOT EXISTS {fq}.sas_egp_pipeline (projeto STRING,
  etapa_migracao STRING, status_migracao STRING, etapa_progresso STRING, status_progresso STRING,
  updated_by STRING, updated_at STRING) USING DELTA""")
    run(f"""CREATE TABLE IF NOT EXISTS {fq}.sas_pipeline_audit (id STRING, projeto STRING,
  funil STRING, campo STRING, valor_antigo STRING, valor_novo STRING, ator STRING, ts STRING) USING DELTA""")
    _esc_da = run(f"SELECT count(*) AS n FROM {T_ESC}").result.data_array
    _n_esc = int(_esc_da[0][0]) if _esc_da else 0
    if _n_esc == 0:
        seed = [{"id": uuid.uuid4().hex, "egp_dor1": r["egp_dor1"], "area": r["area"],
                 "status_extracao": r["status_extracao"], "projeto": r["projeto"],
                 "origem": "csv", "created_by": "seed", "created_at": data["cap"]} for r in data["indicium"]]
        for st in insert_batches(T_ESC, esc_cols, seed):
            run(st)
        print(f"  escopo SEMEADO do CSV ({len(seed)} linhas)")
    else:
        print(f"  escopo preservado ({_n_esc} linhas; nao re-semeado)")

    # EGPs "casca": 1 linha em sas_escopo por casca ainda não cadastrada. NÃO é redundante
    # com o escopo_indi=True do nó — o recompute logo abaixo RESETA escopo_indi de todo nó
    # fora do sas_escopo, e sem esta linha a flag se apagaria sozinha no primeiro recompute
    # (achado 2026-09, §3.6 regra 24). Idempotente e sem ressuscitar soft-delete: a comparação
    # é contra TODOS os projetos da tabela, ativos ou não.
    _esc_projs = {r[0] for r in read_rows(f"SELECT projeto FROM {T_ESC}") if r and r[0]}
    _casca_esc = casca_escopo_rows(data["casca"], _esc_projs, data["cap"])
    if _casca_esc:
        for st in insert_batches(T_ESC, esc_cols, _casca_esc):
            run(st)
    print(f"  casca: {len(data['casca'])} EGP(s) sem inventário próprio "
          f"({len(_casca_esc)} nova(s) linha(s) em sas_escopo)")

    # ---- recompute escopo_indi + funil a partir de sas_escopo ----
    # Publish reconstrói escopo_indi a partir do `indi` do CSV; já o sas_escopo pode ter
    # edições manuais (add/remove). Esta etapa re-deriva escopo_indi (nodes/egp_inputs/
    # inputs_monitor/resumo) e o funil a partir do sas_escopo VIGENTE, para que as edições
    # sobrevivam ao republish. Espelha recompute_escopo() do backend (main.py) — mantenha
    # os dois conjuntos de statements idênticos.
    # sas_escopo pré-existente pode não ter a coluna ativo (soft-delete criado pelo app):
    try:
        run(f"SELECT ativo FROM {T_ESC} LIMIT 0")
    except Exception:
        run(f"ALTER TABLE {T_ESC} ADD COLUMNS (ativo BOOLEAN)")
        print("  coluna ativo adicionada (ALTER) ao sas_escopo pré-existente")
    # entradas DESATIVADAS (soft-delete do app) ficam fora do escopo e do funil — sem este
    # filtro, um republish ressuscitaria removidos (espelha recompute_escopo do main.py).
    esc = f"(SELECT projeto FROM {T_ESC} WHERE projeto <> '' AND ativo IS NOT false)"
    ch_egp = f"(SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE escopo_indi = true)"
    ch_res = f"(SELECT DISTINCT chave_canonica FROM {T_RESP} WHERE projeto IN {esc})"
    for s in [
        f"UPDATE {T_ND}  SET escopo_indi = false",
        f"UPDATE {T_ND}  SET escopo_indi = true WHERE projeto IN {esc}",
        f"UPDATE {T_EGP} SET escopo_indi = false",
        f"UPDATE {T_EGP} SET escopo_indi = true WHERE projeto IN {esc}",
        f"UPDATE {T_IN}  SET escopo_indi = false",
        f"UPDATE {T_IN}  SET escopo_indi = true WHERE chave_canonica IN {ch_egp}",
        f"UPDATE {T_RES} SET escopo_indi = false",
        f"UPDATE {T_RES} SET escopo_indi = true WHERE chave_canonica IN {ch_res}",
        # self-heal: entrada adicionada antes do EGP existir no corpus fica 'faltante' p/ sempre;
        # se o projeto agora está no grafo, promove a 'exato' (senão o funil por área subconta).
        f"UPDATE {T_ESC} SET status_extracao = 'exato' WHERE ativo IS NOT false "
        f"AND status_extracao = 'faltante' AND projeto <> '' AND projeto IN (SELECT projeto FROM {T_ND})",
        # funil: DELETE+INSERT (não CREATE OR REPLACE) p/ ficar dentro de MODIFY — usuários
        # OBO sem privilégio CREATE no schema falhariam, deixando o funil defasado.
        # A CASCA é um `extra` (§3.6.27): a linha dela em sas_escopo existe só p/ este
        # recompute não apagar o escopo_indi (regra 24) — fora do funil por área, senão a
        # Cobrança subiria +5 sem que nada tivesse sido migrado. Espelha SQL_ESC_NAO_EXTRA
        # do backend (main.py).
        f"DELETE FROM {T_FUN}",
        f"""INSERT INTO {T_FUN} (area, qtd_dor1, egps_enviados, egps_analisados)
  SELECT area, count(*),
    count_if(status_extracao <> 'faltante'),
    count_if(status_extracao IN ('exato','variante','confirmado_area','ingerido_extraido'))
  FROM {T_ESC} WHERE ativo IS NOT false AND coalesce(origem, '') <> 'casca' GROUP BY area""",
    ]:
        run(s)
    print("  escopo_indi + funil recomputados a partir de sas_escopo")

    # area_principal: 1 área/input LASTREADA no frontier (escopo ∪ dependências transitivas).
    # É lógica de grafo, então Python — não cabe no bloco SQL acima. DEPOIS do escopo_indi.
    # Sem este passo a coluna fica na regra fraca (ponte DOR1) e o funil por área
    # "+ dependências" do Resumo ganha uma linha "(sem área)". Ver recompute_area_principal.
    recompute_area_principal(run, read_rows, data, T_ND, T_IN, T_RES, f"{fq}.sas_egp_pipeline")

    # metrics — append
    for st in insert_batches(T_MT, mt_cols, data["metrics"]):
        run(st)
    print(f"  pipeline_metrics: +{len(data['metrics'])} linhas (snapshot {data['cap']})")

    # IDENTIDADE (ticket 25) — o publish é full-replace nas tabelas do corpus, e todo
    # colapso de alias aplicado à mão morre aqui. Medido em 29/09/2026: um republish desfez
    # os 101 colapsos de `sas_input_alias_canonico` sem uma linha de log, e o sintoma
    # chegou como "o escopo mudou de 1.237 p/ 1.251 e não sei por quê".
    #
    # Dois passos, nesta ordem: REAPLICA o que o mapa manda (com as duas recusas — alvo
    # ausente, alias com trabalho humano) e só então CONFERE. A guarda deixou de ser o
    # aviso e virou a prova: se ela ainda acusar, é porque algo foi recusado, e aí o
    # publish falha em vez de entregar números que ninguém sabe explicar.
    if not args.sem_reaplicar_identidade:
        aceitos, recusas = identidade_reaplica.reaplica(run, read_rows, fq)
        for linha in identidade_reaplica.relata(aceitos, recusas, True):
            print(linha)
    desfeitos, veredito = identidade_guard.checa_no_banco(read_rows, fq)
    for linha in identidade_guard._linha_de_saida(veredito, desfeitos):
        print(linha)
    # 2a invariante: colapso aplicado nao basta, as derivacoes tem de acompanhar.
    defasadas = identidade_guard.flags_defasadas(read_rows, fq)
    if defasadas:
        print(f"  ERRO DE IDENTIDADE: {len(defasadas)} chave(s) com escopo_indi defasado "
              f"em relacao aos pares que a leem — contam no balde errado.")
        for c in sorted(defasadas)[:8]:
            print(f"     {c}")
        veredito["ok"] = False
    if not veredito["ok"]:
        print("\n❌ PUBLISH concluiu a escrita, mas há decisões de identidade DESFEITAS que "
              "a reaplicação recusou — resolva-as antes de usar estes números.", file=sys.stderr)
        sys.exit(1)

    print("\n✅ PUBLISH concluído.")


if __name__ == "__main__":
    main()
