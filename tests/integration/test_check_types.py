"""tools/check_types.py must actually reach every file it claims to check.

Found by: reading CI's output. pyrefly skips hidden directories, so the
config's `.claude/hooks` entry was silently dropped and the type gate never
read a hook. The hooks are now checked as explicit files; these tests prove
that command sees a planted error in a hook and is clean on the real ones.
"""

import shutil
import subprocess
from pathlib import Path

from tools.check_types import ROOT, hooks_command


def _hooks_tree(tmp_path: Path) -> Path:
    hooks = tmp_path / ".claude" / "hooks"
    shutil.copytree(ROOT / ".claude" / "hooks", hooks, ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def test_the_hooks_command_sees_an_error_planted_in_a_hook(tmp_path):
    tree = _hooks_tree(tmp_path)
    (tree / ".claude" / "hooks" / "zz_planted.py").write_text(
        "import guard_shared\n\ndef f(x: str) -> str:\n    return x\n\nf(None)\n"
    )
    r = subprocess.run(hooks_command(tree), cwd=tree, capture_output=True, text=True)
    assert r.returncode != 0
    assert "zz_planted.py" in r.stdout + r.stderr


def test_the_real_hooks_type_check_clean_including_sibling_imports(tmp_path):
    tree = _hooks_tree(tmp_path)
    r = subprocess.run(hooks_command(tree), cwd=tree, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
