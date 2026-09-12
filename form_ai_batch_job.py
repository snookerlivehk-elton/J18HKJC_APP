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

# 勿 override=True：Railway／容器已注入的 DATABASE_URL／OPENAI_* 不能被映像內 .env 蓋掉，
# 否則背景子進程會寫錯庫，父進程 background_jobs 永遠停在 phase=spawned。
load_dotenv(override=False)

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH, resolve_database_url

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = resolve_database_url()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_is_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 行程存在但無權發訊號 → 視為仍在
        return True
    except OSError:
        return False
    return True


def _as_progress(job: Optional[dict]) -> Dict[str, Any]:
    if not job:
        return {}
    prog = job.get("progress_json") or {}
    if isinstance(prog, str):
        try:
            prog = json.loads(prog)
        except Exception:
            prog = {}
    return prog if isinstance(prog, dict) else {}


def _tail_log(path: Any, *, max_chars: int = 800) -> str:
    try:
        p = str(path or "")
        if not p or not os.path.isfile(p):
            return ""
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 2000), os.SEEK_SET)
            raw = f.read().decode("utf-8", errors="replace")
        return raw[-max_chars:].replace("\n", " | ").strip()
    except Exception:
        return ""


def _job_age_seconds(job: dict) -> Optional[float]:
    """用 updated_at／created_at 計年齡（秒）；解析失敗回傳 None。"""
    raw = job.get("updated_at") or job.get("created_at")
    if raw is None:
        return None
    try:
        if isinstance(raw, datetime):
            ts = raw
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
        s = str(raw).strip().replace("Z", "+00:00")
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def _pid_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return f.read().decode("utf-8", errors="replace").replace("\x00", " ").strip()
    except Exception:
        return ""


def _pid_looks_like_form_ai(pid: int, job_id: str = "") -> bool:
    cmd = _pid_cmdline(pid).lower()
    if not cmd:
        return False
    if "form_ai_batch_job" not in cmd and "form_ai_batch" not in cmd:
        return False
    if job_id and job_id.lower() not in cmd:
        # cmdline 未必帶 job-id；有 script 名已足夠
        pass
    return True


def reconcile_running_job(engine, job: Optional[dict]) -> Optional[dict]:
    """
    清掉殭屍 running 任務。

    Railway 上 Web／APP-CORN 唔同容器，單靠 PID 存活會誤判（PID 重用或他容器 PID）。
    因此以年齡／心跳為主，PID 只作同容器輔助：
      - phase 仍係 spawned／booting 且超過 FORM_AI_SPAWNED_STALE_SEC（預設 120s）→ failed
      - 寬限內唔用 PID 判死（避免剛由 CORN 啟動、Web 刷新就誤殺）
      - phase=running 但 updated_at 超過 FORM_AI_RUNNING_STALE_SEC（預設 45min）無心跳 → failed
      - 同容器且 cmdline 明顯唔似 form_ai_batch_job（逾短門檻）→ failed
    """
    if not job:
        return job
    if str(job.get("status") or "") != "running":
        return job
    job_id = str(job.get("job_id") or "")
    if not job_id:
        return job

    prog = _as_progress(job)
    phase = str(prog.get("phase") or "").strip().lower() or "unknown"
    age = _job_age_seconds(job)
    # 預設 2 分鐘：spawned 太久無 booting／running 心跳即當殭屍（跨容器唔好信 PID）
    spawned_stale = int(os.getenv("FORM_AI_SPAWNED_STALE_SEC", "120") or 120)
    running_stale = int(os.getenv("FORM_AI_RUNNING_STALE_SEC", str(45 * 60)) or 45 * 60)

    pid_raw = prog.get("pid")
    try:
        pid = int(pid_raw) if pid_raw is not None else None
    except (TypeError, ValueError):
        pid = None

    stale_reason = ""
    if phase in ("spawned", "booting", "dead", "unknown"):
        if age is None or age >= spawned_stale:
            age_s = "未知" if age is None else f"{int(age)}s"
            stale_reason = (
                f"phase={phase} 已 {age_s} 無進入 running"
                f"（門檻 {spawned_stale}s；跨容器 PID 不可靠，視作殭屍）"
            )
        else:
            # 寬限內：等 worker 打 booting／running 心跳，唔好因他容器 PID 誤殺
            return job
    elif phase == "running" and age is not None and age >= running_stale:
        stale_reason = f"phase=running 但 {int(age)}s 無進度心跳（門檻 {running_stale}s）"
    elif pid is not None and _pid_is_alive(pid) and not _pid_looks_like_form_ai(
        pid, job_id
    ):
        # 同容器 PID 重用：進程在但唔係 Form AI（要過短門檻先殺，避免誤判）
        if age is not None and age >= min(60, spawned_stale):
            stale_reason = (
                f"pid={pid} 仍在但 cmdline 不像 form_ai_batch_job"
                f"（可能 PID 重用）；age={int(age)}s"
            )
    elif pid is None and age is not None and age >= spawned_stale:
        stale_reason = f"無 pid 且已 {int(age)}s 仍 running"

    if not stale_reason:
        return job

    log_tail = _tail_log(prog.get("log"))
    detail = f"後台任務已視為中斷：{stale_reason}。"
    if log_tail:
        detail = f"{detail} log: {log_tail}"

    update_job(
        engine,
        job_id,
        status="failed",
        detail=detail[:1500],
        progress={
            **prog,
            "phase": "dead",
            "reconciled": True,
            "stale_reason": stale_reason,
        },
        finished=True,
    )
    return get_job(engine, job_id)


def force_fail_job(
    engine,
    job_id: str,
    *,
    detail: str = "人手標記失敗／強制解除 running",
) -> Optional[dict]:
    job = get_job(engine, job_id)
    prog = _as_progress(job) if job else {}
    update_job(
        engine,
        job_id,
        status="failed",
        detail=detail[:1500],
        progress={**prog, "phase": "force_failed", "reconciled": True},
        finished=True,
    )
    return get_job(engine, job_id)


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

    # 盡早打心跳，避免父進程只見 phase=spawned；跨容器 reconcile 靠呢個
    update_job(
        engine,
        job_id,
        status="running",
        detail="booting Form AI worker",
        progress={
            "phase": "booting",
            "pid": os.getpid(),
            "racing_date": racing_date[:10],
            "course": course.upper(),
        },
    )

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

    try:
        out = run_meeting(
            racing_date,
            course,
            only_missing=only_missing,
            sleep=args.sleep,
            job_id=job_id,
        )
    except Exception as e:
        traceback.print_exc()
        try:
            update_job(
                engine,
                job_id,
                status="failed",
                detail=f"crash: {e}",
                progress={"phase": "crash", "error": str(e)},
                finished=True,
            )
        except Exception:
            pass
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if not out.get("ok"):
        print(f"ERROR: {out.get('error')}", file=sys.stderr)
        return 1
    return 0 if int(out.get("errors") or 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
