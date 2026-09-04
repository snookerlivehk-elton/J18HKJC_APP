# J18 賽馬量化預測系統 - AI 開發交接報告 (Handover Report)

> **⚠️ 下一次 AI 接手注意事項 (To Next AI Agent):**
> 1. 本專案是一個**高度量化的賽馬預測系統**，請在執行任何操作前，**務必先閱讀 [`FACTOR_MODEL_DESIGN.md`](file:///c:/Users/User/.trae/J182026API_RE/FACTOR_MODEL_DESIGN.md)**，裡面記載了 6 大核心因子（如 Z-Score、貝葉斯平滑、FSR、Pace Projection）的數學邏輯，切勿偏離白皮書的設計。
> 2. 目前卡關點：`api.j18.hk` 的歷史賽果 API 暫時阻擋 IP / 維修中。
> 3. 下一步首要任務：一旦使用者告知 API 已修復，請立即執行 `python batch_crawler.py` 抓取歷史數據，並測試 `factor_calculator.py` 是否能正確產出所有因子的 Z-Score。
> 4. 專案最終目標是部署至 **Railway**，並依賴 `fixtures` 表進行全自動 Cron Job 排程。

---

## 1. 系統架構與目前進度 (Current Status)

### 🧠 核心大腦與模型 (Models)
- **`FACTOR_MODEL_DESIGN.md` (已完成 100%)**：定義了 6 大量化因子。這是整個系統的靈魂。
- **`config.py` (已完成 100%)**：將所有模型超參數（如時間衰減、平滑常數、目標權重）抽離，為未來的機器學習 (ML) 參數尋優做好準備。
- **`factor_calculator.py` (已完成 80%)**：基於 Pandas 的高速計算引擎，目前已完成 Phase 1 (騎練 Z-Score) 的計算，並串接至 Streamlit UI。

### 🕸️ 資料收集與爬蟲管線 (ETL Pipelines)
- **`schema.sql` (已完成)**：支援 PostgreSQL (Railway) 與 SQLite (Local)，並特別獨立出 `text_reports` 表供未來 NLP 分析。
- **`batch_crawler.py` (已完成)**：負責抓取 J18 歷史賽果，具備斷點續傳與智能退避功能。(等待 API 修復中)
- **`racecard_crawler.py` (已完成)**：負責抓取 HKJC 官方「明日排位表」。(已測試成功)
- **`formguide_crawler.py` (已完成)**：負責抓取 HKJC Speedpro 的「賽前短評」，供 NLP 萃取隱藏優勢。
- **`fixture_crawler.py` (已完成)**：負責抓取全季 88 個賽馬日的「賽期表」，這是全自動排程的基石。

---

## 2. 全自動化排程藍圖 (The Auto-Pilot Cron Logic)

當 API 修復且模型數據驗證無誤後，系統將部署至 Railway，並按以下邏輯自動運作（無需人工介入）：

1. **每年季前**：執行 `fixture_crawler.py`，載入全季賽馬日曆至 `fixtures` 表。
2. **賽前 2 日 (早上 08:00)**：若 `fixtures` 顯示後天有賽事，觸發 `racecard_crawler.py` 抓取排位表，並呼叫大腦進行「Pace Projection (預計步速推算)」。
3. **賽前 1 日 (下午 17:00)**：觸發 `formguide_crawler.py` 抓取賽前短評，交由 LLM 萃取「漏閘 / 狀態提升」等標籤，進行 Z-Score 最終補償。
4. **賽後隔日 (半夜 03:00)**：觸發 `batch_crawler.py` 抓取昨日賽果，接著啟動 `factor_calculator.py` 重新計算全庫的 Z-Score，完成大腦的自我迭代與升級。

---

## 3. 未來開發待辦事項 (Future Roadmap)

1. **API 恢復後的首要工作**：
   - 啟動 `batch_crawler.py` 灌入至少 1 年的歷史數據。
   - 補齊 `factor_calculator.py` 中剩餘的 Phase 2 ~ Phase 6 因子計算邏輯（目前僅實作了 Phase 1）。
   - 確保 Streamlit UI (`ui_app.py`) 能正確顯示所有因子的綜合評分。

2. **NLP 模組開發**：
   - 串接 OpenAI / Claude API，針對 `text_reports` (賽後) 與 `upcoming_formguide` (賽前) 進行結構化 JSON 標籤抽取。

3. **Railway 部署**：
   - 將 SQLite 切換回 PostgreSQL。
   - 設定 Railway 的 Cron Jobs 對應上述的自動化排程藍圖。
