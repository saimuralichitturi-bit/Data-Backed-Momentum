"""
Matplotlib-based static charts for inline display.
Produces a single PNG with one row per exchange showing:
  - Daily turnover bars (green=BUY family, red=SHORT family, grey=NEUTRAL)
  - 5-day MA (orange)
  - 20-day MA (purple dashed)
  - Weekly Nifty/Sensex Tuesday expiry markers (thin red verticals)
  - OI overlay on secondary axis
  - Signal annotation strip at the top of each panel
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from pathlib import Path
from datetime import datetime

from ..analysis.signals import SIGNAL_COLORS, EXPIRY_WEEKDAY

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "charts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Map signal → bar colour
BAR_COLOR_MAP = {
    "STRONG_BUY":   "#00c853",
    "BUY":          "#69f0ae",
    "NEUTRAL":      "#bdbdbd",
    "SHORT":        "#ff6d00",
    "STRONG_SHORT": "#d50000",
}

EXCHANGE_LABEL = {
    "NSE": "NSE — Nifty F&O Turnover (₹ Cr)\n[Weekly expiry: Tuesday]",
    "BSE": "BSE — Sensex F&O Turnover (₹ Cr)\n[Weekly expiry: Tuesday]",
    "IEX": "IEX — Energy Market Turnover (₹ Cr)\n[Weekly expiry: Tuesday]",
}


def plot_fo_analysis(
    dfs: dict[str, pd.DataFrame],
    composite_df: pd.DataFrame | None = None,
    save_path: str | None = None,
) -> str:
    exchanges = [e for e in ["NSE", "BSE", "IEX"] if e in dfs and not dfs[e].empty]
    n_exc = len(exchanges)
    n_rows = n_exc + (1 if composite_df is not None and not composite_df.empty else 0)

    fig = plt.figure(figsize=(22, 5 * n_rows + 1))
    fig.patch.set_facecolor("#f5f5f5")

    title_str = (
        "Exchange F&O Daily Activity — NSE (Nifty) · BSE (Sensex) · IEX\n"
        "Daily Turnover  |  5-Day MA  |  20-Day MA  |  Tuesday Weekly Expiry Markers  |  Signal Colouring"
    )
    fig.suptitle(title_str, fontsize=13, fontweight="bold", y=0.995, va="top",
                 color="#212121", family="monospace")

    gs = fig.add_gridspec(n_rows, 1, hspace=0.55)
    axes = [fig.add_subplot(gs[i]) for i in range(n_exc)]
    if composite_df is not None and not composite_df.empty:
        ax_comp = fig.add_subplot(gs[n_exc])
    else:
        ax_comp = None

    for ax, exchange in zip(axes, exchanges):
        df = dfs[exchange]
        _plot_exchange_panel(ax, df, exchange)

    if ax_comp is not None and composite_df is not None:
        _plot_composite_panel(ax_comp, composite_df)

    _add_legend(fig)

    path = save_path or str(OUTPUT_DIR / f"fo_static_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[StaticChart] Saved: {path}")
    return path


def _plot_exchange_panel(ax: plt.Axes, df: pd.DataFrame, exchange: str):
    ax.set_facecolor("#ffffff")
    dates = df["date"].values
    turnover = df["turnover_cr"].values

    # ── Bar colours by signal
    signals = df["signal"].values if "signal" in df.columns else np.full(len(df), "NEUTRAL")
    bar_colors = [BAR_COLOR_MAP.get(s, "#bdbdbd") for s in signals]
    ax.bar(dates, turnover, color=bar_colors, width=0.8, alpha=0.75, zorder=2)

    # ── 5-day MA
    if "ma5" in df.columns:
        ax.plot(dates, df["ma5"].values, color="#e65100", linewidth=2.2,
                label="5-Day MA", zorder=4)

    # ── 20-day MA
    if "ma20" in df.columns:
        ax.plot(dates, df["ma20"].values, color="#6a1b9a", linewidth=1.8,
                linestyle="--", label="20-Day MA", zorder=4)

    # ── OI on twin axis
    if "oi_contracts" in df.columns and df["oi_contracts"].notna().sum() > 5:
        ax2 = ax.twinx()
        ax2.plot(dates, df["oi_contracts"].values, color="#37474f", linewidth=1.2,
                 linestyle=":", alpha=0.65, label="OI (contracts)", zorder=3)
        ax2.set_ylabel("OI (contracts)", fontsize=8, color="#37474f")
        ax2.tick_params(axis="y", labelsize=7, colors="#37474f")
        ax2.spines["right"].set_color("#b0bec5")
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M"))

    # ── Weekly expiry vertical lines (Tuesdays)
    expiry_wd = EXPIRY_WEEKDAY.get(exchange, 1)
    expiry_dates = df[df["date"].dt.weekday == expiry_wd]["date"].values
    ymax = np.nanmax(turnover) if len(turnover) else 1
    for ed in expiry_dates:
        ax.axvline(x=ed, color="#c62828", linewidth=0.5, linestyle=":", alpha=0.6, zorder=1)

    # Expiry label on the right edge
    ax.text(0.998, 0.97, f"┊ = Expiry (Tue)",
            transform=ax.transAxes, fontsize=7, color="#c62828",
            ha="right", va="top")

    # ── Signal strip: tiny colored band at top
    _add_signal_strip(ax, df)

    ax.set_ylabel("Turnover (₹ Cr)", fontsize=9)
    ax.set_title(EXCHANGE_LABEL.get(exchange, exchange), fontsize=10, fontweight="bold",
                 loc="left", pad=4, color="#212121")
    ax.tick_params(axis="both", labelsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"₹{x:,.0f}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)

    # Latest signal annotation box
    last = df.iloc[-1]
    sig = last.get("signal", "NEUTRAL")
    sig_color = BAR_COLOR_MAP.get(sig, "#bdbdbd")
    ax.text(0.002, 0.97,
            f"Latest: {last['date'].strftime('%d %b %Y')}  |  "
            f"₹{last['turnover_cr']:,.0f} Cr  |  Signal: {sig}",
            transform=ax.transAxes, fontsize=8.5, color="#212121",
            va="top", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=sig_color,
                      edgecolor="#888", alpha=0.85))


def _add_signal_strip(ax: plt.Axes, df: pd.DataFrame):
    """Draw a thin coloured signal-timeline strip using a single broken_barh per colour group."""
    if "signal" not in df.columns:
        return
    dates_num = mdates.date2num(df["date"].dt.to_pydatetime())
    signals = df["signal"].values
    y0, y1 = ax.get_ylim()
    strip_h = (y1 - y0) * 0.018

    # Batch bars by colour to avoid per-day loop
    widths = np.diff(dates_num, append=dates_num[-1] + 1)
    for sig_name, color in BAR_COLOR_MAP.items():
        mask = signals == sig_name
        if not mask.any():
            continue
        xranges = [(d, w) for d, w, m in zip(dates_num, widths, mask) if m]
        ax.broken_barh(xranges, (y0 - strip_h, strip_h),
                       facecolors=color, alpha=0.88, zorder=5)


def _plot_composite_panel(ax: plt.Axes, composite_df: pd.DataFrame):
    ax.set_facecolor("#f9f9f9")
    if "composite_score" not in composite_df.columns:
        return

    dates = composite_df["date"].values
    score = composite_df["composite_score"].values

    colors = [
        "#00c853" if s >= 1.5 else
        "#69f0ae" if s >= 0.5 else
        "#ff6d00" if s <= -0.5 else
        "#d50000" if s <= -1.5 else
        "#bdbdbd"
        for s in score
    ]
    ax.bar(dates, score, color=colors, width=0.8, alpha=0.8, zorder=2)
    ax.axhline(0, color="#9e9e9e", linewidth=1, zorder=3)
    ax.set_ylim(-2.4, 2.4)
    ax.set_yticks([-2, -1, 0, 1, 2])
    ax.set_yticklabels(["STRONG\nSHORT", "SHORT", "NEUTRAL", "BUY", "STRONG\nBUY"],
                       fontsize=7)
    ax.set_title("Composite Momentum Score (NSE + BSE + IEX)", fontsize=10,
                 fontweight="bold", loc="left", pad=4)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def _add_legend(fig: plt.Figure):
    legend_elements = [
        Patch(facecolor="#00c853", label="STRONG BUY"),
        Patch(facecolor="#69f0ae", label="BUY"),
        Patch(facecolor="#bdbdbd", label="NEUTRAL"),
        Patch(facecolor="#ff6d00", label="SHORT"),
        Patch(facecolor="#d50000", label="STRONG SHORT"),
        Line2D([0], [0], color="#e65100", linewidth=2, label="5-Day MA"),
        Line2D([0], [0], color="#6a1b9a", linewidth=1.8, linestyle="--", label="20-Day MA"),
        Line2D([0], [0], color="#c62828", linewidth=0.8, linestyle=":", label="Weekly Expiry (Tue)"),
    ]
    fig.legend(
        handles=legend_elements,
        loc="upper right",
        bbox_to_anchor=(1.0, 0.995),
        ncol=1,
        fontsize=8.5,
        framealpha=0.9,
        edgecolor="#cccccc",
    )
