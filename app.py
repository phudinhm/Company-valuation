import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import yfinance as yf
import time
from datetime import datetime, timedelta
from scipy.stats import norm, linregress

# ==============================================================================
# 1. PAGE CONFIGURATION & ADVANCED CSS
# ==============================================================================
st.set_page_config(
    page_title="Investment Terminal Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- THEME MANAGEMENT ---
if 'theme' not in st.session_state:
    st.session_state.theme = "Light"

def get_theme_css(theme):
    """Returns CSS variables based on selected theme."""
    if theme == "Dark":
        return """
        :root {
            --bg-color: #0e1117;
            --card-bg: #1e2130;
            --text-color: #fafafa;
            --secondary-text: #b0b0b0;
            --border-color: #303030;
            --accent-color: #4da6ff;
            --success-color: #00e676;
            --danger-color: #ff5252;
            --warning-color: #ffab40;
            --box-insight-bg: #112924;
            --box-insight-border: #004d40;
            --box-insight-text: #80cbc4;
            --box-warn-bg: #2b1111;
            --box-warn-border: #4a1515;
            --box-warn-text: #ef9a9a;
            --box-info-bg: #101924;
            --box-info-border: #0d2745;
            --box-info-text: #90caf9;
        }
        """
    elif theme == "Sepia":
        return """
        :root {
            --bg-color: #f4ecd8;
            --card-bg: #fff9e6;
            --text-color: #433422;
            --secondary-text: #5b4636;
            --border-color: #dcd0b0;
            --accent-color: #8c6b5d;
            --success-color: #388e3c;
            --danger-color: #d32f2f;
            --warning-color: #f57c00;
            --box-insight-bg: #e8f5e9;
            --box-insight-border: #c8e6c9;
            --box-insight-text: #2e7d32;
            --box-warn-bg: #ffebee;
            --box-warn-border: #ffcdd2;
            --box-warn-text: #c62828;
            --box-info-bg: #e3f2fd;
            --box-info-border: #bbdefb;
            --box-info-text: #1565c0;
        }
        """
    else: # Light (Default)
        return """
        :root {
            --bg-color: #f8f9fa;
            --card-bg: #ffffff;
            --text-color: #2c3e50;
            --secondary-text: #7f8c8d;
            --border-color: #e0e0e0;
            --accent-color: #3498db;
            --success-color: #27ae60;
            --danger-color: #c0392b;
            --warning-color: #f39c12;
            --box-insight-bg: #e8f8f5;
            --box-insight-border: #1abc9c;
            --box-insight-text: #0e6251;
            --box-warn-bg: #fdedec;
            --box-warn-border: #e74c3c;
            --box-warn-text: #78281f;
            --box-info-bg: #ebf5fb;
            --box-info-border: #3498db;
            --box-info-text: #154360;
        }
        """

# Inject CSS
current_theme_css = get_theme_css(st.session_state.theme)
st.markdown(f"""
<style>
    /* IMPORT FONTS */
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap');
    
    {current_theme_css}

    html, body, [class*="css"] {{
        font-family: 'Roboto', sans-serif;
        color: var(--text-color);
        background-color: var(--bg-color);
    }}

    /* SIDEBAR STYLING */
    [data-testid="stSidebar"] {{
        background-color: var(--card-bg);
        border-right: 1px solid var(--border-color);
    }}
    [data-testid="stSidebar"] * {{
        color: var(--text-color) !important;
    }}

    /* KPI CARD DESIGN */
    .kpi-container {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 20px;
    }}
    
    .kpi-card {{
        background-color: var(--card-bg);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border-left: 4px solid var(--accent-color);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        color: var(--text-color);
    }}
    
    .kpi-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.1);
    }}
    
    .kpi-label {{
        font-size: 11px;
        color: var(--secondary-text);
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
        margin-bottom: 5px;
    }}
    
    .kpi-value {{
        font-size: 26px;
        font-weight: 700;
        color: var(--text-color);
        font-family: 'IBM Plex Mono', monospace;
    }}
    
    .kpi-delta {{
        font-size: 13px;
        font-weight: 600;
        display: flex;
        align-items: center;
        margin-top: 5px;
    }}
    
    .kpi-delta.positive {{ color: var(--success-color); }}
    .kpi-delta.negative {{ color: var(--danger-color); }}

    /* ANALYSIS BOXES */
    .analysis-box {{
        padding: 20px;
        border-radius: 8px;
        margin: 15px 0;
        font-size: 14px;
        line-height: 1.6;
        border-left-width: 5px;
        border-left-style: solid;
    }}
    
    .box-insight {{
        background-color: var(--box-insight-bg);
        border-left-color: var(--box-insight-border);
        color: var(--box-insight-text);
    }}
    
    .box-warning {{
        background-color: var(--box-warn-bg);
        border-left-color: var(--box-warn-border);
        color: var(--box-warn-text);
    }}
    
    .box-info {{
        background-color: var(--box-info-bg);
        border-left-color: var(--box-info-border);
        color: var(--box-info-text);
    }}

    /* TABS & DATAFRAMES */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 10px;
        background-color: transparent;
    }}
    
    .stTabs [data-baseweb="tab"] {{
        height: 50px;
        white-space: pre-wrap;
        background-color: var(--card-bg);
        border-radius: 6px;
        border: 1px solid var(--border-color);
        font-weight: 500;
        padding: 0 20px;
        color: var(--text-color);
    }}
    
    .stTabs [aria-selected="true"] {{
        background-color: var(--accent-color);
        color: #ffffff !important;
        border: none;
    }}

    .dataframe {{
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 12px !important;
        color: var(--text-color) !important;
        background-color: var(--card-bg) !important;
    }}

    /* FOOTER */
    .footer {{
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: var(--card-bg);
        color: var(--secondary-text);
        text-align: center;
        padding: 10px;
        font-size: 12px;
        border-top: 1px solid var(--border-color);
        z-index: 999;
    }}
    
    /* INPUTS */
    div[data-baseweb="select"] > div {{
        background-color: var(--card-bg);
        color: var(--text-color);
    }}
    div[data-baseweb="input"] > div {{
        background-color: var(--card-bg);
        color: var(--text-color);
    }}
</style>
""", unsafe_allow_html=True)

# Determine Plotly Template based on Theme
plotly_template = "plotly_white"
if st.session_state.theme == "Dark":
    plotly_template = "plotly_dark"
elif st.session_state.theme == "Sepia":
    plotly_template = "simple_white" # Closest proxy, we customize colors elsewhere

# ==============================================================================
# 2. UTILITY & HELPER CLASSES
# ==============================================================================

class Utils:
    """Core utility functions for formatting and safe calculations."""
    
    @staticmethod
    def format_currency(num, symbol="$"):
        if num is None: return "N/A"
        if abs(num) >= 1e12: return f"{symbol}{num/1e12:.2f}T"
        if abs(num) >= 1e9: return f"{symbol}{num/1e9:.2f}B"
        if abs(num) >= 1e6: return f"{symbol}{num/1e6:.2f}M"
        if abs(num) >= 1e3: return f"{symbol}{num/1e3:.2f}K"
        return f"{symbol}{num:,.2f}"

    @staticmethod
    def format_percent(num):
        if num is None: return "N/A"
        return f"{num * 100:.2f}%"

    @staticmethod
    def format_number(num):
        if num is None: return "N/A"
        if abs(num) >= 1e9: return f"{num/1e9:.2f}B"
        if abs(num) >= 1e6: return f"{num/1e6:.2f}M"
        return f"{num:,.2f}"

    @staticmethod
    def safe_div(n, d):
        return n / d if d and d != 0 else 0

    @staticmethod
    def get_cagr(start, end, periods):
        if start <= 0 or periods == 0: return 0
        return (end / start) ** (1 / periods) - 1
        
    @staticmethod
    def get_financial_section(df, items, indent=False):
        """Extracts specific financial items from the DataFrame (assumes items are in INDEX)."""
        existing_items = df.index.tolist()
        ordered_items = []
        
        for item in items:
            # Case insensitive check or direct check
            if item in existing_items:
                ordered_items.append(item)
        
        subset = df.loc[ordered_items].copy() if ordered_items else pd.DataFrame()
        if indent and not subset.empty:
            subset.index = ["   " + idx for idx in subset.index]
        return subset

class CurrencyFX:
    """Handles Currency Conversion Logic"""
    @staticmethod
    @st.cache_data(ttl=3600) # Cache rates for 1 hour
    def get_fx_rate(from_curr, to_curr):
        if from_curr == to_curr: return 1.0
        try:
            rate_to_usd = 1.0
            if from_curr != "USD":
                if from_curr in ["EUR", "GBP", "AUD", "NZD"]:
                    t = yf.Ticker(f"{from_curr}USD=X")
                    hist = t.history(period="1d")
                    if not hist.empty: rate_to_usd = hist['Close'].iloc[-1]
                else:
                    t = yf.Ticker(f"USD{from_curr}=X")
                    hist = t.history(period="1d")
                    if not hist.empty: rate_to_usd = 1.0 / hist['Close'].iloc[-1]

            rate_from_usd = 1.0
            if to_curr != "USD":
                if to_curr in ["EUR", "GBP", "AUD", "NZD"]:
                    t = yf.Ticker(f"{to_curr}USD=X")
                    hist = t.history(period="1d")
                    if not hist.empty: rate_from_usd = 1.0 / hist['Close'].iloc[-1]
                else:
                    t = yf.Ticker(f"USD{to_curr}=X")
                    hist = t.history(period="1d")
                    if not hist.empty: rate_from_usd = hist['Close'].iloc[-1]
            
            return rate_to_usd * rate_from_usd
        except Exception as e:
            st.warning(f"FX Error ({from_curr}->{to_curr}): {e}")
            return 1.0

# ==============================================================================
# 3. FINANCIAL ANALYSIS ENGINES
# ==============================================================================

class TechnicalIndicators:
    """Library of technical analysis indicators."""
    @staticmethod
    def add_all_indicators(df):
        if df.empty: return df
        df = df.copy()
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
        df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        std_20 = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (std_20 * 2)
        df['BB_Lower'] = df['SMA_20'] - (std_20 * 2)
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['ATR'] = true_range.rolling(14).mean()
        df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
        return df

class FundamentalScoring:
    @staticmethod
    def calculate_altman_z(bs, inc, mcap):
        try:
            total_assets = bs.get('Total Assets', 1)
            working_capital = bs.get('Current Assets', 0) - bs.get('Current Liabilities', 0)
            retained_earnings = bs.get('Retained Earnings', 0)
            ebit = inc.get('EBIT', 0)
            total_liab = bs.get('Total Liabilities Net Minority Interest', 1)
            sales = inc.get('Total Revenue', 0)
            A = working_capital / total_assets
            B = retained_earnings / total_assets
            C = ebit / total_assets
            D = mcap / total_liab
            E = sales / total_assets
            z_score = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
            return z_score
        except: return 0

    @staticmethod
    def calculate_piotroski_f(bs, inc, cf, bs_prev, inc_prev):
        try:
            score = 0
            net_income = inc.get('Net Income', 0)
            roa = Utils.safe_div(net_income, bs.get('Total Assets', 1))
            cfo = cf.get('Operating Cash Flow', 0)
            if net_income > 0: score += 1
            if cfo > 0: score += 1
            if roa > Utils.safe_div(inc_prev.get('Net Income', 0), bs_prev.get('Total Assets', 1)): score += 1
            if cfo > net_income: score += 1
            lt_debt = bs.get('Long Term Debt', 0)
            lt_debt_prev = bs_prev.get('Long Term Debt', 0)
            curr_ratio = Utils.safe_div(bs.get('Current Assets', 0), bs.get('Current Liabilities', 1))
            curr_ratio_prev = Utils.safe_div(bs_prev.get('Current Assets', 0), bs_prev.get('Current Liabilities', 1))
            shares = bs.get('Share Issued', 1)
            shares_prev = bs_prev.get('Share Issued', 1)
            if lt_debt < lt_debt_prev: score += 1
            if curr_ratio > curr_ratio_prev: score += 1
            if shares <= shares_prev: score += 1
            gross_margin = Utils.safe_div(inc.get('Gross Profit', 0), inc.get('Total Revenue', 1))
            gross_margin_prev = Utils.safe_div(inc_prev.get('Gross Profit', 0), inc_prev.get('Total Revenue', 1))
            asset_turnover = Utils.safe_div(inc.get('Total Revenue', 0), bs.get('Total Assets', 1))
            asset_turnover_prev = Utils.safe_div(inc_prev.get('Total Revenue', 0), bs_prev.get('Total Assets', 1))
            if gross_margin > gross_margin_prev: score += 1
            if asset_turnover > asset_turnover_prev: score += 1
            return score
        except: return 0

class ValuationModels:
    @staticmethod
    def dcf_2_stage(fcf, growth_rate_1, years_1, growth_rate_2, discount_rate, terminal_growth, net_debt, shares):
        try:
            future_cash_flows = []
            current_fcf = fcf
            for i in range(years_1):
                current_fcf *= (1 + growth_rate_1)
                future_cash_flows.append(current_fcf)
            terminal_value = (future_cash_flows[-1] * (1 + terminal_growth)) / (discount_rate - terminal_growth)
            discounted_cf = sum([cf / ((1 + discount_rate) ** (i + 1)) for i, cf in enumerate(future_cash_flows)])
            discounted_tv = terminal_value / ((1 + discount_rate) ** years_1)
            enterprise_value = discounted_cf + discounted_tv
            equity_value = enterprise_value - net_debt
            fair_value = equity_value / shares
            return {"fair_value": fair_value, "enterprise_value": enterprise_value, "projected_fcf": future_cash_flows, "terminal_value": terminal_value}
        except Exception as e: return {"fair_value": 0, "error": str(e)}

    @staticmethod
    def graham_number(eps, bvps):
        if eps < 0 or bvps < 0: return 0
        return np.sqrt(22.5 * eps * bvps)

    @staticmethod
    def peter_lynch_value(eps, growth_rate):
        if growth_rate > 25: growth_rate = 25 
        return eps * growth_rate

class DataEngine:
    def __init__(self, ticker):
        self.ticker = ticker.upper()
        self.stock = yf.Ticker(self.ticker)
        self.info = self.stock.info
        self.valid = 'currentPrice' in self.info
        if self.valid:
            self.inc = self.stock.income_stmt.T.sort_index(ascending=True)
            self.bs = self.stock.balance_sheet.T.sort_index(ascending=True)
            self.cf = self.stock.cash_flow.T.sort_index(ascending=True)
            self.q_inc = self.stock.quarterly_income_stmt.T.sort_index(ascending=True)
            self.q_bs = self.stock.quarterly_balance_sheet.T.sort_index(ascending=True)
            self.q_cf = self.stock.quarterly_cash_flow.T.sort_index(ascending=True)
            self.price = self.info.get('currentPrice', 0)
            self.mcap = self.info.get('marketCap', 0)
            self.beta = self.info.get('beta', 1)
            self.shares = self.info.get('sharesOutstanding', 1)

    def get_history(self, period="1y", interval="1d"):
        df = self.stock.history(period=period, interval=interval)
        return TechnicalIndicators.add_all_indicators(df)

    def get_peers(self):
        sector = self.info.get('sector', 'Technology')
        peers_map = {
            "Technology": ["MSFT", "AAPL", "NVDA", "ORCL", "ADBE"],
            "Financial Services": ["JPM", "BAC", "V", "MA"],
            "Healthcare": ["JNJ", "LLY", "PFE", "UNH"],
            "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD"],
            "Consumer Defensive": ["PG", "KO", "PEP", "COST"],
            "Energy": ["XOM", "CVX", "SHELL"],
            "Communication Services": ["GOOGL", "META", "NFLX", "DIS"]
        }
        return peers_map.get(sector, ["SPY", "QQQ"])

    def risk_analysis(self):
        hist = self.stock.history(period="2y")['Close']
        if hist.empty: return {}
        ret = hist.pct_change().dropna()
        vol = ret.std() * np.sqrt(252)
        mean_ret = ret.mean()
        var_95 = norm.ppf(0.05, mean_ret, ret.std())
        cum = (1+ret).cumprod()
        peak = cum.expanding(min_periods=1).max()
        dd = (cum/peak) - 1
        max_dd = dd.min()
        return {"vol": vol, "var_95": var_95, "max_dd": max_dd}

# ==============================================================================
# 4. COMPONENT RENDERING FUNCTIONS
# ==============================================================================

def render_kpi(label, value, delta=None, prefix="", suffix="", tooltip=""):
    delta_html = ""
    if delta is not None:
        cls = "positive" if delta >= 0 else "negative"
        icon = "▲" if delta >= 0 else "▼"
        delta_html = f'<div class="kpi-delta {cls}">{icon} {abs(delta):.2f}%</div>'
        
    st.markdown(f"""
    <div class="kpi-card" title="{tooltip}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{prefix}{value}{suffix}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)

def render_interpretation(content, sentiment="neutral"):
    colors = {
        "neutral": st.session_state.get('theme_accent', "#3498db"), 
        "bullish": "#27ae60",
        "bearish": "#c0392b"
    }
    color = colors.get(sentiment, "#3498db")
    
    # Use cleaner HTML without nested complex divs that might break text selection or rendering
    html_str = f"""
    <div style="background-color: {color}15; border-left: 4px solid {color}; padding: 15px; border-radius: 5px; margin: 10px 0;">
        <strong style="color: {color}; display: block; margin-bottom: 5px;">💡 Analyst Interpretation:</strong>
        <span style="color: var(--text-color); font-size: 14px; line-height: 1.5;">{content}</span>
    </div>
    """
    st.markdown(html_str, unsafe_allow_html=True)

# ==============================================================================
# 5. MAIN APPLICATION LOGIC
# ==============================================================================

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/bullish.png", width=60)
    st.title("INVESTMENT TERMINAL")
    st.caption("Pro Edition | Analysis Suite")
    st.markdown("---")
    
    # THEME SELECTION
    st.subheader("Appearance")
    selected_theme = st.selectbox("Select Theme", ["Light", "Dark", "Sepia"], index=0)
    if st.session_state.theme != selected_theme:
        st.session_state.theme = selected_theme
        st.rerun()

    st.markdown("---")

    # MARKET SELECTION
    st.subheader("Asset Selection")
    
    market_map = {
        "🇺🇸 USA": "",
        "🇩🇪 Germany": ".DE",
        "🇻🇳 Vietnam": ".VN",
        "🇬🇧 UK": ".L",
        "🇯🇵 Japan": ".T",
        "🇨🇳 China (Shanghai)": ".SS",
        "🌐 Other (Manual Input)": "MANUAL"
    }
    
    selected_market_label = st.selectbox("Select Market", list(market_map.keys()), index=0)
    market_suffix = market_map[selected_market_label]
    
    # Smart Input Logic
    symbol_input = st.text_input("Ticker Symbol", value="AAPL", help="Enter symbol (e.g., AAPL). If you enter a ticker with a suffix (e.g., 7203.T), it will override the market selection.").upper().strip()

    if market_suffix == "MANUAL":
        ticker_input = symbol_input
    else:
        # Check if user explicitly provided a suffix (indicated by a dot, e.g., '7203.T')
        # Yahoo Finance uses '-' for share classes (BRK-B) and '.' for exchange suffixes (BMW.DE)
        if "." in symbol_input:
            ticker_input = symbol_input
            # If the user typed 'ADS.DE' while Market is Germany (.DE), this works (ADS.DE).
            # If the user typed '7203.T' while Market is Germany (.DE), this works (7203.T overrides .DE).
        else:
            # No suffix provided, apply the selected market's suffix
            ticker_input = f"{symbol_input}{market_suffix}"
    
    # TIME HORIZON
    st.subheader("Time Control")
    time_map = {
        "5 Days": "5d", "1 Month": "1mo", "3 Months": "3mo", 
        "6 Months": "6mo", "YTD": "ytd", "1 Year": "1y", 
        "3 Years": "3y", "5 Years": "5y", "10 Years": "10y", "Max": "max"
    }
    sel_time_label = st.selectbox("Chart Period", list(time_map.keys()), index=5)
    sel_period = time_map[sel_time_label]
    
    interval_lookup = {"5d": "15m", "1mo": "60m", "3mo": "1d", "6mo": "1d", "ytd": "1d", "1y": "1d", "3y": "1wk", "5y": "1wk", "10y": "1mo", "max": "1mo"}
    sel_interval = interval_lookup.get(sel_period, "1d")

    # CURRENCY CONTROL
    st.subheader("Currency Settings")
    currency_mode = st.radio("Display Currency", ["Auto (Default)", "USD ($)", "EUR (€)", "VND (₫)"], index=0)

    if st.button("🚀 Run Full Analysis", type="primary", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()
        
    st.markdown("---")
    
    module = st.radio("Select Module", [
        "1. Executive Dashboard",
        "2. Technical Analysis Lab",
        "3. Financial Statement Deep Dive",
        "4. Cash Flow Intelligence",
        "5. Intrinsic Valuation (DCF)",
        "6. Peer Valuation & Comparables",
        "7. Risk Management",
        "8. Price & Capital Dynamics",
        "9. Market Leaders Ranking"
    ])
    
    st.markdown("---")
    st.markdown("""
    <div style='font-size: 11px; color: #888;'>
    <b>Developed by Minh Phu Dinh</b><br>
    Data: Yahoo Finance<br>
    </div>
    """, unsafe_allow_html=True)

# --- INITIALIZATION ---
try:
    engine = DataEngine(ticker_input)
    if not engine.valid:
        st.error(f"Ticker '{ticker_input}' not found or delisted.")
        st.stop()
    info = engine.info
except Exception as e:
    st.error(f"Engine Initialization Error: {e}")
    st.stop()

# --- CURRENCY LOGIC ---
native_currency = info.get('currency', 'USD')
if "Auto" in currency_mode: target_currency = native_currency
elif "USD" in currency_mode: target_currency = "USD"
elif "EUR" in currency_mode: target_currency = "EUR"
elif "VND" in currency_mode: target_currency = "VND"
else: target_currency = "USD"

currency_symbols = {"USD": "$", "EUR": "€", "VND": "₫"}
target_symbol = currency_symbols.get(target_currency, target_currency)
fx_rate = CurrencyFX.get_fx_rate(native_currency, target_currency)

# --- HEADER SECTION ---
c1, c2, c3 = st.columns([1, 4, 2])
with c1:
    logo = info.get('logo_url', '')
    if logo: st.image(logo, width=80)
    else: st.markdown("## 🏦")

with c2:
    st.title(info.get('longName', ticker_input))
    st.markdown(f"**{info.get('sector', 'N/A')}** | {info.get('industry', 'N/A')} | {info.get('exchange', 'N/A')}")
    st.caption(f"Native: {native_currency} | Display: {target_currency} (Rate: {fx_rate:.2f})")

with c3:
    price = info.get('currentPrice', 0)
    prev = info.get('previousClose', price)
    chg = price - prev
    pct = (chg / prev) * 100 if prev else 0
    disp_price = price * fx_rate
    disp_chg = chg * fx_rate
    color = "#27ae60" if chg >= 0 else "#c0392b"
    st.markdown(f"""
    <div style='text-align: right; background: var(--card-bg); padding: 10px; border-radius: 8px; border: 1px solid var(--border-color);'>
        <div style='font-size: 32px; font-weight: 800; color: {color};'>{target_symbol}{disp_price:,.2f}</div>
        <div style='font-size: 16px; font-weight: 600; color: {color};'>{disp_chg:+.2f} ({pct:+.2f}%)</div>
    </div>
    """, unsafe_allow_html=True)
st.markdown("---")

# ==============================================================================
# MODULE 1-4 (Standard Modules)
# ==============================================================================
if module == "1. Executive Dashboard":
    st.subheader("📊 Executive Summary")

    # --- COMPANY PROFILE SNAPSHOT (Moved to Top) ---
    with st.container():
        # Safety check for Employees formatting
        emp_raw = info.get('fullTimeEmployees')
        emp_str = f"{emp_raw:,}" if isinstance(emp_raw, (int, float)) else "N/A"
        
        st.markdown(f"""
        <div style="padding: 15px; border: 1px solid var(--border-color); border-radius: 8px; background-color: var(--card-bg); margin-bottom: 20px;">
            <h4 style="margin-top: 0; color: var(--accent-color);">🏢 Company Profile: {info.get('longName')}</h4>
            <p style="font-size: 14px; line-height: 1.6;">{info.get('longBusinessSummary', 'No description available.')}</p>
            <hr style="border-top: 1px solid var(--border-color);">
            <div style="display: flex; justify-content: space-between; font-size: 13px; color: var(--secondary-text);">
                <span><b>Sector:</b> {info.get('sector', 'N/A')}</span>
                <span><b>Industry:</b> {info.get('industry', 'N/A')}</span>
                <span><b>Employees:</b> {emp_str}</span>
                <span><b>IPO:</b> {info.get('firstTradeDateEpochUtc', 'N/A')}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- ROW 1: CORE VALUATION ---
    st.markdown("##### 1. Valuation & Size")
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1: render_kpi("Market Cap", Utils.format_currency(info.get('marketCap'), target_symbol), None, "")
    with k2: render_kpi("P/E Ratio", f"{info.get('trailingPE', 0):.2f}", None, "")
    with k3: render_kpi("Forward P/E", f"{info.get('forwardPE', 0):.2f}", None, "")
    with k4: render_kpi("PEG Ratio", f"{info.get('pegRatio', 0):.2f}", None, "")
    with k5: render_kpi("Price/Book", f"{info.get('priceToBook', 0):.2f}", None, "")
    
    # Interpretation for Valuation
    peg = info.get('pegRatio', 0)
    pe = info.get('trailingPE', 0)
    val_sent = "bullish" if (peg > 0 and peg < 1.0) else "bearish" if peg > 2.0 else "neutral"
    render_interpretation(f"The stock trades at a **P/E of {pe:.2f}x**. The **PEG Ratio is {peg:.2f}**, where < 1.0 generally implies undervaluation relative to growth.", val_sent)

    # --- ROW 2: PROFITABILITY & EFFICIENCY ---
    st.markdown("##### 2. Profitability & Efficiency")
    p1, p2, p3, p4, p5 = st.columns(5)
    with p1: render_kpi("ROE", f"{info.get('returnOnEquity', 0)*100:.2f}%", None, "")
    with p2: render_kpi("ROA", f"{info.get('returnOnAssets', 0)*100:.2f}%", None, "")
    with p3: render_kpi("Gross Margin", f"{info.get('grossMargins', 0)*100:.2f}%", None, "")
    with p4: render_kpi("Operating Margin", f"{info.get('operatingMargins', 0)*100:.2f}%", None, "")
    with p5: render_kpi("Profit Margin", f"{info.get('profitMargins', 0)*100:.2f}%", None, "")

    # Interpretation for Profitability
    roe = info.get('returnOnEquity', 0)
    prof_sent = "bullish" if roe > 0.15 else "neutral"
    render_interpretation(f"**ROE of {roe*100:.1f}%** measures how efficiently management uses equity. >15% is considered strong.", prof_sent)

    # --- ROW 3: FINANCIAL HEALTH & DIVIDENDS ---
    st.markdown("##### 3. Balance Sheet & Income")
    h1, h2, h3, h4, h5 = st.columns(5)
    with h1: render_kpi("Current Ratio", f"{info.get('currentRatio', 0):.2f}", None, "")
    with h2: render_kpi("Debt/Equity", f"{info.get('debtToEquity', 0)/100:.2f}", None, "")
    with h3: render_kpi("Free Cash Flow", Utils.format_currency(info.get('freeCashflow'), target_symbol), None, "")
    with h4: render_kpi("Dividend Yield", f"{info.get('dividendYield', 0)*100:.2f}%", None, "")
    with h5: render_kpi("Payout Ratio", f"{info.get('payoutRatio', 0)*100:.2f}%", None, "")

    # Interpretation for Health
    cr = info.get('currentRatio', 0)
    de = info.get('debtToEquity', 0)
    health_sent = "bullish" if cr > 1.5 and de < 100 else "warning" if cr < 1.0 else "neutral"
    render_interpretation(f"**Current Ratio of {cr:.2f}** indicates liquidity (ability to pay short-term debts). >1.5 is safe. Debt/Equity is {de/100:.2f}.", health_sent)

    # --- VISUALS ---
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("📈 Revenue vs Earnings Trend")
        # Get annual data
        fin_df = engine.inc 
        if not fin_df.empty:
            # Create combo chart
            fig_fin = make_subplots(specs=[[{"secondary_y": True}]])
            # Use string year for X-axis to avoid "2021.5" issue
            x_vals = fin_df.index.year.astype(str)
            
            fig_fin.add_trace(go.Bar(x=x_vals, y=fin_df['Total Revenue'], name="Revenue", marker_color=st.session_state.get('theme_accent', '#3498db')), secondary_y=False)
            fig_fin.add_trace(go.Scatter(x=x_vals, y=fin_df['Net Income'], name="Net Income", line=dict(color='#27ae60', width=3)), secondary_y=True)
            
            # Explicitly force categorical x-axis
            fig_fin.update_xaxes(type='category')
            fig_fin.update_layout(height=350, template=plotly_template, title="Top Line vs Bottom Line")
            st.plotly_chart(fig_fin, use_container_width=True)
            
            # Trend Interpretation
            rev_cagr = Utils.get_cagr(fin_df['Total Revenue'].iloc[0], fin_df['Total Revenue'].iloc[-1], len(fin_df)-1)
            render_interpretation(f"Revenue has grown at a CAGR of **{rev_cagr*100:.1f}%** over the displayed period. Divergence between Revenue (Bars) and Income (Line) indicates changing margins.", "neutral")

    with c2:
        st.subheader("🥧 DuPont Analysis (ROE Breakdown)")
        # Calculate DuPont Components
        net_margin = info.get('profitMargins', 0)
        asset_turnover = Utils.safe_div(info.get('totalRevenue', 0), engine.bs.get('Total Assets', pd.Series([1])).iloc[-1]) if not engine.bs.empty else 0
        leverage = Utils.safe_div(engine.bs.get('Total Assets', pd.Series([1])).iloc[-1], engine.bs.get('Stockholders Equity', pd.Series([1])).iloc[-1]) if not engine.bs.empty else 1
        
        st.metric("1. Net Margin (Efficiency)", f"{net_margin*100:.2f}%")
        st.metric("2. Asset Turnover (Speed)", f"{asset_turnover:.2f}x")
        st.metric("3. Fin. Leverage (Multiplier)", f"{leverage:.2f}x")
        st.divider()
        st.metric("= ROE (Return)", f"{info.get('returnOnEquity', 0)*100:.2f}%")

    st.subheader("🏥 Fundamental Health Cards")
    try:
        z_score = FundamentalScoring.calculate_altman_z(engine.bs.iloc[-1], engine.inc.iloc[-1], info.get('marketCap', 0)) if not engine.bs.empty else 0
        f_score = FundamentalScoring.calculate_piotroski_f(engine.bs.iloc[-1], engine.inc.iloc[-1], engine.cf.iloc[-1], engine.bs.iloc[-2], engine.inc.iloc[-2]) if not engine.bs.empty else 0
    except: z_score, f_score = 0, 0
    
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        color = "var(--success-color)" if z_score > 3 else "var(--warning-color)" if z_score > 1.8 else "var(--danger-color)"
        st.markdown(f'<div class="analysis-box box-info" style="border-left-color: {color};"><h3>Altman Z-Score: {z_score:.2f}</h3><p>Predicts bankruptcy risk. >3.0 is Safe.</p></div>', unsafe_allow_html=True)
    with sc2:
        color = "var(--success-color)" if f_score >= 7 else "var(--warning-color)" if f_score >= 4 else "var(--danger-color)"
        st.markdown(f'<div class="analysis-box box-info" style="border-left-color: {color};"><h3>Piotroski F-Score: {f_score}/9</h3><p>Measures financial strength trends.</p></div>', unsafe_allow_html=True)
    with sc3:
        rec = info.get('recommendationKey', 'none').upper().replace('_', ' ')
        color = "var(--success-color)" if 'BUY' in rec else "var(--warning-color)" if 'HOLD' in rec else "var(--danger-color)"
        target_p = info.get('targetMeanPrice', 0) * fx_rate
        st.markdown(f'<div class="analysis-box box-info" style="border-left-color: {color};"><h3>Analyst Consensus</h3><p style="font-size: 20px; font-weight: bold;">{rec}</p><p>Target: {target_symbol}{target_p:,.2f}</p></div>', unsafe_allow_html=True)

elif module == "2. Technical Analysis Lab":
    st.subheader("📈 Advanced Charting & Indicators")
    df_chart = engine.get_history(period=sel_period, interval=sel_interval)
    if df_chart.empty: st.warning("No chart data available."); st.stop()
    for col in ['Open', 'High', 'Low', 'Close', 'SMA_20', 'SMA_50', 'SMA_200', 'EMA_12', 'EMA_26', 'BB_Upper', 'BB_Lower', 'ATR']:
        if col in df_chart.columns: df_chart[col] = df_chart[col] * fx_rate
    
    ind_opts = st.multiselect("Overlay Indicators", ["SMA 50", "SMA 200", "Bollinger Bands"], default=["SMA 50", "Bollinger Bands"])
    osc_opts = st.multiselect("Oscillators", ["Volume", "RSI", "MACD"], default=["Volume", "RSI"])
    
    fig = make_subplots(rows=1+len(osc_opts), cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6] + [0.4/len(osc_opts)]*len(osc_opts) if osc_opts else [1.0])
    fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name="Price"), row=1, col=1)
    
    if "SMA 50" in ind_opts: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], line=dict(color='orange', width=1.5), name="SMA 50"), row=1, col=1)
    if "Bollinger Bands" in ind_opts: 
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['BB_Upper'], line=dict(color='gray', width=1, dash='dot'), name="BB Upp"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['BB_Lower'], line=dict(color='gray', width=1, dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.1)', name="BB Low"), row=1, col=1)
    
    curr_row = 2
    for osc in osc_opts:
        if osc == "Volume": fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], name="Volume"), row=curr_row, col=1)
        elif osc == "RSI": 
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['RSI'], line=dict(color='purple'), name="RSI"), row=curr_row, col=1)
            fig.add_hline(y=70, line_dash="dot", row=curr_row, col=1, line_color="red")
            fig.add_hline(y=30, line_dash="dot", row=curr_row, col=1, line_color="green")
        curr_row += 1
    
    fig.update_layout(height=800, xaxis_rangeslider_visible=False, template=plotly_template, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
    
    # Technical Interpretation
    last_price = df_chart['Close'].iloc[-1]
    sma_50 = df_chart['SMA_50'].iloc[-1] if 'SMA_50' in df_chart.columns else last_price
    rsi = df_chart['RSI'].iloc[-1] if 'RSI' in df_chart.columns else 50
    bb_upper = df_chart['BB_Upper'].iloc[-1] if 'BB_Upper' in df_chart.columns else last_price*1.1
    bb_lower = df_chart['BB_Lower'].iloc[-1] if 'BB_Lower' in df_chart.columns else last_price*0.9
    
    tech_signal = "Bullish" if last_price > sma_50 else "Bearish"
    rsi_state = "Overbought (>70)" if rsi > 70 else "Oversold (<30)" if rsi < 30 else "Neutral"
    bb_state = "near Upper Band (Resistance)" if last_price > bb_upper * 0.98 else "near Lower Band (Support)" if last_price < bb_lower * 1.02 else "within bands"
    
    t_sent = "bullish" if tech_signal == "Bullish" and rsi < 70 else "bearish"
    
    render_interpretation(f"""
    **Technician's Note:**
    Current Price is **{tech_signal}** relative to the 50-period SMA. 
    Momentum (RSI) is **{rsi_state}** at {rsi:.1f}.
    Volatility-wise, price is trading **{bb_state}**. 
    {'Breakout potential if volume confirms.' if last_price > bb_upper else 'Watch for mean reversion.'}
    """, t_sent)

elif module == "3. Financial Statement Deep Dive":
    st.subheader("📑 Financial Statements Analysis")
    inc = engine.inc * fx_rate
    bs = engine.bs * fx_rate
    cf = engine.cf * fx_rate
    
    t1, t2, t3 = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow"])
    
    # --- HELPER TO RENAME COLUMNS ---
    def format_cols(df, type="FY"):
        new_cols = []
        for c in df.columns:
            if isinstance(c, pd.Timestamp):
                if type == "FY": new_cols.append(c.strftime("FY%Y"))
                elif type == "Ending": new_cols.append(c.strftime("Ending %Y-%m-%d"))
            else:
                new_cols.append(str(c)[:10])
        df.columns = new_cols
        return df

    def render_financial_section(df, items, title, indent=False):
        subset = Utils.get_financial_section(df, items, indent)
        if not subset.empty:
            # Sort columns descending (Latest year first)
            subset = subset[sorted(subset.columns, reverse=True)]
            
            # --- Variance Logic ---
            if len(subset.columns) >= 2:
                latest = subset.iloc[:, 0]
                prev = subset.iloc[:, 1]
                diff = latest - prev
                pct = ((latest - prev) / prev.abs()) * 100
                
                # Append to end
                subset["Abs Chg (YoY)"] = diff
                subset["% Chg (YoY)"] = pct
            # ----------------------

            subset = format_cols(subset, "FY") 
            st.markdown(f"**{title}**")
            st.caption("Comparing the two most recent fiscal periods.")
            
            # Dynamic Formatting
            format_dict = {}
            for c in subset.columns:
                if "%" in str(c): format_dict[c] = "{:+.2f}%"
                elif "Abs" in str(c): format_dict[c] = "{:+.0f}"
                else: format_dict[c] = "{:,.0f}"
                
            st.dataframe(subset.style.format(format_dict), use_container_width=True)

    with t1: 
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown("##### 📜 Income Statement (Grouped)")
            
            # Pass Transposed DF (Metrics as Index)
            # Group 1: Revenue & Gross Profit
            render_financial_section(inc.T, ['Total Revenue', 'Cost Of Revenue', 'Gross Profit'], "Top Line & Gross Profit")
            
            # Group 2: Operating Expenses
            render_financial_section(inc.T, ['Operating Expense', 'Selling General And Administration', 'Research And Development', 'Operating Income'], "Operating Expenses & Income", indent=True)
            
            # Group 3: Bottom Line
            render_financial_section(inc.T, ['Net Non Operating Interest Income Expense', 'Other Income Expense', 'Pretax Income', 'Tax Provision', 'Net Income', 'Basic EPS', 'Diluted EPS'], "Bottom Line & Margins", indent=True)
        
        # --- BRIDGE CHART (Waterfall) ---
        with c2:
            st.markdown("##### 🌉 Profitability Bridge")
            # Year Selector
            available_years = sorted(inc.index.year.tolist(), reverse=True)
            sel_year_int = st.selectbox("Select Fiscal Year", available_years)
            
            # Get data for selected year
            mask = inc.index.year == sel_year_int
            if mask.any():
                latest = inc[mask].iloc[0]
                rev = latest.get('Total Revenue', 0)
                gross = latest.get('Gross Profit', 0)
                opex = latest.get('Total Operating Expenses', 0)
                op_inc = latest.get('Operating Income', 0)
                net = latest.get('Net Income', 0)
                
                # Approximate components
                cost_rev = -(rev - gross)
                other = (op_inc - net) * -1 
                
                fig_bridge = go.Figure(go.Waterfall(
                    orientation="v",
                    measure=["relative", "relative", "total", "relative", "total", "relative", "total"],
                    x=["Revenue", "COGS", "Gross Profit", "OpEx", "Operating Inc", "Tax/Other", "Net Income"],
                    y=[rev, cost_rev, 0, -opex, 0, -other, 0], 
                    connector={"line": {"color": "rgb(63, 63, 63)"}},
                    decreasing={"marker": {"color": "#e74c3c"}},
                    increasing={"marker": {"color": "#27ae60"}},
                    totals={"marker": {"color": "#3498db"}}
                ))
                fig_bridge.update_layout(title=f"P&L Cascade ({sel_year_int})", height=500, template=plotly_template)
                st.plotly_chart(fig_bridge, use_container_width=True)
            else:
                st.warning("Data not available for selected year.")

    with t2: 
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown("##### ⚖️ Balance Sheet (Grouped)")
            
            # 1. Assets
            st.markdown("###### 1. Assets")
            render_financial_section(bs.T, ['Cash And Cash Equivalents', 'Inventory', 'Accounts Receivable', 'Current Assets'], "Current Assets", indent=True)
            render_financial_section(bs.T, ['Net PPE', 'Goodwill', 'Total Non Current Assets', 'Total Assets'], "Non-Current Assets", indent=True)
            
            # 2. Liabilities
            st.markdown("###### 2. Liabilities")
            render_financial_section(bs.T, ['Accounts Payable', 'Current Debt', 'Current Liabilities'], "Current Liabilities", indent=True)
            render_financial_section(bs.T, ['Long Term Debt', 'Total Non Current Liabilities', 'Total Liabilities Net Minority Interest'], "Non-Current Liabilities", indent=True)
            
            # 3. Equity
            st.markdown("###### 3. Equity")
            render_financial_section(bs.T, ['Common Stock', 'Retained Earnings', 'Stockholders Equity'], "Shareholders' Equity", indent=True)
            
        with c2:
            st.markdown("##### 📊 Balance Sheet Composition")
            if not bs.empty:
                latest_bs = bs.iloc[-1]
                
                # Asset Composition
                curr_assets = latest_bs.get('Current Assets', 0)
                total_assets = latest_bs.get('Total Assets', 1)
                non_curr_assets = total_assets - curr_assets
                
                fig_assets = px.pie(names=['Current (Liquid)', 'Non-Current (Fixed)'], values=[curr_assets, non_curr_assets], title="Asset Mix")
                fig_assets.update_layout(height=300, template=plotly_template)
                st.plotly_chart(fig_assets, use_container_width=True)
                
                # Capital Structure
                liab = latest_bs.get('Total Liabilities Net Minority Interest', 0)
                equity = latest_bs.get('Stockholders Equity', 0)
                
                fig_cap = px.bar(x=['Liabilities', 'Equity'], y=[liab, equity], color=['Liabilities', 'Equity'], title="Capital Structure")
                fig_cap.update_layout(height=300, showlegend=False, template=plotly_template)
                st.plotly_chart(fig_cap, use_container_width=True)

    with t3: 
        st.markdown("##### 💸 Cash Flow Statement (Grouped)")
        
        # Operating
        render_financial_section(cf.T, ['Net Income', 'Depreciation And Amortization', 'Change In Working Capital', 'Operating Cash Flow'], "Operating Activities")
        
        # Investing
        render_financial_section(cf.T, ['Capital Expenditure', 'Investing Cash Flow'], "Investing Activities")
        
        # Financing
        render_financial_section(cf.T, ['Net Issuance Payments Of Debt', 'Cash Dividends Paid', 'Financing Cash Flow'], "Financing Activities")
        
        # Summary
        render_financial_section(cf.T, ['Free Cash Flow'], "Summary Metrics")

# ==============================================================================
# MODULE 4: CASH FLOW INTELLIGENCE (DETAILED)
# ==============================================================================
elif module == "4. Cash Flow Intelligence":
    st.subheader("💸 Cash Flow Deep Dive")
    cf = engine.cf * fx_rate
    inc = engine.inc * fx_rate
    
    if cf.empty:
        st.error("No Cash Flow Data")
        st.stop()
    
    # 1. Full Detail Statement
    st.markdown("### 📋 Detailed Cash Flow Statement (Grouped)")
    
    # Reuse helper
    def format_cols(df, type="FY"):
        new_cols = []
        for c in df.columns:
            if isinstance(c, pd.Timestamp):
                if type == "FY": new_cols.append(c.strftime("FY%Y"))
                elif type == "Ending": new_cols.append(c.strftime("Ending %Y-%m-%d"))
            else:
                new_cols.append(str(c)[:10])
        df.columns = new_cols
        return df

    def render_financial_section(df, items, title):
        subset = Utils.get_financial_section(df, items)
        if not subset.empty:
            subset = subset[sorted(subset.columns, reverse=True)]
            
            # --- Variance Logic ---
            if len(subset.columns) >= 2:
                latest = subset.iloc[:, 0]
                prev = subset.iloc[:, 1]
                diff = latest - prev
                pct = ((latest - prev) / prev.abs()) * 100
                
                # Append to end
                subset["Abs Chg (YoY)"] = diff
                subset["% Chg (YoY)"] = pct
            # ----------------------

            subset = format_cols(subset, "FY")
            st.markdown(f"**{title}**")
            
            # Dynamic Formatting
            format_dict = {}
            for c in subset.columns:
                if "%" in str(c): format_dict[c] = "{:+.2f}%"
                elif "Abs" in str(c): format_dict[c] = "{:+.0f}"
                else: format_dict[c] = "{:,.0f}"
            
            # Removed background_gradient
            st.dataframe(subset.style.format(format_dict), use_container_width=True)

    # Operating
    render_financial_section(cf.T, ['Net Income', 'Depreciation And Amortization', 'Change In Working Capital', 'Operating Cash Flow'], "1. Operating Activities")
    
    # Investing
    render_financial_section(cf.T, ['Capital Expenditure', 'Investing Cash Flow'], "2. Investing Activities")
    
    # Financing
    render_financial_section(cf.T, ['Net Issuance Payments Of Debt', 'Cash Dividends Paid', 'Financing Cash Flow'], "3. Financing Activities")
    
    # Summary Commentary
    fcf = cf.loc[:, 'Free Cash Flow'] if 'Free Cash Flow' in cf.columns else (cf.get('Operating Cash Flow', 0) + cf.get('Capital Expenditure', 0))
    if not fcf.empty:
        fcf_trend = "growing" if fcf.iloc[-1] > fcf.iloc[0] else "declining"
        render_interpretation(f"**Cash Flow Summary:** The company's Free Cash Flow has been **{fcf_trend}** over the period. "
                              "Positive FCF indicates the ability to pay dividends, buy back stock, or pay down debt without external financing.", "neutral")

    # 2. Operating Activities Analysis
    st.markdown("---")
    st.subheader("1️⃣ Operating Activities Analysis")
    c1, c2 = st.columns([2, 1])
    
    with c1:
        # Metrics
        ocf = cf.loc[:, 'Operating Cash Flow'] if 'Operating Cash Flow' in cf.columns else cf.iloc[0] # Fallback
        ni = inc.loc[:, 'Net Income'] if 'Net Income' in inc.columns else pd.Series(0, index=cf.index)
        
        fig_ocf = go.Figure()
        # Force categorical x-axis by converting years to strings
        x_vals = cf.index.year.astype(str)
        fig_ocf.add_trace(go.Bar(x=x_vals, y=ocf, name="Operating Cash Flow", marker_color='#27ae60'))
        fig_ocf.add_trace(go.Scatter(x=x_vals, y=ni, name="Net Income", line=dict(color='#2c3e50', width=3, dash='dot')))
        fig_ocf.update_xaxes(type='category')
        fig_ocf.update_layout(title="Quality of Income: OCF vs Net Income", height=350, template=plotly_template)
        st.plotly_chart(fig_ocf, use_container_width=True)
        
    with c2:
        # Interpretation
        ratio = (ocf.iloc[-1] / ni.iloc[-1]) if ni.iloc[-1] != 0 else 0
        sentiment = "bullish" if ratio > 1.0 else "bearish"
        render_interpretation(f"""
        **Cash Flow Conversion Ratio:** {ratio:.2f}x
        <br>
        - **> 1.0:** Company generates more cash than accounting profit. Indicates high quality earnings (e.g., high depreciation, deferred taxes).
        - **< 1.0:** Earnings are not fully backed by cash. Could be aggressive revenue recognition or ballooning working capital.
        """, sentiment)

    # 3. Investing Activities Analysis
    st.markdown("---")
    st.subheader("2️⃣ Investing Activities (Reinvestment)")
    c1, c2 = st.columns([2, 1])
    
    with c1:
        capex = cf.loc[:, 'Capital Expenditure'] if 'Capital Expenditure' in cf.columns else pd.Series(0, index=cf.index)
        # Usually CapEx is negative, make absolute for comparison
        capex_abs = capex.abs()
        
        fig_inv = go.Figure()
        x_vals = cf.index.year.astype(str)
        fig_inv.add_trace(go.Bar(x=x_vals, y=capex_abs, name="CapEx (Absolute)", marker_color='#e74c3c'))
        fig_inv.add_trace(go.Scatter(x=x_vals, y=ocf, name="Operating CF", line=dict(color='#27ae60', width=2)))
        fig_inv.update_xaxes(type='category')
        fig_inv.update_layout(title="Reinvestment: CapEx vs OCF", height=350, template=plotly_template)
        st.plotly_chart(fig_inv, use_container_width=True)
        
    with c2:
        # Interpretation
        reinvest_rate = (capex_abs.iloc[-1] / ocf.iloc[-1]) * 100 if ocf.iloc[-1] != 0 else 0
        sent_inv = "neutral"
        if reinvest_rate < 20: sent_inv = "bullish" # Asset light
        elif reinvest_rate > 80: sent_inv = "bearish" # Capital intensive
        
        render_interpretation(f"""
        **Capital Intensity Ratio:** {reinvest_rate:.1f}%
        <br>
        - **Low (< 20%):** Asset-light business model (Software, Services). High potential for dividends/buybacks.
        - **High (> 80%):** Heavy machinery, infrastructure, or aggressive expansion phase. Consumes most cash generated.
        """, sent_inv)

    # 4. Free Cash Flow Profiler
    st.markdown("---")
    st.subheader("3️⃣ Free Cash Flow (FCF) Master View")
    
    fcf = cf.loc[:, 'Free Cash Flow'] if 'Free Cash Flow' in cf.columns else (ocf + capex)
    
    # Waterfall for Latest Year
    l_ni = ni.iloc[-1]
    l_fcf = fcf.iloc[-1]
    diff = l_fcf - l_ni
    
    fig_wf = go.Figure(go.Waterfall(
        measure=["relative", "relative", "relative", "total"],
        x=["Net Income", "Non-Cash/WC/CapEx Adjustments", "Free Cash Flow"],
        y=[l_ni, diff, l_fcf],
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        totals={"marker": {"color": "#3498db"}}
    ))
    fig_wf.update_layout(title="Bridge: Net Income to FCF", height=400, template=plotly_template)
    st.plotly_chart(fig_wf, use_container_width=True)

    # 5. Enterprise Value Calculation (New Section)
    st.markdown("---")
    st.subheader("5️⃣ Enterprise Value (EV) Calculation")
    
    ev_mcap = info.get('marketCap', 0) * fx_rate
    ev_debt = info.get('totalDebt', 0) * fx_rate
    ev_cash = info.get('totalCash', 0) * fx_rate
    ev_val = ev_mcap + ev_debt - ev_cash
    
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.markdown(f"""
        **Formula:**
        $$EV = \\text{{Market Cap}} + \\text{{Total Debt}} - \\text{{Cash \\& Equivalents}}$$
        
        The theoretical price to acquire the company free and clear of debt and cash.
        
        | Component | Value ({target_symbol}) |
        | :--- | ---: |
        | **Market Cap** | `{Utils.format_number(ev_mcap)}` |
        | (+) Total Debt | `{Utils.format_number(ev_debt)}` |
        | (-) Cash & Eq. | `({Utils.format_number(ev_cash)})` |
        | **= Enterprise Value** | **`{Utils.format_number(ev_val)}`** |
        """)
        
    with c2:
        fig_ev_calc = go.Figure(go.Waterfall(
            orientation="v",
            measure=["relative", "relative", "relative", "total"],
            x=["Market Cap", "Debt", "Cash", "Enterprise Value"],
            y=[ev_mcap, ev_debt, -ev_cash, 0],
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            totals={"marker": {"color": "#8e44ad"}},
            decreasing={"marker": {"color": "#27ae60"}}, # Subtracting cash (green/positive factor for buyer)
            increasing={"marker": {"color": "#3498db"}}  # Adding debt/cost
        ))
        fig_ev_calc.update_layout(title="EV Composition", height=350, template=plotly_template)
        st.plotly_chart(fig_ev_calc, use_container_width=True)

    render_interpretation(f"**Enterprise Value:** The company has an EV of **{Utils.format_currency(ev_val, target_symbol)}**. "
                          f"Net Debt (Debt - Cash) is **{Utils.format_currency(ev_debt - ev_cash, target_symbol)}**.", "neutral")

# ==============================================================================
# MODULE 5: VALUATION & MODELING (ENHANCED)
# ==============================================================================
elif module == "5. Intrinsic Valuation (DCF)":
    st.subheader("💎 Intrinsic Valuation Laboratory (DCF)")
    
    tab_dcf, tab_models = st.tabs(["DCF Model (Smart)", "Other Models"])
    
    with tab_dcf:
        c_in, c_out = st.columns([1, 2])
        
        # --- Smart Assumptions Calculation ---
        # 1. WACC Calculation
        beta = info.get('beta', 1.0) or 1.0
        risk_free_rate = 4.2 # Approx 10Y Treasury (Dynamic in real app)
        equity_risk_premium = 5.0 # Standard assumption
        calc_cost_equity = risk_free_rate + (beta * equity_risk_premium)
        
        # Cost of Debt (Simplified: Interest Exp / Total Debt) - defaulting to 5% if data missing
        cost_debt = 5.0 
        tax_rate = 0.21
        after_tax_cost_debt = cost_debt * (1 - tax_rate)
        
        # Weights (Simplified Market Value)
        mcap = info.get('marketCap', 1)
        debt = info.get('totalDebt', 0)
        total_cap = mcap + debt
        w_e = mcap / total_cap
        w_d = debt / total_cap
        
        calculated_wacc = (w_e * calc_cost_equity) + (w_d * after_tax_cost_debt)
        calculated_wacc = min(max(calculated_wacc, 5.0), 15.0) # Clamp for sanity
        
        # 2. Growth Calculation
        rev_g = info.get('revenueGrowth', 0.05) or 0.05
        earn_g = info.get('earningsGrowth', 0.05) or 0.05
        hist_growth = (rev_g + earn_g) / 2 * 100
        
        # Conservative Growth Suggestion (lower of historical or 15%)
        suggested_growth = min(hist_growth, 15.0)
        suggested_growth = max(suggested_growth, 2.0) # Floor at inflation
        
        # 3. Terminal Growth (GDP Proxy)
        suggested_terminal = 2.5
        
        with c_in:
            st.markdown("##### ⚙️ Model Inputs")
            
            # WACC
            wacc = st.number_input("WACC (%)", 4.0, 20.0, float(round(calculated_wacc, 1)), 0.1, help=f"Weighted Average Cost of Capital. Suggestion based on Beta {beta:.2f}") / 100
            
            # Growth
            g1 = st.number_input("Growth Stage 1 (%)", 0.0, 50.0, float(round(suggested_growth, 1)), 0.5, help="FCF Growth for first stage. Based on recent earnings trends.") / 100
            
            # Duration
            years1 = st.slider("Duration Stage 1 (Years)", 3, 10, 5, help="How long will high growth last? 5y is standard.")
            
            # Terminal
            term_g = st.number_input("Terminal Growth (%)", 1.0, 5.0, 2.5, 0.1, help="Perpetual growth rate. Should not exceed GDP (2-3%).") / 100
            
            # Base FCF
            base_fcf = (engine.cf['Free Cash Flow'].iloc[-1] if not engine.cf.empty else 0) * fx_rate
            fcf_input = st.number_input(f"Base FCF ({target_symbol})", value=float(base_fcf))
            
            with st.expander("💡 Why these suggestions?", expanded=True):
                st.info(f"""
                **1. WACC ({calculated_wacc:.1f}%):**
                * Derived from **CAPM**.
                * **Beta:** {beta:.2f} (Volatility relative to market).
                * **Risk-Free Rate:** {risk_free_rate}% (10Y Treasury).
                * **Equity Risk Premium:** {equity_risk_premium}%.
                
                **2. Growth Rate ({suggested_growth:.1f}%):**
                * Based on recent Revenue Growth ({(rev_g*100):.1f}%) and Earnings Growth ({(earn_g*100):.1f}%).
                * Capped at 15% to be conservative.
                
                **3. Terminal Rate (2.5%):**
                * Standard long-term economic growth (GDP) proxy.
                """)
            
        with c_out:
            net_debt = (info.get('totalDebt', 0) - info.get('totalCash', 0)) * fx_rate
            shares = info.get('sharesOutstanding', 1)
            res = ValuationModels.dcf_2_stage(fcf_input, g1, years1, 0.05, wacc, term_g, net_debt, shares)
            
            fair_val = res.get('fair_value', 0)
            model_ev = res.get('enterprise_value', 0)
            curr = info.get('currentPrice', 1) * fx_rate
            market_ev = info.get('enterpriseValue', 0) * fx_rate
            
            upside = (fair_val / curr - 1) * 100
            
            # Scorecard
            st.metric("Fair Value per Share", f"{target_symbol}{fair_val:.2f}", f"{upside:+.2f}% Upside")
            
            # --- REALITY CHECK SECTION ---
            st.markdown("##### ⚖️ Reality Check: Model vs Market")
            ev_diff_pct = (model_ev / market_ev - 1) * 100 if market_ev else 0
            
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Model Implied EV", Utils.format_number(model_ev))
            rc2.metric("Current Market EV", Utils.format_number(market_ev))
            rc3.metric("Gap (Alpha)", f"{ev_diff_pct:+.1f}%", help="Positive = Model sees more value than Market")
            
            # Smart Commentary on Divergence
            if ev_diff_pct > 15:
                status = "Undervalued"
                reason = "The market may be underappreciating the company's future growth potential or overestimating risks (WACC)."
            elif ev_diff_pct < -15:
                status = "Overvalued"
                reason = "The market currently prices in higher growth or lower risk than your base case assumptions."
            else:
                status = "Fairly Valued"
                reason = "Your assumptions align closely with the market's current pricing consensus."
            
            st.info(f"**Analysis:** The model suggests the asset is **{status}** by {abs(ev_diff_pct):.1f}%. {reason} Verify if the 'Base FCF' ({Utils.format_number(fcf_input)}) truly reflects normalized earnings power.")
            # -----------------------------
            
            # Projections Chart
            proj = res.get('projected_fcf', [])
            years = [f"Y{i+1}" for i in range(len(proj))]
            fig_dcf = px.bar(x=years, y=proj, title="Projected Free Cash Flows (next 5 years)")
            fig_dcf.update_layout(template=plotly_template)
            st.plotly_chart(fig_dcf, use_container_width=True)
            
            render_interpretation(f"""
            **FCF Projection Analysis:**
            The chart visualizes the expected Free Cash Flow for the next {years1} years based on your {g1*100:.1f}% growth assumption.
            * **Trend:** { "Rising" if g1 > 0 else "Declining" } cash flows indicate { "growing" if g1 > 0 else "shrinking" } intrinsic value.
            * **Usage:** These flows are discounted back to present value to determine the enterprise value.
            """, "neutral")

            # Sensitivity Matrix
            st.markdown("##### Sensitivity Matrix (Terminal Growth vs WACC)")
            w_range = np.linspace(wacc-0.02, wacc+0.02, 5)
            g_range = np.linspace(term_g-0.01, term_g+0.01, 5)
            
            mat = []
            for w in w_range:
                row = []
                for g in g_range:
                    v = ValuationModels.dcf_2_stage(fcf_input, g1, years1, 0.05, w, g, net_debt, shares)['fair_value']
                    row.append(v)
                mat.append(row)
                
            fig_heat = go.Figure(data=go.Heatmap(z=mat, x=[f"{x:.1%}" for x in g_range], y=[f"{y:.1%}" for y in w_range], colorscale='RdYlGn'))
            st.plotly_chart(fig_heat, use_container_width=True)

            render_interpretation(f"""
            **Sensitivity Analysis Interpretation:**
            This matrix shows how the Fair Value per share changes with different WACC (Discount Rate) and Terminal Growth assumptions.
            * **X-Axis (Terminal Growth):** Higher growth = Higher Value.
            * **Y-Axis (WACC):** Higher risk/cost of capital = Lower Value.
            * **Use Case:** If the current price fits within the 'green' zones, the stock might be undervalued even with conservative estimates. If it requires the top-right corner assumptions to justify the price, it is priced for perfection.
            """, "neutral")

    with tab_models:
        eps = info.get('trailingEps', 0) * fx_rate
        bvps = info.get('bookValue', 0) * fx_rate
        growth = info.get('earningsGrowth', 0) * 100
        graham = ValuationModels.graham_number(eps, bvps)
        lynch = ValuationModels.peter_lynch_value(eps, growth)
        c1, c2 = st.columns(2)
        c1.metric("Graham Number", f"{target_symbol}{graham:.2f}", help="Sqrt(22.5 * EPS * BVPS)")
        c2.metric("Peter Lynch Fair Value", f"{target_symbol}{lynch:.2f}", help="PEG=1 Assumption")

# ==============================================================================
# MODULE 6: PEER VALUATION & COMPARABLES (ENHANCED)
# ==============================================================================
elif module == "6. Peer Valuation & Comparables":
    st.subheader("🆚 Relative Valuation & Peer Matrix")
    
    # 1. Concept Section
    with st.expander("📚 Concept & Methodology", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **Relative Valuation (Comps):**
            Assets are valued by comparing them to similar assets. If your peers trade at 15x Earnings and you trade at 10x, you might be undervalued—or you might have lower growth.
            
            **Key Metrics:**
            * **EV/EBITDA:** Best for capital-intensive industries (ignores debt structure).
            * **P/E:** Standard equity multiple.
            * **PEG Ratio:** Adjusts P/E for growth.
            """)
        with c2:
            st.markdown("""
            **The Value Line (Growth vs Value):**
            We plot peers based on Growth (X-Axis) vs Valuation (Y-Axis). 
            * **Below Line:** Undervalued relative to growth.
            * **Above Line:** Overvalued relative to growth.
            """)

    # 2. Peer Selection
    peers = engine.get_peers()
    peers_sel = st.multiselect("Select Peer Group", peers + ["SPY", "QQQ"], default=peers[:4])
    
    # New: Manual Input
    custom_peers = st.text_input("Add Custom Peers (comma separated)", placeholder="e.g. NVDA, AMD")
    if custom_peers:
        additional_peers = [p.strip().upper() for p in custom_peers.split(",") if p.strip()]
        for p in additional_peers:
            if p not in peers_sel:
                peers_sel.append(p)
    
    if not peers_sel:
        st.warning("Please select at least one peer.")
        st.stop()

    # 3. Data Fetching (Optimized Loop)
    with st.spinner("Analyzing Peer Group..."):
        peer_data = []
        unique_peers = []
        [unique_peers.append(x) for x in peers_sel + [ticker_input] if x not in unique_peers]

        for p in unique_peers:
            try:
                # Use st.cache_data wrapper in real app for speed, here direct fetch
                pi = yf.Ticker(p).info
                if 'currentPrice' not in pi: continue
                
                raw_price = pi.get('currentPrice', 0)
                peer_curr = pi.get('currency', 'USD')
                peer_fx = CurrencyFX.get_fx_rate(peer_curr, target_currency)
                
                # Core Metrics
                ev_ebitda = pi.get('enterpriseToEbitda')
                pe = pi.get('trailingPE')
                pb = pi.get('priceToBook')
                ps = pi.get('priceToSalesTrailing12Months')
                rev_growth = pi.get('revenueGrowth', 0)
                mcap = pi.get('marketCap', 0) * peer_fx
                
                # Filter out extreme outliers (e.g. P/E > 500 or negative) for better charts
                if pe and (pe > 500 or pe < 0): pe = None
                if ev_ebitda and (ev_ebitda > 200 or ev_ebitda < 0): ev_ebitda = None

                peer_data.append({
                    "Ticker": p,
                    f"Price ({target_currency})": raw_price * peer_fx,
                    "EV/EBITDA": ev_ebitda,
                    "P/E": pe,
                    "P/B": pb,
                    "EV/Sales": ps,
                    "Revenue Growth (%)": rev_growth * 100 if rev_growth else 0,
                    "Market Cap": mcap
                })
            except: 
                pass
            
        df_peers = pd.DataFrame(peer_data).set_index("Ticker")
        
        # 4. Multiples Table
        st.markdown("#### Peer Multiples Matrix")
        
        def highlight_target(s):
            return ['background-color: #d4edda' if s.name == ticker_input else '' for _ in s]
        
        def safe_fmt(x): return f"{x:.2f}" if isinstance(x, (int, float)) else "N/A"
        
        st.dataframe(df_peers.style.apply(highlight_target, axis=1).format(safe_fmt), use_container_width=True)

        if ticker_input in df_peers.index:
            target_stats = df_peers.loc[ticker_input]
            peers_only = df_peers.drop(ticker_input)
            
            # --- VISUAL 1: The "Value Matrix" (Scatter Plot) ---
            st.markdown("#### 📉 The Value Matrix: Growth vs. Valuation")
            
            # Prepare data for scatter
            scatter_df = df_peers.dropna(subset=['Revenue Growth (%)', 'EV/EBITDA'])
            
            if not scatter_df.empty:
                fig_scatter = px.scatter(
                    scatter_df, 
                    x="Revenue Growth (%)", 
                    y="EV/EBITDA", 
                    text=scatter_df.index,
                    size="Market Cap",
                    color=scatter_df.index == ticker_input,
                    color_discrete_map={True: '#27ae60', False: '#3498db'},
                    trendline="ols", # Ordinary Least Squares Regression
                    trendline_scope="overall"
                )
                fig_scatter.update_traces(textposition='top center')
                fig_scatter.update_layout(
                    title="Regression: EV/EBITDA vs Revenue Growth",
                    template=plotly_template,
                    showlegend=False
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
                
                # Scatter Interpretation
                target_growth = scatter_df.loc[ticker_input, "Revenue Growth (%)"]
                target_ev = scatter_df.loc[ticker_input, "EV/EBITDA"]
                
                scatter_sent = "bullish" if target_growth > scatter_df["Revenue Growth (%)"].median() and target_ev < scatter_df["EV/EBITDA"].median() else "neutral"
                
                render_interpretation(f"**Interpretation:** Tickers below the trendline are typically considered 'cheap' for their growth rate. "
                                      f"{ticker_input} has {target_growth:.1f}% growth vs peer median {scatter_df['Revenue Growth (%)'].median():.1f}%, "
                                      f"trading at {target_ev:.1f}x EBITDA.", scatter_sent)
            else:
                st.info("Not enough data points for Regression Analysis.")

            # --- VISUAL 2: Implied Valuation Football Field (Ranges) ---
            st.markdown("#### 🎯 Implied Valuation Ranges")

            # Calc Stats
            metrics = {
                "P/E": ("trailingEps", None),
                "P/B": ("bookValue", None), 
                "EV/EBITDA": ("ebitda", "NetDebt")
            }
            
            t_net_debt = (info.get('totalDebt', 0) - info.get('totalCash', 0)) * fx_rate
            t_shares = info.get('sharesOutstanding', 1)

            plot_data = []

            for name, (input_key, adjust) in metrics.items():
                # Get Target Input
                val = info.get(input_key, 0)
                if val is None: val = 0
                val = val * fx_rate
                
                # Get Peer Multiples Stats
                multiples = peers_only[name].dropna()
                if multiples.empty: continue
                
                low_mult = multiples.quantile(0.25)
                med_mult = multiples.median()
                high_mult = multiples.quantile(0.75)
                
                # Calculate Implied Price
                def get_price(mult):
                    if adjust == "NetDebt":
                        ev = mult * val
                        equity = ev - t_net_debt
                        return equity / t_shares
                    else:
                        return mult * val
                
                p_low = get_price(low_mult)
                p_mid = get_price(med_mult)
                p_high = get_price(high_mult)
                
                if p_low > 0 and p_high > 0:
                    plot_data.append({
                        "Metric": name,
                        "Low": p_low,
                        "Mid": p_mid,
                        "High": p_high
                    })

            # Plot Football Field
            if plot_data:
                fig_fb = go.Figure()
                curr_p = target_stats[f"Price ({target_currency})"]

                for d in plot_data:
                    # Range Bar
                    fig_fb.add_trace(go.Bar(
                        y=[d['Metric']], 
                        x=[d['High'] - d['Low']], 
                        base=[d['Low']],
                        orientation='h',
                        marker_color='rgba(52, 152, 219, 0.3)',
                        name=f"{d['Metric']} Range",
                        hoverinfo='text',
                        hovertext=f"{d['Metric']}<br>Low: {d['Low']:.2f}<br>High: {d['High']:.2f}"
                    ))
                    # Median Line
                    fig_fb.add_trace(go.Scatter(
                        y=[d['Metric']], x=[d['Mid']],
                        mode='markers',
                        marker=dict(color='#2c3e50', size=12, symbol='line-ns-open'),
                        name="Peer Median"
                    ))

                # Current Price Line
                fig_fb.add_vline(x=curr_p, line_width=2, line_dash="dash", line_color="#e74c3c", annotation_text="Current")
                
                fig_fb.update_layout(
                    title="Valuation Football Field (25th-75th Percentile)",
                    barmode='overlay',
                    xaxis_title=f"Implied Share Price ({target_symbol})",
                    template=plotly_template,
                    showlegend=False
                )
                st.plotly_chart(fig_fb, use_container_width=True)

                # Summary Table
                st.markdown("#### 📋 Valuation Summary")
                summary_df = pd.DataFrame(plot_data)
                summary_df['Upside to Mid (%)'] = ((summary_df['Mid'] / curr_p) - 1) * 100
                st.dataframe(summary_df.style.format({
                    "Low": "{:,.2f}", "Mid": "{:,.2f}", "High": "{:,.2f}", "Upside to Mid (%)": "{:+.2f}%"
                }), use_container_width=True)
                
                # Conclusion
                avg_upside = summary_df['Upside to Mid (%)'].mean()
                sent = "bullish" if avg_upside > 5 else "bearish" if avg_upside < -5 else "neutral"
                render_interpretation(f"The average implied upside based on peer medians is **{avg_upside:+.2f}%**. "
                                      f"The stock is trading {'below' if avg_upside > 0 else 'above'} the peer median valuation.", sent)

# ==============================================================================
# MODULE 7: RISK MANAGEMENT (Renamed)
# ==============================================================================
elif module == "7. Risk Management":
    st.subheader("🛡️ Portfolio Risk Analytics")
    risk = engine.risk_analysis()
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Beta", f"{info.get('beta', 0):.2f}")
    r2.metric("Annual Volatility", f"{risk.get('vol', 0)*100:.1f}%")
    r3.metric("VaR (95% Daily)", f"{risk.get('var_95', 0)*100:.2f}%")
    r4.metric("Max Drawdown (2Y)", f"{risk.get('max_dd', 0)*100:.2f}%")
    
    # Interpretation for Risk
    beta = info.get('beta', 1)
    beta_sent = "bullish" if beta < 1 else "bearish" # Lower beta is safer in downturns
    render_interpretation(f"Beta of **{beta:.2f}** suggests the stock is **{'less' if beta < 1 else 'more'}** volatile than the market. "
                          f"A VaR of {risk.get('var_95', 0)*100:.2f}% implies that in a worst-case normal day (95% confidence), you could lose this much.", beta_sent)

    # Simulation (Monte Carlo)
    st.subheader("🎲 Monte Carlo Simulation (Next 252 Days)")
    
    if st.button("Run Simulation"):
        hist = engine.stock.history(period="1y")['Close'] * fx_rate
        returns = hist.pct_change().dropna()
        mu = returns.mean()
        sigma = returns.std()
        last_price = hist.iloc[-1]
        
        simulations = 100
        days = 252
        sim_df = pd.DataFrame()
        
        for x in range(simulations):
            price_list = [last_price]
            for d in range(days):
                price = price_list[-1] * (1 + np.random.normal(mu, sigma))
                price_list.append(price)
            sim_df[f"Sim {x}"] = price_list
            
        fig_mc = px.line(sim_df, title=f"{simulations} Random Price Paths")
        fig_mc.update_layout(showlegend=False, yaxis_title=f"Price ({target_currency})")
        st.plotly_chart(fig_mc, use_container_width=True)
        
        # Stats
        final_prices = sim_df.iloc[-1]
        median_px = final_prices.median()
        
        mc_sent = "bullish" if median_px > last_price else "bearish"
        st.info(f"Median Expected Price: {target_symbol}{median_px:.2f} | 95% Confidence Range: {target_symbol}{final_prices.quantile(0.05):.2f} - {target_symbol}{final_prices.quantile(0.95):.2f}")
        
        render_interpretation(f"The Monte Carlo simulation predicts a median price of **{target_symbol}{median_px:.2f}** in one year. "
                              f"This suggests a **{(median_px/last_price - 1)*100:.1f}%** potential return based on historical volatility drift.", mc_sent)

# ==============================================================================
# MODULE 8: PRICE & CAPITAL DYNAMICS (Renamed)
# ==============================================================================
elif module == "8. Price & Capital Dynamics":
    st.subheader("📉 Market Cap & EV Mechanics")
    
    hist = engine.get_history(period=sel_period, interval=sel_interval)
    shares = info.get('sharesOutstanding', 0)
    if shares == 0: shares = 1
    
    hist['Close'] = hist['Close'] * fx_rate
    hist['Market Cap'] = hist['Close'] * shares
    
    # --- TREND DETECTION LOGIC ---
    # Rolling 20-day returns to find momentum peaks/troughs
    hist['Rolling_Ret'] = hist['Close'].pct_change(20)
    
    # Identify key points
    max_rally_idx = hist['Rolling_Ret'].idxmax()
    max_drawdown_idx = hist['Rolling_Ret'].idxmin()
    
    rally_val = hist.loc[max_rally_idx, 'Rolling_Ret'] if pd.notnull(max_rally_idx) else 0
    drawdown_val = hist.loc[max_drawdown_idx, 'Rolling_Ret'] if pd.notnull(max_drawdown_idx) else 0

    # Chart Construction
    fig_dual = make_subplots(specs=[[{"secondary_y": True}]])
    fig_dual.add_trace(go.Scatter(x=hist.index, y=hist['Market Cap'], name="Market Cap", line=dict(color='#8e44ad', dash='dot', width=2), opacity=0.6), secondary_y=True)
    fig_dual.add_trace(go.Scatter(x=hist.index, y=hist['Close'], name="Price", line=dict(color='#2c3e50', width=2.5)), secondary_y=False)
    
    # Annotations for Strongest Moves
    if pd.notnull(max_rally_idx):
        fig_dual.add_annotation(x=max_rally_idx, y=hist.loc[max_rally_idx, 'Close'],
            text="Strongest Rally", showarrow=True, arrowhead=1, ax=0, ay=-40, bgcolor="#27ae60", font=dict(color="white"))
            
    if pd.notnull(max_drawdown_idx):
        fig_dual.add_annotation(x=max_drawdown_idx, y=hist.loc[max_drawdown_idx, 'Close'],
            text="Deepest Drop", showarrow=True, arrowhead=1, ax=0, ay=40, bgcolor="#e74c3c", font=dict(color="white"))

    fig_dual.update_layout(
        title="Price vs Market Cap (Click to Inspect EV)",
        yaxis_title=f"Price ({target_symbol})",
        yaxis2_title=f"Market Cap ({target_symbol})",
        hovermode="x unified",
        height=450,
        template=plotly_template,
        xaxis=dict(rangeslider=dict(visible=True)) # Zoom Slider
    )
    
    # Selection Event
    selection = st.plotly_chart(fig_dual, use_container_width=True, on_select="rerun", selection_mode="points")
    
    # Trend Interpretation
    trend_sent = "bullish" if rally_val > abs(drawdown_val) else "bearish"
    render_interpretation(f"""
    **Trend Analysis:**
    The strongest 20-day rally occurred around **{max_rally_idx.strftime('%Y-%m-%d') if pd.notnull(max_rally_idx) else 'N/A'}** with a gain of **{rally_val*100:.1f}%**.
    The sharpest 20-day drop was around **{max_drawdown_idx.strftime('%Y-%m-%d') if pd.notnull(max_drawdown_idx) else 'N/A'}** with a loss of **{drawdown_val*100:.1f}%**.
    
    *Factors:* Volatility clusters often align with earnings releases or macro events. Steep downtrends usually indicate institutional distribution or sector rotation.
    """, trend_sent)
    
    # Dynamic EV Bridge
    st.markdown("#### Enterprise Value Bridge (Snapshot)")
    sel_date_str = "Latest"
    sel_mcap = info.get('marketCap', 0) * fx_rate
    sel_debt = info.get('totalDebt', 0) * fx_rate
    sel_cash = info.get('totalCash', 0) * fx_rate
    
    if selection and selection["selection"]["points"]:
        point = selection["selection"]["points"][0]
        sel_x = point["x"]
        try:
            ts = pd.to_datetime(sel_x).tz_localize(None)
            idx_loc = hist.index.get_indexer([ts], method='nearest')[0]
            sel_mcap = hist.iloc[idx_loc]['Market Cap']
            sel_date_str = ts.strftime('%Y-%m-%d')
            # Approximation: Use current debt/cash structure applied to historical mcap 
            # (Historical BS data is hard to sync perfectly without premium API)
        except: pass

    fig_ev = go.Figure(go.Waterfall(
        measure=["relative", "relative", "relative", "total"],
        x=["Market Cap", "+ Debt", "- Cash", "Enterprise Value"],
        y=[sel_mcap, sel_debt, -sel_cash, 0],
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        totals={"marker": {"color": "#3498db"}}
    ))
    fig_ev.update_layout(title=f"EV Snapshot ({sel_date_str})", template=plotly_template)
    st.plotly_chart(fig_ev, use_container_width=True)

# ==============================================================================
# MODULE 9: MARKET LEADERS RANKING (NEW)
# ==============================================================================
elif module == "9. Market Leaders Ranking":
    st.subheader("🏆 Market Leaders & Trends")
    st.markdown("Compare the market capitalization and revenue of top market leaders at a specific point in time.")

    # 1. Define Basket & Mode
    market_pools = {
        "🇺🇸 USA / Global": [
            "AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META", "TSLA", "BRK-B", "LLY", "TSM",
            "AVGO", "V", "JPM", "WMT", "XOM", "UNH", "MA", "PG", "JNJ", "COST",
            "HD", "MRK", "ORCL", "ABBV", "CVX", "BAC", "KO", "PEP", "CRM", "AMD"
        ],
        "🇩🇪 Germany (DAX)": [
            "SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "VOW3.DE", "BMW.DE", "BAS.DE", "ADS.DE", 
            "MBG.DE", "IFX.DE", "AIR.DE", "MUV2.DE", "DB1.DE", "DHL.DE", "BEI.DE"
        ],
        "🇬🇧 UK (FTSE)": [
            "SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "BP.L", "RIO.L", "GSK.L", "DGE.L", "BATS.L", 
            "REL.L", "GLEN.L", "LSEG.L", "CNA.L", "NG.L", "LLOY.L"
        ],
        "🇯🇵 Japan (Nikkei)": [
            "7203.T", "6758.T", "9432.T", "6861.T", "8035.T", "9984.T", "8058.T", "4063.T", "9983.T", "7974.T",
            "8306.T", "6098.T", "4568.T", "6501.T", "6902.T"
        ],
        "🇻🇳 Vietnam": [
             "VCB.VN", "VHM.VN", "VIC.VN", "GAS.VN", "VNM.VN", "HPG.VN", "BID.VN", "MSN.VN", "SAB.VN", "CTG.VN",
             "TCB.VN", "VPB.VN", "MBB.VN", "FPT.VN", "MWG.VN"
        ]
    }

    mode = st.radio("Selection Mode", ["Auto-Detect (Market Pool)", "Manual Ticker List"])

    if mode == "Auto-Detect (Market Pool)":
        sel_market = st.selectbox("Select Market", list(market_pools.keys()))
        leader_tickers = market_pools[sel_market]
        st.info(f"Scanning pool of {len(leader_tickers)} companies in {sel_market} to find the top leaders.")
    else:
        default_leaders = ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META", "TSLA", "BRK-B", "LLY", "TSM"]
        custom_leaders = st.text_input("Customize Leaderboard Tickers (comma separated)", value=", ".join(default_leaders))
        leader_tickers = [x.strip().upper() for x in custom_leaders.split(",") if x.strip()]

    # 2. Time Selection
    lookback_days = 365 * 20 # Expanded to 20 Years
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    
    # Slider for date
    selected_date = st.slider("Select Date for Ranking Snapshot", min_value=start_date.date(), max_value=end_date.date(), value=end_date.date())

    if st.button("Generate Ranking Snapshot", type="primary"):
        with st.spinner(f"Analyzing Market Data for {selected_date}..."):
            leader_data = []
            
            # Progress bar for UX
            progress_bar = st.progress(0)
            
            # Optimized Logic: Fetch prices for ALL tickers in one batch if possible
            # However, we also need Name and Industry which requires looping or .info calls.
            # To keep it responsive, we loop.
            
            # Batch fetch prices for efficiency
            batch_tickers = " ".join(leader_tickers)
            start_window = selected_date - timedelta(days=5)
            end_window = selected_date + timedelta(days=1)
            
            try:
                # yf.download is faster for bulk history
                batch_hist = yf.download(batch_tickers, start=start_window, end=end_window, progress=False)['Close']
            except:
                batch_hist = pd.DataFrame()

            for i, ticker in enumerate(leader_tickers):
                try:
                    price_at_date = 0
                    # Get Price from Batch
                    if not batch_hist.empty:
                        # Check if multiple columns (multiple tickers) or single series (one ticker)
                        if isinstance(batch_hist, pd.DataFrame) and ticker in batch_hist.columns:
                             price_series = batch_hist[ticker].dropna()
                             if not price_series.empty:
                                 price_at_date = price_series.iloc[-1]
                        elif isinstance(batch_hist, pd.Series) and batch_hist.name == ticker: # Single ticker case
                             price_at_date = batch_hist.dropna().iloc[-1]
                    
                    # Fallback individual fetch if batch failed
                    if price_at_date == 0:
                         t = yf.Ticker(ticker)
                         h = t.history(start=start_window, end=end_window)
                         if not h.empty:
                             price_at_date = h['Close'].iloc[-1]

                    if price_at_date > 0:
                        # Get Info (Name, Industry, Shares)
                        # This is the slow part, but necessary for requested features
                        t_obj = yf.Ticker(ticker)
                        info_data = t_obj.info
                        
                        shares = info_data.get('sharesOutstanding', 0)
                        name = info_data.get('longName', ticker)
                        industry = info_data.get('industry', 'N/A')
                        
                        # Currency Conversion
                        ticker_currency = info_data.get('currency', 'USD')
                        leader_fx = CurrencyFX.get_fx_rate(ticker_currency, target_currency)
                        
                        mcap_at_date = (price_at_date * shares) * leader_fx
                        price_converted = price_at_date * leader_fx
                        
                        # Store prelim data
                        leader_data.append({
                            "Ticker": ticker,
                            "Name": name,
                            "Industry": industry,
                            "Market Cap": mcap_at_date,
                            "Price": price_converted,
                            "Obj": t_obj, # Store object to fetch revenue later only for top N
                            "FX": leader_fx
                        })
                except:
                    pass
                
                # Update progress
                progress_bar.progress((i + 1) / len(leader_tickers))
            
            progress_bar.empty()
            
            if leader_data:
                # Rank by Market Cap
                df_leaders = pd.DataFrame(leader_data)
                df_leaders = df_leaders.sort_values(by="Market Cap", ascending=False).reset_index(drop=True)
                
                # Take Top 10
                df_top10 = df_leaders.head(10).copy()
                
                # Now fetch Revenue ONLY for these top 10 (Efficiency!)
                revenues = []
                for _, row in df_top10.iterrows():
                    t = row['Obj']
                    fx = row['FX']
                    rev = 0
                    try:
                        financials = t.income_stmt
                        if not financials.empty:
                            # Logic to find revenue closest to date
                            financial_dates = pd.to_datetime(financials.columns)
                            valid_reports = [d for d in financial_dates if d.date() <= selected_date]
                            if valid_reports:
                                report_date = max(valid_reports)
                                col_idx = financial_dates.get_loc(report_date)
                                rev = financials.iloc[:, col_idx].get('Total Revenue', 0)
                            else:
                                rev = financials.iloc[:, -1].get('Total Revenue', 0)
                    except:
                        pass
                    revenues.append(rev * fx) # Apply FX
                
                df_top10['Revenue (TTM)'] = revenues
                
                # --- PLOT ---
                fig_combo = make_subplots(specs=[[{"secondary_y": True}]])

                # Bar: Market Cap (Left Axis)
                fig_combo.add_trace(
                    go.Bar(
                        x=df_top10['Ticker'],
                        y=df_top10['Market Cap'],
                        name="Market Cap",
                        marker_color='#00b4d8',
                        opacity=0.8,
                        hovertemplate=f'%{{x}}<br>Market Cap: {target_symbol}%{{y:,.0f}}'
                    ),
                    secondary_y=False
                )

                # Line: Revenue (Right Axis)
                fig_combo.add_trace(
                    go.Scatter(
                        x=df_top10['Ticker'],
                        y=df_top10['Revenue (TTM)'],
                        name="Revenue (FY)",
                        mode='lines+markers',
                        marker=dict(size=12, color='#ff4d6d'),
                        line=dict(width=3, color='#ff4d6d'),
                        hovertemplate=f'%{{x}}<br>Revenue: {target_symbol}%{{y:,.0f}}'
                    ),
                    secondary_y=True
                )

                # Layout
                fig_combo.update_layout(
                    title=f"Top 10 Leaders by Market Cap & Revenue (Snapshot: {selected_date})",
                    template=plotly_template,
                    hovermode="x unified",
                    height=500,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                
                fig_combo.update_yaxes(title_text=f"Market Cap ({target_symbol})", secondary_y=False)
                fig_combo.update_yaxes(title_text=f"Revenue ({target_symbol})", secondary_y=True)

                st.plotly_chart(fig_combo, use_container_width=True)
                
                # --- NEW: Historical Trend Chart ---
                st.markdown("### 📈 Market Cap Trajectory (3 Year Trend)")
                
                # Get tickers from top 10
                top_tickers_list = df_top10['Ticker'].tolist()
                
                # Fetch history for 3 years
                end_hist = datetime.now()
                start_hist = end_hist - timedelta(days=365*3)
                
                with st.spinner("Loading historical trends..."):
                    try:
                        # Bulk download is faster
                        hist_data = yf.download(top_tickers_list, start=start_hist, end=end_hist, progress=False)['Close']
                        
                        fig_trend = go.Figure()
                        
                        for ticker in top_tickers_list:
                            # Get specific metadata for this ticker from df_top10
                            meta = df_top10[df_top10['Ticker'] == ticker].iloc[0]
                            shares = meta['Obj'].info.get('sharesOutstanding', 0)
                            fx = meta['FX']
                            
                            # Handle single ticker result vs multiple from yf.download
                            if len(top_tickers_list) == 1:
                                series = hist_data
                            elif isinstance(hist_data, pd.DataFrame) and ticker in hist_data.columns:
                                series = hist_data[ticker]
                            else:
                                continue # Skip if data missing
                            
                            # Calculate Mcap Trend
                            series = series.dropna()
                            mcap_series = series * shares * fx
                            
                            fig_trend.add_trace(go.Scatter(
                                x=mcap_series.index,
                                y=mcap_series,
                                name=ticker,
                                mode='lines',
                                hovertemplate=f'%{{x}}<br>{target_symbol}%{{y:,.0f}}'
                            ))
                            
                        fig_trend.update_layout(
                            title="Market Cap Change Over Time (Top 10 Leaders)",
                            yaxis_title=f"Market Cap ({target_symbol})",
                            template=plotly_template,
                            hovermode="x unified",
                            height=500,
                            xaxis=dict(
                                rangeselector=dict(
                                    buttons=list([
                                        dict(count=1, label="1m", step="month", stepmode="backward"),
                                        dict(count=6, label="6m", step="month", stepmode="backward"),
                                        dict(count=1, label="1y", step="year", stepmode="backward"),
                                        dict(count=3, label="3y", step="year", stepmode="backward"),
                                        dict(step="all")
                                    ])
                                ),
                                rangeslider=dict(visible=True),
                                type="date"
                            )
                        )
                        st.plotly_chart(fig_trend, use_container_width=True)
                        
                    except Exception as e:
                        st.warning(f"Could not load trend data: {e}")

                # --- DATA TABLE ---
                st.markdown("##### 📋 Ranking Details")
                
                # Format for display
                df_display = df_top10[['Ticker', 'Name', 'Industry', 'Market Cap', 'Revenue (TTM)', 'Price']].copy()
                df_display['Market Cap'] = df_display['Market Cap'].apply(lambda x: Utils.format_currency(x, target_symbol))
                df_display['Revenue (TTM)'] = df_display['Revenue (TTM)'].apply(lambda x: Utils.format_currency(x, target_symbol))
                df_display['Price'] = df_display['Price'].apply(lambda x: f"{target_symbol}{x:,.2f}")
                df_display.index += 1 # Start rank at 1
                
                st.dataframe(df_display, use_container_width=True)
                
            else:
                st.error("No data found for the selected tickers/date.")


# --- FOOTER ---
st.markdown("""
<div class="footer">
    Investment Terminal Pro | Developed by <b>Minh Phu Dinh</b> | Data Source: Yahoo Finance<br>
    Disclaimer: Not financial advice. Educational purposes only.
</div>
""", unsafe_allow_html=True)