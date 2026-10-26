#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressão: um `.sas7bdat` lido por caminho físico É a tabela SAS do LIBNAME que
aponta para aquele diretório — não um "arquivo" a ingerir.

Padrão real no corpus (Cobranças__Reneg_Over30e90_Ever30_v2, Fase Administrativa,
Performance_Saldo_COLORE): o EGP descompacta o dataset em disco, lê via libname e
recompacta —

    x gunzip '/riscosbv/cobranca/caroline/michael/teste_enc_1pmt_20211208.sas7bdat.gz';
    ... set MIKE.TESTE_ENC_1PMT_20211208 ...     LIBNAME MIKE '/riscosbv/cobranca/caroline/michael'
    x gzip   '/riscosbv/cobranca/caroline/michael/teste_enc_1pmt_20211208.sas7bdat';

O caminho entra em `files_read` e virava `file_in` (categoria 'arquivo'), que NUNCA
passa pela árvore de modernização (só `table_in`/`table_out`) — logo ficava
`modernizada_auto='A ingerir'` para sempre. Ver
docs/analises/RELATORIO_INPUTS_SAS7BDAT_COMO_TABELA_2026-08-27.md.

Uso: egps_analysis/venv/bin/python test_sas7bdat_como_tabela.py
"""
import orchestrator_inventory as o

f = o._sas7bdat_as_libname_table

GTAVARES = "/riscosbv/cobranca/gtavares"
MARCACAO = "/riscosbv/cobranca/gtavares/Reneg/Marcacao"
MIKE = "/riscosbv/cobranca/caroline/michael"

# (nome, path do arquivo, libname_dict, prefer_libs, esperado)
CASES = [
    (
        "caso base: arquivo no diretório do LIBNAME vira LIB.MEMBRO",
        f"{GTAVARES}/empilha_reneg_final_202406.sas7bdat",
        {"GTAVARES": GTAVARES}, (),
        "GTAVARES.EMPILHA_RENEG_FINAL_202406",
    ),
    (
        "subdiretório ganha do pai (match é por diretório exato, não prefixo)",
        f"{MARCACAO}/marcacao_reneg_tescon_202409.sas7bdat",
        {"GTAVARES": GTAVARES, "MARCACAO": MARCACAO}, (),
        "MARCACAO.MARCACAO_RENEG_TESCON_202409",
    ),
    (
        "alias ambíguo (2 librefs no mesmo dir) sem preferência -> determinístico",
        f"{MARCACAO}/cubo_over30_202408_2.sas7bdat",
        {"EMPILHA": MARCACAO, "MARCACAO": MARCACAO}, (),
        "EMPILHA.CUBO_OVER30_202408_2",
    ),
    (
        "alias ambíguo COM preferência: usa o libref já visto como table_in",
        f"{MARCACAO}/cubo_over30_202408_2.sas7bdat",
        {"EMPILHA": MARCACAO, "MARCACAO": MARCACAO}, ("MARCACAO",),
        "MARCACAO.CUBO_OVER30_202408_2",
    ),
    (
        "normalização: barra final, barra invertida, caixa e barras duplicadas",
        "/RISCOSBV//COBRANCA\\CAROLINE/MICHAEL/teste_enc_1pmt_20211208.SAS7BDAT",
        {"MIKE": MIKE + "/"}, (),
        "MIKE.TESTE_ENC_1PMT_20211208",
    ),
    # ---- guards: nunca converter (o input segue como 'arquivo') ----
    (
        "guard: nenhum libname aponta para o diretório do arquivo",
        "/riscosbv/cobranca/erocha/CARTAO/CL/MIS/pagos_cyber_202404.sas7bdat",
        {"PAGOSCBR": "/riscosbv/cobranca/jcarneiro/estrategia_cartoes/pagos_cyber"}, (),
        None,
    ),
    (
        "guard: extensão diferente de .sas7bdat",
        f"{GTAVARES}/base.csv", {"GTAVARES": GTAVARES}, (), None,
    ),
    (
        "guard: membro com macro não resolvida",
        f"{GTAVARES}/molicar_&SafraM2..sas7bdat", {"GTAVARES": GTAVARES}, (), None,
    ),
    (
        "guard: entidade XML não desescapada (&amp;) segue como arquivo",
        f"{GTAVARES}/&amp;arquivo..sas7bdat", {"GTAVARES": GTAVARES}, (), None,
    ),
    (
        "guard: libref excluído (WORK e afins) não vira tabela",
        f"{GTAVARES}/tmp_base.sas7bdat", {"WORK": GTAVARES}, (), None,
    ),
    (
        "guard: membro inválido (começa com dígito)",
        f"{GTAVARES}/2024_base.sas7bdat", {"GTAVARES": GTAVARES}, (), None,
    ),
    (
        "guard: caminho sem diretório (só basename) não resolve",
        "empilha_reneg_final_202406.sas7bdat", {"GTAVARES": GTAVARES}, (), None,
    ),
    (
        "guard: libname_dict vazio",
        f"{GTAVARES}/base.sas7bdat", {}, (), None,
    ),
]


def run():
    fails = 0
    for name, path, libmap, prefer, esperado in CASES:
        obtido = f(path, libmap, prefer)
        ok = obtido == esperado
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"        esperado: {esperado!r}")
            print(f"        obtido  : {obtido!r}")
            fails += 1
    print(f"\n{'TODOS PASSARAM' if fails == 0 else f'{fails} FALHA(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
