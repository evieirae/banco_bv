#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica EGPs Atualizados (versões novas enviadas pelo cliente) nas tabelas da aba
"EGPs Atualizados" do app — fora do publish geral, que nunca toca estas tabelas.

Conceitos (CONTEXT.md): cada carga é uma VERSÃO RECEBIDA (versao_id = <egp_key>@<data>),
versionada por append — o histórico nunca é sobrescrito; re-rodar a MESMA versao_id faz
DELETE+INSERT só daquela versão (idempotente). O EGP pode ter ANTECESSOR no corpus
(pareado por fingerprint via compare_egp_versions) ou ser INÉDITO (exige --area).

Isolamento é de ESCRITA, não de leitura (docs/adr/0001): este script escreve apenas em
sas_egp_atualizados / _inputs / _outputs; o snapshot do funil é lido ao vivo (read-only).

Uso (da pasta egps_analysis/, dry-run por padrão):
    venv/bin/python publish_egps_atualizados.py --novo "<pasta ou .egp>"
    venv/bin/python publish_egps_atualizados.py --novo novo.egp --antigo hint --apply
    venv/bin/python publish_egps_atualizados.py --novo inedito.egp --area "Cobranças" --apply

Guards: --apply para escrever; schema default é DEV (monitoramento_sas_dev); publicar em
monitoramento_sas (PROD) exige --prod-confirm.
"""
import argparse
import datetime
import hashlib
import os
import re
import sys
import zipfile
from collections import defaultdict

import compare_egp_versions as cev
import pipeline_status_snapshot as pss
# Regras de chave do pipeline atual — importadas da fonte de verdade para o JOIN vivo
# do app casar byte a byte (chave divergente = tudo "fora do corpus", falha silenciosa;
# ver docs/adr/0001). canon do publish preserva acentos (≠ cev.canon, que remove).
from publish_to_databricks import (
    IN_CATS, canon as pub_canon, eff_categoria, is_macro_artifact, is_noise_table,
    is_work_implicit, _memb_sas7,
)

PROD_SCHEMA = "monitoramento_sas"
DEFAULT_SCHEMA = "monitoramento_sas_dev"
DEFAULT_CATALOG = "bv_dev_db"

T_MAIN = "sas_egp_atualizados"
T_INPUTS = "sas_egp_atualizados_inputs"
T_OUTPUTS = "sas_egp_atualizados_outputs"

# Colunas de métrica copiadas 1:1 do resultado do compare (subset de COLUNAS_CSV que
# não é identidade/vínculo — esses têm tratamento próprio abaixo).
COLS_METRICA_INT = [
    'n_vetos',
    'table_in_antigo', 'table_in_novo', 'a_ingerir_antigo', 'a_ingerir_novo',
    'disponivel_antigo', 'disponivel_novo', 'file_in_antigo', 'file_in_novo',
    'script_in_antigo', 'script_in_novo', 'outputs_antigo', 'outputs_novo',
    'outputs_removidos_com_consumidor', 'outputs_removidos_privados',
    'inputs_macro_nao_resolvido', 'inputs_rede_novos', 'deps_novas',
    'loc_antigo', 'loc_novo', 'linhas_add', 'linhas_rem', 'tasks_novas',
    'alcance_total', 'alcance_por_grafo', 'alcance_por_output',
]
DDL = {
    T_MAIN: f"""
CREATE TABLE IF NOT EXISTS {{fq}}.{T_MAIN} (
    versao_id STRING NOT NULL,
    egp_key STRING,
    nome STRING,
    area STRING,
    arquivo STRING,
    arquivo_hash STRING,
    origem STRING,
    egp_original STRING,
    n_antecessores INT,
    confianca_par STRING,
    overlap_tasks DOUBLE,
    autor_ultimo_save STRING,
    login_autor STRING,
    data_ultimo_save STRING,
    data_criacao STRING,
    data_recebimento STRING,
    valor DOUBLE,
    esforco DOUBLE,
    razao DOUBLE,
    quadrante STRING,
    n_vetos INT,
    vetos STRING,
    alertas STRING,
    table_in_antigo INT, table_in_novo INT,
    a_ingerir_antigo INT, a_ingerir_novo INT,
    disponivel_antigo INT, disponivel_novo INT,
    file_in_antigo INT, file_in_novo INT,
    script_in_antigo INT, script_in_novo INT,
    outputs_antigo INT, outputs_novo INT,
    outputs_removidos_com_consumidor INT,
    outputs_removidos_privados INT,
    inputs_macro_nao_resolvido INT,
    inputs_rede_novos INT,
    deps_novas INT,
    loc_antigo INT, loc_novo INT,
    linhas_add INT, linhas_rem INT, tasks_novas INT,
    alcance_total INT, alcance_por_grafo INT, alcance_por_output INT,
    status_troca STRING,
    publicado_por STRING,
    publicado_em TIMESTAMP
) USING DELTA
""",
    T_INPUTS: f"""
CREATE TABLE IF NOT EXISTS {{fq}}.{T_INPUTS} (
    versao_id STRING NOT NULL,
    chave_canonica STRING,
    artefato STRING,
    categoria STRING,
    source STRING,
    situacao_no_recebimento STRING,
    novo BOOLEAN,
    publicado_em TIMESTAMP
) USING DELTA
""",
    T_OUTPUTS: f"""
CREATE TABLE IF NOT EXISTS {{fq}}.{T_OUTPUTS} (
    versao_id STRING NOT NULL,
    chave_canonica STRING,
    artefato STRING,
    situacao STRING,
    novo BOOLEAN,
    removido BOOLEAN,
    n_consumidores_externos INT,
    padrao BOOLEAN,
    categoria STRING,
    publicado_em TIMESTAMP
) USING DELTA
""",
}


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


def md5_arquivo(path: str) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def _ticks(v):
    """<ModifiedOn>/<CreatedOn> do project.xml são ticks .NET (100ns desde 0001-01-01)."""
    try:
        return (datetime.datetime(1, 1, 1)
                + datetime.timedelta(microseconds=int(v) / 10)).date().isoformat()
    except Exception:
        return None


def metadados_autor(egp_path: str) -> dict:
    """Autor/login/datas do último save, do cabeçalho UTF-16 do project.xml.
    Mesma leitura de docs/analises/gerar_fila_confirmacao_versao.py."""
    out = {'autor_ultimo_save': None, 'login_autor': None,
           'data_ultimo_save': None, 'data_criacao': None}
    try:
        bruto = zipfile.ZipFile(egp_path).read('project.xml')[:20000].decode('utf-16', 'ignore')
    except (KeyError, zipfile.BadZipFile, OSError) as e:
        # Sem log, um project.xml ausente/renomeado ou gravado em UTF-8 produzia uma
        # linha publicada com autor NULL — indistinguível de "o EGP realmente não tem
        # autor". E o autor é a chave do gate de confirmação de versão (contato é com
        # quem salvou por último, não com o coordenador), então perder isso em silêncio
        # trava a etapa seguinte sem ninguém entender por quê.
        print(f'  aviso: não li project.xml de {os.path.basename(egp_path)} '
              f'({type(e).__name__}: {e}) — autor/datas ficam vazios nesta versão',
              file=sys.stderr)
        return out
    def tag(t):
        m = re.search(rf'<{t}>([^<]*)</{t}>', bruto)
        return m.group(1).strip() if m else None
    out['autor_ultimo_save'] = tag('ModifiedBy')
    out['login_autor'] = tag('ModifiedByEGID')
    out['data_ultimo_save'] = _ticks(tag('ModifiedOn'))
    out['data_criacao'] = _ticks(tag('CreatedOn'))
    return out


def monta_linha(res: dict, data_recebimento: str, area_cli: str | None,
                origem: str) -> dict:
    """Resultado do compare -> linha de sas_egp_atualizados. Levanta ValueError se um
    EGP inédito/sem área chegar sem --area (fail-loud, decisão do grilling Q10)."""
    caminho = res['_egp_path']
    nome = os.path.splitext(os.path.basename(caminho))[0]
    area = (res.get('area') or '').strip() or (area_cli or '').strip()
    if not area:
        raise ValueError(
            f'"{os.path.basename(caminho)}" não tem área: sem antecessor no corpus '
            f'(quadrante: {res.get("quadrante")}) e sem --area. Informe --area.')

    inv = res.get('_inventarios') or {}
    projetos_antigos = inv.get('projetos_antigos') or []
    egp_key = f'{area}__{nome}'

    linha = {
        'versao_id': f'{egp_key}@{data_recebimento}',
        'egp_key': egp_key,
        'nome': nome,
        'area': area,
        'arquivo': os.path.basename(caminho),
        'arquivo_hash': md5_arquivo(caminho),
        'origem': origem or None,
        # egp_original = chaves de projeto dos antecessores quando o inventário resolveu;
        # senão o(s) basename(s) que o compare reporta. Vazio = inédito.
        'egp_original': (' + '.join(projetos_antigos) if projetos_antigos
                         else (res.get('egp_antigo') or None)),
        'n_antecessores': res.get('n_antecessores') or 0,
        'confianca_par': res.get('confianca_par'),
        'overlap_tasks': res.get('overlap_tasks'),
        'data_recebimento': data_recebimento,
        'valor': res.get('valor'),
        'esforco': res.get('esforco'),
        'razao': res.get('razao'),
        'quadrante': res.get('quadrante'),
        'vetos': res.get('vetos') or None,
        'alertas': res.get('alertas') or None,
        'status_troca': 'recebida',
    }
    linha.update(metadados_autor(caminho))
    for c in COLS_METRICA_INT:
        linha[c] = res.get(c)
    return linha


def monta_inventario(res: dict) -> tuple[list, list]:
    """_inventarios do compare -> linhas de _inputs e _outputs da versão recebida.

    chave_canonica segue a regra do pipeline atual (categoria::ARTEFATO upper, acentos
    preservados) para o JOIN vivo com sas_inputs_monitor/sas_outputs_monitor casar.
    situacao_no_recebimento congela a classificação do momento da carga (fallback do app
    para chave fora do corpus). `novo` = não existia no(s) antecessor(es); NULL p/ inédito
    (não há de quem herdar — "tudo novo" seria ruído, não informação).
    """
    inv = res.get('_inventarios') or {}
    inv_b, inv_a, cls_b = inv.get('novo'), inv.get('antigo'), inv.get('cls_novo') or {}
    versao_id = res['versao_id_calc']
    if not inv_b:
        # FAIL-LOUD (mesmo padrão do --area ausente em monta_linha). Antes devolvia
        # ([], []) e a LINHA PRINCIPAL era publicada assim mesmo: a versão aparecia no
        # app com n_inputs = 0, sem nenhum input ou output, indistinguível de um EGP
        # que realmente não lê nada. Quem não conseguiu ser lido tem de barrar a
        # publicação e aparecer na lista de erros, não virar uma linha plausível.
        raise ValueError(
            f'"{res.get("egp_novo")}" não tem inventário do lado novo '
            f'(quadrante: {res.get("quadrante")}) — o extrator não conseguiu ler o '
            f'.egp. Corrija a origem do arquivo; publicar geraria uma versão vazia.')

    tem_antecessor = inv_a is not None
    old_tabs = {cev.canon(i.get('table', '')) for i in (inv_a or {}).get('inputs', [])}
    old_files = {cev.canon(x) for x in (inv_a or {}).get('files_read', [])}
    old_scripts = {cev.canon(x) for x in (inv_a or {}).get('included_scripts', [])}
    disponiveis = cls_b.get('disponiveis') or set()

    # dedup .sas7bdat vs lib.membro do MESMO EGP (versão leve do _sas7bdat_dedup_members
    # do publish: sem libmap por projeto, colapsa por membro homônimo dentro da versão).
    membros_tab = {t.split('.')[-1].upper() for t in
                   (cev.canon(i.get('table', '')) for i in inv_b.get('inputs', [])) if t}

    # Descartes NUNCA silenciosos (mesmo princípio do macro_dropped em
    # publish_to_databricks.py). Vários filtros abaixo removem linhas por motivos
    # legítimos, mas um falso-positivo de qualquer um deles some sem deixar rastro —
    # e é exatamente assim que um input real desaparece da fila de ingestão.
    descartados = defaultdict(set)

    inputs = {}

    def add_input(cat_raw: str, art: str, source: str, novo_calc):
        art = (art or '').strip()
        if not art:
            return
        if cat_raw == 'table_in' and is_noise_table(art):
            descartados['ruido_tabela'].add(art)
            return
        if cat_raw == 'file_in' and is_macro_artifact(art):
            descartados['macro_nao_expandida'].add(art)
            return
        if cat_raw == 'file_in' and art.lower().endswith('.sas7bdat') \
                and _memb_sas7(art) in membros_tab:
            descartados['sas7bdat_ja_como_tabela'].add(art)
            return
        categoria = eff_categoria(cat_raw, art, IN_CATS)
        # Regra de chave do pipeline atual (observada em sas_inputs_monitor): tabela usa
        # o artefato inteiro; arquivo/script usam o BASENAME (o path fica em coluna
        # própria no monitor; aqui preservamos o caminho completo em `artefato`).
        base = art.replace('\\', '/').rsplit('/', 1)[-1] if categoria != 'tabela' else art
        chave = f'{categoria}::{pub_canon(base)}'
        if chave in inputs:
            # Para arquivo/script a chave é o BASENAME, então dois CAMINHOS distintos
            # com o mesmo nome de arquivo colapsam aqui — não é duplicata, é uma linha
            # diferente sumindo. Só conta como colisão real quando o artefato completo
            # difere do que já ocupava a chave.
            if inputs[chave]['artefato'] != art:
                descartados['colisao_por_basename'].add(
                    f"{art}  (já ocupado por {inputs[chave]['artefato']})")
            return
        if categoria == 'tabela':
            situacao = 'disponivel' if cev.canon(art) in disponiveis else 'a_ingerir'
        else:
            situacao = categoria  # arquivo | script (sem teste de modernização na carga)
        inputs[chave] = {
            'versao_id': versao_id, 'chave_canonica': chave, 'artefato': art,
            'categoria': categoria, 'source': source or None,
            'situacao_no_recebimento': situacao,
            'novo': novo_calc if tem_antecessor else None,
        }

    for i in inv_b.get('inputs', []):
        art = i.get('table', '')
        add_input('table_in', art, i.get('source', ''), cev.canon(art) not in old_tabs)
    for x in inv_b.get('files_read', []):
        add_input('file_in', x, '', cev.canon(x) not in old_files)
    for x in inv_b.get('included_scripts', []):
        add_input('script_in', x, '', cev.canon(x) not in old_scripts)

    # outputs: os da versão nova (novo = não existia no antecessor) + os REMOVIDOS
    # (existiam no antecessor e sumiram), com nº de consumidores externos do compare.
    # WORK implícita (`data X;` sem libname — temporária de sessão) fica FORA, como na
    # aba Outputs. Mas escrita QUALIFICADA com macro no nome (RENEG.RENEG_IMP_&SAFRA) é
    # tabela permanente REAL — o corpus a descarta como chave de monitoramento (decisão
    # b29c691a), porém escondê-la aqui fazia o EGP parecer "sem outputs" (caso
    # Reneg_Remunerav3_RPA). Ela entra com padrao=True (badge "padrão &macro" na tela).
    # `&` sem qualificação (PERFORMANCE_FINAL_&SAFRA, &DATA) segue fora: é WORK/macro-var.
    def _output_ruido(art: str) -> bool:
        if is_work_implicit(art):
            return True
        if '&' in art:
            return '.' not in art
        return is_noise_table(art)

    def _output_padrao(art: str) -> bool:
        return '&' in art and '.' in art

    outs = []
    vistos_out = set()
    for _x in inv_b.get('outputs', []):
        if _output_ruido(_x):
            descartados['output_ruido_novo'].add(_x)
    out_b_raw = [x for x in inv_b.get('outputs', []) if not _output_ruido(x)]
    out_b = {cev.canon(x) for x in out_b_raw}
    old_outs = {cev.canon(x) for x in (inv_a or {}).get('outputs', [])
                if not _output_ruido(x)}
    cons = inv.get('consumidores_externos_removidos') or {}
    for art in out_b_raw:
        k = cev.canon(art)
        if k in vistos_out:
            continue
        vistos_out.add(k)
        eh_novo = k not in old_outs
        outs.append({'versao_id': versao_id, 'chave_canonica': pub_canon(art),
                     'artefato': art,
                     'situacao': ('novo' if eh_novo else 'mantido') if tem_antecessor else 'novo_egp',
                     'novo': eh_novo if tem_antecessor else None,
                     'removido': False, 'n_consumidores_externos': None,
                     'padrao': _output_padrao(art), 'categoria': 'tabela'})
    if tem_antecessor:
        for art in inv_a.get('outputs', []):
            if _output_ruido(art):
                continue
            k = cev.canon(art)
            if k in out_b or k in vistos_out:
                continue
            vistos_out.add(k)
            outs.append({'versao_id': versao_id, 'chave_canonica': pub_canon(art),
                         'artefato': art, 'situacao': 'removido', 'novo': False,
                         'removido': True,
                         'n_consumidores_externos': cons.get(k),
                         'padrao': _output_padrao(art), 'categoria': 'tabela'})
    exp_b_raw = list(inv_b.get('exports', []))
    old_exps = {cev.canon(x) for x in (inv_a or {}).get('exports', [])}
    vistos_exp = set()

    def _exp_row(art, removido):
        base = art.replace('\\', '/').rsplit('/', 1)[-1]
        # SEM prefixo, igual aos outputs de tabela acima (pub_canon(art) puro): a
        # convenção do pipeline é chave_canonica PREFIXADA em inputs (`categoria::...`,
        # ver add_input) e PURA em outputs, para o JOIN com sas_outputs_monitor por
        # upper(artifact) casar. Um `arquivo::` aqui — só nesta linha, não nos outputs
        # de tabela — fazia todo output de arquivo exportado sumir desse JOIN em
        # silêncio.
        chave = pub_canon(base)
        if chave in vistos_exp:
            return None
        vistos_exp.add(chave)
        eh_novo = cev.canon(art) not in old_exps
        return {'versao_id': versao_id, 'chave_canonica': chave, 'artefato': art,
                'situacao': ('removido' if removido else
                             (('novo' if eh_novo else 'mantido') if tem_antecessor else 'novo_egp')),
                'novo': (False if removido else eh_novo) if tem_antecessor else None,
                'removido': removido, 'n_consumidores_externos': None,
                'padrao': '&' in art, 'categoria': 'arquivo'}

    exp_b = {cev.canon(x) for x in exp_b_raw}
    for art in exp_b_raw:
        r = _exp_row(art, removido=False)
        if r:
            outs.append(r)
    if tem_antecessor:
        for art in inv_a.get('exports', []):
            if cev.canon(art) in exp_b:
                continue
            r = _exp_row(art, removido=True)
            if r:
                outs.append(r)

    if descartados:
        res['_descartes'] = {k: sorted(v) for k, v in descartados.items() if v}
    return list(inputs.values()), outs


COLS_INPUTS = ['versao_id', 'chave_canonica', 'artefato', 'categoria', 'source',
               'situacao_no_recebimento', 'novo']
COLS_OUTPUTS = ['versao_id', 'chave_canonica', 'artefato', 'situacao', 'novo',
                'removido', 'n_consumidores_externos', 'padrao', 'categoria']


def _insert_lote(run, fq_tabela: str, cols: list, rows: list, lote=200):
    for i in range(0, len(rows), lote):
        values = ', '.join(
            '(' + ', '.join(sql_lit(r.get(c)) for c in cols) + ', current_timestamp())'
            for r in rows[i:i + lote])
        run(f'INSERT INTO {fq_tabela} ({", ".join(cols)}, publicado_em) VALUES {values}')


def publica(pacotes: list, fq: str, w, warehouse_id: str):
    """pacotes: [(linha, inputs, outputs)] — DELETE+INSERT por versao_id nas 3 tabelas."""
    def run(sql):
        return pss.query(w, sql, warehouse_id=warehouse_id)

    for t, ddl in DDL.items():
        run(ddl.format(fq=fq))
    # Mesmo padrão de publish_to_databricks.py: sonda a coluna com SELECT ... LIMIT 0
    # (aí sim engolindo a exceção — "não existe" é o único motivo esperado) e deixa o
    # ALTER TABLE propagar se falhar. Um `try/except Exception: pass` em volta do
    # próprio ALTER (como estava antes) engolia IGUAL um erro de permissão/timeout/
    # conflito de schema — sem log nenhum — e o INSERT que vem depois falhava mais
    # tarde com "coluna não encontrada", sem apontar a causa real.
    for cols_decl in ('padrao BOOLEAN', 'categoria STRING'):
        col_name = cols_decl.split()[0]
        try:
            run(f'SELECT {col_name} FROM {fq}.{T_OUTPUTS} LIMIT 0')
        except Exception:
            run(f'ALTER TABLE {fq}.{T_OUTPUTS} ADD COLUMNS ({cols_decl})')
            print(f'  coluna {col_name} adicionada (ALTER) à tabela pré-existente')

    cols = ['versao_id', 'egp_key', 'nome', 'area', 'arquivo', 'arquivo_hash', 'origem',
            'egp_original', 'n_antecessores', 'confianca_par', 'overlap_tasks',
            'autor_ultimo_save', 'login_autor', 'data_ultimo_save', 'data_criacao',
            'data_recebimento', 'valor', 'esforco', 'razao', 'quadrante',
            'vetos', 'alertas'] + COLS_METRICA_INT + ['status_troca']

    # DELETE+INSERT por VERSÃO, não em lote. Antes as 3 tabelas eram limpas de TODAS as
    # versões do lote de uma vez e só depois vinham os INSERTs: uma falha no 4º de 10
    # (timeout do warehouse, valor que quebra o INSERT) deixava as versões 5-10
    # APAGADAS e não reinseridas — some o que já estava publicado. Escopando por
    # versao_id, o estrago máximo é a versão corrente, e ela é nomeada no erro.
    publicadas = []
    for x, ins, outs in pacotes:
        vid = x['versao_id']
        vid_lit = sql_lit(vid)
        try:
            for t in (T_MAIN, T_INPUTS, T_OUTPUTS):
                run(f'DELETE FROM {fq}.{t} WHERE versao_id = {vid_lit}')
            valores = ', '.join(sql_lit(x.get(c)) for c in cols)
            run(f'INSERT INTO {fq}.{T_MAIN} ({", ".join(cols)}, publicado_por, publicado_em) '
                f'SELECT {valores}, current_user(), current_timestamp()')
            if ins:
                _insert_lote(run, f'{fq}.{T_INPUTS}', COLS_INPUTS, ins)
            if outs:
                _insert_lote(run, f'{fq}.{T_OUTPUTS}', COLS_OUTPUTS, outs)
        except Exception:
            print(f"\n!! FALHA publicando '{vid}'. Esta versão pode ter ficado "
                  f"INCOMPLETA em {fq} (apagada e não reinserida, ou com linha "
                  f"principal sem inputs/outputs) — republique-a.\n"
                  f"   Versões já publicadas OK neste lote: "
                  f"{', '.join(publicadas) if publicadas else '(nenhuma)'}",
                  file=sys.stderr)
            raise
        publicadas.append(vid)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--novo', required=True, help='.egp novo ou pasta com vários')
    ap.add_argument('--antigo', default=None,
                    help='hint(s) do(s) antecessor(es), como no compare (só com arquivo único)')
    ap.add_argument('--area', default=None,
                    help='área para EGP INÉDITO (sem antecessor não há de quem herdar)')
    ap.add_argument('--origem', default='', help='procedência do envio (ex.: pasta do SharePoint)')
    ap.add_argument('--data', default=None,
                    help='data de RECEBIMENTO usada no versao_id (YYYY-MM-DD; default hoje). '
                         'Re-rodar com a mesma data substitui a versão (idempotente); data '
                         'nova cria outra versão no histórico.')
    ap.add_argument('--catalog', default=DEFAULT_CATALOG)
    ap.add_argument('--schema', default=DEFAULT_SCHEMA)
    ap.add_argument('--warehouse-id', default=pss.WAREHOUSE_ID)
    ap.add_argument('--profile', default='bv')
    ap.add_argument('--corpus', default='received_egps')
    ap.add_argument('--src', default='src')
    ap.add_argument('--cache', default='.cache/egp_fingerprints.json')
    ap.add_argument('--snapshot-csv', default=None,
                    help='fallback: CSV do snapshot do funil em vez da busca ao vivo')
    ap.add_argument('--apply', action='store_true', help='sem esta flag é dry-run')
    ap.add_argument('--prod-confirm', action='store_true',
                    help=f'obrigatório para escrever no schema de PROD ({PROD_SCHEMA})')
    args = ap.parse_args()

    if args.schema == PROD_SCHEMA and args.apply and not args.prod_confirm:
        ap.error(f'--schema {PROD_SCHEMA} é PROD: escrever lá exige --prod-confirm')

    if os.path.isdir(args.novo):
        novos = sorted(os.path.join(args.novo, f) for f in os.listdir(args.novo)
                       if f.lower().endswith('.egp'))
        if args.antigo:
            ap.error('--antigo só faz sentido com --novo apontando para um arquivo')
    else:
        novos = [args.novo]
    if not novos:
        ap.error(f'nenhum .egp em {args.novo}')

    data_receb = args.data or datetime.date.today().isoformat()
    fq = f'{args.catalog}.{args.schema}'

    # Snapshot do funil ao vivo (read-only); CSV só como fallback explícito.
    if args.snapshot_csv:
        snapshot = args.snapshot_csv
    else:
        print(f'snapshot do funil ao vivo: {args.catalog}.{PROD_SCHEMA}.sas_egp_pipeline')
        _, snapshot = pss.busca_linhas(profile=args.profile,
                                       schema=f'{args.catalog}.{PROD_SCHEMA}')

    cmp_res = cev.comparar(novos, corpus_dir=args.corpus, src_dir=args.src,
                           snapshot=snapshot, antigo=args.antigo, cache=args.cache,
                           incluir_inventarios=True, verbose=True)

    # Reconciliação entrada -> saída: arquivo que não virou versão tem de aparecer.
    pulados = cmp_res.get('pulados') or []
    if pulados:
        print(f'\n!! {len(pulados)} arquivo(s) de entrada NÃO puderam ser lidos e '
              f'ficaram de fora:', file=sys.stderr)
        for cam, err in pulados:
            print(f'   - {os.path.basename(cam)}: {err}', file=sys.stderr)

    erros, pacotes = [], []
    descartes_por_versao = {}
    for res in cmp_res['resultados']:
        try:
            linha = monta_linha(res, data_receb, args.area, args.origem)
            res['versao_id_calc'] = linha['versao_id']
            ins, outs = monta_inventario(res)
        except ValueError as e:
            erros.append(str(e))
            continue
        if res.get('_descartes'):
            descartes_por_versao[linha['versao_id']] = res['_descartes']
        pacotes.append((linha, ins, outs))
    if erros:
        for e in erros:
            print(f'ERRO: {e}', file=sys.stderr)
        sys.exit(2)
    if not pacotes:
        print('nada a publicar (nenhum resultado da comparação)', file=sys.stderr)
        sys.exit(2)

    print(f'\nalvo: {fq} ({"APPLY" if args.apply else "DRY-RUN"})')
    for x, ins, outs in pacotes:
        score = (f' · V{x["valor"]} E{x["esforco"]}' if x.get('valor') is not None else '')
        n_rem = sum(1 for o in outs if o['removido'])
        print(f'  {x["versao_id"]}\n'
              f'    quadrante: {x["quadrante"]}{score} · antecessor: {x["egp_original"] or "(inédito)"}\n'
              f'    autor: {x["autor_ultimo_save"] or "?"} ({x["login_autor"] or "?"}) · '
              f'último save: {x["data_ultimo_save"] or "?"} · hash: {x["arquivo_hash"][:8]}\n'
              f'    inventário: {len(ins)} inputs · {len(outs)} outputs'
              + (f' ({n_rem} removido(s))' if n_rem else ''))
        # Descarte NUNCA silencioso (mesmo princípio do macro_dropped no publish
        # geral): os filtros de ruído/macro/dedup removem linha por motivo legítimo,
        # mas um falso-positivo some sem rastro — e é assim que um input real
        # desaparece da fila de ingestão.
        for motivo, itens in sorted((descartes_por_versao.get(x['versao_id']) or {}).items()):
            print(f'    descartados [{motivo}]: {len(itens)}')
            for it in itens[:5]:
                print(f'       - {it}')
            if len(itens) > 5:
                print(f'       ... e mais {len(itens) - 5}')

    if not args.apply:
        print('\ndry-run: nada foi escrito. Use --apply para publicar.')
        return

    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=args.profile)
    publica(pacotes, fq, w, args.warehouse_id)
    print(f'\npublicado: {len(pacotes)} versão(ões) em {fq}.{T_MAIN} '
          f'(DELETE+INSERT por versao_id — idempotente)')


if __name__ == '__main__':
    main()
