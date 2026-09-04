-- J18 賽馬歷史賽果分析與 AI 輔助資料庫 Schema
-- 專為 Railway (PostgreSQL) 部署設計

-- ==========================================
-- 1. 賽日層 (Meetings)
-- ==========================================
CREATE TABLE race_meetings (
    meeting_id VARCHAR(50) PRIMARY KEY, -- 例如 '2026-07-15'
    racing_date DATE NOT NULL UNIQUE,
    file_name VARCHAR(100),
    file_mtime BIGINT,
    file_size BIGINT,
    race_count INT,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================
-- 2. 賽事層 (Races)
-- ==========================================
CREATE TABLE races (
    race_id VARCHAR(50) PRIMARY KEY, -- 例如 '20260715HV01' (日期 + 場地 + 場次)
    meeting_id VARCHAR(50) REFERENCES race_meetings(meeting_id) ON DELETE CASCADE,
    race_num INT NOT NULL,
    title VARCHAR(50),
    race_name VARCHAR(100),
    class VARCHAR(50),
    distance_m INT,             -- 例如 1650
    distance_text VARCHAR(50),  -- 例如 '1650米'
    rating_text VARCHAR(50),    -- 例如 '40-0'
    course VARCHAR(50),         -- 例如 '草地'
    track VARCHAR(50),          -- 例如 '"C" 賽道'
    ground VARCHAR(50),         -- 例如 '好地'
    race_time_raw VARCHAR(50),
    raw_detail_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(meeting_id, race_num)
);

-- 2.1 賽事分段時間 (Race Sectionals)
CREATE TABLE race_sectionals (
    id SERIAL PRIMARY KEY,
    race_id VARCHAR(50) REFERENCES races(race_id) ON DELETE CASCADE,
    stage_no INT NOT NULL,
    sectional_time VARCHAR(20),
    split_1 VARCHAR(20),
    split_2 VARCHAR(20),
    raw_json JSONB,
    UNIQUE(race_id, stage_no)
);

-- ==========================================
-- 3. 馬匹成績層 (Runners) - 最核心的統計表
-- ==========================================
CREATE TABLE runners (
    runner_id VARCHAR(50) PRIMARY KEY, -- 直接使用 API 回傳的 id, 例如 '20260715HV01J080'
    race_id VARCHAR(50) REFERENCES races(race_id) ON DELETE CASCADE,
    horse_id VARCHAR(50) NOT NULL,     -- 例如 'HK_2023_J080'
    racing_horse_id BIGINT,
    horse_no INT,
    brand_num VARCHAR(20),
    horse_name VARCHAR(100),
    finish_order_raw VARCHAR(20),      -- 保留 'DNF', 'WX-A' 等文字
    finish_order_num INT,              -- 清洗後的數字名次
    final_time VARCHAR(20),
    jockey_name VARCHAR(50),
    trainer_name VARCHAR(50),
    handicap_weight NUMERIC,
    bar_draw INT,
    runner_rating INT,
    runner_rating_delta INT,
    horse_body_weight NUMERIC,         -- 例如 1095
    horse_body_weight_delta NUMERIC,   -- 例如 +14
    optimal_time VARCHAR(20),
    age INT,
    sex VARCHAR(20),
    gear_raw VARCHAR(50),              -- 例如 'V-/B2/TT'
    last_six_run_raw VARCHAR(50),
    bonus NUMERIC,                     -- 千分位清洗後數字
    priority VARCHAR(10),
    trump_card VARCHAR(10),
    preference VARCHAR(10),
    scratched BOOLEAN DEFAULT FALSE,
    win_probability_raw VARCHAR(20),
    pla_probability_raw VARCHAR(20),
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(race_id, horse_no)
);

-- 3.1 馬匹分段走位 (Runner Sections)
CREATE TABLE runner_sections (
    id SERIAL PRIMARY KEY,
    runner_id VARCHAR(50) REFERENCES runners(runner_id) ON DELETE CASCADE,
    stage_no INT NOT NULL,
    position_raw VARCHAR(20),
    distance_behind_raw VARCHAR(50),
    sectional_time VARCHAR(20),
    split_1 VARCHAR(20),
    split_2 VARCHAR(20),
    raw_json JSONB,
    UNIQUE(runner_id, stage_no)
);

-- ==========================================
-- 4. 派彩資料 (Payouts)
-- ==========================================
CREATE TABLE payouts (
    id SERIAL PRIMARY KEY,
    race_id VARCHAR(50) REFERENCES races(race_id) ON DELETE CASCADE,
    bet_type VARCHAR(50) NOT NULL,     -- 例如 '獨贏', '位置'
    combination VARCHAR(100) NOT NULL, -- 例如 '3,11'
    payout_amount NUMERIC NOT NULL,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================
-- 5. 站內衍生分析層 (Signals)
-- ==========================================

-- 5.1 人氣指標
CREATE TABLE popularity_metrics (
    race_id VARCHAR(50) PRIMARY KEY REFERENCES races(race_id) ON DELETE CASCADE,
    total_likes INT,
    famous_count INT,
    cache_hit BOOLEAN,
    raw_json JSONB
);

CREATE TABLE popularity_horse_tally (
    id SERIAL PRIMARY KEY,
    race_id VARCHAR(50) REFERENCES races(race_id) ON DELETE CASCADE,
    horse_no INT NOT NULL,
    like_count INT,
    ratio NUMERIC,
    UNIQUE(race_id, horse_no)
);

-- 5.2 推薦/趨勢
CREATE TABLE promote_signals (
    id SERIAL PRIMARY KEY,
    race_id VARCHAR(50) REFERENCES races(race_id) ON DELETE CASCADE,
    promote_type VARCHAR(50),
    scene_status INT,
    trend_raw JSONB,
    json_data_raw JSONB,
    source VARCHAR(50),
    raw_json JSONB
);

-- 5.3 折讓/盤口 (Discount4)
CREATE TABLE discount_signals (
    id SERIAL PRIMARY KEY,
    race_id VARCHAR(50) REFERENCES races(race_id) ON DELETE CASCADE,
    horse_no INT NOT NULL,
    win_code VARCHAR(20),
    win_value NUMERIC,
    pla_code VARCHAR(20),
    pla_value NUMERIC,
    add_code VARCHAR(20),
    add_value NUMERIC,
    win_odds_raw VARCHAR(20),
    pla_odds_raw VARCHAR(20),
    raw_json JSONB,
    UNIQUE(race_id, horse_no)
);

-- ==========================================
-- 6. AI 專用文字資料表 (Text Reports) - 滿足需求: 確保不遺漏 running_comment_text 及 incident_report_text
-- ==========================================
CREATE TABLE text_reports (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(20) NOT NULL,    -- 'race' 或 'runner'
    entity_id VARCHAR(50) NOT NULL,      -- 對應 race_id 或 runner_id
    report_type VARCHAR(50) NOT NULL,    -- 'running_comment', 'incident_report', 'veterinary_record' 等
    report_text TEXT NOT NULL,           -- 原始文字
    report_text_clean TEXT,              -- 供 AI 或 NLP 處理後使用的清洗版
    source_api VARCHAR(100),             -- 資料來源端點或識別
    language VARCHAR(20) DEFAULT 'zh-HK',
    raw_json JSONB,                      -- 關聯的原始 JSON 段落
    nlp_result TEXT,                     -- LLM 結構化 JSON（has_excuse / stage / severity）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================
-- 7. 因子分數表 (Factor Scores) - 供未來的機器學習與排位預測查詢
-- ==========================================
CREATE TABLE factor_scores (
    id SERIAL PRIMARY KEY,
    factor_type VARCHAR(20) NOT NULL,    -- 'JOCKEY', 'TRAINER', 'SYNERGY', 'DRAW' 等
    bucket_id VARCHAR(50) NOT NULL,      -- 例如 'HV_C_1650'
    entity_name VARCHAR(100) NOT NULL,   -- 例如 '潘頓', '告東尼', '潘頓 & 告東尼'
    actual_runs INT NOT NULL,            -- 真實出賽次數
    weighted_runs NUMERIC NOT NULL,      -- 時間衰減加權後的出賽次數
    adjusted_score NUMERIC NOT NULL,     -- 貝葉斯平滑後的原始分數
    z_score NUMERIC NOT NULL,            -- 同分桶內的標準化分數 (Z-Score)
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(factor_type, bucket_id, entity_name)
);

-- 建立索引加速查詢
CREATE INDEX idx_text_reports_entity ON text_reports(entity_type, entity_id);
CREATE INDEX idx_text_reports_type ON text_reports(report_type);

-- 觸發器：自動更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER trg_text_reports_updated_at
BEFORE UPDATE ON text_reports
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ==========================================
-- 8. 賽前排位與速勢走位 (Upcoming Races & Formguide)
-- ==========================================
CREATE TABLE upcoming_races (
    race_id VARCHAR(50) PRIMARY KEY,
    racing_date DATE,
    race_num INT,
    course VARCHAR(50),
    race_name VARCHAR(100),
    class VARCHAR(50),
    distance_m INT,
    track VARCHAR(50),
    ground VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE upcoming_runners (
    runner_id VARCHAR(50) PRIMARY KEY,
    race_id VARCHAR(50) REFERENCES upcoming_races(race_id) ON DELETE CASCADE,
    horse_no INT,
    horse_name VARCHAR(100),
    horse_code VARCHAR(20),
    draw INT,
    jockey_name VARCHAR(50),
    trainer_name VARCHAR(50),
    handicap_weight NUMERIC,
    horse_weight NUMERIC,
    rating INT,
    rating_delta INT,
    gear VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE upcoming_formguide (
    runner_id VARCHAR(50) PRIMARY KEY,
    race_id VARCHAR(50),
    horse_no INT,
    form_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE upcoming_speedguide (
    runner_id VARCHAR(50) PRIMARY KEY,
    race_id VARCHAR(50),
    horse_no INT,
    form_rating VARCHAR(20),      -- 狀態評級 (例如 A, B, C 或數值)
    speed_energy NUMERIC,         -- 速勢能量評估
    speed_energy_delta NUMERIC,   -- 速勢能量評估差值
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
