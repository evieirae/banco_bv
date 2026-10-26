from priorizacao_logic import plan_months, resumo_counts

# Cenário base (cap=3):
#   A:{a,b}(2)  B:{b,c}(2, compartilha b)  C:{d}(1)  D:{e,f,g,h}(4, > cap)
INPUTS = {"A": {"a", "b"}, "B": {"b", "c"}, "C": {"d"}, "D": {"e", "f", "g", "h"}}
ORDER = ["A", "B", "C", "D"]


def _names(month):
    return [e["projeto"] for e in month["egps"]]


def test_sem_pins_empacota_como_o_algoritmo_atual():
    meses = plan_months(ORDER, INPUTS, {}, cap=3)
    # m1: A(+a,b)=2, B(+c)=1 -> {a,b,c}; m2: C(+d)=1; m3: D solo (excede)
    assert [_names(m) for m in meses] == [["A", "B"], ["C"], ["D"]]
    assert meses[0]["inputs"] == {"a", "b", "c"}
    assert meses[0]["egps"][0]["n_inputs_novos"] == 2   # A
    assert meses[0]["egps"][1]["n_inputs_novos"] == 1   # B (dedupe: b já contado)
    assert meses[2]["egps"][0]["excede"] is True        # D sozinho > cap
    assert meses[2]["egps"][0]["pinned"] is False


def test_pin_puxa_egp_para_mes_1():
    meses = plan_months(ORDER, INPUTS, {"C": 1}, cap=3)
    # m1: C(pin, +d), A(+a,b) -> {d,a,b}; m2: B(+c); m3: D solo
    assert [_names(m) for m in meses] == [["C", "A"], ["B"], ["D"]]
    assert meses[0]["egps"][0]["pinned"] is True        # C fixado vem primeiro
    assert meses[0]["inputs"] == {"a", "b", "d"}


def test_pin_que_estoura_o_teto_marca_excede_e_nao_enche_o_mes():
    meses = plan_months(ORDER, INPUTS, {"D": 1}, cap=3)
    # m1: D(pin, 4 > cap) sozinho; automáticos NÃO entram no m1
    assert _names(meses[0]) == ["D"]
    assert meses[0]["egps"][0]["excede"] is True
    assert len(meses[0]["inputs"]) == 4                 # acima do teto (guia)
    assert [_names(m) for m in meses[1:]] == [["A", "B"], ["C"]]


def test_pin_para_mes_novo_ao_final_com_dedupe():
    meses = plan_months(ORDER, INPUTS, {"A": 3}, cap=3)
    # m1: B(+b,c), C(+d); m2: D solo; m3: A(pin) -> só {a} (b já ingerido no m1)
    assert [_names(m) for m in meses] == [["B", "C"], ["D"], ["A"]]
    assert meses[2]["egps"][0]["pinned"] is True
    assert meses[2]["egps"][0]["n_inputs_novos"] == 1   # dedupe reduz A para {a}


def test_meses_vazios_sao_removidos():
    meses = plan_months(["A"], {"A": {"a"}}, {"A": 2}, cap=3)
    assert len(meses) == 1 and _names(meses[0]) == ["A"]


def test_resumo_counts_complemento():
    r = resumo_counts(["A", "B", "C", "D", "E"], {"B", "C"})
    assert r == {"total": 5, "bloqueados": 2, "habilitados": 3}


