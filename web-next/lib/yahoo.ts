export const BROWSER_HEADERS: Record<string, string> = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  Accept: "*/*",
};

interface Session {
  cookie: string;
  crumb: string;
  expires: number;
}

let cachedSession: Session | null = null;
const SESSION_TTL_MS = 25 * 60 * 1000;

async function buildSession(): Promise<Session | null> {
  try {
    const cookieRes = await fetch("https://fc.yahoo.com", {
      headers: BROWSER_HEADERS,
      redirect: "manual",
    });
    const setCookie = cookieRes.headers.get("set-cookie");
    if (!setCookie) return null;
    const cookie = setCookie.split(";")[0];

    const crumbRes = await fetch(
      "https://query2.finance.yahoo.com/v1/test/getcrumb",
      {
        headers: { ...BROWSER_HEADERS, Cookie: cookie },
      }
    );
    if (!crumbRes.ok) return null;
    const crumb = (await crumbRes.text()).trim();
    if (!crumb || crumb.includes("<html")) return null;

    return { cookie, crumb, expires: Date.now() + SESSION_TTL_MS };
  } catch {
    return null;
  }
}

async function getSession(): Promise<Session | null> {
  if (cachedSession && cachedSession.expires > Date.now()) {
    return cachedSession;
  }
  const session = await buildSession();
  cachedSession = session;
  return session;
}

export async function yahooFetch(
  url: string,
  withCrumb = false
): Promise<Response | null> {
  try {
    if (withCrumb) {
      const session = await getSession();
      if (!session) {
        const res = await fetch(url, { headers: BROWSER_HEADERS });
        return res.ok ? res : null;
      }
      const sep = url.includes("?") ? "&" : "?";
      const finalUrl = `${url}${sep}crumb=${encodeURIComponent(session.crumb)}`;
      const res = await fetch(finalUrl, {
        headers: { ...BROWSER_HEADERS, Cookie: session.cookie },
      });
      if (res.ok) return res;
      return null;
    }
    const res = await fetch(url, { headers: BROWSER_HEADERS });
    return res.ok ? res : null;
  } catch {
    return null;
  }
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export const RANGE_TO_INTERVAL: Record<string, string> = {
  "5d": "15m",
  "1mo": "1d",
  "3mo": "1d",
  "6mo": "1d",
  "1y": "1d",
  "2y": "1d",
  "5y": "1wk",
  max: "1mo",
};

export async function fetchChart(
  symbol: string,
  range = "1y"
): Promise<{ candles: Candle[]; currency: string | null } | null> {
  const interval = RANGE_TO_INTERVAL[range] ?? "1d";
  const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
    symbol
  )}?range=${range}&interval=${interval}`;

  for (const withCrumb of [false, true]) {
    const res = await yahooFetch(url, withCrumb);
    if (!res) continue;
    try {
      const json = await res.json();
      const result = json?.chart?.result?.[0];
      if (!result) continue;
      const timestamps: number[] = result.timestamp ?? [];
      const quote = result.indicators?.quote?.[0] ?? {};
      const currency = result.meta?.currency ?? null;
      const candles: Candle[] = [];
      for (let i = 0; i < timestamps.length; i++) {
        const open = quote.open?.[i];
        const high = quote.high?.[i];
        const low = quote.low?.[i];
        const close = quote.close?.[i];
        if (
          open == null ||
          high == null ||
          low == null ||
          close == null
        )
          continue;
        candles.push({
          time: timestamps[i],
          open,
          high,
          low,
          close,
          volume: quote.volume?.[i] ?? 0,
        });
      }
      if (candles.length > 0) return { candles, currency };
    } catch {
      continue;
    }
  }
  return null;
}

export interface QuoteSummary {
  symbol: string;
  shortName: string | null;
  longName: string | null;
  currency: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  regularMarketPrice: number | null;
  previousClose: number | null;
  marketCap: number | null;
  trailingPE: number | null;
  forwardPE: number | null;
  priceToBook: number | null;
  pegRatio: number | null;
  enterpriseToEbitda: number | null;
  enterpriseToRevenue: number | null;
  beta: number | null;
  fiftyTwoWeekHigh: number | null;
  fiftyTwoWeekLow: number | null;
  fiftyDayAverage: number | null;
  twoHundredDayAverage: number | null;
  dividendYield: number | null;
  payoutRatio: number | null;
  trailingEps: number | null;
  forwardEps: number | null;
  profitMargins: number | null;
  operatingMargins: number | null;
  returnOnAssets: number | null;
  returnOnEquity: number | null;
  revenuePerShare: number | null;
  totalRevenue: number | null;
  revenueGrowth: number | null;
  grossProfits: number | null;
  ebitda: number | null;
  netIncomeToCommon: number | null;
  totalCash: number | null;
  totalCashPerShare: number | null;
  totalDebt: number | null;
  debtToEquity: number | null;
  currentRatio: number | null;
  quickRatio: number | null;
  bookValue: number | null;
  operatingCashflow: number | null;
  freeCashflow: number | null;
  earningsGrowth: number | null;
  sharesOutstanding: number | null;
  floatShares: number | null;
  heldPercentInsiders: number | null;
  heldPercentInstitutions: number | null;
  recommendationKey: string | null;
  recommendationMean: number | null;
  numberOfAnalystOpinions: number | null;
  targetMeanPrice: number | null;
  targetHighPrice: number | null;
  targetLowPrice: number | null;
  fiscalYearEnd: string | null;
  mostRecentQuarter: string | null;
}

export const SUMMARY_MODULES =
  "price,summaryDetail,defaultKeyStatistics,financialData,assetProfile,recommendationTrend";

function raw(v: unknown): number | null {
  if (v == null) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "object" && v !== null && "raw" in v) {
    const r = (v as { raw?: unknown }).raw;
    return typeof r === "number" && Number.isFinite(r) ? r : null;
  }
  return null;
}

function rawDate(v: unknown): string | null {
  const n = raw(v);
  if (n == null) return null;
  return new Date(n * 1000).toISOString().slice(0, 10);
}

export async function fetchQuoteSummary(
  symbol: string
): Promise<QuoteSummary | null> {
  const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(
    symbol
  )}?modules=${SUMMARY_MODULES}`;

  const res =
    (await yahooFetch(url, true)) ?? (await yahooFetch(url, false));
  if (!res) return null;

  try {
    const json = await res.json();
    const result = json?.quoteSummary?.result?.[0];
    if (!result) return null;

    const price = result.price ?? {};
    const summaryDetail = result.summaryDetail ?? {};
    const keyStats = result.defaultKeyStatistics ?? {};
    const financialData = result.financialData ?? {};
    const assetProfile = result.assetProfile ?? {};

    return {
      symbol,
      shortName: price.shortName ?? null,
      longName: price.longName ?? null,
      currency: price.currency ?? summaryDetail.currency ?? null,
      exchange: price.exchangeName ?? null,
      sector: assetProfile.sector ?? null,
      industry: assetProfile.industry ?? null,
      regularMarketPrice: raw(price.regularMarketPrice),
      previousClose: raw(summaryDetail.previousClose),
      marketCap: raw(price.marketCap ?? summaryDetail.marketCap),
      trailingPE: raw(summaryDetail.trailingPE),
      forwardPE: raw(summaryDetail.forwardPE ?? keyStats.forwardPE),
      priceToBook: raw(keyStats.priceToBook),
      pegRatio: raw(keyStats.pegRatio),
      enterpriseToEbitda: raw(keyStats.enterpriseToEbitda),
      enterpriseToRevenue: raw(keyStats.enterpriseToRevenue),
      beta: raw(keyStats.beta ?? summaryDetail.beta),
      fiftyTwoWeekHigh: raw(summaryDetail.fiftyTwoWeekHigh),
      fiftyTwoWeekLow: raw(summaryDetail.fiftyTwoWeekLow),
      fiftyDayAverage: raw(summaryDetail.fiftyDayAverage),
      twoHundredDayAverage: raw(summaryDetail.twoHundredDayAverage),
      dividendYield: raw(summaryDetail.dividendYield),
      payoutRatio: raw(summaryDetail.payoutRatio),
      trailingEps: raw(keyStats.trailingEps),
      forwardEps: raw(keyStats.forwardEps),
      profitMargins: raw(financialData.profitMargins ?? keyStats.profitMargins),
      operatingMargins: raw(financialData.operatingMargins),
      returnOnAssets: raw(financialData.returnOnAssets),
      returnOnEquity: raw(financialData.returnOnEquity),
      revenuePerShare: raw(financialData.revenuePerShare),
      totalRevenue: raw(financialData.totalRevenue),
      revenueGrowth: raw(financialData.revenueGrowth),
      grossProfits: raw(financialData.grossProfits),
      ebitda: raw(financialData.ebitda),
      netIncomeToCommon: raw(keyStats.netIncomeToCommon),
      totalCash: raw(financialData.totalCash),
      totalCashPerShare: raw(financialData.totalCashPerShare),
      totalDebt: raw(financialData.totalDebt),
      debtToEquity: raw(financialData.debtToEquity),
      currentRatio: raw(financialData.currentRatio),
      quickRatio: raw(financialData.quickRatio),
      bookValue: raw(keyStats.bookValue),
      operatingCashflow: raw(financialData.operatingCashflow),
      freeCashflow: raw(financialData.freeCashflow),
      earningsGrowth: raw(financialData.earningsGrowth),
      sharesOutstanding: raw(keyStats.sharesOutstanding ?? price.sharesOutstanding),
      floatShares: raw(keyStats.floatShares),
      heldPercentInsiders: raw(keyStats.heldPercentInsiders),
      heldPercentInstitutions: raw(keyStats.heldPercentInstitutions),
      recommendationKey: financialData.recommendationKey ?? null,
      recommendationMean: raw(financialData.recommendationMean),
      numberOfAnalystOpinions: raw(financialData.numberOfAnalystOpinions),
      targetMeanPrice: raw(financialData.targetMeanPrice),
      targetHighPrice: raw(financialData.targetHighPrice),
      targetLowPrice: raw(financialData.targetLowPrice),
      fiscalYearEnd: rawDate(keyStats.nextFiscalYearEnd) ?? rawDate(keyStats.lastFiscalYearEnd),
      mostRecentQuarter: rawDate(keyStats.mostRecentQuarter),
    };
  } catch {
    return null;
  }
}

export interface StatementRow {
  date: string;
  values: Record<string, number | null>;
}

export interface Statements {
  income: StatementRow[];
  balance: StatementRow[];
  cashflow: StatementRow[];
}

export const STATEMENT_MODULES =
  "incomeStatementHistory,incomeStatementHistoryQuarterly,balanceSheetHistory,balanceSheetHistoryQuarterly,cashflowStatementHistory,cashflowStatementHistoryQuarterly";

function rawStatement(
  entries: Record<string, unknown>[] | undefined
): StatementRow[] {
  if (!entries) return [];
  const rows: StatementRow[] = [];
  for (const entry of entries) {
    const dateStr = rawDate(entry.endDate);
    if (!dateStr) continue;
    const values: Record<string, number | null> = {};
    for (const [key, val] of Object.entries(entry)) {
      if (key === "endDate" || key === "maxAge") continue;
      values[key] = raw(val);
    }
    rows.push({ date: dateStr, values });
  }
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return rows;
}

export async function fetchStatements(
  symbol: string
): Promise<{ annual: Statements; quarterly: Statements } | null> {
  const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(
    symbol
  )}?modules=${STATEMENT_MODULES}`;

  const res =
    (await yahooFetch(url, true)) ?? (await yahooFetch(url, false));
  if (!res) return null;

  try {
    const json = await res.json();
    const result = json?.quoteSummary?.result?.[0];
    if (!result) return null;

    const annual: Statements = {
      income: rawStatement(result.incomeStatementHistory?.incomeStatementHistory),
      balance: rawStatement(result.balanceSheetHistory?.balanceSheetStatements),
      cashflow: rawStatement(
        result.cashflowStatementHistory?.cashflowStatements
      ),
    };
    const quarterly: Statements = {
      income: rawStatement(
        result.incomeStatementHistoryQuarterly?.incomeStatementHistory
      ),
      balance: rawStatement(
        result.balanceSheetHistoryQuarterly?.balanceSheetStatements
      ),
      cashflow: rawStatement(
        result.cashflowStatementHistoryQuarterly?.cashflowStatements
      ),
    };

    const isEmpty = (s: Statements) =>
      s.income.length === 0 && s.balance.length === 0 && s.cashflow.length === 0;
    if (isEmpty(annual) && isEmpty(quarterly)) return null;

    return { annual, quarterly };
  } catch {
    return null;
  }
}

export interface SearchHit {
  symbol: string;
  name: string;
  exchange: string | null;
  type: string | null;
}

export const COMMON_SUFFIXES = [
  "",
  ".VN",
  ".DE",
  ".L",
  ".T",
  ".HK",
  ".SS",
  ".SZ",
  ".TW",
  ".KS",
  ".NS",
  ".SI",
  ".AX",
  ".TO",
  ".PA",
  ".MI",
  ".SW",
];

export async function probeAsSymbol(query: string): Promise<SearchHit[]> {
  const q = query.trim().toUpperCase();
  if (!q || /\s/.test(q)) return [];
  const hits: SearchHit[] = [];
  for (const suffix of COMMON_SUFFIXES) {
    const candidate = q.includes(".") ? q : `${q}${suffix}`;
    const result = await fetchChart(candidate, "5d");
    if (result && result.candles.length > 0) {
      hits.push({ symbol: candidate, name: candidate, exchange: null, type: "EQUITY" });
      if (q.includes(".")) break;
    }
  }
  return hits;
}

export async function searchSymbols(
  query: string,
  maxResults = 10
): Promise<SearchHit[]> {
  const url = `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(
    query
  )}&quotesCount=${maxResults}&newsCount=0`;

  const res = await yahooFetch(url, false);
  if (res) {
    try {
      const json = await res.json();
      const quotes = json?.quotes ?? [];
      const hits: SearchHit[] = quotes
        .filter((q: Record<string, unknown>) => q.symbol)
        .map((q: Record<string, unknown>) => ({
          symbol: q.symbol as string,
          name: (q.shortname ?? q.longname ?? q.symbol) as string,
          exchange: (q.exchange as string) ?? null,
          type: (q.quoteType as string) ?? null,
        }));
      if (hits.length > 0) return hits;
    } catch {
      // fall through to probing
    }
  }

  return probeAsSymbol(query);
}

export async function fetchFxRate(
  from: string,
  to: string
): Promise<number | null> {
  if (from.toUpperCase() === to.toUpperCase()) return 1;
  const pair = `${from.toUpperCase()}${to.toUpperCase()}=X`;
  const result = await fetchChart(pair, "5d");
  if (!result || result.candles.length === 0) return null;
  return result.candles[result.candles.length - 1].close;
}
