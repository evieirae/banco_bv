---
name: orchestrator
description: Única skill do pipeline EGP; orquestra micro-papéis via prompts (.cursor/prompts) + scripts determinísticos — contexto mínimo por fase
---

# Conversão EGP – Fluxo completo (Orquestrador)

## Quando usar

**Um EGP** — use quando o usuário pedir para:
- Converter um EGP
- Rodar a conversão para [nome].egp
- Executar o prompt de conversão do arquivo [nome]
- Migrar o projeto [nome] (EGP)

**Modo lote** — use quando pedir para:
- Converter **todos** (ou uma **lista** de) EGPs, **em massa**, **batch**, **fila** de projetos
- **Só extrair** vários `.egp` para `text_egps/` com rastreio
- Rodar **gate** ou **extract+gate** sobre uma lista de `egp_key` (CI / preparação antes dos agentes)

O usuário informa o **nome do arquivo EGP** (com ou sem `.egp`) **ou**, em lote, uma **lista de nomes** / ficheiro `registry/egp_keys_batch.txt` (um `egp_key` por linha; linhas `#` ignoradas). Ex.: `CobrancaAcima120dias_v15_GCP`, `Performance Solar 2 (1).egp`.

**Comportamento (single-EGP):** Execute os passos 1 a 6 **em ordem**, sem perguntar ao usuário. **Preferência anti-alucinação:** tratar cada fase LLM como **micro-papel** (só o prompt da vez + ficheiros que ele exige), depois **gate/script** antes do micro-papel seguinte.

**Comportamento (lote):** Siga a secção **Modo lote** abaixo: parte determinística via **`python -m scripts.batch_pipeline`** + manifest; micro-papéis **1c → 2 → 2b → 3 → 4 → 5 → 6** **por EGP em série** (recomendado), salvo indicação explícita do utilizador.

## Micro-papéis (uma única skill: este orchestrator)

**Não** criar outras skills Cursor para o pipeline. Os **micro-papéis** são:

- **Prompts** em **`.cursor/prompts/*.md`** (um por fase LLM).
- **Passos determinísticos** no terminal (sem LLM).

**Disciplina de contexto:** em cada fase, o agente deve **priorizar** ler **só** o prompt indicado e as **`.mdc`** que esse prompt referencia — evitar carregar o roteiro completo deste ficheiro + todas as regras num único turno quando o utilizador estiver a executar fase a fase.

### Regras Cursor (`.mdc`) condicionais por `TARGET_ARCH` (arquitetura alvo)

Objetivo: **menos contexto** e **menos conflito** entre SQL dbt e PySpark — em cada invocação, carregar **apenas** a regra da **arquitetura alvo** correta.

| `TARGET_ARCH` efetivo (cabeçalho `.txt` + `MIGRATION_SPEC` / catálogo) | Regra de governança / estilo a usar nos PASSOS 2, 2b e 3 |
|------------------------------------------------------------------------|-----------------------------------------------------------|
| **`DBT_BQ`** | **Só** `.cursor/rules/01_sas_to_dbt.mdc` |
| **`DATABRICKS`** | **Só** `.cursor/rules/02_sas_to_databricks.mdc` |

- **PASSO 5 (AGENTE 3):** Critérios de governança no relatório seguem **`03_migration_auditor.mdc`**, que já remete a **`01`** ou **`02`** conforme `TARGET_ARCH` — **não** aplicar os dois ao mesmo tempo.
- **Sem terceiro modo “HYBRID” de arquitetura alvo:** não existe `TARGET_ARCH` HYBRID nem regra `04_hybrid_...mdc` no roadmap. **`staging_mode: hybrid`** no catálogo é **outro conceito** (staging parcialmente reutilizado), não arquitetura alvo — ver `registry/egp_catalog.yaml` e `README.md` (catálogo / `staging_mode`).

| Micro-papel | PASSO | LLM? | Entrada principal | Saída / artefacto | Verificação obrigatória antes de avançar |
|-------------|-------|------|-------------------|-------------------|------------------------------------------|
| Extrator | 1 | Não | `received_egps/<AREA>/*.egp` (recomendado) ou raiz + `--area` / `EGP_BUSINESS_AREA` | `text_egps/[NOME].txt` | Ficheiro `.txt` gerado; cabeçalho com **`BUSINESS_AREA`** coerente com a área (evitar `(none)` salvo legado acordado) |
| Catálogo + clone | 1b | Não* | `egp_catalog.yaml`, `resolve` | `[DBT_REPO_ROOT]`, `[DBT_CLONE_DEST]` | Paths válidos no disco |
| **Spec** | 1c | Sim | **PROMPT 0** + `.txt` + catálogo | `draft_models/.../MIGRATION_SPEC.md` | **`python -m scripts.generate_migration_spec`** corrido; TODOs fechados |
| **Draft (flow-only — padrão)** | 2 | Sim | **AGENTE 1 (FLOW)** `.cursor/prompts/1_LOGIC_TRANSLATOR_FLOW.md` + `.txt` + `MIGRATION_SPEC.md` | `draft_models/<egp>/models/NN_*.sql` (flat; cadeia `ref()` coerente; **sem** `models/steps/`; **sem** `staging/intermediate/marts`) + `AI_DRAFT_FLOW_VALIDATION_REPORT.md` | **Gate mecânico:** `python -m scripts.draft_flow_gate \"<egp_key>\" --write-report` (**até 5 tentativas**). **Coverage gate (flow-only):** se o cabeçalho do `.txt` declarar **`PERMANENT OUTPUTS (Target Marts)`** **e** **`EXPORTED FILES (Artifacts)`** (ambos ≠ `(none)`), o `AI_DRAFT_FLOW_VALIDATION_REPORT.md` deve conter `## Coverage` registrando **os dois** (Permanent outputs + Exported files) + status `total|parcial` + `Missing` — caso contrário o `draft_flow_gate` falha. **Autofix safe-only (opcional):** `python -m scripts.draft_model_autofix \"<egp_key>\" --autofix`. **Regra A (fecho):** `python -m scripts.batch_pipeline checks --batch-file <1 linha> --strict` OK (inclui `flow_coverage_ok`). |
| **Draft (steps-only — legado)** | 2A | Sim | **AGENTE 1 (STEPS)** + `.txt` (+ `STEP_MANIFEST.json`) | `.sql` em **`models/steps/`** (1 ficheiro por passo SAS conforme `STEP_MANIFEST.json`) **preenchidos com a lógica do bloco SAS** (proibido placeholder genérico como `data_null`) | **Gate mecânico:** `python -m scripts.step_gate --write-report` sem faltas (**até 5 tentativas**). **Gate IA (obrigatório, 100% dos steps):** `python -m scripts.ai_step_gate \"[NOME_SEM_EXT]\" --write-report --autofix` deve retornar 0 e gerar `draft_models/[NOME_SEM_EXT]/AI_STEP_VALIDATION_REPORT.md` (sem FAIL; pode conter `AUTO-FIXED`). Use `templates/AI_VALIDATION_CHECKLIST.md` (2A) como referência semântica. **Fecho do draft-only:** só considerar sucesso quando **step_gate + ai_step_gate** estiverem OK. |
| **Draft (camadas / legado canônico)** | 2B | Sim | **AGENTE 1 (LAYERS_FROM_STEPS)** + spec + `.txt` + `STEP_MANIFEST.json` + `models/steps/*.sql` | `.sql`/`.py` em **`models/staging/`**, **`intermediate/`**, **`marts/`** (≥1 por camada) com **`materialized='…'`** literal por ficheiro (**DBT_BQ** e **DATABRICKS**; ver `draft_layer_guard.py`) + **`stem.yml`** irmão por modelo em `intermediate/` e `marts/` (**DBT_BQ**) + `_FILTROS_APLICADOS.md` se aplicável. As camadas devem ser **derivadas dos steps** (fonte de verdade do PASSO 2A), não “reconvertidas” do zero. | **Pré-requisito:** `python -m scripts.step_gate --write-report` OK (PASSO 2A). **Depois:** `python -m scripts.draft_gate --write-report` sem erros (**até 5 tentativas**). **Regra A (fecho do EGP):** após produzir o draft e copiar para sandbox/clone, executar **`python -m scripts.batch_pipeline checks --batch-file <ficheiro com 1 egp_key> --strict`** e só considerar a tentativa como sucesso se também estiver OK. |
| **Gate semântico** | 2b | Sim | **PROMPT 1b** + output do gate + checklist | Decisão “ok para governança” | **`DRAFT_GATE_CHECKLIST.md`** esgotada ou justificada |
| **Governança** | 3 | Sim | **AGENTE 2** + draft + regras `01`/`02` | `converted_egps/...` + clone | **PASSO 4** (`auto_fixer` se DBT_BQ) |
| Validação / fecho draft | 4 | Não (major) | sandbox | Lint / cópia clone | `auto_fixer` + reaplicar clone se mudou; **não apagar** `draft_models/` por defeito (ver **Ciclo de vida** abaixo) |
| **Auditoria** | 5 | Sim | **AGENTE 3** + `.txt` + sandbox | `AUDITORIA_*.md` | Critérios em `03_migration_auditor.mdc` |

**Nota (PASSO 2, DBT_BQ — marts):** além do mínimo mecânico de ficheiros em `marts/`, cobrir **§2.1–2.3** de `01_sas_to_dbt.mdc` (`PROC EXPORT` + libref permanente + `PERMANENT OUTPUTS`; **§2.3** = ordem canónica). O fallback é **mart(s) a partir da(s) tabela(s) `WORK` terminal(is)** só quando não houver exports nem essas saídas permanentes a mapear (não é regra “1 mart por ficheiro `int_*`”).

\*Leitura de YAML e comandos `bootstrap_egp_catalog.py` são determinísticos; só documentação pode ser LLM se o humano pedir.

**Scripts determinísticos (nunca substituir por LLM):** `egps_extractor.py`, `generate_migration_spec.py`, `draft_gate.py`, `draft_flow_gate.py`, `draft_model_autofix.py`, `draft_layer_guard.py`, `batch_pipeline.py`, `model_yml_guard.py`, `check_draft_yml_pairing.py`, `scaffold_int_mart_yml.py`, `pii_sensitive_yml_guard.py`, `yml_documentation_guard.py`, `audit_batch_stamp.py` (metadados `AUDITORIA_*` em lote, stdout), `auto_fixer.py`, `bootstrap_egp_catalog.py` (inclui `ensure-repo` — só operações git seguras; ver guardrails). **Invocação canónica no terminal:** `python -m scripts.<módulo>` a partir da pasta **`converter/`** (ex.: `python -m scripts.egps_extractor`, `python -m scripts.batch_pipeline`).

### Mapa rápido prompt ↔ ficheiro

| Micro-papel LLM | Ficheiro |
|-----------------|----------|
| Spec | `.cursor/prompts/0_MIGRATION_SPEC.md` |
| Draft (flow-only) | `.cursor/prompts/1_LOGIC_TRANSLATOR_FLOW.md` |
| Draft (steps-only) | `.cursor/prompts/1_LOGIC_TRANSLATOR_STEPS.md` |
| Draft (camadas a partir de steps) | `.cursor/prompts/1_LOGIC_TRANSLATOR_LAYERS_FROM_STEPS.md` |
| Gate semântico | `.cursor/prompts/1b_DRAFT_GATE_SEMANTIC.md` |
| Diagnóstico txt↔draft (opcional; read-only) | `.cursor/prompts/1d_TXT_DRAFT_DIAGNOSTIC.md` |
| Governança | `.cursor/prompts/2_GOVERNANCE_ENGINEER.md` |
| Verificação publicação clone (PASSO 3B; obrigatório) | `.cursor/prompts/3b_COMPONENT_PUBLISH_VERIFIER.md` |
| Auditoria | `.cursor/prompts/3_MIGRATION_AUDITOR.md` |

### Diagnóstico forense opcional (falhas `.txt` ↔ draft dbt)

**Objetivo:** interpretar falhas ou avisos persistentes dos gates (especialmente heurísticas e paridade semântica incerta), produzindo **causa provável + próximo passo** — útil em **lote** ou quando o PROMPT **1b** deixa dúvidas. **Não** substitui `draft_gate`, `draft_flow_gate`, `step_gate` nem a decisão de avançar à governança.

**Quando usar:** gate falhou ou `DRAFT_GATE_REPORT.md` / `DRAFT_FLOW_GATE_REPORT.md` / `STEP_GATE_REPORT.md` acumula avisos; padrão repetido em vários `egp_key`; incerteza após 1b.

**Como invocar (sub-agente Cursor):** delegar a um agente **explore** em **modo read-only** com o **PROMPT 1d** (`.cursor/prompts/1d_TXT_DRAFT_DIAGNOSTIC.md`) e contexto mínimo: `egp_key`, paths sob `converter/` para `text_egps/<egp_key>.txt`, `draft_models/<egp_key>/`, e os relatórios de gate existentes. O agente **executor** (mesmo chat ou turno seguinte) aplica correções e reexecuta o gate adequado com `--write-report`.

**Saída:** preencher `converter/templates/TXT_DRAFT_DIAGNOSIS_REPORT.template.md` (resposta no chat; persistir como `draft_models/<egp_key>/TXT_DRAFT_DIAGNOSIS_REPORT.md` só se o utilizador pedir).

**Guardrails:** o PROMPT 1d é **só leitura** — alinhar a `.cursor/rules/04_pipeline_operational_guardrails.mdc` (sem `dbt build`, `git commit`, `git push`).

### Ciclo de vida de `draft_models/` (política canónica)

**Fonte única desta política** — prompts AGENTE 2 / AGENTE 3 e regra `03_migration_auditor.mdc` remetem aqui.

- **Por defeito:** **não apagar** `draft_models/<egp_key>/` no PASSO 4. Manter até:
  1. O **PASSO 5** (auditoria) estar **concluído**, e  
  2. O resultado em **`AUDITORIA_*.md`** estar **aceite** pelo time (ou pelo humano responsável), **ou**  
  3. O utilizador pedir **explicitamente** a remoção antecipada.
- **Motivos:** diff draft ↔ `converted_egps/` após ajustes na governança ou na auditoria; rastreio de `MIGRATION_SPEC.md`, `_FILTROS_APLICADOS.md`, `DRAFT_GATE_REPORT.md` e SQL/Py de rascunho; **reexecução** de **`python -m scripts.draft_gate`** sem regenerar tudo.
- **Onde entra no fluxo:** PASSO 4 (lint/validação) **não** implica apagar `draft_models/` por defeito. PASSO 3 (governança): após gravar em `converted_egps/`, **manter** o draft até auditoria aceite. PASSO 5: relatório **não** deve recomendar apagar `draft_models/` por defeito; o draft pode ser usado **opcionalmente** para cruzamento com o sandbox.
- **Exceções (pode apagar antes):** pedido explícito no chat/ticket; política interna que exija limpeza **após** auditoria registada noutro sistema; EGP abandonado/duplicado com decisão documentada.

## Guardrails operacionais obrigatórios

**Em hipótese nenhuma** o agente ou automação deste pipeline deve executar: **`dbt build`**, **`git commit`**, **`git push`**.

- **Motivo:** evitar materialização não controlada no warehouse e alterações de histórico/remoto git sem revisão humana explícita.
- **Regra Cursor:** `.cursor/rules/04_pipeline_operational_guardrails.mdc`.
- **Permitido:** `git clone` / `git fetch` / `git checkout` / `git pull` **apenas** como parte de **`python -m scripts.bootstrap_egp_catalog ensure-repo`** (preparar pasta do componente dbt), **nunca** `commit` nem `push`.
- **dbt:** no PASSO 4, no máximo **`dbt parse`** opcional no clone — **não** usar `dbt build` (nem como substituto de validação).

## Pré-requisitos

- O arquivo EGP deve estar sob **`received_egps/`** (recomendado: **`received_egps/<slug_area>/projeto.egp`**) ou noutro caminho indicado pelo utilizador.
- No catálogo, o slug **`area`** deve alinhar com a pasta de área quando se usa esse layout; o campo **`egp_file`** deve ser o caminho **relativo** a `received_egps/` quando o `.egp` não está na raiz (ex.: `cobranca/MeuProj.egp`), para o **`python -m scripts.batch_pipeline`** (`extract`) resolver o ficheiro.
- **`registry/egp_catalog.yaml`** deve conter uma entrada cujo **`egp_key`** seja **exatamente** igual a **`[NOME_SEM_EXT]`** (nome do projeto sem `.egp`). Se faltar, execute **`python -m scripts.bootstrap_egp_catalog add ...`** ou **`scan`** a partir da pasta **`converter/`** (ver **`python -m scripts.bootstrap_egp_catalog --help`**).

## Convenção de nomes

- **Nome com extensão** (input/comando): se o usuário não passou `.egp`, acrescente. Ex.: `PROJETO CPC CARTOES 1.egp`.
- **Nome sem extensão** (pastas e referências): remova `.egp`. Ex.: `PROJETO CPC CARTOES 1`. Use como `[NOME_SEM_EXT]` ou `[NOME_DO_PROJETO]`.
- No nome do arquivo de auditoria, substitua espaços por underscores (ex.: `AUDITORIA_PROJETO_CPC_CARTOES_1.md`).
- **`[EGP_SLUG]`** (subpasta segura no clone dbt): derive de `[NOME_SEM_EXT]` substituindo espaços por `_` e caracteres problemáticos para paths (ex.: `(`, `)`) por `_`; colapsar `__` repetidos. Use o mesmo slug na pasta **`migracao_sas/[EGP_SLUG]`** dentro do repositório clonado.

### Política anti-colisão (vários EGPs no mesmo `componente_dbt`)

Especificação canónica: os bullets seguintes neste ficheiro; alinhar com **`01_sas_to_dbt.mdc`** §2 (nomes de modelos).

- **Clone:** um EGP = uma árvore sob **`migracao_sas/[EGP_SLUG]/`**; não misturar ficheiros de dois projetos na mesma pasta sem acordo.
- **Nomes de modelos (`ref`):** padrão **`produto_compacto`** colado (minúsculas) em `int_<produto_compacto>_...` e `<produto_compacto>_..._fato`, conforme **`01_sas_to_dbt.mdc`** §2 — deve ser **distinto por `egp_key`** na prática.
- **Se dois EGPs gerarem o mesmo `produto_compacto` ou o time exigir:** reforçar com prefixo explícito (`int_<slug>__<assunto>`) ou documentar exceção no **`MIGRATION_SPEC.md`** (fatos canónicos partilhados exigem curadoria).
- **Parâmetros `var()`:** chaves únicas por EGP no `dbt_project` quando vários fluxos coexistem (ver §1.3 do `.mdc`).

## Destino duplo: sandbox + clone (obrigatório)

1. **Sandbox (cópia por EGP):** `converter/converted_egps/[DATA_CONVERSAO]_[ULTIMO_COMMIT]_[TARGET_ARCH]/[NOME_SEM_EXT]/` — espelho isolado por **run** de conversão. `[DATA_CONVERSAO]` = data local `YYYY-MM-DD`; `[ULTIMO_COMMIT]` = `git rev-parse --short HEAD` na raiz **`converter/`**; `[TARGET_ARCH]` = `dbt` ou `databricks`. Contém `models/`, YAMLs, `DE_PARA_TIPAGEM.md`, `AUDITORIA_*.md`. **Legado** (ainda suportado por scripts e descoberta): `converter/converted_egps/[TARGET_ARCH]/[NOME_SEM_EXT]/`. **Colisão:** mesmo dia + mesmo HEAD + mesmo alvo + mesmo EGP reutiliza a mesma pasta de run (sobrescreve). **Descoberta:** `python -m scripts.batch_pipeline` / `find_converted_sandbox` preferem legado se existir; no layout novo, se houver vários candidatos, prevalece o pai com **maior `mtime`** (empate: nome lexicográfico).
2. **Clone dbt (integração):** raiz resolvida pelo catálogo + **`python -m scripts.bootstrap_egp_catalog resolve`** (ver PASSO 1b). Dentro dela, copie a árvore de modelos migrados para:
   - **`models/workspace/corp_cobranca/migracao_sas/[EGP_SLUG]/`**  
   preservando subpastas `staging/`, `intermediate/`, `marts/` (ou a estrutura gerada no sandbox).  
   - **Área ≠ cobrança:** use o prefixo acordado no time ou um campo futuro no catálogo; até lá, mantenha `migracao_sas/[EGP_SLUG]/` sob `models/workspace/` conforme governança do repositório alvo.

**Ordem:** primeiro materializar e validar no **sandbox**; em seguida **replicar** (cópia de ficheiros) para o **clone**.

Quando o usuário pedir "converter [nome].egp" (**um** projeto), execute o roteiro completo abaixo (passos 1 a 6 em sequência).

---

## Modo lote (vários EGPs)

Objetivo: repetir o mesmo roteiro **sem perder rastreabilidade**.

### Padrão recomendado (lote isolado: 1 sessão por EGP)

Quando o usuário pedir **conversão em lote**, por defeito execute o lote via runner que dispara **uma sessão nova do Agent CLI por `egp_key`** (isolamento e logs por projeto):

- `bash scripts/run_agent_per_egp.sh -b registry/egp_keys_batch.txt -w "$(pwd)"`
- (Atalho) `bash scripts/run_agent_batch_isolated.sh -b registry/egp_keys_batch.txt -w "$(pwd)"` (roda + imprime resumo)
- Saídas: `logs/agent_runs/<egp_key>.ndjson` e `logs/agent_runs/SUMMARY.tsv`
- Regras: não paraleliza; cada EGP roda sem `--resume/--continue`; segue a skill deste ficheiro por EGP.
- **`scripts/run_batch_interactive.sh`:** antes do agente, pode oferecer **`ensure-repo` em série** só para os `componente_dbt` referenciados no ficheiro de lote (cruzamento `egp_keys_batch.txt` × `egp_catalog.yaml`), quando falta `dbt_project.yml` no path esperado (`defaults.dbt_project_path` + componente). **Não** clonar todos os repositórios listados em `area_componente_dbt.yaml` só porque existem áreas mapeadas.

### Alternativa (um chat/sessão só)

Só quando o usuário pedir explicitamente “tudo na mesma conversa”, aplicar o modo descrito abaixo (iterar **em série** dentro da mesma sessão) e/ou usar os scripts determinísticos de batch.

O agente **não** substitui scripts determinísticos: use **`python -m scripts.batch_pipeline`** para extract/gate e **`registry/batch_manifest.json`**. Políticas de nomes, `EGP_SLUG` e lote: **secções «Convenção de nomes» e «Modo lote» neste ficheiro** e **`README.md`** (Pré-batch, Visão rápida, Execução em lote).

### PASSO 0 — Pré-requisitos do lote

1. **Catálogo (`registry/egp_catalog.yaml`):** garantir que o ficheiro existe **antes** do lote. Se **não existir**, criar a partir de [`registry/egp_catalog.example.yaml`](registry/egp_catalog.example.yaml) (cópia manual ou copiar conteúdo mínimo + `defaults`) — **não** apagar nem regenerar o catálogo inteiro em cada lote (preserva `staging_ref_map`, notas e overrides). Para **novos** `.egp` sem entrada: correr **`python -m scripts.bootstrap_egp_catalog scan [--area <slug>] [--componente …]`**. Com ficheiros em **`received_egps/<slug>/*.egp`**, o `scan` **infere** `area` e grava **`egp_file`** relativo (ex.: `cobranca/MeuProj.egp`) e pode **omitir `--area`**; com `.egp` **directamente na raiz** de `--egp-dir`, **`--area <slug>`** é **obrigatório**. O `scan` **só acrescenta** chaves novas; entradas existentes são ignoradas (use **`--update-area`** só quando quiser alinhar `area`/componente em EGPs já listados).
2. **Mapa área → componente (`registry/area_componente_dbt.yaml`):** opcional mas recomendado em lote; permite omitir `--componente` no `scan` quando a área está definida no mapa. Ver README «Mapa área → componente dbt».
3. **Clone do repositório dbt (condicional, só o que o lote precisa):** antes do PASSO 1c / agente, garantir que cada **`componente_dbt` usado por alguma `egp_key` do ficheiro de lote** existe localmente com **`dbt_project.yml`** na raiz esperada (`defaults.dbt_project_path` + nome do componente, tipicamente `converted_egps/<componente_dbt>/`).
   - **Escopo:** derivar o conjunto de componentes **apenas** do cruzamento **`registry/egp_keys_batch.txt`** (ou batch equivalente) × **`registry/egp_catalog.yaml`**. **Não** iterar `registry/area_componente_dbt.yaml` na íntegra nem clonar repos de áreas que não apareçam nesse conjunto. Chaves do batch **sem** entrada no catálogo: avisar; **não** inferir componente para `git`.
   - **Se a árvore já for válida** (`dbt_project.yml` presente): não rodar git (pular `ensure-repo`).
   - **Se faltar clone / árvore inválida:** **`python -m scripts.bootstrap_egp_catalog ensure-repo --componente "<componente_dbt>"`** (ou **`--egp-key`** / **`--area`** conforme README). Em lote, **uma vez por `componente_dbt`** distinto nesse conjunto. **Proibido:** `git clone` / `fetch` / `pull` fora de `ensure-repo`; **proibido** `git commit` / `git push`.
4. **`registry/egp_catalog.yaml`** completo para **cada** `egp_key` da lista (`scan` / `add` / `import-csv` se faltar entrada).
5. **Lista de alvos:** ficheiro **`registry/egp_keys_batch.txt`** (modelo: **`registry/egp_keys_batch.example.txt`**) **ou** nomes explícitos na mensagem do utilizador — normalizar para um `egp_key` por linha, alinhado ao catálogo.
   - Se o utilizador fornecer a lista no chat, pode materializar o ficheiro de forma determinística com:
     - `python -m scripts.write_egp_keys_batch -o registry/egp_keys_batch.txt <egp_key_1> <egp_key_2> ...`
     - ou via stdin: `printf "%s\n" "key1" "key2" | python -m scripts.write_egp_keys_batch -o registry/egp_keys_batch.txt`
   - Se o pedido for **“converter tudo”** (todos os `.egp` em `received_egps/`) e **não existir** `registry/egp_keys_batch.txt`, gerar automaticamente a lista a partir de `received_egps/**/*.egp` com checagem de colisões:
     - `python -m scripts.write_egp_keys_batch_from_received --received-dir received_egps --out registry/egp_keys_batch.txt`
6. **`.egp` em** **`received_egps/`** (recomendado: **`received_egps/<AREA>/`**, raiz do repo do converter; ou outro `--received-dir` no batch). O **`egp_file`** no catálogo deve ser o caminho **relativo** a esse diretório (ex.: **`cobranca/MeuProj.egp`** sob área; **`MeuProj.egp`** na raiz), alinhado com **`resolve_egp_path`** / **`python -m scripts.batch_pipeline extract`**.

### Parte determinística (terminal, pasta `converter/`)

| Objetivo | Comando |
|----------|---------|
| Extrair todos para `text_egps/` e atualizar manifest | `python -m scripts.batch_pipeline extract --batch-file registry/egp_keys_batch.txt [--resume]` |
| Só gate mecânico (pós-draft) + manifest | `python -m scripts.batch_pipeline draft-gate --batch-file registry/egp_keys_batch.txt [--strict] [--write-report] [--skip-int-mart-yml-pairing]` |
| Extract seguido de draft-gate | `python -m scripts.batch_pipeline run --batch-file registry/egp_keys_batch.txt [--resume-extract] [--scaffold-yml] [--write-csv]` (`--scaffold-yml`: gera `stem.yml` mínimos em falta **antes** do gate; não substitui o AGENTE 2) |
| Checagens leves no disco (`batch_checks` no manifest) | `python -m scripts.batch_pipeline checks --batch-file registry/egp_keys_batch.txt [--strict] [--write-csv]` — com **`--strict`**, falha também se o **draft** (`draft_models/.../models`) tiver int/mart sem `stem.yml` quando `TARGET_ARCH: DBT_BQ` no `.txt` (`draft_yml_pairing_ok`) |
| Pré-check local só paridade YAML do draft | `python -m scripts.check_draft_yml_pairing --draft-root draft_models --egp-key <key>` (exit 1 se faltar irmão) |
| Registar progresso de um passo (1c–6) no manifest | `python -m scripts.batch_pipeline set-step --egp-key <key> --step audit_5 --status ok [--note "..."]` |
| Relatório Markdown agregado do lote | `python -m scripts.batch_pipeline batch-audit -b registry/egp_keys_batch.txt [--refresh-checks] [-o registry/BATCH_AUDIT.md]` |

- **Manifest:** `registry/batch_manifest.json` (merge por `egp_key`; modelo `registry/batch_manifest.example.json`). **`--write-csv`** gera resumo tabular (ex.: `registry/batch_manifest.csv`).
- **Retomada:** `extract --resume` salta EGPs com `extract.status=ok` e `text_egps/<key>.txt` existente. Para passos de agente, **reprocessar só os EGPs pendentes** ajustando o batch file ou repetindo o roteiro por chave em falta.

### Regra de execução (agente LLM)

1. **Por defeito:** para **cada** `egp_key` da lista, **em série**, repetir **PASSO 1b → 1c → 2 → 2b → 3 → 4 → 5 → 6** como no roteiro single-EGP (substituir **`[NOME_SEM_EXT]`** pela chave atual). **Não** avançar o EGP seguinte se o anterior falhar num passo crítico, salvo instrução do utilizador para continuar e registar falhas no resumo.
2. **Alternativa (documentar no chat):** executar **`python -m scripts.batch_pipeline extract`** (ou **`run`**) **uma vez** para todo o lote; depois, por EGP, apenas **1c → 2 → …** (o `.txt` já existe). O **`extract`** usa o campo **`area`** do catálogo ou **infere** a partir do caminho sob `received_dir`; se **`area`** estava vazio e foi inferido, o pipeline **grava** `area` no catálogo após sucesso.

### Paralelismo

- **Não** paralelizar vários EGPs nos passos **2–4** (draft / gate semântico / governança) no **mesmo** `componente_dbt` sem limite acordado — risco de inconsistência, custo e conflitos em YAML no clone. Paralelizar só **extract** (Python) é aceitável se o ambiente suportar; caso contrário, manter **série**.

### Catálogo e nomes no mesmo repositório

- Antes do **PASSO 2** de cada EGP, **ler** a entrada em **`egp_catalog.yaml`** (`area`, `componente_dbt`, `staging_mode`, `staging_ref_map`, overrides).
- Vários fluxos no **mesmo** pacote dbt: seguir **secção 9.3** do doc de melhorias (`produto_compacto` distintos, isolamento `migracao_sas/[EGP_SLUG]/`, reforço de prefixo ou nota no spec se necessário). Resumo na skill: **Política anti-colisão** acima.

### Saída esperada do lote

No final (ou após cada EGP, se o utilizador pedir progresso), apresentar **tabela resumo**: `egp_key` × `componente_dbt` × estado (ok / aviso / falha) × caminho **`AUDITORIA_*.md`** no sandbox (quando existir). Opcional: referenciar **`batch_manifest.json`** / CSV. **`BATCH_AUDIT.md`** agregado é **opcional** (ainda não automatizado no repo).

**Auditoria em lote (PASSO 5):** cada **`AUDITORIA_*.md`** gerado nesse contexto **deve** incluir **`modo_lote: sim`**, **`ficheiro_lote:`** com o path do ficheiro de lista usado (ex.: `registry/egp_keys_batch.txt`) e a secção **`## Pontos de alto risco (revisão humana)`** conforme **`.cursor/rules/03_migration_auditor.mdc`**. Esqueleto opcional: **`converter/templates/AUDITORIA_HIGH_RISK_SECTION.template.md`**.

---

## Roteiro de execução (siga estritamente a ordem)

### PASSO 1: Extração (Script Python)

1. Extraia da mensagem do usuário o nome do arquivo e normalize (com e sem `.egp`).
2. Execute no terminal (a partir da pasta **`converter/`**), com o `.egp` tipicamente em **`received_egps/<AREA>/`**:
   - `python -m scripts.egps_extractor "received_egps/<AREA>/[NOME_COM_EXTENSAO].egp"`
   - **Área (prioridade):** `--area <slug>` > variável de ambiente **`EGP_BUSINESS_AREA`** > inferência (pasta-mãe / caminho sob `received_egps`) > **`input`** em TTY se ainda faltar; **fora de TTY** o comando **falha** se não houver área (defina `--area` ou `EGP_BUSINESS_AREA`, ou use subpasta `received_egps/<AREA>/...`).
   - Se o `.egp` estiver **directamente na raiz** de `received_egps/`, use **`--area`** ou **`EGP_BUSINESS_AREA`** (a inferência devolve vazio nesse caso).
3. Aguarde o comando terminar.
4. Leia o arquivo gerado em `text_egps/[NOME_SEM_EXT].txt` e identifique o **TARGET_ARCH** e **`BUSINESS_AREA`** no cabeçalho (pode ser `DBT_BQ` ou `DATABRICKS`).

### PASSO 1b: Catálogo e raiz do repositório dbt (clone)

1. Abra **`registry/egp_catalog.yaml`** e localize a entrada com **`egp_key`** igual a **`[NOME_SEM_EXT]`**. Se não existir, **pare** e registre que é necessário registar o EGP no catálogo (**`python -m scripts.bootstrap_egp_catalog`** `add` / `scan`).
2. Anote da entrada (e dos **`defaults`**, quando aplicável): **`area`**, **`componente_dbt`**, **`staging_mode`**, **`staging_ref_map`**, **`target_arch_override`** (se houver). Para **`cd_governanca`** nos labels dbt, consulte **`registry/area_cd_governanca.yaml`** (copiar de **`area_cd_governanca.example.yaml`** se necessário) usando o slug **`area`** como chave em `area_cd_governanca`, ou `default_cd_governanca` se faltar a chave. Opcionalmente execute: `python -m scripts.bootstrap_egp_catalog governance-cd "[NOME_SEM_EXT]" -o registry/egp_catalog.yaml` (use `-v` para ver `area` e origem do valor).
3. **Preparar componente dbt (clone condicional):** garantir que a raiz do projeto dbt para este **`componente_dbt`** existe localmente e contém **`dbt_project.yml`** **antes** do `resolve` e antes do PASSO 1c se o spec/paths dependerem do clone.
   - **Critério:** pasta `defaults.dbt_project_path` + `componente_dbt` (ex.: `converted_egps/dbt-srcg-anlt-plataforma/`) com `dbt_project.yml` na raiz.
   - **Se a árvore já for válida:** **não** rodar git (pular `ensure-repo`) e seguir para o `resolve`.
   - **Se faltar clone ou árvore inválida:** executar **`python -m scripts.bootstrap_egp_catalog ensure-repo --componente "<componente_dbt>"`** (ou `--area "<area>"` / `--egp-key` conforme README). **Proibido:** `git commit` / `git push`. (O único caminho permitido para git no pipeline é via `ensure-repo`.)
   - **Modo lote:** repetir o mesmo critério por `egp_key`; agregar os `componente_dbt` **só** a partir das chaves do batch + catálogo e correr `ensure-repo` **no máximo uma vez por componente** antes das sessões do agente (o script `run_batch_interactive.sh` automatiza esse passo quando aplicável).
4. Obtenha o caminho absoluto da raiz do projeto dbt no clone. A partir da **raiz do repo converter**, execute:
   - `python -m scripts.bootstrap_egp_catalog resolve "[NOME_SEM_EXT]" -o registry/egp_catalog.yaml`  
   (use aspas se `egp_key` tiver espaços). Guarde o output como **`[DBT_REPO_ROOT]`**.
5. Confirme que **`[DBT_REPO_ROOT]`** existe no disco (contém tipicamente `dbt_project.yml` e `models/`).
6. Calcule **`[EGP_SLUG]`** conforme a secção **Convenção de nomes** e o caminho de destino no clone:  
   **`[DBT_CLONE_DEST]`** = `[DBT_REPO_ROOT]/models/workspace/corp_cobranca/migracao_sas/[EGP_SLUG]/`

Use **`[DBT_REPO_ROOT]`**, **`[DBT_CLONE_DEST]`** e os metadados do catálogo em todos os passos seguintes (contexto do tradutor e governança).

### PASSO 1c: MIGRATION_SPEC (contrato de migração)

1. Adote o conteúdo de **`.cursor/prompts/0_MIGRATION_SPEC.md`** (PROMPT 0) como instrução principal desta fase.
2. A partir de **`converter/`**, execute:  
   `python -m scripts.generate_migration_spec "[NOME_SEM_EXT]"`  
   (aspas se o nome tiver espaços). Gera **`draft_models/[NOME_SEM_EXT]/MIGRATION_SPEC.md`**.
3. Complete secções **TODO**; referência: **`converter/templates/MIGRATION_SPEC.template.md`**.

**Modo lote:** se **`python -m scripts.batch_pipeline extract`** já tiver corrido, o **PASSO 1** por EGP pode ser **omitido**; mantém-se **1b → 1c → …**.

---

### PASSO 2: Conversão de lógica (draft)

1. Adote **`.cursor/prompts/1_LOGIC_TRANSLATOR.md`** (AGENTE 1) como persona e checklist desta fase.
2. **Entradas:** `draft_models/[NOME_SEM_EXT]/MIGRATION_SPEC.md`, `text_egps/[NOME_SEM_EXT].txt`, metadados do catálogo já refletidos no spec (`staging_mode`, `staging_ref_map`, paths).
3. Gere `.sql` ou `.py` em **`draft_models/[NOME_SEM_EXT]/`** (tipicamente sob `models/`). Com **`TARGET_ARCH == DBT_BQ`**, inclua **`stem.yml` irmão** para cada modelo em **`models/intermediate/`** e **`models/marts/`** (paridade de nome com o `.sql`/`.py`). **`_FILTROS_APLICADOS.md`** quando aplicável.
   - **Definição de “draft concluído” (DBT_BQ e DATABRICKS):** o PASSO 2 **não** está concluído se faltar qualquer um destes itens:
     1) pasta `draft_models/[NOME_SEM_EXT]/models/`,
     2) ao menos 1 modelo em **`models/staging/`** (com `materialized='ephemeral'` em SQL; em Python **DATABRICKS** use `materialized="ephemeral"` ou `materialized="view"`),
     3) ao menos 1 modelo em **`models/intermediate/`** (com `materialized='table'` / `materialized="table"`),
     4) ao menos 1 modelo em **`models/marts/`** (idem `table`),
     5) cada ficheiro nas três pastas deve declarar **`materialized=`** com valor **literal entre aspas** (o `draft_gate` valida via `draft_layer_guard.py`).
     Em **DBT_BQ**, acrescentar: paridade **`stem.yml`** em `intermediate/` e `marts/`.
     Opcional mas recomendado para cobertura: preencher **`## 9. Manifest canónico do draft`** (`draft_manifest.models`); com lista não vazia, o **`draft_gate`** valida cada ficheiro declarado.
     **Marts “naturais” (DBT_BQ):** cada **`PROC EXPORT`** (§2.1) e cada persistência em **biblioteca permanente** (libref ≠ `WORK`, ex.: `data ADAMOR....`) / entrada alinhada a **`PERMANENT OUTPUTS (Target Marts):`** no cabeçalho do `.txt` (§2.2) deve ter correspondência em **`models/marts/`** — ver **`01_sas_to_dbt.mdc`** §2.1–2.3 e **`1_LOGIC_TRANSLATOR.md`**.
     **Fallback:** mart(s) materializando a(s) **tabela(s) `WORK` terminal(is)** do fluxo (`select * from {{ ref('int_...') }}` quando um `int_*` corresponde à última etapa; vários marts se houver várias folhas `WORK` finais) **apenas** quando **não** existirem exports **nem** essas saídas permanentes a mapear (mesmo critério no PROMPT `1_LOGIC_TRANSLATOR.md` e §2.3 do `.mdc`).
4. Em seguida execute sempre o **PASSO 2b (mecânico)**. Se o `draft_gate` reportar **erros**, siga o **Ciclo de retry** abaixo (teto **5** tentativas) antes de avançar ao gate semântico ou ao PASSO 3.

---

### PASSO 2b: Gate híbrido (pós-draft, antes da governança)

1. **Mecânico (terminal, `converter/`):**  
   `python -m scripts.draft_gate "[NOME_SEM_EXT]"`  
   - **`--strict`**, **`--write-report`**, **lote:** `python -m scripts.draft_gate --batch-file ...` ou **`python -m scripts.batch_pipeline draft-gate`** / **`run`** (ver **Modo lote**).  
   - **`--reference-interno-strict`** (opcional): PII em **DBT_BQ** — exige `PII_INTERNO_*` de referência do `componente_dbt` para tipos sensíveis alvo (`pii_sensitive_yml_guard.STRICT_REFERENCE_ENTRY_IDS`); espelhado em **`python -m scripts.batch_pipeline`** (`draft-gate`, `run`, `checks`, `batch-audit --refresh-checks`). Por defeito desligado; pode ativar-se também com **`pii_reference_interno_strict: true`** no **`registry/egp_catalog.yaml`** (entrada ou `defaults`).
   - **`--parity-tables-all-arch`** (opcional): aplica a heurística de cobertura de `DETECTED_TABLES_*` também quando o alvo é **DATABRICKS** (pode gerar mais ruído em `.py`). O mesmo flag existe em **`python -m scripts.batch_pipeline draft-gate`** e **`run`**.  
   - **`--skip-yml-doc`** (opcional): não validar documentação mínima dos `stem.yml` em `intermediate/`/`marts/` no sandbox convertido (**DBT_BQ**); espelhado em **`python -m scripts.batch_pipeline`** (`draft-gate`, `run`, `checks`, `batch-audit --refresh-checks`). Uso: legado ou exceção acordada — **não** substituir governança completa.
   - **`--skip-int-mart-yml-pairing`** (opcional): não exigir `stem.yml` irmão no **draft** para cada modelo int/mart (**DBT_BQ**); espelhado em **`python -m scripts.batch_pipeline`** (`draft-gate`, `run`). **Só** com exceção documentada — o destino canónico continua a ser YAML já no draft.
   - Corrigir **erros** do script no draft antes de avançar.
2. **Semântico:** adote **`.cursor/prompts/1b_DRAFT_GATE_SEMANTIC.md`** (PROMPT 1b) e **`converter/templates/DRAFT_GATE_CHECKLIST.md`**.

#### Guardrails do `draft_gate` (paridade `text_egps` ↔ draft)

O script **`converter/draft_gate.py`** valida alinhamento entre a saída do extrator e o rascunho:

| Verificação | Severidade | Notas |
|-------------|------------|--------|
| Existência de **`text_egps/[NOME_SEM_EXT].txt`** | **erro** se em falta | Correr **`python -m scripts.egps_extractor`** / PASSO 1 antes do gate. |
| Marcadores **`START_METADATA` / `END_METADATA`** no `.txt` | **aviso** se ausentes ou cabeçalho não parseável | Possível ficheiro corrompido ou extrator antigo. |
| Corpo SAS após `END_METADATA` muito pequeno | **aviso** | Deteta extração vazia ou truncada (limiar no código de `draft_gate.py`). |
| **`MIGRATION_SPEC.md`** no `draft_models/.../` (quando existe) | **erro** se **`TARGET_ARCH efetivo`** no spec ≠ arquitetura efetiva do **cabeçalho `.txt` + catálogo** (`target_arch_override` / `TARGET_ARCH`) | Regenerar o spec: `python -m scripts.generate_migration_spec "[NOME_SEM_EXT]"` após re-extração ou alinhar catálogo. |
| Mesmo spec: **`PROJECT (extrator)`** vs `PROJECT:` no `.txt` | **aviso** se divergirem | Spec desatualizado face ao extrator — regenerar ou corrigir. |
| Sem **`MIGRATION_SPEC.md`** no draft | **info** apenas | Não é possível validar paridade TARGET_ARCH/PROJECT até existir spec (fluxo antes do PASSO 1c). |
| **`staging_ref_map`** em modo `reuse_existing` / `hybrid` | **erro** se faltar `ref('...')` | Inalterado. |
| Tabelas **`DETECTED_TABLES_*`** vs texto do draft | **aviso** (heurística) em **DBT_BQ**; idem em **DATABRICKS** só com **`--parity-tables-all-arch`** | Não substitui revisão semântica. |
| **Três camadas + `materialized` no draft (DBT_BQ e DATABRICKS)** | **erro** se faltar **`models/staging/`**, **`intermediate/`** ou **`marts/`** com ≥1 `.sql`/`.py` cada, ou se algum modelo não tiver `materialized='…'` literal permitido por camada | `draft_layer_guard.check_draft_three_layers_and_materialization` (chamado por `draft_gate.py`). |
| **Paridade `stem.yml` no draft (DBT_BQ)** | **erro** se existir `draft_models/.../models/` com `.sql`/`.py` em **`intermediate/`** ou **`marts/`** sem ficheiro **`.yml` irmão** (mesmo stem) | `model_yml_guard.check_int_mart_yml_pairing`; **`--skip-int-mart-yml-pairing`** desliga. |
| **`draft_manifest` (MIGRATION_SPEC §9)** | **erro** se existir bloco YAML `draft_manifest` com **`models`** não vazio e algum par (`layer`, `stem`) **não** tiver `models/<layer>/<stem>.sql` ou `.py` no draft | `draft_gate.parse_draft_manifest_from_spec` + validação de disco; `models: []` ou ausência do bloco não gera erro por esta regra. |
| **`FILTERS_ORIGINAIS`** no `.txt` | **aviso** se faltar **`_FILTROS_APLICADOS.md`** no draft | Inalterado. |
| **PII em `stem.yml` (DBT_BQ)** | **erro** se coluna listada casar com `sensitive_data_types.yaml` sem `policy_tags` com `PII_INTERNO_*` permitido (inferido de `models/**/04_marts/**`, fallback documentado em `pii_reference.py`); **`PII_DADOS_CONFIDENCIAIS` sozinho não cumpre**; com **`--reference-interno-strict`** ou catálogo, reforço extra para tipos alvo (`STRICT_REFERENCE_ENTRY_IDS`) | Só quando existe sandbox/clone com `models/`; ver `pii_sensitive_yml_guard.py`. **`--skip-pii-yml`** desliga. |
| **Documentação `stem.yml` int/mart (DBT_BQ)** | **erro** se existir sandbox com `models/` e algum `stem.yml` for stub (ex.: `columns: []`, falta `meta.cron`, descrições curtas ou texto placeholder no modelo) | `yml_documentation_guard.py`. **`--skip-yml-doc`** desliga. |

Com **`--write-report`**, o ficheiro **`DRAFT_GATE_REPORT.md`** no draft inclui a secção **Paridade extrator ↔ spec/draft** com este resumo.

#### Ciclo de retry até o gate **mecânico** passar (teto: **5 tentativas**)

Objetivo: quando o draft **não** estiver alinhado com o `.txt` / catálogo / `MIGRATION_SPEC` ou faltar `ref`/artefactos exigidos pelo `draft_gate`, **repetir** (no mesmo pedido de conversão) correções + **`python -m scripts.draft_gate "[NOME_SEM_EXT]"`** até o gate sair **sem erros** na lista do script.

**Contagem do teto:** **5 tentativas totais** de executar o gate mecânico com sucesso (sem erros). **Tentativa 1** = primeira corrida do `draft_gate` após o draft inicial. Se houver **erros**, corrigir (PASSO 2 e/ou 1c conforme abaixo), depois **tentativa 2**; repetir até **tentativa 5**. Se na **quinta** execução ainda houver **erros**, **parar** antes do PASSO 3 e pedir decisão ao utilizador (não assumir “OK para governança”).

**Falha pós‑cópia no clone (Regra A):** mesmo que o `draft_gate` fique OK, se após copiar para `converted_egps/...` e para `models/.../migracao_sas/<EGP_SLUG>/` o comando **`python -m scripts.batch_pipeline checks --batch-file <1 linha> --strict`** falhar (ex.: ausência de `models/`, falta de YAML par, inconsistências na saída convertida), isso **conta como falha da tentativa** e o EGP deve ser refeito até o teto de **5**.

**O que fazer após cada falha (erros do gate), por prioridade:**

1. **Paridade spec ↔ extrator** (`TARGET_ARCH efetivo`, `PROJECT`, `.txt` em falta): **`python -m scripts.generate_migration_spec "[NOME_SEM_EXT]"`** com `text_egps/...txt` atualizado (re-extração se necessário, PASSO 1); em seguida **PASSO 2** onde o código ainda não cumprir o spec ou o catálogo.
2. **`Paridade stem.yml (draft)`** (mensagens com `models/intermediate/...` ou `models/marts/...`): criar **`stem.yml` irmão** por modelo (**AGENTE 1**) ou ponto de partida com **`python -m scripts.scaffold_int_mart_yml --draft-root draft_models --egp-key "[NOME_SEM_EXT]"`** / **`python -m scripts.batch_pipeline run … --scaffold-yml`**; **não** usar `--skip-int-mart-yml-pairing` salvo exceção documentada.
3. **`staging_ref_map` / `ref()` em falta:** completar os `ref('...')` no draft (PASSO 2).
4. **Três camadas / `materialized`:** criar `models/staging/` com `stg_*` (wrappers em `reuse_existing` se necessário), garantir `intermediate/` e `marts/`, e `materialized='ephemeral'` / `'table'` (ou `materialized="view"` só em staging **DATABRICKS`) em cada `.sql`/`.py` conforme a mensagem do gate.
5. **`draft_manifest` (§9):** alinhar lista `models` no `MIGRATION_SPEC.md` aos ficheiros reais no draft (ou criar os ficheiros em falta).
6. **Outros erros** (ex.: sem `.sql`/`.py` quando obrigatório): corrigir no PASSO 2 ou no spec conforme a mensagem do gate.

Recomendado: **`--write-report`** em cada **`python -m scripts.draft_gate`** para rasto em **`DRAFT_GATE_REPORT.md`**.

**Avisos** (sem erros na lista): **não** consomem uma “tentativa” do teto para efeitos de retry **obrigatório**; trate-os no gate **semântico** (PROMPT 1b). Se usar **`--strict`**, trate cada reexecução após corrigir avisos como uso do mesmo **teto de 5 tentativas** (priorize eliminar a causa ou documente exceção — sem loops indefinidos).

**Modo lote:** por `egp_key`, o mesmo **teto de 5 tentativas** do gate mecânico (e, para fecho do EGP, `checks --strict` conforme Regra A); se esgotar, marcar o EGP como bloqueado no resumo e seguir conforme política acordada com o utilizador.

---

### PASSO 3A: Refinamento e governança (sandbox / `converted_egps/`)

1. Adote **`.cursor/prompts/2_GOVERNANCE_ENGINEER.md`** (AGENTE 2). Regras: **`01_sas_to_dbt.mdc`** ou **`02_sas_to_databricks.mdc`** conforme `TARGET_ARCH`.
2. No início do 3A, calcular **`[DATA_CONVERSAO]_[ULTIMO_COMMIT]_[TARGET_ARCH]`** (data local + `git rev-parse --short HEAD` em `converter/` + `dbt`|`databricks` conforme o alvo). Refatore para **`converter/converted_egps/[DATA_CONVERSAO]_[ULTIMO_COMMIT]_[TARGET_ARCH]/[NOME_SEM_EXT]/`**; copiar **`MIGRATION_SPEC.md`** para a raiz do sandbox. (Se existir sandbox **legado** `converted_egps/[TARGET_ARCH]/[NOME_SEM_EXT]/`, os scripts continuam a encontrá-lo; só crie o layout novo para conversões novas salvo instrução explícita em manter legado.)
   - **Formato do sandbox:** manter **somente** `models/staging/`, `models/intermediate/`, `models/marts/` (não copiar `models/steps/` para o sandbox).
   - **Staging (DBT_BQ):** proibido qualquer `JOIN` em `models/staging/*.sql` (staging = 1 fonte / primeira conexão). Enforce com: `python -m scripts.check_staging_no_join "[NOME_SEM_EXT]"`.
   - **Regra passthrough (DBT_BQ):**
     - **`staging/`**: conter **apenas** as tabelas-base do passthrough (primeira conexão/fonte), como `stg_*`.
     - **`intermediate/`**: conter o **SQL inteiro** do passthrough reescrito sobre `{{ ref('stg_*') }}`.
     - **`WORK.*`**: se for temporário/local, virar **CTE** dentro do `int_*`; se for reutilizado/compartilhado, virar **modelo `int_*`**.
   - **Proibido no sandbox:** qualquer `ref('step_')` (steps devem ser incorporados/inline nas CTEs do `intermediate`, com nomes semânticos). Enforce com: `python -m scripts.check_no_step_ref_in_sandbox "[NOME_SEM_EXT]"`.
   - **Marts (DBT_BQ):** 1 mart por output real do SAS (exports / libref permanente / `PERMANENT OUTPUTS`). Proibido mart duplicada por assinatura. Enforce com: `python -m scripts.check_no_duplicate_marts "[NOME_SEM_EXT]"`.
3. **Gate IA (obrigatório, mesmo com scripts OK):** aplicar `templates/AI_VALIDATION_CHECKLIST.md` (3A) e bloquear se staging tiver JOIN/2 fontes, se passthrough não estiver no padrão `stg_*` + `int_*`, se houver marts duplicadas/sem output real, ou se existir `ref('step_')` no sandbox.
4. Rodar **`python -m scripts.auto_fixer "<sandbox>/models"`** quando `TARGET_ARCH=DBT_BQ` (ver PASSO 4) e ajustar artefactos resultantes.
5. **Labels de governança (determinístico, DBT_BQ):** com cwd na raiz **`converter/`**, após existirem `models/intermediate/` e `models/marts/` no sandbox, executar **`python -m scripts.apply_governance_config "[NOME_SEM_EXT]"`** (resolve automaticamente sandbox legado ou `…/<DATA>_<sha>_dbt|databricks/…`). O script **injeta** `config` completo quando faltam `labels` ou **actualiza in-place** `nm_engenheiro_responsavel_pela_transformacao`, `nm_grupo_de_acesso` e **`fl_modernizacao_legacy`** (sempre **`'false'`**; corrige valores antigos **`'true'`**). **`nm_delivery_legacy`** **não** é inferido pelo script: o Agente 2 (governança semântica) deve preencher conforme `01_sas_to_dbt.mdc` §4 (formato `sas__<tabela>` minúsculo, sem `[SAS]`/libref/`WORK.`, com a tabela SAS/WORK principal); o inject pode deixar vazio como último recurso até essa correção. Engenheiro: **`--engineer`** → **`CONVERTER_ENGINEER`** → `registry/user_profile.local.yaml` (`engineer:`) → `int_unknown`. Grupo: **`pdbd_gcp-<workspace_subdir>-dados_interno`** (segmento após `workspace/` no layout do componente), inferido de **`dbt_clone_dest`** no `MIGRATION_SPEC.md`, ou do caminho passado em **`--models-root`**, ou via catálogo + clone dbt; excepção: **`--nm-grupo-de-acesso`** / **`CONVERTER_NM_GRUPO_DE_ACESSO`**. Se for preciso alinhar só o clone depois de uma cópia antiga: **`--models-root "[DBT_CLONE_DEST]" --spec "converted_egps/<DATA>_<sha>_dbt/<egp_key>/MIGRATION_SPEC.md"`** (caminho explícito; legado: `converted_egps/dbt/<egp_key>/MIGRATION_SPEC.md`).
6. Rodar **`python -m scripts.batch_pipeline checks --batch-file <ficheiro com 1 egp_key> --strict`** e só considerar o 3A OK se passar.
   - Em **DBT_BQ**, o passo **5** (`apply_governance_config`) deve ter corrido **antes** deste `checks`.
7. **Definição de “governança concluída” (DBT_BQ):** não avançar ao 3B nem ao PASSO 4/5 se `…/[NOME_SEM_EXT]/models/marts/` no **sandbox resolvido** (legado ou `…/<DATA>_<sha>_dbt/…`) estiver ausente/vazio.
   - Se falhar, repetir o 3A (ajustes + regeneração dos artefactos necessários) no máximo **3x**; se na 3ª tentativa ainda não houver marts, **parar** o EGP como bloqueado (não “pular” etapa).

---
### PASSO 3B: Publicação no componente (clone dbt)

1. **Clone:** copiar **apenas** o `models/` do sandbox (staging/intermediate/marts + YAMLs coerentes) para **`[DBT_CLONE_DEST]`** (PASSO 1b), em `models/.../migracao_sas/<EGP_SLUG>/`.
   - **Regra:** nunca copiar diretamente do `draft_models/` para o clone.
   - **Ordem:** em DBT_BQ, o PASSO 3A item **5** (`apply_governance_config` no sandbox) deve ter corrido **antes** desta cópia, para que `intermediate/` e `marts/` levem ao componente os labels finais (`nm_engenheiro_*`, `nm_grupo_de_acesso` no formato `pdbd_gcp-<workspace_subdir>-dados_interno`, `fl_modernizacao_legacy` a **`false`**, e `nm_delivery_legacy` já preenchido pelo Agente 2 no formato `sas__<tabela>` onde aplicável).
   - **Sanity check (bloqueio):** antes de copiar, executar `python -m scripts.check_no_step_ref_in_sandbox "[NOME_SEM_EXT]"` e falhar se houver `ref('step_')` no sandbox.
2. **Verificador pós-publicação (obrigatório):** executar o micro-papel `.cursor/prompts/3b_COMPONENT_PUBLISH_VERIFIER.md` para comparar sandbox → clone (apenas `intermediate/` + `marts/`) e validar o coverage gate quando aplicável. **Persistir** o relatório em: `converted_egps/<DATA>_<sha>_<target>/<egp_key>/COMPONENT_PUBLISH_VERIFICATION_REPORT.md` (ou legado `converted_egps/<target>/<egp_key>/…`) com `**Overall:** PASS|FAIL`.
3. Rodar novamente **`python -m scripts.batch_pipeline checks --batch-file <1 egp_key> --strict`** após a cópia.
   - Com `--strict`, o pipeline falha se o report do PASSO 3B estiver ausente/FAIL quando aplicável (`component_publish_ok`).
4. Se falhar, tratar como falha pós-cópia (Regra A / retry do pipeline).
5. Atualizar **`DE_PARA_TIPAGEM.md`** com secção **Filtros (WHERE)** e nota com **`[DBT_REPO_ROOT]`** / **`[DBT_CLONE_DEST]`**.

---

### PASSO 4: Validação condicional e finalização

- **DBT_BQ:** `python -m scripts.auto_fixer "<caminho>/models"` na pasta **models** do sandbox ou clone (ver README); reaplicar cópia ao clone se alterar ficheiros. Opcional: **`dbt parse`** no clone — **nunca** `dbt build` (guardrail operacional).
- **DBT_BQ (config):** remover `alias=` de `config()` em `intermediate/` e `marts/` (padrão do time: não usar alias nos modelos). Use:
  - `python -m scripts.remove_dbt_config_alias --root "converted_egps/<DATA>_<sha>_dbt/<egp_key>/models"` (ou caminho legado `converted_egps/dbt/<egp_key>/models`)
  - (após copiar para o clone) `python -m scripts.remove_dbt_config_alias --root "[DBT_CLONE_DEST]"`
  - Se alterar ficheiros no clone, reaplique a cópia do sandbox (ou execute a remoção também no sandbox antes do rsync/cópia).
- **Chamados (artefacto obrigatório):** gerar `CHAMADOS_CONVERSAO.md` no sandbox para facilitar abertura de chamados:
  - `python -m scripts.generate_chamados_conversao "<egp_key>"`
- **Paridade intermediate/mart ↔ `.yml` (guardrail mecânico):** `python -m scripts.batch_pipeline checks --batch-file registry/egp_keys_batch.txt` preenche `batch_checks` com **`draft_three_layers_ok`** (staging + intermediate + marts no draft com `materialized` literal, quando `TARGET_ARCH` é **DBT_BQ** ou **DATABRICKS** no `.txt` **e** o draft **não** está no modo **flow-only**), **`draft_flow_gate_ok`** (quando o draft está em **`draft_models/<egp>/models/NN_*.sql`** sem as 3 pastas canónicas), **`flow_coverage_ok`** (no modo flow-only, quando `.txt` tem **PERMANENT OUTPUTS + EXPORTED FILES**, exige `## Coverage` no relatório IA registrando os dois), **`draft_yml_pairing_ok`** (paridade no **draft** sob `draft_models/.../models`, quando `TARGET_ARCH: DBT_BQ` no `.txt`) e **`yml_pairing_ok`** (saída **convertida**). Com **`--strict`**, exit 1 se qualquer um dos KPIs aplicáveis falhar (ver `README.md`).
- **PII nos `stem.yml` (DBT_BQ):** o mesmo `checks` valida `pii_sensitive_yml_ok` — colunas declaradas nos YAML que casam com `registry/sensitive_data_types.yaml` devem ter `policy_tags` com `PII_INTERNO_*` permitido (referência `04_marts` + fallback; `pii_sensitive_yml_guard.py`; `draft_gate.py` idem salvo `--skip-pii-yml`). Com **`pii_reference_interno_strict`** no catálogo ou **`--reference-interno-strict`** no CLI, aplica-se o modo estrito adicional (ver PASSO 2b).
- **Documentação `stem.yml` int/mart (DBT_BQ):** o mesmo `checks` preenche `yml_documentation_ok` — cada `stem.yml` existente deve cumprir regras mínimas (`yml_documentation_guard.py`; salvo `--skip-yml-doc`). Com **`--strict`**, exit 1 se falhar (alinhado a `README.md`).
- **DATABRICKS:** não usar **`python -m scripts.auto_fixer`**; validar template Python; reaplicar cópia ao clone se necessário.
- **`draft_models/`:** **não apagar** por defeito — manter até **PASSO 5** concluído e auditoria aceite, ou instrução explícita do utilizador. Ver **Ciclo de vida de `draft_models/`** no topo deste ficheiro.

---

### PASSO 5: Auditoria de migração

1. Adote **`.cursor/prompts/3_MIGRATION_AUDITOR.md`** (AGENTE 3) e a regra **`.cursor/rules/03_migration_auditor.mdc`**.
2. Gerar **`AUDITORIA_*.md`** no sandbox (`converted_egps/<DATA>_<sha>_dbt|databricks/<nome>/`, ou legado `converted_egps/dbt|databricks/<nome>/`), com espaços normalizados no nome do ficheiro.
3. **Entradas:** além de `text_egps/...` e `converted_egps/...`, pode usar **`draft_models/[NOME_SEM_EXT]/`** (opcional) para paridade spec/filtros vs. código final — ver AGENTE 3. Se existir **`DRAFT_GATE_REPORT.md`** nessa pasta (PASSO 2b com `--write-report`), use-o só como **contexto** das checagens mecânicas já feitas; a auditoria continua a ser **semântica** (SAS ↔ sandbox final, governança 01/02, riscos), sem repetir como falha nova o que o `draft_gate` já sinalizou, salvo alterações ao código ou ao spec **depois** do gate.
4. **Relatório (estrutura obrigatória da regra):** imediatamente após o título, **Metadados de execução** (`**modo_lote:**` `sim`|`não`; se lote, **`ficheiro_lote:`** obrigatório quando conhecido). Secção obrigatória **`## Pontos de alto risco (revisão humana)`** com tabela (estados Revisado / Pendente / N/A) e **coerência** com o **Resumo** (qualquer **Pendente** em alto risco impede “OK” em todas as áreas — ver regra). Depois: **Pré-checagens** (opcional), **Resumo**, **Paridade**, **Governança**, **Riscos**, **Recomendações**. **Não** recomendar apagar **`draft_models/`** por defeito (política em **Ciclo de vida de `draft_models/`** no topo deste ficheiro). Template opcional: **`converter/templates/AUDITORIA_HIGH_RISK_SECTION.template.md`**.

---

### PASSO 6: Saída esperada

**Um EGP** — ao final, apresente:

1. **Resumo do que foi criado (sandbox):** lista de arquivos finais em `converted_egps/<DATA>_<sha>_[dbt|databricks]/[NOME_SEM_EXT]/` (ou legado `converted_egps/[dbt|databricks]/[NOME_SEM_EXT]/`), incluindo **`MIGRATION_SPEC.md`** na raiz do projeto (rastreabilidade).
2. **Integração no clone:** caminho **`[DBT_CLONE_DEST]`** e confirmação de que a cópia foi feita.
3. **Confirmações:** (1) extração e catálogo/`resolve`, (2) **`python -m scripts.draft_gate`** (PASSO 2b mecânico) e checklist semântica, (3) arquivos gerados e DE_PARA_TIPAGEM.md, (4) linting quando for dbt (sandbox e, se aplicável, clone), (5) auditoria e local do relatório (`AUDITORIA_*.md` no sandbox). (6) Se a política padrão for seguida, **`draft_models/`** permanece até após auditoria aceite.

**Modo lote** — após tratar todos os EGPs da lista (ou a sublista acordada), apresente o **resumo agregado** (tabela EGP × estado × links para `AUDITORIA_*.md`) e indique se **`python -m scripts.batch_pipeline`** / **`batch_manifest.json`** foi atualizado. **Verificação rápida:** confirmar que cada `AUDITORIA_*.md` do lote contém **`modo_lote: sim`**, **`ficheiro_lote:`** e a secção **Pontos de alto risco** (regra `03_migration_auditor.mdc`). Opcional: correr **`python -m scripts.batch_pipeline checks`** e **`python -m scripts.batch_pipeline batch-audit`** para consolidar `BATCH_AUDIT.md` e `batch_checks`.

---

## Referências

- **Micro-papéis (tabela + disciplina de contexto):** secção **Micro-papéis** no topo deste ficheiro.
- **Catálogo EGP e resolução da raiz dbt:** `registry/egp_catalog.yaml`, `python -m scripts.bootstrap_egp_catalog` (subcomandos `scan`, `add`, `resolve`, `governance-cd`, `ensure-repo`). Mapa **`area` → `componente_dbt` + git:** `registry/area_componente_dbt.yaml` (modelo: `area_componente_dbt.example.yaml`). Mapa **`area` → `cd_governanca`:** `registry/area_cd_governanca.yaml` (modelo: `area_cd_governanca.example.yaml`). **`MIGRATION_SPEC`:** código em `scripts/generate_migration_spec.py`; invocação **`python -m scripts.generate_migration_spec`**; modelo `templates/MIGRATION_SPEC.template.md`. **Gate pós-draft:** `python -m scripts.draft_gate`, `scripts/yml_documentation_guard.py`, `templates/DRAFT_GATE_CHECKLIST.md`, `registry/egp_keys_batch.example.txt`. **Lote:** `python -m scripts.batch_pipeline`, `registry/batch_manifest.json`, `registry/BATCH_AUDIT.md`. **Layout sandbox / resolução de paths:** `scripts/sandbox_layout.py` (`find_converted_sandbox`, `sandbox_run_dir_name`, `expected_sandbox_run_parent`). **Operação (entrada / extração / área / batch):** `README.md` (secções **Pré-batch**, **Visão rápida** — bullets Entrada/Extração — e **Execução (modo lote)**). **`draft_models/`:** secção **Ciclo de vida de `draft_models/`** neste ficheiro.
- **Guardrails operacionais:** `.cursor/rules/04_pipeline_operational_guardrails.mdc` (proibição de `dbt build`, `git commit`, `git push`).
- **Config por utilizador + labels determinísticos:** opcionalmente criar `registry/user_profile.local.yaml` (ignorado no git) com `engineer: int_seu_usuario`. **`python -m scripts.apply_governance_config`** (PASSO 3A.5) usa esse valor (ou `CONVERTER_ENGINEER` / `--engineer`) para `nm_engenheiro_responsavel_pela_transformacao`, define `nm_grupo_de_acesso` como **`pdbd_gcp-<workspace_subdir>-dados_interno`**, e normaliza **`fl_modernizacao_legacy`** para **`false`** (ver docstring do script); **`nm_delivery_legacy`** não é preenchido pelo script — ver `01_sas_to_dbt.mdc` §4. Excepção grupo: `--nm-grupo-de-acesso` / `CONVERTER_NM_GRUPO_DE_ACESSO`.
- **Prompts (micro-papéis LLM):** `.cursor/prompts/0_MIGRATION_SPEC.md`, `1_LOGIC_TRANSLATOR.md`, `1b_DRAFT_GATE_SEMANTIC.md`, `2_GOVERNANCE_ENGINEER.md`, `3_MIGRATION_AUDITOR.md`
- **Regras de governança:** `.cursor/rules/01_sas_to_dbt.mdc` (DBT_BQ) e `.cursor/rules/02_sas_to_databricks.mdc` (DATABRICKS)
- **Auditoria:** regra `.cursor/rules/03_migration_auditor.mdc`