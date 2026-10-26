# converter — Conversão de EGP (SAS EG) → dbt BigQuery / Databricks

Este projeto implementa um pipeline para migrar projetos `.egp` (SAS Enterprise Guide) para:

- **dbt BigQuery (SQL)** quando `TARGET_ARCH = DBT_BQ`
- **dbt Databricks (dbt Python Models)** quando `TARGET_ARCH = DATABRICKS`

O fluxo combina **scripts determinísticos** (extração, geração de spec, gates e batch) com **micro‑papéis** do agente (prompts em `.cursor/prompts/`) para draft, governança e auditoria.

## Guardrails (agente e automação)

**Em hipótese nenhuma** o agente deve executar neste fluxo: **`dbt build`**, **`git commit`**, **`git push`**.

- Regra Cursor: [`.cursor/rules/04_pipeline_operational_guardrails.mdc`](.cursor/rules/04_pipeline_operational_guardrails.mdc).
- Roteiro completo: [`.cursor/skills/orchestrator/SKILL.md`](.cursor/skills/orchestrator/SKILL.md) (secção «Guardrails operacionais obrigatórios»).
- **Permitido:** `git clone` / `fetch` / `checkout` / `pull` apenas via **`python -m scripts.bootstrap_egp_catalog ensure-repo`** (sem commit/push). Opcionalmente **`dbt parse`** no clone após validação humana — **não** `dbt build`.

## Pré-batch (lote)

Antes de **`python -m scripts.batch_pipeline extract`** / conversão em série:

1. **`registry/egp_catalog.yaml`:** deve existir. Se ainda não existir, copie [`registry/egp_catalog.example.yaml`](registry/egp_catalog.example.yaml) para `egp_catalog.yaml` e ajuste `defaults` — **não** apague o catálogo inteiro em cada lote (preserva `staging_ref_map` e notas).
2. **Novos `.egp` sem entrada:** `python -m scripts.bootstrap_egp_catalog scan [--area <slug>] [--componente …] [--area-map registry/area_componente_dbt.yaml]`. Com ficheiros em **`received_egps/<slug>/*.egp`**, o `scan` infere `area` e grava `egp_file` relativo (ex.: `cobranca/MeuProj.egp`); com `.egp` na **raiz** de `--egp-dir`, `--area` é obrigatório. O `scan` **só acrescenta** chaves novas; entradas existentes são ignoradas (`--update-area` altera `area`/componente só quando indicado).
3. **Lista do lote:** `registry/egp_keys_batch.txt` (modelo: `registry/egp_keys_batch.example.txt`).
4. **Clone do componente (opcional):** com `git_url` em [`registry/area_componente_dbt.yaml`](registry/area_componente_dbt.yaml), `python -m scripts.bootstrap_egp_catalog ensure-repo --componente <nome>` ou `--area <slug>`.

## Mapa área → componente dbt (`registry/area_componente_dbt.yaml`)

- Modelo: [`registry/area_componente_dbt.example.yaml`](registry/area_componente_dbt.example.yaml).
- Secção **`areas`:** slug igual ao campo `area` do catálogo → nome da pasta `componente_dbt`.
- Secção **`components`:** metadados por pasta (`git_url`, `git_ref`). Com `git_url` vazio, `ensure-repo` só verifica se a pasta existe e tem `dbt_project.yml` (útil para cópias locais em `converted_egps/`).
- O `scan` / `add` podem **omitir `--componente`** quando o slug `--area` existir em `areas`.

## Visão rápida (pastas e artefatos)

- **Entrada**
  - `received_egps/<AREA>/*.egp` (recomendado) ou `received_egps/*.egp` na raiz
- **Extração**
  - `text_egps/<egp_key>.txt` (cabeçalho `START_METADATA/END_METADATA` + código SAS; campo **`BUSINESS_AREA`** alinhado com a pasta `AREA` ou com o catálogo)
  - **Área / catálogo:** [`scripts/egps_extractor.py`](scripts/egps_extractor.py) com um ficheiro `.egp` usa a pasta-mãe como área (excepto ficheiros directamente sob `received_egps/`); override com **`--area <slug>`** ou variável **`EGP_BUSINESS_AREA`** (prioridade: CLI > env > inferência > prompt em TTY; fora de TTY falha se faltar área). O **`python -m scripts.batch_pipeline extract`** preenche o cabeçalho com o campo `area` do catálogo ou infere a partir do caminho sob `received_dir`; se `area` no catálogo estava vazio e foi inferido, **grava** `area` no `egp_catalog.yaml`.
  - **Referência / diff:** [`scripts/egps_extractor_v10.py`](scripts/egps_extractor_v10.py) — cópia legada com saída por defeito em `text_egps_v10/`; o extrator **canónico** é [`scripts/egps_extractor.py`](scripts/egps_extractor.py) (já com as mesmas políticas v10 por defeito: sem órfãos XML nem ingestão sintética a partir de `METADATA/LOG` / `result.log`, salvo `--include-xml-orphans` e `--include-metadata-log`). O lote usa **`python -m scripts.batch_pipeline`**, que chama o módulo canónico.
- **Catálogo (fonte de verdade operacional)**
  - `registry/egp_catalog.yaml`
  - `registry/area_componente_dbt.yaml` (modelo: `registry/area_componente_dbt.example.yaml`)
  - `registry/area_cd_governanca.yaml` (modelo: `registry/area_cd_governanca.example.yaml`)
- **Contrato de migração**
  - `draft_models/<egp_key>/MIGRATION_SPEC.md` — código em `scripts/generate_migration_spec.py`; gerar com **`python -m scripts.generate_migration_spec "<egp_key>"`**
- **Draft (PASSO 2) + gate mecânico (pós‑draft)**
  - **Modo padrão (flow-only):** draft em `draft_models/<egp_key>/models/NN_*.sql` (flat, numerado) e gate em **`python -m scripts.draft_flow_gate "<egp_key>" --write-report`** (gera `DRAFT_FLOW_GATE_REPORT.md`). Também exige o artefacto IA `AI_DRAFT_FLOW_VALIDATION_REPORT.md` com `**Overall:** PASS` e um bloco por ficheiro.
    - **Coverage gate (flow-only):** quando o cabeçalho do `text_egps/<egp_key>.txt` declarar **ambos** `PERMANENT OUTPUTS (Target Marts)` e `EXPORTED FILES (Artifacts)` (não-`(none)`), o `AI_DRAFT_FLOW_VALIDATION_REPORT.md` deve conter `## Coverage` registrando **Permanent outputs** e **Exported files**.
  - **Modo legado (3 camadas no draft):** gate em **`python -m scripts.draft_gate "<egp_key>"`** (`scripts/draft_gate.py` + `scripts/draft_layer_guard.py`: exige `models/staging/`, `intermediate/` e `marts/` no draft com `materialized='…'` literal por camada quando `TARGET_ARCH` é **DBT_BQ** ou **DATABRICKS**; se `MIGRATION_SPEC.md` tiver **`draft_manifest.models`** não vazio no §9, valida que cada `layer`/`stem` existe como `.sql`/`.py` em `draft_models/.../models/`). Opcional: `DRAFT_GATE_REPORT.md` com **`--write-report`**. Em lote: **`python -m scripts.batch_pipeline draft-gate`**
- **Sandbox por EGP (PASSO 3A)** — espelho antes do clone
  - **Novo layout (por run):** `converted_egps/<YYYY-MM-DD>_<git-short>_dbt|databricks/<egp_key>/` (`git rev-parse --short HEAD` na raiz `converter/`, data local).
  - **Legado (ainda suportado):** `converted_egps/dbt|databricks/<egp_key>/`. Resolução automática: `scripts/sandbox_layout.py` (`find_converted_sandbox`; legado tem prioridade se existir).
- **Conversão final (integração no clone dbt)**
  - `converted_egps/<componente_dbt>/models/workspace/corp_cobranca/migracao_sas/<EGP_SLUG>/...`
- **Batch / rastreabilidade**
  - `registry/batch_manifest.json` (estado por `egp_key`)
  - `registry/BATCH_AUDIT.md` (tabela agregada)

## Pré‑requisitos

- Python 3
- Dependências:

```bash
pip install -r requirements.txt
```

## Configuração (catálogo + lista do lote)

1) Coloque os `.egp` em `received_egps/` (**pasta local; crie se não existir**)

2) Cadastre cada projeto no `registry/egp_catalog.yaml` (campos típicos por entrada):
- `egp_key`: chave do projeto (normalmente o nome do arquivo sem `.egp`)
- `egp_file`: nome real do arquivo `.egp` (quando diferir do `egp_key`)
- `area`: ex. `cobranca`
- `componente_dbt`: ex. `dbt-srcg-anlt-plataforma`
- `pii_reference_interno_strict`: opcional (`true`/`false`) — por entrada ou em `defaults`; quando ativo (ou com CLI `--reference-interno-strict`), o guard PII reforça tipos em `STRICT_REFERENCE_ENTRY_IDS` (ver `pii_sensitive_yml_guard.py`). Por defeito, colunas sensíveis já exigem `PII_INTERNO_*` inferido de `models/**/04_marts/**/*.yml` (fallback documentado em `pii_reference.py`); `PII_DADOS_CONFIDENCIAIS` sozinho não basta.
- `target_arch_override`: opcional (`DBT_BQ` ou `DATABRICKS`)
- **`defaults.staging_mode`:** por defeito **`reuse_existing`** — reutilizar `stg_*` já existentes no **mesmo** repositório do `componente_dbt`. Use `generate_new` na entrada (ou em `defaults`) só quando faltar staging no componente; documente em `notes`.
- **`staging_ref_map`:** quando em `reuse_existing` / `hybrid`, mapear fontes para `ref('stg_...')` existentes (o `draft_gate` valida presença dos `ref`).

3) Para lote, liste os alvos em `registry/egp_keys_batch.txt` (um `egp_key` por linha; linhas `#` são ignoradas).

## Configuração por usuário (perfil local, ignorado no git)

Para evitar preencher manualmente labels de governança, alguns scripts usam um **perfil local** (não versionado):

- **Arquivo:** `registry/user_profile.local.yaml` *(recomendado; não commitar)*
- **Uso principal:** o script **`python -m scripts.apply_governance_config "<egp_key>"`** lê o campo `engineer:` para definir `nm_engenheiro_responsavel_pela_transformacao` quando não for passado via `--engineer` ou variável `CONVERTER_ENGINEER`.

Exemplo mínimo:

```yaml
engineer: int_seu_usuario
```

Notas:
- `nm_grupo_de_acesso` é inferido a partir do path do componente (`models/workspace/<workspace_subdir>/...`) ou do `DBT_CLONE_DEST` no `MIGRATION_SPEC.md`.
- Se você não criar esse ficheiro, o pipeline usa fallback (ex.: `int_unknown`) ou o valor configurado por ambiente/CLI.

### Bootstrap do catálogo (opcional)

Ao criar entradas com `bootstrap_egp_catalog.py`:

```bash
python -m scripts.bootstrap_egp_catalog scan  \
  --defaults-staging-mode reuse_existing --entry-staging-mode reuse_existing
```

Com **`registry/area_componente_dbt.yaml`** preenchido (`areas.cobranca`, etc.), pode omitir `--componente`:

```bash
python -m scripts.bootstrap_egp_catalog scan --area cobranca \
  --defaults-staging-mode reuse_existing --entry-staging-mode reuse_existing
```

Com EGPs já organizados em **`received_egps/<AREA>/*.egp`**, o `scan` pode omitir **`--area`** (a área infere-se por pasta; `egp_file` no catálogo fica relativo, ex.: `cobranca/MeuProj.egp`):

```bash
python -m scripts.bootstrap_egp_catalog scan \
  --defaults-staging-mode reuse_existing --entry-staging-mode reuse_existing
```

**Clone / atualização do repositório do componente** (só `clone`/`fetch`/`checkout`/`pull`; nunca `commit`/`push`):

```bash
python -m scripts.bootstrap_egp_catalog ensure-repo --componente dbt-srcg-anlt-plataforma
# ou, a partir do slug de área no mapa:
python -m scripts.bootstrap_egp_catalog ensure-repo --area cobranca
# ou, a partir de uma entrada do catálogo:
python -m scripts.bootstrap_egp_catalog ensure-repo --egp-key "Pagamentos_Digital" -c registry/egp_catalog.yaml
```

- **`--defaults-staging-mode`:** grava `catalog.defaults.staging_mode` antes de processar.
- **`--entry-staging-mode`:** em entradas **novas** (`scan` / `import-csv`) ou na entrada em `add`, define `staging_mode`.

## Execução (modo lote — determinístico)

Execute **a partir da raiz** do projeto (`converter/`).

### 1) Extração em lote → `text_egps/` + manifest

```bash
python -m scripts.batch_pipeline extract --batch-file registry/egp_keys_batch.txt --resume
```

### 2) Checagens leves em disco + CSV (opcional)

```bash
python -m scripts.batch_pipeline checks --batch-file registry/egp_keys_batch.txt --write-csv
```

Com **`--strict`**, o comando falha (exit 1) também quando, com **`TARGET_ARCH: DBT_BQ`** ou **`DATABRICKS`** no `.txt` e ficheiros `.sql`/`.py` no draft, **`batch_checks.draft_three_layers_ok`** é falso (falta alguma das pastas `staging/` / `intermediate/` / `marts/` ou falta `materialized='…'` literal permitido por camada — ver `draft_layer_guard.py`); quando, com **`TARGET_ARCH: DBT_BQ`**, o **draft** tem modelos em `intermediate/` ou `marts/` **sem** `stem.yml` irmão (`batch_checks.draft_yml_pairing_ok`); quando existem modelos na pasta convertida **sem** `stem.yml` irmão (`yml_pairing_ok` — paridade pós-governança; ver `model_yml_guard.py`); em **DBT_BQ** quando colunas sensíveis nos `stem.yml` não têm `policy_tags` conforme `registry/sensitive_data_types.yaml` (ver `pii_sensitive_yml_guard.py`); e em **DBT_BQ** quando os `stem.yml` existentes **não cumprem documentação mínima** (`columns` não vazio, `meta.cron`, descrições — ver `yml_documentation_guard.py`; desligar com **`--skip-yml-doc`**).

No **modo flow-only** (layout `draft_models/<egp_key>/models/NN_*.sql`), com `--strict` o comando também falha se:

- `batch_checks.draft_flow_gate_ok` não estiver OK (ver `python -m scripts.draft_flow_gate "<egp_key>" --write-report`)
- `batch_checks.flow_coverage_ok` não estiver OK quando a regra de coverage for aplicável (ver secção “Coverage gate (flow-only)” acima)

**Não promover** o EGP ao PASSO 3 / merge sem **`python -m scripts.draft_gate`** (ou equivalente no batch) verde e, em lote, sem **`python -m scripts.batch_pipeline checks … --strict`** quando o manifesto indicar `draft_three_layers_ok`, `draft_yml_pairing_ok` e `yml_pairing_ok` conforme aplicável.

Scripts auxiliares (paridade no draft): **`python -m scripts.check_draft_yml_pairing --draft-root draft_models --egp-key "<egp_key>"`** (exit 1 se faltar irmão); **`python -m scripts.scaffold_int_mart_yml --draft-root draft_models --egp-key "<egp_key>"`** gera **stubs** mínimos — o `yml_documentation_guard` no sandbox ainda pode exigir enriquecimento (não usar stub como destino final).

Com **`pii_reference_interno_strict: true`** no catálogo (por entrada ou em `defaults`) **ou** com **`--reference-interno-strict`** no mesmo comando, o check PII aplica o modo estrito **adicional** para os `id` em `STRICT_REFERENCE_ENTRY_IDS`. Em qualquer caso, a lista permitida de `PII_INTERNO_*` vem primeiro de **`models/**/04_marts/**/*.yml`**, com fallback ao resto de `models/` exceto `migracao_sas` (campos `pii_reference_scope`, `pii_reference_04_marts_fallback` em `batch_checks`). **`PII_DADOS_CONFIDENCIAIS` sozinho não satisfaz** colunas sensíveis catalogadas. O manifest expõe `batch_checks.pii_reference_interno_strict_applied`.

### 3) Relatório agregado do lote (Markdown)

```bash
python -m scripts.batch_pipeline batch-audit --batch-file registry/egp_keys_batch.txt --refresh-checks --out registry/BATCH_AUDIT.md
```

### 4) Gate mecânico em lote (somente se houver `draft_models/` para os EGPs)

```bash
python -m scripts.batch_pipeline draft-gate --batch-file registry/egp_keys_batch.txt --write-report
# Exceção legado (não exigir stem.yml no draft para int/mart):
python -m scripts.batch_pipeline draft-gate --batch-file registry/egp_keys_batch.txt --skip-int-mart-yml-pairing
```

## Execução (modo lote — 1 EGP = 1 sessão do agente)

Para evitar “vazamento de contexto” entre EGPs, execute o lote como **uma execução do Cursor Agent por `egp_key`** (cada chamada cria um `session_id` novo; não usa `--resume/--continue`).

Pré‑requisitos:

- Cursor Agent CLI disponível no `PATH` (no Windows/Git Bash tipicamente `agent`; em outros ambientes pode ser `cursor-agent` ou `cursor agent`).
- Arquivo de lote: `registry/egp_keys_batch.txt`.

### Converter tudo (todos os `.egp` em `received_egps/`)

#### Opção 1 — Usando a skill (modo lote)

No chat, peça **“converter tudo”**. No modo lote, a skill segue a regra:

- Se **não existir** `registry/egp_keys_batch.txt`, gerar a lista automaticamente a partir de `received_egps/**/*.egp`:
  - `python -m scripts.write_egp_keys_batch_from_received --received-dir received_egps --out registry/egp_keys_batch.txt`
- Em seguida, executar o lote isolado (1 sessão por EGP) via runner.

Referência: [`.cursor/skills/orchestrator/SKILL.md`](.cursor/skills/orchestrator/SKILL.md).

#### Opção 2 — Via terminal (determinístico)

```bash
# 1) Gerar o batch file a partir de received_egps/**/*.egp
python -m scripts.write_egp_keys_batch_from_received --received-dir received_egps --out registry/egp_keys_batch.txt

# 2) Rodar 1 sessão do agente por EGP + imprimir resumo ao final
bash scripts/run_agent_batch_isolated.sh -b registry/egp_keys_batch.txt -w "$(pwd)"
```

#### Opção 3 — Via terminal (interativo, com prompts s/n)

Este wrapper faz pausas por etapa, **mostra os arquivos criados** para conferência e segue defaults seguros:

- **Default = S** (continua) na maioria das etapas
- **Default = N** no cleanup pós-run (`cleanup_registry`)

```bash
# a partir da raiz do repo converter/
bash scripts/run_batch_interactive.sh
```

Opções úteis:

```bash
# se os .egp estiverem na raiz de received_egps/, passe o slug (o script também pode pedir no prompt)
bash scripts/run_batch_interactive.sh --catalog-scan-area cobranca

# permitir colisões de egp_key (dedup por stem) ao gerar o batch
bash scripts/run_batch_interactive.sh --allow-collisions

# parar no primeiro EGP com falha no runner do agente
bash scripts/run_batch_interactive.sh --stop-on-fail
```

Notas:
- Com **`received_egps/<AREA>/*.egp`**, o scan do catálogo no script **não assume área** e varre todas as subpastas; **`--update-area`** só entra se confirmar nesse passo.
- Antes do agente, o script pode oferecer **`ensure-repo`** só para os `componente_dbt` das chaves do batch atual (quando falta `dbt_project.yml` sob `defaults.dbt_project_path`).
- Se existirem **dois `.egp` com o mesmo nome** em subpastas diferentes, o gerador falha por defeito (colisão de `egp_key`). Use `--allow-collisions` apenas se souber o que está fazendo (vai deduplicar por `stem`).

Executar:

```bash
# a partir da raiz do repo converter/
bash scripts/run_agent_per_egp.sh
```

Opções úteis:

```bash
# batch file diferente
bash scripts/run_agent_per_egp.sh -b registry/egp_keys_batch.txt

# parar no primeiro erro
bash scripts/run_agent_per_egp.sh --stop-on-fail
```

Logs:

- Um arquivo por EGP em `logs/agent_runs/<egp_key>.ndjson` (NDJSON, `stream-json`).
- Resumo agregado em `logs/agent_runs/SUMMARY.tsv` com exit code + paths de log.

### Qual a diferença entre `run_agent_per_egp.sh` e `run_agent_batch_isolated.sh`?

- **`scripts/run_agent_per_egp.sh`**: é o **runner base**. Lê um batch file e executa **uma chamada do Agent CLI por `egp_key`**, gravando `logs/agent_runs/<egp_key>.ndjson` e `logs/agent_runs/SUMMARY.tsv`.
- **`scripts/run_agent_batch_isolated.sh`**: é um **wrapper/atalho**. Ele chama o `run_agent_per_egp.sh` e, ao final, imprime um resumo legível a partir do `SUMMARY.tsv` (via `python -m scripts.summarize_agent_runs`).

## Execução (um EGP)

O roteiro completo (passos 1–6, modo lote, guardrails e política de retry) está em:
- `.cursor/skills/orchestrator/SKILL.md`

Atalhos determinísticos mais usados:

```bash
# Extração
python -m scripts.egps_extractor "received_egps/<arquivo>.egp"

# MIGRATION_SPEC
python -m scripts.generate_migration_spec "<egp_key>"

# Gate mecânico do draft (flow-only — padrão)
python -m scripts.draft_flow_gate "<egp_key>" --write-report

# Gate mecânico do draft
python -m scripts.draft_gate "<egp_key>"
# PII (PII_INTERNO_* a partir de 04_marts; ver README secção checks)
python -m scripts.draft_gate "<egp_key>" --reference-interno-strict
# Legacy / exceção: não validar documentação mínima dos stem.yml int/mart
python -m scripts.draft_gate "<egp_key>" --skip-yml-doc
# Exceção legado: não exigir stem.yml irmão no draft (int/mart)
python -m scripts.draft_gate "<egp_key>" --skip-int-mart-yml-pairing
```

## Como ler o `registry/batch_manifest.json`

O manifest agrega, por `egp_key`:

- `extract`: status + paths do `.egp` e do `.txt`
- `draft_gate`: status/erros/avisos quando `draft-gate` foi executado
- `batch_checks`: checagens locais (existência de txt/spec, convertido, auditoria, **`draft_yml_pairing_ok`** / amostras no **draft**, paridade int/mart ↔ `.yml` na saída convertida (`yml_pairing_ok`), `yml_documentation_ok`, PII em YAML, `pii_reference_interno_strict_applied`, etc.)
- `pipeline_steps`: progresso manual dos passos (1c–6), atualizável via `set-step`

**Auditoria (AGENTE 3):** estrutura do `AUDITORIA_*.md` (metadados `modo_lote`, secção **Pontos de alto risco**) está em `.cursor/rules/03_migration_auditor.mdc`. **Carimbo determinístico (lote):** **`python -m scripts.audit_batch_stamp --batch-file registry/egp_keys_batch.txt`** imprime na stdout o bloco de metadados + tabela de alto risco para colar após o título do relatório (`python -m scripts.audit_batch_stamp --help`).

Para registrar/atualizar progresso manual:

```bash
python -m scripts.batch_pipeline set-step --egp-key "<egp_key>" --step audit_5 --status ok --note "motivo/observação"
```

## Como ler o `registry/BATCH_AUDIT.md`

O `BATCH_AUDIT.md` é um resumo “uma linha por EGP” para fechamento de lote. Colunas principais:

- `extract`: ok/fail (extração)
- `draft_gate`: resultado do gate no manifest (quando aplicável) ou `na`
- `txt`, `spec`: presença dos artefatos
- `converted`: detecção de saída convertida no workspace
- `int_mart_yml`: KPI sobre a **saída convertida** — `na` se não houver modelos int/mart na árvore convertida; `sim` se cada `*.sql`/`.py` tem `stem.yml` irmão; `não` se faltar algum (detalhe em `batch_checks.int_mart_yml_missing_sample` no manifest). Para paridade **já no draft**, ver `draft_yml_pairing_ok` / `check_draft_*` no CSV do manifesto e a secção **KPI paridade YAML** em `BATCH_AUDIT.md`.
- `yml_doc`: `na` se não aplicável; `sim`/`não` conforme o campo `yml_documentation_ok` em `batch_checks` (qualidade mínima dos `stem.yml`; ver `yml_documentation_guard.py`)
- `auditoria`: caminho do `AUDITORIA_*.md` quando existir
- `pipeline`: resumo dos passos registrados em `pipeline_steps`

## Troubleshooting rápido

- **`extract` falha**: conferir se o `.egp` existe em `received_egps/` e se `egp_file` no catálogo está correto.
- **`txt = não`**: rode **`python -m scripts.batch_pipeline extract`** (lote) ou **`python -m scripts.egps_extractor`** com o caminho do `.egp` (single; preferir `received_egps/<AREA>/…` ou **`--area`** / **`EGP_BUSINESS_AREA`** na raiz de `received_egps/`).
- **`spec = não`**: rode **`python -m scripts.generate_migration_spec "<egp_key>"`**.
- **`draft_gate` não aparece**: só existe se você executar **`python -m scripts.draft_gate`** ou **`python -m scripts.batch_pipeline draft-gate`** (e **`--write-report`** gera `DRAFT_GATE_REPORT.md`).
- **`int_mart_yml = não`**: faltam `.yml` irmãos na **árvore convertida** — completar na governança (AGENTE 2) ou corrigir paths; ver `batch_checks` no manifest.
- **`draft_yml_pairing_ok` falso** (ou erros «Paridade stem.yml (draft)» no gate): faltam `stem.yml` no **draft** sob `draft_models/.../models/` — o AGENTE 1 deve criar um YAML por modelo int/mart (**DBT_BQ**) ou usar **`python -m scripts.scaffold_int_mart_yml`** / **`python -m scripts.batch_pipeline run … --scaffold-yml`** como ponto de partida, depois enriquecer.
- **`yml_doc = não` / `checks --strict` falha por documentação**: completar `stem.yml` (colunas com descrições, `meta.cron`, texto do modelo sem placeholders) ou usar **`--skip-yml-doc`** só como exceção transitória; ver `yml_documentation_errors` em `batch_checks`.

