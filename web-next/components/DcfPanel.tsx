"use client";

import { useMemo, useState } from "react";
import { computeDcf, capmWacc } from "@/lib/analysis";
import { price as fmtPrice, pct } from "@/lib/format";
import { KpiGrid, Note } from "./Kpi";
import type { QuoteSummary } from "@/lib/yahoo";

export function DcfPanel({ summary }: { summary: QuoteSummary }) {
  const defaultWacc = useMemo(() => {
    if (summary.beta == null || summary.marketCap == null) return 0.09;
    const { wacc } = capmWacc(
      summary.beta,
      0.042,
      0.05,
      0.05,
      0.21,
      summary.marketCap,
      summary.totalDebt ?? 0
    );
    return Math.max(0.04, Math.min(0.2, wacc));
  }, [summary.beta, summary.marketCap, summary.totalDebt]);

  const [growth1, setGrowth1] = useState(0.08);
  const [years1, setYears1] = useState(5);
  const [wacc, setWacc] = useState(defaultWacc);
  const [terminalGrowth, setTerminalGrowth] = useState(0.025);

  const baseFcf = summary.freeCashflow ?? summary.operatingCashflow ?? null;
  const netDebt = (summary.totalDebt ?? 0) - (summary.totalCash ?? 0);
  const shares = summary.sharesOutstanding ?? 0;

  const result = useMemo(() => {
    if (baseFcf == null || shares <= 0) return null;
    if (wacc <= terminalGrowth) return null;
    return computeDcf({
      baseFcf,
      growth1,
      years1,
      terminalGrowth,
      wacc,
      netDebt,
      sharesOutstanding: shares,
    });
  }, [baseFcf, growth1, years1, terminalGrowth, wacc, netDebt, shares]);

  if (baseFcf == null || shares <= 0) {
    return (
      <Note tone="neu">
        Not enough data (free cash flow or shares outstanding missing) to run a
        DCF for this company.
      </Note>
    );
  }

  const upside =
    result && summary.regularMarketPrice
      ? result.fairValue / summary.regularMarketPrice - 1
      : null;

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-1 sm:grid-cols-2 gap-4">
        <label className="flex flex-col gap-1">
          <span className="kpi-label">Stage 1 growth ({pct(growth1, 1)})</span>
          <input
            type="range"
            min={-0.1}
            max={0.4}
            step={0.005}
            value={growth1}
            onChange={(e) => setGrowth1(parseFloat(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="kpi-label">Stage 1 length ({years1} yrs)</span>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={years1}
            onChange={(e) => setYears1(parseInt(e.target.value, 10))}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="kpi-label">WACC ({pct(wacc, 1)})</span>
          <input
            type="range"
            min={0.04}
            max={0.2}
            step={0.001}
            value={wacc}
            onChange={(e) => setWacc(parseFloat(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="kpi-label">Terminal growth ({pct(terminalGrowth, 1)})</span>
          <input
            type="range"
            min={0}
            max={0.04}
            step={0.001}
            value={terminalGrowth}
            onChange={(e) => setTerminalGrowth(parseFloat(e.target.value))}
          />
        </label>
      </div>

      {result ? (
        <>
          <KpiGrid
            items={[
              {
                label: "Fair value / share",
                value: fmtPrice(result.fairValue, summary.currency ?? "USD"),
                tone: upside != null && upside > 0 ? "good" : "bad",
              },
              {
                label: "Current price",
                value: fmtPrice(summary.regularMarketPrice, summary.currency ?? "USD"),
              },
              {
                label: "Implied upside",
                value: upside != null ? pct(upside, 1) : "—",
                tone: upside != null && upside > 0 ? "good" : "bad",
              },
              {
                label: "Enterprise value",
                value: fmtPrice(result.enterpriseValue, summary.currency ?? "USD"),
              },
              {
                label: "Terminal value share",
                value: pct(result.terminalShare, 0),
              },
            ]}
          />
          <Note tone="neu">
            This DCF discounts an explicit growth stage ({years1} years at{" "}
            {pct(growth1, 1)}), a 5-year fade toward the terminal growth rate,
            then a Gordon-growth terminal value at {pct(terminalGrowth, 1)},
            all discounted at a WACC of {pct(wacc, 1)}. Treat it as one lens,
            not a price target.
          </Note>
        </>
      ) : (
        <Note tone="neg">
          WACC must be greater than the terminal growth rate for the model to
          resolve.
        </Note>
      )}
    </div>
  );
}
