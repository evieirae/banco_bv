# Month filter on the Outputs tab

## Goal

Add a **Mês** (month) multi-select dropdown to the Outputs tab, replicating the existing
Inputs-tab month filter. It filters outputs down to those related to EGPs targeted to
migrate in the selected month(s).

- "Related EGPs" = the output's **producers** (EGPs that produce it). The multi-producer
  case is exactly why one output can span months.
- An output inherits the migration months of **all** its producers (full base, regardless
  of the tab's indi/base scope selector) — so `OutputX` can appear under M1, M2 and M3
  simultaneously. That is expected.
- Multi-select: empty selection = all; a selected month keeps outputs whose producer-month
  set contains it.

## Data model reused

- `useMesPlan()` → `mesOf: Map<projeto, month>` (from `/api/priorizacao`) and `meses`
  (sorted month numbers).
- `api.outputsEgps("base")` → output→producer pairs `{chave_canonica, projeto}` (already
  used by the CSV export; loaded once via `useQuery`, keyed `["outputs-egps","base"]`).

## Frontend — `OutputsView.tsx` (only file changed)

1. Add `const { mesOf, meses } = useMesPlan();`.
2. Add `outputsEgpsQ = useQuery(["outputs-egps","base"], () => api.outputsEgps("base"))`.
3. Build `mesByOutput: Map<string, Set<number>>` (useMemo over `outputsEgpsQ.data` + `mesOf`):
   for each producer pair, add `mesOf.get(projeto)` (when defined) to the output's set.
4. New state `const [mesSel, setMesSel] = useState<Set<string>>(new Set())`.
5. In the existing `filtered` memo, add a clause: when `mesSel.size > 0`, keep `r` only if
   `mesByOutput.get(r.chave_canonica)` intersects `mesSel` (compare as numbers). Add
   `mesByOutput` and `mesSel` to the memo deps.
6. UI: a `MultiSelect` in the filter row after Categoria —
   `label="Mês"`, `options={meses.map(String)}`,
   `labels={Object.fromEntries(meses.map(m => [String(m), mesTag(m)]))}`,
   `sel={mesSel}`, toggle/clear handlers mutating `mesSel`.

Mirror the Inputs pattern (`MonitorView` `mesByInput` + `FilterBar` Mês `MultiSelect`).

## CSV export

**Untouched.** `exportCsv` iterates `sorted` (= `useTableSort(filtered, …)`), so it already
honors every active filter; the month filter flows through automatically. No export code
changes.

## Behavior notes

- An output whose producers are not in the plan (`mesOf` has no month for them) has an
  empty month set → filtered out when any month is selected (same as the Inputs behavior).
- Producer months come from `outputsEgps("base")` (all producers), independent of the
  indi/base scope selector — matches the export and keeps month coverage complete.

## Testing

- `tsc --noEmit` clean.
- Manual (dev app): select M1 → only outputs with a producer targeted for M1 remain;
  an output with producers in M1 and M2 appears when either is selected; clearing shows all.
- Export with a month selected → the downloaded CSV contains exactly the filtered rows.

## Out of scope

- No backend changes (all client-side, like the Inputs month filter).
- No new columns; no change to existing Outputs filters/columns or to `/api/outputs`.
