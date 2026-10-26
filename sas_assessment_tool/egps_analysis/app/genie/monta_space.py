"""Monta o serialized_space (version 2) do Genie. Só escreve arquivo; quem sobe é o update-space.

Fontes: instrucoes.md + o catálogo ../docs/divergencias-entre-telas.md (texto), exemplos.sql
(SQLs de exemplo; blocos P* têm parâmetros), conhecimento.py (colunas, joins, expressões,
parâmetros), benchmarks.sql. Os SQLs são escritos com o schema de PROD; `--schema` troca
para o alvo (ex.: monitoramento_sas_dev no space de pré-visualização).

Formato confirmado contra a API em 06/10/2026 (space temporário + get-space): version 2,
textos como lista de linhas, coleções com id ordenadas por id, column_configs por nome.

Uso: python3 monta_space.py [--schema monitoramento_sas_dev]
"""
import argparse
import json
import pathlib
import re
import unicodedata
import uuid

import conhecimento as K

AQUI = pathlib.Path(__file__).resolve().parent
CATALOGO = AQUI.parent / "docs" / "divergencias-entre-telas.md"
CATALOG = "bv_dev_db"
SCHEMA_FONTE = "monitoramento_sas"   # o schema que os arquivos usam

SUGERIDAS = [
    "Por que o funil de migração +deps tem um total diferente do funil do escopo?",
    "Por que a Gestão de inputs tem menos itens que o Total de Inputs do Resumo?",
    "Quais EGPs estão em Block, há quantos dias e por quê?",
    "O que mudou nos totais entre ontem e hoje?",
]


def hexid():
    return uuid.uuid4().hex


def linhas(texto):
    # o formato guarda texto como lista de linhas, cada uma terminando em \n
    return [l + "\n" for l in texto.rstrip("\n").split("\n")]


def alias(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def por_id(itens):
    return sorted(itens, key=lambda x: x["id"])


def coluna(nome, cfg):
    c = {"column_name": nome}
    if cfg.get("x"):
        c["exclude"] = True
        return c
    if cfg.get("d"):
        c["description"] = [cfg["d"]]
    if cfg.get("s"):
        c["synonyms"] = cfg["s"]
    if cfg.get("em"):
        c["enable_format_assistance"] = True
        c["enable_entity_matching"] = True
    return c


def snippet(nome, sql, sinonimos, instrucao, com_alias):
    s = {"id": hexid(), "sql": [sql], "display_name": nome}
    if com_alias:
        s["alias"] = alias(nome)
    if sinonimos:
        s["synonyms"] = sinonimos
    if instrucao:
        s["instruction"] = [instrucao]
    return s


def blocos(arquivo, padrao, troca):
    return re.split(padrao, troca((AQUI / arquivo).read_text(encoding="utf-8")), flags=re.M)


def monta(schema):
    fq = f"{CATALOG}.{schema}"

    def troca(txt):
        return txt.replace(f"{CATALOG}.{SCHEMA_FONTE}.", f"{fq}.")

    p = blocos("exemplos.sql", r"^-- ([A-Z]\d+) (.+)$", troca)
    exemplos = []
    for i in range(1, len(p), 3):
        bid, pergunta, sql = p[i], p[i + 1].strip(), p[i + 2].strip().rstrip(";").strip()
        ex = {"id": hexid(), "question": [pergunta], "sql": linhas(sql)}
        if bid in K.PARAMETROS:
            ex["parameters"] = [{"name": n, "type_hint": t, "description": [d], "default_value": {"values": [v]}}
                                for n, t, d, v in K.PARAMETROS[bid]]
        exemplos.append(ex)

    b = blocos("benchmarks.sql", r"^-- (B\d+) \| (?:escalar|conjunto) \| (.+)$", troca)
    bench = [{"id": hexid(), "question": [b[i + 1].strip()],
              "answer": [{"format": "SQL", "content": linhas(b[i + 2].strip().rstrip(";").strip())}]}
             for i in range(1, len(b), 3)]

    texto = ((AQUI / "instrucoes.md").read_text(encoding="utf-8").rstrip("\n")
             + "\n\n# CATÁLOGO DE DIVERGÊNCIAS ENTRE TELAS (fonte: docs/divergencias-entre-telas.md)\n\n"
             + CATALOGO.read_text(encoding="utf-8"))

    space = {
        "version": 2,
        "config": {"sample_questions": por_id([{"id": hexid(), "question": [q]} for q in SUGERIDAS])},
        "data_sources": {"tables": sorted([
            {"identifier": f"{fq}.{t}",
             "column_configs": sorted([coluna(n, c) for n, c in K.COLUNAS[t].items()], key=lambda c: c["column_name"])}
            for t in K.COLUNAS], key=lambda t: t["identifier"])},
        "instructions": {
            "text_instructions": [{"id": hexid(), "content": linhas(texto)}],
            "example_question_sqls": por_id(exemplos),
            "join_specs": por_id([{
                "id": hexid(),
                "left": {"identifier": f"{fq}.{e}", "alias": e},
                "right": {"identifier": f"{fq}.{d}", "alias": d},
                "sql": [cond, f"--rt=FROM_RELATIONSHIP_TYPE_{rel}--"]} for e, d, cond, rel in K.JOINS]),
            "sql_snippets": {
                "filters": por_id([snippet(*f, com_alias=False) for f in K.FILTROS]),
                "expressions": por_id([snippet(*c, com_alias=True) for c in K.CAMPOS]),
                "measures": por_id([snippet(*m, com_alias=True) for m in K.MEDIDAS]),
            },
        },
        "benchmarks": {"questions": por_id(bench)},
    }
    return space, len(exemplos), len(bench), len(texto)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=SCHEMA_FONTE)
    a = ap.parse_args()
    space, n_ex, n_b, n_txt = monta(a.schema)
    (AQUI / "serialized_space.json").write_text(json.dumps(space, ensure_ascii=False, indent=1), encoding="utf-8")
    json.dump({"serialized_space": json.dumps(space, ensure_ascii=False)},
              open(AQUI / "update_body.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"ok schema={a.schema}: {len(K.COLUNAS)} tabelas, {sum(len(c) for c in K.COLUNAS.values())} colunas, "
          f"{n_ex} exemplos, {len(K.JOINS)} joins, {len(K.FILTROS)}+{len(K.CAMPOS)}+{len(K.MEDIDAS)} expressões, "
          f"{n_b} benchmarks, {n_txt} chars de instrução")
