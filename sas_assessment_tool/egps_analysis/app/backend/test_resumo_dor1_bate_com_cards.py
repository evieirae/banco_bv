# -*- coding: utf-8 -*-
"""Tabelas DOR1 do Resumo ("Funil por área" e "Inputs por origem") batem com os cards.

Medido em prod em 14/10/2026, quatro divergências independentes:

1. não modernizados do escopo 194 × "A ingerir" do card 205: a família de safras agrega
   só as safras em vista, e o dataset do escopo não vê a safra pendente que só a
   dependência/o extra lê. O card conta a pendência no recorte AMPLIADO (landing, item4);
   a tabela passa a contar igual;
2. total +deps 1.351 × 1.356: o card conta o placeholder `casco::` dos unificados, que não
   é origem — a tabela não conta, e passa a dizer quantos são (`fora_das_origens`);
3. EGPs 192 × 193: a tabela contava dependências pelo grafo vivo e perdia a dependência da
   foto que saiu do recorte (unificada num sucessor). Passa a contar pela linha de base;
4. linha "(sem área)" com 0 EGPs e 116 inputs: a área principal não enxerga extra, e os
   inputs que só extras leem caíam ali. Passam a uma linha "Extras" à parte, cujos EGPs
   ficam fora do total (como o "(+N extra)" do card) e cujos inputs entram nele.

Endpoint inteiro com colaboradores falsos (sem rede).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402

PEND = {"etapa": "A Receber", "status": "A Iniciar"}
SAN = {"etapa": "A Receber", "status": "Sanitizado"}


def un(chave, origem="SAS/Local (externo)", area="Cobrança", **kw):
    r = {"chave_canonica": chave, "origem": origem, "area_principal": area,
         "vinculo_ativo": True}
    r.update(kw)
    return r


CASCO = un("casco::Cobranças__U", origem="Casco (EGP unificado)", area="(sem área)",
           so_de_extra=True, **SAN)
# A família: no escopo só a safra sanitizada está em vista; no recorte ampliado entra a
# safra pendente que só a dependência lê — a família fica pendente.
RI = [un("familia::tabela::A.FAM", **SAN), un("tabela::A.X", **PEND), CASCO]
RD = [
    un("familia::tabela::A.FAM", **PEND),
    un("tabela::A.X", **PEND),
    un("tabela::D.Y", area="Riscos", **PEND),                          # de dependência
    un("tabela::E.Z", area="(sem área)", so_de_extra=True, **PEND),   # só extra lê
    CASCO,
]
LB = {"Cobranças__B1": "base", "Cobranças__B2": "base", "Riscos__D1": "dependencia",
      "Cobranças__D2": "dependencia", "Cobranças__EX": "ex_dependencia"}
# D2 e EX estão na foto mas FORA do recorte vivo (D2 foi unificada num sucessor).
FRONTIER = {"Cobranças__B1", "Cobranças__B2", "Riscos__D1", "Cobranças__SUC"}
NODES = {"Riscos__D1": "Riscos", "Cobranças__D2": "Cobrança", "Cobranças__EX": "Cobrança"}
EXTRAS = ["Cobranças__SUC"]


def _fake_sql(sql, *a, **k):
    if "sas_funil_area" in sql:
        return [{"area": "Cobrança", "qtd_dor1": 2, "egps_enviados": 2, "egps_analisados": 2}]
    if "sas_lineage_nodes" in sql and "projeto IN" in sql:
        nos = [{"projeto": p, "area": a} for p, a in NODES.items() if f"'{p}'" in sql]
        if "GROUP BY area" in sql:
            por = {}
            for n in nos:
                por[n["area"]] = por.get(n["area"], 0) + 1
            return [{"area": a, "n": c} for a, c in por.items()]
        return nos
    if "sas_egp_pipeline" in sql:
        return []                                         # nenhum despriorizado/vínculo
    raise AssertionError(f"SQL inesperado: {sql[:160]}")


def _resumo():
    with patch.object(m, "FAMILIAS_ON", True), \
            patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None), \
            patch.object(m, "_ensure_link_tables", lambda *a, **k: None), \
            patch.object(m, "run_sql", side_effect=_fake_sql), \
            patch.object(m, "_dataset_escopo", lambda s, a: RI if s == "indi" else RD), \
            patch.object(m, "_frontier_egps", lambda s, a: (FRONTIER, {"Cobranças__B1", "Cobranças__B2"})), \
            patch.object(m, "_linha_base", lambda: LB), \
            patch.object(m, "_extras_no_recorte", lambda: EXTRAS):
        return m.resumo()


def test_pendencia_do_escopo_e_a_do_recorte_ampliado():
    R = _resumo()
    # A.FAM está resolvida olhando só o escopo, pendente no recorte ampliado: conta pendente.
    assert R["origem"]["total"] == {"total": 2, "modernizado": 0, "nao_modernizado": 2}
    assert R["funil"]["total"]["inputs_nao_modernizados"] == 2


def test_casco_fica_fora_das_origens_e_e_contado_a_parte():
    R = _resumo()
    assert R["origem_deps"]["total"]["total"] == 4
    assert R["origem_deps"]["fora_das_origens"] == 1


def test_egps_mais_deps_e_o_tamanho_da_linha_de_base():
    R = _resumo()
    fd = R["funil_deps"]
    assert fd["total"]["qtd_dor1"] == len(LB)            # D2 fora do recorte vivo conta
    assert fd["total"]["deps"] == 3
    cob = next(r for r in fd["rows"] if r["area"] == "Cobrança")
    assert (cob["qtd_dor1"], cob["deps"]) == (4, 2)


def test_inputs_so_de_extra_vao_para_a_linha_extras_a_parte():
    fd = _resumo()["funil_deps"]
    areas = [r["area"] for r in fd["rows"]]
    assert "(sem área)" not in areas
    ext = fd["rows"][-1]                                 # à parte: sempre por último
    assert ext["area"] == m.AREA_EXTRAS and ext.get("a_parte")
    assert (ext["qtd_dor1"], ext["inputs_nao_modernizados"]) == (len(EXTRAS), 1)
    # EGPs do extra fora do total; inputs dentro — e o total bate com a tabela de origem.
    assert fd["total"]["qtd_dor1"] == len(LB)
    assert fd["total"]["inputs_nao_modernizados"] == 4


def test_familia_com_alguma_safra_com_area_nao_fica_sem_area():
    """A família herdava a MODA das safras, e as safras que só extra lê valem "(sem área)":
    sendo maioria, a família inteira ficava sem área mesmo com um EGP da base lendo uma
    safra (13 unidades em 14/10/2026, ex.: LDUARTE.BASE_ATUACAO). "(sem área)" só quando
    nenhuma safra tem área — a régua da área por input."""
    assert m._area_da_familia(["(sem área)", "(sem área)", "Cobrança"]) == "Cobrança"
    assert m._area_da_familia(["(sem área)", None]) == "(sem área)"
    assert m._area_da_familia([None, None]) is None
    assert m._area_da_familia(["Riscos", "Cobrança", "Cobrança"]) == "Cobrança"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
