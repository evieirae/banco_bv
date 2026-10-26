# Dependências entre EGPs — Escopo Indicium (231 Indicium)

> Gerado em 2026-06-11 a partir de `03_matriz_dependencias.csv` (roda do orchestrator de 2026-06-11)
> e do mapeamento `indi_231_vs_extracao_06.csv`. Detalhe completo (aresta a aresta, com as tabelas
> que materializam cada dependência): **`dependencias_indi_231.csv`** nesta pasta.

## Resumo

| Métrica | Valor |
|---|---|
| EGPs Indicium analisados | **229** de 231 (1 faltante: `ca_apagar_periodo`; 1 sem mapeamento não há) |
| Indicium que dependem de outro EGP | **130** |
| Indicium autônomos (dependem só de fontes externas/ingestão, nenhum EGP) | **99** |
| Arestas EGP→EGP no fechamento transitivo | **437** |
| **EGPs FORA dos 231 que são pré-requisito** (fechamento transitivo) | **73** (sendo 65 dependência direta de algum Indicium) |
| Profundidade máxima de cadeia | **3** níveis |

**Leitura:** `nivel 0` = EGP do escopo Indicium; `nivel 1` = EGP fora dos 231 do qual um Indicium depende
diretamente; `nivel 2-3` = dependência da dependência (cadeia transitiva).

## 1. Pré-requisitos EXTERNOS aos 231 (ordenados por impacto)

EGPs que **não estão** no escopo Indicium mas **produzem tabelas consumidas** (direta ou
transitivamente) por EGPs do escopo. Migrar/ingerir a saída deles é pré-condição.

| EGP externo (pré-requisito) | Área | Nível | Indicium impactados |
|---|---|---:|---:|
| `Riscos__DBEP_Andamentos` | Riscos | 1 | 19 |
| `Crédito__Base_Bruta_GL` | Crédito | 1 | 18 |
| `Atacado__Base_Bruta` | Atacado | 1 | 17 |
| `Atacado__Base_Sinais_v5` | Atacado | 1 | 17 |
| `Atacado__Esteira 2` | Atacado | 1 | 17 |
| `Atacado__GCarteira` | Atacado | 1 | 17 |
| `Atacado__[Gestão_de_Carteira] Motores` | Atacado | 1 | 17 |
| `Crédito__Base_Bruta` | Crédito | 1 | 17 |
| `Crédito__CIB` | Crédito | 1 | 17 |
| `Crédito__Esteira - OMIE Sacados_v2` | Crédito | 1 | 17 |
| `Crédito__Esteira - Sales Finance PJ` | Crédito | 1 | 17 |
| `Crédito__[Gestão_de_Carteira] Motores` | Crédito | 2 | 17 |
| `Riscos__Base_Unica_202509` | Riscos | 1 | 17 |
| `Riscos__Controle_PMES_v19__v2` | Riscos | 2 | 17 |
| `Riscos__Indicadores_PMEs_PPT_V3` | Riscos | 1 | 17 |
| `Riscos__VNP - Diario Middle e Corporate_2025_WINSCP` | Riscos | 2 | 17 |
| `Cobranças__20250918_darkpost_v15` | Cobranças | 1 | 14 |
| `Riscos__DBEP_Pagamento` | Riscos | 1 | 11 |
| `Riscos__SAS_IQ_V001__v2` | Riscos | 1 | 9 |
| `Cobranças__ACORDO_AMIGAVEL_v1__v2` | Cobranças | 1 | 8 |
| `Riscos__DBEP_ProcessosReabertura` | Riscos | 1 | 8 |
| `Riscos__DBEP_Causas` | Riscos | 1 | 6 |
| `Riscos__DBEP_Garantia` | Riscos | 1 | 6 |
| `Cobranças__Carteira_CA_COMPLETA_GCP_2` | Cobranças | 1 | 5 |
| `Riscos__ATUALIZACAO_BASES v09` | Riscos | 2 | 5 |
| `Riscos__BASES_Portal_Cloud` | Riscos | 2 | 5 |
| `Riscos__Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` | Riscos | 1 | 5 |
| `Riscos__DBEP_Partes` | Riscos | 1 | 5 |
| `Riscos__DBEP_Processos` | Riscos | 1 | 5 |
| `Riscos__MONITORAMENTO_CONSOLIDADO_UNDERWRITTING` | Riscos | 1 | 5 |
| `Riscos__SAS_IQ_SQ_Vigente__v2` | Riscos | 1 | 5 |
| `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` | Cobranças | 1 | 4 |
| `Cobranças__Painel_Desconto_Perf_Solar` | Cobranças | 1 | 4 |
| `Crédito__02. Classifica reg 3.1 - cdloja_Grupo` | Crédito | 1 | 4 |
| `Riscos__Apetite_Gerenciados_2025_v5__v2` | Riscos | 1 | 4 |
| `Riscos__DBEP_Assessorias` | Riscos | 1 | 4 |
| `Riscos__DBEP_ProcessoRequisicao` | Riscos | 1 | 4 |
| `Riscos__DBEP_Requisicoes` | Riscos | 1 | 4 |
| `Riscos__1040-DBEP_Desdobramentos` | Riscos | 1 | 3 |
| `Riscos__1040-DBEP_LiberacaoGarantia` | Riscos | 1 | 3 |
| `Riscos__DBEP_Motivos` | Riscos | 1 | 3 |
| `Riscos__DBEP_ProcessoRequisicaoAtributo` | Riscos | 1 | 3 |
| `Riscos__DBEP_Produto` | Riscos | 1 | 3 |
| `Cobranças__COLCHAO_ACORDO_CL__v2` | Cobranças | 1 | 2 |
| `Cobranças__Entrada_em_Cob_Geral_REAPONTADO_V2` | Cobranças | 1 | 2 |
| `Riscos__1023-inconsistencia__v2` | Riscos | 1 | 2 |
| `Riscos__ATUALIZACAO_PROJURIS V10` | Riscos | 1 | 2 |
| `Riscos__Atualizaç╞o BD Cíveis Massificadas V11 Projuris` | Riscos | 1 | 2 |
| `Riscos__DBEP_Contratos` | Riscos | 2 | 2 |
| `Cobranças__CartoesAmigaveis_PilotoAcordos_20260515` | Cobranças | 1 | 1 |
| `Cobranças__Novo_Project -Tratativa_1ºNivel_Oficial_v3` | Cobranças | 1 | 1 |
| `Cobranças__Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5` | Cobranças | 1 | 1 |
| `Cobranças__Project_Rolagem v8` | Cobranças | 1 | 1 |
| `Cobranças__Público Elasticidade_reap` | Cobranças | 1 | 1 |
| `Cobranças__SALDO_ALTOS_+_PE_20260224 - Reapontado_VF` | Cobranças | 1 | 1 |
| `Cobranças__SALDO_REMANESCENTE_V2` | Cobranças | 1 | 1 |
| `Cobranças__Teste_Carta_Cartoraria - Simplificação CP_GCP_V3` | Cobranças | 1 | 1 |
| `Cobranças__Valida_carga_v1_cp` | Cobranças | 1 | 1 |
| `Negócios e Produtos Relacional e Seguros__BaseUnica` | Negócios e Produtos Relacional e Seguros | 1 | 1 |
| `Riscos__Análise de Variaç╞o v8` | Riscos | 1 | 1 |
| `Riscos__AçΣes Alçadas Apuraç╞o v3` | Riscos | 1 | 1 |
| `Riscos__DBEP_Acordo` | Riscos | 1 | 1 |
| `Riscos__DBEP_Audiencia` | Riscos | 1 | 1 |
| `Riscos__DBEP_ProcessoObjetoPrognostico` | Riscos | 1 | 1 |
| `Riscos__DBEP_ProvisaoJuridica` | Riscos | 1 | 1 |
| `Riscos__DBEP_Reclassificacoes` | Riscos | 1 | 1 |
| `Riscos__DBEP_UsuarioEncerramento` | Riscos | 1 | 1 |
| `Riscos__INAC Tableau v2__v2` | Riscos | 1 | 1 |
| `Riscos__RelatorioVFIN v8` | Riscos | 1 | 1 |
| `Riscos__Tableau_2025.v2` | Riscos | 1 | 1 |
| `SAS_UC4__etl_bhrodas` | SAS_UC4 | 1 | 1 |
| `SAS_UC4__ext_seguros` | SAS_UC4 | 2 | 1 |
| `Seguros__CODIGO_PRODUTO_NOVO_FINANCE (1)` | Seguros | 3 | 1 |

### 1.1 Cadeias transitivas (dependência de dependência)

Externos que nenhum Indicium consome diretamente — entram porque **outro externo** depende deles:

- `Crédito__[Gestão_de_Carteira] Motores` (nível 2) ← consumido por: `Atacado__[Gestão_de_Carteira] Motores`
- `Riscos__ATUALIZACAO_BASES v09` (nível 2) ← consumido por: `Riscos__Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud`
- `Riscos__BASES_Portal_Cloud` (nível 2) ← consumido por: `Riscos__Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud`
- `Riscos__Controle_PMES_v19__v2` (nível 2) ← consumido por: `Riscos__Base_Unica_202509`, `Riscos__Indicadores_PMEs_PPT_V3`
- `Riscos__DBEP_Contratos` (nível 2) ← consumido por: `Riscos__Atualizaç╞o BD Cíveis Massificadas V11 Projuris`
- `Riscos__VNP - Diario Middle e Corporate_2025_WINSCP` (nível 2) ← consumido por: `Atacado__Base_Bruta`, `Crédito__Base_Bruta`, `Riscos__Tableau_2025.v2`
- `SAS_UC4__ext_seguros` (nível 2) ← consumido por: `Negócios e Produtos Relacional e Seguros__BaseUnica`
- `Seguros__CODIGO_PRODUTO_NOVO_FINANCE (1)` (nível 3) ← consumido por: `SAS_UC4__ext_seguros`

## 2. Dependências diretas de cada EGP Indicium

Os 130 EGPs do escopo que dependem de pelo menos um outro EGP. Legenda: **[EXT]** = fora dos 231.

### Atacado

- **`Atacado__Base Monitor de Alertas_vAut`** depende de:
  - `Crédito__CIB` **[EXT]** — via `SHAREATA.TBCARTEIRAGRUPO`
- **`Atacado__BaseRelatorioSCR_GCP_vAut`** depende de:
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `INSIGHT.TBBRUTA`
- **`Atacado__Base_Carteira_Consolidada`** depende de:
  - `Crédito__CIB` **[EXT]** — via `INSIGHT.TBPESSOA`
  - `Riscos__Base_Unica_202509` **[EXT]** — via `MISCRED.BASE_UNICA_ATACADO_202408`
- **`Atacado__CL_CTR`** depende de:
  - `Atacado__Painel Sales Finance` — via `PME.BASE_CADASTRAL_SERASA_PJ`
  - `Crédito__Esteira - OMIE Sacados_v2` **[EXT]** — via `PME.BASE_RESTR_SERASA_PJ`
  - `Crédito__Esteira - Sales Finance PJ` **[EXT]** — via `PME.BASE_HBV8_SERASA_PJ`
  - `Riscos__Base_Unica_202509` **[EXT]** — via `MISCRED.MATRIZ_SETORES`
- **`Atacado__Painel Sales Finance`** depende de:
  - `Atacado__Base_Bruta` **[EXT]** — via `PLCA.TBSISTEMAPLCA`, `SHAREATA.TBRATING_V2`
  - `Atacado__Base_Carteira_Consolidada` — via `ATUAL.CLIENTES_ATUAL_2026`
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `INSIGHT.TBBRUTA`
  - `Atacado__Esteira 2` **[EXT]** — via `INSIGHT.TBPMEANALITICA`, `PME.BASE_FATURAMENTO_SERASA_PJ`
  - `Atacado__[Gestão_de_Carteira] Motores` **[EXT]** — via `PME.BASE_HISTORICA_PMUM_SF`, `PME.TBMGCANALITICA`
  - `Crédito__Esteira - OMIE Sacados_v2` **[EXT]** — via `PME.BASE_SCORE_SERASA_PJ`
  - `Crédito__Esteira - Sales Finance PJ` **[EXT]** — via `PME.BASE_HBV8_SERASA_PJ`
- **`Atacado__Project_semiUpper`** depende de:
  - `Atacado__Base_Bruta` **[EXT]** — via `INSIGHT.TBVNP`
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `INSIGHT.TBBRUTA`
  - `Atacado__Esteira 2` **[EXT]** — via `PME.BASE_FATURAMENTO_SERASA_PJ`
  - `Atacado__GCarteira` **[EXT]** — via `GCSERASA.TBGCRESUMOOCORRENCIAS`, `GCSERASA.TBGCSOCIOS`
  - `Crédito__Base_Bruta` **[EXT]** — via `INSIGHT.TB_GARANTIAS_ANALITICO`
  - `Crédito__CIB` **[EXT]** — via `SHAREATA.TBCARTEIRAGRUPO`
  - `Crédito__Esteira - OMIE Sacados_v2` **[EXT]** — via `PME.BASE_SCORE_SERASA_PJ`

### Cobranças

- **`Cobranças__1.REG_CARTEIRA_WO`** depende de:
  - `Cobranças__Processo_Semanal_V2` — via `JOAO.SIMULACAO_AJUIZAMENTO_NEW`
- **`Cobranças__14.PROTESTO_SELECAO_PUBLICO`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `LDUARTE.BASE_ATUACAO_202602`
- **`Cobranças__16. PROTESTOS_VS_AJU`** depende de:
  - `Cobranças__Processo_Semanal_V2` — via `JOAO.SIMULACAO_AJUIZAMENTO_NEW`
  - `Riscos__1110 - Tributario Estrategico` — via `DATE`
- **`Cobranças__2.Mix_Pagamentos_Geral`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
  - `Cobranças__Carteira_CA_COMPLETA_GCP_2` **[EXT]** — via `CARNEIRO.CARTEIRA_CA`
- **`Cobranças__2_Mix_Pagamentos_Geral - 202511 V2`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
  - `Cobranças__Carteira_CA_COMPLETA_GCP_2` **[EXT]** — via `CARNEIRO.CARTEIRA_CA`
- **`Cobranças__3.Performance_Assessoria_COMPLETO`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
  - `Cobranças__Carteira_CA_COMPLETA_GCP_2` **[EXT]** — via `CARNEIRO.CARTEIRA_CA`
- **`Cobranças__ACOMPANHAMENTO_DESCONTO`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__ALIMENTAR DASH - NPSv10 - copia`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__Processo_NPS_UNICO_SEG_DIG` — via `NPS.BA_ESTOQUE_NPSENVIO`
- **`Cobranças__Acompanhamento_Desconto - Painel_VE2`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Análise Desconto Outubro 2025`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__PUBLICO_INELASTICO_GRADATIVO` — via `LDUARTE.CHAVE_GRADATIVO_121D_360D`, `LDUARTE.REGRA_GRADATIVO_121D_360D`
- **`Cobranças__Apuração_Simplificada_202505`** depende de:
  - `Cobranças__Carteira_Envio_Protesto_Solar_GCP` — via `TALITA.BASE_PROTESTO_ANALIT_10022026`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__Notificações - GCP` — via `TALITA.NOTIFICACAO_SOLAR_20251205`
  - `Cobranças__processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` — via `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211`, `GRIMALDI.SOLAR_MASSIFICADOS_20250211`
- **`Cobranças__Avaliacao_modelos_v3`** depende de:
  - `Cobranças__Teste_Carta_Cartoraria - Simplificação CP_GCP_V3` **[EXT]** — via `SAFRA`
- **`Cobranças__Avaliação de perfil deteriorado - Mundo Auto`** depende de:
  - `Cobranças__1.REG_CARTEIRA_WO` — via `LDUARTE.BASE_VENDA_RODAS`
  - `Cobranças__ELEGIBILIDADE_COM_VALIDACAO_SUBIDA_UF` — via `LDUARTE.BASE_TESTE_GRADATIVO`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Avaliação de perfil deteriorado por performance - Mundo Auto`** depende de:
  - `Cobranças__1.REG_CARTEIRA_WO` — via `LDUARTE.BASE_VENDA_RODAS`
  - `Cobranças__Avaliação de perfil deteriorado - Mundo Auto` — via `LDUARTE.CHAVE_ATIVA_GRADATIVO_202601`, `LDUARTE.REGRA_ATIVA_GRADATIVO_202601`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__CODIGO_APURACAO_AGO25 - Versão Final`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`, `GTAVARES.ACAO_31A60_202503_TESCON_GERAL`
- **`Cobranças__CODIGO_PAINEL_PERFORMANCE - V10`** depende de:
  - `Cobranças__1.REG_CARTEIRA_WO` — via `LDUARTE.BASE_VENDA_RODAS`
  - `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` **[EXT]** — via `LDUARTE.PUBLICO_DETERIORADO_COMEX`
- **`Cobranças__CODIGO_PERFORMANCE_DU`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Carta_Cartoraria_REAPONTADO_v2`** depende de:
  - `Cobranças__processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` — via `SOLAR.BASE_SOLAR_OUT`
- **`Cobranças__Carteira_Bruno_YYYYMM`** depende de:
  - `Riscos__Apetite_Gerenciados_2025_v5__v2` **[EXT]** — via `BASE`, `BASE1`
- **`Cobranças__Carteira_Envio_Protesto_Solar_GCP`** depende de:
  - `Cobranças__Oportunidade Protesto - Piloto de Ajuizamento_GCP` — via `KEVIN.PUBLICO_PROTESTO_20260210`
- **`Cobranças__CartoesAmigaveis_PilotoAcordos_20260227`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
- **`Cobranças__CartoesAmigaveis_PilotoAcordos_20260306_2`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
- **`Cobranças__Consignado_PF_INSS v7`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Consulta_NPS_202602`** depende de:
  - `Cobranças__Processo_NPS_UNICO_SEG_DIG` — via `CLEBER.TB_BOLETOCANAL`
- **`Cobranças__Código Elegibilidade Acima de 120D`** depende de:
  - `Cobranças__Público Elasticidade_reap` **[EXT]** — via `COMP_TOT.BASE_ELASTICIDADE_20260306`
- **`Cobranças__Diagnostico_pesados_V3`** depende de:
  - `Cobranças__Painel_Desconto_Perf_Solar` **[EXT]** — via `KAUE.BASE_CYBER`
- **`Cobranças__Diagnostico_produtos`** depende de:
  - `Cobranças__Painel_Desconto_Perf_Solar` **[EXT]** — via `KAUE.BASE_CYBER`
- **`Cobranças__EA_Semanal_NovoProcesso_GCP_V2`** depende de:
  - `Cobranças__Campanha_Entrega_amigavel_v4_mensal_gcp` — via `ENTREGA.BASE_ELEG_110226`
- **`Cobranças__ELEGIBILIDADE_COM_VALIDACAO_SUBIDA_UF`** depende de:
  - `Cobranças__Painel_Desconto_Perf_Solar` **[EXT]** — via `KAUE.BASE_CYBER`
- **`Cobranças__ENTREGA_AMIGAVEL_reneg_GCP`** depende de:
  - `Cobranças__Campanha_Entrega_amigavel_v4_mensal_gcp` — via `ENTREGA.BASE_ELEG_110226`
- **`Cobranças__Entrada_Cobranca_5DDA_GCP`** depende de:
  - `Cobranças__Regularizacao_Mensal_EDU_GCP` — via `MOVTO.PERF_AMIGAVEL`
- **`Cobranças__Entrada_Cobranca_N_DDA_GCP`** depende de:
  - `Cobranças__Carteira_CA_COMPLETA_GCP_2` **[EXT]** — via `CARNEIRO.CARTEIRA_CA`
- **`Cobranças__Envio SMS - Pagamentos - Cartão Amigável`** depende de:
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.COB_MDM_TELEFONE_BKPD3`
  - `Cobranças__Regularizacao_Mensal_EDU_GCP` — via `MOVTO.PERF_AMIGAVEL`
- **`Cobranças__Fase Administrativa - Novo Processo_v20260227_GCP`** depende de:
  - `Cobranças__SALDO_ALTOS_+_PE_20260224 - Reapontado_VF` **[EXT]** — via `LDUARTE.BASE_ALTA_PROVISAO_202602`
  - `Riscos__Apetite_Gerenciados_2025_v5__v2` **[EXT]** — via `BASE1`, `BASE3`
- **`Cobranças__MIS-AcordoV3`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Marcacao_20260220`** depende de:
  - `Cobranças__CPF_Contrato` — via `CARNEIRO.BASE_3040_202601`
- **`Cobranças__Marcacao_Teste_IOF_GCP`** depende de:
  - `Cobranças__CPF_Contrato` — via `CARNEIRO.BASE_3040_202601`
- **`Cobranças__Marketplace_Rodas_Emprestimos_v5`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_CYBER_INFO_VEIC`, `CONTATOS.AUX_SYNAPSE_MDM_EMAIL`, `CONTATOS.AUX_SYNAPSE_MDM_TEL`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Bloqueio_RFlow_Manual` — via `ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`
- **`Cobranças__NOVO_IPF_V9_MACRO_MES_RPA`** depende de:
  - `SAS_UC4__etl_bhrodas` **[EXT]** — via `TB_RENEG_SIMULADOR`
- **`Cobranças__Novo_Project_Tratativa_1_Nivel_Oficial_v3_RPA`** depende de:
  - `Cobranças__Novo_Project -Tratativa_1ºNivel_Oficial_v3` **[EXT]** — via `ESTOQUE.ESTOQUE_SALESFORCE_CARTAO`
  - `Crédito__02. Classifica reg 3.1 - cdloja_Grupo` **[EXT]** — via `BASE01`
- **`Cobranças__PERFORMANCE_CL_202603`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__Regularizacao_Mensal_EDU_GCP` — via `MOVTO.PERF_AMIGAVEL`
- **`Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__PERFORMANCE_CL_202603` — via `PERF_CL.RESULT_DIST_CL_202502`
  - `Cobranças__Regularizacao_Mensal_EDU_GCP` — via `MOVTO.PERF_AMIGAVEL`
- **`Cobranças__PROJECT_LINHAS_QIKVIEW_V5_RPA`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__Projecao_RPDD_4966_Filtrado` — via `CARNEIRO.NUCONTRATO_CONTABIL`
  - `Cobranças__Project_Rolagem v8` **[EXT]** — via `LUCAS.PASTA1`
- **`Cobranças__PROJECT_MASSIFICADOS_202507_RPA`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__PROJETO BI CARTOES GERAL_V3`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
  - `Cobranças__Carteira_CA_COMPLETA_GCP_2` **[EXT]** — via `CARNEIRO.CARTEIRA_CA`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__PERFORMANCE_CL_202603` — via `PERF_CL.RESULT_DIST_CL_202502`
  - `Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU` — via `PERF_CL.CART_COB_DIST_CL_202502`, `PERF_CL.CL_TABLEAU`, `PERF_CL.PAGOS_COB_CL_202502`, `PERF_CL.PAGOS_CYBER_202502`
  - `Riscos__1110 - Tributario Estrategico` — via `DATE`
- **`Cobranças__PUBLICO_INELASTICO_GRADATIVO`** depende de:
  - `Cobranças__ELEGIBILIDADE_COM_VALIDACAO_SUBIDA_UF` — via `LDUARTE.BASE_TESTE_GRADATIVO`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Painel_Desconto_3040_Edu`** depende de:
  - `Cobranças__CPF_Contrato` — via `CARNEIRO.BASE_3040_202510`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__Projecao_RPDD_4966_Filtrado` — via `CARNEIRO.NUCONTRATO_CONTABIL`
- **`Cobranças__Performance_Produtos_V1`** depende de:
  - `Cobranças__CobrancaAcima120dias_v15_GCP` — via `CART.MIS_RESULT_120_WO`
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU` — via `PERF_CL.CL_TABLEAU`
  - `Cobranças__PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente` — via `ATIVANEW.MIS_TABLEAU_GERAL`
  - `Cobranças__Performance_Solar_RPA` — via `ATIVA.BASE_EXPORT`
  - `Cobranças__SALDO_REMANESCENTE_V2` **[EXT]** — via `SALDO.MIS_TABLEAU_SALDO_GERAL`
- **`Cobranças__Processo_NPS_UNICO_SEG_DIG`** depende de:
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.COB_MDM_TELEFONE_BKPD3`
  - `Crédito__02. Classifica reg 3.1 - cdloja_Grupo` **[EXT]** — via `BASE02`
- **`Cobranças__Programa_Marcação_Encargos_Sem_Flex`** depende de:
  - `Cobranças__Entrada_em_Cob_Geral_REAPONTADO_V2` **[EXT]** — via `LDUARTE.BAD_BANK`
  - `Cobranças__processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` — via `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211`, `GRIMALDI.SOLAR_MASSIFICADOS_20250211`
- **`Cobranças__Programa_v2`** depende de:
  - `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` **[EXT]** — via `LDUARTE.PUBLICO_DETERIORADO_COMEX`
- **`Cobranças__Projecao_RPDD_4966_Filtrado`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
  - `Cobranças__CPF_Contrato` — via `CARNEIRO.BASE_3040_202509`
  - `Cobranças__CartoesAmigaveis_PilotoAcordos_20260515` **[EXT]** — via `CARNEIRO.INFO_CONTA`
- **`Cobranças__Projecao_Rolagem - 3040 - 2026`** depende de:
  - `Cobranças__ACORDO_AMIGAVEL_v1__v2` **[EXT]** — via `CARD_ACR.EFETIVACOES_HIST`
  - `Cobranças__Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5` **[EXT]** — via `PAGOSCBR.PAGOS_CYBER_202603`
  - `Cobranças__Regularizacao_Mensal_EDU_GCP` — via `MOVTO.PERF_AMIGAVEL`
- **`Cobranças__Project_AnalisePerformanceAtrasoCurto`** depende de:
  - `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` **[EXT]** — via `LDUARTE.PUBLICO_DETERIORADO_COMEX`
- **`Cobranças__Project_Analise_Leves_V2`** depende de:
  - `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` **[EXT]** — via `LDUARTE.PUBLICO_DETERIORADO_COMEX`
  - `Riscos__RelatorioVFIN v8` **[EXT]** — via `LIMITE`
- **`Cobranças__Project_Atualiza_Base_Acesso_Site_App_GCP`** depende de:
  - `Cobranças__Project_Atualiza_Base_Hash_BV` — via `CONTATOS.AUX_BASE_HASH`
- **`Cobranças__Project_Atualiza_Base_D0`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_SYNAPSE_MDM_TEL`
- **`Cobranças__Project_Atualiza_Base_Eventos_Whats`** depende de:
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_SYNAPSE_MDM_TEL`
- **`Cobranças__Project_Atualiza_Base_Hash_BV`** depende de:
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
- **`Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH`** depende de:
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Acesso_Site_App_GCP` — via `CONTATOS.AUX_HIST_ACESSO_APP`, `CONTATOS.AUX_HIST_ACESSO_SITE`
  - `Cobranças__Project_Atualiza_Base_Collection` — via `CONTATOS.AUX_BASE_COLLECTION`
  - `Cobranças__Project_Atualiza_Base_D0` — via `CONTATOS.AUX_BASE_CYBER_D0`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_QUARENTENA_TEL`
  - `Cobranças__Project_Atualiza_Base_Hash_BV` — via `CONTATOS.AUX_BASE_HASH`
  - `Cobranças__Project_Atualiza_Base_Pend_Gravame` — via `CONTATOS.AUX_GRAVAME_PEND`
  - `Cobranças__Project_Atualiza_Base_Propensao_Digital_Reapontamento_GCP` — via `CONTATOS.AUX_BASE_PROP_DIGITAL`
  - `Cobranças__Project_Atualiza_Base_SaidaDeRisco` — via `CONTATOS.AUX_SAIDADERISCO`
  - `Cobranças__Project_Atualiza_Feriados_Municipais` — via `TCONFIG.CONFIG_FERIADO_MUNICIPAL`
  - `Cobranças__Project_Atualiza_Lista_Restrita` — via `ZBLOQ.LISTA_RESTRITA_INTERNA`
  - `Cobranças__Project_Controle_Envios_HSM` — via `CONTATOS.AUX_HIST_INTERACAO_WHATS`
- **`Cobranças__Project_Base_Serasa_CL_V4`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_SYNAPSE_MDM_EMAIL`, `CONTATOS.AUX_SYNAPSE_MDM_TEL`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Bloqueio_RFlow_Manual` — via `ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`
- **`Cobranças__Project_Bloqueio_Acordos_Aut`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_SYNAPSE_MDM_TEL`
- **`Cobranças__Project_Bloqueio_RFlow_Manual`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ACOMPANHAMENTO_DESCONTO` — via `AUX_HIDP.AUX_OTIMIZACAO_TRILHA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_SYNAPSE_MDM_TEL`
- **`Cobranças__Project_Controle_Envios_HSM`** depende de:
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `RATINHO.RATINHO_UNIFICADO`
- **`Cobranças__Project_Jornada_e_Mailing_RENEG_EPS_ADIMP_INAD`** depende de:
  - `Cobranças__202508 - validacao torre negativacao` — via `CONTATOS.AUX_IQ_CARTEIRA`
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__Project_Atualiza_Base_Propensao_Digital_Reapontamento_GCP` — via `CONTATOS.AUX_BASE_PROP_DIGITAL`
  - `Cobranças__Project_Atualiza_Base_SaidaDeRisco` — via `CONTATOS.AUX_SAIDADERISCO`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_IQ_MODELO`, `CONTATOS.AUX_RENEG_SIMULACAO`
- **`Cobranças__Project_Mailing_Domu_v2`** depende de:
  - `Cobranças__202508 - validacao torre negativacao` — via `CONTATOS.AUX_IQ_CARTEIRA`
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_CYBER_INFO_VEIC`, `CONTATOS.AUX_LINHADIG_5A15`, `CONTATOS.AUX_SYNAPSE_MDM_TEL`, `RATINHO.RATINHO_UNIFICADO`, `ZBLOQ.LISTA_RESTRITA`
- **`Cobranças__Project_Trilha_Agradecimento_Acordo`** depende de:
  - `Cobranças__202508 - validacao torre negativacao` — via `CONTATOS.AUX_IQ_CARTEIRA`
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_SYNAPSE_MDM_TEL`, `RATINHO.RATINHO_UNIFICADO`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Atualiza_Lista_Restrita` — via `ZBLOQ.LISTA_RESTRITA_INTERNA`
- **`Cobranças__Project_Trilha_Isencao_Encargos`** depende de:
  - `Cobranças__202508 - validacao torre negativacao` — via `CONTATOS.AUX_IQ_CARTEIRA`
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_IQ_ACAO_CONTRA`, `RATINHO.RATINHO_UNIFICADO`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Atualiza_Lista_Restrita` — via `ZBLOQ.LISTA_RESTRITA_INTERNA`
- **`Cobranças__Project_Trilha_Preventivo_Digital_Alt_Teste_Controle`** depende de:
  - `Cobranças__202508 - validacao torre negativacao` — via `CONTATOS.AUX_IQ_CARTEIRA`
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_IQ_ACAO_CONTRA`, `RATINHO.RATINHO_UNIFICADO`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Atualiza_Lista_Restrita` — via `ZBLOQ.LISTA_RESTRITA_INTERNA`
- **`Cobranças__Project_Trilha_Quebra_Digital_Alt_Layot_Pontal`** depende de:
  - `Cobranças__202508 - validacao torre negativacao` — via `CONTATOS.AUX_IQ_CARTEIRA`
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_IQ_ACAO_CONTRA`, `RATINHO.RATINHO_UNIFICADO`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Atualiza_Lista_Restrita` — via `ZBLOQ.LISTA_RESTRITA_INTERNA`
- **`Cobranças__Project_Trilha_RENEG_Oferta_Emprestimos`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_EMAIL`, `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Base_Hash_BV` — via `CONTATOS.AUX_BASE_HASH`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_ELEGIBILIDADE_RENEG`, `CONTATOS.AUX_IQ_ACAO_CONTRA`, `RATINHO.RATINHO_UNIFICADO`, `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
  - `Cobranças__Project_Atualiza_Lista_Restrita` — via `ZBLOQ.LISTA_RESTRITA_INTERNA`
- **`Cobranças__Query_Excecoes_ContraProposta_20260116`** depende de:
  - `Cobranças__PROJETO BI CARTOES GERAL_V3` — via `SAFE_CAST`
- **`Cobranças__REVISIONAIS_V1`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Rastreador_v8_corr_tb_taylor_vf`** depende de:
  - `Riscos__AçΣes Alçadas Apuraç╞o v3` **[EXT]** — via `WORK`
- **`Cobranças__Remuneracao_CL_202601`** depende de:
  - `Cobranças__COLCHAO_ACORDO_CL__v2` **[EXT]** — via `PERF_CL.COLCHAO_CONSOLIDADO`
  - `Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU` — via `PERF_CL.CL_TABLEAU`
- **`Cobranças__Remuneracao_CL_202603`** depende de:
  - `Cobranças__COLCHAO_ACORDO_CL__v2` **[EXT]** — via `PERF_CL.COLCHAO_CONSOLIDADO`
  - `Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU` — via `PERF_CL.CL_TABLEAU`
- **`Cobranças__SERASAFEIRAO_V7GCP`** depende de:
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `ZBLOQ.LISTA_RESTRITA`, `ZBLOQ.LISTA_RESTRITA_EMAIL`
- **`Cobranças__Safra e Carteira Ajuizamento Reapontado`** depende de:
  - `Cobranças__Processo_Semanal_V2` — via `JOAO.SIMULACAO_AJUIZAMENTO_NEW`
- **`Cobranças__Saldo_repactuado_v2`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
- **`Cobranças__Simulação_Cenários_Proposta - Reapontado`** depende de:
  - `Cobranças__Painel_Desconto_Perf_Solar` **[EXT]** — via `KAUE.BASE_CYBER`
- **`Cobranças__base_carta_EVG_v4_saidarisco_v2`** depende de:
  - `Crédito__02. Classifica reg 3.1 - cdloja_Grupo` **[EXT]** — via `BASE03`
  - `Riscos__Apetite_Gerenciados_2025_v5__v2` **[EXT]** — via `BASE`
- **`Cobranças__base_carta_rodas_v4_saidarisco_v2`** depende de:
  - `Crédito__02. Classifica reg 3.1 - cdloja_Grupo` **[EXT]** — via `BASE03`
  - `Riscos__Apetite_Gerenciados_2025_v5__v2` **[EXT]** — via `BASE`
- **`Cobranças__gradativo_202506_CP_REAPONTADO`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`
  - `Cobranças__Valida_carga_v1_cp` **[EXT]** — via `GRIMALDI.CARGA_MASSIFICADOS_20260219`
  - `Cobranças__gradativo_202507_SOLAR_IDEAL_NTEC` — via `KAUE.BASE_ELEGIVEIS_KEVIN`
- **`Cobranças__gradativo_202507_SOLAR_IDEAL_NTEC`** depende de:
  - `Cobranças__Carteira_Envio_Protesto_Solar_GCP` — via `TALITA.HISTORICO_PROTESTO_SOLAR`
  - `Cobranças__processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` — via `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211`, `GRIMALDI.SOLAR_MASSIFICADOS_20250211`
- **`Cobranças__processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS`** depende de:
  - `Cobranças__Entrada_em_Cob_Geral_REAPONTADO_V2` **[EXT]** — via `LDUARTE.BAD_BANK`
- **`Cobranças__project_piloto_ia_google`** depende de:
  - `Cobranças__20250918_darkpost_v15` **[EXT]** — via `CONTATOS.COB_MDM_TELEFONE`
  - `Cobranças__ALIMENTAR DASH - NPSv10 - copia` — via `TCONFIG.CONFIG_TPENTRADA`
  - `Cobranças__Project_Atualiza_Base_Eventos_Whats` — via `CONTATOS.AUX_BASE_CYBER`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` — via `CONTATOS.AUX_CYBER_INFO_VEIC`
  - `Cobranças__Project_Bloqueio_RFlow_Manual` — via `ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`

### Finanças

- **`Finanças__GERA_BASE_GASTOS_GCP`** depende de:
  - `Atacado__Esteira 2` **[EXT]** — via `CONCAT`
  - `Riscos__1110 - Tributario Estrategico` — via `DATE`
- **`Finanças__RAC_CARTOES_2026`** depende de:
  - `Finanças__Fechamento_Cartoes_MIS_AUT` — via `CARTAOBV.TBL_CARTOES_DRE_TOTAL`

### Jurídico

- **`Jurídico__1351 - Estudo Revisionais_Cobranca(Dev)`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__SAS_IQ_SQ_Vigente__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQSQVIGENTE`
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQ`
- **`Jurídico__1430-Estudo_15022023`** depende de:
  - `Jurídico__1430-ProjetoSAS-TributarioIPVA_V16` — via `YBRTEMP.TBL1430TRIBUTARIOIPVA`
- **`Jurídico__1430-ProjetoSAS-TributarioIPVA_V16`** depende de:
  - `Riscos__Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` **[EXT]** — via `LT_NATUREZA`, `M_PROCESSO`
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLSACOBJGARANTIABEMVEICULO`
- **`Jurídico__1500 - Financeiro Sintetico`** depende de:
  - `Riscos__1003-Relatório Honorários Cível PBI - Consolidado` — via `YRIBEIRO.TBLPGTOHONORARIOLOTEHISTCAUSA`
  - `Riscos__1040-DBEP_Desdobramentos` **[EXT]** — via `DBEP.TBLDESDOBRAMENTOS`
  - `Riscos__1353-ProjetoSAS-Relevantes_Prognostico__v2` — via `DB1353.TBL1353CAUSAPROGNOSTICOOBJETO2`
  - `Riscos__DBEP_Causas` **[EXT]** — via `DBEP.TBLCAUSAPROJURIS`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`

### Negócios Transacionais Varejo e NaPista

- **`Negócios Transacionais Varejo e NaPista__COLCHAO_ACORDO_CL`** depende de:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4` — via `B_GERAL.DIAS_UTEIS`

### Operações

- **`Operações__Indicador Partes Relacionadas_V_1_5`** depende de:
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `TBPESSOA`

### Riscos

- **`Riscos__00_Extração_Base_GL_SYBASE IQ`** depende de:
  - `Atacado__Painel Sales Finance` — via `BASESGER.DMOPERACAOCREDITO`
- **`Riscos__1003-Relatório Honorários Cível PBI - Consolidado`** depende de:
  - `Riscos__DBEP_Acordo` **[EXT]** — via `DBEP.TBLPROCESSOACORDO`
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_ProcessoRequisicao` **[EXT]** — via `DBEP.TBLPROCESSOREQUISICAO`
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
- **`Riscos__1004-Relatório_Encerramento_PU`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
- **`Riscos__1015-Ranking Assessorias_Dev_v17`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
- **`Riscos__1023-inconsistencia`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Garantia` **[EXT]** — via `DBEP.TBLPROCESSOGARANTIA`
  - `Riscos__DBEP_Motivos` **[EXT]** — via `DBEP.TBLPROCESSOMOTIVO`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
  - `Riscos__DBEP_ProcessoRequisicao` **[EXT]** — via `DBEP.TBLPROCESSOREQUISICAO`
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
  - `Riscos__DBEP_Produto` **[EXT]** — via `DBEP.TBLPROCESSOPRODUTO`
  - `Riscos__DBEP_Requisicoes` **[EXT]** — via `DBEP.TBLCAUSAREQUISICAO`
- **`Riscos__1040-Base_Unica_2_TblCausaConsHist`** depende de:
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
- **`Riscos__1219- Base_Encerradas`** depende de:
  - `Riscos__Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` **[EXT]** — via `LT_NATUREZA`, `M_PROCESSO`
- **`Riscos__1271-Pre-Contestacao`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Assessorias` **[EXT]** — via `DBEP.TBLASSESSORIAS`
  - `Riscos__DBEP_Audiencia` **[EXT]** — via `DBEP.TBLPROCESSOAUDIENCIA`
- **`Riscos__1351 - Estudo Revisionais_Cobranca(Dev)`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__SAS_IQ_SQ_Vigente__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQSQVIGENTE`
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQ`
- **`Riscos__1351-SAS_v20201209_V2`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Partes` **[EXT]** — via `DBEP.TBLPROCESSOPARTE`
  - `Riscos__DBEP_Processos` **[EXT]** — via `DBEP.TBLPROCESSO`
  - `Riscos__SAS_IQ_SQ_Vigente__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQSQVIGENTE`
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQPFPROFISSAO`, `YRIBEIRO.TBLSACOBJGARANTIABEMVEICULO`
- **`Riscos__1353-ProjetoSAS-Relevantes_Prognostico__v2`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Causas` **[EXT]** — via `DBEP.TBLCAUSAPROJURIS`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
  - `Riscos__DBEP_Partes` **[EXT]** — via `DBEP.TBLPROCESSOPARTE`
  - `Riscos__DBEP_ProcessoObjetoPrognostico` **[EXT]** — via `DBEP.TBLPROCESSOOBJETOPROGNOSTICO`
  - `Riscos__DBEP_Processos` **[EXT]** — via `DBEP.TBLPROCESSO`
  - `Riscos__DBEP_ProvisaoJuridica` **[EXT]** — via `DBEP.TBLPROCESSOPROVISAOJURIDICA`
  - `Riscos__DBEP_Reclassificacoes` **[EXT]** — via `DBEP.TBLRECLASSIFICACOES`
- **`Riscos__1389-Project -v2`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
- **`Riscos__1403-Base Unica Trabalhista_V2`** depende de:
  - `Riscos__Calculo Provisão Trabalhista 2025 Prov AE - v01 - Cloud` **[EXT]** — via `LT_NATUREZA`, `M_PROCESSO`
  - `Riscos__DBEP_Assessorias` **[EXT]** — via `DBEP.TBLASSESSORIAS`
- **`Riscos__1457 - Garantias Judiciais`** depende de:
  - `Riscos__1040-DBEP_Desdobramentos` **[EXT]** — via `DBEP.TBLDESDOBRAMENTOS`
  - `Riscos__1040-DBEP_LiberacaoGarantia` **[EXT]** — via `DBEP.TBLPROCESSOLIBERACAOGARANTIA`
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Garantia` **[EXT]** — via `DBEP.TBLPROCESSOGARANTIA`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
  - `Riscos__DBEP_ProcessoRequisicaoAtributo` **[EXT]** — via `DBEP.TBLPROCESSOREQUISICAOATRIBUTO`
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
  - `Riscos__DBEP_Requisicoes` **[EXT]** — via `DBEP.TBLCAUSAREQUISICAO`
- **`Riscos__1462 - Criminal Acompanhamento diario de oficios`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Partes` **[EXT]** — via `DBEP.TBLPROCESSOPARTE`
- **`Riscos__1465-BO_Lavratura_Windows`** depende de:
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQ`
- **`Riscos__1482-Contingencias Civeis`** depende de:
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQ`
- **`Riscos__1482-EstoqueRo_ContingenciasCiveisContrato`** depende de:
  - `Riscos__ATUALIZACAO_PROJURIS V10` **[EXT]** — via `BDPO.BDPORTAL_CONSOLIDADA`, `BDPO.BDPORTAL_PROVISAO`
  - `Riscos__Análise de Variaç╞o v8` **[EXT]** — via `PROVAR.NOVASACOES`
  - `Riscos__Atualizaç╞o BD Cíveis Massificadas V11 Projuris` **[EXT]** — via `BDCIVEL.MASSIFICADO`
  - `Riscos__INAC Tableau v2__v2` **[EXT]** — via `MODELO.SUMARIO_2010_ANALITICO`
- **`Riscos__1499 - Monitoramento - consistencias de cadastros`** depende de:
  - `Riscos__1023-inconsistencia__v2` **[EXT]** — via `DBRPTTBL.TBL1023CADASTROINCONSISTENCIA`, `DBRPTTBL.TBL1023INCONSISTENCIA`, `DBRPTTBL.TBL1023TBLCAUSAREGRA`, `DBRPTTBL.TBL1499TBLCAUSAREGRA`
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_ProcessoRequisicao` **[EXT]** — via `DBEP.TBLPROCESSOREQUISICAO`
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
- **`Riscos__1499-Email20220721_Novo`** depende de:
  - `Riscos__1023-inconsistencia__v2` **[EXT]** — via `DBRPTTBL.TBL1023CADASTROINCONSISTENCIA`, `DBRPTTBL.TBL1023TBLCAUSAREGRA`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
  - `Riscos__DBEP_ProcessoRequisicao` **[EXT]** — via `DBEP.TBLPROCESSOREQUISICAO`
  - `Riscos__DBEP_ProcessoRequisicaoAtributo` **[EXT]** — via `DBEP.TBLPROCESSOREQUISICAOATRIBUTO`
  - `Riscos__DBEP_Processos` **[EXT]** — via `DBEP.TBLPROCESSO`
  - `Riscos__SAS_IQ_SQ_Vigente__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQSQVIGENTE`
- **`Riscos__1500 – Andamento`** depende de:
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
- **`Riscos__1500-Base Unica Civel - Visao Advogados`** depende de:
  - `Riscos__1040-DBEP_Desdobramentos` **[EXT]** — via `DBEP.TBLDESDOBRAMENTOS`
  - `Riscos__DBEP_Andamentos` **[EXT]** — via `DBEP.TBLPROCESSOANDAMENTO`
  - `Riscos__DBEP_Pagamento` **[EXT]** — via `DBEP.TBLPAGAMENTOS`
  - `Riscos__DBEP_ProcessosReabertura` **[EXT]** — via `DBEP.TBLPROCESSOREABERTURA`
  - `Riscos__DBEP_UsuarioEncerramento` **[EXT]** — via `DBEP.TBLUSUARIOENCERRAMENTO`
  - `Riscos__SAS_IQ_SQ_Vigente__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQSQVIGENTE`
  - `Riscos__SAS_IQ_V001__v2` **[EXT]** — via `YRIBEIRO.TBLCONTRATOSIQ`, `YRIBEIRO.TBLSACOBJGARANTIABEMVEICULO`
- **`Riscos__Apetite_2025`** depende de:
  - `Riscos__Tableau_2025.v2` **[EXT]** — via `TABLEAU.BASE_ATIVOS_202509`
- **`Riscos__Apetite_Gerenciados_2025_v5`** depende de:
  - `Riscos__Base_Unica_202509` **[EXT]** — via `CARTEIRA.DE_PARA_GERAL_SIC`, `MISCRED.BASE_CLIENTES`, `MISCRED.EXTRACAO_RPDD_HIST`
  - `Riscos__MONITORAMENTO_CONSOLIDADO_UNDERWRITTING` **[EXT]** — via `SALVA.HISTORICO`, `SALVA.RESUMO_MENSAL`
- **`Riscos__Atualização PBI Grupos`** depende de:
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `INSIGHT.TBBRUTA`
- **`Riscos__Controle_PMES_v19`** depende de:
  - `Atacado__Base_Bruta` **[EXT]** — via `PLCA.TBSISTEMAPLCA`
  - `Atacado__Base_Carteira_Consolidada` — via `INSIGHT.TBBRUTA_20260331`
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `INSIGHT.TBBRUTA`
  - `Atacado__[Gestão_de_Carteira] Motores` **[EXT]** — via `GCSERASA.TBGCDADOSCADASTRAIS`, `PME.BASE_HISTORICA_PMUM_SF`
  - `Crédito__CIB` **[EXT]** — via `SHAREATA.TBCARTEIRAGRUPO`
  - `Riscos__Indicadores_PMEs_PPT_V3` **[EXT]** — via `MONITRCA.NE_DESEMBOLSOS`
- **`Riscos__Histórico Carteira_V3`** depende de:
  - `Atacado__Base_Sinais_v5` **[EXT]** — via `INSIGHT.TBBRUTA`
- **`Riscos__INAC Tableau v2`** depende de:
  - `Riscos__ATUALIZACAO_PROJURIS V10` **[EXT]** — via `BDPO.BDPORTAL_CONSOLIDADA`, `BDPORTAL.CONTRATOS_PROJURIS`
  - `Riscos__Atualizaç╞o BD Cíveis Massificadas V11 Projuris` **[EXT]** — via `BDCIVEL.MASSIFICADO`
- **`Riscos__Tb_bals`** depende de:
  - `Crédito__Base_Bruta_GL` **[EXT]** — via `INSIGHT.TBBALS`

### Seguros

- **`Seguros__FECHAMENTO_CARDIF_ICATU`** depende de:
  - `Negócios e Produtos Relacional e Seguros__BaseUnica` **[EXT]** — via `BASES.TBPRODUCAO`

## 3. EGPs Indicium autônomos (99)

Não dependem de nenhum outro EGP — apenas de tabelas de banco/ingestão externa
(ver report `01_prioridade_ingestao.csv` para essas fontes).

- `Atacado__Exporta BALS`
- `Atacado__GeraBaseOperacoesPLRC`
- `Cartões__Processo de bonificação - taxas_v35 (2)`
- `Cobranças__10.PARCELA_PULADA`
- `Cobranças__1PMTv4`
- `Cobranças__2. ESTUDO_CUSTAS_TOTAL`
- `Cobranças__202508 - validacao torre negativacao`
- `Cobranças__3.ESTUDO_ISENC_CUSTAS_TOTAL`
- `Cobranças__6.APURACAO_NOTIFIC`
- `Cobranças__8.2 VEIC_ALTO_VLR_V3`
- `Cobranças__ANALISE_ELEGIVEIS_v2`
- `Cobranças__ATUALIZACAO BASE PROJURIS`
- `Cobranças__Analise_mix_vulneraveis`
- `Cobranças__Apuracao_Performance_safrada_v3`
- `Cobranças__Apuracao_recorrente_GCP`
- `Cobranças__Atualiza_UF_Cartoes`
- `Cobranças__Avaliacao_divergencias_v5 - Reapontado`
- `Cobranças__CPF_Contrato`
- `Cobranças__Campanha_Entrega_amigavel_v4_mensal_gcp`
- `Cobranças__CobrancaAcima120dias_v15_GCP`
- `Cobranças__Construcao_carteira_Risco`
- `Cobranças__Consulta_Carteira_New_Automatizada`
- `Cobranças__Código Elegibilidade Abaixo de 120D`
- `Cobranças__Desconto_Carteira_RPA`
- `Cobranças__Diagnostico_divergencias_encargos20250904`
- `Cobranças__Distribuidor_PF`
- `Cobranças__Elegibilidade WO - GCP`
- `Cobranças__Elegibilidade menor que 90_GCP_v4`
- `Cobranças__Elegibilidade_Reneg_CP`
- `Cobranças__Empilhamento Acionamento`
- `Cobranças__Entrada_em_Cob_Intra`
- `Cobranças__Entrada_em_Cob_intrames`
- `Cobranças__Estrategia_Reneg_Solar_180_v20250305_GCP`
- `Cobranças__GESTAO_BNDU`
- `Cobranças__Geracao_carteira_91_120d`
- `Cobranças__MIS_IQ_v2_NEW`
- `Cobranças__Migracao_Potencial v3`
- `Cobranças__Notificações - GCP`
- `Cobranças__Oportunidade Protesto - Piloto de Ajuizamento_GCP`
- `Cobranças__PROCESSO ENRIQUECIMENTO PRODUTO`
- `Cobranças__PROCESSO ENRIQUECIMENTO REVISIONAL`
- `Cobranças__PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente`
- `Cobranças__PROJECT_PJ_PRIVADO_DISTRIBUIDOR_RPA`
- `Cobranças__PROJECT_REMUNERA_CP`
- `Cobranças__PROJECT_ROLAGEM_NEW`
- `Cobranças__PROJETO CPC CARTOES`
- `Cobranças__PROJETO_CARBGDATA`
- `Cobranças__Performance Safrada Fase Ativa - Agente IA`
- `Cobranças__Performance_Solar_RPA`
- `Cobranças__Processo_Semanal_V2`
- `Cobranças__Programa_verificacao`
- `Cobranças__Project_Aderencia_+10`
- `Cobranças__Project_Analise_Over90`
- `Cobranças__Project_Atualiza_Base_Collection`
- `Cobranças__Project_Atualiza_Base_Pend_Gravame`
- `Cobranças__Project_Atualiza_Base_Propensao_Digital_Reapontamento_GCP`
- `Cobranças__Project_Atualiza_Base_Propensao_Digital_Reapontamento_Kraken`
- `Cobranças__Project_Atualiza_Base_SaidaDeRisco`
- `Cobranças__Project_Atualiza_Feriados_Municipais`
- `Cobranças__Project_Atualiza_Lista_Restrita`
- `Cobranças__Project_Compensacao_Encargos_v1`
- `Cobranças__Project_Performance_ADM_BOM_PAGADOR`
- `Cobranças__Project_Reneg_WO_NEW`
- `Cobranças__Project_Rolagem v10`
- `Cobranças__Project_Share_Digital_GCP_v4`
- `Cobranças__Projeto-Atualiza-Base_Orgao`
- `Cobranças__Projeto_Revisionais_Set25_V2`
- `Cobranças__Projeção_Rolagem_Mai26`
- `Cobranças__QUERY_LINHA_DIGITAVEL_CA_v2`
- `Cobranças__Regularizacao_Mensal_EDU_GCP`
- `Cobranças__Reneg_Over30e90_Ever30_v2`
- `Cobranças__Reneg_Remunera`
- `Cobranças__Reneg_Remunerav3`
- `Cobranças__SELECAO_DETERIORADOS - Reapontado`
- `Cobranças__SELECAO_RECORRENTE_GCP`
- `Cobranças__Safra Ajuizamento_v3`
- `Cobranças__VALIDACAO_CYBER_VOLUMETRIA_ATUALIZADA_v3 - Reapontado`
- `Cobranças__Valida_recebimentos_nov24`
- `Cobranças__Valida_score_v2`
- `Cobranças__Validacao_subida_encargos_20260302`
- `Cobranças__Validacao_subida_score16`
- `Cobranças__ativa`
- `Cobranças__manut_acordo`
- `Cobranças__tipos_acordo`
- `Finanças__Carteira_Final_Semana_edit_joao`
- `Finanças__Fechamento_Cartoes_MIS_AUT`
- `Finanças__KPIs - Carteira Accrual e Não Accrual 1`
- `Finanças__Sinergias_v2 1`
- `Jurídico__SAS_IQ_V001`
- `Riscos__1047-20170814174201_V2`
- `Riscos__1100-BaseAcoesContrarias`
- `Riscos__1110 - Tributario Estrategico`
- `Riscos__1351-VINCULACAO DAS ASSESSORIAS DE BUSCA`
- `Riscos__1374 - Boletim Cível`
- `Riscos__1449-Acoes Judiciais Baas`
- `Riscos__SAS_IQ_SQ_Vigente`
- `Riscos__SIC-Fluxo_Posicao`
- `Riscos__atualizacao_graficos_matriz_pme`
- `Riscos__atualizacao_graficos_matriz_v2`

## Ressalvas

- `Cobranças__Consulta_Carteira_New_Automatizada` foi ingerido em 2026-06-11 **depois** da roda do
  orchestrator — aparece como autônomo aqui; reconferir na próxima roda da matriz 03.
- `ca_apagar_periodo` (Cobrança Varejo) segue **sem .egp recebido** — fora desta análise.
- A matriz 03 liga EGPs por tabela produzida×consumida com chave canônica; falsos positivos do
  extrator e EGPs duplicados entre áreas podem inflar arestas (ver §2.H do STATUS_MIGRACAO_SAS.md).
