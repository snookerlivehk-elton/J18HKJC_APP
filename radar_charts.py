"""共用雷達圖：同場每軸 min-max 相對位置，供推論頁／賽日速覽使用。

圖形半徑為 [0,1]：
  - 中心 = 該軸同場最低分（現為場內份額% 亦可）
  - 外緣 = 該軸同場最高分
  - hover 顯示該軸數值
"""
from __future__ import annotations

import pandas as pd

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

RADAR_AXES = [
    ("騎師分", "騎師"),
    ("練馬師分", "練馬師"),
    ("騎練分", "騎練"),
    ("檔位分", "檔位"),
    ("近績分", "近績"),
    ("步速分", "步速"),
    ("速度分", "速度"),
    ("SG貢獻", "速勢"),
]


def radar_radius(series: pd.Series) -> pd.Series:
    """
    同場該軸：min → 0（圖心）、max → 1（外緣）。
    負的原始分只要是同場最低，就落在中心；不會先 clamp 成 0。
    缺值不填 0（避免假的「絕對零」扭曲 min/max），正規化後填 0.5。
    """
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(0.5, index=s.index)
    lo, hi = float(valid.min()), float(valid.max())
    if hi - lo < 1e-9:
        out = pd.Series(0.5, index=s.index)
        return out
    return ((s - lo) / (hi - lo)).fillna(0.5)


def build_radar_figure(
    df: pd.DataFrame,
    horse_nos: list,
    *,
    height: int = 320,
    title: str = "",
    mobile: bool = False,
):
    if go is None:
        return None
    df = df.reset_index(drop=True)
    categories = [label for _, label in RADAR_AXES]
    cats_closed = categories + [categories[0]]
    norm = {col: radar_radius(df[col]) for col, _ in RADAR_AXES if col in df.columns}

    fig = go.Figure()
    palette = [
        "#0B6E4F", "#C45C26", "#1B4F72", "#B8860B",
        "#5D6D7E", "#922B21", "#1A5276", "#196F3D",
    ]
    for i, hno in enumerate(horse_nos):
        hits = df.index[df["馬號"].astype(int) == int(hno)].tolist()
        if not hits:
            continue
        idx = hits[0]
        row = df.loc[idx]
        r_vals = []
        raw_vals = []
        for col, _ in RADAR_AXES:
            if col not in norm:
                r_vals.append(0.5)
                raw_vals.append(None)
                continue
            r_vals.append(float(norm[col].iloc[idx]))
            v = row.get(col)
            try:
                raw_vals.append(float(v) if pd.notna(v) else None)
            except (TypeError, ValueError):
                raw_vals.append(None)
        r_closed = r_vals + [r_vals[0]]
        raw_closed = raw_vals + [raw_vals[0]]
        label = f"{int(hno)} {row['馬名']}"
        fig.add_trace(
            go.Scatterpolar(
                r=r_closed,
                theta=cats_closed,
                fill="toself",
                name=label,
                customdata=raw_closed,
                hovertemplate=(
                    "%{theta}<br>"
                    "原始分 %{customdata:+.2f}<br>"
                    "同場相對 %{r:.0%}"
                    "<extra>%{fullData.name}</extra>"
                ),
                line=dict(color=palette[i % len(palette)], width=2),
                opacity=0.8,
            )
        )

    default_title = title or (
        "雷達：中心＝同場該軸最低份額，外緣＝最高"
        if not mobile
        else ""
    )
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0.0, 0.5, 1.0] if mobile else [0.0, 0.25, 0.5, 0.75, 1.0],
                ticktext=(
                    ["最低", "中", "最高"]
                    if mobile
                    else ["同場最低", "", "中", "", "同場最高"]
                ),
                tickfont=dict(size=10 if mobile else 11),
                gridcolor="rgba(20,40,30,0.15)",
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                tickfont=dict(size=11 if mobile else 12),
                gridcolor="rgba(20,40,30,0.12)",
            ),
        ),
        showlegend=len(horse_nos) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, x=0, font=dict(size=11)),
        margin=dict(l=28, r=28, t=36 if default_title else 12, b=48 if len(horse_nos) > 1 else 24),
        height=height,
        title=dict(text=default_title, font=dict(size=13)) if default_title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Noto Sans TC, Segoe UI, sans-serif", color="#1a2e24"),
    )
    return fig


def factor_rows_for_horse(row: pd.Series) -> list[tuple[str, float]]:
    return [(label, float(row[col])) for col, label in RADAR_AXES if col in row.index]
