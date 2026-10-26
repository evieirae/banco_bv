#!/usr/bin/env python3
"""Fase 1 do Plano A: o dado do input chega a alguma SAÍDA do EGP?

Diferença para `descompacta_varredura.py` (18/08): lá o critério era de PROVENIÊNCIA —
o input só aparecia num `x cp`/`gunzip`, nunca num `SET`/`FROM`. Aqui o input É lido de
verdade, e a pergunta é de ALCANÇABILIDADE: seguindo o fluxo de dados dentro do EGP,
o conteúdo dele desemboca numa tabela permanente, num arquivo exportado ou num
relatório — ou morre num WORK que ninguém mais usa?

Grafo por EGP (nós = datasets, WORK incluso; arestas = passo que lê A e escreve B),
montado sobre o corpo do `.txt` com macros %let expandidas. Reaproveita o splitter de
passos e o expansor de macros de `auditoria_ordem_codigo.py`.

Sinks (o que conta como saída):
  perm         escrita em lib permanente (fora da WORK) — inclui INSERT INTO de pass-through
  arquivo      PROC EXPORT / OUTFILE= / DATA _NULL_ com FILE+PUT
  relatorio    PROC PRINT/REPORT/FREQ/MEANS/... sem OUT= — entregável de EGP consultivo

Vereditos por (EGP, input):
  ALCANCA_OUTPUT     chega a perm/arquivo/passthrough            -> manter
  SO_RELATORIO       só chega a relatório                        -> manter, revisar granularidade
  NAO_ALCANCA        é lido, mas o derivado é ponta solta        -> candidato a desvincular
  MACRO_NAO_CHAMADA  toda leitura está em %macro nunca invocada  -> candidato a desvincular
  NAO_LOCALIZADO     nome não aparece como nó (macro/wizard/%INCLUDE) -> fila manual

Regra de ouro: na dúvida, `usado`. Falso-positivo aqui tira input real da fila e a
primeira execução no destino quebra por tabela vazia (mesma assimetria do tier 3 do
estudo de 17/08).

    cd egps_analysis && . venv/bin/activate
    python docs/analises/alcancabilidade_inputs.py --egps /caminho/plano_egps.txt
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import auditoria_ordem_codigo as AO  # noqa: E402

WORK_LIBS = {'WORK', '_TEMP_'}
REPORT_PROCS = {'print', 'report', 'freq', 'means', 'summary', 'tabulate', 'univariate',
                'sgplot', 'sgpanel', 'gchart', 'gplot', 'corr', 'reg', 'compare',
                'contents', 'datasets', 'printto'}
FILE_PROCS = {'export'}

# LIB.MEMBER, MEMBER, ou nome totalmente qualificado de pass-through
# (`BV-PDBD-PRD.DVRY_CORE.TBCONTRATO` — 3 partes, com hifen e backtick).
NAME_RE = re.compile(r'^[A-Z_][A-Z0-9_-]*(?:\.[A-Z_][A-Z0-9_-]*){0,3}$')
W_DATA = re.compile(r'(?is)^\s*data\s+([^;]*);')
W_CREATE = re.compile(r'(?is)\bcreate\s+(?:table|view)\s+([\w.&`-]+)')
W_OUT = re.compile(r'(?i)\bout\s*=\s*([\w.&]+)')
W_BASE = re.compile(r'(?i)\bbase\s*=\s*([\w.&]+)')
W_INSERT = re.compile(r'(?i)\binsert\s+into\s+([\w.&`-]+)')
R_SETLIKE = re.compile(r'(?is)\b(?:set|merge|modify|update)\s+([^;]*);')
# (?!connection\s+to) descarta so o proprio match; o resto do passo de
# pass-through segue lido -- e onde estao as tabelas BQ/Sybase reais.
R_FROMJOIN = re.compile(r'(?i)\b(?:from|join)\s+(?!connection\s+to\b)([\w.&`-]+)')
R_DATAEQ = re.compile(r'(?i)\bdata\s*=\s*([\w.&]+)')
FILE_SINK = re.compile(r'(?i)\b(outfile\s*=|ods\s+(?:csv|excel|tagsets|html|pdf|rtf))')
NULL_FILE = re.compile(r'(?is)\bfile\s+[^;]*;.*?\bput\b')
# O conteúdo do input pode sair por MACRO-VARIÁVEL (CALL SYMPUT / SELECT INTO :var) e
# parametrizar todo o resto do fluxo — `DATA _NULL_; SET X; CALL SYMPUT(...)` não escreve
# dataset nenhum, mas está longe de ser leitura morta. Sink próprio.
MACRO_SINK = re.compile(r'(?i)\b(call\s+symput|call\s+symputx|into\s*:)')
# SASHELP.V* são views de dicionário do SAS (metadado da sessão), não dado de negócio.
META_LIBS = ('SASHELP.', 'DICTIONARY.')


def norm(tok):
    """token -> (chave canônica, resolvido?). WORK implícita para nome só-membro."""
    t = (tok or '').strip().strip(',').upper()
    t = t.replace('`', '')                       # BQ quoting
    t = re.sub(r'\(.*$', '', t).strip()          # opções de dataset
    t = t.rstrip('.').strip()
    if not t or t in ('_NULL_', '_LAST_', '_DATA_'):
        return None, True
    if '/' in t or '\\' in t or "'" in t or '"' in t:
        return None, True
    if '&' in t:
        return t, False                           # nome só existe via macro não resolvida
    if not NAME_RE.match(t):
        return None, True
    return (t if '.' in t else 'WORK.' + t), True


def _tokens(blob):
    """lista de datasets num `SET a b c(keep=..)` / `DATA a b;`"""
    blob = re.sub(r'\(([^()]|\([^()]*\))*\)', ' ', blob)   # remove opções
    out = []
    for raw in re.split(r'[\s,]+', blob):
        if not raw or '=' in raw:
            continue
        out.append(raw)
    return out


# `_passos` de auditoria_ordem_codigo.py corta só em início de LINHA. Um `data`/`proc`
# depois de `;` na mesma linha (idioma comum em corpo de %macro) era absorvido no passo
# anterior — e, se o anterior fosse `proc sql`, o `SET` dele nem era lido, produzindo
# input "morto" que na verdade alimenta a cadeia (9% dos candidatos na auditoria de
# 21/08). Splitter local; `_passos` fica intocado porque outras análises dependem dele.
_STEP_START = re.compile(r'(?im)(?:^|;)[^\S\n]*(data\s|proc\s+\w+)')


def passos(code):
    marks = [(m.start(1), m.group(1).lower().strip()) for m in _STEP_START.finditer(code)]
    for n, (pos, kind) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(code)
        yield pos, kind, code[pos:end]


def steps(code):
    """[{kind, pos, reads, writes, sinks, unresolved, snippet}] para um EGP."""
    res = []
    for pos, kind, blk in passos(code):
        reads, writes, sinks = set(), set(), set()
        unres_r, unres_w = set(), set()

        def add(target, tok):
            k, ok = norm(tok)
            if k is None:
                return
            if ok:
                target.add(k)
            else:
                # destino/origem só existe resolvido em runtime: registrado à parte para
                # o veredito não afirmar "morre aqui" quando o rastro apenas se perde.
                (unres_w if target is writes else unres_r).add(k)

        is_data = kind.startswith('data')
        proc = None if is_data else kind.split()[-1].lower()
        body = blk
        if is_data:
            m = W_DATA.match(blk)
            if m:
                for t in _tokens(m.group(1)):
                    add(writes, t)
                body = blk[len(m.group(0)):]
            for m in R_SETLIKE.finditer(body):
                for t in _tokens(m.group(1)):
                    add(reads, t)
            if NULL_FILE.search(blk) and not writes:
                sinks.add('arquivo')
        else:
            for m in R_DATAEQ.finditer(blk):
                add(reads, m.group(1))
            for m in W_BASE.finditer(blk):
                add(writes, m.group(1))
            for m in W_OUT.finditer(blk):
                add(writes, m.group(1))
            if proc in FILE_PROCS or FILE_SINK.search(blk):
                sinks.add('arquivo')
            if proc in REPORT_PROCS and not W_OUT.search(blk):
                sinks.add('relatorio')
        # PROC SQL e afins (valem para os dois ramos)
        for m in W_CREATE.finditer(blk):
            add(writes, m.group(1))
        for m in W_INSERT.finditer(blk):
            add(writes, m.group(1))
        for m in R_FROMJOIN.finditer(blk):
            add(reads, m.group(1))
        if any(not w.startswith('WORK.') for w in writes):
            sinks.add('perm')
        if unres_w:
            sinks.add('incerto')
        if MACRO_SINK.search(blk):
            sinks.add('macro_var')
        res.append({'kind': kind, 'pos': pos, 'reads': reads, 'writes': writes,
                    'sinks': sinks, 'unresolved': unres_r | unres_w,
                    'snippet': re.sub(r'\s+', ' ', blk[:160]).strip()})
    return res


def macros_nao_chamadas(code):
    """[(nome, ini, fim)] de %macro cujo %nome não aparece fora da própria definição."""
    out = []
    for m in re.finditer(r'(?is)%macro\s+(\w+)[^;]*;', code):
        nome = m.group(1)
        fim = re.search(r'(?is)%mend\b[^;]*;', code[m.end():])
        stop = m.end() + fim.end() if fim else len(code)
        rx = re.compile(r'(?i)%' + re.escape(nome) + r'\b')
        chamada = any(mm.start() < m.start() or mm.start() >= stop
                      for mm in rx.finditer(code))
        if not chamada:
            out.append((nome, m.start(), stop))
    return out


def reach_map(sts):
    """nó -> sinks alcançáveis, por PONTO-FIXO.

    Memoização com guarda de ciclo cacheia resultado PARCIAL (o valor depende de quem
    entrou primeiro na pilha) — em EGP com acumulador `DATA X; SET X;` isso dava input
    "morto" que na verdade alcança output. Iteração de Kleene até estabilizar é
    ordem-independente e converge: o reticulado é finito (4 sinks) e monótono.
    """
    por_leitura = collections.defaultdict(list)
    for i, s in enumerate(sts):
        for r in s['reads']:
            por_leitura[r].append(i)
    reach = collections.defaultdict(set)
    for _ in range(200):
        mudou = False
        for node, idxs in por_leitura.items():
            acc = set()
            for i in idxs:
                acc |= sts[i]['sinks']
                for w in sts[i]['writes']:
                    if w != node:
                        acc |= reach[w]
            if acc - reach[node]:
                reach[node] |= acc
                mudou = True
        if not mudou:
            break
    return (lambda n: reach[n]), por_leitura


def veredito(input_key, sts, reach, por_leitura, macros_mortas, egp_sem_output):
    if input_key not in por_leitura:
        return 'NAO_LOCALIZADO', 'nome não aparece como leitura no corpo (macro/wizard/%INCLUDE)'
    if input_key.startswith(META_LIBS):
        return 'METADADO_SAS', 'view de dicionário do SAS, não é dado de negócio'
    if egp_sem_output:
        # o EGP inteiro não declara output permanente nem arquivo: a pergunta deixa de
        # ser sobre o input e passa a ser sobre o EGP (consultivo? entrega na tela?).
        return 'EGP_SEM_OUTPUT', 'EGP não declara nenhum output permanente nem arquivo'
    pos = [sts[i]['pos'] for i in por_leitura[input_key]]
    if macros_mortas and all(any(a <= p < b for _, a, b in macros_mortas) for p in pos):
        nomes = sorted({n for n, a, b in macros_mortas if any(a <= p < b for p in pos)})
        return 'MACRO_NAO_CHAMADA', 'leituras só dentro de %' + ', %'.join(nomes[:3])
    sinks = reach(input_key)
    if sinks & {'perm', 'arquivo'}:
        return 'ALCANCA_OUTPUT', '+'.join(sorted(sinks))
    if 'relatorio' in sinks:
        return 'SO_RELATORIO', 'só desemboca em proc de relatório'
    if 'macro_var' in sinks:
        return 'ALIMENTA_MACRO_VARIAVEL', 'conteúdo sai por CALL SYMPUT/INTO : e parametriza o fluxo'
    if 'incerto' in sinks:
        return 'NAO_DECIDIVEL_MACRO', 'derivado é escrito em destino que só existe via macro'
    ev = sts[por_leitura[input_key][0]]['snippet']
    return 'NAO_ALCANCA', ev[:120]


def egps_sem_output(txt_dir='text_egps'):
    """PROJECTs cujo cabeçalho não declara output permanente nem arquivo exportado.
    O cabeçalho é a autoridade (nomes já resolvidos por %let no extractor); o grafo
    local não decide isso porque destino via macro pode escapar da regex."""
    sem = set()
    for f in sorted(glob.glob(os.path.join(txt_dir, '*.txt'))):
        proj = po = ef = None
        with open(f, encoding='utf-8', errors='replace') as fh:
            for ln in fh:
                if ln.startswith('END_METADATA'):
                    break
                if ln.startswith('PROJECT: '):
                    proj = ln[9:].strip()
                elif ln.startswith('PERMANENT OUTPUTS'):
                    po = ln.split(':', 1)[1].strip()
                elif ln.startswith('EXPORTED FILES'):
                    ef = ln.split(':', 1)[1].strip()
        vazio = {None, '', '(none)'}
        if proj and po in vazio and ef in vazio:
            sem.add(proj)
    return sem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--egps', help='arquivo com um PROJECT por linha (recorte do plano)')
    ap.add_argument('--inventario', default='06_prontidao_tabela.csv')
    ap.add_argument('--out', default='/tmp/alcancabilidade_inputs.csv')
    args = ap.parse_args()

    recorte = None
    if args.egps:
        recorte = {l.strip() for l in open(args.egps, encoding='utf-8') if l.strip()}
        print(f'[recorte] {len(recorte)} EGPs')

    pares = collections.defaultdict(set)      # project -> {artifact}
    n_file_in = 0
    with open(args.inventario, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            proj, art, cat = r['project'].strip(), r['artifact'].strip(), r['category'].strip()
            if recorte is not None and proj not in recorte:
                continue
            if cat == 'file_in':
                n_file_in += 1
            if cat != 'table_in' or not art or '.' not in art:
                continue
            pares[proj].add(art)
    print(f'[inventario] {sum(len(v) for v in pares.values())} pares (EGP x table_in) '
          f'em {len(pares)} EGPs | file_in no recorte: {n_file_in}')

    CODE = AO.carrega_codigo()
    print(f'[codigo] {len(CODE)} EGPs com corpo carregado')
    SEM_OUT = egps_sem_output()
    print(f'[cabecalho] {len(SEM_OUT)} EGPs sem output permanente nem arquivo (corpus)')

    linhas, dist = [], collections.Counter()
    por_egp = {}
    sem_codigo = 0
    for proj in sorted(pares):
        raw = CODE.get(proj)
        if not raw:
            sem_codigo += len(pares[proj])
            for art in sorted(pares[proj]):
                linhas.append({'egp': proj, 'input': art, 'veredito': 'SEM_CODIGO',
                               'evidencia': 'EGP sem .txt correspondente'})
                dist['SEM_CODIGO'] += 1
            continue
        code = AO.expande_macros(raw)
        sts = steps(code)
        reach, por_leitura = reach_map(sts)
        mortas = macros_nao_chamadas(code)
        sem_out = proj in SEM_OUT
        for art in sorted(pares[proj]):
            key, ok = norm(art)
            if key is None or not ok:
                vd, ev = 'NAO_LOCALIZADO', 'nome do inventário não resolve (macro)'
            else:
                vd, ev = veredito(key, sts, reach, por_leitura, mortas, sem_out)
            linhas.append({'egp': proj, 'input': art, 'veredito': vd, 'evidencia': ev})
            dist[vd] += 1
        vs = collections.Counter(l['veredito'] for l in linhas if l['egp'] == proj)
        alc = vs['ALCANCA_OUTPUT'] + vs['SO_RELATORIO']
        nao = vs['NAO_ALCANCA']
        por_egp[proj] = {
            'egp': proj, 'n_inputs': sum(vs.values()), 'alcanca': alc, 'nao_alcanca': nao,
            # cobertura só sobre o decidível: NAO_LOCALIZADO/MACRO ficam fora do denominador
            'cobertura': round(alc / (alc + nao), 3) if alc + nao else '',
            'egp_sem_output': int(sem_out), 'n_passos': len(sts),
            'nao_localizado': vs['NAO_LOCALIZADO'], 'nao_decidivel': vs['NAO_DECIDIVEL_MACRO'],
        }

    # splitext, não replace: `replace('.csv', ...)` troca TODA ocorrência (um diretório
    # com '.csv' no nome corrompia o caminho) e, se --out não terminasse em .csv,
    # out_egp ficava IGUAL a args.out — o relatório por EGP era então sobrescrito pelo
    # por par, sem erro nenhum.
    _raiz, _ext = os.path.splitext(args.out)
    out_egp = f'{_raiz}_por_egp{_ext or ".csv"}'
    with open(out_egp, 'w', encoding='utf-8', newline='') as f:
        cols = ['egp', 'n_inputs', 'alcanca', 'nao_alcanca', 'cobertura', 'egp_sem_output',
                'n_passos', 'nao_localizado', 'nao_decidivel']
        w = csv.DictWriter(f, fieldnames=cols, delimiter=';')
        w.writeheader()
        w.writerows([por_egp[k] for k in sorted(por_egp)])

    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['egp', 'input', 'veredito', 'evidencia'],
                           delimiter=';')
        w.writeheader()
        w.writerows(linhas)

    tot = sum(dist.values())
    print(f'\n[distribuicao] {tot} pares (EGP x input)')
    for k, v in dist.most_common():
        print(f'  {v:6d}  {v/tot*100:5.1f}%  {k}')
    # Partição por cobertura do EGP: input morto num EGP que comprovadamente produz
    # (cobertura alta) é candidato real; num EGP cuja cadeia toda morre em WORK a
    # pergunta é sobre o EGP, não sobre o input.
    faixas = [('100%', 1.0, 1.01), ('80-99%', 0.8, 1.0), ('50-79%', 0.5, 0.8),
              ('1-49%', 0.001, 0.5), ('0% (nada alcança)', -0.1, 0.001)]
    print('\n[particao por cobertura do EGP]')
    print(f'  {"faixa":20s} {"EGPs":>5s} {"pares NAO_ALCANCA":>18s}')
    for nome, lo, hi in faixas:
        sel = [v for v in por_egp.values()
               if v['cobertura'] != '' and lo <= v['cobertura'] < hi]
        print(f'  {nome:20s} {len(sel):5d} {sum(v["nao_alcanca"] for v in sel):18d}')
    reais = [v for v in por_egp.values()
             if v['cobertura'] != '' and v['cobertura'] >= 0.8 and v['nao_alcanca']]
    print(f'\n[candidatos reais] {sum(v["nao_alcanca"] for v in reais)} pares em '
          f'{len(reais)} EGPs com cobertura >= 80%')
    for v in sorted(reais, key=lambda x: -x['nao_alcanca'])[:15]:
        print(f'  {v["nao_alcanca"]:4d}/{v["n_inputs"]:4d}  cob={v["cobertura"]:.0%}  {v["egp"]}')
    print(f'\n[csv] {args.out}\n[csv] {out_egp}')


if __name__ == '__main__':
    main()
