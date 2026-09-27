import type { Candle } from "./yahoo";

export const STOOQ_SUFFIX: Record<string, string> = {
  US: "us",
  DE: "de",
  L: "uk",
  PA: "fr",
  MI: "it",
  SW: "ch",
  AS: "nl",
  BR: "be",
  LS: "pt",
  MC: "es",
  VI: "at",
  HE: "fi",
  ST: "se",
  CO: "dk",
  OL: "no",
  IR: "ie",
  AT: "gr",
  WA: "pl",
  PR: "cz",
  BD: "hu",
  IS: "tr",
  JO: "za",
  SA: "sa",
  TA: "il",
  T: "jp",
  HK: "hk",
  SS: "cn",
  SZ: "cn",
  TW: "tw",
  KS: "kr",
  NS: "in",
  BO: "in",
  SI: "sg",
  AX: "au",
  NZ: "nz",
  TO: "ca",
};

export function toStooqSymbol(ticker: string): string | null {
  const parts = ticker.split(".");
  if (parts.length === 1) {
    return `${ticker.toLowerCase()}.us`;
  }
  const [base, suffix] = parts;
  const mapped = STOOQ_SUFFIX[suffix.toUpperCase()];
  if (!mapped) return null;
  return `${base.toLowerCase()}.${mapped}`;
}

export async function fetchStooqHistory(
  ticker: string
): Promise<Candle[] | null> {
  const symbol = toStooqSymbol(ticker);
  if (!symbol) return null;

  try {
    const res = await fetch(
      `https://stooq.com/q/d/l/?s=${encodeURIComponent(symbol)}&i=d`
    );
    if (!res.ok) return null;
    const text = await res.text();
    if (!text || text.startsWith("<") || text.includes("No data")) return null;

    const lines = text.trim().split("\n");
    if (lines.length < 2) return null;

    const candles: Candle[] = [];
    for (const line of lines.slice(1)) {
      const [date, open, high, low, close, volume] = line.split(",");
      if (!date || !open) continue;
      const time = Math.floor(new Date(date).getTime() / 1000);
      if (Number.isNaN(time)) continue;
      candles.push({
        time,
        open: parseFloat(open),
        high: parseFloat(high),
        low: parseFloat(low),
        close: parseFloat(close),
        volume: parseFloat(volume) || 0,
      });
    }
    return candles.length > 0 ? candles : null;
  } catch {
    return null;
  }
}
