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
Copy-Item LICENSE (Join-Path $appDir 'LICENSE.txt') -Force
# 同梱する第三者ソフトウェアのライセンス表記(ライセンス全文が見つからないものがあれば、ここで止める)
& $venvPy scripts\make_notices.py (Join-Path $appDir 'THIRD_PARTY_NOTICES.txt') --strict
if ($LASTEXITCODE -ne 0) { Stop-WithError '第三者ライセンスの表記を作れませんでした(上のエラーを確認してください)。' }

Write-Step '3. できた exe の動作確認'
# 作業フォルダを別の場所にして起動し、データが exe と同じフォルダに作られることも確認する
# --no-ui: 画面を出さずサーバーだけ起動する(専用ウィンドウの表示は、このあと手動で確認する)
$proc = Start-Process -FilePath $exe -ArgumentList '--no-ui' -WorkingDirectory $env:TEMP -PassThru
$ok = $false
try {
    for ($i = 0; $i -lt 40 -and -not $ok; $i++) {
        Start-Sleep -Milliseconds 500
        foreach ($port in 8000..8019) {
            try {
                $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:$port/api/health"
                if ($r.StatusCode -eq 200) { $ok = $true; break }
            } catch { }
        }
    }
} finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    $null = $proc.WaitForExit(10000)   # 終了を待つ(ログや DB のファイルを、まだ掴んでいることがある)
}
if (-not $ok) { Stop-WithError '起動した exe から応答がありません(dist\FanTracker\data\logs を確認してください)。' }
$db = Join-Path $appDir 'data\fantracker.db'
if (-not (Test-Path $db)) { Stop-WithError "データが exe と同じフォルダに作られていません: $db" }
Write-Host 'exe の起動と、データの保存先(exe と同じフォルダの data\)を確認しました。'
# 配布物に動作確認のデータを含めない。プロセスが終わっても、ファイルのハンドルが閉じるまで少しかかることがあるので、やり直す
$dataDir = Join-Path $appDir 'data'
for ($i = 0; $i -lt 20 -and (Test-Path $dataDir); $i++) {
    try { Remove-Item -Recurse -Force $dataDir -ErrorAction Stop }
    catch { Start-Sleep -Milliseconds 500 }
}
if (Test-Path $dataDir) { Stop-WithError "動作確認で作られたデータを削除できません(使用中の可能性があります): $dataDir`n FanTracker.exe が残っていないか確認して、もう一度実行してください。" }

foreach ($f in 'README.txt', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.txt', 'FanTracker.exe') {
    if (-not (Test-Path (Join-Path $appDir $f))) { Stop-WithError "$f が配布物にありません。" }
}

Write-Step '4. zip の作成'
$zip = Join-Path $root "dist\FanTracker-portable-v$version.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $appDir -DestinationPath $zip
Write-Host "できました: $zip" -ForegroundColor Green
# 受け取った人が、zip が改ざん・破損していないか確かめられるよう、SHA-256 を添える(sha256sum 形式)
$hash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
$hashFile = "$zip.sha256"
[IO.File]::WriteAllText($hashFile, "$hash *$(Split-Path -Leaf $zip)`n", (New-Object Text.UTF8Encoding($false)))
Write-Host "SHA-256: $hash" -ForegroundColor Green
Write-Host "         $hashFile"
Write-Host "最後に、dist\FanTracker\FanTracker.exe をダブルクリックして、専用ウィンドウが開くことを確認してください。" -ForegroundColor Yellow
