#!/usr/bin/env python3
"""Results of the checks of one CI run: its summary and the README badges.

Reads what the steps of the run left behind:

- the reports of scripts/run_checks.sh, one per step: <reports>/<step>.jsonl
  (CHECKS_REPORT, see tests/test_checks.py);
- the versions of the run: the outputs of scripts/ha_versions.py as JSON
  (HA_VERSIONS);
- optionally the steps context as JSON (STEPS): a step that failed outside
  the checks (docker pull, pip) counts as an error even with a clean report.

Prints tests=<badge> and home_assistant=<badge> for $GITHUB_OUTPUT, each in
the shields.io endpoint format; --summary prints a Markdown table for
$GITHUB_STEP_SUMMARY instead. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_versions import CHANNELS, TITLES  # noqa: E402

NON_BLOCKING = ("next",)
DEV = re.compile(r"^(\d{4}\.\d{1,2})\.\d+\.dev")
PASSED, FAILED, ERROR = "passed", "failed", "error"


def read_report(path: Path) -> dict | None:
    """Counts of one report; None without one (the step did not get to the checks)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    report = {"homeassistant": None, "scripts": 0, "passed": 0, "failed": 0, "broken": 0}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if "script" in record:
                report["scripts"] += 1
                report["passed"] += int(record["passed"])
                report["failed"] += int(record["failed"])
                report["broken"] += not record["ok"]
            elif "homeassistant" in record:
                report["homeassistant"] = record["homeassistant"]
        except (ValueError, KeyError, TypeError):
            report["broken"] += 1
    return report


def results(versions: dict[str, str], reports: Path, steps: dict | None = None) -> list[dict]:
    """One entry per step that ran, in the order of the steps."""
    out = []
    for channel in CHANNELS:
        tag = versions.get(channel) or ""
        if not tag:
            continue
        report = read_report(reports / f"{channel}.jsonl")
        outcome = ((steps or {}).get(channel) or {}).get("outcome")
        entry = {"channel": channel, "tag": tag, "homeassistant": None, "passed": 0, "failed": 0}
        if report is None or not report["scripts"]:
            status = ERROR
        else:
            entry.update(homeassistant=report["homeassistant"], passed=report["passed"], failed=report["failed"])
            if report["failed"] or report["broken"]:
                status = FAILED
            elif outcome not in (None, "success"):
                status = ERROR
            else:
                status = PASSED
        entry["status"] = status
        out.append(entry)
    return out


def version_name(entry: dict) -> str:
    """The tag, but the nightly build as "2026.12-dev": the release it leads to."""
    if entry["tag"] == "dev":
        match = DEV.match(entry["homeassistant"] or "")
        if match:
            return f"{match.group(1)}-dev"
    return entry["tag"]


def badge(label: str, message: str, color: str, **extra) -> dict:
    return {"schemaVersion": 1, "label": label, "message": message, "color": color, **extra}


def tests_badge(entries: list[dict]) -> dict:
    """Checks passed: on the current version; on a failure, the worst blocking step."""
    blocking = [e for e in entries if e["channel"] not in NON_BLOCKING]
    if not blocking:
        return badge("tests", "no results", "lightgrey")
    failed = [e for e in blocking if e["status"] == FAILED]
    if failed:
        worst = max(failed, key=lambda e: e["failed"])
        return badge("tests", f"{worst['passed']} passed, {max(worst['failed'], 1)} failed", "red")
    if any(e["status"] == ERROR for e in blocking):
        return badge("tests", "error", "red")
    shown = next((e for e in blocking if e["channel"] == "current"), blocking[-1])
    return badge("tests", f"{shown['passed']} passed", "brightgreen")


def home_assistant_badge(entries: list[dict]) -> dict:
    """The versions checked; one that did not pass is marked with a cross."""
    if not entries:
        return badge("Home Assistant", "no results", "lightgrey", namedLogo="homeassistant")
    parts = [version_name(e) + ("" if e["status"] == PASSED else " ✗") for e in entries]
    blocking_bad = any(e["status"] != PASSED for e in entries if e["channel"] not in NON_BLOCKING)
    other_bad = any(e["status"] != PASSED for e in entries if e["channel"] in NON_BLOCKING)
    color = "red" if blocking_bad else "yellow" if other_bad else "brightgreen"
    return badge("Home Assistant", " | ".join(parts), color, namedLogo="homeassistant")


def summary(entries: list[dict]) -> str:
    verdict = {PASSED: "✅ пройдено", FAILED: "❌ не пройдено", ERROR: "❌ не запустилось"}
    lines = ["| Шаг | Версия Home Assistant | Пройдено проверок | Не пройдено | Итог |", "|---|---|---|---|---|"]
    for e in entries:
        version = f"`{e['tag']}`"
        if e["homeassistant"] and e["homeassistant"] != e["tag"]:
            version += f" ({e['homeassistant']})"
        failed = "—" if e["status"] == ERROR else str(e["failed"])
        passed = "—" if e["status"] == ERROR else str(e["passed"])
        lines.append(f"| {TITLES[e['channel']]} | {version} | {passed} | {failed} | {verdict[e['status']]} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", required=True, help="directory with <step>.jsonl")
    parser.add_argument("--versions", default=os.environ.get("HA_VERSIONS", ""),
                        help="JSON of the versions (default: $HA_VERSIONS)")
    parser.add_argument("--steps", default=os.environ.get("STEPS", ""),
                        help="JSON of the steps context (default: $STEPS)")
    parser.add_argument("--summary", action="store_true", help="print a Markdown table instead")
    args = parser.parse_args(argv)
    if not args.versions:
        parser.error("no versions: pass --versions or set HA_VERSIONS")
    entries = results(json.loads(args.versions), Path(args.reports), json.loads(args.steps) if args.steps else None)
    if args.summary:
        sys.stdout.write(summary(entries))
    else:
        sys.stdout.write(f"tests={json.dumps(tests_badge(entries))}\n")
        sys.stdout.write(f"home_assistant={json.dumps(home_assistant_badge(entries))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
