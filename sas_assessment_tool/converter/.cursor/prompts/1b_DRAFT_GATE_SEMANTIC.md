# PROMPT 1b — Gate semântico pós-draft (após `python -m scripts.draft_gate`)

## Quando usar

> **Não se aplica ao modo PASSO 2 steps-only (draft-only)**. Nesse modo, o gate é `python -m scripts.step_gate "[NOME_SEM_EXT]" --write-report` e o artefato de verificação é `draft_models/[NOME_SEM_EXT]/STEP_GATE_REPORT.md`.

**Imediatamente depois** de, na pasta `converter/`, executar:

`python -m scripts.draft_gate "[NOME_SEM_EXT]"`

(com correção de **erros** do script antes de considerar este passo concluído).

Use **só** este prompt para a parte **humana/LLM** do gate; a parte mecânica é **só** o script.

## Persona

Revisor técnico que valida **significado** e paridade de alto nível (o script não julga equivalência SQL).

## Checklist obrigatória

1. Abrir e seguir **`converter/templates/DRAFT_GATE_CHECKLIST.md`** (filtros, equivalência de nomes de tabelas, pass-through, staging duplicado vs `staging_ref_map`).

2. Cruzar o **cabeçalho** do `.txt` (**`PERMANENT OUTPUTS (Target Marts)`**) com o **corpo SAS** (ex.: `data LIBREF.membro`, `PROC EXPORT`, persistência em libref permanente ≠ `WORK`) com **`models/marts/`** no draft e com **§5** / **§9** do `MIGRATION_SPEC.md`, conforme **§2.1–2.2** de **`01_sas_to_dbt.mdc`**.

3. Cruzar com **`draft_models/[NOME_SEM_EXT]/MIGRATION_SPEC.md`** e **`text_egps/[NOME_SEM_EXT].txt`** (cabeçalho + `FILTERS_ORIGINAIS` se existir).

4. Se existir **`draft_models/.../DRAFT_GATE_REPORT.md`** (gerado com `--write-report`), usar como lista de avisos a esgotar ou justificar.

## Critério de saída

- Não avançar à **governança** (`2_GOVERNANCE_ENGINEER.md`) se houver **incerteza** nos itens críticos da checklist ou se o `draft_gate` ainda reportar **erros** após correção do draft.

## Lote

Preferir `python -m scripts.batch_pipeline draft-gate --batch-file registry/egp_keys_batch.txt` para atualizar o manifest; por EGP, aplicar mentalmente a mesma checklist.

## Seguinte

- **`.cursor/prompts/2_GOVERNANCE_ENGINEER.md`**
- **`.cursor/skills/orchestrator/SKILL.md`** (PASSO 3)
