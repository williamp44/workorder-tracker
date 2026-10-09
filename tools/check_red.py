"""RED first, checked: every new test must fail against the code before the change.

    python -m tools.check_red --base origin/main            # this branch vs main
    python -m tools.check_red --base fb28feb^ --head fb28feb  # audit one commit

Builds the base revision's code with HEAD's tests laid over it and runs them.
A test that is new at HEAD and already passes on the base code tests nothing
the change did: it was written after the code, or it cannot fail. Either way
the gate fails and names it.

A test that pins behaviour which must KEEP working is green on base by
design. It says so with `@pytest.mark.control("reason")`, and the reason is
required (tests/conftest.py refuses a control without one).

A test the base cannot even collect (the module under test did not exist yet)
counts as RED. A test skipped on base was never seen failing, so it does not.
Tests are matched by file name and test id, not directory, so moving a test
file does not make its tests new.

Verdict from pytest's JUnit XML, never from its console output.
"""

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def key(classname: str, name: str) -> str:
    """A test's identity across moves: file stem plus test id."""
    return f"{classname.rsplit('.', 1)[-1]}::{name}"


def verdict(new: set[str], base: dict[str, str], controls: frozenset[str]) -> list[str]:
    """Problems with the new tests; [] means every one was RED on base."""
    problems = []
    for test in sorted(new - controls):
        outcome = base.get(test, "RED")  # not collected on base: the code did not exist
        if outcome == "GREEN":
            problems.append(f"{test} passed before the change: it was not RED first, or it cannot fail")
        elif outcome == "SKIP":
            problems.append(f"{test} was skipped on base, so it was never seen failing")
    return problems


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _checkout(rev: str, dest: Path) -> None:
    archive = subprocess.run(["git", "archive", rev], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)


def _run(tree: Path) -> tuple[dict[str, str], frozenset[str]]:
    """({test: GREEN|RED|SKIP}, controls) for the suite in `tree`."""
    report = tree / ".check_red.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--continue-on-collection-errors", f"--junitxml={report}", "tests"],
        cwd=tree, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not report.exists():
        raise RuntimeError(f"pytest wrote no report in {tree}: the suite did not run at all")
    outcomes, controls = {}, set()
    for case in ET.parse(report).iter("testcase"):
        test = key(case.get("classname", ""), case.get("name", ""))
        if case.find("failure") is not None or case.find("error") is not None:
            outcomes[test] = "RED"
        elif case.find("skipped") is not None:
            outcomes[test] = "SKIP"
        else:
            outcomes[test] = "GREEN"
        if any(p.get("name") == "control" for p in case.iter("property")):
            controls.add(test)
    return outcomes, frozenset(controls)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the revision before the change")
    ap.add_argument("--head", default="HEAD", help="the revision with the change (default HEAD)")
    args = ap.parse_args(argv)
    base_rev = _git("merge-base", args.base, args.head)

    with tempfile.TemporaryDirectory() as h, tempfile.TemporaryDirectory() as b:
        head_tree, base_tree = Path(h), Path(b)
        _checkout(args.head, head_tree)
        _checkout(base_rev, base_tree)
        at_head, controls = _run(head_tree)
        existing, _ = _run(base_tree)
        # Base code, HEAD tests.
        subprocess.run(["rm", "-rf", str(base_tree / "tests")], check=True)
        subprocess.run(["cp", "-R", str(head_tree / "tests"), str(base_tree / "tests")], check=True)
        on_base, _ = _run(base_tree)

    new = set(at_head) - set(existing)
    not_green = sorted(t for t, o in at_head.items() if o != "GREEN")
    print(f"  base {base_rev[:8]}  head {args.head}")
    print(f"  {len(new)} new test(s), {len(new & controls)} declared control(s)")
    problems = verdict(new, on_base, controls)
    if not_green:
        problems += [f"{t} is not green at head" for t in not_green]
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print(f"OK   all {len(new - controls)} new test(s) were RED on the base code")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
