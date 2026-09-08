"""
Form AI 批次任務（可背景跑，不依賴 Streamlit 保持連線）。

用法：
  python form_ai_batch_job.py --date 2026-09-06 --course ST
  python form_ai_batch_job.py --date 2026-09-06 --course ST --all
  python form_ai_batch_job.py --date 2026-09-06 --course ST --job-id <uuid>

寫入 upcoming_form_ai；若帶 --job-id 會更新 background_jobs 進度。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(override=True)

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_jobs_table(engine) -> None:
    if USE_SQLITE:
        ddl = """
        CREATE TABLE IF NOT EXISTS background_jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            racing_date TEXT,
            course TEXT,
            status TEXT DEFAULT 'queued',
            detail TEXT,
            progress_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            finished_at TEXT
        )
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS background_jobs (
            job_id VARCHAR(64) PRIMARY KEY,
            job_type VARCHAR(40) NOT NULL,
            racing_date DATE,
            course VARCHAR(10),
            status VARCHAR(20) DEFAULT 'queued',
            detail TEXT,
            progress_json JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """
    with engine.begin() as conn:
        conn.execute(text(ddl))


def update_job(
    engine,
    job_id: Optional[str],
    *,
    status: Optional[str] = None,
    detail: Optional[str] = None,
    progress: Optional[Dict[str, Any]] = None,
    finished: bool = False,
) -> None:
    if not job_id:
        return
    ensure_jobs_table(engine)
    fields = ["updated_at = :u"]
    params: Dict[str, Any] = {"u": _now(), "id": job_id}
    if status is not None:
        fields.append("status = :st")
        params["st"] = status
    if detail is not None:
        fields.append("detail = :d")
        params["d"] = detail
    if progress is not None:
        fields.append("progress_json = :p")
        params["p"] = json.dumps(progress, ensure_ascii=False)
    if finished:
        fields.append("finished_at = :f")
        params["f"] = _now()
    sql = f"UPDATE background_jobs SET {', '.join(fields)} WHERE job_id = :id"
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def create_job(
    engine,
    *,
    job_type: str,
    racing_date: str,
    course: str,
    detail: str = "",
) -> str:
    ensure_jobs_table(engine)
    job_id = uuid4().hex[:16]
    with engine.begin() as conn:
        if USE_SQLITE:
            conn.execute(
                text(
                    """
                    INSERT INTO background_jobs
                      (job_id, job_type, racing_date, course, status, detail, progress_json, created_at, updated_at)
                    VALUES
                      (:id, :t, :d, :c, 'queued', :detail, :p, :ts, :ts)
                    """
                ),
                {
                    "id": job_id,
                    "t": job_type,
                    "d": racing_date[:10],
                    "c": course,
                    "detail": detail,
                    "p": json.dumps({"phase": "queued"}),
                    "ts": _now(),
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO background_jobs
                      (job_id, job_type, racing_date, course, status, detail, progress_json, created_at, updated_at)
                    VALUES
                      (:id, :t, CAST(:d AS DATE), :c, 'queued', :detail, CAST(:p AS jsonb), NOW(), NOW())
                    """
                ),
                {
                    "id": job_id,
                    "t": job_type,
                    "d": racing_date[:10],
                    "c": course,
                    "detail": detail,
                    "p": json.dumps({"phase": "queued"}),
                },
            )
    return job_id


def get_job(engine, job_id: str) -> Optional[dict]:
    ensure_jobs_table(engine)
    try:
        import pandas as pd

        df = pd.read_sql(
            text("SELECT * FROM background_jobs WHERE job_id = :id"),
            engine,
            params={"id": job_id},
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        prog = row.get("progress_json")
        if isinstance(prog, str):
            try:
                row["progress_json"] = json.loads(prog)
            except Exception:
                pass
        return row
    except Exception:
        return None


def latest_job(
    engine,
    *,
    job_type: str = "form_ai",
    racing_date: Optional[str] = None,
    course: Optional[str] = None,
) -> Optional[dict]:
    ensure_jobs_table(engine)
    try:
        import pandas as pd

        q = "SELECT * FROM background_jobs WHERE job_type = :t"
        params: Dict[str, Any] = {"t": job_type}
        if racing_date:
            q += " AND CAST(racing_date AS TEXT) LIKE :d"
            params["d"] = racing_date[:10] + "%"
        if course:
            q += " AND course = :c"
            params["c"] = course
        q += " ORDER BY created_at DESC"
        df = pd.read_sql(text(q), engine, params=params)
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        prog = row.get("progress_json")
        if isinstance(prog, str):
            try:
                row["progress_json"] = json.loads(prog)
            except Exception:
                pass
        return row
    except Exception:
        return None


def run_meeting(
    racing_date: str,
    course: str,
    *,
    only_missing: bool = True,
    sleep: float = 0.15,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    from form_ai_analyst import FormAIAnalyst
    from inference_engine import InferenceEngine

    engine = create_engine(DATABASE_URL_SYNC)
    ensure_jobs_table(engine)

    analyst = FormAIAnalyst()
    if not analyst.is_ready():
        update_job(engine, job_id, status="failed", detail="OPENAI_API_KEY 未設定", finished=True)
        return {"ok": False, "error": "OPENAI_API_KEY 未設定"}

    races = InferenceEngine().get_upcoming_races()
    if races is None or races.empty:
        update_job(engine, job_id, status="failed", detail="無 upcoming 賽事", finished=True)
        return {"ok": False, "error": "無 upcoming 賽事"}

    races = races.copy()
    races = races[
        (races["racing_date"].astype(str).str[:10] == racing_date[:10])
        & (races["course"].astype(str).str.upper() == course.upper())
    ]
    race_ids = [str(x) for x in races["race_id"].tolist()]
    if not race_ids:
        update_job(
            engine,
            job_id,
            status="failed",
            detail=f"找不到 {racing_date} {course} 排位",
            finished=True,
        )
        return {"ok": False, "error": f"找不到 {racing_date} {course} 排位"}

    update_job(
        engine,
        job_id,
        status="running",
        detail=f"開始 {len(race_ids)} 場",
        progress={"phase": "running", "race_count": len(race_ids), "race_index": 0, "done": 0},
    )

    total_done = 0
    total_errors = 0
    n_races = len(race_ids)

    for i, rid in enumerate(race_ids, start=1):
        print(f"[{i}/{n_races}] {rid} …", flush=True)

        def _cb(cur, tot, hno, res, _i=i, _rid=rid):
            update_job(
                engine,
                job_id,
                status="running",
                detail=f"{_rid} 馬#{hno} ({cur}/{tot})",
                progress={
                    "phase": "running",
                    "race_index": _i,
                    "race_count": n_races,
                    "race_id": _rid,
                    "horse_done": cur,
                    "horse_total": tot,
                    "horse_no": hno,
                    "done": total_done + int(cur or 0),
                },
            )

        try:
            out = analyst.analyze_race(
                rid,
                only_missing=only_missing,
                progress_cb=_cb,
            )
            total_done += int(out.get("done") or 0)
            total_errors += len(out.get("errors") or [])
            print(
                f"  done={out.get('done')} skipped={out.get('skipped')} errors={len(out.get('errors') or [])}",
                flush=True,
            )
        except Exception as e:
            total_errors += 1
            print(f"  FAIL {rid}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
            update_job(
                engine,
                job_id,
                status="running",
                detail=f"{rid} 失敗：{e}",
                progress={
                    "phase": "running",
                    "race_index": i,
                    "race_count": n_races,
                    "race_id": rid,
                    "error": str(e),
                    "done": total_done,
                },
            )
        if sleep > 0:
            time.sleep(sleep)

    final = {
        "ok": True,
        "done": total_done,
        "n_races": n_races,
        "errors": total_errors,
        "racing_date": racing_date[:10],
        "course": course.upper(),
        "only_missing": only_missing,
    }
    st = "ok" if total_errors == 0 else "ok_with_errors"
    update_job(
        engine,
        job_id,
        status=st,
        detail=f"完成：寫入 {total_done} 匹／{n_races} 場，錯誤 {total_errors}",
        progress={"phase": "done", **final},
        finished=True,
    )
    print(f"Done. wrote={total_done} races={n_races} errors={total_errors}", flush=True)
    return final


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Background Form AI batch for a meeting")
    p.add_argument("--date", required=True, help="YYYY-MM-DD or YYYY/MM/DD")
    p.add_argument("--course", required=True, choices=["ST", "HV", "st", "hv"])
    p.add_argument("--all", action="store_true", help="重跑已有結果的馬（預設只補缺）")
    p.add_argument("--sleep", type=float, default=0.15, help="每場之間間隔秒")
    p.add_argument("--job-id", default=None, help="寫入 background_jobs 的 job_id")
    p.add_argument("--create-job", action="store_true", help="若無 job-id 則自動建立一筆")
    args = p.parse_args(argv)

    racing_date = args.date.replace("/", "-")[:10]
    course = args.course.upper()
    only_missing = not args.all

    engine = create_engine(DATABASE_URL_SYNC)
    job_id = args.job_id
    if args.create_job and not job_id:
        job_id = create_job(
            engine,
            job_type="form_ai",
            racing_date=racing_date,
            course=course,
            detail="cli create-job",
        )
        print(f"job_id={job_id}", flush=True)

    out = run_meeting(
        racing_date,
        course,
        only_missing=only_missing,
        sleep=args.sleep,
        job_id=job_id,
    )
    if not out.get("ok"):
        print(f"ERROR: {out.get('error')}", file=sys.stderr)
        return 1
    return 0 if int(out.get("errors") or 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
