# Impacto da adoção dos EGPs atualizados — rodada de 2026-09-01

Entrega do BV: pasta **"EGP Atualizado"** (SharePoint, Cobrança / Projetos Cobrança
Atualizados), 30 `.egp`, todos de Cobranças. Este doc registra a rodada; o procedimento
reutilizável está na skill `analise-egp-atualizado`.

Dados: `BV_Migracao_SAS_Troca_EGP_2026-09-01.csv` (30 linhas, 39 colunas) e os markdowns
`BV_Migracao_SAS_Troca_<egp>_2026-09-01.md`.

## A adoção já está decidida

Direcionamento do BV em 21/08/2026 (Michelli Martins, "Alinhamento EGPs com Novas
Versões | Direcionamento para a Migração SAS"):

> "as versões mais recentes aprovadas pelo negócio serão adotadas como referência
> oficial, **sem a necessidade de comparações detalhadas com versões anteriores**."

E, no mesmo email, o que passa a ser exigido:

> "avaliar os impactos nas **dependências downstream** [...] será utilizada a
> rastreabilidade e a linhagem já disponível"
> "**Manter o registro das dependências identificadas** para suportar as próximas ondas"

Portanto este doc **não decide se troca**. Ele é o registro de impacto que o
direcionamento manda manter, mais a ordem de trabalho. Os nomes dos quadrantes ainda
dizem "Trocar / Não trocar" porque vêm da especificação original; leia-os como
prioridade e risco.

## Resultado

| Quadrante | Qtd | Leitura |
|---|---|---|
| Trocar agora | 4 | adotar primeiro: reduzem a fila de ingestão |
| Não trocar (veto) | 7 | **não produtizar antes de resolver o impacto** |
| Trocar depois | 12 | adotar na vaga seguinte: inventário praticamente igual |
| Não trocar | 3 | adotar com cautela: **aumentam** a fila de ingestão |
| Sem mudança (descartar) | 3 | código idêntico ao corpus |
| Par não resolvido | 1 | antecessor desconhecido |

## 1. Impacto downstream (o que o cliente pediu)

### 1.1 Outputs que desaparecem e têm consumidor externo

Seis EGPs removem um output consumido por 2 ou mais EGPs do corpus. Cada um é uma
quebra em potencial e precisa de confirmação da área antes da produtização.

| EGP novo | Output removido | Consumidores |
|---|---|---|
| `PERFORMANCE_CL_202608_GCP` | `PERF_CL.CL_TABLEAU` | 7 |
| `Performance_Saldo_COLORE_…_Lite_V5` | `PAGOSCBR.PAGOS_CYBER_202603` | 3 |
| `PROJECT_ATIVA_TABLEAU_NEW_RPA` | `ATIVA.BASE_ATIVA_202510` | 2 |
| `Oportunidade Protesto_20260703` | `KEVIN.PUBLICO_PROTESTO_20260210` | 2 |
| `Campanha_Entrega_amigavel_v4_mensal_gcp` | `ENTREGA.BASE_ELEG_110226` | 2 |
| `processo_carga_score_solar_jul_26_REAPONTADO_PJeOFENS` | `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211` | 2 |

Pergunta única para a área, para os seis: **a tabela foi renomeada ou deixou de existir?**
Se renomeada, o consumidor precisa ser reapontado. Se extinta, os consumidores quebram.

### 1.2 EGPs que aumentam a fila de ingestão

Estes três são o oposto do que o projeto quer, e serão adotados mesmo assim:

| EGP novo | Inputs a ingerir | Outputs |
|---|---|---|
| `Elegibilidade menor que 90_GCP_v4` | 25 → **43** | 168 → 209 |
| `CartoesAmigaveis_PilotoAcordos_20260710` | 12 → **25** | 134 → 151 |
| `Elegibilidade_Gradativo_20251103_reap_v26` | 19 → **25** | 117 → 172 |

Somam **+37 inputs novos** na fila. Precisam entrar no planejamento de ingestão da
próxima onda, não apenas na conversão.

### 1.3 Um EGP novo que substitui vários antigos

Quatro casos. O primeiro foi confirmado por escrito pelo BV em 26/08 ("Precisaremos
substituir os EGPs PROJECT_ATIVA_GCP_V2 e PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente, pelo
EGP PROJECT_ATIVA_TABLEAU_NEW_RPA"); os outros três foram deduzidos por similaridade de
código e **precisam de confirmação**.

| EGP novo | Substitui | Confirmado? |
|---|---|---|
| `PROJECT_ATIVA_TABLEAU_NEW_RPA` | `_V2_4_vigente` + `PROJECT_ATIVA_GCP_V2` | sim, email 26/08 |
| `PERFORMANCE_CL_202608_GCP` | `PERFORMANCE_CL_202603` + `_202603_REPROC_HIST_EDU` | não |
| `Acompanhamento_Desconto - Painel_vK` | `Painel_vK` + `Painel_VE2` | não |
| `NuContratoContabil_Atualizado` | `Fechamento_Contabil_RPDD_3040` + `Projecao_RPDD_4966_Filtrado` + `10. Marcacao_Score_BANKLY` + 1 | **duvidoso** |

O último é o menos crível: 4 EGPs consolidados num só, exatamente no teto do detector.
A família contábil compartilha um preâmbulo de macros grande, e é provável que o
detector esteja lendo irmandade de boilerplate como consolidação. O número de "42
inputs a ingerir → 3" e "183 outputs → 24" desse EGP é a união dos quatro e **não deve
ser usado** antes de a área confirmar quantos EGPs ele realmente substitui.

## 2. Bloqueado por conversão já feita

`Project_Compensacao_Encargos_v1`: o antecessor está em etapa `Validação da Área` com
status `Em Andamento`, e em 31/08 o BV formalizou a entrega dele migrado para
dbt/BigQuery. Adotar a versão nova aqui joga fora conversão concluída. Este caso precisa
de decisão explícita da liderança, não de execução.

## 3. Prioridade de adoção

**Primeiro (4):** `NuContratoContabil_Atualizado` (com a ressalva de 1.3),
`Estrategia_Reneg_Solar_180_v20251117_GCP_PJ`, `Elegibilidade_Reneg_CP`,
`SALDO_ALTOS_+_PE_20260714 - Reapontado_VF_Reduzido`. Todos reduzem `file_in` a zero ou
quase, que é o pior tipo de input.

**Verificação obrigatória antes de adotar qualquer um dos 4.** Nos quatro, inputs e
outputs caem juntos, e em três os inputs *já disponíveis* também caem. Um EGP que passou
a ler menos tabela modernizada e a gerar metade dos outputs pode ter sido modernizado,
partido em dois, ou ter tido escopo cortado — nos números as três coisas são idênticas.
Um deles se chama literalmente "Reduzido". Confirmar com a área que o EGP novo faz o
mesmo trabalho; se faz menos, o resto foi para outro lugar que também precisa entrar no
escopo.

**Depois (12):** o maior tem Valor 19 e a maioria tem Valor 0. Inventário praticamente
inalterado; adotar em lote, sem análise individual.

**Sem ação (3):** `ANALISE_ELEGIVEIS_v2`, `Atualiza_UF_Cartoes` e `Project_Reneg_WO_NEW`
têm código idêntico ao corpus.

**Par não resolvido (1):** `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB`, 31% de
tasks em comum com `_Inc_Desconto_ORAHASH`, abaixo do corte de 40%. Perguntar à área
qual é o antecessor. Não afirmar par por semelhança de nome.

## 4. Ordem de execução

1. **Um bloco de perguntas para a área**: os 6 outputs removidos (renomeados ou
   extintos?), as 3 consolidações não confirmadas de 1.3, o antecessor do
   `Bases_Auxiliares`, e a equivalência de escopo dos 4 de maior prioridade.
2. **Decisão de liderança** sobre o `Project_Compensacao_Encargos_v1`.
3. **Adotar** os liberados, começando pelos 4.
4. **Nível 2** (orquestrador em worktree) com todos os adotados **juntos**, uma vez.
   Já rodado em 02/09 para o cenário "adotar todos os 27": ver
   `BV_Migracao_SAS_Validacao_Nivel2_2026-09-02.md`. Refazer só se o escopo aprovado
   pela área for diferente desse.
5. **Registrar** as dependências identificadas, conforme o direcionamento de 21/08.

**Critério de parada:** com menos de 3 EGPs liberados após o passo 1, não roda o Nível 2
nesta rodada — o custo fixo do orquestrador não se paga.

## Registro de calibração

**2026-09-01 — cortes de quadrante: 50/50 → 20/20 (ajuste único).**
Na 1ª rodada o Valor máximo foi 44,1 e a mediana ~1, então 50/50 jogou 100% dos casos em
"Trocar depois" ou veto. Não recalibrar por rodada.

**2026-09-01 — dois vetos estreitados:**
- *Caminho de rede novo* virou alerta. Vetava 6 de 30, mas caminho de rede é o estado
  normal deste corpus. O caso que provou: em `tipos_acordo` os "regressivos" eram
  `AGRTYPE_V2.XLSX`, `AGRVALQ_V2.XLSX`, `AGTPDSC_V2.XLSX`, ou seja, version bump de
  planilha. Macro não resolvido no caminho continua veto.
- *Output removido com consumidor* passou a exigir **2+ consumidores externos**. Com 1
  é quase sempre rascunho de analista em libname pessoal. Critério por contagem, não por
  lista de nomes.

**2026-09-01 — pareamento passou a ser N:1**, depois do email do BV de 26/08 confirmando
que um EGP novo pode substituir vários. Duas correções durante o teste:
- a medida de co-antecessor é **Jaccard**, não o overlap assimétrico. Com o assimétrico,
  um EGP antigo grande que contenha todo o boilerplate de um novo pequeno marca 100%:
  deu 14 "co-antecessores" para o `Atualiza_UF_Cartoes`, que é byte-idêntico ao seu par;
- o corte é **0,60**, calibrado contra o fato conhecido: no par confirmado pelo BV o
  co-antecessor verdadeiro tem Jaccard 0,681 e o candidato mais próximo que a Michelli
  **não** citou tem 0,516. Teto de 3 co-antecessores; acima disso é irmandade de
  boilerplate e o detector desiste com alerta.

**Bugs corrigidos no desenvolvimento:** o veto de output contava o próprio EGP como
consumidor (disparava em massa e falso nos inputs auto-gerados); e a saída antecipada
por código idêntico não valia quando havia co-antecessores, o que inventava outputs que
o EGP novo nunca teve.

## Números em que não confiar

- `PROJECT_ATIVA_TABLEAU_NEW_RPA` reporta ~1,65 milhão de linhas de código (o `.egp` tem
  21 MB). Implausível para SAS escrito à mão, provável MPRINT gerado dentro do
  `code.sas`. O eixo de churn desse EGP não significa nada.
- Os números do `NuContratoContabil_Atualizado` dependem de a consolidação de 4 EGPs ser
  verdadeira. Ver 1.3.
