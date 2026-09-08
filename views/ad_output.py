"""廣告輸出 — 依預測快照生成宣傳海報 JPEG + 文案。"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ad_poster import (
    default_output_dir,
    generate_ads_from_snapshot_batch,
    list_ad_batches,
    list_batch_images,
    load_copy_json,
    make_preview_jpeg,
    zip_batch_bytes,
)
from factor_calibration import FactorCalibration

st.title("廣告輸出")
st.caption(
    "每次預測快照成功後，系統自動為每場生成 **模型 · 勝率份額** 與 **AI 馬評 · 份額** 兩幅海報，"
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

st.caption(
    "說明：海報存於伺服器本機目錄。Railway 重佈署後檔案可能消失，請用「手動重產」或下載 ZIP 備份。"
)

tab_browse, tab_regen = st.tabs(["瀏覽輸出", "手動重產"])

with tab_browse:
    batches = list_ad_batches(out_root)
    prefer = st.session_state.get("ad_last_batch")
    if prefer and prefer in batches:
        batches = [prefer] + [b for b in batches if b != prefer]

    if not batches:
        st.warning("尚無廣告輸出。請先在作戰室／校正台完成預測快照，或使用「手動重產」。")
    else:
        labels = {
            b: f"{b} · {len(list_batch_images(out_root / b))} 圖"
            for b in batches
        }
        pick = st.selectbox(
            "批次",
            batches,
            format_func=lambda x: labels.get(x, x),
            key="ad_browse_batch",
        )
        bdir = out_root / pick
        imgs = list_batch_images(bdir)
        st.write(f"目錄 `{bdir}` · **{len(imgs)}** 張海報")

        try:
            zbytes = zip_batch_bytes(bdir)
            st.download_button(
                "下載整批 ZIP（海報＋文案）",
                data=zbytes,
                file_name=f"{pick}_ads.zip",
                mime="application/zip",
                key=f"zip_{pick}",
            )
        except Exception as e:
            st.caption(f"ZIP 打包失敗：{e}")

        copy = load_copy_json(bdir)
        races = (copy.get("races") or []) if copy else []
        if not races and imgs:
            # 無 manifest 時用檔名推斷
            stems = sorted({p.name.rsplit("_", 1)[0] for p in imgs})
            races = [{"race_id": s, "race_no": i + 1, "model_file": f"{s}_model.jpg", "ai_file": f"{s}_ai.jpg"} for i, s in enumerate(stems)]

        if races:
            race_labels = {
                i: f"R{r.get('race_no') or '?'} · {r.get('race_name') or r.get('race_id') or i}"
                for i, r in enumerate(races)
            }
            ri = st.selectbox(
                "場次（每次只預覽一場，避免頁面過重）",
                list(race_labels.keys()),
                format_func=lambda i: race_labels[i],
                key=f"ad_race_{pick}",
            )
            r = races[ri]
            with st.expander("本場宣傳文案", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**模型**")
                    st.write(r.get("model_copy") or "")
                with c2:
                    st.markdown("**AI 馬評**")
                    st.write(r.get("ai_copy") or "")

            def _resolve_track(race_id: str, track: str, hinted: str | None) -> Path | None:
                candidates = []
                if hinted:
                    candidates.append(bdir / hinted)
                if race_id:
                    for ext in (".jpg", ".jpeg", ".png"):
                        candidates.append(bdir / f"{race_id}_{track}{ext}")
                for cand in candidates:
                    if cand.is_file():
                        return cand
                return None

            rid = str(r.get("race_id") or "")
            model_p = _resolve_track(rid, "model", r.get("model_file"))
            ai_p = _resolve_track(rid, "ai", r.get("ai_file"))

            cols = st.columns(2)
            for col, label, path in (
                (cols[0], "模型 · 勝率份額", model_p),
                (cols[1], "AI 馬評 · 份額", ai_p),
            ):
                with col:
                    st.markdown(f"**{label}**")
                    if path and path.is_file():
                        try:
                            st.image(
                                make_preview_jpeg(path),
                                caption=path.name,
                                use_container_width=True,
                            )
                        except Exception as e:
                            st.warning(f"預覽失敗：{e}")
                        with open(path, "rb") as f:
                            st.download_button(
                                f"下載原圖 {path.name}",
                                data=f.read(),
                                file_name=path.name,
                                mime="image/jpeg"
                                if path.suffix.lower() in {".jpg", ".jpeg"}
                                else "image/png",
                                key=f"dl_{pick}_{path.name}",
                            )
                        st.caption(f"{path.stat().st_size // 1024} KB")
                    else:
                        st.warning("找不到圖檔")
        else:
            st.warning("此批次沒有可顯示的海報")

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
                    st.session_state["ad_last_result"] = result
                    if result.get("ok") or result.get("races_written"):
                        st.session_state["ad_last_batch"] = str(result.get("batch_id") or bid)
                        st.success(
                            f"完成：{result.get('races_written', 0)} 場 · "
                            f"{result.get('files_written', 0)} 檔 · `{result.get('output_dir')}`"
                        )
                        st.info("請切到「瀏覽輸出」查看／下載（每次只預覽一場）。")
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
        if last and (last.get("ok") or last.get("races_written")):
            bdir = Path(last.get("output_dir") or (out_root / str(last.get("batch_id"))))
            if bdir.is_dir():
                n = len(list_batch_images(bdir))
                st.caption(f"最近一次輸出：`{bdir}` · {n} 圖")
                if n:
                    try:
                        st.download_button(
                            "下載最近一批 ZIP",
                            data=zip_batch_bytes(bdir),
                            file_name=f"{bdir.name}_ads.zip",
                            mime="application/zip",
                            key="zip_last_regen",
                        )
                    except Exception:
                        pass
