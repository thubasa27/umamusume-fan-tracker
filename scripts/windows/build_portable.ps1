<#
.SYNOPSIS
  ポータブル版(フォルダ配布の zip)をビルドする。

.DESCRIPTION
  1. .venv を用意し、実行用の依存と PyInstaller を入れる
  2. PyInstaller で dist\FanTracker\ を作る(exe + 依存。データは含めない)
  3. できた exe を実際に起動して動作確認(画面が返る・データが exe と同じフォルダに作られる)
  4. dist\FanTracker-portable-v<バージョン>.zip を作る
#>
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

function Write-Step([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Stop-WithError([string]$text) { Write-Host "エラー: $text" -ForegroundColor Red; exit 1 }

Write-Step '1. 準備'
$pyExe = $null; $pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = 'py'; $pyArgs = @('-3') }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = 'python' }
else { Stop-WithError 'Python が見つかりません。' }
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { & $pyExe @pyArgs -m venv .venv; if ($LASTEXITCODE -ne 0) { Stop-WithError '仮想環境を作れませんでした。' } }
& $venvPy -m pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { Stop-WithError '依存のインストールに失敗しました。' }
$version = (& $venvPy -c "import fantracker; print(fantracker.__version__)").Trim()
Write-Host "バージョン: $version"

Write-Step '2. PyInstaller でビルド'
if (Test-Path dist\FanTracker) { Remove-Item -Recurse -Force dist\FanTracker }
& $venvPy -m PyInstaller packaging\fantracker.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { Stop-WithError 'ビルドに失敗しました。' }
$appDir = Join-Path $root 'dist\FanTracker'
$exe = Join-Path $appDir 'FanTracker.exe'
if (-not (Test-Path $exe)) { Stop-WithError "$exe ができていません。" }
Copy-Item packaging\README-portable.txt (Join-Path $appDir 'README.txt') -Force

Write-Step '3. できた exe の動作確認'
# 作業フォルダを別の場所にして起動し、データが exe と同じフォルダに作られることも確認する
$proc = Start-Process -FilePath $exe -WorkingDirectory $env:TEMP -PassThru -WindowStyle Minimized
$ok = $false
try {
    for ($i = 0; $i -lt 40 -and -not $ok; $i++) {
        Start-Sleep -Milliseconds 500
        foreach ($port in 8000..8019) {
            try {
                $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:$port/api/records"
                if ($r.StatusCode -eq 200) { $ok = $true; break }
            } catch { }
        }
    }
} finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
}
if (-not $ok) { Stop-WithError '起動した exe から応答がありません(dist\FanTracker\data\logs を確認してください)。' }
$db = Join-Path $appDir 'data\fantracker.db'
if (-not (Test-Path $db)) { Stop-WithError "データが exe と同じフォルダに作られていません: $db" }
Write-Host 'exe の起動と、データの保存先(exe と同じフォルダの data\)を確認しました。'
Remove-Item -Recurse -Force (Join-Path $appDir 'data')   # 配布物に動作確認のデータを含めない

Write-Step '4. zip の作成'
$zip = Join-Path $root "dist\FanTracker-portable-v$version.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $appDir -DestinationPath $zip
Write-Host "できました: $zip" -ForegroundColor Green
