# EGPs afetados pelo fix `%DESCOMPACTA`

Lista de todos os EGPs que ganharam inputs previamente ocultos pela macro
`%DESCOMPACTA(libname, base)` (cópia física `x cp` + `x gunzip` de
`lib.member.sas7bdat` para WORK). Antes do fix, essas leituras apareciam
unqualified na `PROC SQL` (FROM WORK), então o scan de FROM/JOIN não as
capturava como input externo e a linhagem quebrava.

## Escopo do patch aplicado a prod (2026-07-28)

- **48 EGPs** afetados (todos em Cobranças).
- **335 chaves** distintas (`tabela::LIB.MEMBER`) inseridas em `sas_inputs_monitor`.
- **407 pares** `(projeto, chave)` inseridos em `sas_egp_inputs`.
- **10 arestas** inseridas em `sas_lineage_edges` (a maioria das chaves não tem
  produtor no corpus — são inputs terminais/upstream).

O fix no extrator (`egps_analysis/egps_extractor.py:1055`, commit
`0d839a0`) detecta macros com corpo `x cp … sas7*` + `x gunzip` e registra
`LIB.MEMBER` como input qualificado via a plumbing existente.

## Lista de EGPs

Ordem alfabética. `n` = número de novas chaves capturadas para o EGP.

| EGP | n novos inputs |
|---|---:|
| `Cobranças__00. Performance_Testes_CL` | 9 |
| `Cobranças__1.REG_CARTEIRA_WO` | 7 |
| `Cobranças__16. PROTESTOS_VS_AJU` | 4 |
| `Cobranças__2. ESTUDO_CUSTAS_TOTAL` | 9 |
| `Cobranças__3.ESTUDO_ISENC_CUSTAS_TOTAL` | 9 |
| `Cobranças__8.2 VEIC_ALTO_VLR_V3` | 8 |
| `Cobranças__ATIVIDADE_EXPLORANDO_BASES` | 2 |
| `Cobranças__Avaliacao_modelos_v3` | 1 |
| `Cobranças__CODIGO_PAINEL_PERFORMANCE - V10` | 1 |
| `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` | 10 |
| `Cobranças__Carteira_RPDD_EMPRESTIMOS` | 1 |
| `Cobranças__Construcao_carteira_Risco` | 13 |
| `Cobranças__Código Elegibilidade Acima de 120D` | 36 |
| `Cobranças__ELEGIBILIDADE_COM_VALIDACAO_SUBIDA_UF` | 1 |
| `Cobranças__Elegibilidade maior que 90_GCP_v5` | 1 |
| `Cobranças__Elegibilidade menor que 90_GCP_v4` | 1 |
| `Cobranças__Elegibilidade_Gradativo_20251103_reap_v12 - Expansao_custas` | 1 |
| `Cobranças__Fase Administrativa - Novo Processo_v20260227_GCP` | 23 |
| `Cobranças__Geracao_carteira_91_120d_analise_pdd` | 1 |
| `Cobranças__Import_Excecoes` | 3 |
| `Cobranças__Migracao_Potencial v3` | 1 |
| `Cobranças__PROJECT_LINHAS_QIKVIEW_V4` | 2 |
| `Cobranças__PROJECT_LINHAS_QIKVIEW_V5_RPA` | 2 |
| `Cobranças__PROJECT_LINHAS_QIKVIEW_V5_RPA (1)` | 2 |
| `Cobranças__Painel_Desconto_3040_Edu` | 4 |
| `Cobranças__Programa_verificacao` | 1 |
| `Cobranças__Project_Aderencia_+10` | 2 |
| `Cobranças__Project_AnalisePerformanceAtrasoCurto` | 1 |
| `Cobranças__Project_Analise_Carteira_Rodas_V5` | 1 |
| `Cobranças__Project_Analise_Over90` | 1 |
| `Cobranças__Project_Reneg_WO_NEW` | 1 |
| `Cobranças__Projeto_Revisionais_Set25` | 2 |
| `Cobranças__Projeto_Revisionais_Set25_V2` | 2 |
| `Cobranças__Rastreador_v8_corr_tb_taylor` | 1 |
| `Cobranças__Rastreador_v8_corr_tb_taylor_vf` | 1 |
| `Cobranças__Reneg_Ruim_v1` | 1 |
| `Cobranças__SELECAO_DETERIORADOS - Reapontado` | 1 |
| `Cobranças__Safra e Carteira Ajuizamento` | 4 |
| `Cobranças__Safra e Carteira Ajuizamento Reapontado` | 4 |
| `Cobranças__Saldo_elegvel_Repactuao` | 1 |
| `Cobranças__Simulação_Cenários_Proposta - Reapontado` | 1 |
| `Cobranças__Teste_Carta_Cartoraria - Simplificação CP_GCP_V3` | 214 |
| `Cobranças__Valuation_Ajuizamento_10_Refatorado 2` | 9 |
| `Cobranças__base_carta_EVG_2026` | 2 |
| `Cobranças__base_carta_EVG_v4_saidarisco_v2` | 2 |
| `Cobranças__base_carta_rodas_2026` | 1 |
| `Cobranças__base_carta_rodas_v4_saidarisco_v2` | 1 |
| `Cobranças__desafiante_90a180_v0` | 1 |

## Detalhe (amostra por EGP)

Os primeiros 5 inputs novos de cada EGP (lista completa em `sas_egp_inputs` filtrando por `chave_canonica` das linhas com `refreshed_at` recente de 2026-07-28).

### `Cobranças__00. Performance_Testes_CL` (9 novos)

- `["tabela::RAFAEL.SCORE_CL_20250618","tabela::RAFAEL.SCORE_CL_20250721","tabela::RAFAEL.SCORE_CL_20250812","tabela::RAFAEL.SCORE_CL_20250911","tabela::RAFAEL.SCORE_CL_20251015","tabela::RAFAEL.SCORE_CL_20251022","tabela::RAFAEL.SCORE_CL_20251114","tabela::RAFAEL.SCORE_CL_20251118","tabela::RAFAEL.SCORE_CL_20251224"]`
- … (+4 mais)

### `Cobranças__1.REG_CARTEIRA_WO` (7 novos)

- `["tabela::RENEG.BASE_ELEG_CONT_202504","tabela::RENEG.BASE_ELEG_CONT_202505","tabela::RENEG.BASE_ELEG_CONT_202506","tabela::RENEG.BASE_ELEG_CONT_202508","tabela::RENEG.BASE_ELEG_CONT_202509","tabela::RENEG.BASE_ELEG_CONT_202511","tabela::RENEG.BASE_ELEG_CONT_202512"]`
- … (+2 mais)

### `Cobranças__16. PROTESTOS_VS_AJU` (4 novos)

- `["tabela::CAROL2.LTV_NOVO_202506","tabela::CAROL2.LTV_NOVO_202507","tabela::CAROL2.LTV_NOVO_202508","tabela::CAROL2.LTV_NOVO_202509"]`

### `Cobranças__2. ESTUDO_CUSTAS_TOTAL` (9 novos)

- `["tabela::CAROL2.LTV_NOVO_202501","tabela::CAROL2.LTV_NOVO_202502","tabela::CAROL2.LTV_NOVO_202504","tabela::CAROL2.LTV_NOVO_202506","tabela::CAROL2.LTV_NOVO_202507","tabela::CAROL2.LTV_NOVO_202508","tabela::CAROL2.LTV_NOVO_202509","tabela::VICTORL.ANALITICO_CUSTAS_AJUSTADO","tabela::VICTORL.ANALITICO_SAFRAS_CUSTAS"]`
- … (+4 mais)

### `Cobranças__3.ESTUDO_ISENC_CUSTAS_TOTAL` (9 novos)

- `["tabela::CAROL2.LTV_NOVO_202501","tabela::CAROL2.LTV_NOVO_202502","tabela::CAROL2.LTV_NOVO_202504","tabela::CAROL2.LTV_NOVO_202506","tabela::CAROL2.LTV_NOVO_202507","tabela::CAROL2.LTV_NOVO_202508","tabela::CAROL2.LTV_NOVO_202509","tabela::VICTORL.ANALITICO_CUSTAS_AJUSTADO","tabela::VICTORL.ANALITICO_SAFRAS_CUSTAS"]`
- … (+4 mais)

### `Cobranças__8.2 VEIC_ALTO_VLR_V3` (8 novos)

- `["tabela::CAROL2.LTV_NOVO_202501","tabela::CAROL2.LTV_NOVO_202502","tabela::CAROL2.LTV_NOVO_202504","tabela::CAROL2.LTV_NOVO_202506","tabela::CAROL2.LTV_NOVO_202507","tabela::CAROL2.LTV_NOVO_202508","tabela::CAROL2.LTV_NOVO_202509","tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`
- … (+3 mais)

### `Cobranças__ATIVIDADE_EXPLORANDO_BASES` (2 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX","tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__Avaliacao_modelos_v3` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__CODIGO_PAINEL_PERFORMANCE - V10` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` (10 novos)

- `["tabela::BU.BASEUNICARODAS_2012","tabela::BU.BASEUNICARODAS_2013","tabela::BU.BASEUNICARODAS_2014","tabela::BU.BASEUNICARODAS_2015","tabela::BU.BASEUNICARODAS_2016","tabela::BU.BASEUNICARODAS_2017","tabela::BU.BASEUNICARODAS_2018","tabela::BU.BASEUNICARODAS_2019","tabela::BU.BASEUNICARODAS_2020","tabela::MARINA.BASE_FINAL2"]`
- … (+5 mais)

### `Cobranças__Carteira_RPDD_EMPRESTIMOS` (1 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__Construcao_carteira_Risco` (13 novos)

- `["tabela::JOAO.CARTEIRA_202307_BRUNO","tabela::JOAO.CARTEIRA_202308_BRUNO","tabela::JOAO.CARTEIRA_202309_BRUNO","tabela::JOAO.CARTEIRA_202310_BRUNO","tabela::JOAO.CARTEIRA_202311_BRUNO","tabela::JOAO.CARTEIRA_202312_BRUNO","tabela::JOAO.CARTEIRA_TOTAL_BRUNO_AJUST_CRD","tabela::SATIE.BASEUNICARODAS_2018","tabela::SATIE.BASEUNICARODAS_2020","tabela::SATIE.BASEUNICARODAS_2021","tabela::SATIE.BASEUNICARODAS_2022","tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX","tabela::SATIE.BASE_PDD_EMPILHADA"]`
- … (+8 mais)

### `Cobranças__Código Elegibilidade Acima de 120D` (36 novos)

- `["tabela::MIKE.TESTE_DESC_ENC_3_20240110","tabela::MIKE.TESTE_DESC_ENC_3_20240126","tabela::MIKE.TESTE_DESC_ENC_3_20240209","tabela::MIKE.TESTE_DESC_ENC_3_20240223","tabela::MIKE.TESTE_DESC_ENC_3_20240311","tabela::MIKE.TESTE_DESC_ENC_3_20240326","tabela::MIKE.TESTE_DESC_ENC_3_20240409","tabela::MIKE.TESTE_DESC_ENC_3_20240423","tabela::MIKE.TESTE_DESC_ENC_3_20240507","tabela::MIKE.TESTE_DESC_ENC_3_20240604","tabela::MIKE.TESTE_DESC_ENC_3_20240618","tabela::MIKE.TESTE_DESC_ENC_3_20240702","tabela::MIKE.TESTE_DESC_ENC_3_20240716","tabela::MIKE.TESTE_DESC_ENC_3_20240730","tabela::MIKE.TESTE_DESC_ENC_3_20240805","tabela::MIKE.TESTE_DESC_ENC_3_20240809","tabela::MIKE.TESTE_DESC_ENC_3_20240823","tabela::MIKE.TESTE_DESC_ENC_3_20240906","tabela::MIKE.TESTE_DESC_ENC_3_20240923","tabela::MIKE.TESTE_DESC_ENC_3_20241007","tabela::MIKE.TESTE_DESC_ENC_3_20241018","tabela::MIKE.TESTE_DESC_ENC_3_20241104","tabela::MIKE.TESTE_DESC_ENC_3_20241118","tabela::MIKE.TESTE_DESC_ENC_3_20241202","tabela::MIKE.TESTE_DESC_ENC_3_20241216","tabela::MIKE.TESTE_DESC_ENC_3_20241230","tabela::MIKE.TESTE_DESC_ENC_3_20250113","tabela::MIKE.TESTE_DESC_ENC_3_20250128","tabela::MIKE.TESTE_DESC_ENC_3_20250210","tabela::MIKE.TESTE_DESC_ENC_3_20250224","tabela::MIKE.TESTE_DESC_ENC_3_20250311","tabela::MIKE.TESTE_DESC_ENC_3_20250325","tabela::MIKE.TESTE_DESC_ENC_3_20250411","tabela::MIKE.TESTE_DESC_ENC_3_20250428","tabela::MIKE.TESTE_DESC_ENC_3_20250512","tabela::MIKE.TESTE_DESC_ENC_3_20250526"]`
- … (+31 mais)

### `Cobranças__ELEGIBILIDADE_COM_VALIDACAO_SUBIDA_UF` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__Elegibilidade maior que 90_GCP_v5` (1 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__Elegibilidade menor que 90_GCP_v4` (1 novos)

- `["tabela::RENEG.RENEG_ATE_90_20251119_TESCON_A"]`

### `Cobranças__Elegibilidade_Gradativo_20251103_reap_v12 - Expansao_custas` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__Fase Administrativa - Novo Processo_v20260227_GCP` (23 novos)

- `["tabela::BU.BASEUNICARODAS_2012","tabela::BU.BASEUNICARODAS_2013","tabela::BU.BASEUNICARODAS_2014","tabela::BU.BASEUNICARODAS_2015","tabela::BU.BASEUNICARODAS_2016","tabela::BU.BASEUNICARODAS_2017","tabela::BU.BASEUNICARODAS_2018","tabela::BU.BASEUNICARODAS_2019","tabela::BU.BASEUNICARODAS_2020","tabela::KAUE.TRAFFIC_LIGHT","tabela::KAUE.TRAFFIC_LIGHT2","tabela::SATIE.BASE_RS_20240507","tabela::SATIE.BASE_RS_20240521","tabela::SATIE.ISENCAO_20240520","tabela::SATIE.ISENCAO_20240612","tabela::SATIE.ISENCAO_20240725","tabela::SATIE.ISENCAO_20240821","tabela::SATIE.ISENCAO_20240923","tabela::SATIE.ISENCAO_20240925","tabela::SATIE.ISENCAO_20241015","tabela::SATIE.ISENCAO_20241212","tabela::SATIE.ISENCAO_20250122","tabela::SATIE.ISENCAO_FULL_20241126"]`
- … (+18 mais)

### `Cobranças__Geracao_carteira_91_120d_analise_pdd` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__Import_Excecoes` (3 novos)

- `["tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA","tabela::SATIE.LNO_SERASA2_V"]`

### `Cobranças__Migracao_Potencial v3` (1 novos)

- `["tabela::LDUARTE.BASE_COLLECTION_EMP_5_30"]`

### `Cobranças__PROJECT_LINHAS_QIKVIEW_V4` (2 novos)

- `["tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__PROJECT_LINHAS_QIKVIEW_V5_RPA` (2 novos)

- `["tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__PROJECT_LINHAS_QIKVIEW_V5_RPA (1)` (2 novos)

- `["tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__Painel_Desconto_3040_Edu` (4 novos)

- `["tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA","tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__Programa_verificacao` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__Project_Aderencia_+10` (2 novos)

- `["tabela::MARINA.POTENCIAL_MIGRACAO_ADM_20250605","tabela::MARINA.POTENCIAL_MIGRACAO_ADM_20250703"]`

### `Cobranças__Project_AnalisePerformanceAtrasoCurto` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__Project_Analise_Carteira_Rodas_V5` (1 novos)

- `["tabela::DANIEL.IPFADM_ANALITICO_20231023_2"]`

### `Cobranças__Project_Analise_Over90` (1 novos)

- `["tabela::CRIS.BASE_FINAL_3"]`

### `Cobranças__Project_Reneg_WO_NEW` (1 novos)

- `["tabela::GUI.BASE_ELEG_CONT_202508"]`

### `Cobranças__Projeto_Revisionais_Set25` (2 novos)

- `["tabela::SAFRA.SAFRADO_5_DIASANL_24","tabela::SAFRA.SAFRADO_5_DIASANL_25"]`

### `Cobranças__Projeto_Revisionais_Set25_V2` (2 novos)

- `["tabela::SAFRA.SAFRADO_5_DIASANL_24","tabela::SAFRA.SAFRADO_5_DIASANL_25"]`

### `Cobranças__Rastreador_v8_corr_tb_taylor` (1 novos)

- `["tabela::RENEG.BASE_TESTE_CONT_202408"]`

### `Cobranças__Rastreador_v8_corr_tb_taylor_vf` (1 novos)

- `["tabela::RENEG.BASE_TESTE_CONT_202408"]`

### `Cobranças__Reneg_Ruim_v1` (1 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__SELECAO_DETERIORADOS - Reapontado` (1 novos)

- `["tabela::KAUE.TRAFFIC_LIGHT"]`

### `Cobranças__Safra e Carteira Ajuizamento` (4 novos)

- `["tabela::BU.BASEUNICARODAS_2018","tabela::BU.BASEUNICARODAS_2019","tabela::BU.BASEUNICARODAS_2020","tabela::SAFRA.SAFRADO_5_DIASANL_24_JUN25"]`

### `Cobranças__Safra e Carteira Ajuizamento Reapontado` (4 novos)

- `["tabela::BU.BASEUNICARODAS_2018","tabela::BU.BASEUNICARODAS_2019","tabela::BU.BASEUNICARODAS_2020","tabela::SAFRA.SAFRADO_5_DIASANL_24_JUN25"]`

### `Cobranças__Saldo_elegvel_Repactuao` (1 novos)

- `["tabela::RENEG.CARGA_202412"]`

### `Cobranças__Simulação_Cenários_Proposta - Reapontado` (1 novos)

- `["tabela::JOAO.BASE_ESTUDO_PERFORMANCE_MIX"]`

### `Cobranças__Teste_Carta_Cartoraria - Simplificação CP_GCP_V3` (214 novos)

- `["tabela::SATIE.CARTA_TESTE_20230913","tabela::SATIE.CARTA_TESTE_20230921","tabela::SATIE.CARTA_TESTE_20230928","tabela::SATIE.CARTA_TESTE_20231006","tabela::SATIE.CARTA_TESTE_20231011","tabela::SATIE.CARTA_TESTE_20231019","tabela::SATIE.CARTA_TESTE_20231026","tabela::SATIE.CARTA_TESTE_20231101","tabela::SATIE.CARTA_TESTE_20231109","tabela::SATIE.CARTA_TESTE_20231116","tabela::SATIE.CARTA_TESTE_20231123","tabela::SATIE.CARTA_TESTE_20231130","tabela::SATIE.CARTA_TESTE_20231207","tabela::SATIE.CARTA_TESTE_20231214","tabela::SATIE.CARTA_TESTE_20231228","tabela::SATIE.CARTA_TESTE_20240104","tabela::SATIE.CARTA_TESTE_20240111","tabela::SATIE.CARTA_TESTE_20240118","tabela::SATIE.CARTA_TESTE_20240124","tabela::SATIE.CARTA_TESTE_20240201","tabela::SATIE.CARTA_TESTE_20240208","tabela::SATIE.CARTA_TESTE_20240215","tabela::SATIE.CARTA_TESTE_20240222","tabela::SATIE.CARTA_TESTE_20240229","tabela::SATIE.CARTA_TESTE_20240307","tabela::SATIE.CARTA_TESTE_20240314","tabela::SATIE.CARTA_TESTE_20240321","tabela::SATIE.CARTA_TESTE_20240328","tabela::SATIE.CARTA_TESTE_20240404","tabela::SATIE.CARTA_TESTE_20240411","tabela::SATIE.CARTA_TESTE_20240418","tabela::SATIE.CARTA_TESTE_20240425","tabela::SATIE.CARTA_TESTE_20240502","tabela::SATIE.CARTA_TESTE_20240509","tabela::SATIE.CARTA_TESTE_20240516","tabela::SATIE.CARTA_TESTE_20240606","tabela::SATIE.CARTA_TESTE_20240613","tabela::SATIE.CARTA_TESTE_20240620","tabela::SATIE.CARTA_TESTE_20240627","tabela::SATIE.CARTA_TESTE_20240704","tabela::SATIE.CARTA_TESTE_20240711","tabela::SATIE.CARTA_TESTE_20240718","tabela::SATIE.CARTA_TESTE_20240725","tabela::SATIE.CARTA_TESTE_20240801","tabela::SATIE.CARTA_TESTE_20240808","tabela::SATIE.CARTA_TESTE_20240815","tabela::SATIE.CARTA_TESTE_20240822","tabela::SATIE.CARTA_TESTE_20240829","tabela::SATIE.CARTA_TESTE_20240905","tabela::SATIE.CARTA_TESTE_20240912","tabela::SATIE.CARTA_TESTE_20240919","tabela::SATIE.CARTA_TESTE_20240926","tabela::SATIE.CARTA_TESTE_20241003","tabela::SATIE.CARTA_TESTE_20241010","tabela::SATIE.CARTA_TESTE_20241017","tabela::SATIE.CARTA_TESTE_20241024","tabela::SATIE.CARTA_TESTE_20241031","tabela::SATIE.CARTA_TESTE_20241107","tabela::SATIE.CARTA_TESTE_20241122","tabela::SATIE.CARTA_TESTE_20241127","tabela::SATIE.CARTA_TESTE_20241205","tabela::SATIE.CARTA_TESTE_20241212","tabela::SATIE.CARTA_TESTE_20241219","tabela::SATIE.CARTA_TESTE_20241226","tabela::SATIE.CARTA_TESTE_20250109","tabela::SATIE.CARTA_TESTE_20250116","tabela::SATIE.CARTA_TESTE_20250123","tabela::SATIE.CARTA_TESTE_20250206","tabela::SATIE.CARTA_TESTE_20250213","tabela::SATIE.CARTA_TESTE_20250220","tabela::SATIE.CARTA_TESTE_20250227","tabela::SATIE.CARTA_TESTE_20250306","tabela::SATIE.CARTA_TESTE_20250313","tabela::SATIE.CARTA_TESTE_20250320","tabela::SATIE.CARTA_TESTE_20250327","tabela::SATIE.CARTA_TESTE_20250404","tabela::SATIE.CARTA_TESTE_20250411","tabela::SATIE.CARTA_TESTE_20250424","tabela::SATIE.CARTA_TESTE_20250430","tabela::SATIE.CARTA_TESTE_20250508","tabela::SATIE.CARTA_TESTE_20250523","tabela::SATIE.CARTA_TESTE_20250529","tabela::SATIE.CARTA_TESTE_20250612","tabela::SATIE.CARTA_TESTE_20250623","tabela::SATIE.CARTA_TESTE_20250627","tabela::SATIE.CARTA_TESTE_20250804","tabela::SATIE.CARTA_TESTE_20250808","tabela::SATIE.CARTA_TESTE_20250821","tabela::SATIE.CARTA_TESTE_20250909","tabela::SATIE.CARTA_TESTE_20250918","tabela::SATIE.CARTA_TESTE_20250925","tabela::SATIE.CARTA_TESTE_20251003","tabela::SATIE.CARTA_TESTE_20251009","tabela::SATIE.CARTA_TESTE_20251015","tabela::SATIE.CARTA_TESTE_20251030","tabela::SATIE.CARTA_TESTE_MOTOS_20241121","tabela::SATIE.CARTA_TESTE_MOTOS_20241127","tabela::SATIE.CARTA_TESTE_MOTOS_20241205","tabela::SATIE.CARTA_TESTE_MOTOS_20241213","tabela::SATIE.CARTA_TESTE_MOTOS_20241219","tabela::SATIE.CARTA_TESTE_MOTOS_20241226","tabela::SATIE.CARTA_TESTE_MOTOS_20250109","tabela::SATIE.CARTA_TESTE_MOTOS_20250116","tabela::SATIE.CARTA_TESTE_MOTOS_20250123","tabela::SATIE.CARTA_TESTE_MOTOS_20250206","tabela::SATIE.CARTA_TESTE_MOTOS_20250220","tabela::SATIE.CARTA_TESTE_MOTOS_20250227","tabela::SATIE.CARTA_TESTE_MOTOS_20250307","tabela::SATIE.CARTA_TESTE_MOTOS_20250313","tabela::SATIE.CARTA_TESTE_MOTOS_20250320","tabela::SATIE.CARTA_TESTE_MOTOS_20250327","tabela::SATIE.CARTA_TESTE_MOTOS_20250404","tabela::SATIE.CARTA_TESTE_MOTOS_20250411","tabela::SATIE.CARTA_TESTE_MOTOS_20250424","tabela::SATIE.CARTA_TESTE_MOTOS_20250430","tabela::SATIE.CARTA_TESTE_MOTOS_20250508","tabela::SATIE.CARTA_TESTE_MOTOS_20250523","tabela::SATIE.CARTA_TESTE_MOTOS_20250529","tabela::SATIE.CARTA_TESTE_MOTOS_20250612","tabela::SATIE.CARTA_TESTE_MOTOS_20250623","tabela::SATIE.CARTA_TESTE_MOTOS_20250627","tabela::SATIE.CARTA_TESTE_MOTOS_20250804","tabela::SATIE.CARTA_TESTE_MOTOS_20250808","tabela::SATIE.CARTA_TESTE_MOTOS_20250821","tabela::SATIE.CARTA_TESTE_MOTOS_20250909","tabela::SATIE.CARTA_TESTE_MOTOS_20250918","tabela::SATIE.CARTA_TESTE_MOTOS_20250925","tabela::SATIE.CARTA_TESTE_MOTOS_20251002","tabela::SATIE.CARTA_TESTE_MOTOS_20251009","tabela::SATIE.CARTA_TESTE_MOTOS_20251015","tabela::SATIE.CARTA_TESTE_MOTOS_20251030","tabela::SATIE.CARTA_TESTE_RODAS_20231201","tabela::SATIE.CARTA_TESTE_RODAS_20231207","tabela::SATIE.CARTA_TESTE_RODAS_20231214","tabela::SATIE.CARTA_TESTE_RODAS_20231221","tabela::SATIE.CARTA_TESTE_RODAS_20231228","tabela::SATIE.CARTA_TESTE_RODAS_20240104","tabela::SATIE.CARTA_TESTE_RODAS_20240111","tabela::SATIE.CARTA_TESTE_RODAS_20240118","tabela::SATIE.CARTA_TESTE_RODAS_20240124","tabela::SATIE.CARTA_TESTE_RODAS_20240201","tabela::SATIE.CARTA_TESTE_RODAS_20240208","tabela::SATIE.CARTA_TESTE_RODAS_20240215","tabela::SATIE.CARTA_TESTE_RODAS_20240222","tabela::SATIE.CARTA_TESTE_RODAS_20240229","tabela::SATIE.CARTA_TESTE_RODAS_20240307","tabela::SATIE.CARTA_TESTE_RODAS_20240314","tabela::SATIE.CARTA_TESTE_RODAS_20240321","tabela::SATIE.CARTA_TESTE_RODAS_20240328","tabela::SATIE.CARTA_TESTE_RODAS_20240404","tabela::SATIE.CARTA_TESTE_RODAS_20240411","tabela::SATIE.CARTA_TESTE_RODAS_20240418","tabela::SATIE.CARTA_TESTE_RODAS_20240425","tabela::SATIE.CARTA_TESTE_RODAS_20240502","tabela::SATIE.CARTA_TESTE_RODAS_20240509","tabela::SATIE.CARTA_TESTE_RODAS_20240516","tabela::SATIE.CARTA_TESTE_RODAS_20240606","tabela::SATIE.CARTA_TESTE_RODAS_20240613","tabela::SATIE.CARTA_TESTE_RODAS_20240620","tabela::SATIE.CARTA_TESTE_RODAS_20240627","tabela::SATIE.CARTA_TESTE_RODAS_20240704","tabela::SATIE.CARTA_TESTE_RODAS_20240711","tabela::SATIE.CARTA_TESTE_RODAS_20240718","tabela::SATIE.CARTA_TESTE_RODAS_20240725","tabela::SATIE.CARTA_TESTE_RODAS_20240801","tabela::SATIE.CARTA_TESTE_RODAS_20240808","tabela::SATIE.CARTA_TESTE_RODAS_20240815","tabela::SATIE.CARTA_TESTE_RODAS_20240822","tabela::SATIE.CARTA_TESTE_RODAS_20240829","tabela::SATIE.CARTA_TESTE_RODAS_20240904","tabela::SATIE.CARTA_TESTE_RODAS_20240912","tabela::SATIE.CARTA_TESTE_RODAS_20240919","tabela::SATIE.CARTA_TESTE_RODAS_20240926","tabela::SATIE.CARTA_TESTE_RODAS_20241003","tabela::SATIE.CARTA_TESTE_RODAS_20241010","tabela::SATIE.CARTA_TESTE_RODAS_20241017","tabela::SATIE.CARTA_TESTE_RODAS_20241024","tabela::SATIE.CARTA_TESTE_RODAS_20241031","tabela::SATIE.CARTA_TESTE_RODAS_20241107","tabela::SATIE.CARTA_TESTE_RODAS_20241127","tabela::SATIE.CARTA_TESTE_RODAS_20241205","tabela::SATIE.CARTA_TESTE_RODAS_20241212","tabela::SATIE.CARTA_TESTE_RODAS_20241219","tabela::SATIE.CARTA_TESTE_RODAS_20241226","tabela::SATIE.CARTA_TESTE_RODAS_20250109","tabela::SATIE.CARTA_TESTE_RODAS_20250116","tabela::SATIE.CARTA_TESTE_RODAS_20250123","tabela::SATIE.CARTA_TESTE_RODAS_20250206","tabela::SATIE.CARTA_TESTE_RODAS_20250220","tabela::SATIE.CARTA_TESTE_RODAS_20250227","tabela::SATIE.CARTA_TESTE_RODAS_20250307","tabela::SATIE.CARTA_TESTE_RODAS_20250313","tabela::SATIE.CARTA_TESTE_RODAS_20250320","tabela::SATIE.CARTA_TESTE_RODAS_20250327","tabela::SATIE.CARTA_TESTE_RODAS_20250404","tabela::SATIE.CARTA_TESTE_RODAS_20250411","tabela::SATIE.CARTA_TESTE_RODAS_20250424","tabela::SATIE.CARTA_TESTE_RODAS_20250430","tabela::SATIE.CARTA_TESTE_RODAS_20250508","tabela::SATIE.CARTA_TESTE_RODAS_20250523","tabela::SATIE.CARTA_TESTE_RODAS_20250529","tabela::SATIE.CARTA_TESTE_RODAS_20250612","tabela::SATIE.CARTA_TESTE_RODAS_20250623","tabela::SATIE.CARTA_TESTE_RODAS_20250626","tabela::SATIE.CARTA_TESTE_RODAS_20250804","tabela::SATIE.CARTA_TESTE_RODAS_20250808","tabela::SATIE.CARTA_TESTE_RODAS_20250821","tabela::SATIE.CARTA_TESTE_RODAS_20250909","tabela::SATIE.CARTA_TESTE_RODAS_20250918","tabela::SATIE.CARTA_TESTE_RODAS_20250925","tabela::SATIE.CARTA_TESTE_RODAS_20251002","tabela::SATIE.CARTA_TESTE_RODAS_20251009","tabela::SATIE.CARTA_TESTE_RODAS_20251015","tabela::SATIE.CARTA_TESTE_RODAS_20251030"]`
- … (+209 mais)

### `Cobranças__Valuation_Ajuizamento_10_Refatorado 2` (9 novos)

- `["tabela::BRUNO.CARTEIRA_202312_BRUNO","tabela::LUFILHO.BASE_FECHAMENTO_AGO24","tabela::LUFILHO.BASE_FECHAMENTO_JUL24","tabela::LUFILHO.BASE_FECHAMENTO_OUT24","tabela::LUFILHO.BASE_FECHAMENTO_SET24","tabela::LUFILHO.VAREJO_2023","tabela::LUFILHO.VAREJO_2024","tabela::PRETER.EMP_2023_BASE_COBRANCA","tabela::PRETER.EMP_2024_BASE_COBRANCA"]`
- … (+4 mais)

### `Cobranças__base_carta_EVG_2026` (2 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA","tabela::SATIE.CAMPANHA_H_EMP_80"]`

### `Cobranças__base_carta_EVG_v4_saidarisco_v2` (2 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA","tabela::SATIE.CAMPANHA_H_EMP_80"]`

### `Cobranças__base_carta_rodas_2026` (1 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__base_carta_rodas_v4_saidarisco_v2` (1 novos)

- `["tabela::PRETER.EMP_2024_BASE_COBRANCA"]`

### `Cobranças__desafiante_90a180_v0` (1 novos)

- `["tabela::RENEG.BASE_ELEG_CONT_202505"]`

