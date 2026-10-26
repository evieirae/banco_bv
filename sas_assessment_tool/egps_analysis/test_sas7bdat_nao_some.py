#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressão: `.sas7bdat` sob LIBNAME nunca pode SUMIR do inventário.

Quando a leitura de `.sas7bdat` passou a preferir `table_in` (ver
test_sas7bdat_como_tabela.py), o laço de `files_read` deixou de acrescentar o `file_in` e
passou a delegar para `_append_supplemental_table_in`. Só que esse append RECUSA tokens
"com cara de arquivo" — e `_exclude_from_table_in_metadata_token` casa a extensão no FIM
do nome, exatamente a forma de `LIB.MEMBRO`. Um membro chamado CSV, TXT, ZIP, SAS, XML…
(`/dados/reneg/CSV.sas7bdat` -> `RENEG.CSV`) era recusado e o input desaparecia dos
relatórios 01-06 sem mensagem nenhuma — antes do desvio ele ao menos entrava como
'arquivo'.

Offline: só helpers e leitura do fonte, nenhuma conexão.
"""
import pathlib
import re

import pytest

import orchestrator_inventory as O

LIBS = {"RENEG": "/dados/reneg"}

# Membros que colidem com a lista de extensões de _FILEISH_EXT_RE.
MEMBROS_COM_CARA_DE_ARQUIVO = ["CSV", "TXT", "ZIP", "SAS", "XML", "JSON", "ORC", "HTM"]


@pytest.mark.parametrize("membro", MEMBROS_COM_CARA_DE_ARQUIVO)
def test_a_colisao_existe_mesmo(membro):
    """Documenta a armadilha: os dois helpers DISCORDAM para esses membros.

    Se um dia `_exclude_from_table_in_metadata_token` passar a aceitar `LIB.CSV`, este
    teste fica vermelho — e aí o fallback abaixo pode ser revisto conscientemente, em vez
    de alguém achar que ele nunca serviu para nada."""
    tn = O._sas7bdat_as_libname_table(f"/dados/reneg/{membro}.sas7bdat", LIBS)
    assert tn == f"RENEG.{membro}", "a resolução para lib.membro deixou de funcionar"
    assert O._exclude_from_table_in_metadata_token(tn) is True


@pytest.mark.parametrize("membro", ["CLIENTES", "BASE_202501", "EMPILHA_RENEG_FINAL"])
def test_membro_normal_segue_virando_tabela(membro):
    tn = O._sas7bdat_as_libname_table(f"/dados/reneg/{membro}.sas7bdat", LIBS)
    assert tn == f"RENEG.{membro}"
    assert O._exclude_from_table_in_metadata_token(tn) is False


def test_o_append_devolve_recusa_em_vez_de_engolir():
    """`_append_supplemental_table_in` precisa SINALIZAR a recusa (retornar False), senão
    o chamador não tem como saber que precisa do fallback."""
    src = pathlib.Path(O.__file__).read_text(encoding="utf-8")
    corpo = src.split("def _append_supplemental_table_in", 1)[1].split("\n            for ", 1)[0]
    assert "return False" in corpo, (
        "o append voltou a engolir a recusa em silêncio — sem o retorno, o flush dos "
        ".sas7bdat não consegue cair de volta para file_in")


def test_flush_dos_sas7bdat_tem_fallback_para_file_in():
    """O laço de flush tem de acrescentar `file_in` quando o table_in é recusado.

    Estrutural de propósito: o laço vive dentro da função monolítica que varre os
    projetos, sem ponto de entrada para exercitá-lo com dado sintético. O que dá para
    garantir aqui é que o fallback não seja removido por descuido."""
    src = pathlib.Path(O.__file__).read_text(encoding="utf-8")
    flush = src.split("for _p in sas7bdat_sob_libname:", 1)[1][:1200]
    assert re.search(r"if not \(_tn and _append_supplemental_table_in\(", flush), \
        "o flush voltou a chamar o append sem checar a recusa"
    assert "'file_in'" in flush, \
        "o flush perdeu o fallback para file_in — .sas7bdat recusado some do inventário"
