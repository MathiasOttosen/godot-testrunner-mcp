@agents.nano.md

## Delegation (Token Saving)

See `/Users/kognido/.shared/routing.md` for delegation rules.
Tools: `delegate-read`, `delegate-write`, `extract-chat`.

**Never delegate:** debugging, architecture decisions, tasks under ~2000 tokens.

**Subagent layering rule:** Within subagent-driven execution, use `delegate-read` for bulk reads and `delegate-write` for test/boilerplate before dispatching full Claude subagents.

## Scope loading

- `[nano]` — agents.nano.md. Simple tool calls, diagnostics.
- `[min]` — + agents.min.md + .rules/efficiency.md. Active testing sessions.
- `[full]` — + README.md + relevant server.py sections. Deep debugging, server modifications.

## Scoped rules

- `.rules/efficiency.md` — always loaded with min+. Cost-efficient MCP usage patterns.
