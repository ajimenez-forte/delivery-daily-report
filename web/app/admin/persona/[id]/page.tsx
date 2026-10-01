import Link from "next/link";
import { notFound } from "next/navigation";
import { requireAdmin } from "@/lib/auth";
import { DISCLAIMER, fmtCountPct, fmtDays, fmtRatio, parseRange } from "@/lib/carga";
import { createClient } from "@/lib/supabase/server";
import { WeeklyChart } from "@/components/WeeklyChart";
import { guardarNota } from "./actions";

type Semana = {
  semana: string; desde: string; hasta: string; dias_libre: number; dias_reporte: number; dias_disponibles: number;
  dias_pto: number; tasa_reporte: number | null; hechos: number; marcados: number; pct_hechos: number | null;
  sin_tocar: number; pct_sin_tocar: number | null;
};

export default async function Persona({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ desde?: string; hasta?: string }>;
}) {
  await requireAdmin();
  const id = Number((await params).id);
  if (!Number.isInteger(id)) notFound();
  const [desde, hasta] = parseRange(await searchParams);
  const supabase = await createClient();
  const { data: person } = await supabase.from("people").select("id, name").eq("id", id).maybeSingle();
  if (!person) notFound();

  const [{ data: total }, { data: weeks }, { data: note }] = await Promise.all([
    supabase.rpc("carga_cumplimiento", { p_desde: desde, p_hasta: hasta }).eq("person_id", id),
    supabase.rpc("evolucion_semanal", { p_person: id, p_desde: desde, p_hasta: hasta }),
    // RLS solo devuelve la nota del admin que la escribió.
    supabase.from("admin_notes").select("body, updated_at").eq("person_id", id).maybeSingle(),
  ]);
  const r = total?.[0];
  const ws = (weeks ?? []) as Semana[];
  const back = new URLSearchParams({ desde, hasta }).toString();
  const save = guardarNota.bind(null, id);

  return (
    <>
      <p><Link href={`/admin/carga?${back}`}>← Carga y cumplimiento</Link></p>
      <h1>{person.name}</h1>
      <form className="row" method="get">
        <label>Desde <input type="date" name="desde" defaultValue={desde} /></label>
        <label>Hasta <input type="date" name="hasta" defaultValue={hasta} /></label>
        <button>Aplicar</button>
      </form>
      {r ? (
        <p>{fmtDays(r)} · Ayer hechos {fmtRatio(r.hechos, r.marcados, r.pct_hechos)} · sin tocar {fmtCountPct(r.sin_tocar, r.pct_sin_tocar)}</p>
      ) : null}

      <h2>Evolución semanal</h2>
      <p className="muted">Semanas de lunes a domingo, recortadas al rango. Los porcentajes de Ayer usan solo días con formato de marcas.</p>
      {ws.length ? (
        <div className="multiples">
          <WeeklyChart title="Días con reporte (%)" points={ws.map((w) => ({ semana: w.semana, valor: w.tasa_reporte,
            detalle: `${w.dias_reporte}/${w.dias_disponibles}${w.dias_pto ? `, PTO ${w.dias_pto}` : ""}` }))} />
          <WeeklyChart title="Ítems de Ayer hechos (%)" points={ws.map((w) => ({ semana: w.semana, valor: w.pct_hechos,
            detalle: `${w.hechos} de ${w.marcados}` }))} />
          <WeeklyChart title="Ítems sin tocar (%)" points={ws.map((w) => ({ semana: w.semana, valor: w.pct_sin_tocar,
            detalle: `${w.sin_tocar} de ${w.marcados}` }))} />
        </div>
      ) : <p className="muted">No hay semanas con días de Daily en este rango.</p>}
      <div className="scroll">
        <table>
          <thead><tr><th>Semana</th><th className="n">Días con reporte</th><th className="n">Ayer hechos</th><th className="n">Sin tocar</th><th></th></tr></thead>
          <tbody>
            {ws.map((w) => (
              <tr key={w.semana}>
                <td>{w.desde} a {w.hasta}</td>
                <td className="n">{fmtDays(w)}</td>
                <td className="n">{fmtRatio(w.hechos, w.marcados, w.pct_hechos)}</td>
                <td className="n">{fmtCountPct(w.sin_tocar, w.pct_sin_tocar)}</td>
                <td>{w.dias_libre ? `texto libre: ${w.dias_libre} días` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">{DISCLAIMER}</p>

      <h2>Notas privadas</h2>
      <p className="muted">Solo tú las ves y las editas. La base de datos no se las muestra a nadie más, ni a otro admin.</p>
      <form action={save}>
        <textarea name="body" defaultValue={note?.body ?? ""} />
        <p className="row">
          <button className="primary">Guardar notas</button>
          <span className="muted">{note?.updated_at ? `Última edición: ${note.updated_at}` : ""}</span>
        </p>
      </form>
    </>
  );
}
