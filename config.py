import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.graph_objects as go

# ==========================================
# CORE ENGINE (MULTI-MARKET: US / VN / DE)
# ==========================================
class FinanceEngine:
    def __init__(self, ticker, market="US"):
        self.raw_ticker = ticker.upper().strip()
        self.market = market
        
        # 1. Handle Market Suffixes
        if market == "VN":
            self.suffix = ".VN"
            self.full_ticker = self.raw_ticker if self.raw_ticker.endswith(".VN") else f"{self.raw_ticker}.VN"
        elif market == "DE":
            self.suffix = ".DE"  # Defaults to Xetra
            self.full_ticker = self.raw_ticker if self.raw_ticker.endswith(".DE") else f"{self.raw_ticker}.DE"
        else:  # US or Direct
            self.suffix = ""
            self.full_ticker = self.raw_ticker

        # 2. Fetch Data
        self.stock = yf.Ticker(self.full_ticker)
        
        try:
            self.info = self.stock.info
            # Check if data exists by looking for a price
            self.valid = 'currentPrice' in self.info and self.info['currentPrice'] is not None
        except Exception:
            self.valid = False
            self.info = {}

        if self.valid:
            # Fetch Financials
            self.income_stmt = self.stock.financials.T.sort_index(ascending=True)
            self.balance_sheet = self.stock.balance_sheet.T.sort_index(ascending=True)
            self.cash_flow = self.stock.cashflow.T.sort_index(ascending=True)
            self.hist_data = self.stock.history(period="2y")
            self.currency = self.info.get('currency', 'USD')
        else:
            self.currency = 'USD'

    # --- MODULE 1: COMPANY OVERVIEW ---
    def get_kpi_summary(self):
        i = self.info
        return {
            "Market Cap": i.get('marketCap', 0),
            "Enterprise Value": i.get('enterpriseValue', 0),
            "Beta": i.get('beta', 0),
            "Price": i.get('currentPrice', 0),
            "52W High": i.get('fiftyTwoWeekHigh', 0),
            "52W Low": i.get('fiftyTwoWeekLow', 0),
            "Currency": self.currency
        }

    # --- MODULE 2: GROWTH ANALYSIS ---
    def get_growth_quality(self):
        if self.income_stmt.empty: return {}
        
        rev = self.income_stmt.get('Total Revenue', pd.Series())
        ni = self.income_stmt.get('Net Income', pd.Series())
        
        if rev.empty: return {}

        years = len(rev)
        cagr_3y = ((rev.iloc[-1] / rev.iloc[-3]) ** (1 / 3) - 1) * 100 if years >= 3 else 0
        cagr_5y = ((rev.iloc[-1] / rev.iloc[0]) ** (1 / years) - 1) * 100 if years >= 5 else 0
        
        rev_growth = rev.pct_change()
        volatility = rev_growth.std() * 100
        
        try:
            fcf = self.cash_flow['Free Cash Flow'].iloc[-1]
        except Exception:
            # Fallback calculation
            ocf = self.cash_flow.get('Operating Cash Flow', pd.Series([0])).iloc[-1]
            capex = self.cash_flow.get('Capital Expenditure', pd.Series([0])).iloc[-1]
            fcf = ocf + capex
        
        # Quality Ratio
        current_ni = ni.iloc[-1] if not ni.empty else 0
        eq_ratio = fcf / current_ni if current_ni != 0 else 0
        
        return {
            "Revenue CAGR 3Y": cagr_3y,
            "Revenue CAGR 5Y": cagr_5y,
            "Rev Volatility": volatility,
            "FCF/Net Income": eq_ratio
        }

    # --- MODULE 3: EFFICIENCY ---
    def get_efficiency_metrics(self):
        if self.income_stmt.empty: return pd.DataFrame()
        
        df = pd.DataFrame(index=self.income_stmt.index)
        tax_rate = 0.21  # Simplified global assumption
        
        ebit = self.income_stmt.get('EBIT', self.income_stmt.get('Pretax Income'))
        if ebit is None: return pd.DataFrame()

        nopat = ebit * (1 - tax_rate)
        
        equity = self.balance_sheet.get('Stockholders Equity', 0)
        debt = self.balance_sheet.get('Total Debt', 0)
        cash = self.balance_sheet.get('Cash And Cash Equivalents', 0)
        inv_cap = equity + debt - cash
        
        # Avoid division by zero
        df['ROIC (%)'] = (nopat / inv_cap.replace(0, np.nan)) * 100
        
        return df.sort_index(ascending=False).dropna()

    # --- MODULE 4: RISK ---
    def get_risk_metrics(self):
        if not self.hist_data.empty:
            daily_ret = self.hist_data['Close'].pct_change().dropna()
            volatility_1y = daily_ret.std() * np.sqrt(252) * 100
            
            rolling_max = self.hist_data['Close'].cummax()
            drawdown = (self.hist_data['Close'] - rolling_max) / rolling_max
            max_drawdown = drawdown.min() * 100
        else:
            volatility_1y = 0
            max_drawdown = 0

        last_bs = self.balance_sheet.iloc[-1] if not self.balance_sheet.empty else {}

        # NOTE: yfinance's balance sheet rows are labelled "Current Assets" /
        # "Current Liabilities", not "Total Current Assets" / "Total Current
        # Liabilities" - the old keys silently returned the 0/1 defaults below,
        # so Current Ratio was always showing as 0. Fixed to the real field names.
        curr_assets = last_bs.get('Current Assets', 0)
        curr_liab = last_bs.get('Current Liabilities', 1)
        curr_ratio = curr_assets / curr_liab if curr_liab else 0
        
        net_debt = self.info.get('totalDebt', 0) - self.info.get('totalCash', 0)
        ebitda = self.info.get('ebitda', 1)
        nd_ebitda = net_debt / ebitda if ebitda else 0
        
        return {
            "Volatility (1Y)": volatility_1y,
            "Max Drawdown": max_drawdown,
            "Current Ratio": curr_ratio,
            "Net Debt/EBITDA": nd_ebitda
        }

    # --- MODULE 5: DCF ---
    def run_dcf(self, g_rate, t_rate, wacc):
        try:
            # Attempt to get FCF from Yahoo, fallback to OCF - Capex
            if 'Free Cash Flow' in self.cash_flow.columns:
                last_fcf = self.cash_flow['Free Cash Flow'].iloc[-1]
            else:
                ocf = self.cash_flow.get('Operating Cash Flow', pd.Series([0])).iloc[-1]
                capex = self.cash_flow.get('Capital Expenditure', pd.Series([0])).iloc[-1]
                last_fcf = ocf + capex  # Capex is usually negative

            # Guard against WACC <= terminal growth, which makes the Gordon
            # Growth denominator zero or negative and produces a nonsense value.
            if wacc <= t_rate:
                wacc = t_rate + 0.02
            
            # Simple 2-Stage DCF
            future_fcf = [last_fcf * ((1 + g_rate) ** i) for i in range(1, 6)]
            
            # Terminal Value (Gordon Growth)
            tv = (future_fcf[-1] * (1 + t_rate)) / (wacc - t_rate)
            
            # Discounting
            pv_fcf = sum([f / ((1 + wacc) ** (i + 1)) for i, f in enumerate(future_fcf)])
            pv_tv = tv / ((1 + wacc) ** 5)
            
            enterprise_value = pv_fcf + pv_tv
            
            net_debt = self.info.get('totalDebt', 0) - self.info.get('totalCash', 0)
            equity_value = enterprise_value - net_debt
            shares = self.info.get('sharesOutstanding', 1)
            
            fair_value = equity_value / shares
            
            return {
                "Fair Value": fair_value,
                "Upside": (fair_value - self.info.get('currentPrice', 0)) / self.info.get('currentPrice', 1) * 100,
                "EV breakdown": {"PV of FCF (5y)": pv_fcf, "PV of Terminal Value": pv_tv}
            }
        except Exception as e:
            return {"Fair Value": 0, "Upside": 0, "Error": str(e)}

    # --- MODULE 6: PEERS ---
    def get_peer_comparison(self, peer_list_raw):
        data = []
        # Add market suffix to peers if they don't have one
        clean_peers = []
        for p in peer_list_raw:
            p = p.upper().strip()
            if self.market == "VN" and not p.endswith(".VN"): p += ".VN"
            elif self.market == "DE" and not p.endswith(".DE"): p += ".DE"
            clean_peers.append(p)
            
        all_tickers = [self.full_ticker] + clean_peers
        
        for t in all_tickers:
            try:
                stock = yf.Ticker(t)
                i = stock.info
                # Basic checks to ensure data exists
                if 'currentPrice' not in i: continue
                
                data.append({
                    "Ticker": t.replace(".VN", "").replace(".DE", ""),
                    "Price": i.get('currentPrice'),
                    "P/E": i.get('trailingPE', None),
                    "Fwd P/E": i.get('forwardPE', None),
                    "P/B": i.get('priceToBook', None),
                    "ROE (%)": i.get('returnOnEquity', 0) * 100 if i.get('returnOnEquity') else None,
                    "Margins (%)": i.get('profitMargins', 0) * 100 if i.get('profitMargins') else None
                })
            except Exception:
                continue
            
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.set_index("Ticker")
        return df

# ==========================================
# STREAMLIT UI
# ==========================================

st.set_page_config(page_title="Multi-Market Equity Analyzer", layout="wide", page_icon="🌍")

# --- CSS Styling ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

    :root {
        --bg-color: #f5f6fa;
        --card-bg: #ffffff;
        --text-color: #16192b;
        --secondary-text: #667085;
        --border-color: #e6e8f0;
        --accent-color: #4338ca;
        --accent-soft: #6366f1;
        --success-color: #0f9d63;
        --danger-color: #d92d20;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
        color: var(--text-color);
    }

    [data-testid="stAppViewContainer"] {
        background: radial-gradient(circle at 15% 0%, #ffffff 0%, #f5f6fa 55%);
    }

    h1, h2, h3, h4, h5, h6 {
        font-weight: 700;
        letter-spacing: -0.01em;
    }

    [data-testid="stSidebar"] {
        background-color: var(--card-bg);
        border-right: 1px solid var(--border-color);
    }

    /* METRIC CARDS (native st.metric, restyled) */
    [data-testid="stMetric"] {
        position: relative;
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 16px 18px 12px 18px;
        overflow: hidden;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    [data-testid="stMetric"]::before {
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--accent-color), var(--accent-soft));
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 16px rgba(16, 24, 40, 0.08);
    }
    [data-testid="stMetricLabel"] {
        color: var(--secondary-text);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        color: var(--text-color);
    }

    /* TABS */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid var(--border-color);
    }
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 8px 8px 0 0;
        font-weight: 500;
        padding: 0 18px;
        color: var(--secondary-text);
    }
    .stTabs [aria-selected="true"] {
        background-color: #f0efff;
        color: var(--accent-color) !important;
        font-weight: 700;
        box-shadow: inset 0 -3px 0 var(--accent-color);
    }

    /* PRIMARY BUTTON */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--accent-color), var(--accent-soft));
        border: none;
        font-weight: 600;
        letter-spacing: 0.02em;
        box-shadow: 0 4px 10px rgba(67, 56, 202, 0.25);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(67, 56, 202, 0.32);
    }

    .dataframe {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 12px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
st.sidebar.title("🌍 Multi-Market Equity Analyzer")
st.sidebar.caption("US · Vietnam · Germany")
st.sidebar.markdown("---")
st.sidebar.header("Configuration")
market = st.sidebar.selectbox("Select Market", ["US", "VN", "DE"], format_func=lambda x: f"{x} Market")

if market == "US":
    default_ticker = "AAPL"
    default_wacc = 9.0
    default_peers = "MSFT, GOOGL"
elif market == "VN":
    default_ticker = "VNM"
    default_wacc = 13.0  # Emerging markets higher risk
    default_peers = "MSN, HPG"
else:  # DE
    default_ticker = "BMW"
    default_wacc = 8.5
    default_peers = "VOW3, MBG"

ticker_input = st.sidebar.text_input("Ticker Symbol", value=default_ticker)
st.sidebar.markdown("---")
st.sidebar.header("DCF Assumptions")
wacc_input = st.sidebar.slider("WACC (%)", 5.0, 20.0, default_wacc, 0.5) / 100
growth_input = st.sidebar.slider("Growth Rate (Next 5Y)", 0.0, 30.0, 10.0, 0.5) / 100
term_growth = st.sidebar.slider("Terminal Growth", 0.0, 5.0, 2.5, 0.1) / 100

analyze_clicked = st.sidebar.button("🚀 Analyze Stock", type="primary", use_container_width=True)

# --- SESSION STATE (fixes dashboard disappearing on any other widget click) ---
# The original version kept everything inside `if st.sidebar.button(...)`, and a
# Streamlit button only evaluates True on the run right after it's clicked. Any
# later rerun (typing in the peer box, clicking "Compare Peers", switching tabs)
# made that condition False again and wiped the whole dashboard. Session state
# keeps the last analyzed ticker "sticky" until you deliberately re-run it.
if "analyzer_state" not in st.session_state:
    st.session_state.analyzer_state = None

if analyze_clicked:
    st.session_state.analyzer_state = {
        "ticker": ticker_input,
        "market": market,
        "wacc": wacc_input,
        "growth": growth_input,
        "term_growth": term_growth,
    }

if st.session_state.analyzer_state:
    s = st.session_state.analyzer_state
    with st.spinner(f"Fetching data for {s['ticker']} in {s['market']}..."):
        engine = FinanceEngine(s['ticker'], s['market'])

    if not engine.valid:
        st.error(f"Could not load data for **{engine.full_ticker}**. Please check the symbol.")
    else:
        # --- Main Dashboard ---
        kpi = engine.get_kpi_summary()
        currency = kpi['Currency']

        # Header
        col1, col2 = st.columns([3, 1])
        with col1:
            st.title(f"{engine.stock.info.get('longName', engine.full_ticker)}")
            st.caption(f"Exchange: {engine.stock.info.get('exchange', 'N/A')} | Sector: {engine.stock.info.get('sector', 'N/A')}")
        with col2:
            st.metric("Current Price", f"{kpi['Price']:,.2f} {currency}")

        # Tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 Financials", "💰 Valuation", "👥 Peers"])

        # --- TAB 1: OVERVIEW ---
        with tab1:
            row1_1, row1_2, row1_3, row1_4 = st.columns(4)
            row1_1.metric("Market Cap", f"{kpi['Market Cap']/1e9:,.2f}B {currency}")
            row1_2.metric("Ent. Value", f"{kpi['Enterprise Value']/1e9:,.2f}B {currency}")
            row1_3.metric("52W High", f"{kpi['52W High']:,.2f}")
            row1_4.metric("Beta", f"{kpi['Beta']:,.2f}")

            st.markdown("### Risk & Efficiency")
            risk = engine.get_risk_metrics()
            growth = engine.get_growth_quality()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Volatility (1Y)", f"{risk['Volatility (1Y)']:,.1f}%")
            c2.metric("Max Drawdown", f"{risk['Max Drawdown']:,.1f}%")
            c3.metric("Current Ratio", f"{risk['Current Ratio']:,.2f}x")
            c4.metric("Net Debt/EBITDA", f"{risk['Net Debt/EBITDA']:,.2f}x")

            # Chart
            if not engine.hist_data.empty:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=engine.hist_data.index,
                                open=engine.hist_data['Open'],
                                high=engine.hist_data['High'],
                                low=engine.hist_data['Low'],
                                close=engine.hist_data['Close'], name='Price'))
                fig.update_layout(height=400, title="Price History (2Y)", xaxis_rangeslider_visible=False,
                                   template="plotly_white", margin=dict(t=50, b=10))
                st.plotly_chart(fig, use_container_width=True)

        # --- TAB 2: FINANCIALS ---
        with tab2:
            st.subheader("Efficiency Trend (ROIC)")
            eff_df = engine.get_efficiency_metrics()
            if not eff_df.empty:
                st.line_chart(eff_df['ROIC (%)'])
            else:
                st.warning("Not enough data for ROIC calculation.")

            st.subheader("Recent Income Statement")
            st.dataframe(engine.income_stmt.tail(3).style.format("{:,.0f}"), use_container_width=True)

        # --- TAB 3: VALUATION (DCF) ---
        with tab3:
            dcf = engine.run_dcf(s['growth'], s['term_growth'], s['wacc'])
            
            if "Error" in dcf:
                st.error(dcf["Error"])
            else:
                col_v1, col_v2 = st.columns(2)
                
                with col_v1:
                    st.markdown("#### DCF Results")
                    st.metric("Fair Value", f"{dcf['Fair Value']:,.2f} {currency}")
                    
                    upside = dcf['Upside']
                    color = "var(--success-color)" if upside > 0 else "var(--danger-color)"
                    st.markdown(f"Upside/Downside: <span style='color:{color}; font-weight:bold'>{upside:+,.2f}%</span>", unsafe_allow_html=True)
                    
                    st.info(f"Assumptions: WACC={s['wacc']*100:,.1f}%, Growth={s['growth']*100:,.1f}%, Term G={s['term_growth']*100:,.1f}%")
                    st.caption("Assumptions reflect the sliders' values at the moment you last clicked **Analyze Stock**. Move a slider and click it again to recalculate.")

                with col_v2:
                    st.markdown("#### Value Composition")
                    breakdown = dcf.get('EV breakdown', {})
                    if breakdown:
                        b_df = pd.DataFrame(list(breakdown.items()), columns=["Component", "Value"])
                        st.bar_chart(b_df.set_index("Component"))

        # --- TAB 4: PEERS ---
        with tab4:
            st.subheader("Relative Valuation")
            peers_input = st.text_input("Comparables (comma separated)", default_peers, key="peers_input")
            peer_list = [p.strip() for p in peers_input.split(",") if p.strip()]
            
            if st.button("Compare Peers"):
                with st.spinner("Fetching peer data..."):
                    peer_df = engine.get_peer_comparison(peer_list)
                    st.session_state["peer_df"] = peer_df

            peer_df = st.session_state.get("peer_df")
            if peer_df is not None and not peer_df.empty:
                def highlight_target(row):
                    is_target = row.name == engine.full_ticker.replace(".VN", "").replace(".DE", "")
                    style = 'background-color: #f0efff; color: #322a8c; font-weight: 600;' if is_target else ''
                    return [style] * len(row)

                def fmt_ratio(x): return f"{x:,.2f}" if isinstance(x, (int, float)) else "N/A"
                def fmt_pct(x): return f"{x:,.2f}%" if isinstance(x, (int, float)) else "N/A"

                col_formats = {
                    "Price": fmt_ratio, "P/E": fmt_ratio, "Fwd P/E": fmt_ratio, "P/B": fmt_ratio,
                    "ROE (%)": fmt_pct, "Margins (%)": fmt_pct
                }
                st.dataframe(
                    peer_df.style.apply(highlight_target, axis=1).format(col_formats),
                    use_container_width=True
                )
                
                # Visual comparison
                st.subheader("P/E Ratio Comparison")
                st.bar_chart(peer_df['P/E'])
            elif peer_df is not None:
                st.warning("Could not fetch peer data.")
else:
    st.info("Select a market, enter a ticker, and click **Analyze Stock** in the sidebar to begin.")
