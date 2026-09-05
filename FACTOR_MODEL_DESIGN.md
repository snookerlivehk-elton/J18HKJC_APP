# J18 Quant Model - 因子模型設計白皮書 (Factor Model Design)

> **實作／運維交接**：請先讀 [`DEVELOPMENT_REPORT.md`](DEVELOPMENT_REPORT.md)。  
> 本檔定義數學與產品原則；交接手冊記載現行 Bucket 政策（騎練／近績＝距離帶粗桶、檔位＝細桶等）、`factor_scores` 類型與部署後重算流程。

## 1. 核心理念
本模型旨在將歷史賽果轉換為可量化的「因子分數 (Factor Scores)」，以供未來排位表進行同場比較。模型設計嚴格遵循「分桶 (Bucketing)」、「時間衰減 (Time Decay)」、「貝葉斯平滑 (Bayesian Smoothing)」與「因子獨立性」四大原則。

## 2. 系統最高指導原則：特徵顆粒度原則 (Feature Granularity Principle)
隨著系統未來將加入「檔位 (Draw)」、「近績 (Recent Form)」、「分段時間 (Sectional Times)」等不同類別的因素，本模型嚴格規定：**所有因子必須保持為「獨立分項 (Independent Features)」，絕對不可在特徵工程階段將其硬性綜合成單一類別分數。**

**原因 (ML 最佳化考量)：**
1. **保留非線性特徵互動 (Feature Interactions)**：未來的樹狀模型 (如 XGBoost) 能夠學習到「高騎師分數能克服差檔位，但高練馬師分數無法」的隱藏邏輯。若將騎練綜合成單一分數，AI 將丟失此關鍵決策維度。
2. **避免資訊遺失 (Information Loss)**：不同班次或路程中，各因子的重要性不同 (例如低班賽練馬師更重要，一級賽騎師更重要)。保留獨立因子能讓 ML 自動學習動態權重。
3. **雙軌制輸出**：底層資料庫 (`factor_scores`) 永遠儲存獨立的顆粒化特徵供 AI 訓練；僅在最終給人類觀看的 UI/報表端，才依據 `config.py` 的權重將其綜合成「人馬配搭分」、「近績分」以利快速閱讀。

## 3. 三大獨立人為因子 (Independent Connection Factors)
系統針對人馬配搭計算三個完全獨立的分數，供未來機器學習模型挖掘互動關係：
1. **Jockey Factor (J_Score)**：騎師個人在特定條件下的能力。
2. **Trainer Factor (T_Score)**：練馬師在特定條件下的出擊與部署能力。
3. **Synergy Factor (JT_Score)**：特定騎練組合的化學反應與搏殺信號。

## 3. 分桶設計 (Bucketing Strategy)
為了捕捉細微的場地偏差與專長，基礎分桶維度如下：
- `Venue` (地點): ST (沙田) / HV (跑馬地)
- `Track` (賽道): A / B / C / C+3 等
- `Distance` (距離): 1000, 1200, 1650, 1800 等
> **範例 Bucket**: `HV_C_1650`

## 4. 評分數學邏輯與機器學習超參數 (Hyperparameters for Future ML)
為了替未來的機器學習（如 Grid Search 或 Optuna 參數最佳化）鋪路，所有牽涉主觀定義的參數皆已抽離至 `config.py` 中，確保演算法邏輯與參數配置完全隔離。

### 4.1 基礎分數計算 (Base Score)
不單純看勝率，將前四名 (Top 4) 納入考量以穩定變異數。
- **ML 可調參數**: 
  - `WIN_WEIGHT` (預設 1.0)
  - `PLACE_WEIGHT` (預設 0.3 - 代表第 2,3,4 名的權重。ML 可能會發現將其設為 0.25 預測力更高)

### 4.2 時間衰減 (Time Decay)
採用階梯式折扣 (Step Decay)，距離預測日越近的賽事權重越高。由於騎師狀態波動快於練馬師，兩者參數應獨立。
- **ML 可調參數**:
  - `TIME_WINDOW_DAYS`: 每個衰減階梯的天數 (預設 90 天)
  - `JOCKEY_DECAY`: [1.0, 0.7, 0.4, 0.2, 0.0] (騎師狀態衰減快)
  - `TRAINER_DECAY`: [1.0, 0.85, 0.7, 0.5, 0.2] (馬房實力衰減慢)
  - `SYNERGY_DECAY`: [1.0, 1.0, 0.6, 0.6, 0.0] 

### 4.3 貝葉斯平滑處理稀疏數據 (Bayesian Smoothing)
解決「出賽 1 次贏 1 次 = 勝率 100%」的統計陷阱。
- **公式**: 
  `Adjusted_Score = (Σ(真實分數 * 時間權重) + C * 總體平均分數) / (Σ(真實出賽 * 時間權重) + C)`
- **ML 可調參數 (`C` = 虛擬出賽次數限制 / Cap)**:
  - `JOCKEY_SMOOTH_C` (預設 20)
  - `TRAINER_SMOOTH_C` (預設 20)
  - `SYNERGY_SMOOTH_C` (預設 10，因為組合數據天生較少)

## 5. 實作架構建議 (Implementation Plan)
1. **資料來源**: 讀取 PostgreSQL 內的 `runners` 與 `races` 表。
2. **計算引擎**: 使用 **Python (Pandas)** 進行向量化運算。因為涉及複雜的時間差計算與分組 (Groupby)，Pandas 的效能與靈活度遠勝純 SQL。
3. **產出結果**: 將計算完的 Z-Score (標準化分數) 寫入新表 `factor_scores`。
4. **API 串接**: 當未來排位爬蟲抓到明日名單時，直接從 `factor_scores` 撈取分數進行同場排名。

## Phase 2: 檔位與場地因子 (Draw & Track Bias Factor) [規劃中]

### 1. 核心理念
檔位的優劣是物理與幾何問題（如首彎距離、外疊代價），高度依賴於「馬場、賽道、距離」的組合。
**絕對不可將「班次 (Class)」納入分桶條件**，因為無論是第一班或第五班，跑同一個外檔被逼出外疊的物理劣勢是一模一樣的。將班次納入只會無謂稀釋樣本數，導致過度擬合 (Overfitting)。

### 2. 特徵顆粒度與分桶設計 (Bucketing)
為了在「捕捉賽道特性」與「保持統計樣本數」之間取得平衡，我們採用雙層架構：

#### A. 基礎檔位偏差 (Base Draw Bias)
- **分桶鍵 (Bucket Key)**：`course + track + distance_m` (例如：`HV_C_1200`)
- **檔位群組化 (Draw Grouping)**：將 1-14 檔壓縮為 4 個特徵區間，以利機器學習與統計穩定性：
  - `Inner` (內檔): 1-3 檔
  - `Mid-Inner` (中內): 4-7 檔
  - `Mid-Outer` (中外): 8-10 檔
  - `Outer` (外檔): 11-14 檔

#### B. 場地動態修正係數 (Dynamic Ground Multiplier)
「場地狀況 (好地/黏地)」對檔位影響極大，但不適合直接加入分桶（會導致變化地樣本過少）。
我們將其設計為全局乘數：
- **好地/快地 (Good/Firm)**：`Multiplier = 1.0` (完全採納 Base Draw Score)
- **變化地 (Yielding/Soft)**：`Multiplier = -0.5` (內欄通常變爛，削弱內檔加分，甚至反轉為外欄優勢)

### 3. 超參數預留 (Hyperparameters for ML)
- `DRAW_GROUP_BOUNDARIES` = `[3, 7, 10]` (定義內、中內、中外的檔位切分點)
- `YIELDING_TRACK_MULTIPLIER` = `-0.5` (變化地的內檔削弱係數)

---

## Phase 3: 人馬合作與換人效應因子 (Horse-Jockey Synergy & Switch Factor)

### 1. 核心理念
「人馬合作 (Horse-Jockey)」與「騎練合作」本質不同，因為單一馬匹與特定騎師的合作次數極少。
因此，我們不能再加入賽道或距離進行分桶，否則樣本會被稀釋至零。我們只關注**「韁繩相性」**。
此外，為了解決「初次合作沒有歷史數據，但實際上是強勢換人」的問題，我們必須引入**雙軌指標**。

### 2. 特徵與分桶設計 (Bucketing & Metrics)

#### A. 人馬合作歷史得分 (Historical Partnership Score)
- **分桶鍵 (Bucket Key)**：`horse_id + jockey_name` (全域統計，不分賽道/距離)
- **計算邏輯**：計算該組合的歷史勝出/入圍加權總分。
- **平滑處理**：因為樣本極少 (常為 1~3 次)，必須套用貝葉斯平滑 (Bayesian Smoothing) 拉回全域平均，避免「1戰1勝 = 100%」的極端偏誤。

#### B. 騎師升級指數 (Jockey Upgrade Delta)
專門捕捉「弱將換強手」的出擊信號。
- **計算邏輯**：`今仗騎師的 Z-Score` 減去 `該駒近 N 仗前任騎師的平均 Z-Score`。
- **應用場景**：如果一匹馬前三仗配搭弱勢騎師 (平均 Z-Score -1.0)，今仗突換潘頓 (Z-Score +2.0)，其 Upgrade Delta 高達 +3.0。即使 A 指標 (合作歷史) 為 0，B 指標也能強烈提示這是一次**潛在的突破出擊**。

### 3. 超參數預留 (Hyperparameters for ML)
- `HJ_SMOOTH_C` = `3` (人馬合作的貝葉斯平滑虛擬出賽次數，需比騎練合作小)
- `HJ_TIME_WINDOW_DAYS` = `180` (人馬合作的時間衰減窗格，通常拉長至半年一桶)
- `JOCKEY_LOOKBACK_RACES` = `3` (計算換人效應時，回溯前任騎師的場數)

---

## Phase 5: 步速形勢與走位因子 (Pace Scenario & Positional Delta)

### 1. 核心理念
馬匹的真實能力往往隱藏在「分段走位」中。純粹的完成時間容易受到賽事整體步速的干擾。我們透過計算馬匹的 **「走位變動值 (Positional Delta)」**，將馬匹量化歸類為不同的跑法標籤，進而在排位預測時，推演出同場的**「步速形勢化學反應」**。

### 2. 走位變動 (Positional Delta) 演算法
利用 API 提供的 `sections` 資料（如 `8-8-3`），定義 `Delta = 中段名次 - 終點名次`。
- **後追型 (Closer)**：如走位 `12-10-2`，`Delta = +8`。反映極強的末段爆發力與慣性。
- **前置耐力型 (Sustained Speed)**：如走位 `2-1-1`，`Delta = 0` 且中段名次居前。反映出閘快且持續力強，不易崩潰。
- **前領力弱型 (Fader)**：如走位 `1-2-9`，`Delta = -7`。反映早段耗力過多或耐力不足。

### 3. 預計步速推算模型 (Pace Projection / Speed Map)
要預測一場未發生賽事的步速，不能憑空猜測，必須依賴馬匹歷史的「首段分段時間 (First Sectional Time)」：
- **早段速度指數 (Early Speed Figure)**：將馬匹近仗的首段時間標準化，分數越高代表起步越快、越具前領意圖。
- **步速熱度指數 (Pace Heat Index)**：當排位公佈時，取同場 12 匹馬中 `Early Speed Figure` **最高的前 3 名**進行加總。一場賽事的步速是由最想搶放的馬匹決定的。

### 4. 同場形勢預測與加權 (Pace Match Bonus)
根據算出的 `Pace Heat Index`，系統將自動推演賽事劇本，並分配形勢加權：
- **超快步速 (Suicidal Pace)**：熱度極高（多匹快馬互燒）。系統將自動給予「後追型 (Closer)」馬匹高額形勢加分。
- **極慢步速 (Lone Speed)**：熱度極低（全場僅 1 匹快馬）。系統將大幅加分給該唯一的前領馬，並懲罰後追馬（因步速慢難以追趕）。

### 5. 結合 NLP 補償過濾假性數據 (NLP Contextual Override)
步速數據必須與 Phase 4 的 NLP 賽後報告結合，以避免數字陷阱：
- **過濾「假性腳軟」**：若 Delta 呈現嚴重負值 (如 `2-2-10`)，但 NLP 偵測到 `[外疊無遮擋 (3-wide)]`，則抹除其耐力扣分。
- **過濾「假性無追勢」**：若後追馬 Delta 呈現平庸 (如 `10-10-9`)，但 NLP 偵測到 `[直路受困 (Blocked)]`，則強制保留其原有的後追高分評級。

### 6. 超參數預留 (Hyperparameters for ML)
- `EARLY_SPEED_TOP_N` = `3` (計算步速熱度時，取前幾名的快馬來加總)
- `PACE_SCENARIO_BONUS` = `1.5` (當步速形勢極度有利時，給予的 Z-Score 加權乘數)
- `WIDE_TRIP_FORGIVENESS` = `0.8` (當發生外疊時，對負面 Delta 的赦免比例)

## Phase 6: 速度指數與分段真實時間因子 (Speed Figure & FSR)

### 1. 核心理念
直接比較「原始完成時間」或「原始分段時間」是量化分析中最危險的陷阱，因為時間會受到「距離、場地快慢、賽事步速戰略」的嚴重扭曲。
必須將原始時間轉換為剝離環境因素的 **「速度指數 (Speed Figure)」**，並利用 **「末段變速比率 (FSR)」** 來評估末段時間的真實含金量。

### 2. 完成時間的標準化 (Speed Figure Calculation)
完成時間必須經過兩層校準，方能產生絕對能力分數：
- **標準時間差 (Par Time Delta)**：
  先以分桶 `(venue ST/HV + track + distance_m + class_num)` 的完成時間**分位數**（預設中位數；樣本不足回退粗桶）作為 `Par Time`。`time_delta = Par − 實際時間`（正＝較快）。
- **當日場地偏差修正 (Daily Track Variant)**：
  同一天的場地可能特別快（如壓實的草地）或特別慢。按 `racing_date + venue + track` 對 time_delta 取平均偏差。
- **最終速度指數**：`Speed Figure = time_delta − Daily Track Variant`。將其轉化為 Z-Score。

### 3. 分段時間與戰略剝離 (Finishing Speed Ratio, FSR)
為了判斷一匹馬的末段時間 (L400m) 是否真的具備爆發力，還是只因為早段步速太慢而得益，引入 FSR 進行評估：
- **公式**：`FSR = (全場平均速度 / 最後 400 米速度) * 100%`
- **量化邏輯**：
  - `FSR > 105%` (慢步速賽事)：此時跑出極快末段時間是理所當然，系統將**調降**該末段時間的得分權重。
  - `FSR < 95%` (快步速消耗戰)：此時若有馬匹的末段時間仍能維持高水準，代表其真實能力極強，系統將給予**極大加分補償**。

### 4. 歷史峰值 vs 近況趨勢 (Peak vs. Current EMA)
時間因子的彙整不採用單一平均值，而是提取兩個特徵供機器學習使用：
- **歷史峰值 (Peak Speed Rating)**：過去 365 天內創下的最高 Speed Figure。代表馬匹的**能力天花板 (Ceiling)**。
- **近況趨勢 (Current Form EMA)**：近 3 仗 Speed Figure 的指數移動平均 (EMA)。代表馬匹的**當下狀態 (Fitness)**。
- 當 `Current EMA` 顯著回升並逼近 `Peak Rating` 時，即構成強烈的出擊信號。

### 5. 超參數預留 (Hyperparameters for ML)
- `FSR_PENALTY_THRESHOLD` = `105.0` (步速過慢，開始懲罰末段時間的閥值)
- `FSR_BONUS_THRESHOLD` = `95.0` (步速極快，開始獎勵末段時間的閥值)
- `TIME_EMA_ALPHA` = `0.5` (近況時間趨勢的指數平滑衰減率)

## Phase 4: 近績與 NLP 賽後報告因子 (Recent Form & NLP Factor)

### 1. 核心理念
傳統的近績 (如近六仗 9-8-10-7-9) 容易產生極大盲點：無法區分「真實狀態下滑」與「戰術性減分降班」，也無法反映賽事中遭遇的「意外阻礙」。
因此，近績因子必須結合 **「班次/評分變動 (Class/Rating Delta)」** 與 **「NLP 賽後報告 (Text Reports)」** 進行雙重修正。

### 2. 班次與評分修正 (Class-Adjusted Form)
為了精準區分「蓄意減分降班」與「真實狀態下滑」，模型將採用以下 3 項條件進行交叉驗證 (Cross-Validation)。**必須同時滿足**才會觸發降班信號：

- **條件 1：班次實質跨越 (The Rating Threshold)**
  今仗 `runnerRating` 跌破班次邊界（如從 61 分跌至 59 分），且今仗出賽班次數字大於前三仗（如 Class 3 -> Class 4）。
- **條件 2：賠率與名次背離 (Odds-Rank Divergence)**
  前三仗平均名次 > 7（看似劣績），但前三仗平均獨贏賠率 (或 `win_probability`) 卻小於 15.0 倍。這代表幕後資金與市場並未放棄，只是受制於高分重磅。
- **條件 3：隱藏的末段實力 (Hidden Sectional Pace)**
  在近三仗的敗仗中，至少有一場的**最後 400 米分段時間 (L400m)** 名列全場前 30%。代表馬匹體能無礙，僅是戰術性留後或未完全施為。

**近績權重洗牌**：
若觸發上述 `Class_Drop_Signal`，系統將自動**抹除**其近三仗敗績的懲罰分數，並給予 `CLASS_DROP_BONUS` (降班優勢加分)。若未滿足，則視為真實狀態下滑，予以嚴格扣分。

### 3. NLP 賽後報告補償系統 (AI Excuse & Bonus System)
**嚴禁使用傳統關鍵字比對**（易受否定句如「未有受困」誤導）。必須使用 LLM (大語言模型) 進行語義理解，並強制輸出結構化 JSON 特徵。
針對 `running_comment_text` 與 `incident_report_text`，按賽事三階段進行特徵抽取與分數補償：

#### A. 起步階段 (Start)
- **抽取特徵**：漏閘 (Missed Break)、起步碰撞 (Bumped)。
- **量化處理**：標記為「戰術劣勢」。若在漏閘情況下仍能跑入前列，給予額外的「能力補償分 (Ability Bonus)」。

#### B. 中段 (Middle)
- **抽取特徵**：外疊無遮擋 (Wide no cover)、搶口/難以操控 (Pulling/Keen)。
- **量化處理**：此階段意外最耗費馬匹體力。若發生，系統自動將其真實名次**「向上修正」**（例如：真實第 8 名 -> 修正後視為第 4 名的實力），給予高額「體力消耗補償分」。

#### C. 末段/直路 (Late/Finish)
- **抽取特徵**：受困/未能望空 (Blocked for run)、未施為 (Not ridden out)、追勢凌厲 (Strong finish)。
- **量化處理**：末段受困代表「馬有餘力但無法發揮」，是尋找高賠率冷門 (Value Bet) 的最大金礦。觸發此特徵的馬匹，其近績分數將獲得**最高級別的補償加權**。

### 4. 超參數預留 (Hyperparameters for ML)
- `CLASS_DROP_BONUS` = `1.5` (降班戰術加分)
- `EXCUSE_MULTIPLIER_MID` = `1.3` (中段外疊體力消耗的名次補償乘數)
- `EXCUSE_MULTIPLIER_LATE` = `1.8` (直路受困的極大補償乘數)
