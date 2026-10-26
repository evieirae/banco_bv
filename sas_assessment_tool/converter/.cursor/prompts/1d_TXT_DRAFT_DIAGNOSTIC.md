# PROMPT 1d — Diagnóstico forense: falhas entre `text_egps` (`.txt`) e draft dbt

## Quando usar

- Após **falha ou avisos persistentes** de `python -m scripts.draft_flow_gate`, `python -m scripts.draft_gate` ou `python -m scripts.step_gate` (idealmente com `--write-report` já executado pelo agente executor).
- **Incerteza** pós-PROMPT 1b (gate semântico): o mecânico passou com warnings ou o revisor não sabe se o gap é extração, spec, ou tradução SAS→SQL.
- **Lote / triagem**: documentar causa provável e próximo passo **sem** editar código (este micro-papel é **só leitura**).

**Não** usar como substituto dos gates nem como decisão “ok para governança”. **Não** avançar o pipeline sozinho: entregar o relatório ao agente executor / humano.

## Pré-condições e guardrails

- Trabalhar a partir da pasta **`converter/`** (paths relativos a ela).
- Receber o **`egp_key`** (nome do projeto **sem** `.egp`), igual ao usado em `text_egps/<egp_key>.txt` e `draft_models/<egp_key>/`.
- **Read-only:** **não** criar, alterar nem apagar ficheiros do draft, `.txt`, clone ou repo. **Não** executar `dbt build`, `git commit`, `git push` (ver `.cursor/rules/04_pipeline_operational_guardrails.mdc`).
- Saída: preencher **`converter/templates/TXT_DRAFT_DIAGNOSIS_REPORT.template.md`** (copiar para `draft_models/<egp_key>/TXT_DRAFT_DIAGNOSIS_REPORT.md` **só** se o utilizador/agente executor pedir explicitamente persistência — por defeito, basta o Markdown na resposta).

## Ordem de leitura (contexto mínimo)

1. **Relatório(s) de gate** existentes (prioridade ao último que falhou ou que concentra avisos):
   - Flow-only: `draft_models/<egp_key>/DRAFT_FLOW_GATE_REPORT.md`, `AI_DRAFT_FLOW_VALIDATION_REPORT.md`
   - Camadas: `draft_models/<egp_key>/DRAFT_GATE_REPORT.md` (requer gate corrido com `--write-report`)
   - Steps: `draft_models/<egp_key>/STEP_GATE_REPORT.md`, `AI_STEP_VALIDATION_REPORT.md` (se existirem)
2. **`text_egps/<egp_key>.txt`**: bloco `START_METADATA` … `END_METADATA` (chaves relevantes: `TARGET_ARCH`, `PROJECT`, `DETECTED_TABLES_*`, `PERMANENT OUTPUTS`, `FILTERS_ORIGINAIS` se existir); depois amostra do corpo SAS após `END_METADATA` se o relatório apontar extração truncada ou paridade semântica.
3. **`draft_models/<egp_key>/MIGRATION_SPEC.md`** (se existir): contrato YAML, tabela **TARGET_ARCH efetivo**, **PROJECT (extrator)**, §5/§9 conforme necessário ao caso.
4. **SQL/Py do draft** — **só** ficheiros citados nos relatórios ou diretamente ligados à hipótese (ex.: `models/marts/*.sql` citado em aviso de tabela; `NN_*.sql` na raiz de `models/` em flow-only).

## Detetar o modo de draft (ramificar)

| Heurística | Modo | Gates / artefactos de referência |
|------------|------|-----------------------------------|
| Existe `draft_models/<egp>/models/staging/`, `intermediate/`, `marts/` com conteúdo canónico | **Três camadas** | `draft_gate.py`; PROMPT **1b** + `templates/DRAFT_GATE_CHECKLIST.md` para o que é semântico após o mecânico |
| Existem `models/steps/*.sql` e/ou `STEP_MANIFEST.json` como fonte de verdade dos passos | **Steps / caminho para camadas** | `step_gate.py`; `ai_step_gate`; checklist steps em `templates/AI_VALIDATION_CHECKLIST.md` quando aplicável |
| `models/` tem `NN_*.sql` na raiz **e** não há as três pastas canónicas como layout principal | **Flow-only** | `draft_flow_gate.py`; `templates/AI_DRAFT_FLOW_VALIDATION_CHECKLIST.md` |

Se dois modos parecem misturados (ex.: steps + marts vazios), registar como **inconsistência de layout** na secção de hipóteses.

## O que cruzar (checklist de investigação)

- **Spec ↔ extrator:** `TARGET_ARCH` / `PROJECT` no `MIGRATION_SPEC.md` vs cabeçalho do `.txt` + catálogo (espelhar mensagens já em `DRAFT_GATE_REPORT.md` — não duplicar como “descoberta” sem citar o relatório).
- **Tabelas:** avisos `DETECTED_TABLES_*` “possivelmente não refletidas” (`draft_gate`) — distinguir falso positivo (nome curto, alias, `source()`) vs omissão real.
- **Outputs permanentes / marts:** cabeçalho e corpo SAS vs modelos em `marts/` (alinhar mentalmente com **§2.1–2.3** de `01_sas_to_dbt.mdc` quando `TARGET_ARCH` for DBT_BQ).
- **Filtros:** presença de `FILTERS_ORIGINAIS` no `.txt` vs existência de `_FILTROS_APLICADOS.md` e rastreio nos SQL.
- **Staging reutilizado:** `staging_ref_map` no catálogo vs `ref()` no draft (erros explícitos do `draft_gate`).
- **Corpo SAS curto:** aviso de tamanho após `END_METADATA` — suspeita de extração incompleta (PASSO 1), não de “só” SQL.

## Saída obrigatória

Produzir o relatório no formato de **`converter/templates/TXT_DRAFT_DIAGNOSIS_REPORT.template.md`**, com:

- Resumo executivo.
- Modo detetado + lista de ficheiros de gate lidos.
- Tabela Hipótese | Evidência | Severidade | Ação sugerida.
- Secção “Já coberto pelo gate mecânico”.
- Secção “Lacunas só semânticas”.

## Invocação como sub-agente (Cursor)

O orquestrador pode delegar este papel a um agente **explore** em **modo read-only**, passando apenas: `egp_key`, estes paths sob `converter/`, e a instrução de seguir este ficheiro até preencher o template. O agente **executor** aplica correções e volta a correr os scripts de gate.

## Seguinte (fora deste prompt)

- Executor: corrigir draft/spec/extração conforme ações sugeridas; reexecutar o gate adequado com `--write-report`.
- Governança: só após fecho normal do PASSO 2 / 2A / 2B + 2b conforme `orchestrator/SKILL.md`.
