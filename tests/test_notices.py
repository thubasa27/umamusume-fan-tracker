"""LICENSE と、第三者ソフトウェアのライセンス表記(scripts/make_notices.py)。"""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("make_notices", ROOT / "scripts" / "make_notices.py")
make_notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_notices)

# Windows 専用の依存(pywebview → pythonnet など)は、Linux の開発環境にはインストールされていない
WINDOWS_ONLY = {"pythonnet", "clr-loader", "cffi", "pycparser"}


@pytest.fixture(scope="module")
def notices():
    return make_notices.build(strict=False)


def test_every_installed_component_has_a_license_text(notices):
    text, problems = notices
    missing = [p for p in problems if "ライセンス全文が見つかりません" in p or "がありません" in p]
    assert missing == [], missing
    # 見つからない・入っていないのは、この環境に無い Windows 専用の依存だけ
    for p in problems:
        assert any(name in p.lower().replace("_", "-") for name in WINDOWS_ONLY), p


def test_notices_list_the_bundled_components(notices):
    text, _ = notices
    for name in ("Chart.js 4.4.7", "@kurkle/color 0.3.2", "Microsoft Edge WebView2 SDK", "Python ", "pillow ", "numpy ", "fastapi ",
                 "starlette ", "uvicorn ", "pydantic ", "python-multipart ", "pywebview ", "proxy-tools ", "pyinstaller "):
        assert re.search(rf"^- {re.escape(name)}", text, re.MULTILINE), name
    # 全文が入っている(表記だけではない)
    assert "Permission is hereby granted, free of charge" in text  # MIT
    assert "Redistribution and use in source and binary forms" in text  # BSD
    assert "Apache License" in text  # python-multipart など
    assert "PyInstaller" in text and "exception" in text.lower()  # ブートローダーの例外条項


def test_proxy_tools_notice_matches_its_real_license(notices):
    text, _ = notices
    line = next(line for line in text.splitlines() if line.startswith("- proxy-tools"))
    assert "BSD" in line  # パッケージのメタデータは MIT だが、上流の LICENSE は BSD


def test_vendored_chartjs_matches_the_notice_versions():
    """chart.umd.min.js を更新したら、STATIC の版とライセンス全文(licenses/)も更新すること。"""
    js = (ROOT / "fantracker" / "static" / "chart.umd.min.js").read_text(encoding="utf-8")
    chart = next(e for e in make_notices.STATIC if e["name"] == "Chart.js")
    kurkle = next(e for e in make_notices.STATIC if e["name"] == "@kurkle/color")
    assert f"Chart.js v{chart['version']}" in js
    assert f"@kurkle/color v{kurkle['version']}" in js
    for e in make_notices.STATIC:
        for f in e["files"]:
            assert (make_notices.LICENSES / f).read_text(encoding="utf-8").strip(), f


def test_webview2_sdk_notice_matches_the_bundled_dlls():
    webview = pytest.importorskip("webview")
    sdk = next(e for e in make_notices.STATIC if "WebView2" in e["name"])
    dll = Path(webview.__file__).parent / "lib" / "Microsoft.Web.WebView2.Core.dll"
    version = sdk["version"].encode("utf-16-le")
    assert version in dll.read_bytes(), "pywebview の DLL の版が変わった。licenses/ の WebView2 SDK のライセンスと、STATIC の版を更新すること"


def test_project_license():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 thubasa27. All rights reserved." in text
    assert "THIRD_PARTY_NOTICES.txt" in text and "AS IS" in text
    assert "再配布" in text and "営利" in text and "個人" in text


def test_portable_package_ships_the_license_files():
    ps1 = (ROOT / "scripts" / "windows" / "build_portable.ps1").read_text(encoding="utf-8-sig")
    assert "LICENSE.txt" in ps1 and "make_notices.py" in ps1 and "--strict" in ps1 and "SHA256" in ps1
    readme = (ROOT / "packaging" / "README-portable.txt").read_text(encoding="utf-8")
    assert "LICENSE.txt" in readme and "THIRD_PARTY_NOTICES.txt" in readme


def test_version_is_semver():
    import fantracker

    assert re.fullmatch(r"\d+\.\d+\.\d+", fantracker.__version__)
