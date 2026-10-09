"""PreToolUse on Bash: block the two git commands that quietly destroy work.

Both were run by an AI agent in another project while the rules forbidding
them were written down and in its context. A rule that has to hold at one
tool call among hundreds does not survive as text, so it is enforced here.

  1. `git add -A` / `git add .` / `git add <directory>` stages everything,
     including another session's half-finished files and build artefacts.
     Stage explicit paths.
  2. `git checkout -- <path>` / `git restore <path>` over UNCOMMITTED changes
     discards them with no reflog. Used to undo a "break it and check the
     test fails" step, it destroyed an uncommitted fix. Verify on a copy.

Both stay allowed where they are safe: `git add` of named files, and a
restore of a file with nothing uncommitted.
"""

import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard_shared


class Denied(Exception):
    pass


def words(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd)
    except ValueError:  # unbalanced quotes: judge the plain split instead
        return cmd.split()


def check_add(w: list[str], cwd: str) -> None:
    args = [a for a in w[2:] if a != "--"]
    if any(a in ("-A", "--all", "-u", "--update") for a in args):
        raise Denied("`git add -A` / `--all` / `-u` stages everything, including files "
                     "nobody meant to commit. Stage the explicit paths this change touches.")
    for p in (a for a in args if not a.startswith("-")):
        if p in (".", "./", "*"):
            raise Denied(f"`git add {p}` stages everything. Run `git status --short` "
                         f"and name the files.")
        if os.path.isdir(os.path.join(cwd, p)):
            raise Denied(f"`git add {p}` stages a whole directory. Name the files.")


def check_restore(w: list[str], cwd: str) -> None:
    if w[1] == "checkout":
        if "--" not in w:
            return  # a branch switch destroys nothing
        paths = w[w.index("--") + 1:]
    else:  # every form of `git restore` overwrites the worktree
        after = w[2:]
        rest = after[after.index("--") + 1:] if "--" in after else after
        paths = [a for a in rest if not a.startswith("-")]
    if not paths:
        return
    # Fails CLOSED: a `git status` that will not run is not evidence that
    # there is nothing to lose.
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", *paths],
                           cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Denied(f"cannot tell whether {', '.join(paths[:4])} has uncommitted changes "
                     f"({type(exc).__name__}). Refusing rather than guessing.") from None
    if r.returncode != 0:
        raise Denied(f"`git status` exited {r.returncode}, so uncommitted changes cannot be "
                     f"ruled out. Refusing rather than guessing.")
    dirty = [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]
    if dirty:
        raise Denied(f"this would DISCARD uncommitted changes in {', '.join(dirty[:4])}, "
                     f"with no reflog. To undo a deliberate break, verify on a copy "
                     f"instead. To really discard, commit or stash first, explicitly.")


def main() -> int:
    data, why = guard_shared.payload(sys.stdin)
    if why or data is None:
        return 0  # not a payload this hook can judge; allowed, and distinguishable
    line = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    try:
        for cmd in guard_shared.commands(line):
            w = words(cmd)
            if len(w) < 2 or os.path.basename(w[0]) != "git":
                continue
            if w[1] == "add":
                check_add(w, cwd)
            elif w[1] in ("checkout", "restore"):
                check_restore(w, cwd)
    except Denied as exc:
        guard_shared.deny(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
