#!/usr/bin/env python3
"""End-of-session helper.

Updates ledger.json and appends to sessions.log atomically, then optionally
commits and pushes.

Usage:
    python3 scripts/end_session.py \\
      --update WI-02-01=completed \\
      --message "Completed WI-02-01." \\
      --commit "plans: end session" \\
      --push

Flags:
    --update <ID>=<status>   One or more work item status changes.
    --message <text>         Line appended to sessions.log.
    --commit <msg>           Auto-stage and commit docs/plans/ with this message.
    --push                   Also git push (only with --commit).
    --check-phase            Recalculate phase state from WI statuses.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LEDGER_PATH = BASE_DIR / "ledger.json"
SESSIONS_PATH = BASE_DIR / "sessions.log"
VALID_STATUSES = {"not_started", "in_progress", "complete", "merged", "blocked", "in_pr"}


def load_ledger() -> dict:
    with open(LEDGER_PATH) as f:
        return json.load(f)


def save_ledger(ledger: dict) -> None:
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)
        f.write("\n")


def read_sessions() -> str:
    if SESSIONS_PATH.exists():
        return SESSIONS_PATH.read_text()
    return ""


def append_session(text: str) -> None:
    with open(SESSIONS_PATH, "a") as f:
        f.write(text + "\n")


def compute_phase_state(ledger: dict) -> dict:
    """Determine phase state from individual WI statuses inside that phase."""
    items = ledger.get("items", {})
    phase_wis: dict[str, list[str]] = {}
    for wi_id, wi_data in items.items():
        match = re.match(r"WI-(\d+)", wi_id)
        if match:
            phase = f"phase-{match.group(1)}"
            phase_wis.setdefault(phase, []).append(wi_data.get("status", "not_started"))

    phases = ledger.get("phase_states", {})
    for phase, statuses in phase_wis.items():
        if phase not in phases:
            continue
        if all(s in ("merged", "complete") for s in statuses):
            phases[phase] = "completed"
        elif any(s == "in_progress" for s in statuses):
            phases[phase] = "in_progress"
        elif any(s == "blocked" for s in statuses):
            if phases[phase] != "in_progress":
                phases[phase] = "blocked"
    return phases


def git_commit(msg: str) -> bool:
    result = subprocess.run(
        ["git", "add", str(BASE_DIR)],
        capture_output=True, text=True, cwd=BASE_DIR.parent
    )
    if result.returncode != 0:
        print(f"  git add failed: {result.stderr.strip()}")
        return False
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        capture_output=True, text=True, cwd=BASE_DIR.parent
    )
    print(f"  {result.stdout.strip()}")
    return result.returncode == 0


def git_push() -> bool:
    result = subprocess.run(
        ["git", "push"], capture_output=True, text=True, cwd=BASE_DIR.parent
    )
    print(f"  {result.stdout.strip()}")
    return result.returncode == 0


def main() -> None:
    updates: list[tuple[str, str]] = []
    message: str | None = None
    commit_msg: str | None = None
    do_push = False
    check_phase = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--update" and i + 1 < len(sys.argv):
            updates.append(parse_update(sys.argv[i + 1]))
            i += 2
        elif arg.startswith("--update="):
            updates.append(parse_update(arg[len("--update="):]))
            i += 1
        elif arg == "--message" and i + 1 < len(sys.argv):
            message = sys.argv[i + 1]
            i += 2
        elif arg.startswith("--message="):
            message = arg[len("--message="):]
            i += 1
        elif arg == "--commit" and i + 1 < len(sys.argv):
            commit_msg = sys.argv[i + 1]
            i += 2
        elif arg.startswith("--commit="):
            commit_msg = arg[len("--commit="):]
            i += 1
        elif arg == "--push":
            do_push = True
            i += 1
        elif arg == "--check-phase":
            check_phase = True
            i += 1
        else:
            i += 1

    if not updates and not message:
        print(__doc__)
        sys.exit(1)

    ledger = load_ledger()

    # Apply updates
    for wi_id, status in updates:
        items = ledger.setdefault("items", {})
        if wi_id not in items:
            print(f"  WARNING: '{wi_id}' not found in ledger. Adding it.")
            items[wi_id] = {"status": "not_started", "notes": ""}
        items[wi_id]["status"] = status
        print(f"  {wi_id} -> {status}")

    if check_phase:
        ledger["phase_states"] = compute_phase_state(ledger)
        print(f"  Phase states auto-computed.")

    ledger["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_ledger(ledger)
    print(f"  Ledger saved.")

    if message:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"{timestamp}  Hermes  {message}"
        append_session(entry)
        print(f"  Session logged: {entry}")

    if commit_msg:
        print(f"  Committing...")
        if git_commit(commit_msg):
            if do_push:
                git_push()

    print(f"\n  Done.")


def parse_update(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        print(f"  ERROR: Invalid format '{raw}'. Use WI-XX-NNN=status")
        sys.exit(1)
    wi_id, status = raw.split("=", 1)
    wi_id = wi_id.strip()
    status = status.strip()
    if status not in VALID_STATUSES:
        print(f"  ERROR: Invalid status '{status}'.")
        sys.exit(1)
    return wi_id, status


if __name__ == "__main__":
    main()
