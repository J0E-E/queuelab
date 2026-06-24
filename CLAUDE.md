# CLAUDE.md

<!-- code-review-graph tool binding -->
## Code navigation — code-review-graph

**WHERE / current code structure** — definitions, callers, callees, imports, blast-radius,
test coverage → use the **code-review-graph MCP tools first**, before Grep/Glob/Read.

**Make the graph call first and on its own.** Read what it returns, *then* fall back to
Grep/Glob/Read only for what the graph doesn't index (config, logs, strings) or when it misses.
Do **not** run a file search in the same parallel turn as the graph call — the graph decides
whether a file scan is even needed, so it cannot be "independent" work you batch alongside Grep.

**These tools are deferred** — load them with `ToolSearch` (query `code-review-graph`, or
`select:mcp__code-review-graph__query_graph_tool`) before the first call in a session, or it
errors. Skipping that load is the usual reason an agent silently falls back to file scanning.

| Tool | Use when |
| --- | --- |
| `semantic_search_nodes` | find functions/classes by name or intent (instead of Grep) |
| `query_graph` | trace `callers_of` / `callees_of` / `imports_of` / `tests_for` |
| `get_impact_radius` | gauge the blast-radius of a change |
| `detect_changes` | risk-scored review of the current diff |
| `get_review_context` | token-lean source snippets for review |
| `get_architecture_overview` | high-level module / community structure |

The graph auto-updates on file changes via the `.claude/settings.json` hooks.
<!-- /code-review-graph tool binding -->

<!-- memory-vault tool binding -->
## Persistent memory — memory-vault

**WHY / decisions / history / what-was-tried** → call **`recall` first**, before grepping to
understand *why* something is the way it is or what was already tried. The code records *what
is*, never *why*. Still grep for *current code facts*. If `recall` returns nothing relevant,
fall back to the code, then `remember` what you learned so the next session hits.

**`remember`** a decision, constraint, gotcha, or preference that emerges in conversation and
isn't written in a `.development-docs/` file. Never store secrets or copies of what's in git.

**These tools are deferred** — load them with `ToolSearch` (query `memory-vault`) before the
first call in a session.

| Tool | Use when |
| --- | --- |
| `recall` | search memory (pass `spaces`; this project's space is its dir name) |
| `remember` | store a durable fact (pass `space` = this project's space) |
| `forget` | soft-delete one chunk by id |
| `memory_status` | health / stats |

The vault is a shared Docker stack; a down vault means "fall back to the code," not a blocker.
<!-- /memory-vault tool binding -->
