import yfinance as yf
import pandas as pd
import numpy as np

def get_financial_data(ticker):
    """Lấy dữ liệu tài chính với cơ chế phòng ngừa lỗi (Error Handling)"""
    stock = yf.Ticker(ticker)
    
    try:
        info = stock.info
        # Nếu không lấy được info cơ bản, trả về None
        if not info or 'currentPrice' not in info:
            return None
            
        balance_sheet = stock.balance_sheet
        income_stmt = stock.financials
        cashflow = stock.cashflow
    except:
        return None

    # --- 1. Xử lý các biến số đầu vào (Inputs) ---
    
    # Beta: Nếu thiếu thì giả định bằng 1 (biến động bằng thị trường)
    beta = info.get('beta')
    if beta is None: beta = 1.0
        
    market_cap = info.get('marketCap', 0)
    
    # Cost of Debt (Rd)
    # Tìm chi phí lãi vay (Interest Expense)
    interest_expense = 0
    if 'Interest Expense' in income_stmt.index:
        interest_expense = abs(income_stmt.loc['Interest Expense'].iloc[0])
    
    # Tìm tổng nợ (Total Debt)
    total_debt = 0
    if 'Total Debt' in balance_sheet.index:
        total_debt = balance_sheet.loc['Total Debt'].iloc[0]
    elif 'Long Term Debt' in balance_sheet.index: # Fallback nếu không có dòng Total Debt
        total_debt = balance_sheet.loc['Long Term Debt'].iloc[0]
            
    # Tính Rd: Nếu không có nợ, mặc định lãi vay 5%
    cost_of_debt = interest_expense / total_debt if total_debt > 0 else 0.05

    # Tax Rate
    # Tính thuế trung bình thực tế
    tax_rate = 0.21 # Mặc định thuế Mỹ
    if 'Tax Provision' in income_stmt.index and 'Pretax Income' in income_stmt.index:
        pre_tax = income_stmt.loc['Pretax Income'].iloc[0]
        tax_prov = income_stmt.loc['Tax Provision'].iloc[0]
        if pre_tax != 0:
            tax_rate = tax_prov / pre_tax
            # Giới hạn tax rate trong khoảng hợp lý (0% - 40%) để tránh số liệu ảo
            tax_rate = max(0.0, min(0.40, tax_rate))

    # Cost of Equity (Re) - CAPM
    # Lấy Risk Free Rate (US 10Y)
    risk_free_rate = 0.042 # Mặc định 4.2% để tránh lỗi kết nối mạng
    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="1d")
        if not hist.empty:
            risk_free_rate = hist['Close'].iloc[-1] / 100
    except:
        pass

    market_return = 0.10 
    cost_of_equity = risk_free_rate + beta * (market_return - risk_free_rate)

    # --- 2. Tính WACC ---
    total_equity = market_cap
    total_val = total_equity + total_debt
    
    if total_val > 0:
        w_e = total_equity / total_val
        w_d = total_debt / total_val
        wacc = (w_e * cost_of_equity) + (w_d * cost_of_debt * (1 - tax_rate))
    else:
        wacc = 0.10 # Fallback 10%

    # --- 3. Lấy Free Cash Flow (FCF) ---
    last_fcf = 0
    # Ưu tiên lấy dòng có sẵn
    if not cashflow.empty and 'Free Cash Flow' in cashflow.index:
        last_fcf = cashflow.loc['Free Cash Flow'].iloc[0]
    # Nếu không có, tự tính: Operating Cash Flow - CapEx
    elif not cashflow.empty and 'Operating Cash Flow' in cashflow.index and 'Capital Expenditure' in cashflow.index:
        ocf = cashflow.loc['Operating Cash Flow'].iloc[0]
        capex = cashflow.loc['Capital Expenditure'].iloc[0]
        last_fcf = ocf + capex # Capex thường là số âm

    # Xử lý nếu FCF bị Nan hoặc 0 (Dùng Net Income thay thế tạm thời)
    if pd.isna(last_fcf) or last_fcf == 0:
        if 'Net Income' in income_stmt.index:
            last_fcf = income_stmt.loc['Net Income'].iloc[0]

    return {
        "wacc": wacc,
        "total_debt": total_debt,
        "cash_and_equivalents": balance_sheet.loc['Cash And Cash Equivalents'].iloc[0] if not balance_sheet.empty and 'Cash And Cash Equivalents' in balance_sheet.index else 0,
        "shares_outstanding": info.get('sharesOutstanding', 1),
        "last_fcf": last_fcf,
        "current_price": info.get('currentPrice'),
        "currency": info.get('currency', 'USD'),
        "info": info
    }

def calculate_dcf(ticker, growth_rate, terminal_growth_rate, forecast_years=5):
    """Hàm chạy mô hình DCF"""
    data = get_financial_data(ticker)
    
    if data is None:
        return "Error: Không tìm thấy dữ liệu hoặc lỗi kết nối."
        
    wacc = data['wacc']
    last_fcf = data['last_fcf']

    # Kiểm tra FCF âm (Công ty đang lỗ dòng tiền)
    is_fcf_negative = False
    if last_fcf < 0:
        is_fcf_negative = True
        # Nếu âm, chúng ta không thể định giá DCF chính xác, cảnh báo người dùng
        # Để demo chạy được, ta sẽ dùng tuyệt đối nhưng đây chỉ là giả định
        # last_fcf = abs(last_fcf) 

    # Logic dự phóng
    future_cash_flows = []
    for i in range(1, forecast_years + 1):
        fcf = last_fcf * ((1 + growth_rate) ** i)
        future_cash_flows.append(fcf)

    # Terminal Value
    last_projected_fcf = future_cash_flows[-1]
    
    if wacc <= terminal_growth_rate:
        wacc = terminal_growth_rate + 0.02 # Điều chỉnh WACC để tránh lỗi chia cho 0
        
    terminal_value = (last_projected_fcf * (1 + terminal_growth_rate)) / (wacc - terminal_growth_rate)

    # Discounting
    pv_cash_flows = 0
    for i, fcf in enumerate(future_cash_flows):
        pv_cash_flows += fcf / ((1 + wacc) ** (i + 1))
        
    pv_terminal_value = terminal_value / ((1 + wacc) ** forecast_years)

    enterprise_value = pv_cash_flows + pv_terminal_value
    equity_value = enterprise_value - data['total_debt'] + data['cash_and_equivalents']
    
    shares = data['shares_outstanding']
    if shares is None or shares == 0: shares = 1
        
    implied_price = equity_value / shares

    return {
        "Ticker": ticker,
        "Current Price": data['current_price'],
        "Implied Price": round(implied_price, 2),
        "Upside": round(((implied_price / data['current_price']) - 1) * 100, 2),
        "WACC": round(wacc * 100, 2),
        "Currency": data['currency'],
        "Enterprise Value": enterprise_value,
        "Equity Value": equity_value,
        "Is FCF Negative": is_fcf_negative,
        "Info": data['info'] # Trả về info để dùng cho Peer Review
    }