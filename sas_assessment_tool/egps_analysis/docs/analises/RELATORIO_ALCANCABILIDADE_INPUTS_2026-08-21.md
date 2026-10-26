# Inputs que a lógica lê mas não aplicam em nenhuma saída — verificação por alcançabilidade

**Data:** 2026-08-21 · **Continuação de:** `RELATORIO_INPUTS_NAO_USADOS_2026-08-18.md`
**Base:** 1.741 EGPs extraídos (`text_egps/`) · recorte do plano vigente (193 EGPs:
escopo Indicium + dependências + ex-dependências, lido de `bv_dev_db.monitoramento_sas`)

## Resumo

O estudo de 18/08 respondeu por **proveniência**: o input só aparecia num `x cp`/`gunzip`,
nunca num `SET`/`FROM` — 321 casos no corpus. Este responde a pergunta mais forte, de
**alcançabilidade**: o input É lido de verdade, e o conteúdo dele desemboca em alguma saída
do EGP, ou morre num WORK que ninguém mais usa?

Resultado: **126 pares (EGP × tabela) confirmados sem uso**, em 28 EGPs — desses, **72
ainda pendentes** na fila, e a pendência desses EGPs cai de **600 para 528 (−12%)**.
28 dos 72 são exclusivos: nenhum outro EGP do plano os consome, então somem do corpus.

O resultado colateral é maior que o principal: **31 EGPs do plano não têm cadeia de dados
que termine em saída nenhuma** — 507 pares de input parados —, e 29 deles são
`DATA_TRANSFORMATION` na classificação do extractor. O indício aponta para **entrega por
task wizard do Enterprise Guide**, que não deixa código. Esses 507 **não** entram em
nenhuma lista de desvinculação.

## Como a verificação funciona

`docs/analises/alcancabilidade_inputs.py` monta, por EGP, um grafo de fluxo de dados sobre
o corpo do `.txt` com macros `%let` expandidas (reaproveita o splitter de passos e o
expansor de macros de `auditoria_ordem_codigo.py`):

- **nós** = datasets, WORK inclusive; **arestas** = passo que lê A e escreve B;
- **sinks** (o que conta como saída): escrita em lib permanente (inclui `INSERT INTO` de
  pass-through), `PROC EXPORT`/`OUTFILE=`/`DATA _NULL_` com `FILE`+`PUT`, proc de relatório
  sem `OUT=` (entregável legítimo de EGP consultivo) e **macro-variável**
  (`CALL SYMPUT`/`INTO :`, que parametriza o resto do fluxo);
- **alcançabilidade por ponto fixo** de Kleene, não por memoização — ver §Validação.

| Veredito | Pares | % |
|---|---:|---:|
| `ALCANCA_OUTPUT` | 2.026 | 43,7% |
| `NAO_ALCANCA` | 812 | 17,5% |
| `EGP_SEM_OUTPUT` | 619 | 13,3% |
| `NAO_LOCALIZADO` (macro / wizard / `%INCLUDE`) | 585 | 12,6% |
| `NAO_DECIDIVEL_MACRO` | 429 | 9,2% |
| `SO_RELATORIO` | 90 | 1,9% |
| `ALIMENTA_MACRO_VARIAVEL` | 48 | 1,0% |
| `METADADO_SAS` (`SASHELP.V*`) | 26 | 0,6% |
| `MACRO_NAO_CHAMADA` | 3 | — |
| **Total** | **4.638** | |

## O total bruto não é a resposta: partição por cobertura do EGP

`cobertura` = alcançam / (alcançam + não alcançam), só sobre o decidível.

| Cobertura do EGP | EGPs | pares `NAO_ALCANCA` | Leitura |
|---|---:|---:|---|
| 100% | 66 | 0 | sanidade do grafo |
| 80–99% | 28 | **126** | **input é outlier num EGP produtivo → candidato real** |
| 50–79% | 22 | 179 | zona cinzenta — precisa amostragem |
| <50% | 31 | 507 | a cadeia do EGP morre em WORK → pergunta é sobre o EGP |

Input morto dentro de um EGP que comprovadamente produz é achado. Input morto dentro de um
EGP que não produz nada é o EGP, não o input.

## Validação

**Auditoria independente do grafo:** para cada um dos 126, o nó terminal da cadeia foi
procurado por regex em posição de leitura (`SET`/`FROM`/`JOIN`/`DATA=`/`BASE=`) em qualquer
ponto do código, com guardas para nome curto e WORK homônimo do input permanente.
**125 de 126 confirmados**; 1 residual para o golden set.

Quatro defeitos foram encontrados **pela própria auditoria**, todos produzindo falso
"input morto" — registrados porque um "fix" futuro pode reintroduzi-los:

1. **Memoização com guarda de ciclo cacheava resultado parcial**: em EGP com acumulador
   (`DATA X; SET X;`) o veredito passava a depender da ordem de travessia. Trocado por
   ponto fixo.
2. **Nomes BQ de 3 partes com hífen** (`BV-PDBD-PRD.DVRY_CORE.TBCONTRATO`) eram descartados
   no parse — 55% do `NAO_LOCALIZADO` (2.027 → 585).
3. **Splitter cortava só em início de linha**: `data`/`proc` depois de `;` era absorvido no
   passo anterior e o `SET` dele se perdia.
4. **`CALL SYMPUT`/`INTO :` não era sink**: `DATA _NULL_; SET X; CALL SYMPUT(...)` não
   escreve dataset, mas o conteúdo sai por macro-variável — 48 falsos-mortos.

## Impacto em produção

| | |
|---|---:|
| Pares confirmados sem uso | 126 |
| Presentes no inventário de produção | 126 |
| Já com vínculo quebrado (sem ganho) | 6 |
| **Pendentes ("A Receber")** | **72** |
| Exclusivos (nenhum outro consumidor ativo no plano) | 28 |
| Pendência dos 28 EGPs | **600 → 528 (−72, −12%)** |
| EGPs que zeram a pendência | 0 |

Os 72 pendentes são todos tabela: 59 `SAS/Local (externo)` e 13 `SAS/Local (dependência)`.

Maiores efeitos por EGP (pendências antes → depois):

| EGP | antes → depois |
|---|---|
| `processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` | 19 → 6 |
| `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` | 35 → 25 |
| `Fase Administrativa - Novo Processo_v20260227_GCP` | 77 → 66 |
| `Processo_NPS_UNICO_Novo_produto` · `Processo_NPS_UNICO_SEG_DIG` | 29 → 23 · 28 → 22 |
| `PERFORMANCE_CL_202603` | 9 → 4 |
| `14.PROTESTO_SELECAO_PUBLICO` | 15 → 11 |
| `SALDO_ALTOS_+_PE_20260224 - Reapontado_VF` | 9 → 6 |

> Cálculo sobre o grafo bruto de produção, sem a poda de produtor canônico/vias resolvidas
> que o app aplica: o **delta** é o que vale, não o absoluto.

## O achado colateral: ponto cego do lado da SAÍDA

`Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5` tem 56 KB de código, 116 passos, só
`PROC SQL` e `PROC SORT`, e **dois** outputs permanentes; todo o resto vai para WORK
(dezenas de linhas em `TEMP/DISCARDED OUTPUTS`). Os dois últimos passos do fluxo se chamam
`QUERY_FOR_PERF_AMG1` e `QUERY_FOR_CUBO_PERFORMANCE_SALDO` — `QUERY_FOR_*` é o nome default
que o **Query Builder do EG** dá ao resultado da task. No corpus: **344 EGPs com 2.761
tabelas `QUERY_FOR_*`**.

Verificação da hipótese contrária, antes de concluir: `OPTIONS USER=<lib>` faria nome de um
nível resolver em biblioteca permanente em vez da WORK — **zero ocorrências no corpus**.
Logo o WORK é WORK mesmo, e a entrega desses EGPs é grade na interface ou planilha
exportada pela configuração da task, invisível para qualquer análise de código.

Consequência prática: para os 31 EGPs de cobertura baixa a pergunta é **"qual é a entrega
deste EGP?"**, com o dono — e não "este input é dispensável?".

## Fila que o código não decide

| Bloco | Pares | Motivo |
|---|---:|---|
| `NAO_LOCALIZADO` | 585 | nome só existe resolvido em runtime, ou import/export de wizard |
| `NAO_DECIDIVEL_MACRO` | 429 | destino da escrita só existe via macro |
| `file_in` do recorte | 818 | fora desta passada — mesmo ponto cego de 18/08 |

São **1.014 pares** de tabela + 818 de arquivo. É esse o tamanho real do trabalho manual (ou
de leitura assistida por agente), e ele só ficou conhecido depois da passada determinística.

## O que fazer

1. **Desvincular** os 72 pendentes pelo mecanismo que já existe (vínculo por EGP+input) —
   sai da fila sem apagar nada. Os 6 já quebrados dispensam ação.
2. **Emitir as tasks de wizard no extractor** (import *e* export; o par arquivo→tabela está
   no `project.xml`). Destrava os dois pontos cegos de uma vez.
3. **Pauta com os donos** dos 31 EGPs de cobertura baixa: qual é a entrega.
4. Amostrar a zona cinzenta (22 EGPs, 179 pares, cobertura 50–79%).

## Anexos

- `alcancabilidade_inputs.py` — grafo e veredito (fase 1)
- `impacto_alcancabilidade.py` — impacto em produção (fase 4)
- `BV_Migracao_SAS_Alcancabilidade_Inputs_2026-08-21.csv` — 4.638 pares com veredito e evidência
- `BV_Migracao_SAS_Alcancabilidade_Por_EGP_2026-08-21.csv` — cobertura por EGP
- `BV_Migracao_SAS_Alcancabilidade_Impacto_Prod_2026-08-21.csv` — os 126 com etapa, vínculo e consumidores
