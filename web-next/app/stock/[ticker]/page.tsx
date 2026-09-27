"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import type { Candle, QuoteSummary, StatementRow } from "@/lib/yahoo";
import { PriceChart } from "@/components/PriceChart";
import { FinancialsTable } from "@/components/FinancialsTable";
import { DcfPanel } from "@/components/DcfPanel";
import { KpiGrid, Note, Section } from "@/components/Kpi";
import { buildScorecard } from "@/lib/analysis";
import { price as fmtPrice, pct, ratio, money, num } from "@/lib/format";

const RANGES = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"];
type Tab = "overview" | "financials" | "valuation";

interface QuoteResponse {
  summary: QuoteSummary | null;
  price: number | null;
  currency: string | null;
}

interface HistoryResponse {
  candles: Candle[];
}

interface FinancialsResponse {
  annual: { income: StatementRow[]; balance: StatementRow[]; cashflow: StatementRow[] };
  quarterly: { income: StatementRow[]; balance: StatementRow[]; cashflow: StatementRow[] };
}

export default function StockPage({
  params,
}: PageProps<"/stock/[ticker]">) {
  const { ticker } = use(params);
  const symbol = decodeURIComponent(ticker).toUpperCase();

  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [financials, setFinancials] = useState<FinancialsResponse | null>(null);
  const [range, setRange] = useState("1y");
  const [tab, setTab] = useState<Tab>("overview");
  const [basis, setBasis] = useState<"annual" | "quarterly">("annual");
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset stale not-found state from a previous ticker while the new fetch is in flight
    setNotFound(false);
    setQuote(null);
    setHistory(null);
    setFinancials(null);

    async function load() {
      const [quoteRes, financialsRes] = await Promise.all([
        fetch(`/api/quote/${encodeURIComponent(symbol)}`),
        fetch(`/api/financials/${encodeURIComponent(symbol)}`),
      ]);
      if (cancelled) return;

      if (quoteRes.status === 404) {
        setNotFound(true);
        return;
      }
      const quoteData = await quoteRes.json();
      setQuote(quoteData);

      if (financialsRes.ok) {
        setFinancials(await financialsRes.json());
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  useEffect(() => {
    let cancelled = false;
    async function loadHistory() {
      const res = await fetch(
        `/api/history/${encodeURIComponent(symbol)}?range=${range}`
      );
      if (cancelled) return;
      if (res.ok) setHistory(await res.json());
    }
    loadHistory();
    return () => {
      cancelled = true;
    };
  }, [symbol, range]);

  if (notFound) {
    return (
      <main className="flex-1 flex items-center justify-center px-4">
        <div className="card max-w-md text-center space-y-3">
          <div className="section-title">No data for &ldquo;{symbol}&rdquo;</div>
          <p className="kpi-sub">
            We couldn&apos;t find price or fundamental data for this symbol.
            Try a different ticker or search by company name.
          </p>
          <Link href="/" className="eyebrow inline-block">
            ← Back to search
          </Link>
        </div>
      </main>
    );
  }

  const summary = quote?.summary ?? null;
  const currency = summary?.currency ?? quote?.currency ?? "USD";
  const candles = history?.candles ?? [];

  const scorecard = summary
    ? buildScorecard({
        trailingPE: summary.trailingPE,
        priceToBook: summary.priceToBook,
        enterpriseToEbitda: summary.enterpriseToEbitda,
        profitMargins: summary.profitMargins,
        returnOnEquity: summary.returnOnEquity,
        operatingMargins: summary.operatingMargins,
        currentRatio: summary.currentRatio,
        debtToEquity: summary.debtToEquity,
        revenueGrowth: summary.revenueGrowth,
        earningsGrowth: summary.earningsGrowth,
      })
    : null;

  const statements = financials?.[basis];

  return (
    <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="eyebrow">{symbol}</div>
          <h1 style={{ fontSize: "var(--fs-hdr)" }} className="font-semibold">
            {summary?.longName ?? summary?.shortName ?? symbol}
          </h1>
          <div className="kpi-sub">
            {summary?.exchange ?? ""} {summary?.sector ? `· ${summary.sector}` : ""}
          </div>
        </div>
        <div className="text-right">
          <div className="kpi-value mono">
            {fmtPrice(quote?.price ?? summary?.regularMarketPrice, currency)}
          </div>
          <Link href="/" className="kpi-sub">
            ← New search
          </Link>
        </div>
      </div>

      <div className="flex gap-2 border-b" style={{ borderColor: "var(--border)" }}>
        {(["overview", "financials", "valuation"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="px-3 py-2 capitalize"
            style={{
              borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent",
              color: tab === t ? "var(--accent)" : "var(--foreground)",
              fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-6">
          {scorecard && (
            <div className="card space-y-3">
              <div className="flex items-baseline justify-between">
                <Section title="Composite scorecard" />
                <div className="text-right">
                  <div className="kpi-value mono">{scorecard.total.toFixed(0)}</div>
                  <div className="kpi-sub">{scorecard.band}</div>
                </div>
              </div>
              <div className="space-y-2">
                {scorecard.pillars.map((p) => (
                  <div key={p.name}>
                    <div className="flex justify-between kpi-sub mb-1">
                      <span>{p.name}</span>
                      <span>{p.score.toFixed(0)}</span>
                    </div>
                    <div
                      className="h-2 rounded-full overflow-hidden"
                      style={{ background: "var(--border)" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${p.score}%`,
                          background: "var(--accent)",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <Note tone="neu">
                A weighted blend of valuation (30%), profitability (25%),
                financial health (25%), and growth (20%), each scaled 0-100
                against typical market ranges.
              </Note>
            </div>
          )}

          {summary && (
            <KpiGrid
              items={[
                { label: "Market cap", value: money(summary.marketCap, currency) },
                { label: "P/E (trailing)", value: ratio(summary.trailingPE) },
                { label: "P/B", value: ratio(summary.priceToBook) },
                { label: "EV/EBITDA", value: ratio(summary.enterpriseToEbitda) },
                { label: "Profit margin", value: pct(summary.profitMargins) },
                { label: "Return on equity", value: pct(summary.returnOnEquity) },
                { label: "Revenue growth (yoy)", value: pct(summary.revenueGrowth) },
                { label: "Dividend yield", value: pct(summary.dividendYield) },
                { label: "Beta", value: num(summary.beta) },
                { label: "52w range low", value: fmtPrice(summary.fiftyTwoWeekLow, currency) },
                { label: "52w range high", value: fmtPrice(summary.fiftyTwoWeekHigh, currency) },
                {
                  label: "Analyst target (mean)",
                  value: fmtPrice(summary.targetMeanPrice, currency),
                  sub: summary.numberOfAnalystOpinions
                    ? `${summary.numberOfAnalystOpinions} analysts`
                    : undefined,
                },
              ]}
            />
          )}

          <div>
            <div className="flex gap-2 mb-2 flex-wrap">
              {RANGES.map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className="px-2.5 py-1 text-sm rounded-md mono"
                  style={{
                    background: range === r ? "var(--accent)" : "var(--card-bg)",
                    color: range === r ? "#fff" : "var(--foreground)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
            <PriceChart candles={candles} />
          </div>
        </div>
      )}

      {tab === "financials" && (
        <div className="space-y-4">
          <div className="flex gap-2">
            {(["annual", "quarterly"] as const).map((b) => (
              <button
                key={b}
                onClick={() => setBasis(b)}
                className="px-3 py-1.5 text-sm rounded-md capitalize"
                style={{
                  background: basis === b ? "var(--accent)" : "var(--card-bg)",
                  color: basis === b ? "#fff" : "var(--foreground)",
                  border: "1px solid var(--border)",
                }}
              >
                {b}
              </button>
            ))}
          </div>
          <div>
            <Section title="Income statement" />
            <FinancialsTable
              rows={statements?.income ?? []}
              currency={currency}
              baseKey="totalRevenue"
            />
          </div>
          <div>
            <Section title="Balance sheet" />
            <FinancialsTable
              rows={statements?.balance ?? []}
              currency={currency}
              baseKey="totalAssets"
            />
          </div>
          <div>
            <Section title="Cash flow statement" />
            <FinancialsTable rows={statements?.cashflow ?? []} currency={currency} />
          </div>
        </div>
      )}

      {tab === "valuation" && summary && (
        <div>
          <Section title="Discounted cash flow" sub="Adjust assumptions to stress-test fair value." />
          <DcfPanel summary={summary} />
        </div>
      )}
    </main>
  );
}
