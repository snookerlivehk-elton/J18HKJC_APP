# 社交留言答覆上下文 API（Reply Context）

給**負責回覆社交媒體留言**嘅下游機械人，提供：

1. **最新賽事綜合推介**（fused tips，與廣告海報同一套）
2. **推介馬匹嘅 Form AI 評價**（`summary`／`ai_score`／`confidence`／`tags`／`risks`／`evidence`）

同現有 [Ad Package API](README_AD_API.md)（發佈用海報＋Facebook 文案）分開：Ad API 服務發佈；本上下文專供**留言答覆**。

詳見下游用法：留言機械人應輪詢／接收 webhook 後用 `tips[].horses[].ai` 回答，唔好捏造未提供嘅評價。

掛喺同一 `ad_api` 服務（`bash start-ad-api.sh`），路徑前綴 `/v1/reply-context`。

## 機械人（本倉）

```bash
# 由最新廣告包＋DB Form AI 重建，並 webhook 推去留言機械人
python social_reply_bot.py push

# 只重建／查看，唔推 webhook
python social_reply_bot.py push --no-notify
python social_reply_bot.py show
python social_reply_bot.py prompt   # 印 LLM 可注入嘅參考文本
```

廣告包產出（`build_ad_package_from_copy`／ingest）有 tips 時，預設會**自動**寫入 reply context 並嘗試 webhook（`SOCIAL_REPLY_AUTO_PUBLISH=true`）。

## 環境變量

| 變量 | 用途 |
|------|------|
| `AD_API_KEY` | 與 Ad API 相同；Bearer／X-API-Key |
| `SOCIAL_REPLY_BOT_WEBHOOK_URL` | 留言機械人 webhook（可別名 `REPLY_BOT_WEBHOOK_URL`） |
| `SOCIAL_REPLY_BOT_WEBHOOK_SECRET` | Header `X-Webhook-Secret`（可 fallback `GROK_BOT_WEBHOOK_SECRET`） |
| `SOCIAL_REPLY_AUTO_PUBLISH` | 廣告包有 tips 時自動 rebuild＋notify（預設 true） |
| `AD_OUTPUT_DIR` | 本機寫入 `reply_context/` |

## 端點

| Method | Path | Auth | 說明 |
|--------|------|------|------|
| GET | `/v1/reply-context/latest` | Bearer | 最新 ready 上下文 JSON |
| GET | `/v1/reply-context/latest/prompt` | Bearer | `{ id, prompt }` LLM 參考文本 |
| GET | `/v1/reply-context/{id}` | Bearer | 按 id |
| GET | `/v1/reply-context` | Bearer | id 清單 |
| POST | `/v1/reply-context/rebuild` | Bearer | 由廣告包重建；body `{ "ad_id"?, "notify" }` |
| POST | `/v1/reply-context/{id}/notify` | Bearer | 重發 webhook |

## curl

```bash
BASE=https://YOUR-AD-API.up.railway.app
KEY=$AD_API_KEY

# 健康檢查（含 reply_webhook_configured）
curl -sS "$BASE/health" | jq .

# 最新上下文
curl -sS -H "Authorization: Bearer $KEY" \
  "$BASE/v1/reply-context/latest" | jq '{id, status, meeting, tips: .tips[:1], meta}'

# LLM prompt
curl -sS -H "Authorization: Bearer $KEY" \
  "$BASE/v1/reply-context/latest/prompt" | jq -r .prompt

# 手動重建並推送
curl -sS -X POST -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"notify":true}' \
  "$BASE/v1/reply-context/rebuild" | jq .
```

## Sample JSON（精簡）

```json
{
  "id": "2026-07-15-hv-night",
  "status": "ready",
  "purpose": "social_reply",
  "meeting": {
    "date": "2026-07-15",
    "venue": "谷草",
    "venue_code": "HV",
    "session": "夜"
  },
  "intro": "…J18 綜合推介已出爐…",
  "tips": [
    {
      "race": 1,
      "race_id": "20260715HV01",
      "horses": [
        {
          "no": 4,
          "name": "多利神駒",
          "tag": "爭勝",
          "share_pct": 28.5,
          "ai": {
            "ai_score": 1.2,
            "confidence": 0.8,
            "ai_combo": 0.96,
            "summary": "近績穩陣，距離適性佳。",
            "tags": ["穩陣", "適性"],
            "risks": ["檔位一般"],
            "evidence": ["近兩仗入位"]
          }
        }
      ]
    }
  ],
  "featured": [],
  "disclaimer": "預測／AI 評價只供參考…",
  "meta": { "n_races": 2, "n_horses": 3, "n_ai_evals": 3, "coverage": 1.0 }
}
```

下游留言機械人建議：

- 開賽前／收到 webhook 後拉 `GET /v1/reply-context/latest`
- 或把 `GET …/prompt` 嘅文本注入 system／context
- 回答時只引用 `tips` 內推介同 `ai.summary`；冇 `ai` 就只講推介馬名，唔好捏造評價

## 測試

```bash
pytest tests/test_social_reply_context.py -q
```
