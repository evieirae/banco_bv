# Pipeline Automatizado de Carregamento de EGPs — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o fluxo manual de extrair → orquestrar → publicar EGPs por um pipeline disparado automaticamente quando arquivos chegam num UC Volume, com upload de novos `.egp` via UI do próprio app Painel de Modernização SAS.

**Architecture:** Databricks Workflow (Job multi-task) com File Arrival trigger num UC Volume; tasks Python reusam os scripts existentes do `egps_analysis/` empacotados num Databricks Asset Bundle; manifesto Delta (`sas_pipeline_manifest`) controla idempotência por hash de conteúdo; novo POST `/api/upload` no FastAPI grava no Volume; aba Histórico do app ganha drill-down por run usando nova tabela `sas_pipeline_runs`.

**Tech Stack:** Python 3.10+ (existing scripts), Databricks Asset Bundles (workflow + bundle YAML), Databricks SDK, FastAPI (existing backend), React/TypeScript + Vite (existing frontend), UC Volumes + Delta tables, pytest para testes unitários de helpers novos.

---

## Resumo das decisões fechadas (referência)

| Aspecto | Resposta |
|---|---|
| Runtime | Databricks Job (Workflow) |
| Storage EGPs | UC Volume em `client_journey.monitoramento_sas` |
| Trigger | File Arrival no Volume |
| Granularidade | Extract incremental (hash) + orchestrator/publish full |
| GCP/Chameleon | SA dedicada (pedido formal) + ponte manual com `--job-project bv-sadn-dtm` enquanto SA não chega |
| Persistência | UC Volume + Delta `sas_pipeline_manifest` |
| Gate | Auto-publish + diff em `sas_pipeline_runs` + banner no app |
| Porta de entrada | Upload UI no app (drag-and-drop + dropdown de área por arquivo) |
| Colisão | Hash dedup (igual = no-op; diff = overwrite + reprocessa) |
| Escopo Indicium | Novo upload fora do escopo por padrão + checkbox no upload |

## File Structure

**Novos diretórios e arquivos a criar:**

- `egps_analysis/pipeline/` — novo pacote Python com helpers que serão chamados pelas tasks do Workflow
  - `__init__.py` — vazio
  - `manifest.py` — leitura/upsert da tabela Delta `sas_pipeline_manifest` (hash, status, timestamps)
  - `volume_io.py` — abstração para paths "Volume vs local" (extractor e orchestrator hoje assumem path local)
  - `diff_metrics.py` — calcula Δ entre estado anterior e atual de `sas_inputs_monitor` e popula `sas_pipeline_runs`
  - `job_extract.py` — entrypoint da task T1: lista `.egp` no Volume, decide quais reprocessar via manifest, chama o `egps_extractor.py` por arquivo
  - `job_chameleon.py` — entrypoint da task T2: refresca o snapshot `chameleon.csv` no Volume. Modo "skip" (default) só verifica idade; modo "fetch" (quando SA chegar) re-baixa do BQ
  - `job_orchestrate.py` — entrypoint da task T3: chama orchestrator + validators apontando para paths Volume
  - `job_publish.py` — entrypoint da task T4: chama `publish_to_databricks.py --apply` + popula `sas_pipeline_runs` com diff
- `egps_analysis/databricks_bundle/` — Asset Bundle para deployar o Workflow
  - `databricks.yml` — manifesto raiz do bundle
  - `resources/workflow_refresh.yml` — definição do Job multi-task
- `egps_analysis/tests/` — pytest para helpers novos
  - `__init__.py` — vazio
  - `conftest.py` — fixtures comuns
  - `test_manifest.py` — testes de upsert/skip logic
  - `test_volume_io.py` — testes do path resolver
  - `test_diff_metrics.py` — testes do cálculo de diff
- `egps_analysis/app/frontend/src/components/UploadView.tsx` — nova tela de upload
- `egps_analysis/app/frontend/src/components/RunHistoryView.tsx` — nova tela de histórico de runs (a aba Histórico atual segue exibindo edições humanas; runs ficam numa sub-aba ou outra aba; decisão na Task 4.7)

**Arquivos existentes a modificar:**

- `egps_analysis/requirements.txt` — adicionar `pytest>=7`, `python-multipart` (este último vai pro app/requirements.txt também)
- `egps_analysis/orchestrator_inventory.py:1125-1145` — aceitar flags `--text-egps-dir`, `--reports-dir`, `--src-dir` para sair do default relativo a `__file__`
- `egps_analysis/publish_to_databricks.py:280-310` — receber `--reports-dir` e gerar diff a ser registrado em `sas_pipeline_runs`
- `egps_analysis/publish_to_databricks.py:435-440` — adicionar DDL de `sas_pipeline_runs` ao bloco de criação de tabelas
- `egps_analysis/app/backend/main.py` — adicionar rotas `POST /api/upload`, `GET /api/run-history`, `GET /api/run-history/{run_id}`, `GET /api/last-run-status` (esta última usada pelo banner)
- `egps_analysis/app/requirements.txt` — adicionar `python-multipart`
- `egps_analysis/app/frontend/src/App.tsx` — adicionar tab "Upload" no início (`TABS`) e banner de falha do último run no topo
- `egps_analysis/app/frontend/src/types.ts` — adicionar tipos `UploadResult`, `RunHistoryRow`, `RunDetail`, `LastRunStatus`
- `egps_analysis/app/frontend/src/api.ts` — adicionar métodos `upload`, `runHistory`, `runDetail`, `lastRunStatus`

---

## Phase 0 — Bootstrap e Discovery (sem código)

> Objetivo: destravar o ambiente e validar o caminho de dados manualmente antes de escrever uma linha de código novo.

### Task 0.1: Criar venv local em `egps_analysis/`

**Files:** —

- [ ] **Step 1: Criar venv e instalar dependências**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Expected: `Successfully installed pandas-... openpyxl-... google-cloud-bigquery-...` sem erro.

- [ ] **Step 2: Verificar gcloud auth do usuário**

```bash
gcloud auth application-default print-access-token | head -c 20 && echo
```

Expected: imprime ~20 caracteres de access token. Se erro `Reauthentication needed`, rodar `gcloud auth application-default login`.

### Task 0.2: Validar acesso BQ ao Chameleon via `--job-project bv-sadn-dtm`

**Files:**
- Modify: `egps_analysis/src/chameleon.csv` (será gerado)

- [ ] **Step 1: Rodar o export pra um arquivo de teste**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
python gcp_bigquery_table_data_export.py \
  --query "SELECT NmTabela, NmTabelaWork, NmTabelaOrigem, DsOrigem, NmFonteDados, DtFimIngestao FROM \`bv-pdbd-prd.trusted_chameleon.tbindicadoringestao\`" \
  --job-project bv-sadn-dtm \
  -o ./src/chameleon.csv --format csv
```

Expected: arquivo `./src/chameleon.csv` criado, ~13MB, exit code 0.

- [ ] **Step 2: Validar shape do CSV**

```bash
wc -l ./src/chameleon.csv
head -2 ./src/chameleon.csv
```

Expected: ordem de milhares de linhas; primeira linha = `NmTabela,NmTabelaWork,NmTabelaOrigem,DsOrigem,NmFonteDados,DtFimIngestao`.

### Task 0.3: Solicitar SA dedicada ao admin GCP do BV

**Files:** —

- [ ] **Step 1: Enviar email/Slack ao contato GCP do BV**

Template (ajustar destinatário):

```
Assunto: Solicitação de Service Account no projeto bv-pdbd-prd para Databricks Job

Olá,

Estamos automatizando o Painel de Modernização SAS (app Databricks
"monitoramento-sas") e precisamos que um Databricks Workflow leia
diariamente a tabela bv-pdbd-prd.trusted_chameleon.tbindicadoringestao
para alimentar o inventário.

Hoje o acesso é feito como meu user (Lucas Müller, lucas.muller@indicium.tech)
usando `--job-project bv-sadn-dtm` — funciona localmente mas não em job
automatizado.

Pedido: criar Service Account dedicada, com escopo mínimo:
  - Nome sugerido: chameleon-reader@bv-sadn-dtm.iam.gserviceaccount.com
  - Permissões:
      * roles/bigquery.dataViewer no dataset bv-pdbd-prd.trusted_chameleon
      * roles/bigquery.jobUser no projeto bv-sadn-dtm
  - Chave JSON me enviada (será guardada em Databricks secret scope com
    acesso restrito ao service principal do Job).

Caso prefiram impersonation ou Workload Identity Federation, estou aberto
a discutir.

Obrigado.
```

Expected: ticket aberto / email enviado. Anotar data e contato no `_manifests/` do projeto (`_manifests/sa_request_log.md`, criação opcional).

### Task 0.4: Provisionar UC Volume e grants

**Files:** —

- [ ] **Step 1: Criar Volume**

Via Databricks CLI (precisa do `.env` do `converter/` sourceado per CLAUDE.md):

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
set -a && source <(tr -d '\r' < converter/.env) && set +a
export DATABRICKS_HOST="https://dbc-5626df64-1b10.cloud.databricks.com"

databricks volumes create client_journey monitoramento_sas egp_landing MANAGED
databricks volumes create client_journey monitoramento_sas text_egps MANAGED
databricks volumes create client_journey monitoramento_sas reports MANAGED
databricks volumes create client_journey monitoramento_sas chameleon_landing MANAGED
```

Expected: 4 Volumes criados, cada um devolvendo um JSON com `full_name`.

- [ ] **Step 2: Conferir paths esperados**

```bash
databricks fs ls dbfs:/Volumes/client_journey/monitoramento_sas/
```

Expected: lista os 4 volumes (`egp_landing/`, `text_egps/`, `reports/`, `chameleon_landing/`).

- [ ] **Step 3: Aplicar grants ao service principal do app**

Descobrir o SP atual:

```bash
databricks apps get monitoramento-sas | grep service_principal
```

Conceder permissões (substitua `<SP_NAME>` pelo retornado):

```bash
databricks grants update volume client_journey.monitoramento_sas.egp_landing \
  --json '{"changes":[{"principal":"<SP_NAME>","add":["READ_VOLUME","WRITE_VOLUME"]}]}'
databricks grants update volume client_journey.monitoramento_sas.text_egps \
  --json '{"changes":[{"principal":"<SP_NAME>","add":["READ_VOLUME"]}]}'
databricks grants update volume client_journey.monitoramento_sas.reports \
  --json '{"changes":[{"principal":"<SP_NAME>","add":["READ_VOLUME"]}]}'
databricks grants update volume client_journey.monitoramento_sas.chameleon_landing \
  --json '{"changes":[{"principal":"<SP_NAME>","add":["READ_VOLUME","WRITE_VOLUME"]}]}'
```

Expected: cada comando retorna a lista de grants atualizada sem erro.

### Task 0.5: Bootstrap — subir os 229 EGPs atuais + Chameleon inicial

**Files:** —

- [ ] **Step 1: Subir Chameleon inicial**

```bash
databricks fs cp egps_analysis/src/chameleon.csv \
  dbfs:/Volumes/client_journey/monitoramento_sas/chameleon_landing/chameleon.csv
```

Expected: `dbfs:/Volumes/.../chameleon.csv` listado em `databricks fs ls`.

- [ ] **Step 2: Subir todos os `.egp` atuais preservando estrutura por área**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
for area in new_egps/*/; do
  area_name=$(basename "$area")
  databricks fs cp -r "$area" \
    "dbfs:/Volumes/client_journey/monitoramento_sas/egp_landing/$area_name/" \
    --overwrite
done
```

Expected: cada `.egp` de `new_egps/<area>/` aparece em `/Volumes/.../egp_landing/<area>/`.

- [ ] **Step 3: Validar contagem**

```bash
databricks fs ls dbfs:/Volumes/client_journey/monitoramento_sas/egp_landing/ --recursive | grep -c '\.egp$'
```

Expected: ≥229 (pode ser mais se incluir _arquivo_*; ajustar conforme escopo).

### Task 0.6: Criar branch e commit baseline

**Files:** —

- [ ] **Step 1: Criar branch**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git checkout -b feat/auto-load-pipeline
```

- [ ] **Step 2: Verificar baseline limpa**

```bash
git status
```

Expected: branch criada. Se houver pendências do branch atual `import/project-sas`, decidir com o user se commita antes.

---

## Phase 1 — Pipeline Helpers + Databricks Workflow (sem trigger, sem UI)

> Objetivo: rodar o pipeline ponta-a-ponta no Databricks (manualmente via "Run now") usando os EGPs já no Volume.

### Task 1.1: Criar pacote `pipeline/` com manifesto Delta

**Files:**
- Create: `egps_analysis/pipeline/__init__.py`
- Create: `egps_analysis/pipeline/manifest.py`
- Create: `egps_analysis/tests/__init__.py`
- Create: `egps_analysis/tests/conftest.py`
- Create: `egps_analysis/tests/test_manifest.py`
- Modify: `egps_analysis/requirements.txt`

- [ ] **Step 1: Adicionar pytest ao requirements**

Edit `egps_analysis/requirements.txt`, adicionar ao final:

```
pytest>=7,<9
```

- [ ] **Step 2: Instalar pytest no venv**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
pip install -r requirements.txt
```

Expected: `Successfully installed pytest-...`.

- [ ] **Step 3: Criar pacote vazio + conftest**

```bash
mkdir -p pipeline tests
touch pipeline/__init__.py tests/__init__.py
```

Create `egps_analysis/tests/conftest.py`:

```python
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
```

- [ ] **Step 4: Escrever teste falhando para `egp_hash`**

Create `egps_analysis/tests/test_manifest.py`:

```python
import io
import os
import tempfile

from pipeline.manifest import egp_hash


def test_egp_hash_is_stable_for_same_content():
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "a.egp")
        p2 = os.path.join(d, "b.egp")
        with open(p1, "wb") as f:
            f.write(b"PK\x03\x04hello")
        with open(p2, "wb") as f:
            f.write(b"PK\x03\x04hello")
        assert egp_hash(p1) == egp_hash(p2)


def test_egp_hash_changes_when_content_changes():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.egp")
        with open(p, "wb") as f:
            f.write(b"PK\x03\x04hello")
        h1 = egp_hash(p)
        with open(p, "wb") as f:
            f.write(b"PK\x03\x04world")
        h2 = egp_hash(p)
        assert h1 != h2


def test_egp_hash_format_is_hex_sha256():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.egp")
        with open(p, "wb") as f:
            f.write(b"x")
        h = egp_hash(p)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
```

- [ ] **Step 5: Rodar teste, ver falhar**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
pytest tests/test_manifest.py -v
```

Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.manifest'` ou `ImportError: cannot import name 'egp_hash'`.

- [ ] **Step 6: Implementar `egp_hash`**

Create `egps_analysis/pipeline/manifest.py`:

```python
"""Helpers para a tabela Delta `sas_pipeline_manifest`.

Rastreia, por EGP, o hash do conteúdo binário, o caminho do .txt extraído,
o status do último processamento e timestamps. O extractor (T1) consulta
isso pra pular EGPs cujo hash já esteja registrado como SUCCESS.
"""
import hashlib

CHUNK = 1024 * 1024


def egp_hash(path: str) -> str:
    """SHA-256 hex do conteúdo binário do .egp."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 7: Rodar teste, ver passar**

```bash
pytest tests/test_manifest.py -v
```

Expected: 3 PASSED.

- [ ] **Step 8: Commitar**

```bash
git add egps_analysis/pipeline egps_analysis/tests egps_analysis/requirements.txt
git commit -m "feat(pipeline): pacote pipeline + egp_hash com testes"
```

### Task 1.2: Adicionar `Manifest` (read/upsert) usando Databricks SQL

**Files:**
- Modify: `egps_analysis/pipeline/manifest.py`
- Modify: `egps_analysis/tests/test_manifest.py`

- [ ] **Step 1: Adicionar teste para `Manifest.should_process`**

Append em `egps_analysis/tests/test_manifest.py`:

```python
from unittest.mock import MagicMock

from pipeline.manifest import Manifest


def _fake_runner(rows_by_query):
    """rows_by_query: list of (predicate, rows) — match by substring."""
    def runner(sql, *, want_rows=True):
        if not want_rows:
            return None
        for needle, rows in rows_by_query:
            if needle in sql:
                return rows
        return []
    return runner


def test_should_process_true_when_no_record():
    m = Manifest(run_sql=_fake_runner([("FROM ", [])]), table="cat.sch.m")
    assert m.should_process("k1", "abc") is True


def test_should_process_false_when_hash_matches_and_success():
    m = Manifest(run_sql=_fake_runner([
        ("FROM ", [{"egp_hash": "abc", "status": "SUCCESS"}]),
    ]), table="cat.sch.m")
    assert m.should_process("k1", "abc") is False


def test_should_process_true_when_hash_changed():
    m = Manifest(run_sql=_fake_runner([
        ("FROM ", [{"egp_hash": "xyz", "status": "SUCCESS"}]),
    ]), table="cat.sch.m")
    assert m.should_process("k1", "abc") is True


def test_should_process_true_when_last_status_failed():
    m = Manifest(run_sql=_fake_runner([
        ("FROM ", [{"egp_hash": "abc", "status": "FAILED"}]),
    ]), table="cat.sch.m")
    assert m.should_process("k1", "abc") is True
```

- [ ] **Step 2: Rodar teste, ver falhar**

```bash
pytest tests/test_manifest.py -v
```

Expected: 4 novos FAIL com `cannot import name 'Manifest'`.

- [ ] **Step 3: Implementar `Manifest`**

Append em `egps_analysis/pipeline/manifest.py`:

```python
def _lit(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


class Manifest:
    """Wrapper fino sobre `sas_pipeline_manifest`.

    Schema esperado (DDL no método ensure_table):
        egp_key STRING NOT NULL,
        area STRING,
        egp_hash STRING,
        egp_path STRING,
        txt_path STRING,
        status STRING,            -- SUCCESS | FAILED | RUNNING
        error STRING,
        extracted_at TIMESTAMP,
        run_id STRING

    `run_sql` é injetado pra desacoplar de databricks-sdk em testes; em produção,
    pass a função `run_sql` do job_extract que usa o SDK contra um SQL Warehouse.
    """

    DDL = """CREATE TABLE IF NOT EXISTS {table} (
        egp_key STRING NOT NULL,
        area STRING,
        egp_hash STRING,
        egp_path STRING,
        txt_path STRING,
        status STRING,
        error STRING,
        extracted_at TIMESTAMP,
        run_id STRING
    ) USING DELTA"""

    def __init__(self, run_sql, table: str):
        self.run_sql = run_sql
        self.table = table

    def ensure_table(self):
        self.run_sql(self.DDL.format(table=self.table), want_rows=False)

    def get(self, egp_key: str):
        rows = self.run_sql(
            f"SELECT egp_hash, status FROM {self.table} "
            f"WHERE egp_key = {_lit(egp_key)} ORDER BY extracted_at DESC LIMIT 1"
        )
        return rows[0] if rows else None

    def should_process(self, egp_key: str, new_hash: str) -> bool:
        rec = self.get(egp_key)
        if rec is None:
            return True
        if rec.get("status") != "SUCCESS":
            return True
        return rec.get("egp_hash") != new_hash

    def upsert(self, *, egp_key, area, egp_hash_, egp_path, txt_path,
               status, error=None, run_id):
        """Append simples (histórico preservado). Consulta lê o mais recente."""
        cols = ("egp_key", "area", "egp_hash", "egp_path", "txt_path",
                "status", "error", "extracted_at", "run_id")
        vals = (
            _lit(egp_key), _lit(area), _lit(egp_hash_), _lit(egp_path),
            _lit(txt_path), _lit(status), _lit(error),
            "current_timestamp()", _lit(run_id),
        )
        self.run_sql(
            f"INSERT INTO {self.table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(vals)})",
            want_rows=False,
        )
```

- [ ] **Step 4: Rodar testes**

```bash
pytest tests/test_manifest.py -v
```

Expected: 7 PASSED.

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/pipeline/manifest.py egps_analysis/tests/test_manifest.py
git commit -m "feat(pipeline): classe Manifest com upsert e should_process"
```

### Task 1.3: Helper `volume_io` para paths Volume/local

**Files:**
- Create: `egps_analysis/pipeline/volume_io.py`
- Create: `egps_analysis/tests/test_volume_io.py`

- [ ] **Step 1: Escrever testes**

Create `egps_analysis/tests/test_volume_io.py`:

```python
from pipeline.volume_io import resolve_egp_dir, resolve_text_dir, resolve_reports_dir, resolve_chameleon


def test_resolve_egp_dir_volume_mode():
    base = "/Volumes/client_journey/monitoramento_sas"
    assert resolve_egp_dir(base, "Riscos") == "/Volumes/client_journey/monitoramento_sas/egp_landing/Riscos"


def test_resolve_egp_dir_strips_trailing_slash():
    base = "/Volumes/client_journey/monitoramento_sas/"
    assert resolve_egp_dir(base, "TI").endswith("/egp_landing/TI")


def test_resolve_text_dir_creates_area_subpath():
    assert resolve_text_dir("/Volumes/x/y", "Cobranças") == "/Volumes/x/y/text_egps/Cobranças"


def test_resolve_reports_dir():
    assert resolve_reports_dir("/Volumes/x/y") == "/Volumes/x/y/reports"


def test_resolve_chameleon_path():
    assert resolve_chameleon("/Volumes/x/y") == "/Volumes/x/y/chameleon_landing/chameleon.csv"
```

- [ ] **Step 2: Rodar, ver falhar**

```bash
pytest tests/test_volume_io.py -v
```

Expected: FAIL `No module named 'pipeline.volume_io'`.

- [ ] **Step 3: Implementar**

Create `egps_analysis/pipeline/volume_io.py`:

```python
"""Path resolver para o conjunto de Volumes do Painel.

Layout dentro do volume base (default
`/Volumes/client_journey/monitoramento_sas`):

  egp_landing/<area>/*.egp          # input (upload pelo app ou CLI)
  text_egps/<area>/*.txt            # output do extractor (T1)
  reports/0[1-6]_*.csv              # output do orchestrator (T3)
  chameleon_landing/chameleon.csv   # CSV vindo do BQ (T2)
"""
import os


def _norm(p: str) -> str:
    return p.rstrip("/")


def resolve_egp_dir(base: str, area: str) -> str:
    return os.path.join(_norm(base), "egp_landing", area)


def resolve_text_dir(base: str, area: str) -> str:
    return os.path.join(_norm(base), "text_egps", area)


def resolve_reports_dir(base: str) -> str:
    return os.path.join(_norm(base), "reports")


def resolve_chameleon(base: str) -> str:
    return os.path.join(_norm(base), "chameleon_landing", "chameleon.csv")
```

- [ ] **Step 4: Rodar, ver passar**

```bash
pytest tests/test_volume_io.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/pipeline/volume_io.py egps_analysis/tests/test_volume_io.py
git commit -m "feat(pipeline): volume_io path resolver"
```

### Task 1.4: Refatorar `orchestrator_inventory.py` para aceitar paths externos

**Files:**
- Modify: `egps_analysis/orchestrator_inventory.py:1125-1145`

- [ ] **Step 1: Localizar o bloco do argparse**

```bash
grep -n "argparse\|add_argument\|TEXT_EGPS_DIR\|REPORTS_DIR\|CHAMELEON_CSV" /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/orchestrator_inventory.py | head -30
```

Expected: `argparse` na linha ~1128 e provavelmente paths hardcoded próximos do topo.

- [ ] **Step 2: Adicionar flags ao argparse**

No bloco `parser = argparse.ArgumentParser(...)` (linha ~1128), adicionar os argumentos abaixo, juntos com os existentes:

```python
parser.add_argument(
    "--text-egps-dir",
    default=None,
    help="Diretório com .txt extraídos (default: ./text_egps relativo ao script).",
)
parser.add_argument(
    "--reports-dir",
    default=None,
    help="Diretório de saída dos CSVs 01-06 (default: ./ relativo ao script).",
)
parser.add_argument(
    "--chameleon-csv",
    default=None,
    help="Path do chameleon.csv (default: ./src/chameleon.csv).",
)
parser.add_argument(
    "--inventario-csv",
    default=None,
    help="Path do inventario_transacional.csv (default: ./src/inventario_transacional.csv).",
)
```

- [ ] **Step 3: Substituir os usos das constantes globais**

No corpo do `main()` (após `args = parser.parse_args(...)`), inserir antes dos `load_*`:

```python
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_DIR = args.text_egps_dir or os.path.join(HERE, "text_egps")
REPORTS_DIR = args.reports_dir or HERE
CHAMELEON = args.chameleon_csv or os.path.join(HERE, "src", "chameleon.csv")
INVENTARIO = args.inventario_csv or os.path.join(HERE, "src", "inventario_transacional.csv")
```

Substituir referências subsequentes a `text_egps` / `chameleon.csv` / `inventario_transacional.csv` / paths de saída pelos novos. Isso requer leitura cuidadosa do arquivo (48KB); usar `grep -n "text_egps\|chameleon\|inventario_transacional" orchestrator_inventory.py` e atualizar cada uso pra usar `TEXT_DIR / CHAMELEON / INVENTARIO / REPORTS_DIR`.

- [ ] **Step 4: Smoke test local — paths default mantêm o comportamento atual**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
python orchestrator_inventory.py --prontidao-scope all
ls 01_*.csv 02_*.csv 03_*.csv 04_*.csv 05_*.csv 06_*.csv
```

Expected: roda igual antes, gera os 6 CSVs no diretório atual.

- [ ] **Step 5: Smoke test — paths explícitos**

```bash
mkdir -p /tmp/orc_out /tmp/orc_text
cp text_egps/Banco\ Relacional/*.txt /tmp/orc_text/ 2>/dev/null || true  # exemplo
python orchestrator_inventory.py \
  --text-egps-dir ./text_egps \
  --reports-dir /tmp/orc_out \
  --chameleon-csv ./src/chameleon.csv \
  --prontidao-scope all
ls /tmp/orc_out/
```

Expected: os 6 CSVs em `/tmp/orc_out/`.

- [ ] **Step 6: Commitar**

```bash
git add egps_analysis/orchestrator_inventory.py
git commit -m "feat(orchestrator): flags --text-egps-dir/--reports-dir/--chameleon-csv/--inventario-csv"
```

### Task 1.5: Adicionar `--reports-dir` ao `publish_to_databricks.py`

**Files:**
- Modify: `egps_analysis/publish_to_databricks.py:280-310, 380-395`

- [ ] **Step 1: Localizar onde os paths são definidos**

```bash
grep -n "^R06 =\|^R03 =\|^R04 =\|^INDI =\|^BASE =" /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/publish_to_databricks.py
```

Expected: constantes no topo do arquivo (linhas ~35-40).

- [ ] **Step 2: Tornar BASE/R0X overridable via argparse**

Editar o bloco do `argparse.ArgumentParser` (procurar por `parser = argparse.ArgumentParser`) e adicionar:

```python
parser.add_argument(
    "--reports-dir",
    default=None,
    help="Diretório com 03_, 04_, 06_*.csv. Default: dirname(__file__).",
)
parser.add_argument(
    "--indi-csv",
    default=None,
    help="Path do indi_231_vs_extracao_06.csv. Default: docs/analises/.../indi_231_vs_extracao_06.csv",
)
```

No corpo do `main()` após parse:

```python
reports_dir = args.reports_dir or BASE
R06 = os.path.join(reports_dir, "06_prontidao_tabela.csv")
R03 = os.path.join(reports_dir, "03_matriz_dependencias.csv")
R04 = os.path.join(reports_dir, "04_ondas_de_migracao.csv")
INDI = args.indi_csv or os.path.join(BASE, "docs", "analises", "indi_231_vs_extracao_06.csv")
```

Remover as constantes globais que ficaram redundantes.

- [ ] **Step 3: Smoke test dry-run**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
python publish_to_databricks.py
ls docs/analises/publish_databricks.preview.sql
```

Expected: arquivo `.preview.sql` é gerado e contém os CREATE TABLE habituais.

- [ ] **Step 4: Smoke test dry-run com --reports-dir**

```bash
python publish_to_databricks.py --reports-dir /tmp/orc_out
```

Expected: rodam sem erro, lendo os CSVs de `/tmp/orc_out/`.

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/publish_to_databricks.py
git commit -m "feat(publish): flags --reports-dir e --indi-csv pro Workflow Databricks"
```

### Task 1.6: Tabela `sas_pipeline_runs` + diff metrics

**Files:**
- Create: `egps_analysis/pipeline/diff_metrics.py`
- Create: `egps_analysis/tests/test_diff_metrics.py`

- [ ] **Step 1: Escrever testes**

Create `egps_analysis/tests/test_diff_metrics.py`:

```python
from pipeline.diff_metrics import compute_diff


def test_compute_diff_basic():
    prev = [{"chave_canonica": "k1"}, {"chave_canonica": "k2"}]
    curr = [{"chave_canonica": "k2"}, {"chave_canonica": "k3"}]
    d = compute_diff(prev, curr, key="chave_canonica")
    assert d["added"] == 1
    assert d["removed"] == 1
    assert d["unchanged"] == 1


def test_compute_diff_no_prev_means_all_added():
    curr = [{"chave_canonica": "k1"}, {"chave_canonica": "k2"}]
    d = compute_diff([], curr, key="chave_canonica")
    assert d["added"] == 2
    assert d["removed"] == 0
    assert d["unchanged"] == 0


def test_compute_diff_empty_curr_means_all_removed():
    prev = [{"chave_canonica": "k1"}]
    d = compute_diff(prev, [], key="chave_canonica")
    assert d["added"] == 0
    assert d["removed"] == 1
    assert d["unchanged"] == 0


def test_compute_diff_returns_lists_of_keys_when_requested():
    prev = [{"chave_canonica": "k1"}]
    curr = [{"chave_canonica": "k2"}]
    d = compute_diff(prev, curr, key="chave_canonica", return_keys=True)
    assert d["added_keys"] == ["k2"]
    assert d["removed_keys"] == ["k1"]
```

- [ ] **Step 2: Rodar, ver falhar**

```bash
pytest tests/test_diff_metrics.py -v
```

Expected: FAIL `No module named 'pipeline.diff_metrics'`.

- [ ] **Step 3: Implementar**

Create `egps_analysis/pipeline/diff_metrics.py`:

```python
"""Calcula diffs entre estados (antes/depois) do `sas_inputs_monitor` e
EGPs (`sas_lineage_nodes`) para popular `sas_pipeline_runs` — visível
na aba Histórico do app.
"""

RUNS_DDL = """CREATE TABLE IF NOT EXISTS {table} (
    run_id STRING NOT NULL,
    triggered_by STRING,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_s BIGINT,
    status STRING,                 -- SUCCESS | FAILED | RUNNING
    error STRING,
    egps_total INT,
    egps_added INT,
    egps_updated INT,
    egps_removed INT,
    inputs_added INT,
    inputs_removed INT,
    inputs_unchanged INT,
    notes STRING                   -- JSON livre (drill-down opcional)
) USING DELTA"""


def compute_diff(prev_rows, curr_rows, *, key, return_keys=False):
    prev_set = {r[key] for r in prev_rows}
    curr_set = {r[key] for r in curr_rows}
    added = curr_set - prev_set
    removed = prev_set - curr_set
    unchanged = prev_set & curr_set
    out = {
        "added": len(added),
        "removed": len(removed),
        "unchanged": len(unchanged),
    }
    if return_keys:
        out["added_keys"] = sorted(added)
        out["removed_keys"] = sorted(removed)
    return out
```

- [ ] **Step 4: Rodar, ver passar**

```bash
pytest tests/test_diff_metrics.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/pipeline/diff_metrics.py egps_analysis/tests/test_diff_metrics.py
git commit -m "feat(pipeline): compute_diff + DDL sas_pipeline_runs"
```

### Task 1.7: Job entrypoints — `job_extract.py`

**Files:**
- Create: `egps_analysis/pipeline/job_extract.py`

- [ ] **Step 1: Implementar entrypoint**

Create `egps_analysis/pipeline/job_extract.py`:

```python
"""Task T1 do Workflow: extrai .egp → .txt incrementalmente.

Lê o Volume `<base>/egp_landing/<area>/*.egp`, consulta o manifesto
`sas_pipeline_manifest`, e para cada EGP cujo hash mudou (ou que ainda não
foi extraído com sucesso) invoca o `egps_extractor.py` produzindo
`<base>/text_egps/<area>/<egp_key>.txt`.

Argumentos:
  --volume-base   path do Volume base (ex: /Volumes/client_journey/monitoramento_sas)
  --catalog       catálogo do manifesto Delta
  --schema        schema do manifesto Delta
  --warehouse-id  warehouse pra SQL execution
  --run-id        identificador do run atual (gerado pelo Workflow)
"""
import argparse
import os
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
EGPS_ANALYSIS = os.path.dirname(HERE)


def _make_runner(warehouse_id, catalog, schema):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format

    w = WorkspaceClient()

    def run_sql(stmt, *, want_rows=True):
        r = w.statement_execution.execute_statement(
            statement=stmt, warehouse_id=warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=catalog, schema=schema)
        sid = r.statement_id
        while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            r = w.statement_execution.get_statement(statement_id=sid)
        if not r.status or r.status.state != StatementState.SUCCEEDED:
            msg = r.status.error.message if (r.status and r.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--\n{stmt}")
        if not want_rows:
            return None
        cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
        data = r.result.data_array if (r.result and r.result.data_array) else []
        return [dict(zip(cols, row)) for row in data]

    return run_sql


def _egp_key(area: str, filename: str) -> str:
    """Mesma convenção do egps_extractor: <area>__<basename sem extensão>."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    return f"{area}__{stem}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume-base", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_id = args.run_id or str(uuid.uuid4())
    print(f"[extract] run_id={run_id}", flush=True)

    from pipeline.manifest import Manifest, egp_hash
    from pipeline.volume_io import resolve_egp_dir, resolve_text_dir

    run_sql = _make_runner(args.warehouse_id, args.catalog, args.schema)
    manifest = Manifest(run_sql, f"{args.catalog}.{args.schema}.sas_pipeline_manifest")
    manifest.ensure_table()

    landing = os.path.join(args.volume_base, "egp_landing")
    if not os.path.isdir(landing):
        print(f"[extract] FATAL: {landing} não existe.", file=sys.stderr)
        sys.exit(2)

    total = 0
    processed = 0
    skipped = 0
    failed = 0

    for area in sorted(os.listdir(landing)):
        area_dir = resolve_egp_dir(args.volume_base, area)
        if not os.path.isdir(area_dir):
            continue
        for fname in sorted(os.listdir(area_dir)):
            if not fname.lower().endswith(".egp"):
                continue
            total += 1
            egp_path = os.path.join(area_dir, fname)
            key = _egp_key(area, fname)
            h = egp_hash(egp_path)
            if not manifest.should_process(key, h):
                skipped += 1
                continue
            text_dir = resolve_text_dir(args.volume_base, area)
            os.makedirs(text_dir, exist_ok=True)
            print(f"[extract] {key}: extracting", flush=True)
            cmd = [
                sys.executable,
                os.path.join(EGPS_ANALYSIS, "egps_extractor.py"),
                egp_path,
                "--out-dir", text_dir,
                "--area", area,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                txt = os.path.join(text_dir, f"{key}.txt")
                manifest.upsert(
                    egp_key=key, area=area, egp_hash_=h,
                    egp_path=egp_path, txt_path=txt,
                    status="SUCCESS", error=None, run_id=run_id,
                )
                processed += 1
            except subprocess.CalledProcessError as e:
                err = (e.stderr or e.stdout or str(e))[:2000]
                manifest.upsert(
                    egp_key=key, area=area, egp_hash_=h,
                    egp_path=egp_path, txt_path=None,
                    status="FAILED", error=err, run_id=run_id,
                )
                failed += 1
                print(f"[extract] {key}: FAILED — {err[:200]}", file=sys.stderr)

    print(f"[extract] done — total={total} processed={processed} skipped={skipped} failed={failed}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificar que `egps_extractor.py` aceita `--out-dir` e `--area`**

```bash
grep -n "add_argument.*out-dir\|add_argument.*area" /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/egps_extractor.py | head
```

Expected: ambos os args já existem (per CLAUDE.md). Se algum faltar, adicionar uma sub-task pra incluí-lo no `egps_extractor.py`.

- [ ] **Step 3: Smoke test sintático**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
python -m pipeline.job_extract --help
```

Expected: imprime a ajuda do argparse.

- [ ] **Step 4: Commitar**

```bash
git add egps_analysis/pipeline/job_extract.py
git commit -m "feat(pipeline): job_extract entrypoint da task T1"
```

### Task 1.8: Job entrypoints — `job_chameleon.py`

**Files:**
- Create: `egps_analysis/pipeline/job_chameleon.py`

- [ ] **Step 1: Implementar entrypoint (modo `skip`)**

Create `egps_analysis/pipeline/job_chameleon.py`:

```python
"""Task T2: refresca o snapshot chameleon.csv no Volume.

Modo padrão `--mode skip` apenas verifica se o CSV existe e é mais novo que
`--stale-after-hours` (default 36h). Se estiver fresco, no-op. Se estiver
velho ou faltando, falha o job com mensagem clara — Lucas roda manualmente.

Quando a SA dedicada estiver disponível, mudar pra `--mode fetch`, que usa
o `gcp_bigquery_table_data_export.py` com `GOOGLE_APPLICATION_CREDENTIALS`
apontando pra um secret montado.
"""
import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EGPS_ANALYSIS = os.path.dirname(HERE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume-base", required=True)
    parser.add_argument("--mode", choices=("skip", "fetch"), default="skip")
    parser.add_argument("--stale-after-hours", type=int, default=36)
    parser.add_argument("--job-project", default="bv-sadn-dtm")
    args = parser.parse_args()

    from pipeline.volume_io import resolve_chameleon

    path = resolve_chameleon(args.volume_base)
    if args.mode == "skip":
        if not os.path.exists(path):
            print(f"[chameleon] FATAL: {path} ausente. Rode manualmente:")
            _print_manual_cmd(args.job_project, path)
            sys.exit(2)
        age_h = (datetime.datetime.now().timestamp() - os.path.getmtime(path)) / 3600
        if age_h > args.stale_after_hours:
            print(f"[chameleon] FATAL: {path} tem {age_h:.1f}h (limite: {args.stale_after_hours}h).")
            _print_manual_cmd(args.job_project, path)
            sys.exit(2)
        print(f"[chameleon] OK — idade {age_h:.1f}h, dentro do limite.")
        return

    # mode == fetch — usado quando SA estiver disponível
    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred or not os.path.exists(cred):
        print("[chameleon] FATAL: GOOGLE_APPLICATION_CREDENTIALS não configurado", file=sys.stderr)
        sys.exit(2)
    cmd = [
        sys.executable,
        os.path.join(EGPS_ANALYSIS, "gcp_bigquery_table_data_export.py"),
        "--query",
        "SELECT NmTabela, NmTabelaWork, NmTabelaOrigem, DsOrigem, "
        "NmFonteDados, DtFimIngestao "
        "FROM `bv-pdbd-prd.trusted_chameleon.tbindicadoringestao`",
        "--job-project", args.job_project,
        "-o", path,
        "--format", "csv",
    ]
    subprocess.run(cmd, check=True)
    print(f"[chameleon] refreshed → {path}")


def _print_manual_cmd(job_project, dest):
    print()
    print("Para atualizar manualmente, do laptop:")
    print(f"  cd egps_analysis && source venv/bin/activate && \\")
    print(f"  python gcp_bigquery_table_data_export.py --job-project {job_project} \\")
    print(f"    --query \"SELECT NmTabela,NmTabelaWork,NmTabelaOrigem,DsOrigem,"
          f"NmFonteDados,DtFimIngestao FROM \\`bv-pdbd-prd.trusted_chameleon.tbindicadoringestao\\`\" \\")
    print(f"    -o ./src/chameleon.csv --format csv && \\")
    print(f"  databricks fs cp ./src/chameleon.csv dbfs:{dest}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
python -m pipeline.job_chameleon --help
```

Expected: imprime ajuda.

- [ ] **Step 3: Commitar**

```bash
git add egps_analysis/pipeline/job_chameleon.py
git commit -m "feat(pipeline): job_chameleon (skip ou fetch quando SA chegar)"
```

### Task 1.9: Job entrypoints — `job_orchestrate.py` e `job_publish.py`

**Files:**
- Create: `egps_analysis/pipeline/job_orchestrate.py`
- Create: `egps_analysis/pipeline/job_publish.py`

- [ ] **Step 1: Implementar orchestrate**

Create `egps_analysis/pipeline/job_orchestrate.py`:

```python
"""Task T3: roda orchestrator_inventory.py + validators apontando para
os paths do Volume.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EGPS_ANALYSIS = os.path.dirname(HERE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume-base", required=True)
    args = parser.parse_args()

    from pipeline.volume_io import resolve_reports_dir, resolve_chameleon

    text_dir = os.path.join(args.volume_base, "text_egps")
    reports_dir = resolve_reports_dir(args.volume_base)
    chameleon = resolve_chameleon(args.volume_base)
    os.makedirs(reports_dir, exist_ok=True)

    # 1) orchestrator
    subprocess.run([
        sys.executable,
        os.path.join(EGPS_ANALYSIS, "orchestrator_inventory.py"),
        "--text-egps-dir", text_dir,
        "--reports-dir", reports_dir,
        "--chameleon-csv", chameleon,
        "--prontidao-scope", "all",
    ], check=True)

    # 2) validators
    subprocess.run([
        sys.executable,
        os.path.join(EGPS_ANALYSIS, "validate_table_in_vs_repmap.py"),
        "--reports-dir", reports_dir,
    ], check=True)

    subprocess.run([
        sys.executable,
        os.path.join(EGPS_ANALYSIS, "migration_hints_table_in_repmap_chameleon.py"),
        "--reports-dir", reports_dir,
        "--chameleon-csv", chameleon,
    ], check=True)

    print(f"[orchestrate] reports → {reports_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Adicionar `--reports-dir` aos validators (se ainda não tiverem)**

Inspecionar:

```bash
grep -n "argparse\|add_argument" /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/validate_table_in_vs_repmap.py | head
grep -n "argparse\|add_argument" /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/migration_hints_table_in_repmap_chameleon.py | head
```

Se necessário, adicionar `--reports-dir` e `--chameleon-csv` nos dois (padrão idêntico ao da Task 1.4). Sub-task: edita cada arquivo, smoke test, commit separado se ficar grande.

- [ ] **Step 3: Implementar publish**

Create `egps_analysis/pipeline/job_publish.py`:

```python
"""Task T4: chama publish_to_databricks.py --apply contra os reports no
Volume + popula sas_pipeline_runs com diff.

Captura o estado de `sas_inputs_monitor` ANTES do publish, executa o publish,
e em seguida calcula diff vs depois, gravando 1 linha em sas_pipeline_runs.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
EGPS_ANALYSIS = os.path.dirname(HERE)


def _make_runner(warehouse_id, catalog, schema):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format

    w = WorkspaceClient()

    def run_sql(stmt, *, want_rows=True):
        r = w.statement_execution.execute_statement(
            statement=stmt, warehouse_id=warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=catalog, schema=schema)
        sid = r.statement_id
        while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            r = w.statement_execution.get_statement(statement_id=sid)
        if not r.status or r.status.state != StatementState.SUCCEEDED:
            msg = r.status.error.message if (r.status and r.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}")
        if not want_rows:
            return None
        cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
        data = r.result.data_array if (r.result and r.result.data_array) else []
        return [dict(zip(cols, row)) for row in data]

    return run_sql


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume-base", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--triggered-by", default="workflow")
    args = parser.parse_args()

    from pipeline.diff_metrics import compute_diff, RUNS_DDL
    from pipeline.volume_io import resolve_reports_dir

    run_id = args.run_id or str(uuid.uuid4())
    started = datetime.datetime.utcnow()
    run_sql = _make_runner(args.warehouse_id, args.catalog, args.schema)
    runs_table = f"{args.catalog}.{args.schema}.sas_pipeline_runs"
    inputs_table = f"{args.catalog}.{args.schema}.sas_inputs_monitor"
    nodes_table = f"{args.catalog}.{args.schema}.sas_lineage_nodes"

    run_sql(RUNS_DDL.format(table=runs_table), want_rows=False)
    run_sql(
        f"INSERT INTO {runs_table} (run_id, triggered_by, started_at, status) "
        f"VALUES ('{run_id}', '{args.triggered_by}', current_timestamp(), 'RUNNING')",
        want_rows=False,
    )

    # estado prévio
    prev_inputs = run_sql(f"SELECT chave_canonica FROM {inputs_table}") or []
    prev_egps = run_sql(f"SELECT projeto FROM {nodes_table}") or []

    try:
        subprocess.run([
            sys.executable,
            os.path.join(EGPS_ANALYSIS, "publish_to_databricks.py"),
            "--apply",
            "--reports-dir", resolve_reports_dir(args.volume_base),
        ], check=True)
    except subprocess.CalledProcessError as e:
        run_sql(
            f"UPDATE {runs_table} SET status='FAILED', "
            f"finished_at=current_timestamp(), "
            f"duration_s=unix_timestamp(current_timestamp())-unix_timestamp(started_at), "
            f"error='{str(e)[:500].replace(chr(39), chr(39)+chr(39))}' "
            f"WHERE run_id='{run_id}'", want_rows=False)
        raise

    # estado pós
    curr_inputs = run_sql(f"SELECT chave_canonica FROM {inputs_table}") or []
    curr_egps = run_sql(f"SELECT projeto FROM {nodes_table}") or []

    diff_in = compute_diff(prev_inputs, curr_inputs, key="chave_canonica")
    diff_egp = compute_diff(prev_egps, curr_egps, key="projeto")

    run_sql(
        f"UPDATE {runs_table} SET "
        f"status='SUCCESS', finished_at=current_timestamp(), "
        f"duration_s=unix_timestamp(current_timestamp())-unix_timestamp(started_at), "
        f"egps_total={len(curr_egps)}, "
        f"egps_added={diff_egp['added']}, egps_removed={diff_egp['removed']}, "
        f"egps_updated={diff_egp['unchanged']}, "
        f"inputs_added={diff_in['added']}, inputs_removed={diff_in['removed']}, "
        f"inputs_unchanged={diff_in['unchanged']} "
        f"WHERE run_id='{run_id}'", want_rows=False)
    print(f"[publish] run_id={run_id} success — Δinputs +{diff_in['added']}/-{diff_in['removed']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
python -m pipeline.job_orchestrate --help
python -m pipeline.job_publish --help
```

Expected: ambos imprimem ajuda.

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/pipeline/job_orchestrate.py egps_analysis/pipeline/job_publish.py
git commit -m "feat(pipeline): job_orchestrate + job_publish com diff em sas_pipeline_runs"
```

### Task 1.10: Asset Bundle do Workflow

**Files:**
- Create: `egps_analysis/databricks_bundle/databricks.yml`
- Create: `egps_analysis/databricks_bundle/resources/workflow_refresh.yml`

- [ ] **Step 1: Criar bundle root**

Create `egps_analysis/databricks_bundle/databricks.yml`:

```yaml
bundle:
  name: monitoramento-sas-refresh

include:
  - resources/*.yml

targets:
  dev:
    mode: development
    workspace:
      host: https://dbc-5626df64-1b10.cloud.databricks.com
    variables:
      catalog: client_journey
      schema: monitoramento_sas
      volume_base: /Volumes/client_journey/monitoramento_sas
      warehouse_id: 5922c26f81f1bbdd
      notification_email: lucas.muller@indicium.tech

variables:
  catalog:
    description: UC catalog onde residem as tabelas Delta do app
  schema:
    description: UC schema dentro do catalog
  volume_base:
    description: Path base dos Volumes (egp_landing, text_egps, reports, chameleon_landing)
  warehouse_id:
    description: ID do SQL Warehouse usado pelo job
  notification_email:
    description: Email para alertas on-failure
```

- [ ] **Step 2: Criar workflow definition**

Create `egps_analysis/databricks_bundle/resources/workflow_refresh.yml`:

```yaml
resources:
  jobs:
    monitoramento_sas_refresh:
      name: monitoramento-sas-refresh
      max_concurrent_runs: 1
      email_notifications:
        on_failure:
          - ${var.notification_email}
        no_alert_for_skipped_runs: true

      # File arrival trigger ativado em Phase 2 — em Phase 1 fica desabilitado
      # via "pause_status: PAUSED" pra rodar só manualmente.
      trigger:
        pause_status: PAUSED
        file_arrival:
          url: ${var.volume_base}/egp_landing/
          min_time_between_triggers_seconds: 300

      job_clusters:
        - job_cluster_key: pipeline_cluster
          new_cluster:
            spark_version: 14.3.x-scala2.12
            node_type_id: i3.xlarge
            num_workers: 0
            data_security_mode: SINGLE_USER

      tasks:
        - task_key: extract
          job_cluster_key: pipeline_cluster
          spark_python_task:
            python_file: ../../egps_analysis/pipeline/job_extract.py
            parameters:
              - --volume-base
              - ${var.volume_base}
              - --catalog
              - ${var.catalog}
              - --schema
              - ${var.schema}
              - --warehouse-id
              - ${var.warehouse_id}
              - --run-id
              - "{{job.run_id}}"
          libraries:
            - pypi:
                package: databricks-sdk>=0.20.0

        - task_key: chameleon
          depends_on:
            - task_key: extract
          job_cluster_key: pipeline_cluster
          spark_python_task:
            python_file: ../../egps_analysis/pipeline/job_chameleon.py
            parameters:
              - --volume-base
              - ${var.volume_base}
              - --mode
              - skip
              - --stale-after-hours
              - "36"

        - task_key: orchestrate
          depends_on:
            - task_key: chameleon
          job_cluster_key: pipeline_cluster
          spark_python_task:
            python_file: ../../egps_analysis/pipeline/job_orchestrate.py
            parameters:
              - --volume-base
              - ${var.volume_base}
          libraries:
            - pypi:
                package: openpyxl
            - pypi:
                package: pandas

        - task_key: publish
          depends_on:
            - task_key: orchestrate
          job_cluster_key: pipeline_cluster
          spark_python_task:
            python_file: ../../egps_analysis/pipeline/job_publish.py
            parameters:
              - --volume-base
              - ${var.volume_base}
              - --catalog
              - ${var.catalog}
              - --schema
              - ${var.schema}
              - --warehouse-id
              - ${var.warehouse_id}
              - --run-id
              - "{{job.run_id}}"
              - --triggered-by
              - "{{job.trigger.type}}"
          libraries:
            - pypi:
                package: databricks-sdk>=0.20.0
```

- [ ] **Step 3: Validar bundle**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
set -a && source <(tr -d '\r' < converter/.env) && set +a
export DATABRICKS_HOST="https://dbc-5626df64-1b10.cloud.databricks.com"

cd egps_analysis/databricks_bundle
databricks bundle validate --target dev
```

Expected: `Name: monitoramento-sas-refresh` e nenhuma mensagem de erro.

- [ ] **Step 4: Deploy do bundle (dry-run primeiro)**

```bash
databricks bundle deploy --target dev
```

Expected: `Deployment complete!` e o Workflow listado no UI do Databricks.

- [ ] **Step 5: Run manual e observar**

```bash
databricks bundle run monitoramento_sas_refresh --target dev
```

Expected: o Job inicia, as 4 tasks rodam em sequência, status final `SUCCESS`. Se falhar, abrir a task no UI do Databricks pra ver o stderr.

- [ ] **Step 6: Validar que `sas_pipeline_runs` ganhou linha**

```bash
databricks sql query \
  --warehouse-id 5922c26f81f1bbdd \
  --query "SELECT run_id, status, duration_s, egps_total, inputs_added, inputs_removed FROM client_journey.monitoramento_sas.sas_pipeline_runs ORDER BY started_at DESC LIMIT 3"
```

Expected: 1 linha com status `SUCCESS`.

- [ ] **Step 7: Commitar**

```bash
git add egps_analysis/databricks_bundle
git commit -m "feat(workflow): Asset Bundle do monitoramento-sas-refresh"
```

---

## Phase 2 — Ativar File Arrival Trigger

> Objetivo: upload manual via CLI no Volume já dispara o pipeline sem clique.

### Task 2.1: Tirar PAUSED do trigger

**Files:**
- Modify: `egps_analysis/databricks_bundle/resources/workflow_refresh.yml`

- [ ] **Step 1: Editar arquivo**

Mudar:

```yaml
      trigger:
        pause_status: PAUSED
        file_arrival:
```

para:

```yaml
      trigger:
        pause_status: UNPAUSED
        file_arrival:
```

- [ ] **Step 2: Re-deploy**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/databricks_bundle
databricks bundle deploy --target dev
```

Expected: `Deployment complete!`.

- [ ] **Step 3: Testar — subir 1 EGP novo**

Pega um EGP qualquer que ainda não esteja no Volume (ou usa um modificado):

```bash
# exemplo: copiar pra forçar disparo
databricks fs cp egps_analysis/new_egps/Riscos/Saída\ de\ Risco_v1.egp \
  dbfs:/Volumes/client_journey/monitoramento_sas/egp_landing/Riscos/Saída_de_Risco_v1_TEST.egp \
  --overwrite
```

Expected: dentro de 1-5min, o Workflow inicia sozinho (visível em "Workflows" → "monitoramento-sas-refresh" → "Runs").

- [ ] **Step 4: Limpeza do arquivo de teste**

```bash
databricks fs rm dbfs:/Volumes/client_journey/monitoramento_sas/egp_landing/Riscos/Saída_de_Risco_v1_TEST.egp
```

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/databricks_bundle/resources/workflow_refresh.yml
git commit -m "feat(workflow): ativa file arrival trigger"
```

---

## Phase 3 — Upload UI no app

### Task 3.1: Backend — `POST /api/upload` com hash dedup

**Files:**
- Modify: `egps_analysis/app/backend/main.py`
- Modify: `egps_analysis/app/requirements.txt`

- [ ] **Step 1: Adicionar `python-multipart` ao requirements**

Edit `egps_analysis/app/requirements.txt`, adicionar:

```
python-multipart>=0.0.9
```

- [ ] **Step 2: Adicionar imports e constantes em `main.py`**

No topo de `egps_analysis/app/backend/main.py`, após os imports existentes:

```python
import hashlib
from fastapi import UploadFile, File, Form

VOLUME_BASE = os.environ.get(
    "VOLUME_BASE",
    "/Volumes/client_journey/monitoramento_sas",
)
EGP_LANDING = os.path.join(VOLUME_BASE, "egp_landing")
KNOWN_AREAS = {"Banco Relacional", "Cobranças", "Finanças", "Riscos", "TI", "Cartões"}
T_MANIFEST = f"{FQ}.sas_pipeline_manifest"
```

- [ ] **Step 3: Adicionar endpoint**

Antes do bloco `app.mount("/", StaticFiles(...))` ou similar (deixar antes da rota estática catch-all), adicionar:

```python
def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


@app.post("/api/upload")
async def upload_egp(
    file: UploadFile = File(...),
    area: str = Form(...),
    include_in_scope: bool = Form(False),
):
    if not file.filename.lower().endswith(".egp"):
        raise HTTPException(400, "Apenas arquivos .egp são aceitos.")
    if area not in KNOWN_AREAS:
        raise HTTPException(400, f"Área inválida: {area}. Use: {sorted(KNOWN_AREAS)}")

    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Arquivo > 50MB rejeitado.")
    new_hash = _sha256(data)

    stem = os.path.splitext(os.path.basename(file.filename))[0]
    egp_key = f"{area}__{stem}"
    rows = run_sql(
        f"SELECT egp_hash FROM {T_MANIFEST} "
        f"WHERE egp_key = {sql_lit(egp_key)} "
        f"ORDER BY extracted_at DESC LIMIT 1"
    )
    if rows and rows[0].get("egp_hash") == new_hash:
        return {"status": "noop", "reason": "hash idêntico ao último processado", "egp_key": egp_key}

    target_dir = os.path.join(EGP_LANDING, area)
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, file.filename)
    with open(target_path, "wb") as f:
        f.write(data)

    if include_in_scope:
        # Sinaliza no log do servidor; aplicação efetiva ao indi_231 é follow-up
        # (ver "Notas operacionais" #3 no fim do plano).
        print(f"[upload] {egp_key}: marcado include_in_scope=true")

    return {
        "status": "uploaded",
        "egp_key": egp_key,
        "path": target_path,
        "hash": new_hash,
        "size": len(data),
    }
```

- [ ] **Step 4: Smoke local**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app
set -a && source <(tr -d '\r' < ../../converter/.env) && set +a
export DATABRICKS_HOST="https://dbc-5626df64-1b10.cloud.databricks.com"
export DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd
export PUBLISH_CATALOG=client_journey
export PUBLISH_SCHEMA=monitoramento_sas
export VOLUME_BASE=/Volumes/client_journey/monitoramento_sas
../venv/bin/python backend/main.py &
BACKEND_PID=$!
sleep 3

curl -s -F "file=@../new_egps/Riscos/Saída de Risco_v1.egp" \
     -F "area=Riscos" \
     -F "include_in_scope=false" \
     http://localhost:8000/api/upload
kill $BACKEND_PID
```

Expected: JSON com `status: "uploaded"` ou `status: "noop"` (se já estiver no Volume com mesmo hash).

- [ ] **Step 5: Commitar**

```bash
git add egps_analysis/app/backend/main.py egps_analysis/app/requirements.txt
git commit -m "feat(app/back): POST /api/upload com hash dedup"
```

### Task 3.2: Frontend — tipos e cliente da rota

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts`
- Modify: `egps_analysis/app/frontend/src/api.ts`

- [ ] **Step 1: Tipos**

Append em `egps_analysis/app/frontend/src/types.ts`:

```typescript
export type UploadResult =
  | { status: "uploaded"; egp_key: string; path: string; hash: string; size: number }
  | { status: "noop"; reason: string; egp_key: string };

export type UploadItem = {
  file: File;
  area: string;
  includeInScope: boolean;
  status: "pending" | "uploading" | "done" | "error";
  result?: UploadResult;
  error?: string;
};
```

- [ ] **Step 2: Cliente**

Append em `egps_analysis/app/frontend/src/api.ts` no objeto `api`:

```typescript
upload: async (file: File, area: string, includeInScope: boolean): Promise<UploadResult> => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("area", area);
  fd.append("include_in_scope", includeInScope ? "true" : "false");
  const r = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
},
```

(verificar se `API_BASE` já existe ou usar a constante equivalente)

- [ ] **Step 3: Compilar**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend
npm run build
```

Expected: build limpo.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app/front): tipos e cliente do POST /api/upload"
```

### Task 3.3: Frontend — `UploadView` com drag-and-drop

**Files:**
- Create: `egps_analysis/app/frontend/src/components/UploadView.tsx`
- Modify: `egps_analysis/app/frontend/src/App.tsx`

- [ ] **Step 1: Componente**

Create `egps_analysis/app/frontend/src/components/UploadView.tsx`:

```typescript
import { useState, type ChangeEvent, type DragEvent } from "react";
import { api } from "../api";
import type { UploadItem } from "../types";

const AREAS = ["Banco Relacional", "Cobranças", "Finanças", "Riscos", "TI", "Cartões"];

function inferArea(name: string): string {
  const lower = name.toLowerCase();
  for (const a of AREAS) {
    if (lower.includes(a.toLowerCase().replace(/\s+/g, "_"))) return a;
  }
  return "";
}

export function UploadView() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [drag, setDrag] = useState(false);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const next: UploadItem[] = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      if (!f.name.toLowerCase().endsWith(".egp")) continue;
      next.push({
        file: f,
        area: inferArea(f.name),
        includeInScope: false,
        status: "pending",
      });
    }
    setItems((prev) => [...prev, ...next]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    addFiles(e.dataTransfer.files);
  };

  const updateItem = (idx: number, patch: Partial<UploadItem>) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  const sendAll = async () => {
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.status !== "pending") continue;
      if (!it.area) {
        updateItem(i, { status: "error", error: "Selecione a área" });
        continue;
      }
      updateItem(i, { status: "uploading" });
      try {
        const r = await api.upload(it.file, it.area, it.includeInScope);
        updateItem(i, { status: "done", result: r });
      } catch (e) {
        updateItem(i, { status: "error", error: String(e) });
      }
    }
  };

  const allDone = items.length > 0 && items.every((it) => it.status === "done");

  return (
    <div className="upload-view">
      <h2>Upload de EGP</h2>
      <p className="hint">
        Cada arquivo .egp dispara o pipeline automático em alguns minutos. Se o
        conteúdo for idêntico ao último processado, o upload é silencioso (no-op).
      </p>

      <div
        className={"dropzone" + (drag ? " drag" : "")}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <p>Arraste arquivos .egp aqui ou</p>
        <input
          type="file"
          multiple
          accept=".egp"
          onChange={(e: ChangeEvent<HTMLInputElement>) => addFiles(e.target.files)}
        />
      </div>

      {items.length > 0 && (
        <table className="upload-table">
          <thead>
            <tr>
              <th>Arquivo</th>
              <th>Área</th>
              <th>Escopo Indicium</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i} className={`row-${it.status}`}>
                <td>{it.file.name}</td>
                <td>
                  <select
                    value={it.area}
                    disabled={it.status !== "pending"}
                    onChange={(e) => updateItem(i, { area: e.target.value })}
                  >
                    <option value="">— escolher —</option>
                    {AREAS.map((a) => (
                      <option key={a} value={a}>{a}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={it.includeInScope}
                    disabled={it.status !== "pending"}
                    onChange={(e) => updateItem(i, { includeInScope: e.target.checked })}
                  />
                </td>
                <td>
                  {it.status === "pending" && "—"}
                  {it.status === "uploading" && "enviando…"}
                  {it.status === "done" && it.result?.status === "noop" && "sem mudança (hash igual)"}
                  {it.status === "done" && it.result?.status === "uploaded" && "✓ enviado"}
                  {it.status === "error" && <span className="err">✗ {it.error}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {items.length > 0 && !allDone && (
        <button className="primary" onClick={sendAll}>Enviar todos</button>
      )}
      {allDone && (
        <p className="success">Tudo enviado. O pipeline vai processar nos próximos minutos.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Tab no App.tsx**

Edit `egps_analysis/app/frontend/src/App.tsx`. Adicionar import:

```typescript
import { UploadView } from "./components/UploadView";
```

Estender o tipo `View`:

```typescript
type View = "resumo" | "monitor" | "egp" | "readiness" | "waves" | "lineage" | "history" | "upload";
```

Adicionar à array `TABS` (final, mas antes de "history"):

```typescript
{ id: "upload", label: "Upload", slug: "upload" },
```

No render do conteúdo da view (procurar pela função/switch que escolhe o componente), adicionar:

```typescript
{view === "upload" && <UploadView />}
```

- [ ] **Step 3: Build + smoke visual**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend
npm run build
```

Expected: build sem erro.

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app
../venv/bin/python backend/main.py &
sleep 3
# abrir browser em http://localhost:8000 e clicar na aba Upload
```

Validar visualmente: tab "Upload" aparece, dropzone funcional, arrastar EGP popula a tabela, dropdown de área presente.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/components/UploadView.tsx \
        egps_analysis/app/frontend/src/App.tsx
git commit -m "feat(app/front): aba Upload (drag-and-drop + área + escopo)"
```

---

## Phase 4 — Diff + Histórico de runs no app

### Task 4.1: Backend — `GET /api/run-history`

**Files:**
- Modify: `egps_analysis/app/backend/main.py`

- [ ] **Step 1: Adicionar endpoints**

Em `egps_analysis/app/backend/main.py`, após o endpoint `/api/upload`:

```python
T_RUNS = f"{FQ}.sas_pipeline_runs"


@app.get("/api/run-history")
def run_history(limit: int = 50):
    limit = max(1, min(200, limit))
    rows = run_sql(
        f"SELECT run_id, triggered_by, started_at, finished_at, duration_s, "
        f"status, error, egps_total, egps_added, egps_removed, "
        f"inputs_added, inputs_removed, inputs_unchanged "
        f"FROM {T_RUNS} ORDER BY started_at DESC LIMIT {limit}"
    )
    return {"rows": rows or []}


@app.get("/api/run-history/{run_id}")
def run_detail(run_id: str):
    rows = run_sql(
        f"SELECT egp_key, area, status, error, extracted_at "
        f"FROM {T_MANIFEST} WHERE run_id = {sql_lit(run_id)} "
        f"ORDER BY area, egp_key"
    )
    return {"run_id": run_id, "egps": rows or []}


@app.get("/api/last-run-status")
def last_run_status():
    rows = run_sql(
        f"SELECT run_id, status, started_at, finished_at, error "
        f"FROM {T_RUNS} ORDER BY started_at DESC LIMIT 1"
    )
    return rows[0] if rows else {"status": None}
```

- [ ] **Step 2: Smoke**

```bash
curl -s http://localhost:8000/api/run-history?limit=5 | python -m json.tool
curl -s http://localhost:8000/api/last-run-status | python -m json.tool
```

Expected: JSON com pelo menos a linha da run da Task 1.10.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app/back): /api/run-history e /api/last-run-status"
```

### Task 4.2: Frontend — tipos + cliente para runs

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts`
- Modify: `egps_analysis/app/frontend/src/api.ts`

- [ ] **Step 1: Tipos**

Append em `types.ts`:

```typescript
export type RunHistoryRow = {
  run_id: string;
  triggered_by: string;
  started_at: string;
  finished_at: string | null;
  duration_s: number | null;
  status: "SUCCESS" | "FAILED" | "RUNNING";
  error: string | null;
  egps_total: number | null;
  egps_added: number | null;
  egps_removed: number | null;
  inputs_added: number | null;
  inputs_removed: number | null;
  inputs_unchanged: number | null;
};

export type RunDetail = {
  run_id: string;
  egps: { egp_key: string; area: string; status: string; error: string | null; extracted_at: string }[];
};

export type LastRunStatus = {
  run_id?: string;
  status: "SUCCESS" | "FAILED" | "RUNNING" | null;
  started_at?: string;
  finished_at?: string | null;
  error?: string | null;
};
```

- [ ] **Step 2: Cliente**

Append em `api.ts`:

```typescript
runHistory: async (limit = 50): Promise<{ rows: RunHistoryRow[] }> => {
  const r = await fetch(`${API_BASE}/run-history?limit=${limit}`);
  return r.json();
},

runDetail: async (runId: string): Promise<RunDetail> => {
  const r = await fetch(`${API_BASE}/run-history/${encodeURIComponent(runId)}`);
  return r.json();
},

lastRunStatus: async (): Promise<LastRunStatus> => {
  const r = await fetch(`${API_BASE}/last-run-status`);
  return r.json();
},
```

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app/front): tipos e cliente do run-history"
```

### Task 4.3: Frontend — `RunHistoryView` + sub-aba na History

**Files:**
- Create: `egps_analysis/app/frontend/src/components/RunHistoryView.tsx`
- Modify: `egps_analysis/app/frontend/src/components/HistoryView.tsx`

- [ ] **Step 1: Componente**

Create `egps_analysis/app/frontend/src/components/RunHistoryView.tsx`:

```typescript
import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunHistoryRow, RunDetail } from "../types";

function fmtDur(s: number | null): string {
  if (!s) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  return `${m}m ${r}s`;
}

export function RunHistoryView() {
  const [rows, setRows] = useState<RunHistoryRow[]>([]);
  const [open, setOpen] = useState<Record<string, RunDetail | null>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setBusy(true);
    api.runHistory(50).then((r) => setRows(r.rows)).finally(() => setBusy(false));
  }, []);

  const toggle = async (runId: string) => {
    if (open[runId]) {
      setOpen((p) => ({ ...p, [runId]: null }));
      return;
    }
    const d = await api.runDetail(runId);
    setOpen((p) => ({ ...p, [runId]: d }));
  };

  if (busy) return <div className="loading">carregando runs…</div>;
  if (!rows.length) return <div className="empty">Nenhum run registrado.</div>;

  return (
    <div className="run-history">
      {rows.map((r) => (
        <div key={r.run_id} className={`run-card status-${r.status.toLowerCase()}`}>
          <div className="run-head" onClick={() => toggle(r.run_id)}>
            <span className="run-status">{r.status}</span>
            <span className="run-when">{r.started_at}</span>
            <span className="run-dur">{fmtDur(r.duration_s)}</span>
            <span className="run-summary">
              Δinputs +{r.inputs_added ?? 0} / -{r.inputs_removed ?? 0}
              {" · "}
              ΔEGPs +{r.egps_added ?? 0} / -{r.egps_removed ?? 0}
            </span>
            <span className="run-trigger">{r.triggered_by}</span>
          </div>
          {open[r.run_id] && (
            <div className="run-detail">
              {open[r.run_id]!.egps.map((e) => (
                <div key={e.egp_key} className={`egp-row egp-${e.status.toLowerCase()}`}>
                  <span className="egp-key">{e.egp_key}</span>
                  <span className="egp-area">{e.area}</span>
                  <span className="egp-status">{e.status}</span>
                  {e.error && <span className="egp-err">{e.error.slice(0, 120)}</span>}
                </div>
              ))}
            </div>
          )}
          {r.error && r.status === "FAILED" && (
            <div className="run-error">{r.error}</div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Renomear `HistoryView.tsx` → `EditAuditView.tsx`**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend/src/components
git mv HistoryView.tsx EditAuditView.tsx
```

- [ ] **Step 3: Renomear o export no arquivo movido**

No arquivo `EditAuditView.tsx`, trocar a única linha:

```typescript
export function HistoryView() {
```

por:

```typescript
export function EditAuditView() {
```

- [ ] **Step 4: Criar nova `HistoryView.tsx` com sub-tabs**

Create `egps_analysis/app/frontend/src/components/HistoryView.tsx`:

```typescript
import { useState } from "react";
import { EditAuditView } from "./EditAuditView";
import { RunHistoryView } from "./RunHistoryView";

type Sub = "edits" | "runs";

export function HistoryView() {
  const [sub, setSub] = useState<Sub>("runs");
  return (
    <div className="history">
      <div className="sub-tabs">
        <button className={sub === "runs" ? "active" : ""} onClick={() => setSub("runs")}>
          Runs do pipeline
        </button>
        <button className={sub === "edits" ? "active" : ""} onClick={() => setSub("edits")}>
          Edições humanas
        </button>
      </div>
      {sub === "runs" && <RunHistoryView />}
      {sub === "edits" && <EditAuditView />}
    </div>
  );
}
```

- [ ] **Step 5: Build + smoke**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend
npm run build
```

Expected: build limpo.

Validar visualmente que a aba Histórico mostra 2 sub-tabs: "Runs do pipeline" (default) e "Edições humanas".

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/components/
git commit -m "feat(app/front): aba Histórico com sub-tabs (runs + edições)"
```

---

## Phase 5 — Banner de falha + ativação do GCP quando SA chegar

### Task 5.1: Banner de "último run falhou"

**Files:**
- Modify: `egps_analysis/app/frontend/src/App.tsx`

- [ ] **Step 1: Importar e estado**

No `App.tsx`, adicionar imports:

```typescript
import { useEffect } from "react";
import type { LastRunStatus } from "./types";
```

Dentro do componente App, adicionar estado:

```typescript
const [lastRun, setLastRun] = useState<LastRunStatus | null>(null);

useEffect(() => {
  api.lastRunStatus().then((s) => setLastRun(s));
  const id = setInterval(() => api.lastRunStatus().then(setLastRun), 60_000);
  return () => clearInterval(id);
}, []);
```

No JSX, antes do `<nav>` ou similar:

```typescript
{lastRun?.status === "FAILED" && (
  <div className="failure-banner">
    ⚠ Último run do pipeline falhou ({lastRun.started_at}). Veja a aba{" "}
    <a href="#" onClick={(e) => { e.preventDefault(); setView("history"); }}>
      Histórico
    </a>{" "}
    para detalhes.
  </div>
)}
```

- [ ] **Step 2: CSS mínimo**

Anexar em `egps_analysis/app/frontend/src/styles.css`:

```css
.failure-banner {
  background: #fee;
  color: #900;
  padding: 8px 12px;
  border-bottom: 1px solid #c00;
  font-size: 13px;
}
```

- [ ] **Step 3: Build**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend
npm run build
```

Expected: limpo. Banner aparece no topo do app quando o último run for FAILED.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/App.tsx \
        egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app/front): banner de falha do último run"
```

### Task 5.2: Deploy do app atualizado

**Files:** —

- [ ] **Step 1: Rebuild do front e deploy**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app
npm --prefix frontend run build
WSPATH="/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas"
databricks sync . "$WSPATH"
databricks apps deploy monitoramento-sas --source-code-path "$WSPATH"
```

Expected: deploy OK. App live em `https://monitoramento-sas-4394921022945130.aws.databricksapps.com`.

- [ ] **Step 2: Smoke do deploy**

Abrir o app no browser. Verificar:
1. Aba Upload aparece e funciona (subir 1 EGP de teste).
2. Aba Histórico mostra 2 sub-tabs e listas runs.
3. Banner aparece se algum run foi marcado FAILED.

### Task 5.3: Quando SA chegar — ativar `mode=fetch` no Chameleon

**Files:**
- Modify: `egps_analysis/databricks_bundle/resources/workflow_refresh.yml`

> **Pré-requisito:** receber o JSON da SA + criar secret scope.

- [ ] **Step 1: Criar secret scope**

```bash
databricks secrets create-scope monitoramento-sas
databricks secrets put-secret monitoramento-sas gcp_chameleon_sa_json \
  --string-value "$(cat ~/chameleon-reader-sa.json)"   # ajustar caminho do arquivo recebido
```

Expected: secret listado em `databricks secrets list-secrets monitoramento-sas`.

- [ ] **Step 2: Conceder acesso ao Job**

```bash
databricks secrets put-acl monitoramento-sas \
  <SP_DO_JOB> \
  --permission READ
```

- [ ] **Step 3: Editar workflow YAML**

Em `workflow_refresh.yml`, na task `chameleon`, mudar:

```yaml
        - task_key: chameleon
          depends_on:
            - task_key: extract
          job_cluster_key: pipeline_cluster
          spark_python_task:
            python_file: ../../egps_analysis/pipeline/job_chameleon.py
            parameters:
              - --volume-base
              - ${var.volume_base}
              - --mode
              - fetch
              - --job-project
              - bv-sadn-dtm
          libraries:
            - pypi:
                package: google-cloud-bigquery
```

O próprio `job_chameleon.py` (modo `fetch`) busca o secret do scope, escreve em `/tmp/chameleon_sa.json` e popula `GOOGLE_APPLICATION_CREDENTIALS`. Editar `egps_analysis/pipeline/job_chameleon.py`, no início do `main()` quando `mode == "fetch"`:

```python
if args.mode == "fetch":
    # Materializa a SA do secret scope num arquivo temporário
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        scope = os.environ.get("GCP_SECRET_SCOPE", "monitoramento-sas")
        key = os.environ.get("GCP_SECRET_KEY", "gcp_chameleon_sa_json")
        sa_json = w.secrets.get_secret(scope, key).value
        import base64
        sa_path = "/tmp/chameleon_sa.json"
        with open(sa_path, "w") as f:
            f.write(base64.b64decode(sa_json).decode("utf-8") if not sa_json.startswith("{") else sa_json)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
    except Exception as e:
        print(f"[chameleon] FATAL: secret SA não acessível: {e}", file=sys.stderr)
        sys.exit(2)
```

- [ ] **Step 4: Redeploy + run manual**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/databricks_bundle
databricks bundle deploy --target dev
databricks bundle run monitoramento_sas_refresh --target dev
```

Expected: task `chameleon` faz refresh do CSV no Volume; resto do pipeline procede.

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/databricks_bundle/resources/workflow_refresh.yml \
        egps_analysis/pipeline/job_chameleon.py
git commit -m "feat(workflow): chameleon mode=fetch com SA via secret scope"
```

---

## Verificações finais

### Task F.1: Rodar suite de testes completa

- [ ] **Step 1**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
source venv/bin/activate
pytest tests/ -v
```

Expected: todos os testes verdes.

### Task F.2: Documentação

**Files:**
- Modify: `egps_analysis/app/README.md`
- Modify: `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`

- [ ] **Step 1: Adicionar seção "Refresh automático" no README do app**

Append em `egps_analysis/app/README.md`:

```markdown
## Refresh automático (Workflow)

Desde 2026-06, o app é alimentado por um Databricks Workflow
(`monitoramento-sas-refresh`) que dispara automaticamente quando um `.egp`
chega em `/Volumes/client_journey/monitoramento_sas/egp_landing/<area>/`.

Pontos de entrada do upload:
- **Aba Upload do app**: drag-and-drop + escolha de área + checkbox de escopo Indicium.
- **CLI**: `databricks fs cp arquivo.egp dbfs:/Volumes/.../egp_landing/<area>/`.

Histórico de runs (status, duração, Δ inputs/EGPs) na aba **Histórico → Runs do pipeline**.

Para refresh manual: `databricks bundle run monitoramento_sas_refresh --target dev`
(de dentro de `egps_analysis/databricks_bundle/`).
```

- [ ] **Step 2: Atualizar referência ao pipeline em `docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`**

Adicionar nota no topo apontando para o Workflow Databricks como execução canônica em produção; o fluxo local segue válido pra desenvolvimento.

- [ ] **Step 3: Commit**

```bash
git add egps_analysis/app/README.md egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md
git commit -m "docs: registra Workflow Databricks como fluxo de produção"
```

### Task F.3: Abrir PR

- [ ] **Step 1: Push da branch**

```bash
git push -u origin feat/auto-load-pipeline
```

- [ ] **Step 2: Abrir PR para `main`**

Use a skill `indimesh-airflow:create-pull-request` ou:

```bash
# Bitbucket Cloud API — ajustar workspace e repo:
# preferir abrir pelo navegador, conferindo o diff
```

Expected: PR aberto para `main` (ou `import/project-sas` dependendo do plano de branches do user) com title `feat: pipeline automatizado de carregamento de EGPs`.

---

## Notas operacionais (post-implementação)

1. **Falha de extract num EGP**: o Workflow marca o run como FAILED por causa do `sys.exit(1)` em `job_extract.py`. Pra tolerar EGPs ruins, mudar pra `sys.exit(0)` quando `failed > 0` mas `processed > 0` (com flag CLI explícita).
2. **Limite de tamanho do upload**: 50MB é o cap no backend. Subir além disso quebra o `await file.read()` em memória — refatorar pra streaming se necessário.
3. **Escopo Indicium via checkbox**: o `include_in_scope=true` hoje é só log no backend. Pra valer no próximo run, é preciso atualizar o `indi_231_vs_extracao_06.csv` ou marcar diretamente `sas_lineage_nodes.escopo_indi=true` após o publish. Trabalho não coberto neste plano — deixar como follow-up.
4. **Custo do Workflow**: serverless compute é cobrado por minuto. Cada run extract→publish leva ~3-5min com 229 EGPs. Esperado: ~3-10 runs/dia, custo trivial. Se passar de 30 runs/dia, considerar batchar com debounce via `min_time_between_triggers_seconds`.
5. **GCP via SA**: se o JSON da SA tiver chave privada vazada por engano em log/stderr, **revogar imediatamente** no console GCP. O log do `gcp_bigquery_table_data_export.py` imprime SQL inteira em stderr (flag `--print-sql`), mas não a credencial. Validar antes de rodar.

