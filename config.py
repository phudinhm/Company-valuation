# ==========================================
# APP CONFIGURATION & MASTER DATA
# Markets: United States (US) & Germany (DE)
# ==========================================

# 1. Page Configuration
PAGE_CONFIG = {
    "page_title": "Global Investment Terminal Pro",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
    "page_icon": "🌍"
}

# 2. Market Specific Settings
# Used to handle suffixes, currencies, and benchmark indices dynamically
MARKET_CONFIG = {
    "US": {
        "name": "United States",
        "suffix": "",       # US tickers usually have no suffix on Yahoo Finance
        "currency": "$",
        "index": "^GSPC",   # S&P 500
        "timezone": "US/Eastern"
    },
    "DE": {
        "name": "Germany",
        "suffix": ".DE",    # Xetra suffix for Yahoo Finance
        "currency": "€",
        "index": "^GDAXI",  # DAX Performance Index
        "timezone": "Europe/Berlin"
    }
}

# 3. Robust Industry Map (US & German Peers)
# Blends top US stocks with major DAX/MDAX players
INDUSTRY_PEERS = {
    "Technology & Software": [
        "AAPL", "MSFT", "NVDA", "ORCL", "ADBE", "CRM",  # US
        "SAP.DE", "IFX.DE", "NEM.DE"                    # DE (SAP, Infineon, Nemetschek)
    ],
    "Automotive & Mobility": [
        "TSLA", "F", "GM",                              # US
        "VOW3.DE", "BMW.DE", "MBG.DE", "PAH3.DE"        # DE (VW, BMW, Mercedes, Porsche)
    ],
    "Financial Services": [
        "JPM", "BAC", "GS", "MS", "V",                  # US
        "ALV.DE", "DBK.DE", "CBK.DE", "MUV2.DE"         # DE (Allianz, Deutsche Bank, Commerzbank, Munich Re)
    ],
    "Industrials & Engineering": [
        "CAT", "GE", "HON", "DE",                       # US
        "SIE.DE", "AIR.DE", "MTX.DE", "RHM.DE"          # DE (Siemens, Airbus, MTU, Rheinmetall)
    ],
    "Chemicals & Materials": [
        "DOW", "DD", "LIN",                             # US (Linde is technically dual but trades nicely as LIN)
        "BAS.DE", "BAYN.DE", "COV.DE", "HEI.DE"         # DE (BASF, Bayer, Covestro, Heidelberg Mat)
    ],
    "Healthcare & Pharma": [
        "JNJ", "PFE", "LLY", "ABBV", "MRK",             # US
        "SHL.DE", "MRT.DE", "FME.DE"                    # DE (Siemens Healthineers, Merck KGaA)
    ],
    "Consumer & Sportswear": [
        "NKE", "MCD", "SBUX", "AMZN",                   # US
        "ADS.DE", "PUM.DE", "ZAL.DE"                    # DE (Adidas, Puma, Zalando)
    ],
    "Telecommunications": [
        "VZ", "T", "TMUS",                              # US
        "DTE.DE", "O2D.DE"                              # DE (Deutsche Telekom, Telefonica DE)
    ],
    "Energy & Utilities": [
        "XOM", "CVX", "NEE",                            # US
        "EOAN.DE", "RWE.DE"                             # DE (E.ON, RWE)
    ]
}

# 4. Quick Select Examples (Dual Market)
SECTOR_EXAMPLES = {
    "🇺🇸 Tech Giant": "AAPL",
    "🇩🇪 Tech Giant": "SAP.DE",
    "🇺🇸 Auto Leader": "TSLA",
    "🇩🇪 Auto Leader": "VOW3.DE",
    "🇺🇸 Bank": "JPM",
    "🇩🇪 Insurer": "ALV.DE",
    "🇺🇸 Pharma": "PFE",
    "🇩🇪 Chemicals": "BAS.DE"
}

# 5. CSS Styling
STYLES = """
<style>
    /* Global Background */
    .main { background-color: #f8f9fa; }
    
    /* KPI Cards */
    .kpi-box {
        background-color: white; border-radius: 8px; padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); text-align: center;
        border-top: 4px solid #3498db; transition: transform 0.2s;
    }
    .kpi-box:hover { transform: translateY(-3px); box-shadow: 0 6px 12px rgba(0,0,0,0.1); }
    .kpi-val { font-size: 26px; font-weight: 700; color: #2c3e50; }
    .kpi-lbl { font-size: 12px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
    
    /* Market Flags/Badges */
    .market-badge-us { color: #e74c3c; font-weight: bold; border: 1px solid #e74c3c; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
    .market-badge-de { color: #f1c40f; font-weight: bold; border: 1px solid #f1c40f; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; background-color: #333; }

    /* Insight Boxes */
    .interpret-box {
        background-color: #e8f4f8; border-left: 5px solid #3498db;
        padding: 15px; border-radius: 4px; margin-top: 15px; font-size: 14px; color: #2c3e50;
    }
    .insight-box {
        background-color: #eafaf1; border-left: 5px solid #2ecc71;
        padding: 15px; border-radius: 4px; margin-top: 15px; font-size: 14px; color: #27ae60;
    }
    .warning-box {
        background-color: #fce8e6; border-left: 5px solid #e74c3c;
        padding: 15px; border-radius: 4px; margin-top: 15px; font-size: 14px; color: #c0392b;
    }
    
    /* Verdict Card */
    .verdict-box {
        padding: 30px; border-radius: 10px; color: white; text-align: center;
        background: linear-gradient(135deg, #2c3e50, #4ca1af);
        box-shadow: 0 4px 10px rgba(0,0,0,0.1); margin-top: 20px;
    }
    
    /* Footer */
    .footer {
        position: fixed; left: 0; bottom: 0; width: 100%;
        background-color: #f1f1f1; color: #7f8c8d; text-align: center;
        padding: 10px; font-size: 11px; border-top: 1px solid #ddd;
        z-index: 100;
    }
    
    /* Table Fixes */
    div[data-testid="stDataFrame"] { width: 100%; }
</style>
"""