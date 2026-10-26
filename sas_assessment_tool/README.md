# sas_assessment_tool

Ferramental de assessment e migração **SAS → stack moderna** do projeto BV. Monorepo de sub-projetos independentes que cobrem o ciclo completo: ingestão de logs → análise dbt → modelagem em grafo → inventário/priorização de EGPs → conversão automatizada EGP → dbt.

Cada sub-projeto tem seu próprio README, dependências e runtime — não assuma ambientes compartilhados.

## Setup de dados (obrigatório para `converter/` e `egps_analysis/`)

Os binários `.egp` do BV **não são versionados** neste repositório (o `.gitignore` bloqueia `*.egp` e `received_egps/`). Eles ficam num arquivo tar no Google Drive:

- **Arquivo:** `received_egps_20260612.tar` (~846MB, 982 EGPs organizados por área de negócio)
- **Link:** _(adicionar link do Drive aqui)_

Após clonar o repositório, baixe o tar e extraia na raiz do repo:

```bash
tar -xf received_egps_20260612.tar -C egps_analysis/
```

Isso restaura `egps_analysis/received_egps/<Área>/*.egp`. O tar também contém `_arquivo_rodas_egp_binarios/` (binários arquivados de Rodas), `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_NOVO.egp` e `log_files/Exemplo 1.egp`.

Credenciais (`.env`) também não são versionadas — copie os `.env.example`/`.example.*` de cada módulo e preencha.

## Sub-projetos

| Pasta | Papel | Documentação |
|---|---|---|
| [`ingestion/`](ingestion/) | Ingestão de logs SAS (`.log`), CSVs de usuários e tabelas modernizadas para o Databricks (Delta Lake, OAuth U2M). | [`ingestion/`](ingestion/) |
| [`dbt_sas_migration_assessment/`](dbt_sas_migration_assessment/) | Projeto dbt que transforma os logs ingeridos em camadas staging → trusted → marts → serving (dependências, linhagem, classificação). Roda em Databricks **ou** Snowflake (`DBT_PROFILE_TARGET`). | [`dbt_sas_migration_assessment/`](dbt_sas_migration_assessment/) |
| [`sas_neo4j_setup/`](sas_neo4j_setup/) | Converte export CSV de modelagem em scripts Cypher e carrega no Neo4j via Docker Compose. | [`sas_neo4j_setup/`](sas_neo4j_setup/) |
| [`converter/`](converter/) | Conversão automatizada de `.egp` → **modelos dbt** (SQL BigQuery ou Python Databricks) via pipeline determinístico + multi-agente (6 passos, gates, modo batch). | [`converter/README.md`](converter/README.md) · [`converter/.cursor/skills/orchestrator/SKILL.md`](converter/.cursor/skills/orchestrator/SKILL.md) |
| [`egps_analysis/`](egps_analysis/) | Análise de projetos `.egp`: inventário de I/O e relatórios CSV (01–06) para priorização de ingestão e migração. | [`egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`](egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md) |
| [`code_sas_to_py/`](code_sas_to_py/) | Notebook de referência (`PERF_AMIGAVEL_GCP.ipynb`) e config `.sqlfluff`. | — |

## egps_analysis/ — ordem de execução do pipeline

Executar a partir da pasta `egps_analysis/`. O `src/chameleon.csv` deve refletir as ingestões atuais no BigQuery, por isso o export GCP (passo 2) **deve rodar antes** do orquestrador (passo 3).

```bash
python egps_extractor.py                              # 1. .egp/.sas → .txt (metadados + inventário I/O)
python gcp_bigquery_table_data_export.py \
    --project … --dataset … --table … --format csv -o ./src/chameleon.csv   # 2. catálogo Chameleon
python orchestrator_inventory.py                      # 3. → 01_*.csv … 06_prontidao_tabela.csv
python validate_table_in_vs_repmap.py                 # 4. → 06_table_in_vs_repmap.csv (precisa de src/RepMap.xlsx)
python migration_hints_table_in_repmap_chameleon.py   # 5. → 06_migration_hints_table_in.csv
```

Inputs de referência em `src/`: `inventario_transacional.csv` (corporativo), `RepMap.xlsx` (mapa de replicação), `chameleon.csv` (gerado no passo 2). `bq_connect.py` é só para consulta interativa ao BigQuery — não substitui o passo 2.

## converter/ — conversão EGP → dbt

Scripts rodam **da raiz de `converter/`** como módulos: `python -m scripts.<nome>`. O roteiro completo (passos 1–6, gates, modo batch e guardrails operacionais — nunca `dbt build`, nunca `git commit/push` automático) está em [`converter/README.md`](converter/README.md) e no skill do orquestrador.

## Histórico

O conteúdo de `converter/` e `egps_analysis/` foi importado em 2026-06-12 do repositório de trabalho `project_sas` (ambiente BV) como snapshot, sem histórico de commits. O acompanhamento da migração SAS está em [`STATUS_MIGRACAO_SAS.md`](STATUS_MIGRACAO_SAS.md).
