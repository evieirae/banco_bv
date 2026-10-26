#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressão: 'Falha na extração' causada por falha de CHURN deve levar o inventário
do antecessor junto no resultado.

Contexto — são dois casos distintos de 'Falha na extração' em analisa_par():
  a) o extrator não produziu inventário para um dos lados -> não há antecessor
     legível, 'antigo': None é a resposta correta;
  b) os dois inventários saíram bem e só a RELEITURA do código para o diff falhou
     -> o antecessor está em mãos e tem de ir junto.

No caso (b) o resultado saía sem '_inventarios'; comparar() então caía no ramo de
saída antecipada, re-extraía só o lado novo e gravava 'antigo': None. Em
publish_egps_atualizados.monta_inventario isso vira `tem_antecessor = False`:
nenhum output é marcado 'removido' e todo input recebe novo=None — ou seja, um
EGP com antecessor conhecido publica como se fosse inédito.

É o mesmo modo de falha que a correção do 'Sem mudança (descartar)' eliminou, e
que voltou por outra porta quando o quadrante 'Falha na extração' foi criado.

Uso: egps_analysis/venv/bin/python test_compare_falha_churn.py
"""
import sys

sys.path.insert(0, '.')
import compare_egp_versions as cev  # noqa: E402

INV_A = {'project': 'Area__Velho', 'inputs': [{'table': 'LIB.T1', 'source': ''}],
         'outputs': ['LIB.SAI_ANTIGA'], 'files_read': [], 'included_scripts': [],
         'exports': [], 'libnames': [], 'non_creator': []}
INV_B = {'project': 'Area__Novo', 'inputs': [{'table': 'LIB.T1', 'source': ''}],
         'outputs': ['LIB.SAI_NOVA'], 'files_read': [], 'included_scripts': [],
         'exports': [], 'libnames': [], 'non_creator': []}


def _fake_extrai(path, area, scratch):
    return INV_A if 'velho' in path.lower() else INV_B


def _churn_quebrado(fp_novo, fp_antigo):
    """Simula o zip ilegível na releitura do código (ok=False)."""
    return {'ok': False, 'linhas_add': 0, 'linhas_rem': 0, 'tasks_novas': 0,
            'tasks_removidas': 0, 'loc_antigo': 0, 'loc_novo': 0}


def roda():
    cev.extrai_inventario = _fake_extrai
    cev.calcula_churn = _churn_quebrado

    fp_novo = {'path': '/x/novo.egp', 'ok': True, 'codes': {'a': 'h1'}, 'loc': 10, 'n_code': 1}
    primario = {'path': '/x/velho.egp', 'ok': True, 'codes': {'a': 'h2'}, 'loc': 10, 'n_code': 1}
    par = {'confianca': 'ok', 'overlap': 0.9, 'antigos': [primario], 'motivo': ''}
    # disp no formato do carrega_disponibilidade (índice + ponte), sem tocar disco
    disp = {'override': {}, 'chameleon_idx': {'exato': set(), 'por_sufixo': {}},
            'n_chameleon': 0, 'repmap': None, 'cache': {}}
    alc = {'consumidores': {}, 'deps': {}, 'dependentes': {}}
    snap = {'linhas': {}, 'data': 0, 'ok': True, 'aviso': ''}

    res = cev.analisa_par(fp_novo, par, disp, alc, snap, '/tmp')
    inv = res.get('_inventarios') or {}

    casos = [
        ("quadrante é 'Falha na extração'", res.get('quadrante') == 'Falha na extração'),
        ("resultado carrega '_inventarios'", '_inventarios' in res),
        ("antecessor NÃO é None (o bug)", inv.get('antigo') is not None),
        ("lado novo presente", inv.get('novo') is not None),
        ("projetos_antigos preenchido", inv.get('projetos_antigos') == ['Area__Velho']),
        ("classificação do antigo presente", inv.get('cls_antigo') is not None),
    ]

    # ponta a ponta: o publish precisa enxergar o antecessor
    res['versao_id_calc'] = 'v1'
    import publish_egps_atualizados as pub
    ins, outs = pub.monta_inventario(res)
    casos += [
        ("publish marca LIB.SAI_ANTIGA como 'removido'",
         any(o.get('removido') and 'SAI_ANTIGA' in (o.get('artefato') or '') for o in outs)),
        ("inputs têm 'novo' booleano (não None)",
         bool(ins) and all(i.get('novo') is not None for i in ins)),
    ]

    falhas = 0
    for nome, ok in casos:
        print(f"[{'PASS' if ok else 'FAIL'}] {nome}")
        if not ok:
            falhas += 1
    print(f"\n{'TODOS PASSARAM' if falhas == 0 else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(roda())
