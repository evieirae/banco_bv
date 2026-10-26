"""Unit do classificador de origem do monitor (origem_input). Gate = os testes
puros abaixo (independem de dados). A distribuição de contagem do escopo Indicium
é impressa como ADVISORY (não-gate), pois os relatórios 01-06 são regenerados
periodicamente e os números mudam. Roda como script:
    python egps_analysis/test_origem_input.py
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_to_databricks as pub


def test_bigquery_vence_tudo():
    assert pub.origem_input({"BIGQUERY/GCP", "POSTGRES"}, "tabela", True) == "BigQuery"


def test_arquivo_por_categoria():
    assert pub.origem_input({"SAS/LOCAL"}, "arquivo", False) == "Arquivo"


def test_script_por_categoria():
    assert pub.origem_input({"SAS/LOCAL"}, "script", False) == "Script"


def test_transacional():
    assert pub.origem_input({"SYBASEIQ"}, "tabela", False) == "Transacional"
    assert pub.origem_input({"DBCON", "SAS/LOCAL"}, "tabela", False) == "Transacional"


def test_sas_local_dependencia_quando_produzida():
    assert pub.origem_input({"SAS/LOCAL"}, "tabela", True) == "SAS/Local (dependência)"


def test_sas_local_externo_quando_sem_produtor():
    assert pub.origem_input({"SAS/LOCAL"}, "tabela", False) == "SAS/Local (externo)"


def test_transacional_vence_dependencia():
    # token transacional tem prioridade sobre o split SAS/Local mesmo se produzida
    assert pub.origem_input({"POSTGRES"}, "tabela", True) == "Transacional"


# ADVISORY (não-gate): imprime a distribuição de origem do escopo Indicium SEM
# assertar números — os relatórios 01-06 são regenerados e a distribuição muda.
# Não tem prefixo test_, então não entra em TESTS nem gata a suíte. Referência
# (snapshot commitado de 2026-06-18): externo 1566 · Arquivo 850 · dependência 544
# · BigQuery 310 · Transacional 82 · Script 2 (soma 3354).
def advisory_distribuicao_origem_indicium():
    try:
        data = pub.build()
    except Exception as e:  # noqa: BLE001
        print(f"[advisory] build() falhou ({type(e).__name__}: {e}); distribuição pulada.")
        return
    import collections
    c = collections.Counter(r["origem"] for r in data["inputs"] if r["escopo_indi"])
    print(f"[advisory] distribuição origem (escopo Indicium, soma={sum(c.values())}):")
    for k, v in c.most_common():
        print(f"           {k:26s} {v}")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passaram")
    advisory_distribuicao_origem_indicium()
    raise SystemExit(1 if failed else 0)
