# 賽前歷史戰績圖 — 下游機械人／AI 使用說明

給**負責發佈或轉發賽前歷史戰績圖**的下游機械人（Grok Bot 等）。  
與預測海報廣告包分開：海報用 [`SOCIAL_PUBLISH_AI_USAGE.md`](SOCIAL_PUBLISH_AI_USAGE.md)（`/v1/ads/*`）；  
本檔係 **三幅馬匹歷史戰績表 PNG**（`/v1/helper-form/*`）。

上游在**排位資料齊備**（meeting_tick `helper_form_ensure`）或手動／API `generate` 後，會寫入 ready 包並可 webhook。

---

## 一頁搞掂

| 項目 | 說明 |
|------|------|
| Base | `$AD_API_PUBLIC_BASE`（與 Ad API 相同服務） |
| 取最新 | `GET /v1/helper-form/latest` |
| 認證 | `Authorization: Bearer $AD_API_KEY`（或 `X-API-Key`） |
| 圖片 | `assets.images[0..2].url`（通常三幅；公開 PNG） |
| 分辨 | `purpose == "helper_form"` 或 `kind == "pre_race_form_history"` |
| 幂等 id | `{YYYY-MM-DD}-{st\|hv}-helper-form` |

```bash
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/helper-form/latest" | jq '{
    id, status, purpose, kind,
    meeting, layout, n_races,
    images: [.assets.images[] | {index, race_nums, url}]
  }'
```

只喺 `status == "ready"` 先用圖。

---

## 同 `/v1/ads/latest` 嘅分別

| | 預測廣告包 | 歷史戰績包 |
|--|-----------|-----------|
| Path | `/v1/ads/latest` | `/v1/helper-form/latest` |
| 內容 | 海報 + Facebook 文案 | **三幅**戰績表 PNG |
| `purpose` | 賽前／`post_race` | **`helper_form`** |
| 用途 | 社交發佈推介 | 賽前歷史戰績參考圖 |

機械人若要「戰績表」**唔好**打 `/v1/ads/latest`。

---

## 建議流程

### A. Webhook（優先）

ready 且 `notify=true` 時 POST 公開 JSON（`HELPER_FORM_WEBHOOK_URL`，未設則回退 `GROK_BOT_WEBHOOK_URL`）。

1. 驗 `X-Webhook-Secret`（若有）
2. 確認 `purpose == "helper_form"` 且 `status == "ready"`
3. 下載 `assets.images[].url`（通常 3 張）
4. 以 `id` 做幂等（同一 id 唔好重複發）

Header：`X-J18-Purpose: helper_form`、`Idempotency-Key: <id>`。

### B. 定時輪詢

1. `GET /v1/helper-form/latest`
2. `id` 同上次已處理 → skip
3. `status != ready` → skip
4. 否則下載三幅圖並處理

### C. 手動觸發重產

```bash
curl -sS -X POST -H "Authorization: Bearer $AD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notify":true,"force":false}' \
  "$AD_API_PUBLIC_BASE/v1/helper-form/generate"
```

---

## JSON 欄位

```json
{
  "id": "2026-10-01-st-helper-form",
  "status": "ready",
  "purpose": "helper_form",
  "kind": "pre_race_form_history",
  "meeting": { "date": "2026-10-01", "course": "ST" },
  "layout": [4, 4, 3],
  "n_races": 11,
  "assets": {
    "images": [
      {
        "index": 1,
        "race_nums": [1, 2, 3, 4],
        "n_races": 4,
        "url": "https://…/v1/helper-form/2026-10-01-st-helper-form/image/1"
      },
      { "index": 2, "race_nums": [5, 6, 7, 8], "url": "…" },
      { "index": 3, "race_nums": [9, 10, 11], "url": "…" }
    ]
  },
  "publish": {
    "hint": "下載 assets.images[].url 三幅賽前歷史戰績圖；以 id 做幂等。",
    "image_count": 3
  }
}
```

排版：9→3+3+3、10→4+3+3、11→4+4+3、12→4+4+4（餘場補前）。

---

## 端點一覽

| Method | Path | Auth | 說明 |
|--------|------|------|------|
| GET | `/v1/helper-form/latest` | Bearer | 最新 ready |
| GET | `/v1/helper-form/{id}` | Bearer | 按 id |
| GET | `/v1/helper-form/{id}/image/{1\|2\|3}` | 預設公開 | PNG |
| GET | `/v1/helper-form` | Bearer | id 清單 |
| POST | `/v1/helper-form/generate` | Bearer | 核對賽日並產圖 |
| POST | `/v1/helper-form/{id}/notify` | Bearer | 重發 webhook |

上游自動化：`meeting_tick` 在 **RACECARD ok** 後跑 `helper_form_ensure`（日期須與 Helper API title 匹配，否則不會 ready）。
