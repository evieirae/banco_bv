# Passo a passo: identificar tabelas modernizáveis referenciadas em projetos `.egp`

Este guia liga a **extração** do código SAS dentro dos Enterprise Guide (`.egp`) à **classificação** de oportunidades de modernização (uso de BigQuery / datalake em vez de fontes legadas).

**“Modernizar”** aqui significa: o dado **já está** ou **pode ser consumido** a partir do ecossistema atual (BigQuery via Chameleon, ou referência já nativa BQ no projeto), em contraste com leitura direta só em Sybase/ASE/IQ ou librefs locais sem caminho claro para o datalake.

---

## Pré-requisitos

- Pasta com ficheiros **`.egp`** (projetos SAS Enterprise Guide).
- Python 3 e dependências: na raiz de `egps_analysis`, `pip install -r requirements.txt` (inclui **`openpyxl`** para ler `RepMap.xlsx` em `validate_table_in_vs_repmap.py` / `migration_hints_*`).
- Ficheiros de referência em `src/` (conforme o teu ambiente):
  - **`chameleon.csv`** — catálogo de ingestões no datalake; **actualizar** com **`gcp_bigquery_table_data_export.py`** (export a partir do BigQuery) **antes** de correr o orquestrador, para matches Chameleon correctos.
  - `inventario_transacional.csv` — inventário de objetos por SGBD (opcional para o orquestrador).
  - `RepMap.xlsx` — mapa de réplica ASE → IQ (para análise fina Sybase).

---

## Fluxo resumido

```text
.egp  →  extrator  →  *.txt ─────────────────────────────┐
                                                          │
BigQuery (Chameleon)  →  gcp_bigquery_table_data_export  →  src/chameleon.csv
                                                          │
                                                          ▼
                                              orquestrador  →  06_prontidao_tabela.csv
                                                          │
                    ┌─────────────────────────────────────┴─────────────────────────────────────┐
                    │                                                                         │
      validate_table_in_vs_repmap.py                          migration_hints_table_in_repmap_chameleon.py
           (+ RepMap.xlsx)                                    (+ RepMap.xlsx + chameleon.csv Sybase)
                    │                                                                         │
                    ▼                                                                         ▼
        06_table_in_vs_repmap.csv                                      06_migration_hints_table_in.csv
```

**Ordem recomendada:** depois dos `.txt` e de **`src/chameleon.csv`** actualizado (passo de export GCP), executar o **orquestrador**. Em seguida, primeiro **`validate_table_in_vs_repmap.py`** (vista só réplica ASE→IQ), depois **`migration_hints_table_in_repmap_chameleon.py`**. Os dois últimos só precisam do mesmo `06` e do `RepMap.xlsx`; não dependem um do outro, mas esta ordem alinha auditoria operacional antes da análise de migração para o datalake.

---

## Passo 1 — Extrair texto e inventário I/O dos `.egp`

1. Configura em **`egps_extractor.py`** (ou passa por CLI):
   - `DEFAULT_INPUT_FOLDER` = pasta onde estão os `.egp` (por área/subpastas, se usares essa convenção).
   - `DEFAULT_OUTPUT_FOLDER` = pasta onde vão ficar os `.txt` (ex. `text_egps`).

2. Executa:
   ```text
   python egps_extractor.py [caminho_para_pasta_ou_ficheiro]
   ```

3. Confirma que por cada projeto existe pelo menos um **`.txt`** com bloco `START_METADATA` … `[[ I/O INVENTORY ]]` … `END_METADATA` e o código SAS a seguir.

**O que obténs:** referências a `lib.tabela`, `BD.DBO.TABELA`, pass-through SQL, ficheiros, etc., já agregadas e etiquetadas no cabeçalho.

---

## Passo 2 — Gerar o relatório 06 (inventário por artefato)

1. **Actualize `src/chameleon.csv`** com **`gcp_bigquery_table_data_export.py`** (export da vista/tabela Chameleon no BigQuery para `./src/chameleon.csv`). Este passo deve ser feito **antes** do orquestrador para o relatório 06 reflectir ingestões actuais.

2. Em **`orchestrator_inventory.py`**, define:
   - `INPUT_FOLDER` = pasta dos **`.txt`** gerados no Passo 1 (não os `.egp`).
   - `CHAMELEON_CSV_PATH` e `INVENTARIO_CSV_PATH` apontando para `src/chameleon.csv` e `src/inventario_transacional.csv`.

3. Executa o orquestrador (na pasta do projeto):
   ```text
   python orchestrator_inventory.py
   ```
   Opcional: `python orchestrator_inventory.py --prontidao-scope in` (só linhas de **entrada** no 06: `file_in`, `table_in`, `libname_in`, `script_in`) ou `--prontidao-scope out` (só saídas). O valor predefinido é `all`.

4. Abre o ficheiro gerado **`06_prontidao_tabela.csv`**.

**O que obténs:** uma linha por artefato (ficheiro, tabela, libname, …). Para **tabelas** usadas como entrada, interessa a categoria **`table_in`**.

---

## Passo 3 — Filtrar linhas que são “tabela em script”

No `06_prontidao_tabela.csv`:

1. Filtra **`category = table_in`** — são as referências a tabelas (inputs) identificadas a partir do código / XML ligado ao fluxo.

2. Opcionalmente cruza com **`project`** / **`file_sas`** para saber **em que projeto .egp** (derivado do `.txt`) cada tabela aparece.

A coluna **`artifact`** é o nome da tabela como referenciada (ex. `DBCOR.DBO.TBPARCEIRO`, `BV-PDBD-PRD.TRUSTED_*.TABELA`).

---

## Passo 4 — Identificar tabelas “já modernizadas” no relatório 06

Ainda no `06_prontidao_tabela.csv`, para `category = table_in`:

| Sinal | Colunas / valores típicos |
|-------|---------------------------|
| **Já nativo BigQuery no EGP** | `source_type` contém **`BIGQUERY`** ou **`BIGQUERY/GCP`** — o código já aponta para BQ; migração “de uso” costuma ser menor. |
| **Match com Chameleon (datalake)** | `status_validacao` e texto de modernização; colunas **`chameleon_NmTabelaDestino`**, **`chameleon_NmTabelaOrigem`** preenchidas — a tabela (ou equivalente) **já existe** no catálogo Chameleon / BQ. |
| **Só inventário transacional** | `status_validacao` tipo inventário e `source_type` com SGBD (ex. Sybase) quando não houve match Chameleon — confirma legado, não modernização automática. |

Estas linhas respondem a: *“esta tabela aparece no script e já tem contraparte moderna / BQ?”*

---

## Passo 5 — Validar só o mapa de réplica (RepMap)

Vista **só RepMap** (ASE→IQ), sem cruzamento com Chameleon — útil para **operações Sybase** e auditoria do mapa de réplica.

1. Garante **`src/RepMap.xlsx`** atualizado.

2. Executa (a partir da pasta `egps_analysis/`, ou com caminhos explícitos):
   ```text
   python validate_table_in_vs_repmap.py [06_prontidao_tabela.csv] [src/RepMap.xlsx] [06_table_in_vs_repmap.csv]
   ```

3. Abre **`06_table_in_vs_repmap.csv`**: filtra `category = table_in` e indica **`replica_found`** (`YES`/`NO` no CSV) e detalhes de match no RepMap.

---

## Passo 6 — Cruzar RepMap e Chameleon Sybase (migration hints)

Para focar **Sybase ASE / IQ**, **réplica** e **datalake** (ingestões Chameleon):

1. Garante **`src/RepMap.xlsx`** e **`src/chameleon.csv`** atualizados.

2. Executa:
   ```text
   python migration_hints_table_in_repmap_chameleon.py [06_prontidao_tabela.csv] [src/RepMap.xlsx] [src/chameleon.csv] [06_migration_hints_table_in.csv]
   ```

3. Abre **`06_migration_hints_table_in.csv`** (exclui `BIGQUERY`/`BIGQUERY/GCP` no `source_type` para focar o que ainda não é “nativo BQ” no EGP).

**Interpretação útil:**

| Coluna / situação | Leitura |
|-------------------|---------|
| **`migration_pattern`** = texto sobre Chameleon Sybase **sem** correspondência no RepMap | Candidato forte: **datalake tem ingestão Sybase**, mas o mapa de réplica ASE→IQ não casou com o token do EGP — rever SQL/libname para usar **BQ**. |
| **`attention_use_chameleon_bq_not_repmap` = Sim** | Mesma prioridade — destaque automático. |
| **Alinhado RepMap + Chameleon** | Réplica conhecida **e** presença no Chameleon (Sybase). |
| **Só RepMap, sem Chameleon Sybase** | Réplica mapeada; ingestão BQ Sybase pode não existir ou ter outro nome. |
| **Lacuna** | Nem RepMap nem Chameleon Sybase no cruzamento — possível backlog de ingestão ou nome incompatible. |

---

## Passo 7 — Rever no código `.egp` / SAS (validação humana)

A pipeline identifica **tokens**; a decisão final de modernização exige:

1. Abrir o **projeto EG** ou o **`.txt`** correspondente e localizar `PROC SQL`, `DATA`, pass-through e `LIBNAME`.
2. Confirmar se o **mesmo objeto** semântico está no Chameleon (homónimos entre databases são possíveis).
3. Para equipas de dados: alinhar **dataset BQ** (`chameleon_primary_NmTabela`) e **política de acesso** (trusted/work).

---

## Checklist rápido

| # | Ação |
|---|------|
| 1 | Extrair `.txt` com `egps_extractor.py` a partir dos `.egp`. |
| 2 | Actualizar `src/chameleon.csv` com `gcp_bigquery_table_data_export.py` (BigQuery). |
| 3 | Gerar `06_prontidao_tabela.csv` com `orchestrator_inventory.py`. |
| 4 | Filtrar `category = table_in`. |
| 5 | Marcar linhas com `BIGQUERY`/`BIGQUERY/GCP` ou colunas `chameleon_*` preenchidas = já orientadas a modernização. |
| 6 | Correr `validate_table_in_vs_repmap.py` (RepMap × `table_in`). |
| 7 | Correr `migration_hints_table_in_repmap_chameleon.py` (RepMap + Chameleon Sybase). |
| 8 | Priorizar `attention_use_chameleon_bq_not_repmap = Sim` no CSV de hints e rever artefactos no código. |

---

## Limitações a comunicar ao negócio

- **Librefs só SAS** (`AUTOMATI.BVO_...`) podem não casar com Chameleon por nome físico.
- **Nomes duplicados** em databases diferentes exigem revisão manual.
- O **06** reflete o que foi **extraído e parseado**; código morto ou só em comentários pode aparecer em secções *comment-only* no `.txt`, não sempre como `table_in` “ativo”.

---

*Documento alinhado aos scripts neste repositório. Ajusta caminhos e nomes de pastas ao teu ambiente.*
