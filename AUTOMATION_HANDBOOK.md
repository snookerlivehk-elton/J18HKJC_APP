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

### 1.1 資料契約（取貨唯一主路徑）

| 用途 | HTTP | Schema |
|------|------|--------|
| 賽前排位 | `GET {JJJC_API_BASE}/api/export/racecard?date=YYYY-MM-DD&venue=ST\|HV` | `jjjc.racecard.v1` |
| 賽後賽果 | `GET {JJJC_API_BASE}/api/export/results?date=YYYY-MM-DD&venue=ST\|HV` | `jjjc.results.v1` |

環境變量：`JJJC_API_BASE`（無尾斜線）。  
- 外網／阿里雲：`https://apicc.up.railway.app`  
- 同 Railway 內可選：`http://apijjjc.railway.internal:8787`

**空 `races: []`** = 上游尚未備好（或非賽日），J18 應 `waiting`，不要當硬失敗狂打。

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
- 賽前社交文案 `social_copy.json`（現手動）  
- 結算後 → 命中率可讀；可宣傳場次 → 賽後文案 `post_race_social_copy.json`（現手動／半自動）

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
| **SPEEDGUIDE** | 覆蓋 ≥ 約 80% runners | 距賽日 >36h 且空 → waiting；到期仍低 → failed／waiting |
| **FORMGUIDE** | 覆蓋 ≥ 約 80% | 空 → waiting |
| **FACTORS** | `factor_scores` 有近期資料 | 空 → 重算 |
| **NLP** | **可選**；現 check 常放行 | 不擋快照（可降級路徑） |
| **FORM_AI** | 覆蓋達標（建議 ≥80% 或業務定義） | 未跑 → pending；可背景 job |
| **SNAPSHOT** | 有未過期／當日 primary 或可用 batch；含 `ad_pick_rank`（新快照） | 無 → 建快照；可 provisional 後再 revision |
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
| F3 速勢 | `crawl_speedguide` | SPEEDGUIDE ok／可接受 waiting | 未到時間→waiting；到期不足→failed 或人工放行 |
| F4 賽績指引 | `crawl_formguide` | FORMGUIDE ok | 同 SG |
| F5 因子 | `run_factors`（預設無 NLP） | FACTORS ok | 無歷史→failed（查 J18 API／batch） |
| F6 Form AI | `start_form_ai_background` | FORM_AI ok | API key／配額→failed；可略過後 provisional |
| F7 快照 | `snapshot` | SNAPSHOT ok；鎖 fused／ad_pick_rank；可出海報 | 無排位→不做；provisional 標記 |
| F8 修訂 | `revise_snapshot`（資料補齊後） | 新 revision batch | 已結算不覆寫 |
| F9 文案 | （待做）自動 social copy | 檔案落地 | LLM 失敗→fallback／跳過不擋主鏈 |

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
| R4 宣傳評估 | `evaluate_ad_promo_hits`（唯讀） | 可宣傳列表 | 無命中→不做文案 |
| R5 賽後文案 | （待做自動）`generate_post_race_copy` | JSON＋可貼文 | LLM 失敗→fallback |
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
| `meeting_tick.py` 賽後 RESULTS→SETTLED | ✅ 已有（含 cooldown／max fails／dry-run） | 加輕探、generated_at 去重、+12h 窗 |
| 賽前 racecard→…→snapshot | ❌ 未做（排位**不會**因 JJJC 有貨而自動入 J18） | `mode=pre_race` 全鏈 |
| Railway／阿里雲 Cron | 手冊已教；需各邊掛 `start-tick.sh` | 雙邊常駐 |
| 廣告賽前／賽後文案自動 | 海報可跟快照；文案多手動 | 附屬 job |
| Webhook 由 JJJC 推送 | ❌ | 優化項（可替代部分輪詢） |
| 作戰室「標準流程」可視化 | 有 stage 狀態；缺一頁式 SOP 引導 | 手冊＋UI 對齊本文件 |

**重要：** 即使 JJJC 已有 9/13 排位，**現階段 J18 不會自動爬取**；需手動 `jjjc_racecard_sync` 或作戰室同步，或待賽前 tick 上線。

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

1. 選 fixtures：今日～未來 N 日  
2. 動作序：探＋`sync_jjjc_racecard` →（可選）SG／FG → factors → form_ai 背景 → snapshot  
3. 每步只在上游 stage ok 或可降級規則允許時推進  
4. dry-run 與作戰室 readiness 對照驗收  

### Phase D — 附屬自動化

1. 快照後確保海報  
2. 賽前 social copy（可開關）  
3. SETTLED 後 promo hits → 賽後 copy（可開關）  
4. 通知（可選：Telegram／email 僅 failed／需人工）  

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
# 等價：python meeting_tick.py --mode post_race --lookback-days 3 --json
```

未來：

```bash
python meeting_tick.py --mode pre_race --lookahead-days 3 --json
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

## 10. 待產品確認的決策（討論用）

請在開工 Phase C 前勾選／答覆：

1. **正式快照是否允許無 Form AI？**（現可降級 provisional）  
2. **SG／FormGuide 最低覆蓋 %？**（現約 80%）  
3. **賽前 tick 是否自動 revision，還是只建一次 primary？**  
4. **賽後文案／賽前文案：全自動產檔即可，還是要審批？**  
5. **失敗通知渠道？**（先只寫 log／stage detail 是否夠）  
6. **阿里雲 vs Railway：誰跑 pre_race、誰跑 post_race，或兩邊都跑？**（建議兩邊都跑但錯開分鐘，DB 各管各的）  
7. **沿路走勢遺留：最長保留天數？**（建議 21～30 日後標 `expired` 停撈）  
8. **評述到位後：是否自動觸發 NLP＋因子重算，還是只入遺留清單等人按？**（建議自動，但限批次大小）  

---

## 11. 數據遺留清單（延遲資料／沿路走勢）

### 11.1 為什麼需要

部分**賽後**資料不會跟「完場 +12h」一起到，常見要 **5～7 日**（甚至更耐）才齊。  
其中最難排程的是 **沿路走勢評述**（`running_comment_text` → 表 `text_reports`，`report_type=running_comment`）。

| 資料 | 典型來源（現況） | 節奏 |
|------|------------------|------|
| 名次／獨贏賠率 | api_jjjc `/api/export/results` | 完場約 +12h＋JJJC 重試 |
| 沿路走勢／事故評述 | **J18 歷史 API** → `etl_pipeline`／`batch_crawler` → `text_reports` | **無固定節奏**，常滯後數日 |
| NLP 結構化結果 | `nlp_batch_job` → `text_reports.nlp_result` | 有評述正文後才可跑 |

> **注意（2026-09）：** `jjjc_results_sync` **尚未**寫入 `running_comment`。遺留清單的「創新拉取」主路徑目前是 **重跑該日 J18 歷史增量**（`batch_crawler`／ETL），不是再打一次 jjjc results。若日後 JJJC export 也帶評述，再加一條 sync。

此類資料：

- **不阻擋** 當日 RESULTS／SETTLED（作戰室 NLP 節點已標可選）  
- **會影響** 之後賽日的近績／干擾持份者 coverage（查表推論）  
- 故要用 **遺留清單（backlog）** 長期補洞，而不是只靠單次賽後 tick

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
| `source_hint` | `j18_history` / `jjjc_results` / … |

**入列時機（每次 tick／更新順路做）：**

1. 賽後 RESULTS 已有名次，但該日 `text_reports` 缺 `running_comment`（相對 runners 覆蓋不足）→ 入列  
2. 輕探／sync 後發現仍缺賠率、部分場無名次 → 入列（可與 JJJC 重試疊加）  
3. 賽前發現 FormGuide／SG 過期仍空且已過預期上架窗 → 可入列（可選）  

**出列時機：**

- 覆蓋達標（例如該 meeting runners 有評述比例 ≥ 閾值，或「預期有評述的馬」齊）→ `done`  
- 超過保留窗（如 21～30 日）→ `expired`（停撈，可人工再開）  

### 11.3 每次更新「順路」掃清單（配合 JJJC／既有 Cron）

在 `meeting_tick`（或獨立 `backlog_tick`）每輪：

```
1. 跑當日主流程（pre/post）
2. SELECT backlog WHERE status IN (open, retrying)
     AND next_attempt_at <= now()
     LIMIT K          -- 每輪上限，避免拖垮
3. 按 data_kind 分流拉取：
     running_comment / incident → 重跑該日 J18 history（batch_crawler 單日）
     finish/odds → sync_jjjc_results（或等 JJJC）
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
`評述入庫 →（同輪或短延遲）NLP only_missing → 因子重算一次 → 對「未來未結算 meeting」可選 revise`。  
**不要**為補歷史評述而重結已 `settled_at` 的 batch。

#### 與覆蓋度手冊對齊

見 `COVERAGE_STAKEHOLDER_HANDBOOK.md`：缺評述 → I=0 + coverage↓；補丁後重算 I／相關因子；snapshot 用 revision 語意。

### 11.5 開發切片（接 Phase B/C）

| 步 | 內容 |
|----|------|
| B1 | `data_backlog` 表 + 賽後 tick 入列（缺 running_comment） |
| B2 | tick 順路重試 J18 單日 history |
| B3 | 新評述 → 觸發 NLP batch（limit） |
| B4 | NLP 完成 → 因子重算（防抖：合併為每輪一次） |
| B5 | 可選：未來賽日 auto-revise |

---

## 12. 變更紀錄

| 日期 | 說明 |
|------|------|
| 2026-09-10 | 初版：配合 JJJC 全自動；賽前／賽後 SOP；現況 vs 目標；開發切片 A–E |
| 2026-09-10 | §11：數據遺留清單；沿路走勢延遲；評述到位後 NLP→因子→revision 流程 |

---

## 13. 快速對照（給值班）

| 問題 | 答案 |
|------|------|
| JJJC 有 9/13 排位，J18 會自動入庫嗎？ | **現在不會**；要手動 sync 或等賽前 tick |
| `JJJC_API_BASE` 填什麼？ | Public：`https://apicc.up.railway.app` |
| 賽後何時積極拉名次？ | 對齊完場約 +12h |
| 沿路走勢為何常缺？ | 多經 J18 歷史 API，滯後 5～7 日；用遺留清單補 |
| 評述到了要立刻重算因子？ | **先 NLP，再重算因子**；合併批次；已結算快照不覆寫 |
| 空 export 怎辦？ | `waiting`，交給 JJJC 重試 |
| 主狀態在哪？ | `meeting_pipeline` + 作戰室 |
| Cron 跑什麼？ | `bash start-tick.sh`（獨立服務） |
