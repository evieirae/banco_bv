# Design — Filtro de origem na aba "Monitoramento Inputs"

**Data:** 2026-06-18
**Componente:** `egps_analysis/app` (frontend React/TS + backend FastAPI) + `egps_analysis/publish_to_databricks.py` (coluna nova na tabela Delta `sas_inputs_monitor`)
**Status:** aprovado para implementação

## 1. Objetivo

Permitir filtrar — e ver — os inputs da aba **Monitoramento Inputs** pela **origem**
do dado: de onde a tabela vem e o que ela exige na migração. Hoje a aba só expõe
`source_types` cru (tokens como `POSTGRES`, `SAS/LOCAL -> LIBNAME_IN`), sem uma
classificação acionável.

Motivação adicional: parte de "SAS/Local a ingerir" não é ingestão externa — é
**tabela intermediária produzida por outro EGP** (dependência do pipeline). No
escopo Indicium, 544 das tabelas SAS/Local são output de algum EGP. O filtro
precisa separar isso.

## 2. Classificação de origem (4-way + categorias não-tabela)

Cada input recebe **uma** `origem`, por prioridade:

| origem | regra | significado |
|---|---|---|
| **BigQuery** | algum `source_type` contém `BIGQUERY` | já modernizada |
| **Arquivo** | `categoria = arquivo` | arquivo (não tabela) |
| **Script** | `categoria = script` | código `.sas` (`%INCLUDE`) |
| **Transacional** | algum token em `_TRANS_SRC` (`POSTGRES`, `SYBASE`, `SYBASEIQ`, `IQ`, `SQLSVR`, `DBCON`, `DBCONN`, `ASE`) | banco transacional |
| **SAS/Local (dependência)** | SAS/Local **e** o artefato é `table_out` de algum EGP do corpus | intermediária: nasce quando o EGP produtor é migrado — **não se ingere** |
| **SAS/Local (externo)** | SAS/Local **e** sem produtor no corpus | candidata a ingestão **OU** dependência de um EGP não recebido |

Prioridade: BigQuery → Arquivo/Script (por categoria) → Transacional →
SAS/Local (split por "produzida"). O split por "produzida" só se aplica ao
fallback SAS/Local (uma tabela transacional que também seja output continua
"Transacional").

### Definição precisa de "produzida" e do limite do heurístico

"Produzida por EGP" = `canon(artifact)` pertence ao conjunto de **todos** os
`table_out` (sem ruído) dos ~1.190 EGPs **extraídos** (não só Indicium).

**Limitação documentada (importante):** o único sinal de produtor é a tabela
aparecer como `table_out` no corpus. Se o EGP produtor **não foi recebido/
extraído**, a tabela cai em **"SAS/Local (externo)"** mesmo sendo, na vida real,
uma dependência. Portanto **"externo" = "sem produtor conhecido no corpus"**, e
não uma garantia de dataset externo. Decisão (2026-06-18): mantemos os rótulos
"externo"/"dependência" pela concisão, mas essa definição precisa **deve** ficar
num tooltip na UI (no controle de origem) e aqui no spec, para o analista não
ler "externo" como "tenho que ingerir" sem antes checar se falta o EGP produtor.

## 3. Decisões de design

1. **Coluna `origem` única e pré-computada** em `sas_inputs_monitor` (valor 4-way
   acima). Filtro = `WHERE origem = X`; coluna da tabela mostra o mesmo valor.
   - *Alternativa descartada (YAGNI):* `origem` 3-way + booleano `produzida_por_egp`
     separado. Mais flexível/consistente com a aba Resumo, mas exige filtro
     composto sem ganho prático para esta aba.
2. **Filtro + coluna visível** na aba (não só filtro).
3. **Escopo: só a aba Monitoramento Inputs.** A aba **Resumo** segue com seu
   `origem_bucket` 3-way (grão diferente — inclui `libname_in`). A divergência de
   rótulo é aceitável; unificar fica para depois.

## 4. Camada de dados — `publish_to_databricks.py`

- Nova função `origem_input(source_types, categoria, produced)` → string 4-way
  (lógica da seção 2). Distinta de `origem_bucket()` (que serve o grão Resumo).
- Em `build()`:
  - calcular `produced` = `{canon(art) para todo table_out sem is_noise_table}`.
  - gravar `origem` em cada `inputs_rows` (`produced = canon(artifact) in produced`).
- `origem` entra em: DDL de `T_IN`, DDL do staging, `in_cols`, e no `MERGE`
  (coluna de **pipeline** — atualizada no refresh, como `categoria`/`source_types`;
  **não** é coluna humana, não preservar).
- **Migração da tabela existente:** adicionar passo idempotente
  `ALTER TABLE {T_IN} ADD COLUMNS IF NOT EXISTS (origem STRING)` antes do MERGE —
  `CREATE TABLE IF NOT EXISTS` não adiciona coluna a tabela já criada em prod.

## 5. Backend — `main.py`

- `/api/inputs`: novo parâmetro `origem: str = ""`. Se `origem in ORIGENS`,
  `where.append(f"origem = {sql_lit(origem)}")`. Incluir `origem` no SELECT.
- Constante `ORIGENS` (lista das 6 origens válidas) + expô-la em `/api/config`
  como `cfg.origens` (padrão de `CATEGORIAS`/`STATUS_OPTIONS`).
- Demais endpoints (`/api/egp`, `/api/input`, Resumo) **inalterados** neste escopo.

## 6. Frontend

- `types.ts`: `InputRow.origem: string`; `Filters.origem: string`;
  `AppConfig.origens: string[]`.
- `api.ts`: passar `origem` no query de `inputs()`.
- `FilterBar.tsx`: `<select>` de origem (opções de `cfg.origens`), no padrão dos
  outros selects. **Tooltip/ajuda** explicando os buckets — em especial
  "externo = sem produtor conhecido no corpus".
- `InputsTable.tsx`: coluna `origem` (cabeçalho + célula + `InputSortKey` `origem`).
- `MonitorView.tsx`: `DEFAULT_FILTERS.origem = ""`; `inputAccessor` cobre `origem`.

## 7. Ordem de deploy (constraint)

1. **Republish** (`publish_to_databricks.py --apply …`) — adiciona+popula `origem`.
   Já está pendente junto do dedup `.sas`; os dois vão juntos. **Gate humano.**
2. **Deploy do backend+frontend** depois do republish — senão o SELECT em
   `origem` quebra (coluna inexistente). **Gate humano.**

## 8. Critérios de aceite

Contadores `origem` no escopo Indicium (todas as categorias, soma = 3.354):

| origem | esperado |
|---|---:|
| SAS/Local (externo) | 1.566 |
| Arquivo | 850 |
| SAS/Local (dependência) | 544 |
| BigQuery | 310 |
| Transacional | 82 |
| Script | 2 |

(Base completa, soma = 11.159: externo 4.336 · Arquivo 3.414 · dependência 2.073
· BigQuery 671 · Script 380 · Transacional 285.)

- Filtrar `origem = "SAS/Local (dependência)"` + `categoria = tabela` + escopo
  Indicium → 544 linhas (das quais 538 "a ingerir").
- Coluna `origem` visível e ordenável na tabela.
- `npm run build` (tsc strict) verde.

## 9. Testes

- **Python:** unit de `origem_input` — um caso por ramo (BigQuery vence; Arquivo;
  Script; Transacional; SAS/Local produced=True → dependência; produced=False →
  externo; prioridade BigQuery sobre transacional).
- **Reprodução dos contadores** da seção 8 via script (ex.: estender
  `docs/analises/build_metricas_escopo.py` ou um check dedicado).
- **Frontend:** `tsc -b && vite build` sem erro; smoke manual do filtro+coluna.

## 10. Fora de escopo

- Unificar `origem` entre Monitor e Resumo.
- Distinguir "EGP ausente" de "externo real" (exigiria fonte extra de EGPs
  esperados — hoje não há sinal).
- Quebra por origem na MetricsBar / funis.
