
```question
We've been developing tools for this project. What I see as result is roughly python scripts and skills
teaching how to use them. I see it works, but when I read the Cursor AI documentation about tools,
I see one is supposed to declare a JSON with the tool name, description and parameters (see the example
below), but I can't find something like that in our developments. I want to understand that a little
better. Are we taking a different approach on making tools? Are they equivalent? What are the pros and
cons of each? Is there any particular approach that is recommended? Why?

{
  "name": "read_file",
  "description": "Read the contents of a file from the codebase",
  "parameters": {
    "filepath": "The path to the file to read"
  }
}
```

---

# Two Approaches to AI Tools

## What the JSON declaration actually is

The JSON schema in the Cursor docs is the **MCP (Model Context Protocol) / function-calling** format.
It describes a tool so that the AI model itself can invoke it via structured output — the AI emits a
JSON payload, a framework intercepts it, runs the actual code, and returns the result.

```
AI → emits structured JSON → framework executes code → returns result to AI
```

## What we built

Our approach uses **CLI scripts + SKILL.md documentation**:

```
AI → writes a bash command string → shell executes it → AI reads stdout
```

The AI never calls `bigquery_tools.py` "natively" — it uses its `Bash` tool to construct and run
`python tools/bigquery_tools.py query --sql "..."`, then reads the JSON output.

The SKILL.md files are not tool declarations — they are **user manuals** that teach the AI which
commands to run and what to expect back.

---

## Comparison

| | MCP / JSON tools | Our CLI approach |
|--|--|--|
| **Invocation** | AI emits structured JSON; framework executes | AI writes a bash string; shell executes |
| **Discovery** | AI sees the schema automatically | AI reads SKILL.md to learn the interface |
| **Type safety** | Parameters are typed and validated by the schema | Parameters are strings; argparse validates them |
| **Setup** | Requires an MCP server running and registered | Just needs Python and a shell |
| **Usable by humans** | No — agent-only interface | Yes — developers can run the same commands |
| **Portability** | Tied to the MCP protocol | Works in any shell, CI, or agent with Bash access |
| **Error handling** | Structured error responses | Stderr + exit codes |

---

## Are they equivalent?

Functionally yes — both let an AI interact with external services. But the abstraction level differs.
MCP tools feel more like calling a function; CLI tools feel more like typing a command.

---

## Which is recommended?

**For production AI agent systems** (APIs, autonomous pipelines, multi-agent frameworks): JSON/MCP tools
are preferred — structured I/O, composable, no shell dependency, works across any LLM that supports
tool calling.

**For developer-facing tooling like this project**: the CLI approach is the right call, for three
reasons:

1. **Dual audience** — a human analyst can run `python tools/bigquery_tools.py list-tables --dataset raw`
   directly. An MCP tool can't be called from a terminal.
2. **No infrastructure** — MCP requires a server process registered in Cursor/Claude settings.
   A Python script just runs.
3. **Claude Code's native pattern** — Claude Code's own interface IS the Bash tool. Our tools are
   designed exactly for how Claude Code operates.

---

## Future path

If this project ever moves toward a fully autonomous agent architecture (e.g., LangGraph or CrewAI),
wrapping the CLI scripts in MCP tool declarations would be the natural next step — the scripts
themselves wouldn't need to change, just the interface layer on top.
