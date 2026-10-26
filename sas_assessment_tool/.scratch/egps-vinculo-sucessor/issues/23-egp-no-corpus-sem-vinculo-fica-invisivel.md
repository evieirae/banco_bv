# 23 — EGP entra no corpus, não tem vínculo, e some da tela

**Status:** itens 1 e 2 ENTREGUES (01/10/2026) · item 3 segue decisão da gestão
· vínculo do First_Loss CONFIRMADO pelo usuário (ver §Correção)

## O caso que revelou

O usuário apontou que `processo_carga_score_solar_set_26_REAPONTADO_PJeOFENS`, da pasta
`Documents\EGPs Atualizados`, "não tá no app". Ele **está** no corpus
(`monitoramento_sas_atualizados_dev`, 1.270 nós) com o inventário extraído. O que não
existe é o **vínculo**: o antecessor `..._jul_25` (linha de base) aponta para `..._jul_26`,
uma versão anterior à que o BV mandou depois.

Pela régua de 29/09 isso está certo — `extra` é quem tem vínculo, não "todo o resto do
corpus". Mas a consequência não estava prevista: **um EGP pode ser processado, publicado e
ficar invisível em todas as telas**, sem nenhum contador dizendo que ele existe.

## O escopo do buraco (medido em 29/09, schema dos atualizados)

Dos 13 arquivos da pasta, **todos** já estavam no corpus. 7 não aparecem em tela:

| projeto | por quê |
|---|---|
| `…score_solar_set_26_REAPONTADO_PJeOFENS` | sem vínculo — o de `jul_25` aponta p/ `jul_26` |
| `…Solar_180_v20251117_GCP_PJ__ATU20260901` e `__ATU20260916` | sem vínculo (2 versões) |
| `Remuneracao_CL_202603__ATU20260910` | sem vínculo |
| `Reneg_Remunerav3_RPA` | sem vínculo |
| `First_Loss_GCP_2026` | sem vínculo, e sem antecessor óbvio |
| `ROI` | sem vínculo (era artefato BigQuery convertido, não backlog) |
| `Project_Fyf_Reneg_BQ_202608 1` | **tem** vínculo, mas o antecessor (`…_v2`) está fora do recorte, e o `suc` do `_frontier_egps` só puxa sucessor de antecessor que já esteja no fecho |

O último é o caso mais feio: existe um vínculo declarado que **não puxa nada**, e nada
avisa.

## O que já existe e não cobre

`/api/egps-atualizados/aguardando-corpus` cobre o sentido inverso — versão recebida que
ainda **não** entrou no corpus. Falta o "entrou no corpus e está esperando vínculo".

## Proposta

1. Contador/lista **"no corpus, sem vínculo"**: nós fora da linha de base, fora do frontier
   e sem `egp_sucessor` apontando para eles. Mesmo lugar do 📥 Aguardando corpus, na aba
   EGPs. Com o antecessor SUGERIDO (o `sucessorSugerido()` do front já faz o pareamento por
   nome; aqui é a direção contrária).
2. Aviso de **vínculo órfão**: antecessor fora do recorte, sucessor que não entra. Hoje
   passa em silêncio.
3. Decidir o que fazer quando chega uma versão **mais nova que o sucessor já vinculado**
   (`jul_26` → `set_26`): repontar o vínculo descarta a classificação anterior, e isso é
   decisão da gestão, não do publish.


## Atualização 29/09/2026 — 4 vínculos criados, 1 recusado pelo app

Criados pelo endpoint (`PATCH /api/egp-pipeline`, não por SQL) em
`monitoramento_sas_atualizados_dev`:

| antecessor | sucessor |
|---|---|
| `…score_solar_jul_26_REAPONTADO_PJeOFENS` | `…score_solar_set_26_REAPONTADO_PJeOFENS` |
| `Estrategia_Reneg_Solar_180_v20250305_GCP` | `…_v20251117_GCP_PJ__ATU20260901` |
| `…_v20251117_GCP_PJ__ATU20260901` | `…_v20251117_GCP_PJ__ATU20260916` |
| `Remuneracao_CL_202603` | `Remuneracao_CL_202603__ATU20260910` |

Antecessores conferidos contra o pareamento medido em `sas_egp_atualizados`
(`egp_original` + `overlap_tasks`), não por semelhança de nome.

**`Reneg_Remunerav3 → Reneg_Remunerav3_RPA` foi RECUSADO pela guarda do app:**
*"EGP com status Migrado não recebe sucessor — reabra o status antes de vincular"*. A
guarda está certa e é o mesmo caso dos 4 vetos de "já convertido". Reabrir o status é
decisão da gestão; não foi forçado.

**O item 2 desta issue virou bug e foi corrigido:** `_frontier_egps` fazia UMA passada
sobre os sucessores, então a 2ª versão de uma cadeia nunca entrava no recorte. Virou fecho
(`vinculos.cadeia_de_sucessores`, 5 testes). Extras 14 → 18, total de EGPs intacto em 193.

**O item 1 (contador "no corpus, sem vínculo") segue aberto** — hoje sobram 3 nessa
condição: `First_Loss_GCP_2026`, `ROI` e `Reneg_Remunerav3_RPA`.

## First_Loss e ROI: não são versões novas (apurado no email, 29/09/2026)

**`First_Loss_GCP_2026` é EGP próprio, não sucessor de ninguém.** A formalização enviada ao
BV em 22/09 ("Formalização da modernização do EGP First_Loss_GCP_2026", Morgana → Natália/
Laís/Marília/Thiago/Leandro/Cleber) diz, no item 7: *"EGP origem: `first_loss_gcp_2026`"*.
A entrega substitui o **fluxo SAS legado dele mesmo** (`WORK.FIRSTLOSS_CONSOLIDADO` →
`firstloss_consolidado_diaria_aggr`), com card UDAA-5039 e PR #388 próprios.

Isso **derruba** a hipótese vinda do Slack (Sérgio, 10/09: *"First_Loss_GCP_2026.egp
(NOVO_IPF_V9_MACRO_MES_RPA)"*). Nenhum vínculo foi criado.

**`ROI` não tem antecessor registrado em lugar nenhum** — nem no app, nem no Slack, nem no
email. O que existe é a série "Piloto - Egp ROI" (organizadora Francielly Miranda/BV, com
Cleber Saure e Leandro Rocha), semanal desde 31/08 e **cancelada toda semana**; a de 04/09
com a justificativa *"estamos compilando os pontos do workshop"*. O `ROI.txt` é SQL
BigQuery puro (577 linhas, 1 task, zero PROC SAS), compatível com artefato de piloto.

## O buraco maior: a aposentadoria da aba não tem porta para eles

**Correção do que estava escrito aqui antes.** A primeira versão desta seção media
`sas_lineage_nodes` em prod e concluía que os EGPs "não existem no app". Está errado: em
prod eles aparecem na aba **EGPs Atualizados**, que tem tabelas próprias
(`sas_egp_atualizados` e cia., write-isolated, §5). Não estar no corpus é o estado CERTO de
prod hoje — a unificação é justamente o que esta branch entrega.

O problema real é outro: **o §5 aposenta a aba, e a justificativa é que "o sucessor entra no
corpus e aparece sozinho na aba EGPs".** Isso vale para sucessor. Não vale para versão sem
antecessor. Estas quatro estão hoje na aba de prod e, no mundo unificado, não têm linha em
lugar nenhum:

| na aba EGPs Atualizados (prod) | quadrante | vínculo possível |
|---|---|---|
| `First_Loss_GCP_2026` | EGP inédito | nenhum — é EGP próprio (formalizado 22/09) |
| `ROI` | EGP inédito | nenhum — artefato do piloto |
| `Reneg_Remunerav3_RPA` | Não trocar (veto) | recusado: antecessor está `Migrado` |
| `Project_Fyf_Reneg_BQ_202608 1` | Avaliar caso a caso | existe, mas o antecessor está fora do recorte |

Os três primeiros com entrega **formalizada por email ao BV** (First_Loss 22/09 UDAA-5039
PR #388; Fyf e Reneg_Remunera_v3_RPA em 25/09).

É **categoria faltando**: EGP que entra no escopo depois do congelamento e não é sucessor de
nada não cabe nem nos 193 (congelado) nem em `extra` (enumeração por vínculo). Enquanto a
aba existir em prod, ninguém sente. Quando ela sair, somem.

**Não aposentar a aba antes de decidir isto.**


## O custo real de não ter o contador (medido em 30/09/2026)

O buraco não é só "o EGP fica invisível". Ele **muda número de gestão em silêncio**.

O usuário perguntou por que "Inputs das dependências" marcava **88** no ambiente e **61** em
prod. Causa: **3 EGPs atualizados entraram no corpus sem vínculo**. Sem vínculo o app não
sabe que são versão nova de alguém, então não são `extra`; mas eles produzem tabelas que a
linha de base consome, e o grafo puxa todo produtor como dependência. Os inputs deles foram
parar no card de dependências.

| EGP (só existia no ambiente) | inputs |
|---|---|
| `Elegibilidade menor que 90_GCP_v4__ATU20260901` | 79 |
| `Elegibilidade_Gradativo_20251103_reap_v26` | 44 |
| `PERFORMANCE_CL_202608_GCP` | 61 |

Criados os 4 vínculos (o `PERFORMANCE_CL_202608_GCP` tem 2 antecessores → `Unificado`), os
26 inputs mudaram de balde: **deps 88 → 62** (prod: 61), **extras 38 → 64**, e o **total
ficou em 1.362**, intacto — como tem de ser, já que nada entrou nem saiu do recorte.

**Isto é o argumento do item 1 desta issue.** Um EGP sem vínculo não fica só escondido: ele
é silenciosamente reclassificado como dependência e distorce o card que a gestão lê. O
contador "no corpus, sem vínculo" teria mostrado os três no dia em que entraram.

Armadilha confirmada no caminho: o `egp_key` de `sas_egp_atualizados` é a chave de CHEGADA,
não o projeto do corpus (`Elegibilidade menor que 90_GCP_v4` × `…__ATU20260901`). Vincular
pelo `egp_key` apontaria o EGP para ele mesmo.

---

## Itens 1 e 2 — entregues (01/10/2026)

### O universo do contador, decidido por medição

A lista "no corpus, sem vínculo" usava como universo só as versões RECEBIDAS
(`sas_egp_atualizados`) que viraram projeto. EGP carregado por fora dessa tabela — pela
skill `sobe-egp-atualizado`, ou à mão — ficava cego. As três opções, medidas no clone:

| universo | acha | ruído |
|---|---|---|
| versões recebidas no corpus (o de antes) | 22 | — |
| corpus inteiro fora do frontier | **1051** | inutilizável |
| **recebidas ∪ corpus com sufixo `__ATU<AAAAMMDD>`** | **23** | **zero** |

Adotada a união: custa +1 caso real (`manut_acordo__ATU20260901`) e nenhum falso positivo.

**Armadilha de substring encontrada no caminho:** `"__ATU" in projeto` casa também
`Cobranças__ATUALIZACAO BASE PROJURIS`, `Riscos__ATUALIZACAO_BASES v09` e
`Riscos__ATUALIZACAO_PROJURIS V10` — 3 falsos positivos em 21 casamentos. O predicado novo
(`egps_atualizados.eh_chave_atu`) é **ancorado no fim e exige 8 dígitos**. O `_id_atu`
pré-existente ainda usa a forma por substring; não foi tocado (fora do escopo), mas é a
mesma armadilha esperando.

**O que ainda escapa, declarado:** versão que entra sem o sufixo E fora da tabela de
chegada. Não há sinal para pegar, e inventar um seria adivinhar.

### Item 2 — vínculo órfão, agora com dois níveis

O critério original era "antecessor fora do recorte". Com ele, **3 dos 4 órfãos eram
ruído**, e o ruído enterrava o único caso que pedia ação. Auditados um a um em 01/10/2026:

| antecessor → sucessor | por que o antecessor está fora | sucessor em tela? |
|---|---|---|
| `Import_Excecoes` → `…__ATU20260930` | nunca esteve no escopo Indicium (`escopo_indi=false`) | **NÃO** |
| `PROJECT_ATIVA_GCP_V2` → `…TABLEAU_NEW_RPA` | é **ex-dependência** (fora do frontier por construção) | sim, com badge |
| `…_Inc_Cadu_HUB` → `…__ATU20260930` | ex-dependência **por decisão da gestão** (repontar o Cadu_HUB, 30/09) | sim, via 2 `Unificado` |
| `…score_solar_jul_26` → `…set_26` | antecessor duplicado fora do escopo | sim, via `jul_25` |

Note que **não há cadeia** no caso do score_solar: `jul_25` e `jul_26` apontam os dois para
`set_26`, em paralelo — não é `jul_25 → jul_26 → set_26`.

O alerta passou a separar:

- **invisível** (`sucessor_em_tela = false`): nem antecessor nem sucessor aparecem. O EGP
  foi publicado e não existe em tela nenhuma. **Este bloco é a única coisa no app que o
  menciona** — a lista "sem vínculo" não o pega, justamente porque ele TEM vínculo. Hoje: 1
  (`Import_Excecoes__ATU20260930`, que o usuário vai avaliar; deixado como está);
- **inerte**: o vínculo não age, mas o sucessor aparece por outro caminho. Vira registro,
  não pendência. Hoje: 3.

`em_tela` é o recorte que a aba de fato lista (frontier ∪ ex-dependências ∪ linha de base),
não só o frontier — usar só o frontier classificaria a ex-dependência como invisível e
devolveria o ruído. Sem `em_tela`, o campo é `None` e nunca `True`: afirmar "aparece" sem
ter olhado esconderia o caso grave.

### O que mudou de diagnóstico

- **A população perigosa está vazia.** EGP puxado SÓ como dependência (fora da base, sem
  vínculo, sem ser casca/novo) — a causa do `deps 88 × 61` — hoje é **0**. Os 4 vínculos
  de 30/09 fecharam. O contador agora existe para a próxima vez.
- **A "categoria faltando" foi resolvida pelo ticket 24.** A issue dizia "não aposentar a
  aba antes de decidir isto". Decidido: EGP que entra depois do congelamento e não sucede
  ninguém é declarado `novo` pela aba Gestão. `ROI` já está declarado; `First_Loss` não
  precisa (ver abaixo).

## Correção: o vínculo do First_Loss está CERTO (01/10/2026)

Esta issue afirmava, com base no email de 22/09, que `First_Loss_GCP_2026` não sucede
ninguém e que "nenhum vínculo foi criado". **Levantei isso como contradição e estava
errado.** O usuário confirmou: *"ele entrou no lugar desse novo_ipf"*.

Onde meu raciocínio falhou:

- o email diz *"EGP origem: `first_loss_gcp_2026`"*, que responde **de qual fluxo a
  entrega saiu** — não **o que ela aposenta**. Tratei uma pergunta como se negasse a outra;
- `overlap_tasks = 0.0` / `confianca_par = sem_par` **não decide nada aqui**: reescrita
  completa de SAS para BigQuery não compartilha hash de task nenhum. Overlap zero é
  igualmente compatível com "sem relação" e com "reescreveu do zero". A régua de pareamento
  por hash não separa esses dois casos — e a tabela de faixas da skill já diz isso ao
  mandar PARAR e perguntar quando o overlap é baixo, em vez de concluir.

`NOVO_IPF_V9_MACRO_MES_RPA` está na **linha de base** (classe `base`, um dos 193), então
`Substituído` é o tipo correto: o antigo fecha, o novo começa do zero.

### O que o vínculo sustenta (medido, simulando a remoção em memória)

| | com o vínculo | sem o vínculo |
|---|---|---|
| `First_Loss` na aba EGPs | `extra · sucessor` | **ausente** |
| na lista "no corpus, sem vínculo" | não | sim (23 → 24) |
| extras | 24 | 23 |
| inputs dos extras / TOTAL | 71 / **1369** | 69 / **1367** |
| `NOVO_IPF_V9_MACRO_MES_RPA` | Migrado / Despriorizado | **inalterado** |

Duas lições que ficam:

1. **O vínculo é a única coisa que mantém o sucessor em tela.** Removê-lo não "corrige
   uma classificação": apaga o EGP de todas as superfícies e tira 2 inputs do total.
2. **`Substituído` não toca no antecessor** — por desenho, as trajetórias são
   independentes. Quem muda é só o sucessor. Isso torna o vínculo barato de criar e caro
   de remover, o que é o contrário da intuição.

### O 2º antecessor do Fyf_Reneg: resolvido (01/10/2026)

`Project_Fyf_Reneg_BQ_202608 1` tinha dois antecessores com tipos diferentes
(`PROJECT_ROLAGEM_NEW` = `Substituído`, `Project_Fyf_Reneg_v2` = `Atualizado`). Decisão do
usuário: **só o `PROJECT_ROLAGEM_NEW` é substituído; o `Project_Fyf_Reneg_v2` está fora do
escopo e pode ser ignorado.**

O vínculo do `Fyf_Reneg_v2` foi removido **pelo endpoint** (`PATCH /api/egp-pipeline` com
`egp_sucessor=""`), nunca por SQL — um UPDATE direto pularia a cópia de etapa do ticket 07
(armadilha registrada no ticket 17).

Simulado antes e conferido depois, idênticos:

| | antes | depois |
|---|---|---|
| total_egps / extras / TOTAL inputs | 193 / 24 / 1369 | **193 / 24 / 1369** |
| vínculos órfãos | 5 | **4** |
| antecessores do sucessor | ROLAGEM_NEW + Fyf_Reneg_v2 | só `PROJECT_ROLAGEM_NEW` |

Nenhum número de gestão se moveu, e **um alarme falso sumiu**: o `Fyf_Reneg_v2` está fora
do recorte, então era ele próprio que gerava o órfão. `PROJECT_ROLAGEM_NEW` está na linha
de base; o sucessor segue visível por ele.

Vale a régua que isto confirma: **antes de remover um vínculo, simule.** Aqui era seguro
porque o sucessor tinha um segundo antecessor dentro do recorte. No `First_Loss`, que só
tinha um, remover o apagaria da tela — ver §Correção.

## Item 3 segue aberto

"Versão mais nova que o sucessor já vinculado" (`jul_26` → `set_26`): **não há nenhuma
cadeia nos dados hoje** (0 sucessores que também sejam antecessores, em 29 vínculos). O
fecho `cadeia_de_sucessores` está pronto e é defensivo. A regra — encadear ou repontar —
continua sendo decisão da gestão, mas sem caso vivo pressionando.

---

## O invisível resolvido: `Import_Excecoes` (01/10/2026)

O usuário informou: *"O Import_Excecoes é um substituto do painel_edu_3040"*. O único
candidato no corpus é `Cobranças__Painel_Desconto_3040_Edu` (linha de base, Pré-conversão /
Concluído, sem sucessor), confirmado por ele.

Vínculo gravado **pelo endpoint**, direto para a versão de 30/09 (escolha do usuário entre
as duas modelagens simuladas):

```
Cobranças__Painel_Desconto_3040_Edu --[Substituído]--> Cobranças__Import_Excecoes__ATU20260930
```

| | antes | depois |
|---|---|---|
| total_egps / escopo / deps | 193 / 1237 / 61 | **193 / 1237 / 61** |
| extras | 24 | 25 |
| inputs dos extras / TOTAL | 71 / 1369 | **451 / 1749** |
| órfãos · invisíveis | 4 · **1** | 4 · **0** |

**+380 inputs, e nenhum deles no escopo ou nas dependências.** O `__ATU20260930` lê 421
inputs (contra 19 do painel que ele substitui) e todos caem no balde `extra`, que é
exatamente o desenho: o extra tem contador próprio para não contaminar os 193. O card
"Inputs dos extras" multiplica por 6 e "a ingerir" vai de 40 para 420 — é visível na Visão
geral e foi aceito com os números à vista.

Os 4 órfãos permanecem, mas **todos inertes**: `Import_Excecoes` deixou de ser invisível
porque o sucessor dele entrou em tela por outro caminho.

### A observar: a cópia de etapa roda também no `Substituído`

`_copia_trabalho_para_sucessor` dispara em **qualquer** vínculo criado
(`vinculo_criado_agora`), sem olhar o tipo. Aqui o sucessor recebeu
`etapa = 'Pré-conversão'` do antecessor, embora `Substituído` signifique trajetórias
independentes — *"o antecessor fecha e o sucessor começa do zero"*
(`sucessores_espelhados`).

Dos dois motivos no docstring da cópia, só o primeiro se aplica a `Substituído`:

1. *"quem executa acha o trabalho no lugar certo"* — vale para qualquer substituição;
2. *"impede o antecessor de sumir da coluna do funil +deps espelhando a etapa vazia do
   sucessor"* — vale **só** para tipo espelhado, e `Substituído` não espelha.

Não é claramente defeito: herdar a posição no funil pode ser desejado. Mas um EGP que lê
421 inputs começar em "Pré-conversão" porque o antecessor de 19 inputs estava lá merece
decisão explícita. **Não alterado** — está aqui para a gestão decidir se a cópia deve ser
condicionada a `espelha(tipo)`.
