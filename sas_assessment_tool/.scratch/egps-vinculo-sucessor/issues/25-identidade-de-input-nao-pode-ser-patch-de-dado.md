# 25 — Identidade de input não pode viver como patch de dado

**Status:** camadas 1 e 2 ENTREGUES (29/09/2026) · camada 3 FECHADA sem entrega (01/10/2026)

## O que acontece

Decisões de **identidade** de input (qual alias de libname é o canônico, qual chave uma
planilha `[SHEET=]` recebe, o rename do `CPF_Contrato`) são aplicadas como **UPDATE nas
tabelas do corpus**. O publish é full-replace nessas tabelas. Toda decisão morre no publish
seguinte, **em silêncio**.

Medido hoje, comparando `monitoramento_sas` (prod) com o clone que levou um republish
completo:

| | prod | clone pós-republish |
|---|---|---|
| `sas_input_alias_canonico` | 186 linhas | 186 linhas (**sobreviveu**) |
| colapsos ativos no mapa (`eh_canonico=false`) | 101 | 101 |
| desses, ainda **soltos** em `sas_inputs_monitor` | **0** | **101** |
| chaves não-órfãs no corpus | 10.087 | 10.325 (**+238**) |
| membros com conjunto de aliases divergente | — | **102** |

**101 de 101 colapsos desfeitos por um publish.** O mapa sobreviveu; o efeito dele não.

Exemplos: `BASE_NPS_ATU` é 1 chave em prod (`NPSNOTA.`) e 3 no clone (`NPS.`, `NPSNOTA.`,
`ZNPS.`). `BASE_AUX_DU` é 1 (`ZBRUNO.`) e vira 3. `PERF_AMIGAVEL` é `MOVTO.` e vira
`CARTAO.` + `MOVTO.`.

Foi isso — e não a feature de extras — que fez o escopo do clone marcar 1.251 contra 1.237
de prod.

## Por que volta

1. O publish dá `DROP TABLE` em `sas_lineage_nodes`, `sas_lineage_edges`, `sas_egp_inputs`,
   `sas_egp_outputs`, `sas_resumo_*`, `sas_funil_area` (`publish_to_databricks.py:1461-1512`).
2. `sas_inputs_monitor` é **MERGE por `chave_canonica`**, preservando as colunas humanas.
   Quando a identidade muda, a chave muda — o MERGE não casa, o estado humano fica na
   chave velha e a nova nasce zerada. Foi o que aconteceu com as 834 planilhas em 23/09
   (117 estados zerados).
3. `sas_input_alias_canonico` **não é tocada pelo publish** (não aparece em
   `publish_to_databricks.py`). Ela é o único pedaço que sobrevive — e está **inerte**:
   `grep` por `sas_input_alias_canonico` no código do app dá **zero**.

## A correção, em três camadas

As três são independentes e entregáveis em ordem. A 1ª já impede o dano silencioso.

### 1. Guarda pós-publish que FALHA ALTO — **ENTREGUE** (`identidade_guard.py`)

Uma verificação no fim do publish — e um teste no CI — que cruza o corpus recém-escrito
com `sas_input_alias_canonico` e recusa terminar em silêncio:

```
colapsos ativos no mapa: 101
ainda soltos no corpus : 101   -> ERRO: o publish desfez 101 decisões de identidade
```

Hoje esse número não é calculado em lugar nenhum. É o mesmo princípio do
`test_arquivo_vive_dentro_do_deploy` e do `LinhaBaseAusente`: **um zero silencioso é pior
que um 500**.

**Verifica:** rodar o publish num schema descartável com o mapa populado tem de acusar 101;
com o mapa vazio, 0.

### 2. Reaplicação idempotente dirigida pelo mapa — **ENTREGUE** (`identidade_reaplica.py`)

Um passo único no fim do publish que releia `sas_input_alias_canonico` e reaplique os
colapsos. Substitui os scripts ad-hoc que hoje existem um por caso —
`reaplica_rename_cpf_contrato_pos_publish.py`, o das planilhas, o dos homônimos — por um só,
dirigido por dado versionado em vez de lista no código.

Requisitos duros:
- **idempotente**: rodar duas vezes não muda nada;
- **não propaga estado entre irmãos** (regra de 23/09: propagar cancelaria ingestão ativa
  — o colapso junta a identidade, nunca o status);
- audita o que mexeu em `sas_inputs_audit`.

**Verifica:** publish → reaplicação → a guarda da camada 1 tem de dar 0.

### 3. O alvo real: colapso DERIVADO no backend — **ABERTO** *(torna a 2 desnecessária)*

Identidade deixa de ser dado mutável e vira **leitura**, nos moldes de `familias.py`: o
backend lê `sas_input_alias_canonico` e colapsa na resposta da API, como `_agrega_familias`
já faz com as safras. O corpus guarda o grão físico; a tela mostra a unidade.

É o caminho já registrado como o certo quando a tabela foi criada, e tem as mesmas
propriedades que fizeram a família funcionar:
- **reversível sem republish** — desligar é parar de ler o mapa;
- **imune ao publish** por construção, não por reaplicação;
- **um lugar só** decide a unidade, em vez de N scripts.

Pontos a resolver no desenho (os mesmos que `familias.py` já resolveu uma vez):
- estado misto entre irmãos (dois aliases com etapas diferentes) — a família expõe
  `estado_misto`; aqui provavelmente vale o mesmo;
- o grafo de linhagem continua no grão físico (como acontece com safra);
- a chave de transporte precisa de namespace próprio e reconhecível num grep, como
  `familia::`, para nunca vazar para uma escrita.

**Verifica:** com o mapa ligado, `BASE_NPS_ATU` aparece como **uma** linha nas abas Inputs
e Resumo nos dois schemas, e os totais de prod e do clone voltam a bater.

## Enquanto isso

**Não rodar republish completo em prod sem a camada 1 no lugar.** Hoje ele desfaz 101
colapsos sem avisar ninguém, e o efeito só aparece como "o número mudou e não sei por quê"
— que foi exatamente como isto apareceu.

Ver também: `docs/analises/PLANO_CONSOLIDACAO_SASLOCAL.md` (a análise que originou o mapa)
e o ticket 23, que tem a mesma raiz — decisão que o app grava e o pipeline apaga.


## Entregue em 29/09/2026 (camadas 1 e 2)

O publish faz, nesta ordem: **reaplica** e depois **confere**. A guarda deixou de ser o
aviso e virou a prova — se ela ainda acusar, é porque algo foi recusado, e o publish sai 1.
`--sem-reaplicar-identidade` desliga só a reaplicação; a guarda continua.

**A semântica não foi inventada.** Foi lida de prod, comparando uma chave colapsada tabela
a tabela contra o clone pós-republish:

| tabela | o que acontece com o alias |
|---|---|
| `sas_egp_inputs` | o par é **repontado** (dedupe antes: 14 EGPs já liam o canônico) |
| `sas_inputs_monitor` | a linha é **apagada**; o canônico não é tocado |
| `sas_resumo_inputs` | a linha é **apagada** |
| `sas_egp_input_link` | o link segue o par (mesma decisão humana, mesmo par EGP×input) |

**Duas recusas, nenhuma adivinha:** alvo ausente no monitor (apagar o alias perderia o
input) e alias com estado **além do default** `A Receber`/`A Iniciar` sem responsável nem
observação (apagá-lo jogaria fora trabalho de gente — a regra de 23/09 de não propagar
estado entre irmãos). Medido: os 101 estavam **todos** no default, então a reaplicação era
lossless; a recusa existe para o dia em que não for.

`modernizada_auto` não bloqueia de propósito: é detecção automática, recalculada no publish
seguinte — tratá-la como trabalho humano travaria o colapso por um dado que se refaz.

21 testes (9 da guarda + 12 da reaplicação), todos sem banco.

## O que a camada 3 ainda resolve

A 2 é reparo: o corpus ainda nasce errado a cada publish e é consertado depois. A 3 faz a
identidade deixar de ser dado mutável — o backend lê o mapa e colapsa na resposta, nos
moldes de `familias.py`. Aí não há o que reparar, e a 2 pode sair.

## Camada 3 — construída, medida e removida (01/10/2026)

Decisão do usuário depois da medição: **a 2 já resolve, a 3 sai.**

A 3 foi implementada por inteiro (`app/backend/identidade.py`, 11 testes, flag
`IDENTIDADE_ALIAS`, aplicada nos dois produtores antes de `_agrega_familias`) e então
removida. O que a medição mostrou:

- mapa ativo: 101 colapsos; chaves de alias presentes no corpus: **0 de 101** — nos três
  schemas (`monitoramento_sas`, `monitoramento_sas_dev`, `monitoramento_sas_atualizados_dev`);
- motivo: `identidade_reaplica.reaplica()` roda **dentro do publish**
  (`publish_to_databricks.py`, logo após o full-replace). Os alias voltam a cada publish —
  estão nos CSVs locais — e são recolapsados no mesmo run, antes de qualquer leitura;
- delta ligado × desligado: **0** nos dois schemas (1369 no clone, 1291 em prod);
- o fio estava ligado: injetando um mapa em memória sobre linhas reais, 1608 → 1607, o alias
  some, `areas` unem, `qtd_projetos` sai 113 (não a soma 221) e `estado_misto` sobe.

Ou seja: a premissa da 3 — "o corpus nasce errado e fica errado até alguém reparar" —
deixou de valer quando a 2 entrou no publish. O critério de aceite original
(`BASE_NPS_ATU` como uma linha) não dispara porque a 2 nunca deixa o alias sobreviver ao
publish; e as duas linhas `BASE_NPS_ATU` que existem em prod são `NPSNOTA.BASE_NPS_ATU` e
`NPS.BASE_NPS_ATU_IA` — membros diferentes, não um par de alias.

**Se a 3 voltar à mesa**, o gatilho é um só: a 2 passar a RECUSAR colapsos com frequência
(alvo ausente, ou alias com trabalho humano). Hoje uma recusa faz o publish sair com
`exit 1`, então o alias solto também não chega à tela. Mudando isso, a 3 volta a ter
função.

A camada 3 **nunca foi commitada** — não há commit para reverter nem código a resgatar do
histórico. Refazer é reescrever, e a especificação está em §"A correção, em três camadas"
acima. O desenho que funcionou, para não repetir a descoberta: a chave do grupo é a
CANÔNICA (não um namespace `alias::` como o ticket sugeria — o canônico É linha real de
`sas_inputs_monitor` e é nele que o estado humano mora); a cadeia A→B→C é resolvida e o
ciclo descartado; o alias com trabalho humano levanta `estado_misto` em vez de sumir; e o
colapso roda ANTES de `_agrega_familias`, porque dois aliases da mesma tabela têm
`artifact` diferente e a família os veria como tabelas distintas.
