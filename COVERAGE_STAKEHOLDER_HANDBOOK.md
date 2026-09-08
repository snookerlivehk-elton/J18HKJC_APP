# 覆蓋度持份者模型 — 一次性開發手冊

> **狀態**：**已實作**（本 branch：`COVERAGE_MODE=on`、`INTERFERENCE_MODE=stakeholder`）。  
> **前置閱讀**：[`DEVELOPMENT_REPORT.md`](DEVELOPMENT_REPORT.md)（運維／賽日 SOP）、[`FACTOR_MODEL_DESIGN.md`](FACTOR_MODEL_DESIGN.md)（數學白皮書）。  
> **問題陳述**：HKJC／賽後「沿路走勢評述」上架時間不定；現行 NLP 受阻補償烤進近績／速度 raw，缺資料時整條結算易停滯。同時推論 miss 以 `z=0` 進場卻仍吃滿 `WEIGHT_*`，覆蓋率資訊（`命中 n/7`）未進分數。  
> **目標**：可降級推論、不阻塞快照；每個資料源＝value＋coverage 持份者；干擾獨立成干擾值 \(I\)；缺資料縮有效權重、可補丁重算。

---

## 0. 設計契約（Phase 0 凍結結果）

### 0.1 一句話

每個持份者同時輸出 **信號值** 與 **覆蓋／信心**；總分只加總「有效貢獻」；官方資料延遲時出 **provisional** 預測，資料到位後追加 **revision**，不阻塞賽日管線。

### 0.2 三種「缺」的語意（實作時必須分開）

| 代碼 | 語意 | value | coverage | 範例 |
|------|------|-------|----------|------|
| **DELAY** | 本應有資料但尚未到達 | 不進（或 \(I=0\)） | **下降** | 走勢評述未上架、NLP 未解析、SG 未上架 |
| **ABSENT_TRUE** | 資料已到，判定「無事件」 | \(I=0\) 或中性 | **高** | 有評述且 `has_excuse=false` |
| **MISS** | 查表無實體／無歷史 | 該項不貢獻 | **下降** | 新馬無 HORSE Z、冷門騎練無桶內分數 |

> **嚴禁**把 ABSENT_TRUE 當成 DELAY 懲罰。無受阻是真資訊。

### 0.3 Stakeholder 合約

每個持份者（推論時）必須能組成：

```text
Stakeholder {
  key:          str          # 如 "JOCKEY" | "HORSE" | "INTERFERENCE_FORM" | "SG"
  value:        float        # 已標準化信號（多為 Z；SG／I 依各自定義）
  present:      bool         # 是否有觀測（MISS=false；ABSENT_TRUE 對干擾仍 present=true）
  coverage:     float        # [0, 1]
  base_weight:  float        # 來自 ModelConfig.WEIGHT_*
}
effective = value * base_weight * coverage   # present=false → 該項 effective=0，且 coverage 反映懲罰
```

馬級合成：

\[
S_h = \sum_k w_k \cdot c_{h,k} \cdot z_{h,k}
+ w_{I_f}\cdot c_{h,I_f}\cdot I_{h,f}
+ w_{I_s}\cdot c_{h,I_s}\cdot I_{h,s}
+ w_{SG}\cdot c_{h,SG}\cdot SG_h
\]

馬級信心（供 UI／推介閘門，不必然再乘進 \(S_h\)）：

\[
C_h = \frac{\sum_k w_k\, c_{h,k}}{\sum_k w_k}
\]

### 0.4 已凍結決策

| 決策 | 選擇 | 理由 |
|------|------|------|
| 缺資料時權重重正規化 | **不做** | 缺＝場內競爭變弱，語意才是低信心；重正規化會膨脹其餘因子 |
| 干擾與基礎近績 | **分離** | 符合白皮書特徵顆粒度；可缺 I 而不重算整條 raw |
| severity vs coverage | **分開** | NLP `severity`＝受阻多嚴重；coverage＝資料多可靠 |
| 部分覆蓋 | **連續 \(c\in[0,1]\)** | 近窗 3/5 場有 NLP → 約 0.6，非二元 |
| 快照策略 | **provisional + revision 追加** | 不覆寫已用於下注／結算的原 batch 列 |
| AI 軌 | **保持雙軌** | Form AI 已有 `ai_score×confidence`；不混入模型 \(S_h\)，但 UI／閘門語意對齊 |
| 舊模式相容 | **開關過渡** | `INTERFERENCE_MODE=legacy\|stakeholder`；`COVERAGE_MODE=off\|shadow\|on` |

### 0.5 建議 Config 鍵（實作時寫入 `config.py`）

```python
# 合成模式
COVERAGE_MODE = "on"           # off | shadow | on（已預設 on）
INTERFERENCE_MODE = "stakeholder"  # legacy | stakeholder（已預設 stakeholder）

# 覆蓋曲線（MISS / DELAY）
COVERAGE_MISS_DEFAULT = 0.0    # 查表完全 miss 時該因子 coverage
COVERAGE_PARTIAL_FLOOR = 0.15  # 有部分樣本時下限（可調）
NLP_COVERAGE_LOOKBACK_RACES = 5
NLP_COVERAGE_MIN_PARSED_RATIO = 0.0  # 解析比例 → c_nlp 的映射可再加溫度

# 干擾持份者權重（stakeholder 模式）
WEIGHT_INTERFERENCE_FORM = 0.4   # 近績名次向 I
WEIGHT_INTERFERENCE_SPEED = 0.3  # 速度時間向 I

# 推介／風控（可選）
PICK_MIN_MODEL_COVERAGE = 0.35   # C_h 低於此可不推或縮 Kelly
SNAPSHOT_ALLOW_PROVISIONAL = True
```

### 0.6 資料形狀（建議）

**推論列（內部，寫入快照前）**

```json
{
  "stakeholders": {
    "JOCKEY": {"value": 0.8, "present": true, "coverage": 1.0, "effective": 0.8},
    "HORSE":  {"value": 0.5, "present": true, "coverage": 0.6, "effective": 0.45},
    "INTERFERENCE_FORM": {"value": 0.0, "present": false, "coverage": 0.4, "effective": 0.0}
  },
  "total_score": 3.21,
  "model_coverage": 0.72,
  "provisional": true,
  "provisional_reasons": ["nlp_pending", "sg_missing"]
}
```

**DB（Phase 3 擴充；Phase 1 可先 JSON 欄或 meta）**

| 欄位／表 | 說明 |
|----------|------|
| `prediction_snapshots.model_coverage` | \(C_h\) |
| `prediction_snapshots.coverage_json` | 各持份者 coverage／present |
| `prediction_snapshots.provisional` | bool |
| `prediction_snapshot_batches.revision_of` | 可空；指向被補丁的 batch_id |
| `prediction_snapshot_batches.snapshot_kind` | `primary` \| `revision` |
| （可選）`factor_scores` 或旁表存馬級 `nlp_coverage`、聚合 \(I\) | 避免每次推論重掃 text_reports |

### 0.7 與現況對照（改碼錨點）

| 現況 | 目標 |
|------|------|
| `_lookup_z` → `(0.0, False)` 仍 `× WEIGHT` | miss → effective=0，coverage↓ |
| `apply_nlp_excuse_boost` 改 `raw_score` | stakeholder 模式：基礎 HORSE 不改；另算 \(I_f\) |
| SPEED `nlp_time_boost` 併入 SF | 另算 \(I_s\) |
| `run_factors(..., apply_nlp=False)` | 允許無 NLP 出 provisional；NLP 後 revision |
| `命中 n/7` 僅展示 | 進合成／快照 |
| Form AI `confidence` | 模型軌對齊語意，軌仍分離 |
| `WEIGHT_HORSE_JOCKEY` 未進 `predict_race` | Phase 3 納入或正式廢棄並改 config／UI |

---

## 1. Phase 0 — 契約與文件凍結

**目的**：實作前鎖定語意，避免邊寫邊改合約。  
**本文件即 Phase 0 產出**；開工實作時只需確認下列清單打勾。

### 細項

- [ ] 複核 §0 三種缺失語意與團隊共識  
- [ ] 確認不做權重重正規化  
- [ ] 確認 `COVERAGE_MODE` / `INTERFERENCE_MODE` 過渡策略  
- [ ] 在 `FACTOR_MODEL_DESIGN.md` Phase 4 加註：補償改獨立干擾持份者（實作 PR 內改）  
- [ ] 在 `DEVELOPMENT_REPORT.md` 賽日 SOP 加「降級路徑」一節（實作 PR 內改）  
- [ ] 列出影響檔案 diff 範圍（見 §6）並開 feature branch

### 驗收

- ADR／本手冊已合併或置於約定路徑；實作 PR 描述連回本手冊章節號。

### 不包含

- 任何分數公式／DB／UI 行為變更。

---

## 2. Phase 1 — 解阻塞：推論 coverage（最高優先）

**目的**：官方評述／NLP 未到仍可 SNAPSHOT；miss 不再「假中性滿權重」。  
**原則**：先改合成層，暫不拆 NLP raw 寫入。

### 2.1 實作細項

1. **`inference_engine.py`**
   - 將 `_lookup_z` 的 `hit` 升級為 stakeholder（至少 `present` + `coverage`）。
   - MISS：`value` 不進總分（effective=0）；`coverage = COVERAGE_MISS_DEFAULT`（或依實體樣本數的連續函數，首版可用 0）。
   - HIT：`coverage = 1.0`（首版；樣本稀疏可留 Phase 3 接 Bayesian 代理）。
   - `total_score = Σ value * weight * coverage`（HIT 時與舊式等價若 coverage=1）。
   - meta 增加 `model_coverage`、每因子 hit/coverage；保留舊 `hit_counts` 相容。
   - `COVERAGE_MODE=shadow`：同時算 `total_score_legacy` 與 `total_score`，UI／log 可對照，正式排序仍用 legacy。
   - `COVERAGE_MODE=on`：正式改用新總分。

2. **Speed Guide 首版**
   - 整場／該馬 SG 欄全空：SG 各子項 coverage=0，不阻塞預測。
   - 部分欄位缺：缺者 coverage=0，有者照舊。

3. **`meeting_pipeline.py` / 作戰室**
   - `SNAPSHOT_ALLOW_PROVISIONAL=True` 時：NLP=`waiting`／`skipped`、SG=`waiting` 仍允許建快照。
   - 批次標記 `provisional=true` + reasons（`nlp_pending` / `sg_missing` / `low_match_rate`…）。
   - 狀態展示：`degraded` 不等於 failed。

4. **UI（最小改動，保留 GitHub 最新版面）**
   - 賽日速覽／融合預測：顯示馬級覆蓋或「降級」徽章；沿用並強化命中資訊。
   - 勿整檔覆蓋 `views/*` 樣式。

5. **測試**
   - 單元：miss 馬 effective=0；全 hit 且 coverage=1 時與 legacy 總分一致（容差）。
   - 場景：無 NLP、無 SG 仍能 `predict_race` + snapshot。

### 2.2 驗收

- [ ] 評述未到可完成 SNAPSHOT  
- [ ] shadow 模式下可匯出舊／新總分對照  
- [ ] 全覆蓋賽馬：`on` 與 legacy 排序高度一致（無故意引入的隨機性）

### 2.3 風險與緩解

| 風險 | 緩解 |
|------|------|
| 新馬／冷門大量 miss → 總分系統性偏低 | shadow 先跑數個賽日；調 `COVERAGE_MISS_DEFAULT` 或只對高權重因子懲罰 |
| 快照尚未有新欄 | Phase 1 可將 coverage 塞進既有 JSON／meta；正式欄位 Phase 3 |

---

## 3. Phase 2 — 干擾值獨立化

**目的**：NLP 受阻不再必須烤進 HORSE／SPEED raw；缺評述＝忽略 \(I\) + 降 \(c\)，基礎近績仍可算。

### 3.1 實作細項

1. **NLP 產物不變**：`nlp_result = {has_excuse, excuse_stage, severity, ...}` 仍寫 `text_reports`。

2. **`factor_calculator.py`**
   - 抽出純函式：
     - `compute_interference_form(excuse) -> I_f`（對應現有名次向補償幅度，但**回傳獨立值**，不改 raw）
     - `compute_interference_speed(excuse) -> I_s`（對應現有 time boost）
   - `calculate_horse_factor`：
     - `INTERFERENCE_MODE=legacy`：維持 `apply_nlp_excuse_boost`（相容）。
     - `stakeholder`：計算基礎 HORSE Z **不**套用 excuse boost；另產出／落庫干擾聚合。
   - `calculate_speed_factor`：同上，拆開 `nlp_time_boost`。
   - **覆蓋度** `c_nlp`（建議）：
     - 取馬近 `NLP_COVERAGE_LOOKBACK_RACES` 場（與近績窗對齊更佳）。
     - `parsed_ratio = 有非 skipped 之 nlp_result 場數 / 窗場數`。
     - 無評述文本且官方可能尚未上架：計入 DELAY（降 c）。
     - 有評述、`has_excuse=false`：計入已觀測（不降 c，\(I=0\)）。

3. **干擾聚合（馬級）**
   - 首版可用：窗內各場 \(I\) 經時間衰減後加權平均，再（可選）場內 Z。
   - 輸出：`I_f`, `I_s`, `c_nlp`（form／speed 可共用 c，或分兩條若解析來源不同）。

4. **`inference_engine.py`**
   - 新增持份者 `INTERFERENCE_FORM` / `INTERFERENCE_SPEED`（或合併為一個 I 若要減參數；預設雙通道）。
   - DELAY：`I=0`, `c=c_nlp`（低）。
   - ABSENT_TRUE：`I=0`, `c` 高。
   - 有受阻：`I>0`, `c` 高，再 × severity 已含於 I 的定義內。

5. **作戰室／NLP 節點**
   - NLP 完成後：重算受影響因子（HORSE／SPEED／I）→ 可觸發 snapshot revision（Phase 3 完善；Phase 2 至少能手動重跑預測）。

6. **測試**
   - 同一歷史：legacy vs stakeholder 可解釋差異（僅干擾通道）。
   - 窗內 0 場 NLP：I 不貢獻，c 低，基礎 HORSE 仍有值。
   - 窗內全無受阻：I=0，c 高。

### 3.2 驗收

- [ ] `INTERFERENCE_MODE=stakeholder` 時關閉 NLP 不阻止基礎近績／速度落庫  
- [ ] 開關干擾只影響 I 通道與 coverage，不污染「無 NLP 的基礎近績」定義  
- [ ] legacy 開關仍可重現舊行為（回歸安全網）

### 3.3 風險與緩解

| 風險 | 緩解 |
|------|------|
| 雙寫 raw＋I 不一致 | 單一模式開關；禁止同時兩種都加權 |
| I 尺度與 Z 不一致 | I 先標準化到近似 Z 尺度，或獨立權重小步調參 |
| 白皮書 Phase 5 NLP pace override 仍未做 | 本方案不阻塞；另開任務，同樣用持份者合約 |

---

## 4. Phase 3 — 全因子持份者化 + 快照 schema

**目的**：所有模型分數走同一 `compose_total(stakeholders)`；快照可鎖定 value／coverage／effective。

### 4.1 實作細項

1. **共用合成器**（新建建議 `score_compose.py` 或置於 `score_share.py` 旁）
   - `compose_total(stakeholders) -> total, model_coverage, breakdown`
   - 單一實作供推論、校準重放、API 使用。

2. **持份者清單（模型軌）**

   | key | value 來源 | coverage 首版 |
   |-----|------------|----------------|
   | JOCKEY | Z | hit→1 / miss→0 |
   | TRAINER | Z | 同上 |
   | SYNERGY | Z | 同上 |
   | DRAW | Z | 同上 |
   | HORSE（近績基礎） | Z | hit；可乘 `c_nlp` 若近績強依賴評述品質（建議：**基礎 HORSE 不乘 c_nlp**，只由 I 通道乘） |
   | PACE | Z | hit／miss |
   | SPEED（基礎） | Z | hit／miss |
   | INTERFERENCE_FORM | \(I_f\) | `c_nlp` |
   | INTERFERENCE_SPEED | \(I_s\) | `c_nlp` |
   | SG_FORM / SG_ENERGY / SG_DELTA | 現有映射 | 欄位有值→1 否則 0 |
   | HORSE_JOCKEY | 決議納入或刪除死權重 | 納入則 hit 層級回退時 coverage 遞減 |

3. **`schema.sql` + migration**
   - 快照表加 §0.6 欄位；`revision_of` / `snapshot_kind`。
   - 舊列：`provisional` 預設 false；`coverage_json` 可空。

4. **`factor_calibration.py`**
   - snapshot 寫入 coverage／effective／provisional。
   - `evaluate_settled`：可選按 `model_coverage` 分桶報命中率。
   - 結算讀舊快照：缺欄 fallback（視為 coverage=1 或未知）。

5. **`prediction_export.py` / API**
   - payload 增加 `model_coverage`、`provisional`（展示用）；破壞性變更需 version 或可選欄。

6. **UI**
   - 作戰室：provisional／revision 標記。
   - 校準頁：coverage 分桶表。
   - 參數頁：新 `WEIGHT_INTERFERENCE_*`、`COVERAGE_*`（expander，勿破壞現有 layout）。

7. **測試**
   - 合成器純函式測試。
   - 快照 round-trip；舊快照 settle 不炸。

### 4.2 驗收

- [ ] 所有模型因子只經合成器進總分  
- [ ] 快照可重放 \(S_h\)（固定權重＋鎖存 value/coverage）  
- [ ] SG／NLP 缺失不阻塞；狀態為 degraded／provisional  
- [ ] HJ 權重「納入或刪除」二選一已落地並改文件

---

## 5. Phase 4 — 補丁閉環、校準與參數

**目的**：延遲資料到達後可修訂預測；用數據調 coverage／I 權重；推介風控可吃 \(C_h\)。

### 5.1 實作細項

1. **補丁管線**
   - 觸發：NLP 批次完成、SG 爬蟲成功、手動「重算並修訂快照」。
   - 行為：重算相關 factor_scores → `predict_race` → **新** `prediction_snapshot_batches`（`snapshot_kind=revision`, `revision_of=原 batch`）。
   - **禁止** UPDATE 已 `settled` 的原快照分數列。
   - 未結算 provisional primary：允許同 batch 覆寫策略需在 PR 寫明；預設仍建議追加 revision 以利審計。

2. **校準**
   - 報表：高／中／低 `model_coverage` 三桶的獨贏／入圍率。
   - 對照 provisional vs 最終 revision 的排序變動幅度（穩定性）。
   - 調參對象：`WEIGHT_INTERFERENCE_*`、`NLP_COVERAGE_LOOKBACK_RACES`、miss coverage 曲線。

3. **推介／Kelly**
   - 可選：`C_h < PICK_MIN_MODEL_COVERAGE` → 不出模型推介或 `kelly_scale` 再乘 \(C_h\)。
   - 與 Form AI `PICK_AI_MIN_CONFIDENCE` 並列說明於 UI note。

4. **SOP 文件**
   - 更新 `DEVELOPMENT_REPORT.md`：賽日降級路徑、何時等 NLP、何時直接 provisional、何時打 revision。
   - 更新 `FACTOR_MODEL_DESIGN.md` Phase 4／推論章：獨立 I + coverage。

5. **清理**
   - `COVERAGE_MODE=on`、`INTERFERENCE_MODE=stakeholder` 穩定後，標記 legacy 棄用期限。
   - 移除或隔離 shadow 對照碼（可留 debug flag）。

### 5.2 驗收

- [ ] 賽日：無評述 → provisional 快照 → NLP 後 revision → 賽後 settle 原／修訂策略清楚  
- [ ] 校準頁可見 coverage 分桶  
- [ ] 文件與 config 預設一致；Railway 部署後重算指引已寫

---

## 6. 檔案地圖與建議 PR 切分

### 6.1 主要觸及檔案

| 區域 | 檔案 |
|------|------|
| 契約／參數 | `config.py`、`ui_param_help.py` |
| 合成 | **新建** `score_compose.py`（建議）、`inference_engine.py`、`score_share.py` |
| 因子／NLP | `factor_calculator.py`、`nlp_processor.py`、`nlp_batch_job.py` |
| 管線／結算 | `meeting_pipeline.py`、`factor_calibration.py`、`schema.sql` |
| API | `prediction_export.py`、`prediction_api.py` |
| UI（最小） | `views/raceday.py`、`views/inference.py`、`views/meeting_ops.py`、`views/calibration.py`、`views/form_nlp_factor.py`、`views/speed_factor.py`、`views/home.py` |
| 文件 | 本手冊、`DEVELOPMENT_REPORT.md`、`FACTOR_MODEL_DESIGN.md` |
| 測試 | `tests/test_score_compose.py`、`tests/test_coverage_inference.py`、`tests/test_interference_stakeholder.py`（新建） |

### 6.2 建議 PR 切分（可一次開大 PR，或按下表拆）

| PR | 內容 | 對應 |
|----|------|------|
| A | `score_compose` + inference coverage + shadow 開關 + 測試 | Phase 1 |
| B | 作戰室 provisional 快照（schema 最小／JSON meta） | Phase 1 尾 |
| C | 干擾獨立化 + mode 開關 + 近績／速度頁說明 | Phase 2 |
| D | 全持份者 + 快照欄位 + calibration／API | Phase 3 |
| E | revision 管線 + 分桶校準 + SOP／白皮書更新 + 推介閘門 | Phase 4 |

**一次性完成時**：仍建議依 A→E 順序在同一 branch 堆 commit，方便 revert 與 review。

### 6.3 實作順序（單次開發日 checklist）

```text
1. config 開關與預設（off/legacy）
2. score_compose + 單元測試
3. inference_engine 接上（shadow）
4. meeting_pipeline 允許 provisional
5. 拆 I_f / I_s；stakeholder 模式
6. schema + calibration 寫讀
7. 其餘因子一律走合成器；HJ 決策
8. revision 動作 + UI 徽章
9. 校準分桶 + 文件
10. shadow 對照數場 → 切 on/stakeholder
```

---

## 7. 明確不做（本方案範圍外）

- 全系統 Cron／自動代運作（交接手冊既有閘門仍有效）。  
- 用關鍵字取代 LLM 做受阻判定。  
- 把 Form AI 分數混入模型 \(S_h\)。  
- Phase 5 步速 NLP override（假性腳軟等）——另案，但應復用本持份者合約。  
- 重正規化缺因子權重至加總不變。

---

## 8. 驗收總表（整案完成定義）

| # | 條件 |
|---|------|
| 1 | 走勢評述／NLP 延遲時，賽日可出 provisional 預測與快照，管線不停滯 |
| 2 | 任意持份者缺失以 coverage 降有效權重；ABSENT_TRUE 不罰 |
| 3 | 干擾為獨立持份者；基礎 HORSE／SPEED 可在無 NLP 下計算 |
| 4 | 所有模型因子經同一合成器；可重放總分 |
| 5 | 資料到位可追加 revision；不覆寫已結算快照 |
| 6 | 校準可按 coverage 分桶；文件／SOP／config 一致 |
| 7 | legacy／shadow 開關可回歸；切 `on`+`stakeholder` 有對照依據 |

---

## 9. 術語對照

| 手冊用語 | 程式現況／去向 |
|----------|----------------|
| 干擾值 \(I\) | 今日 `apply_nlp_excuse_boost`／`nlp_time_boost` → 獨立持份者 |
| 覆蓋／信心 coverage | 今日僅 Form AI `confidence`、推論 `hit` → 模型軌全面化 |
| 結算 | `FactorCalibration.settle_pending`（賽後）；本方案另指分數合成不中斷 |
| 沿路走勢評述 | ≈ `running_comment_text` → `text_reports`（`running_comment`） |
| provisional / revision | 新快照語意；現況無 |

---

*文件版本：2026-09-08｜對應設計討論：覆蓋度持份者模型五階段。實作時以本手冊為單一真相；與白皮書衝突時先更新白皮書再改碼。*
