# Ingestão in-app — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deixar um membro `bv_users` subir `.egp` e `chameleon.csv` direto no app `monitoramento-sas` e, num clique, recalcular o inventário corpus-wide e publicar nas tabelas Delta — sem rodar scripts locais.

**Architecture:** Estado durável num UC Volume (`bv_dev_db.monitoramento_sas.pipeline`). O app baixa o corpus/`src` do Volume para um workdir local (`/tmp/pipeline`), roda os scripts existentes (extractor importado; orchestrator + publish via subprocess) num job em **background como service principal**, re-aplica o escopo do app (`recompute_escopo` como SP), invalida o cache e devolve progresso via `sas_ingest_jobs`. Extração de 1 EGP é síncrona (preview rápido); o recálculo pesado é o botão "Processar".

**Tech Stack:** FastAPI + databricks-sdk (Files API + Statement Execution), pandas/openpyxl (pipeline), React + @tanstack/react-query v5 + Vite, Delta.

---

## Contexto verificado (não re-descobrir)

- **App SP:** `app-3a6zfb monitoramento-sas`, client `5b524c4c-c116-4de7-b414-01f719e49d0d`. Grants já concedidos: `USE_CATALOG` em `bv_dev_db`, `READ/WRITE VOLUME` no volume `pipeline`, `ALL_PRIVILEGES` no schema. Compute **Medium (2 vCPU, 6 GB)**.
- **Volume:** `bv_dev_db.monitoramento_sas.pipeline` já criado (vazio). Caminho FUSE `/Volumes/bv_dev_db/monitoramento_sas/pipeline` **provavelmente não está montado** em Databricks Apps → usar **Files API** do SDK (`w.files.upload/download/list_directory_contents`).
- **`main.py` (`app/backend/main.py`) âncoras:**
  - `run_sql(statement, want_rows=True)` usa `_client()` (OBO→SP). Em thread de background **não há token OBO** → `_client()` lança 401. Por isso o job usa `sp_exec` (SP direto), definido neste plano.
  - `_sp_client()` = `WorkspaceClient()` (linhas ~215-218). `WAREHOUSE_ID` via env `DATABRICKS_WAREHOUSE_ID`. `CATALOG`/`SCHEMA`/`FQ` (linhas 38-39). Constantes de tabela `T_*` (linhas 49-62).
  - Gate: `_require_gestao()` / `_is_gestao()` (grupo `bv_users`); `sql_lit()` existe.
  - `/api/config` já devolve `is_gestao` (retorno em ~1014).
  - `recompute_escopo()` (linhas ~909-936) faz updates via `run_sql` e no fim: `global _lineage_gen; _lineage_gen += 1; _lineage_cache.clear()`. **Precisa aceitar `exec_fn`** para rodar como SP.
  - `_ensure_analistas_table()` (399-407) é o template de tabela lazy. Endpoints: `app = FastAPI()` + `@app.post/...`, corpo via `BaseModel`. **`UploadFile`/`python-multipart` ainda não usados.**
  - Static SPA montado em `/` (após as rotas `/api`).
- **Scripts (fonte da verdade em `egps_analysis/`; serão *vendored* em `app/pipeline/`):**
  - `egps_extractor.py`: função importável `extract_code_from_egp(egp_path, output_folder, business_area="", eg_style=False, clean_output=False)`. Escreve `output_folder/<project_id>.txt`, `project_id = sanitize(f"{area}__{base}")`. Sem `--area` no CLI → **importar e passar `business_area`**. Header entre `START_METADATA`…`END_METADATA` com labels exatos (ver Task 5).
  - `orchestrator_inventory.py`: CLI `--prontidao-scope {all,in,out}`. Lê **relativo ao cwd**: `./text_egps`, `./src/chameleon.csv`, `./src/inventario_transacional.csv`, `./src/inputs_modernizados.csv`, `./src/RepMap.xlsx`. Escreve `./01..06_*.csv` no cwd. Sem rede. → rodar via subprocess com `cwd=WORK`.
  - `publish_to_databricks.py`: CLI `--apply --catalog --schema --warehouse-id [--profile]`. Auth: `WorkspaceClient(profile=...) if profile else WorkspaceClient()` → **sem `--profile` autentica como SP**. `BASE = os.path.dirname(__file__)`; lê `BASE/06,03,04.csv` e `BASE/docs/analises/indi_231_vs_extracao_06.csv`. → **copiar `publish_to_databricks.py` para dentro do `WORK`** e rodar de lá (assim `BASE=WORK`, zero edição do script sensível). `sas_escopo` só é semeado se vazio (preservado). `sas_inputs_monitor` via MERGE preserva `status_humano/responsavel/observacao`.

## Estrutura de arquivos

| Arquivo | Papel |
|---|---|
| `app/backend/ingest.py` | **novo.** Núcleo de ingestão: `sp_exec`, paths do Volume, Files API (upload/download/list), cache local do corpus, `validate_chameleon`, `parse_io_inventory`, `run_extract_one`, `run_orchestrator`, `run_publish`, CRUD de `sas_ingest_jobs`/`sas_ingest_stage`. Sem import de `main` (evita ciclo). |
| `app/backend/test_ingest.py` | **novo.** Unit tests das funções puras (`validate_chameleon`, `parse_io_inventory`). |
| `app/backend/main.py` | **mod.** `sp_exec` (re-export de `ingest`), `recompute_escopo(exec_fn=...)`, endpoints `/api/ingest/*`, thread do job. |
| `app/pipeline/` | **novo.** Cópias deployáveis: `egps_extractor.py`, `orchestrator_inventory.py`, `publish_to_databricks.py`, `libname_resolver.py` + `README.md` (fonte da verdade = `egps_analysis/`). |
| `app/requirements.txt` | **mod.** `+pandas, openpyxl, pyarrow, python-multipart`. |
| `app/frontend/src/components/IngestaoView.tsx` | **novo.** Aba de upload + stage + Processar/progresso. |
| `app/frontend/src/{routes.ts,App.tsx,types.ts,api.ts}` | **mod.** Registrar/gate a aba, tipos, chamadas. |
| `app/frontend/src/styles.css` | **mod.** Estilos da dropzone/progresso. |
| `app/README.md`, memória | **mod.** Documentar decisões. |

**Convenções de teste:** as funções puras (`validate_chameleon`, `parse_io_inventory`) seguem TDD com `pytest`. As partes de integração (Files API, subprocess, escrita Delta, UI) são validadas por passos manuais de **deploy + verificação** (curl/UI) — TDD contra um warehouse ao vivo não é prático aqui; cada passo diz exatamente o que rodar e o esperado.

---

## Phase 0 — Provisionamento & vendoring

### Task 0.1: Seed do Volume (setup único, com consentimento do usuário — é escrita real)

**Files:** nenhum (comandos CLI).

- [ ] **Step 1: Semear corpus + src no Volume**

Pergunte ao usuário antes (escrita real ~140MB). Rodar de `egps_analysis/`:

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
V=dbfs:/Volumes/bv_dev_db/monitoramento_sas/pipeline
databricks fs cp -r --overwrite text_egps "$V/text_egps" -p bv
databricks fs cp --overwrite src/chameleon.csv               "$V/src/chameleon.csv" -p bv
databricks fs cp --overwrite src/inventario_transacional.csv "$V/src/inventario_transacional.csv" -p bv
databricks fs cp --overwrite src/inputs_modernizados.csv     "$V/src/inputs_modernizados.csv" -p bv
databricks fs cp --overwrite src/RepMap.xlsx                 "$V/src/RepMap.xlsx" -p bv
databricks fs cp --overwrite docs/analises/indi_231_vs_extracao_06.csv "$V/src/indi_231_vs_extracao_06.csv" -p bv
```

- [ ] **Step 2: Verificar contagem**

```bash
databricks fs ls dbfs:/Volumes/bv_dev_db/monitoramento_sas/pipeline/text_egps -p bv | wc -l
```
Expected: ~1741. E `.../src` lista os 5 arquivos.

### Task 0.2: Vendorizar scripts do pipeline em `app/pipeline/`

**Files:**
- Create: `app/pipeline/{egps_extractor.py, orchestrator_inventory.py, publish_to_databricks.py, libname_resolver.py}` (cópias)
- Create: `app/pipeline/README.md`

- [ ] **Step 1: Copiar os scripts**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
mkdir -p app/pipeline
cp egps_extractor.py orchestrator_inventory.py publish_to_databricks.py libname_resolver.py app/pipeline/
```

- [ ] **Step 2: README de proveniência**

`app/pipeline/README.md`:
```markdown
# app/pipeline — cópias deployáveis do pipeline

**Fonte da verdade: `egps_analysis/*.py`.** Estes arquivos são cópias para o deploy do
Databricks App (o container não tem o repo). Ao mudar o pipeline, edite em `egps_analysis/`
e re-copie:

    cp ../{egps_extractor,orchestrator_inventory,publish_to_databricks,libname_resolver}.py .

Rodados pelo `backend/ingest.py`: extractor por import; orchestrator e publish por subprocess.
```

- [ ] **Step 3: Sanidade de import/sintaxe**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app
python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('pipeline/*.py')]; print('ok')"
```
Expected: `ok`.

### Task 0.3: Dependências do app

**Files:** Modify: `app/requirements.txt`

- [ ] **Step 1: Acrescentar deps**

Adicionar ao fim de `app/requirements.txt`:
```
pandas==3.*
openpyxl>=3.1.5
pyarrow>=14.0.0
python-multipart>=0.0.9
```

- [ ] **Step 2: Commit da Phase 0** (com aprovação do usuário; sem `Co-Authored-By`)

```bash
git add app/pipeline app/requirements.txt
git commit -m "build(app): vendoriza pipeline + deps p/ ingestão in-app"
```

---

## Phase 1 — Núcleo `ingest.py` (funções puras, TDD)

### Task 1.1: `validate_chameleon` (TDD)

**Files:**
- Create: `app/backend/ingest.py`
- Test: `app/backend/test_ingest.py`

- [ ] **Step 1: Teste que falha**

`app/backend/test_ingest.py`:
```python
import ingest

def test_validate_chameleon_ok():
    csv = "NmTabela;NmTabelaOrigem;DsOrigem;NmFonteDados\n"            \
          "proj.ds.t1;dbo.t1;desc;SYBASE_ASE\n"                       \
          "proj.ds.t2;dbo.t2;desc;SQL_Server\n"
    ok, msg, n, cols = ingest.validate_chameleon(csv.encode("utf-8"))
    assert ok is True
    assert n == 2
    assert "NmTabela" in cols

def test_validate_chameleon_missing_origin():
    csv = "NmTabela;DsOrigem\nproj.ds.t1;desc\n"
    ok, msg, n, cols = ingest.validate_chameleon(csv.encode("utf-8"))
    assert ok is False
    assert "origem" in msg.lower()
```

- [ ] **Step 2: Rodar → falha**

```bash
cd app/backend && python -m pytest test_ingest.py -q
```
Expected: FAIL (`ModuleNotFoundError: ingest` ou `AttributeError`).

- [ ] **Step 3: Implementar (início de `ingest.py`)**

Criar `app/backend/ingest.py` com o cabeçalho + a função:
```python
"""Núcleo de ingestão in-app: Volume I/O, cache local do corpus, execução do
pipeline (extractor/orchestrator/publish) e status de jobs. Roda como service
principal (sem OBO). Fonte da verdade dos scripts: egps_analysis/ (vendored em app/pipeline)."""
import os, io, csv, re, sys, json, glob, time, shutil, tempfile, subprocess, threading, hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from databricks.sdk import WorkspaceClient

CATALOG = os.environ.get("PUBLISH_CATALOG", "bv_dev_db")
SCHEMA = os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas")
FQ = f"{CATALOG}.{SCHEMA}"
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
VOL = os.environ.get("PIPELINE_VOLUME", f"/Volumes/{CATALOG}/{SCHEMA}/pipeline")
WORK = os.environ.get("PIPELINE_WORKDIR", "/tmp/pipeline")
PIPELINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline"))

T_JOBS = f"{FQ}.sas_ingest_jobs"
T_STAGE = f"{FQ}.sas_ingest_stage"

CHAMELEON_REQUIRED_HINT = "precisa de uma coluna de tabela destino e outra de origem"


def validate_chameleon(raw: bytes):
    """Valida bytes de um chameleon.csv. Detecção por substring (igual orchestrator):
    coluna com 'tabela' e sem 'origem' = destino; coluna com 'origem' = origem.
    Retorna (ok, msg, n_linhas, colunas)."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    sample = text[:4096]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        return (False, "CSV vazio", 0, [])
    cols = [c.strip() for c in header]
    low = [c.lower() for c in cols]
    has_dest = any(("tabela" in c and "origem" not in c) for c in low)
    has_orig = any(("origem" in c) for c in low)
    if not (has_dest and has_orig):
        return (False, f"Colunas inválidas ({CHAMELEON_REQUIRED_HINT}). Encontradas: {cols}", 0, cols)
    n = sum(1 for row in reader if any(cell.strip() for cell in row))
    if n == 0:
        return (False, "CSV sem linhas de dados", 0, cols)
    return (True, f"{n} linhas válidas", n, cols)
```

- [ ] **Step 4: Rodar → passa**

```bash
cd app/backend && python -m pytest test_ingest.py -q
```
Expected: 2 passed.

### Task 1.2: `parse_io_inventory` (TDD)

**Files:** Modify `app/backend/ingest.py`, `app/backend/test_ingest.py`

- [ ] **Step 1: Teste que falha**

Anexar em `test_ingest.py`:
```python
SAMPLE_TXT = """START_METADATA
PROJECT: Cobranca__Exemplo
BUSINESS_AREA: Cobranca
HAS_PASSTHROUGH: Yes
----------------------------------------
[[ I/O INVENTORY ]]
EXTERNAL INPUTS (Requires Ingestion): dbo.clientes, dbo.contratos
IMPORTED FILES (Requires Ingestion): /dados/tabela.xlsx
INTERNAL READS (Temp/Local): work.tmp1
----------------------------------------
PERMANENT OUTPUTS (Target Marts): trusted.mart_cobranca
EXPORTED FILES (Artifacts): (none)
END_METADATA
====
"""

def test_parse_io_inventory():
    inv = ingest.parse_io_inventory(SAMPLE_TXT)
    assert inv["project"] == "Cobranca__Exemplo"
    assert inv["business_area"] == "Cobranca"
    assert inv["has_passthrough"] is True
    assert inv["external_inputs"] == ["dbo.clientes", "dbo.contratos"]
    assert inv["imported_files"] == ["/dados/tabela.xlsx"]
    assert inv["permanent_outputs"] == ["trusted.mart_cobranca"]
    assert inv["exported_files"] == []  # (none) → vazio
```

- [ ] **Step 2: Rodar → falha**

```bash
cd app/backend && python -m pytest test_ingest.py::test_parse_io_inventory -q
```
Expected: FAIL (`AttributeError: parse_io_inventory`).

- [ ] **Step 3: Implementar**

Anexar em `ingest.py`:
```python
_INV_LABELS = {
    "external_inputs": "EXTERNAL INPUTS (Requires Ingestion):",
    "imported_files": "IMPORTED FILES (Requires Ingestion):",
    "internal_reads": "INTERNAL READS (Temp/Local):",
    "permanent_outputs": "PERMANENT OUTPUTS (Target Marts):",
    "exported_files": "EXPORTED FILES (Artifacts):",
}

def _split_list(value: str):
    value = value.strip()
    if not value or value == "(none)":
        return []
    return [x.strip() for x in value.split(", ") if x.strip() and x.strip() != "(none)"]

def parse_io_inventory(txt: str):
    """Extrai o bloco START_METADATA…END_METADATA de um .txt do extractor."""
    m = re.search(r"START_METADATA(.*?)END_METADATA", txt, re.S)
    block = m.group(1) if m else txt
    out = {k: [] for k in _INV_LABELS}
    out["project"] = ""
    out["business_area"] = ""
    out["has_passthrough"] = False
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("PROJECT:"):
            out["project"] = s.split(":", 1)[1].strip()
        elif s.startswith("BUSINESS_AREA:"):
            ba = s.split(":", 1)[1].strip()
            out["business_area"] = "" if ba == "(none)" else ba
        elif s.startswith("HAS_PASSTHROUGH:"):
            out["has_passthrough"] = "yes" in s.split(":", 1)[1].strip().lower()
        else:
            for key, label in _INV_LABELS.items():
                if s.startswith(label):
                    out[key] = _split_list(s[len(label):])
                    break
    return out
```

- [ ] **Step 4: Rodar → passa**

```bash
cd app/backend && python -m pytest test_ingest.py -q
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backend/ingest.py app/backend/test_ingest.py
git commit -m "feat(app): ingest.py — validação chameleon + parser I/O (TDD)"
```

---

## Phase 2 — `ingest.py`: SP SQL, Files API, cache do corpus, status

### Task 2.1: `sp_exec` (SQL como service principal)

**Files:** Modify `app/backend/ingest.py`

- [ ] **Step 1: Implementar**

Anexar em `ingest.py`:
```python
from databricks.sdk.service.sql import Disposition, Format

_sp = None
_sp_lock = threading.Lock()

def sp_client():
    global _sp
    if _sp is None:
        with _sp_lock:
            if _sp is None:
                _sp = WorkspaceClient()
    return _sp

def sp_exec(statement: str, want_rows: bool = False):
    """Executa SQL como o SP do app (sem OBO). Para uso em background/job."""
    r = sp_client().statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement,
        catalog=CATALOG, schema=SCHEMA, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    if r.status and r.status.state and r.status.state.value not in ("SUCCEEDED",):
        err = getattr(r.status, "error", None)
        raise RuntimeError(f"SQL falhou ({r.status.state.value}): {getattr(err,'message',err)}")
    if not want_rows:
        return None
    cols = [c.name for c in (r.manifest.schema.columns if r.manifest and r.manifest.schema else [])]
    data = (r.result.data_array if r.result else None) or []
    return [dict(zip(cols, row)) for row in data]
```

- [ ] **Step 2: Sintaxe**

```bash
cd app/backend && python -c "import ast; ast.parse(open('ingest.py').read()); print('ok')"
```
Expected: `ok`.

### Task 2.2: Files API — download do corpus/`src` e upload de arquivos

**Files:** Modify `app/backend/ingest.py`

- [ ] **Step 1: Implementar helpers de Volume**

Anexar em `ingest.py`:
```python
def _vol(path: str) -> str:
    return f"{VOL}/{path.lstrip('/')}"

def vol_upload(local_path: str, vol_rel: str):
    with open(local_path, "rb") as f:
        sp_client().files.upload(_vol(vol_rel), f, overwrite=True)

def vol_upload_bytes(data: bytes, vol_rel: str):
    sp_client().files.upload(_vol(vol_rel), io.BytesIO(data), overwrite=True)

def vol_download(vol_rel: str, local_path: str):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    resp = sp_client().files.download(_vol(vol_rel))
    with open(local_path, "wb") as out:
        shutil.copyfileobj(resp.contents, out)

def vol_list(vol_rel: str):
    try:
        return [e.name for e in sp_client().files.list_directory_contents(_vol(vol_rel))]
    except Exception:
        return []
```

- [ ] **Step 2: Cache local do corpus (rehydrate)**

Anexar em `ingest.py`:
```python
_corpus_lock = threading.Lock()

def work_paths():
    return {
        "root": WORK,
        "text": os.path.join(WORK, "text_egps"),
        "src": os.path.join(WORK, "src"),
    }

def ensure_corpus_local(log=print):
    """Garante WORK/text_egps + WORK/src espelhando o Volume. Rehydrata se o container
    é novo (cache local vazio). Baixa arquivos em paralelo."""
    p = work_paths()
    os.makedirs(p["text"], exist_ok=True)
    os.makedirs(p["src"], exist_ok=True)
    have = set(os.listdir(p["text"]))
    remote = [n for n in vol_list("text_egps") if n.endswith(".txt")]
    missing = [n for n in remote if n not in have]
    if missing:
        log(f"rehydrate: baixando {len(missing)} .txt do Volume...")
        def _one(name):
            vol_download(f"text_egps/{name}", os.path.join(p["text"], name))
        with ThreadPoolExecutor(max_workers=16) as ex:
            list(ex.map(_one, missing))
    for name in ("chameleon.csv", "inventario_transacional.csv", "inputs_modernizados.csv",
                 "RepMap.xlsx", "indi_231_vs_extracao_06.csv"):
        dst = os.path.join(p["src"], name)
        if not os.path.exists(dst):
            try:
                vol_download(f"src/{name}", dst)
            except Exception as e:
                log(f"aviso: src/{name} ausente no Volume ({e})")
    return p
```

- [ ] **Step 3: Sintaxe**

```bash
cd app/backend && python -c "import ast; ast.parse(open('ingest.py').read()); print('ok')"
```
Expected: `ok`.

### Task 2.3: Tabelas de controle + CRUD de stage/jobs

**Files:** Modify `app/backend/ingest.py`

- [ ] **Step 1: Implementar ensure + CRUD**

Anexar em `ingest.py`:
```python
def _sql_lit(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"

def _now():
    return datetime.now(timezone.utc).isoformat()

def ensure_tables():
    sp_exec(f"""CREATE TABLE IF NOT EXISTS {T_JOBS} (
      job_id STRING, status STRING, etapa STRING, started_by STRING,
      started_at STRING, finished_at STRING, n_egps INT, log STRING, erro STRING
    ) USING DELTA""")
    sp_exec(f"""CREATE TABLE IF NOT EXISTS {T_STAGE} (
      egp_key STRING, area STRING, uploaded_by STRING, uploaded_at STRING,
      processed BOOLEAN, job_id STRING
    ) USING DELTA""")

def stage_add(egp_key, area, user):
    ensure_tables()
    sp_exec(f"DELETE FROM {T_STAGE} WHERE egp_key = {_sql_lit(egp_key)} AND processed = false")
    sp_exec(f"""INSERT INTO {T_STAGE} VALUES ({_sql_lit(egp_key)}, {_sql_lit(area)},
      {_sql_lit(user)}, {_sql_lit(_now())}, false, NULL)""")

def stage_list():
    ensure_tables()
    return sp_exec(f"""SELECT egp_key, area, uploaded_by, uploaded_at
      FROM {T_STAGE} WHERE processed = false ORDER BY uploaded_at""", want_rows=True)

def stage_remove(egp_key):
    sp_exec(f"DELETE FROM {T_STAGE} WHERE egp_key = {_sql_lit(egp_key)} AND processed = false")

def job_running():
    ensure_tables()
    r = sp_exec(f"SELECT job_id FROM {T_JOBS} WHERE status = 'running'", want_rows=True)
    return r[0]["job_id"] if r else None

def job_create(user, n_egps):
    ensure_tables()
    job_id = hashlib.sha1(f"{_now()}|{user}".encode()).hexdigest()[:16]
    sp_exec(f"""INSERT INTO {T_JOBS} VALUES ({_sql_lit(job_id)}, 'running', 'iniciando',
      {_sql_lit(user)}, {_sql_lit(_now())}, NULL, {int(n_egps)}, '', NULL)""")
    return job_id

def job_update(job_id, etapa=None, log_append=None, status=None, erro=None, finished=False):
    sets = []
    if etapa is not None: sets.append(f"etapa = {_sql_lit(etapa)}")
    if status is not None: sets.append(f"status = {_sql_lit(status)}")
    if erro is not None: sets.append(f"erro = {_sql_lit(erro)}")
    if finished: sets.append(f"finished_at = {_sql_lit(_now())}")
    if log_append is not None:
        sets.append(f"log = concat(coalesce(log,''), {_sql_lit(log_append + chr(10))})")
    if sets:
        sp_exec(f"UPDATE {T_JOBS} SET {', '.join(sets)} WHERE job_id = {_sql_lit(job_id)}")

def job_get(job_id):
    r = sp_exec(f"""SELECT job_id, status, etapa, started_at, finished_at, n_egps, log, erro
      FROM {T_JOBS} WHERE job_id = {_sql_lit(job_id)}""", want_rows=True)
    return r[0] if r else None

def mark_interrupted_orphans():
    """Chamar no startup: jobs 'running' de um container morto viram 'interrupted'."""
    ensure_tables()
    sp_exec(f"UPDATE {T_JOBS} SET status='interrupted', finished_at={_sql_lit(_now())} "
            f"WHERE status='running'")
```

- [ ] **Step 2: Sintaxe**

```bash
cd app/backend && python -c "import ast; ast.parse(open('ingest.py').read()); print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/backend/ingest.py
git commit -m "feat(app): ingest — sp_exec, Files API, cache do corpus, tabelas de controle"
```

---

## Phase 3 — `ingest.py`: execução do pipeline

### Task 3.1: `run_extract_one` (extração de 1 EGP + preview)

**Files:** Modify `app/backend/ingest.py`

- [ ] **Step 1: Implementar**

Anexar em `ingest.py`:
```python
def _import_extractor():
    if PIPELINE_DIR not in sys.path:
        sys.path.insert(0, PIPELINE_DIR)
    import egps_extractor
    return egps_extractor

def run_extract_one(egp_bytes: bytes, filename: str, area: str, user: str, log=print):
    """Extrai 1 .egp: salva tmp, roda extractor -> WORK/text_egps, sobe .txt novo(s)
    ao Volume, registra em stage, devolve preview. Retorna dict com keys + inventário."""
    p = work_paths()
    os.makedirs(p["text"], exist_ok=True)
    before = set(os.listdir(p["text"]))
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1] or ".egp", delete=False) as tf:
        tf.write(egp_bytes)
        tmp_egp = tf.name
    try:
        ex = _import_extractor()
        ex.extract_code_from_egp(tmp_egp, p["text"], business_area=area)
    finally:
        os.unlink(tmp_egp)
    after = set(os.listdir(p["text"]))
    new_files = sorted(after - before)
    if not new_files:
        # re-extração de EGP já existente sobrescreve o mesmo .txt (mtime muda)
        raise RuntimeError("Extração não produziu .txt (EGP inválido ou vazio).")
    results = []
    for name in new_files:
        local = os.path.join(p["text"], name)
        with open(local, encoding="utf-8") as fh:
            inv = parse_io_inventory(fh.read())
        vol_upload(local, f"text_egps/{name}")
        key = os.path.splitext(name)[0]
        stage_add(key, area, user)
        results.append({"egp_key": key, "inventory": inv})
        log(f"extraído: {name} ({len(inv['external_inputs'])} inputs externos)")
    return results
```

**Nota:** re-upload de um EGP já existente gera o mesmo nome de `.txt` → não aparece em `after-before`. Tratamento: se `new_files` vazio mas o extractor rodou sem erro, comparar por mtime. Para manter simples, o fluxo aceita o caso comum (arquivo novo); re-extrações do mesmo EGP são raras e o Task 3.1b abaixo cobre.

- [ ] **Step 1b: Cobrir re-extração (mesmo nome)**

Substituir o bloco `if not new_files:` por deteção via mtime:
```python
    changed = new_files or [n for n in after
        if os.path.getmtime(os.path.join(p["text"], n)) >= (time.time() - 120)]
    if not changed:
        raise RuntimeError("Extração não produziu .txt (EGP inválido ou vazio).")
    seen = set()
    results = []
    for name in changed:
        if name in seen: continue
        seen.add(name)
```
(Ajustar o loop para iterar `changed` em vez de `new_files`.)

- [ ] **Step 2: Sintaxe**

```bash
cd app/backend && python -c "import ast; ast.parse(open('ingest.py').read()); print('ok')"
```
Expected: `ok`.

### Task 3.2: `run_orchestrator` e `run_publish` (subprocess)

**Files:** Modify `app/backend/ingest.py`

- [ ] **Step 1: Implementar**

Anexar em `ingest.py`:
```python
def _run(cmd, cwd, log, timeout=1800):
    log(f"$ {' '.join(cmd)} (cwd={cwd})")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]
    log(tail.strip())
    if proc.returncode != 0:
        raise RuntimeError(f"comando falhou (rc={proc.returncode}): {' '.join(cmd)}")
    return tail

def run_orchestrator(log=print):
    p = work_paths()
    _run([sys.executable, os.path.join(PIPELINE_DIR, "orchestrator_inventory.py"),
          "--prontidao-scope", "all"], cwd=p["root"], log=log, timeout=1800)

def run_publish(log=print):
    """Copia publish + indi p/ WORK (BASE=__file__ dir) e roda como SP (sem --profile)."""
    p = work_paths()
    shutil.copy(os.path.join(PIPELINE_DIR, "publish_to_databricks.py"),
                os.path.join(p["root"], "publish_to_databricks.py"))
    os.makedirs(os.path.join(p["root"], "docs", "analises"), exist_ok=True)
    indi_src = os.path.join(p["src"], "indi_231_vs_extracao_06.csv")
    if os.path.exists(indi_src):
        shutil.copy(indi_src, os.path.join(p["root"], "docs", "analises", "indi_231_vs_extracao_06.csv"))
    _run([sys.executable, os.path.join(p["root"], "publish_to_databricks.py"),
          "--apply", "--catalog", CATALOG, "--schema", SCHEMA,
          "--warehouse-id", WAREHOUSE_ID], cwd=p["root"], log=log, timeout=1800)

def upload_generated_csvs(log=print):
    p = work_paths()
    for name in glob.glob(os.path.join(p["root"], "0?_*.csv")):
        vol_upload(name, f"out/{os.path.basename(name)}")
    log("CSVs 01..06 arquivados no Volume (out/)")
```

- [ ] **Step 2: Sintaxe + commit**

```bash
cd app/backend && python -c "import ast; ast.parse(open('ingest.py').read()); print('ok')"
git add app/backend/ingest.py && git commit -m "feat(app): ingest — extração de 1 EGP + orchestrator/publish"
```

---

## Phase 4 — Backend `main.py`: `recompute_escopo(exec_fn)`, endpoints, job

### Task 4.1: Tornar `recompute_escopo` executável como SP

**Files:** Modify `app/backend/main.py` (~909-936)

- [ ] **Step 1: Threading de `exec_fn`**

Ler `recompute_escopo` (main.py ~909-936). Alterar a assinatura para `def recompute_escopo(exec_fn=None):` e no topo `exec_fn = exec_fn or run_sql`. Trocar **todas** as chamadas internas `run_sql(...)` por `exec_fn(...)`. Manter o final `global _lineage_gen; _lineage_gen += 1; _lineage_cache.clear()`. (As chamadas existentes `recompute_escopo()` continuam válidas — default = `run_sql`, OBO.)

- [ ] **Step 2: Import + alias SP no topo de main.py**

Perto dos outros imports/helpers em `main.py`:
```python
import ingest  # núcleo de ingestão (mesmo diretório)

def _sp_exec(statement, want_rows=False):
    return ingest.sp_exec(statement, want_rows=want_rows)
```

- [ ] **Step 3: Verificar compilação**

```bash
cd app/backend && python -c "import ast; ast.parse(open('main.py').read()); print('ok')"
```
Expected: `ok`. (Não rodar `main.py` — precisa de env Databricks.)

### Task 4.2: Endpoints de upload (chameleon + egp)

**Files:** Modify `app/backend/main.py`

- [ ] **Step 1: Imports FastAPI para upload**

Garantir no topo: `from fastapi import FastAPI, UploadFile, File, Form, HTTPException` (acrescentar `UploadFile, File, Form` ao import existente).

- [ ] **Step 2: Endpoints**

Adicionar (perto dos outros `@app.post`, após os de analistas):
```python
@app.post("/api/ingest/chameleon")
def ingest_chameleon(file: UploadFile = File(...)):
    _require_gestao()
    raw = file.file.read()
    ok, msg, n, cols = ingest.validate_chameleon(raw)
    if not ok:
        raise HTTPException(400, msg)
    ingest.vol_upload_bytes(raw, "src/chameleon.csv")
    return {"ok": True, "linhas": n, "msg": msg}

@app.post("/api/ingest/egp")
def ingest_egp(file: UploadFile = File(...), area: str = Form(...)):
    _require_gestao()
    if not area.strip():
        raise HTTPException(400, "Área é obrigatória.")
    raw = file.file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")
    user = _user_name() if "_user_name" in globals() else "app"
    try:
        results = ingest.run_extract_one(raw, file.filename or "upload.egp", area.strip(), user)
    except Exception as e:
        raise HTTPException(400, f"Falha na extração: {e}")
    return {"ok": True, "extraidos": results}

@app.get("/api/ingest/stage")
def ingest_stage():
    _require_gestao()
    rows = ingest.stage_list() or []
    return {"rows": rows, "running": ingest.job_running()}

@app.delete("/api/ingest/stage/{egp_key}")
def ingest_stage_del(egp_key: str):
    _require_gestao()
    ingest.stage_remove(egp_key)
    return {"ok": True}
```

**Nota `_user_name`:** se `main.py` já tiver um helper que devolve o e-mail do OBO (procure por `X-Forwarded-Email`/`current-user`), use-o; senão use `"app"`. (Não é crítico — é só auditoria.)

- [ ] **Step 3: Compilar**

```bash
cd app/backend && python -c "import ast; ast.parse(open('main.py').read()); print('ok')"
```
Expected: `ok`.

### Task 4.3: Endpoint `processar` + thread do job + `status`

**Files:** Modify `app/backend/main.py`

- [ ] **Step 1: Função do job + endpoints**

Adicionar em `main.py`:
```python
import threading as _threading

def _ingest_job(job_id: str):
    def log(m):
        try: ingest.job_update(job_id, log_append=str(m))
        except Exception: pass
    try:
        ingest.job_update(job_id, etapa="preparando")
        ingest.ensure_corpus_local(log=log)
        ingest.job_update(job_id, etapa="orchestrator")
        ingest.run_orchestrator(log=log)
        ingest.job_update(job_id, etapa="publicando")
        ingest.run_publish(log=log)
        ingest.upload_generated_csvs(log=log)
        ingest.job_update(job_id, etapa="reaplicando escopo")
        recompute_escopo(exec_fn=_sp_exec)   # re-aplica sas_escopo + bumpa cache
        ingest.sp_exec(f"UPDATE {ingest.T_STAGE} SET processed=true, job_id={ingest._sql_lit(job_id)} WHERE processed=false")
        ingest.job_update(job_id, etapa="concluído", status="done", finished=True)
    except Exception as e:
        ingest.job_update(job_id, etapa="erro", status="error", erro=str(e), finished=True)

@app.post("/api/ingest/processar")
def ingest_processar():
    _require_gestao()
    if ingest.job_running():
        raise HTTPException(409, "Já existe um processamento em andamento.")
    n = len(ingest.stage_list() or [])
    user = _user_name() if "_user_name" in globals() else "app"
    job_id = ingest.job_create(user, n)
    _threading.Thread(target=_ingest_job, args=(job_id,), daemon=True).start()
    return {"ok": True, "job_id": job_id}

@app.get("/api/ingest/status")
def ingest_status(job_id: str = ""):
    _require_gestao()
    if not job_id:
        return {"running": ingest.job_running()}
    j = ingest.job_get(job_id)
    if not j:
        raise HTTPException(404, "job não encontrado")
    return j
```

- [ ] **Step 2: Marcar órfãos no startup**

No bloco `if __name__ == "__main__":` (antes do `uvicorn.run`), adicionar:
```python
    try:
        ingest.mark_interrupted_orphans()
    except Exception as _e:
        print(f"[ingest] mark_interrupted_orphans falhou: {_e}")
```

- [ ] **Step 3: Compilar + commit**

```bash
cd app/backend && python -c "import ast; ast.parse(open('main.py').read()); print('ok')"
git add app/backend/main.py && git commit -m "feat(app): endpoints de ingestão + job em background (SP) + recompute_escopo(exec_fn)"
```

### Task 4.4: Verificação backend em produção (deploy — requer consentimento)

**Files:** nenhum.

- [ ] **Step 1: Deploy** (só com "pode dar deploy" do usuário) — ver comandos na Phase 6, Task 6.2.

- [ ] **Step 2: Smoke via curl** (com token OBO do usuário; peça ao usuário rodar `! ...` se necessário)

```bash
BASE=https://monitoramento-sas-4394921022945130.aws.databricksapps.com
# validação de chameleon (deve dar 200 + linhas)
curl -s -H "Authorization: Bearer $TOKEN" -F "file=@src/chameleon.csv" $BASE/api/ingest/chameleon
# stage vazio
curl -s -H "Authorization: Bearer $TOKEN" $BASE/api/ingest/stage
```
Expected: `{"ok":true,"linhas":...}` e `{"rows":[],"running":null}`.

---

## Phase 5 — Frontend: aba `Ingestão`

### Task 5.1: Tipos + API

**Files:** Modify `app/frontend/src/types.ts`, `app/frontend/src/api.ts`

- [ ] **Step 1: Tipos** (`types.ts`)

```typescript
export interface IoInventory {
  project: string; business_area: string; has_passthrough: boolean;
  external_inputs: string[]; imported_files: string[];
  internal_reads: string[]; permanent_outputs: string[]; exported_files: string[];
}
export interface EgpExtracted { egp_key: string; inventory: IoInventory; }
export interface StageRow { egp_key: string; area: string; uploaded_by: string; uploaded_at: string; }
export interface IngestStage { rows: StageRow[]; running: string | null; }
export interface IngestJob {
  job_id: string; status: string; etapa: string; started_at: string;
  finished_at: string | null; n_egps: number; log: string; erro: string | null;
}
```

- [ ] **Step 2: API** (`api.ts`, dentro do objeto `api`)

```typescript
  ingestChameleon: (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return fetch("api/ingest/chameleon", { method: "POST", body: fd }).then(json<{ ok: boolean; linhas: number; msg: string }>);
  },
  ingestEgp: (file: File, area: string) => {
    const fd = new FormData(); fd.append("file", file); fd.append("area", area);
    return fetch("api/ingest/egp", { method: "POST", body: fd }).then(json<{ ok: boolean; extraidos: EgpExtracted[] }>);
  },
  ingestStage: () => fetch("api/ingest/stage").then(json<IngestStage>),
  ingestStageDel: (k: string) => fetch(`api/ingest/stage/${encodeURIComponent(k)}`, { method: "DELETE" }).then(json<{ ok: boolean }>),
  ingestProcessar: () => fetch("api/ingest/processar", { method: "POST" }).then(json<{ ok: boolean; job_id: string }>),
  ingestStatus: (jobId: string) => fetch(`api/ingest/status?job_id=${encodeURIComponent(jobId)}`).then(json<IngestJob>),
```

Acrescentar os novos tipos ao `import type { … }` do topo do `api.ts`: `EgpExtracted, IngestStage, IngestJob`.

### Task 5.2: Registrar e gate da aba

**Files:** Modify `app/frontend/src/routes.ts`, `app/frontend/src/App.tsx`

- [ ] **Step 1: `routes.ts`**

- Adicionar `| "ingestao"` ao union `View`.
- Adicionar ao fim de `TABS`: `{ id: "ingestao", label: "Ingestão", slug: "ingestao" },`

- [ ] **Step 2: `App.tsx`**

- Import: `import IngestaoView from "./components/IngestaoView";`
- Atualizar o filtro de tabs para esconder `ingestao` de não-gestão:
  ```typescript
  {TABS.filter((t) => !["gestao", "ingestao"].includes(t.id) || cfg?.is_gestao).map((t) => (
  ```
- Adicionar o render condicional (junto ao de `gestao`):
  ```typescript
  {view === "ingestao" && (cfg?.is_gestao
    ? <IngestaoView />
    : cfg ? <div className="empty">Acesso restrito ao grupo de gestão (bv_users).</div> : null)}
  ```

### Task 5.3: Componente `IngestaoView.tsx`

**Files:** Create `app/frontend/src/components/IngestaoView.tsx`

- [ ] **Step 1: Implementar**

```tsx
import { useRef, useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { EgpExtracted, IngestJob } from "../types";

const AREAS = ["Cobrança", "Crédito", "Risco", "Atacado", "Varejo", "Negócios Transacionais", "Outros"];

export default function IngestaoView() {
  const qc = useQueryClient();
  const egpRef = useRef<HTMLInputElement>(null);
  const chamRef = useRef<HTMLInputElement>(null);
  const [area, setArea] = useState(AREAS[0]);
  const [msg, setMsg] = useState("");
  const [previews, setPreviews] = useState<EgpExtracted[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);

  const stage = useQuery({ queryKey: ["ingest-stage"], queryFn: () => api.ingestStage() });

  const upEgp = useMutation({
    mutationFn: (f: File) => api.ingestEgp(f, area),
    onSuccess: (r) => { setPreviews((p) => [...r.extraidos, ...p]); setMsg(`Extraído: ${r.extraidos.map(e => e.egp_key).join(", ")}`);
      qc.invalidateQueries({ queryKey: ["ingest-stage"] }); },
    onError: (e) => setMsg(`Falha EGP: ${e}`),
  });
  const upCham = useMutation({
    mutationFn: (f: File) => api.ingestChameleon(f),
    onSuccess: (r) => setMsg(`chameleon.csv ok — ${r.linhas} linhas`),
    onError: (e) => setMsg(`Falha chameleon: ${e}`),
  });
  const proc = useMutation({
    mutationFn: () => api.ingestProcessar(),
    onSuccess: (r) => { setJobId(r.job_id); setMsg("Processamento iniciado…"); },
    onError: (e) => setMsg(`Falha ao processar: ${e}`),
  });
  const delStage = useMutation({
    mutationFn: (k: string) => api.ingestStageDel(k),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ingest-stage"] }),
  });

  const job = useQuery<IngestJob>({
    queryKey: ["ingest-job", jobId],
    queryFn: () => api.ingestStatus(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && s !== "running" ? false : 2000;
    },
  });
  useEffect(() => {
    if (job.data && job.data.status !== "running") {
      qc.invalidateQueries({ queryKey: ["ingest-stage"] });
      if (job.data.status === "done") {
        // dados novos publicados → invalida tudo do painel
        qc.invalidateQueries();
        setPreviews([]);
      }
    }
  }, [job.data?.status]);

  const running = !!stage.data?.running || job.data?.status === "running" || proc.isPending;

  return (
    <div className="ingestao">
      <h2>Ingestão</h2>
      <p className="muted">Suba <code>.egp</code> e/ou <code>chameleon.csv</code>; depois clique <b>Processar &amp; publicar</b> (~5,5 min; reescreve as tabelas do painel).</p>
      {msg && <div className="muted">{msg}</div>}

      <div className="ingest-cards">
        <div className="card">
          <h3>Subir EGP</h3>
          <label>Área&nbsp;
            <select value={area} onChange={(e) => setArea(e.target.value)}>
              {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <input type="file" accept=".egp,.zip" ref={egpRef} disabled={upEgp.isPending}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upEgp.mutate(f); e.currentTarget.value = ""; }} />
          {upEgp.isPending && <span className="muted"> extraindo…</span>}
        </div>
        <div className="card">
          <h3>Subir chameleon.csv</h3>
          <input type="file" accept=".csv" ref={chamRef} disabled={upCham.isPending}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upCham.mutate(f); e.currentTarget.value = ""; }} />
          {upCham.isPending && <span className="muted"> validando…</span>}
        </div>
      </div>

      {previews.length > 0 && (
        <div className="card">
          <h3>Preview dos EGPs extraídos</h3>
          {previews.map((p) => (
            <div key={p.egp_key} className="preview">
              <b>{p.egp_key}</b> — {p.inventory.external_inputs.length} inputs externos, {p.inventory.permanent_outputs.length} outputs
              {p.inventory.external_inputs.length > 0 && <div className="muted">inputs: {p.inventory.external_inputs.join(", ")}</div>}
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h3>Na fila para processar</h3>
        {stage.isFetching && <span className="muted">…</span>}
        {(stage.data?.rows ?? []).length === 0 ? <div className="muted">nada na fila</div> : (
          <table><tbody>
            {(stage.data?.rows ?? []).map((r) => (
              <tr key={r.egp_key}>
                <td>{r.egp_key}</td><td>{r.area}</td>
                <td><button onClick={() => delStage.mutate(r.egp_key)} disabled={running}>remover</button></td>
              </tr>
            ))}
          </tbody></table>
        )}
        <button className="primary" disabled={running} onClick={() => proc.mutate()}>
          {running ? "Processando…" : "Processar & publicar"}
        </button>
      </div>

      {job.data && (
        <div className="card">
          <h3>Status</h3>
          <div>Etapa: <b>{job.data.etapa}</b> — {job.data.status}</div>
          {job.data.erro && <div className="error">Erro: {job.data.erro}</div>}
          {job.data.log && <pre className="job-log">{job.data.log}</pre>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Estilos** (`styles.css`, acrescentar)

```css
.ingest-cards { display: flex; gap: 16px; flex-wrap: wrap; }
.ingestao .card { margin: 12px 0; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.ingestao .preview { margin: 6px 0; }
.job-log { max-height: 240px; overflow: auto; background: var(--code-bg, #1113); padding: 8px; font-size: 12px; white-space: pre-wrap; }
```
(Se `--code-bg`/`--border` não existirem, usar variáveis já presentes no tema — conferir `styles.css`.)

- [ ] **Step 3: Type-check + build**

```bash
cd app/frontend && npm run build
```
Expected: `tsc -b` sem erros; bundle gerado em `../static/`.

- [ ] **Step 4: Commit**

```bash
git add app/frontend/src app/frontend/tsconfig.tsbuildinfo app/static
git commit -m "feat(app): aba Ingestão (upload egp/chameleon + processar/progresso)"
```

---

## Phase 6 — Integração, docs, deploy-verify

### Task 6.1: Documentação

**Files:** Modify `app/README.md`; memória.

- [ ] **Step 1: README** — nova subseção em "Decisões de design" descrevendo: aba Ingestão (gate bv_users), Volume `pipeline`, job em background como SP, `sas_ingest_jobs`/`sas_ingest_stage`, `recompute_escopo(exec_fn)`, e a armadilha `app/pipeline` vendored (fonte = `egps_analysis/`).

- [ ] **Step 2: Memória** — atualizar `monitoramento-sas-2026-06-features.md` (ou criar `monitoramento-sas-ingestao-in-app.md`) com: modelo in-container, Volume + grants do SP, job como SP (não OBO), corpus rehydrate via Files API, publish rodado de `WORK` (BASE=__file__). Linkar `[[monitoramento-sas-app-deploy]]`, `[[monitoramento-sas-deploy-verify]]`. Adicionar 1 linha no `MEMORY.md`.

### Task 6.2: Deploy (requer consentimento explícito do usuário)

**Files:** nenhum.

- [ ] **Step 1: Build + sync + deploy** (rodar de `app/`, conforme memória de deploy)

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npm run build
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app
WS=/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas
databricks sync . "$WS" --exclude 'frontend/node_modules/**' --exclude 'venv/**' -p bv
databricks apps deploy monitoramento-sas --source-code-path "$WS" -p bv
```
Expected: `state: SUCCEEDED`.

- [ ] **Step 2: Verificar artefato deployado** (disciplina de deploy-verify)

Confirmar que `requirements.txt` deployado tem pandas e que `main.py` deployado tem os endpoints de ingest:
```bash
databricks workspace export "$WS/requirements.txt" -p bv 2>/dev/null | grep -c pandas
databricks workspace export "$WS/backend/main.py" -p bv 2>/dev/null | grep -c "api/ingest/processar"
```
Expected: `1` e `>=1`.

### Task 6.3: Teste end-to-end em produção (com o usuário)

**Files:** nenhum.

- [ ] **Step 1:** Na UI (logado como `bv_users`): abrir a aba **Ingestão**; subir `chameleon.csv` → ver "X linhas".
- [ ] **Step 2:** Subir 1 `.egp` conhecido com Área → ver preview dos inputs; conferir que aparece na fila.
- [ ] **Step 3:** Clicar **Processar & publicar** → acompanhar etapas (preparando → orchestrator → publicando → reaplicando escopo → concluído). Ao concluir, conferir nas abas Monitoramento/EGPs que o novo EGP e seus inputs aparecem, e que **status humanos anteriores continuam intactos**.
- [ ] **Step 4:** Confirmar que um usuário **fora** de `bv_users` não vê a aba e recebe 403 em `/api/ingest/*`.

---

## Self-review (preenchido)

**Cobertura do spec:**
- Upload chameleon → Task 4.2 (endpoint) + 5.x (UI). ✅
- Upload egp + extração + preview → Task 3.1 + 4.2 + 5.3. ✅
- Volume durável + seed → Task 0.1; I/O → 2.2. ✅
- Job em background como SP + status + concorrência → 2.1/2.3/3.2/4.3. ✅
- Gate bv_users → 4.2/4.3 (`_require_gestao`) + 5.2 (esconde aba). ✅
- MERGE preserva colunas humanas → herdado do publish (verificado); reforçado no teste 6.3 Step 3. ✅
- recompute_escopo pós-publish + cache bump → 4.1/4.3. ✅
- Deploy-verify → 6.2. ✅
- Riscos (OOM resolvido; restart→interrupted) → 4.3 Step 2 (órfãos). ✅

**Placeholders:** nenhum "TBD/TODO". Pontos que exigem leitura de `main.py` ao vivo (âncoras de linha em `recompute_escopo`, `_user_name`) estão explicitados com o que procurar.

**Consistência de tipos:** `ingest.*` (sp_exec, vol_upload, run_extract_one, run_orchestrator, run_publish, stage_*, job_*) chamados em `main.py` batem com as assinaturas definidas nas Phases 1-3. Nomes de tabela `T_JOBS`/`T_STAGE` consistentes. Tipos TS (`EgpExtracted`, `IngestStage`, `IngestJob`) usados no componente batem com `types.ts`/`api.ts`.

---

## Emendas (review de qualidade do diff 5191a15..759584c, 2026-07-03)

O review encontrou 2 críticos + 2 importantes **no código inline deste plano** (a implementação os transcreveu fielmente). Corrigidos no commit de fix da Fase 3 — **não re-propagar o código antigo das Tasks 2.2/2.3/3.1**; as assinaturas públicas não mudaram (Fases 4-6 seguem válidas):

- **C1 (Task 3.1):** `NamedTemporaryFile` destruía a identidade do EGP — o extractor deriva stem e `PROJECT:` do basename em disco, gerando chave `Area__tmpXXXX` e duplicata-fantasma a cada re-upload. Fix: `mkdtemp()` + basename original sanitizado (`_safe_upload_name`); re-upload do mesmo EGP sobrescreve o mesmo `.txt` (premissa do fallback por mtime passa a valer).
- **C2 (Task 2.2):** `vol_list` engolia toda exceção → container frio + falha da Files API = corpus local vazio *silencioso* → orchestrator+publish full-replace destrutivo (linhagem zerada, tudo órfão). Fix: captura só `NotFound`; + preflight fail-loud em `run_orchestrator` (piso `PIPELINE_MIN_CORPUS`, default 1000 `.txt`; `src/` obrigatórios presentes).
- **I1 (Task 2.3):** `_sql_lit` sem escape de backslash (o `sql_lit` do main.py já tinha; o corpus é cheio de UNC paths `\\sasehml01\...`). Um `erro` com backslash travaria o job em `running` pra sempre. Fix: escaping byte-idêntico ao main.py + testes table-driven.
- **I2 (Task 3.1):** `_corpus_lock` declarado e nunca adquirido → uploads concorrentes cruzavam atribuição de `.txt`. Fix: lock em `run_extract_one` e `ensure_corpus_local`.
- Menores: download atômico (`.part` + `os.replace`); `sp_exec` com poll até estado terminal (sem falso-negativo >50s e sem rotular `PENDING` como falha); INSERTs com colunas nomeadas; cache de `ensure_tables`; `sp_client` via `lru_cache` (padrão do main.py); `max_workers=10`.
