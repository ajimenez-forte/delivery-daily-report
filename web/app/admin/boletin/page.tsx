import Link from "next/link";
import { requireAdmin } from "@/lib/auth";
import { todayBogota } from "@/lib/carga";
import { createClient } from "@/lib/supabase/server";

type C = { id: number; section: string; text: string; mark: string | null; is_extra: number; streak_days: number;
  monday_url: string | null; note: string | null; due_date: string | null };
type R = { id: number; format: string; raw_text: string | null; blockers_status: string | null;
  people: { id: number; name: string }; commitments: C[]; operation_items: { text: string }[];
  blockers: { text: string; decision_level: number | null }[] };

const MARK: Record<string, string> = { hecho: "✅", pendiente: "🔄", no_tocado: "⬜" };

export default async function Boletin({ searchParams }: { searchParams: Promise<{ dia?: string }> }) {
  await requireAdmin();
  const q = await searchParams;
  const supabase = await createClient();
  const { data: lastDay } = await supabase.from("days").select("day").lte("day", todayBogota()).order("day", { ascending: false }).limit(1).maybeSingle();
  const dia = q.dia && /^\d{4}-\d{2}-\d{2}$/.test(q.dia) ? q.dia : lastDay?.day ?? todayBogota();

  const [{ data: reps, error }, { data: missing }, { data: prev }, { data: next }] = await Promise.all([
    supabase.from("reports")
      .select("id, format, raw_text, blockers_status, people(id, name), commitments(id, section, text, mark, is_extra, streak_days, monday_url, note, due_date), operation_items(text), blockers(text, decision_level), days!inner(day)")
      .eq("days.day", dia),
    supabase.rpc("boletin_sin_reporte", { p_dia: dia }),
    supabase.from("days").select("day").lt("day", dia).order("day", { ascending: false }).limit(1).maybeSingle(),
    supabase.from("days").select("day").gt("day", dia).order("day").limit(1).maybeSingle(),
  ]);
  if (error) throw new Error(error.message);
  const reports = ((reps ?? []) as unknown as R[]).sort((a, b) => a.people.name.localeCompare(b.people.name, "es"));

  const repeated = reports.flatMap((r) => r.commitments.filter((c) => c.section === "hoy" && c.streak_days >= 2)
    .map((c) => ({ persona: r.people.name, ...c }))).sort((a, b) => b.streak_days - a.streak_days);
  const blockers = reports.flatMap((r) => r.blockers.map((b) => ({ persona: r.people.name, ...b })))
    .sort((a, b) => (b.decision_level ?? 0) - (a.decision_level ?? 0));

  return (
    <>
      <h1>Boletín del día · {dia}</h1>
      <p className="row">
        {prev ? <Link href={`/admin/boletin?dia=${prev.day}`}>← {prev.day}</Link> : null}
        {next ? <Link href={`/admin/boletin?dia=${next.day}`}>{next.day} →</Link> : null}
      </p>

      <h2>Sin reporte</h2>
      <p>{(missing ?? []).length ? (missing ?? []).map((m: { persona: string }) => m.persona).join(", ") : "Todos reportaron (sin contar PTO ni días no hábiles)."}</p>

      <h2>Compromisos repetidos</h2>
      {repeated.length ? <ul>{repeated.map((c) => (
        <li key={c.id}>{c.persona}: «{c.text}» · {c.streak_days} días seguidos
          {c.streak_days >= 3 ? <span className="warn"> ⚠️ {c.due_date || "sin fecha nueva"}</span> : null}</li>
      ))}</ul> : <p className="muted">Ninguno.</p>}

      <h2>Bloqueos</h2>
      {blockers.length ? <ul>{blockers.map((b, i) => (
        <li key={i} className={b.decision_level && b.decision_level >= 4 ? "danger" : ""}>
          Nivel {b.decision_level ?? "sin nivel"} · {b.persona}: {b.text}</li>
      ))}</ul> : <p className="muted">Nadie reportó bloqueos.</p>}

      <h2>Reportes</h2>
      {reports.map((r) => {
        const ayer = r.commitments.filter((c) => c.section === "ayer" && !c.is_extra);
        const extras = r.commitments.filter((c) => c.section === "ayer" && c.is_extra);
        const hoy = r.commitments.filter((c) => c.section === "hoy");
        return (
          <div className="card" key={r.id}>
            <h3 style={{ margin: "4px 0" }}>{r.people.name}</h3>
            {r.format === "libre" ? <div className="raw">{r.raw_text}</div> : (
              <>
                <p><b>Ayer</b></p>
                <ul>{ayer.map((c) => <li key={c.id}>{c.mark ? MARK[c.mark] : "·"} {c.text}{c.note ? <span className="muted"> ({c.note})</span> : null}</li>)}</ul>
                {extras.length ? <><p><b>Extras</b></p><ul>{extras.map((c) => <li key={c.id}>{c.mark ? MARK[c.mark] : "·"} {c.text}</li>)}</ul></> : null}
                <p><b>Compromisos de hoy</b></p>
                <ul>{hoy.map((c) => <li key={c.id}>{c.text}{c.monday_url ? <> · <a href={c.monday_url}>Monday</a></> : <span className="muted"> · sin link</span>}{c.due_date ? ` · cierre: ${c.due_date}` : ""}</li>)}</ul>
                <p><b>Operación:</b> {r.operation_items.map((o) => o.text).join(" · ") || <span className="muted">no reportó</span>}</p>
                <p><b>Bloqueos:</b> {r.blockers.length ? r.blockers.map((b) => `${b.text}${b.decision_level ? ` (nivel ${b.decision_level})` : ""}`).join(" · ")
                  : r.blockers_status === "sin_bloqueos" ? "Sin bloqueos" : <span className="warn">campo ausente</span>}</p>
              </>
            )}
          </div>
        );
      })}
    </>
  );
}
