# Dependências Cíclicas entre EGPs — Catálogo de Evidências

> Gerado em 2026-06-12 a partir de `egps_analysis/03_matriz_dependencias.csv` (grafo projeto→projeto, derivado do inventário `06_prontidao_tabela.csv`). Componentes fortemente conexos por **Tarjan**; classificação por investigação multiagente + verificação adversarial.

Cada **aresta** do grafo significa: o projeto produtor **escreve** uma tabela e o consumidor a **lê**. Um conjunto de projetos forma um **ciclo** quando há um caminho de dependências que volta ao início (A→B→…→A), o que impede definir uma ordem de migração — daí a marcação *“Ciclo - quebrar manualmente”* nas ondas.

## 1. Sumário

- Grafo de dependências: **727 projetos** com vínculo, **1.519 arestas** dirigidas (produtor→consumidor).
- **13 clusters cíclicos** (SCC de tamanho ≥ 2), somando **57 projetos** e **127 arestas internas**. Nenhum self-loop.
- Tamanhos: 16, 9, 8, 4, 3, 3, 2, 2, 2, 2, 2, 2, 2 projetos.
- Vereditos (pós-verificação, todos alta confiança, verificador concordou nos 13): **4 ciclo real** · **8 artefato parcial** · **1 artefato total**.

### Causa-raiz dominante

A maioria das arestas cíclicas **não é entrega projeto→projeto**. São **tabelas de schemas corporativos compartilhados** (`INSIGHT.`, `PME.`, `PLCA.`, `SHAREATA.`, `SIC.`, `MISCRED.`, `GCSERASA.`…) que vários projetos **leem e regravam** (padrão *read-modify-write* na mesma tabela). O grafo conta a leitura como dependência e isso fecha o ciclo. **Tratando essas tabelas como fontes externas únicas** (uma `source` no dbt, carregada uma vez), a maior parte dos ciclos desaparece.
- Tabela-raiz: **`INSIGHT.TBBRUTA`** (5 escritores / 16 leitores) costura sozinha o cluster #1 (16 projetos).

### Os 4 ciclos REAIS (precisam de quebra manual)

- **Cluster #4** (4 proj · Crédito): Quebrar o par mútuo: externalizar _BASE_LOG_RED_ATRASO_20251124 como source única (snapshot da rodada anterior) consumida por Reducao_Em_Dia, removendo a leitur
- **Cluster #7** (2 proj · Finanças): Extrair a construção das regras de segmentação/risk-sharing (REGRAS_SEGMENTAR_TEMP) para um modelo dbt independente, upstream de ambos os projetos. Tanto Book q
- **Cluster #10** (2 proj · Riscos): Manter como aresta unidirecional (esta e a direcao 'final' do fluxo: VCARIMBOS alimenta o cubo 4060). Modelar _4040_VCARIMBOS como model dbt unico de owner Base
- **Cluster #13** (2 proj · Rodas): Externalizar AUXL.PROPOSTAS_ESG em um modelo standalone/shared (fora de ambos os projetos), pois sua logica (QDV/02-base-esg) so depende de DBA.TbProposta, DBA.

## 2. Resumo dos 13 clusters

| # | Tam | Áreas | Onda(s) | Veredito | Conf | Tabelas (handoff/fonte/colisão) | Quebra |
|---:|---:|---|---|---|---|---|---|
| 4 | 4 | Crédito | O3* | 🔴 ciclo real | alta | 5/0/0 | Quebrar o par mútuo: externalizar _BASE_LOG_RED_ATRASO_20251124 como source única (snapsho |
| 7 | 2 | Finanças | O5* | 🔴 ciclo real | alta | 2/0/0 | Extrair a construção das regras de segmentação/risk-sharing (REGRAS_SEGMENTAR_TEMP) para u |
| 10 | 2 | Riscos | O2* | 🔴 ciclo real | alta | 2/0/0 | Manter como aresta unidirecional (esta e a direcao 'final' do fluxo: VCARIMBOS alimenta o  |
| 13 | 2 | Rodas | O9* | 🔴 ciclo real | alta | 2/0/0 | Externalizar AUXL.PROPOSTAS_ESG em um modelo standalone/shared (fora de ambos os projetos) |
| 1 | 16 | Atacado, Crédito, Riscos | O1* | 🟡 artefato parcial | alta | 12/22/1 | Externalizar como SOURCE unica. Materializar a base bruta uma vez (projeto/modelo dedicado |
| 2 | 9 | Cobranças | O1* | 🟡 artefato parcial | alta | 10/7/0 | Externalizar: TCONFIG.CONFIG_TPENTRADA e config compartilhada (lida por 16 projetos). Vira |
| 3 | 8 | SAS_UC4 | O7* | 🟡 artefato parcial | alta | 12/0/1 | REMOVER aresta do grafo — colisão de nome (WORK temp em originacao vs CTE local em passthr |
| 5 | 3 | Atacado | O2* | 🟡 artefato parcial | alta | 3/6/0 | Externalizar: promover os snapshots mensais EXTRATO.EXTRATO_YYYYMM a uma camada/source uni |
| 6 | 3 | Rodas | O8* | 🟡 artefato parcial | alta | 2/2/0 | Externalizar as duas tabelas DEPARA como seed/source unica (CSV em /infogrc/IGE_NEW/EGV/Pa |
| 9 | 2 | Riscos | O1* | 🟡 artefato parcial | alta | 7/2/0 | Remover do grafo de dependencia projeto->projeto: nao sao handoff. Externalizar como UMA s |
| 11 | 2 | Riscos | O1* | 🟡 artefato parcial | alta | 1/1/0 | Eliminar esta aresta: e falsa. Reclassificar PLD.BS_MIDIA_AML como source externa unica (l |
| 12 | 2 | Rodas, SAS_UC4 | O10* | 🟡 artefato parcial | alta | 1/1/0 | Quebrar: externalizar TMP.TBPOTENCIALRODAS como source/seed unica (origem .sas7bdat pre-ex |
| 8 | 2 | Negócios Transacionais Varejo e NaPista, Solar | O0* | 🟢 artefato total | alta | 0/2/0 | Eliminar a aresta: A nao escreve HOML.TBORIGINACAO (so FROM/JOIN). Modelar HOML.TBORIGINAC |

*`O1*` = projeto na Onda 1 marcada como ciclo.

## 3. Detalhe por cluster

Ordem: ciclos reais primeiro, depois artefatos (maiores primeiro).

### Cluster #4 — 4 projetos · Crédito — 🔴 ciclo real

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| 20250924 - BASE_CONTROLE_TOTAL_VF | Crédito | Onda 3 (Ciclo - quebrar manualmente) | 144 | 195 |
| 20251114 - BASE MANUTENCAO TOTAL | Crédito | Onda 3 (Ciclo - quebrar manualmente) | 149 | 297 |
| RED_LIMITE_PUBLICO_EM_ATRASO_20251124 | Crédito | Onda 3 (Ciclo - quebrar manualmente) | 11 | 54 |
| Reducao_Em_Dia_20251124 | Crédito | Onda 3 (Ciclo - quebrar manualmente) | 26 | 135 |

**O laço:** Ciclo 100% interno à área Crédito entre 4 projetos de manutenção/redução de limite de cartão. Fluxo principal em cadeia: BASE_CONTROLE_TOTAL_VF escreve MANUTLIM.CONTROLE_MANUTENCAO_TOTAL → BASE MANUTENCAO TOTAL a lê e escreve MANUTLIM.MANUTENCAO_TOTAL → Reducao_Em_Dia a lê. O ciclo se fecha por DUAS arestas de volta que apontam para o início da cadeia: (1) Reducao_Em_Dia escreve MANUTLIM._BASE_LOG_RED_EMDIA_20251124 que BASE_CONTROLE_TOTAL_VF lê de volta; (2) RED_LIMITE_PUBLICO_EM_ATRASO escreve MANUTLIM._BASE_LOG_RED_ATRASO_20251124 que BASE_CONTROLE_TOTAL_VF lê de volta. Há ainda um par MÚTUO real A<->B entre RED_LIMITE_PUBLICO_EM_ATRASO e Reducao_Em_Dia: RED_ATRASO escreve _BASE_LOG_RED_ATRASO_20251124 (lido por Reducao_Em_Dia) e Reducao_Em_Dia escreve GALDINO.BASE_PARTIDA_REDUCAOCARGA_202511 (lido por RED_ATRASO). Ou seja, os dois projetos de redução (em-dia e em-atraso) consomem saídas um do outro, e ambos os logs de redução voltam para realimentar a base de controle total. Todas as tabelas-via são datasets SAS/Local (libs pessoais/de time MANUTLIM e GALDINO), não fontes de banco corporativas; são artefatos intermediários gravados pelos próprios projetos.

**Exemplos de ciclo:**

- 20250924 - BASE_CONTROLE_TOTAL_VF → 20251114 - BASE MANUTENCAO TOTAL → Reducao_Em_Dia_20251124 → 20250924 - BASE_CONTROLE_TOTAL_VF
- 20250924 - BASE_CONTROLE_TOTAL_VF → 20251114 - BASE MANUTENCAO TOTAL → Reducao_Em_Dia_20251124 → RED_LIMITE_PUBLICO_EM_ATRASO_20251124 → 20250924 - BASE_CONTROLE_TOTAL_VF

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `MANUTLIM.CONTROLE_MANUTENCAO_TOTAL` | 1 | 2 | handoff real | Escrita só por BASE_CONTROLE_TOTAL_VF (PERMANENT OUTPUTS); lida por BASE MANUTENCAO TOTAL (EXTERNAL INPUTS + provenance DATA Step-SET). 1 writer real -> consumidor distinto. (leito |
| `MANUTLIM.MANUTENCAO_TOTAL` | 1 | 2 | handoff real | Escrita só por BASE MANUTENCAO TOTAL (PERMANENT OUTPUTS); lida por Reducao_Em_Dia (EXTERNAL INPUTS + provenance PROC SQL-FROM). Handoff genuino; outro reader é o proprio writer. |
| `MANUTLIM._BASE_LOG_RED_ATRASO_20251124` | 1 | 3 | handoff real | Escrita só por RED_LIMITE_PUBLICO_EM_ATRASO (PERMANENT OUTPUTS); lida por BASE_CONTROLE_TOTAL_VF e por Reducao_Em_Dia (ambos em EXTERNAL INPUTS + provenance). 1 writer alimentando  |
| `MANUTLIM._BASE_LOG_RED_EMDIA_20251124` | 1 | 2 | handoff real | Escrita só por Reducao_Em_Dia (PERMANENT OUTPUTS); lida por BASE_CONTROLE_TOTAL_VF (EXTERNAL INPUTS + provenance). Outra aresta de retorno do ciclo; reader extra é auto-leitura. |
| `GALDINO.BASE_PARTIDA_REDUCAOCARGA_202511` | 1 | 2 | handoff real | Escrita só por Reducao_Em_Dia (PERMANENT OUTPUTS); lida por RED_LIMITE_PUBLICO_EM_ATRASO (EXTERNAL INPUTS + provenance DATA Step-SET). É a via_ba do par mutuo A<->B; reader extra é |

**Veredito:** investigador `ciclo_real` → verificação **`ciclo_real`** (concorda: True; nenhuma. Verifiquei as 5 tabelas-via no código (text_egps/) e todas batem com table_flow (n_writers=1 cada; flow_summary). As 5 tabelas-via são handoffs reais de writer único: cada uma tem exatamente 1 produtor dentro do cluster e é lida por outro(s) projeto(s) do cluster, confirmado tanto em PERMANENT OUTPUTS do produtor quanto em EXTERNAL INPUTS+TABLE_READ_PROVENANCE dos consumidores. Nenhuma é fonte de banco corporat

**Como quebrar:**

- `RED_LIMITE_PUBLICO_EM_ATRASO_20251124` → `Reducao_Em_Dia_20251124` via `MANUTLIM._BASE_LOG_RED_ATRASO_20251124` — Quebrar o par mútuo: externalizar _BASE_LOG_RED_ATRASO_20251124 como source única (snapshot da rodada anterior) consumida por Reducao_Em_Dia, removendo a leitura ao vivo do output de RED_ATRASO.
- `Reducao_Em_Dia_20251124` → `RED_LIMITE_PUBLICO_EM_ATRASO_20251124` via `GALDINO.BASE_PARTIDA_REDUCAOCARGA_202511` — Determinar quem produz a base de partida da campanha: extrair BASE_PARTIDA_REDUCAOCARGA_202511 para um modelo/stg compartilhado (upstream comum aos dois) e fazer Reducao_Em_Dia e RED_ATRASO lerem desse modelo, em vez de Reducao_Em_Dia escrever e RED_ATRASO ler. Isso desfaz o ciclo de 2 nós.
- `Reducao_Em_Dia_20251124` → `20250924 - BASE_CONTROLE_TOTAL_VF` via `MANUTLIM._BASE_LOG_RED_EMDIA_20251124` — Aresta de retorno: BASE_CONTROLE_TOTAL_VF é um agregador histórico que faz SET de TODOS os logs de redução; converter _BASE_LOG_RED_EMDIA_20251124 (e os demais _BASE_LOG_RED_*) em fonte append-only/incremental lida por BASE_CONTROLE_TOTAL_VF como snapshot, não como output ao vivo da rodada corrente.
- `RED_LIMITE_PUBLICO_EM_ATRASO_20251124` → `20250924 - BASE_CONTROLE_TOTAL_VF` via `MANUTLIM._BASE_LOG_RED_ATRASO_20251124` — Mesma estratégia da aresta acima: BASE_CONTROLE_TOTAL_VF deve depender de uma camada de logs consolidados (incremental), não diretamente do output da rodada de RED_ATRASO; assim o agregador fica downstream estável e não realimenta o ciclo.

**Recomendação:** É ciclo REAL, exige quebra manual (compatível com a marcação 'Onda 3'). Recomendação em duas frentes. (A) Camada temporal/incremental para a base de controle: BASE_CONTROLE_TOTAL_VF é um agregador que faz SET de dezenas de logs históricos de redução/aumento (incl. _BASE_LOG_RED_ATRASO_* e _BASE_LOG_RED_EMDIA_* de várias datas). Em dbt, modelar os logs MANUTLIM._BASE_LOG_RED_* como uma tabela incremental/append-only e fazer BASE_CONTROLE_TOTAL_VF referenciar a versão consolidada (snapshot da rodada anterior, não a corrente). Isso elimina as duas arestas de retorno (_BASE_LOG_RED_EMDIA_20251124 e _BASE_LOG_RED_ATRASO_20251124) sem alterar a lógica de negócio (ele já agrega histórico). (B) Quebrar o par mútuo RED_ATRASO<->Reducao_Em_Dia: extrair GALDINO.BASE_PARTIDA_REDUCAOCARGA_202511 (a 'base de partida' da campanha de redução de carga) para um modelo upstream compartilhado, do qual AMBOS os projetos descendem, em vez de um escrever e o outro ler; e tratar o consumo cruzado de _BASE_LOG_RED_ATRASO_20251124 por Reducao_Em_Dia como snapshot da rodada anterior. Após (A)+(B) a cadeia vira DAG linear: BASE_PARTIDA(comum) -> RED_ATRASO e Reducao_Em_Dia -> logs consolidados -> BASE_CONTROLE_TOTAL_VF -> BASE MANUTENCAO TOTAL. Validar com o time de Crédito (libs MANUTLIM/GALDINO) se BASE_PARTIDA_REDUCAOCARGA é insumo comum (provável) e se as leituras de log são da rodada corrente ou histórica — ponto decisivo para confirmar a estratégia de snapshot.

### Cluster #7 — 2 projetos · Finanças — 🔴 ciclo real

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| Book_Diario_Acumulado | Finanças | Onda 5 (Ciclo - quebrar manualmente) | 71 | 27 |
| Tesouraria_sem_porta | Finanças | Onda 5 (Ciclo - quebrar manualmente) | 33 | 24 |

**O laço:** Laço mútuo A↔B entre dois projetos de Finanças no fechamento mensal (sufixo NOV25D). Tesouraria_sem_porta GRAVA PLANCTRL.BASE_TESOURARIA (resultado/VR mesa caixa da tesouraria) e Book_Diario_Acumulado a LÊ para ratear tesouraria por linha. Na volta, Book_Diario GRAVA SAIDASIC.REGRAS_SEGMENTAR_TEMP_NOV25D_D3 (regras de segmentação/risk-sharing do mês corrente) e Tesouraria a LÊ para segmentar sua base. Ou seja: resultado de tesouraria vai do Tesouraria->Book, e as regras de segmentação voltam do Book->Tesouraria, dentro do mesmo ciclo mensal -> dependência circular real.

**Exemplos de ciclo:**

- Book_Diario_Acumulado → Tesouraria_sem_porta → Book_Diario_Acumulado

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `PLANCTRL.BASE_TESOURARIA` | 1 | 2 | handoff real | Tesouraria_sem_porta é o único writer: 'delete from PLANCTRL.BASE_TESOURARIA' (l.2232) + 'insert into PLANCTRL.BASE_TESOURARIA' (l.2235) = full refresh. Book_Diario consome em l.33 |
| `SAIDASIC.REGRAS_SEGMENTAR_TEMP_NOV25D_D3` | 1 | 2 | handoff real | Book_Diario é único writer do mês corrente: 'Create table SAIDASIC.REGRAS_SEGMENTAR_TEMP&DtBase.' com %Let DtBase=_NOV25D_D3 (l.2694) + Proc Append base=...&DtBase (l.2778). Tesour |

**Veredito:** investigador `ciclo_real` → verificação **`ciclo_real`** (concorda: True; Nenhuma correção material. Todas as alegações de carga foram verificadas no código e confirmam o veredito. (1) BASE_TESO). As duas arestas são handoffs genuínos com exatamente 1 writer cada, em sentidos opostos, dentro do mesmo ciclo de fechamento mensal: Tesouraria->Book via PLANCTRL.BASE_TESOURARIA e Book->Tesouraria via SAIDASIC.REGRAS_SEGMENTAR_TEMP_NOV25D_D3. Não é artefato de fonte compartilhada nem colisão (os se

**Como quebrar:**

- `Book_Diario_Acumulado` → `Tesouraria_sem_porta` via `SAIDASIC.REGRAS_SEGMENTAR_TEMP_NOV25D_D3` — Extrair a construção das regras de segmentação/risk-sharing (REGRAS_SEGMENTAR_TEMP) para um modelo dbt independente, upstream de ambos os projetos. Tanto Book quanto Tesouraria passam a referenciá-lo via ref()/source, eliminando a aresta Book->Tesouraria e quebrando o ciclo.
- `Tesouraria_sem_porta` → `Book_Diario_Acumulado` via `PLANCTRL.BASE_TESOURARIA` — Manter como aresta linear: BASE_TESOURARIA vira um modelo/mart de Tesouraria e Book o consome via ref(). Não cortar esta; é o handoff natural Tesouraria->Book uma vez removida a outra aresta.

**Recomendação:** Quebrar pela aresta das regras de segmentação (a mais barata). Promover SAIDASIC.REGRAS_SEGMENTAR_TEMP_NOV25D_D3 a um modelo dbt próprio (ex.: int_regras_segmentar_financas), pois é uma tabela de regras/segmentação determinística construída cedo no fluxo do Book a partir de TB001_SEGMENTACAO/TBCLIENTE/risk-sharing, não dependente da tesouraria do mesmo dia. Com esse modelo upstream compartilhado, a ordem fica: REGRAS_SEGMENTAR -> Tesouraria (BASE_TESOURARIA) -> Book_Diario, virando um DAG acíclico. Cuidado na migração: parametrizar o sufixo de mês (&DtBase vs &BaseRef) por variável dbt para não colidir Book com seu próprio histórico FEV19D. Verificar se o cálculo de REGRAS no Book não usa colunas derivadas de BASE_TESOURARIA (pela leitura do código não usa — l.2694 monta a partir de segmentação/risk-sharing); confirmar com o time de Finanças antes de fixar o corte.

### Cluster #10 — 2 projetos · Riscos — 🔴 ciclo real

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| Base_Origem_FPR_85_202509_Res_229_V2_SRP | Riscos | Onda 2 (Ciclo - quebrar manualmente) | 39 | 185 |
| RWAcpad_202509_vIFRS9_V22_batimento4060_SRP | Riscos | Onda 2 (Ciclo - quebrar manualmente) | 74 | 710 |

**O laço:** Ciclo mútuo A<->B de 2 EGPs da MESMA área (Riscos), que na verdade são dois estágios de UM ÚNICO pipeline mensal do cubo regulatório PEPR/RWA (Resolução 229), persistido na biblioteca compartilhada _PEPR_RA (path físico idêntico nos dois projetos: /riscosbv/ctrcredito/pepr/results/). O laço: RWAcpad ESCREVE _PEPR_RA.BASECUBO202509._4040_V229 (linha 8466: SET do próprio V229 + EXTRACAO.BASE_OPERACOES_RWAMPAD, ou seja consolida carimbos/ops manuais); Base_Origem LÊ esse _4040_V229 (linhas 106/2599) para gerar BASE_POPULAR/BASE_OUTROS e ESCREVE _PEPR_RA.BASECUBO202509._4040_VCARIMBOS (linha 4269, derivado do seu cubo local _4040); RWAcpad volta a LER _4040_VCARIMBOS (linha 9404) para montar o cubo 4060 (CUBO_4060_ATACADO/VAREJO). Ou seja: o dado que 'volta pra trás' é a sequência 4040 -> V229 -> VCARIMBOS -> 4060, com os dois EGPs intercalando etapas da construção da mesma base. A dependência temporal é genuína (VCARIMBOS depende de V229 já existir; o 4060 depende de VCARIMBOS), mas o ciclo só existe porque um pipeline lógico único foi partido em dois EGPs no ponto errado.

**Exemplos de ciclo:**

- Base_Origem_FPR_85_202509_Res_229_V2_SRP → RWAcpad_202509_vIFRS9_V22_batimento4060_SRP → Base_Origem_FPR_85_202509_Res_229_V2_SRP

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `_PEPR_RA.BASECUBO202509._4040_V229` | 1 | 1 | handoff real | Writer unico=RWAcpad (linha 8466 DATA _PEPR_RA...4040_v229; SET self + EXTRACAO.BASE_OPERACOES_RWAMPAD). Reader=Base_Origem (linhas 106/2599 SET _PEPR_RA...4040_V229 -> BASE_POPULA |
| `_PEPR_RA.BASECUBO202509._4040_VCARIMBOS` | 1 | 1 | handoff real | Writer unico=Base_Origem (linha 4269 DATA _PEPR_RA...4040_VCarimbos; SET BASECUBO..._4040 local + ajustes manuais COAMO). Reader=RWAcpad (linha 9404 SET _PEPR_RA...4040_VCARIMBOS - |

**Veredito:** investigador `ciclo_real` → verificação **`ciclo_real`** (concorda: True; Veredito correto e bem evidenciado; confirmei tudo no codigo. Apenas duas imprecisoes menores que NAO alteram a topologi). As duas tabelas do ciclo sao handoffs reais (1 writer + 1 reader cada, ambas em biblioteca persistente compartilhada _PEPR_RA com path fisico identico nos dois EGPs, nao WORK/temp e nao colisao de nome). Confirmado no codigo: RWAcpad produz _4040_V229 que Base_Origem consome, e Base_Origem produz _4

**Como quebrar:**

- `Base_Origem_FPR_85_202509_Res_229_V2_SRP` → `RWAcpad_202509_vIFRS9_V22_batimento4060_SRP` via `_PEPR_RA.BASECUBO202509._4040_VCARIMBOS` — Manter como aresta unidirecional (esta e a direcao 'final' do fluxo: VCARIMBOS alimenta o cubo 4060). Modelar _4040_VCARIMBOS como model dbt unico de owner Base_Origem (camada intermediate) e RWAcpad referencia via ref()/source. Esta aresta NAO precisa ser cortada.
- `RWAcpad_202509_vIFRS9_V22_batimento4060_SRP` → `Base_Origem_FPR_85_202509_Res_229_V2_SRP` via `_PEPR_RA.BASECUBO202509._4040_V229` — ESTA e a aresta que fecha o ciclo e deve ser quebrada. Extrair a producao de _4040_V229 (RWAcpad linha 8466, que so consolida _4040 base + carimbos manuais de EXTRACAO.BASE_OPERACOES_RWAMPAD) para um model/EGP de ESTAGIO INICIAL, a montante de Base_Origem. Assim a ordem vira: [V229 builder] -> Base_Origem (le V229, escreve VCARIMBOS) -> RWAcpad (le VCARIMBOS, escreve 4060). Sem volta.

**Recomendação:** Quebrar pela aresta _4040_V229 (RWAcpad->Base_Origem), que e o elo que fecha o laço. O cubo _PEPR_RA.BASECUBO202509 e uma base regulatoria unica construida em estagios 4040 -> V229 -> VCARIMBOS -> 4060; o ciclo so surge porque o estagio inicial (montar _4040_V229 a partir de _4040 + carimbos manuais de EXTRACAO.BASE_OPERACOES_RWAMPAD) hoje mora dentro do RWAcpad, que tambem e o estagio FINAL (4060). Acao concreta: (1) Dividir o RWAcpad em dois — separar o bloco que escreve _4040_V229 (linhas ~8460-8600) num model/no de montante (ex.: 'cubo_4040_v229') e deixar no RWAcpad apenas a etapa 4060 que consome VCARIMBOS. (2) Materializar cada particao do cubo como UM model dbt com owner unico e dependencias via ref(): cubo_4040_v229 (owner novo no/RWAcpad-stage1) -> base_origem_vcarimbos (owner Base_Origem) -> rwacpad_4060 (owner RWAcpad-stage2). (3) Tratar _PEPR_RA.BASECUBO202509._4040 (base raiz, lida pelos dois e sem writer dentro do cluster) como source externa unica. Resultado: DAG linear, ciclo eliminado sem perda de logica. Atencao: ha leituras cross-mes (BASECUBO202508/202507_4040_V229/VCARIMBOS) que sao snapshots historicos — modelar como sources versionadas por _DATA_REFERENCIA_, nao como dependencia do mes corrente.

### Cluster #13 — 2 projetos · Rodas — 🔴 ciclo real

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| inad | Rodas | Onda 9 (Ciclo - quebrar manualmente) | 24 | 19 |
| qualidadedevendas_cubo_estudo | Rodas | Onda 9 (Ciclo - quebrar manualmente) | 27 | 46 |

**O laço:** Laço mútuo A↔B entre dois projetos da área Rodas. Rodas__inad escreve a mart permanente INAD.INADHISTORICA (lib INAD, no script 04-base-final), que Rodas__qualidadedevendas_cubo_estudo lê em 06-inad como insumo de inadimplência histórica. Na direção oposta, qualidadedevendas_cubo_estudo escreve AUXL.PROPOSTAS_ESG (lib AUXL, no script 02-base-esg, a partir de tabelas DBA via pass-through) que Rodas__inad lê em 02-tb-modelomolicar para derivar TbModeloMolicar. Cada projeto produz um insumo permanente que o outro consome: dado de inadimplência vai inad→QDV, e a base de propostas ESG/molicar vai QDV→inad. Os dois lados são tabelas físicas distintas em libs permanentes diferentes (INAD. e AUXL.), com exatamente 1 produtor cada — não há colisão de temporária nem fonte multi-writer.

**Exemplos de ciclo:**

- inad → qualidadedevendas_cubo_estudo → inad

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `INAD.INADHISTORICA` | 1 | 2 | handoff real | Rodas__inad/04-base-final.sas: EXPORTED_LIBNAMES INAD, 'CREATE TABLE INAD.InadHistorica AS' (mart permanente). Lida por Rodas__inad/05-finalizacao (self) e por QDV/06-inad ('SELECT |
| `AUXL.PROPOSTAS_ESG` | 1 | 1 | handoff real | QDV/02-base-esg.sas: EXPORTED_LIBNAMES AUXL, 'PROC SORT ... OUT=AUXL.PROPOSTAS_ESG NODUPKEY' construida a partir de DBA.TbProposta/TbPropGarantiaMaqEquip/TbMolicar (pass-through).  |

**Veredito:** investigador `ciclo_real` → verificação **`ciclo_real`** (concorda: True; nenhuma. Verifiquei adversarialmente os dois lados no codigo e tudo confere. (1) INAD.INADHISTORICA: Rodas__inad/04-base). As duas arestas sao handoffs reais e independentes: INAD.INADHISTORICA (inad->QDV) e AUXL.PROPOSTAS_ESG (QDV->inad). Ambas sao tabelas fisicas distintas em libs permanentes proprias (INAD., AUXL.), cada uma com exatamente 1 produtor no cluster; nao sao schemas de origem comum (sem prefixos tipo INSI

**Como quebrar:**

- `qualidadedevendas_cubo_estudo` → `inad` via `AUXL.PROPOSTAS_ESG` — Externalizar AUXL.PROPOSTAS_ESG em um modelo standalone/shared (fora de ambos os projetos), pois sua logica (QDV/02-base-esg) so depende de DBA.TbProposta, DBA.TbPropGarantiaMaqEquip e DBA.TbMolicar. Tanto inad/02-tb-modelomolicar quanto QDV passam a referenciar esse modelo unico como source/ref, removendo a aresta QDV->inad e quebrando o ciclo.

**Recomendação:** Quebrar pela aresta AUXL.PROPOSTAS_ESG (mais barata e logicamente correta). Extrair a construcao de AUXL.PROPOSTAS_ESG (hoje em Rodas__qualidadedevendas_cubo_estudo/02-base-esg.sas, alimentada apenas por DBA.TbProposta/TbPropGarantiaMaqEquip/TbMolicar) para um modelo dbt independente e compartilhado. Ambos os projetos (inad/02-tb-modelomolicar e QDV) o consomem via ref(), eliminando a dependencia QDV->inad. Observacao: inad/02-tb-modelomolicar e QDV/02-base-esg derivam o mesmo TbModeloMolicar de forma quase identica a partir de PROPOSTAS_ESG + AUXL.BASE_MODELOS_ESG — candidato a consolidar tambem TbModeloMolicar como modelo compartilhado para evitar duplicacao. Manter intacto o handoff real inad->QDV via INAD.INADHISTORICA: nesse sentido inad (produtor da inadimplencia) deve ser materializado antes de QDV. Apos extrair PROPOSTAS_ESG, a ordem de execucao fica: modelo PROPOSTAS_ESG (DBA) -> inad -> QDV, sem ciclo.

### Cluster #1 — 16 projetos · Atacado, Crédito, Riscos — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| Base_Bruta | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 21 | 186 |
| Base_Carteira_Consolidada | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 96 | 107 |
| Base_Sinais_v5 | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 10 | 161 |
| Esteira 2 | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 22 | 137 |
| Painel Sales Finance | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 19 | 121 |
| Project_semiUpper | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 24 | 54 |
| [Gestão_de_Carteira] Motores | Atacado | Onda 1 (Ciclo - quebrar manualmente) | 28 | 191 |
| Base_Bruta | Crédito | Onda 1 (Ciclo - quebrar manualmente) | 22 | 183 |
| CIB | Crédito | Onda 1 (Ciclo - quebrar manualmente) | 19 | 76 |
| Esteira - OMIE Sacados_v2 | Crédito | Onda 1 (Ciclo - quebrar manualmente) | 9 | 65 |
| Esteira - Sales Finance PJ | Crédito | Onda 1 (Ciclo - quebrar manualmente) | 15 | 136 |
| [Gestão_de_Carteira] Motores | Crédito | Onda 1 (Ciclo - quebrar manualmente) | 27 | 182 |
| Base_Unica_202509 | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 77 | 336 |
| Controle_PMES_v19__v2 | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 72 | 139 |
| Indicadores_PMEs_PPT_V3 | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 22 | 67 |
| VNP - Diario Middle e Corporate_2025_WINSCP | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 114 | 197 |

**O laço:** O SCC de 16 projetos (Atacado/Crédito/Riscos) é fechado quase inteiramente por tabelas de SCHEMAS CORPORATIVOS COMPARTILHADOS (INSIGHT., PME., PLCA., SHAREATA., SIC., MISCRED., GCSERASA.) que vários projetos LEEM e REESCREVEM. O padrão dominante é read-modify-write da MESMA tabela dentro do mesmo projeto: dezenas de tabelas aparecem simultaneamente em INTERNAL READS e PERMANENT OUTPUTS do mesmo .egp (ex.: Base_Bruta lê e grava INSIGHT.TBVNP, PLCA.TBSISTEMAPLCA, SHAREATA.TBRATING_V2, SIC.DMRELATIOLIMITESHIST; Esteira 2 lê e grava INSIGHT.BASE_BACEN_FINAL e PME.BASE_FATURAMENTO_SERASA_PJ; Indicadores lê e grava MONITRCA.NE_DESEMBOLSOS). O grafo conta a leitura dessas tabelas como aresta produtor->consumidor, mas elas são FONTES/áreas de staging comuns, não entregas projeto->projeto. O 'laço que volta pra trás' raiz é INSIGHT.TBBRUTA (5 writers / 16 readers): todos os projetos a leem e alguns a regravam, conectando todo o cluster. Sobram pouquíssimos handoffs reais (intra-área), notadamente o ciclo mútuo Riscos Controle_PMES <-> Indicadores (PDD.INFOS_PME / MONITRCA.NE_DESEMBOLSOS).

**Exemplos de ciclo:**

- Base_Bruta → Esteira 2 → Base_Sinais_v5 → Painel Sales Finance → Base_Bruta
- Base_Bruta → Esteira 2 → Base_Sinais_v5 → Painel Sales Finance → [Gestão_de_Carteira] Motores → Controle_PMES_v19__v2 → Base_Unica_202509 → Base_Carteira_Consolidada → CIB → Base_Bruta
- Base_Bruta → Esteira 2 → Base_Sinais_v5 → Painel Sales Finance → [Gestão_de_Carteira] Motores → Controle_PMES_v19__v2 → Base_Unica_202509 → CIB → Base_Bruta

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `INSIGHT.TBBRUTA` | 5 | 16 | fonte compartilhada | 5 writers (Base_Bruta, Base_Carteira_Consolidada, Base_Sinais, Cred Base_Bruta, CIB) e 16 readers; schema INSIGHT compartilhado; cada writer a tem em INTERNAL READS e PERMANENT OUT |
| `SHAREATA.TBCARTEIRAGRUPO` | 3 | 7 | fonte compartilhada | 3 writers (Cred Base_Bruta, CIB, Riscos Base_Unica) e 7 readers; schema SHAREATA compartilhado; CIB a tem em INTERNAL READS e PERMANENT OUTPUTS + backup TBCARTEIRAGRUPO_BACKUP. |
| `PME.BASE_HISTORICA_PMUM_SF` | 3 | 6 | fonte compartilhada | 3 writers (Atacado Motores, Credito Motores, SalesFinance) + 6 readers, schema PME; cada writer a tem em INTERNAL READS e PERMANENT OUTPUTS + _ANT (versao anterior). Base historica |
| `PLCA.TBSISTEMAPLCA` | 2 | 12 | fonte compartilhada | Schema PLCA. Base_Bruta a le [PROC SQL - FROM] e grava DATA PLCA.TBSISTEMAPLCA (read-modify-write); 12 readers. Tabela de sistema PLCA, fonte comum. |
| `INSIGHT.TBVNP` | 2 | 5 | fonte compartilhada | Atacado e Credito Base_Bruta a leem e regravam (INSIGHT.TBVNP em INTERNAL READS e PERMANENT OUTPUTS; UPDATE/MERGE INSIGHT.TBVNP). Carga incremental de fonte compartilhada. |
| `SHAREATA.TBCARTEIRACLIENTE` | 2 | 4 | fonte compartilhada | 2 writers (CIB, Riscos Base_Unica); CIB grava TBCARTEIRACLIENTE + _BACKUP e exporta para arquivos UC4/RenovaCredito. Carteira compartilhada SHAREATA. |
| `SHAREATA.TBRATING_V2` | 2 | 4 | fonte compartilhada | 2 writers (Atacado e Credito Base_Bruta); Base_Bruta a tem em INTERNAL READS e PERMANENT OUTPUTS. Rating compartilhado em SHAREATA. |
| `SIC.DMRELATIOLIMITESHIST` | 2 | 3 | fonte compartilhada | 2 writers (Atacado/Credito Base_Bruta); schema SIC; Base_Bruta a le (PROC SORT/SQL FROM/JOIN) e grava. DM de limites historica, fonte comum. |
| `PME.BASE_SCORE_SERASA_PJ` | 2 | 6 | fonte compartilhada | Escrita por OMIE e SalesFinance (ambas em INTERNAL READS+PERMANENT OUTPUTS); 6 readers. Tabela de score Serasa PJ no schema PME, enriquecimento de fonte comum. |
| `PME.BASE_RESTR_SERASA_PJ` | 2 | 4 | fonte compartilhada | Escrita por OMIE e SalesFinance; restricoes Serasa PJ no schema PME. Fonte de enriquecimento compartilhada (multi-writer). |
| `PME.BASE_SOCIOS_SERASA_PJ` | 2 | 4 | fonte compartilhada | Escrita por OMIE e SalesFinance; socios Serasa PJ no schema PME. Multi-writer, fonte compartilhada. |
| `GCSERASA.TBGCDADOSCADASTRAIS` | 2 | 4 | fonte compartilhada | 2 writers (Atacado/Credito Motores), schema GCSERASA; ambos a leem e regravam. Dados cadastrais Serasa GC, fonte compartilhada. |
| `INSIGHT.TBPESSOA` | 1 | 4 | fonte compartilhada | CIB a le [PROC SQL - FROM] e grava (CREATE TABLE INSIGHT.TBPESSOA AS ... FROM INSIGHT.TBPESSOA); Base_Bruta a le via &LIB..TbPessoa / DBGLOBAL..TbPessoa. Dimensao de pessoa corpora |
| `MISCRED.MATRIZ_SETORES` | 1 | 5 | fonte compartilhada | Schema MISCRED; Riscos Base_Unica grava e 5 projetos leem (incl. ela mesma); exportada de planilha MATRIZ_SETORES_RISCO.xlsx. Tabela de referencia setorial compartilhada. |
| `MISCRED.BASE_CLIENTES` | 1 | 2 | fonte compartilhada | Schema MISCRED; writer Base_Unica tambem reader (self). Fonte/staging comum, nao handoff dedicado. |
| `MISCRED.TBCRED_BASE_GLOBAL_202510` | 1 | 2 | fonte compartilhada | Schema MISCRED com sufixo de data; writer Base_Unica tambem reader. Base global credito compartilhada. |
| `MISCRED.BASE_UNICA_ATACADO_202408` | 1 | 2 | fonte compartilhada | Schema MISCRED, snapshot mensal versionado; Base_Unica grava varios BASE_UNICA_ATACADO_AAAAMM e os reusa. Snapshot historico compartilhado, nao entrega viva. |
| `MISCRED.VNP_CONSOLIDADO` | 1 | 3 | fonte compartilhada | Schema MISCRED; VNP_WINSCP grava e Base_Bruta(Atacado/Credito) leem [PROC SQL - FROM]. Base VNP consolidada compartilhada; fecha aresta VNP->Base_Bruta como fonte. |
| `PME.BASE_HBV8_SERASA_PJ` | 1 | 4 | fonte compartilhada | Schema PME (Serasa HBV8); SalesFinance a le e grava (INTERNAL READS+OUTPUTS); 4 readers. Enriquecimento Serasa compartilhado. |
| `PME.BASE_FATURAMENTO_SERASA_PJ` | 1 | 4 | fonte compartilhada | Esteira 2 a tem em INTERNAL READS e PERMANENT OUTPUTS (read-modify-write); 4 readers. Faturamento Serasa PJ no schema PME, fonte comum. |
| `PME.BASE_CADASTRAL_SERASA_PJ` | 1 | 3 | fonte compartilhada | Cadastral Serasa PJ no schema PME; Painel Sales Finance grava, Base_Bruta/Motores leem [PROC SQL - JOIN]. Cadastro Serasa compartilhado, nao entrega dedicada. |
| `INSIGHT.TBBRUTA_20250731` | 1 | 2 | fonte compartilhada | Snapshot datado de INSIGHT.TBBRUTA; Base_Carteira grava, Controle_PMES le via lib.member dinamico (%LET). Snapshot da base bruta compartilhada, nao entrega viva. |
| `_INSIGHT.TBMGCANALITICA` | 1 | 2 | colisão de nome | Libref com prefixo '_' (alias de INSIGHT). Credito Motores e Atacado Motores AMBOS leem _INSIGHT.TBMGCANALITICA e gravam PME.TBMGCANALITICA; os dois Motores sao quase-clones. Arest |
| `MISCRED.BASE_UNICA_ATACADO_202408 (dup)` | 1 | 2 | incerto | Ja classificada como fonte_compartilhada; mantida por completude. Snapshot MISCRED versionado. |
| `PME.BASE_HISTORICA_OMIE_CEDENTES` | 1 | 2 | handoff real | 1 writer (OMIE Sacados) -> reader Credito Motores; schema PME mas especifica do fluxo OMIE. Producao OMIE->Motores genuina. |
| `PME.BASE_SUSPENSAO_GL` | 1 | 2 | handoff real | 1 writer Atacado Motores -> reader Esteira 2 (alem do self). Suspensoes GL especificas dos Motores; handoff intra-Atacado. |
| `PME.TBMGCANALITICA` | 1 | 2 | handoff real | Atacado Motores grava PME.TBMGCANALITICA -> reader Painel Sales Finance. Saida analitica MGC; handoff intra-Atacado. |
| `INSIGHT.BASE_BACEN_FINAL` | 1 | 2 | handoff real | Esteira 2 grava INSIGHT.BASE_BACEN_FINAL (tambem self read-modify-write) -> reader Base_Sinais. Saida BACEN especifica da Esteira; handoff intra-Atacado. |
| `INSIGHT.TBPMEANALITICA` | 1 | 2 | handoff real | Esteira 2 grava -> Painel Sales Finance le. Analitica PME da Esteira; handoff intra-Atacado. |
| `INSIGHT.BASE_DIREITOS_CREDITORIOS` | 1 | 2 | handoff real | Project_semiUpper grava -> Esteira 2 le. Direitos creditorios; handoff intra-Atacado (fecha mutual com PME.BASE_FATURAMENTO). |
| `INSIGHT.TB_GARANTIAS_ANALITICO` | 1 | 4 | handoff real | Credito Base_Bruta grava -> readers Atacado (Base_Sinais, Esteira 2, Project_semiUpper). Garantias analitico; handoff Credito->Atacado genuino (cross-area). |
| `ATUAL.CLIENTES_ATUAL_2025` | 1 | 2 | handoff real | Base_Carteira_Consolidada grava -> CIB le. Fecha 2-cycle com INSIGHT.TBPESSOA; lado A->B e handoff real, lado B->A (TBPESSOA) e fonte compartilhada. |
| `ATUAL.CLIENTES_ATUAL_2026` | 1 | 2 | handoff real | Base_Carteira_Consolidada grava -> Painel Sales Finance le. Lista de clientes do ano; handoff intra-Atacado. |
| `PDD.INFOS_PME` | 1 | 3 | handoff real | Controle_PMES grava PDD.INFOS_PME (+_BKP) e Indicadores/Base_Unica leem. Handoff Riscos real; metade do 2-cycle Controle<->Indicadores. |
| `MONITRCA.NE_DESEMBOLSOS` | 1 | 2 | handoff real | Indicadores grava MONITRCA.NE_DESEMBOLSOS -> Controle_PMES le [PROC SQL - FROM]. Outra metade do 2-cycle Riscos real (Indicadores->Controle). |
| `SME.BASE_HISTORICA_SME_PJ` | 1 | 2 | handoff real | Controle_PMES grava (tambem self) -> Base_Unica le. Base historica SME PJ; handoff intra-Riscos. |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Concordo com artefato_parcial; o veredito resiste a verificacao adversarial. Confirmei no codigo o nucleo que SUSTENTA o). A grande maioria das 35 tabelas que fecham o SCC sao FONTES/STAGING de schemas corporativos compartilhados (INSIGHT., PME., PLCA., SHAREATA., SIC., MISCRED., GCSERASA.) lidas e regravadas por multiplos projetos — confirmado pelo padrao read-modify-write (mesma tabela em INTERNAL READS e PERMANENT OU

**Como quebrar:**

- `(fonte)` → `TODOS os 16 projetos` via `INSIGHT.TBBRUTA` — Externalizar como SOURCE unica. Materializar a base bruta uma vez (projeto/modelo dedicado) e fazer todos os outros consumirem via source()/ref unico; proibir regravacao por multiplos projetos. Remove a aresta que sozinha conecta 16 readers.
- `(fonte)` → `12 readers` via `PLCA.TBSISTEMAPLCA, INSIGHT.TBVNP, INSIGHT.TBPESSOA, SHAREATA.TBCARTEIRAGRUPO, SHAREATA.TBCARTEIRACLIENTE, SHAREATA.TBRATING_V2, SIC.DMRELATIOLIMITESHIST` — Tratar todos os objetos dos schemas PLCA./SHAREATA./SIC./DBGLOBAL. como sources externas (ingestao corporativa). Quebrar o read-modify-write de Base_Bruta/CIB: separar 'refresh da fonte' de 'consumo'. Elimina as arestas CIB->Base_Bruta, Base_Bruta->(quase tudo).
- `(fonte)` → `Motores/Painel/esteiras` via `PME.BASE_SCORE_SERASA_PJ, PME.BASE_RESTR_SERASA_PJ, PME.BASE_SOCIOS_SERASA_PJ, PME.BASE_HBV8_SERASA_PJ, PME.BASE_CADASTRAL_SERASA_PJ, PME.BASE_FATURAMENTO_SERASA_PJ, PME.BASE_HISTORICA_PMUM_SF, GCSERASA.TBGCDADOSCADASTRAIS` — Consolidar o enriquecimento Serasa (schemas PME./GCSERASA.) num unico pipeline de ingestao Serasa e expor como sources. As esteiras OMIE/SalesFinance hoje gravam as MESMAS tabelas (multi-writer) — unificar para um so writer por tabela. Quebra as arestas das esteiras->Painel/Motores.
- `(fonte)` → `Base_Unica e outros` via `MISCRED.MATRIZ_SETORES, MISCRED.BASE_CLIENTES, MISCRED.TBCRED_BASE_GLOBAL_*, MISCRED.BASE_UNICA_ATACADO_*, MISCRED.VNP_CONSOLIDADO` — Schema MISCRED. vira camada de sources/snapshots; snapshots datados (BASE_UNICA_ATACADO_AAAAMM, TBBRUTA_20250731) nao devem ser arestas vivas. Remove arestas Base_Unica->* e VNP->Base_Bruta.
- `[Gestão_de_Carteira] Motores` → `[Gestão_de_Carteira] Motores` via `_INSIGHT.TBMGCANALITICA` — Colisao de libref: '_INSIGHT' e alias de INSIGHT e os dois Motores sao quase-clones que gravam PME.TBMGCANALITICA. Desambiguar o libref e tratar como fonte INSIGHT compartilhada; nao e entrega Credito->Atacado. Considerar fundir os dois Motores num unico modelo parametrizado por area.
- `Indicadores_PMEs_PPT_V3` → `Controle_PMES_v19__v2` via `MONITRCA.NE_DESEMBOLSOS` — CICLO REAL intra-Riscos. Quebrar esta aresta de retorno: materializar NE_DESEMBOLSOS de uma versao/snapshot anterior (defasagem temporal) OU extrair o calculo de NE_DESEMBOLSOS para um modelo upstream comum consumido pelos dois, eliminando a dependencia mutua com PDD.INFOS_PME.

**Recomendação:** Acao 1 (resolve ~90% do cluster): promover os schemas corporativos compartilhados (INSIGHT., PME., PLCA., SHAREATA., SIC., MISCRED., GCSERASA., DBGLOBAL.) a SOURCES EXTERNAS UNICAS no dbt, com exatamente UM produtor por tabela. Hoje varios projetos fazem read-modify-write da mesma tabela (ela aparece em INTERNAL READS e PERMANENT OUTPUTS do mesmo .egp) e ha tabelas multi-writer (INSIGHT.TBBRUTA com 5 writers; PME Serasa e SHAREATA com 2-3) — isso e o que inventa as arestas ciclicas. INSIGHT.TBBRUTA isolada ja desconecta 16 readers. Acao 2: separar 'refresh da fonte' do 'consumo' em Base_Bruta e CIB para matar o 2-cycle Base_Carteira_Consolidada<->CIB (lado INSIGHT.TBPESSOA e fonte; so ATUAL.CLIENTES_ATUAL_2025 e handoff real). Acao 3: desambiguar o libref _INSIGHT.TBMGCANALITICA e avaliar fundir os dois projetos [Gestão_de_Carteira] Motores (Atacado/Crédito), que sao quase-clones. Acao 4 (unico ciclo realmente intrinseco): quebrar manualmente o par mutuo Riscos Controle_PMES_v19 <-> Indicadores_PMEs cortando a aresta de retorno MONITRCA.NE_DESEMBOLSOS (consumir snapshot/versao anterior ou extrair o calculo para um modelo upstream comum). Apos isso o cluster deixa de ser SCC e migra em ondas por dependencia normal; manter como handoffs reais apenas: TB_GARANTIAS_ANALITICO (Crédito->Atacado), as saidas intra-Atacado da Esteira 2/Project_semiUpper/Painel/Base_Carteira, e PDD.INFOS_PME/SME.BASE_HISTORICA_SME_PJ (intra-Riscos).

### Cluster #2 — 9 projetos · Cobranças — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| 20250918_darkpost_v15 | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 8 | 4 |
| ALIMENTAR DASH - NPSv10 - copia | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 57 | 150 |
| Processo_NPS_UNICO_SEG_DIG | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 61 | 128 |
| Project_Atualiza_Base_Acesso_Site_App_GCP | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 3 | 2 |
| Project_Atualiza_Base_D0 | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 4 | 4 |
| Project_Atualiza_Base_Eventos_Whats | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 8 | 7 |
| Project_Atualiza_Base_Hash_BV | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 5 | 3 |
| Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 78 | 39 |
| Project_Controle_Envios_HSM | Cobranças | Onda 1 (Ciclo - quebrar manualmente) | 4 | 1 |

**O laço:** Cluster de 9 projetos, todos da area Cobranças, girando em torno da biblioteca SAS compartilhada CONTATOS (caminho fisico identico em todos: /riscosbv/cobranca/rribeiro/contatos) e da config TCONFIG (/riscosbv/cobranca/rribeiro/config_trilha_geral). O 'ciclo' nao e um pipeline circular real de negocio: e a consequencia de tratar leitura/escrita numa CAMADA DE DADOS PERSISTENTE COMPARTILHADA (tabelas MDM/AUX de contatos) como se fosse handoff ponto-a-ponto projeto->projeto. O projeto-hub Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH e o verdadeiro job de construcao da camada: le das tabelas de producao BigQuery (BV-PDBD-PRD.*) e CRIA a maioria das CONTATOS.AUX_*/COB_MDM_* (62 refs a AUX_BASE_CYBER, faz o unico CREATE TABLE). Os demais projetos em sua maioria so LEEM essas tabelas; alguns fazem UPDATE incremental na MESMA tabela fisica (ex.: D0 e Eventos_Whats dao UPDATE CONTATOS.AUX_BASE_CYBER), o que o inventario contou como 'writer' e gerou arestas de retorno falsas. Soma-se colisao de nome temporario (darkpost faz PROC SORT OUT=COB_MDM_TELEFONE sem libref = WORK.COB_MDM_TELEFONE, mas so LE a CONTATOS.COB_MDM_TELEFONE real). Restam poucos handoffs incrementais genuinos em volta do hub (AUX_SYNAPSE_MDM_TEL, AUX_QUARENTENA_TEL, AUX_HIST_INTERACAO_WHATS, AUX_BASE_CYBER_D0, AUX_BASE_HASH) que formam um laco de atualizacao mutua real, porem pequeno.

**Exemplos de ciclo:**

- 20250918_darkpost_v15 → ALIMENTAR DASH - NPSv10 - copia → 20250918_darkpost_v15
- 20250918_darkpost_v15 → ALIMENTAR DASH - NPSv10 - copia → Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH → 20250918_darkpost_v15
- 20250918_darkpost_v15 → ALIMENTAR DASH - NPSv10 - copia → Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH → Project_Atualiza_Base_Eventos_Whats → 20250918_darkpost_v15

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `CONTATOS.AUX_BASE_CYBER` | 4 | 6 | fonte compartilhada | CONTATOS = /riscosbv/cobranca/rribeiro/contatos (mesmo path fisico em todos). So o hub ORAHASH faz CREATE TABLE CONTATOS.AUX_BASE_CYBER (linha 1161); D0 (l.257) e Eventos_Whats (l. |
| `CONTATOS.COB_MDM_TELEFONE` | 2 | 4 | fonte compartilhada | Unico CREATE real e do hub ORAHASH. darkpost so LE (l.85,382) e cria um WORK.COB_MDM_TELEFONE temp (PROC SORT OUT=COB_MDM_TELEFONE sem libref, l.386) - colisao de nome contada como |
| `CONTATOS.COB_MDM_EMAIL` | 2 | 3 | fonte compartilhada | Mesmo padrao do COB_MDM_TELEFONE: tabela MDM da lib compartilhada CONTATOS, criada pelo hub e lida por muitos; writers extra sao UPDATE/temp. |
| `CONTATOS.COB_MDM_TELEFONE_BKPD3` | 2 | 2 | fonte compartilhada | Backup D-3 da tabela MDM telefone na lib compartilhada CONTATOS; aparece em 6 arquivos. Dois 'writers' (NPSdash e hub) indicam reescrita/backup da mesma fisica, nao handoff dedicad |
| `CONTATOS.AUX_SYNAPSE_MDM_TEL` | 1 | 4 | fonte compartilhada | CREATE unico no hub ORAHASH (1 writer). Lida por 12 projetos da area (grep), so 4 no cluster: tabela de referencia MDM/Synapse compartilhada. Alimenta darkpost/D0/Eventos = fan-out |
| `TCONFIG.CONFIG_TPENTRADA` | 1 | 3 | fonte compartilhada | TCONFIG = /riscosbv/cobranca/rribeiro/config_trilha_geral (lib de config compartilhada). Tabela de configuracao/lookup lida por 16 projetos da area (grep), so 3 no cluster. E o lad |
| `RATINHO.RATINHO_UNIFICADO` | 1 | 2 | fonte compartilhada | Lib RATINHO separada; nao foi encontrado CREATE/INSERT no cluster (provavel fonte externa/ingestao em outra lib). Lida pelo hub e pelo HSM - tabela unificada compartilhada, candida |
| `CONTATOS.AUX_BASE_HASH` | 1 | 2 | incerto | (linha duplicada conceitualmente coberta acima por AUX_BASE_HASH - sem evidencia adicional) |
| `CONTATOS.AUX_BASE_HASH` | 1 | 2 | handoff real | 1 writer (Project_Atualiza_Base_Hash_BV faz o CREATE) -> lido por Acesso_Site_App_GCP e pelo hub. Producao genuina projeto->projeto (gera o hash que os outros consomem). |
| `CONTATOS.AUX_BASE_CYBER_D0` | 1 | 2 | handoff real | 1 writer (Project_Atualiza_Base_D0: INSERT INTO / DELETE FROM, l.154/163, e PERMANENT OUTPUT) -> lido pelo hub ORAHASH. Recorte D0 da base cyber produzido pelo D0 para o hub. |
| `CONTATOS.AUX_HIST_INTERACAO_WHATS` | 1 | 2 | handoff real | 1 writer (Project_Controle_Envios_HSM cria) -> lido pelo hub ORAHASH (e por si mesmo). Historico de interacao WhatsApp produzido pelo HSM e consumido pelo hub. |
| `CONTATOS.AUX_QUARENTENA_TEL` | 1 | 2 | handoff real | 1 writer (Project_Atualiza_Base_Eventos_Whats cria, e PERMANENT OUTPUT) -> lido pelo hub ORAHASH. Quarentena de telefones produzida pelo Eventos e consumida pelo hub (lado A->B do  |
| `CONTATOS.AUX_HIST_ACESSO_APP` | 1 | 1 | handoff real | 1 writer (Acesso_Site_App_GCP cria) -> 1 reader (hub ORAHASH). Handoff limpo de historico de acesso app. |
| `CONTATOS.AUX_HIST_ACESSO_SITE` | 1 | 1 | handoff real | 1 writer (Acesso_Site_App_GCP) -> 1 reader (hub ORAHASH). Handoff limpo de historico de acesso site. |
| `CONTATOS.AUX_CYBER_ALCADAS` | 1 | 2 | handoff real | 1 writer (hub ORAHASH) -> lido por darkpost (e pelo hub). Derivado da base cyber produzido pelo hub para o darkpost. |
| `CONTATOS.AUX_IQ_ACAO_CONTRA` | 1 | 2 | handoff real | 1 writer (hub ORAHASH) -> lido por darkpost (e pelo hub). Handoff hub->darkpost. |
| `CONTATOS.AUX_SYNAPSE_MDM_EMAIL` | 1 | 2 | handoff real | 1 writer (hub ORAHASH) -> lido por darkpost (e pelo hub). Par email do AUX_SYNAPSE_MDM_TEL; producao do hub consumida pelo darkpost. |
| `NPS.BA_ESTOQUE_NPSENVIO` | 1 | 2 | handoff real | 1 writer (Processo_NPS_UNICO_SEG_DIG) -> lido por ALIMENTAR DASH NPS (e por si). Estoque de envios NPS produzido pelo processo NPS e consumido pelo dashboard. Aparece em 6 arquivos |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Concordo com o veredito artefato_parcial; o investigador acertou no nucleo e na maioria das evidencias, mas cometeu UM e). A maior parte das arestas que fecham o ciclo desaparece quando as tabelas da lib compartilhada CONTATOS (AUX_BASE_CYBER, COB_MDM_TELEFONE, COB_MDM_EMAIL, AUX_SYNAPSE_MDM_TEL/EMAIL, BKPD3), de TCONFIG (CONFIG_TPENTRADA, lida por 16 projetos) e de RATINHO (RATINHO_UNIFICADO) viram SOURCES unicas: sao 

**Como quebrar:**

- `ALIMENTAR DASH - NPSv10 - copia` → `20250918_darkpost_v15` via `TCONFIG.CONFIG_TPENTRADA` — Externalizar: TCONFIG.CONFIG_TPENTRADA e config compartilhada (lida por 16 projetos). Vira source/seed unica (dbt source ou seed). Remove o lado de retorno do 2-cycle darkpost<->NPSdash.
- `ALIMENTAR DASH - NPSv10 - copia` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` via `TCONFIG.CONFIG_TPENTRADA` — Mesma source unica TCONFIG.CONFIG_TPENTRADA; nenhum projeto deve 'produzir' essa config para o hub.
- `20250918_darkpost_v15` → `ALIMENTAR DASH - NPSv10 - copia` via `CONTATOS.COB_MDM_TELEFONE` — Falso writer: darkpost so LE CONTATOS.COB_MDM_TELEFONE e cria WORK.COB_MDM_TELEFONE temp (PROC SORT OUT= sem libref). Corrigir o inventario para nao marcar darkpost como writer; o unico produtor e o hub ORAHASH. Aresta deixa de existir.
- `20250918_darkpost_v15` → `Project_Atualiza_Base_D0` via `CONTATOS.COB_MDM_EMAIL / CONTATOS.COB_MDM_TELEFONE` — Idem: COB_MDM_EMAIL/TELEFONE sao MDM produzidos pelo hub. Reapontar leitores para a versao do hub (source/ref do hub); remover atribuicao de writer ao darkpost.
- `Project_Atualiza_Base_D0` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` via `CONTATOS.AUX_BASE_CYBER (UPDATE)` — Separar responsabilidade de escrita: o hub CRIA AUX_BASE_CYBER; D0/Eventos apenas dao UPDATE incremental. Modelar AUX_BASE_CYBER como tabela canonica do hub e mover os UPDATEs para colunas/modelos derivados proprios (ex.: AUX_BASE_CYBER_D0 ja existe), evitando 2+ projetos escreverem a mesma fisica.
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `Project_Atualiza_Base_Eventos_Whats` via `CONTATOS.AUX_SYNAPSE_MDM_TEL` — AUX_SYNAPSE_MDM_TEL e tabela de referencia MDM com fan-out (4 leitores, 12 na area). Externalizar como source/ref unica do hub; Eventos passa a ref() o modelo do hub. Quebra o lado hub->Eventos do 2-cycle real.
- `Project_Atualiza_Base_Eventos_Whats` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` via `CONTATOS.AUX_QUARENTENA_TEL` — Handoff incremental genuino (Eventos produz quarentena, hub consome). Manter como ref() Eventos->hub e ORDENAR manualmente Eventos ANTES do hub. Se o hub tambem alimentar dado que Eventos precisa, dividir o hub em duas etapas (pre-MDM e pos-incrementais) para romper a mutualidade.
- `Project_Controle_Envios_HSM` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` via `CONTATOS.AUX_HIST_INTERACAO_WHATS` — Handoff real HSM->hub. Manter ref() HSM->hub e quebrar o retorno hub->HSM (via RATINHO.RATINHO_UNIFICADO) externalizando RATINHO_UNIFICADO como source unica.
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `Project_Controle_Envios_HSM` via `RATINHO.RATINHO_UNIFICADO` — RATINHO_UNIFICADO nao tem CREATE no cluster (fonte externa). Declarar como source unica; HSM le source, nao 'depende' do hub. Quebra o 2-cycle hub<->HSM.

**Recomendação:** Tratar o cluster como uma CAMADA COMPARTILHADA + um nucleo de incrementais, nao como ciclo de negocio. Passos: (1) Promover a SOURCES/seeds unicos todas as tabelas de fonte/config compartilhada: TCONFIG.CONFIG_TPENTRADA (config, 16 leitores), RATINHO.RATINHO_UNIFICADO (sem produtor no cluster), e as MDM CONTATOS.COB_MDM_TELEFONE/COB_MDM_EMAIL/AUX_SYNAPSE_MDM_TEL/AUX_SYNAPSE_MDM_EMAIL/COB_MDM_TELEFONE_BKPD3/AUX_BASE_CYBER - todas produzidas pelo hub ORAHASH e lidas pela area inteira; cada leitor passa a ref()/source() a versao canonica do hub em vez de 'depender' de quem por acaso escreveu por ultimo. Isso sozinho elimina as 2-cycles darkpost<->NPSdash e a maioria das arestas de retorno. (2) Corrigir falsos writers no inventario 06: PROC SORT/DATA OUT= sem libref cria WORK.* (ex.: darkpost WORK.COB_MDM_TELEFONE) e nao deve contar como writer da tabela CONTATOS; UPDATE de tabela compartilhada (D0/Eventos em AUX_BASE_CYBER) tambem nao e 'producao' e deve ser desambiguado. (3) Para o nucleo de handoffs incrementais reais em volta do hub (AUX_QUARENTENA_TEL Eventos->hub, AUX_BASE_CYBER_D0 D0->hub, AUX_HIST_INTERACAO_WHATS HSM->hub, AUX_BASE_HASH/AUX_HIST_ACESSO_* Hash_BV/Acesso->hub), definir ordem topologica manual: Hash_BV -> Acesso_Site_App -> (D0, Eventos_Whats, HSM produzem seus recortes) -> hub ORAHASH (consolida) -> darkpost/NPSdash/Processo_NPS (consomem). Se persistir mutualidade hub<->Eventos, DIVIDIR o hub ORAHASH em duas etapas (hub_pre: constroi MDM a partir de BV-PDBD-PRD; hub_pos: consolida os incrementais), quebrando o laco sem alterar logica de negocio. Resultado esperado: cluster colapsa de 9 nos ciclicos para um DAG com 1 source layer + 1 hub em 2 etapas + leitores downstream.

### Cluster #3 — 8 projetos · SAS_UC4 — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| ext_originacao | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 25 | 11 |
| ext_parceirocomercial | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 38 | 27 |
| ext_producao | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 28 | 16 |
| ext_resultadogerencial | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 5 | 6 |
| ext_taxamercado | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 3 | 9 |
| tbpotencialpdvs | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 9 | 8 |
| tbpotencialrodas | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 11 | 19 |
| tbprospeccaoprivado | SAS_UC4 | Onda 7 (Ciclo - quebrar manualmente) | 12 | 66 |

**O laço:** Cluster de 8 projetos SAS_UC4 (todos compartilham as MESMAS libnames físicas BASES/BASEGRC/TMP/AUXL via include comum /projetos/MISV/sas-misv-base-lib/scripts/libname.sas — logo, tabelas com prefixo são tabelas físicas reais, não colisões). O laço NÃO é por uma única tabela, mas por uma teia de handoffs físicos genuínos entre marts derivados. Laços principais: (1) producao <-> resultadogerencial: producao escreve TMP.TBPRODUCAO -> resultadogerencial lê para calcular BASES.TBRESULTADOGERENCIAL -> producao RE-LÊ BASES.TBRESULTADOGERENCIAL (left join, linha 1083) para enriquecer sua própria saída (feedback de período anterior). (2) parceirocomercial -> {originacao, producao, pdvs, prospeccao} via TMP.TBPARCEIROCOMERCIAL e BASES.BASE_DSLOGIN_ORIGINADOR; e volta: prospeccao escreve BASEGRC.TBPRIVADOCONVENIOFUNCIONARIOS que parceirocomercial lê, e tbpotencialrodas escreve TMP.TBPOTENCIALRODAS que parceirocomercial lê -> fecha o anel parceiro->rodas->parceiro e parceiro->prospeccao->parceiro. (3) taxamercado produz BASES.TBDIMTAXAMERCADO lido por originacao e producao; e producao escreve BASEGRC.TBPROPOSTAMULTIBANCO/TBRASTREADOR lidos por originacao. A única aresta FALSA é originacao->taxamercado via TBDATACORTE: é colisão de nome (WORK temp em originacao vs CTE local dentro de passthrough DBCON em taxamercado). Removê-la não desfaz o ciclo; o SCC continua real.

**Exemplos de ciclo:**

- ext_originacao → ext_taxamercado → ext_originacao
- ext_originacao → ext_taxamercado → ext_producao → ext_originacao
- ext_originacao → ext_taxamercado → ext_producao → tbpotencialrodas → ext_parceirocomercial → ext_originacao

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `TBDATACORTE` | 1 | 1 | colisão de nome | originacao: 'DATA TbDataCorte;' não-qualificada = WORK temp (listada em TEMP/DISCARDED OUTPUTS). taxamercado: 'TbDataCorte AS' é CTE local dentro de 'select * from TbDataCorte' em  |
| `BASEGRC.TBPRIVADOCONVENIOFUNCIONARIOS` | 1 | 1 | handoff real | prospeccaoprivado declara PERMANENT OUTPUT; parceirocomercial linha 774 'left join basegrc.TbPrivadoConvenioFuncionarios' (PROC SQL JOIN). Mart físico em lib compartilhada, 1 produ |
| `BASEGRC.TBPROPOSTAMULTIBANCO` | 1 | 1 | handoff real | producao escreve via proc append/DATA (PERMANENT OUTPUT); originacao linha 714 'left join basegrc.Tbpropostamultibanco' on nuproposta. Handoff producao->originacao genuíno. |
| `BASEGRC.TBRASTREADOR` | 1 | 1 | handoff real | producao: linha 299 'proc append base=basegrc.TbRastreador'; originacao linha 710 'left join basegrc.TbRastreador'. Produção -> consumo cross-projeto real. |
| `BASES.BASE_DSLOGIN_ORIGINADOR` | 1 | 2 | handoff real | parceirocomercial é o único writer (PERMANENT OUTPUT BASES.BASE_DSLOGIN_ORIGINADOR); originacao (linha 720 'left join Bases.Base_DsLogin_Originador') e producao leem. 1 writer -> 2 |
| `BASES.TBDIMTAXAMERCADO` | 1 | 2 | handoff real | taxamercado tem como ÚNICA saída BASES.TBDIMTAXAMERCADO (PERMANENT OUTPUT); originacao (linha 684 join) e producao leem. É dimensão derivada produzida por 1 projeto-membro, não fon |
| `BASES.TBRESULTADOGERENCIAL` | 1 | 1 | handoff real | resultadogerencial: 'data bases.TbResultadoGerencial' (linhas 161-183, PERMANENT OUTPUT, escreve/atualiza); producao linha 1083 'left join bases.TbResultadoGerencial'. Fecha 2-cycl |
| `TMP.TBEXTPROPOSTA` | 1 | 1 | handoff real | originacao PERMANENT OUTPUT TMP.TBEXTPROPOSTA; tbpotencialrodas a lê. TMP é lib física compartilhada (não WORK), handoff real originacao->rodas. |
| `TMP.TBORIGINACAO` | 1 | 1 | handoff real | originacao PERMANENT OUTPUT TMP.TBORIGINACAO; tbpotencialrodas a lê. Tabela física em /projetos/MISV/data/bases/tmp/tboriginacao.sas7bdat (citada nos paths externos). Handoff genuí |
| `TMP.TBPARCEIROCOMERCIAL` | 1 | 4 | handoff real | parceirocomercial é único writer (PERMANENT OUTPUT); lida por originacao/producao/pdvs/prospeccao via 'tmp.TbParceiroComercial' (ex.: originacao linhas 201/675). Fan-out de 1 produ |
| `TMP.TBPOTENCIALPDVS` | 1 | 1 | handoff real | tbpotencialpdvs único PERMANENT OUTPUT TMP.TBPOTENCIALPDVS; tbpotencialrodas a lê. 1->1. |
| `TMP.TBPOTENCIALRODAS` | 1 | 1 | handoff real | tbpotencialrodas PERMANENT OUTPUT TMP.TBPOTENCIALRODAS; parceirocomercial linha 831 'FROM TMP.TBPOTENCIALRODAS A'. Back-edge que fecha o anel rodas->parceiro. |
| `TMP.TBPRODUCAO` | 1 | 3 | handoff real | producao PERMANENT OUTPUT TMP.TBPRODUCAO; lida por resultadogerencial (join), tbpotencialrodas e prospeccao. Fan-out 1->3; núcleo do 2-cycle com BASES.TBRESULTADOGERENCIAL. |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Verdito e classificacoes corretos e bem evidenciados; confirmei no codigo: (a) TBDATACORTE e de fato colisao de nome/are). A grande maioria das arestas são handoffs físicos reais (TMP/BASES/BASEGRC são libs físicas compartilhadas via libname.sas comum, confirmado por reads em PROC SQL JOIN / proc append / data step no código). Há um SCC real: producao<->resultadogerencial é mútuo genuíno (TMP.TBPRODUCAO ida, BASES.TBRES

**Como quebrar:**

- `ext_originacao` → `ext_taxamercado` via `TBDATACORTE` — REMOVER aresta do grafo — colisão de nome (WORK temp em originacao vs CTE local em passthrough DBCON em taxamercado). Não é dependência; corrigir o inventário 06 para não casar nomes não-qualificados/CTEs.
- `ext_resultadogerencial` → `ext_producao` via `BASES.TBRESULTADOGERENCIAL` — QUEBRAR o 2-cycle: producao re-lê BASES.TBRESULTADOGERENCIAL (left join linha 1083) que resultadogerencial produz a partir de TMP.TBPRODUCAO. Em dbt, materializar TBRESULTADOGERENCIAL e fazer producao referenciar o SNAPSHOT do período/run ANTERIOR (source/snapshot), não o ref do mesmo run. Assim a dependência cíclica vira temporal e o DAG fica acíclico.
- `ext_producao` → `ext_originacao` via `BASEGRC.TBPROPOSTAMULTIBANCO / BASEGRC.TBRASTREADOR` — Avaliar se producao deve ser DIVIDIDA: a geração de TBPROPOSTAMULTIBANCO/TBRASTREADOR (proc append, dimensões de proposta/rastreador) é upstream de originacao, mas producao também depende de originacao/parceiro/taxa. Extrair o bloco que materializa TBPROPOSTAMULTIBANCO/TBRASTREADOR para um modelo/projeto staging próprio (ex. stg_proposta_multibanco) que originacao consome — quebra a aresta producao->originacao sem tocar no resto.

**Recomendação:** Sequência recomendada para tornar o DAG acíclico: 1) Corrigir o inventário: remover a aresta originacao->taxamercado (TBDATACORTE é colisão WORK/CTE) — único artefato. 2) Externalizar como SOURCE/snapshot a leitura de retorno BASES.TBRESULTADOGERENCIAL dentro de ext_producao: producao só RE-LÊ o gerencial do período anterior para enriquecer; tratar como source de snapshot (run anterior) quebra o 2-cycle producao<->resultadogerencial sem perda funcional. 3) Dividir ext_producao: mover a materialização de BASEGRC.TBPROPOSTAMULTIBANCO e BASEGRC.TBRASTREADOR (dimensões de proposta upstream de originacao) para um staging dedicado; isso corta a aresta producao->originacao. Com (2)+(3) o anel grande producao->originacao->...->producao se abre. 4) As demais tabelas (TMP.TBPARCEIROCOMERCIAL fan-out 4, TMP.TBPRODUCAO fan-out 3, TBDIMTAXAMERCADO, BASE_DSLOGIN_ORIGINADOR, TBPOTENCIALRODAS, TBPRIVADOCONVENIOFUNCIONARIOS) são handoffs legítimos 1-writer; manter como refs dbt normais e ordenar pela topologia resultante. NÃO transformar TBPARCEIROCOMERCIAL nem TBPRODUCAO em source: têm 1 writer dentro do cluster, são marts derivados, e o fan-out sozinho não cria ciclo. Ordem de execução final esperada: parceirocomercial+taxamercado (raízes) -> originacao -> producao -> resultadogerencial / pdvs -> rodas -> prospeccao, com as 2 arestas de retorno (gerencial e potencialrodas->parceiro) resolvidas via snapshot de período anterior.

### Cluster #5 — 3 projetos · Atacado — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| Compilados_v27 | Atacado | Onda 2 (Ciclo - quebrar manualmente) | 22 | 40 |
| Consolidado_V68 | Atacado | Onda 2 (Ciclo - quebrar manualmente) | 97 | 60 |
| consultas_v8 | Atacado | Onda 2 (Ciclo - quebrar manualmente) | 50 | 22 |

**O laço:** Ciclo de 3 projetos da area Atacado (Compilados_v27, Consolidado_V68, consultas_v8) que compartilham duas bibliotecas SAS fisicas: EXTRATO e PASSIVOS. O laco principal nao e um handoff projeto-a-projeto limpo: e uma ZONA DE STAGING/SNAPSHOT MENSAL compartilhada (biblioteca EXTRATO) onde varios projetos LEEM e ESCREVEM tabelas de extrato datadas (EXTRATO.EXTRATO_YYYYMM, EXTRATO.EXTRATO_AAAA_ENCARTEIRAMENTO23). Dado que volta pra tras: (1) Consolidado escreve os snapshots mensais EXTRATO.EXTRATO_202404 / _2019_ENCARTEIRAMENTO23 / _2021_ENCARTEIRAMENTO23 / _202308 / _202402 que Compilados e consultas leem; (2) consultas escreve EXTRATO.EXTRATO_ENCART24_2023 que Consolidado le; (3) Compilados escreve EXTRATO.CLIENTES_ATIVOS e PASSIVOS.BOOK_PASSIVO_ANTERIOR/ATUAL que Consolidado le. Agravante: EXTRATO.EXTRATO_202404 e lido E reescrito no mesmo lugar (DATA EXTRATO.EXTRATO_202404; SET EXTRATO.EXTRATO_202404 - padrao restate/carimba), reforcando a aparencia de loop. So (3) e claramente handoff de produto de negocio; o resto e uso de uma fonte/area comum mensal.

**Exemplos de ciclo:**

- Compilados_v27 → Consolidado_V68 → Compilados_v27

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `EXTRATO.EXTRATO_202404` | 1 | 2 | fonte compartilhada | Snapshot mensal na biblioteca compartilhada EXTRATO, lido por 2 projetos (Compilados + consultas). Em Consolidado aparece em PERMANENT OUTPUTS mas tambem em EXTERNAL INPUTS e e ree |
| `EXTRATO.EXTRATO_2019_ENCARTEIRAMENTO23` | 1 | 1 | fonte compartilhada | Snapshot historico de extrato na lib EXTRATO. Consolidado o cria (PERMANENT OUTPUTS; DATA EXTRATO.EXTRATO_2019_ENCARTEIRAMENTO23 linhas 10902/11715/30528) mas tambem le (SET na mes |
| `EXTRATO.EXTRATO_2021_ENCARTEIRAMENTO23` | 1 | 1 | fonte compartilhada | Mesma natureza: extrato historico na lib compartilhada EXTRATO criado por Consolidado (linhas 9712/13180) e lido por consultas. Base historica comum. |
| `EXTRATO.EXTRATO_202308` | 1 | 1 | fonte compartilhada | Snapshot mensal EXTRATO; Consolidado escreve e tambem le no mesmo lugar (data extrato.EXTRATO_202308; set extrato.EXTRATO_202308 linhas 13210-13211); consultas le. Area comum de ex |
| `EXTRATO.EXTRATO_202402` | 1 | 1 | fonte compartilhada | Snapshot mensal; DATA EXTRATO.EXTRATO_202402; SET EXTRATO.EXTRATO_202402 (linhas 13375-13376) em Consolidado (restate in place); consultas le. Fonte mensal compartilhada. |
| `EXTRATO.EXTRATO_ENCART24_2023` | 1 | 1 | fonte compartilhada | consultas escreve de fato (DATA EXTRATO.EXTRATO_ENCART24_2023 linhas 3440/9785; consta em PERMANENT OUTPUTS de consultas) e Consolidado le (so SET/FROM, esta em EXTERNAL INPUTS de  |
| `EXTRATO.CLIENTES_ATIVOS` | 1 | 1 | handoff real | Compilados escreve de verdade (CREATE TABLE EXTRATO.CLIENTES_ATIVOS / DATA EXTRATO.CLIENTES_ATIVOS, linhas 725/735/744); Consolidado le via DATA Step SET (TABLE_READ_PROVENANCE: EX |
| `PASSIVOS.BOOK_PASSIVO_ANTERIOR` | 1 | 1 | handoff real | Compilados escreve (DATA PASSIVOS.BOOK_PASSIVO_ANTERIOR linha 2129; CREATE TABLE linha 2189); Consolidado le (PASSIVOS.BOOK_PASSIVO_ANTERIOR [PROC SQL - FROM]). Handoff real de boo |
| `PASSIVOS.BOOK_PASSIVO_ATUAL` | 1 | 1 | handoff real | Compilados escreve (DATA PASSIVOS.BOOK_PASSIVO_ATUAL linha 1946); Consolidado le (PASSIVOS.BOOK_PASSIVO_ATUAL [PROC SQL - FROM]). Handoff real. |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Concordo com o veredito artefato_parcial e com a recomendacao. A tese central foi confirmada no codigo, mas faltaram/err). Existe dependencia REAL e direcional Compilados->Consolidado via 3 produtos de negocio genuinos (EXTRATO.CLIENTES_ATIVOS, PASSIVOS.BOOK_PASSIVO_ANTERIOR, PASSIVOS.BOOK_PASSIVO_ATUAL - escritas confirmadas no codigo de Compilados). Porem o FECHAMENTO do ciclo (Consolidado/consultas -> de volta) acont

**Como quebrar:**

- `Consolidado_V68` → `Compilados_v27` via `EXTRATO.EXTRATO_202404` — Externalizar: promover os snapshots mensais EXTRATO.EXTRATO_YYYYMM a uma camada/source unica de extratos (ex. source/staging stg_atacado_extrato_mensal). Compilados passa a referenciar essa source, nao o output de Consolidado. Quebra a aresta de retorno Consolidado->Compilados.
- `Consolidado_V68` → `consultas_v8` via `EXTRATO.EXTRATO_2019_ENCARTEIRAMENTO23 / EXTRATO.EXTRATO_2021_ENCARTEIRAMENTO23 / EXTRATO.EXTRATO_202308 / EXTRATO.EXTRATO_202402 / EXTRATO.EXTRATO_202404` — Mesma medida: tratar todos os extratos mensais/historicos da lib EXTRATO como source compartilhada. consultas le da source, nao do Consolidado. Resolver o padrao read-modify-write (DATA X; SET X) extraindo a producao desses snapshots para um modelo de staging unico e idempotente.
- `consultas_v8` → `Consolidado_V68` via `EXTRATO.EXTRATO_ENCART24_2023` — Definir UM unico produtor de EXTRATO.EXTRATO_ENCART24_2023 (hoje consultas escreve, Consolidado so le): mover a producao para a camada de staging de encarteiramento e Consolidado consome via source/ref, eliminando o vinculo direto consultas->Consolidado.

**Recomendação:** Quebrar o ciclo externalizando a biblioteca EXTRATO como uma camada de SOURCE/STAGING unica de extratos mensais e de encarteiramento (EXTRATO.EXTRATO_YYYYMM, EXTRATO.EXTRATO_*_ENCARTEIRAMENTO23, EXTRATO.EXTRATO_ENCART24_2023). Passos concretos: (1) Criar uma fonte/modelo de staging unico para os snapshots mensais de extrato, com produtor unico e materializacao idempotente - isso elimina os padroes read-modify-write (DATA EXTRATO.EXTRATO_202404; SET EXTRATO.EXTRATO_202404) que falsificam o loop. (2) Reapontar Compilados e consultas para LER essa source em vez do output direto do outro projeto; isso corta as duas arestas de retorno (Consolidado->Compilados e Consolidado->consultas) e a aresta consultas->Consolidado. (3) Manter como UNICA dependencia direcional real Compilados_v27 -> Consolidado_V68 via EXTRATO.CLIENTES_ATIVOS, PASSIVOS.BOOK_PASSIVO_ANTERIOR e PASSIVOS.BOOK_PASSIVO_ATUAL (handoffs genuinos) - apos externalizar EXTRATO, o grafo vira aciclico e Compilados pode migrar antes de Consolidado. Ordem de migracao sugerida: source de extratos -> Compilados -> Consolidado/consultas. Nao e necessario dividir projetos; basta isolar a zona EXTRATO como fonte comum.

### Cluster #6 — 3 projetos · Rodas — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| IGE_NEW_EGV_Parceiros_digitais | Rodas | Onda 8 (Ciclo - quebrar manualmente) | 15 | 26 |
| IGE_NEW_Funil_EGV | Rodas | Onda 8 (Ciclo - quebrar manualmente) | 9 | 28 |
| filtrocvg | Rodas | Onda 8 (Ciclo - quebrar manualmente) | 11 | 3 |

**O laço:** Cluster de 3 projetos da area Rodas (todos Onda 8). O laco que fecha o ciclo e o par mutuo Parceiros_digitais <-> Funil_EGV: (1) Parceiros 'produz' as tabelas de-para AUXL.EGV_DEPARABALCAODIGITAL e AUXL.EGV_DEPARAPARCEIROSDIGITAIS, lidas por Funil; (2) Funil produz/atualiza TRIBO.EGV_PAP (CREATE + DELETE + append via DATA SET), lida por Parceiros (__4, PROC SQL FROM). Esse mutuo ja basta para o SCC. O terceiro projeto (filtrocvg) so alonga o caminho: ele tambem le as DEPARA da Parceiros e escreve BASEGRC.TBFILTROCVG, lida por Funil. O dado que 'volta pra tras' de verdade e o EGV_PAP (Funil -> Parceiros). As tabelas DEPARA voltando para Parceiros sao um artefato: na pratica sao seeds CSV estaticos que a Parceiros apenas carrega.

**Exemplos de ciclo:**

- IGE_NEW_EGV_Parceiros_digitais → IGE_NEW_Funil_EGV → IGE_NEW_EGV_Parceiros_digitais
- IGE_NEW_EGV_Parceiros_digitais → filtrocvg → IGE_NEW_Funil_EGV → IGE_NEW_EGV_Parceiros_digitais

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `AUXL.EGV_DEPARABALCAODIGITAL` | 1 | 3 | fonte compartilhada | Parceiros __2 nao deriva: importa CSV estatico (filename balcao '/infogrc/IGE_NEW/EGV/Parceiros_Digitais/DePara/EGV_DeParaBalcaoDigital.csv'; data AUXL.EGV_DeParaBalcaoDigital). Fu |
| `AUXL.EGV_DEPARAPARCEIROSDIGITAIS` | 1 | 3 | fonte compartilhada | Parceiros __1 importa CSV estatico (filename csvEGV '/infogrc/.../EGV_DeParaParceirosDigitais.csv'; data AUXL.EGV_DeParaParceirosDigitais). Lida como lookup por Funil __1 (PROC SQL |
| `TRIBO.EGV_PAP` | 1 | 2 | handoff real | Funil __1 e o unico produtor: 'create table EGV_PAP', 'DELETE * FROM TRIBO.EGV_PAP WHERE...', 'data TRIBO.EGV_PAP; set TRIBO.EGV_PAP EGV_PAP' (append historico). Parceiros __4 le n |
| `BASEGRC.TBFILTROCVG` | 1 | 1 | handoff real | filtrocvg __01 e o unico writer (data BASEGRC.TbFiltroCVG; set FiltroCVG; PERMANENT OUTPUTS: BASEGRC.TBFILTROCVG). Funil __1 le (L449 left join basegrc.tbfiltrocvg b on a.nupropost |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Praticamente nenhuma de fundo - a investigacao esta correta e bem evidenciada no codigo. Verifiquei: (1) Parceiros __1/_). Das 4 tabelas, 2 (as AUXL.EGV_DEPARA*) sao seeds CSV estaticos que a Parceiros apenas carrega - nao sao producao derivada, sao fonte compartilhada. Elas causam as arestas Parceiros->Funil e Parceiros->filtrocvg. Removendo-as (virando source/seed unica), essas arestas somem e o SCC quebra: sobra um D

**Como quebrar:**

- `IGE_NEW_EGV_Parceiros_digitais` → `IGE_NEW_Funil_EGV` via `AUXL.EGV_DEPARABALCAODIGITAL / AUXL.EGV_DEPARAPARCEIROSDIGITAIS` — Externalizar as duas tabelas DEPARA como seed/source unica (CSV em /infogrc/IGE_NEW/EGV/Parceiros_Digitais/DePara/) referenciada via source() por todos. A 'producao' pela Parceiros e so um PROC IMPORT; deixa de ser dependencia de projeto. Aresta deixa de existir.
- `IGE_NEW_EGV_Parceiros_digitais` → `filtrocvg` via `AUXL.EGV_DEPARABALCAODIGITAL / AUXL.EGV_DEPARAPARCEIROSDIGITAIS` — Mesma acao: filtrocvg passa a ler os seeds DEPARA via source() em vez de depender do output da Parceiros. Aresta eliminada - filtrocvg deixa de estar abaixo da Parceiros.

**Recomendação:** Quebrar o ciclo externalizando os dois de-para como dbt seeds/sources unicos (a partir dos CSV originais em /infogrc/IGE_NEW/EGV/Parceiros_Digitais/DePara/EGV_DeParaBalcaoDigital.csv e EGV_DeParaParceirosDigitais.csv): NAO modele AUXL.EGV_DEPARA* como output da Parceiros que alimenta Funil/filtrocvg; modele como source compartilhada que os tres referenciam. Isso elimina as arestas Parceiros->Funil e Parceiros->filtrocvg e dissolve o SCC. Sobra um DAG aciclico: filtrocvg (produz BASEGRC.TBFILTROCVG) -> Funil_EGV (produz TRIBO.EGV_PAP) -> Parceiros_digitais; os tres consomem os seeds DEPARA. Nao e preciso cortar nenhum handoff real (EGV_PAP e TBFILTROCVG ficam como ref() normais) nem dividir projetos. Recomendacao adicional: tratar BASEGRC.TBFILTROCVG como mart/source publicada (e lida por 10+ projetos fora do cluster), garantindo que filtrocvg seja migrado/materializado antes dos consumidores. Migrar nesta ordem: seeds DEPARA -> filtrocvg -> Funil_EGV -> Parceiros_digitais.

### Cluster #9 — 2 projetos · Riscos — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| ATUALIZACAO_BASES v09 | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 97 | 120 |
| Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 233 | 397 |

**O laço:** Ciclo de 2 projetos da área Riscos que são, na prática, dois estágios da MESMA rotina de Provisão Contábil Trabalhista. Ambos montam o MESMO library físico: `libname TRAB '/riscosbv/MRO/Modelos/ProvContTrab/RotinaCalculo'` (confirmado em ambos os .txt, linha 645 e dezenas de repetições). Por isso os datasets TRAB.* são os MESMOS arquivos em disco, lidos/escritos pelos dois lados. O laço bidirecional: (A→B) ATUALIZACAO_BASES escreve datasets-base mensais que o Calculo consome (ex.: TRAB.HISTORICO_201812, TRAB.BVT_POR_CPF, TRAB.TR_HIST_INDICE); (B→A) o Calculo escreve outros históricos mensais (TRAB.HISTORICO_202008, TRAB.HISTORICO_202011) que o ATUALIZACAO volta a ler. Ou seja, dado de histórico/garantias trabalhista circula nos dois sentidos pelo mesmo diretório compartilhado. Parte das 'arestas' são falsas: LT_INDICE e M_VALOR_INDICE NÃO são handoff — cada projeto faz seu próprio pull do Postgres bv-production (`connect to postgres ... CREATE TABLE M_VALOR_INDICE AS select * from connection to postgres`) numa tabela WORK sem prefixo de mesmo nome (colisão de nome).

**Exemplos de ciclo:**

- ATUALIZACAO_BASES v09 → Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud → ATUALIZACAO_BASES v09

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `LT_INDICE` | 1 | 1 | fonte compartilhada | Sem prefixo de lib; criada em A e B identicamente via pass-through Postgres bv-production (A:29171 'CREATE TABLE LT_INDICE AS select * from connection to postgres (SELECT * FROM LT |
| `M_VALOR_INDICE` | 1 | 1 | fonte compartilhada | Igual a LT_INDICE: A:29160 'CREATE TABLE M_VALOR_INDICE AS select * from connection to postgres (SELECT * FROM M_VALOR_INDICE)' (server 172.22.0.9 bv-production). Pull independente |
| `TRAB.GARANTIAS` | 1 | 2 | incerto | Inventario 06: writer=B. No corpo so achei A LENDO ('set TRAB.GARANTIAS' A:33177,100639) e B escrevendo um nome DIFERENTE 'data TRAB.GARANTIAS_UNIFICADAS_202202' (B:69601). A escri |
| `TRAB.HISTORICA` | 1 | 2 | incerto | Inventario 06: writer=B. No corpo so confirmei A LENDO ('SET TRAB.HISTORICA' A:15803,30134,88109); escrita bare por B nao aparece literal (provavel macro). Provavel base persistent |
| `TRAB.BVT_POR_CPF` | 1 | 2 | handoff real | A escreve: 'create table TRAB.BVT_POR_CPF (compress=yes index=(CPFNum/unique) ...) as' (A:8828). B le: 'left join TRAB.BVT_POR_CPF as mbvt' (B:1807,11856,17161). Mesmo lib fisico T |
| `TRAB.TR_HIST_INDICE` | 1 | 2 | handoff real | A escreve: 'DATA TRAB.TR_HIST_INDICE;' (A:8627). B le: 'left join TRAB.TR_HIST_INDICE as tini/tfim' (B:1414,1415,1804). Handoff A->B. |
| `TRAB.HISTORICO_201812` | 1 | 2 | handoff real | A escreve: 'DATA TRAB.HISTORICO_201812 (compress=yes PW=&DS_PASSWORD.);' (A:105555). B le: 'SET TRAB.HISTORICO_201812' (B:231671). Handoff A->B via lib compartilhada. |
| `TRAB.PARTEPRO_EXCLUSIVO` | 1 | 2 | handoff real | Atribuida pelo inventario 06 como writer=A. No corpo nao achei DATA/CREATE bare (provavel geracao via macro/&DSREFMODEL ou %INCLUDE); A a declara em 'INTERNAL READS' e B a consome. |
| `TRAB.PJ_GARANTIAS_PERDAS` | 1 | 2 | handoff real | Inventario 06: writer=A, readers=A+B. So existem no corpo as variantes mensais TRAB.PJ_GARANTIAS_PERDAS_&DSREFMODEL (write) e a bare na lista de INTERNAL READS; persistida no lib T |
| `TRAB.HISTORICO_202008` | 1 | 2 | handoff real | B escreve: 'CREATE TABLE TRAB.HISTORICO_202008 (pw=&DS_PASSWORD.) AS' (B:68279 e repeticoes). A le. Handoff B->A via lib TRAB compartilhado -> fecha o ciclo. |
| `TRAB.HISTORICO_202011` | 1 | 2 | handoff real | B escreve: 'CREATE TABLE TRAB.HISTORICO_202011 (pw=&DS_PASSWORD.) AS' (B:68231 e repeticoes). A le. Handoff B->A -> outra meia-volta do ciclo. |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Concordo com o veredito e a tese central. Verifiquei no codigo (caminhos absolutos: /home/lucasmuller_ind/bv/project_sas). Existe dependencia cruzada GENUINA (nao puramente artefato): A->B confirmado em codigo (TRAB.HISTORICO_201812, BVT_POR_CPF, TR_HIST_INDICE escritos por A e lidos por B) e B->A confirmado (TRAB.HISTORICO_202008/202011 escritos por B e lidos por A), todos via o MESMO library fisico TRAB '/riscosbv/MRO

**Como quebrar:**

- `ATUALIZACAO_BASES v09` → `Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` via `LT_INDICE / M_VALOR_INDICE` — Remover do grafo de dependencia projeto->projeto: nao sao handoff. Externalizar como UMA source unica dbt (origem Postgres bv-production: M_VALOR_INDICE, LT_INDICE). Ambos os projetos passam a referenciar a mesma source de indices, eliminando o vinculo aparente.
- `ATUALIZACAO_BASES v09` → `Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` via `TRAB.BVT_POR_CPF / TRAB.TR_HIST_INDICE / TRAB.HISTORICO_201812 / TRAB.PARTEPRO_EXCLUSIVO / TRAB.PJ_GARANTIAS_PERDAS` — Handoff real A->B: manter como dependencia direcional limpa. Materializar esses datasets como modelos dbt no projeto ATUALIZACAO_BASES (staging/intermediate da rotina) e o Calculo faz ref() deles. Esta direcao NAO e o problema - so a contra-direcao fecha o ciclo.
- `Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` → `ATUALIZACAO_BASES v09` via `TRAB.HISTORICO_202008 / TRAB.HISTORICO_202011 / TRAB.GARANTIAS / TRAB.HISTORICA` — ESTA e a aresta que cria o ciclo (B->A). Quebrar separando o estagio: os datasets de historico/garantias que A re-le devem virar uma camada COMUM (ex. modelos 'trab_historico_base' / 'trab_garantias') que NAO pertence a nenhum dos dois projetos, mas a um terceiro modulo de base compartilhada referenciado por ambos. Alternativamente, fundir os dois EGPs num unico projeto dbt 'prov_contab_trabalhista' (eles ja compartilham o mesmo lib fisico), eliminando a fronteira projeto-projeto que gera o ciclo.

**Recomendação:** 1) Reconhecer que os dois EGPs sao a MESMA rotina (libname TRAB aponta para o mesmo path '/riscosbv/MRO/Modelos/ProvContTrab/RotinaCalculo' nos dois). Recomendacao primaria: MIGRAR OS DOIS COMO UM UNICO PROJETO dbt 'prov_contab_trabalhista', onde a ordem A->B->(historicos)->A vira um DAG interno aciclico (cada dataset mensal e um modelo, ref() resolve a ordem). Isso dissolve o ciclo de cara, pois a fronteira projeto-a-projeto deixa de existir. 2) Se precisarem ficar separados: (a) externalizar LT_INDICE e M_VALOR_INDICE como source unica dbt da origem Postgres bv-production (remove 2 arestas falsas); (b) extrair os datasets de historico/garantias re-lidos por A (TRAB.HISTORICO_202008/202011, TRAB.GARANTIAS, TRAB.HISTORICA) para uma camada de base compartilhada (terceiro modulo), quebrando a aresta B->A que fecha o ciclo. 3) Confirmar com o time de Riscos as escritas de TRAB.GARANTIAS e TRAB.HISTORICA por B (marcadas 'incerto' - nao achei DATA/CREATE bare no codigo, possivel macro/%INCLUDE ou base pre-existente) antes de decidir se sao realmente produzidas no ciclo ou sao bases externas estaticas.

### Cluster #11 — 2 projetos · Riscos — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| Matriz Onboarding CIB | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 9 | 33 |
| Matriz Renovacao Continua v29 | Riscos | Onda 1 (Ciclo - quebrar manualmente) | 32 | 372 |

**O laço:** O cluster tem 2 projetos da area Riscos/PLD (Matriz Onboarding CIB e Matriz Renovacao Continua v29) ligados pela lib compartilhada PLD = /riscosbvf/pld. O grafo aponta um laco mutuo A<->B via duas tabelas: Onboarding->Renovacao por PLD.BASE_ONBOARDING_RESULTADOS, e Renovacao->Onboarding por PLD.BS_MIDIA_AML. Na pratica so existe UM sentido real: Onboarding produz PLD.BASE_ONBOARDING_RESULTADOS (DATA PLD.BASE_ONBOARDING_RESULTADOS; SET ... BASE_ONBOARDING_INI) e Renovacao a le (PROC SQL FROM). Ja PLD.BS_MIDIA_AML NAO e escrita por ninguem dentro do cluster: os dois projetos apenas fazem SET PLD.BS_MIDIA_AML (leitura) carregando para uma WORK homonima; ela e uma tabela de origem comum da lib PLD. A aresta de volta (Renovacao->Onboarding) e falsa, gerada por erro de atribuicao de writer no inventario. Sem essa aresta, o laco desaparece.

**Exemplos de ciclo:**

- Matriz Onboarding CIB → Matriz Renovacao Continua v29 → Matriz Onboarding CIB

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `PLD.BS_MIDIA_AML` | 0 | 2 | fonte compartilhada | Nenhum projeto escreve: nao ha 'DATA PLD.BS_MIDIA_AML' nem 'CREATE TABLE PLD.BS_MIDIA_AML' em nenhum dos dois (grep=0). Ambos so leem via SET: Onboarding L546 'SET PLD.BS_MIDIA_AML |
| `PLD.BASE_ONBOARDING_RESULTADOS` | 1 | 2 | handoff real | Onboarding CIB linha 1142-1143: 'DATA PLD.BASE_ONBOARDING_RESULTADOS; SET PLD.BASE_ONBOARDING_RESULTADOS BASE_ONBOARDING_INI;' (escrita persistente + self-append). Renovacao v29 a  |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Nenhuma correcao material; a analise do investigador esta correta e bem fundamentada no codigo. Confirmei por grep no co). Das 2 tabelas do laco, apenas PLD.BASE_ONBOARDING_RESULTADOS e handoff real (Onboarding->Renovacao). A aresta de retorno (Renovacao->Onboarding via PLD.BS_MIDIA_AML) e artefato: BS_MIDIA_AML nao e escrita por nenhum dos projetos (so SET/leitura), e o writer atribuido a Renovacao no inventario 06 e f

**Como quebrar:**

- `Matriz Renovacao Continua v29` → `Matriz Onboarding CIB` via `PLD.BS_MIDIA_AML` — Eliminar esta aresta: e falsa. Reclassificar PLD.BS_MIDIA_AML como source externa unica (lib PLD = /riscosbvf/pld), lida tanto por Onboarding quanto por Renovacao. Corrigir o inventario 06 removendo BS_MIDIA_AML dos PERMANENT OUTPUTS de Renovacao (writer fantasma por colisao com a WORK homonima criada via SET).

**Recomendação:** Quebra: nao e preciso refatorar logica nem dividir projeto. (1) Modelar PLD.BS_MIDIA_AML como source/dbt source unico (origem da lib PLD), referenciada por ambos via source(); isso ja remove a unica aresta de retorno e mata o ciclo. (2) Tambem modelar PLD.BASE_ONBOARDING_RESULTADOS como entregavel de Onboarding (um model dbt em Onboarding) que Renovacao consome via ref() cross-project -> dependencia DAG limpa Onboarding -> Renovacao. (3) Atencao na conversao: PLD.BASE_ONBOARDING_RESULTADOS faz auto-append (SET dela mesma + BASE_ONBOARDING_INI), padrao acumulativo/historico -> tratar como model incremental em Onboarding, nao como full-refresh. (4) Corrigir o extractor/inventario para nao marcar como writer da lib PLD um 'DATA <nome>' que cria WORK homonima a uma tabela PLD lida por SET (fonte da colisao de writer). Ordem de migracao: Onboarding antes de Renovacao.

### Cluster #12 — 2 projetos · Rodas, SAS_UC4 — 🟡 artefato parcial

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| campanha_ativabv | Rodas | Onda 10 (Ciclo - quebrar manualmente) | 11 | 43 |
| tbmetaproducao | SAS_UC4 | Onda 10 (Ciclo - quebrar manualmente) | 36 | 149 |

**O laço:** Ciclo de 2 projetos: SAS_UC4__tbmetaproducao (area SAS_UC4) e Rodas__campanha_ativabv (area Rodas). O grafo aponta duas arestas opostas. (1) SAS_UC4 -> Rodas via BASES.TBMETAPRODUCAOFINAL: real - SAS_UC4 produz essa tabela permanente (PERMANENT OUTPUT) e a versao BKP do Rodas a le (from bases.TBMETAPRODUCAOFINAL, linha 993). (2) Rodas -> SAS_UC4 via /projetos/MISV/data/bases/tmp/tbpotencialrodas.sas7bdat (TMP.TBPOTENCIALRODAS): NAO e handoff - os DOIS projetos LEEM esse arquivo .sas7bdat como insumo externo (SAS_UC4 via %VerificaAtualizacao + FROM TMP.TBPOTENCIALRODAS; Rodas via set tmp.TbPotencialRodas), e NENHUM dos dois o grava como saida permanente. E uma fonte TMP comum pre-existente. O 'dado que volta pra tras' (TBPOTENCIALRODAS) na verdade nao volta: e uma origem compartilhada. So a aresta TBMETAPRODUCAOFINAL e uma dependencia verdadeira.

**Exemplos de ciclo:**

- campanha_ativabv → tbmetaproducao → campanha_ativabv

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `/PROJETOS/MISV/DATA/BASES/TMP/TBPOTENCIALRODAS.SAS7BDAT` | 0 | 0 | fonte compartilhada | table_flow: 0 writers / 0 readers no cluster (aresta so existe pelo path normalizado). Ambos os projetos LEEM TMP.TBPOTENCIALRODAS como EXTERNAL INPUT: SAS_UC4 tbmetaproducao.txt L |
| `BASES.TBMETAPRODUCAOFINAL` | 1 | 1 | handoff real | tbmetaproducao.txt L39 PERMANENT OUTPUTS lista BASES.TBMETAPRODUCAOFINAL (criada via CREATE TABLE TbMetaProducaoFinal + serie de UPDATEs, L3203+). Rodas BKP L993 'from bases.TBMETA |

**Veredito:** investigador `artefato_parcial` → verificação **`artefato_parcial`** (concorda: True; Substancialmente nenhuma; a analise se sustenta sob escrutinio adversarial. Edge SAS_UC4 -> Rodas (BASES.TBMETAPRODUCAOF). Uma das duas arestas e real (SAS_UC4 -> Rodas via BASES.TBMETAPRODUCAOFINAL: 1 writer + 1 reader confirmados em codigo) e a outra e artefato (Rodas -> SAS_UC4 via TMP.TBPOTENCIALRODAS: 0/0 no table_flow, fonte .sas7bdat lida pelos dois e gravada por nenhum). Removendo a aresta falsa, o cluster vira 

**Como quebrar:**

- `campanha_ativabv` → `tbmetaproducao` via `/projetos/MISV/data/bases/tmp/tbpotencialrodas.sas7bdat (TMP.TBPOTENCIALRODAS)` — Quebrar: externalizar TMP.TBPOTENCIALRODAS como source/seed unica (origem .sas7bdat pre-existente). Ambos projetos a consomem como leitura; Rodas nao a produz de forma permanente. Reapontar as duas leituras (SAS_UC4 e Rodas) para a mesma source externa em vez de tratar Rodas como produtor.

**Recomendação:** Quebrar a aresta Rodas -> SAS_UC4 modelando /projetos/MISV/data/bases/tmp/tbpotencialrodas.sas7bdat (TMP.TBPOTENCIALRODAS) como UMA source/ingestion externa unica, consumida por ref/source pelos dois projetos - ela nao e gerada por nenhum dos dois dentro do cluster (0 writers no table_flow; em Rodas so existe como copia WORK descartavel). Manter apenas a aresta verdadeira: SAS_UC4__tbmetaproducao produz BASES.TBMETAPRODUCAOFINAL e Rodas__campanha_ativabv (script CampanhaPDV_BKP) a le. Ordem de migracao resultante: ingerir TMP.TBPOTENCIALRODAS (+ TMP.TBPARCEIROCOMERCIAL, TMP.TBPRODUCAO, que tem o mesmo padrao) como sources; migrar SAS_UC4__tbmetaproducao antes de Rodas__campanha_ativabv. Nao e necessario dividir nenhum projeto. Verificar tambem TMP.TBPARCEIROCOMERCIAL e TMP.TBPRODUCAO: aparecem como leitura nos dois e podem gerar arestas-fantasma identicas em outros clusters.

### Cluster #8 — 2 projetos · Negócios Transacionais Varejo e NaPista, Solar — 🟢 artefato total

**Membros:**

| Projeto | Área | Onda | lê | escreve |
|---|---|---|---:|---:|
| Bases Solar Allan_v40__v2 | Negócios Transacionais Varejo e NaPista | Onda 0 (Ciclo - quebrar manualmente) | 23 | 85 |
| Dados médios acompanhamento Pricing-NBK5DQM5T3 | Solar | Onda 0 (Ciclo - quebrar manualmente) | 147 | 30 |

**O laço:** Ciclo mútuo A↔B de tamanho 2 entre "Bases Solar Allan_v40" (Negócios Transacionais Varejo) e "Dados médios acompanhamento Pricing" (Solar). O grafo aponta: A escreve HOML.TBORIGINACAO e B a lê (A→B); B escreve TUYRA.SOLAR_REBATE_1024 e A a lê (B→A). Na prática NENHUM dos dois dados volta pra trás: ao ler o código, AMBAS as tabelas são apenas LIDAS pelos dois projetos (FROM/JOIN/SET), e nenhuma das duas é de fato produzida (CREATE/DATA) por nenhum dos projetos dentro do cluster. HOML.TBORIGINACAO é uma tabela-fonte corporativa (libname HOML/HOMOLOG2 = mesmo path físico /projetos/MISV/data/bases, lib de homologação/ODS) consumida pelos dois. TUYRA.SOLAR_REBATE_1024 é uma tabela de referência de rebate carregada manualmente de um Excel (solar_rebate_1024.xlsx em Downloads) e só lida pelos dois. Logo, o "laço" é um par de arestas espúrias geradas por má-atribuição de writer no inventário; não há dado realimentando para trás.

**Exemplos de ciclo:**

- Bases Solar Allan_v40__v2 → Dados médios acompanhamento Pricing-NBK5DQM5T3 → Bases Solar Allan_v40__v2

**Evidência — tabelas que fecham o ciclo** (escritores/leitores dentro do cluster):

| Tabela | Esc | Lê | Classificação | Evidência |
|---|---:|---:|---|---|
| `HOML.TBORIGINACAO` | 1 | 2 | fonte compartilhada | table_flow marca A como writer, mas no código de A todas as ~30 referencias sao FROM/JOIN (read): TABLE_READ_PROVENANCE 'HOML.TBORIGINACAO [PROC SQL - FROM; PROC SQL - JOIN]' e nen |
| `TUYRA.SOLAR_REBATE_1024` | 1 | 2 | fonte compartilhada | table_flow marca B como writer, mas em B nao existe 'data tuyra.solar_rebate_1024' nem 'create table tuyra.solar_rebate_1024' (grep vazio); provenance mostra 'TUYRA.SOLAR_REBATE_10 |

**Veredito:** investigador `artefato_total` → verificação **`artefato_total`** (concorda: True; Nenhuma correcao material; o veredito artefato_total esta correto e bem sustentado pelo codigo. Confirmei em text_egps a). Nenhuma das 2 tabelas do ciclo e handoff real. Verificacao no codigo: (1) HOML.TBORIGINACAO so e LIDA por A e por B (FROM/JOIN); A nunca a cria — sua unica saida permanente real e ALE.ENCART_SOLAR_PDV. (2) TUYRA.SOLAR_REBATE_1024 so e LIDA por A e por B; B nunca executa 'data/create table tuyra.sola

**Como quebrar:**

- `Bases Solar Allan_v40__v2` → `Dados médios acompanhamento Pricing-NBK5DQM5T3` via `HOML.TBORIGINACAO` — Eliminar a aresta: A nao escreve HOML.TBORIGINACAO (so FROM/JOIN). Modelar HOML.TBORIGINACAO (=HOMOLOG2.TBORIGINACAO, path /projetos/MISV/data/bases) como source externa unica de homologacao/ODS, referenciada via source() pelos dois projetos. Corrigir o inventario 06 removendo HOML.TBORIGINACAO dos PERMANENT OUTPUTS de A (falso positivo do EXPORTED_LIBNAMES).
- `Dados médios acompanhamento Pricing-NBK5DQM5T3` → `Bases Solar Allan_v40__v2` via `TUYRA.SOLAR_REBATE_1024` — Eliminar a aresta: B nao escreve TUYRA.SOLAR_REBATE_1024 (apenas 'set' = leitura; WORK.solar_rebate_1024 e import de planilha). Modelar TUYRA.SOLAR_REBATE_1024 como source de referencia de rebate (seed/source alimentada pelo upload manual solar_rebate_1024.xlsx) consumida por ambos. Remover TUYRA.SOLAR_REBATE_1024 dos PERMANENT OUTPUTS de B no inventario.

**Recomendação:** Tratar como ARTEFATO TOTAL — nao ha dependencia ciclica real, logo nao precisa de quebra manual de fluxo nem reordenacao de ondas. Acoes: (1) Externalizar as duas tabelas como sources unicas no dbt/Databricks: HOML.TBORIGINACAO (=HOMOLOG2.TBORIGINACAO) como source de homologacao/ODS corporativo (path /projetos/MISV/data/bases), e TUYRA.SOLAR_REBATE_1024 como source/seed de referencia de rebate (origem: planilha solar_rebate_1024.xlsx). Ambos os projetos devem referencia-las via source(), nao via dependencia projeto->projeto. (2) Corrigir a causa-raiz no extractor/inventario 06: PERMANENT OUTPUTS nao deve ser derivado de EXPORTED_LIBNAMES nem da colisao com tabelas WORK de mesmo nome — exigir um statement de escrita real (create table LIB.TAB / data LIB.TAB / proc append base=LIB.TAB) e tratar 'DATA Step - SET' como leitura. Isso provavelmente dissolve outros ciclos parecidos no grafo. (3) Apos a correcao, A e B podem migrar em paralelo na mesma onda, sem ordem imposta. Validar HOML.TBORIGINACAO e TUYRA.SOLAR_REBATE_1024 no RepMap/Chameleon para confirmar que ja sao ingestoes/fontes existentes."

## 4. Apêndice A — todas as arestas internas dos ciclos (127)

Lista exaustiva de cada dependência cíclica (produtor → consumidor : tabela(s)).

**Cluster #1** (16 proj · Atacado, Crédito, Riscos) — 64 arestas:

- `Base_Bruta` → `Esteira 2` : INSIGHT.TBVNP | PLCA.TBSISTEMAPLCA
- `Base_Bruta` → `Painel Sales Finance` : PLCA.TBSISTEMAPLCA | SHAREATA.TBRATING_V2
- `Base_Bruta` → `Project_semiUpper` : INSIGHT.TBVNP
- `Base_Bruta` → `[Gestão_de_Carteira] Motores` : PLCA.TBSISTEMAPLCA
- `Base_Bruta` → `CIB` : INSIGHT.TBVNP | PLCA.TBSISTEMAPLCA
- `Base_Bruta` → `Esteira - OMIE Sacados_v2` : PLCA.TBSISTEMAPLCA
- `Base_Bruta` → `Esteira - Sales Finance PJ` : PLCA.TBSISTEMAPLCA | SHAREATA.TBRATING_V2
- `Base_Bruta` → `[Gestão_de_Carteira] Motores` : PLCA.TBSISTEMAPLCA
- `Base_Bruta` → `Base_Unica_202509` : PLCA.TBSISTEMAPLCA | SIC.DMRELATIOLIMITESHIST
- `Base_Bruta` → `Controle_PMES_v19__v2` : PLCA.TBSISTEMAPLCA
- `Base_Bruta` → `VNP - Diario Middle e Corporate_2025_WINSCP` : PLCA.TBSISTEMAPLCA
- `Base_Carteira_Consolidada` → `Painel Sales Finance` : ATUAL.CLIENTES_ATUAL_2026
- `Base_Carteira_Consolidada` → `CIB` : ATUAL.CLIENTES_ATUAL_2025
- `Base_Carteira_Consolidada` → `Controle_PMES_v19__v2` : INSIGHT.TBBRUTA_20250731
- `Base_Sinais_v5` → `Esteira 2` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Painel Sales Finance` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Project_semiUpper` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `[Gestão_de_Carteira] Motores` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Esteira - OMIE Sacados_v2` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Esteira - Sales Finance PJ` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `[Gestão_de_Carteira] Motores` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Base_Unica_202509` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Controle_PMES_v19__v2` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `Indicadores_PMEs_PPT_V3` : INSIGHT.TBBRUTA
- `Base_Sinais_v5` → `VNP - Diario Middle e Corporate_2025_WINSCP` : INSIGHT.TBBRUTA
- `Esteira 2` → `Base_Sinais_v5` : INSIGHT.BASE_BACEN_FINAL
- `Esteira 2` → `Painel Sales Finance` : INSIGHT.TBPMEANALITICA | PME.BASE_FATURAMENTO_SERASA_PJ
- `Esteira 2` → `Project_semiUpper` : PME.BASE_FATURAMENTO_SERASA_PJ
- `Esteira 2` → `[Gestão_de_Carteira] Motores` : PME.BASE_FATURAMENTO_SERASA_PJ
- `Painel Sales Finance` → `Base_Bruta` : PME.BASE_CADASTRAL_SERASA_PJ
- `Painel Sales Finance` → `[Gestão_de_Carteira] Motores` : PME.BASE_CADASTRAL_SERASA_PJ
- `Project_semiUpper` → `Esteira 2` : INSIGHT.BASE_DIREITOS_CREDITORIOS
- `[Gestão_de_Carteira] Motores` → `Base_Sinais_v5` : GCSERASA.TBGCDADOSCADASTRAIS
- `[Gestão_de_Carteira] Motores` → `Esteira 2` : PME.BASE_HISTORICA_PMUM_SF | PME.BASE_SUSPENSAO_GL
- `[Gestão_de_Carteira] Motores` → `Painel Sales Finance` : PME.BASE_HISTORICA_PMUM_SF | PME.TBMGCANALITICA
- `[Gestão_de_Carteira] Motores` → `Controle_PMES_v19__v2` : GCSERASA.TBGCDADOSCADASTRAIS | PME.BASE_HISTORICA_PMUM_SF
- `Base_Bruta` → `Base_Sinais_v5` : INSIGHT.TB_GARANTIAS_ANALITICO
- `Base_Bruta` → `Esteira 2` : INSIGHT.TB_GARANTIAS_ANALITICO
- `Base_Bruta` → `Project_semiUpper` : INSIGHT.TB_GARANTIAS_ANALITICO
- `CIB` → `Base_Bruta` : INSIGHT.TBPESSOA | SHAREATA.TBCARTEIRACLIENTE | SHAREATA.TBCARTEIRAGRUPO
- `CIB` → `Base_Carteira_Consolidada` : INSIGHT.TBPESSOA
- `CIB` → `Base_Sinais_v5` : SHAREATA.TBCARTEIRAGRUPO
- `CIB` → `Project_semiUpper` : SHAREATA.TBCARTEIRAGRUPO
- `CIB` → `Base_Bruta` : INSIGHT.TBPESSOA | SHAREATA.TBCARTEIRACLIENTE
- `CIB` → `Controle_PMES_v19__v2` : SHAREATA.TBCARTEIRAGRUPO
- `Esteira - OMIE Sacados_v2` → `Painel Sales Finance` : PME.BASE_SCORE_SERASA_PJ
- `Esteira - OMIE Sacados_v2` → `Project_semiUpper` : PME.BASE_SCORE_SERASA_PJ
- `Esteira - OMIE Sacados_v2` → `[Gestão_de_Carteira] Motores` : PME.BASE_RESTR_SERASA_PJ | PME.BASE_SCORE_SERASA_PJ | PME.BASE_SOCIOS_SERASA_PJ
- `Esteira - OMIE Sacados_v2` → `[Gestão_de_Carteira] Motores` : PME.BASE_HISTORICA_OMIE_CEDENTES | PME.BASE_RESTR_SERASA_PJ | PME.BASE_SCORE_SERASA_PJ | PME.BASE_SOCIOS_SERASA_PJ
- `Esteira - Sales Finance PJ` → `Painel Sales Finance` : PME.BASE_HBV8_SERASA_PJ
- `Esteira - Sales Finance PJ` → `[Gestão_de_Carteira] Motores` : PME.BASE_HBV8_SERASA_PJ
- `Esteira - Sales Finance PJ` → `[Gestão_de_Carteira] Motores` : PME.BASE_HBV8_SERASA_PJ
- `[Gestão_de_Carteira] Motores` → `[Gestão_de_Carteira] Motores` : _INSIGHT.TBMGCANALITICA
- `Base_Unica_202509` → `Base_Carteira_Consolidada` : MISCRED.BASE_UNICA_ATACADO_202408
- `Base_Unica_202509` → `[Gestão_de_Carteira] Motores` : MISCRED.MATRIZ_SETORES
- `Base_Unica_202509` → `CIB` : MISCRED.MATRIZ_SETORES
- `Base_Unica_202509` → `Esteira - Sales Finance PJ` : MISCRED.MATRIZ_SETORES
- `Base_Unica_202509` → `[Gestão_de_Carteira] Motores` : MISCRED.MATRIZ_SETORES
- `Base_Unica_202509` → `VNP - Diario Middle e Corporate_2025_WINSCP` : MISCRED.BASE_CLIENTES | MISCRED.TBCRED_BASE_GLOBAL_202510
- `Controle_PMES_v19__v2` → `Base_Unica_202509` : PDD.INFOS_PME | SME.BASE_HISTORICA_SME_PJ
- `Controle_PMES_v19__v2` → `Indicadores_PMEs_PPT_V3` : PDD.INFOS_PME
- `Indicadores_PMEs_PPT_V3` → `Controle_PMES_v19__v2` : MONITRCA.NE_DESEMBOLSOS
- `VNP - Diario Middle e Corporate_2025_WINSCP` → `Base_Bruta` : MISCRED.VNP_CONSOLIDADO
- `VNP - Diario Middle e Corporate_2025_WINSCP` → `Base_Bruta` : MISCRED.VNP_CONSOLIDADO

**Cluster #2** (9 proj · Cobranças) — 19 arestas:

- `20250918_darkpost_v15` → `ALIMENTAR DASH - NPSv10 - copia` : CONTATOS.COB_MDM_TELEFONE
- `20250918_darkpost_v15` → `Project_Atualiza_Base_D0` : CONTATOS.COB_MDM_EMAIL | CONTATOS.COB_MDM_TELEFONE
- `ALIMENTAR DASH - NPSv10 - copia` → `20250918_darkpost_v15` : TCONFIG.CONFIG_TPENTRADA
- `ALIMENTAR DASH - NPSv10 - copia` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` : TCONFIG.CONFIG_TPENTRADA
- `Processo_NPS_UNICO_SEG_DIG` → `ALIMENTAR DASH - NPSv10 - copia` : NPS.BA_ESTOQUE_NPSENVIO
- `Project_Atualiza_Base_Acesso_Site_App_GCP` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` : CONTATOS.AUX_HIST_ACESSO_APP | CONTATOS.AUX_HIST_ACESSO_SITE
- `Project_Atualiza_Base_D0` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` : CONTATOS.AUX_BASE_CYBER_D0
- `Project_Atualiza_Base_Eventos_Whats` → `20250918_darkpost_v15` : CONTATOS.AUX_BASE_CYBER
- `Project_Atualiza_Base_Eventos_Whats` → `Project_Atualiza_Base_Hash_BV` : CONTATOS.AUX_BASE_CYBER
- `Project_Atualiza_Base_Eventos_Whats` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` : CONTATOS.AUX_QUARENTENA_TEL
- `Project_Atualiza_Base_Eventos_Whats` → `Project_Controle_Envios_HSM` : CONTATOS.AUX_BASE_CYBER
- `Project_Atualiza_Base_Hash_BV` → `Project_Atualiza_Base_Acesso_Site_App_GCP` : CONTATOS.AUX_BASE_HASH
- `Project_Atualiza_Base_Hash_BV` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` : CONTATOS.AUX_BASE_HASH
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `20250918_darkpost_v15` : CONTATOS.AUX_CYBER_ALCADAS | CONTATOS.AUX_IQ_ACAO_CONTRA | CONTATOS.AUX_SYNAPSE_MDM_EMAIL | CONTATOS.AUX_SYNAPSE_MDM_TEL
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `Processo_NPS_UNICO_SEG_DIG` : CONTATOS.COB_MDM_TELEFONE_BKPD3
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `Project_Atualiza_Base_D0` : CONTATOS.AUX_SYNAPSE_MDM_TEL
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `Project_Atualiza_Base_Eventos_Whats` : CONTATOS.AUX_SYNAPSE_MDM_TEL
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` → `Project_Controle_Envios_HSM` : RATINHO.RATINHO_UNIFICADO
- `Project_Controle_Envios_HSM` → `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` : CONTATOS.AUX_HIST_INTERACAO_WHATS

**Cluster #3** (8 proj · SAS_UC4) — 16 arestas:

- `ext_originacao` → `ext_taxamercado` : TBDATACORTE
- `ext_originacao` → `tbpotencialrodas` : TMP.TBEXTPROPOSTA | TMP.TBORIGINACAO
- `ext_parceirocomercial` → `ext_originacao` : BASES.BASE_DSLOGIN_ORIGINADOR | TMP.TBPARCEIROCOMERCIAL
- `ext_parceirocomercial` → `ext_producao` : BASES.BASE_DSLOGIN_ORIGINADOR | TMP.TBPARCEIROCOMERCIAL
- `ext_parceirocomercial` → `tbpotencialpdvs` : TMP.TBPARCEIROCOMERCIAL
- `ext_parceirocomercial` → `tbprospeccaoprivado` : TMP.TBPARCEIROCOMERCIAL
- `ext_producao` → `ext_originacao` : BASEGRC.TBPROPOSTAMULTIBANCO | BASEGRC.TBRASTREADOR
- `ext_producao` → `ext_resultadogerencial` : TMP.TBPRODUCAO
- `ext_producao` → `tbpotencialrodas` : TMP.TBPRODUCAO
- `ext_producao` → `tbprospeccaoprivado` : TMP.TBPRODUCAO
- `ext_resultadogerencial` → `ext_producao` : BASES.TBRESULTADOGERENCIAL
- `ext_taxamercado` → `ext_originacao` : BASES.TBDIMTAXAMERCADO
- `ext_taxamercado` → `ext_producao` : BASES.TBDIMTAXAMERCADO
- `tbpotencialpdvs` → `tbpotencialrodas` : TMP.TBPOTENCIALPDVS
- `tbpotencialrodas` → `ext_parceirocomercial` : TMP.TBPOTENCIALRODAS
- `tbprospeccaoprivado` → `ext_parceirocomercial` : BASEGRC.TBPRIVADOCONVENIOFUNCIONARIOS

**Cluster #4** (4 proj · Crédito) — 6 arestas:

- `20250924 - BASE_CONTROLE_TOTAL_VF` → `20251114 - BASE MANUTENCAO TOTAL` : MANUTLIM.CONTROLE_MANUTENCAO_TOTAL
- `20251114 - BASE MANUTENCAO TOTAL` → `Reducao_Em_Dia_20251124` : MANUTLIM.MANUTENCAO_TOTAL
- `RED_LIMITE_PUBLICO_EM_ATRASO_20251124` → `20250924 - BASE_CONTROLE_TOTAL_VF` : MANUTLIM._BASE_LOG_RED_ATRASO_20251124
- `RED_LIMITE_PUBLICO_EM_ATRASO_20251124` → `Reducao_Em_Dia_20251124` : MANUTLIM._BASE_LOG_RED_ATRASO_20251124
- `Reducao_Em_Dia_20251124` → `20250924 - BASE_CONTROLE_TOTAL_VF` : MANUTLIM._BASE_LOG_RED_EMDIA_20251124
- `Reducao_Em_Dia_20251124` → `RED_LIMITE_PUBLICO_EM_ATRASO_20251124` : GALDINO.BASE_PARTIDA_REDUCAOCARGA_202511

**Cluster #5** (3 proj · Atacado) — 4 arestas:

- `Compilados_v27` → `Consolidado_V68` : EXTRATO.CLIENTES_ATIVOS | PASSIVOS.BOOK_PASSIVO_ANTERIOR | PASSIVOS.BOOK_PASSIVO_ATUAL
- `Consolidado_V68` → `Compilados_v27` : EXTRATO.EXTRATO_202404
- `Consolidado_V68` → `consultas_v8` : EXTRATO.EXTRATO_2019_ENCARTEIRAMENTO23 | EXTRATO.EXTRATO_2021_ENCARTEIRAMENTO23 | EXTRATO.EXTRATO_202308 | EXTRATO.EXTRATO_202402 | EXTRATO.EXTRATO_202404
- `consultas_v8` → `Consolidado_V68` : EXTRATO.EXTRATO_ENCART24_2023

**Cluster #6** (3 proj · Rodas) — 4 arestas:

- `IGE_NEW_EGV_Parceiros_digitais` → `IGE_NEW_Funil_EGV` : AUXL.EGV_DEPARABALCAODIGITAL | AUXL.EGV_DEPARAPARCEIROSDIGITAIS
- `IGE_NEW_EGV_Parceiros_digitais` → `filtrocvg` : AUXL.EGV_DEPARABALCAODIGITAL | AUXL.EGV_DEPARAPARCEIROSDIGITAIS
- `IGE_NEW_Funil_EGV` → `IGE_NEW_EGV_Parceiros_digitais` : TRIBO.EGV_PAP
- `filtrocvg` → `IGE_NEW_Funil_EGV` : BASEGRC.TBFILTROCVG

**Cluster #7** (2 proj · Finanças) — 2 arestas:

- `Book_Diario_Acumulado` → `Tesouraria_sem_porta` : SAIDASIC.REGRAS_SEGMENTAR_TEMP_NOV25D_D3
- `Tesouraria_sem_porta` → `Book_Diario_Acumulado` : PLANCTRL.BASE_TESOURARIA

**Cluster #8** (2 proj · Negócios Transacionais Varejo e NaPista, Solar) — 2 arestas:

- `Bases Solar Allan_v40__v2` → `Dados médios acompanhamento Pricing-NBK5DQM5T3` : HOML.TBORIGINACAO
- `Dados médios acompanhamento Pricing-NBK5DQM5T3` → `Bases Solar Allan_v40__v2` : TUYRA.SOLAR_REBATE_1024

**Cluster #9** (2 proj · Riscos) — 2 arestas:

- `ATUALIZACAO_BASES v09` → `Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` : LT_INDICE | M_VALOR_INDICE | TRAB.BVT_POR_CPF | TRAB.HISTORICO_201812 | TRAB.PARTEPRO_EXCLUSIVO | TRAB.PJ_GARANTIAS_PERDAS | TRAB.TR_HIST_INDICE
- `Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` → `ATUALIZACAO_BASES v09` : TRAB.GARANTIAS | TRAB.HISTORICA | TRAB.HISTORICO_202008 | TRAB.HISTORICO_202011

**Cluster #10** (2 proj · Riscos) — 2 arestas:

- `Base_Origem_FPR_85_202509_Res_229_V2_SRP` → `RWAcpad_202509_vIFRS9_V22_batimento4060_SRP` : _PEPR_RA.BASECUBO202509._4040_VCARIMBOS
- `RWAcpad_202509_vIFRS9_V22_batimento4060_SRP` → `Base_Origem_FPR_85_202509_Res_229_V2_SRP` : _PEPR_RA.BASECUBO202509._4040_V229

**Cluster #11** (2 proj · Riscos) — 2 arestas:

- `Matriz Onboarding CIB` → `Matriz Renovacao Continua v29` : PLD.BASE_ONBOARDING_RESULTADOS
- `Matriz Renovacao Continua v29` → `Matriz Onboarding CIB` : PLD.BS_MIDIA_AML

**Cluster #12** (2 proj · Rodas, SAS_UC4) — 2 arestas:

- `campanha_ativabv` → `tbmetaproducao` : /projetos/MISV/data/bases/tmp/tbpotencialrodas.sas7bdat
- `tbmetaproducao` → `campanha_ativabv` : BASES.TBMETAPRODUCAOFINAL

**Cluster #13** (2 proj · Rodas) — 2 arestas:

- `inad` → `qualidadedevendas_cubo_estudo` : INAD.INADHISTORICA
- `qualidadedevendas_cubo_estudo` → `inad` : AUXL.PROPOSTAS_ESG

## 5. Metodologia

- **Grafo:** `03_matriz_dependencias.csv` (colunas Projeto_Alvo, Depende_Do_Projeto, Via_Tabela). Aresta dirigida `Depende_Do → Projeto_Alvo`.
- **Ciclos:** componentes fortemente conexos (Tarjan) de tamanho ≥ 2. Todo nó num SCC participa de ao menos um ciclo.
- **table_flow:** para cada tabela do ciclo, quem a escreve (`table_out`) e quem a lê (`table_in`) *dentro* do cluster, a partir do inventário `06` (ruído `WORK./macro/.sas7bdat` excluído).
- **Classificação por tabela:** `handoff real` (1 escritor → leitores = entrega genuína) · `fonte compartilhada` (vários escritores e/ou schema de banco corporativo lido por muitos = fonte, não handoff) · `colisão de nome` (mesmo nome de tabela temporária/alias usado por projetos distintos).
- **Veredito:** `ciclo real` (há handoffs mútuos genuínos) · `artefato parcial` (parte real, parte fonte/colisão) · `artefato total` (nenhum handoff real — o ciclo some ao externalizar as fontes).
- Cada cluster foi investigado por 1 agente (com leitura do código em `text_egps/`) e o veredito **verificado adversarialmente** por um 2º agente (priorizando refutar alegações de “artefato”).

**Fontes:** `_manifests/ciclos_clusters.json` (evidência determinística) · `_manifests/ciclos_workflow_result.json` (investigação+verificação).