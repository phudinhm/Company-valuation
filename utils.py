import yfinance as yf
import pandas as pd
import numpy as np

def get_data(ticker):
    """Lấy toàn bộ dữ liệu cần thiết một lần duy nhất"""
    stock = yf.Ticker(ticker)
    
    try:
        # Lấy dữ liệu cơ bản
        info = stock.info
        if not info or 'currentPrice' not in info: return None
        
        # Lấy Báo cáo tài chính (Hàng năm)
        income_stmt = stock.financials.T  # Transpose để dòng là năm
        balance_sheet = stock.balance_sheet.T
        cash_flow = stock.cashflow.T
        
        # Sắp xếp theo thời gian (cũ -> mới)
        income_stmt = income_stmt.sort_index()
        balance_sheet = balance_sheet.sort_index()
        cash_flow = cash_flow.sort_index()
        
        return {
            "stock": stock,
            "info": info,
            "income_stmt": income_stmt,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow
        }
    except Exception as e:
        print(e)
        return None

def calculate_metrics(data):
    """Tính toán các chỉ số tài chính (Growth, Ratios)"""
    is_df = data['income_stmt']
    bs_df = data['balance_sheet']
    cf_df = data['cash_flow']
    
    metrics = pd.DataFrame(index=is_df.index)
    
    # 1. Growth (YoY)
    metrics['Revenue Growth'] = is_df['Total Revenue'].pct_change() * 100
    if 'Net Income' in is_df.columns:
        metrics['Net Income Growth'] = is_df['Net Income'].pct_change() * 100
    
    # 2. Profitability
    metrics['Gross Margin'] = (is_df['Gross Profit'] / is_df['Total Revenue']) * 100
    # EBITDA (Giả định đơn giản: EBIT + Depreciation)
    if 'EBIT' in is_df.columns: 
        ebit = is_df['EBIT']
    elif 'Operating Income' in is_df.columns:
        ebit = is_df['Operating Income']
    else:
        ebit = is_df['Total Revenue'] * 0.1 # Fallback
        
    metrics['Operating Margin'] = (ebit / is_df['Total Revenue']) * 100
    
    # 3. Efficiency (ROE)
    # ROE = Net Income / Total Equity
    if 'Stockholders Equity' in bs_df.columns and 'Net Income' in is_df.columns:
        metrics['ROE'] = (is_df['Net Income'] / bs_df['Stockholders Equity']) * 100
        
    # 4. Financial Health
    # Current Ratio
    if 'Total Current Assets' in bs_df.columns and 'Total Current Liabilities' in bs_df.columns:
        metrics['Current Ratio'] = bs_df['Total Current Assets'] / bs_df['Total Current Liabilities']
        
    return metrics.sort_index(ascending=False) # Đảo ngược để năm mới nhất lên đầu

def get_dcf_valuation(data, growth_rate, terminal_growth, wacc, forecast_years=5):
    """Mô hình DCF tính toán Intrinsic Value"""
    info = data['info']
    cf_df = data['cash_flow']
    bs_df = data['balance_sheet']
    
    # Lấy FCF gần nhất
    try:
        last_fcf = cf_df['Free Cash Flow'].iloc[-1]
    except:
        # Fallback: Operating CF - CapEx
        ocf = cf_df['Operating Cash Flow'].iloc[-1]
        capex = abs(cf_df['Capital Expenditure'].iloc[-1])
        last_fcf = ocf - capex

    future_fcf = []
    discount_factors = []
    
    # Projection
    for i in range(1, forecast_years + 1):
        fcf = last_fcf * ((1 + growth_rate) ** i)
        future_fcf.append(fcf)
        discount_factors.append((1 + wacc) ** i)
        
    # Terminal Value
    terminal_val = (future_fcf[-1] * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv_terminal = terminal_val / ((1 + wacc) ** forecast_years)
    
    pv_fcf = sum([f / d for f, d in zip(future_fcf, discount_factors)])
    
    enterprise_value = pv_fcf + pv_terminal
    
    # Equity Value = EV - Debt + Cash
    total_debt = info.get('totalDebt', 0)
    cash = info.get('totalCash', 0)
    equity_value = enterprise_value - total_debt + cash
    
    shares = info.get('sharesOutstanding', 1)
    fair_value = equity_value / shares
    
    return {
        "Fair Value": fair_value,
        "Enterprise Value": enterprise_value,
        "Equity Value": equity_value,
        "Upside": (fair_value / info['currentPrice'] - 1) * 100
    }

def sensitivity_analysis(data, base_growth, base_wacc):
    """Tạo bảng độ nhạy (Sensitivity Matrix)"""
    growth_range = [base_growth - 0.02, base_growth - 0.01, base_growth, base_growth + 0.01, base_growth + 0.02]
    wacc_range = [base_wacc - 0.02, base_wacc - 0.01, base_wacc, base_wacc + 0.01, base_wacc + 0.02]
    
    matrix = pd.DataFrame(index=[f"{w:.1%}" for w in wacc_range], columns=[f"{g:.1%}" for g in growth_range])
    
    for w in wacc_range:
        row = []
        for g in growth_range:
            res = get_dcf_valuation(data, g, 0.025, w) # Terminal fix 2.5%
            row.append(res['Fair Value'])
        matrix.loc[f"{w:.1%}"] = row
        
    return matrix