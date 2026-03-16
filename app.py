"""
F&O Momentum Dashboard — Streamlit App
Run: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from pathlib import Path

st.set_page_config(
    page_title="F&O Momentum Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark theme override ───────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp { background-color: #0d1117; color: #e6edf3; }
  .block-container { padding: 1rem 2rem; }
  .metric-card {
    background: #161b22; border-radius: 8px; padding: 1rem;
    border-left: 3px solid; margin-bottom: 0.5rem;
  }
  h1, h2, h3 { color: #e6edf3 !important; }
</style>
""", unsafe_allow_html=True)

SIG_COLOR = {
    "STRONG_BUY":   "#00e676",
    "BUY":          "#69f0ae",
    "NEUTRAL":      "#607d8b",
    "SHORT":        "#ff9100",
    "STRONG_SHORT": "#ff1744",
}

# ── Data loading ─────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    mcx = pd.read_csv("data/mcx/mcx_real.csv", parse_dates=["date"])
    bse = pd.read_csv("data/bse/bse_real.csv",  parse_dates=["date"])
    nse = pd.read_csv("data/nse/nse_monthly.csv", parse_dates=["date"])
    return mcx, bse, nse


def add_signals(df, val_col="turnover_cr"):
    df = df.sort_values("date").reset_index(drop=True)
    v = df[val_col].replace(0, np.nan)
    df["ma5"]  = v.rolling(5,  min_periods=1).mean()
    df["ma20"] = v.rolling(20, min_periods=1).mean()
    df["mom5"] = v.pct_change(5) * 100

    def sig(r):
        if pd.isna(r.ma5) or pd.isna(r.ma20) or r.ma20 == 0:
            return "NEUTRAL"
        sp = (r.ma5 - r.ma20) / r.ma20 * 100
        mom = r.get("mom5", np.nan)
        rising  = not pd.isna(mom) and mom >  3
        falling = not pd.isna(mom) and mom < -3
        if sp > 2:
            return "STRONG_BUY" if rising else "BUY"
        elif sp < -2:
            return "STRONG_SHORT" if falling else "SHORT"
        return "NEUTRAL"

    df["signal"] = df.apply(sig, axis=1)
    df["signal_color"] = df["signal"].map(SIG_COLOR)
    return df


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("⚙️ Controls")
st.sidebar.markdown("---")

mcx_raw, bse_raw, nse_raw = load_data()

date_min = mcx_raw["date"].min().date()
date_max = mcx_raw["date"].max().date()
start_d, end_d = st.sidebar.date_input(
    "Date Range",
    value=(datetime(2023, 1, 1).date(), date_max),
    min_value=date_min, max_value=date_max,
)

exchanges = st.sidebar.multiselect(
    "Exchanges", ["MCX", "BSE", "NSE (Monthly)"],
    default=["MCX", "BSE", "NSE (Monthly)"],
)

show_oi     = st.sidebar.checkbox("Show OI Overlay", value=False)
show_zscore = st.sidebar.checkbox("Show Z-Score Panel", value=True)
show_expiry = st.sidebar.checkbox("Show Expiry Markers", value=True)

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Expiry schedule:**
- 🟠 MCX: Tuesday (metals/energy)
- 🟣 BSE: Friday until Jan-25, then Tuesday
- 🔵 NSE: (monthly data shown)

**Signals:**
- 5-day MA vs 20-day MA spread
- Turnover 5-day momentum
""")

# ── Filter data ───────────────────────────────────────────────────────────────
mcx = mcx_raw[(mcx_raw["date"].dt.date >= start_d) & (mcx_raw["date"].dt.date <= end_d)].copy()
bse = bse_raw[(bse_raw["date"].dt.date >= start_d) & (bse_raw["date"].dt.date <= end_d)].copy()
nse = nse_raw[(nse_raw["date"].dt.date >= start_d) & (nse_raw["date"].dt.date <= end_d)].copy()

mcx = add_signals(mcx)
bse = add_signals(bse, val_col="contracts")   # signal from contracts
bse["ma5_cr"]  = bse["turnover_cr"].rolling(5,  min_periods=1).mean()
bse["ma20_cr"] = bse["turnover_cr"].rolling(20, min_periods=1).mean()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📊 F&O Momentum Dashboard — Real Data")
st.markdown(f"**MCX** Commodity F&O · **BSE** Sensex F&O · **NSE** Index F&O (Monthly)  |  "
            f"{start_d} → {end_d}")

# ── KPI Cards ─────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

def kpi(col, label, sig, val, sub, color):
    col.markdown(f"""
    <div class="metric-card" style="border-color:{color}">
      <div style="color:#8b949e;font-size:12px;font-weight:bold">{label}</div>
      <div style="background:{color}22;border:1px solid {color};border-radius:4px;
                  padding:2px 8px;margin:6px 0;display:inline-block;
                  color:{color};font-size:13px;font-weight:bold">{sig.replace("_"," ")}</div>
      <div style="font-size:18px;font-weight:bold;color:#e6edf3">{val}</div>
      <div style="font-size:11px;color:#8b949e">{sub}</div>
    </div>
    """, unsafe_allow_html=True)

if not mcx.empty:
    r = mcx.iloc[-1]
    sp = ((r.ma5 - r.ma20) / r.ma20 * 100) if r.ma20 > 0 else 0
    kpi(col1, "MCX (latest)", r.signal, f"₹{r.turnover_cr:,.0f} Cr",
        f"5MA ₹{r.ma5:,.0f}  |  Spread {sp:+.1f}%", SIG_COLOR.get(r.signal, "#607d8b"))

if not bse.empty:
    r = bse.iloc[-1]
    sp = ((r.ma5 - r.ma20) / r.ma20 * 100) if r.ma20 > 0 else 0
    kpi(col2, "BSE Turnover (latest)", r.signal, f"₹{r.turnover_cr:,.2f} Cr",
        f"Contracts MA spread {sp:+.1f}%", SIG_COLOR.get(r.signal, "#607d8b"))

if not nse.empty:
    r = nse.iloc[-1]
    kpi(col3, f"NSE ({r['period']})", "MONTHLY", f"₹{r.total_cr:,.0f} Cr",
        f"IF ₹{r.if_turnover_cr:,.0f}  |  IO ₹{r.io_notional_cr:,.0f}", "#2979ff")

# Growth metric
if not mcx.empty and len(mcx) > 20:
    first_mo = mcx.head(20)["turnover_cr"].mean()
    last_mo  = mcx.tail(20)["turnover_cr"].mean()
    growth   = (last_mo / first_mo - 1) * 100
    kpi(col4, "MCX Growth (period)", "TREND", f"{growth:+.0f}%",
        f"₹{first_mo:,.0f} → ₹{last_mo:,.0f} Cr avg", "#ffd740")

st.markdown("---")

# ── MCX Chart ─────────────────────────────────────────────────────────────────
if "MCX" in exchanges and not mcx.empty:
    st.subheader("🟠 MCX — Commodity F&O (Daily Turnover ₹ Cr)")
    expiry_dates_mcx = mcx[mcx["date"].dt.weekday == 1]["date"].dt.strftime("%Y-%m-%d").tolist()

    fig_mcx = go.Figure()
    fig_mcx.add_trace(go.Bar(
        x=mcx["date"], y=mcx["turnover_cr"],
        marker_color=mcx["signal_color"], name="Daily Turnover",
        opacity=0.6,
    ))
    fig_mcx.add_trace(go.Scatter(
        x=mcx["date"], y=mcx["ma5"], name="5-Day MA",
        line=dict(color="#ffab40", width=2.2),
    ))
    fig_mcx.add_trace(go.Scatter(
        x=mcx["date"], y=mcx["ma20"], name="20-Day MA",
        line=dict(color="#e040fb", width=1.8, dash="dot"),
    ))

    shapes = []
    if show_expiry:
        for d in expiry_dates_mcx:
            shapes.append(dict(type="line", xref="x", yref="paper",
                               x0=d, x1=d, y0=0, y1=1,
                               line=dict(color="#f44336", width=0.5, dash="dot")))

    fig_mcx.update_layout(
        shapes=shapes,
        height=380, paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#e6edf3"), hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0),
        yaxis=dict(gridcolor="#21262d", title="₹ Cr"),
        xaxis=dict(gridcolor="#21262d"),
        margin=dict(l=60, r=20, t=30, b=30),
    )
    st.plotly_chart(fig_mcx, use_container_width=True)

    # Z-score
    if show_zscore:
        roll_m = mcx["turnover_cr"].rolling(20, min_periods=5).mean()
        roll_s = mcx["turnover_cr"].rolling(20, min_periods=5).std()
        zscore = ((mcx["turnover_cr"] - roll_m) / roll_s.replace(0, np.nan)).clip(-4, 8)
        z_colors = ["#ff1744" if z > 3 else "#ff9100" if z > 2 else "#ffab40" if z > 1
                    else "#69f0ae" if z > -1 else "#607d8b" for z in zscore.fillna(0)]
        fig_z = go.Figure()
        fig_z.add_trace(go.Bar(x=mcx["date"], y=zscore, marker_color=z_colors,
                               name="Z-Score", opacity=0.8))
        fig_z.add_hline(y=0, line_color="#546e7a")
        fig_z.add_hline(y=2, line=dict(color="#ff9100", dash="dash", width=0.7))
        fig_z.add_hline(y=3, line=dict(color="#ff1744", dash="dot",  width=0.7))
        fig_z.update_layout(
            height=180, paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            font=dict(color="#e6edf3"), title="MCX 20-Day Z-Score (Red >3σ = extreme volume)",
            yaxis=dict(gridcolor="#21262d", range=[-4.5, 8.5]),
            xaxis=dict(gridcolor="#21262d"),
            margin=dict(l=60, r=20, t=40, b=30),
            showlegend=False,
        )
        st.plotly_chart(fig_z, use_container_width=True)

# ── BSE Chart ─────────────────────────────────────────────────────────────────
if "BSE" in exchanges and not bse.empty:
    st.subheader("🟣 BSE — Sensex F&O (Daily Turnover ₹ Cr  |  Expiry: Fri until Jan-25, then Tue)")

    cutoff = "2025-01-01"
    expiry_bse = bse[bse["is_expiry"] == True]["date"].dt.strftime("%Y-%m-%d").tolist()

    fig_bse = make_subplots(specs=[[{"secondary_y": True}]])
    fig_bse.add_trace(go.Bar(
        x=bse["date"], y=bse["turnover_cr"],
        marker_color=bse["signal_color"], name="Turnover (₹ Cr)", opacity=0.6,
    ), secondary_y=False)
    fig_bse.add_trace(go.Scatter(
        x=bse["date"], y=bse["ma5_cr"], name="Turnover 5MA",
        line=dict(color="#ffab40", width=2),
    ), secondary_y=False)
    fig_bse.add_trace(go.Scatter(
        x=bse["date"], y=bse["ma20_cr"], name="Turnover 20MA",
        line=dict(color="#e040fb", width=1.6, dash="dot"),
    ), secondary_y=False)
    fig_bse.add_trace(go.Scatter(
        x=bse["date"], y=bse["contracts"] / 1e6,
        name="Contracts (M)", line=dict(color="#546e7a", width=1, dash="dot"),
        opacity=0.5,
    ), secondary_y=True)

    shapes_bse = [dict(type="line", xref="x", yref="paper", x0=cutoff, x1=cutoff,
                       y0=0, y1=1, line=dict(color="#ffd740", width=1.5, dash="dash"))]
    if show_expiry:
        for d in expiry_bse:
            shapes_bse.append(dict(type="line", xref="x", yref="paper",
                                   x0=d, x1=d, y0=0, y1=1,
                                   line=dict(color="#f44336", width=0.5, dash="dot")))

    fig_bse.update_layout(
        shapes=shapes_bse, height=380,
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#e6edf3"), hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=60, r=60, t=30, b=30),
    )
    fig_bse.update_yaxes(title_text="₹ Cr", gridcolor="#21262d", secondary_y=False)
    fig_bse.update_yaxes(title_text="Contracts (M)", gridcolor="", secondary_y=True,
                          showgrid=False)
    fig_bse.update_xaxes(gridcolor="#21262d")
    st.plotly_chart(fig_bse, use_container_width=True)

# ── NSE Monthly ──────────────────────────────────────────────────────────────
if "NSE (Monthly)" in exchanges and not nse.empty:
    st.subheader("🔵 NSE — Index F&O Monthly Totals (₹ Cr) — Stacked by Segment")
    fig_nse = go.Figure()
    fig_nse.add_trace(go.Bar(x=nse["period"], y=nse["if_turnover_cr"],
                              name="Index Futures", marker_color="#1565c0", opacity=0.85))
    fig_nse.add_trace(go.Bar(x=nse["period"], y=nse["io_notional_cr"],
                              name="Index Options Notional", marker_color="#0288d1", opacity=0.8))
    fig_nse.add_trace(go.Bar(x=nse["period"], y=nse["io_premium_cr"],
                              name="Options Premium", marker_color="#00bcd4", opacity=0.85))

    for i, r in nse.iterrows():
        fig_nse.add_annotation(x=r["period"], y=r["total_cr"]*1.03,
                               text=f"₹{r['total_cr']/1000:.0f}K",
                               showarrow=False, font=dict(size=9, color="#e6edf3"))

    fig_nse.update_layout(
        barmode="stack", height=340,
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#e6edf3"),
        legend=dict(orientation="h", y=1.02, x=0),
        yaxis=dict(gridcolor="#21262d", title="₹ Cr / month"),
        xaxis=dict(gridcolor="#21262d"),
        margin=dict(l=60, r=20, t=40, b=30),
    )
    st.plotly_chart(fig_nse, use_container_width=True)

# ── Cross-check summary ───────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📋 Cross-Check Notes & Data Validation", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
**MCX Data**
- Unit: *Sum of Total Value (Lacs)*  →  ÷100 = ₹ Crores
- Range: Jan 2022 – Feb 2026 (1,064 trading days)
- Clear ~10× growth from ₹31K Cr/day (2022) to ₹400K+ Cr/day (2025-26)
- Driven by commodity options launch (Gold, Silver, Crude, NatGas)
- **49 anomaly days** with z-score > 3 — concentrated in Oct-Nov 2025 & Dec-Jan 2026
  - Not errors: these are **contract rollover + monthly/quarterly expiry clusters**
  - e.g. 31-Oct-25 ₹19.4L Cr, 31-Dec-25 ₹25.6L Cr (month-end rollover)
        """)
    with c2:
        st.markdown("""
**BSE Data**
- Unit: Turnover already in ₹ Crores; Contracts in absolute count
- Range: Jan 2023 – Feb 2026 (753 trading days)
- **Phase 1 (Jan–Apr 2023):** Negligible volume, ₹0.09–0.47 Cr/day
- **Phase 2 (May 2023):** Launch of new Sensex/Bankex weekly options — sharp ramp
- **Expiry day signature:** Clear weekly spikes — confirms Friday expiry through Dec 2024
- **Jan 2025 onwards:** Spikes shift to Tuesday — SEBI Oct-2024 rationalisation confirmed
- Turnover: ₹0.19 Cr (Jan-23) → ₹1,648 Cr (Sep-20-24) — massive growth

**NSE Data (Monthly)**
- Only 11 months of granular data provided (Apr-25 to Feb-26)
- Apr-25 Index Futures turnover missing (shown as 0)
- Total monthly F&O: ₹30–47 Lakh Cr/month (~₹1.5–2.5L Cr/day)
        """)
