# Graphify — setup notes

The knowledge graph lives in `graphify-out/` and is **gitignored**. It is a
development aid for "what touches this symbol?" questions, not part of the
PyroScan runtime. Nothing in `server/` imports it.

## Scope

`graphify-out/` is built from a deliberately narrow corpus: `server/`, `Docs/`,
and the small root-level tools. See `.graphifyignore` for exclusions and why.

Bare `/graphify .` on the repo root scans **461 files / 3.5M words** — mostly
`spike/web/node_modules`, the Cesium build, imagery, and ODM outputs. The
`.graphifyignore` scopes that down to **66 files** (48 code + 18 docs). Do not
remove those exclusions without understanding this.

## Build state

| | |
|---|---|
| Nodes | 828 |
| Edges | 1880 |
| Communities | 54 (12 hand-labelled) |
| Code files | 48 |
| Docs | 18 |
| Graph HTML | 804 KB |

## Usage

```bash
# who calls X, with line numbers
graphify explain "get_weather"

# shortest path between two symbols
graphify path "get_weather" "Gateway"

# natural-language question (BFS over the graph)
graphify query "how does the provider chain fall through"

# rebuild after code changes (AST only, no LLM needed)
graphify update .

# full rebuild, then regenerate the report
python docs/../graphify-out/graphify_build.py   # see below
```

## Rebuild

AST extraction is deterministic and free. Semantic extraction (docs) needs the
host agent to act as the LLM — there is no `GEMINI_API_KEY` set, so docs are
extracted by dispatching subagents, which is slow.

For a code-only refresh after a refactor:

```bash
graphify update .          # re-extracts changed code files
graphify cluster-only .    # re-cluster + regenerate report and HTML
```

**Regenerate when you touch:** `server/providers/base.py`,
`server/providers/gateway.py`, `server/providers/registry.py`, `server/api.py`.
Those define the interfaces the graph is most useful for.

## What it is good at

Verified working:

- **Callers of a function**, with file and line:
  `get_weather` → `run_mission() runner.py:L82`, `_weather() api.py:L176`
- **Community structure** — clusters match real modules (gateway core, cache
  layer, HTTP adapters, advisory runtime, dashboard UI, selftest groups)
- **Rationale capture** — docstrings become `rationale_for` edges, so design
  intent sits next to the code it explains

## Known limits

- **Module-level dicts produce no edges.** `ACTION_CATALOG`,
  `PROVIDER_ORDER`-style constants are not callables, so AST extraction misses
  them. Use grep for those.
- **External imports are dropped.** Stdlib/3rd-party names (`pathlib`, `json`)
  get no nodes, so ~137 import edges were removed as noise. Do not expect
  `imports` edges to external packages.
- **The health check reports collapsed edges.** 107 undirected edge collapses
  (same pair, multiple relations like `calls` + `references`). Expected in an
  undirected graph, not corruption.
- **It goes stale.** A graph indexed before a refactor is worse than no graph,
  because it looks authoritative. The spec in `Docs/specs/` stays the source of
  truth; the graph does not override it.
- **Token cost shows 0.** Semantic extraction ran as host-agent subagents,
  which do not report usage through graphify's counter.

## Files

```
graphify-out/
  graph.html         interactive graph, open in a browser
  GRAPH_REPORT.md    audit report (god nodes, surprises, questions)
  graph.json         raw graph data
  manifest.json      file hashes for incremental --update
  cost.json          cumulative token tracker
```

## Setup files (committed)

```
.graphifyignore      corpus scope — read this before changing
.gitignore           graphify-out/ is ignored
```
