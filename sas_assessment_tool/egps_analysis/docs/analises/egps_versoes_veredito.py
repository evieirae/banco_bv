#!/usr/bin/env python3
"""Fases 4-6: evidências, eleição do canônico e relatório.

Rodar de egps_analysis/:  python3 <scratch>/relatorio.py
Depende de versoes.py (mesma pasta) e de zipdates.json + prod.json já gerados.
"""
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from versoes import (build_inventory, tokens, base_name, shingles, jac)  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
HOJE = '2026-08-13'

RE_COLETA = re.compile(r'__v(\d+)$')        # sufixo de coleta (dois underscores, no fim)


def sha(path, cap=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def load_prod():
    p = json.load(open(os.path.join(OUT, 'prod.json')))
    esc = {r['projeto']: bool(r['escopo_indi']) for r in p['nodes']}
    pipe = {r['projeto']: r for r in p['pipe']}
    choice_of = {}
    for r in p['choice']:
        choice_of.setdefault(r['projeto_escolhido'], []).append(r['chave_canonica'])
    prod_n = {r['projeto'] for r in p['nodes']}
    as_prod = defaultdict(set)
    as_cons = defaultdict(set)
    for e in p['edges']:
        as_prod[e['depende_do']].add(e['projeto_alvo'])
        as_cons[e['projeto_alvo']].add(e['depende_do'])
    return esc, pipe, choice_of, prod_n, as_prod, as_cons


def subcluster(members, thr=0.60):
    """Single-linkage por similaridade de código -> separa linhagens distintas
    que a normalização de nome juntou."""
    n = len(members)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    sims = {}
    for i in range(n):
        for j in range(i + 1, n):
            s = jac(members[i]['sh'], members[j]['sh'])
            sims[(i, j)] = s
            if s >= thr:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    cl = defaultdict(list)
    for i in range(n):
        cl[find(i)].append(members[i])
    return list(cl.values()), sims


def ordinal(r):
    """Ordinal comparável extraído do nome (maior = mais novo), ignorando o
    sufixo de coleta __vN, que não é versão do analista."""
    t = tokens(RE_COLETA.sub('', r['stem']))
    return (t['date'] or (0, 0, 0), t['vnum'] or (0,), t['vf'] or 0,
            t['paren'] or 0, t['trail'] or 0)


AREAS_ESPURIAS = {'Teste EGPs'}


def decidir(members, esc, pipe, choice_of, as_prod):
    """Elege o canônico por cascata explicável. Devolve (canonico, motivos, conflitos)."""
    motivos, conflitos = [], []
    elig = list(members)

    # C0 — área espúria (pasta de teste da coleta) nunca é a dona do projeto
    esp = [m for m in elig if m['area'] in AREAS_ESPURIAS]
    if esp and len(esp) < len(elig):
        elig = [m for m in elig if m not in esp]
        motivos.append('C0 descarta cópia em área de teste da coleta')

    # C1 — marcadores desclassificatórios (só se sobrar alguém)
    desc = [m for m in elig if m['tok']['marks'] & {'copia', 'teste', 'antigo'}]
    if desc and len(desc) < len(elig):
        elig = [m for m in elig if m not in desc]
        motivos.append('C1 descarta por marcador no nome (' +
                       ', '.join(sorted({x for m in desc for x in m['tok']['marks'] &
                                         {'copia', 'teste', 'antigo'}})) + ')')

    # C2 — marcador de vigência promove
    vig = [m for m in elig if m['tok']['marks'] & {'atual'}]
    if vig and len(vig) < len(elig):
        elig = vig
        motivos.append('C2 nome declara vigência (ATUAL/vigente)')

    # C3 — ordinal do nome (versão/data explícita do analista)
    ords = {m['proj']: ordinal(m) for m in elig}
    if len(set(ords.values())) > 1:
        top = max(ords.values())
        cand = [m for m in elig if ords[m['proj']] == top]
        if len(cand) < len(elig):
            elig = cand
            motivos.append('C3 maior versão/data no nome')

    # C4 — recência real (project.xml do .egp)
    dated = [m for m in elig if m['saved']]
    if len(dated) > 1 and len({m['saved'] for m in dated}) > 1:
        top = max(m['saved'] for m in dated)
        cand = [m for m in dated if m['saved'] == top]
        if len(cand) < len(elig):
            elig = cand
            motivos.append('C4 save mais recente do .egp')
    elif len(dated) == 1 and len(elig) > 1:
        elig = dated
        motivos.append('C4 único com .egp datado')

    # C5 — operacional: escopo / pipeline / produtor canônico
    if len(elig) > 1:
        def op(m):
            return (1 if choice_of.get(m['proj']) else 0,
                    1 if esc.get(m['proj']) else 0,
                    1 if (pipe.get(m['proj']) or {}).get('etapa_migracao') else 0,
                    len(as_prod.get(m['proj'], ())))
        top = max(op(m) for m in elig)
        if top != (0, 0, 0, 0):
            cand = [m for m in elig if op(m) == top]
            if len(cand) < len(elig):
                elig = cand
                motivos.append('C5 sinal operacional (escopo/pipeline/produtor canônico)')

    # C6 — superconjunto funcional
    if len(elig) > 1:
        top = max((len(m['outputs']), m['loc'], m['tasks']) for m in elig)
        cand = [m for m in elig if (len(m['outputs']), m['loc'], m['tasks']) == top]
        if len(cand) < len(elig):
            elig = cand
            motivos.append('C6 superconjunto funcional (mais outputs/linhas)')

    canon = sorted(elig, key=lambda m: m['proj'])[0]

    # --- conflitos: sinais que apontam para outro membro
    if len(members) > 1:
        dated = [m for m in members if m['saved']]
        if dated:
            newest = max(dated, key=lambda m: m['saved'])
            if newest is not canon and newest['saved'] > (canon['saved'] or (0, 0, 0)):
                conflitos.append(f'save mais recente é de {newest["stem"]} '
                                 f'({"-".join(map(str, newest["saved"]))})')
        for m in members:
            if m is canon:
                continue
            if esc.get(m['proj']) and not esc.get(canon['proj']):
                conflitos.append(f'{m["stem"]} está no escopo Indicium e o eleito não')
            if choice_of.get(m['proj']) and not choice_of.get(canon['proj']):
                conflitos.append(f'{m["stem"]} é produtor canônico de '
                                 f'{len(choice_of[m["proj"]])} tabela(s)')
            pm = (pipe.get(m['proj']) or {}).get('etapa_migracao')
            if pm and not (pipe.get(canon['proj']) or {}).get('etapa_migracao'):
                conflitos.append(f'{m["stem"]} tem etapa de migração ({pm}) e o eleito não')
    return canon, motivos, conflitos


def main():
    inv = build_inventory()
    zd = json.load(open(os.path.join(OUT, 'zipdates.json')))
    esc, pipe, choice_of, prod_n, as_prod, as_cons = load_prod()

    bypath = {}
    for k, v in zd.items():
        bypath[os.path.basename(k)[:-4]] = (k, v)

    for r in inv:
        r['tok'] = tokens(r['stem'])
        r['base'] = base_name(r['stem'])
        r['sh'] = shingles(r['code'])
        hit = bypath.get(r['stem'])
        r['egp_path'] = hit[0] if hit else None
        r['saved'] = tuple(hit[1]['projxml'])[:3] if hit and hit[1].get('projxml') else None
        r['bytes'] = hit[1]['bytes'] if hit else 0
        r['sha'] = sha(r['egp_path']) if r['egp_path'] and os.path.exists(r['egp_path']) else ''
        r['coleta'] = bool(RE_COLETA.search(r['stem']))
        r['em_prod'] = r['proj'] in prod_n

    # grupos
    by_area, by_glob = defaultdict(list), defaultdict(list)
    for r in inv:
        if r['base']:
            by_area[(r['area'], r['base'])].append(r)
            by_glob[r['base']].append(r)

    grupos = []
    divergentes = []       # mesmo nome-base, mas código não bateu no sub-cluster
    gid = 0
    for (area, base), v in sorted(by_area.items()):
        if len(v) < 2:
            continue
        subs, sims = subcluster(v)
        multi = [s for s in subs if len(s) > 1]
        singles = [s[0] for s in subs if len(s) == 1]
        for s in sorted(multi, key=lambda s: -len(s)):
            gid += 1
            canon, motivos, conflitos = decidir(s, esc, pipe, choice_of, as_prod)
            pares = [(a['stem'], b['stem'], round(sims.get((v.index(a), v.index(b)),
                     sims.get((v.index(b), v.index(a)), 0)), 3))
                     for i, a in enumerate(s) for b in s[i + 1:]]
            grupos.append({'gid': f'G{gid:03d}', 'tipo': 'intra-area', 'area': area,
                           'base': base, 'membros': s, 'canon': canon,
                           'motivos': motivos, 'conflitos': conflitos, 'pares': pares})
        # nome igual mas código divergente: candidato a reescrita OU falso agrupamento
        if len(subs) > 1:
            gid += 1
            allpairs = [(a['stem'], b['stem'],
                         round(sims.get((v.index(a), v.index(b)),
                               sims.get((v.index(b), v.index(a)), 0)), 3))
                        for i, a in enumerate(v) for b in v[i + 1:]]
            divergentes.append({'gid': f'D{gid:03d}', 'tipo': 'nome-igual-codigo-divergente',
                                'area': area, 'base': base, 'membros': v,
                                'canon': None, 'motivos': [], 'conflitos': [],
                                'pares': allpairs, 'n_sub': len(subs),
                                'n_single': len(singles)})
    cross = []
    for base, v in sorted(by_glob.items()):
        if len({r['area'] for r in v}) < 2:
            continue
        gid += 1
        canon, motivos, conflitos = decidir(v, esc, pipe, choice_of, as_prod)
        subs, sims = subcluster(v)
        cross.append({'gid': f'X{gid:03d}', 'tipo': 'entre-areas', 'area': '/'.join(
            sorted({r['area'] for r in v})), 'base': base, 'membros': v, 'canon': canon,
            'motivos': motivos, 'conflitos': conflitos,
            'n_sub': len([s for s in subs if len(s) > 1]),
            'sim_max': round(max([sims[k] for k in sims], default=0), 3)})

    # ---- CSV por membro
    csvp = os.path.join(OUT, f'versoes_egps_{HOJE}.csv')
    with open(csvp, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh, delimiter=';')
        w.writerow(['grupo', 'tipo', 'area', 'nome_base', 'projeto', 'veredito',
                    'familia', 'save_egp', 'bytes', 'sha16', 'loc', 'tasks',
                    'n_inputs', 'n_outputs', 'outputs_criados', 'escopo_indi',
                    'etapa_migracao', 'status_migracao', 'mes', 'produtor_canonico_de',
                    'arestas_como_produtor', 'arestas_como_consumidor', 'em_prod',
                    'marcadores', 'motivos_eleicao', 'conflitos'])
        for g in grupos + divergentes + cross:
            for m in sorted(g['membros'], key=lambda m: m['proj']):
                pv = pipe.get(m['proj']) or {}
                w.writerow([
                    g['gid'], g['tipo'], m['area'], g['base'], m['proj'],
                    ('CANÔNICO' if m is g['canon'] else 'substituído') if g['canon'] else 'revisar',
                    'coleta (__vN)' if m['coleta'] else 'autoral',
                    '%04d-%02d-%02d' % m['saved'] if m['saved'] else '',
                    m['bytes'], m['sha'], m['loc'], m['tasks'],
                    len(m['inputs']), len(m['outputs']),
                    len(set(m['outputs']) - set(m['noncreator'])),
                    'sim' if esc.get(m['proj']) else 'nao',
                    pv.get('etapa_migracao', ''), pv.get('status_migracao', ''),
                    pv.get('mes_prioridade', ''),
                    len(choice_of.get(m['proj'], ())),
                    len(as_prod.get(m['proj'], ())), len(as_cons.get(m['proj'], ())),
                    'sim' if m['em_prod'] else 'nao',
                    ','.join(sorted(m['tok']['marks'])),
                    ' | '.join(g['motivos']) if m is g['canon'] else '',
                    ' | '.join(g['conflitos']) if m is g['canon'] else '',
                ])
    print('CSV:', csvp)

    json.dump({'grupos': [{k: (v if k not in ('membros', 'canon') else
                               ([m['proj'] for m in v] if k == 'membros' else (v['proj'] if v else None)))
                           for k, v in g.items() if k != 'pares'}
                          for g in grupos + divergentes + cross]},
              open(os.path.join(OUT, 'grupos.json'), 'w'), ensure_ascii=False)

    n_mem = sum(len(g['membros']) for g in grupos)
    print(f'grupos intra-área: {len(grupos)} ({n_mem} EGPs) | '
          f'entre-áreas: {len(cross)} ({sum(len(g["membros"]) for g in cross)} EGPs)')
    print(f'divergentes (nome igual, codigo != ): {len(divergentes)} ({sum(len(g["membros"]) for g in divergentes)} EGPs)')
    print(f'grupos com conflito: {sum(1 for g in grupos + cross if g["conflitos"])}')
    ident=[(g["gid"],a,b) for g in grupos for i,a in enumerate(g['membros']) for b in g['membros'][i+1:] if a['sha'] and a['sha']==b['sha']]
    print(f'pares byte-identicos: {len(ident)}')
    fam = defaultdict(int)
    for g in grupos:
        fam['coleta' if all(m['coleta'] or m is g['canon'] for m in g['membros'])
            else 'autoral'] += 1
    print('famílias (intra):', dict(fam))

    # dump legível p/ eu escrever o relatório
    with open(os.path.join(OUT, 'dump.txt'), 'w', encoding='utf-8') as fh:
        for g in grupos + divergentes + cross:
            fh.write(f"\n{'='*100}\n{g['gid']} [{g['tipo']}] {g['area']} :: \"{g['base']}\"\n")
            for m in sorted(g['membros'], key=lambda m: (m['saved'] or (0, 0, 0)), reverse=True):
                pv = pipe.get(m['proj']) or {}
                fh.write(
                    f"  {'>>' if m is g['canon'] else '  '} {m['stem'][:62]:64s} "
                    f"save={('%04d-%02d-%02d' % m['saved']) if m['saved'] else 'n/d':10s} "
                    f"loc={m['loc']:6d} tsk={m['tasks']:3d} in={len(m['inputs']):3d} "
                    f"out={len(m['outputs']):3d} cria={len(set(m['outputs'])-set(m['noncreator'])):3d} "
                    f"esc={'S' if esc.get(m['proj']) else '-'} "
                    f"etapa={(pv.get('etapa_migracao') or '')[:18]:18s} "
                    f"st={(pv.get('status_migracao') or '')[:22]:22s} "
                    f"chc={len(choice_of.get(m['proj'], ())):2d} "
                    f"prod={len(as_prod.get(m['proj'], ())):3d} "
                    f"cons={len(as_cons.get(m['proj'], ())):3d} "
                    f"sha={m['sha'][:8]:8s} b={m['bytes']:>9} "
                    f"mk={','.join(sorted(m['tok']['marks']))}\n")
            if g.get('pares'):
                fh.write('     sim_codigo: ' + '; '.join(f'{a[:22]}~{b[:22]}={s}'
                                                         for a, b, s in g['pares']) + '\n')
            if g.get('sim_max') is not None:
                fh.write(f"     sim_max={g.get('sim_max')} n_sub={g.get('n_sub')}\n")
            fh.write('     MOTIVOS: ' + ' | '.join(g['motivos']) + '\n')
            if g['conflitos']:
                fh.write('     !! CONFLITO: ' + ' | '.join(g['conflitos']) + '\n')
    print('dump:', os.path.join(OUT, 'dump.txt'))


if __name__ == '__main__':
    main()
