# Mapa de réplica `src/RepMap.xlsx`

## O que é

Ficheiro **Excel (.xlsx)** com o catálogo operacional de **réplicação de dados** entre **Sybase ASE** (origem transacional) e **Sybase IQ** (destino analítico), e metadados associados (servidores, definições de replicação, tipo de carga). Cada linha descreve, em geral, **uma tabela** (ou artigo de replicação) num dado par origem→destino.

## Para que serve no pipeline

- **`validate_table_in_vs_repmap.py`** — lê a **primeira folha** da planilha, com cabeçalho na linha 1, e cruza tokens do inventário (`06_prontidao_tabela.csv`, filtro `table_in`) com chaves derivadas de `DBsource`, `DBtarget`, `Tabela`, `TabRep`, etc., para indicar se a tabela referenciada no SAS **consta no mapa de réplica**.

- **`migration_hints_table_in_repmap_chameleon.py`** — reutiliza a mesma carga e a função `match_artifact` para o mesmo fim, em conjunto com o Chameleon (Sybase).

## Formato

- **Folha utilizada:** a primeira do livro (`sheetnames[0]`).
- **Linha 1:** nomes das colunas.
- **Dados:** a partir da linha 2; linhas vazias nas primeiras colunas são ignoradas pelo código de leitura.

## Colunas

| Coluna | Descrição |
|--------|-----------|
| `Source` | Identificador do **servidor ou papel de origem** no ecossistema de replicação Sybase (lado ASE / publicação). |
| `DBsource` | Nome do **database no Sybase ASE** onde a tabela de origem existe. |
| `Target` | **Destino da réplica** — tipicamente o servidor ou cluster **Sybase IQ** (ou identificador de nó/camada) para onde os dados são replicados. |
| `DBtarget` | Nome do **database no destino** (IQ); muitas vezes espelha o nome lógico do database no ASE. |
| `Tipo` | Modalidade de réplica ou consumo (ex. `dbrep` para replicação clássica em IQ, `warm` para camadas “quentes” / consumo diferido conforme operação). |
| `Carga` | Perfil de atualização (ex. `NRT` — *near real-time*, ou outros códigos de batch/carga usados pela operação). |
| `Tabela` | Nome **lógico** da tabela no mapeamento de replicação (lado alinhado ao ASE / artigo publicado). |
| `TabRep` | Nome da tabela **no destino** da réplica (IQ); frequentemente igual a `Tabela`, mas pode diferir quando há renomeação no destino. |
| `RepDef` | Nome da **definição de replicação** (objeto de configuração do produto de replicação Sybase). |
| `SubName` | Nome da **subscrição** associada à definição (conjunto de artigos / fila lógica no destino). |

## Uso na lógica de match (resumo)

Os scripts derivam **chaves textuais** (ex. `DBSOURCE.TABELA`, `DBTARGET.TABELA`) e comparam com o artefato do inventário, com regras adicionais para nomes **três partes** do tipo `BANCO.DBO.TABELA` (colapso do owner `DBO` e similares). O número da linha na planilha é guardado internamente como `_rownum` para auditoria.

A leitura do `.xlsx` usa **`openpyxl`** (`requirements.txt`); o módulo partilhado `validate_table_in_vs_repmap.py` implementa `load_repmap_rows`, `repmap_derived_keys` e `match_artifact` consumidos por `migration_hints_table_in_repmap_chameleon.py`.

## Notas

- Este ficheiro **não** lista ingestões BigQuery; o caminho “datalake” passa pelo **Chameleon** nos scripts de migração.
- Manter **backup** e **controle de versão** do `RepMap.xlsx` alinhado ao ambiente operacional (DEV/HML/PRD) usado na análise.

---

*Documento gerado para apoio ao time de dados. Ajuste as descrições se a área de negócio usar convenções próprias para `Tipo` / `Carga`.*
