"""
統一分桶與名稱正規化。

白皮書標準 bucket：Venue_Track_Distance，例如 HV_C_1650、ST_A_1200。
歷史 API 的 races.course 常是「草地/全天候」，真正場地碼在 race_id 內（YYYYMMDDST01）。
排位爬蟲的 course 則直接是 ST / HV。
"""
from __future__ import annotations

import re
from typing import Any, Optional


def extract_venue(race_id: Any = None, course: Any = None) -> str:
    """從 race_id 或 course 抽出 ST / HV。"""
    if race_id is not None and not _is_na(race_id):
        rid = str(race_id).upper()
        m = re.search(r"(ST|HV)", rid)
        if m:
            return m.group(1)

    if course is not None and not _is_na(course):
        c = str(course).strip().upper()
        if c in ("ST", "HV"):
            return c
        if "沙田" in str(course) or "SHA TIN" in c:
            return "ST"
        if "跑馬地" in str(course) or "HAPPY VALLEY" in c:
            return "HV"

    return "UNK"


def normalize_track(track: Any) -> str:
    """清理賽道字串：'"C+3" 賽道' -> 'C+3'；全天候 -> AWT。"""
    if track is None or _is_na(track):
        return "UNK"

    t = str(track).strip()
    if not t or t in ("未知", "None"):
        return "UNK"

    if "全天候" in t or "泥地" in t or "AWT" in t.upper():
        return "AWT"

    t = t.replace('"', "").replace("'", "")
    t = t.replace("賽道", "").replace("跑道", "").strip()
    t = re.sub(r"\s+", "", t)

    # 只保留常見賽道碼片段（A / B / C / C+3 等）
    m = re.search(r"([A-Z](?:\+\d+)?)", t.upper())
    if m:
        return m.group(1)

    return t.upper() if t else "UNK"


def normalize_distance(distance_m: Any) -> Optional[int]:
    if distance_m is None or _is_na(distance_m):
        return None
    try:
        s = str(distance_m).replace("米", "").replace(",", "").strip()
        val = int(float(s))
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def make_bucket_id(venue: Any = None, track: Any = None, distance_m: Any = None,
                   race_id: Any = None, course: Any = None) -> str:
    """
    組出標準 bucket_id。
    可直接傳 venue/track/distance，或傳 race_id + course + track + distance_m。
    """
    v = extract_venue(race_id=race_id, course=course if course is not None else venue)
    if venue is not None and not _is_na(venue):
        # 若明確傳入已是 ST/HV，優先使用
        vv = str(venue).strip().upper()
        if vv in ("ST", "HV"):
            v = vv
        elif v == "UNK":
            v = extract_venue(course=venue)

    tr = normalize_track(track)
    dist = normalize_distance(distance_m)
    dist_s = str(dist) if dist is not None else "0"
    return f"{v}_{tr}_{dist_s}"


def normalize_person_name(name: Any) -> str:
    """騎師/練馬師名稱：去掉負磅括號與多餘空白。"""
    if name is None or _is_na(name):
        return ""
    s = str(name).strip()
    s = re.sub(r"\([^)]*\)", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def synergy_name(jockey: Any, trainer: Any) -> str:
    return f"{normalize_person_name(jockey)} & {normalize_person_name(trainer)}"


def horse_jockey_name(horse: Any, jockey: Any) -> str:
    """人馬組合鍵（白皮書：不分賽道距離，全域統計）。"""
    return f"{normalize_person_name(horse)} & {normalize_person_name(jockey)}"


# 人馬合作 / 部分全域因子使用的虛擬分桶
GLOBAL_BUCKET = "GLOBAL"

# 距離帶：接近距離可共用樣本（短途 / 哩途 / 長途）
DISTANCE_BANDS = (
    ("SPRINT", 1000, 1200),   # 1000–1200
    ("MILE", 1400, 1650),     # 1400–1650
    ("STAY", 1800, 2400),     # 1800+
)


def distance_band(distance_m: Any) -> str:
    d = normalize_distance(distance_m)
    if d is None:
        return "UNK"
    for name, lo, hi in DISTANCE_BANDS:
        if lo <= d <= hi:
            return name
    # 1300 等夾縫：靠最近帶
    if d < 1400:
        return "SPRINT"
    if d < 1800:
        return "MILE"
    return "STAY"


def distance_proximity_weight(hist_distance_m: Any, target_distance_m: Any) -> float:
    """
    接近距離加權：同距 1.0；±200 較高；更遠仍保留小權重（不全丟，避免過度分桶）。
    """
    h = normalize_distance(hist_distance_m)
    t = normalize_distance(target_distance_m)
    if h is None or t is None:
        return 1.0
    diff = abs(h - t)
    if diff == 0:
        return 1.0
    if diff <= 200:
        return 0.80
    if diff <= 400:
        return 0.50
    if distance_band(h) == distance_band(t):
        return 0.35
    return 0.20


def make_band_bucket_id(
    venue: Any = None,
    distance_m: Any = None,
    race_id: Any = None,
    course: Any = None,
) -> str:
    """
    粗桶：Venue + 距離帶（忽略賽道細碼）。
    例：ST_SPRINT、HV_MILE、ST_STAY
    供騎師 / 練馬師 / 騎練使用，增加樣本。
    """
    v = extract_venue(race_id=race_id, course=course if course is not None else venue)
    if venue is not None and not _is_na(venue):
        vv = str(venue).strip().upper()
        if vv in ("ST", "HV"):
            v = vv
    band = distance_band(distance_m)
    return f"{v}_{band}"


def is_valid_band_bucket(bucket_id: str) -> bool:
    if not bucket_id or not isinstance(bucket_id, str):
        return False
    parts = bucket_id.split("_")
    if len(parts) != 2:
        return False
    venue, band = parts[0], parts[1]
    return venue in ("ST", "HV") and band in ("SPRINT", "MILE", "STAY")


def parse_bucket_parts(bucket_id: str):
    """ST_A_1200 -> (ST, A, 1200)；無法解析則 (None,None,None)。"""
    if not bucket_id or not isinstance(bucket_id, str):
        return None, None, None
    parts = bucket_id.split("_")
    if len(parts) < 3:
        return None, None, None
    venue, track, dist_s = parts[0], parts[1], parts[-1]
    try:
        dist = int(dist_s)
    except ValueError:
        dist = None
    return venue, track, dist


def is_valid_bucket(bucket_id: str) -> bool:
    if not bucket_id or not isinstance(bucket_id, str):
        return False
    parts = bucket_id.split("_")
    if len(parts) < 3:
        return False
    venue, track, dist = parts[0], parts[1], parts[-1]
    if venue not in ("ST", "HV"):
        return False
    if track in ("", "UNK", "0"):
        return False
    try:
        return int(dist) > 0
    except ValueError:
        return False


def _is_na(val: Any) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(val))
    except Exception:
        return val is None


# 排位／歷史班次標籤（長詞優先，避免「國際三級賽」被切成「三級賽」前漏掉國際）
RACE_CLASS_LABEL_RE = re.compile(
    r"(國際[一二三]級賽|香港[一二三]級賽|[一二三]級賽|"
    r"第[一二三四五]班|表列賽|新馬賽|"
    r"Group\s*(?:III|II|I|[123])|G\s*([123]))",
    re.IGNORECASE,
)


def extract_race_class_label(text: Any) -> str:
    """從排位標題／內文抽出班次顯示字串（如『三級賽』『第四班』）。"""
    if text is None or _is_na(text):
        return ""
    m = RACE_CLASS_LABEL_RE.search(str(text))
    if not m:
        return ""
    label = m.group(0).strip()
    # 正規化 Group / G1
    g = re.match(r"Group\s*(III|II|I|[123])", label, re.I)
    if g:
        tok = g.group(1).upper()
        mapping = {"I": "一級賽", "1": "一級賽", "II": "二級賽", "2": "二級賽", "III": "三級賽", "3": "三級賽"}
        return mapping.get(tok, label)
    g2 = re.match(r"G\s*([123])", label, re.I)
    if g2:
        return {"1": "一級賽", "2": "二級賽", "3": "三級賽"}[g2.group(1)]
    return label


def parse_class_num(race_class: Any):
    """
    班次 → 數字等級（愈大班次愈低）。
    - 第五班→5 … 第一班→1
    - 一／二／三級賽、國際／香港級賽、表列賽、Group → 皆視為 **第一班等級 (1)**
    - 新馬賽 → None（特殊賽，不強行對齊）
    """
    if race_class is None or _is_na(race_class):
        return None
    s = str(race_class).strip()
    if not s:
        return None
    if re.search(r"新馬", s):
        return None
    # 分級賽／表列 = 第一班等級
    if re.search(
        r"[一二三]級賽|表列賽|Group\s*(?:III|II|I|[123])|\bG\s*[123]\b",
        s,
        re.I,
    ):
        return 1
    m = re.search(r"第([一二三四五六七八九十])班", s)
    if m:
        cmap = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        return cmap.get(m.group(1))
    m = re.search(r"(?:Class|班)\s*([1-5])", s, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-5])\s*班", s)
    if m:
        return int(m.group(1))
    return None


def format_class_display(race_class: Any) -> str:
    """UI 顯示：三級賽 →『三級賽（≡第一班）』。"""
    if race_class is None or _is_na(race_class) or not str(race_class).strip():
        return "-"
    s = str(race_class).strip()
    n = parse_class_num(s)
    if n == 1 and re.search(r"[一二三]級賽|表列賽|Group|\bG\s*[123]\b", s, re.I):
        return f"{s}（≡第一班）"
    return s
