# Relatório de Métricas — Migração SAS

> Gerado em **2026-06-12** por `build_metrics_report.py` a partir de `06_prontidao_tabela.csv` (pipeline) + `indi_231_vs_extracao_06.csv` (escopo Indicium).

Tabelas únicas = nome normalizado (maiúsculas), excluindo ruído (`WORK.*`, `DICTIONARY.*`, placeholders de macro). “Modernizada” = `status_validacao` indica presença no BigQuery.

## A) Base completa (todos os projetos extraídos)

Tudo que está em `received_egps/` — EGPs de todas as áreas + jobs SAS de produção (UC4). A extração cobre **1.224** projetos; **19** não têm nenhum I/O detectado (projetos vazios/só visualização — candidatos a auditoria) e ficam fora das métricas.

| Métrica | Valor |
|---|---:|
| **Projetos únicos (EGP/SAS)** | **1.205** |
| &nbsp;&nbsp;— extensão `.egp` | 847 |
| &nbsp;&nbsp;— extensão `.sas` | 358 |
| **Inputs de entrada distintos** (`table_in`+`file_in`+`script_in`) | **11.526** |
| &nbsp;&nbsp;— **a ingerir / modernizar (total de inputs)** | **10.517** |
| &nbsp;&nbsp;— já disponíveis (BigQuery) | 1.009 |
| &nbsp;&nbsp;*detalhe por categoria (distintos → a ingerir):* | |
| &nbsp;&nbsp;&nbsp;&nbsp;tabelas (`table_in`) | 7.361 → **6.352** |
| &nbsp;&nbsp;&nbsp;&nbsp;arquivos (`file_in`) | 3.790 → 3.790 |
| &nbsp;&nbsp;&nbsp;&nbsp;scripts (`script_in`) | 375 → 375 |
| &nbsp;&nbsp;tabelas compartilhadas (≥2 projetos) | 2.529 |
| **Tabelas de SAÍDA únicas** (outputs) | **20.465** |
| Tabelas intermediárias (saída de um, entrada de outro) | 2.099 |
| Arquivos de saída únicos (file_out) | 1.503 |
| Libnames detectados (in / out) — *contexto, não contam como input* | 443 / 508 |
| Ruído excluído (WORK/macro/metadado) | 8.390 |
| % de inputs já modernizados | 8.8% |

**Projetos e inputs únicos por área:**

| Área | Projetos | Inputs únicos (tabelas) |
|---|---:|---:|
| Cobranças | 325 | 2.496 |
| SAS_UC4 | 223 | 742 |
| Riscos | 219 | 1.718 |
| Rodas | 134 | 638 |
| Finanças | 61 | 742 |
| Pricing | 53 | 116 |
| Crédito | 51 | 665 |
| Atacado | 30 | 316 |
| Planejamento e P&L (Rodas) | 27 | 34 |
| Negócios Transacionais Varejo e NaPista | 18 | 83 |
| Jurídico | 16 | 139 |
| Operações | 15 | 55 |
| TI | 10 | 2 |
| Negócios e Produtos Relacional e Seguros | 6 | 94 |
| Solar | 6 | 353 |
| Seguros | 5 | 48 |
| Auditoria | 4 | 28 |
| Cartões | 1 | 5 |
| Negócios Relacional | 1 | 73 |

**Top 10 inputs por nº de projetos consumidores:**

| Tabela | Projetos | Modernizada? |
|---|---:|---|
| `BV-PDBD-PRD.DVRY_CORE.TBCONTRATO` | 112 | Sim |
| `BV-PDBD-PRD.TRUSTED_GESTAOCONTABIL.TBCONTRATOCONTABIL` | 108 | Sim |
| `BV-PDBD-PRD.DVRY_CORE.TBPARCELA` | 90 | Sim |
| `BV-PDBD-PRD.TRUSTED_DBCRED.TBPROPOSTA` | 90 | Sim |
| `DBA.TBPROPOSTA` | 90 | Não |
| `DBA.VWTBCONTRATO` | 74 | Sim |
| `B_GERAL.DIAS_UTEIS` | 64 | Não |
| `TMP.TBPRODUCAO` | 63 | Não |
| `BV-PDBD-PRD.TRUSTED_DBCRED.TBSUBPRODUTOGRUPO` | 62 | Sim |
| `BASES.TBPRODUCAO` | 61 | Não |

## B) Escopo Indicium — 231 priorizados para a consultoria

Subconjunto casado com a extração: **229** projetos (2 EGPs ainda não recebidos; demais divergências de nome documentadas em `indi_231_vs_extracao_06.csv`).

| Métrica | Valor |
|---|---:|
| **Projetos únicos (EGP/SAS)** | **229** |
| &nbsp;&nbsp;— extensão `.egp` | 229 |
| **Inputs de entrada distintos** (`table_in`+`file_in`+`script_in`) | **3.356** |
| &nbsp;&nbsp;— **a ingerir / modernizar (total de inputs)** | **2.924** |
| &nbsp;&nbsp;— já disponíveis (BigQuery) | 432 |
| &nbsp;&nbsp;*detalhe por categoria (distintos → a ingerir):* | |
| &nbsp;&nbsp;&nbsp;&nbsp;tabelas (`table_in`) | 2.502 → **2.070** |
| &nbsp;&nbsp;&nbsp;&nbsp;arquivos (`file_in`) | 852 → 852 |
| &nbsp;&nbsp;&nbsp;&nbsp;scripts (`script_in`) | 2 → 2 |
| &nbsp;&nbsp;tabelas compartilhadas (≥2 projetos) | 637 |
| **Tabelas de SAÍDA únicas** (outputs) | **5.157** |
| Tabelas intermediárias (saída de um, entrada de outro) | 480 |
| Arquivos de saída únicos (file_out) | 613 |
| Libnames detectados (in / out) — *contexto, não contam como input* | 160 / 186 |
| Ruído excluído (WORK/macro/metadado) | 2.342 |
| % de inputs já modernizados | 12.9% |

**Projetos e inputs únicos por área:**

| Área | Projetos | Inputs únicos (tabelas) |
|---|---:|---:|
| Cobranças | 167 | 1.865 |
| Riscos | 39 | 447 |
| Atacado | 8 | 141 |
| Finanças | 6 | 83 |
| Jurídico | 5 | 84 |
| Cartões | 1 | 5 |
| Negócios Transacionais Varejo e NaPista | 1 | 11 |
| Operações | 1 | 11 |
| Seguros | 1 | 1 |

**Top 10 inputs por nº de projetos consumidores:**

| Tabela | Projetos | Modernizada? |
|---|---:|---|
| `BV-PDBD-PRD.TRUSTED_GESTAOCONTABIL.TBCONTRATOCONTABIL` | 63 | Sim |
| `BV-PDBD-PRD.DVRY_CORE.TBCONTRATO` | 62 | Sim |
| `BV-PDBD-PRD.TRUSTED_DBCRED.TBPROPOSTA` | 51 | Sim |
| `BV-PDBD-PRD.DVRY_CORE.TBPARCELA` | 47 | Sim |
| `BV-PDBD-PRD.TRUSTED_DBCRED.TBSUBPRODUTOGRUPO` | 39 | Sim |
| `BV-PDBD-PRD.TRUSTED_DBCRED.TBGRUPOSUBPRODUTO` | 36 | Sim |
| `BV-PDBD-PRD.TRUSTED_SCC_FIN.SAJ_PROCESSO` | 35 | Sim |
| `DBA.VWTBCONTRATO` | 34 | Sim |
| `BV-PDBD-PRD.TRUSTED_SCC_FIN.SAJ_AGENTE` | 30 | Sim |
| `BV-PDBD-PRD.TRUSTED_DBCOBRANCA.TBSCORECOBRANCA` | 29 | Sim |
