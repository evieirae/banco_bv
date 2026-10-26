# -*- coding: utf-8 -*-
"""A guarda de identidade (ticket 25): o publish desfez algum colapso?

O que se testa aqui é a RÉGUA, sem banco. O caso real que a originou: dos 101 colapsos
ativos em `sas_input_alias_canonico`, prod tinha 0 chaves soltas e o clone pós-republish
tinha 101 — e ninguém foi avisado.
"""
import identidade_guard as g


def test_colapso_aplicado_passa():
    """Prod em 29/09: as 101 chaves não-canônicas não existem mais soltas no corpus."""
    desfeitos, v = g.verifica({"tabela::LEADS.ABANDONO", "tabela::MOVTO.PERF_AMIGAVEL"},
                              {"tabela::ABANDONO.ABANDONO", "tabela::CARTAO.PERF_AMIGAVEL"})
    assert desfeitos == set()
    assert v == {"colapsos_ativos": 2, "desfeitos": 0, "ok": True}


def test_colapso_desfeito_reprova_e_nomeia_as_chaves():
    """O clone pós-republish: a chave que o mapa manda colapsar voltou a existir."""
    desfeitos, v = g.verifica(
        {"tabela::LEADS.ABANDONO", "tabela::MOVTO.PERF_AMIGAVEL"},
        {"tabela::ABANDONO.ABANDONO", "tabela::LEADS.ABANDONO", "tabela::MOVTO.PERF_AMIGAVEL"})
    assert desfeitos == {"tabela::LEADS.ABANDONO", "tabela::MOVTO.PERF_AMIGAVEL"}
    assert v["desfeitos"] == 2 and v["ok"] is False


def test_mapa_vazio_nao_e_erro():
    """Schema sem decisão de identidade registrada passa — ausência não é violação."""
    _, v = g.verifica(set(), {"tabela::A"})
    assert v == {"colapsos_ativos": 0, "desfeitos": 0, "ok": True}
    _, v2 = g.verifica(None, None)
    assert v2["ok"] is True


def test_chave_do_mapa_que_nem_existe_no_corpus_nao_conta():
    """Mapa pode citar chave que sumiu do corpus por outro motivo: não é colapso desfeito."""
    desfeitos, v = g.verifica({"tabela::SUMIU"}, {"tabela::OUTRA"})
    assert desfeitos == set() and v["ok"] is True


def test_mapa_ausente_no_schema_nao_derruba_o_publish():
    """Schema novo, antes de qualquer decisão: a guarda informa e libera."""
    def read_rows(sql):
        if g.TABELA_MAPA in sql:
            raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")
        return []
    desfeitos, v = g.checa_no_banco(read_rows, "cat.esquema")
    assert desfeitos == set() and v["ok"] is True


def test_checa_no_banco_cruza_as_duas_tabelas():
    def read_rows(sql):
        if g.TABELA_MAPA in sql:
            return [{"chave_canonica": "tabela::LEADS.ABANDONO"}]
        return [{"chave_canonica": "tabela::LEADS.ABANDONO"},
                {"chave_canonica": "tabela::ABANDONO.ABANDONO"}]
    desfeitos, v = g.checa_no_banco(read_rows, "cat.esquema")
    assert desfeitos == {"tabela::LEADS.ABANDONO"}
    assert v["ok"] is False


def test_saida_nomeia_o_que_reprovou():
    desfeitos, v = g.verifica({"tabela::X"}, {"tabela::X"})
    texto = "\n".join(g._linha_de_saida(v, desfeitos))
    assert "DESFEITO" in texto and "tabela::X" in texto


def test_aceita_linha_posicional_do_publish():
    """`read_rows` do publish_to_databricks devolve listas, não dicts. A guarda roda dentro
    dele — assumir dict a deixaria quebrada justamente onde ela mais importa."""
    def read_rows(sql):
        if g.TABELA_MAPA in sql:
            return [["tabela::LEADS.ABANDONO"]]
        return [["tabela::LEADS.ABANDONO"], ["tabela::ABANDONO.ABANDONO"]]
    desfeitos, v = g.checa_no_banco(read_rows, "cat.esquema")
    assert desfeitos == {"tabela::LEADS.ABANDONO"} and v["ok"] is False


def test_linha_vazia_ou_nula_nao_derruba():
    assert g._chaves([[], None, [""], ["tabela::A"], {"chave_canonica": None}]) == {"tabela::A"}


def test_flags_defasadas_pega_a_chave_no_balde_errado():
    """Aprendido errando: a guarda so conferia que o alias sumiu, e a flag derivada ficou
    velha depois da reaplicacao."""
    def read_rows(sql):
        assert "escopo_indi" in sql and "sas_egp_inputs" in sql
        return [{"chave_canonica": "tabela::CP.MIS_TABLEAU_GERAL_2"}]
    assert g.flags_defasadas(read_rows, "cat.esq") == {"tabela::CP.MIS_TABLEAU_GERAL_2"}


def test_flags_defasadas_vazio_quando_tudo_bate():
    assert g.flags_defasadas(lambda sql: [], "cat.esq") == set()


def test_flags_defasadas_nao_derruba_se_a_query_falhar():
    def read_rows(sql):
        raise RuntimeError("coluna ausente")
    assert g.flags_defasadas(read_rows, "cat.esq") == set()
