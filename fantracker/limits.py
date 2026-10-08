"""入力の上限。悪意のある(または壊れた)ファイルでメモリを使い切られないための値で、通常の利用(150 万画素・約 150KB〜数 MB の
スクリーンショット、数百行の CSV)を大きく上回る。"""

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_SCAN_FILES = 100  # 1 回のリクエストで読み取る枚数(画面は 20 枚ずつ送る)
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 100_000
MAX_FILENAME = 255
MAX_FAN_TOTAL = 10**13  # 総獲得ファン数として現実的な上限(SQLite の整数にも収まる)
HASH_PATTERN = r"^[0-9a-f]{64}$"
