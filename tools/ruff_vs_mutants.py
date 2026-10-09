"""Does ruff see the bugs the test suite is required to catch?

    python tools/ruff_vs_mutants.py

Runs `ruff check` on the current tree, then on a copy with each mutant from
tools/mutation_check.py applied, and prints the findings ruff adds for each.
A rule that adds a finding on a mutant can see that defect class. A rule
that adds nothing is blind to it, however clean the current tree looks.

A measurement, not a gate: always exits 0 unless ruff itself fails to run.
"""

import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from tools.mutation_check import MUTANTS, ROOT, SKIP, Mutant, apply


def findings(tree: Path) -> Counter[str]:
    """Ruff findings as 'path:rule message', line numbers dropped so a
    finding is still the same finding when a mutant shifts lines.  A Counter,
    not a set: seven identical messages in one file are seven findings."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format", "concise", "--quiet", "."],
        cwd=tree,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):  # 0 clean, 1 findings, else ruff broke
        raise RuntimeError(f"ruff exited {result.returncode}: {result.stderr}")
    out: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        path, _, _, rest = line.split(":", 3)
        out[f"{path}:{rest.strip()}"] += 1
    return out


def on_copy(mutant: Mutant | None) -> Counter[str]:
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "repo"
        shutil.copytree(ROOT, tree, ignore=SKIP)
        if mutant is not None:
            target = tree / mutant.path
            target.write_text(apply(target.read_text(), mutant.old, mutant.new))
        return findings(tree)


def main() -> int:
    base = on_copy(None)
    print(f"  current tree: {base.total()} finding(s)")
    seen = 0
    for m in MUTANTS:
        added = sorted((on_copy(m) - base).elements())
        seen += bool(added)
        print(f"  {m.name:36} +{len(added)}  {'; '.join(added)}")
    print(f"  ruff adds a finding on {seen} of {len(MUTANTS)} mutants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
