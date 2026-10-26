<!-- Colar após o título `# AUDITORIA — {{egp_key}}` e preencher placeholders. -->

## Metadados de execução

- **modo_lote:** não <!-- ou: sim -->
- **ficheiro_lote:** <!-- obrigatório se modo_lote = sim; ex.: registry/egp_keys_batch.txt -->
- **data_utc_auditoria:** {{data_utc}} <!-- opcional; ISO 8601 -->
- **notas_lote:** <!-- opcional -->

## Pontos de alto risco (revisão humana)

| Tema | Estado | Notas |
|------|--------|--------|
| Filtros / `WHERE` e impacto em volume de linhas vs SAS | Pendente | |
| Chaves, joins e cardinalidade (PK/FK, duplicações) | Pendente | |
| `PROC EXPORT` / marts de exportação vs SAS | Pendente | |
| `PERMANENT OUTPUTS` / libref permanente vs `models/marts/` | Pendente | |
| PII / `registry/sensitive_data_types.yaml` vs YAML e `fl_contem_pii` | Pendente | |
| Tabelas de negócio / `ref`+`source` vs fluxo SAS | Pendente | |
| Amostragem ou validação no motor alvo (ex. BigQuery) | N/A | |

<!-- Estado: Revisado | Pendente | N/A. Se alguma linha ficar Pendente, o Resumo não pode ser OK em todas as áreas. -->
