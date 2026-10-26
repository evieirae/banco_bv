#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decisões por EGP (src/egps_decisoes.csv): o que o corpus não sabe e o publish desfazia.

Medido em 16/10/2026: as 11 duplicatas removidas à mão estavam todas de volta em prod, e o
renome do CPF_Contrato era refeito à mão a cada publish. Estes testes travam as duas
promessas do módulo: a decisão vale na leitura do corpus, e decisão que não se aplica
(órfã, conflitante) para o processo em vez de sumir.

Roda como:
    egps_analysis/venv/bin/python -m pytest egps_analysis/test_egp_decisoes.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import egp_decisoes as dec  # noqa: E402

CAB = "egp_key,acao,alvo,motivo,data,quem\n"


def _csv(tmp_path, linhas, cab=CAB):
    p = tmp_path / "egps_decisoes.csv"
    p.write_text(cab + "".join(linhas), encoding="utf-8")
    return str(p)


def _corpus(tmp_path, arquivos):
    """arquivos = {stem: projeto do cabeçalho}"""
    d = tmp_path / "text_egps"
    d.mkdir()
    for stem, projeto in arquivos.items():
        (d / f"{stem}.txt").write_text(
            f"PROJECT: {projeto}\nLINES_OF_CODE: 10\nEND_METADATA\ncorpo\n", encoding="utf-8")
    return str(d)


# ---------------------------------------------------------------- carrega

def test_arquivo_ausente_para_o_processo(tmp_path):
    with pytest.raises(dec.DecisaoInvalida, match="não existe"):
        dec.carrega(str(tmp_path / "nao_existe.csv"))


def test_cabecalho_errado_para_o_processo(tmp_path):
    path = _csv(tmp_path, [], cab="egp,acao\n")
    with pytest.raises(dec.DecisaoInvalida, match="cabeçalho"):
        dec.carrega(path)


def test_excluir_e_renomear(tmp_path):
    path = _csv(tmp_path, [
        "A__dup,excluir,,duplicata de A__orig,2026-09-21,x\n",
        "A__v1,renomear,A__v2,D013,2026-08-24,x\n",
    ])
    d = dec.carrega(path)
    assert d.nome("A__dup") is None
    assert d.nome("A__v1") == "A__v2"
    assert d.nome("A__outro") == "A__outro"
    assert d.nomes_proibidos() == {"A__dup", "A__v1"}


def test_cpf_alvo_do_renome_e_o_nome_do_excluido(tmp_path):
    """O caso real: o `__v2` pequeno sai e o v1 passa a se chamar `__v2`. O nome `__v2`
    sai das proibições, porque é o nome que o v1 publica."""
    path = _csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
    ])
    d = dec.carrega(path)
    assert d.nome("C__CPF__v2") is None
    assert d.nome("C__CPF") == "C__CPF__v2"
    assert d.nomes_proibidos() == {"C__CPF"}


@pytest.mark.parametrize("linhas,trecho", [
    (["A,excluir,,,2026-01-01,x\n"], "sem motivo"),
    (["A,excluir,B,m,2026-01-01,x\n"], "não leva alvo"),
    (["A,renomear,,m,2026-01-01,x\n"], "renomear sem alvo"),
    (["A,tirar_output_do_escopo,,m,2026-01-01,x\n"], "sem alvo"),
    (["A,apagar,,m,2026-01-01,x\n"], "desconhecida"),
    ([",excluir,,m,2026-01-01,x\n"], "egp_key vazio"),
    (["A,excluir,,m,2026-01-01,x\n", "A,excluir,,m,2026-01-01,x\n"], "excluído duas vezes"),
    (["A,renomear,B,m,2026-01-01,x\n", "A,renomear,C,m,2026-01-01,x\n"], "renomeado duas vezes"),
    (["A,excluir,,m,2026-01-01,x\n", "A,renomear,B,m,2026-01-01,x\n"], "excluído e renomeado"),
    (["A,excluir,,m,2026-01-01,x\n", "A,tirar_output_do_escopo,LIB.T,m,2026-01-01,x\n"],
     "EGP excluído"),
    (["A,renomear,Z,m,2026-01-01,x\n", "B,renomear,Z,m,2026-01-01,x\n"], "mais de um renome"),
    (["A,excluir,,duplicata de X, revisão,2026-09-21,x\n"], "colunas a mais"),
    (["A,renomear,A,m,2026-01-01,x\n"], "próprio nome"),
    (["A,renomear,B,m,2026-01-01,x\n", "B,renomear,C,m,2026-01-01,x\n"], "o alvo também é renomeado"),
    (['A,excluir,,"duplicata, revisão,2026-09-21,x\n', "B,excluir,,m,2026-09-21,x\n"],
     "aspas sem fechar"),
])
def test_arquivo_incoerente_para_o_processo(tmp_path, linhas, trecho):
    with pytest.raises(dec.DecisaoInvalida, match=trecho):
        dec.carrega(_csv(tmp_path, linhas))


def test_arquivo_fora_de_utf8_para_o_processo(tmp_path):
    p = tmp_path / "egps_decisoes.csv"
    p.write_bytes((CAB + "A,excluir,,revisão,2026-01-01,x\n").encode("cp1252"))
    with pytest.raises(dec.DecisaoInvalida, match="não é UTF-8"):
        dec.carrega(str(p))


def test_erro_aponta_a_linha_fisica(tmp_path):
    """Linha em branco no meio não desloca o número que a mensagem mostra."""
    with pytest.raises(dec.DecisaoInvalida, match=r"linha 3 \(A\): sem motivo"):
        dec.carrega(_csv(tmp_path, ["\n", "A,excluir,,,2026-01-01,x\n"]))


def test_arquivo_salvo_com_bom_e_aceito(tmp_path):
    """Excel salva CSV UTF-8 com BOM; o cabeçalho tem de casar mesmo assim."""
    d = dec.carrega(_csv(tmp_path, ["A,excluir,,duplicata,2026-01-01,x\n"], cab="\ufeff" + CAB))
    assert d.nome("A") is None


def test_output_fora_do_escopo_vale_pelo_nome_publicado(tmp_path):
    """A decisão cita o nome do corpus; o publish pergunta pelo nome já renomeado."""
    path = _csv(tmp_path, [
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
        "C__CPF,tirar_output_do_escopo,CARNEIRO.BASE_3040,D013,2026-08-24,x\n",
    ])
    d = dec.carrega(path)
    assert d.output_no_escopo("C__CPF__v2", "CARNEIRO.BASE_3040_202509") is False
    assert d.output_no_escopo("C__CPF__v2", "carneiro.base_3040_202510") is False
    assert d.output_no_escopo("C__CPF__v2", "CARNEIRO.OUTRA") is True
    assert d.output_no_escopo("C__OUTRO", "CARNEIRO.BASE_3040_202509") is True
    assert d.outputs_fora() == {"C__CPF__v2": ("CARNEIRO.BASE_3040",)}


# ---------------------------------------------------------------- aplica_ao_corpus

def test_cabecalho_vale_o_ultimo_project_como_no_orquestrador(tmp_path):
    """parse_txt_metadata do orquestrador fica com o último PROJECT: antes do END_METADATA;
    o nome publicado tem de ser o mesmo, senão a decisão e o relatório falam de EGPs diferentes."""
    d = tmp_path / "text_egps"
    d.mkdir()
    (d / "X.txt").write_text("PROJECT: X_velho\nPROJECT: X\nEND_METADATA\nPROJECT: Y\n",
                             encoding="utf-8")
    assert dec.projeto_do_cabecalho(str(d / "X.txt")) == "X"


def test_corpus_sai_sem_excluido_e_com_renome(tmp_path):
    txt = _corpus(tmp_path, {"C__CPF": "C__CPF", "C__CPF__v2": "C__CPF__v2",
                             "A__dup": "A__dup", "A__orig": "A__orig"})
    d = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
        "A__dup,excluir,,duplicata,2026-09-21,x\n",
    ]))
    saida = dec.aplica_ao_corpus(txt, d)
    assert [(os.path.basename(a.caminho), a.stem, a.projeto) for a in saida] == [
        ("A__orig.txt", "A__orig", "A__orig"),
        ("C__CPF.txt", "C__CPF__v2", "C__CPF__v2"),
    ]


def test_parte_de_projeto_multiarquivo_e_excluida_junto(tmp_path):
    """Exclusão é pelo PROJECT: do cabeçalho, então pega todas as partes do projeto."""
    txt = _corpus(tmp_path, {"R__proj__01": "R__proj", "R__proj__02": "R__proj", "R__x": "R__x"})
    d = dec.carrega(_csv(tmp_path, ["R__proj,excluir,,teste,2026-01-01,x\n"]))
    assert [a.projeto for a in dec.aplica_ao_corpus(txt, d)] == ["R__x"]


@pytest.mark.parametrize("linha", [
    "A__dupp,excluir,,duplicata,2026-09-21,x\n",
    "A__v11,renomear,A__v2,D013,2026-08-24,x\n",
    "A__v11,tirar_output_do_escopo,LIB.T,D013,2026-08-24,x\n",
])
def test_decisao_orfa_para_o_processo(tmp_path, linha):
    """Erro de digitação ou .txt apagado: a decisão não se aplicaria e a duplicata (ou o
    renome) voltaria calada. Vale para as três ações."""
    txt = _corpus(tmp_path, {"A__orig": "A__orig"})
    d = dec.carrega(_csv(tmp_path, [linha]))
    with pytest.raises(dec.DecisaoInvalida, match="não está no corpus"):
        dec.aplica_ao_corpus(txt, d)


def test_renome_para_nome_de_egp_mantido_para_o_processo(tmp_path):
    """O orquestrador une projetos de mesmo nome: o renome juntaria dois EGPs em silêncio."""
    txt = _corpus(tmp_path, {"A": "A", "B": "B"})
    d = dec.carrega(_csv(tmp_path, ["A,renomear,B,m,2026-01-01,x\n"]))
    with pytest.raises(dec.DecisaoInvalida, match="já existe um EGP B"):
        dec.aplica_ao_corpus(txt, d)


def test_renome_para_stem_de_txt_mantido_para_o_processo(tmp_path):
    """Os leitores do publish chaveados por stem juntariam os dois .txt."""
    txt = _corpus(tmp_path, {"03-X": "SAS_UC4__03-X", "A": "A"})
    d = dec.carrega(_csv(tmp_path, ["A,renomear,03-X,m,2026-01-01,x\n"]))
    with pytest.raises(dec.DecisaoInvalida, match="já existe um EGP 03-X"):
        dec.aplica_ao_corpus(txt, d)


def test_renome_de_egp_com_stem_diferente_do_projeto_para_o_processo(tmp_path):
    """Os leitores por stem não saberiam o nome novo: só renomeia EGP cujo .txt tem o nome do projeto."""
    txt = _corpus(tmp_path, {"R__proj__01": "R__proj"})
    d = dec.carrega(_csv(tmp_path, ["R__proj,renomear,R__novo,m,2026-01-01,x\n"]))
    with pytest.raises(dec.DecisaoInvalida, match="mesmo nome do projeto"):
        dec.aplica_ao_corpus(txt, d)


# ---------------------------------------------------------------- no publish

def test_publish_le_o_corpus_pelo_nome_publicado(tmp_path):
    """O LOC do v1 vai para o nome novo e o do `__v2` pequeno descartado não entra. Antes, o nó
    `__v2` mostrava o LOC do arquivo pequeno (106 em vez de 1114)."""
    import publish_to_databricks as pub
    txt = tmp_path / "text_egps"
    txt.mkdir()
    for stem, loc in (("C__CPF", 1114), ("C__CPF__v2", 106)):
        (txt / f"{stem}.txt").write_text(
            f"PROJECT: {stem}\nLINES_OF_CODE: {loc}\nEND_METADATA\n", encoding="utf-8")
    d = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
    ]))
    assert pub.build_loc_tasks(dec.aplica_ao_corpus(str(txt), d)) == {"C__CPF__v2": (1114, 0)}


def test_publish_nome_da_lista_indicium(tmp_path):
    """indi_231 cita o CPF pelo nome antigo (linha 48); quem editar a linha para o nome que o
    app mostra também passa. EGP excluído na lista Indicium é contradição: para."""
    import publish_to_databricks as pub
    d = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
        "A__dup,excluir,,duplicata,2026-09-21,x\n",
    ]))
    assert pub._nome_indi("A__orig", d) == "A__orig"
    assert pub._nome_indi("C__CPF", d) == "C__CPF__v2"
    assert pub._nome_indi("C__CPF__v2", d) == "C__CPF__v2"
    with pytest.raises(dec.DecisaoInvalida, match="lista Indicium"):
        pub._nome_indi("A__dup", d)


def test_publish_recusa_prefixo_de_output_que_nao_acha_nada(tmp_path):
    """Prefixo digitado errado deixaria os outputs no escopo calado: é decisão que não se
    aplica, então para."""
    import publish_to_databricks as pub
    egp_out = {("C__CPF__v2", "CARNEIRO.BASE_3040_202509"):
               {"projeto": "C__CPF__v2", "artifact": "CARNEIRO.BASE_3040_202509"}}
    errado = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,tirar_output_do_escopo,CARNEIRO.BASE3040,D013,2026-08-24,x\n"]))
    with pytest.raises(dec.DecisaoInvalida,
                       match="nenhum output de C__CPF__v2 começa com CARNEIRO.BASE3040"):
        pub._confere_outputs_fora(errado, egp_out)
    certo = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,tirar_output_do_escopo,carneiro.base_3040,D013,2026-08-24,x\n"]))
    pub._confere_outputs_fora(certo, egp_out)  # caixa diferente casa; não levanta


CAB06 = "project,artifact,category,area,path,status_validacao,source_type\n"
DEC_CPF = ("egp_key,acao,alvo,motivo,data,quem\n"
           "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n"
           "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n"
           "C__CPF,tirar_output_do_escopo,CARNEIRO.BASE_3040,D013,2026-08-24,x\n")


def _publish_sobre_fixture(tmp_path, monkeypatch, linhas_06):
    """build() do publish sobre corpus e CSVs mínimos, sem banco: as constantes de caminho
    apontam para tmp_path. O v1 do CPF tem LOC 50 e marca INFO_CONTA como só-contribuição; o
    `__v2` pequeno tem LOC 7."""
    import publish_to_databricks as pub
    txt = tmp_path / "text_egps"
    txt.mkdir()
    (txt / "C__CPF.txt").write_text(
        "PROJECT: C__CPF\nLINES_OF_CODE: 50\nNON_CREATOR_OUTPUTS: CARNEIRO.INFO_CONTA\n"
        "END_METADATA\n", encoding="utf-8")
    (txt / "C__CPF__v2.txt").write_text(
        "PROJECT: C__CPF__v2\nLINES_OF_CODE: 7\nEND_METADATA\n", encoding="utf-8")
    (tmp_path / "dec.csv").write_text(DEC_CPF, encoding="utf-8")
    (tmp_path / "06.csv").write_text(CAB06 + "".join(
        f"{p},{a},{c},Cobranças,,,\n" for p, a, c in linhas_06), encoding="utf-8")
    (tmp_path / "03.csv").write_text("alvo,dep,via,n_produtores\n", encoding="utf-8")
    (tmp_path / "indi.csv").write_text(
        "egp_dor1,area,status_extracao,project_no_06 / observacao\n"
        "cpf,Cobrança,exato,C__CPF\n", encoding="utf-8")
    for nome, val in (("TXT_DIR", str(txt)), ("DECISOES", str(tmp_path / "dec.csv")),
                      ("R06", str(tmp_path / "06.csv")), ("R03", str(tmp_path / "03.csv")),
                      ("R04", str(tmp_path / "nao.csv")), ("INDI", str(tmp_path / "indi.csv")),
                      ("EGPS_CASCA", str(tmp_path / "nao.csv"))):
        monkeypatch.setattr(pub, nome, val)
    return pub


def test_build_aplica_as_decisoes(tmp_path, monkeypatch):
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF__v2", "CARNEIRO.BASE_3040_202509", "table_out"),
        ("C__CPF__v2", "CARNEIRO.INFO_CONTA", "table_out"),
        ("C__CPF__v2", "LIB.ENTRADA", "table_in"),
    ])
    data = pub.build()
    no = {r["projeto"]: r for r in data["nodes"]}
    assert no["C__CPF__v2"]["loc"] == 50
    assert no["C__CPF__v2"]["escopo_indi"] is True
    out = {r["chave_canonica"]: r["escopo_indi"] for r in data["outputs"]}
    assert out == {"CARNEIRO.BASE_3040_202509": False, "CARNEIRO.INFO_CONTA": True}
    eo = {r["artifact"]: r for r in data["egp_outputs"]}
    assert {a: r["escopo_indi"] for a, r in eo.items()} == {
        "CARNEIRO.BASE_3040_202509": False, "CARNEIRO.INFO_CONTA": True}
    assert eo["CARNEIRO.INFO_CONTA"]["apenas_contribui"] is True
    assert [r["projeto"] for r in data["indicium"]] == ["C__CPF__v2"]


def test_build_recusa_csv_gerado_sem_as_decisoes(tmp_path, monkeypatch):
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF", "CARNEIRO.BASE_3040_202509", "table_out")])
    with pytest.raises(dec.DecisaoInvalida, match="rode o orchestrator_inventory.py"):
        pub.build()


def test_build_recusa_prefixo_sem_output(tmp_path, monkeypatch):
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF__v2", "CARNEIRO.INFO_CONTA", "table_out")])
    with pytest.raises(dec.DecisaoInvalida, match="nenhum output de C__CPF__v2"):
        pub.build()


def test_build_recusa_indi_231_com_o_mesmo_egp_por_dois_nomes(tmp_path, monkeypatch):
    """Nome antigo e nome publicado na lista Indicium viram o mesmo EGP: o escopo seria
    semeado duas vezes e o funil contaria o EGP em dobro, sem aviso."""
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF__v2", "CARNEIRO.BASE_3040_202509", "table_out")])
    (tmp_path / "indi.csv").write_text(
        "egp_dor1,area,status_extracao,project_no_06 / observacao\n"
        "cpf,Cobrança,exato,C__CPF\n"
        "cpf_novo,Cobrança,exato,C__CPF__v2\n", encoding="utf-8")
    with pytest.raises(dec.DecisaoInvalida, match="cita o mesmo EGP por dois nomes"):
        pub.build()


# ---------------------------------------------------------------- o arquivo versionado

def test_arquivo_versionado_bate_com_o_corpus_versionado():
    """O src/egps_decisoes.csv do repo carrega e se aplica ao text_egps/ do repo."""
    base = os.path.dirname(os.path.abspath(__file__))
    d = dec.carrega()
    saida = dec.aplica_ao_corpus(os.path.join(base, "text_egps"), d)
    projetos = {a.projeto for a in saida}
    assert "Cobranças__CPF_Contrato" not in projetos
    assert "Cobranças__CPF_Contrato__v2" in projetos
    assert "Cobranças__Envio SMS - Pagamentos - Cartão Amigável__v2" not in projetos
    assert "Cobranças__Envio SMS - Pagamentos - Cartão Amigável" in projetos
