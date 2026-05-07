# Git Workflow — 390OrBust v2

Single developer + AI coding agent. The workflow is designed to keep main
reviewable, enable clean reverts, and minimize coordination overhead.

---

## Commit Strategy

**One commit per completed work item.** Never more, never less.

A work item is a single behavioral slice (see `plans/work-item-schema.yaml`).
If a work item touches the data provider ABC, the commit contains exactly
that: the ABC, its interface tests, and any necessary type additions. Nothing
else.

### Commit message format

```
WI-2.1: DataProvider ABC and BarEvent streaming protocol

- DataProvider ABC with get_bars, stream_bars, available_fields
- Interface compliance tests (mock implementation)
- BarEvent invariants validated in __post_init__

Depends on: Phase 1 (types, config, logging)
Review-group: data-foundation
```

The body explains what changed. The `Depends on` line references prior
commits/items. The `Review-group` tag matches the PR it belongs to.

### Rules

- **Each commit leaves the tree green.** All existing tests pass, lint is
  clean, mypy passes. No "will fix in next commit" debt.
- **No WIP commits on main.** Work in progress lives on feature branches.
- **No fixup commits.** If you find a bug in a previous commit within the
  same PR, amend or rebase. If it's already on main, it's a new work item.
- **One concern per commit.** If you notice formatting issues unrelated to
  the work item, resist the urge — that's a separate commit or PR.

---

## Branch Strategy

Branches are organized by **natural review group** — a cluster of 2-4
related work items that make sense to review together.

### Naming

```
wi/{phase-abbrev}-{group-name}
```

Examples:
```
wi/p2-data-provider-abc       # DataProvider ABC + Parquet store
wi/p2-alpaca-fetch            # AlpacaBarProvider + RTH filtering + caching
wi/p3-registry-core           # FeatureRegistry + shift + NaN policy
wi/p3-builtins-returns        # Returns/rolling/MA built-in features
wi/p3-builtins-advanced       # RSI/ATR/volume/CSZ/calendar features
wi/p4-strategy-abc            # Strategy ABC + Signal types
wi/p4-training-harness        # Training harness + GPU management + ledger
```

### Lifecycle

```
main  ──●────────────────────●────────────────────●──
         \                  / \                  /
          wi/p2-provider   /   wi/p2-alpaca     /
                         ✨                    ✨
```

1. Branch off `main`
2. Commit work items one at a time (1 commit = 1 work item)
3. Push branch
4. Open PR against `main`
5. Run review pipeline
6. Address review findings (amend commits or add fixup commits)
7. **Rebase-merge** to main (preserves individual work item commits)

---

## PR Strategy

### Granularity

One PR per **natural group** — 2-4 related work items, 3-10 commits,
usually touching a single module seam.

### Natural group definitions (by phase)

| Phase | PR Groups | Work Items Per PR | Rationale |
|-------|-----------|-------------------|-----------|
| P2: Data | data-foundation (ABC + store), alpaca-integration (fetch + RTH + cache), data-quality (checks + tests) | 2-3 each | Provider ABC is pure interface; Alpaca is external-dependency; quality is cross-cutting |
| P3: Features | registry-core (registry + shift + NaN), builtins-returns (returns/rolling/MA), builtins-advanced (RSI/ATR/volume/CSZ/calendar), parity-validation (v1 comparison) | 2-3 each | Feature categories have different NaN semantics and edge cases |
| P4: Strategy | strategy-contract (ABC + Signal), training-harness (engine + harness + ledger), gpu-cli (GPU management + CLI) | 2-3 each | Contract is pure design; harness is implementation; GPU is device-specific |
| P5: Evaluation | walk-forward (fold gen + scaler lifecycle), backtester (simulation + cost model), metrics-audit (metrics + leakage audit) | 2-3 each | WF is the engine; cost model is independent concern; audit is verification |
| P6: Risk | interpreter (signal policies), risk-gate (system + strategy tiers), logging (decision audit) | 2-3 each | Each is a distinct failure domain |
| P7: Execution | broker-abc (adapter + fake), order-lifecycle (state machine + approval), crash-recovery (SQLite + reconciliation) | 2-3 each | Order state machine is the critical path |
| P8: Dashboard | research-api (experiment queries), ops-api (live state + SSE), views (templates + timeline) | 2-3 each | API first, views second |
| P9: Port | parity-audit (data + features), model-implementation (Conv1D port), validation (backtest comparison + gap report) | 2-3 each | Port is an acid test, not a rewrite |

### PR template

```markdown
## Summary

[2-3 sentences: what this PR adds and why]

## Work Items

- WI-2.1: DataProvider ABC and BarEvent streaming protocol
- WI-2.2: Parquet store — write and read bars in wide format

## Review Focus

- [ ] Interface contracts match kickstart section 3.1
- [ ] Timestamp handling is UTC-aware throughout
- [ ] Test coverage for edge cases (empty bars, missing fields)
- [ ] No lookahead bias introduced
```

---

## Review Pipeline

Each PR goes through a staged review chain before merging:

```
PR opened → Opus 4.6 review → address findings
         → GLM 5.1 review  → address findings  
         → Kimi K2.6 review → address findings
         → Final human sign-off → rebase-merge
```

### Review scope per model

| Model | Focus |
|-------|-------|
| **Opus 4.6** | Architecture conformance, interface design, edge cases, test coverage |
| **GLM 5.1** | Code quality, error handling, Python idioms, type correctness |
| **Kimi K2.6** | Logic bugs, performance concerns, security (no hardcoded secrets) |
| **Human** | Strategic fit, risk assessment for live-money paths, final sign-off |

### Handling review findings

- **Small fixes** (typos, naming, formatting) — amend into the relevant
  commit and force-push the branch
- **Medium changes** (missing test case, refactor within same module) —
  add a fixup commit, then squash during rebase-merge
- **Large structural changes** — close the PR, split into smaller groups,
  open new PRs

### Merge strategy

**Rebase-merge only.** Never squash-merge (loses per-work-item commits)
and never merge-commit (pollutes history with merge bubbles).

```
git checkout main
git pull --rebase
git rebase wi/p2-provider    # or: gh pr merge <number> --rebase
```

The result on main:

```
WI-7.3: Crash recovery — SQLite state reload + Alpaca reconciliation
WI-7.2: Order lifecycle — place, fill, cancel, expire state machine
WI-7.1: BrokerAdapter ABC + AlpacaBrokerAdapter + fake broker for tests
WI-6.3: Risk gate evaluation logging — every decision with full reasoning
...
```

Each commit is a coherent behavioral unit, each PR is a reviewed group,
and the full execution trace is readable in `git log --oneline`.

---

## Recovery from Bad States

### Commit landed on main, broke tests
```bash
# Create a work item to fix it
git revert <commit-hash>
# Push fix as a new PR
```

### PR branch has a bug found during review
```bash
# Fix and amend (if it's the most recent commit)
git add <files>
git commit --amend --no-edit
git push --force-with-lease

# Or add a fixup commit (if multiple commits need fixing)
git add <files>
git commit -m "fixup! <original-commit-message>"
git push --force-with-lease
# Squash during rebase-merge
```

### Wrong branch base (branch off wrong commit)
```bash
git rebase --onto <correct-base> <old-base> <branch-name>
git push --force-with-lease
```

### Stale branch (main has moved on)
```bash
git fetch origin
git rebase origin/main
# Resolve conflicts, test, push
git push --force-with-lease
```
