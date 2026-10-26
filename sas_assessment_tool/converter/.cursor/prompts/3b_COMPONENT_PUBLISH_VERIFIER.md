# PROMPT 3b — Verificador de publicação no componente dbt (pós-PASSO 3B)

## Quando usar

- Após o **PASSO 3B** (cópia do sandbox `converted_egps/...` para o clone do componente em `DBT_CLONE_DEST`).
- Objetivo: garantir que o que foi publicado no componente dbt está **completo e coerente** antes do fecho do EGP.

## Guardrails

- **Read-only** sobre lógica: não alterar SQL/Py do EGP nem do componente.  
- **Pode** escrever apenas o relatório final (artefacto) no **sandbox** (ver “Saída obrigatória”).
- **Proibido:** `dbt build`, `git commit`, `git push`. (ver `.cursor/rules/04_pipeline_operational_guardrails.mdc`)

## Entradas obrigatórias (paths sob `converter/`)

- `text_egps/<egp_key>.txt`
- `draft_models/<egp_key>/MIGRATION_SPEC.md`
- `draft_models/<egp_key>/AI_DRAFT_FLOW_VALIDATION_REPORT.md` (quando existir; obrigatório no modo flow-only)
- **Sandbox convertido**: `converted_egps/<YYYY-MM-DD>_<git-short>_<target>/<egp_key>/` (ou legado `converted_egps/<target>/<egp_key>/`; `<target>` = `dbt` ou `databricks`)
- **Clone do componente**: `DBT_CLONE_DEST` (path absoluto vem do spec/catalog; tipicamente `.../models/workspace/.../migracao_sas/<EGP_SLUG>/`)

## O que validar (escopo)

### A) Paridade sandbox → clone (somente intermediate + marts)

- Compare **conteúdo e existência** de todos os ficheiros em:
  - `converted_egps/<DATA>_<sha>_<target>/<egp_key>/models/intermediate/**` (ou legado `converted_egps/<target>/<egp_key>/...`)
  - `converted_egps/<DATA>_<sha>_<target>/<egp_key>/models/marts/**` (ou legado `converted_egps/<target>/<egp_key>/...`)
  com os correspondentes em:
  - `DBT_CLONE_DEST/intermediate/**`
  - `DBT_CLONE_DEST/marts/**`

**Regras:**
- Se um ficheiro existir no sandbox e **não** existir no clone → **FAIL**.
- Se existir em ambos mas o conteúdo for claramente diferente (ex.: tamanho muito discrepante / alterações visíveis) → **WARN** (ou **FAIL** se alterar lógica/materialização).

### B) Staging (reuso preferencial)

- **Não** exigir paridade 1:1 entre `models/staging/**` do sandbox e do clone.
- Verificar apenas:
  - existe `DBT_CLONE_DEST/staging/` (ou staging reutilizado por `ref()` fora de `migracao_sas`) e
  - os modelos em `intermediate/` e `marts/` no clone **não** referenciam staging inexistente (ex.: `ref('stg_...')` que não existe no componente).

### C) Coverage gate (quando aplicável)

Se o cabeçalho do `.txt` declarar **ambos** (≠ `(none)`):
- `PERMANENT OUTPUTS (Target Marts): ...`
- `EXPORTED FILES (Artifacts): ...`

Então:
- Confirmar que `draft_models/<egp_key>/AI_DRAFT_FLOW_VALIDATION_REPORT.md` contém `## Coverage` e registra explicitamente:
  - **Permanent outputs (txt):**
  - **Exported files (txt):**
  - **Coverage status:** `total|parcial`
  - **Missing:**
- Se faltar → **FAIL**.

## Saída obrigatória (persistência no sandbox — opção B)

Preencher o template `converter/templates/COMPONENT_PUBLISH_VERIFICATION_REPORT.template.md` e salvar como:

- `converted_egps/<DATA>_<sha>_<target>/<egp_key>/COMPONENT_PUBLISH_VERIFICATION_REPORT.md` (ou legado `converted_egps/<target>/<egp_key>/...`)

O relatório deve conter obrigatoriamente:
- `**Overall:** PASS` ou `**Overall:** FAIL`
- Lista de ficheiros faltantes (se houver)
- Evidência mínima do coverage gate quando aplicável

## Nota operacional

Este micro-papel serve para **bloquear fecho** quando a publicação no componente está incompleta. O gate determinístico vai procurar o relatório no sandbox.
