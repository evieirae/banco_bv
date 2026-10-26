#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roll-up de família (ticket 02): `_agrega_familias` / `_estado_familia` do main.py.

Não bate no warehouse: os dois helpers que consultam o banco (`_familias_corpus` e
`_familia_egp_counts`) são substituídos por mapas sintéticos. O que está sob teste é a
REGRA do ADR 0002 — safra terminal não conta nem segura, consumidor é distinto por
família, e auto só vale para a família quando vale para todas as safras.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402


def _safra(art, **kw):
    """Linha de input no grão safra, com os defaults de uma safra pendente crua."""
    r = {"chave_canonica": f"tabela::{art}", "artifact": art, "categoria": "tabela",
         "origem": "SAS/Local (externo)", "source_types": "table_in", "qtd_projetos": 1,
         "areas": "Cobranças", "area_principal": "Cobranças", "escopo_indi": True,
         "modernizada_auto": "A ingerir", "etapa": None, "status": None,
         "responsavel": None, "observacao": None, "orfao": False,
         "paths_fisicos": "", "n_paths_fisicos": 0, "vinculo_ativo": True,
         "ex_dependencia": False, "autoprodutor_candidato": False, "autoprodutor_egp": None}
    r.update(kw)
    return r


@pytest.fixture
def corpus(monkeypatch):
    """Instala um corpus sintético; devolve uma função para declarar famílias."""
    def instalar(familias_map, counts=None):
        chave, membros = {}, {}
        for fam, arts in familias_map.items():
            for a in arts:
                eff = fam if len(arts) > 1 else a
                chave[("tabela", a)] = eff
                membros.setdefault(("tabela", eff), []).append(a)
        monkeypatch.setattr(M, "_familias_corpus",
                            lambda: {"chave": chave, "membros": membros})
        monkeypatch.setattr(M, "_familia_egp_counts", lambda: counts or {})
    return instalar


# ---------------------------------------------------------------- roll-up de estado

def test_familia_com_safras_sanitizadas_e_vivas_fala_pelas_vivas(corpus):
    """O caso que define a regra: 47 Sanitizadas + 11 vivas = 1 input pendente."""
    arts = [f"GRIMALDI.CARGA_MASSIFICADOS_2025{m:02d}" for m in range(1, 13)]
    corpus({"GRIMALDI.CARGA_MASSIFICADOS": arts})
    rows = ([_safra(a, status="Sanitizado") for a in arts[:9]]
            + [_safra(a, etapa="Pré-Working", status="Em Andamento") for a in arts[9:]])
    out = M._agrega_familias(rows)
    assert len(out) == 1
    f = out[0]
    assert f["is_familia"] is True
    assert f["artifact"] == "GRIMALDI.CARGA_MASSIFICADOS"
    assert f["chave_canonica"] == "familia::tabela::GRIMALDI.CARGA_MASSIFICADOS"
    assert f["n_safras"] == 12 and f["n_safras_pendentes"] == 3
    # estado da família = o da safra PENDENTE menos avançada (as Sanitizadas não seguram)
    assert (f["etapa"], f["status"]) == ("Pré-Working", "Em Andamento")
    assert M.py_aingerir(f) is True


def test_sanitizadas_na_MESMA_etapa_nao_votam_no_status(corpus):
    """Regressão: `Sanitizado` é STATUS, não etapa — a safra sanitizada fica em
    py_eff_etapa "A Receber", igual a uma safra crua. Com a moda saindo sobre TODOS os
    membros daquela etapa, 47 sanitizadas abafavam 1 pendente e a família se declarava
    "Sanitizado" (py_modern -> True, fora do universo a ingerir) com
    n_safras_pendentes=1 na mesma linha. O teste irmão acima não pegava isto porque lá
    as vivas estão em OUTRA etapa, então as terminais não votavam."""
    arts = [f"LIB.SAFRA_2025{m:02d}" for m in range(1, 13)]
    corpus({"LIB.SAFRA": arts})
    rows = ([_safra(a, status="Sanitizado") for a in arts[:11]]
            + [_safra(arts[11])])                      # 1 pendente crua, mesma etapa
    f = M._agrega_familias(rows)[0]
    assert f["n_safras_pendentes"] == 1
    assert f["etapa"] == "A Receber"
    assert f["status"] != "Sanitizado", "safra terminal decidiu o status da família"
    assert M.py_aingerir(f) is True, "família com safra pendente saiu do universo a ingerir"


def test_familia_toda_sanitizada_continua_sanitizada(corpus):
    """Contraprova: sem nenhuma pendente, a família fala pelas terminais — e aí
    `Sanitizado` é a resposta certa (não pode virar 'A Iniciar' com o fix acima)."""
    arts = ["LIB.T_202501", "LIB.T_202502", "LIB.T_202503"]
    corpus({"LIB.T": arts})
    f = M._agrega_familias([_safra(a, status="Sanitizado") for a in arts])[0]
    assert f["status"] == "Sanitizado"
    assert f["n_safras_pendentes"] == 0
    assert M.py_aingerir(f) is False


def test_familia_pendente_fala_pela_safra_menos_avancada(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502", "LIB.X_202503"]})
    out = M._agrega_familias([
        _safra("LIB.X_202501", etapa="Ingestão PRD", status="Em Andamento"),
        _safra("LIB.X_202502", etapa="A Receber", status="A Iniciar"),
        _safra("LIB.X_202503", etapa="Modernizado", status="Concluído"),
    ])
    assert (out[0]["etapa"], out[0]["status"]) == ("A Receber", "A Iniciar")
    assert out[0]["n_safras_pendentes"] == 2


def test_familia_toda_resolvida_sai_da_fila(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    out = M._agrega_familias([
        _safra("LIB.X_202501", status="Sanitizado"),
        _safra("LIB.X_202502", etapa="Modernizado", status="Concluído",
               modernizada_auto="Disponível"),
    ])
    f = out[0]
    assert f["n_safras_pendentes"] == 0
    assert M.py_aingerir(f) is False
    # sem pendente, fala pela mais avançada
    assert f["etapa"] == "Modernizado"


def test_status_concluido_em_etapa_intermediaria_nao_resolve(corpus):
    """`Concluído` é 'essa etapa acabou', não 'input resolvido' — a família segue pendente."""
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    out = M._agrega_familias([
        _safra("LIB.X_202501", etapa="Recebido", status="Concluído"),
        _safra("LIB.X_202502", etapa="Recebido", status="Concluído"),
    ])
    assert out[0]["n_safras_pendentes"] == 2
    assert M.py_aingerir(out[0]) is True


def test_estado_misto_sinalizado(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    misto = M._agrega_familias([_safra("LIB.X_202501", status="Sanitizado"),
                                _safra("LIB.X_202502")])
    igual = M._agrega_familias([_safra("LIB.X_202501"), _safra("LIB.X_202502")])
    assert misto[0]["estado_misto"] is True
    assert igual[0]["estado_misto"] is False


# ---------------------------------------------------------------- contagens e uniões

def test_consumidor_e_distinto_por_familia_nunca_soma(corpus):
    """O mesmo EGP lê 47 safras num `SET` só: somar qtd_projetos daria 47 consumidores."""
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502", "LIB.X_202503"]},
           counts={("tabela", "LIB.X"): {"qtd": 2, "ativos": 1}})
    out = M._agrega_familias([_safra("LIB.X_202501", qtd_projetos=2),
                              _safra("LIB.X_202502", qtd_projetos=2),
                              _safra("LIB.X_202503", qtd_projetos=1)])
    assert out[0]["qtd_projetos"] == 2
    assert out[0]["n_proj_ativos"] == 1


def test_sem_contagem_no_mapa_usa_o_maior_nunca_a_soma(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]}, counts={})
    out = M._agrega_familias([_safra("LIB.X_202501", qtd_projetos=3),
                              _safra("LIB.X_202502", qtd_projetos=1)])
    assert out[0]["qtd_projetos"] == 3


def test_auto_disponivel_so_quando_todas_as_safras_estao(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    parcial = M._agrega_familias([_safra("LIB.X_202501", modernizada_auto="Disponível"),
                                  _safra("LIB.X_202502")])
    todas = M._agrega_familias([_safra("LIB.X_202501", modernizada_auto="Disponível"),
                                _safra("LIB.X_202502", modernizada_auto="Disponível")])
    assert parcial[0]["modernizada_auto"] == "A ingerir"
    assert todas[0]["modernizada_auto"] == "Disponível"


def test_unioes_e_consensos(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    out = M._agrega_familias([
        _safra("LIB.X_202501", areas="Cobranças", source_types="table_in",
               paths_fisicos="N:/a", origem="SAS/Local (externo)", responsavel="ana@x"),
        _safra("LIB.X_202502", areas="Riscos", source_types="table_in | sql_in",
               paths_fisicos="N:/b", origem="SAS/Local (dependência)", responsavel="ana@x"),
    ])
    f = out[0]
    assert f["areas"] == "Cobranças | Riscos"
    assert f["source_types"] == "sql_in | table_in"
    assert f["paths_fisicos"] == "N:/a | N:/b" and f["n_paths_fisicos"] == 2
    assert f["responsavel"] == "ana@x"                    # consenso
    assert f["origens"] == "SAS/Local (dependência) | SAS/Local (externo)"   # origem mista


def test_responsavel_divergente_vira_none(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    out = M._agrega_familias([_safra("LIB.X_202501", responsavel="ana@x"),
                              _safra("LIB.X_202502", responsavel="bob@x")])
    assert out[0]["responsavel"] is None


def test_vinculo_e_ex_dependencia(corpus):
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502"]})
    out = M._agrega_familias([
        _safra("LIB.X_202501", vinculo_ativo=False, ex_dependencia=True),
        _safra("LIB.X_202502", vinculo_ativo=True, ex_dependencia=False)])
    assert out[0]["vinculo_ativo"] is True        # basta uma safra com vínculo vivo
    assert out[0]["ex_dependencia"] is False      # só é ex-dep se TODAS forem


def test_intervalo_de_safras(corpus):
    corpus({"LIB.X": ["LIB.X_202411", "LIB.X_202502", "LIB.X_2024"]})
    out = M._agrega_familias([_safra("LIB.X_202411"), _safra("LIB.X_202502"),
                              _safra("LIB.X_2024")])
    assert out[0]["safra_min"] == "202411" and out[0]["safra_max"] == "202502"
    assert out[0]["safras_sem_mes"] == 1          # ano solto não entra no intervalo


def test_familia_e_decidida_pelo_corpus_nao_pelo_recorte(corpus):
    """Invariante 3 na agregação: se o CORPUS diz que é família, a linha é família mesmo
    que só UMA safra esteja no recorte. Decidir pelo recorte fazia a mesma tabela ter chave
    de safra num escopo e de família noutro — e a subtração "inputs das deps" da landing
    achava 2 chaves novas que eram a mesma família (bug pego em 14/09)."""
    corpus({"LIB.X": ["LIB.X_202501", "LIB.X_202502", "LIB.X_202503"]})
    out = M._agrega_familias([_safra("LIB.X_202502")])        # recorte com 1 safra só
    assert len(out) == 1
    f = out[0]
    assert f["is_familia"] is True
    assert f["chave_canonica"] == "familia::tabela::LIB.X"
    assert f["n_safras"] == 3                 # tamanho da FAMÍLIA (corpus)
    assert f["n_safras_no_recorte"] == 1      # o que está sendo contado neste recorte
    assert f["n_safras_pendentes"] == 1


# ---------------------------------------------------------------- linhas soltas e ordem

def test_intervalo_normaliza_token_diario_para_mes(corpus):
    """Família pode misturar token mensal e diário; o intervalo exibido é sempre AAAAMM."""
    corpus({"LIB.X": ["LIB.X_20240826", "LIB.X_202502"]})
    out = M._agrega_familias([_safra("LIB.X_20240826"), _safra("LIB.X_202502")])
    assert (out[0]["safra_min"], out[0]["safra_max"]) == ("202408", "202502")


def test_safra_sem_irma_passa_intacta(corpus):
    corpus({"CORP.HISTORICO_2016": ["CORP.HISTORICO_2016"]})
    linha = _safra("CORP.HISTORICO_2016")
    out = M._agrega_familias([linha])
    assert out == [linha]                          # mesma linha, sem campos de família
    assert "is_familia" not in out[0]


def test_ordem_por_consumidores_depois_nome(corpus):
    corpus({"LIB.A": ["LIB.A_202501", "LIB.A_202502"],
            "LIB.B": ["LIB.B_202501", "LIB.B_202502"]},
           counts={("tabela", "LIB.A"): {"qtd": 1, "ativos": 0},
                   ("tabela", "LIB.B"): {"qtd": 9, "ativos": 0}})
    out = M._agrega_familias([_safra("LIB.A_202501"), _safra("LIB.A_202502"),
                              _safra("LIB.B_202501"), _safra("LIB.B_202502")])
    assert [r["artifact"] for r in out] == ["LIB.B", "LIB.A"]


def test_lista_vazia(corpus):
    corpus({})
    assert M._agrega_familias([]) == []


# ---- nome de exibição da família (pedido 2026-09-16) ---------------------------------

def test_nome_exibicao_marca_posicao_da_safra(corpus):
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"]})
    out = M._agrega_familias([_safra("GRIM.CARGA_202505"), _safra("GRIM.CARGA_202506")])
    assert out[0]["nome_exibicao"] == "GRIM.CARGA_{SAFRA}"
    assert out[0]["artifact"] == "GRIM.CARGA"        # chave segue sem o marcador


def test_nome_exibicao_com_data_no_meio(corpus):
    corpus({"ALVESDS.EMP_8_GCP": ["ALVESDS.EMP_8_20250124_GCP", "ALVESDS.EMP_8_20250125_GCP"]})
    out = M._agrega_familias([_safra("ALVESDS.EMP_8_20250124_GCP"),
                              _safra("ALVESDS.EMP_8_20250125_GCP")])
    assert out[0]["nome_exibicao"] == "ALVESDS.EMP_8_{SAFRA}_GCP"


def test_nome_exibicao_desempata_determinismo(corpus):
    """Membros com a data em posições diferentes caem na mesma chave: rótulo estável."""
    corpus({"A_B": ["A_202505_B", "A_B_202506", "A_B_202507"]})
    out = M._agrega_familias([_safra("A_202505_B"), _safra("A_B_202506"), _safra("A_B_202507")])
    assert out[0]["nome_exibicao"] == "A_B_{SAFRA}"   # posição mais comum vence


def test_linha_solta_nao_ganha_nome_exibicao(corpus):
    """Input sem irmã segue linha física: sem marcador, o nome é o real."""
    corpus({"SOZINHA.TAB": ["SOZINHA.TAB"]})
    out = M._agrega_familias([_safra("SOZINHA.TAB")])
    assert "nome_exibicao" not in out[0] and out[0]["artifact"] == "SOZINHA.TAB"


def test_nome_exibicao_ignora_membro_sem_data(corpus):
    """Família com a tabela "corrente" + a datada (`X` e `X_2026`): o rótulo marca a data.

    O empate alfabético do `_moda` fazia o nome SEM marcador ganhar — a família aparecia
    com cara de input solto. Caso real no corpus: B_GERAL.DIAS_UTEIS (+ _2026).
    """
    corpus({"B_GERAL.DIAS_UTEIS": ["B_GERAL.DIAS_UTEIS", "B_GERAL.DIAS_UTEIS_2026"]})
    out = M._agrega_familias([_safra("B_GERAL.DIAS_UTEIS"), _safra("B_GERAL.DIAS_UTEIS_2026")])
    assert out[0]["nome_exibicao"] == "B_GERAL.DIAS_UTEIS_{SAFRA}"
