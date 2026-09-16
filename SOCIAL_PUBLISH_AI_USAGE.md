# 社交媒體發佈機械人 — Ad API 使用說明

給**負責發佈 Facebook／專頁帖文**嘅下游機械人（Grok Bot 等）。  
**唔係**留言答覆 AI（答覆請用 [`SOCIAL_REPLY_AI_USAGE.md`](SOCIAL_REPLY_AI_USAGE.md)）。

上游會把「賽前預測包」同「賽後命中包」ingest 到同一條 Ad API。你照拉 `GET /v1/ads/latest`（或收 webhook）即可發佈。

---

## 一頁搞掂

| 項目 | 說明 |
|------|------|
| Base | `$AD_API_PUBLIC_BASE`（與現有 Ad API 相同） |
| 取最新 | `GET /v1/ads/latest` |
| 認證 | `Authorization: Bearer $AD_API_KEY`（或 `X-API-Key`） |
| 發佈文案 | `copy.facebook`（已含 CTA／免責，可直接贴） |
| 海報 | `assets.poster_url`（公開 PNG；下載唔使 key） |
| 賽前 vs 賽後 | 睇 `purpose` 同 `id` 後綴（見下） |

```bash
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/ads/latest" | jq '{
    id, status, purpose,
    facebook: .copy.facebook,
    poster_url: .assets.poster_url,
    meeting, tips, publish
  }'
```

只喺 `status == "ready"` 先發佈。

---

## 賽前 vs 賽後：點分辨

上游 ingest 兩類 ready 包；**`/v1/ads/latest` 永遠係最近一次 ready**（賽後 ingest 後會蓋過賽前）。

| | 賽前預測 | 賽後命中回顧 |
|--|----------|--------------|
| `id` 例 | `2026-09-16-hv-night` | `2026-09-16-hv-night-post` |
| `purpose` | 無／省略（舊包）或可視為賽前 | **`post_race`** |
| 文案語氣 | 開賽前推介／提問互動 | 賽後命中回顧（T3／高賠等） |
| 海報 | 當日預測海報 | 暫重用當日賽前海報 |
| 典型出現時間 | 開賽前（夜馬約傍晚前） | 全場 RESULTS＋SETTLED 之後 |

建議判斷：

```text
若 id 以 "-post" 結尾 或 purpose == "post_race"
  → 當「賽後帖」發（標題／配圖策略可跟賽前唔同）
否則
  → 當「賽前預測帖」發
```

```bash
# 例：只在賽後包先發
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/ads/latest" | jq '
  select(.status=="ready")
  | select((.purpose=="post_race") or (.id|endswith("-post")))
  | {id, purpose, facebook: .copy.facebook, poster_url: .assets.poster_url}
'
```

按 id 攞指定一期（唔依賴 latest）：

```bash
# 賽前
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/ads/2026-09-16-hv-night"

# 賽後
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/ads/2026-09-16-hv-night-post"
```

列出庫內 ids：

```bash
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/ads"
```

---

## 建議發佈流程

### A. Webhook（優先）

上游 ingest `ready` 且 `notify=true` 時，會 POST 完整公開 JSON 去 `GROK_BOT_WEBHOOK_URL`。

1. 驗 `X-Webhook-Secret`（若有設）
2. 確認 `status == "ready"`
3. 用 `purpose`／`id` 分辨賽前／賽後
4. 發 `copy.facebook` + 下載 `assets.poster_url` 作配圖
5. 以 `id` 做冪等（同一 `id` 唔好重複發）

### B. 定時輪詢（備援）

例如香港時間賽日 **08:15–22:45**，每小時 `:15`／`:45`：

1. `GET /v1/ads/latest`
2. 若 `id` 同上次已發佈相同 → skip
3. 若 `status != "ready"` → skip
4. 否則發佈並記錄 `id`

賽後窗口：夜馬通常完場後至午夜；若當日仍未見 `*-post`，可繼續輪詢或等 webhook，**唔好**把舊賽前包當賽後重發。

---

## JSON 欄位（發佈要用）

```json
{
  "id": "2026-09-16-hv-night-post",
  "status": "ready",
  "purpose": "post_race",
  "meeting": {
    "date": "2026-09-16",
    "weekday": "星期三",
    "venue": "谷草",
    "venue_code": "HV",
    "session": "夜"
  },
  "intro": "……",
  "tips": [
    {
      "race": 5,
      "horses": [
        {"no": 4, "name": "幸運愉快"},
        {"no": 6, "name": "競駿非凡"},
        {"no": 7, "name": "紅錢到"}
      ]
    }
  ],
  "copy": {
    "facebook": "（可直接贴嘅完整帖文）",
    "cta": "想睇模型紀錄同系統更新？免費登入 J18.hk",
    "hashtags": ["#J18", "#賽事數據"],
    "ai": {
      "title": "……",
      "post_text": "……",
      "featured": [],
      "purpose": "post_race"
    }
  },
  "assets": {
    "poster_url": "https://…/v1/ads/2026-09-16-hv-night-post/poster",
    "poster_alt": "J18 賽後命中回顧 …"
  },
  "publish": {
    "channels": ["facebook"],
    "page": "https://www.facebook.com/j18hk",
    "when": "immediate"
  }
}
```

下載海報：

```bash
POSTER=$(curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/ads/latest" | jq -r .assets.poster_url)
curl -sS -o poster.png "$POSTER"
```

---

## 唔好做

| 錯誤 | 原因 |
|------|------|
| 用 `/v1/reply-context/latest` 去發廣告帖 | 嗰條係留言答覆上下文，唔係發佈文案 |
| `status != ready` 仍發 | 可能缺海報／文案 |
| 忽略 `id` 冪等 | 會重複發同一期 |
| 假設 latest 永遠係賽前 | 賽後 ingest 後 latest 會變成 `*-post` |
| 改寫免責／CTA 前半 | `copy.facebook` 已消毒；除非產品另有指示 |

---

## 上游何時會推賽後包

1. 當日 RESULTS 齊 + SETTLED  
2. 宣傳規則有命中（如 T3 覆蓋／高賠等）  
3. 產 `post_race` 文案 → ingest `*-post`  

若 latest 仍係賽前 id、庫內未有 `*-post`：代表上游未 settle／未命中／未部署 ingest。可回報上游補跑「賽後命中＋文案」或再查一次。

運維細節見 [`README_AD_API.md`](README_AD_API.md)。
