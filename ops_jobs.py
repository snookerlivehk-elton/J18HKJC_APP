"""
通用後台任務啟動器（不依賴 Streamlit 長連線）。

job_type:
  - form_ai          → form_ai_batch_job.py（既有）
  - ad_regen         → 依 snapshot batch 重產海報
  - nlp_meeting      → 整個賽日 NLP 解析（待解析報告）
  - factors_nlp      → run_all_factors(apply_nlp=True)
  - hit_snapshot_bf  → 補回命中率日快照

用法：
  python ops_jobs.py --type ad_regen --batch 20260906ST_xxx
  python ops_jobs.py --type nlp_meeting --date 2026-09-06 --course ST --job-id xxx
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(override=True)

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH, resolve_database_url
import form_ai_batch_job as faj

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = resolve_database_url()
    if DATABASE_URL_SYNC.startswith("postgres://"):
        DATABASE_URL_SYNC = DATABASE_URL_SYNC.replace("postgres://", "postgresql://", 1)


def _engine():
    return create_engine(DATABASE_URL_SYNC)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_background_job(
    *,
    job_type: str,
    racing_date: str = "",
    course: str = "",
    extra_args: Optional[list] = None,
    detail: str = "",
) -> Dict[str, Any]:
    """
    建立 background_jobs 列並 Popen ops_jobs.py（或 form_ai_batch_job）。
    關閉瀏覽器不中斷。
    """
    eng = _engine()
    faj.ensure_jobs_table(eng)
    # 同類型 running 防重
    latest = faj.latest_job(
        eng,
        job_type=job_type,
        racing_date=racing_date[:10] if racing_date else None,
        course=course.upper() if course else None,
    )
    if latest and str(latest.get("status") or "") == "running":
        return {
            "ok": False,
            "error": f"已有 {job_type} 進行中",
            "job_id": latest.get("job_id"),
            "job": latest,
        }

    job_id = faj.create_job(
        eng,
        job_type=job_type,
        racing_date=(racing_date or "")[:10] or "1970-01-01",
        course=(course or "NA").upper(),
        detail=detail or f"ops_jobs {job_type}",
    )
    root = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(root, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = "/tmp"
    log_path = os.path.join(log_dir, f"{job_type}_{job_id}.log")

    if job_type == "form_ai":
        cmd = [
            sys.executable,
            "form_ai_batch_job.py",
            "--date",
            racing_date[:10],
            "--course",
            course.upper(),
            "--job-id",
            job_id,
        ]
    else:
        cmd = [
            sys.executable,
            "ops_jobs.py",
            "--type",
            job_type,
            "--job-id",
            job_id,
        ]
        if racing_date:
            cmd += ["--date", racing_date[:10]]
        if course:
            cmd += ["--course", course.upper()]
        if extra_args:
            cmd += list(extra_args)

    env = os.environ.copy()
    try:
        with open(log_path, "ab", buffering=0) as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        faj.update_job(
            eng,
            job_id,
            status="running",
            detail=f"pid={proc.pid} log={log_path}",
            progress={"phase": "spawned", "pid": proc.pid, "log": log_path},
        )
        return {
            "ok": True,
            "job_id": job_id,
            "pid": proc.pid,
            "log_path": log_path,
            "message": "已後台啟動；可關閉本頁，稍後重新整理進度",
        }
    except Exception as e:
        faj.update_job(eng, job_id, status="failed", detail=str(e), finished=True)
        return {"ok": False, "error": str(e), "job_id": job_id}


def get_job(job_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    eng = _engine()
    faj.ensure_jobs_table(eng)
    if job_id:
        job = faj.get_job(eng, job_id)
    else:
        job = faj.latest_job(eng, **kwargs)
    return {"ok": True, "job": job}


def _run_ad_regen(eng, job_id: str, batch_id: str) -> Dict[str, Any]:
    from ad_poster import default_output_dir, generate_ads_from_snapshot_batch

    faj.update_job(
        eng, job_id, status="running", progress={"phase": "ad_regen", "batch_id": batch_id}
    )
    result = generate_ads_from_snapshot_batch(batch_id)
    ok = bool(result.get("ok") or result.get("races_written"))

    # 海報後自動產 AI 文案並 publish ready 包（寫 DB + 可選推送生產 Ad API）
    social_out: Dict[str, Any] = {}
    pkg_out: Dict[str, Any] = {}
    if ok:
        try:
            faj.update_job(
                eng,
                job_id,
                status="running",
                progress={"phase": "ad_social", "batch_id": batch_id},
            )
            from ad_copy_jobs import run_auto_social_copy
            from ad_package import publish_ad_package_after_outputs
            from ad_poster import load_copy_json

            out_root = default_output_dir()
            copy = load_copy_json(out_root) or {}
            meeting = copy.get("meeting") or {}
            d = str(meeting.get("racing_date") or "")[:10]
            c = str(meeting.get("course") or "").upper()
            if d and c:
                social_out = run_auto_social_copy(
                    racing_date=d, course=c, batch_id=str(batch_id), force=True
                )
            pkg_out = publish_ad_package_after_outputs(
                output_root=out_root, notify=True
            )
            result["social_copy"] = {
                k: social_out.get(k)
                for k in (
                    "ok",
                    "error",
                    "waiting",
                    "skipped",
                    "n_featured",
                    "source",
                    "ad_package",
                    "batch_id",
                )
                if k in social_out
            }
            result["ad_package"] = {
                k: pkg_out.get(k) for k in ("ok", "id", "status", "error") if k in pkg_out
            }
        except Exception as exc:
            result["social_copy"] = {"ok": False, "error": str(exc)}

    faj.update_job(
        eng,
        job_id,
        status="ok" if ok else "failed",
        detail=json.dumps(
            {
                k: result.get(k)
                for k in (
                    "ok",
                    "races_written",
                    "error",
                    "fused_bytes",
                    "primary_track_label",
                    "files_written",
                    "social_copy",
                    "ad_package",
                )
                if k in result or result.get(k)
            },
            ensure_ascii=False,
        )[:1800],
        progress={
            "phase": "done",
            "result": {
                k: result.get(k)
                for k in (
                    "ok",
                    "races_written",
                    "error",
                    "primary_track_label",
                    "social_copy",
                    "ad_package",
                )
            },
        },
        finished=True,
    )
    return result


def _run_nlp_meeting(eng, job_id: str, racing_date: str, course: str) -> Dict[str, Any]:
    from factor_calculator import FactorCalculator
    from nlp_processor import NLPProcessor
    from inference_engine import InferenceEngine

    calc = FactorCalculator()
    nlp = NLPProcessor()
    if not nlp.is_ready():
        out = {"ok": False, "error": "OPENAI_API_KEY 未設定"}
        faj.update_job(eng, job_id, status="failed", detail=out["error"], finished=True)
        return out

    races = InferenceEngine().get_upcoming_races()
    if races is None or races.empty:
        # 歷史賽日：用 race_id 前綴掃 text_reports 待解析
        race_ids = []
    else:
        races = races[
            (races["racing_date"].astype(str).str[:10] == racing_date[:10])
            & (races["course"].astype(str) == course.upper())
        ]
        race_ids = [str(x) for x in races["race_id"].tolist()]

    faj.update_job(
        eng,
        job_id,
        status="running",
        progress={"phase": "load", "race_count": len(race_ids)},
    )
    if race_ids:
        related = calc.load_reports_for_upcoming_race(
            race_ids, lookback_days=360, only_unprocessed=True
        )
    else:
        related = calc.load_unprocessed_reports(limit=80, skip_trivial=True)

    if related is None or related.empty:
        faj.update_job(
            eng, job_id, status="ok", detail="無待解析報告", progress={"phase": "done", "parsed": 0}, finished=True
        )
        return {"ok": True, "parsed": 0, "skipped": 0}

    skipped = 0
    if "is_trivial" in related.columns:
        trivial_ids = related.loc[related["is_trivial"], "id"].tolist()
        if trivial_ids:
            skipped = calc.mark_trivial_reports_skipped(report_ids=trivial_ids)
        if "needs_llm" in related.columns:
            to_llm = related.loc[related["needs_llm"]].copy()
        else:
            to_llm = related.loc[~related["is_trivial"]].copy()
    else:
        to_llm = related.copy()

    done = 0
    errors = 0
    total = len(to_llm)
    for i, (_, row) in enumerate(to_llm.iterrows(), start=1):
        faj.update_job(
            eng,
            job_id,
            progress={
                "phase": "nlp",
                "done": i - 1,
                "total": total,
                "report_id": int(row["id"]) if "id" in row else None,
            },
        )
        try:
            parsed = nlp.analyze_report_sync(str(row.get("report_text") or ""))
            calc.save_nlp_result(int(row["id"]), parsed)
            done += 1
        except Exception:
            errors += 1
    out = {"ok": True, "parsed": done, "errors": errors, "skipped": skipped, "total": total}
    faj.update_job(
        eng,
        job_id,
        status="ok" if errors == 0 else "ok_with_errors",
        detail=json.dumps(out, ensure_ascii=False),
        progress={"phase": "done", **out},
        finished=True,
    )
    return out


def _run_factors_nlp(eng, job_id: str) -> Dict[str, Any]:
    from factor_calculator import FactorCalculator

    faj.update_job(eng, job_id, status="running", progress={"phase": "factors"})
    calc = FactorCalculator()
    result = calc.run_all_factors(persist=True, apply_nlp=True)
    ok = result is not None and result[0] is not None
    out = {"ok": ok, "msg": "已重算 factor_scores（含 NLP／干擾）" if ok else "無歷史或失敗"}
    faj.update_job(
        eng,
        job_id,
        status="ok" if ok else "failed",
        detail=out["msg"],
        progress={"phase": "done", **out},
        finished=True,
    )
    return out


def _run_hit_snapshot_bf(eng, job_id: str, only_missing: bool) -> Dict[str, Any]:
    from factor_calibration import FactorCalibration

    faj.update_job(eng, job_id, status="running", progress={"phase": "backfill"})
    out = FactorCalibration().backfill_hit_rate_snapshots(only_missing=only_missing)
    faj.update_job(
        eng,
        job_id,
        status="ok" if out.get("ok") else "failed",
        detail=json.dumps(
            {k: out.get(k) for k in ("n_done", "n_skip", "ok")}, ensure_ascii=False
        ),
        progress={"phase": "done", **{k: out.get(k) for k in ("n_done", "n_skip")}},
        finished=True,
    )
    return out


def run_worker(
    *,
    job_type: str,
    job_id: str,
    racing_date: str = "",
    course: str = "",
    batch_id: str = "",
    only_missing: bool = True,
) -> Dict[str, Any]:
    eng = _engine()
    faj.ensure_jobs_table(eng)
    faj.update_job(eng, job_id, status="running", progress={"phase": "start"})
    try:
        if job_type == "ad_regen":
            if not batch_id:
                raise ValueError("--batch required for ad_regen")
            return _run_ad_regen(eng, job_id, batch_id)
        if job_type == "nlp_meeting":
            return _run_nlp_meeting(eng, job_id, racing_date, course)
        if job_type == "factors_nlp":
            return _run_factors_nlp(eng, job_id)
        if job_type == "hit_snapshot_bf":
            return _run_hit_snapshot_bf(eng, job_id, only_missing)
        raise ValueError(f"unknown job_type {job_type}")
    except Exception as e:
        faj.update_job(
            eng,
            job_id,
            status="failed",
            detail=f"{e}\n{traceback.format_exc()[-1500:]}",
            finished=True,
        )
        return {"ok": False, "error": str(e)}


def build_arg_parser():
    p = argparse.ArgumentParser(description="Ops background jobs")
    p.add_argument("--type", required=True, choices=[
        "ad_regen", "nlp_meeting", "factors_nlp", "hit_snapshot_bf", "form_ai"
    ])
    p.add_argument("--job-id", default="")
    p.add_argument("--date", default="")
    p.add_argument("--course", default="")
    p.add_argument("--batch", default="")
    p.add_argument("--all", action="store_true", help="hit_snapshot_bf: 覆寫全部")
    p.add_argument("--spawn", action="store_true", help="只啟動後台，不在前景跑")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.spawn:
        extra = []
        if args.batch:
            extra += ["--batch", args.batch]
        if args.all:
            extra += ["--all"]
        out = start_background_job(
            job_type=args.type,
            racing_date=args.date,
            course=args.course,
            extra_args=extra,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1

    job_id = args.job_id or uuid4().hex[:16]
    if not args.job_id:
        eng = _engine()
        faj.ensure_jobs_table(eng)
        faj.create_job(
            eng,
            job_type=args.type,
            racing_date=(args.date or "1970-01-01")[:10],
            course=(args.course or "NA").upper(),
            detail="cli foreground",
        )
        # create_job 產生新 id；若未傳 job-id 用 spawn 路徑較佳
    out = run_worker(
        job_type=args.type,
        job_id=job_id,
        racing_date=args.date,
        course=args.course,
        batch_id=args.batch,
        only_missing=not args.all,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
