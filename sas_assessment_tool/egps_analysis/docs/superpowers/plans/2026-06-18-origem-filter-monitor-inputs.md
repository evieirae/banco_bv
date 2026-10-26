# Filtro de origem na aba Monitoramento Inputs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar uma coluna/filtro de **origem** (BigQuery · Transacional · SAS/Local externo · SAS/Local dependência · Arquivo · Script) à aba Monitoramento Inputs do app.

**Architecture:** `origem` é pré-computada no `build()` do `publish_to_databricks.py` e gravada como coluna em `sas_inputs_monitor`. O backend FastAPI ganha um parâmetro de filtro `origem` e expõe a lista de origens no `/api/config`. O frontend React adiciona um `<select>` na `FilterBar` e uma coluna na `InputsTable`.

**Tech Stack:** Python 3.12 (sem pytest garantido → testes rodam como `python <arquivo>.py`), databricks-sdk; FastAPI; React 18 + TS + Vite (tsc strict).

**Spec:** `egps_analysis/docs/superpowers/specs/2026-06-18-origem-filter-monitor-inputs-design.md`

**Convenções desta sessão (IMPORTANTE):**
- Commits **sem** trailer `Co-Authored-By` (ver auto-memory). Branch atual: `import/project-sas` (não criar worktree salvo se o executor preferir).
- Os passos **republish** e **deploy** (Task 9) mexem em estado prod/compartilhado → **gate humano**: o agente NÃO executa sem OK explícito.
- Comandos Python rodam da raiz do repo. O backend usa `run_sql` que devolve tudo como string.

---

## File Structure

| Arquivo | Mudança | Responsabilidade |
|---|---|---|
| `egps_analysis/publish_to_databricks.py` | modificar | `origem_input()`, `produced_tables`, coluna `origem` no build/DDL/staging/MERGE |
| `egps_analysis/test_origem_input.py` | criar | unit do classificador + reprodução dos contadores de aceite |
| `egps_analysis/app/backend/main.py` | modificar | `ORIGENS`, `/api/config`, filtro+SELECT em `/api/inputs` |
| `egps_analysis/app/frontend/src/types.ts` | modificar | `InputRow.origem`, `Filters.origem`, `AppConfig.origens` |
| `egps_analysis/app/frontend/src/api.ts` | modificar | passar `origem` no query de `inputs()` |
| `egps_analysis/app/frontend/src/components/FilterBar.tsx` | modificar | `<select>` de origem + tooltip |
| `egps_analysis/app/frontend/src/components/InputsTable.tsx` | modificar | coluna `origem`, sort key, relabel `source_types`→"Fontes" |
| `egps_analysis/app/frontend/src/components/MonitorView.tsx` | modificar | default do filtro + accessor de sort |
| `egps_analysis/app/frontend/src/styles.css` | modificar | grid-template-columns + `.c-orig` |

---

## Task 1: Classificador `origem_input()` + unit test

**Files:**
- Create: `egps_analysis/test_origem_input.py`
- Modify: `egps_analysis/publish_to_databricks.py` (após `origem_bucket`, ~linha 73)

- [ ] **Step 1: Escrever o teste que falha**

Create `egps_analysis/test_origem_input.py`:

```python
"""Unit do classificador de origem do monitor (origem_input) + reprodução dos
contadores de aceite do escopo Indicium. Roda como script:
    python egps_analysis/test_origem_input.py
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_to_databricks as pub


def test_bigquery_vence_tudo():
    assert pub.origem_input({"BIGQUERY/GCP", "POSTGRES"}, "tabela", True) == "BigQuery"


def test_arquivo_por_categoria():
    assert pub.origem_input({"SAS/LOCAL"}, "arquivo", False) == "Arquivo"


def test_script_por_categoria():
    assert pub.origem_input({"SAS/LOCAL"}, "script", False) == "Script"


def test_transacional():
    assert pub.origem_input({"SYBASEIQ"}, "tabela", False) == "Transacional"
    assert pub.origem_input({"DBCON", "SAS/LOCAL"}, "tabela", False) == "Transacional"


def test_sas_local_dependencia_quando_produzida():
    assert pub.origem_input({"SAS/LOCAL"}, "tabela", True) == "SAS/Local (dependência)"


def test_sas_local_externo_quando_sem_produtor():
    assert pub.origem_input({"SAS/LOCAL"}, "tabela", False) == "SAS/Local (externo)"


def test_transacional_vence_dependencia():
    # token transacional tem prioridade sobre o split SAS/Local mesmo se produzida
    assert pub.origem_input({"POSTGRES"}, "tabela", True) == "Transacional"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passaram")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool && python3 egps_analysis/test_origem_input.py`
Expected: FAIL/ERROR — `AttributeError: module 'publish_to_databricks' has no attribute 'origem_input'`.

- [ ] **Step 3: Implementar `origem_input()`**

In `egps_analysis/publish_to_databricks.py`, logo após a função `origem_bucket` (que termina ~linha 72), adicionar:

```python
def origem_input(source_types, categoria, produced):
    """Origem de um input do grão monitor (sas_inputs_monitor): 4-way para tabelas
    + Arquivo/Script para as demais categorias. Distinta de origem_bucket() (grão
    Resumo, com libname). `produced`=True quando o artefato é table_out de algum
    EGP do corpus → dependência intra-pipeline; senão SAS/Local sem produtor
    conhecido ("externo"). Prioridade: BigQuery > Arquivo/Script (categoria) >
    Transacional > SAS/Local (split por produced)."""
    sts = {s.upper() for s in source_types if s}
    if any("BIGQUERY" in s for s in sts):
        return "BigQuery"
    if categoria == "arquivo":
        return "Arquivo"
    if categoria == "script":
        return "Script"
    if any(any(t in s for t in _TRANS_SRC) for s in sts):
        return "Transacional"
    return "SAS/Local (dependência)" if produced else "SAS/Local (externo)"
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool && python3 egps_analysis/test_origem_input.py`
Expected: PASS em todos; última linha `7/7 passaram`, exit 0.

- [ ] **Step 5: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/test_origem_input.py egps_analysis/publish_to_databricks.py
git commit -m "feat(monitor): classificador origem_input (4-way) p/ inputs do monitor"
```

---

## Task 2: Gravar `origem` no `build()` + contadores de aceite

**Files:**
- Modify: `egps_analysis/publish_to_databricks.py` (`build()`: ~linha 254 accumuladores, ~266 table_out, ~313 inputs_rows; `in_cols` ~518)
- Modify: `egps_analysis/test_origem_input.py` (adicionar teste de contagem)

- [ ] **Step 1: Escrever o teste de contagem (falha)**

Em `egps_analysis/test_origem_input.py`, adicionar antes da linha `TESTS = [...]`:

```python
def test_contadores_origem_indicium():
    data = pub.build()
    indi = [r for r in data["inputs"] if r["escopo_indi"]]
    import collections
    c = collections.Counter(r["origem"] for r in indi)
    assert sum(c.values()) == 3354, c
    assert c["SAS/Local (externo)"] == 1566, c
    assert c["Arquivo"] == 850, c
    assert c["SAS/Local (dependência)"] == 544, c
    assert c["BigQuery"] == 310, c
    assert c["Transacional"] == 82, c
    assert c["Script"] == 2, c
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool && python3 egps_analysis/test_origem_input.py`
Expected: `test_contadores_origem_indicium` falha com `KeyError`/`AssertionError` (a chave `origem` ainda não existe em `data["inputs"]`).

- [ ] **Step 3: Adicionar o acumulador `produced_tables`**

Em `build()`, junto aos demais acumuladores (logo após `proj_area = {}`, ~linha 256), adicionar:

```python
    produced_tables = set()  # canon(art) de todo table_out (sem ruído) — p/ origem "dependência"
```

- [ ] **Step 4: Popular `produced_tables` no ramo table_out**

Em `build()`, no ramo `table_out` (atual):

```python
            if cat == "table_out":
                if not is_noise_table(art):
                    proj_out[proj].add(canon(art))
                continue
```

trocar por:

```python
            if cat == "table_out":
                if not is_noise_table(art):
                    proj_out[proj].add(canon(art))
                    produced_tables.add(canon(art))
                continue
```

- [ ] **Step 5: Gravar `origem` em cada linha de input**

Em `build()`, no loop que monta `inputs_rows` (atual `for rec in inputs.values(): ... inputs_rows.append({...})`), adicionar a chave `origem` ao dict (logo após `"categoria": rec["categoria"],`):

```python
            "origem": origem_input(rec["source_types"], rec["categoria"],
                                   canon(rec["artifact"]) in produced_tables),
```

- [ ] **Step 6: Incluir `origem` em `in_cols`**

Trocar (atual):

```python
    in_cols = ["chave_canonica", "artifact", "categoria", "source_types", "qtd_projetos",
               "areas", "escopo_indi", "modernizada_auto"]
```

por:

```python
    in_cols = ["chave_canonica", "artifact", "categoria", "origem", "source_types", "qtd_projetos",
               "areas", "escopo_indi", "modernizada_auto"]
```

- [ ] **Step 7: Rodar o teste e ver passar**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool && python3 egps_analysis/test_origem_input.py`
Expected: `8/8 passaram`, exit 0. (Se algum contador divergir, é sinal de que os CSVs locais mudaram — revalidar com `python3 egps_analysis/docs/analises/build_metricas_escopo.py` antes de ajustar os números do teste.)

- [ ] **Step 8: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/publish_to_databricks.py egps_analysis/test_origem_input.py
git commit -m "feat(monitor): origem gravada no build() + contadores de aceite Indicium"
```

---

## Task 3: DDL + staging + MERGE + ALTER da coluna `origem`

**Files:**
- Modify: `egps_analysis/publish_to_databricks.py` (DDL `T_IN` ~532; apply: guard ALTER ~593; staging DDL ~597; MERGE ~606)

- [ ] **Step 1: Adicionar `origem` ao DDL de criação de `T_IN`**

No bloco `ddl = [...]`, na criação de `T_IN`, adicionar `origem STRING,` após `categoria STRING,`:

```python
        f"""CREATE TABLE IF NOT EXISTS {T_IN} (
  chave_canonica STRING, artifact STRING, categoria STRING, origem STRING, source_types STRING,
  qtd_projetos INT, areas STRING, escopo_indi BOOLEAN, modernizada_auto STRING,
  status_humano STRING, responsavel STRING, observacao STRING,
  updated_at TIMESTAMP, updated_by STRING,
  orfao BOOLEAN, refreshed_at TIMESTAMP
) USING DELTA""",
```

- [ ] **Step 2: Adicionar o guard idempotente de ALTER (tabela pré-existente)**

No caminho `--apply`, logo após o loop `for d in ddl: run(d)` e o `print("  DDL ok ...")`, inserir:

```python
    # CREATE IF NOT EXISTS não altera schema de tabela já existente em prod: garante a coluna origem
    try:
        run(f"SELECT origem FROM {T_IN} LIMIT 0")
    except Exception:
        run(f"ALTER TABLE {T_IN} ADD COLUMNS (origem STRING)")
        print("  coluna origem adicionada (ALTER) à tabela pré-existente")
```

- [ ] **Step 3: Adicionar `origem` ao DDL da staging**

Trocar a criação da staging (atual):

```python
    run(f"""CREATE TABLE {STG} (
  chave_canonica STRING, artifact STRING, categoria STRING, source_types STRING,
  qtd_projetos INT, areas STRING, escopo_indi BOOLEAN, modernizada_auto STRING
) USING DELTA""")
```

por:

```python
    run(f"""CREATE TABLE {STG} (
  chave_canonica STRING, artifact STRING, categoria STRING, origem STRING, source_types STRING,
  qtd_projetos INT, areas STRING, escopo_indi BOOLEAN, modernizada_auto STRING
) USING DELTA""")
```

- [ ] **Step 4: Propagar `origem` no MERGE**

No `MERGE INTO {T_IN}`: (a) no `UPDATE SET`, após `t.categoria=s.categoria,` adicionar `t.origem=s.origem,`; (b) na lista de colunas do `INSERT`, após `categoria,` adicionar `origem,`; (c) no `VALUES`, após `s.categoria,` adicionar `s.origem,`. Resultado:

```python
    run(f"""MERGE INTO {T_IN} t USING {STG} s ON t.chave_canonica = s.chave_canonica
WHEN MATCHED THEN UPDATE SET
  t.artifact=s.artifact, t.categoria=s.categoria, t.origem=s.origem, t.source_types=s.source_types,
  t.qtd_projetos=s.qtd_projetos, t.areas=s.areas, t.escopo_indi=s.escopo_indi,
  t.modernizada_auto=s.modernizada_auto, t.orfao=false, t.refreshed_at=current_timestamp()
WHEN NOT MATCHED THEN INSERT (
  chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, areas,
  escopo_indi, modernizada_auto, status_humano, orfao, refreshed_at
) VALUES (
  s.chave_canonica, s.artifact, s.categoria, s.origem, s.source_types, s.qtd_projetos, s.areas,
  s.escopo_indi, s.modernizada_auto,
  CASE s.modernizada_auto WHEN 'Disponível' THEN 'Modernizado' ELSE 'A receber' END,
  false, current_timestamp()
)""")
```

- [ ] **Step 5: Verificar via dry-run que a SQL inclui `origem`**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool && python3 egps_analysis/publish_to_databricks.py && grep -c "origem" egps_analysis/docs/analises/publish_databricks.preview.sql`
Expected: dry-run conclui sem erro e `grep` retorna `>= 2` (origem no DDL e no INSERT de amostra). Reverter mudança colateral do preview depois se necessário: `git checkout -- egps_analysis/docs/analises/publish_databricks.preview.sql`.

- [ ] **Step 6: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/publish_to_databricks.py
git commit -m "feat(monitor): coluna origem no DDL/staging/MERGE + ALTER idempotente"
```

---

## Task 4: Backend — `ORIGENS`, `/api/config`, filtro em `/api/inputs`

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (constantes ~64; `/api/inputs` ~284-310; `/api/config` ~567-569)

- [ ] **Step 1: Adicionar a constante `ORIGENS`**

Após `CATEGORIAS = ["tabela", "arquivo", "lib", "script"]` (linha 64), adicionar:

```python
ORIGENS = ["BigQuery", "Transacional", "SAS/Local (externo)", "SAS/Local (dependência)", "Arquivo", "Script"]
```

- [ ] **Step 2: Expor `origens` no `/api/config`**

Trocar (atual):

```python
    return {"status_options": STATUS_OPTIONS, "categorias": CATEGORIAS, "scope": FQ}
```

por:

```python
    return {"status_options": STATUS_OPTIONS, "categorias": CATEGORIAS, "origens": ORIGENS, "scope": FQ}
```

- [ ] **Step 3: Adicionar parâmetro + filtro + SELECT de `origem` em `/api/inputs`**

Na assinatura de `def inputs(...)`, adicionar `origem: str = ""`:

```python
def inputs(scope: str = "indi", categoria: str = "", modern: str = "",
           status: str = "", q: str = "", divergence: bool = False, origem: str = ""):
```

Logo após o bloco `if categoria in CATEGORIAS: ...`, adicionar:

```python
    if origem in ORIGENS:
        where.append(f"origem = {sql_lit(origem)}")
```

No SELECT de `rows`, incluir `origem` (após `categoria,`):

```python
    rows = run_sql(
        f"SELECT chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, areas, "
        f"escopo_indi, modernizada_auto, status_humano, responsavel, observacao, orfao "
        f"FROM {T_IN}{wsql} ORDER BY qtd_projetos DESC, artifact LIMIT {READ_CAP}")
```

- [ ] **Step 4: Sanity-check de import do backend**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/backend && python3 -c "import ast; ast.parse(open('main.py').read()); print('sintaxe ok')"`
Expected: `sintaxe ok` (não conecta no Databricks; só valida que o arquivo parseia).

- [ ] **Step 5: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/backend/main.py
git commit -m "feat(api): filtro origem em /api/inputs + origens no /api/config"
```

---

## Task 5: Frontend — types + api

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts` (`InputRow` ~1-14; `AppConfig` ~25-29; `Filters` ~31-38)
- Modify: `egps_analysis/app/frontend/src/api.ts` (`inputs` ~18-28)

- [ ] **Step 1: Adicionar `origem` aos tipos**

Em `InputRow`, após `source_types: string;`, adicionar:

```typescript
  origem: string;
```

Em `AppConfig`, após `categorias: string[];`, adicionar:

```typescript
  origens: string[];
```

Em `Filters`, após `categoria: string;`, adicionar:

```typescript
  origem: string;
```

- [ ] **Step 2: Passar `origem` no query de `inputs()` (api.ts)**

No `URLSearchParams` de `inputs`, após `categoria: f.categoria,`, adicionar:

```typescript
      origem: f.origem,
```

- [ ] **Step 3: Verificar tipos**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npx tsc -b 2>&1 | head -20`
Expected: erros apontando que `MonitorView`/`FilterBar`/`InputsTable` ainda não tratam `origem` (esperado — corrigidos nas Tasks 6-8). Nenhum erro em `types.ts`/`api.ts`.

- [ ] **Step 4: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app): tipos e api do filtro de origem"
```

---

## Task 6: Frontend — `<select>` de origem na FilterBar

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/FilterBar.tsx` (após o select de categoria, ~linha 36)

- [ ] **Step 1: Adicionar o select de origem com tooltip**

Logo após o `</select>` do filtro de categoria (o que tem `<option value="">Todas categorias</option>`), inserir:

```tsx
      <select
        value={filters.origem}
        onChange={(e) => onChange({ origem: e.target.value })}
        title={"Origem do dado. 'SAS/Local (externo)' = sem produtor conhecido no "
          + "corpus extraído — pode ser ingestão real OU dependência de um EGP não "
          + "recebido. 'SAS/Local (dependência)' = é output de algum EGP do corpus."}
      >
        <option value="">Origem: todas</option>
        {(cfg?.origens ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
```

- [ ] **Step 2: Verificar tipos**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npx tsc -b 2>&1 | grep -i filterbar | head`
Expected: nenhum erro relativo a `FilterBar.tsx`.

- [ ] **Step 3: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/components/FilterBar.tsx
git commit -m "feat(app): select de origem na FilterBar (com tooltip do 'externo')"
```

---

## Task 7: Frontend — coluna `origem` na InputsTable + CSS

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/InputsTable.tsx` (`InputSortKey` ~5-7; thead ~68-77; trow ~96-97)
- Modify: `egps_analysis/app/frontend/src/styles.css` (grid ~106; classes ~114)

- [ ] **Step 1: Adicionar `"origem"` ao `InputSortKey`**

Trocar (atual):

```typescript
export type InputSortKey =
  | "artifact" | "categoria" | "source_types" | "qtd_projetos"
  | "modernizada_auto" | "status_humano" | "responsavel" | "observacao";
```

por:

```typescript
export type InputSortKey =
  | "artifact" | "categoria" | "origem" | "source_types" | "qtd_projetos"
  | "modernizada_auto" | "status_humano" | "responsavel" | "observacao";
```

- [ ] **Step 2: Adicionar a coluna no cabeçalho e relabel do source_types**

No `<div className="thead">`, trocar a linha do `categoria` + `source_types` (atual):

```tsx
        {H("categoria", "Cat.", "c-cat")}
        {H("source_types", "Origem", "c-src")}
```

por (adiciona "Origem" novo e renomeia o cru para "Fontes"):

```tsx
        {H("categoria", "Cat.", "c-cat")}
        {H("origem", "Origem", "c-orig")}
        {H("source_types", "Fontes", "c-src")}
```

- [ ] **Step 3: Adicionar a célula da origem na linha**

No corpo da linha (`trow`), após `<div className="c-cat">{r.categoria}</div>`, inserir:

```tsx
                <div className="c-orig" title={r.origem}>{r.origem}</div>
```

- [ ] **Step 4: Atualizar o grid e adicionar `.c-orig` (styles.css)**

Em `styles.css` linha 106, trocar (atual):

```css
.thead, .trow { display: grid; grid-template-columns: minmax(220px, 3fr) 70px minmax(120px, 1.4fr) 60px 80px 150px 1.2fr 1.6fr; align-items: center; }
```

por (insere uma coluna p/ `c-orig` após `c-cat`):

```css
.thead, .trow { display: grid; grid-template-columns: minmax(220px, 3fr) 70px minmax(120px, 1.3fr) minmax(120px, 1.4fr) 60px 80px 150px 1.2fr 1.6fr; align-items: center; }
```

Logo após a regra `.c-src { ... }` (linha 114), adicionar:

```css
.c-orig { white-space: nowrap; text-overflow: ellipsis; font-size: 11px; }
```

- [ ] **Step 5: Verificar tipos**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npx tsc -b 2>&1 | grep -i inputstable | head`
Expected: nenhum erro relativo a `InputsTable.tsx`.

- [ ] **Step 6: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/components/InputsTable.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): coluna origem na tabela de inputs (+ grid e relabel Fontes)"
```

---

## Task 8: Frontend — MonitorView (default + sort) + build verde

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/MonitorView.tsx` (`DEFAULT_FILTERS` ~11-18; `inputAccessor` ~22-34)

- [ ] **Step 1: Adicionar `origem` ao DEFAULT_FILTERS**

Em `DEFAULT_FILTERS`, após `categoria: "",`, adicionar:

```typescript
  origem: "",
```

- [ ] **Step 2: Adicionar `origem` ao `inputAccessor`**

No `switch (k)` de `inputAccessor`, após `case "categoria": return r.categoria;`, adicionar:

```typescript
    case "origem": return r.origem;
```

- [ ] **Step 3: Build completo (tsc strict + vite)**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npm run build 2>&1 | tail -15`
Expected: `tsc -b && vite build` conclui sem erro (gera `dist/`).

- [ ] **Step 4: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/components/MonitorView.tsx
git commit -m "feat(app): filtro origem default + ordenação na aba Monitoramento Inputs"
```

---

## Task 9: Deploy (GATE HUMANO — não executar sem OK explícito)

Estes passos mexem em prod/estado compartilhado. **Ordem obrigatória:** republish ANTES do deploy (senão o SELECT em `origem` quebra). Apresentar ao usuário e aguardar OK. NÃO são checkboxes do executor automático.

**9a. Republish** (popula a coluna `origem`; junto com o dedup `.sas` já pendente):

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool && python3 egps_analysis/publish_to_databricks.py \
  --apply --profile bv --catalog client_journey --schema monitoramento_sas \
  --warehouse-id 5922c26f81f1bbdd
```

Esperado nos logs: `coluna origem adicionada (ALTER) ...` (na 1ª vez) e MERGE ok.

**9b. Deploy do app** (depois do 9a):

```bash
cd egps_analysis/app/frontend && npm run build && cd ..
databricks sync . /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas \
  --exclude 'frontend/node_modules/**' --exclude '.databricks/**' --profile bv
databricks apps deploy monitoramento-sas \
  --source-code-path /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas --profile bv
```

**9c. Verificação pós-deploy:** abrir a aba Monitoramento Inputs, conferir o select "Origem" com as 6 opções, filtrar `SAS/Local (dependência)` no escopo Indicium → 544 linhas; coluna "Origem" visível e ordenável.

---

## Self-Review (preenchido pelo autor do plano)

- **Cobertura do spec:** §2 classificação → Task 1; §4 dados/build → Tasks 2-3; §5 backend → Task 4; §6 frontend → Tasks 5-8; §7 ordem de deploy → Task 9; §8 aceite → Task 2 (contadores) + Task 9c (UI); §9 testes → Tasks 1-2 (Python) + Task 8 (build). Tooltip do "externo" (§2/§3) → Task 6.
- **Placeholders:** nenhum — todo passo tem código/comando concretos.
- **Consistência de tipos:** `origem` (string) usado igual em types.ts, api.ts, InputRow, Filters, AppConfig; valores de `ORIGENS` (backend) == retornos de `origem_input` == labels do `<select>`; `InputSortKey` inclui `"origem"` usado em thead/inputAccessor.
