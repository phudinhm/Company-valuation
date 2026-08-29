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
| 02 | Technical Analysis | Trend, momentum and volatility from price action. |
| 03 | Financial Statements | Reported line items on an Annual, Quarterly or TTM basis, with common-size figures beside live industry medians and a line-by-line explanation of what every reported item means. |
| 04 | Cash Flow Quality | Whether reported profit turns into cash, and what it costs to keep the business running. |
| 05 | Intrinsic Valuation | Three-phase DCF, reverse DCF, scenarios, sensitivity grid, cross-method summary. |
| 06 | Peer Comparables | Percentile ranking, growth-versus-valuation regression, peer-implied price ranges. |
| 07 | Compare Companies | Two or more companies side by side: rebased performance, a comparison matrix, profile scores, return correlation. |
| 08 | Risk & Scenarios | Volatility, drawdown, value at risk, expected shortfall, Monte Carlo simulation. |
| 09 | Investment Simulator | What a lump sum, or a monthly contribution, invested on a past date would be worth now — against a benchmark and against every alternative start date. |
| 10 | Portfolio | Allocation against policy targets, drift and where new capital should go, concentration guardrails, time-weighted and money-weighted return, benchmark comparison, holdings on fundamentals. |
| 11 | Price & Capital Dynamics | Price against market capitalisation, news context, enterprise value bridge. |
| 12 | Market Leaders | Cross-company ranking by size and revenue, with three-year trajectories. |

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
