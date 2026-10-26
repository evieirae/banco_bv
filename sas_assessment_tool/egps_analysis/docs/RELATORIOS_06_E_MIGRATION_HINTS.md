# Relatórios `06_prontidao_tabela.csv` e `06_migration_hints_table_in.csv`

Este documento descreve o **propósito** de cada ficheiro, a **origem** no pipeline e o **significado de cada coluna**.

---

## 1. `06_prontidao_tabela.csv`

### O que é

**Relatório 06 — “prontidão vertical”** do inventário SAS/EGP: uma linha por **artefato** referenciado nos projetos analisados (ficheiros, scripts, tabelas de leitura/escrita, libnames, exports). É a **planilha mestra** de inputs/outputs e caminhos, enriquecida com validação contra o catálogo **Chameleon** (BigQuery) e, quando aplicável, contra o **inventário transacional** (`src/inventario_transacional.csv`).

### Como é gerado

Produzido pelo script **`orchestrator_inventory.py`**, a partir dos ficheiros **`.txt`** gerados pelo extrator de EGP (ex. `egps_extractor.py`), mais:

- `src/chameleon.csv` — cruzamento para tabelas já ingeridas no datalake;
- `src/inventario_transacional.csv` — identificação de SGBD quando não há match Chameleon.

O orquestrador gera **também** os relatórios **01–05** e **não** grava `07_validacao_chameleon.csv` nesta versão (constante reservada no código). Opcionalmente: `python orchestrator_inventory.py --prontidao-scope in|out` para restringir as **linhas** do 06 a entradas ou saídas.

### Âmbito das linhas

Inclui **todas** as categorias de artefato definidas no orquestrador: `file_in`, `script_in`, `table_in`, `libname_in`, `table_out`, `libname_out`, `file_out`, etc. **Não** é apenas tabela.

### Colunas

| Coluna | Descrição |
|--------|-----------|
| `project` | Nome do projeto SAS (identificador lógico derivado do parse dos `.txt` / estrutura de pastas). |
| `file_sas` | Referência ao(s) programa(s) SAS do projeto (lista ou nome, conforme metadados extraídos). |
| `area` | Área de negócio (`business_area`) associada ao projeto. |
| `artifact` | Nome do artefato: ficheiro (ex. `IQ.sas`), referência `lib.tabela`, planilha com `[SHEET=...]`, libname, etc. |
| `path` | Caminho físico ou lógico quando existir (ex. pasta do `LIBNAME` para uma tabela, caminho de include). Vazio se não aplicável. |
| `category` | Tipo de artefato: `file_in`, `table_in`, `libname_in`, `script_in`, `table_out`, `libname_out`, `file_out`, … |
| `source_type` | Origem inferida ou classificada: ex. `BIGQUERY` / `BIGQUERY/GCP`, `Connection -> libname_in` / `Connection -> libname_out`, `DBCON`, `SAS/Local -> libname_in`, `Avaliar` (após match Chameleon), ou valor vindo do inventário transacional (ex. `SYBASE_ASE`). |
| `status_validacao` | Resultado da árvore de decisão do orquestrador: ex. `Não Encontrado`, `Nativa BigQuery (Identificada no EGP)`, mensagens com Chameleon (“modernizada no BigQuery”), `Inventário Transacional (Match Exato 100%)`, etc. |
| `chameleon_NmTabelaOrigem` | Se houve match com Chameleon: texto da origem lógica (ex. `dbcred.dbo.tabela`). Vazio se sem match. |
| `chameleon_NmTabelaDestino` | Tabela destino no BigQuery (`projeto.dataset.tabela`), normalizada em maiúsculas no cruzamento. Vazio se sem match. |
| `chameleon_NmDataSet` | Parte **dataset** do identificador BQ (segundo segmento após o projeto). |
| `chameleon_NmProjeto` | Parte **projeto** GCP do identificador BQ (primeiro segmento). |
| `chameleon_DsOrigem` | Campo `DsOrigem` do Chameleon — descrição textual da origem / conector. |
| `project_extension` | Extensão do ficheiro de projeto (ex. `.egp`). |
| `created_at` | Data/hora de criação do projeto extraída dos metadados, quando disponível. |
| `target_arch` | Tecnologia do cabeçalho `TARGET_ARCH` do `.txt` (ex. `DBT_BQ`), sem o sufixo `(Score: …)`. |

---

## 2. `06_migration_hints_table_in.csv`

### O que é

Relatório **derivado** do `06_prontidao_tabela.csv`, focado em **migração**: cruza referências a **tabelas** com o mapa de **réplica Sybase ASE → IQ** (`src/RepMap.xlsx`) e com o **Chameleon** limitado a fontes **Sybase ASE / Sybase IQ**, para indicar se o dado já existe no datalake e se há desalinhamento com o RepMap.

### Como é gerado

Produzido pelo script **`migration_hints_table_in_repmap_chameleon.py`**.

### Âmbito das linhas (diferença em relação ao 06)

- Apenas linhas com **`category = table_in`** (referências a tabelas como input).
- **Exclui** linhas cujo `source_type` seja **`BIGQUERY`** ou **`BIGQUERY/GCP`** (tratadas como já modernizadas no próprio EGP).

Por isso o número de linhas é **inferior** ao total de linhas `table_in` no 06 se existirem muitas entradas já classificadas como BigQuery.

### Colunas

| Coluna | Descrição |
|--------|-----------|
| `project` | Copiado do 06 — nome do projeto SAS. |
| `file_sas` | Copiado do 06 — programa(s) SAS. |
| `area` | Copiado do 06 — área de negócio. |
| `artifact` | Copiado do 06 — token da tabela (ex. `DBCOR.DBO.TBX`, `LIB.TABELA`). |
| `path` | Copiado do 06 — caminho associado (ex. pasta do libname). |
| `source_type` | Copiado do 06 — classificação de origem (já sem valores exclusivamente “nativo BQ” no recorte exportado). |
| `status_validacao` | Copiado do 06 — estado de validação Chameleon/inventário na geração do relatório 06. |
| `repmap_replica_found` | **Sim** ou **Não** — indica se o `artifact` foi associado a pelo menos uma linha do **RepMap** (réplica declarada ASE→IQ), excluindo casos em que o token não é válido para match (`SKIP`). |
| `repmap_match_level` | Texto em **português** descrevendo **como** foi feita a correspondência no RepMap (ex. correspondência exata por chave, colapso de `DBO`, heurística em 3 partes, não encontrado). |
| `repmap_hit_count` | Número inteiro — quantas linhas do RepMap corresponderam ao `artifact`. |
| `repmap_primary` | Resumo textual da **primeira** linha RepMap encontrada (BD origem/destino, tabela, alvo, tipo, linha na planilha Excel). Vazio se não houver match. |
| `chameleon_sybase_found` | **Sim** ou **Não** — existe pelo menos uma entrada no **Chameleon** com `NmFonteDados` Sybase ASE/IQ compatível com o cruzamento por `database.tabela`. |
| `chameleon_hit_count` | Número de linhas Chameleon (Sybase) consideradas para aquele artefato. |
| `chameleon_match_key` | Chave usada no primeiro match bem-sucedido (ex. `DBCOR.TABELA`); pode aparecer **`qualquer_base.TABELA`** quando o match veio só pelo nome da tabela. |
| `chameleon_primary_NmTabela` | Tabela **trusted** no BigQuery da primeira linha Chameleon encontrada (`projeto.dataset.tabela`). |
| `chameleon_primary_NmTabelaOrigem` | Origem lógica registada no Chameleon (ex. `dbcred.dbo.tabela`). |
| `chameleon_primary_NmFonteDados` | Fonte no Chameleon (ex. `SYBASE_ASE`, `SYBASE_IQ`). |
| `chameleon_primary_DtFimIngestao` | Data/hora da última ingestão registada para essa linha. |
| `migration_pattern` | Frase em **português** com o cenário combinado RepMap + Chameleon Sybase: alinhado, só RepMap, só Chameleon sem RepMap, lacuna nos dois, ou ignorado (token inválido). |
| `attention_use_chameleon_bq_not_repmap` | **Sim** ou **Não** — **Sim** destaca o caso em que **não** há match no RepMap mas **há** ingestão Sybase no Chameleon (prioridade para avaliar uso do datalake em vez de leitura direta legada). |
| `chameleon_matches_short` | Até cinco correspondências Chameleon resumidas; se houver mais, indica **“(mais N)”**. |

---

## Relação entre os dois ficheiros

```text
BigQuery (Chameleon)  →  gcp_bigquery_table_data_export.py  →  src/chameleon.csv
                                                                        │
06_prontidao_tabela.csv  ←  orchestrator_inventory.py  ←  *.txt  ←  egps_extractor.py
        │
        ├── validate_table_in_vs_repmap.py (+ RepMap.xlsx)
        │           └── 06_table_in_vs_repmap.csv
        │
        └── migration_hints_table_in_repmap_chameleon.py (+ RepMap.xlsx + chameleon.csv Sybase)
                    └── 06_migration_hints_table_in.csv
```

- O **06** é a **fonte canónica** do inventário por projeto e artefato.
- O **06_migration_hints** é um **recorte analítico** para o time de migração, com colunas **adicionais** de RepMap e Chameleon Sybase; **não substitui** o relatório 06 para ficheiros, scripts ou saídas.

---

*Documento alinhado aos scripts `orchestrator_inventory.py`, `validate_table_in_vs_repmap.py` e `migration_hints_table_in_repmap_chameleon.py`.*

---

## Ordem de execução (resumo)

1. `egps_extractor.py` → `.txt`.
2. **`gcp_bigquery_table_data_export.py`** → **`src/chameleon.csv`** (antes do orquestrador).
3. `orchestrator_inventory.py` → `06_prontidao_tabela.csv` (e relatórios 01–05).
4. `validate_table_in_vs_repmap.py` → `06_table_in_vs_repmap.csv` (opcional mas recomendado antes dos *hints*).
5. `migration_hints_table_in_repmap_chameleon.py` → `06_migration_hints_table_in.csv`.

Os passos 4 e 5 são **independentes** entre si (ambos leem o mesmo 06 e o `RepMap.xlsx`); a ordem acima favorece primeiro a auditoria de réplica ASE→IQ.
