#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ligação da sanitização DERIVADA no main.py (§3.4.18 da spec da unificação).

A régua pura está em test_sanitizacao.py; aqui se testa o que o main.py faz com ela:
monta o conjunto a partir do recorte ativo, devolve a expressão SQL que entra nos
contadores, e aplica o overlay nas linhas que a aba Inputs serve.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402
from backend import sanitizacao  # noqa: E402

FRONTIER = {"Cob__Velho", "Cob__Vivo"}
SO_DESP = "tabela::SO_DESPRIORIZADO"
COMPART = "tabela::COMPARTILHADA"
SO_ANTE = "tabela::SO_ANTECESSOR"


def _fake_run_sql(pares, pendentes):
    """pares: [(chave, projeto)] de sas_egp_inputs; pendentes: chaves ainda na fila."""
    def _run(sql, want_rows=True, **kw):
        if "sas_egp_inputs" in sql:
            return [{"ch": ch, "pj": pj} for ch, pj in pares]
        if "sas_inputs_monitor" in sql:
            return [{"chave_canonica": ch} for ch in pendentes]
        return []
    return _run


def _derivada(pares, pendentes, despriorizados=("Cob__Velho",), frontier=FRONTIER,
              vinculos=None):
    """`vinculos`: {antecessor: {tipo, sucessor}}, como _vinculos_por_antecessor()."""
    ps = [patch.object(m, "run_sql", side_effect=_fake_run_sql(pares, pendentes)),
          patch.object(m, "_frontier_egps", lambda *a, **k: (set(frontier), set())),
          patch.object(m, "_egps_fora_backlog", lambda: set(despriorizados)),
          patch.object(m, "_vinculos_por_antecessor", lambda: dict(vinculos or {})),
          patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
          patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
    for p in ps:
        p.start()
    try:
        m._bump_gen()          # o conjunto é cacheado por geração
        return m._sanitizacao_derivada()
    finally:
        for p in ps:
            p.stop()
        m._bump_gen()


def test_chave_so_de_despriorizado_entra_no_conjunto():
    d = _derivada([(SO_DESP, "Cob__Velho"), (COMPART, "Cob__Velho"), (COMPART, "Cob__Vivo")],
                  pendentes={SO_DESP, COMPART})
    assert d == {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS}


def test_repriorizar_o_egp_devolve_a_chave_a_fila():
    pares = [(SO_DESP, "Cob__Velho")]
    assert _derivada(pares, {SO_DESP}, despriorizados=("Cob__Velho",))
    # gestão repriorizou Cob__Velho: nada foi gravado, e a chave volta sozinha
    assert _derivada(pares, {SO_DESP}, despriorizados=()) == {}


def test_sem_despriorizado_e_sem_vinculo_nao_consulta_nada():
    chamou = []

    def _run(sql, want_rows=True, **kw):
        chamou.append(sql)
        return []
    ps = [patch.object(m, "run_sql", side_effect=_run),
          patch.object(m, "_frontier_egps", lambda *a, **k: (set(FRONTIER), set())),
          patch.object(m, "_vinculos_por_antecessor", lambda: {}),
          patch.object(m, "_egps_fora_backlog", lambda: set())]
    for p in ps:
        p.start()
    try:
        m._bump_gen()
        assert m._sanitizacao_derivada() == {}
        assert chamou == []      # short-circuit: zero query a mais quando as DUAS
        # origens estão vazias (nenhum despriorizado, nenhum vínculo no recorte)
    finally:
        for p in ps:
            p.stop()
        m._bump_gen()


def test_chave_so_do_antecessor_entra_no_conjunto():
    # §3.4.15: vinculado o sucessor, o que vale é o inventário da versão nova.
    d = _derivada([(SO_ANTE, "Cob__Velho"), (COMPART, "Cob__Velho"), (COMPART, "Cob__Vivo")],
                  pendentes={SO_ANTE, COMPART}, despriorizados=(),
                  vinculos={"Cob__Velho": {"tipo": "Atualizado", "sucessor": "Cob__Novo"}})
    assert d == {SO_ANTE: sanitizacao.MOTIVO_SO_ANTECESSOR}


def test_desfazer_o_vinculo_devolve_a_chave_a_fila():
    pares = [(SO_ANTE, "Cob__Velho")]
    vinc = {"Cob__Velho": {"tipo": "Atualizado", "sucessor": "Cob__Novo"}}
    assert _derivada(pares, {SO_ANTE}, despriorizados=(), vinculos=vinc)
    # vínculo desfeito: nada foi gravado, e a chave volta sozinha no request seguinte
    assert _derivada(pares, {SO_ANTE}, despriorizados=(), vinculos={}) == {}


def test_input_que_o_sucessor_tambem_le_continua_na_fila():
    # O sucessor entra no recorte por regra (§3.1.2) e lê a chave: ela sobreviveu.
    d = _derivada([(SO_ANTE, "Cob__Velho"), (SO_ANTE, "Cob__Novo")],
                  pendentes={SO_ANTE}, despriorizados=(),
                  frontier=FRONTIER | {"Cob__Novo"},
                  vinculos={"Cob__Velho": {"tipo": "Atualizado", "sucessor": "Cob__Novo"}})
    assert d == {}


def test_vinculo_fora_do_recorte_nao_sanitiza():
    # Antecessor que não está no recorte ativo não resolve input nenhum (§3.4.16).
    d = _derivada([(SO_ANTE, "Cob__Vivo")], pendentes={SO_ANTE}, despriorizados=(),
                  vinculos={"Cob__DeOutroEscopo": {"tipo": "Atualizado", "sucessor": "X"}})
    assert d == {}


def test_as_duas_origens_convivem_no_mesmo_conjunto():
    d = _derivada([(SO_DESP, "Cob__Desp"), (SO_ANTE, "Cob__Velho"), (COMPART, "Cob__Vivo")],
                  pendentes={SO_DESP, SO_ANTE, COMPART}, despriorizados=("Cob__Desp",),
                  frontier=FRONTIER | {"Cob__Desp"},
                  vinculos={"Cob__Velho": {"tipo": "Unificado", "sucessor": "Cob__Novo"}})
    assert d == {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS,
                 SO_ANTE: sanitizacao.MOTIVO_SO_ANTECESSOR}


def test_sem_grafo_publicado_devolve_vazio():
    ps = [patch.object(m, "_frontier_egps", side_effect=m.HTTPException(
        502, "Falha SQL: [TABLE_OR_VIEW_NOT_FOUND] sas_lineage_nodes cannot be found")),
          patch.object(m, "_vinculos_por_antecessor", lambda: {}),
          patch.object(m, "_egps_fora_backlog", lambda: {"Cob__Velho"})]
    for p in ps:
        p.start()
    try:
        m._bump_gen()
        assert m._sanitizacao_derivada() == {}
    finally:
        for p in ps:
            p.stop()
        m._bump_gen()


def test_expressao_sql_do_conjunto():
    with patch.object(m, "_sanitizacao_derivada", lambda: {SO_DESP: "so_despriorizados"}):
        sql = m._san_derivada_sql("i.chave_canonica")
        assert sql == f"i.chave_canonica IN ('{SO_DESP}')"
        assert m._san_derivada_sql() == f"e.chave_canonica IN ('{SO_DESP}')"
        # `lnk` completo: vínculo quebrado OU sanitização derivada
        assert m._lnk_resolvido() == (
            f"(coalesce(l.link_broken, false) OR e.chave_canonica IN ('{SO_DESP}'))")
    with patch.object(m, "_sanitizacao_derivada", lambda: {}):
        # sem chave derivada a expressão some do plano, em vez de virar `IN ()` inválido
        assert m._san_derivada_sql() == "false"


def test_dataset_do_escopo_serve_a_linha_como_sanitizado_com_motivo():
    linhas = [{"chave_canonica": SO_DESP, "artifact": "SO_DESPRIORIZADO", "origem": "Transacional",
               "etapa": "A Receber", "status": "A Iniciar", "modernizada_auto": "Não"},
              {"chave_canonica": COMPART, "artifact": "COMPARTILHADA", "origem": "Transacional",
               "etapa": "A Receber", "status": "A Iniciar", "modernizada_auto": "Não"}]
    ps = [patch.object(m, "run_sql", lambda *a, **k: [dict(r) for r in linhas]),
          patch.object(m, "_enrich_n_proj_ativos", lambda rows: rows),
          patch.object(m, "_enrich_vinculo_ativo", lambda rows, w: rows),
          patch.object(m, "_enrich_autoprodutor", lambda rows: rows),
          patch.object(m, "_marca_safra", lambda rows: rows),
          patch.object(m, "_marca_extra", lambda rows: rows),   # marcador de filtro; testado em test_inputs_de_extra.py
          patch.object(m, "_cache_scope_dataset", lambda scope, producer: producer()),
          patch.object(m, "_sanitizacao_derivada",
                       lambda: {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS})]
    for p in ps:
        p.start()
    try:
        rows = {r["chave_canonica"]: r for r in m._dataset_escopo("indi", [])}
    finally:
        for p in ps:
            p.stop()
    so = rows[SO_DESP]
    assert so["status"] == "Sanitizado"                      # rótulo
    assert so["status_real"] == "A Iniciar"                  # nada foi gravado por baixo
    assert so["sanitizado_motivo"] == "só consumidores despriorizados"   # motivo visível
    assert m.py_aingerir(so) is False                        # saiu da fila de ingestão
    # chave com consumidor vivo: intocada
    outra = rows[COMPART]
    assert outra["status"] == "A Iniciar"
    assert "sanitizado_derivado" not in outra
    assert m.py_aingerir(outra) is True


def test_linha_do_antecessor_chega_a_aba_com_o_motivo_certo():
    # Mesma superfície do §3.4.18 (um caminho só, não dois): o overlay do _dataset_escopo
    # tira a chave da fila e o motivo diz QUAL das duas origens a tirou.
    linhas = [{"chave_canonica": SO_ANTE, "artifact": "SO_ANTECESSOR", "origem": "Transacional",
               "etapa": "A Receber", "status": "A Iniciar", "modernizada_auto": "Não"}]
    ps = [patch.object(m, "run_sql", lambda *a, **k: [dict(r) for r in linhas]),
          patch.object(m, "_enrich_n_proj_ativos", lambda rows: rows),
          patch.object(m, "_enrich_vinculo_ativo", lambda rows, w: rows),
          patch.object(m, "_enrich_autoprodutor", lambda rows: rows),
          patch.object(m, "_marca_safra", lambda rows: rows),
          patch.object(m, "_marca_extra", lambda rows: rows),   # marcador de filtro; testado em test_inputs_de_extra.py
          patch.object(m, "_cache_scope_dataset", lambda scope, producer: producer()),
          patch.object(m, "_sanitizacao_derivada",
                       lambda: {SO_ANTE: sanitizacao.MOTIVO_SO_ANTECESSOR})]
    for p in ps:
        p.start()
    try:
        row = {r["chave_canonica"]: r for r in m._dataset_escopo("indi", [])}[SO_ANTE]
    finally:
        for p in ps:
            p.stop()
    assert row["status"] == "Sanitizado"
    assert row["status_real"] == "A Iniciar"
    assert row["sanitizado_motivo"] == "só o antecessor, que tem sucessor"
    assert m.py_aingerir(row) is False


# ---- §3.4.17 reescrito (28/09/2026): as duas origens se somam no recorte REAL ------

SO_MISTA = "tabela::MISTA"


def test_sucessor_segura_a_chave_mesmo_com_os_outros_resolvidos():
    # A TRAVA, no caminho que o app usa: a chave é lida por um despriorizado, por um
    # antecessor E pelo SUCESSOR. O sucessor entra no recorte por regra (§3.1.2) e não
    # é antecessor, então é consumidor vivo — a chave CONTINUA na fila.
    pares = [(SO_MISTA, "Cob__Desp"), (SO_MISTA, "Cob__Velho"), (SO_MISTA, "Cob__Novo")]
    kw = dict(pendentes={SO_MISTA}, despriorizados=("Cob__Desp",),
              frontier=FRONTIER | {"Cob__Desp", "Cob__Novo"},
              vinculos={"Cob__Velho": {"tipo": "Atualizado", "sucessor": "Cob__Novo"}})
    assert _derivada(pares, **kw) == {}
    # tirar SÓ o sucessor da lista de leitores libera a MESMA entrada: quem segurava
    # era ele, e não outra coisa qualquer.
    assert _derivada(pares[:2], **kw) == {SO_MISTA: sanitizacao.MOTIVO_MISTO}


def test_origens_misturadas_saem_da_fila_no_recorte():
    # Antes de 28/09 esta chave ficava na fila: cada régua sozinha recusava porque
    # nenhuma via "todos os seus consumidores" dentro do próprio conjunto.
    d = _derivada([(SO_MISTA, "Cob__Desp"), (SO_MISTA, "Cob__Velho")],
                  pendentes={SO_MISTA}, despriorizados=("Cob__Desp",),
                  frontier=FRONTIER | {"Cob__Desp"},
                  vinculos={"Cob__Velho": {"tipo": "Atualizado", "sucessor": "Cob__Novo"}})
    assert d == {SO_MISTA: sanitizacao.MOTIVO_MISTO}


# ---- fragilidade: N chaves fora da fila só porque M EGPs estão fora do escopo -----

def _frag(pares, motivos, frontier=FRONTIER, log_on=True):
    """Roda _fragilidade_sanitizacao() sobre `pares` [(chave, projeto)] do corpus.

    Devolve (payload, sqls) — `sqls` é tudo que foi ao warehouse, usado pelos testes do
    log (o que ele escreve, e que NADA o lê)."""
    sqls = []

    def _run(sql, want_rows=True, **kw):
        sqls.append(sql)
        if "sas_egp_inputs" in sql:
            return [{"ch": ch, "pj": pj} for ch, pj in pares]
        return []
    ps = [patch.object(m, "run_sql", side_effect=_run),
          patch.object(m, "_sanitizacao_derivada", lambda: dict(motivos)),
          patch.object(m, "_frontier_egps", lambda *a, **k: (set(frontier), set())),
          patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
          patch.object(m, "_SAN_LOG_ON", log_on),
          # cada cenário é um processo que ainda não gravou o dia (a guarda é por processo)
          patch.object(m, "_san_log_dia", None)]
    for p in ps:
        p.start()
    try:
        m._bump_gen()
        return m._fragilidade_sanitizacao(), sqls
    finally:
        for p in ps:
            p.stop()
        m._bump_gen()


def test_fragilidade_conta_chaves_e_egps_fora_do_escopo():
    # SO_DESP é lida também por um EGP FORA do recorte: ela só está fora da fila
    # porque a exclusividade é medida contra o escopo ativo (§3.4.16). Se esse EGP
    # entrar, a chave volta.
    f, _ = _frag([(SO_DESP, "Cob__Velho"), (SO_DESP, "Fora__X"), (SO_ANTE, "Cob__Velho")],
                 {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS,
                  SO_ANTE: sanitizacao.MOTIVO_SO_ANTECESSOR})
    assert f["n_chaves"] == 1 and f["n_egps"] == 1
    assert f["chaves"] == [SO_DESP]
    assert f["por_egp"] == [{"projeto": "Fora__X", "n_chaves": 1, "chaves": [SO_DESP]}]


def test_fragilidade_vazia_quando_ninguem_esta_fora():
    f, _ = _frag([(SO_DESP, "Cob__Velho")],
                 {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS})
    assert f == {"n_chaves": 0, "n_egps": 0, "chaves": [], "por_egp": []}


def test_fragilidade_sem_chave_sanitizada_nao_consulta_nada():
    f, sqls = _frag([], {})
    assert f["n_chaves"] == 0
    assert not [s for s in sqls if "sas_egp_inputs" in s]


# ---- log diário: SÓ contador, e NADA o realimenta --------------------------------

def _escritas_no_log(sqls):
    return [s for s in sqls if "sas_app_config" in s]


def test_log_diario_grava_contador_e_nunca_o_estado():
    hoje = m.datetime.date.today().isoformat()
    _, sqls = _frag([(SO_DESP, "Cob__Velho"), (SO_DESP, "Fora__X")],
                    {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS})
    escritas = _escritas_no_log(sqls)
    merge = [s for s in escritas if "MERGE" in s]
    assert len(merge) == 1                       # no máximo UMA linha por dia
    assert f"san_contadores::{hoje}" in merge[0]
    assert '"total": 1' in merge[0] and '"n_frageis": 1' in merge[0]
    assert '"so_despriorizados": 1' in merge[0]
    # REGRA DURA: nenhuma CHAVE vai para o log — só número. Se o estado derivado
    # vazasse para cá, o log viraria fonte de verdade e a reversibilidade morreria.
    assert SO_DESP not in merge[0]


def test_log_diario_e_idempotente_por_data_e_nunca_reescreve():
    _, sqls = _frag([(SO_DESP, "Cob__Velho")],
                    {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS})
    merge = [s for s in _escritas_no_log(sqls) if "MERGE" in s][0]
    # só INSERT do que falta: a foto do dia não é sobrescrita, e a tabela viva da
    # gestão (sas_app_config) nunca é dropada nem tem linha existente tocada.
    assert "WHEN NOT MATCHED THEN INSERT" in merge
    assert "WHEN MATCHED" not in merge
    assert "DROP" not in " ".join(_escritas_no_log(sqls))


def test_nada_le_o_log():
    # A independência é estrutural: em nenhum caminho do cálculo há SELECT da chave do
    # log. O que o log escreve não volta.
    _, sqls = _frag([(SO_DESP, "Cob__Velho"), (SO_DESP, "Fora__X")],
                    {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS})
    tocam = [s for s in sqls if "san_contadores" in s]
    assert len(tocam) == 1 and tocam[0].strip().upper().startswith("MERGE")
    assert not [s for s in sqls if s.strip().upper().startswith("SELECT")
                and "san_contadores" in s]


def test_desligar_o_log_nao_muda_nenhum_numero():
    # Critério de aceite, literal: o MESMO cenário com o log desligado devolve
    # exatamente os mesmos números da fila e da fragilidade.
    pares = [(SO_DESP, "Cob__Velho"), (SO_DESP, "Fora__X"), (SO_ANTE, "Cob__Velho")]
    motivos = {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS,
               SO_ANTE: sanitizacao.MOTIVO_SO_ANTECESSOR}
    com, sqls_com = _frag(pares, motivos, log_on=True)
    sem, sqls_sem = _frag(pares, motivos, log_on=False)
    assert com == sem
    assert _escritas_no_log(sqls_com) and not _escritas_no_log(sqls_sem)


def test_falha_do_log_nao_derruba_a_fragilidade():
    # Nem o log quebrado pode mudar um número: ele é efeito colateral, não etapa.
    with patch.object(m, "_log_san_contadores", side_effect=RuntimeError("warehouse")):
        f, _ = _frag([(SO_DESP, "Cob__Velho"), (SO_DESP, "Fora__X")],
                     {SO_DESP: sanitizacao.MOTIVO_SO_DESPRIORIZADOS})
    assert f["n_chaves"] == 1 and f["chaves"] == [SO_DESP]


def test_endpoint_serve_a_fragilidade():
    payload = {"n_chaves": 73, "n_egps": 12, "chaves": ["t::A"],
               "por_egp": [{"projeto": "Fora__X", "n_chaves": 40, "chaves": ["t::A"]}]}
    with patch.object(m, "_fragilidade_sanitizacao", lambda: payload):
        assert m.inputs_fragilidade() == payload


# ---- a TRAVA do sucessor, sem patch no recorte -----------------------------------
# Os testes acima injetam o frontier. Este NÃO: monta o corpus na fonte (nós + funil) e
# deixa _frontier_egps derivar o recorte, provando que o sucessor chega nele por regra
# (§3.1.2) — que é o que faz dele consumidor vivo. Se algum dia o sucessor parar de
# entrar no recorte, a régua sanitizaria o inventário da versão nova em silêncio, e é
# ESTE teste que quebra.

NODES_TRAVA = [{"projeto": p} for p in ("Cob__Velho", "Cob__Desp", "Cob__Vivo")]
PIPE_TRAVA = [
    {"projeto": "Cob__Desp", "status_migracao": "Despriorizado e Contabilizado",
     "egp_vinculo_tipo": "", "egp_sucessor": ""},
    {"projeto": "Cob__Velho", "status_migracao": "Em Andamento",
     "egp_vinculo_tipo": "Atualizado", "egp_sucessor": "Cob__Novo"},
]


def _derivada_sem_patch_no_recorte(pares):
    """Roda _sanitizacao_derivada() com o recorte DERIVADO da fonte (só run_sql é falso)."""
    def _run(stmt, want_rows=True, **kw):
        s = " ".join(stmt.split())
        if not want_rows:
            return []
        if "sas_lineage_nodes" in s:
            return [dict(n) for n in NODES_TRAVA]
        if "sas_egp_pipeline" in s:
            if "Despriorizado e Contabilizado" in s:
                return [{"projeto": r["projeto"]} for r in PIPE_TRAVA
                        if r["status_migracao"] == "Despriorizado e Contabilizado"]
            return [dict(r) for r in PIPE_TRAVA]
        if "sas_egp_inputs" in s:
            # emula o `projeto IN (...)` do recorte: só passa quem está no statement
            return [{"ch": ch, "pj": pj} for ch, pj in pares if m.sql_lit(pj) in s]
        if "sas_inputs_monitor" in s:
            return [{"chave_canonica": SO_MISTA}]
        return []
    ps = [patch.object(m, "run_sql", side_effect=_run),
          patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
          patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
    for p in ps:
        p.start()
    try:
        m._bump_gen()
        return m._sanitizacao_derivada()
    finally:
        for p in ps:
            p.stop()
        m._bump_gen()


def test_trava_do_sucessor_com_o_recorte_derivado_da_fonte():
    lido_pelo_sucessor = [(SO_MISTA, "Cob__Desp"), (SO_MISTA, "Cob__Velho"),
                          (SO_MISTA, "Cob__Novo")]
    assert _derivada_sem_patch_no_recorte(lido_pelo_sucessor) == {}
    # controle: a versão nova NÃO lê a chave -> ela sai da fila. Mesma fonte, mesma
    # régua; a única diferença é o sucessor ter deixado de ler.
    assert _derivada_sem_patch_no_recorte(lido_pelo_sucessor[:2]) == {
        SO_MISTA: sanitizacao.MOTIVO_MISTO}
