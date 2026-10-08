"""同梱する第三者ソフトウェアのライセンス表記(THIRD_PARTY_NOTICES.txt)を作る。

    python scripts/make_notices.py <出力ファイル> [--strict]

- Python のパッケージ: requirements.txt の依存(と、その依存の依存)のうち、インストールされているものについて、
  各パッケージの dist-info にあるライセンス全文を集める。表記を手で書くと、版が変わったときにずれるため。
- Chart.js、@kurkle/color、Microsoft WebView2 SDK: パッケージ管理の外にあるので、licenses/ に置いた全文を使う。
- Python 本体、PyInstaller(ブートローダーが exe に入る): インストールされているものから集める。
- --strict: ライセンス全文が見つからないものがあれば、エラーにする(配布物をビルドするときに使う)。
  Windows 専用の依存(pywebview など)は、Linux ではインストールされていないので、strict でなければ警告だけにする。
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "licenses"
# Windows 用の配布物をビルドする想定で、Windows 専用の依存(pywebview → pythonnet など)も対象にする
TARGET_ENV = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "extra": ""}
LICENSE_FILE = re.compile(r"^(licen[sc]e|copying|notice)", re.IGNORECASE)

# パッケージ管理の外にある、同梱物(ファイルは licenses/ にある。chart.umd.min.js の版と合わせること)
STATIC = [
    {
        "name": "Chart.js", "version": "4.4.7", "license": "MIT", "url": "https://www.chartjs.org",
        "note": "fantracker/static/chart.umd.min.js(グラフの描画)",
        "files": ["chartjs-4.4.7-LICENSE.md"],
    },
    {
        "name": "@kurkle/color", "version": "0.3.2", "license": "MIT", "url": "https://github.com/kurkle/color",
        "note": "Chart.js に組み込まれている",
        "files": ["kurkle-color-0.3.2-LICENSE.md"],
    },
    {
        "name": "Microsoft Edge WebView2 SDK", "version": "1.0.3856.49", "license": "BSD-3-Clause 系(Microsoft)",
        "url": "https://aka.ms/webview",
        "note": "pywebview が同梱する DLL(専用ウィンドウ用)。WebView2 ランタイム本体は同梱せず、Windows のものを使う",
        "files": ["microsoft-webview2-sdk-1.0.3856.49-LICENSE.txt", "microsoft-webview2-sdk-1.0.3856.49-NOTICE.txt"],
    },
]


# パッケージにライセンス全文が付属しない場合の補い(上流のリポジトリから取得して、licenses/ に置いたもの)
# 値は (ファイル名, ライセンスの表記)。表記は、上流の LICENSE.txt に合わせる(パッケージのメタデータと食い違うため)
FALLBACK_FILES = {"proxy-tools": ("proxy-tools-0.1.0-LICENSE.txt", "BSD(上流の LICENSE.txt による。パッケージのメタデータは MIT と記載)")}


def requirement_roots() -> list[str]:
    roots = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        req = Requirement(line)
        if not req.marker or req.marker.evaluate(TARGET_ENV):
            roots.append(req.name)
    return roots


def closure(roots: list[str]) -> tuple[dict[str, metadata.Distribution], list[str]]:
    found: dict[str, metadata.Distribution] = {}
    missing: list[str] = []
    stack = list(roots)
    while stack:
        name = canonicalize_name(stack.pop())
        if name in found or name in missing:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        found[name] = dist
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker and not req.marker.evaluate(TARGET_ENV):
                continue
            stack.append(req.name)
    return found, missing


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """dist-info にある、ライセンス・著作権表示のファイル(PEP 639 の licenses/ 以下は、すべて)。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for f in dist.files or []:
        parts = Path(str(f)).parts
        if not parts or not parts[0].endswith((".dist-info", ".egg-info")):
            continue
        if not (len(parts) > 2 and parts[1] == "licenses") and not LICENSE_FILE.match(parts[-1]):
            continue
        text = Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(("/".join(parts[1:]), text))
    return out


def describe(dist: metadata.Distribution) -> tuple[str, str]:
    md = dist.metadata
    lic = (md.get("License-Expression") or md.get("License") or "").strip()
    if not lic or "\n" in lic or len(lic) > 80:  # License フィールドに全文が入っている場合は、分類子から取る
        classes = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = ", ".join(c for c in classes if c != "OSI Approved") or "(分類子なし。下の全文を参照)"
    url = md.get("Home-page") or ""
    if not url:
        for entry in md.get_all("Project-URL") or []:
            label, _, link = entry.partition(",")
            if re.search(r"home|source|repo|github", label, re.IGNORECASE):
                url = link.strip()
                break
    return lic, url


def python_license() -> str | None:
    for base in (Path(sys.base_prefix), Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"):
        f = base / "LICENSE.txt"
        if f.exists():
            return f.read_text(encoding="utf-8", errors="replace").strip()
    return None


def build(strict: bool) -> tuple[str, list[str]]:
    problems: list[str] = []
    entries: list[dict] = []  # name, version, license, url, note, texts[(label, text)]

    for item in STATIC:
        texts = []
        for fname in item["files"]:
            path = LICENSES / fname
            if not path.exists():
                problems.append(f"{item['name']}: {path} がありません")
                continue
            texts.append((fname, path.read_text(encoding="utf-8").strip()))
        entries.append({**item, "texts": texts})

    py = python_license()
    if py is None:
        problems.append("Python: LICENSE.txt が見つかりません")
    entries.append({"name": "Python", "version": ".".join(map(str, sys.version_info[:3])), "license": "Python Software Foundation License",
                    "url": "https://www.python.org", "note": "実行環境(exe に同梱)", "texts": [("LICENSE.txt", py)] if py else []})

    found, missing = closure(requirement_roots())
    for opt in ("pyinstaller",):  # ブートローダーが exe に入る(GPL + 例外)
        try:
            found.setdefault(opt, metadata.distribution(opt))
        except metadata.PackageNotFoundError:
            missing.append(opt)
    for name, dist in sorted(found.items()):
        lic, url = describe(dist)
        texts = license_texts(dist)
        fallback = FALLBACK_FILES.get(name)
        if not texts and fallback and (LICENSES / fallback[0]).exists():
            texts = [(f"{fallback[0]}(パッケージに付属しないため、上流のリポジトリのもの)", (LICENSES / fallback[0]).read_text(encoding="utf-8").strip())]
            lic = fallback[1]
        if not texts:
            problems.append(f"{dist.metadata['Name']} {dist.version}: ライセンス全文が見つかりません")
        entries.append({"name": dist.metadata["Name"], "version": dist.version, "license": lic, "url": url,
                        "note": "", "texts": texts})
    for name in missing:
        problems.append(f"{name}: インストールされていません(この環境では、表記に含められません)")

    bar = "=" * 78
    lines = [
        "ウマ娘 ファン数トラッカー — 第三者ソフトウェアのライセンス表記",
        "THIRD-PARTY SOFTWARE NOTICES",
        "",
        "このソフトには、次のソフトウェアが含まれています。それぞれのライセンスに従います。",
        "This software includes the following third-party software, each under its own license.",
        "",
        bar,
        "目次 / Contents",
        bar,
    ]
    for e in entries:
        lines.append(f"- {e['name']} {e['version']} — {e['license']}" + (f" — {e['url']}" if e["url"] else ""))
    for e in entries:
        lines += ["", bar, f"{e['name']} {e['version']}", bar, f"License: {e['license']}"]
        if e["url"]:
            lines.append(f"URL: {e['url']}")
        if e["note"]:
            lines.append(f"Note: {e['note']}")
        for label, text in e["texts"]:
            lines += ["", f"--- {label} ---", text]
        if not e["texts"]:
            lines += ["", "(ライセンス全文を取得できませんでした)"]
    return "\n".join(lines) + "\n", problems


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--strict", action="store_true", help="ライセンス全文が見つからないものがあれば、エラーにする")
    args = parser.parse_args(argv)
    text, problems = build(args.strict)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    print(f"書き出しました: {args.output}({text.count(chr(10) + '--- ')} 件のライセンス全文を含む)")
    for p in problems:
        print(("エラー: " if args.strict else "警告: ") + p)
    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
