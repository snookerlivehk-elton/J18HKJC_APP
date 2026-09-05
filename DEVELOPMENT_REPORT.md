# J18 賽馬量化預測系統 — AI 開發交接手冊

> **給下一位 AI / 開發者**：先讀本文件，再讀 [`FACTOR_MODEL_DESIGN.md`](FACTOR_MODEL_DESIGN.md)（數學白皮書）。  
> 實作以**查表推論**為主：歷史 → `factor_scores` → 排位條件匹配 → 加權總分。  
> 生產環境：**GitHub `snookerlivehk-elton/J18HKJC_APP` → Railway Streamlit**；本機 `.env` 連同一套 Postgres（勿提交密碼）。

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
| HKJC 排位 | `upcoming_races`, `upcoming_runners` | `racecard_crawler`（注意欄位偏移：檔位/練馬師） |
| HKJC Speed Guide | `upcoming_speedguide` | CMS JSON：`consvc.hkjc.com/.../SpeedPro/current/sg_*`；賽前約 1 日中午上架 |
| 因子落庫 | `factor_scores` | **推論只讀這張表**（查表，不每次現算） |

- 雲端：`USE_SQLITE=false` + `DATABASE_URL` / `DATABASE_URL_SYNC`  
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
| SPEED | GLOBAL | 馬名 | Peak/EMA；FSR 校正；可選 NLP 時間補償 |

推論加權見 `config.py`：`WEIGHT_*`（含 `WEIGHT_RECENT_FORM`、`WEIGHT_PACE`、`WEIGHT_SPEED_FIGURE`、Speed Guide 三項）。

### 1.4 關鍵檔案地圖

```
bucket_utils.py          # 場地/跑道/距離帶、名稱正規化、synergy/horse_jockey 名
config.py                # 全部超參數與 WEIGHT_*
factor_calculator.py     # 歷史抓取、各因子、NLP 補償、save/load factor_scores
inference_engine.py      # 排位查表預測
nlp_processor.py         # OpenAI/OpenRouter JSON 受阻解析（只讀環境變數 Key）
nlp_batch_job.py         # 本機/CI 大批次 NLP（可略過「無特別報告」）
ui_app.py                # 主頁：載歷史、重算全部因子
ui_utils.py              # 排位選擇、匹配面板、賽日 NLP 選項、NLP 新鮮度顯示
pages/0_Data_Control…   # 排位/整備度
pages/1–3_*              # 騎／練／騎練（粗桶）
pages/4_Draw…            # 檔位（細桶）
pages/5_Horse_Jockey…    # 人馬雙軌
pages/6_Recent_Form…     # 近績 + 賽日 NLP 解析
pages/7_Pace_Sectional…  # 步速／跑法
pages/8_Speed_Figure…    # 速度指數 / FSR
pages/9_HKJC_Speed…      # 官方 Speed Guide
pages/10_Inference…      # 融合總分 + 分場次表 + 因子雷達圖
pages/11_RaceDay_Mobile  # 手機優先賽日速覽（用戶向：場次按鈕＋勝率卡片＋雷達）
pages/13_Form_AI…         # Form Guide CMS + 賽前 AI 評語／獨立分
formguide_crawler.py     # CMS fg_index / fg_race_N → upcoming_formguide
form_ai_analyst.py       # 統計+近績文字 → upcoming_form_ai
racecard_crawler.py      # 排位爬蟲（欄位索引易壞）
speedguide_crawler.py    # Speed Guide：CMS JSON → upcoming_speedguide
etl_pipeline.py / batch_crawler.py
schema.sql
```

#### Speed Guide 實作要點

- **URL（給人看）**：https://racing.hkjc.com/zh-hk/local/info/speedpro/speedguide?raceno=1  
- **真正資料**：`https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/sg_index` 與 `sg_race_{N}`（UTF-8 BOM JSON）  
- 欄位映射：`fitnessrating`→`form_rating`；`speedproenergy`→`speed_energy`；`speedproenergydifference`→`speed_energy_delta`  
- 推論：Fitness：`0`=倒轉拇指→`-1.5`，`1/2/3`=向上拇指→`0/1/2`；能量**同場 Z**；差值× `WEIGHT_SG_DELTA`  
- CLI：`python speedguide_crawler.py`（可選 `--date` / `--course` 核對、`--races 1,2`）  

Streamlit 多頁：`ui_app.py` 為入口；`pages/` 自動掛載。

---

## 2. 運維 Runbook（改碼後必做）

### 2.1 部署後

1. Railway 部署完成  
2. 主頁 **「重算並寫入 factor_scores」**（Bucket 規則或因子公式變更後**必須**重算，否則匹配率歸零）  
3. 若改了排位爬蟲欄位：資料控制中心 **重新抓排位**  
4. 近績要吃 NLP：賽日模式解析 → 再算近績／主頁重算  

### 2.2 NLP（賽後報告）

- Key：**只**用環境變數 `OPENAI_API_KEY`（可選 `OPENAI_MODEL`、`OPENAI_BASE_URL`）。**禁止**在 UI 輸入 Key。  
- 結果寫入 `text_reports.nlp_result`（JSON），**可重用**；只處理 `nlp_result IS NULL`。  
- UI：**整個賽日解析**（該日該場地所有排位馬）+ 自動略過空白／「無特別報告」。  
- 換頁會中斷 Streamlit 同步迴圈；長跑用 `python nlp_batch_job.py --limit 200`。  
- **解析 ≠ 已入近績/速度**：必須再跑對應計算（或主頁重算）。近績頁有「NLP vs 近績分數時間」警示。  

兩種 NLP 用途（勿混）：

| 用途 | 行為 |
|------|------|
| 近績 HORSE | 受阻 → 調整該場 **raw_score（名次向）** |
| 速度 SPEED | 受阻 → 該場 **Speed Figure 小幅上修（時間向）** |

### 2.3 環境變數（Railway）

```
USE_SQLITE=false
DATABASE_URL=...
DATABASE_URL_SYNC=...   # SQLAlchemy 用的同步 URL
OPENAI_API_KEY=...      # 可選但 NLP 需要
OPENAI_MODEL=gpt-4o-mini
# OpenRouter 時設 OPENAI_BASE_URL + 對應 model 名
```

本地 `.env` 同上；**勿 commit**。密碼若曾貼在聊天室請輪替。

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

---

## 4. 開發慣例（給 AI）

- **改 Bucket / 公式後**：更新計算 + 匹配 UI + `inference_engine` + 手冊；提醒使用者重算 `factor_scores`。  
- **因子頁模式**：可從 DB 載歷史計算（`ui_utils.get_history_df_for_compute`），不要只綁主頁 session。  
- **落庫**：`save_factor_scores` 只保留標準欄位；診斷欄（跑法、Peak、NLP場次）可留 session／回傳 DataFrame。  
- **名稱**：一律 `normalize_person_name`（去括號磅數）；騎練組合用 `synergy_name`。  
- **提交**：使用者要求才 commit/push；`main` 為 Railway 追蹤分支。  
- **秘錀**：不寫進 repo、不回顯完整 Key。  

建議實作順序（新因子）：

1. `factor_calculator` 純函式 + 可落庫  
2. 專頁匹配／診斷  
3. `inference_engine` + `WEIGHT_*`  
4. `run_all_factors` / 主頁  
5. 更新本手冊  

---

## 5. 全自動排程藍圖

### 已落地（手動作戰室）

- `fixture_crawler.py` → `fixtures`（HKJC Fixture.aspx 整季）
- `meeting_pipeline.py`：`meeting_readiness` + 各 stage 狀態 + 手動動作
- UI：`pages/14_Meeting_Ops.py`（賽日作戰室）

階段：FIXTURE → RACECARD → SPEEDGUIDE → FORMGUIDE → FACTORS → NLP → FORM_AI → SNAPSHOT → RESULTS → SETTLED

### 尚未落地（Cron tick）

目標仍是短輪詢 Cron，無需人工：

| 時機 | 動作 |
|------|------|
| 季前／每周 | `fixture_crawler` → `fixtures` |
| 賽前 ~2 日 | `racecard_crawler` |
| 賽前 ~24–36h | `speedguide_crawler` / `formguide_crawler`（未上架則 waiting 重試） |
| 排位齊後 | factors／Form AI → `snapshot_meeting` |
| 賽後隔日 | `batch_crawler` → `settle_pending` |

---

## 6. 待辦優先序（Roadmap）

### P0 — 穩定生產

- [ ] 確認 Railway 每次 deploy 後有無需要的「重算因子」SOP（文件化給使用者）  
- [ ] 排位爬蟲回歸測試（欄位索引）  
- [ ] 歷史爬蟲監控（J18 API 偶發封鎖）  

### P1 — 模型品質

- [ ] 步速形勢加權併入推論總分（現多在 Pace 頁）  
- [ ] SPEED：固定末 400m、Par Time 分位數  
- [ ] 降班三條件再校準；NLP 過濾假性腳軟／假性無追勢（白皮書 Phase 5）  
- [ ] Peak vs EMA 雙特徵進總分／ML  

### P2 — 自動化與產品

- [ ] Cron tick 接 `meeting_pipeline`（依 readiness 重試，非無限爬）  
- [ ] formguide／Form AI 訊號進推論權重（現多為旁路顯示）  
- [ ] 實驗追蹤（匯出 `ModelConfig.get_params_dict()`）  

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
| B 雷達半徑 | 同場每軸 min-max → [0,1] | **只顯示**；不是勝率 |
| C 模型勝率 | 場內 z(總分) → `softmax(/T)`，加總≈1 | 外傳凱利；`export_kelly_payload` |

- **不要**把總分硬加常數變正數再當機率。  
- **不要**把各因子 Z 改成同場瓜分 100%（破壞跨場比較與校正）。  
- `SOFTMAX_WITHIN_RACE_Z`（預設 True）+ `SOFTMAX_TEMPERATURE`（預設 1.5）：壓低極端勝率。  
- Kelly：`p=model_win_prob`，小數賠率 `o`，`b=o-1`，`q=1-p`，`f*=(b p - q)/b`。  

---

*最後更新：2026-09-05 — 對齊距離帶粗桶、賽日 NLP、PACE/SPEED 落庫與推論、raw_json dict 修復。*
