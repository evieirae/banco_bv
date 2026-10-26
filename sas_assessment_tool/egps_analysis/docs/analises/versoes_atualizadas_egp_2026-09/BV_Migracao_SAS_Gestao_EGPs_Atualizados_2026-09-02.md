# EGPs atualizados de Cobranças: impacto na migração e decisões necessárias

**Para:** gestão do projeto de Migração SAS
**Data:** 02/09/2026
**Assunto:** análise das 30 versões novas de EGP entregues pelo BV na pasta "EGP Atualizado"

O detalhe técnico por EGP está na pasta do estudo. Este documento traz o que muda na
migração e o que depende de decisão.

---

## O essencial

O BV entregou 30 versões atualizadas de EGP, todas de Cobranças. Comparamos cada uma com
a versão que já estava no nosso inventário, task de código por task de código.

**Adotar as versões novas aumenta a fila de ingestão.** Reprocessamos o inventário
inteiro com as 30 adotadas: a fila sai de 6.843 para 6.875 artefatos, 32 a mais. Entram
91 e saem 59. Quem estiver contando com essa entrega para acelerar a ingestão precisa
recalibrar a expectativa agora, não em outubro.

Há ganho, e ele é menor do que aparentava. São **15 planilhas e CSVs de rede a menos**
para ingerir. As referências a arquivo de rede caem 39, o que reduz acoplamento e é bom,
mas só 15 arquivos distintos saem da fila. Os outros continuam sendo lidos por outros
EGPs, e em troca entram 15 tabelas novas.

**O risco real de quebra está em 2 EGPs, não em 6.** Seis deixam de gerar uma tabela que
outros consomem. Em três, os consumidores estão todos fora do escopo. No quarto
(`PERFORMANCE_CL_202608_GCP`) a tabela foi renomeada e todos os consumidores no escopo já
têm solução ou vão ser despriorizados. Sobram **`processo_carga_score_solar_jul_26`** e
**`Campanha_Entrega_amigavel`**, com 5 consumidores no escopo e pré-conversão já
concluída. Um sexto caso depende de uma divergência de escopo em aberto.

Sobre o enquadramento: em 21/08 o BV direcionou que as versões vigentes são adotadas como
referência oficial, sem comparação detalhada com as anteriores, e pediu em troca a
avaliação de impacto nas dependências downstream. É isso que este documento entrega. A
adoção não está em discussão. O que está é o que precisa ser resolvido antes de
produtizar.

---

## O que muda na migração

| | Antes | Depois | Efeito |
|---|---|---|---|
| Artefatos a ingerir (corpus) | 6.843 | 6.875 | **32 a mais** |
| Arquivos de rede distintos | 2.833 | 2.818 | 15 a menos |
| Tabelas distintas a ingerir | 8.314 | 8.329 | 15 a mais |
| EGPs no inventário | 1.244 | 1.239 | 5 a menos |
| Dependências EGP → EGP | 1.870 | 1.861 | 9 a menos |

Três EGPs vão na direção contrária e somam **37 inputs novos** na fila:
`Elegibilidade menor que 90_GCP_v4` (25 para 43), `CartoesAmigaveis_PilotoAcordos`
(12 para 25) e `Elegibilidade_Gradativo_reap_v26` (19 para 25). Como a adoção é
obrigatória, isso é demanda nova para a próxima onda de ingestão, e precisa entrar no
planejamento agora.

A contagem de escopo também muda. **Quatro EGPs novos substituem mais de um EGP antigo**,
e se as consolidações se confirmarem o escopo perde 6 EGPs além das substituições
um-para-um. Isso mexe no plano do mês e nos funis, não só no arquivo.

---

## Riscos que precisam de decisão

### 1. Seis tabelas deixam de ser geradas. Três afetam o escopo.

São 18 consumidores nominais, mas **só 10 estão no escopo ativo** de migração (168 EGPs
de `sas_escopo`). Filtrando pelo que importa:

| EGP novo | Tabela que desaparece | No escopo | Fora | Ação |
|---|---|---|---|---|
| `processo_carga_score_solar_jul_26` | `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211` | **3 de 3** | 0 | bloquear |
| `Campanha_Entrega_amigavel_v4_mensal_gcp` | `ENTREGA.BASE_ELEG_110226` | **2 de 2** | 0 | bloquear |
| `PERFORMANCE_CL_202608_GCP` | `PERF_CL.CL_TABLEAU` | 4 de 7 (**0 efetivo**) | 3 | liberar, ver abaixo |
| `Performance_Saldo_COLORE_Lite_V5` | `PAGOSCBR.PAGOS_CYBER_202603` | 1 de 3 | 2 | ver ressalva |
| `PROJECT_ATIVA_TABLEAU_NEW_RPA` | `ATIVA.BASE_ATIVA_202510` | **0 de 2** | 2 | liberar |
| `Oportunidade Protesto_20260703` | `KEVIN.PUBLICO_PROTESTO_20260210` | **0 de 1** | 1 | liberar |

**Três casos podem ser liberados.** `PROJECT_ATIVA_TABLEAU_NEW_RPA` e
`Oportunidade Protesto_20260703` removem tabela cujos consumidores estão todos fora do
escopo (`DIAGNOSTICO_SCORE3 - 20251013`, `Project_Pilto_AgenteVirtual`,
`Notificações - GCP__v2`). O `PERFORMANCE_CL_202608_GCP` entra nessa lista pelo detalhe
abaixo. Nenhum dos três é bloqueio de migração.

Pode virar quatro: se o `Projecao_Rolagem - 3040 - 2026` estiver fora do escopo, como diz
a relação do BV, o `Performance_Saldo_COLORE_Lite_V5` também é liberado.

**Os que importam de verdade são cinco**, todos em etapa `Pré-conversão` com status
`Concluído`, ou seja já têm trabalho de pré-conversão feito que passaria a depender de
tabela sem produtor:

- de `GRIMALDI...`: `Apuração_Simplificada_202505`, `Programa_Marcação_Encargos_Sem_Flex`,
  `gradativo_202507_SOLAR_IDEAL_NTEC`
- de `ENTREGA...`: `EA_Semanal_NovoProcesso_GCP_V2`, `ENTREGA_AMIGAVEL_reneg_GCP`

Um sexto, o `Projecao_Rolagem - 3040 - 2026` (de `PAGOS_CYBER`), depende da divergência de
escopo descrita nas ressalvas. Os do `PERF_CL.CL_TABLEAU` saíram da lista pelo detalhe
abaixo.

#### O caso `PERFORMANCE_CL_202608_GCP` é renomeação, não extinção

A tabela não morreu, foi renomeada. O EGP novo produz `PERF_CL.CL_TABLEAU_3CL` e
`PERF_CL.CL_TABLEAU_ANT_3CL` no lugar do `PERF_CL.CL_TABLEAU`. Então aqui o trabalho é
**reapontar consumidor**, não recuperar dado perdido.

Nenhum dos 4 consumidores no escopo é risco efetivo:

- `Remuneracao_CL_202603` — **já resolvido**. Existe uma versão nova dele que lê o
  `PERF_CL.CL_TABLEAU_3CL`, e essa versão **ainda não foi entregue para nós**. O nosso
  inventário mostra a dependência antiga porque temos o EGP velho.
- `Performance_Produtos_V1` — **vai ser despriorizado**. Como EGP despriorizado deixa de
  puxar dependência exclusiva, ele para de ser motivo de bloqueio. Falta aplicar essa
  despriorização no app; até lá o inventário segue acusando a dependência.
- `PROJETO BI CARTOES GERAL_V3` e `Remuneracao_CL_202601` — já estão em
  `Migrado / Despriorizado e Contabilizado`. Se foram migrados, provavelmente leem fonte
  modernizada e não a tabela SAS. Confirmar, mas não bloqueia.

**Conclusão: o `PERFORMANCE_CL_202608_GCP` pode ser produtizado.** O que resta dele não é
quebra, é um item de ingestão, no parágrafo seguinte.

Uma consequência que não estava no radar: o EGP novo **lê o `PERF_CL.CL_TABLEAU` antigo
como input externo** (junto com `RESTORE.CL_TABLEAU` e `RESTORE.CL_TABLEAU_3CL`). Ou seja,
mesmo reapontando todos os consumidores, a tabela antiga continua sendo necessária para o
EGP novo rodar, e portanto continua na fila de ingestão. Precisamos saber se essa leitura
é transitória, de carga de histórico, ou permanente.

O `Oportunidade Protesto` já havia caído de 2 para 1 consumidor porque
`Carteira_Envio_Protesto_Solar_GCP` também está sendo substituído nesta entrega e a
versão nova não lê mais essa tabela.

Cada caso tem uma pergunta só. A tabela foi renomeada ou deixou de existir? Se foi
renomeada, os consumidores precisam ser reapontados. Se deixou de existir, eles quebram.
Recomendamos não produtizar esses seis antes da resposta.

A validação no inventário completo confirmou o risco nos **seis casos**: com a versão
nova adotada, cada uma dessas seis tabelas passa a exigir ingestão externa, porque
deixou de ser produzida e continua sendo lida.

### 2. Um EGP já foi migrado na versão antiga

`Project_Compensacao_Encargos_v1` está em Validação da Área, e em 31/08 o BV formalizou a
entrega dele migrado para dbt/BigQuery. Adotar a versão nova significa refazer conversão
já concluída e validada. Quem decide isso é a gestão, e as opções são manter o que foi
entregue ou assumir o retrabalho.

### 3. Unificações informadas pelo BV

O BV enviou a relação de EGPs novos que **unificam** projetos antigos, com o parecer de
escopo de cada um. Ela resolve uma pendência nossa e corrige uma leitura:

| EGP novo | Unifica | No escopo | Parecer do BV |
|---|---|---|---|
| `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB` | `_Inc_Desconto_ORAHASH` | Sim | despriorizado conforme solicitado |
| | `_Inc_Cadu_` | Não | fora do escopo de migração |
| `Project_Jornada_e_Mailing_RENEG_EPS_ADIMP_INAD_CADU_Whats` | `Trilha_RENEG_Oferta_Emprestimos` | Sim | despriorizado conforme solicitado |
| | + 4 `Trilha_RENEG` / `Mailing_RENEG` | Não | fora do escopo de migração |
| `NuContratoContabil` | `Fechamento_Contabil_RPDD_3040` | Sim | **seguir com a migração da versão original** |
| | `Projecao_RPDD_4966_Filtrado` | Sim | despriorizado conforme solicitado |
| | `Projecao_Rolagem - 3040 - 2026` | Não | fora do escopo de migração |

Três consequências:

**O par não resolvido está resolvido.** O antecessor do
`Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB` é o `_Inc_Desconto_ORAHASH`, que a
nossa detecção automática havia recusado por semelhança de código baixa (31%). Não era
falso: era unificação de dois projetos, e o segundo está fora do escopo.

**O `NuContratoContabil` tem uma instrução específica.** O BV diz para seguir com a
migração da versão **original** do `Fechamento_Contabil_RPDD_3040`. Ou seja, adotar o
`NuContratoContabil` não substitui esse antecessor. Nossa medição de impacto tratou os 32
antecessores como removidos, incluindo esse, então o número dele precisa ser refeito se a
adoção for aprovada nesses termos.

**Uma detecção nossa era falsa.** Havíamos identificado 4 antecessores para o
`NuContratoContabil`; a lista do BV traz 3, e o `10. Marcacao_Score_BANKLY` não está
nela. Era o falso positivo por biblioteca compartilhada que já suspeitávamos.

Nota: o `Project_Jornada_e_Mailing_RENEG_EPS_ADIMP_INAD_CADU_Whats` **não estava** na
pasta que analisamos. É entrega separada e ainda não passou pela análise.

### 4. Não sabemos se as versões novas fazem o mesmo trabalho

Nos 4 EGPs de maior ganho aparente, o número de inputs e de tabelas geradas cai junto. Um
deles se chama literalmente "Reduzido". Outro sai de 183 para 24 tabelas geradas.

Modernização, divisão do EGP em dois e corte de escopo produzem o mesmo padrão nos
números, e a análise não distingue os três casos. Antes de tratar esses EGPs como ganho,
precisamos que a área confirme que a versão nova faz o mesmo trabalho. Se faz menos, a
diferença foi para outro lugar, e esse outro lugar também entra no escopo da migração.

---

## Entregas que faltam chegar

O `Remuneracao_CL_202603` mostrou um padrão que muda o modo de perguntar: **parte dos
consumidores em risco já tem versão nova que resolve a dependência, e nós não temos essa
versão.** Enquanto o EGP novo não chega, o nosso inventário aponta uma quebra que na
prática já foi tratada pela área.

Duas consequências. Precisamos pedir esses EGPs nominalmente, e não podemos tratar a
lista de consumidores em risco como definitiva até saber quais deles têm versão nova a
caminho.

Também falta o `Project_Jornada_e_Mailing_RENEG_EPS_ADIMP_INAD_CADU_Whats`, que aparece
na relação de unificações do BV mas não estava na pasta analisada.

## O que já está encaminhado

Três EGPs (`ANALISE_ELEGIVEIS_v2`, `Atualiza_UF_Cartoes`, `Project_Reneg_WO_NEW`) têm
código idêntico ao que já temos e saem da fila sem trabalho nenhum. Outros doze têm
inventário praticamente inalterado e podem ser adotados em lote, sem análise individual.

A análise virou procedimento reprodutível, versionado por data, então as próximas
entregas de EGP atualizado passam pelo mesmo caminho e os resultados são comparáveis
entre rodadas.

---

## Ressalvas

Os números de fila, dependência e escopo vêm da validação com o inventário completo
reprocessado (02/09), não de estimativa. O detalhe está em
`BV_Migracao_SAS_Validacao_Nivel2_2026-09-02.md`.

Essa validação mediu a adoção dos 27 com conteúdo novo, incluindo os 6 vetados. É o
cenário do direcionamento do BV, adotar tudo, e não o que recomendamos. Se os 6 ficarem
de fora, a fila cresce menos, e quanto menos exige uma nova medição. As 3 consolidações
não confirmadas foram tratadas como reais; se alguma for falsa, o antecessor volta ao
corpus e o delta muda.

**Duas divergências entre a lista do BV e o nosso `sas_escopo`**, que precisam de
alinhamento porque mudam decisão:

- `Projecao_Rolagem - 3040 - 2026`: o BV diz fora do escopo; no nosso cadastro está
  ativo e em `Pré-conversão / Concluído`. É o **único** consumidor no escopo do
  `PAGOSCBR.PAGOS_CYBER_202603`. Se o BV estiver certo, o veto do
  `Performance_Saldo_COLORE_Lite_V5` também cai, e passam a ser **três** liberados em vez
  de dois.
- `Fechamento_Contabil_RPDD_3040`: o BV diz que está no escopo; ele não tem registro em
  `sas_escopo`, embora esteja no funil em `Pré-conversão / Concluído`. Inconsistência do
  nosso lado, a corrigir.

Nas outras 8 linhas da relação do BV o parecer de escopo casa exatamente com o nosso
cadastro.

Duas medidas específicas merecem cautela. Os números do `NuContratoContabil_Atualizado`
dependem de ele realmente substituir 4 EGPs, o que é o caso menos crível da lista. E o
volume de código do `PROJECT_ATIVA_TABLEAU_NEW_RPA` está inflado por código gerado
automaticamente, então não serve para estimar esforço.

---

## O que precisamos

**Da área de negócio, em um bloco:**

1. As 6 tabelas que desaparecem foram renomeadas ou extintas?
2. Os 4 EGPs de maior prioridade fazem o mesmo trabalho que os antigos?
3. Duas consolidações seguem sem confirmação: `PERFORMANCE_CL` e
   `Acompanhamento_Desconto`. As do `PROJECT_ATIVA` (e-mail de 26/08),
   `NuContratoContabil` e `Bases_Auxiliares` (relação de unificações) já estão
   confirmadas.
4. O `Projecao_Rolagem - 3040 - 2026` está dentro ou fora do escopo? A relação de
   unificações diz fora, o nosso cadastro diz dentro, e isso decide se o
   `Performance_Saldo_COLORE_Lite_V5` fica bloqueado.
5. Quais dos consumidores em risco **já têm versão nova** que aponta para a tabela nova,
   como o `Remuneracao_CL_202603`? Precisamos desses EGPs para o inventário parar de
   acusar quebra que já foi resolvida. Interessa em especial os 5 consumidores do
   `GRIMALDI...` e do `ENTREGA...`, que são os únicos bloqueios que restam.
6. A leitura do `PERF_CL.CL_TABLEAU` antigo pelo EGP novo é transitória (carga de
   histórico) ou permanente? Isso decide se a tabela sai da fila de ingestão depois da
   primeira carga.

**Da gestão, para seguirmos:**

7. Decisão sobre o `Project_Compensacao_Encargos_v1`, cuja versão antiga já foi entregue
   migrada: mantém ou refaz?
8. Aval para incluir os inputs novos no planejamento da próxima onda de ingestão.
9. Registrar no app a despriorização do `Performance_Produtos_V1`, já decidida. Enquanto
   não for registrada, o inventário continua apontando bloqueio que não existe mais.

Com as respostas de 1 a 6 e a decisão de 7, adotamos os EGPs liberados e refazemos a
medição de escopo na mesma semana.
