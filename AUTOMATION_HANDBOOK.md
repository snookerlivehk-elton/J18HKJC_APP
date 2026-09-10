# J18 賽日全自動運作優化手冊

> **給誰看**：產品（Snooker）、開發／Cloud Agent。  
> **用途**：作戰實驗室標準流程 + 全自動開發依據。改碼前先對本手冊對齊，避免兩邊各自狂爬。  
> **最後更新**：2026-09-10  
> **相關**：`DEVELOPMENT_REPORT.md`（總覽）、`meeting_pipeline.py`（狀態機）、`meeting_tick.py`（Cron tick）、api_jjjc（上游爬蟲）

---

## 0. 一句話目標

**JJJC 負責從馬會抓數並備好 export；J18 按階段閘門取貨、檢查齊備、推進下一步；缺料則重試／等待／人工介入；最終賽前有快照＋海報，賽後有結算＋命中／賽後文案。**

---

## 1. 系統分工（不可混淆）

| 系統 | 職責 | 不做 |
|------|------|------|
| **api_jjjc**（例 Railway：`https://apicc.up.railway.app`） | 官網／GraphQL 拉取；賽前未來數日排位；完場約 **+12h** 拉賽果；缺料自帶重試；提供 JSON export | 不寫 J18 snapshot／settle |
| **J18HKJC_APP**（本 repo） | `GET /api/export/*` → 入庫；因子／Form AI／快照／結算／廣告；狀態機＋tick | **不應**再爬馬會官網作主路徑（HTML 僅備援） |
| **作戰室** `views/meeting_ops.py` | 人工監看、放行、略過、備援重抓 | 不取代 Cron 長跑 |

### 1.1 資料契約（取貨主路徑）

| 用途 | HTTP | Schema／去向 |
|------|------|----------------|
| 賽前排位 | `GET {JJJC_API_BASE}/api/export/racecard?date=&venue=` | `jjjc.racecard.v1` → `upcoming_*` |
| 賽後賽果（名次／賠率） | `GET …/api/export/results?date=&venue=` | `jjjc.results.v1` → `runners` |
| **賽事指引／沿路走勢／競賽報告（文字）** | **主路徑：JJJC** → 見 §1.3 | → `upcoming_formguide`／`text_reports` |
| **速勢能量 SG** | **主路徑：JJJC** → 見 §1.3 | → `upcoming_speedguide` |
| 同上（備援） | HKJC CMS 爬蟲／J18 歷史 API | 僅當 JJJC 無貨或失敗 |

環境變量：`JJJC_API_BASE`（無尾斜線）。  
- 外網／阿里雲：`https://apicc.up.railway.app`  
- 同 Railway 內可選：`http://apijjjc.railway.internal:8787`

**空 `races: []`** = 上游尚未備好（或非賽日），J18 應 `waiting`，不要當硬失敗狂打。

### 1.3 賽前加料來源決策（2026-09-10 更新｜api_jjjc 正式契約）

產品確認：下列均可由 **JJJC** 取得；**HKJC CMS／J18 歷史 API 僅備援**。  
**勿指望** `jjjc.racecard.v1`／`jjjc.results.v1` 內出現 SG／短評／沿途／事故欄位。

| 種類 | 業務含義 | J18 落庫 | 主路徑 | 備援 |
|------|----------|----------|--------|------|
| 速勢能量 **SG** | 能量／狀態評級 | `upcoming_speedguide` | **JJJC** `GET /api/export/speedguide`（`jjjc.speedguide.v1`） | HKJC SpeedPro CMS（`speedguide_crawler`） |
| 賽事指引 | 近績／形勢短評 | `upcoming_formguide.form_text` | **JJJC** `GET /api/export/formguide`（`jjjc.formguide.v1`） | HKJC FormGuide CMS；再退 J18 API |
| 沿路走勢 | 沿路評述／走位 | `text_reports` `running_comment`（別名 `corunning`） | **JJJC** `GET /api/export/text-reports`（`jjjc.text_reports.v1`） | J18 歷史 API |
| 競賽報告 | 競賽／事故報告 | `text_reports` `incident_report`（別名 `racereport`） | 同上（`report_type=incident_report` 或 `racereport`） | J18 歷史 API |

**HTTP 契約（J18 已實作 sync）：**

| Export | schema | J18 模組 | `run_action` |
|--------|--------|----------|--------------|
| `/api/export/speedguide?date=&venue=`（可選 `raceNo`） | `jjjc.speedguide.v1` | `jjjc_speedguide_sync.py` | `sync_jjjc_speedguide`；`crawl_speedguide`＝JJJC→CMS 備援 |
| `/api/export/formguide?date=&venue=` | `jjjc.formguide.v1` | `jjjc_formguide_sync.py` | `sync_jjjc_formguide`；`crawl_formguide`＝JJJC→CMS 備援 |
| `/api/export/text-reports?date=&venue=`（可選 `raceNo`／`report_type`） | `jjjc.text_reports.v1` | `jjjc_text_reports_sync.py` | `sync_jjjc_text_reports`（賽後 tick 會順路打） |

欄位對照：
- `races[].runners[].energy` → `upcoming_speedguide.speed_energy`
- `energy_delta` → `speed_energy_delta`；`fitness_rating` → `form_rating`
- `races[].runners[].form_text` → `upcoming_formguide.form_text`
- `reports[report_type=running_comment|incident_report].runners[].text` → `text_reports.report_text`  
  （`is_placeholder=true`／空字＝略過，視為 waiting）

**語意：**
- **waiting**（繼續輪詢）：HTTP 200 且 `races=[]`／`reports=[]`；文字 null／""；`is_placeholder`；`status`∈ unpublished／suspicious／date_mismatch／partial／empty  
- **failed**（可切備援）：5xx／連線失敗／`status=unavailable`  
- **更新指紋**：用 `content_updated_at`（勿用每次 GET 都刷新的 `generated_at`）  
- **Join**：`race_id`（`YYYYMMDD`+`ST|HV`+兩位場次）+ `horse_no`  
- **report_type 契約（api_jjjc 2026-09-10 確認）**：response **只出** `incident_report`／`running_comment`；查詢可用別名 `racereport`／`corunning`。對照：`incident_report`←R3 競賽報告；`running_comment`←R4 沿途走位。

**建議同步順序：** 賽前 racecard → speedguide → formguide；賽後 results → text-reports。

**探針備註（2026-09-10 复测 apicc）：**  
`/api/export/text-reports`、`/speedguide`、`/formguide` **已上線**（200）。text-reports 實測 9/6 ST、9/9 HV 可入庫；沿途評述常仍 placeholder／suspicious，競賽報告可先入庫，之後重拉冪等 upsert。

**遺留／重試拉取順序：**  
1. JJJC（主）→ 2. 對應備援 → 3. 仍無則 waiting／退避。

### 1.2 效率原則（配合 JJJC 已全自動）

1. **輕探 → 有變才重同步**：先看 `race_count` / `generated_at`（或 `fetched_at`）；無變不 upsert。  
2. **時間窗對齊**：賽果積極同步對齊完場 **+10～14h**；此前可低頻探活。  
3. **重試分層**：馬會缺頁 → JJJC 重試；export 空 → J18 waiting；入庫／settle 失敗 → J18 短冷卻 + max fails。  
4. **禁止**：Streamlit request 內長跑；同一 stage 無冷卻連打；J18 與 JJJC 同時爬馬會。

---

## 2. 狀態機（作戰實驗室單一真相）

程式：`meeting_pipeline.py`  
表：`meeting_pipeline`（`racing_date, course, stage, status, detail, manual_override`）  
輔助：`meeting_tick_state`（tick 失敗次數／上次 attempt）

### 2.1 階段順序（STAGES）

```
FIXTURE → RACECARD → SPEEDGUIDE → FORMGUIDE → FACTORS
       → NLP(可選) → FORM_AI → SNAPSHOT → RESULTS → SETTLED
```

附屬（建議納入自動，但可先不進 STAGES 硬閘）：

- 快照成功 → 廣告海報（已可 `AD_OUTPUT_ON_SNAPSHOT`）  
- 賽前社交文案 `social_copy.json`（✅ `MEETING_TICK_AUTO_SOCIAL_COPY`，預設 true）  
- 結算後 → 命中率可讀；可宣傳場次 → 賽後文案 `post_race_social_copy.json`（✅ `AUTO_PROMO_HITS`＋`AUTO_POST_RACE_COPY`）

### 2.2 狀態碼

| status | 含義 | Tick 行為 |
|--------|------|-----------|
| `pending` | 尚未做／未達標 | 可嘗試推進 |
| `waiting` | 上游未上架／未到時間窗 | 冷卻後再探；**不**累加硬失敗 |
| `ok` | 達標 | 跳過；可進下游 |
| `failed` | 可重試的失敗或覆蓋不足 | 冷卻 + fail_count；達上限停手等人 |
| `skipped_manual` | 人工略過 | **永不**自動強跑 |

`manual_override=true` 且 status 為 `ok`／`skipped_manual` → tick **尊重人工，不覆蓋、不強跑**。

### 2.3 齊備門檻（標準「檢查清單」）

以下為**作戰實驗室建議標準**（可與現有 `check_*` 微調，但改門檻要改手冊＋測試）。

| 階段 | 齊備（→ ok） | 未齊（waiting／pending／failed） |
|------|----------------|-----------------------------------|
| **FIXTURE** | 賽日在 `fixtures` | 無賽期 → 跑 fixtures 爬蟲 |
| **RACECARD** | upcoming 該日場次數達標（建議 ≥ 當日預期場數或 ≥8）；每場有馬；無錯位 | export 空 → waiting；有場無馬／錯位 → failed（可備援 HTML） |
| **SPEEDGUIDE** | 馬匹覆蓋 ≥80% | 未達 → waiting／failed；**未達標禁止任何快照** |
| **FORMGUIDE** | 馬匹覆蓋 ≥80% | 未達 → waiting／failed；**未達標禁止任何快照**（與 SG／AI 一致） |
| **FORM_AI** | 馬匹覆蓋 ≥80% | 未達 → pending；**未達標禁止任何快照** |
| **SNAPSHOT** | 僅當 SG＋FormGuide＋Form AI 皆 ≥80% | 否則不建；無快照 ⇒ 無廣告／命中主路徑 |
| **RESULTS** | historical `runners` 該日有 `finish_order_num` | 空 → waiting（對齊 JJJC +12h） |
| **SETTLED** | 對應 batch 有 `settled_at`（每場名次覆蓋達現有 ≥50% 規則） | 有名次未滿 → 重跑 settle；無快照 → 不能結 |

---

## 3. 賽前標準流程（Pre-race SOP）

### 3.1 流程圖（邏輯）

```
fixtures 有賽日
    → 輕探 racecard export（race_count / generated_at）
    → 有貨？否 → waiting（冷卻）→ 結束本輪
    → 是 → sync_jjjc_racecard → check RACECARD
         → 不齊 → 備援 HTML 或 failed／人工
         → 齊 → SPEEDGUIDE / FORMGUIDE（可並行探＋爬）
              → 達標或可降級？
              → FACTORS（可不待 NLP）
              → FORM_AI（only_missing；長跑背景）
              → SNAPSHOT（可 provisional）
              → （可選）修訂 revision 當 SG／AI 補齊
              → （可選）賽前 social copy
```

### 3.2 每步：動作／成功／失敗分支

| 步驟 | 自動動作（`run_action`） | 成功 | 失敗／缺料分支 |
|------|--------------------------|------|----------------|
| F0 賽期 | `crawl_fixtures`（低頻，如每日） | FIXTURE ok | 人工補賽日 |
| F1 探排位 | HTTP 輕探 export | race_count>0 且 generated_at 新 | waiting |
| F2 同步排位 | `sync_jjjc_racecard` | RACECARD ok | 空→waiting；錯位→備援 `crawl_racecard` 或人工 |
| F3 速勢 SG | **JJJC sync**（目標）；備援 `crawl_speedguide` | SPEEDGUIDE ok | 空→waiting；不足→failed／人工 |
| F4 賽事指引 | **JJJC sync**（目標）；備援 `crawl_formguide` | FORMGUIDE ok | 同 SG |
| F5 因子 | `run_factors`（預設無 NLP） | FACTORS ok | 無歷史→failed（查 J18 API／batch） |
| F6 Form AI | `start_form_ai_background` | FORM_AI ok | API key／配額→failed；可略過後 provisional |
| F7 快照 | `snapshot`（**僅當 FORM_AI ok**） | SNAPSHOT ok；鎖 fused／ad_pick_rank；可出海報 | Form AI 未達標 → **禁止正式快照／廣告** |
| F8 修訂 | `revise_snapshot`（資料再齊後） | 新 revision batch | 已結算不覆寫；revision 亦須 Form AI 仍達標 |
| F9 文案／海報 | 自動 social＋歸檔 | 檔案落地 | **無正式快照 → 不觸發** |

### 3.3 賽前時間建議（可調）

| 相對開賽 | J18 行為 |
|----------|----------|
| T-7d～T-3d | 探 fixtures＋racecard；有則 sync |
| T-2d～T-36h | 催 SG／Form；可跑 FACTORS |
| T-36h～T-12h | Form AI；允許 provisional 快照 |
| T-12h～T-2h | 資料齊則 revision；定稿海報／文案 |
| 開賽後 | 賽前鏈停止；轉賽後監聽 |

### 3.4 可降級（覆蓋度持份者）路徑

與 `DEVELOPMENT_REPORT` §2.2b 一致：

1. 排位齊 → 因子（可不待 NLP）  
2. SG／評述未齊也可 **provisional 快照**  
3. 齊備後 **revision**（不覆寫已結算）  
4. 人工可「放行」某 stage 讓下游繼續  

---

## 4. 賽後標準流程（Post-race SOP）

### 4.1 流程圖

```
完場
    →（建議）等到約 +10～14h 或輕探 results 有 race_count
    → sync_jjjc_results
    → check RESULTS
         → 無／不足 → waiting（信任 JJJC 重試）
         → 齊 → settle_pending
              → SETTLED ok？
              → 是 → 命中率可讀；evaluate_ad_promo_hits
                   → 有可宣傳場次 →（可選）賽後文案
              → 否 → 部分名次：保留 waiting，下輪再 settle
```

### 4.2 每步

| 步驟 | 自動動作 | 成功 | 分支 |
|------|----------|------|------|
| R1 探賽果 | 輕探 export results | race_count>0、generated_at 新 | 空→waiting（尤其未到 +12h） |
| R2 同步 | `sync_jjjc_results` | runners 有 finish_order_num | 空 export→waiting；HTTP 錯→failed |
| R3 結算 | `settle`（`settle_pending`） | batch `settled_at` | 無名次／未達 50%→waiting；無快照→跳過並記 detail |
| R4 宣傳評估 | `evaluate_ad_promo_hits` | 可宣傳列表 | **無正式已結算快照 → 不跑／不廣告** |
| R5 賽後文案 | 自動 `generate_post_race_copy`＋歸檔 | JSON＋可貼文 | 無命中或不滿足 R4 → 不觸發 |
| R6 可選 | 重算因子／NLP batch | 模型資料更新 | 不擋 SETTLED |

### 4.3 與 JJJC +12h 對齊

| 完場後時間 | J18 建議 |
|------------|----------|
| 0～10h | 低頻輕探（如每 1～2h）或乾脆不探 |
| 10～24h | 正常 tick（30～60 分）積極 sync＋settle |
| 24h+ | 仍 waiting → 繼續探；fail 僅限真・HTTP／解析錯 |
| 多日未齊 | fail_count 達上限 → `failed`＋通知人工 |

備援：夜間 GHA `batch_crawler`／J18 歷史 API 仍可補洞，但**主路徑是 jjjc results export**。

---

## 5. 人工介入標準（作戰室）

| 情境 | 操作 | 之後 tick |
|------|------|-----------|
| 官方長期無 SG，但要出快照 | 人工放行 SPEEDGUIDE 或允許 provisional | 尊重 override |
| 排位錯位／壞資料 | 備援 HTML 重抓；或略過當日 | 清 override 後才恢復自動 |
| LLM／Form AI 配額爆 | 略過 FORM_AI；provisional 快照 | 不擋 SNAPSHOT（若規則允許） |
| 連續 failed | 查 Logs／export；修 env 後 `--force` 或清 tick_state | 恢復自動 |
| 錯誤結算／錯日 | 人工停 tick；修資料；必要時重建 | |

UI：`views/meeting_ops.py`（放行／略過／清除覆寫／各 stage 手動鈕）。

---

## 6. Tick 實作現況 vs 目標

| 能力 | 現況（2026-09-10） | 目標 |
|------|-------------------|------|
| `meeting_tick.py` 賽後 RESULTS→SETTLED＋text-reports | ✅ 已有（含 cooldown／max fails／dry-run） | 加輕探、`content_updated_at` 去重、+12h 窗 |
| 賽前 racecard→SG→FG→factors→Form AI→snapshot | ✅ `mode=pre_race`／`all`（硬閘：SG+FG+Form AI 齊才 snapshot） | 輕探 fingerprint；Webhook |
| Railway／阿里雲 Cron | `start-tick.sh` 預設 `mode=all`；GHA 每小時 | 雙邊常駐確認掛載 |
| 廣告賽前／賽後文案自動 | ✅ 海報跟快照；賽前 social＋賽後 promo／copy 經 tick（`ad_copy_jobs.py`） | 通知／儀表板歸檔瀏覽 |
| Webhook 由 JJJC 推送 | ❌ | 優化項（可替代部分輪詢） |
| 作戰室「標準流程」可視化 | 有 stage 狀態；缺一頁式 SOP 引導 | 手冊＋UI 對齊本文件 |

**Cron 一鍵：** `bash start-tick.sh` ≡ `python meeting_tick.py --mode all --json`（賽前前瞻 `MEETING_TICK_LOOKAHEAD_DAYS`＋賽後回看 `MEETING_TICK_LOOKBACK_DAYS`）。

開關（環境變數）：
- `MEETING_TICK_MODE=all|pre_race|post_race`
- `MEETING_TICK_AUTO_FACTORS`／`AUTO_FORM_AI`／`AUTO_SNAPSHOT`（預設 true）
- `MEETING_TICK_AUTO_SOCIAL_COPY`／`AUTO_PROMO_HITS`／`AUTO_POST_RACE_COPY`（預設 true；Phase D）
- `AD_SOCIAL_TONE`（賽前／賽後文案語氣；預設跟 `ad_llm_copy.DEFAULT_TONE`）
- 正式快照**不會**在閘門未齊時自動出 provisional
- 文案冪等：`ad_output/archive/{date}_{course}/{social|promo_hits|post_race}_latest.json` 以 `batch_id` 去重
---

## 7. 開發切片（跟隨本手冊開工順序）

### Phase A — 文件與閘門（本文件）

- [x] 寫本手冊  
- [ ] 產品確認：齊備門檻數字、是否允許無 Form AI 出正式快照、賽後文案是否進自動  

### Phase B — 取貨效率（賽後已有 tick 上增強）

1. sync 前輕探 `race_count` + `generated_at`  
2. 寫入 `meeting_tick_state` 或等價快取「上次指紋」  
3. 賽後時間窗：未到完場+10h 預設跳過或極低頻  
4. 測試：空 export／有更新／無更新 三態  

### Phase C — 賽前 tick（`mode=pre_race`）

1. [x] 選 fixtures：今日～未來 N 日  
2. [x] 動作序：`sync_jjjc_racecard` → SG／FG（JJJC→CMS）→ factors → form_ai 背景 → snapshot（硬閘）  
3. [x] 每步 cooldown／manual_override；dry-run  
4. [ ] 作戰室 readiness 對照驗收（阿里雲）  
5. [ ] 確認兩邊 Cron／GHA 已用 `mode=all`
### Phase D — 附屬自動化

1. [x] 快照後確保海報（既有 `AD_OUTPUT_ON_SNAPSHOT`）  
2. [x] 賽前 social copy（`MEETING_TICK_AUTO_SOCIAL_COPY` → `ad_copy_jobs.run_auto_social_copy`）  
3. [x] SETTLED 後 promo hits → 賽後 copy（`AUTO_PROMO_HITS`／`AUTO_POST_RACE_COPY`）  
4. [ ] 通知（可選：Telegram／email 僅 failed／需人工）  

### Phase E — 優化

1. JJJC webhook／etag  
2. Railway internal URL 自動偵測  
3. 作戰室「一鍵對照手冊 SOP」進度條  

每一切片：**先測 dry-run → 阿里雲驗收 → 再開 Cron**。

---

## 8. 運維掛載（Cron）

### 8.1 指令

```bash
bash start-tick.sh
# 等價：python meeting_tick.py --mode all --lookback-days 3 --lookahead-days 3 --json
```

亦可單獨：

```bash
python meeting_tick.py --mode pre_race --lookahead-days 3 --json
python meeting_tick.py --mode post_race --lookback-days 3 --json
python meeting_tick.py --mode all --json
```

### 8.2 Railway

- **獨立** service（勿與 Streamlit 共用）  
- Start Command：`bash start-tick.sh`  
- Cron Schedule（UTC）：如 `*/30 * * * *`  
- Variables：`USE_SQLITE=false`、`DATABASE_URL`、`JJJC_API_BASE=https://apicc.up.railway.app`、可選 `MEETING_TICK_*`  

### 8.3 阿里雲 ECS（主驗收）

```cron
*/30 * * * * cd /path/to/J18HKJC_APP && set -a && source .env && set +a && bash start-tick.sh >> /var/log/j18_meeting_tick.log 2>&1
```

### 8.4 GitHub Actions

`.github/workflows/meeting_tick.yml`：`tick-railway` / `tick-aliyun`（缺 secret 則 skip）。

---

## 9. 核對清單（每次改自動邏輯必跑）

### 9.1 上游

```bash
export BASE=https://apicc.up.railway.app
curl -sS "$BASE/api/export/racecard?date=YYYY-MM-DD&venue=ST" | head
curl -sS "$BASE/api/export/results?date=YYYY-MM-DD&venue=ST" | head
# 期望：schema 正確；有貨則 race_count>0
```

### 9.2 入庫

```bash
python jjjc_racecard_sync.py --date YYYY-MM-DD --course ST
python jjjc_results_sync.py --date YYYY-MM-DD --course ST
python meeting_tick.py --date YYYY-MM-DD --course ST --dry-run --json
```

### 9.3 作戰室

- readiness 與 tick 報告一致  
- 人工略過後 tick 不再強跑該 stage  

### 9.4 業務

- 賽前：有 snapshot batch、海報可選  
- 賽後：`settled_at`、命中率頁可讀、可宣傳規則可評估  

---

## 10. 產品決策紀錄（已確認／待解釋）

### 10.1 已拍板（2026-09-10）

| # | 決策 | 實作含義 |
|---|------|----------|
| 1 | **無 Form AI → 不能出任何正式快照** | FORM_AI 馬匹覆蓋 ≥80% 前禁止 snapshot |
| 1b | **無速勢能量 SG → 不能出任何快照** | SPEEDGUIDE 馬匹覆蓋 ≥80% 前禁止 snapshot（SG 為主要評分參考；見 §10.1c） |
| 1c | **覆蓋門檻** | SG／FormGuide／Form AI 一律 **馬匹覆蓋 ≥80%** |
| 3b | **資料未齊 → 不出命中快照／統計，也不觸發廣告** | 無正式快照（及賽後未結算）⇒ 不產海報定稿、不產賽前／賽後社交文案、不進可宣傳命中統計 |
| 3c | **沿路走勢等遺留** | 最長保留 **10～14 日**；取得後 **自動 NLP（若為文字）→ 因子重算** |
| 4 | **文案全自動產檔** | 僅在閘門通過後；每期歸檔可回測 |
| 5 | **失敗必須通知＋判斷是否要人工** | 自動化中控儀表板 |
| 6 | **兩邊都跑（對稱）** | 分庫、Cron 錯開 |

### 10.1b Form AI／SG 與快照的前後關係

**正式快照硬閘門（生產）：**

```
排位齊
  → SG 馬匹覆蓋 ≥80%          ← 缺則完全不建快照
  → FormGuide ≥80%             ← 同樣硬閘
  → Form AI ≥80%
  → 才建立正式 primary 快照
  → 才允許海報／文案／其後命中與賽後廣告
```

| 問 | 答 |
|----|----|
| Form AI 在快照前還是後？ | **之前** |
| SG 可以缺嗎？ | **不可以**——你定案：缺 SG **不生成任何快照** |
| 賽後結算／廣告？ | 只認正式快照；無快照 ⇒ 無命中主統計 ⇒ 不廣告 |

### 10.1c 舊制「可缺料仍出快照」缺什麼？vs 新定案

**舊／現行程式（可降級 provisional）** 在資料未齊時仍可能建快照，並在列上記 `provisional_reasons`，常見包括：

| 代碼 | 意思 |
|------|------|
| `sg_missing` | 該場／該馬缺少 Speed Guide（速勢能量） |
| `nlp_pending` | 沿路走勢 NLP 尚未解析（干擾通道降覆蓋） |
| `low_match` | 因子查表匹配偏弱 |

另外業務上還可能「未齊仍鎖」的有：Form Guide 不足、Form AI 未跑完（舊可降級；**你已禁止無 Form AI 出正式快照**）。

權重上 SG 相關（`WEIGHT_SG_FORM`／`WEIGHT_SG_ENERGY`／`WEIGHT_SG_DELTA`）是總分重要來源之一，缺 SG 時分數會偏離「有 SG 的正賽版本」——因此你要求 **缺 SG 就不要生成快照** 合理，手冊改為：

- **禁止** 帶 `sg_missing` 的生產快照（含 primary／revision）  
- **禁止** 無 Form AI 達標的快照  
- Form Guide：**同樣硬閘**——未達 80% **不出快照**（Form AI 依賴指引；與 SG／AI 一致）。

### 10.2b 「覆蓋率」是什麼？（馬匹覆蓋，不是「某一列表頭齊不齊」）

程式現況（`meeting_pipeline.check_*`）定義：

\[
\text{覆蓋率} = \frac{\text{該賽日該場地「已有該資料的馬匹數」}}{\text{排位表馬匹總數（upcoming_runners）}}
\]

達標線現為 **≥ 80%**。

| 階段 | 分子（有資料的馬） | 分母 |
|------|-------------------|------|
| SPEEDGUIDE | `upcoming_speedguide` 且 `speed_energy IS NOT NULL` | 同日同場地 runners |
| FORMGUIDE | `upcoming_formguide` 且 `form_text` 非空 | 同上 |
| FORM_AI | `upcoming_form_ai` 且 `summary IS NOT NULL` | 同上 |

所以是 **「多少匹馬已齊這包資料」**，不是「meeting 那一列有沒有填完所有欄位」。  
例：100 匹排位馬，80 匹有 SG 能量 → 80% → ok；只有 50 匹有 → 不足。

（若將來要「關鍵欄位齊備」第二層檢查，另加規則；與現覆蓋率分開。）

### 10.2 Speed Guide（SG）／Form Guide／文字三件是什麼？

| 名稱 | 板塊 | 本系統 | 主來源（新決策） |
|------|------|--------|------------------|
| **Speed Guide（速勢能量）** | 能量／狀態評級 | `upcoming_speedguide` | **JJJC**；HKJC CMS 備援 |
| **賽事指引（Form Guide 類）** | 近績短評彙整 | `upcoming_formguide` | **JJJC**；CMS／J18 API 備援 |
| **沿路走勢** | 沿路評述 | `text_reports.running_comment` | **JJJC**；J18 API 備援 |
| **競賽報告** | 事故／競賽報告 | `text_reports.incident_report` 等 | **JJJC**；J18 API 備援 |
| **Form AI** | 我方 LLM 評分 | `upcoming_form_ai` | 依賴賽事指引等就緒後再跑 |

和 **排位** 區分：排位＝誰出賽；SG＝速勢能量；文字三件＝敘述類；Form AI＝自有分數。

### 10.3 Primary 快照 vs Revision 是什麼？

一次「預測快照」= 把某賽日當下的模型分、AI 分、融合推介、`ad_pick_rank` 等 **鎖進資料庫**（`prediction_snapshot_batches` + `prediction_snapshots`），之後結算、命中率、廣告推介都以這批為準。

| 種類 | `snapshot_kind` | 意思 | 何時用 |
|------|-----------------|------|--------|
| **Primary（主快照）** | `primary` | 該賽日**第一份正式鎖分** | Form AI 齊備後首次建立；**正式出賽／對外表**以它為錨 |
| **Revision（修訂快照）** | `revision` | **追加**一份新 batch，`revision_of` 指向舊 batch；**不刪、不覆寫**舊資料 | 主快照之後，SG／Form／因子／AI 又更新了，想用新分數再鎖一版（例如開賽前最終版） |
| **Provisional（臨時）** | 常搭 `provisional=true` | 資料未齊仍鎖一版（可降級） | **依你的決策 #1：正式流程禁止用「無 Form AI」當正式 primary**；provisional 僅內部實驗／人工明確允許時 |

生活化比喻：

- **Primary**＝交卷的第一份正式答案紙  
- **Revision**＝老師允許「再交一版修訂卷」，舊卷仍留底（方便對照／回測）  
- 賽後結算：對**選定的 batch**（通常最新未結算或指定 primary）回填名次；已 `settled_at` 的 batch **不再改分數**

### 10.4 文案全自動＋每期歸檔回測

目標檔案（現有）：

- 賽前：`ad_output/social_copy.json`（最新覆蓋）＋ `archive/{date}_{course}/social_*.json`  
- 賽後：`ad_output/post_race_social_copy.json`／`promo_hits.json` ＋對應 archive  
- 觸發：`meeting_tick`（`ad_copy_jobs.py`）；冪等看 `*_latest.json` 的 `meeting.batch_id`

**回測要求（已實作 latest＋timestamped）：**

```
ad_output/archive/{racing_date}_{course}/social_{timestamp}.json
ad_output/archive/{racing_date}_{course}/post_race_{timestamp}.json
ad_output/archive/{racing_date}_{course}/promo_hits_{timestamp}.json
```

JSON 內保留：`meeting`、`tone`、`source`（llm／fallback）、`featured`、完整 `post_text`、觸發的 `batch_id`／命中規則。  
儀表板可列出歷史版本並對照當日命中（回測）（UI 瀏覽仍待 Phase E）。

### 10.5 失敗通知＋是否人工介入（儀表板）

原則：

1. Tick／sync 失敗寫 stage + `meeting_tick_state`  
2. 系統依規則標 **`needs_human: true/false`**（例如：fail_count≥上限、排位錯位、FORM_AI 擋正式快照逾時、backlog 將 expired）  
3. 管理介面「自動化儀表板」一眼看出：哪日卡住、卡在哪、要不要人  

詳細線框見 **§14**。

### 10.6 「兩邊都跑」vs「分工」——詳細分別

兩邊＝**阿里雲（主驗收）**＋**Railway（並行）**，通常是**兩套 Postgres**（或偶發共庫，不建議共庫雙寫）。

#### 方案 A：兩邊都跑（對稱）

```
阿里雲 Cron ──► meeting_tick ──► 阿里雲 DB ──► 阿里雲作戰室
Railway Cron ──► meeting_tick ──► Railway DB ──► Railway 網頁
         ▲                              ▲
         └──── 都 pull 同一 JJJC API ────┘
```

| 優點 | 缺點 |
|------|------|
| 一邊掛了另一邊仍有完整自動鏈 | **雙倍** API／LLM／算力 |
| 方便對照「同一天兩邊結果一不一樣」 | 若共庫會搶寫；分庫則資料可能漂移 |
| 設定簡單（兩邊 env 同款） | 告警會雙份，要過濾 |

適合：現在這種**雙軌測試期**，要驗證阿里雲／Railway 行為一致。

#### 方案 B：分工（不對稱）

例：

| 邊 | 負責 | 不負責 |
|----|------|--------|
| **阿里雲** | 全部 tick（賽前＋賽後＋backlog＋文案）、主 DB、儀表板 | — |
| **Railway** | 只跑 Streamlit／預測 API 展示；或只跑 dry-run／唯讀 | 不寫正式 snapshot |

或：Railway 只跑 `post_race`，阿里雲跑 `pre_race`（較少見，除非 DB 共用且要分散負載）。

| 優點 | 缺點 |
|------|------|
| 省錢、單一真相在主庫 | 備援邊沒有完整自動；主邊掛則全停 |
| 告警集中 | 兩邊功能不一致，要文件寫清 |

適合：雙軌結束、**阿里雲定為唯一生產**之後。

#### 怎麼選（已拍板）

- **測試期（現在）：方案 A 兩邊都跑** — 分庫、Cron 錯開分鐘、儀表板可對照。  
- 之後若定阿里雲為唯一生產，再改方案 B（手冊保留）。

---

## 11. 數據遺留清單（延遲資料／沿路走勢）


### 11.1 為什麼需要

部分資料不會跟「完場 +12h 名次」一起到，或賽前文字會遲到；其中 **沿路走勢／競賽報告** 常要多日才齊。

| 資料 | 主來源（目標） | 備援 | 節奏 |
|------|----------------|------|------|
| 名次／獨贏賠率 | api_jjjc `/api/export/results` | J18 歷史／batch_crawler | 完場約 +12h＋重試 |
| 速勢能量 SG | **JJJC** | HKJC SpeedPro CMS | 賽前陸續 |
| 賽事指引 | **JJJC** | HKJC FG CMS → J18 API | 賽前陸續 |
| 沿路走勢／競賽報告 | **JJJC** | J18 歷史 API | 可能滯後；用 backlog |
| NLP 結構化 | `nlp_batch_job` → `nlp_result` | — | 有正文後才跑 |

> **架構（2026-09-10）：** 文字三件以 JJJC 為主；J18 歷史 API **只作備援**。  
> **程式現況（2026-09-10）：** ✅ `data_backlog` 表＋tick 入列／退避重試＋操作員頁「數據遺留清單」；覆蓋以歷史有名次 runners 為母體，`running_comment`／`incident_report` 正文達 80% 作出列。

此類資料：

- **不阻擋** 當日 RESULTS／SETTLED（名次鏈獨立）  
- **會影響** Form AI／干擾 coverage／之後查表  
- 用 **遺留清單** 長期補洞

### 11.2 清單應記什麼（建議表 `data_backlog`）

建議欄位（實作時可 SQLite／PG 一張表）：

| 欄位 | 說明 |
|------|------|
| `id` | PK |
| `racing_date` / `course` / `race_id` | 粒度：建議先 **race 或 meeting**，評述可再細到 runner |
| `data_kind` | 如 `running_comment`、`incident_report`、`finish_order`、`win_odds`、`formguide`… |
| `status` | `open` / `retrying` / `done` / `expired` / `skipped_manual` |
| `first_seen_at` / `last_attempt_at` / `done_at` | |
| `attempt_count` | |
| `next_attempt_at` | 退避用 |
| `last_error` / `detail` | |
| `source_hint` | `jjjc` / `j18_history_fallback` / … |

**入列時機（每次 tick／更新順路做）：**

1. 賽後 RESULTS 已有名次，但該日 `text_reports` 缺 `running_comment`（相對 runners 覆蓋不足）→ 入列  
2. 輕探／sync 後發現仍缺賠率、部分場無名次 → 入列（可與 JJJC 重試疊加）  
3. 賽前發現 FormGuide／SG 過期仍空且已過預期上架窗 → 可入列（可選）  

**出列時機：**

- 覆蓋達標（例如該 meeting runners 有評述比例 ≥ 閾值，或「預期有評述的馬」齊）→ `done`  
- 超過保留窗（**10～14 日**）→ `expired`（停撈，可人工再開）  

### 11.3 每次更新「順路」掃清單（配合 JJJC／既有 Cron）

在 `meeting_tick`（或獨立 `backlog_tick`）每輪：

```
1. 跑當日主流程（pre/post）
2. SELECT backlog WHERE status IN (open, retrying)
     AND next_attempt_at <= now()
     LIMIT K          -- 每輪上限，避免拖垮
3. 按 data_kind 分流拉取：
     formguide / running_comment / incident → **先 JJJC 文字／賽前 export**；仍缺 → J18 history 備援
     finish/odds → sync_jjjc_results
4. 刷新覆蓋檢查 → 達標則 done，否則加大退避寫回 next_attempt_at
5. 若本輪有「新評述寫入」→ 觸發 §11.4 管道（可异步／下輪）
```

**退避建議（無固定節奏的評述）：**  
首日每 6～12h → 其後每日 1 次 → 7 日後每 2～3 日 → 至保留窗結束。  
勿與「完場 +12h 名次窗」綁死。

### 11.4 沿路走勢到位後：要不要立刻重算因子？正確流程

**不要**一拿到評述就只喊 `run_all_factors` 完事。正確順序：

```
① 評述正文入庫（text_reports.report_text，nlp_result 仍空）
    ↓
② NLP 解析（nlp_batch_job／只處理 nlp_result IS NULL）
    ↓
③ 重算因子（干擾通道／近績相關）
    ↓
④ 視情況：未來賽日 revision 快照（已結算舊 batch 不覆寫）
```

#### 為什麼要先 NLP？

- 沿路走勢的**機器可用訊號**在 `nlp_result`（受阻／腳軟等），不是原文本身。  
- stakeholder 模式：基礎 HORSE／SPEED 可不烤 NLP；**干擾持份者 I** 與 coverage 要靠 NLP。  
- 無 NLP 就重算：多數情況 I 仍缺，白跑。

#### ③ 因子重算範圍（建議）

| 做法 | 說明 |
|------|------|
| **預設** | `run_all_factors(persist=True)`（或至少 HORSE／SPEED／INTERFERENCE_*）寫入 `factor_scores` |
| **目的** | 更新**歷史查表**，令之後賽日匹配用到新評述／干擾 |
| **已結算賽日** | **不要**改寫該日 `prediction_snapshots` 的鎖分（結算真相不動） |
| **未開跑／未結算的未來賽日** | 若已有 provisional／primary 快照，可 `revise_snapshot` 吃新因子 |

#### 要不要「立刻」？

| 選項 | 建議 |
|------|------|
| 每寫入 1 場評述就全庫重算 | ❌ 太貴 |
| 本輪 backlog 結束後，若 `new_comments > 0`，排隊 **一次** NLP batch + **一次** 因子重算 | ✅ 推薦 |
| 僅標記 `needs_recompute=true`，交下一班維護窗（如每日凌晨） | ✅ 若白天負載高 |

**推薦預設：**  
遺留保留 **10～14 日**；正文入庫後 **自動 NLP（文字類）→ 因子重算一次**；未來未結算 meeting 可選 revise。  
**不要**為補歷史評述而重結已 `settled_at` 的 batch。

#### 與覆蓋度手冊對齊

見 `COVERAGE_STAKEHOLDER_HANDBOOK.md`：缺評述 → I=0 + coverage↓；補丁後重算 I／相關因子；snapshot 用 revision 語意。

### 11.5 開發切片（接 Phase B/C）

| 步 | 內容 |
|----|------|
| B1 | `data_backlog` 表 + 缺文字／名次入列 | ✅ `data_backlog.py` |
| B2 | tick 順路：**JJJC 文字主路徑**＋退避；UI 遺留清單 | ✅ post_race／all 掛載；`views/data_backlog.py`＋作戰室③ |
| B3 | ✅ 與 JJJC 對齊三支 export：`jjjc_speedguide_sync`／`jjjc_formguide_sync`／`jjjc_text_reports_sync`（見 §1.3） |
| B4 | 新評述 → NLP batch（limit） | ✅ `MEETING_TICK_BACKLOG_AUTO_NLP`（預設 true） |
| B5 | NLP 完成 → 因子重算（每輪一次） | ✅ `MEETING_TICK_BACKLOG_AUTO_FACTORS`（預設 **false**，可開） |
| B6 | 可選：未來賽日 auto-revise | 未做 |

---

## 14. 自動化儀表板（管理介面設計）

> 取代「只靠作戰室逐日點」：一頁看清全自動健康、遺留、要不要人。  
> 入口建議：管理員選單 **「自動化中控」**（與作戰室並列；作戰室保留手動按鈕）。

### 14.1 一屏資訊架構（由上而下）

**A. 總覽條（今日／未來 3 日／賽後 7 日）**

| 指標 | 含義 |
|------|------|
| 健康 meeting 數 | 無 `needs_human`、無 failed |
| 等待中 | `waiting`（上游未到） |
| 需人工 | 規則判定要介入 |
| 遺留評述 open | backlog `running_comment` |
| 最近 tick | 上次成功／失敗時間（阿里雲／Railway 可分頁籤） |

用色：綠=順、琥珀=waiting、紅=需人工／failed。**不要**做成雜亂多卡 dashboard；一條總覽 + 下列兩表即可。

**B. 賽日流水表（主表，一目了然）**

每列一個 `racing_date + course`：

| 欄 | 內容 |
|----|------|
| 賽日／場地 | |
| 鏈路 | 賽前｜賽後｜遺留（小點：灰未開始／藍進行／綠 ok／琥珀 wait／紅 block） |
| 目前卡點 | 如 `FORM_AI`、`RESULTS`、`backlog:running_comment` |
| 正式快照 | 有 primary？provisional？Form AI 是否達標（決策 #1） |
| 結算 | settled_at 有無 |
| 人工 | `需要／不需要` + 原因一句 |
| 動作 | 「去作戰室」「略過」「重試 tick」「清失敗計數」 |

**C. 需人工佇列（只列 needs_human=true）**

原因標籤例如：`排位錯位`、`Form AI 逾時不能出正式快照`、`tick 連敗達上限`、`評述遺留將過期`。

**D. 產檔／回測抽屜**

按賽日列出 archived social／post_race 版本；可預覽 `post_text`、下載 JSON。

### 14.2 `needs_human` 判定（系統自動）

| 條件 | needs_human |
|------|-------------|
| status=waiting 且未過預期窗 | 否（繼續等 JJJC／官方） |
| fail_count ≥ max_fails | **是** |
| RACECARD 錯位／corrupt | **是** |
| 距開賽 &lt; Xh 且 FORM_AI 未 ok（擋正式快照） | **是** |
| backlog 將 expired | **是**（或警告） |
| LLM fallback 出稿 | 否（可記 info） |

### 14.3 與作戰室關係

| 頁 | 職責 |
|----|------|
| **自動化中控（新）** | 多日總覽、告警、遺留、產檔回測、一鍵重試 |
| **作戰室（現有）** | 單日深挖、手動 sync／放行／略過 |

---

## 15. 決策狀態

| 題 | 狀態 |
|----|------|
| 覆蓋 ≥80% | ✅ |
| 缺 SG／FormGuide／Form AI → 不出任何快照；無快照不廣告 | ✅ |
| 遺留 10～14 日；到齊自動 NLP→因子重算 | ✅ |
| 兩邊都跑 | ✅ |
| 自動 revision | ✅ 預設：閘門齊建一次 primary；仍達標且有更新才可 revision |
| JJJC export 契約 | ⏳ 請用 §16 提示詞問對方 |

---

## 16. 給 JJJC 專案 AI 的提示詞（可直接複製）

```text
你是 api_jjjc／JJJC 爬蟲專案的助手。我們下游系統是 J18HKJC_APP，目前已用：

- GET {BASE}/api/export/racecard?date=YYYY-MM-DD&venue=ST|HV
- GET {BASE}/api/export/results?date=YYYY-MM-DD&venue=ST|HV

schema 分別為 jjjc.racecard.v1、jjjc.results.v1。
公開 racecard／results 裡目前主要是排位與名次／賠率，尚未穩定見到以下欄位。

我們需要把「JJJC 當主資料源、HKJC CMS／J18 歷史 API 只作備援」。請清楚回答：

1) 下列資料現在是否已由你們爬取並入庫？若有，對應的 DB 表／欄位名是什麼？
   - 速勢能量 Speed Guide（energy／form／delta 或等價）
   - 賽事指引／Form Guide 短評文字
   - 沿路走勢評述（running comment）
   - 競賽報告／事故報告（incident／race report）

2) 下游應如何取得？請給「唯一建議」的 HTTP 契約：
   - 是擴充現有 /api/export/racecard 與 /api/export/results？
   - 還是新 endpoint（請寫完整 path）？
   - 查詢參數（date、venue、raceNo…）？
   - 回應 JSON 的 schema 名稱與版本（例如 jjjc.racecard.v2）？
   - 請貼一份「含上述欄位」的最小樣本 JSON（可打碼馬名），標出欄位路徑。

3) 時間語意：
   - SG／賽事指引：最早大約賽前多久會有非空資料？
   - 沿路走勢／競賽報告：完場後多久開始有？會否分批補齊？如何用 generated_at／fetched_at 判斷「有更新」？

4) 空資料語意：races=[] 或某馬文字為 null／"" 時，下游應視為 waiting 還是 failed？

5) 若同一日資料稍後補齊，export 是否保證幂等 upsert？下游能否只靠 generated_at 變更決定是否重拉？

請用條列回答，並給「J18 應實作的 sync 對照表」：
JJJC 欄位路徑 → 建議寫入 J18 的表.欄位
（J18 目標表：upcoming_speedguide、upcoming_formguide.form_text、
 text_reports report_type=running_comment|incident_report）
```

---

## 12. 變更紀錄

| 日期 | 說明 |
|------|------|
| 2026-09-10 | 多輪：JJJC 主路徑、雙跑、Form AI／SG／廣告閘門等 |
| 2026-09-10 | 覆蓋 80%；缺 SG 不出快照；遺留 10–14 日；§16 JJJC 提示詞 |
| 2026-09-10 | §1.3 寫入 api_jjjc 正式三支 export 契約；J18 sync 模組落地 |
| 2026-09-10 | Phase C：`meeting_tick` 支援 `pre_race`／`all`；`start-tick.sh` 預設全鏈 |

---

## 13. 快速對照（給值班）

| 問題 | 答案 |
|------|------|
| 無 SG／FormGuide／Form AI（&lt;80%）？ | **不生成任何快照**；無快照則無廣告／命中主路徑 |
| 舊 provisional 可缺什麼？ | 常有 `sg_missing`／`nlp_pending`／`low_match`——生產已禁止缺 SG／AI |
| 遺留評述？ | 留 10～14 日；到齊 → NLP→因子重算 |
| JJJC 契約？ | §1.3 三支 export（speedguide／formguide／text-reports）；§16 為當初問句存檔 |
| 兩邊都跑？ | 已確認，分庫錯開 Cron |
| `JJJC_API_BASE` | `https://apicc.up.railway.app` |
