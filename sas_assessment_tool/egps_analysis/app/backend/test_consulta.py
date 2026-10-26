"""Tabelas de consulta do agente (ADR 0004): transcrição fiel + paridade. Offline."""
from fastapi import HTTPException
import pytest

import consulta
import main

STAGES = ["Projetos Habilitados", "Validação em DES", "Migrado"]
FANTASMAS = {"Pré-conversão", "Conversão pela Área"}


def _r(projeto, **kw):
    base = {"projeto": projeto, "deps": [], "etapa": None, "status": None, "status_contagem": None}
    return {**base, **kw}


def _egp(readiness, linha_base, frontier=(), extras=(), gestao=(), mes=None):
    return consulta.linhas_egp(readiness, linha_base, {}, set(frontier), set(extras), set(gestao),
                               mes or {}, STAGES, FANTASMAS, "2026-10-06 00:00:00")


def test_classe_e_contas_seguem_a_linha_de_base():
    linhas = {r["projeto"]: r for r in _egp(
        [_r("A"), _r("B"), _r("X", e_extra=True, extra_motivo="casca")],
        {"A": "base", "B": "dependencia"}, extras={"X"})}
    assert linhas["A"]["conta_funil_migracao"] and linhas["A"]["conta_total_egps"]
    assert not linhas["B"]["conta_funil_migracao"] and linhas["B"]["conta_funil_migracao_deps"]
    x = linhas["X"]
    assert not x["conta_total_egps"] and x["conta_funil_migracao_extras"] and x["casca"]


def test_e_dependencia_de_e_o_inverso_de_depende_de():
    linhas = {r["projeto"]: r for r in _egp(
        [_r("A", deps=[{"projeto": "D"}]), _r("B", deps=[{"projeto": "D"}]), _r("D")], {})}
    assert linhas["A"]["depende_de"] == "D"
    assert linhas["D"]["e_dependencia_de"] == "A, B"


@pytest.mark.parametrize("etapa,status,conta", [
    ("Migrado", "Migrado", True),
    ("Migrado", "Despriorizado e Contabilizado", True),
    ("Validação em DES", "Em Andamento", False),
    ("Pré-conversão", "Despriorizado e Contabilizado", False),   # fantasma: fora do coorte
    (None, "Migrado", False),                                    # sem etapa: fora do coorte
])
def test_conta_migrado_e_a_regua_do_proj_funnel(etapa, status, conta):
    assert consulta.conta_no_coorte_migrado(etapa, status, STAGES, FANTASMAS) is conta


def _inp(rows, escopo=(), indi=None, gestao=()):
    return {r["chave"]: r for r in consulta.linhas_input(
        rows, set(escopo), indi or {}, set(gestao), {},
        main.py_eff_etapa, main.py_eff_status, main.py_modern, main.py_aingerir,
        main._universo_contagem, "2026-10-06 00:00:00")}


def _in(k, **kw):
    return {"chave_canonica": k, "etapa": "Recebido", "status": "Em Andamento", **kw}


def test_baldes_particionam_como_a_visao_geral():
    rows = [_in("e"), _in("d"), _in("x", so_de_extra=True), _in("q", vinculo_ativo=False),
            _in("o", ex_dependencia=True)]
    out = _inp(rows, escopo={"e"})
    assert {k: r["balde"] for k, r in out.items()} == {
        "e": "escopo", "d": "dependencia", "x": "extra",
        "q": "sem_vinculo_ativo", "o": "so_ex_dependencia"}
    assert [k for k, r in out.items() if r["conta_total_inputs"]] == ["e", "d", "x"]


def test_sanitizado_conta_no_total_mas_sai_do_funil():
    out = _inp([_in("s", status="Sanitizado")], escopo={"s"})["s"]
    assert out["conta_total_inputs"] and out["resolvido"] and not out["a_ingerir"]
    assert not out["conta_funil_ingestao_deps"]


def test_funil_do_escopo_le_o_estado_do_dataset_do_escopo():
    # a família agrega só as safras em vista: no escopo pode estar Sanitizada e no Recorte não
    out = _inp([_in("f")], escopo={"f"}, indi={"f": _in("f", status="Sanitizado")})["f"]
    assert not out["conta_funil_ingestao"] and out["conta_funil_ingestao_deps"]


def test_confere_aponta_cada_total_que_nao_fecha():
    landing = {k: 0 for k in ("total_egps", "egps_escopo", "deps", "deps_ex", "extras",
                              "inputs_escopo", "inputs_deps", "inputs_extras", "total_inputs",
                              "inputs_a_ingerir", "inputs_deps_a_ingerir",
                              "inputs_extras_a_ingerir", "total_nao_modernizados")}
    funis = {k: {"migrados": 0, "total": 0} for k in (
        "migracao", "migracao_deps", "migracao_extras", "ingestao", "ingestao_deps", "ingestao_extras")}
    egp = _egp([_r("A")], {"A": "base"})
    assert consulta.confere(egp, [], {**landing, "total_egps": 1, "egps_escopo": 1}, funis, 0, 0) == []
    div = consulta.confere(egp, [], landing, funis, 0, 0)
    assert ("total de EGPs (Resumo)", 0, 1) in div


def test_colunas_sem_repeticao_e_com_calculado_em():
    for cols in (consulta.COLUNAS_EGP, consulta.COLUNAS_INPUT):
        nomes = [c for c, _ in cols]
        assert len(nomes) == len(set(nomes)) and "calculado_em" in nomes
    linha = _egp([_r("A")], {"A": "base"})[0]
    assert set(linha) == {c for c, _ in consulta.COLUNAS_EGP}
    linha = _inp([_in("e")], escopo={"e"})["e"]
    assert set(linha) == {c for c, _ in consulta.COLUNAS_INPUT}


def test_marca_da_rotina_usa_sp_e_nao_vaza_para_request(monkeypatch):
    monkeypatch.setattr(main, "_sp_client", lambda: "SP")
    monkeypatch.setattr(main, "REQUIRE_OBO", True)
    with pytest.raises(HTTPException):
        main._client()                                   # request sem token: 401, como sempre
    tok = main._rotina_sistema.set(True)
    try:
        assert main._client() == "SP"                    # só a rotina usa o service principal
    finally:
        main._rotina_sistema.reset(tok)
    with pytest.raises(HTTPException):
        main._client()                                   # e a marca não fica para trás


def test_texto_vazio_vira_null_para_quem_consulta_por_sql():
    egp = _egp([_r("A", etapa="", status="  ", responsavel="")], {"A": "base"})[0]
    assert egp["etapa_exibida"] is None and egp["status_exibido"] is None and egp["responsavel"] is None
    assert egp["projeto"] == "A" and egp["conta_total_egps"] is True     # não-texto intacto
    inp = _inp([_in("e", responsavel="")], escopo={"e"})["e"]
    assert inp["responsavel"] is None


def test_rotina_nao_sobe_ao_importar():
    import threading
    assert not any(t.name == "consulta" for t in threading.enumerate())
    assert main.CONSULTA_ON is False                     # testes/scripts: desligada por padrão


# ---- quando a rotina roda: intervalo mínimo vale para TODA tentativa ----
I = main.CONSULTA_INTERVALO_S


def test_falha_na_diaria_nao_vira_retentativa_a_cada_minuto():
    # a passada diária falhou há 60 s (ultima_sonda marca a tentativa): espera o intervalo
    assert main._consulta_decide(10_000, 9, "2026-10-06", None, 10_000 - 60, 0) == (False, False)
    assert main._consulta_decide(10_000, 9, "2026-10-06", None, 10_000 - I, 0) == (True, True)


def test_primeira_tentativa_nao_espera_nem_com_container_recem_ligado():
    assert main._consulta_decide(5.0, 9, "2026-10-06", None, float("-inf"), 0) == (True, True)


def test_app_parado_nao_sonda_fora_da_diaria():
    # já gravou hoje e ninguém usa o app há 1 h: não acorda o warehouse
    assert main._consulta_decide(10_000, 14, "2026-10-06", "2026-10-06", 0, 10_000 - 3600) == (False, False)
    # alguém usando: sonda (sem forçar recálculo)
    assert main._consulta_decide(10_000, 14, "2026-10-06", "2026-10-06", 0, 10_000 - 30) == (True, False)


def test_diaria_so_depois_das_6h():
    assert main._consulta_decide(10_000, 5, "2026-10-06", "2026-10-05", 0, 0) == (False, False)


def test_retrato_do_dia_e_trocado_num_statement_so(monkeypatch):
    """DELETE do dia + INSERT eram dois statements: falha entre eles deixava o dia SEM
    retrato até a próxima passada. `INSERT INTO … REPLACE WHERE` troca atômico no Delta
    (sintaxe validada com EXPLAIN no warehouse em 08/10/2026)."""
    sql = []
    monkeypatch.setattr(main, "_run_sp", lambda stmt, want_rows=False: sql.append(" ".join(stmt.split())))
    monkeypatch.setattr(main, "_consulta_ensure", lambda: None)
    main._consulta_grava([{"projeto": "Cob__A"}], [{"chave": "TB.X"}])
    assert not [s for s in sql if s.upper().startswith("DELETE")]
    dia = [s for s in sql if "_dia" in s.split(" SELECT ")[0]]
    assert len(dia) == 2 and all(" REPLACE WHERE dia = DATE '" in s for s in dia)
    # o retrato atual é gravado ANTES de virar o retrato do dia (o _dia lê dele)
    for t in (main.T_CONS_EGP, main.T_CONS_IN):
        i_atual = next(i for i, s in enumerate(sql) if s.startswith(f"INSERT OVERWRITE {t} "))
        i_dia = next(i for i, s in enumerate(sql) if s.startswith(f"INSERT INTO {t}_dia "))
        assert i_atual < i_dia
