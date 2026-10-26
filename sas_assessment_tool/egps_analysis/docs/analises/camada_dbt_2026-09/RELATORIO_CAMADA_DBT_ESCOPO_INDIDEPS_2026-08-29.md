# Camada dbt provável de cada EGP do escopo indi + deps

**Data:** 2026-08-29 · **CSV pareado:** `BV_Migracao_SAS_Camada_DBT_Escopo_IndiDeps_2026-08-29.csv`
**Base:** frontier `indi_deps` reconstruído de `bv_dev_db.monitoramento_sas` (mesma regra
do app: `escopo_indi = true` ∪ fecho transitivo upstream sobre arestas podadas por
produtor canônico e vias resolvidas, sem expandir despriorizados) · contagens de
tabelas do inventário local (`05_prontidao_egp.csv`)

## Pergunta

Para cada EGP do escopo, em qual camada dbt o **modelo final** dele tende a cair —
`stg`, `int` ou `mart`? A classificação é **estrutural**, pela posição do EGP no
subgrafo vivo do escopo:

| Camada | Critério no grafo |
|---|---|
| `stg` | Só lê fonte bruta (nenhum produtor EGP vivo a montante) **e** alimenta outros EGPs do escopo |
| `int` | Consome output de outros EGPs **e** é consumido — meio da malha |
| `mart` | Terminal: tem upstream mas ninguém consome o que ele gera |
| `mart (isolado)` | Nem depende de EGP nem alimenta EGP — pipeline ponta-a-ponta; a conversão gera a cadeia `stg → int → mart` inteira dentro dele, com o modelo final sendo mart |

## Escopo analisado

- **185 EGPs** = 168 indicados (`escopo_indi`) + 17 dependências transitivas.
- **184 de Cobranças** + 1 de Riscos (dependência).
- Poda de arestas: 1.815 brutas em prod → 1.539 vivas após remover vias já
  Modernizadas/Sanitizadas (1.792 tabelas resolvidas) e a escolha de produtor
  canônico (9 choices, nenhuma aresta removida por elas neste corte).
- **57 dos 185 estão Despriorizados e Contabilizados** — seguem no escopo (base do
  plano), mas não puxam dependências.

## Resultado geral (185 EGPs)

| Camada final | Total | Despriorizados | **Ativos (backlog vivo)** |
|---|---:|---:|---:|
| mart (isolado: stg→mart no mesmo EGP) | 78 | 23 | **55** |
| mart | 52 | 19 | **33** |
| stg | 32 | 10 | **22** |
| int | 23 | 5 | **18** |
| **Total** | **185** | **57** | **128** |

Leituras:

- **~70% do escopo termina em mart** (isolados + terminais), nos dois recortes —
  o escopo de Cobranças é majoritariamente relatório/entregável final.
- No backlog **vivo** (128 EGPs), a proporção se mantém: 88 marts (69%),
  22 stg (17%), 18 int (14%).
- Das **17 dependências** puxadas para o escopo, 13 são `stg` e 4 são `int` —
  nenhuma é terminal (esperado: dependência existe porque alguém a consome).
  Dessas, 4 estão despriorizadas.

## Efeito da despriorização

A despriorização **não cascateia** (regra do app: `no_expand` — despriorizado não
puxa dependência, mas dependência compartilhada com EGP vivo permanece). Dois
pontos de atenção derivados disso:

### 1. Despriorizados que ainda seguram EGPs vivos

**15 EGPs despriorizados ainda têm consumidores vivos no escopo.** Despriorizar o
EGP tira ele do backlog de conversão, mas os dados que ele produz continuam sendo
pré-requisito de quem ficou — essas vias precisarão ser resolvidas por outra rota
(modernização do input, sanitização ou reativação do EGP):

| EGP despriorizado | Camada | Consumidores vivos |
|---|---|---:|
| `Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU` | int | 4 |
| `Cobranças__Performance Solar` | stg | 4 |
| `Cobranças__Project_Atualiza_Base_Hash_BV` | int | 3 |
| `Cobranças__Programa_verificacao` | int | 3 |
| `Cobranças__Project_Atualiza_Base_Propensao_Digital_Reapontamento_GCP` | stg | 3 |
| `Cobranças__Project_Atualiza_Base_Propensao_Digital_Reapontamento_Kraken` | stg | 3 |
| `Cobranças__Projecao_RPDD_4966_Filtrado` | int | 2 |
| + 8 EGPs com 1 consumidor cada (ver CSV) | stg/int | 1 |

### 2. O que a despriorização já economizou

Os 57 despriorizados removem do backlog 23 pipelines ponta-a-ponta e 19 marts
terminais — trabalho que sai limpo, sem efeito colateral no grafo. Já os
15 da tabela acima são "saída suja": o EGP sai, a obrigação de dado fica.

## Hubs do backlog vivo (por onde começar)

**`int` mais crítico** — `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH`:
12 upstream + **21 consumidores** vivos. É o centro da malha do escopo; convertê-lo
(ou modernizar suas saídas) destrava a maior fatia do backlog.

**Melhores candidatos a `stg_*` compartilhado** (sem upstream vivo, muitos consumidores):

| EGP | Consumidores vivos | Nível |
|---|---:|---:|
| `Cobranças__PERF_AMIGAVEL_gcp` | 13 | dependência |
| `Cobranças__ACORDO_AMIGAVEL_v1__v2` | 10 | dependência |
| `Cobranças__Project_Atualiza_Lista_Restrita` | 10 | indicado |
| `Cobranças__Construcao_carteira_Risco` | 7 | indicado |
| `Cobranças__CPF_Contrato__v2` | 5 | indicado |

**Marts mais pesados** (mais upstream vivo — últimos da fila natural):
`Performance_Produtos_V1` (11 upstream), `PROJECT_LINHAS_QIKVIEW_V5_RPA`,
`Painel_Desconto_3040_Edu`, `Project_Jornada_e_Mailing_RENEG_EPS_ADIMP_INAD` e
`Simulação_Cenários_Proposta - Reapontado` (4 cada).

## Verificação: EGPs do escopo com 0 outputs no monitor (2026-09-02)

**23 EGPs do escopo não têm nenhuma linha em `sas_egp_outputs`** (19 ativos + 4
despriorizados: `2.Mix_Pagamentos_Geral`, `Avaliacao_modelos_v3`,
`Apuracao_Performance_safrada_v3`, `Valida_recebimentos_nov24`). Todos indicados,
todos de Cobranças; na classificação, 14 "mart isolado" e 5 "mart" terminal.
Hipótese verificada: haveria output comentado no código.

**Método**: a verificação teve de ser feita nos `.egp` **brutos** — o extractor
remove comentários SAS do interior das tasks ao gerar o `.txt`
(`remove_sas_comments`, `egps_extractor.py:3184`), então output comentado nunca
aparece no texto extraído. Task viva × morta separada pela presença do diretório
da task no `.txt` (fluxo do `project.xml`).

Resultado em 4 grupos:

**A) Output comentado em task VIVA — 5 EGPs (hipótese confirmada):**

| EGP | Escrita comentada |
|---|---|
| `2.Mix_Pagamentos_Geral` / `2_Mix_..._202511 V2` | `/*DATA CARNEIRO.PARCELAMENTO_FATURA_2023_2024;*/` (após `LIBNAME CARNEIRO` ativo) |
| `3.Performance_Assessoria_COMPLETO` | mesma tabela |
| `Painel_Desconto_3040_Edu` | `/*DATA CARNEIRO.BASE_COBRANCA_HIST;*/` — o passo vivo ainda **lê** essa tabela |
| `Carteira_CA_COMPLETA_GCP_2` | `CARNEIRO.CARTEIRA_CA`, `CARTEIRA_CA_20260121`, `CARTEIRA_CA_BACKUP` |

Padrão: o analista materializava um snapshot permanente e comentou o passo. A
extração está correta em não contar como output; para a migração, as tabelas
`CARNEIRO.*` existem no disco como snapshot congelado e podem ter consumidores.

**B) Output ativo descartado no publish — 1 EGP (caso mais relevante):**
`Reneg_Over30e90_Ever30_v2` grava de verdade `MARCACAO.CUBO_OVER30_&SAFRA_M1` e
`MARCACAO.CUBO_OVER30_MAIOR90_&SAFRA_M1` em task viva. O extractor captura
(estão em `PERMANENT OUTPUTS` no txt e no `02_entregaveis`), mas o guard
`'&' in a` (macro não expandida) descarta no caminho para o app. **EGP com
output real, invisível no monitor.** Fix candidato (revisado 2026-09-02):
**publicar o padrão com placeholder** — `MARCACAO.CUBO_OVER30_{SAFRA_M1}` —
como o lado de leitura já faz (`DYNAMIC REFS`). NÃO resolver a macro para um
mês concreto: o output é **safrado** (família de tabelas), e o nome resolvido
mudaria a cada Processar (chave instável → re-key, perda de status humano) e
representaria mal o artefato lógico, que em dbt vira **um** modelo incremental
particionado por safra. O placeholder dá chave estável, 1 linha = 1 modelo
futuro, e habilita arestas produtor↔consumidor safrado que hoje nunca casam.
Irresolvíveis continuam descartados, mas logados. (Consolidar famílias com
data **literal**, ex. `BASE_3040_2026xx`, é mudança de identidade corpus-wide
— fica fora deste fix.)

**C) Escrita persistente só em task MORTA — 7 EGPs:** `SELECAO_RECORRENTE_GCP`
(5), `Simulação_Cenários_Proposta - Reapontado` (7), `Performance_Produtos_V1`,
`Safra e Carteira Ajuizamento Reapontado`, `CODIGO_PERFORMANCE_DU`,
`Performance Safrada Fase Ativa - Agente IA`, `Projeção_Rolagem_Mai26`
(só comentada). Atenção ao `SELECAO_RECORRENTE_GCP`: as tasks mortas gravam
`RENEG.RENEG_TESTE_ACAO_*` que o fluxo **vivo lê** — produtor saiu do fluxo,
consumo ficou (provável execução manual da task fora do fluxo).

**D) Nada em lugar nenhum — 10 EGPs:** `Avaliacao_modelos_v3`,
`ACOMPANHAMENTO_DESCONTO`, `Analise_mix_vulneraveis`,
`Apuracao_Performance_safrada_v3`, `Apuracao_recorrente_GCP`,
`Diagnostico_divergencias_encargos20250904`, `Entrada_em_Cob_Intra`,
`Entrada_em_Cob_intrames`, `Valida_recebimentos_nov24`, `Valida_score_v2`.
Consultivos puros: tudo morre em WORK e o entregável é a grade de resultado no
EG (ou export manual não persistido). Classificação "mart consultivo" correta.

Encaminhamento: verificação manual dos 5 do grupo A (+ Reneg e SELECAO) pedida
ao Marlon via Slack em 2026-09-02 — abrir os `.egp` no Enterprise Guide e
confirmar com a área se as tabelas comentadas ainda são o entregável oficial
ou viraram snapshot morto.

## Caveats

- Classificação **estrutural, não semântica**: um `stg` com transformação pesada
  pode merecer modelos `int` na conversão; todo mart isolado ainda gera seus
  próprios `stg_*` internos no draft (layout flow-only do converter).
- O grafo usado é o **vivo** de prod: via já Modernizada/Sanitizada não conta como
  dependência. Um EGP que era `int` na malha histórica pode aparecer aqui como
  `stg` ou `mart isolado` — é a visão do trabalho que resta, não do lineage original.
- Snapshot de 2026-08-29; o frontier muda a cada status editado no app
  (despriorização, modernização de input, vínculo quebrado).

## Reprodução

1. Queries read-only em `bv_dev_db.monitoramento_sas` (`sas_lineage_nodes`,
   `sas_lineage_edges`, `sas_output_producer_choice`, `sas_inputs_monitor`,
   `sas_egp_pipeline`), warehouse `5922c26f81f1bbdd`, profile `bv`.
2. Replicar `_prune_edges` + `_filter_vias_resolvidas` + `_transitive_upstream`
   (com `no_expand` = despriorizados) de `app/backend/main.py`.
3. Classificar cada EGP do frontier pelo grau de entrada/saída no subgrafo
   induzido; juntar contagens do `05_prontidao_egp.csv`.

Colunas do CSV pareado: `Projeto`, `Area`, `camada_dbt`, `dep_nivel` (0 = indicado,
≥1 = distância da base), `origem_escopo`, `despriorizado`, `upstream_no_escopo`,
`downstream_no_escopo`, `qtd_tabelas_geradas`, `qtd_arquivos_exportados`.
