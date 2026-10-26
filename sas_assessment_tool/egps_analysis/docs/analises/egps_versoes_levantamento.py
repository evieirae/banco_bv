#!/usr/bin/env python3
"""Levantamento de EGPs que são versões diferentes do mesmo projeto.

Rodar de egps_analysis/:  python3 <este>/versoes.py

Fase 1  parse do inventário (text_egps/*.txt)
Fase 2  tokens de versão + normalização do nome -> base
Fase 3  agrupamento por nome (intra-área e entre áreas) + corroboração por conteúdo
Fase 4  evidências por membro (recência real do .egp, I/O, código)
Fase 5  eleição do canônico por critérios explicáveis
"""
import glob
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- fase 1

SEC_RE = {
    'ext_inputs': r'^EXTERNAL INPUTS \(Requires Ingestion\): (.*)$',
    'imp_files': r'^IMPORTED FILES \(Requires Ingestion\): (.*)$',
    'outputs': r'^PERMANENT OUTPUTS \(Target Marts\): (.*)$',
    'append_out': r'^APPEND_ONLY_OUTPUTS: (.*)$',
    'noncreator': r'^NON_CREATOR_OUTPUTS \(apensa/atualiza, nunca cria\): (.*)$',
    'exp_files': r'^EXPORTED FILES \(Artifacts\): (.*)$',
    'libnames': r'^DETECTED_LIBNAMES: (.*)$',
    'procs': r'^DETECTED_PROCS: (.*)$',
    'passthrough': r'^HAS_PASSTHROUGH: (.*)$',
    'loc': r'^LINES_OF_CODE: (.*)$',
    'tasks': r'^CODE_TASKS_COUNT: (.*)$',
    'arch': r'^TARGET_ARCH: (.*)$',
    'ext': r'^PROJECT_EXTENSION: (.*)$',
    'proj': r'^PROJECT: (.*)$',
    'conn': r'^CONNECTION_LIBS: (.*)$',
}


def _lst(v):
    if not v or v.strip() in ('(none)', ''):
        return []
    return [x.strip() for x in v.split(',') if x.strip()]


def parse_txt(path):
    raw = open(path, encoding='utf-8', errors='replace').read()
    d = {'txt': path}
    for key, pat in SEC_RE.items():
        m = re.search(pat, raw, re.M)
        d[key] = m.group(1).strip() if m else ''
    # corpo de código: tudo após o último separador de metadados
    i = raw.find('[[ FILE_REFS_MACRO ]]')
    body = raw[i:] if i > 0 else raw
    j = body.find('\n\n')
    d['code'] = body[j:] if j > 0 else body
    d['raw_len'] = len(raw)
    return d


def build_inventory():
    """Um registro por PROJECT. Vários .txt do mesmo PROJECT são TASKS do mesmo
    projeto (área Rodas exporta um .sas por nó do fluxo) — agregados, não versões."""
    agg = {}
    for f in sorted(glob.glob('text_egps/*.txt')):
        d = parse_txt(f)
        proj = d['proj']
        if not proj:
            continue
        area, _, stem = proj.partition('__')
        loc = int(re.sub(r'\D', '', d['loc']) or 0)
        tasks = int(re.sub(r'\D', '', d['tasks'].split('(')[0]) or 0)
        r = agg.get(proj)
        if r is None:
            r = agg[proj] = {
                'proj': proj, 'area': area, 'stem': stem, 'ext': d['ext'],
                'loc': 0, 'tasks': 0, 'n_txt': 0,
                'arch': d['arch'].split('(')[0].strip(),
                'inputs': set(), 'imp_files': set(), 'outputs': set(),
                'append_out': set(), 'noncreator': set(), 'exp_files': set(),
                'procs': set(), 'passthrough': False, 'conn': set(),
                'code': [], 'txts': [],
            }
        r['loc'] += loc
        r['tasks'] += tasks
        r['n_txt'] += 1
        r['inputs'] |= set(_lst(d['ext_inputs']))
        r['imp_files'] |= set(_lst(d['imp_files']))
        r['outputs'] |= set(_lst(d['outputs']))
        r['append_out'] |= set(_lst(d['append_out']))
        r['noncreator'] |= set(_lst(d['noncreator']))
        r['exp_files'] |= set(_lst(d['exp_files']))
        r['procs'] |= set(_lst(d['procs']))
        r['passthrough'] = r['passthrough'] or d['passthrough'].startswith('Yes')
        if d['conn'] and d['conn'] != '(none)':
            r['conn'].add(d['conn'])
        r['code'].append(d['code'])
        r['txts'].append(f)
    inv = []
    for r in agg.values():
        r['code'] = '\n'.join(r['code'])
        for k in ('inputs', 'imp_files', 'outputs', 'append_out', 'noncreator',
                  'exp_files', 'procs', 'conn'):
            r[k] = sorted(r[k])
        inv.append(r)
    return inv


# ---------------------------------------------------------------- fase 2
# tokens de versão. cada entrada: (nome, regex, extrator de ordinal)

MESES = {'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 'jul': 7,
         'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12,
         'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4, 'maio': 5,
         'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10,
         'novembro': 11, 'dezembro': 12}

RE_VNUM = re.compile(r'(?i)(?<![a-z0-9])_{0,2}v[\s._]?(\d{1,3})(?:[._](\d{1,3}))?(?![0-9])')
RE_VF = re.compile(r'(?i)(?<![a-z0-9])vf[\s._]?(\d{1,3})(?![0-9])')
RE_D8 = re.compile(r'(?<!\d)(20[12]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)')
RE_D6 = re.compile(r'(?<!\d)(20[12]\d)(0[1-9]|1[0-2])(?!\d)')
RE_MESANO = re.compile(r'(?i)(?<![a-z])(' + '|'.join(sorted(MESES, key=len, reverse=True)) + r')[\s._/-]?(?:de[\s._]?)?(20\d\d|\d\d)(?![\d])')
RE_ANO = re.compile(r'(?<!\d)(20[12]\d)(?!\d)')
RE_PAREN = re.compile(r'\(\s*(\d{1,2})\s*\)')
RE_TRAIL = re.compile(r'(?<=[\w\)])[-_ ](\d{1,2})\s*$')

# marcadores de estado (não ordinais)
MARK = {
    'copia': r'(?i)(?<![a-z])(c[oó]pia|copy)(?![a-z])',
    'teste': r'(?i)(?<![a-z])(teste|test|tst)(?![a-z])',
    'antigo': r'(?i)(?<![a-z])(antigo|antiga|old|bkp|backup|bak)(?![a-z])',
    'atual': r'(?i)(?<![a-z])(atual|atualizado|vigente)(?![a-z])',
    'final': r'(?i)(?<![a-z])(final|vf)(?![a-z])',
    'novo': r'(?i)(?<![a-z])(novo|nova|new)(?![a-z])',
    'gcp': r'(?i)(?<![a-z])(gcp|bq|bigquery)(?![a-z])',
    'rpa': r'(?i)(?<![a-z])(rpa|vaut|automatizad\w*)(?![a-z])',
}


def tokens(stem):
    """Extrai os ordinais e marcadores de versão de um nome."""
    t = {'vnum': None, 'vf': None, 'date': None, 'paren': None, 'trail': None,
         'marks': set()}
    vs = [tuple(int(g) for g in m.groups() if g) for m in RE_VNUM.finditer(stem)]
    if vs:
        t['vnum'] = max(vs)
    m = RE_VF.search(stem)
    if m:
        t['vf'] = int(m.group(1))
    dates = []
    for m in RE_D8.finditer(stem):
        dates.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in RE_D6.finditer(stem):
        dates.append((int(m.group(1)), int(m.group(2)), 0))
    for m in RE_MESANO.finditer(stem):
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        dates.append((y, MESES[m.group(1).lower()], 0))
    if not dates:
        for m in RE_ANO.finditer(stem):
            dates.append((int(m.group(1)), 0, 0))
    if dates:
        t['date'] = max(dates)
    m = RE_PAREN.search(stem)
    if m:
        t['paren'] = int(m.group(1))
    m = RE_TRAIL.search(stem)
    if m:
        t['trail'] = int(m.group(1))
    for name, pat in MARK.items():
        if re.search(pat, stem):
            t['marks'].add(name)
    return t


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


STRIP_PATS = [RE_VNUM, RE_VF, RE_D8, RE_D6, RE_MESANO, RE_PAREN, RE_TRAIL, RE_ANO] + \
    [re.compile(p) for p in MARK.values()]


def base_name(stem):
    """Normaliza o nome removendo tokens de versão -> chave de agrupamento."""
    s = stem
    for _ in range(3):
        for p in STRIP_PATS:
            s = p.sub(' ', s)
    s = strip_accents(s).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    s = re.sub(r'\s+', ' ', s)
    return s


# ---------------------------------------------------------------- fase 3

def shingles(code, k=5):
    toks = re.findall(r'[A-Za-z_][A-Za-z0-9_\.]*|\d+', code.upper())
    if len(toks) < k:
        return set()
    return {hash(tuple(toks[i:i + k])) for i in range(0, len(toks) - k + 1, 2)}


def jac(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    inv = build_inventory()
    print(f'[1] EGPs inventariados: {len(inv)}')

    zd = {}
    zp = os.path.join(OUT, 'zipdates.json')
    if os.path.exists(zp):
        zd = json.load(open(zp))
    # mapeia proj -> data do project.xml (último save real)
    def egp_saved(r):
        # acha o binario pelo stem
        for cand in (f"received_egps/{r['area']}/{r['stem']}.egp",):
            v = zd.get(cand)
            if v and v.get('projxml'):
                return tuple(v['projxml'])[:3], cand
        for k, v in zd.items():
            if os.path.basename(k)[:-4] == r['stem'] and v.get('projxml'):
                return tuple(v['projxml'])[:3], k
        return None, None

    for r in inv:
        r['tok'] = tokens(r['stem'])
        r['base'] = base_name(r['stem'])
        r['saved'], r['egp_path'] = egp_saved(r)
        r['sh'] = shingles(r['code'])
        r['out_set'] = {o.upper() for o in r['outputs']}
        r['in_set'] = {o.upper() for o in r['inputs']}

    print(f'[2] com data de save do .egp: {sum(1 for r in inv if r["saved"])}')

    # --- grupos por nome
    by_area = defaultdict(list)
    by_global = defaultdict(list)
    for r in inv:
        if r['base']:
            by_area[(r['area'], r['base'])].append(r)
            by_global[r['base']].append(r)

    g_intra = {k: v for k, v in by_area.items() if len(v) > 1}
    g_cross = {k: v for k, v in by_global.items()
               if len({r['area'] for r in v}) > 1}
    print(f'[3] grupos por nome: intra-área={len(g_intra)} '
          f'({sum(len(v) for v in g_intra.values())} EGPs) | '
          f'entre-áreas={len(g_cross)} ({sum(len(v) for v in g_cross.values())} EGPs)')

    # --- descoberta por conteúdo (independente do nome): pares com código muito similar
    #     só compara dentro de blocos plausíveis p/ não explodir O(n^2)
    pares = []
    idx = defaultdict(list)
    for r in inv:
        if len(r['sh']) < 20:
            continue
        # bucket por primeiras 3 letras do base + tamanho aproximado
        idx[r['base'][:4]].append(r)
        for o in list(r['out_set'])[:6]:
            idx['OUT:' + o].append(r)
    seen = set()
    for _, bucket in idx.items():
        if len(bucket) < 2 or len(bucket) > 60:
            continue
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, b = bucket[i], bucket[j]
                key = tuple(sorted((a['proj'], b['proj'])))
                if key in seen:
                    continue
                seen.add(key)
                s = jac(a['sh'], b['sh'])
                if s >= 0.35:
                    pares.append({'a': a['proj'], 'b': b['proj'], 'sim_codigo': round(s, 3),
                                  'sim_outputs': round(jac(a['out_set'], b['out_set']), 3),
                                  'sim_inputs': round(jac(a['in_set'], b['in_set']), 3),
                                  'mesmo_base': a['base'] == b['base'],
                                  'mesma_area': a['area'] == b['area']})
    print(f'[3b] pares com código >=35% similar: {len(pares)} '
          f'(dos quais {sum(1 for p in pares if not p["mesmo_base"])} NÃO tem nome-base igual)')

    json.dump(pares, open(os.path.join(OUT, 'pares_similares.json'), 'w'), ensure_ascii=False)
    slim = [{k: (list(v) if isinstance(v, set) else v) for k, v in r.items()
             if k not in ('code', 'sh')} for r in inv]
    json.dump(slim, open(os.path.join(OUT, 'inv_full.json'), 'w'), ensure_ascii=False, default=str)

    print('\n--- amostra de grupos intra-área (maiores) ---')
    for (area, base), v in sorted(g_intra.items(), key=lambda x: -len(x[1]))[:12]:
        print(f'  [{area}] "{base}" ({len(v)}):')
        for r in sorted(v, key=lambda r: r['stem']):
            sv = '-'.join(str(x) for x in r['saved']) if r['saved'] else 'sem .egp'
            print(f'      {r["stem"][:58]:60s} loc={r["loc"]:5d} out={len(r["outputs"]):3d} save={sv}')


if __name__ == '__main__':
    main()
