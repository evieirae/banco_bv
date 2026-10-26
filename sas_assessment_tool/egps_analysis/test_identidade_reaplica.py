# -*- coding: utf-8 -*-
"""A reaplicação dos colapsos de identidade (ticket 25, camada 2).

A semântica testada aqui foi LIDA de prod, não inventada: comparando uma chave colapsada
tabela a tabela contra um clone pós-republish, o colapso reponta o par em `sas_egp_inputs`
e apaga a linha do alias em `sas_inputs_monitor` e `sas_resumo_inputs`, sem tocar no
canônico.
"""
import identidade_reaplica as r

ALIAS, ALVO = "tabela::LEADS.ABANDONO", "tabela::ABANDONO.ABANDONO"
DEFAULT = {"etapa": "A Receber", "status": "A Iniciar", "responsavel": None, "observacao": None}


def _mon(**extra):
    m = {ALVO: dict(DEFAULT, chave_canonica=ALVO)}
    m[ALIAS] = dict(DEFAULT, chave_canonica=ALIAS, **extra)
    return m


def test_colapso_no_estado_de_fabrica_e_aceito():
    aceitos, recusas = r.plano({ALIAS: ALVO}, _mon())
    assert aceitos == {ALIAS: ALVO} and recusas == []


def test_alias_com_trabalho_humano_e_RECUSADO():
    """A regra de 23/09: estado não se propaga entre irmãos. Apagar o alias jogaria fora
    trabalho de gente, então o colapso não acontece — e diz por quê."""
    for campo, valor in [("etapa", "Modernizado"), ("status", "Em ingestão"),
                         ("responsavel", "fulano"), ("observacao", "combinado com a área")]:
        aceitos, recusas = r.plano({ALIAS: ALVO}, _mon(**{campo: valor}))
        assert aceitos == {}, campo
        assert recusas and "estado humano" in recusas[0][2], campo


def test_descartar_estado_explicito_libera():
    aceitos, recusas = r.plano({ALIAS: ALVO}, _mon(etapa="Modernizado"), descartar_estado=True)
    assert aceitos == {ALIAS: ALVO} and recusas == []


def test_alvo_ausente_e_RECUSADO():
    """Apagar o alias sem o canônico existir perderia o input inteiro."""
    aceitos, recusas = r.plano({ALIAS: ALVO}, {ALIAS: dict(DEFAULT, chave_canonica=ALIAS)})
    assert aceitos == {}
    assert recusas[0][2] == "alvo ausente em sas_inputs_monitor"


def test_idempotente_alias_ja_colapsado_sai_do_plano():
    """2ª rodada: o alias não está mais no monitor. Não é recusa — é nada a fazer."""
    aceitos, recusas = r.plano({ALIAS: ALVO}, {ALVO: dict(DEFAULT, chave_canonica=ALVO)})
    assert aceitos == {} and recusas == []


def test_modernizada_auto_nao_bloqueia():
    """Detecção automática se refaz no publish; tratá-la como trabalho humano travaria o
    colapso por um dado que se recalcula sozinho."""
    assert r.sem_trabalho_humano(dict(DEFAULT, modernizada_auto="Disponível")) is True


def test_sql_dedupa_antes_de_repontar_e_apaga_o_alias_por_ultimo():
    """Ordem importa: o EGP pode já ler o canônico (14 casos em 29/09) e o UPDATE criaria
    linha dupla; e apagar a linha do alias antes de repontar deixaria par órfão."""
    st = r.sqls({ALIAS: ALVO}, "cat.esq")
    txt = " || ".join(st)
    i_del_par = next(i for i, s in enumerate(st) if "DELETE FROM cat.esq.sas_egp_inputs" in s)
    i_upd_par = next(i for i, s in enumerate(st) if "UPDATE cat.esq.sas_egp_inputs" in s)
    i_del_mon = next(i for i, s in enumerate(st) if "sas_inputs_monitor" in s)
    assert i_del_par < i_upd_par < i_del_mon
    assert "sas_resumo_inputs" in txt and "sas_egp_input_link" in txt
    # o CANÔNICO nunca é apagado
    assert f"DELETE FROM cat.esq.sas_inputs_monitor WHERE chave_canonica = '{ALVO}'" not in txt


def test_sql_escapa_aspas_na_chave():
    st = r.sqls({"tabela::X'Y": ALVO}, "cat.esq")
    assert "tabela::X''Y" in " ".join(st)


def test_plano_vazio_nao_gera_sql():
    assert r.sqls({}, "cat.esq") == []


def test_mapa_ausente_e_noop():
    def read_rows(sql):
        raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")
    aceitos, recusas = r.reaplica(lambda s: None, read_rows, "cat.esq")
    assert aceitos == {} and recusas == []


def test_reaplica_executa_na_ordem_e_so_o_planejado():
    executados = []
    def read_rows(sql):
        if r.TABELA_MAPA in sql:
            return [{"chave_canonica": ALIAS, "chave_canonica_alvo": ALVO}]
        return [dict(DEFAULT, chave_canonica=ALIAS), dict(DEFAULT, chave_canonica=ALVO)]
    aceitos, recusas = r.reaplica(executados.append, read_rows, "cat.esq")
    assert aceitos == {ALIAS: ALVO} and recusas == []
    assert executados == r.sqls(aceitos, "cat.esq") + r.sqls_flags({ALVO}, "cat.esq")


def test_reaplica_com_recusa_nao_COLAPSA_nada():
    executados = []
    def read_rows(sql):
        if r.TABELA_MAPA in sql:
            return [{"chave_canonica": ALIAS, "chave_canonica_alvo": ALVO}]
        return [dict(DEFAULT, chave_canonica=ALIAS, etapa="Modernizado"),
                dict(DEFAULT, chave_canonica=ALVO)]
    aceitos, recusas = r.reaplica(executados.append, read_rows, "cat.esq")
    assert aceitos == {} and len(recusas) == 1
    # nenhuma escrita que MOVA identidade — o recompute de flag pode rodar, ele so re-deriva
    assert not [x for x in executados if "chave_canonica =" in x and "escopo_indi" not in x]
    assert executados == r.sqls_flags({ALVO}, "cat.esq")


def test_recompute_de_flags_roda_SEMPRE_e_nao_so_nos_colapsos_novos():
    """A reaplicacao e idempotente: na 2a rodada o plano vem vazio. Se o recompute
    dependesse de haver colapso aceito, ele nunca repararia o que a rodada anterior deixou
    torto — que foi exatamente o caso do `CP.MIS_TABLEAU_GERAL_2`."""
    executados = []
    def read_rows(sql):
        if r.TABELA_MAPA in sql:
            return [{"chave_canonica": ALIAS, "chave_canonica_alvo": ALVO}]
        return [dict(DEFAULT, chave_canonica=ALVO)]      # alias JA colapsado
    aceitos, recusas = r.reaplica(executados.append, read_rows, "cat.esq")
    assert aceitos == {} and recusas == []               # nada a colapsar
    assert executados == r.sqls_flags({ALVO}, "cat.esq")  # e ainda assim recomputou


def test_sql_recomputa_escopo_indi_dos_canonicos():
    """O defeito que a 1a versao tinha: repontar o par muda QUEM le a chave, e `escopo_indi`
    e derivada dos pares — mas quem a calcula e o publish, que ja passou. Sem isto o
    `CP.MIS_TABLEAU_GERAL_2` ficou com 2 pares de escopo e a flag false, contando como
    dependencia em vez de escopo."""
    upd = r.sqls_flags({ALVO}, "cat.esq")
    assert len(upd) == 2, upd
    assert upd[0].startswith("UPDATE cat.esq.sas_inputs_monitor SET escopo_indi = false")
    assert "SET escopo_indi = true" in upd[1] and "sas_egp_inputs" in upd[1]
    # cirurgico: so os ALVOS, nunca a tabela inteira
    for u in upd:
        assert ALVO in u and "WHERE chave_canonica IN" in u
    assert r.sqls_flags(set(), "cat.esq") == []


def test_recompute_cita_cada_alvo_uma_vez_so():
    upd = r.sqls_flags([ALVO, ALVO], "cat.esq")
    assert len(upd) == 2 and upd[0].count(ALVO) == 1
