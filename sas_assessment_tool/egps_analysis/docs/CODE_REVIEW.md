# Code Review — `egps_analysis/`

> Reviewer: Claude (Opus 4.8) · Scope: full module · Goal assessed: *extract `.egp` (SAS) I/O so we know EGP-to-EGP dependencies, inputs, and outputs to migrate to BigQuery/Databricks via dbt.*
> Scale: **118 `.egp` files across 7 business areas** (Cobranças 55, Riscos 28, Atacado 21, Jurídico 8, Finanças 4, Banco Relacional 1, Operações 1).

---

## 1. Verdict (TL;DR)

The pipeline **works and the architecture is fundamentally sound**: a per-EGP extractor emits structured I/O inventories, an orchestrator joins them into a cross-EGP dependency graph + migration waves, and two downstream scripts cross-reference RepMap/Chameleon for migration hints. The split between "extract per file" and "join across files" is the *right* design.

But there are **three issues that directly undermine the stated goal**, plus a layer of accumulated cruft:

| Severity | Issue | Impact on goal |
|----------|-------|----------------|
| 🔴 **P0** | The cross-EGP dependency join (report 03/04) uses **raw exact string equality** on table names, with **none** of the normalization the extractor and report 06 apply elsewhere. | At 118 EGPs, dependencies will be **silently under-linked**. `LIB.TBL` ≠ `lib.tbl` ≠ `` `LIB`.TBL ``. Migration waves built on a graph with missing edges are unreliable. |
| 🟠 **P1** | `egps_extractor.py` is **4,031 lines** with two ~850/300-line orchestrators sharing ~150–200 lines of near-verbatim duplication, up to 10 levels of nesting, hand-rolled argv parsing. | Unmaintainable; the highest-value refactor target. |
| 🟠 **P1** | `orchestrator_inventory.py` `main()` is a **368-line god function** (200 lines of which is the report-06 block) parsing a brittle `.txt` header format by exact long-string prefixes. | Wording drift in the extractor silently drops fields; comma-in-value corrupts list parsing. |
| 🟡 **P2** | Dead code (`OUTPUT_REPORT_7`), an orphan script (`bq_connect.py`), EN-vs-pt-BR label divergence between the two RepMap reports, position-based `.xlsx` parsing. | Maintenance traps and confusion, not correctness-critical. |

---

## 2. The central finding: dependency detection is real but fragile

This is the most important thing to understand about the codebase, because it's the whole point of the module.

**Dependency detection does NOT live in the extractor.** `egps_extractor.py` processes each file in complete isolation — no global state, no second pass, no cross-file linking. The only intra-file "dependency" it computes is `SAME-SCRIPT RE-READS` (a table the *same* script wrote and re-read), which is the *opposite* of a cross-EGP dependency. So the extractor's job is purely: emit per-EGP `PERMANENT OUTPUTS` and `EXTERNAL INPUTS`.

**The graph is built in the orchestrator** (`orchestrator_inventory.py`, lines ~644–725):

```text
table_to_generator[output_table] = project      # last writer wins (silent overwrite on collision)
table_to_consumers[input_table].append(project)
# edge: for each project input, if table_to_generator.get(input_table) exists and != self → A depends on B
```

It then runs a genuine **Kahn topological sort** for migration waves (report 04) with correct **cycle detection** (`ERRO: Dependência Cíclica`). That part is correct and idiomatic.

**The problem is the join key.** The edge is created by `table_to_generator.get(inp_table)` — a dict keyed by the *raw* output string, matched byte-for-byte against the *raw* input string. At this exact join point there is **no** `.upper()`, no quote/backtick stripping, no `lib.member` canonicalization — even though:
- the extractor normalizes tables internally, and
- report 06 (in the *same file*) carefully cleans artifacts (`clean_artifact`, `.upper()`, quote-strip — a block copy-pasted ~6 times).

So the careful normalization exists twice but is **not applied to the one join that produces the dependency graph.** Across 118 EGPs written by different authors over years, table references will differ in case, quoting, and libref — and those edges will simply be missing. The waves report will look clean and be wrong.

**This is the single highest-value fix in the module** and it's small: extract one `canonical_table_key()` function and apply it on *both* sides when building `table_to_generator` / `table_to_consumers`. Also replace "last writer wins" with collision tracking (two EGPs writing the same table name is itself a migration signal worth a report).

---

## 3. Per-script findings

### `egps_extractor.py` — 4,031 lines, ~119 functions, 0 classes 🟠

- **Two oversized orchestrators**: `extract_code_from_egp` (lines 2804–3659, ~855 lines) and `extract_code_from_sas` (3666–3966, ~300 lines) = ~28% of the file. The metadata-header construction block and the full header literal are **near-verbatim duplicated** between them (e.g. lines 3520–3556 ≈ 3762–3798; header lists 3580–3654 ≈ 3889–3957) — ~150–200 lines that exist twice.
- **Deep nesting**: up to 10 levels (40-space indent) at line 2901; 314 lines inside `extract_code_from_egp` are indented ≥6 levels.
- **No argparse**: CLI is hand-parsed from `sys.argv` (3970–3974); the `--eg-style`/`--clean` flags are parsed but **documented as no-ops** — dead flags.
- **Broad `except Exception`** wrapping each orchestrator's whole body (≈3958) with `traceback.print_exc()` — swallows all per-file errors.
- **Versioning smell is documentary, not structural**: module brands itself `egps_extractor_v1`, with stale `V6:`/`V8:` annotations in docstrings. No live version branches. `EGPS_EXTRACTOR_V9.md` is a legacy note. Recommend deleting the v-annotations and the v9 doc, or folding into a CHANGELOG.
- **Highest-value refactors**: (1) extract a shared `build_metadata_header(...)` + `enriched_external_inputs()` used by both orchestrators; (2) break the XML-traversal section into named helpers; (3) switch to argparse.

### `orchestrator_inventory.py` — 1,013 lines 🟠

- **`main()` is ~368 lines** (613–981); the report-06 block alone is ~180 lines (781–960) with closures (`clean_artifact`, `get_basename`) defined *inside* the loop.
- **`parse_txt_metadata` is ~188 lines** (278–465) — one `if/elif` chain of ~22 exact-prefix `startswith` branches. **Fragile**: any wording drift in the extractor header silently drops a field; list fields split on `,` with no escaping, so a comma inside a table/path name corrupts the list. This is a tightly-coupled text contract between two scripts with no schema.
- **Dead code**: `OUTPUT_REPORT_7 = '07_validacao_chameleon.csv'` (line 48) is never written — only referenced in an argparse help string.
- **Silent failures**: both loaders end in `except Exception as e: pass` (539, 596) — empty results, no diagnostic.
- **`is_strict_match` (602–611) has a substring bug**: `prefix in cham_val` matches unrelated rows (e.g. prefix `"DW"` matches anything containing `"DW"`) — false-positive Chameleon matches in report 06.
- **Good parts**: the Kahn topo-sort (waves), cycle detection, and the auto-detecting CSV loaders (sniff delimiter, detect origem/destino columns, try 5 encodings).

### `validate_table_in_vs_repmap.py` (317 lines) + `migration_hints_...py` (376 lines) 🟡

- **Duplication is mostly handled well**: `migration_hints` *imports* the RepMap library from `validate_table` (good). Remaining copy-paste is small (~30–50 lines): identical RepMap-index build loop, duplicated `replica_found` predicate, and **two `format_replica_primary` functions identical except EN vs pt-BR labels**.
- **EN-vs-pt-BR inconsistency** 🟠: the two reports emit the *same* RepMap match with different vocabularies (`EXACT_KEY` vs a pt-BR sentence). The two CSVs **can't be joined/diffed** on match-level, and `_REPMAP_NIVEL_PT.get(lvl, lvl)` silently falls back to raw English when a new level is added — a maintenance trap.
- **Position-based `.xlsx` parsing** (`load_repmap_rows` hardcodes `row[0]..row[9]`): any column reorder in `RepMap.xlsx` silently maps wrong fields. Switch to header-name lookup.
- **Dead branch** in `match_artifact` (184–186 re-checks a condition already returned at 175–177).
- Both hand-roll positional `sys.argv` parsing instead of argparse.

### `gcp_bigquery_table_data_export.py` (454 lines) 🟢 + `bq_connect.py` (314 lines) 🟡

- The export script is the **best-engineered CLI** of the lot (proper argparse, mutual-exclusion validation). Minor: `export_rows_to_output` duplicates a 5000-row progress block ×3; uses manual open/close instead of `with`.
- **`bq_connect.py` is an orphan**: zero importers across the repo; its `main()` just runs a hardcoded `DEFAULT_QUERY` against a prod table and prints `df.head()` — a connectivity smoke-test. Yet it contains the *more capable* auth factory (`get_bigquery_client`: SA-JSON → saved OAuth → browser OAuth → ADC), while the export script reimplements a weaker `bigquery.Client(...)` inline.
- **Recommendation**: either delete `bq_connect.py`, or promote `get_bigquery_client` (add a `project=` param) into a shared `bq_auth.py` that the export script imports — don't maintain two auth paths.

---

## 4. Prioritized recommendations

### P0 — correctness of the dependency graph (do first, small effort, high impact)
1. **Add a single `canonical_table_key(name)`** (upper-case, strip backticks/quotes, normalize `lib.member`, drop trailing `;`) and apply it on **both** sides when populating `table_to_generator` and `table_to_consumers` in `orchestrator_inventory.py`. This is *the* fix for under-linked dependencies.
2. **Track output collisions** instead of "last writer wins" — surface "N EGPs write table X" as a diagnostic (it's a real migration concern).
3. Fix the `is_strict_match` substring bug (require boundary/full match, not `in`).

### P1 — maintainability of the two big scripts
4. **`egps_extractor.py`**: extract a shared `build_metadata_header()` to kill the ~150–200 lines duplicated across the two orchestrators; decompose the XML-traversal; adopt argparse. Target: get the file well under 2,500 lines without behavior change (golden-file test the `.txt` output first).
5. **Define the `.txt` header as an explicit schema** (a small dataclass / dict with versioned field names) shared by extractor (writer) and orchestrator (reader), replacing the 22-branch `startswith` parser and the brittle comma-split. This removes the silent-field-drop risk between the two scripts.
6. Split `orchestrator_inventory.main()` into `discover() → parse_all() → build_graph() → write_report_NN()` functions; pull the report-06 block out of `main()`.

### P2 — cleanup
7. Delete `OUTPUT_REPORT_7` and its help text; delete or fold `EGPS_EXTRACTOR_V9.md` and the stale `V6:/V8:/v1` annotations into a CHANGELOG.
8. Unify EN/pt-BR RepMap labels into one parametrized formatter; remove the `.get(lvl, lvl)` fallback trap; dedupe the RepMap-index build and `replica_found` predicate.
9. Replace position-based `RepMap.xlsx` reads with header-name lookups; remove the dead branch in `match_artifact`.
10. Consolidate BigQuery auth into one module; delete or repurpose `bq_connect.py`.
11. Replace hardcoded relative paths (`INPUT_FOLDER`, `./src/...`, output names) with CLI/env overrides so the pipeline isn't CWD-locked. Add `--input`/`--output-dir` to the orchestrator and extractor.

---

## 5. Strategic note

The intended end-state is dbt on BigQuery/Databricks. The dependency graph this module produces is the **input to the migration-wave plan** the `converter/` module then executes EGP-by-EGP. That makes the **P0 normalization fix non-optional**: every other artifact (waves, prioritization, the converter's batch order) inherits the graph's edges. A clean-looking `04_ondas_de_migracao.csv` built on exact-string matching gives false confidence.

Suggested sequencing: **P0 first** (a few hours, makes the existing reports trustworthy at 118-EGP scale), then **P1.5** (the shared `.txt` schema, which is the seam decoupling the two largest scripts and the prerequisite for safely refactoring either), then the rest as opportunistic cleanup.

*Recommended next step before refactoring: capture a golden-file snapshot of the current `.txt` outputs and the six CSVs on the full 118-EGP set, so every refactor can be verified as behavior-preserving (except the P0 fix, which should add edges).*
