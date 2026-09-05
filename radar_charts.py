"""共用雷達圖：同場因子 min-max → [0,1]，供推論頁／賽日速覽使用。"""
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
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    lo, hi = float(s.min()), float(s.max())
    if hi - lo < 1e-9:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


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
    norm = {col: radar_radius(df[col].rename(col)) for col, _ in RADAR_AXES}

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
        r_vals = [float(norm[col].iloc[idx]) for col, _ in RADAR_AXES]
        r_vals = r_vals + [r_vals[0]]
        label = f"{int(hno)} {row['馬名']}"
        fig.add_trace(
            go.Scatterpolar(
                r=r_vals,
                theta=cats_closed,
                fill="toself",
                name=label,
                line=dict(color=palette[i % len(palette)], width=2),
                opacity=0.8,
            )
        )

    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0.5, 1.0] if mobile else [0.25, 0.5, 0.75, 1.0],
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
        margin=dict(l=28, r=28, t=36 if title else 12, b=48 if len(horse_nos) > 1 else 24),
        height=height,
        title=dict(text=title, font=dict(size=14)) if title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Noto Sans TC, Segoe UI, sans-serif", color="#1a2e24"),
    )
    return fig


def factor_rows_for_horse(row: pd.Series) -> list[tuple[str, float]]:
    return [(label, float(row[col])) for col, label in RADAR_AXES if col in row.index]
