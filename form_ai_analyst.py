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
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )

FORM_AI_SYSTEM_PROMPT = """你是香港賽馬賽前分析師。根據「系統量化統計」與「官方賽績指引近績文字」為該馬寫評價。
嚴格輸出 JSON：
{
  "summary": "繁中 3~5 句評價（優劣、距離/跑道適性、風險）",
  "ai_score": -2.0至2.0的數字（正=看高、負=看淡、0=中性）,
  "confidence": 0.0至1.0,
  "tags": ["短標籤1","短標籤2"],
  "risks": ["風險要點"],
  "evidence": ["必須引用輸入中出現過的數字或近績事實，禁止捏造"]
}
規則：
- 不可發明未出現在輸入的名次、賠率、時間。
- 官方文字若空泛，降低 confidence，並在 risks 註明「近績資訊不足」。
- ai_score 是獨立觀點，不要只複述模型勝率高低。
"""


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
        return (
            "【場次】\n"
            + json.dumps(meta, ensure_ascii=False)
            + "\n【系統統計】\n"
            + json.dumps(stats, ensure_ascii=False)
            + "\n【官方賽績指引近績】\n"
            + (form_text or "（無）")
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

    def analyze_one(self, race_meta: dict, row: pd.Series, form_text: str) -> dict:
        user = self.build_user_payload(race_meta, row, form_text)
        # 借用 NLPProcessor 的 sync chat，但換 system prompt；user 已含完整內容
        # analyze_report_sync 會再包一層「分析以下賽馬報告」— 改直接打 API
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
            "temperature": 0.25,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                self.nlp.base_url, headers=self.nlp._headers(), json=payload
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        parsed = self.nlp._parse_content(content)
        # 若誤走受阻 schema，兜底
        if "ai_score" not in parsed and "summary" not in parsed:
            parsed = {
                "summary": parsed.get("reason") or content[:200],
                "ai_score": 0,
                "confidence": 0.2,
                "tags": [],
                "risks": ["模型輸出格式異常"],
                "evidence": [],
            }
        return self._normalize_result(parsed)

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

        done = 0
        errors = []
        total = len(work)
        if progress_cb and total == 0:
            progress_cb(0, 0, None, None)

        for row in work:
            hno = int(row["馬號"])
            try:
                res = self.analyze_one(race_meta, row, form_map.get(hno, ""))
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
        }
