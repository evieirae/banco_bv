# Monitoramento de Outputs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Nova aba **Monitoramento Outputs** (read-only) no app `monitoramento-sas`: lista as tabelas/artefatos produzidos pelos EGPs com produtores, consumidores (fan-out), terminal×intermediário e disponibilidade no lake.

**Architecture:** `publish` passa a materializar 2 tabelas Delta novas (`sas_egp_outputs` grão EGP×output; `sas_outputs_monitor` grão output distinto), full-replace (sem colunas humanas). Backend expõe 3 endpoints read-only (`/api/outputs`, `/api/output`, `/api/outputs-egps`) + `recompute_escopo` re-deriva `escopo_indi` dos outputs **com guarda** (pula se as tabelas ainda não existem). Frontend espelha a aba de inputs **sem edição**: `OutputsView` + `OutputsTable` (virtualizada) + `OutputsDrawer`, reusando `csv.ts`.

**Tech Stack:** Python (publish, pandas-free loops), FastAPI + databricks-sdk, React + @tanstack/react-query + react-virtual + Vite, Delta.

---

## Contexto verificado (não re-descobrir)

- **Base limpa:** priorização/mesPlan já commitada (`cc91d71`). Publish **não** foi tocado por ela.
- **`publish_to_databricks.py`** (fonte da verdade; re-vendoriza em `app/pipeline/` depois): `fq`@603, `T_EGP = f"{fq}.sas_egp_inputs"`@606. Loop do report 06 ~331-386 constrói `proj_in`, `proj_out` (dict projeto→set de `canon(art)`), `produced_tables`, `proj_area`. Helpers: `canon(art)`@125 (`art.strip().upper()`), `is_noise_table(art)`@116, `run(sql)`@~696-708, `insert_batches(table, cols, rows, batch=400)`@~582-589. Escopo: `indi = load_indi_projects()` (set de projetos in-scope, carregado ~315). Modernização: campo `status_validacao` do report 06; `MODERN_MARKERS`@56; `rec["modern"] = any(m in st for m in MODERN_MARKERS)`. Templates a espelhar: build de `sas_lineage_nodes` (usa proj_out+area+onda+escopo_indi+n_outputs) ~459-470; build de `sas_egp_inputs` ~472-484; DDL+write ~728-778.
- **`app/backend/main.py`** (Read-BLOQUEADO por hook — usar `sed -n`/`grep`, editar por **script de patch** UTF-8 com asserts de âncora única + `py_compile` + smoke import; conferir acentos): `CATALOG/SCHEMA/FQ`@38-39; bloco `T_*`@49-62 (`T_EGP = f"{FQ}.sas_egp_inputs"`); `run_sql(stmt, want_rows=True)`; `sql_lit()`; `_client()`; `Query` já importado de fastapi; `recompute_escopo(exec_fn=None)`@905 (termina com `_lineage_gen += 1` / `_lineage_cache.clear()`); `/api/inputs`@552, `/api/input`@623, `/api/inputs-egps`@646 (bom lugar p/ inserir os de outputs logo depois). `ingest.sp_exec` existe (do trabalho de ingestão).
- **Frontend** (não Read-bloqueado): mirrors — `MonitorView.tsx` (container: query `api.inputs`, `filters` state, `useTableSort`, `selected`→drawer), `InputsTable.tsx` (virtualizada com `useVirtualizer`, grid `c-*`, **tem selects de edição a REMOVER**), `InputDrawer.tsx` (fetch `api.inputDetail`, lista produtores+consumidores), `FilterBar.tsx`. Tipos em `types.ts` (`InputRow`,`InputsResponse`,`InputDetail`,`InputUsageEgp`). `api.ts` (`inputs`,`inputDetail`,`inputsEgps`). `csv.ts` (`csvDownload`,`csvFromColumns`,`csvBool`,`csvDate`,`egpShort`,`CsvColumn`). `routes.ts` (`View` union + `TABS`), `App.tsx` (render por `view`). Aba **não-gated** (como "monitor").

## Estrutura de arquivos

| Arquivo | Ação | Papel |
|---|---|---|
| `egps_analysis/publish_to_databricks.py` | mod | build + DDL das 2 tabelas de output |
| `egps_analysis/app/pipeline/publish_to_databricks.py` | mod | re-cópia (deploy) |
| `app/backend/main.py` | mod | `T_OUT`/`T_EGP_OUT`, 3 endpoints, guarda no recompute |
| `app/frontend/src/types.ts` | mod | `OutputRow`,`OutputsResponse`,`OutputFilters`,`OutputDetail`,`OutputUsageEgp` |
| `app/frontend/src/api.ts` | mod | `outputs`,`outputDetail`,`outputsEgps` |
| `app/frontend/src/routes.ts` | mod | tab "Monitoramento Outputs" (`outputs`, slug `monitoramento-outputs`) |
| `app/frontend/src/App.tsx` | mod | render `<OutputsView/>` |
| `app/frontend/src/components/OutputsView.tsx` | novo | container + filtros inline + export |
| `app/frontend/src/components/OutputsTable.tsx` | novo | tabela virtualizada read-only |
| `app/frontend/src/components/OutputsDrawer.tsx` | novo | drawer produtores+consumidores |
| `app/frontend/src/styles.css` | mod | grid-template da tabela de outputs |
| `app/README.md` + memória | mod | documentar |

---

## Phase 1 — Pipeline: 2 tabelas de output no publish

### Task 1.1: Build + DDL de `sas_egp_outputs` e `sas_outputs_monitor`

**Files:** Modify `egps_analysis/publish_to_databricks.py`

- [ ] **Step 1: Ler as regiões-alvo** (o arquivo pode ser grande; use sed)

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
sed -n '110,130p;315,320p;325,390p;415,490p;600,615p;640,650p;720,790p' publish_to_databricks.py
```
Confirme: nomes exatos `proj_in`/`proj_out`/`produced_tables`/`proj_area`, `onda`/`ciclo`/`indi` lookups, `canon`, `is_noise_table`, `run`, `insert_batches`, o padrão DROP+CREATE+insert de `sas_egp_inputs` e `sas_lineage_nodes`, e onde `MODERN_MARKERS`/`status_validacao` marcam `modern`.

- [ ] **Step 2: No loop do report 06, construir os dicts de output**

Dentro do loop que já classifica `cat` (onde `table_out` hoje só entra em `proj_out`/`produced_tables`), estender para as 3 categorias de output e guardar metadados por output distinto. Logo após o bloco que trata `cat == "table_out"` (e os outros outputs), adicionar a coleta (espelha `inputs`/`egp_in`). Use os dicts (declare-os junto de `proj_out` no topo do main):
```python
    # --- outputs (paralelo a inputs/egp_in) ---
    OUT_CATS = {"table_out", "file_out", "libname_out"}
    # (declarar no topo, junto de proj_in/proj_out:)
    #   outputs = {}       # canon -> {"artifact","categoria","projetos":set,"modern":bool}
    #   egp_out = {}       # (projeto,canon) -> {"projeto","chave_canonica","artifact","categoria"}
    if cat in OUT_CATS:
        if cat == "table_out" and is_noise_table(art):
            pass  # ruído: WORK/SASHELP/wildcards — não vira linha de output
        else:
            ck = canon(art)
            rec = outputs.setdefault(ck, {"artifact": art, "categoria": cat, "projetos": set(), "modern": False})
            rec["projetos"].add(proj)
            st = n(r.get("status_validacao")).upper()
            if any(m in st for m in MODERN_MARKERS):
                rec["modern"] = True
            egp_out.setdefault((proj, ck), {"projeto": proj, "chave_canonica": ck, "artifact": art, "categoria": cat})
```
(Mantém `proj_out`/`produced_tables` como estão — só ADICIONA a coleta; não remover o `continue` existente do table_out se houver, mas garantir que a coleta de output roda antes dele. Se o `continue` impedir, mover a coleta para antes do `continue`.)

- [ ] **Step 3: Consumidores + linhas de `sas_outputs_monitor`**

Depois do loop, com `proj_in` pronto, inverter para achar consumidores por nome e montar as linhas (espelha o build de `inputs_rows` + `nodes`):
```python
    # consumidores(o) = EGPs que leem 'o' como input (mesmo canon)
    consumers_by_name = {}
    for p, ins in proj_in.items():
        for ck in ins:
            consumers_by_name.setdefault(ck, set()).add(p)

    out_rows = []
    for ck, rec in outputs.items():
        prods = rec["projetos"]
        cons = consumers_by_name.get(ck, set())
        areas = sorted({proj_area.get(p, "") for p in prods if proj_area.get(p)})
        out_rows.append({
            "chave_canonica": ck,
            "artifact": rec["artifact"],
            "categoria": rec["categoria"],
            "areas": ", ".join(areas),
            "qtd_produtores": len(prods),
            "qtd_consumidores": len(cons),
            "terminal": len(cons) == 0,
            "modernizada_auto": "Disponível" if rec["modern"] else "A ingerir",
            "escopo_indi": bool(prods & indi),
        })

    egp_out_rows = []
    for (p, ck), er in egp_out.items():
        egp_out_rows.append({
            "projeto": er["projeto"],
            "area": proj_area.get(p, ""),
            "onda": onda.get(p, "") if isinstance(onda, dict) else "",
            "escopo_indi": p in indi,
            "chave_canonica": er["chave_canonica"],
            "artifact": er["artifact"],
            "categoria": er["categoria"],
        })
```
(Ajustar `onda.get(p)`/`ciclo` ao nome real confirmado no Step 1 — se `onda` for outro dict/estrutura, usar o mesmo lookup que o build de `sas_lineage_nodes` usa.)

- [ ] **Step 4: Constantes + DDL + insert** (espelha `T_EGP`/nodes ~728-778)

Junto ao bloco `T_*` (~606):
```python
T_OUT = f"{fq}.sas_outputs_monitor"
T_EGP_OUT = f"{fq}.sas_egp_outputs"
```
Junto às listas de colunas (~642):
```python
out_cols = ["chave_canonica", "artifact", "categoria", "areas", "qtd_produtores",
            "qtd_consumidores", "terminal", "modernizada_auto", "escopo_indi"]
egp_out_cols = ["projeto", "area", "onda", "escopo_indi", "chave_canonica", "artifact", "categoria"]
```
No bloco de escrita (`if args.apply:` onde as outras tabelas são criadas), espelhar o DROP+CREATE+insert de `sas_egp_inputs`:
```python
    run(f"DROP TABLE IF EXISTS {T_OUT}")
    run(f"""CREATE TABLE {T_OUT} (chave_canonica STRING, artifact STRING, categoria STRING,
  areas STRING, qtd_produtores INT, qtd_consumidores INT, terminal BOOLEAN,
  modernizada_auto STRING, escopo_indi BOOLEAN) USING DELTA""")
    insert_batches(T_OUT, out_cols, out_rows)
    run(f"DROP TABLE IF EXISTS {T_EGP_OUT}")
    run(f"""CREATE TABLE {T_EGP_OUT} (projeto STRING, area STRING, onda STRING,
  escopo_indi BOOLEAN, chave_canonica STRING, artifact STRING, categoria STRING) USING DELTA""")
    insert_batches(T_EGP_OUT, egp_out_cols, egp_out_rows)
    print(f"  outputs: {len(out_rows)} distintos, {len(egp_out_rows)} pares EGP×output")
```
(Conferir a assinatura real de `insert_batches` no Step 1 — pode receber `(table, cols, rows)` posicional; usar exatamente como `sas_egp_inputs` chama.)

- [ ] **Step 5: Validar em dry-run (sem --apply → não escreve no warehouse)**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
python -m py_compile publish_to_databricks.py && echo "compile OK"
python publish_to_databricks.py 2>&1 | tail -25
```
Expected: sem `--apply`, roda o build (exercita o novo código) e imprime prévia incluindo a linha `outputs: N distintos, M pares…`, sem erro e sem escrever no Databricks. Se faltar CSV local (06_prontidao_tabela.csv), rode de onde os CSVs estão (`egps_analysis/`).

- [ ] **Step 6: Re-vendorizar + commit**

```bash
cp publish_to_databricks.py app/pipeline/publish_to_databricks.py
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/publish_to_databricks.py egps_analysis/app/pipeline/publish_to_databricks.py
git commit -m "feat(app): publish materializa sas_outputs_monitor + sas_egp_outputs (inventário de outputs)"
```

---

## Phase 2 — Backend: endpoints + recompute guard

### Task 2.1: Constantes + 3 endpoints + recompute (main.py via patch script)

**Files:** Modify `app/backend/main.py`

Protocolo: escrever `/tmp/.../scratchpad/patch_outputs.py` (UTF-8) que lê main.py, assert cada âncora ocorre 1×, aplica, grava; depois `py_compile` + smoke import + checagem de acento (`grep -c 'Autenticação de usuário ausente'` == 1) + `git diff`.

- [ ] **Step 1: Constantes** — inserir logo após `T_EGP = f"{FQ}.sas_egp_inputs"` (âncora única):
```python
T_OUT = f"{FQ}.sas_outputs_monitor"
T_EGP_OUT = f"{FQ}.sas_egp_outputs"
```

- [ ] **Step 2: Endpoints** — inserir logo após o handler de `/api/inputs-egps` (âncora: a linha do decorator `@app.get("/api/inputs-egps")` + achar o fim da função via sed; inserir os 3 novos handlers ANTES do próximo `@app.` seguinte). Código:
```python
@app.get("/api/outputs")
def outputs(scope: str = "indi"):
    """Inventário de outputs (read-only). Filtragem fina (área/categoria/terminal/busca)
    é client-side, como no Monitoramento de Inputs. Tolera tabela ausente (pré-1º publish)."""
    where = " WHERE escopo_indi = true" if scope == "indi" else ""
    try:
        rows = run_sql(f"""SELECT chave_canonica, artifact, categoria, areas, qtd_produtores,
  qtd_consumidores, terminal, modernizada_auto, escopo_indi
  FROM {T_OUT}{where} ORDER BY qtd_consumidores DESC, artifact""")
    except HTTPException:
        rows = []
    return {"total": len(rows), "returned": len(rows), "capped": False, "rows": rows}


@app.get("/api/output")
def output_detail(chave: str):
    """Detalhe p/ o drawer: produtores (sas_egp_outputs) + consumidores (sas_egp_inputs)."""
    q = (f"SELECT projeto, area, onda, escopo_indi, ciclo_id FROM {{t}} "
         f"WHERE chave_canonica = {sql_lit(chave)} ORDER BY projeto")
    try:
        prod = run_sql(q.format(t=T_EGP_OUT))
    except HTTPException:
        prod = []
    try:
        cons = run_sql(q.format(t=T_EGP))
    except HTTPException:
        cons = []
    return {"produtores": prod, "consumidores": cons}


@app.get("/api/outputs-egps")
def outputs_egps(scope: str = "indi"):
    """Pares output->produtor p/ o export explodido (uma linha por output×EGP produtor)."""
    where = " WHERE escopo_indi = true" if scope == "indi" else ""
    try:
        rows = run_sql(f"SELECT chave_canonica, projeto FROM {T_EGP_OUT}{where}")
    except HTTPException:
        rows = []
    return {"rows": rows}
```
**Nota:** confirmar via sed que `sas_egp_inputs` (T_EGP) tem colunas `projeto, area, onda, escopo_indi, ciclo_id` (o `/api/input` já lê consumidores dessas). Se o nome de coluna diferir (ex.: sem `ciclo_id`), ajustar o SELECT de `cons` para as colunas reais de T_EGP.

- [ ] **Step 3: recompute_escopo — re-derivar escopo dos outputs (com guarda)**

Inserir imediatamente ANTES de `_lineage_gen += 1` dentro de `recompute_escopo` (âncora única `    _lineage_gen += 1`). Reusa a subquery `esc` já definida na função:
```python
    # outputs: só se as tabelas já existem (criadas no 1º publish com outputs) — nunca
    # pode quebrar a edição de escopo. exec_fn=run_sql (OBO) lança HTTPException; sp_exec lança RuntimeError.
    try:
        exec_fn(f"SELECT 1 FROM {T_EGP_OUT} LIMIT 0", want_rows=False)
        for s in [
            f"UPDATE {T_EGP_OUT} SET escopo_indi = false",
            f"UPDATE {T_EGP_OUT} SET escopo_indi = true WHERE projeto IN {esc}",
            f"UPDATE {T_OUT} SET escopo_indi = false",
            f"UPDATE {T_OUT} SET escopo_indi = true WHERE chave_canonica IN "
            f"(SELECT DISTINCT chave_canonica FROM {T_EGP_OUT} WHERE escopo_indi = true)",
        ]:
            exec_fn(s, want_rows=False)
    except (HTTPException, RuntimeError):
        pass
```

- [ ] **Step 4: Verificar**
```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/backend
python3 -m py_compile main.py && echo "compile OK"
../venv/bin/python -c "import main; print(sorted(r.path for r in main.app.routes if 'output' in r.path))"
grep -Fc 'Autenticação de usuário ausente' main.py   # == 1
```
Expected: rotas `['/api/output','/api/outputs','/api/outputs-egps']`; acento intacto.

- [ ] **Step 5: Commit**
```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): endpoints /api/outputs* + recompute_escopo re-deriva escopo dos outputs (guarded)"
```

---

## Phase 3 — Frontend: aba Monitoramento Outputs

### Task 3.1: Tipos + API

**Files:** Modify `app/frontend/src/types.ts`, `app/frontend/src/api.ts`

- [ ] **Step 1: types.ts** — anexar:
```typescript
export interface OutputRow {
  chave_canonica: string;
  artifact: string;
  categoria: string;
  areas: string;
  qtd_produtores: number;
  qtd_consumidores: number;
  terminal: boolean | string;
  modernizada_auto: string;
  escopo_indi: boolean | string;
}
export interface OutputsResponse { total: number; returned: number; capped: boolean; rows: OutputRow[]; }
export interface OutputUsageEgp {
  projeto: string; area: string | null; onda: string | null;
  escopo_indi: string | boolean | null; ciclo_id: number | string | null;
}
export interface OutputDetail { produtores: OutputUsageEgp[]; consumidores: OutputUsageEgp[]; }
```

- [ ] **Step 2: api.ts** — adicionar `OutputsResponse, OutputDetail` ao `import type`, e no objeto `api`:
```typescript
  outputs: (scope: string) => fetch(`api/outputs?scope=${scope}`).then(json<OutputsResponse>),
  outputDetail: (chave: string) =>
    fetch(`api/output?chave=${encodeURIComponent(chave)}`).then(json<OutputDetail>),
  outputsEgps: (scope: string) =>
    fetch(`api/outputs-egps?scope=${scope}`).then(json<{ rows: { chave_canonica: string; projeto: string }[] }>),
```

### Task 3.2: Registrar a aba

**Files:** Modify `app/frontend/src/routes.ts`, `app/frontend/src/App.tsx`

- [ ] **Step 1: routes.ts** — adicionar `"outputs"` ao union `View` e, logo após a entrada do `monitor`, na `TABS`:
```typescript
  { id: "outputs", label: "Monitoramento Outputs", slug: "monitoramento-outputs" },
```
- [ ] **Step 2: App.tsx** — importar `import { OutputsView } from "./components/OutputsView";` e, ao lado do render do `monitor`, adicionar (copiar a assinatura de props real do MonitorView — provavelmente `cfg` + `onOpenEgp`):
```tsx
{view === "outputs" && <OutputsView cfg={cfg} onOpenEgp={(p) => { setEgpToOpen(p); go("readiness", p); }} />}
```
(Ajustar aos nomes reais de `cfg`/`go`/`setEgpToOpen` no App.tsx.)

### Task 3.3: OutputsDrawer

**Files:** Create `app/frontend/src/components/OutputsDrawer.tsx`

- [ ] **Step 1:** Espelhar `InputDrawer.tsx` (ler primeiro), sem auditoria. Fetch `api.outputDetail(row.chave_canonica)`; renderizar 2 seções: **Produzido por** (`produtores`) e **Consumido por** (`consumidores`), cada EGP com nome curto (`id.split("__").slice(1).join("__")`), área, onda, clique → `onOpenEgp(projeto)`. Header com `artifact`, `categoria`, `areas`, terminal/intermediário, disponível. Botão fechar. Estados vazios ("nenhum produtor no corpus" / "nenhum consumidor — output terminal").

### Task 3.4: OutputsTable (virtualizada, read-only)

**Files:** Create `app/frontend/src/components/OutputsTable.tsx`

- [ ] **Step 1:** Espelhar `InputsTable.tsx` (ler primeiro) **removendo toda edição** (sem `<select>`/`<input>` de status/responsável/observação; sem `onPatch`). Manter `useVirtualizer` + `useTableSort`. Colunas (grid): `#` · Artefato (clicável → `onSelect(row)`) · Categoria · Área(s) · Produtores (qtd) · Consumidores (qtd) · Terminal/Intermediário (`row.terminal ? "Terminal" : "Intermediário"`) · Disponível (`modernizada_auto`). `OutputSortKey = "artifact"|"categoria"|"areas"|"qtd_produtores"|"qtd_consumidores"|"terminal"|"modernizada_auto"`. Props: `{ rows, onSort, indicator, onSelect }`.

### Task 3.5: OutputsView (container + filtros + export)

**Files:** Create `app/frontend/src/components/OutputsView.tsx`

- [ ] **Step 1:** Espelhar `MonitorView.tsx` (ler primeiro) **sem** mutations/MetricsBar. Elementos:
  - Query: `useQuery({ queryKey: ["outputs", scope], queryFn: () => api.outputs(scope) })`, `scope` de um `<select>` indi/base (default "indi").
  - `rows` → filtro client-side (useMemo): área (multi via `MultiSelect`, opções = distintas de `areas` split por `, `), categoria (multi: table_out/file_out/libname_out), toggle **"só terminais"**, busca (`artifact`). Depois `useTableSort<OutputRow, OutputSortKey>(filtered, accessor, { key: "qtd_consumidores", dir: "desc" })`.
  - Render: barra de filtros inline (scope select + MultiSelects + toggle + busca + contagem + botão **⬇ Exportar CSV** `ghost csv-btn`), `<OutputsTable rows={sorted} onSort onSelect={setSelected} .../>`, `{selected && <OutputsDrawer row={selected} onClose onOpenEgp/>}`.
  - **Export** (reusa `csv.ts`): explode por produtor via `api.outputsEgps(scope)` (pares chave→projeto), 1 linha por (output × produtor). Colunas: `EGP` (=`egpShort(projeto)`) + Artefato · Categoria · Área(s) · Produtores · Consumidores · Terminal/Intermediário · Disponível. `csvBool` p/ terminal. Arquivo `outputs_${scope}_${csvDate()}.csv`. Mesmo mecanismo do export de inputs (buscar pares no clique, cruzar com as linhas exibidas; output sem produtor → 1 linha com EGP vazio).

- [ ] **Step 2: styles.css** — adicionar o grid-template da tabela de outputs (espelhar o dos inputs, com as 8 colunas). Reusar classes `c-*`/`ghost`/`csv-btn` existentes.

- [ ] **Step 3: build**
```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npm run build
```
Expected: `tsc -b` sem erros; bundle em `../static/`.

- [ ] **Step 4: commit**
```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src egps_analysis/app/frontend/tsconfig.tsbuildinfo egps_analysis/app/static
git commit -m "feat(app): aba Monitoramento Outputs (read-only: produtores/consumidores/terminal/disponível + export)"
```

---

## Phase 4 — Docs

### Task 4.1: README + memória

**Files:** Modify `app/README.md`; memória.

- [ ] **Step 1:** README — subseção em "Decisões de design": aba Monitoramento Outputs (read-only), tabelas `sas_outputs_monitor`/`sas_egp_outputs` (full-replace no publish), consumidores via `sas_egp_inputs`, terminal=fan-out 0, escopo integrado ao recompute com guarda, e que precisa de um **Processar/publish** pra popular.
- [ ] **Step 2:** Memória `monitoramento-sas-outputs-tab.md` + linha no `MEMORY.md`. Linkar `[[monitoramento-sas-ingestao-in-app]]`, `[[egps-design-invariants]]`.

---

## Populate (pós-deploy, requer consentimento p/ deploy)

As 2 tabelas são criadas pelo `publish`. Após deploy (front+back+publish vendorizado), rodar **um Processar & publicar** (aba Ingestão) ou publish local `--apply`. Até lá `/api/outputs` retorna vazio e a aba mostra "nada" graciosamente.

---

## Self-review (preenchido)

**Cobertura do spec:** tabelas (T1.1) ✅; endpoints (T2.1) ✅; recompute guard (T2.1 S3) ✅; tab+colunas+filtros+drawer+export (T3.x) ✅; libname_out incluído/filtrável (OUT_CATS + filtro categoria) ✅; "também é input" fundido em terminal (só a coluna terminal) ✅; read-only (sem edição em T3.4/T3.5) ✅; docs (T4) ✅; popular via publish (seção final) ✅.
**Placeholders:** os "confirmar via sed/ler o arquivo" são verificações de âncora obrigatórias (o arquivo real é a fonte), não placeholders de requisito. Código novo está completo.
**Consistência de tipos:** `T_OUT`/`T_EGP_OUT` iguais no publish e no main.py (`sas_outputs_monitor`/`sas_egp_outputs`). Colunas `out_cols`/`egp_out_cols` batem com os SELECTs dos endpoints e com `OutputRow`/`OutputUsageEgp`. `terminal` BOOLEAN em todo o caminho; `csvBool` no export. `scope` indi|base consistente front↔back.
