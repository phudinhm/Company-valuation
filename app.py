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
    # "auto" keeps the sidebar open on a desktop but collapses it on a phone,
    # where "expanded" would land the reader on the controls rather than on the
    # report they asked for.
    initial_sidebar_state="auto",
)

# A single source of truth for colour: the same dictionary drives the CSS
# variables AND the Plotly figure styling, so charts can never drift out of
# sync with the surrounding page the way hardcoded hex values did before.
THEMES = {
    "Light": {
        "bg": "#f4f5f9", "bg_grad": "radial-gradient(circle at 12% -10%, #ffffff 0%, #f4f5f9 60%)",
        "surface": "#ffffff", "surface_alt": "#f8f9fc", "surface_sunk": "#eef0f6",
        "text": "#14172a", "muted": "#515c73", "faint": "#6f7a90",
        "border": "#e4e7f0", "accent": "#3d3ab0", "accent_soft": "#6366f1",
        "success": "#0f8f5c", "danger": "#cf2c1e", "warning": "#b8760a", "info": "#2563eb",
        "pos_bg": "#ecfdf3", "pos_text": "#0a5f3d",
        "neg_bg": "#fef3f2", "neg_text": "#8f2318",
        "warn_bg": "#fffaeb", "warn_text": "#8a5a05",
        "neu_bg": "#f0f2fc", "neu_text": "#2f2a86",
        "grid": "rgba(20,23,42,0.08)", "shadow": "rgba(16,24,40,0.08)",
        "ring": "rgba(61,58,176,0.20)",
    },
    "Dark": {
        "bg": "#080b13", "bg_grad": "radial-gradient(circle at 12% -10%, #151c30 0%, #080b13 60%)",
        "surface": "#111726", "surface_alt": "#161d2e", "surface_sunk": "#0d121e",
        "text": "#eef1f8", "muted": "#a3b0c6", "faint": "#8590a6",
        "border": "#222a3d", "accent": "#8b93f8", "accent_soft": "#a5adfb",
        "success": "#34d399", "danger": "#f87171", "warning": "#fbbf24", "info": "#60a5fa",
        "pos_bg": "#0d2a22", "pos_text": "#7ee2b8",
        "neg_bg": "#2a1416", "neg_text": "#fca5a5",
        "warn_bg": "#2b2110", "warn_text": "#fcd34d",
        "neu_bg": "#141b2e", "neu_text": "#c3caff",
        "grid": "rgba(238,241,248,0.09)", "shadow": "rgba(0,0,0,0.45)",
        "ring": "rgba(139,147,248,0.26)",
    },
    "Sepia": {
        "bg": "#f4eee0", "bg_grad": "radial-gradient(circle at 12% -10%, #fbf6ea 0%, #f4eee0 60%)",
        "surface": "#fffaf0", "surface_alt": "#faf3e4", "surface_sunk": "#efe6d3",
        "text": "#382e21", "muted": "#6b5c45", "faint": "#8b7c63",
        "border": "#e2d4ba", "accent": "#8f5730", "accent_soft": "#b57a4a",
        "success": "#3d8a5c", "danger": "#b0432d", "warning": "#b4801f", "info": "#3f6f9c",
        "pos_bg": "#edf3e5", "pos_text": "#2c6742",
        "neg_bg": "#f8e8e2", "neg_text": "#8b3520",
        "warn_bg": "#f7eeda", "warn_text": "#7d5a12",
        "neu_bg": "#f1e8d9", "neu_text": "#674325",
        "grid": "rgba(56,46,33,0.10)", "shadow": "rgba(80,60,35,0.12)",
        "ring": "rgba(143,87,48,0.20)",
    },
}

DEFAULTS = {
    "theme": "Light",
    "module": "01. Executive Dashboard",
    "market_select": "United States",
    "ticker_symbol_input": "AAPL",
    "explain_open": False,
    "_export": False,
}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)

T = THEMES[st.session_state.theme]


def _tokens_css(t: dict) -> str:
    pairs = {
        "--bg": t["bg"], "--bg-grad": t["bg_grad"], "--surface": t["surface"],
        "--surface-alt": t["surface_alt"], "--surface-sunk": t["surface_sunk"],
        "--text": t["text"], "--muted": t["muted"], "--faint": t["faint"],
        "--border": t["border"], "--accent": t["accent"], "--accent-soft": t["accent_soft"],
        "--success": t["success"], "--danger": t["danger"], "--warning": t["warning"],
        "--info": t["info"], "--pos-bg": t["pos_bg"], "--pos-text": t["pos_text"],
        "--neg-bg": t["neg_bg"], "--neg-text": t["neg_text"], "--warn-bg": t["warn_bg"],
        "--warn-text": t["warn_text"], "--neu-bg": t["neu_bg"], "--neu-text": t["neu_text"],
        "--shadow": t["shadow"], "--ring": t["ring"],
    }
    return ":root{" + "".join(f"{k}:{v};" for k, v in pairs.items()) + "}"


# The stylesheet is a plain string (no f-string) so CSS braces stay readable;
# the theme block is spliced in at a marker instead.
_STYLESHEET = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

/*TOKENS*/

:root{
  --card-pad: 20px 22px;
  --kpi-pad: 17px 19px;
  --gap: 14px;
  --fs-body: 15px;
  --fs-kpi: 27px;
  --fs-note: 14.5px;
  --fs-cap: 13.5px;
  --sec-top: 34px;
}

html, body, [class*="css"] { font-family: 'Inter', -apple-system, "Segoe UI", sans-serif; color: var(--text); }
[data-testid="stAppViewContainer"] { background: var(--bg-grad); }
[data-testid="stAppViewContainer"] p, [data-testid="stAppViewContainer"] li,
[data-testid="stAppViewContainer"] label, [data-testid="stMarkdownContainer"] p { font-size: var(--fs-body); }
.block-container { padding-top: 2.2rem; padding-bottom: 4.5rem; max-width: 1560px; }
h1,h2,h3,h4,h5,h6 { font-family: 'Inter', sans-serif; letter-spacing: -0.015em; color: var(--text); }
a { color: var(--accent); }
hr { border-color: var(--border); }
[data-testid="stCaptionContainer"] p, .stCaption p { font-size: 13px !important; color: var(--muted) !important; }
[data-testid="stMarkdownContainer"] { color: var(--text); }

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--border); }
[data-testid="stSidebar"] * { color: var(--text); }
[data-testid="stSidebar"] label { font-size: 13.5px !important; font-weight: 500; }
.side-brand { font-size: 18px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; }
.side-sub { font-size: 11.5px; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; margin-top: 4px; }
.side-group { font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
              color: var(--faint); margin: 18px 0 2px; }

/* ---------- Buttons & inputs ---------- */
.stButton > button[kind="primary"] { background: linear-gradient(135deg, var(--accent), var(--accent-soft));
    border: none; font-weight: 600; }
.stButton > button { border-radius: 8px; font-size: 14px; }
/* Streamlit's own base theme is light, and this app paints its themes on top in
   CSS. Form controls have to be re-skinned explicitly or they stay white in the
   Dark and Sepia themes. */
/* Streamlit wraps every control in a "…RootElement" that paints the white
   background; skinning only the inner input leaves that showing through. */
[data-testid$="RootElement"], [data-testid$="Container"] > div[data-baseweb="input"],
.stSelectbox div[role="group"], .stMultiSelect div[role="group"],
.stDateInput div[role="group"], .stNumberInput div[role="group"],
div[data-baseweb="select"] > div, div[data-baseweb="input"], div[data-baseweb="base-input"],
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea {
    background-color: var(--surface-alt) !important;
    color: var(--text) !important;
    border-color: var(--border) !important;
    border-radius: 8px; font-size: 14px;
}
div[data-baseweb="select"] svg { fill: var(--muted); }
div[data-baseweb="popover"] div[role="listbox"], div[data-baseweb="menu"], ul[role="listbox"] {
    background-color: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border);
}
div[data-baseweb="menu"] li, ul[role="listbox"] li { color: var(--text) !important; }
div[data-baseweb="menu"] li:hover, ul[role="listbox"] li:hover {
    background-color: var(--surface-alt) !important;
}
[data-testid="stSliderTickBar"], [data-testid="stTickBar"] { color: var(--muted); }

/* ---------- Section headers ---------- */
.section { display: flex; align-items: baseline; gap: 12px; margin: var(--sec-top) 0 5px; }
.section-num { font-family: 'IBM Plex Mono', monospace; font-size: 13px; font-weight: 600;
    color: var(--accent); background: var(--neu-bg); border-radius: 5px; padding: 3px 8px; letter-spacing: .04em; }
.section-title { color: var(--text);  font-size: 19.5px; font-weight: 700; letter-spacing: -0.015em; }
.section-rule { height: 1px; background: var(--border); flex: 1; margin-bottom: 4px; }
.section-sub { font-size: 14px; color: var(--muted); margin: 0 0 14px; line-height: 1.6; max-width: 105ch; }
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--faint); }

/* ---------- Cards ---------- */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: var(--card-pad); box-shadow: 0 1px 2px var(--shadow); }
.card + .card { margin-top: var(--gap); }
.card-title { color: var(--text);  font-size: 15px; font-weight: 700; margin: 0 0 7px; }
.card-body { font-size: 14.5px; line-height: 1.65; color: var(--text); }
.card-meta { font-size: 13px; color: var(--muted); }

/* ---------- KPI grid ---------- */
.kpi-grid { display: grid; gap: var(--gap); margin-bottom: 8px; }
.kpi { position: relative; background: var(--surface); border: 1px solid var(--border);
    border-radius: 11px; padding: var(--kpi-pad); overflow: hidden;
    transition: border-color .16s ease, transform .16s ease; }
.kpi:hover { border-color: var(--accent); transform: translateY(-1px); }
.kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--border); }
.kpi.good::before { background: var(--success); }
.kpi.bad::before { background: var(--danger); }
.kpi.warn::before { background: var(--warning); }
.kpi.flat::before { background: var(--accent); }
.kpi-label { font-size: 11.5px; font-weight: 600; letter-spacing: .07em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.kpi-value { color: var(--text);  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
    font-size: var(--fs-kpi); font-weight: 600; line-height: 1.15; letter-spacing: -0.02em; }
.kpi-sub { font-size: 12.5px; color: var(--muted); margin-top: 6px; line-height: 1.45; }
.kpi-delta { font-size: 13px; font-weight: 600; margin-top: 5px; font-variant-numeric: tabular-nums; }
.kpi-delta.pos { color: var(--success); } .kpi-delta.neg { color: var(--danger); }
.help-dot { display: inline-block; width: 14px; height: 14px; line-height: 14px; text-align: center;
    border-radius: 50%; background: var(--surface-sunk); color: var(--faint); font-size: 10px;
    font-weight: 700; cursor: help; }

/* ---------- Notes / interpretation ---------- */
.note { border: 1px solid var(--border); border-left-width: 3px; border-radius: 9px;
    padding: 15px 17px; margin: 12px 0 4px; font-size: var(--fs-note); line-height: 1.68; }
.note-title { font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
    margin-bottom: 7px; opacity: .85; }
.note p { margin: 0 0 8px; } .note ul { margin: 6px 0 7px 19px; padding: 0; } .note li { margin-bottom: 6px; }
.note.pos { background: var(--pos-bg); color: var(--pos-text); border-left-color: var(--success); }
.note.neg { background: var(--neg-bg); color: var(--neg-text); border-left-color: var(--danger); }
.note.warn { background: var(--warn-bg); color: var(--warn-text); border-left-color: var(--warning); }
.note.neu { background: var(--neu-bg); color: var(--neu-text); border-left-color: var(--accent); }

/* ---------- Figure captions ---------- */
.figcap { border-top: 1px solid var(--border); padding-top: 8px; margin: -4px 0 2px; }
.figcap-line { font-size: var(--fs-cap); color: var(--muted); line-height: 1.6; }
.figcap-num { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; font-weight: 600;
    color: var(--accent); margin-right: 7px; }
.figcap-title { color: var(--text); font-weight: 600; }
.exp-block { font-size: 13.8px; line-height: 1.68; color: var(--text); }
.exp-row { display: grid; grid-template-columns: 104px 1fr; gap: 12px; margin-bottom: 9px; }
.exp-key { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--faint); padding-top: 3px; }

/* ---------- Header ---------- */
.hdr-name { color: var(--text);  font-size: 30px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.15; margin: 0; }
.hdr-meta { font-size: 13.5px; color: var(--muted); margin-top: 7px; }
.hdr-chip { display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 5px;
    background: var(--surface-sunk); color: var(--muted); margin: 0 6px 4px 0; }
.px-box { text-align: right; background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px 18px; }
.px-value { font-family: 'IBM Plex Mono', monospace; font-size: 32px; font-weight: 700; letter-spacing: -0.02em; }
.px-chg { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
.px-meta { font-size: 12px; color: var(--faint); margin-top: 5px; }
.monogram { width: 48px; height: 48px; border-radius: 10px; display: flex; align-items: center;
    justify-content: center; font-weight: 800; font-size: 17px; }

/* ---------- 52-week range bar ---------- */
.rng { margin-top: 10px; }
.rng-track { position: relative; height: 6px; border-radius: 3px; background: var(--surface-sunk); }
.rng-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px;
    background: linear-gradient(90deg, var(--accent-soft), var(--accent)); }
.rng-mark { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--text); border-radius: 1px; }
.rng-labels { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--faint); margin-top: 5px;
    font-family: 'IBM Plex Mono', monospace; }

/* ---------- Score bars ---------- */
.score-row { display: grid; grid-template-columns: 150px 1fr 50px; gap: 12px; align-items: center; margin-bottom: 9px; }
.score-name { font-size: 13px; color: var(--muted); font-weight: 500; }
.score-track { height: 8px; border-radius: 4px; background: var(--surface-sunk); overflow: hidden; }
.score-fill { height: 100%; border-radius: 4px; }
.score-val { color: var(--text);  font-family: 'IBM Plex Mono', monospace; font-size: 13px; font-weight: 600; text-align: right; }
.verdict { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.verdict-score { font-family: 'IBM Plex Mono', monospace; font-size: 46px; font-weight: 700; line-height: 1; letter-spacing: -0.03em; }
.verdict-band { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }
.verdict-text { font-size: 13.8px; color: var(--muted); line-height: 1.6; flex: 1; min-width: 240px; }

/* ---------- Checklist ---------- */
.chk { display: grid; grid-template-columns: 22px 1fr; gap: 10px; align-items: start; margin-bottom: 10px;
    font-size: 13.8px; line-height: 1.55; }
.chk-mark { font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 14px; text-align: center; }
.chk-pass { color: var(--success); } .chk-fail { color: var(--danger); } .chk-warn { color: var(--warning); } .chk-na { color: var(--faint); }
.chk-label { color: var(--text);  font-weight: 600; } .chk-detail { color: var(--muted); }

/* ---------- Definition blocks (line-item deep dive) ---------- */
.defn { border-left: 3px solid var(--accent); background: var(--surface); border: 1px solid var(--border);
    border-left-width: 3px; border-radius: 9px; padding: 14px 16px; margin-bottom: 10px; }
.defn-h { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.defn-name { color: var(--text);  font-size: 15px; font-weight: 700; }
.defn-val { font-family: 'IBM Plex Mono', monospace; font-size: 15px; font-weight: 600; color: var(--accent); }
.defn-row { display: grid; grid-template-columns: 110px 1fr; gap: 12px; margin-top: 9px;
    font-size: 13.8px; line-height: 1.6; }
.defn-k { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--faint); padding-top: 3px; }

/* ---------- Tabs & tables ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--border);
    overflow-x: auto; scrollbar-width: thin; }
.stTabs [data-baseweb="tab"] { height: 42px; background: transparent; border: none; font-size: 14.5px;
    font-weight: 500; padding: 0 15px; color: var(--muted); border-radius: 7px 7px 0 0; white-space: nowrap; }
.stTabs [aria-selected="true"] { color: var(--accent) !important; font-weight: 700;
    background: var(--surface-alt); box-shadow: inset 0 -2px 0 var(--accent); }
[data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; font-size: 13.5px; }
[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; font-size: 23px; }
[data-testid="stMetricLabel"] { font-size: 13px; color: var(--muted); }
[data-testid="stExpander"] summary p { font-size: 14px !important; font-weight: 500; }

/* ---------- News list ---------- */
.news { border-bottom: 1px solid var(--border); padding: 10px 0; }
.news:last-child { border-bottom: none; }
.news-t { color: var(--text);  font-size: 14.5px; line-height: 1.5; font-weight: 500; }
.news-m { font-size: 12px; color: var(--faint); margin-top: 4px; }

/* ---------- Footer ---------- */
.foot { border-top: 1px solid var(--border); margin-top: 36px; padding: 16px 0 6px;
    font-size: 12.5px; color: var(--faint); line-height: 1.7; }


/* ---------- Floating sidebar panel ---------- */
[data-testid="stSidebar"] { background: transparent; border-right: none; }
[data-testid="stSidebarContent"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin: 10px 6px 10px 10px;
    box-shadow: 0 12px 32px var(--shadow);
}
[data-testid="stSidebarHeader"] { padding: 8px 12px 0; height: auto; }
[data-testid="stSidebarUserContent"] { padding-top: .35rem; }

/* ---------- Module navigator: visible tabs, not a dropdown ---------- */
.st-key-module, .st-key-module [data-testid="stRadio"] { width: 100% !important; }
.st-key-module div[role="radiogroup"] { display: flex; flex-direction: column;
    gap: 5px; align-items: stretch; width: 100%; }
.st-key-module [data-testid="stRadioOption"] { width: 100%; }
/* hide the radio dot; the card itself carries the selected state */
.st-key-module [data-testid="stRadioOption"] > div > div > div:first-child { display: none; }
.st-key-module [data-testid="stRadioOption"] {
    position: relative;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 9px 12px 9px 13px;
    background: var(--surface-alt);
    cursor: pointer;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease,
                opacity .16s ease, background-color .16s ease;
}
.st-key-module [data-testid="stRadioOption"] p {
    font-size: 13.5px !important; font-weight: 600; margin: 0;
    color: var(--muted) !important; letter-spacing: .005em;
}
/* hover: a grey outline and a slight lift */
.st-key-module [data-testid="stRadioOption"]:hover {
    border-color: var(--border);
    background: var(--surface);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px var(--shadow);
}
.st-key-module [data-testid="stRadioOption"]:hover p { color: var(--text) !important; }
/* selected: bright accent border, a ring, and a left marker */
.st-key-module [data-testid="stRadioOption"]:has(input:checked) {
    background: var(--neu-bg);
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--ring), 0 8px 20px var(--shadow);
    transform: translateY(-1px);
}
.st-key-module [data-testid="stRadioOption"]:has(input:checked) p {
    color: var(--accent) !important; font-weight: 700;
}
.st-key-module [data-testid="stRadioOption"]:has(input:checked)::before {
    content: ""; position: absolute; left: 0; top: 9px; bottom: 9px; width: 3px;
    background: var(--accent); border-radius: 0 3px 3px 0;
}
.st-key-module [data-testid="stRadioOption"]:focus-visible {
    outline: 2px solid var(--accent); outline-offset: 2px;
}
/* Dim the unselected entries only where :has() can actually mark the selected
   one, so a browser without :has() shows every entry at full strength rather
   than a uniformly greyed-out list. */
@supports selector(:has(*)) {
    .st-key-module [data-testid="stRadioOption"] { opacity: .62; }
    .st-key-module [data-testid="stRadioOption"]:hover { opacity: .9; }
    .st-key-module [data-testid="stRadioOption"]:has(input:checked) { opacity: 1; }
}

/* ---------- Mobile ---------- */
@media (max-width: 780px) {
  :root { --card-pad: 15px 16px; --kpi-pad: 13px 15px; --gap: 10px; --fs-kpi: 23px;
          --fs-body: 14.5px; --fs-note: 14px; --sec-top: 26px; }
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: 1.2rem; }
  .hdr-name { font-size: 23px; }
  .px-box { text-align: left; margin-top: 12px; }
  .px-value { font-size: 27px; }
  .section-title { font-size: 17.5px; }
  .score-row { grid-template-columns: 118px 1fr 40px; gap: 9px; }
  .exp-row, .defn-row { grid-template-columns: 1fr; gap: 3px; }
  .verdict-score { font-size: 38px; }
  .stTabs [data-baseweb="tab"] { font-size: 13.5px; padding: 0 11px; height: 38px; }
  .monogram { display: none; }
  .hdr-chip { font-size: 11.5px; }
}

/* ---------- Print ---------- */
@media print {
  [data-testid="stSidebar"], [data-testid="stToolbar"], .stButton { display: none !important; }
  .block-container { max-width: 100%; padding: 0; }
  .card, .kpi, .note { break-inside: avoid; }
}
</style>
"""

st.markdown(_STYLESHEET.replace("/*TOKENS*/", _tokens_css(T)), unsafe_allow_html=True)

# Plotly styling derived from the same tokens.
PLOT_SEQ = [T["accent_soft"], T["success"], T["warning"], T["info"], T["danger"], T["faint"]]
PLOTLY_TEMPLATE = "plotly_dark" if st.session_state.theme == "Dark" else "plotly_white"


def style_fig(fig, height=None, legend="top", margin=None):
    """Applies the app's typographic and colour system to any Plotly figure.

    Note on the title: it is cleared with an empty string, not None. Passing
    None leaves an empty title *object* behind, which Plotly.js renders as the
    literal text "undefined" above the chart.
    """
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        font=dict(family="Inter, sans-serif", size=13, color=T["text"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=PLOT_SEQ,
        margin=margin or dict(l=8, r=8, t=30, b=8),
        hoverlabel=dict(font_family="IBM Plex Mono, monospace", font_size=13,
                        bgcolor=T["surface"], bordercolor=T["border"]),
        title_text="",
    )
    if height:
        fig.update_layout(height=height)
    if legend == "top":
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.01,
                                      xanchor="left", x=0, font=dict(size=12.5)))
    elif legend == "off":
        fig.update_layout(showlegend=False)
    fig.update_xaxes(gridcolor=T["grid"], zerolinecolor=T["grid"], linecolor=T["border"],
                     tickfont=dict(size=12, color=T["muted"]), title_font=dict(size=12.5, color=T["muted"]))
    fig.update_yaxes(gridcolor=T["grid"], zerolinecolor=T["grid"], linecolor=T["border"],
                     tickfont=dict(size=12, color=T["muted"]), title_font=dict(size=12.5, color=T["muted"]))
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


def conv(value, rate):
    """Convert a monetary figure into the display currency. Returns None when
    the value itself is missing, so a gap in the data feed reads as "not
    available" instead of raising on `None * rate`."""
    return value * rate if _isnum(value) else None


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


def dividend_yield(info: dict, price):
    """Dividend yield as a fraction.

    `dividendYield` alone is unreliable: yfinance has reported it as a fraction
    (0.0044) in some versions and as a percentage (0.44) in others, and the two
    are indistinguishable from the number alone. Deriving it from the annual
    dividend per share and the price is unambiguous, so that is tried first;
    the reported fields are only fallbacks, cross-checked against the payout
    ratio and capped at a level no ordinary equity exceeds."""
    rate = pick(info, "dividendRate", "trailingAnnualDividendRate")
    derived = safe_div(rate, price)
    if derived is not None and 0 <= derived < 0.25:
        return derived
    # No equity yields more than about 25% for long, so a "fraction" above that
    # is really a percentage that has not been scaled.
    for key in ("trailingAnnualDividendYield", "dividendYield", "yield"):
        v = info.get(key)
        if not _isnum(v) or v <= 0:
            continue
        candidate = v / 100.0 if v > 0.25 else v
        if candidate < 0.25:
            return candidate
    return None


def dividend_facts(info: dict, price):
    """Everything the dividend panel needs, with epoch timestamps resolved."""
    def as_date(key):
        v = info.get(key)
        if not _isnum(v):
            return None
        try:
            return datetime.fromtimestamp(v)
        except (ValueError, OSError, OverflowError):
            return None

    five_yr = info.get("fiveYearAvgDividendYield")  # reported in percent
    return {
        "yield": dividend_yield(info, price),
        "rate": pick(info, "dividendRate", "trailingAnnualDividendRate"),
        "ex_date": as_date("exDividendDate"),
        "pay_date": as_date("dividendDate"),
        "payout": info.get("payoutRatio"),
        "five_year_avg": (five_yr / 100.0) if _isnum(five_yr) else None,
        "last_split": info.get("lastSplitFactor"),
    }


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


def _fetch_fast_info(ticker: str) -> dict:
    """Yahoo's lightweight quote endpoint, reached through a different route
    than `.info`. When the heavier endpoint is rate-limited — which happens
    routinely from shared cloud hosts — this one often still answers."""
    out = {}
    try:
        fast = yf.Ticker(ticker).fast_info
        for key in ("last_price", "previous_close", "open", "day_high", "day_low",
                    "market_cap", "shares", "currency", "year_high", "year_low",
                    "fifty_day_average", "two_hundred_day_average", "ten_day_average_volume"):
            try:
                value = fast[key]
            except Exception:
                value = getattr(fast, key, None)
            if value is not None:
                out[key] = value
    except Exception:
        pass
    return out


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


# --- Backup sources ----------------------------------------------------------
# Yahoo rate-limits per source address, and a shared cloud host hits that limit
# routinely. Two independent providers stand behind it. Neither needs an API key,
# so they work on any deployment without configuration:
#
#   Stooq       - daily price history as CSV, covering most developed markets.
#   SEC EDGAR   - the XBRL company-facts API: the filings themselves, straight
#                 from the regulator. US filers only, but authoritative.
#
# Whichever source answers is recorded, and the provenance panel names it, so a
# figure can always be traced back to where it came from.

SOURCE_LOG_KEY = "_source_log"


def note_source(what: str, source: str):
    """Records which provider actually served a piece of data. Wrapped because
    cached loaders can run outside a script context, where session state is
    unavailable — losing a provenance note must never break a fetch."""
    try:
        st.session_state.setdefault(SOURCE_LOG_KEY, {})[what] = source
    except Exception:
        pass


def _http_json(url: str, timeout: int = 10, headers: dict = None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_text(url: str, timeout: int = 10, headers: dict = None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# Stooq's own market suffixes, keyed by the Yahoo suffix this app uses.
STOOQ_SUFFIX = {
    "": ".us", "DE": ".de", "F": ".de", "L": ".uk", "T": ".jp", "HK": ".hk",
    "PA": ".fr", "MI": ".it", "MC": ".es", "AS": ".nl", "BR": ".be", "VI": ".at",
    "SW": ".ch", "ST": ".se", "OL": ".no", "CO": ".dk", "HE": ".fi", "IR": ".ie",
    "LS": ".pt", "AT": ".gr", "WA": ".pl", "PR": ".cz", "BD": ".hu", "IS": ".tr",
    "TA": ".il", "NS": ".in", "BO": ".in", "SS": ".cn", "SZ": ".cn", "KS": ".kr",
    "KQ": ".kr", "TW": ".tw", "SI": ".sg", "AX": ".au", "NZ": ".nz", "TO": ".ca",
    "V": ".ca", "SA": ".br", "MX": ".mx", "BA": ".ar", "SN": ".cl", "JO": ".za",
}


def _stooq_symbol(ticker: str):
    """Translates a Yahoo symbol into Stooq's convention, or None where Stooq
    does not cover that market (Vietnam among them)."""
    if not ticker:
        return None
    if "." in ticker:
        base, suffix = ticker.rsplit(".", 1)
        suffix = suffix.upper()
    else:
        base, suffix = ticker, ""
    stooq_suffix = STOOQ_SUFFIX.get(suffix)
    if stooq_suffix is None:
        return None
    return f"{base.replace('-', '.').lower()}{stooq_suffix}"


def _stooq_history(ticker: str) -> pd.DataFrame:
    """Daily OHLCV from Stooq. Returns the app's usual history shape so it can
    be swapped in wherever a Yahoo history would have gone."""
    symbol = _stooq_symbol(ticker)
    if not symbol:
        return pd.DataFrame()
    try:
        text = _http_text(f"https://stooq.com/q/d/l/?s={urllib.parse.quote(symbol)}&i=d", timeout=12)
    except Exception as exc:
        note_error("stooq history", exc)
        return pd.DataFrame()
    lines = text.splitlines() if text else []
    if not lines or "," not in lines[0]:
        return pd.DataFrame()
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception:
        return pd.DataFrame()
    if df.empty or "Date" not in df.columns or "Close" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column not in df.columns:
            df[column] = np.nan
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _stooq_window(ticker: str, period: str) -> pd.DataFrame:
    """Stooq serves the full history in one file; this trims it to the period
    the caller asked Yahoo for, so the fallback is a drop-in replacement."""
    df = _stooq_history(ticker)
    if df.empty:
        return df
    days = {"5d": 7, "1mo": 31, "3mo": 93, "6mo": 186, "1y": 365,
            "3y": 1095, "5y": 1825, "10y": 3650}.get(period)
    if period == "ytd":
        return df[df.index >= pd.Timestamp(datetime.now().year, 1, 1)]
    if days:
        return df[df.index >= pd.Timestamp(datetime.now().date() - timedelta(days=days))]
    return df


# --- SEC EDGAR ---------------------------------------------------------------
# The SEC asks that automated requests identify themselves; this is that
# identification, and the 10 requests/second guidance is respected simply by how
# little this app calls it (twice per company, both cached for a day).
SEC_HEADERS = {"User-Agent": "Investment Terminal research app (contact via GitHub repository)",
               "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}

# XBRL concepts mapped onto the line-item names the rest of the app expects, so
# a statement rebuilt from EDGAR is indistinguishable downstream.
SEC_INCOME = {
    "Total Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                      "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "Cost Of Revenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
    "Gross Profit": ["GrossProfit"],
    "Research And Development": ["ResearchAndDevelopmentExpense"],
    "Selling General And Administration": ["SellingGeneralAndAdministrativeExpense"],
    "Operating Expense": ["OperatingExpenses", "CostsAndExpenses"],
    "Operating Income": ["OperatingIncomeLoss"],
    "Interest Expense": ["InterestExpense", "InterestIncomeExpenseNet"],
    "Pretax Income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "Tax Provision": ["IncomeTaxExpenseBenefit"],
    "Net Income": ["NetIncomeLoss", "ProfitLoss"],
}
SEC_INCOME_PERSHARE = {
    "Basic EPS": ["EarningsPerShareBasic"],
    "Diluted EPS": ["EarningsPerShareDiluted"],
}
SEC_INCOME_SHARES = {
    "Basic Average Shares": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "Diluted Average Shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
SEC_BALANCE = {
    "Cash And Cash Equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "Accounts Receivable": ["AccountsReceivableNetCurrent"],
    "Inventory": ["InventoryNet"],
    "Current Assets": ["AssetsCurrent"],
    "Net PPE": ["PropertyPlantAndEquipmentNet"],
    "Goodwill": ["Goodwill"],
    "Total Assets": ["Assets"],
    "Accounts Payable": ["AccountsPayableCurrent"],
    "Current Liabilities": ["LiabilitiesCurrent"],
    "Current Debt": ["LongTermDebtCurrent", "DebtCurrent"],
    "Long Term Debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "Total Liabilities Net Minority Interest": ["Liabilities"],
    "Retained Earnings": ["RetainedEarningsAccumulatedDeficit"],
    "Stockholders Equity": ["StockholdersEquity",
                            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "Ordinary Shares Number": ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"],
    "Total Debt": ["DebtLongtermAndShorttermCombinedAmount"],
}
SEC_CASHFLOW = {
    "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities",
                            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "Depreciation And Amortization": ["DepreciationDepletionAndAmortization",
                                      "DepreciationAmortizationAndAccretionNet"],
    "Stock Based Compensation": ["ShareBasedCompensation"],
    "Capital Expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "Investing Cash Flow": ["NetCashProvidedByUsedInInvestingActivities"],
    "Financing Cash Flow": ["NetCashProvidedByUsedInFinancingActivities"],
    "Cash Dividends Paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "Repurchase Of Capital Stock": ["PaymentsForRepurchaseOfCommonStock"],
}
SEC_ANNUAL_FORMS = ("10-K", "20-F", "40-F")
SEC_QUARTER_FORMS = ("10-Q",)


@st.cache_data(ttl=86400, show_spinner=False)
def _sec_cik(ticker: str):
    """Maps a ticker to its SEC central index key. US listings only."""
    base = (ticker or "").split(".")[0].upper().replace("-", "")
    if not base or ("." in (ticker or "") and not ticker.upper().endswith(".US")):
        return None
    try:
        data = _http_json("https://www.sec.gov/files/company_tickers.json",
                          headers={"User-Agent": SEC_HEADERS["User-Agent"]})
    except Exception as exc:
        note_error("sec ticker map", exc)
        return None
    for row in (data or {}).values():
        if str(row.get("ticker", "")).upper().replace("-", "") == base:
            return f"CIK{int(row['cik_str']):010d}"
    return None


def _sec_series(facts: dict, tags, instant: bool, forms) -> pd.Series:
    """One concept's reported values, keyed by period end.

    Duration facts (revenue, cash flow) are filtered by how long the period they
    cover actually is, because the same tag carries quarterly, half-year and
    annual values in the same list and only the period length separates them."""
    namespaces = (facts or {}).get("facts", {})
    pool = {}
    for ns in ("us-gaap", "ifrs-full", "dei"):
        pool.update(namespaces.get(ns, {}))
    for tag in tags:
        node = pool.get(tag)
        if not node:
            continue
        for unit in ("USD", "USD/shares", "shares"):
            entries = node.get("units", {}).get(unit)
            if not entries:
                continue
            out = {}
            for e in entries:
                if e.get("form") not in forms or e.get("val") is None or not e.get("end"):
                    continue
                if not instant:
                    if not e.get("start"):
                        continue
                    span = (pd.Timestamp(e["end"]) - pd.Timestamp(e["start"])).days
                    ok = (330 <= span <= 400) if forms == SEC_ANNUAL_FORMS else (60 <= span <= 110)
                    if not ok:
                        continue
                out[pd.Timestamp(e["end"])] = float(e["val"])
            if out:
                return pd.Series(out).sort_index()
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def load_sec_statements(ticker: str, quarterly: bool = False) -> dict:
    """Income statement, balance sheet and cash flow rebuilt from EDGAR's XBRL
    company facts, in the same shape as the primary source's."""
    empty = {"inc": pd.DataFrame(), "bs": pd.DataFrame(), "cf": pd.DataFrame()}
    cik = _sec_cik(ticker)
    if not cik:
        return empty
    try:
        facts = _http_json(f"https://data.sec.gov/api/xbrl/companyfacts/{cik}.json",
                           timeout=20, headers={"User-Agent": SEC_HEADERS["User-Agent"]})
    except Exception as exc:
        note_error("sec companyfacts", exc)
        return empty
    forms = SEC_QUARTER_FORMS if quarterly else SEC_ANNUAL_FORMS

    def build(mapping, instant, extra_maps=()):
        cols = {}
        for name, tags in mapping.items():
            series = _sec_series(facts, tags, instant, forms)
            if series is not None:
                cols[name] = series
        for mapping_extra in extra_maps:
            for name, tags in mapping_extra.items():
                series = _sec_series(facts, tags, instant, forms)
                if series is not None:
                    cols[name] = series
        return pd.DataFrame(cols).sort_index() if cols else pd.DataFrame()

    inc = build(SEC_INCOME, instant=False, extra_maps=(SEC_INCOME_PERSHARE, SEC_INCOME_SHARES))
    bs = build(SEC_BALANCE, instant=True)
    cf = build(SEC_CASHFLOW, instant=False)
    # EDGAR reports capital expenditure as a positive outflow; the rest of the
    # app follows the cash-flow-statement convention of a negative number.
    if not cf.empty and "Capital Expenditure" in cf.columns:
        cf["Capital Expenditure"] = -cf["Capital Expenditure"].abs()
        if "Operating Cash Flow" in cf.columns:
            cf["Free Cash Flow"] = cf["Operating Cash Flow"] + cf["Capital Expenditure"]
    if not inc.empty and {"Total Revenue", "Cost Of Revenue"}.issubset(inc.columns) \
            and "Gross Profit" not in inc.columns:
        inc["Gross Profit"] = inc["Total Revenue"] - inc["Cost Of Revenue"]
    return {"inc": inc, "bs": bs, "cf": cf}


# --- cached loaders ----------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def load_info(ticker: str) -> dict:
    return _fetch_info(ticker)


@st.cache_data(ttl=900, show_spinner=False)
def load_fast_info(ticker: str) -> dict:
    return _fetch_fast_info(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def estimate_beta(ticker: str, benchmark: str = "SPY"):
    """Beta from two years of daily returns against a broad index, used when the
    quote endpoint does not report one."""
    try:
        a = _fetch_history(ticker, "2y", "1d")
        b = _fetch_history(benchmark, "2y", "1d")
        if a.empty or b.empty or "Close" not in a or "Close" not in b:
            return None
        ra = a["Close"].pct_change().dropna()
        rb = b["Close"].pct_change().dropna()
        joined = pd.concat([ra, rb], axis=1, join="inner").dropna()
        if len(joined) < 60:
            return None
        cov = joined.cov().iloc[0, 1]
        var = joined.iloc[:, 1].var()
        return float(cov / var) if var else None
    except Exception:
        return None


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
    if any(not frame.empty for frame in out.values()):
        note_source("financial statements", DATA_SOURCE)
        return out
    backup = load_sec_statements(ticker, quarterly)
    if any(not frame.empty for frame in backup.values()):
        note_source("financial statements", "SEC EDGAR (XBRL company facts)")
        return backup
    return out


@st.cache_data(ttl=900, show_spinner=False)
def load_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    df = _fetch_history(ticker, period, interval)
    if isinstance(df, pd.DataFrame) and not df.empty:
        note_source("price history", DATA_SOURCE)
        return df
    # Intraday intervals have no equivalent on the daily-only backup, so this
    # only rescues daily-and-longer requests - which is all of them except the
    # shortest chart period.
    if interval in ("1d", "1wk", "1mo"):
        backup = _stooq_window(ticker, period)
        if not backup.empty:
            note_source("price history", "Stooq")
            return backup
    return df


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

# Yahoo's exchange suffixes. This is a mapping of *venues*, not of companies:
# no company list is bundled with the app, so any symbol on any of these markets
# resolves live.
EXCHANGE_LABELS = {
    "": "United States", "VN": "Vietnam (HOSE/HNX)", "DE": "Germany (Xetra)",
    "F": "Germany (Frankfurt)", "L": "United Kingdom (LSE)", "IL": "London (intl)",
    "T": "Japan (Tokyo)", "SS": "China (Shanghai)", "SZ": "China (Shenzhen)",
    "HK": "Hong Kong", "TW": "Taiwan", "TWO": "Taiwan (OTC)", "KS": "South Korea (KOSPI)",
    "KQ": "South Korea (KOSDAQ)", "NS": "India (NSE)", "BO": "India (BSE)",
    "SI": "Singapore", "AX": "Australia (ASX)", "NZ": "New Zealand",
    "TO": "Canada (TSX)", "V": "Canada (TSXV)", "NE": "Canada (NEO)",
    "SW": "Switzerland (SIX)", "PA": "France (Euronext Paris)",
    "AS": "Netherlands (Euronext)", "BR": "Belgium (Euronext)",
    "LS": "Portugal (Euronext)", "MI": "Italy (Borsa Italiana)",
    "MC": "Spain (BME)", "VI": "Austria (Wiener Börse)", "IR": "Ireland (Euronext)",
    "ST": "Sweden (Nasdaq Stockholm)", "OL": "Norway (Oslo Børs)",
    "CO": "Denmark (Nasdaq Copenhagen)", "HE": "Finland (Nasdaq Helsinki)",
    "IC": "Iceland", "WA": "Poland (GPW)", "PR": "Czechia (PSE)",
    "IS": "Türkiye (Borsa Istanbul)", "TA": "Israel (TASE)", "SR": "Saudi Arabia (Tadawul)",
    "QA": "Qatar", "AE": "UAE (Abu Dhabi)", "CA": "Egypt (EGX)", "JO": "South Africa (JSE)",
    "SA": "Brazil (B3)", "MX": "Mexico (BMV)", "BA": "Argentina (BYMA)",
    "SN": "Chile (Santiago)", "CN": "Canada (CSE)", "BK": "Thailand (SET)",
    "JK": "Indonesia (IDX)", "KL": "Malaysia (Bursa)", "PS": "Philippines (PSE)",
    "AT": "Greece (ATHEX)", "BD": "Hungary (BSE)", "RG": "Latvia", "TL": "Estonia",
}
MARKET_SUFFIXES = tuple(f".{k}" for k in EXCHANGE_LABELS if k)

# Where each market's own audited filings actually live. Yahoo carries a
# normalised summary; these are the primary sources to verify a number against,
# with the filing rhythm that market runs on.
FILING_SOURCES = {
    "": {"name": "SEC EDGAR",
         "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={base}&type=10-K&dateb=&owner=include&count=40",
         "rhythm": "Annual report on Form 10-K and quarterly reports on Form 10-Q, plus 8-K for material events. Full text is free and searchable."},
    "VN": {"name": "HOSE disclosure and Vietstock",
           "url": "https://finance.vietstock.vn/{base}/tai-chinh.htm",
           "rhythm": "Báo cáo tài chính quý (unaudited quarterly), a reviewed half-year report, and an audited annual report, filed with the State Securities Commission and the exchange. Quarterly statements are typically due within 20 days of quarter end (30 for consolidated), the reviewed half-year within 45 days, and the audited annual within 90 days. Vietnamese issuers report in VND under Vietnamese Accounting Standards, which differ from IFRS in several places — treat cross-border comparisons of margins and equity with care."},
    "DE": {"name": "Bundesanzeiger and company IR",
           "url": "https://www.bundesanzeiger.de/pub/en/suchen?4",
           "rhythm": "Annual and half-year financial reports; Prime Standard issuers also publish quarterly statements. Filings are in German and often English on the company's own investor-relations pages."},
    "L": {"name": "FCA National Storage Mechanism / RNS",
          "url": "https://data.fca.org.uk/#/nsm/nationalstoragemechanism",
          "rhythm": "Annual report and a half-year report. Quarterly reporting has not been mandatory in the UK since 2014, so many companies publish trading updates instead of full quarterly accounts."},
    "T": {"name": "EDINET and TDnet",
          "url": "https://disclosure2.edinet-fsa.go.jp/",
          "rhythm": "Quarterly earnings summaries (kessan tanshin) through TDnet and the annual securities report (yūkashōken hōkokusho) through EDINET. Many filings are Japanese-only; larger issuers publish English summaries."},
    "SS": {"name": "Shanghai Stock Exchange / CNINFO",
           "url": "http://www.cninfo.com.cn/new/index",
           "rhythm": "Quarterly, half-year and annual reports are all mandatory. Filings are in Chinese; annual reports are audited under Chinese Accounting Standards."},
    "SZ": {"name": "Shenzhen Stock Exchange / CNINFO",
           "url": "http://www.cninfo.com.cn/new/index",
           "rhythm": "Quarterly, half-year and annual reports are all mandatory, filed in Chinese."},
    "HK": {"name": "HKEXnews",
           "url": "https://www.hkexnews.hk/",
           "rhythm": "Interim and annual reports are required; quarterly reporting is voluntary on the Main Board. Filings are published in both English and Chinese."},
    "KS": {"name": "DART (Financial Supervisory Service)",
           "url": "https://engdart.fss.or.kr/",
           "rhythm": "Quarterly, half-year and annual reports. English summaries are available through the English DART portal."},
    "TW": {"name": "MOPS (Market Observation Post System)",
           "url": "https://mops.twse.com.tw/mops/web/index",
           "rhythm": "Monthly revenue announcements plus quarterly and annual financial reports — the monthly revenue disclosure is unusual and useful."},
    "NS": {"name": "NSE India / BSE",
           "url": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
           "rhythm": "Quarterly results and an audited annual report; Indian issuers also publish detailed shareholding patterns each quarter."},
    "AX": {"name": "ASX announcements",
           "url": "https://www.asx.com.au/markets/company/{base}",
           "rhythm": "Half-year and annual reports, plus quarterly cash-flow reports (Appendix 4C/5B) for smaller and pre-revenue companies."},
    "TO": {"name": "SEDAR+",
           "url": "https://www.sedarplus.ca/",
           "rhythm": "Quarterly and annual filings, including the MD&A, which is where Canadian issuers explain the numbers."},
    "SI": {"name": "SGX company announcements",
           "url": "https://www.sgx.com/securities/company-announcements",
           "rhythm": "Half-year and annual results; quarterly reporting is required only for companies flagged by the exchange."},
    "SW": {"name": "SIX Exchange regulation",
           "url": "https://www.six-exchange-regulation.com/en/home/publications/official-notices.html",
           "rhythm": "Annual and half-year reports under IFRS or Swiss GAAP FER."},
}
FILING_SOURCE_DEFAULT = {
    "name": "the company's own investor-relations pages",
    "url": "",
    "rhythm": "Reporting frequency and deadlines vary by market. The company's investor-relations site and its exchange's disclosure portal are the authoritative sources.",
}


def filing_source(ticker: str) -> dict:
    """The primary filing source for a symbol's market, with the ticker filled in."""
    suffix = ticker.split(".")[-1].upper() if ticker and "." in ticker else ""
    base = ticker.split(".")[0] if ticker else ""
    src = dict(FILING_SOURCES.get(suffix, FILING_SOURCE_DEFAULT))
    src["url"] = src["url"].replace("{base}", base) if src.get("url") else ""
    return src


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

# Yahoo exposes several different search routes, and they fail independently:
# the raw JSON endpoint needs a cookie and crumb that expire, while yfinance's
# own Search and Lookup classes negotiate those for you. Any one of them can be
# rate-limited at a given moment, so all of them are tried in turn before the
# app tells a user their company does not exist.

ACCEPTED_QUOTE_TYPES = ("EQUITY", "ETF", "INDEX", "MUTUALFUND")


def _norm_hit(symbol, name, exchange, qtype):
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return None
    return {"symbol": symbol, "name": str(name or symbol).strip(),
            "exchange": str(exchange or "").strip(), "type": str(qtype or "").upper()}


def _search_via_yf_search(query, max_results):
    try:
        quotes = yf.Search(query, max_results=max_results, news_count=0, lists_count=0,
                           enable_fuzzy_query=True, raise_errors=False).quotes or []
    except Exception as exc:
        note_error("search (yf.Search)", exc)
        return []
    out = []
    for q in quotes:
        if not isinstance(q, dict):
            continue
        hit = _norm_hit(q.get("symbol"),
                        q.get("shortname") or q.get("longname"),
                        q.get("exchDisp") or q.get("exchange"),
                        q.get("quoteType"))
        if hit and (not hit["type"] or hit["type"] in ACCEPTED_QUOTE_TYPES):
            out.append(hit)
    return out


def _search_via_yf_lookup(query, max_results):
    """`Lookup` searches Yahoo's instrument directory directly and reaches
    listings the fuzzy search sometimes misses, particularly outside the US."""
    try:
        lookup = yf.Lookup(query, raise_errors=False)
    except Exception as exc:
        note_error("search (yf.Lookup)", exc)
        return []
    out = []
    for getter, qtype in (("get_stock", "EQUITY"), ("get_etf", "ETF"), ("get_index", "INDEX")):
        try:
            df = getattr(lookup, getter)(count=max_results)
        except Exception:
            continue
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        for symbol, row in df.iterrows():
            hit = _norm_hit(row.get("symbol", symbol),
                            row.get("shortName") or row.get("longName") or row.get("name"),
                            row.get("exchange") or row.get("exchDisp"),
                            row.get("quoteType") or qtype)
            if hit:
                out.append(hit)
    return out


def _search_via_endpoint(query, max_results):
    for host in ("query2", "query1"):
        try:
            params = urllib.parse.urlencode({
                "q": query, "quotesCount": max_results, "newsCount": 0,
                "listsCount": 0, "enableFuzzyQuery": True,
            })
            url = f"https://{host}.finance.yahoo.com/v1/finance/search?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            out = []
            for q in data.get("quotes", []):
                hit = _norm_hit(q.get("symbol"), q.get("shortname") or q.get("longname"),
                                q.get("exchange") or q.get("exchDisp"), q.get("quoteType"))
                if hit and (not hit["type"] or hit["type"] in ACCEPTED_QUOTE_TYPES):
                    out.append(hit)
            if out:
                return out
        except Exception as exc:
            note_error(f"search ({host})", exc)
    return []


def _probe_as_symbol(query, suffixes):
    """Last resort: treat the query as a symbol and check it against every
    market suffix at once. This is what rescues a search when Yahoo's search
    routes are all throttled but the quote route still answers."""
    base = query.strip().upper().replace(" ", "")
    if not (1 < len(base) <= 12) or not re.fullmatch(r"[A-Z0-9.\-]+", base):
        return []
    candidates = [base] if "." in base else [base] + [f"{base}{sfx}" for sfx in suffixes if sfx]

    def check(sym):
        fast = _fetch_fast_info(sym)
        if _isnum(fast.get("last_price")):
            return _norm_hit(sym, sym, fast.get("currency", ""), "EQUITY")
        hist = _fetch_history(sym, "5d", "1d")
        if not hist.empty and "Close" in hist and hist["Close"].dropna().size:
            return _norm_hit(sym, sym, "", "EQUITY")
        return None

    return [h for h in parallel_map(check, candidates[:14]) if h]


@st.cache_data(ttl=1800, show_spinner=False)
def search_ticker(query: str, max_results: int = 12):
    """Resolves a company name, or a partial symbol, to tradable symbols.

    Always live: nothing about the company universe is bundled with this app,
    because listings, renames and delistings change constantly. Four independent
    routes are tried in order and their results merged, so one throttled
    endpoint does not make a real company look nonexistent."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    results, seen = [], set()
    for route in (_search_via_yf_search, _search_via_yf_lookup, _search_via_endpoint):
        try:
            hits = route(query, max_results)
        except Exception as exc:
            note_error(f"search route {route.__name__}", exc)
            hits = []
        for h in hits:
            if h["symbol"] not in seen:
                seen.add(h["symbol"])
                results.append(h)
        if len(results) >= max_results:
            return results[:max_results]
    if not results:
        for h in _probe_as_symbol(query, list(MARKET_SUFFIXES)):
            if h["symbol"] not in seen:
                seen.add(h["symbol"])
                results.append(h)
    return results[:max_results]


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


# --- Industry benchmarks -----------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def load_industry_commonsize(tickers: tuple) -> dict:
    """Median common-size statements across a peer group.

    Each peer's latest income statement is expressed as a percentage of its own
    revenue and each balance sheet as a percentage of its own total assets, then
    the median is taken line by line. That makes the comparison scale-free, so a
    company can be read against its industry rather than against an absolute
    number that means nothing on its own."""
    if not tickers:
        return {"income": pd.Series(dtype="float64"), "balance": pd.Series(dtype="float64"), "n": 0}

    def fetch(t):
        try:
            tk = yf.Ticker(t)
            return _norm_stmt(tk.income_stmt), _norm_stmt(tk.balance_sheet)
        except Exception:
            return pd.DataFrame(), pd.DataFrame()

    inc_rows, bs_rows = [], []
    for inc, bs in parallel_map(fetch, tickers):
        if not inc.empty and "Total Revenue" in inc.columns:
            row = inc.iloc[-1]
            rev = row.get("Total Revenue")
            if _isnum(rev) and rev > 0:
                inc_rows.append(row / rev * 100)
        if not bs.empty and "Total Assets" in bs.columns:
            row = bs.iloc[-1]
            ta = row.get("Total Assets")
            if _isnum(ta) and ta > 0:
                bs_rows.append(row / ta * 100)
    return {
        "income": pd.DataFrame(inc_rows).median() if inc_rows else pd.Series(dtype="float64"),
        "balance": pd.DataFrame(bs_rows).median() if bs_rows else pd.Series(dtype="float64"),
        "n": max(len(inc_rows), len(bs_rows)),
    }


# What each reported line actually means, what moves it, and what to watch.
# Keyed on the data source's own line-item names so the guide can be attached
# automatically to whatever the company happens to report.
LINE_ITEMS = {
    "Total Revenue": {
        "what": "Money billed to customers for goods and services over the period, after returns, discounts and rebates. It is the top line every other figure is measured against.",
        "drivers": "Volume sold, price per unit, product mix, currency translation on foreign sales, and — where relevant — how much of a long contract the accountants judge to have been delivered.",
        "watch": "Growth that comes only from price rises is more fragile than growth from volume. Revenue rising while receivables rise faster (section 1's quality flags) can mean sales are being pulled forward on looser credit terms."},
    "Cost Of Revenue": {
        "what": "The direct cost of producing what was sold: materials, manufacturing labour, freight in, and the depreciation of production equipment. Costs that would disappear if the product were not made.",
        "drivers": "Input and commodity prices, factory utilisation, wage rates, logistics costs, and manufacturing yield.",
        "watch": "Rising faster than revenue means gross margin is compressing — either inputs cost more or pricing power has weakened. Which one it is decides whether it reverses."},
    "Gross Profit": {
        "what": "Revenue less the direct cost of delivering it. What is left to cover everything else: research, selling, administration, interest and tax.",
        "drivers": "Pricing power, product mix, and manufacturing or delivery efficiency.",
        "watch": "Gross margin is the most durable indicator of competitive position. It moves slowly, so a sustained shift in either direction is usually structural rather than noise."},
    "Operating Expense": {
        "what": "The cost of running the business rather than making the product: research, sales and marketing, and general administration.",
        "drivers": "Headcount, marketing intensity, R&D commitment, and how much of the cost base is fixed.",
        "watch": "Growing more slowly than revenue is operating leverage and lifts margins. Growing faster is either investment for future growth or loss of cost discipline — the following years tell you which."},
    "Research And Development": {
        "what": "Spending on developing new products and improving existing ones, expensed as incurred rather than capitalised.",
        "drivers": "Engineering headcount, project pipeline, and how fast the industry's technology moves.",
        "watch": "Cutting R&D flatters this year's margin at the expense of the products that would have shipped in three years. Judge it as a percentage of revenue over time, not in absolute terms."},
    "Selling General And Administration": {
        "what": "Salaries and costs of the sales force, marketing programmes, finance, legal, HR and executive functions.",
        "drivers": "Sales headcount and commission, advertising commitments, and the fixed overhead of running a listed company.",
        "watch": "For consumer businesses this is largely discretionary marketing, so it is the first lever pulled when a quarter looks weak — and the reason a margin beat is not always good news."},
    "Operating Income": {
        "what": "Profit from the core business before financing costs and tax. The cleanest measure of whether the operation itself makes money.",
        "drivers": "Everything above it: revenue, direct costs and overheads.",
        "watch": "This is the figure to compare across companies, because it is unaffected by how each one chooses to finance itself."},
    "EBITDA": {
        "what": "Operating profit before depreciation and amortisation are subtracted — a rough proxy for cash operating earnings.",
        "drivers": "The same operating factors, with non-cash charges added back.",
        "watch": "It flatters capital-intensive businesses by ignoring the cost of the assets they must keep replacing. Always read it beside capital expenditure."},
    "Interest Expense": {
        "what": "The cost of borrowed money over the period.",
        "drivers": "Debt outstanding, the fixed-versus-floating mix, and prevailing rates when debt is refinanced.",
        "watch": "Compare against operating profit for interest cover. A company refinancing low-rate debt into a higher-rate market sees this line step up years before the debt itself changes."},
    "Pretax Income": {
        "what": "Profit after operating costs and financing but before tax.",
        "drivers": "Operating income, net interest, and one-off gains or losses.",
        "watch": "A large gap between operating income and pre-tax income means non-operating items are doing meaningful work — worth identifying before treating the result as repeatable."},
    "Tax Provision": {
        "what": "The tax charged against this period's profit, which is an accounting estimate rather than cash paid to a tax authority.",
        "drivers": "Statutory rates in each country of operation, profit mix by geography, and one-off settlements or credits.",
        "watch": "An unusually low effective rate in one year often reverses. The DCF in section 5 clamps the derived rate to a sensible band for exactly this reason."},
    "Net Income": {
        "what": "The bottom line: profit attributable to shareholders after every cost, including tax.",
        "drivers": "Everything above, plus one-off items that may not repeat.",
        "watch": "The most managed number in the statements. Section 4 checks it against cash, which is much harder to influence."},
    "Basic EPS": {
        "what": "Net income divided by the average number of shares outstanding.",
        "drivers": "Profit, and the share count — buybacks raise it without the business improving.",
        "watch": "Compare EPS growth against net income growth. A gap between them is the buyback, not the business."},
    "Diluted EPS": {
        "what": "Earnings per share assuming all options, convertibles and restricted stock become shares.",
        "drivers": "Profit and the fully diluted share count.",
        "watch": "A wide gap to basic EPS signals heavy equity compensation — a real cost to existing holders that never appears as cash."},

    "Cash And Cash Equivalents": {
        "what": "Money in the bank and instruments convertible to cash within about three months.",
        "drivers": "Operating cash generation, capital spending, borrowing, dividends and buybacks.",
        "watch": "Read alongside debt, not on its own. Large cash balances held against larger borrowings are often trapped in the wrong jurisdiction."},
    "Accounts Receivable": {
        "what": "Money owed by customers for goods already delivered and recognised as revenue.",
        "drivers": "Sales volume, payment terms offered, and how promptly customers actually pay.",
        "watch": "Growing faster than revenue means either customers are slower to pay or terms were loosened to close sales. Both bring the cash further out."},
    "Inventory": {
        "what": "Raw materials, work in progress and finished goods not yet sold.",
        "drivers": "Production plans, demand forecasts and supply-chain lead times.",
        "watch": "Rising faster than revenue is the classic early signal of demand coming in below plan, and it usually ends in discounting that shows up in gross margin two quarters later."},
    "Current Assets": {
        "what": "Everything expected to convert to cash within a year.",
        "drivers": "Cash, receivables and inventory.",
        "watch": "Against current liabilities this is the liquidity question: can the next twelve months of obligations be met from the next twelve months of assets."},
    "Net PPE": {
        "what": "Property, plant and equipment after accumulated depreciation — the physical asset base.",
        "drivers": "Capital expenditure less depreciation, plus acquisitions and disposals.",
        "watch": "Shrinking net PPE while revenue grows means the asset base is being run harder, which raises returns until maintenance can no longer be deferred."},
    "Goodwill": {
        "what": "The premium paid for acquisitions over the fair value of the identifiable assets bought.",
        "drivers": "Acquisition activity and prices paid.",
        "watch": "It is never a source of cash. Large goodwill relative to equity means an impairment could wipe out a big share of book value without any cash changing hands."},
    "Total Assets": {
        "what": "Everything the company owns or controls, at carrying value.",
        "drivers": "Retained profits, borrowing, share issuance and acquisitions.",
        "watch": "Assets growing faster than revenue means each unit of assets is producing less — falling asset turnover, and the second term of the DuPont breakdown in section 1."},
    "Accounts Payable": {
        "what": "Money owed to suppliers for goods and services already received.",
        "drivers": "Purchase volumes and the payment terms suppliers grant.",
        "watch": "Stretching payables is a cheap source of funding until suppliers push back. A sudden fall can quietly consume a quarter's cash flow."},
    "Current Debt": {
        "what": "Borrowings falling due within twelve months, including the current portion of longer-term debt.",
        "drivers": "The maturity schedule and short-term facility use.",
        "watch": "This is the refinancing risk. Large near-term maturities alongside thin cash means the company must go to the market on the market's terms."},
    "Current Liabilities": {
        "what": "All obligations due within a year.",
        "drivers": "Payables, short-term debt, accrued costs and deferred revenue.",
        "watch": "Deferred revenue inside this line is a good liability — customers who have already paid — and worth separating from the rest."},
    "Long Term Debt": {
        "what": "Borrowings due beyond twelve months.",
        "drivers": "Issuance, repayment and refinancing decisions.",
        "watch": "The level matters less than the cost and the maturity wall. Cheap long-dated debt is an asset; expensive debt maturing soon is a problem."},
    "Total Liabilities Net Minority Interest": {
        "what": "Everything owed to anyone other than shareholders.",
        "drivers": "Debt, payables, provisions, leases and deferred tax.",
        "watch": "Against total assets this gives the plain leverage picture, without the definitional arguments about what counts as debt."},
    "Retained Earnings": {
        "what": "Cumulative profit kept in the business rather than paid out, since inception.",
        "drivers": "Net income less dividends, plus accounting adjustments.",
        "watch": "A negative balance means the company has lost more over its life than it has earned, or has returned more than it made."},
    "Stockholders Equity": {
        "what": "The shareholders' residual claim: total assets less total liabilities. Book value.",
        "drivers": "Retained profit, share issuance and buybacks.",
        "watch": "Buybacks reduce equity, which mechanically raises return on equity without any operational improvement. Cross-check against return on assets."},

    "Operating Cash Flow": {
        "what": "Cash generated by trading, after working capital movements and before investment.",
        "drivers": "Profit, non-cash charges added back, and swings in receivables, inventory and payables.",
        "watch": "The single hardest figure to manipulate, and the reason section 4 compares it against net income."},
    "Depreciation And Amortization": {
        "what": "The accounting cost of using up long-lived assets, spread over their useful life. No cash leaves the business.",
        "drivers": "The asset base and the depreciation policy applied to it.",
        "watch": "Persistently below capital expenditure means the asset base is growing; persistently above means it is shrinking and today's earnings are borrowing from tomorrow's capacity."},
    "Stock Based Compensation": {
        "what": "The value of shares and options granted to employees, expensed but paid in equity rather than cash.",
        "drivers": "Headcount, grant policy and the share price at grant.",
        "watch": "Added back in cash flow because no cash moved, but it is a genuine cost to existing holders — it shows up as dilution in the share count instead."},
    "Change In Working Capital": {
        "what": "Cash absorbed or released by movements in receivables, inventory and payables.",
        "drivers": "Growth rate, seasonality, and payment discipline on both sides.",
        "watch": "Growing companies normally absorb working capital; a large release can flatter one period's cash flow and cannot repeat indefinitely."},
    "Capital Expenditure": {
        "what": "Cash spent on property, plant, equipment and other long-lived assets. Reported as a negative figure.",
        "drivers": "Maintenance needs plus growth projects.",
        "watch": "Splitting maintenance from growth capex is the key judgement in any valuation, and companies rarely disclose it. Depreciation is a rough proxy for the maintenance half."},
    "Free Cash Flow": {
        "what": "Operating cash flow less capital expenditure: the cash genuinely available to lenders and owners.",
        "drivers": "Everything in the operating and investing sections.",
        "watch": "This is what the DCF in section 5 discounts. One unusual year should not anchor a valuation, which is why the model offers a normalised median instead."},
    "Cash Dividends Paid": {
        "what": "Cash actually paid out to shareholders during the period.",
        "drivers": "The declared dividend per share and the share count.",
        "watch": "Against free cash flow this is the dividend safety test, and a far better one than the earnings-based payout ratio."},
    "Repurchase Of Capital Stock": {
        "what": "Cash spent buying back the company's own shares.",
        "drivers": "Board authorisation, spare cash and the share price.",
        "watch": "Buybacks funded by debt at a high valuation destroy value as reliably as they create it when done cheaply. Check the share count actually fell — many buybacks only offset the shares issued to employees."},
    "Net Issuance Payments Of Debt": {
        "what": "Net cash raised from, or repaid to, lenders.",
        "drivers": "Financing needs and refinancing schedules.",
        "watch": "Positive year after year alongside negative free cash flow means the business is being funded by lenders rather than by customers."},
}

# Typical cost structure by sector. Filings differ in how much they break out, so
# this states what usually sits inside these lines for a company of this type
# rather than inventing a breakdown the data source does not provide.
SECTOR_COST_NOTES = {
    "Technology": {
        "cogs": "hosting and data-centre capacity, third-party licences, hardware components and contract manufacturing, plus support staff attached to delivery",
        "opex": "engineering salaries inside research and development, with sales commissions and marketing making up most of the selling cost"},
    "Consumer Cyclical": {
        "cogs": "raw materials, contract manufacturing, inbound freight and warehousing, plus store or fulfilment labour where retail is involved",
        "opex": "store or platform operating costs, advertising, and distribution"},
    "Consumer Defensive": {
        "cogs": "agricultural and packaging inputs, plant labour, energy and distribution",
        "opex": "trade marketing and promotional spend, often as large a swing factor as input costs"},
    "Healthcare": {
        "cogs": "manufacturing of compounds or devices, quality control, and royalties on licensed intellectual property",
        "opex": "clinical trial costs inside research and development, and a large specialised sales force"},
    "Financial Services": {
        "cogs": "interest paid to depositors and lenders, and credit losses — the revenue line itself is interest and fee income, so conventional margin analysis does not transfer",
        "opex": "compensation, technology and regulatory compliance"},
    "Energy": {
        "cogs": "extraction, refining and transport costs, plus depletion of reserves",
        "opex": "field administration and exploration costs written off"},
    "Industrials": {
        "cogs": "steel and component inputs, factory labour, energy and freight",
        "opex": "engineering, aftermarket service networks and distribution"},
    "Basic Materials": {
        "cogs": "ore, feedstock and energy, which together usually dominate the cost base and make margins swing with commodity prices",
        "opex": "logistics and site administration"},
    "Communication Services": {
        "cogs": "content licensing and production, network capacity and interconnect fees",
        "opex": "subscriber acquisition marketing and platform engineering"},
    "Utilities": {
        "cogs": "fuel and purchased power, and network maintenance",
        "opex": "regulatory compliance and customer service"},
    "Real Estate": {
        "cogs": "property operating costs, maintenance and property taxes",
        "opex": "leasing commissions and corporate administration"},
}


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


# The metrics a healthy quote response carries. When most of them are absent the
# quote endpoint has effectively failed, and the app rebuilds them from the
# financial statements rather than showing a page of dashes.
QUOTE_METRICS = ("marketCap", "trailingPE", "returnOnEquity", "operatingMargins",
                 "currentRatio", "totalRevenue", "freeCashflow", "ebitda",
                 "sharesOutstanding", "bookValue", "trailingEps", "profitMargins")

FAST_INFO_MAP = {
    "currentPrice": "last_price", "previousClose": "previous_close",
    "marketCap": "market_cap", "sharesOutstanding": "shares",
    "fiftyTwoWeekHigh": "year_high", "fiftyTwoWeekLow": "year_low",
    "fiftyDayAverage": "fifty_day_average",
    "twoHundredDayAverage": "two_hundred_day_average",
}


class Company:
    """A thin, lazy facade over the cached loaders. Constructing one costs
    nothing; each statement is fetched the first time it is actually read.

    `info` is not the raw quote response. Yahoo's quote endpoint is rate-limited
    per source address and regularly returns almost nothing when the app runs on
    shared cloud infrastructure, while the statement and price endpoints keep
    answering. So the raw response is topped up from the lightweight quote
    endpoint and, when it is still threadbare, from the financial statements
    themselves. Anything filled in this way is recorded in `derived`, and the
    page says so rather than passing a computed figure off as reported."""

    def __init__(self, ticker: str):
        self.ticker = (ticker or "").upper().strip()
        self._raw = load_info(self.ticker) if self.ticker else {}
        self._fast = load_fast_info(self.ticker) if self.ticker else {}
        self.derived = set()

    # -- quote assembly ------------------------------------------------------
    def _base_price(self):
        """Price without touching `info`, so the enrichment below can use it
        without recursing back into the property it is building."""
        for source in (self._raw, self._fast):
            for key in ("currentPrice", "regularMarketPrice", "previousClose",
                        "last_price", "previous_close"):
                v = source.get(key)
                if _isnum(v) and v > 0:
                    return float(v)
        h = load_history(self.ticker, "5d", "1d")
        if not h.empty and "Close" in h:
            series = h["Close"].dropna()
            if not series.empty:
                return float(series.iloc[-1])
        backup = _stooq_history(self.ticker)
        if not backup.empty and "Close" in backup:
            series = backup["Close"].dropna()
            if not series.empty:
                note_source("price", "Stooq")
                return float(series.iloc[-1])
        return None

    @cached_property
    def info(self):
        merged = dict(self._raw)
        for key, fast_key in FAST_INFO_MAP.items():
            if not _isnum(merged.get(key)) and _isnum(self._fast.get(fast_key)):
                merged[key] = float(self._fast[fast_key])
                self.derived.add(key)
        if not merged.get("currency") and self._fast.get("currency"):
            merged["currency"] = self._fast["currency"]
        self.quote_fields = sum(1 for k in QUOTE_METRICS if _isnum(merged.get(k)))
        if self.quote_fields < 6:
            merged = self._rebuild_from_statements(merged)
        return merged

    def _rebuild_from_statements(self, merged: dict) -> dict:
        """Recomputes the headline metrics from the reported statements.

        Every value written here is the textbook definition applied to the
        company's own filings, so it is a reconstruction of the same number the
        quote endpoint would have returned — not an estimate of something else."""
        inc, bs, cf = self.annual["inc"], self.annual["bs"], self.annual["cf"]
        price = self._base_price()

        def put(key, value):
            if _isnum(value) and not _isnum(merged.get(key)):
                merged[key] = float(value)
                self.derived.add(key)

        def latest(df, *names):
            for n in names:
                if isinstance(df, pd.DataFrame) and n in df.columns:
                    series = df[n].dropna()
                    if not series.empty:
                        return float(series.iloc[-1])
            return None

        def prior(df, *names):
            for n in names:
                if isinstance(df, pd.DataFrame) and n in df.columns:
                    series = df[n].dropna()
                    if len(series) >= 2:
                        return float(series.iloc[-2])
            return None

        shares = merged.get("sharesOutstanding")
        if not _isnum(shares):
            shares = (latest(bs, "Ordinary Shares Number", "Share Issued")
                      or latest(inc, "Diluted Average Shares", "Basic Average Shares"))
            put("sharesOutstanding", shares)
        mcap = merged.get("marketCap")
        if not _isnum(mcap) and _isnum(price) and _isnum(shares):
            mcap = price * shares
            put("marketCap", mcap)

        revenue = latest(inc, "Total Revenue")
        net_income = latest(inc, "Net Income")
        gross = latest(inc, "Gross Profit")
        op_income = latest(inc, "Operating Income", "EBIT")
        ebitda = latest(inc, "EBITDA")
        d_and_a = latest(cf, "Depreciation And Amortization")
        if not _isnum(ebitda) and _isnum(op_income):
            ebitda = op_income + (d_and_a if _isnum(d_and_a) else 0.0)
        equity = latest(bs, "Stockholders Equity")
        assets = latest(bs, "Total Assets")
        debt = latest(bs, "Total Debt")
        if not _isnum(debt):
            lt, st_ = latest(bs, "Long Term Debt"), latest(bs, "Current Debt")
            debt = (lt if _isnum(lt) else 0.0) + (st_ if _isnum(st_) else 0.0) or None
        cash = latest(bs, "Cash And Cash Equivalents")
        cur_assets, cur_liab = latest(bs, "Current Assets"), latest(bs, "Current Liabilities")
        eps = latest(inc, "Diluted EPS", "Basic EPS")
        if not _isnum(eps) and _isnum(net_income) and _isnum(shares) and shares:
            eps = net_income / shares
        fcf = latest(cf, "Free Cash Flow")
        if not _isnum(fcf):
            ocf, capex = latest(cf, "Operating Cash Flow"), latest(cf, "Capital Expenditure")
            if _isnum(ocf):
                fcf = ocf + (capex if _isnum(capex) else 0.0)

        put("totalRevenue", revenue)
        put("ebitda", ebitda)
        put("totalDebt", debt)
        put("totalCash", cash)
        put("freeCashflow", fcf)
        put("trailingEps", eps)
        put("grossMargins", safe_div(gross, revenue))
        put("operatingMargins", safe_div(op_income, revenue))
        put("profitMargins", safe_div(net_income, revenue))
        put("returnOnEquity", safe_div(net_income, equity))
        put("returnOnAssets", safe_div(net_income, assets))
        put("currentRatio", safe_div(cur_assets, cur_liab))
        put("bookValue", safe_div(equity, shares))
        de = safe_div(debt, equity)
        put("debtToEquity", de * 100 if de is not None else None)   # reported as a percentage
        put("trailingPE", safe_div(price, eps) if _isnum(eps) and eps > 0 else None)
        put("priceToBook", safe_div(price, safe_div(equity, shares)))
        put("priceToSalesTrailing12Months", safe_div(mcap, revenue))
        if _isnum(mcap):
            ev = mcap + (debt if _isnum(debt) else 0.0) - (cash if _isnum(cash) else 0.0)
            put("enterpriseValue", ev)
            put("enterpriseToEbitda", safe_div(ev, ebitda))
            put("enterpriseToRevenue", safe_div(ev, revenue))
        prev_rev, prev_ni = prior(inc, "Total Revenue"), prior(inc, "Net Income")
        if _isnum(prev_rev) and prev_rev > 0 and _isnum(revenue):
            put("revenueGrowth", revenue / prev_rev - 1)
        if _isnum(prev_ni) and prev_ni > 0 and _isnum(net_income):
            put("earningsGrowth", net_income / prev_ni - 1)
        if not _isnum(merged.get("beta")):
            put("beta", estimate_beta(self.ticker))
        return merged

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
        """Total debt less cash, always a real number.

        Every branch is filtered through `_isnum` because a NaN coming out of a
        sparse balance sheet is truthy: `nan or 0` returns nan, and every
        downstream comparison against it then quietly evaluates false."""
        debt, cash = self.info.get("totalDebt"), self.info.get("totalCash")
        if _isnum(debt) or _isnum(cash):
            return (debt if _isnum(debt) else 0.0) - (cash if _isnum(cash) else 0.0)
        if not self.bs.empty:
            row = self.bs.iloc[-1]
            d, c = row.get("Total Debt"), row.get("Cash And Cash Equivalents")
            return (d if _isnum(d) else 0.0) - (c if _isnum(c) else 0.0)
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
    def dividend_history(self):
        """Per-share dividends actually paid, from the price history's own
        actions column. Returns an empty series when the source omits it."""
        h = self.history("5y", "1d")
        if h is None or h.empty or "Dividends" not in h.columns:
            return pd.Series(dtype="float64")
        s = h["Dividends"]
        return s[s > 0]

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


# --- Forecasting -------------------------------------------------------------

def build_forecast(close: pd.Series, horizon: int = 60):
    """Three independent forward projections of a price series.

    They are deliberately different in kind, because agreement between methods
    that share no assumptions is the only weak evidence a price forecast can
    offer, and disagreement is the honest signal that the future is open:

      * a log-linear trend fitted to the whole window, with a statistical
        prediction interval — the "if the last N days continue" case;
      * Holt's damped linear trend, which weights recent observations far more
        heavily and lets the trend decay rather than extrapolate forever;
      * a geometric random walk cone built from the series' own drift and
        volatility, which describes the range rather than a path.
    """
    close = close.dropna()
    if len(close) < 30 or horizon < 1:
        return None
    y = np.log(close.values.astype(float))
    n = len(y)
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    sigma = float(resid.std(ddof=2)) if n > 2 else float(resid.std())
    sxx = float(((x - x.mean()) ** 2).sum()) or 1.0

    future_x = np.arange(n, n + horizon, dtype=float)
    trend = np.exp(slope * future_x + intercept)
    se = sigma * np.sqrt(1.0 + 1.0 / n + ((future_x - x.mean()) ** 2) / sxx)
    trend_lo, trend_hi = np.exp(np.log(trend) - 1.96 * se), np.exp(np.log(trend) + 1.96 * se)

    holt_path = None
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        fit = ExponentialSmoothing(close.values.astype(float), trend="add",
                                   damped_trend=True, initialization_method="estimated").fit()
        holt_path = np.asarray(fit.forecast(horizon), dtype=float)
    except Exception:
        holt_path = None

    log_ret = np.diff(y)
    mu, sd = float(log_ret.mean()), float(log_ret.std())
    steps = np.arange(1, horizon + 1, dtype=float)
    last = float(close.iloc[-1])
    mc_mid = last * np.exp(mu * steps)
    mc_lo = last * np.exp(mu * steps - 1.645 * sd * np.sqrt(steps))
    mc_hi = last * np.exp(mu * steps + 1.645 * sd * np.sqrt(steps))

    last_date = pd.Timestamp(close.index[-1])
    future_index = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=horizon)
    out = pd.DataFrame({"Trend": trend, "Trend low": trend_lo, "Trend high": trend_hi,
                        "Random-walk median": mc_mid, "Random-walk 5%": mc_lo,
                        "Random-walk 95%": mc_hi}, index=future_index)
    if holt_path is not None and len(holt_path) == horizon:
        out["Damped trend"] = holt_path
    out.attrs["annual_drift"] = float(np.expm1(mu * 252))
    out.attrs["annual_vol"] = float(sd * np.sqrt(252))
    out.attrs["r_squared"] = float(1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()) if n > 2 else None
    return out


def detect_shocks(close: pd.Series, z_threshold: float = 2.5, max_events: int = 8):
    """Days whose move is a statistical outlier for this series.

    Picked by standardised return rather than a fixed percentage, so the
    threshold adapts to how volatile the stock actually is: a 4% day is
    unremarkable for one name and a shock for another."""
    close = close.dropna()
    if len(close) < 40:
        return pd.DataFrame()
    ret = close.pct_change().dropna()
    sd = ret.std()
    if not sd:
        return pd.DataFrame()
    z = (ret - ret.mean()) / sd
    hits = z[z.abs() >= z_threshold]
    if hits.empty:
        return pd.DataFrame()
    frame = pd.DataFrame({"Move %": ret.loc[hits.index] * 100, "Sigma": hits})
    frame = frame.reindex(frame["Sigma"].abs().sort_values(ascending=False).index).head(max_events)
    return frame.sort_index()


# --- Portfolio return engines ------------------------------------------------

def xirr(cashflows):
    """Money-weighted (internal) rate of return over dated cash flows.

    Signs follow the investor's perspective: money paid in is negative, the
    closing value is positive. Solved by bisection rather than Newton's method,
    which diverges on the irregular flows a real portfolio produces."""
    flows = sorted([(pd.Timestamp(d), float(a)) for d, a in cashflows if _isnum(a)], key=lambda x: x[0])
    if len(flows) < 2:
        return None
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = flows[0][0]

    def npv(rate):
        return sum(a / ((1 + rate) ** ((d - t0).days / 365.0)) for d, a in flows)

    lo, hi = -0.95, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_mid == 0:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def twrr(values: pd.Series, flows: pd.Series):
    """Time-weighted return: each day's return is measured after removing the
    money that arrived that day, then the daily returns are chained. This
    isolates how the assets performed from when cash happened to be added,
    which is what makes it comparable with an index."""
    if values is None or values.empty:
        return None
    v = values.astype(float)
    c = flows.reindex(v.index).fillna(0.0).astype(float)
    prev = v.shift()
    daily = (v - c) / prev.replace(0, np.nan) - 1
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna()
    # A long-only portfolio cannot lose more than everything in a single day;
    # anything beyond that is a data artefact, not a return.
    daily = daily[(daily > -1) & (daily < 5)]
    if daily.empty:
        return None
    return float((1 + daily).prod() - 1)


@st.cache_data(ttl=900, show_spinner=False)
def load_portfolio_history(holdings: tuple, target_currency: str):
    """Daily value of a set of holdings, plus two dated flow series.

    `holdings` is a tuple of (ticker, shares, cost_per_share, purchase_date_iso)
    so the whole computation is cacheable. Prices come from one bulk download;
    currencies are resolved once per distinct currency rather than per holding.

    Two flow series are returned because the two return measures need different
    ones. Time-weighted return needs the *market value* the position added on
    the day it entered, otherwise the difference between the entry price and the
    cost basis the user typed shows up as a fake return. Money-weighted return
    needs the *cash actually paid*, which is the point of the measure.
    """
    empty = (pd.DataFrame(), pd.Series(dtype="float64"),
             pd.Series(dtype="float64"), pd.Series(dtype="float64"))
    if not holdings:
        return empty

    tickers = tuple(dict.fromkeys(h[0] for h in holdings))
    first = min(pd.Timestamp(h[3]) for h in holdings).date()
    closes = load_batch_close(tickers, first - timedelta(days=7), datetime.now().date() + timedelta(days=1))
    if closes.empty:
        return empty
    closes = closes.ffill()
    closes.index = pd.to_datetime(closes.index).tz_localize(None)

    infos = dict(zip(tickers, parallel_map(_fetch_info, tickers)))
    fx_map = {}
    for t in tickers:
        cur = (infos.get(t) or {}).get("currency", "USD")
        if cur not in fx_map:
            fx_map[cur] = load_fx(cur, target_currency) or 1.0

    per_ticker = pd.DataFrame(0.0, index=closes.index, columns=list(tickers))
    flows_market = pd.Series(0.0, index=closes.index)
    flows_cash = pd.Series(0.0, index=closes.index)
    for ticker, shares, cost, bought in holdings:
        if ticker not in closes.columns:
            continue
        rate = fx_map.get((infos.get(ticker) or {}).get("currency", "USD"), 1.0)
        pos = closes.index.searchsorted(pd.Timestamp(bought))
        buy_day = closes.index[min(pos, len(closes.index) - 1)]
        entry_price = float(closes.loc[buy_day, ticker])
        if not _isnum(entry_price) or entry_price <= 0:
            continue
        held = pd.Series(0.0, index=closes.index)
        held.loc[held.index >= buy_day] = float(shares)
        per_ticker[ticker] = per_ticker[ticker] + held * closes[ticker] * rate
        flows_market.loc[buy_day] += float(shares) * entry_price * rate
        paid = float(cost) if _isnum(cost) and cost > 0 else entry_price
        flows_cash.loc[buy_day] += float(shares) * paid * rate
    return per_ticker, per_ticker.sum(axis=1), flows_market, flows_cash


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
    ("Guide & Method", "How the terminal is put together and when to use each module."),
    ("Executive Dashboard", "One screen: composite score, valuation, profitability, health, dividends, quality flags."),
    ("Technical Analysis", "Price action, trend, momentum and volatility."),
    ("Financial Statements", "Reported figures, line-by-line explanations and industry-relative common size."),
    ("Cash Flow Quality", "Whether reported profit actually converts into cash."),
    ("Capital Allocation", "Return on invested capital against the cost of it, and where the cash went."),
    ("Solvency & Debt", "Maturity profile, leverage, interest cover and a refinancing stress test."),
    ("Dilution & Owner Earnings", "Share-count creep and free cash flow after the cost of paying people in stock."),
    ("Intrinsic Valuation", "Three-phase DCF, reverse DCF, scenarios and sensitivity."),
    ("Peer Comparables", "Relative valuation against live-matched industry peers."),
    ("Compare Companies", "Two or more companies side by side on price, quality, valuation and growth."),
    ("Risk & Scenarios", "Volatility, drawdown, value at risk and Monte Carlo paths."),
    ("Investment Simulator", "What an investment made on a past date would be worth today."),
    ("Portfolio", "Allocation against targets, concentration limits, TWRR and money-weighted return."),
    ("Price & Capital Dynamics", "Price, market cap, news context and the EV bridge."),
    ("Market Leaders", "Cross-company ranking by market cap and revenue."),
]
MODULE_LABELS = [f"{i:02d}. {name}" for i, (name, _) in enumerate(MODULES)]
LABEL_BY_NAME = dict(zip([n for n, _ in MODULES], MODULE_LABELS))
NAME_BY_LABEL = dict(zip(MODULE_LABELS, [n for n, _ in MODULES]))
MODULE_HELP = {f"{i:02d}. {n}": h for i, (n, h) in enumerate(MODULES)}


# Built from the exchange map, so every venue yfinance can reach is selectable.
_MARKET_ORDER = ["", "VN", "DE", "L", "T", "HK", "SS", "SZ", "TW", "KS", "NS", "SI",
                 "AX", "TO", "SW", "PA", "AS", "MI", "MC", "ST", "OL", "CO", "HE",
                 "BR", "IR", "VI", "LS", "WA", "IS", "TA", "SR", "SA", "MX", "BK",
                 "JK", "KL", "PS", "AT", "NZ", "JO", "BO", "KQ", "TWO", "F", "V"]
MARKETS = {EXCHANGE_LABELS[k]: (f".{k}" if k else "") for k in _MARKET_ORDER if k in EXCHANGE_LABELS}
MARKETS["Other / enter full symbol"] = "MANUAL"
SUFFIX_TO_MARKET = {v: k for k, v in MARKETS.items() if v != "MANUAL"}

PERIODS = {"5 days": "5d", "1 month": "1mo", "3 months": "3mo", "6 months": "6mo",
           "Year to date": "ytd", "1 year": "1y", "3 years": "3y", "5 years": "5y",
           "10 years": "10y", "Maximum": "max"}
INTERVALS = {"5d": "15m", "1mo": "60m", "3mo": "1d", "6mo": "1d", "ytd": "1d",
             "1y": "1d", "3y": "1wk", "5y": "1wk", "10y": "1mo", "max": "1mo"}

st.session_state[_LOAD_ERRORS_KEY] = []
st.session_state[SOURCE_LOG_KEY] = {}


def monogram(name: str) -> str:
    """Initials tile used in place of a remote logo lookup. Third-party logo
    services fail often enough (and add a blocking request) that a rendered
    monogram is both faster and more reliable."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]
    return ("".join(w[0] for w in words[:2]) or "?").upper()


with st.sidebar:
    st.markdown(f"<div class='side-brand'>{APP_NAME}</div>"
                f"<div class='side-sub'>{APP_TAGLINE}</div>", unsafe_allow_html=True)

    st.markdown("<div class='side-group'>Company</div>", unsafe_allow_html=True)
    with st.expander("Search by company name", expanded=False):
        q = st.text_input("Company name", placeholder="Siemens, Toyota, Vietcombank…",
                          key="name_search_query", label_visibility="collapsed")
        if q.strip():
            with st.spinner("Searching every market…"):
                results = search_ticker(q)
            if results:
                def _fmt(r):
                    venue = r["exchange"] or market_label(r["symbol"])
                    return f"{r['symbol']} · {r['name']} ({venue})"
                opts = {_fmt(r): r["symbol"] for r in results}
                picked = st.selectbox("Match", list(opts.keys()), key="name_search_pick",
                                      label_visibility="collapsed")
                if st.button("Use this ticker", type="primary", **FILL_BTN):
                    sym = opts[picked]
                    suffix = f".{sym.split('.')[-1]}" if "." in sym else ""
                    st.session_state["market_select"] = SUFFIX_TO_MARKET.get(suffix, "Other / enter full symbol")
                    st.session_state["ticker_symbol_input"] = sym
                    st.rerun()
            else:
                st.caption("Nothing came back for that. Yahoo's search routes are rate-limited from shared "
                           "hosting and sometimes return nothing for a company that does exist — try again, "
                           "or type the symbol with its market suffix directly (Vinamilk is VNM.VN, "
                           "Siemens is SIE.DE, Toyota is 7203.T).")
        st.caption("Searched live across four Yahoo routes covering every listed market. No company list is "
                   "bundled with this app, so renames, new listings and delistings are picked up immediately.")

    market = st.selectbox("Market", list(MARKETS.keys()), key="market_select")
    suffix = MARKETS[market]
    symbol = st.text_input("Ticker symbol", key="ticker_symbol_input",
                           help="A symbol that already carries an exchange suffix (7203.T) overrides the market above.").upper().strip()
    ticker = symbol if (suffix == "MANUAL" or "." in symbol) else f"{symbol}{suffix}"

    st.markdown("<div class='side-group'>View</div>", unsafe_allow_html=True)
    # A visible list rather than a dropdown: the whole map of the terminal stays
    # on screen, so switching view is one click and the reader can see what else
    # is available without opening anything.
    module = st.radio("Module", MODULE_LABELS, key="module", label_visibility="collapsed")
    view = NAME_BY_LABEL[module]
    st.caption(MODULE_HELP[module])

    st.markdown("<div class='side-group'>Reporting basis</div>", unsafe_allow_html=True)
    period_label = st.selectbox("Chart period", list(PERIODS.keys()), index=5)
    period = PERIODS[period_label]
    interval = INTERVALS.get(period, "1d")
    basis = segmented("Statement basis", ["Annual", "Quarterly", "TTM"], key="basis_sel", default_index=0,
                      help="Annual and quarterly are as reported; TTM sums the last four reported quarters.")
    currency_mode = st.selectbox("Display currency", ["Native", "USD", "EUR", "VND", "GBP", "JPY"], index=0)

    st.markdown("<div class='side-group'>Presentation</div>", unsafe_allow_html=True)
    st.selectbox("Theme", list(THEMES.keys()), key="theme")
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
if view == "Guide & Method":
    st.markdown(f"<div class='eyebrow'>{APP_NAME}</div>"
                f"<div class='hdr-name'>Guide &amp; method</div>"
                f"<div class='hdr-meta'>What each module answers, how the numbers are built, and what the "
                f"figures assume. Nothing on this page loads market data.</div>", unsafe_allow_html=True)

    section("Modules", "Pick the module that matches the question you are actually asking.")
    for idx, (name, purpose) in enumerate(MODULES[1:], start=1):
        st.markdown(f"<div class='card'><div class='card-title'>"
                    f"<span class='section-num'>{idx:02d}</span> &nbsp;{name}</div>"
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
<b>Data.</b> The primary source is Yahoo Finance, which rate-limits by source address — so two independent
backups stand behind it, neither needing an API key. <b>Stooq</b> supplies daily price history for most
developed markets when Yahoo's price endpoint is throttled. <b>SEC EDGAR's XBRL company-facts API</b> supplies
the statements themselves, straight from the regulator, for companies that file in the United States. When
even the quote endpoint is empty, the headline metrics are recomputed from those statements, and the page says
which figures were computed rather than quoted. Whichever source answered is named in the provenance panel at
the foot of every view. All of it can still contain gaps, restatements and classification quirks, particularly
outside the United States — verify against the primary filing before anything consequential rests on a number.
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
    lg, txt = st.columns([1, 9], vertical_alignment="center")
    with lg:
        st.markdown(f"<div class='monogram' style='background:{T['neu_bg']};color:{T['accent']}'>"
                    f"{monogram(co.name)}</div>", unsafe_allow_html=True)
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

# Say plainly when the quote endpoint came back thin and the headline metrics
# had to be rebuilt, rather than presenting computed figures as reported ones.
quote_fields = getattr(co, "quote_fields", len(QUOTE_METRICS))
if co.derived:
    rebuilt = ", ".join(sorted(co.derived)[:8]) + ("…" if len(co.derived) > 8 else "")
    if quote_fields < 6:
        st.info(
            f"Yahoo's quote endpoint returned only {quote_fields} of "
            f"{len(QUOTE_METRICS)} headline metrics for {co.ticker} — usually rate limiting, which hits "
            f"shared cloud hosts hardest. The figures below were recomputed from the company's own "
            f"reported statements and price history instead ({len(co.derived)} fields: {rebuilt}). "
            f"They follow the standard definitions, but they are calculated here rather than quoted. "
            f"Use *Refresh market data* in the sidebar to try the quote endpoint again.")
    else:
        st.caption(f"{len(co.derived)} metric(s) were not quoted and have been computed from the reported "
                   f"statements: {rebuilt}.")


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

if view == "Executive Dashboard":
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
{co.sector} sector, capitalised at **{Fmt.money(conv(co.market_cap, fx), sym)}** and trading at
**{Fmt.price((co.price or 0) * fx, sym)}**.
- **What the market pays.** {'A trailing P/E of ' + Fmt.ratio(pe) if _isnum(pe) and pe > 0 else 'Earnings are negative or unreported, so P/E is not meaningful'}
{' and a free cash flow yield of ' + Fmt.as_pct(fcf_yield) if fcf_yield is not None else ''}.
{'The shares sit ' + Fmt.as_pct(extras.get('vs_sma200'), signed=True) + ' versus their 200-day average' if extras.get('vs_sma200') is not None else ''}
{' and ' + f"{extras['range_pos']*100:.0f}% of the way up the 52-week range" if extras.get('range_pos') is not None else ''}.
- **What the business earns.** Return on equity of {Fmt.as_pct(info.get('returnOnEquity'))} on operating
margins of {Fmt.as_pct(info.get('operatingMargins'))}{', with revenue compounding at ' + Fmt.as_pct(rev_cagr) + ' over the reported history' if rev_cagr is not None else ''}.
- **How it is financed.** {'Debt to equity of ' + Fmt.ratio(de) if de is not None else 'Leverage is unreported'}
with a current ratio of {Fmt.ratio(info.get('currentRatio'))} and a net {'debt' if co.net_debt >= 0 else 'cash'}
position of {Fmt.money(conv(abs(co.net_debt), fx), sym)}.
- **Where to look next.** {'Strongest pillar: **' + strongest.name + f'** ({strongest.score:.0f}/100). ' if strongest else ''}
{'Weakest: **' + weakest.name + f'** ({weakest.score:.0f}/100) — start there.' if weakest else ''}
""", tone="pos" if (total or 0) >= 65 else "warn" if (total or 0) >= 40 else "neg",
             title="What the numbers say")

    # --- Headline KPI strip ---------------------------------------------------
    ev = info.get("enterpriseValue")
    fcf_yield = safe_div(co.base_fcf, co.market_cap)
    div_facts = dividend_facts(info, co.price)
    div_y = div_facts["yield"]
    nd_ebitda = safe_div(co.net_debt, info.get("ebitda"))
    kpi_grid([
        {"label": "Market cap", "value": Fmt.money(conv(co.market_cap, fx), sym),
         "sub": f"Enterprise value {Fmt.money(conv(ev, fx), sym)}", "tone": "flat",
         "help": "Share price times shares outstanding: the value of the equity alone."},
        {"label": "Trailing P/E", "value": Fmt.ratio(info.get("trailingPE")),
         "sub": f"Forward {Fmt.ratio(info.get('forwardPE'))}",
         "tone": tone_for(info.get("trailingPE"), 18, 35, higher_better=False),
         "help": "Price paid per unit of last year's earnings."},
        {"label": "EV / EBITDA", "value": Fmt.ratio(info.get("enterpriseToEbitda")),
         "sub": "Capital-structure neutral", "tone": tone_for(info.get("enterpriseToEbitda"), 10, 20, higher_better=False),
         "help": "Enterprise value against cash operating earnings; comparable across different debt levels."},
        {"label": "FCF yield", "value": Fmt.as_pct(fcf_yield),
         "sub": f"FCF {Fmt.money(conv(co.base_fcf, fx), sym)}",
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
         "sub": (f"Ex-dividend {Fmt.date(div_facts['ex_date'])}" if div_facts["ex_date"]
                 else f"Payout {Fmt.as_pct(div_facts['payout'])}"), "tone": "flat",
         "help": "Annual dividend per share divided by the current price. Derived from the dividend "
                 "rate rather than the reported yield field, which is inconsistent between data versions."},
    ])

    tabs = st.tabs(["Growth & margins", "Valuation", "Returns", "Balance sheet",
                    "Quality flags", "Dividends", "Profile"])

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
                {"label": "Mean target price", "value": Fmt.price(conv(target, fx), sym),
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

    # -- Dividends ---------------------------------------------------------------
    with tabs[5]:
        cf_div = to_display(co.cf, fx)
        div_paid = abs(last(cf_div, "Cash Dividends Paid") or 0)
        buyback = abs(last(cf_div, "Repurchase Of Capital Stock") or 0)
        fcf_now = (co.base_fcf or 0) * fx
        mcap_now = (co.market_cap or 0) * fx
        buyback_yield = safe_div(buyback, mcap_now)
        total_yield = (div_y or 0) + (buyback_yield or 0)
        cover = safe_div(fcf_now, div_paid) if div_paid else None

        if not _isnum(div_y) and not div_paid:
            empty_state("This company does not currently pay a dividend.",
                        "Retained cash shows up in the balance sheet and, for buybacks, in the "
                        "financing section of the cash flow statement.")
        else:
            kpi_grid([
                {"label": "Dividend yield", "value": Fmt.as_pct(div_y),
                 "sub": f"Five-year average {Fmt.as_pct(div_facts['five_year_avg'])}",
                 "tone": "flat"},
                {"label": "Annual dividend", "value": Fmt.price(conv(div_facts["rate"], fx), sym),
                 "sub": "Per share, most recent annualised rate", "tone": "flat"},
                {"label": "Ex-dividend date", "value": Fmt.date(div_facts["ex_date"]),
                 "sub": "Buy before this date to receive the next payment", "tone": "flat",
                 "help": "On the ex-dividend date the shares trade without the upcoming payment, and the "
                         "price typically opens lower by roughly the dividend amount."},
                {"label": "Next payment", "value": Fmt.date(div_facts["pay_date"]),
                 "sub": "Date the declared dividend is paid", "tone": "flat"},
                {"label": "Payout ratio", "value": Fmt.as_pct(div_facts["payout"]),
                 "sub": "Share of earnings distributed",
                 "tone": tone_for((div_facts["payout"] or 0) * 100 if _isnum(div_facts["payout"]) else None,
                                  60, 90, higher_better=False),
                 "help": "Above roughly 80% of earnings leaves little room to keep paying through a weak year."},
                {"label": "Free cash flow cover", "value": Fmt.ratio(cover),
                 "sub": f"FCF {Fmt.money(fcf_now, sym)} against {Fmt.money(div_paid, sym)} paid",
                 "tone": tone_for(cover, 1.5, 1.0)},
                {"label": "Buyback yield", "value": Fmt.as_pct(buyback_yield),
                 "sub": f"{Fmt.money(buyback, sym)} of stock repurchased", "tone": "flat"},
                {"label": "Total shareholder yield", "value": Fmt.as_pct(total_yield),
                 "sub": "Dividends plus buybacks against market cap", "tone": "flat",
                 "help": "The full cash return to owners; a company with no dividend can still return a lot."},
            ], min_width=200)

            hist_div = co.dividend_history
            if not hist_div.empty:
                per_year = hist_div.groupby(hist_div.index.year).sum() * fx
                figdv = go.Figure(go.Bar(x=[str(y) for y in per_year.index], y=per_year.values,
                                         marker_color=T["accent_soft"], opacity=.85))
                figdv.update_yaxes(title_text=f"Dividends per share ({sym})")
                figdv.update_xaxes(type="category")
                style_fig(figdv, height=300, legend="off")
                figure(figdv, "Dividends paid per share, by year",
                       "Every dividend recorded against the shares, summed by calendar year.",
                       "Look for an unbroken, rising staircase. A **flat** run means the real value of the "
                       "income is being eroded by inflation; a **cut** is the single most reliable signal that "
                       "management sees pressure it has not yet talked about.",
                       "Note that a partial current year will look like a fall simply because not every "
                       "payment has happened yet.",
                       data=per_year.to_frame("Dividend per share"))
            elif div_paid:
                yrs = year_labels(cf_div.index)
                paid = cf_div["Cash Dividends Paid"].abs() if "Cash Dividends Paid" in cf_div.columns else None
                if paid is not None:
                    figdv = go.Figure(go.Bar(x=yrs, y=paid, marker_color=T["accent_soft"], opacity=.85))
                    figdv.update_yaxes(title_text=f"Total dividends paid ({sym})")
                    figdv.update_xaxes(type="category")
                    style_fig(figdv, height=300, legend="off")
                    figure(figdv, "Total cash paid out as dividends",
                           "The cash actually leaving the business as dividends each reported year.",
                           "Rising totals with a flat per-share dividend would mean the share count grew. "
                           "Compare against free cash flow in section 4 to see whether the payment is funded "
                           "by the business or by borrowing.",
                           "This is the company-level view; the per-share view is what an individual holder receives.")

            note(f"""
The shares yield **{Fmt.as_pct(div_y)}**, against a five-year average of {Fmt.as_pct(div_facts['five_year_avg'])},
and the next ex-dividend date on record is **{Fmt.date(div_facts['ex_date'])}**.
- **The ex-dividend date is the one that matters for eligibility.** Buy on or after it and the seller keeps the
upcoming payment. The price typically drops by roughly the dividend on that morning, so buying just before it
is not free income.
- **Cover, not yield, is the safety question.** Free cash flow covers the dividend
{Fmt.ratio(cover)} over, and the payout ratio is {Fmt.as_pct(div_facts['payout'])} of earnings. A high yield
alongside thin cover is usually the market pricing in a cut rather than an opportunity.
- **Buybacks count too.** Adding {Fmt.as_pct(buyback_yield)} of repurchases gives a total shareholder yield of
{Fmt.as_pct(total_yield)}, which is the fairer comparison against a company that returns cash a different way.
""", tone="pos" if (cover or 0) > 1.5 else "warn" if div_paid else "neu")

    # -- Profile ---------------------------------------------------------------
    with tabs[6]:
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
elif view == "Technical Analysis":
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

    # --- Forecast --------------------------------------------------------------
    section("Forecast",
            "Three projections built on different assumptions. Where they agree there is weak evidence; "
            "where they disagree, that spread is the honest answer.")

    fc1, fc2 = st.columns([1, 3])
    with fc1:
        horizon = st.select_slider("Horizon (trading days)", [20, 40, 60, 120, 250], value=60,
                                   format_func=lambda d: {20: "1 month", 40: "2 months", 60: "3 months",
                                                          120: "6 months", 250: "1 year"}[d])
    fc = build_forecast(hist["Close"], int(horizon))
    if fc is None:
        empty_state("Not enough price history in this window to fit a forecast.",
                    "Choose a longer chart period in the sidebar.")
    else:
        tail = hist["Close"].dropna().tail(180)
        figf = go.Figure()
        figf.add_trace(go.Scatter(x=np.concatenate([fc.index, fc.index[::-1]]),
                                  y=np.concatenate([fc["Random-walk 95%"], fc["Random-walk 5%"][::-1]]),
                                  fill="toself", fillcolor="rgba(99,102,241,0.12)", line=dict(width=0),
                                  name="Random walk, 90% range", hoverinfo="skip"))
        figf.add_trace(go.Scatter(x=np.concatenate([fc.index, fc.index[::-1]]),
                                  y=np.concatenate([fc["Trend high"], fc["Trend low"][::-1]]),
                                  fill="toself", fillcolor="rgba(148,163,184,0.14)", line=dict(width=0),
                                  name="Trend, 95% interval", hoverinfo="skip"))
        figf.add_trace(go.Scatter(x=tail.index, y=tail, name="Actual",
                                  line=dict(color=T["text"], width=2.2)))
        figf.add_trace(go.Scatter(x=fc.index, y=fc["Trend"], name="Log-linear trend",
                                  line=dict(color=T["accent"], width=2, dash="dash")))
        if "Damped trend" in fc.columns:
            figf.add_trace(go.Scatter(x=fc.index, y=fc["Damped trend"], name="Damped trend (Holt)",
                                      line=dict(color=T["warning"], width=2, dash="dot")))
        figf.add_trace(go.Scatter(x=fc.index, y=fc["Random-walk median"], name="Random-walk median",
                                  line=dict(color=T["success"], width=1.6)))
        figf.update_yaxes(title_text=f"Price ({sym})")
        figf.update_layout(hovermode="x unified")
        style_fig(figf, height=430)
        r2 = fc.attrs.get("r_squared")
        figure(figf, f"Projected price over the next {horizon} trading days",
               "Recent actual prices, then three forward projections: a log-linear trend fitted to the whole "
               "window, Holt's damped trend which weights recent days far more heavily, and the median of a "
               "geometric random walk built from this stock's own drift and volatility. The shaded areas are "
               "the trend's 95% prediction interval and the random walk's 90% range.",
               "Read the **width of the shading**, not the lines. If the bands are wide enough to contain both "
               "a good and a bad outcome — which they almost always are — then the central lines are not a "
               "target, they are the midpoint of a distribution. Where the damped trend diverges from the "
               "log-linear one, recent behaviour differs from the longer window.",
               f"The trend explains {Fmt.as_pct(r2)} of the variation in this window "
               f"(R² = {r2:,.2f}). " if _isnum(r2) else ""
               "None of these methods knows anything about earnings, competition or the news. They extrapolate "
               "price history, which is exactly the thing that stops working when something changes.",
               data=fc)

        end = fc.iloc[-1]
        kpi_grid([
            {"label": "Trend projection", "value": Fmt.price(end["Trend"], sym),
             "sub": f"{Fmt.as_pct(end['Trend'] / last_px - 1, signed=True)} from today",
             "tone": "good" if end["Trend"] > last_px else "bad"},
            {"label": "Damped trend", "value": Fmt.price(end.get("Damped trend"), sym),
             "sub": "Weights recent days most heavily", "tone": "flat"},
            {"label": "Random-walk median", "value": Fmt.price(end["Random-walk median"], sym),
             "sub": "Drift only, no trend assumption", "tone": "flat"},
            {"label": "90% range at the horizon", "value":
                f"{Fmt.price(end['Random-walk 5%'], sym)} – {Fmt.price(end['Random-walk 95%'], sym)}",
             "sub": "Nineteen times in twenty, inside this", "tone": "flat"},
            {"label": "Implied annual volatility", "value": Fmt.as_pct(fc.attrs.get("annual_vol")),
             "sub": "From this window's daily moves", "tone": "flat"},
        ], min_width=200)

        note(f"""
Over {horizon} trading days the three methods land between
**{Fmt.price(min(end['Trend'], end['Random-walk median']), sym)}** and
**{Fmt.price(max(end['Trend'], end['Random-walk median']), sym)}**, inside a 90% range of
{Fmt.price(end['Random-walk 5%'], sym)} to {Fmt.price(end['Random-walk 95%'], sym)}.
- **A price forecast is not a valuation.** These methods extrapolate the price series and nothing else. The
intrinsic valuation and peer sections answer what the business is worth; this answers what the recent price
pattern would imply if it simply continued.
- **The trend line is the most confident and the least trustworthy.** It fits the window you selected, so
changing the chart period changes the forecast — worth trying, precisely because a projection that flips with
the window is telling you how little signal there is.
- **Use the band, not the line.** A range wide enough to contain both outcomes is the correct output of an
honest short-horizon model, and it is the input a position size should be set from.
""", tone="neu")

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
elif view == "Financial Statements":
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

    src = filing_source(co.ticker)
    st.markdown(
        f"<div class='card' style='margin-bottom:14px'><div class='card-title'>Where these numbers come from</div>"
        f"<div class='card-body'>Figures here are the data provider's normalised version of "
        f"{co.name}'s filings. The primary source for this market is "
        + (f"<a href='{src['url']}' target='_blank'>{src['name']}</a>" if src["url"] else f"<b>{src['name']}</b>")
        + f".<br><span style='color:var(--muted)'>{src['rhythm']}</span></div></div>",
        unsafe_allow_html=True)

    stmt_view = segmented("View", ["Reported", "Common size", "Growth"], key="stmt_view",
                          help="Common size expresses each line as a share of revenue (or total assets on the "
                               "balance sheet) and adds the industry median beside it. Growth shows the "
                               "period-on-period change.")

    # Industry benchmark: same live peer matching as section 6, so the
    # common-size view always has something to be compared against.
    bench = {"income": pd.Series(dtype="float64"), "balance": pd.Series(dtype="float64"), "n": 0}
    with st.spinner("Building the industry benchmark from live peers…"):
        bench_peers = tuple(suggest_peers(co.ticker, info.get("sector"), info.get("industry"), max_n=8))
        if bench_peers:
            bench = load_industry_commonsize(bench_peers)
    if stmt_view == "Common size":
        if bench["n"]:
            st.caption(f"Industry median columns are computed live from {bench['n']} peers matched on "
                       f"{info.get('industry') or info.get('sector') or 'sector'} "
                       f"({', '.join(bench_peers[:6])}{'…' if len(bench_peers) > 6 else ''}). Each peer is "
                       f"expressed as a share of its own revenue or assets before the median is taken, so "
                       f"size differences do not distort the comparison.")
        else:
            st.caption("No live peer group resolved for this company right now, so the industry median "
                       "columns are omitted rather than filled with a placeholder.")

    def statement_table(df, items, title, what, base=None, base_label="revenue", bench_key=None):
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
        extra_cols = []
        if stmt_view == "Common size" and base is not None:
            denom = base.reindex(sub.columns).replace(0, np.nan)
            sub = sub.div(denom, axis=1) * 100
            fmt = "{:,.1f}%"
            med = bench.get(bench_key) if bench_key else None
            if med is not None and not med.empty:
                latest_col = sub.columns[0]
                industry = med.reindex(sub.index)
                if industry.notna().any():
                    sub["Industry median"] = industry
                    sub["Gap (pp)"] = sub[latest_col] - industry
                    extra_cols = ["Industry median", "Gap (pp)"]
        elif stmt_view == "Growth":
            ordered = sub[sorted(sub.columns)]
            sub = (ordered.pct_change(axis=1) * 100)[sorted(sub.columns, reverse=True)]
            fmt = "{:+,.1f}%"
        elif len(sub.columns) >= 2:
            latest, prev = sub.iloc[:, 0], sub.iloc[:, 1]
            sub["Change"] = latest - prev
            sub["Change %"] = (latest - prev) / prev.abs().replace(0, np.nan) * 100
        sub.columns = (year_labels([c for c in sub.columns if isinstance(c, pd.Timestamp)], basis)
                       + [c for c in sub.columns if not isinstance(c, pd.Timestamp)])
        formats = {}
        for c in sub.columns:
            label = str(c)
            if label == "Gap (pp)":
                formats[c] = "{:+,.1f}"
            elif label == "Industry median":
                formats[c] = "{:,.1f}%"
            elif label == "Change %":
                formats[c] = "{:+,.1f}%"
            elif label == "Change":
                formats[c] = "{:+,.0f}"
            else:
                formats[c] = fmt
        table(sub, title, what, formats=formats)

    t_inc, t_bs, t_cf, t_guide = st.tabs(["Income statement", "Balance sheet", "Cash flow",
                                          "Line by line"])

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
                                base=rev_base, bench_key="income")
                statement_table(inc_d, ["Operating Expense", "Research And Development",
                                        "Selling General And Administration", "Operating Income"],
                                "Operating costs and operating profit",
                                "The overhead layer between gross profit and profit from operations.",
                                base=rev_base, bench_key="income")
                statement_table(inc_d, ["Net Non Operating Interest Income Expense", "Interest Expense",
                                        "Other Income Expense", "Pretax Income", "Tax Provision",
                                        "Net Income", "Basic EPS", "Diluted EPS"],
                                "Below the operating line",
                                "Financing costs, tax, and what finally reaches shareholders.",
                                base=rev_base, bench_key="income")
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
                                base=asset_base, base_label="total assets", bench_key="balance")
                statement_table(bs_d, ["Net PPE", "Goodwill", "Other Intangible Assets",
                                       "Total Non Current Assets", "Total Assets"],
                                "Non-current assets", "The long-lived asset base.",
                                base=asset_base, base_label="total assets", bench_key="balance")
                statement_table(bs_d, ["Accounts Payable", "Current Debt", "Current Liabilities",
                                       "Long Term Debt", "Total Non Current Liabilities",
                                       "Total Liabilities Net Minority Interest"],
                                "Liabilities", "What is owed, split by when it falls due.",
                                base=asset_base, base_label="total assets", bench_key="balance")
                statement_table(bs_d, ["Common Stock", "Retained Earnings", "Stockholders Equity"],
                                "Equity", "The shareholders' residual claim.",
                                base=asset_base, base_label="total assets", bench_key="balance")
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

    with t_guide:
        st.markdown(
            "<div class='section-sub'>Every line the company actually reports, explained: what it is, what "
            "moves it, what to watch — with this company's own figure, its share of the relevant total, its "
            "change on the prior period, and the industry median for the same line where a peer group "
            "resolved. Generated from the reported statements, so it follows whatever the company files.</div>",
            unsafe_allow_html=True)

        cost_note = SECTOR_COST_NOTES.get(info.get("sector") or "", None)
        summary = (info.get("longBusinessSummary") or "").strip()
        first_sentences = " ".join(re.split(r"(?<=[.!?]) ", summary)[:3]) if summary else ""
        emp = info.get("fullTimeEmployees")
        rev_latest = last(inc_d, "Total Revenue")
        rev_per_head = safe_div(rev_latest, emp) if _isnum(emp) and emp else None

        st.markdown(
            f"<div class='card'><div class='card-title'>What this company actually sells</div>"
            f"<div class='card-body'>{first_sentences or 'No business description is available from the data source.'}</div>"
            f"<div class='card-meta' style='margin-top:10px'>"
            f"Classified as <b>{co.industry}</b> within <b>{co.sector}</b>"
            + (f" · revenue per employee <b>{Fmt.money(rev_per_head, sym)}</b> across "
               f"<b>{emp:,}</b> staff" if rev_per_head else "")
            + (f"<br>For a business of this type the direct cost line typically contains {cost_note['cogs']}; "
               f"operating expenses are usually dominated by {cost_note['opex']}. The filing's own breakdown "
               f"is in the annual report — this data source does not publish segment detail."
               if cost_note else "")
            + "</div></div>", unsafe_allow_html=True)

        def line_cards(df, names, base_series, bench_key, share_label):
            """One explanatory card per reported line, with this company's figure
            beside the industry median for the same line."""
            base_latest = None
            if base_series is not None and not base_series.dropna().empty:
                base_latest = float(base_series.dropna().iloc[-1])
            med = bench.get(bench_key) if bench_key else None
            shown = 0
            for name in names:
                if name not in df.columns:
                    continue
                series = df[name].dropna()
                if series.empty:
                    continue
                val = float(series.iloc[-1])
                share = safe_div(val, base_latest) if base_latest else None
                yoy = (val / float(series.iloc[-2]) - 1) if len(series) >= 2 and series.iloc[-2] else None
                growth = cagr(float(series.iloc[0]), val, len(series) - 1) if len(series) >= 3 and series.iloc[0] > 0 else None
                ind = None
                if med is not None and not med.empty and name in med.index and _isnum(med.get(name)):
                    ind = float(med[name])
                guide = LINE_ITEMS.get(name)

                facts = [f"<b>{Fmt.money(val, sym)}</b> in the latest {basis.lower()} period"]
                if share is not None:
                    facts.append(f"{Fmt.as_pct(share)} of {share_label}")
                if yoy is not None:
                    facts.append(f"{Fmt.as_pct(yoy, signed=True)} on the prior period")
                if growth is not None:
                    facts.append(f"{Fmt.as_pct(growth)} a year compounded")
                if ind is not None and share is not None:
                    gap = share * 100 - ind
                    facts.append(
                        f"industry median {ind:,.1f}% — this company is <b>in line</b>" if abs(gap) < 0.05
                        else f"industry median {ind:,.1f}% — this company is "
                             f"<b>{abs(gap):,.1f}pp {'above' if gap > 0 else 'below'}</b>")

                rows = f"<div class='defn-row'><div class='defn-k'>Figures</div><div>{' · '.join(facts)}</div></div>"
                if guide:
                    rows += (f"<div class='defn-row'><div class='defn-k'>What it is</div><div>{guide['what']}</div></div>"
                             f"<div class='defn-row'><div class='defn-k'>What moves it</div><div>{guide['drivers']}</div></div>"
                             f"<div class='defn-row'><div class='defn-k'>What to watch</div><div>{guide['watch']}</div></div>")
                st.markdown(
                    f"<div class='defn'><div class='defn-h'><span class='defn-name'>{name}</span>"
                    f"<span class='defn-val'>{Fmt.money(val, sym)}</span></div>{rows}</div>",
                    unsafe_allow_html=True)
                shown += 1
            if not shown:
                st.caption("None of these lines are reported for this company.")

        g1, g2, g3 = st.tabs(["Income statement lines", "Balance sheet lines", "Cash flow lines"])
        with g1:
            line_cards(inc_d, ["Total Revenue", "Cost Of Revenue", "Gross Profit", "Operating Expense",
                               "Research And Development", "Selling General And Administration",
                               "Operating Income", "EBITDA", "Interest Expense", "Pretax Income",
                               "Tax Provision", "Net Income", "Basic EPS", "Diluted EPS"],
                       col(inc_d, "Total Revenue"), "income", "revenue")
        with g2:
            line_cards(bs_d, ["Cash And Cash Equivalents", "Accounts Receivable", "Inventory",
                              "Current Assets", "Net PPE", "Goodwill", "Total Assets", "Accounts Payable",
                              "Current Debt", "Current Liabilities", "Long Term Debt",
                              "Total Liabilities Net Minority Interest", "Retained Earnings",
                              "Stockholders Equity"],
                       col(bs_d, "Total Assets"), "balance", "total assets")
        with g3:
            line_cards(cf_d, ["Operating Cash Flow", "Depreciation And Amortization",
                              "Stock Based Compensation", "Change In Working Capital",
                              "Capital Expenditure", "Free Cash Flow", "Cash Dividends Paid",
                              "Repurchase Of Capital Stock", "Net Issuance Payments Of Debt"],
                       col(inc_d, "Total Revenue"), None, "revenue")

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
elif view == "Cash Flow Quality":
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
elif view == "Capital Allocation":
    inc_d, bs_d, cf_d = to_display(co.inc, fx), to_display(co.bs, fx), to_display(co.cf, fx)
    if inc_d.empty or bs_d.empty:
        empty_state("This module needs both an income statement and a balance sheet.")
        st.stop()

    section("Return on invested capital",
            "Growth is only worth having if the capital funding it earns more than that capital costs. "
            "This section measures the spread, and then follows where the cash actually went.")

    # --- ROIC: NOPAT over invested capital -----------------------------------
    tax_rate = 0.21
    pretax, taxp = last(inc_d, "Pretax Income"), last(inc_d, "Tax Provision")
    if _isnum(pretax) and pretax and _isnum(taxp):
        tax_rate = float(np.clip(taxp / pretax, 0.0, 0.40))

    def invested_capital(row):
        """Total debt plus equity less cash: the capital the operating business
        actually has at its disposal, which is what a return should be measured
        against."""
        debt = row.get("Total Debt")
        if not _isnum(debt):
            lt, st_ = row.get("Long Term Debt"), row.get("Current Debt")
            debt = (lt if _isnum(lt) else 0.0) + (st_ if _isnum(st_) else 0.0)
        eq = row.get("Stockholders Equity")
        cash = row.get("Cash And Cash Equivalents")
        if not _isnum(eq):
            return None
        return float(debt) + float(eq) - (float(cash) if _isnum(cash) else 0.0)

    ebit_series = col(inc_d, "EBIT")
    if ebit_series is None:
        ebit_series = col(inc_d, "Operating Income")
    if ebit_series is None:
        empty_state("Operating profit is not reported, so ROIC cannot be computed.")
        st.stop()

    rows = []
    for i, period in enumerate(bs_d.index):
        if period not in inc_d.index:
            continue
        ic = invested_capital(bs_d.loc[period])
        ebit = inc_d.loc[period].get("EBIT") or inc_d.loc[period].get("Operating Income")
        if not _isnum(ic) or ic <= 0 or not _isnum(ebit):
            continue
        rows.append({"period": period, "NOPAT": ebit * (1 - tax_rate), "Invested capital": ic,
                     "ROIC": ebit * (1 - tax_rate) / ic * 100})
    roic_df = pd.DataFrame(rows).set_index("period") if rows else pd.DataFrame()

    rf = load_risk_free_rate()
    beta_v = info.get("beta") if _isnum(info.get("beta")) else 1.0
    cost_debt = 0.05
    int_exp, tot_debt = last(inc_d, "Interest Expense"), last(bs_d, "Total Debt")
    if _isnum(int_exp) and _isnum(tot_debt) and tot_debt:
        cost_debt = float(np.clip(abs(int_exp) / tot_debt, 0.005, 0.20))
    wacc_v, cost_equity, w_e, w_d = Valuation.capm_wacc(
        beta_v, rf, 0.05, cost_debt, tax_rate, (co.market_cap or 0) * fx,
        (info.get("totalDebt") or last(bs_d, "Total Debt") or 0) * (1 if info.get("totalDebt") else 1))
    wacc_pct = float(np.clip(wacc_v, 0.04, 0.20)) * 100

    latest_roic = float(roic_df["ROIC"].iloc[-1]) if not roic_df.empty else None
    spread = (latest_roic - wacc_pct) if latest_roic is not None else None

    # Incremental return: the extra NOPAT earned on the extra capital committed.
    ronic = None
    if len(roic_df) >= 2:
        d_nopat = float(roic_df["NOPAT"].iloc[-1] - roic_df["NOPAT"].iloc[0])
        d_ic = float(roic_df["Invested capital"].iloc[-1] - roic_df["Invested capital"].iloc[0])
        if d_ic > 0:
            ronic = d_nopat / d_ic * 100

    kpi_grid([
        {"label": "ROIC", "value": Fmt.pct(latest_roic),
         "sub": f"NOPAT {Fmt.money(roic_df['NOPAT'].iloc[-1] if not roic_df.empty else None, sym)} "
                f"on {Fmt.money(roic_df['Invested capital'].iloc[-1] if not roic_df.empty else None, sym)}",
         "tone": tone_for(latest_roic, 12, 6),
         "help": "After-tax operating profit divided by debt plus equity less cash."},
        {"label": "WACC", "value": Fmt.pct(wacc_pct),
         "sub": f"Cost of equity {Fmt.as_pct(cost_equity)} at beta {Fmt.ratio(beta_v)}",
         "tone": "flat",
         "help": "The blended cost of the capital funding the business, from CAPM."},
        {"label": "Spread", "value": Fmt.pct(spread, signed=True),
         "sub": "ROIC less WACC — value created per unit of capital",
         "tone": tone_for(spread, 2, -1),
         "help": "Positive means each unit of capital employed earns more than it costs. Negative means "
                 "growth destroys value however fast revenue climbs."},
        {"label": "Incremental ROIC", "value": Fmt.pct(ronic),
         "sub": "Extra NOPAT per unit of extra capital, across the reported period",
         "tone": tone_for(ronic, 12, 5),
         "help": "The return on the capital most recently committed, which matters far more than the "
                 "average return on capital committed years ago."},
    ], min_width=205)

    if not roic_df.empty:
        x = year_labels(roic_df.index)
        figr = go.Figure()
        figr.add_trace(go.Bar(x=x, y=roic_df["ROIC"], name="ROIC",
                              marker_color=[T["success"] if v >= wacc_pct else T["danger"]
                                            for v in roic_df["ROIC"]], opacity=.85))
        figr.add_hline(y=wacc_pct, line_dash="dash", line_color=T["accent"],
                       annotation_text=f"WACC {wacc_pct:,.1f}%", annotation_position="top left")
        figr.update_xaxes(type="category")
        figr.update_yaxes(title_text="%", ticksuffix="%")
        style_fig(figr, height=340, legend="off")
        figure(figr, "Return on invested capital against its cost",
               "ROIC for each reported year, with the current cost of capital drawn across it. Bars are green "
               "where the business earned more than its capital cost and red where it did not.",
               "The **gap** is the whole story. A company earning 18% on capital that costs 8% creates value "
               "with every unit it reinvests; one earning 5% on capital that costs 9% destroys value with "
               "every unit, and growing faster only destroys it faster.",
               "This is the single test that separates a compounding business from one that is merely large. "
               "Revenue growth tells you nothing about it.",
               data=roic_df)

    # --- Cash deployment waterfall --------------------------------------------
    section("Where the cash went",
            "Every unit of cash the business generated, and the choice management made with it.")
    ocf_total = float(col(cf_d, "Operating Cash Flow").sum()) if col(cf_d, "Operating Cash Flow") is not None else None
    if ocf_total is None:
        empty_state("No cash flow history available.")
    else:
        def total(name):
            series = col(cf_d, name)
            return abs(float(series.sum())) if series is not None else 0.0

        capex = total("Capital Expenditure")
        acq = total("Purchase Of Business")
        buyback = total("Repurchase Of Capital Stock")
        divs = total("Cash Dividends Paid")
        debt_repaid = 0.0
        dser = col(cf_d, "Net Issuance Payments Of Debt")
        if dser is not None:
            net_debt_flow = float(dser.sum())
            debt_repaid = abs(net_debt_flow) if net_debt_flow < 0 else 0.0
        retained = ocf_total - capex - acq - buyback - divs - debt_repaid

        uses = {"Capital expenditure": capex, "Acquisitions": acq, "Buybacks": buyback,
                "Dividends": divs, "Debt repaid": debt_repaid}
        uses = {k: v for k, v in uses.items() if v > 0}

        figw = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute"] + ["relative"] * len(uses) + ["total"],
            x=["Operating cash flow"] + list(uses.keys()) + ["Left on the balance sheet"],
            y=[ocf_total] + [-v for v in uses.values()] + [0],
            connector={"line": {"color": T["border"]}},
            increasing={"marker": {"color": T["success"]}},
            decreasing={"marker": {"color": T["danger"]}},
            totals={"marker": {"color": T["accent"]}}))
        figw.update_yaxes(title_text=f"Cumulative over the reported period ({sym})")
        style_fig(figw, height=380, legend="off")
        figure(figw, "Cash deployment across the reported period",
               "Total cash generated from operations, and every use it was put to, summed across all "
               "reported years.",
               "Read the relative sizes. Heavy **capital expenditure** means the business must keep feeding "
               "itself; heavy **acquisitions** mean growth is being bought rather than built, and should be "
               "checked against the ROIC trend above; heavy **buybacks and dividends** mean management could "
               "not find enough to reinvest in at an attractive return.",
               "Capital allocation is the decision that compounds. A business with a high ROIC that returns "
               "all its cash is a bond; one with a low ROIC that reinvests all of it is a value trap.",
               data=pd.DataFrame({"Amount": {"Operating cash flow": ocf_total, **uses,
                                             "Retained": retained}}))

        mix = pd.Series(uses)
        reinvest_share = safe_div(capex + acq, ocf_total)
        return_share = safe_div(buyback + divs, ocf_total)
        note(f"""
Over the reported period the business generated **{Fmt.money(ocf_total, sym)}** from operations and put
**{Fmt.as_pct(reinvest_share)}** of it back into the business, returning **{Fmt.as_pct(return_share)}** to
shareholders.
- **ROIC of {Fmt.pct(latest_roic)} against a cost of capital of {Fmt.pct(wacc_pct)}** means each unit
reinvested {'creates' if (spread or 0) > 0 else 'destroys'} value.
{'Reinvestment is the right call at this spread, and the heavier it is the better — provided incremental returns hold up.' if (spread or 0) > 2 else 'At a spread this thin, returning cash to shareholders is usually the better use of it than reinvestment.' if (spread or 0) < 1 else ''}
- **Incremental ROIC of {Fmt.pct(ronic)}** is the forward-looking figure: it measures the capital committed
most recently, not the legacy asset base. When it runs well below the average ROIC, the returns that built the
company's reputation are not being repeated on new money.
- **Acquisitions of {Fmt.money(acq, sym)}** deserve separate scrutiny: they are the deployment route with the
worst average outcome across markets, and their effect shows up in ROIC only after the goodwill lands on the
balance sheet.
""", tone="pos" if (spread or 0) > 2 else "warn" if (spread or 0) > -1 else "neg")


# ==============================================================================
elif view == "Solvency & Debt":
    inc_d, bs_d, cf_d = to_display(co.inc, fx), to_display(co.bs, fx), to_display(co.cf, fx)
    if bs_d.empty:
        empty_state("No balance sheet available for this symbol.")
        st.stop()

    section("Can the balance sheet take a shock?",
            "Leverage only matters when refinancing or earnings turn against you. This section sizes both.")

    latest_bs = bs_d.iloc[-1]
    current_debt = latest_bs.get("Current Debt")
    long_debt = latest_bs.get("Long Term Debt")
    total_debt = latest_bs.get("Total Debt")
    if not _isnum(total_debt):
        total_debt = (current_debt if _isnum(current_debt) else 0.0) + (long_debt if _isnum(long_debt) else 0.0)
    cash = latest_bs.get("Cash And Cash Equivalents")
    net_debt_v = float(total_debt) - (float(cash) if _isnum(cash) else 0.0)
    ebitda_v = (info.get("ebitda") or 0) * fx
    if not ebitda_v:
        op = last(inc_d, "EBIT", ) or last(inc_d, "Operating Income")
        da = last(cf_d, "Depreciation And Amortization")
        ebitda_v = (op or 0) + (da or 0)
    ebit_v = last(inc_d, "EBIT") or last(inc_d, "Operating Income")
    interest_v = abs(last(inc_d, "Interest Expense") or 0)
    cover = safe_div(ebit_v, interest_v) if interest_v else None
    avg_rate = safe_div(interest_v, total_debt)

    kpi_grid([
        {"label": "Total debt", "value": Fmt.money(total_debt, sym),
         "sub": f"Cash {Fmt.money(cash, sym)} · net debt {Fmt.money(net_debt_v, sym)}",
         "tone": "flat"},
        {"label": "Net debt / EBITDA", "value": Fmt.ratio(safe_div(net_debt_v, ebitda_v)),
         "sub": "Years of cash earnings to repay net borrowings",
         "tone": tone_for(safe_div(net_debt_v, ebitda_v), 2, 4, higher_better=False),
         "help": "Above roughly 3.5x is where lenders start attaching conditions and refinancing gets harder."},
        {"label": "Interest cover", "value": Fmt.ratio(cover),
         "sub": f"Operating profit {Fmt.money(ebit_v, sym)} against interest {Fmt.money(interest_v, sym)}",
         "tone": tone_for(cover, 5, 2),
         "help": "How many times over current earnings pay the interest bill. Below 2x leaves no room for a "
                 "bad year."},
        {"label": "Average borrowing rate", "value": Fmt.as_pct(avg_rate),
         "sub": "Interest expense over total debt",
         "tone": tone_for((avg_rate or 0) * 100 if avg_rate else None, 4, 8, higher_better=False),
         "help": "A rate well below current market rates means cheap legacy debt that will reprice upward "
                 "as it matures."},
        {"label": "Due within a year", "value": Fmt.money(current_debt, sym),
         "sub": f"{Fmt.as_pct(safe_div(current_debt, total_debt))} of total borrowings",
         "tone": tone_for((safe_div(current_debt, total_debt) or 0) * 100 if _isnum(current_debt) else None,
                          15, 40, higher_better=False)},
    ], min_width=200)

    # --- Maturity profile ------------------------------------------------------
    lad = {"Due within 1 year": float(current_debt) if _isnum(current_debt) else 0.0,
           "Due beyond 1 year": float(long_debt) if _isnum(long_debt) else 0.0}
    if sum(lad.values()) > 0:
        figl = go.Figure(go.Bar(x=list(lad.keys()), y=list(lad.values()),
                                marker_color=[T["danger"], T["accent_soft"]], opacity=.85,
                                text=[Fmt.money(v, sym) for v in lad.values()], textposition="outside"))
        figl.update_yaxes(title_text=sym)
        style_fig(figl, height=320, legend="off")
        figure(figl, "Debt maturity profile, as reported",
               "Borrowings split into the portion falling due within twelve months and the portion beyond it, "
               "alongside the cash available to meet it.",
               "Compare the left bar against cash of " + Fmt.money(cash, sym) + " and free cash flow of "
               + Fmt.money((co.base_fcf or 0) * fx, sym) + ". If near-term maturities exceed both, the "
               "company must refinance, and it will do so on whatever terms the market offers at the time.",
               "A full year-by-year ladder is disclosed only in the notes to the accounts, which this data "
               "source does not carry — the primary filing linked in the Financial Statements module has it. "
               "The same applies to the fixed-versus-floating split, which is a note-level disclosure.",
               data=pd.Series(lad).to_frame("Amount"))

    # --- Refinancing stress test ----------------------------------------------
    section("Refinancing stress test",
            "What happens to interest cover if this debt is refinanced at higher rates.")
    shock = st.slider("Increase in borrowing cost (basis points)", 0, 600, 200, 25,
                      help="Applied to total debt, i.e. the fully-repriced case rather than only the "
                           "portion maturing soon.")
    if _isnum(ebit_v) and total_debt:
        scenarios = []
        for bump in (0, shock / 2, shock, shock * 1.5):
            new_interest = interest_v + total_debt * (bump / 10000.0)
            scenarios.append({"Rate increase (bps)": bump,
                              "Interest expense": new_interest,
                              "Interest cover": safe_div(ebit_v, new_interest),
                              "Profit after interest": ebit_v - new_interest})
        sdf = pd.DataFrame(scenarios).set_index("Rate increase (bps)")
        c1, c2 = st.columns([1.2, 1])
        with c1:
            figs = go.Figure(go.Bar(x=[f"+{int(i)}bp" for i in sdf.index], y=sdf["Interest cover"],
                                    marker_color=[T["success"] if v >= 3 else T["warning"] if v >= 1.5
                                                  else T["danger"] for v in sdf["Interest cover"]],
                                    text=[f"{v:,.1f}x" for v in sdf["Interest cover"]],
                                    textposition="outside", opacity=.85))
            figs.add_hline(y=2.0, line_dash="dot", line_color=T["danger"],
                           annotation_text="2.0x — the level lenders watch")
            figs.update_yaxes(title_text="Interest cover (x)")
            style_fig(figs, height=330, legend="off")
            figure(figs, "Interest cover under higher borrowing costs",
                   "Operating profit divided by the interest bill, if all debt repriced upward by the amount "
                   "shown.",
                   "Watch where the bars cross the dotted line. That is the increase in rates at which this "
                   "company stops comfortably covering its interest from operating profit — and therefore the "
                   "point at which covenants, credit ratings and dividend policy come under real pressure.",
                   "It assumes operating profit stays flat, which is the optimistic case: rates usually rise "
                   "because the economy is running hot, and they bite hardest when it subsequently is not.")
        with c2:
            table(sdf, "Stress scenarios",
                  "Each row repriced the whole debt stack, holding operating profit constant.",
                  formats={"Interest expense": lambda v: Fmt.money(v, sym),
                           "Interest cover": "{:,.2f}x",
                           "Profit after interest": lambda v: Fmt.money(v, sym)})

        breaking = next((int(i) for i, v in sdf["Interest cover"].items() if _isnum(v) and v < 2.0), None)
        note(f"""
Interest cover today is **{Fmt.ratio(cover)}**, on an average borrowing cost of **{Fmt.as_pct(avg_rate)}**.
- {'A ' + str(breaking) + ' basis point rise in borrowing costs would take cover below 2.0x, the level at which lenders and rating agencies start to react.' if breaking else 'Even a ' + str(int(shock * 1.5)) + ' basis point rise leaves cover above 2.0x on current earnings, which is a genuinely resilient position.'}
- **{Fmt.money(current_debt, sym)} falls due within a year**, against cash of {Fmt.money(cash, sym)}. That is
the immediate refinancing question, and it is answered by the balance sheet rather than by the income statement.
- **The average rate paid ({Fmt.as_pct(avg_rate)}) versus current market rates** tells you which direction the
interest bill is heading. Cheap legacy debt is an asset that quietly expires.
- A year-by-year maturity ladder and the fixed-versus-floating split are note-level disclosures. This module
shows what the summary statements carry; the primary filing has the rest.
""", tone="pos" if (cover or 0) >= 5 else "warn" if (cover or 0) >= 2 else "neg")


# ==============================================================================
elif view == "Dilution & Owner Earnings":
    inc_d, cf_d, bs_d = to_display(co.inc, fx), to_display(co.cf, fx), to_display(co.bs, fx)
    if cf_d.empty or inc_d.empty:
        empty_state("This module needs both an income statement and a cash flow statement.")
        st.stop()

    section("What is left for owners, after paying people in stock",
            "Stock compensation is added back in the cash flow statement because no cash moved. It is still a "
            "real cost — it is paid in ownership rather than in cash, and it lands on the share count.")

    shares_series = col(inc_d, "Diluted Average Shares")
    if shares_series is None:
        shares_series = col(inc_d, "Basic Average Shares")
    if shares_series is None:
        shares_series = col(bs_d, "Share Issued")
    sbc_series = col(cf_d, "Stock Based Compensation")
    ocf_series = col(cf_d, "Operating Cash Flow")
    fcf_series = col(cf_d, "Free Cash Flow")
    if fcf_series is None and ocf_series is not None:
        capex_series = col(cf_d, "Capital Expenditure")
        fcf_series = ocf_series + (capex_series if capex_series is not None else 0)
    rev_series = col(inc_d, "Total Revenue")

    share_cagr = None
    if shares_series is not None and shares_series.dropna().size >= 2:
        sh = shares_series.dropna()
        share_cagr = cagr(float(sh.iloc[0]), float(sh.iloc[-1]), len(sh) - 1)

    sbc_latest = float(sbc_series.dropna().iloc[-1]) if sbc_series is not None and sbc_series.dropna().size else None
    ocf_latest = float(ocf_series.dropna().iloc[-1]) if ocf_series is not None and ocf_series.dropna().size else None
    fcf_latest = float(fcf_series.dropna().iloc[-1]) if fcf_series is not None and fcf_series.dropna().size else None
    rev_latest = float(rev_series.dropna().iloc[-1]) if rev_series is not None and rev_series.dropna().size else None
    shares_latest = float(shares_series.dropna().iloc[-1]) if shares_series is not None and shares_series.dropna().size else (co.shares or None)

    adj_fcf = (fcf_latest - sbc_latest) if _isnum(fcf_latest) and _isnum(sbc_latest) else fcf_latest
    fcf_ps = safe_div(fcf_latest, shares_latest)
    adj_fcf_ps = safe_div(adj_fcf, shares_latest)
    price_now = (co.price or 0) * fx

    kpi_grid([
        {"label": "Diluted share count CAGR", "value": Fmt.as_pct(share_cagr, signed=True),
         "sub": "Annual change across the reported history",
         "tone": tone_for((share_cagr or 0) * 100 if share_cagr is not None else None, 0, 2, higher_better=False),
         "help": "Positive means each existing share owns a little less of the company every year."},
        {"label": "Stock compensation", "value": Fmt.money(sbc_latest, sym),
         "sub": f"{Fmt.as_pct(safe_div(sbc_latest, rev_latest))} of revenue · "
                f"{Fmt.as_pct(safe_div(sbc_latest, ocf_latest))} of operating cash flow",
         "tone": tone_for((safe_div(sbc_latest, rev_latest) or 0) * 100 if _isnum(sbc_latest) else None,
                          3, 12, higher_better=False)},
        {"label": "Reported FCF per share", "value": Fmt.price(fcf_ps, sym),
         "sub": "As the cash flow statement presents it", "tone": "flat"},
        {"label": "FCF per share after stock comp", "value": Fmt.price(adj_fcf_ps, sym),
         "sub": f"{Fmt.as_pct(safe_div(adj_fcf, fcf_latest) - 1 if _isnum(adj_fcf) and fcf_latest else None, signed=True)} against the reported figure",
         "tone": tone_for((safe_div(adj_fcf, fcf_latest) or 0) * 100 if _isnum(adj_fcf) and fcf_latest else None,
                          90, 70),
         "help": "Treating stock compensation as the cost it is, rather than adding it back."},
        {"label": "Yield on owner earnings", "value": Fmt.as_pct(safe_div(adj_fcf_ps, price_now)),
         "sub": "Adjusted free cash flow per share against the price",
         "tone": tone_for((safe_div(adj_fcf_ps, price_now) or 0) * 100 if price_now else None, 5, 2)},
    ], min_width=205)

    c1, c2 = st.columns(2)
    with c1:
        if shares_series is not None and shares_series.dropna().size >= 2:
            sh = shares_series.dropna()
            figsh = go.Figure(go.Scatter(x=year_labels(sh.index), y=sh, mode="lines+markers",
                                         line=dict(color=T["accent"], width=2.6), name="Diluted shares"))
            figsh.update_xaxes(type="category")
            figsh.update_yaxes(title_text="Shares outstanding")
            style_fig(figsh, height=320, legend="off")
            figure(figsh, "Diluted share count over time",
                   "The number of shares the company's earnings are divided between, each reported year.",
                   "A line drifting **up** means existing holders own a shrinking slice — earnings per share "
                   "grows more slowly than earnings. A line drifting **down** means buybacks are outrunning "
                   "issuance, and per-share figures grow faster than the business.",
                   f"At {Fmt.as_pct(share_cagr, signed=True)} a year, this is "
                   + ("a meaningful drag on per-share returns that compounds silently."
                      if (share_cagr or 0) > 0.01 else
                      "not materially diluting existing holders.")
                   + " Buybacks that merely offset issuance return nothing to owners; they just stop the leak.",
                   data=sh.to_frame("Diluted shares"))
    with c2:
        if fcf_series is not None and sbc_series is not None:
            comp = pd.DataFrame({"Reported FCF": fcf_series, "After stock comp": fcf_series - sbc_series}).dropna()
            if not comp.empty:
                x = year_labels(comp.index)
                figc = go.Figure()
                figc.add_trace(go.Bar(x=x, y=comp["Reported FCF"], name="Reported free cash flow",
                                      marker_color=T["accent_soft"], opacity=.85))
                figc.add_trace(go.Bar(x=x, y=comp["After stock comp"], name="After stock compensation",
                                      marker_color=T["warning"], opacity=.9))
                figc.update_layout(barmode="overlay")
                figc.update_xaxes(type="category")
                figc.update_yaxes(title_text=sym)
                style_fig(figc, height=320)
                figure(figc, "Free cash flow, before and after the cost of stock compensation",
                       "Reported free cash flow beside the same figure with stock-based compensation "
                       "subtracted rather than added back.",
                       "The gap is the part of reported cash flow that exists because employees were paid in "
                       "ownership instead of cash. For companies where the gap is wide, the headline free "
                       "cash flow yield is measuring something the owners never receive.",
                       "Whether stock compensation is a real expense is one of the few genuine accounting "
                       "debates left. The defensible position: it is real, because the alternative was paying "
                       "cash, and the bill arrives as dilution.",
                       data=comp)

    note(f"""
Reported free cash flow of **{Fmt.money(fcf_latest, sym)}** becomes **{Fmt.money(adj_fcf, sym)}** once stock
compensation of {Fmt.money(sbc_latest, sym)} is treated as the cost it is.
- **Per share, that is {Fmt.price(fcf_ps, sym)} against {Fmt.price(adj_fcf_ps, sym)}** — and per share is the
only unit that matters to an owner, because it already accounts for the shares the company issued along the way.
- **The share count is compounding at {Fmt.as_pct(share_cagr, signed=True)} a year.**
{'Over a decade that alone consumes a meaningful share of the returns, before the business has done anything wrong.' if (share_cagr or 0) > 0.01 else 'That is low enough not to materially change the investment case.'}
- **Watch buybacks against issuance, not in isolation.** A company can spend heavily on repurchases and still
end the year with more shares outstanding. The chart above settles that question in one line, where the
buyback announcement does not.
- Stock compensation of {Fmt.as_pct(safe_div(sbc_latest, rev_latest))} of revenue is
{'high enough that the valuation multiples elsewhere in this app understate what owners are paying' if (safe_div(sbc_latest, rev_latest) or 0) > 0.08 else 'modest relative to revenue'}.
""", tone="warn" if (share_cagr or 0) > 0.01 else "neu")


# ==============================================================================
elif view == "Intrinsic Valuation":
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
elif view == "Peer Comparables":
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
elif view == "Risk & Scenarios":
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
elif view == "Price & Capital Dynamics":
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

    # --- Automatic wall of worry ----------------------------------------------
    section("Wall of worry, assembled automatically",
            "Every statistically unusual day in this window, found without being told what to look for, and "
            "matched against the headlines closest to it.")

    shocks = detect_shocks(px_series, z_threshold=2.5, max_events=10)
    if shocks.empty:
        empty_state("No day in this window moved far enough to stand out statistically.",
                    "Try a longer chart period — quiet windows genuinely have no outliers.")
    else:
        all_news = [n for n in (company_news + sector_news) if n.get("time")]

        def nearest_headline(day, window_days=3):
            best, best_gap = None, None
            for item in all_news:
                gap = abs((item["time"].date() - day.date()).days)
                if gap <= window_days and (best_gap is None or gap < best_gap):
                    best, best_gap = item, gap
            return best, best_gap

        event_rows, annotated = [], []
        for day, row in shocks.iterrows():
            item, gap = nearest_headline(pd.Timestamp(day))
            event_rows.append({
                "Date": pd.Timestamp(day).strftime("%d %b %Y"),
                "Move %": float(row["Move %"]),
                "Sigma": float(row["Sigma"]),
                "Closest headline": (item["title"][:110] if item else "nothing in the current news window"),
                "Days apart": (gap if item else np.nan),
            })
            annotated.append((pd.Timestamp(day), float(row["Move %"]), item))

        figsh = go.Figure()
        figsh.add_trace(go.Scatter(x=px_series.index, y=px_series, name="Price",
                                   line=dict(color=T["accent"], width=2)))
        for day, move, item in annotated:
            if day not in px_series.index:
                continue
            colour = T["success"] if move > 0 else T["danger"]
            figsh.add_trace(go.Scatter(
                x=[day], y=[float(px_series.loc[day])], mode="markers",
                marker=dict(size=11, color=colour, symbol="circle-open", line=dict(width=2.5)),
                name=f"{move:+.1f}%", showlegend=False,
                hovertext=(f"{day:%d %b %Y}: {move:+.1f}%<br>"
                           + (item["title"][:90] if item else "no headline nearby")),
                hoverinfo="text"))
        figsh.update_yaxes(title_text=f"Price ({sym})")
        style_fig(figsh, height=380, legend="off")
        figure(figsh, "Statistically unusual days, marked automatically",
               "Every day whose move was at least 2.5 standard deviations from this stock's own average, "
               "circled in green for gains and red for falls. Hover for the headline nearest that date.",
               "The threshold is measured in this stock's **own** volatility, not a fixed percentage, so a 4% "
               "day registers as a shock for a steady name and passes unremarked for a volatile one. Clusters "
               "of circles matter more than isolated ones: they mark regime changes rather than single events.",
               "Marking the moves first and looking for the cause second is the right order. Reading the news "
               "first invites you to find a story for a move that was just noise.",
               data=shocks)

        edf = pd.DataFrame(event_rows).set_index("Date")
        table(edf, "Unusual days and the nearest headline",
              "Matched within three days either side. A blank match means the current news feed does not "
              "reach back that far — it is a limit of the feed, not evidence that nothing happened.",
              formats={"Move %": "{:+,.2f}%", "Sigma": "{:+,.1f}σ", "Days apart": "{:,.0f}"})

        ups = int((shocks["Move %"] > 0).sum())
        downs = int((shocks["Move %"] < 0).sum())
        matched = sum(1 for r in event_rows if not pd.isna(r["Days apart"]))
        note(f"""
This window contains **{len(shocks)} statistically unusual days** — {ups} up, {downs} down — of which
**{matched}** fall within three days of a headline currently in the feed.
- **The unmatched ones are the interesting ones.** A large move with no company or sector news nearby is
usually an index-level event, a sector rotation, or a flow rather than anything about this business. The news
feed here reaches back only a few weeks, so older events will show blank regardless.
- **Direction matters less than clustering.** Several outliers close together mark a period when the market
was repricing the company, and that is the stretch to read the filings and transcripts around.
- Thresholds are relative to this stock's own volatility over the window, so changing the chart period changes
what counts as unusual — a deliberate property, not an inconsistency.
""", tone="warn" if downs > ups else "neu")

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
elif view == "Market Leaders":
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
elif view == "Compare Companies":
    section("Side by side",
            "Two or more companies on identical measures. Everything is converted to a single currency and "
            "rebased to a common starting point, so the comparison is about the businesses rather than about "
            "share prices or listing currencies.")

    with st.spinner("Suggesting comparable companies…"):
        sugg = suggest_peers(co.ticker, info.get("sector"), info.get("industry"), max_n=6)
    default_list = ", ".join(dict.fromkeys([co.ticker] + sugg[:2]))
    raw = st.text_input("Companies to compare (comma separated, up to eight)", value=default_list,
                        help="Any symbol the data source knows, including cross-market ones such as SAP.DE "
                             "or 7203.T. The company selected in the sidebar is added automatically.")
    picks = [t.strip().upper() for t in raw.split(",") if t.strip()][:8]
    universe = tuple(dict.fromkeys(picks + [co.ticker]))

    if len(universe) < 2:
        empty_state("Add at least one more company to compare against.")
        st.stop()

    with st.spinner(f"Loading {len(universe)} companies in parallel…"):
        cmp_df = load_comparables(universe, target_currency)
    if cmp_df.empty:
        empty_state("None of those symbols returned usable data.")
        st.stop()

    start = {"5d": 7, "1mo": 31, "3mo": 93, "6mo": 186, "1y": 365,
             "3y": 1095, "5y": 1825, "10y": 3650}.get(period)
    if period == "ytd":
        start_date = datetime(datetime.now().year, 1, 1).date()
    elif start is None:
        start_date = (datetime.now() - timedelta(days=365 * 10)).date()
    else:
        start_date = (datetime.now() - timedelta(days=start)).date()
    with st.spinner("Loading price history…"):
        closes = load_batch_close(tuple(cmp_df.index), start_date, datetime.now().date())

    returns_12m = {}
    if not closes.empty:
        rebased = closes.dropna(how="all").ffill()
        rebased = rebased / rebased.bfill().iloc[0] * 100
        figc = go.Figure()
        for t in cmp_df.index:
            if t not in rebased.columns:
                continue
            series = rebased[t].dropna()
            if series.empty:
                continue
            returns_12m[t] = float(series.iloc[-1] / 100 - 1)
            figc.add_trace(go.Scatter(x=series.index, y=series, name=t, mode="lines",
                                      line=dict(width=3 if t == co.ticker else 1.8)))
        figc.add_hline(y=100, line_dash="dot", line_color=T["faint"])
        figc.update_yaxes(title_text="Rebased to 100 at the start")
        figc.update_layout(hovermode="x unified")
        style_fig(figc, height=400)
        figure(figc, f"Relative price performance over {period_label.lower()}",
               "Every company's price rebased to 100 on the first day shown, so the lines can be compared "
               "directly regardless of the actual share prices or currencies.",
               "The vertical gap between two lines at any date is the difference in total percentage return "
               "since the start. A line crossing another is a change in relative performance, which is more "
               "informative than either line alone.",
               "Rebasing removes the two things that make raw price charts misleading: differing share prices "
               "and differing currencies.",
               data=rebased)

    display_cols = ["Name", "Price", "P/E", "Fwd P/E", "P/B", "EV/EBITDA", "FCF Yield (%)",
                    "Op Margin (%)", "ROE (%)", "Revenue Growth (%)", "Net Debt/EBITDA", "Market Cap"]
    shown = cmp_df[[c for c in display_cols if c in cmp_df.columns]]
    table(shown, "Comparison matrix",
          f"The same metrics for every company, in {target_currency}. The highlighted row is the company "
          f"selected in the sidebar.",
          formats={"Price": "{:,.2f}", "P/E": "{:,.1f}", "Fwd P/E": "{:,.1f}", "P/B": "{:,.2f}",
                   "EV/EBITDA": "{:,.1f}", "FCF Yield (%)": "{:,.1f}%", "Op Margin (%)": "{:,.1f}%",
                   "ROE (%)": "{:,.1f}%", "Revenue Growth (%)": "{:+,.1f}%",
                   "Net Debt/EBITDA": "{:,.2f}", "Market Cap": lambda v: Fmt.money(v, sym)},
          highlight=co.ticker)

    # A like-for-like profile score. Deliberately built from the quote snapshot
    # alone (not the full statements) so adding a company to the comparison
    # costs one request rather than four.
    prof = pd.DataFrame(index=cmp_df.index)
    prof["Value"] = [np.nanmean([v for v in (
        scale(r.get("FCF Yield (%)"), 0, 8), scale(r.get("P/E"), 45, 10),
        scale(r.get("EV/EBITDA"), 25, 6), scale(r.get("P/B"), 8, 1)) if v is not None] or [np.nan])
        for _, r in cmp_df.iterrows()]
    prof["Profitability"] = [np.nanmean([v for v in (
        scale(r.get("Op Margin (%)"), 0, 30), scale(r.get("ROE (%)"), 0, 25)) if v is not None] or [np.nan])
        for _, r in cmp_df.iterrows()]
    prof["Growth"] = [scale(r.get("Revenue Growth (%)"), -5, 25) or np.nan for _, r in cmp_df.iterrows()]
    prof["Balance sheet"] = [scale(r.get("Net Debt/EBITDA"), 4, 0) or np.nan for _, r in cmp_df.iterrows()]
    prof["Momentum"] = [scale((returns_12m.get(t, np.nan) or 0) * 100, -30, 40) or np.nan for t in cmp_df.index]

    figp = go.Figure()
    for t in prof.index:
        figp.add_trace(go.Bar(name=t, x=prof.columns, y=prof.loc[t].values,
                              marker_line_width=2 if t == co.ticker else 0,
                              marker_line_color=T["accent"]))
    figp.update_yaxes(title_text="Score (0–100)", range=[0, 100])
    figp.update_layout(barmode="group")
    style_fig(figp, height=360)
    figure(figp, "Profile comparison across five dimensions",
           "Each company scored 0 to 100 on value, profitability, growth, balance-sheet strength and "
           "twelve-month momentum, using the same thresholds for all of them.",
           "Read the **shape**, not the total. A company scoring high on value and low on profitability is "
           "cheap for a reason; one high on both is the rarer case worth understanding. Bars are directly "
           "comparable because every company is scored on the same scale.",
           "Scores come from the quote snapshot rather than the full statements, so this is a screen for "
           "where to look, not a substitute for section 1's deeper scorecard.",
           data=prof)

    if not closes.empty and closes.shape[1] > 1:
        corr = closes.pct_change().corr()
        figcor = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index,
                                      colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
                                      text=[[f"{v:.2f}" for v in row] for row in corr.values],
                                      texttemplate="%{text}", textfont={"size": 12}))
        style_fig(figcor, height=90 + 46 * len(corr), legend="off")
        figure(figcor, "Correlation of daily returns",
               "How closely each pair of companies has moved together over the period shown. 1.00 is "
               "lockstep, 0 is unrelated, negative means they move against each other.",
               "High correlation across the whole grid means these names are effectively one bet — owning "
               "several of them diversifies far less than the count suggests. Look for the lowest pairs if "
               "diversification is the goal.",
               "Two businesses can look different and still trade as one position, particularly within a "
               "single sector or when a shared macro factor dominates.",
               data=corr)

    best_val = prof["Value"].idxmax() if prof["Value"].notna().any() else None
    best_prof = prof["Profitability"].idxmax() if prof["Profitability"].notna().any() else None
    best_growth = prof["Growth"].idxmax() if prof["Growth"].notna().any() else None
    note(f"""
Across the {len(cmp_df)} companies compared:
- **Cheapest on the value measures:** {best_val or Fmt.NA}. **Most profitable:** {best_prof or Fmt.NA}.
**Fastest growing:** {best_growth or Fmt.NA}.
- These rarely coincide, and when they do it is usually a signal to check whether one of the inputs is
distorted by a one-off item rather than a sign of a free lunch.
- **Comparison is only as good as the set.** Adding a company that does not really belong drags every median
and every relative judgement with it. Companies in different currencies are converted here, but differences
in accounting standards and reporting conventions are not adjusted away.
""", tone="neu")


# ==============================================================================
elif view == "Investment Simulator":
    section("What an investment would have returned",
            "Put a sum into this company on a past date and follow what it would be worth now, against the "
            "same sum put into a benchmark.")

    hist_all = co.history("max", "1d")
    if hist_all.empty or "Close" not in hist_all:
        empty_state("No price history available for this symbol.")
        st.stop()

    px_all = hist_all["Close"].dropna()
    px_all.index = pd.to_datetime(px_all.index).tz_localize(None)
    first_day, last_day = px_all.index[0].date(), px_all.index[-1].date()

    i1, i2, i3, i4 = st.columns([1, 1, 1, 1])
    with i1:
        amount = st.number_input(f"Initial investment ({sym})", min_value=100.0, value=10000.0, step=500.0)
    with i2:
        horizon = segmented("Invested since", ["1y", "3y", "5y", "10y", "Custom"], key="sim_horizon",
                            default_index=2)
    with i3:
        years_map = {"1y": 1, "3y": 3, "5y": 5, "10y": 10}
        proposed = (datetime.now() - timedelta(days=365 * years_map.get(horizon, 5))).date()
        default_start = max(first_day, min(proposed, last_day - timedelta(days=5)))
        start_day = st.date_input("Start date", value=default_start,
                                  min_value=first_day, max_value=last_day - timedelta(days=1),
                                  disabled=(horizon != "Custom"))
        if horizon != "Custom":
            start_day = default_start
    with i4:
        monthly = st.number_input(f"Added every month ({sym})", min_value=0.0, value=0.0, step=100.0,
                                  help="Set above zero to simulate regular contributions alongside the "
                                       "initial sum.")

    bench_choice = st.selectbox("Benchmark", ["SPY — S&P 500", "QQQ — Nasdaq 100", "None"], index=0)
    bench_symbol = bench_choice.split(" ")[0] if bench_choice != "None" else None

    window = px_all[px_all.index >= pd.Timestamp(start_day)] * fx
    if window.empty or len(window) < 5:
        empty_state("Not enough price history after that date.",
                    f"This symbol's history starts on {first_day:%d %b %Y}.")
        st.stop()
    if pd.Timestamp(start_day) < px_all.index[0]:
        st.caption(f"History for {co.ticker} starts on {first_day:%d %b %Y}, so the simulation begins there.")

    def simulate_position(prices: pd.Series, initial: float, monthly_amount: float):
        """Buys `initial` on the first day, then `monthly_amount` on the first
        trading day of each subsequent month. Prices are split- and
        dividend-adjusted by the data source, so this is a total-return
        simulation with dividends reinvested."""
        shares = initial / float(prices.iloc[0])
        invested = initial
        contributions = pd.Series(0.0, index=prices.index)
        contributions.iloc[0] = initial
        if monthly_amount > 0:
            month_starts = prices.groupby([prices.index.year, prices.index.month]).head(1).index[1:]
            for d in month_starts:
                shares += monthly_amount / float(prices.loc[d])
                invested += monthly_amount
                contributions.loc[d] += monthly_amount
        share_path = (contributions / prices).cumsum()
        return share_path * prices, invested, contributions.cumsum()

    value, invested, cost_path = simulate_position(window, amount, monthly)
    final = float(value.iloc[-1])
    years = max((window.index[-1] - window.index[0]).days / 365.25, 1e-9)
    total_return = final / invested - 1
    annualised = cagr(invested, final, years)
    peak = value.cummax()
    worst_dd = float((value / peak - 1).min())

    bench_value = None
    if bench_symbol:
        bh = load_history(bench_symbol, "max", "1d")
        if not bh.empty and "Close" in bh:
            bp = bh["Close"].dropna()
            bp.index = pd.to_datetime(bp.index).tz_localize(None)
            bp = bp[bp.index >= window.index[0]]
            bp = bp.reindex(window.index).ffill().bfill()
            if not bp.empty:
                bench_value, _, _ = simulate_position(bp, amount, monthly)

    kpi_grid([
        {"label": "Value today", "value": Fmt.money(final, sym),
         "sub": f"From {Fmt.money(invested, sym)} invested", "tone": "good" if final > invested else "bad"},
        {"label": "Profit", "value": Fmt.money(final - invested, sym),
         "sub": Fmt.as_pct(total_return, signed=True) + " on money in",
         "tone": "good" if final > invested else "bad"},
        {"label": "Annualised return", "value": Fmt.as_pct(annualised),
         "sub": f"Over {years:,.1f} years", "tone": tone_for((annualised or 0) * 100, 8, 0)},
        {"label": "Deepest fall along the way", "value": Fmt.as_pct(worst_dd),
         "sub": "Largest drop from a peak while holding", "tone": tone_for(worst_dd * 100, -20, -45),
         "help": "The return is the destination; this is the journey. It is what would actually have tested "
                 "your conviction."},
        {"label": "Benchmark value", "value": Fmt.money(float(bench_value.iloc[-1]) if bench_value is not None else None, sym),
         "sub": f"Same schedule into {bench_symbol}" if bench_symbol else "No benchmark selected",
         "tone": ("good" if bench_value is not None and final > float(bench_value.iloc[-1]) else "bad")
                 if bench_value is not None else "flat"},
    ], min_width=205)

    figsim = go.Figure()
    figsim.add_trace(go.Scatter(x=value.index, y=value, name=f"{co.ticker} position",
                                line=dict(color=T["accent"], width=2.6), fill="tozeroy",
                                fillcolor=f"rgba(99,102,241,0.10)"))
    if bench_value is not None:
        figsim.add_trace(go.Scatter(x=bench_value.index, y=bench_value, name=f"{bench_symbol} benchmark",
                                    line=dict(color=T["warning"], width=2, dash="dash")))
    figsim.add_trace(go.Scatter(x=cost_path.index, y=cost_path, name="Money invested",
                                line=dict(color=T["faint"], width=1.5, dash="dot")))
    figsim.update_yaxes(title_text=f"Value ({sym})")
    figsim.update_layout(hovermode="x unified")
    style_fig(figsim, height=420)
    figure(figsim, f"Value of the investment since {window.index[0]:%d %b %Y}",
           f"What {Fmt.money(amount, sym)}"
           + (f" plus {Fmt.money(monthly, sym)} a month" if monthly else "")
           + f" put into {co.ticker} would be worth, against the same schedule into a benchmark and against "
             "the cash actually contributed.",
           "The dotted line is money in; everything above it is gain. Where the position line dips **below** "
           "the dotted line, the investment was under water — the periods that matter for whether a strategy "
           "is one you could actually have stuck with.",
           "Prices here are adjusted for dividends and splits, so this is a total-return figure: dividends "
           "are assumed reinvested on the day they are paid.",
           data=pd.DataFrame({"Position": value, "Invested": cost_path,
                              **({"Benchmark": bench_value} if bench_value is not None else {})}))

    rolling = value.pct_change(252).dropna()
    if not rolling.empty:
        figroll = go.Figure(go.Histogram(x=rolling * 100, nbinsx=45, marker_color=T["accent_soft"], opacity=.85))
        figroll.add_vline(x=0, line_dash="dash", line_color=T["danger"])
        figroll.update_xaxes(title_text="Rolling one-year return (%)")
        figroll.update_yaxes(title_text="Number of days")
        style_fig(figroll, height=300, legend="off")
        share_negative = float((rolling < 0).mean())
        figure(figroll, "Distribution of rolling one-year returns while holding",
               "Every possible one-year holding period inside this window, and what it returned.",
               "The share of the distribution left of the dashed line is how often a one-year holder would "
               "have been down. Here that is **" + Fmt.as_pct(share_negative) + "** of all start dates.",
               "A single historical path flatters or damns an investment depending on when you happened to "
               "start. This shows the whole range of entry points instead of the one you picked.")

    excess = None
    if bench_value is not None:
        excess = final / float(bench_value.iloc[-1]) - 1
    note(f"""
{Fmt.money(invested, sym)} invested {'from ' + window.index[0].strftime('%d %B %Y') if not monthly else 'on this schedule since ' + window.index[0].strftime('%d %B %Y')}
would be **{Fmt.money(final, sym)}** today — {Fmt.as_pct(total_return, signed=True)} in total, or
**{Fmt.as_pct(annualised)} a year**.
- {'That is ' + Fmt.as_pct(excess, signed=True) + ' against the same money in ' + str(bench_symbol) + '. Beating a broad index over one specific window is not evidence of skill; the window matters enormously.' if excess is not None else 'No benchmark was selected, so there is nothing here to say whether the return was good relative to simply owning the market.'}
- **The drawdown is the real test.** This position fell {Fmt.as_pct(worst_dd)} from its peak at the worst
point. Returns are only collected by holders who did not sell there.
- **Past performance is a description, not a forecast.** The single largest determinant of the number above is
the start date, which is why the rolling distribution matters more than the headline.
""", tone="pos" if total_return > 0 else "warn")


# ==============================================================================
elif view == "Portfolio":
    section("Holdings",
            "Enter what you own. Everything below — allocation drift, concentration limits, and both measures "
            "of return — is computed from this table and refreshed with live prices. Nothing is stored "
            "anywhere: the table lives in this browser session only.")

    CATEGORIES = ["Core equity", "International equity", "Fixed income & cash", "Other"]
    if "portfolio_rows" not in st.session_state:
        st.session_state.portfolio_rows = pd.DataFrame([
            {"Ticker": "AAPL", "Shares": 40.0, "Cost per share": 150.0,
             "Purchased": (datetime.now() - timedelta(days=730)).date(), "Category": "Core equity"},
            {"Ticker": "MSFT", "Shares": 25.0, "Cost per share": 280.0,
             "Purchased": (datetime.now() - timedelta(days=500)).date(), "Category": "Core equity"},
            {"Ticker": "SAP.DE", "Shares": 60.0, "Cost per share": 120.0,
             "Purchased": (datetime.now() - timedelta(days=400)).date(), "Category": "International equity"},
        ])

    edited = st.data_editor(
        st.session_state.portfolio_rows, num_rows="dynamic", key="portfolio_editor",
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", help="Any symbol the data source knows.", width="small"),
            "Shares": st.column_config.NumberColumn("Shares", min_value=0.0, step=1.0, format="%.4f"),
            "Cost per share": st.column_config.NumberColumn(
                f"Cost per share", min_value=0.0, step=1.0, format="%.2f",
                help="In the security's own currency. Leave at zero to use the closing price on the "
                     "purchase date."),
            "Purchased": st.column_config.DateColumn("Purchased", format="YYYY-MM-DD"),
            "Category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, width="medium"),
        }, **FILL_DF)

    rows = edited.dropna(subset=["Ticker"]).copy()
    rows = rows[(rows["Ticker"].astype(str).str.strip() != "") & (rows["Shares"].fillna(0) > 0)]
    if rows.empty:
        empty_state("Add at least one holding to see the analysis.",
                    "Enter a ticker, the number of shares, and the date you bought them.")
        st.stop()
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Category"] = rows["Category"].fillna("Other")
    rows["Purchased"] = pd.to_datetime(rows["Purchased"]).dt.date

    holdings_key = tuple(
        (str(t), float(sh), float(c or 0), str(d))
        for t, sh, c, d in zip(rows["Ticker"], rows["Shares"], rows["Cost per share"].fillna(0), rows["Purchased"]))

    with st.spinner(f"Pricing {len(rows)} holdings…"):
        quotes = load_comparables(tuple(dict.fromkeys(rows["Ticker"])), target_currency)

    if quotes.empty:
        empty_state("None of those symbols could be priced right now.")
        st.stop()

    rows["Price"] = rows["Ticker"].map(quotes["Price"])
    rows["Value"] = rows["Price"] * rows["Shares"]
    rows = rows.dropna(subset=["Value"])
    if rows.empty:
        empty_state("None of those symbols could be priced right now.")
        st.stop()
    total_value = float(rows["Value"].sum())
    rows["Weight %"] = rows["Value"] / total_value * 100
    rows["Cost value"] = rows["Cost per share"].fillna(0) * rows["Shares"]
    rows["Gain %"] = np.where(rows["Cost value"] > 0,
                              (rows["Value"] / rows["Cost value"] - 1) * 100, np.nan)

    kpi_grid([
        {"label": "Portfolio value", "value": Fmt.money(total_value, sym),
         "sub": f"{len(rows)} positions across {rows['Category'].nunique()} categories", "tone": "flat"},
        {"label": "Largest position", "value": f"{rows.loc[rows['Value'].idxmax(), 'Ticker']}"
                                               f" · {rows['Weight %'].max():,.1f}%",
         "sub": Fmt.money(rows["Value"].max(), sym),
         "tone": "bad" if rows["Weight %"].max() > 25 else "warn" if rows["Weight %"].max() > 15 else "good"},
        {"label": "Unrealised gain", "value": Fmt.money(
            float(rows["Value"].sum() - rows["Cost value"].sum()) if (rows["Cost value"] > 0).all() else None, sym),
         "sub": Fmt.pct(float((rows["Value"].sum() / rows["Cost value"].sum() - 1) * 100), signed=True)
                if rows["Cost value"].sum() > 0 else "Enter a cost basis to see this",
         "tone": "good" if rows["Value"].sum() >= rows["Cost value"].sum() else "bad"},
        {"label": "Effective positions", "value": Fmt.ratio(
            1 / ((rows["Weight %"] / 100) ** 2).sum(), 1, suffix=""),
         "sub": "Inverse Herfindahl: how many equal-sized positions this is really equivalent to",
         "tone": "flat",
         "help": "A portfolio of ten names where one is 60% behaves like a portfolio of about three."},
    ], min_width=210)

    holdings_view = rows[["Ticker", "Category", "Shares", "Price", "Value", "Weight %", "Gain %"]].set_index("Ticker")
    table(holdings_view, "Current holdings",
          f"Live prices converted to {target_currency}. Gain is against the cost basis entered above.",
          formats={"Shares": "{:,.4f}", "Price": "{:,.2f}", "Value": lambda v: Fmt.money(v, sym),
                   "Weight %": "{:,.1f}%", "Gain %": "{:+,.1f}%"})

    # --- Allocation against policy targets -----------------------------------
    section("Allocation against target",
            "Policy targets say where the portfolio should sit. Drift says how far it has moved, and where "
            "new money should go to close the gap without selling anything.")

    t_cols = st.columns(len(CATEGORIES))
    defaults = {"Core equity": 60, "International equity": 20, "Fixed income & cash": 20, "Other": 0}
    targets = {}
    for c, cat in zip(t_cols, CATEGORIES):
        with c:
            targets[cat] = st.number_input(f"{cat} target %", 0, 100, defaults[cat], 5, key=f"tgt_{cat}")
    target_total = sum(targets.values())
    if target_total != 100:
        st.warning(f"Targets add up to {target_total}%, not 100%. The drift below is measured against the "
                   f"targets as entered, so normalise them before acting on it.")

    actual = rows.groupby("Category")["Value"].sum().reindex(CATEGORIES).fillna(0.0)
    alloc = pd.DataFrame({
        "Target %": [targets[c] for c in CATEGORIES],
        "Actual %": (actual / total_value * 100).values,
        "Value": actual.values,
    }, index=CATEGORIES)
    alloc["Drift (pp)"] = alloc["Actual %"] - alloc["Target %"]
    alloc["To target"] = (alloc["Target %"] / 100 * total_value) - alloc["Value"]

    a1, a2 = st.columns([1.25, 1])
    with a1:
        figal = go.Figure()
        figal.add_trace(go.Bar(x=CATEGORIES, y=alloc["Target %"], name="Target",
                               marker_color=T["faint"], opacity=.55))
        figal.add_trace(go.Bar(x=CATEGORIES, y=alloc["Actual %"], name="Actual",
                               marker_color=T["accent_soft"]))
        figal.update_yaxes(title_text="% of portfolio", ticksuffix="%")
        figal.update_layout(barmode="group")
        style_fig(figal, height=330)
        figure(figal, "Actual allocation against policy target",
               "Each category's current share of the portfolio beside the target you set.",
               "The gap between the pale target bar and the solid actual bar is the drift. Drift builds "
               "quietly: the category that performs best grows its own weight, so a portfolio left alone "
               "becomes progressively more concentrated in whatever has already run.",
               "Rebalancing by directing new contributions at the underweight categories closes drift "
               "without realising gains, which is the difference between a tax event and a free adjustment.",
               data=alloc)
    with a2:
        new_capital = st.number_input(f"New capital to deploy ({sym})", min_value=0.0, value=10000.0, step=1000.0)
        shortfall = ((alloc["Target %"] / 100) * (total_value + new_capital) - alloc["Value"]).clip(lower=0)
        suggestion = (shortfall / shortfall.sum() * new_capital) if shortfall.sum() > 0 else shortfall * 0
        plan = pd.DataFrame({"Add": suggestion,
                             "Weight after": ((alloc["Value"] + suggestion) / (total_value + new_capital) * 100)})
        table(plan, "Where new capital should go",
              "Directing the new money entirely at underweight categories, with no sales.",
              formats={"Add": lambda v: Fmt.money(v, sym), "Weight after": "{:,.1f}%"})

    # --- Concentration guardrails --------------------------------------------
    limit = st.slider("Concentration limit for a single holding (% of portfolio)", 5, 40, 15, 1,
                      help="Positions above this share of the portfolio are flagged. Single-stock risk is "
                           "the risk no amount of analysis removes.")
    breaches = rows[rows["Weight %"] > limit].sort_values("Weight %", ascending=False)
    checks = []
    for _, r in rows.sort_values("Weight %", ascending=False).iterrows():
        state = "fail" if r["Weight %"] > limit else "warn" if r["Weight %"] > limit * 0.75 else "pass"
        trim = (r["Weight %"] - limit) / 100 * total_value
        checks.append({
            "label": f"{r['Ticker']} · {r['Weight %']:,.1f}%",
            "state": state,
            "value": Fmt.money(r["Value"], sym),
            "detail": (f"over the {limit}% limit — trimming {Fmt.money(trim, sym)} would bring it back within"
                       if state == "fail" else
                       "approaching the limit; new money is better directed elsewhere" if state == "warn"
                       else "within the limit"),
        })
    checklist(checks)
    if not breaches.empty:
        breach_list = ", ".join(f"{t} at {w:,.1f}%" for t, w in zip(breaches["Ticker"], breaches["Weight %"]))
        note(f"""
**{len(breaches)} position{'s' if len(breaches) > 1 else ''} exceed{'' if len(breaches) > 1 else 's'} the
{limit}% limit**: {breach_list}.
- A single holding above roughly 15% means one company-specific surprise — a failed product, an accounting
restatement, a regulatory action — can set the whole portfolio back by more than a normal bear market would.
- The fix does not have to be a sale. Directing every new contribution elsewhere shrinks the weight over time
without realising a gain, which is usually the cheaper route.
- Concentration is not automatically wrong; it is a deliberate choice. The question is whether it was chosen or
simply arrived at because a winner was left to run.
""", tone="warn")

    # --- Performance ----------------------------------------------------------
    section("Performance attribution",
            "Two different questions: how the assets performed, and how your money performed. They differ "
            "whenever contributions were not evenly timed.")

    with st.spinner("Rebuilding the portfolio's daily history…"):
        per_ticker, value_series, flows_market, flows_cash = load_portfolio_history(
            holdings_key, target_currency)

    if value_series is None or value_series.empty:
        empty_state("Could not rebuild a price history for these holdings.",
                    "This usually means one of the symbols has no history at the purchase date entered.")
    else:
        value_series = value_series[value_series > 0]
        flows_market = flows_market.reindex(value_series.index).fillna(0.0)
        flows_cash = flows_cash.reindex(value_series.index).fillna(0.0)
        days = max((value_series.index[-1] - value_series.index[0]).days, 1)
        tw = twrr(value_series, flows_market)
        tw_annual = ((1 + tw) ** (365.0 / days) - 1) if tw is not None and tw > -1 else None
        cashflows = [(d, -amt) for d, amt in flows_cash[flows_cash > 0].items()]
        cashflows.append((value_series.index[-1], float(value_series.iloc[-1])))
        mw = xirr(cashflows)
        invested_total = float(flows_cash.sum())

        bench_sym = st.selectbox("Benchmark", ["SPY — S&P 500", "QQQ — Nasdaq 100", "None"], index=0,
                                 key="pf_bench").split(" ")[0]
        bench_series = None
        if bench_sym != "None":
            bh = load_history(bench_sym, "max", "1d")
            if not bh.empty and "Close" in bh:
                bp = bh["Close"].dropna()
                bp.index = pd.to_datetime(bp.index).tz_localize(None)
                bench_series = bp.reindex(value_series.index).ffill().bfill()

        bench_return = float(bench_series.iloc[-1] / bench_series.iloc[0] - 1) if bench_series is not None else None
        kpi_grid([
            {"label": "Time-weighted return", "value": Fmt.as_pct(tw),
             "sub": f"{Fmt.as_pct(tw_annual)} a year · comparable with an index",
             "tone": "good" if (tw or 0) > 0 else "bad",
             "help": "Removes the effect of when money was added, so it measures the holdings themselves. "
                     "This is what fund performance tables report."},
            {"label": "Money-weighted return", "value": Fmt.as_pct(mw),
             "sub": "Annualised internal rate of return on your actual cash",
             "tone": "good" if (mw or 0) > 0 else "bad",
             "help": "Your personal return, which rewards or penalises the timing of contributions. If it "
                     "beats the time-weighted figure, your timing helped."},
            {"label": "Benchmark over the same window", "value": Fmt.as_pct(bench_return),
             "sub": f"{bench_sym} total return" if bench_sym != "None" else "No benchmark selected",
             "tone": ("good" if (tw or 0) > (bench_return or 0) else "bad") if bench_return is not None else "flat"},
            {"label": "Capital deployed", "value": Fmt.money(invested_total, sym),
             "sub": f"Valued at {Fmt.money(float(value_series.iloc[-1]), sym)} on the price history used here",
             "tone": "flat",
             "help": "This series is rebuilt from daily closing prices, so it can differ slightly from the "
                     "live quote total above, which uses the latest intraday price."},
        ], min_width=215)

        figpf = go.Figure()
        rebased_pf = value_series / value_series.iloc[0] * 100
        figpf.add_trace(go.Scatter(x=rebased_pf.index, y=rebased_pf, name="Portfolio",
                                   line=dict(color=T["accent"], width=2.6)))
        if bench_series is not None:
            rb = bench_series / bench_series.iloc[0] * 100
            figpf.add_trace(go.Scatter(x=rb.index, y=rb, name=bench_sym,
                                       line=dict(color=T["warning"], width=2, dash="dash")))
        figpf.update_yaxes(title_text="Rebased to 100")
        figpf.update_layout(hovermode="x unified")
        style_fig(figpf, height=380)
        figure(figpf, "Portfolio against benchmark",
               "The portfolio's value rebased to 100 at the earliest purchase date, beside the benchmark over "
               "exactly the same window.",
               "Because the portfolio line includes money added along the way, it is not a pure performance "
               "line — the time-weighted figure above is. Use this chart for the **shape**: where the two "
               "diverge, and whether the gap came from one episode or accumulated steadily.",
               "Beating a benchmark over a window that starts at a date you chose is weak evidence. The value "
               "is in seeing when the portfolio behaved differently from the market, and asking why.",
               data=pd.DataFrame({"Portfolio": rebased_pf,
                                  **({bench_sym: bench_series / bench_series.iloc[0] * 100}
                                     if bench_series is not None else {})}))

        gap = (tw - mw) if (tw is not None and mw is not None) else None
        note(f"""
The holdings returned **{Fmt.as_pct(tw)}** time-weighted over this window, while the money actually invested
earned **{Fmt.as_pct(mw)}** annualised.
- **The difference is timing.** {'The money-weighted figure trails the time-weighted one, which means larger contributions went in before weaker stretches.' if (gap or 0) > 0.005 else 'The money-weighted figure leads, which means contributions happened to land before stronger stretches.' if (gap or 0) < -0.005 else 'The two are close, which means contribution timing has had little effect either way.'}
- **Compare the right one.** Time-weighted is the fair comparison against an index, because an index has no
contributions. Money-weighted is the honest answer to "how did I do".
- {'The portfolio ' + ('beat' if (tw or 0) > (bench_return or 0) else 'trailed') + f' {bench_sym} over the same window ({Fmt.as_pct(bench_return)}).' if bench_return is not None else 'No benchmark selected, so there is nothing to say whether this was good or bad in context.'}
""", tone="pos" if (tw or 0) > (bench_return or 0) else "neu")

    # --- Fundamentals of what is held -----------------------------------------
    section("What the portfolio owns, fundamentally",
            "Valuation and quality for every holding, so the portfolio can be judged as a collection of "
            "businesses rather than a list of tickers.")
    fund_cols = ["Name", "P/E", "Fwd P/E", "EV/EBITDA", "FCF Yield (%)", "Op Margin (%)",
                 "ROE (%)", "Net Debt/EBITDA", "Revenue Growth (%)"]
    fund = quotes[[c for c in fund_cols if c in quotes.columns]].copy()
    weights = rows.groupby("Ticker")["Value"].sum() / total_value
    fund.insert(1, "Weight %", (weights.reindex(fund.index) * 100))
    table(fund, "Holdings on fundamentals",
          "Weighted by position size, so the metrics that matter most are the ones attached to the largest rows.",
          formats={"Weight %": "{:,.1f}%", "P/E": "{:,.1f}", "Fwd P/E": "{:,.1f}", "EV/EBITDA": "{:,.1f}",
                   "FCF Yield (%)": "{:,.1f}%", "Op Margin (%)": "{:,.1f}%", "ROE (%)": "{:,.1f}%",
                   "Net Debt/EBITDA": "{:,.2f}", "Revenue Growth (%)": "{:+,.1f}%"})

    w = weights.reindex(fund.index).fillna(0)
    def weighted(colname):
        if colname not in fund.columns:
            return None
        vals = fund[colname]
        mask = vals.notna() & (w > 0)
        return float((vals[mask] * w[mask]).sum() / w[mask].sum()) if mask.any() else None

    kpi_grid([
        {"label": "Weighted P/E", "value": Fmt.ratio(weighted("P/E")),
         "sub": "Portfolio-level earnings multiple", "tone": "flat"},
        {"label": "Weighted EV/EBITDA", "value": Fmt.ratio(weighted("EV/EBITDA")),
         "sub": "Capital-structure neutral", "tone": "flat"},
        {"label": "Weighted operating margin", "value": Fmt.pct(weighted("Op Margin (%)")),
         "sub": "Quality of the underlying businesses", "tone": "flat"},
        {"label": "Weighted revenue growth", "value": Fmt.pct(weighted("Revenue Growth (%)"), signed=True),
         "sub": "How fast the portfolio's businesses are growing", "tone": "flat"},
        {"label": "Weighted net debt / EBITDA", "value": Fmt.ratio(weighted("Net Debt/EBITDA")),
         "sub": "Leverage carried through the holdings", "tone": "flat"},
    ], min_width=200)


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
                "title": f"{co.name} ({co.ticker}) — {view}",
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
                               file_name=f"{co.ticker}_{view.lower().replace(' ', '_')}_report.html",
                               mime="text/html", type="primary", **FILL_DL)
            if st.button("Clear", **FILL_BTN):
                st.session_state["_export"] = False
                st.rerun()

with x2:
    with st.expander("Data provenance", expanded=False):
        rows = [
            ("Primary source", DATA_SOURCE),
            ("Served by", ", ".join(f"{k}: {v}" for k, v in
                                    (st.session_state.get(SOURCE_LOG_KEY) or {}).items())
                          or "everything on this page came from the in-session cache"),
            ("Backups available", "Stooq (prices, most developed markets) · "
                                  "SEC EDGAR XBRL (statements, US filers)"),
            ("Quote endpoint", f"{quote_fields} of {len(QUOTE_METRICS)} headline metrics returned"),
            ("Primary filings", (f"<a href='{filing_source(co.ticker)['url']}' target='_blank'>"
                                 f"{filing_source(co.ticker)['name']}</a>"
                                 if filing_source(co.ticker)["url"] else filing_source(co.ticker)["name"])),
            ("Computed locally", f"{len(co.derived)} field(s)" + (f" — {', '.join(sorted(co.derived))}"
                                                                  if co.derived else "")),
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
