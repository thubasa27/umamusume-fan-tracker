# umamusume-fan-tracker

ウマ娘(PC版)の「進行状況」スクリーンショットから総獲得ファン数を読み取り、日次の推移を集計するローカルツール。
要件は [docs/requirements.md](docs/requirements.md) を参照。

## 開発

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt    # Windows: .venv\Scripts\pip
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

`http://127.0.0.1:8000/` がブラウザで開く(ローカル専用)。データ(SQLite と取り込んだ画像)はカレントの `data/` に保存される。
Chart.js は `fantracker/static/` に同梱しており、オフラインで動く。

- **取り込み**: 画像をドロップ → 読み取り値と切り抜きを確認・修正 → 確定(`POST /api/scan` → `POST /api/records` の2段階)
- **ダッシュボード**: 総獲得ファン数の推移(折れ線)・日次増加量(棒)、期間切替、日割り補間(グラフと週次・月次集計の両方に反映)、PNG ダウンロード
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
