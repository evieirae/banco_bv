# Catálogo `src/chameleon.csv`

## O que é

Ficheiro **CSV** com o inventário de tabelas **ingeridas no datalake** via solução **Chameleon**, com destino em **BigQuery** (camadas *trusted* / *work*). Cada linha representa um fluxo de dados: origem lógica → tabela física no BQ, mais metadados de fonte e última ingestão.

## Para que serve no pipeline

- **`orchestrator_inventory.py`** — cruza artefatos do relatório `06_prontidao_tabela.csv` (em especial `table_in` / `table_out`) com as colunas de **destino** e **origem** no CSV para preencher `status_validacao` e colunas `chameleon_*`. No código, os valores são normalizados para os campos internos `NmTabelaDestino` e `NmTabelaOrigem` (ver nota abaixo sobre nomes de colunas no ficheiro exportado).
- **`migration_hints_table_in_repmap_chameleon.py`** — indexa apenas linhas cuja **`NmFonteDados`** corresponde a **Sybase ASE** ou **Sybase IQ** (e variantes), para cruzar `database.tabela` com o inventário EGP e o `RepMap.xlsx`.

**Actualização do ficheiro:** em rotina de análise, gere `src/chameleon.csv` com **`gcp_bigquery_table_data_export.py`** (export da tabela/vista Chameleon no BigQuery) **antes** de correr o orquestrador — ver [`PIPELINE_INVENTARIO_MIGRACAO_SAS.md`](PIPELINE_INVENTARIO_MIGRACAO_SAS.md).

### Como o orquestrador escolhe as colunas no CSV

A função `load_chameleon_data` **não exige** cabeçalhos com nomes exactos `NmTabelaDestino` / `NmTabelaOrigem`. Percorre os nomes das colunas (minúsculas, sem espaços) e escolhe:

- **Origem:** primeira coluna cujo nome contém `origem` e `tabela`, excluindo nomes com `work` (ex.: `NmTabelaOrigem`).
- **Destino:** primeira coluna com `tabela` no nome **sem** `origem` e **sem** `work` (ex.: **`NmTabela`** trusted — `NmTabelaWork` é ignorada para este efeito).

Assim, um export típico com `NmTabela` + `NmTabelaOrigem` funciona sem renomear colunas.

## Formato

- Delimitador: vírgula.
- Codificação típica: UTF-8 com BOM (`utf-8-sig`).
- Cabeçalho na primeira linha.

## Colunas

| Coluna | Descrição |
|--------|-----------|
| `NmTabela` | Identificador completo da tabela **trusted** no BigQuery, no formato `projeto.dataset.tabela` (ex. `bv-pdbd-prd.trusted_dbcred.tbproposta`). É o destino canónico da ingestão. |
| `NmTabelaWork` | Identificador da tabela na camada **work** associada (mesmo projeto, dataset `work_*` espelhando o domínio). Usada em fluxos de transformação após a carga inicial. |
| `NmTabelaOrigem` | Descrição da **origem lógica** do dado: pode ser notação `db.dbo.tabela`, caminho de ficheiro, API (`api.salesforce.*`), string JDBC truncável antes de `(` em outros scripts, etc. Serve para rastreabilidade e para *match* com nomes de tabela no SAS/SQL. |
| `DsOrigem` | Texto descritivo ou identificador curto da origem / conector (ex. `api-salesforce-account`, `SFTP`, nome de *pipeline*). Complementa `NmFonteDados` com contexto legível. |
| `NmFonteDados` | **Sistema ou motor fonte** da ingestão (ex. `SYBASE_ASE`, `SYBASE_IQ`, `SQL_Server`, `Salesforce`, `PUBSUB`, `FIRESTORE`). Usado no projeto para filtrar ingestões Sybase no script de *migration hints*. |
| `DtFimIngestao` | Data e hora (com fuso, em ISO 8601) da **última ingestão** registada para essa linha no catálogo. |

## Notas de uso

- O ficheiro agrega **várias tecnologias**; apenas um subconjunto é Sybase. Scripts que falam em “Chameleon Sybase” aplicam filtro em `NmFonteDados`.
- Nomes de coluna no CSV podem ser sensíveis a maiúsculas; em cruzamentos o código costuma normalizar para maiúsculas onde necessário.

---

*Documento gerado para apoio ao time de dados. Atualize este ficheiro se o layout exportado do Chameleon mudar.*
