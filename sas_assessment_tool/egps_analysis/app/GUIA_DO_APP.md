# Guia do Painel de Modernização SAS (`monitoramento-sas`)

Guia de **uso** do painel, para analistas e gestão. Explica o que cada aba mostra, o que é editável, quem vê o quê e os fluxos do dia a dia. (O documento técnico — arquitetura, API, decisões de design — é o [`README.md`](README.md).)

O painel acompanha a migração dos projetos SAS (**EGPs**) para o BigQuery/lake: quais tabelas (**inputs**) cada EGP consome, o que já está modernizado, o que bloqueia o quê, e um plano mensal de ingestão.

---

## 1. Acesso e permissões

O app é um **Databricks App** — o acesso usa o login do workspace, e **toda consulta/edição roda em seu nome** (aparece no Histórico com seu e-mail).

| Perfil | O que vê |
|---|---|
| **Qualquer usuário logado** | 8 abas: **Guia** · Resumo · Inputs · Outputs · EGPs · Escopo · Priorização · Histórico. Pode **editar** status/responsável/observação de inputs e etapa/status/responsável de EGPs. |
| **Gestão (grupo `bv_users`)** | Tudo acima **+** a aba **Gestão** + o controle de **fixar EGP num mês (📌)** na Priorização. |

> Se uma consulta falhar com erro de permissão, é grant de Unity Catalog/warehouse do **seu usuário** — fale com a gestão do projeto.

## 2. Conceitos que aparecem em todas as abas

- **EGP** — um projeto SAS (Enterprise Guide). É a unidade de migração.
- **Input** — tabela/arquivo/script que um EGP **consome**. "Ingerir" um input = disponibilizá-lo no BigQuery/lake.
- **Output** — artefato que um EGP **produz**. Outputs não são migrados; servem para entender dependências.
- **Escopo Indicium** — a lista DOR1 de EGPs sob responsabilidade da Indicium (gerida na aba **Escopo**).
- **Dependências (transitivas)** — EGPs *fora* do escopo cujos outputs alimentam (direta ou indiretamente) EGPs do escopo. Vários recortes do app têm a visão "**+ dependências**". Tabela já **modernizada ou sanitizada não gera dependência**: se tudo o que liga A a B está resolvido, B deixa de aparecer (e de ser puxado) como dependência de A.
- **Origem do input** — de onde o dado vem: `BigQuery` (já no lake) · `Transacional` (banco corporativo) · `SAS/Local (dependência)` (produzido por outro EGP do corpus) · `SAS/Local (externo)` (**"dep. produtor ausente"** — ninguém no corpus produz; falta mapear a fonte) · `Arquivo` · `Script`.
- **Status do input** — o **status humano** (editado por vocês) sempre prevalece sobre a detecção automática ("Auto"); divergência entre os dois é sinalizada com **⚠**, nunca sobrescrita.
- **Sanitizado** — input descartado do escopo ("não vai ser migrado"). Sai de todas as contagens, mas continua visível na lista de Inputs para poder ser revertido.
- **Autoprodutor** — input cujo próprio EGP consumidor também **cria** a tabela (não só apensa), então não precisa de ingestão separada. Ao contrário de Sanitizado, **conta como feito** na prontidão (do input e do EGP). Um badge "🔁 candidato a autoprodutor" aparece em Inputs quando algum EGP consumidor é criador único (ou produtor canônico escolhido) da mesma tabela; a confirmação é manual, pelo mesmo seletor de Status — e vale para **todos** os EGPs que usam o input, não só o autoprodutor. Reversível.
- **Bloqueado (🔒)** — EGP que depende (direta ou transitivamente) de tabela SAS **sem produtor mapeado**. Só destrava quando essas tabelas forem ingeridas ou o produtor for identificado.
- **⟳ (ciclo)** — EGP numa dependência circular com outros (A alimenta B que alimenta A). Precisam ser tratados juntos.
- **Mês** — posição do EGP no plano da aba **Priorização** (substituiu a antiga "Onda" em todo o app). "—" = EGP fora do recorte do plano.
- **Família de safras** — quando a mesma tabela aparece com várias datas no nome (`..._202505`, `..._202506`, …), o app mostra **uma linha só**, com a pílula `N safras`. Motivo: ingerir essa família cria **uma** tabela particionada no destino, e acrescentar safra depois é carga incremental — não uma ingestão nova. É por isso que a fila de inputs é menor que a contagem de tabelas físicas: **o esforço não mudou, a unidade mudou**. Safra já sanitizada continua no histórico, mas não pesa na fila; se as safras estiverem em situações diferentes, aparece a pílula `estado misto` e a linha mostra a **safra pendente menos avançada**. Editar a família escreve em todas as safras dela (o Histórico guarda o valor anterior de cada uma).
- **Profundidade necessária / ingerida** — no detalhe de uma família: quanto de passado **cada EGP consumidor** precisa (derivado das safras que ele lê hoje; a gestão pode declarar outro valor) e o que de fato já foi carregado (registrado por quem fez a ingestão). A comparação gera avisos — "carga rasa para 2 de 5 consumidores", "consumidores pedem de 8 a 103 meses", "leitura esparsa" — que são **informativos**: nenhum deles bloqueia EGP.
- **homônimo ×N** — um mesmo nome de tabela SAS que corresponde a N tabelas físicas distintas (caminhos diferentes).

## 3. As abas

### Guia (`/guia`) — 1ª aba da barra

Versão **dentro do app** deste documento, para onboarding: como o painel funciona, conceitos, o papel de cada aba (com atalho "abrir →"), fluxos do dia a dia e FAQ. É o primeiro lugar para mandar um analista novo. (Ao abrir o app, a view inicial continua sendo o **Resumo**.)

### Resumo (página inicial)

Visão executiva, em pares "**Escopo Indicium**" / "**+ dependências**":

- **Cards**: EGPs no escopo, EGPs analisados, Inputs no escopo, Inputs a ingerir; dependências e seus inputs; totais gerais.
- **Funis de migração** (EGPs, por etapa × status) e **de ingestão** (inputs) — e a versão "(+ dependências)", com denominador maior (universo ampliado).
- **Funil por área (DOR1)** — por área: qtd. projetos, EGPs enviados/analisados, inputs não modernizados. Na visão +deps ganha a coluna **"Dependências"** (quantos EGPs da linha vêm de fora do escopo).
- **Inputs por origem (DOR1)** — total/modernizado/não modernizado + **% Modernizado** por origem.

Tudo reflete edições em tempo real (status efetivo). Não há nada editável aqui.

### Inputs (`/monitoramento`)

A grade de trabalho da **ingestão** — um input por linha, milhares de linhas (tabela virtualizada).

- **Seletor de escopo**: `Indicium` · **`Indicium + Dependências` (padrão)** · `Base completa`. No modo "+ Dependências", a **área selecionada define a base** e as dependências entram mesmo sendo de outras áreas.
- **Filtros** multi-select (Categoria, Origem, Status, Área), busca server-side em todas as linhas (o Ctrl+F do navegador só acha as visíveis), checkbox **divergência** (⚠).
- **Cards** no topo (refletem os filtros aplicados): "Inputs a ingerir / distintos", a modernizar/total por origem (SAS/Local, Transacional, Arquivos/Scripts, BigQuery), "% modern./sanit." e o indicador de **EGPs no recorte**.
- **Editável inline**: **Status (humano)**, **Responsável** (dropdown de analistas — responsável do *input* = ingestão), **Observação**.
- Clicar num input abre o **painel lateral**: quem produz, quem usa (com área/mês de cada EGP) e o histórico de alterações daquele input.
- **⬇ Exportar CSV** exporta as linhas exibidas, **uma linha por (input × EGP)** — cada input repetido para cada EGP que o consome.

### Outputs (`/monitoramento-outputs`)

Espelho da aba Inputs para o que os EGPs **produzem** — **somente leitura**. Tem o mesmo **seletor de escopo** das outras abas (`Indicium` · **`Indicium + dependências`, o padrão** · `Base`). Colunas: Artefato · Categoria · Área(s) · Produtores · Consumidores · Tipo (**Terminal** = ninguém no corpus consome; **Intermediário** = alimenta outros EGPs). Só artefatos **permanentes** entram (tabelas `lib.membro`/datasets físicos e arquivos exportados) — temporárias de `WORK` ficam de fora. Painel lateral com produtores e consumidores (incl. disponibilidade no lake); export CSV.

### EGPs (`/egps`)

Prontidão de **cada EGP** para migrar. Esta aba absorveu a antiga "Escopo de migração" — o recorte é escolhido no **seletor de escopo**: `escopo: só Indicium` · **`Indicium + dependências` (padrão)** · `escopo: todos`.

- **Cards** (refletem o seletor, não os filtros): **EGPs** (com "X escopo + Y deps"), **Inputs distintos** (sem dupla contagem), **A ingerir**, **Sem fonte (SAS/Local)**.
- **Chips clicáveis** para filtrar: 🟢 Habilitados · 🟡 Quase · 🟠 Parcial · 🔴 Bloqueado · ⟳ Em ciclo · ⚡ Quick win · 🔒 Bloqueio dependência · ⏸ Dep. despriorizada (EGPs impactados por dependência fora do backlog).
- **Colunas**: EGP (com 🔒/⚠ quando aplicável) · Tipo (só no modo "+ dependências": `escopo` × `dependência · nível`) · Área · **Mês** · Inputs · **% modernizado** · Faltam · Depende de · **Etapa** · **Status** · **Responsável** · Prontidão.
- **Editável inline** (em qualquer recorte, inclusive dependências): **Etapa**, **Status** e **Responsável** (responsável do *EGP* = migração).
- Clicar na linha expande o **detalhe do EGP**: pipeline de migração, *Depende de* / *Alimenta* (navegáveis, com **selo** `Migrado`/`Despriorizado` nos projetos já resolvidos), motivo do bloqueio (quais tabelas SAS sem produtor, próprias e das dependências), o aviso **⏸ de dependência despriorizada** (quais EGPs fora do backlog impactam este), e a lista de **inputs editável** ali mesmo.
- **🔗 link** no detalhe copia uma **URL compartilhável** (`/egps/<nome>`) — quem abrir cai direto naquele EGP.
- Regra de leitura: **100% modernizado + fora de ciclo = pode começar a migrar**.
- **Etapa "Conversão pela Área"** (grupo "Fora do funil" no seletor de Etapa): marca um EGP cuja **conversão de código não é feita pela Indicium** — a própria área de negócio do BV converte. A Indicium segue só com a **ingestão dos inputs**; o EGP fica de fora da contagem "X/Y migrados" (não é etapa do funil de conversão) mas suas dependências continuam sendo puxadas normalmente.

### Versões atualizadas de EGP (dentro da aba EGPs)

A aba dedicada "EGPs Atualizados" foi **aposentada em 2026-09**: a versão nova entra no corpus e vira linha da aba EGPs, com um funil só. O que ela tinha de único mora agora em dois lugares, os dois na aba **EGPs**:

- **Seção "Versão atualizada" no detalhe do EGP** — o vínculo com a versão recebida (sugestão automática por conteúdo, que você **confirma** ou troca) e, logo abaixo, a **comparação com o antecessor**: impactos/alertas por extenso, churn de código e alcance downstream, inputs (com **prontidão viva** contra o monitor; input que o corpus não conhece aparece como *fora do corpus*), outputs (inclusive **removidos**, com nº de consumidores), **histórico de versões** navegável, autor e data do último save no EG. O badge 🔄 na linha da tabela indica que há versão vinculada (confirmada) ou sugerida.
- **Chip "📥 Aguardando corpus: N"** — versões que chegaram e já foram comparadas, mas ainda **não viraram projeto do corpus** (o pipeline não rodou). Clique para ver quais. O chip também marca **pendências** (⚠): *pareamento não resolvido* e *falha na extração* — casos em que a comparação **não rodou**, e que continuam visíveis mesmo depois de a versão entrar no corpus.
- A carga continua sendo feita por script local (`egps_analysis/publish_egps_atualizados.py`) — não há upload pela interface. Links antigos `/egps-atualizados` abrem o Resumo.

### Escopo (`/escopo`)

A **lista DOR1 editável** — fonte do que é/não é Indicium.

- **+ Adicionar** um EGP (autocomplete dos extraídos; nome livre registra um "esperado mas não recebido").
- **Recebido** = o EGP foi extraído e existe nas tabelas; clicar num recebido abre-o na aba EGPs.
- **✕ desativa** (soft) — a entrada fica guardada, esmaecida, com pill "desativado" e botão **↺** para reativar. Desativar tira o EGP de **todas** as contagens do app na hora; reativar traz de volta com tudo preservado.
- Cada edição aqui **re-deriva o escopo no app inteiro** (Resumo, Inputs, EGPs, Priorização) imediatamente.

### Priorização (`/ondas`)

O **plano mensal de ingestão**. Recorte **fixo**: Indicium + dependências · todas as áreas · prazo **dez/2026**. A **capacidade** (inputs/mês, padrão 400) é ajustável **pela gestão**, direto na linha de recorte — a mudança é persistida e recalcula o plano **para todos**.

- Os EGPs são empacotados em meses de até a capacidade em inputs distintos **a ingerir**, na ordem: **1) viabilidade** (desbloqueado e ingerível primeiro) → **2) alavancagem** (quem destrava mais EGPs) → **3) quick win** (menos inputs). Input compartilhado entre EGPs conta **uma vez só**, no primeiro mês em que aparece.
- EGPs **`Despriorizado e Contabilizado`** aparecem nos meses **como EGPs normais** (o status azul na linha os distingue); a única diferença é que as dependências exclusivas deles não são puxadas para o recorte.
- **Mês 1 = mês corrente** ("Mês 1 — julho/2026"…). Meses além de dez/2026 ganham o aviso **"fora do prazo"**.
- **Cards**: **Migrados** (status `Migrado`; mostra também quantos neste mês) · **Despriorizados** (fora do backlog, esforço contabilizado) · **Bloqueados** (dependem de tabela SAS sem produtor) · **Habilitados** (sem bloqueio = total − bloqueados).
- **A barra de cada mês mostra o avanço**: quantos EGPs do mês já foram **concluídos** (`Migrado` ou `Despriorizado e Contabilizado`). A carga de inputs vira texto ("X/400 inputs novos") — passar do teto **não é erro**: a gestão pode fixar quantos EGPs quiser num mês (o teto só orienta o empacotamento automático).
- Cada mês expande para a lista de EGPs (1 por linha): EGP · Área · Etapa · Status · **+Inputs** (custo marginal) · Alimenta · Responsável · Mês. Clique abre o EGP na aba EGPs.
- **📌 Fixar num mês (só gestão)**: o seletor "Mês" de cada linha fixa o EGP num mês específico (`auto` volta ao automático). O pin é **absoluto** — vale mesmo estourando os 400 (a linha marca `excede`); o teto vira guia.
- O mês calculado aqui é o **"Mês"** exibido nas outras abas — fixar um pin atualiza tudo na hora.

### Histórico (`/historico`)

Auditoria de **todas as edições**: quando, quem, aba de origem, artefato, campo, valor de → para. Busca por artefato, usuário ou valor. Nada some silenciosamente — toda mudança de status/etapa/responsável/escopo fica registrada.

### Gestão (`/gestao`) — só grupo `bv_users`

Duas seções:

1. **Gestão de EGPs / Inputs** (switch no topo) — acompanhamento da migração, com **3 indicadores** no topo (com responsáveis · Convertidos · Migrados/Modernizados): tabela com **datas editáveis** (clique na data → pop-up com calendário → confirmar; na variante EGPs: Início Migração, **Fim Conversão** e Fim Migração; na variante Inputs: Início/Fim **Ingestão**), **QTD de dias úteis** com responsável (exclui fins de semana e feriados; congela no Fim), e o **último status** (1 linha) — clique nele abre o **painel lateral** com o status completo, o histórico e o botão **+ Adicionar Comentário** (o comentário vira o novo último status). A lista mostra por padrão **só quem tem responsável** (checkbox "só com responsável" para incluir o resto). No rodapé, gráficos de barras: **atribuídos por colaborador** (altura = total atribuído, para ver o balanceamento do time; a parte verde é o que já concluiu), **EGPs convertidos por mês** e **migrações/ingestões por mês**.
2. **Cadastro de analistas** (nome, e-mail, ativo) — fonte dos dropdowns de "Responsável" nas abas Inputs e EGPs. Cadastro só manual (adicione um a um). E-mails são padronizados para **`@indicium.ai`** — adicionar alguém que já existe com `@indicium.tech` atualiza o cadastro em vez de duplicar. Desativar um analista não apaga atribuições existentes.

---

## 4. Fluxos do dia a dia

| Quero… | Onde / como |
|---|---|
| Marcar um input como ingerido | **Inputs** → filtre/busque → coluna "Status (humano)" → selecione o status. O ⚠ some quando humano e Auto convergem. |
| Descartar um input do escopo | **Inputs** → status **Sanitizado**. Sai das contagens; reversível pela própria coluna. |
| Dispensar pré-working de um input que o próprio EGP produz | **Inputs** → badge "🔁 candidato a autoprodutor" sinaliza qual EGP cria+consome → confirme em status **Autoprodutor**. Conta como feito na prontidão; reversível. |
| Atribuir responsável pela ingestão de um input | **Inputs** → coluna "Responsável". |
| Avançar um EGP no funil de migração | **EGPs** → colunas Etapa/Status (ou dentro do detalhe do EGP). `Concluído` = terminou *a etapa atual*; `Migrado` = terminal (em produção, validado). |
| Atribuir responsável pela migração de um EGP | **EGPs** → coluna "Responsável". |
| Saber por que um EGP está bloqueado | **EGPs** → clique na linha → seção "🔒 Bloqueado por dependência" + inputs com pill "dep. produtor ausente". |
| Compartilhar um EGP com alguém | **EGPs** → detalhe → **🔗 link** (URL direta `/egps/<nome>`). |
| Incluir/tirar um EGP do escopo Indicium | **Escopo** → "+ Adicionar" / ✕ (desativa; ↺ reativa). |
| Ver quando um EGP está previsto | Coluna **Mês** (qualquer aba) — o plano vem da **Priorização**. |
| Antecipar/adiar um EGP no plano *(gestão)* | **Priorização** → seletor "Mês" da linha → escolher mês ou `auto`. |
| Levar os dados para Excel | **⬇ Exportar CSV** (Inputs, Outputs, EGPs, Escopo, Priorização) — exporta o que está exibido (na Priorização, o plano inteiro: 1 linha por EGP × mês); abre direto no Excel pt-BR. |
| Auditar quem mudou o quê | **Histórico** (ou o histórico do input no painel lateral). |

## 5. Perguntas frequentes

**Os números de duas abas não batem — bug?**
Quase sempre é diferença de **recorte**: escopo (Indicium × +deps × base), filtros aplicados, e a regra de que **Sanitizado não conta**. Os cards de cada aba dizem no tooltip qual recorte usam. Na aba EGPs, os cards seguem o **seletor de escopo**, não os filtros de coluna.

**"X/Y migrados" no funil conta o quê?**
Conta por **status terminal**: `Migrado` + `Despriorizado e Contabilizado` (esforço resolvido) — não "chegou na última etapa". Já o card **"Migrados neste mês"** da Priorização conta **só `Migrado`**, no mês de calendário corrente.

**Marquei um EGP como "Despriorizado e Contabilizado" — o que acontece?**
Ele continua aparecendo em tudo — inclusive **no mês do plano de Priorização**, como um EGP normal — mas **deixa de puxar dependências**: as que só existiam por causa dele saem dos recortes "+ dependências"; as compartilhadas com outro EGP ativo ficam. Além disso, **quem depende dele ganha o aviso ⏸** na aba EGPs (grade e detalhe): o output que esses EGPs consomem não será produzido pelo plano. Reverter o status traz as dependências de volta na hora e apaga os avisos. (É o único status de saída de backlog — o antigo `Removido` foi fundido nele.)

**Onde foi a aba "Escopo de migração"?**
Foi fundida na aba **EGPs** (use o seletor "Indicium + dependências"). Links antigos `/escopo-migracao` continuam funcionando — abrem a aba EGPs.

**Onde foi a aba "Linhagem"?**
Foi desativada (2026-07): o grafo estava defasado em relação às regras de dependência mais novas (escolha de produtor canônico) e será repensado. Para "se eu migrar X, o que destravo?", use o detalhe do EGP — listas *Depende de* / *Alimenta*, navegáveis.

**Por que um EGP mostra "—" na coluna Mês?**
Ele está **fora do recorte do plano** (não é Indicium nem dependência do escopo) — a Priorização não o agenda.

**Por que "dep. produtor ausente" em vez de "input a ingerir"?**
Porque a tabela é produzida por um EGP que **não está no corpus recebido**. Marcar assim deixa explícito que falta **mapear o produtor** (ou receber o EGP), em vez de esconder a tabela entre inputs comuns.

**Editei e nada mudou em outra aba.**
Use o **⟳ Atualizar dados** no topo. Edições de Escopo e pins de mês propagam sozinhos; alguns agregados usam cache curto (até ~5 min). Em particular, as **dependências** usam esse cache: marcar um input como **Modernizado/Sanitizado** (que faz a dependência satisfeita sumir) ou mudar um EGP para **Despriorizado** (que liga o aviso ⏸ nos dependentes) pode levar até ~5 min — ou um ⟳ — para refletir na aba EGPs e na Priorização.

**Posso desfazer uma edição?**
Sim — edite de volta (o valor anterior está no **Histórico**). Nada é apagado de verdade: escopo desativa (não deleta), analista desativa, auditoria guarda tudo.
