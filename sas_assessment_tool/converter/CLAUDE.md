# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cursor AI Compatibility

This project uses Cursor AI conventions. Claude Code acts as a drop-in replacement. The `.cursor/` directory is the **single source of truth** for all project rules, agent personas, and skills. Never modify files there unless explicitly asked to update project configuration.

### Rules — `.cursor/rules/`
Before any task that involves generating or reviewing code, scan all `.mdc` files in `.cursor/rules/` and load the ones relevant to the task based on their YAML frontmatter:
- `alwaysApply: true` → load for every task in this project
- `globs: [...]` → load when working with files matching those patterns
- Neither field set → use the `description` to judge relevance

Read each applicable rule in full before producing any output.

### Skills — `.cursor/skills/`
All available skills are defined as `SKILL.md` files inside `.cursor/skills/*/`. When a user invokes `/skill-name`, locate the matching subdirectory and follow its instructions exactly. To discover what skills exist, list `.cursor/skills/`.

### Personas — `.cursor/prompts/`
Agent personas live in `.cursor/prompts/`. Individual skills reference these files and instruct when to load them — do not load a persona unless a skill explicitly tells you to.

### Auto-lint hook
A `PostToolUse` hook (configured in `.claude/settings.json`) automatically runs SQLFluff on any `.sql` file written outside `draft_models/`. No manual linting action is needed after writing SQL.

---

## Project Purpose

This is a **SAS Enterprise Guide (EGP) to Modern Data Stack Migration Tool**. It automates the extraction of SAS code from `.egp` project files and converts it to either **dbt/BigQuery (SQL)** or **Databricks/PySpark (Python)**, depending on detected complexity.

## Commands

### Extract a SAS EGP file
```bash
python egps_extractor.py "received_egps/[NAME].egp"
# Output: text_egps/[NAME].txt
```

### Analyze complexity & effort estimation
```bash
python egp_analysis.py
# Scans ./egps/ → outputs saida_tasks/*_resumo.txt
```

### Lint and auto-fix SQL (DBT_BQ only)
```bash
python auto_fixer.py converted_egps/dbt/[NAME]/models
```

### Install dependencies
```bash
pip install -r requirements.txt
```

### Interact with GitHub (PR, comments, branches, CI)
```bash
python tools/github_tools.py <subcommand> [options]
# Subcommands: create-pr, get-pr, list-prs, list-comments, add-comment, list-branches, pipeline-status
# Requires env vars: GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME
```

### Interact with BigQuery (query, inspect tables/datasets)
```bash
python tools/bigquery_tools.py <subcommand> [options]
# Subcommands: query, dry-run, list-datasets, list-tables, get-table
# Required env var: GCP_PROJECT_ID
# Auth: set GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  OR  run `gcloud auth application-default login`
# Optional env var: GCP_DATASET (default dataset; lets you omit --dataset)
```

## Architecture & Key Modules

### `egps_extractor.py`
Core extraction engine (~1,900 lines). Opens `.egp` files (ZIP format), parses task dependency graphs via topological sort, and emits a metadata header followed by the full extracted code.

**Complexity scoring (0–100):** score ≥ 70 → `TARGET_ARCH: DATABRICKS`; < 70 → `DBT_BQ`. Hard blockers (`PROC IML`, `PROC PYTHON`) force score to 100.

**Key metadata fields in `text_egps/[NAME].txt`:** `TARGET_ARCH`, `TRIGGERS`, `DETECTED_TABLES_HARDCODED`, `DETECTED_MACROS_USED/DEFINED`, `HAS_PASSTHROUGH`, `DETECTED_PROCS`, `FILE_REFERENCES_SUMMARY`, `FILTERS_ORIGINAIS`.

### `egp_analysis.py`
Lightweight complexity/effort scorer. Classifies projects as P/M/G/GG and estimates person-hours. Does not produce converted code.

### `auto_fixer.py`
SQLFluff wrapper. 3-phase cycle: lint → fix (`--force`) → re-lint. Only applies to SQL (DBT_BQ targets).
