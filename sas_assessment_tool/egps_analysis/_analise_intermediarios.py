#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Números brutos: EGPs cujos outputs parecem alimentar só OUTROS EGPs (candidatos a
"modelo intermediário" em vez de fato/dimensão terminal), cruzado com LINES_OF_CODE.

Reaproveita o parser e a linhagem OFICIAIS de orchestrator_inventory.py (mesma regra do
criador, mesma identidade canônica de tabela e a mesma recuperação por path físico —
ver CLAUDE.md "Decisões de design & armadilhas"). Não reimplementa o matching por nome.

Saída: intermediarios_candidatos_<data>.csv (uma linha por EGP com outputs) + resumo no
terminal (distribuições brutas, sem corte ainda — é só para decidir o corte).
"""
import csv
import os
import re
import statistics
from collections import defaultdict
from datetime import date

import orchestrator_inventory as oi

INPUT_FOLDER = oi.INPUT_FOLDER
OUT_CSV = f"intermediarios_candidatos_{date.today().isoformat()}.csv"

_LOC_RE = re.compile(r'^LINES_OF_CODE:\s*(\d+)')
_TASKS_RE = re.compile(r'^CODE_TASKS_COUNT:\s*(\d+)')


def _parse_loc_tasks(filepath):
    loc, tasks = 0, 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if "END_METADATA" in line:
                break
            m = _LOC_RE.match(line.strip())
            if m:
                loc = int(m.group(1))
                continue
            m = _TASKS_RE.match(line.strip())
            if m:
                tasks = int(m.group(1))
    return loc, tasks


def main():
    txt_files = sorted(f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.txt'))
    print(f"Lendo {len(txt_files)} .txt de '{INPUT_FOLDER}'...")

    project_catalog = {}
    loc_tasks = defaultdict(lambda: [0, 0])  # proj -> [loc, tasks], somado se multi-arquivo

    for filename in txt_files:
        filepath = os.path.join(INPUT_FOLDER, filename)
        p_data = oi.parse_txt_metadata(filepath)
        p_data['libmap'] = oi.parse_libmap_from_txt(filepath)
        proj = p_data['project']
        loc, tasks = _parse_loc_tasks(filepath)
        loc_tasks[proj][0] += loc
        loc_tasks[proj][1] += tasks

        if proj in project_catalog:
            base = project_catalog[proj]
            seen_in = {i['table'] for i in base['inputs']}
            base['inputs'].extend(i for i in p_data['inputs'] if i['table'] not in seen_in)
            base['outputs'].extend(t for t in p_data['outputs'] if t not in base['outputs'])
            base['exports'].extend(e for e in p_data['exports'] if e not in base['exports'])
            base['non_creator'].extend(t for t in p_data.get('non_creator', ()) if t not in base['non_creator'])
            base_lm = base.setdefault('libmap', {})
            for _lib, _paths in p_data.get('libmap', {}).items():
                base_lm.setdefault(_lib, set()).update(_paths)
        else:
            project_catalog[proj] = p_data

    # ---- réplica da linhagem oficial (orchestrator_inventory.main(), 3 passes) ----
    def _is_unresolved_macro_table(name):
        return any(ch in (name or '') for ch in ('&', '{', '}'))

    def _member_key(name):
        m = (name or '').strip().strip('"').strip("'").replace('\\', '/')
        m = m.rsplit('/', 1)[-1]
        m = m.upper().split('.')[-1]
        return re.sub(r'[^A-Z0-9_]', '', m)

    def _dataset_key(fname):
        b = (fname or '').strip().strip('"').strip("'").rsplit('/', 1)[-1]
        b = re.sub(r'\.sas7bdat$', '', b, flags=re.IGNORECASE)
        return re.sub(r'[^A-Z0-9_]', '', b.upper())

    def _split_lib_member(ref):
        c = oi._canonical_table_key(ref)
        lib, _sep, member = c.partition('.')
        return lib, member

    # cada output vira um "slot" com 3 identidades possíveis de match (nome canônico,
    # basename de membro, path físico). Os 3 passes de linhagem abaixo atribuem consumo
    # ao slot certo, não só ao projeto — senão os passes de recuperação (basename/path,
    # que existem justamente p/ pegar alias de libname diferente do produtor) nunca
    # batem com o proj_output_keys por nome e o consumo fica subcontado.
    proj_output_slots = defaultdict(list)  # proj -> [ {name_key, member_key, physical_keys} ]
    proj_output_keys = defaultdict(set)    # proj -> {name_key}  (p/ checar auto-escrita+leitura)
    proj_out_path = defaultdict(set)       # proj -> {(path, member)}  (idem, passe físico)
    name_key_index = defaultdict(list)     # name_key -> [(proj, slot_idx)]
    member_key_index = defaultdict(list)   # member_key -> [(proj, slot_idx)]
    physical_key_index = defaultdict(list)  # (path, member) -> [(proj, slot_idx)]

    for proj, data in project_catalog.items():
        lm = data.get('libmap', {})
        _nc = {oi._canonical_table_key(t) for t in data.get('non_creator', ())}
        for tb in data['outputs']:
            if _is_unresolved_macro_table(tb):
                continue
            nk = oi._canonical_table_key(tb)
            if nk in _nc:
                continue
            phys = set()
            if '/' in tb or '\\' in tb:
                pn = re.sub(r'/+', '/', tb.replace('\\', '/')).rstrip('/').lower()
                d, _, b = pn.rpartition('/')
                if d and b:
                    phys.add((d, b.upper()))
            else:
                lib, member = _split_lib_member(tb)
                for p in lm.get(lib, ()):
                    phys.add((p, member))
            slot_idx = len(proj_output_slots[proj])
            proj_output_slots[proj].append({'raw': tb, 'name_key': nk})
            proj_output_keys[proj].add(nk)
            proj_out_path[proj].update(phys)
            name_key_index[nk].append((proj, slot_idx))
            member_key_index[_member_key(tb)].append((proj, slot_idx))
            for pk in phys:
                physical_key_index[pk].append((proj, slot_idx))

    adj_list = defaultdict(set)
    consumed_slots = defaultdict(set)  # proj -> {slot_idx consumido por >=1 OUTRO egp}

    # passe 1: nome canônico igual (LIB.MEMBER bate literalmente)
    for proj, data in project_catalog.items():
        for inp_obj in data['inputs']:
            inp_table = inp_obj['table']
            if _is_unresolved_macro_table(inp_table):
                continue
            k_in = oi._canonical_table_key(inp_table)
            if k_in in proj_output_keys.get(proj, ()):
                continue
            for generator, slot_idx in name_key_index.get(k_in, ()):
                if generator == proj:
                    continue
                adj_list[generator].add(proj)
                consumed_slots[generator].add(slot_idx)

    # passe 2: basename .sas7bdat lido == membro de um output (mesmas guards do orquestrador)
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
            candidates = member_key_index.get(key, ())
            producer_projects = {p for p, _ in candidates}
            if not producer_projects or proj in producer_projects or len(producer_projects) > 3:
                continue
            for generator, slot_idx in candidates:
                if generator == proj:
                    continue
                adj_list[generator].add(proj)
                consumed_slots[generator].add(slot_idx)

    # passe 3: mesmo path físico do libname, alias de nome pode ser diferente (aditivo)
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
                for generator, slot_idx in physical_key_index.get(key, ()):
                    if generator == proj:
                        continue
                    adj_list[generator].add(proj)
                    consumed_slots[generator].add(slot_idx)

    # ---- métricas por EGP ----
    rows = []
    for proj, data in sorted(project_catalog.items()):
        n_outputs = len(proj_output_slots.get(proj, ()))
        if n_outputs == 0:
            continue
        loc, tasks = loc_tasks[proj]
        n_exports = len(data.get('exports', ()))
        n_egp_consumers = len(adj_list.get(proj, ()))
        n_outputs_consumed = len(consumed_slots.get(proj, ()))
        pct = round(100 * n_outputs_consumed / n_outputs, 1)

        # ---- indicadores independentes (nenhum combina os outros nem decide nada;
        # servem só para o analista filtrar/cruzar no Excel e priorizar revisão manual) ----
        flag_100pct_egp = pct == 100
        flag_algum_egp = pct > 0
        flag_sem_export = n_exports == 0
        flag_output_unico = n_outputs == 1
        flag_hub = n_egp_consumers >= 3

        if pct == 0:
            faixa_pct = '0%'
        elif pct == 100:
            faixa_pct = '100%'
        elif pct <= 25:
            faixa_pct = '1-25%'
        elif pct <= 50:
            faixa_pct = '26-50%'
        elif pct <= 75:
            faixa_pct = '51-75%'
        else:
            faixa_pct = '76-99%'

        sinais = []
        if flag_100pct_egp:
            sinais.append('100% p/ outro EGP')
        elif flag_algum_egp:
            sinais.append('parte p/ outro EGP')
        if flag_sem_export:
            sinais.append('sem export de arquivo')
        if flag_output_unico:
            sinais.append('output único')
        if flag_hub:
            sinais.append(f'hub ({n_egp_consumers} EGPs leem)')

        rows.append({
            'project': proj,
            'business_area': data.get('business_area', ''),
            'target_arch': data.get('target_arch', ''),
            'loc': loc,
            'tasks': tasks,
            'n_outputs': n_outputs,
            'n_outputs_consumed_by_other_egp': n_outputs_consumed,
            'pct_outputs_consumed_by_other_egp': pct,
            'faixa_pct_consumo_egp': faixa_pct,
            'n_distinct_egp_consumers': n_egp_consumers,
            'n_exports_arquivos': n_exports,
            'flag_output_100pct_egp': flag_100pct_egp,
            'flag_algum_output_egp': flag_algum_egp,
            'flag_sem_export_arquivo': flag_sem_export,
            'flag_output_unico': flag_output_unico,
            'flag_hub_multiplos_consumidores': flag_hub,
            'sinais': '; '.join(sinais) if sinais else '(nenhum)',
        })

    # sem corte: sai 1 linha por EGP com output, ordenado só p/ leitura (não é ranking de prioridade)
    rows.sort(key=lambda r: (-r['pct_outputs_consumed_by_other_egp'], -r['n_distinct_egp_consumers'], r['loc']))

    with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=';')
        w.writeheader()
        w.writerows(rows)
    print(f"-> {OUT_CSV} ({len(rows)} EGPs com >=1 output, SEM filtro — todos os indicadores vêm como colunas)")

    # ---- resumo bruto no terminal: cada indicador contado à parte, nenhum combinado em veredito ----
    print(f"\nTotal EGPs com output: {len(rows)}")
    print("\n-- Contagem de cada indicador (independentes — um EGP pode ter vários) --")
    flag_cols = [
        ('flag_output_100pct_egp', '100% dos outputs vão para outro EGP do corpus'),
        ('flag_algum_output_egp', 'pelo menos 1 output vai para outro EGP'),
        ('flag_sem_export_arquivo', 'não exporta nenhum arquivo (não confirma terminal via BI)'),
        ('flag_output_unico', 'só tem 1 output (mais simples de revisar)'),
        ('flag_hub_multiplos_consumidores', '>=3 EGPs distintos leem algum output dele'),
    ]
    for col, label in flag_cols:
        n = sum(1 for r in rows if r[col])
        print(f"  {label:<62}: {n:>4} ({100*n/len(rows):.1f}%)")

    print("\n-- LOC (mediana) por faixa de %% consumo por outro EGP, informativo — não é corte --")
    for faixa in ['0%', '1-25%', '26-50%', '51-75%', '76-99%', '100%']:
        sub = [r['loc'] for r in rows if r['faixa_pct_consumo_egp'] == faixa]
        if not sub:
            continue
        print(f"  {faixa:<8}: n={len(sub):>4}  loc_mediana={statistics.median(sub):>6.0f}  "
              f"loc_min={min(sub):>6}  loc_max={max(sub):>7}")

    print("\n-- Onde os sinais mais fortes se concentram (100% + hub, só para orientar por onde começar) --")
    destaque = [r for r in rows if r['flag_output_100pct_egp'] and r['flag_hub_multiplos_consumidores']]
    destaque.sort(key=lambda r: r['loc'])
    if not destaque:
        print("  (nenhum EGP com 100% + hub>=3 — ver coluna 'sinais' no CSV p/ combinações parciais)")
    for r in destaque[:15]:
        print(f"  {r['project']:<55} loc={r['loc']:>5} outputs={r['n_outputs']:>3} "
              f"consumidores_egp={r['n_distinct_egp_consumers']:>3}")


if __name__ == '__main__':
    main()
