# -*- coding: utf-8 -*-
"""Lê uma tabela do Databricks INTEIRA com a credencial da sincronização.

Com disposition=INLINE só o primeiro chunk vem na resposta; ler apenas `result.data_array`
truncava em silêncio tudo que não coubesse num chunk (já mordeu este repo duas vezes).
Por isso segue `next_chunk_index` até o fim E confere o total do manifesto.
"""
import time

from databricks.sdk.service.sql import Disposition, Format, StatementState


def le_tabela(w, warehouse_id, fq_tabela, colunas, expressoes=None):
    """`expressoes`: o que vai no SELECT, uma por coluna (ex.: CAST(ts AS STRING) AS ts);
    sem elas, as próprias colunas."""
    sql = f"SELECT {', '.join(expressoes or colunas)} FROM {fq_tabela}"
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if (r.status and r.status.error) else "erro desconhecido"
        raise RuntimeError(f"leitura de {fq_tabela} falhou: {msg}")
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = getattr(chunk, "next_chunk_index", None)
        if nxt is None:
            break
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
    total = getattr(getattr(r, "manifest", None), "total_row_count", None)
    if total is not None and int(total) != len(linhas):
        raise RuntimeError(f"{fq_tabela}: li {len(linhas)} de {total} linhas (truncamento)")
    return [dict(zip(colunas, linha)) for linha in linhas]
