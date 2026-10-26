# TXT_DRAFT_DIAGNOSIS_REPORT — `[EGP_KEY]`

> Preencher substituindo `[EGP_KEY]` e removendo linhas de instrução opcionais. Gerado pelo micro-papel **PROMPT 1d** (`.cursor/prompts/1d_TXT_DRAFT_DIAGNOSTIC.md`). **Read-only** — não substitui `draft_gate` / `draft_flow_gate` / `step_gate`.

## Resumo executivo

<!-- 1–3 frases: o que falhou ou está em dúvida, e qual a causa mais provável. -->

## Modo de draft detetado e fontes

| Campo | Valor |
|-------|--------|
| **Modo** | <!-- flow-only \| steps-only \| três-camadas \| inconsistente --> |
| **text_egps** | `text_egps/[EGP_KEY].txt` |
| **draft_models** | `draft_models/[EGP_KEY]/` |
| **Relatórios de gate lidos** | <!-- ex.: DRAFT_GATE_REPORT.md, DRAFT_FLOW_GATE_REPORT.md, STEP_GATE_REPORT.md, AI_* --> |
| **MIGRATION_SPEC** | <!-- presente / ausente --> `draft_models/[EGP_KEY]/MIGRATION_SPEC.md` |

## Hipóteses de causa

| # | Hipótese | Evidência (trecho `.txt`, linha de relatório ou de SQL) | Severidade | Ação sugerida |
|---|----------|--------------------------------------------------------|------------|---------------|
| 1 | | | <!-- baixa / média / alta --> | |
| 2 | | | | |

## Já coberto pelo gate mecânico

<!-- Listar achados que são apenas repetição do que `draft_gate` / `draft_flow_gate` / `step_gate` já afirmou — para não re-tratar na governança como novidade. -->

-

## Lacunas só semânticas

<!-- O que os scripts não podem validar: equivalência de negócio, ordem de joins, semântica de PROC específica, etc. -->

-

## Próximo passo recomendado (para o executor)

<!-- Um parágrafo: qual comando reexecutar (ex.: `python -m scripts.draft_gate "[EGP_KEY]" --write-report`) e qual ficheiro/prompt corrigir primeiro. -->

---

**Data / contexto:** <!-- opcional -->
