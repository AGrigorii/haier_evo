"""The summary of a CI run and the README badges (scripts/ci_results.py)."""
import sys, json, os, io, tempfile, importlib.util
from contextlib import redirect_stdout
from pathlib import Path
_HERE = Path(__file__).resolve().parent
root = sys.argv[1] if len(sys.argv) > 1 else str(_HERE.parent)
spec = importlib.util.spec_from_file_location("ci_results", os.path.join(root, "scripts", "ci_results.py"))
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

fails = 0
def check(name, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(("OK  " if ok else "FAIL"), name, "" if ok else f"\n      got:  {got!r}\n      want: {want!r}")

VERSIONS = {"minimum": "", "prev2": "2026.9.4", "prev1": "2026.10.4", "current": "2026.11.0", "next": "dev"}
HA = {"minimum": "2026.9.4", "prev2": "2026.9.4", "prev1": "2026.10.4", "current": "2026.11.0",
      "next": "2026.12.0.dev202611070240"}

def lines(channel, passed=(300, 166), failed=(0, 0)):
    """A report as tests/test_checks.py writes it: the version, then one line per script."""
    out = [{"homeassistant": HA[channel]}]
    out += [{"script": f"check_{i}.py", "passed": p, "failed": f, "ok": not f} for i, (p, f) in enumerate(zip(passed, failed))]
    return out

def run(reports, versions=VERSIONS, steps=None):
    tmp = Path(tempfile.mkdtemp())
    for channel, records in reports.items():
        (tmp / f"{channel}.jsonl").write_text("".join(
            (r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records))
    entries = cr.results(versions, tmp, steps)
    return entries, cr.tests_badge(entries), cr.home_assistant_badge(entries)

ALL = {c: lines(c) for c in ("prev2", "prev1", "current", "next")}

entries, tests, ha = run(ALL)
check("every step ran: one entry per version, in the order of the steps",
      [(e["channel"], e["status"]) for e in entries],
      [("prev2", "passed"), ("prev1", "passed"), ("current", "passed"), ("next", "passed")])
check("tests badge: checks passed on the current version", (tests["label"], tests["message"], tests["color"]),
      ("tests", "466 passed", "brightgreen"))
check("Home Assistant badge: the versions checked, the nightly build named by its release",
      (ha["message"], ha["color"], ha["namedLogo"]), ("2026.9.4 | 2026.10.4 | 2026.11.0 | 2026.12-dev", "brightgreen", "homeassistant"))
check("shields.io endpoint format", all(b["schemaVersion"] == 1 and isinstance(b["message"], str) for b in (tests, ha)), True)

reports = dict(ALL, prev2=lines("prev2", passed=(1, 166)))
check("the counts differ between versions: the current one is shown", run(reports)[1]["message"], "466 passed")

reports = dict(ALL, next=lines("next", passed=(298, 166), failed=(2, 0)))
_, tests, ha = run(reports)
check("only next failed: tests stay green, the version gets a cross, the badge is yellow",
      (tests["message"], tests["color"], ha["message"], ha["color"]),
      ("466 passed", "brightgreen", "2026.9.4 | 2026.10.4 | 2026.11.0 | 2026.12-dev ✗", "yellow"))

reports = dict(ALL, prev1=lines("prev1", passed=(297, 166), failed=(3, 0)), current=lines("current", passed=(299, 166), failed=(1, 0)))
_, tests, ha = run(reports)
check("a blocking version failed: the worst one is shown, both badges red",
      (tests["message"], tests["color"], ha["message"], ha["color"]),
      ("463 passed, 3 failed", "red", "2026.9.4 | 2026.10.4 ✗ | 2026.11.0 ✗ | 2026.12-dev", "red"))

reports = {k: v for k, v in ALL.items() if k != "prev2"}
entries, tests, ha = run(reports)
check("no report (docker pull or pip failed): an error, not a pass",
      (entries[0]["status"], tests["message"], tests["color"], ha["message"].split(" | ")[0]), ("error", "error", "red", "2026.9.4 ✗"))
check("a report without scripts (pytest broke before the checks) is an error",
      run(dict(ALL, current=[{"homeassistant": HA["current"]}]))[0][2]["status"], "error")
check("a script that broke without a FAIL line counts as failed",
      run(dict(ALL, current=lines("current") + [{"script": "check_x.py", "passed": 0, "failed": 1, "ok": False}]))[1]["message"],
      "466 passed, 1 failed")
check("a broken line in a report is a failure, not ignored",
      run(dict(ALL, current=lines("current") + ['{"script": "check_x.py", "pass']))[0][2]["status"], "failed")
steps = {c: {"outcome": "success"} for c in ALL}
check("a step outcome of success keeps a clean report passed", run(ALL, steps=steps)[0][2]["status"], "passed")
steps["prev1"] = {"outcome": "failure"}
check("a failed step with a clean report is an error", run(ALL, steps=steps)[0][1]["status"], "error")

versions = dict(VERSIONS, minimum="2026.9.4", next="2026.12.0b1")
entries, tests, ha = run(dict(ALL, minimum=lines("minimum"), next=lines("next")), versions)
check("the minimum of hacs.json comes first, a beta is shown by its tag",
      (entries[0]["channel"], ha["message"]), ("minimum", "2026.9.4 | 2026.9.4 | 2026.10.4 | 2026.11.0 | 2026.12.0b1"))
check("the nightly build without a version in its report stays dev",
      cr.version_name({"tag": "dev", "homeassistant": None}), "dev")
check("no versions at all: grey badges, not a crash",
      (run({}, versions={})[1]["color"], run({}, versions={})[2]["color"]), ("lightgrey", "lightgrey"))

# what the workflow reads
tmp = tempfile.mkdtemp()
for channel, records in ALL.items():
    Path(tmp, f"{channel}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
out = io.StringIO()
with redirect_stdout(out):
    cr.main(["--reports", tmp, "--versions", json.dumps(VERSIONS), "--steps", json.dumps({c: {"outcome": "success"} for c in ALL})])
got = dict(line.split("=", 1) for line in out.getvalue().splitlines())
check("$GITHUB_OUTPUT: two keys, each a one-line JSON badge",
      (sorted(got), json.loads(got["tests"])["message"], json.loads(got["home_assistant"])["color"]),
      (["home_assistant", "tests"], "466 passed", "brightgreen"))
out = io.StringIO()
with redirect_stdout(out):
    cr.main(["--reports", tmp, "--versions", json.dumps(VERSIONS), "--summary"])
table = out.getvalue()
check("summary: a row per step with its counts and the exact nightly version",
      ("| текущая | `2026.11.0` | 466 | 0 | ✅ пройдено |" in table, "(2026.12.0.dev202611070240)" in table, table.count("\n")), (True, True, 6))

# tests/test_checks.py writes what this script reads: a real pytest run over three scripts
if importlib.util.find_spec("pytest") is None:
    print("SKIP the report of tests/test_checks.py: pytest is not installed")
else:
    import shutil, subprocess
    work = Path(tempfile.mkdtemp()) / "tests"
    work.mkdir()
    shutil.copy(os.path.join(root, "tests", "test_checks.py"), work)
    (work / "check_a.py").write_text('print("OK   one")\nprint("OK   two")\nprint("FAILS: 0")\n')
    (work / "check_b.py").write_text('import sys\nprint("OK   one")\nprint("FAIL two")\nprint("FAILS: 1")\nsys.exit(1)\n')
    (work / "check_c.py").write_text('print("OK   one")\nraise RuntimeError("broken")\n')
    report_file = work.parent / "report.jsonl"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(work)],
                          cwd=work.parent, capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, CHECKS_REPORT=str(report_file)))
    got = cr.read_report(report_file)
    check("test_checks.py: OK and FAIL lines counted per script (not FAILS:), a crash is one failed check",
          (proc.returncode, got and {k: got[k] for k in ("scripts", "passed", "failed", "broken")}),
          (1, {"scripts": 3, "passed": 4, "failed": 2, "broken": 2}))
    check("test_checks.py: the report names the Home Assistant version of the run",
          '"homeassistant"' in report_file.read_text(), True)

print("FAILS:", fails)
sys.exit(1 if fails else 0)
