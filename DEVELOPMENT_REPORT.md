# J18 賽馬量化預測系統 — AI 開發交接手冊

> **給下一位 AI / 開發者**：先讀本文件與 [`AUTOMATION_HANDBOOK.md`](AUTOMATION_HANDBOOK.md)（賽日全自動 SOP），再讀 [`FACTOR_MODEL_DESIGN.md`](FACTOR_MODEL_DESIGN.md)（數學白皮書）。  
> **覆蓋度持份者（已落地）**：見 [`COVERAGE_STAKEHOLDER_HANDBOOK.md`](COVERAGE_STAKEHOLDER_HANDBOOK.md)。預設 `COVERAGE_MODE=on`、`INTERFERENCE_MODE=stakeholder`；缺評述／SG 可建 provisional 快照，資料到位後 `revise_snapshot`。  
> 實作以**查表推論**為主：歷史 → `factor_scores` → 排位條件匹配 → 加權總分。  
> **部署（2026-09 起暫時雙軌）**：**阿里雲為主要運作系統**（例：`http://47.83.164.64`）；**Railway**（`j18hkjc-app.up.railway.app`）暫時並行。所有開發／驗證須**先顧及阿里雲環境**（路徑、字型、Nginx／反向代理、本機碟、記憶體限制），再兼顾 Railway。  
> 程式碼仍經 **GitHub `snookerlivehk-elton/J18HKJC_APP` `main`** 發布；本機 `.env` 連同一套（或對應環境的）Postgres（勿提交密碼）。  
> **計算邏輯／結構可改；UI 以 GitHub `main` 最新為準，勿用本地舊版覆蓋。**  
> **自動化**：賽後 `meeting_tick` 已落地；賽前全鏈見 `AUTOMATION_HANDBOOK.md` Phase C（尚未實作）。

---

## 0. 一句話產品流程

1. 爬歷史賽果 + 排位表（馬、騎練、檔位、ST/HV、班次、距離、跑道）  
2. 依白皮書算各因子 Z-Score，寫入 `factor_scores`  
3. 對即將舉行的賽事做條件匹配 → 預測排名  

UI 不應再做成「純因子實驗室」；主路徑是 **排位 → 查表 → 預測**。

---

## 1. 目前架構（2026-09 現況）

### 1.1 資料層

| 來源 | 表 / 產物 | 說明 |
|------|-----------|------|
| J18 歷史 API | `race_meetings`, `races`, `runners`, `text_reports` | `batch_crawler` / `etl_pipeline` |
| **api_jjjc 排位** | `upcoming_races`, `upcoming_runners` | `jjjc_racecard_sync.py` ← `GET /api/export/racecard`（`jjjc.racecard.v1`）；join=`race_id`+`horse_no` |
| **api_jjjc 賽果** | `runners.finish_order_num`（+ `payouts`） | `jjjc_results_sync.py` ← `GET /api/export/results`（`jjjc.results.v1`） |
| **api_jjjc 文字（目標）** | `upcoming_formguide`、`text_reports` | 賽事指引／沿路走勢／競賽報告：**JJJC 主路徑**；J18 歷史 API 僅備援（見 `AUTOMATION_HANDBOOK` §1.3） |
| HKJC 排位（備援） | 同上 upcoming_* | `racecard_crawler` HTML；作戰室保留「備援重抓」 |
| HKJC Speed Guide | `upcoming_speedguide` | CMS JSON：`consvc.hkjc.com/.../SpeedPro/current/sg_*`；賽前約 1 日中午上架 |
| 因子落庫 | `factor_scores` | **推論只讀這張表**（查表，不每次現算） |

- 雲端：`USE_SQLITE=false` + `DATABASE_URL` / `DATABASE_URL_SYNC`  
- 排位同步需：`JJJC_API_BASE`（api_jjjc 根網址，無尾斜線；亦相容 `JJJC_RESULTS_API_BASE`）  
- 本地可 SQLite，但與 Railway 開發請對齊 Postgres  
- `start.sh`：**只跑 Streamlit**，部署時不要重爬整年歷史  

### 1.2 Bucket 政策（極重要）

實作在 `bucket_utils.py`。

| 用途 | Bucket 例 | 誰用 |
|------|-----------|------|
| **細桶** `Venue_Track_Distance` | `ST_A_1200`, `HV_C+3_1650` | **DRAW**（檔位） |
| **粗桶** `Venue_距離帶` | `ST_SPRINT`, `HV_MILE`, `ST_STAY` | **JOCKEY / TRAINER / SYNERGY / HORSE（近績）** |
| **GLOBAL** | `GLOBAL` | **HORSE_JOCKEY**、**PACE**、**SPEED** |

距離帶：SPRINT 1000–1200、MILE 1400–1650、STAY 1800–2400（夾縫靠最近帶）。

**歷史坑**：J18 歷史 `races.course` 常是「草地」；真正場地碼在 `race_id`（如 `YYYYMMDDST01`）。必須用 `extract_venue(race_id=...)`，否則歷史與排位對不上。

### 1.3 `factor_scores` 類型一覽

| factor_type | bucket | 實體 | 計算入口 |
|-------------|--------|------|----------|
| JOCKEY | 距離帶粗桶 | 騎師名 | `calculate_entity_factor(..., use_distance_band=True)` |
| TRAINER | 距離帶粗桶 | 練馬師名 | 同上 |
| SYNERGY | 距離帶粗桶 | `騎師 & 練馬師`（`synergy_name`） | 同上 |
| DRAW | 細桶 | Inner / Mid-Inner / Mid-Outer / Outer | `calculate_draw_factor` |
| HORSE | 距離帶粗桶 | 馬名 | `calculate_horse_factor`（可 NLP 受阻 + 降班） |
| HORSE_JOCKEY | GLOBAL | `馬|騎` | 合作 Z + 換人 Δ（匹配時近距加權） |
| PACE | GLOBAL | 馬名 | 跑法／追回 Z；頁面另算同場步速熱度 |
| SPEED | GLOBAL | 馬名 | Peak/EMA；Par＝venue+track+距離+班次**分位數**（樣本不足回退）；FSR；可選 NLP |

推論加權見 `config.py`：`WEIGHT_*`（含 `WEIGHT_RECENT_FORM`、`WEIGHT_PACE`、`WEIGHT_SPEED_FIGURE`、Speed Guide 三項）。

### 1.4 關鍵檔案地圖

```
ui_app.py                # 入口：登入關卡 + st.navigation（start.sh）
auth_utils.py            # 白名單／bootstrap／登入登出
ui_theme.py              # 登入／管理／用戶 CSS
views/home.py            # 系統主頁（載歷史、重算因子）
views/whitelist.py       # 白名單 CRUD（僅 admin）
views/data_control.py    # 資料控制中心
views/meeting_ops.py     # 賽日作戰室
views/ad_output.py       # 廣告輸出（公司原圖風格全賽日 PNG）
views/raceday.py         # 賽日速覽（用戶主畫面）
views/inference.py       # 融合預測
views/calibration.py     # 因子命中率
views/form_ai.py         # 賽績 AI
views/*_factor.py         # 各因子診斷頁
pages/                   # 留空（勿自動掛頁，避免用戶看到管理選單）
bucket_utils.py / config.py / factor_calculator.py / inference_engine.py
meeting_pipeline.py / fixture_crawler.py / …
prediction_api.py / prediction_export.py / start-api.sh   # 對外賽前預測 API
schema.sql
```

### 1.5 登入與角色分頁

| 角色 | 可見頁面 | 登入憑證 |
|------|----------|----------|
| **user** | 僅「賽日速覽」 | `auth_whitelist` 中 `role=user` 的 email／通行碼 |
| **admin** | 全部管理頁 + 白名單 + 賽日速覽 | `role=admin` 的 email／通行碼 |

- 表：`auth_whitelist`（token、token_type=email|password、role、label、is_active）  
- 環境變數：`AUTH_BOOTSTRAP_ADMIN` — **僅當庫內尚無 active admin** 時可當開機通行碼登入，登入後請立刻在白名單加正式 admin。  
- 安全：Streamlit session 屬「擋君子」；勿把密鑰寫進程式碼或 git。  
- 導航：`st.navigation` 依角色組裝；`pages/` 目錄刻意留空。  

首次上線 SOP：Railway 設 `AUTH_BOOTSTRAP_ADMIN` → 開站登入 → 白名單新增 admin／user → 可清空或輪替 bootstrap。

#### Speed Guide 實作要點

- **URL（給人看）**：https://racing.hkjc.com/zh-hk/local/info/speedpro/speedguide?raceno=1  
- **真正資料**：`https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/sg_index` 與 `sg_race_{N}`（UTF-8 BOM JSON）  
- 欄位映射：`fitnessrating`→`form_rating`；`speedproenergy`→`speed_energy`；`speedproenergydifference`→`speed_energy_delta`  
- 推論：Fitness：`0`=倒轉拇指→`-1.5`，`1/2/3`=向上拇指→`0/1/2`；能量**同場 Z**；差值× `WEIGHT_SG_DELTA`  
- CLI：`python speedguide_crawler.py`（可選 `--date` / `--course` 核對、`--races 1,2`）  

Streamlit：`ui_app.py` + `views/`；`streamlit>=1.40`（`st.navigation`／`st.Page`）。

---

## 2. 運維 Runbook（改碼後必做）

### 2.0 雙軌部署（阿里雲優先）

| 環境 | 角色 | 備註 |
|------|------|------|
| **阿里雲**（例 `47.83.164.64`） | **主要運作系統** | 開發／驗收以這邊為準；注意 Nginx／反向代理逾時、本機 `ad_output/`、系統資源 |
| **Railway** | 暫時並行 | 與阿里雲同 repo `main`；ephemeral 碟、重佈署會清本機檔 |
| GitHub `main` | 唯一發佈來源 | 兩邊都應跟 `main`；功能先在阿里雲確認再視為完成 |

**開發原則**：新功能、修 bug、效能／體積（如海報 ≤800KB）、靜態資源路徑，**先確保阿里雲可跑**；勿只在本機或只在 Railway 通過就結案。

### 2.1 部署後

1. 阿里雲／Railway 部署完成（以阿里雲為主驗收）  
2. 主頁 **「重算並寫入 factor_scores」**（Bucket 規則或因子公式變更後**必須**重算，否則匹配率歸零）  
3. 若改了排位爬蟲欄位：資料控制中心 **重新抓排位**  
4. 近績要吃 NLP：賽日模式解析 → 再算近績／主頁重算  

### 2.2 NLP（賽後報告）

- Key：**只**用環境變數 `OPENAI_API_KEY`（可選 `OPENAI_MODEL`、`OPENAI_BASE_URL`）。**禁止**在 UI 輸入 Key。  
- 結果寫入 `text_reports.nlp_result`（JSON），**可重用**；只處理 `nlp_result IS NULL`。  
- UI：**整個賽日解析**（該日該場地所有排位馬）+ 自動略過空白／「無特別報告」。  
- 換頁會中斷 Streamlit 同步迴圈；長跑用 `python nlp_batch_job.py --limit 200`。  
- **Form AI 長跑**：作戰室按「後台啟動 Form AI」（可關頁）；或  
  `python form_ai_batch_job.py --date YYYY-MM-DD --course ST`；  
  或 GitHub Actions → **Form AI Background Job**（workflow_dispatch）。  
- **解析 ≠ 已入近績/速度**：必須再跑對應計算（或主頁重算）。近績頁有「NLP vs 近績分數時間」警示。  

兩種 NLP 用途（勿混）：

| 用途 | 行為 |
|------|------|
| 近績 HORSE | **legacy**：受阻 → 調整該場 raw_score；**stakeholder（預設）**：基礎近績不烤 NLP |
| 速度 SPEED | **legacy**：受阻 → SF 小幅上修；**stakeholder**：基礎 SF 不併 NLP |
| 干擾持份者 | `INTERFERENCE_FORM`／`INTERFERENCE_SPEED` 獨立落庫；缺評述 → I=0 + coverage↓ |

### 2.2b 可降級賽日路徑（覆蓋度持份者）

1. 排位齊 → **重算因子**（可不待 NLP；干擾通道可低覆蓋）  
2. SG／評述未到也可 **建立快照**（`provisional=true`）  
3. NLP／SG 到位 → **重算（含 NLP／干擾）** → 作戰室 **修訂快照 revision**（追加 batch，不覆寫已結算）  
4. 賽後照常 RESULTS → 結算；校準頁可見覆蓋度分桶  

開關：`config.COVERAGE_MODE`（off/shadow/on）、`INTERFERENCE_MODE`（legacy/stakeholder）。細節見手冊。

### 2.3 環境變數（Railway）

```
USE_SQLITE=false
DATABASE_URL=...
DATABASE_URL_SYNC=...   # SQLAlchemy 用的同步 URL
J18_API_BASE_URL=...    # 公司內 J18 歷史 API 源站或完整 historyResult URL（費用敏感，勿寫死／勿公開）
JJJC_API_BASE=...       # api_jjjc 根網址（排位／賽果 export；無尾斜線）
OPENAI_API_KEY=...      # 可選但 NLP 需要
OPENAI_MODEL=gpt-4o-mini
AUTH_BOOTSTRAP_ADMIN=...  # 僅庫內尚無 admin 時的開機通行碼
PREDICTION_API_KEY=...    # 對外預測 API（獨立服務）；Header X-API-Key
PREDICTION_API_CORS=*     # 可選；逗號分隔 origin
# OpenRouter 時設 OPENAI_BASE_URL + 對應 model 名
```

本地 `.env` 同上；**勿 commit**。`J18_API_BASE_URL` 可填 `https://api.j18.hk`（自動接 path）或完整 `…/historyResult`。密碼若曾貼在聊天室請輪替。

### 2.4 賽前預測 API（外部平台）

給另一平台拉**展示用預測**，並用本系統 `model_win_prob` + **對方即時獨贏小數賠率**算凱利／值搏指數。

| 項目 | 說明 |
|------|------|
| 程式 | `prediction_api.py`（FastAPI）+ `prediction_export.py`（payload／Kelly） |
| 啟動 | `bash start-api.sh` → `uvicorn prediction_api:app --host 0.0.0.0 --port $PORT` |
| 部署 | **Railway 第二個服務**（勿與 Streamlit 同一 process）；共用同一 `DATABASE_URL*` |
| 認證 | Header `X-API-Key: <PREDICTION_API_KEY>`；未設 key 時受保護路由回 503 |

| Method | Path | 用途 |
|--------|------|------|
| GET | `/health` | 探活（無需 key） |
| GET | `/v1/meetings?date=&course=` | 即將舉行賽日／場次清單 |
| GET | `/v1/races/{race_id}/prediction` | 單場預測；可選 `odds=3:5.5,7:8`、`kelly_scale=0.5` |
| POST | `/v1/races/prediction-with-odds` | body 傳 `win_odds` 後回傳含 Kelly 的預測 |
| GET | `/v1/meetings/{date}/{course}/predictions` | 整日（較重；預設不含 factors） |
| POST | `/v1/kelly` | 純算：已知 `p` + 小數賠率 → `kelly_fraction` / edge |

Kelly：`f*=(b·p−q)/b`，`b=o−1`，`q=1−p`，`o`＝小數獨贏（例 `5.0`）。半凱利用 `kelly_scale=0.5`。展示以 **model_win_prob** 為主；`picks.win` / `picks.place` 與賽日速覽邏輯對齊；可選 Form AI 欄位。

```bash
curl -s -H "X-API-Key: $PREDICTION_API_KEY" \
  "$API/v1/races/20260906ST01/prediction?odds=1:4.5,3:8&kelly_scale=0.5"
```

OpenAPI：部署後 `/docs`。

---

## 3. 已知坑（改碼前先看）

1. **`raw_json` 在 Postgres 是 `dict`**：不可無腦 `json.loads`；先 `isinstance(raw, dict)`（步速曾因此全空）。  
2. **排位表 HTML 欄位偏移**：檔位／練馬師索引錯會導致 draw=0、練馬師變閘號 → `racecard_looks_corrupt()`。  
   班次：本地球「一／二／三級賽」須能解析（勿只認「第X班／國際X級賽」）；`parse_class_num` 將級賽／表列視為 **第一班 (=1)**。  
3. **細桶過嚴**：馬「有近績」≠ 命中本場條件；騎練／近績已改粗桶，檔位仍細桶。  
4. **人馬 HORSE_JOCKEY**：合作本身 GLOBAL；現場近距加權 + 換人 Δ 層級回退（粗桶查騎師 Z）。  
5. **Speed Guide**：頁面是 Next.js「正在加載」；真實資料在 CMS JSON（`sg_index` / `sg_race_N`），**勿再 scrape HTML**。Fitness 是 `0/1/2/3` 拇指數；能量推論用**同場 Z**；差值直接入分。缺值給 0。  
6. **Streamlit 換頁**：長任務（NLP 批次）會停；非背景 job。  
7. **`run_all_factors` 回傳**：`(jockey, trainer, synergy, draw, hj, horse, pace, speed)` — 改 UI 解包時注意數量。  
8. **UI 被 GitHub 同事更新後**：本地舊 `views/`／`ui_theme.py` 推上去會蓋掉最新版面 — 見 §4.1。  

---

## 4. 開發慣例（給 AI）

### 4.1 UI 與 GitHub 協作（必讀）

> **GitHub 上會有 UI 同事持續優化頁面 UI。**  
> 本地工作區與 `origin/main` 的 UI 程式**有機會不同**；下次開發**計算邏輯／資料結構／推論／API 時，禁止用本機舊 UI 蓋掉 GitHub 上已合併的最新 UI**。

| 可改（邏輯／結構） | 勿輕易覆蓋（UI 外觀／互動） |
|--------------------|------------------------------|
| `factor_calculator.py`、`inference_engine.py`、`config.py`、`bucket_utils.py` | `ui_theme.py`、`ui_app.py`、`auth_utils.py`（登入／導航殼） |
| `*_crawler.py`、`meeting_pipeline.py`、`etl_pipeline.py` | `views/*.py` 的版面、CSS、元件排版、文案樣式 |
| `prediction_api.py`、`prediction_export.py`、schema／DB | `assets/`、靜態圖示、品牌展示相關 |

**開工前 SOP**

1. `git fetch origin` → `git status`／`git log HEAD..origin/main`：確認遠端是否有新 UI commit。  
2. 有遠端更新先 **`git pull`（或 rebase）** 再改邏輯；衝突時：**保留 GitHub 側 UI／樣式相關 hunk**，只合併你的計算／API 變更。  
3. Commit 前用 `git diff` 自查：是否誤含僅本地的舊 `ui_theme`／`views` 排版；有則還原那些檔再提交。  
4. 若必須動 UI（例如新欄位一定要顯示）：**先 pull 最新 UI**，再最小改動；勿整檔覆蓋。  
5. **計算邏輯與結構以本手冊／白皮書為準；視覺以 GitHub `main` 最新為準。**

### 4.2 一般慣例

- **改 Bucket / 公式後**：更新計算 + 匹配 UI（在**最新** UI 上最小改動）+ `inference_engine` + 手冊；提醒使用者重算 `factor_scores`。  
- **因子頁模式**：可從 DB 載歷史計算（`ui_utils.get_history_df_for_compute`），不要只綁主頁 session。  
- **落庫**：`save_factor_scores` 只保留標準欄位；診斷欄（跑法、Peak、NLP場次）可留 session／回傳 DataFrame。  
- **名稱**：一律 `normalize_person_name`（去括號磅數）；騎練組合用 `synergy_name`。  
- **因子／融合參數**：放在**主內容區** `st.expander`（勿只放 `st.sidebar`；側欄收合時會像「參數 UI 消失」）。  

建議實作順序（新因子）：

1. `factor_calculator` 純函式 + 可落庫  
2. 專頁匹配／診斷（基於最新 UI，勿覆蓋同事樣式）  
3. `inference_engine` + `WEIGHT_*`  
4. `run_all_factors` / 主頁  
5. 更新本手冊  

---

## 5. 自動化藍圖與賽後開發流程

### 5.1 已落地（手動作戰室）

- `fixture_crawler.py` → `fixtures`（無參數當月頁才有當月；`CalMonth=當月` 可能空殼）
- `meeting_pipeline.py`：`refresh_readiness` + stage + 手動動作
- UI：`pages/14_賽日作戰室.py`

階段：`FIXTURE → RACECARD → SPEEDGUIDE → FORMGUIDE → FACTORS → NLP → FORM_AI → SNAPSHOT → RESULTS → SETTLED`

### 5.2 賽前手動 SOP（目前生產）

1. 作戰室選賽日 → 重新檢查 readiness  
2. 缺什麼按什麼（排位／SG／Form Guide／Form AI）  
3. **賽前**建立預測快照（鎖總分＋當版模型勝率）  
4. 改了勝率公式／權重後：**必須重建快照**再賽  

### 5.3 賽後自動化

> **詳情與標準 SOP**：見 [`AUTOMATION_HANDBOOK.md`](AUTOMATION_HANDBOOK.md)。  
> **已落地**：`meeting_tick.py`（`mode=post_race`）+ `start-tick.sh` + GHA `meeting_tick.yml`。  
> **原則**：狀態機 + 短 Cron；依 readiness 重試；空 export → waiting；禁止無限狂爬。  
> **下一步**：輕探／generated_at 去重、對齊 JJJC 完場 +12h；再做賽前 `mode=pre_race`。

| 步驟 | 觸發 | 動作 | 成功準則 |
|------|------|------|----------|
| A | 完場約 +10～14h（或 export 有貨） | `sync_jjjc_results` | RESULTS=ok |
| B | 有未結算 snapshot | `settle_pending` | batch 有 `settled_at` |
| C | 結算後（可選） | 命中評估／賽後文案 | 可宣傳場次有稿 |

**掛載**：Railway／阿里雲獨立 Cron → `bash start-tick.sh`（勿塞進 Streamlit）。

### 5.4 賽前 Cron（見手冊 Phase C）

fixtures → 輕探 racecard → sync → SG／FormGuide → factors → Form AI → snapshot（可 provisional／revision）。  
**現況：尚未自動；JJJC 有排位 ≠ J18 已入庫。**

---

## 6. 待辦優先序（Roadmap）

### P0 — 穩定生產

- [ ] 確認 Railway 每次 deploy 後有無需要的「重算因子」SOP（文件化給使用者）  
- [ ] 排位爬蟲回歸測試（欄位索引）  
- [ ] 歷史爬蟲監控（J18 API 偶發封鎖）  

### P1 — 模型品質

- [ ] 步速形勢加權併入推論總分（現多在 Pace 頁）  
- [x] SPEED：Par 桶修正（ST/HV＋class_num）+ 分位數／最少樣本回退（`SPEED_PAR_*`）  
- [ ] SPEED：固定末 400m 真實距離；可選 HKJC 官方標準時間錨  
- [ ] 降班三條件再校準；NLP 過濾假性腳軟／假性無追勢（白皮書 Phase 5）  
- [ ] Peak vs EMA 雙特徵進總分／ML  
- [ ] 用已結算快照校準 `SOFTMAX_TEMPERATURE`  

### P2 — 自動化與產品

- [x] **賽後**：`meeting_tick.py` post_race（見 `AUTOMATION_HANDBOOK.md`）  
- [ ] **賽後增強**：輕探／generated_at／+12h 窗  
- [ ] **賽前**：`mode=pre_race` 全鏈（手冊 Phase C）  
- [x] Form AI：獨立馬評軌道（推介＋快照命中；不併入 `WEIGHT_*`）  
- [ ] 實驗追蹤（匯出 `ModelConfig.get_params_dict()`）  

### 階段完成（2026-09-05）— 暫停點

已交付、可手動作戰：

- 登入分權、賽日速覽雙軌（模型勝率%｜AI 推介指數%）  
- Form AI 獨立軌道 + 進度條；快照鎖 `ai_*`；命中訊號「AI評價×信心」  
- 賽前預測 API（Kelly）；雷達同場 min/max（含負分）  

**下一步（人工）**：本賽日完場 → RESULTS → 結算快照 → 對照命中率。通過後再開 §5.3 全自動。

---

## 7. 快速自檢指令（本機連 Railway DB）

```bash
# .env: USE_SQLITE=false + DATABASE_URL_SYNC
python -c "from factor_calculator import FactorCalculator; c=FactorCalculator(); \
 print(c.load_factor_scores().groupby('factor_type').size())"

python -c "from inference_engine import InferenceEngine; e=InferenceEngine(); \
 r=e.get_upcoming_races(); print(len(r)); \
 print(e.predict_race(r.iloc[0].race_id)[2]['hit_counts'])"

# Speed Guide（CMS；日期可省略，以 sg_index 為準）
python speedguide_crawler.py --date 2026/09/06 --course ST
# 或只抓第 1 場：python speedguide_crawler.py --races 1
```

Smoke：各 `factor_type` 有列；預測 `hit_counts` 對 JOCKEY/TRAINER/HORSE 等非全 0（重算後）。

---

## 8. 文件關係

| 文件 | 角色 |
|------|------|
| **本檔 `DEVELOPMENT_REPORT.md`** | 架構、運維、坑、待辦 — **AI 接手首讀** |
| **`FACTOR_MODEL_DESIGN.md`** | 數學與產品定義（勿無故偏離） |
| **`schema.sql`** | 表結構（含 `text_reports.nlp_result`） |
| **`config.py`** | 可調參數唯一來源 |

### 分數／勝率／凱利（三層）

| 層 | 內容 | 用途 |
|----|------|------|
| A 因子／總分 | 可正可負（Z-Score + 加權） | 排序、診斷、雷達前的原料 |
| B 雷達半徑 | 同場每軸 min→中心、max→外緣（圖上 [0,1]；原始可負） | **只顯示**；hover 看原始 Z；不是勝率 |
| C 模型勝率 | 場內 z(總分) → `softmax(/T)`，加總≈1 | 外傳凱利；`prediction_api` / `export_kelly_payload` |
| D **AI 馬評（獨立）** | `ai_score`×`confidence`＝`ai_combo` | **不混入**總分／權重；並排推介 + 快照命中統計 |

- **不要**把總分硬加常數變正數再當機率。  
- **不要**把各因子 Z 改成同場瓜分 100%（破壞跨場比較與校正）。  
- **不要**把 Form AI 分數併入 `WEIGHT_*`／總分（AI 是參考了因子＋賽績指引的獨立馬評家）。  
- `SOFTMAX_WITHIN_RACE_Z`（預設 True）+ `SOFTMAX_TEMPERATURE`（預設 1.5）：壓低極端勝率。  
- Kelly：`p=model_win_prob`，小數賠率 `o`，`b=o-1`，`q=1-p`，`f*=(b p - q)/b`（見 §2.4）。  
- AI 推介：`form_ai_picks.py`；賽前快照鎖 `ai_*`；`evaluate_settled` 訊號「AI評價×信心」。重建快照才含 AI 欄。  
- 用戶 UI 推介列：AI 只顯示指數**百分比**（如 `72%`）；評價×信心算式僅在馬匹詳情。  

---

## 9. 變更日誌（摘要）

| 日期 | 內容 |
|------|------|
| 2026-09-09 | **廣告輸出公司模版**：跟從藍／米色原圖；動態高度；每場最多 4 匹只顯示馬號＋馬名；PNG≤2MB；隨機色調 |
| 2026-09-08 | **雙軌部署說明**：阿里雲＝主要運作；Railway 暫時並行；開發須先顧及阿里雲 |
| 2026-09-08 | **廣告輸出改版**：全賽日模型／AI 各一張（固定 `model.jpg`/`ai.jpg` 覆蓋）；單張 ≤800KB；緊湊排版 |
| 2026-09-08 | **廣告輸出修復**：內嵌 CJK 字型；輸出改 JPEG＋單場預覽／ZIP，避免一次載入多張大圖導致 502 |
| 2026-09-08 | **廣告輸出模組**：快照後自動生成模型／AI 海報 PNG + 文案（`ad_poster.py`、`views/ad_output.py`）；模版 `assets/ad_templates/` |
| 2026-09-06 | **場內份額制**：因子／模型／AI 以分差比率瓜分 100%（非負）；推介動態最多 5 匹、AI 低信心可略過 |
| 2026-09-05 | **預計步速上賽日／推論**：每場顯示偏慢／中性／偏快；`factor_scores` 落庫 `early_speed_z`／跑法 |
| 2026-09-05 | **步速劇本修正**：形勢改依爭搶馬數（早段 Z≥門檻），不再用 heat≥2.5（幾乎全判超快） |
| 2026-09-05 | **SPEED Par 小切片**：`extract_venue`+`class_num` 分桶；`SPEED_PAR_PERCENTILE`／`MIN_N`；粗桶回退 |
| 2026-09-05 | **階段完成／暫停自動化**：雙軌推介＋AI 獨立軌道就緒；待賽日結算跑通再開 Cron（§5.3／§6） |
| 2026-09-05 | **AI 推介 UI**：賽日只顯示指數%（如 `72%`）；算式留詳情 |
| 2026-09-05 | **AI 獨立軌道**：`form_ai_picks` 推介；快照鎖 ai_*；命中率訊號「AI評價×信心」；賽日並排模型／AI |
| 2026-09-05 | **手冊 §4.1**：GitHub UI 同事會優化版面；開發邏輯時勿用本地舊 UI 覆蓋 `main` |
| 2026-09-05 | **賽前預測 API**：`prediction_api` + Kelly／即時賠率；`PREDICTION_API_KEY`；獨立 `start-api.sh` |
| 2026-09-08 | **覆蓋度持份者**：`score_compose`；miss 降權；干擾獨立 I；provisional／revision 快照；見 `COVERAGE_STAKEHOLDER_HANDBOOK.md` |
| 2026-09-05 | **登入分權**：`auth_whitelist` + `AUTH_BOOTSTRAP_ADMIN`；user 僅賽日速覽；admin 全管理頁；`views/` + `st.navigation` |
| 2026-09-05 | **UI**：登入頁／管理外殼／賽日速覽簡潔綠系；側欄中文由 Page title 提供 |
| 2026-09-05 | **勝率**：場內 z → softmax（`SOFTMAX_WITHIN_RACE_Z`，T 預設 1.5） |
| 2026-09-05 | **作戰室**：fixtures + meeting_pipeline；§5.3 賽後自動化開發切片 |
| 2026-09-05 | Form Guide CMS + Form AI；預測快照結算；級賽 class 解析 |

---

*最後更新：2026-09-08 — 雙軌部署（阿里雲為主）／全賽日廣告海報已落地。*
