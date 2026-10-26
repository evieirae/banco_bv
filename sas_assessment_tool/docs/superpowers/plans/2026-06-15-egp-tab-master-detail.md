# Aba EGPs master-detail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar a aba EGPs num master-detail: lista filtrável/ordenável de todos os EGPs (esquerda) + detalhe do EGP selecionado (direita), com deep-link via `?egp=<id>`.

**Architecture:** Reusa os endpoints existentes `/api/egp-readiness` (lista) e `/api/egp` (detalhe) — zero backend. Lógica pura de filtro/ordenação/chips/URL extraída para um módulo testável (`egpList.ts`); o detalhe atual é extraído para um componente próprio (`EgpDetailPanel.tsx`); `EgpView.tsx` vira o container com a lista master + estado de seleção.

**Tech Stack:** React 18 + TypeScript (Vite), FastAPI (sem mudança). Sem novas dependências. Testes de lógica pura via Node 24 (type stripping nativo); componentes verificados por `tsc`/`npm run build` + checagem manual.

---

## File Structure

| Arquivo | Papel |
|---|---|
| `egps_analysis/app/frontend/src/egpList.ts` (**criar**) | Lógica pura: helpers de display (`shortName`, `waveTag`, `indiOf`, `pctTone`), predicados/contagem de chips, `filterRows`, `sortRows`, helpers de URL (`readSelectedFromUrl`, `buildUrlWithSelected`). Sem React, sem fetch. |
| `egps_analysis/app/frontend/egpList.test.mts` (**criar**) | Teste Node das funções puras (fora de `src/` para o `tsc` não compilá-lo). |
| `egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx` (**criar**) | Painel direito: recebe `projeto`, busca `/api/egp`, renderiza header + depende de / alimenta + tabela de inputs editável. Extraído do `EgpView` atual. |
| `egps_analysis/app/frontend/src/components/EgpView.tsx` (**reescrever**) | Container: filtros + chips + tabela master (lista de `ReadinessRow`) + estado de seleção/URL; renderiza `<EgpDetailPanel>`. |
| `egps_analysis/app/frontend/src/styles.css` (**modificar**) | Adicionar `.egp-split`, `.egp-master`, `.egp-detail`, `.em-*`, `.em-chips`. |

Sem mudança em `api.ts`, `types.ts` ou no backend (todos os tipos/endpoints já existem: `ReadinessRow`, `EgpDetail`, `EgpInput`, `api.egpReadiness`, `api.egp`, `api.patch`).

Comando base (rodar tudo a partir de `egps_analysis/app/frontend`):

```bash
cd egps_analysis/app/frontend
```

---

### Task 1: Módulo de lógica pura `egpList.ts` (TDD)

**Files:**
- Create: `egps_analysis/app/frontend/src/egpList.ts`
- Test: `egps_analysis/app/frontend/egpList.test.mts`

- [ ] **Step 1: Escrever o teste que falha**

Criar `egps_analysis/app/frontend/egpList.test.mts`:

```ts
import assert from "node:assert/strict";
import {
  shortName, indiOf, waveTag, pctTone,
  matchesChip, chipCounts, filterRows, sortRows,
  readSelectedFromUrl, buildUrlWithSelected,
} from "./src/egpList.ts";

type Row = Parameters<typeof matchesChip>[0];

function row(p: Partial<Row>): Row {
  return {
    projeto: "RISCO__x", area: "RISCO", onda: "Onda 1", escopo_indi: true,
    ciclo_id: 0, n_inputs: 0, n_disp: 0, n_faltam: 0, pct: 0,
    n_deps: 0, n_deps_indi: 0, n_deps_ext: 0, deps: [],
    ...p,
  } as Row;
}

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("shortName tira o prefixo area__", () => {
  assert.equal(shortName("RISCO__limite_out"), "limite_out");
  assert.equal(shortName("semprefixo"), "semprefixo");
});

check("indiOf aceita boolean e string", () => {
  assert.equal(indiOf({ escopo_indi: true }), true);
  assert.equal(indiOf({ escopo_indi: "true" }), true);
  assert.equal(indiOf({ escopo_indi: false }), false);
});

check("waveTag", () => {
  assert.equal(waveTag(null), "—");
  assert.equal(waveTag("Onda 3"), "O3");
  assert.equal(waveTag("ciclo X"), "⟳");
});

check("pctTone (ciclo prevalece)", () => {
  assert.equal(pctTone(50, 2), "cyc");
  assert.equal(pctTone(100, 0), "ok");
  assert.equal(pctTone(70, 0), "wip");
  assert.equal(pctTone(10, 0), "todo");
});

check("matchesChip", () => {
  assert.equal(matchesChip(row({ ciclo_id: 1 }), "ciclo"), true);
  assert.equal(matchesChip(row({ n_deps_ext: 2 }), "externo"), true);
  assert.equal(matchesChip(row({ n_deps: 0 }), "folha"), true);
  assert.equal(matchesChip(row({ n_deps: 3 }), "folha"), false);
});

check("chipCounts", () => {
  const rows = [row({ ciclo_id: 1, n_deps: 2, n_deps_ext: 1 }), row({ n_deps: 0 })];
  assert.deepEqual(chipCounts(rows), { ciclo: 1, externo: 1, folha: 1 });
});

check("filterRows aplica area, q e chips em AND", () => {
  const rows = [
    row({ projeto: "RISCO__alpha", area: "RISCO", n_deps_ext: 1 }),
    row({ projeto: "CRED__beta", area: "CRED", n_deps_ext: 0 }),
  ];
  assert.equal(filterRows(rows, { area: "RISCO", q: "", chips: [] }).length, 1);
  assert.equal(filterRows(rows, { area: "", q: "beta", chips: [] }).length, 1);
  assert.equal(filterRows(rows, { area: "", q: "", chips: ["externo"] }).length, 1);
  assert.equal(filterRows(rows, { area: "CRED", q: "", chips: ["externo"] }).length, 0);
});

check("sortRows numérico e string", () => {
  const rows = [row({ projeto: "b", n_deps: 1 }), row({ projeto: "a", n_deps: 5 })];
  assert.equal(sortRows(rows, "n_deps", false)[0].n_deps, 5);
  assert.equal(sortRows(rows, "n_deps", true)[0].n_deps, 1);
  assert.equal(sortRows(rows, "projeto", true)[0].projeto, "a");
});

check("helpers de URL", () => {
  assert.equal(readSelectedFromUrl("?egp=CRED__x"), "CRED__x");
  assert.equal(readSelectedFromUrl(""), null);
  assert.equal(buildUrlWithSelected("https://h/egps", "CRED__x"), "https://h/egps?egp=CRED__x");
  assert.equal(buildUrlWithSelected("https://h/egps?egp=old&z=1", null), "https://h/egps?z=1");
});

console.log(`\n${pass} testes OK`);
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `node egpList.test.mts`
Expected: FAIL — `Cannot find module './src/egpList.ts'` (módulo ainda não existe).

> Node 24 faz type stripping nativo. Se a versão reclamar de tipos, use `node --experimental-strip-types egpList.test.mts`.

- [ ] **Step 3: Implementar `src/egpList.ts`**

Criar `egps_analysis/app/frontend/src/egpList.ts`:

```ts
import type { ReadinessRow } from "./types";

export type EgpSortKey = "projeto" | "area" | "n_inputs" | "pct" | "n_faltam" | "n_deps";
export type EgpChip = "ciclo" | "externo" | "folha";

export interface EgpListFilters {
  area: string;
  q: string;
  chips: EgpChip[];
}

export const shortName = (id: string): string =>
  id.includes("__") ? id.split("__").slice(1).join("__") : id;

export const indiOf = (n: { escopo_indi: string | boolean }): boolean =>
  n.escopo_indi === true || n.escopo_indi === "true";

export function waveTag(onda: string | null): string {
  if (!onda) return "—";
  if (/cicl/i.test(onda)) return "⟳";
  const m = onda.match(/\d+/);
  return m ? `O${m[0]}` : onda;
}

export function pctTone(pct: number, cicloId: number): "ok" | "wip" | "todo" | "cyc" {
  if (cicloId > 0) return "cyc";
  if (pct >= 100) return "ok";
  if (pct >= 30) return "wip";
  return "todo";
}

export function matchesChip(r: ReadinessRow, chip: EgpChip): boolean {
  if (chip === "ciclo") return r.ciclo_id > 0;
  if (chip === "externo") return r.n_deps_ext > 0;
  return r.n_deps === 0; // folha
}

export function chipCounts(rows: ReadinessRow[]): Record<EgpChip, number> {
  const c: Record<EgpChip, number> = { ciclo: 0, externo: 0, folha: 0 };
  for (const r of rows) {
    if (matchesChip(r, "ciclo")) c.ciclo++;
    if (matchesChip(r, "externo")) c.externo++;
    if (matchesChip(r, "folha")) c.folha++;
  }
  return c;
}

export function filterRows(rows: ReadinessRow[], f: EgpListFilters): ReadinessRow[] {
  const q = f.q.trim().toLowerCase();
  return rows.filter((r) => {
    if (f.area && r.area !== f.area) return false;
    if (q && !r.projeto.toLowerCase().includes(q)) return false;
    for (const chip of f.chips) if (!matchesChip(r, chip)) return false;
    return true;
  });
}

export function sortRows(rows: ReadinessRow[], key: EgpSortKey, asc: boolean): ReadinessRow[] {
  const dir = asc ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[key];
    const y = b[key];
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
    return String(x).localeCompare(String(y)) * dir;
  });
}

export function readSelectedFromUrl(search: string): string | null {
  return new URLSearchParams(search).get("egp");
}

export function buildUrlWithSelected(href: string, projeto: string | null): string {
  const url = new URL(href);
  if (projeto) url.searchParams.set("egp", projeto);
  else url.searchParams.delete("egp");
  return url.toString();
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `node egpList.test.mts`
Expected: PASS — imprime `ok - ...` para cada caso e `9 testes OK`, exit code 0.

- [ ] **Step 5: Garantir que o build (tsc) continua verde**

Run: `npm run build`
Expected: build sem erros. (`egpList.ts` está em `src/` e é type-checado; `egpList.test.mts` está fora de `src/`, então o `tsc` o ignora — `tsconfig.json` tem `include: ["src"]`.)

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/egpList.ts egps_analysis/app/frontend/egpList.test.mts
git commit -m "feat(egps): logica pura de lista (filtro/ordenacao/chips/url) + testes"
```

---

### Task 2: Componente `EgpDetailPanel.tsx` (painel direito)

**Files:**
- Create: `egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx`

Extrai o bloco de detalhe do `EgpView` atual para um componente que recebe `projeto` e busca `/api/egp`. Sem teste unitário (componente) — verificado por `tsc`.

- [ ] **Step 1: Criar o componente**

Criar `egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppConfig, EgpDetail, EgpInput } from "../types";
import { shortName, indiOf, waveTag } from "../egpList";

const stClass = (s: string | null): string => {
  if (s === "Disponível" || s === "Sanitizada") return "st-ok";
  if (s === "Em ingestão" || s === "Em análise") return "st-wip";
  if (s === "Descartada") return "st-muted";
  return "st-todo";
};

export function EgpDetailPanel({ projeto, cfg }: { projeto: string | null; cfg: AppConfig | null }) {
  const statusOpts = cfg?.status_options ?? ["A ingerir", "Em análise", "Em ingestão", "Disponível", "Sanitizada", "Descartada"];
  const [det, setDet] = useState<EgpDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!projeto) { setDet(null); setErr(null); return; }
    setBusy(true); setErr(null);
    let alive = true;
    api.egp(projeto)
      .then((d) => { if (alive) setDet(d); })
      .catch((e) => { if (alive) setErr(String(e)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [projeto]);

  const onPatch = async (chave: string, patch: Partial<EgpInput>) => {
    try {
      await api.patch({ chave_canonica: chave, ...patch });
      setDet((d) => d && { ...d, inputs: d.inputs.map((i) => i.chave_canonica === chave ? { ...i, ...patch } : i) });
    } catch (e) { setErr(String(e)); }
  };

  if (!projeto) return <div className="empty">Selecione um EGP para ver seus inputs e dependências.</div>;
  if (busy) return <div className="empty">carregando…</div>;
  if (err) return <div className="error">{err}</div>;
  if (!det) return null;

  return (
    <div className="egp-body">
      <div className="egp-head">
        <h2>{shortName(det.node.projeto)}</h2>
        <span className="pill">{det.node.area}</span>
        <span className="pill">{waveTag(det.node.onda)}</span>
        {Number(det.node.ciclo_id) > 0 && <span className="pill cyc">⟳ em ciclo #{det.node.ciclo_id}</span>}
        {indiOf(det.node) && <span className="pill ind">◆ Indicium</span>}
        <span className="muted">{det.node.n_inputs} inputs · {det.node.n_outputs} outputs</span>
      </div>

      {det.em_ciclo_com.length > 0 && (
        <div className="cyc-warn">
          ⚠ Este EGP está numa <b>dependência cíclica</b> com:{" "}
          {det.em_ciclo_com.map((c) => shortName(c.projeto)).join(", ")}. Ver detalhe e como quebrar na aba <b>Linhagem</b> e no documento <code>DEPENDENCIAS_CICLICAS.md</code>.
        </div>
      )}

      <div className="egp-cols">
        <div className="egp-panel">
          <h3>Depende de ({det.depende_de.length})</h3>
          {det.depende_de.length === 0 && <div className="muted">— nenhuma dependência upstream</div>}
          {det.depende_de.map((d) => (
            <div key={d.projeto} className="dep">
              <span className="dep-proj">{shortName(d.projeto)}</span>
              <span className="dep-meta">{d.area ?? "?"} · {waveTag(d.onda)} {Number(d.ciclo_id) > 0 ? "· ⟳" : ""}</span>
              <span className="dep-via" title={d.via_tabelas ?? ""}>via {d.via_tabelas ?? "—"}</span>
            </div>
          ))}
        </div>
        <div className="egp-panel">
          <h3>Alimenta ({det.alimenta.length})</h3>
          {det.alimenta.length === 0 && <div className="muted">— não alimenta outros EGPs</div>}
          {det.alimenta.map((d) => (
            <div key={d.projeto} className="dep">
              <span className="dep-proj">{shortName(d.projeto)}</span>
              <span className="dep-meta">{d.area ?? "?"} · {waveTag(d.onda)} {Number(d.ciclo_id) > 0 ? "· ⟳" : ""}</span>
              <span className="dep-via" title={d.via_tabelas ?? ""}>via {d.via_tabelas ?? "—"}</span>
            </div>
          ))}
        </div>
      </div>

      <h3>Inputs / necessidades ({det.inputs.length})</h3>
      <div className="egp-table">
        <div className="egp-thead">
          <div>Artefato</div><div>Cat.</div><div>Origem</div><div>Auto</div><div>Status (ingestão)</div><div>Responsável</div><div>Observação</div>
        </div>
        <div className="egp-tbody">
          {det.inputs.map((i) => (
            <div key={i.chave_canonica} className="egp-trow">
              <div className="c-art" title={i.artifact}>{i.artifact}</div>
              <div>{i.categoria}</div>
              <div className="c-src" title={i.source_types}>{i.source_types || "—"}</div>
              <div><span className={`pill ${i.modernizada_auto === "Disponível" ? "ok" : "todo"}`}>{i.modernizada_auto}</span></div>
              <div>
                <select className={stClass(i.status_humano)} value={i.status_humano ?? ""}
                  onChange={(e) => onPatch(i.chave_canonica, { status_humano: e.target.value })}>
                  <option value="">—</option>
                  {statusOpts.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div><input value={i.responsavel ?? ""} placeholder="—"
                onBlur={(e) => e.target.value !== (i.responsavel ?? "") && onPatch(i.chave_canonica, { responsavel: e.target.value })}
                onChange={(e) => setDet((d) => d && { ...d, inputs: d.inputs.map((x) => x.chave_canonica === i.chave_canonica ? { ...x, responsavel: e.target.value } : x) })} /></div>
              <div><input value={i.observacao ?? ""} placeholder="—"
                onBlur={(e) => e.target.value !== (i.observacao ?? "") && onPatch(i.chave_canonica, { observacao: e.target.value })}
                onChange={(e) => setDet((d) => d && { ...d, inputs: d.inputs.map((x) => x.chave_canonica === i.chave_canonica ? { ...x, observacao: e.target.value } : x) })} /></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar o build**

Run: `npm run build`
Expected: build sem erros. (O componente ainda não é importado por ninguém — arquivo não usado não quebra o `tsc`/vite.)

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx
git commit -m "feat(egps): extrai painel de detalhe para EgpDetailPanel"
```

---

### Task 3: Reescrever `EgpView.tsx` (container + lista master)

**Files:**
- Modify (substituir conteúdo): `egps_analysis/app/frontend/src/components/EgpView.tsx`

Substitui o dropdown por uma tabela master (lista de `ReadinessRow`), com filtros, chips, ordenação por header e estado de seleção sincronizado com `?egp=`. Renderiza `<EgpDetailPanel>` à direita.

- [ ] **Step 1: Reescrever o componente**

Substituir TODO o conteúdo de `egps_analysis/app/frontend/src/components/EgpView.tsx` por:

```tsx
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { AppConfig, ReadinessRow } from "../types";
import {
  shortName, indiOf, waveTag, pctTone,
  chipCounts, filterRows, sortRows, readSelectedFromUrl, buildUrlWithSelected,
  type EgpSortKey, type EgpChip,
} from "../egpList";
import { EgpDetailPanel } from "./EgpDetailPanel";

const CHIPS: { id: EgpChip; label: string }[] = [
  { id: "ciclo", label: "⟳ em ciclo" },
  { id: "externo", label: "depende de externo" },
  { id: "folha", label: "folhas (sem deps)" },
];

export function EgpView({ cfg }: { cfg: AppConfig | null }) {
  const [scopeIndi, setScopeIndi] = useState(true);
  const [rows, setRows] = useState<ReadinessRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [area, setArea] = useState("");
  const [q, setQ] = useState("");
  const [chips, setChips] = useState<EgpChip[]>([]);
  const [sort, setSort] = useState<EgpSortKey>("n_deps");
  const [asc, setAsc] = useState(false);
  const [selected, setSelected] = useState<string | null>(() => readSelectedFromUrl(window.location.search));

  useEffect(() => {
    setBusy(true); setErr(null);
    api.egpReadiness(scopeIndi ? "indi" : "base")
      .then((r) => setRows(r.rows))
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  }, [scopeIndi]);

  // voltar/avançar do navegador atualiza o EGP selecionado
  useEffect(() => {
    const onPop = () => setSelected(readSelectedFromUrl(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const select = (projeto: string) => {
    if (projeto === selected) return;
    setSelected(projeto);
    window.history.pushState(null, "", buildUrlWithSelected(window.location.href, projeto));
  };

  const toggleChip = (id: EgpChip) =>
    setChips((cs) => (cs.includes(id) ? cs.filter((c) => c !== id) : [...cs, id]));

  const areasList = useMemo(() => [...new Set(rows.map((r) => r.area))].sort(), [rows]);
  const counts = useMemo(() => chipCounts(rows), [rows]);
  const view = useMemo(
    () => sortRows(filterRows(rows, { area, q, chips }), sort, asc),
    [rows, area, q, chips, sort, asc],
  );

  const th = (k: EgpSortKey, label: string) => (
    <div className="em-th" onClick={() => (k === sort ? setAsc(!asc) : (setSort(k), setAsc(false)))}>
      {label}{sort === k ? (asc ? " ▲" : " ▼") : ""}
    </div>
  );

  return (
    <div className="egpview">
      <div className="filters">
        <select value={scopeIndi ? "indi" : "all"} onChange={(e) => setScopeIndi(e.target.value === "indi")}>
          <option value="indi">escopo: só Indicium</option>
          <option value="all">escopo: todos</option>
        </select>
        <select value={area} onChange={(e) => setArea(e.target.value)}>
          <option value="">todas as áreas</option>
          {areasList.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <input type="search" placeholder="filtrar EGP…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="count">{busy ? "carregando…" : `${view.length} de ${rows.length} EGPs`}</span>
      </div>

      <div className="em-chips">
        {CHIPS.map((c) => (
          <button key={c.id} className={`chip ${chips.includes(c.id) ? "on" : ""}`} onClick={() => toggleChip(c.id)}>
            {c.label}: {counts[c.id]}
          </button>
        ))}
      </div>

      {err && <div className="error">{err}</div>}

      <div className="egp-split">
        <div className="egp-master">
          <div className="em-table">
            <div className="em-thead">
              {th("projeto", "EGP")}{th("area", "Área")}<div>Onda</div>
              {th("n_inputs", "Inputs")}{th("pct", "% mod.")}{th("n_faltam", "Faltam")}
              {th("n_deps", "Depende de")}
            </div>
            <div className="em-tbody">
              {view.map((r) => (
                <div key={r.projeto}
                  className={`em-trow ${r.projeto === selected ? "sel" : ""}`}
                  onClick={() => select(r.projeto)}>
                  <div className="c-art" title={r.projeto}>{shortName(r.projeto)}{indiOf(r) ? " ◆" : ""}</div>
                  <div className="c-src">{r.area}</div>
                  <div className={r.ciclo_id > 0 ? "cyc-txt" : ""}>{waveTag(r.onda)}</div>
                  <div className="c-num">{r.n_inputs}</div>
                  <div className="em-pct">
                    <div className="rd-bar"><div className={`rd-fill ${pctTone(r.pct, r.ciclo_id)}`} style={{ width: `${r.pct}%` }} /></div>
                    <span>{r.pct}%</span>
                  </div>
                  <div className="c-num">{r.n_faltam || ""}</div>
                  <div className={`em-deps ${r.n_deps ? "has" : ""}`}>
                    {r.n_deps ? (
                      <>
                        <span className="dep-tot">{r.n_deps}</span>
                        <span className="dep-bd">
                          {r.n_deps_indi > 0 && <span className="dep-b indi">{r.n_deps_indi}i</span>}
                          {r.n_deps_ext > 0 && <span className="dep-b ext">{r.n_deps_ext}e</span>}
                        </span>
                        {r.ciclo_id > 0 && <span className="cyc-txt"> ⟳</span>}
                      </>
                    ) : "—"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="egp-detail">
          <EgpDetailPanel projeto={selected} cfg={cfg} />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar o build**

Run: `npm run build`
Expected: build sem erros de tipo. (A app passa a importar `egpList` e `EgpDetailPanel`.)

> Nota: após este passo a aba já funciona (lista + detalhe + deep-link), mas a lista fica **sem estilo** até a Task 4.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/frontend/src/components/EgpView.tsx
git commit -m "feat(egps): EgpView vira master-detail (lista + selecao via ?egp)"
```

---

### Task 4: Estilos do split + tabela master

**Files:**
- Modify (append): `egps_analysis/app/frontend/src/styles.css`

Reusa classes existentes (`.chip`, `.rd-bar`, `.rd-fill`, `.dep-b/.dep-tot/.dep-bd`, `.c-art/.c-src/.c-num`, `.cyc-txt`, `.filters`, `.count`). Cria só o layout do split e a tabela master.

- [ ] **Step 1: Adicionar as regras CSS**

Acrescentar ao final da seção da aba EGPs em `styles.css` (pode colar logo após a linha `.egp-trow select.st-todo { ... }`):

```css
/* aba EGPs — master-detail (lista + detalhe) */
.egp-split { flex: 1; display: flex; gap: 14px; min-height: 0; }
.egp-master { flex: 0 0 380px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
.egp-detail { flex: 1; min-width: 0; overflow: auto; display: flex; flex-direction: column; }
.egp-detail .egp-table { min-width: 680px; }
.em-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.em-table { display: flex; flex-direction: column; font-size: 12px; }
.em-thead, .em-trow { display: grid; grid-template-columns: minmax(120px,1.7fr) 0.9fr 46px 52px 1fr 52px 1fr; align-items: center; }
.em-thead { position: sticky; top: 0; z-index: 1; background: var(--panel2); border-bottom: 1px solid var(--line); color: var(--mut); text-transform: uppercase; font-size: 10px; letter-spacing: .4px; }
.em-thead > div, .em-trow > div { padding: 5px 7px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.em-th { cursor: pointer; user-select: none; }
.em-th:hover { color: var(--ink); }
.em-trow { border-bottom: 1px solid #23272e; cursor: pointer; }
.em-trow:hover { background: #20242b; }
.em-trow.sel { background: var(--panel2); outline: 1px solid var(--accent); outline-offset: -1px; }
.em-pct { display: flex; align-items: center; gap: 6px; }
.em-deps.has { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
```

- [ ] **Step 2: Verificar o build**

Run: `npm run build`
Expected: build sem erros (CSS não afeta o `tsc`; só confirma que o bundle gera).

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/frontend/src/styles.css
git commit -m "style(egps): layout do split master-detail e tabela da lista"
```

---

### Task 5: Verificação final (build + teste + manual + revisão)

**Files:** nenhum (verificação).

- [ ] **Step 1: Build limpo + teste de lógica**

```bash
cd egps_analysis/app/frontend
npm run build
node egpList.test.mts
```
Expected: build sem erros; `9 testes OK`.

- [ ] **Step 2: Checagem manual (app rodando)**

Subir o front em dev (`npm run dev`, com o backend em :8000 — precisa de credenciais Databricks) ou validar após deploy. Conferir:
  - A lista carrega todos os EGPs do escopo; o contador "N de M EGPs" bate.
  - Filtros escopo/área/busca funcionam; chips (em ciclo / externo / folhas) filtram em AND e mostram contagem.
  - Clicar num header ordena (e re-clicar inverte a direção); default é `Depende de` desc.
  - Clicar numa linha seleciona (destaque), abre o detalhe à direita e a URL vira `…/egps?egp=<id>`.
  - Recarregar (F5) numa URL `?egp=<id>` reabre o mesmo EGP; voltar/avançar do navegador troca a seleção.
  - No detalhe: editar status/responsável/observação persiste (PATCH) — igual ao comportamento antigo.
  - A tabela de inputs no painel direito rola (não some conteúdo) quando aperta.

- [ ] **Step 3: Revisão adversarial do diff**

Disparar uma revisão (agente `feature-dev:code-reviewer`) sobre o diff das Tasks 1–4, focada em: efeitos do React (cancelamento de fetch com `alive`, StrictMode), corretude do estado de seleção/URL (pushState/popstate, query param preservando outros params), e regressões na edição inline.

- [ ] **Step 4: Commit de ajustes (se a revisão apontar algo)**

```bash
git add -A egps_analysis/app/frontend
git commit -m "fix(egps): ajustes da revisao da aba master-detail"
```

---

## Fora do plano (passo de operação)

O **deploy** (sync + `databricks apps deploy monitoramento-sas`) é um passo de operação separado, disparado pelo usuário quando a verificação manual estiver ok — não faz parte deste plano de implementação. Lembrar do rebuild do front antes (já coberto pela Task 5/Step 1) e do hard-refresh (o hash do bundle muda).
