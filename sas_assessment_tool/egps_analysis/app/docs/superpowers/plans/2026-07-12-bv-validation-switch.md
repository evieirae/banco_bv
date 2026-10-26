# Switch "Com BV" + coluna "Dias em validação (BV)" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track, per EGP/Input, whether the ball is in BV's court (a "Com BV" toggle) and how many business days it has spent there ("Dias em validação (BV)"), with an append-only audit log and admin-only retroactive correction.

**Architecture:** Append-only Delta table `sas_gestao_bv` (one row per toggle) is the source of truth. The everyday toggle (`bv_users`) appends a today-dated event; retroactive corrections (delete an event, or append a past-dated one) are gated to `bv_admins`. The running day count is computed on the **frontend** from the event log, reusing `diasUteis`/`FERIADOS_BR` so the holiday list stays single-sourced.

**Tech Stack:** FastAPI + Databricks SQL (Statement Execution) backend; React + TypeScript + `@tanstack/react-query` frontend; `diasUteis.ts` for business-day math.

## Global Constraints

- Day unit: **business days** (`diasUteis`, excludes weekends + `FERIADOS_BR`). Verbatim from spec.
- Interval counting: closed `[entrega, retorno)` (return day excluded → same-day = 0); open interval `[entrega, hoje]` inclusive. Verbatim from spec.
- No "deadline reached" visual cue (user decision — keep UI clean).
- Booleans from Databricks Statement Execution arrive as the **strings** `"true"`/`"false"` — always parse with `str(x).lower() == "true"`, never Python truthiness.
- Writes gated: everyday toggle needs `_require_gestao()` (bv_users); corrections (DELETE, or POST with explicit `data`) need `_require_admin()` (bv_admins).
- No new dependencies (frontend has no test runner; do not add one).
- Never `git push` or touch prod; commits only, no `Co-Authored-By` (repo CLAUDE.md).

---

## File Structure

- `backend/main.py` — new `T_GBV` constant, `_is_admin`/`_require_admin`, table DDL in `_ensure_gestao_tables`, BV hydration in `_gestao_extras`/`gestao_rows`, `POST`/`DELETE /api/gestao/bv`, `is_admin` in `/api/config`.
- `frontend/src/diasUteis.ts` — `ehDiaUtil` + `diasEmValidacaoBV` pure helpers.
- `frontend/src/types.ts` — `AppConfig.is_admin`.
- `frontend/src/gestaoApi.ts` — `BVEvento` type, `GestaoRow.bvEventos`, `setBV`/`deleteBV` in interface + delta + mock.
- `frontend/src/components/GestaoMigracao.tsx` — "Com BV" toggle column + "Dias em validação (BV)" column + sort keys + mutation.
- `frontend/src/components/GestaoStatusPanel.tsx` — "Validação BV" correction section (admin-gated).
- `frontend/src/styles.css` — `.gm-bv-toggle` switch styles.

---

## Task 1: Backend — admin group check + `is_admin` in config

**Files:**
- Modify: `backend/main.py` (near `_is_gestao` ~395; `/api/config` ~1316)

**Interfaces:**
- Produces: `_is_admin() -> bool`, `_require_admin()`, and `"is_admin"` key in the `/api/config` JSON.

- [ ] **Step 1: Add `_is_admin`/`_require_admin` after `_require_gestao` (~line 410)**

```python
ADMIN_GROUPS = ("bv_admins",)  # correção retroativa da validação BV (reescreve histórico)


def _is_admin():
    """True se o usuário logado (OBO) pertence a bv_admins. Mesmo mecanismo de _is_gestao
    (is_account_group_member/is_member via SQL, como o usuário — sem SCIM)."""
    try:
        conds = " OR ".join(
            f"is_account_group_member({sql_lit(g)}) OR is_member({sql_lit(g)})" for g in ADMIN_GROUPS)
        r = run_sql(f"SELECT ({conds}) AS m")
        return bool(r and (r[0]["m"] is True or str(r[0]["m"]).lower() == "true"))
    except HTTPException:
        return False


def _require_admin():
    if not _is_admin():
        raise HTTPException(403, "Restrito ao grupo de administração (bv_admins).")
```

- [ ] **Step 2: Add `is_admin` to `/api/config` return (~line 1324)**

Change the return dict in `config()` from:

```python
            "areas": areas, "scope": FQ, "is_gestao": _is_gestao()}
```

to:

```python
            "areas": areas, "scope": FQ, "is_gestao": _is_gestao(), "is_admin": _is_admin()}
```

- [ ] **Step 3: Verify the app still imports (syntax check)**

Run: `cd egps_analysis/app && python -c "import ast; ast.parse(open('backend/main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): _is_admin (bv_admins) + is_admin no /api/config"
```

---

## Task 2: Backend — `sas_gestao_bv` table, row hydration, POST/DELETE

**Files:**
- Modify: `backend/main.py` (constants ~72; `_ensure_gestao_tables` ~2489; `_gestao_extras`/`gestao_rows` ~2499; new endpoints after `gestao_status_add` ~2597)

**Interfaces:**
- Consumes: `_ensure_gestao_tables`, `_require_gestao`, `_require_admin`, `sql_lit`, `run_sql`, `uuid`, `re`.
- Produces:
  - `GET /api/gestao/rows` rows now include `bvEventos: [{id, comBv, data, autor}]` (ascending by `ts`).
  - `POST /api/gestao/bv {entity, id, comBv, data?}` → `{ok, id}`.
  - `DELETE /api/gestao/bv?id=<eventId>` → `{ok}`.

- [ ] **Step 1: Add the `T_GBV` constant next to `T_GDT` (~line 73)**

```python
T_GBV = f"{FQ}.sas_gestao_bv"       # Gestão: log append-only do switch "Com BV" (nunca dropada)
```

- [ ] **Step 2: Create the table in `_ensure_gestao_tables` (after the `T_GDT` CREATE, ~line 2495)**

```python
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_GBV} ("
            f"id STRING, entity STRING, entity_id STRING, com_bv BOOLEAN, data STRING, "
            f"autor STRING, ts STRING) USING DELTA", want_rows=False)
```

- [ ] **Step 3: Hydrate rows with BV events — extend `_gestao_extras` (~line 2499)**

Replace the whole `_gestao_extras` function with:

```python
def _gestao_extras(entity):
    """Datas + texto do ÚLTIMO status + eventos do switch "Com BV" por entity_id."""
    _ensure_gestao_tables()
    datas = {r["entity_id"]: r for r in run_sql(
        f"SELECT entity_id, inicio, fim_conversao, fim FROM {T_GDT} "
        f"WHERE entity = {sql_lit(entity)}")}
    ultimos = {r["entity_id"]: r.get("texto") for r in run_sql(
        f"SELECT entity_id, texto FROM (SELECT entity_id, texto, "
        f"row_number() OVER (PARTITION BY entity_id ORDER BY ts DESC) AS rn "
        f"FROM {T_GST} WHERE entity = {sql_lit(entity)}) t WHERE rn = 1")}
    bv = {}
    for r in run_sql(f"SELECT id, entity_id, com_bv, data, autor FROM {T_GBV} "
                     f"WHERE entity = {sql_lit(entity)} ORDER BY ts"):
        bv.setdefault(r["entity_id"], []).append(
            {"id": r["id"], "comBv": str(r["com_bv"]).lower() == "true",
             "data": r["data"], "autor": r.get("autor")})
    return datas, ultimos, bv
```

- [ ] **Step 4: Thread `bv` through `gestao_rows` (~line 2519)**

Change `datas, ultimos = _gestao_extras(entity)` to:

```python
    datas, ultimos, bv = _gestao_extras(entity)
```

And in the inner `_row(...)` builder, add `bvEventos` to the returned dict (after `resumoStatus`):

```python
                "resumoStatus": ultimos.get(rid) or None, "egps": egps,
                "bvEventos": bv.get(rid, [])}
```

- [ ] **Step 5: Add the POST/DELETE endpoints after `gestao_status_add` (~line 2597)**

```python
class GestaoBV(BaseModel):
    entity: str
    id: str
    comBv: bool
    data: str | None = None   # YYYY-MM-DD; ausente = hoje (bv_users). Presente = correção (bv_admins).


@app.post("/api/gestao/bv")
def gestao_bv_add(p: GestaoBV):
    """Registra 1 toggle do switch "Com BV" (append-only). Sem `data` = hoje (SP), aberto a
    bv_users. Com `data` (retroativa) = correção, restrita a bv_admins."""
    if p.entity not in ("egp", "input"):
        raise HTTPException(400, "entity deve ser egp|input")
    _require_gestao()
    if p.data is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.data):
            raise HTTPException(400, "data deve ser YYYY-MM-DD")
        _require_admin()   # data explícita = reescrita de histórico
    _ensure_gestao_tables()
    bid = uuid.uuid4().hex
    data_lit = (sql_lit(p.data) if p.data is not None else
                "date_format(from_utc_timestamp(current_timestamp(), 'America/Sao_Paulo'), 'yyyy-MM-dd')")
    run_sql(
        f"INSERT INTO {T_GBV} (id, entity, entity_id, com_bv, data, autor, ts) VALUES ("
        f"{sql_lit(bid)}, {sql_lit(p.entity)}, {sql_lit(p.id)}, {str(p.comBv).lower()}, "
        f"{data_lit}, current_user(), cast(current_timestamp() AS STRING))",
        want_rows=False)
    return {"ok": True, "id": bid}


@app.delete("/api/gestao/bv")
def gestao_bv_del(id: str):
    """Remove 1 evento do log "Com BV" pelo id. Correção — restrita a bv_admins (hard-delete)."""
    _require_gestao()
    _require_admin()
    _ensure_gestao_tables()
    run_sql(f"DELETE FROM {T_GBV} WHERE id = {sql_lit(id)}", want_rows=False)
    return {"ok": True}
```

- [ ] **Step 6: Syntax check**

Run: `cd egps_analysis/app && python -c "import ast; ast.parse(open('backend/main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Live smoke test against dev (read-only-ish; the dev backend is running on :8000 with profile bv)**

The dev backend from this session is up. Restart it if needed (Task-agnostic), then:
Run: `curl -s "http://localhost:8000/api/gestao/rows?entity=egp" | python3 -c "import sys,json; d=json.load(sys.stdin); r=d['rows'][0]; print('bvEventos' in r, type(r['bvEventos']))"`
Expected: `True <class 'list'>`
(If `curl` to localhost is blocked by policy, verify instead by opening the Gestão tab in the running dev app and confirming no 500 in the backend log.)

- [ ] **Step 8: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): tabela sas_gestao_bv + endpoints POST/DELETE /api/gestao/bv + hidratação das linhas"
```

---

## Task 3: Frontend — business-day counting helper

**Files:**
- Modify: `frontend/src/diasUteis.ts`

**Interfaces:**
- Consumes: existing `diasUteis(inicio, fim, feriados?)`, `FERIADOS_BR`.
- Produces:
  - `ehDiaUtil(data: string, feriados?: readonly string[]): boolean`
  - `diasEmValidacaoBV(eventos: {comBv: boolean; data: string}[], hoje: string, feriados?: readonly string[]): number`

- [ ] **Step 1: Add both helpers at the end of `diasUteis.ts` (after `fmtBR`)**

```ts
// Dia útil? (seg–sex e não feriado). ISO "YYYY-MM-DD".
export function ehDiaUtil(data: string, feriados: readonly string[] = FERIADOS_BR): boolean {
  const dow = new Date(`${data}T12:00:00Z`).getUTCDay();
  return dow !== 0 && dow !== 6 && !feriados.includes(data);
}

// Total de dias úteis que o switch "Com BV" ficou ON, a partir do log de eventos.
// `eventos` em ordem ASCENDENTE por data; `comBv` = estado APÓS o evento.
// Intervalo fechado [entrega, retorno): o dia de retorno NÃO conta (mesmo dia = 0).
// Intervalo aberto (ainda ON) [entrega, hoje]: hoje conta (a bola ainda está com o BV).
// Eventos redundantes (ON sobre ON, OFF sobre OFF) são ignorados.
export function diasEmValidacaoBV(
  eventos: { comBv: boolean; data: string }[],
  hoje: string,
  feriados: readonly string[] = FERIADOS_BR,
): number {
  let total = 0;
  let abertoDesde: string | null = null;
  for (const ev of eventos) {
    if (ev.comBv && abertoDesde === null) {
      abertoDesde = ev.data;
    } else if (!ev.comBv && abertoDesde !== null) {
      const d = diasUteis(abertoDesde, ev.data, feriados) ?? 0;      // inclusivo nas 2 pontas
      total += Math.max(0, d - (ehDiaUtil(ev.data, feriados) ? 1 : 0)); // exclui o dia de retorno
      abertoDesde = null;
    }
  }
  if (abertoDesde !== null) total += diasUteis(abertoDesde, hoje, feriados) ?? 0;
  return total;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: exit 0, no output.

- [ ] **Step 3: Verify the logic with concrete cases (no TS runner in repo — `ponytail:` documented manual check).**

The dev app is running. Open the browser console on http://localhost:5173 and paste (module is bundled, so import via the app's module graph is not directly available in console — instead paste the function bodies inline). Confirm each assertion prints `true`. Reference dates (July 2026, no BR holidays): 06=Mon,07=Tue,08=Wed,09=Thu,10=Fri,03=Fri.

```js
// paste ehDiaUtil + diasEmValidacaoBV bodies, then:
const H = FERIADOS_BR; const on = (d)=>({comBv:true,data:d}), off=(d)=>({comBv:false,data:d});
console.log(
  diasEmValidacaoBV([on("2026-07-06"),off("2026-07-06")], "2026-07-31") === 0,       // mesmo dia = 0
  diasEmValidacaoBV([on("2026-07-06"),off("2026-07-08")], "2026-07-31") === 2,       // [Mon,Wed) = Mon,Tue
  diasEmValidacaoBV([on("2026-07-03"),off("2026-07-06")], "2026-07-31") === 1,       // Fri; fim de semana não conta
  diasEmValidacaoBV([on("2026-07-06"),off("2026-07-08"),on("2026-07-08"),off("2026-07-10")], "2026-07-31") === 4, // sem dupla contagem na fronteira
  diasEmValidacaoBV([on("2026-07-06")], "2026-07-08") === 3,                          // aberto até qua, inclusivo
);
```
Expected: `true true true true true`

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/diasUteis.ts
git commit -m "feat(app): helpers ehDiaUtil e diasEmValidacaoBV (contagem de dias úteis com BV)"
```

---

## Task 4: Frontend — data layer (types + gestaoApi delta + mock + AppConfig)

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/gestaoApi.ts`

**Interfaces:**
- Consumes: `GestaoRow`, `GestaoDataSource`, delta `j<T>` helper, mock `db`/`seq`.
- Produces:
  - `AppConfig.is_admin?: boolean`
  - `BVEvento { id: string; comBv: boolean; data: string; autor: string | null }`
  - `GestaoRow.bvEventos: BVEvento[]`
  - `GestaoDataSource.setBV(entity, id, comBv, data?)` and `.deleteBV(id)` (delta + mock)

- [ ] **Step 1: Add `is_admin` to `AppConfig` in `types.ts` (after `is_gestao`, ~line 34)**

```ts
  is_gestao?: boolean;   // usuário pertence ao grupo bv_users (vê a aba Gestão)
  is_admin?: boolean;    // usuário pertence a bv_admins (correção retroativa da validação BV)
```

- [ ] **Step 2: Add `BVEvento` + `bvEventos` in `gestaoApi.ts` (near `GestaoRow`, ~line 17)**

Add the interface before `GestaoRow`:

```ts
export interface BVEvento {
  id: string;
  comBv: boolean;
  data: string;         // "YYYY-MM-DD"
  autor: string | null; // email de quem registrou
}
```

And add the field inside `GestaoRow` (after `egps`):

```ts
  egps: string[];                // EGPs consumidores (input); no egp = [id]
  bvEventos: BVEvento[];         // log append-only do switch "Com BV" (asc por data)
```

- [ ] **Step 3: Add `setBV`/`deleteBV` to the `GestaoDataSource` interface (after `setDates`, ~line 40)**

```ts
  setBV(entity: EntityType, id: string, comBv: boolean, data?: string): Promise<void>;
  deleteBV(id: string): Promise<void>;
```

- [ ] **Step 4: Implement in `deltaGestaoApi` (after `setDates`, before `getHolidays`)**

```ts
  setBV: async (entity, id, comBv, data) => {
    await fetch("api/gestao/bv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity, id, comBv, ...(data ? { data } : {}) }),
    }).then(j<{ ok: boolean; id: string }>);
  },
  deleteBV: async (id) => {
    await fetch(`api/gestao/bv?id=${encodeURIComponent(id)}`, { method: "DELETE" })
      .then(j<{ ok: boolean }>);
  },
```

- [ ] **Step 5: Update the mock — seed empty `bvEventos` and add a module-level `bvDb`**

In the mock section, extend the `db` seeding. In `seed(...)` where the row object is built (`db[entity].set(s.id, { ... egps: s.egps ?? [s.id] })`), add `bvEventos: []` to that object:

```ts
      egps: s.egps ?? [s.id],
      bvEventos: [],
```

Add a mock BV store next to `statusDb` (~line 197):

```ts
const bvDb: Record<EntityType, Map<string, BVEvento[]>> = { egp: new Map(), input: new Map() };
```

- [ ] **Step 6: Implement `setBV`/`deleteBV` in `mockGestaoApi` (after `setDates`, before `getHolidays`)**

```ts
  async setBV(entity, id, comBv, data) {
    await delay(200);
    const row = db[entity].get(id);
    if (!row) throw new Error(`registro não encontrado: ${id}`);
    const dia = data ?? hojeSP();
    const ev: BVEvento = { id: `bv${++seq}`, comBv, data: dia, autor: "lucas.muller@indicium.tech" };
    const list = [...(bvDb[entity].get(id) ?? []), ev].sort((a, b) => (a.data < b.data ? -1 : 1));
    bvDb[entity].set(id, list);
    row.bvEventos = list.map((e) => ({ ...e }));
  },
  async deleteBV(id) {
    await delay(150);
    for (const entity of ["egp", "input"] as EntityType[]) {
      for (const [rid, list] of bvDb[entity]) {
        const next = list.filter((e) => e.id !== id);
        if (next.length !== list.length) {
          bvDb[entity].set(rid, next);
          const row = db[entity].get(rid);
          if (row) row.bvEventos = next.map((e) => ({ ...e }));
        }
      }
    }
  },
```

- [ ] **Step 7: Typecheck**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: exit 0.
(`hojeSP` is already imported in `gestaoApi.ts` line 11 — `import { FERIADOS_BR, hojeSP } from "./diasUteis";` — so the mock `setBV` can call it directly. No new import needed here.)

- [ ] **Step 8: Commit**

```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/gestaoApi.ts
git commit -m "feat(app): camada de dados do switch Com BV (BVEvento, setBV/deleteBV, is_admin)"
```

---

## Task 5: Frontend — table toggle column + days column

**Files:**
- Modify: `frontend/src/components/GestaoMigracao.tsx`, `frontend/src/styles.css`

**Interfaces:**
- Consumes: `diasEmValidacaoBV` (Task 3), `GestaoRow.bvEventos` (Task 4), `gestaoApi.setBV` (Task 4).
- Produces: two new columns and a `setBV` mutation in the table.

- [ ] **Step 1: Import the helper (line 8)**

Change:
```ts
import { diasUteis, fmtBR } from "../diasUteis";
```
to:
```ts
import { diasUteis, diasEmValidacaoBV, fmtBR } from "../diasUteis";
```

- [ ] **Step 2: Add a small state-derivation helper above the component (after `HOJE_SORT`, ~line 39)**

```ts
// Estado atual do switch = comBv do evento mais recente (bvEventos vem asc por data).
const comBvAtual = (r: GestaoRow): boolean =>
  r.bvEventos.length > 0 && r.bvEventos[r.bvEventos.length - 1].comBv;
```

- [ ] **Step 3: Add two sort keys**

Change the `GestaoSortKey` union (~line 36) to include `"comBv"` and `"diasBV"`:

```ts
type GestaoSortKey =
  | "nome" | "area" | "responsavel" | "etapa"
  | "inicio" | "fimConversao" | "fim" | "dias" | "comBv" | "diasBV" | "status";
```

And add cases to `gestaoAccessor` (before `default`):

```ts
    case "comBv": return comBvAtual(r) ? 1 : 0;
    case "diasBV": return diasEmValidacaoBV(r.bvEventos, HOJE_SORT);
```

- [ ] **Step 4: Add the `setBV` mutation (after the `setDates` mutation, ~line 125)**

```ts
  const setBV = useMutation({
    mutationFn: (v: { id: string; comBv: boolean }) => gestaoApi.setBV(entity, v.id, v.comBv),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gestao", entity] }),
  });
```

- [ ] **Step 5: Add the two `<Th>` headers (between "fim" and "status", ~line 239)**

```tsx
              <Th k="comBv" label="Com BV" onSort={onSort} indicator={indicator}
                title="Ligado = a bola está com o BV (em validação). Desligado = conosco. Clique no switch de cada linha p/ alternar; clique aqui p/ ordenar." />
              <Th k="diasBV" label="Dias em validação (BV)" onSort={onSort} indicator={indicator}
                title="Total de dias úteis que a linha ficou com o BV (soma de todas as entregas). O prazo do BV é 8 dias úteis, fixo entre entregas. Correções ficam no painel lateral (só admin)." />
```

- [ ] **Step 6: Add the two `<td>` cells in the row body (between the "fim" `<td>` and the "status" `<td>`, ~line 270)**

```tsx
                <td>
                  <label className="gm-bv-toggle" title={comBvAtual(r) ? "Com o BV — clique p/ trazer p/ nós" : "Conosco — clique p/ entregar ao BV"}>
                    <input type="checkbox" checked={comBvAtual(r)} disabled={setBV.isPending}
                      onChange={(e) => setBV.mutate({ id: r.id, comBv: e.target.checked })} />
                    <span className="gm-bv-track"><span className="gm-bv-thumb" /></span>
                  </label>
                </td>
                <td className="gm-num">{diasEmValidacaoBV(r.bvEventos, hoje)}</td>
```

- [ ] **Step 7: Bump the `colSpan` of the empty/loading/cap rows**

Every `colSpan={entity === "egp" ? 9 : 8}` becomes `colSpan={entity === "egp" ? 11 : 10}` (two new columns). There are three such rows (~lines 280, 285, 288).

- [ ] **Step 8: Add the switch CSS to `styles.css` (near the other `.gm-*` rules, e.g. after `.gm-add-btn`)**

```css
/* Switch "Com BV" da tabela de Gestão (slider). Estado ON = bola com o BV. */
.gm-bv-toggle { display: inline-flex; cursor: pointer; }
.gm-bv-toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.gm-bv-track {
  width: 34px; height: 18px; border-radius: 999px; background: var(--fill-muted);
  position: relative; transition: background .15s;
}
.gm-bv-thumb {
  position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%;
  background: #fff; transition: left .15s;
}
.gm-bv-toggle input:checked + .gm-bv-track { background: var(--accent); }
.gm-bv-toggle input:checked + .gm-bv-track .gm-bv-thumb { left: 18px; }
.gm-bv-toggle input:disabled + .gm-bv-track { opacity: .5; }
```

- [ ] **Step 9: Typecheck + visual check**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: exit 0.
Then in the running dev app (Gestão tab): the two columns render; toggling the switch flips it and the row persists after refetch; "Dias em validação (BV)" shows `0` until the switch is used. Sorting by both columns works.

- [ ] **Step 10: Commit**

```bash
git add egps_analysis/app/frontend/src/components/GestaoMigracao.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): coluna switch \"Com BV\" + coluna \"Dias em validação (BV)\" na Gestão"
```

---

## Task 6: Frontend — side-panel correction section (admin-only)

**Files:**
- Modify: `frontend/src/components/GestaoStatusPanel.tsx`

**Interfaces:**
- Consumes: `api.config` (for `is_admin`), `gestaoApi.setBV`/`deleteBV`, `row.bvEventos`, `fmtBR`.
- Produces: a "Validação BV" section in the drawer (read-only list for everyone; delete + dated-add for admins).

- [ ] **Step 1: Add one import at the top of `GestaoStatusPanel.tsx`**

`fmtBR` is already imported (line 7: `import { fmtBR } from "../diasUteis";`) — do NOT duplicate it. Add only:

```ts
import { api } from "../api";
```

- [ ] **Step 2: Inside `GestaoStatusPanel`, read `is_admin` and wire mutations (after the existing `statusQ`, ~line 27)**

```ts
  const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const isAdmin = !!cfgQ.data?.is_admin;
  const invalidateRows = () => qc.invalidateQueries({ queryKey: ["gestao", entity] });
  const addBV = useMutation({
    mutationFn: (v: { comBv: boolean; data?: string }) => gestaoApi.setBV(entity, row.id, v.comBv, v.data),
    onSuccess: invalidateRows,
  });
  const delBV = useMutation({
    mutationFn: (id: string) => gestaoApi.deleteBV(id),
    onSuccess: invalidateRows,
  });
  const [corrData, setCorrData] = useState("");
  const [corrOn, setCorrOn] = useState(true);
```
(`useState` is already imported at line 4; `useMutation`/`useQuery`/`useQueryClient` at line 5. `gestaoApi` is imported at line 6.)

- [ ] **Step 3: Render the "Validação BV" section (before the `<h4>Histórico</h4>` block, ~line 54)**

```tsx
        <h4>Validação BV</h4>
        {row.bvEventos.length === 0 && <div className="muted">— sem eventos de validação</div>}
        {row.bvEventos.length > 0 && (
          <div className="gm-bv-log">
            {[...row.bvEventos].reverse().map((ev) => (
              <div className="gm-bv-ev" key={ev.id}>
                <span>{fmtBR(ev.data)} · {ev.comBv ? "Com BV" : "Conosco"}{ev.autor ? ` · ${nomeDe(ev.autor)}` : ""}</span>
                {isAdmin && (
                  <button className="gm-bv-del" title="Remover este evento (correção)"
                    onClick={() => delBV.mutate(ev.id)} disabled={delBV.isPending}>✕</button>
                )}
              </div>
            ))}
          </div>
        )}
        {isAdmin && (
          <div className="gm-bv-corr">
            <select value={corrOn ? "on" : "off"} onChange={(e) => setCorrOn(e.target.value === "on")}>
              <option value="on">Com BV</option>
              <option value="off">Conosco</option>
            </select>
            <input type="date" value={corrData} onChange={(e) => setCorrData(e.target.value)} />
            <button className="theme-btn" disabled={!corrData || addBV.isPending}
              onClick={() => { addBV.mutate({ comBv: corrOn, data: corrData }); setCorrData(""); }}>
              + evento na data
            </button>
          </div>
        )}
```

- [ ] **Step 4: Add minimal CSS for the log/correction rows in `styles.css` (near the other `.gm-bv-*` rules)**

```css
.gm-bv-log { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.gm-bv-ev { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.gm-bv-del { background: transparent; border: none; color: var(--danger); cursor: pointer; padding: 0 4px; }
.gm-bv-corr { display: flex; gap: 6px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
```

- [ ] **Step 5: Typecheck + visual check**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: exit 0.
Then in the dev app: open a project's side panel → "Validação BV" lists events newest-first. As a non-admin the delete buttons and the "add event on date" control are hidden; as a `bv_admins` member they appear, delete removes an event and the count/toggle recompute, and adding a past-dated event adjusts the days.

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): seção \"Validação BV\" no painel (correção retroativa, só bv_admins)"
```

---

## Notes for the implementer

- The dev app (backend :8000 profile `bv` → `monitoramento_sas_dev`; Vite :5173) is already running this session; Vite HMR reloads on save. Restart the backend after Task 1/2 (Python changes are not hot-reloaded).
- `sas_gestao_bv` is created lazily by `_ensure_gestao_tables()` on first Gestão call — no manual DDL needed in dev.
- Do NOT rebuild the `static/` bundle per task; rebuild once at the end (or leave it to the deploy scripts, which always `npm run build`). Keep the bundle out of the per-task commits to keep diffs readable; add one `chore(app): rebuild bundle` commit at the end if you want the versioned bundle in sync.
- Do not commit `TODO.md` files.
