# 社交媒體答覆 AI — API 使用說明

給**負責回覆社交媒體留言／私訊**嘅下游 AI（唔係發佈廣告嘅 bot）。

## 重要：唔好再用 `/v1/ads/latest`

| API | 用途 | 下游應否使用 |
|-----|------|--------------|
| `GET /v1/ads/latest` | **廣告產出**：海報 PNG + Facebook 發佈文案（`copy.facebook`／`copy.ai`） | ❌ 發佈 bot 用；**留言答覆唔夠用**（冇完整 Form AI 評述） |
| `GET /v1/reply-context/latest` | **留言答覆**：每場最多 4 匹綜合推介 + 推介馬嘅 Form AI（From AI）評述 | ✅ **請用呢條** |
| `GET /v1/reply-context/latest/prompt` | 同上資料編成一段可直接注入 LLM 嘅繁中參考文本 | ✅ 可選（省解析） |

Base URL（生產）：與現有 Ad API 相同（Railway `j18hkjcapp-production` 服務），路徑前綴 `/v1/reply-context`。

```text
https://<AD_API_HOST>/v1/reply-context/latest
```

認證（與 Ad API 相同）：

```http
Authorization: Bearer <AD_API_KEY>
```

或：

```http
X-API-Key: <AD_API_KEY>
```

---

## 建議呼叫流程

1. 開賽前／收到新留言時，先拉最新上下文：

```bash
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/reply-context/latest"
```

2. 若你嘅框架較適合「一段 system prompt」，改拉：

```bash
curl -sS -H "Authorization: Bearer $AD_API_KEY" \
  "$AD_API_PUBLIC_BASE/v1/reply-context/latest/prompt"
```

回應：`{ "id", "status", "prompt" }` —— 把 `prompt` 注入 system／context。

3. （可選）若設咗 webhook `SOCIAL_REPLY_BOT_WEBHOOK_URL`，廣告包更新時會主動 POST 完整 JSON；收到後可快取，仍建議留言當下再 GET 一次以防過期。

---

## 你會收到咩（JSON 重點）

```json
{
  "id": "2026-09-16-hv-night",
  "status": "ready",
  "purpose": "social_reply",
  "meeting": {
    "date": "2026-09-16",
    "weekday": "星期三",
    "venue": "谷草",
    "venue_code": "HV",
    "session": "夜"
  },
  "intro": "……J18 綜合推介已出爐……",
  "tips": [
    {
      "race": 1,
      "race_id": "20260916HV01",
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
  "disclaimer": "……只供參考……",
  "meta": { "n_races": 8, "n_horses": 32, "n_ai_evals": 30, "coverage": 0.938 }
}
```

欄位說明：

- `tips[]`：最新賽前**綜合推介**（fused；與海報同一套），**每場最多 4 匹**
- `tips[].horses[].ai`：該馬嘅 **Form AI／From AI 評述**
  - `summary`：主要評價文字（回答用戶時優先引用）
  - `ai_score`／`confidence`／`ai_combo`：評分參考
  - `tags`／`risks`／`evidence`：標籤、風險、依據
  - 若 `ai` 為 `null`：該馬暫無評價 → **只講推介名單，唔好自行編造評述**
- `featured[]`：社交精選短評（可輔助語氣；唔係完整 Form AI）
- `disclaimer`：回覆結尾應保留類似免責聲明（可改寫語氣，唔好刪除「只供參考／非投注建議」意思）

---

## 回答用戶時嘅硬規則

1. **只引用本 API 提供嘅推介同 AI 評述**；冇列出嘅馬／場次，唔好當「有推介」或捏造 Form AI。
2. 用戶問某場推介 → 用該場 `tips[].horses`（馬號＋馬名＋可選 `tag`／`share_pct`）。
3. 用戶問「點解推呢匹／形勢點」→ 用該馬 `ai.summary`，可輔以 `tags`／`risks`／`evidence`。
4. `ai == null` → 誠實講暫無 AI 評述，仍可報推介名單。
5. 語氣：親切、簡潔、繁中（或跟隨用戶語言）；**唔構成投注建議**。
6. 唔好承諾必勝、唔好提供「必中組合」、唔好鼓勵未成年人賭博。
7. 若 `status` 非 `ready` 或 HTTP 404：告知「最新推介稍後更新」，唔好用過期記憶胡亂答。

---

## 與廣告 API 嘅關係（實施備註）

- 廣告產出（Streamlit／CORN → `POST /v1/ads/ingest`）成功且有 tips 時，會**自動**重建 reply-context（`SOCIAL_REPLY_AUTO_PUBLISH=true`）。
- 推介名單來源與海報相同（fused top-4）；留言 API **額外**掛上 DB 內 Form AI 全文。
- 因此留言 bot **唔使**再打 `/v1/ads/latest`；一條 `/v1/reply-context/latest` 已夠答覆。

健康檢查（無需 key）：

```bash
curl -sS "$AD_API_PUBLIC_BASE/health"
```

睇 `reply_webhook_configured` 可知 webhook 有冇配。

更多運維／重建端點見 [`README_REPLY_CONTEXT_API.md`](README_REPLY_CONTEXT_API.md)。
