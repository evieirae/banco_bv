---
name: text-egp-excel-batch-unify
description: >-
  Executa o lote Cursor Agent sobre ficheiros em text_egps (documentação Excel)
  e, após o término do comando, agrega respostas_text_egp em mapeamento_projetos.csv.
  Usar quando o utilizador pedir lote text_egps, respostas_text_egp,
  mapeamento_projetos, lote Excel, unify_response_txt ou cursor_agent_text_egp_batch.
disable-model-invocation: true
---

# Lote texto EGP + unificação CSV

## Relação com o orquestrador

A skill **orchestrator** governa o **pipeline de migração EGP** (micro-papéis 1–6). **Esta skill é um fluxo auxiliar** (documentação Excel em lote + CSV de mapeamento). Não substitui nem duplica o orquestrador; não misturar os dois roteiros na mesma invocação salvo o utilizador pedir explicitamente.

## Quando usar

- Correr o batch do Agent sobre `.txt` em `text_egps/` com o template de Excel/CSV.
- Depois gerar ou atualizar `mapeamento_projetos.csv` a partir das respostas em `respostas_text_egp/`.

## Pré-requisitos

1. **Diretório de trabalho:** raiz do repositório **`converter/`** (todos os comandos abaixo assumem `cwd` aqui).
2. **Cursor Agent CLI:** instalado e autenticado; se falhar, seguir as mensagens de erro do script (`agent login`, `CURSOR_API_KEY`, `--agent`, etc.).
3. **Ficheiros/pastas por defeito:** `prompt-egp-excel-csv.txt`, pasta `text_egps/` com `.txt`; saída em `respostas_text_egp/` (prefixo `REPROCES__`). Ajustar com flags se o utilizador indicar outros paths.

## Passos (ordem fixa)

### 1. Lote Agent (texto EGP → respostas)

```bash
python -m scripts.cursor_agent_text_egp_batch
```

Flags úteis:

- `--no-skip` — reprocessar mesmo se `REPROCES__*.txt` já existir.
- `--input-dir` — pasta de `.txt` (default: `text_egps`).
- `--output-dir` — pasta de saída (default: `respostas_text_egp`).
- `--template` — ficheiro de instruções (default: `prompt-egp-excel-csv.txt`).
- `--workspace` — valor de `--workspace` do CLI (default: diretório atual).
- `--agent` — caminho explícito para `agent` / `agent.cmd`.

**Nota:** o script pode terminar com código **0** mesmo quando alguns ficheiros falham no loop (`[FAIL]` / `[ERR]`). Se o utilizador exigir rigor, rever o output do terminal antes de confiar no CSV.

### 2. Unificação para CSV

Só **depois** do comando do passo 1 **terminar**:

```bash
python -m scripts.unify_response_txt
```

(Alternativa equivalente: `python scripts/unify_response_txt.py` — preferir `-m` por consistência com o resto do repo.)

## Pós-condição

- CSV gerado na cwd do `converter/`: **`mapeamento_projetos.csv`** (delimitador `;`, UTF-8 com BOM).
- O unify **ignora** ficheiros em `respostas_text_egp/` que não contenham a secção `--- DOCUMENTAÇÃO EXCEL ---` (o script imprime aviso e continua).

## Nota (Windows)

Se `python -m scripts.unify_response_txt` falhar com `UnicodeEncodeError` no terminal (consola em cp1252), forçar UTF-8 na saída, por exemplo: `PYTHONIOENCODING=utf-8 python -m scripts.unify_response_txt`.

## Guardrails operacionais

Alinhar a `.cursor/rules/04_pipeline_operational_guardrails.mdc` quando aplicável: **não** executar `git commit`, `git push` nem `dbt build` como parte deste fluxo.
