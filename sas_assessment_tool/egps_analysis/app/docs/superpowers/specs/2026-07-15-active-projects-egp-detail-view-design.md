# `#Proj Ativos Dentro do Escopo` in the EGP detail view

## Goal

In the **EGPs** tab, expanding an EGP shows its inputs (columns: Artefato, Cat.,
Origem, Auto, Status, Responsável, Observação). Add a new column
**`#Proj Ativos Dentro do Escopo`**: the number of EGPs consuming that input that are
**within the Indicium scope + dependencies AND not deprioritized**.

As in-scope EGPs get deprioritized, this count drops; an input with **0** such projects
is a candidate to be deprioritized/removed itself. That is the flag this column enables.

Two conditions, both required (see fork below):

- **Within scope+deps** = the `indi_deps` frontier: Indicium base (`escopo_indi`) ∪ its
  transitive upstream dependencies (`_frontier_egps("indi_deps", [])`).
- **Not deprioritized** = migration status ≠ `Despriorizado e Contabilizado`
  (`_egps_fora_backlog()`).

Why both: the `indi_deps` frontier **still includes** deprioritized EGPs that sit in the
Indicium base (in `_transitive_upstream` they get level 0 — they just don't expand their
own deps). So scope membership alone does not drop deprioritized EGPs; the deprioritized
filter must be applied explicitly for the "0 = removable" behavior to hold.

## Scope

- **Only** the EGP detail view (`EgpDetailPanel`). The Inputs-tab `#Proj`
  (`qtd_projetos`) counts consumers across the **entire database** and stays exactly as is
  — this new column is deliberately a different, scoped measure.
- Counting universe: consumers that are in the `indi_deps` frontier **and** not
  deprioritized. `0` means no live in-scope EGP consumes the input.

## Backend — `egp_detail` in `backend/main.py`

`_fora = _egps_fora_backlog()` is already computed in `egp_detail`. After building
`inputs`, compute the active set once and count per input chave:

```python
active_set = _frontier_egps("indi_deps", [])[0] - _fora   # scope+deps AND not deprioritized
```

Then one grouped query over `sas_egp_inputs` (`T_EGP`), restricted to this EGP's input
chaves and the active set:

```sql
SELECT chave_canonica, count(DISTINCT projeto) AS n_proj_ativos
FROM sas_egp_inputs
WHERE chave_canonica IN (<this EGP's input chaves>)
  AND projeto IN (<active_set>)
GROUP BY chave_canonica
```

- Attach `n_proj_ativos` (int) to each input row; default **0** when the chave is absent
  from the result (no active in-scope consumer).
- Skip the query when the EGP has no inputs, and when `active_set` is empty (all rows → 0).
- Graceful degradation: wrap in `try/except HTTPException`; on failure, set the field to
  `None` (frontend renders blank) rather than a misleading `0`.

## Frontend

- `types.ts`: add `n_proj_ativos: number | null` to the `EgpInput` interface.
- `EgpDetailPanel.tsx`: add the column **immediately after `Cat.`** — a header cell
  `#Proj Ativos Dentro do Escopo` (with a `title` tooltip explaining the measure) and a
  numeric body cell `{i.n_proj_ativos}`. Plain rendering (no highlight for 0).
- `styles.css`: the `.egp-thead, .egp-trow` grid has 7 tracks
  (`minmax(180px,2.4fr) 70px 1.3fr 90px 150px 1fr 1.4fr`). Insert one `96px` track in the
  3rd position (after the `70px` Cat. track); the header wraps within it, body shows the
  number.

## Testing

- Backend: for an EGP, `n_proj_ativos` of an input equals the number of its consumers that
  are in the `indi_deps` frontier and not deprioritized; ≤ the whole-DB consumer count; an
  input with no live in-scope consumer → `0`.
- Frontend: `tsc --noEmit` clean; column renders aligned after `Cat.`.
- Manual: open an EGP in the app (dev), confirm the column shows scoped counts.

## Out of scope

- No change to the Inputs tab, its `#Proj`, or the CSV export.
- No visual flag/highlight for 0 rows (kept plain, per decision).
