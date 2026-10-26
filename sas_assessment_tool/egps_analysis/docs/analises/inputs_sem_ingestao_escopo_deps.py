#!/usr/bin/env python3
"""Versão cliente: inputs que NÃO precisam de ingestão, restrito a escopo + dependências.

Diferença para `inputs_sanitizaveis_tiers.py`: o recorte aqui é o **plano de migração
vigente** lido do app (escopo Indicium + dependências transitivas + ex-dependências
contabilizadas), e a consolidação da classe considera apenas os EGPs do plano — é a
pergunta que interessa à gestão: "para os EGPs que vou migrar, o que dispensa ingestão?".

    . app/venv/bin/activate
    PUBLISH_SCHEMA=monitoramento_sas DATABRICKS_CONFIG_PROFILE=bv \
      DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd \
      python docs/analises/inputs_sem_ingestao_escopo_deps.py 2026-08-13
"""
import collections
import csv
import os
import sys

DIA = sys.argv[1] if len(sys.argv) > 1 else '2026-08-13'
DIA_FONTE = sys.argv[2] if len(sys.argv) > 2 else '2026-08-13'
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
# APP_BACKEND permite apontar para o checkout DEPLOYADO em prod (origin/main), que pode
# divergir da working tree. Foi o caso em 2026-08-17: main já tinha _ex_deps_manuais
# (escopo 193) e a working tree não (191).
APP_BACKEND = os.environ.get(
    'APP_BACKEND', os.path.join(AQUI, '..', '..', 'app', 'backend'))

import auditoria_ordem_codigo as AO  # noqa: E402  (precisa do sys.path acima)

CODE = {}

# mais conservador primeiro — a classe que "ganha" quando vários EGPs leem o mesmo input
RANK = ['ingestao_recorrente', 'acumulador_compartilhado', 'ingestao_snapshot_datado',
        'membro_dinamico', 'outro_egp_cria_safra_irma', 'outro_egp_cria',
        'auto_safra_irma', 'calendario', 'auto_mesmo_run']

TIER = {
    'auto_mesmo_run': ('1 — dispensa ingestão',
                       'O próprio EGP recria a tabela a cada execução',
                       'Marcar Sanitizado'),
    'calendario': ('1 — dispensa ingestão',
                   'Calendário/dias úteis — vira date spine no destino',
                   'Marcar Sanitizado'),
    'outro_egp_cria': ('2 — dispensa ingestão se o produtor migrar',
                       'Outro EGP do plano cria a tabela',
                       'Confirmar o produtor no plano; então marcar Sanitizado'),
    'outro_egp_cria_safra_irma': ('2 — dispensa ingestão se o produtor migrar',
                                  'Outro EGP do plano cria a safra anterior da mesma família',
                                  'Confirmar o produtor no plano; backfill do histórico'),
    'acumulador_compartilhado': ('3 — exige carga inicial',
                                 'Tabela de acumulação: o EGP só apensa, ninguém a cria',
                                 'Carga inicial do histórico — NÃO sanitizar'),
    'auto_safra_irma': ('3 — exige carga inicial',
                        'O EGP cria a safra do mês lendo a safra anterior que ele mesmo gerou',
                        'Backfill único do histórico — NÃO sanitizar'),
}
MOJIBAKE = {'╞': 'ã', '╡': 'õ', '┌': 'ú', '╨': 'Ñ'}

# Calendário é DERIVÁVEL (datas + feriados): não precisa de ingestão nem de carga de
# histórico, independente de quem o cria hoje. Fica fora da promoção por ordem de código.
# Detectado por nome porque a classe `calendario` subconta — quando o calendário tem
# produtor no corpus, ele cai em `outro_egp_cria`, que vence na precedência.
import re as _re
CALENDARIO = _re.compile(r'(?i)(dias?_?ute|dia_util|dtutil|calend|feriad)')


def fix(s):
    for a, b in MOJIBAKE.items():
        s = (s or '').replace(a, b)
    return s


def read(p):
    rows = list(csv.DictReader(open(os.path.join(AQUI, p), encoding='utf-8-sig'),
                               delimiter=';'))
    return [{k: fix(v) for k, v in r.items()} for r in rows]


def _mes_min(egps, mes):
    v = sorted(mes[e] for e in egps if e in mes)
    return v[0] if v else ''


def _seq(cons, prods, mes):
    """O produtor migra antes do consumidor? Se não, o consumidor fica sem fonte no
    intervalo entre os dois meses do plano."""
    mc = _mes_min(cons, mes)
    mp = _mes_min(prods, mes)
    if not mc:
        return 'consumidor sem mês'
    if not mp:
        return 'PRODUTOR SEM MÊS NO PLANO'
    return 'ok' if mp <= mc else f'INVERTIDO: consumidor M{mc} antes do produtor M{mp}'


def eff_etapa(etapa, auto):
    """Réplica de effEtapa() do front (app/frontend/src/inputs.ts) e de _eff_etapa() do
    backend: a etapa humana manda; sem ela, deriva de modernizada_auto. É a etapa que o
    cliente vê na coluna e o que os cards contam."""
    if (etapa or '').strip():
        return etapa.strip()
    return 'Modernizado' if auto == 'Disponível' else 'A Receber'


def eff_status_input(status, etapa, auto):
    """Réplica de effStatusInput(): sem status humano, 'A Iniciar' em qualquer etapa
    que não seja a terminal."""
    if (status or '').strip():
        return status.strip()
    return 'Concluído' if eff_etapa(etapa, auto) == 'Modernizado' else 'A Iniciar'


def main():
    sys.path.insert(0, APP_BACKEND)
    import main as M
    print(f'[backend] {os.path.realpath(APP_BACKEND)}')
    frontier, base = M._frontier_egps('indi_deps', [])
    plano = set(frontier) | set(M._ex_deps_contab(frontier, base))
    linhas = M.inputs(scope='indi_deps', categoria=[], area=[])['rows']
    mes = {r['projeto']: r['mes_prioridade'] for r in
           M.run_sql(f"SELECT projeto, mes_prioridade FROM {M.T_PIPE} "
                     f"WHERE mes_prioridade IS NOT NULL")}
    # régua dos CARDS da aba Inputs (MonitorView.tsx): fora quem tem todos os vínculos
    # quebrados e fora input de ex-dependência. Sem isso o total dá 1.799 (linhas da
    # tabela) em vez dos 1.699 que o painel mostra.
    cards = [r for r in linhas
             if r.get('vinculo_ativo') is not False and not r.get('ex_dependencia')]
    app = {r['chave_canonica']: r for r in cards}
    fila = [r for r in cards
            if eff_etapa(r.get('etapa'), r.get('modernizada_auto') or '') == 'A Receber']
    print(f'[plano] {len(plano)} EGPs (base {len(base)}) | linhas da tabela {len(linhas)} '
          f'| universo dos cards {len(cards)} | fila "A receber" {len(fila)}')

    global CODE
    CODE = AO.carrega_codigo()
    print(f'[codigo] {len(CODE)} EGPs com corpo de codigo carregado')

    par = read(f'revisao_autoprodutores_pares_{DIA_FONTE}.csv')
    tri = {r['Chave (path|alias)']: r for r in
           read(f'revisao_autoprodutores_triagem_{DIA_FONTE}.csv')}

    por_chave = collections.defaultdict(list)
    for p in par:
        por_chave[p['Chave (path|alias)']].append(p)

    out, fora_de_prod = [], []
    for ch, ps in por_chave.items():
        no_plano = [p for p in ps if p['EGP'] in plano]
        if not no_plano:
            continue                                  # input fora do recorte
        best = min(no_plano, key=lambda r: RANK.index(r['Classificação']))
        c = best['Classificação']
        if c not in TIER:
            continue                                  # ingestão real: fora desta lista
        tier, porque, acao = TIER[c]
        leitores = sorted({p['EGP'] for p in no_plano})
        t = tri.get(ch, {})
        prods = [x.strip() for x in (t.get('Outros criadores (chave exata)') or '').split('|')
                 if x.strip()]
        if not prods:
            prods = [x.strip() for x in
                     (t.get('Outros criadores (mesma família)') or '').split('|') if x.strip()]
        prods_plano = [p for p in prods if p in plano]
        # o próprio leitor pode ser o criador (auto-produção)
        if c in ('auto_mesmo_run', 'auto_safra_irma'):
            prods_plano = prods_plano or leitores
        for a in sorted({p['Input'].strip() for p in no_plano}):
            r = app.get(f'tabela::{a}')
            if r is None:
                # não existe no universo de prod: o cliente não vê essa linha no painel.
                # fica fora da lista para os números do estudo baterem com o app.
                fora_de_prod.append(a)
                continue
            # --- auditoria de ORDEM no código (2026-08-13): a tabela é intermediária
            # ou é estado que atravessa execuções? No tier 1 quem cria é o próprio
            # leitor; no tier 2 é o produtor — em ambos, se a criação depende do
            # conteúdo anterior, a tabela exige carga inicial.
            donos = leitores if tier.startswith('1') else (prods_plano or leitores)
            res = [AO.audita_com_macros(a, CODE.get(d, '')) for d in donos]
            vd, ev = AO.pior([(x[0], x[1]) for x in res])
            via_macro = any(x[2] for x in res)
            tier_a, porque_a, acao_a = tier, porque, acao
            if CALENDARIO.search(a):
                tier_a = '1c — calendário (derivável)'
                porque_a = 'Calendário/dias úteis: conteúdo derivável de datas + feriados'
                acao_a = 'Recriar como date spine único no dbt; não precisa ingestão'
            elif vd in AO.RISCO:
                tier_a = '3 — exige carga inicial'
                if vd == 'SO_LE' and c.startswith('outro_egp_cria'):
                    porque_a = ('Nenhum EGP do plano cria esta safra — foi gerada por uma '
                                'execução anterior do produtor')
                elif vd == 'SO_LE':
                    porque_a = 'Lida sem nenhuma criação no fluxo: vem de execução anterior'
                else:
                    porque_a = ('Lê o conteúdo da execução anterior da própria tabela '
                                f'({vd.lower().replace("_", " ")})')
                acao_a = 'Carga inicial do histórico — NÃO sanitizar'
            elif vd in AO.NAO_VERIFICAVEL or vd == 'so_escreve':
                # nome (ou a leitura) só existe resolvido por macro: ordem não auditável
                if tier.startswith('1'):
                    tier_a = '1v — a verificar (ordem não auditável no código)'
                    acao_a = 'Confirmar no código antes de sanitizar'
            out.append({
                'Tier': tier_a,
                'Tabela': a,
                'Por que dispensa (ou não) ingestão': porque_a,
                'Ação': acao_a,
                'Auditoria de ordem no código': vd,
                'Nome resolvido por macro': 'sim' if via_macro else 'não',
                'Evidência': ev[:180],
                'Etapa atual no painel': eff_etapa(r.get('etapa'),
                                                   r.get('modernizada_auto') or ''),
                'Status atual no painel': eff_status_input(
                    r.get('status'), r.get('etapa'), r.get('modernizada_auto') or ''),
                'Qtd EGPs do plano que leem': len(leitores),
                'EGPs do plano que leem': ' | '.join(leitores),
                'Produtor no plano': ' | '.join(prods_plano) or '—',
                'Mês do consumidor': _mes_min(leitores, mes),
                'Mês do produtor': _mes_min(prods_plano, mes),
                'Sequenciamento': _seq(leitores, prods_plano, mes),
                'Área': r.get('area_principal') or '',
            })

    ordem = {'1 ': 0, '1c': 1, '1v': 2, '2 ': 3, '3 ': 4}
    out.sort(key=lambda r: (ordem.get(r['Tier'][:2], 9), r['Tabela']))
    dest = os.path.join(AQUI, f'BV_Migracao_SAS_Inputs_Sem_Ingestao_{DIA}.csv')
    with open(dest, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), delimiter=';')
        w.writeheader()
        w.writerows(out)

    print(f'\n{dest}\n{len(out)} tabelas visíveis no painel de prod dentro do recorte')
    print(f'(excluídas {len(set(fora_de_prod))} tabelas fora do universo dos cards: '
          f'não publicadas ainda, ou input de ex-dependência)\n')
    for k, v in sorted(collections.Counter(r['Tier'] for r in out).items()):
        print(f'  {v:5d}  {k}')
    print('\netapa atual no painel:')
    for k, v in collections.Counter(r['Etapa atual no painel'] for r in out).most_common():
        print(f'  {v:5d}  {k}')
    AR = lambda p: [r for r in out if r['Tier'].startswith(p)
                    and r['Etapa atual no painel'] == 'A Receber']
    t1, t1v, t2, t12 = AR('1 '), AR('1v'), AR('2 '), AR('1 ') + AR('1c') + AR('2 ')
    t3 = [r for r in out if r['Tier'].startswith('3')]
    print(f'\nSAEM DA FILA (verificado): {len(t12)} de {len(fila)} pendentes '
          f'({100*len(t12)/len(fila):.1f}%)  [tier1={len(t1)} tier1c={len(AR("1c"))} tier2={len(t2)}]')
    print(f'A VERIFICAR (ordem não auditável): {len(t1v)}')
    print(f'EXIGEM CARGA INICIAL: {len(t3)}  '
          f'(já marcados Sanitizado: {sum(1 for r in t3 if r["Status atual no painel"]=="Sanitizado")})')


if __name__ == '__main__':
    main()
