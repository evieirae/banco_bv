# Migração SAS — monitoramento de EGPs

Glossário do domínio de avaliação/migração dos projetos SAS (EGPs) do BV e do app `monitoramento-sas`. Registra a linguagem canônica; implementação fica fora daqui.

## Language

### Corpus e app atual

**EGP**:
Um projeto SAS Enterprise Guide (`.egp`) do cliente; a unidade de inventário, priorização e migração.
_Avoid_: projeto SAS (ambíguo com "projeto" de gestão)

**Corpus**:
O conjunto de EGPs já recebidos e inventariados que alimenta o app atual (base de `received_egps/`).

**Input**:
Artefato externo que um EGP lê e que exige ingestão/disponibilidade (tabela, arquivo ou script), identificado por chave canônica.

**Leitura dispensada**:
Declaração da gestão de que um EGP não precisa de um Input que ele lê no código. Para aquele EGP o Input conta como resolvido; para os outros EGPs que o leem, nada muda.
_Avoid_: vínculo, vínculo quebrado, desvincular (Vínculo é Antecessor → Sucessor)

**Escopo**:
Os EGPs da lista DOR1 da Indicium (a aba Escopo), e os inputs que eles leem. É vivo: muda quando alguém adiciona ou desativa um EGP da lista.
_Avoid_: escopo como sinônimo de "tudo que o app conta" (isso é o Recorte ou a Linha de base, conforme a tela)

**Sub-área BV**:
A área interna do cliente (Digital, MIS, Operações, Estratégia - cartões, Estratégia - rodas, Riscos) a que pertence o Responsável BV de um EGP. É atributo da pessoa (cadastro `sas_responsaveis_bv`), herdado pelo EGP.
_Avoid_: área interna (colide com "Área", a área de negócio do EGP: Cobrança/Riscos/Jurídico)

**gestão**:
O grupo de pessoas da Indicium que gerencia a migração (`bv_users`). Não é a aba Gestão, nem a gestão do cliente.
_Avoid_: "a Gestão" para se referir às pessoas (é o nome da aba)

**Papel**:
O que uma pessoa pode fazer no app: **leitor**, **gestão** ou **admin**, cada um incluindo o anterior. Quem edita no app é sempre da gestão.

**leitor**:
Papel de quem só acompanha: vê as abas que não são da gestão e não edita nada. É o papel das pessoas do cliente.
_Avoid_: cliente (é o BV, a organização), usuário externo

**admin**:
Gestão que também reescreve o passado: salva o plano de priorização e corrige registros com data retroativa.

### Recortes e classificação de EGPs

**Dependência**:
EGP fora do Escopo que cria uma tabela lida, direta ou indiretamente, por um EGP do Escopo. É viva: deixa de ser quando a tabela que a liga ao Escopo é modernizada ou sanitizada, sem ninguém editar o EGP.
_Avoid_: input de dependência para a origem "SAS/Local (dependência)" do inventário (ali significa só "tabela produzida por algum EGP do corpus")

**Recorte**:
Escopo + Dependências, vivo. É o conjunto que as listas e os quadros mostram.
_Avoid_: escopo

**Linha de base**:
A lista congelada em 29/09/2026 de 193 EGPs (Escopo, Dependências e Ex-dependências daquele dia) que forma o denominador do "X de 193". Só a lista congela — etapa e status seguem vivos — e quem sai do Escopo depois continua contando.
_Avoid_: escopo, plano (o plano de priorização é outro congelamento)

**Ex-dependência**:
EGP que já foi Dependência e deixou de ser. Nunca é Extra.

**Extra**:
EGP que entrou depois do congelamento da Linha de base e foi nomeado — Sucessor de um Vínculo, Casca, novo declarado pela gestão ou Dependência que apareceu depois do congelamento (os 193 estão fechados: dependência nova vira Extra, e os inputs exclusivos dela vão para o balde dos extras). Conta à parte ("+N extra"), nunca dentro do total.
_Avoid_: qualquer EGP fora da Linha de base (Ex-dependência nunca é Extra; um EGP que não foi nomeado nem é dependência do Recorte fica fora de tudo)

**Casca**:
Antecessor sem inventário próprio, unificado em outro EGP. Existe para manter o Vínculo; não é trabalho.

**Mês do plano**:
O mês em que um EGP entra no plano congelado de priorização. Um Input herda o **menor** mês entre os EGPs **do Recorte** que o leem: EGP que saiu do Recorte não dá mês a ninguém, mesmo continuando no plano. Um Extra tem o mês do seu Antecessor, mas ele só conta para o Input nas visões que incluem os extras; nas visões da Linha de base, e nos funis dela, o mês vem só dos EGPs do plano, porque a chegada de um Extra não muda essas contas. Casca não entra, e Extra sem Antecessor no plano fica sem mês.
_Avoid_: mês do EGP (o mês é do plano, não atributo do EGP), mês de ingestão

### EGPs atualizados

**EGP Atualizado**:
Um `.egp` reenviado pelo cliente para substituir ou evoluir um EGP do corpus. Só é carregado no app o que vai ser usado — uma versão que não será usada não entra, e se já tiver entrado é removida.
_Avoid_: EGP novo, novo EGP (ambíguo entre "nova versão" e "inédito")

**Versão recebida**:
Uma carga concreta de um EGP Atualizado, identificada por `versao_id`; o mesmo EGP pode ter várias versões recebidas ao longo do tempo (histórico, nunca sobrescrito).

**Antecessor**:
O EGP do corpus que já existia, do qual parte o vínculo.
_Avoid_: EGP original, versão antiga

**Sucessor**:
A versão recebida depois que ela entra no corpus como projeto próprio, com chave sufixada pela data de recebimento. É nele que o trabalho de migração acontece.
_Avoid_: EGP novo, substituto (nomeiam só um dos três tipos de vínculo)

**Vínculo**:
O par ordenado Antecessor → Sucessor. Mora no Antecessor e tem dois campos: o **tipo** e qual é o Sucessor. É sempre decisão humana da gestão; o app apenas sugere.

**Tipo de vínculo**:
Como o Antecessor está ligado ao Sucessor. Três valores: **Atualizado** (nova versão do mesmo EGP), **Substituído** (o antigo sai e outro EGP entra no lugar — os dois contam) e **Unificado** (N antecessores para um sucessor).
_Avoid_: "unificação" para se referir a juntar as abas — colide com o tipo Unificado

**Desatualizado**:
Status do Antecessor que tem Sucessor. Conta nos totais, nunca conta como migrado, e é derivado do vínculo — o status anterior fica intacto por baixo. A etapa de um EGP Desatualizado é espelho da etapa do Sucessor e não pode ser editada.
_Avoid_: obsoleto, vencido

**Funil**:
O gráfico de progresso do Resumo, que conta EGPs por etapa × status num recorte. São três: escopo, escopo + dependências e sucessores.
_Avoid_: pipeline (é a tabela de estado editável, não o gráfico)

**Pipeline**:
A tabela de estado editável de um EGP — etapa, status, responsável, mês, Jira. É onde se edita; o Funil é onde se lê.
_Avoid_: funil

**Quadrante**:
Classificação valor×esforço produzida pela comparação determinística (ex.: "Trocar agora", "Não trocar (veto)"). É **consultivo**: não decide o tipo de vínculo nem bloqueia nada.

### Famílias de safra

**Safra**:
Uma carga datada de uma mesma tabela lógica, identificada pelo token de data no nome do artefato (`GRIMALDI.CARGA_MASSIFICADOS_202506`). No SAS é um dataset separado; no destino é uma partição da tabela da família. Deixou de ser unidade de trabalho — é evidência.
_Avoid_: versão, histórico

**Família de safras** (curto: **família**):
O conjunto de safras da mesma tabela lógica e **a unidade de input do app**: conta como 1, carrega o estado de trabalho e é o que se pede ao BV para ingerir. Só existe a partir de duas safras; safra sem irmã é um input comum.
_Avoid_: grupo de tabelas, agregado

**Profundidade necessária**:
Até que ponto do passado um EGP precisa da família para rodar — `todas`, `desde AAAAMM` ou `últimos N meses`. É propriedade do par (EGP, família): consumidores da mesma família precisam de profundidades diferentes.
_Avoid_: janela (ambíguo com a regra 12M/3M declarada pelo cliente)

**Profundidade ingerida**:
A safra mais antiga que de fato existe no destino depois da carga, sempre `desde AAAAMM`, declarada por quem ingere. Comparada à necessária, produz aviso — nunca bloqueio.

**Leitura esparsa**:
Par (EGP, família) que lê safras com buracos no intervalo (ex.: só dezembros desde 2017). A profundidade necessária continua sendo a safra mais antiga lida, mas carregar o intervalo inteiro entrega muito mais do que o EGP usa.
