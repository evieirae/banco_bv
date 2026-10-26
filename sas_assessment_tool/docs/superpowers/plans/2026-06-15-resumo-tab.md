# Aba "Resumo" (funil + inputs por origem) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nova aba read-only "Resumo" no app com 2 tabelas (funil por área DOR1 + inputs por origem, modernizado/não ao vivo).

**Architecture:** O `publish` cria 2 tabelas Delta (`sas_resumo_inputs`, `sas_funil_area`) sem tocar no `sas_inputs_monitor`. O backend expõe `GET /api/resumo` que junta `sas_resumo_inputs` com `sas_inputs_monitor` para o status humano ao vivo. O front ganha `ResumoView.tsx` como primeira aba (`/resumo`).

**Tech Stack:** Python (publish, stdlib) · FastAPI + databricks-sdk (backend) · React 18 + TypeScript/Vite (front).

---

## File Structure

| Arquivo | Mudança | Responsabilidade |
|---|---|---|
| `egps_analysis/publish_to_databricks.py` | modificar | `build()` deriva `resumo` (input distinto + `area_principal` + `origem_bucket`, inclui `libname_in`) e `funil` (do `indi_231`); `main()` grava `sas_resumo_inputs` + `sas_funil_area`. |
| `egps_analysis/app/backend/main.py` | modificar | Endpoint `GET /api/resumo` (join com monitor p/ status ao vivo). |
| `egps_analysis/app/frontend/src/types.ts` | modificar | `ResumoFunilRow`, `ResumoOrigemRow`, `ResumoPayload`. |
| `egps_analysis/app/frontend/src/api.ts` | modificar | `resumo()`. |
| `egps_analysis/app/frontend/src/components/ResumoView.tsx` | criar | As 2 tabelas. |
| `egps_analysis/app/frontend/src/App.tsx` | modificar | Aba "Resumo" (primeira, slug `resumo`). |
| `egps_analysis/app/frontend/src/styles.css` | modificar | `.resumo` + `.rsm-tbl`. |

Sem mudança em `sas_inputs_monitor` nem nas outras abas.

---

### Task 1: Publish — build + grava `sas_resumo_inputs` e `sas_funil_area`

**Files:**
- Modify: `egps_analysis/publish_to_databricks.py`

- [ ] **Step 1: Adicionar a função pura `origem_bucket` + constante `RES_CATS` (nível de módulo)**

Inserir logo após a definição de `IN_CATS`/`MODERN_MARKERS` (perto da linha 44):

```python
# universo do resumo = inputs do monitor + libname_in (re-incluído só p/ a aba Resumo)
RES_CATS = {"table_in": "tabela", "file_in": "arquivo", "script_in": "script", "libname_in": "lib"}
_TRANS_SRC = ("POSTGRES", "SYBASE", "SYBASEIQ", "IQ", "SQLSVR", "DBCON", "DBCONN", "ASE")


def origem_bucket(source_types, categoria):
    """Classifica um input distinto num bucket de origem (prioridade)."""
    sts = {s.upper() for s in source_types if s}
    if any("BIGQUERY" in s for s in sts):
        return "BigQuery"
    if categoria == "lib":
        return "Libname_in"
    if categoria == "arquivo":
        return "Arquivo"
    if any(any(t in s for t in _TRANS_SRC) for s in sts):
        return "Transacional"
    return "SAS/Local"
```

- [ ] **Step 2: Testar `origem_bucket` (função pura)**

Run (de `egps_analysis/`):

```bash
cd egps_analysis && python3 -c "
from publish_to_databricks import origem_bucket
assert origem_bucket({'BIGQUERY'}, 'tabela') == 'BigQuery'
assert origem_bucket({'BIGQUERY/GCP'}, 'tabela') == 'BigQuery'
assert origem_bucket(set(), 'lib') == 'Libname_in'
assert origem_bucket({'SAS/Local'}, 'arquivo') == 'Arquivo'
assert origem_bucket({'POSTGRES'}, 'tabela') == 'Transacional'
assert origem_bucket({'SYBASEIQ'}, 'tabela') == 'Transacional'
assert origem_bucket({'SAS/Local'}, 'tabela') == 'SAS/Local'
assert origem_bucket({'Avaliar',''}, 'script') == 'SAS/Local'
print('origem_bucket OK')
"
```

Expected: `origem_bucket OK` (exit 0).

- [ ] **Step 3: Acumular `resumo` dentro do loop de R06 em `build()`**

Em `build()`, declarar o dict junto dos outros acumuladores (perto de `inputs = {}`):

```python
    resumo = {}  # rkey -> dict (input distinto p/ a aba Resumo; inclui libname_in)
```

Dentro do `for r in csv.DictReader(f):`, **logo após** o bloco `if cat == "table_out": ... continue` e **antes** de `if cat not in IN_CATS: continue`, inserir:

```python
            if cat in RES_CATS and not (cat == "table_in" and is_noise_table(art)):
                rcat = RES_CATS[cat]
                rkey = f"{rcat}::{canon(art)}"
                rr = resumo.get(rkey)
                if rr is None:
                    rr = resumo[rkey] = {
                        "chave_canonica": rkey, "categoria": rcat,
                        "source_types": set(), "area_count": collections.Counter(),
                        "projetos": set(), "modern": False,
                    }
                rr["source_types"].add(n(r.get("source_type")))
                rr["area_count"][AREA_OVERRIDE.get(proj, n(r.get("area")) or "(sem área)")] += 1
                rr["projetos"].add(proj)
                _stv = n(r.get("status_validacao")).upper()
                if any(m in _stv for m in MODERN_MARKERS):
                    rr["modern"] = True
```

- [ ] **Step 4: Montar `resumo_rows` e `funil_rows` antes do `return` de `build()`**

Inserir logo antes do `return {...}` final de `build()`:

```python
    # ---- resumo_inputs (input distinto: area_principal + origem_bucket) ----
    resumo_rows = []
    for rr in resumo.values():
        ac = rr["area_count"]
        if ac:
            top = max(ac.values())
            area_principal = sorted(a for a, c in ac.items() if c == top)[0]
        else:
            area_principal = "(sem área)"
        resumo_rows.append({
            "chave_canonica": rr["chave_canonica"],
            "area_principal": area_principal,
            "origem_bucket": origem_bucket(rr["source_types"], rr["categoria"]),
            "escopo_indi": bool(rr["projetos"] & indi),
            "modernizada_auto": "Disponível" if rr["modern"] else "A ingerir",
        })

    # ---- funil_area (do indi_231: DOR1 / Enviados / Analisados) ----
    ANALISADO = {"exato", "variante", "confirmado_area"}
    funil_acc = collections.defaultdict(lambda: [0, 0, 0])
    if os.path.exists(INDI):
        with open(INDI, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                a = n(r.get("area"))
                stt = n(r.get("status_extracao"))
                funil_acc[a][0] += 1
                if stt != "faltante":
                    funil_acc[a][1] += 1
                if stt in ANALISADO:
                    funil_acc[a][2] += 1
    funil_rows = [{"area": a, "qtd_dor1": v[0], "egps_enviados": v[1], "egps_analisados": v[2]}
                  for a, v in sorted(funil_acc.items())]
```

E acrescentar ao dict do `return`:

```python
            "resumo": resumo_rows, "funil": funil_rows,
```

- [ ] **Step 5: Em `main()`, declarar tabelas, imprimir no resumo e gravar no `--apply`**

Junto das constantes de tabela (perto de `T_EGP = ...`):

```python
    T_RES = f"{fq}.sas_resumo_inputs"
    T_FUN = f"{fq}.sas_funil_area"
```

No bloco de print (após a linha do `egp_inputs`):

```python
    print(f"  resumo_inputs  : {len(data['resumo']):6d}  (input distinto + origem/area)")
    print(f"  funil_area     : {len(data['funil']):6d}  (areas)")
```

Definir as colunas junto das outras (`egp_cols = ...`):

```python
    res_cols = ["chave_canonica", "area_principal", "origem_bucket", "escopo_indi", "modernizada_auto"]
    fun_cols = ["area", "qtd_dor1", "egps_enviados", "egps_analisados"]
```

No `--apply`, após o bloco que grava `egp_inputs` (full replace), inserir:

```python
    # resumo_inputs + funil_area — full replace
    run(f"DROP TABLE IF EXISTS {T_RES}")
    run(f"""CREATE TABLE {T_RES} (chave_canonica STRING, area_principal STRING,
  origem_bucket STRING, escopo_indi BOOLEAN, modernizada_auto STRING) USING DELTA""")
    for st in insert_batches(T_RES, res_cols, data["resumo"]):
        run(st)
    run(f"DROP TABLE IF EXISTS {T_FUN}")
    run(f"""CREATE TABLE {T_FUN} (area STRING, qtd_dor1 INT,
  egps_enviados INT, egps_analisados INT) USING DELTA""")
    for st in insert_batches(T_FUN, fun_cols, data["funil"]):
        run(st)
    print(f"  resumo_inputs ({len(data['resumo'])}) + funil_area ({len(data['funil'])}) recriadas")
```

- [ ] **Step 6: Dry-run para validar o build (não conecta)**

Run (de `egps_analysis/`):

```bash
cd egps_analysis && python3 publish_to_databricks.py --catalog client_journey --schema monitoramento_sas
```

Expected: imprime `resumo_inputs : <N>` e `funil_area : <N>` sem erro; `[dry-run]` no fim. Anotar os valores.

- [ ] **Step 7: Commit**

```bash
git add egps_analysis/publish_to_databricks.py
git commit -m "feat(publish): tabelas sas_resumo_inputs e sas_funil_area p/ a aba Resumo"
```

---

### Task 2: Backend — endpoint `GET /api/resumo`

**Files:**
- Modify: `egps_analysis/app/backend/main.py`

- [ ] **Step 1: Declarar as tabelas novas**

Junto das constantes de tabela (perto de `T_AUD = ...`, linha ~45):

```python
T_RES = f"{FQ}.sas_resumo_inputs"
T_FUN = f"{FQ}.sas_funil_area"
```

- [ ] **Step 2: Adicionar o endpoint**

Inserir antes do bloco de estáticos (antes de `# ---- estáticos (SPA) ...`):

```python
@app.get("/api/resumo")
def resumo():
    eff = "coalesce(nullif(i.status_humano,''), i.modernizada_auto, r.modernizada_auto)"
    modern = f"({eff} IN ('Disponível','Sanitizada'))"
    frm = (f"{T_RES} r LEFT JOIN {T_IN} i ON r.chave_canonica = i.chave_canonica "
           f"WHERE r.escopo_indi = true")
    origem = run_sql(
        f"SELECT r.origem_bucket AS bucket, count(*) AS total, "
        f"count(CASE WHEN {modern} THEN 1 END) AS modernizado, "
        f"count(CASE WHEN NOT {modern} THEN 1 END) AS nao_modernizado "
        f"FROM {frm} GROUP BY r.origem_bucket")
    nao_area = run_sql(
        f"SELECT r.area_principal AS area, "
        f"count(CASE WHEN NOT {modern} THEN 1 END) AS nao_mod "
        f"FROM {frm} GROUP BY r.area_principal")
    funil = run_sql(f"SELECT area, qtd_dor1, egps_enviados, egps_analisados FROM {T_FUN}")

    nm = {x["area"]: int(x["nao_mod"]) for x in nao_area}
    frows, ftot = [], {"qtd_dor1": 0, "egps_enviados": 0, "egps_analisados": 0, "inputs_nao_modernizados": 0}
    for x in funil:
        row = {"area": x["area"], "qtd_dor1": int(x["qtd_dor1"]),
               "egps_enviados": int(x["egps_enviados"]), "egps_analisados": int(x["egps_analisados"]),
               "inputs_nao_modernizados": nm.get(x["area"], 0)}
        for k in ftot:
            ftot[k] += row[k]
        frows.append(row)
    frows.sort(key=lambda r: -r["qtd_dor1"])

    BUCKET_ORDER = ["BigQuery", "Libname_in", "Arquivo", "Transacional", "SAS/Local"]
    om = {x["bucket"]: x for x in origem}
    orows, otot = [], {"total": 0, "modernizado": 0, "nao_modernizado": 0}
    for b in BUCKET_ORDER:
        x = om.get(b)
        row = {"bucket": b,
               "total": int(x["total"]) if x else 0,
               "modernizado": int(x["modernizado"]) if x else 0,
               "nao_modernizado": int(x["nao_modernizado"]) if x else 0}
        for k in otot:
            otot[k] += row[k]
        orows.append(row)

    return {"funil": {"rows": frows, "total": ftot},
            "origem": {"rows": orows, "total": otot}}
```

- [ ] **Step 3: Verificar sintaxe**

Run: `python3 -m py_compile egps_analysis/app/backend/main.py && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app/backend): endpoint GET /api/resumo (funil + inputs por origem)"
```

> Verificação ao vivo do endpoint acontece na Task 6 (após o re-publish criar as tabelas).

---

### Task 3: Frontend — tipos + api

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts`
- Modify: `egps_analysis/app/frontend/src/api.ts`

- [ ] **Step 1: Adicionar os tipos**

Acrescentar ao final de `types.ts`:

```ts
export interface ResumoFunilRow {
  area: string;
  qtd_dor1: number;
  egps_enviados: number;
  egps_analisados: number;
  inputs_nao_modernizados: number;
}

export interface ResumoOrigemRow {
  bucket: string;
  total: number;
  modernizado: number;
  nao_modernizado: number;
}

export interface ResumoPayload {
  funil: {
    rows: ResumoFunilRow[];
    total: { qtd_dor1: number; egps_enviados: number; egps_analisados: number; inputs_nao_modernizados: number };
  };
  origem: {
    rows: ResumoOrigemRow[];
    total: { total: number; modernizado: number; nao_modernizado: number };
  };
}
```

- [ ] **Step 2: Adicionar o método na api**

Em `api.ts`, no import de tipos acrescentar `ResumoPayload`, e dentro do objeto `api`:

```ts
  resumo: () => fetch("api/resumo").then(json<ResumoPayload>),
```

- [ ] **Step 3: Verificar o build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build sem erros (tipos novos não usados ainda, mas válidos).

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app/front): tipos + api.resumo() p/ a aba Resumo"
```

---

### Task 4: Frontend — componente `ResumoView.tsx`

**Files:**
- Create: `egps_analysis/app/frontend/src/components/ResumoView.tsx`

- [ ] **Step 1: Criar o componente**

Criar `egps_analysis/app/frontend/src/components/ResumoView.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api } from "../api";
import type { ResumoPayload } from "../types";

export function ResumoView() {
  const [data, setData] = useState<ResumoPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.resumo().then(setData).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="error">{err}</div>;
  if (!data) return <div className="empty">carregando…</div>;

  const { funil: f, origem: o } = data;

  return (
    <div className="resumo">
      <h3>Funil por área (DOR1)</h3>
      <table className="rsm-tbl">
        <thead>
          <tr><th>Área</th><th>Qtd. Projetos DOR 1</th><th>EGPs Enviados</th><th>EGPs Analisados</th><th>Inputs não Modernizados</th></tr>
        </thead>
        <tbody>
          {f.rows.map((r) => (
            <tr key={r.area}>
              <td>{r.area}</td><td>{r.qtd_dor1}</td><td>{r.egps_enviados}</td><td>{r.egps_analisados}</td><td>{r.inputs_nao_modernizados}</td>
            </tr>
          ))}
          <tr className="tot">
            <td>Total</td><td>{f.total.qtd_dor1}</td><td>{f.total.egps_enviados}</td><td>{f.total.egps_analisados}</td><td>{f.total.inputs_nao_modernizados}</td>
          </tr>
        </tbody>
      </table>

      <h3>Inputs por origem (DOR1)</h3>
      <table className="rsm-tbl">
        <thead>
          <tr><th>Origem</th><th>Total</th><th>Modernizado</th><th>Não Modernizado</th></tr>
        </thead>
        <tbody>
          {o.rows.map((r) => (
            <tr key={r.bucket}>
              <td>{r.bucket}</td><td>{r.total}</td><td>{r.modernizado}</td><td>{r.nao_modernizado}</td>
            </tr>
          ))}
          <tr className="tot">
            <td>Total</td><td>{o.total.total}</td><td>{o.total.modernizado}</td><td>{o.total.nao_modernizado}</td>
          </tr>
        </tbody>
      </table>

      <p className="muted">Modernizado = status efetivo Disponível/Sanitizada (humano prevalece sobre o auto). Escopo: DOR1 (Indicium).</p>
    </div>
  );
}
```

- [ ] **Step 2: Verificar o build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build sem erros. (Componente ainda não importado — arquivo não usado é ok.)

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/frontend/src/components/ResumoView.tsx
git commit -m "feat(app/front): ResumoView com as 2 tabelas"
```

---

### Task 5: Frontend — aba na App.tsx + CSS

**Files:**
- Modify: `egps_analysis/app/frontend/src/App.tsx`
- Modify: `egps_analysis/app/frontend/src/styles.css`

- [ ] **Step 1: Importar e registrar a aba em App.tsx**

Adicionar o import junto dos outros componentes de view:

```tsx
import { ResumoView } from "./components/ResumoView";
```

Trocar o `type View` para incluir `"resumo"`:

```tsx
type View = "resumo" | "monitor" | "egp" | "readiness" | "waves" | "lineage" | "history";
```

Adicionar `resumo` como **primeira** entrada de `TABS` e tornar default:

```tsx
const TABS: { id: View; label: string; slug: string }[] = [
  { id: "resumo", label: "Resumo", slug: "resumo" },
  { id: "monitor", label: "Monitoramento", slug: "monitoramento" },
  { id: "egp", label: "EGPs", slug: "egps" },
  { id: "readiness", label: "Prontidão", slug: "prontidao" },
  { id: "waves", label: "Ondas", slug: "ondas" },
  { id: "lineage", label: "Linhagem", slug: "linhagem" },
  { id: "history", label: "Histórico", slug: "historico" },
];

const DEFAULT_VIEW: View = "resumo";
```

Adicionar a renderização (antes de `{view === "monitor" && ...}`):

```tsx
      {view === "resumo" && <ResumoView />}
```

- [ ] **Step 2: Adicionar o CSS**

Acrescentar ao final de `styles.css`:

```css
/* aba Resumo */
.resumo { flex: 1; overflow: auto; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
.rsm-tbl { border-collapse: collapse; font-size: 13px; }
.rsm-tbl th, .rsm-tbl td { border: 1px solid var(--line); padding: 6px 14px; text-align: right; }
.rsm-tbl th:first-child, .rsm-tbl td:first-child { text-align: left; }
.rsm-tbl thead th { background: var(--panel2); color: var(--mut); font-weight: 600; }
.rsm-tbl tr.tot td { font-weight: 700; background: var(--panel2); }
```

- [ ] **Step 3: Verificar o build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build sem erros; a aba "Resumo" passa a existir no bundle.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/App.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app/front): aba Resumo (primeira aba, rota /resumo)"
```

---

### Task 6: Operação — re-publish + calibração + redeploy (gate humano)

**Files:** nenhum (operação contra a prod; disparar só após confirmação do usuário).

- [ ] **Step 1: Re-publish (cria as 2 tabelas novas em prod)**

```bash
cd egps_analysis
/home/lucasmuller_ind/bv/sas_assessment_tool/venv/bin/python3 publish_to_databricks.py \
  --apply --profile bv --catalog client_journey --schema monitoramento_sas \
  --warehouse-id 5922c26f81f1bbdd
```
Expected: `✅ PUBLISH concluído.` com linha `resumo_inputs (...) + funil_area (...) recriadas`.

- [ ] **Step 2: Calibrar contra o print**

```bash
databricks experimental aitools tools query "SELECT origem_bucket, count(*) FROM client_journey.monitoramento_sas.sas_resumo_inputs WHERE escopo_indi GROUP BY origem_bucket ORDER BY origem_bucket" --profile bv
```
Conferir a estrutura vs o print (BigQuery 309 / Libname_in 104 / Arquivo 780 / Transacional 91 / SAS-Local 1900). Se a forma divergir muito (não só pelo refresh), revisar as regras `origem_bucket`/`area_principal` na Task 1 e repetir. Anotar deltas atribuíveis ao refresh.

- [ ] **Step 3: Validar o endpoint ao vivo**

```bash
databricks experimental aitools tools query "SELECT 1" --profile bv  # warm-up
# subir backend local OU validar após deploy; conferir GET /api/resumo retorna funil+origem
```

- [ ] **Step 4: Rebuild + sync + deploy**

```bash
cd egps_analysis/app/frontend && npm run build && cd ..
databricks sync . /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas \
  --exclude 'frontend/node_modules/**' --exclude '.databricks/**' --profile bv
databricks apps deploy monitoramento-sas \
  --source-code-path /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas --profile bv
```
Expected: deployment `SUCCEEDED`.

- [ ] **Step 5: Checagem manual**

Abrir o app → aba **Resumo** (primeira). Conferir as 2 tabelas. No Monitoramento, marcar um input DOR1 como `Disponível` → recarregar Resumo → `Inputs não Modernizados` cai em 1 (prova do "ao vivo").

---

## Fora do plano
Edição inline, gráficos, mobile, persistência em CSV das tabelas-resumo.

## Self-review (preenchido)
- **Cobertura do spec:** funil (T1) §3 → Task 1/2/4; inputs por origem (T2) → Task 1/2/4; ao vivo (status efetivo) → Task 2; tabela dedicada + sem mexer no monitor → Task 1; aba primeira/`/resumo`/read-only → Task 5/4; re-publish+redeploy → Task 6; calibração → Task 6/Step 2. ✓
- **Placeholders:** nenhum; todo passo tem código/comando + resultado esperado.
- **Consistência de tipos:** `resumo`/`funil` keys do publish (`area_principal`,`origem_bucket`,`escopo_indi`,`modernizada_auto` / `area`,`qtd_dor1`,`egps_enviados`,`egps_analisados`) batem com `res_cols`/`fun_cols`, com as colunas SQL do backend e com `ResumoFunilRow`/`ResumoOrigemRow`/`ResumoPayload` no front. `api.resumo()` → `ResumoPayload` → consumido por `ResumoView`. ✓
