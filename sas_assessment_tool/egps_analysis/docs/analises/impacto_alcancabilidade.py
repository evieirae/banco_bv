#!/usr/bin/env python3
"""Fase 4 do Plano A: impacto em produção dos inputs que não alcançam nenhum output.

Entra o CSV de `alcancabilidade_inputs.py`; sai o efeito na fila real: quantos dos pares
confirmados estão pendentes, quantos são exclusivos (nenhum outro EGP do plano os
consome, então somem do corpus ao desvincular) e a pendência por EGP antes → depois.

Recorte deliberado: SÓ os pares `NAO_ALCANCA` em EGP com cobertura >= 80% — nos EGPs
cuja cadeia toda morre em WORK a pergunta é sobre o EGP (entrega por wizard do EG), não
sobre o input; ver RELATORIO de 21/08.

    . app/venv/bin/activate
    PUBLISH_SCHEMA=monitoramento_sas DATABRICKS_CONFIG_PROFILE=bv \
      DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd \
      python docs/analises/impacto_alcancabilidade.py <pares.csv> <por_egp.csv> <out.csv>
"""
import collections
import csv
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
PARES = sys.argv[1]
POR_EGP = sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else '/tmp/impacto_alcancabilidade.csv'
CORTE = 0.8


def eff_etapa(etapa, auto):
    """Réplica de _eff_etapa() do backend: a etapa humana manda; sem ela, deriva do
    modernizada_auto. É a etapa que o cliente vê e o que os cards contam."""
    if (etapa or '').strip():
        return etapa.strip()
    return 'Modernizado' if auto == 'Disponível' else 'A Receber'


def main():
    sys.path.insert(0, os.path.join(AQUI, '..', '..', 'app', 'backend'))
    import main as M

    egp_cob = {r['egp']: (float(r['cobertura']) if r['cobertura'] else None)
               for r in csv.DictReader(open(POR_EGP, encoding='utf-8'), delimiter=';')}
    mortos = collections.defaultdict(set)      # egp -> {artifact}
    for r in csv.DictReader(open(PARES, encoding='utf-8'), delimiter=';'):
        cob = egp_cob.get(r['egp'])
        if r['veredito'] == 'NAO_ALCANCA' and cob is not None and cob >= CORTE:
            mortos[r['egp']].add(r['input'].strip().upper())
    n_mortos = sum(len(v) for v in mortos.values())
    print(f'[entrada] {n_mortos} pares confirmados em {len(mortos)} EGPs '
          f'(cobertura >= {CORTE:.0%})')

    egps = ', '.join(M.sql_lit(p) for p in sorted(mortos))
    rows = M.run_sql(
        f"SELECT e.projeto, e.chave_canonica, i.artifact, i.categoria, i.etapa, "
        f"i.modernizada_auto, i.origem, "
        f"coalesce(l.link_broken, false) AS link_broken "
        f"FROM {M.T_EGP} e JOIN {M.T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {M.T_LINK} l ON l.projeto = e.projeto "
        f"AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({egps})")
    print(f'[prod] {len(rows)} pares (EGP x input) nesses EGPs')

    # consumidores ATIVOS de cada input em todo o plano (vínculo não quebrado)
    frontier, base = M._frontier_egps('indi_deps', [])
    plano = set(frontier) | set(M._ex_deps_contab(frontier, base))
    fin = ', '.join(M.sql_lit(p) for p in sorted(plano))
    cons = collections.Counter()
    for r in M.run_sql(
            f"SELECT e.chave_canonica, count(*) AS n FROM {M.T_EGP} e "
            f"LEFT JOIN {M.T_LINK} l ON l.projeto = e.projeto "
            f"AND l.chave_canonica = e.chave_canonica "
            f"WHERE e.projeto IN ({fin}) AND NOT coalesce(l.link_broken, false) "
            f"GROUP BY e.chave_canonica"):
        cons[r['chave_canonica']] = int(r['n'])

    linhas = []
    pend_antes = collections.Counter()
    pend_depois = collections.Counter()
    achados = collections.Counter()
    for r in rows:
        proj = r['projeto']
        quebrado = str(r.get('link_broken')).lower() == 'true'
        etapa = eff_etapa(r.get('etapa'), r.get('modernizada_auto') or '')
        pendente = (etapa == 'A Receber') and not quebrado
        morto = (r['artifact'] or '').strip().upper() in mortos[proj]
        if pendente:
            pend_antes[proj] += 1
            if not morto:
                pend_depois[proj] += 1
        if not morto:
            continue
        achados['confirmados em prod'] += 1
        achados['já com vínculo quebrado'] += quebrado
        achados['pendentes (A Receber)'] += pendente
        n = cons.get(r['chave_canonica'], 0)
        exclusivo = n <= 1
        achados['exclusivos do EGP'] += exclusivo and pendente
        linhas.append({
            'egp': proj, 'input': r['artifact'], 'categoria': r['categoria'],
            'origem': r.get('origem') or '', 'etapa_efetiva': etapa,
            'pendente': int(pendente), 'vinculo_quebrado': int(quebrado),
            'consumidores_ativos_no_plano': n, 'exclusivo': int(exclusivo),
        })

    achados_fora = n_mortos - achados['confirmados em prod']
    print('\n[impacto]')
    for k, v in achados.items():
        print(f'  {v:5d}  {k}')
    print(f'  {achados_fora:5d}  fora do inventário de produção (não contam)')

    zeram = [e for e in mortos if pend_antes[e] and not pend_depois[e]]
    tot_a, tot_d = sum(pend_antes.values()), sum(pend_depois.values())
    print(f'\n[fila] pendências desses {len(mortos)} EGPs: {tot_a} -> {tot_d} '
          f'({tot_d - tot_a:+d}, {(tot_d - tot_a) / tot_a * 100:+.1f}%)')
    print(f'[fila] EGPs que ZERAM a pendência: {len(zeram)}')
    for e in sorted(zeram):
        print(f'         {e}')
    print('\n[por EGP] antes -> depois (só quem muda)')
    for e in sorted(mortos, key=lambda x: pend_depois[x] - pend_antes[x]):
        if pend_antes[e] != pend_depois[e]:
            print(f'  {pend_antes[e]:4d} -> {pend_depois[e]:4d}  {e}')

    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()), delimiter=';')
        w.writeheader()
        w.writerows(sorted(linhas, key=lambda r: (r['egp'], r['input'])))
    print(f'\n[csv] {OUT}')


if __name__ == '__main__':
    main()
