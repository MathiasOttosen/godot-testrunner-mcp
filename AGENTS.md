# Godot Testrunner MCP — Codex Context
*Python FastMCP server · Project-agnostic Godot test infrastructure*

---

## What this MCP is

Python FastMCP server that gives agents structured access to Godot 4 projects:
run tests, inspect scenes, capture screenshots, query runtime state,
compare visual output. Works headless or with the editor open.

Server path: `server.py` in this repo root.

## How to set up for any project

```bash
# Required: point at your target Godot project
export GODOT_PROJECT=/path/to/your/godot/project
export GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot
```

If `GODOT_PROJECT=/` or unset, the server falls back to searching upward from
cwd for `project.godot`.

## Delegation (Token Saving)

See `/Users/kognido/.shared/routing.md` for delegation rules.
Tools: `delegate-read`, `delegate-write`, `extract-chat`.

**Never delegate:** debugging, architecture decisions, tasks under ~2000 tokens.

**Subagent layering rule:** Within subagent-driven execution, use `delegate-read` for bulk reads and `delegate-write` for test/boilerplate before dispatching full Claude subagents.
