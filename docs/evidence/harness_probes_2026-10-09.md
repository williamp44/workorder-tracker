# Harness probes, 2026-10-09 (BEFORE and AFTER the fixes)

Run on Windows 11, Git Bash, Python 3.14.3, branch `main` at 8209a76. Each script feeds synthetic payloads to a hook (nothing is executed against the repo) and prints the hook's decision next to the expected one. These are the oracles for PRD_HARNESS_HARDENING.md. `want=None` rows are recorded, not judged. Paths in the scripts are absolute to this checkout.

## probe_git.py

```python
import json, subprocess, sys, os, tempfile
HOOK = r"C:/dev/workorder-tracker/.claude/hooks/guard_git.py"
# A throwaway repo with one dirty tracked file and one subdir, so dirty-path checks are real.
repo = tempfile.mkdtemp()
def g(*a): subprocess.run(["git", *a], cwd=repo, capture_output=True, check=True)
g("init"); g("config","user.email","p@p"); g("config","user.name","p")
os.makedirs(os.path.join(repo,"sub")); open(os.path.join(repo,"f.txt"),"w").write("a")
open(os.path.join(repo,"sub","x.txt"),"w").write("a"); g("add","f.txt","sub/x.txt"); g("commit","-m","i")
open(os.path.join(repo,"f.txt"),"w").write("DIRTY")
CASES = [
 # (command, should_deny)
 ("git add -A", True), ("git add .", True), ("git add sub", True), ("git add f.txt", False),
 ("git checkout -- f.txt", True), ("git restore f.txt", True),
 ("git commit -m 'mention git add -A here'", False), ('grep -E "a|b" f.txt', False),
 # suspected gaps
 ("git -C . add -A", True), ("git.exe add -A", True), ("git add :/", True), ("git add -- :/", True),
 ("git add --all", True), ("git add -Av", True), ("git add *.txt", None),
 ("git checkout f.txt", True), ("git checkout HEAD f.txt", True), ("git checkout . ", True),
 ("git reset --hard", True), ("git clean -fdx", True), ("git stash drop", True),
 ("git restore --staged f.txt", False),
 ('bash -c "git add -A"', True), ("sh -c 'git checkout -- f.txt'", True),
 ("$(git add -A)", True), ("cd sub && git add .", True), ("env git add -A", True),
 ("git commit -am wip", None), ("git -c core.x=1 add -A", True),
]
miss = 0
for cmd, want in CASES:
    p = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_name":"Bash","tool_input":{"command":cmd},"cwd":repo}),
                       capture_output=True, text=True)
    denied = '"deny"' in p.stdout
    flag = "" if want is None or want == denied else "  <-- MISMATCH"
    miss += bool(flag)
    print(f"{'DENY ' if denied else 'allow'}  {cmd!r:45}{flag}")
print(f"mismatches: {miss}")
```

Output:

```
DENY   'git add -A'                                 
DENY   'git add .'                                  
DENY   'git add sub'                                
allow  'git add f.txt'                              
DENY   'git checkout -- f.txt'                      
DENY   'git restore f.txt'                          
allow  "git commit -m 'mention git add -A here'"    
allow  'grep -E "a|b" f.txt'                        
allow  'git -C . add -A'                              <-- MISMATCH
allow  'git.exe add -A'                               <-- MISMATCH
allow  'git add :/'                                   <-- MISMATCH
allow  'git add -- :/'                                <-- MISMATCH
DENY   'git add --all'                              
allow  'git add -Av'                                  <-- MISMATCH
allow  'git add *.txt'                              
allow  'git checkout f.txt'                           <-- MISMATCH
allow  'git checkout HEAD f.txt'                      <-- MISMATCH
allow  'git checkout . '                              <-- MISMATCH
allow  'git reset --hard'                             <-- MISMATCH
allow  'git clean -fdx'                               <-- MISMATCH
allow  'git stash drop'                               <-- MISMATCH
DENY   'git restore --staged f.txt'                   <-- MISMATCH
allow  'bash -c "git add -A"'                         <-- MISMATCH
allow  "sh -c 'git checkout -- f.txt'"                <-- MISMATCH
allow  '$(git add -A)'                                <-- MISMATCH
DENY   'cd sub && git add .'                        
allow  'env git add -A'                               <-- MISMATCH
allow  'git commit -am wip'                         
allow  'git -c core.x=1 add -A'                       <-- MISMATCH
mismatches: 17
```

## probe_git2.py

```python
"""guard_git round 2: discard-forms, aliases, cwd drift, and PowerShell syntax."""
import json
import os
import subprocess
import sys
import tempfile

HOOK = "C:/dev/workorder-tracker/.claude/hooks/guard_git.py"
repo = tempfile.mkdtemp()


def g(*a):
    subprocess.run(["git", *a], cwd=repo, capture_output=True, check=True)


g("init")
g("config", "user.email", "p@p")
g("config", "user.name", "p")
os.makedirs(os.path.join(repo, "sub"))
for f in ("f.txt", "sub/x.txt"):
    open(os.path.join(repo, f), "w").write("a")
g("add", "f.txt", "sub/x.txt")
g("commit", "-m", "i")
g("config", "alias.aa", "add -A")
open(os.path.join(repo, "sub", "x.txt"), "w").write("DIRTY")  # only sub/x.txt dirty

CASES = [
    # discard forms (all destroy the dirty sub/x.txt)
    ("git checkout -f", True), ("git switch --discard-changes main", True),
    ("git checkout -p -- sub/x.txt", True), ("git restore --worktree sub/x.txt", True),
    ("git restore -s HEAD sub/x.txt", True),
    # cwd drift: hook runs `git status` in the payload cwd, not after `cd`
    ("cd sub && git checkout -- x.txt", True), ("cd sub && git restore x.txt", True),
    # alias defined in repo config
    ("git aa", True),
    # PowerShell syntax
    ("git add -A; git status", True), ("& git add -A", True), ("git add -A 2>$null", True),
    ("cmd /c git add -A", True), ("Start-Process git -ArgumentList 'add','-A'", True),
    ("git add `\n -A", True), ("git checkout -- 'sub/x.txt'", True),
    # should stay allowed
    ("git status", False), ("git checkout main", False), ("git add sub/x.txt", False),
    ("git log -- .", False), ("git diff -- sub", False),
]
miss = 0
for cmd, want in CASES:
    p = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"tool_name": "PowerShell", "tool_input": {"command": cmd}, "cwd": repo}),
                       capture_output=True, text=True)
    d = '"deny"' in p.stdout
    flag = "" if want == d else "  <-- MISMATCH"
    miss += bool(flag)
    print(f"{'DENY ' if d else 'allow'}  {cmd!r:48}{flag}")
print("mismatches:", miss, "of", len(CASES))
```

Output:

```
allow  'git checkout -f'                                 <-- MISMATCH
allow  'git switch --discard-changes main'               <-- MISMATCH
DENY   'git checkout -p -- sub/x.txt'                  
DENY   'git restore --worktree sub/x.txt'              
DENY   'git restore -s HEAD sub/x.txt'                 
allow  'cd sub && git checkout -- x.txt'                 <-- MISMATCH
allow  'cd sub && git restore x.txt'                     <-- MISMATCH
allow  'git aa'                                          <-- MISMATCH
DENY   'git add -A; git status'                        
allow  '& git add -A'                                    <-- MISMATCH
DENY   'git add -A 2>$null'                            
allow  'cmd /c git add -A'                               <-- MISMATCH
allow  "Start-Process git -ArgumentList 'add','-A'"      <-- MISMATCH
allow  'git add `\n -A'                                  <-- MISMATCH
DENY   "git checkout -- 'sub/x.txt'"                   
allow  'git status'                                    
allow  'git checkout main'                             
allow  'git add sub/x.txt'                             
allow  'git log -- .'                                  
allow  'git diff -- sub'                               
mismatches: 9 of 20
```

## probe_gates.py

```python
import json
import subprocess
import sys

HOOK = r"C:/dev/workorder-tracker/.claude/hooks/guard_gates.py"
R = "C:\\dev\\workorder-tracker\\"
CASES = [
    ("Edit", R + ".claude\\hooks\\guard_git.py", True),
    ("Write", R + ".claude\\settings.json", True),
    ("Edit", R + ".github\\workflows\\ci.yml", True),
    ("Edit", R + "ruff.toml", True),
    ("Edit", R + "tools\\mutation_check.py", True),
    ("Edit", R + "app\\services.py", False),
    ("Edit", R + "tests\\unit\\test_rules.py", False),
    # suspected gaps: files that decide correctness but are not listed
    ("Write", R + ".claude\\settings.local.json", True),
    ("Edit", R + "tools\\check_red.py", True),
    ("Edit", R + "tools\\check_fp.py", True),
    ("Edit", R + "tools\\check_types.py", True),
    ("Edit", R + "tools\\isolation.py", True),
    ("Edit", R + "tests\\conftest.py", True),
    ("Edit", R + "pyproject.toml", True),
    ("Edit", R + "tests\\spec.py", None),
    # case-insensitive filesystem
    ("Edit", R + ".Claude\\Hooks\\guard_git.py", True),
    ("Edit", R + "RUFF.TOML", True),
    ("Edit", R + "Tools\\Mutation_Check.py", True),
    # tool the matcher never routes here
    ("NotebookEdit", R + ".claude\\hooks\\x.py", True),
    # user-level settings can disable every hook
    ("Write", "C:\\Users\\wh429\\.claude\\settings.json", True),
]
miss = 0
for tool, path, want in CASES:
    p = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"tool_name": tool, "tool_input": {"file_path": path}}),
                       capture_output=True, text=True)
    d = '"deny"' in p.stdout
    flag = "" if want is None or want == d else "  <-- MISMATCH"
    miss += bool(flag)
    print(f"{'DENY ' if d else 'allow'} {tool:12} {path.replace(R, ''):45}{flag}")
print("mismatches:", miss)
```

Output:

```
DENY  Edit         .claude\hooks\guard_git.py                   
DENY  Write        .claude\settings.json                        
DENY  Edit         .github\workflows\ci.yml                     
DENY  Edit         ruff.toml                                    
DENY  Edit         tools\mutation_check.py                      
allow Edit         app\services.py                              
allow Edit         tests\unit\test_rules.py                     
allow Write        .claude\settings.local.json                    <-- MISMATCH
allow Edit         tools\check_red.py                             <-- MISMATCH
allow Edit         tools\check_fp.py                              <-- MISMATCH
allow Edit         tools\check_types.py                           <-- MISMATCH
allow Edit         tools\isolation.py                             <-- MISMATCH
allow Edit         tests\conftest.py                              <-- MISMATCH
allow Edit         pyproject.toml                                 <-- MISMATCH
allow Edit         tests\spec.py                                
allow Edit         .Claude\Hooks\guard_git.py                     <-- MISMATCH
allow Edit         RUFF.TOML                                      <-- MISMATCH
allow Edit         Tools\Mutation_Check.py                        <-- MISMATCH
allow NotebookEdit .claude\hooks\x.py                             <-- MISMATCH
DENY  Write        C:\Users\wh429\.claude\settings.json         
mismatches: 11
```

## probe_scan.py

```python
"""Precision probe for diagnostic_scan: green gate output must produce 0 hits;
reading a source file is not a diagnostic, so report how often `cat` trips it."""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path("C:/dev/workorder-tracker")
HOOKS = ROOT / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("ds", HOOKS / "diagnostic_scan.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

PY = sys.executable
GREEN = {
    "pytest -v": [PY, "-m", "pytest", "-v", "-p", "no:cacheprovider"],
    "ruff check .": [PY, "-m", "ruff", "check", "--no-cache", "."],
    "check_fp": [PY, "-m", "tools.check_fp"],
    "check_types": [PY, "-m", "tools.check_types"],
    "complexity": [PY, "-m", "tools.complexity"],
    "git status/log": ["git", "log", "--oneline", "-20"],
}
print("== green gate output (want 0 hits each)")
for name, cmd in GREEN.items():
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    hits = ds.scan(r.stdout + "\n" + r.stderr)
    print(f"  {name:16} exit={r.returncode} lines={len((r.stdout + r.stderr).splitlines()):5} hits={len(hits)}")
    for h in hits[:3]:
        print(f"      L{h[0]} {h[1][:100]!r} <- {h[2]}")

print("== reading files (cat): hits per file")
files = sorted(p for top in ("app", "tools", "tests", ".claude/hooks", "docs") for p in (ROOT / top).rglob("*")
               if p.suffix in (".py", ".md") and "__pycache__" not in p.parts)
tripped = 0
for f in files:
    hits = ds.scan(f.read_text(encoding="utf-8"))
    if hits:
        tripped += 1
        print(f"  {f.relative_to(ROOT).as_posix():50} {len(hits)}")
print(f"  {tripped} of {len(files)} files trip the scanner when merely read")
```

Output:

```
== green gate output (want 0 hits each)
  pytest -v        exit=0 lines=  226 hits=0
  ruff check .     exit=0 lines=    1 hits=0
  check_fp         exit=0 lines=    1 hits=0
  check_types      exit=0 lines=    3 hits=0
  complexity       exit=0 lines=    2 hits=0
  git status/log   exit=0 lines=   20 hits=0
== reading files (cat): hits per file
  .claude/hooks/diagnostic_scan.py                   10
  docs/CHECKS.md                                     2
  tests/integration/test_diagnostic_scan.py          7
  3 of 49 files trip the scanner when merely read
```

# AFTER the fixes, 2026-10-09

Each probe above, copied out of this file unchanged and re-run against `.claude/hooks` at `8d8fc99`
(US-008), with `GATE_EDIT` unset. With `GATE_EDIT=1` inherited, `probe_gates` reports 17 mismatches,
because the launch override opens every gate: run the probes without it.

## probe_git.py (AFTER)

```
DENY   'git add -A'                                 
DENY   'git add .'                                  
DENY   'git add sub'                                
allow  'git add f.txt'                              
DENY   'git checkout -- f.txt'                      
DENY   'git restore f.txt'                          
allow  "git commit -m 'mention git add -A here'"    
allow  'grep -E "a|b" f.txt'                        
DENY   'git -C . add -A'                            
DENY   'git.exe add -A'                             
DENY   'git add :/'                                 
DENY   'git add -- :/'                              
DENY   'git add --all'                              
DENY   'git add -Av'                                
allow  'git add *.txt'                              
DENY   'git checkout f.txt'                         
DENY   'git checkout HEAD f.txt'                    
DENY   'git checkout . '                            
DENY   'git reset --hard'                           
allow  'git clean -fdx'                               <-- MISMATCH
DENY   'git stash drop'                             
allow  'git restore --staged f.txt'                 
DENY   'bash -c "git add -A"'                       
DENY   "sh -c 'git checkout -- f.txt'"              
DENY   '$(git add -A)'                              
DENY   'cd sub && git add .'                        
DENY   'env git add -A'                             
allow  'git commit -am wip'                         
DENY   'git -c core.x=1 add -A'                     
mismatches: 1
```

## probe_git2.py (AFTER)

```
DENY   'git checkout -f'                               
DENY   'git switch --discard-changes main'             
DENY   'git checkout -p -- sub/x.txt'                  
DENY   'git restore --worktree sub/x.txt'              
DENY   'git restore -s HEAD sub/x.txt'                 
DENY   'cd sub && git checkout -- x.txt'               
DENY   'cd sub && git restore x.txt'                   
DENY   'git aa'                                        
DENY   'git add -A; git status'                        
DENY   '& git add -A'                                  
DENY   'git add -A 2>$null'                            
DENY   'cmd /c git add -A'                             
allow  "Start-Process git -ArgumentList 'add','-A'"      <-- MISMATCH
DENY   'git add `\n -A'                                
DENY   "git checkout -- 'sub/x.txt'"                   
allow  'git status'                                    
allow  'git checkout main'                             
allow  'git add sub/x.txt'                             
allow  'git log -- .'                                  
allow  'git diff -- sub'                               
mismatches: 1 of 20
```

## probe_gates.py (AFTER)

```
DENY  Edit         .claude\hooks\guard_git.py                   
DENY  Write        .claude\settings.json                        
DENY  Edit         .github\workflows\ci.yml                     
DENY  Edit         ruff.toml                                    
DENY  Edit         tools\mutation_check.py                      
allow Edit         app\services.py                              
allow Edit         tests\unit\test_rules.py                     
DENY  Write        .claude\settings.local.json                  
DENY  Edit         tools\check_red.py                           
DENY  Edit         tools\check_fp.py                            
DENY  Edit         tools\check_types.py                         
DENY  Edit         tools\isolation.py                           
DENY  Edit         tests\conftest.py                            
DENY  Edit         pyproject.toml                               
allow Edit         tests\spec.py                                
DENY  Edit         .Claude\Hooks\guard_git.py                   
DENY  Edit         RUFF.TOML                                    
DENY  Edit         Tools\Mutation_Check.py                      
DENY  NotebookEdit .claude\hooks\x.py                           
DENY  Write        C:\Users\wh429\.claude\settings.json         
mismatches: 0
```

## probe_scan.py (AFTER)

```
== green gate output (want 0 hits each)
  pytest -v        exit=0 lines=  373 hits=0
  ruff check .     exit=0 lines=    1 hits=0
  check_fp         exit=0 lines=    1 hits=0
  check_types      exit=0 lines=    3 hits=0
  complexity       exit=0 lines=    3 hits=0
  git status/log   exit=0 lines=   20 hits=0
== reading files (cat): hits per file
  .claude/hooks/diagnostic_scan.py                   10
  docs/CHECKS.md                                     3
  tests/integration/test_diagnostic_scan.py          7
  3 of 51 files trip the scanner when merely read
```

### The two remaining mismatches are in the probes, not the guards

- `probe_git`: `git clean -fdx` is **allowed**, and that is right. The probe's repo has a dirty
  *tracked* file but no untracked or ignored files, so `clean` has nothing to delete. US-006 refuses
  `clean -f` only when it would delete something (`git status --porcelain --untracked-files=all`,
  plus `--ignored` for `-x`). The probe's `True` predates that rule. The refusing case is
  `test_us006_refuses_on_a_dirty_tree[git clean -fdx]` in `tests/integration/test_guard_git.py`.
- `probe_git2`: `Start-Process git -ArgumentList 'add','-A'` is **allowed**: a stated limit in the
  `guard_git` docstring and in GUARDRAILS.md, as the PRD records ("Start-Process was allowed in
  the probe").

Read with those two, every guard probe case behaves as intended: 0 unexplained mismatches.
