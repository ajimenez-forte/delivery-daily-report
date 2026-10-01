import "server-only";
import { createClient } from "@/lib/supabase/server";
import type { Fila } from "@/lib/carga";

/** Filas de carga_cumplimiento y días del rango. Todo con el token del usuario (RLS). */
export async function loadCarga(desde: string, hasta: string) {
  const supabase = await createClient();
  const [{ data: rows, error }, { data: days, error: e2 }] = await Promise.all([
    supabase.rpc("carga_cumplimiento", { p_desde: desde, p_hasta: hasta }),
    supabase.from("days").select("day, format").gte("day", desde).lte("day", hasta).order("day"),
  ]);
  if (error || e2) throw new Error((error || e2)!.message);
  return { rows: (rows ?? []) as Fila[], days: (days ?? []) as { day: string; format: string }[] };
}
