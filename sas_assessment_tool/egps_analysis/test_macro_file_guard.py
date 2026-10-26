#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressão: `file_in` com referência de macro NÃO resolvida não é arquivo — é um padrão
parametrizado que o extrator não conseguiu expandir (`&arquivo..sas7bdat`,
`ESTOQUE_&DSRefModel.sas7bdat`, `BA_ACORDO_&SAFRA..csv`). Entrava no monitor como input
pendente e enchia a fila de ingestão com trabalho inexistente.

`is_noise_table()` já descarta o equivalente em TABELAS (guard `'&' in a`), mas nunca
rodou para `file_in` — daí 181 pseudo-inputs `arquivo` em prod, um deles
(`&arquivo..sas7bdat`) vivo, no escopo e lido por 5 EGPs.

Os nomes chegam com a entidade XML escapada (`&amp;`) porque
`egps_extractor.sas_metadata_path_display()` re-escapa `&` de propósito, para alinhar a
linha de metadados ao modo como SAS/EG renderiza caminhos. O guard cobre as duas formas.

Nome de macro com >=2 caracteres: um `P&C` literal no nome do arquivo (citado no docstring
do extractor) não deve ser confundido com macro. Medição no corpus em prod (2026-08-27):
181/181 dos casos reais têm nome >=2 chars, 0 casariam só com 1 char.

Uso: egps_analysis/venv/bin/python test_macro_file_guard.py
"""
import publish_to_databricks as pub

CASES = [
    # (nome, artefato, esperado_e_macro)
    ("macro nua com ponto terminador", "&arquivo..sas7bdat", True),
    ("entidade XML nao desescapada", "&amp;arquivo..sas7bdat", True),
    ("macro no meio do nome", "ESTOQUE_&DSRefModel.sas7bdat", True),
    ("macro no meio, escapada", "BASE_CONTABILIDADE_&amp;DSRefModel.sas7bdat", True),
    ("duas macros no mesmo nome", "hist_anal_cart_&anomes_ini._&anomes_fim..sas7bdat", True),
    ("macro em csv", "BA_ACORDO_&SAFRA..csv", True),
    ("macro em xlsx", "DXC_CARTAO3040_&amp;mes.&amp;ano..xlsx", True),
    ("so o nome da macro", "&amp;Diretorio.", True),
    ("macro sem ponto terminador", "&amp;base_robbu", True),
    ("macro de macro (&&file&i)", "&amp;&amp;file&amp;i", True),
    ("nome curto de 2 chars (&a0)", "tboriginacao&amp;a0..sas7bdat", True),
    # ---- não são macro: o input segue no inventário ----
    ("arquivo comum", "empilha_reneg_final_202406.sas7bdat", False),
    ("csv comum", "desconto_cobranca_RODAS.csv", False),
    ("caminho com diretorio", "/riscosbv/cobranca/gtavares/base.sas7bdat", False),
    ("'&' seguido de digito nao e nome SAS", "TABELA_&2024.csv", False),
    ("'&' isolado no fim", "RELATORIO_2026&", False),
    ("vazio", "", False),
    ("None", None, False),
    # ---- exceção: '&' LITERAL entre duas letras isoladas (abreviação) ----
    # Caso REAL do corpus, com status humano 'Concluído': Profit & Loss.
    ("P&L literal (escapado) nao e macro", "P&amp;L_Cartoes_Real.v2.xlsx[SHEET='Ajustes']", False),
    ("P&C literal nao e macro", "RELATORIO_P&C_2026.xlsx", False),
    ("abreviacao no inicio do nome", "P&amp;L.xlsx", False),
    # a exceção é cirúrgica: não pode blindar um nome que TAMBÉM tem macro de verdade
    ("literal + macro no mesmo nome ainda e macro", "P&amp;L_Base_&amp;anomes..xlsx", True),
    # e não pode isentar macro curta legítima, onde o lado esquerdo não é letra isolada
    ("macro curta apos palavra (&a0) segue macro", "tboriginacao&amp;a0..sas7bdat", True),
]


def run():
    fails = 0
    for nome, art, esperado in CASES:
        obtido = pub.is_macro_artifact(art)
        ok = bool(obtido) == esperado
        print(f"[{'PASS' if ok else 'FAIL'}] {nome}")
        if not ok:
            print(f"        artefato: {art!r}  esperado={esperado}  obtido={obtido}")
            fails += 1
    print(f"\n{'TODOS PASSARAM' if fails == 0 else f'{fails} FALHA(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
