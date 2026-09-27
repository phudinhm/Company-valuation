import type { Candle } from "./yahoo";

export interface IndicatorSeries {
  time: number[];
  sma20: (number | null)[];
  sma50: (number | null)[];
  sma200: (number | null)[];
  rsi14: (number | null)[];
  bbUpper: (number | null)[];
  bbLower: (number | null)[];
}

function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function stdDev(values: number[], period: number, means: (number | null)[]): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    const mean = means[i];
    if (mean == null) continue;
    let sumSq = 0;
    for (let j = i - period + 1; j <= i; j++) {
      sumSq += (values[j] - mean) ** 2;
    }
    out[i] = Math.sqrt(sumSq / period);
  }
  return out;
}

function rsi(values: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period + 1) return out;

  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const diff = values[i] - values[i - 1];
    if (diff >= 0) gainSum += diff;
    else lossSum -= diff;
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period + 1; i < values.length; i++) {
    const diff = values[i] - values[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

export function computeIndicators(candles: Candle[]): IndicatorSeries {
  const closes = candles.map((c) => c.close);
  const time = candles.map((c) => c.time);
  const sma20 = sma(closes, 20);
  const sma50 = sma(closes, 50);
  const sma200 = sma(closes, 200);
  const rsi14 = rsi(closes, 14);
  const std20 = stdDev(closes, 20, sma20);

  const bbUpper: (number | null)[] = closes.map((_, i) =>
    sma20[i] != null && std20[i] != null ? sma20[i]! + 2 * std20[i]! : null
  );
  const bbLower: (number | null)[] = closes.map((_, i) =>
    sma20[i] != null && std20[i] != null ? sma20[i]! - 2 * std20[i]! : null
  );

  return { time, sma20, sma50, sma200, rsi14, bbUpper, bbLower };
}

export interface DcfInputs {
  baseFcf: number;
  growth1: number;
  years1: number;
  growth2?: number;
  years2?: number;
  terminalGrowth: number;
  wacc: number;
  netDebt: number;
  sharesOutstanding: number;
}

export interface DcfResult {
  fairValue: number;
  enterpriseValue: number;
  equityValue: number;
  pvExplicit: number;
  pvTerminal: number;
  terminalShare: number;
  projectedFcf: number[];
}

export function computeDcf(inputs: DcfInputs): DcfResult {
  const {
    baseFcf,
    growth1,
    years1,
    growth2 = (growth1 + inputs.terminalGrowth) / 2,
    years2 = 5,
    terminalGrowth,
    wacc,
    netDebt,
    sharesOutstanding,
  } = inputs;

  const projectedFcf: number[] = [];
  let fcf = baseFcf;
  let pvExplicit = 0;

  for (let t = 1; t <= years1; t++) {
    fcf = fcf * (1 + growth1);
    projectedFcf.push(fcf);
    pvExplicit += fcf / Math.pow(1 + wacc, t);
  }

  for (let t = 1; t <= years2; t++) {
    const stepGrowth =
      growth1 + ((growth2 - growth1) * t) / years2;
    fcf = fcf * (1 + stepGrowth);
    projectedFcf.push(fcf);
    pvExplicit += fcf / Math.pow(1 + wacc, years1 + t);
  }

  const terminalFcf = fcf * (1 + terminalGrowth);
  const terminalValue = terminalFcf / (wacc - terminalGrowth);
  const pvTerminal = terminalValue / Math.pow(1 + wacc, years1 + years2);

  const enterpriseValue = pvExplicit + pvTerminal;
  const equityValue = enterpriseValue - netDebt;
  const fairValue = sharesOutstanding > 0 ? equityValue / sharesOutstanding : 0;

  return {
    fairValue,
    enterpriseValue,
    equityValue,
    pvExplicit,
    pvTerminal,
    terminalShare: enterpriseValue !== 0 ? pvTerminal / enterpriseValue : 0,
    projectedFcf,
  };
}

export function capmWacc(
  beta: number,
  riskFree: number,
  erp: number,
  costDebt: number,
  taxRate: number,
  marketCap: number,
  debt: number
): { wacc: number; costEquity: number } {
  const costEquity = riskFree + beta * erp;
  const totalCap = marketCap + debt;
  if (totalCap <= 0) return { wacc: costEquity, costEquity };
  const weightEquity = marketCap / totalCap;
  const weightDebt = debt / totalCap;
  const afterTaxCostDebt = costDebt * (1 - taxRate);
  const wacc = weightEquity * costEquity + weightDebt * afterTaxCostDebt;
  return { wacc, costEquity };
}

export function scale(v: number | null, lo: number, hi: number): number {
  if (v == null || !Number.isFinite(v)) return 50;
  if (hi === lo) return 50;
  const pct = ((v - lo) / (hi - lo)) * 100;
  return Math.max(0, Math.min(100, pct));
}

export function avg(values: (number | null | undefined)[]): number | null {
  const nums = values.filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v)
  );
  if (nums.length === 0) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

export interface Pillar {
  name: string;
  score: number;
  weight: number;
}

export interface ScorecardMetrics {
  trailingPE: number | null;
  priceToBook: number | null;
  enterpriseToEbitda: number | null;
  profitMargins: number | null;
  returnOnEquity: number | null;
  operatingMargins: number | null;
  currentRatio: number | null;
  debtToEquity: number | null;
  revenueGrowth: number | null;
  earningsGrowth: number | null;
}

export function buildScorecard(metrics: ScorecardMetrics): {
  total: number;
  band: string;
  pillars: Pillar[];
} {
  const valuationScore = avg([
    metrics.trailingPE != null ? 100 - scale(metrics.trailingPE, 5, 40) : null,
    metrics.priceToBook != null ? 100 - scale(metrics.priceToBook, 0.5, 10) : null,
    metrics.enterpriseToEbitda != null
      ? 100 - scale(metrics.enterpriseToEbitda, 4, 25)
      : null,
  ]) ?? 50;

  const profitabilityScore = avg([
    metrics.profitMargins != null ? scale(metrics.profitMargins * 100, 0, 30) : null,
    metrics.returnOnEquity != null ? scale(metrics.returnOnEquity * 100, 0, 30) : null,
    metrics.operatingMargins != null
      ? scale(metrics.operatingMargins * 100, 0, 30)
      : null,
  ]) ?? 50;

  const financialHealthScore = avg([
    metrics.currentRatio != null ? scale(metrics.currentRatio, 0.5, 3) : null,
    metrics.debtToEquity != null
      ? 100 - scale(metrics.debtToEquity, 0, 200)
      : null,
  ]) ?? 50;

  const growthScore = avg([
    metrics.revenueGrowth != null ? scale(metrics.revenueGrowth * 100, -10, 30) : null,
    metrics.earningsGrowth != null ? scale(metrics.earningsGrowth * 100, -10, 40) : null,
  ]) ?? 50;

  const pillars: Pillar[] = [
    { name: "Valuation", score: valuationScore, weight: 0.3 },
    { name: "Profitability", score: profitabilityScore, weight: 0.25 },
    { name: "Financial health", score: financialHealthScore, weight: 0.25 },
    { name: "Growth", score: growthScore, weight: 0.2 },
  ];

  const total = pillars.reduce((sum, p) => sum + p.score * p.weight, 0);

  let band: string;
  if (total >= 80) band = "Exceptional";
  else if (total >= 65) band = "Strong";
  else if (total >= 50) band = "Solid";
  else if (total >= 35) band = "Mixed";
  else band = "Fragile";

  return { total, band, pillars };
}
