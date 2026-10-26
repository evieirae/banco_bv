#!/usr/bin/env python3
"""Consolida a triagem de inputs SAS/Local que NÃO precisam de ingestão, em tiers.

Reescreve a triagem de 2026-08-12 (que classificava por chave idêntica dentro do
recorte indi_deps) usando a classificação safra-aware de 2026-08-13 (corpus
completo, path-aware) e cruza com o status atual da aba Inputs em produção.

Rodar de egps_analysis/ com o venv do app (precisa de Databricks p/ o status):

    . app/venv/bin/activate
    PUBLISH_SCHEMA=monitoramento_sas DATABRICKS_CONFIG_PROFILE=bv \
      DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd \
      python docs/analises/inputs_sanitizaveis_tiers.py 2026-08-13

Tiers:
  1   auto_mesmo_run  -> sanitizar sem condição (o próprio leitor cria e lê no mesmo run)
  1c  calendario      -> sanitizar (recriar como date spine no dbt)
  2   outro_egp_cria[_safra_irma] -> não é ingestão, MAS depende de migrar o produtor
  3   acumulador_compartilhado / auto_safra_irma -> NÃO sanitizar: exige carga inicial
"""
import collections
import csv
import os
import sys

DIA = sys.argv[1] if len(sys.argv) > 1 else '2026-08-13'
AQUI = os.path.dirname(os.path.abspath(__file__))

TIER = {
    'auto_mesmo_run': ('1 — sanitizar (auto-produção no mesmo run)',
                       'Marcar Sanitizado na aba Inputs'),
    'calendario': ('1c — sanitizar (calendário)',
                   'Marcar Sanitizado; recriar como date spine no dbt'),
    'outro_egp_cria': ('2 — condicionado (outro EGP cria)',
                       'Sanitizado SE o produtor estiver no plano; senão trazer o produtor'),
    'outro_egp_cria_safra_irma': ('2 — condicionado (outro EGP cria safra irmã)',
                                  'Sanitizado SE o produtor estiver no plano; + backfill do histórico'),
    'acumulador_compartilhado': ('3 — NÃO sanitizar (acumulador)',
                                 'Carga inicial: o leitor só apensa, ninguém cria a tabela'),
    'auto_safra_irma': ('3 — NÃO sanitizar (safra irmã própria)',
                        'Backfill único do histórico (não é ingestão recorrente)'),
}


# o CSV de origem carrega mojibake de nomes de EGP (cp437 escapado): 'Atualizaç╞o' -> 'Atualização'
MOJIBAKE = {'╞': 'ã', '╡': 'õ', '┌': 'ú', '╨': 'Ñ'}


def fix(s):
    if not s:
        return s
    for a, b in MOJIBAKE.items():
        s = s.replace(a, b)
    return s


def read(p, sep=';'):
    rows = list(csv.DictReader(open(os.path.join(AQUI, p), encoding='utf-8-sig'),
                               delimiter=sep))
    return [{k: fix(v) for k, v in r.items()} for r in rows]


def main():
    tri = read(f'revisao_autoprodutores_triagem_{DIA}.csv')
    par = read(f'revisao_autoprodutores_pares_{DIA}.csv')

    cls = {r['Chave (path|alias)']: r['Classificação'] for r in tri}
    trow = {r['Chave (path|alias)']: r for r in tri}
    # todos os aliases (forma LIB.MEMBRO) de cada chave path-aware
    alias = collections.defaultdict(set)
    egps_por_chave = collections.defaultdict(set)
    for p in par:
        alias[p['Chave (path|alias)']].add(p['Input'].strip())
        egps_por_chave[p['Chave (path|alias)']].add(p['EGP'])

    # ---- status do app + universo do plano (opcional: sem Databricks sai vazio)
    status, plano = {}, set()
    try:
        sys.path.insert(0, os.path.join(AQUI, '..', '..', 'app', 'backend'))
        import main as M
        for r in M.run_sql(f"SELECT chave_canonica, etapa, status, escopo_indi, "
                           f"qtd_projetos FROM {M.T_IN}"):
            k = r['chave_canonica']
            if k and k.lower().startswith('tabela::'):
                status[k[8:].strip().upper()] = r
        frontier, base = M._frontier_egps('indi_deps', [])
        plano = set(frontier) | set(M._ex_deps_contab(frontier, base))
        print(f'[app] {len(status)} inputs tabela::, plano={len(plano)} EGPs')
    except Exception as e:                                   # noqa: BLE001
        print(f'[app] sem Databricks ({str(e)[:60]}) — colunas de status ficam vazias')

    out = []
    for ch, c in cls.items():
        if c not in TIER:
            continue
        t = trow[ch]
        if t['Lido por EGP do escopo Indicium'].strip().lower() != 'sim':
            continue
        tier, acao = TIER[c]
        leitores = sorted(egps_por_chave.get(ch, ()))
        prods = [x.strip() for x in
                 (t['Outros criadores (chave exata)'] or '').split('|') if x.strip()]
        if not prods:
            prods = [x.strip() for x in
                     (t['Outros criadores (mesma família)'] or '').split('|') if x.strip()]
        no_plano = ('n/d' if not plano else
                    ('sim' if any(p in plano for p in prods) else 'não') if prods else '—')
        path = ch.split('::')[0] if '::' in ch else ''
        for a in sorted(alias.get(ch, ())):
            st = status.get(a.strip().upper()) or {}
            out.append({
                'Tier': tier,
                'Chave canônica': f'tabela::{a}',
                'Artefato': a,
                'Classe (13/08)': c,
                'Ação': acao,
                'Etapa atual no app': st.get('etapa') or ('(não está na aba Inputs)'
                                                          if not st else ''),
                'Status atual no app': st.get('status') or '',
                'Qtd EGPs leitores': len(leitores),
                'EGPs leitores': ' | '.join(leitores),
                'Produtor(es) identificado(s)': ' | '.join(prods) or '—',
                'Produtor no plano de migração': no_plano,
                'Path físico': path if not path.endswith(a.split('.')[0]) else path,
            })

    ordem = {'1 —': 0, '1c ': 1, '2 —': 2, '3 —': 3}
    out.sort(key=lambda r: (ordem.get(r['Tier'][:3], 9), r['Artefato']))
    dest = os.path.join(AQUI, f'BV_Migracao_SAS_Inputs_Sanitizaveis_{DIA}.csv')
    with open(dest, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), delimiter=';')
        w.writeheader()
        w.writerows(out)

    print(f'\n{dest}\n{len(out)} linhas (uma por alias de tabela)\n')
    c1 = collections.Counter(r['Tier'] for r in out)
    for k, v in sorted(c1.items()):
        print(f'  {v:5d}  {k}')
    print('\npor etapa atual na aba Inputs:')
    for k, v in collections.Counter(
            (r['Etapa atual no app'] or '(sem etapa)') for r in out).most_common():
        print(f'  {v:5d}  {k}')
    acion = [r for r in out if r['Tier'].startswith(('1 —', '1c'))
             and r['Etapa atual no app'] == 'A Receber']
    print(f'\nACIONÁVEL AGORA (tier 1/1c + hoje "A Receber"): {len(acion)} inputs')
    cond = [r for r in out if r['Tier'].startswith('2 —')]
    print(f'Condicionado (tier 2): {len(cond)}  — produtor no plano: '
          f"{sum(1 for r in cond if r['Produtor no plano de migração'] == 'sim')}")
    print(f"NÃO sanitizar (tier 3): {sum(1 for r in out if r['Tier'].startswith('3'))}")


if __name__ == '__main__':
    main()
