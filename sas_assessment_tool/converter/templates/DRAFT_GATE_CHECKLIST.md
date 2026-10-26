# Checklist semântica — Gate pós-draft (agente)

Execute **depois** de `python draft_gate.py "<egp_key>"` (e de ler `DRAFT_GATE_REPORT.md` se existir).

O script cobre apenas regras **mecânicas**. Marque cada item com base no **conteúdo SAS** (`text_egps/*.txt`) e no **draft**.

## Paridade de filtros

- [ ] Cada condição em **FILTERS_ORIGINAIS** (ou WHERE crítico identificado) tem equivalente explícito no modelo que lê a fonte (staging/intermediate).
- [ ] Não há “simplificação” que altere cardinalidade (ex.: remover `AND` do filtro na tabela base).

## Tabelas e fontes (interpretação)

- [ ] Para cada aviso *“tabela possivelmente não refletida”* do `draft_gate.py`: confirmar se o nome BQ/libref no extrator corresponde a um `ref`/`source` com **nome diferente** (falso positivo) ou se falta modelo.
- [ ] Pass-through / `CONNECT TO`: tratado ou documentado (TODO) conforme `MIGRATION_SPEC.md`.

## Staging reutilizado

- [ ] Em `reuse_existing` / `hybrid`: além dos `ref('stg_*')` exigidos pelo `staging_ref_map`, não há **staging duplicado** desnecessário para a mesma fonte já mapeada.

## Arquitetura

- [ ] `TARGET_ARCH` efetivo no spec / catálogo alinha com a stack usada no draft (SQL vs PySpark).

## Cobertura de modelos (`draft_manifest`)

- [ ] Se **`MIGRATION_SPEC.md` §9** tem `draft_manifest.models` **não vazio**: cada entrada (`layer`, `stem`) tem ficheiro correspondente em `draft_models/.../models/<layer>/<stem>.sql` ou `.py` (o `draft_gate` já valida isto mecanicamente).
- [ ] Se `models` está **vazio** ou omitido: confirmar conscientemente (ou preencher a lista) que nenhum modelo SAS relevante ficou de fora — alinhar a **`PERMANENT OUTPUTS (Target Marts)`** / `PROC EXPORT` do `.txt`, a **escritas em libref de biblioteca permanente** (≠ `WORK`, ex.: `data ADAMOR....`) visíveis no SAS, e à secção **5** do spec — critérios de mart em **`01_sas_to_dbt.mdc` §2.1–2.2**.
- [ ] Cada deliverable desses tipos (`PROC EXPORT`, persistência em libref permanente, alvo em **`PERMANENT OUTPUTS`**) tem **mart** correspondente em `draft_models/.../models/marts/` (ou exceção explícita no `MIGRATION_SPEC` §5).

## PII nos YAML (pós-governança / DBT_BQ)

- [ ] Nos `stem.yml` de **intermediate** e **marts** (já na pasta convertida), cada coluna cujo nome casa com `registry/sensitive_data_types.yaml` tem `policy_tags` coerente com o repositório alvo (o `draft_gate` / `batch_pipeline checks --strict` já cobrem isto mecanicamente quando aplicável).

## Próximo passo

Se todos os itens críticos estão OK (e erros mecânicos resolvidos), prosseguir para **governança** (Agente 2).
