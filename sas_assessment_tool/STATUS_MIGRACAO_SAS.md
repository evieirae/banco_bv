# Painel de Migração SAS → dbt — Status e Próximos Passos

> Documento de organização pessoal. Última atualização: **2026-06-11**.
> Escopo: módulo `egps_analysis/` (inventário e linhagem dos `.egp`/`.sas` antes da conversão).
> Objetivo final: ter a **linhagem completa** (dependências entre EGPs, entre SAS e EGP↔SAS) e as **métricas de monitoramento** da migração para BigQuery/Databricks via dbt.

---

## 1. Onde estamos (visão de 30s)

| Item | Estado |
|------|--------|
| EGPs consolidados em `egps_analysis/received_egps/` | ✅ **981 `.egp`** em 21 pastas (áreas + `SAS_UC4` + `Teste EGPs`) |
| Scripts SAS consolidados | ✅ **273 `.sas`** (SAS_UC4 232, campanha 20, pessoais/usuário 12, Rodas/Programas 2026 9) |
| `.sas`/`.txt` de usuários (SharePoint) | ✅ **triados e ingeridos** (§2.D); **root limpo** — refs→`docs/referencias_negocio/`, scratch→`docs/_arquivo_scratch_usuarios/` |
| Análise de duplicados entre áreas | ✅ feita → `duplicados_areas.csv` + `duplicados_quase_iguais_diff.md` |
| **Extração completa** (`text_egps/`) | ✅ **rodada e atualizada** — 1.732 `.txt` (inclui Rodas decomposto §2.G + Consulta_Carteira; 0 falhas) |
| **Relatórios de dependência** (03 matriz / 04 ondas) | ✅ **saneados 2026-06-11** — 16 ondas, **0 "ERRO ciclo"**; só 55 projetos marcados "Ciclo - quebrar manualmente" (ver §2.H) |
| Métricas de monitoramento | ✅ **revisadas 2026-06-12 (§2.J)** → `RELATORIO_METRICAS_MIGRACAO.md`. **Indicium 229 EGPs: 3.356 inputs distintos · 2.924 a ingerir** (das quais **2.070 tabelas**, 852 arquivos, 2 scripts) |
| Conferência Indicium (231) × extração | ✅ **229 confirmados · 1 recebido (a ingerir) · 1 faltante** (`ca_apagar_periodo`) → `indi_231_vs_extracao_06.csv` |

**Tradução:** insumos organizados **e** linhagem/métricas v1 geradas. O que falta agora é **saneamento** (dedup SHA256, ciclos artefatuais), **refinamento das ondas** (critérios operacionais) e os alinhamentos com as áreas (§5A).

---

## 2. O que já foi feito ✅

### A. Organização do repositório
- [x] Removidos todos os arquivos `Zone.Identifier`.
- [x] Criado `CLAUDE.md` (guia do monorepo para o agente).
- [x] **Consolidação**: ~960 `.egp` + ~160 `.zip` espalhados em pastas no root → movidos (MOVE) para `egps_analysis/received_egps/<área>/`.
  - Merges aplicados: `Cobrança → Cobranças`, `Operações e CX → Operações`.
  - `.zip` descompactados para eliminar EGP duplicado.
  - Manifestos de reversibilidade gerados: `egp_move_manifest.tsv`, `egp_unzip_manifest.tsv`, `egp_unzip2_manifest.tsv`, `sas_ingest_manifest.tsv`.
- [x] Pastas vazias removidas; confirmado que não sobrou `.zip`.
- [x] `campanha_SuperaBV.egp.zip` investigado → eram **20 `.sas` soltos**, não um EGP. Ingeridos em `received_egps/Rodas/sas_files/campanha_SuperaBV/`.
- [x] `SAS_UC4` (232 jobs agendados de produção) ingerido em `received_egps/SAS_UC4/` (flat).
- [x] Estrutura definida para `.sas` de projeto: `received_egps/<área>/sas_files/<projeto>/*.sas`.

### B. Código — auditoria e correções
- [x] **Code review** completo do `egps_analysis/` → `egps_analysis/docs/CODE_REVIEW.md` (achados P0/P1/P2).
- [x] **P0 corrigido** em `egps_analysis/orchestrator_inventory.py`: grafo de dependências agora usa `_canonical_table_key()` (normaliza maiúsculas/aspas/crase) nos 3 pontos do join — antes ligava tabelas por string exata e perdia arestas silenciosamente.
- [x] **`egps_extractor.py`** melhorado:
  - `PROJECT` agora é **qualificado por área** (`<área>__<nome>`) → fim da perda silenciosa por colisão de nome entre áreas.
  - Adicionado contador/resumo de execução (`RESUMO: escritos / falhas / colisões`).
  - Parou de usar `result.log` como fonte de caminhos/inventário (gerava lixo tipo `s 10`, `GC P`); mantido só como fallback de código.
  - Passou a ler a nova estrutura `<área>/sas_files/<projeto>/*.sas`.

### C. Análise de duplicados entre áreas
- [x] Cruzamento por nome + hash de conteúdo dos 981 EGPs.
  - **946 nomes distintos**; **35 nomes aparecem em ≥2 áreas**.
  - **11 idênticos** (byte-a-byte) · **13 quase-iguais** · **11 diferentes**.
- [x] Diff interno dos 13 quase-iguais → `duplicados_quase_iguais_diff.md`. Resultado: **6 são iguais de fato** (só log), **2 (Jur/Risc) Riscos é superset**, **5 são versões diferentes** (código real diverge).
- [x] Detectada **senha de banco Sybase em texto claro** dentro do `[Gestão_de_Carteira] Motores.egp` (redigida nos relatórios).

### D. Ingestão dos `.sas` de usuários (SharePoint) — 2026-06-10
- [x] Triados os 36 `.sas` + `.txt` que os usuários subiram nas pastas raiz (classificação em paralelo + dedup por hash).
- [x] **12 `.sas` pessoais** → `received_egps/<área>/sas_files/<usuário>/` (geovana, luciano, samara, juliana→**Operações**, Bruno Lage, beatriz).
- [x] **8 jobs de produção Rodas** (novos, não estavam no SAS_UC4) → `received_egps/Rodas/sas_files/Programas 2026/` (7 com saídas permanentes `BASEGRC.*`/`APPBV.*`).
- [x] **6 `.txt` que são código SAS** (henrique.campos, chang.fang) avaliados: criam só `WORK` / modelos EM → **não ingeridos** (critério acordado: só ingere se cria tabela permanente usável downstream).
- [x] 4 conflitos de versão Rodas×SAS_UC4 resolvidos a favor do **SAS_UC4** (exceto `tbprodutos`, pendente da área); 11 cópias idênticas ao SAS_UC4 ignoradas.
- Manifesto de reversão: `sas_user_ingest_manifest.tsv` (20 moves).
- ℹ️ `augusto.costa/Consulta_eventual.sas` (Crédito): **removido pelo usuário** — era só um `SELECT` ad-hoc, sem relevância para a migração.
- [x] **Root esvaziado** das pastas de projeto: 6 referências → `egps_analysis/docs/referencias_negocio/` (xlsx-fonte, mapa Doc3040, Acessos BD, Leia-me, 2 docs stored-process); 6 scratch (henrique/chang `.txt`) → `egps_analysis/docs/_arquivo_scratch_usuarios/`. Manifesto `leftovers_move_manifest.tsv`.
- [x] **Dedup Rodas** (lar canônico = `SAS_UC4`): 11 cópias idênticas deletadas, 3 conflitos → `docs/_arquivo_rodas_conflitos/`; `Rodas/sas_files/Programas 2026/` ficou com 8 novos + `tbprodutos`. Manifesto `rodas_dedup_manifest.tsv`. Resta 1 duplicação intencional: `tbprodutos` (Consignado) aguardando a área.
- [x] **`Cobrança/…/Projetos.xlsx`** extraído → `src/cobranca_projetos.csv` (1.508 projetos) + cruzamento `cobranca_projetos_x_egps.csv` (162 exatos, 129 variantes, 460 sem `.egp` no repo).

### F. Linhagem total + métricas + escopo Indicium — 2026-06-11

- [x] **Extração completa rodada** (1.255 `.txt`, 0 falhas) + **orchestrator** → reports 01–06 sobre **1.217 projetos** (1.942 arestas, 7.726 tabelas). PROJECT dos `.sas` qualificado por área antes da roda.
- [x] **Cruzamento × Plano de Projeto 2026** (consultoria): cobertura nominal 176/478 (acentos atrapalham o match); **os 282 "ciclo" do report 04 são majoritariamente ARTEFATO** — os 40 cíclicos que casam com o plano estão TODOS em ondas normais 1–6 lá (zero em onda final). Causas prováveis: 26 EGPs duplicados, agregação `Programas 2026` (9 jobs em 1 nó), falsos positivos do extrator.
- [x] **Escopo Indicium conferido** (231 da aba "Panorama inputs" × report 06): **225 extraídos**, 4 prováveis (Riscos), 2 faltantes → `docs/analises/indi_231_vs_extracao_06.csv`. **Update 2026-06-11:** área **confirmou os 4 prováveis** (1271=Pre-Contestacao · 1351=Estudo Revisionais · 1389=Project-v2 · DBEP.VWTBLCAUSACONSHIST=1040-Base_Unica_2); `Consulta_Carteira_New_Automatizada` **chegou** (7z, a ingerir). **Falta só 1: `ca_apagar_periodo`** (Cobrança).

### G. Pacotes 7z recebidos — 2026-06-11 (verificados, NÃO ingeridos)

- [x] **`Consulta_Carteira_New_Automatizada 1 1.7z`** → 1 `.egp` **novo** (era um dos 2 faltantes do Indicium). **Ingerido** em `received_egps/Cobranças/Consulta_Carteira_New_Automatizada.egp` + **extraído** (`text_egps/Cobranças__Consulta_Carteira_New_Automatizada.txt`, 3 inputs). Manifesto: `_manifests/egp_late_arrivals_manifest.tsv`. Entra nos reports na próxima roda do orchestrator.
- [x] **`migracao (2).7z`** verificado contra o inventário (por nome + SHA256): **665 arquivos** em **146 projetos** — é a pasta **Rodas** do SharePoint com os EGPs **decompostos em `.sas`** (+ 4 `.egp` binários).
  - **137 nomes já conhecidos** (em geral = `.egp` binário em `received_egps/Rodas/`), mas o **conteúdo é quase todo novo** (só 42 arquivos idênticos — ex.: `campanha_SuperaBV` 20/20 já ingerido) → são as **fontes `.sas` decompostas / versões mais novas** dos EGPs de Rodas.
  - **9 nomes novos**: `base_planejamento`, `BAse_DsLogin`, `Base_farol_solar`, `agent_space`, `Bases_Planejamento.egp`, `MisVarejo_GCP_TbPessoa`, `qualidadedevendas_cubo_estudo`, `qualidadedevendas_qdv-simu`, `qualidadedevendas_qdv-emprestimos`.
  - ⚠️ Os **3 conflitos antigos do dedup Rodas** (`tbvisaopdvs`, `tbrelatorioapnp`, `tbpotencialrodascomercial`) **voltaram com versão ≠ do SAS_UC4** (diffs de 27–96 linhas) — reabrir a decisão de qual é canônico.
  - `ca_apagar_periodo` **não veio** em nenhum dos pacotes.
  - ✅ **EXECUTADO o plano (b) com validações (2026-06-11):**
    - Achado-chave: **115/149 `.egp` binários de Rodas eram cascas vazias** (LOC=0, sem I/O) — o código sempre viveu nos `.sas` decompostos.
    - Validação de cobertura (I/O do binário ⊆ I/O da fonte): **110 SUBSTITUIR** · 9 novos · **1 MANTER_AMBOS** (`rito_comercial_solar`: binário tem outputs `ONESOLAR.*` não cobertos — revisar).
    - 590 `.sas` ingeridos em `Rodas/sas_files/<projeto>/` (achatados, `Old/` excluído); **110 binários arquivados** em `docs/_arquivo_rodas_egp_binarios/`; 110 `.txt` órfãos removidos; re-extração (610 txts, 0 falhas). Manifesto: `_manifests/rodas_decomposed_ingest_manifest.tsv` (707 linhas).
    - 3 variantes de conflito preservadas em `docs/_arquivo_rodas_conflitos/*__sharepoint_20260611.sas` — **pergunta à área Rodas pendente** (qual versão vigente: SharePoint ou UC4?).
    - Reports 01–06 + métricas **regenerados**: base completa **1.207 projetos com I/O**; Indicium **229** — ver números canônicos revisados em **§2.J (2026-06-12)**. Ondas: 623/139/71/41/12/22/9/4 + **306 ciclo** (saneamento pendente).
- [x] **Inputs distintos do escopo Indicium** — ⚠️ versão da aba "Extração Bruta oficial" (planilha, `build_lineage.py`) deu 2.071 tabelas + 879 arquivos a ingerir. **SUPERSEDED pela fonte canônica (pipeline 06 + indi_231)** — ver **§2.J (2026-06-12)**. `indicium_inputs_distintos.csv` foi **regenerado a partir do pipeline** (3 categorias de input).
- [x] **Linhagem visual interativa** (HTML, vis-network) → `docs/analises/lineage_indicium.html` + `build_lineage.py`. ⚠️ **SUPERSEDED pelo app** (`monitoramento-sas`, aba Linhagem em **Cytoscape.js + fCoSE**, colapsado por área) — o HTML legado lê da planilha e diverge do pipeline; manter só como histórico.
- [x] **Relatório de métricas v1** → `docs/analises/RELATORIO_METRICAS_MIGRACAO.md` + gerador `build_metrics_report.py`. Números atuais reescritos na **§2.J (2026-06-12)** — o relatório agora distingue **inputs (table_in+file_in+script_in)** de **tabelas (table_in)**.

### H. Saneamento dos ciclos — 2026-06-11

Diagnóstico: dos 306 "ERRO ciclo", só **69 estavam em ciclo de verdade** (16 SCCs); 237 eram apenas **jusante** de ciclo. Causas das arestas de ciclo: 62 tabela multi-escritor, 14 placeholder de macro, 13+ duplicados cross-área, resto cadeias reais.

**Correções no `orchestrator_inventory.py`** (CRLF preservado, py_compile OK):
1. **Bug de agregação corrigido**: projetos multi-arquivo (`sas_files/<proj>/*.sas`) **sobrescreviam** o I/O no `project_catalog` (só o último `.sas` contava) → agora **união** de inputs/outputs/exports. Ficou crítico com Rodas decomposto.
2. **Regra placeholder**: tabela com macro não-resolvida (`&VAR`, `{…}`) não entra no grafo de dependências.
3. **Regra leitor-também-escreve**: se o projeto lê uma tabela que ele mesmo escreve, não é produtor→consumidor (tabela compartilhada/append) → sem aresta.
4. **Ondas por condensação de SCC (Tarjan)**: membros de ciclo recebem a onda do componente rotulada **"(Ciclo - quebrar manualmente)"** e **não bloqueiam o jusante** (critério da consultoria: ciclo→atenção, não trava o plano).

**Saneamento de dados** (manifesto `_manifests/saneamento_ciclos_manifest.tsv`):
- `Programas 2026` separado: 9 jobs movidos para `Rodas/sas_files/` raiz (1 nó por job; antes 9 jobs num nó).
- 11 txts de cópias **byte-idênticas cross-área** excluídos (→ `_excluded_text_egps/`; canônico = 1ª área alfabética).

**Resultado:** **0 "ERRO ciclo"** · 1.224 projetos todos com onda (16 ondas; cadeias mais longas reveladas pela correção do merge) · só **55 projetos** marcados "Ciclo - quebrar manualmente" (ecossistemas reais de retroalimentação: hub Atacado/Crédito via `INSIGHT.TBBRUTA`/`PLCA.TBSISTEMAPLCA`, Cobranças `CONTATOS.*`, SAS_UC4 `TMP.*`).

**Catálogo de evidências dos ciclos — 2026-06-12** → `docs/analises/DEPENDENCIAS_CICLICAS.md` (gerador: SCC de Tarjan sobre o 03 + investigação/verificação multiagente). **13 clusters cíclicos · 57 projetos · 127 arestas internas**. Após verificação adversarial (todos alta confiança, 0 discordâncias): **4 ciclos REAIS** (#4 Crédito, #7 Finanças, #10 Riscos, #13 Rodas — pequenos, quebra manual) · **8 artefatos parciais** · **1 artefato total** (#8). Causa-raiz dominante: tabelas de **schemas corporativos compartilhados** (`INSIGHT.`/`PME.`/`PLCA.`/`SHAREATA.`/`MISCRED.`) lidas e regravadas por vários projetos (read-modify-write) — viram ciclo no grafo mas são **fontes comuns**; externalizá-las como `source` única no dbt desfaz a maioria dos ciclos. Tabela-raiz: `INSIGHT.TBBRUTA` (5 escritores/16 leitores) costura o cluster #1 (16 projetos). Evidência completa (toda aresta + tabela + writers/readers) em `_manifests/ciclos_clusters.json`; vereditos em `_manifests/ciclos_workflow_result.json`.

### I. Dependência por `.sas7bdat` (dataset SAS lido = output de EGP) — 2026-06-12

Pergunta: um `.sas7bdat` lido por um EGP, se for **escrito** por outro, é dependência interna (não ingestão). Implementado match no `orchestrator_inventory.py`: basename do `.sas7bdat` em `files_read` × **membro** de um `table_out`, com **guards** (len≥6, não-genérico, **≤3 produtores**, produtor≠consumidor).

- Dos 255 `.sas7bdat` distintos: ~40 são escritos por algum EGP, mas a maioria são **nomes de trabalho reusados** (`CARTEIRA_CA`=10 produtores, `TBORIGINACAO`=15, `FUNIL_LEVES`=5) → ambíguos, **não** viram aresta (evita arestas falsas/ciclos). Isso é um achado de **colisão de nomes** a desambiguar com as áreas.
- **5 arestas limpas** (1 produtor) adicionadas → report 03 (1.871→1.876) e `sas_lineage_edges` (1.514→1.519). Todas **Rodas/SAS_UC4** (fora do escopo Indicium-231), ex.: `precoxrisco`→`funil_pricing_*` via `ppr_analitico.sas7bdat`, `campanha_ativabv`→`tbmetaproducao` via `tbpotencialrodas.sas7bdat`. ⇒ o grafo Indicium-231 não muda; aparecem na linhagem da base completa.
- Reports + métricas + Delta re-publicados (`client_journey.monitoramento_sas`).
- [ ] *(opcional)* marcar no app os `.sas7bdat` produzidos internamente como "Interno" (saem de "a ingerir") — coluna `produzido_internamente`.

### J. Revisão dos inputs do escopo Indicium (número p/ o BV) — 2026-06-12

Objetivo: número defensável de **inputs a ingerir** dos EGPs Indicium. Fonte canônica agora é o **pipeline** (`06_prontidao_tabela.csv` + `indi_231_vs_extracao_06.csv`); a versão da planilha (`build_lineage.py`) e o HTML vis-network ficam como histórico (divergiam por escopo/metodologia).

**Definição (importante, não confundir):**
- **Input** = `table_in` + `file_in` + `script_in` (as 3 categorias). É o que se diz ao falar de **ingestão de inputs**.
- **Tabela** = só `table_in` — um **subconjunto** dos inputs. "Ingestão de tabelas" ≠ "ingestão de inputs".
- `libname_in` **não** conta (libref sozinho não é dado); ruído excluído: `WORK./DICTIONARY./SASHELP./SASUSER.`, placeholders de macro (`{}`,`&`), `.sas7bdat` sem libname.
- **A ingerir** = input cujo `status_validacao` não indica presença no BigQuery em nenhum projeto.

**Reconciliação do escopo:** lista tem **231**; − 1 ainda não recebido (`ca_apagar_periodo`) − 1 item duplicado (`1353` listado 2×) = **229 EGPs distintos**, todos com I/O. Corrigidos 2 mapeamentos defasados no `indi_231_vs_extracao_06.csv` (`SAS_IQ_SQ_Vigente`→`__v3`; `taxas_v35 (2)`→área `Banco Relacional`) — antes o relatório oscilava 227↔229.

**Números canônicos (229 EGPs):**

| Categoria | distintos | **a ingerir** | disponíveis (BQ) |
|---|---:|---:|---:|
| **INPUTS** (tab+arq+script) | **3.356** | **2.924** | 432 |
| ↳ tabelas (`table_in`) | 2.502 | 2.070 | 432 |
| ↳ arquivos (`file_in`) | 852 | 852 | 0 |
| ↳ scripts (`script_in`) | 2 | 2 | 0 |

**Propagado:**
- `indi_231_vs_extracao_06.csv` corrigido (229); `RELATORIO_METRICAS_MIGRACAO.md` regenerado (distingue inputs × tabelas); `indicium_inputs_distintos.csv` regenerado do pipeline (3.356 linhas, com `modernizada`/`areas`).
- `publish_to_databricks.py`: novas métricas `inputs_a_ingerir`/`inputs_disponiveis`. **Delta republicada** em `client_journey.monitoramento_sas` (MERGE preservou colunas humanas).
- App (`monitoramento-sas`): card **"Inputs a ingerir (2.924)"** liderando, tabelas como subconjunto. **Deploy SUCCEEDED.**

---

## 3. Decisões que você tomou (úteis pro texto do Slack)

- Consolidação por **MOVE** (destrutivo), não cópia — com manifestos pra reverter.
- Incluir os conjuntos "curados" e mesclar Cobrança/Cobranças e Operações/Operações e CX.
- **SAS_UC4 fica flat** (1 projeto por `.sas`), por serem jobs agendados independentes.
- `.sas` de projeto vão para subpasta `sas_files/<projeto>/` dentro da área.
- Na correção do extrator: aplicar **qualificação por área no PROJECT** e **resumo de execução**, mas **não** mexer (ainda) em redação de credenciais.

---

## 4. Dúvidas / pontos em aberto encontrados (úteis pro Slack)

1. **Mesmo nome em áreas diferentes ≠ mesmo arquivo.** Dos 35 casos, só 11 são idênticos. Como as áreas querem tratar os EGPs compartilhados (quem é o dono, migra uma vez?).
2. **Versões divergentes** entre áreas irmãs (Jurídico↔Riscos, Atacado↔Crédito): em casos como **Motores** e **GeraBaseOperacoesPLRC** o código é genuinamente diferente — **qual é a versão de produção?**
3. **Credenciais em texto claro** dentro dos `.egp` (ex.: senha Sybase no Motores). Precisa de política de segredos na migração + rotacionar o que está exposto.
4. **`.sas` soltos** (37 no root + os de projeto): quais são produção e quais são rascunho/pessoal? Só os de produção entram na linhagem/migração.
5. **Falsos positivos do extrator** (documentados, não corrigidos): outputs "fantasma" a partir de tabelas `WORK` e classificação errada por nome de macro — inflam o inventário de outputs.
6. **Inconsistência de identidade**: os `.egp` têm `PROJECT = <área>__<nome>`, mas os `.sas` ainda **não são qualificados por área** — precisa alinhar antes de gerar a linhagem confiável.

---

## 5. O que falta — separado por responsável

### 5A. 🧑 Precisa de VOCÊ (decisão / alinhamento / acesso)

- [ ] **Alinhar os 35 duplicados com as áreas** — priorize os pares que concentram tudo:
  - [ ] **Jurídico ↔ Riscos** (13 casos): confirmar dono; nos 2 "superset" usar a cópia de **Riscos**.
  - [ ] **Atacado ↔ Crédito** (8 casos): decidir versão viva de **Motores** e **GeraBaseOperacoesPLRC** (código diverge de verdade).
  - [ ] **NT Varejo ↔ Planejamento e P&L (Rodas)** (7 casos, quase todos idênticos): definir área dona.
  - [ ] Demais pares (Cobranças/NT Varejo, Seguros, Banco Relacional/Cartões).
  - *Material pronto pra mandar:* `egps_analysis/docs/analises/duplicados_areas.csv` (caminho + hash de cada cópia) e `duplicados_quase_iguais_diff.md` (o que muda em cada um).
- [x] ~~Decidir o destino dos `.sas` soltos no root~~ — **feito** (§2.D): 12 pessoais + 8 Rodas ingeridos; 6 `.txt` só-`WORK` ficaram fora. Resta cobrar:
  - [ ] `tbprodutos`: a área confirma se o produto **'Consignado'** entra (versão Programas 2026) ou não (SAS_UC4 atual).
  - [ ] `joao.neves2`: subiu só a **documentação** (`.docx`) dos stored processes — pedir o código real.
- [x] ~~Decidir o destino do `migracao (2).7z`~~ — **plano (b) executado com validações** (§2.G). Restam 2 perguntas à área Rodas:
  - **3 conflitos**: `tbvisaopdvs`, `tbrelatorioapnp`, `tbpotencialrodascomercial` — SharePoint diverge do UC4; qual versão é a vigente? (variantes preservadas em `docs/_arquivo_rodas_conflitos/*__sharepoint_20260611.sas`)
  - **`rito_comercial_solar`**: binário tem outputs `ONESOLAR.*` que os `.sas` decompostos não cobrem — falta código no SharePoint?
- [ ] **Cobrar o último EGP faltante do Indicium**: `ca_apagar_periodo` (Cobrança Varejo) — não veio nos 7z.
- [ ] **Credenciais**: rotacionar a senha Sybase exposta no Motores e definir como segredos serão tratados na migração.
- [ ] **Acesso GCP (ADC)**: garantir `gcloud auth application-default login` para quando formos atualizar o `src/chameleon.csv` (passo 2 da pipeline).
- [ ] **Commit das mudanças**: `egps_extractor.py` e `orchestrator_inventory.py` estão alterados e **não commitados** — decidir quando versionar (o agente não faz commit/push por política).

### 5B. 🤖 Eu executo quando você mandar (mecânico, sem decisão sua)

- [ ] **Adicionar `EGP_SHA256` ao header do extrator** → chave canônica de "EGP distinto"; habilita dedup dos 26 redundantes e limpa parte dos ciclos artefatuais. *(próximo saneamento)*
- [x] ~~Qualificar o `PROJECT` dos `.sas` por área~~ — **feito** (2026-06-10).
- [x] ~~Rodar a extração completa~~ — **feito** (§2.F): 1.255 `.txt`, 0 falhas.
- [x] ~~Rodar o orchestrator~~ — **feito** (§2.F): reports 01–06 = linhagem total (b).
- [x] ~~Sanear os "ciclo" do report 04~~ — **feito** (§2.H): 0 "ERRO ciclo"; 55 marcados "(Ciclo - quebrar manualmente)" dentro das ondas.
- [x] ~~Separar `Programas 2026` por job~~ — **feito** (§2.H): 9 jobs = 9 nós.
- [x] **Linhagem explorável no Neo4j** — adotado o kit `~/bv/sas_assessment_tool/sas_neo4j_setup` (Docker + Cypher data-driven). Gerador novo: `docs/analises/build_neo4j_modelagem.py` (reports 03+06 saneados → `modelagem_bv.csv`): **31.447 nós** (1.202 EgpProject · 25.068 LibnameSource · 4.802 ExternalSource · 375 IncludeFiles) e **58.261 arestas** (READS_FROM 23.332 · WRITES_TO 32.217 · DEPENDS_ON 2.712). Browser: `http://localhost:7474`. Substitui a ideia do Sankey: exploração por consulta resolve a poluição visual.
- [ ] *(opcional)* **Sankey executivo** (Origem→Schema→Área) para apresentação — o Neo4j cobre a exploração; o Sankey seria só visão de slide.
- [ ] **Ingerir a telemetria de execução** (Frequência, Última Execução, Execuções) do *Plano de Projeto 2026* → enriquecer report 06 e priorizar ondas; sinaliza jobs mortos. Ver **§9.2**.
- [ ] **Implementar os critérios de onda no report 04** (precedência, ingestão just-in-time, ciclo→Onda Final, autonomia-primeiro, máx 2 áreas/onda, 40–50/onda, resgate de sanitização, complexidade→Final) — sair do topo-sort puro. Spec na **§9.2**.
- [ ] **Gerar o Panorama automaticamente** — **parcialmente atendido** pelo `build_metrics_report.py` (§2.F): já produz projetos/inputs únicos/a-ingerir por área nas 2 visões. Falta: EGPs enviados/pendentes por área e % conclusão no formato da planilha. Ver **§9**.
- [ ] **Unificar as colunas de enriquecimento no report 06** (`migration_pattern`, `attention_use_chameleon_bq_not_repmap`, `chameleon_matches_short`, `Status Transacional`) — hoje coladas de 3 fontes na planilha. Ver **§9**.
- [x] ~~Construir as métricas de monitoramento (v1)~~ — **feito** (§2.F): `RELATORIO_METRICAS_MIGRACAO.md` (EGPs/inputs/outputs únicos, modernização, intermediárias, compartilhados, por área, 2 visões). Evoluções ficam no item Panorama acima.
- [ ] *(opcional)* **Scan de credenciais** em texto claro nos 981 EGPs.
- [ ] *(opcional)* **Corrigir os falsos positivos** do extrator (outputs fantasma de `WORK`, classificação por macro).

---

## 6. Sequência recomendada (ordem de execução)

```
  [5B] add EGP_SHA256  ─┐
  [5B] qualificar PROJECT dos .sas  ─┤
                                     ├─► [5B] extração completa → text_egps/
  [5A] (em paralelo) alinhar          │
       áreas + triar .sas soltos ─────┘
                                          │
        (atualizar src/chameleon.csv via export GCP — passo 2) ──► precisa rodar ANTES do orchestrator
                                          ▼
                          [5B] orchestrator → 03 matriz + 04 ondas  (= linhagem total / "b")
                                          ▼
                          [5B] métricas de monitoramento
                                          ▼
        (cruzamentos extras: 06_table_in_vs_repmap → migration_hints, usam src/RepMap.xlsx)
```

**Regras de ordem da pipeline (do CLAUDE.md):**
- `src/chameleon.csv` deve refletir o BigQuery atual → **export GCP (passo 2) roda ANTES do orchestrator (passo 3)**.
- Os cruzamentos 4/5 (`validate_table_in_vs_repmap.py`, `migration_hints_...py`) precisam de `src/RepMap.xlsx`.

---

## 7. Mapa de arquivos (insumos e artefatos)

| Arquivo | O que é |
|---------|---------|
| `egps_analysis/egps_extractor.py` | Extrator `.egp`/`.sas` → `.txt` (metadados + inventário I/O). **Alterado, não commitado.** |
| `egps_analysis/orchestrator_inventory.py` | Monta grafo de dependências e ondas (03/04). **Alterado, não commitado.** |
| `egps_analysis/received_egps/` | 981 `.egp` + 273 `.sas`, organizados por área. |
| `egps_analysis/text_egps/` | ✅ 1.251 `.txt` da extração completa (4 `Teste EGPs` em `_excluded_text_egps/`). |
| `egps_analysis/01..06_*.csv` | Reports do orchestrator (linhagem/ondas/prontidão) sobre 1.217 projetos. |
| `egps_analysis/src/chameleon.csv` | Catálogo de ingestões BigQuery (gerar/atualizar via export GCP). |
| `egps_analysis/src/RepMap.xlsx` | Mapa de replicação (insumo dos cruzamentos 4/5). |
| `egps_analysis/src/inventario_transacional.csv` | Inventário corporativo (insumo de referência). |
| `egps_analysis/src/cobranca_projetos.csv` | Registro de projetos da Cobrança (dono/status/área), extraído do xlsx (insumo). |
| `egps_analysis/docs/referencias_negocio/` · `docs/_arquivo_*` | Referências de negócio + scratch/conflitos arquivados (não-migráveis). |
| `egps_analysis/docs/CODE_REVIEW.md` | Review técnico do módulo (P0/P1/P2). |
| `egps_analysis/docs/README.md` | Explica os manifestos e as pastas de `docs/` (o que são, pra que servem, por quê). |
| `egps_analysis/docs/analises/` | Análises: `duplicados_areas.csv`, `duplicados_egp.txt`, `cobranca_projetos_x_egps.csv`. |
| `duplicados_quase_iguais_diff.md` (root) | Diff interno dos 13 quase-iguais (credenciais redigidas). |
| `egps_analysis/_manifests/*.tsv` | Manifestos de reversão (egp_move, egp_unzip×2, sas_ingest, sas_user_ingest, leftovers_move, rodas_dedup). |

---

## 8. Glossário rápido

- **EGP** — projeto SAS Enterprise Guide (ZIP de XML + código). Unidade a migrar.
- **PROJECT qualificado** — identidade `<área>__<nome>` que evita colisão entre áreas.
- **Linhagem / ondas (03/04)** — quem lê o quê (matriz) e em que ordem migrar (ordenação topológica = "ondas").
- **chameleon** — catálogo das tabelas já ingeridas no BigQuery (pra saber o que já existe no destino).
- **RepMap** — mapa de replicação corporativo (origem → destino das tabelas).

---

## 9. Fontes de negócio externas (planilhas)

Duas planilhas de negócio espelham/complementam o pipeline. **Meta:** o **pipeline é o motor** (linhagem/ondas/métricas reproduzíveis); as planilhas — e depois um **app** — são as visões. As 3 visões (pipeline 981 EGPs · §9.1 Controle 228 ativos · §9.2 Plano de Projeto) precisam convergir para **uma fonte de verdade**.

### 9.1 — Controle e Validação (Pré-Working)

**Planilha:** `[SAS] 1. Pré-Working - Controle e Validação` (Google Drive, dona: lucas.muller@indicium.tech) — `fileId 1sKvIn_SrGFJfycvsW7RrgsBsuXXZ3lp_` · [abrir](https://drive.google.com/file/d/1sKvIn_SrGFJfycvsW7RrgsBsuXXZ3lp_/view). É o **painel de controle de negócio da migração**; boa parte das abas é **alimentada (copiada) das saídas do nosso pipeline**. Objetivo declarado: virar um **app** depois.

### Mapa aba ↔ artefato do pipeline

| Aba da planilha | O que é | Equivalente em `egps_analysis` |
|---|---|---|
| **Panorama - Controle** | dashboard por área (EGPs enviados/analisados/pendentes, **inputs não modernizados**, % conclusão, metas) | **derivável** de `received_egps` + report 06 (group by área) = a **métrica do (b)** |
| **PW - Projeto SAS** | 1 linha/projeto: status, responsável (Consultoria/Área/Sanitizar), **EGP disponível?**, nº inputs, Revisão EGP vs OFICIAL | reports 01/02/05 + `src/cobranca_projetos.csv`; é o **workflow de migração** |
| **Extração Bruta EGPS** | 1 linha/artefato (I/O, paths, Chameleon) + colunas manuais | **= `06_prontidao_tabela.csv`** (cabeçalho idêntico) + `migration_hints` + anotação humana |
| **SYBASE Replicas** | tabelas × RepMap ASE→IQ × Chameleon | `migration_hints_table_in_repmap_chameleon.py` / `validate_table_in_vs_repmap.py` |
| **LIBs SAS** | libnames (engine + path) | `DETECTED_LIBNAMES` do extrator |
| **TARGET_ARCH** | arquitetura de saída por EGP | `TARGET_ARCH` do extrator |

Cabeçalho da **"Extração Bruta"** = `project, file_sas, area, artifact, path, category, source_type, status_validacao, chameleon_*(5), project_extension, created_at, target_arch` (idêntico ao report 06) **+** manuais/derivadas: `Modernizada?, Status Transacional, migration_pattern, attention_use_chameleon_bq_not_repmap, chameleon_matches_short, Observações Fabricio, Responsável Time BV, Status`.

### Reconciliação de escopo
A planilha controla **~228 EGPs** ("confirmados para consultoria", de 231 Indicium); o repo tem **981** em `received_egps` (todas as áreas + conjuntos curados). Falta cruzar **quais dos 981 estão nos 228 ativos** — já iniciado para Cobrança em `docs/analises/cobranca_projetos_x_egps.csv`.

### Plano (encurta o caminho até o app)
1. **Panorama automático** a partir de `received_egps` + report 06 — fim do count manual. *(§5B)*
2. **Unificar enriquecimento no report 06** (`migration_pattern`, `attention_*`, `chameleon_matches_short`, `Status Transacional`) — a planilha vira *refresh* de 1 CSV, não cópia de 3 fontes. *(§5B)*
3. **App** (depois): entidades = Projeto (PW) · Artefato (report 06) · Libname (LIBs) · rollup Área (Panorama). O **pipeline alimenta os dados**; o humano edita só status/responsável/observação. Resolve a fragilidade do xlsx de 11.8MB feito por copia-cola.

### 9.2 — Plano de Projeto 2026 (ondas + telemetria)

**Planilha:** `[Migração SAS] Plano de Projeto 2026` (Google Drive, compartilhada) — `fileId 1H1qAcyYpO7_-N0hAHc8zxYENnghGlLCmymUWC9LgIvc` · [abrir](https://docs.google.com/spreadsheets/d/1H1qAcyYpO7_-N0hAHc8zxYENnghGlLCmymUWC9LgIvc/edit). É o **plano de migração da consultoria** — já tem linhagem + ondas + capacity, e dados que o pipeline **não** extrai do `.egp` estático.

| Aba/tabela | Colunas-chave | Equivalente no pipeline |
|---|---|---|
| Roadmap projetos | Projeto, Onda, Área, Responsável SAS, Autônomo?, Projetos dependentes, Projetos habilitadores, Frequência, Execuções | report 03 + 04 |
| Roadmap tabelas | Tabela, Onda, Áreas, Projetos habilitados, Path, Responsável Ingestão, Deadline | report 01 + ondas |
| Linhagem de dados | table_name, area, estrategia, projects_names, waves, path, category, count_table_read, nm_dataset, dominio_de_tabela | report 01/06 |
| Inventário reduzido | qty_tables, qty_modernized, qty_bigquery/sybaseiq/sybase/postgres/sqlsrv, pct_modernized | derivável do report 06 |
| Pré-Working (inventário) | + telemetria de execução, shell scripts, sanitização, classificação | parcial |
| Capacity / Frentes / Deadlines | pessoas, dias úteis, ondas, datas, deadline por área | não temos |

**O que ela tem e o pipeline não tem (mais útil):**
- ⭐ **Telemetria de execução** (`Frequência`, `Primeira/Última Execução`, `Execuções`, `Ocorrências`) — vem do **UC4/Automic**, não do `.egp`. Sinal-chave de priorização (migrar o que roda diário/recente; **descartar o que não roda há meses**).
- **Critérios de onda documentados** (precedência habilitador→dependente, ingestão just-in-time, ciclo→Onda Final, autonomia-primeiro, máx 2 áreas/onda, 40–50 projetos/onda, resgate de sanitização, complexidade→Onda Final) — **spec** para o report 04 (hoje só topo-sort técnico).
- **Classificação** (Potencial de Sanitização, Finalidade ETL/ML, shell scripts) e **capacity/cronograma** (pessoas, dias úteis, deadlines por área/onda).

**Usar como validação:** ao rodar a extração completa + orchestrator, cruzar nossas ondas/dependências computadas × este plano manual — cada divergência é um bug em um dos dois.

---

## 10. App "Painel de Modernização SAS" (decidido em 2026-06-12)

**Produto:** app interno (Indicium: analista + técnico) para **monitorar a modernização dos inputs** da migração, com métricas automáticas do pipeline e uma página de **linhagem estilo catálogo** (só projeto→projeto, sem estrutura interna dos EGPs). Substitui as abas manuais da planilha de Controle. **Neo4j descartado** (containers parados; fica como ferramenta interna).

### Decisões (grilling 2026-06-12)

| # | Tema | Decisão |
|---|---|---|
| 1 | Usuários | Indicium (analista de projetos + time técnico) |
| 2 | Backend de estado | **Databricks** (Delta) — `bv_dev_db.dev_lucas_muller` |
| 3 | Stack do app | **Databricks Apps** |
| 4 | Refresh | passo **publish** no fim do pipeline local (`publish_to_databricks.py`) |
| 5 | Grão da tela | **1 linha = input distinto** (tabela/arquivo/script), expande p/ projetos consumidores |
| 6 | População | base completa + flag `escopo_indi`; app abre filtrado no escopo Indicium |
| 7 | Status | **humano sempre ganha**; `modernizada_auto` (chameleon) é informativo + indicador de divergência |
| 8 | Linhagem | página separada no mesmo app; nó rico (cor=área, badge=onda) + aresta com "via tabelas"; expande 1 nível |
| 9 | Chaves | nome canônico + **aba de órfãos** p/ reconciliar edições após renomeação |
| 10 | Arquivos/scripts | incluídos como **categoria filtrável** (padrão: tabela) |
| 11 | MVP | ✅ **inc.1** (publish+Delta) **FEITO**; ✅ **inc.2** (página de monitoramento, React/TS+FastAPI) **FEITO**; **inc.3**: linhagem |
| 12 | Front | **React + TypeScript (Vite)** + tabela virtualizada — **não Streamlit** (decisão 2026-06-12) |

### Modelo de dados (Delta em `bv_dev_db.dev_lucas_muller`)

- `sas_inputs_monitor` — grão input distinto; colunas do pipeline (refresh) + **humanas preservadas no MERGE** (`status_humano, responsavel, observacao, updated_*`); `orfao` p/ reconciliação.
- `sas_lineage_edges` — projeto_alvo → depende_do (+ via_tabelas) — full replace.
- `sas_lineage_nodes` — projeto: área, onda, n_inputs, n_outputs, escopo — full replace.
- `sas_pipeline_metrics` — snapshot por refresh (histórico de progresso).

### Incremento 1 — estado

- [x] **`egps_analysis/publish_to_databricks.py`** escrito (idempotente; `--dry-run` default, `--apply` escreve; MERGE preserva colunas humanas; marca órfãos).
- [x] **Dry-run validado**: 11.969 inputs (3.501 Indicium; 6.352 tabelas a ingerir) · 1.514 arestas · 1.205 nós · 12 métricas. Preview SQL em `docs/analises/publish_databricks.preview.sql`.
- [x] **APLICADO no Databricks (2026-06-12)** — host `dbc-5626df64-1b10.cloud.databricks.com`, warehouse `indimesh-aws-bv-default-sql-wh` (`ecc2a5699da67093`). 4 tabelas criadas e populadas em `bv_dev_db.dev_lucas_muller`: `sas_inputs_monitor` (11.969) · `sas_lineage_edges` (1.514) · `sas_lineage_nodes` (1.205) · `sas_pipeline_metrics` (12). Colunas humanas existem e MERGE preserva.
- ⚠️ `DATABRICKS_HOST` e `DATABRICKS_DEFAULT_WAREHOUSE_ID` **continuam vazios no `.env`** — passei via `export` no comando. Para persistir, preencher no `.env` (e converter CRLF→LF). Indicium: 2.068 tabelas a ingerir · 431 disponíveis · 841 arquivos · 159 libs.

**Rodar o publish** (após preencher o `.env`):
```bash
cd converter && set -a && source <(tr -d '\r' < .env) && set +a && cd .. \
  && egps_analysis/venv/bin/python egps_analysis/publish_to_databricks.py --apply
```

### Incremento 2 — página de monitoramento ✅ (2026-06-12)

App em **`egps_analysis/app/`** — **React + TypeScript (Vite)** + **FastAPI** (servido como **Databricks App**), substituindo a ideia do Streamlit por algo mais otimizado (tabela virtualizada, sem re-render total).

- **Backend** (`app/backend/main.py`): API JSON sobre as Delta via `databricks-sdk` (auto-auth no App; host/token em dev local). Rotas: `/api/{health,me,config,metrics,inputs}` + `PATCH /api/inputs`. Filtros server-side (escopo, categoria, modernização, status, busca, divergência, órfãos). Escrita valida status e grava `updated_at/updated_by=current_user()`.
- **Frontend** (`app/frontend/`): cards de métricas, barra de filtros, tabela virtualizada (`@tanstack/react-virtual`) com edição inline de `status_humano`/`responsavel`/`observacao` (otimista), badge de **divergência** humano×auto e de **órfão**. Bundle em `app/static/` (56 KB gzip).
- **Status workflow**: A ingerir → Em análise → Em ingestão → Disponível (+ Sanitizada/Descartada). **Humano sempre prevalece**; auto é informativo.
- **Verificado** local (TestClient) contra o warehouse: health/config/me OK, métricas (3.501 inputs Indicium · 2.068 a ingerir · 17,2% modernizado), filtro (2.068 linhas, topo `DBA.TBPROPOSTA`=90 proj.), **PATCH grava e reverte** na Delta. ✅
- **Deploy** (instruções em `app/README.md`): `npm run build` → `databricks sync` → `databricks apps deploy`. Conceder ao service principal do app `SELECT/MODIFY` em `bv_dev_db.dev_lucas_muller` + `CAN USE` no warehouse `ecc2a5699da67093`.
- [x] **DEPLOYADO (2026-06-12)** no app **`monitoramento-sas`** (reusei o existente): `databricks sync` + `databricks apps deploy --mode SNAPSHOT` → **state SUCCEEDED, compute ACTIVE**. URL: `https://monitoramento-sas-4394921022945130.aws.databricksapps.com`.
- [x] **Grants ao service principal do app** (`5b524c4c-c116-4de7-b414-01f719e49d0d` = "app-3a6zfb monitoramento-sas"): ✅ `USE SCHEMA`+`SELECT`+`MODIFY` em `bv_dev_db.dev_lucas_muller`; ✅ `CAN_USE` no warehouse `ecc2a5699da67093`.
- [x] **Destino movido para `client_journey.monitoramento_sas`** (2026-06-12) — onde tenho permissão de catálogo. Republicado (mesmas 4 tabelas/contagens), `app.yaml` atualizado, **re-sync + redeploy SUCCEEDED**. Grants ao SP **todos OK incluindo `USE CATALOG`** → o bloqueio anterior do `bv_dev_db` **deixou de existir**. (As tabelas em `bv_dev_db.dev_lucas_muller` ficaram órfãs — podem ser dropadas.)
- [ ] **Validar na UI** (browser, atrás do OAuth do app): abrir a URL e confirmar que métricas/tabela carregam com o SP já liberado.
- [x] **Incremento 3 — página de linhagem ✅ (2026-06-12)**: nova aba **Linhagem** no app (vis-network). Nó = caixa colorida por área + rótulo com onda; aresta = produtor→consumidor com **tabelas no hover** (via). Lê `sas_lineage_edges`/`sas_lineage_nodes`. **Redeploy SUCCEEDED**, endpoints verificados (TestClient).
  - **2 modos** (`/api/lineage/graph`): **Por EGP** (dropdown de EGPs + duplo-clique expande 1 nível via `/neighbors`) e **Conjunto** com **Área × Escopo combináveis**.
  - **Filtros combinados** (2026-06-12): dropdown de **Área** (todas/<área>) × dropdown de **Escopo** (todos / só Indicium) → ex.: *Finanças + só Indicium* = 6 EGPs (13 c/ deps); *Todos · Indicium* = área=todas+indi; *base completa* = todas+todos. Dropdown de EGPs também filtra por área+escopo. Toggle "incluir deps externas".
  - **Layout adaptativo**: hierárquico LR até 250 nós; acima disso, física (estabiliza e congela) — evita o hairball lento.
- ⚠️ Corrigida inconsistência do rename **DOR1→indi**: backend (`/api/inputs`, `/api/metrics`) e frontend usavam `escopo_dor1`/`scope=dor1` enquanto as Delta tables já estavam em `escopo_indi`/`escopo=indi` — **padronizado tudo em `indi`** (senão monitor dava erro). Botão do filtro renomeado para "Indicium".
