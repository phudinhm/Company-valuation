import clsx from "clsx";

export interface KpiItem {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad" | "warn" | "flat";
}

export function KpiGrid({ items }: { items: KpiItem[] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {items.map((item) => (
        <div key={item.label} className={clsx("card kpi", item.tone ?? "flat")}>
          <div className="kpi-label">{item.label}</div>
          <div className="kpi-value mono">{item.value}</div>
          {item.sub && <div className="kpi-sub">{item.sub}</div>}
        </div>
      ))}
    </div>
  );
}

export function Note({
  children,
  tone = "neu",
}: {
  children: React.ReactNode;
  tone?: "pos" | "neg" | "neu";
}) {
  return <div className={clsx("note", tone)}>{children}</div>;
}

export function Section({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-2">
      <div className="section-title">{title}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
