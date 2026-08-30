# Investment Terminal

A Streamlit workbench for fundamental equity research: pull a company's reported
financials, value it, compare it with live-matched peers, and export the result as
a self-contained report.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Modules

| # | Module | Answers |
|---|--------|---------|
| 00 | Guide & Method | How each module works, and the assumptions behind every calculated figure. |
| 01 | Executive Dashboard | Composite screen, headline metrics, margin and return decomposition, dividends, earnings-quality flags. |
| 02 | Technical Analysis | Trend, momentum, volatility — and a forward projection from three independent methods. |
| 03 | Financial Statements | Reported line items on an Annual, Quarterly or TTM basis, common-size figures beside live industry medians, a line-by-line explanation of every reported item, and a link to the market's primary filing source. |
| 04 | Cash Flow Quality | Whether reported profit turns into cash, and what it costs to keep the business running. |
| 05 | Capital Allocation | ROIC against WACC, incremental return on new capital, and a waterfall of where the cash actually went. |
| 06 | Solvency & Debt | Maturity profile, leverage, interest cover, and a refinancing stress test at higher rates. |
| 07 | Dilution & Owner Earnings | Share-count creep, stock compensation as a share of revenue and cash flow, and free cash flow per share after it. |
| 08 | Intrinsic Valuation | Three-phase DCF, reverse DCF, scenarios, sensitivity grid, cross-method summary. |
| 09 | Peer Comparables | Percentile ranking, growth-versus-valuation regression, peer-implied price ranges. |
| 10 | Compare Companies | Two or more companies side by side: rebased performance, comparison matrix, profile scores, return correlation. |
| 11 | Risk & Scenarios | Volatility, drawdown, value at risk, expected shortfall, Monte Carlo simulation. |
| 12 | Investment Simulator | What a lump sum, or a monthly contribution, invested on a past date would be worth now. |
| 13 | Portfolio | Allocation against policy targets, drift, concentration guardrails, time-weighted and money-weighted return, benchmark comparison. |
| 14 | Price & Capital Dynamics | Price against market cap, an automatically assembled wall of worry, and the enterprise value bridge. |
| 15 | Market Leaders | Cross-company ranking by size and revenue, with three-year trajectories. |

## Coverage

Any listed company on any market yfinance can reach. Nothing about the company
universe is bundled with the app:

* **Search** resolves a name or partial symbol through four independent routes —
  `yf.Search`, `yf.Lookup`, Yahoo's raw search endpoint, and, when all of those
  are throttled, by probing the query as a symbol across every market suffix in
  parallel. One rate-limited endpoint cannot make a real company look
  nonexistent.
* **Markets** are selectable for every Yahoo exchange suffix, from Vietnam and
  Vietnam's HOSE through to Brazil, Saudi Arabia and the Nordics.
* **Quotes degrade gracefully.** When Yahoo's quote endpoint is rate-limited —
  routine on shared cloud hosting — the headline metrics are recomputed from the
  company's own filings, and the page says which figures were computed rather
  than quoted.
* **Two independent backup providers**, neither needing an API key, so they work
  on any deployment without configuration:
  * **Stooq** — daily price history for most developed markets, used whenever
    Yahoo's price endpoint returns nothing.
  * **SEC EDGAR XBRL company facts** — the filings themselves, from the
    regulator, used whenever Yahoo returns no financial statements for a US
    filer. Income statement, balance sheet and cash flow are rebuilt from the
    reported XBRL concepts into the same shape the rest of the app expects.

  Whichever source answered is named in the provenance panel at the foot of
  every view. With Yahoo entirely unavailable, the executive dashboard still
  renders 20 of its 29 metric tiles from these two.
* **Primary sources are linked per market**, with that market's own reporting
  rhythm: SEC EDGAR for the US, HOSE and Vietstock for Vietnam, EDINET for
  Japan, HKEXnews for Hong Kong, and so on.

## How it is built

* **`app.py`** is the whole application, organised in nine numbered sections:
  design system, formatting, data layer, analytics, UI components, reporting,
  navigation, modules, export.
* **All network access is confined to the data layer** and cached. Quotes and
  news refresh every 15 minutes, statements and FX every hour. Moving a slider
  or switching theme never refetches anything.
* **Fan-out fetches run in parallel.** Peer tables, leaderboards and sector
  filters use a thread pool rather than a serial loop.
* **Every chart is rendered through one `figure()` helper**, which requires a
  numbered caption plus a "what it shows / how to read it / why it matters"
  explanation, and offers the underlying data as CSV.
* **Any view exports** to a standalone HTML report with its charts still
  interactive; statements export as CSV.
* **Nothing is stored.** The portfolio table lives in the browser session only —
  it is never written to disk or sent anywhere.

## Data and limitations

Everything comes from Yahoo Finance via `yfinance`. Coverage is uneven outside
the United States, statements are occasionally restated or misclassified, and
some fields are missing entirely for smaller listings. The app degrades to an
explicit "not available" rather than substituting zero, and states the FX rate
applied to every converted figure. Verify against primary filings before
anything consequential rests on a number here.

Educational research tool — not investment advice.

*Legacy modules `config.py`, `finance_engine.py`, `valuation.py`, `utils.py` and
`data_loader.py` predate the current single-file application and are not imported
by it.*
