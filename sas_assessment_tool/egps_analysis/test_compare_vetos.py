#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressões de VETO e de rastro no compare de versões de EGP.

Os dois modos de falha cobertos aqui têm a mesma assinatura perigosa: o resultado
parece bom (nenhum veto, nenhum alerta) justamente porque a análise não conseguiu
olhar para o que provaria o contrário.

  F2 — extração PARCIAL do lado antigo. Com N:1 (o EGP novo consolida vários
       antecessores), um antecessor ilegível era descartado em silêncio e a
       comparação seguia com a união incompleta, ainda reportando n_antecessores
       cheio. Como `removidos = out_a - out_b` perde os outputs do que não foi
       lido, `outputs_compartilhados` fica vazio e o veto de "output removido com
       2+ consumidores externos" NUNCA dispara.

  F13 — quadrantes de saída antecipada (inédito / par não resolvido / sem mudança /
       falha na extração) retornam antes de avalia_veto(), que é onde o aviso de
       snapshot vencido entra nos alertas. Uma rodada feita com snapshot fora da
       validade publicava essas linhas sem nenhum rastro disso.

Uso: egps_analysis/venv/bin/python test_compare_vetos.py
"""
import sys

sys.path.insert(0, '.')
import compare_egp_versions as cev  # noqa: E402

SNAP_VELHO = {'linhas': {}, 'data': 30, 'ok': False,
              'aviso': 'snapshot tem 30 dias (limite 7): REGERE antes de confiar no veto'}

_INV = {'project': 'Area__Ant', 'inputs': [], 'outputs': ['LIB.SAIDA'],
        'files_read': [], 'included_scripts': [], 'exports': [], 'libnames': [],
        'non_creator': []}


def _extrai_com_falha(path, area, scratch):
    """Simula um antecessor ilegível (o que contém 'ruim' no nome)."""
    return None if 'ruim' in path else dict(_INV)


def _churn_ok(fp_novo, fp_antigo):
    """Churn que SUCEDE.

    Necessário para o teste isolar o F2: os .egp do fixture não existem em disco,
    então calcula_churn falharia e devolveria 'Falha na extração' por OUTRO motivo —
    o teste passaria pela razão errada, inclusive no código sem a correção."""
    return {'ok': True, 'linhas_add': 1, 'linhas_rem': 1, 'tasks_novas': 0,
            'tasks_removidas': 0, 'loc_antigo': 10, 'loc_novo': 10}


def roda():
    casos = []

    # --- F13: o aviso de staleness sobrevive nas saídas antecipadas ---------------
    casos.append(("F13 aviso anexado a um alerta que já existia",
                  'REGERE' in cev._com_aviso('motivo original', SNAP_VELHO)))
    casos.append(("F13 aviso vira o alerta quando não havia nenhum",
                  cev._com_aviso('', SNAP_VELHO) == SNAP_VELHO['aviso']))
    casos.append(("F13 snapshot fresco não altera o alerta",
                  cev._com_aviso('so isso', {'aviso': ''}) == 'so isso'))

    # --- F2: co-antecessor ilegível não vira comparação válida --------------------
    cev.extrai_inventario = _extrai_com_falha
    cev.calcula_churn = _churn_ok
    fp_novo = {'path': '/x/novo.egp', 'ok': True, 'codes': {'a': 'h1'}, 'loc': 9, 'n_code': 1}
    antigos = [{'path': '/x/bom.egp', 'ok': True, 'codes': {'a': 'h2'}},
               {'path': '/x/ruim.egp', 'ok': True, 'codes': {'a': 'h3'}}]
    par = {'confianca': 'ok', 'overlap': 0.9, 'antigos': antigos, 'motivo': ''}
    disp = {'override': {}, 'chameleon_idx': {'exato': set(), 'por_sufixo': {}},
            'n_chameleon': 0, 'repmap': None, 'cache': {}}
    alc = {'consumidores': {}, 'deps': {}, 'dependentes': {}}

    res = cev.analisa_par(fp_novo, par, disp, alc, SNAP_VELHO, '/tmp')
    al = res.get('alertas') or ''
    casos += [
        ("F2 extração parcial não segue como comparação válida",
         res.get('quadrante') == 'Falha na extração'),
        ("F2 alerta nomeia o antecessor ilegível", 'ruim.egp' in al),
        ("F2 alerta diz quantos de quantos falharam", '1 de 2' in al),
        ("F2 não reporta veto zerado como se fosse análise completa",
         res.get('n_vetos') == 0 and res.get('quadrante') != 'Trocar agora'),
        ("F2+F13 o aviso de staleness também chega nessa linha", 'REGERE' in al),
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
