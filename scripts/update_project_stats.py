"""Record the number of passing tests so the site can state it accurately.

Run from the repository root, after the suite passes:

    python3 scripts/update_project_stats.py

Writes data/project_stats.json. The landing page reads that file and omits the
figure entirely when it is absent, so a forgotten run shows nothing rather
than something false.

Why a recorded number rather than a live one: the test suite is not importable
from the running application, and collecting it per request would be absurd.
Recording it makes the staleness explicit and bounded - the file carries the
timestamp and the commit it was measured at.
"""

import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(PROJECT_ROOT, "data", "project_stats.json")


def run(*args):
    result = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def main():
    print("running the suite ...")
    code, out, err = run(sys.executable, "-m", "pytest", "-q")
    tail = (out or err).strip().splitlines()[-1:] or [""]
    summary = tail[0]
    print(f"  {summary}")

    if code != 0:
        print("\nSuite did not pass. Nothing written: the site should not "
              "advertise a count from a failing run.")
        return 1

    passed = None
    for token in summary.replace("=", " ").split():
        if token.isdigit():
            passed = int(token)
            break
    if not passed:
        print("\nCould not parse a test count from pytest's summary line.")
        return 1

    _, commit, _ = run("git", "rev-parse", "--short", "HEAD")
    _, when, _ = run("git", "log", "-1", "--format=%cI")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    payload = {
        "tests_passing": passed,
        "measured_at_commit": commit or None,
        "commit_date": when or None,
    }
    with open(OUT_PATH, "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    print(f"\nwrote {OUT_PATH}")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
