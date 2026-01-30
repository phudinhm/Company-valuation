import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import zscore
from scipy.optimize import newton
import plotly.graph_objects as go

# ==========================================
# CORE ENGINE (UPDATED FOR MULTI-MARKET)
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
            self.suffix = ".DE" # Defaults to Xetra
            self.full_ticker = self.raw_ticker if self.raw_ticker.endswith(".DE") else f"{self.raw_ticker}.DE"
        else: # US or Direct
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
        cagr_3y = ((rev.iloc[-1] / rev.iloc[-3])**(1/3) - 1) * 100 if years >= 3 else 0
        cagr_5y = ((rev.iloc[-1] / rev.iloc[0])**(1/years) - 1) * 100 if years >= 5 else 0
        
        rev_growth = rev.pct_change()
        volatility = rev_growth.std() * 100
        
        try:
            fcf = self.cash_flow['Free Cash Flow'].iloc[-1]
        except:
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
        tax_rate = 0.21 # Simplified global assumption
        
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
        last_is = self.income_stmt.iloc[-1] if not self.income_stmt.empty else {}
        
        curr_assets = last_bs.get('Total Current Assets', 0)
        curr_liab = last_bs.get('Total Current Liabilities', 1)
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
                last_fcf = ocf + capex # Capex is usually negative
            
            # Simple 2-Stage DCF
            future_fcf = [last_fcf * ((1 + g_rate) ** i) for i in range(1, 6)]
            
            # Terminal Value (Gordon Growth)
            tv = (future_fcf[-1] * (1 + t_rate)) / (wacc - t_rate)
            
            # Discounting
            pv_fcf = sum([f / ((1+wacc)**(i+1)) for i, f in enumerate(future_fcf)])
            pv_tv = tv / ((1+wacc)**5)
            
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
            except: continue
            
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.set_index("Ticker")
        return df

# ==========================================
# STREAMLIT UI
# ==========================================

st.set_page_config(page_title="Multi-Market Equity Analyzer", layout="wide", page_icon="📈")

# --- CSS Styling ---
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #4B4B4B;
    }
    .metric-label { font-size: 0.8rem; color: #555; }
    .metric-value { font-size: 1.5rem; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: white; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }
    .stTabs [aria-selected="true"] { background-color: #e6f3ff; color: #0066cc; }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
st.sidebar.title("Configuration")
market = st.sidebar.selectbox("Select Market", ["US", "VN", "DE"], format_func=lambda x: f"{x} Market")

if market == "US":
    default_ticker = "AAPL"
    default_wacc = 9.0
    default_peers = "MSFT, GOOGL"
elif market == "VN":
    default_ticker = "VNM"
    default_wacc = 13.0 # Emerging markets higher risk
    default_peers = "MSN, HPG"
else: # DE
    default_ticker = "BMW"
    default_wacc = 8.5
    default_peers = "VOW3, MBG"

ticker_input = st.sidebar.text_input("Ticker Symbol", value=default_ticker)
st.sidebar.markdown("---")
st.sidebar.header("DCF Assumptions")
wacc_input = st.sidebar.slider("WACC (%)", 5.0, 20.0, default_wacc, 0.5) / 100
growth_input = st.sidebar.slider("Growth Rate (Next 5Y)", 0.0, 30.0, 10.0, 0.5) / 100
term_growth = st.sidebar.slider("Terminal Growth", 0.0, 5.0, 2.5, 0.1) / 100

if st.sidebar.button("Analyze Stock"):
    with st.spinner(f"Fetching data for {ticker_input} in {market}..."):
        engine = FinanceEngine(ticker_input, market)

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
            row1_4.metric("Beta", f"{kpi['Beta']:.2f}")

            st.markdown("### Risk & Efficiency")
            risk = engine.get_risk_metrics()
            growth = engine.get_growth_quality()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Volatility (1Y)", f"{risk['Volatility (1Y)']:.1f}%")
            c2.metric("Max Drawdown", f"{risk['Max Drawdown']:.1f}%")
            c3.metric("Net Debt/EBITDA", f"{risk['Net Debt/EBITDA']:.2f}x")
            c4.metric("FCF Conversion", f"{growth.get('FCF/Net Income', 0)*100:.0f}%")

            # Chart
            if not engine.hist_data.empty:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=engine.hist_data.index,
                                open=engine.hist_data['Open'],
                                high=engine.hist_data['High'],
                                low=engine.hist_data['Low'],
                                close=engine.hist_data['Close'], name='Price'))
                fig.update_layout(height=400, title="Price History (2Y)", xaxis_rangeslider_visible=False)
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
            st.dataframe(engine.income_stmt.tail(3).style.format("{:,.0f}"))

        # --- TAB 3: VALUATION (DCF) ---
        with tab3:
            dcf = engine.run_dcf(growth_input, term_growth, wacc_input)
            
            if "Error" in dcf:
                st.error(dcf["Error"])
            else:
                col_v1, col_v2 = st.columns(2)
                
                with col_v1:
                    st.markdown("#### DCF Results")
                    st.metric("Fair Value", f"{dcf['Fair Value']:,.2f} {currency}")
                    
                    upside = dcf['Upside']
                    color = "green" if upside > 0 else "red"
                    st.markdown(f"Upside/Downside: <span style='color:{color}; font-weight:bold'>{upside:.2f}%</span>", unsafe_allow_html=True)
                    
                    st.info(f"Assumptions: WACC={wacc_input*100:.1f}%, Growth={growth_input*100:.1f}%, Term G={term_growth*100:.1f}%")

                with col_v2:
                    st.markdown("#### Value Composition")
                    breakdown = dcf.get('EV breakdown', {})
                    if breakdown:
                        b_df = pd.DataFrame(list(breakdown.items()), columns=["Component", "Value"])
                        st.bar_chart(b_df.set_index("Component"))

        # --- TAB 4: PEERS ---
        with tab4:
            st.subheader("Relative Valuation")
            peers_input = st.text_input("Comparables (comma separated)", default_peers)
            peer_list = [p.strip() for p in peers_input.split(",")]
            
            if st.button("Compare Peers"):
                with st.spinner("Fetching peer data..."):
                    peer_df = engine.get_peer_comparison(peer_list)
                    
                    if not peer_df.empty:
                        # Highlight the main ticker
                        st.dataframe(peer_df.style.highlight_max(axis=0, color='#f0f2f6'), use_container_width=True)
                        
                        # Visual comparison
                        st.subheader("P/E Ratio Comparison")
                        st.bar_chart(peer_df['P/E'])
                    else:
                        st.warning("Could not fetch peer data.")
else:
    st.info("Select a market and enter a ticker in the sidebar to begin.")