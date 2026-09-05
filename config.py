"""
J18 量化模型 - 超參數設定檔 (Hyperparameters Configuration)
此檔案將所有因子計算的主觀參數獨立隔離。
未來在使用機器學習 (如 Optuna, Grid Search) 進行參數最佳化時，
只需動態修改此檔案或覆寫此 Config 類別即可進行自動回測尋優。
"""

class ModelConfig:
    # ==========================================
    # 1. 賽果目標權重 (Target Weights)
    # ==========================================
    WIN_WEIGHT = 1.0    # 跑第 1 名的得分
    PLACE_WEIGHT = 0.3  # 跑入位置 (第 2, 3, 4 名) 的得分

    # ==========================================
    # 2. 時間衰減設定 (Time Decay Rates)
    # 預設以 90 天 (約 3 個月) 為一個時間桶 (Bucket)
    # ==========================================
    TIME_WINDOW_DAYS = 90
    
    # 衰減陣列：[0~3個月, 3~6個月, 6~9個月, 9~12個月, 12個月以上]
    JOCKEY_DECAY = [1.0, 0.70, 0.40, 0.20, 0.0]   # 騎師狀態波動大，衰減快
    TRAINER_DECAY = [1.0, 0.85, 0.70, 0.50, 0.2]  # 練馬師狀態穩定，衰減慢
    SYNERGY_DECAY = [1.0, 1.00, 0.60, 0.60, 0.0]  # 騎練合作次數少，時間窗需拉長
    HORSE_JOCKEY_DECAY = [1.0, 1.00, 0.80, 0.60, 0.4] # 人馬合作次數極少，保留長期記憶
    HORSE_DECAY = [1.0, 0.80, 0.50, 0.20, 0.0]    # 馬匹近績狀態波動大，衰減較快

    # ==========================================
    # 3. 貝葉斯平滑常數 (Bayesian Smoothing 'C')
    # 解決稀疏數據 (例如出賽 1 次贏 1 次 = 100% 勝率的偏差)
    # 數值代表「虛擬平均出賽次數」，數字越大，拉回平均值的力量越強 (Cap)
    # ==========================================
    JOCKEY_SMOOTH_C = 20
    TRAINER_SMOOTH_C = 20
    SYNERGY_SMOOTH_C = 10  # 合作數據天生較少，平滑力道可稍微放輕
    HORSE_JOCKEY_SMOOTH_C = 5  # 人馬合作次數極少，平滑力道更輕
    HORSE_SMOOTH_C = 5     # 馬匹近績平滑 (馬匹出賽頻率低)
    DRAW_SMOOTH_C = 20     # 檔位大數據平滑
    JOCKEY_LOOKBACK_RACES = 3  # 換人效應：回溯該駒近 N 仗前任騎師
    # B 軌換人Δ 合理化：差值尺度大於 Z-Score；純 B（無合作）再折扣
    UPGRADE_DELTA_CAP = 1.2          # tanh 飽和上限
    UPGRADE_B_ONLY_SCALE = 0.40      # 無合作、純用 B 時再乘此折扣（換人≠已熟識）
    HJ_MIN_RUNS_PURE_A = 2           # 合作出賽達此數純用 A
    HJ_SPARSE_B_BLEND = 0.15         # 合作樣本少時，正規化 B 混入權重（宜小）
    HJ_PARTNERSHIP_PRIOR = 0.30      # 有合作歷史的熟識加分（疊在採用分上）


    # ==========================================
    # 4. 檔位與場地因子設定 (Draw & Track Bias)
    # Phase 2 參數
    # ==========================================
    # 檔位分組邊界：[3, 7, 10] 代表 1-3(內), 4-7(中內), 8-10(中外), 11-14(外)
    DRAW_GROUP_BOUNDARIES = [3, 7, 10]
    
    # 場地變化動態修正 (針對變化地 Yielding/Soft 削弱內欄優勢)
    YIELDING_TRACK_MULTIPLIER = -0.5
    
    # ==========================================
    # 5. 近績與 NLP 補償因子 (Recent Form & NLP Excuse)
    # Phase 4 參數
    # ==========================================
    RECENT_FORM_WEIGHT = 0.5         # 近績基礎分數權重
    EXCUSE_MULTIPLIER_EARLY = 1.2    # 早段受阻補償係數 (較小)
    EXCUSE_MULTIPLIER_MIDDLE = 1.5   # 中段受阻補償係數 (中等)
    EXCUSE_MULTIPLIER_LATE = 2.0     # 直路/末段受阻補償係數 (最大，因為直接影響名次)
    CLASS_DROP_BONUS = 1.5           # 降班戰術加分 (需配合賠率與時間驗證)

    # ==========================================
    # 7. 步速與跑法因子 (Pace & Running Style)
    # Phase 5 參數
    # ==========================================
    PACE_SMOOTH_C = 5              # 跑法數據平滑常數
    CLOSER_BONUS_WEIGHT = 1.2      # 後追馬加分權重 (當預期為快步速時)
    FRONT_RUNNER_BONUS_WEIGHT = 1.2 # 前領馬加分權重 (當預期為慢步速時)

    # ==========================================
    # 8. 速度指數與絕對時間 (Speed Figure & FSR)
    # Phase 6 參數
    # ==========================================
    FSR_PENALTY_THRESHOLD = 105.0  # 步速過慢，開始懲罰末段時間的閥值 (%)
    FSR_BONUS_THRESHOLD = 95.0     # 步速極快，開始獎勵末段時間的閥值 (%)
    TIME_EMA_ALPHA = 0.5           # 近況時間趨勢的指數平滑衰減率
    # Par Time：分桶分位數（50=中位數，較抗極端慢馬）；桶樣本不足則逐級回退
    SPEED_PAR_PERCENTILE = 50.0
    SPEED_PAR_MIN_N = 30

    # ==========================================
    # 9. 最終推論總分組合權重 (Inference Ensemble Weights)
    # 用於計算排位表上的最終總分預測 (Total Score)
    # 這些權重加總不一定要是 1.0，但比例代表影響力
    # ==========================================
    WEIGHT_JOCKEY = 1.0
    WEIGHT_TRAINER = 0.8
    WEIGHT_SYNERGY = 0.5
    WEIGHT_DRAW = 1.2
    WEIGHT_HORSE_JOCKEY = 0.5
    WEIGHT_RECENT_FORM = 1.5
    WEIGHT_SPEED_FIGURE = 1.5
    WEIGHT_PACE = 0.8              # 跑法／追回指數 + 同場形勢加權

    # 官方 Speed Guide 權重（CMS：fitnessrating / speedproenergy / speedproenergydifference）
    # ENERGY 在推論時改為同場 Z；DELTA 為官方主排序（正＝看好）
    WEIGHT_SG_FORM = 1.0
    WEIGHT_SG_ENERGY = 1.0
    WEIGHT_SG_DELTA = 0.5

    # 總分 → 同場勝率。先場內 z-score 再 softmax，避免加權總分絕對差造成 80% vs 0.2%。
    # T 愈小愈尖、愈大愈平均。場內 z 後分數約在 ±2～3，預設 T=1.5 較贴近真實獨贏分佈。
    SOFTMAX_WITHIN_RACE_Z = True
    SOFTMAX_TEMPERATURE = 1.5

    # 步速熱度／形勢劇本
    # heat 顯示用：同場 early_speed_z 最高前 N 名加總（僅供參考）
    EARLY_SPEED_TOP_N = 3
    # 劇本判定：數「早段速度 Z ≥ 門檻」的爭搶馬（互燒 vs 獨走）
    # 舊版用 heat≥2.5→超快會幾乎全場中標（12 匹場前 3 名 Z 期望和約 3.5+）
    PACE_EARLY_FAST_Z = 1.0        # 達此視為具前領／搶放意圖（約前 16% 全局）
    PACE_HOT_MIN_CONTENDERS = 3    # 爭搶馬 ≥ 此 → 超快互燒
    PACE_COLD_MAX_CONTENDERS = 1   # 爭搶馬 ≤ 此 → 偏慢／獨走

    @classmethod
    def get_params_dict(cls):
        """將參數轉為字典，方便匯出給機器學習框架記錄實驗 (Experiment Tracking)"""
        return {k: v for k, v in cls.__dict__.items() if not k.startswith("__") and not callable(v)}
