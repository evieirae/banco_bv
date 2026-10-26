#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EGP "casca": antecessor absorvido por um unificador que nunca terá inventário próprio
(spec §3.6, regras 22–27). Ele precisa de UMA linha no funil, capaz de chegar a `Migrado`,
para que a migração dele seja contabilizada junto com a do unificador.

Os dois pontos cegos medidos em 2026-09 — e o motivo destes testes existirem:
  1. `escopo_indi` se apaga sozinho: `recompute_escopo()` RESETA a flag de todo nó que não
     esteja em `sas_escopo`, então gravar `escopo_indi=True` no nó não basta — a casca
     precisa também de uma linha ATIVA em `sas_escopo` (regra 24).
  2. EGP com ZERO inputs é invisível na aba EGPs: a aba agrupa a partir de `sas_egp_inputs`
     (grão projeto×input), então um EGP sem input nenhum não gera linha no GROUP BY. Daí o
     input SINTÉTICO `casco::<projeto>`, já `Disponível` (regras 25–26).

Roda como:
    egps_analysis/venv/bin/python -m pytest egps_analysis/test_egps_casca.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_to_databricks as pub  # noqa: E402

CSV_HEADER = "pasta,nome,area,unificado_em,motivo\n"


def _csv(tmp_path, linhas):
    p = tmp_path / "egps_casca.csv"
    p.write_text(CSV_HEADER + "".join(linhas), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- loader

def test_loader_monta_projeto_e_canoniza_area(tmp_path):
    path = _csv(tmp_path, [
        "Cobranças,Project_X,Cobrança,Project_HUB,absorvido\n",
    ])
    (c,) = pub.load_egps_casca(path)
    assert c["projeto"] == "Cobranças__Project_X"
    assert c["area"] == "Cobrança"
    assert c["unificado_em"] == "Project_HUB"
    assert c["motivo"] == "absorvido"


def test_pasta_com_acento_nao_vira_a_area_canonica(tmp_path):
    """`pasta` é o rótulo CRU da extração; `area` é o canônico. Não colapsar os dois:
    "Cobranças" na pasta vs "Cobrança" na coluna area."""
    path = _csv(tmp_path, ["Cobranças,Project_X,Cobranças,HUB,m\n"])
    (c,) = pub.load_egps_casca(path)
    assert c["projeto"].startswith("Cobranças__")      # com 's', o rótulo cru
    assert c["area"] == "Cobrança"                      # canonizado, sem 's'


def test_arquivo_ausente_e_lista_vazia_nao_erro(tmp_path):
    assert pub.load_egps_casca(str(tmp_path / "nao_existe.csv")) == []


def test_linha_sem_pasta_ou_sem_nome_e_ignorada(tmp_path):
    path = _csv(tmp_path, [
        ",Project_X,Cobrança,HUB,m\n",
        "Cobranças,,Cobrança,HUB,m\n",
        "Cobranças,Project_OK,Cobrança,HUB,m\n",
    ])
    assert [c["projeto"] for c in pub.load_egps_casca(path)] == ["Cobranças__Project_OK"]


def test_csv_versionado_do_repo_carrega(tmp_path):
    """src/egps_casca.csv é o cadastro real — 5 cascas, todas de Cobranças."""
    reais = pub.load_egps_casca()
    assert len(reais) == 5
    assert all(c["projeto"].startswith("Cobranças__") for c in reais)
    assert all(c["area"] == "Cobrança" for c in reais)
    assert all(c["unificado_em"] for c in reais)


# ---------------------------------------------------------------- montagem das linhas

def _casca(projeto="Cobranças__Project_X", area="Cobrança"):
    return {"projeto": projeto, "area": area, "unificado_em": "HUB", "motivo": "m"}


def test_no_nasce_com_escopo_indi_e_um_input():
    r = pub.build_casca_rows([_casca()], existentes=set())
    (nd,) = r["nodes"]
    assert nd["projeto"] == "Cobranças__Project_X"
    assert nd["area"] == "Cobrança"
    assert nd["escopo_indi"] is True     # gravado DIRETO, sem depender de sas_escopo
    assert nd["n_inputs"] == 1           # o sintético — senão some da aba EGPs
    assert nd["n_outputs"] == 0


def test_input_sintetico_tem_chave_casco_e_rotulo_visivel():
    r = pub.build_casca_rows([_casca()], existentes=set())
    (inp,) = r["inputs"]
    assert inp["chave_canonica"] == "casco::Cobranças__Project_X"
    assert inp["artifact"].startswith("(casco — ")
    assert inp["escopo_indi"] is True


def test_input_sintetico_nao_entra_na_fila_de_ingestao():
    """Nasce Disponível: é placeholder, não trabalho de ingestão (regra 26)."""
    r = pub.build_casca_rows([_casca()], existentes=set())
    assert r["inputs"][0]["modernizada_auto"] == "Disponível"
    assert r["egp_inputs"][0]["modernizada_auto"] == "Disponível"


def test_egp_input_amarra_o_projeto_ao_input_sintetico():
    """É esta linha (grão projeto×input) que faz a casca aparecer na aba EGPs."""
    r = pub.build_casca_rows([_casca()], existentes=set())
    (ei,) = r["egp_inputs"]
    assert ei["projeto"] == "Cobranças__Project_X"
    assert ei["chave_canonica"] == "casco::Cobranças__Project_X"
    assert ei["escopo_indi"] is True


def test_casca_que_colide_com_projeto_real_e_ignorada():
    """O real manda: não duplicar nó nem inventar input sintético em cima dele."""
    r = pub.build_casca_rows([_casca()], existentes={"Cobranças__Project_X"})
    assert r["cascas"] == [] and r["nodes"] == [] and r["inputs"] == [] and r["egp_inputs"] == []


def test_colunas_do_input_batem_com_as_de_um_input_real():
    """inputs_rows vai inteiro para o INSERT — chave faltando quebraria o publish."""
    r = pub.build_casca_rows([_casca()], existentes=set())
    esperado = {"chave_canonica", "artifact", "categoria", "origem", "source_types",
                "qtd_projetos", "areas", "escopo_indi", "modernizada_auto",
                "paths_fisicos", "n_paths_fisicos"}
    assert set(r["inputs"][0]) == esperado
    assert set(r["egp_inputs"][0]) == {"projeto", "area", "onda", "escopo_indi", "ciclo_id",
                                       "chave_canonica", "artifact", "categoria",
                                       "source_types", "modernizada_auto"}


def test_lista_vazia_nao_explode():
    r = pub.build_casca_rows([], existentes=set())
    assert r == {"cascas": [], "nodes": [], "inputs": [], "egp_inputs": []}


# ------------------------------------------------- armadilha 1: sas_escopo

def test_linha_de_escopo_por_casca():
    """`recompute_escopo()` reseta escopo_indi de quem não está em sas_escopo — sem esta
    linha a flag se apaga sozinha no próximo recompute (regra 24)."""
    linhas = pub.casca_escopo_rows([_casca()], existentes=set(), cap="2026-09-28T00:00:00")
    (e,) = linhas
    assert e["projeto"] == "Cobranças__Project_X"
    assert e["area"] == "Cobrança"
    assert e["origem"] == "casca"
    assert e["status_extracao"] != "faltante"   # a casca ESTÁ no grafo (a contagem é barrada
                                               # no funil por área, não aqui — regra 27)
    assert e["id"] and e["created_at"] == "2026-09-28T00:00:00"


def test_escopo_nao_duplica_projeto_ja_cadastrado():
    """Idempotente: republish não pode empilhar a mesma casca (nem ressuscitar um
    soft-delete feito pela gestão no app)."""
    assert pub.casca_escopo_rows([_casca()], existentes={"Cobranças__Project_X"}, cap="x") == []


def test_colunas_do_escopo_batem_com_esc_cols():
    linhas = pub.casca_escopo_rows([_casca()], existentes=set(), cap="x")
    assert set(linhas[0]) == {"id", "egp_dor1", "area", "status_extracao", "projeto",
                              "origem", "created_by", "created_at"}


# ------------------------------------------- a casca é um `extra` (regra 27)

def test_recompute_do_publish_exclui_a_casca_do_funil_por_area():
    """A linha em sas_escopo serve à VISIBILIDADE, não à contagem (§3.6.24 revista em
    28/09): sem esta guarda, o funil por área da Cobrança subiria +5 no primeiro
    recompute. O bloco do publish espelha o do backend — os dois têm de ter a guarda."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    pub_src = open(os.path.join(aqui, "publish_to_databricks.py"), encoding="utf-8").read()
    main_src = open(os.path.join(aqui, "app", "backend", "main.py"), encoding="utf-8").read()
    guarda = "coalesce(origem, '') <> 'casca'"
    # backend: o predicado é uma constante montada a partir de vinculos.ORIGEM_CASCA
    assert "SQL_ESC_NAO_EXTRA" in main_src
    # publish: statement literal, sem import do backend — a guarda vem escrita
    insert = [ln for ln in pub_src.splitlines() if "FROM {T_ESC} WHERE ativo IS NOT false" in ln]
    assert insert, "bloco do funil por área não encontrado no publish"
    assert all(guarda in ln for ln in insert), insert
