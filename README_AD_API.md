# 賽前預測廣告包 API（Ad Package API）

給外部助手（Grok Bot / Elton-PC）攞「賽前預測」結構化 JSON + Facebook 文案，並在新一期 `ready` 時**主動 webhook POST**。

**唔會**直接發 Facebook；發佈由外部助手／人手處理。

## 啟動

```bash
# 本機
export AD_API_KEY=dev-secret
export AD_API_PUBLIC_BASE=http://127.0.0.1:8001
# 可選：webhook（未設則只寫本地 packages，唔推送）
# export GROK_BOT_WEBHOOK_URL=https://…
# export GROK_BOT_WEBHOOK_SECRET=…
bash start-ad-api.sh
# 或：uvicorn ad_api:app --host 0.0.0.0 --port 8001
```

Railway：另開一個 service（或與預測 API 分開 Start Command），設：

| 變量 | 用途 |
|------|------|
| `AD_API_KEY` | `Authorization: Bearer …` 讀取／產生 |
| `AD_API_PUBLIC_BASE` | 公開 base（例如 `https://xxx.up.railway.app`），用來組 `assets.poster_url` |
| `GROK_BOT_WEBHOOK_URL` | 外部助手 webhook |
| `GROK_BOT_WEBHOOK_SECRET` | 送出 Header `X-Webhook-Secret`（可用 `GROK_BOT_WEBHOOK_SECRET_HEADER` 改名） |
| `AD_OUTPUT_DIR` | 可選；預設專案 `ad_output/` |
| `DATABASE_URL` | 若要 `POST /v1/ads/generate` 連 snapshot 重產海報 |

Start Command：`bash start-ad-api.sh`

統計／海報完成後（`ad_poster._write_primary_meeting_outputs`）會自動寫入 `ad_output/packages/{id}.json` 並嘗試 webhook。

## 端點

| Method | Path | Auth | 說明 |
|--------|------|------|------|
| GET | `/health` | 否 | 健康檢查 |
| GET | `/v1/ads/latest` | Bearer | 最新一期 `ready` payload |
| GET | `/v1/ads/{id}` | Bearer | 按 id 取回 |
| GET | `/v1/ads/{id}/poster` | 否（預設公開） | 海報 PNG |
| GET | `/v1/ads` | Bearer | id 清單 |
| POST | `/v1/ads/generate` | Bearer | 由 copy／snapshot 產出並可 notify |
| POST | `/v1/ads/rebuild-from-copy` | Bearer | 用現有 `copy.json` 重建 |
| POST | `/v1/ads/{id}/notify` | Bearer | **手動重發 webhook** |

幂等 `id`：`{YYYY-MM-DD}-{hv\|st}-{day\|night}`（同一期重複產出覆寫同一檔，保留首次 `created_at`）。

Webhook：只喺 `status=ready` 時 POST 完整公開 JSON；非 2xx 指數退避重試至少 3 次。

## curl 例子

```bash
BASE=https://YOUR-AD-API.up.railway.app
KEY=your-ad-api-key

# 健康檢查
curl -sS "$BASE/health"

# 取最新
curl -sS -H "Authorization: Bearer $KEY" "$BASE/v1/ads/latest" | jq .

# 按 id
curl -sS -H "Authorization: Bearer $KEY" "$BASE/v1/ads/2026-07-15-hv-night" | jq .

# 手動觸發／重建（有 copy.json 時）
curl -sS -X POST -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"notify":true}' \
  "$BASE/v1/ads/rebuild-from-copy" | jq .

# 手動重發 webhook
curl -sS -X POST -H "Authorization: Bearer $KEY" \
  "$BASE/v1/ads/2026-07-15-hv-night/notify" | jq .
```

### 本機模擬 webhook 接收

```bash
# 終端 A：簡易接收
python - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        print(self.headers.get("X-Webhook-Secret"), self.headers.get("Idempotency-Key"))
        print(self.rfile.read(n).decode())
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", 9999), H).serve_forever()
PY

# 終端 B：設 URL 後 notify
export GROK_BOT_WEBHOOK_URL=http://127.0.0.1:9999/hook
export GROK_BOT_WEBHOOK_SECRET=dev-hook-secret
curl -sS -X POST -H "Authorization: Bearer $KEY" \
  "$BASE/v1/ads/2026-07-15-hv-night/notify"
```

## 測試

```bash
pytest tests/test_ad_package_api.py -q
```

## Sample JSON（schema）

```json
{
  "id": "2026-07-15-hv-night",
  "created_at": "2026-07-15T10:00:00+08:00",
  "status": "ready",
  "meeting": {
    "date": "2026-07-15",
    "weekday": "星期三",
    "venue": "谷草",
    "venue_code": "HV",
    "session": "夜"
  },
  "intro": "2026-07-15 星期三谷草夜賽共 2 場，J18 綜合推介已出爐——開賽前或會更新，請以網站最新版為準。",
  "tips": [
    {
      "race": 1,
      "horses": [
        { "no": 4, "name": "多利神駒" },
        { "no": 9, "name": "天下寵兒" },
        { "no": 2, "name": "飛影" },
        { "no": 7, "name": "金光" }
      ]
    }
  ],
  "copy": {
    "facebook": "【J18 賽前預測】…（完整文案，含 CTA 與注意變更）",
    "short": "【J18】2026-07-15 谷草夜賽 …",
    "cta": "想追臨場心水？而家就登入 J18.hk",
    "hashtags": ["#J18", "#賽馬", "#賽前預測"]
  },
  "assets": {
    "poster_url": "https://YOUR-AD-API.up.railway.app/v1/ads/2026-07-15-hv-night/poster",
    "poster_alt": "J18 賽前預測海報 2026-07-15 谷草夜"
  },
  "publish": {
    "channels": ["facebook"],
    "page": "https://www.facebook.com/j18hk",
    "when": "immediate"
  },
  "links": {
    "site": "https://J18.hk",
    "detail": ""
  }
}
```

> 賽後命中廣告目前只得邏輯／文案 job，未有海報同呢條 API；本服務只涵蓋賽前預測包。


## 歷史歸檔（不存海報 PNG）

- 路徑：`ad_output/archive/{YYYY-MM-DD}_{COURSE}/`
- 種類：`copy_latest.json`（海報生成資料）、`social_latest.json`、`promo_hits_latest.json`、`post_race_latest.json`
- **不歸檔 fused.png**；需要海報時用「廣告輸出 → 手動重產」由快照重畫
- UI：廣告輸出／命中率榜可翻查最新歸檔並「強制重做」
- 賽後 AI 文案輸入已含每匹推介馬嘅 `name`／`finish`／`win_odds`（`picks_detail`）
