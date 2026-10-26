# Divergências entre telas — catálogo

Por que o app mostra **X num lugar e Y em outro**. É a fonte das instruções do agente de
consulta (aba Perguntas / Genie — ver `egps_analysis/app/genie/`) e a referência para quem
mexe no app. Termos (Escopo, Recorte, Linha de base, Extra, Ex-dependência…) seguem o
`CONTEXT.md` da raiz.

**Manutenção:** mudou o que uma tela conta? Atualize a entrada (ou crie uma) e rode
`egps_analysis/app/genie/avalia.py`. Toda magnitude tem data — o Recorte muda sozinho
(item 18), então número sem data não serve de prova.

Classificação de cada entrada:
- **proposital** — as duas telas respondem perguntas diferentes; o agente explica a régua.
- **corrigido** — foi bug, não é mais; fica para explicar números antigos.
- **inconsistência medida** — medida e confirmada, ainda não corrigida; o agente diz que é
  inconsistência do app e manda reportar.
- **suspeita** — inferida do código, não medida; o agente diz que é suspeita, nunca bug.

---

## Réguas que explicam quase tudo

| Régua | Valores | Quem usa o quê |
|---|---|---|
| **Universo de EGPs** | Escopo (vivo) · Linha de base (193, congelada em 29/09/2026) · Recorte (Escopo + Dependências, vivo) · Recorte + Ex-dependências · Extras à parte | Cards de total e "X de 193": Linha de base. Listas, Kanban e Gestão: Recorte. Escopo/Tempo por Etapa: Escopo vivo. |
| **Grão de input** | Família de safras (prod, `FAMILIAS_SAFRA=1`) · safra | Família: Resumo, Inputs, EGPs, Gestão, Priorização. Safra: Outputs, Tempo por Etapa (inputs), app local (flag desligada). |
| **Etapa/status** | exibido (antecessor Atualizado/Unificado = `Desatualizado`, etapa do sucessor) · de contagem (antecessor herda o status do fim da cadeia) · gravado | Telas mostram o exibido; "X/Y migrados" conta pelo de contagem; Tempo por Etapa usa o gravado. |
| **Sanitizado** | dentro do universo (conta como resolvido) · fora | Cards de input contam; funis de ingestão e Gestão tiram. |
| **Vínculo ativo** | input com ≥1 vínculo não quebrado no recorte | Todas as contagens e a Gestão de inputs exigem (a Gestão desde 09/10/2026 — item 12). |
| **Vivo × congelado** | Linha de base, plano de Priorização e Histórico de métricas são fotos | Comparar foto com tela viva sempre dá diferença. |

---

## Catálogo

### 1. Total de Inputs (Resumo) × funil de ingestão +deps — proposital
Os funis de ingestão excluem os inputs lidos **só** por Extras (que têm funil próprio); o
card soma escopo + dependências + extras. 05/10/2026: funil +deps 1.222 + funil extras 74
= 1.296 do card. A tabela "Inputs por origem +deps" inclui extras e bate com o card
menos os placeholders `casco::` dos unificados, que o card conta e a tabela não (não
são origem de ingestão) — a tabela informa quantos embaixo (5 em 14/10/2026).

### 2. Funis de ingestão × cards de inputs — proposital
O funil tira Sanitizado do total (vira contador ao lado); o card conta Sanitizado como
resolvido, dentro do universo.

### 3. Cards de input da aba EGPs × Visão geral — proposital
Os cards da aba EGPs contam os inputs dos EGPs **em tela**; a Visão geral, os do universo
do grupo. 05/10/2026 (inputs / a ingerir): só Indicium 1.166/311 × 1.161/311; +deps
1.222/327 × 1.242/336; +deps+extras 1.296/370 × 1.303/377. Fecha exato em "+extras" com o
chip "fora da linha de base" ligado (7 unidades lidas só por 19 linhas ocultas). "Só
extras": aba 381 × grupo do Resumo 61 — a aba mostra tudo que os extras leem, o grupo só o
que **só** eles leem.

### 4. "X de 193" × tamanho das listas — proposital
O total é a Linha de base congelada; a lista da aba EGPs mostra Recorte + todas as
Ex-dependências (209 × 192 em 25/09/2026). O chip "fora da linha de base", desligado por
padrão, esconde as que não contam. O Recorte vivo oscila (≈181–214) sem ninguém editar.

### 5. "(+N extra)" ao lado do total — proposital
Extra conta à parte, nunca dentro do total. Até 29/09/2026 havia bug (ex-dependências
rotuladas como extra "novo", 37 × 18) — **corrigido**.

### 6. Kanban (Acompanhamento/Gestão) × aba EGPs — inconsistência medida (estrutural)
O Kanban usa Recorte + Ex-dependências contabilizadas **vivo**, sem a régua da Linha de
base e com Extras; a aba EGPs, a lista congelada. 05/10/2026: Kanban 228 × EGPs 226,
Desatualizado 30 × 29 (eram Cadu_HUB e PERFORMANCE_CL_202608_GCP, removidos do corpus).
Qualquer dependência nova fora da lista reabre a diferença.

### 7. "Migrados" da Gestão × "X/Y migrados" do funil +deps — proposital
Medido em prod 06/10/2026: Gestão 100 × funil 96. A diferença são exatamente **4 Extras
já migrados** (First_Loss_GCP_2026, Oportunidade Protesto_20260703, ROI,
Project_Fyf_Reneg_BQ_202608 1): a Gestão mostra o Recorte com os 33 Extras; o funil +deps,
só a Linha de base (eles aparecem no funil de extras, 4/33). A Gestão conta pela **etapa**
e o funil pelo **status**, mas os dois somam Migrado + Despriorizado e Contabilizado — a
régua de etapa não muda o número hoje. Lembrar: etapa "Migrado" inclui despriorizados (73
dos 100).

### 8. Antecessor espelhado nos totais de migrados — corrigido (05/10/2026)
O antecessor Atualizado/Unificado aparecia na coluna "Migrado" (etapa espelhada) e fora do
"X/Y" (status Desatualizado): 96 × 95/193. Corrigido com o status de contagem. **Suspeita**
remanescente: o card "Migrados" da Priorização lê o status **exibido**, não o de contagem.

### 9. Plano da Priorização × recorte vivo — proposital (+ bug corrigido)
O plano é foto (mês, EGPs, `n_inputs_novos`); responsável, etapa/status e bloqueio são
sobrepostos ao vivo. 14/09/2026: funil por mês 193 × cards 194 (PERF_REVISIONAIS_RPA no
plano e fora do recorte). Plano 206 × lista 193 (30/09) resolvido pela poda na leitura.
**Corrigido em 06/10/2026:** os totais do mês e bloqueados/habilitados eram calculados
antes da poda (194 → 193). A pill de inputs da Priorização é viva.

### 10. Funil por área (DOR1) × cards — EGPs pela Linha de base desde 14/10/2026
A base conta a lista DOR1 ativa (`sas_escopo`, por situação de extração — inclui
"esperado não recebido"); dependências e ex-dependências contam pela classe gravada na
Linha de base, como o card. Até 14/10/2026 elas vinham do grafo vivo, e a dependência da
foto que saiu do recorte sumia da tabela: 192 × 193 (`Fechamento_Contabil_RPDD_3040`,
unificado num sucessor). Os extras ficam numa linha "Extras (à parte)": os EGPs fora
do total, como o "(+N extra)" do card; os inputs que só eles leem dentro, como no
Total de Inputs. Até 14/10/2026 esses inputs caíam numa linha "(sem área)" com 0 EGPs
(116: 103 só de extra e 13 famílias lidas pela base cuja maioria das safras só extra
lê — a família herdava a área pela moda das safras). A área principal é calculada
sobre escopo ∪ dependências e não enxerga extra — o publish não corrige. "(sem área)" que ainda aparecer é input
sem nenhum EGP com área no recorte.

### 11. Inputs por origem × card de inputs — corrigido
1.211 × 1.206 até 14/09/2026 (o JOIN partia do resumo e não do monitor). SAS/Local 1.735 ×
1.737 até julho (bucket de foto). Não modernizados do escopo 194 × "A ingerir" 205 até
14/10/2026: a família de safras agrega só as safras em vista, e a tabela do escopo não
via a safra pendente que só dependência/extra lê (11 famílias); o card já contava a
pendência no recorte ampliado. A tabela passou a contar igual.

### 12. Gestão de inputs × Visão geral — vínculo quebrado corrigido (09/10/2026); resta família
Até 09/10/2026 a Gestão (e o Kanban do Acompanhamento, mesmo endpoint) ignorava o vínculo
quebrado: mostrava input que nenhum EGP do recorte usa mais e listava no card o EGP
desvinculado — o que também mexia no filtro de Mês, herdado dos EGPs do card. Em prod: 54
cards em 06/10, 62 em 08/10 (cresce a cada desvinculação) e 53 cards com EGP desvinculado na
lista. Corrigido: a Gestão aplica a mesma régua de vínculo das contagens.

Medido com a correção sobre prod (09/10/2026): Gestão 673 × Visão geral 1.276.
1.276 = 673 + 596 + 1 + 6:
- **596** Sanitizados: a Gestão os tira de propósito (é fila de trabalho) — proposital.
- **1** input só de extra e Sanitizado — coberto pela régua do Sanitizado.
- **6** famílias cuja única safra pendente o recorte não usa mais — **inconsistência medida
  (regra a decidir)**. A Gestão filtra safra a safra (vínculo, Sanitizado) e só depois junta
  a família; a Visão junta todas as safras e decide sobre a família inteira. Em 5 delas a safra
  pendente só tem vínculo quebrado e as com vínculo ativo estão Sanitizadas (ex.:
  `THANRAR.MARCA_ELEGIBILIDADE`, `LDUARTE.BASE_PROTESTO_ANALIT`); em `CARD_ACR.CARTEIRA_CL`
  uma safra é sanitizada por derivação (`so_antecessor`) e a outra só é usada por
  ex-dependência. A Visão conta as 6 como pendentes; a Gestão, não.

### 13. Família × safra — proposital
Prod conta por família (escopo 2.446 linhas → 1.438 unidades em 22/09/2026). Seguem em
safra: aba Outputs, inputs do Tempo por Etapa, o app local e o grafo/linhagem. Antes de
18/09/2026 a Gestão tinha 1.608 cards × 754 unidades. Uma família está pendente se
**qualquer** safra está; o estado da família depende do recorte.

### 14. Inputs por sub-área — proposital
Não somam (1.615 na soma × 1.175 distintos): um input lido por EGPs de duas sub-áreas
conta nas duas.

### 15. "Total escopo" (aba Escopo) × 168 — proposital
A aba conta as entradas ativas da lista DOR1, incluindo não recebidos e cascas; o 168 é a
classe base da Linha de base.

### 16. Tempo por Etapa × contagens de etapa — proposital
Usa o Escopo vivo (sem dependências), a etapa/status **gravados** e a trilha de auditoria;
EGP nunca editado pelo app fica fora; dias "Em espera" são descontados.

### 17. Histórico — proposital
É um feed de eventos com no máximo 1.000 por fonte, não uma foto de estado nem a lista
completa.

### 18. Número que muda sem ninguém editar — proposital
Recorte, Ex-dependências e Sanitizado derivado mudam quando uma tabela é modernizada ou
sanitizada, ou num publish. Prod derivou +10 inputs em ~20 min sem edição. Para comparar
datas, compare com o retrato do dia, não com a memória.

### 19. Números que caem ou sobem depois de um publish — inconsistência medida (recorrente)
Re-key de chave no publish zera ou reverte estados até o reparo: planilhas `[SHEET=]` (834
chaves em 23/09/2026) e o `CPF_Contrato` v1→v2.
