# Painel de Modernização SAS — app (incremento 2)

App de **monitoramento dos inputs** da migração SAS. React + TypeScript (Vite) no
front, **FastAPI** no back, servido como **Databricks App**. Lê/escreve as Delta
tables em `bv_dev_db.monitoramento_sas` (geradas por `../publish_to_databricks.py`).

> **Guia de uso (para quem opera o painel):** [`GUIA_DO_APP.md`](GUIA_DO_APP.md) — o que
> cada aba mostra, quem vê o quê e os fluxos do dia a dia. Este README é o doc
> técnico (arquitetura, API, decisões de design, dev/deploy).

## Arquitetura

```
app/
├── app.yaml              # manifesto do Databricks App (command + env)
├── requirements.txt      # fastapi, uvicorn, databricks-sdk
├── backend/main.py       # API JSON + serve o SPA (../static)
├── frontend/             # React/TS (Vite) — código-fonte
│   └── src/               # App.tsx, routes.ts (rotas + deep-links), components/ (11 abas),
│                          #   pipeline.ts (status/funil), api.ts, types.ts
└── static/               # bundle compilado (servido pelo FastAPI) — vai no deploy
```

- **Backend** usa `databricks-sdk` (StatementExecutionAPI) contra o SQL Warehouse.
  **On-behalf-of-user (OBO):** dentro do Databricks App, cada request usa o **token
  do usuário logado** (header `X-Forwarded-Access-Token`, escopos já habilitados) —
  as queries rodam como a pessoa, e `current_user()`/auditoria refletem quem editou.
  Com `REQUIRE_OBO=true` (no `app.yaml`), o app **recusa** request sem token (não cai
  no service principal). Em dev local (sem `REQUIRE_OBO`) usa o profile do
  `~/.databrickscfg` — exporte `DATABRICKS_CONFIG_PROFILE`.
- **Tabela** virtualizada (`@tanstack/react-virtual`) — aguenta milhares de linhas.
  Edição inline de `status_humano` (select), `responsavel`, `observacao` → `PATCH`
  grava na Delta com `updated_at`/`updated_by = current_user()`.
- **Regra de status:** humano sempre prevalece; `modernizada_auto` (detecção via
  pipeline/chameleon) é informativa e a **divergência** é sinalizada (⚠), não sobrescrita.

## Telas (abas)

Cada aba tem URL própria (deep-link e refresh funcionam — ver §Decisões de design → Deep-links). Labels renomeados em 2026-07 (sem o prefixo "Monitoramento"); **slugs preservados** para não quebrar links salvos.

| Aba | Slug | O que mostra |
|---|---|---|
| **Guia** | `/guia` | 1ª aba da barra: onboarding dos analistas dentro do app — como o painel funciona, conceitos, papel de cada aba, fluxos e FAQ. Estática (`GuiaView.tsx`), espelho resumido de [`GUIA_DO_APP.md`](GUIA_DO_APP.md) — **mudou aba/conceito, atualize os dois**. (A página **inicial** segue sendo o Resumo.) |
| **Resumo** | `/resumo` | Funis de migração/ingestão + funil por área + inputs por origem, cada um em 2 visões (escopo Indicium e **+ dependências**); página inicial. |
| **Inputs** | `/monitoramento` | Tabela virtualizada de inputs; edição inline (status/responsável/observação); filtros multi-select (categoria, **origem**, status); export CSV. Abre em **Indicium + dependências**. |
| **Outputs** | `/monitoramento-outputs` | Artefatos **produzidos** pelos EGPs (read-only): produtores, consumidores, terminal/intermediário. Abre em **Indicium + dependências**. |
| **EGPs** | `/egps` | Prontidão por EGP com **seletor de escopo** (Indicium / **+ dependências, o padrão** / base completa) — absorveu a antiga aba "Escopo de migração" (2026-07); **status + etapa + responsável** editáveis inline; expande para o detalhe (deps + inputs). |
| ~~EGPs Atualizados~~ | `/egps-atualizados` | **Aposentada (2026-09, spec §5):** o sucessor entra no corpus e vira linha da aba EGPs, com um funil só. A comparação com o antecessor — o que a aba tinha de único — virou a seção **"Versão atualizada"** do detalhe do EGP (`EgpAtualizadoDetail`); o chip **"📥 Aguardando corpus"** cobre a janela antes da entrada no corpus. As 5 tabelas e o script local seguem intactos. `/egps-atualizados` cai no Resumo. |
| **Escopo** | `/escopo` | Lista DOR1 editável (o que é/não é Indicium); ✕ desativa (soft); clicar num recebido abre o EGP na aba EGPs. |
| **Priorização** | `/ondas` | Plano de ingestão por **mês** (recorte fixo Indicium+deps, capacidade-guia 400); pin manual de mês (gestão); cards migrados/bloqueados/habilitados. |
| ~~Linhagem~~ | `/linhagem` | **Desativada (2026-07):** o grafo não reflete a escolha de produtor canônico; removida da barra (view/rotas dormentes — re-habilitar = reinserir o entry em `routes.ts`). `/linhagem` cai no Resumo. |
| **Histórico** | `/historico` | Auditoria das edições (quem/quando/de→para). |
| **Acompanhamento** | `/acompanhamento` | **Único Kanban visível ao cliente (BV)** — switch EGP/Input, KPIs médios e um quadro por **Responsável BV** (recolhível, ver §Acompanhamento). Sem tabela/gráficos e com todos os controles de edição em read-only: a edição é exclusiva da Gestão. |
| **Gestão** | `/gestao` | **Gestão de EGPs/Inputs** (switch, KPIs, tabela com datas editáveis, sidepanel de status/comentários, gráficos — ver §Gestão de EGPs/Inputs) + cadastro de analistas. **Só grupo `bv_users`.** |
| ~~Ingestão~~ | `/ingestao` | **Removida (2026-08):** upload de `.egp`/`chameleon.csv` + "Processar & publicar" in-app. Não era usada; o refresh dos dados voltou a ser só pelo pipeline local (§Refresh dos dados). Backend (`ingest.py`, `/api/ingest/*`) e `app/pipeline/` **apagados** — histórico na spec/plano de 2026-07-03. |

## API

Todas sob `/api/*` (declaradas **antes** do mount estático do SPA → têm precedência). Cada request roda como o usuário (OBO).

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` · `/api/me` · `/api/config` | sanidade · `current_user()` · opções (status, categorias, **origens**, scope, `is_gestao`) |
| GET | `/api/metrics?scope` · `/api/landing` · `/api/resumo` · `/api/funis` | métricas do snapshot (dormente) · landing · agregados do Resumo (funil/origem ± deps) · dados dos 4 funis |
| GET / PATCH | `/api/inputs` | linhas (filtros server-side: scope, categoria, **origem**, status, q, divergence) / grava `status_humano`·`responsavel`·`observacao` |
| GET | `/api/input?chave` · `/api/inputs-egps?scope` | EGPs que consomem um input · pares input→EGP do recorte (export CSV) |
| GET | `/api/outputs` · `/api/output?chave` · `/api/outputs-egps` | outputs distintos (read-only) · produtores+consumidores de 1 output · pares output→EGP |
| GET | `/api/egp?projeto` · `/api/egp-readiness?scope=indi\|indi_deps\|base` | detalhe de 1 EGP (deps **com status p/ selo Migrado/Despriorizado** + inputs) · prontidão por EGP (rows + header de inputs distintos; aba EGPs unificada) |
| GET | `/api/egp-input-units?scope=indi\|indi_deps\|base` | unidades de input por EGP (universo + estado do MESMO dataset da Visão geral) — alimenta os cards vivos da aba EGPs |
| PATCH | `/api/egp-pipeline` | grava **etapa/status/responsável** do EGP no funil de migração |
| GET | `/api/priorizacao` | plano de meses (recorte fixo indi+deps; capacidade da config, default 400) + resumo |
| PATCH | `/api/priorizacao/mes` · `/api/priorizacao/capacidade` | fixa/solta o **mês pinado** de um EGP (1..100) · muda a **capacidade** persistida do plano (1..10000) — ambos **gestão** |
| GET/POST/DELETE | `/api/indicium` · `/api/escopo` · `/api/escopo/{id}[/ativar]` | lista DOR1 · adiciona · desativa (soft; `?hard=true` apaga) / reativa (cada edição **re-deriva o escopo** no app todo) |
| GET/POST/DELETE | `/api/analistas[/{email}]` | GET aberto (dropdowns); escritas **gestão**; delete soft. O antigo `sync-grupo` (SCIM do Databricks) saiu na Fase 2: cadastro só manual |
| GET | `/api/scope-egps?scope&area` | indicador n_egps/n_base/n_deps do recorte (cards do Monitor) |
| GET | `/api/egps-atualizados` · `/api/egps-atualizados/aguardando-corpus` · `/api/egp-atualizado?versao_id` | versões recebidas (módulo `backend/egps_atualizados.py`, **read-only puro**): catálogo p/ a busca do vínculo no detalhe do EGP · guarda "aguardando corpus" + pendências · comparação com o antecessor (inputs com JOIN vivo no monitor, outputs, histórico). O PATCH do funil próprio saiu com a aba (2026-09) |
| GET | `/api/lineage/{areas,search,graph,neighbors}` | grafo de linhagem — `areas`/`graph`/`neighbors` com cache em memória (ver Decisões); `search` é live. **Aba Linhagem desativada (2026-07)** — rotas mantidas, sem UI |
| GET | `/api/waves?scope` · `/api/audit?chave` | ondas do dado (**dormente** — a aba virou Priorização) · auditoria das edições |
| GET/POST/PATCH/DELETE | `/api/prioridades[/{id}[/move]]` | fila de prioridades — **aba removida; rotas + Delta table dormentes** (mantidas, sem UI) |

> `GET /api/migration-scope` **não existe mais** (2026-07): a aba "Escopo de migração" foi absorvida pela aba EGPs — use `/api/egp-readiness?scope=indi_deps`.

## Decisões de design (por quê?)

### Etapa espelhada resolve com o sucessor fora do recorte (2026-10-08)

Três cascas apareciam na tabela da aba EGPs com **`— etapa —`** e, ao abrir o drawer, com
**`Pré-conversão`**.

A etapa delas é espelhada do unificador, e `anexa_vinculo` resolvia o espelho lendo a etapa
**das linhas do próprio payload**. No recorte "só Indicium" as cascas aparecem (nascem com
`escopo_indi=true`, regra 27) mas o unificador não (é sucessor, `escopo_indi=false`): o
`.get` não achava de quem espelhar e devolvia `None`. O drawer carrega o recorte `base`,
onde o unificador existe — daí a divergência entre as duas telas.

Não eram 3 linhas e sim **27**: atinge todo antecessor cujo sucessor está fora do recorte
carregado. Em `indi_deps` e `base` o número sempre foi 0.

`anexa_vinculo` ganhou `etapa_de` — a leitura crua da tabela INTEIRA (`_pipe_egp_map`,
cacheada por geração, sem query nova por recorte). O que o `.get` sem default protegia
continua protegido: o fallback **nunca** é a etapa do próprio antecessor (exibir a velha
como se fosse a nova), só a do sucessor lida de outro lugar; sucessor inexistente segue
virando `None`, e a linha carregada vence a tabela inteira quando as duas têm o valor.

Medido em prod: recorte `indi` saiu de **27 linhas com `etapa=None` para 0**.

### Tabela da aba EGPs: colunas # e EGP congeladas (2026-09)

A tabela tem 16 colunas e não cabe em tela nenhuma: rolando para a direita até Status/
Responsável, sobravam fragmentos do nome (`IS_v2`, `a_Base_D0…`) e não dava para saber de
qual EGP era a linha. As duas primeiras colunas agora são `position: sticky`.

**Por que o scroll horizontal mudou de elemento.** `sticky` se ancora no container de scroll
**mais próximo**. O `.rd-tbody` já era um (tem `overflow: auto` para o scroll vertical), então
com o scroll horizontal no `.rd-table` a célula congelada rolava junto e não congelava nada. O
X passou para o `.rd-tbody`; como o cabeçalho é **irmão** do corpo, ele vive num wrapper
recortado e acompanha por `scrollLeft` no `onScroll` do corpo (`onBodyScroll`). Se o cabeçalho
dessincronizar do corpo, é aí que quebrou.

**Por que tudo está escopado em `.rd-egps`.** `.rd-table`, `.rd-thead` e `.rd-trow` são
reusados pela tabela do Escopo (`.ms-table`), com primeira coluna e larguras diferentes.
Regra global de `sticky`/`min-width` a desalinha silenciosamente. Qualquer coisa específica
da aba EGPs entra sob `.rd-egps`, nunca na regra genérica.

A coluna **"Último status"** saiu da tabela na mesma leva (−140px): o texto já aparece no
drawer do EGP, com o histórico completo, e era a coluna mais larga que não identificava nem
era editável. Com ela foi embora a única leitura de `gestaoApi.listRows` nesta aba.

### Sub-área BV é atributo da pessoa, não do EGP (2026-09)

A **sub-área BV** é a área interna do cliente (Digital, MIS, Operações, Estratégia - cartões,
Estratégia - rodas, Riscos) e fica no cadastro `sas_responsaveis_bv` (aba Gestão → Responsáveis
BV), chaveado pelo nome **normalizado** (trim + minúsculas + sem acento + espaços colapsados —
`_norm_nome_bv` no backend, `normNome` em `frontend/src/subareas.ts`; mudou num, muda no outro).

O EGP herda a sub-área do seu `responsavel_bv`; o input herda as dos EGPs que o consomem
(multi-valorado — a soma dos chips pode passar do nº de linhas, e isso é correto). **Não existe**
sub-área editável por EGP: seria trabalho manual em ~200 linhas e divergiria do responsável. Quem
não está no cadastro aparece como **"Sem sub-área"** — bucket visível de propósito, é o sinal de
que falta cadastrar alguém, não um EGP escondido.

Não confundir com **Área** (Cobrança/Riscos/Jurídico), que é a área de **negócio** do EGP e é outro
eixo: um EGP de Cobrança pode ter responsável da sub-área MIS.

Duas armadilhas que já custaram caro:

- **A contagem de cada chip ignora o próprio filtro de sub-área** (`baseSemSubarea` em
  `ReadinessView`/`AcompanhamentoView`). Contar sobre o conjunto já filtrado zera todos os outros
  chips ao clicar em um, e nenhum volta a ser clicável.
- **Grafia é identidade.** `responsavel_bv` é texto livre: "Leticia" e "Leticia Domingos Duarte"
  viravam duas pessoas em sub-áreas diferentes. Prod foi normalizado por
  `egps_analysis/scripts/normaliza_responsavel_bv.py` e o campo ganhou datalist do cadastro para
  não recriar o problema.

As colunas da tabela por sub-área são uma **partição por status** (`baldeEgp` em
`pipeline.ts`): *A migrar + Migrados + Despriorizados = EGPs*, em toda linha. Foi uma troca
deliberada (2026-09-16) — as colunas anteriores, "Bloqueados" e "Inputs faltando", **não
fechavam com o total**:

- **Inputs faltando** somava `n_faltam` por EGP: 1.615 contra 1.175 inputs distintos (1,37x).
  Pior, a métrica **não é somável por sub-área** — 112 inputs pendentes são lidos por EGPs de
  sub-áreas diferentes e pertencem às duas, então nem a soma das linhas corrigidas (1.292)
  chega à união real (1.180). Inputs distintos a ingerir só no card "A ingerir" da aba EGPs.
- **Bloqueados** era correto (contagem de EGPs), mas exibia 123 ao lado dos 130 do chip da aba
  EGPs — a diferença são ex-dependências bloqueadas, listadas lá e fora dos totais aqui. Dois
  números para o mesmo conceito na mesma sessão de leitura.

A tabela do Resumo conta o **mesmo universo das demais superfícies**: `/api/egp-readiness`
LISTA todas as ex-dependências (badge de retenção), mas só as com **etapa real** entram nos
totais — `contaNoTotalEgp` em `pipeline.ts`, espelho de `_ex_deps_contab` no backend. Sem esse
filtro a tabela somava 208 onde o card da aba EGPs mostra 194. Quem **soma** EGPs filtra por
isso; quem só **lista**, não (por isso os chips da aba EGPs contam sobre as 208 listadas).

Uma exceção (25/09/2026): etapa **fantasma conta** quando o status é `Despriorizado e
Contabilizado`. `Pré-conversão` segue fora da ordem do funil — ela é anterior a "Projetos
Habilitados", só a conversão do código sem tabela correta nem nada pronto —, mas
despriorizar um EGP que já teve pré-conversão é justamente reconhecer o esforço gasto.
Motiva o caso da **ex-dependência resolvida por ingestão**: a tabela entrou no lake, a
aresta morreu e o trabalho feito no produtor ficaria órfão. Esse caso tem **dois desfechos**
— o produtor foi dispensado (status `Despriorizado e Contabilizado`) ou continua necessário
porque a ingestão não cobre o que o consumidor lê (botão **"ainda é dependência"**, que
reabre a aresta por par consumidor/input via `sas_egp_dep_mantida` — espelho do
`link_broken`, e a regra vive em DUAS cópias, `main.py` e `publish_to_databricks.py`, com
teste de paridade em `backend/test_dep_mantida.py`).
→ `docs/analises/EX_DEP_RESOLVIDA_POR_INGESTAO.md`.

A tabela do Resumo é calculada **no cliente** sobre `/api/readiness` (mesma queryKey da aba EGPs) —
nenhuma query nova no warehouse. `sas_responsaveis_bv` fica **fora do publish**, como
`sas_analistas`: guarda dado 100% humano e nunca é dropada no republish. Seed reproduzível em
`egps_analysis/scripts/seed_responsaveis_bv.py`.

### Família de safras é a unidade de input (2026-09, atrás de flag)

Safras datadas da mesma tabela lógica (`GRIMALDI.CARGA_MASSIFICADOS_202506`, `_202507`, …) contam como **um** input em toda superfície quando `FAMILIAS_SAFRA=1`. Motivo: a ingestão de uma família cria **uma** tabela particionada no destino (das 5.772 origens da chameleon, só 2 têm sufixo de safra) e a carga é incremental por pasta — acrescentar safra depois não é ingestão nova. Medido em prod: o escopo Indicium cai de 2.446 linhas para **1.438 unidades** (126 famílias, régua do corpus; medido em prod em 17/09/2026). Racional completo, alternativas rejeitadas e consequências: `docs/adr/0002-familia-de-safras-como-unidade-de-input.md` (raiz do repo).

Sete coisas que parecem bug e são decisão (não "consertar" sem ler o ADR):

- **O grafo continua no grão da safra.** Linhagem, produtor canônico e o casamento input↔output seguem por safra; família é camada de contagem, exibição e estado. Colapsar os dois lados trocaria erro de contagem por erro de linhagem, muito mais caro de detectar.
- **Safra terminal não conta nem segura.** Família com 47 `Sanitizado` + 11 vivas é **1 input pendente**; todas terminais = 1 input fora da fila. Isso tornou histórico o lote de 73 sanitizações da regra 12M/3M (11/09/2026), que era a forma de dizer "isso não é trabalho" quando a única unidade era a safra.
- **`n_disp` é derivado de `n_faltam`, não contado direto.** `count(DISTINCT CASE WHEN modernizado…)` diria que uma família com 1 safra pronta e 46 pendentes está resolvida. A régua é a inversa: qualquer safra pendente segura a família.
- **Contagem por família em SQL dispensa window function:** `count(DISTINCT <candidato de família>)` já é a contagem certa — dois artefatos só caem no mesmo candidato se forem membros da mesma família, e candidato de artefato solitário é 1:1 com ele (`_fam_sql_egp()`). Mas a guarda dos **≥2 membros** é decisão de CORPUS: resolver sobre o recorte em tela faz a mesma tabela ser "família" num escopo e "input solto" noutro (invariante 3 de `familias.py`).
- **Escrita é fan-out**: editar a família grava nas N safras, com auditoria por safra — não há linha de estado na chave da família (duas verdades no banco é o que produz número divergente entre telas). A chave `familia::cat::NOME` é só transporte; nenhuma tabela é chaveada por ela.
- **O histórico colapsa o fan-out, a gravação não.** Uma edição de família grava N linhas em `sas_inputs_audit`, no mesmo instante (39 numa edição real de `CARNEIRO.BASE_3040_{SAFRA}`). `/api/audit` agrupa por chave de família + campo + valores + autor + instante e devolve `n_safras`, com o `LIMIT` **depois** do `GROUP BY` — sem isso uma edição comia o limite da aba Histórico e escondia o resto do dia. A chave de família no `GROUP BY` é o que separa fan-out de edição em lote: tabelas diferentes no mesmo segundo seguem uma linha cada.
- **Nome sem data também pode ser safra.** `PERF_CL.PAGOS_CYBER_`, `CARNEIRO.BASE_3040_` e outros 19 perderam o token para uma macro de runtime (`PAGOS_CYBER_&DAT_EXEC.`) ou para um curinga (`SET MIKE.TESTE_ENC_1PMT_:`) e por isso não achavam as próprias safras. Entraram como exceção curada em `familias_overrides.json` (`juntar`, um membro por entrada, macro/curinga no motivo) — virar regra ("separador solto vale por data") erraria nos 28 nomes que têm separador solto e família nenhuma. A guarda de `juntar` aceita **um** membro justamente para isso: a família já existe pela regra, e fixar uma safra só para satisfazer um mínimo de dois faria um re-key derrubar a carga dos overrides (`strict=True`).
- **Fase 1 cobre só `categoria='tabela'`, agora por medição e não por falta de dado.** Desde 17/09/2026 o publish também publica `paths_fisicos` para `arquivo`/`script` (vem pronto da coluna `path` do relatório 06 — o artifact é o basename dele; 2.650 de 2.650 linhas cobertas, 155 com o mesmo nome em pastas diferentes). Com o caminho em mão, dá para formar família de arquivo — e rende pouco: **6 famílias, 94 arquivos, 6 deles no escopo Indicium** (a maior é `EXCECOES_V2.CSV`, 67 arquivos numa pasta só). O caminho *confirmou* a guarda antiga: sem ele, um `EXCECOES.CSV` juntaria 154 membros sem prova; com ele, os dados se separam em 67 (`_V2`) + 12 (`_V3`) na mesma pasta. Estender a máquina de família para a categoria não se paga hoje.

**Profundidade** (quanto de passado cada EGP precisa) é propriedade do **par (EGP, família)**, não da família: 52 de 74 famílias multi-EGP têm consumidores pedindo profundidades diferentes (`CARTAOBV.TBL_RAC_RESUMO`: 103m, 98m, 36m, 36m). A **necessária** é derivada ao vivo das safras que o EGP lê (nunca gravada — valor derivado persistido envelhece) e só a gestão declara outra (`sas_egp_input_periodo`); a **ingerida** é fato consumado que qualquer analista registra (`sas_familia_ingestao`, só `desde AAAAMM`). Os avisos (carga rasa, dispersão, leitura esparsa) são **informativos**: campo manual esquecido não pode virar bloqueio.

**Ligar/validar.** A flag está **LIGADA** no `app.yaml` e no `app.dev.yaml` desde 17/09/2026 —
prod conta por família. Desligar é remover as duas linhas do manifesto e redeployar: reversível
sem republish, porque nada é materializado. No run local, `FAMILIAS_SAFRA=1` na env. Dois scripts read-only
medem de propósito por fora e por dentro: `egps_analysis/scripts/verifica_familias.py` (SQL: paridade da regra
e contagens) e `egps_analysis/scripts/verifica_familias_api.py` (chama a API nos dois estados da flag e confere
4 coerências — card == dataset == universo do funil == tabela de origem, e funil por mês == funil +deps;
recusa rodar contra o schema de prod). Medido no dev em 15/09/2026: Inputs 2.408 linhas → **1.378 unidades**
(125 famílias), landing 2.297/1.189 → **1.341/533**, readiness Σfaltam 1.850 → **1.025**, com as 4 coerências
OK nos dois estados. Duas réguas que **parecem** divergência: (a) contar famílias "no recorte" dá 98 e por
**corpus** dá 125 — a do corpus é a certa; (b) `pendentes` do script é grão monitor (544) e o card da landing é
universo por vínculo ativo (533); (c) **não reimplemente a conta de pendentes** — a landing soma escopo
+ (deps − escopo), em dois datasets, e `_estado_familia` roda sobre os membros de CADA um, então uma família
com composição diferente nos dois pode virar de estado. Medir por `py_aingerir` sobre um `_dataset_escopo("indi_deps")`
único deu 444 contra os 441 da tela (21/09/2026). Chame `landing()`. Plano, medições de prod e backlog da fase 2:
`docs/superpowers/plans/2026-09-15-familias-de-safra.md`.

### EGPs Atualizados: isolamento de escrita, não de leitura (2026-09)

> A **aba** foi aposentada em 2026-09 (spec §5) — as tabelas, o script local e este
> isolamento **continuam valendo**. Depois da aposentadoria o backend é read-only *puro*:
> o funil próprio (`sas_egp_atualizados_pipeline`/`_audit`) era o único ponto de escrita e
> saiu com a tela; as duas tabelas ficam como registro histórico, sem serem lidas pelo app.

Versões novas de EGP vivem em **tabelas próprias** (`sas_egp_atualizados`/`_inputs`/`_outputs`), criadas e alimentadas **só** pelo script local `egps_analysis/publish_egps_atualizados.py` — o publish geral nunca as toca, e o backend da aba (`backend/egps_atualizados.py`) **nunca escreve** em tabela alguma. Mas a **leitura cruza**: a disponibilidade dos inputs é um JOIN vivo read-only com `sas_inputs_monitor`, usando o **mesmo predicado `_modern`** das demais abas (injetado pelo `main.py` no `register()` — não duplicar a regra). Racional completo: `docs/adr/0001-egps-atualizados-isolamento-de-escrita.md` (raiz do repo). Armadilha: a **chave canônica** dos inputs da carga segue a regra do pipeline (tabela = artefato inteiro; arquivo/script = **basename**) — divergiu, o JOIN não casa e tudo vira "fora do corpus" silenciosamente. Modelo versionado por append (`versao_id = <egp_key>@<data>`; re-publicar a mesma data substitui só ela). Fase 2 (troca de versão no escopo) reservou `status_troca`; ação será script local + botão oculto `bv_admins`.

> Racional das escolhas que costumam virar dúvida em sessão futura. **Status/funil:** `frontend/src/pipeline.ts` é espelho de `backend/main.py` — mantenha os dois em sincronia.

### Vocabulário de status do EGP (7 valores)

`A Iniciar · Em Andamento · Em espera · Concluído · Block · Despriorizado e Contabilizado · Migrado` (definições em `pipeline.ts:STATUS_HELP`).

- **Por que `Concluído` *e* `Migrado`?** `Concluído` = concluiu *a etapa atual* do funil (intermediário, repetível a cada etapa); `Migrado` = estado **terminal** do projeto (em produção e validado pela área). Um EGP fica `Concluído` várias vezes (uma por etapa) antes de ficar `Migrado` uma vez.
- **Tempo por Etapa em DIAS ÚTEIS (2026-10-06):** todas as contas da aba (tempo por etapa, Com BV/Conosco, por status, lead time, aging — funis de migração e de ingestão) descontam fins de semana e feriados nacionais BR via `_dias_uteis_entre` (intervalo semiaberto `[entrada, saída)`). `FERIADOS_BR` em `backend/main.py` **espelha** `frontend/src/diasUteis.ts` (2025–2027) — mudou num, sincronize o outro. O número é menor que o de dias corridos e deve ser lido assim; séries antigas não foram regravadas (a conta é de leitura).
- **`Em espera` (2026-10-01)** é diferente de `Block`: não é um impedimento externo, é o responsável ocupado em **outro** EGP (cada pessoa só avança 1 por vez). Dias nesse status são **excluídos** das métricas de tempo da aba "Tempo por Etapa" (`_dias_uteis_segmentos` em `backend/main.py`) — lead time, tempo por etapa (total/Com BV/Conosco) e aging — pra não inflar o tempo "real" gasto no EGP com tempo que, na prática, foi gasto em outro.
- **`Despriorizado e Contabilizado`** é a única **saída de backlog** (2026-07): o antigo `Removido` (saída sem ingestão) foi **extinto e fundido** nele — dados de prod migrados por UPDATE; a auditoria preserva os valores históricos. O esforço já gasto (quando houve) fica contabilizado. EGP nesse status **não puxa dependências exclusivas**; ele mesmo segue no plano e nas contagens como um EGP normal (ver §"Despriorizado e Contabilizado" não puxa dependências). Quem **depende** dele ganha o aviso **⏸** ("impactado por dependência despriorizada"): flag `deps_despriorizadas` nas rows da aba EGPs (badge + chip de filtro + coluna no CSV) e bloco `impacto_despriorizado` no `/api/egp` (painel de detalhe) — propagação transitiva downstream (mesma direção do bloqueio), sobre as arestas já filtradas (via resolvida não conta).
- **`Block`** continua no backlog (será retomado) — por isso é distinto de sair do backlog.

### Funil de migração: etapas × status (a "banda")

9 **etapas** no eixo (`pipeline.ts:PIPELINE_PROJETO.migracao`: Projetos Habilitados → … → Migrado); cada barra é empilhada pelos **status** (segmentos coloridos, ordem fixa em `SEG_ORDER`, paleta acessível a daltonismo).

- **Por que status como "banda" e não como etapa?** Etapa = *onde* o projeto está no fluxo; status = *como* ele está naquela etapa. São ortogonais — um projeto em "Validação em DES" pode estar `Em Andamento`, `Block` ou `Concluído`. Colapsar os dois num eixo só perdia informação.
- **Removido o funil "Progresso Projetos"** (incremento anterior): era quase idêntico ao funil de migração + status e gerava confusão (dois funis redundantes). Migração + banda de status cobrem o mesmo sem duplicar.
- `Migrado` é **etapa terminal** e **status** — coerente: ao chegar na etapa Migrado, o status vira Migrado.
- **Etapas "fantasma" (`PHANTOM_ETAPAS_MIGRACAO`), fora da ordem do funil:** `Pré-conversão` (pré-conversão iniciada sem passar por "Conversão do Código", p/ destravar o funil enquanto BV atrasa outputs) e **`Conversão pela Área`** (2026-08: a conversão de código deste EGP **não é escopo da Indicium** — a própria área de negócio do BV converte; só a **ingestão dos inputs** segue acompanhada). Ambas ficam fora do coorte/denominador do funil de migração (não inflam nem contam em "X/Y migrados") e aparecem só como contador no topo (`top_stats`). **Por que etapa e não status?** Diferente de `Despriorizado e Contabilizado` (que é status e aciona `no_expand`/`_egps_fora_backlog`), aqui a Indicium continua responsável pela ingestão — então as dependências do EGP devem continuar sendo puxadas normalmente nos recortes "+ dependências". Editável no seletor de Etapa (grupo "Fora do funil") em qualquer linha da aba EGPs.
- **Headline "X/Y migrados" conta por STATUS, não por etapa (2026-06):** numerador = EGPs com status terminal **Migrado + Removido + Despriorizado e Contabilizado** (`proj_funnel`: `if stt in BANDS or stt == "Migrado"`), i.e. a soma das bandas "resolvidas". **Não** voltar para "chegou na última etapa" — incluía um `Concluído@Migrado`, que não é status terminal, e divergia da soma visível das bandas.

### `origem` do input (6 valores) e "produtor ausente"

`origem ∈ {BigQuery, Transacional, SAS/Local (externo), SAS/Local (dependência), Arquivo, Script}` (`main.py:ORIGENS`). Responde **"de onde vem este input?"**:

- **`BigQuery`** — já no lake/BQ (modernizado por construção).
- **`Transacional`** — banco transacional corporativo (Sybase/SQL Server/…) a modernizar.
- **`SAS/Local (dependência)`** — tabela SAS/Local **produzida por outro EGP do corpus** → vira aresta EGP→EGP (dependência interna).
- **`SAS/Local (externo)`** — tabela SAS/Local que **nenhum EGP do corpus produz**. **Decisão (2026-06):** classificar como **"externo" = dependência de um produtor ausente** (rótulo na UI: **"dep. produtor ausente"**), em vez de tratá-la como dado genérico a ingerir. O EGP produtor existe fora do recorte analisado; marcá-la "externo" deixa **explícito que falta mapear esse produtor** — não esconde a tabela entre os inputs comuns nem inventa uma fonte. Detalhe da classificação subjacente: `docs/CLASSIFICACAO_INPUTS_SAS.md` §3–4 e §8.
- **`Arquivo`/`Script`** — arquivo físico (`file_in`) / `%INCLUDE` (`script_in`).

**Homônimos:** o mesmo nome de input SAS/Local pode mapear para **N tabelas físicas distintas** (`n_paths_fisicos > 1`) — sinalizado como "homônimo" no detalhe do EGP, porque a linhagem é por **(path físico, membro)**, não só pelo nome.

### Identidade física dos homônimos: colunas aditivas, não colapsadas

O publish anexa a `sas_inputs_monitor` duas colunas **derivadas e aditivas**: `paths_fisicos` (paths resolvidos via `libname_resolver`, ` | `-joined) e `n_paths_fisicos` (contagem). A UI mostra o badge **"homônimo: N tab. físicas"** quando `n_paths_fisicos > 1`.

- **Por que colunas novas e não colapsar as linhas homônimas numa só?** As linhas são chaveadas por `chave_canonica`, que carrega os **status humanos** (`status_humano`/`responsavel`/`observacao`, preenchidos pelos analistas) e a auditoria. Colapsar homônimos numa linha **destruiria** esses status e a monitoria já feita. A identidade física é exposta **ao lado** do dado existente; o MERGE do publish **não toca** as colunas humanas (ver §Refresh dos dados).
- **Por que a contagem de inputs *aumentou* ao considerar o path, em vez de diminuir?** A intuição inicial era que tratar "os iguais" como um só **reduziria** o total. Os dados mostraram o contrário: **6.474 inputs por nome → 6.767 por identidade física** (439 homônimos, mais do que o nº de aliases). Motivo: o mesmo **nome** em **paths diferentes** costuma ser **tabelas distintas** (o falso-merge que a chave-por-nome escondia), não cópias — então separá-las por path **aumenta** a contagem real. Consolidar cópias *verdadeiras* é assunto à parte (`../docs/analises/PLANO_CONSOLIDACAO_SASLOCAL.md`), e exclui os `multi_produtor` exatamente por isso.

### Filtros multi-select

Todos os dropdowns (categoria, origem, status, área, etapa) são **multi-select** (checkbox). O uso real é combinatório — "cobrança **e** crédito", status `Block` **ou** `A Iniciar` — e single-select forçava refiltrar a cada combinação. O filtro "modernização" do Monitoramento foi **removido** (redundante com `origem`/status).

- **"selecionar todos" ≠ seleção vazia.** Seleção vazia é "sem filtro"; "selecionar todos" deixa o `Set` com **todas** as opções, para o caso real de excluir só 1-2 delas (marca tudo, desmarca o que não quer) sem cair de volta em "sem filtro".
- **`onSelectAll` é obrigatório para consumidores com estado derivado do render (fix 2026-09).** O `MultiSelect` aceita `onSelectAll(options)` e, quando ele existe, "selecionar todos" vira **uma** transição de estado com a lista inteira. O laço opção-a-opção (`onToggle` N vezes) só é correto para quem usa `setState` **funcional**: a `FilterBar` da aba Inputs calcula o patch a partir do `filters` **capturado no render** (`toggleArr(filters.etapa, v)`), então as N chamadas partiam todas do mesmo valor velho e a última sobrescrevia as outras — marcava **1** opção só. Consumidor novo que não usa updater funcional **precisa** passar `onSelectAll`.
- **Opções do filtro de Área = só as áreas presentes no recorte (2026-09).** Antes vinha a lista canônica do `/api/config`, então dava para marcar uma área sem nenhum input no escopo (ex.: Atacado em `indi_deps`) e a única consequência era zerar a tela. As opções são derivadas no `MonitorView` a partir do recorte filtrado por **tudo menos a própria Área** (`semArea`) — se saíssem do recorte já filtrado por área, escolher uma apagaria as outras da lista e não daria para trocar. Área **já selecionada nunca some**, mesmo que outro filtro zere a contagem dela (senão sobra um filtro ativo e invisível).

### Performance (resumo — detalhe em [`ANALISE_PERFORMANCE.md`](ANALISE_PERFORMANCE.md))

- **Não** trocamos de linguagem (Go/Rust) nem de framework de front. O app é **I/O-bound** no SQL Warehouse (cada request espera o Statement Execution API); a CPU local não é o gargalo. Trocar seria *teatro de performance*. (Veredito completo no doc.)
- Implementado nesta linha: logging de latência (`[perf]`), DDL fora do hot-path (`functools.lru_cache`), fim do re-SELECT no `PATCH`, e **cache em memória** (linhagem, dataset do escopo, payload) com TTL 5 min + **invalidação por geração** (toda mutação bumpa; leitura começada antes de um bump nunca é servida depois dele).
- **Cache COMPARTILHADO entre usuários + prova de leitura por token (2026-10).** A chave deixou de levar o hash do token OBO: o schema não tem row filter/column mask e os grants de leitura são por schema (medido), então o dado é o mesmo para todo leitor. O que a chave por token protegia passa a ser checado por `_sessao()` — 1 query OBO por token a cada 5 min, com um scalar subquery em `sas_inputs_monitor` que falha (403) para quem não lê o schema. **Se entrar row filter ou grant por tabela, a chave volta a precisar da identidade.** Single-flight: GETs concorrentes da mesma chave esperam o primeiro. Detalhe e medição: `ANALISE_PERFORMANCE.md` §8.
  - **Regra que sustenta isso: checagem de grupo (`_require_gestao`/`_require_admin`) vai no HANDLER, antes de qualquer leitura cacheada — nunca dentro de um produtor.** Um produtor que dependa de quem pede serviria o resultado de um gestor para quem não é. `test_cache_compartilhado_gestao.py` quebra se isso acontecer (guarda estrutural, com teste de mutação feito) e prova o 403 de ponta a ponta com o cache aquecido por um gestor.
- **Leitura que falha não vira vazio (2026-10).** Só `TABLE_OR_VIEW_NOT_FOUND`/`UNRESOLVED_COLUMN` (`_objeto_ausente`) cai no fallback "ainda não publicado"; timeout/403/502 sobem. Antes, um timeout virava conjunto vazio **cacheado** e mudava contagem em silêncio.

### Deep-links `/egps/<id>`

Cada EGP tem URL própria compartilhável (`id = encodeURIComponent(projeto)`). Abrir/atualizar o link cai direto no EGP (abre, rola até a linha, destaca); o botão **🔗 link** no detalhe copia a URL.

- **Por que `<base href="/">` no `index.html`?** O Vite usa `base: "./"` (relativo). Numa rota aninhada como `/egps/<id>`, `./assets/...` resolveria contra `/egps/` → bundle 404 → o fallback SPA (`_SPAStaticFiles`) devolve `index.html` como `text/html` → **página em branco**; e os `fetch("api/...")` relativos virariam `/egps/api/...`. O `<base href="/">` ancora assets **e** chamadas de API na raiz (o app é servido na raiz do seu subdomínio Databricks). **Qualquer rota aninhada nova depende dele.**
- **Por que `projeto` (encoded) como id, e não `egp_dor1`?** `projeto` é a chave universal (chave de linha, do `/api/egp`, do cross-nav Escopo→EGPs); `egp_dor1` só existe no Escopo e nem todo EGP está no escopo. O parse junta os segmentos antes do `decodeURIComponent`, então tolera `/` no nome.

### Sanitizado = removido do escopo (app inteiro) (2026-06)

`Sanitizado` (status efetivo; engloba legados `Sanitizada`/`Descartada`/`Descartado`) = input **descartado/removido do escopo** — não é "feito", é "não vai ser migrado". Helper `main.py:_sanitizado()`; injetamos `AND NOT _sanitizado(...)` no **universo de toda contagem de escopo**: `metrics`, `landing`, `_egp_readiness_rows`, `migration_scope` (distintos), `waves`, `resumo` e o **funil de ingestão**.

- **Por que filtrar o universo e NÃO mexer em `_modern`/`_aingerir`?** Num conjunto já sem Sanitizado, `_modern` (`IN ('Modernizado','Sanitizado','Autoprodutor')` — ver seção seguinte) = só Modernizado(+Autoprodutor) e `_aingerir` (`NOT _modern`) = pendente — os helpers seguem corretos **sem alteração**. "A ingerir" já excluía Sanitizado (ele conta como `_modern`). Os únicos bugs eram Sanitizado entrar no **denominador** e como **disponível** — resolvidos filtrando o universo. **Não reverter** mudando os helpers.
- **Continua VISÍVEL na lista do Monitor** (grade de gestão, filtro de status) — só sai dos **contadores/métricas**. Esconder da lista tiraria a capacidade de gerir/reverter.

### Sanitização DERIVADA: input que só despriorizado lê sai da fila (2026-09)

§3.4.18 da spec `docs/superpowers/specs/2026-09-24-egps-atualizados-unificacao-design.md`. Input cujos consumidores **no recorte ativo** (Indi ∪ deps, vínculo não quebrado) são **todos** EGPs `Despriorizado e Contabilizado` conta como `Sanitizado` — e a fila de ingestão para de pedir aquela tabela ao BV. Medido em prod 24/09/2026: 370 chaves, das quais 202 já estavam sanitizadas na mão e ~132 saem da fila (110 "A receber" + 22 sem status).

- **Derivado, nunca gravado.** Régua pura em `backend/sanitizacao.py`; `main.py:_sanitizacao_derivada()` monta o conjunto (cacheado por geração, como `_egps_fora_backlog`). Nenhum status é escrito: **repriorizar um EGP devolve os inputs dele à fila sozinho**, no request seguinte. O status real vai junto na linha, em `status_real`.
- **O motivo é campo, não rótulo.** `sanitizado_derivado` (código) + `sanitizado_motivo` (legível) — o §3.4.15 (input lido só pelo antecessor de um vínculo) é a regra irmã e entra pelo mesmo caminho com outro motivo. Visível na aba Inputs (tag na 2ª linha) e no painel de detalhe.
- **Exibido como Modernizado + Sanitizado, com etapa/status TRAVADOS (14/10/2026).** O overlay também sobrescreve a `etapa` por `Modernizado` (a gravada vai em `etapa_real`), e o `PATCH /api/inputs` recusa etapa/status desses inputs com 409 — na família, a escrita pula as safras derivadas e só recusa se todas forem. Responsável e observação seguem editáveis. Motivo: com "A Receber" à vista o time lia pendência e marcava Modernizado à mão; a derivação só vale para chave **pendente**, então o input saía dela e passava a contar como modernizado, com o status cru `A Iniciar` do publish — 37 inputs lidos só pelo antecessor estavam assim em prod. A etapa exibida não muda contagem (Sanitizado já resolvia o input em toda régua). O drawer do EGP (`/api/egp`) passou a receber o mesmo overlay — antes mostrava o estado cru e editável.
- **Exclusividade é medida contra o ESCOPO ATIVO, não contra o corpus** (§3.4.16), e num recorte **único** (o mais largo, `indi_deps`) para o app inteiro — por escopo, a mesma chave sairia sanitizada na visão +deps e pendente na visão de escopo, na mesma página.
- **Só chave PENDENTE entra.** As 202 sanitizações manuais e as já modernizadas ficam exatamente como estão — a regra derivada não as re-rotula.
- **Fora:** o input sintético de casca `casco::` (§3.4.26, placeholder, não trabalho) e o `_blocking()` (semântica downstream, intocada — mesma reserva de `_egps_fora_backlog`).
- **Onde entra:** como `lnk` nas geradoras de `input_state` (o mesmo slot do vínculo quebrado, pela mesma razão — par (EGP, input) resolvido sem ninguém ter gravado nada). Pontos de contagem tratados: `_dataset_escopo` (aba Inputs/Resumo/funis com família ligada), `landing`, `funis`, `funil-ingestao-mes`, `resumo`, `gestao/rows`, `_egp_readiness_rows`, `_readiness_inputs_header`, `_sem_fonte_by_proj`, `waves`, `_compute_priorizacao`, `_prio_live_input_stats`.
- **Fica de fora de propósito:** `/api/inputs-recebidos-serie` (indicadores mensais), que só conta **eventos datáveis** de `sas_inputs_audit` — sanitização derivada não tem data porque não tem escrita.

### Autoprodutor: dispensa pré-working, CONTA COMO FEITO na prontidão (2026-08)

Status irmão de Sanitizado (`STATUS_INPUT`), para o input cujo **próprio EGP consumidor também CRIA** a tabela (não só apensa/atualiza) — em vez de reingerir um dado que a lógica migrada do EGP já vai regenerar, dispensa-se o pré-working. Mapeado antes numa análise manual pontual (`docs/analises/BV_Migracao_SAS_Analise_Inputs_Autogerados_2026-08-12.md`, 333 inputs/97 EGPs, metodologia Tier 1/Tier 2 via CSV) — este é o mecanismo **vivo** no app.

- **Diferença deliberada com Sanitizado: CONTA, não exclui.** Sanitizado sai do universo de contagem (`_sanitizado()` — "não se aplica"). Autoprodutor faz `_modern()` (`main.py:_modern`) retornar `true` (`IN ('Sanitizado','Autoprodutor')`), mas **NÃO** entra em `_sanitizado()` — soma no numerador **e** no denominador da prontidão por EGP (`_egp_readiness_rows`) e do funil de ingestão: é trabalho entregue por uma via alternativa, não descarte. Reaproveita o **mesmo vocabulário de status** do input (dropdown já existente em `PATCH /api/inputs`) — sem tabela nova, sem endpoint novo.
- **Detecção automática, confirmação manual.** `main.py:_autoprodutor_candidatos()` faz o join `sas_egp_inputs` (categoria='tabela') × `sas_egp_outputs` pelo mesmo `projeto`, restrito a `apenas_contribui = false` (o EGP de fato CRIA, não só apensa — mesmo critério Tier 1/2 da análise manual, já publicado ao vivo) e a criador **único** (`qtd_criadores<=1`) ou ao **produtor canônico** já escolhido (`_producer_choices()`, quando há múltiplos criadores). O resultado vira `autoprodutor_candidato`/`autoprodutor_egp` em cada linha de `/api/inputs` (badge "🔁 candidato a autoprodutor" na UI) — mas só conta na prontidão depois que alguém **confirma** marcando o status; `PATCH /api/inputs` rejeita (400) `status=Autoprodutor` em input que não é candidato.
- **Por que não usar `sas_lineage_edges`/`via_tabelas`?** O `orchestrator_inventory.py` pula de propósito a self-edge quando o leitor também escreve a tabela (`docs/CLASSIFICACAO_INPUTS_SAS.md` §"input que também é output do próprio EGP") — então o produtor nunca apareceria como dependência ali. O join precisa ser contra `sas_egp_outputs` diretamente.
- **Escopo GLOBAL, não por (EGP, input).** Uma vez confirmado, o input sai da fila de ingestão para **todos** os EGPs que o consomem, não só para o autoprodutor — decisão de produto (2026-08); o par-a-par foi descartado porque a maioria dos casos é o EGP autoprodutor sendo o único (ou canônico) consumidor real do dado.
- **`ingest_funnel()` trata Autoprodutor como etapa "Modernizado"** (mesmo sem a etapa real ter avançado) para cair no bucket `done`/coorte — aparece como segmento próprio (cor distinta, `SEG.Autoprodutor` no front) dentro da coluna "Modernizado" da barra, **não** como contador separado no topo (isso quebraria o invariante "KPIs do topo particionam o universo" — Autoprodutor é subconjunto de "Modernizado", não aditivo).

### Aba Inputs: ler "quem ainda depende disto" (2026-09)

Três mudanças com o mesmo objetivo — a tela precisa responder *quem ainda depende deste input*, não *quantos EGPs um dia o citaram*.

- **Detalhe do input mostra recorte + etapa + status de cada EGP.** Em "Usado por"/"Produzido por", cada EGP traz o **recorte** a que pertence (`indi` escopo Indicium direto · `dep` dependência transitiva viva · `ex` ex-dependência retida · `fora` fora do recorte, só na base completa), mais **etapa** e **status** do funil de migração. Quem está fora do recorte fica **tracejado e apagado** (e `fora` com o nome riscado), a lista é ordenada por recorte e o título traz a quebra ("9 escopo · 3 dependência · 2 fora do escopo", só vínculos vivos). **Por que no backend e não no cliente:** `escopo_indi` só distingue `indi`; o resto exige o **fecho** — `_enrich_egp_contexto()` (em `/api/input`) reusa `_frontier_egps("indi_deps")` + `_ex_deps()`, os **mesmos conjuntos** das abas EGPs/Inputs, em vez de uma regra paralela que sairia do lugar. Etapa/status vêm de `_pipe_egp_map()`, cacheado **por geração** (todo `PATCH /api/egp-pipeline` chama `_bump_gen()`), senão seria uma query por clique.
- **Ordem inicial da tabela = `#ativos`, não `#proj`.** `#proj` conta **todo** consumidor do corpus — inclusive despriorizado, fora do recorte ou com vínculo quebrado — e inflava o topo da lista com inputs que já não travam ninguém. `#ativos` (`n_proj_ativos`) é o que ainda pesa. Ambas seguem clicáveis; `n_proj_ativos` nulo (fora do recorte) vira `-1` no accessor e fica no fim nas duas direções.
- **Badge "🔁 candidato a autoprodutor" vive na 2ª linha, não na do nome.** A linha do nome é `nowrap` + `ellipsis`: um badge longo inline consumia a coluna inteira e **escondia o input**. Ele fica na faixa de badges (`.art-tags`), **depois** das pílulas de bloqueio — se o espaço apertar, o que clipa é o hint, não o sinal acionável. A faixa é `overflow: hidden` de propósito: a altura da linha é fixa (`ROW_H`), quebrar linha desalinharia a grid.

### Acompanhamento: um quadro por Responsável BV, recolhível (2026-09)

O Kanban do cliente é **separado por Responsável BV** — cada um com seu quadro completo, como se fosse uma tela só dele. Com muitos responsáveis isso vira uma pilha de Kanbans e ninguém acha o seu, então cada quadro **recolhe no título** (▾/▸), com "recolher/expandir todos" acima da lista.

- Recolhido, sobra a faixa de resumo (nº de EGPs/inputs + prontidão/checklist média) e o `GestaoKanban` **nem monta** — alivia o render, não só a poluição visual.
- O estado é **persistente** (`localStorage`, mesmo espírito do `useHeaderCollapse` das abas de tabela) e por **responsável**, não por entidade: quem cuida do próprio quadro não recolhe os outros toda vez que abre a aba, e a preferência vale para EGPs e Inputs.
- Com o chip "agrupar por Responsável BV" desligado é um quadro único, sem título e sem recolhimento (não há o que agrupar).

### Universo por vínculo: predicado único dos contadores (2026-07)

Input cujos vínculos (EGP, input) do recorte estão **TODOS quebrados** (`sas_egp_input_link.link_broken`) **sai do universo de contagem em TODAS as superfícies** — cards da landing, funil de ingestão (2 visões), tabelas do Resumo (por área/origem) e cards da aba Inputs. Predicado único: `main.py:_ch_vinculo_ativo(egp_where)` (semi-join "chave com ≥1 vínculo NÃO quebrado com EGP do recorte").

- **Por quê?** Antes cada endpoint aplicava (ou não) o filtro por conta própria: `/api/resumo` (+deps) filtrava, `/api/funis` e a parte de escopo do `/api/landing`/`/api/inputs` não → o Resumo divergia por N da própria página e da aba Inputs (o famoso "1811 vs 1812"). A semântica do vínculo quebrado sempre foi "resolvido/não conta"; agora ela vale por igual. **Não reintroduzir contagem sem o predicado** — qualquer contador novo de inputs deve usar `_ch_vinculo_ativo`.
- **A linha fica visível SÓ na base completa** (tag "sem vínculo ativo"): nos escopos Indicium/`indi_deps` ela sai da tabela **e do export CSV** (`MonitorView.filtered`) — sem isso o CSV "por EGP" explodia linhas com a coluna EGP vazia (input sem nenhum vínculo ativo no recorte não pertence a EGP algum do escopo+deps; pedido 2026-07-30). Na base completa segue listada/editável p/ gerir/reverter o vínculo (`vinculo_ativo=false` anotado por linha, bool Python → JSON).
- **`vinculo_ativo` ≠ `n_proj_ativos`:** `n_proj_ativos` também desconta EGPs **despriorizados** (régua mais estrita, p/ candidatura a re-priorização). O universo dos contadores NÃO desconta despriorizados (eles seguem no plano) — usar `n_proj_ativos == 0` p/ excluir dos cards divergiria do Resumo.
- **`escopo_indi` (flag) segue sendo superconjunto:** o `recompute_escopo` não olha links (de propósito — statements espelhados no publish); o estreitamento acontece nos endpoints via `IN _ch_vinculo_ativo(...)`.
- **Bucket de origem do Resumo derivado AO VIVO de `i.origem`** (mesma régua dos cards da aba Inputs): `sas_resumo_inputs.origem_bucket` (snapshot do publish) divergia — TODO script era bucketado `SAS/Local` (ex.: dev, SAS/Local 1735 vs 1737). O `CASE` em `/api/resumo` mapeia `i.origem` → bucket (`Arquivo`+`Script` → "Arquivo", exibido como "Arquivo/Script") e usa `r.origem_bucket` só como **fallback** p/ `i.origem` NULL (hoje só fora do universo). Desde 2026-09 a consulta **parte do monitor** (ver §Resumo dirigido pelo monitor abaixo) — `Libname_in` segue FORA da tabela porque libname não tem linha no monitor. **Não voltar a agrupar por `r.origem_bucket` direto.**

### Ex-dependências: esforço não desaparece (2026-08)

O frontier "+deps" é vivo; EGP que deixa de ser dependência (via resolvida, vínculo quebrado ou cadeia despriorizada via `no_expand`) sairia das telas levando o status junto (caso Riscos: despriorizados/convertidos sumiram dos contadores). Regra decidida com o PM (5 decisões, 2026-08-06): **todo** EGP que já foi dependência fica retido com badge **"ex-dependência"**.

Consequência para quem **publica** número de EGP: o recorte muda entre requests sem ninguém editar input. Em 21/09/2026 o frontier caiu de 182 (168 base + 14 deps) para 181 (168 + 13) em cerca de uma hora, e as ex-dependências de 26 para 25, sem nenhuma edição de input no período — o fecho é recalculado a cada request sobre `_edges_pruned` + `_egps_fora_backlog`. Fila e pendentes não se mexeram (a dep que saiu não tinha input exclusivo), mas o denominador da prontidão sim. Todo número de EGP em relatório precisa da data da medição, e não deve ser comparado com o **total da landing** (193 = 168 + 13 + 12 ex **contabilizadas**): o relatório conta quem gera fila de input, a landing conta quem tem trabalho de migração.

- **Derivação retroativa, sem tabela nova:** `main.py:_ex_deps()` = fecho transitivo sobre o grafo **BRUTO** (sem poda de produtor, sem filtro de vias resolvidas, sem `no_expand`) − frontier vivo. Motivo no tooltip: aresta viva → "cadeia despriorizada"; aresta podada → "resolvida por ingestão" (todas as vias entraram no lake, nenhuma Sanitizada: **houve entrega**) ou "via descartada/desvinculada" (descarte, vínculo quebrado ou produtor canônico). A distinção decide se o esforço gasto no produtor merece ser contabilizado — ver `docs/analises/EX_DEP_RESOLVIDA_POR_INGESTAO.md`.
- **Contam em numeradores E denominadores de EGP**: aba EGPs (tipo `ex_dependencia`, no fim da lista), funil de migração +deps, card "Dependências" com "(+N ex)", tabela por área do Resumo, Priorização (Recalcular retém: fim da ordem, **0 inputs novos** — não consomem capacidade nem entram na contagem viva do mês).
- **Contadores de INPUTS não mudam** (fila de entrega intacta). Na aba Inputs, input consumido **exclusivamente** por ex-deps entra FLAGADO (`ex_dependencia=true`): linha cinza + tag, atrás do chip **"mostrar ex-dependências" (off por padrão)** — tabela/export só os incluem com o chip ligado (coluna de marcador no CSV); os **cards nunca** os contam.
- **Não** usar isso para reintroduzir inputs de ex-dep em contagens — decisão explícita do PM (proteger a extração de entregáveis).

### Cards do Monitor: client-side e sensíveis a filtro (2026-06)

Os big numbers do Monitoramento são calculados **no cliente** das linhas **filtradas** (`MonitorView.cardMetrics`), não do `/api/metrics` (que ficou **dormente**). Refletem **todos** os filtros + busca, instantâneo, sem ida ao warehouse. **Não re-religar os cards no `/api/metrics`.**

- **Sanitizado nos cards:** fora por padrão (regra acima); **entra** quando o filtro de status inclui "Sanitizado" — senão filtrar só sanitizados zerava tudo. Regra: "cards refletem os filtros aplicados".
- **Cards por origem = "a modernizar / total" (X/Y)** (2026-07): cada origem (SAS/Local, Transacional, Arquivos/Scripts, BigQuery) mostra `X/Y` — X = inputs ainda **não** modernizados (efetivo ≠ Modernizado/Sanitizado), Y = total da origem no recorte. SAS/Local conta normalmente como input a modernizar (a tentativa de status "Migrar EGP" foi **revertida** — não reintroduzir).

### Vínculo antecessor → sucessor e o status `Desatualizado` (2026-09)

> **Implementado e verde, ainda NÃO deployado** (25/09/2026). Régua completa em
> `docs/superpowers/specs/2026-09-24-egps-atualizados-unificacao-design.md`.

Quando o cliente reenvia um `.egp`, a versão nova entra no corpus como projeto próprio (o
**sucessor**) e a gestão a liga ao EGP antigo (o **antecessor**) por dois campos em
`sas_egp_pipeline`: `egp_vinculo_tipo` (`Atualizado` · `Substituído` · `Unificado`) e
`egp_sucessor`. **`egp_atualizado_key` não foi reaproveitada** — ela aponta para a chave da
aba EGPs Atualizados (a sugestão da chegada, com 10 valores em prod), enquanto o vínculo
aponta para o **projeto do corpus**; são chaves diferentes.

**Tudo é derivado em leitura, nada é gravado** (`backend/vinculos.py`, lógica pura e sem DB,
no padrão de `priorizacao_logic.py`). O antecessor exibe status `Desatualizado` e a **etapa
do sucessor**; o status real dele continua no banco e reaparece inteiro se o vínculo for
desfeito. Duas exceções: quem já é `Despriorizado e Contabilizado` continua despriorizado
(decisão de gestão não é apagada por fato derivado), e `Substituído` não espelha nada.

**A etapa espelhada é recusada pelo servidor**, não só desabilitada na tela — só no front, a
próxima integração escreveria por baixo.

**Quem vê o derivado, quem precisa do real — e por que isso está escrito no código.** A
derivação nasceu num lugar só (`vinculos.anexa_vinculo`, em `/api/egp-readiness`), e as
outras superfícies seguiram lendo `etapa_migracao`/`status_migracao` crus: a aba EGPs e o
Resumo discordavam sobre a etapa do mesmo antecessor, em silêncio. A correção não foi
"derivar em tudo" — as duas respostas são legítimas:

- **derivado** (etapa espelhada + `Desatualizado`) onde a tela mostra **andamento**: funis
  do Resumo (`/api/funis`), drawer do EGP (`/api/egp`), drawer do input
  (`_enrich_egp_contexto`), coluna Etapa da Gestão, coluna Etapa/Status da Priorização.
  O mapa derivado é `_pipe_exibido()` / `vinculos.mapa_exibido()`, sobre a leitura crua
  `_pipe_egp_map()` — mesma regra do `anexa_vinculo`, formato de mapa, cacheado por geração.
- **real** onde se pergunta pelo **estado gravado** de gestão, ou se escreve nele: quem está
  despriorizado (`_egps_fora_backlog`, que recorta dependências app-wide e alimenta a
  sanitização derivada), o **critério 189** dos denominadores (`_ex_deps_contab`, `et_by_pj`
  do funil `+deps`, `_prio_contabiliza`), o `PATCH /api/egp-pipeline`, a DDL e a cópia do
  §3.3.11. Derivar num denominador faria uma ex-dependência sem etapa entrar no total só
  porque ganhou sucessor — a armadilha que a spec §4 manda **anunciar**, não deixar passar.

`Desatualizado` **não** está em `BANDS`: fosse banda, cairia no `stt in BANDS or stt ==
"Migrado"` e passaria a contar como migrado.

A trava é `backend/test_leitura_pipe_decidida.py`: varre o fonte e **falha** se alguma
leitura dessas colunas não declarar, ali do lado, `# pipe-etapa-status: real — <porquê>` ou
`# pipe-etapa-status: derivado — <porquê>`. A janela é por comando, então uma leitura nova
colada numa já decidida também é cobrada. O comportamento está preso em
`backend/test_etapa_espelhada_superficies.py`.

**O vínculo leva o trabalho de gestão junto** (§3.3.11). No **ato** do vínculo — e só nele —
`etapa`, `mes_prioridade`, `jira_id` e `responsavel` são **copiados** do antecessor para o
sucessor (`vinculos.campos_copiados_no_vinculo` + `_copia_trabalho_para_sucessor` em
`main.py`). Não é sincronização: daí em diante os dois divergem livremente, re-salvar a
mesma classificação **não** recopia, e campo que o sucessor já tem nunca é sobrescrito
(vincular → desvincular → vincular não pode atropelar o que já andou lá).

A **etapa** está na lista por causa do funil: sem ela, no instante do vínculo o antecessor
passaria a espelhar a etapa **vazia** de um sucessor recém-chegado ao corpus e cairia para
"sem etapa" — sumindo da coluna do funil `+deps` sem que trabalho nenhum tivesse sido
desfeito. Regressão coberta por `test_funil_deps_nao_perde_egp_de_coluna_ao_vincular`.

**O `status` fica de fora de propósito: classificar nunca muda status sozinho** (§3.5.21).
No `Substituído` o app **sugere** fechar o antecessor como `Despriorizado e Contabilizado`
— um aviso com um botão no detalhe do EGP (`frontend/src/vinculo.ts`,
`sugereFecharAntecessor`) — e o status só é gravado pelo caminho normal de edição, depois
do clique da gestão. O PR #136 gravava esse status automaticamente ao vincular; foi
**deliberadamente rejeitado**, é a invariante de nunca cascatear status.

A cópia também respeita a guarda da etapa espelhada: numa cadeia v1 → v2 → v3, a etapa do
v2 já é espelho do v3, então ela sai da cópia em vez de furar a própria guarda.

**Contagem — duas perguntas, nunca uma.** *Conta?* é a **LISTA CONGELADA** de 29/09/2026
(`backend/linha_base_congelada_2026-09-29.csv`, 193 projetos): o total deixou de ser
calculado, e **quem está fora dela não conta** — inclusive o que o grafo classificaria como
dependência. *É `extra`?* é outra coisa: o EGP que tem **vínculo de atualização com outro**
— os **sucessores** (de qualquer tipo de vínculo, **inclusive o de um `Substituído`**) e as
**cascas** (§3.6) — e está fora da lista. O extra entra no recorte `indi_deps` (é como os
inputs dele passam a contar) e é listado com o 4º valor do filtro Tipo, mas fica **fora do
total**, num **contador próprio exibido ao lado** (`extra_count` na aba EGPs, `extras` no
Resumo). A linha de base não sobe porque o BV mandou versão nova.

**Não unir as duas perguntas** (correção de 29/09/2026, depois de a régua unificada ser
vista em uso): "extra = tudo que não está na lista" rotulava de `extra · novo` toda
**ex-dependência** fora da contagem — 16 em prod, 19 no dev, nenhuma recém-chegada —, e
fazia a TELA (que lista as ex) discordar do CONTADOR (que conta sobre o frontier, onde a ex
não está): 37 × 18. Hoje **ex-dependência nunca é extra**, o motivo `novo` não existe mais,
e cada linha do readiness carrega `na_linha_base` — é ele, e não a etapa viva, que o front
lê em `contaNoTotalEgp`. Travado por `test_extra_enumeracao.py`.

**Categoria e espelhamento são eixos independentes.** Espelhar (etapa espelhada, status
`Desatualizado`, etapa read-only) continua decidido pelo **tipo do vínculo**
(`sucessores_espelhados()`); ser `extra` vale para todo sucessor e toda casca
(`extras()` = (sucessores ∪ cascas) − linha de base − ex-dependências). Não reunir os dois
num conjunto só — era exatamente isso que fazia o sucessor de um `Substituído` cair no
denominador.

O **recorte da aba EGPs** tem 5 valores: `só Indicium` · `Indicium + dependências` (os 193,
**sem** extra) · `todos` · `Indicium + dependências + extras` · `só os extras`. Os dois
últimos são vistas da mesma consulta `indi_deps`, filtradas na tela (`vinculo.recorteApi` /
`passaNoRecorte`) — duas consultas para o mesmo recorte é como a tabela e o contador
voltariam a discordar. O botão "+N extra" do card e o seletor mexem no mesmo estado.

### Cards de input da aba EGPs: contados em tela (2026-10-05)

Os três cards de input da aba EGPs (**Inputs distintos**, **A ingerir**, **Sem fonte**)
são contados **no cliente, sobre os EGPs que a tabela está mostrando** — recorte, filtros
de dimensão e chips inclusive. O card de **EGPs** é a exceção e segue congelado: ele é o
tamanho da linha de base, não uma conta sobre o recorte.

Antes vinham de `_readiness_inputs_header`, uma agregação SQL própria, e isso produzia
dois defeitos ao mesmo tempo: nenhum filtro da aba mexia neles, e o universo não era o da
Visão geral — o header **tira o Sanitizado** do universo, então o card dizia 711 inputs
onde o Resumo dizia 1.303 (prod, 05/10/2026). O header continua no payload de
`/api/egp-readiness` (não foi removido), mas a tela não o usa mais.

A fonte é `GET /api/egp-input-units?scope=`, que devolve o universo do recorte
(`_universo_contagem(_dataset_escopo(...))` — **as mesmas linhas** que `/api/landing` e a
aba Inputs contam) mais, por EGP, os índices das unidades com vínculo não quebrado. O
cliente faz a união dos índices dos EGPs em tela e conta o conjunto; a dedup por unidade é
o que impede o card de virar `Σ n_inputs` das linhas. Com `FAMILIAS_SAFRA=1` a unidade é a
família, então dois EGPs que leem safras diferentes da mesma tabela contam **uma**.

O **estado** de cada unidade é o do recorte inteiro, nunca reagregado por filtro: família
de safras agrega só as safras em vista (ver o bloco dos itens 4/7 em `landing`), e
reagregar por filtro faria a mesma família responder coisas diferentes conforme o chip
ligado. O filtro escolhe o que contar, nunca o que a unidade é.

Medido em prod em 05/10/2026 (`backend/test_egp_input_units.py` segura a propriedade; os
números abaixo são o retrato do dia):

| Recorte da aba | Inputs / a ingerir | Visão geral |
|---|---|---|
| `só Indicium` | 1.166 / 311 | escopo: 1.161 / 311 |
| `Indicium + dependências` (os 193) | 1.222 / 327 | escopo + deps: 1.242 / 336 |
| `Indicium + dependências + extras` | 1.296 / 370 | **Total: 1.303 / 377** |
| `só os extras` | 381 / 151 | grupo próprio: 61 / 41 |

**O recorte que reproduz o Total da Visão geral é `+ extras` com o chip "fora da linha de
base" LIGADO: 1.303 / 377, exatos.** Desligado (o padrão) faltam 7 unidades, todas
pendentes, que só 19 linhas ocultas leem — EGPs fora da lista congelada, como o
`PERFORMANCE_CL_202608_GCP` e o `PROJECT_ATIVA_TABLEAU_NEW_RPA`, mais as ex-dependências
sem etapa real. A Visão geral conta os inputs deles (estão no frontier, logo no dataset);
a aba os esconde por padrão para a LISTA bater com o card de EGPs. São duas decisões
antigas e independentes — o que mudou aqui é que a diferença passou a ser reproduzível em
tela, com um chip, em vez de ser um número que não fechava.

As outras duas diferenças são da mesma família. `só Indicium` tem 5 unidades a mais porque
a aba LISTA os extras nesse recorte (`passaNoRecorte` só os filtra em `indi_deps`) e o
Resumo os separa em grupo próprio; são 5 unidades resolvidas, por isso o "a ingerir" bate
exato. E `só os extras` (381) é maior que o grupo "extras" do Resumo (61) porque o grupo é
só o que **nenhum** EGP contável lê, enquanto o recorte mostra tudo que os extras leem —
perguntas diferentes, ambas corretas.

A contagem vale em **todos** os pontos que contam EGP — coorte e denominador do funil
`+deps`, `n_egps` do funil de ingestão por mês, `/api/scope-egps`,
`dep_count`/`base_count`/`total` da aba EGPs, itens 1/2 e `total_egps` da landing, `deps` da
tabela por área —, todos via `_contaveis()` / `linha_base`. O mapa de vínculos é **fonte
única cacheada**
(`_vinculos_por_antecessor`) e o das cascas também (`_cascas()`, lido de
`sas_escopo.origem = 'casca'`): duas queries para o mesmo fato fariam recorte e card
discordarem entre si.

### O denominador é a lista congelada em TODA superfície (2026-10-08)

O funil/tabela por área (DOR1) mostrava **192** onde a Visão geral e o card da aba EGPs,
na mesma tela, mostravam **193**. Faltava o `Fechamento_Contabil_RPDD_3040` — ex-dependência
com etapa FANTASMA (`Pré-conversão`) presente na foto.

Mesma causa da correção do dia anterior, em outra superfície: o critério "189"
(`_ex_deps_contab`, só ex com etapa REAL) foi ABSORVIDO pela foto em 29/09/2026, quando o
`total_egps` deixou de ser calculado e passou a ser o tamanho da lista — e sobreviveu em
quem ninguém reviu. O comentário no código ainda dizia "mesmo critério do total_egps", o
que tinha deixado de ser verdade.

A régua agora mora num lugar só, **`_ex_deps_na_foto(frontier, base)`**, usada pela tabela
por área e pelo universo da Gestão. `p in linha_base`, e não "classe `ex_dependencia` na
foto": o `Performance_Saldo_COLORE_…_V5` entrou na lista como `dependencia` e virou ex
depois. A pergunta é "está na lista", nunca "foi classificado ex na lista".

A **Priorização** foi alinhada junto (`_prio_contabiliza` ganhou `linha_base`): ela dava 193
por coincidência — o EGP faltante não está no plano — mas a régua era a mesma defasada. O
critério 189 segue como *fallback* de quem chamar sem a lista.

Onde ficam as superfícies, medido em prod em 08/10/2026 (todas em 193):

| Superfície | Antes | Depois |
|---|---|---|
| Visão geral (`total_egps`) | 193 | 193 |
| Aba EGPs (card) | 193 | 193 |
| Priorização | 193 | 193 |
| **Funil por área (DOR1)** | **192** | **193** |

`backend/test_denominador_pela_foto.py` trava a régua E o uso dela: além dos casos de
lógica, há um guard de FONTE que falha se `resumo` ou `_gestao_rows_uncached` voltarem a
chamar `_ex_deps_contab`. Sem ele, reverter a linha de chamada passava por todos os testes
— foi o que aconteceu na primeira versão deste arquivo.

### A Gestão retém ex-dependência pela lista congelada (2026-10-07)

A Acompanhamento/Kanban mostrava **31** EGPs `Desatualizado` onde a aba EGPs mostrava **33**.
Duas réguas para a mesma pergunta ("esta ex-dependência conta?"):

| Superfície | Universo | Régua |
|---|---|---|
| Aba EGPs | recorte `indi_deps` | `contaNoTotalEgp` → **lista congelada** (`na_linha_base`) |
| Acompanhamento | `/api/gestao/rows` | `_ex_deps_contab` → **critério "189"** (só ex com etapa REAL) |

Os dois que faltavam — `Fechamento_Contabil_RPDD_3040` e
`Performance_Saldo_COLORE_…_Lite_V5` — são ex-dependências com etapa **fantasma**
(`Pré-conversão`) e status `Desatualizado`, então o critério 189 as descarta e a foto não.
O próprio comentário de `contaNoTotalEgp` já registrava que a lista **absorveu** o critério
189 em 29/09 (§3.1.2); ele tinha sobrado só neste ponto.

Medido em prod: ex-dependências vivas 33, das quais **14** passam no critério 189 e **16**
estão na foto — a diferença são exatamente os dois, e nada vai no sentido contrário (a foto
é superconjunto estrito aqui).

A régua é `_ex_deps(...)[0] & set(_linha_base())`, **não** "classe `ex_dependencia` na
foto": o `Performance_Saldo_COLORE_…_V5` entrou na lista como `dependencia` e só virou ex
depois. A pergunta é "está na lista", nunca "foi classificado ex na lista".

Impacto: universo da Gestão **224 → 226**, Desatualizado da Acompanhamento **31 → 33**,
fechando com a aba EGPs. As linhas de **input** da Gestão seguem o frontier vivo (decisão 3
da spec, fila de entrega intacta) — 740, inalteradas.

### `tipo` é propriedade do EGP, não do recorte pedido (2026-10-07)

O recorte `base` forçava `dep_nivel = 0` em toda linha ("linhas exatamente como antes"), e
o `tipo` é derivado dele — então **o corpus inteiro saía como `escopo`**: 1.250 linhas em
prod, 1.007 delas fora do escopo Indicium. Como o drawer do EGP (`EgpDetailPanel`) pede
`egpReadiness("base")` **fixo**, ele exibia o badge "escopo" para qualquer EGP que se
abrisse, inclusive para uma ex-dependência. A coluna Tipo do recorte "escopo: todos" tinha,
pelo mesmo motivo, um valor só.

Agora a classificação é sempre contra o recorte **Indicium**, em qualquer `scope`, e os
quatro valores batem entre `base` e `indi_deps`:

| | `base` (1.250 linhas) | `indi_deps` (243) |
|---|---|---|
| escopo | 168 | 168 |
| dependência | 43 | 43 |
| ex-dependência | 32 | 32 |
| **fora do recorte** | **1.007** | — (não entram nesse recorte) |

`fora_do_recorte` é o 4º valor: está no corpus e fora de tudo — não é escopo, não é
dependência de ninguém do escopo, e nunca foi (logo não é ex-dependência). Chamá-lo de
escopo era a mentira; deixá-lo sem rótulo seria a seguinte.

**O que NÃO mudou, de propósito:** `frontier`/`base` locais do recorte `base` seguem sendo
"tudo", porque são eles que alimentam o header de inputs daquele recorte. A mudança é só
rótulo por linha — `base_count`, `dep_count`, `ex_count`, `total` e `inputs_distintos` ficam
idênticos. O recorte `indi` também não muda: ali toda linha é escopo por construção.

### O sucessor de uma ex-dependência continua no recorte (2026-10-07)

A ex-dependência é **retida** com badge para "o esforço não sumir" (`_ex_deps`). A versão
nova dela não era. A cadeia de sucessores (`_frontier_egps`) era semeada só com o fecho
**podado**, então no instante em que a via do antecessor entrava no lake o antecessor virava
ex-dependência — certo, fica retido — e o sucessor dele sumia de **todas** as telas.

Medido em prod: `PAGOSCBR.PAGOS_CYBER_202603` virou `Modernizado` em 06/10 19:35 (era a
única via que puxava o `Performance_Saldo_COLORE_…_Lite_V5`, por 3 consumidores). O
`…__ATU20260901`, com 21 inputs no recorte, saiu junto, e o contador de extras caiu de **33
para 32** sem que EGP algum tivesse sido resolvido. Só aparecia em "escopo: todos".

A correção: `_retidos(base)` — fecho transitivo sobre o grafo **bruto**, o mesmo de
`_ex_deps` — entra na semente da cadeia. A ex-dependência **não** entra no frontier (quem a
retém segue sendo `_ex_deps`); ela só serve de ponte para alcançar a versão nova.

**A armadilha, que custou uma medição:** `cadeia_de_sucessores` devolve o fecho **menos a
semente**, porque o chamador normal reúne a semente de volta no return. Aqui não — `_ret`
não entra no frontier. Resultado da 1ª versão: 5 sucessores que também estavam no fecho
bruto foram subtraídos junto e os extras caíram para **28**. Eles voltam por
`suc |= _ret & vinculos.sucessores(_vinc)`: quem está no fecho bruto a partir da base tem
ticket próprio. Travado em `backend/test_sucessor_de_ex_dependencia.py`.

Impacto medido: +1 EGP no frontier, extras 32 → 33, +3 unidades de input (todas no grupo
dos extras — a partição dos três grupos continua fechando). `total_egps` **não muda**: a
linha de base é congelada e o extra tem contador próprio.

### Antecessor espelhado conta como migrado pelo fim da cadeia (2026-10-05)

`Desatualizado` é um rótulo de RELAÇÃO ("alguém tomou meu lugar"), mas ocupa o mesmo campo
que os status terminais. Quem contava migrados por status perdia o antecessor cujo sucessor
já migrou: ele aparecia DENTRO da coluna "Migrado" do gráfico (a etapa já é espelhada,
§3.2.7) e FORA do "X/Y" logo acima dela. Medido em prod: **95/193 onde a coluna dizia 96**,
por causa do `Oportunidade Protesto - Piloto de Ajuizamento_GCP`, cujo sucessor
`Oportunidade Protesto_20260703` está Migrado.

A régua: o antecessor que ESPELHA herda, para efeito de contagem, o status do **fim da
cadeia** de espelhamento — o mesmo EGP de onde ele já tira a etapa. Mora em
`vinculos.mapa_contagem`, irmã de `mapa_exibido`, e é usada pelos DOIS lugares que somam
terminais: `proj_funnel` (os três funis de migração) e as linhas do readiness, via o campo
`status_contagem` que `baldeEgp` lê na tabela por sub-área do Resumo. Uma função só porque
a última vez que esta régua teve duas cópias a aba e o Resumo discordaram do mesmo EGP.

Consequências deliberadas: a BARRA continua mostrando o segmento `Desatualizado` (é o que o
antecessor é); `Substituído` não herda nada (trajetórias independentes — herdar contaria o
mesmo trabalho duas vezes); `Despriorizado e Contabilizado` do próprio antecessor continua
vencendo, como em `status_exibido`; e sucessor fora do recorte carregado vira `None`, nunca
um terminal chutado. `_migrados_mes` (KPI de velocidade do mês) **não** entra nessa regra:
ele conta EVENTOS de transição na auditoria, não estado.

### Os funis de ingestão não contam o inventário exclusivo dos extras (2026-10-05)

Os dois são **pares de funis de migração que já contam sem extra**: `migracao` conta os 168
da classe base, `migracao_deps` os 193 da linha de base. Enquanto os de ingestão somavam o
universo inteiro, o mesmo input aparecia duas vezes no mesmo Resumo — neles e no funil de
ingestão dos extras logo abaixo.

Agora os três usam a mesma régua, que `/api/funil-ingestao-mes`, a tabela de origem e o
item 3 da landing (`_ri_sem_ex`) já usavam: fora o que SÓ os extras leem (`so_de_extra`). O
que o extra lê **em comum** com a linha de base fica na dela; o **exclusivo** fica na dos
extras.

Medido em prod (05/10/2026):

| Funil | Universo antes | Depois | Confere com |
|---|---|---|---|
| `ingestao` (só Indicium) | 1.166 | **1.161** | item 3 da Visão geral |
| `ingestao_deps` | 1.296 | **1.222** | escopo + deps (1.161 + 61) |
| `ingestao_extras` | 74 | 74 | grupo próprio |

Os três **particionam** o universo (1.222 + 74 = 1.296 = Total de Inputs), que é o que
permite ler os três na mesma tela. Consequência aceita, a mesma do funil por mês: nenhum
deles bate sozinho com o card "Total de Inputs", que soma os três baldes.

**O 3º funil do Resumo — os extras** (§3.1.3). Ao lado de "escopo" e "escopo +
dependências", `/api/funis` devolve `migracao_extras`: a **mesma** `proj_funnel`, as mesmas
9 etapas, só o universo muda. Ele é um **recorte**, não outra entidade — os extras já são
EGPs do corpus. O denominador é o **próprio conjunto** (`len(extras)`), nunca o total base,
e o universo é `_extras_no_recorte()`, o **mesmo** conjunto do contador "(+N extra)" da
Visão geral: card e funil estão na mesma tela e duas definições do mesmo recorte foi o bug
que o off-by-one do Resumo já custou em julho/2026. Consequências deliberadas: extra **sem
etapa** conta no denominador e fica fora do coorte (o estado honesto — trabalho que chegou
e não começou); a régua das ex-dependências (`ex_f`/`ex_denom`, critério 189) **não** vale
aqui, é do `+deps`; e os dois funis antigos **não mudam de régua** — nada é somado neles
porque um extra chegou (travado em `test_funil_extras.py`, que compara os dois dicionários
inteiros antes × depois da injeção).

**O mês do input vem só de consumidor vivo** (09/10/2026). O funil de ingestão por mês dava
a cada input o menor mês entre os EGPs do **plano** que o leem — e o plano é podado pela
linha de base, não pelo frontier. Uma ex-dependência que saiu do recorte continua com mês no
plano, e puxava para M1 inputs que nenhum EGP vivo de M1 lê. A aba Inputs monta o mês a
partir de `/api/inputs-egps`, só com pares do frontier, e por isso os dois discordavam:
**22 × 20** em M1/A Receber. Os 2 de diferença (`BU.BASEUNICARODAS` e
`BU.BASEUNICARODAS_20`) eram lidos pelo `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1`
(ex-dependência, M1 no plano, fora do frontier) e caem em M4 e M5 pelos consumidores vivos.
Decisão da gestão: vale o 1º mês entre os consumidores vivos. `funil_ingestao_mes` passa a
filtrar o mapa do plano pelo frontier. Os inputs só mudam de mês (total segue 624): M1 189→184,
M2 159→140, M3 79→81, M4 146→166, M5 51→53. O funil **não** usa o mês dos extras: o
compartilhado entre linha de base e extra pertence ao funil da linha de base, e esse funil não
muda de régua porque um extra chegou — o extra tem funil próprio.

**Na visão da linha de base, a aba Inputs não usa o mês dos extras** (09/10/2026). Depois do
fix acima sobrou 1 diferença em M1, em Modernizado: 150 no funil × 155 na aba. Os 5 inputs
eram lidos por EGPs do plano em M2/M3 e também pelo extra
`Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HU…`, que herda M1 do antecessor. O
`useMesPlan` passou a colocar o mês dos extras no mapa de todas as telas (parágrafo abaixo), e
no recorte "Indicium + dependências" (`semExtras`) isso puxava o compartilhado para o mês do
antecessor do extra. O hook passa a expor também `mesOfPlano`, o mapa sem os extras, e a aba
Inputs o usa nesse recorte; nos recortes que mostram os extras, o mês deles continua valendo.
Medido: a linha M1 inteira bate com o funil nas 7 etapas. A Gestão (Acompanhamento, Gestão,
Kanban) **não** muda: o universo dela inclui os extras (226 EGPs = 193 + 33, e 65 dos 66
inputs exclusivos de extra), então ali o mês do extra é o certo.

**O mês do extra chega ao front** (08/10/2026). `_mes_dos_extras()` existe desde 30/09 e dá
a 27 dos 33 extras o mês do **Antecessor**, mas só os dois funis de extras o consumiam. O
mapa que as telas usam (`useMesPlan`) é montado a partir de `meses[].egps[]` do
`/api/priorizacao` — os 193 do plano —, então **todo extra saía com mês "—"** e era
derrubado por qualquer filtro de mês nas 11 telas que usam o hook. O sintoma reportado foi
na aba Inputs: ligar "+ extras" e marcar um mês devolvia o número de Indicium + dependências,
porque os **66** inputs `so_de_extra` não tinham mês nenhum. `/api/priorizacao` passa a
devolver `extras: [{projeto, mes}]`, em campo **separado** de `meses[].egps[]` — quem conta
o plano (`FunilMesTable`, `_prio_live_input_stats`) continua contando 193; extra ganha mês,
não vaga. Medido em prod: `mesOf` 193 → 220 EGPs, e inputs `so_de_extra` sem mês **66 → 6**
(5 são o placeholder `casco::` das cascas, 1 é do `Cobranças__ROI`, novo que a gestão ainda
não datou). Nenhuma opção nova aparece no filtro: o mês do extra é sempre o mês de um EGP
que já está no plano. Os dois funis de ingestão por mês **não** mudam — a separação deles é
sobre dupla contagem, não sobre mês.

**O cabeçalho das abas de tabela não recolhe mais sozinho** (09/10/2026). O
`useHeaderCollapse` tem duas camadas: a preferência persistente do botão ▴/▾ e um
recolhimento automático ao rolar a tabela. A segunda foi desligada na aba EGPs em 08/10 e
na aba Inputs em 09/10, pelo mesmo motivo: com poucas linhas o corpo da tabela mal rola, o
gatilho dispara com qualquer tremida do trackpad e as métricas somem debaixo do cursor. Os
dois usos do hook passam `auto: false`, então hoje a camada automática não roda em lugar
nenhum — o parâmetro fica como registro da decisão, e o `onBodyScroll` segue ligado mas
vira no-op. O tooltip do botão deixou de prometer "rolar a tabela também recolhe".

**A resposta do PATCH tem de trazer as derivações de leitura** (09/10/2026).
`sanitizacao.aplica_em_linhas` sobrescreve `status` por `Sanitizado` na LEITURA (§3.4.18) —
o banco guarda o real em `status_real`, a tela mostra o derivado. O `PATCH /api/inputs`
devolvia `dict(old)`, a linha CRUA, e o `onSuccess` da aba Inputs faz **merge** da resposta
na linha em cache: trocar a etapa de um input com sanitização derivada fazia o `Sanitizado`
da tela virar o status cru na hora de salvar (`A Receber/Sanitizado` → `Modernizado/A
Iniciar`) e voltar a `Sanitizado` no refetch seguinte. O banco nunca mudou — só a resposta
vinha sem o overlay, e o `onSuccess` já se protegia de coluna **ausente** (`paths_fisicos`),
não de coluna **presente com o valor cru**. Agora `patch_input` aplica o overlay no
`result`, e `_patch_familia` o aplica nas safras **antes** de reagregar, na mesma ordem do
`_dataset_escopo` — senão a família volta com `status`/`estado_misto`/`n_safras_pendentes`
calculados sobre o status cru. Medido em prod: 60 inputs com sanitização derivada e 23
linhas exibidas como "A Receber + Sanitizado", das quais 7 safras da família
`TALITA.NOTIFICACAO_SOLAR` com status cru `A Iniciar` e motivo `so_despriorizados`.

**Dependência nova vira extra** (13/10/2026). Decisão da gestão: "os 193 estão fechados;
dependência que vier vira extra, e os inputs dela entram em extra". O `landing()` já dizia em
comentário que "uma dependência que apareceu depois do congelamento traz os inputs dela e
conta entre os extras", mas `vinculos.extras()` seguia a enumeração de 29/09 (sucessor,
casca, novo) e a dependência nova ficava **fora de tudo como EGP** enquanto os inputs
exclusivos dela entravam no card de **dependências**: 11 dependências na tela e os inputs de
12. Revelado pelo publish de 13/10: o `20. Performance Safrada Fase Ativa - Agente IA`, sem
vínculo, foi puxado pelo grafo e levou +10 inputs / +9 a ingerir para aquele card. Agora
`main._deps_novas()` apura a dependência nova (frontier − base viva − linha de base − quem já
entra por regra: sucessor, casca, novo) e ela é a 4ª perna nomeada da enumeração, com
`extra_motivo='dependencia'` e o papel "dependência nova" na coluna Tipo. Ex-dependência
continua vetada (não está no frontier). Medido em prod: dependências 44/24 → **34/15** (os
valores de antes do publish), extras 62/32 → 72/41, EGPs extra 32 → 33; totais inalterados
(1.258 / 291) — só muda o balde.

**As tabelas DOR1 do Resumo batem com os cards** (14/10/2026). "Funil por área" e "Inputs
por origem" divergiam dos cards da Visão geral por quatro causas independentes, medidas em
prod: (1) não modernizados do escopo **194 × 205** do card — a família de safras agrega só
as safras em vista, e o dataset do escopo não via a safra pendente que só dependência ou
extra lê (11 famílias); a tabela passa a tirar o modernizado/não do recorte ampliado, como
o `landing()` já fazia, mantendo bucket e área do escopo; (2) EGPs +deps **192 × 193** — a
tabela contava dependências pelo grafo vivo e perdia a dependência da foto que saiu do
recorte (`Fechamento_Contabil_RPDD_3040`, unificado num sucessor; o mesmo 192 de 08/10, que
o `_ex_deps_na_foto` só tinha resolvido para ex-dependência); agora dependências e ex vêm da
classe gravada na Linha de base; (3) linha **"(sem área)" com 0 EGPs e 116 inputs** — a área
principal é calculada sobre escopo ∪ dependências e não enxerga extra, então o input que só
extra lê ficava sem área; ele passa a uma linha "Extras (à parte)", com os EGPs fora do total
(o "(+N extra)" do card) e os inputs dentro (o Total de Inputs do card os conta). Na
mesma linha caíam 13 famílias lidas pela base: a família herdava a área pela MODA das
safras, e as safras que só extra lê ("(sem área)") eram maioria — agora a família
herda a moda das safras que têm área (`_area_da_familia`);
(4) total +deps **1.351 × 1.356** — o card conta os placeholders `casco::` dos unificados, a
tabela não (não são origem de ingestão); continua assim, e a tabela diz quantos são.

**Casca e o funil por área.** A casca ganha 1 linha em `sas_escopo` (§3.6.24) só para o
`recompute_escopo()` não apagar o `escopo_indi` dela. Essa linha serve à **visibilidade,
não à contagem**: o `INSERT INTO sas_funil_area` filtra `coalesce(origem,'') <> 'casca'`
(`SQL_ESC_NAO_EXTRA`, espelhado no bloco gêmeo do `publish_to_databricks.py`). Sem essa
guarda o funil da Cobrança subiria **+5** sem que nada tivesse sido migrado. A linha em
`sas_escopo` é **persistente**: reverter o código não a remove.

**Como verificar que os funis não se mexeram.** Comparar contra um snapshot gravado antes
não serve: prod deriva sozinha (medido: +10 inputs em ~20 min) e, sem nenhum vínculo criado,
o conjunto de espelhados é vazio — qualquer ponto de contagem esquecido passaria batido. O
verificador captura base e injeção **no mesmo processo** e injeta vínculos falsos na fonte
única; só contagem de EGP entra no conjunto estrito (funis de ingestão acompanham os inputs
por definição). Medido: recorte 180 → 185, lista da aba 209 → 214, **18 contagens de EGP
idênticas**.

**No Kanban**, `Desatualizado` vira coluna pela mesma precedência de status que
`separarDespriorizados` já usava — e **despriorizado vence**, porque só cabe um status por
EGP. As funções de coluna saíram de `GestaoKanban.tsx` para `src/kanbanColunas.ts` (lógica
pura, testável: `node --experimental-strip-types` não processa JSX), com re-export para os
importadores seguirem inalterados.

**Versão recebida que ainda não entrou no corpus fica visível** (§5, "O buraco que A abre").
Entre a chegada do arquivo (etapa 0) e a entrada no corpus (etapa 2) o sucessor não existe
em superfície nenhuma: já foi comparado e publicado na aba, mas ainda não é projeto. A
janela deveria durar o tempo de uma rodada do pipeline; se ninguém rodar, dura dias. A aba
EGPs ganha um chip **"📥 Aguardando corpus: N"** (`GET /api/egps-atualizados/aguardando-corpus`,
em `backend/egps_atualizados.py`) que abre a lista de **quais** são. É a guarda que repõe o
que a aba dedicada fazia — e que a aposentadoria (2026-09) tornou obrigatória.

O mesmo endpoint carrega as **pendências**: `pareamento não resolvido` e `falha na extração`.
A taxonomia "Situação" da aba morreu com ela e ficou o **Tipo de vínculo**, mas estes dois
valores não são tipo — dizem que a comparação **não pôde ser feita**. Descartá-los junto
faria um arquivo cuja extração falhou parecer normal (o bug que "Falha na extração" já
causou uma vez: sem branch própria, caía no default e aparecia como "Atualizado" verde).
Quem ainda aguarda leva o selo na própria linha; quem **já entrou no corpus** vem em
`pendencias` — entrar no corpus resolve o "aguardando", não a pendência. `n_pendencias`
conta cada versão uma vez só.

O contador é **derivado**, como o resto da feature: diferença entre as versões de
`sas_egp_atualizados` e os projetos de `sas_lineage_nodes`, calculada na hora. Nada é
gravado — por isso ele **zera sozinho** quando o pipeline roda e a versão **descartada**
(linha removida da aba, §2) some sem limpeza manual. Três detalhes sustentam o critério
*nenhuma versão some de vista sem ter entrado no corpus ou sido descartada*
(`backend/test_recebidas_aguardando_corpus.py`):

- o casamento exige o sufixo `__ATU<data>` da régua de nomeação (§2, etapa 2). Casar pelo
  `Área__nome` puro daria "já entrou" no minuto zero para as **12 versões com nome idêntico
  ao antecessor** — o antecessor já é projeto do corpus;
- a **data** entra no casamento (normalizada a dígitos, porque a etapa 2 ainda não está
  implementada e a grafia do sufixo não está decidida): por prefixo, a entrada da v2
  cobriria a v3 recém-chegada;
- o grão é a **versão**, não a `egp_key`. A lista da aba mostra só a mais recente
  (`rn = 1`); herdar esse recorte faria a v2 que nunca entrou sumir no dia em que a v3
  chegasse — um terceiro desfecho, invisível.

Versão que entrar no corpus com outra grafia continua contada (falso positivo, visível e
corrigível) em vez de sumir em silêncio.

### Ex-dependência sem etapa real: oculta por padrão na aba EGPs (2026-09)

A lista da aba EGPs mostrava **209** linhas enquanto o card dizia **192** (recorte
`indi_deps`, medido 25/09). Não era bug: `total`/`ex_count` contam só as ex-dependências
com **etapa real** (`contaNoTotalEgp` no front, `_ex_deps_contab` no back — critério de
2026-08-10), e a lista mostrava todas. O código já avisava: *"rows.length pode exceder
total"*.

Agora as ex-dependências sem etapa real ficam **ocultas por padrão** e voltam pelo chip
`👁 Ex-dep. sem etapa` — com o chip desligado a lista bate com o card (192 = 192). O
filtro entra no início de `baseSemSubarea`, então contagens de chip, ordenação e CSV ficam
coerentes com o que está na tela; a contagem do chip é sobre `rows` (recorte inteiro),
senão zeraria justamente quando as linhas estão ocultas, e seria impossível reexibi-las.

**Não é "sumir".** A retenção de ex-dependência existe para o esforço não desaparecer: das
17 em prod, **2 têm Pré-conversão concluída, com responsável e JIRA**
(`CRIAR_MARCACAO_SEGMENTACAO_reap_1`, `Valida_carga_v1_cp`). Elas não contam porque
**`Pré-conversão` é etapa fantasma**, não porque ninguém trabalhou nelas — por isso o
default é ocultar, não remover.

### Escopo "Indicium + Dependências" (`indi_deps`) + indicador de EGPs (2026-06)

3º botão de escopo no Monitor. Inputs de **todos os EGPs do fecho** = base Indicium [∩ área] **∪ dependências TRANSITIVAS** (mesmo fecho do escopo "+ dependências" da aba EGPs; helper `_frontier_egps()`). Validado à época: Cobrança = 168 base → **201** com deps (todos os níveis); 1-hop daria 190.

- **A ÁREA define a BASE (server-side):** em `indi_deps` a área entra na chave do dataset e **recarrega** (deps entram **mesmo de outras áreas** — ex.: deps de Cobrança que são Riscos). Em `indi`/`base` a área é filtro **client-side**. Por isso o filtro de área client-side é **pulado** quando `scope==indi_deps`.
- **Indicador de EGPs** (card destacado, à esquerda dos big numbers): `/api/scope-egps` → `n_egps`/`n_base`/`n_deps` do recorte, pra correlacionar "X inputs em Y EGPs". Área-aware nos 3 escopos.

### Funis do Resumo: 2ª visão "(+ dependências)" (2026-06)

A aba **Resumo** mostra os funis de migração/ingestão em **duas visões**: escopo Indicium (atual, intacta) e, abaixo, **"Funis de migração (+ dependências)"** sobre o **frontier** = escopo Indicium **∪ dependências TRANSITIVAS** (mesmo fecho `_frontier_egps()` do Monitor/EGPs), **sem dupla contagem**. `/api/funis` devolve as 4 chaves num **único request** (`migracao`/`ingestao` + `migracao_deps`/`ingestao_deps`); o fecho é calculado **uma vez**. `FunnelChart` é reutilizado sem alteração.

- **Migração (+deps):** coorte = EGPs do frontier com etapa em `sas_egp_pipeline`; denominador = `len(frontier)` (a visão de cima usa `sas_escopo`). Como deps raramente têm etapa, o efeito típico é **denominador maior e % menor** (quanto do universo ampliado já migrou). `proj_funnel(..., universe, total)` parametriza o recorte; `universe=None` = comportamento atual.
- **Ingestão (+deps):** status efetivo dos **inputs distintos de todos os EGPs do frontier** (`SELECT DISTINCT chave_canonica FROM sas_egp_inputs WHERE projeto IN (<frontier>)`) — `sas_inputs_monitor` é 1 linha/input → **sem dupla contagem**. Mesma base dos itens 6/7 da landing (escopo + deps disjuntos). `ingest_funnel(rows)` é compartilhado pelas duas visões.
- **Degrada com segurança:** grafo não publicado → frontier vazio → a visão +deps espelha a de escopo.

### dep. ausente / "sem fonte mapeada" (aba EGPs) (2026-06)

Card "Sem fonte (SAS/Local)" + badge ⚠ por EGP na aba EGPs: conta inputs `SAS/Local (externo)` **ainda pendentes** (`origem externo AND NOT _modern` → nem modernizado nem sanitizado). Resolvido (modernizado/sanitizado) **não** conta. Distinto de `#deps` (arestas EGP→EGP **conhecidas**) — um EGP pode ter `#deps=0` e ainda ter dep. ausente (lê tabela SAS que ninguém no corpus produz).

### Área "Cobrança" canonizada (2026-06)

`AREA_CANON = {"Cobranças": "Cobrança", "Cobrança Varejo": "Cobrança"}` em `publish_to_databricks.py` (`canon_area()` em todos os pontos de leitura de área) + patch único nas tabelas de prod. **Não reintroduzir** as variantes. Bônus: o "inputs não modernizados" do funil casa por **nome de área** entre funil (DOR1) e resumo (business) — só fecha com o nome unificado.

### Gestão de EGPs/Inputs (aba Gestão, topo) (2026-07)

Tela de gestão de migração no topo da aba Gestão: **um componente parametrizado** (`GestaoMigracao.tsx`, switch EGPs/Inputs — sem duplicação), com **3 KPIs** (com responsáveis · Convertidos, só EGP · Migrados/Modernizados), filtros (nome + EGP consumidor + **"só com responsável", LIGADO por padrão** — senão a lista vira o corpus inteiro; desligue para ver tudo), tabela ordenável (datas **editáveis via pop-up de confirmação** — rótulos por variante: Início/Fim **Migração** + **Fim Conversão** no EGP; Início/Fim **Ingestão** no Input —, QTD dias úteis calculada, último status em 1 linha), **sidepanel** de status/comentários (`GestaoStatusPanel.tsx`, modal com dropdown do grupo bv_users) e bar charts **VERTICAIS**: **atribuídos por colaborador** (altura = total atribuído independente de status — balanceamento do time; segmento verde = concluídos), **EGPs convertidos por mês** (Fim Conversão, só EGP) e migrações/ingestões por mês (Fim). A coluna "Último status" mostra o **texto cru** do status mais recente (truncado em 1 linha) — **sem resumo IA, por decisão do usuário**.

- **Dados REAIS (2026-07):** `gestaoApi = deltaGestaoApi` → endpoints `GET /api/gestao/rows` (egp: nós escopo ⋈ `sas_egp_pipeline`; input: `sas_inputs_monitor` sem sanitizados + consumidores), `GET/POST /api/gestao/status` e `PATCH /api/gestao/datas` (auditado, funil `gestao`). **2 tabelas novas**, criadas on-demand e **nunca dropadas, fora do publish**: `sas_gestao_status` (histórico de comentários; `autor` do dropdown + `criado_por = current_user()`) e `sas_gestao_datas` (datas por `entity`+`entity_id` — evita ALTER/MERGE nas tabelas existentes). `getUsers` = `/api/analistas`. O `mockGestaoApi` fica no arquivo p/ dev sem warehouse (mesma interface). Tabela renderiza no máx. 800 linhas (aviso p/ refinar filtros).
- **Dias úteis**: [`frontend/src/diasUteis.ts`](frontend/src/diasUteis.ts) — exclui fins de semana + feriados BR (lista 2025–2027 **configurável**); congela no Fim Migração quando preenchido; timezone America/Sao_Paulo.
- **Regra do gráfico**: "concluído" = `Migrado`/`Modernizado`/`Despriorizado e Contabilizado` (helper `isConcluido` — despriorizado SEMPRE conta como esforço entregue).
- **Coluna futura** "Responsável Validação BV" (etapa "Validação da Área" + evidência): só comentário no código, junto do `<thead>`.

### Timestamps: gravados em UTC, exibidos em São Paulo (2026-08)

Todo timestamp do painel (`sas_gestao_status.ts`, `sas_inputs_audit.updated_at`, `sas_pipeline_audit.ts`, `saved_at` do snapshot da Priorização) é gravado com `current_timestamp()` do **SQL warehouse, que roda em UTC**, e persistido como **STRING sem sufixo de zona** (`"2026-07-27 19:51:38.841"`). A UI exibia a hora crua → **+3h** (comentário das 16:51 aparecia como 19:51; ao virar a meia-noite UTC até a data saía errada).

- **A conversão é na EXIBIÇÃO, não na escrita** — helper único [`fmtTsBR`](frontend/src/diasUteis.ts) (UTC → `America/Sao_Paulo`, via `Intl` com `hourCycle: "h23"`). O banco mantém **uma convenção só** (tudo UTC) e as **linhas antigas passam a aparecer certas** sem backfill. Converter na escrita criaria base misturada (UTC antigo + SP novo) indistinguível.
- **Não dupliquem a conversão**: se algum dia a escrita passar a gravar SP (`from_utc_timestamp`), `fmtTsBR` tem de sair junto — senão desconta 3h de novo.
- **Campos date-only NÃO passam por `fmtTsBR`** (usam `fmtBR`, string slicing puro): eventos "Com BV" e datas da Gestão já são **data de SP** na escrita (`from_utc_timestamp(current_timestamp(), 'America/Sao_Paulo')` em `POST /api/gestao/bv`). Deslocá-las mudaria o dia.
- Superfícies cobertas: sidepanel de status (último + histórico), aba **Histórico**, histórico do input (drawer do Monitor) e o selo "📌 fixado em" da Priorização. Regressão em [`frontend/datas.test.mts`](frontend/datas.test.mts).
- **Nome do arquivo nos exports**: `csv.ts:csvDate()` passou a usar `hojeSP()` (era `toISOString()` = UTC, e export feito das 21h em diante saía com a data de amanhã no nome).
- **Aceito como está** (decisão do usuário, 2026-08-12): `_migrados_mes` compara `substr(ts,1,7)` com `date_format(current_date(),'yyyy-MM')` — ambos UTC, então uma migração marcada depois das 21h SP do último dia do mês conta no mês seguinte. Não é problema na prática; não "corrigir" sem pedido.

### Aba Gestão + responsáveis (grupo bv_users) (2026-07)

Aba **Gestão** (`/gestao`) gerencia a lista de **analistas** (`sas_analistas`: email, nome, ativo) — fonte dos **dropdowns de responsável**. Atribuição de responsável acontece **nas abas existentes**: input (Monitor) e EGP (aba EGPs). Responsável do **input** = ingestão; do **EGP** = migração.

- **Gate por grupo via SQL** (não SCIM): `is_account_group_member('bv_users') OR is_member('bv_users')` roda **como o usuário** (OBO). Exposto como `is_gestao` no `/api/config`; o front **esconde a aba** e o backend reforça **403** (`_require_gestao()`) nas escritas de analista. Aceita `bv_users`/`bv_user` (o real é `bv_users`, plural). Validado: `is_account_group_member('bv_users')`=true.
- **Só a aba Gestão é restrita** — os **dropdowns** de responsável são livres a qualquer usuário (como editar status). `GET /api/analistas` é aberto (popular dropdowns); `POST/DELETE` são gated. Delete é **soft** (`ativo=false`).
- **Valor guardado = email** do analista; a UI exibe o **nome**. Valores antigos (texto livre) seguem aparecendo até serem reatribuídos (o `<select>` injeta uma option com o valor atual se não estiver na lista).
- **Sufixo canônico `@indicium.ai` (2026-07):** a mesma pessoa existe na Indicium com `@indicium.tech` e `@indicium.ai` — toda escrita (upsert/delete) **canoniza para `.ai`** (`_canon_analista_email`) e **nunca duplica** por `nome.sobrenome`: se a pessoa já existe com o sufixo legado `.tech`, a linha é **migrada** para `.ai` (ou a legada é descartada se o `.ai` já existe); o delete desativa o par. Dados históricos migrados por UPDATE (analistas + colunas `responsavel`).
- **EGP responsável**: coluna `responsavel` em `sas_egp_pipeline` (`_ensure_pipe_table` cria/ALTER); `PATCH /api/egp-pipeline` aceita `responsavel` (+ auditoria). Prontidão (`_egp_readiness_rows`) devolve `responsavel`.
- **Cadastro de analistas é só manual** desde a Fase 2 (o antigo sync do grupo via SCIM saiu). O gate NÃO depende disso.

### Aba "Priorização" (ex-Ondas): plano por capacidade + pin de mês (2026-07)

A antiga aba **Ondas** virou **"Priorização"** (slug segue `/ondas` p/ deep-links): um **plano de ingestão por mês**. `GET /api/priorizacao` empacota os EGPs do recorte em **meses** de ≤ **400** inputs distintos a ingerir (lógica pura em [`backend/priorizacao_logic.py`](backend/priorizacao_logic.py), testada em `test_priorizacao_logic.py`).

- **Recorte FIXO** (decisão 2026-07): Área = todas, escopo = **Indicium + dependências** (frontier transitivo). Os seletores foram removidos da UI — o plano é um só, compartilhado por todos (e pelas outras abas, ver *Onda → Mês dinâmico*).
- **Capacidade configurável pela gestão** (2026-07): o teto de inputs/mês é **persistido** em `sas_app_config` (chave `prio_capacidade`, default **400**) e editável inline na linha de recorte (só `bv_users`) via `PATCH /api/priorizacao/capacidade` (1..10000; auditado em `sas_pipeline_audit` com projeto sentinela `(config)`). Gravar recalcula O plano de todos — não é filtro por usuário. O front não envia mais `capacidade` no GET (0 = usa a config; >0 na URL segue como override manual).
- **`Despriorizado e Contabilizado` entra no mês como EGP normal** (decisão final 2026-07, após duas iterações: excluir do plano → grupo "Fora do backlog" → **no mês mesmo**): consome capacidade, conta em total/habilitados, aceita pin; o status azul na linha já o distingue. A única diferença é a regra de deps (`no_expand`): as dependências exclusivas dele não são puxadas para o recorte.
- **Ordem lexicográfica** (`_viab` + fan-out): **1) viabilidade** — não bloqueado + com pendências **ingeríveis** vem antes de bloqueado / só-SAS-local (tiers 0/1/2); **2) alavancagem** — maior **fan-out** (nº de EGPs do recorte que consomem o output, via `sas_lineage_edges`); **3) quick win** — menos inputs (desempate). O teto conta todos os inputs a ingerir; SAS/local já cai pro fim via viabilidade.
- **Dedupe entre meses**: custo marginal de um EGP = seus inputs a ingerir que **ainda não** entraram em meses anteriores (input compartilhado conta **1×**, no 1º mês). Guloso, mês a mês.
- **Pin manual de mês (📌, só gestão):** `PATCH /api/priorizacao/mes` grava `mes_prioridade` (1..100) em `sas_egp_pipeline`. O pin é **absoluto**: o EGP entra no mês pinado mesmo estourando a capacidade (o teto 400 vira **guia**, marcado `excede`); soltar o pin devolve o EGP ao empacotamento automático. Meses vazios são removidos/renumerados.
- **Cards de resumo (2026-07, v2):** **Migrados** (status `Migrado`, com "N neste mês" embutido), **Despriorizados** (`Despriorizado e Contabilizado`), **Bloqueados** (dependem de tabela SAS sem produtor) e **Habilitados** (= total − bloqueados) — cada card com descrição curta + tooltip. Migrados/Despriorizados são contados **client-side** do payload dos meses.
- **Barra do mês = AVANÇO, não carga (2026-07):** a barra/pill de cada mês mostra **EGPs concluídos** (`Migrado` + `Despriorizado e Contabilizado`, mesma régua do headline do funil) sobre o total do mês — não mais inputs/capacidade. A carga de inputs virou texto neutro ("X/cap inputs novos"): mês acima do teto **não é erro** (pin é absoluto; o teto só guia o empacotamento automático).
- **Plano = SNAPSHOT CONGELADO; o recorte é vivo (2026-09).** `GET /api/priorizacao` devolve o snapshot salvo (`sas_priorizacao_snapshot`), com overlay vivo apenas de etapa/status/responsável/bloqueado. EGP que entra no recorte **depois** do save (ex.: nova dependência transitiva, caso `PERF_REVISIONAIS_RPA` 2026-09-14) não existe no plano — os cards vivos (Total de EGPs, funil +deps) contam 1 a mais que o "Funil de migração por mês" do Resumo (193 vs 194). **Não é bug:** re-salvar o snapshot (botão Salvar da aba, admin) absorve o EGP novo. Divergência tabela-por-mês vs cards = sinal de recorte alterado pós-snapshot.
- **Meses de calendário:** Mês 1 = mês corrente (dinâmico), rotulado "Mês N — <mês>/<ano>"; deadline **dez/2026** — meses além exibem aviso **"fora do prazo"**.
- Front (`WavesView`): lista vertical de meses (accordion), **1 EGP por linha** (EGP · Área · Etapa · Status · +Inputs · Alimenta · Responsável · Mês/pin), clique → aba EGPs. EGP cujos inputs próprios já passam da capacidade → **mês próprio**, `excede=true`. `/api/waves` (ondas manuais do dado) fica **dormente**.
- **Export CSV (2026-07):** "⬇ Exportar CSV" baixa o **plano inteiro** (todos os meses, expandidos ou não), 1 linha por EGP × mês na ordem exibida — colunas Mês/Calendário/Fora do prazo/EGP/Área/Etapa/Status/Concluído/Inputs novos/Alimenta/Responsável/Bloqueado/Fixado/Excede (`csv.ts` compartilhado, EGP sem prefixo de área).

### Onda → Mês dinâmico app-wide (2026-07)

A coluna estática **"Onda"** (do dado publicado) foi substituída pelo **Mês do plano de priorização** em todas as abas que a exibiam (EGPs, Escopo, Linhagem, drawers de input/EGP). Hook compartilhado `frontend/src/mesPlan.ts` (`useMesPlan()`): consome o **mesmo cache** React Query do plano (`queryKey ["priorizacao"]`, `staleTime` 60 s) — pinar um mês re-renderiza todas as abas na hora. EGP **fora do recorte** do plano mostra **"—"**; o marcador **⟳** (ciclo) continua vindo de `ciclo_id`.

### Via resolvida não gera dependência (2026-07)

Uma via de dependência (tabela que liga consumidor→produtor) cujo status **efetivo** é `Modernizado` ou `Sanitizado` está **resolvida**: o dado já está no lake (ou foi descartado do escopo), então o consumidor **não precisa mais do EGP produtor** por causa dela. `_vias_resolvidas()` (mesma regra do `_modern()`; cache OBO+TTL da linhagem) + `_filter_vias_resolvidas()` **compostos dentro de `_edges_pruned()`** — vale automaticamente em TODO o app: frontier/"+ dependências", `depende_de`/`alimenta` do detalhe, bloqueio (deixar de precisar = deixar de ser bloqueado por), priorização (recorte e alavancagem/fan-out). Aresta que ficar sem via alguma é descartada; aresta sem via declarada é mantida (não há como avaliar). **Derivado do status a cada leitura** — reverter o status do input traz a dependência de volta (TTL de cache curto). Medido na ativação: 211 vias removidas → 156/1.733 arestas descartadas; frontier indi+deps 201→193.

### "Despriorizado e Contabilizado" não puxa dependências (2026-07)

EGP com status `Despriorizado e Contabilizado` **não semeia nem expande** o fecho de dependências — dependência **exclusiva** dele some de todos os recortes "+ dependências". Fora isso, o EGP em si segue em **tudo** como um EGP normal, **inclusive no plano da Priorização** (mês, capacidade, resumo, pin) — decisão final 2026-07; as versões intermediárias (excluir do plano / grupo "Fora do backlog") foram revertidas no mesmo dia.

- **Mecânica: derivado, nunca cascateado.** O status **não** é propagado às dependências (status é estado humano; e "exclusiva de X" muda com o tempo). Em vez disso, `_transitive_upstream(..., no_expand=_egps_fora_backlog())`: o EGP fora do backlog recebe nível (continua visível na base/DOR1 e como dep alcançada por EGP vivo) mas **não expande** o BFS. Dependência **exclusiva** dele deixa de ser alcançada → some de todos os recortes "+ dependências" (Monitor `indi_deps`, aba EGPs, funis +deps, Resumo, landing, Priorização — um ponto de mudança); dependência **compartilhada** com EGP vivo continua alcançável → fica. Reverter o status traz tudo de volta na hora.
- **Contagens DOR1 não mudam**: ele segue na base (`base_count`, funil por área, aba EGPs) com o status visível — sair de *tudo* é papel do ✕ desativar na aba Escopo.
- **O `_blocking()` (BFS downstream) fica intocado** — semântica de bloqueio é outra questão; `_egps_fora_backlog()` documenta isso.
- **Dep viva marcada como despriorizada**: se um EGP ativo depende dela, ela continua aparecendo (a necessidade é real; alcançabilidade decide, não o status da dep).

### Recorte default = "Indicium + dependências" (2026-08)

**Inputs**, **Outputs** e **EGPs** abrem em `indi_deps` (antes `indi`). O trabalho real é o
fecho — um EGP do escopo só migra quando as dependências dele saem do caminho —, então abrir
em "só Indicium" escondia por padrão justamente a parte que trava. As três abas mantêm o
seletor: quem quer o recorte estreito troca em 1 clique.

- **Outputs ganhou o recorte `indi_deps`, que não existia** (o `<select>` só tinha Indicium/Base).
  A flag `escopo_indi` da linha **não serve** para o fecho — o recompute só a marca para EGPs do
  escopo direto —, então `_outputs_scope_where()` filtra por `chave_canonica ∈ outputs dos EGPs
  do frontier` (`_frontier_egps("indi_deps", [])`), o mesmo universo da aba Inputs. Vale para
  `/api/outputs` e `/api/outputs-egps` (export). Medido no dev: 562 (indi) → 653 (indi_deps) →
  3741 (base), com inclusão estrita verificada.
- **Sem filtro de área server-side** no Outputs: a aba filtra área no cliente, então o recorte
  do servidor é o fecho inteiro (diferente de `/api/inputs`, onde a área define a base).
- **Custa mais caro:** o fecho transitivo é ~3x o recorte antigo (inputs 7,8s → 20s;
  egp-readiness 7s → 27s no dev morno). Por isso o `prefetch.ts` foi **reordenado** — `inputs`
  saiu do grupo das leves e subiu para a 1ª onda. Se mudar algum default, reordene junto.
- Os defaults `scope: str = "indi"` dos endpoints **não** mudaram: são fallback para chamada sem
  parâmetro e o front sempre manda o `scope` explícito.

### Unificação: aba EGPs absorveu "Escopo de migração" (2026-07)

A antiga aba **"Escopo de migração"** foi fundida na aba **EGPs**, que ganhou um **seletor de escopo** com 3 opções: *só Indicium* (`indi`), *Indicium + dependências* (`indi_deps`, frontier **sempre transitivo** — a opção 1-nível morreu) e *todos* (`base`). Spec: [`docs/superpowers/specs/2026-07-06-unificacao-egps-escopo-migracao-design.md`](docs/superpowers/specs/2026-07-06-unificacao-egps-escopo-migracao-design.md).

- **`GET /api/migration-scope` e `MigrationScopeView.tsx` foram REMOVIDOS** — não "restaurar" nem referenciar. Tudo vive em `GET /api/egp-readiness?scope=…` (payload `ReadinessPayload`: `rows` + header `base_count`/`dep_count`/`inputs_distintos[_disp/_faltam/_base]`/`inputs_sem_fonte`, sempre presente).
- Rows têm `tipo` (escopo × dependência), `dep_nivel`, `n_sem_fonte`, `dep_ausente` em **qualquer** scope; a coluna **Tipo** só é exibida em `indi_deps`. Dependência sem linha no inventário (produtor-only) vira **stub** completo no backend — nunca dict parcial (já causou 500).
- **Cards sempre visíveis** (EGPs, Inputs distintos, A ingerir, Sem fonte) refletem o **recorte do seletor**, não os filtros client-side (decisão explícita).
- **Deps são editáveis** (etapa/status/responsável) como qualquer linha — decisão do usuário.
- Slug `/escopo-migracao` é **alias** para a aba EGPs (`routes.ts::parsePath`, links salvos); deep-links `/egps/<id>` seguem donos da aba. CSS `.ms-*` do view antigo ficou (`.ms-badge` é usado pela coluna Tipo).

### Abas renomeadas: sem o prefixo "Monitoramento" (2026-07)

"Monitoramento Inputs" → **Inputs**; "Monitoramento Outputs" → **Outputs** (labels em `routes.ts:TABS`). **Slugs preservados** (`/monitoramento`, `/monitoramento-outputs`) para não quebrar links salvos — não "arrumar" o slug junto com o label.

### Resumo: funil por área e inputs por origem em 2 visões (2026-07)

As tabelas **"Funil por área (DOR1)"** e **"Inputs por origem (DOR1)"** aparecem lado a lado em duas visões: **escopo Indicium** e **"+ dependências"** (chips `Escopo Indicium` / `+ dependências`). `/api/resumo` devolve `funil`/`origem` + `funil_deps`/`origem_deps` (null se grafo ausente → a UI degrada para a visão única).

- Na visão +deps, o funil por área ganha a coluna **"Dependências"** (quantos EGPs da linha vêm de fora do escopo).
- **`Libname_in` saiu** da tabela de origem: libname é *alias de biblioteca*, não origem de dado — só poluía o DOR1. Ordem fixa dos buckets: BigQuery · Arquivo · Transacional · SAS/Local, com **% Modernizado** em barra.
- **Tabela dirigida pelo MONITOR, não por `sas_resumo_inputs` (2026-09).** `sas_resumo_inputs` só é reescrita pelo **publish completo**; input que entra por carga avulsa (ex.: overlay INSERT-only do descompacta) não ganha linha lá — e, com o JOIN no sentido antigo (`sas_resumo_inputs LEFT JOIN sas_inputs_monitor`), sumia da tabela de origem enquanto o card da landing (que lê o monitor) contava: 5 chaves de diferença em 2026-09-14 (1.211 vs 1.206). O `/api/resumo` agora faz `sas_inputs_monitor i LEFT JOIN sas_resumo_inputs r` e filtra o universo por `i.*`; `r` vira só fallback de `area_principal`/`origem_bucket` (linha nova fica com área "—" no funil por área até o próximo publish preencher). O que a inversão descarta são as órfãs de `sas_resumo_inputs` — verificado em prod: 100% `Libname_in`, já fora da tabela e da landing. **Invariante ampliado:** "Total" da origem ≡ "Total de Inputs" da landing e "Não Modernizado" ≡ "Total não modernizados", nas duas visões. Não reverter a direção do JOIN — a defasagem volta na próxima carga fora do publish.
- **A coluna "Inputs não Modernizados" do funil usa a MESMA régua da tabela de origem** (fix 2026-07): `nao_mod_por_area` filtra os 4 buckets (Libname_in fora do funil também — sem isso divergia 2.204 vs 2.092), e área de input **sem linha de EGP** no recorte (ex.: input Jurídico consumido por EGP de Cobrança) ganha **linha própria zerada** em vez de sumir do total (21 inputs perdidos na visão +deps quando detectado). Invariante: total do funil ≡ "Não Modernizado" da tabela de origem, nas duas visões.

### recompute_escopo: filtro `ativo` + self-heal de `faltante` (2026-07)

O recompute do escopo existe em **2 cópias que DEVEM andar juntas**: `backend/main.py:recompute_escopo` e `../publish_to_databricks.py`. (Havia uma 3ª, `app/pipeline/publish_to_databricks.py`, apagada com a aba Ingestão em 2026-08.) Invariantes das três:

- Todo universo de escopo filtra **`ativo IS NOT false`** (senão o publish ressuscita entradas desativadas — bug latente corrigido em 2026-07).
- **Self-heal:** `status_extracao='faltante'` vira `'exato'` quando o `projeto` existe no grafo publicado (um EGP que chegou depois de entrar no escopo ficava "faltante" para sempre e sumia da contagem de analisados — caso 167 vs 168).
- O funil por área conta por `status_extracao` — depende do self-heal acima para fechar com o total.
- **`area_principal` recomputada no frontier também no publish (2026-08).** O `build()` do publish vota pela ponte DOR1 (só EGPs da lista Indicium), então input consumido **apenas por EGP-dependência** não recebia voto e ficava `(sem área)` — virava linha órfã no funil por área **"+ dependências"** do Resumo (105 inputs não modernizados no dev, 143 em prod). O backend já corrigia em `_recompute_area_principal` (voto pela área do nó no **frontier** = escopo ∪ deps), mas **só quando alguém editava escopo no app**: publish por CLI deixava a coluna defasada. O publish agora chama `recompute_area_principal()` logo depois do bloco de escopo — atribuição verificada **idêntica** à do backend, chave a chave, sobre os dados do dev.

### Desativar entrada do escopo (soft) (2026-07)

Na aba **Escopo**, o ✕ agora **desativa** (soft, `sas_escopo.ativo=false`) em vez de apagar — a entrada fica guardada (área/status/created) e um botão **↺ reativar** a traz de volta **sem re-adicionar**.

- `DELETE /api/escopo/{id}` = **soft** por padrão (`?hard=true` remove de vez); `POST /api/escopo/{id}/ativar` reativa; **adicionar** um EGP que está desativado o **reativa** (em vez de 409).
- `recompute_escopo` e as contagens de escopo (egps_escopo, funis, funil por área) consideram **só `ativo IS NOT false`** → desativar tira o EGP do escopo em **todo o app** na hora (Resumo/Monitor/EGPs/landing); reativar traz de volta com tudo preservado.
- Coluna garantida por `_ensure_escopo_ativo()` (ALTER-if-missing, flag process-local; já criada em prod). NULL/ausente = ativo. UI: linhas desativadas **esmaecidas** + pill "desativado" + chip "⏸ Desativados: N".

### Armadilha de tema (light mode)

No tema claro, `--danger-soft` é definido **igual** a `--danger` (vermelho escuro) — texto `--danger` sobre fundo `--danger-soft` vira bloco ilegível. Para chips/badges de aviso use a paleta **`--tone-cyc-bg/fg/border`** (theme-aware, usada em `.error`/`.cyc-warn`). `--danger-soft` é cor de **texto**, nunca de fundo.

### Export CSV (Monitor)

Botão "⬇ Exportar CSV" exporta as linhas **exibidas** (`sorted` — filtros + busca + ordenação) no **cliente**, sem warehouse. Separador `;` + BOM UTF-8 (Excel pt-BR abre com acento e colunas corretas).

- **Explode por EGP (2026-07):** o CSV sai com uma coluna **`EGP`** e **uma linha por (input × EGP)** — cada input se repete para cada EGP que o consome. O mapeamento vem de `GET /api/inputs-egps?scope&area` (pares `chave_canonica`→`projeto` do recorte; `escopo_indi` p/ indi, frontier p/ indi_deps), buscado no clique do export e cruzado com as linhas exibidas. Input sem EGP mapeado → 1 linha com EGP vazio.

### ~~Ingestão in-app~~ — removida (2026-08)

A aba **Ingestão** (upload de `.egp`/`chameleon.csv` + "Processar & publicar", que rodava
extractor → orchestrator → publish dentro do container como SP) **não era usada** e foi
removida por decisão do usuário. Junto com ela saíram `backend/ingest.py`, as rotas
`/api/ingest/*`, o UC Volume como estado durável do pipeline e as cópias vendorizadas em
`app/pipeline/` — logo, **não há mais nada a espelhar de `egps_analysis/` para dentro do app**.
O refresh dos dados passa a ser só o caminho local (§Refresh dos dados).

Contexto do que existia (caso um dia se queira ressuscitar): spec
[`docs/superpowers/specs/2026-07-03-ingestao-in-app-design.md`](docs/superpowers/specs/2026-07-03-ingestao-in-app-design.md)
e plano [`docs/superpowers/plans/2026-07-03-ingestao-in-app.md`](docs/superpowers/plans/2026-07-03-ingestao-in-app.md).

### Aba Monitoramento Outputs (read-only) (2026-07)

Espelha a de Monitoramento Inputs, mas para os artefatos **produzidos** pelos EGPs — e **read-only** (outputs não serão migrados; só informação). Slug `/monitoramento-outputs`, não-gated. Colunas: Artefato · Categoria · Área(s) · Produtores · Consumidores · Terminal/Intermediário (coluna "Disponível" removida da grade/CSV em 2026-07 a pedido; o dado `modernizada_auto` segue na tabela e no drawer). Filtros client-side (escopo indi/base, área, categoria, "só terminais", busca), drawer com produtores+consumidores, export CSV (reusa `csv.ts`, nome do EGP sem prefixo de área).

Decisões (o **porquê**):

- **Duas tabelas Delta novas, full-replace no `publish`** (sem colunas humanas — nada a preservar): `sas_outputs_monitor` (grão output distinto: `qtd_produtores`, `qtd_consumidores`, `terminal`, `modernizada_auto`, `escopo_indi`) e `sas_egp_outputs` (grão EGP×output, alimenta o drawer e o export). Construídas a partir das linhas de output do report 06 (`table_out`/`file_out`/`libname_out`; `table_out` ruído filtrado por `is_noise_table` e nome solto por `is_work_implicit` — ver bullet abaixo). Endpoints read-only: `GET /api/outputs`, `/api/output`, `/api/outputs-egps`.
- **Consumidores vêm de `sas_egp_inputs`** (invertendo `proj_in` por nome canônico), não de `sas_lineage_edges`. Um output é **terminal** quando `qtd_consumidores = 0` (saída final, ninguém no corpus lê) e **intermediário** caso contrário. `proj_in` guarda `canon(art)` **puro** (não a chave prefixada dos inputs) justamente pra casar com as chaves dos outputs — sem isso todo output apareceria como terminal.
- **`table_out` de nome solto (sem `lib.` nem path) fica FORA do universo (2026-07):** `data X;` sem libname = `WORK` **implícita** — temporária por sessão; "N produtores" de um nome solto não significa nada (cada EGP escreve a própria WORK) e 85% da grade era isso (22.255→4.955 outputs distintos; o "multi-produtor" cai de 5.607 para ~414 reais — dos verificáveis por path, 100% escrevem no mesmo lugar físico). Filtro `is_work_implicit` no `publish`, **só** no universo da aba (`outputs`/`egp_outputs`); `produced_tables`/arestas ficam intactos. Vale a partir do próximo publish. Complemento no extrator (2026-07): `data '/caminho/tabela';` (dataset físico quotado, sem LIBNAME) agora é capturado como output **permanente** (`physical_dataset_target`) e o orquestrador registra o produtor na linhagem por `(path, membro)` — casa com consumidores que leem o mesmo diretório via LIBNAME.
- **`escopo_indi` dos outputs entra no `recompute_escopo`, mas com guarda:** os 4 UPDATEs de output só rodam se as tabelas já existem (probe `SELECT 1 … LIMIT 0`), dentro de `try/except (HTTPException, RuntimeError)`. Editar o escopo **nunca** pode quebrar por causa dos outputs (ex.: antes do 1º publish com outputs). Roda via `exec_fn` (OBO nas edições; SP no job de ingestão).
- **`sas_egp_outputs` não tem `ciclo_id`** (produtores); o `/api/output` seleciona `NULL AS ciclo_id` nos produtores pra manter o mesmo shape dos consumidores (`sas_egp_inputs`, que tem).
- **Popular:** as 2 tabelas nascem no `publish` — rode **um publish local** após deploy. Até lá `/api/outputs` retorna vazio (tolerado) e a aba mostra "nada".

Spec + plano: [`docs/superpowers/specs/2026-07-04-monitoramento-outputs-design.md`](docs/superpowers/specs/2026-07-04-monitoramento-outputs-design.md) e [`docs/superpowers/plans/2026-07-04-monitoramento-outputs.md`](docs/superpowers/plans/2026-07-04-monitoramento-outputs.md).

## Dev local

Pré-requisitos:

- Profile **`bv`** no `~/.databrickscfg` (host + auth do workspace). Confira com
  `databricks auth profiles`.
- Acesso ao SQL Warehouse **`monitoramento-sas`** (id `5922c26f81f1bbdd`) — precisa
  estar ligado (ou liga sozinho na 1ª query).

```bash
# 1. venv com as deps (uma vez) — fica em egps_analysis/venv
python3 -m venv ../venv
../venv/bin/pip install -r requirements.txt

# 2. backend (porta 8000) — auth pelo profile bv (não precisa de .env/token)
export DATABRICKS_CONFIG_PROFILE=bv
export DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd
export PUBLISH_CATALOG=bv_dev_db PUBLISH_SCHEMA=monitoramento_sas
../venv/bin/python backend/main.py        # serve API + ./static em :8000

# 3a. usar o bundle já compilado: abra http://localhost:8000
# 3b. ou front com hot-reload (proxy /api -> :8000):
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Sanidade: `curl http://localhost:8000/api/health` deve retornar
`{"ok":true,"table":"bv_dev_db.monitoramento_sas.sas_inputs_monitor","warehouse":true}`.

> Auth alternativa (sem profile): `export DATABRICKS_HOST=... DATABRICKS_TOKEN=...`.
> Se o token vier de um `.env` salvo no Windows, remova o CRLF ao carregar:
> `set -a && source <(tr -d '\r' < .env) && set +a` (um `\r` no token quebra o header `Bearer`).

Rebuild do front (**sempre antes do deploy**): `cd frontend && npm run build` → gera `../static/`.

## Deploy (Databricks Apps)

**Processo completo (prod via CI/CD + dev manual): [`docs/DEPLOY.md`](docs/DEPLOY.md).** Resumo:

- **Produção** (`monitoramento-sas`, schema `monitoramento_sas`) — **automático**: merge na `main` que toque `egps_analysis/app/**` dispara o [`bitbucket-pipelines.yml`](../../bitbucket-pipelines.yml) (testes → build → sync → deploy → verificação). O gate humano é o **merge do PR**. Fallback manual, mesma lógica: `cd app && DATABRICKS_PROFILE=bv bash deploy_prod.sh`.
- **Dev** (`monitoramento-sas-dev`, schema `monitoramento_sas_dev`) — **manual**: `cd app && bash deploy_dev.sh` (troca `app.yaml`→`app.dev.yaml`, deploya, restaura por `trap`).

Ambos rodam **de dentro de `app/`** e fazem a mesma sequência abaixo — se rodar de `egps_analysis/`, o `sync` sobe a árvore inteira (docs/CSVs) e o deploy falha no limite de **10 MB por arquivo**.

```bash
# o que os scripts fazem (deploy_prod.sh / deploy_dev.sh encapsulam isto):
cd frontend && npm run build && cd ..                    # 1. bundle compilado
WS=/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas
databricks sync --full . "$WS" -p bv                     # 2. sync só do app/ + deploy
databricks apps deploy monitoramento-sas --source-code-path "$WS" -p bv
```

> Criar o app (só na 1ª vez): `databricks apps create monitoramento-sas -p bv`.
> CI/CD usa **OAuth M2M** (service principal) por variáveis de repositório — ver `docs/DEPLOY.md` §Setup.

O app roda `python backend/main.py` na porta `DATABRICKS_APP_PORT`. Catálogo/schema e
warehouse vão no `app.yaml` (`PUBLISH_CATALOG`/`PUBLISH_SCHEMA`/`DATABRICKS_WAREHOUSE_ID`).
**Grants (OBO):** com `REQUIRE_OBO=true`, quem precisa de acesso é **cada usuário**
(não o service principal). Conceda a cada usuário/grupo, no Unity Catalog:
`USE CATALOG bv_dev_db`, `USE SCHEMA monitoramento_sas`, `SELECT` (ler) e `MODIFY`
(editar status) nas tabelas do schema, e `CAN USE` no warehouse `monitoramento-sas`.
Sem isso, as queries do usuário retornam **403** (sem permissão). No 1º acesso pode
haver tela de consentimento dos escopos.

## Refresh dos dados

Só há um caminho desde 2026-08 (a aba Ingestão foi removida — ver §Decisões de design).

Os dados vêm do passo publish do pipeline (recria/atualiza as Delta tables, preservando as colunas humanas no MERGE). Rode da pasta `egps_analysis/` (onde estão os CSVs `06_*`).

> ⚠️ **`monitoramento_sas` é o schema de PRODUÇÃO** (apesar do catálogo `bv_dev_db`). O
> sandbox seguro é `monitoramento_sas_dev`. Sem `--schema`, o publish escreve no **sandbox**
> (default). Para escrever em prod é preciso `--schema monitoramento_sas --prod-confirm` —
> a flag existe para impedir um `--apply` manual cair em prod por acidente.

Sandbox (o normal para teste manual):

```bash
cd ..   # egps_analysis/
venv/bin/python publish_to_databricks.py --apply --profile bv --warehouse-id 5922c26f81f1bbdd
# escreve em bv_dev_db.monitoramento_sas_dev (default)
```

Produção (deliberado):

```bash
venv/bin/python publish_to_databricks.py --apply --prod-confirm \
  --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd
```

> `publish` exige `--profile` (ou `DATABRICKS_HOST`+`DATABRICKS_TOKEN`); só exportar
> `DATABRICKS_CONFIG_PROFILE` não basta para ele. Sem `--apply` roda em dry-run.
