#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes da regra de família de safras (ticket 01). `python -m pytest test_familias.py`"""
import json
import os
import tempfile

import re

import pytest

import familias as F


# ---------------------------------------------------------------- regra pura

@pytest.mark.parametrize("artifact,esperado", [
    # sufixo: a forma mais comum (3.034 artefatos no corpus)
    ("GRIMALDI.CARGA_MASSIFICADOS_202506", "GRIMALDI.CARGA_MASSIFICADOS"),
    ("_TRADE.ACORDOS_TRADE_202308", "_TRADE.ACORDOS_TRADE"),
    ("GH16.POLITICA_ACORDO_GH16_20250704", "GH16.POLITICA_ACORDO_GH16"),
    # data NO MEIO: 370 artefatos que o sufixo sozinho não pegava
    ("ALVESDS.EMP_8_20250124_GCP", "ALVESDS.EMP_8_GCP"),
    ("ALVESDS.BASE_ATUACAO_202602_ENRIQ", "ALVESDS.BASE_ATUACAO_ENRIQ"),
    # mais de um token no mesmo nome
    ("BASE_202401_X_202402", "BASE_X"),
    # ano solto ainda é token (a guarda dos ≥2 é que protege tabela legítima)
    ("CORP.HISTORICO_2016", "CORP.HISTORICO"),
    # número que NÃO é data não colapsa (sufixo de versão/código)
    ("GRIMALDI.CRT_ELEITOS_SOL_45_135", "GRIMALDI.CRT_ELEITOS_SOL_45_135"),
    ("MIKE.TESTE_DESC_ENC_3", "MIKE.TESTE_DESC_ENC_3"),
    ("LIB.X_1999", "LIB.X_1999"),          # fora do século 20xx
    ("LIB.X_202613", "LIB.X_202613"),      # mês 13 não existe
    ("LIB.X_2026030", "LIB.X_2026030"),    # 7 dígitos não é YYYYMM nem YYYYMMDD
    # --- formatos vindos da branch feat/vintage_analysis (2026-09-17) ---
    # mês em português é o caso mais comum que a régua só-numérica perdia (15 irmãos)
    ("SEGUROS.RECLAMACOES_ICATU_ABR25", "SEGUROS.RECLAMACOES_ICATU"),
    ("AUTOMATI.BVO_GRUPOS_ABRIL25", "AUTOMATI.BVO_GRUPOS"),
    ("FINAL.TABELAO_ABR24_AUTOMACAO", "FINAL.TABELAO_AUTOMACAO"),
    ("X.TAB_29JAN26", "X.TAB"),                      # dia + mês + ano de 2 dígitos
    ("TUYRA.SOLAR_REBATE_0124", "TUYRA.SOLAR_REBATE"),          # MMYY
    ("ENTREGA.BASE_ENTREGA_110226_TOTAL", "ENTREGA.BASE_ENTREGA_TOTAL"),  # DDMMYY
    ("ABORDAGEM_29012026", "ABORDAGEM"),                        # DDMMYYYY (dia primeiro)
    ("LIB.X_2026.03", "LIB.X"),                                 # YYYY.MM
    # YYYY_MM_DD (19/10/2026): sem este formato o regex tirava só o ano e sobrava `06_01`,
    # então cada mês de RENEG.NOVARENEG_2023_06_01_EXPORT_A virava tabela distinta
    ("RENEG.NOVARENEG_2023_06_01_EXPORT_A", "RENEG.NOVARENEG_EXPORT_A"),
    ("RENEG.NOVARENEG_2024_05_01_EXPORT_A", "RENEG.NOVARENEG_EXPORT_A"),
    ("LIB.X_2026_03_15", "LIB.X"),
    # data inválida não casa com YYYY_MM_DD: cai no ano solto, como antes (sobra `13_01`)
    ("LIB.X_2026_13_01", "LIB.X_13_01"),                        # mês 13 não existe
    ("LIB.X_2026_03_32", "LIB.X_03_32"),                        # dia 32 não existe
    # ponto à direita conta quando NÃO vem dígito depois (o `.30` do caso pinado abaixo é
    # sufixo numérico e continua fora)
    ("ALVESDS.EMP_8_20260305._GCP", "ALVESDS.EMP_8._GCP"),
    ("BRUNO.CARTEIRA_202601._BRUNO", "BRUNO.CARTEIRA._BRUNO"),
    # mês inválido em MMYY não colapsa (13 não é mês)
    ("LIB.X_1324", "LIB.X_1324"),
    # delimitador à direita tem que ser fim ou _/- : ponto não conta
    ("ATIVOS.ATIVOS_ENCART_23_202509.30", "ATIVOS.ATIVOS_ENCART_23_202509.30"),
    # sem delimitador à esquerda não é token
    ("LIB.BASE202506", "LIB.BASE202506"),
    # normalização: sempre maiúsculo
    ("grimaldi.carga_massificados_202506", "GRIMALDI.CARGA_MASSIFICADOS"),
    # nome que viraria vazio devolve o artefato (chave vazia colapsaria tudo)
    ("202506", "202506"),
    ("", ""),
])
def test_familia_candidata(artifact, esperado):
    assert F.familia_candidata(artifact, "tabela") == esperado


@pytest.mark.parametrize("categoria", ["arquivo", "script", "", None])
def test_so_tabela_colapsa(categoria):
    """Fase 1: arquivo/script passam intactos (sem path publicado, a chave é fraca demais)."""
    assert F.familia_candidata("EXCECOES_20251110.CSV", categoria) == "EXCECOES_20251110.CSV"


@pytest.mark.parametrize("artifact,esperado", [
    ("GRIMALDI.CARGA_MASSIFICADOS_202506", ["202506"]),
    ("BASE_202401_X_202402", ["202401", "202402"]),
    ("LIB.X_20260306", ["20260306"]),
    ("CORP.HISTORICO_2016", ["2016"]),
    ("MIKE.TESTE_DESC_ENC_3", []),
])
def test_safras_no_nome(artifact, esperado):
    assert F.safras_no_nome(artifact) == esperado


@pytest.mark.parametrize("safra,esperado", [
    ("202506", (2025, 6)), ("20250612", (2025, 6)), ("2025", None), ("xx", None), ("", None),
    ("0124", (2024, 1)), ("1225", (2025, 12)),          # MMYY
    ("ABR25", (2025, 4)), ("29JAN26", (2026, 1)),       # mês em português
])
def test_safra_ym(safra, esperado):
    assert F.safra_ym(safra) == esperado


@pytest.mark.parametrize("safra,esperado", [
    # Os dias 19 e 20 produzem o mesmo prefixo que o ano, então o teste de prefixo
    # sozinho lia `200125` (20/01/25) como ano 2001 mês 25 — mês impossível, que ia
    # parar em span_meses/dispersao e disparava `rasa` contra um piso ~22 anos fundo.
    ("200125", (2025, 1)),
    ("201225", (2025, 12)),
    ("190226", (2026, 2)),
    ("20012025", (2025, 1)),
    ("19022026", (2026, 2)),
    # controle: dias vizinhos, que o prefixo já acertava — não podem regredir
    ("210125", (2025, 1)),
    ("180226", (2026, 2)),
    ("310125", (2025, 1)),
    # DDMMYY cujo ano lido como YYYYMM seria absurdo (0102) — segue DDMMYY
    ("010203", (2003, 2)),
    # ano 19xx não é safra: `_DATA` só aceita 20xx
    ("199812", None),
    ("19980101", None),
])
def test_safra_ym_dia_19_e_20_nao_viram_ano(safra, esperado):
    """Regressão: desempate YYYYMM x DDMMYY é pelo mês, não pelo prefixo."""
    assert F.safra_ym(safra) == esperado


# ---------------------------------------------------------------- guarda dos ≥2 membros

VAZIO = {"juntar": {}, "separar": set(), "familias_forcadas": {}}


def _rows(*pares):
    return [{"artifact": a, "categoria": c} for a, c in pares]


def test_familia_precisa_de_dois_membros():
    r = F.resolve(_rows(("LIB.X_202501", "tabela"), ("LIB.X_202502", "tabela"),
                        ("CORP.HISTORICO_2016", "tabela")), overrides=VAZIO)
    assert r["chave"][("tabela", "LIB.X_202501")] == "LIB.X"
    assert r["chave"][("tabela", "LIB.X_202502")] == "LIB.X"
    # datado mas sozinho: continua sendo ele mesmo, NÃO vira família "CORP.HISTORICO"
    assert r["chave"][("tabela", "CORP.HISTORICO_2016")] == "CORP.HISTORICO_2016"
    assert F.e_familia(r["membros"], "tabela", "LIB.X")
    assert not F.e_familia(r["membros"], "tabela", "CORP.HISTORICO_2016")
    assert r["membros"][("tabela", "LIB.X")] == ["LIB.X_202501", "LIB.X_202502"]


def test_membros_contados_no_corpus_inteiro_nao_no_recorte():
    """Invariante 3: identidade não pode depender do filtro em tela."""
    corpus = _rows(("LIB.X_202501", "tabela"), ("LIB.X_202502", "tabela"))
    assert F.resolve(corpus, overrides=VAZIO)["chave"][("tabela", "LIB.X_202501")] == "LIB.X"
    # se alguém resolver sobre o recorte (1 linha), a chave MUDA — é exatamente o erro que a
    # docstring do módulo manda evitar; o teste fixa o comportamento para deixá-lo visível
    recorte = _rows(("LIB.X_202501", "tabela"))
    assert F.resolve(recorte, overrides=VAZIO)["chave"][("tabela", "LIB.X_202501")] == "LIB.X_202501"


def test_categorias_nao_se_misturam():
    r = F.resolve(_rows(("BASE_202501", "tabela"), ("BASE_202502", "arquivo")), overrides=VAZIO)
    assert r["chave"][("tabela", "BASE_202501")] == "BASE_202501"    # sem irmão NA categoria
    assert r["chave"][("arquivo", "BASE_202502")] == "BASE_202502"


def test_linhas_duplicadas_nao_inflam_a_contagem_de_membros():
    """O monitor tem 1 linha por chave, mas quem chamar com o join por EGP repete artefato."""
    r = F.resolve(_rows(("LIB.X_202501", "tabela"), ("LIB.X_202501", "tabela")), overrides=VAZIO)
    assert r["chave"][("tabela", "LIB.X_202501")] == "LIB.X_202501"


# ---------------------------------------------------------------- overrides

def _ov(doc):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(doc, f)
        return f.name


def test_override_juntar_forca_familia():
    p = _ov({"juntar": [{"familia": "LIB.MESMA", "motivo": "mesma tabela, nome trocado em 2025",
                         "membros": ["LIB.ANTIGA_202412", "LIB.NOVA_202501"]}]})
    try:
        ov = F.carrega_overrides(p)
        r = F.resolve(_rows(("LIB.ANTIGA_202412", "tabela"), ("LIB.NOVA_202501", "tabela")),
                      overrides=ov)
        assert r["chave"][("tabela", "LIB.ANTIGA_202412")] == "LIB.MESMA"
        assert r["chave"][("tabela", "LIB.NOVA_202501")] == "LIB.MESMA"
    finally:
        os.unlink(p)


def test_override_separar_tira_da_familia():
    p = _ov({"separar": [{"artefato": "LIB.X_202502", "motivo": "tabela distinta, homônima"}]})
    try:
        ov = F.carrega_overrides(p)
        r = F.resolve(_rows(("LIB.X_202501", "tabela"), ("LIB.X_202502", "tabela"),
                            ("LIB.X_202503", "tabela")), overrides=ov)
        assert r["chave"][("tabela", "LIB.X_202502")] == "LIB.X_202502"
        assert r["chave"][("tabela", "LIB.X_202501")] == "LIB.X"
        assert r["membros"][("tabela", "LIB.X")] == ["LIB.X_202501", "LIB.X_202503"]
    finally:
        os.unlink(p)


def test_override_ausente_e_estado_normal():
    ov = F.carrega_overrides(os.path.join(tempfile.gettempdir(), "nao-existe-familias.json"))
    assert ov == VAZIO


def test_arquivo_de_overrides_do_repo_carrega():
    assert F.carrega_overrides() is not None


def test_juntar_com_um_membro_so_e_valido():
    """Um membro basta quando a família JÁ existe pela regra.

    O caso real são os nomes que perderam a data para uma macro (`PAGOS_CYBER_&DAT_EXEC.`
    vira `PERF_CL.PAGOS_CYBER_`) ou para um curinga (`MIKE.TESTE_ENC_1PMT_:`): o override
    só redireciona esse nome órfão para a família que a regra já montou com as safras
    datadas. Exigir um segundo membro obrigaria a fixar no arquivo o nome de uma safra
    qualquer — e aí um re-key do pipeline derrubaria a carga dos overrides (strict=True)
    por um motivo que nada tem a ver com a exceção.
    """
    p = _ov({"juntar": [{"familia": "PERF_CL.PAGOS_CYBER", "motivo": "macro &DAT_EXEC.",
                         "membros": ["PERF_CL.PAGOS_CYBER_"]}]})
    try:
        ov = F.carrega_overrides(p)
        assert ov["juntar"] == {"PERF_CL.PAGOS_CYBER_": "PERF_CL.PAGOS_CYBER"}
    finally:
        os.unlink(p)


def test_membro_unico_entra_na_familia_montada_pela_regra():
    """O efeito no corpus: o nome órfão passa a ser membro da família das safras datadas."""
    ov = {"juntar": {"PERF_CL.PAGOS_CYBER_": "PERF_CL.PAGOS_CYBER"}, "separar": set(),
          "familias_forcadas": {}}
    rows = [{"artifact": a, "categoria": "tabela"} for a in
            ("PERF_CL.PAGOS_CYBER_202501", "PERF_CL.PAGOS_CYBER_202502", "PERF_CL.PAGOS_CYBER_")]
    res = F.resolve(rows, overrides=ov)
    assert res["chave"][("tabela", "PERF_CL.PAGOS_CYBER_")] == "PERF_CL.PAGOS_CYBER"
    assert len(res["membros"][("tabela", "PERF_CL.PAGOS_CYBER")]) == 3


@pytest.mark.parametrize("doc,trecho", [
    ({"juntar": [{"familia": "LIB.X", "membros": ["LIB.A_202501", "LIB.B_202501"]}]}, "motivo"),
    ({"juntar": [{"familia": "LIB.X", "motivo": "x", "membros": []}]}, "membro"),
    ({"juntar": [{"motivo": "x", "membros": ["LIB.A", "LIB.B"]}]}, "sem 'familia'"),
    ({"separar": [{"motivo": "x"}]}, "sem 'artefato'"),
    ({"separar": [{"artefato": "LIB.A_202501"}]}, "motivo"),
    ({"juntar": [{"familia": "LIB.X", "motivo": "x", "membros": ["LIB.A_202501", "LIB.B_202501"]},
                 {"familia": "LIB.Y", "motivo": "x", "membros": ["LIB.A_202501", "LIB.C_202501"]}]},
     "duas famílias"),
    ({"juntar": [{"familia": "LIB.X", "motivo": "x", "membros": ["LIB.A_202501", "LIB.B_202501"]}],
      "separar": [{"artefato": "LIB.A_202501", "motivo": "x"}]}, "ao mesmo tempo"),
])
def test_override_invalido_falha_alto(doc, trecho):
    p = _ov(doc)
    try:
        with pytest.raises(F.OverridesInvalidos) as e:
            F.carrega_overrides(p)
        assert trecho in str(e.value)
    finally:
        os.unlink(p)


def test_override_para_artefato_inexistente_falha_no_resolve():
    """Exceção órfã (o pipeline renomeou o artefato) não pode apodrecer em silêncio."""
    p = _ov({"separar": [{"artefato": "LIB.SUMIU_202501", "motivo": "x"}]})
    try:
        ov = F.carrega_overrides(p)
        with pytest.raises(F.OverridesInvalidos) as e:
            F.resolve(_rows(("LIB.X_202501", "tabela")), overrides=ov)
        assert "não existem no corpus" in str(e.value)
        # strict=False é a saída de emergência, não o default
        assert F.resolve(_rows(("LIB.X_202501", "tabela")), overrides=ov, strict=False)
    finally:
        os.unlink(p)


# ---------------------------------------------------------------- paridade Python x SQL

def test_sql_usa_o_mesmo_token_da_regra_python():
    """Quebra se alguém reescrever o regex de um lado só (a paridade em dados roda contra prod)."""
    sql = F.familia_candidata_sql(overrides=VAZIO)
    assert F.TOKEN_SAFRA.pattern in sql
    assert "upper(artifact)" in sql and "categoria = 'tabela'" in sql


def test_sql_da_chave_efetiva_tem_a_guarda_dos_dois_membros():
    sql = F.familia_efetiva_sql(overrides=VAZIO)
    assert "count(*) OVER (PARTITION BY categoria," in sql
    assert "> 1" in sql


def test_sql_embute_os_overrides():
    p = _ov({"juntar": [{"familia": "LIB.MESMA", "motivo": "x",
                         "membros": ["LIB.A_202501", "LIB.B_202501"]}],
             "separar": [{"artefato": "LIB.C_202501", "motivo": "x"}]})
    try:
        sql = F.familia_candidata_sql(overrides=F.carrega_overrides(p))
        assert "'LIB.A_202501'" in sql and "'LIB.MESMA'" in sql and "'LIB.C_202501'" in sql
    finally:
        os.unlink(p)


def test_sql_escapa_aspas_no_literal():
    p = _ov({"separar": [{"artefato": "LIB.O'BRIEN_202501", "motivo": "x"}]})
    try:
        sql = F.familia_candidata_sql(overrides=F.carrega_overrides(p))
        assert "\\'" in sql
    finally:
        os.unlink(p)


# ---- nome de exibição com marcador {SAFRA} (pedido 2026-09-16) ------------------------

def test_marcador_preserva_posicao_do_token():
    assert (F.nome_com_marcador("GRIMALDI.CARGA_MASSIFICADOS_202506")
            == "GRIMALDI.CARGA_MASSIFICADOS_{SAFRA}")


def test_marcador_no_meio_do_nome():
    assert F.nome_com_marcador("ALVESDS.EMP_8_20250124_GCP") == "ALVESDS.EMP_8_{SAFRA}_GCP"


def test_marcador_preserva_separador_hifen():
    assert F.nome_com_marcador("BASE-202506") == "BASE-{SAFRA}"


def test_marcador_em_nome_sem_token_nao_muda():
    assert F.nome_com_marcador("CONTATOS.AUX_BASE_CYBER") == "CONTATOS.AUX_BASE_CYBER"


def test_marcador_vale_para_tabela_e_arquivo_nunca_para_script():
    """REVISADO em 02/10/2026. Este teste afirmava que o marcador só valia para `tabela`,
    porque `arquivo` não formava família. Agora forma — por (diretório, padrão) — e o
    rótulo precisa do marcador, senão a tabela mostraria a chave com o diretório inteiro.
    `script` segue de fora: nunca vira família."""
    assert F.nome_com_marcador("BASE_202506.CSV", categoria="arquivo") == "BASE_{SAFRA}.CSV"
    assert F.nome_com_marcador("BASE_202506.SAS", categoria="script") == "BASE_202506.SAS"


def test_marcador_troca_todos_os_tokens():
    """Dois tokens no nome: os dois viram marcador (a chave de família removeria os dois)."""
    assert F.nome_com_marcador("X_202501_Y_202502") == "X_{SAFRA}_Y_{SAFRA}"


# ---- exceção curada do DIAS_UTEIS (feedback do BV, 2026-09-16) ----------------------


def _tabs(*arts, cat="tabela"):
    """Linhas de corpus só com nome (o `_rows` acima é por (artefato, categoria))."""
    return [{"artifact": a, "categoria": cat} for a in arts]


def test_override_separa_dias_uteis_do_ano_solto():
    """Roda com o `familias_overrides.json` REAL — a exceção versionada é o que está sob teste.

    `B_GERAL.DIAS_UTEIS` + `_2026` são tabelas diferentes (BV, 16/09/2026). O padrão
    {corrente, um ano} aparece em 10 famílias do corpus, mas só esta é exceção: as outras 9
    são safra, e por isso a guarda mora no arquivo de exceções, não na regra.
    """
    # strict=False: o corpus aqui são 4 nomes sintéticos, e os overrides de `juntar` (os
    # nomes que perderam a data para macro/curinga) apontam para artefatos reais que não
    # estão nele. Quem confere override contra o corpus DE VERDADE é
    # `scripts/verifica_familias.py`, contra o schema publicado — este teste é da regra.
    res = F.resolve(_tabs("B_GERAL.DIAS_UTEIS", "B_GERAL.DIAS_UTEIS_2026",
                          "CARNEIRO.CARTEIRA_COMPLETA", "CARNEIRO.CARTEIRA_COMPLETA_2026"),
                    strict=False)
    assert not F.e_familia(res["membros"], "tabela", "B_GERAL.DIAS_UTEIS")
    assert res["chave"][("tabela", "B_GERAL.DIAS_UTEIS_2026")] == "B_GERAL.DIAS_UTEIS_2026"
    # o análogo NÃO curado segue família — a exceção é cirúrgica, não um padrão
    assert F.e_familia(res["membros"], "tabela", "CARNEIRO.CARTEIRA_COMPLETA")


def test_overrides_versionados_sao_validos():
    """O arquivo que vai no deploy tem de carregar (motivo obrigatório, JSON válido)."""
    ov = F.carrega_overrides()
    assert "B_GERAL.DIAS_UTEIS_2026" in ov["separar"]
    # os nomes que perderam a data (macro ou curinga) entram por `juntar`, um membro cada
    assert ov["juntar"]["PERF_CL.PAGOS_CYBER_"] == "PERF_CL.PAGOS_CYBER"
    assert ov["juntar"]["MIKE.TESTE_ENC_1PMT_"] == "MIKE.TESTE_ENC_1PMT"
    assert all(k.endswith("_") for k in ov["juntar"]), \
        "só nome com separador solto entra aqui; qualquer outro é mudança de regra disfarçada"


# ---- armadilha de CAIXA no padrão (2026-09-17) ---------------------------------------

def test_padrao_de_data_nao_depende_de_flag_de_caixa():
    """O padrão tem de ser literalmente o mesmo nos dois motores.

    Ao portar o mês em português eu escrevi `jan|fev|...` e me apoiei no `re.I` do Python.
    O lado SQL não tem flag e recebe o artefato em `upper()`: resultado, 174 divergências
    de paridade em 10.451 linhas. O padrão agora é MAIÚSCULO e sem flag — este teste falha
    se alguém reintroduzir minúscula ou `re.I`.
    """
    assert not F.TOKEN_SAFRA.flags & re.IGNORECASE
    # nenhuma minúscula no padrão: é a invariante, não só "jan" ausente
    assert re.search(r"[a-zç]", F._DATA) is None, "padrão com minúscula volta a depender de flag"
    assert "JAN" in F._DATA and "DEZ" in F._DATA


def test_mes_em_portugues_casa_nas_duas_formas():
    """Mesma entrada, mesmo resultado na forma Python e na expressão SQL (caixa alta)."""
    assert F.familia_candidata("SEGUROS.RECLAMACOES_ICATU_ABR25") == "SEGUROS.RECLAMACOES_ICATU"
    sql = F.familia_candidata_sql()
    assert "ABR" in sql and "jan" not in sql


# ---- SAFRA EM ARQUIVO (02/10/2026) ------------------------------------------------------
# O ADR 0002 excluía `arquivo` porque o app não publicava caminho físico. A premissa caiu
# (73% dos 4.420 arquivos têm `paths_fisicos` em prod), mas o risco que ela guardava é REAL:
# 64 das 145 famílias que o nome sozinho formaria abrangem 2+ diretórios. Daí a chave ser
# (diretório, padrão).

def _fam(art, cat="arquivo", paths=None):
    return F.familia_candidata(art, cat, paths)


def test_arquivo_datado_na_mesma_pasta_colapsa():
    a = _fam("EXCECOES_20250701.CSV", paths="/RISCOSBV/COBRANCA/EXCECOES_20250701.CSV")
    b = _fam("EXCECOES_20250702.CSV", paths="/RISCOSBV/COBRANCA/EXCECOES_20250702.CSV")
    assert a == b
    assert a.startswith("/RISCOSBV/COBRANCA|")


def test_arquivo_datado_em_pastas_diferentes_NAO_colapsa():
    """O caso que o ADR temia, e que existe: EXCECOES.CSV tem 258 membros em 2 pastas."""
    a = _fam("EXCECOES_20250701.CSV", paths="/A/EXCECOES_20250701.CSV")
    b = _fam("EXCECOES_20250701.CSV", paths="/B/EXCECOES_20250701.CSV")
    assert a != b


def test_arquivo_sem_path_nao_colapsa():
    """Ausência de evidência não vira evidência — fica o artefato, como antes do ADR cair."""
    assert _fam("EXCECOES_20250701.CSV") == "EXCECOES_20250701.CSV"
    assert _fam("EXCECOES_20250701.CSV", paths="") == "EXCECOES_20250701.CSV"
    assert _fam("EXCECOES_20250701.CSV", paths="EXCECOES_20250701.CSV") == "EXCECOES_20250701.CSV"


def test_arquivo_nao_datado_fica_intacto():
    """Sem token de data não é safra. Precisa continuar 1:1 com o artefato, senão
    `_fam_sql_egp` (que conta DISTINCT candidato sem janela) passa a contar errado."""
    assert _fam("ANSWERS.CSV", paths="/A/B/ANSWERS.CSV") == "ANSWERS.CSV"


def test_tabela_nao_muda_com_a_regra_de_arquivo():
    assert F.familia_candidata("LIB.X_20250701", "tabela") == "LIB.X"
    assert F.familia_candidata("LIB.X_20250701", "tabela", "/qualquer/path") == "LIB.X"


def test_diretorio_de_pega_o_primeiro_caminho_e_aceita_as_duas_barras():
    assert F.diretorio_de("/a/b/x.csv") == "/A/B"
    assert F.diretorio_de("N:\\DRSC\\x.csv") == "N:\\DRSC"
    assert F.diretorio_de("/a/x.csv | /z/x.csv") == "/A"      # o PRIMEIRO
    assert F.diretorio_de("") == ""
    assert F.diretorio_de("semdiretorio.csv") == ""


def test_sql_de_arquivo_tem_o_ramo_e_o_default_e_sem_evidencia():
    """O default de `paths` é `''` e NÃO um nome de coluna: a auditoria lê
    sas_inputs_audit, que não tem paths_fisicos — default de coluna quebraria em runtime."""
    sem_ov = {"juntar": {}, "separar": set()}
    padrao = F.familia_candidata_sql(overrides=sem_ov)
    assert "'arquivo'" in padrao
    assert "paths_fisicos" not in padrao          # default não cita coluna
    com = F.familia_candidata_sql(paths="i.paths_fisicos", overrides=sem_ov)
    assert "i.paths_fisicos" in com


def test_rotulo_de_familia_de_arquivo_usa_o_marcador_e_nao_o_diretorio():
    """A CHAVE do arquivo leva o diretório (identidade), mas o RÓTULO não pode: na tabela
    `/RISCOSBV/COBRANCA/SATIE/EXCECAO|EXCECOES.CSV` é ilegível. O diretório fica no tooltip,
    que já mostra a chave crua."""
    assert F.nome_com_marcador("EXCECOES_20250701.CSV", "arquivo") == "EXCECOES_{SAFRA}.CSV"
    assert F.nome_com_marcador("ANSWERS.CSV", "arquivo") == "ANSWERS.CSV"
    assert F.nome_com_marcador("LIB.X_202506", "tabela") == "LIB.X_{SAFRA}"
    assert F.nome_com_marcador("X_20250701.SAS", "script") == "X_20250701.SAS"
