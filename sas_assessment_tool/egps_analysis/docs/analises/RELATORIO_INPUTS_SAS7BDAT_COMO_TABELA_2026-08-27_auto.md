# Inputs `.sas7bdat` classificados como arquivo — na verdade tabelas SAS

Fonte: **prod** `bv_dev_db.monitoramento_sas` (read-only) · 2026-08-27

## Causa raiz

`orchestrator_inventory.py:1268` — a árvore de decisão de modernização (Chameleon → RepMap → Inventário → override) roda só para `cat in ('table_in','table_out')`. Um `file_in` `.sas7bdat` nunca entra: `modernizada_auto` fica `'A ingerir'` mesmo com a tabela já no BigQuery.

`publish_to_databricks.py:366` — o dedup `.sas7bdat` ↔ `lib.membro` só colapsa DENTRO do mesmo projeto; arquivo no EGP A + tabela no EGP B viram duas chaves para o mesmo dataset.

## Números

| recorte | n |
|---|---|
| `.sas7bdat` como `arquivo` | 280 |
| pendentes (não modernizados) | 276 |
| pendentes no escopo Indicium | 35 |

## Buckets

| bucket | total | pendentes | no escopo | ação |
|---|---:|---:|---:|---|
| 0. já resolvido | 4 | 0 | 0 | nenhuma (já modernizado/sanitizado) |
| A. modernizada invisível | 4 | 4 | 0 | reclassificar p/ tabela → vira Disponível (BV-PDBD-PRD.TRUSTED_CLIE_MKT.TBPRODUCAO); ou Sanitizar |
| B. gêmeo tabela já resolvido | 5 | 5 | 0 | Sanitizar o arquivo (mesma tabela já resolvida como 'tabela') |
| C. gêmeo tabela pendente | 122 | 122 | 1 | desduplicar: Sanitizar o arquivo, manter a linha 'tabela' |
| D. produzida no corpus | 12 | 12 | 1 | é dependência intra-corpus (EGP→EGP), não arquivo externo |
| F. tabela SAS externa | 133 | 133 | 33 | reclassificar p/ tabela SAS e entrar na esteira de ingestão |

## Amostra (pendentes, por nº de EGPs)

| artifact | membro | EGPs | escopo | bucket | gêmeo tabela |
|---|---|---:|:-:|---|---|
| `depara_assessoria.sas7bdat` | DEPARA_ASSESSORIA | 7 | ✓ | C. gêmeo tabela pendente | SATIE.DEPARA_ASSESSORIA |
| `politica_acordo_gh16_20241227.sas7bdat` | POLITICA_ACORDO_GH16_20241227 | 7 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20241227 |
| `politica_acordo_gh16_20250228.sas7bdat` | POLITICA_ACORDO_GH16_20250228 | 7 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250228 |
| `politica_acordo_gh16_20250328.sas7bdat` | POLITICA_ACORDO_GH16_20250328 | 7 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250328 |
| `politica_acordo_gh16_20250530.sas7bdat` | POLITICA_ACORDO_GH16_20250530 | 7 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250530 |
| `politica_acordo_gh16_20250627.sas7bdat` | POLITICA_ACORDO_GH16_20250627 | 7 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250627 |
| `politica_acordo_gh16_20250725.sas7bdat` | POLITICA_ACORDO_GH16_20250725 | 7 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250725 |
| `politica_acordo_gh16_20250103.sas7bdat` | POLITICA_ACORDO_GH16_20250103 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250103 |
| `politica_acordo_gh16_20250110.sas7bdat` | POLITICA_ACORDO_GH16_20250110 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250110 |
| `politica_acordo_gh16_20250117.sas7bdat` | POLITICA_ACORDO_GH16_20250117 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250117 |
| `politica_acordo_gh16_20250124.sas7bdat` | POLITICA_ACORDO_GH16_20250124 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250124 |
| `politica_acordo_gh16_20250207.sas7bdat` | POLITICA_ACORDO_GH16_20250207 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250207 |
| `politica_acordo_gh16_20250214.sas7bdat` | POLITICA_ACORDO_GH16_20250214 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250214 |
| `politica_acordo_gh16_20250221.sas7bdat` | POLITICA_ACORDO_GH16_20250221 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250221 |
| `politica_acordo_gh16_20250321.sas7bdat` | POLITICA_ACORDO_GH16_20250321 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250321 |
| `politica_acordo_gh16_20250404.sas7bdat` | POLITICA_ACORDO_GH16_20250404 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250404 |
| `politica_acordo_gh16_20250411.sas7bdat` | POLITICA_ACORDO_GH16_20250411 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250411 |
| `politica_acordo_gh16_20250417.sas7bdat` | POLITICA_ACORDO_GH16_20250417 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250417 |
| `politica_acordo_gh16_20250509.sas7bdat` | POLITICA_ACORDO_GH16_20250509 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250509 |
| `politica_acordo_gh16_20250523.sas7bdat` | POLITICA_ACORDO_GH16_20250523 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250523 |
| `politica_acordo_gh16_20250606.sas7bdat` | POLITICA_ACORDO_GH16_20250606 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250606 |
| `politica_acordo_gh16_20250613.sas7bdat` | POLITICA_ACORDO_GH16_20250613 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250613 |
| `politica_acordo_gh16_20250620.sas7bdat` | POLITICA_ACORDO_GH16_20250620 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250620 |
| `politica_acordo_gh16_20250704.sas7bdat` | POLITICA_ACORDO_GH16_20250704 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250704 |
| `politica_acordo_gh16_20250712.sas7bdat` | POLITICA_ACORDO_GH16_20250712 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250712 |
| `politica_acordo_gh16_20250718.sas7bdat` | POLITICA_ACORDO_GH16_20250718 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250718 |
| `politica_acordo_gh16_20250801.sas7bdat` | POLITICA_ACORDO_GH16_20250801 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250801 |
| `politica_acordo_gh16_20250808.sas7bdat` | POLITICA_ACORDO_GH16_20250808 | 6 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250808 |
| `tbsimulacoes.sas7bdat` | TBSIMULACOES | 5 |  | A. modernizada invisível | CONVSIMU.TBSIMULACOES | INFCVS.TBSIMULACOES | MIS2.TBSIMULACOES |
| `carteira_ca.sas7bdat` | CARTEIRA_CA | 5 |  | C. gêmeo tabela pendente | CARNEIRO.CARTEIRA_CA |
| `politica_acordo_gh16_20241129.sas7bdat` | POLITICA_ACORDO_GH16_20241129 | 5 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20241129 |
| `politica_acordo_gh16_20250829.sas7bdat` | POLITICA_ACORDO_GH16_20250829 | 5 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250829 |
| `politica_acordo_gh16_20250926.sas7bdat` | POLITICA_ACORDO_GH16_20250926 | 5 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20250926 |
| `politica_acordo_gh16_20260130.sas7bdat` | POLITICA_ACORDO_GH16_20260130 | 5 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20260130 |
| `&amp;arquivo..sas7bdat` | &AMP;ARQUIVO. | 5 | ✓ | F. tabela SAS externa | — |
| `politica_acordo_gh16_20240927.sas7bdat` | POLITICA_ACORDO_GH16_20240927 | 4 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20240927 |
| `politica_acordo_gh16_20241004.sas7bdat` | POLITICA_ACORDO_GH16_20241004 | 4 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20241004 |
| `politica_acordo_gh16_20241011.sas7bdat` | POLITICA_ACORDO_GH16_20241011 | 4 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20241011 |
| `politica_acordo_gh16_20241018.sas7bdat` | POLITICA_ACORDO_GH16_20241018 | 4 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20241018 |
| `politica_acordo_gh16_20241025.sas7bdat` | POLITICA_ACORDO_GH16_20241025 | 4 |  | C. gêmeo tabela pendente | GH16.POLITICA_ACORDO_GH16_20241025 |

Detalhe completo: `BV_Migracao_SAS_Inputs_sas7bdat_como_Tabela_2026-08-27.csv`
