#!/usr/bin/env python3
"""Render a work item JSON file as a markdown task brief.

Usage:
    python3 scripts/render_wi.py wi-data-provider-abc.json
    python3 scripts/render_wi.py --all
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WI_DIR = BASE_DIR / "work-items"


def render(wi: dict) -> str:
    lines: list[str] = []

    status_icon = {"not_started": "○", "in_progress": "◔", "complete": "✓", "merged": "●", "blocked": "⊘", "in_pr": "◷"}
    icon = status_icon.get(wi.get("status", ""), "○")

    lines.append(f"# {icon} {wi.get('id', '?')}: {wi.get('title', '?')}")
    lines.append("")
    if wi.get("objective"):
        lines.append(wi["objective"])
        lines.append("")

    lines.append("## Dependencies")
    deps = wi.get("depends_on", []) or []
    if deps:
        for d in deps:
            lines.append(f"- {d}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("## Files")
    for key, label in [("files_to_create", "Create"), ("files_to_modify", "Modify"), ("tests_to_create", "Tests")]:
        files = wi.get(key, []) or []
        if files:
            lines.append(f"### {label}")
            for f in files:
                lines.append(f"- `{f}`")
            lines.append("")
        else:
            lines.append(f"### {label}")
            lines.append("(none)")
            lines.append("")

    lines.append("## Context Files (read first)")
    for cf in wi.get("context_files", []) or []:
        lines.append(f"- `{cf}`")
    lines.append("")

    lines.append("## Acceptance Criteria")
    for ac in wi.get("acceptance_criteria", []) or []:
        lines.append(f"- [ ] {ac}")
    lines.append("")

    lines.append("## Validation")
    for v in wi.get("validation", []) or []:
        lines.append(f"```bash")
        lines.append(f"{v}")
        lines.append(f"```")
    lines.append("")

    non_goals = wi.get("non_goals", []) or []
    if non_goals:
        lines.append("## Non-Goals (do NOT implement)")
        for ng in non_goals:
            lines.append(f"- {ng}")
        lines.append("")

    lines.append(f"---")
    lines.append(f"Risk: {wi.get('risk_level', '?')}  |  Est. lines: {wi.get('estimated_lines', '?')}  |  Review group: {wi.get('review_group', '?')}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = sys.argv[1:]

    if "--all" in args:
        for path in sorted(WI_DIR.glob("*.json")):
            with open(path) as f:
                wi = json.load(f)
            print(render(wi))
            print("\n---\n")
        return

    if not args:
        print("Usage: render_wi.py <file.json> [--all]")
        sys.exit(1)

    path = Path(args[0])
    if not path.is_absolute():
        path = WI_DIR / path

    with open(path) as f:
        wi = json.load(f)

    print(render(wi))


if __name__ == "__main__":
    main()
