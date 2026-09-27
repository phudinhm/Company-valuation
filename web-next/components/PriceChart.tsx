"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle } from "@/lib/yahoo";
import { computeIndicators } from "@/lib/analysis";

export function PriceChart({ candles }: { candles: Candle[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || candles.length === 0) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#6b6f85",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "rgba(148,150,170,0.12)" },
        horzLines: { color: "rgba(148,150,170,0.12)" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#1f8a54",
      downColor: "#c0392b",
      borderVisible: false,
      wickUpColor: "#1f8a54",
      wickDownColor: "#c0392b",
    });
    candleSeries.setData(
      candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );

    const indicators = computeIndicators(candles);

    const sma50Series = chart.addSeries(LineSeries, {
      color: "#6366f1",
      lineWidth: 1,
      title: "SMA 50",
    });
    sma50Series.setData(
      indicators.time
        .map((t, i) => ({ time: t as UTCTimestamp, value: indicators.sma50[i] }))
        .filter((d): d is { time: UTCTimestamp; value: number } => d.value != null)
    );

    const sma200Series = chart.addSeries(LineSeries, {
      color: "#b8760a",
      lineWidth: 1,
      title: "SMA 200",
    });
    sma200Series.setData(
      indicators.time
        .map((t, i) => ({ time: t as UTCTimestamp, value: indicators.sma200[i] }))
        .filter((d): d is { time: UTCTimestamp; value: number } => d.value != null)
    );

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candles]);

  if (candles.length === 0) {
    return (
      <div className="card flex items-center justify-center h-[360px] kpi-sub">
        No price history available.
      </div>
    );
  }

  return <div ref={containerRef} className="card h-[360px]" />;
}
