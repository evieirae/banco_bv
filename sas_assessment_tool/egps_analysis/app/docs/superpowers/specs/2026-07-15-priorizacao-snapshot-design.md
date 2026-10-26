# Priorização: snapshot (freeze) + Recalcular + Salvar

> **Amendment 2026-07-16 (implemented on `fix/prioritization`).** The v1 below froze the
> **entire** computed payload as a JSON blob and rendered it verbatim, so live-attribution
> fields (`responsavel`, `etapa`, `status`, `bloqueado`) — editable on EGP/Gestão — were
> stuck at snapshot-time. Bug that surfaced it: Project_Atualiza_Lista_Restrita assigned to
> David on EGP tab showed **no responsible** on Priorização.
>
> **Final design (this fix):** keep the full computed payload as the snapshot (unchanged
> storage), but at read time **overlay live attribution** onto it — for each EGP, replace
> `responsavel/etapa/status/bloqueado` with the current T_PIPE / `_blocking()` values, and
> recompute `resumo.bloqueados` and `resumo.migrados_mes` from the overlay. The **plan**
> stays frozen (mês/EGPs/`n_inputs_novos`/`excede`/`fan_out`/`mes_pin`/`capacidade`); only
> the four attribution fields (and their derived counts) update mid-execution. Sections
> below tagged **[amended 2026-07-16]** describe the final behavior. Untagged text is v1.
>
> _Iteration history (commits on this branch): 66a74af tried a `{projeto: mes}`-only map
> with `_compute_priorizacao(pin_override=plan)` at read time — that leaked "everything
> derived is live" (including `n_inputs_novos`, which is part of the plan). Replaced with
> the overlay approach above._

## Problem

The Priorização plan is recomputed live on every request (`GET /api/priorizacao`),
purely derived from ever-changing data (each EGP's "a ingerir" set, deprioritization,
frontier) plus persisted pins/capacity. So the plan silently drifts as data changes and
cannot be held to a known state — the root cause of the "prioritization doesn't match the
sync" incident (532 input edits + 7 deprioritizations since the sync moved it; unpinning
could not reverse that).

## Goal

Freeze the displayed plan behind a **saved snapshot**, and give an explicit
**Recalcular** (preview) + **Salvar** (persist) flow:

- The tab shows the **saved snapshot** (frozen) — it does NOT change when underlying data,
  pins, or capacity change.
  - **[amended 2026-07-16]** The **plan is frozen**: mês, EGP set per mês, `n_inputs_novos`,
    `excede`, `fan_out`, `mes_pin`, `capacidade`. New EGPs discovered post-Save do NOT sneak
    in; removed EGPs stay in the frozen plan. **Attribution is live**: `responsavel`,
    `etapa`, `status`, `bloqueado` are re-read from T_PIPE / `_blocking()` on each request
    and overlaid onto the frozen payload; `resumo.bloqueados` and `resumo.migrados_mes` are
    recomputed from the overlay so summary counts match the visible per-EGP state.
- **Recalcular** (view-all): computes a fresh plan server-side and shows it as an
  **unsaved preview** in the user's session. Persists nothing.
- **Salvar** (**admins only**, `bv_admins`): persists a fresh authoritative computation as
  the new snapshot; audited. From then on everyone sees the new frozen plan.

This also resolves management's "app recalcula o tempo todo" concern: recompute is now
on-demand, not on every load.
_**[amended 2026-07-16]** Still true: `GET /api/priorizacao` **does not recompute** the
plan — it returns the frozen payload with a cheap live-attribution overlay (one T_PIPE read
+ `_blocking()`). Full recompute happens only on Recalcular (preview) and Salvar._

## Decisions (locked)

- Recompute = **server compute, unsaved preview** (reuse the existing tested `plan_months`
  path; no client-side reimplementation).
- Snapshot stores the **full displayed plan + metadata** (tab renders straight from it).
  - **[amended 2026-07-16]** Kept as-is: full payload in `payload STRING`. Read overlays the
    four live-attribution fields (`responsavel`, `etapa`, `status`, `bloqueado`) and the two
    derived counts (`resumo.bloqueados`, `resumo.migrados_mes`) before returning.
- **Auto-seed once**: first load with no snapshot computes once and saves it as the initial
  snapshot; frozen thereafter.
- **View all; Recalcular = view-all; Salvar = admins only** (`_require_admin`, `bv_admins`),
  audited. (Pins/capacity edits stay gestão-gated as today.)

## Backend — `backend/main.py`

**Refactor:** extract the current body of `priorizacao()` into a pure-ish
`_compute_priorizacao(scope, area, deps, capacidade) -> dict` returning the existing
payload shape (`{meses, n_meses, n_inputs, n_egps, capacidade, resumo}`). No behavior
change to the computation.

**New table** `sas_priorizacao_snapshot` (single current snapshot; `CREATE TABLE IF NOT
EXISTS` on first use, mirroring other tables):

```
id STRING,            -- constant 'current' (single-row, overwritten on save)
payload STRING,       -- JSON of the computed PriorizacaoPayload (rendered verbatim by the tab)
capacidade INT,       -- capacity used for this snapshot (quick display / staleness)
saved_by STRING,      -- current_user() at save ('auto' for the seed)
saved_at STRING       -- cast(current_timestamp() AS STRING)
```

Storing the payload as a JSON blob keeps the snapshot faithful to what the tab renders and
avoids schema drift; the tab already consumes exactly this shape.

**[amended 2026-07-16]** Storage unchanged (full payload). Rows written by the
intermediate `{projeto: mes}`-only iteration (commit 66a74af) are rejected on read
(`_read_prio_snapshot` returns `None`), so the tab shows "no snapshot" and an admin
re-Saves. `capacidade`/`saved_by`/`saved_at` unchanged.

**Endpoints:**

- `GET /api/priorizacao` (changed): returns the **saved snapshot** payload (parsed from
  `payload`), augmented with `snapshot: {saved_by, saved_at}`.
  **[amended 2026-07-16]** returns the frozen payload with `_overlay_live_attribution`
  applied (responsavel/etapa/status/bloqueado from T_PIPE + `_blocking()`; resumo counts
  recomputed) + `snapshot: {saved_by, saved_at}`. Overlay failures degrade to the frozen
  values rather than erroring. If no snapshot exists,
  **auto-seed**: `_compute_priorizacao(...)` → persist with `saved_by='auto'` (idempotent
  MERGE on `id='current'`; concurrent seeds are benign — deterministic identical result) →
  return it. Keep the current default params (`scope=indi&deps=transitive`).
  - The auto-seed write uses the **SP client** (`_sp_client()`), NOT the caller's OBO token,
    so a read-only user's first load still seeds successfully (the table write must not
    depend on the reader's privileges). The `_compute_priorizacao` reads still run as the
    caller (OBO). If the SP write fails for any reason, fall back to returning the live
    computation unpersisted (seed retries on the next load) rather than erroring the tab.
- `GET /api/priorizacao/preview` (new, view-all): returns `_compute_priorizacao(...)` live,
  **unsaved**. Same payload shape (no `snapshot` field, or `snapshot: null`).
- `POST /api/priorizacao/snapshot` (new, **`_require_admin()`**): recompute
  `_compute_priorizacao(...)` server-side and **persist** (MERGE into `id='current'`) with
  `saved_by=current_user()`; write an audit row (`sas_pipeline_audit`, projeto `'(config)'`,
  campo `'priorizacao_snapshot'`, valor_novo = saved_at). Returns the saved payload.
  - Save recomputes rather than trusting a client-sent payload; since the computation is
    deterministic on current pins/capacity/data, the saved plan equals what the admin just
    previewed (barring an edit in the intervening seconds — acceptable).

The existing `PATCH /api/priorizacao/mes` and `/capacidade` are unchanged: they persist
pins/capacity immediately but no longer alter the displayed plan until a Recalcular+Salvar.

## Frontend — `WavesView.tsx`, `api.ts`, `types.ts`

- `types.ts`: `PriorizacaoPayload.snapshot?: { saved_by: string; saved_at: string } | null`.
- `api.ts`: add `priorizacaoPreview()` (GET `/api/priorizacao/preview`) and
  `priorizacaoSaveSnapshot()` (POST `/api/priorizacao/snapshot`).
- `WavesView.tsx`:
  - Default view renders the snapshot from `api.priorizacao()` (unchanged rendering) and
    shows a header line: **"Prioridade fixada — snapshot de {saved_at} por {saved_by}"**.
  - **Recalcular** button (all users): fetches the preview into local state and switches the
    tab into an **unsaved-preview mode** — a banner "Pré-visualização não salva" plus a light
    diff hint "{N} EGPs mudariam de mês vs. o snapshot atual" (compare preview vs snapshot
    months client-side). Buttons: **Descartar** (back to snapshot) and, for admins,
    **Salvar prioridade**.
  - **Salvar prioridade** (admins only — hidden/disabled when `!cfg.is_admin`): calls
    `priorizacaoSaveSnapshot()`, invalidates `["priorizacao"]`, exits preview mode.
  - After a pin/capacity edit (gestão), show a subtle hint: "há alterações não aplicadas ao
    plano — clique em Recalcular para pré-visualizar." (Since edits no longer change the
    frozen plan.)

## Testing

- Backend: `priorizacao_logic` unchanged (existing tests hold). Add a small check that
  `_compute_priorizacao` output is unchanged vs. the pre-refactor endpoint for a fixture.
  Verify: fresh schema → `GET /api/priorizacao` auto-seeds and returns a snapshot; editing a
  pin does NOT change `GET /api/priorizacao` until `POST /snapshot`; `POST /snapshot` as a
  non-admin → 403.
  - **[amended 2026-07-16]** Editing an EGP's **responsável/etapa/status** (EGP/Gestão tab)
    or its **bloqueado** condition (upstream dep change) DOES flow into `GET /api/priorizacao`
    without a Salvar, while its **mês/n_inputs_novos/excede** stay put. Editing pins/capacity
    still only takes effect after Salvar. `dev` can be brought into alignment with `prod` via
    `egps_analysis/app/sync_dev.py` (read-only on prod, DEEP CLONE per table into
    `monitoramento_sas_dev`; refuses to write anywhere that doesn't end in `_dev`).
- Frontend: `tsc --noEmit` clean; snapshot renders identically to today; Recalcular shows
  preview + diff count; Salvar hidden for non-admins.
- Manual (dev): load tab (seeds); pin an EGP → plan unchanged; Recalcular → preview shows the
  move; Salvar (admin) → snapshot updates; reload → frozen at new snapshot.

## Out of scope (note for later)

- Snapshot **history / revert to a previous snapshot** (v1 keeps a single current snapshot +
  save audit). Easy to extend by appending rows instead of overwriting.
- Per-scope snapshots (v1 snapshots the default `scope=indi&deps=transitive`, which is what
  the tab uses).
