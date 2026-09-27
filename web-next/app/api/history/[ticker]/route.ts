import { NextRequest, NextResponse } from "next/server";
import { fetchChart } from "@/lib/yahoo";
import { fetchStooqHistory } from "@/lib/stooq";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params;
  const symbol = decodeURIComponent(ticker).toUpperCase();
  const range = request.nextUrl.searchParams.get("range") ?? "1y";

  const chart = await fetchChart(symbol, range);
  if (chart && chart.candles.length > 0) {
    return NextResponse.json({
      symbol,
      source: "yahoo",
      currency: chart.currency,
      candles: chart.candles,
    });
  }

  const stooqCandles = await fetchStooqHistory(symbol);
  if (stooqCandles && stooqCandles.length > 0) {
    return NextResponse.json({
      symbol,
      source: "stooq",
      currency: null,
      candles: stooqCandles,
    });
  }

  return NextResponse.json({ error: "not_found", symbol }, { status: 404 });
}
