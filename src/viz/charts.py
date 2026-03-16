"""
Interactive Plotly charts for exchange F&O analysis.

Each exchange panel shows:
  - Daily turnover bar chart (coloured by signal)
  - 5-day MA line
  - 20-day MA line
  - Weekly expiry markers (vertical dashed lines)
  - OI overlay (secondary y-axis)

Bottom panel: composite signal heatmap across all exchanges.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime

from ..analysis.signals import SIGNAL_COLORS, EXPIRY_WEEKDAY

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "charts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EXCHANGE_CONFIG = {
    "NSE": {"color": "#1565c0", "label": "NSE — Equity F&O Turnover (₹ Cr)"},
    "BSE": {"color": "#6a1b9a", "label": "BSE — Equity F&O Turnover (₹ Cr)"},
    "MCX": {"color": "#e65100", "label": "MCX — Commodity F&O Turnover (₹ Cr)"},
    "IEX": {"color": "#2e7d32", "label": "IEX — Energy Market Turnover (₹ Cr)"},
}


def _get_weekly_expiries(df: pd.DataFrame, expiry_weekday: int) -> pd.Series:
    return df[df["date"].dt.weekday == expiry_weekday]["date"]


def build_exchange_chart(
    dfs: dict[str, pd.DataFrame],
    composite_df: pd.DataFrame | None = None,
    title: str = "Exchange F&O Activity — Daily Turnover, MA & Weekly Expiry",
) -> go.Figure:
    """Build multi-panel figure: one row per exchange + composite row."""

    exchanges = [e for e in ["NSE", "BSE", "MCX", "IEX"] if e in dfs and not dfs[e].empty]
    n_rows = len(exchanges) + (1 if composite_df is not None and not composite_df.empty else 0)

    row_heights = [0.22] * len(exchanges)
    if composite_df is not None and not composite_df.empty:
        row_heights.append(0.12)

    specs = [[{"secondary_y": True}] for _ in range(n_rows)]
    subplot_titles = [EXCHANGE_CONFIG.get(e, {}).get("label", e) for e in exchanges]
    if composite_df is not None and not composite_df.empty:
        subplot_titles.append("Composite Momentum Signal (All Exchanges)")

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=subplot_titles,
        row_heights=row_heights,
        specs=specs,
    )

    for row_idx, exchange in enumerate(exchanges, start=1):
        df = dfs[exchange].copy()
        expiry_wd = EXPIRY_WEEKDAY.get(exchange, 3)
        cfg = EXCHANGE_CONFIG.get(exchange, {"color": "#607d8b", "label": exchange})

        _add_exchange_traces(fig, df, exchange, cfg, row_idx, expiry_wd)

    if composite_df is not None and not composite_df.empty:
        _add_composite_panel(fig, composite_df, n_rows)

    fig.update_layout(
        title=dict(text=title, font=dict(size=18, color="#212121"), x=0.5),
        height=260 * n_rows + 80,
        plot_bgcolor="#fafafa",
        paper_bgcolor="#ffffff",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        margin=dict(l=60, r=60, t=100, b=60),
        font=dict(family="Inter, Arial, sans-serif", size=11),
    )

    # Style all x-axes
    for i in range(1, n_rows + 1):
        fig.update_xaxes(
            showgrid=True,
            gridcolor="#e0e0e0",
            zeroline=False,
            tickformat="%d %b %Y",
            row=i, col=1,
        )
        fig.update_yaxes(
            showgrid=True,
            gridcolor="#e0e0e0",
            zeroline=False,
            row=i, col=1,
        )

    return fig


def _add_exchange_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    exchange: str,
    cfg: dict,
    row: int,
    expiry_wd: int,
):
    # ── Bar: daily turnover coloured by signal
    bar_colors = df["signal_color"].tolist() if "signal_color" in df.columns else [cfg["color"]] * len(df)

    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["turnover_cr"],
            name=f"{exchange} Daily Turnover",
            marker=dict(color=bar_colors, line=dict(width=0)),
            opacity=0.72,
            showlegend=(row == 1),
        ),
        row=row, col=1, secondary_y=False,
    )

    # ── 5-day MA line
    if "ma5" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["ma5"],
                name="5-Day MA",
                line=dict(color="#f57f17", width=2.5),
                mode="lines",
                showlegend=(row == 1),
            ),
            row=row, col=1, secondary_y=False,
        )

    # ── 20-day MA line
    if "ma20" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["ma20"],
                name="20-Day MA",
                line=dict(color="#880e4f", width=2, dash="dot"),
                mode="lines",
                showlegend=(row == 1),
            ),
            row=row, col=1, secondary_y=False,
        )

    # ── OI on secondary y-axis
    if "oi_contracts" in df.columns and df["oi_contracts"].notna().sum() > 3:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["oi_contracts"],
                name=f"{exchange} OI (Contracts)",
                line=dict(color="#37474f", width=1.5, dash="dash"),
                mode="lines",
                opacity=0.6,
                showlegend=(row == 1),
            ),
            row=row, col=1, secondary_y=True,
        )
        fig.update_yaxes(
            title_text="OI (Contracts)",
            secondary_y=True,
            showgrid=False,
            row=row, col=1,
        )

    # ── Weekly expiry vertical lines
    expiry_dates = _get_weekly_expiries(df, expiry_wd)
    for exp_date in expiry_dates:
        # Convert to string to avoid Plotly Timestamp arithmetic bug
        exp_str = exp_date.strftime("%Y-%m-%d")
        fig.add_vline(
            x=exp_str,
            line=dict(color="#b71c1c", width=1, dash="dot"),
            row=row, col=1,
        )
        # Add annotation separately on first panel only to avoid clutter
        if row == 1:
            fig.add_annotation(
                x=exp_str,
                y=1.0,
                xref=f"x{row}",
                yref="paper",
                text="Exp",
                font=dict(size=8, color="#b71c1c"),
                showarrow=False,
                textangle=-90,
            )

    # ── Signal icons on the top of bars (STRONG_BUY / STRONG_SHORT only)
    strong = df[df["signal"].isin(["STRONG_BUY", "STRONG_SHORT"])] if "signal" in df.columns else pd.DataFrame()
    if not strong.empty:
        for _, srow in strong.iterrows():
            symbol = "▲" if srow["signal"] == "STRONG_BUY" else "▼"
            color = SIGNAL_COLORS[srow["signal"]]
            fig.add_annotation(
                x=srow["date"],
                y=srow["turnover_cr"] * 1.03,
                text=symbol,
                font=dict(size=10, color=color),
                showarrow=False,
                row=row, col=1,
                yref=f"y{row if row > 1 else ''}",
            )

    fig.update_yaxes(
        title_text="Turnover (₹ Cr)",
        secondary_y=False,
        row=row, col=1,
    )


def _add_composite_panel(fig: go.Figure, composite_df: pd.DataFrame, row: int):
    """Heatmap row showing composite signal value over time."""
    sig_cols = [c for c in composite_df.columns if c.endswith("_signal")]

    if "composite_score" not in composite_df.columns:
        return

    # Color map for composite score
    score = composite_df["composite_score"]
    colors = score.apply(_score_to_color).tolist()

    fig.add_trace(
        go.Bar(
            x=composite_df["date"],
            y=score.abs(),
            name="Composite Momentum",
            marker=dict(color=colors, line=dict(width=0)),
            opacity=0.85,
            showlegend=True,
        ),
        row=row, col=1, secondary_y=False,
    )

    # Zero line
    fig.add_hline(y=0, line=dict(color="#9e9e9e", width=1), row=row, col=1)

    fig.update_yaxes(
        title_text="Score",
        secondary_y=False,
        range=[0, 2.2],
        row=row, col=1,
    )


def _score_to_color(score: float) -> str:
    if pd.isna(score):
        return SIGNAL_COLORS["NEUTRAL"]
    if score >= 1.5:
        return SIGNAL_COLORS["STRONG_BUY"]
    elif score >= 0.5:
        return SIGNAL_COLORS["BUY"]
    elif score <= -1.5:
        return SIGNAL_COLORS["STRONG_SHORT"]
    elif score <= -0.5:
        return SIGNAL_COLORS["SHORT"]
    return SIGNAL_COLORS["NEUTRAL"]


def build_signal_summary_chart(latest_signals: dict) -> go.Figure:
    """Compact bar chart showing current signal per exchange."""
    from ..analysis.signals import SIGNAL_VALUES

    exchanges = [k for k in latest_signals if k != "COMPOSITE"]
    signals   = [latest_signals[e]["signal"] for e in exchanges]
    values    = [SIGNAL_VALUES.get(s, 0) for s in signals]
    colors    = [SIGNAL_COLORS.get(s, "#9e9e9e") for s in signals]
    turnovers = [latest_signals[e].get("turnover_cr", 0) for e in exchanges]
    ma_spreads = [latest_signals[e].get("ma_spread_pct", 0) for e in exchanges]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=exchanges,
        y=values,
        marker_color=colors,
        text=[f"{s}<br>₹{t:,.0f}Cr<br>MA Spread: {ms:+.1f}%"
              for s, t, ms in zip(signals, turnovers, ma_spreads)],
        textposition="outside",
        name="Signal Strength",
    ))

    composite = latest_signals.get("COMPOSITE", {})
    if composite:
        fig.add_annotation(
            x=0.5, y=1.08,
            xref="paper", yref="paper",
            text=(f"<b>Composite Signal: {composite.get('signal', 'N/A')}</b>  "
                  f"(Score: {composite.get('composite_score', 0):+.2f})"),
            showarrow=False,
            font=dict(size=14, color="#212121"),
            bgcolor=SIGNAL_COLORS.get(composite.get("signal", "NEUTRAL"), "#fff"),
            bordercolor="#666",
            borderwidth=1,
            borderpad=6,
        )

    fig.update_layout(
        title="Current F&O Signal Snapshot",
        yaxis=dict(
            title="Signal Strength",
            range=[-2.5, 2.5],
            tickvals=[-2, -1, 0, 1, 2],
            ticktext=["STRONG SHORT", "SHORT", "NEUTRAL", "BUY", "STRONG BUY"],
            zeroline=True,
            zerolinecolor="#9e9e9e",
        ),
        plot_bgcolor="#fafafa",
        paper_bgcolor="#ffffff",
        height=420,
        font=dict(family="Inter, Arial, sans-serif", size=12),
        margin=dict(t=80, b=40),
    )

    return fig


def save_charts(main_fig: go.Figure, snapshot_fig: go.Figure, tag: str = ""):
    ts = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    main_path     = OUTPUT_DIR / f"fo_analysis_{ts}.html"
    snapshot_path = OUTPUT_DIR / f"signal_snapshot_{ts}.html"

    main_fig.write_html(str(main_path), include_plotlyjs="cdn")
    snapshot_fig.write_html(str(snapshot_path), include_plotlyjs="cdn")

    # Also save static PNG if kaleido is available
    try:
        main_fig.write_image(str(OUTPUT_DIR / f"fo_analysis_{ts}.png"), width=1600, height=900)
        snapshot_fig.write_image(str(OUTPUT_DIR / f"signal_snapshot_{ts}.png"), width=900, height=500)
        print(f"[Charts] Saved PNG: fo_analysis_{ts}.png")
    except Exception:
        pass  # kaleido not installed; HTML is the primary output

    print(f"[Charts] Saved HTML: {main_path.name}, {snapshot_path.name}")
    return str(main_path), str(snapshot_path)
