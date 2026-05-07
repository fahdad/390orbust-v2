# 390OrBust v2 — Algorithmic Trading Platform

## Mission

Build a modular, event-driven algorithmic trading platform for US equities
(energy sector, XLE components) using 1-minute Alpaca bar data. Full lifecycle
from signal research to autonomous live execution, all on a single box
(Ryzen 5 5600X, 48GB RAM, RTX 3090 24GB).

Three deployment stages, config changes not rewrites:
1. **Supervised Paper** — human approves every action
2. **Autonomous Paper** — system executes, human monitors
3. **Autonomous Live** — system executes with risk guardrails

---

## Architecture (8 Modules)

```
DataProvider → FeatureRegistry → StrategyEngine → SignalInterpreter + RiskGate → ExecutionLayer
                                                  ↓
                                    WalkForwardEngine + Backtester
                                  Dashboard (FastAPI + SSE, reads everything)
                                  ExperimentLedger + ModelStore (SQLite + .pt)
                                  Logging & Observability (structlog)
```

---

## Current State

**Phase 1 (Foundation): COMPLETE**
Project skeleton, types.py (all dataclasses + enums), config.py (Pydantic YAML),
log.py (structlog), service.py (typer CLI), pyproject.toml (uv, torch 2.11),
ruff/mypy/pytest configs, .pre-commit-config.yaml, tests/conftest.py,
8 smoke tests, git remote, docs/seed (kickstart + research prompt).

**Phase 2 (Data Pipeline): IN PROGRESS — PR #1 open**

| Item | Status | Branch/PR |
|---|---|---|
| WI-2.1: DataProvider ABC | **Done** — in PR | `wi/p2-data-foundation` → PR #1 |
| WI-2.2: ParquetStore | **Done** — in PR | same branch |
| WI-2.3: AlpacaFetcher | Not started | `wi/p2-alpaca-integration` |
| WI-2.4: RTH filtering | Not started | same branch |
| WI-2.5: AlpacaBarProvider | Not started | same branch |
| WI-2.6: Data quality checks | Not started | `wi/p2-data-quality` |
| WI-2.7: Integration tests | Not started | same branch |
| WI-2.8: Notebook helper | Not started | same branch |

**PR #1** (`wi/p2-data-foundation → main`):
Open at https://github.com/fahdad/390orbust-v2/pull/1
Reviews: 2 rounds from gemini-code-assist, findings addressed.
Next: finish review pipeline → rebase-merge to main.

---

## Development Workflow

See `plans/git-workflow.md` for full details.

- **One commit per work item** — green tree, descriptive message
- **One branch per PR** — `wi/{phase-abbrev}-{group-name}`
- **One PR per natural group** — 2-4 related work items
- **Review pipeline**: Gemini Code Assist (loop) → Opus 4.6 → GLM 5.1 → Kimi K2.6 → human → rebase-merge
- **Merge**: rebase-merge only (preserves per-work-item commits)

---

## Next Steps (Immediate)

1. Finish review on PR #1 (merge to main)
2. Start PR 2: `wi/p2-alpaca-integration`
   - WI-2.3: AlpacaFetcher (paginate, rate-limit, error handling)
   - WI-2.4: RTH filtering (09:30-16:00 ET Mon-Fri)
   - WI-2.5: AlpacaBarProvider (cache-aware, RTH-applied, full DataProvider)
3. Then PR 3: `wi/p2-data-quality`
   - WI-2.6: Data quality checks
   - WI-2.7: Integration tests
   - WI-2.8: Notebook helper
4. Then Phase 3 decomposition (Feature Engineering)

---

## Key Paths

| Asset | Location |
|---|---|
| Source code | `src/orbust/` |
| Work item plans | `plans/phase-02-data.yaml` |
| Phase index | `plans/_index.yaml` |
| Git workflow | `plans/git-workflow.md` |
| Architecture spec | `docs/seed/390OrBust_v2_Kickstart.md` |
| Research prompt | `docs/seed/390OrBust_Deep_Research_Prompt.md` |
| Tests | `tests/` |
| Strategies | `strategies/energy_conv1d/` |

---

## Key Commands

```bash
uv sync --group dev          # Install deps (first time or after pyproject.toml changes)
uv run pytest tests/ -v      # Run test suite (33 tests)
uv run ruff check src/       # Lint
uv run mypy src/             # Type check
python -m orbust.service --help  # CLI skeleton
```

---

## Review Handoff Signal

The review pipeline signals are documented in `plans/git-workflow.md` section
"Review pipeline". Key rule: when transitioning from Gemini bot loop to
frontier model review, do NOT append `/gemini review` tag — the frontier
pair (Opus + GPT) is the final sign-off.
