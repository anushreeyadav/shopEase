"""Run every component's tests, each in its own pytest process (no network, no MySQL needed).

Every service's package is called `app`, so the suites cannot share one interpreter.

    python scripts/run_tests.py                 # unit + api tests for the gateway and all services
    python scripts/run_tests.py -m unit         # one layer only (unit | api | integration)
    python scripts/run_tests.py --cov           # with line coverage per component

Database integration tests (`-m integration`) also need SHOPEASE_MYSQL_TESTS=1 and a disposable
MySQL (docs/database_setup.md). Cross-service tests: python scripts/run_integration.py.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = [
    "api_gateway",
    "services/auth_service",
    "services/user_service",
    "services/product_service",
    "services/order_service",
    "services/payment_service",
]
SUMMARY = re.compile(r"\d+ (passed|failed|skipped|deselected|error)")


def run(component: str, marker: str | None, cov: bool) -> tuple[bool, str]:
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    if marker:
        args += ["-m", marker]
    if cov:
        args += ["--cov=app", "--cov-report=term"]
    print(f"\n=== {component} ===", flush=True)
    result = subprocess.run(args, cwd=ROOT / component, capture_output=True, text=True)
    lines = [line for line in result.stdout.splitlines() if not line.startswith('{"ts"')]
    print("\n".join(lines[-30:] if cov else lines[-8:]))
    summary = next((line for line in reversed(lines) if SUMMARY.search(line)), "")
    # pytest exit code 5 = no tests selected for this marker: not a failure.
    return result.returncode in (0, 5), summary.strip("= ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-m", "--marker", help="run one layer: unit, api or integration")
    parser.add_argument("--cov", action="store_true", help="measure line coverage of each component's app package")
    args = parser.parse_args()

    results = {component: run(component, args.marker, args.cov) for component in COMPONENTS}
    print("\n=== Summary ===")
    for component, (passed, summary) in results.items():
        print(f"{'PASS' if passed else 'FAIL'}  {component:28} {summary}")
    return 0 if all(passed for passed, _ in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
