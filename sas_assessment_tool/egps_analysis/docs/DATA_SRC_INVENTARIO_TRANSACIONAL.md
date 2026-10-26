# Inventário `src/inventario_transacional.csv`

## O que é

Ficheiro **CSV** de inventário **corporativo** de objetos (em especial **tabelas**) em bases **transacionais** e outros SGBDs, organizado por fabricante, database e nome do objeto. É uma visão ampla de **o que existe** nos ambientes de origem, não apenas Sybase.

## Para que serve no pipeline

- **`orchestrator_inventory.py`** — quando o artefato no relatório 06 **não** é BigQuery nativo no EGP **e** **não** há match no Chameleon, o orquestrador tenta um **match exato** da chave `DATABASE.OBJETO` (normalizado em maiúsculas) contra este inventário. Se encontrar, preenche o `source_type` com o valor da coluna de SGBD (ex. `SYBASE_ASE`) e o `status_validacao` com mensagem de inventário transacional.

- **`migration_hints_table_in_repmap_chameleon.py`** **não** consome diretamente este ficheiro; o cruzamento “Sybase + RepMap” usa o Chameleon filtrado e o `RepMap.xlsx`.

## Formato

- Delimitador: vírgula (o orquestrador também tolera `;`, tab ou `|` via *sniff*).
- Primeira linha: cabeçalho.
- Volume típico: muitas linhas (dezenas ou centenas de milhares), incluindo objetos de sistema em alguns SGBDs.

## Colunas

| Coluna | Descrição |
|--------|-----------|
| `detalhamentoFabricanteSGBD` | Fabricante ou família do motor (ex. `Mysql`, `Sybase`, `Oracle`). Identifica o “tipo” de plataforma na nomenclatura do inventário. |
| `tipoObjeto` | Tipo de objeto no database (ex. `table` para tabela). Permite filtrar apenas tabelas se necessário. |
| `dataBase` | Nome do **database** ou *schema* de primeiro nível onde o objeto reside (ex. `DBCOR`, `information_schema`). |
| `nomeObjeto ` | Nome do **objeto** (ex. nome da tabela). *Nota: no ficheiro original o cabeçalho pode incluir um espaço final (`nomeObjeto `); em importações use o nome exato do CSV ou normalização.* |
| `bd` | Etiqueta de **instância / SGBD** ou agrupamento lógico associado à linha (ex. `Mysql`, `Sybase`). Usada pelo orquestrador como valor de `source_type` quando há match exato com o artefato. |

## Chave de match no orquestrador

O script constrói chaves do tipo **`DATABASE.NOMEOBJETO`** em maiúsculas (com `nomeObjeto` sem espaços à direita no valor) e compara com o **artefato** do inventário SAS já normalizado (ex. `DBCOR.TBCLIENTE`).

## Limitações

- **Match exato**: diferenças de nome, case ou database entre o EGP e o inventário impedem o match.
- Linhas de **information_schema** e catálogos de sistema podem aparecer no ficheiro; nem todas são relevantes para migração de aplicações.

---

*Documento gerado para apoio ao time de dados. Alinhe com a fonte oficial do inventário transacional se os nomes das colunas forem alterados no export.*
