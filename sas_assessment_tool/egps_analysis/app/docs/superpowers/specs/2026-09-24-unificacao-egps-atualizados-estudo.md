# Estudo — unificar "EGPs Atualizados" (e os inputs deles) ao projeto

Data: 2026-09-24 · Status: **estudo, sem decisão tomada** · Autor: sessão Claude Code

Pergunta do pedido: *como unificar os EGPs atualizados e os inputs deles dentro do
projeto; vale mexer nas métricas ou ficamos com duas métricas separadas (anteriores ×
atualizados); e como mostrar que um EGP está desatualizado e outro atualizado.*

> **SUPERADO EM PARTE (24/09/2026).** A gestão decidiu régua diferente da
> recomendada aqui: os inputs das versões novas **entram nos contadores**, os funis
> atuais ficam intactos com um funil **novo** ao lado, e "Substituído" significa
> antecessor fechado + EGP novo no escopo, **contando os dois**. O desenho vigente é
> [`2026-09-24-egps-atualizados-unificacao-design.md`](2026-09-24-egps-atualizados-unificacao-design.md).
> As **medições** deste estudo seguem válidas (com a ressalva de que a população caiu
> de 46 para 45 EGPs na tarde de 24/09); a **recomendação** da §1 e §5, não.

Fonte dos números: **prod** (`bv_dev_db.monitoramento_sas`), medido em 24/09/2026, só
`SELECT`. Scripts de medição descartáveis (não versionados) rodaram em
`egps_analysis/venv`; todas as consultas estão reproduzidas ao longo do texto em prosa
suficiente para refazê-las. Contexto anterior: [`docs/adr/0001-egps-atualizados-isolamento-de-escrita.md`](../../../../../docs/adr/0001-egps-atualizados-isolamento-de-escrita.md)
(raiz do repo), `CONTEXT.md` (glossário) e `app/README.md` §"Aba EGPs Atualizados".

---

## 1. Resposta curta

**Não são duas métricas de migração; é uma métrica e uma fila de decisão.**

Uma versão nova de um EGP **não é trabalho novo** — é o mesmo trabalho com outro
conteúdo. Somar as duas populações duplica o denominador; manter "duas métricas de
migração" em paralelo sugere que existem dois estoques de trabalho, e não existem. A
única operação semanticamente correta sobre o indicador é **substituir** (adotar a
versão nova, aposentando o antecessor) ou **ignorar** (não adotar).

Portanto:

- **Não mexer nos funis, no escopo, na fila de ingestão nem no plano do mês** enquanto a
  troca não acontece. Nenhum contador deve se mover por causa de um `.egp` recebido.
- **Mexer numa coisa só:** marcar, no EGP do escopo, que ele está **desatualizado**. Isso
  não muda numerador nem denominador — muda a *confiança* do número (converter um EGP
  desatualizado é retrabalho potencial), que é exatamente o que hoje está invisível na
  hora de priorizar.
- A aba EGPs Atualizados continua sendo a **fila de decisão** (o que chegou, o que vale
  adotar, qual o impacto), não um segundo painel de migração.

O caso legítimo de soma é outro e é pequeno: **EGP inédito** (sem antecessor). Esse é
trabalho novo de verdade e deve entrar pelo caminho normal do escopo (aba Escopo/DOR1),
não como "EGP atualizado". Hoje são **2**.

---

## 2. O que foi medido (prod, 24/09/2026)

### 2.1 A população

| Medida | Valor |
|---|---|
| Versões recebidas / EGPs distintos | **48 / 46** |
| Janela de recebimento | 01/09/2026 → 23/09/2026 |
| Área | **100% Cobranças** |
| `status_troca` | **`recebida` em 46/46 — nenhuma troca efetivada** |
| Vínculo manual já confirmado na aba EGPs | 10 |

Quadrante da comparação determinística (última versão de cada EGP):

| Quadrante | EGPs | Antecessores no escopo **ativo** |
|---|---:|---:|
| Trocar depois | 13 | 10 |
| Não trocar (veto) | 11 | 9 |
| Trocar agora | 8 | 6 |
| Sem mudança (descartar) | 6 | 0 |
| Não trocar | 4 | 1 |
| Avaliar caso a caso | 2 | 1 |
| EGP inédito | 2 | — |

Confiança do pareamento automático: `nome_igual` 20 · `ok` 11 · `alerta` 11 · `manual` 2
· `sem_par` 2. Ou seja, **24 dos 44 pares com antecessor não são "nome igual"** (26 dos 46 contando os 2 `sem_par`) — o pareamento depende de
confirmação humana, e 10 já foram confirmados.

### 2.2 O que a soma ingênua faria com a contagem de EGPs

- **20 dos 46** `egp_key` são idênticos a um `projeto` já existente no corpus (16 deles no
  escopo ativo) → casariam sozinhos.
- **Os outros 26 mudaram de nome** (ex.: `ACORDO_AMIGAVEL_v1` → `ACORDO_AMIGAVEL_v1_RPA`;
  `base_carta_EVG_2026` → `CARTA_EGV_2026`) → entrariam como EGP novo, **enquanto o
  antecessor continua no escopo**. Somar hoje = **até +26 EGPs sobre os 168 ativos
  (+15%) em dupla contagem pura**.
- 3 EGPs do corpus são antecessores de **duas** versões novas cada
  (`PERFORMANCE_CL_202603`, `PERFORMANCE_CL_202603_REPROC_HIST_EDU`,
  `processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS`) — consolidação, que a soma
  também não sabe representar.

### 2.3 O que a soma ingênua faria com a fila de inputs

As 46 versões trazem **1.330 linhas de input / 716 chaves distintas**. O JOIN vivo com
`sas_inputs_monitor` casa **1.179 de 1.330 (89%)** — evidência de que a chave canônica da
carga **não** está quebrada (o risco nº 1 do ADR 0001 não se materializou).

Fora do corpus: **142 chaves** (125 tabela + 17 arquivo), das quais **102 `a_ingerir`** —
demanda de ingestão que hoje não aparece em indicador nenhum. Mas olhe de onde ela vem:

| Quadrante | chaves fora do corpus | destas, `a_ingerir` |
|---|---:|---:|
| Não trocar | 58 | **45** |
| Não trocar (veto) | 38 | **34** |
| Trocar depois | 20 | 14 |
| Sem mudança (descartar) | 11 | 3 |
| Avaliar caso a caso | 9 | 0 |
| **Trocar agora** | **7** | **7** |
| EGP inédito | 3 | 0 |

**79 dos 102 (77%) estão em EGPs que a comparação diz para NÃO adotar.** Somar hoje
inflaria a fila de ingestão com 79 pedidos de trabalho que nunca vão acontecer — e cada
um deles é uma conversa com o BV.

Na direção oposta, a adoção **encolhe** a fila: **320 chaves** existem só no antecessor e
sumiriam com a troca; **143 delas ficariam órfãs** (nenhum outro EGP do corpus as lê).

Isolando só os 8 "Trocar agora": **entram 7 chaves, saem 58 órfãs — saldo −51.**

Deltas agregados que o próprio compare já gravou, somados nas 46 versões: `table_in`
1.230 → 1.180 · `a_ingerir` 785 → 745 · disponíveis 445 → 435 · outputs 2.250 → 2.075
(com **12 outputs removidos que ainda têm consumidor externo** — risco de quebra) · 18
inputs de rede novos · 24 dependências novas.

### 2.4 O conflito agudo: o antecessor não está parado

Os **27 antecessores no escopo ativo têm todos mês no plano**. E o funil deles já andou:

| Etapa / status do antecessor | EGPs |
|---|---:|
| Pré-conversão / Concluído | 9 |
| Migrado / Despriorizado e Contabilizado | 6 |
| Projetos Habilitados / Block | 3 |
| Validação em DES / Em Andamento | 2 |
| Pré-conversão / Despriorizado e Contabilizado | 2 |
| Aprv. PR + Validação Governança / Em Andamento | 2 |
| Validação da Área / Em Andamento | 2 |
| Projetos Habilitados / A Iniciar | 1 |

Cruzando com o quadrante, **3 EGPs marcados "Trocar agora" já passaram da pré-conversão**:

- `Cobranças__REVISIONAIS_V1` — Validação em DES / Em Andamento
- `Cobranças__Elegibilidade_Reneg_CP` — Aprv. PR + Validação Governança / Em Andamento
- `Cobranças__Remuneracao_CL_202603` — Pré-conversão / Concluído

Estes são o argumento de urgência: **está se convertendo e validando em cima de versão
velha, e nada na tela de quem prioriza diz isso.** É o problema que a sinalização resolve
— e ele é independente de qualquer decisão sobre métrica.

---

## 3. As três leituras de "unificar" — comparação

| | **A. Substituir (troca)** | **B. Somar agora** | **C. Só sinalizar** |
|---|---|---|---|
| O que acontece com o número | 1 métrica; o novo ocupa o lugar do velho | 1 métrica inflada, ou 2 em paralelo | 1 métrica, intacta |
| EGPs no escopo | 168 (constante) | até 194 (**+26 fantasma**) | 168 |
| Fila de ingestão | −51 chaves só nos "Trocar agora" | **+102, dos quais 79 nunca acontecem** | inalterada |
| Fidelidade semântica | alta — é o mesmo trabalho | baixa — duplica trabalho | alta |
| Custo | alto (pipeline, ver §4) | médio (dedup por antecessor, herança de estado) | **baixo** |
| Reversível | não sem re-publish | não (contaminou histórico) | sim |
| Resolve o conflito agudo (§2.4) | sim | não (só mostra mais linhas) | **sim** |

**Duas métricas separadas de migração** (a leitura literal da pergunta) é a pior das
opções e não aparece na tabela por mérito próprio: exigiria manter funil, plano e fila
em duplicata para 46 EGPs que são os *mesmos* 52 EGPs já contados, e a soma das duas
nunca fecharia com o total do projeto. O que faz sentido manter separado não é uma
métrica de migração, é a **fila de decisão** (§6).

---

## 4. A troca é uma operação de PIPELINE, não de banco

Este é o achado que mais muda o custo do plano, e ele é verificável:
`publish_to_databricks.py` deriva `sas_inputs_monitor`, `sas_egp_inputs` e a linhagem de
**`06_prontidao_tabela.csv`**, que o `orchestrator_inventory.py` produz a partir dos
`.txt` do `egps_extractor.py`, que por sua vez lê **`received_egps/`** (cabeçalho do
próprio publish, linhas 5–10).

Consequência: **marcar `status_troca='trocada'` numa tabela Delta não troca nada.**
Enquanto o `.egp` novo não estiver no corpus físico e o pipeline local não for re-rodado,
os inputs, a linhagem e os outputs do app continuam sendo os da versão velha. Pior: um
"adotado" gravado só no banco é **revertido em silêncio no próximo Processar**, que é
exatamente o modo de falha que já aconteceu com o re-key do `CPF_Contrato` e das
planilhas `[SHEET=]`.

Logo, a adoção real tem três partes, nesta ordem:

1. **Corpus** — colocar o `.egp` novo em `received_egps/<ÁREA>/`, arquivar/remover o
   antecessor, re-extrair e re-rodar o orquestrador (~5,5 min).
2. **Escopo** — desativar o antecessor (`sas_escopo.ativo = false`, com motivo) e ativar a
   nova chave herdando mês, responsável, Jira e etapa/status do funil.
3. **Registro** — `status_troca = 'trocada'` + auditoria, feito **pelo publish** por
   reconciliação (a nova chave apareceu no corpus e o antecessor saiu), não por um botão
   otimista na tela.

O app pode (e deve) ser a fila e a evidência da decisão. Ele não pode ser o executor.

---

## 5. Recomendação

**Uma métrica de migração (a do projeto) + uma fila de decisão (a aba), com sinalização
cruzada entre as duas. Sem somar, sem duplicar funil.**

Em concreto:

1. **Nada muda nos contadores hoje.** Funis, escopo, fila de ingestão, plano do mês e
   Priorização ficam exatamente como estão enquanto `status_troca = 'recebida'`.
2. **O EGP do corpus ganha um estado de atualidade** (§6), que é informativo e entra nas
   telas onde se decide trabalho — EGPs, Priorização, Gestão.
3. **Os inputs da versão nova continuam fora da fila**, mas ficam *consultáveis* pela aba
   Inputs como "entra se adotar" / "sai se adotar" — badge e filtro, nunca contador.
4. **A adoção move o número, por substituição**, e é executada pelo pipeline (§4).
5. **EGP inédito não é "atualizado"**: entra pelo escopo normal. São 2; trate-os como
   dois DOR1 novos e tire-os da conversa de unificação.

O que se ganha sem mexer em métrica nenhuma: os 3 EGPs do §2.4 param de ser convertidos
às cegas, e os 21 EGPs cuja versão nova é veto/descarte param de gerar ruído.

---

## 6. Como mostrar "desatualizado" × "atualizado"

### 6.1 O que já existe

Na aba EGPs (`ReadinessView.tsx:542`) o EGP do corpus já exibe um badge **🔄** quando há
versão atualizada vinculada, com duas variantes visuais: confirmada (`rd-atu-confirmed`)
e sugestão automática (`rd-atu-suggested`), mais o `AtualizadoLinkButton` para confirmar
ou trocar o vínculo. O inverso — a aba Atualizados mostrando o antecessor com etapa,
status e recorte — também existe (`_anexa_antecessores`).

**O defeito não é ausência de sinal, é sinal indiscriminado:** o mesmo 🔄 aparece para
"Trocar agora" e para "Não trocar (veto)". Dos 46, **21 (46%) são veto, "Não trocar" ou
"Sem mudança"** — quase metade do badge atual é ruído, e ruído treina o usuário a ignorar
o sinal que importa.

### 6.2 Os quatro estados propostos

Todos deriváveis de dados que **já existem** (`atualizado_link_key`, `egp_atualizado_key`,
`quadrante`, `status_troca`, `data_recebimento`) — nenhuma coluna nova na fase 1.

| Estado | Quando | Como aparece no EGP do corpus |
|---|---|---|
| **Desatualizado** | há versão vinculada, `status_troca='recebida'`, quadrante adotável (`Trocar agora` / `Trocar depois` / `Avaliar caso a caso`) | badge âmbar **"desatualizado"** + data de recebimento; tooltip com o quadrante. **Com destaque forte** se a etapa do EGP já passou da pré-conversão (o caso §2.4) |
| **Versão nova recusada** | vinculada, mas quadrante `Não trocar` / `(veto)` / `Sem mudança (descartar)` | badge **cinza**, discreto, tooltip com o motivo do veto. Não é alerta: é registro de que já se olhou |
| **Em dia** | `status_troca='trocada'` | ✓ discreto com a data da adoção. Estado calmo — não compete por atenção |
| **Sem versão nova** | nenhum vínculo | nada (o silêncio é o default correto) |

Regras de leitura que evitam falso positivo:

- **Sugestão automática ≠ fato.** Enquanto o humano não confirma o vínculo, o rótulo é
  "possível versão nova" com `?`, como o `AtualizadoLinkButton` já faz. 22 dos 46 pares
  não são `nome_igual`, então isto não é detalhe.
- **O badge nunca altera contador.** É a invariante que mantém a opção reversível.

### 6.3 Onde o estado precisa aparecer (além da aba EGPs)

- **Priorização / plano do mês** — os 27 antecessores no escopo têm mês atribuído. Um EGP
  desatualizado no mês corrente é a informação mais acionável do estudo inteiro; hoje ela
  não existe na tela.
- **Gestão** — mesma linha, para quem edita etapa/status decidir antes de empurrar o EGP
  para a próxima etapa.
- **Aba Inputs** — badge informativo "entra se adotar" (142 chaves) / "sai se adotar"
  (320, das quais 143 órfãs), com filtro. Fora de todo contador.
- **Drawer do EGP** — bloco "Versão atualizada recebida", com o delta que o compare já
  calculou e link para `/egps-atualizados/<versao_id>`.

### 6.4 O lado da aba Atualizados

O que falta lá é o espelho honesto do §2.4: mostrar, ao lado do quadrante, **quanto o
antecessor já andou**. "Trocar agora" num EGP em Validação em DES não é a mesma decisão
que "Trocar agora" num EGP A Iniciar. O dado já chega via `_anexa_antecessores`; falta
promovê-lo a critério de ordenação da fila.

---

## 7. Plano em fases

Cada fase tem critério verificável. As fases 0–1 não tocam em métrica; a 2 é a única que
move número, e move por substituição.

### Fase 0 — Semântica do sinal (baixo custo, alto valor)

Separar os quatro estados do §6.2 e parar de alertar sobre versão recusada.

**Verifica:** dos 46 EGPs vinculados, exatamente **21** deixam de exibir alerta (passam a
badge cinza) e **23** permanecem como "desatualizado" (13 Trocar depois + 8 Trocar agora +
2 Avaliar), sendo **3** com destaque forte (§2.4). Snapshot dos contadores dos funis antes
e depois: **idênticos**.

### Fase 1 — Sinal onde se decide trabalho

Estado de atualidade exposto em Priorização, Gestão e drawer; badges "entra/sai se
adotar" na aba Inputs, com filtro.

**Verifica:** teste de backend que, para um EGP com troca pendente e mês no plano, o
endpoint devolve a flag; teste de regressão que os quatro funis (`migracao`, `ingestao`,
`migracao_deps`, `ingestao_deps`) devolvem os **mesmos números** antes e depois da
mudança.

### Fase 2 — Adoção (a troca de verdade)

O procedimento de três partes do §4, com o app registrando a decisão e o publish
reconciliando. Piloto com **1 EGP**, de preferência um dos 3 do §2.4.

**Verifica, no dev, com 1 EGP adotado:**
- escopo continua com **N** EGPs ativos, não N+1 (o antecessor saiu);
- mês, responsável, Jira e etapa/status foram herdados (nenhum campo humano perdido);
- a fila de inputs muda **exatamente** pelo delta medido para aquele EGP (entram X, saem
  as órfãs Y) — número conferido antes da adoção;
- rodar o publish **duas vezes** e confirmar que a adoção sobrevive (é a armadilha do §4);
- auditoria registra a troca com autor e data.

### Fase 3 — EGPs inéditos

Os 2 entram pelo fluxo normal do escopo (DOR1). **Verifica:** escopo ativo vai a 170 e
os inputs deles aparecem na fila pelo caminho padrão, sem nenhum código específico de
"atualizados".

---

## 8. Armadilhas registradas

- **Re-publish reverte decisão gravada só no banco** (§4). Vale para a troca, como já
  valeu para o re-key do `CPF_Contrato` e das planilhas `[SHEET=]`.
- **Família de safras.** Com `FAMILIAS_SAFRA=1` a aba Inputs conta famílias; a aba
  Atualizados ainda conta **por safra**. Qualquer cruzamento de contagem entre as duas
  precisa passar por `familias.py`, ou os números divergem por construção.
- **Chave canônica.** O JOIN casa 89% hoje; se a regra da carga divergir do pipeline,
  tudo vira "fora do corpus" em silêncio (ADR 0001). Vale uma sentinela sobre essa
  taxa — queda brusca é bug, não mudança de conteúdo.
- **12 outputs removidos com consumidor externo.** Adotar uma versão que deixou de
  produzir uma tabela que outro EGP lê quebra o consumidor. É veto de adoção, não
  detalhe de inventário.
- **Antecessor `Despriorizado e Contabilizado` (8 dos 27).** Adotar versão nova de EGP
  despriorizado é contradição — a fila de decisão deve filtrá-los por padrão.
- **Pareamento não confirmado.** 34 dos 44 pares com antecessor ainda não passaram por confirmação humana.
  Nenhuma automação de troca deve agir sobre vínculo automático.

## 9. Fora de escopo deste estudo

Ordenação/priorização da fila de adoção (o Valor × Esforço do compare já existe e não foi
reavaliado aqui); o botão de troca restrito a `bv_admins` previsto na fase 2 do design
original; e qualquer mudança no `compare_egp_versions.py`.

---

## 10. Decisões que precisam da gestão

Nenhuma delas é técnica: são decisões de régua, de risco e de capacidade. As três
primeiras **travam** o trabalho; as outras podem ser confirmadas na mesma conversa.

### Travam o trabalho

**D1 — A régua: receber um `.egp` novo muda indicador?**
Recomendação: **não**. Escopo, funis, fila de ingestão e plano do mês só se movem quando
a versão é adotada. Alternativa (somar já) custa +26 EGPs fantasma no escopo e +79
pedidos de ingestão que nunca acontecem (§2.2, §2.3).
*O que muda no relatório mensal:* nenhum número atual; passa a existir uma linha nova —
"N EGPs do escopo estão desatualizados". Se a gestão espera ver "46 EGPs novos" no
fechamento, é aqui que se alinha a expectativa.
*Trava:* fases 0 e 1 inteiras.

**D2 — Os 3 EGPs em conflito agudo: continua, refaz ou congela?**
`REVISIONAIS_V1` (Validação em DES), `Elegibilidade_Reneg_CP` (Aprv. PR + Governança) e
`Remuneracao_CL_202603` (Pré-conversão Concluído) estão sendo convertidos/validados em
cima de versão que o BV já substituiu, e os três são quadrante "Trocar agora".
Recomendação: **a pergunta que resolve os três é para a área dona — qual versão roda em
produção hoje?** Sem essa resposta, continuar é apostar e refazer é caro.
*Trava:* a fase 2 (piloto de adoção) não tem candidato definido.

**D3 — Capacidade: adoção compete com o plano de 400/mês.**
Os 27 antecessores no escopo ativo **têm todos mês atribuído**. Uma troca re-abre trabalho
já planejado. Decisão: reservar quota explícita (ex.: N trocas/mês) ou tratar toda troca
como exceção aprovada caso a caso.
*Contrapeso a favor:* adotar os 8 "Trocar agora" tira **51 chaves líquidas** da fila de
ingestão (7 entram, 58 órfãs saem) — são 51 pedidos a menos para o BV.
*Trava:* sem quota, a troca não acontece por falta de slot, e a fila de decisão vira
backlog morto.

### Processo e risco (mesma conversa, não travam)

**D4 — Quem assina a adoção de cada versão?**
Opções: (a) o quadrante do compare decide sozinho; (b) o quadrante propõe e a gestão
Indicium decide; (c) a área dona do BV assina cada troca.
Recomendação: **(b)**, com veto obrigatório do BV nos casos que removem output ainda
consumido (são **12** no conjunto — adotar quebra o consumidor).

**D5 — As 21 versões recusadas: o que se comunica ao BV, e quem?**
11 veto + 4 "Não trocar" + 6 "Sem mudança". O risco é assimétrico: seguimos migrando a
versão velha enquanto o BV pode já estar rodando a nova. Decisão: aceitar e registrar, ou
pedir confirmação da área por EGP antes de manter a versão antiga.

**D6 — Contrato de recebimento.**
46 EGPs em 23 dias, **100% de uma única área** (Cobranças). A gestão precisa dizer se as
demais áreas também vão reenviar versões e com que cadência — é o que define se a adoção
vira processo automatizado ou continua exceção manual.

**D7 — Governança da troca.** Quem pode aposentar um EGP do escopo (a troca desativa o
antecessor e herda mês/responsável/Jira). Hoje o desenho previa botão restrito a
`bv_admins`; confirmar se é essa a alçada.

### Confirmações rápidas

**D8 — EGP despriorizado com versão nova (8 dos 27):** confirmar que **não se adota** —
adotar versão nova de EGP despriorizado é contradição. A fila deve filtrá-los por padrão.

**D9 — Os 2 EGPs inéditos entram no escopo?** Não têm antecessor: é trabalho novo de
verdade. Se entram, vão pelo caminho normal (DOR1) e o escopo ativo passa de 168 a 170.
