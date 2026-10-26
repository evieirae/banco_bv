# Alias de libname não é unidade de input — a tabela física é

Status: **proposed** (2026-09-23). Mapa de decisão já semeado em prod (`sas_input_alias_canonico`, 85 grupos, 186 linhas), **inerte**: nada o lê e nenhum número do app mudou. Plano e tickets: `egps_analysis/app/docs/superpowers/plans/2026-09-23-alias-de-libname.md`. Levantamento: `egps_analysis/docs/analises/inputs_homonimos_libname_2026-09-23.csv`. Precedente direto: ADR 0002.

O app conta **linha de `sas_inputs_monitor`**, e a chave dessa linha é `tabela::LIB.MEMBRO`. Só que o `LIB` é um apelido que cada EGP escolhe: o mesmo diretório vira `INSIGHT` num projeto e `_INSIGHT` noutro, `MISCRED` e `_MISCRED`, `COBRANC` e `PRETER` (ambos `/riscosbv/cobranca/preter`). O resultado é que **um arquivo vira N inputs**. Medido em 23/09/2026 sobre as linhas vivas de tabela SAS/Local no formato `LIB.MEMBRO`: 249 membros aparecem sob mais de um libname, somando 589 linhas. Destes, **85 grupos (186 linhas) compartilham exatamente o mesmo caminho físico** — são 101 linhas a mais do que existem arquivos. `TBSIMULACOES` é uma tabela contada três vezes (`CONVSIMU`, `INFCVS`, `MIS2`, todas em `/infogrc/convsimu`) e lida por 72 EGPs.

Isso é o mesmo defeito que a ADR 0002 resolveu para safras, com um agravante: safra ao menos é um dado real (partições diferentes existem), enquanto alias divergente não é nada — é a mesma linha de `LIBNAME` escrita com outro nome.

Decidimos que **a tabela física é a unidade de contagem de input, e o alias de libname deixa de sê-lo**. A identidade é o par `(path físico, membro)`, que já é a chave da linhagem desde a decisão registrada em `docs/analises/REFAZ_LINHAGEM_PATH.md`. A decisão de qual alias representa o grupo vira dado explícito em `sas_input_alias_canonico`, revisável por humano, e não uma regra derivada em runtime.

**O grafo continua por alias.** Linhagem, produtor canônico e casamento input↔output seguem no grão da linha. O colapso é de contagem, exibição e estado — exatamente o recorte da ADR 0002, e pelo mesmo motivo: colapsar os dois lados ao mesmo tempo troca um erro de contagem, que é visível e chato, por um erro de linhagem, que é silencioso e caro.

**Só colapsa quando o caminho físico é conhecido e idêntico.** Os 249 grupos se dividem em três baldes, e a fronteira é dado, não julgamento: **A** (85 grupos) tem path preenchido em todas as linhas e um único valor — mesmo arquivo; **B** (92 grupos) tem paths distintos — são tabelas diferentes que só dividem o nome, e `DIAS_UTEIS` é o caso didático, com 6 libnames em 6 diretórios, um calendário por analista; **C** (72 grupos) tem path ausente em alguma linha — indeterminado, porque `paths_fisicos` fica vazio quando o `LIBNAME` é declarado fora do EGP ou montado por macro. Só o balde A entra. O B fica fora para sempre; o C entra quando o resolvedor de libname preencher o path, e não antes.

## A alternativa rejeitada, com o custo medido

**Resolver a contagem pelo status não funciona, e isso foi medido em produção no mesmo dia.** A tentativa foi marcar os aliases redundantes como `Modernizado / Sanitizado`: tira a linha da fila, resolve a contagem dupla, parece barato. O efeito colateral é que `_modern()` trata Sanitizado como resolvido, então **o EGP que lê o alias redundante passa a contar aquele input como pronto** enquanto o arquivo continua pendente pelo canônico. Depois de 72 linhas marcadas assim, o app tinha **78 grupos divergentes, 128 EGPs com prontidão inflada em 172 pares (EGP, input)**. Só `TBSIMULACOES/INFCVS` inflava 30 EGPs. Foi revertido no mesmo dia pela unificação de estado (`unificacao_estado_libname_2026-09-23.sql`).

A lição é curta e vale para além deste caso: **status é estado, contagem é contagem.** Todo atalho que usa um para resolver o outro faz o app mentir em algum lugar — aqui, no número que o cliente usa para saber se pode começar a conversão.

O mesmo erro já existia à mão antes da tentativa automática: 20 linhas sanitizadas entre julho e setembro, todas no mesmo formato — o alias com **menos** EGPs marcado como resolvido enquanto o gêmeo físico, com mais, seguia pendente. A intenção era claramente "este alias é redundante", e a ferramenta disponível para dizer isso era a errada.

**Colapsar linha no publish também está fora.** É o que `CLAUDE.md` já registra: o MERGE preserva coluna humana por `chave_canonica` e expõe identidade física como coluna **aditiva** (`paths_fisicos`/`n_paths_fisicos`), nunca fundindo linhas de homônimo, porque fundir destrói status digitado por analista. Nada nesta decisão muda isso — o colapso é de leitura.

**Casar por nome, sem path, faria falso-merge.** É a mesma recusa que a ADR 0002 fez ao `strip_schema` da branch `feat/vintage_analysis`. Aqui o contraexemplo está medido no próprio corpus: os 92 grupos do balde B somam 241 linhas que uma regra por nome juntaria indevidamente.

## Consequências

A contagem de input muda nas mesmas superfícies que a família de safras já tocou — Inputs, Resumo, landing, funil de ingestão, prontidão por EGP, priorização — e o efeito é pequeno e mensurável: **10.188 linhas vivas passam a 10.087 unidades**, 101 a menos. No escopo Indicium são 56 linhas em 25 grupos, das quais 25 são excedente. Quem esperava um salto de número vai se decepcionar; o valor está em parar de pedir ao BV a ingestão do mesmo arquivo duas vezes, não em encolher o relatório.

A escrita humana passa a fazer **fan-out** para as N linhas do grupo, com auditoria por linha, como em famílias de safra. Isso sobrescreve estados divergentes por alias — que é o ponto, já que estado divergente entre aliases do mesmo arquivo é sempre erro.

A decisão de canônico é **dado, não regra**. A proposta automática (mais EGPs consumidores → etapa mais avançada → dentro do escopo → nome do libname) semeia a tabela, e `origem_decisao='revisao_humana'` protege a linha revisada de ser sobrescrita no re-seed. `ativo=false` tira um grupo da unificação sem apagar o registro da análise. Isso existe porque a escolha tem casos genuinamente ambíguos: nas quatro safras de `BASE_UNICA_ATACADO` o vencedor alterna entre `MISCRED` e `_MISCRED` conforme a safra, e ninguém quer que a tabela mude de nome de um mês para o outro por causa de uma contagem de consumidores.

Enquanto o backend não colapsar, o estado permanece **unificado entre aliases** do mesmo grupo: todos exibem o etapa/status do alias que carrega o trabalho real, com Sanitizado pesando zero na escolha, porque descarte não é progresso. Essa é a única configuração em que a prontidão não mente, e a contagem dupla de 101 linhas fica visível de propósito — melhor um número inflado que se explica do que um número certo apoiado num estado falso.
