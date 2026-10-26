#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressão estrutural: quem lê resultado de statement tem de seguir `next_chunk_index`.

Com `disposition=INLINE` o PRIMEIRO chunk vem na resposta do statement e o resto só sai
pelo endpoint de chunk. Ler apenas `result.data_array` trunca EM SILÊNCIO: sem erro, sem
aviso, e o chamador processa um recorte achando que é o todo.

Este repo já pagou por isso duas vezes — e as duas correções ficaram presas na cópia onde
foram feitas, porque o laço de conectar-e-ler está duplicado em ~20 arquivos. Daí o
teste ser estrutural: varre os arquivos OPERACIONAIS e falha se algum voltar a ler
`data_array` sem seguir a cadeia.

Offline: só lê o fonte, não abre conexão nenhuma.

Uso: egps_analysis/venv/bin/python -m pytest test_chunks_sem_truncar.py -q
"""
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent

# Arquivos operacionais: rodam em produção ou decidem escrita em produção.
OPERACIONAIS = [
    "app/backend/main.py",
    "app/sync_dev.py",
    "publish_to_databricks.py",
    "publish_egps_atualizados.py",
    "pipeline_status_snapshot.py",
    "scripts/normaliza_responsavel_bv.py",
    "scripts/seed_responsaveis_bv.py",
    "scripts/migrate_input_status_split.py",
    "scripts/rename_migracao_etapas.py",
    "scripts/verifica_familias.py",
]

# FORA do gate de propósito: `docs/analises/` são scripts de uma vez só, rodados à mão
# por quem confere as contagens na hora. Alguns já seguem a cadeia, outros não; incluí-los
# aqui só produziria um gate vermelho que ninguém pode consertar sem reescrever scratch
# histórico. Se um deles for promovido a operacional, entra na lista acima junto.


@pytest.mark.parametrize("rel", OPERACIONAIS)
def test_le_todos_os_chunks(rel):
    p = RAIZ / rel
    if not p.exists():
        pytest.skip(f"{rel} não existe neste checkout")
    src = p.read_text(encoding="utf-8")
    if "data_array" not in src:
        return                      # não materializa resultado: nada a garantir
    assert "next_chunk_index" in src, (
        f"{rel} lê `data_array` mas não segue `next_chunk_index` — resultado maior que um "
        f"chunk é truncado em silêncio. Ver o laço em pipeline_status_snapshot.query.")
