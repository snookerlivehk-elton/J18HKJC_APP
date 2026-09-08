"""廣告輸出 — 全賽日模型／AI 各一張海報（固定檔名覆蓋）。"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ad_poster import (
    default_output_dir,
    generate_ads_from_snapshot_batch,
    latest_paths,
    load_copy_json,
    make_preview_jpeg,
    zip_batch_bytes,
)
from factor_calibration import FactorCalibration

st.title("廣告輸出")
st.caption(
    "每次預測快照成功後，系統把**全賽日**推介寫入兩張海報："
    "模型 · 勝率份額、AI 馬評 · 份額。下次生成會**覆蓋**同一檔名；單張目標 ≤800KB。"
)

out_root = default_output_dir()
paths = latest_paths(out_root)
st.info(f"輸出：`{paths['model'].name}` / `{paths['ai'].name}` @ `{out_root}`")
try:
    from ad_poster import font_status, _max_bytes

    fs = font_status()
    if fs.get("ok"):
        st.caption(f"字型：`{fs.get('path')}` · 上限 {_max_bytes() // 1024} KB／張")
    else:
        st.error(f"CJK 字型不可用：{fs.get('error') or '未找到字型檔'}")
except Exception as e:
    st.warning(f"字型檢查失敗：{e}")

tab_browse, tab_regen = st.tabs(["瀏覽輸出", "手動重產"])

with tab_browse:
    has_any = paths["model"].is_file() or paths["ai"].is_file()
    if not has_any:
        st.warning("尚無海報。請先完成預測快照，或使用「手動重產」。")
    else:
        copy = load_copy_json(out_root)
        meeting = (copy or {}).get("meeting") or {}
        if meeting:
            st.write(
                f"**{meeting.get('racing_date', '')} {meeting.get('course', '')}** · "
                f"{meeting.get('n_races', '?')} 場 · batch `{meeting.get('batch_id', '')}`"
            )
            mb = meeting.get("model_bytes")
            ab = meeting.get("ai_bytes")
            if mb or ab:
                st.caption(
                    f"檔案大小：模型 {int(mb or 0) // 1024} KB · AI {int(ab or 0) // 1024} KB"
                )

        try:
            st.download_button(
                "下載 ZIP（model + ai + copy）",
                data=zip_batch_bytes(out_root),
                file_name="ad_output_latest.zip",
                mime="application/zip",
                key="zip_latest",
            )
        except Exception as e:
            st.caption(f"ZIP 失敗：{e}")

        cols = st.columns(2)
        for col, label, key in (
            (cols[0], "模型 · 全賽日", "model"),
            (cols[1], "AI 馬評 · 全賽日", "ai"),
        ):
            with col:
                st.markdown(f"**{label}**")
                p = paths[key]
                if p.is_file():
                    try:
                        st.image(
                            make_preview_jpeg(p),
                            caption=f"{p.name} · {p.stat().st_size // 1024} KB",
                            use_container_width=True,
                        )
                    except Exception as e:
                        st.warning(f"預覽失敗：{e}")
                    with open(p, "rb") as f:
                        st.download_button(
                            f"下載 {p.name}",
                            data=f.read(),
                            file_name=p.name,
                            mime="image/jpeg",
                            key=f"dl_{key}",
                        )
                else:
                    st.warning("尚無檔案")

        if copy:
            with st.expander("宣傳文案", expanded=False):
                st.markdown("**模型**")
                st.write(copy.get("model_copy") or "")
                st.markdown("**AI 馬評**")
                st.write(copy.get("ai_copy") or "")

with tab_regen:
    st.markdown("選擇預測快照批次，依鎖分重產全賽日海報（覆蓋 `model.jpg` / `ai.jpg`）。")
    cal = FactorCalibration()
    try:
        bdf = cal.list_batches()
    except Exception as e:
        bdf = None
        st.error(f"讀取快照批次失敗：{e}")
    if bdf is not None and bdf.empty:
        st.warning("尚無預測快照批次")
    elif bdf is not None:
        opts = {
            f"{r.batch_id} · {str(r.racing_date)[:10]} {r.course} · rows={int(r.n_rows)}": str(
                r.batch_id
            )
            for r in bdf.itertuples()
        }
        blabel = st.selectbox("預測批次", list(opts.keys()), key="ad_regen_batch")
        bid = opts[blabel]
        if st.button("重新生成廣告輸出", type="primary", key="ad_regen_go"):
            with st.spinner("生成全賽日海報…"):
                try:
                    result = generate_ads_from_snapshot_batch(bid, output_root=out_root)
                    st.session_state["ad_last_result"] = result
                    if result.get("ok") or result.get("races_written"):
                        st.success(
                            f"完成：{result.get('races_written', 0)} 場合入 2 張海報 · "
                            f"模型 {int(result.get('model_bytes') or 0) // 1024} KB / "
                            f"AI {int(result.get('ai_bytes') or 0) // 1024} KB · `{result.get('output_dir')}`"
                        )
                        st.info("請切到「瀏覽輸出」查看或下載。")
                    else:
                        st.error(result.get("error") or "重產失敗")
                    errs = result.get("errors") or []
                    if errs:
                        st.warning(
                            "部分錯誤："
                            + "；".join(
                                f"{e.get('race_id')}: {e.get('error')}" for e in errs[:5]
                            )
                        )
                except Exception as e:
                    st.error(f"重產失敗：{e}")

        last = st.session_state.get("ad_last_result")
        if last and last.get("model_file"):
            st.caption(
                f"最近：`{Path(last['model_file']).name}` / `{Path(last.get('ai_file') or '').name}`"
            )
