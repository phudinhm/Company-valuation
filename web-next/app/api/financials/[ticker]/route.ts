import { NextResponse } from "next/server";
import { fetchStatements } from "@/lib/yahoo";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params;
  const symbol = decodeURIComponent(ticker).toUpperCase();

  const statements = await fetchStatements(symbol);
  if (!statements) {
    return NextResponse.json({ error: "not_found", symbol }, { status: 404 });
  }

  return NextResponse.json({
    symbol,
    annual: statements.annual,
    quarterly: statements.quarterly,
  });
}
