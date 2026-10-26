# PROMPT 0 — Contrato MIGRATION_SPEC (PASSO 1c)

## Quando usar

Depois de **PASSO 1** (extrator) e **PASSO 1b** (catálogo + `resolve` + `cd_governanca`). Use **só** este prompt quando o pedido for gerar/completar o spec, sem traduzir SAS nem governança.

## Persona

Engenheiro de dados que fixa o **contrato** de migração para tradutor e governança.

## Tarefas

1. Na pasta **`converter/`**, executar:
   `python -m scripts.generate_migration_spec "[NOME_SEM_EXT]"`
   (aspas se o `egp_key` tiver espaços).

2. Abrir **`converter/draft_models/[NOME_SEM_EXT]/MIGRATION_SPEC.md`** e **completar todas as secções TODO** relevantes (fontes, saídas, ordem lógica, notas de staging).

3. Preencher ou rever o **`## 9. Manifest canónico do draft`** (bloco YAML `draft_manifest` com lista `models`: `{layer, stem}` por modelo esperado em `draft_models/.../models/`). Alinhe o manifesto a: (i) **`PERMANENT OUTPUTS (Target Marts)`** no cabeçalho do `.txt`; (ii) **persistência em libref de biblioteca permanente** (não `WORK`) visível no SAS (`data LIBREF.membro`, etc.); (iii) cada **`PROC EXPORT`** → 1 mart (`@01_sas_to_dbt.mdc` §2.1–2.2); (iv) se não houver (i)–(iii), incluir mart(s) para **`WORK` terminal(is)** conforme **§2.3**. Com `models` não vazio, o `draft_gate` **falha** se faltar algum ficheiro listado.

4. Usar como referência de estrutura: **`converter/templates/MIGRATION_SPEC.template.md`**.

## Entrada esperada

- `converter/text_egps/[NOME_SEM_EXT].txt` já existente.
- Entrada correspondente em **`converter/registry/egp_catalog.yaml`**.

## Saída

- `draft_models/[NOME_SEM_EXT]/MIGRATION_SPEC.md` pronto para o **PROMPT 1** (`1_LOGIC_TRANSLATOR.md`).

## Seguinte

- Draft SAS: **`.cursor/prompts/1_LOGIC_TRANSLATOR.md`**
- Roteiro global e tabela de **micro-papéis**: **`.cursor/skills/orchestrator/SKILL.md`**
