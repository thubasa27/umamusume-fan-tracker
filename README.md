# umamusume-fan-tracker

ウマ娘(PC版)の「進行状況」スクリーンショットから総獲得ファン数を読み取り、日次の推移を集計するローカルツール。
要件は [docs/requirements.md](docs/requirements.md) を参照。

## 開発

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt    # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
```

## 読み取り(fantracker/ocr.py)

- 読み取り領域は `fantracker/layout.json` の相対座標で指定する(ゲームのレイアウト変更時はここを差し替える)。
- 数字は `fantracker/templates.npz` のテンプレートと照合する。再生成は `PYTHONPATH=. python scripts/build_templates.py`。
  テンプレートは sample_1 の「総獲得数」以外の行から作るため、総獲得数の3枚は読み取りテストとして独立している。

## 起動

```bash
.venv/bin/python -m fantracker      # Windows: .venv\Scripts\python -m fantracker
```

Windows では**専用ウィンドウ**(WebView2。Windows 11 に標準で入っている)で開き、ウィンドウを閉じると終了する。
Linux/macOS など pywebview を入れていない環境、または `--browser` を付けたときは、ブラウザで `http://127.0.0.1:8000/` を開く(ローカル専用。ポートが使用中なら 8001 以降。止めるには画面の「終了」ボタンか `Ctrl+C`)。
WebView2 が使えない場合も、自動でブラウザ表示に切り替わる。`--no-ui` は画面を出さずにサーバーだけ起動する。データ(SQLite、取り込んだ画像、ログ)は、**アプリと同じフォルダの `data/`** に保存される(カレントディレクトリには依存しない。`fantracker/paths.py`)。
Chart.js は `fantracker/static/` に同梱しており、オフラインで動く。

- **取り込み**: 画像をドロップ → 読み取り値と切り抜きを確認・修正 → 確定(`POST /api/scan` → `POST /api/records` の2段階)
- **ダッシュボード**: 総獲得ファン数の推移(折れ線)・日次増加量(棒)、期間切替、日割り補間(グラフと週次・月次集計の両方に反映)、PNG ダウンロード
- **保存(CSV・グラフの PNG)**: 専用ウィンドウでは保存先を選ぶダイアログが出る(ブラウザ表示では通常のダウンロード)
- **記録一覧**: 編集・削除・手動追加、履歴(同日の非採用)の表示、CSV エクスポート/インポート(UTF-8 BOM 付き。集計日が重複する場合は上書き/スキップを選択)

集計日はゲームの日替わりに合わせて AM 5:00 区切り(`fantracker/dates.py`)。

## テスト

```bash
.venv/bin/python -m pytest
```

`tests/test_e2e.py` はヘッドレス Chromium で画面を操作する。初回のみ `.venv/bin/playwright install chromium` が必要
(Chromium を起動できない環境ではスキップされる)。

## Windows 11 での動作確認

リポジトリ直下で、次のどちらかを実行する(セットアップ → 自動確認 → pytest → サンプル画像の準備 → 起動まで一括)。

```powershell
scripts\windows\verify_windows.bat
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\verify_windows.ps1
```

オプション: `-SkipTests`(pytest を省く)、`-E2E`(Chromium を入れてブラウザ操作のテストも実行)、`-NoStart`(起動しない)、`-Minimized`(アプリを最小化した別ウィンドウで起動し、確認用のウィンドウは閉じる)。
`.bat` は `-Minimized` 付きで実行する(失敗時だけウィンドウを残す)。最小化したアプリを止めるには、そのウィンドウを閉じる。
自動確認の本体は `scripts/verify_smoke.py`(OS 非依存。`python scripts/verify_smoke.py` 単体でも実行できる)。
日本語フォントの表示、Excel での CSV 表示、実スクリーンショットの読み取りは、スクリプトが表示するチェックリストに沿って目視で確認する。

## ポータブル版(インストール不要)

Python が無い PC でも、フォルダごと置けば動く。インストーラーは使わず、レジストリなどにも書かない。
データはすべて、exe と同じフォルダの `data\`(記録 `fantracker.db`、画像 `images\`、ログ `logs\`)に保存される。

ビルド(Windows、リポジトリ直下):

```powershell
scripts\windows\build_portable.bat
```

`dist\FanTracker\`(exe と依存一式)と `dist\FanTracker-portable-v<バージョン>.zip` ができる。
ビルドの最後に、できた exe を実際に起動して「画面が返る」「データが exe と同じフォルダに作られる」を確認する。
配布物に `data\` は含めない。利用者向けの説明は `packaging/README-portable.txt`(zip 内では `README.txt`)。

- 使い方: zip を展開して `FanTracker.exe` を実行する。書き込める場所に置くこと(Program Files は不可)。
- 引っ越し・バックアップ: フォルダごとコピーする。更新: 新しいフォルダへ、古い `data\` をコピーする。
- 読み取り位置の調整: `data\layout.json` に書いたキーが、同梱の `layout.json` を上書きする。
- コンソールなしの exe(`console=False`)。起動エラーはメッセージボックスで表示し、ログは `data\logs\fantracker.log` に出る。専用ウィンドウを閉じると終了する。
- 専用ウィンドウが開けない(WebView2 が無い等)ときは、ブラウザに切り替わり、画面右上の「終了」ボタンで止められる。`FanTracker.exe --browser` で、最初からブラウザ表示にもできる。
- ビルド時の動作確認は `--no-ui`(画面なし)で行う。専用ウィンドウが開くことは、ビルド後に exe を起動して手動で確認する。
- DB は `PRAGMA user_version` で版を管理する。新しい版のアプリで作ったデータを古いアプリで開くと、分かる形で止まる。
- アイコンは `python scripts/make_icon.py` で `packaging/FanTracker.ico` を作り直せる。

## セキュリティ

サーバーは `127.0.0.1` だけで待ち受けるが、それだけでは、ブラウザで開いた別のサイトのページや、同じ PC の他のユーザーのプログラムから
`127.0.0.1` へアクセスできてしまう。`fantracker/security.py` と `fantracker/limits.py` で、次を防いでいる。

| 攻撃・問題 | 対策 |
|---|---|
| 他サイトからの書き込み(CSRF)。マルチパートのフォーム送信などは、ブラウザの事前確認なしに送れる | GET/HEAD 以外は `X-FanTracker: 1` ヘッダー必須。Origin があれば、このサーバーと同じオリジン(スキーム・ホスト・ポート)か確認。OPTIONS(プリフライト)は拒否。CORS ヘッダーは付けない。Cookie は SameSite=Strict |
| DNS リバインディング(攻撃者のドメインが `127.0.0.1` を指し、同一オリジンとして記録を読み出す) | Host ヘッダーが `127.0.0.1` / `localhost` でなければ、読み取りも含めて拒否 |
| **同じ PC の他のユーザーやプログラム**からのアクセス | **起動ごとのランダムなトークン**。最初に開く URL(`/?t=…`)だけがトークンを持ち、開くと Cookie(HttpOnly・SameSite=Strict)に替わり、URL からは消える(リダイレクト)。Cookie がない・一致しないリクエストは 403(`/api/health` だけは、起動の確認用に認証なし)。トークンは画面にもログにも出さない |
| クリックジャッキング、スクリプトの注入 | 全応答に CSP(`frame-ancestors 'none'`、`script-src 'self'` など。`unsafe-inline` / `unsafe-eval` なし)、`X-Frame-Options: DENY`、`nosniff`、`Referrer-Policy: no-referrer`、`Cross-Origin-Resource-Policy: same-origin`。API は `no-store`。`Server` ヘッダーは出さない |
| 巨大・壊れたファイルによるメモリの使い切り(悪意のある画像や CSV を、取り込まされる) | 画像は 20MB・5000 万画素まで、1 回に読み取るのは 100 枚まで(画面は 20 枚ずつ送る)、CSV は 5MB・10 万行まで、リクエスト全体は 200MB まで。超えたファイルは、そのファイルだけエラーにして続ける |
| CSV の数式インジェクション(ファイル名が `=…` などで始まると、Excel で開いたときに数式として実行される) | エクスポートで、文字列の列の危険な先頭文字(`=` `+` `-` `@`、タブ、改行)に `'` を前置。インポートで元に戻す(往復で変わらない) |
| 入力値 | `image_hash` は 64 桁の 16 進数、ファイル名は 255 文字まで、ファン数は 10¹³ まで。ログには、ファイル名を `repr` で出す(改行で、偽のログ行を作れない) |

- 画面(`app.js`)は、すべての API 呼び出しにヘッダーを付ける。画面以外から API を呼ぶ場合は、トークン付きの URL を開いて Cookie を受け取り、
  書き込み系には `X-FanTracker: 1` を付け、Host は `127.0.0.1` か `localhost` にする。
- 許可する Host は `create_app(allowed_hosts=...)`、トークンは `create_app(token=...)` で指定できる(省略時は自動で作る)。
- 想定外(対象外): 管理者権限を持つユーザーや、すでにあなたのアカウントで動いているプログラム(データフォルダを直接読める。
  トークンはアプリのプロセスにあり、起動時にブラウザへ渡す URL にも含まれる)。通信の暗号化(ローカルのみ)。
- **データの取り扱い**: `data\images\` には、取り込んだスクリーンショットの全体が保存される。画面に個人を特定できる情報が写っていれば、
  `data\` をそのまま他人に渡すと一緒に渡ってしまう。配布する zip には `data\` を含めない(ビルドスクリプトは含めない)。
- テスト: `tests/test_auth.py`(トークン、防御ヘッダー)、`tests/test_security.py`(Host、CSRF)、`tests/test_limits.py`(上限、CSV)、
  `tests/test_e2e.py`(実ブラウザで、別オリジンからの書き込み・DNS リバインディング・iframe への埋め込み・トークンなしの利用を再現)。
  防御を外すとテストが失敗することを、変異テストで確認している。
