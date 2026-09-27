export const NA = "—";

export const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CNY: "¥",
  VND: "₫",
  HKD: "HK$",
  KRW: "₩",
  INR: "₹",
  SGD: "S$",
  AUD: "A$",
  CAD: "C$",
  CHF: "CHF",
  TWD: "NT$",
};

export function currencySymbol(code?: string | null): string {
  if (!code) return "$";
  return CURRENCY_SYMBOLS[code.toUpperCase()] ?? code.toUpperCase() + " ";
}

function isFiniteNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function num(v: number | null | undefined, decimals = 2): string {
  if (!isFiniteNum(v)) return NA;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function money(
  v: number | null | undefined,
  currency = "USD",
  compact = true
): string {
  if (!isFiniteNum(v)) return NA;
  const sym = currencySymbol(currency);
  if (!compact) return `${sym}${num(v, 2)}`;

  const abs = Math.abs(v);
  if (abs >= 1e12) return `${sym}${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sym}${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sym}${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sym}${(v / 1e3).toFixed(2)}K`;
  return `${sym}${num(v, 2)}`;
}

export function price(v: number | null | undefined, currency = "USD"): string {
  if (!isFiniteNum(v)) return NA;
  const sym = currencySymbol(currency);
  return `${sym}${num(v, 2)}`;
}

export function pct(v: number | null | undefined, decimals = 2): string {
  if (!isFiniteNum(v)) return NA;
  return `${(v * 100).toFixed(decimals)}%`;
}

export function asPct(v: number | null | undefined, decimals = 2): string {
  if (!isFiniteNum(v)) return NA;
  return `${v.toFixed(decimals)}%`;
}

export function ratio(v: number | null | undefined, decimals = 2): string {
  if (!isFiniteNum(v)) return NA;
  return `${v.toFixed(decimals)}x`;
}

export function safeDiv(
  numerator: number | null | undefined,
  denominator: number | null | undefined
): number | null {
  if (!isFiniteNum(numerator) || !isFiniteNum(denominator) || denominator === 0) {
    return null;
  }
  return numerator / denominator;
}

export function cagr(
  begin: number | null | undefined,
  end: number | null | undefined,
  years: number
): number | null {
  if (!isFiniteNum(begin) || !isFiniteNum(end) || begin <= 0 || years <= 0) {
    return null;
  }
  return Math.pow(end / begin, 1 / years) - 1;
}

export function dateStr(d: string | number | Date | null | undefined): string {
  if (!d) return NA;
  const date = new Date(d);
  if (Number.isNaN(date.getTime())) return NA;
  return date.toISOString().slice(0, 10);
}
