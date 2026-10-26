# EGPs Atualizados — unificação com o corpus: processo e regras

Data: 2026-09-24 · Status: **régua fechada com a gestão; não implementado**
Estudo com as medições: [`2026-09-24-unificacao-egps-atualizados-estudo.md`](2026-09-24-unificacao-egps-atualizados-estudo.md)
Precedentes: `docs/adr/0001-egps-atualizados-isolamento-de-escrita.md` e
`docs/adr/0002-familia-de-safras-como-unidade-de-input.md` (raiz do repo), `CONTEXT.md`,
`app/README.md` §"Aba EGPs Atualizados".

> Este documento **substitui integralmente** a versão anterior do mesmo arquivo. A régua
> mudou em vários pontos durante a definição do processo (o tipo de vínculo passou a ser
> flag no antecessor, "Desatualizado" virou status, deixou de existir decisão de adoção).
> Os **números** vêm do estudo e de medições de 24/09/2026 — cada um com sua data, porque
> a população da aba mudou três vezes no mesmo dia (46 → 45 → **39** EGPs, limpeza feita
> por outra sessão).

> **Estado em 25/09/2026:** §1 a §3 implementados e verdes no worktree
> `cached-wiggling-hopper` (302 testes no backend, 6 arquivos no frontend, `vite build` ok),
> **não commitado e não deployado**. Falta: a entrada no corpus (§2 etapas 0–2, bloqueada
> pelos `.egp` que não estão neste checkout), o funil de sucessores (§3.1.3), a sanitização
> derivada (§3.4.15–18) e a aposentadoria da aba (§5). Plano:
> [`../plans/2026-09-25-vinculo-egp-sucessor.md`](../plans/2026-09-25-vinculo-egp-sucessor.md).

---

## 1. Papéis e vocabulário

**Antecessor** — o EGP do corpus que já existia. **Sucessor** — a versão recebida, depois
de entrar no corpus. O vínculo é um par ordenado (antecessor → sucessor) e mora **no
antecessor**, em dois campos:

- **Tipo de vínculo**: como o antecessor está ligado ao sucessor — `Atualizado`,
  `Substituído` ou `Unificado`.
- **Sucessor**: qual EGP é o atualizado / substituto / unificador.

| Tipo | O que significa | Efeito no antecessor | Efeito no sucessor |
|---|---|---|---|
| **Atualizado** | nova versão do mesmo EGP | status `Desatualizado`, etapa espelhada | fica fora do escopo |
| **Substituído** | o antigo sai e outro EGP entra no lugar | fechado como `Despriorizado e Contabilizado` | **entra no escopo** |
| **Unificado** | N antecessores → 1 sucessor | os N ficam `Desatualizado`, etapa espelhada | fica fora do escopo |

**Não existe decisão de adoção.** Só sobe para o app o que vai ser usado — versão que não
vai ser usada não é carregada, e a que já estiver carregada é removida (§4, Descarte).

**O tipo é humano, não derivado.** Medido em 24/09 (população 45): nome e `overlap_tasks`
não separam Atualizado de Substituído — `tipos_acordo` tem **nome igual e overlap 0,0**
(conteúdo inteiramente outro), e **4 casos de nome diferente têm overlap ≥ 0,8**
(`GESTAO_BNDU` → `GESTAO_BNDU_RPA`, 0,94). A distinção é de intenção do cliente, não de
assinatura do arquivo. O app **sugere** (2+ antecessores → Unificado; 1 com nome igual →
Atualizado; 1 com nome diferente → Substituído) e a gestão confirma.

---

## 2. Etapas do processo

**0 · Chegada.** O BV envia o arquivo. Ele vai para `received_egps_atualizados/<AREA>/`,
pasta **irmã** de `received_egps/` e com a mesma estrutura — a área do EGP vem do nome da
subpasta de 1º nível, então uma pasta dentro da área quebraria a área (e o extrator nem
varre `.egp` no 2º nível). Nenhum efeito no app.

**1 · Carga na aba.** `publish_egps_atualizados.py` publica a versão (comparação +
inventário). O antecessor sugerido pelo pareamento automático ganha o badge **"possível
versão nova"** — sugestão, não fato. Nenhum contador muda.

**2 · Entrada no corpus.** Extrator → orquestrador → publish (~5,5 min). O sucessor vira
projeto do corpus com chave `Área__nome__ATU<data de recebimento>`. O sufixo é obrigatório:
a chave é `Área__nome` e **12 versões têm nome idêntico ao antecessor** (medido com 45),
o que colidiria. Não reusar `__v2`/`__v3` — no corpus isso já significa homônimo de outra
pasta, e misturar os dois sentidos numa chave só custa caro depois.

*A partir daqui os inputs do sucessor contam* (§3.4).

**3 · Vínculo.** A gestão escolhe o tipo e aponta o sucessor. **Só é possível depois da
etapa 2** — antes disso o ponteiro apontaria para um EGP que não existe, e o espelhamento
e a sanitização agiriam sobre o vazio. Efeitos, todos derivados do vínculo:

- o antecessor passa a exibir status **`Desatualizado`**;
- a **etapa** do antecessor vira espelho da etapa do sucessor, **bloqueada para edição**;
- **etapa**, mês, Jira e responsável são **copiados** para o sucessor (cópia no ato —
  depois cada um segue sozinho);
- os inputs exclusivos do antecessor passam a contar como **`Sanitizado`**;
- no **Substituído**: o app *sugere* fechar o antecessor como `Despriorizado e
  Contabilizado` e o sucessor entra no escopo.

**4 · Execução.** O trabalho acontece no sucessor: etapa e status editáveis nele, no
`sas_egp_pipeline` como qualquer projeto, e é ele que aparece no funil de sucessores. O
antecessor segue ocupando a vaga no escopo e no plano do mês.

**5 · Próxima versão.** Uma v3 repete o processo desde a etapa 0 e o sucessor v2 vira
antecessor dela — **cadeia**, sem apagar arquivo. O corpus cresce a cada reenvio; é
intencional.

**Descarte.** Versão que não vai ser usada é **removida da aba**, sem registro de recusa.

---

## 3. Regras de funcionamento

### 3.1 Contagem de EGPs

1. Os funis atuais (**escopo** e **escopo + dependências**) mantêm a régua: o antecessor
   continua contando, inclusive nos Unificados, onde os N antecessores contam N.
2. **O total de EGPs é uma LISTA CONGELADA. `extra` é outra pergunta: quem tem vínculo de
   atualização com outro EGP.**
   *(Reescrito em 29/09/2026 — decisão da gestão; substitui a régua de 28/09, que ainda
   calculava o total e apenas descontava dele os sucessores e as cascas. **Corrigido no
   mesmo dia**, depois de a régua nova ser vista em uso: ela unificava contagem e rótulo
   num conjunto só e por isso rotulava de `extra · novo` toda ex-dependência que não
   entrava no total — 16 em produção, 19 no schema de dev, nenhuma recém-chegada. Contar
   e rotular voltaram a ser duas perguntas separadas.)*

   **O total deixa de ser calculado.** Ele é o tamanho de uma lista versionada:
   `egps_analysis/src/linha_base_congelada_2026-09-29.csv`, **193 projetos**, colunas
   `projeto,classe`, com `classe` ∈ `base` (168) · `dependencia` (11) ·
   `ex_dependencia` (14). A foto foi capturada de produção em 29/09/2026, em leitura.

   - **Fora da lista = fora do total.** Isto vale para **todo mundo**, inclusive o que o
     grafo classificaria como dependência: uma dependência inédita não entra calada no
     denominador, que era o buraco da régua de 28/09. Aqui não há enumeração de portas de
     entrada — a lista diz quem conta, ponto.
   - **`extra` é o 4º valor do filtro Tipo, e é uma ENUMERAÇÃO**: o EGP que tem **vínculo
     de atualização com outro EGP do corpus** — o **sucessor** apontado por um vínculo
     (`egp_sucessor`) e a **casca** (que tem `unificado_em`) — e que não está na lista.
     Continua sendo um valor só no filtro; a distinção (`sucessor` · `casca`, e **só**
     esses dois) fica no detalhe.
   - **Estar fora da lista NÃO é ser `extra`.** São eixos independentes: `na_linha_base`
     responde *conta?*, `e_extra` responde *é versão nova/casca?*. Juntá-los foi o defeito
     de 29/09: `extra · novo` afirmava "chegou depois do congelamento" sobre 16
     ex-dependências que estão no corpus desde junho. A dependência inédita segue fora do
     total **sem** ganhar rótulo.
   - **Ex-dependência NUNCA é `extra`.** O badge de ex-dependência já diz o que ela é, e um
     segundo rótulo só mentiria sobre quando ela chegou. Era daí que vinha a discordância
     entre a TELA (que lista as ex) e o CONTADOR (que conta sobre o frontier, onde a ex não
     está por definição): 37 × 18 no schema de dev. Os dois passam a falar do mesmo
     conjunto — travado por `test_extra_enumeracao.py`.
   - **Sucessor que ESTIVER na lista não é extra**: ele já conta no denominador, e marcá-lo
     seria contá-lo duas vezes — uma no total e outra no contador ao lado.
   - **Congelado nos DOIS lados.** Quem **sai** do escopo continua no denominador, e
     `Despriorizado e Contabilizado` segue dentro — é o que "Contabilizado" sempre quis
     dizer. Remoção e dedup deixam de mexer no número. O progresso passa a ser medido
     contra um total que nunca muda.
   - **Só o DENOMINADOR congela.** Congelado é *quais* projetos contam e a *classe* de
     cada um. Etapa, status (inclusive os derivados `Desatualizado` e a etapa espelhada),
     barras dos funis, coorte, migrados, inputs, fila de ingestão, Kanban, Priorização e
     Gestão continuam derivados do estado atual a cada leitura. É **"X de 193"**, com o
     193 parado e o X se mexendo o tempo todo.
   - **A decomposição exibida vem da classe GRAVADA**, não de um cálculo vivo: os cards
     "escopo / deps / ex" da aba EGPs, os cards da Visão geral (`egps_escopo`, `deps`,
     `deps_ex`) e os denominadores dos dois funis de migração (168 no escopo, 193 no
     +deps) saem todos do CSV. O universo dos funis é a própria lista, para que um EGP que
     saiu do escopo continue mostrando a etapa dele na barra: sumir da barra e ficar no
     denominador faria o funil parecer ter regredido sem ninguém ter desfeito trabalho.
   - **O critério "189" foi absorvido.** "Ex-dependência só conta com etapa real"
     (2026-08-10) era a régua que decidia quais ex entravam no total; quem estava
     contabilizado no dia da foto entrou na lista com a classe `ex_dependencia` e lá fica.
     `_ex_deps` continua vivo para a LISTA da aba (badge, retenção, auditoria) — só não
     decide mais contagem. **Inclusive no front:** cada linha do readiness carrega
     `na_linha_base`, e é ele que `contaNoTotalEgp` lê. Reaplicar o critério antigo sobre a
     etapa VIVA fazia a tabela divergir do card por drift — medido em 29/09 no schema de
     dev: 6 ex da lista já tinham perdido a etapa e a tabela mostrava 187 onde o card dizia
     193.
   - **Contável que some do corpus continua LISTADO.** "Congelado nos dois lados" vale
     também para a tabela: um projeto da lista que saiu do grafo ganha linha vazia em vez
     de desaparecer — senão a tabela diria 192, o card 193, e ninguém saberia qual faltou.
     Em 29/09 o conjunto é vazio nos dois schemas; é guarda, não caso corrente.
   - **Três motivos, três LISTAS** *(o 3º entrou em 29/09/2026)*: `sucessor` (tem vínculo),
     `casca` (absorvido por um unificador) e **`novo`** — declarado à mão em
     `sas_app_config`/`egps_novos`, para o EGP que entrou no escopo e **não substitui
     ninguém**. Caso que o motivou: o `Cobranças__ROI` (*"entra como um a mais mesmo"*),
     que não cabia nem nos 193 (congelados) nem em `extra` (que só conhecia vínculo) e
     sobrevivia apenas na aba que o §5 aposenta.
     **Não é o `novo` do ticket 19 voltando.** Aquele era `recorte − linha_base`, uma
     DEFINIÇÃO por exclusão, e foi ela que rotulou 16 ex-dependências de "chegou depois do
     congelamento" em produção. Este é lista: ninguém entra sem ter sido nomeado, e quem já
     está na linha de base é descartado na leitura. A guarda em `test_vinculos.py` deixou
     de proteger o NOME do motivo e passou a proteger o invariante —
     `test_extra_nunca_volta_a_ser_definicao_por_exclusao`.
   - **O ESPELHO também atravessa a cadeia** *(29/09/2026)*. A etapa exibida do antecessor
     sai do **fim** da cadeia de espelhamento (`vinculos.fim_do_espelho`), não do sucessor
     direto: quando o sucessor também espelha, a etapa crua dele é vazia por construção, e
     o antecessor exibia nada. Medido: 2 EGPs da linha de base com `Projetos Habilitados` e
     `Pré-conversão` gravados caindo fora do coorte do funil e da tabela por mês — trabalho
     feito sumindo da tela por causa de um vínculo. `Substituído` encerra a cadeia (lá o
     sucessor começa do zero). **A cópia do §3.3.11 passou a escrever no mesmo lugar**: o
     fim da cadeia, e não o sucessor direto — escrevendo no direto ela caía na própria
     guarda de cadeia e não copiava nada.
   - **A CADEIA inteira entra, não só o 1º salto** *(corrigido em 29/09/2026)*. O BV manda
     versão nova da versão nova (`…score_solar_jul_25 → jul_26 → set_26`). O recorte fazia
     **uma passada só** sobre os sucessores, então o `set_26` ficava gravado no vínculo e
     **invisível em tela nenhuma** — dado quebrado em silêncio, que é exatamente o que a
     cadeia já prevista pelo desenho (§3.2.7) não podia produzir. Agora é fecho
     (`vinculos.cadeia_de_sucessores`), com a regra de entrada intacta: a cadeia só começa
     num antecessor que **já está** no recorte. Antecessor fora do recorte segue sem puxar
     nada — é o caso do `Project_Fyf_Reneg_v2`, que tem vínculo e não aparece.
   - **Vale também para o `Substituído`**: o sucessor é extra como qualquer outro. Não há
     dupla contagem — o antecessor fecha como `Despriorizado e Contabilizado` e segue
     contando, e o sucessor conta entre os extras.
   - **O contador de extras diz quantos E quais.** Na aba EGPs o "+N extra" é um botão que
     filtra a tabela para eles; no Resumo, o tooltip do card lista os projetos
     (`GET /api/egps-extras`). Um número sem lista não é rastreável até um EGP.
   - **O seletor de recorte da aba EGPs tem CINCO valores** (29/09/2026): `só Indicium` ·
     `Indicium + dependências` (**exatamente os 193**, sem extra) · `todos` ·
     `Indicium + dependências + extras` · `só os extras`. Os dois últimos são vistas da
     mesma consulta `indi_deps`, filtradas na tela (`vinculo.recorteApi`): consultar o
     servidor duas vezes para o mesmo recorte é como a tabela e o contador voltariam a
     discordar. O botão "+N extra" do card e o seletor mexem no mesmo estado — um
     mecanismo só.
   - **A lista é dado versionado, com a data no nome.** Ela é lida do arquivo (como o
     publish lê `src/egps_casca.csv`), e **arquivo ausente explode** em vez de virar lista
     vazia — sem a linha de base o total seria um número inventado, e um zero silencioso é
     pior do que um 500. Trocar a linha de base exige arquivo novo e mudar `ARQUIVO` em
     `app/backend/linha_base.py`: ato deliberado, nunca efeito colateral de um republish.
   - Em uma frase: **o denominador é fixo, o numerador se move.**

3. **Funil de extras**: um terceiro gráfico no **Resumo**, ao lado de "escopo" e
   "escopo + dependências", sobre **todos os extras que entraram no corpus** — sucessores
   com ou sem vínculo, e cascas —, usando as **mesmas 9 etapas de migração**. Extra sem
   vínculo aparece sem etapa, que é o estado honesto. É um **recorte** sobre os EGPs do corpus, não um
   funil sobre outra entidade: mesma maquinaria dos outros dois.
4. Na aba unificada, o sucessor é **linha própria**, com a coluna "Tipo de vínculo"
   dizendo o que ele é. A aba segue o comportamento de hoje (recorte, filtros, edição
   inline), mais as informações do vínculo.

### 3.2 Status e etapa

5. **`Desatualizado` é um status** (7º valor), nunca uma etapa. Conta no total e **nunca
   conta como migrado**. *(Revisto em 28/09/2026: a versão anterior pedia **banda visual
   distinta**, como `Despriorizado e Contabilizado`. Não foi entregue e a exigência caiu —
   o conjunto `BANDS` está sobrecarregado, pois define ao mesmo tempo a cor e quem conta
   como migrado, e pôr `Desatualizado` ali violaria o "nunca conta como migrado" desta
   mesma regra. O status continua legível pelo rótulo e pela coluna do Kanban. Se algum dia
   valer a pena, o caminho é separar os dois conjuntos — não emendar o `BANDS`.)*
6. Ele é **derivado** da existência do vínculo, não gravado: o status real do antecessor
   (`Em Andamento`, `Block`…) fica intacto por baixo e reaparece se o vínculo for desfeito.
7. A **etapa** do antecessor é espelho da etapa do sucessor e **o backend recusa** qualquer
   tentativa de alterá-la — bloqueio no servidor, não só na tela.
8. O antecessor **não espelha o status** do sucessor: o status dele é `Desatualizado`.
9. **Despriorizado vence**: EGP que já é `Despriorizado e Contabilizado` e ganha vínculo
   continua despriorizado, e o vínculo vira badge. São **10 antecessores** hoje.
10. No Kanban, a coluna sai da **etapa**; `Desatualizado` entra como coluna pela mesma
    precedência de status que `separarDespriorizados` já implementa (`kanbanColKeyOf`).

### 3.3 Atribuição de trabalho

11. **Etapa**, mês do plano, Jira e responsável são **copiados** para o sucessor no ato do
    vínculo e a partir daí divergem livremente. Medido em 24/09: dos 42 antecessores,
    **35 têm mês**, 33 têm Jira, 36 têm responsável.

    **Por que a etapa entra na cópia** (decisão de 25/09): o funil `+deps` conta os EGPs do
    recorte **que têm etapa**. Sem a cópia, no instante do vínculo o antecessor passaria a
    espelhar a etapa do sucessor, que acabou de entrar no corpus e **não tem etapa** — e um
    EGP que estava em "Validação em DES" sumiria da coluna sem que trabalho algum tivesse
    sido desfeito. O total do funil não mexeria, mas a **distribuição** esvaziaria. Copiando,
    a transição fica invisível no funil e quem executa ajusta a partir dali. Mesmo raciocínio
    do mês e do Jira: é o mesmo trabalho continuando noutro arquivo, não trabalho novo.
12. O plano da Priorização segue **congelado**: os contadores vivos mudam de imediato, o
    plano do mês só muda quando a gestão clicar em Recalcular + Salvar.

### 3.4 Inputs

13. Os inputs do sucessor **entram junto com o recorte** (§3.1.2) — não há bloco separado
    a somar. O universo de inputs do `indi_deps` passa a incluir os EGPs sucessores, pela
    mesma maquinaria de sempre. É a razão de o sucessor precisar estar no recorte: o
    antecessor carrega os inputs **velhos**, e são os do sucessor que viraram trabalho.
    - **Mas dá para ver quanto é deles** *(revisão da gestão, 29/09/2026)*. "Entram junto"
      valia para o **denominador** e continua valendo — o Total de Inputs não mudou. O que
      mudou é que eles pararam de ser invisíveis: a Visão geral ganhou um **grupo próprio**
      ("Extras, fora da linha de base") e a aba Inputs ganhou o filtro *só inputs de
      extras*. O que motivou: 5 das unidades do grupo "Escopo Indicium" eram os inputs
      sintéticos `casco::` das cascas — placeholder contado como inventário do escopo.
    - **Duas contagens, de propósito, porque são duas perguntas.** O **grupo** conta só o
      que **nenhum EGP contável lê** (28 unidades em 29/09): os três grupos particionam o
      Total, e a chave compartilhada pertence à linha de base, senão ela contaria duas
      vezes. O **filtro** mostra **tudo que algum extra lê** (190), inclusive as 162
      compartilhadas — lá a pergunta é "o que a versão nova consome". Os dois números não
      batem, e não devem: `de_extra` e `so_de_extra` são campos separados na linha
      (`_marca_extra`), nunca um derivado do outro na hora de exibir.
14. Não há dupla contagem por chave: das 716 chaves que as versões traziam (medido com 45),
    **574 já existiam no corpus** — input é contado por chave canônica distinta. O
    crescimento real era de **+142 chaves, 102 a ingerir**.
15. Input lido **só** pelo antecessor passa a contar como **`Sanitizado`** — derivado, sem
    escrever status. Continua **visível** na aba, com o rótulo; não some.
16. **Exclusividade é medida contra o escopo ativo**, não contra o corpus. Medido em 24/09:
    os 42 antecessores leem 736 chaves, das quais **371 são exclusivas no escopo** e 298 no
    corpus inteiro.
17. Input lido por **qualquer outro EGP** do escopo não é tocado.
    - **As duas origens se somam** *(decisão da gestão, 28/09/2026)*. A chave sai da fila
      quando **todos** os consumidores dela no escopo estão resolvidos — seja por estarem
      despriorizados (§3.4.18), seja por serem antecessores com sucessor (§3.4.15) —,
      inclusive **misturando** as duas origens. A régua é uma só: *input que só quem não vai
      trabalhar lê não é trabalho.* Tratar as duas como listas separadas deixava na fila
      chaves que ninguém vivo consome.
    - **O sucessor segura o input sozinho.** Ele está no recorte e **não** é antecessor,
      então conta como consumidor vivo: se a versão nova também lê a chave, ela **continua
      na fila**, por mais resolvidos que estejam os demais consumidores. É o que impede a
      régua de sanitizar justamente o inventário que passou a valer.
18. A mesma regra vale para **EGPs despriorizados**: input lido só por despriorizados conta
    como `Sanitizado`. Medido: **370 chaves**, das quais **202 já estavam sanitizadas na
    mão** — a regra derivada chega no mesmo lugar que a prática —, **110 "A receber" e 22
    sem status** sairiam da fila. As sanitizações manuais ficam como estão.

**Fragilidade e log** *(decisão da gestão, 28/09/2026 — ambos pedidos.)*

Medir exclusividade contra o **escopo ativo** (§3.4.16) tem um preço conhecido: até **73
chaves** voltam à fila sozinhas no dia em que um EGP hoje fora do escopo entrar. Isso não
pode ser descoberto por acaso. Mas o estado é **derivado e nunca gravado** — sem baseline,
"mudou" não é detectável, e gravar o estado para detectar mataria a reversibilidade, que é
a razão de o desenho ser derivado. Daí dois mecanismos, e não um:

- **Fragilidade (o presente, nada gravado):** aviso permanente — *"N chaves estão fora da
  fila só porque M EGPs estão fora do escopo"* —, com o rollup inverso `EGP fora → quantas
  chaves voltariam`, que é a pergunta acionável. Não é alerta de mudança: é a exposição de
  um risco que existe o tempo todo, e usa só o presente, que é o que o desenho derivado sabe.
- **Log diário (o passado):** uma linha por dia em `sas_app_config`, `MERGE` sem
  `WHEN MATCHED` — a primeira foto do dia vence e história não é reescrita. Grava **só
  contadores**, nunca chave.

**A regra dura:** *desligar o log não pode mudar nenhum número da fila.* Nenhum `SELECT`
lê `san_contadores` — a independência é estrutural e está travada por teste, não por
convenção. No dia em que o log virar fonte de verdade em qualquer caminho, a
reversibilidade morre.

**Três motivos, não dois.** O caso misto (consumidores de origens diferentes) tem rótulo
próprio — *"só consumidores despriorizados e antecessores"* —, porque reusar um dos dois
esconderia a outra metade da explicação.

### 3.5 Permissões e escrita

19. Criar, trocar e desfazer vínculo é **da gestão** (`bv_users`), com o mesmo peso de um
    DOR1 — classificar como Substituído faz um EGP entrar no escopo e outro fechar.
20. O **isolamento de escrita do ADR 0001 continua**: `sas_egp_atualizados*` só é escrito
    pelo script local. O vínculo mora na tabela de estado do antecessor, que já existe e
    nunca é dropada.
21. **Classificar nunca muda status sozinho.** No Substituído, fechar o antecessor é ação
    *sugerida*, aplicada pela gestão — o repo já tem a invariante de nunca cascatear status.

### 3.6 EGP casca (antecessor sem inventário próprio)

*Absorvido do PR #136 em 28/09/2026 — o mecanismo já roda na develop e cobre uma lacuna
que o §3.1.1 deixava aberta. É a única parte do #136 que entra nesta régua.*

22. **O problema.** Num `Unificado` os N antecessores contam (§3.1.1). Só que alguns deles
    **nunca terão inventário próprio**: não vão ser extraídos nem analisados como EGP
    individual — precisam apenas de uma linha no funil, capaz de chegar a `Migrado`, para
    que a migração deles seja contabilizada junto com a do unificador. Sem essa linha o
    antecessor não existe como projeto do corpus e, como **o vínculo mora na linha do
    antecessor** (§1), não haveria sequer onde gravá-lo.
23. **Cadastro versionado, e nasce no publish.** A casca é declarada em
    `egps_analysis/src/egps_casca.csv` (`pasta,nome,area,unificado_em,motivo`) e é criada
    **dentro do publish**, junto dos nós reais. O motivo é duro: `sas_lineage_nodes` é
    full-replace a cada publish, então um insert feito só pelo app sumiria na publicação
    seguinte. Arquivo ausente = lista vazia, não erro.
    - `projeto = "<pasta>__<nome>"`, a mesma convenção dos nós reais. `pasta` é o rótulo
      cru da área na extração e **não** é necessariamente igual à `area` canônica —
      `Cobranças` na pasta, `Cobrança` na coluna. Não unificar os dois.
    - Hoje são **5 cascas**, todas de Cobranças, todas absorvidas por unificadores.
24. **`escopo_indi = True` é gravado direto**, sem depender de `sas_escopo` — mas é flag de
    **visibilidade**, não de escopo. O `_frontier_egps()` **subtrai as cascas da base** e as
    devolve ao recorte pela mesma porta dos sucessores. *(Corrigido em 29/09/2026: sem essa
    subtração a casca ficava classificada nos **dois** conjuntos ao mesmo tempo — `base` e
    `extras` — e a linha de base subia de 168 para 173 sem que EGP algum tivesse entrado no
    escopo. O total não mudava, porque os extras eram descontados depois; o que estava
    errado era a classificação, e ela vazaria para qualquer superfície que lesse `base`.)* **Mas isso sozinho não
    para em pé:** `recompute_escopo()` **reseta** `escopo_indi` dos nós que não estão no
    `sas_escopo`, a cada edição de escopo, e a flag se apaga sozinha no próximo recompute.
    Armadilha medida em 2026-09, não hipótese.
    - **Fechado no publish (28/09):** cada casca também ganha **1 linha em `sas_escopo`**.
      O PR #136 deixava isso para "script/app à parte" — um passo manual que ninguém ia
      lembrar de dar. O insert é **aditivo e idempotente**: compara contra *todos* os
      projetos da tabela, ativos ou não, então republish não empilha duplicata **nem
      ressuscita um soft-delete da gestão**.
    - Isto abre uma exceção consciente ao "o publish só semeia `sas_escopo` se ela estiver
      vazia". A exceção é só-INSERT e nunca toca linha existente; nenhuma edição humana é
      sobrescrita.
    - `status_extracao = 'exato'` (a casca **está** no grafo).
    - **A linha em `sas_escopo` serve à visibilidade, não à contagem** (revisto em 28/09
      com a decisão do `extra`). Ela existe só para o `recompute_escopo()` não apagar o
      `escopo_indi`; a casca continua **fora do total base e fora do funil por área**, como
      todo extra (§3.1.2). O funil da Cobrança **não se mexe**. A exclusão é feita pelo
      mesmo conjunto que exclui os demais extras — não por um caso especial de casca.
    - Cuidado ao mexer: a linha em `sas_escopo` é **persistente**. Reverter o código não a
      remove, e ela sozinha faria a casca contar.
25. **Um input sintético por casca.** A aba EGPs não lê `sas_lineage_nodes` direto: a query
    agrupa a partir de `sas_egp_inputs` (grão projeto×input), então um EGP com **zero**
    inputs nunca gera linha no `GROUP BY` e fica invisível ali, mesmo com o nó existindo.
    Em vez de reescrever essa query central — usada por várias telas —, cada casca ganha
    **1 input fictício já `Disponível`**, chave `casco::<projeto>` e `artifact` começando em
    `"(casco — "` para quem abrir o detalhe.
26. **O input sintético não é trabalho.** Nasce `Disponível`, então não entra na fila de
    ingestão; e fica **fora da sanitização derivada do §3.4.15**. Ele é placeholder, não
    input exclusivo do antecessor — aplicar a régua de exclusividade sobre `casco::` seria
    agir sobre o vazio. Vale o mesmo para o §3.4.18 (despriorizados).
27. **A casca é um `extra`.** *(Revisto em 28/09/2026 — a versão anterior desta regra
    mandava a casca contar no denominador; a decisão do `extra` reverteu isso. Em
    29/09/2026 o motivo oscilou duas vezes e o resultado nunca mudou: a régua congelada
    disse "é extra porque não está na lista", e a correção do mesmo dia voltou a "é extra
    **porque é casca** — ela tem `unificado_em`, que é um vínculo de atualização — e não
    está na lista". A segunda forma é a que vale: `extra` é enumeração (§3.1.2), e a casca
    é um dos dois membros dela, ao lado do sucessor. Não é caso especial na contagem: o
    mesmo `vinculos.extras()` decide os dois.)* Ela
    recebe vínculo `Unificado`, exibe `Desatualizado` e espelha a etapa do sucessor, como
    qualquer antecessor — mas **não soma no total base**: entra no contador de extras
    (§3.1.2), junto com os sucessores. É o mesmo princípio dos dois: chegou depois da linha
    de base, então conta à parte. A migração dela segue visível e fechável; o que muda é
    em qual número ela aparece.

---

## 4. Guardas (falha barulhenta)

- **Vínculo por quem não é da gestão** → recusado (§3.5.19). A guarda vale **só para os
  campos do vínculo**: `PATCH /api/egp-pipeline` é aberto para etapa/status desde sempre, e
  fechá-lo inteiro tiraria de todo mundo uma edição que hoje funciona.
- **Sucessor inexistente no corpus** → o vínculo é recusado, com a mensagem dizendo que
  falta rodar o pipeline. Nunca aceitar ponteiro para chave que não é projeto.
- **EGP com status `Migrado` recebendo sucessor** → não deve acontecer (migrado é
  terminal, e hoje **nenhum** antecessor está nesse status: são Concluído 15,
  Despriorizado 10, sem status 7, Em Andamento 6, Block 3, A Iniciar 1). Se acontecer, o
  sistema **recusa e sinaliza** em vez de decidir sozinho.
- **Edição de etapa em EGP desatualizado** → recusada pelo backend, com o motivo.
- **Input que volta à fila sozinho.** Como a exclusividade é medida contra o **escopo**, um
  EGP hoje fora do escopo que entre depois faz até **73 chaves** deixarem de ser
  sanitizadas — a fila cresce sem ninguém ter agido. Precisa de aviso quando acontecer,
  senão vira "o número mudou do nada".
- **Vínculo pode fazer o total subir sozinho.** Uma ex-dependência **sem etapa real** fica
  fora do denominador (critério de 2026-08-10). Se ela ganhar sucessor, a etapa dela passa a
  espelhar a do sucessor — e, se essa etapa fosse lida como **real**, ela entraria no
  denominador sem que ninguém tenha mexido no escopo. Medido em prod (25/09): são **17**
  ex-dependências nessa situação no recorte `indi_deps`, e **`Cobranças__ACORDO_AMIGAVEL_v1`
  é uma delas e já é antecessor** de um vínculo `Unificado`.

  **RESOLVIDO em 28/09/2026 (decisão da gestão): isso não acontece.** O denominador lê a
  etapa **gravada**, nunca a espelhada — a decisão está declarada ponto a ponto no código
  (§3.1.2 e a trava `test_leitura_pipe_decidida.py`). Espelhar muda o que se **exibe**, não
  o que se **conta**. É a mesma régua da categoria `extra`: a linha de base não se mexe
  porque algo novo chegou. O aviso que esta guarda pedia deixa de ser necessário, porque
  não há mudança a anunciar.

- **Taxa de casamento da chave canônica.** O JOIN dos inputs da carga com o monitor casava
  **89%** (1.179 de 1.330) em 24/09. Queda brusca é bug de chave, não mudança de conteúdo
  — sentinela sobre essa taxa (risco nº 1 do ADR 0001).
- **Split que aparece depois.** Se um antecessor já vinculado ganhar outro sucessor, ele
  **volta para pendência** em vez de manter a herança antiga. O vínculo manual resolve a
  ambiguidade por construção (o antecessor aponta para um só), mas a chegada de uma
  segunda candidata precisa ser visível.

---

## 5. Superfície: a aba EGPs Atualizados é aposentada

Decisão de 24/09/2026. O sucessor vira **linha na aba EGPs** e o bloco de comparação vira
**seção do drawer** do EGP. A aba dedicada sai da barra.

O contexto que torna isso quase automático: a partir do momento em que o sucessor entra no
corpus (§2, etapa 2), ele **aparece sozinho** na aba EGPs, na aba Inputs, em Outputs e na
linhagem — é o que o pipeline faz com qualquer projeto. Manter a aba dedicada significaria
o mesmo EGP em duas telas, com duas taxonomias e dois funis.

### O que fica

- **As 5 tabelas** (`sas_egp_atualizados` / `_inputs` / `_outputs` / `_pipeline` / `_audit`)
  e o **script local** `publish_egps_atualizados.py`. São a fonte da comparação, que não
  existe em nenhum outro lugar.
- **`EgpAtualizadoDetail`** (~320 linhas): deltas antigo×novo, impactos, inputs novos,
  outputs removidos com consumidor externo, histórico de versões, autor e data do último
  save. Reusado como seção do drawer do EGP, sem reescrever.
- **O vínculo manual com sugestão automática** (`AtualizadoLinkButton`, `egp_atualizado_key`,
  badge, nível de confiança do pareamento) — já existe e é a base do §1. **10 vínculos já
  estão confirmados** em `sas_egp_pipeline` e sobrevivem intactos.

### O que sai

- A lista, os cards, os chips de **Situação**, o export CSV próprio e o seletor de recorte
  da aba — todos passam a ser os da aba EGPs.
- O **pipeline próprio** (`sas_egp_atualizados_pipeline` — etapa/status/responsável por
  versão, editável na aba) e o **Kanban dedicado** (3ª opção do switch em
  Gestão/Acompanhamento). O sucessor passa a usar o `sas_egp_pipeline` e o board de EGP.
  **Atenção ao termo:** o que morre é o lugar onde se *edita* o estado da versão. O
  **funil de sucessores** no Resumo (§3.1.3) continua — é onde se *lê* o progresso do
  conjunto. O código de hoje chama a mesma tabela de "Funil da TROCA" e de "Pipeline da
  troca"; na spec, **funil = gráfico do Resumo** e **pipeline = tabela de estado**.
- A taxonomia **"Situação"** (6 valores) morre; fica o **Tipo de vínculo** (3 valores).
  As duas descrevem o mesmo fato, e "Atualizado" aparecia nas duas querendo dizer coisas
  diferentes. O que a Situação sinalizava e não tem equivalente no tipo — `Par não
  resolvido` e `Falha na extração` — vira **pendência** na lista de recebimentos, não tipo.

### Migração do estado

Medido em 24/09: `sas_egp_atualizados_pipeline` tem **5 linhas, 3 preenchidas** (2
`Migrado/Migrado`, 1 `Implant. em PRD/Em Andamento`) e nenhuma órfã. A auditoria tem 30
eventos, 7 EGPs, 3 autores, o último em 24/09 19:36 — em uso, mas pequeno. **Copiar as 3
linhas para o `sas_egp_pipeline` do sucessor correspondente**; a tabela e a auditoria ficam
como registro histórico, sem serem lidas pelo app.

### O buraco que A abre, e a guarda

Entre a etapa 0 e a etapa 2 o sucessor **não existe em superfície nenhuma**: chegou, foi
comparado, mas ainda não é projeto do corpus. A janela deveria ser de minutos (o tempo do
pipeline), mas se ninguém rodar o pipeline ela dura dias e o arquivo some de vista.

**Guarda:** a aba EGPs exibe um contador/alerta — *"N versões recebidas aguardando entrada
no corpus"* — lido direto de `sas_egp_atualizados` por diferença com os projetos existentes.
Sem isso, aposentar a aba transforma "chegou versão nova" num fato que ninguém vê.

### Efeito no §3.1.3

Com o sucessor sendo EGP do corpus, o **funil de sucessores** fica mais barato do que era:
é um recorte sobre o mesmo universo dos outros dois funis, com o mesmo vocabulário e a
mesma maquinaria — não uma segunda implementação sobre outra tabela.

---

## 6. Priorização (independente do resto)

**O EGP a mais no mês 1 — diagnosticado, não é bug.** O plano é snapshot congelado; o
vigente foi salvo em 22/09 18:00, o anterior em 18/08. Mês 1 foi de **60 → 61** (mês 2 caiu
40 → 36; meses 3 e 4 intactos). Contando só quem entra no total: entrou
`PERF_REVISIONAIS_RPA` (o backfill de linhagem de 22/09 o puxou do mês 4), entrou
`Riscos__1351-SAS_v20201209_V2` (pinado no mês 1), saiu `20250918_darkpost_v15` (dedup de
setembro), e `CPF_Contrato` → `CPF_Contrato__v2` empata. **Decidido pela gestão (28/09/2026): re-congelar
em 60** — aplicado fora desta sessão. Esta spec não registra qual EGP saiu; se isso importar
depois, a foto anterior está nas tabelas de auditoria.

**Contagem viva de inputs — já implementada.** `X/Y inputs modernizados` por mês sobre o
plano congelado existe no código atual (`_prio_live_input_stats` no backend, pill no
`WavesView`). Falta confirmar visualmente em prod antes de anunciar na sync.

---

## 7. Decisões conscientes contra a recomendação

Registradas para que uma sessão futura não as "conserte":

- **Exclusividade medida contra o escopo, não contra o corpus** (§3.16). A recomendação era
  corpus, pelo precedente da família de safras (ADR 0002: a guarda é decisão de corpus,
  porque resolver sobre o recorte faz o mesmo artefato mudar de natureza conforme o filtro).
  A gestão escolheu escopo — "me importa só o escopo" —, aceitando as 73 chaves que podem
  voltar à fila.
- **Sucessor como linha própria na aba** (§3.4), e não como coluna na linha do antecessor.
  A aba cresce ~39 linhas e a régua "não entra nos 168" fica menos óbvia na tela.
- **Descarte sem registro** (§2). Uma versão recusada não deixa rastro; pode ser reavaliada
  do zero na próxima remessa.

---

## 8. Reconciliação com o PR #136 (já na develop)

Descoberto em 26/09, ao buscar a develop: o **PR #136** (Eduardo, commit `930c4783`, de
23/09) implementa a mesma feature com desenho diferente, e já está mergeado. O PR #138 e o
commit `1dce5d9d` (etapa fantasma) tocam os mesmos arquivos.

**Decisão do usuário (26/09): vale o que está nesta spec, não o que o PR #136 fez.** Este
capítulo existe para que a reconciliação seja deliberada, arquivo a arquivo, em vez de
resolvida no meio de um conflito de merge — e para que a conversa com o autor do #136 parta
de um documento, não de um `git checkout --ours`.

### Onde os dois se contradizem

| | PR #136 (develop) | Esta spec |
|---|---|---|
| Onde mora o tipo | `sas_egp_atualizados_pipeline`, chave `egp_key` da aba | `sas_egp_pipeline`, linha do antecessor (§1) |
| Valores | `atualizacao` · `substituicao` · `agrupamento` | `Atualizado` · `Substituído` · `Unificado` |
| Ao confirmar o vínculo | **grava** `Despriorizado e Contabilizado` no antecessor (no front, `EgpDetailPanel.atuMut`) | apenas *sugere*; classificar nunca muda status (§3.5.21) |
| Desvincular | **não reverte** o status — deliberado, "senão perde informação" | devolve o status real, porque nada foi gravado (§3.2.6) |
| Status do antecessor | reusa `Despriorizado e Contabilizado` | `Desatualizado`, derivado (§3.2.5) |
| Etapa | não espelha | espelha a do sucessor, recusada no servidor (§3.2.7) |

**O argumento do #136 não é descuidado**, e vale registrar: reusar um status que já exclui
do funil, do plano e da priorização em todo lugar evita criar um 7º valor e propagá-lo por
todas as superfícies — que é exatamente o custo desta spec (seis pontos de contagem). A
escolha dele é mais barata; a desta spec é **reversível**, e foi por isso que foi mantida:
desvincular por engano, no #136, deixa o antecessor despriorizado sem rastro do que ele era.

### O que do #136 deve ser mantido

Nem tudo colide — três partes são aditivas e ficam:

- **EGPs "casca"** (`egps_analysis/src/egps_casca.csv` + ~75 linhas no
  `publish_to_databricks.py`): antecessor absorvido por uma unificação que não tem
  inventário próprio ganha linha no funil e **sobrevive à republicação do corpus**.
  Preenchia uma lacuna desta spec — o §1 dizia que num `Unificado` os N antecessores
  seguem contando, mas não dizia o que fazer quando um deles não tem inventário.
  **ABSORVIDO em 28/09/2026: virou o §3.6 (regras 22–27)**, com as duas armadilhas medidas
  (o reset do `escopo_indi` pelo `recompute_escopo` e a invisibilidade do EGP sem input no
  `GROUP BY` de `sas_egp_inputs`).
- **Comentários combinados** (`EgpAtualizadoComentarios.tsx`, reusando `sas_gestao_status`):
  independente do vínculo.
- **Suporte** (`api.ts`, `gestaoApi.ts`, `styles.css`) e os ajustes em
  `EgpsAtualizadosView`/`Kanban` — estas duas superfícies são aposentadas pelo §5, então
  não vale gastar conflito nelas.

### Ordem da reconciliação

1. **Commitar o que está nesta árvore antes de qualquer merge** — são dois assuntos (o chip
   de ex-dependência e o vínculo) e, enquanto não estiver em commit, um merge malsucedido
   custa a sessão inteira.
2. ~~Alinhar com o autor do #136 os três pontos da tabela acima.~~ **Dispensado pelo
   usuário em 28/09/2026:** segue o desenho desta spec, sem rodada de alinhamento. Os três
   pontos (onde mora o vínculo · se classificar grava status · se a etapa espelha) ficam
   como estão aqui.
3. ~~Absorver os EGPs casca.~~ **Feito em 28/09/2026 — §3.6, regras 22–27.**
4. Resolver os 6 arquivos em conflito (`main.py`, `ReadinessView.tsx`, `GestaoKanban.tsx`,
   `pipeline.ts`, `types.ts`, `README.md`), fazendo valer esta spec.
5. **Reimplementar a casca** sobre o código desta árvore: o mecanismo é conhecimento
   absorvido, mas as ~75 linhas do `publish_to_databricks.py` e o `src/egps_casca.csv`
   ainda vêm da develop — ver §3.6 para o que precisa sobreviver à reescrita.

### O commit `1dce5d9d` não conflita de régua

Ele faz etapa fantasma contar **quando o status é `Despriorizado e Contabilizado`**, e
unificou as quatro cópias do critério (`_ex_deps_contab`, `_prio_contabiliza`, a cópia
inline em `egp_readiness` — que divergia — e `contaNoTotalEgp`). Nenhum dos 17 EGPs que o
chip de ex-dependência esconde está nesse status (são `A Iniciar` e dois
`Pré-conversão/Concluído`), então os números medidos seguem válidos. O conflito ali é
**textual**: as alterações desta sessão foram feitas sobre a versão antiga e divergente.
