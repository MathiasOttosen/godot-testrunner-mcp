@agents.nano.md

## Delegation (Token Saving)

See `/Users/kognido/game-dev/.shared/routing.md` for delegation rules.
Tools: `delegate-read`, `delegate-write`, `extract-chat`.

**Never delegate:** debugging, architecture decisions, tasks under ~2000 tokens.

## Scope loading

- `[nano]` — agents.nano.md. Simple tool calls, diagnostics.
- `[min]` — + agents.min.md + .rules/efficiency.md. Active testing sessions.
- `[full]` — + README.md + relevant server.py sections. Deep debugging, server modifications.

## Scoped rules

- `.rules/efficiency.md` — always loaded with min+. Cost-efficient MCP usage patterns.
