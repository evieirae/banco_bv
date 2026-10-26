# COMPONENT_PUBLISH_VERIFICATION_REPORT — `[EGP_KEY]`

## Sumário

- **Overall:** <!-- PASS | FAIL -->
- **Sandbox (converted_egps) root:** `converted_egps/[YYYY-MM-DD]_[git-short]_[TARGET]/[EGP_KEY]/` (ou legado `converted_egps/[TARGET]/[EGP_KEY]/`)
- **Clone dest (DBT_CLONE_DEST):** `[...]`

## Paridade sandbox → clone (intermediate + marts)

### Intermediate

- **Sandbox intermediate path:** `converted_egps/[YYYY-MM-DD]_[git-short]_[TARGET]/[EGP_KEY]/models/intermediate/` (ou legado)
- **Clone intermediate path:** `DBT_CLONE_DEST/intermediate/`
- **Faltantes no clone (a partir do sandbox):**
  - <!-- listar paths relativos; se nenhum, escrever “(nenhum)” -->

### Marts

- **Sandbox marts path:** `converted_egps/[YYYY-MM-DD]_[git-short]_[TARGET]/[EGP_KEY]/models/marts/` (ou legado)
- **Clone marts path:** `DBT_CLONE_DEST/marts/`
- **Faltantes no clone (a partir do sandbox):**
  - <!-- listar paths relativos; se nenhum, escrever “(nenhum)” -->

## Staging (reuso no componente)

- **Regra:** não exigir paridade 1:1 do staging do sandbox para o clone.
- **Checagem:** refs `stg_*` usados por intermediate/marts no clone existem no componente.
- **Resultado:** <!-- OK | FAIL | N/A -->
- **Notas:**
  - <!-- opcional -->

## Coverage gate (quando aplicável)

> Aplicável quando o cabeçalho de `text_egps/[EGP_KEY].txt` declarar **ambos** (≠ `(none)`):
> `PERMANENT OUTPUTS (Target Marts)` e `EXPORTED FILES (Artifacts)`.

- **Permanent outputs (txt):** <!-- colar lista do cabeçalho -->
- **Exported files (txt):** <!-- colar lista do cabeçalho -->
- **Flow-only IA report tem `## Coverage`:** <!-- sim | não | n/a -->
- **Coverage status:** <!-- total | parcial | n/a -->
- **Missing:** <!-- se parcial -->

## Evidências mínimas (citar)

- **Ficheiros verificados (amostra):**
  - <!-- ex.: 3-5 paths em intermediate/marts -->
- **Trechos / links (quando FAIL):**
  - <!-- referenciar onde ficou incompleto -->

## Próximo passo recomendado

<!-- 1 parágrafo com ação concreta: recopy, corrigir relatório IA Coverage, reexecutar checks --strict, etc. -->

---

**Data / contexto:** <!-- opcional -->
