# O que conta como **input** de um EGP/`.sas`

> Doc de referência: como `egps_extractor.py` (extração do `.egp`/`.sas` → `text_egps/<egp_key>.txt`) e `orchestrator_inventory.py` (consolidação nos relatórios 01–06) decidem o que é "input" e o que é descartado.
>
> Use este doc quando precisar entender:
> - Por que uma tabela apareceu (ou não) no `01_prioridade_ingestao.csv` / `06_prontidao_tabela.csv`
> - Por que uma aresta `EGP_A → EGP_B` apareceu (ou não) em `03_matriz_dependencias.csv`
> - O que vai contar como "input a ingerir" no destino (BigQuery/Databricks)

---

## 1. As 3 categorias de input (+ 1 de contexto)

O relatório 06 (`06_prontidao_tabela.csv`) consolida cada leitura em uma das categorias abaixo. Em `orchestrator_inventory.py`:

```python
_REPORT6_CATEGORIES_IN = frozenset({'file_in', 'table_in', 'script_in'})
```

| Categoria | Vem do `.txt` (seção) | O que é | Exemplo |
|---|---|---|---|
| **`table_in`** | `EXTERNAL INPUTS (Requires Ingestion)` + `INTERNAL READS (Temp/Local)` filtrado | Tabela `LIB.MEMBRO` lida pelo script (DATA STEP `SET`/`MERGE`, `SQL FROM`, pass-through). É o input **canônico** para a migração. | `PME.BASE_HISTORICA_GESTAO_OMIE`, `BV-PDBD-PRD.TRUSTED_EXTE_GFD.TBBASEFATPRESUMIDOSERASAPJ` |
| **`file_in`** | `IMPORTED FILES (Requires Ingestion)` | Arquivo físico lido — `.xlsx`, `.csv`, `.json`, `.parquet`, `.sas7bdat`, `.txt`, etc. (LIBNAME apontando para path, PROC IMPORT, INFILE) | `/projetos/acessos/bq/op/saop-dtm.json`, `N:\…\TBCONSOLIDADA.xlsx` |
| **`script_in`** | `INCLUDED SCRIPTS (Dependencies)` | `.sas` chamado via `%INCLUDE` — dependência **de código**, não de dado | `/projetos/MISV/sas-misv-base-lib/scripts/ConectaDB.sas` |

> **`libname_in` NÃO conta como input** (decisão 2026-06-12). O libref citado sem membro
> (`IMPORTED_LIBNAMES`, ex.: `PME`) é só **contexto**: a tabela concreta importada da libname já
> entra individualmente como `table_in` (ex.: `PME.BASE_HISTORICA_GESTAO_OMIE`). Contar o libref
> além das tabelas duplicaria a mesma fonte. As linhas `libname_in` continuam no relatório 06
> (scope `all`) como diagnóstico, mas ficam fora de métricas de input, do filtro `--scope in`
> e dos inputs publicados no Databricks (`publish_to_databricks.py`).

**⚠ Um `.sas` aparece em DOIS papéis — `file_in` e `script_in` — e isso pode se repetir.**
O mesmo arquivo `.sas` é `script_in` quando `%INCLUDE`-ado, mas vira `file_in` quando citado
como caminho (tem extensão de arquivo / é caminho de SO — ver §2.1). Como a chave do monitor
é `categoria::ARTEFATO`, o mesmo `.sas` virava **duas linhas** (`arquivo` + `script`),
inflando `qtd_projetos`/prontidão — eram **375 arquivos** nesse estado (ex.: `all-includes.sas`,
`libname.sas`, `ConectaDB.sas`, `RISCO_BCO_DBBVF.sas`). O `publish_to_databricks.py`
normaliza **todo `.sas` para a categoria `script`** (`eff_categoria()`) — é código, não dado a
ingerir — unificando os dois papéis numa única chave. **Pode reaparecer** se o extrator mudar a
classificação de `.sas`; reconferir com um group-by `artifact`×`category` no 06
(`canon(art)` em ≥2 categorias).

### Exemplo real — `text_egps/Atacado__Monitoramento.txt`

```
[[ I/O INVENTORY ]]
EXTERNAL INPUTS (Requires Ingestion):
  BV-PDBD-PRD.TRUSTED_EXTE_GFD.TBBASEFATPRESUMIDOSERASAPJ [BIGQUERY],
  PME.BASE_HISTORICA_GESTAO_OMIE [SAS/Local],
  PME.BASE_HISTORICA_OMIE_CEDENTES [SAS/Local],
  PME.BASE_HISTORICA_PMUM_SF [SAS/Local]
SAME-SCRIPT RE-READS: (none)
IMPORTED_LIBNAMES: PME
EXPORTED_LIBNAMES: (none)
IMPORTED FILES (Requires Ingestion): /projetos/acessos/bq/op/saop-dtm.json
INTERNAL READS (Temp/Local): (none)
INCLUDED SCRIPTS (Dependencies): (none)
```

Resultado consolidado no `06_prontidao_tabela.csv`:

| categoria | artefato |
|---|---|
| `table_in` | `BV-PDBD-PRD.TRUSTED_EXTE_GFD.TBBASEFATPRESUMIDOSERASAPJ` |
| `table_in` | `PME.BASE_HISTORICA_GESTAO_OMIE` |
| `table_in` | `PME.BASE_HISTORICA_OMIE_CEDENTES` |
| `table_in` | `PME.BASE_HISTORICA_PMUM_SF` |
| `file_in` | `/projetos/acessos/bq/op/saop-dtm.json` |
| `libname_in` *(contexto — não conta como input)* | `PME` |

---

## 2. Regras de filtragem (o que **não** entra)

### 2.1 Excluído de `table_in` — `_exclude_from_table_in_metadata_token()`

| Token | Por quê é excluído | Vai para outra categoria? |
|---|---|---|
| Macro não resolvido (`&VAR`, `%macro`) | Não é tabela concreta — bloqueia a aresta no grafo de dependências | Não (descartado) |
| Caminho de SO (`/…`, `\…`, `C:\…`) | É arquivo, não tabela SAS | Sim → `file_in` |
| Termina em extensão de arquivo (`.xlsx`, `.csv`, `.json`, `.parquet`, `.sas7bdat`, `.txt`, `.tsv`, `.zip`, `.xml`, …) | Idem | Sim → `file_in` |
| Notação V6 com macro no membro (`CART.TABELA_{MACRO}`) | **Mantido** como `table_in` (caso particular: lib resolvido, só o membro tem variável) | — |

### 2.2 Librefs excluídos — `_EXCLUDED_SAS_LIBREFS`

Tabelas com estes librefs **não** entram em nenhuma categoria (são voláteis/sistema):

```
WORK, SASUSER, SASHELP, SASTMP, TEMP, USER, MAPPING
```

### 2.3 `INTERNAL READS` é fortemente filtrado — `_merge_inputs_with_filtered_internal()`

Só entra como `table_in` se:
1. Casa o padrão `LIB.MEMBRO` válido (sem macro, sem espaços, libref alfa-numérico)
2. **E** o libref está em `DETECTED_LIBNAMES` (descarta lixo de scan de texto)

Caso contrário descarta — evita poluir o relatório com tokens espúrios encontrados no scan bruto do `.txt`.

### 2.4 `SAME-SCRIPT RE-READS` é sempre descartado

Quando o script grava uma tabela e relê ela depois no mesmo script, isso **não** é input externo — não conta como dependência de ingestão nem cria aresta entre EGPs.

### 2.5 Modo "executable" vs "full" — `--report6-artifact-mode`

Por padrão (`executable`) o relatório 06 **omite** linhas suplementares de diagnóstico. Com `full`, aparecem com source-type explícito:

| `source` (modo `full`) | O que indica | Modo `executable` |
|---|---|---|
| `SAS/Local (macro no membro)` | Referência onde o nome do membro tem variável macro não resolvida | Omitido |
| `SAS/Local (scan completo .txt)` | Encontrada no scan bruto, fora do fluxo EG | Omitido |
| `SAS/Local (EG project.xml — não no scan do fluxo)` | Registrada no `project.xml` do EG mas não executada no flow | Omitido |
| `SAS/Local (só em comentário — não executado)` | Referência em comentário SAS | Omitido |

Use `full` para auditar; use `executable` (default) para governança/decisão de migração.

---

## 3. `table_in` → aresta de dependência (relatório 03)

A matriz `03_matriz_dependencias.csv` (e o grafo `dependencias_indi_231_grafo.html`) só liga `EGP_A → EGP_B` quando:

1. EGP_A produz uma tabela em `outputs` (consolidado de `PERMANENT OUTPUTS (Target Marts)` + `TEMP/DISCARDED OUTPUTS`)
2. EGP_B lê essa **mesma tabela** em `table_in`
3. A comparação usa `_canonical_table_key()` — normalização que remove crases/aspas, faz trim e converte para upper-case, então `Lib.Tbl` e `LIB.TBL` casam

Se a tabela é input de EGP_B mas **nenhum** EGP no inventário a produz, ela **não** vira aresta — vira "requer ingestão externa" no `01_prioridade_ingestao.csv` (fonte corporativa a modernizar para BigQuery/Databricks).

### Filtro adicional: input que também é output do próprio EGP

Se um EGP grava e relê a mesma tabela (caso comum em jobs append/merge incremental), o orchestrator não cria self-edge:

```python
if k_in in proj_output_keys.get(proj, ()):
    # leitor TAMBEM escreve a tabela: partilha/append, nao e produtor→consumidor
    continue
```

Isso evita falsos ciclos em scripts de UPDATE/MERGE.

---

## 4. Diferença entre os 3 tipos de "input a ingerir"

Quando uma área pergunta "**o que vamos precisar ingerir no BigQuery/Databricks**", a resposta vem do relatório 01, que cruza `table_in` × `outputs` do inventário e categoriza:

| Categoria | Significado | Onde vai parar |
|---|---|---|
| **Gerado Internamente** | Existe um EGP no inventário que produz esta tabela | Vira aresta no grafo (relatório 03), entra na ordem de migração (ondas, relatório 04) |
| **Requer Ingestão Externa** | Nenhum EGP do inventário produz — vem de fonte corporativa (Sybase, BigQuery, SQL Server, arquivo, libref legado) | Vira **input do projeto** — alguém precisa modernizar essa fonte (Chameleon, RepMap) |

O `validate_table_in_vs_repmap.py` e `migration_hints_table_in_repmap_chameleon.py` fazem essa segunda parte: cruzam os `table_in` "externos" com `src/RepMap.xlsx` (mapa de replicação) e `src/chameleon.csv` (catálogo de ingestões já feitas no BigQuery) para classificar:

- **Modernizado** — já existe a versão BigQuery/Databricks (`status_validacao` aponta para tabela equivalente)
- **A modernizar** — está no RepMap mas ainda não foi para BigQuery
- **Sem cobertura** — não está em lugar nenhum, precisa de plano de ingestão novo

---

## 5. Por que importa para os 4 níveis de input

Resumindo o fluxo conceitual:

```
Script SAS lê algo  ───►  Extrator classifica
                         │
                         ├─► table_in  ──► é tabela?     ──► sim, lib.membro válida, libref não-volátil
                         ├─► file_in   ──► é arquivo?    ──► tem extensão ou é caminho
                         ├─► script_in ──► é %INCLUDE?   ──► dependência de código
                         └─► libname_in ─► libref sem membro ─► CONTEXTO (não é input)
                                          │
                                          ▼
                                   Esta tabela é produzida por
                                   outro EGP do inventário?
                                          │
                                ┌─────────┴─────────┐
                              SIM                  NÃO
                                │                   │
                                ▼                   ▼
                       Aresta EGP→EGP        Requer Ingestão
                       (relatório 03)        Externa (relatório 01)
                                │                   │
                                ▼                   ▼
                       Onda de migração       Cruza com RepMap +
                       (relatório 04)         Chameleon → categoriza
                                                como Modernizado /
                                                A modernizar / Sem cobertura
```

---

## 6. Onde está cada coisa no código

| Pergunta | Arquivo | Função/símbolo |
|---|---|---|
| Como o `.txt` é gerado? | `egps_extractor.py` | Saída das seções `EXTERNAL INPUTS`, `IMPORTED FILES`, `IMPORTED_LIBNAMES`, `INCLUDED SCRIPTS`, `INTERNAL READS` |
| Quais categorias contam como input no relatório 06? | `orchestrator_inventory.py` | `_REPORT6_CATEGORIES_IN` |
| Quais librefs SAS são excluídos? | `orchestrator_inventory.py` | `_EXCLUDED_SAS_LIBREFS` |
| Quando um token é excluído de `table_in`? | `orchestrator_inventory.py` | `_exclude_from_table_in_metadata_token()` |
| Como `INTERNAL READS` é filtrado? | `orchestrator_inventory.py` | `_merge_inputs_with_filtered_internal()` |
| Como o source-type é refinado (SAS/Local vs BIGQUERY vs SYBASE)? | `orchestrator_inventory.py` | `_refine_table_in_source_type()` |
| Como `LIB.MEMBRO` é validado? | `orchestrator_inventory.py` | `_is_plausible_sas_lib_dot_member()` |
| Como tabelas são casadas entre EGPs (produtor↔consumidor)? | `orchestrator_inventory.py` | `_canonical_table_key()` |
| Como o pipeline 01 → 06 escolhe entre `executable` e `full`? | `orchestrator_inventory.py` | parâmetro `report6_artifact_mode` |

---

## 7. Tabela-resumo (cola na parede)

| Tipo de leitura no SAS | Categoria | Vira aresta? | Vira "input a ingerir"? |
|---|---|---|---|
| `SET PME.BASE_X;` (tabela em libref real) | `table_in` | Sim, se outro EGP produz | Sim, se ninguém produz |
| `SET WORK.TEMP;` | — (descartado) | Não | Não |
| `PROC IMPORT … '/path/x.xlsx'` | `file_in` | Não (não casa com tabela) | Sim, arquivo a ingerir |
| `LIBNAME XPTO '/folder';` (sem membro lido) | `libname_in` *(contexto)* | Não | **Não** — só as tabelas `XPTO.*` lidas contam (via `table_in`) |
| `%INCLUDE '/scripts/util.sas';` | `script_in` | Não (não é tabela) | Não (é dependência de código) |
| `SET LIB.&VAR;` (macro não resolvido) | — (descartado) | Não | Não |
| `SET tabela_recem_gravada;` (mesmo script) | — (descartado: SAME-SCRIPT) | Não | Não |
| `SELECT … FROM \`bv-pdbd.dataset.tbl\`` (pass-through BQ) | `table_in` | Sim, se outro EGP produz | Sim, se ninguém produz (com `[BIGQUERY]`) |

---

## 8. Como o app `monitoramento-sas` expõe isto (coluna `origem`)

O app (`egps_analysis/app/`) reusa esta classificação e adiciona a coluna **`origem`** (taxonomia de 6 valores, `app/backend/main.py:ORIGENS`) para responder, por linha, "de onde vem este input?":

| `origem` (app) | Vem de | Equivale aqui a | Rótulo na UI |
|---|---|---|---|
| `BigQuery` | `table_in` com source-type `[BIGQUERY]` | já modernizado | — |
| `Transacional` | `table_in` de fonte corporativa (Sybase/SQL Server/…) | §4 "Requer Ingestão Externa" | a modernizar |
| `SAS/Local (dependência)` | `table_in` SAS/Local **produzida por outro EGP do corpus** | §3 aresta EGP→EGP | dependência interna |
| `SAS/Local (externo)` | `table_in` SAS/Local que **nenhum EGP do corpus produz** | §3 "nenhum EGP produz" | **"dep. produtor ausente"** |
| `Arquivo` | `file_in` | §1 | arquivo a ingerir |
| `Script` | `script_in` | §1 | dependência de código |

### A decisão "externo" — por quê (2026-06)

Quando uma tabela `LIB.MEMBRO` SAS/Local é lida mas **nenhum EGP do inventário a produz** (§3), havia três opções: (a) deixá-la sumir entre os inputs comuns, (b) dar a ela uma fonte corporativa inventada, ou (c) marcá-la como **dependência de um produtor ausente**. Escolhemos **(c)**: `origem = "SAS/Local (externo)"`, rotulada **"dep. produtor ausente"** no app.

**Racional:** SAS/Local sem produtor no corpus quase sempre significa que **o EGP produtor existe fora do recorte analisado** — logo o dado não é "fonte corporativa a ingerir do zero" (`Transacional`), e sim uma **lacuna de mapeamento** (falta trazer o EGP produtor para o corpus). Tornar isso explícito orienta a ação correta (mapear/incluir o produtor) em vez de abrir um plano de ingestão desnecessário. É a contraparte, no app, do galho "nenhum EGP produz" do fluxograma da §5.

### Homônimos (`n_paths_fisicos`)

A linhagem SAS/Local é feita por **(path físico, membro)**, não só pelo nome do membro. Um mesmo nome de input (ex.: `PME.BASE`) pode resolver para **N caminhos físicos distintos** em EGPs diferentes. Quando `n_paths_fisicos > 1`, o app marca **"homônimo"** no detalhe do EGP — sinal de que aquele nome **não** é uma tabela única e a consolidação precisa desambiguar pelo path antes de tratar como a mesma fonte.
