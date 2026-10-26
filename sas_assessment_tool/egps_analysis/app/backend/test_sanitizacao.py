# -*- coding: utf-8 -*-
"""Testes da sanitização DERIVADA de input (sem DB, sem rede) — §3.4.18 da spec
2026-09-24-egps-atualizados-unificacao-design.md.

Régua (uma só, §3.4.17 desde 28/09/2026): input cujos consumidores no recorte ativo
estão TODOS resolvidos — despriorizados (§3.4.18), antecessores com sucessor (§3.4.15)
ou uma MISTURA dos dois — sai da fila de ingestão como `Sanitizado`: derivado, sem
gravar status. O sucessor nunca está nesses conjuntos, e por isso segura o input.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import sanitizacao as s


DESP = {"Cob__Velho", "Cob__Velho2"}


def test_todos_consumidores_despriorizados_sanitiza():
    cons = {"tabela::A": {"Cob__Velho", "Cob__Velho2"}}
    m = s.motivos_derivados(cons, DESP, set(), pendentes={"tabela::A"})
    assert m == {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS}


def test_um_consumidor_vivo_nao_toca():
    # ≥1 consumidor não despriorizado: o input segue sendo trabalho de alguém.
    cons = {"tabela::A": {"Cob__Velho", "Cob__Vivo"}}
    assert s.motivos_derivados(cons, DESP, set(), pendentes={"tabela::A"}) == {}


def test_sem_consumidor_no_recorte_nao_toca():
    # Ninguém decidiu nada sobre este input — sanitizar seria agir sobre o vazio.
    assert s.motivos_derivados({"tabela::A": set()}, DESP, set(), {"tabela::A"}) == {}
    assert s.motivos_derivados({}, DESP, set(), {"tabela::A"}) == {}


def test_repriorizar_devolve_a_fila_sem_intervencao():
    # Mesma entrada, só o conjunto de despriorizados encolhe (a gestão repriorizou
    # Cob__Velho2): o input volta à fila sozinho, sem nada ter sido gravado/apagado.
    cons = {"tabela::A": {"Cob__Velho", "Cob__Velho2"}}
    assert s.motivos_derivados(cons, DESP, set(), {"tabela::A"})
    assert s.motivos_derivados(cons, {"Cob__Velho"}, set(), {"tabela::A"}) == {}


def test_ja_resolvido_a_mao_fica_como_esta():
    # As 202 chaves já sanitizadas na mão (e as já modernizadas) não estão em
    # `pendentes` — a regra derivada não as reclassifica nem as re-rotula.
    cons = {"tabela::A": {"Cob__Velho"}}
    assert s.motivos_derivados(cons, DESP, set(), pendentes=set()) == {}


def test_input_sintetico_de_casca_fica_de_fora():
    # §3.4.26: `casco::<projeto>` é placeholder, não input exclusivo do antecessor.
    cons = {"casco::Cob__Velho": {"Cob__Velho"}}
    assert s.motivos_derivados(cons, DESP, set(), {"casco::Cob__Velho"}) == {}


def test_despriorizados_vazio_nao_sanitiza_nada():
    cons = {"tabela::A": {"Cob__Velho"}, "tabela::B": {"Cob__Vivo"}}
    assert s.motivos_derivados(cons, set(), set(), {"tabela::A", "tabela::B"}) == {}
    assert s.motivos_derivados(cons, None, set(), {"tabela::A"}) == {}


def test_projeto_vazio_nao_conta_como_consumidor():
    # Linha sem projeto não transforma "sem consumidor" em "todos despriorizados".
    assert s.motivos_derivados({"tabela::A": {None, ""}}, DESP, set(), {"tabela::A"}) == {}


def test_aplica_em_linhas_sobrescreve_status_e_guarda_o_real():
    rows = [{"chave_canonica": "tabela::A", "etapa": "A Receber", "status": "A Iniciar"},
            {"chave_canonica": "tabela::B", "etapa": "A Receber", "status": "A Iniciar"}]
    s.aplica_em_linhas(rows, {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS})
    a, b = rows
    assert a["status"] == "Sanitizado"
    assert a["status_real"] == "A Iniciar"          # o real continua legível por baixo
    assert a["sanitizado_derivado"] == s.MOTIVO_SO_DESPRIORIZADOS
    assert a["sanitizado_motivo"] == "só consumidores despriorizados"
    # etapa EXIBIDA = Modernizado (decisão 14/10/2026): o input sanitizado por derivação
    # aparece como Modernizado + Sanitizado; a gravada continua legível por baixo
    assert a["etapa"] == "Modernizado"
    assert a["etapa_real"] == "A Receber"
    # linha fora dos motivos: NADA anotado (nem chave nova)
    assert b["status"] == "A Iniciar"
    assert b["etapa"] == "A Receber"
    assert "sanitizado_derivado" not in b
    assert "status_real" not in b
    assert "etapa_real" not in b


def test_aplica_em_linhas_sem_status_humano():
    # 22 das 132 chaves não têm status gravado: status_real fica None, não "".
    rows = [{"chave_canonica": "tabela::A", "etapa": None, "status": None}]
    s.aplica_em_linhas(rows, {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS})
    assert rows[0]["status"] == "Sanitizado"
    assert rows[0]["status_real"] is None
    assert rows[0]["etapa"] == "Modernizado"
    assert rows[0]["etapa_real"] is None


def test_etapa_exibida_nao_muda_o_que_conta():
    """A etapa Modernizado é só exibição: Sanitizado já resolvia o input em toda régua de
    contagem (py_modern/py_aingerir/py_sanitizado), com qualquer etapa por baixo."""
    from input_state import py_modern, py_aingerir, py_sanitizado
    crua = {"chave_canonica": "tabela::A", "etapa": "A Receber", "status": "A Iniciar",
            "modernizada_auto": "A ingerir"}
    antes = dict(crua, status="Sanitizado")              # o overlay como era até 13/10
    depois = s.aplica_em_linhas([dict(crua)], {"tabela::A": s.MOTIVO_SO_ANTECESSOR})[0]
    for f in (py_modern, py_aingerir, py_sanitizado):
        assert f(antes) == f(depois), f.__name__


def test_aplica_em_linhas_tolera_vazio():
    assert s.aplica_em_linhas([], {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS}) == []
    assert s.aplica_em_linhas(None, None) is None
    rows = [{"chave_canonica": "tabela::A", "status": "A Iniciar"}]
    assert s.aplica_em_linhas(rows, {})[0]["status"] == "A Iniciar"


def test_motivo_distingue_as_duas_origens():
    # O motivo é campo, não string fixa: quem lê a linha sabe QUAL régua a tirou da
    # fila. Com a união do §3.4.17 são três casos — ver test_motivo_misto_*.
    assert s.MOTIVO_SO_DESPRIORIZADOS != s.MOTIVO_SO_ANTECESSOR
    assert s.MOTIVO_LABEL[s.MOTIVO_SO_DESPRIORIZADOS] == "só consumidores despriorizados"


def test_status_sanitizado_com_acento_igual_ao_app():
    # Acento/caixa são significativos: é a string que o funil de ingestão casa.
    assert s.STATUS_SANITIZADO == "Sanitizado"


# ---- §3.4.15/16/17: input lido SÓ pelo antecessor de um vínculo -------------------
# O que vale depois do vínculo é o inventário da versão NOVA: o input que só a versão
# velha lia sai da fila. Exclusividade medida contra o ESCOPO ATIVO (§3.4.16), nunca
# contra o corpus — por isso `consumidores_por_chave` é o mesmo recorte da regra irmã.

ANTE = {"Cob__Velho", "Cob__Velho2"}


def test_input_so_do_antecessor_sanitiza():
    cons = {"tabela::A": {"Cob__Velho"}}
    m = s.motivos_derivados(cons, set(), ANTE, pendentes={"tabela::A"})
    assert m == {"tabela::A": s.MOTIVO_SO_ANTECESSOR}


def test_input_lido_por_outro_egp_do_escopo_nao_e_tocado():
    # §3.4.17: basta UM consumidor sem vínculo no escopo p/ o input seguir sendo trabalho.
    cons = {"tabela::A": {"Cob__Velho", "Cob__Vivo"}}
    assert s.motivos_derivados(cons, set(), ANTE, {"tabela::A"}) == {}


def test_input_que_o_sucessor_tambem_le_nao_e_tocado():
    # O sucessor está no recorte (o frontier o traz por regra) e NÃO é antecessor: o
    # input sobreviveu à nova versão, então continua na fila.
    cons = {"tabela::A": {"Cob__Velho", "Cob__Velho__ATU20260924"}}
    assert s.motivos_derivados(cons, set(), ANTE, {"tabela::A"}) == {}


def test_unificado_n_antecessores_ainda_sanitiza():
    # Num Unificado os N antecessores são todos versões velhas: nenhum deles é "outro
    # EGP do escopo" no sentido do §3.4.17.
    cons = {"tabela::A": {"Cob__Velho", "Cob__Velho2"}}
    assert s.motivos_derivados(cons, set(), ANTE, {"tabela::A"}) == {
        "tabela::A": s.MOTIVO_SO_ANTECESSOR}


def test_desfazer_o_vinculo_devolve_o_input_a_fila():
    # Nada foi gravado: some o antecessor do conjunto e a chave volta à fila sozinha.
    cons = {"tabela::A": {"Cob__Velho"}}
    assert s.motivos_derivados(cons, set(), ANTE, {"tabela::A"})
    assert s.motivos_derivados(cons, set(), {"Cob__Velho2"}, {"tabela::A"}) == {}
    assert s.motivos_derivados(cons, set(), set(), {"tabela::A"}) == {}


def test_antecessor_sem_consumidor_ou_ja_resolvido_ou_casca():
    # As mesmas três recusas da regra irmã, pelas mesmas razões.
    assert s.motivos_derivados({"tabela::A": set()}, set(), ANTE, {"tabela::A"}) == {}
    assert s.motivos_derivados({"tabela::A": {"Cob__Velho"}}, set(), ANTE, set()) == {}
    assert s.motivos_derivados({"casco::Cob__Velho": {"Cob__Velho"}}, set(), ANTE,
                               {"casco::Cob__Velho"}) == {}


def test_motivos_derivados_une_as_duas_origens():
    cons = {"tabela::DESP": {"Cob__Desp"},
            "tabela::ANTE": {"Cob__Velho"},
            "tabela::VIVA": {"Cob__Vivo"}}
    m = s.motivos_derivados(cons, despriorizados={"Cob__Desp"}, antecessores=ANTE,
                            pendentes={"tabela::DESP", "tabela::ANTE", "tabela::VIVA"})
    assert m == {"tabela::DESP": s.MOTIVO_SO_DESPRIORIZADOS,
                 "tabela::ANTE": s.MOTIVO_SO_ANTECESSOR}


def test_nas_duas_origens_ao_mesmo_tempo_despriorizado_vence():
    # Consumidor único que é despriorizado E antecessor: o §3.2.9 já resolve esse empate
    # no EGP ("despriorizado vence, o vínculo vira badge") e o input segue a mesma
    # precedência — uma régua só, não duas.
    cons = {"tabela::A": {"Cob__Velho"}}
    m = s.motivos_derivados(cons, despriorizados={"Cob__Velho"}, antecessores={"Cob__Velho"},
                            pendentes={"tabela::A"})
    assert m == {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS}


def test_motivos_derivados_sem_nada_devolve_vazio():
    cons = {"tabela::A": {"Cob__Vivo"}}
    assert s.motivos_derivados(cons, None, None, {"tabela::A"}) == {}


def test_aplica_em_linhas_rotula_a_origem_antecessor():
    rows = [{"chave_canonica": "tabela::A", "etapa": "A Receber", "status": "A Iniciar"}]
    s.aplica_em_linhas(rows, {"tabela::A": s.MOTIVO_SO_ANTECESSOR})
    assert rows[0]["status"] == "Sanitizado"
    assert rows[0]["status_real"] == "A Iniciar"
    assert rows[0]["sanitizado_derivado"] == s.MOTIVO_SO_ANTECESSOR
    assert rows[0]["sanitizado_motivo"] == "só o antecessor, que tem sucessor"


# ---- §3.4.17 (reescrito em 28/09/2026): AS DUAS ORIGENS SE SOMAM -----------------
# A régua passou a ser uma só — "input que só quem não vai trabalhar lê não é trabalho".
# A chave sai da fila quando TODOS os consumidores dela no escopo estão resolvidos,
# inclusive MISTURANDO despriorizado (§3.4.18) e antecessor (§3.4.15).


def test_sucessor_segura_o_input_sozinho():
    # A TRAVA do §3.4.17, e o teste mais importante do arquivo: o sucessor está no
    # recorte e NÃO é antecessor, então é consumidor VIVO. Por mais resolvidos que
    # estejam os demais, se a versão NOVA lê a chave ela continua na fila — é o que
    # impede a régua de sanitizar justamente o inventário que passou a valer.
    cons = {"tabela::A": {"Cob__Desp", "Cob__Velho", "Cob__Velho__ATU20260924"}}
    assert s.motivos_derivados(cons, despriorizados={"Cob__Desp"},
                               antecessores={"Cob__Velho"},
                               pendentes={"tabela::A"}) == {}
    # e sem o sucessor lendo a chave, a MESMA entrada sai da fila: a trava é ele,
    # não outra coisa qualquer.
    cons_sem = {"tabela::A": {"Cob__Desp", "Cob__Velho"}}
    assert s.motivos_derivados(cons_sem, {"Cob__Desp"}, {"Cob__Velho"},
                               {"tabela::A"}) == {"tabela::A": s.MOTIVO_MISTO}


def test_origens_misturadas_saem_da_fila():
    # Um consumidor despriorizado + outro antecessor: ninguém vivo lê. Antes de 28/09
    # cada régua sozinha recusava (nenhuma via "todos os seus consumidores") e a chave
    # ficava na fila; a decisão da gestão uniu as duas.
    cons = {"tabela::A": {"Cob__Desp", "Cob__Velho"}}
    assert s.motivos_derivados(cons, {"Cob__Desp"}, ANTE, {"tabela::A"}) == {
        "tabela::A": s.MOTIVO_MISTO}


def test_motivo_misto_nomeia_as_duas_origens():
    # Critério de aceite: o motivo do caso misto não pode MENTIR sobre a origem —
    # chamá-lo de "só despriorizados" esconderia o antecessor, e vice-versa.
    rotulo = s.MOTIVO_LABEL[s.MOTIVO_MISTO]
    assert "despriorizado" in rotulo and "antecessor" in rotulo
    assert s.MOTIVO_MISTO not in (s.MOTIVO_SO_DESPRIORIZADOS, s.MOTIVO_SO_ANTECESSOR)
    assert set(s.MOTIVO_LABEL) == {s.MOTIVO_SO_DESPRIORIZADOS, s.MOTIVO_SO_ANTECESSOR,
                                   s.MOTIVO_MISTO}


def test_origem_unica_mantem_o_motivo_especifico():
    # A união não apaga os motivos de origem única: quem lê a linha continua sabendo
    # qual régua a tirou da fila.
    cons = {"tabela::D": {"Cob__Desp"}, "tabela::A": {"Cob__Velho"}}
    m = s.motivos_derivados(cons, {"Cob__Desp"}, ANTE, {"tabela::D", "tabela::A"})
    assert m == {"tabela::D": s.MOTIVO_SO_DESPRIORIZADOS,
                 "tabela::A": s.MOTIVO_SO_ANTECESSOR}


def test_empate_continua_vencendo_despriorizado():
    # Consumidor único que é despriorizado E antecessor: o empate do §3.2.9 segue
    # resolvido pelo despriorizado — a união NÃO o transformou em misto.
    cons = {"tabela::A": {"Cob__Velho"}}
    assert s.motivos_derivados(cons, {"Cob__Velho"}, {"Cob__Velho"},
                               {"tabela::A"}) == {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS}


def test_uniao_mantem_as_tres_recusas():
    # Sem consumidor, já resolvida e casca continuam de fora — a união mexe em QUEM
    # conta como resolvido, não em quem a régua se recusa a tocar.
    desp, ante = {"Cob__Desp"}, {"Cob__Velho"}
    assert s.motivos_derivados({"tabela::A": set()}, desp, ante, {"tabela::A"}) == {}
    assert s.motivos_derivados({"tabela::A": {"Cob__Desp", "Cob__Velho"}}, desp, ante,
                               set()) == {}
    assert s.motivos_derivados({"casco::Cob__Velho": {"Cob__Desp", "Cob__Velho"}}, desp,
                               ante, {"casco::Cob__Velho"}) == {}


def test_uniao_continua_reversivel():
    # Repriorizar UM dos dois consumidores devolve a chave à fila, sem nada gravado.
    cons = {"tabela::A": {"Cob__Desp", "Cob__Velho"}}
    assert s.motivos_derivados(cons, {"Cob__Desp"}, {"Cob__Velho"}, {"tabela::A"})
    assert s.motivos_derivados(cons, set(), {"Cob__Velho"}, {"tabela::A"}) == {}
    assert s.motivos_derivados(cons, {"Cob__Desp"}, set(), {"tabela::A"}) == {}


def test_aplica_em_linhas_rotula_o_caso_misto():
    rows = [{"chave_canonica": "tabela::A", "etapa": "A Receber", "status": "A Iniciar"}]
    s.aplica_em_linhas(rows, {"tabela::A": s.MOTIVO_MISTO})
    assert rows[0]["status"] == "Sanitizado"
    assert rows[0]["status_real"] == "A Iniciar"
    assert rows[0]["sanitizado_derivado"] == s.MOTIVO_MISTO
    assert rows[0]["sanitizado_motivo"] == s.MOTIVO_LABEL[s.MOTIVO_MISTO]


# ---- fragilidade: a fila pode crescer sozinha ------------------------------------
# A exclusividade é medida contra o ESCOPO ATIVO (§3.4.16), não contra o corpus: uma
# chave pode estar fora da fila só porque os outros consumidores dela estão fora do
# escopo. Se qualquer um deles entrar, a chave VOLTA — sem ninguém ter gravado nada.


def test_fragilidade_conta_chaves_e_egps():
    motivos = {"tabela::A": s.MOTIVO_SO_DESPRIORIZADOS,
               "tabela::B": s.MOTIVO_SO_ANTECESSOR,
               "tabela::C": s.MOTIVO_MISTO}
    fora = {"tabela::A": {"Out__X"}, "tabela::B": {"Out__X", "Out__Y"}}
    f = s.fragilidade(motivos, fora)
    assert f["n_chaves"] == 2          # tabela::C não tem consumidor fora do escopo
    assert f["n_egps"] == 2
    assert f["chaves"] == ["tabela::A", "tabela::B"]


def test_fragilidade_rollup_inverso_por_egp():
    # A pergunta acionável: "quem é o EGP que, se entrar, me devolve N chaves".
    motivos = {c: s.MOTIVO_SO_DESPRIORIZADOS for c in ("t::A", "t::B", "t::C")}
    fora = {"t::A": {"Out__X"}, "t::B": {"Out__X"}, "t::C": {"Out__X", "Out__Y"}}
    por = s.fragilidade(motivos, fora)["por_egp"]
    assert [(e["projeto"], e["n_chaves"]) for e in por] == [("Out__X", 3), ("Out__Y", 1)]
    assert por[0]["chaves"] == ["t::A", "t::B", "t::C"]     # dá p/ ver QUAIS


def test_fragilidade_so_olha_chave_sanitizada():
    # Chave que segue na fila não é frágil: ela já está sendo trabalhada.
    f = s.fragilidade({}, {"tabela::A": {"Out__X"}})
    assert f["n_chaves"] == 0 and f["n_egps"] == 0 and f["por_egp"] == []


def test_fragilidade_ignora_projeto_vazio_e_casca():
    motivos = {"tabela::A": s.MOTIVO_MISTO, "casco::Cob__Velho": s.MOTIVO_MISTO}
    f = s.fragilidade(motivos, {"tabela::A": {None, ""},
                                "casco::Cob__Velho": {"Out__X"}})
    assert f["n_chaves"] == 0 and f["por_egp"] == []


def test_fragilidade_tolera_vazio():
    f = s.fragilidade(None, None)
    assert f == {"n_chaves": 0, "n_egps": 0, "chaves": [], "por_egp": []}


# ---- contadores do log diário ----------------------------------------------------
# SÓ contador, nunca o estado derivado (nenhuma chave vai para o log): o log é foto do
# passado, e o presente é sempre recalculado.


def test_contadores_quebra_por_origem():
    motivos = {"a": s.MOTIVO_SO_DESPRIORIZADOS, "b": s.MOTIVO_SO_DESPRIORIZADOS,
               "c": s.MOTIVO_SO_ANTECESSOR, "d": s.MOTIVO_MISTO}
    c = s.contadores(motivos, n_frageis=3, data="2026-09-28")
    assert c == {"data": "2026-09-28", "total": 4, "n_frageis": 3,
                 s.MOTIVO_SO_DESPRIORIZADOS: 2, s.MOTIVO_SO_ANTECESSOR: 1,
                 s.MOTIVO_MISTO: 1}


def test_contadores_nao_levam_nenhuma_chave():
    # REGRA DURA: se uma chave vazasse p/ o log, o log viraria estado — e desligá-lo
    # mudaria a fila. Só número entra.
    c = s.contadores({"tabela::SEGREDO": s.MOTIVO_MISTO}, n_frageis=1, data="2026-09-28")
    assert "tabela::SEGREDO" not in repr(c)
    assert all(isinstance(v, (int, str)) for v in c.values())


def test_contadores_com_fila_vazia():
    assert s.contadores(None, 0, "2026-09-28") == {
        "data": "2026-09-28", "total": 0, "n_frageis": 0,
        s.MOTIVO_SO_DESPRIORIZADOS: 0, s.MOTIVO_SO_ANTECESSOR: 0, s.MOTIVO_MISTO: 0}
