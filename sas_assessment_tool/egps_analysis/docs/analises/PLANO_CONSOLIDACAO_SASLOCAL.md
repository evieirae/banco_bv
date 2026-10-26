# Plano de consolidação — tabelas SAS/Local replicadas

> **Data:** 2026-06-20 · **Base:** análise de libname-path (`ANALISE_LIBNAME_PATHS.md`) + cruzamento produtor↔consumidor.
> **Objetivo:** evitar ingerir/migrar a **mesma tabela lógica N vezes**. Cada grupo → **1 tabela canônica** no BigQuery; os demais EGPs repontam para ela.
> **Escopo:** os **95 grupos** classificados como replicação (de 236 homônimos literal-estáveis). Os **141 `multi_produtor` ficam de fora** (são tabelas distintas que só compartilham nome — não mesclar).

---

## Big numbers

| | |
|---|---|
| Grupos a consolidar | **95** (70 externa + 25 fonte única) |
| Cópias/paths redundantes a aposentar | **105** (Σ `n_paths − 1`) |
| Raio de impacto (Σ EGPs consumidores) | **470** toques de EGP |

Lista completa acionável: **`plano_consolidacao_saslocal.csv`** (membro, classe, fonte_canônica, nº paths, cópias a aposentar, EGPs consumidores, paths).

---

## Como consolidar, por classe

### 1. `fonte_unica_replicada` (25) — já há uma fonte de verdade
A tabela é **produzida por 1 path** (um EGP a gera) e **lida em outros paths** (cópias).
- **Ação:** migrar o EGP produtor como a fonte canônica (modelo dbt). As demais cópias **não viram tabela nova** — os EGPs consumidores apontam para a canônica.
- A coluna `fonte_canonica` do CSV já traz o path produtor.

### 2. `externa_replicada` (70) — referência externa copiada
Lida em N paths, **produzida em 0** dentro do corpus (vem de fora: corporativo/transacional/manual, copiada para vários libnames).
- **Ação:** **ingerir 1× só** para uma tabela canônica no BQ; todos os N consumidores repontam. Definir a fonte autoritativa externa (cruzar com Chameleon/inventário transacional / RepMap quando aplicável).

---

## Prioridade — top alvos por raio de impacto (EGPs consumidores)

| Membro | Classe | paths | EGPs | Fonte canônica |
|---|---|---:|---:|---|
| **TBPRODUCAO** | fonte única | 2 | **87** | `/projetos/misv/data/bases` |
| **TBPARCEIROCOMERCIAL** | fonte única | 2 | **67** | `/projetos/misv/data/bases` |
| **PPR_ANALITICO** | fonte única | 2 | 45 | `/infogrc/precoxrisco` |
| **TBORIGINACAO** | fonte única | 2 | 28 | `/projetos/misv/data/bases` |
| **TBINAD** | externa | 2 | 21 | (externa — ingerir 1×) |
| **FIM_DE_SEMANA** | fonte única | 5 | 19 | `/riscosbv/cobranca/erocha/ativa/tableau` |
| **DIA_UTIL** | externa | 4 | 12 | (externa — ingerir 1×) |
| **BU_NN** | externa | 2 | 12 | (externa — ingerir 1×) |
| **TBFUNILSIMULACAO_SOLAR** | externa | 2 | 12 | (externa — ingerir 1×) |
| **DMOPERACAOCREDITO** | fonte única | 2 | 8 | `/projetos/miscredito/saspdd/datamart` |

**Observação estratégica:** `/projetos/misv/data/bases` é um **hub corporativo** — `TBPRODUCAO`, `TBPARCEIROCOMERCIAL`, `TBORIGINACAO` (e os 11 aliases do mesmo path, ver análise A.1) somam centenas de leituras. Consolidar esse diretório primeiro tem o maior retorno.

---

## Sequência recomendada
1. **Hub `/projetos/misv/data/bases`** (TBPRODUCAO/TBPARCEIROCOMERCIAL/TBORIGINACAO + aliases) — maior raio.
2. Demais `fonte_unica_replicada` por ordem de EGPs (produtor já conhecido → conversão direta).
3. `externa_replicada` de maior impacto (TBINAD, DIA_UTIL, calendários) — definir fonte externa e ingerir 1×.

## Caveats (herdados da verificação adversarial)
- **`multi_produtor` (141) está fora**: são distintas; mesclar destruiria semântica (ex.: `TBPESSOA` é `CREATE`-ado independentemente em 4 paths).
- **Replicação parcial precisa olhar humano**: `DIAS_UTEIS` (6 cópias, 2 produtores) caiu em `multi_produtor` por ter 2 geradores — provavelmente é um calendário quase-replicado; revisar caso a caso antes de mesclar os limítrofes.
- `n_paths` é **teto superior** (não rastreia o binding ativo no ponto exato da leitura).
- Cobertura limitada pelos **26% de librefs não-resolvidos** (definidos via `%include`/autoexec fora da captura) — alguns grupos podem ter cópias adicionais não contabilizadas.

## Anexo
- `plano_consolidacao_saslocal.py` — script gerador.
- `plano_consolidacao_saslocal.csv` — os 95 grupos (ordenados por impacto).
