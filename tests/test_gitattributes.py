"""改行コードの固定(.gitattributes)。同じコミットから、同じ内容の配布物ができるようにする。"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(), reason="git のリポジトリではありません"
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def attr(name: str, path: str) -> str:
    return git("check-attr", name, "--", path).strip().rsplit(": ", 1)[-1]


def test_repository_stores_text_files_with_lf_only():
    """リポジトリ(インデックス)には、CRLF が混じらない。作業ツリーの改行は、属性で決まる。"""
    bad = [line for line in git("ls-files", "--eol").splitlines() if line.split()[0] in ("i/crlf", "i/mixed")]
    assert bad == [], "CRLF が混じっています。`git add --renormalize .` で直してください:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", [
    "fantracker/static/app.js", "fantracker/static/index.html", "fantracker/static/style.css", "fantracker/static/chart.umd.min.js",
    "fantracker/static/favicon.svg", "fantracker/layout.json", "fantracker/api.py", "README.md", "requirements.txt",
])
def test_sources_are_lf_in_the_working_tree(path):
    """同梱するファイルは、Windows の autocrlf に関わらず LF(配布物の内容が、環境で変わらない)。"""
    assert attr("eol", path) == "lf" and attr("text", path) in ("set", "auto")


@pytest.mark.parametrize("path", [
    "scripts/windows/build_portable.ps1", "scripts/windows/build_portable.bat", "scripts/windows/verify_windows.ps1",
    "scripts/windows/verify_windows.bat", "LICENSE", "packaging/README-portable.txt",
])
def test_windows_scripts_and_user_documents_are_crlf_in_the_working_tree(path):
    assert attr("eol", path) == "crlf" and attr("text", path) == "set"


@pytest.mark.parametrize("path", ["fantracker/templates.npz", "packaging/FanTracker.ico"])
def test_binary_files_are_not_converted(path):
    assert attr("text", path) == "unset" and attr("diff", path) == "unset"
