"""
Migration hints: inventário EGP (06) × RepMap (réplica ASE→IQ) × Chameleon (ingestões no datalake).

Contexto
--------
- **06_prontidao_tabela.csv**: inventário extraído de projetos .egp (SAS Guide). ``category=table_in`` são
  referências a tabelas (libref.nome ou database.owner.tabela).
- **RepMap.xlsx**: catálogo operacional de **réplicação Sybase ASE → Sybase IQ** (e metadados de alvo/servidor).
  Uma linha descreve um fluxo de dados para uma tabela lógica em um par origem/destino.
- **chameleon.csv**: catálogo de tabelas **já ingeridas** no datalake (BigQuery). Colunas ``NmTabela*``,
  ``NmTabelaOrigem``, ``NmFonteDados`` identificam destino BQ e origem lógica.

Significado das colunas do RepMap (nomenclatura típica)
-------------------------------------------------------
- **Source**: identificador do **servidor ou instância de origem** no ecossistema de replicação (lado ASE / publicação).
- **DBsource**: **nome do database** no Sybase ASE de origem onde a tabela transacional existe.
- **Target**: **alvo da replicação** — servidor ou papel de destino (ex.: cluster IQ, nome de servidor de destino,
  ou identificador de camada ``warm`` / ``dbrep`` associado ao consumo no IQ).
- **DBtarget**: **database no destino** (normalmente o mesmo nome lógico do database no IQ ou espelho do ASE).
- **Tipo**: modalidade de réplica / consumo (ex.: ``dbrep`` replicação clássica para IQ, ``warm`` camada quente).
- **Carga**: perfil de carga (ex.: **NRT** near-real-time vs batch), conforme operação de replicação.
- **Tabela**: nome **lógico** da tabela no mapeamento de replicação (lado fonte alinhado ao ASE).
- **TabRep**: nome da tabela **no destino** da réplica (IQ); em muitos casos igual a **Tabela**.
- **RepDef**: nome da **definição de replicação** (artefato de produto de replicação Sybase).
- **SubName**: nome da **subscrição** associada à definição (conjunto de artigos / fila lógica).

Este script filtra ``table_in``, exclui ``source_type`` BIGQUERY / BIGQUERY/GCP (já “modernizados” no EGP),
cruza cada **artifact** com RepMap (réplica declarada) e com Chameleon (somente fontes **SYBASE_ASE** /
**SYBASE_IQ** e variantes de capitalização). O caso de interesse principal é:

  **Referência direta a ASE no SAS, sem linha equivalente no RepMap, mas com ingestão Sybase já no Chameleon**
  → o dado equivalente pode existir no datalake; revisar libname / SQL para apontar para BigQuery.

Uso::
  python migration_hints_table_in_repmap_chameleon.py [06.csv] [RepMap.xlsx] [chameleon.csv] [out.csv]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from collections import defaultdict

from validate_table_in_vs_repmap import (
    _sybase_collapsed_db_table_pairs,
    load_repmap_rows,
    match_artifact,
    norm,
    norm_upper,
    repmap_derived_keys,
)


def sim_nao(flag: bool) -> str:
    return "Sim" if flag else "Não"


# Níveis internos de match_artifact → rótulo em português (valores da coluna repmap_match_level)
_REPMAP_NIVEL_PT: dict[str, str] = {
    "SKIP": "Ignorado — não é token de tabela qualificado",
    "EXACT_KEY": "Correspondência exata por chave derivada do RepMap",
    "SCHEMA_TABLE": "Correspondência esquema.tabela (DBsource/Fonte/DBtarget/TabRep + Tabela)",
    "SCHEMA_TABLE_MULTIPLE": "Múltiplas linhas RepMap para o mesmo esquema.tabela",
    "SYBASE_OWNER_COLLAPSED": "Correspondência após ignorar owner intermediário (ex.: DBO)",
    "SYBASE_OWNER_COLLAPSED_MULTIPLE": "Múltiplas linhas RepMap após colapsar owner (ex.: DBO)",
    "TABLE_ONLY_UNIQUE": "Somente nome de tabela — ocorrência única no RepMap",
    "TABLE_ONLY_MULTIPLE": "Somente nome de tabela — várias linhas no RepMap com o mesmo nome",
    "THREE_PART": "Heurística projeto.conjunto.tabela (3 partes)",
    "THREE_PART_MULTIPLE": "Heurística 3 partes — múltiplas linhas no RepMap",
    "NOT_FOUND": "Não encontrado no RepMap",
}


def repmap_nivel_pt(lvl: str) -> str:
    return _REPMAP_NIVEL_PT.get(lvl, lvl)


def format_replica_primary_pt(r: dict[str, Any]) -> str:
    return (
        f"BD_origem={r['DBsource']} → BD_destino={r['DBtarget']} | Tabela={r['Tabela']} | "
        f"Alvo={r['Target']} | Tabela_réplica={r['TabRep']} | Tipo={r['Tipo']} | "
        f"Def_réplica={r['RepDef']} | Linha_planilha={r['_rownum']}"
    )


def format_chameleon_row_pt(r: dict[str, str]) -> str:
    return (
        f"NmTabela_BQ={r['NmTabela']}|Origem={r['NmTabelaOrigem']}|"
        f"Fonte_dados={r['NmFonteDados']}|Fim_ingestão={r['DtFimIngestao']}"
    )


def chave_cruzamento_pt(used_key: str) -> str:
    if used_key.startswith("*."):
        return f"qualquer_base.{used_key[2:]}"
    return used_key


def is_excluded_bigquery_source_type(st: str) -> bool:
    u = norm_upper(st).replace(" ", "")
    return u in ("BIGQUERY", "BIGQUERY/GCP")


def is_sybase_chameleon_fonte(nm_fonte: str) -> bool:
    u = norm_upper(nm_fonte).replace(" ", "_")
    return u in ("SYBASE_ASE", "SYBASE_IQ") or u.startswith("SYBASE_")


def _clean_chameleon_origem(origem: str) -> str:
    s = norm(origem)
    if not s:
        return ""
    if "(" in s:
        s = s[: s.index("(")].strip()
    return s.replace("[", "").replace("]", "")


def chameleon_db_table_keys_from_origem(origem: str) -> set[tuple[str, str]]:
    """
    Extrai pares (DATABASE, TABELA) upper a partir de NmTabelaOrigem.
    - ASE: db.dbo.table → (DB, TABLE)
    - IQ / 3 partes sem dbo no meio: host.db.table → (DB, TABLE) usando os dois últimos segmentos.
    """
    s = _clean_chameleon_origem(origem)
    if not s:
        return set()
    parts = [p.strip() for p in s.split(".") if p.strip()]
    if not parts:
        return set()
    parts_u = [norm_upper(p) for p in parts]
    keys: set[tuple[str, str]] = set()
    from validate_table_in_vs_repmap import _SQL_OWNER_SKIP

    if len(parts_u) >= 3 and parts_u[1] in _SQL_OWNER_SKIP:
        keys.add((parts_u[0], ".".join(parts_u[2:])))
    elif len(parts_u) >= 3:
        keys.add((parts_u[-2], parts_u[-1]))
    elif len(parts_u) == 2:
        keys.add((parts_u[0], parts_u[1]))
    return {(a, b) for a, b in keys if a and b}


def key_from_nm_tabela_bq(nm_tabela: str) -> tuple[str, str] | None:
    """trusted_<db>.<table> no NmTabela → par (DB_GUESS, TABLE) para cruzamento fraco."""
    parts = [p for p in norm(nm_tabela).split(".") if p]
    if len(parts) < 3:
        return None
    ds = norm_upper(parts[-2])
    tb = norm_upper(parts[-1])
    if ds.startswith("TRUSTED_"):
        return (ds[len("TRUSTED_") :], tb)
    return None


def artifact_db_table_candidates(artifact: str) -> list[tuple[str, str]]:
    """Pares (db, table) upper derivados do token SAS / SQL (inclui colapso DBO)."""
    a = norm(artifact)
    if not a or a.startswith("/"):
        return []
    parts = [p for p in a.split(".") if p]
    if not parts:
        return []
    parts_u = [norm_upper(p) for p in parts]
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(db: str, tbl: str) -> None:
        if not tbl:
            return
        t = (norm_upper(db), norm_upper(tbl))
        if t not in seen:
            seen.add(t)
            out.append(t)

    if len(parts_u) == 2:
        add(parts_u[0], parts_u[1])
    for db, tb in _sybase_collapsed_db_table_pairs(parts_u):
        add(db, tb)
    if len(parts_u) == 1:
        add("", parts_u[0])
    return out


def load_chameleon_sybase_index(
    chameleon_path: Path,
) -> tuple[dict[tuple[str, str], list[dict[str, str]]], dict[str, list[dict[str, str]]], int]:
    """Índice (DB, TABELA) upper e índice por nome de tabela (último segmento) para artefactos de 1 parte."""
    idx: dict[tuple[str, str], list[dict[str, str]]] = {}
    by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    total_sybase = 0
    with open(chameleon_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not is_sybase_chameleon_fonte(row.get("NmFonteDados", "")):
                continue
            total_sybase += 1
            keys: set[tuple[str, str]] = set()
            keys |= chameleon_db_table_keys_from_origem(row.get("NmTabelaOrigem", ""))
            kt = key_from_nm_tabela_bq(row.get("NmTabela", ""))
            if kt and kt[0] and kt[1]:
                keys.add(kt)
            rec = {
                "NmTabela": norm(row.get("NmTabela", "")),
                "NmTabelaOrigem": norm(row.get("NmTabelaOrigem", "")),
                "NmFonteDados": norm(row.get("NmFonteDados", "")),
                "DtFimIngestao": norm(row.get("DtFimIngestao", "")),
            }
            for k in keys:
                idx.setdefault(k, []).append(rec)
                by_table[k[1]].append(rec)
    return idx, by_table, total_sybase


def repmap_source_db_table_pairs(rep_hits: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Pares (DBsource, tabela) upper das linhas RepMap já casadas com o artefato.

    O índice do Chameleon é chaveado pela **base de origem** Sybase ASE (ex.: ``DBCRED``,
    de ``dbcred.dbo.tbproposta`` / ``trusted_dbcred``). Quando o SAS referencia a tabela
    pelo **alias do destino de réplica no IQ** (ex.: libref ``DBA``), o artefato nunca casa
    diretamente. O RepMap é a única ponte (``DBsource=DBCRED → DBtarget=DBA``): usamos a
    base de origem das linhas casadas para sondar o Chameleon. Inclui ``Tabela`` e ``TabRep``.
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for r in rep_hits:
        dbs = norm_upper(r.get("DBsource", ""))
        if not dbs:
            continue
        for tb in (norm_upper(r.get("Tabela", "")), norm_upper(r.get("TabRep", ""))):
            if tb and (dbs, tb) not in seen:
                seen.add((dbs, tb))
                out.append((dbs, tb))
    return out


def lookup_chameleon(
    artifact: str,
    idx: dict[tuple[str, str], list[dict[str, str]]],
    by_table: dict[str, list[dict[str, str]]],
    extra_candidates: list[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Retorna hits e chave usada (primeira que encontrou).

    ``extra_candidates`` são pares (db, tabela) adicionais (tipicamente a base de origem
    resolvida via RepMap por :func:`repmap_source_db_table_pairs`); são sondados após os
    candidatos derivados do próprio token e marcam a chave usada como ``(via RepMap)``.
    """
    cands: list[tuple[str, str, str]] = [(db, tbl, "art") for db, tbl in artifact_db_table_candidates(artifact)]
    if extra_candidates:
        seen_c = {(db, tbl) for db, tbl, _ in cands}
        for db, tbl in extra_candidates:
            if db and (db, tbl) not in seen_c:
                seen_c.add((db, tbl))
                cands.append((db, tbl, "repmap"))
    hits: list[dict[str, str]] = []
    used_key = ""
    seen_row: set[tuple[str, str, str]] = set()
    for db, tbl, origin in cands:
        if not tbl:
            continue
        if db:
            key = (db, tbl)
            rows = idx.get(key, [])
            if not used_key and rows:
                used_key = f"{db}.{tbl}" + (" (via RepMap)" if origin == "repmap" else "")
            for row in rows:
                sig = (row["NmTabela"], row["NmTabelaOrigem"], row["NmFonteDados"])
                if sig not in seen_row:
                    seen_row.add(sig)
                    hits.append(row)
        else:
            for row in by_table.get(tbl, []):
                sig = (row["NmTabela"], row["NmTabelaOrigem"], row["NmFonteDados"])
                if sig not in seen_row:
                    seen_row.add(sig)
                    hits.append(row)
                    if not used_key:
                        used_key = f"*.{tbl}"
    return hits, used_key


def padrao_migracao_pt(repmap_yes: bool, chameleon_yes: bool, repmap_level: str) -> str:
    if repmap_level == "SKIP":
        return "Ignorar: caminho ou token que não representa tabela qualificada"
    if repmap_yes and chameleon_yes:
        return "Alinhado: há réplica no RepMap e ingestão Sybase no Chameleon"
    if repmap_yes and not chameleon_yes:
        return "Só RepMap: réplica mapeada, sem linha Sybase correspondente no Chameleon"
    if not repmap_yes and chameleon_yes:
        return "Chameleon (Sybase) sem correspondência no RepMap — avaliar uso no datalake (BQ)"
    return "Lacuna: sem correspondência no RepMap e sem ingestão Sybase no Chameleon"


def main() -> None:
    root = Path(__file__).resolve().parent
    csv_06 = root / "06_prontidao_tabela.csv"
    xlsx_rep = root / "src" / "RepMap.xlsx"
    csv_ch = root / "src" / "chameleon.csv"
    out_csv = root / "06_migration_hints_table_in.csv"

    if len(sys.argv) >= 2:
        csv_06 = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        xlsx_rep = Path(sys.argv[2])
    if len(sys.argv) >= 4:
        csv_ch = Path(sys.argv[3])
    if len(sys.argv) >= 5:
        out_csv = Path(sys.argv[4])

    rep_rows = load_repmap_rows(xlsx_rep)
    full_key_index: dict[str, list[dict[str, Any]]] = {}
    for r in rep_rows:
        for k in repmap_derived_keys(r):
            full_key_index.setdefault(k, []).append(r)

    ch_idx, ch_by_table, ch_sybase_rows = load_chameleon_sybase_index(csv_ch)

    with open(csv_06, newline="", encoding="utf-8-sig") as f:
        prontidao = list(csv.DictReader(f))

    scope = [
        row
        for row in prontidao
        if norm(row.get("category", "")).lower() == "table_in"
        and not is_excluded_bigquery_source_type(row.get("source_type", ""))
    ]

    fieldnames = [
        "project",
        "file_sas",
        "area",
        "artifact",
        "path",
        "source_type",
        "status_validacao",
        "repmap_replica_found",
        "repmap_match_level",
        "repmap_hit_count",
        "repmap_primary",
        "chameleon_sybase_found",
        "chameleon_hit_count",
        "chameleon_match_key",
        "chameleon_primary_NmTabela",
        "chameleon_primary_NmTabelaOrigem",
        "chameleon_primary_NmFonteDados",
        "chameleon_primary_DtFimIngestao",
        "migration_pattern",
        "attention_use_chameleon_bq_not_repmap",
        "chameleon_matches_short",
    ]

    attention_count = 0
    with open(out_csv, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=fieldnames)
        w.writeheader()
        for row in scope:
            art = norm(row.get("artifact", ""))
            lvl, _desc, rep_hits = match_artifact(art, rep_rows, full_key_index)
            repmap_yes = bool(rep_hits) and lvl not in ("SKIP",)
            # Ponte RepMap → Chameleon: se há réplica casada, sonda também a base de origem
            # (DBsource), pois o Chameleon é chaveado pela origem ASE, não pelo alias/destino IQ.
            extra_cands = repmap_source_db_table_pairs(rep_hits) if repmap_yes else None
            ch_hits, ch_key = lookup_chameleon(art, ch_idx, ch_by_table, extra_candidates=extra_cands)
            ch_yes = bool(ch_hits)
            pattern_pt = padrao_migracao_pt(repmap_yes, ch_yes, lvl)
            attention_flag = not repmap_yes and ch_yes and lvl != "SKIP"
            attention = sim_nao(attention_flag)
            if attention_flag:
                attention_count += 1

            rep_primary = format_replica_primary_pt(rep_hits[0]) if rep_hits else ""
            ch0 = ch_hits[0] if ch_hits else {}
            ch_short = " || ".join(format_chameleon_row_pt(h) for h in ch_hits[:5])
            if len(ch_hits) > 5:
                ch_short += f" || ... (mais {len(ch_hits) - 5})"

            w.writerow(
                {
                    "project": row.get("project", ""),
                    "file_sas": row.get("file_sas", ""),
                    "area": row.get("area", ""),
                    "artifact": art,
                    "path": row.get("path", ""),
                    "source_type": row.get("source_type", ""),
                    "status_validacao": row.get("status_validacao", ""),
                    "repmap_replica_found": sim_nao(repmap_yes),
                    "repmap_match_level": repmap_nivel_pt(lvl),
                    "repmap_hit_count": len(rep_hits),
                    "repmap_primary": rep_primary,
                    "chameleon_sybase_found": sim_nao(ch_yes),
                    "chameleon_hit_count": len(ch_hits),
                    "chameleon_match_key": chave_cruzamento_pt(ch_key),
                    "chameleon_primary_NmTabela": ch0.get("NmTabela", ""),
                    "chameleon_primary_NmTabelaOrigem": ch0.get("NmTabelaOrigem", ""),
                    "chameleon_primary_NmFonteDados": ch0.get("NmFonteDados", ""),
                    "chameleon_primary_DtFimIngestao": ch0.get("DtFimIngestao", ""),
                    "migration_pattern": pattern_pt,
                    "attention_use_chameleon_bq_not_repmap": attention,
                    "chameleon_matches_short": ch_short,
                }
            )

    print(
        f"Gravado: {out_csv} — {len(scope)} linhas table_in (excl. source_type BIGQUERY/GCP); "
        f"linhas Sybase indexadas no Chameleon: {ch_sybase_rows}; "
        f"atenção usar Chameleon/BQ sem RepMap (Sim): {attention_count}"
    )


if __name__ == "__main__":
    main()
