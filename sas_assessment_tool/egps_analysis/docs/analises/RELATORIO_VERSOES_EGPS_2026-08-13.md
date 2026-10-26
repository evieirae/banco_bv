# Versões do mesmo EGP: levantamento, critérios de vigência e veredito por grupo

**Data:** 2026-08-13 · **Corpus:** 1.243 EGPs extraídos (`text_egps/`), 872 binários `.egp`
**Artefatos:** [`egps_versoes_grupos_2026-08-13.csv`](egps_versoes_grupos_2026-08-13.csv) (uma linha por EGP, com toda a evidência) · scripts [`egps_versoes_levantamento.py`](egps_versoes_levantamento.py) e [`egps_versoes_veredito.py`](egps_versoes_veredito.py) (reprodutíveis)

---

## 1. Resumo executivo

**225 EGPs (18% do corpus) participam de algum grupo de versão**, distribuídos em 118 grupos. Mas a redundância que de fato custa esforço de migração é muito menor:

| | |
|---|---|
| EGPs em grupos de versão | **225** de 1.243 |
| Grupos identificados | **118** |
| Desses, grupos com 2+ membros **dentro do plano de migração** (191 EGPs) | **6** |
| EGPs redundantes contados no plano | **6** brutos, todos em Cobranças — mas 1 é falso positivo e 2 já se resolveram por despriorização, sobrando **2 acionáveis + 1 dúvida de negócio** (§7) |
| Grupos onde o registro operacional está grudado na cópia **errada** | **14** |
| Pares byte-idênticos (mesmo sha256) | **46** — 5 na mesma área, 41 entre áreas; envolvem 80 EGPs |

Três conclusões práticas:

1. **A maior parte da duplicação é de coleta, não de autoria.** 47 binários chegaram com sufixo `__v2`/`__v3` porque o mesmo projeto foi encontrado em mais de um local durante a coleta do BV. Esses não são versões que o analista criou — são a mesma coisa capturada duas vezes. Só um de cada entrou no plano, então **não inflam o esforço**.
2. **O plano de migração está limpo, com 6 exceções.** Apenas 6 pares realmente concorrentes sobreviveram dentro dos 191 EGPs do plano — todos em Cobranças, todos do padrão "versão antiga vs. versão RPA/nova" (seção 7). São ~3 EGPs de esforço potencialmente evitável, dependendo da decisão da área.
3. **Há um problema de rastreio a corrigir:** em 14 grupos o `etapa_migracao`/`status_migracao` (e em 2 casos a escolha de produtor canônico) foi registrado na cópia **mais antiga** do projeto, não na vigente. Isso não erra contagem, mas confunde quem for abrir o EGP para converter (seção 8).

---

## 2. De onde vem a evidência

| Fonte | O que dá | Ressalva |
|---|---|---|
| `text_egps/*.txt` (1.243) | metadados, inventário de I/O e **o código SAS completo** de cada projeto | um projeto pode ter vários `.txt` (a área Rodas exporta um `.sas` por nó do fluxo) — foram **agregados por `PROJECT`**, senão 13 tasks de um projeto viram "13 versões" |
| `project.xml` dentro do ZIP `.egp` (872) | **timestamp do último save do projeto** — distribuído de 2020 a 2026 e coerente com o `max` das demais entradas do ZIP em 871/872 casos | — |
| `bv_dev_db.monitoramento_sas` (prod, leitura) | `escopo_indi`, etapa/status de migração, produtor canônico escolhido, arestas de linhagem | prod tem 1.223 nós vs. 1.243 extraídos — a publicação da regra do criador ainda não foi para prod |
| sha256 dos binários | identidade byte a byte | — |

**O `mtime` do arquivo no disco é inútil aqui**: todos marcam a data em que o tar foi extraído (2026-06-21). A recência real só sai de dentro do ZIP. Essa foi a peça que destravou o levantamento — sem ela, "qual é a mais nova" seria chute em metade dos casos.

Para similaridade de conteúdo, o código de cada projeto é reduzido a *shingles* de 5 tokens e comparado por Jaccard. Isso serve a dois propósitos: confirmar que membros de um grupo são de fato o mesmo projeto, e **separar linhagens distintas que o nome juntou** (ver `PROJECT_ROLAGEM_NEW` vs `Project_Rolagem v10`, similaridade 0,048 — nomes parecidos, projetos diferentes).

---

## 3. Como os EGPs são versionados na prática

Levantei os padrões empiricamente sobre os 1.243 nomes, em vez de assumir uma convenção. Contagens sobre nomes de projeto:

| Padrão | Ocorrências | Exemplos |
|---|---|---|
| `v` + número (`v5`, `V68`, `_v40`, `V_1_6`) | 251 | `Compilados_v27`, `Consolidado_V68`, `Indicador Partes Relacionadas_V_1_6` |
| Marcador de plataforma (`GCP`, `BQ`, `RPA`, `vAut`) | 70 | `PERF_AMIGAVEL_gcp`, `PROJECT_LINHAS_QIKVIEW_V5_RPA`, `ARQPAUTA_vAut` |
| `novo`/`NEW` | 106 | `PROJECT_ROLAGEM_NEW`, `MIS_IQ_v2_NEW` |
| Sufixo numérico solto (`_1`, ` 2`) | 49 | `Base_Bruta 2`, `Base_Bruta_GL 1`, `Esteira 2` |
| Ano solto | 42 | `base_carta_motos_2026`, `Análise Desconto Outubro 2025` |
| Data `AAAAMMDD` | 28 | `CartoesAmigaveis_PilotoAcordos_20260306` |
| Data `AAAAMM` | 28 | `Remuneracao_CL_202603`, `202404_Projeto_Dados_CTX` |
| Mês+ano em português | — | `Projeção_Rolagem_Mai26`, `CODIGO_APURACAO_AGO25`, `Projeto_Revisionais_Set25` |
| `teste`/`test` | 20 | `Apuração_Teste_Solar`, `Teste - Lançamentos Manuais - Copia` |
| `final`/`VF`/`ATUAL`/`vigente` | 13 | `SAS_IQ_SQ_Vigente`, `DB 12 FINAL_vAut`, `..._10%_ATUAL` |
| Número entre parênteses | 8 | `Processo de bonificação - taxas_v35 (2)`, `PROJECT_LINHAS_QIKVIEW_V5_RPA (1)` |
| `copia`/`cópia` | 5 | `PROJECT_MASSIFICADOS_202507 - Copia`, `Base_Reclamacoes15 - Copia` |
| `antigo`/`BKP` | 2 | `BENECIFIO-BKP` |

Dois achados que mudam a leitura:

**`__vN` (dois underscores, no fim) não é versão do analista.** Está no nome do arquivo em disco — 47 binários — e foi aplicado na **coleta**: quando o mesmo projeto foi achado em dois locais, o segundo ganhou `__v2`. Prova: `Consignado_PF_INSS v7`, `__v2` e `__v3` têm as mesmas 19.541 linhas e os mesmos 7 outputs, e `COLCHAO_ACORDO_CL` / `__v2` são **byte-idênticos** (mesmo sha256, mesmo tamanho). O critério para esses é puramente mecânico: vale o de save mais recente. (Precedente: o `Cartão Amigável __v2` foi removido do app em 10/08 exatamente por isso.)

**Cuidado — `__vN` nem sempre é o mesmo projeto.** Em 5 casos o nome coincide mas o conteúdo não: `CPF_Contrato` (1.114 linhas, 12 outputs, produtor de 11 tabelas) vs `CPF_Contrato__v2` (106 linhas, 1 output) têm similaridade **0,025**. `Notificações - GCP` vs `__v2`: 0,07. Nesses, tratar `__v2` como cópia descartável apagaria um projeto distinto. Estão isolados na seção 6.3.

**`vAut` / `RPA` / `GCP` indicam a versão pós-automação ou pós-migração**, geralmente a mais nova — e o par costuma aparecer nas áreas Atacado e Crédito (`ARQPAUTA` vs `ARQPAUTA_vAut`, `CL` vs `CL_vAut`, `BaseRelatorioSCR_GCP` vs `..._GCP_vAut`).

---

## 4. Os critérios de vigência

A cascata abaixo é aplicada **em ordem**; o primeiro critério que separa os candidatos decide, e os motivos ficam registrados no CSV (coluna `motivos_eleicao`). A ordem não é arbitrária — ela põe o que o analista **declarou** acima do que a máquina **inferiu**, e a evidência objetiva acima de heurística de tamanho.

| # | Critério | O que faz | Por que nessa posição |
|---|---|---|---|
| **C0** | Área espúria de coleta (`Teste EGPs`) | **desclassifica** o membro | a pasta `received_egps/Teste EGPs/` tem 4 cópias avulsas e nenhum EGP do plano; nenhuma delas é a versão dona do processo. Sem esse critério, o sufixo ` 2` desses arquivos era lido como ordinal de versão e os elegia — foi um erro real, encontrado e corrigido na revisão deste levantamento |
| **C1** | Marcador de descarte no nome (`copia`, `teste`, `antigo`, `bkp`) | **desclassifica** o membro, se sobrar algum irmão | é a intenção explícita de quem nomeou: ninguém chama de "Copia" o arquivo que está usando |
| **C2** | Marcador de vigência (`ATUAL`, `vigente`) | **promove** o membro | idem, no sentido inverso — declaração direta do dono |
| **C3** | Maior ordinal no nome (versão, data, mês/ano) | escolhe `v10` sobre `v8`, `Mai26` sobre `Fev26`, `202603` sobre `202601` | é a convenção que a área realmente usa para marcar sucessão; `__vN` de coleta é **ignorado** aqui |
| **C4** | Save mais recente do `project.xml` | árbitro objetivo | não depende de convenção de nome, mas mede *último toque*, não *versão vigente* — alguém pode abrir e salvar um arquivo velho |
| **C5** | Sinal operacional (produtor canônico > escopo > etapa de migração > nº de arestas como produtor) | escolhe o que o corpus já trata como real | reflete o que está em uso, mas é consequência de decisões anteriores — pode estar apontando para a cópia errada, e é exatamente o que a seção 8 investiga |
| **C6** | Superconjunto funcional (mais outputs, mais linhas) | último desempate | tamanho maior costuma ser evolução, mas também pode ser lixo acumulado — por isso vem no fim |
| **C7** | Modernidade técnica (`GCP`/`BQ`/`RPA`, passthrough BigQuery) | leitura de apoio, não automatizada | sinaliza a versão pós-migração; usada na análise dos casos da seção 7 |

**Marcação de conflito.** Sempre que um critério posterior aponta para outro membro, o grupo é marcado com ⚠️ em vez de fingir certeza. Foi assim que os 14 casos da seção 8 apareceram. Um veredito com conflito **não é uma decisão fechada** — é uma recomendação com o contra-argumento explícito ao lado.

**Limite do método.** C1–C6 só decidem "qual arquivo é o mais recente/vigente". Não decidem "qual processo o negócio quer manter" — isso é decisão da área, e nos 6 casos do plano (seção 7) é isso que está em jogo.

---

## 5. Taxonomia dos 118 grupos

| Família | Grupos | EGPs | O que é | Tratamento |
|---|---|---|---|---|
| **A. Duplicata de coleta** (`__vN`, mesmo código) | 29 | 64 | mesmo projeto capturado em 2+ locais | mecânico: vale o save mais recente |
| **A′. Byte-idênticos** | 3 | 6 | sha256 igual — cópia literal | mecânico: qualquer um; manter 1 |
| **B. Versão autoral** | 11 | 22 | o analista criou uma nova versão (`v2`, `Mai26`, ` 1`) | C3/C4 resolvem com segurança |
| **C. Mesmo nome, código divergente** | 29 | 64 | nome-base igual mas linhagens diferentes | **exige revisão humana** — inclui os 6 do plano |
| **D. Mesmo projeto em duas áreas — idêntico** | 27 | 56 | o mesmo binário coletado sob duas áreas | mecânico: escolher a área dona |
| **D′. Mesmo projeto em duas áreas — divergente** | 19 | 55 | versões diferentes, uma por área (padrão `vAut`) | C3/C4 + confirmar dono |

As famílias C e D′ se sobrepõem por construção: um grupo C é o *grupo de nome inteiro*, e os sub-clusters dele que fecharam por similaridade aparecem também como grupo A ou B. O CSV traz as duas visões (coluna `grupo`, prefixo `G`/`D`/`X`).

---

## 6. Grupo a grupo

O detalhamento completo de todos os 118 grupos — com save do `.egp`, linhas, outputs, arestas, etapa de migração e similaridade par a par — está em [`egps_versoes_grupos_2026-08-13.csv`](egps_versoes_grupos_2026-08-13.csv). Abaixo, cada família com o veredito e os casos que exigem leitura.

### 6.1 Família B — versões autorais (11 grupos)

Casos limpos: o nome declara a sucessão e o save do `.egp` confirma.

| Grupo | Área | Vigente | Substituído | Decidido por |
|---|---|---|---|---|
| G002 | Atacado | `Base_Bruta_GL 1` (save 2026-05-28) | `Base_Bruta_GL` (2025-09-11) | C3 + C4 concordam |
| G007 | Cobranças | `base_carta_motos_2026` (2026-02-13) | `base_carta_motos_v2` (2025-12-26) | C3 (ano 2026 > v2) + C4 |
| G010 | Cobranças | `CODIGO_PERFORMANCE_DU 1` (2025-11-21) | `CODIGO_PERFORMANCE_DU` (2025-09-29) | C3 + C4 — ⚠️ etapa está no antigo |
| G020 | Cobranças | `Projeção_Rolagem_Mai26` (2026-05-08) | `Projeção_Rolagem_Fev26` (2026-02-06) | C3 (mai > fev) + C4; o Mai26 já está **Migrado** |
| G024 | Cobranças | `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_RPA` (2026-02-12) | `..._NOVO` (2025-10-17) | C4 — o "NOVO" é o **antigo**; ver nota abaixo |
| G031 | Cobranças | `Projeto_Revisionais_Set25_V2` (2026-03-13) | `Projeto_Revisionais_Set25` (2025-10-17) | C3 + C4 |
| G033 | Cobranças | `Rastreador_v8_corr_tb_taylor_vf` (2025-08-26) | `..._corr_tb_taylor` (2025-08-22) | C4; código idêntico (sim 1,0), o `vf` é o fechamento |
| G036 | Cobranças | `ROLAGENS_GCP 2` (2026-05-08) | `ROLAGENS_GCP` (2026-03-06) | C3 + C4 |
| G045 | Operações | `Indicador Partes Relacionadas_V_1_6` (2026-02-05) | `_V_1_5` (2025-10-06) | C3 + C4 — ⚠️ etapa está no V_1_5 |
| G047 | Planej. e P&L | `Project - Vagas v2` (2025-08-06) | `Project - Vagas` (2025-05-22) | C3 + C4 |
| G063 | Riscos | `Atualização PBI Grupos 1` (2026-05-18) | `Atualização PBI Grupos` (2025-10-20) | C3 + C4 |

**G024 merece atenção**: `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_NOVO` tem mais linhas (9.099 vs 7.710), mais tasks (69 vs 54) e muito mais inputs (146 vs 33) que o `_RPA`, mas foi salvo 4 meses antes. A similaridade é 0,703 — são parentes, não cópias. A leitura é que o `_RPA` é a versão enxugada e automatizada que substituiu o `_NOVO`, e o `_NOVO` carrega inputs que a automação deixou de usar. O `_RPA` está **Migrado / Despriorizado e Contabilizado** no plano; o `_NOVO` não tem etapa. Veredito mantido no `_RPA`, mas se alguém precisar auditar quais dos 146 inputs foram perdidos, o `_NOVO` é a referência.

### 6.2 Família A — duplicatas de coleta `__vN` (29 grupos) e A′ byte-idênticos (3)

Todos resolvem pelo save mais recente, e em 24 dos 29 o membro **sem** sufixo é o mais novo (3 exceções, 2 indeterminados por falta de binário datado) — ou seja, a coleta tendeu a dar `__vN` à cópia mais velha, mas não confiavelmente. A lista completa está no CSV; o padrão é sempre o mesmo:

```
SAS_IQ_V001        save 2026-03-18   837 linhas   18 arestas como produtor   ← vigente
SAS_IQ_V001__v2    save 2026-01-28   838 linhas   18 arestas   [etapa: Migrado]  ⚠️
SAS_IQ_V001__v3    save 2025-10-23   826 linhas   18 arestas
```

Três grupos intra-área têm **todos** os membros byte-idênticos (sha256 igual), onde nenhum critério consegue — nem precisa — decidir:

| Grupo | Área | Membros | sha256 |
|---|---|---|---|
| G042 | Jurídico | `1004-Relatório_Encerramento_PU` + `__v2` | `237b7969…` (ambos, 1.761.730 bytes, save 2026-03-19) |
| G043 | Jurídico | `1500-Base Unica Civel - Visao Advogados` + `__v2` | `6b838cee…` (ambos) |
| G021 | Cobranças | `PROJECT_LINHAS_QIKVIEW_V5_RPA` + `... (1)` | `7beecd36…` (ambos) |

Nesses, manter um e descartar o outro é seguro sem análise adicional.

Isso é a identidade em nível de **grupo**. Em nível de **par**, a identidade byte a byte é muito mais comum: 46 pares distintos, envolvendo 80 EGPs — 5 dentro da mesma área (incluindo `COLCHAO_ACORDO_CL`/`__v2` e `Consignado_PF_INSS v7`/`__v2`, grupos de 3 membros onde só 2 são idênticos) e **41 entre áreas**, que é essencialmente a família D da seção 6.4.

### 6.3 Família C — mesmo nome, linhagens divergentes (29 grupos)

Aqui a similaridade de código contradiz o nome. Três subgrupos:

**(a) `__vN` que NÃO é o mesmo projeto** — tratar como cópia descartável apagaria conteúdo:

| Grupo | Membros | Similaridade | Leitura |
|---|---|---|---|
| D013 | `CPF_Contrato` (1.114 linhas, 12 outputs, produtor de 11, **produtor canônico**) vs `CPF_Contrato__v2` (106 linhas, 1 output, save mais recente) | **0,025** | projetos diferentes; o `__v2` é um script pequeno e sem papel na linhagem |
| D018 | `Notificações - GCP` (8.711 linhas, 68 inputs, Pré-conversão/Concluído) vs `__v2` (8.487 linhas, 47 inputs, save 3 meses depois) | **0,07** | idem — o `__v2` refez o projeto por outro caminho |
| D067 | `INAC Tableau v2` (676 linhas, 25 inputs, 6 arestas) vs `__v2` (419 linhas, 5 inputs) | 0,173 | idem |
| D052 | `1023-inconsistencia` (1 output) vs `__v2` (12 outputs, produtor de 2) | 0,314 | o `__v2` cria 11 tabelas que o outro não cria |
| D058 | 4 membros de `1353-ProjetoSAS-Relevantes_Prognostico` | 0,03 a 0,986 | **duas linhagens** dentro do mesmo nome: o par base/`__v2` (sim 0,986) e o par `_V2`/`_V2__v2` (0,718), mas cruzados dão 0,03 — resolvidos separadamente em G056 e G057 |

**(b) Nomes parecidos, projetos diferentes** — falso agrupamento do meu normalizador, registrado para não voltar a aparecer:

- **D027** `PROJECT_ROLAGEM_NEW` vs `Project_Rolagem v10` vs `v8`: similaridade cruzada **0,048**. O `_NEW` (12 outputs, 23 inputs) não é versão dos `Project_Rolagem` (3 outputs, 6 inputs) — são processos distintos que compartilham a palavra "Rolagem". Cada um resolve internamente (G026 e G025).
- **D022** `PROJECT_LINHAS_QIKVIEW_V4` vs `V5_RPA`: 0,337 — o V4 é versão anterior de verdade, mas reescrita o suficiente para não fechar por similaridade.
- **D072** `rito_comercial_solar` (Rodas, `.sas`) vs `Rito Comercial - Solar` (`.egp`): 0,422 — mesmo processo, um exportado como scripts e outro como projeto.

**(c) Versões autorais com reescrita grande** (0,26–0,6 de similaridade): `Base_Bruta 2` vs `Base_Bruta` (0,576), `Apetite_Gerenciados_2025_v5` vs `__v2` (0,504), `atualizacao_graficos_matriz_v2` vs `v1` (0,338), `Visibilidade Total v5` vs `Visibilidade Total` (0,384), `Estudo Feirao` vs `Estudo Feirao 1` (0,264), `0 SAS-Apuração v2` vs `0 SAS-Apuração` (0,424), `Elegibilidade_Reneg_CP` vs `__v2` (0,391), `DIAGNOSTICO_SCORE3 - 20260105` vs `- 20251013` (0,36), `Estrategia_Reneg_Solar_180_v20250305_GCP` vs `_v20251117_GCP` (0,484), `Project_Base_Contratos_Reneg` vs `__v2` (0,585), `PROJETO BI CARTOES GERAL_V3` vs `__v2` (0,43), `Processo de bonificação - taxas_v35 (2)` vs `_v38` (0,527), `ApuracaoRealizado_P&L_Atendimento 3` vs sem sufixo (0,412), `Apuracao...` e demais. Em todos, C3/C4 apontam para o mesmo membro — o veredito é confiável; a baixa similaridade só indica que a versão nova foi bastante reescrita.

Uma inversão a registrar: em **D017** o nome diz `v20251117` (mais recente) mas o save diz que o `v20250305_GCP` foi tocado depois (2026-03-09 vs 2025-12-02), e é o `v20250305_GCP` que está Pré-conversão/Concluído. Aqui a data **no nome** é a data do dado processado, não da versão do código — o critério C3 se engana e C4+C5 corrigem.

### 6.4 Família D — o mesmo projeto sob duas áreas (27 idênticos + 19 divergentes)

**27 grupos são byte-idênticos entre áreas**: o mesmo `.egp` foi coletado duas vezes, sob rótulos de área diferentes. O par recorrente é **Jurídico/Riscos** (`1004-Relatório_Encerramento_PU`, `1015-Ranking Assessorias_Dev_v17`, `1351 - Estudo Revisionais_Cobranca(Dev)`, `1351-SAS_v20201209_V2`, `SAS_IQ_V001`, `SAS_IQ_SQ_Vigente`, `1351-VINCULACAO...`) — coerente com a poda de produtor canônico que já foi feita nesses casos (ver [`NOTA_EVOLUCAO_ESCOPO_DEPS_2026-08-12.md`](NOTA_EVOLUCAO_ESCOPO_DEPS_2026-08-12.md) §4). Também aparece **Cobranças/Teste EGPs** e **Cobranças/Negócios Transacionais**, onde a área "Teste EGPs" é claramente a espúria.

**19 grupos divergem entre áreas**, e o padrão dominante é **Atacado vs Crédito com sufixo `vAut`**:

| Grupo | Áreas | Vigente | Substituído | Similaridade |
|---|---|---|---|---|
| X085 | Atacado/Crédito | `ARQPAUTA_vAut` (2026-02-13) | `ARQPAUTA` (2025-08-29) | 1,0 |
| X089 | Atacado/Crédito | `Base Monitor de Alertas_vAut` (2025-10-03) | `Base Monitor de Alertas` (2025-10-01) | 0,473 |
| X091 | Atacado/Crédito | `BaseRelatorioSCR_GCP_vAut` (2026-04-22) | `BaseRelatorioSCR_GCP` (2025-09-12) | 0,214 |
| X093 | Atacado/Crédito | `CL_vAut` (2025-08-21) | `CL` (2025-08-19) | 0,286 |
| X090 | Atacado/Crédito | `Base_Sinais_v5` (2026-02-13) | `Base_Sinais_v4` (2025-11-03) | 0,421 |
| X107 | Auditoria/Jurídico | `Reclamações_v8` (2026-04-16) | `Reclamações_v7` (2025-12-03) | 0,393 |
| X118 | Pricing/Rodas | `Visibilidade Potencial v3` (2026-03-23) | `Visibilidade Potencial`, `visibilidade-potencial` | 0,282 |

Dois com conflito de sinal:

- **X100** `Esteira V6` (save 2025-10-29) vs `Esteira 2` (save **2026-04-13**): o nome diz V6, o save diz que o "Esteira 2" foi tocado 6 meses depois. Provavelmente `Esteira 2` é uma cópia mais recente do mesmo processo, não uma versão anterior. **Precisa da área para decidir** — C3 e C4 discordam frontalmente.
- **X106** `Processo de bonificação - taxas_v38` (sem `.egp`, só `.sas`) vs `_v35 (2)` (save 2026-02-04): o v38 é maior (2.703 vs 1.889 linhas) e o nome diz v38 > v35, mas não tem binário datado para confirmar. Veredito no v38 por C3, com a ressalva.

---

## 7. Os 6 casos que custam esforço no plano de migração

Estes são os únicos grupos com **2+ membros dentro dos 191 EGPs do plano**. Todos em Cobranças, todos do padrão "processo antigo vs. processo automatizado/novo", e em todos os dois membros já receberam trabalho registrado:

| Grupo | Membro A | Membro B | Sim. | Leitura |
|---|---|---|---|---|
| **D019** | `Performance Solar` (2.419 linhas, save 2025-10-17, sem etapa) | `Performance_Solar_RPA` (1.181 linhas, 2026-01-06, **Pré-conversão/Concluído**) | 0,461 | o RPA é a versão vigente e já foi trabalhada; o antigo entrou no plano como dependência. Candidato claro a despriorizar o A. |
| **D023** | `PROJECT_MASSIFICADOS_202507 - Copia` (2.116 linhas, 2025-10-17, sem etapa) | `PROJECT_MASSIFICADOS_202507_RPA` (2.581 linhas, 2026-01-15, **Pré-conversão/Concluído**, produtor canônico de 2) | 0,592 | já identificado na nota de escopo como pendência: o nome diz "Copia" (C1 desclassifica) e o RPA é o canônico. **A poda não surtiu efeito porque produtor e consumidores referenciam a tabela por aliases de libname diferentes** — é o caso conhecido em revisão. |
| **D028** | `Novo_Project -Tratativa_1ºNivel_Oficial_v3` (4.238 linhas, 2025-10-16, Migrado/Despriorizado) | `Novo_Project_Tratativa_1_Nivel_Oficial_v3_RPA` (2.149 linhas, 2026-01-29, **Pré-conversão/Concluído**) | 0,312 | mesma versão nominal (`v3`), um automatizado. O antigo já está Despriorizado e Contabilizado — situação já resolvida na prática. |
| **D027** | `PROJECT_ROLAGEM_NEW` (Pré-conversão) | `Project_Rolagem v10` (Migrado/Despriorizado, produtor canônico de 1) | **0,048** | **não são versões** — projetos distintos que o nome aproximou. Nada a consolidar; os dois são trabalho legítimo. |
| **D004** | `2.Mix_Pagamentos_Geral` (1.160 linhas, 2025-08-13, Migrado/Despriorizado) | `2_Mix_Pagamentos_Geral - 202511 V2` (1.391 linhas, 2025-12-22, Pré-conversão) | 0,51 | o V2 de novembro substituiu o original, que já está despriorizado. Resolvido na prática. |
| **D034** | `Remuneracao_CL_202601` (1.148 linhas, 2025-12-11, Pré-conversão/Concluído) | `Remuneracao_CL_202603` (2.218 linhas, 2026-03-06, Pré-conversão/Concluído) | 0,42 | **os dois foram convertidos** — são safras mensais do mesmo processo (jan vs mar). Vale confirmar com a área se a de março substitui a de janeiro ou se ambas rodam. |

**Onde há esforço a recuperar:** D019 e D023 são os dois casos em que a versão antiga ainda está viva no plano sem ter sido substituída formalmente. D004 e D028 já se resolveram via despriorização. D027 é falso positivo. D034 é a única dúvida genuína de negócio (duas safras convertidas em paralelo).

---

## 8. Os 14 conflitos de rastreio operacional

Em 14 grupos o registro de trabalho (etapa/status de migração, ou a escolha de produtor canônico) está associado a um EGP que **não é o vigente** pelos critérios. Isso não erra as contagens do painel — cada linha é um EGP e continua sendo contada — mas cria um risco concreto: quem abrir o EGP indicado pelo painel para converter vai abrir a cópia mais antiga.

| Grupo | Registro está em | Vigente é | Distância entre os saves |
|---|---|---|---|
| **G005** | `ACORDO_AMIGAVEL_v1__v2` (Pré-conversão + **produtor canônico de 1**) | `ACORDO_AMIGAVEL_v1` | ~6 semanas |
| **G010** | `CODIGO_PERFORMANCE_DU` (Pré-conversão) | `CODIGO_PERFORMANCE_DU 1` | ~2 meses |
| **G037** | `Saldo_repactuado_v2` (Migrado) | `Saldo_repactuado_v2__v2` | ~2 meses |
| **G045** | `Indicador Partes Relacionadas_V_1_5` (Projetos Habilitados) | `_V_1_6` | ~4 meses |
| **G069** / X108 | `SAS_IQ_V001__v2` (Migrado/Despriorizado) | `SAS_IQ_V001` | ~2 meses |
| **G070** / X109 | `SAS_IQ_SQ_Vigente__v2` (Migrado/Despriorizado) | `SAS_IQ_SQ_Vigente` — o nome declara a vigência! | ~2 meses |
| G011 / X097 | `COLCHAO_ACORDO_CL__v2` (Pré-conversão) | `COLCHAO_ACORDO_CL` (produtor canônico de 1) | **byte-idênticos** (mesmo sha) |
| G021 | `PROJECT_LINHAS_QIKVIEW_V5_RPA` (Pré-conversão/Concluído) | `... (1)` | **byte-idênticos** |
| G038 | `SERASAFEIRAO_V7GCP` (Migrado/Despriorizado) | `SERASAFEIRAO_V7GCP__v2` | 2 dias |
| X100 | — | `Esteira V6` vs `Esteira 2`: C3 e C4 discordam (ver 6.4) | 6 meses |
| X106 | — | `taxas_v38` sem binário datado para confirmar | — |

Os que **merecem correção** são **G005, G010, G037, G045, G069 e G070**: a cópia registrada é materialmente mais antiga que a vigente. Nos casos byte-idênticos (G011, G021) o conflito é nominal e inofensivo — os arquivos são o mesmo. Em G038 a diferença é de 2 dias, sem consequência prática.

O caso **G070/X109** é o mais expressivo: o projeto se chama `SAS_IQ_SQ_Vigente` — o dono declarou no próprio nome qual é a versão vigente — e o registro de migração foi para a cópia `__v2`.

Vale notar o caso **G070/X109**: o projeto se chama `SAS_IQ_SQ_Vigente` — o dono declarou qual é a versão vigente no próprio nome — e o registro de migração foi para o `__v2`.

---

## 9. Recomendações

1. **Não mexer no plano por conta de duplicata de coleta.** As 47 ocorrências `__vN` não inflam o plano: só um representante de cada entrou. Descartar binários é limpeza de acervo, não redução de escopo.
2. **Levar D019 e D023 para a área de Cobranças.** São os dois casos em que a versão antiga segue viva no plano tendo já sido substituída por uma versão RPA convertida. D023 depende de resolver o problema de aliases de libname já conhecido.
3. **Confirmar D034 com a área** (Remuneracao_CL jan vs mar): as duas foram convertidas; se forem safras do mesmo processo, uma é retrabalho.
4. **Corrigir o rastreio nos 6 casos materiais da seção 8** — mover etapa/status e escolha de produtor para o EGP vigente. Sem isso, um conversor vai abrir o arquivo errado.
5. **Nunca tratar `__vN` como descartável sem checar similaridade.** Os 5 casos da seção 6.3(a) provam que o sufixo é ambíguo: em `CPF_Contrato` o `__v2` é outro projeto.
6. **Preferir C1/C3 a C4 quando houver marcador explícito.** O save do `.egp` mede último toque, não versão vigente — `SAS_IQ_SQ_Vigente` e `PROJECT_MASSIFICADOS ... - Copia` mostram que o nome carrega intenção que o timestamp não vê.

## 10. Limitações

- **C4 não se aplica a 379 dos 1.243 projetos** (30%), que não têm `project.xml` datado: 366 são scripts `.sas` soltos, 12 são `.egp` cujo binário não foi localizado pelo nome do projeto, e 1 é `.zip`. Nesses o veredito depende do nome (ex.: `Processo de bonificação - taxas_v38`, `Elegibilidade WO - GCP`, `Limite_Out_from_SAS_2 - Copia`).
- **O agrupamento por nome tem falsos positivos**, por design: normalizar removendo tokens de versão junta `PROJECT_ROLAGEM_NEW` com `Project_Rolagem v10`. A similaridade de código os separa, mas a decisão final de "é o mesmo processo de negócio?" continua humana.
- **A similaridade não distingue reescrita de projeto novo.** Um valor de 0,3–0,5 pode ser uma versão bastante refatorada ou um projeto diferente que reaproveitou código.
- **Prod está 20 nós atrás do corpus extraído** (1.223 vs 1.243), porque a publicação da regra do criador não foi para produção. Os sinais operacionais (etapa, escopo, arestas) refletem prod em 13/08.
- **O levantamento cobre nomes e conteúdo, não execução.** Nenhum critério aqui prova que a versão eleita é a que roda em produção no SAS — só que é a mais recente e a mais referenciada no corpus.
