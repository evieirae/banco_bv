"""Regressão: link de modernizadas quando o SAS usa o alias do destino IQ (libref) em vez da base de origem.

Cenário canônico (BV): o SAS lê ``DBA.TBPROPOSTA``. ``DBA`` é o alias do **destino de réplica
no Sybase IQ**; a base de **origem** ASE é ``DBCRED`` (RepMap: ``DBsource=DBCRED → DBtarget=DBA``).
A modernizada existe no Chameleon como ``bv-pdbd-prd.trusted_dbcred.tbproposta`` (origem
``dbcred.dbo.tbproposta``). Antes da correção nenhum dos dois linkers ligava os dois nomes.

Roda como script (``python test_repmap_chameleon_bridge.py``) ou via pytest.
"""
from __future__ import annotations

import os

import migration_hints_table_in_repmap_chameleon as mh
import orchestrator_inventory as orch
import publish_to_databricks as pub

# ----- fixtures sintéticos (sem depender dos CSV/XLSX grandes) -----
_CH_REC = {
    "NmTabela": "bv-pdbd-prd.trusted_dbcred.tbproposta",
    "NmTabelaOrigem": "dbcred.dbo.tbproposta",
    "NmFonteDados": "SYBASE_ASE",
    "DtFimIngestao": "",
}
_CH_IDX = {("DBCRED", "TBPROPOSTA"): [_CH_REC]}
_CH_BY_TABLE = {"TBPROPOSTA": [_CH_REC]}
_REP_HITS = [{"DBsource": "DBCRED", "Tabela": "TbProposta", "TabRep": "TbProposta"}]
_CH_DESTINO = "BV-PDBD-PRD.TRUSTED_DBCRED.TBPROPOSTA"  # como load_chameleon_data normaliza (upper)


def test_migration_hints_regression_without_bridge_misses():
    """Sem a ponte RepMap, o token do destino IQ (DBA.) não casa — comportamento antigo."""
    hits, _ = mh.lookup_chameleon("DBA.TBPROPOSTA", _CH_IDX, _CH_BY_TABLE)
    assert hits == [], "DBA.TBPROPOSTA não deveria casar sem a ponte (é o bug original)"


def test_migration_hints_bridge_links_via_repmap_source():
    extra = mh.repmap_source_db_table_pairs(_REP_HITS)
    assert ("DBCRED", "TBPROPOSTA") in extra
    hits, key = mh.lookup_chameleon("DBA.TBPROPOSTA", _CH_IDX, _CH_BY_TABLE, extra_candidates=extra)
    assert len(hits) == 1, f"esperava 1 hit via ponte, veio {len(hits)}"
    assert hits[0]["NmTabela"] == "bv-pdbd-prd.trusted_dbcred.tbproposta"
    assert "via RepMap" in key, f"chave deveria sinalizar a ponte: {key!r}"


def test_migration_hints_direct_source_still_works():
    hits, key = mh.lookup_chameleon("DBCRED.TBPROPOSTA", _CH_IDX, _CH_BY_TABLE)
    assert len(hits) == 1 and "via RepMap" not in key


def test_orchestrator_strict_match_regression_and_translation():
    # Bug original: o token do destino IQ não é substring do destino BQ (trusted_dbcred).
    assert orch.is_strict_match("DBA.TBPROPOSTA", _CH_DESTINO) is False
    # A chave traduzida (base de origem) casa.
    assert orch.is_strict_match("DBCRED.TBPROPOSTA", _CH_DESTINO) is True


def test_new_status_marker_is_registered():
    status = "[Modernizada via replica] Tabela presente no BigQuery (origem resolvida via RepMap)"
    assert any(m in status.upper() for m in pub.MODERN_MARKERS), (
        "o novo status precisa ser reconhecido por MODERN_MARKERS (senão não conta como modernizada no app)"
    )


# ----- integração opcional contra os dados reais (se presentes) -----
def _integration_available() -> tuple[bool, str]:
    """(pode rodar, motivo do skip).

    Checa também o `openpyxl`, não só os dados. Os dois arquivos SÃO versionados, então a
    guarda antiga passava em qualquer ambiente e o teste ia direto para
    `load_repmap_rows`, que importa openpyxl DENTRO da função
    (validate_table_in_vs_repmap.py) — um `import` a dois hops daqui, que não aparece no
    topo de nenhum dos arquivos. Em ambiente sem a lib isso virava ModuleNotFoundError,
    não skip: foi o que deixou o pipeline da develop vermelho em 22/09/2026.

    openpyxl é dependência de `egps_analysis/requirements.txt`, não do app — quem roda só
    o requirements do app (o CI) legitimamente não a tem."""
    if not (os.path.exists("src/chameleon.csv") and os.path.exists("src/RepMap.xlsx")):
        return False, "dados reais (src/chameleon.csv, src/RepMap.xlsx) ausentes"
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return False, "openpyxl ausente (necessário para ler src/RepMap.xlsx)"
    return True, ""


def test_integration_real_data_links_dba_tbproposta():
    pode, motivo = _integration_available()
    if not pode:
        print(f"  [skip] {motivo}")
        return
    from pathlib import Path

    rep_rows = mh.load_repmap_rows(Path("src/RepMap.xlsx"))
    full_key_index: dict = {}
    for r in rep_rows:
        for k in mh.repmap_derived_keys(r):
            full_key_index.setdefault(k, []).append(r)
    ch_idx, ch_by_table, _ = mh.load_chameleon_sybase_index(Path("src/chameleon.csv"))

    lvl, _d, rep_hits = mh.match_artifact("DBA.TBPROPOSTA", rep_rows, full_key_index)
    assert rep_hits, "RepMap deveria ter linha para DBA.TBPROPOSTA"
    extra = mh.repmap_source_db_table_pairs(rep_hits)
    hits, key = mh.lookup_chameleon("DBA.TBPROPOSTA", ch_idx, ch_by_table, extra_candidates=extra)
    nmtab = {h["NmTabela"] for h in hits}
    assert any("trusted_dbcred.tbproposta" in n for n in nmtab), f"esperava trusted_dbcred; veio {nmtab}"
    print(f"  [integração] DBA.TBPROPOSTA -> {sorted(nmtab)} (chave={key})")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passaram")
    raise SystemExit(1 if failed else 0)
