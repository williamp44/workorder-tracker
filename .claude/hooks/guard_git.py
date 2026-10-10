"""PreToolUse on Bash|PowerShell: block the git commands that quietly destroy work.

The first two were run by an AI agent in another project while the rules
forbidding them were written down and in its context. A rule that has to
hold at one tool call among hundreds does not survive as text, so it is
enforced here.

  1. `git add -A` / `git add .` / `git add <directory>` stages everything,
     including another session's half-finished files and build artefacts.
     Stage explicit paths.
  2. Every form that overwrites UNCOMMITTED work with no reflog: `checkout`
     of paths (with or without `--`), `restore`, `checkout -f`, `switch
     -f/--discard-changes`, `reset --hard`, `stash drop/clear`, and `clean
     -f` over untracked (with -x, also ignored) files. Used to undo a "break
     it and check the test fails" step, one destroyed an uncommitted fix.
     Verify on a copy.

Each stays allowed where it is safe: `git add` of named files, a branch
switch, `restore --staged` (index only), and any discard form when there is
nothing uncommitted for it to destroy. A `git status` that cannot run is not
evidence that there is nothing to lose, so those checks fail CLOSED.

FINDING GIT. Bash and PowerShell both reach this hook (F1), and git hides
in more places than the first word. It is found past git's global options
(`git -C . add`, `-c x=y`, `--no-pager`), as `git.exe`, behind `env`, `&`,
`command`, `exec` and `cmd /c`, inside `bash|sh|pwsh|powershell -c "<s>"`,
inside `$( ... )`, after a `cd`/`Set-Location` earlier in the same line,
and behind a repo-local alias (expanded once).

STATED LIMITS, NOT PARSED: `eval`, scripts, `Start-Process git -ArgumentList
...` (allowed in the probe), backtick command substitution, shell aliases
(`!cmd`) and aliases defined outside the repo. This is a table-driven guard,
not a shell parser.
"""

import json
import os
import re
import subprocess
import sys
from types import MappingProxyType


def refuse_crash(exc: BaseException) -> None:
    """A crashed PreToolUse hook exits 1, which lets the call through. So a
    crash refuses instead (US-011). Inline, not guard_shared.deny: the import
    of guard_shared may be what failed. Edit is not judged here, so the
    agent can still repair the hook."""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (f"guard_git crashed ({type(exc).__name__}: {exc}): refusing "
                                     f"rather than guessing. Fix the hook through Edit."),
    }}))


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_shared
    from guard_shared import CD, SHELLS, program, shell_script, short_flags, subshells, unwrap, words
except Exception as import_error:  # a half-edited sibling must not switch this guard off
    refuse_crash(import_error)
    sys.exit(0)

# git's global options that take a value as the next word, and those that do not.
GIT_OPTS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
GIT_FLAGS = ("--no-pager", "-P", "--paginate", "-p", "--bare", "--literal-pathspecs",
             "--no-replace-objects", "--no-optional-locks")
MAX_DEPTH = 4  # nested shells and $( ) deeper than this are not followed
TOP_PATHSPEC = re.compile(r"^:(?:/|\((?:[^)]*,)?top\b)")
# Subcommands an alias cannot shadow, so no `git config` lookup is needed.
BUILTINS = frozenset((
    "add", "checkout", "restore", "switch", "reset", "clean", "stash", "status", "log",
    "diff", "show", "commit", "push", "pull", "fetch", "branch", "merge", "rebase", "tag",
    "remote", "config", "rev-parse", "ls-files", "blame", "grep", "init", "clone",
    "worktree", "cherry-pick", "revert", "describe", "reflog", "mv", "rm",
))


class Denied(Exception):
    pass


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


def git_out(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)


def expand_alias(w: list[str], cwd: str) -> list[str]:
    """`git aa` with repo config `alias.aa = add -A` -> `git add -A`, once."""
    if len(w) < 2 or w[1].startswith("-") or w[1] in BUILTINS:
        return w
    try:
        r = git_out(cwd, "config", "--get", f"alias.{w[1]}")
    except (OSError, subprocess.SubprocessError):
        return w
    body = r.stdout.strip()
    if r.returncode != 0 or not body or body.startswith("!"):
        return w
    return ["git", *words(body), *w[2:]]


def is_ref(cwd: str, name: str) -> bool:
    try:
        return git_out(cwd, "rev-parse", "--verify", "--quiet", name).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def status(cwd: str, *args: str) -> list[str]:
    """`git status --porcelain <args>` lines. Fails CLOSED."""
    try:
        r = git_out(cwd, "status", "--porcelain", *args)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Denied(f"cannot tell whether there are uncommitted changes "
                     f"({type(exc).__name__}). Refusing rather than guessing.") from None
    if r.returncode != 0:
        raise Denied(f"`git status` exited {r.returncode}, so uncommitted changes cannot be "
                     f"ruled out. Refusing rather than guessing.")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def refuse_if_dirty(w: list[str], cwd: str, paths: list[str] | None = None) -> None:
    dirty = [ln[3:] for ln in status(cwd, *(["--", *paths] if paths else []))]
    if dirty:
        raise Denied(f"`{' '.join(w)}` would DISCARD uncommitted changes in "
                     f"{', '.join(dirty[:4])}, with no reflog. To undo a deliberate break, "
                     f"verify on a copy instead. To really discard, commit or stash first, "
                     f"explicitly.")


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


def check_checkout(w: list[str], cwd: str) -> None:
    args = w[2:]
    if "--" in args:
        paths = args[args.index("--") + 1:]
        if paths:
            refuse_if_dirty(w, cwd, paths)
        return
    if any(a in ("-f", "--force") for a in args):
        refuse_if_dirty(w, cwd)
        return
    if any(a in ("-b", "-B", "--orphan") for a in args):
        return  # creates a branch
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        return
    # Without `--`, git reads `<ref> <path>...` or `<path>...`: path mode
    # whenever a word names a path, which destroys exactly what `--` would.
    first_is_ref = is_ref(cwd, positional[0])
    if first_is_ref and len(positional) == 1:
        return  # a branch switch keeps local changes, or refuses
    candidates = positional[1:] if first_is_ref else positional
    paths = [p for p in candidates if p == "." or os.path.exists(os.path.join(cwd, p))]
    if paths:
        refuse_if_dirty(w, cwd, paths)


def check_restore(w: list[str], cwd: str) -> None:
    after = w[2:]
    opts = [a for a in (after[:after.index("--")] if "--" in after else after) if a.startswith("-")]
    staged = "--staged" in opts or "S" in short_flags(opts)
    worktree = "--worktree" in opts or "W" in short_flags(opts)
    if staged and not worktree:
        return  # index only; the worktree copy is untouched
    rest = after[after.index("--") + 1:] if "--" in after else after
    paths = [a for a in rest if not a.startswith("-")]
    if paths:
        refuse_if_dirty(w, cwd, paths)


def check_force(w: list[str], cwd: str) -> None:
    """switch -f/--discard-changes, reset --hard, stash drop/clear."""
    args = w[2:]
    forced = {
        "switch": any(a in ("-f", "--force", "--discard-changes") for a in args),
        "reset": "--hard" in args,
        "stash": bool(args) and args[0] in ("drop", "clear"),
    }[w[1]]
    if forced:
        refuse_if_dirty(w, cwd)


def check_clean(w: list[str], cwd: str) -> None:
    args = w[2:]
    flags = short_flags(args)
    if "--force" not in args and "f" not in flags:
        return
    ignored = "x" in flags or "X" in flags
    lines = status(cwd, "--untracked-files=all", *(["--ignored"] if ignored else []))
    doomed = [ln[3:] for ln in lines if ln.startswith(("??", "!!"))]
    if doomed:
        raise Denied(f"`{' '.join(w)}` would DELETE untracked files, which git cannot bring "
                     f"back: {', '.join(doomed[:4])}. Move them aside or name them.")


CHECKS = MappingProxyType({
    "add": check_add,
    "checkout": check_checkout,
    "restore": check_restore,
    "switch": check_force,
    "reset": check_force,
    "stash": check_force,
    "clean": check_clean,
})


FILTERS = ("tail", "head", "grep", "sort", "select-string", "select-object", "findstr")


def is_commit_or_push(segment: str, cwd: str) -> bool:
    found = git_argv(unwrap(words(segment)), cwd)
    return found is not None and len(found[0]) > 1 and found[0][1] in ("commit", "push")


def check_gated_commits(line: str, cwd: str) -> None:
    """Refuse `<check> | <filter> && git commit` (US-014).

    A pipeline's exit status is its LAST stage's, so `&&` sees the filter's
    0, and a failing check still commits. A warning about this was read past
    every time; a refusal cannot be. `set -o pipefail` earlier in the line
    makes the pipeline fail with its producer, and is allowed."""
    pipefail = False
    for statement in guard_shared.split_unquoted(guard_shared.without_heredocs(line), (";", "\n")):
        w = words(statement)
        if w[:1] == ["set"] and "pipefail" in w:
            pipefail = True
        gate = None
        for segment in guard_shared.split_unquoted(statement, ("&&", "||")):
            if gate and is_commit_or_push(segment, cwd):
                raise Denied(f"this commit is gated on {gate[1]}'s exit status, not on "
                             f"{gate[0]}'s. A failing run would still commit. Add "
                             f"'set -o pipefail;' or run the check and the commit as "
                             f"separate commands.")
            stages = guard_shared.split_unquoted(segment, ("|",))
            last = unwrap(words(stages[-1])) if len(stages) > 1 else []
            if last and program(last[0]) in FILTERS and not pipefail:
                gate = (words(stages[0])[0] if words(stages[0]) else stages[0], last[0])


def judge(line: str, cwd: str, depth: int = 0) -> None:
    """Raise Denied if any command in `line`, wherever git hides in it, destroys work."""
    if depth > MAX_DEPTH:
        return
    check_gated_commits(line, cwd)
    for body in subshells(guard_shared.without_heredocs(line)):
        judge(body, cwd, depth + 1)
    for cmd in guard_shared.commands(line):
        w = unwrap(words(cmd))
        if w and program(w[0]) in CD:
            target = [a for a in w[1:] if not a.startswith("-")]
            if target:
                cwd = os.path.join(cwd, target[0])  # later commands in this line run there
            continue
        if w and program(w[0]) in SHELLS:
            script = shell_script(w)
            if script:
                judge(script, cwd, depth + 1)
            continue
        found = git_argv(w, cwd)
        if found is None or len(found[0]) < 2:
            continue
        w, git_cwd = found
        w = expand_alias(w, git_cwd)
        if len(w) >= 2 and w[1] in CHECKS:
            CHECKS[w[1]](w, git_cwd)


def judge_payload() -> None:
    data, why = guard_shared.payload(sys.stdin)
    if why or data is None:
        return  # not a payload this hook can judge; allowed, and distinguishable
    line = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    try:
        judge(line, cwd)
    except Denied as exc:
        guard_shared.deny(str(exc))


def main() -> int:
    try:
        judge_payload()
    except Exception as exc:
        refuse_crash(exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
