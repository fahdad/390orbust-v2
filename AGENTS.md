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

## Session Start — Do This Every Time

1. **Read sessions.log tail** — `tail -5 plans/sessions.log` for context on what happened last session
2. **Read ledger** — `plans/ledger.json` for live status of all work items
3. **Find next task** — pick the lowest-numbered phase not marked "completed", then the lowest-numbered `not_started` or `in_pr` work item inside it
4. **Load the WI JSON** — read that work item's file from `plans/work-items/`
5. **Report** — tell the user what the next task is, what it requires, and wait for their go-ahead. Do NOT execute until they say "go" or "execute [WI-ID]".

The session flow is:
- User triggers each work item manually
- After you implement it, user runs their own verification
- User says "End session" when done
- Run `plans/scripts/end_session.py` to close out

---

## Current State

**Phase 1 (Foundation): COMPLETE**
Project skeleton, types.py, config.py, log.py, service.py, pyproject.toml,
ruff/mypy/pytest configs, .pre-commit-config.yaml, tests/conftest.py,
8 smoke tests, git remote, docs/seed (kickstart + research prompt).

**Phase 2 (Data Pipeline): IN PROGRESS — PR #1 open**

| Item | Status | Details |
|---|---|---|
| WI-02-01: DataProvider ABC | in_pr | PR #1 (wi/p2-data-foundation) |
| WI-02-02: ParquetStore | in_pr | PR #1 (wi/p2-data-foundation) |
| WI-02-03: AlpacaFetcher | not_started | Next PR |
| WI-02-04: RTH filtering | not_started | Next PR |
| WI-02-05: AlpacaBarProvider | not_started | Next PR |
| WI-02-06: Data quality checks | not_started | Future PR |
| WI-02-07: Integration tests | not_started | Future PR |
| WI-02-08: Notebook helper | not_started | Future PR |

**PR #1** (`wi/p2-data-foundation → main`):
https://github.com/fahdad/390orbust-v2/pull/1
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
3. Then PR 3: `wi/p2-data-quality`
4. Then Phase 3 decomposition (Feature Engineering)

---

## Key Paths

| Asset | Location |
|---|---|
| Source code | `src/orbust/` |
| Work item files | `plans/work-items/*.json` |
| Live status | `plans/ledger.json` |
| Session history | `plans/sessions.log` |
| Session closeout | `plans/scripts/end_session.py` |
| Render WI → markdown | `plans/scripts/render_wi.py` |
| Git workflow | `plans/git-workflow.md` |
| Phase index | `plans/_index.yaml` |
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
uv run python -m orbust.service --help  # CLI skeleton
# Session closeout
uv run python plans/scripts/end_session.py --update WI-02-01=merged --message "..." --commit "..." --push
# Render work item as markdown brief
uv run python plans/scripts/render_wi.py wi-data-provider-abc.json
```

---

## Review Handoff Signal

The review pipeline signals are documented in `plans/git-workflow.md` section
"Review pipeline". Key rule: when transitioning from Gemini bot loop to
frontier model review, do NOT append `/gemini review` tag — the frontier
pair (Opus + GPT) is the final sign-off.
