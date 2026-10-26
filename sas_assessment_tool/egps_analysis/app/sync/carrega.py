# -*- coding: utf-8 -*-
"""Grava um retrato completo no Postgres numa transação só (ADR 0005, Fase 1).

Quem lê o app vê o retrato anterior até o COMMIT. Na Fase 1 o Databricks é a fonte da
verdade de TUDO (inclusive do estado humano), então as tabelas sincronizadas são apagadas e
recarregadas; as FKs ficam adiadas até o COMMIT para a ordem não importar. As exceções são
`cadastro.usuario` (os papéis moram só no Postgres: a sincronização só acrescenta pessoas,
inativas, e atualiza nome/cargo) e `historico.publicacao` (só recebe linha).
"""
import datetime
import json

from . import espelho, mapeamento as mp

# Apaga filhos antes dos pais; insere pais antes dos filhos.
SINCRONIZADAS = ("trabalho.estado_input", "corpus.egp_input", "trabalho.escopo_item",
                 "corpus.input", "corpus.egp")


def _copia(cur, tabela, linhas):
    cols = mp.COLUNAS[tabela]
    with cur.copy(f"COPY {tabela} ({', '.join(cols)}) FROM STDIN") as cp:
        for linha in linhas:
            cp.write_row(linha)


def carrega(conn, retrato, versao_codigo=None, agora=None):
    """`retrato`: dict destino -> lista de tuplas (âncoras já completas) + 'usuarios'
    (lista de (email, nome, cargo, organograma)) + 'pessoas_referenciadas' (e-mails).
    Devolve o resumo gravado em historico.publicacao."""
    agora = agora or datetime.datetime.now(datetime.timezone.utc)
    resumo = {t: len(retrato.get(t, [])) for t in SINCRONIZADAS}
    with conn.transaction():
        conn.execute("SELECT set_config('app.usuario', 'sincronizacao', true)")
        conn.execute("SET CONSTRAINTS ALL DEFERRED")
        with conn.cursor() as cur:
            for t in SINCRONIZADAS:
                cur.execute(f"DELETE FROM {t}")
            for email, nome, cargo, organograma in retrato.get("usuarios", []):
                cur.execute(
                    "INSERT INTO cadastro.usuario (email, nome, cargo, organograma, ativo) "
                    "VALUES (%s, %s, %s, %s, false) ON CONFLICT (email) DO UPDATE SET "
                    "nome = EXCLUDED.nome, cargo = EXCLUDED.cargo, organograma = EXCLUDED.organograma",
                    (email, nome, cargo, organograma))
            for email in sorted(set(retrato.get("pessoas_referenciadas", []))):
                cur.execute("INSERT INTO cadastro.usuario (email, nome, ativo) VALUES (%s, %s, false) "
                            "ON CONFLICT (email) DO NOTHING", (email, email))
            for t in reversed(SINCRONIZADAS):
                _copia(cur, t, retrato.get(t, []))
            resumo["espelho"] = espelho.carrega(cur, retrato.get("espelho", {}))
            cur.execute("SELECT count(*) FROM derivado.v_trabalho_orfao")
            resumo["trabalho_orfao"] = cur.fetchone()[0]
            resumo["ancoras_acrescentadas"] = retrato.get("ancoras_acrescentadas", {})
            cur.execute(
                "INSERT INTO historico.publicacao (origem, iniciada_em, concluida_em, ok, versao_codigo, resumo) "
                "VALUES ('sync_databricks', %s, now(), true, %s, %s::jsonb)",
                (agora, versao_codigo, json.dumps(resumo)))
    return resumo
