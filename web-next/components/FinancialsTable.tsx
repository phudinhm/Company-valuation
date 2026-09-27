"use client";

import { useState } from "react";
import type { StatementRow } from "@/lib/yahoo";
import { money } from "@/lib/format";

const LABELS: Record<string, string> = {
  totalRevenue: "Total revenue",
  costOfRevenue: "Cost of revenue",
  grossProfit: "Gross profit",
  researchDevelopment: "R&D",
  sellingGeneralAdministrative: "SG&A",
  totalOperatingExpenses: "Total operating expenses",
  operatingIncome: "Operating income",
  ebit: "EBIT",
  interestExpense: "Interest expense",
  incomeBeforeTax: "Income before tax",
  incomeTaxExpense: "Income tax expense",
  netIncome: "Net income",
  netIncomeApplicableToCommonShares: "Net income to common",
  totalAssets: "Total assets",
  totalCurrentAssets: "Current assets",
  cash: "Cash",
  totalLiab: "Total liabilities",
  totalCurrentLiabilities: "Current liabilities",
  longTermDebt: "Long-term debt",
  shortLongTermDebt: "Short-term debt",
  totalStockholderEquity: "Total shareholder equity",
  netTangibleAssets: "Net tangible assets",
  totalCashFromOperatingActivities: "Operating cash flow",
  capitalExpenditures: "Capital expenditures",
  totalCashflowsFromInvestingActivities: "Investing cash flow",
  totalCashFromFinancingActivities: "Financing cash flow",
  dividendsPaid: "Dividends paid",
  netBorrowings: "Net borrowings",
  changeInCash: "Change in cash",
  depreciation: "Depreciation & amortization",
};

function label(key: string): string {
  return LABELS[key] ?? key.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
}

export function FinancialsTable({
  rows,
  currency,
  baseKey,
}: {
  rows: StatementRow[];
  currency?: string | null;
  baseKey?: string;
}) {
  const [commonSize, setCommonSize] = useState(false);

  if (rows.length === 0) {
    return <div className="card kpi-sub">No data available.</div>;
  }

  const sorted = [...rows].sort((a, b) => (a.date < b.date ? 1 : -1));
  const keys = Array.from(
    new Set(sorted.flatMap((r) => Object.keys(r.values)))
  ).filter((k) => sorted.some((r) => r.values[k] != null));

  return (
    <div className="card overflow-x-auto">
      {baseKey && (
        <label className="flex items-center gap-2 mb-3 kpi-sub cursor-pointer w-fit">
          <input
            type="checkbox"
            checked={commonSize}
            onChange={(e) => setCommonSize(e.target.checked)}
          />
          Common size (% of {label(baseKey).toLowerCase()})
        </label>
      )}
      <table className="w-full text-sm mono">
        <thead>
          <tr className="text-left border-b" style={{ borderColor: "var(--border)" }}>
            <th className="py-2 pr-4 kpi-label font-normal">Line item</th>
            {sorted.map((r) => (
              <th key={r.date} className="py-2 pr-4 kpi-label font-normal text-right">
                {r.date}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key} className="border-b" style={{ borderColor: "var(--border)" }}>
              <td className="py-1.5 pr-4">{label(key)}</td>
              {sorted.map((r) => {
                const val = r.values[key];
                const base = baseKey ? r.values[baseKey] : null;
                if (commonSize && baseKey && val != null && base) {
                  return (
                    <td key={r.date} className="py-1.5 pr-4 text-right">
                      {((val / base) * 100).toFixed(1)}%
                    </td>
                  );
                }
                return (
                  <td key={r.date} className="py-1.5 pr-4 text-right">
                    {money(val, currency ?? "USD")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
