import { NextRequest, NextResponse } from "next/server";
import { fetchQuoteSummary, fetchChart, fetchFxRate } from "@/lib/yahoo";
import { fetchStooqHistory } from "@/lib/stooq";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params;
  const symbol = decodeURIComponent(ticker).toUpperCase();
  const targetCurrency = request.nextUrl.searchParams.get("currency");

  const [summary, chart] = await Promise.all([
    fetchQuoteSummary(symbol),
    fetchChart(symbol, "5d"),
  ]);

  let price = summary?.regularMarketPrice ?? null;
  const currency = summary?.currency ?? chart?.currency ?? null;

  if (price == null && chart && chart.candles.length > 0) {
    price = chart.candles[chart.candles.length - 1].close;
  }

  if (price == null) {
    const stooqCandles = await fetchStooqHistory(symbol);
    if (stooqCandles && stooqCandles.length > 0) {
      price = stooqCandles[stooqCandles.length - 1].close;
    }
  }

  if (!summary && price == null) {
    return NextResponse.json(
      { error: "not_found", symbol },
      { status: 404 }
    );
  }

  let fxRate: number | null = null;
  if (targetCurrency && currency && targetCurrency.toUpperCase() !== currency.toUpperCase()) {
    fxRate = await fetchFxRate(currency, targetCurrency);
  }

  return NextResponse.json({
    symbol,
    summary,
    price,
    currency,
    targetCurrency,
    fxRate,
  });
}
