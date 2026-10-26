#!/usr/bin/env python3
"""
Post-file-edit hook for Claude Code.
Mirrors Cursor's afterFileEdit hook: runs SQLFluff fix on any .sql file
that was just written, except files inside draft_models/.

Claude Code PostToolUse hooks receive a JSON payload on stdin:
  {"tool_name": "...", "tool_input": {"file_path": "..."}, ...}
"""
import sys
import json
import subprocess


def get_file_path():
    try:
        payload = json.load(sys.stdin)
        return payload.get("tool_input", {}).get("file_path", "")
    except Exception:
        return ""


def should_lint(filepath):
    if not filepath:
        return False
    normalized = filepath.replace("\\", "/")
    return normalized.endswith(".sql") and "converted_egps/dbt" in normalized


def main():
    filepath = get_file_path()
    if should_lint(filepath):
        subprocess.run(
            ["sqlfluff", "fix", filepath, "--dialect", "bigquery", "--force"],
            capture_output=True,
            text=True,
        )
    sys.exit(0)  # Always exit 0 — never block file writes


if __name__ == "__main__":
    main()
