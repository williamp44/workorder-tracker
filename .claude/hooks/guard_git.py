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

FINDING GIT. Bash and PowerShell both reach this hook (F1), and git hides
in more places than the first word. It is found past git's global options
(`git -C . add`, `-c x=y`, `--no-pager`), as `git.exe`, behind `env`, `&`,
`command`, `exec` and `cmd /c`, inside `bash|sh|pwsh|powershell -c "<s>"`,
and inside `$( ... )`.

STATED LIMITS, NOT PARSED: `eval`, scripts, `Start-Process git -ArgumentList
...` (allowed in the probe), backtick command substitution, and aliases
defined outside the repo. This is a table-driven guard, not a shell parser.
"""

import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard_shared

# git's global options that take a value as the next word, and those that do not.
GIT_OPTS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
GIT_FLAGS = ("--no-pager", "-P", "--paginate", "-p", "--bare", "--literal-pathspecs",
             "--no-replace-objects", "--no-optional-locks")
SHELLS = ("bash", "sh", "zsh", "dash", "pwsh", "powershell")
PREFIXES = ("&", "command", "exec")
MAX_DEPTH = 4  # nested shells and $( ) deeper than this are not followed
TOP_PATHSPEC = re.compile(r"^:(?:/|\((?:[^)]*,)?top\b)")


class Denied(Exception):
    pass


def words(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd)
    except ValueError:  # unbalanced quotes: judge the plain split instead
        return cmd.split()


def program(word: str) -> str:
    """`/usr/bin/git`, `git.exe`, `C:\\...\\Git.EXE` -> `git`."""
    name = os.path.basename(word.replace("\\", "/")).casefold()
    return name[:-4] if name.endswith(".exe") else name


def unwrap(w: list[str]) -> list[str]:
    """Drop the prefixes that run the rest of the line as a command."""
    while w:
        head = program(w[0])
        if head in PREFIXES:
            w = w[1:]
        elif head == "env":
            w = w[1:]
            while w and ("=" in w[0] or w[0].startswith("-")):
                w = w[1:]
        elif head == "cmd" and len(w) > 1 and w[1].casefold() == "/c":
            w = w[2:]
        else:
            return w
    return w


def shell_script(w: list[str]) -> str | None:
    """The `<s>` of `bash -c "<s>"` / `pwsh -Command "<s>"`; None if there is none."""
    for i, a in enumerate(w[1:], 1):
        flag = a.casefold()
        if flag in ("-c", "-command") or (flag.startswith("-") and not flag.startswith("--")
                                          and "c" in flag[1:] and program(w[0]) in SHELLS[:4]):
            return " ".join(w[i + 1:])
    return None


def subshells(line: str) -> list[str]:
    """The body of each `$( ... )` outside single quotes, where the shell runs it."""
    bodies, quote, i = [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            quote = None if ch == quote else quote
        elif ch == "'":
            quote = ch
        elif line.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(line) and depth:
                depth += {"(": 1, ")": -1}.get(line[j], 0)
                j += 1
            bodies.append(line[i + 2:j - 1] if depth == 0 else line[i + 2:])
            i = j
            continue
        i += 1
    return bodies


def git_argv(w: list[str], cwd: str) -> tuple[list[str], str] | None:
    """(`git <subcommand> ...` with global options removed, the dir git runs in);
    None when this is not git."""
    if not w or program(w[0]) != "git":
        return None
    i = 1
    while i < len(w):
        a = w[i]
        if a in GIT_OPTS_WITH_VALUE:
            if a == "-C" and i + 1 < len(w):
                cwd = os.path.join(cwd, w[i + 1])
            i += 2
        elif a in GIT_FLAGS or a.startswith(tuple(f"{o}=" for o in GIT_OPTS_WITH_VALUE[2:])):
            i += 1
        else:
            break
    return ["git", *w[i:]], cwd


def check_add(w: list[str], cwd: str) -> None:
    args = [a for a in w[2:] if a != "--"]
    short = [a for a in args if a.startswith("-") and not a.startswith("--")]
    if (any(a in ("--all", "--update") for a in args)
            or any("A" in a[1:] or "u" in a[1:] for a in short)):
        raise Denied("`git add -A` / `--all` / `-u` stages everything, including files "
                     "nobody meant to commit. Stage the explicit paths this change touches.")
    for p in (a for a in args if not a.startswith("-")):
        if TOP_PATHSPEC.match(p):
            raise Denied(f"`git add {p}` stages everything from the top of the repo. "
                         f"Name the files.")
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


def judge(line: str, cwd: str, depth: int = 0) -> None:
    """Raise Denied if any command in `line`, wherever git hides in it, destroys work."""
    if depth > MAX_DEPTH:
        return
    for body in subshells(guard_shared.without_heredocs(line)):
        judge(body, cwd, depth + 1)
    for cmd in guard_shared.commands(line):
        w = unwrap(words(cmd))
        if w and program(w[0]) in SHELLS:
            script = shell_script(w)
            if script:
                judge(script, cwd, depth + 1)
            continue
        found = git_argv(w, cwd)
        if found is None or len(found[0]) < 2:
            continue
        w, git_cwd = found
        if w[1] == "add":
            check_add(w, git_cwd)
        elif w[1] in ("checkout", "restore"):
            check_restore(w, git_cwd)


def main() -> int:
    data, why = guard_shared.payload(sys.stdin)
    if why or data is None:
        return 0  # not a payload this hook can judge; allowed, and distinguishable
    line = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    try:
        judge(line, cwd)
    except Denied as exc:
        guard_shared.deny(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
