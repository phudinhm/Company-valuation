"""Investment Terminal - an equity research, valuation and reporting workbench.

Structure of this file
----------------------
  1. Configuration and design system   (theme tokens -> CSS + Plotly styling)
  2. Formatting helpers
  3. Data layer                        (all network access, cached + parallel)
  4. Analytics engines                 (indicators, scoring, valuation models)
  5. UI component library              (sections, KPI grids, annotated figures)
  6. Reporting layer                   (exportable HTML / CSV report)
  7. Navigation and shell
  8. Modules 1-9

Design rules applied throughout:
  * Every network call goes through the cached data layer in section 3, so
    moving a slider never refetches a financial statement.
  * Every chart is rendered through `figure()`, which forces a numbered
    caption and a "how to read this" explanation to exist.
  * Iconography is typographic (numbers, rules, weight) rather than emoji.
"""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots
from scipy.stats import norm

APP_NAME = "Investment Terminal"
APP_TAGLINE = "Fundamental research, valuation and reporting"
DATA_SOURCE = "Yahoo Finance"

# ==============================================================================
# 1. CONFIGURATION & DESIGN SYSTEM
# ==============================================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# A single source of truth for colour: the same dictionary drives the CSS
# variables AND the Plotly figure styling, so charts can never drift out of
# sync with the surrounding page the way hardcoded hex values did before.
THEMES = {
    "Light": {
        "bg": "#f4f5f9", "bg_grad": "radial-gradient(circle at 12% -10%, #ffffff 0%, #f4f5f9 60%)",
        "surface": "#ffffff", "surface_alt": "#f8f9fc", "surface_sunk": "#eef0f6",
        "text": "#14172a", "muted": "#5f6980", "faint": "#8b93a7",
        "border": "#e4e7f0", "accent": "#3d3ab0", "accent_soft": "#6366f1",
        "success": "#0f8f5c", "danger": "#cf2c1e", "warning": "#b8760a", "info": "#2563eb",
        "pos_bg": "#ecfdf3", "pos_text": "#0a5f3d",
        "neg_bg": "#fef3f2", "neg_text": "#8f2318",
        "warn_bg": "#fffaeb", "warn_text": "#8a5a05",
        "neu_bg": "#f0f2fc", "neu_text": "#2f2a86",
        "grid": "rgba(20,23,42,0.08)", "shadow": "rgba(16,24,40,0.08)",
    },
    "Dark": {
        "bg": "#080b13", "bg_grad": "radial-gradient(circle at 12% -10%, #151c30 0%, #080b13 60%)",
        "surface": "#111726", "surface_alt": "#161d2e", "surface_sunk": "#0d121e",
        "text": "#eef1f8", "muted": "#94a1b8", "faint": "#6c7893",
        "border": "#222a3d", "accent": "#8b93f8", "accent_soft": "#a5adfb",
        "success": "#34d399", "danger": "#f87171", "warning": "#fbbf24", "info": "#60a5fa",
        "pos_bg": "#0d2a22", "pos_text": "#7ee2b8",
        "neg_bg": "#2a1416", "neg_text": "#fca5a5",
        "warn_bg": "#2b2110", "warn_text": "#fcd34d",
        "neu_bg": "#141b2e", "neu_text": "#c3caff",
        "grid": "rgba(238,241,248,0.09)", "shadow": "rgba(0,0,0,0.45)",
    },
    "Sepia": {
        "bg": "#f4eee0", "bg_grad": "radial-gradient(circle at 12% -10%, #fbf6ea 0%, #f4eee0 60%)",
        "surface": "#fffaf0", "surface_alt": "#faf3e4", "surface_sunk": "#efe6d3",
        "text": "#382e21", "muted": "#77674f", "faint": "#9a8a70",
        "border": "#e2d4ba", "accent": "#8f5730", "accent_soft": "#b57a4a",
        "success": "#3d8a5c", "danger": "#b0432d", "warning": "#b4801f", "info": "#3f6f9c",
        "pos_bg": "#edf3e5", "pos_text": "#2c6742",
        "neg_bg": "#f8e8e2", "neg_text": "#8b3520",
        "warn_bg": "#f7eeda", "warn_text": "#7d5a12",
        "neu_bg": "#f1e8d9", "neu_text": "#674325",
        "grid": "rgba(56,46,33,0.10)", "shadow": "rgba(80,60,35,0.12)",
    },
}

DENSITY = {
    "Comfortable": {"card_pad": "18px 20px", "kpi_pad": "16px 18px", "gap": "14px",
                    "kpi_value": "24px", "block_top": "2.4rem", "sec_top": "30px"},
    "Compact": {"card_pad": "12px 14px", "kpi_pad": "11px 13px", "gap": "9px",
                "kpi_value": "21px", "block_top": "1.4rem", "sec_top": "20px"},
}

DEFAULTS = {
    "theme": "Light",
    "density": "Comfortable",
    "module": "1. Executive Dashboard",
    "market_select": "United States",
    "ticker_symbol_input": "AAPL",
    "explain_open": False,
    "build_report": False,
    "_export": False,
}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)

T = THEMES[st.session_state.theme]
D = DENSITY[st.session_state.density]


def _tokens_css(t: dict, d: dict) -> str:
    pairs = {
        "--bg": t["bg"], "--bg-grad": t["bg_grad"], "--surface": t["surface"],
        "--surface-alt": t["surface_alt"], "--surface-sunk": t["surface_sunk"],
        "--text": t["text"], "--muted": t["muted"], "--faint": t["faint"],
        "--border": t["border"], "--accent": t["accent"], "--accent-soft": t["accent_soft"],
        "--success": t["success"], "--danger": t["danger"], "--warning": t["warning"],
        "--info": t["info"], "--pos-bg": t["pos_bg"], "--pos-text": t["pos_text"],
        "--neg-bg": t["neg_bg"], "--neg-text": t["neg_text"], "--warn-bg": t["warn_bg"],
        "--warn-text": t["warn_text"], "--neu-bg": t["neu_bg"], "--neu-text": t["neu_text"],
        "--shadow": t["shadow"], "--card-pad": d["card_pad"], "--kpi-pad": d["kpi_pad"],
        "--gap": d["gap"], "--kpi-value": d["kpi_value"], "--block-top": d["block_top"],
        "--sec-top": d["sec_top"],
    }
    return ":root{" + "".join(f"{k}:{v};" for k, v in pairs.items()) + "}"


# The stylesheet is a plain string (no f-string) so CSS braces stay readable;
# the theme block is spliced in at a marker instead.
_STYLESHEET = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

/*TOKENS*/

html, body, [class*="css"] { font-family: 'Inter', -apple-system, "Segoe UI", sans-serif; color: var(--text); }
[data-testid="stAppViewContainer"] { background: var(--bg-grad); }
.block-container { padding-top: var(--block-top); padding-bottom: 4.5rem; max-width: 1560px; }
h1,h2,h3,h4,h5,h6 { font-family: 'Inter', sans-serif; letter-spacing: -0.015em; color: var(--text); }
a { color: var(--accent); }
hr { border-color: var(--border); }

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--border); }
[data-testid="stSidebar"] * { color: var(--text); }
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small { color: var(--muted) !important; }
.side-brand { font-size: 17px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1; }
.side-sub { font-size: 11px; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; margin-top: 3px; }
.side-group { font-size: 10.5px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
              color: var(--faint); margin: 16px 0 2px; }

/* ---------- Buttons & inputs ---------- */
.stButton > button[kind="primary"] { background: linear-gradient(135deg, var(--accent), var(--accent-soft));
    border: none; font-weight: 600; letter-spacing: .01em; }
.stButton > button { border-radius: 8px; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
    background: var(--surface); color: var(--text); border-radius: 8px; }

/* ---------- Section headers ---------- */
.section { display: flex; align-items: baseline; gap: 12px; margin: var(--sec-top) 0 4px; }
.section-num { font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600;
    color: var(--accent); background: var(--neu-bg); border-radius: 5px; padding: 2px 7px; letter-spacing: .04em; }
.section-title { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; }
.section-rule { height: 1px; background: var(--border); flex: 1; margin-bottom: 3px; }
.section-sub { font-size: 12.5px; color: var(--muted); margin: 0 0 12px; line-height: 1.55; }
.eyebrow { font-size: 10.5px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--faint); }

/* ---------- Cards ---------- */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: var(--card-pad); box-shadow: 0 1px 2px var(--shadow); }
.card + .card { margin-top: var(--gap); }
.card-title { font-size: 13.5px; font-weight: 700; margin: 0 0 6px; }
.card-body { font-size: 13px; line-height: 1.6; color: var(--text); }
.card-meta { font-size: 12px; color: var(--muted); }

/* ---------- KPI grid ---------- */
.kpi-grid { display: grid; gap: var(--gap); margin-bottom: 6px; }
.kpi { position: relative; background: var(--surface); border: 1px solid var(--border);
    border-radius: 11px; padding: var(--kpi-pad); overflow: hidden;
    transition: border-color .16s ease, transform .16s ease; }
.kpi:hover { border-color: var(--accent); transform: translateY(-1px); }
.kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--border); }
.kpi.good::before { background: var(--success); }
.kpi.bad::before { background: var(--danger); }
.kpi.warn::before { background: var(--warning); }
.kpi.flat::before { background: var(--accent); }
.kpi-label { font-size: 10.5px; font-weight: 600; letter-spacing: .07em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
.kpi-value { font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
    font-size: var(--kpi-value); font-weight: 600; line-height: 1.15; letter-spacing: -0.02em; }
.kpi-sub { font-size: 11.5px; color: var(--muted); margin-top: 5px; line-height: 1.4; }
.kpi-delta { font-size: 12px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
.kpi-delta.pos { color: var(--success); } .kpi-delta.neg { color: var(--danger); }
.help-dot { display: inline-block; width: 13px; height: 13px; line-height: 13px; text-align: center;
    border-radius: 50%; background: var(--surface-sunk); color: var(--faint); font-size: 9px;
    font-weight: 700; cursor: help; }

/* ---------- Notes / interpretation ---------- */
.note { border: 1px solid var(--border); border-left-width: 3px; border-radius: 9px;
    padding: 13px 15px; margin: 10px 0 4px; font-size: 13px; line-height: 1.62; }
.note-title { font-size: 10.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
    margin-bottom: 6px; opacity: .85; }
.note p { margin: 0 0 7px; } .note ul { margin: 5px 0 6px 18px; padding: 0; } .note li { margin-bottom: 4px; }
.note.pos { background: var(--pos-bg); color: var(--pos-text); border-left-color: var(--success); }
.note.neg { background: var(--neg-bg); color: var(--neg-text); border-left-color: var(--danger); }
.note.warn { background: var(--warn-bg); color: var(--warn-text); border-left-color: var(--warning); }
.note.neu { background: var(--neu-bg); color: var(--neu-text); border-left-color: var(--accent); }

/* ---------- Figure captions ---------- */
.figcap { border-top: 1px solid var(--border); padding-top: 7px; margin-top: -6px; margin-bottom: 2px; }
.figcap-line { font-size: 12.5px; color: var(--muted); line-height: 1.55; }
.figcap-num { font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; font-weight: 600;
    color: var(--accent); margin-right: 7px; }
.figcap-title { color: var(--text); font-weight: 600; }
.exp-block { font-size: 12.8px; line-height: 1.62; color: var(--text); }
.exp-block b { color: var(--text); }
.exp-row { display: grid; grid-template-columns: 92px 1fr; gap: 10px; margin-bottom: 7px; }
.exp-key { font-size: 10.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--faint); padding-top: 2px; }

/* ---------- Header ---------- */
.hdr-name { font-size: 26px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.15; margin: 0; }
.hdr-meta { font-size: 12.5px; color: var(--muted); margin-top: 5px; }
.hdr-chip { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 5px;
    background: var(--surface-sunk); color: var(--muted); margin-right: 6px; letter-spacing: .02em; }
.px-box { text-align: right; background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 16px; }
.px-value { font-family: 'IBM Plex Mono', monospace; font-size: 29px; font-weight: 700; letter-spacing: -0.02em; }
.px-chg { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.px-meta { font-size: 11px; color: var(--faint); margin-top: 4px; }

/* ---------- 52-week range bar ---------- */
.rng { margin-top: 9px; }
.rng-track { position: relative; height: 5px; border-radius: 3px; background: var(--surface-sunk); }
.rng-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px;
    background: linear-gradient(90deg, var(--accent-soft), var(--accent)); }
.rng-mark { position: absolute; top: -3px; width: 2px; height: 11px; background: var(--text); border-radius: 1px; }
.rng-labels { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--faint); margin-top: 4px;
    font-family: 'IBM Plex Mono', monospace; }

/* ---------- Score bars ---------- */
.score-row { display: grid; grid-template-columns: 132px 1fr 46px; gap: 10px; align-items: center; margin-bottom: 8px; }
.score-name { font-size: 12px; color: var(--muted); font-weight: 500; }
.score-track { height: 7px; border-radius: 4px; background: var(--surface-sunk); overflow: hidden; }
.score-fill { height: 100%; border-radius: 4px; }
.score-val { font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600; text-align: right; }
.verdict { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.verdict-score { font-family: 'IBM Plex Mono', monospace; font-size: 42px; font-weight: 700; line-height: 1; letter-spacing: -0.03em; }
.verdict-band { font-size: 15px; font-weight: 700; letter-spacing: -0.01em; }
.verdict-text { font-size: 12.8px; color: var(--muted); line-height: 1.55; flex: 1; min-width: 240px; }

/* ---------- Checklist ---------- */
.chk { display: grid; grid-template-columns: 20px 1fr; gap: 9px; align-items: start; margin-bottom: 9px; font-size: 12.8px; line-height: 1.5; }
.chk-mark { font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 13px; text-align: center; }
.chk-pass { color: var(--success); } .chk-fail { color: var(--danger); } .chk-warn { color: var(--warning); } .chk-na { color: var(--faint); }
.chk-label { font-weight: 600; } .chk-detail { color: var(--muted); }

/* ---------- Tabs & tables ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] { height: 38px; background: transparent; border: none; font-size: 13px;
    font-weight: 500; padding: 0 14px; color: var(--muted); border-radius: 7px 7px 0 0; }
.stTabs [aria-selected="true"] { color: var(--accent) !important; font-weight: 700;
    background: var(--surface-alt); box-shadow: inset 0 -2px 0 var(--accent); }
[data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; font-size: 21px; }
[data-testid="stMetricLabel"] { font-size: 12px; color: var(--muted); }

/* ---------- News list ---------- */
.news { border-bottom: 1px solid var(--border); padding: 8px 0; }
.news:last-child { border-bottom: none; }
.news-t { font-size: 13px; line-height: 1.45; font-weight: 500; }
.news-m { font-size: 11px; color: var(--faint); margin-top: 3px; }

/* ---------- Footer ---------- */
.foot { border-top: 1px solid var(--border); margin-top: 34px; padding: 14px 0 6px;
    font-size: 11.5px; color: var(--faint); line-height: 1.65; }

/* ---------- Print ---------- */
@media print {
  [data-testid="stSidebar"], [data-testid="stToolbar"], .stButton { display: none !important; }
  .block-container { max-width: 100%; padding: 0; }
  .card, .kpi, .note { break-inside: avoid; }
}
</style>
"""

st.markdown(_STYLESHEET.replace("/*TOKENS*/", _tokens_css(T, D)), unsafe_allow_html=True)

# Plotly styling derived from the same tokens.
PLOT_SEQ = [T["accent_soft"], T["success"], T["warning"], T["info"], T["danger"], T["faint"]]
PLOTLY_TEMPLATE = "plotly_dark" if st.session_state.theme == "Dark" else "plotly_white"


def style_fig(fig, height=None, legend="top", margin=None):
    """Applies the app's typographic + colour system to any Plotly figure."""
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        font=dict(family="Inter, sans-serif", size=12, color=T["text"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=PLOT_SEQ,
        margin=margin or dict(l=8, r=8, t=26, b=8),
        hoverlabel=dict(font_family="IBM Plex Mono, monospace", font_size=12,
                        bgcolor=T["surface"], bordercolor=T["border"]),
        title=None,
    )
    if height:
        fig.update_layout(height=height)
    if legend == "top":
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.01,
                                      xanchor="left", x=0, font=dict(size=11.5)))
    elif legend == "off":
        fig.update_layout(showlegend=False)
    fig.update_xaxes(gridcolor=T["grid"], zerolinecolor=T["grid"], linecolor=T["border"],
                     tickfont=dict(size=11, color=T["muted"]), title_font=dict(size=11.5, color=T["muted"]))
    fig.update_yaxes(gridcolor=T["grid"], zerolinecolor=T["grid"], linecolor=T["border"],
                     tickfont=dict(size=11, color=T["muted"]), title_font=dict(size=11.5, color=T["muted"]))
    return fig


# ==============================================================================
# 2. FORMATTING HELPERS
# ==============================================================================

def _isnum(x) -> bool:
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) and not pd.isna(x)


class Fmt:
    """Consistent number formatting. Every figure in the app goes through here
    so units, precision and the em-dash placeholder are uniform."""

    NA = "—"

    @staticmethod
    def money(v, sym="$", dp=2):
        if not _isnum(v):
            return Fmt.NA
        a = abs(v)
        sign = "-" if v < 0 else ""
        for cut, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if a >= cut:
                return f"{sign}{sym}{a / cut:,.{dp}f}{suf}"
        return f"{sign}{sym}{a:,.{dp}f}"

    @staticmethod
    def num(v, dp=2):
        if not _isnum(v):
            return Fmt.NA
        a = abs(v)
        sign = "-" if v < 0 else ""
        for cut, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if a >= cut:
                return f"{sign}{a / cut:,.{dp}f}{suf}"
        return f"{sign}{a:,.{dp}f}"

    @staticmethod
    def price(v, sym="$"):
        return f"{sym}{v:,.2f}" if _isnum(v) else Fmt.NA

    @staticmethod
    def pct(v, dp=1, signed=False):
        """`v` is already in percent units (12.3 means 12.3%)."""
        if not _isnum(v):
            return Fmt.NA
        return f"{v:+,.{dp}f}%" if signed else f"{v:,.{dp}f}%"

    @staticmethod
    def ratio(v, dp=2, suffix="x"):
        return f"{v:,.{dp}f}{suffix}" if _isnum(v) else Fmt.NA

    @staticmethod
    def as_pct(v, dp=1, signed=False):
        """`v` is a fraction (0.123 means 12.3%)."""
        return Fmt.pct(v * 100, dp, signed) if _isnum(v) else Fmt.NA

    @staticmethod
    def date(d):
        if d is None:
            return Fmt.NA
        try:
            return pd.Timestamp(d).strftime("%d %b %Y")
        except Exception:
            return Fmt.NA


def safe_div(n, d):
    if not _isnum(n) or not _isnum(d) or d == 0:
        return None
    return n / d


def cagr(start, end, years):
    if not _isnum(start) or not _isnum(end) or start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1


def pick(info: dict, *keys, default=None):
    """First present, numeric-or-truthy value among `keys`."""
    for k in keys:
        v = info.get(k)
        if v is not None and v != "" and not (isinstance(v, float) and pd.isna(v)):
            return v
    return default


def yield_as_fraction(v):
    """yfinance has reported dividendYield both as a fraction (0.0044) and as a
    percentage (0.44) across versions. Anything above 1 is treated as percent."""
    if not _isnum(v):
        return None
    return v / 100.0 if v > 1 else v


def de_as_ratio(v):
    """`debtToEquity` comes back as a percentage (e.g. 154.0 = 1.54x)."""
    if not _isnum(v):
        return None
    return v / 100.0 if abs(v) > 5 else v


# ==============================================================================
# 3. DATA LAYER
# ==============================================================================
# Everything that touches the network lives here. Three rules:
#   * Cached: a widget interaction must never trigger a refetch.
#   * Serialisable: cached functions return dicts / DataFrames, never yfinance
#     objects, so Streamlit can actually store them.
#   * Thread-safe: the `_fetch_*` primitives call no Streamlit APIs, so they can
#     be fanned out across a thread pool by the cached aggregate loaders.

MAX_WORKERS = 8
_LOAD_ERRORS_KEY = "_load_errors"


def note_error(scope: str, exc: Exception):
    """Records a data-loading problem for the provenance panel instead of
    silently swallowing it (the previous code used bare `except: pass`)."""
    errs = st.session_state.setdefault(_LOAD_ERRORS_KEY, [])
    msg = f"{scope}: {type(exc).__name__}: {exc}"[:220]
    if msg not in errs:
        errs.append(msg)


def parallel_map(fn, items, workers=MAX_WORKERS):
    """Fans work out across threads. Used for the peer and leaderboard tables,
    where the old sequential `.info` loop was the dominant cost (N round trips
    end to end instead of N/workers)."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(fn, items))


def _retry(fn, attempts=2, pause=0.4):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - surfaced by the caller
            last = exc
            if i + 1 < attempts:
                import time as _t
                _t.sleep(pause * (i + 1))
    raise last


# --- primitives (no Streamlit calls; safe inside threads) ---------------------

def _fetch_info(ticker: str) -> dict:
    try:
        return dict(_retry(lambda: yf.Ticker(ticker).info) or {})
    except Exception:
        return {}


def _fetch_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = _retry(lambda: yf.Ticker(ticker).history(period=period, interval=interval))
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _norm_stmt(df) -> pd.DataFrame:
    """yfinance returns line items in the index and periods in the columns.
    The app wants periods on the index, oldest first."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.T
    try:
        out = out.sort_index(ascending=True)
    except Exception:
        pass
    return out.loc[:, ~out.columns.duplicated()]


# --- cached loaders ----------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def load_info(ticker: str) -> dict:
    return _fetch_info(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def load_statements(ticker: str, quarterly: bool = False) -> dict:
    t = yf.Ticker(ticker)
    out = {}
    getters = (
        ("inc", "quarterly_income_stmt" if quarterly else "income_stmt"),
        ("bs", "quarterly_balance_sheet" if quarterly else "balance_sheet"),
        ("cf", "quarterly_cash_flow" if quarterly else "cash_flow"),
    )
    for key, attr in getters:
        try:
            out[key] = _norm_stmt(getattr(t, attr))
        except Exception:
            out[key] = pd.DataFrame()
    return out


@st.cache_data(ttl=900, show_spinner=False)
def load_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    return _fetch_history(ticker, period, interval)


@st.cache_data(ttl=1800, show_spinner=False)
def load_risk_free_rate() -> float:
    """US 10-year yield, used as the CAPM risk-free rate. Falls back to a
    documented constant so the DCF never dies on a network hiccup."""
    try:
        h = yf.Ticker("^TNX").history(period="5d")
        if not h.empty:
            v = float(h["Close"].iloc[-1]) / 100.0
            if 0 < v < 0.25:
                return v
    except Exception:
        pass
    return 0.042


@st.cache_data(ttl=3600, show_spinner=False)
def load_batch_close(tickers: tuple, start, end) -> pd.DataFrame:
    """One bulk price download instead of one request per ticker."""
    if not tickers:
        return pd.DataFrame()
    try:
        raw = yf.download(list(tickers), start=start, end=end, progress=False,
                          auto_adjust=True, group_by="column")
        if raw is None or raw.empty:
            return pd.DataFrame()
        close = raw["Close"] if "Close" in raw else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])
        return close
    except Exception:
        return pd.DataFrame()


class CurrencyFX:
    """Currency conversion.

    Two things make this trickier than a single ticker lookup:
    1. Yahoo quotes EUR/GBP/AUD/NZD as "{CUR}USD=X" (base currency first), but
       quotes almost everything else (JPY, VND, CNY, CHF, CAD, ...) as
       "USD{CUR}=X". Mixing these up silently produces an inverted rate.
    2. Many UK-listed tickers report their price AND their `currency` field in
       pence ("GBp"/"GBX"), not pounds; 1 GBP = 100 GBp. "USDGBp=X" does not
       exist on Yahoo, so a naive lookup falls back to 1.0 - wrong by ~100x.
    """

    MAJORS = ("EUR", "GBP", "AUD", "NZD")
    PENCE = ("GBp", "GBX")

    @staticmethod
    def _usd_per_unit(curr: str):
        if curr == "USD":
            return 1.0
        primary = (f"{curr}USD=X", False) if curr in CurrencyFX.MAJORS else (f"USD{curr}=X", True)
        fallback = (f"USD{curr}=X", True) if curr in CurrencyFX.MAJORS else (f"{curr}USD=X", False)
        for symbol, invert in (primary, fallback):
            try:
                hist = yf.Ticker(symbol).history(period="5d")
                if not hist.empty:
                    px_ = float(hist["Close"].iloc[-1])
                    if px_ > 0:
                        return (1.0 / px_) if invert else px_
            except Exception:
                continue
        return None

    @staticmethod
    def rate(from_curr: str, to_curr: str):
        """Returns the multiplier, or None when the pair genuinely could not be
        resolved. Never silently returns 1.0 for a real cross-currency pair."""
        if not from_curr or not to_curr:
            return 1.0
        if from_curr == to_curr:
            return 1.0
        pence_from, pence_to = from_curr in CurrencyFX.PENCE, to_curr in CurrencyFX.PENCE
        a = "GBP" if pence_from else from_curr
        b = "GBP" if pence_to else to_curr
        if a == b and pence_from == pence_to:
            return 1.0
        ua, ub = CurrencyFX._usd_per_unit(a), CurrencyFX._usd_per_unit(b)
        if ua is None or ub is None:
            return None
        r = ua / ub
        if pence_from:
            r /= 100.0
        if pence_to:
            r *= 100.0
        return r


@st.cache_data(ttl=3600, show_spinner=False)
def load_fx(from_curr: str, to_curr: str):
    return CurrencyFX.rate(from_curr, to_curr)


CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "VND": "₫", "GBP": "£", "GBp": "p", "GBX": "p",
    "JPY": "¥", "CNY": "¥", "CHF": "CHF ", "HKD": "HK$", "SGD": "S$",
    "KRW": "₩", "INR": "₹", "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "SEK": "kr ",
}

SECTOR_ETF_MAP = {
    "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Energy": "XLE",
    "Communication Services": "XLC", "Industrials": "XLI", "Utilities": "XLU",
    "Real Estate": "XLRE", "Basic Materials": "XLB",
}

EXCHANGE_LABELS = {
    "": "United States", "DE": "Germany (Xetra)", "VN": "Vietnam (HOSE)", "L": "United Kingdom (LSE)",
    "T": "Japan (Tokyo)", "SS": "China (Shanghai)", "HK": "Hong Kong", "SW": "Switzerland",
    "PA": "France (Euronext)", "MI": "Italy (Borsa)", "AS": "Netherlands", "TO": "Canada (TSX)",
    "AX": "Australia (ASX)", "KS": "South Korea (KRX)", "TW": "Taiwan", "SI": "Singapore",
    "MC": "Spain (BME)", "ST": "Sweden", "OL": "Norway", "BR": "Belgium",
}


def market_label(ticker: str) -> str:
    suffix = ticker.split(".")[-1].upper() if ticker and "." in ticker else ""
    return EXCHANGE_LABELS.get(suffix, suffix or "International")


# --- News -------------------------------------------------------------------

def _parse_news_item(n):
    """yfinance's `.news` schema has changed across library versions - some
    return a flat dict (title/publisher/link/providerPublishTime), newer ones
    nest the article under a 'content' key with different field names. Both
    shapes are handled so this does not silently break on an upgrade."""
    try:
        c = n.get("content") if isinstance(n.get("content"), dict) else n
        title = c.get("title") or n.get("title")
        if not title:
            return None
        publisher = None
        provider = c.get("provider")
        if isinstance(provider, dict):
            publisher = provider.get("displayName")
        publisher = publisher or c.get("publisher") or n.get("publisher") or "Unknown source"
        link = None
        click = c.get("clickThroughUrl")
        if isinstance(click, dict):
            link = click.get("url")
        if not link:
            canonical = c.get("canonicalUrl")
            if isinstance(canonical, dict):
                link = canonical.get("url")
        link = link or c.get("link") or n.get("link") or ""
        ts = c.get("pubDate") or n.get("providerPublishTime")
        pub_dt = None
        if isinstance(ts, (int, float)):
            pub_dt = datetime.fromtimestamp(ts)
        elif isinstance(ts, str):
            try:
                pub_dt = pd.to_datetime(ts).tz_localize(None).to_pydatetime()
            except Exception:
                pub_dt = None
        return {"title": title, "publisher": publisher, "link": link, "time": pub_dt}
    except Exception:
        return None


def _fetch_news(ticker, max_items):
    out = []
    try:
        for n in (yf.Ticker(ticker).news or [])[:max_items]:
            parsed = _parse_news_item(n)
            if parsed:
                out.append(parsed)
    except Exception:
        pass
    return out


@st.cache_data(ttl=900, show_spinner=False)
def load_news(ticker: str, sector: str, max_items: int = 6):
    """Company headlines plus headlines for a representative sector ETF.
    Both legs are fetched in parallel; refreshed every 15 minutes."""
    etf = SECTOR_ETF_MAP.get(sector)
    targets = [ticker] + ([etf] if etf else [])
    results = parallel_map(lambda t: _fetch_news(t, max_items), targets, workers=2)
    company = results[0] if results else []
    sector_news = results[1] if len(results) > 1 else []
    return company, sector_news, etf


def time_ago(dt):
    if not dt:
        return ""
    delta = datetime.now() - dt
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    return f"{max(delta.seconds // 60, 1)}m ago"


# --- Discovery --------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def search_ticker(query: str, max_results: int = 8):
    """Live query against Yahoo's own search index rather than a bundled lookup
    table, which would go stale on renames, delistings and new listings."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    try:
        params = urllib.parse.urlencode({
            "q": query, "quotesCount": max_results, "newsCount": 0,
            "listsCount": 0, "enableFuzzyQuery": True,
        })
        url = f"https://query2.finance.yahoo.com/v1/finance/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = []
        for q in data.get("quotes", []):
            symbol, qtype = q.get("symbol"), q.get("quoteType", "")
            if symbol and qtype in ("EQUITY", "ETF"):
                results.append({
                    "symbol": symbol,
                    "name": q.get("shortname") or q.get("longname") or symbol,
                    "exchange": q.get("exchange") or q.get("exchDisp") or "",
                })
        return results
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def sector_top_holdings(etf_symbol: str, max_n: int = 15):
    """A sector SPDR ETF is market-cap weighted, so its top holdings *are* that
    sector's current leaders - and they rotate automatically as the market does."""
    try:
        funds = yf.Ticker(etf_symbol).funds_data
        top = funds.top_holdings if funds is not None else None
        if top is None or top.empty:
            return []
        return [str(s).upper() for s in top.index.tolist()][:max_n]
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def ticker_names(tickers: tuple) -> dict:
    known = {"SPY": "SPDR S&P 500 ETF Trust", "QQQ": "Invesco QQQ Trust (Nasdaq-100)"}
    todo = [t for t in tickers if t not in known]
    infos = parallel_map(_fetch_info, todo)
    out = dict(known)
    for t, i in zip(todo, infos):
        out[t] = i.get("shortName") or i.get("longName") or ""
    return {t: out.get(t, "") for t in tickers}


@st.cache_data(ttl=3600, show_spinner=False)
def filter_by_sector(tickers: tuple, sector_name: str):
    """Keeps tickers whose own live-reported sector matches - lets a Market pool
    and a Sector filter be combined, which ETF holdings alone cannot do."""
    infos = parallel_map(_fetch_info, tickers)
    return [t for t, i in zip(tickers, infos) if i.get("sector") == sector_name]


@st.cache_data(ttl=3600, show_spinner=False)
def suggest_peers(ticker: str, sector: str, industry: str, max_n: int = 8):
    """Peers matched on the finer-grained `industry` classification where
    possible, falling back to same-sector names. Candidates come from the
    sector ETF's live top holdings rather than a hardcoded five-name list."""
    etf = SECTOR_ETF_MAP.get(sector)
    if not etf:
        return []
    candidates = [c for c in sector_top_holdings(etf, max_n=20) if c.upper() != ticker.upper()]
    if not candidates:
        return []
    infos = parallel_map(_fetch_info, candidates)
    same_industry, same_sector = [], []
    for c, i in zip(candidates, infos):
        if industry and i.get("industry") == industry:
            same_industry.append(c)
        elif i.get("sector") == sector:
            same_sector.append(c)
    result = same_industry if len(same_industry) >= 3 else (same_industry + same_sector)
    return result[:max_n]


@st.cache_data(ttl=900, show_spinner=False)
def load_comparables(tickers: tuple, target_currency: str) -> pd.DataFrame:
    """The peer matrix, fetched concurrently. Previously this was a serial loop
    of `.info` calls with a bare `except: pass`, which made a 10-name peer group
    roughly ten round trips long."""
    if not tickers:
        return pd.DataFrame()
    infos = parallel_map(_fetch_info, tickers)
    currencies = {i.get("currency", "USD") for i in infos if i}
    fx_map = {c: (load_fx(c, target_currency) or 1.0) for c in currencies}

    rows = []
    for t, i in zip(tickers, infos):
        if not i:
            continue
        price = pick(i, "currentPrice", "regularMarketPrice", "previousClose")
        if not _isnum(price):
            continue
        fx = fx_map.get(i.get("currency", "USD"), 1.0)
        pe = i.get("trailingPE")
        ev_ebitda = i.get("enterpriseToEbitda")
        # Guard the charts against multiples that are meaningless or off-scale.
        if _isnum(pe) and (pe > 500 or pe < 0):
            pe = None
        if _isnum(ev_ebitda) and (ev_ebitda > 200 or ev_ebitda < 0):
            ev_ebitda = None
        fcf, mcap = i.get("freeCashflow"), i.get("marketCap")
        rows.append({
            "Ticker": t,
            "Name": i.get("shortName") or i.get("longName") or t,
            "Price": price * fx,
            "P/E": pe,
            "Fwd P/E": i.get("forwardPE"),
            "P/B": i.get("priceToBook"),
            "EV/Sales": i.get("priceToSalesTrailing12Months"),
            "EV/EBITDA": ev_ebitda,
            "FCF Yield (%)": (safe_div(fcf, mcap) or 0) * 100 if _isnum(fcf) and _isnum(mcap) else None,
            "Op Margin (%)": (i.get("operatingMargins") or 0) * 100 if _isnum(i.get("operatingMargins")) else None,
            "ROE (%)": (i.get("returnOnEquity") or 0) * 100 if _isnum(i.get("returnOnEquity")) else None,
            "Revenue Growth (%)": (i.get("revenueGrowth") or 0) * 100 if _isnum(i.get("revenueGrowth")) else None,
            "Net Debt/EBITDA": safe_div((i.get("totalDebt") or 0) - (i.get("totalCash") or 0), i.get("ebitda")),
            "Market Cap": (mcap or 0) * fx,
        })
    return pd.DataFrame(rows).set_index("Ticker") if rows else pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def load_leaderboard(tickers: tuple, target_currency: str, as_of: str) -> pd.DataFrame:
    """Leaderboard rows: one bulk price download plus a concurrent profile
    fetch, instead of two sequential network calls per company."""
    if not tickers:
        return pd.DataFrame()
    as_of_date = pd.Timestamp(as_of).date()
    closes = load_batch_close(tickers, as_of_date - timedelta(days=7), as_of_date + timedelta(days=1))
    infos = parallel_map(_fetch_info, tickers)
    currencies = {i.get("currency", "USD") for i in infos if i}
    fx_map = {c: (load_fx(c, target_currency) or 1.0) for c in currencies}

    rows = []
    for t, i in zip(tickers, infos):
        if not i:
            continue
        price = None
        if isinstance(closes, pd.DataFrame) and t in closes.columns:
            s = closes[t].dropna()
            if not s.empty:
                price = float(s.iloc[-1])
        if price is None:
            price = pick(i, "currentPrice", "regularMarketPrice", "previousClose")
        if not _isnum(price):
            continue
        fx = fx_map.get(i.get("currency", "USD"), 1.0)
        shares = pick(i, "sharesOutstanding", "impliedSharesOutstanding", default=0) or 0
        rows.append({
            "Ticker": t,
            "Name": i.get("longName") or i.get("shortName") or t,
            "Market": market_label(t),
            "Industry": i.get("industry", Fmt.NA),
            "Price": price * fx,
            "Market Cap": price * shares * fx,
            "Revenue": (i.get("totalRevenue") or 0) * fx,
            "Net Margin (%)": (i.get("profitMargins") or 0) * 100 if _isnum(i.get("profitMargins")) else None,
            "_shares": shares,
            "_fx": fx,
        })
    df = pd.DataFrame(rows)
    return df.sort_values("Market Cap", ascending=False).reset_index(drop=True) if not df.empty else df


# --- Company facade ---------------------------------------------------------

def ttm_from_quarters(df_q: pd.DataFrame) -> pd.DataFrame:
    """Trailing-twelve-month flow statement: the last four reported quarters
    summed. Returned as a one-row frame stamped with the latest quarter end."""
    if df_q is None or df_q.empty:
        return pd.DataFrame()
    tail = df_q.tail(4)
    if tail.empty:
        return pd.DataFrame()
    return pd.DataFrame([tail.sum(min_count=1)], index=[tail.index[-1]])


class Company:
    """A thin, lazy facade over the cached loaders. Constructing one costs
    nothing; each statement is fetched the first time it is actually read."""

    def __init__(self, ticker: str):
        self.ticker = (ticker or "").upper().strip()
        self.info = load_info(self.ticker) if self.ticker else {}

    # -- identity ------------------------------------------------------------
    @property
    def name(self):
        return self.info.get("longName") or self.info.get("shortName") or self.ticker

    @property
    def currency(self):
        return self.info.get("currency", "USD")

    @property
    def sector(self):
        return self.info.get("sector") or Fmt.NA

    @property
    def industry(self):
        return self.info.get("industry") or Fmt.NA

    # -- statements ----------------------------------------------------------
    @cached_property
    def annual(self):
        return load_statements(self.ticker, quarterly=False)

    @cached_property
    def quarterly(self):
        return load_statements(self.ticker, quarterly=True)

    @property
    def inc(self):
        return self.annual["inc"]

    @property
    def bs(self):
        return self.annual["bs"]

    @property
    def cf(self):
        return self.annual["cf"]

    def basis_statements(self, basis: str):
        """Returns (income, balance sheet, cash flow) on the requested basis.
        Balance sheet items are stocks, not flows, so TTM uses the most recent
        quarterly balance sheet rather than a sum."""
        if basis == "Quarterly":
            q = self.quarterly
            return q["inc"], q["bs"], q["cf"]
        if basis == "TTM":
            q = self.quarterly
            bs = q["bs"].tail(1) if not q["bs"].empty else self.bs.tail(1)
            return ttm_from_quarters(q["inc"]), bs, ttm_from_quarters(q["cf"])
        return self.inc, self.bs, self.cf

    # -- market data ---------------------------------------------------------
    @cached_property
    def price(self):
        p = pick(self.info, "currentPrice", "regularMarketPrice", "previousClose")
        if _isnum(p):
            return float(p)
        h = load_history(self.ticker, "5d", "1d")
        if not h.empty and "Close" in h:
            return float(h["Close"].dropna().iloc[-1])
        return None

    @property
    def previous_close(self):
        v = pick(self.info, "previousClose", "regularMarketPreviousClose")
        return float(v) if _isnum(v) else self.price

    @property
    def shares(self):
        v = pick(self.info, "sharesOutstanding", "impliedSharesOutstanding")
        return float(v) if _isnum(v) and v > 0 else None

    @property
    def market_cap(self):
        v = self.info.get("marketCap")
        if _isnum(v) and v > 0:
            return float(v)
        return (self.price or 0) * (self.shares or 0) or None

    @property
    def net_debt(self):
        debt, cash = self.info.get("totalDebt"), self.info.get("totalCash")
        if _isnum(debt) or _isnum(cash):
            return (debt or 0) - (cash or 0)
        if not self.bs.empty:
            row = self.bs.iloc[-1]
            return (row.get("Total Debt", 0) or 0) - (row.get("Cash And Cash Equivalents", 0) or 0)
        return 0.0

    def history(self, period="1y", interval="1d"):
        return load_history(self.ticker, period, interval)

    @property
    def ok(self):
        return bool(self.info) and (self.price is not None)

    # -- derived -------------------------------------------------------------
    @cached_property
    def base_fcf(self):
        """Latest reported free cash flow, falling back to operating cash flow
        less capex, then to the info snapshot."""
        cf = self.cf
        if not cf.empty:
            if "Free Cash Flow" in cf.columns and _isnum(cf["Free Cash Flow"].iloc[-1]):
                return float(cf["Free Cash Flow"].iloc[-1])
            ocf = cf["Operating Cash Flow"].iloc[-1] if "Operating Cash Flow" in cf.columns else None
            capex = cf["Capital Expenditure"].iloc[-1] if "Capital Expenditure" in cf.columns else None
            if _isnum(ocf):
                return float(ocf) + float(capex if _isnum(capex) else 0)
        v = self.info.get("freeCashflow")
        return float(v) if _isnum(v) else None

    @cached_property
    def normalised_fcf(self):
        """Median free cash flow across reported years - a steadier DCF anchor
        than a single year that may be a peak or a trough."""
        cf = self.cf
        if cf.empty:
            return self.base_fcf
        if "Free Cash Flow" in cf.columns:
            s = cf["Free Cash Flow"].dropna()
        elif "Operating Cash Flow" in cf.columns:
            s = (cf["Operating Cash Flow"].fillna(0) + cf.get("Capital Expenditure", 0)).dropna()
        else:
            return self.base_fcf
        return float(s.median()) if not s.empty else self.base_fcf

    @cached_property
    def risk_stats(self):
        hist = self.history("2y", "1d")
        if hist.empty or "Close" not in hist:
            return {}
        close = hist["Close"].dropna()
        ret = close.pct_change().dropna()
        if ret.empty:
            return {}
        vol = float(ret.std() * np.sqrt(252))
        cum = (1 + ret).cumprod()
        dd = (cum / cum.expanding(min_periods=1).max()) - 1
        downside = ret[ret < 0].std() * np.sqrt(252)
        return {
            "vol": vol,
            "var_95": float(norm.ppf(0.05, ret.mean(), ret.std())),
            "cvar_95": float(ret[ret <= ret.quantile(0.05)].mean()) if len(ret) > 20 else None,
            "max_dd": float(dd.min()),
            "sortino": float((ret.mean() * 252) / downside) if downside and downside > 0 else None,
            "ann_return": float((1 + ret.mean()) ** 252 - 1),
        }


# ==============================================================================
# 4. ANALYTICS ENGINES
# ==============================================================================

class Indicators:
    """Technical indicator library (vectorised, no Python loops)."""

    @staticmethod
    def enrich(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty or "Close" not in df:
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        df = df.copy()
        c = df["Close"]
        for w in (20, 50, 200):
            df[f"SMA_{w}"] = c.rolling(w).mean()
        ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        df["RSI"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
        df["MACD"] = ema12 - ema26
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
        std20 = c.rolling(20).std()
        df["BB_Upper"] = df["SMA_20"] + 2 * std20
        df["BB_Lower"] = df["SMA_20"] - 2 * std20
        if {"High", "Low"}.issubset(df.columns):
            tr = pd.concat([df["High"] - df["Low"],
                            (df["High"] - c.shift()).abs(),
                            (df["Low"] - c.shift()).abs()], axis=1).max(axis=1)
            df["ATR"] = tr.rolling(14).mean()
        if "Volume" in df:
            df["Vol_SMA_20"] = df["Volume"].rolling(20).mean()
        return df


class Scoring:
    @staticmethod
    def altman_z(bs_row, inc_row, mcap):
        """Altman Z-score for public manufacturers. Returns None when the
        inputs needed for a meaningful score are missing, rather than 0, which
        previously read as 'imminent distress'."""
        try:
            ta = bs_row.get("Total Assets")
            tl = bs_row.get("Total Liabilities Net Minority Interest")
            if not _isnum(ta) or ta <= 0 or not _isnum(tl) or tl <= 0:
                return None
            wc = (bs_row.get("Current Assets") or 0) - (bs_row.get("Current Liabilities") or 0)
            re_ = bs_row.get("Retained Earnings") or 0
            ebit = inc_row.get("EBIT") or inc_row.get("Operating Income") or 0
            sales = inc_row.get("Total Revenue") or 0
            if not _isnum(mcap) or mcap <= 0:
                return None
            return float(1.2 * wc / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * mcap / tl + 1.0 * sales / ta)
        except Exception:
            return None

    @staticmethod
    def piotroski_f(bs, inc, cf, bs_prev, inc_prev, cf_prev=None):
        """The nine Piotroski tests, returned with the individual results so the
        score can be explained rather than just asserted."""
        tests = []

        def add(label, passed, detail):
            tests.append({"label": label, "pass": bool(passed), "detail": detail})

        try:
            ni, ta = inc.get("Net Income"), bs.get("Total Assets")
            roa = safe_div(ni, ta)
            roa_prev = safe_div(inc_prev.get("Net Income"), bs_prev.get("Total Assets"))
            cfo = cf.get("Operating Cash Flow")
            add("Positive net income", _isnum(ni) and ni > 0, Fmt.num(ni))
            add("Positive operating cash flow", _isnum(cfo) and cfo > 0, Fmt.num(cfo))
            add("Improving return on assets", roa is not None and roa_prev is not None and roa > roa_prev,
                f"{Fmt.as_pct(roa)} vs {Fmt.as_pct(roa_prev)}")
            add("Cash flow exceeds net income", _isnum(cfo) and _isnum(ni) and cfo > ni, "accrual quality")
            lt, lt_prev = bs.get("Long Term Debt") or 0, bs_prev.get("Long Term Debt") or 0
            add("Lower long-term debt", lt <= lt_prev, f"{Fmt.num(lt)} vs {Fmt.num(lt_prev)}")
            cr = safe_div(bs.get("Current Assets"), bs.get("Current Liabilities"))
            cr_prev = safe_div(bs_prev.get("Current Assets"), bs_prev.get("Current Liabilities"))
            add("Improving current ratio", cr is not None and cr_prev is not None and cr > cr_prev,
                f"{Fmt.ratio(cr)} vs {Fmt.ratio(cr_prev)}")
            sh, sh_prev = bs.get("Share Issued"), bs_prev.get("Share Issued")
            add("No share dilution", _isnum(sh) and _isnum(sh_prev) and sh <= sh_prev,
                f"{Fmt.num(sh, 0)} vs {Fmt.num(sh_prev, 0)}")
            gm = safe_div(inc.get("Gross Profit"), inc.get("Total Revenue"))
            gm_prev = safe_div(inc_prev.get("Gross Profit"), inc_prev.get("Total Revenue"))
            add("Improving gross margin", gm is not None and gm_prev is not None and gm > gm_prev,
                f"{Fmt.as_pct(gm)} vs {Fmt.as_pct(gm_prev)}")
            at = safe_div(inc.get("Total Revenue"), ta)
            at_prev = safe_div(inc_prev.get("Total Revenue"), bs_prev.get("Total Assets"))
            add("Improving asset turnover", at is not None and at_prev is not None and at > at_prev,
                f"{Fmt.ratio(at)} vs {Fmt.ratio(at_prev)}")
        except Exception:
            pass
        return sum(1 for t in tests if t["pass"]), tests


class Valuation:
    @staticmethod
    def dcf(fcf, g1, years1, g2, wacc, terminal_g, net_debt, shares, years2=5):
        """Three-phase DCF: an explicit high-growth stage, a fade stage, then a
        Gordon-growth terminal value. Returns the components so the result can
        be shown as a bridge rather than a single opaque number."""
        if not all(_isnum(x) for x in (fcf, g1, wacc, terminal_g, shares)) or not shares:
            return None
        if wacc <= terminal_g:
            wacc = terminal_g + 0.015  # keep the Gordon denominator positive
        flows, cur = [], float(fcf)
        for _ in range(int(years1)):
            cur *= (1 + g1)
            flows.append(cur)
        for _ in range(int(years2)):
            cur *= (1 + g2)
            flows.append(cur)
        n = len(flows)
        pv_flows = [f / ((1 + wacc) ** (i + 1)) for i, f in enumerate(flows)]
        terminal = flows[-1] * (1 + terminal_g) / (wacc - terminal_g)
        pv_terminal = terminal / ((1 + wacc) ** n)
        ev = sum(pv_flows) + pv_terminal
        equity = ev - (net_debt or 0)
        return {
            "fair_value": equity / shares,
            "enterprise_value": ev,
            "equity_value": equity,
            "pv_explicit": sum(pv_flows),
            "pv_terminal": pv_terminal,
            "terminal_share": safe_div(pv_terminal, ev),
            "projected_fcf": flows,
            "wacc_used": wacc,
        }

    @staticmethod
    def implied_growth(price, fcf, years1, g2, wacc, terminal_g, net_debt, shares):
        """Reverse DCF: the stage-1 growth rate that makes the model agree with
        today's market price - i.e. what the market is already assuming."""
        if not all(_isnum(x) for x in (price, fcf, shares)) or price <= 0 or not shares or not fcf:
            return None
        lo, hi = -0.60, 1.00

        def fv(g):
            r = Valuation.dcf(fcf, g, years1, g2, wacc, terminal_g, net_debt, shares)
            return r["fair_value"] if r else None

        f_lo, f_hi = fv(lo), fv(hi)
        if f_lo is None or f_hi is None or not (f_lo <= price <= f_hi):
            return None
        for _ in range(60):
            mid = (lo + hi) / 2
            if fv(mid) < price:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    @staticmethod
    def graham_number(eps, bvps):
        if not _isnum(eps) or not _isnum(bvps) or eps <= 0 or bvps <= 0:
            return None
        return float(np.sqrt(22.5 * eps * bvps))

    @staticmethod
    def lynch_value(eps, growth_pct):
        if not _isnum(eps) or eps <= 0 or not _isnum(growth_pct) or growth_pct <= 0:
            return None
        return float(eps * min(growth_pct, 25.0))

    @staticmethod
    def capm_wacc(beta, risk_free, erp, cost_debt, tax_rate, mcap, debt):
        beta = beta if _isnum(beta) else 1.0
        cost_equity = risk_free + beta * erp
        total = (mcap or 0) + (debt or 0)
        if total <= 0:
            return cost_equity, cost_equity, 1.0, 0.0
        w_e, w_d = (mcap or 0) / total, (debt or 0) / total
        wacc = w_e * cost_equity + w_d * cost_debt * (1 - tax_rate)
        return wacc, cost_equity, w_e, w_d


# --- Composite scorecard -----------------------------------------------------

def scale(v, lo, hi):
    """Maps a metric onto 0-100. `lo` scores 0 and `hi` scores 100; passing
    lo > hi expresses a lower-is-better metric."""
    if not _isnum(v):
        return None
    if lo == hi:
        return 50.0
    return float(np.clip((v - lo) / (hi - lo) * 100, 0, 100))


@dataclass
class Pillar:
    name: str
    weight: float
    drivers: list = field(default_factory=list)  # (label, display, score)

    @property
    def score(self):
        vals = [s for _, _, s in self.drivers if s is not None]
        return float(np.mean(vals)) if vals else None


SCORE_BANDS = [
    (80, "Exceptional", "Screens strongly on nearly every pillar measured here."),
    (65, "Strong", "Screens well overall, with one or two softer pillars."),
    (50, "Solid", "A balanced profile: clear strengths offset by clear weaknesses."),
    (35, "Mixed", "More weak pillars than strong ones on these measures."),
    (0, "Fragile", "Weak across most pillars measured here; treat with care."),
]


def build_scorecard(co: Company, extras: dict) -> dict:
    """A transparent composite: five weighted pillars, each an average of the
    sub-metrics that could actually be computed. Missing inputs are skipped and
    the weights renormalise, so a thinly reported company is not punished for
    gaps in the data feed."""
    i = co.info
    pillars = []

    fcf_yield = safe_div(co.base_fcf, co.market_cap)
    pe, peg = i.get("trailingPE"), pick(i, "pegRatio", "trailingPegRatio")
    pillars.append(Pillar("Valuation", 0.25, [
        ("FCF yield", Fmt.as_pct(fcf_yield), scale((fcf_yield or 0) * 100 if fcf_yield is not None else None, 0, 8)),
        ("Trailing P/E", Fmt.ratio(pe), (scale(pe, 45, 10) if _isnum(pe) and pe > 0 else (10.0 if _isnum(pe) else None))),
        ("PEG", Fmt.ratio(peg), scale(peg, 3.0, 0.8) if _isnum(peg) and peg > 0 else None),
        ("EV/EBITDA", Fmt.ratio(i.get("enterpriseToEbitda")), scale(i.get("enterpriseToEbitda"), 25, 6)),
    ]))

    pillars.append(Pillar("Profitability", 0.20, [
        ("Return on equity", Fmt.as_pct(i.get("returnOnEquity")), scale((i.get("returnOnEquity") or 0) * 100 if _isnum(i.get("returnOnEquity")) else None, 0, 25)),
        ("Return on assets", Fmt.as_pct(i.get("returnOnAssets")), scale((i.get("returnOnAssets") or 0) * 100 if _isnum(i.get("returnOnAssets")) else None, 0, 12)),
        ("Operating margin", Fmt.as_pct(i.get("operatingMargins")), scale((i.get("operatingMargins") or 0) * 100 if _isnum(i.get("operatingMargins")) else None, 0, 30)),
        ("Net margin", Fmt.as_pct(i.get("profitMargins")), scale((i.get("profitMargins") or 0) * 100 if _isnum(i.get("profitMargins")) else None, 0, 20)),
    ]))

    de = de_as_ratio(i.get("debtToEquity"))
    nd_ebitda = safe_div(co.net_debt, i.get("ebitda"))
    pillars.append(Pillar("Financial health", 0.20, [
        ("Current ratio", Fmt.ratio(i.get("currentRatio")), scale(i.get("currentRatio"), 0.8, 2.5)),
        ("Debt / equity", Fmt.ratio(de), scale(de, 2.5, 0.2)),
        ("Net debt / EBITDA", Fmt.ratio(nd_ebitda), scale(nd_ebitda, 4.0, 0.0)),
        ("Altman Z", Fmt.ratio(extras.get("z_score"), suffix=""), scale(extras.get("z_score"), 1.1, 3.5)),
        ("Interest cover", Fmt.ratio(extras.get("interest_cover")), scale(extras.get("interest_cover"), 1.0, 12.0)),
    ]))

    pillars.append(Pillar("Growth", 0.20, [
        ("Revenue CAGR (3y)", Fmt.as_pct(extras.get("rev_cagr")), scale((extras.get("rev_cagr") or 0) * 100 if extras.get("rev_cagr") is not None else None, 0, 20)),
        ("Earnings growth", Fmt.as_pct(i.get("earningsGrowth")), scale((i.get("earningsGrowth") or 0) * 100 if _isnum(i.get("earningsGrowth")) else None, -10, 25)),
        ("FCF CAGR (3y)", Fmt.as_pct(extras.get("fcf_cagr")), scale((extras.get("fcf_cagr") or 0) * 100 if extras.get("fcf_cagr") is not None else None, -5, 15)),
    ]))

    pillars.append(Pillar("Momentum & quality", 0.15, [
        ("Piotroski F", f"{extras.get('f_score')}/9" if extras.get("f_score") is not None else Fmt.NA,
         scale(extras.get("f_score"), 2, 8)),
        ("Price vs 200-day", Fmt.as_pct(extras.get("vs_sma200"), signed=True),
         scale((extras.get("vs_sma200") or 0) * 100 if extras.get("vs_sma200") is not None else None, -25, 25)),
        ("52-week position", Fmt.as_pct(extras.get("range_pos")), scale((extras.get("range_pos") or 0) * 100 if extras.get("range_pos") is not None else None, 0, 100)),
        ("Cash conversion", Fmt.ratio(extras.get("cash_conversion")), scale(extras.get("cash_conversion"), 0.5, 1.5)),
    ]))

    scored = [p for p in pillars if p.score is not None]
    wsum = sum(p.weight for p in scored)
    total = sum(p.score * p.weight for p in scored) / wsum if wsum else None
    band, blurb = "Not enough data", "Too many inputs are missing to score this company."
    if total is not None:
        for cut, b, text in SCORE_BANDS:
            if total >= cut:
                band, blurb = b, text
                break
    coverage = sum(len([d for d in p.drivers if d[2] is not None]) for p in pillars)
    total_drivers = sum(len(p.drivers) for p in pillars)
    return {"total": total, "band": band, "blurb": blurb, "pillars": pillars,
            "coverage": coverage, "total_drivers": total_drivers}


def quality_flags(co: Company, extras: dict) -> list:
    """A short earnings-quality checklist. Each row states the test, the
    measured value, and what a failure would imply - so the conclusion is
    auditable rather than asserted."""
    i, out = co.info, []

    def add(label, state, value, detail):
        out.append({"label": label, "state": state, "value": value, "detail": detail})

    cc = extras.get("cash_conversion")
    add("Cash conversion", "na" if cc is None else ("pass" if cc >= 1 else "warn" if cc >= 0.8 else "fail"),
        Fmt.ratio(cc), "Operating cash flow versus net income. Below 1.0 for several years suggests profit is not turning into cash.")

    acc = extras.get("accruals")
    add("Accruals ratio", "na" if acc is None else ("pass" if acc <= 0.05 else "warn" if acc <= 0.10 else "fail"),
        Fmt.as_pct(acc), "(Net income minus operating cash flow) over total assets. High accruals often precede earnings disappointments.")

    dil = extras.get("dilution")
    add("Share count", "na" if dil is None else ("pass" if dil <= 0.005 else "warn" if dil <= 0.03 else "fail"),
        Fmt.as_pct(dil, signed=True), "Year-on-year change in shares issued. Persistent growth dilutes existing holders' claim on earnings.")

    gm = extras.get("gm_delta")
    add("Gross margin trend", "na" if gm is None else ("pass" if gm >= 0 else "warn" if gm > -0.02 else "fail"),
        Fmt.as_pct(gm, signed=True), "Change in gross margin versus the prior year. Sustained erosion points to pricing or input-cost pressure.")

    ic = extras.get("interest_cover")
    add("Interest cover", "na" if ic is None else ("pass" if ic >= 5 else "warn" if ic >= 2 else "fail"),
        Fmt.ratio(ic), "Operating profit over interest expense. Below about 2x leaves little room if earnings fall.")

    nde = safe_div(co.net_debt, i.get("ebitda"))
    add("Net debt / EBITDA", "na" if nde is None else ("pass" if nde <= 2 else "warn" if nde <= 3.5 else "fail"),
        Fmt.ratio(nde), "Leverage relative to cash earnings. Above roughly 3.5x is where refinancing risk starts to matter.")

    fcf = co.base_fcf
    add("Free cash flow", "na" if fcf is None else ("pass" if fcf > 0 else "fail"), Fmt.num(fcf),
        "Cash left after capital spending. Negative FCF means growth is currently funded by debt or share issuance.")

    rr = extras.get("receivable_gap")
    add("Receivables vs revenue", "na" if rr is None else ("pass" if rr <= 0.05 else "warn" if rr <= 0.15 else "fail"),
        Fmt.as_pct(rr, signed=True), "Receivables growing materially faster than revenue can signal looser credit terms pulling sales forward.")
    return out


def compute_extras(co: Company) -> dict:
    """Derived inputs shared by the scorecard, the quality checklist and the
    executive summary. Computed once per run from already-cached statements."""
    e, inc, bs, cf = {}, co.inc, co.bs, co.cf
    i = co.info

    if not inc.empty and "Total Revenue" in inc.columns:
        rev = inc["Total Revenue"].dropna()
        if len(rev) >= 2:
            e["rev_cagr"] = cagr(rev.iloc[0], rev.iloc[-1], len(rev) - 1)
    if not cf.empty:
        fcf_col = cf["Free Cash Flow"] if "Free Cash Flow" in cf.columns else None
        if fcf_col is not None:
            s = fcf_col.dropna()
            if len(s) >= 2 and s.iloc[0] > 0:
                e["fcf_cagr"] = cagr(s.iloc[0], s.iloc[-1], len(s) - 1)
        ocf = cf["Operating Cash Flow"].iloc[-1] if "Operating Cash Flow" in cf.columns else None
        ni = inc["Net Income"].iloc[-1] if not inc.empty and "Net Income" in inc.columns else None
        e["cash_conversion"] = safe_div(ocf, ni) if _isnum(ni) and ni > 0 else None
        ta = bs["Total Assets"].iloc[-1] if not bs.empty and "Total Assets" in bs.columns else None
        if _isnum(ni) and _isnum(ocf) and _isnum(ta) and ta:
            e["accruals"] = (ni - ocf) / ta

    if not inc.empty and len(inc) >= 2:
        ebit = inc["EBIT"] if "EBIT" in inc.columns else inc.get("Operating Income")
        int_exp = inc.get("Interest Expense")
        if ebit is not None and int_exp is not None and _isnum(int_exp.iloc[-1]) and abs(int_exp.iloc[-1]) > 0:
            e["interest_cover"] = abs(safe_div(ebit.iloc[-1], abs(int_exp.iloc[-1])) or 0)
        if "Gross Profit" in inc.columns and "Total Revenue" in inc.columns:
            gm = (inc["Gross Profit"] / inc["Total Revenue"]).dropna()
            if len(gm) >= 2:
                e["gm_delta"] = float(gm.iloc[-1] - gm.iloc[-2])
        if "Total Revenue" in inc.columns and not bs.empty and "Accounts Receivable" in bs.columns:
            rev_g = inc["Total Revenue"].pct_change().iloc[-1]
            ar_g = bs["Accounts Receivable"].pct_change().iloc[-1]
            if _isnum(rev_g) and _isnum(ar_g):
                e["receivable_gap"] = float(ar_g - rev_g)

    if not bs.empty and "Share Issued" in bs.columns and len(bs) >= 2:
        sh = bs["Share Issued"].dropna()
        if len(sh) >= 2 and sh.iloc[-2]:
            e["dilution"] = float(sh.iloc[-1] / sh.iloc[-2] - 1)

    if not bs.empty and not inc.empty:
        e["z_score"] = Scoring.altman_z(bs.iloc[-1], inc.iloc[-1], co.market_cap)
        if len(bs) >= 2 and len(inc) >= 2 and not cf.empty:
            e["f_score"], e["f_tests"] = Scoring.piotroski_f(bs.iloc[-1], inc.iloc[-1], cf.iloc[-1],
                                                             bs.iloc[-2], inc.iloc[-2])

    hi, lo = i.get("fiftyTwoWeekHigh"), i.get("fiftyTwoWeekLow")
    if _isnum(hi) and _isnum(lo) and hi > lo and co.price:
        e["range_pos"] = float(np.clip((co.price - lo) / (hi - lo), 0, 1))
    sma200 = i.get("twoHundredDayAverage")
    if _isnum(sma200) and sma200 and co.price:
        e["vs_sma200"] = co.price / sma200 - 1
    return e


# ==============================================================================
# 5. UI COMPONENT LIBRARY  (+ report recording)
# ==============================================================================
# Every visual primitive is defined once here and reused by all nine modules.
# Each one also records itself into REPORT, which is what makes the exportable
# report an exact transcript of what the analyst was looking at.

# Streamlit renamed the "fill the container" argument from `use_container_width`
# to `width="stretch"`. Detect which one the installed version accepts so the app
# runs clean on both, instead of emitting a deprecation warning per widget.
def _fill(fn):
    try:
        import inspect
        return {"width": "stretch"} if "width" in inspect.signature(fn).parameters \
            else {"use_container_width": True}
    except Exception:
        return {"use_container_width": True}


FILL_DF = _fill(st.dataframe)
FILL_CHART = _fill(st.plotly_chart)
FILL_BTN = _fill(st.button)
FILL_DL = _fill(st.download_button)


def md_inline(text: str) -> str:
    """Renders the light markdown used in commentary strings (**bold**, *italic*
    and '- ' bullets) as real HTML.

    Needed because these strings go out through st.markdown(unsafe_allow_html=True),
    which treats the whole string as raw HTML and never runs markdown over it.
    Wrapped source lines are joined into the paragraph or bullet they belong to,
    so a sentence split across two lines in the source does not become two
    paragraphs on the page.
    """
    parts, para, bullets = [], [], []

    def flush_para():
        if para:
            parts.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    def flush_bullets():
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw in (text or "").strip().split("\n"):
        line = raw.strip()
        if not line:
            flush_para()
            flush_bullets()
        elif line.startswith("- "):
            flush_para()
            bullets.append(line[2:].strip())
        elif bullets:
            bullets[-1] = (bullets[-1] + " " + line).strip()
        else:
            para.append(line)
    flush_para()
    flush_bullets()
    html = "".join(parts)
    html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", html)
    # Tidy the artefacts of building sentences from conditional fragments.
    html = re.sub(r"\s+([.,;:])", r"\1", html)
    html = re.sub(r"\s{2,}", " ", html)
    return html


class Report:
    """Collects everything rendered this run so it can be exported."""

    def __init__(self):
        self.blocks = []
        self.section_no = 0
        self.fig_no = 0

    def open_section(self, title, sub=None):
        self.section_no += 1
        self.fig_no = 0
        self.blocks.append({"kind": "section", "n": self.section_no, "title": title, "sub": sub})
        return self.section_no

    def next_figure(self):
        self.fig_no += 1
        return f"{max(self.section_no, 1)}.{self.fig_no}"

    def add(self, kind, **payload):
        self.blocks.append({"kind": kind, **payload})

    # -- export ---------------------------------------------------------------
    def to_html(self, meta: dict) -> str:
        css = """
        body{font-family:Inter,-apple-system,Segoe UI,sans-serif;color:#14172a;background:#fff;
             max-width:1080px;margin:0 auto;padding:44px 30px 90px;line-height:1.6}
        h1{font-size:27px;margin:0 0 4px;letter-spacing:-.02em}
        .sub{color:#5f6980;font-size:13px;margin-bottom:22px}
        h2{font-size:18px;margin:34px 0 4px;padding-top:14px;border-top:1px solid #e4e7f0;letter-spacing:-.01em}
        .secsub{color:#5f6980;font-size:13px;margin:0 0 14px}
        .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:12px 0}
        .kpi{border:1px solid #e4e7f0;border-radius:10px;padding:12px 14px}
        .kpi .l{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#5f6980;font-weight:600}
        .kpi .v{font-family:'IBM Plex Mono',monospace;font-size:21px;font-weight:600;margin-top:4px}
        .kpi .s{font-size:11.5px;color:#5f6980;margin-top:4px}
        .note{border:1px solid #e4e7f0;border-left:3px solid #3d3ab0;background:#f7f8fd;
              border-radius:8px;padding:12px 15px;margin:12px 0;font-size:13.5px}
        .note.pos{border-left-color:#0f8f5c;background:#f2fbf6}
        .note.neg{border-left-color:#cf2c1e;background:#fdf5f4}
        .note.warn{border-left-color:#b8760a;background:#fffaef}
        .cap{font-size:12.5px;color:#5f6980;border-top:1px solid #e4e7f0;padding-top:7px;margin:2px 0 20px}
        .cap b{color:#14172a}.capn{font-family:'IBM Plex Mono',monospace;color:#3d3ab0;margin-right:6px}
        .exp{font-size:12.5px;color:#3f465c;margin-top:6px}
        table{border-collapse:collapse;width:100%;font-size:12.5px;margin:10px 0 20px}
        th,td{border-bottom:1px solid #e9ebf2;padding:7px 9px;text-align:right}
        th:first-child,td:first-child{text-align:left}
        th{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:#5f6980;font-weight:600}
        .foot{margin-top:44px;border-top:1px solid #e4e7f0;padding-top:14px;font-size:11.5px;color:#8b93a7}
        """
        head = (f"<!doctype html><html><head><meta charset='utf-8'><title>{meta['title']}</title>"
                f"<style>{css}</style>"
                "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script></head><body>")
        out = [head, f"<h1>{meta['title']}</h1>",
               f"<div class='sub'>{meta['subtitle']}</div>"]
        for b in self.blocks:
            k = b["kind"]
            if k == "section":
                out.append(f"<h2>{b['n']}. {b['title']}</h2>")
                if b.get("sub"):
                    out.append(f"<div class='secsub'>{b['sub']}</div>")
            elif k == "kpis":
                cards = "".join(
                    f"<div class='kpi'><div class='l'>{it['label']}</div>"
                    f"<div class='v'>{it['value']}</div>"
                    f"<div class='s'>{it.get('sub') or ''}</div></div>" for it in b["items"])
                out.append(f"<div class='kpis'>{cards}</div>")
            elif k == "note":
                out.append(f"<div class='note {b['tone']}'>{md_inline(b['text'])}</div>")
            elif k == "figure":
                out.append(b["html"])
                out.append(f"<div class='cap'><span class='capn'>Figure {b['num']}</span>"
                           f"<b>{b['title']}</b>. {b.get('what', '')}"
                           f"<div class='exp'>{b.get('how', '')}</div></div>")
            elif k == "table":
                out.append(f"<div class='cap'><b>Table {b['num']}</b>. {b['title']}</div>")
                out.append(b["html"])
            elif k == "text":
                out.append(f"<p style='font-size:13.5px'>{md_inline(b['text'])}</p>")
        out.append(f"<div class='foot'>{meta['footer']}</div></body></html>")
        return "".join(out)


REPORT = Report()
_WIDGET_SEQ = {"n": 0}


def uid(prefix="w"):
    _WIDGET_SEQ["n"] += 1
    return f"{prefix}_{_WIDGET_SEQ['n']}"


# --- primitives --------------------------------------------------------------

def section(title, sub=None, record=True):
    n = REPORT.open_section(title, sub) if record else ""
    st.markdown(
        f"<div class='section'><span class='section-num'>{n:02d}</span>"
        f"<span class='section-title'>{title}</span><span class='section-rule'></span></div>"
        + (f"<div class='section-sub'>{sub}</div>" if sub else ""),
        unsafe_allow_html=True)


def subhead(title, sub=None):
    st.markdown(f"<div class='eyebrow' style='margin-top:14px'>{title}</div>"
                + (f"<div class='section-sub'>{sub}</div>" if sub else ""),
                unsafe_allow_html=True)


def kpi_grid(items, min_width=190, record=True):
    """One responsive CSS grid rather than fixed st.columns, so cards reflow
    instead of squashing when the window or the card count changes."""
    cards = []
    for it in items:
        tone = it.get("tone", "flat")
        help_ = it.get("help", "")
        dot = f"<span class='help-dot' title=\"{help_}\">?</span>" if help_ else ""
        delta = ""
        if it.get("delta") is not None and _isnum(it["delta"]):
            cls = "pos" if it["delta"] >= 0 else "neg"
            arrow = "▲" if it["delta"] >= 0 else "▼"
            delta = f"<div class='kpi-delta {cls}'>{arrow} {abs(it['delta']):,.2f}%</div>"
        sub = f"<div class='kpi-sub'>{it['sub']}</div>" if it.get("sub") else ""
        cards.append(f"<div class='kpi {tone}'><div class='kpi-label'>{it['label']}{dot}</div>"
                     f"<div class='kpi-value'>{it['value']}</div>{delta}{sub}</div>")
    st.markdown(
        f"<div class='kpi-grid' style='grid-template-columns:repeat(auto-fit,minmax({min_width}px,1fr))'>"
        + "".join(cards) + "</div>", unsafe_allow_html=True)
    if record:
        REPORT.add("kpis", items=items)


def note(text, tone="neu", title="Interpretation", record=True):
    """Analyst commentary. `tone` is pos / neg / warn / neu."""
    tone = {"bullish": "pos", "bearish": "neg", "warning": "warn", "neutral": "neu"}.get(tone, tone)
    st.markdown(f"<div class='note {tone}'><div class='note-title'>{title}</div>{md_inline(text)}</div>",
                unsafe_allow_html=True)
    if record:
        REPORT.add("note", text=text, tone=tone)


def figure(fig, title, what, how, why=None, height=None, data=None, record=True):
    """The only sanctioned way to put a chart on screen.

    Forcing every chart through here guarantees three things the previous
    version left to chance: a stable figure number, a caption that says what the
    chart shows, and an expandable note on how to read it and why it matters."""
    if height:
        fig.update_layout(height=height)
    num = REPORT.next_figure() if record else ""
    st.plotly_chart(fig, key=uid("fig"), **FILL_CHART)
    st.markdown(
        f"<div class='figcap'><div class='figcap-line'><span class='figcap-num'>Figure {num}</span>"
        f"<span class='figcap-title'>{title}.</span> {what}</div></div>", unsafe_allow_html=True)
    with st.expander("How to read this figure", expanded=st.session_state.explain_open):
        rows = [("Shows", what), ("How to read", how)]
        if why:
            rows.append(("Why it matters", why))
        st.markdown("<div class='exp-block'>" + "".join(
            f"<div class='exp-row'><div class='exp-key'>{k}</div><div>{md_inline(v)}</div></div>"
            for k, v in rows) + "</div>", unsafe_allow_html=True)
        if data is not None and isinstance(data, pd.DataFrame) and not data.empty:
            st.download_button("Download the data behind this figure (CSV)",
                               data.to_csv().encode("utf-8"),
                               file_name=f"figure_{num.replace('.', '_')}.csv",
                               mime="text/csv", key=uid("dl"))
    if record:
        # Serialising a chart to HTML is only worth doing when an export was
        # actually requested; on an ordinary render it is pure overhead.
        chart_html = ""
        if st.session_state.get("_export"):
            try:
                chart_html = fig.to_html(include_plotlyjs=False, full_html=False,
                                         default_height=(height or 380))
            except Exception as exc:
                note_error("report figure export", exc)
        REPORT.add("figure", num=num, title=title, what=what, how=how, html=chart_html)


def table(df, title, what=None, formats=None, height=None, record=True, highlight=None):
    """A dataframe with a numbered caption, consistent number formatting and a
    CSV export, so tables are first-class report objects too."""
    num = REPORT.next_figure() if record else ""
    st.markdown(f"<div class='figcap-line' style='margin-bottom:5px'>"
                f"<span class='figcap-num'>Table {num}</span>"
                f"<span class='figcap-title'>{title}.</span> {what or ''}</div>", unsafe_allow_html=True)
    styled = df.style.format(formats, na_rep=Fmt.NA) if formats else df.style.format(na_rep=Fmt.NA)
    if highlight is not None:
        styled = styled.apply(
            lambda s: [f"background-color:{T['neu_bg']};color:{T['neu_text']};font-weight:600"
                       if s.name == highlight else "" for _ in s], axis=1)
    st.dataframe(styled, **({"height": height} if height else {}), **FILL_DF)
    if record:
        table_html = ""
        if st.session_state.get("_export"):
            try:
                table_html = styled.to_html()
            except Exception:
                table_html = df.to_html()
        REPORT.add("table", num=num, title=title, html=table_html)


def checklist(rows, record=True):
    marks = {"pass": ("+", "chk-pass"), "warn": ("!", "chk-warn"),
             "fail": ("x", "chk-fail"), "na": ("·", "chk-na")}
    html = []
    for r in rows:
        mark, cls = marks.get(r["state"], marks["na"])
        html.append(f"<div class='chk'><div class='chk-mark {cls}'>{mark}</div>"
                    f"<div><span class='chk-label'>{r['label']}</span> "
                    f"<span class='chk-detail'>— {r['value']}. {r['detail']}</span></div></div>")
    st.markdown("<div class='card'>" + "".join(html) + "</div>", unsafe_allow_html=True)
    if record:
        REPORT.add("text", text="\n".join(f"- **{r['label']}** ({r['value']}): {r['detail']}" for r in rows))


def score_bars(pillars, record=True):
    def colour(s):
        if s is None:
            return T["faint"]
        return T["success"] if s >= 65 else T["warning"] if s >= 40 else T["danger"]

    rows = []
    for p in pillars:
        s = p.score
        width = 0 if s is None else s
        rows.append(f"<div class='score-row'><div class='score-name'>{p.name}"
                    f"<span style='color:{T['faint']}'> · {int(p.weight * 100)}%</span></div>"
                    f"<div class='score-track'><div class='score-fill' style='width:{width:.0f}%;"
                    f"background:{colour(s)}'></div></div>"
                    f"<div class='score-val'>{'—' if s is None else f'{s:.0f}'}</div></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)


def range_bar(low, high, current, sym):
    if not all(_isnum(x) for x in (low, high, current)) or high <= low:
        return
    pos = float(np.clip((current - low) / (high - low), 0, 1)) * 100
    st.markdown(
        f"<div class='rng'><div class='rng-track'><div class='rng-fill' style='width:{pos:.1f}%'></div>"
        f"<div class='rng-mark' style='left:calc({pos:.1f}% - 1px)'></div></div>"
        f"<div class='rng-labels'><span>52w low {Fmt.price(low, sym)}</span>"
        f"<span>{pos:.0f}% of range</span><span>{Fmt.price(high, sym)} high</span></div></div>",
        unsafe_allow_html=True)


def empty_state(message, hint=None):
    st.markdown(f"<div class='card' style='text-align:center;padding:26px'>"
                f"<div class='card-title'>{message}</div>"
                f"<div class='card-meta'>{hint or ''}</div></div>", unsafe_allow_html=True)


def segmented(label, options, key, default_index=0, help=None):
    """Uses the compact segmented control where the installed Streamlit has it,
    falling back to a horizontal radio so the app still runs on older versions."""
    if hasattr(st, "segmented_control"):
        val = st.segmented_control(label, options, default=options[default_index],
                                   key=key, help=help)
        return val if val is not None else options[default_index]
    return st.radio(label, options, index=default_index, horizontal=True, key=key, help=help)


# ==============================================================================
# 6. NAVIGATION & SHELL
# ==============================================================================

MODULES = [
    ("0. Guide & Method", "How the terminal is put together and when to use each module."),
    ("1. Executive Dashboard", "One screen: composite score, valuation, profitability, health, quality flags."),
    ("2. Technical Analysis", "Price action, trend, momentum and volatility."),
    ("3. Financial Statements", "Reported figures, common-size views and year-on-year variance."),
    ("4. Cash Flow Quality", "Whether reported profit actually converts into cash."),
    ("5. Intrinsic Valuation", "Three-phase DCF, reverse DCF, scenarios and sensitivity."),
    ("6. Peer Comparables", "Relative valuation against live-matched industry peers."),
    ("7. Risk & Scenarios", "Volatility, drawdown, value at risk and Monte Carlo paths."),
    ("8. Price & Capital Dynamics", "Price, market cap, news context and the EV bridge."),
    ("9. Market Leaders", "Cross-company ranking by market cap and revenue."),
]
MODULE_NAMES = [m for m, _ in MODULES]
MODULE_HELP = dict(MODULES)

MARKETS = {
    "United States": "", "Germany (Xetra)": ".DE", "Vietnam (HOSE)": ".VN",
    "United Kingdom (LSE)": ".L", "Japan (Tokyo)": ".T", "China (Shanghai)": ".SS",
    "Other / enter full symbol": "MANUAL",
}
SUFFIX_TO_MARKET = {v: k for k, v in MARKETS.items() if v != "MANUAL"}

PERIODS = {"5 days": "5d", "1 month": "1mo", "3 months": "3mo", "6 months": "6mo",
           "Year to date": "ytd", "1 year": "1y", "3 years": "3y", "5 years": "5y",
           "10 years": "10y", "Maximum": "max"}
INTERVALS = {"5d": "15m", "1mo": "60m", "3mo": "1d", "6mo": "1d", "ytd": "1d",
             "1y": "1d", "3y": "1wk", "5y": "1wk", "10y": "1mo", "max": "1mo"}

st.session_state[_LOAD_ERRORS_KEY] = []


def company_logo(info):
    """Yahoo's `logo_url` is frequently empty now, so fall back to deriving a
    logo from the company's own website domain (Clearbit, no API key)."""
    logo = info.get("logo_url")
    if logo:
        return logo
    site = info.get("website") or ""
    domain = site.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "").strip()
    return f"https://logo.clearbit.com/{domain}" if domain else None


with st.sidebar:
    st.markdown(f"<div class='side-brand'>{APP_NAME}</div>"
                f"<div class='side-sub'>{APP_TAGLINE}</div>", unsafe_allow_html=True)

    st.markdown("<div class='side-group'>Company</div>", unsafe_allow_html=True)
    with st.expander("Search by company name", expanded=False):
        q = st.text_input("Company name", placeholder="Siemens, Toyota, Vietcombank…",
                          key="name_search_query", label_visibility="collapsed")
        if q.strip():
            results = search_ticker(q)
            if results:
                opts = {f"{r['symbol']} · {r['name']} ({r['exchange']})": r["symbol"] for r in results}
                picked = st.selectbox("Match", list(opts.keys()), key="name_search_pick",
                                      label_visibility="collapsed")
                if st.button("Use this ticker", type="primary", **FILL_BTN):
                    sym = opts[picked]
                    suffix = f".{sym.split('.')[-1]}" if "." in sym else ""
                    st.session_state["market_select"] = SUFFIX_TO_MARKET.get(suffix, "Other / enter full symbol")
                    st.session_state["ticker_symbol_input"] = sym
                    st.rerun()
            else:
                st.caption("No matches on Yahoo Finance. Try another spelling, or type the symbol directly.")
        st.caption("Live search against Yahoo's own index, not a bundled list, so it stays correct as symbols change.")

    market = st.selectbox("Market", list(MARKETS.keys()), key="market_select")
    suffix = MARKETS[market]
    symbol = st.text_input("Ticker symbol", key="ticker_symbol_input",
                           help="A symbol that already carries an exchange suffix (7203.T) overrides the market above.").upper().strip()
    ticker = symbol if (suffix == "MANUAL" or "." in symbol) else f"{symbol}{suffix}"

    st.markdown("<div class='side-group'>View</div>", unsafe_allow_html=True)
    module = st.selectbox("Module", MODULE_NAMES, key="module", label_visibility="collapsed")
    st.caption(MODULE_HELP[module])

    st.markdown("<div class='side-group'>Reporting basis</div>", unsafe_allow_html=True)
    period_label = st.selectbox("Chart period", list(PERIODS.keys()), index=5)
    period = PERIODS[period_label]
    interval = INTERVALS.get(period, "1d")
    basis = segmented("Statement basis", ["Annual", "Quarterly", "TTM"], key="basis_sel", default_index=0,
                      help="Annual and quarterly are as reported; TTM sums the last four reported quarters.")
    currency_mode = st.selectbox("Display currency", ["Native", "USD", "EUR", "VND", "GBP", "JPY"], index=0)

    st.markdown("<div class='side-group'>Presentation</div>", unsafe_allow_html=True)
    tcol, dcol = st.columns(2)
    with tcol:
        st.selectbox("Theme", list(THEMES.keys()), key="theme")
    with dcol:
        st.selectbox("Density", list(DENSITY.keys()), key="density")
    st.checkbox("Expand figure explanations by default", key="explain_open")

    st.markdown("<div class='side-group'>Data</div>", unsafe_allow_html=True)
    if st.button("Refresh market data", **FILL_BTN,
                 help="Clears every cached response and refetches on the next render."):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"Source: {DATA_SOURCE} · rendered {datetime.now():%d %b %Y %H:%M}")

    st.markdown(f"<div class='foot' style='margin-top:18px'>Built by Minh Phu Dinh<br>"
                f"Educational research tool — not investment advice.</div>", unsafe_allow_html=True)


# --- Guide page (no data loading, so it renders instantly) --------------------
if module == "0. Guide & Method":
    st.markdown(f"<div class='eyebrow'>{APP_NAME}</div>"
                f"<div class='hdr-name'>Guide &amp; method</div>"
                f"<div class='hdr-meta'>What each module answers, how the numbers are built, and what the "
                f"figures assume. Nothing on this page loads market data.</div>", unsafe_allow_html=True)

    section("Modules", "Pick the module that matches the question you are actually asking.")
    for name, purpose in MODULES[1:]:
        n, title = name.split(". ", 1)
        st.markdown(f"<div class='card'><div class='card-title'>"
                    f"<span class='section-num'>{n}</span> &nbsp;{title}</div>"
                    f"<div class='card-body'>{purpose}</div></div>", unsafe_allow_html=True)

    section("How the report is structured",
            "Every module follows the same shape, so figures can be quoted and compared reliably.")
    st.markdown("""
<div class='card'><div class='card-body'>
<b>Numbered sections and figures.</b> Each chart and table carries a stable reference such as
<i>Figure 5.2</i> (section 5, second exhibit), and every figure has a "how to read this" note covering
what it shows, how to read it and why it matters.<br><br>
<b>Consistent units.</b> All monetary figures are converted into your selected display currency using a
live FX rate; if a rate cannot be fetched, the app says so and leaves the figures in the native currency
rather than silently applying a 1:1 rate.<br><br>
<b>Stated basis.</b> Statements are labelled Annual, Quarterly or TTM. TTM sums the last four reported
quarters for flow items and uses the most recent quarter-end for balance sheet items.<br><br>
<b>Exportable.</b> Any view can be exported as a standalone HTML report with its charts and captions
intact, plus the underlying statements as CSV.
</div></div>""", unsafe_allow_html=True)

    section("Method notes and limitations",
            "The assumptions behind the calculated figures, stated up front.")
    st.markdown("""
<div class='card'><div class='card-body'>
<b>Discount rate.</b> WACC is built from CAPM: a live 10-year Treasury yield as the risk-free rate, an
equity risk premium you control, the company's reported beta, and an after-tax cost of debt weighted by
market values of equity and debt.<br><br>
<b>DCF shape.</b> Three phases — an explicit high-growth stage, a fade stage that converges toward the
terminal rate, then Gordon growth in perpetuity. The share of value coming from the terminal figure is
always shown, because a model where 90% of value sits beyond the forecast horizon deserves less weight.<br><br>
<b>Scores.</b> The composite score is a weighted average of five pillars, each an average of the
sub-metrics that could be computed. Missing inputs are skipped and weights renormalise. It is a
screening aid, not a recommendation.<br><br>
<b>Data.</b> Everything comes from a single free source and can contain gaps, restatements and
classification quirks, particularly outside the United States. Figures should be verified against filings
before anything consequential rests on them.
</div></div>""", unsafe_allow_html=True)
    st.markdown(f"<div class='foot'>{APP_NAME} · Data: {DATA_SOURCE} · "
                f"Educational use only, not investment advice.</div>", unsafe_allow_html=True)
    st.stop()


# --- Load the company --------------------------------------------------------
if not ticker:
    empty_state("Enter a ticker symbol to begin", "Use the sidebar search if you only know the company name.")
    st.stop()

with st.spinner(f"Loading {ticker}…"):
    co = Company(ticker)

if not co.ok:
    empty_state(f"No usable data for “{ticker}”",
                "The symbol may be delisted, mistyped, or missing its exchange suffix "
                "(for example BMW.DE rather than BMW). The sidebar search resolves names to symbols.")
    st.stop()

info = co.info

# --- Currency ----------------------------------------------------------------
native_currency = co.currency
target_currency = native_currency if currency_mode == "Native" else currency_mode
fx = load_fx(native_currency, target_currency)
fx_note = None
if fx is None:
    # A genuine lookup failure: do not silently misstate every figure with a
    # wrong 1:1 rate - fall back to the native currency and say so.
    fx, target_currency = 1.0, native_currency
    fx_note = (f"A live {native_currency} → {currency_mode} rate was not available, so every figure below "
               f"is shown in the native currency ({native_currency}).")
sym = CURRENCY_SYMBOLS.get(target_currency, target_currency + " ")

extras = compute_extras(co)

# --- Header ------------------------------------------------------------------
h_left, h_right = st.columns([3, 1.15], vertical_alignment="center")
with h_left:
    logo = company_logo(info)
    lg, txt = st.columns([1, 9], vertical_alignment="center")
    with lg:
        if logo:
            st.image(logo, width=46)
        else:
            initials = "".join(w[0] for w in co.name.split()[:2]).upper()
            st.markdown(f"<div style='width:44px;height:44px;border-radius:9px;background:{T['neu_bg']};"
                        f"color:{T['accent']};display:flex;align-items:center;justify-content:center;"
                        f"font-weight:800;font-size:16px'>{initials}</div>", unsafe_allow_html=True)
    with txt:
        st.markdown(
            f"<div class='eyebrow'>{co.ticker} · {market_label(co.ticker)}</div>"
            f"<div class='hdr-name'>{co.name}</div>"
            f"<div class='hdr-meta'>"
            f"<span class='hdr-chip'>{co.sector}</span>"
            f"<span class='hdr-chip'>{co.industry}</span>"
            f"<span class='hdr-chip'>{info.get('exchange', Fmt.NA)}</span>"
            f"Reported in {native_currency} · shown in {target_currency}"
            f"{'' if native_currency == target_currency else f' at {fx:,.4f}'}</div>",
            unsafe_allow_html=True)

with h_right:
    price_disp = (co.price or 0) * fx
    prev = co.previous_close or co.price or 0
    chg = (co.price or 0) - prev
    chg_pct = (chg / prev * 100) if prev else 0
    colour = T["success"] if chg >= 0 else T["danger"]
    st.markdown(
        f"<div class='px-box'><div class='px-value' style='color:{colour}'>{Fmt.price(price_disp, sym)}</div>"
        f"<div class='px-chg' style='color:{colour}'>{chg * fx:+,.2f} ({chg_pct:+,.2f}%)</div>"
        f"<div class='px-meta'>Previous close {Fmt.price(prev * fx, sym)}</div></div>",
        unsafe_allow_html=True)

hi52, lo52 = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
if _isnum(hi52) and _isnum(lo52) and co.price:
    range_bar(lo52 * fx, hi52 * fx, co.price * fx, sym)

if fx_note:
    st.warning(fx_note)


# --- Shared helpers for the modules ------------------------------------------

# Share counts and rates live in the statements alongside monetary items;
# multiplying them by an FX rate (as the previous version did wholesale) turns a
# share count into nonsense. These columns are left untouched on conversion.
NON_CURRENCY_ITEMS = {
    "Basic Average Shares", "Diluted Average Shares", "Share Issued",
    "Ordinary Shares Number", "Treasury Shares Number", "Tax Rate For Calcs",
}


def to_display(df: pd.DataFrame, rate: float) -> pd.DataFrame:
    if df is None or df.empty or rate == 1.0:
        return df
    out = df.copy()
    cols = [c for c in out.columns if c not in NON_CURRENCY_ITEMS]
    out[cols] = out[cols] * rate
    return out


def year_labels(idx, basis="Annual"):
    """Categorical x-axis labels; keeps Plotly from inventing '2021.5' ticks."""
    try:
        if basis == "Quarterly":
            return [pd.Timestamp(d).strftime("%b %Y") for d in idx]
        return [pd.Timestamp(d).strftime("FY%Y") for d in idx]
    except Exception:
        return [str(d)[:10] for d in idx]


def col(df, name):
    return df[name] if (isinstance(df, pd.DataFrame) and name in df.columns) else None


def last(df, name):
    s = col(df, name)
    if s is None:
        return None
    s = s.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def tone_for(value, good, bad, higher_better=True):
    if not _isnum(value):
        return "flat"
    if higher_better:
        return "good" if value >= good else "bad" if value <= bad else "warn"
    return "good" if value <= good else "bad" if value >= bad else "warn"


# ==============================================================================
# 8. MODULES
# ==============================================================================

if module == "1. Executive Dashboard":
    scorecard = build_scorecard(co, extras)
    section("Executive summary",
            "A single screen answering: what is the market paying, what is the business earning, "
            "how solid is the balance sheet, and where are the warning signs.")

    v_left, v_right = st.columns([1.05, 2], vertical_alignment="top")
    with v_left:
        total = scorecard["total"]
        band_colour = (T["success"] if (total or 0) >= 65 else T["warning"] if (total or 0) >= 40 else T["danger"])
        st.markdown(
            f"<div class='card'><div class='eyebrow'>Composite screen</div>"
            f"<div class='verdict' style='margin-top:8px'>"
            f"<div><div class='verdict-score' style='color:{band_colour}'>"
            f"{'—' if total is None else f'{total:.0f}'}"
            f"<span style='font-size:15px;color:{T['faint']}'>/100</span></div>"
            f"<div class='verdict-band' style='color:{band_colour}'>{scorecard['band']}</div></div>"
            f"<div class='verdict-text'>{scorecard['blurb']}<br>"
            f"<span style='color:{T['faint']}'>Built from {scorecard['coverage']} of "
            f"{scorecard['total_drivers']} possible inputs.</span></div></div></div>",
            unsafe_allow_html=True)
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        score_bars(scorecard["pillars"])

    with v_right:
        pe = info.get("trailingPE")
        fcf_yield = safe_div(co.base_fcf, co.market_cap)
        rev_cagr = extras.get("rev_cagr")
        de = de_as_ratio(info.get("debtToEquity"))
        strongest = max((p for p in scorecard["pillars"] if p.score is not None),
                        key=lambda p: p.score, default=None)
        weakest = min((p for p in scorecard["pillars"] if p.score is not None),
                      key=lambda p: p.score, default=None)
        note(f"""
**{co.name}** is a {co.industry.lower() if co.industry != Fmt.NA else 'diversified'} business in the
{co.sector} sector, capitalised at **{Fmt.money(co.market_cap * fx, sym)}** and trading at
**{Fmt.price((co.price or 0) * fx, sym)}**.
- **What the market pays.** {'A trailing P/E of ' + Fmt.ratio(pe) if _isnum(pe) and pe > 0 else 'Earnings are negative or unreported, so P/E is not meaningful'}
{' and a free cash flow yield of ' + Fmt.as_pct(fcf_yield) if fcf_yield is not None else ''}.
{'The shares sit ' + Fmt.as_pct(extras.get('vs_sma200'), signed=True) + ' versus their 200-day average' if extras.get('vs_sma200') is not None else ''}
{' and ' + f"{extras['range_pos']*100:.0f}% of the way up the 52-week range" if extras.get('range_pos') is not None else ''}.
- **What the business earns.** Return on equity of {Fmt.as_pct(info.get('returnOnEquity'))} on operating
margins of {Fmt.as_pct(info.get('operatingMargins'))}{', with revenue compounding at ' + Fmt.as_pct(rev_cagr) + ' over the reported history' if rev_cagr is not None else ''}.
- **How it is financed.** {'Debt to equity of ' + Fmt.ratio(de) if de is not None else 'Leverage is unreported'}
with a current ratio of {Fmt.ratio(info.get('currentRatio'))} and a net {'debt' if co.net_debt >= 0 else 'cash'}
position of {Fmt.money(abs(co.net_debt) * fx, sym)}.
- **Where to look next.** {'Strongest pillar: **' + strongest.name + f'** ({strongest.score:.0f}/100). ' if strongest else ''}
{'Weakest: **' + weakest.name + f'** ({weakest.score:.0f}/100) — start there.' if weakest else ''}
""", tone="pos" if (total or 0) >= 65 else "warn" if (total or 0) >= 40 else "neg",
             title="What the numbers say")

    # --- Headline KPI strip ---------------------------------------------------
    ev = info.get("enterpriseValue")
    fcf_yield = safe_div(co.base_fcf, co.market_cap)
    div_y = yield_as_fraction(info.get("dividendYield"))
    nd_ebitda = safe_div(co.net_debt, info.get("ebitda"))
    kpi_grid([
        {"label": "Market cap", "value": Fmt.money(co.market_cap * fx if co.market_cap else None, sym),
         "sub": f"Enterprise value {Fmt.money(ev * fx if _isnum(ev) else None, sym)}", "tone": "flat",
         "help": "Share price times shares outstanding: the value of the equity alone."},
        {"label": "Trailing P/E", "value": Fmt.ratio(info.get("trailingPE")),
         "sub": f"Forward {Fmt.ratio(info.get('forwardPE'))}",
         "tone": tone_for(info.get("trailingPE"), 18, 35, higher_better=False),
         "help": "Price paid per unit of last year's earnings."},
        {"label": "EV / EBITDA", "value": Fmt.ratio(info.get("enterpriseToEbitda")),
         "sub": "Capital-structure neutral", "tone": tone_for(info.get("enterpriseToEbitda"), 10, 20, higher_better=False),
         "help": "Enterprise value against cash operating earnings; comparable across different debt levels."},
        {"label": "FCF yield", "value": Fmt.as_pct(fcf_yield),
         "sub": f"FCF {Fmt.money(co.base_fcf * fx if co.base_fcf else None, sym)}",
         "tone": tone_for((fcf_yield or 0) * 100 if fcf_yield is not None else None, 5, 2),
         "help": "Free cash flow divided by market cap: the cash return at today's price."},
        {"label": "Return on equity", "value": Fmt.as_pct(info.get("returnOnEquity")),
         "sub": f"ROA {Fmt.as_pct(info.get('returnOnAssets'))}",
         "tone": tone_for((info.get("returnOnEquity") or 0) * 100 if _isnum(info.get("returnOnEquity")) else None, 15, 5),
         "help": "Profit generated per unit of shareholder capital."},
        {"label": "Operating margin", "value": Fmt.as_pct(info.get("operatingMargins")),
         "sub": f"Gross {Fmt.as_pct(info.get('grossMargins'))}",
         "tone": tone_for((info.get("operatingMargins") or 0) * 100 if _isnum(info.get("operatingMargins")) else None, 15, 3),
         "help": "Profit from core operations as a share of revenue."},
        {"label": "Net debt / EBITDA", "value": Fmt.ratio(nd_ebitda),
         "sub": f"Current ratio {Fmt.ratio(info.get('currentRatio'))}",
         "tone": tone_for(nd_ebitda, 2, 4, higher_better=False),
         "help": "Years of cash earnings needed to repay net debt."},
        {"label": "Dividend yield", "value": Fmt.as_pct(div_y),
         "sub": f"Payout {Fmt.as_pct(info.get('payoutRatio'))}", "tone": "flat",
         "help": "Annual dividend as a share of the current price."},
    ])

    tabs = st.tabs(["Growth & margins", "Valuation", "Returns", "Balance sheet",
                    "Quality flags", "Profile"])

    inc_d = to_display(co.inc, fx)
    bs_d = to_display(co.bs, fx)
    cf_d = to_display(co.cf, fx)

    # -- Growth & margins ------------------------------------------------------
    with tabs[0]:
        if inc_d.empty or "Total Revenue" not in inc_d.columns:
            empty_state("No income statement history available for this symbol.")
        else:
            x = year_labels(inc_d.index)
            g1, g2 = st.columns([1.25, 1])
            with g1:
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(go.Bar(x=x, y=inc_d["Total Revenue"], name="Revenue",
                                     marker_color=T["accent_soft"], opacity=.85), secondary_y=False)
                if "Net Income" in inc_d.columns:
                    fig.add_trace(go.Scatter(x=x, y=inc_d["Net Income"], name="Net income",
                                             mode="lines+markers", line=dict(color=T["success"], width=3)),
                                  secondary_y=True)
                fig.update_xaxes(type="category")
                fig.update_yaxes(title_text=f"Revenue ({sym})", secondary_y=False)
                fig.update_yaxes(title_text=f"Net income ({sym})", secondary_y=True)
                style_fig(fig, height=330)
                rc = extras.get("rev_cagr")
                figure(fig, "Revenue against net income",
                       f"Reported revenue (bars, left axis) and net income (line, right axis) by fiscal year, in {target_currency}.",
                       "Compare the *slopes*, not the levels: the two axes are scaled independently. Net income "
                       "pulling away from revenue means operating leverage — fixed costs spread over a bigger base. "
                       "Net income flattening while revenue climbs means margin compression.",
                       f"Revenue has compounded at {Fmt.as_pct(rc)} a year over the reported history. Growth that "
                       "does not reach the bottom line eventually shows up in the multiple the market is willing to pay.",
                       data=inc_d[[c for c in ("Total Revenue", "Net Income") if c in inc_d.columns]])
            with g2:
                margins = pd.DataFrame(index=inc_d.index)
                for label, num in (("Gross", "Gross Profit"), ("Operating", "Operating Income"),
                                   ("Net", "Net Income")):
                    if num in inc_d.columns:
                        margins[label] = inc_d[num] / inc_d["Total Revenue"] * 100
                if margins.empty:
                    empty_state("Margin detail is not reported for this symbol.")
                else:
                    figm = go.Figure()
                    for i_, c in enumerate(margins.columns):
                        figm.add_trace(go.Scatter(x=x, y=margins[c], name=f"{c} margin",
                                                  mode="lines+markers", line=dict(width=2.5)))
                    figm.update_xaxes(type="category")
                    figm.update_yaxes(title_text="% of revenue", ticksuffix="%")
                    style_fig(figm, height=330)
                    figure(figm, "Margin structure over time",
                           "Gross, operating and net margin, each as a percentage of revenue.",
                           "The **gap between the lines** is where money goes: gross to operating is overheads "
                           "and R&D, operating to net is interest and tax. Widening gaps mean costs growing "
                           "faster than sales.",
                           "Margin direction is usually a better early signal than any single year's level, "
                           "because it reflects pricing power and cost discipline before they reach earnings.",
                           data=margins)

    # -- Valuation -------------------------------------------------------------
    with tabs[1]:
        mult = {"Trailing P/E": info.get("trailingPE"), "Forward P/E": info.get("forwardPE"),
                "P/B": info.get("priceToBook"), "P/S": info.get("priceToSalesTrailing12Months"),
                "EV/EBITDA": info.get("enterpriseToEbitda"), "EV/Revenue": info.get("enterpriseToRevenue"),
                "PEG": pick(info, "pegRatio", "trailingPegRatio")}
        mult = {k: v for k, v in mult.items() if _isnum(v) and 0 < v < 500}
        vc1, vc2 = st.columns([1.2, 1])
        with vc1:
            if mult:
                figv = go.Figure(go.Bar(x=list(mult.values()), y=list(mult.keys()), orientation="h",
                                        marker_color=T["accent_soft"],
                                        text=[f"{v:,.1f}x" for v in mult.values()], textposition="outside"))
                figv.update_xaxes(title_text="Multiple (x)")
                style_fig(figv, height=300, legend="off")
                figure(figv, "Valuation multiples at a glance",
                       "Every headline multiple the data source reports for this company, on one scale.",
                       "Read across, not down: a high P/E next to a low EV/EBITDA usually means leverage or "
                       "non-operating items are distorting the equity multiple. PEG below 1.0x means the market "
                       "is paying less than one unit of P/E per unit of growth.",
                       "Absolute multiples say little on their own — section 6 puts these against live peers.",
                       data=pd.DataFrame({"Multiple": mult}))
            else:
                empty_state("No valuation multiples reported.", "Common for loss-making or thinly covered names.")
        with vc2:
            target = info.get("targetMeanPrice")
            rec = (info.get("recommendationKey") or "none").replace("_", " ").title()
            upside = (safe_div(target, co.price) or 1) - 1 if _isnum(target) else None
            kpi_grid([
                {"label": "Analyst consensus", "value": rec,
                 "sub": f"{info.get('numberOfAnalystOpinions', Fmt.NA)} contributing analysts", "tone": "flat"},
                {"label": "Mean target price", "value": Fmt.price(target * fx if _isnum(target) else None, sym),
                 "sub": f"{Fmt.as_pct(upside, signed=True)} versus the current price" if upside is not None else "",
                 "tone": tone_for((upside or 0) * 100 if upside is not None else None, 10, -5)},
                {"label": "Graham number", "value": Fmt.price(
                    (Valuation.graham_number(info.get("trailingEps"), info.get("bookValue")) or 0) * fx
                    if Valuation.graham_number(info.get("trailingEps"), info.get("bookValue")) else None, sym),
                 "sub": "Defensive-investor ceiling: √(22.5 × EPS × book value)", "tone": "flat"},
            ], min_width=210, record=False)
            note("Consensus targets are an input, not an answer: they cluster around the current price and "
                 "move after it, not before. Section 5 builds an independent value from cash flows.",
                 tone="neu", title="Reading this panel", record=False)

    # -- Returns (DuPont) ------------------------------------------------------
    with tabs[2]:
        rev = last(inc_d, "Total Revenue")
        ni = last(inc_d, "Net Income")
        ta = last(bs_d, "Total Assets")
        eq = last(bs_d, "Stockholders Equity")
        net_margin, asset_turn, leverage = safe_div(ni, rev), safe_div(rev, ta), safe_div(ta, eq)
        roe_calc = (net_margin or 0) * (asset_turn or 0) * (leverage or 0) if all(
            v is not None for v in (net_margin, asset_turn, leverage)) else None
        d1, d2 = st.columns([1, 1.2])
        with d1:
            kpi_grid([
                {"label": "Net margin", "value": Fmt.as_pct(net_margin), "sub": "Profit per unit of sales",
                 "tone": tone_for((net_margin or 0) * 100 if net_margin is not None else None, 10, 2)},
                {"label": "Asset turnover", "value": Fmt.ratio(asset_turn), "sub": "Sales per unit of assets",
                 "tone": tone_for(asset_turn, 1.0, 0.3)},
                {"label": "Equity multiplier", "value": Fmt.ratio(leverage), "sub": "Assets per unit of equity",
                 "tone": tone_for(leverage, 2.0, 4.0, higher_better=False)},
                {"label": "Return on equity", "value": Fmt.as_pct(roe_calc), "sub": "Product of the three above",
                 "tone": tone_for((roe_calc or 0) * 100 if roe_calc is not None else None, 15, 5)},
            ], min_width=165, record=False)
        with d2:
            if roe_calc is not None:
                figd = go.Figure(go.Waterfall(
                    orientation="v", measure=["absolute", "relative", "relative", "total"],
                    x=["Net margin", "× Asset turnover", "× Leverage", "= ROE"],
                    y=[(net_margin or 0) * 100,
                       ((net_margin or 0) * (asset_turn or 0) - (net_margin or 0)) * 100,
                       ((net_margin or 0) * (asset_turn or 0) * (leverage or 0) - (net_margin or 0) * (asset_turn or 0)) * 100,
                       0],
                    connector={"line": {"color": T["border"]}},
                    increasing={"marker": {"color": T["success"]}},
                    decreasing={"marker": {"color": T["danger"]}},
                    totals={"marker": {"color": T["accent"]}}))
                figd.update_yaxes(ticksuffix="%")
                style_fig(figd, height=310, legend="off")
                figure(figd, "DuPont decomposition of return on equity",
                       "How each of the three DuPont components contributes to the final return on equity.",
                       "Start from net margin, then see how much of the final ROE comes from turning assets "
                       "over quickly versus from financing assets with debt. A tall third bar means leverage is "
                       "doing the work.",
                       "Two companies can report identical ROE for completely different reasons. Margin-driven "
                       "and turnover-driven returns tend to persist; leverage-driven returns reverse when "
                       "credit tightens.")
            else:
                empty_state("Not enough balance-sheet detail to decompose ROE.")

    # -- Balance sheet ---------------------------------------------------------
    with tabs[3]:
        if bs_d.empty:
            empty_state("No balance sheet history available.")
        else:
            x = year_labels(bs_d.index)
            b1, b2 = st.columns([1.2, 1])
            with b1:
                figb = go.Figure()
                for label, key, colour in (("Equity", "Stockholders Equity", T["success"]),
                                           ("Total debt", "Total Debt", T["danger"]),
                                           ("Other liabilities", None, T["faint"])):
                    if key and key in bs_d.columns:
                        figb.add_trace(go.Bar(x=x, y=bs_d[key], name=label, marker_color=colour))
                    elif key is None and {"Total Liabilities Net Minority Interest"}.issubset(bs_d.columns):
                        other = bs_d["Total Liabilities Net Minority Interest"] - bs_d.get("Total Debt", 0)
                        figb.add_trace(go.Bar(x=x, y=other, name=label, marker_color=colour, opacity=.6))
                figb.update_layout(barmode="stack")
                figb.update_xaxes(type="category")
                figb.update_yaxes(title_text=f"{sym}")
                style_fig(figb, height=320)
                figure(figb, "Capital structure over time",
                       "How the asset base has been funded each year: shareholders' equity, interest-bearing "
                       "debt, and other liabilities.",
                       "Watch the **mix**, not just the height. Debt growing faster than equity means leverage "
                       "is rising; equity growing while debt is flat usually means retained profits are funding "
                       "the business.",
                       "Capital structure determines who bears the risk. The more of the bar that is debt, the "
                       "more sensitive equity value is to a downturn in earnings.",
                       data=bs_d[[c for c in ("Stockholders Equity", "Total Debt",
                                              "Total Liabilities Net Minority Interest") if c in bs_d.columns]])
            with b2:
                latest = bs_d.iloc[-1]
                ca, cl = latest.get("Current Assets"), latest.get("Current Liabilities")
                kpi_grid([
                    {"label": "Working capital", "value": Fmt.money((ca or 0) - (cl or 0), sym),
                     "sub": "Current assets less current liabilities",
                     "tone": "good" if (ca or 0) - (cl or 0) > 0 else "bad"},
                    {"label": "Cash & equivalents", "value": Fmt.money(latest.get("Cash And Cash Equivalents"), sym),
                     "sub": "Immediately deployable", "tone": "flat"},
                    {"label": "Goodwill", "value": Fmt.money(latest.get("Goodwill"), sym),
                     "sub": "Acquisition premium carried on the balance sheet", "tone": "flat"},
                    {"label": "Retained earnings", "value": Fmt.money(latest.get("Retained Earnings"), sym),
                     "sub": "Cumulative profit kept in the business",
                     "tone": "good" if (latest.get("Retained Earnings") or 0) > 0 else "warn"},
                ], min_width=175, record=False)

    # -- Quality flags ---------------------------------------------------------
    with tabs[4]:
        q1, q2 = st.columns([1.15, 1])
        with q1:
            subhead("Earnings-quality checklist",
                    "Eight tests on whether reported profit is backed by cash and a sound balance sheet.")
            checklist(quality_flags(co, extras))
        with q2:
            f_tests = extras.get("f_tests") or []
            z = extras.get("z_score")
            subhead("Distress and strength scores", "Two long-standing academic screens, shown with their inputs.")
            kpi_grid([
                {"label": "Altman Z-score", "value": Fmt.ratio(z, suffix=""),
                 "sub": "Above 3.0 safe · 1.8–3.0 grey zone · below 1.8 distress",
                 "tone": tone_for(z, 3.0, 1.8),
                 "help": "A five-factor bankruptcy screen built for public manufacturers; less meaningful for banks and asset-light software."},
                {"label": "Piotroski F-score", "value": f"{extras.get('f_score', '—')}/9",
                 "sub": "Nine pass/fail tests on profitability, leverage and efficiency",
                 "tone": tone_for(extras.get("f_score"), 7, 3)},
            ], min_width=210, record=False)
            if f_tests:
                checklist([{"label": t["label"], "state": "pass" if t["pass"] else "fail",
                            "value": t["detail"], "detail": ""} for t in f_tests], record=False)

    # -- Profile ---------------------------------------------------------------
    with tabs[5]:
        emp = info.get("fullTimeEmployees")
        ipo = info.get("firstTradeDateEpochUtc")
        try:
            ipo_s = datetime.fromtimestamp(ipo).strftime("%d %b %Y") if ipo else Fmt.NA
        except (TypeError, ValueError, OSError):
            ipo_s = Fmt.NA
        facts = [("Sector", co.sector), ("Industry", co.industry),
                 ("Employees", f"{emp:,}" if _isnum(emp) else Fmt.NA),
                 ("First traded", ipo_s), ("Country", info.get("country") or Fmt.NA),
                 ("Website", info.get("website") or Fmt.NA)]
        fact_html = "".join(
            f"<div><div class='eyebrow'>{k}</div><div style='font-size:13px;margin-top:2px'>{v}</div></div>"
            for k, v in facts)
        st.markdown(
            f"<div class='card'><div class='card-title'>{co.name}</div>"
            f"<div class='card-body'>{info.get('longBusinessSummary', 'No description available.')}</div>"
            f"<hr style='border:none;border-top:1px solid {T['border']};margin:14px 0'>"
            f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px'>"
            f"{fact_html}</div></div>", unsafe_allow_html=True)


# ==============================================================================
elif module == "2. Technical Analysis":
    hist = Indicators.enrich(co.history(period, interval))
    if hist.empty:
        empty_state("No price history returned for this symbol and period.",
                    "Try a longer period — intraday intervals are only available for recent windows.")
        st.stop()

    price_cols = ["Open", "High", "Low", "Close", "SMA_20", "SMA_50", "SMA_200",
                  "BB_Upper", "BB_Lower", "ATR"]
    for c in price_cols:
        if c in hist.columns:
            hist[c] = hist[c] * fx

    section("Price, trend and momentum",
            f"{period_label} of price action for {co.ticker}, with the overlays and oscillators you select below.")

    c_over, c_osc = st.columns([1.4, 1])
    with c_over:
        overlays = st.multiselect("Price overlays", ["SMA 20", "SMA 50", "SMA 200", "Bollinger bands"],
                                  default=["SMA 50", "SMA 200"])
    with c_osc:
        oscillators = st.multiselect("Lower panels", ["Volume", "RSI", "MACD"], default=["Volume", "RSI"])

    last_px = float(hist["Close"].dropna().iloc[-1])
    rsi = last(hist, "RSI")
    atr = last(hist, "ATR")
    sma50, sma200 = last(hist, "SMA_50"), last(hist, "SMA_200")
    vol_ratio = safe_div(last(hist, "Volume"), last(hist, "Vol_SMA_20"))

    kpi_grid([
        {"label": "Last close", "value": Fmt.price(last_px, sym),
         "sub": f"{period_label} change {Fmt.as_pct(last_px / float(hist['Close'].dropna().iloc[0]) - 1, signed=True)}",
         "tone": "flat"},
        {"label": "Versus 50-day", "value": Fmt.as_pct(safe_div(last_px, sma50) - 1 if sma50 else None, signed=True),
         "sub": f"50-day at {Fmt.price(sma50, sym)}",
         "tone": "good" if sma50 and last_px > sma50 else "bad"},
        {"label": "Versus 200-day", "value": Fmt.as_pct(safe_div(last_px, sma200) - 1 if sma200 else None, signed=True),
         "sub": f"200-day at {Fmt.price(sma200, sym)}",
         "tone": "good" if sma200 and last_px > sma200 else "bad"},
        {"label": "RSI (14)", "value": Fmt.ratio(rsi, 1, suffix=""),
         "sub": "Above 70 stretched · below 30 washed out",
         "tone": "warn" if _isnum(rsi) and (rsi > 70 or rsi < 30) else "good"},
        {"label": "ATR (14)", "value": Fmt.price(atr, sym),
         "sub": f"{Fmt.as_pct(safe_div(atr, last_px))} of price per day", "tone": "flat",
         "help": "Average true range: the typical daily trading range, a plain measure of volatility."},
        {"label": "Volume vs 20-day", "value": Fmt.ratio(vol_ratio),
         "sub": "Above 1.0x means heavier than usual participation",
         "tone": "flat"},
    ], min_width=175)

    rows = 1 + len(oscillators)
    heights = [0.55] + [0.45 / len(oscillators)] * len(oscillators) if oscillators else [1.0]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.035, row_heights=heights)
    fig.add_trace(go.Candlestick(x=hist.index, open=hist["Open"], high=hist["High"], low=hist["Low"],
                                 close=hist["Close"], name="Price",
                                 increasing_line_color=T["success"], decreasing_line_color=T["danger"]),
                  row=1, col=1)
    overlay_map = {"SMA 20": ("SMA_20", T["warning"]), "SMA 50": ("SMA_50", T["accent_soft"]),
                   "SMA 200": ("SMA_200", T["info"])}
    for label in overlays:
        if label in overlay_map and overlay_map[label][0] in hist.columns:
            key, colour = overlay_map[label]
            fig.add_trace(go.Scatter(x=hist.index, y=hist[key], name=label,
                                     line=dict(color=colour, width=1.6)), row=1, col=1)
    if "Bollinger bands" in overlays and "BB_Upper" in hist.columns:
        fig.add_trace(go.Scatter(x=hist.index, y=hist["BB_Upper"], name="Bollinger upper",
                                 line=dict(color=T["faint"], width=1, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist.index, y=hist["BB_Lower"], name="Bollinger lower",
                                 line=dict(color=T["faint"], width=1, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(128,128,128,0.10)"), row=1, col=1)

    r = 2
    for osc in oscillators:
        if osc == "Volume" and "Volume" in hist.columns:
            fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"], name="Volume",
                                 marker_color=T["faint"], opacity=.55), row=r, col=1)
            fig.update_yaxes(title_text="Volume", row=r, col=1)
        elif osc == "RSI" and "RSI" in hist.columns:
            fig.add_trace(go.Scatter(x=hist.index, y=hist["RSI"], name="RSI",
                                     line=dict(color=T["accent"], width=1.6)), row=r, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color=T["danger"], row=r, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color=T["success"], row=r, col=1)
            fig.update_yaxes(title_text="RSI", range=[0, 100], row=r, col=1)
        elif osc == "MACD" and "MACD" in hist.columns:
            fig.add_trace(go.Bar(x=hist.index, y=hist["MACD_Hist"], name="MACD histogram",
                                 marker_color=T["faint"], opacity=.6), row=r, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist["MACD"], name="MACD",
                                     line=dict(color=T["accent"], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist["MACD_Signal"], name="Signal",
                                     line=dict(color=T["warning"], width=1.2, dash="dot")), row=r, col=1)
            fig.update_yaxes(title_text="MACD", row=r, col=1)
        r += 1
    fig.update_layout(xaxis_rangeslider_visible=False, hovermode="x unified")
    style_fig(fig, height=240 + 190 * rows)
    figure(fig, "Price with selected overlays and oscillators",
           f"Candlesticks show each period's open, high, low and close in {target_currency}; the lower panels "
           "show the indicators you selected.",
           "Read the panels top down. **Trend** is price relative to the moving averages, and the averages "
           "relative to each other. **Momentum** is RSI: above 70 the move is stretched, below 30 it is washed "
           "out — neither is a signal on its own. **Volatility** is the Bollinger band width; bands squeezing "
           "together often precedes a larger move in either direction.",
           "Technicals describe positioning and timing, not worth. They are most useful once you already have "
           "a view on value from the other sections.",
           data=hist[[c for c in ("Close", "SMA_50", "SMA_200", "RSI") if c in hist.columns]])

    trend = "above" if sma50 and last_px > sma50 else "below"
    rsi_state = ("stretched" if _isnum(rsi) and rsi > 70 else
                 "washed out" if _isnum(rsi) and rsi < 30 else "neutral")
    note(f"""
Price is trading **{trend}** its 50-day average and
**{'above' if sma200 and last_px > sma200 else 'below'}** its 200-day average, with RSI at
{Fmt.ratio(rsi, 1, suffix='')} — momentum reads **{rsi_state}**.
- **Trend.** The 50-day against the 200-day is the cleanest single read: price above both usually means
buyers are in control on both horizons; between them means the two horizons disagree.
- **Momentum.** A stretched RSI does not mean sell. Strong trends stay overbought for months. It means the
odds of a pause or pullback have risen, which matters mostly for entry timing.
- **Volatility.** ATR of {Fmt.price(atr, sym)} is roughly {Fmt.as_pct(safe_div(atr, last_px))} of the price
per day. That is the range to expect on an ordinary day, and a sensible unit for sizing a stop.
- Volume at {Fmt.ratio(vol_ratio)} of its 20-day average tells you how much conviction is behind the
current move: breakouts on light volume are the ones that most often fail.
""", tone="pos" if trend == "above" and rsi_state != "stretched" else "warn")


# ==============================================================================
elif module == "3. Financial Statements":
    inc_r, bs_r, cf_r = co.basis_statements(basis)
    inc_d, bs_d, cf_d = to_display(inc_r, fx), to_display(bs_r, fx), to_display(cf_r, fx)

    if inc_d.empty and bs_d.empty and cf_d.empty:
        empty_state(f"No {basis.lower()} statements available for this symbol.",
                    "Quarterly detail is often missing outside the United States; try the Annual basis.")
        st.stop()

    section(f"Reported financials — {basis} basis",
            f"As-reported line items in {target_currency}"
            + (" (last four quarters summed for flow items)." if basis == "TTM" else ".")
            + " Use the view switch to move between absolute figures, common-size percentages and growth rates.")

    view = segmented("View", ["Reported", "Common size", "Growth"], key="stmt_view",
                     help="Common size expresses each line as a share of revenue (or total assets on the "
                          "balance sheet). Growth shows the period-on-period change.")

    def statement_table(df, items, title, what, base=None, base_label="revenue"):
        """Renders one grouped block of a statement in the currently selected
        view. Periods run newest-first; empty periods are dropped, because the
        oldest reported year is often blank after a restatement or spin-off."""
        cols = [i for i in items if i in df.columns]
        if not cols or df.empty:
            return
        sub = df[cols].T
        sub = sub[sorted(sub.columns, reverse=True)].dropna(axis=1, how="all")
        if sub.empty:
            return
        fmt = "{:,.0f}"
        if view == "Common size" and base is not None:
            denom = base.reindex(sub.columns).replace(0, np.nan)
            sub = sub.div(denom, axis=1) * 100
            fmt = "{:,.1f}%"
        elif view == "Growth":
            ordered = sub[sorted(sub.columns)]
            sub = (ordered.pct_change(axis=1) * 100)[sorted(sub.columns, reverse=True)]
            fmt = "{:+,.1f}%"
        elif len(sub.columns) >= 2:
            latest, prev = sub.iloc[:, 0], sub.iloc[:, 1]
            sub["Change"] = latest - prev
            sub["Change %"] = (latest - prev) / prev.abs().replace(0, np.nan) * 100
        labels = year_labels(list(sub.columns), basis) if view != "Reported" else \
            year_labels([c for c in sub.columns if isinstance(c, pd.Timestamp)], basis) + \
            [c for c in sub.columns if not isinstance(c, pd.Timestamp)]
        sub.columns = labels
        formats = {c: ("{:+,.1f}%" if "%" in str(c) else "{:+,.0f}" if c == "Change" else fmt)
                   for c in sub.columns}
        table(sub, title, what, formats=formats)

    t_inc, t_bs, t_cf = st.tabs(["Income statement", "Balance sheet", "Cash flow"])

    with t_inc:
        if inc_d.empty:
            empty_state("No income statement on this basis.")
        else:
            rev_base = col(inc_d, "Total Revenue")
            left, right = st.columns([1.5, 1])
            with left:
                statement_table(inc_d, ["Total Revenue", "Cost Of Revenue", "Gross Profit"],
                                "Revenue and gross profit",
                                "What the company sold and what it kept after the direct cost of selling it.",
                                base=rev_base)
                statement_table(inc_d, ["Operating Expense", "Research And Development",
                                        "Selling General And Administration", "Operating Income"],
                                "Operating costs and operating profit",
                                "The overhead layer between gross profit and profit from operations.",
                                base=rev_base)
                statement_table(inc_d, ["Net Non Operating Interest Income Expense", "Interest Expense",
                                        "Other Income Expense", "Pretax Income", "Tax Provision",
                                        "Net Income", "Basic EPS", "Diluted EPS"],
                                "Below the operating line",
                                "Financing costs, tax, and what finally reaches shareholders.",
                                base=rev_base)
            with right:
                years = [pd.Timestamp(d) for d in inc_d.index]
                labels = year_labels(inc_d.index, basis)
                pick_label = st.selectbox("Bridge period", list(reversed(labels)), key="bridge_year")
                row = inc_d.iloc[labels.index(pick_label)]
                rev = row.get("Total Revenue", 0) or 0
                gross = row.get("Gross Profit", np.nan)
                opinc = row.get("Operating Income", np.nan)
                net = row.get("Net Income", np.nan)
                cogs = -(rev - gross) if _isnum(gross) else 0
                opex = -(gross - opinc) if _isnum(gross) and _isnum(opinc) else 0
                below = -(opinc - net) if _isnum(opinc) and _isnum(net) else 0
                figw = go.Figure(go.Waterfall(
                    orientation="v",
                    measure=["absolute", "relative", "total", "relative", "total", "relative", "total"],
                    x=["Revenue", "Cost of revenue", "Gross profit", "Operating costs",
                       "Operating profit", "Interest & tax", "Net income"],
                    y=[rev, cogs, 0, opex, 0, below, 0],
                    connector={"line": {"color": T["border"]}},
                    increasing={"marker": {"color": T["success"]}},
                    decreasing={"marker": {"color": T["danger"]}},
                    totals={"marker": {"color": T["accent"]}}))
                figw.update_yaxes(title_text=sym)
                style_fig(figw, height=430, legend="off")
                figure(figw, f"Profit bridge, {pick_label}",
                       "Every step from revenue down to net income, sized to the amount it adds or removes.",
                       "Read left to right. Blue bars are subtotals; red bars are what was deducted to get "
                       "there. The **tallest red bar is the company's largest cost**, and the fastest place "
                       "to look when margins move.",
                       "The bridge makes it obvious whether profit is being made or lost in production "
                       "(cost of revenue), in overheads, or below the operating line in financing and tax.")

    with t_bs:
        if bs_d.empty:
            empty_state("No balance sheet on this basis.")
        else:
            asset_base = col(bs_d, "Total Assets")
            left, right = st.columns([1.5, 1])
            with left:
                statement_table(bs_d, ["Cash And Cash Equivalents", "Other Short Term Investments",
                                       "Accounts Receivable", "Inventory", "Current Assets"],
                                "Current assets", "Resources expected to convert to cash within a year.",
                                base=asset_base, base_label="total assets")
                statement_table(bs_d, ["Net PPE", "Goodwill", "Other Intangible Assets",
                                       "Total Non Current Assets", "Total Assets"],
                                "Non-current assets", "The long-lived asset base.",
                                base=asset_base, base_label="total assets")
                statement_table(bs_d, ["Accounts Payable", "Current Debt", "Current Liabilities",
                                       "Long Term Debt", "Total Non Current Liabilities",
                                       "Total Liabilities Net Minority Interest"],
                                "Liabilities", "What is owed, split by when it falls due.",
                                base=asset_base, base_label="total assets")
                statement_table(bs_d, ["Common Stock", "Retained Earnings", "Stockholders Equity"],
                                "Equity", "The shareholders' residual claim.",
                                base=asset_base, base_label="total assets")
            with right:
                latest = bs_d.iloc[-1]
                ca = latest.get("Current Assets", 0) or 0
                ta = latest.get("Total Assets", 0) or 0
                figp = go.Figure(go.Pie(labels=["Current (liquid)", "Non-current (fixed)"],
                                        values=[ca, max(ta - ca, 0)], hole=.58,
                                        marker=dict(colors=[T["accent_soft"], T["faint"]])))
                style_fig(figp, height=270)
                figure(figp, "Asset mix",
                       "The split between assets that turn into cash within a year and those that do not.",
                       "A heavy current share means flexibility, and sometimes idle capital. A heavy "
                       "non-current share means the business is capital-intensive: earnings depend on assets "
                       "that cannot be liquidated quickly.",
                       "Asset mix sets how quickly a business can react to a downturn.")
                x = year_labels(bs_d.index, basis)
                figl = go.Figure()
                if "Current Assets" in bs_d.columns and "Current Liabilities" in bs_d.columns:
                    figl.add_trace(go.Scatter(x=x, y=bs_d["Current Assets"] / bs_d["Current Liabilities"],
                                              name="Current ratio", mode="lines+markers",
                                              line=dict(color=T["accent"], width=2.5)))
                    figl.add_hline(y=1.0, line_dash="dot", line_color=T["danger"])
                    figl.update_xaxes(type="category")
                    style_fig(figl, height=250, legend="off")
                    figure(figl, "Liquidity trend",
                           "Current assets divided by current liabilities, period by period.",
                           "The dotted line is 1.0x, where short-term obligations exactly consume short-term "
                           "assets. Below it, the company depends on refinancing or on cash still to be "
                           "generated. Comfortably above 2.0x can mean capital sitting idle.",
                           "The direction matters more than the level: a ratio falling steadily toward 1.0x is "
                           "an early warning even while it is still technically fine.")

    with t_cf:
        if cf_d.empty:
            empty_state("No cash flow statement on this basis.")
        else:
            statement_table(cf_d, ["Net Income", "Depreciation And Amortization",
                                   "Stock Based Compensation", "Change In Working Capital",
                                   "Operating Cash Flow"],
                            "Operating activities", "Cash generated by running the business.")
            statement_table(cf_d, ["Capital Expenditure", "Purchase Of Business",
                                   "Net Investment Purchase And Sale", "Investing Cash Flow"],
                            "Investing activities", "Cash spent on, or released by, the asset base.")
            statement_table(cf_d, ["Net Issuance Payments Of Debt", "Repurchase Of Capital Stock",
                                   "Cash Dividends Paid", "Financing Cash Flow"],
                            "Financing activities", "Cash exchanged with lenders and shareholders.")
            statement_table(cf_d, ["Free Cash Flow", "End Cash Position"],
                            "Summary", "The bottom line of the cash statement.")

    # --- Export ---------------------------------------------------------------
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, frame in (("income_statement", inc_d), ("balance_sheet", bs_d), ("cash_flow", cf_d)):
            if not frame.empty:
                z.writestr(f"{co.ticker}_{name}_{basis.lower()}.csv", frame.T.to_csv())
    st.download_button(f"Download all three statements ({basis}, {target_currency}) as CSV",
                       buf.getvalue(), file_name=f"{co.ticker}_statements_{basis.lower()}.zip",
                       mime="application/zip")


# ==============================================================================
elif module == "4. Cash Flow Quality":
    cf_d, inc_d = to_display(co.cf, fx), to_display(co.inc, fx)
    if cf_d.empty:
        empty_state("No cash flow statement available for this symbol.")
        st.stop()

    x = year_labels(cf_d.index)
    ocf = col(cf_d, "Operating Cash Flow")
    capex = col(cf_d, "Capital Expenditure")
    fcf = col(cf_d, "Free Cash Flow")
    if fcf is None and ocf is not None and capex is not None:
        fcf = ocf + capex  # capex is reported negative
    ni = col(inc_d, "Net Income")
    rev = col(inc_d, "Total Revenue")

    section("Does the profit turn into cash?",
            "Accounting profit is an opinion; cash is a fact. This section tests how much of one becomes the other.")

    l_ocf = float(ocf.dropna().iloc[-1]) if ocf is not None and not ocf.dropna().empty else None
    l_fcf = float(fcf.dropna().iloc[-1]) if fcf is not None and not fcf.dropna().empty else None
    l_ni = float(ni.dropna().iloc[-1]) if ni is not None and not ni.dropna().empty else None
    l_capex = abs(float(capex.dropna().iloc[-1])) if capex is not None and not capex.dropna().empty else None
    l_rev = float(rev.dropna().iloc[-1]) if rev is not None and not rev.dropna().empty else None
    conversion = safe_div(l_ocf, l_ni)
    intensity = safe_div(l_capex, l_ocf)
    fcf_margin = safe_div(l_fcf, l_rev)
    div_paid = abs(last(cf_d, "Cash Dividends Paid") or 0)
    buyback = abs(last(cf_d, "Repurchase Of Capital Stock") or 0)

    kpi_grid([
        {"label": "Operating cash flow", "value": Fmt.money(l_ocf, sym), "sub": "Latest reported year",
         "tone": "good" if (l_ocf or 0) > 0 else "bad"},
        {"label": "Free cash flow", "value": Fmt.money(l_fcf, sym),
         "sub": f"{Fmt.as_pct(fcf_margin)} of revenue", "tone": "good" if (l_fcf or 0) > 0 else "bad",
         "help": "Operating cash flow after capital expenditure: the cash genuinely available to owners and lenders."},
        {"label": "Cash conversion", "value": Fmt.ratio(conversion),
         "sub": "Operating cash flow per unit of net income",
         "tone": tone_for(conversion, 1.0, 0.7),
         "help": "Above 1.0x means reported profit is more than covered by cash."},
        {"label": "Capital intensity", "value": Fmt.as_pct(intensity),
         "sub": "Capex as a share of operating cash flow",
         "tone": tone_for((intensity or 0) * 100 if intensity is not None else None, 25, 80, higher_better=False)},
        {"label": "FCF per share", "value": Fmt.price(safe_div(l_fcf, co.shares), sym),
         "sub": f"Price is {Fmt.ratio(safe_div((co.price or 0) * fx, safe_div(l_fcf, co.shares)))} of it",
         "tone": "flat"},
        {"label": "Cash returned to owners", "value": Fmt.money(div_paid + buyback, sym),
         "sub": f"Dividends {Fmt.money(div_paid, sym)} · buybacks {Fmt.money(buyback, sym)}",
         "tone": "good" if (l_fcf or 0) >= (div_paid + buyback) else "warn",
         "help": "Distributions funded from free cash flow are sustainable; those funded from debt are not."},
    ])

    c1, c2 = st.columns(2)
    with c1:
        figq = go.Figure()
        if ocf is not None:
            figq.add_trace(go.Bar(x=x, y=ocf, name="Operating cash flow", marker_color=T["success"], opacity=.85))
        if ni is not None:
            figq.add_trace(go.Scatter(x=year_labels(inc_d.index), y=ni, name="Net income",
                                      mode="lines+markers", line=dict(color=T["accent"], width=2.5, dash="dot")))
        figq.update_xaxes(type="category")
        figq.update_yaxes(title_text=sym)
        style_fig(figq, height=320)
        figure(figq, "Cash from operations against reported profit",
               "Operating cash flow (bars) beside net income (dotted line) for each reported year.",
               "Bars **above** the line means cash exceeds accounting profit — usually depreciation and other "
               "non-cash charges, which is healthy. Bars persistently **below** the line means profit is being "
               "recognised before the cash arrives.",
               "One year below the line is normal for a fast-growing business building receivables and "
               "inventory. Several years below it is the classic pattern behind an earnings disappointment.",
               data=pd.DataFrame({"Operating cash flow": ocf, "Net income": ni}))
    with c2:
        figc = go.Figure()
        if capex is not None:
            figc.add_trace(go.Bar(x=x, y=capex.abs(), name="Capital expenditure",
                                  marker_color=T["danger"], opacity=.8))
        if ocf is not None:
            figc.add_trace(go.Scatter(x=x, y=ocf, name="Operating cash flow",
                                      mode="lines+markers", line=dict(color=T["success"], width=2.5)))
        figc.update_xaxes(type="category")
        figc.update_yaxes(title_text=sym)
        style_fig(figc, height=320)
        figure(figc, "Reinvestment against cash generated",
               "Capital expenditure (bars, shown as a positive amount) against operating cash flow (line).",
               "The gap between line and bars is roughly free cash flow. Bars approaching the line mean almost "
               "everything generated is being spent again to keep the business running or growing.",
               f"At {Fmt.as_pct(intensity)} of operating cash flow, this business is "
               f"{'asset-light' if (intensity or 0) < 0.25 else 'moderately capital-intensive' if (intensity or 0) < 0.8 else 'heavily capital-intensive'}. "
               "That determines how much of its growth can be self-funded.",
               data=pd.DataFrame({"Capex": capex.abs() if capex is not None else None, "OCF": ocf}))

    if l_ni is not None and l_fcf is not None:
        figb = go.Figure(go.Waterfall(
            orientation="v", measure=["absolute", "relative", "relative", "total"],
            x=["Net income", "Non-cash & working capital", "Capital expenditure", "Free cash flow"],
            y=[l_ni, (l_ocf or l_ni) - l_ni, -(l_capex or 0), 0],
            connector={"line": {"color": T["border"]}},
            increasing={"marker": {"color": T["success"]}},
            decreasing={"marker": {"color": T["danger"]}},
            totals={"marker": {"color": T["accent"]}}))
        figb.update_yaxes(title_text=sym)
        style_fig(figb, height=340, legend="off")
        figure(figb, "From accounting profit to free cash flow",
               "The two adjustments that separate the profit figure in the income statement from the cash left "
               "at the end of the year.",
               "The first step adds back non-cash charges and removes working-capital absorption; the second "
               "subtracts what was spent on plant, equipment and other long-lived assets. Whichever step is "
               "larger is where cash is really being decided.",
               "This is the single most useful chart for a dividend or buyback question: only the final bar can "
               "fund distributions without borrowing.")

    section("Enterprise value bridge",
            "What it would cost to acquire the whole business rather than just its equity.")
    ev_mcap = (co.market_cap or 0) * fx
    ev_debt = (info.get("totalDebt") or 0) * fx
    ev_cash = (info.get("totalCash") or 0) * fx
    ev_total = ev_mcap + ev_debt - ev_cash
    e1, e2 = st.columns([1, 1.25])
    with e1:
        kpi_grid([
            {"label": "Market capitalisation", "value": Fmt.money(ev_mcap, sym), "sub": "The equity alone", "tone": "flat"},
            {"label": "Plus total debt", "value": Fmt.money(ev_debt, sym), "sub": "Assumed by an acquirer", "tone": "flat"},
            {"label": "Less cash", "value": Fmt.money(ev_cash, sym), "sub": "Comes with the business", "tone": "flat"},
            {"label": "Enterprise value", "value": Fmt.money(ev_total, sym), "sub": "The cost of the whole business", "tone": "flat"},
        ], min_width=185, record=False)
    with e2:
        fige = go.Figure(go.Waterfall(
            orientation="v", measure=["absolute", "relative", "relative", "total"],
            x=["Market cap", "Plus debt", "Less cash", "Enterprise value"],
            y=[ev_mcap, ev_debt, -ev_cash, 0],
            connector={"line": {"color": T["border"]}},
            increasing={"marker": {"color": T["danger"]}},
            decreasing={"marker": {"color": T["success"]}},
            totals={"marker": {"color": T["accent"]}}))
        fige.update_yaxes(title_text=sym)
        style_fig(fige, height=320, legend="off")
        figure(fige, "Enterprise value composition",
               "Market capitalisation adjusted for the debt an acquirer would assume and the cash they "
               "would receive.",
               "Debt **adds** to the cost of acquiring a business; cash **reduces** it. The further enterprise "
               "value sits above market cap, the more of this company is financed by lenders rather than owners.",
               "Enterprise value is the right numerator when comparing companies with different debt loads — "
               "which is why EV/EBITDA travels better across peers than P/E does.")

    net_pos = ev_debt - ev_cash
    net_debt_comment = (
        "Net debt magnifies both returns and risk: interest is paid before shareholders see anything, and "
        "refinancing happens on the market's terms rather than the company's."
        if net_pos >= 0 else
        "A net cash position is optionality: it funds downturns, acquisitions and buybacks without needing "
        "anyone's permission. It also drags on return on equity while it sits idle.")
    note(f"""
Enterprise value is **{Fmt.money(ev_total, sym)}**, against a market capitalisation of {Fmt.money(ev_mcap, sym)}.
The company holds a net **{'debt' if net_pos >= 0 else 'cash'}** position of {Fmt.money(abs(net_pos), sym)}.
- {net_debt_comment}
- Free cash flow of {Fmt.money(l_fcf, sym)} covers the {Fmt.money(div_paid + buyback, sym)} returned to
shareholders {'comfortably' if (l_fcf or 0) > (div_paid + buyback) * 1.2 else 'only just' if (l_fcf or 0) >= (div_paid + buyback) else 'not at all — the shortfall is being financed'}.
- Cross-check the leverage read against Net debt / EBITDA of {Fmt.ratio(safe_div(co.net_debt, info.get('ebitda')))}
in section 1 before drawing a conclusion.
""", tone="warn" if net_pos > 0 and (l_fcf or 0) < (div_paid + buyback) else "neu")


# ==============================================================================
elif module == "5. Intrinsic Valuation":
    section("Discounted cash flow",
            "What the business is worth on its own cash generation, independent of what the market happens "
            "to pay for it today.")

    # --- Assumption defaults, derived rather than hardcoded --------------------
    rf = load_risk_free_rate()
    beta = info.get("beta") if _isnum(info.get("beta")) else 1.0
    inc_a, bs_a, cf_a = co.inc, co.bs, co.cf
    tax_rate = 0.21
    if not inc_a.empty and {"Tax Provision", "Pretax Income"}.issubset(inc_a.columns):
        pretax, taxp = last(inc_a, "Pretax Income"), last(inc_a, "Tax Provision")
        if _isnum(pretax) and pretax:
            tax_rate = float(np.clip(taxp / pretax, 0.0, 0.40))
    cost_debt = 0.05
    int_exp = last(inc_a, "Interest Expense")
    tot_debt = info.get("totalDebt") or last(bs_a, "Total Debt")
    if _isnum(int_exp) and _isnum(tot_debt) and tot_debt:
        cost_debt = float(np.clip(abs(int_exp) / tot_debt, 0.005, 0.20))

    c_in, c_out = st.columns([1, 2.15], vertical_alignment="top")

    with c_in:
        st.markdown("<div class='eyebrow'>Assumptions</div>", unsafe_allow_html=True)
        erp = st.slider("Equity risk premium (%)", 3.0, 8.0, 5.0, 0.25,
                        help="The extra annual return investors demand for holding equities over government bonds.") / 100
        wacc_auto, cost_equity, w_e, w_d = Valuation.capm_wacc(
            beta, rf, erp, cost_debt, tax_rate, co.market_cap, info.get("totalDebt") or 0)
        wacc_auto = float(np.clip(wacc_auto, 0.04, 0.20))
        wacc = st.slider("Discount rate / WACC (%)", 4.0, 20.0, round(wacc_auto * 100, 1), 0.1,
                         help="Pre-filled from CAPM using the live 10-year yield, the reported beta and the "
                              "company's own after-tax cost of debt.") / 100

        rev_g = info.get("revenueGrowth") if _isnum(info.get("revenueGrowth")) else None
        earn_g = info.get("earningsGrowth") if _isnum(info.get("earningsGrowth")) else None
        hist_g = extras.get("rev_cagr")
        candidates = [g for g in (rev_g, earn_g, hist_g) if g is not None]
        suggested = float(np.clip(np.median(candidates) if candidates else 0.05, 0.0, 0.15))
        g1 = st.slider("Stage 1 growth (%)", -10.0, 40.0, round(suggested * 100, 1), 0.5,
                       help="Free cash flow growth during the explicit forecast.") / 100
        years1 = st.slider("Stage 1 length (years)", 3, 10, 5)
        term_g = st.slider("Terminal growth (%)", 0.0, 4.0, 2.5, 0.1,
                           help="Perpetual growth after the fade. Must stay below long-run nominal GDP.") / 100
        g2 = (g1 + term_g) / 2  # fade stage: converges from stage 1 toward the terminal rate

        fcf_choice = segmented("Starting cash flow", ["Latest", "Normalised", "Custom"], key="fcf_basis",
                               help="Normalised uses the median free cash flow across reported years, which "
                                    "avoids anchoring the whole model on one unusually good or bad year.")
        base_latest = (co.base_fcf or 0) * fx
        base_norm = (co.normalised_fcf or 0) * fx
        if fcf_choice == "Latest":
            base_fcf = base_latest
        elif fcf_choice == "Normalised":
            base_fcf = base_norm
        else:
            base_fcf = st.number_input(f"Free cash flow ({sym})", value=float(base_latest), step=float(abs(base_latest) / 20 or 1.0))
        st.caption(f"Latest {Fmt.money(base_latest, sym)} · median {Fmt.money(base_norm, sym)}")

        with st.expander("Where these defaults come from", expanded=False):
            st.markdown(f"""
<div class='exp-block'>
<b>Discount rate {wacc_auto * 100:,.1f}%</b> — CAPM: risk-free {rf * 100:,.2f}% (live 10-year Treasury)
+ beta {beta:,.2f} × equity risk premium {erp * 100:,.1f}% gives a cost of equity of
{cost_equity * 100:,.1f}%. Blended with an after-tax cost of debt of
{cost_debt * (1 - tax_rate) * 100:,.1f}% at weights {w_e * 100:,.0f}% equity / {w_d * 100:,.0f}% debt.<br><br>
<b>Effective tax rate {tax_rate * 100:,.1f}%</b> — tax provision over pre-tax income from the latest
income statement, clamped to a 0–40% band so a one-off credit cannot distort the model.<br><br>
<b>Stage 1 growth {suggested * 100:,.1f}%</b> — the median of reported revenue growth, earnings growth and
the multi-year revenue CAGR, capped at 15% for conservatism.<br><br>
<b>Fade stage</b> — five further years growing at {g2 * 100:,.1f}%, halfway between stage 1 and the
terminal rate, so growth decays rather than stopping abruptly.
</div>""", unsafe_allow_html=True)

    with c_out:
        shares = co.shares
        net_debt_disp = co.net_debt * fx
        res = Valuation.dcf(base_fcf, g1, years1, g2, wacc, term_g, net_debt_disp, shares)
        cur_price = (co.price or 0) * fx

        if not res or not shares:
            empty_state("The DCF cannot be computed for this symbol.",
                        "It needs a share count and a positive free cash flow figure. Loss-making or "
                        "cash-burning companies are better approached through the peer comparables section.")
        else:
            fair = res["fair_value"]
            upside = safe_div(fair, cur_price)
            upside = (upside - 1) if upside else None
            term_share = res["terminal_share"]
            kpi_grid([
                {"label": "Fair value per share", "value": Fmt.price(fair, sym),
                 "sub": f"Against {Fmt.price(cur_price, sym)} in the market",
                 "tone": "good" if (upside or 0) > 0.1 else "bad" if (upside or 0) < -0.1 else "warn"},
                {"label": "Upside to fair value", "value": Fmt.as_pct(upside, signed=True),
                 "sub": "Model versus market", "tone": tone_for((upside or 0) * 100 if upside is not None else None, 10, -10)},
                {"label": "Enterprise value", "value": Fmt.money(res["enterprise_value"], sym),
                 "sub": f"Market says {Fmt.money((info.get('enterpriseValue') or 0) * fx, sym)}", "tone": "flat"},
                {"label": "Value beyond the forecast", "value": Fmt.as_pct(term_share),
                 "sub": "Share of value in the terminal figure",
                 "tone": tone_for((term_share or 0) * 100 if term_share else None, 60, 85, higher_better=False),
                 "help": "The higher this is, the more the answer depends on assumptions no one can verify."},
            ], min_width=195)

            figv = go.Figure(go.Waterfall(
                orientation="v", measure=["absolute", "relative", "total", "relative", "total"],
                x=["Forecast cash flows", "Terminal value", "Enterprise value", "Net debt", "Equity value"],
                y=[res["pv_explicit"], res["pv_terminal"], 0, -net_debt_disp, 0],
                connector={"line": {"color": T["border"]}},
                increasing={"marker": {"color": T["success"]}},
                decreasing={"marker": {"color": T["danger"]}},
                totals={"marker": {"color": T["accent"]}}))
            figv.update_yaxes(title_text=sym)
            style_fig(figv, height=310, legend="off")
            figure(figv, "How the valuation is built",
                   "Present value of the explicit forecast, plus the present value of everything after it, "
                   "less net debt, giving the value attributable to shareholders.",
                   "Look at the relative height of the first two bars. If the terminal bar dwarfs the forecast "
                   "bar, the model is mostly an opinion about the distant future rather than a projection of "
                   "the next few years.",
                   f"Here {Fmt.as_pct(term_share)} of enterprise value sits in the terminal figure. "
                   "Above roughly 75% is normal for a growth company and a reason to weight the sensitivity "
                   "grid below more heavily than the point estimate.")

            # --- Reverse DCF -------------------------------------------------
            implied = Valuation.implied_growth(cur_price, base_fcf, years1, g2, wacc, term_g,
                                               net_debt_disp, shares)
            subhead("Reverse DCF — what the market is already assuming",
                    "Holding your discount rate and terminal assumptions fixed, this solves for the stage-1 "
                    "growth rate that would exactly justify today's price.")
            if implied is None:
                st.caption("No growth rate within a −60% to +100% range reproduces the current price under "
                           "these assumptions — usually a sign the discount rate or starting cash flow needs revisiting.")
            else:
                gap = g1 - implied
                kpi_grid([
                    {"label": "Growth priced in by the market", "value": Fmt.as_pct(implied),
                     "sub": "Stage-1 growth implied by today's price", "tone": "flat"},
                    {"label": "Growth you assumed", "value": Fmt.as_pct(g1),
                     "sub": "Your stage-1 input", "tone": "flat"},
                    {"label": "Difference", "value": Fmt.as_pct(gap, signed=True),
                     "sub": "Positive means you are more optimistic than the market",
                     "tone": "good" if gap > 0.01 else "bad" if gap < -0.01 else "warn"},
                ], min_width=210)
                note(f"""
At {Fmt.price(cur_price, sym)}, the market is implicitly assuming free cash flow grows about
**{Fmt.as_pct(implied)}** a year through stage 1.
- The useful question is not "is the fair value right" but **"is that implied growth achievable?"** Compare it
against the company's own history: revenue has compounded at {Fmt.as_pct(extras.get('rev_cagr'))} over the
reported period.
- {'You are assuming faster growth than the market, which is where the upside in this model comes from. That view needs a reason: a product cycle, a margin programme, an end-market shift.' if gap > 0 else 'You are assuming slower growth than the market, so this model shows downside. The market may be seeing something your assumptions do not capture.'}
- A reverse DCF sidesteps the biggest weakness of a forward DCF: it stops you arguing with a point estimate
and makes you argue with an assumption instead.
""", tone="pos" if gap > 0 else "warn")

            # --- Scenarios ----------------------------------------------------
            subhead("Scenarios", "The same model under three futures, with a probability-weighted result.")
            scen_defs = [
                ("Bear", max(g1 - 0.06, -0.15), wacc + 0.015, max(term_g - 0.005, 0.0), 0.25),
                ("Base", g1, wacc, term_g, 0.50),
                ("Bull", g1 + 0.05, max(wacc - 0.01, term_g + 0.02), min(term_g + 0.005, 0.045), 0.25),
            ]
            rows, weighted = [], 0.0
            for name, gg, ww, tt, prob in scen_defs:
                r = Valuation.dcf(base_fcf, gg, years1, g2, ww, tt, net_debt_disp, shares)
                if not r:
                    continue
                fv = r["fair_value"]
                weighted += fv * prob
                rows.append({"Scenario": name, "Stage 1 growth": gg * 100, "Discount rate": ww * 100,
                             "Terminal growth": tt * 100, "Fair value": fv,
                             "Upside %": (fv / cur_price - 1) * 100 if cur_price else np.nan,
                             "Probability": prob * 100})
            if rows:
                sdf = pd.DataFrame(rows).set_index("Scenario")
                s1, s2 = st.columns([1.3, 1])
                with s1:
                    table(sdf, "Scenario outcomes",
                          "Each scenario flexes growth, the discount rate and terminal growth together, the way "
                          "they actually move.",
                          formats={"Stage 1 growth": "{:,.1f}%", "Discount rate": "{:,.1f}%",
                                   "Terminal growth": "{:,.1f}%", "Fair value": "{:,.2f}",
                                   "Upside %": "{:+,.1f}%", "Probability": "{:,.0f}%"})
                with s2:
                    kpi_grid([
                        {"label": "Probability-weighted value", "value": Fmt.price(weighted, sym),
                         "sub": f"{Fmt.as_pct(weighted / cur_price - 1 if cur_price else None, signed=True)} versus market",
                         "tone": tone_for((weighted / cur_price - 1) * 100 if cur_price else None, 10, -10)},
                        {"label": "Range width", "value": Fmt.price(sdf["Fair value"].max() - sdf["Fair value"].min(), sym),
                         "sub": "Bull less bear — the honest uncertainty", "tone": "flat"},
                    ], min_width=200, record=False)

            # --- Sensitivity ---------------------------------------------------
            subhead("Sensitivity", "Fair value across a grid of discount rates and terminal growth rates.")
            w_range = np.linspace(max(wacc - 0.02, term_g + 0.01), wacc + 0.02, 5)
            g_range = np.linspace(max(term_g - 0.01, 0.0), term_g + 0.01, 5)
            grid = [[(Valuation.dcf(base_fcf, g1, years1, g2, w, g, net_debt_disp, shares) or {}).get("fair_value", np.nan)
                     for g in g_range] for w in w_range]
            grid_df = pd.DataFrame(grid, index=[f"{w:.1%}" for w in w_range],
                                   columns=[f"{g:.1%}" for g in g_range])
            figh = go.Figure(go.Heatmap(
                z=grid_df.values, x=grid_df.columns, y=grid_df.index, colorscale="RdYlGn",
                text=[[f"{v:,.0f}" for v in row] for row in grid_df.values],
                texttemplate="%{text}", textfont={"size": 11},
                colorbar=dict(title=f"Value<br>({sym})")))
            figh.update_xaxes(title_text="Terminal growth")
            figh.update_yaxes(title_text="Discount rate", autorange="reversed")
            style_fig(figh, height=330, legend="off")
            figure(figh, "Fair value sensitivity to discount rate and terminal growth",
                   f"Fair value per share in {target_currency} across a grid around your base assumptions. "
                   f"The market price today is {Fmt.price(cur_price, sym)}.",
                   "Find the cells at or above the current price. If most of the grid clears it, the "
                   "conclusion survives a range of reasonable assumptions. If only the top-right corner does — "
                   "lowest discount rate, highest terminal growth — the case depends on everything going right.",
                   "A DCF's honest output is a range, not a number. This grid is that range.",
                   data=grid_df)

            # --- Cross-method summary -------------------------------------------
            subhead("Valuation summary across methods",
                    "Every independent estimate this app can compute, on one scale, against the market price.")
            eps = (info.get("trailingEps") or 0) * fx
            bvps = (info.get("bookValue") or 0) * fx
            methods = {
                "DCF — base case": fair,
                "DCF — probability weighted": weighted or None,
                "Graham number": (Valuation.graham_number(info.get("trailingEps"), info.get("bookValue")) or 0) * fx or None,
                "Peter Lynch (PEG = 1)": (Valuation.lynch_value(info.get("trailingEps"),
                                                                (info.get("earningsGrowth") or 0) * 100) or 0) * fx or None,
                "Analyst mean target": (info.get("targetMeanPrice") or 0) * fx or None,
                "52-week high": (info.get("fiftyTwoWeekHigh") or 0) * fx or None,
                "52-week low": (info.get("fiftyTwoWeekLow") or 0) * fx or None,
            }
            methods = {k: v for k, v in methods.items() if _isnum(v) and v > 0}
            if methods:
                figm = go.Figure(go.Bar(
                    x=list(methods.values()), y=list(methods.keys()), orientation="h",
                    marker_color=[T["success"] if v > cur_price else T["danger"] for v in methods.values()],
                    text=[Fmt.price(v, sym) for v in methods.values()], textposition="outside", opacity=.85))
                figm.add_vline(x=cur_price, line_width=2, line_dash="dash", line_color=T["text"],
                               annotation_text="Market price", annotation_position="top")
                figm.update_xaxes(title_text=f"Implied value per share ({sym})")
                style_fig(figm, height=330, legend="off", margin=dict(l=8, r=70, t=26, b=8))
                figure(figm, "Independent value estimates against the market price",
                       "Each bar is a separate method's implied value per share; the dashed line is what the "
                       "market is charging today.",
                       "Bars to the **right** of the line imply the shares are cheap on that method; to the "
                       "**left**, expensive. Agreement between methods that rest on different inputs — cash "
                       "flows, book value, earnings — is far more persuasive than any single bar.",
                       "Methods disagreeing sharply is information too: it usually means one input (a one-off "
                       "earnings item, an unusual balance sheet, an aggressive growth assumption) is doing all "
                       "the work.",
                       data=pd.DataFrame({"Implied value": methods}))

            note(f"""
On these assumptions the model puts fair value at **{Fmt.price(fair, sym)}**, against a market price of
{Fmt.price(cur_price, sym)} — a gap of **{Fmt.as_pct(upside, signed=True)}**.
- **The two inputs that matter most** are the discount rate and the starting cash flow. A one-point change in
the discount rate moves the answer far more than a one-point change in growth, because it compounds through
every discount factor and through the terminal value.
- **Before trusting the gap**, check that the starting free cash flow of {Fmt.money(base_fcf, sym)} is
representative rather than a peak or a trough — the Normalised option uses the median of reported years for
exactly this reason.
- **A large gap is not proof the market is wrong.** More often it means your growth or risk assumptions differ
from consensus, which the reverse DCF above makes explicit.
""", tone="pos" if (upside or 0) > 0.1 else "neg" if (upside or 0) < -0.1 else "neu")


# ==============================================================================
elif module == "6. Peer Comparables":
    section("Relative valuation",
            "What the market pays for comparable businesses today — a different question from what this "
            "business is intrinsically worth.")

    with st.spinner("Matching live industry peers…"):
        suggested = suggest_peers(co.ticker, info.get("sector"), info.get("industry"), max_n=8)
    pool = list(dict.fromkeys(suggested + ["SPY", "QQQ"]))
    with st.spinner("Resolving company names…"):
        names = ticker_names(tuple(pool))

    p1, p2 = st.columns([2, 1])
    with p1:
        selected = st.multiselect(
            "Peer group", pool, default=suggested[:5] or pool[:3],
            format_func=lambda t: f"{t} — {names.get(t)}" if names.get(t) else t)
    with p2:
        custom = st.text_input("Add symbols", placeholder="NVDA, AMD, 005930.KS")
    if custom:
        selected = list(dict.fromkeys(selected + [c.strip().upper() for c in custom.split(",") if c.strip()]))

    st.caption(
        f"Peers are matched live on **{info.get('industry') or 'industry'}** where possible, falling back to the "
        f"wider **{info.get('sector') or 'sector'}**, drawn from current sector-ETF holdings rather than a fixed "
        f"list. Everything is converted to {target_currency}."
        if suggested else
        "No live industry matches came back just now. Add symbols manually to build a comparison set.")

    universe = tuple(dict.fromkeys(selected + [co.ticker]))
    if len(universe) < 2:
        empty_state("Select at least one peer to compare against.")
        st.stop()

    with st.spinner(f"Fetching {len(universe)} companies in parallel…"):
        peers = load_comparables(universe, target_currency)

    if peers.empty or co.ticker not in peers.index:
        empty_state("Could not build a peer table from the current selection.",
                    "One or more symbols returned no usable data. Try a different peer set.")
        st.stop()

    display_cols = ["Name", "Price", "P/E", "Fwd P/E", "P/B", "EV/Sales", "EV/EBITDA",
                    "FCF Yield (%)", "Op Margin (%)", "ROE (%)", "Revenue Growth (%)",
                    "Net Debt/EBITDA", "Market Cap"]
    shown = peers[[c for c in display_cols if c in peers.columns]]
    table(shown, "Peer multiples and fundamentals",
          f"Every selected company on the same basis, in {target_currency}. The highlighted row is {co.ticker}.",
          formats={"Price": "{:,.2f}", "P/E": "{:,.1f}", "Fwd P/E": "{:,.1f}", "P/B": "{:,.2f}",
                   "EV/Sales": "{:,.2f}", "EV/EBITDA": "{:,.1f}", "FCF Yield (%)": "{:,.1f}%",
                   "Op Margin (%)": "{:,.1f}%", "ROE (%)": "{:,.1f}%",
                   "Revenue Growth (%)": "{:+,.1f}%", "Net Debt/EBITDA": "{:,.2f}",
                   "Market Cap": lambda v: Fmt.money(v, sym)},
          highlight=co.ticker)

    peers_only = peers.drop(index=co.ticker)
    target = peers.loc[co.ticker]

    # --- Percentile positioning ------------------------------------------------
    rank_metrics = [("P/E", False), ("EV/EBITDA", False), ("P/B", False), ("EV/Sales", False),
                    ("FCF Yield (%)", True), ("Op Margin (%)", True), ("ROE (%)", True),
                    ("Revenue Growth (%)", True)]
    rank_rows = []
    for metric, higher_better in rank_metrics:
        if metric not in peers.columns:
            continue
        series = peers[metric].dropna()
        if len(series) < 3 or co.ticker not in series.index:
            continue
        pctile = (series < series.loc[co.ticker]).mean() * 100
        rank_rows.append({"Metric": metric,
                          "Percentile": pctile if higher_better else 100 - pctile,
                          "Value": series.loc[co.ticker],
                          "Peer median": series.drop(co.ticker).median()})
    if rank_rows:
        rdf = pd.DataFrame(rank_rows).set_index("Metric")
        figr = go.Figure(go.Bar(
            x=rdf["Percentile"], y=rdf.index, orientation="h",
            marker_color=[T["success"] if v >= 50 else T["danger"] for v in rdf["Percentile"]],
            text=[f"{v:,.0f}th" for v in rdf["Percentile"]], textposition="outside", opacity=.85))
        figr.add_vline(x=50, line_dash="dot", line_color=T["faint"])
        figr.update_xaxes(title_text="Percentile within the peer group (higher is better)", range=[0, 108])
        style_fig(figr, height=330, legend="off", margin=dict(l=8, r=50, t=26, b=8))
        figure(figr, f"Where {co.ticker} ranks against its peer group",
               "Each bar is this company's percentile within the selected peer set, already oriented so that "
               "further right is always the more favourable outcome — cheap on valuation metrics, high on "
               "quality and growth metrics.",
               "The dotted line is the peer median. A profile with bars far right on quality and far left on "
               "valuation is the classic value setup; the reverse means you are paying a premium for a "
               "middling business.",
               "Percentiles travel better than raw multiples: they are unaffected by the whole sector being "
               "expensive or cheap at the moment.",
               data=rdf)

    # --- Growth versus valuation ----------------------------------------------
    scatter_df = peers.dropna(subset=["Revenue Growth (%)", "EV/EBITDA"])
    if len(scatter_df) >= 3:
        figs = px.scatter(scatter_df, x="Revenue Growth (%)", y="EV/EBITDA", text=scatter_df.index,
                          size="Market Cap", size_max=42,
                          color=[c == co.ticker for c in scatter_df.index],
                          color_discrete_map={True: T["success"], False: T["accent_soft"]},
                          trendline="ols", trendline_scope="overall",
                          trendline_color_override=T["faint"])
        figs.update_traces(textposition="top center", textfont_size=11)
        style_fig(figs, height=420, legend="off")
        med_g = scatter_df["Revenue Growth (%)"].median()
        med_v = scatter_df["EV/EBITDA"].median()
        figure(figs, "Growth against valuation",
               "Each bubble is a company: revenue growth on the horizontal axis, EV/EBITDA on the vertical, "
               "bubble size proportional to market capitalisation. The line is a least-squares fit across the group.",
               "The line is the price the group currently charges for growth. Companies **below** it are cheap "
               "relative to what they are growing; **above** it, expensive. Distance from the line matters more "
               "than absolute position.",
               f"Peer medians: {med_g:,.1f}% growth at {med_v:,.1f}x EV/EBITDA. Being below the line is a "
               "starting point for investigation, not a conclusion — the discount may be pricing in a real risk "
               "this chart cannot see.",
               data=scatter_df[["Revenue Growth (%)", "EV/EBITDA", "Market Cap"]])

    # --- Football field --------------------------------------------------------
    subhead("Implied value from peer multiples",
            "Applying the peer group's own multiples to this company's fundamentals.")
    with st.expander("What a football-field chart is", expanded=False):
        st.markdown("""
<div class='exp-block'>
Named for the yard lines it resembles, it shows a <b>range</b> of implied share prices side by side so you can
see where different methods agree.<br><br>
<b>1.</b> For each multiple, take the peer group's 25th percentile, median and 75th percentile.<br>
<b>2.</b> Apply each to <i>this</i> company's own fundamentals — its earnings per share for P/E, book value per
share for P/B, EBITDA for EV/EBITDA, revenue for EV/Sales.<br>
<b>3.</b> Each bar spans the resulting low-to-high price, with a marker at the median.<br>
<b>4.</b> The dashed line is the current market price.<br><br>
Bars mostly to the right of the line imply the shares are cheap relative to peers; mostly to the left, expensive.
Bars that disagree sharply with each other point to one input being distorted rather than to a real mispricing.
</div>""", unsafe_allow_html=True)

    shares = co.shares or 1
    net_debt_disp = co.net_debt * fx
    revenue = (info.get("totalRevenue") or 0) * fx
    ebitda = (info.get("ebitda") or 0) * fx
    fundamentals = {
        "P/E": ((info.get("trailingEps") or 0) * fx, "equity"),
        "P/B": ((info.get("bookValue") or 0) * fx, "equity"),
        "EV/EBITDA": (ebitda, "enterprise"),
        "EV/Sales": (revenue / shares if shares else 0, "equity"),
    }
    field = []
    for metric, (value, kind) in fundamentals.items():
        if metric not in peers_only.columns or not _isnum(value) or value <= 0:
            continue
        mult = peers_only[metric].dropna()
        if len(mult) < 3:
            continue

        def implied(m):
            if kind == "enterprise":
                return (m * value - net_debt_disp) / shares
            return m * value

        lo, mid, hi = implied(mult.quantile(0.25)), implied(mult.median()), implied(mult.quantile(0.75))
        if lo > 0 and hi > 0:
            field.append({"Metric": metric, "Low": lo, "Median": mid, "High": hi})

    cur_price = (co.price or 0) * fx
    if field:
        figf = go.Figure()
        for d in field:
            figf.add_trace(go.Bar(y=[d["Metric"]], x=[d["High"] - d["Low"]], base=[d["Low"]],
                                  orientation="h", marker_color=T["accent_soft"], opacity=.35,
                                  hovertemplate=f"{d['Metric']}<br>Low {d['Low']:,.2f} · "
                                                f"Median {d['Median']:,.2f} · High {d['High']:,.2f}<extra></extra>",
                                  showlegend=False))
            figf.add_trace(go.Scatter(y=[d["Metric"]], x=[d["Median"]], mode="markers",
                                      marker=dict(color=T["accent"], size=13, symbol="line-ns-open",
                                                  line=dict(width=3)), showlegend=False,
                                      hovertemplate=f"Peer median implies {d['Median']:,.2f}<extra></extra>"))
        figf.add_vline(x=cur_price, line_width=2, line_dash="dash", line_color=T["danger"],
                       annotation_text="Market price", annotation_position="top")
        figf.update_xaxes(title_text=f"Implied share price ({sym})")
        figf.update_layout(barmode="overlay")
        style_fig(figf, height=290, legend="off")
        fdf = pd.DataFrame(field).set_index("Metric")
        figure(figf, "Peer-implied price ranges",
               "One bar per multiple, spanning the price implied by the peer group's 25th to 75th percentile, "
               "with the median marked. The dashed line is today's price.",
               "If the dashed line sits **left** of most bars, peers are valued more richly than this company "
               "on those measures. Inside the bars means it is priced in line with the group. Bars that "
               "disagree with each other are the interesting case — check which fundamental is unusual.",
               "This is a relative answer only. If the whole peer group is mispriced, every bar moves together "
               "and the chart cannot tell you.",
               data=fdf)

        fdf["Upside to median (%)"] = (fdf["Median"] / cur_price - 1) * 100 if cur_price else np.nan
        avg_up = fdf["Upside to median (%)"].mean()
        spread = fdf["Upside to median (%)"].std()
        table(fdf, "Implied values by multiple",
              "The same figures as the chart, with the gap from today's price.",
              formats={"Low": "{:,.2f}", "Median": "{:,.2f}", "High": "{:,.2f}",
                       "Upside to median (%)": "{:+,.1f}%"})
        note(f"""
Averaged across the multiples above, the peer group's median valuation implies
**{Fmt.pct(avg_up, signed=True)}** against today's price.
- This is a statement about **relative** value: it says the shares look {'cheap' if avg_up > 0 else 'expensive'}
next to the peers you chose, not that the peer group itself is correctly valued.
- The methods {'broadly agree' if _isnum(spread) and spread < 15 else 'disagree materially with one another'}
{'' if _isnum(spread) and spread < 15 else ', which usually means one input — leverage, a one-off earnings item, or an accounting difference — is distorting a multiple'}.
- Peer choice drives the answer. Adding or removing two companies can move the median by more than any
analytical insight in this section, so it is worth checking the table above for names that do not really belong.
- Read this alongside section 5: the DCF answers what the business is worth, this answers what the market is
currently paying for similar businesses.
""", tone="pos" if avg_up > 5 else "neg" if avg_up < -5 else "neu")


# ==============================================================================
elif module == "7. Risk & Scenarios":
    section("Risk profile",
            "How much the position moves, how far it has fallen before, and what a year of the same behaviour "
            "could look like.")

    risk = co.risk_stats
    hist2y = co.history("2y", "1d")
    if not risk or hist2y.empty:
        empty_state("Not enough price history to compute risk statistics.")
        st.stop()

    beta = info.get("beta")
    kpi_grid([
        {"label": "Beta", "value": Fmt.ratio(beta),
         "sub": "Sensitivity to the market: 1.0 moves with it",
         "tone": tone_for(beta, 1.0, 1.6, higher_better=False)},
        {"label": "Annualised volatility", "value": Fmt.as_pct(risk.get("vol")),
         "sub": "Standard deviation of daily returns, annualised",
         "tone": tone_for((risk.get("vol") or 0) * 100, 25, 50, higher_better=False)},
        {"label": "Daily VaR (95%)", "value": Fmt.as_pct(risk.get("var_95")),
         "sub": "Exceeded on roughly one day in twenty", "tone": "flat",
         "help": "The loss threshold that 95% of daily moves stay above; it says nothing about how bad the worst 5% get."},
        {"label": "Expected shortfall", "value": Fmt.as_pct(risk.get("cvar_95")),
         "sub": "Average loss on the worst 5% of days", "tone": "flat",
         "help": "Conditional VaR: what the tail actually costs when VaR is breached."},
        {"label": "Maximum drawdown (2y)", "value": Fmt.as_pct(risk.get("max_dd")),
         "sub": "Largest peak-to-trough fall actually experienced",
         "tone": tone_for((risk.get("max_dd") or 0) * 100, -20, -45)},
        {"label": "Sortino ratio", "value": Fmt.ratio(risk.get("sortino")),
         "sub": "Return per unit of downside volatility",
         "tone": tone_for(risk.get("sortino"), 1.0, 0.0),
         "help": "Like Sharpe, but only penalises downside moves, which is what investors actually mind."},
    ])

    close = hist2y["Close"].dropna()
    ret = close.pct_change().dropna()
    r1, r2 = st.columns(2)
    with r1:
        cum = (1 + ret).cumprod()
        dd = (cum / cum.expanding().max() - 1) * 100
        figd = go.Figure(go.Scatter(x=dd.index, y=dd, fill="tozeroy", name="Drawdown",
                                    line=dict(color=T["danger"], width=1.4),
                                    fillcolor="rgba(207,44,30,0.18)"))
        figd.update_yaxes(title_text="Below the running peak (%)", ticksuffix="%")
        style_fig(figd, height=310, legend="off")
        figure(figd, "Underwater curve",
               "How far below its own running peak the share price has been, every day for the past two years.",
               "Depth is how much was lost from the top; **width is how long it took to recover**, which is the "
               "part investors underestimate. A shallow but permanent drawdown can be worse than a deep, quick one.",
               "Volatility is symmetric and abstract; this chart is the asymmetric, concrete version of the same "
               "risk, and a better guide to whether a position is holdable.",
               data=dd.to_frame("Drawdown %"))
    with r2:
        figh = go.Figure(go.Histogram(x=ret * 100, nbinsx=60, marker_color=T["accent_soft"], opacity=.85))
        figh.add_vline(x=(risk.get("var_95") or 0) * 100, line_dash="dash", line_color=T["danger"],
                       annotation_text="VaR 95%", annotation_position="top")
        figh.update_xaxes(title_text="Daily return (%)")
        figh.update_yaxes(title_text="Number of days")
        style_fig(figh, height=310, legend="off")
        figure(figh, "Distribution of daily returns",
               "How often each size of daily move actually occurred over the past two years.",
               "Check the **tails**, not the middle. A normal distribution would thin out quickly at the edges; "
               "real return distributions have fatter tails, meaning extreme days happen more often than the "
               "volatility figure implies. The dashed line marks the 95% VaR threshold.",
               "Every model below, including the simulation, assumes something about this shape. Seeing the "
               "real one is a useful check on how much to trust them.")

    section("Forward simulation",
            "One year of possible paths, generated from this stock's own drift and volatility.")
    s1, s2, s3 = st.columns(3)
    with s1:
        sims = st.select_slider("Simulated paths", [200, 500, 1000, 5000, 10000], value=1000)
    with s2:
        horizon = st.select_slider("Horizon (trading days)", [63, 126, 252, 504], value=252,
                                   format_func=lambda d: {63: "3 months", 126: "6 months",
                                                          252: "1 year", 504: "2 years"}[d])
    with s3:
        seed = st.number_input("Random seed", value=42, step=1,
                               help="Fixing the seed makes the simulation reproducible between runs.")

    @st.cache_data(ttl=1800, show_spinner=False)
    def simulate(last_price: float, mu: float, sigma: float, days: int, paths: int, seed: int):
        """Vectorised geometric random walk. The previous implementation used a
        nested Python loop over paths and days; this generates the whole matrix
        at once and is roughly two orders of magnitude faster."""
        rng = np.random.default_rng(int(seed))
        shocks = rng.normal(mu, sigma, size=(days, paths))
        return float(last_price) * np.cumprod(1.0 + shocks, axis=0)

    last_price = float(close.iloc[-1]) * fx
    paths = simulate(last_price, float(ret.mean()), float(ret.std()), int(horizon), int(sims), int(seed))
    finals = paths[-1]
    p5, p25, p50, p75, p95 = (np.percentile(paths, q, axis=1) for q in (5, 25, 50, 75, 95))
    days_idx = np.arange(1, horizon + 1)

    figmc = go.Figure()
    for upper, lower, opacity, label in ((p95, p5, 0.13, "5th–95th percentile"),
                                         (p75, p25, 0.25, "25th–75th percentile")):
        figmc.add_trace(go.Scatter(x=np.concatenate([days_idx, days_idx[::-1]]),
                                   y=np.concatenate([upper, lower[::-1]]),
                                   fill="toself", fillcolor=f"rgba(99,102,241,{opacity})",
                                   line=dict(width=0), name=label, hoverinfo="skip"))
    figmc.add_trace(go.Scatter(x=days_idx, y=p50, name="Median path",
                               line=dict(color=T["accent"], width=2.5)))
    figmc.add_hline(y=last_price, line_dash="dot", line_color=T["faint"],
                    annotation_text="Today", annotation_position="right")
    figmc.update_xaxes(title_text="Trading days ahead")
    figmc.update_yaxes(title_text=f"Price ({sym})")
    style_fig(figmc, height=380)

    prob_loss = float((finals < last_price).mean())
    prob_20 = float((finals > last_price * 1.2).mean())
    figure(figmc, f"Simulated price distribution over {horizon} trading days",
           f"{sims:,} random paths built from this stock's own average daily return and volatility, summarised "
           "as a median line with the middle 50% and middle 90% of outcomes shaded.",
           "Read the **width**, not the line. The median path is the least interesting part; the spread between "
           "the shaded bands is the honest statement of how little a one-year point forecast is worth.",
           "The simulation assumes returns are normally distributed and that the next year resembles the last "
           "two. Both assumptions break precisely when it matters — around earnings shocks, rate moves and "
           "credit events — so treat the bands as a floor on uncertainty, not a ceiling.",
           data=pd.DataFrame({"Median": p50, "P5": p5, "P95": p95}, index=days_idx))

    kpi_grid([
        {"label": "Median outcome", "value": Fmt.price(np.median(finals), sym),
         "sub": Fmt.as_pct(np.median(finals) / last_price - 1, signed=True) + " from today",
         "tone": "good" if np.median(finals) > last_price else "bad"},
        {"label": "5th percentile", "value": Fmt.price(np.percentile(finals, 5), sym),
         "sub": "Only 1 path in 20 ended below this", "tone": "flat"},
        {"label": "95th percentile", "value": Fmt.price(np.percentile(finals, 95), sym),
         "sub": "Only 1 path in 20 ended above this", "tone": "flat"},
        {"label": "Chance of a loss", "value": Fmt.as_pct(prob_loss),
         "sub": "Share of paths finishing below today's price",
         "tone": tone_for(prob_loss * 100, 40, 55, higher_better=False)},
        {"label": "Chance of +20%", "value": Fmt.as_pct(prob_20),
         "sub": "Share of paths finishing at least 20% higher", "tone": "flat"},
    ], min_width=185)

    note(f"""
Over the simulated horizon the median path ends at **{Fmt.price(np.median(finals), sym)}**, with a 90% band
running from {Fmt.price(np.percentile(finals, 5), sym)} to {Fmt.price(np.percentile(finals, 95), sym)}.
- **Beta of {Fmt.ratio(beta)}** says the stock has historically moved
{'less' if _isnum(beta) and beta < 1 else 'more'} than the market. That is a statement about the past, and beta
is unstable — it changes with the estimation window.
- **Maximum drawdown of {Fmt.as_pct(risk.get('max_dd'))}** is the concrete version of that risk: it is what an
investor holding through the last two years actually had to sit through.
- **Position sizing, not prediction,** is what this section is for. If a {Fmt.as_pct(risk.get('max_dd'))} fall
in this position would force you to sell, the position is too large regardless of how good the valuation looks.
""", tone="warn" if prob_loss > 0.5 else "neu")


# ==============================================================================
elif module == "8. Price & Capital Dynamics":
    section("Price, capital and context",
            "What actually happened to the shares over the selected window, and what was in the news while "
            "it happened.")

    hist = co.history(period, interval)
    if hist.empty:
        empty_state("No price history for this period.")
        st.stop()

    shares = co.shares or 1
    px_series = hist["Close"] * fx
    mcap_series = px_series * shares

    roll = px_series.pct_change(20)
    best_idx = roll.idxmax() if roll.notna().any() else None
    worst_idx = roll.idxmin() if roll.notna().any() else None
    best_val = float(roll.loc[best_idx]) if best_idx is not None else None
    worst_val = float(roll.loc[worst_idx]) if worst_idx is not None else None

    company_news, sector_news, sector_etf = load_news(co.ticker, info.get("sector"), 6)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=mcap_series.index, y=mcap_series, name="Market capitalisation",
                             line=dict(color=T["faint"], width=1.6, dash="dot")), secondary_y=True)
    fig.add_trace(go.Scatter(x=px_series.index, y=px_series, name="Share price",
                             line=dict(color=T["accent"], width=2.2)), secondary_y=False)
    if best_idx is not None:
        fig.add_annotation(x=best_idx, y=float(px_series.loc[best_idx]), text="Strongest 20-day run",
                           showarrow=True, arrowhead=2, ax=0, ay=-38,
                           bgcolor=T["success"], font=dict(color="#fff", size=11), bordercolor=T["success"])
    if worst_idx is not None:
        fig.add_annotation(x=worst_idx, y=float(px_series.loc[worst_idx]), text="Sharpest 20-day fall",
                           showarrow=True, arrowhead=2, ax=0, ay=38,
                           bgcolor=T["danger"], font=dict(color="#fff", size=11), bordercolor=T["danger"])

    lo_d = px_series.index.min()
    hi_d = px_series.index.max()
    lo_date = lo_d.tz_localize(None).date() if getattr(lo_d, "tzinfo", None) else lo_d.date()
    hi_date = hi_d.tz_localize(None).date() if getattr(hi_d, "tzinfo", None) else hi_d.date()
    marked = 0
    for item in company_news:
        if item["time"] and lo_date <= item["time"].date() <= hi_date:
            fig.add_vline(x=item["time"].strftime("%Y-%m-%d"), line_width=1.2, line_dash="dot",
                          line_color=T["warning"], opacity=.7)
            marked += 1
    fig.update_yaxes(title_text=f"Price ({sym})", secondary_y=False)
    fig.update_yaxes(title_text=f"Market cap ({sym})", secondary_y=True, showgrid=False)
    fig.update_layout(hovermode="x unified", xaxis=dict(rangeslider=dict(visible=True)))
    style_fig(fig, height=430)
    selection = st.plotly_chart(fig, on_select="rerun", selection_mode="points",
                                key="pxchart", **FILL_CHART)
    st.markdown(
        f"<div class='figcap'><div class='figcap-line'><span class='figcap-num'>Figure {REPORT.next_figure()}</span>"
        f"<span class='figcap-title'>Price against market capitalisation.</span> "
        f"Share price (solid, left axis) and market capitalisation (dotted, right axis) over {period_label}"
        f"{f', with {marked} recent headlines marked as vertical lines' if marked else ''}. "
        f"Click any point to rebuild the enterprise value bridge below at that date.</div></div>",
        unsafe_allow_html=True)
    with st.expander("How to read this figure", expanded=st.session_state.explain_open):
        st.markdown("""
<div class='exp-block'>
<div class='exp-row'><div class='exp-key'>How to read</div><div>The two lines normally move together, because
market capitalisation is simply price multiplied by the share count. <b>Where they diverge, the share count
changed</b> — a buyback pulls market cap below price, an issuance or stock-funded acquisition pushes it above.
That divergence is often the most informative thing on the chart.</div></div>
<div class='exp-row'><div class='exp-key'>Why it matters</div><div>Per-share performance and company-level
performance are different questions. A company can grow while its shares stagnate if the growth was bought
with equity.</div></div>
</div>""", unsafe_allow_html=True)

    note(f"""
Over {period_label.lower()}, the strongest 20-day run was
**{Fmt.as_pct(best_val, signed=True)}** around {Fmt.date(best_idx)}, and the sharpest 20-day fall was
**{Fmt.as_pct(worst_val, signed=True)}** around {Fmt.date(worst_idx)}.
- Clusters of large moves rarely arrive at random. They tend to sit on earnings dates, guidance changes, and
macro events — which is what the marked headlines below are there to help you check.
- Sharp falls with no company-specific news usually reflect sector rotation or an index-level move rather than
anything about this business.
- Net, the largest rally {'outpaced' if (best_val or 0) > abs(worst_val or 0) else 'was outpaced by'} the
largest drawdown over this window.
""", tone="pos" if (best_val or 0) > abs(worst_val or 0) else "warn")

    section("News context", "Recent company and sector headlines, most recent first.")
    n1, n2 = st.columns(2)
    with n1:
        st.markdown(f"<div class='eyebrow'>{co.ticker} headlines</div>", unsafe_allow_html=True)
        if company_news:
            for it in company_news:
                title_html = (f"<a href='{it['link']}' target='_blank'>{it['title']}</a>"
                              if it["link"] else it["title"])
                st.markdown(f"<div class='news'><div class='news-t'>{title_html}</div>"
                            f"<div class='news-m'>{it['publisher']} · {time_ago(it['time'])}</div></div>",
                            unsafe_allow_html=True)
        else:
            st.caption("No recent company headlines returned.")
    with n2:
        st.markdown(f"<div class='eyebrow'>{info.get('sector', 'Sector')} headlines"
                    f"{f' · via {sector_etf}' if sector_etf else ''}</div>", unsafe_allow_html=True)
        if sector_news:
            for it in sector_news:
                title_html = (f"<a href='{it['link']}' target='_blank'>{it['title']}</a>"
                              if it["link"] else it["title"])
                st.markdown(f"<div class='news'><div class='news-t'>{title_html}</div>"
                            f"<div class='news-m'>{it['publisher']} · {time_ago(it['time'])}</div></div>",
                            unsafe_allow_html=True)
        else:
            st.caption("No sector headlines available for this sector.")

    section("Enterprise value at a point in time",
            "Market capitalisation at the selected date, adjusted for the latest reported debt and cash.")
    sel_mcap = (co.market_cap or 0) * fx
    sel_label = "latest"
    if selection and selection.get("selection", {}).get("points"):
        try:
            ts = pd.to_datetime(selection["selection"]["points"][0]["x"]).tz_localize(None)
            idx = mcap_series.index.get_indexer([ts], method="nearest")[0]
            sel_mcap = float(mcap_series.iloc[idx])
            sel_label = pd.Timestamp(mcap_series.index[idx]).strftime("%d %b %Y")
        except Exception as exc:
            note_error("EV snapshot", exc)
    sel_debt = (info.get("totalDebt") or 0) * fx
    sel_cash = (info.get("totalCash") or 0) * fx
    figev = go.Figure(go.Waterfall(
        orientation="v", measure=["absolute", "relative", "relative", "total"],
        x=["Market cap", "Plus debt", "Less cash", "Enterprise value"],
        y=[sel_mcap, sel_debt, -sel_cash, 0],
        connector={"line": {"color": T["border"]}},
        increasing={"marker": {"color": T["danger"]}},
        decreasing={"marker": {"color": T["success"]}},
        totals={"marker": {"color": T["accent"]}}))
    figev.update_yaxes(title_text=sym)
    style_fig(figev, height=320, legend="off")
    figure(figev, f"Enterprise value bridge ({sel_label})",
           "Market capitalisation at the selected point, plus debt, less cash.",
           "Only the first bar moves with your click. Debt and cash are the **latest reported** balance-sheet "
           "figures, because historical quarter-by-quarter balance sheets are not available from this data "
           "source — so a bridge dated far in the past mixes an old market cap with today's capital structure.",
           "Useful for seeing how much of a change in the cost of the whole business came from the share price "
           "versus from the balance sheet.")


# ==============================================================================
elif module == "9. Market Leaders":
    section("Market leaders",
            "Cross-company ranking by size and revenue. Pools are a starting universe, not an exhaustive index.")

    MARKET_POOLS = {
        "United States / global": [
            "AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META", "TSLA", "BRK-B", "LLY", "TSM",
            "AVGO", "V", "JPM", "WMT", "XOM", "UNH", "MA", "PG", "JNJ", "COST",
            "HD", "MRK", "ORCL", "ABBV", "CVX", "BAC", "KO", "PEP", "CRM", "AMD",
            "NFLX", "ADBE", "TMO", "ABT", "DIS", "MCD", "CSCO", "PFE", "INTC", "IBM",
            "GE", "CAT", "NKE", "TXN", "QCOM", "HON", "LOW", "SBUX", "GS", "MS"],
        "Germany (DAX)": [
            "SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "VOW3.DE", "BMW.DE", "BAS.DE", "ADS.DE",
            "MBG.DE", "IFX.DE", "AIR.DE", "MUV2.DE", "DB1.DE", "DHL.DE", "BEI.DE",
            "RWE.DE", "EOAN.DE", "BAYN.DE", "DBK.DE", "CBK.DE", "HEI.DE", "FRE.DE", "MRK.DE",
            "CON.DE", "PUM.DE", "ZAL.DE", "1COV.DE", "SY1.DE", "QIA.DE", "RHM.DE"],
        "United Kingdom (FTSE)": [
            "SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "BP.L", "RIO.L", "GSK.L", "DGE.L", "BATS.L",
            "REL.L", "GLEN.L", "LSEG.L", "CNA.L", "NG.L", "LLOY.L",
            "VOD.L", "TSCO.L", "BARC.L", "PRU.L", "STAN.L", "IMB.L", "RKT.L", "CPG.L",
            "AAL.L", "NWG.L", "SGE.L", "SSE.L", "NXT.L", "LGEN.L", "AV.L"],
        "Japan (Nikkei)": [
            "7203.T", "6758.T", "9432.T", "6861.T", "8035.T", "9984.T", "8058.T", "4063.T", "9983.T",
            "7974.T", "8306.T", "6098.T", "4568.T", "6501.T", "6902.T",
            "6367.T", "4661.T", "9433.T", "8001.T", "8031.T", "6752.T", "7267.T", "4502.T",
            "9020.T", "8766.T", "6981.T", "6503.T", "5108.T", "4901.T", "8802.T"],
        "Vietnam (HOSE)": [
            "VCB.VN", "VHM.VN", "VIC.VN", "GAS.VN", "VNM.VN", "HPG.VN", "BID.VN", "MSN.VN", "SAB.VN",
            "CTG.VN", "TCB.VN", "VPB.VN", "MBB.VN", "FPT.VN", "MWG.VN",
            "PLX.VN", "POW.VN", "GVR.VN", "STB.VN", "SSI.VN", "VRE.VN", "PNJ.VN", "REE.VN",
            "KDH.VN", "ACB.VN"],
    }

    c1, c2, c3 = st.columns([1.2, 1.2, 1])
    with c1:
        mode = segmented("Universe", ["By market", "By sector", "Custom list"], key="leader_mode")
    with c2:
        top_n = st.slider("Companies to rank", 5, 40, 12, 1,
                          help="Each company needs one profile lookup; these run in parallel, but a larger "
                               "list still takes longer on a cold cache.")
    with c3:
        as_of = st.date_input("As at", value=datetime.now().date(),
                              min_value=(datetime.now() - timedelta(days=365 * 20)).date(),
                              max_value=datetime.now().date())

    tickers = []
    if mode == "By market":
        chosen = st.selectbox("Market", ["All tracked markets"] + list(MARKET_POOLS.keys()))
        tickers = ([t for lst in MARKET_POOLS.values() for t in lst] if chosen == "All tracked markets"
                   else MARKET_POOLS[chosen])
        tickers = list(dict.fromkeys(tickers))
        st.caption(f"Scanning {len(tickers)} companies. Market capitalisation is computed from the price on "
                   f"your chosen date multiplied by the current share count.")
    elif mode == "By sector":
        sector_choice = st.selectbox("Sector", list(SECTOR_ETF_MAP.keys()))
        etf = SECTOR_ETF_MAP[sector_choice]
        with st.spinner(f"Pulling current {etf} holdings…"):
            tickers = sector_top_holdings(etf, max_n=max(top_n, 15))
        st.caption(f"Current top holdings of {etf}, the {sector_choice} sector ETF, pulled live. Holdings are "
                   "predominantly US-listed, so use the market universe for leaders elsewhere.")
    else:
        raw = st.text_input("Symbols", value="AAPL, MSFT, NVDA, GOOG, AMZN, META, TSLA, BRK-B, LLY, TSM")
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]

    if not tickers:
        empty_state("No companies in the selected universe.", "Try another market, sector or custom list.")
        st.stop()

    with st.spinner(f"Loading {len(tickers)} companies in parallel…"):
        board = load_leaderboard(tuple(tickers), target_currency, str(as_of))

    if board.empty:
        empty_state("No data came back for this universe.", "The date may fall on a market holiday.")
        st.stop()

    top = board.head(top_n).copy()
    lb1, lb2 = st.columns([1.45, 1])
    with lb1:
        figl = make_subplots(specs=[[{"secondary_y": True}]])
        figl.add_trace(go.Bar(x=top["Ticker"], y=top["Market Cap"], name="Market capitalisation",
                              marker_color=T["accent_soft"], opacity=.85,
                              hovertemplate="%{x}<br>" + sym + "%{y:,.0f}<extra></extra>"), secondary_y=False)
        figl.add_trace(go.Scatter(x=top["Ticker"], y=top["Revenue"], name="Revenue",
                                  mode="lines+markers", line=dict(color=T["warning"], width=2.5),
                                  hovertemplate="%{x}<br>" + sym + "%{y:,.0f}<extra></extra>"), secondary_y=True)
        figl.update_yaxes(title_text=f"Market cap ({sym})", secondary_y=False)
        figl.update_yaxes(title_text=f"Revenue ({sym})", secondary_y=True, showgrid=False)
        style_fig(figl, height=400)
        figure(figl, f"Top {len(top)} by market capitalisation, with revenue alongside",
               f"Ranked by market capitalisation at {as_of:%d %b %Y}, with each company's reported revenue on "
               "the second axis.",
               "The gap between the two series is the market's verdict on quality. Companies whose bar towers "
               "over their revenue point are being paid for margin, growth or durability; those where revenue "
               "leads are typically lower-margin or more cyclical businesses.",
               "It is the fastest way to see which businesses the market values per unit of sales, and which it "
               "does not.",
               data=top[["Ticker", "Market Cap", "Revenue"]].set_index("Ticker"))
    with lb2:
        figt = px.treemap(top, path=["Market", "Ticker"], values="Market Cap",
                          color="Net Margin (%)", color_continuous_scale="RdYlGn",
                          color_continuous_midpoint=10)
        figt.update_traces(textinfo="label+percent root")
        style_fig(figt, height=400, legend="off")
        figure(figt, "Relative size and profitability",
               "Rectangle area is market capitalisation; colour is net margin, green for higher.",
               "Look for **large but red** rectangles: big companies earning thin margins, where scale is doing "
               "the work rather than pricing power. Small green ones are the reverse.",
               "Size and quality are different things, and a ranking by size alone hides that.")

    hist_tickers = tuple(top["Ticker"].tolist())
    with st.spinner("Loading three years of history…"):
        closes = load_batch_close(hist_tickers, (datetime.now() - timedelta(days=365 * 3)).date(),
                                  datetime.now().date())
    if not closes.empty:
        figtr = go.Figure()
        for _, row in top.iterrows():
            t = row["Ticker"]
            if t not in closes.columns:
                continue
            series = closes[t].dropna() * row["_shares"] * row["_fx"]
            if series.empty:
                continue
            figtr.add_trace(go.Scatter(x=series.index, y=series, name=t, mode="lines",
                                       hovertemplate="%{x|%b %Y}<br>" + sym + "%{y:,.0f}<extra>" + t + "</extra>"))
        figtr.update_yaxes(title_text=f"Market cap ({sym})")
        figtr.update_layout(hovermode="x unified",
                            xaxis=dict(rangeselector=dict(buttons=[
                                dict(count=6, label="6m", step="month", stepmode="backward"),
                                dict(count=1, label="1y", step="year", stepmode="backward"),
                                dict(count=3, label="3y", step="year", stepmode="backward"),
                                dict(step="all", label="All")]),
                                rangeslider=dict(visible=False), type="date"))
        style_fig(figtr, height=400)
        figure(figtr, "Market capitalisation trajectories, three years",
               "Each line is one leader's market capitalisation over time, using today's share count applied to "
               "historical prices.",
               "Watch the **crossings**: where one line overtakes another is where leadership actually changed "
               "hands. Lines moving in parallel usually mean a sector-wide re-rating rather than "
               "company-specific news.",
               "Rankings are a snapshot; trajectories show who is gaining and who is giving ground.")

    display = top[["Ticker", "Name", "Market", "Industry", "Market Cap", "Revenue", "Net Margin (%)", "Price"]].copy()
    display.index = np.arange(1, len(display) + 1)
    display.index.name = "Rank"
    table(display, "Ranking detail",
          f"All figures converted to {target_currency}; revenue is the latest reported annual figure.",
          formats={"Market Cap": lambda v: Fmt.money(v, sym), "Revenue": lambda v: Fmt.money(v, sym),
                   "Price": lambda v: Fmt.price(v, sym), "Net Margin (%)": "{:,.1f}%"})


# ==============================================================================
# 9. EXPORT, PROVENANCE & FOOTER  (shared by every data module)
# ==============================================================================

st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
x1, x2 = st.columns([1, 1])

with x1:
    with st.expander("Export this view as a report", expanded=False):
        st.caption("Produces a standalone HTML file containing every figure, caption and note on this page, "
                   "with the charts still interactive. Preparing it serialises the charts, so it is a "
                   "deliberate step rather than something done on every render.")
        if not st.session_state.get("_export"):
            if st.button("Prepare report", type="primary", **FILL_BTN):
                st.session_state["_export"] = True
                st.rerun()
        else:
            meta = {
                "title": f"{co.name} ({co.ticker}) — {module.split('. ', 1)[1]}",
                "subtitle": (f"{co.sector} · {co.industry} · {market_label(co.ticker)} &nbsp;|&nbsp; "
                             f"Prepared {datetime.now():%d %B %Y %H:%M} &nbsp;|&nbsp; "
                             f"Figures in {target_currency}"
                             + (f" (converted from {native_currency} at {fx:,.4f})"
                                if native_currency != target_currency else "")),
                "footer": (f"Generated by {APP_NAME}. Source: {DATA_SOURCE}. "
                           "Educational research only — not investment advice. "
                           "Figures should be verified against primary filings before use."),
            }
            html = REPORT.to_html(meta)
            st.download_button("Download the HTML report", html.encode("utf-8"),
                               file_name=f"{co.ticker}_{module.split('.')[0]}_report.html",
                               mime="text/html", type="primary", **FILL_DL)
            if st.button("Clear", **FILL_BTN):
                st.session_state["_export"] = False
                st.rerun()

with x2:
    with st.expander("Data provenance", expanded=False):
        rows = [
            ("Source", DATA_SOURCE),
            ("Symbol resolved", f"{co.ticker} · {market_label(co.ticker)}"),
            ("Reporting currency", f"{native_currency} → {target_currency}"
                                   + (f" at {fx:,.4f}" if native_currency != target_currency else "")),
            ("Statement basis", basis),
            ("Latest annual period", Fmt.date(co.inc.index[-1]) if not co.inc.empty else Fmt.NA),
            # Only read the quarterly statements when the current basis already
            # needed them - otherwise this panel alone would trigger three extra
            # network round trips on every annual-basis view.
            ("Latest quarter", (Fmt.date(co.quarterly["inc"].index[-1])
                                if basis != "Annual" and not co.quarterly["inc"].empty
                                else "not loaded on the annual basis")),
            ("Cache windows", "Quotes and news 15 min · statements 60 min · FX 60 min"),
            ("Rendered", f"{datetime.now():%d %b %Y %H:%M}"),
        ]
        st.markdown("<div class='card'>" + "".join(
            f"<div style='display:grid;grid-template-columns:170px 1fr;gap:10px;font-size:12.5px;"
            f"padding:4px 0'><span style='color:{T['muted']}'>{k}</span><span>{v}</span></div>"
            for k, v in rows) + "</div>", unsafe_allow_html=True)
        errs = st.session_state.get(_LOAD_ERRORS_KEY) or []
        if errs:
            st.caption("Non-fatal issues during loading:")
            for e in errs:
                st.caption(f"· {e}")

st.markdown(
    f"<div class='foot'>{APP_NAME} · built by Minh Phu Dinh · data from {DATA_SOURCE}<br>"
    f"Figures are as reported by the data provider and may contain gaps or restatements. "
    f"Nothing here is investment advice; it is an educational research tool.</div>",
    unsafe_allow_html=True)
