# Codex Instructions — Godot Testrunner MCP

## Delegation (Token Saving)

See `/Users/kognido/.shared/routing.md` for delegation rules.
Tools: `delegate-read`, `delegate-write`, `extract-chat`.

**Never delegate:** debugging, architecture decisions, tasks under ~2000 tokens.

**Subagent layering rule:** Within subagent-driven execution, use `delegate-read` for bulk reads and `delegate-write` for test/boilerplate before dispatching full Claude subagents.
