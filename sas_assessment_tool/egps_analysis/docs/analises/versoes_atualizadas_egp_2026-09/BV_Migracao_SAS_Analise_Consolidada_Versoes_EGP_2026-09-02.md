# Análise consolidada — versões atualizadas de EGP e impacto no projeto

Rodada de 01–02/09/2026. Entrada: pasta "EGP Atualizado" do SharePoint (Cobrança /
Projetos Cobrança Atualizados), 30 `.egp`, todos de Cobranças.

Artefatos desta análise: `BV_Migracao_SAS_Troca_EGP_2026-09-01.csv`,
`BV_Migracao_SAS_Plano_Troca_EGP_2026-09-01.md`, 15 markdowns por EGP,
`egps_analysis/compare_egp_versions.py`, `egps_analysis/pipeline_status_snapshot.py`,
skill `analise-egp-atualizado`.

---

## 1. Sumário executivo

> **Corrigido em 02/09 pela validação Nível 2.** Os dois parágrafos abaixo foram
> reescritos: a soma por EGP dizia "fila neutra", e o inventário reprocessado mostrou
> que a fila **cresce 32**. Ver `BV_Migracao_SAS_Validacao_Nivel2_2026-09-02.md`.

**Adotar as 30 versões novas aumenta a fila de ingestão em 32 artefatos** (6.843 →
6.875, com 91 entrando e 59 saindo). A soma por EGP dava −2 porque um input que sai de um
EGP e continua sendo lido por outro desaparece da soma e permanece na fila. A leitura de
"versão nova é mais modernizada" não se sustenta no portfólio.

O ganho existe e é menor do que a primeira leitura sugeria: **−15 arquivos de rede
distintos** a ingerir. As referências a `file_in` caem 39, o que reduz acoplamento, mas
só 15 arquivos saem da fila de verdade. Em troca entram 15 tabelas distintas.

O custo real também está concentrado, não distribuído: **três EGPs somam +37 inputs
novos** na fila, e **seis EGPs removem um output que 2 ou mais EGPs consomem**.

E há um caso de retrabalho puro: um EGP cuja versão antiga o BV formalizou como migrada
em 31/08.

Por fim, o achado que mais muda o trabalho não veio dos dados e sim do email: **a decisão
de adotar já estava tomada pelo cliente desde 21/08**. Metade do que construímos
respondia uma pergunta fechada.

---

## 2. O que foi construído

| Artefato | Função | Estado |
|---|---|---|
| `compare_egp_versions.py` | pareia novo↔antigo(s), extrai os dois lados, calcula impacto e score | funcional, 5 rodadas completas |
| `pipeline_status_snapshot.py` | snapshot read-only de `sas_egp_pipeline` (210 EGPs, 204 com etapa) | funcional |
| skill `analise-egp-atualizado` | procedimento, julgamento qualitativo, limites declarados | escrita e reposicionada |
| CSV consolidado | 30 linhas × 39 colunas | gerado |
| 15 markdowns | detalhe dos bloqueados e ambíguos | gerados |
| Plano da rodada | registro de impacto + ordem de trabalho | escrito |

Decisão de método que sustenta a confiança nos números: o script **re-extrai os dois
lados** com o extrator atual, em vez de comparar contra os `.txt` de `text_egps/`. O
extrator mudou muito nas últimas semanas (descompacta, `.sas7bdat` como tabela, regra do
criador, pass-through BQ); comparar saídas de versões diferentes mediria mudança de
ferramenta, não de EGP.

Validação cruzada independente: LOC 751→783 e churn +64/−32 do `Elegibilidade_Reneg_CP`
bateram exatamente com uma medição ad-hoc feita antes por outro caminho.

---

## 3. Impacto no inventário

Base: os 26 EGPs com score calculado (3 sem mudança, 1 par não resolvido ficam fora).

| Categoria | Antigo | Novo | Delta |
|---|---|---|---|
| `table_in` total | 806 | 788 | **−18** |
| ... que exigem ingestão | 509 | 507 | **−2** |
| ... já disponíveis no destino | 297 | 281 | **−16** |
| `file_in` (planilha/CSV de rede) | 122 | 82 | **−40** (só −15 distintos no corpus) |
| `script_in` (`%INCLUDE`) | 0 | 0 | 0 |
| outputs | 1600 | 1484 | **−116** |

A tabela acima é **soma por EGP**, útil para comparar EGPs entre si. Para projetar a
fila ela não serve, e a validação Nível 2 mostrou por quê (ver correção abaixo).

Três leituras do agregado:

**A soma por EGP dá fila neutra, e isso é uma ilusão de contagem.** −2 em 509 parecia
ruído. No inventário reprocessado a fila **cresce 32** (6.843 → 6.875), porque um input
que sai de um EGP e continua sendo lido por outro desaparece da soma e permanece na
fila. Só 59 saíram de verdade; 91 entraram. Mesma correção vale para o `file_in`: as 39
referências a menos viram só **15 arquivos distintos** fora da fila.

**Os inputs já disponíveis caem (−16), não sobem.** As versões novas leem *menos* tabela
já modernizada. Isso pesa contra a hipótese de que elas são mais modernas, e reforça a
hipótese alternativa: várias tiveram escopo cortado.

**`script_in` é zero nos dois lados, nos 26 EGPs.** Nenhum EGP de Cobranças desta
entrega usa `%INCLUDE`. O eixo de 5 pontos que criamos para premiar redução de
acoplamento de código é peso morto nesta área — não é errado, é inaplicável aqui.

### 3.1 O custo concentrado

| EGP | Inputs a ingerir | Outputs |
|---|---|---|
| `Elegibilidade menor que 90_GCP_v4` | 25 → **43** | 168 → 209 |
| `CartoesAmigaveis_PilotoAcordos_20260710` | 12 → **25** | 134 → 151 |
| `Elegibilidade_Gradativo_20251103_reap_v26` | 19 → **25** | 117 → 172 |

+37 inputs concentrados em três EGPs. Sob o direcionamento do cliente eles serão
adotados de todo modo, então isso é **demanda nova de ingestão** a planejar, não uma
decisão a tomar.

### 3.2 O ganho concentrado

Quatro EGPs zeram ou quase zeram `file_in`: `NuContratoContabil_Atualizado` (4→0),
`Estrategia_Reneg_Solar_180_v20251117_GCP_PJ` (3→0), `Elegibilidade_Reneg_CP` (2→0) e
`CARTA_EGV_2026` (9→2). Junto com `PROJECT_ATIVA` (4→1), explicam a maior parte dos −40.

---

## 4. Impacto no risco

### 4.1 Seis outputs desaparecem com consumidor externo

| EGP novo | Output removido | Consumidores |
|---|---|---|
| `PERFORMANCE_CL_202608_GCP` | `PERF_CL.CL_TABLEAU` | 7 |
| `Performance_Saldo_COLORE_…_Lite_V5` | `PAGOSCBR.PAGOS_CYBER_202603` | 3 |
| `PROJECT_ATIVA_TABLEAU_NEW_RPA` | `ATIVA.BASE_ATIVA_202510` | 2 |
| `Oportunidade Protesto_20260703` | `KEVIN.PUBLICO_PROTESTO_20260210` | 2 |
| `Campanha_Entrega_amigavel_v4_mensal_gcp` | `ENTREGA.BASE_ELEG_110226` | 2 |
| `processo_carga_score_solar_jul_26_REAPONTADO_PJeOFENS` | `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211` | 2 |

São 18 pares consumidor→tabela em risco. `PERF_CL.CL_TABLEAU` com 7 consumidores é o
mais grave e está no EGP de maior alcance da entrega.

Este é exatamente o levantamento que o direcionamento do BV de 21/08 exige ("avaliar os
impactos nas dependências downstream [...] manter o registro das dependências
identificadas"). É a parte da análise que está no alvo do que o cliente pediu.

### 4.2 Retrabalho de conversão

`Project_Compensacao_Encargos_v1`: antecessor em etapa `Validação da Área`, status `Em
Andamento`, e em 31/08 o BV formalizou a entrega dele migrado para dbt/BigQuery
(email de int.jtargino). Adotar a versão nova joga fora conversão concluída e validada.

Vale registrar que este veto foi produzido pelo mecanismo antes de eu saber do email de
formalização — o snapshot de `sas_egp_pipeline` pegou o caso sozinho. É a evidência mais
forte de que o veto por etapa/status funciona.

### 4.3 Risco que o modelo não mede

Nos quatro EGPs de maior prioridade, inputs e outputs caem juntos, e em três os inputs
já disponíveis também caem. Modernização, divisão do EGP em dois e corte de escopo
produzem exatamente a mesma assinatura numérica. Um dos quatro se chama literalmente
"Reduzido"; o `NuContratoContabil` sai de 183 para 24 outputs.

**O score não distingue "melhorou" de "faz menos".** Enquanto a área não confirmar
equivalência funcional, os quatro Valores altos desta rodada são hipóteses, não
conclusões.

---

## 5. Impacto no escopo e na contagem de EGPs

Quatro EGPs novos substituem mais de um antigo. Se as consolidações se confirmarem, o
corpus perde **6 EGPs** além dos 26 substituídos um-a-um.

| EGP novo | Substitui | Confirmado |
|---|---|---|
| `PROJECT_ATIVA_TABLEAU_NEW_RPA` | `_V2_4_vigente` + `PROJECT_ATIVA_GCP_V2` | **sim**, email BV 26/08 |
| `PERFORMANCE_CL_202608_GCP` | `PERFORMANCE_CL_202603` + `_202603_REPROC_HIST_EDU` | não |
| `Acompanhamento_Desconto - Painel_vK` | `Painel_vK` + `Painel_VE2` | não |
| `NuContratoContabil_Atualizado` | 4 EGPs da família contábil | **duvidoso** |

Isso mexe em contagem de escopo, no plano do mês e nos funis — não é só substituição de
arquivo. Antes de aplicar, as três não confirmadas precisam de resposta da área.

O caso do `NuContratoContabil` é o mais frágil: 4 EGPs consolidados, exatamente no teto
do detector, numa família que compartilha um preâmbulo de macros grande. É o candidato
mais provável a falso positivo, e é justamente ele que aparece com o maior Valor da
rodada (59,6) — porque a união dos quatro infla o lado "antigo".

---

## 6. Impacto no processo

O que antes era conferência manual por nome e tamanho virou procedimento reprodutível:
pareamento por hash de código, extração simétrica, impacto downstream calculado e
registro versionado por data. Toda entrega futura de "EGP Atualizado" passa pelo mesmo
caminho, e o resultado é comparável entre rodadas — foi por isso que fixamos os cortes de
quadrante em vez de recalibrar a cada rodada.

Três parâmetros de política ficaram registrados no código com data e motivo: os cortes
20/20, o estreitamento dos dois vetos e o corte de co-antecessor em 0,60.

O que **não** foi absorvido: nada disso entrou no Databricks nem no app. Foi decisão
consciente — é dado de decisão pontual, não de acompanhamento diário. Se virar rotina
mensal, promove.

---

## 7. O que mudou no nosso entendimento

Cinco coisas que eu afirmei ou assumi e que se revelaram erradas no curso do trabalho:

1. **"A troca é decisão nossa."** Era do cliente, e estava tomada desde 21/08: adota-se a
   versão vigente sem comparação histórica detalhada. Metade do que construímos (o eixo
   Valor/Esforço como aprovação) responde pergunta fechada; a outra metade (impacto
   downstream) é exatamente o que foi pedido.
2. **"`NuContratoContabil_Atualizado` é o único EGP inédito."** Tem 92% de tasks
   idênticas ao `Fechamento_Contabil_RPDD_3040`. É variante, não novidade.
3. **"`Project_Atualiza_Bases_Auxiliares` tem antecessor claro."** 31% de overlap,
   abaixo do corte. Antecessor desconhecido; é pergunta para a área.
4. **"Cada versão nova substitui um antigo."** O BV confirmou por escrito um caso de
   1-para-2. O modelo 1:1 escondia um output com 2 consumidores externos.
5. **"Caminho de rede novo é regressão."** É o estado normal do corpus. Vetava 6 de 30
   por version bump de planilha.

Os itens 2 e 3 estavam numa mensagem já enviada à liderança e foram corrigidos lá.

---

## 8. Limites do que foi construído

- **Alerta de área diferente é inerte:** `sas_egp_pipeline` não tem coluna `area`, e a
  área do EGP novo é inferida da pasta do antecessor.
- **LOC pode vir inflado por MPRINT** gerado dentro do `code.sas`: o `PROJECT_ATIVA`
  reporta ~1,65 milhão de linhas. O eixo de churn dele não significa nada.
- **Alcance depende de CSV possivelmente defasado** (`01_prioridade_ingestao.csv`,
  `03_matriz_dependencias.csv` da árvore atual).
- **Piso de ruído satura eixos pequenos:** `file_in` 2→0 entrega 25 pontos cheios.
- **`script_in` é inaplicável em Cobranças** (zero nos dois lados, nos 26).
- **O Nível 2 rodou em 02/09** e corrigiu duas conclusões desta análise (fila e
  `file_in`). Os números de fila, dependência e escopo agora são observados. Os deltas
  por EGP das seções 3.1 e 3.2 continuam sendo soma por EGP, que é a medida certa para
  comparar EGPs entre si, mas não para projetar a fila.
- **Detector de consolidação erra para cima** em famílias com boilerplate comum. O teto
  de 3 e o alerta limitam o dano, mas não o eliminam (ver `NuContratoContabil`).

---

## 9. Decisões pendentes

**Para a área (um bloco só):**
1. Os 6 outputs removidos foram renomeados ou extintos?
2. As 3 consolidações não confirmadas são reais?
3. Qual o antecessor do `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB`?
4. Os 4 EGPs de maior prioridade fazem o mesmo trabalho que os antigos, ou tiveram
   escopo cortado?

**Para a liderança:**
5. O que fazer com o `Project_Compensacao_Encargos_v1`, cuja versão antiga já foi
   entregue migrada.

**Interno:**
6. Rodar o Nível 2 com os liberados juntos (só se sobrarem 3 ou mais).
7. Planejar os +37 inputs novos na próxima onda de ingestão.
