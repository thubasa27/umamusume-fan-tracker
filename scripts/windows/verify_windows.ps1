<#
.SYNOPSIS
  Windows 11 での動作確認を一括で行う(セットアップ → 自動確認 → サンプル準備 → 起動)。

.DESCRIPTION
  1. Python(3.11 以上)の確認、.venv の作成、依存のインストール
  2. 実サーバーを一時データで起動して HTTP 経由で自動確認(scripts/verify_smoke.py)
  3. pytest(既定では E2E を除く)
  4. 撮影日時入りの合成サンプル画像を一時フォルダに用意する(フォルダは開かない。実際のゲーム画像はリポジトリに含めない)
  5. 目視確認の項目を表示し、アプリを起動(Ctrl+C で停止)

.PARAMETER SkipTests
  pytest を実行しない。
.PARAMETER E2E
  Chromium を入れて、ブラウザ操作の E2E テストも実行する(初回はダウンロードに時間がかかる)。
.PARAMETER NoStart
  確認とサンプル準備だけ行い、アプリは起動しない。
.PARAMETER Minimized
  アプリを別プロセス(コンソールは最小化)で起動し、このウィンドウは数秒後に閉じる。
  アプリは専用ウィンドウで開く。停止は、そのウィンドウを閉じる。
#>
param(
    [switch]$SkipTests,
    [switch]$E2E,
    [switch]$NoStart,
    [switch]$Minimized
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

function Write-Step([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Stop-WithError([string]$text) { Write-Host "エラー: $text" -ForegroundColor Red; exit 1 }

# --- 1. Python と仮想環境 ---------------------------------------------------
Write-Step '1. Python と仮想環境'
$pyExe = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = 'py'; $pyArgs = @('-3') }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = 'python' }
else { Stop-WithError 'Python が見つかりません。winget install Python.Python.3.11 などで入れてください。' }

$verText = (& $pyExe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ([version]$verText -lt [version]'3.11') { Stop-WithError "Python $verText が見つかりました。3.11 以上が必要です。" }
Write-Host "Python $verText"

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Stop-WithError '仮想環境を作れませんでした。' }
}
& $venvPy -m pip install -q -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { Stop-WithError '依存のインストールに失敗しました。' }
Write-Host '依存のインストール: OK'

$failed = @()

# --- 2. 自動確認(HTTP 経由) ------------------------------------------------
Write-Step '2. 自動確認(実サーバーを一時データで起動)'
& $venvPy scripts\verify_smoke.py
if ($LASTEXITCODE -ne 0) { $failed += '自動確認(verify_smoke.py)' }

# --- 3. pytest ---------------------------------------------------------------
if (-not $SkipTests) {
    Write-Step '3. pytest'
    if ($E2E) {
        & $venvPy -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { $failed += 'Chromium のインストール' }
        & $venvPy -m pytest -q
    } else {
        & $venvPy -m pytest -q --ignore=tests/test_e2e.py
    }
    if ($LASTEXITCODE -ne 0) { $failed += 'pytest' }
}

if ($failed.Count -gt 0) {
    Write-Host "`n失敗した項目:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

# --- 4. サンプル画像の準備 ---------------------------------------------------
Write-Step '4. サンプル画像の準備'
$samples = Join-Path $env:TEMP 'fantracker_verify_samples'
New-Item -ItemType Directory -Force -Path $samples | Out-Null
# ゲームの画像は、リポジトリに含めない。数字テンプレートから合成したスクリーンショットを作る
& $venvPy scripts\make_samples.py $samples
if ($LASTEXITCODE -ne 0) { Stop-WithError 'サンプル画像を作れませんでした。' }

# --- 5. 目視確認 → 起動 ------------------------------------------------------
Write-Step '自動確認はすべて成功しました'
Write-Host @'
以下は目視で確認してください(詳細は README / 手順書を参照)。
  [ ] 日本語が四角にならず表示される(タブ名・ボタン・グラフの凡例)
  [ ] 取り込みタブに上のサンプルをドロップ → 読み取り値と集計日が期待値どおり、警告なし
  [ ] 「警告のない項目をすべて確定」→ ダッシュボードにグラフと表が出る
  [ ] 「PNG でダウンロード」で保存した画像が開け、日本語が崩れていない
  [ ] CSV エクスポートを Excel でダブルクリックで開いて、文字化けしない
  [ ] 実際に撮ったスクリーンショットの値が、画面の「総獲得数」と一致する(合成画像は、読み取りの流れの確認用)
'@

if ($NoStart) { Write-Host "`n-NoStart のため起動しません。起動: .venv\Scripts\python -m fantracker"; exit 0 }

if ($Minimized) {
    # 作業フォルダはこのウィンドウと同じ(データは同じ data\ に保存される)
    Start-Process -FilePath $venvPy -ArgumentList '-m', 'fantracker' -WorkingDirectory $root -WindowStyle Minimized
    Write-Host "`nアプリを起動しました(専用ウィンドウ。コンソールは最小化)。"
    Write-Host '停止するには、アプリのウィンドウを閉じてください。'
    Start-Sleep -Seconds 3
    exit 0
}

Write-Host "`nアプリを起動します(専用ウィンドウ。閉じると終了します)"
& $venvPy -m fantracker
