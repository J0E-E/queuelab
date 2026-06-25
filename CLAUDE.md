# CLAUDE.md


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

**Always pass `repo_root`** — set it to the absolute path of the current project root (the
git toplevel) on **every** call. A single shared local daemon serves all repos at once and
routes each call by its `repo_root`; omit it and the call resolves to a neutral home with no
graph and returns nothing useful (fail-closed — never another project's data), so pass it.

**The server is a shared HTTP daemon, not a per-chat process.** It runs once per machine at
`http://127.0.0.1:5555/mcp`, is auto-started at SessionStart (and before the first graph tool
call), and self-stops after ~1h idle. You don't launch or manage it; `.claude/setup/code-review-graph/daemon.sh`
(`status` / `stop`) is there only if you need to inspect it.

The graph's **structure** auto-updates on file changes via the `.claude/settings.json` PostToolUse
hook (`update --skip-flows`). Its **flows + semantic embeddings** are refreshed in full,
**foreground**, at two points in the build loop — `build-epic` **preflight** (before the plan reads
the graph) and the end of each epic (`8-complete-epic`) — not at SessionStart. Both are incremental
(cheap when nothing changed). Outside the build loop (e.g. a `git pull` then ad-hoc work with no
epic), run `code-review-graph update && code-review-graph embed` by hand to re-embed.
<!-- /code-review-graph tool binding -->
