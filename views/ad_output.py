"""廣告輸出 — 依預測快照生成宣傳海報 PNG + 文案。"""
from __future__ import annotations

import streamlit as st

from ad_poster import (
    default_output_dir,
    generate_ads_from_snapshot_batch,
    list_ad_batches,
    load_copy_json,
)
from factor_calibration import FactorCalibration

st.title("廣告輸出")
st.caption(
    "每次預測快照成功後，系統自動為每場生成 **模型 · 勝率份額** 與 **AI 馬評 · 份額** 兩幅 PNG，"
    "並附宣傳文案。此頁可瀏覽輸出，或依既有快照手動重產。"
)

out_root = default_output_dir()
st.info(f"輸出目錄：`{out_root}`（可用環境變數 `AD_OUTPUT_DIR` 覆寫）")
try:
    from ad_poster import font_status

    fs = font_status()
    if fs.get("ok"):
        st.caption(f"字型：`{fs.get('path')}`")
    else:
        st.error(f"CJK 字型不可用：{fs.get('error') or '未找到 assets/fonts/wqy-microhei.ttc'}")
except Exception as e:
    st.warning(f"字型檢查失敗：{e}")

tab_browse, tab_regen = st.tabs(["瀏覽輸出", "手動重產"])

with tab_browse:
    batches = list_ad_batches(out_root)
    if not batches:
        st.warning("尚無廣告輸出。請先在作戰室／校正台完成預測快照，或使用「手動重產」。")
    else:
        labels = {
            b: f"{b} · {len(list((out_root / b).glob('*.png')))} PNG"
            for b in batches
        }
        pick = st.selectbox("批次", batches, format_func=lambda x: labels.get(x, x))
        bdir = out_root / pick
        copy = load_copy_json(bdir)
        if copy:
            st.subheader("宣傳文案")
            meeting = copy.get("meeting") or {}
            if meeting:
                st.json(meeting)
            for r in copy.get("races") or []:
                with st.expander(
                    f"R{r.get('race_no')} · {r.get('race_name') or ''} · {r.get('distance') or ''}m",
                    expanded=False,
                ):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**模型推介文案**")
                        st.write(r.get("model_copy") or "")
                        st.caption(r.get("model_file") or "")
                    with c2:
                        st.markdown("**AI 馬評推介文案**")
                        st.write(r.get("ai_copy") or "")
                        st.caption(r.get("ai_file") or "")

        pngs = sorted(bdir.glob("*.png"))
        if pngs:
            st.subheader("海報預覽")
            for i in range(0, len(pngs), 2):
                cols = st.columns(2)
                for j, col in enumerate(cols):
                    if i + j >= len(pngs):
                        break
                    p = pngs[i + j]
                    with col:
                        st.image(str(p), caption=p.name, use_container_width=True)
                        with open(p, "rb") as f:
                            st.download_button(
                                f"下載 {p.name}",
                                data=f.read(),
                                file_name=p.name,
                                mime="image/png",
                                key=f"dl_{pick}_{p.name}",
                            )

with tab_regen:
    st.markdown("選擇已寫入的預測快照批次，依鎖分重產廣告海報（不重跑推論）。")
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
            with st.spinner("生成中…"):
                try:
                    result = generate_ads_from_snapshot_batch(bid, output_root=out_root)
                    if result.get("ok") or result.get("races_written"):
                        st.success(
                            f"完成：{result.get('races_written', 0)} 場 · "
                            f"{result.get('files_written', 0)} 檔 · `{result.get('output_dir')}`"
                        )
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
