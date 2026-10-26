# Por que o escopo mudou: antes e depois do estudo dos outputs

**Data:** 2026-08-17
**Base:** painel de monitoramento SAS, produção (`bv_dev_db.monitoramento_sas`), leitura de 2026-08-17
**Assunto:** motivo da alteração dos números do escopo, impacto nas métricas do projeto, o que saiu, o que entrou e o ganho do estudo

---

## 1. Resumo executivo

O plano de migração passou de **189 para 193 EGPs**. O número subiu 4, mas **15 EGPs trocaram de lugar**: 7 saíram e 8 entraram. A mudança não é uma revisão de ambição — é a **correção de quem produz cada tabela**.

Uma dependência entre dois EGPs só existe se um deles **cria** a tabela que o outro lê. O inventário errava esse ponto de duas formas:

1. **Produtor fantasma.** O idioma SAS `DATA X; SET LIB.X;` copia uma tabela permanente para a área temporária da sessão (WORK). A regra antiga, ao encontrar `LIB.X` em qualquer ponto do código, promovia a cópia `X` a `LIB.X` — registrava uma **escrita** onde havia apenas uma **leitura**. EGPs que só leem uma tabela apareciam como produtores dela.
2. **Contribuinte tratado como produtor.** Quem faz `INSERT INTO`, `PROC APPEND`, `UPDATE` ou `DELETE` **acrescenta linhas ou altera registros** de uma tabela que já existe. Não é a origem do dado, e portanto não deve ser puxado para o plano como fonte.

Corrigidos os dois pontos, dependências falsas caíram e dependências reais que estavam encobertas apareceram. O ganho não está no número de EGPs, e sim em três lugares:

| Ganho | Medida |
|---|---|
| Ligações de dependência falsas eliminadas | **459 ligações**, em 84 tabelas que deixaram de gerar dependência |
| Fila de ingestão que pode ser dispensada | **318 tabelas** (18,7% das 1.699 pendentes) |
| Tabelas que **exigem carga inicial** e antes seriam descartadas por engano | **380 tabelas** |

---

## 2. O defeito corrigido, com evidência

### 2.1 Produtor fantasma: 84 tabelas que nunca foram produzidas por ninguém

O caso mais claro: **`BASES.TBPRODUCAO` puxava 55 EGPs consumidores** para dentro do plano, tendo como suposto produtor o EGP `Negócios e Produtos Relacional e Seguros__BaseUnica`. Hoje essa tabela **não aparece no inventário de outputs**: nenhum EGP do corpus a escreve. É tabela de origem, lida por todos e produzida por ninguém. Os 55 vínculos eram artefato da cópia para WORK.

| Tabela | "Produtor" no retrato antigo | Consumidores puxados | Situação hoje |
|---|---|---:|---|
| `BASES.TBPRODUCAO` | `Negócios e Produtos Relacional e Seguros__BaseUnica` | 55 | nenhum EGP a escreve |
| `PROJETOS.TBPARCEIROCOMERCIAL` | `Riscos__Base 360 v4` | 40 | nenhum EGP a escreve |
| `PROJETOS.TBPRODUCAO` | `Negócios e Produtos Relacional e Seguros__BaseUnica` | 39 | nenhum EGP a escreve |
| `INSIGHT.TBBRUTA` | `Atacado__Base_Sinais_v5` | 28 | nenhum EGP a escreve |
| `HOMOLOG2.TBPARCEIROCOMERCIAL` | `Riscos__Base 360 v4` | 18 | nenhum EGP a escreve |
| `TCONFIG.CONFIG_TPENTRADA` | `Cobranças__ALIMENTAR DASH - NPSv10 - copia` | 15 | nenhum EGP a escreve |
| `SHAREATA.TBCARTEIRAGRUPO` | `Crédito__CIB` | 12 | nenhum EGP a escreve |
| `KAUE.BASE_CYBER` | `Cobranças__Painel_Desconto_Perf_Solar` | 7 | nenhum EGP a escreve |
| ...outras 76 tabelas | — | 245 | — |
| **Total** | | **459** | |

Note que o problema **não era só de Cobrança**: Negócios e Produtos, Riscos, Atacado e Crédito aparecem entre os maiores casos.

Além dessas 84, outras **118 tabelas tiveram o conjunto de produtores alterado** — em 24 delas o produtor foi **inteiramente reapontado** para o criador real. Exemplo: `CONTATOS.COB_MDM_TELEFONE` e `CONTATOS.COB_MDM_EMAIL` constavam como produzidas por `Cobranças__20250918_darkpost_v15`, que só as lê; o criador real é `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH`.

Medido na **mesma reextração do corpus** (1.736 EGPs), para isolar o efeito da regra: a heurística antiga produzia **4.975 vias de dependência**; a regra corrigida produz **2.639**. Foram removidos **321 outputs falsos** do inventário.

### 2.2 Criador vs. contribuinte: o caso `ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`

`ZBLOQ.BLOQUEIO_REGUAS_INTERSEC` é um registro compartilhado de bloqueios: **dez EGPs fazem `INSERT INTO` e um faz `DELETE` de limpeza — nenhum a cria**. Verificamos por identidade física (caminho + membro) que não existe criador sob outro apelido de libname nem em outro diretório. `RATINHO.RATINHO_UNIFICADO` é o mesmo padrão: **1 escritor, 0 criadores, 10 consumidores**.

Com a regra antiga, cada inseridor virava "produtor" e era puxado para o plano por quem lia a tabela. Dois EGPs de Trilha entraram no plano exclusivamente por essa via — `Cobranças__Project_Trilha_Calamidade_MG` e `Cobranças__Project_Trilha_Preventivo_Solar_Alt_msg_lembrete` —, cada um aparecendo como fonte para 4 consumidores, sempre pela mesma tabela e por nada mais.

A tabela em si não desaparece do trabalho: passa a ser **infraestrutura compartilhada da onda** (uma tabela de append alimentada por vários jobs), com carga inicial do histórico — não um repasse entre EGPs.

Retrato atual do inventário de outputs em produção:

| Métrica | Valor |
|---|---:|
| Tabelas de output distintas | 4.273 |
| Pares (EGP × tabela) com escrita permanente | 5.257 |
| Desses, escritas que **criam** a tabela | 5.188 |
| Tabelas com **mais de um escritor** | 695 |
| Tabelas com **mais de um criador** | 687 |
| Tabelas **sem nenhum criador** (só apensam/atualizam) | **34** |

A distinção agora está visível na aba **Outputs** do painel: a coluna Produtores mostra o número de **criadores** como valor principal e os escritores como anotação, e o rádio de produtor canônico só é oferecido a quem cria.

### 2.3 Versões concorrentes: escolha do produtor canônico

Várias tabelas do plano têm mais de uma versão do mesmo processo como criadora (cópias `__v2`/`__v3`, cópias de teste, o mesmo projeto salvo em duas áreas). Com o inventário corrigido, ficou possível decidir **qual versão migra**: definiu-se o produtor canônico com base na evidência das extrações (recência do código, versão vigente, presença no escopo), e as versões concorrentes deixaram de ser puxadas como dependência.

---

## 3. Antes e depois nas métricas

Para que a comparação seja limpa, os dois retratos do grafo de dependências foram medidos contra o **mesmo estado vivo de produção** — mesmo escopo direto, mesmos status humanos, mesmas escolhas de produtor canônico. Só a fonte das arestas muda.

| Métrica | Antes | Depois | Δ |
|---|---:|---:|---:|
| **Grafo de dependências** | | | |
| Pares EGP→EGP | 1.733 | 1.830 | +97 |
| Vias (tabela × par) | 2.160 | 2.328 | +168 |
| Tabelas que geram dependência | 600 | 543 | −57 |
| Tabelas que **deixaram** de gerar dependência | — | — | **84** (459 ligações) |
| Tabelas que **passaram** a gerar dependência | — | — | 27 (46 ligações) |
| Tabelas com conjunto de produtores alterado | — | — | 118 (24 reapontadas por inteiro) |
| **Plano de EGPs** | | | |
| Escopo direto (lista Indicium) | 168 | 168 | 0 |
| Dependências transitivas | 16 | 17 | +1 |
| Ex-dependências contabilizadas | 6 | 8 | +2 |
| **Total do plano** | **190** | **193** | **+3** |
| Dependências que trocaram | — | — | **7 saíram / 8 entraram** |
| **Fila de inputs (escopo + dependências)** | | | |
| Inputs no universo dos cards | 2.577 | 2.592 | +15 |
| Fila "A receber" | 1.655 | 1.674 | +19 |
| Inputs que mudaram de situação | — | — | 28 saíram / 43 entraram |

> **Sobre o "190" vs. o "189" comunicado antes.** A tabela mede o grafo antigo contra o estado de hoje, para atribuir a mudança ao inventário e não a decisões tomadas em paralelo. O painel exibia 189 na época; a diferença de 1 vem dessas decisões de gestão, não do estudo. Os totais absolutos da fila também oscilam alguns pontos entre leituras, porque analistas marcam inputs como Sanitizado continuamente — os **deltas** são o que interessa.

Leitura da tabela: o total do plano quase não se move, mas o grafo por baixo dele foi **refeito, não ajustado**. Dos 2.160 vínculos antigos, 662 deixaram de existir e 830 novos apareceram; 84 tabelas pararam de gerar dependência e 118 trocaram de produtor. É por isso que 15 dos 193 EGPs mudaram de lugar.

---

## 4. O que saiu e o que entrou

**9 dependências permaneceram, 7 saíram e 8 entraram.**

### Saíram (7)

| EGP | Motivo | Vias que sustentavam a dependência |
|---|---|---|
| `Cobranças__20250918_darkpost_v15` | produtor fantasma (cópia para WORK) | `CONTATOS.COB_MDM_EMAIL`, `COB_MDM_TELEFONE` — 17 consumidores |
| `Cobranças__Painel_Desconto_Perf_Solar` | produtor fantasma | `KAUE.BASE_CYBER` — 7 consumidores |
| `Cobranças__Entrada_em_Cob_Geral_REAPONTADO_V2` | produtor fantasma | `LDUARTE.BAD_BANK`, `BU_CP.BU_CP` e variantes — 6 consumidores |
| `Cobranças__CartoesAmigaveis_PilotoAcordos_20260515` | produtor fantasma; o criador real é `Cobranças__CPF_Contrato` | `CARNEIRO.INFO_CONTA` — 3 consumidores |
| `Cobranças__COLCHAO_ACORDO_CL__v2` | versão antiga; o produtor canônico é `COLCHAO_ACORDO_CL` | `PERF_CL.COLCHAO_CONSOLIDADO` |
| `Cobranças__Project_Rolagem v8` | versão antiga; o produtor canônico é `Project_Rolagem v10`, já no escopo | — |
| `Cobranças__Envio SMS - Pagamentos - Cartão Amigável__v2` | duplicata removida; a via foi reapontada para o EGP original | `NPS_NEW.BA_ESTOQUE_NPSENVIO_CARTAO` |

Dois desses — `Painel_Desconto_Perf_Solar` e `Project_Rolagem v8` — voltaram aos totais como **ex-dependências retidas manualmente**, a pedido da BV: já foram trabalhados e o esforço não deve desaparecer do painel. É a origem do +2 na linha "ex-dependências" da tabela da seção 3.

### Entraram (8) — dependências reais que o retrato antigo não enxergava

| EGP | Consumidores no plano | Tabelas | Vias |
|---|---:|---:|---|
| `Cobranças__PERF_AMIGAVEL_gcp` | **21** | 4 | `MOVTO.PERF_AMIGAVEL`, `CARTAO.PERF_AMIGAVEL`, `CART_HST.PERF_AMIGAVEL`, `CARTAO.BASE_REGULARIZADO` |
| `Cobranças__PROJECT_ATIVA_GCP_V2` | 8 | 4 | `ATIVA.BASE_ATIVA_202510`, `ERICK.BASE_ATIVA_202510`, `ATIVA.BASE_ATIVA_GERAL`, `ATIVANEW.MIS_TABLEAU_GERAL` |
| `Cobranças__Performance Solar` | 6 | 4 | `SOLAR.BASE_SOLAR_IN`, `SOLAR.BASE_SOLAR_OUT`, `SOLAR_BI.BASE_SOLAR_OUT`, `ATIVA.BASE_EXPORT` |
| `Cobranças__Fechamento_Contabil_RPDD_3040` | 6 | 1 | `CARNEIRO.NUCONTRATO_CONTABIL` |
| `Cobranças__Elegibilidade_Gradativo_20251103_reap_v12 - Expansao_custas` | 3 | 2 | `LDUARTE.BASE_CONFERENCIA`, `LDUARTE.BASE_TESTE_GRADATIVO` |
| `Cobranças__PROJECT_MASSIFICADOS_202507 - Copia` | 3 | 3 | `MASSIF.MIS_TABLEAU_GERAL_2`, `MASSIF.MIS_TABLEAU_GERAL_AJUSTE`, `CP.MIS_TABLEAU_GERAL_2` |
| `Cobranças__Processo_NPS_UNICO_Novo_produto` | 2 | 5 | família `NPS_NEW.BA_*`, `CLEBER.TB_BOLETOCANAL` |
| `Cobranças__COLCHAO_ACORDO_CL` | 2 | 1 | `PERF_CL.COLCHAO_CONSOLIDADO` (substitui a `__v2` que saiu) |

O caso mais relevante é `PERF_AMIGAVEL_gcp`: **21 EGPs do plano** leem tabelas que só ele cria. No plano antigo esse EGP não estava listado — e a primeira execução dos 21 consumidores no destino não teria de onde ler.

---

## 5. O ganho do estudo

### 5.1 Correção de rumo: o plano antigo errava nas duas direções

O plano antigo **subestimava** o trabalho (faltava `PERF_AMIGAVEL_gcp`, que alimenta 21 EGPs, e outras 7 dependências reais) e ao mesmo tempo **carregava trabalho que não existia** (459 ligações de dependência sustentadas por produtores fantasma, mais versões duplicadas e EGPs puxados por tabelas que ninguém cria). Hoje, cada dependência listada é um EGP que **comprovadamente cria** uma tabela que o escopo consome.

### 5.2 Fila de ingestão: 318 tabelas dispensáveis

A distinção criador/contribuinte é o que torna possível responder "esta tabela precisa ser ingerida?". Do recorte do plano (2.592 inputs no universo, **1.699 pendentes** na leitura do relatório de 17/08), 824 tabelas SAS/Local foram classificadas com auditoria do código:

| Tier | Situação | Tabelas | Hoje "A receber" |
|---|---|---:|---:|
| 1 | Dispensa ingestão — ordem verificada no código | 125 | 97 |
| 1c | Calendário — conteúdo derivável | 8 | 6 |
| 1v | A verificar — leitura não localizável no código | 25 | 20 |
| 2 | Dispensa ingestão se o produtor migrar | 286 | 215 |
| 3 | **Exige carga inicial — não descartar** | 380 | 334 |

**Saem da fila com verificação: 318 tabelas (18,7% das 1.699 pendentes).**

### 5.3 Risco evitado: 380 tabelas que exigem carga inicial

Esse é o ganho menos visível e o mais caro de errar. Detectar que "o EGP escreve e lê a mesma tabela" **não** basta para descartá-la, porque a ordem importa:

```sas
DATA CONSIG.CARTEIRA_GERAL;  SET CONSIG.CARTEIRA_GERAL;  WHERE SAFRA <> &SAFRA.;  RUN;
DATA CONSIG.CARTEIRA_GERAL;  SET CONSIG.CARTEIRA_GERAL  CARTEIRA;                 RUN;
```

A tabela guarda todas as safras; cada execução remove a safra corrente e reinsere a versão nova. **Descartar essa tabela apaga o histórico** e a primeira execução no destino não tem de onde ler. A auditoria de ordem do código reclassificou **377 das 824 tabelas** como carga inicial, e a expansão de macros `%let` permitiu emitir veredito para **101 tabelas** que de outro modo ficariam sem classificação.

### 5.4 Achados operacionais de bônus

| Achado | Números | Ação |
|---|---|---|
| **Sequenciamento invertido**: consumidor migra antes do produtor | 48 tabelas (43 ainda "A receber") | adiantar o produtor, atrasar o consumidor ou manter tabela-ponte |
| **Produtor sem mês no plano** | 13 tabelas | entra no escopo ou passa a ser ingestão de verdade |
| **Calendários** (`DIAS_UTEIS`, `FERIADOS`, ...) sob vários apelidos | 8 tabelas | um único calendário no destino atende todos — maior simplificação isolada e independe de migrar EGP |
| **Tier 3 já marcado como Sanitizado** | 44 tabelas | revisar: se o processo estiver ativo, a 1ª execução no destino falha por tabela vazia |
| **Auto-produção** (o EGP recria a tabela que lê) | 243 inputs em 2 tiers (200 no tier 1, descarte direto) | marcar Sanitizado na aba Inputs |

### 5.5 Painel confiável para priorização

Com o grafo corrigido, tudo o que deriva dele passou a valer: bloqueio transitivo, prontidão por EGP, funis por área, alavancagem na priorização e a escolha de produtor canônico. O painel também ganhou a **chave física `(caminho, membro)` por via**, que resolve o caso em que produtor e consumidor referenciam a mesma tabela por apelidos de libname diferentes — 15% das vias, onde a poda por nome falhava em silêncio.

---

## 6. Pendências conhecidas

- **`PROJECT_MASSIFICADOS_202507 - Copia`** segue como dependência embora a versão operacionalizada (`_RPA`) já esteja no escopo: produtor e consumidores referenciam a tabela por apelidos de libname diferentes, e a escolha canônica não surtiu efeito. A chave física por via, agora exportada pelo inventário, é o caminho para resolver.
- **`LUCAS.PASTA1`** é tabela de rascunho pessoal que conecta os projetos de Rolagem. Candidata a descarte pela área.
- **25 tabelas no tier 1v** seguem sem veredito (em 21 o código escreve mas a leitura não foi localizada; em 4 o nome não pôde ser resolvido). Não são seguras nem inseguras — precisam de inspeção manual. 5 delas já estão marcadas como Sanitizado.

---

## 7. Dúvidas prováveis

**O escopo aumentou ou diminuiu?**
O total praticamente não mudou (189 → 193). O que mudou foi **quem** está dentro: 15 EGPs trocaram de lugar, e 459 ligações de dependência falsas saíram do grafo. Tratar isso como "o escopo cresceu 4" perde o ponto.

**Marcar uma tabela como Sanitizado é irreversível?**
Não. É um status editável na aba Inputs. Se for revertido, o input e as dependências ligadas a ele voltam imediatamente, porque o fecho de dependências é recalculado a cada leitura. Nada é cascateado nem apagado.

**A correção pode ter removido uma dependência legítima?**
A regra tem um guarda conservador: quando a escrita é feita sob **outro apelido de libname do mesmo diretório**, a linhagem **preserva** a aresta em vez de arriscar removê-la. Preferimos manter uma dependência duvidosa a perder uma real.

**Como se sabe que as 84 tabelas eram falsas, e não dependências perdidas?**
Porque hoje elas **não constam no inventário de outputs**: nenhum EGP do corpus (1.736 projetos) escreve nelas. São tabelas de origem — leitura de sistema transacional ou de base corporativa. A dependência antiga vinha da cópia para WORK, não de uma escrita.

---

## 8. Reprodutibilidade

Os dois retratos do grafo estão preservados e são consultáveis:

| Retrato | Onde está |
|---|---|
| **Antes** | `bv_dev_db.monitoramento_sas.bkp_sas_lineage_edges_20260728` (1.733 arestas) |
| **Depois** | `bv_dev_db.monitoramento_sas.sas_lineage_edges` (1.830 arestas) |

O escopo e as arestas imediatamente anteriores à regra do criador também estão preservados, para rollback: `docs/analises/backup_prod_escopo_deps_pre_regra_criador_2026-08-12.csv` (168 base + 31 dependências) e `docs/analises/backup_prod_arestas_pre_regra_criador_2026-08-12.csv`.

A medição da seção 3 substitui a fonte das arestas no backend do painel (`_frontier_egps` / `_ex_deps_contab` / `inputs`) mantendo todo o resto no estado vivo de produção, e conta os inputs pela mesma régua dos cards da aba Inputs (fora quem tem todos os vínculos quebrados e fora input de ex-dependência).

Documentos e scripts de apoio:

| Arquivo | Conteúdo |
|---|---|
| `BV_Migracao_SAS_Inputs_Sem_Ingestao_2026-08-17.md` + `.csv` | os 5 tiers da fila de ingestão, com o trecho de código de cada veredito |
| `BV_Migracao_SAS_Analise_Inputs_Autogerados_2026-08-12.md` | triagem dos 243 inputs auto-gerados |
| `revisao_autoprodutores_safra.py` | classificação por família de safra |
| `auditoria_ordem_codigo.py` | auditoria de ordem (criação antes ou depois da leitura) |
| `inputs_sem_ingestao_escopo_deps.py` | recorte do plano, cruzamento com o painel e sequenciamento por mês |
