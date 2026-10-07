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

## API の起動(開発用)

```bash
.venv/bin/python -m uvicorn fantracker.api:create_app --factory
```

データ(SQLite と取り込んだ画像)はカレントの `data/` に保存される。
取り込みは `POST /api/scan`(読み取り・確認用、DB には登録しない)→ `POST /api/records`(確定)の2段階。
集計日はゲームの日替わりに合わせて AM 5:00 区切り(`fantracker/dates.py`)。
