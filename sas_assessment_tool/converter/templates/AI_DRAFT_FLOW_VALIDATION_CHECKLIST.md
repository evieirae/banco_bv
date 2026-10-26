# Checklist — validação IA do draft **flow-only**

Use este checklist **antes** de declarar o draft concluído. O gate `draft_flow_gate` exige o artefacto
`draft_models/<egp_key>/AI_DRAFT_FLOW_VALIDATION_REPORT.md` com **100% PASS**.

## Regras de layout (obrigatório)

- [ ] Existem ficheiros `draft_models/<egp>/models/NN_*.sql` (≥1) na **raiz** de `models/`
- [ ] **Não** existem pastas `models/staging/`, `models/intermediate/`, `models/marts/`, `models/steps/`
- [ ] Cadeia `ref()` faz sentido (cada `ref('…')` aponta para um modelo existente no draft)

## Fidelidade (amostragem orientada)

- [ ] `MIGRATION_SPEC.md` foi lido e o código não contradiz `TARGET_ARCH`, `staging_mode`, `PROJECT`, `cd_governanca`
- [ ] Se existir `FILTERS_ORIGINAIS` no `.txt`, cada filtro foi reproduzido no modelo certo (não “sumiu no join”)
- [ ] Passthrough (`FROM CONNECTION TO` / `EXECUTE`) foi traduzido para o dialeto alvo (sem assumir SAS dentro do SQL nativo)

## Qualidade mínima por ficheiro `NN_*.sql`

Para **cada** ficheiro:

- [ ] Não é stub (`select 1` sem `from`, `where 1=0`, `fl_step_scaffold`, placeholders genéricos)
- [ ] `{{ config(materialized='…') }}` existe e é coerente com o papel do modelo na cadeia
- [ ] Comentários `TODO` são raros, explicados e não substituem lógica obrigatória

## Artefacto obrigatório

Copie o modelo em `templates/AI_DRAFT_FLOW_VALIDATION_REPORT.md` (se existir) ou crie o relatório com:

- `**Overall:** PASS`
- Uma secção `## File: \`models/NN_....sql\`` por ficheiro com `**Result:** PASS`

## Coverage (obrigatório quando aplicável)

- [ ] Se o cabeçalho do `.txt` tiver **ambos**:
  - `PERMANENT OUTPUTS (Target Marts): ...` **(≠ (none))** e
  - `EXPORTED FILES (Artifacts): ...` **(≠ (none))**
  
  então o `AI_DRAFT_FLOW_VALIDATION_REPORT.md` **deve** conter a secção `## Coverage` registrando **os dois** (Permanent outputs + Exported files), além de `Coverage status` e `Missing` (se parcial).
