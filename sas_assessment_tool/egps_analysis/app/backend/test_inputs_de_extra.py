# -*- coding: utf-8 -*-
"""Separação dos inputs dos EGPs `extra` (revisão da §3.4.13 pela gestão em 29/09/2026).

Antes era "tudo junto": os inputs da versão nova entravam no recorte e sumiam dentro dos
grupos Escopo/Dependências da Visão geral. Agora eles têm grupo próprio e a aba Inputs tem
filtro. O que este arquivo guarda é a parte que erra em silêncio:

- os DOIS conjuntos não são o mesmo, e nenhum dos dois pode virar o outro por descuido
  (`de_extra` = 190 unidades medidas em 29/09; `so_de_extra` = 28);
- a família é a UNIÃO das safras: basta uma safra lida por EGP contável para a família
  inteira deixar de ser exclusiva do extra;
- os três grupos PARTICIONAM o total — separar não podia mexer no denominador.

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402

EX = "tabela::SO_DO_EXTRA"        # só a versão nova lê
COMP = "tabela::COMPARTILHADA"    # a versão nova E a linha de base leem
BASE = "tabela::SO_DA_BASE"       # só a linha de base lê


def _marca(rows, de_extra, de_contavel):
    with patch.object(m, "_chaves_por_extra", lambda: (set(de_extra), set(de_contavel))):
        return m._marca_extra([dict(r) for r in rows])


def test_exclusiva_do_extra_marca_os_dois_campos():
    (r,) = _marca([{"chave_canonica": EX}], {EX, COMP}, {COMP, BASE})
    assert r["de_extra"] is True
    assert r["so_de_extra"] is True


def test_compartilhada_e_de_extra_mas_nao_so_de_extra():
    """O caso que diferencia as duas perguntas — e o que impede a dupla contagem.

    A chave conta no grupo da linha de base; o filtro da aba a mostra assim mesmo, porque
    lá a pergunta é "o que a versão nova consome"."""
    (r,) = _marca([{"chave_canonica": COMP}], {EX, COMP}, {COMP, BASE})
    assert r["de_extra"] is True
    assert r["so_de_extra"] is False


def test_chave_que_nenhum_extra_le_sai_com_os_dois_falsos():
    (r,) = _marca([{"chave_canonica": BASE}], {EX, COMP}, {COMP, BASE})
    assert r["de_extra"] is False
    assert r["so_de_extra"] is False


def test_sem_extra_algum_toda_linha_sai_falsa():
    """Prod hoje (0 extras): o filtro e o grupo existem e ficam vazios, sem explodir."""
    linhas = _marca([{"chave_canonica": EX}, {"chave_canonica": BASE}], set(), set())
    assert [(r["de_extra"], r["so_de_extra"]) for r in linhas] == [(False, False)] * 2


def test_familia_e_a_uniao_das_safras():
    """Uma safra lida por EGP contável tira a FAMÍLIA inteira do grupo dos extras.

    É o motivo de `_marca_extra` rodar DEPOIS da agregação: a safra que o contável lê pode
    não ser a mesma que o extra lê, e um rollup por chave de família não enxergaria isso."""
    fam = {"chave_canonica": "familia::tabela::VENDAS",
           "membros": ["tabela::VENDAS_202501", "tabela::VENDAS_202502"]}
    (so_extra,) = _marca([fam], {"tabela::VENDAS_202501"}, set())
    assert (so_extra["de_extra"], so_extra["so_de_extra"]) == (True, True)
    # a 2ª safra é lida por um EGP contável -> a família não é mais exclusiva do extra
    (mista,) = _marca([fam], {"tabela::VENDAS_202501"}, {"tabela::VENDAS_202502"})
    assert (mista["de_extra"], mista["so_de_extra"]) == (True, False)


def test_linha_sem_membros_usa_a_propria_chave():
    """Com FAMILIAS_SAFRA desligada a linha não tem `membros` — e o marcador roda igual."""
    (r,) = _marca([{"chave_canonica": EX}], {EX}, set())
    assert r["so_de_extra"] is True


# ---- a partição da Visão geral ---------------------------------------------------

CASCO = "tabela::CASCO"      # só de extra E dentro do escopo Indicium (a casca nasce
                             # escopo_indi=true, então o inventário dela cai nos dois)
NOVO = "tabela::SO_DO_SUCESSOR"   # só de extra, fora do escopo
DEP = "tabela::DA_DEPENDENCIA"

RI = [{"chave_canonica": CASCO}, {"chave_canonica": COMP}, {"chave_canonica": BASE}]
RD = RI + [{"chave_canonica": NOVO}, {"chave_canonica": DEP}]


def _landing_particionada():
    """landing() com dataset e grafo de mentira; devolve o payload."""
    so_de_extra = {CASCO, NOVO}

    def _dataset(scope, areas=()):
        base = RI if scope == "indi" else RD
        return [dict(r, so_de_extra=r["chave_canonica"] in so_de_extra) for r in base]

    ps = [patch.object(m, "FAMILIAS_ON", True),
          patch.object(m, "_dataset_escopo", _dataset),
          patch.object(m, "_chaves_por_extra", lambda: (so_de_extra | {COMP}, {COMP, BASE, DEP})),
          patch.object(m, "_linha_base", lambda: {"Cob__A": "base", "Cob__C": "dependencia"}),
          patch.object(m, "_extras_no_recorte", lambda: {"Cob__Novo", "Cob__Casca"}),
          patch.object(m, "_edges_pruned", lambda: []),
          patch.object(m, "_egps_fora_backlog", lambda: set()),
          # o lado de EGP da landing não é o que se testa aqui: count(*) devolve 0 e as
          # listas de chave vêm vazias (com a flag ligada quem conta input é o dataset).
          patch.object(m, "run_sql", lambda *a, **k: ([{"n": 0}] if "count(*)" in a[0] else [])),
          patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
          patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
          patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
    for p in ps:
        p.start()
    try:
        return m.landing()
    finally:
        for p in ps:
            p.stop()


def test_os_tres_grupos_particionam_o_total_de_inputs():
    L = _landing_particionada()
    assert L["inputs_escopo"] == 2          # COMP e BASE (o CASCO saiu p/ o grupo dos extras)
    assert L["inputs_deps"] == 1            # DEP
    assert L["inputs_extras"] == 2          # CASCO e NOVO
    assert L["total_inputs"] == 5
    assert L["inputs_escopo"] + L["inputs_deps"] + L["inputs_extras"] == L["total_inputs"]


def test_pendencia_conta_no_grao_do_RECORTE_nao_no_do_escopo():
    """A família de safras tem estado DEPENDENTE DO RECORTE: ela agrega só as safras em
    vista. `MOVTO.BASILEIA` tinha 9 das 23 safras no escopo, todas modernizadas, e 22 das
    23 no recorte ampliado, com safras "A Receber" — resolvida num dataset, pendente no
    outro. Contando a pendência do escopo pelo dataset do escopo, 7 famílias assim saíam
    como resolvidas e o card "Total não modernizados" dizia 386 onde a tabela de origem e
    o funil de ingestão diziam 393. Defeito anterior à separação; exigir que as três
    parcelas fechassem foi o que o revelou."""
    mista = {"chave_canonica": "familia::tabela::BASILEIA"}
    ri = [dict(mista, etapa="Modernizado")]                 # no escopo: resolvida
    rd = [dict(mista, etapa="A Receber")]                   # no recorte: pendente

    def _dataset(scope, areas=()):
        return [dict(r, so_de_extra=False) for r in (ri if scope == "indi" else rd)]

    ps = [patch.object(m, "FAMILIAS_ON", True),
          patch.object(m, "_dataset_escopo", _dataset),
          patch.object(m, "_chaves_por_extra", lambda: (set(), set())),
          patch.object(m, "_linha_base", lambda: {"Cob__A": "base"}),
          patch.object(m, "_extras_no_recorte", lambda: set()),
          patch.object(m, "_edges_pruned", lambda: []),
          patch.object(m, "_egps_fora_backlog", lambda: set()),
          patch.object(m, "run_sql", lambda *a, **k: ([{"n": 0}] if "count(*)" in a[0] else [])),
          patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
          patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
          patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
    for p in ps:
        p.start()
    try:
        L = m.landing()
    finally:
        for p in ps:
            p.stop()
    # a unidade é UMA só, e está pendente NO RECORTE — o total tem de dizer 1, não 0
    assert L["total_inputs"] == 1
    assert L["total_nao_modernizados"] == 1
    assert L["inputs_a_ingerir"] == 1      # atribuída ao escopo, que é onde a chave mora


def test_separar_nao_mexeu_no_denominador():
    """A régua anterior ("tudo junto") dava o MESMO total: 3 no escopo + 2 nas deps.

    Este é o contrato da decisão de 29/09/2026 — a mudança é de LEITURA. Se um refactor
    começar a tirar os extras do total, é aqui que quebra."""
    L = _landing_particionada()
    assert L["total_inputs"] == len({r["chave_canonica"] for r in RD})


def test_a_chave_compartilhada_fica_com_a_linha_de_base():
    """COMP é `de_extra` (o filtro da aba a mostra) mas não entra no grupo dos extras."""
    L = _landing_particionada()
    assert L["inputs_extras"] == 2 and COMP not in (CASCO, NOVO)


def test_caminho_legado_conta_o_frontier_inteiro_e_nao_so_as_deps():
    """Guarda do defeito achado em 29/09 no ramo sem FAMILIAS_SAFRA.

    Ele montava o universo a partir de `deps` (o fecho transitivo) em vez do FRONTIER.
    Sucessor, casca e novo entram no recorte POR REGRA e não estão em `deps`, então a
    chave EXCLUSIVA de um extra não caía em `indi_chaves` nem em `deps_chaves` e sumia do
    Total — 27 chaves a menos que a tabela de origem, medido no schema dos atualizados.
    Era anterior à separação; exigir que as três parcelas fechassem foi o que o revelou.
    """
    chamadas = []

    def _run(sql, want_rows=True, **kw):
        s = " ".join(str(sql).split())
        if "AS tot" in s:                    # itens 3/4 do ramo legado (SQL)
            return [{"tot": 3, "aing": 0}]      # CASCO, COMP, BASE em escopo_indi
        if "count(*)" in s:
            return [{"n": 0}]
        if "sas_egp_inputs" in s:            # o universo por vínculo
            chamadas.append(s)
            # o fake TEM de responder ao WHERE, senão o teste passa sem distinguir nada:
            # só quem cita o EGP extra enxerga as chaves exclusivas dele.
            chaves = [COMP, BASE, DEP]
            if "Cob__Novo" in s:
                chaves += [CASCO, NOVO]
            return [{"chave_canonica": k} for k in chaves]
        return []

    ps = [patch.object(m, "FAMILIAS_ON", False),
          patch.object(m, "_chaves_por_extra", lambda: ({CASCO, NOVO, COMP}, {COMP, BASE, DEP})),
          patch.object(m, "_linha_base", lambda: {"Cob__A": "base"}),
          patch.object(m, "_extras_no_recorte", lambda: {"Cob__Novo"}),
          patch.object(m, "_edges_pruned", lambda: []),
          patch.object(m, "_egps_fora_backlog", lambda: set()),
          # `deps` NÃO contém o extra; o frontier sim — é essa a diferença que o bug tinha
          patch.object(m, "_transitive_upstream", lambda *a, **k: {"Cob__A": 0, "Cob__Dep": 1}),
          patch.object(m, "_frontier_egps", lambda *a, **k: ({"Cob__A", "Cob__Dep", "Cob__Novo"},
                                                             {"Cob__A"})),
          patch.object(m, "run_sql", _run),
          patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
          patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
          patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
    for p in ps:
        p.start()
    try:
        L = m.landing()
    finally:
        for p in ps:
            p.stop()
    # o EGP extra entrou no universo: a query do recorte cita o projeto dele
    assert any("Cob__Novo" in c for c in chamadas), "universo montado sem o frontier"
    # e as chaves exclusivas dele chegaram ao contador. Montado sobre `deps`, o WHERE não
    # citaria Cob__Novo, o fake devolveria só COMP/BASE/DEP e isto daria 0.
    assert L["inputs_extras"] == 2                      # CASCO e NOVO
