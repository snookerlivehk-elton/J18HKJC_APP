# 賽前預測廣告包 API（Ad Package API）

給外部助手（Grok Bot / Elton-PC）攞「賽前預測」**海報 PNG** + **AI 精選社交文案**（`copy.ai`／`copy.facebook`），並在新一期 `ready`（兩者齊備）時**主動 webhook POST**。\n\n`status=ready` 條件：`assets.poster_url` 有圖，且 `copy.ai` 有 AI 精選（可用 `AD_PACKAGE_REQUIRE_AI_SOCIAL=false` 關閉此要求）。

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
| `AD_API_KEY` | `Authorization: Bearer …` 讀取／產生／ingest |
| `AD_API_PUBLIC_BASE` | 公開 base，**必須可組成絕對 https URL**（缺 `https://` 會自動補）；用來改寫 `assets.poster_url` |
| `AD_API_BASE_URL` | **Streamlit／CORN** 指向生產 Ad API（例 `https://j18hkjcapp-production.up.railway.app`）；ready 後 `POST /v1/ads/ingest`。可與 PUBLIC 相同；**漏設 BASE 會 fallback 用 PUBLIC_BASE**（避免 latest 留舊手動 ingest） |
| `AD_API_PUBLIC_BASE` | **必須可組成絕對 https URL**（缺 `https://` 會自動補）。用來改寫 `assets.poster_url` |
| `GROK_BOT_WEBHOOK_URL` | 外部助手 webhook |
| `GROK_BOT_WEBHOOK_SECRET` | 送出 Header `X-Webhook-Secret`（可用 `GROK_BOT_WEBHOOK_SECRET_HEADER` 改名） |
| `AD_OUTPUT_DIR` | 可選；預設專案 `ad_output/` |
| `DATABASE_URL` | 可選共用 DB dual-write；無共碟時靠 ingest 即可 |
| `OPENAI_API_KEY` | Streamlit／CORN 產 AI 精選文案 |

Start Command：`bash start-ad-api.sh`

統計／海報完成後會寫 `ad_output/packages/{id}.json`；有 AI 文案後 `status=ready`，並：
1. dual-write 共用 DB（若有 `DATABASE_URL`）
2. 若設咗 `AD_API_BASE_URL` → `POST /v1/ads/ingest` 推去生產 Ad API（含海報 bytes）
3. 可選 webhook

**品質閘（重要）：**
- 唔會用 `pending_poster`／`tips=[]`／無海報嘅空包覆寫已有 ready 包
- `POST /v1/ads/ingest` 只接受 `status=ready` 且有 tips＋海報（＋ AI，若開啟要求）
- remote push 同樣拒絕空包

手動重產（Streamlit／CORN job）成功後會自動跑 AI 精選 → publish → ingest。  
瀏覽頁「生成 AI 精選評述」成功後亦會 publish + ingest；另有「推送生產 API」按鈕可人手補推。  
ZIP 下載會附消毒後嘅 `facebook_copy.txt`（日馬唔寫「今晚」、無系統句）。

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
| POST | `/v1/ads/ingest` | Bearer | **上游推送 ready 包 + 海報**（Streamlit／CORN → 生產 API） |
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

# 上游 ingest（Streamlit／CORN 自動做；亦可人手補推）
# BODY 含 package JSON + poster_png_b64
curl -sS -X POST -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d @ingest_payload.json \
  "$BASE/v1/ads/ingest" | jq .
```

### 下游 Grok Bot 一次攞齊（完成標準）

```bash
BASE=https://j18hkjcapp-production.up.railway.app
KEY=$AD_API_KEY

curl -sS -H "Authorization: Bearer $KEY" "$BASE/v1/ads/latest" | jq '{
  id, status,
  facebook: .copy.facebook,
  cta: .copy.cta,
  hashtags: .copy.hashtags,
  poster_url: .assets.poster_url,
  meeting, tips, publish
}'

# 下載海報（預設唔使 key）
curl -sS -o poster.png "$(curl -sS -H "Authorization: Bearer $KEY" "$BASE/v1/ads/latest" | jq -r .assets.poster_url)"
```

**Sample `ready` JSON（精簡）：**

```json
{
  "id": "2026-09-13-st-day",
  "status": "ready",
  "meeting": {
    "date": "2026-09-13",
    "weekday": "星期日",
    "venue": "沙田",
    "venue_code": "ST",
    "session": "日",
    "start_time": "約下午1時"
  },
  "copy": {
    "facebook": "【J18】2026-09-13 沙田日賽\n邊場最有睇頭？留言話我知！\n…\n想追臨場？登入 J18.hk\n預測只供參考。\n#J18 #賽馬 #沙田",
    "cta": "想追臨場心水？而家就登入 J18.hk",
    "hashtags": ["#J18", "#賽馬", "#沙田", "#賽前預測", "#J18HK"]
  },
  "assets": {
    "poster_url": "https://j18hkjcapp-production.up.railway.app/v1/ads/2026-09-13-st-day/poster"
  },
  "publish": {
    "channels": ["facebook"],
    "page": "https://www.facebook.com/j18hk"
  },
  "tips": [{"race": 1, "horses": [{"no": 7, "name": "增旺"}]}]
}
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
    "facebook": "今晚邊場最有睇頭？\n\n第1場｜4 多利神駒\n近績走勢穩陣…（AI 精選全文，供 Grok 發佈）",
    "short": "【J18】2026-07-15 谷草夜賽 …",
    "cta": "想追臨場心水？而家就登入 J18.hk",
    "hashtags": ["#J18", "#賽馬", "#賽前預測"],
    "ai": {
      "title": "今晚邊場最有睇頭？",
      "subtitle": "J18 AI 精選",
      "featured": [
        {
          "race_no": 1,
          "horse_no": 4,
          "horse_name": "多利神駒",
          "comment": "近績走勢穩陣，值得一讚"
        }
      ],
      "post_text": "今晚邊場最有睇頭？\n\n第1場｜4 多利神駒\n近績走勢穩陣，值得一讚\n",
      "source": "llm"
    }
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
