# LLM Probe Results — Work Item Decomposition Strategy

**Probed Models**: Opus 4.6 (anthropic/claude-opus-4.6) + GPT 5.4 (openai/gpt-5.4)
**Date**: 2026-05-06
**Prompt**: Architectural kickstart doc + scaffold status → 3 questions about granularity, format, and probe strategy

---

## Q1: Granularity — What should one work item be?

### Opus 4.6
**"Behavioral slice"** — one coherent behavioral unit that produces a testable artifact.

- 1-3 files (impl + test + maybe schema)
- 200-800 LOC of agent output
- Testable in isolation, leaves all existing tests green
- One primary responsibility per item (e.g., "fetch + pagination" is separate from "caching" is separate from "RTH filtering")

### GPT 5.4
**"Executable Capability Slice (ECS)"** — one capability, bounded module seam, explicit interfaces, concrete AC.

- ~300-1200 LOC changed
- 1-3 source files + tests
- One validation loop (run tests, check behavior)
- Must answer: what capability exists when done? what module boundary? what artifacts? how is it verified?

### Convergence
Both agree: **NOT** by deliverable, **NOT** by file, **NOT** by function. The unit is the *behavioral capability* — independently testable, dependency-explicit, 1-3 files, one agent session.

---

## Q2: Output Format — What should work items look like?

### Opus 4.6
**YAML files in `plans/` directory**, one per phase, with a lightweight index.

Key fields: `id`, `title`, `depends_on`, `files_to_create`, `files_to_modify`, `tests_to_create`, `context_files`, `interface_contract`, `acceptance_criteria`, `decisions_deferred`.

Not GitHub Issues — they're coordination tools for humans, not execution plans for agents. The YAML lives in the repo, is version-controlled, and the agent reads it directly.

### GPT 5.4
**Hybrid**: Canonical YAML/JSON for the full DAG + markdown task briefs for agent execution + GitHub Issues only for near-term ready tasks.

YAML is the canonical source. Markdown task briefs (generated from YAML) are what you actually paste to the agent. GitHub Issues are a *projection* for the next 5-10 ready tasks, not the full backlog.

### Convergence
Both strongly favor **YAML as the canonical format**, in-repo. Both reject GitHub Issues as the primary decomposition format (too much overhead, poor dependency modeling, encourages premature operationalization of future work). Both emphasize the need for `context_files` and `decisions_deferred` fields to keep agents on track.

---

## Q3: Probe Strategy — How to generate the decomposition?

### Opus 4.6
**Per-phase focused prompts, rolling 2-3 phase horizon.**

Decompose 2-3 phases ahead, not all 10. Re-decompose after each phase completes. Reasoning: you don't have enough information to decompose Phase 7 correctly until Phase 6 is built. Decomposed all upfront creates a plan you'll spend as much time maintaining as executing.

### GPT 5.4
**Hierarchical two-pass approach (closest to a middle ground).**

1. One global pass to build the full work-item DAG (skeleton only)
2. Phase-by-phase detailed decomposition using focused prompts
3. Targeted multi-agent critique for high-risk phases only (features, evaluation, execution)
4. Human curation before execution

This avoids the problem of per-phase-only decomposition creating inconsistent task shapes and cross-phase gaps, while also avoiding the "one giant plan" problem.

### Convergence
Both **reject** the all-10-phases-in-one-shot approach. Both **reject** heavy multi-agent everywhere (overkill for a solo build with well-defined architecture). Both agree that **later phases should be decomposed later**, informed by what you learn executing earlier phases. Both recommend **focused per-phase prompts** as the core mechanism.

The difference: Opus says 2-3 phase rolling horizon (learn as you go), GPT says one global skeleton first then per-phase refinement (top-down consistency). These are complementary — you could do a lightweight global pass, then decompose the first 2-3 phases in detail.

---

## Comparative Summary

| Dimension | Opus 4.6 | GPT 5.4 | Synthesis |
|---|---|---|---|
| Granularity | Behavioral slice, 200-800 LOC, 1-3 files | ECS, 300-1200 LOC, 1-3 files + tests | **Same concept, slightly different sizing** |
| Format | YAML in `plans/` directory | YAML canonical + markdown briefs + limited GH issues | **Both say YAML in repo** |
| Probe strategy | 2-3 phase rolling horizon | Global skeleton + per-phase + targeted critique | **Complementary: do both** |
| Key differentiator | `context_files` and `decisions_deferred` fields | Two-layer canonical (YAML) + execution (markdown) | **Both are worth implementing** |
