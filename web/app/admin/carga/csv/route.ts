import { NextResponse, type NextRequest } from "next/server";
import { getIdentity } from "@/lib/auth";
import { libreNote, parseRange, parseSort, sortRows, toCsv } from "@/lib/carga";
import { loadCarga } from "@/lib/data/carga";

export async function GET(request: NextRequest) {
  const me = await getIdentity();
  if (!me) return new NextResponse("Sin sesión", { status: 401 });
  if (!me.isAdmin) return new NextResponse("Solo admin", { status: 403 });
  const q = Object.fromEntries(request.nextUrl.searchParams);
  const [desde, hasta] = parseRange(q);
  const { sort, desc } = parseSort(q);
  const { rows, days } = await loadCarga(desde, hasta);
  const body = toCsv(sortRows(rows, sort, desc), desde, hasta, libreNote(days));
  return new NextResponse(body, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="carga_cumplimiento_${desde}_a_${hasta}.csv"`,
      "cache-control": "no-store",
    },
  });
}
