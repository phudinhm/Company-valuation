"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { SearchHit } from "@/lib/yahoo";

const POPULAR = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "SAP.DE", "7203.T"];

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const trimmedQuery = query.trim();

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!trimmedQuery) return;
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(trimmedQuery)}`);
        const data = await res.json();
        setHits(data.hits ?? []);
        setOpen(true);
      } catch {
        setHits([]);
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [trimmedQuery]);

  function goTo(symbol: string) {
    router.push(`/stock/${encodeURIComponent(symbol)}`);
  }

  return (
    <main className="flex-1 flex flex-col items-center justify-center px-4 gap-8">
      <div className="text-center space-y-2">
        <div className="eyebrow">Investment Terminal</div>
        <h1 style={{ fontSize: "var(--fs-hdr)" }} className="font-semibold">
          Search any company, anywhere
        </h1>
        <p className="kpi-sub">Live quotes, financials, technicals, and DCF valuation.</p>
      </div>

      <div className="w-full max-w-xl relative">
        <input
          className="card w-full px-4 py-3"
          placeholder="Search ticker or company name (e.g. Vinamilk, AAPL, 7203.T)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && query.trim()) {
              if (hits.length > 0) goTo(hits[0].symbol);
              else goTo(query.trim().toUpperCase());
            }
          }}
          onFocus={() => hits.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
        {open && trimmedQuery && hits.length > 0 && (
          <div className="card absolute mt-1 w-full z-10 max-h-72 overflow-y-auto p-1">
            {hits.map((hit) => (
              <button
                key={hit.symbol}
                className="w-full text-left px-3 py-2 rounded-md hover:bg-black/5 flex justify-between items-center"
                onMouseDown={() => goTo(hit.symbol)}
              >
                <span>{hit.name}</span>
                <span className="kpi-sub mono">{hit.symbol}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 justify-center max-w-xl">
        {POPULAR.map((sym) => (
          <button
            key={sym}
            className="card px-3 py-1.5 text-sm mono hover:bg-black/5"
            onClick={() => goTo(sym)}
          >
            {sym}
          </button>
        ))}
      </div>
    </main>
  );
}
