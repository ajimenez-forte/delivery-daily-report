// Carga y cumplimiento por persona. El cálculo vive en SQL (public.carga_cumplimiento);
// aquí solo se ordena, se da formato y se arma el CSV. Es el mismo comportamiento que
// daily_report/metrics.py, que ya validó Alejo.

export type Fila = {
  person_id: number;
  persona: string;
  dias_reporte: number;
  dias_disponibles: number;
  dias_pto: number;
  tasa_reporte: number | null;
  dias_marcas_reportados: number;
  compromisos: number;
  compromisos_por_dia: number | null;
  hechos: number;
  pendientes: number;
  marcados: number;
  pct_hechos: number | null;
  sin_tocar: number;
  pct_sin_tocar: number | null;
  cumplimiento: number | null;
  alertas_tercer_dia: number;
  sin_marca: number;
};

export const COLUMNS = [
  ["persona", "Persona"],
  ["tasa_reporte", "Días con reporte"],
  ["compromisos_por_dia", "Compromisos por día"],
  ["pct_hechos", "Ayer hechos"],
  ["pct_sin_tocar", "Sin tocar"],
  ["alertas_tercer_dia", "Alertas de tercer día"],
  ["sin_marca", "Líneas sin marca"],
] as const;
export type SortKey = (typeof COLUMNS)[number][0];
const SORT_KEYS = new Set<string>(COLUMNS.map(([k]) => k));

export const DISCLAIMER =
  "Todo es autorreportado. Mide cómo reporta cada persona, no cuánto produce. " +
  "Una tarea de datos y una llamada de seguimiento pesan lo mismo.";

const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** Fecha de hoy en Bogotá, YYYY-MM-DD. */
export function todayBogota(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Bogota" }).format(now);
}

function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Rango por defecto: los últimos 30 días, contando hoy. */
export function last30Days(now = new Date()): [string, string] {
  const today = todayBogota(now);
  return [addDays(today, -29), today];
}

export function parseRange(q: { desde?: string; hasta?: string }, now = new Date()): [string, string] {
  const [d0, d1] = last30Days(now);
  let a = q.desde && ISO.test(q.desde) ? q.desde : d0;
  let b = q.hasta && ISO.test(q.hasta) ? q.hasta : d1;
  if (b < a) [a, b] = [b, a];
  return [a, b];
}

export function parseSort(q: { orden?: string; dir?: string }): { sort: SortKey; desc: boolean } {
  const sort = (q.orden && SORT_KEYS.has(q.orden) ? q.orden : "pct_hechos") as SortKey;
  return { sort, desc: q.dir !== "asc" };
}

/** Ordena por una columna. Las personas sin datos siempre van al final. */
export function sortRows(rows: Fila[], sort: SortKey, desc: boolean): Fila[] {
  const present = rows.filter((r) => r[sort] !== null && r[sort] !== undefined);
  const empty = rows.filter((r) => r[sort] === null || r[sort] === undefined);
  present.sort((x, y) => {
    const a = x[sort] as number | string;
    const b = y[sort] as number | string;
    const c = typeof a === "string" ? a.localeCompare(b as string, "es") : (a as number) - (b as number);
    return desc ? -c : c;
  });
  return [...present, ...empty];
}

export function fmtDays(r: Pick<Fila, "dias_reporte" | "dias_disponibles" | "tasa_reporte" | "dias_pto">): string {
  let s = `${r.dias_reporte}/${r.dias_disponibles}`;
  s += r.tasa_reporte !== null ? ` (${fmtNum(r.tasa_reporte)}%)` : " (-)";
  if (r.dias_pto) s += ` (${r.dias_pto} ${r.dias_pto === 1 ? "día" : "días"} de PTO)`;
  return s;
}

export function fmtRatio(n: number, d: number, pct: number | null): string {
  return pct !== null ? `${n} de ${d} (${fmtNum(pct)}%)` : "-";
}

export function fmtCountPct(n: number, pct: number | null): string {
  return pct === null ? "-" : `${n} (${fmtNum(pct)}%)`;
}

/** 50 -> "50.0", igual que Python. */
export function fmtNum(v: number | null): string {
  return v === null ? "-" : v.toFixed(1);
}

export function libreNote(days: { day: string; format: string }[]): string | null {
  const libre = days.filter((d) => d.format === "libre").map((d) => d.day).sort();
  if (!libre.length) return null;
  return (
    `El rango incluye ${libre.length} días en formato libre (${libre[0]} a ${libre[libre.length - 1]}). ` +
    "Esos días cuentan solo en la columna de días con reporte."
  );
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows: Fila[], desde: string, hasta: string, note: string | null): string {
  const head = ["persona", "dias_con_reporte", "dias_disponibles", "dias_pto", "pct_dias_reporte",
    "compromisos_por_dia", "ayer_hechos", "ayer_marcados", "pct_hechos", "sin_tocar", "pct_sin_tocar",
    "alertas_tercer_dia", "lineas_sin_marca", "desde", "hasta"];
  const lines = [head.join(",")];
  for (const r of rows) {
    lines.push([r.persona, r.dias_reporte, r.dias_disponibles, r.dias_pto, r.tasa_reporte, r.compromisos_por_dia,
      r.hechos, r.marcados, r.pct_hechos, r.sin_tocar, r.pct_sin_tocar, r.alertas_tercer_dia, r.sin_marca,
      desde, hasta].map(csvCell).join(","));
  }
  if (note) lines.push("", csvCell(note));
  lines.push("", csvCell(DISCLAIMER));
  // BOM para que Excel abra bien las tildes.
  return "﻿" + lines.join("\r\n") + "\r\n";
}
