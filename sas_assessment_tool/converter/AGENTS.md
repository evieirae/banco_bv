# AGENTS.md

Cursor AI entry point for this project. For Claude Code, see `CLAUDE.md`.

## How this project is organized

All agent behavior is defined in `.cursor/`:

| Directory | Contents |
|---|---|
| `.cursor/rules/` | `.mdc` rule files — applied by frontmatter (`alwaysApply`, `globs`, `description`) |
| `.cursor/prompts/` | Agent personas — loaded by skills when needed |
| `.cursor/skills/` | Invocable skills — each subdirectory has a `SKILL.md` |

To see available skills, list `.cursor/skills/`. To invoke one: `/skill-name`.

## Input / Output directories

| Path | Role |
|---|---|
| `received_egps/` | Input: raw `.egp` files |
| `text_egps/` | Extracted metadata + code (output of extraction step) |
| `draft_models/[NAME]/` | Temporary draft — deleted after validation step |
| `converted_egps/dbt/[NAME]/` | Final dbt/BigQuery output |
| `converted_egps/databricks/[NAME]/` | Final Databricks/PySpark output |
