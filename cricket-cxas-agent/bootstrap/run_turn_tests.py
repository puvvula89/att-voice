"""Run the typed scenarios in turn_tests/ against the deployed app with SCRAPI's turn tests.

    .venv/bin/python bootstrap/run_turn_tests.py            # every scenario
    .venv/bin/python bootstrap/run_turn_tests.py P1 P3      # only these profiles

Each test is tagged with the demo profile it needs. Before each profile's group the demo account is
reset to that profile, which also clears any saved place. Requests are paced at TURN_TESTS_RPM per
minute (default 6) to stay inside the project's quota. Afterwards the account goes back to DEMO_PROFILE.

Writes runs/<UTC timestamp>/results.csv (one row per checked expectation, with session ids) and prints
a pass/fail line per test.
"""
import datetime as dt
import os
import sys

import pandas as pd
from cxas_scrapi.evals.turn_evals import TurnEvals
from cxas_scrapi.utils.rate_limiter import RateLimiter

from common import APP, ROOT
from demo_reset import reset

TESTS = ROOT / "turn_tests"


def main():
    wanted = sys.argv[1:]
    runner = TurnEvals(app_name=APP, rate_limiter=RateLimiter(float(os.environ.get("TURN_TESTS_RPM", "6"))))
    tests = runner.load_turn_tests_from_dir(str(TESTS))
    groups = {}
    for t in tests:
        profile = next(iter(t.tags), "P3")
        if not wanted or profile in wanted:
            groups.setdefault(profile, []).append(t)

    frames = []
    for profile, cases in groups.items():
        print(f"\n=== {profile}: {reset(profile)['lines']}")
        frames.append(runner.run_turn_tests(cases))
    results = pd.concat(frames, ignore_index=True)
    reset(os.environ.get("DEMO_PROFILE", "P3"))   # leave the demo account as a caller expects it

    out = ROOT / "runs" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    results.to_csv(out / "results.csv", index=False)
    by_test = results.groupby("test_name", sort=False)["status"].apply(lambda s: (s == "SUCCESS").all())
    print()
    for name, ok in by_test.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{int(by_test.sum())}/{len(by_test)} tests passed. Details: {out / 'results.csv'}")


if __name__ == "__main__":
    main()
