# Review de Tech Lead — `egps_analysis/` (extração + inventário)

> **Reviewer:** Claude (Opus 4.8), atuando como Tech Lead Data Engineer
> **Data:** 2026-06-16
> **Escopo:** scripts de **extração** (`egps_extractor.py`) e **inventário/orquestração** (`orchestrator_inventory.py`), com foco declarado em **velocidade/escala**.
> **Cadência assumida:** pipeline roda *às vezes* (quando muda algo relevante), base ~estável na ordem de **2k fluxos** → otimizações pontuais, **sem** infra de cache/incremental.
> **Status do `CODE_REVIEW.md` anterior:** parcialmente **obsoleto** (ver §1). Este documento reflete o **código atual** verificado, com referências `arquivo:linha`.

---

## 1. Veredito

A arquitetura está **certa** e não é o problema: extrator stateless por-EGP → orquestrador que monta o grafo cross-EGP + ondas topológicas → cruzamentos RepMap/Chameleon. Esse split ("extrair por arquivo" vs. "juntar entre arquivos") é exatamente o que se espera.

Dois recados de entrada:

1. **O `docs/CODE_REVIEW.md` está desatualizado em dois pontos materiais.** Ele assume **118 EGPs** — a realidade é **1.727 fluxos** extraídos (`text_egps/`), ~15× maior. E o achado 🔴 "P0" dele (join de dependências por string crua) **já foi corrigido**: hoje o join usa `_canonical_table_key` nos dois lados (`orchestrator_inventory.py:742,764`). Quem ler aquele doc vai priorizar errado. Recomendo marcá-lo como histórico.
2. Dado o foco (**velocidade/escala, roda às vezes, base ~estável em 2k**), o gargalo real **não** está na arquitetura — está em **um loop quadrático no orquestrador** e na **ausência de paralelismo no extrator**. O resto é dívida de manutenibilidade que afeta *risco de mexer*, não corretude.

---

## 2. O gargalo de performance (confirmado com números)

Escala real medida na base atual:

| Métrica | Valor real | Implicação |
|---|---|---|
| `.txt` em `text_egps/` | **1.727** (não 118) | escala ~15× maior que o review anterior assumiu |
| artefatos no relatório 06 | **81.589** | |
| `table_in` (disparam scan no Chameleon) | **20.066** | cada um varre o Chameleon linha a linha |
| linhas do Chameleon | 5.418 | |
| inventário transacional | **571.676 linhas / 37 MB** | carregado inteiro num dict no startup |

O enriquecimento do relatório 06 faz, para **cada** artefato `table_in`, uma **varredura linear** do Chameleon:

```
20.066 table_in  ×  5.418 linhas Chameleon  ≈  108 milhões de comparações  (1ª passada)
```

E a ponte RepMap (`orchestrator_inventory.py:1124-1126`) **re-varre o Chameleon inteiro por chave derivada** — multiplicando isso por 3-6×. Tudo via `is_strict_match` (comparação de string), **sem índice**. Isso é O(artefatos × linhas × chaves) — cresce mal e justifica o instinto de "escala".

A boa notícia (verificada): as regras de `is_strict_match` (`:618`) — igualdade exata, ou `cham_val` terminando em `.{membro}` — são **indexáveis pelo membro final** (segmento após o último `.`). Um dict `membro → [linhas]` transforma os 108M em **~20k lookups O(1)**, com candidatos minúsculos por chave. **Sem mudar uma linha do CSV de saída.** É o item de maior impacto/menor esforço do módulo inteiro.

Outros pontos de escala:

- **Inventário 37 MB / 571.676 linhas** carregado inteiro num dict no startup (`load_inventario_data`, `:560`). Na cadência "roda às vezes" é tolerável (custo único de alguns segundos); só viraria problema se o pipeline fosse interativo.
- **Extrator single-thread** (`__main__`, glob sequencial chamando `extract_code_from_egp`/`_sas`). É **embaraçosamente paralelo** (cada arquivo é processado isolado) — exceto pelo estado global mutável, ver §3.7.

---

## 3. Diagnóstico por boas práticas Python

Ancorando nos padrões reconhecidos (PEP 8 / PEP 257, PEP 484 type hints, módulo `logging`, `dataclasses`, `pathlib`, e tooling `ruff` / `mypy` / `black` / `pytest`):

### 3.1 Tamanho de função / Single Responsibility (🟠 a maior dívida)

- `extract_code_from_egp` (`egps_extractor.py:2757`, **~850 linhas**) e `extract_code_from_sas` (`:3615`, **~394**) somam ~28% do arquivo. Aninhamento de até ~10 níveis. Uma única função faz: abrir ZIP, parsear XML, ordenar fluxo, extrair código, embeds, exports/imports, scan I/O, montar header e **gravar o arquivo**. Viola SRP e torna a função praticamente **não-testável** (lógica e I/O acoplados).
- `orchestrator_inventory.py:main()` é uma **god function de ~590 linhas** (`:629`) que orquestra os 6 relatórios + SCC + enriquecimento, com closures (`clean_artifact`) definidas *dentro* do loop.
- Boa prática violada: funções devem fazer uma coisa; lógica pura deve ser separável da I/O para permitir teste unitário.

### 3.2 Contrato frágil entre os dois scripts (🟠 — e é o que a migração herda)

`parse_txt_metadata` (`:294`, ~190 linhas) é uma cadeia de ~22 `startswith` de prefixos-literais longos. O `.txt` é um **contrato textual não-versionado** entre extrator (escreve) e orquestrador (lê): qualquer drift de wording no header **dropa um campo silenciosamente**, e listas são split por `,` **sem escaping** — uma vírgula num nome de tabela/path corrompe a lista. Para um artefato que **alimenta a migração**, isso é frágil demais. Boa prática: serializar o intermediário num formato estruturado (JSON/JSONL) com schema versionado (`dataclass`), eliminando o parser de string.

### 3.3 Tratamento de erro (🟠 silent failures)

- `except:` **nus** no extrator (`egps_extractor.py:2888`, `:3177`...) — capturam `KeyboardInterrupt`/`SystemExit`.
- Loaders do orquestrador terminam em `except Exception: pass` (`:612` e similares) → resultado vazio, **sem diagnóstico**. Num pipeline que processa 1.727 arquivos, falhas silenciosas escondem buracos no inventário.
- Cada orquestrador no extrator é envolto num `except Exception` com `traceback.print_exc()` — engole erro por-arquivo. Boa prática: capturar exceções específicas, logar com contexto, e contabilizar falhas explicitamente.

### 3.4 Tipagem & tooling (🟡)

Praticamente **zero type hints** nos dois arquivos (PEP 484). Sem `mypy` / `ruff` / `black` / `pre-commit` aparente neste módulo (diferente do `dbt_sas_migration_assessment/`, que já tem sqlfluff+pre-commit). Para um parser regex-pesado, type hints + `mypy` pegariam classes inteiras de bug de `None`/tipo. Recomendação: `ruff` (lint+format) e hints ao menos nas funções de fronteira (`scan_sas_dependencies`, `parse_txt_metadata`, loaders).

### 3.5 Logging vs print (🟡)

Ambos usam `print()` exclusivamente — sem níveis, sem timestamp, sem redirecionamento. Para execução batch/agendada sobre 1.727 itens, o módulo `logging` (com `INFO`/`WARNING`) é o padrão. Hoje não dá para separar "progresso" de "aviso real".

### 3.6 Config & portabilidade (🟡)

Paths hardcoded e **CWD-locked**: `DEFAULT_INPUT_FOLDER`/`DEFAULT_OUTPUT_FOLDER` (`egps_extractor.py:24-25`), `INPUT_FOLDER`, `./src/...`, nomes de saída no orquestrador. CLI parseada à mão (`sys.argv`) no extrator, com flags `--eg-style`/`--clean` **documentadas como no-op** (flags mortas). Boa prática: `argparse` (o orquestrador já usa) + overrides por env/`pathlib`, para o pipeline não depender do diretório atual.

### 3.7 Estado global mutável (🟠 — e é o bloqueador do paralelismo)

`_RUN_STATS` e `_WRITTEN_OUTPUTS` (`egps_extractor.py:26-27`) são dicts mutados durante a extração (stats + detecção de colisão de nome de saída). Isso é o que **impede paralelizar trivialmente**: com `multiprocessing`, esses globais não são compartilhados entre processos → a detecção de colisão quebra e os stats se perdem. Antes de paralelizar é preciso transformar isso em valores de retorno + agregação pós-processo.

### 3.8 Duplicação (🟡)

- ~150-200 linhas de construção de header **quase idênticas** entre as duas funções de extração — candidato óbvio a `build_metadata_header()` compartilhado.
- Normalização `art.replace('`','').replace('"','')...upper()` repetida 6+ vezes no orquestrador.
- Nos scripts RepMap: dois `format_replica_primary` idênticos exceto **EN vs pt-BR** → os dois CSVs não dão para fazer join no `match_level`, e `_REPMAP_NIVEL_PT.get(lvl, lvl)` cai silenciosamente no inglês quando surge nível novo.

### 3.9 Corretude latente (registrar, decidir à parte)

- **Bug de substring** em `is_strict_match` (`:625`): `prefix in cham_val` casa qualquer coisa que *contenha* o prefixo (ex.: prefixo `"DW"` casa qualquer `cham_val` com "DW") → **falsos positivos** de match Chameleon no 06. Ao indexar, dá para isolar e corrigir — mas é mudança de comportamento, então **gate explícito**.
- **Inconsistência de chave**: `table_to_generator` usa chave canônica, mas `table_to_consumers[t]` (`:752`) usa a chave **crua** → o relatório 01 (tabelas mais consumidas) pode fragmentar contagens por caso/aspas. Resíduo da correção parcial do P0.
- Leitura de `RepMap.xlsx` por **posição** (`row[0]..row[9]`): reordenar coluna na planilha mapeia campo errado em silêncio. Trocar por lookup por nome de header.

### 3.10 Código morto / legado (🟢 limpeza)

- `OUTPUT_REPORT_7 = '07_validacao_chameleon.csv'` (`orchestrator_inventory.py:~51`) nunca é escrito — só citado no help do argparse.
- Anotações `v1`/`V6:`/`V8:` no extrator e `EGPS_EXTRACTOR_V9.md` legado → dobrar num CHANGELOG.
- `bq_connect.py` é **órfão** (zero importadores), mas contém a *melhor* fábrica de auth (`get_bigquery_client`: SA-JSON → OAuth salvo → browser → ADC), enquanto `gcp_bigquery_table_data_export.py` reimplementa uma versão mais fraca inline. Consolidar num `bq_auth.py` ou deletar.

---

## 4. Ideias de otimização da extração (foco migração)

Alinhadas ao eixo (velocidade/escala, roda às vezes — **sem** over-engineering de cache/incremental):

| # | Ideia | Impacto | Esforço | Muda saída? |
|---|---|---|---|---|
| **1** | **Indexar o Chameleon** por membro-final (dict `membro→linhas`) no enriquecimento do 06 e na ponte RepMap | 🔴 Alto — colapsa ~108M+ comparações em ~20k lookups | Baixo (~horas) | **Não** (preserva byte-a-byte) |
| **2** | **Paralelizar o extrator** com `multiprocessing.Pool` por arquivo | 🟠 Alto em wall-clock sobre 1.727+ | Médio (exige tirar estado global antes, §3.7) | Não (mesmos `.txt`) |
| 3 | **Schema versionado do `.txt`** (JSONL + `dataclass`) substituindo o parser `startswith` | 🟠 Médio — robustez do dado que a migração herda | Médio | Reformata intermediário |
| 4 | Canonicalizar `table_to_consumers` (§3.9) | 🟡 corrige contagem do relatório 01 | Trivial | Sim (relatório 01) |
| 5 | Indexar/`mmap` ou mover inventário 37 MB para parquet **só se** o startup incomodar | 🟡 Baixo nesta cadência | Baixo | Não |

**Pré-requisito de qualquer mexida:** capturar um **golden-file** dos `.txt` e dos 6 CSVs sobre a base atual de 1.727, para validar que #1/#2 são behavior-preserving e que só #4 (intencional) muda saída. Sem isso, refatorar parser regex é apostar no escuro.

---

## 5. O que tocar primeiro

Quando houver aval: **#1 (índice do Chameleon)** isolado, com golden-file e medição antes/depois — ganho enorme, risco ~zero, não altera nenhum relatório. Depois **#2 (paralelismo)**, que primeiro exige neutralizar o estado global (§3.7). O resto (#3 em diante) é dívida que vale atacar de forma oportunista, não urgência.

---

*Documento de apoio ao time de dados/migração SAS → BigQuery/Databricks. Atualize as referências `arquivo:linha` se os scripts forem refatorados.*
