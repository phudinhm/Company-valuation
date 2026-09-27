import { NextRequest, NextResponse } from "next/server";
import { searchSymbols } from "@/lib/yahoo";

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q")?.trim() ?? "";
  if (!q) {
    return NextResponse.json({ query: q, hits: [] });
  }

  const hits = await searchSymbols(q, 10);
  return NextResponse.json({ query: q, hits });
}
