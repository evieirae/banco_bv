"""Unit do _funnel_bars: banda p/ "Despriorizado e Contabilizado"; taper p/ os demais.

Roda como script: python egps_analysis/app/test_funnel_bars.py

O status `Removido` foi EXTINTO em 2026-07 (fundido em "Despriorizado e Contabilizado") e
deixou de ganhar banda. O teste que afirmava o contrário ficou vermelho desde então; virou
`test_removido_extinto_nao_ganha_banda`, que pina o comportamento atual e explica o porquê —
apagar o caso perderia o registro de que ali houve uma decisão.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))


def _load_funnel_bars():
    import main  # noqa
    return main._funnel_bars


STAGES = ["E0", "E1", "E2", "E3"]


def test_taper_em_andamento():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(2, "Em Andamento", 1)])
    seg = {b["etapa"]: b["seg"] for b in bars}
    assert seg["E0"] == {"Concluído": 1}
    assert seg["E1"] == {"Concluído": 1}
    assert seg["E2"] == {"Em Andamento": 1}
    assert seg["E3"] == {"A Iniciar": 1}


def test_removido_extinto_nao_ganha_banda():
    """`Removido` saiu do vocabulário em 2026-07: hoje é status comum e sofre taper.

    Antes ele era banda (pintava todas as colunas), como "Despriorizado e Contabilizado"
    continua sendo. Um dado legado com esse status não deve mais pintar o funil inteiro —
    aparece só na etapa onde está, com Concluído atrás e A Iniciar à frente.
    """
    fb = _load_funnel_bars()
    seg = {b["etapa"]: b["seg"] for b in fb(STAGES, [(2, "Removido", 1)])}
    assert seg == {"E0": {"Concluído": 1}, "E1": {"Concluído": 1},
                   "E2": {"Removido": 1}, "E3": {"A Iniciar": 1}}


def test_banda_despriorizado_em_todas_colunas():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(1, "Despriorizado e Contabilizado", 1)])
    for b in bars:
        assert b["seg"] == {"Despriorizado e Contabilizado": 1}, b


def test_migrado_so_na_etapa():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(3, "Migrado", 1)])
    seg = {b["etapa"]: b["seg"] for b in bars}
    assert seg["E0"] == {"Concluído": 1}
    assert seg["E3"] == {"Migrado": 1}


def test_phantom_etapas_fora_do_funil():
    # PHANTOM_ETAPAS_MIGRACAO (dict etapa->tone; ex.: "Pré-conversão", "Conversão pelo
    # BV") não pode entrar em PIPELINE_PROJETO — se entrar, o índice de "Validação em
    # DES" desloca e _funnel_bars quebra.
    import main
    stages = main.PIPELINE_PROJETO["migracao"]
    assert not (set(main.PHANTOM_ETAPAS_MIGRACAO) & set(stages)), \
        "PHANTOM_ETAPAS_MIGRACAO deve ser disjunto de PIPELINE_PROJETO[migracao]"
    assert stages[2] == "Conversão do Código" and stages[3] == "Validação em DES", \
        "adicionar phantom não pode deslocar índices do funil"


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
    raise SystemExit(1 if failed else 0)
