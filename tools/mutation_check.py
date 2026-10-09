"""Prove the test suite fails when the code is wrong.

    python tools/mutation_check.py

For each mutant below: copy the repo to a temp dir, inject the bug into the
copy, run pytest there, and require it to FAIL. An unmutated copy runs first
as a control and must PASS. The working tree is never modified.

Exits 0 only if the control passes and every mutant is killed. The verdict
reads pytest's exit code, never its output.
"""

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "*.db")

TESTS_FAILED = 1  # pytest's exit code for "ran, and some tests failed"


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str
    old: str
    new: str
    # An equivalent mutant changes nothing observable and MUST survive. If it
    # is killed, the suite is failing for some reason other than behaviour.
    equivalent: bool = False


MUTANTS = [
    Mutant(
        "canary-docstring-only",
        "app/services.py",
        '"""Tenant-scoped data access.',
        '"""Tenant-scoped data access (canary).',
        equivalent=True,
    ),
    Mutant(
        "drop-tenant-filter-get-work-order",
        "app/services.py",
        "select(WorkOrder).where(WorkOrder.id == wo_id, WorkOrder.tenant_id == tenant_id)",
        "select(WorkOrder).where(WorkOrder.id == wo_id)",
    ),
    Mutant(
        "drop-tenant-filter-list-work-orders",
        "app/services.py",
        "q = select(WorkOrder).where(WorkOrder.tenant_id == tenant_id)",
        "q = select(WorkOrder)",
    ),
    Mutant(
        "drop-tenant-filter-get-site",
        "app/services.py",
        "select(Site).where(Site.id == site_id, Site.tenant_id == tenant_id)",
        "select(Site).where(Site.id == site_id)",
    ),
    Mutant(
        "allow-done-to-open",
        "app/services.py",
        "Status.done: set(),",
        "Status.done: {Status.open},",
    ),
    Mutant(
        "unconditional-status-write",
        "app/services.py",
        ".where(WorkOrder.id == wo_id, WorkOrder.tenant_id == tenant_id, WorkOrder.status == current)",
        ".where(WorkOrder.id == wo_id, WorkOrder.tenant_id == tenant_id)",
    ),
    Mutant(
        "drop-csrf-guard",
        "app/routers/ui.py",
        '@router.post("/ui/work-orders/{wo_id}/status", dependencies=[Depends(require_htmx)])',
        '@router.post("/ui/work-orders/{wo_id}/status")',
    ),
    Mutant(
        "accept-blank-names",
        "app/schemas.py",
        "strip_whitespace=True, min_length=1, max_length=120",
        "strip_whitespace=True, min_length=0, max_length=120",
    ),
    Mutant(
        "unbounded-ids",
        "app/schemas.py",
        "MAX_ID = 2**31 - 1",
        "MAX_ID = 2**63 - 1",
    ),
    Mutant(
        "migration-default-drifts-from-model",
        "alembic/versions/0001_initial_schema.py",
        'sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False)',
        'sa.Column("created_at", sa.DateTime(), server_default=sa.text("\'2000-01-01\'"), nullable=False)',
    ),
]


class MutantDoesNotApply(Exception):
    pass


def apply(source: str, old: str, new: str) -> str:
    """Replace the one occurrence of `old`. Zero or several is an error."""
    count = source.count(old)
    if count != 1:
        raise MutantDoesNotApply(f"pattern found {count} times, expected 1: {old!r}")
    return source.replace(old, new)


def verdict(
    control_exit: int, mutant_exits: dict[str, int], equivalent: frozenset[str] | set[str] = frozenset()
) -> list[str]:
    """Problems with the run; an empty list means the suite has teeth."""
    if control_exit != 0:
        return ["control failed: the suite is red without any mutation"]
    problems = []
    for name, code in mutant_exits.items():
        if name in equivalent:
            if code != 0:
                problems.append(f"{name} was killed but changes no behaviour: the kills are not trustworthy")
        elif code == 0:
            problems.append(f"{name} survived: the suite passed with the bug in place")
        elif code != TESTS_FAILED:
            problems.append(f"{name} inconclusive: pytest exited {code}, not {TESTS_FAILED}")
    return problems


def run_suite(tree: Path) -> int:
    result = subprocess.run(
        # The mutation tool's own tests are excluded: in a mutated copy, the
        # test that every mutant still applies fails by construction, which
        # once made every mutant look killed whatever the app tests did.
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
         "--ignore=tests/test_mutation_check.py"],
        cwd=tree,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode


def run_on_copy(mutant: Mutant | None) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "repo"
        shutil.copytree(ROOT, tree, ignore=SKIP)
        if mutant is not None:
            target = tree / mutant.path
            target.write_text(apply(target.read_text(), mutant.old, mutant.new))
        return run_suite(tree)


def main() -> int:
    control = run_on_copy(None)
    print(f"  control (no mutation)              pytest exit {control}")
    exits = {}
    if control == 0:
        for m in MUTANTS:
            exits[m.name] = run_on_copy(m)
            print(f"  {m.name:36} pytest exit {exits[m.name]}")
    problems = verdict(control, exits, {m.name for m in MUTANTS if m.equivalent})
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        real = [m for m in MUTANTS if not m.equivalent]
        print(f"OK   control passed, equivalent canary survived, {len(real)} of {len(real)} mutants killed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
