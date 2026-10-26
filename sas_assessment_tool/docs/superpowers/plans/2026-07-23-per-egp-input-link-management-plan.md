# Per-EGP Input Link Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-(EGP, Input) "link_broken" overlay so a specific EGP can declare it doesn't depend on a shared input without changing that input's global status.

**Architecture:** Two new persistent Delta tables (`sas_egp_input_link` state + `sas_egp_input_link_audit`) in `bv_dev_db.monitoramento_sas`, never touched by publish. Backend predicates `_sanitizado`/`_modern`/`_aingerir` get an optional `lnk` SQL-expression arg; every query that joins `sas_egp_inputs × sas_inputs_monitor` adds a LEFT JOIN to the new table and passes `coalesce(l.link_broken, false)` — a broken link then behaves exactly like "Sanitizado for that (EGP, Input) pair". Front adds an emoji toggle (`🔗`/`⛓️‍💥`) in the EGP detail panel (gestão only), a read-only badge/filter on the EGPs tab, and greyed rows in drawers.

**Tech Stack:** FastAPI + `databricks.sdk` (Statement Execution API) on the backend; React + TypeScript + `@tanstack/react-query` on the frontend; Delta Lake tables via SQL Warehouse; Databricks App with OBO (on-behalf-of-user) auth.

## Global Constraints

- **Deploy/prod-write forbidden without explicit human consent.** No `databricks apps deploy`, no OPTIMIZE/ALTER on prod tables, no `git commit`/`push` without the user asking.
- **Commits carry NO `Co-Authored-By` trailer.** (Repo-level rule.)
- **Prod tables live in `bv_dev_db.monitoramento_sas`** (dev: `monitoramento_sas_dev`) — never `client_journey`.
- **OBO auth is required** (`REQUIRE_OBO=true` in prod). All user-attributable writes go through `run_sql` (not `_run_sp`) so `current_user()` returns the human, not the service principal.
- **Do NOT use `curl`** (blocked by org policy) — use `./local_app.sh` for local checks.
- **`pipeline.ts` mirrors `main.py`** status/funil constants. If any change touches those (this feature doesn't), sync both.
- **Accented status strings are load-bearing** (`"Em ingestão"`, `"Concluído"`). Never edit `main.py` via ASCII-lossy scripts.
- **`main.py` may be Read-blocked** in some sessions — edit via targeted `Edit`/`Write`; verify with `git diff`.
- **All predicate helpers take a `lnk` SQL expression** defaulting to `"false"`. Callers that don't join the link table pass nothing; callers that do pass `"coalesce(l.link_broken, false)"`.
- **All writes to `sas_egp_input_link` bump `_lineage_gen`** (invalidates the 5-min lineage/scope cache).
- **Never drop persistent tables** (`sas_egp_input_link`, `sas_egp_input_link_audit`). They're `CREATE IF NOT EXISTS`, publish never touches them.
- **`sas_egp_input_link_audit` MUST be in `sync_dev.py::EXCLUDE`** — audit trails are per-schema (like the other 3 audit tables).
- **Gestão-only writes** for `PATCH /api/egp-input-link` — use `_require_gestao()` (existing helper).

---

## Task 1 — Table constants + DDL bootstrap

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (line 54-77 block + a new helper after `_ensure_analistas_table`)

**Interfaces:**
- Produces: two module-level constants `T_LINK`, `T_LINK_AUD` (fully-qualified table names), and function `_ensure_link_tables() -> None` that runs `CREATE TABLE IF NOT EXISTS` for both, cached with `@functools.lru_cache(maxsize=1)`.

**Why table constants only in `main.py`:** the ONBOARDING mentions duplication, but that's for tables the publish pipeline actually writes to. Backend-only tables (like `T_PIPE`, `T_CHOICE`, `T_ANALISTAS`, `T_GST`, `T_GDT`, `T_GBV`) are declared **only** in `main.py`. `sas_egp_input_link` follows that pattern — publish never touches it.

- [ ] **Step 1: Add the two constants after `T_PIPE_AUD`** (`main.py` around line 77)

Locate:
```python
T_PIPE_AUD = f"{FQ}.sas_pipeline_audit"
```

Insert immediately after:
```python
T_LINK = f"{FQ}.sas_egp_input_link"           # per-(EGP, Input) link state (broken = counts as Sanitizado for that EGP only)
T_LINK_AUD = f"{FQ}.sas_egp_input_link_audit"  # audit trail for T_LINK writes
```

- [ ] **Step 2: Add the DDL bootstrap helper** after `_ensure_analistas_table` (around line 488), before the `@app.get("/api/analistas")` route.

```python
@functools.lru_cache(maxsize=1)
def _ensure_link_tables():
    """DDL bootstrap p/ o overlay de vínculo per-(EGP, Input). Duas tabelas persistentes,
    nunca dropadas pelo publish (padrão de T_CHOICE, T_PIPE): estado + auditoria. Executa
    uma vez por processo (lru_cache) — idempotente via CREATE IF NOT EXISTS."""
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_LINK} (
      projeto STRING NOT NULL,
      chave_canonica STRING NOT NULL,
      link_broken BOOLEAN NOT NULL,
      updated_by STRING,
      updated_at TIMESTAMP
    ) USING DELTA""", want_rows=False)
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_LINK_AUD} (
      id STRING,
      projeto STRING,
      chave_canonica STRING,
      campo STRING,
      valor_antigo STRING,
      valor_novo STRING,
      ator STRING,
      ts TIMESTAMP
    ) USING DELTA""", want_rows=False)
    return True
```

- [ ] **Step 3: Verify manually** — run `./local_app.sh` (dev DB). On first backend request, `_ensure_link_tables()` will fire when a downstream task calls it. For now, just make sure the file parses:

Run:
```bash
cd egps_analysis/app && python3 -c "from backend.main import T_LINK, T_LINK_AUD, _ensure_link_tables; print(T_LINK, T_LINK_AUD)"
```
Expected: two FQ names printed, no import error.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): declare sas_egp_input_link tables + DDL bootstrap"
```

---

## Task 2 — Extend predicates with `lnk` overlay

**Files:**
- Modify: `egps_analysis/app/backend/main.py:84-114` (the four predicate helpers)
- Create: `egps_analysis/app/backend/test_link_predicates.py`

**Interfaces:**
- Produces: predicate helpers now accept optional 3rd arg `lnk: str = "false"`:
  - `_sanitizado(sh, auto, lnk)` — returns SQL `(_eff_status IN ('Sanitizado') OR {lnk})`
  - `_modern(sh, auto, lnk)` — returns SQL `(_eff_status IN ('Modernizado','Sanitizado') OR {lnk})`
  - `_aingerir(sh, auto, lnk)` — returns SQL `NOT _modern(sh, auto, lnk)`
- Default value `"false"` = old behavior (broken links don't apply).

- [ ] **Step 1: Write the failing test**

Create `egps_analysis/app/backend/test_link_predicates.py`:

```python
"""Testes unitários dos predicados SQL de status EFETIVO. Não bate no warehouse;
apenas verifica o STRING SQL gerado — a regra de sanitizado/modern/a_ingerir e o
overlay opcional de vínculo quebrado (lnk)."""
import re
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.main import _sanitizado, _modern, _aingerir  # noqa: E402


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def test_sanitizado_default_lnk_matches_legacy_behavior():
    s = _sanitizado()
    assert "'Sanitizado'" in s
    assert "OR false" in _norm(s), f"lnk default deveria ser 'false': {s}"


def test_sanitizado_with_lnk_expression_gets_ored():
    s = _sanitizado("i.status_humano", "e.modernizada_auto", lnk="coalesce(l.link_broken, false)")
    n = _norm(s)
    assert "'Sanitizado'" in n
    assert "OR coalesce(l.link_broken, false)" in n, f"lnk deve entrar como OR: {n}"


def test_modern_lnk_ored():
    s = _modern("i.status_humano", "e.modernizada_auto", lnk="coalesce(l.link_broken, false)")
    n = _norm(s)
    assert "'Modernizado'" in n and "'Sanitizado'" in n
    assert "OR coalesce(l.link_broken, false)" in n


def test_aingerir_negates_modern_with_lnk():
    s = _aingerir("i.status_humano", "e.modernizada_auto", lnk="coalesce(l.link_broken, false)")
    n = _norm(s)
    assert n.startswith("(NOT ") or n.startswith("NOT ")
    assert "coalesce(l.link_broken, false)" in n


def test_lnk_true_forces_sanitized_short_circuit_semantics():
    """Ao passar lnk='true', a expressão OR-ed deveria colapsar em true no
    otimizador — verificamos que a string contém `OR true`."""
    s = _sanitizado("i.status_humano", "e.modernizada_auto", lnk="true")
    assert "OR true" in _norm(s)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd egps_analysis/app && python3 backend/test_link_predicates.py
```
Expected: `TypeError: _sanitizado() got an unexpected keyword argument 'lnk'` (predicates don't accept `lnk` yet).

- [ ] **Step 3: Extend the predicates in `main.py:84-114`**

Replace:
```python
def _modern(sh="status_humano", auto="modernizada_auto"):
    """Modernizado = resolvido (não pendente)."""
    return f"({_eff_status(sh, auto)} IN ('Modernizado','Sanitizado'))"


def _aingerir(sh="status_humano", auto="modernizada_auto"):
    """Pendência: tudo que não está modernizado (A receber / Recebido / Em ingestão)."""
    return f"(NOT {_modern(sh, auto)})"


def _sanitizado(sh="status_humano", auto="modernizada_auto"):
    """Sanitizado = descartado/REMOVIDO DO ESCOPO. Não conta como disponível nem entra em
    nenhum denominador de escopo (some das métricas em TODO o app). Segue visível na lista do
    Monitor p/ gestão. Aplicar `AND NOT _sanitizado()` no universo de cada contagem de escopo."""
    return f"({_eff_status(sh, auto)} IN ('Sanitizado'))"
```

With:
```python
def _modern(sh="status_humano", auto="modernizada_auto", lnk="false"):
    """Modernizado = resolvido (não pendente). `lnk`: expressão SQL BOOLEAN opcional
    (default 'false') que faz um par (egp, input) contar como resolvido — usado pelo
    overlay per-(EGP, Input) de vínculo quebrado. Callers que fazem
    LEFT JOIN sas_egp_input_link l ON ... passam lnk='coalesce(l.link_broken, false)'."""
    return f"({_eff_status(sh, auto)} IN ('Modernizado','Sanitizado') OR {lnk})"


def _aingerir(sh="status_humano", auto="modernizada_auto", lnk="false"):
    """Pendência: tudo que não está modernizado (A receber / Recebido / Em ingestão).
    `lnk`: ver _modern — vínculo quebrado é considerado resolvido."""
    return f"(NOT {_modern(sh, auto, lnk)})"


def _sanitizado(sh="status_humano", auto="modernizada_auto", lnk="false"):
    """Sanitizado = descartado/REMOVIDO DO ESCOPO. Não conta como disponível nem entra em
    nenhum denominador de escopo (some das métricas em TODO o app). Segue visível na lista do
    Monitor p/ gestão. `lnk`: expressão SQL BOOLEAN opcional (default 'false') — vínculo
    quebrado é tratado como Sanitizado para AQUELE (EGP, Input) apenas. Aplicar
    `AND NOT _sanitizado()` no universo de cada contagem de escopo."""
    return f"({_eff_status(sh, auto)} IN ('Sanitizado') OR {lnk})"
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd egps_analysis/app && python3 backend/test_link_predicates.py
```
Expected: `✓ test_sanitizado_default_lnk_matches_legacy_behavior` and 4 more lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/backend/main.py egps_analysis/app/backend/test_link_predicates.py
git commit -m "feat(app): predicados _sanitizado/_modern/_aingerir aceitam overlay lnk"
```

---

## Task 3 — PATCH `/api/egp-input-link` endpoint

**Files:**
- Modify: `egps_analysis/app/backend/main.py` — add a Pydantic model + a handler after the `PATCH /api/inputs` handler (around line 1090).
- Create: `egps_analysis/app/backend/test_egp_input_link_endpoint.py`

**Interfaces:**
- Produces: HTTP `PATCH /api/egp-input-link` with body `{projeto: str, chave_canonica: str, link_broken: bool}`. Returns `{ok: bool, projeto, chave_canonica, link_broken}`. Requires gestão membership (`_require_gestao()`).
- Consumes: `T_LINK`, `T_LINK_AUD`, `_ensure_link_tables()`, `_lineage_gen` (Task 1); `sql_lit`, `run_sql`, `_require_gestao`, `_norm`, `uuid` (existing helpers).

- [ ] **Step 1: Write the failing test**

Create `egps_analysis/app/backend/test_egp_input_link_endpoint.py`:

```python
"""Testes do endpoint PATCH /api/egp-input-link. Usa FastAPI TestClient e stub
das dependências que batem no warehouse (run_sql, _require_gestao) — não
depende de credenciais nem de rede."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m


def _mk_client(gestao=True, existing_broken=None):
    """Cria um TestClient com run_sql/_require_gestao stubados. `existing_broken`
    controla o SELECT que verifica o valor anterior no state table."""
    calls = {"sql": [], "gen_before": m._lineage_gen}

    def fake_run_sql(stmt, want_rows=True):
        calls["sql"].append(stmt)
        s = stmt.strip().lower()
        if s.startswith("select") and "from" in s and "sas_egp_input_link" in s and "audit" not in s:
            # simula o SELECT que lê o estado atual (para o valor_antigo do audit)
            if existing_broken is None:
                return []
            return [{"link_broken": existing_broken}]
        return []

    def fake_require_gestao():
        if not gestao:
            from fastapi import HTTPException
            raise HTTPException(403, "Restrito ao grupo de gestão (bv_users).")

    patch_a = patch.object(m, "run_sql", side_effect=fake_run_sql)
    patch_b = patch.object(m, "_require_gestao", side_effect=fake_require_gestao)
    patch_c = patch.object(m, "_ensure_link_tables", lambda: True)
    patch_a.start(); patch_b.start(); patch_c.start()
    client = TestClient(m.app)
    return client, calls, (patch_a, patch_b, patch_c)


def _stop(patches):
    for p in patches:
        p.stop()


def test_gestao_break_link_writes_state_and_audit_and_bumps_gen():
    c, calls, ps = _mk_client(gestao=True, existing_broken=None)
    try:
        gen0 = m._lineage_gen
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "Cobrancas__Foo", "chave_canonica": "tabela::T1",
                          "link_broken": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"ok": True, "projeto": "Cobrancas__Foo",
                        "chave_canonica": "tabela::T1", "link_broken": True}
        # 3 statements: SELECT estado atual + MERGE/INSERT em T_LINK + INSERT audit
        stmts = [s.lower() for s in calls["sql"]]
        assert any("select" in s and "sas_egp_input_link" in s and "audit" not in s for s in stmts)
        assert any("sas_egp_input_link" in s and ("merge" in s or "insert into" in s and "audit" not in s) for s in stmts)
        assert any("sas_egp_input_link_audit" in s and "insert" in s for s in stmts)
        assert m._lineage_gen == gen0 + 1
    finally:
        _stop(ps)


def test_restore_link_deletes_state_row_and_audits():
    """link_broken=false quando a linha existia → DELETE + audit."""
    c, calls, ps = _mk_client(gestao=True, existing_broken=True)
    try:
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "P", "chave_canonica": "K", "link_broken": False})
        assert r.status_code == 200, r.text
        stmts = [s.lower() for s in calls["sql"]]
        assert any("delete from" in s and "sas_egp_input_link" in s and "audit" not in s for s in stmts)
        assert any("sas_egp_input_link_audit" in s and "insert" in s for s in stmts)
    finally:
        _stop(ps)


def test_no_change_returns_ok_but_skips_audit():
    """link_broken já é o valor atual → não escreve audit (mesmo padrão de patch_input)."""
    c, calls, ps = _mk_client(gestao=True, existing_broken=True)
    try:
        gen0 = m._lineage_gen
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "P", "chave_canonica": "K", "link_broken": True})
        assert r.status_code == 200
        stmts = [s.lower() for s in calls["sql"]]
        # SELECT rodou; audit não
        assert any("select" in s and "sas_egp_input_link" in s and "audit" not in s for s in stmts)
        assert not any("sas_egp_input_link_audit" in s and "insert" in s for s in stmts)
        # nada mudou → cache não bumpa
        assert m._lineage_gen == gen0
    finally:
        _stop(ps)


def test_non_gestao_gets_403():
    c, _calls, ps = _mk_client(gestao=False)
    try:
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "P", "chave_canonica": "K", "link_broken": True})
        assert r.status_code == 403, r.text
    finally:
        _stop(ps)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd egps_analysis/app && python3 backend/test_egp_input_link_endpoint.py
```
Expected: HTTP 404 (route not registered) — `AssertionError: 404 != 200`.

- [ ] **Step 3: Add the Pydantic model and handler**

In `main.py`, find the end of `patch_input` (around line 1090, just after the `return result`). Add:

```python
class EgpInputLink(BaseModel):
    projeto: str
    chave_canonica: str
    link_broken: bool


@app.patch("/api/egp-input-link")
def patch_egp_input_link(p: EgpInputLink):
    """Quebra/restaura o vínculo (EGP, Input). Broken=True → aquele input passa a
    contar como Sanitizado para AQUELE EGP apenas (não afeta outros consumidores).
    Somente gestão (bv_users); auditado em T_LINK_AUD; bumpa _lineage_gen p/ invalidar
    o cache de linhagem (readiness/blocking/priorização recomputam ao vivo)."""
    global _lineage_gen
    _require_gestao()
    _ensure_link_tables()
    cur = run_sql(
        f"SELECT link_broken FROM {T_LINK} WHERE projeto = {sql_lit(p.projeto)} "
        f"AND chave_canonica = {sql_lit(p.chave_canonica)}")
    old = bool(cur[0]["link_broken"]) if cur else False
    changed = (old != bool(p.link_broken))
    if changed:
        if p.link_broken:
            # UPSERT: linha ausente ≡ linkado; só existem linhas para link_broken=true.
            run_sql(
                f"MERGE INTO {T_LINK} t USING (SELECT {sql_lit(p.projeto)} AS projeto, "
                f"{sql_lit(p.chave_canonica)} AS chave_canonica) s "
                f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica "
                f"WHEN MATCHED THEN UPDATE SET t.link_broken = true, "
                f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
                f"WHEN NOT MATCHED THEN INSERT (projeto, chave_canonica, link_broken, "
                f"updated_by, updated_at) VALUES ({sql_lit(p.projeto)}, "
                f"{sql_lit(p.chave_canonica)}, true, current_user(), current_timestamp())",
                want_rows=False)
        else:
            run_sql(
                f"DELETE FROM {T_LINK} WHERE projeto = {sql_lit(p.projeto)} "
                f"AND chave_canonica = {sql_lit(p.chave_canonica)}", want_rows=False)
        run_sql(
            f"INSERT INTO {T_LINK_AUD} (id, projeto, chave_canonica, campo, valor_antigo, "
            f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
            f"{sql_lit(p.projeto)}, {sql_lit(p.chave_canonica)}, 'link_broken', "
            f"{sql_lit(_norm(old))}, {sql_lit(_norm(p.link_broken))}, current_user(), "
            f"current_timestamp())", want_rows=False)
        _lineage_gen += 1
    return {"ok": True, "projeto": p.projeto, "chave_canonica": p.chave_canonica,
            "link_broken": p.link_broken}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd egps_analysis/app && python3 backend/test_egp_input_link_endpoint.py
```
Expected: 4 `✓` lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/backend/main.py egps_analysis/app/backend/test_egp_input_link_endpoint.py
git commit -m "feat(app): PATCH /api/egp-input-link (gestao-only, audited)"
```

---

## Task 4 — Wire `/api/egp` (EGP detail inputs list)

**Files:**
- Modify: `egps_analysis/app/backend/main.py:1948-1953` (the `inputs = run_sql(...)` SQL inside `egp_detail`)

**Interfaces:**
- Produces: each element of the response `inputs[]` gains a boolean field `link_broken` (default `false`). Consumed by the frontend `EgpInput.link_broken` in Task 15.
- Consumes: `T_LINK` (Task 1); `_ensure_link_tables()` (Task 1).

- [ ] **Step 1: Ensure the link table exists on the first read**

Locate the SELECT at `main.py:1948-1953`:

```python
    inputs = run_sql(
        f"SELECT e.chave_canonica, e.artifact, e.categoria, e.source_types, e.modernizada_auto, "
        f"i.origem, i.status_humano, i.responsavel, i.observacao, "
        f"i.paths_fisicos, i.n_paths_fisicos "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"WHERE e.projeto = {plit} ORDER BY e.categoria, e.artifact")
```

Just BEFORE it, add:
```python
    _ensure_link_tables()
```

Then replace the SELECT with:
```python
    inputs = run_sql(
        f"SELECT e.chave_canonica, e.artifact, e.categoria, e.source_types, e.modernizada_auto, "
        f"i.origem, i.status_humano, i.responsavel, i.observacao, "
        f"i.paths_fisicos, i.n_paths_fisicos, "
        f"coalesce(l.link_broken, false) AS link_broken "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto = {plit} ORDER BY e.categoria, e.artifact")
```

- [ ] **Step 2: Manual smoke test**

Start the app locally and hit an EGP:
```bash
cd egps_analysis/app && ./local_app.sh
# in a second terminal
python3 -c "import urllib.request, json, urllib.parse; \
  q = urllib.parse.urlencode({'projeto': 'PICK_AN_EGP_ID'}); \
  print(json.dumps(json.loads(urllib.request.urlopen(f'http://127.0.0.1:8000/api/egp?{q}').read())['inputs'][:1], indent=2))"
```
Expected: JSON with a `link_broken: false` field on the first input.

Replace `PICK_AN_EGP_ID` with an actual EGP name — inspect `SHOW TABLES` output or run `SELECT projeto FROM bv_dev_db.monitoramento_sas_dev.sas_egp_inputs LIMIT 1` via `bq_connect.py` if unsure.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): /api/egp inclui link_broken por input"
```

---

## Task 5 — Wire `_egp_readiness_rows` + `n_links_broken` counter

**Files:**
- Modify: `egps_analysis/app/backend/main.py:2121-2200` (`_egp_readiness_rows`)

**Interfaces:**
- Produces: each row in `_egp_readiness_rows` output gains `n_links_broken: int`. The existing counters `n_inputs`, `n_disp`, `n_faltam`, `pct` recompute automatically because the `san`/`mod` predicates now include the link overlay.
- Consumes: `T_LINK`, `_ensure_link_tables` (Task 1); predicates with `lnk` (Task 2).

- [ ] **Step 1: Modify `_egp_readiness_rows`** — locate the block at lines 2132-2140. Replace:

```python
    where = "WHERE e.escopo_indi = true" if scope == "indi" else ""
    san = _sanitizado("i.status_humano", "e.modernizada_auto")
    mod = _modern("i.status_humano", "e.modernizada_auto")
    rows = run_sql(
        f"SELECT e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id, "
        f"count(CASE WHEN NOT ({san}) THEN 1 END) AS n_inputs, "
        f"count(CASE WHEN NOT ({san}) AND {mod} THEN 1 END) AS n_disp "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"{where} GROUP BY e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id")
```

With:
```python
    _ensure_link_tables()
    where = "WHERE e.escopo_indi = true" if scope == "indi" else ""
    lnk = "coalesce(l.link_broken, false)"
    san = _sanitizado("i.status_humano", "e.modernizada_auto", lnk)
    mod = _modern("i.status_humano", "e.modernizada_auto", lnk)
    rows = run_sql(
        f"SELECT e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id, "
        f"count(CASE WHEN NOT ({san}) THEN 1 END) AS n_inputs, "
        f"count(CASE WHEN NOT ({san}) AND {mod} THEN 1 END) AS n_disp, "
        f"count(CASE WHEN {lnk} THEN 1 END) AS n_links_broken "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"{where} GROUP BY e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id")
```

- [ ] **Step 2: Propagate `n_links_broken` to the row output** — locate the `out.append({...})` block around line 2159. Add `n_links_broken` next to `n_faltam`:

Find:
```python
            "n_inputs": ni, "n_disp": nd, "n_faltam": ni - nd,
```
Replace with:
```python
            "n_inputs": ni, "n_disp": nd, "n_faltam": ni - nd,
            "n_links_broken": int(r.get("n_links_broken") or 0),
```

- [ ] **Step 3: Also update the `_stub` in `/api/egp-readiness`** — locate lines 2275-2280 (the `_stub` function used for EGPs with no inputs in the deps view). Add `n_links_broken: 0`:

Find:
```python
        def _stub(p):
            return {"projeto": p, "area": area_missing.get(p) or "", "onda": "",
                    "escopo_indi": False, "ciclo_id": 0, "n_inputs": 0, "n_disp": 0,
                    "n_faltam": 0, "pct": 100, "n_deps": 0, "n_deps_indi": 0,
                    "n_deps_ext": 0, "deps": [], "status": "", "etapa": "",
                    "bloqueado_dep": False, "responsavel": None}
```
Replace with:
```python
        def _stub(p):
            return {"projeto": p, "area": area_missing.get(p) or "", "onda": "",
                    "escopo_indi": False, "ciclo_id": 0, "n_inputs": 0, "n_disp": 0,
                    "n_faltam": 0, "n_links_broken": 0, "pct": 100, "n_deps": 0,
                    "n_deps_indi": 0, "n_deps_ext": 0, "deps": [], "status": "",
                    "etapa": "", "bloqueado_dep": False, "responsavel": None}
```

- [ ] **Step 4: Smoke-test locally**

Restart `local_app.sh` and hit `/api/egp-readiness?scope=indi`:
```bash
python3 -c "import urllib.request, json; \
  data = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/egp-readiness?scope=indi').read()); \
  print(json.dumps(data['rows'][:1], indent=2))"
```
Expected: `n_links_broken: 0` present on the first row.

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): _egp_readiness_rows aplica overlay e retorna n_links_broken"
```

---

## Task 6 — Wire `_readiness_inputs_header` + `_sem_fonte_by_proj`

**Files:**
- Modify: `egps_analysis/app/backend/main.py:2204-2245` (both helpers)

**Interfaces:**
- Produces: header counters (`inputs_distintos`, `inputs_distintos_disp`, `inputs_distintos_faltam`, `inputs_sem_fonte`) recompute with the link overlay applied. `_sem_fonte_by_proj` per-EGP counter drops rows where the link is broken.
- Consumes: `T_LINK`, predicates with `lnk`.

- [ ] **Step 1: Modify `_sem_fonte_by_proj`** — locate lines 2204-2219 and replace the SQL:

Find:
```python
    _mod = _modern("i.status_humano", "e.modernizada_auto")
    for rr in run_sql(
        f"SELECT e.projeto, count(DISTINCT CASE WHEN i.origem = {sql_lit('SAS/Local (externo)')} "
        f"AND NOT ({_mod}) THEN e.chave_canonica END) AS n FROM {T_EGP} e "
        f"LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"WHERE e.projeto IN ({_fin}) GROUP BY e.projeto"):
```

Replace with:
```python
    _ensure_link_tables()
    _lnk = "coalesce(l.link_broken, false)"
    _mod = _modern("i.status_humano", "e.modernizada_auto", _lnk)
    for rr in run_sql(
        f"SELECT e.projeto, count(DISTINCT CASE WHEN i.origem = {sql_lit('SAS/Local (externo)')} "
        f"AND NOT ({_mod}) THEN e.chave_canonica END) AS n FROM {T_EGP} e "
        f"LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({_fin}) GROUP BY e.projeto"):
```

- [ ] **Step 2: Modify `_readiness_inputs_header`** — locate lines 2222-2245 and replace the SQL block:

Find:
```python
    mod = _modern("i.status_humano", "e.modernizada_auto")
    dd = run_sql(
        f"SELECT count(DISTINCT e.chave_canonica) AS n_dist, "
        f"count(DISTINCT CASE WHEN ({mod}) THEN e.chave_canonica END) AS n_disp, "
        f"count(DISTINCT CASE WHEN e.projeto IN ({base_in}) THEN e.chave_canonica END) AS n_base, "
        f"count(DISTINCT CASE WHEN i.origem = {sql_lit('SAS/Local (externo)')} AND NOT ({mod}) THEN e.chave_canonica END) AS n_sem_fonte "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"WHERE e.projeto IN ({front_in}) "
        f"AND NOT ({_sanitizado('i.status_humano', 'e.modernizada_auto')})")
```

Replace with:
```python
    _ensure_link_tables()
    lnk = "coalesce(l.link_broken, false)"
    mod = _modern("i.status_humano", "e.modernizada_auto", lnk)
    dd = run_sql(
        f"SELECT count(DISTINCT e.chave_canonica) AS n_dist, "
        f"count(DISTINCT CASE WHEN ({mod}) THEN e.chave_canonica END) AS n_disp, "
        f"count(DISTINCT CASE WHEN e.projeto IN ({base_in}) THEN e.chave_canonica END) AS n_base, "
        f"count(DISTINCT CASE WHEN i.origem = {sql_lit('SAS/Local (externo)')} AND NOT ({mod}) THEN e.chave_canonica END) AS n_sem_fonte "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({front_in}) "
        f"AND NOT ({_sanitizado('i.status_humano', 'e.modernizada_auto', lnk)})")
```

**Note:** `n_dist` (distinct chaves) is NOT filtered by `mod`/`san` in the SELECT — a chave that appears with broken link for EGP_A but active link for EGP_B still counts as one distinct input in the frontier universe. This is correct: the header is "distinct inputs in the frontier", not "distinct inputs no EGP still uses". The distinct-count semantics here are unaffected.

- [ ] **Step 3: Smoke-test**

Restart app; hit `/api/egp-readiness?scope=indi_deps`, check `inputs_distintos` and `inputs_distintos_faltam` still look sensible (should be numeric, non-zero).

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): overlay lnk em _readiness_inputs_header e _sem_fonte_by_proj"
```

---

## Task 7 — Wire `/api/waves`

**Files:**
- Modify: `egps_analysis/app/backend/main.py:2329-2342`

- [ ] **Step 1: Update the waves SQL**

Locate the block:
```python
@app.get("/api/waves")
def waves(scope: str = "indi"):
    san = _sanitizado("i.status_humano", "e.modernizada_auto")
    where = f"WHERE NOT ({san})" + (" AND e.escopo_indi = true" if scope == "indi" else "")
    eff = _eff_status("i.status_humano", "e.modernizada_auto")
    mod = _modern("i.status_humano", "e.modernizada_auto")
    rows = run_sql(
        f"SELECT e.onda AS onda, count(DISTINCT e.projeto) AS n_egps, "
        f"count(DISTINCT e.chave_canonica) AS n_inputs, "
        f"count(DISTINCT CASE WHEN {mod} THEN e.chave_canonica END) AS n_ingeridos, "
        f"count(DISTINCT CASE WHEN {eff} IN ('Recebido','Em ingestão') "
        f"THEN e.chave_canonica END) AS n_andamento "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"{where} GROUP BY e.onda")
```

Replace with:
```python
@app.get("/api/waves")
def waves(scope: str = "indi"):
    _ensure_link_tables()
    lnk = "coalesce(l.link_broken, false)"
    san = _sanitizado("i.status_humano", "e.modernizada_auto", lnk)
    where = f"WHERE NOT ({san})" + (" AND e.escopo_indi = true" if scope == "indi" else "")
    eff = _eff_status("i.status_humano", "e.modernizada_auto")
    mod = _modern("i.status_humano", "e.modernizada_auto", lnk)
    rows = run_sql(
        f"SELECT e.onda AS onda, count(DISTINCT e.projeto) AS n_egps, "
        f"count(DISTINCT e.chave_canonica) AS n_inputs, "
        f"count(DISTINCT CASE WHEN {mod} THEN e.chave_canonica END) AS n_ingeridos, "
        f"count(DISTINCT CASE WHEN {eff} IN ('Recebido','Em ingestão') "
        f"THEN e.chave_canonica END) AS n_andamento "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"{where} GROUP BY e.onda")
```

- [ ] **Step 2: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): /api/waves aplica overlay lnk"
```

---

## Task 8 — Wire `_compute_priorizacao`

**Files:**
- Modify: `egps_analysis/app/backend/main.py:2441-2455` (the `pairs` SELECT inside `_compute_priorizacao`)

**Note:** The Priorização function is long; only the `pairs` SELECT joins `T_EGP × T_IN` and needs the overlay. Everything downstream (`egp_inputs`, `n_ingerivel`, `_viab`, `plan_months`) operates on the returned set — filtering broken pairs at the SQL level makes them disappear from every downstream computation for free.

- [ ] **Step 1: Update the `pairs` SELECT**

Locate lines 2441-2445:
```python
    inl = ", ".join(sql_lit(pj) for pj in frontier)
    pairs = run_sql(
        f"SELECT e.projeto AS projeto, e.chave_canonica AS chave, i.origem AS origem "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"WHERE e.projeto IN ({inl}) AND NOT ({_modern('i.status_humano', 'e.modernizada_auto')})")
```

Replace with:
```python
    _ensure_link_tables()
    inl = ", ".join(sql_lit(pj) for pj in frontier)
    lnk = "coalesce(l.link_broken, false)"
    pairs = run_sql(
        f"SELECT e.projeto AS projeto, e.chave_canonica AS chave, i.origem AS origem "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({inl}) "
        f"AND NOT ({_modern('i.status_humano', 'e.modernizada_auto', lnk)})")
```

- [ ] **Step 2: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): _compute_priorizacao filtra vínculos quebrados do plano"
```

---

## Task 9 — Wire `_blocking` (leaf-blockers)

**Files:**
- Modify: `egps_analysis/app/backend/main.py:1860-1865` (the `cand` SELECT in `_blocking._produce`)

**Interfaces:**
- Produces: an EGP with a broken link to a SAS/local input that would otherwise be a leaf blocker no longer surfaces that leaf; if it was the only blocker, the 🔒 disappears for that EGP.

- [ ] **Step 1: Update the leaf-blocker SELECT**

Locate the block around lines 1860-1865:
```python
        cand = run_sql(
            f"SELECT e.projeto AS projeto, i.artifact AS artifact "
            f"FROM {T_EGP} e JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
            f"WHERE i.categoria = 'tabela' AND NOT i.orfao "
            f"AND NOT ({_modern('i.status_humano', 'i.modernizada_auto')}) "
            f"AND upper(i.source_types) LIKE '%SAS/LOCAL%'")
```

Replace with:
```python
        _ensure_link_tables()
        lnk = "coalesce(l.link_broken, false)"
        cand = run_sql(
            f"SELECT e.projeto AS projeto, i.artifact AS artifact "
            f"FROM {T_EGP} e JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE i.categoria = 'tabela' AND NOT i.orfao "
            f"AND NOT ({_modern('i.status_humano', 'i.modernizada_auto', lnk)}) "
            f"AND upper(i.source_types) LIKE '%SAS/LOCAL%'")
```

- [ ] **Step 2: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): _blocking pula (egp, input) com vínculo quebrado"
```

---

## Task 10 — Wire landing "+ deps" and `/api/resumo` "+ deps"

**Files:**
- Modify: `egps_analysis/app/backend/main.py:1093-1134` (landing)
- Modify: `egps_analysis/app/backend/main.py:2947-2969` (resumo `+ deps` block)

**Interfaces:**
- Produces: the "+ dependências" frontier's chave universe (`deps_chaves` in landing; `ch_fr` in resumo) drops (egp, chave) pairs where the link is broken. If a chave becomes orphan (no frontier EGP still consumes it non-brokenly), it falls out of the frontier universe entirely.

- [ ] **Step 1: Landing** — locate lines 1120-1125:

```python
    if deps:
        inlist = ", ".join(sql_lit(p) for p in deps)
        deps_chaves = {r["chave_canonica"] for r in run_sql(f"SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE projeto IN ({inlist})")}
        novo = deps_chaves - indi_chaves - sanit_chaves
        item6 = len(novo)
        item7 = len(novo & aing_chaves)
```

Replace with:
```python
    if deps:
        _ensure_link_tables()
        inlist = ", ".join(sql_lit(p) for p in deps)
        deps_chaves = {r["chave_canonica"] for r in run_sql(
            f"SELECT DISTINCT e.chave_canonica FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE e.projeto IN ({inlist}) AND NOT coalesce(l.link_broken, false)")}
        novo = deps_chaves - indi_chaves - sanit_chaves
        item6 = len(novo)
        item7 = len(novo & aing_chaves)
```

**Note:** `indi_chaves` is intentionally NOT filtered by link — an input in the Indicium base scope stays in the base regardless of individual EGP links (the base is defined by `escopo_indi=true`, which is EGP-level). Only the frontier-derived `deps_chaves` needs the filter.

- [ ] **Step 2: Resumo `+ deps`** — locate the block around lines 2947-2952:

```python
    if frontier:
        inl = ", ".join(sql_lit(p) for p in frontier)
        ch_fr = (f"r.chave_canonica IN (SELECT DISTINCT chave_canonica FROM {T_EGP} "
                 f"WHERE projeto IN ({inl}))")
        origem_deps = origem_block(ch_fr)
        nm_deps = nao_mod_por_area(ch_fr)
```

Replace with:
```python
    if frontier:
        _ensure_link_tables()
        inl = ", ".join(sql_lit(p) for p in frontier)
        ch_fr = (f"r.chave_canonica IN (SELECT DISTINCT e.chave_canonica FROM {T_EGP} e "
                 f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
                 f"WHERE e.projeto IN ({inl}) AND NOT coalesce(l.link_broken, false))")
        origem_deps = origem_block(ch_fr)
        nm_deps = nao_mod_por_area(ch_fr)
```

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): landing/+deps e resumo/+deps descontam vínculos quebrados"
```

---

## Task 11 — Wire `/api/inputs-egps` (CSV filter)

**Files:**
- Modify: `egps_analysis/app/backend/main.py:909-922`

**Interfaces:**
- Produces: `/api/inputs-egps` no longer returns rows where the (projeto, chave) link is broken. This is what feeds the Inputs-tab CSV explode; broken pairs disappear from the CSV for free.

- [ ] **Step 1: Update both branches**

Replace the whole handler body:
```python
@app.get("/api/inputs-egps")
def inputs_egps(scope: str = "indi", area: list[str] = Query(default=[])):
    """Mapeamento input -> EGP(s) do recorte, p/ o export 'uma linha por (input x EGP)' do
    Monitor. Aberto a qualquer usuario (mesmo escopo dos inputs)."""
    if scope == "indi_deps":
        frontier, _b = _frontier_egps("indi_deps", area)
        if not frontier:
            return {"rows": []}
        inl = ", ".join(sql_lit(pj) for pj in frontier)
        rows = run_sql(f"SELECT chave_canonica, projeto FROM {T_EGP} WHERE projeto IN ({inl})")
    else:
        w = "WHERE escopo_indi = true" if scope == "indi" else ""
        rows = run_sql(f"SELECT chave_canonica, projeto FROM {T_EGP} {w}")
    return {"rows": rows}
```

With:
```python
@app.get("/api/inputs-egps")
def inputs_egps(scope: str = "indi", area: list[str] = Query(default=[])):
    """Mapeamento input -> EGP(s) do recorte, p/ o export 'uma linha por (input x EGP)' do
    Monitor. Aberto a qualquer usuario (mesmo escopo dos inputs). Filtra pares (projeto,
    chave) com vínculo quebrado — CSV nunca exporta uma linha 'não conta para este EGP'."""
    _ensure_link_tables()
    if scope == "indi_deps":
        frontier, _b = _frontier_egps("indi_deps", area)
        if not frontier:
            return {"rows": []}
        inl = ", ".join(sql_lit(pj) for pj in frontier)
        rows = run_sql(
            f"SELECT e.chave_canonica, e.projeto FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE e.projeto IN ({inl}) AND NOT coalesce(l.link_broken, false)")
    else:
        w = "WHERE e.escopo_indi = true" if scope == "indi" else ""
        rows = run_sql(
            f"SELECT e.chave_canonica, e.projeto FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"{w}{' AND' if w else 'WHERE'} NOT coalesce(l.link_broken, false)")
    return {"rows": rows}
```

- [ ] **Step 2: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): /api/inputs-egps oculta pares com vínculo quebrado"
```

---

## Task 12 — Wire drawers: `/api/input` + `/api/output`

**Files:**
- Modify: `egps_analysis/app/backend/main.py:882-906` (`input_detail`)
- Modify: `egps_analysis/app/backend/main.py:957-979` (`output_detail`)

**Interfaces:**
- Produces: `/api/input`'s `egps[]` items and `/api/output`'s `consumidores[]` items gain `link_broken: bool` (default `false`). Frontend uses this to grey out the row and adjust counts.

- [ ] **Step 1: Update `input_detail`**

Locate the `egps` SELECT at lines 887-891:
```python
    egps = run_sql(
        f"SELECT e.projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id "
        f"FROM {T_EGP} e LEFT JOIN {T_ND} n ON e.projeto = n.projeto "
        f"WHERE e.chave_canonica = {sql_lit(chave)} "
        f"ORDER BY n.escopo_indi DESC, e.projeto")
```

Replace with:
```python
    _ensure_link_tables()
    egps = run_sql(
        f"SELECT e.projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id, "
        f"coalesce(l.link_broken, false) AS link_broken "
        f"FROM {T_EGP} e LEFT JOIN {T_ND} n ON e.projeto = n.projeto "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.chave_canonica = {sql_lit(chave)} "
        f"ORDER BY link_broken ASC, n.escopo_indi DESC, e.projeto")
```

Broken rows sort to the bottom (matches the EGP-detail table sort).

- [ ] **Step 2: Update `output_detail` `consumidores` SELECT**

Locate lines 967-971:
```python
    try:
        # consumidores: chaves de input tem prefixo categoria (tabela::) e a chave do
        # output nao — casa pelo canon puro (strip do prefixo), igual ao qtd_consumidores.
        cons = run_sql("SELECT DISTINCT projeto, area, onda, escopo_indi, ciclo_id "
                       f"FROM {T_EGP} WHERE regexp_replace(chave_canonica, '^[^:]*::', '') = {sql_lit(chave)} ORDER BY projeto")
```

Replace with:
```python
    try:
        _ensure_link_tables()
        # consumidores: chaves de input tem prefixo categoria (tabela::) e a chave do
        # output nao — casa pelo canon puro (strip do prefixo), igual ao qtd_consumidores.
        # link_broken vem do OVERLAY per-(EGP, Input): EGPs que declararam não depender do
        # input compartilham a lista mas ficam esmaecidos e não contam nos totais.
        cons = run_sql(
            f"SELECT e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id, "
            f"max(CASE WHEN coalesce(l.link_broken, false) THEN 1 ELSE 0 END) AS link_broken "
            f"FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE regexp_replace(e.chave_canonica, '^[^:]*::', '') = {sql_lit(chave)} "
            f"GROUP BY e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id "
            f"ORDER BY link_broken ASC, e.projeto")
        for r in cons:
            r["link_broken"] = bool(int(r.get("link_broken") or 0))
```

**Why `max(...)`:** an output's chave (e.g. `Foo`) can match multiple input keys with different `chave_canonica` prefixes (e.g. `tabela::Foo`, `arquivo::Foo`). If any of those (projeto, chave_canonica) pairs is broken, we consider the EGP "broken" for this output. Aggregation avoids duplicate rows.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): /api/input e /api/output expõem link_broken por consumidor"
```

---

## Task 13 — Audit union in `/api/audit`

**Files:**
- Modify: `egps_analysis/app/backend/main.py:2787-2863`

**Interfaces:**
- Produces: `/api/audit` (aba Histórico) unions `sas_egp_input_link_audit` with `fonte='Vínculos'` and `campo='link_broken@<chave_canonica>'` (the `@` prefix encoding is how the frontend distinguishes vínculo events and parses the chave).

- [ ] **Step 1: Add the 4th `_safe(...)` block**

Locate the `for r in _safe(...)` blocks around line 2829 (the EGPs block) and add a new one right after the Escopo block (~line 2843-2859).

After the block:
```python
    for r in _safe(
        f"SELECT acao, egp_dor1, projeto, ator, CAST(ts AS STRING) AS ts "
        f"FROM {T_ESC_AUD} ORDER BY ts DESC LIMIT {lim}"):
        acao = r.get("acao")
        if acao == "remove":
            va, vn = "no escopo", "removido"
        else:  # "add" (e qualquer outro valor) → trata como inclusão
            va, vn = "—", "adicionado"
        merged.append({
            "fonte": "Escopo",
            "chave_canonica": r.get("projeto") or r.get("egp_dor1"),
            "campo": "escopo",
            "valor_antigo": va,
            "valor_novo": vn,
            "updated_by": r.get("ator"),
            "updated_at": r.get("ts"),
        })
```

Add:
```python
    for r in _safe(
        f"SELECT projeto, chave_canonica, valor_antigo, valor_novo, ator, "
        f"CAST(ts AS STRING) AS ts FROM {T_LINK_AUD} "
        f"ORDER BY ts DESC LIMIT {lim}"):
        merged.append({
            "fonte": "Vínculos",
            "chave_canonica": r.get("projeto"),                          # entidade no Histórico: o EGP
            "campo": f"link_broken@{r.get('chave_canonica')}",           # frontend parseia o sufixo p/ mostrar qual input
            "valor_antigo": r.get("valor_antigo"),
            "valor_novo": r.get("valor_novo"),
            "updated_by": r.get("ator"),
            "updated_at": r.get("ts"),
        })
```

- [ ] **Step 2: Smoke-test**

After running a PATCH via curl (blocked) — instead, hit the endpoint programmatically:
```bash
python3 -c "import urllib.request, json; \
  print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/audit?limit=5').read()), indent=2))"
```
Expected: response includes rows from all 4 fontes (empty is fine before any writes).

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): /api/audit une T_LINK_AUD com fonte='Vínculos'"
```

---

## Task 14 — sync_dev.py: exclude the new audit table

**Files:**
- Modify: `egps_analysis/app/sync_dev.py:46-50` (EXCLUDE set)

**Interfaces:**
- Produces: `sync_dev.py` copies `sas_egp_input_link` (state — auto-picked by `SHOW TABLES`) but excludes `sas_egp_input_link_audit` (per-schema trail).

- [ ] **Step 1: Add the exclusion**

Locate:
```python
# estado exclusivo de dev — não vem de prod (trilhas de auditoria são per-schema)
EXCLUDE = {
    "sas_pipeline_audit",
    "sas_inputs_audit",
    "sas_escopo_audit",
}
```

Replace with:
```python
# estado exclusivo de dev — não vem de prod (trilhas de auditoria são per-schema)
EXCLUDE = {
    "sas_pipeline_audit",
    "sas_inputs_audit",
    "sas_escopo_audit",
    "sas_egp_input_link_audit",   # audit dedicado ao overlay de vínculo (per-schema)
}
```

- [ ] **Step 2: Dry-run to confirm the state table IS included and audit IS excluded**

```bash
cd egps_analysis/app && python3 sync_dev.py --dry-run 2>&1 | grep -E "sas_egp_input_link"
```
Expected: exactly one line listing `- sas_egp_input_link` (the state table) — the audit table doesn't show.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/sync_dev.py
git commit -m "chore(app): exclui sas_egp_input_link_audit do sync (per-schema)"
```

---

## Task 15 — Frontend: extend types

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts` — 4 interface additions.

**Interfaces:**
- Produces:
  - `EgpInput.link_broken?: boolean`
  - `ReadinessRow.n_links_broken?: number`
  - `InputUsageEgp.link_broken?: boolean`
  - `OutputUsageEgp.link_broken?: boolean`

- [ ] **Step 1: Add `link_broken` to `EgpInput`**

Locate:
```ts
export interface EgpInput {
  chave_canonica: string;
  artifact: string;
  categoria: string;
  source_types: string;
  origem: string;
  modernizada_auto: string;
  status_humano: string | null;
  responsavel: string | null;
  observacao: string | null;
  paths_fisicos: string;
  n_paths_fisicos: number | string;
  n_proj_ativos: number | null;   // EGPs consumidores NÃO despriorizados (0 => candidato a remover)
}
```

Add before the closing brace:
```ts
  link_broken?: boolean;          // vínculo (EGP, Input) quebrado — conta como Sanitizado APENAS para este EGP
```

- [ ] **Step 2: Add `link_broken` to `InputUsageEgp`**

Locate:
```ts
export interface InputUsageEgp {
  projeto: string;
  area: string | null;
  onda: string | null;
  escopo_indi: string | boolean | null;
  ciclo_id: number | string | null;
}
```

Add before the closing brace:
```ts
  link_broken?: boolean;          // este consumidor (EGP) declarou vínculo quebrado com o input
```

- [ ] **Step 3: Add `link_broken` to `OutputUsageEgp`**

Locate:
```ts
export interface OutputUsageEgp {
  projeto: string;
  area: string | null;
  onda: string | null;
  escopo_indi: boolean | string | null;
  ciclo_id: number | string | null;
}
```

Add before the closing brace:
```ts
  link_broken?: boolean;          // consumer (output): o EGP declarou vínculo quebrado com este output
```

- [ ] **Step 4: Add `n_links_broken` to `ReadinessRow`**

Locate:
```ts
export interface ReadinessRow {
  projeto: string;
  ...
  n_inputs: number;
  n_disp: number;
  n_faltam: number;
  ...
```

Add right after `n_faltam: number;`:
```ts
  n_links_broken?: number;         // qtos inputs deste EGP têm vínculo quebrado (informacional)
```

- [ ] **Step 5: Type-check**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/types.ts
git commit -m "feat(app): tipos do overlay per-(EGP, Input) link_broken"
```

---

## Task 16 — Frontend: `api.setEgpInputLink`

**Files:**
- Modify: `egps_analysis/app/frontend/src/api.ts`

**Interfaces:**
- Produces:
  ```ts
  api.setEgpInputLink(projeto: string, chave: string, broken: boolean)
    → Promise<{ok: boolean; projeto: string; chave_canonica: string; link_broken: boolean}>
  ```

- [ ] **Step 1: Add the method**

Locate the block at `api.ts:148-153` (`priorizacaoSetMes`) — right after it, before `egpReadiness`, add:

```ts
  // Quebra (broken=true) ou restaura (false) o vínculo per-(EGP, Input). Gestão-only
  // no backend (403 fora de bv_users); UI decide se mostra clicável ou só ícone.
  setEgpInputLink: (projeto: string, chave: string, broken: boolean) =>
    fetch("api/egp-input-link", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projeto, chave_canonica: chave, link_broken: broken }),
    }).then(json<{ ok: boolean; projeto: string; chave_canonica: string; link_broken: boolean }>),
```

- [ ] **Step 2: Type-check**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app): api.setEgpInputLink (PATCH /api/egp-input-link)"
```

---

## Task 17 — Frontend: EgpDetailPanel — link column + toggle + sort + header

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx`
- Modify: `egps_analysis/app/frontend/src/styles.css` (add `.rd-vinc-btn`, `.rd-row-broken` classes)

**Interfaces:**
- Consumes: `api.setEgpInputLink` (Task 16); `EgpInput.link_broken` (Task 15); `api.config()` (existing — for `is_gestao`).
- Produces: EGP detail panel renders a `Vínculo` column at the end of the inputs table with a `🔗`/`⛓️‍💥` glyph. Gestão gets a clickable `<button>`; others get a read-only `<span>`. Broken rows sort to the bottom and are styled muted. Header counter shows only linked inputs.

- [ ] **Step 1: Add config query (for `is_gestao`) and link mutation**

At the top of `EgpDetailPanel.tsx` after the existing `useQuery` calls (around line 71 for `egpQ`), add:

```tsx
  const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const isGestao = !!cfgQ.data?.is_gestao;
```

Then after `patchMut` (around line 125), add a new mutation:

```tsx
  const linkMut = useMutation({
    mutationFn: (v: { chave: string; broken: boolean }) =>
      api.setEgpInputLink(projeto, v.chave, v.broken),
    onMutate: async ({ chave, broken }) => {
      await qc.cancelQueries({ queryKey: egpKey });
      const prev = qc.getQueryData<EgpDetail>(egpKey);
      setDet((d) => ({ ...d, inputs: d.inputs.map((i) =>
        i.chave_canonica === chave ? { ...i, link_broken: broken } : i) }));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(egpKey, ctx.prev); },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["metrics"] });
      qc.invalidateQueries({ queryKey: ["resumo"] });
      qc.invalidateQueries({ queryKey: ["landing"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
      qc.invalidateQueries({ queryKey: ["priorizacao"] });
      qc.invalidateQueries({ queryKey: ["waves"] });
      qc.invalidateQueries({ queryKey: ["input"] });    // drawer counts
      qc.invalidateQueries({ queryKey: ["output"] });
    },
  });
  const toggleLink = (i: EgpInput) =>
    linkMut.mutate({ chave: i.chave_canonica, broken: !i.link_broken });
```

- [ ] **Step 2: Compute sorted + counter-adjusted inputs**

Locate the line `const nProdAusente = det.inputs.filter(...).length;` at line 158. Right after it, add:

```tsx
  const nLinksBroken = det.inputs.filter((i) => i.link_broken).length;
  // linkados primeiro (broken vai pro fim); dentro do mesmo grupo, mantém a ordem
  // vinda do servidor (por categoria/artefato).
  const sortedInputs = [...det.inputs].sort((a, b) =>
    Number(!!a.link_broken) - Number(!!b.link_broken));
```

- [ ] **Step 3: Update the header counter**

Locate:
```tsx
      <h3>Inputs / necessidades ({det.inputs.length}){nProdAusente > 0 && <span className="muted"> · {nProdAusente} dep. produtor ausente</span>}{nHomonimo > 0 && <span className="muted"> · {nHomonimo} homônimo{nHomonimo > 1 ? "s" : ""}</span>}</h3>
```

Replace with:
```tsx
      <h3>Inputs / necessidades ({det.inputs.length - nLinksBroken}){nProdAusente > 0 && <span className="muted"> · {nProdAusente} dep. produtor ausente</span>}{nHomonimo > 0 && <span className="muted"> · {nHomonimo} homônimo{nHomonimo > 1 ? "s" : ""}</span>}{nLinksBroken > 0 && <span className="muted"> · <span title="Vínculos quebrados: este EGP declarou que não depende destes inputs (equivalem a Sanitizado só para este EGP)">⛓️‍💥 {nLinksBroken} vínculo{nLinksBroken > 1 ? "s" : ""} quebrado{nLinksBroken > 1 ? "s" : ""}</span></span>}</h3>
```

- [ ] **Step 4: Add the `Vínculo` header column**

Locate `<div className="egp-thead">` at line 266 and add `<div>Vínculo</div>` at the end (right before `</div>`):

```tsx
        <div className="egp-thead">
          <div>Artefato</div><div>Cat.</div><div title="EGPs consumidores dentro do escopo Indicium + dependências que NÃO estão despriorizados (0 = candidato a despriorizar/remover)">#Proj Ativos Dentro do Escopo</div><div>Origem</div><div>Auto</div><div>Status (ingestão)</div><div>Responsável</div><div>Tbl. Corresp.</div><div title="Último status registrado na aba Gestão para este input — clique para abrir o painel">Último status</div><div title="Vínculo per-(EGP, Input): quebrar declara que ESTE EGP não depende deste input (equivale a Sanitizado só para este EGP). Só gestão pode alterar.">Vínculo</div>
        </div>
```

- [ ] **Step 5: Replace `det.inputs.map` with `sortedInputs.map` and add the cell**

Locate `{det.inputs.map((i) => (` at line 270. Replace with `{sortedInputs.map((i) => (`.

Then locate the closing `</div>` of the row's last cell (the "Último status" c-lstat around line 315) and add the new cell right before `</div>` of the row (the `<div key={i.chave_canonica} className="egp-trow">`):

Find:
```tsx
              {(() => {
                const gr = gestaoById.get(i.chave_canonica);
                if (!gr) return <div className="c-lstat muted">fora de escopo</div>;
                const txt = gr.resumoStatus;
                return (
                  <div className="c-lstat muted" style={{ cursor: "pointer", color: txt ? "inherit" : undefined }}
                    title={txt ?? "sem status — clique para adicionar"}
                    onClick={() => setPanelChave(i.chave_canonica)}>
                    {txt ?? "sem status"}
                  </div>
                );
              })()}
            </div>
```

Replace with:
```tsx
              {(() => {
                const gr = gestaoById.get(i.chave_canonica);
                if (!gr) return <div className="c-lstat muted">fora de escopo</div>;
                const txt = gr.resumoStatus;
                return (
                  <div className="c-lstat muted" style={{ cursor: "pointer", color: txt ? "inherit" : undefined }}
                    title={txt ?? "sem status — clique para adicionar"}
                    onClick={() => setPanelChave(i.chave_canonica)}>
                    {txt ?? "sem status"}
                  </div>
                );
              })()}
              <div className="c-vinc">
                {isGestao ? (
                  <button className="rd-vinc-btn" onClick={() => toggleLink(i)}
                    disabled={linkMut.isPending}
                    title={i.link_broken
                      ? "Vínculo quebrado — não conta para modernização deste EGP. Clique para restaurar."
                      : "Vínculo ativo. Clique para quebrar (este EGP declara não depender deste input)."}>
                    {i.link_broken ? "⛓️‍💥" : "🔗"}
                  </button>
                ) : (
                  <span title={i.link_broken ? "Vínculo quebrado (só gestão pode alterar)" : "Vínculo ativo"}>
                    {i.link_broken ? "⛓️‍💥" : "🔗"}
                  </span>
                )}
              </div>
            </div>
```

- [ ] **Step 6: Apply muted class to broken rows**

Locate the row `div`:
```tsx
            <div key={i.chave_canonica} className="egp-trow">
```

Replace with:
```tsx
            <div key={i.chave_canonica} className={`egp-trow${i.link_broken ? " egp-trow-broken" : ""}`}>
```

- [ ] **Step 7: Add CSS**

Locate `egps_analysis/app/frontend/src/styles.css` and search for `.rd-badge` or `.egp-trow` selector. At the end of the file (or in an appropriate section — locate the block that styles `.egp-trow`), add:

```css
/* --- overlay de vínculo per-(EGP, Input) ------------------------------ */
.rd-vinc-btn {
  border: 0;
  background: transparent;
  cursor: pointer;
  font-size: 15px;
  padding: 2px 4px;
  line-height: 1;
}
.rd-vinc-btn:hover { filter: brightness(1.1); }
.rd-vinc-btn:disabled { opacity: 0.5; cursor: wait; }
.egp-trow-broken {
  opacity: 0.55;
  background: transparent;
}
.rd-badge.rd-vinc {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(180, 83, 9, 0.12);   /* âmbar suave — mesmo tom do "produtor definido" */
  color: #b45309;
  margin-left: 4px;
}
```

- [ ] **Step 8: Verify the grid columns still align**

Check the CSS block for `.egp-thead` / `.egp-tbody` grid template — it currently has 9 columns. Adding `Vínculo` makes it 10. Locate the `grid-template-columns` for `.egp-thead` (grep for it):

```bash
cd egps_analysis/app/frontend/src && grep -n "egp-thead\|egp-trow" styles.css
```

Update the `grid-template-columns` rule to add one more column (typically `auto` or a small fixed width like `60px` for the icon). Example (actual values may differ):

```css
.egp-thead, .egp-trow {
  display: grid;
  grid-template-columns: /* keep the existing 9 tracks, then: */ 60px;
  /* ... */
}
```

If the file uses `repeat(9, ...)`, change to `repeat(9, ...) 60px` or bump the count to 10. Verify visually with `./local_app.sh` — the header and rows must line up.

- [ ] **Step 9: Type-check and manual verify**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
```
Expected: no errors.

Then run the app locally:
```bash
cd egps_analysis/app && ./local_app.sh
```
Open the browser to an EGP detail; verify the `Vínculo` column shows a `🔗` on each row. If you're in `bv_users`, clicking should toggle the icon. Header counter should update.

- [ ] **Step 10: Commit**

```bash
git add egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): EGP detail — coluna Vínculo com toggle (gestão) e ordenação"
```

---

## Task 18 — Frontend: ReadinessView — badge + filter + CSV

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/ReadinessView.tsx`

**Interfaces:**
- Consumes: `ReadinessRow.n_links_broken` (Task 15).
- Produces: aba EGPs renders `⛓️‍💥 N` badge next to the EGP name when `n_links_broken > 0`; new filter chip; CSV export gains a `Vínculos quebrados` column.

- [ ] **Step 1: Add filter state**

Locate the block of `useState` filters around line 78:
```tsx
  const [convOnly, setConvOnly] = useState(false); // só EGPs com Fim Conversão preenchido (sas_gestao_datas)
  const [soComResp, setSoComResp] = useState(false);
  const [noOutOnly, setNoOutOnly] = useState(false);
```

Add after:
```tsx
  const [brokenOnly, setBrokenOnly] = useState(false); // só EGPs com pelo menos 1 vínculo quebrado
```

- [ ] **Step 2: Compute count and apply filter**

Locate the counts block around line 158-159:
```tsx
  const noOutCount = useMemo(() => baseDims.filter((r) => !producersSet.has(r.projeto)).length, [baseDims, producersSet]);
```

Add after:
```tsx
  const brokenCount = useMemo(() => baseDims.filter((r) => (r.n_links_broken ?? 0) > 0).length, [baseDims]);
```

Locate the `view` `useMemo` around line 161. In the filter chain, add `brokenOnly`:

Find:
```tsx
    if (noOutOnly) v = v.filter((r) => !producersSet.has(r.projeto));
```

Add right after:
```tsx
    if (brokenOnly) v = v.filter((r) => (r.n_links_broken ?? 0) > 0);
```

And update the dependency array of `useMemo` at line 175 — add `brokenOnly`:

Find:
```tsx
  }, [baseDims, bucket, quickWin, blockedOnly, despOnly, convOnly, noOutOnly, producersSet, sort, asc]);
```

Replace with:
```tsx
  }, [baseDims, bucket, quickWin, blockedOnly, despOnly, convOnly, noOutOnly, brokenOnly, producersSet, sort, asc]);
```

- [ ] **Step 3: Add reset of `brokenOnly` in the cross-nav effect**

Locate line 180:
```tsx
    setAreaSel(new Set()); setMesSel(new Set()); setBucket(""); setQ(""); setQuickWin(false); setBlockedOnly(false); setDespOnly(false); setConvOnly(false); setSoComResp(false); setNoOutOnly(false); setStatusSel(new Set()); setEtapaSel(new Set());
```

Replace with:
```tsx
    setAreaSel(new Set()); setMesSel(new Set()); setBucket(""); setQ(""); setQuickWin(false); setBlockedOnly(false); setDespOnly(false); setConvOnly(false); setSoComResp(false); setNoOutOnly(false); setBrokenOnly(false); setStatusSel(new Set()); setEtapaSel(new Set());
```

- [ ] **Step 4: Add the badge next to the EGP name**

Locate lines 351-354:
```tsx
                    <span className="dep-caret">{isOpen ? "▾" : "▸"}</span> {shortName(r.projeto)}
                    {r.bloqueado_dep && <span style={{ marginLeft: 4 }} title="Bloqueado: depende de tabelas SAS sem produtor (EGP) mapeado">🔒</span>}
                    {r.dep_ausente && <span style={{ marginLeft: 4 }} title={`${r.n_sem_fonte} input(s) SAS/Local sem fonte`}>⚠</span>}
                    {(r.deps_despriorizadas?.length ?? 0) > 0 && <span style={{ marginLeft: 4 }} title={`Impactado por dependência despriorizada: ${(r.deps_despriorizadas ?? []).map(shortName).join(", ")}`}>⏸</span>}
```

Add right after the `⏸` line:
```tsx
                    {(r.n_links_broken ?? 0) > 0 && <span className="rd-badge rd-vinc" style={{ marginLeft: 4 }} title={`${r.n_links_broken} vínculo(s) quebrado(s) — este EGP declarou não depender de ${r.n_links_broken} input(s)`}>⛓️‍💥 {r.n_links_broken}</span>}
```

- [ ] **Step 5: Add the filter chip**

Locate the chip row around line 317 (last chip before the closing `</div>`):

```tsx
        <button className={`chip todo ${noOutOnly ? "on" : ""}`} title="EGPs sem nenhum output no corpus (consumidores puros) — candidatos a revisão de escopo/objetivo"
          onClick={() => setNoOutOnly((v) => !v)}>⊘ Sem outputs: {noOutCount}</button>
      </div>
```

Add a new chip right before `</div>`:

```tsx
        <button className={`chip todo ${brokenOnly ? "on" : ""}`} title="EGPs com pelo menos 1 vínculo quebrado — declararam não depender de algum input compartilhado"
          onClick={() => setBrokenOnly((v) => !v)}>⛓️‍💥 Vínculos quebrados: {brokenCount}</button>
      </div>
```

- [ ] **Step 6: Add CSV column**

Locate lines 226-247 (the `cols` array in `exportCsv`). After `{ header: "Sem fonte", get: (r) => r.n_sem_fonte },` add:

Find:
```tsx
      { header: "Sem fonte", get: (r) => r.n_sem_fonte },
      { header: "Etapa", get: (r) => r.etapa },
```

Replace with:
```tsx
      { header: "Sem fonte", get: (r) => r.n_sem_fonte },
      { header: "Vínculos quebrados", get: (r) => r.n_links_broken ?? 0 },
      { header: "Etapa", get: (r) => r.etapa },
```

- [ ] **Step 7: Type-check and verify visually**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
```
Expected: no errors.

Restart `local_app.sh`; open the EGPs tab; verify the new chip appears with a count. Break a vínculo in the EGP detail (Task 17) and confirm the badge appears next to the EGP name on the EGPs tab after cache invalidation.

- [ ] **Step 8: Commit**

```bash
git add egps_analysis/app/frontend/src/components/ReadinessView.tsx
git commit -m "feat(app): aba EGPs — badge + filtro + CSV para vínculos quebrados"
```

---

## Task 19 — Frontend: InputDrawer — badge + count discount

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/InputDrawer.tsx`

**Interfaces:**
- Consumes: `InputUsageEgp.link_broken` (Task 15).
- Produces: consumers list shows greyed row + `⛓️‍💥` badge for broken links; heading count subtracts them.

- [ ] **Step 1: Compute broken count and adjust heading**

Locate:
```tsx
  const egps = usage.data?.egps ?? [];
  const produtores = usage.data?.produtores ?? [];
```

Add right after:
```tsx
  const brokenCount = egps.filter((e) => e.link_broken).length;
  const activeCount = egps.length - brokenCount;
```

- [ ] **Step 2: Update the heading and the row rendering**

Locate:
```tsx
        <h4>Usado por {egps.length || row.qtd_projetos} EGPs</h4>
        {usage.isFetching && <div className="muted">carregando…</div>}
        {usage.error && <div className="error">{String(usage.error)}</div>}
        <div className="drawer-egps">
          {egps.map((e) => (
            <button key={e.projeto} className="drawer-egp" title={e.projeto} onClick={() => onOpenEgp(e.projeto)}>
              <span className="de-name">{Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}{isIndi(e.escopo_indi) ? " ◆" : ""}</span>
              <span className="de-meta">{e.area ?? "?"} · {mesTag(mesOf.get(e.projeto))}</span>
            </button>
          ))}
          {!usage.isFetching && egps.length === 0 && <div className="muted">— nenhum EGP encontrado</div>}
        </div>
```

Replace with:
```tsx
        <h4>
          Usado por {activeCount || row.qtd_projetos} EGP{activeCount === 1 ? "" : "s"}
          {brokenCount > 0 && <span className="muted" style={{ fontSize: 12, fontWeight: 400, marginLeft: 6 }}>+ {brokenCount} com vínculo quebrado</span>}
        </h4>
        {usage.isFetching && <div className="muted">carregando…</div>}
        {usage.error && <div className="error">{String(usage.error)}</div>}
        <div className="drawer-egps">
          {egps.map((e) => (
            <button key={e.projeto} className="drawer-egp" title={e.projeto}
              style={{ opacity: e.link_broken ? 0.55 : 1 }}
              onClick={() => onOpenEgp(e.projeto)}>
              <span className="de-name">
                {Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}{isIndi(e.escopo_indi) ? " ◆" : ""}
                {e.link_broken && <span style={{ marginLeft: 4 }} title="Vínculo quebrado — este EGP declarou não depender deste input">⛓️‍💥</span>}
              </span>
              <span className="de-meta">{e.area ?? "?"} · {mesTag(mesOf.get(e.projeto))}</span>
            </button>
          ))}
          {!usage.isFetching && egps.length === 0 && <div className="muted">— nenhum EGP encontrado</div>}
        </div>
```

- [ ] **Step 3: Type-check**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/components/InputDrawer.tsx
git commit -m "feat(app): InputDrawer — badge + desconto de vínculos quebrados"
```

---

## Task 20 — Frontend: OutputsDrawer — badge + count discount

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/OutputsDrawer.tsx`

**Interfaces:**
- Consumes: `OutputUsageEgp.link_broken` (Task 15).
- Produces: `Consumido por N EGPs` header discounts broken; broken rows greyed with badge.

- [ ] **Step 1: Compute broken count**

Locate:
```tsx
  const produtores = detail.data?.produtores ?? [];
  const consumidores = detail.data?.consumidores ?? [];
```

Add right after:
```tsx
  const brokenConsumers = consumidores.filter((c) => c.link_broken).length;
  const activeConsumers = consumidores.length - brokenConsumers;
```

- [ ] **Step 2: Update consumidores heading and row rendering**

Locate:
```tsx
        <h4>Consumido por {consumidores.length} EGP{consumidores.length === 1 ? "" : "s"}</h4>
        {detail.isFetching && <div className="muted">carregando…</div>}
        {detail.error && <div className="error">{String(detail.error)}</div>}
        <div className="drawer-egps">
          {consumidores.map((e) => (
            <button key={e.projeto} className="drawer-egp" title={e.projeto} onClick={() => onOpenEgp(e.projeto)}>
              <span className="de-name">{Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}{isIndi(e.escopo_indi) ? " ◆" : ""}</span>
              <span className="de-meta">{e.area ?? "?"} · {e.onda ?? "—"}</span>
            </button>
          ))}
          {!detail.isFetching && consumidores.length === 0 && (
            <div className="muted">— nenhum consumidor — output terminal</div>
          )}
        </div>
```

Replace with:
```tsx
        <h4>
          Consumido por {activeConsumers} EGP{activeConsumers === 1 ? "" : "s"}
          {brokenConsumers > 0 && <span className="muted" style={{ fontSize: 12, fontWeight: 400, marginLeft: 6 }}>+ {brokenConsumers} com vínculo quebrado</span>}
        </h4>
        {detail.isFetching && <div className="muted">carregando…</div>}
        {detail.error && <div className="error">{String(detail.error)}</div>}
        <div className="drawer-egps">
          {consumidores.map((e) => (
            <button key={e.projeto} className="drawer-egp" title={e.projeto}
              style={{ opacity: e.link_broken ? 0.55 : 1 }}
              onClick={() => onOpenEgp(e.projeto)}>
              <span className="de-name">
                {Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}{isIndi(e.escopo_indi) ? " ◆" : ""}
                {e.link_broken && <span style={{ marginLeft: 4 }} title="Vínculo quebrado — este EGP declarou não depender deste output">⛓️‍💥</span>}
              </span>
              <span className="de-meta">{e.area ?? "?"} · {e.onda ?? "—"}</span>
            </button>
          ))}
          {!detail.isFetching && consumidores.length === 0 && (
            <div className="muted">— nenhum consumidor — output terminal</div>
          )}
        </div>
```

- [ ] **Step 3: Type-check and commit**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
git add egps_analysis/app/frontend/src/components/OutputsDrawer.tsx
git commit -m "feat(app): OutputsDrawer — badge + desconto de vínculos quebrados"
```

---

## Task 21 — Frontend: HistoryView — parse `link_broken@<chave>` + fonteCls

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/HistoryView.tsx`

**Interfaces:**
- Consumes: audit rows with `fonte='Vínculos'` and `campo='link_broken@<chave>'` from Task 13.
- Produces: history table renders these rows with a friendly `Vínculo (EGP↔Input): <chave>` label and a distinct source badge.

- [ ] **Step 1: Extend `CAMPO_LABEL` handling and `fonteCls`**

Locate lines 6-19:
```tsx
const CAMPO_LABEL: Record<string, string> = {
  status_humano: "Status",
  responsavel: "Responsável",
  observacao: "Observação",
  etapa: "Etapa",
  status: "Status",
  escopo: "Escopo",
  ComBV: "Validação BV",
};
const artifactOf = (chave: string) => (chave.includes("::") ? chave.split("::").slice(1).join("::") : chave);
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
// nome de exibição do artefato conforme a aba: Monitoramento usa a chave do input; EGPs/Escopo usam o nome curto do EGP.
const artefatoLabel = (r: AuditRow) => (r.fonte === "Monitoramento" ? artifactOf(r.chave_canonica) : shortName(r.chave_canonica));
const fonteCls = (f: string) => (f === "Monitoramento" ? "f-mon" : f === "EGPs" ? "f-egp" : "f-esc");
```

Replace with:
```tsx
const CAMPO_LABEL: Record<string, string> = {
  status_humano: "Status",
  responsavel: "Responsável",
  observacao: "Observação",
  etapa: "Etapa",
  status: "Status",
  escopo: "Escopo",
  ComBV: "Validação BV",
};
const artifactOf = (chave: string) => (chave.includes("::") ? chave.split("::").slice(1).join("::") : chave);
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
// nome de exibição do artefato conforme a aba: Monitoramento usa a chave do input; EGPs/Escopo/Vínculos usam o nome curto do EGP.
const artefatoLabel = (r: AuditRow) => (r.fonte === "Monitoramento" ? artifactOf(r.chave_canonica) : shortName(r.chave_canonica));
const fonteCls = (f: string) => (
  f === "Monitoramento" ? "f-mon" :
  f === "EGPs" ? "f-egp" :
  f === "Vínculos" ? "f-vinc" : "f-esc"
);
// Vínculo (EGP↔Input): o campo vem como `link_broken@<chave_canonica>` do backend (não
// há coluna livre no /api/audit shape); parseia o sufixo para exibir qual input.
const campoLabel = (campo: string) => {
  if (campo.startsWith("link_broken@")) {
    const chave = campo.slice("link_broken@".length);
    return `Vínculo (EGP↔Input): ${artifactOf(chave)}`;
  }
  return CAMPO_LABEL[campo] ?? campo;
};
// Vínculos: valores vêm serializados como "True"/"False" — render mais amigável.
const valorVinculoLabel = (v: string | null | undefined) => {
  if (v === "True" || v === "true") return "Quebrado";
  if (v === "False" || v === "false") return "Linkado";
  return v || "—";
};
```

- [ ] **Step 2: Use the new helpers in the row rendering**

Locate lines 59-63 in the history table body:
```tsx
                <div>{CAMPO_LABEL[r.campo] ?? r.campo}</div>
                <div className="c-old">{r.valor_antigo || "—"}</div>
                <div className="c-new">{r.valor_novo || "—"}</div>
```

Replace with:
```tsx
                <div>{campoLabel(r.campo)}</div>
                <div className="c-old">{r.fonte === "Vínculos" ? valorVinculoLabel(r.valor_antigo) : (r.valor_antigo || "—")}</div>
                <div className="c-new">{r.fonte === "Vínculos" ? valorVinculoLabel(r.valor_novo) : (r.valor_novo || "—")}</div>
```

- [ ] **Step 3: Add CSS class for the new fonte**

In `styles.css`, search for `.f-mon` / `.f-egp` / `.f-esc` selectors and add `.f-vinc`:

```bash
cd egps_analysis/app/frontend/src && grep -n "\.f-mon\|\.f-egp\|\.f-esc" styles.css
```

Locate the block that styles the source badges (usually near the `.hist-fonte` class). Add:

```css
.hist-fonte.f-vinc { background: rgba(180, 83, 9, 0.15); color: #92400e; }
```

Use tones consistent with `.rd-vinc` in Task 17. If dark-theme variables exist next to `.f-esc`/etc., add a matching rule under `@media (prefers-color-scheme: dark)` mirroring what the neighboring classes do.

- [ ] **Step 4: Update the hint text**

Locate line 44:
```tsx
      <div className="lin-hint">
        Auditoria de <b>todas as abas</b>: edições de input (Monitoramento), etapa/status de EGP (EGPs) e add/remove de escopo (Escopo) — cada uma com autor, horário e a <b>aba</b> de origem.
      </div>
```

Replace with:
```tsx
      <div className="lin-hint">
        Auditoria de <b>todas as abas</b>: edições de input (Monitoramento), etapa/status de EGP (EGPs), add/remove de escopo (Escopo) e quebra/restauração de vínculo per-(EGP, Input) (Vínculos) — cada uma com autor, horário e a <b>aba</b> de origem.
      </div>
```

- [ ] **Step 5: Type-check and commit**

```bash
cd egps_analysis/app/frontend && npx tsc --noEmit
git add egps_analysis/app/frontend/src/components/HistoryView.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): Histórico — fonte 'Vínculos' + label + tema"
```

---

## Task 22 — E2E manual verification + emoji-render acceptance gate

**Files:**
- Only manual verification; no code changes.

**Interfaces:**
- Consumes: everything from Tasks 1-21.

- [ ] **Step 1: Sync dev from prod**

Run:
```bash
cd egps_analysis/app && python3 sync_dev.py --yes
```
Expected: `✔ concluído` with N tables synced; verify `sas_egp_input_link` is in the copied list and `sas_egp_input_link_audit` is NOT (Task 14).

- [ ] **Step 2: Start the app locally**

```bash
cd egps_analysis/app && ./local_app.sh
```

- [ ] **Step 3: Emoji-render acceptance gate**

Open the app in **Chrome** and **Firefox** in light + dark theme. Navigate to any EGP detail. Confirm:

- `🔗` on linked inputs renders as a single glyph, size consistent with the surrounding UI.
- Click one row's icon (needs to be in `bv_users` group) — icon flips to `⛓️‍💥` and renders as a single glyph, NOT as two disconnected emoji.

If the broken glyph renders poorly on either browser, **do NOT commit the frontend PR yet** — instead:

1. Implement the SVG fallback documented in the spec §5.1 (create `components/LinkIcon.tsx`).
2. Replace every emoji literal `🔗` / `⛓️‍💥` in `EgpDetailPanel.tsx`, `ReadinessView.tsx`, `InputDrawer.tsx`, `OutputsDrawer.tsx`, `HistoryView.tsx` with `<LinkIcon />` / `<LinkIcon broken />`.
3. Repeat the visual check.

If both glyphs render cleanly, continue.

- [ ] **Step 4: Full E2E scenario walk-through**

Pick an EGP that shares an input with another EGP (any `chave_canonica` where `qtd_projetos > 1` in `sas_inputs_monitor`).

1. **Break the link** in EGP_A's detail. Verify:
   - Row greys out; icon becomes `⛓️‍💥`.
   - Header counter drops by 1 (`Inputs / necessidades: N-1`).
   - Row moves to the bottom of the inputs list.
   - `% modernizado` for EGP_A recomputes (higher, since the pending input dropped out).
   - `Faltam` decreases.

2. **Aba EGPs**: verify EGP_A now shows `⛓️‍💥 1` badge next to its name. EGP_B is unchanged.

3. **Filter chip**: click `⛓️‍💥 Vínculos quebrados` — the list filters to just EGP_A (plus any others already broken).

4. **Aba Inputs**: find `Input_1`. Open its drawer.
   - Consumers heading shows count minus 1 with a "+ 1 com vínculo quebrado" note.
   - EGP_A is still listed but greyed with `⛓️‍💥`.
   - Global `status_humano` unchanged.

5. **Aba Histórico**: verify a new row with `Aba = Vínculos`, `Artefato = <EGP_A name>`, `Campo = Vínculo (EGP↔Input): <input chave>`, `De = Linkado`, `Para = Quebrado`.

6. **Aba Priorização**: verify EGP_A's `+Inputs` count decreased. If EGP_A had SAS/local-only pending and this was the last blocker, verify 🔒 dropped.

7. **CSV export from Inputs tab**: click ⬇ Exportar CSV. Open the CSV — the row `(Input_1, EGP_A)` must NOT appear. `(Input_1, EGP_B)` still appears.

8. **CSV export from EGPs tab**: click ⬇ Exportar CSV. Locate EGP_A's row — the new `Vínculos quebrados` column must show `1`.

9. **Restore the link**: back in EGP_A detail, click `⛓️‍💥` to restore. Everything reverses:
   - Row un-greys, icon back to `🔗`.
   - Header counter back to N.
   - Badge disappears from EGPs tab.
   - New Histórico row: `Quebrado → Linkado`.

- [ ] **Step 5: Cache invalidation gate**

While logged in as a bv_users member, break a link on EGP_A. Immediately (< 5 seconds later) refresh the EGPs tab. The badge must appear — do NOT wait 5 minutes. If it takes >5s, `_lineage_gen` isn't bumping. Diagnose in `patch_egp_input_link` (Task 3, Step 3) — the `_lineage_gen += 1` must be inside the `if changed:` branch.

- [ ] **Step 6: Non-gestão behavior**

Log out and log in as a non-`bv_users` user (or temporarily set `is_gestao` false in your local session). Open the same EGP detail. Verify:
- The `Vínculo` column still shows the icon.
- Clicking a linked row's icon does NOT toggle.
- No error is thrown; the icon is a `<span>` not a `<button>`.

- [ ] **Step 7: Commit the manual verification log**

Create `docs/superpowers/plans/2026-07-23-per-egp-input-link-management-VERIFY.md` with a checklist of the above 6 steps, marked done and dated. Then:

```bash
git add docs/superpowers/plans/2026-07-23-per-egp-input-link-management-VERIFY.md
git commit -m "docs: log da verificação manual (per-EGP input link)"
```

---

## Task 23 — Open PR

**Files:** No code changes; only git/gh operations.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/input-link-management
```

- [ ] **Step 2: Confirm CI is green**

Wait for Bitbucket Pipelines to finish; if red, address the failure before opening the PR.

- [ ] **Step 3: Open the PR**

Ask the user for approval before opening. Once approved, open a PR with the summary from the spec's §1 (Problem) and §2 (Decisions), and link the design doc and this plan. Include the manual verification log path.

**Do NOT deploy prod yourself.** Merge = auto-deploy via Bitbucket Pipelines (per ONBOARDING). Confirm the user wants to merge.

---

## Self-Review Notes

- **Spec coverage:** every decision in the spec's §2 table maps to a task:
  - Propagation → predicates + all Task 5–13 wire-ups.
  - Permissions → Task 3 (`_require_gestao`), Task 17 (`isGestao` gate).
  - No reason field → nowhere; enforced by omission.
  - Non-gestão badge visible → Task 17 Step 5 (`<span>` branch).
  - Filter visible to all → Task 18 (no `isGestao` gate on the chip).
  - Icons → Task 17 Step 5 + Task 22 acceptance gate + fallback path.
  - Sort broken to bottom → Task 17 Step 2 (`sortedInputs`).
  - Header shows only linked → Task 17 Step 3.
  - CSV drops broken pairs (Inputs) → Task 11 (`/api/inputs-egps` filter).
  - CSV EGPs column → Task 18 Step 6.
  - Audit → Task 13 + Task 21.
  - Publish never touches new tables → Task 1 (backend-only DDL).
  - sync_dev updated → Task 14.
  - Orphaned EGPs still visible → Task 5 (`n_inputs=0` semantics + `_stub`).
  - `_lineage_gen` bump → Task 3 + verification in Task 22 Step 5.
- **Placeholder scan:** every step contains actual code or exact commands; no TBD.
- **Type consistency:** `EgpInput.link_broken?`, `ReadinessRow.n_links_broken?`, `InputUsageEgp.link_broken?`, `OutputUsageEgp.link_broken?` are declared in Task 15 and consumed exactly by the same names in Tasks 17-21. Backend field names (`link_broken`, `n_links_broken`) match the frontend types.
- **Scope check:** single feature, one plan is appropriate.

---

## Ponytail notes (deliberate simplifications)

- **No orphan cleanup job.** Broken links pointing at a (projeto, chave) that fell out of `sas_egp_inputs` are harmless — the LEFT JOIN doesn't match. If the pair reappears in a future publish, the previous state resurfaces (which is what analysts probably want).
- **State stored as "row present = broken"** — not `link_broken=false` rows. Tables stay tiny (expected < 100 rows), predicates use `coalesce(l.link_broken, false)` which is short-circuit-safe.
- **Predicate default `lnk="false"`** — callers that don't join the link table get identical old behavior. Zero-risk migration.
- **No new fonte-of-truth join in `_vias_resolvidas`** — lineage resolution is global; a broken link between EGP_A and Input_1 must NOT release a shared upstream dependency for EGP_B.
- **No new type for the audit row** — reuse `AuditRow`, encode chave inside `campo` (`link_broken@<chave>`). The `/api/audit` shape stays stable.
- **No changes to `pipeline.ts` or `inputs.ts` `effStatus`** — status stays global; link_broken is a per-EGP overlay, orthogonal.
