"""
賽前 Form Guide + 系統統計 → AI 文字評價與獨立評分。

結果寫入 upcoming_form_ai（可重用）；不覆蓋模型勝率，僅平行訊號。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text

from nlp_processor import NLPProcessor
from inference_engine import InferenceEngine
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH, resolve_database_url

try:
    from dotenv import load_dotenv
    # 與 form_ai_batch_job 相同：唔好蓋過容器已注入嘅 OPENAI_*／DATABASE_URL
    load_dotenv(override=False)
except ImportError:
    pass

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = resolve_database_url()

# 與賽前文案同一口徑：給馬迷看的只有 summary。分數欄留在內部，不進正文。
PUBLIC_SUMMARY_LIMIT = 90
_PUBLIC_ANGLES = ("步速", "走位", "路程", "恢復", "出閘")
_PUBLIC_LEADS = (
    "起句直接寫跑法，不要用「近績」二字開頭。",
    "起句先寫今日路程或步速判斷，近績事實放在後面。",
    "起句用上仗一個具體位置（領放、沿欄、望空、包入），收尾不要用「值得留意」。",
)
_FORBIDDEN_PUBLIC = (
    "模型",
    "演算法",
    "雙軌",
    "份額",
    "勝率",
    "預測分",
    "預測排名",
    "機器學習",
    "系統統計",
    "綜合第",
)

FORM_AI_SYSTEM_PROMPT = """你是香港資深練馬師，替馬迷寫賽前形勢短評。口吻專業、短、有判斷，像筆記而不是報告，也不是貼士。
嚴格輸出 JSON：
{
  "summary": "繁體兩句以內，70到90字。一句是近績或上仗真實跑法，一句是今日形勢判斷。",
  "ai_score": -2.0至2.0的數字（正=看高、負=看淡、0=中性）,
  "confidence": 0.0至1.0,
  "tags": ["步速或走位或路程或恢復或出閘，只一個"],
  "risks": ["一個具體風險，用賽事語言"],
  "evidence": ["只引用近績裡出現過的跑法，不要引用分數"]
}
規則：
- summary 是馬迷會看到的唯一文字，必須和賽前文案同一種寫法。
- summary 禁止出現：模型、AI、演算法、雙軌、份額、勝率、預測分、排名、系統。分數只填在 ai_score 和 confidence。
- 不可虛構近績沒有的名次、路程、跑法、時間。近績空泛就直說資訊不足，並降低 confidence。
- 每匹馬只抓住最貼的一點來判斷：步速、走位、路程、恢復、出閘，五選一，不要面面俱到。
- 換起句、換收尾。禁止每條都用「近績顯示」「值得留意」「賽前可對照會否延續」。
- 有判斷，但不寫心水、必中、跟注。
"""


def summary_leaks_internal(text: str) -> bool:
    s = str(text or "")
    if any(word in s for word in _FORBIDDEN_PUBLIC):
        return True
    return bool(re.search(r"\bAI\b", s, re.IGNORECASE))


def fit_public_summary(text: str, limit: int = PUBLIC_SUMMARY_LIMIT) -> str:
    s = re.sub(r"\s+", "", str(text or "")).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for mark in ("。", "；", "，"):
        idx = cut.rfind(mark)
        if idx >= 24:
            return cut[: idx + 1]
    return cut


def load_public_summaries(race_id: str) -> Dict[int, str]:
    """賽前文案直接用這裡的 summary，避免再生成一遍不同的評述。"""
    engine = create_engine(DATABASE_URL_SYNC)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT horse_no, summary
                    FROM upcoming_form_ai
                    WHERE race_id = :race_id
                    """
                ),
                {"race_id": race_id},
            ).fetchall()
    except Exception:
        return {}
    finally:
        engine.dispose()
    out: Dict[int, str] = {}
    for horse_no, summary in rows:
        text_v = fit_public_summary(summary or "")
        if text_v and not summary_leaks_internal(text_v):
            try:
                out[int(horse_no)] = text_v
            except (TypeError, ValueError):
                continue
    return out


class FormAIAnalyst:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL_SYNC)
        self.nlp = NLPProcessor()
        self.infer = InferenceEngine()
        self.ensure_tables()

    def ensure_tables(self):
        if USE_SQLITE:
            ddl = """
            CREATE TABLE IF NOT EXISTS upcoming_form_ai (
                runner_id TEXT PRIMARY KEY,
                race_id TEXT,
                horse_no INTEGER,
                ai_score REAL,
                confidence REAL,
                summary TEXT,
                tags_json TEXT,
                risks_json TEXT,
                evidence_json TEXT,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = """
            CREATE TABLE IF NOT EXISTS upcoming_form_ai (
                runner_id VARCHAR(50) PRIMARY KEY,
                race_id VARCHAR(50),
                horse_no INT,
                ai_score NUMERIC,
                confidence NUMERIC,
                summary TEXT,
                tags_json JSONB,
                risks_json JSONB,
                evidence_json JSONB,
                raw_json JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        with self.engine.begin() as conn:
            conn.execute(text(ddl))

    def is_ready(self) -> bool:
        return self.nlp.is_ready()

    def load_formguide(self, race_id: str) -> pd.DataFrame:
        try:
            return pd.read_sql(
                text(
                    "SELECT runner_id, race_id, horse_no, form_text FROM upcoming_formguide "
                    "WHERE race_id = :r"
                ),
                self.engine,
                params={"r": race_id},
            )
        except Exception:
            return pd.DataFrame()

    def build_user_payload(self, race_meta: dict, row: pd.Series, form_text: str) -> str:
        stats = {
            "馬號": int(row["馬號"]) if pd.notna(row.get("馬號")) else None,
            "馬名": row.get("馬名"),
            "檔位": row.get("檔位"),
            "騎師": row.get("騎師"),
            "練馬師": row.get("練馬師"),
            "負磅": row.get("負磅"),
            "騎師分": row.get("騎師分"),
            "練馬師分": row.get("練馬師分"),
            "騎練分": row.get("騎練分"),
            "檔位分": row.get("檔位分"),
            "近績分": row.get("近績分"),
            "步速分": row.get("步速分"),
            "速度分": row.get("速度分"),
            "SG貢獻": row.get("SG貢獻"),
            "總預測分": row.get("總預測分"),
            "模型勝率%": row.get("模型勝率%"),
            "預測排名": row.get("預測排名"),
            "命中": row.get("命中"),
        }
        meta = {
            "race_id": race_meta.get("race_id"),
            "場地": race_meta.get("course"),
            "賽道": race_meta.get("track"),
            "距離": race_meta.get("distance_m"),
            "班次": race_meta.get("class"),
        }
        horse_no = int(stats["馬號"] or 0)
        angle = _PUBLIC_ANGLES[horse_no % len(_PUBLIC_ANGLES)]
        lead = _PUBLIC_LEADS[horse_no % len(_PUBLIC_LEADS)]
        return (
            "【場次】\n"
            + json.dumps(meta, ensure_ascii=False)
            + "\n【官方近績。summary 只能改寫這裡出現過的跑法】\n"
            + (form_text or "（無）")
            + "\n【內部評分。只用於 ai_score 和 confidence，禁止寫進 summary】\n"
            + json.dumps(stats, ensure_ascii=False)
            + f"\n【這匹馬的寫法】優先從「{angle}」落筆。{lead}"
        )

    def _normalize_result(self, data: dict) -> dict:
        score = data.get("ai_score", 0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        score = max(-2.0, min(2.0, score))
        conf = data.get("confidence", 0.5)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        return {
            "summary": str(data.get("summary") or "").strip(),
            "ai_score": round(score, 2),
            "confidence": round(conf, 2),
            "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
            "risks": data.get("risks") if isinstance(data.get("risks"), list) else [],
            "evidence": data.get("evidence") if isinstance(data.get("evidence"), list) else [],
            "raw": data,
        }

    def _chat_json(self, user: str, clients: Optional[List[Any]] = None) -> dict:
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY")
        import httpx

        payload = {
            "model": self.nlp.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": FORM_AI_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0.55,
        }
        # 讀取逾時只在「完全沒有位元組」時生效。閘道若持續送 HTTP/2 心跳，
        # 這個逾時不會響。呼叫端要保留 client，超時時主動 close 才能打斷。
        client = httpx.Client(
            timeout=httpx.Timeout(connect=15.0, read=60.0, write=20.0, pool=15.0)
        )
        if clients is not None:
            clients.append(client)
        try:
            resp = client.post(
                self.nlp.base_url, headers=self.nlp._headers(), json=payload
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        finally:
            if clients is None:
                client.close()
        parsed = self.nlp._parse_content(content)
        if "ai_score" not in parsed and "summary" not in parsed:
            parsed = {
                "summary": parsed.get("reason") or content[:200],
                "ai_score": 0,
                "confidence": 0.2,
                "tags": [],
                "risks": ["輸出格式異常"],
                "evidence": [],
            }
        return parsed

    def analyze_one(
        self,
        race_meta: dict,
        row: pd.Series,
        form_text: str,
        clients: Optional[List[Any]] = None,
    ) -> dict:
        user = self.build_user_payload(race_meta, row, form_text)
        parsed = self._chat_json(user, clients)
        result = self._normalize_result(parsed)
        if summary_leaks_internal(result["summary"]):
            parsed = self._chat_json(
                user + "\n上一則 summary 寫了內部分數或系統用語。請重寫 summary，只留跑法和一個形勢判斷。",
                clients,
            )
            result = self._normalize_result(parsed)
        result["summary"] = fit_public_summary(result["summary"])
        if summary_leaks_internal(result["summary"]):
            kept = []
            for piece in re.split(r"(?<=[。；])", result["summary"]):
                if piece and not summary_leaks_internal(piece):
                    kept.append(piece)
            result["summary"] = fit_public_summary("".join(kept))
        return result

    def save_result(self, race_id: str, horse_no: int, result: dict):
        runner_id = f"{race_id}_{horse_no}"
        tags = json.dumps(result.get("tags") or [], ensure_ascii=False)
        risks = json.dumps(result.get("risks") or [], ensure_ascii=False)
        evidence = json.dumps(result.get("evidence") or [], ensure_ascii=False)
        raw = json.dumps(result.get("raw") or result, ensure_ascii=False)
        with self.engine.begin() as conn:
            if USE_SQLITE:
                conn.execute(
                    text(
                        """
                        INSERT INTO upcoming_form_ai
                        (runner_id, race_id, horse_no, ai_score, confidence, summary,
                         tags_json, risks_json, evidence_json, raw_json)
                        VALUES (:runner_id, :race_id, :horse_no, :ai_score, :confidence, :summary,
                                :tags_json, :risks_json, :evidence_json, :raw_json)
                        ON CONFLICT(runner_id) DO UPDATE SET
                          ai_score=excluded.ai_score,
                          confidence=excluded.confidence,
                          summary=excluded.summary,
                          tags_json=excluded.tags_json,
                          risks_json=excluded.risks_json,
                          evidence_json=excluded.evidence_json,
                          raw_json=excluded.raw_json,
                          created_at=CURRENT_TIMESTAMP
                        """
                    ),
                    {
                        "runner_id": runner_id,
                        "race_id": race_id,
                        "horse_no": horse_no,
                        "ai_score": result["ai_score"],
                        "confidence": result["confidence"],
                        "summary": result["summary"],
                        "tags_json": tags,
                        "risks_json": risks,
                        "evidence_json": evidence,
                        "raw_json": raw,
                    },
                )
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO upcoming_form_ai
                        (runner_id, race_id, horse_no, ai_score, confidence, summary,
                         tags_json, risks_json, evidence_json, raw_json)
                        VALUES (:runner_id, :race_id, :horse_no, :ai_score, :confidence, :summary,
                                CAST(:tags_json AS jsonb), CAST(:risks_json AS jsonb),
                                CAST(:evidence_json AS jsonb), CAST(:raw_json AS jsonb))
                        ON CONFLICT(runner_id) DO UPDATE SET
                          ai_score=EXCLUDED.ai_score,
                          confidence=EXCLUDED.confidence,
                          summary=EXCLUDED.summary,
                          tags_json=EXCLUDED.tags_json,
                          risks_json=EXCLUDED.risks_json,
                          evidence_json=EXCLUDED.evidence_json,
                          raw_json=EXCLUDED.raw_json,
                          created_at=NOW()
                        """
                    ),
                    {
                        "runner_id": runner_id,
                        "race_id": race_id,
                        "horse_no": horse_no,
                        "ai_score": result["ai_score"],
                        "confidence": result["confidence"],
                        "summary": result["summary"],
                        "tags_json": tags,
                        "risks_json": risks,
                        "evidence_json": evidence,
                        "raw_json": raw,
                    },
                )

    def load_ai_for_race(self, race_id: str) -> pd.DataFrame:
        try:
            return pd.read_sql(
                text("SELECT * FROM upcoming_form_ai WHERE race_id = :r ORDER BY horse_no"),
                self.engine,
                params={"r": race_id},
            )
        except Exception:
            return pd.DataFrame()

    def analyze_race(
        self,
        race_id: str,
        *,
        only_missing: bool = True,
        horse_nos: Optional[List[int]] = None,
        max_horses: Optional[int] = None,
        progress_cb=None,
    ) -> Dict[str, Any]:
        pred, info, meta = self.infer.predict_race(race_id)
        if pred is None or pred.empty:
            return {"ok": False, "error": "無推論結果", "done": 0}

        race_meta = info.to_dict() if hasattr(info, "to_dict") else (dict(info) if info is not None else {})
        race_meta["race_id"] = race_id

        forms = self.load_formguide(race_id)
        form_map = {}
        if not forms.empty:
            for _, f in forms.iterrows():
                form_map[int(f["horse_no"])] = f.get("form_text") or ""

        existing = set()
        if only_missing:
            cur = self.load_ai_for_race(race_id)
            if not cur.empty:
                existing = set(cur["horse_no"].astype(int).tolist())

        work = []
        for _, row in pred.iterrows():
            hno = int(row["馬號"])
            if horse_nos and hno not in horse_nos:
                continue
            if only_missing and hno in existing:
                continue
            work.append(row)

        budget_hit = False
        if max_horses is not None and max_horses >= 0 and len(work) > int(max_horses):
            work = work[: int(max_horses)]
            budget_hit = True

        done = 0
        errors = []
        total = len(work)
        if progress_cb and total == 0:
            progress_cb(0, 0, None, None)

        horse_timeout = float(os.getenv("FORM_AI_HORSE_TIMEOUT_SEC", "90") or 90)
        horse_timeout = max(15.0, horse_timeout)

        for row in work:
            hno = int(row["馬號"])
            try:
                from concurrent.futures import ThreadPoolExecutor
                from concurrent.futures import TimeoutError as FuturesTimeout

                clients: List[Any] = []
                pool = ThreadPoolExecutor(max_workers=1)
                fut = pool.submit(
                    self.analyze_one, race_meta, row, form_map.get(hno, ""), clients
                )
                try:
                    res = fut.result(timeout=horse_timeout)
                except FuturesTimeout:
                    raise TimeoutError(
                        f"單馬超時 {int(horse_timeout)}s（FORM_AI_HORSE_TIMEOUT_SEC）"
                    )
                finally:
                    # 不要 with Executor：超時後 shutdown(wait=True) 會等那條卡住的請求，整場停住。
                    for client in list(clients):
                        try:
                            client.close()
                        except Exception:
                            pass
                    pool.shutdown(wait=False, cancel_futures=True)
                self.save_result(race_id, hno, res)
                done += 1
                if progress_cb:
                    progress_cb(done, total, hno, res)
            except Exception as e:
                errors.append({"horse_no": hno, "error": str(e)})
                if progress_cb:
                    # 失敗也推進度，避免卡住視覺
                    progress_cb(done + len(errors), total, hno, {"ai_score": None, "summary": str(e)})
        return {
            "ok": True,
            "done": done,
            "skipped": int(len(pred) - total) if only_missing else 0,
            "total": total,
            "errors": errors,
            "race_id": race_id,
            "budget_hit": budget_hit,
        }
